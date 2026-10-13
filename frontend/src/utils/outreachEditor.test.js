import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import {
  applyLocalEdit,
  describeRecipientSync,
  describeScheduleResult,
  findInvalidEmails,
  getActiveStepMessage,
  htmlToPlainText,
  isLockedMessage,
  isValidEmail,
  mergeServerMessages,
  resolveStepMessage,
  shouldRefetchAfterSave,
} from './outreachEditor.js';

const step = (n, extra = {}) => ({
  _id: `m${n}`,
  step: n,
  subject: `Step ${n} subject`,
  bodyHtml: `<p>Step ${n} body</p>`,
  bodyText: `Step ${n} body`,
  recipientEmail: 'orig@example.com',
  ccRecipients: [],
  bccRecipients: [],
  status: 'draft',
  ...extra,
});

// --- body text stays in lockstep with the edited HTML -----------------------
test('editing bodyHtml derives bodyText so dispatch text matches the editor', () => {
  const edited = applyLocalEdit(step(1), { bodyHtml: '<p>Hello <strong>World</strong></p><br/>Bye' });
  assert.equal(edited.bodyText, 'Hello World\nBye');
  assert.equal(edited.isManuallyEdited, true);
});

test('htmlToPlainText strips tags, converts breaks and decodes entities', () => {
  assert.equal(htmlToPlainText('<p>A &amp; B</p><p>C</p>'), 'A & B\nC');
  assert.equal(htmlToPlainText('<div>x</div><div>y</div>'), 'x\ny');
  assert.equal(htmlToPlainText(''), '');
  assert.equal(htmlToPlainText(null), '');
});

// --- ROOT CAUSE A: navigation must not reset/refresh Step 1 -----------------
test('regression: switching Step 1 -> Step 2 -> Step 1 preserves unsaved edits', () => {
  const server = [step(1), step(2), step(3)];

  // User edits Step 1 (unsaved).
  const editedStep1 = applyLocalEdit(server[0], { subject: 'UNSAVED STEP 1' });
  const drafts = { 1: editedStep1 };

  // OLD buggy behaviour: pick straight from the server list -> edit is lost.
  const buggy = server.find((m) => m.step === 1);
  assert.equal(buggy.subject, 'Step 1 subject');

  // NEW behaviour: each step resolves its own working copy.
  const onStep2 = resolveStepMessage(drafts, server, 2);
  assert.equal(onStep2.subject, 'Step 2 subject'); // independent content
  const backOnStep1 = resolveStepMessage(drafts, server, 1);
  assert.equal(backOnStep1.subject, 'UNSAVED STEP 1'); // preserved
});

test('each step keeps independent subject/body/recipient', () => {
  const server = [step(1), step(2), step(3)];
  const drafts = {
    1: applyLocalEdit(server[0], { subject: 'S1', bodyHtml: '<p>B1</p>' }),
    2: applyLocalEdit(server[1], { subject: 'S2', bodyHtml: '<p>B2</p>' }),
    3: applyLocalEdit(server[2], { subject: 'S3', bodyHtml: '<p>B3</p>' }),
  };
  assert.equal(resolveStepMessage(drafts, server, 1).bodyText, 'B1');
  assert.equal(resolveStepMessage(drafts, server, 2).bodyText, 'B2');
  assert.equal(resolveStepMessage(drafts, server, 3).bodyText, 'B3');
});

// --- ROOT CAUSE A: refetch must not clobber dirty local fields --------------
test('mergeServerMessages keeps dirty steps and refreshes clean steps', () => {
  const serverOld = [step(1), step(2, { status: 'scheduled' })];
  const drafts = { 1: applyLocalEdit(serverOld[0], { subject: 'DIRTY EDIT' }), 2: serverOld[1] };
  const dirty = { 1: true };

  // Server now returns different content for both steps.
  const serverNew = [step(1, { subject: 'server over wrote' }), step(2, { status: 'sent' })];
  const merged = mergeServerMessages(drafts, dirty, serverNew);

  assert.equal(merged[1].subject, 'DIRTY EDIT'); // dirty step preserved
  assert.equal(merged[2].status, 'sent'); // clean step refreshed
});

