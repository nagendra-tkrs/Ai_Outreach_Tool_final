import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';

const STATUS_BADGES = {
  draft: 'bg-slate-100 text-slate-700 border-slate-200',
  approved: 'bg-blue-50 text-blue-700 border-blue-200',
  scheduled: 'bg-indigo-50 text-indigo-700 border-indigo-200 font-bold',
  sending: 'bg-amber-50 text-amber-700 border-amber-200 animate-pulse',
  sent: 'bg-emerald-50 text-emerald-700 border-emerald-200 font-bold',
  failed: 'bg-red-50 text-red-700 border-red-200',
};

const CAMPAIGN_STATUS_BADGES = {
  PENDING: 'bg-slate-100 text-slate-700 border-slate-200',
  INITIAL_SENT: 'bg-blue-50 text-blue-700 border-blue-200 font-bold',
  FOLLOW_UP_1_SENT: 'bg-indigo-50 text-indigo-700 border-indigo-200 font-bold',
  FOLLOW_UP_2_SENT: 'bg-purple-50 text-purple-700 border-purple-200 font-bold',
  REPLIED: 'bg-emerald-50 text-emerald-800 border-emerald-300 font-black',
  COMPLETED: 'bg-teal-50 text-teal-800 border-teal-200 font-bold',
  FAILED: 'bg-rose-50 text-rose-700 border-rose-200 font-bold',
};

