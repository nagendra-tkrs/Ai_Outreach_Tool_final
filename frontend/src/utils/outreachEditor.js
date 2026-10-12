// Pure, testable helpers for the Company Detail outreach editor.
//
// The editor previously kept a single shared `editingMessage` for all three
// steps, so switching steps (or a background refetch) replaced it with the last
// saved server copy and silently discarded unsaved edits. These helpers make the
// intended behaviour explicit and unit-testable without a DOM test runner:
//
//   * each step owns its own working copy + dirty flag,
//   * a server refetch never clobbers a step with unsaved edits,
//   * a Step-1 recipient change reports exactly what happened to follow-ups.

// Convert the editable HTML body into the matching plain-text body so the
// dispatched text/plain part never drifts from what the operator sees.
export function htmlToPlainText(html) {
  if (!html) return '';
  let text = String(html);
  text = text.replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, '');
  text = text.replace(/<\/(p|div|h[1-6]|li|ul|ol|tr|table|blockquote)>/gi, '\n');
  text = text.replace(/<br\s*\/?>/gi, '\n');
  text = text.replace(/<[^>]*>/g, '');
  const entities = {
    '&nbsp;': ' ', '&amp;': '&', '&lt;': '<', '&gt;': '>',
    '&quot;': '"', '&#39;': "'",
  };
  text = text.replace(/&(nbsp|amp|lt|gt|quot|#39);/g, (m) => entities[m] || m);
  return text.replace(/\n{2,}/g, '\n').trim();
}

// Apply a local (unsaved) edit to a step's working message. Editing the HTML
// body also refreshes the derived plain-text body and marks the copy as manual.
export function applyLocalEdit(working, patch) {
  const next = { ...(working || {}), ...patch };
  if (Object.prototype.hasOwnProperty.call(patch, 'bodyHtml')) {
    next.bodyText = htmlToPlainText(next.bodyHtml);
    next.isManuallyEdited = true;
  }
  return next;
}

// Which message object should populate the editor for a step. An unsaved
// per-step draft always wins over the last saved server copy.
export function resolveStepMessage(draftsByStep, serverMessages, step) {
  const drafts = draftsByStep || {};
  if (drafts[step]) return drafts[step];
  const list = Array.isArray(serverMessages) ? serverMessages : [];
  return list.find((m) => m.step === step) || null;
}

// Merge a fresh server fetch into the per-step drafts WITHOUT overwriting any
// step that currently has unsaved (dirty) edits.
export function mergeServerMessages(draftsByStep, dirtyByStep, serverMessages) {
  const list = Array.isArray(serverMessages) ? serverMessages : [];
  const dirty = dirtyByStep || {};
  const next = { ...(draftsByStep || {}) };
  for (const m of list) {
    if (!m || dirty[m.step]) continue;
    next[m.step] = m;
  }
  return next;
}

// Human-readable description of the backend `recipientSync` payload.
//
// NOTE: the app's axios interceptor unwraps the HTTP response to its body, so
// callers must pass the response BODY (where `recipientSync` actually lives) —
// reading `body.data.recipientSync` is the bug this documents.
export function describeRecipientSync(sync) {
  if (!sync) return null;
  const conflicts = Array.isArray(sync.conflicts) ? sync.conflicts : [];
  const ccNote = sync.ccUpdated
    ? ` CC recipients synchronized to ${sync.ccUpdated} unsent follow-up(s).`
    : '';
  if (sync.paused) {
    return {
      tone: 'warning',
      message:
        'Step 1 recipient changed after send — Steps 2/3 were paused for manual review.' +
        ccNote,
    };
  }
  if (conflicts.length) {
    const synced = sync.updated || 0;
    return {
      tone: 'warning',
      message:
        `${synced} follow-up(s) synchronized; ${conflicts.length} follow-up(s) have a ` +
        'different recipient — flagged/paused for review, not overwritten.' +
        ccNote,
    };
  }
  if (sync.updated) {
    return {
      tone: 'success',
      message:
        `Step 1 recipient updated — ${sync.updated} unsent follow-up(s) synchronized ` +
        'to the new recipient.' + ccNote,
    };
  }
  if (sync.skippedInvalid) {
    return {
      tone: 'warning',
      message:
        'Recipient saved, but it is not a valid email — follow-ups were NOT synchronized.' +
        ccNote,
    };
  }
  if (sync.ccUpdated) {
    return {
      tone: 'success',
      message: `CC recipients synchronized to ${sync.ccUpdated} unsent follow-up(s).`,
    };
  }
  return null;
}

// Must a completed save re-fetch the company's outreach list?
//
// The PUT response only echoes the SAVED message (Step 1). When that save
// synchronizes the recipient or the CC list onto Step 2/3, the rewritten
// follow-up rows exist ONLY in the database. If we don't refetch,
// `outreachMessages` and `draftsByStep` keep the pre-sync values and the editor
// keeps showing the old recipient/CC — which reads as "synchronization did not
// work" even though the backend succeeded. Sending a message server-side
// (pause/conflict re-flags, sent history) needs the same canonical refresh.
export function shouldRefetchAfterSave({ isSent = false, sync = null } = {}) {
  if (isSent) return true;
  if (!sync) return false;
  const conflicts = Array.isArray(sync.conflicts) ? sync.conflicts : [];
  return Boolean(sync.updated || sync.paused || sync.ccUpdated || conflicts.length);
}

// ---------------------------------------------------------------------------
// Quarantined-draft manual-edit workflow: address validation helpers.
// Mirrors the backend's EMAIL_RE so a malformed To/CC/BCC is caught BEFORE the
// PUT and the operator gets one clear, actionable message. Blank / omitted
// values are allowed — a draft may be saved with an empty To and completed
// later (sending stays blocked server-side for quarantined drafts anyway).
// ---------------------------------------------------------------------------

const EMAIL_RE = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;

export function isValidEmail(value) {
  if (value === null || value === undefined) return true; // not provided
  const text = String(value).trim();
  if (text === '') return true; // cleared on purpose
  return EMAIL_RE.test(text);
}

// Return every malformed address in a save payload so the UI can block the
// save with one precise error listing exactly what to fix.
export function findInvalidEmails({ recipientEmail, ccRecipients, bccRecipients } = {}) {
  const invalid = [];
  if (!isValidEmail(recipientEmail)) invalid.push(String(recipientEmail).trim());
  for (const list of [ccRecipients, bccRecipients]) {
    if (!Array.isArray(list)) continue; // wrong shape -> backend rejects with 400
    for (const listEntry of list) {
      if (!isValidEmail(listEntry)) invalid.push(String(listEntry).trim());
    }
  }
  return invalid;
}

// ---------------------------------------------------------------------------
// Quarantined-draft manual-edit workflow: sent/locked display helpers.
//
// A message is treated as immutable "sent history" ONLY when it is genuinely
// sent AND not quarantined. A quarantined draft (status=draft,
// quarantined=true) stays fully editable — recipient, CC, recipient name,
// subject and body — even if a stale binding ever carried a non-draft status
// onto it. These helpers keep the banner, tab badge and status pill
// consistent with the message actually bound to the selected step.
// ---------------------------------------------------------------------------

export function isQuarantined(message) {
  if (!message || typeof message !== 'object') return false;
  return message.quarantined === true || Boolean(message.quarantine && message.quarantine.active === true);
}

// True only for genuine sent history: sent AND not quarantined. Gates the
// "Sent message — history preserved" banner, the SENT tab badge and the
// status pill so a quarantined draft is never presented as locked sent history.
export function isLockedMessage(message) {
  return Boolean(message) && message.status === 'sent' && !isQuarantined(message);
}

// Which message should the UI treat as active for a step? Prefer the bound
// editor message when it actually belongs to the selected step; otherwise
// re-resolve from the per-step drafts / server list so a stale binding can
// never show the wrong step's sent/locked state.
export function getActiveStepMessage(draftsByStep, serverMessages, selectedStep, editingMessage) {
  if (editingMessage && editingMessage.step === selectedStep) return editingMessage;
  const reResolved = resolveStepMessage(draftsByStep, serverMessages, selectedStep);
  return reResolved || editingMessage || null;
}