test('resolveStepMessage falls back to server data when no draft exists', () => {
  const server = [step(1), step(2)];
  assert.equal(resolveStepMessage({}, server, 2).subject, 'Step 2 subject');
  assert.equal(resolveStepMessage({}, server, 3), null);
});

// --- ROOT CAUSE D: recipientSync must be read from the response BODY --------
test('describeRecipientSync reports paused, conflict, updated, invalid and none', () => {
  assert.equal(describeRecipientSync(null), null);

  const paused = describeRecipientSync({ updated: 0, paused: 2, conflicts: [] });
  assert.equal(paused.tone, 'warning');
  assert.match(paused.message, /paused for manual review/i);

  const conflict = describeRecipientSync({
    updated: 1,
    paused: 0,
    skippedInvalid: false,
    conflicts: [{ messageId: 'm2', step: 2, recipientEmail: 'other@x.com' }],
  });
  assert.equal(conflict.tone, 'warning');
  assert.match(conflict.message, /different recipient/i);
  assert.match(conflict.message, /1 follow-up\(s\) synchronized/);

  const updated = describeRecipientSync({ updated: 2, paused: 0, conflicts: [] });
  assert.equal(updated.tone, 'success');
  assert.match(updated.message, /2 unsent follow-up\(s\)/);

  const invalid = describeRecipientSync({ updated: 0, paused: 0, skippedInvalid: true, conflicts: [] });
  assert.equal(invalid.tone, 'warning');
  assert.match(invalid.message, /not a valid email/i);

  const none = describeRecipientSync({ updated: 0, paused: 0, skippedInvalid: false, conflicts: [] });
  assert.equal(none, null);
});

test('regression: recipientSync lives on the response body, not body.data', () => {
  // Simulates the axios interceptor unwrapping to the HTTP body.
  const responseBody = {
    success: true,
    data: { _id: 'm1', step: 1, recipientEmail: 'new@x.com' },
    recipientSync: { updated: 2, conflicts: [] },
    message: 'Step 1 recipient updated',
  };
  // The buggy read (body.data.recipientSync) yields undefined...
  assert.equal(responseBody.data.recipientSync, undefined);
  // ...the correct read surfaces the payload.
  const sync = responseBody.recipientSync ?? responseBody.data?.recipientSync ?? null;
  assert.deepEqual(sync, { updated: 2, conflicts: [] });
  assert.equal(describeRecipientSync(sync).tone, 'success');
});

// --- the actual root cause: a successful sync must refresh Steps 2/3 ---------
test('regression: successful Step-1 recipient sync must trigger a list refresh', () => {
  // Exact `recipientSync` the backend returns when Steps 2/3 were rewritten
  // (observed in production: {updated: 2, paused: 0, skippedInvalid: false,
  // conflicts: []}). The PUT response echoes ONLY Step 1, so without a refetch
  // Steps 2/3 keep their pre-sync recipient in `outreachMessages`/`draftsByStep`
  // and the editor shows a stale address.
  const sync = { updated: 2, paused: 0, skippedInvalid: false, conflicts: [] };
  assert.equal(shouldRefetchAfterSave({ isSent: false, sync }), true);
});

test('shouldRefetchAfterSave refreshes on server-side state changes, skips no-ops', () => {
  // Sent correction / pause / conflict all rewrite rows we must re-read.
  assert.equal(shouldRefetchAfterSave({ isSent: true, sync: null }), true);
  assert.equal(
    shouldRefetchAfterSave({ isSent: false, sync: { updated: 0, paused: 3, conflicts: [] } }),
    true,
  );
  assert.equal(
    shouldRefetchAfterSave({ isSent: false, sync: { updated: 0, paused: 0, conflicts: [{ step: 2 }] } }),
    true,
  );
  assert.equal(
    shouldRefetchAfterSave({ isSent: false, sync: { updated: 1, paused: 0, conflicts: [] } }),
    true,
  );
  // Content-only save (no `recipientSync` key in the response body) — nothing
  // changed server-side, so no refetch is needed.
  assert.equal(shouldRefetchAfterSave({ isSent: false, sync: null }), false);
  // Invalid recipient: saved on Step 1, follow-ups untouched → no refetch.
  assert.equal(
    shouldRefetchAfterSave({ isSent: false, sync: { updated: 0, paused: 0, skippedInvalid: true, conflicts: [] } }),
    false,
  );
});

