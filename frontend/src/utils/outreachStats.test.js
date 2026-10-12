import test from 'node:test';
import assert from 'node:assert/strict';

import {
  computeDashboardStats,
  formatReplyRate,
  canSendMessage,
  deriveSequenceState,
} from './outreachStats.js';

// FIX 1 / FIX 6.1 — dashboard uses the real API field names.
test('dashboard stats use followUp1Sent + followUp2Sent and replied', () => {
  const dashboard = computeDashboardStats({
    initialSent: 5,
    followUp1Sent: 2,
    followUp2Sent: 1,
    replied: 3,
    replyRate: '60.0%',
    followUpsPending: 4,
  });
  assert.equal(dashboard.initialSent, 5);
  assert.equal(dashboard.followUpsSent, 3);
  assert.equal(dashboard.repliesReceived, 3);
  assert.equal(dashboard.followUpsPending, 4);
});

test('dashboard ignores non-existent legacy field names', () => {
  const dashboard = computeDashboardStats({
    totalFollowUpsSent: 99,
    repliesReceived: 42,
    followUpsPending: 7,
  });
  assert.equal(dashboard.followUpsSent, 0);
  assert.equal(dashboard.repliesReceived, 0);
  assert.equal(dashboard.followUpsPending, 7);
});

test('missing stats are handled safely', () => {
  const dashboard = computeDashboardStats(null);
  assert.equal(dashboard.followUpsSent, 0);
  assert.equal(dashboard.repliesReceived, 0);
  assert.equal(dashboard.followUpsPending, 0);
  assert.equal(dashboard.replyRateText, '0%');
});

// FIX 6.2 — never render a double percentage sign.
test('reply rate never produces a double percent sign', () => {
  assert.equal(formatReplyRate('0.0%'), '0.0%');
  assert.equal(formatReplyRate('60.0%'), '60.0%');
  assert.equal(formatReplyRate('12.5'), '12.5%');
  assert.equal(formatReplyRate(0), '0%');
  assert.equal(formatReplyRate(''), '0%');
  assert.equal(formatReplyRate(undefined), '0%');
  assert.equal(formatReplyRate(null), '0%');
  for (const value of ['0.0%', '100.0%', '12.5']) {
    assert.ok(!formatReplyRate(value).includes('%%'), `unexpected %% for ${value}`);
  }
});

// FIX 6.12 — sent messages cannot be resent from the UI.
test('sent and in-flight messages cannot be sent again', () => {
  assert.equal(canSendMessage({ status: 'sent' }), false);
  assert.equal(canSendMessage({ status: 'sending' }), false);
  assert.equal(canSendMessage({ status: 'draft' }), true);
  assert.equal(canSendMessage({ status: 'approved' }), true);
  assert.equal(canSendMessage({ status: 'scheduled' }), true);
  assert.equal(canSendMessage({ status: 'failed' }), true);
  assert.equal(canSendMessage(null), false);
});

// FIX 3 — sequence state drives the corrected scheduling copy.
test('sequence state reflects inactivity, activation and replies', () => {
  assert.equal(deriveSequenceState([]), 'none');
  assert.equal(
    deriveSequenceState([{ step: 1, status: 'draft' }, { step: 2, status: 'draft' }]),
    'inactive'
  );
  assert.equal(
    deriveSequenceState([{ step: 1, status: 'approved' }, { step: 2, status: 'draft' }]),
    'approved'
  );
  assert.equal(
    deriveSequenceState([
      { step: 1, status: 'sent' },
      { step: 2, status: 'scheduled', delayDays: 10 },
    ]),
    'active'
  );
  assert.equal(
    deriveSequenceState([
      { step: 1, status: 'sent' },
      { step: 2, status: 'sent' },
      { step: 3, status: 'sent' },
    ]),
    'completed'
  );
  assert.equal(
    deriveSequenceState([
      { step: 1, status: 'sent' },
      { step: 2, status: 'draft', cancelledReason: 'prospect_replied' },
    ]),
    'stopped'
  );
});
