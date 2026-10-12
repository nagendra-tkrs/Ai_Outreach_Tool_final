// Pure, testable helpers for the Outbox dashboard, message actions, and the
// Company Detail drip schedule status. Keeping this logic out of the JSX lets
// the frontend regression suite pin the exact API field names and formatting
// rules without a DOM test runner.

const toCount = (value) => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0;
  if (value === null || value === undefined || value === '') return 0;
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
};

// The backend returns `replyRate` already formatted as a string (e.g. "0.0%").
// Never append a second "%".
export function formatReplyRate(replyRate) {
  if (replyRate === null || replyRate === undefined) return '0%';
  const text = String(replyRate).trim();
  if (!text) return '0%';
  return text.endsWith('%') ? text : `${text}%`;
}

// Maps the real `/outreach/stats` response onto the dashboard cards.
//   Follow-ups Sent    = followUp1Sent + followUp2Sent
//   Replies Received   = replied
//   Follow-ups Pending = followUpsPending (armed record follow-ups)
export function computeDashboardStats(stats) {
  const s = stats || {};
  return {
    initialSent: toCount(s.initialSent),
    followUpsSent: toCount(s.followUp1Sent) + toCount(s.followUp2Sent),
    followUpsPending: toCount(s.followUpsPending),
    repliesReceived: toCount(s.replied),
    replyRateText: formatReplyRate(s.replyRate),
  };
}

// A sent, in-flight, or quarantined message must never offer Send/Resend.
export function canSendMessage(message) {
  if (!message) return false;
  if (message.quarantined === true || Boolean(message.quarantine && message.quarantine.active === true)) {
    return false;
  }
  return message.status !== 'sent' && message.status !== 'sending';
}

// Derive the drip sequence state from the company's outreach messages.
// Returns: none | inactive | approved | active | completed | stopped
export function deriveSequenceState(messages) {
  const list = Array.isArray(messages) ? messages.filter(Boolean) : [];
  if (list.length === 0) return 'none';
  if (list.some((m) => m.cancelledReason)) return 'stopped';

  const stepOf = (n) => list.find((m) => m.step === n);
  const allSent = [1, 2, 3].every((n) => stepOf(n)?.status === 'sent');
  if (allSent) return 'completed';

  const followUpsArmed = [2, 3].some((n) => stepOf(n)?.status === 'scheduled');
  if (followUpsArmed) return 'active';

  const step1 = stepOf(1);
  if (step1 && (step1.status === 'approved' || step1.status === 'sent')) return 'approved';
  return 'inactive';
}

export const SEQUENCE_STATE_META = {
  none: { label: 'No sequence generated', className: 'bg-slate-100 text-slate-600 border-slate-200' },
  inactive: { label: 'Inactive — drafts only, nothing scheduled', className: 'bg-slate-100 text-slate-600 border-slate-200' },
  approved: { label: 'Step 1 approved — awaiting manual send', className: 'bg-blue-50 text-blue-700 border-blue-200' },
  active: { label: 'Active — automatic follow-ups armed', className: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
  completed: { label: 'Completed — all steps sent', className: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  stopped: { label: 'Stopped — prospect replied, follow-ups cancelled', className: 'bg-rose-50 text-rose-700 border-rose-200' },
};