test('regression: CompanyDetail routes the save response through shouldRefetchAfterSave', async () => {
  // The bug lived in the component's inline condition, which omitted
  // `sync.updated`. This harness has no DOM runner, so assert the wiring:
  // the component must call the helper, and must not carry the old condition.
  const src = await readFile(new URL('../pages/CompanyDetail.jsx', import.meta.url), 'utf8');
  assert.match(src, /shouldRefetchAfterSave\(\s*\{\s*isSent,\s*sync\s*\}\s*\)/);
  assert.doesNotMatch(src, /isSent\s*\|\|\s*sync\?\.paused/);
});

// --- CC synchronization (Step 1 -> unsent Step 2/3) -------------------------
test('regression: a CC-only Step 1 sync must refresh Steps 2/3', () => {
  // The backend reports CC propagation as `ccUpdated`. Without it in the
  // refetch condition the editor keeps the pre-sync CC chips in local state —
  // the same "synchronization did not work" illusion as the recipient bug.
  const ccSync = { updated: 0, paused: 0, skippedInvalid: false, conflicts: [], ccUpdated: 2 };
  assert.equal(shouldRefetchAfterSave({ isSent: false, sync: ccSync }), true);

  const feedback = describeRecipientSync(ccSync);
  assert.equal(feedback.tone, 'success');
  assert.match(feedback.message, /CC recipients synchronized to 2 unsent follow-up\(s\)/i);
});

test('describeRecipientSync mentions CC alongside a recipient update', () => {
  const both = describeRecipientSync({
    updated: 2, paused: 0, skippedInvalid: false, conflicts: [], ccUpdated: 2,
  });
  assert.equal(both.tone, 'success');
  assert.match(both.message, /2 unsent follow-up\(s\)/);
  assert.match(both.message, /CC recipients synchronized/);

  // No CC change -> the toast stays recipient-only (no phantom CC claim).
  const noCc = describeRecipientSync({ updated: 2, paused: 0, skippedInvalid: false, conflicts: [] });
  assert.equal(noCc.tone, 'success');
  assert.doesNotMatch(noCc.message, /CC recipients/);
  // ...and a save with no signal at all still reports nothing.
  assert.equal(
    describeRecipientSync({ updated: 0, paused: 0, skippedInvalid: false, conflicts: [], ccUpdated: 0 }),
    null,
  );
});

test('refresh after a CC sync shows the new CC without clobbering dirty drafts', () => {
  const serverOld = [step(1), step(2), step(3)];
  const drafts = {
    1: serverOld[0],
    2: serverOld[1],
    3: applyLocalEdit(serverOld[2], { subject: 'UNSAVED STEP 3' }),
  };
  const dirty = { 3: true };

  // The server now holds the CC-synced list for Steps 2 and 3.
  const serverNew = [
    step(1),
    step(2, { ccRecipients: ['ops@tksr.example', 'legal@tksr.example'] }),
    step(3, { ccRecipients: ['ops@tksr.example', 'legal@tksr.example'], subject: 'server subject' }),
  ];
  const merged = mergeServerMessages(drafts, dirty, serverNew);

  // The clean follow-up displays the synchronized CC, keeping its own copy...
  assert.deepEqual(merged[2].ccRecipients, ['ops@tksr.example', 'legal@tksr.example']);
  assert.equal(merged[2].subject, 'Step 2 subject');
  assert.equal(merged[2].bodyHtml, '<p>Step 2 body</p>');
  // ...while a step with unsaved edits keeps its own subject/body intact.
  assert.equal(merged[3].subject, 'UNSAVED STEP 3');
  assert.equal(merged[3].bodyHtml, '<p>Step 3 body</p>');
});

test('regression: the save payload posts ccRecipients for unsent steps', async () => {
  // Root cause check: the request side must actually carry the CC list, and the
  // response must be read off the body before the refetch decision is made.
  const src = await readFile(new URL('../pages/CompanyDetail.jsx', import.meta.url), 'utf8');
  assert.match(src, /ccRecipients:\s*editingMessage\.ccRecipients\s*\|\|\s*\[\]/);
  assert.match(src, /const sync = res\?\.recipientSync \?\? res\?\.data\?\.recipientSync \?\? null/);
  assert.match(src, /describeRecipientSync\(sync\)/);
});