const formatDate = (dateStr) => {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return '—';
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${String(d.getDate()).padStart(2, '0')} ${months[d.getMonth()]} ${d.getFullYear()}`;
};

const formatTime = (dateStr) => {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return '';
  let hours = d.getHours();
  const minutes = String(d.getMinutes()).padStart(2, '0');
  const ampm = hours >= 12 ? 'PM' : 'AM';
  hours = hours % 12 || 12;
  return `${String(hours).padStart(2, '0')}:${minutes} ${ampm}`;
};

export default function Outbox() {
  const [activeView, setActiveView] = useState('tracking'); // 'tracking' | 'messages'
  const [messages, setMessages] = useState([]);
  const [trackingRecords, setTrackingRecords] = useState([]);
  const [trackingStats, setTrackingStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [filterStatus, setFilterStatus] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedMessage, setSelectedMessage] = useState(null);
  const [selectedRecord, setSelectedRecord] = useState(null);
  const [sendingId, setSendingId] = useState(null);
  const [updatingReplyId, setUpdatingReplyId] = useState(null);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  const fetchOutbox = async () => {
    setLoading(true);
    setError('');
    try {
      const [messagesRes, trackingRes, statsRes] = await Promise.all([
        api.get('/outreach/all').catch(() => ({ data: [] })),
        api.get('/outreach/records').catch(() => ({ data: [] })),
        api.get('/outreach/stats').catch(() => ({ data: null })),
      ]);
      setMessages(messagesRes.data || []);
      setTrackingRecords(trackingRes.data || []);
      setTrackingStats(statsRes.data || null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOutbox();
  }, []);

  const handleSend = async (message) => {
    setSendingId(message._id);
    setError('');
    try {
      await api.post(`/outreach/${message._id}/send`, {
        recipientEmail: message.recipientEmail,
        ccRecipients: message.ccRecipients || [],
        bccRecipients: message.bccRecipients || [],
      });
      setSuccessMsg('Email dispatched successfully and tracking record updated!');
      setTimeout(() => setSuccessMsg(''), 4000);
      await fetchOutbox();
    } catch (err) {
      setError(`Failed to send email: ${err.message}`);
    } finally {
      setSendingId(null);
    }
  };

  const handleToggleReply = async (record, newStatus) => {
    setUpdatingReplyId(record._id);
    setError('');
    try {
      const res = await api.patch(`/outreach/records/${record._id}/reply`, {
        replyStatus: newStatus,
      });
      const updated = res.data || res;
      setTrackingRecords((prev) =>
        prev.map((r) => (r._id === record._id ? { ...r, ...updated } : r))
      );
      if (selectedRecord && selectedRecord._id === record._id) {
        setSelectedRecord({ ...selectedRecord, ...updated });
      }
      setSuccessMsg(`Reply status updated to "${newStatus}"`);
      setTimeout(() => setSuccessMsg(''), 3000);
      const statsRes = await api.get('/outreach/stats');
      setTrackingStats(statsRes.data || null);
    } catch (err) {
      setError(`Failed to update reply status: ${err.message}`);
    } finally {
      setUpdatingReplyId(null);
    }
  };

  const handleExportExcel = async () => {
    setExporting(true);
    setError('');
    try {
      const res = await api.get('/outreach/export', { responseType: 'blob' });
      const blob = res instanceof Blob ? res : new Blob([res], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      const today = new Date().toISOString().split('T')[0];
      link.setAttribute('download', `AI_Outreach_Report_${today}.xlsx`);
      document.body.appendChild(link);
      link.click();
      link.parentNode?.removeChild(link);
      window.URL.revokeObjectURL(url);
      setSuccessMsg('Excel report downloaded successfully!');
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err) {
      setError(`Failed to export Excel report: ${err.message}`);
    } finally {
      setExporting(false);
    }
  };

  // Filter messages
  const filteredMessages = messages.filter((m) => {
    if (filterStatus !== 'all' && m.status !== filterStatus) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchComp = m.companyId?.companyName?.toLowerCase().includes(q);
      const matchRecip = m.recipientEmail?.toLowerCase().includes(q) || m.recipientName?.toLowerCase().includes(q);
      const matchSub = m.subject?.toLowerCase().includes(q);
      return matchComp || matchRecip || matchSub;
    }
    return true;
  });

  // Filter tracking records
  const filteredRecords = trackingRecords.filter((r) => {
    if (filterStatus !== 'all') {
      if (filterStatus === 'REPLIED' && r.replyStatus !== 'REPLIED') return false;
      if (filterStatus === 'SENT' && r.initialEmail?.status !== 'SENT') return false;
      if (filterStatus === 'FAILED' && r.initialEmail?.status !== 'FAILED') return false;
      if (filterStatus === 'PENDING' && r.campaignStatus !== 'PENDING') return false;
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchComp = r.companyName?.toLowerCase().includes(q);
      const matchCont = r.contactName?.toLowerCase().includes(q);
      const matchEmail = r.recipientEmail?.toLowerCase().includes(q);
      const matchSub = r.emailSubject?.toLowerCase().includes(q);
      return matchComp || matchCont || matchEmail || matchSub;
    }
    return true;
  });

  const totalSent = trackingStats?.initialSent || messages.filter((m) => m.status === 'sent').length;
  const totalFollowUps = trackingStats?.totalFollowUpsSent || 0;
  const totalReplies = trackingStats?.repliesReceived || 0;
  const totalPendingFollowUps = trackingStats?.followUpsPending || 0;

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-black tracking-tight text-slate-900">Email Outreach &amp; Follow-up Tracking</h1>
            <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
              Live Tracker
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            Real-time tracking of sent emails, automated multi-step follow-ups, reply statuses, and Excel exports.
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={fetchOutbox}
            className="px-3.5 py-2 bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 rounded-xl text-xs font-bold transition-all shadow-xs flex items-center gap-1.5"
          >
            <span>🔄</span>
            <span>Refresh</span>
          </button>

          <button
            onClick={handleExportExcel}
            disabled={exporting}
            className="px-5 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 text-white rounded-xl text-xs font-bold transition-all shadow-md flex items-center gap-2 disabled:opacity-50"
          >
            <span>{exporting ? '⏳' : '📊'}</span>
            <span>{exporting ? 'Exporting Excel...' : 'Export Outreach Report (Excel)'}</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-2xl text-xs flex items-center justify-between animate-fadeIn">
          <span>{error}</span>
          <button onClick={() => setError('')} className="font-bold text-red-500">&times;</button>
        </div>
      )}

      {successMsg && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-3 rounded-2xl text-xs flex items-center justify-between animate-fadeIn">
          <span>{successMsg}</span>
          <button onClick={() => setSuccessMsg('')} className="font-bold text-emerald-600">&times;</button>
        </div>
      )}

      {/* Campaign Performance Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <div className="bg-white rounded-2xl border border-slate-200/80 p-4 shadow-xs">
          <p className="text-[11px] font-bold uppercase text-slate-400">Initial Emails Sent</p>
          <p className="text-2xl font-black text-slate-900 mt-1.5">{totalSent}</p>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200/80 p-4 shadow-xs">
          <p className="text-[11px] font-bold uppercase text-slate-400">Follow-ups Sent</p>
          <p className="text-2xl font-black text-indigo-600 mt-1.5">{totalFollowUps}</p>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200/80 p-4 shadow-xs">
          <p className="text-[11px] font-bold uppercase text-slate-400">Follow-ups Pending</p>
          <p className="text-2xl font-black text-amber-600 mt-1.5">{totalPendingFollowUps}</p>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200/80 p-4 shadow-xs">
          <p className="text-[11px] font-bold uppercase text-slate-400">Replies Received</p>
          <p className="text-2xl font-black text-emerald-600 mt-1.5">{totalReplies}</p>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200/80 p-4 shadow-xs col-span-2 sm:col-span-1">
          <p className="text-[11px] font-bold uppercase text-slate-400">Reply Rate</p>
          <p className="text-2xl font-black text-purple-600 mt-1.5">{trackingStats?.replyRate || 0}%</p>
        </div>
      </div>

      {/* View Switcher & Search Bar */}
      <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 border-b border-slate-200 pb-3">
        <div className="flex items-center gap-2">
          <button
            onClick={() => { setActiveView('tracking'); setFilterStatus('all'); }}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 ${
              activeView === 'tracking'
                ? 'bg-indigo-600 text-white shadow-sm'
                : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'
            }`}
          >
            <span>📋</span>
            <span>Outreach Tracking ({trackingRecords.length})</span>
          </button>

          <button
            onClick={() => { setActiveView('messages'); setFilterStatus('all'); }}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 ${
              activeView === 'messages'
                ? 'bg-indigo-600 text-white shadow-sm'
                : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'
            }`}
          >
            <span>✉️</span>
            <span>Sequence Outbox ({messages.length})</span>
          </button>
        </div>

        {/* Search Box */}
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Search company, contact, or email..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full md:w-64 px-3.5 py-1.5 bg-white border border-slate-200 rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="text-xs text-slate-400 hover:text-slate-600 font-bold px-1.5"
            >
              &times;
            </button>
          )}
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex flex-wrap gap-2">
        {activeView === 'tracking' ? (
          [
            { id: 'all', label: `All Records (${trackingRecords.length})` },
            { id: 'SENT', label: `Initial Sent (${trackingRecords.filter(r => r.initialEmail?.status === 'SENT').length})` },
            { id: 'REPLIED', label: `Replied (${trackingRecords.filter(r => r.replyStatus === 'REPLIED').length})` },
            { id: 'FAILED', label: `Failed (${trackingRecords.filter(r => r.initialEmail?.status === 'FAILED').length})` },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setFilterStatus(tab.id)}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all ${
                filterStatus === tab.id
                  ? 'bg-slate-900 text-white shadow-sm'
                  : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'
              }`}
            >
              {tab.label}
            </button>
          ))
        ) : (
          [
            { id: 'all', label: `All Messages (${messages.length})` },
            { id: 'sent', label: `Dispatched (${messages.filter(m => m.status === 'sent').length})` },
            { id: 'scheduled', label: `Scheduled Drip (${messages.filter(m => m.status === 'scheduled').length})` },
            { id: 'draft', label: `Drafts (${messages.filter(m => m.status === 'draft').length})` },
            { id: 'failed', label: `Failed (${messages.filter(m => m.status === 'failed').length})` },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setFilterStatus(tab.id)}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all ${
                filterStatus === tab.id
                  ? 'bg-slate-900 text-white shadow-sm'
                  : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'
              }`}
            >
              {tab.label}
            </button>
          ))
        )}
      </div>

      {/* Main Content Area */}
      {loading ? (
        <div className="bg-white rounded-2xl border border-slate-200 p-16 text-center text-slate-400">
          <div className="inline-block w-8 h-8 border-3 border-indigo-600 border-t-transparent rounded-full animate-spin mb-3"></div>
          <p className="font-semibold text-sm">Loading outreach tracking data...</p>
        </div>
      ) : activeView === 'tracking' ? (
        /* TRACKING VIEW TABLE */
        filteredRecords.length === 0 ? (
          <div className="bg-white rounded-3xl border border-slate-200 p-16 text-center">
            <div className="w-16 h-16 rounded-3xl bg-indigo-50 text-indigo-600 flex items-center justify-center text-3xl mx-auto mb-4">
              📊
            </div>
            <h3 className="font-bold text-slate-900 text-lg">No Outreach Tracking Records Found</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1 mb-6">
              When you dispatch an email from a company sequence, an outreach tracking record will be automatically generated.
            </p>
            <Link
              to="/companies"
              className="inline-block px-5 py-2.5 bg-gradient-to-r from-indigo-600 to-blue-600 text-white rounded-xl text-xs font-bold shadow-md hover:from-indigo-700 hover:to-blue-700"
            >
              Go to Companies Directory &rarr;
            </Link>
          </div>
        ) : (
          <div className="bg-white rounded-2xl border border-slate-200/80 overflow-hidden shadow-xs">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50/80 border-b border-slate-200/80 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                  <tr>
                    <th className="px-5 py-3.5">Company &amp; Contact</th>
                    <th className="px-4 py-3.5">Recipient &amp; CC</th>
                    <th className="px-4 py-3.5">Initial Sent</th>
                    <th className="px-4 py-3.5">Follow-up 1</th>
                    <th className="px-4 py-3.5">Follow-up 2</th>
                    <th className="px-4 py-3.5">Reply Status</th>
                    <th className="px-4 py-3.5">Campaign Status</th>
                    <th className="px-5 py-3.5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filteredRecords.map((r) => (
                    <tr key={r._id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="px-5 py-4">
                        <Link
                          to={`/companies/${r.companyId?._id || r.companyId}`}
                          className="font-bold text-slate-900 hover:text-indigo-600 block truncate max-w-[200px]"
                        >
                          {r.companyName}
                        </Link>
                        <p className="text-slate-500 text-[11px] mt-0.5 truncate max-w-[200px]">
                          {r.contactName || 'Lead'} {r.contactDesignation && `• ${r.contactDesignation}`}
                        </p>
                      </td>

                      <td className="px-4 py-4">
                        <span className="font-mono text-slate-800 font-semibold block truncate max-w-[180px]">
                          {r.recipientEmail}
                        </span>
                        {Array.isArray(r.cc) && r.cc.length > 0 && (
                          <span className="inline-block text-[10px] text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded font-mono mt-1 truncate max-w-[180px]">
                            CC: {r.cc.join(', ')}
                          </span>
                        )}
                      </td>

                      <td className="px-4 py-4 whitespace-nowrap">
                        {r.initialEmail?.status === 'SENT' ? (
                          <div className="text-[11px]">
                            <span className="inline-flex items-center gap-1 font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
                              ✓ {formatDate(r.initialEmail.sentAt)}
                            </span>
                            <span className="block text-[10px] text-slate-400 font-mono mt-0.5">
                              {formatTime(r.initialEmail.sentAt)}
                            </span>
                          </div>
                        ) : r.initialEmail?.status === 'FAILED' ? (
                          <span className="inline-flex items-center gap-1 font-bold text-rose-700 bg-rose-50 px-2 py-0.5 rounded-md border border-rose-200 text-[10px]">
                            ✗ Failed
                          </span>
                        ) : (
                          <span className="text-[10px] text-slate-400 font-semibold">Pending</span>
                        )}
                      </td>

                      <td className="px-4 py-4 whitespace-nowrap">
                        {r.followUp1?.status === 'SENT' ? (
                          <div className="text-[11px]">
                            <span className="inline-flex items-center gap-1 font-bold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded-md border border-indigo-200">
                              ✓ {formatDate(r.followUp1.sentAt)}
                            </span>
                            <span className="block text-[10px] text-slate-400 font-mono mt-0.5">
                              {formatTime(r.followUp1.sentAt)}
                            </span>
                          </div>
                        ) : r.followUp1?.scheduledAt ? (
                          <div className="text-[11px]">
                            <span className="text-[10px] font-bold text-amber-800 bg-amber-50 px-2 py-0.5 rounded-md border border-amber-200">
                              📅 {formatDate(r.followUp1.scheduledAt)}
                            </span>
                          </div>
                        ) : (
                          <span className="text-[10px] text-slate-400">—</span>
                        )}
                      </td>

                      <td className="px-4 py-4 whitespace-nowrap">
                        {r.followUp2?.status === 'SENT' ? (
                          <div className="text-[11px]">
                            <span className="inline-flex items-center gap-1 font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded-md border border-purple-200">
                              ✓ {formatDate(r.followUp2.sentAt)}
                            </span>
                            <span className="block text-[10px] text-slate-400 font-mono mt-0.5">
                              {formatTime(r.followUp2.sentAt)}
                            </span>
                          </div>
                        ) : r.followUp2?.scheduledAt ? (
                          <div className="text-[11px]">
                            <span className="text-[10px] font-bold text-slate-600 bg-slate-100 px-2 py-0.5 rounded-md">
                              📅 {formatDate(r.followUp2.scheduledAt)}
                            </span>
                          </div>
                        ) : (
                          <span className="text-[10px] text-slate-400">—</span>
                        )}
                      </td>

                      <td className="px-4 py-4 whitespace-nowrap">
                        {r.replyStatus === 'REPLIED' ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-black uppercase bg-emerald-100 text-emerald-800 border border-emerald-300">
                            ✓ Replied
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium text-slate-500 bg-slate-100">
                            No Reply
                          </span>
                        )}
                      </td>

                      <td className="px-4 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase border ${CAMPAIGN_STATUS_BADGES[r.campaignStatus] || 'bg-slate-100 text-slate-600 border-slate-200'}`}>
                          {r.campaignStatus?.replace(/_/g, ' ')}
                        </span>
                      </td>

                      <td className="px-5 py-4 whitespace-nowrap text-right space-x-2">
                        <button
                          onClick={() => setSelectedRecord(r)}
                          className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-bold transition-colors"
                        >
                          Timeline
                        </button>
                        <button
                          onClick={() => handleToggleReply(r, r.replyStatus === 'REPLIED' ? 'NO_REPLY' : 'REPLIED')}
                          disabled={updatingReplyId === r._id}
                          className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors ${
                            r.replyStatus === 'REPLIED'
                              ? 'bg-slate-200 text-slate-700 hover:bg-slate-300'
                              : 'bg-emerald-600 text-white hover:bg-emerald-700'
                          }`}
                        >
                          {r.replyStatus === 'REPLIED' ? 'Mark No Reply' : 'Mark Replied'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      ) : (
        /* MESSAGES OUTBOX TABLE */
        filteredMessages.length === 0 ? (
          <div className="bg-white rounded-3xl border border-slate-200 p-16 text-center">
            <div className="w-16 h-16 rounded-3xl bg-slate-100 text-slate-600 flex items-center justify-center text-3xl mx-auto mb-4">
              📬
            </div>
            <h3 className="font-bold text-slate-900 text-lg">No messages found in this view</h3>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1 mb-6">
              Generate customized 3-step outreach sequences for any company to send emails.
            </p>
          </div>
        ) : (
          <div className="bg-white rounded-2xl border border-slate-200/80 overflow-hidden shadow-xs">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50/80 border-b border-slate-200/80 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                  <tr>
                    <th className="px-5 py-3.5">Prospect &amp; Company</th>
                    <th className="px-4 py-3.5">Sequence Step</th>
                    <th className="px-5 py-3.5">Subject &amp; Snippet</th>
                    <th className="px-4 py-3.5">Engagement &amp; Status</th>
                    <th className="px-4 py-3.5">Date / Timeline</th>
                    <th className="px-5 py-3.5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filteredMessages.map((msg) => {
                    const targetEmail = msg.recipientEmail || msg.contactId?.email || msg.companyId?.contactEmail;
                    const contactName = msg.recipientName || msg.contactId?.name || 'Lead';
                    return (
                      <tr key={msg._id} className="hover:bg-slate-50/80 transition-colors">
                        <td className="px-5 py-4">
                          {msg.companyId ? (
                            <Link
                              to={`/companies/${msg.companyId._id}`}
                              className="font-bold text-slate-900 hover:text-indigo-600 block truncate max-w-[200px]"
                            >
                              {msg.companyId.companyName}
                            </Link>
                          ) : (
                            <span className="text-slate-400 font-medium">Company Profile</span>
                          )}
                          <p className="text-slate-500 text-[11px] mt-0.5 truncate max-w-[220px]">
                            <span className="font-semibold text-slate-700">{contactName}</span>
                            {targetEmail && <span className="font-mono text-slate-400"> &lt;{targetEmail}&gt;</span>}
                          </p>
                          <div className="flex flex-wrap gap-1 mt-1">
                            {Array.isArray(msg.ccRecipients) && msg.ccRecipients.length > 0 && (
                              <span className="inline-flex items-center gap-1 text-[10px] text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded font-mono">
                                CC: {msg.ccRecipients.join(', ')}
                              </span>
                            )}
                          </div>
                        </td>

                        <td className="px-4 py-4 whitespace-nowrap">
                          <span className="inline-block px-2.5 py-1 rounded-lg text-xs font-bold bg-slate-100 text-slate-800">
                            Step {msg.step}
                          </span>
                        </td>

                        <td className="px-5 py-4 max-w-xs">
                          <p className="font-bold text-slate-900 truncate">{msg.subject}</p>
                          <p className="text-[11px] text-slate-500 truncate mt-0.5">
                            {msg.bodyText || msg.bodyHtml?.replace(/<[^>]*>?/gm, '')}
                          </p>
                        </td>

                        <td className="px-4 py-4 whitespace-nowrap">
                          <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase border ${STATUS_BADGES[msg.status] || STATUS_BADGES.draft}`}>
                            {msg.status.toUpperCase()}
                          </span>
                        </td>

                        <td className="px-4 py-4 whitespace-nowrap text-slate-500 font-mono text-[11px]">
                          {msg.sentAt
                            ? formatDate(msg.sentAt)
                            : msg.scheduledAt
                            ? `Sched: ${formatDate(msg.scheduledAt)}`
                            : formatDate(msg.createdAt)}
                        </td>

                        <td className="px-5 py-4 whitespace-nowrap text-right space-x-2">
                          <button
                            onClick={() => setSelectedMessage(msg)}
                            className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-bold transition-colors"
                          >
                            Preview
                          </button>
                          <button
                            onClick={() => handleSend(msg)}
                            disabled={sendingId === msg._id || !targetEmail}
                            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors shadow-xs ${
                              msg.status === 'sent'
                                ? 'bg-slate-800 text-white hover:bg-slate-900'
                                : 'bg-emerald-600 text-white hover:bg-emerald-700'
                            } disabled:opacity-50`}
                          >
                            {sendingId === msg._id ? 'Sending...' : msg.status === 'sent' ? 'Resend' : 'Send Now'}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )
      )}

      {/* OUTREACH TIMELINE MODAL */}
      {selectedRecord && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-3xl max-w-xl w-full p-6 max-h-[90vh] overflow-y-auto shadow-2xl space-y-5 animate-fadeIn">
            <div className="flex items-start justify-between border-b border-slate-100 pb-4">
              <div>
                <span className="text-[10px] font-extrabold uppercase tracking-wider text-indigo-600 bg-indigo-50 px-2.5 py-1 rounded-md">
                  Outreach Tracking Details
                </span>
                <h3 className="text-xl font-black text-slate-900 mt-2">{selectedRecord.companyName}</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Prospect: <strong className="text-slate-800">{selectedRecord.contactName || 'Lead'}</strong>
                  {selectedRecord.contactDesignation && ` (${selectedRecord.contactDesignation})`}
                  &nbsp;• <span className="font-mono text-indigo-600">{selectedRecord.recipientEmail}</span>
                </p>
                {Array.isArray(selectedRecord.cc) && selectedRecord.cc.length > 0 && (
                  <p className="text-xs text-indigo-700 font-mono mt-1">
                    CC: {selectedRecord.cc.join(', ')}
                  </p>
                )}
              </div>
              <button
                onClick={() => setSelectedRecord(null)}
                className="w-8 h-8 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-600 flex items-center justify-center font-bold text-base"
              >
                &times;
              </button>
            </div>

            {/* Visual Timeline Section */}
            <div className="space-y-3">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Campaign Timeline</h4>

              {/* Step 1: Initial Email */}
              <div className="flex items-start gap-3 p-3.5 rounded-2xl border border-slate-200 bg-slate-50">
                <div className="w-7 h-7 rounded-xl flex items-center justify-center font-bold text-xs shrink-0 mt-0.5 bg-emerald-100 text-emerald-700">
                  {selectedRecord.initialEmail?.status === 'SENT' ? '✓' : selectedRecord.initialEmail?.status === 'FAILED' ? '✗' : '1'}
                </div>
                <div className="flex-1">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-bold text-slate-900">Initial Email</p>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md uppercase ${
                      selectedRecord.initialEmail?.status === 'SENT' ? 'bg-emerald-100 text-emerald-800' :
                      selectedRecord.initialEmail?.status === 'FAILED' ? 'bg-rose-100 text-rose-800' : 'bg-slate-200 text-slate-700'
                    }`}>
                      {selectedRecord.initialEmail?.status || 'PENDING'}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {selectedRecord.initialEmail?.sentAt
                      ? `Sent on ${formatDate(selectedRecord.initialEmail.sentAt)} at ${formatTime(selectedRecord.initialEmail.sentAt)}`
                      : `Scheduled: ${formatDate(selectedRecord.initialEmail?.scheduledAt)}`}
                  </p>
                  {selectedRecord.initialEmail?.error && (
                    <p className="text-[11px] text-red-600 mt-1 font-mono">{selectedRecord.initialEmail.error}</p>
                  )}
                </div>
              </div>

              {/* Step 2: Follow-up 1 */}
              <div className="flex items-start gap-3 p-3.5 rounded-2xl border border-slate-200 bg-slate-50">
                <div className="w-7 h-7 rounded-xl flex items-center justify-center font-bold text-xs shrink-0 mt-0.5 bg-indigo-100 text-indigo-700">
                  {selectedRecord.followUp1?.status === 'SENT' ? '✓' : selectedRecord.followUp1?.status === 'FAILED' ? '✗' : '2'}
                </div>
                <div className="flex-1">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-bold text-slate-900">Follow-up 1</p>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md uppercase ${
                      selectedRecord.followUp1?.status === 'SENT' ? 'bg-indigo-100 text-indigo-800' :
                      selectedRecord.followUp1?.status === 'FAILED' ? 'bg-rose-100 text-rose-800' : 'bg-amber-100 text-amber-800'
                    }`}>
                      {selectedRecord.followUp1?.status || 'PENDING'}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {selectedRecord.followUp1?.sentAt
                      ? `Sent on ${formatDate(selectedRecord.followUp1.sentAt)} at ${formatTime(selectedRecord.followUp1.sentAt)}`
                      : selectedRecord.followUp1?.scheduledAt
                      ? `Scheduled: ${formatDate(selectedRecord.followUp1.scheduledAt)}`
                      : 'Not scheduled yet'}
                  </p>
                </div>
              </div>

              {/* Step 3: Follow-up 2 */}
              <div className="flex items-start gap-3 p-3.5 rounded-2xl border border-slate-200 bg-slate-50">
                <div className="w-7 h-7 rounded-xl flex items-center justify-center font-bold text-xs shrink-0 mt-0.5 bg-purple-100 text-purple-700">
                  {selectedRecord.followUp2?.status === 'SENT' ? '✓' : selectedRecord.followUp2?.status === 'FAILED' ? '✗' : '3'}
                </div>
                <div className="flex-1">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-bold text-slate-900">Follow-up 2</p>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md uppercase ${
                      selectedRecord.followUp2?.status === 'SENT' ? 'bg-purple-100 text-purple-800' :
                      selectedRecord.followUp2?.status === 'FAILED' ? 'bg-rose-100 text-rose-800' : 'bg-slate-200 text-slate-700'
                    }`}>
                      {selectedRecord.followUp2?.status || 'PENDING'}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {selectedRecord.followUp2?.sentAt
                      ? `Sent on ${formatDate(selectedRecord.followUp2.sentAt)} at ${formatTime(selectedRecord.followUp2.sentAt)}`
                      : selectedRecord.followUp2?.scheduledAt
                      ? `Scheduled: ${formatDate(selectedRecord.followUp2.scheduledAt)}`
                      : 'Not scheduled yet'}
                  </p>
                </div>
              </div>

              {/* Reply Status Box */}
              <div className="flex items-center justify-between p-4 rounded-2xl border border-indigo-100 bg-indigo-50/50">
                <div>
                  <p className="text-xs font-bold text-indigo-950">Reply Status</p>
                  <p className="text-[11px] text-indigo-700 mt-0.5">
                    {selectedRecord.replyStatus === 'REPLIED'
                      ? '✓ Contact has replied. Automated follow-ups are halted.'
                      : 'No reply received yet. Follow-ups will dispatch as scheduled.'}
                  </p>
                </div>
                <button
                  onClick={() => handleToggleReply(selectedRecord, selectedRecord.replyStatus === 'REPLIED' ? 'NO_REPLY' : 'REPLIED')}
                  disabled={updatingReplyId === selectedRecord._id}
                  className={`px-4 py-2 rounded-xl text-xs font-bold shadow-xs transition-all ${
                    selectedRecord.replyStatus === 'REPLIED'
                      ? 'bg-slate-200 text-slate-800 hover:bg-slate-300'
                      : 'bg-emerald-600 text-white hover:bg-emerald-700'
                  }`}
                >
                  {selectedRecord.replyStatus === 'REPLIED' ? 'Mark as No Reply' : '✓ Mark as Replied'}
                </button>
              </div>
            </div>

            <div className="flex justify-end pt-3 border-t border-slate-100">
              <button
                onClick={() => setSelectedRecord(null)}
                className="px-5 py-2 bg-slate-900 text-white rounded-xl text-xs font-bold hover:bg-slate-800"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* MESSAGE PREVIEW MODAL */}
      {selectedMessage && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-3xl max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto shadow-2xl space-y-4 animate-fadeIn">
            <div className="flex items-start justify-between border-b border-slate-100 pb-4">
              <div>
                <span className="text-[10px] font-extrabold uppercase tracking-wider text-indigo-600 bg-indigo-50 px-2.5 py-1 rounded-md">
                  {selectedMessage.stepLabel || `Step ${selectedMessage.step}`}
                </span>
                <h3 className="text-lg font-black text-slate-900 mt-2">{selectedMessage.subject}</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  To: <span className="font-semibold text-slate-800">{selectedMessage.recipientName || 'Prospect'}</span> &lt;{selectedMessage.recipientEmail || 'no email'}&gt;
                </p>
                {Array.isArray(selectedMessage.ccRecipients) && selectedMessage.ccRecipients.length > 0 && (
                  <p className="text-xs text-indigo-700 font-mono mt-1">
                    CC: {selectedMessage.ccRecipients.join(', ')}
                  </p>
                )}
              </div>
              <button
                onClick={() => setSelectedMessage(null)}
                className="w-8 h-8 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-600 flex items-center justify-center font-bold text-base"
              >
                &times;
              </button>
            </div>

            <div className="p-5 bg-slate-50 rounded-2xl border border-slate-200 text-xs text-slate-800 leading-relaxed shadow-inner">
              <div dangerouslySetInnerHTML={{ __html: selectedMessage.bodyHtml }} />
            </div>

            <div className="flex justify-between items-center pt-3 border-t border-slate-100">
              <span className={`px-2.5 py-1 rounded-full text-xs font-bold border ${STATUS_BADGES[selectedMessage.status]}`}>
                Status: {selectedMessage.status?.toUpperCase()}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setSelectedMessage(null)}
                  className="px-4 py-2 border border-slate-200 text-slate-700 rounded-xl text-xs font-bold hover:bg-slate-50"
                >
                  Close
                </button>
                <button
                  onClick={() => {
                    handleSend(selectedMessage);
                    setSelectedMessage(null);
                  }}
                  disabled={sendingId === selectedMessage._id}
                  className="px-5 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 text-white rounded-xl text-xs font-bold hover:from-emerald-700 hover:to-teal-700 shadow-md disabled:opacity-50"
                >
                  Send Outbound Email
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
