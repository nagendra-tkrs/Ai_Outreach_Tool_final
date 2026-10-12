import { useState, useEffect } from 'react';
import api from '../api';

/**
 * QuarantineReleaseModal
 *
 * Dedicated modal for operator-controlled, authenticated release of a single
 * quarantined draft message.
 *
 * Security & Invariants:
 * - Admin key is held in component local state ONLY (never saved to localStorage,
 *   sessionStorage, cookies, or persisted state).
 * - Requires explicit confirmation of the exact Message ID, expected batch, and reason.
 * - Submits `X-Admin-Key` header to `POST /api/outreach/{id}/release-quarantine`.
 * - Releasing leaves the message in status="draft". It does NOT schedule or send.
 */
export default function QuarantineReleaseModal({
  isOpen,
  onClose,
  message,
  companyName,
  onSuccess,
}) {
  const [confirmId, setConfirmId] = useState('');
  const [expectedBatch, setExpectedBatch] = useState('quarantine-20261009');
  const [reason, setReason] = useState('');
  const [actor, setActor] = useState('operator');
  const [adminKey, setAdminKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  // Reset inputs when modal opens or target message changes
  useEffect(() => {
    if (isOpen && message) {
      setConfirmId(message._id || '');
      setExpectedBatch(message.quarantine?.batch || 'quarantine-20261009');
      setReason('');
      setActor('operator');
      setAdminKey('');
      setError('');
      setSuccessMsg('');
    } else {
      // Clear sensitive memory when closed
      setAdminKey('');
      setError('');
      setSuccessMsg('');
    }
  }, [isOpen, message]);

  if (!isOpen || !message) return null;

  const handleClose = () => {
    // Zero out key from memory on close
    setAdminKey('');
    setError('');
    setSuccessMsg('');
    onClose();
  };

  const handleRelease = async (e) => {
    e?.preventDefault();
    setError('');
    setSuccessMsg('');

    const targetId = message._id;
    if (!targetId) {
      setError('Missing target message ID.');
      return;
    }

    if (confirmId.trim() !== targetId) {
      setError(`Confirmation mismatch: typed ID does not match target message ID ${targetId}.`);
      return;
    }

    if (!adminKey.trim()) {
      setError('Admin Release Key is required for authorization.');
      return;
    }

    if (reason.trim().length < 5) {
      setError('A descriptive release reason (at least 5 characters) is required for the audit log.');
      return;
    }

    setLoading(true);
    try {
      const response = await api.post(
        `/outreach/${targetId}/release-quarantine`,
        {
          confirmMessageId: confirmId.trim(),
          expectedBatch: expectedBatch.trim(),
          reason: reason.trim(),
          actor: actor.trim() || 'operator',
        },
        {
          headers: {
            'X-Admin-Key': adminKey.trim(),
          },
        }
      );

      // Zero out key immediately after submission
      setAdminKey('');

      const msg = response?.message || 'Message successfully released from quarantine.';
      setSuccessMsg(msg);

      if (typeof onSuccess === 'function') {
        onSuccess(response?.data || response);
      }

      setTimeout(() => {
        handleClose();
      }, 1400);
    } catch (err) {
      setError(err.message || 'Failed to release message from quarantine.');
    } finally {
      setLoading(false);
    }
  };

  const stepLabel =
    message.step === 1
      ? 'Step 1 (Initial Hook)'
      : message.step === 2
      ? 'Step 2 (FU1)'
      : message.step === 3
      ? 'Step 3 (FU2)'
      : `Step ${message.step}`;

  const idMatches = confirmId.trim() === (message._id || '');
  const canSubmit =
    !loading &&
    idMatches &&
    adminKey.trim().length > 0 &&
    reason.trim().length >= 5 &&
    expectedBatch.trim().length > 0;

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="bg-white rounded-3xl max-w-lg w-full p-6 shadow-2xl space-y-4 animate-fadeIn max-h-[92vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-100 pb-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg">🔓</span>
              <h3 className="font-bold text-slate-900 text-base">Release Message Quarantine</h3>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Authorized release for individually reviewed follow-up draft.
            </p>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="w-8 h-8 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-600 flex items-center justify-center font-bold text-base transition-colors"
          >
            &times;
          </button>
        </div>

        {/* Safeguard Notice */}
        <div className="p-3.5 rounded-2xl bg-amber-50/80 border border-amber-200 text-amber-900 text-xs space-y-1">
          <div className="font-bold flex items-center gap-1.5">
            <span>⚠️</span>
            <span>Quarantine Safeguards &amp; Invariants</span>
          </div>
          <p className="text-[11px] leading-relaxed text-amber-800">
            Releasing removes the quarantine flag from this single message only. <strong>The message remains a draft</strong>; releasing does NOT schedule or send any email. Server-side authorization requires the configured <code className="font-mono bg-amber-100 px-1 py-0.5 rounded text-amber-950">ADMIN_RELEASE_KEY</code>.
          </p>
        </div>

        {/* Target Message Summary */}
        <div className="p-3.5 bg-slate-50 rounded-2xl border border-slate-200 text-xs space-y-2">
          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div>
              <span className="text-slate-400 font-medium">Company:</span>
              <p className="font-bold text-slate-800 truncate">
                {companyName || message.companyId?.companyName || '—'}
              </p>
            </div>
            <div>
              <span className="text-slate-400 font-medium">Sequence Step:</span>
              <p className="font-bold text-indigo-700">{stepLabel}</p>
            </div>
            <div className="col-span-2">
              <span className="text-slate-400 font-medium">Recipient:</span>
              <p className="font-mono text-slate-800 truncate">
                {message.recipientName ? `${message.recipientName} <${message.recipientEmail}>` : message.recipientEmail || '—'}
              </p>
            </div>
            <div className="col-span-2">
              <span className="text-slate-400 font-medium">Subject:</span>
              <p className="font-semibold text-slate-700 truncate">{message.subject || '—'}</p>
            </div>
            <div className="col-span-2">
              <span className="text-slate-400 font-medium">Target Message ID:</span>
              <p className="font-mono text-xs font-bold text-slate-900 bg-white px-2 py-1 rounded border border-slate-200 select-all">
                {message._id}
              </p>
            </div>
          </div>
        </div>

        {/* Input Form */}
        <form onSubmit={handleRelease} className="space-y-3 pt-1">
          {/* Confirm Message ID */}
          <div>
            <label className="block text-[11px] font-bold text-slate-700 uppercase tracking-wider mb-1">
              Confirm Exact Message ID <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={confirmId}
              onChange={(e) => setConfirmId(e.target.value)}
              placeholder="Paste exact message ID"
              className={`w-full px-3 py-2 rounded-xl text-xs font-mono border focus:outline-none focus:ring-2 ${
                idMatches
                  ? 'border-emerald-300 bg-emerald-50/30 text-emerald-950 focus:ring-emerald-400'
                  : 'border-rose-300 bg-rose-50/30 text-rose-950 focus:ring-rose-400'
              }`}
            />
            {!idMatches && (
              <p className="text-[10px] text-rose-600 mt-1 font-semibold">
                Must match message ID: {message._id}
              </p>
            )}
          </div>

          {/* Expected Batch */}
          <div>
            <label className="block text-[11px] font-bold text-slate-700 uppercase tracking-wider mb-1">
              Expected Quarantine Batch <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={expectedBatch}
              onChange={(e) => setExpectedBatch(e.target.value)}
              placeholder="quarantine-20261009"
              className="w-full px-3 py-2 rounded-xl text-xs font-mono border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {/* Release Reason */}
          <div>
            <label className="block text-[11px] font-bold text-slate-700 uppercase tracking-wider mb-1">
              Audited Release Reason <span className="text-red-500">*</span>
            </label>
            <textarea
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Greeting verified, evidence checked, approved for manual draft workflow"
              className="w-full px-3 py-2 rounded-xl text-xs border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <p className="text-[10px] text-slate-400 mt-0.5">
              Minimum 5 characters. Written permanently to the immutable quarantine audit log.
            </p>
          </div>

          {/* Operator / Actor */}
          <div>
            <label className="block text-[11px] font-bold text-slate-700 uppercase tracking-wider mb-1">
              Operator Identity (Actor)
            </label>
            <input
              type="text"
              value={actor}
              onChange={(e) => setActor(e.target.value)}
              placeholder="e.g. admin or operator-initials"
              className="w-full px-3 py-2 rounded-xl text-xs border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {/* Admin Release Key */}
          <div>
            <label className="block text-[11px] font-bold text-slate-700 uppercase tracking-wider mb-1">
              Admin Release Key (<code className="font-mono text-indigo-600">X-Admin-Key</code>) <span className="text-red-500">*</span>
            </label>
            <input
              type="password"
              value={adminKey}
              onChange={(e) => setAdminKey(e.target.value)}
              placeholder="Enter server ADMIN_RELEASE_KEY"
              autoComplete="off"
              className="w-full px-3 py-2 rounded-xl text-xs font-mono border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <p className="text-[10px] text-slate-500 mt-0.5">
              🔒 In-memory only. Never persisted in local storage or session cache.
            </p>
          </div>

          {/* Feedback messages */}
          {error && (
            <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">
              ❌ {error}
            </div>
          )}

          {successMsg && (
            <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-medium">
              ✅ {successMsg}
            </div>
          )}

          {/* Footer Actions */}
          <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
            <button
              type="button"
              onClick={handleClose}
              disabled={loading}
              className="px-4 py-2 border border-slate-200 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="px-5 py-2 bg-gradient-to-r from-rose-600 to-indigo-600 text-white rounded-xl text-xs font-bold hover:from-rose-700 hover:to-indigo-700 shadow-md disabled:opacity-50 transition-all flex items-center gap-1.5"
            >
              <span>🔓</span>
              <span>{loading ? 'Releasing...' : 'Release from Quarantine'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