// --- draft manual-edit workflow: address validation ------------------------

test('isValidEmail accepts valid/blank addresses and rejects malformed ones', () => {
  assert.equal(isValidEmail('a.person+tag@sub.domain.co'), true);
  assert.equal(isValidEmail('Prospect@Company.COM'), true);
  assert.equal(isValidEmail(''), true);
  assert.equal(isValidEmail('   '), true);
  assert.equal(isValidEmail(null), true);
  assert.equal(isValidEmail(undefined), true);
  assert.equal(isValidEmail('not-an-email'), false);
  assert.equal(isValidEmail('two@@cc.example'), false);
  assert.equal(isValidEmail('spaces in@example.com'), false);
  assert.equal(isValidEmail('missing-tld@example.'), false);
});

test('findInvalidEmails reports exactly the malformed To/CC/BCC entries', () => {
  assert.deepEqual(
    findInvalidEmails({
      recipientEmail: 'ok@example.com',
      ccRecipients: ['fine@example.com', 'bad@@x.co'],
    }),
    ['bad@@x.co'],
  );
  assert.deepEqual(findInvalidEmails({}), []);
  assert.deepEqual(
    findInvalidEmails({ recipientEmail: '', ccRecipients: [], bccRecipients: ['nope'] }),
    ['nope'],
  );
  // A non-list CC value is ignored here; the backend rejects the shape with 400.
  assert.deepEqual(findInvalidEmails({ ccRecipients: 'not-a-list' }), []);
});

test('regression: CompanyDetail blocks the save on malformed addresses before PUT', async () => {
  const src = await readFile(new URL('../pages/CompanyDetail.jsx', import.meta.url), 'utf8');
  assert.match(src, /findInvalidEmails\(\{/);
  assert.match(src, /Cannot save: invalid email address/);
});

// --- follow-up editor: sent/locked display consistency ---------------------

const msg = (step, status, extra = {}) => ({
  _id: `m${step}`,
  step,
  status,
  subject: `Step ${step} subject`,
  bodyHtml: `<p>Step ${step} body</p>`,
  recipientEmail: 'prospect@example.com',
  ...extra,
});

test('isLockedMessage distinguishes sent history from drafts', () => {
  // Genuine sent history -> locked.
  assert.equal(isLockedMessage(msg(1, 'sent')), true);
  // Drafts -> not locked.
  assert.equal(isLockedMessage(msg(2, 'draft')), false);
  assert.equal(isLockedMessage(msg(3, 'draft')), false);
  // No message -> not locked.
  assert.equal(isLockedMessage(null), false);
  assert.equal(isLockedMessage(undefined), false);
});

test('regression: Step 2 and Step 3 select their own drafts while Step 1 remains sent', () => {
  const serverMessages = [
    msg(1, 'sent'),
    msg(2, 'draft'),
    msg(3, 'draft'),
  ];
  const drafts = mergeServerMessages({}, {}, serverMessages);

  // Each step resolves to its OWN message (per-step drafts, no cross-talk).
  const step1 = resolveStepMessage(drafts, serverMessages, 1);
  const step2 = resolveStepMessage(drafts, serverMessages, 2);
  const step3 = resolveStepMessage(drafts, serverMessages, 3);
  assert.equal(step1.status, 'sent');
  assert.equal(step2.status, 'draft');
  assert.equal(step3.status, 'draft');

  // Banner/lock state per selected step: Step 1 locked, Steps 2/3 editable.
  assert.equal(isLockedMessage(step1), true);
  assert.equal(isLockedMessage(step2), false);
  assert.equal(isLockedMessage(step3), false);
});

test('getActiveStepMessage re-resolves a stale binding to the selected step', () => {
  const serverMessages = [
    msg(1, 'sent'),
    msg(2, 'draft'),
    msg(3, 'draft'),
  ];
  const drafts = mergeServerMessages({}, {}, serverMessages);

  // Bound message matches the selected step -> used as-is.
  const bound = msg(2, 'draft', { subject: 'locally edited' });
  assert.equal(
    getActiveStepMessage(drafts, serverMessages, 2, bound).subject,
    'locally edited',
  );

  // Stale binding (Step 1 sent) while Step 2 is selected -> re-resolves to the
  // Step 2 draft, so the sent banner can never appear.
  const stale = msg(1, 'sent');
  const active = getActiveStepMessage(drafts, serverMessages, 2, stale);
  assert.equal(active.step, 2);
  assert.equal(active.status, 'draft');
  assert.equal(isLockedMessage(active), false);

  // No usable message for the step -> falls back to the bound message.
  assert.equal(getActiveStepMessage({}, [], 3, stale), stale);
  assert.equal(getActiveStepMessage({}, [], 3, null), null);
});

test('regression: CompanyDetail gates banner, tab badge and pill on isLockedMessage', async () => {
  const src = await readFile(new URL('../pages/CompanyDetail.jsx', import.meta.url), 'utf8');
  // Banner uses the check on the active (selected-step) message.
  assert.match(src, /isLockedMessage\(activeMessage\) &&/);
  // Tab badge uses the check.
  assert.match(src, /const isSent = isLockedMessage\(stepMsg\)/);
  // Status pill + send button use the check.
  assert.match(src, /isLockedMessage\(editingMessage\) \? 'bg-emerald-100/);
  assert.match(src, /\{isLockedMessage\(editingMessage\) \? \(/);
  // The active message is derived with the stale-binding guard.
  assert.match(src, /getActiveStepMessage\(draftsByStep, outreachMessages, selectedStep, editingMessage\)/);
  // Raw status checks must not drive the sent banner any more.
  assert.doesNotMatch(src, /\{editingMessage\.status === 'sent' && \(/);
});

test('regression: no quarantine references remain in the frontend source', async () => {
  const compSrc = await readFile(new URL('../pages/CompanyDetail.jsx', import.meta.url), 'utf8');
  const outboxSrc = await readFile(new URL('../pages/Outbox.jsx', import.meta.url), 'utf8');
  const editorSrc = await readFile(new URL('./outreachEditor.js', import.meta.url), 'utf8');
  const statsSrc = await readFile(new URL('./outreachStats.js', import.meta.url), 'utf8');
  for (const src of [compSrc, outboxSrc, editorSrc, statsSrc]) {
    assert.doesNotMatch(src, /quarantin/i);
  }
});

test('regression: CompanyDetail protects active editor step from being clobbered by other step saves', async () => {
  const src = await readFile(new URL('../pages/CompanyDetail.jsx', import.meta.url), 'utf8');
  // Only updates editingMessage when selected step matches saved step
  assert.match(src, /if \(selectedStepRef\.current === savedStep\) \{\s*setEditingMessage\(updated\);/);
  // Synchronizes Step 1 recipient and CC to follow-up drafts without mutating locked/sent follow-ups
  assert.match(src, /if \(savedStep === 1 && sync\) \{/);
  assert.match(src, /!isLockedMessage\(followUp\)/);
});

test('describeScheduleResult reflects Step 1 sent state accurately', () => {
  const res = {
    data: [
      { step: 2, status: 'scheduled' },
      { step: 3, status: 'scheduled' },
    ],
  };
  const step1Sent = { step: 1, status: 'sent' };
  const feedback = describeScheduleResult(res, step1Sent);
  assert.equal(feedback.tone, 'success');
  assert.match(feedback.message, /Step 1 was previously sent/);
  assert.match(feedback.message, /Step 2 & Step 3 scheduled/);
});

test('describeScheduleResult reports un-sent Step 1 approval', () => {
  const res = {
    message: 'Step 1 approved for manual send; Step 2, 3 scheduled for automated drip',
    data: [
      { step: 1, status: 'approved' },
      { step: 2, status: 'scheduled' },
      { step: 3, status: 'scheduled' },
    ],
  };
  const step1Draft = { step: 1, status: 'draft' };
  const feedback = describeScheduleResult(res, step1Draft);
  assert.equal(feedback.tone, 'success');
  assert.match(feedback.message, /approved for manual send/);
});

test('describeScheduleResult reports warning when follow-ups revert to draft due to invalid recipient', () => {
  const res = {
    data: [
      { step: 2, status: 'draft' },
      { step: 3, status: 'draft' },
    ],
  };
  const feedback = describeScheduleResult(res, { step: 1, status: 'approved' });
  assert.equal(feedback.tone, 'warning');
  assert.match(feedback.message, /missing or invalid recipient/);
});


