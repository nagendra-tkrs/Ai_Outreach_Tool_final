import { useState, useEffect } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import api from '../api';

export default function Settings() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState('ai');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingSmtp, setTestingSmtp] = useState(false);
  const [connectingGmail, setConnectingGmail] = useState(false);
  const [disconnectingGmail, setDisconnectingGmail] = useState(false);
  const [syncingGmail, setSyncingGmail] = useState(false);
  const [gmailSyncResult, setGmailSyncResult] = useState(null);
  const [manualCode, setManualCode] = useState('');
  const [exchangingCode, setExchangingCode] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState('');
  const [error, setError] = useState('');
  const [testResult, setTestResult] = useState(null);
  const [testEmail, setTestEmail] = useState('');

  const [formData, setFormData] = useState({
    ai: {
      provider: 'ollama',
      ollamaBaseUrl: 'http://localhost:11434',
      model: 'llama3',
    },
    smtp: {
      host: '',
      port: 587,
      secure: false,
      user: '',
      pass: '',
      hasPass: false,
      fromName: 'AI Outreach',
      fromEmail: '',
    },
    gmailOAuth: {
      clientId: '',
      clientSecret: '',
      hasClientSecret: false,
      hasRefreshToken: false,
      userEmail: '',
      isConfigured: false,
    },
    senderProfile: {
      companyName: 'TKSR Product Services',
      senderName: 'Nagendra',
      senderTitle: 'Business analyst',
      productDescription: 'We help high-growth B2B companies automate client research and hyper-personalized outreach pipeline with AI, increasing meeting booking rates by 3.5x.',
      targetPitch: 'Offering a brief 10-minute workflow demo to showcase tailored B2B client acquisition opportunities.',
    },
  });

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const res = await api.get('/settings');
      if (res.data) {
        setFormData({
          ai: { ...formData.ai, ...res.data.ai },
          smtp: { ...formData.smtp, ...res.data.smtp },
          gmailOAuth: { ...formData.gmailOAuth, ...(res.data.gmailOAuth || {}) },
          senderProfile: { ...formData.senderProfile, ...res.data.senderProfile },
        });
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSettings();

    // Check URL parameters for OAuth redirect feedback
    const gmailStatus = searchParams.get('gmail');
    if (gmailStatus === 'connected') {
      setActiveTab('gmail');
      setSaveSuccess('Gmail authorized successfully! Read-only reply tracking is active.');
      setSearchParams({}, { replace: true });
    } else if (gmailStatus === 'error') {
      setActiveTab('gmail');
      const detail = searchParams.get('detail') || 'OAuth authorization failed';
      setError(`Gmail authorization error: ${detail}`);
      setSearchParams({}, { replace: true });
    }
  }, []);

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    setSaveSuccess('');
    try {
      await api.post('/settings', formData);
      setSaveSuccess('Settings saved and synchronized successfully!');
      fetchSettings();
      setTimeout(() => setSaveSuccess(''), 4000);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleTestSmtp = async () => {
    if (!testEmail) {
      setError('Please provide a recipient email to send the test email.');
      return;
    }
    setTestingSmtp(true);
    setError('');
    setTestResult(null);
    try {
      const res = await api.post('/settings/test-smtp', {
        smtp: formData.smtp,
        recipientEmail: testEmail,
      });
      setTestResult(res.data || res);
    } catch (err) {
      setError(err.message);
    } finally {
      setTestingSmtp(false);
    }
  };

  const handleConnectGmail = async () => {
    setConnectingGmail(true);
    setError('');
    try {
      const res = await api.get('/settings/gmail/auth-url');
      if (res.data?.authUrl || res.authUrl) {
        const url = res.data?.authUrl || res.authUrl;
        // Redirect browser to Google's consent screen
        window.location.href = url;
      } else {
        setError('Failed to generate Google authorization URL.');
      }
    } catch (err) {
      setError(`Failed to initiate Gmail authorization: ${err.message}`);
    } finally {
      setConnectingGmail(false);
    }
  };

  const handleDisconnectGmail = async () => {
    if (!window.confirm('Are you sure you want to disconnect Gmail reply tracking?')) return;
    setDisconnectingGmail(true);
    setError('');
    try {
      await api.post('/settings/gmail/disconnect');
      setSaveSuccess('Gmail disconnected successfully.');
      await fetchSettings();
      setTimeout(() => setSaveSuccess(''), 4000);
    } catch (err) {
      setError(`Failed to disconnect Gmail: ${err.message}`);
    } finally {
      setDisconnectingGmail(false);
    }
  };

  const handleExchangeManualCode = async (e) => {
    e.preventDefault();
    if (!manualCode.trim()) {
      setError('Please paste the authorization code provided by Google.');
      return;
    }
    setExchangingCode(true);
    setError('');
    try {
      await api.post('/settings/gmail/exchange-code', { code: manualCode.trim() });
      setSaveSuccess('Authorization code exchanged successfully! Gmail is connected.');
      setManualCode('');
      await fetchSettings();
      setTimeout(() => setSaveSuccess(''), 4000);
    } catch (err) {
      setError(`Code exchange failed: ${err.message}`);
    } finally {
      setExchangingCode(false);
    }
  };

  const handleSyncGmailNow = async () => {
    setSyncingGmail(true);
    setError('');
    setGmailSyncResult(null);
    try {
      const res = await api.post('/outreach/sync-replies', {
        query: 'newer_than:7d',
        maxResults: 20,
      });
      if (res && res.success) {
        setGmailSyncResult(res);
        setSaveSuccess(res.message || 'Gmail replies checked successfully.');
        setTimeout(() => setSaveSuccess(''), 5000);
      } else {
        setError(res?.message || 'Failed to sync Gmail replies.');
      }
    } catch (err) {
      setError(`Failed to sync Gmail replies: ${err.message}`);
    } finally {
      setSyncingGmail(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-white rounded-3xl border border-slate-200 p-16 text-center text-slate-400">
        <div className="inline-block w-8 h-8 border-3 border-indigo-600 border-t-transparent rounded-full animate-spin mb-3"></div>
        <p className="font-semibold text-sm">Loading configuration...</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fadeIn max-w-4xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-black tracking-tight text-slate-900">Platform Settings &amp; Integrations</h1>
        <p className="text-xs text-slate-500 mt-0.5">
          Configure your AI engine, pitch profile, outbound Google SMTP credentials, and read-only Gmail reply tracking.
        </p>
      </div>

      {saveSuccess && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-3 rounded-2xl text-xs flex items-center gap-2 shadow-xs">
          <span>✓</span>
          <span className="font-semibold">{saveSuccess}</span>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-2xl text-xs flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError('')} className="font-bold text-red-500">&times;</button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex flex-wrap gap-2">
        {[
          { id: 'ai', label: 'AI Engine & LLM', icon: '🤖' },
          { id: 'profile', label: 'Sender & Pitch Profile', icon: '🎯' },
          { id: 'smtp', label: 'Email & Google SMTP', icon: '✉️' },
          { id: 'gmail', label: 'Gmail Reply Tracking', icon: '📬' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all flex items-center gap-2 ${
              activeTab === tab.id
                ? 'bg-slate-900 text-white shadow-md'
                : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'
            }`}
          >
            <span>{tab.icon}</span>
            <span>{tab.label}</span>
            {tab.id === 'gmail' && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-bold uppercase ${
                formData.gmailOAuth?.isConfigured
                  ? 'bg-emerald-100 text-emerald-800'
                  : 'bg-amber-100 text-amber-800'
              }`}>
                {formData.gmailOAuth?.isConfigured ? 'Active' : 'Setup'}
              </span>
            )}
          </button>
        ))}
      </div>

      <form onSubmit={handleSave} className="space-y-6">
        {/* Tab 1: AI Settings */}
        {activeTab === 'ai' && (
          <div className="bg-white rounded-3xl border border-slate-200/80 p-6 md:p-8 space-y-6 shadow-xs">
            <div>
              <h2 className="text-base font-bold text-slate-900">AI Model Synthesizer</h2>
              <p className="text-xs text-slate-500 mt-0.5">Powers deep company intelligence, ICP scoring, and cold email personalization</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <label
                className={`flex items-start p-4 border rounded-2xl cursor-pointer transition-all ${
                  formData.ai.provider === 'ollama'
                    ? 'border-indigo-600 bg-indigo-50/50 ring-2 ring-indigo-600/20'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                <input
                  type="radio"
                  name="provider"
                  value="ollama"
                  checked={formData.ai.provider === 'ollama'}
                  onChange={(e) => setFormData({ ...formData, ai: { ...formData.ai, provider: e.target.value } })}
                  className="mt-1 text-indigo-600 focus:ring-indigo-500"
                />
                <div className="ml-3">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-slate-900 text-sm">Ollama (Local LLM)</span>
                    <span className="text-[10px] bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded-full font-bold">Privacy First</span>
                  </div>
                  <p className="text-xs text-slate-500 mt-1">Runs 100% locally on your machine with zero external API fees or cloud data sharing.</p>
                </div>
              </label>

              <label
                className={`flex items-start p-4 border rounded-2xl cursor-pointer transition-all ${
                  formData.ai.provider === 'heuristic'
                    ? 'border-indigo-600 bg-indigo-50/50 ring-2 ring-indigo-600/20'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                <input
                  type="radio"
                  name="provider"
                  value="heuristic"
                  checked={formData.ai.provider === 'heuristic'}
                  onChange={(e) => setFormData({ ...formData, ai: { ...formData.ai, provider: e.target.value } })}
                  className="mt-1 text-indigo-600 focus:ring-indigo-500"
                />
                <div className="ml-3">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-slate-900 text-sm">Built-in Rule Engine</span>
                    <span className="text-[10px] bg-indigo-100 text-indigo-800 px-2 py-0.5 rounded-full font-bold">Fast &amp; Offline</span>
                  </div>
                  <p className="text-xs text-slate-500 mt-1">Smart algorithmic templates that generate outreach sequences instantly without any model downloads.</p>
                </div>
              </label>
            </div>

            {formData.ai.provider === 'ollama' && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5 pt-2 animate-fadeIn">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Ollama Base URL</label>
                  <input
                    type="text"
                    value={formData.ai.ollamaBaseUrl || 'http://localhost:11434'}
                    onChange={(e) => setFormData({ ...formData, ai: { ...formData.ai, ollamaBaseUrl: e.target.value } })}
                    className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-mono focus:ring-2 focus:ring-indigo-500 focus:outline-none bg-slate-50/50"
                    placeholder="http://localhost:11434"
                  />
                  <p className="text-[11px] text-slate-400 mt-1">Default local Ollama service port</p>
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Model Name</label>
                  <input
                    type="text"
                    value={formData.ai.model || 'llama3'}
                    onChange={(e) => setFormData({ ...formData, ai: { ...formData.ai, model: e.target.value } })}
                    className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-medium focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    placeholder="llama3, mistral, deepseek-r1, phi3"
                  />
                  <p className="text-[11px] text-slate-400 mt-1">e.g. llama3, mistral, deepseek-r1:8b</p>
                </div>
              </div>
            )}

            <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200/80 rounded-2xl p-4 text-xs text-blue-900 leading-relaxed">
              🔒 <strong>100% Private &amp; Offline:</strong> All AI processing is performed either locally through Ollama or via the built-in algorithmic engine. No company data or prospect details are sent to external third-party cloud AI vendors.
            </div>
          </div>
        )}

        {/* Tab 2: Sender Profile */}
        {activeTab === 'profile' && (
          <div className="bg-white rounded-3xl border border-slate-200/80 p-6 md:p-8 space-y-6 shadow-xs">
            <div>
              <h2 className="text-base font-bold text-slate-900">Your Business &amp; Outreach Pitch</h2>
              <p className="text-xs text-slate-500 mt-0.5">The AI engine uses this context to personalize sequence messages around how your product solves prospect pain points</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Your Company Name</label>
                <input
                  type="text"
                  value={formData.senderProfile.companyName}
                  onChange={(e) => setFormData({
                    ...formData,
                    senderProfile: { ...formData.senderProfile, companyName: e.target.value }
                  })}
                  className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-medium focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                  placeholder="e.g. TKSR Product Services"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Sender Name</label>
                <input
                  type="text"
                  value={formData.senderProfile.senderName}
                  onChange={(e) => setFormData({
                    ...formData,
                    senderProfile: { ...formData.senderProfile, senderName: e.target.value }
                  })}
                  className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-medium focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                  placeholder="e.g. Nagendra"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Sender Job Title</label>
                <input
                  type="text"
                  value={formData.senderProfile.senderTitle}
                  onChange={(e) => setFormData({
                    ...formData,
                    senderProfile: { ...formData.senderProfile, senderTitle: e.target.value }
                  })}
                  className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-medium focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                  placeholder="e.g. Business analyst"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Core Offering / Value Proposition</label>
              <textarea
                rows={3}
                value={formData.senderProfile.productDescription}
                onChange={(e) => setFormData({
                  ...formData,
                  senderProfile: { ...formData.senderProfile, productDescription: e.target.value }
                })}
                className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-medium focus:ring-2 focus:ring-indigo-500 focus:outline-none leading-relaxed"
                placeholder="Explain what your service or product does..."
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1">Call to Action (CTA) Pitch</label>
              <input
                type="text"
                value={formData.senderProfile.targetPitch}
                onChange={(e) => setFormData({
                  ...formData,
                  senderProfile: { ...formData.senderProfile, targetPitch: e.target.value }
                })}
                className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-medium focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                placeholder="e.g. A brief 10-minute demo to explore how this applies to your pipeline"
              />
            </div>
          </div>
        )}

        {/* Tab 3: SMTP Settings */}
        {activeTab === 'smtp' && (
          <div className="space-y-6">
            <div className="bg-white rounded-3xl border border-slate-200/80 p-6 md:p-8 space-y-6 shadow-xs">
              <div>
                <h2 className="text-base font-bold text-slate-900">Google Workspace / SMTP Mailer</h2>
                <p className="text-xs text-slate-500 mt-0.5">Connected to Google Workspace for real outbound email dispatch</p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                <div className="md:col-span-2">
                  <label className="block text-xs font-bold text-slate-700 mb-1">SMTP Server Host</label>
                  <input
                    type="text"
                    value={formData.smtp.host}
                    onChange={(e) => setFormData({
                      ...formData,
                      smtp: { ...formData.smtp, host: e.target.value }
                    })}
                    className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-mono focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    placeholder="smtp.gmail.com"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Port</label>
                  <input
                    type="number"
                    value={formData.smtp.port}
                    onChange={(e) => {
                      const portNum = Number(e.target.value);
                      setFormData({
                        ...formData,
                        smtp: {
                          ...formData.smtp,
                          port: portNum,
                          secure: portNum === 465 ? true : (portNum === 587 ? false : formData.smtp.secure)
                        }
                      });
                    }}
                    className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-mono focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    placeholder="587"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Sender Email / Username</label>
                  <input
                    type="text"
                    value={formData.smtp.user}
                    onChange={(e) => setFormData({
                      ...formData,
                      smtp: { ...formData.smtp, user: e.target.value }
                    })}
                    className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-medium focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    placeholder="nagendra@tksrproductservices.com"
                  />
                </div>

                <div>
                  <div className="flex justify-between items-center mb-1">
                    <label className="text-xs font-bold text-slate-700">Google App Password</label>
                    {formData.smtp.hasPass && (
                      <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded">✓ Password stored</span>
                    )}
                  </div>
                  <input
                    type="password"
                    placeholder={formData.smtp.hasPass ? '•••••••• (leave blank to keep current)' : '16-digit Google App Password'}
                    value={formData.smtp.pass}
                    onChange={(e) => setFormData({
                      ...formData,
                      smtp: { ...formData.smtp, pass: e.target.value }
                    })}
                    className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-mono focus:ring-2 focus:ring-indigo-500 focus:outline-none bg-slate-50/50"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">From Name</label>
                  <input
                    type="text"
                    value={formData.smtp.fromName}
                    onChange={(e) => setFormData({
                      ...formData,
                      smtp: { ...formData.smtp, fromName: e.target.value }
                    })}
                    className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-medium focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    placeholder="Nagendra"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">From Email</label>
                  <input
                    type="email"
                    value={formData.smtp.fromEmail}
                    onChange={(e) => setFormData({
                      ...formData,
                      smtp: { ...formData.smtp, fromEmail: e.target.value }
                    })}
                    className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-medium focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    placeholder="nagendra@tksrproductservices.com"
                  />
                </div>
              </div>
            </div>

            {/* Test Email Dispatcher */}
            <div className="bg-white rounded-3xl border border-slate-200/80 p-6 md:p-8 space-y-4 shadow-xs">
              <h3 className="text-sm font-bold text-slate-900">Live SMTP Verification Sender</h3>
              <p className="text-xs text-slate-500">Send an instant test email to verify your Google Workspace credentials.</p>

              <div className="flex flex-col sm:flex-row gap-3 max-w-lg">
                <input
                  type="email"
                  placeholder="Enter recipient email (e.g. your-email@gmail.com)"
                  value={testEmail}
                  onChange={(e) => setTestEmail(e.target.value)}
                  className="flex-1 px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                />
                <button
                  type="button"
                  onClick={handleTestSmtp}
                  disabled={testingSmtp || !testEmail}
                  className="px-5 py-2.5 bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold rounded-xl transition-all shadow-sm disabled:opacity-50 shrink-0"
                >
                  {testingSmtp ? 'Sending...' : 'Send Test Email'}
                </button>
              </div>

              {testResult && (
                <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-2xl text-xs text-emerald-900 space-y-1 animate-fadeIn">
                  <p className="font-bold">✓ Test email dispatched successfully!</p>
                  <p className="font-mono text-[11px] text-emerald-800">Message ID: {testResult.messageId}</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tab 4: Gmail Reply Tracking */}
        {activeTab === 'gmail' && (
          <div className="bg-white rounded-3xl border border-slate-200/80 p-6 md:p-8 space-y-6 shadow-xs animate-fadeIn">
            <div>
              <h2 className="text-base font-bold text-slate-900">Gmail OAuth 2.0 Reply Tracking</h2>
              <p className="text-xs text-slate-500 mt-1">
                Authorizes read-only access to detect prospect replies and match them to sent outreach sequences.
              </p>
            </div>

            {/* Connection Status Banner */}
            <div className={`p-5 rounded-2xl border flex flex-col md:flex-row items-start md:items-center justify-between gap-4 ${
              formData.gmailOAuth?.isConfigured
                ? 'bg-emerald-50/70 border-emerald-200 text-emerald-950'
                : 'bg-amber-50/70 border-amber-200 text-amber-950'
            }`}>
              <div className="flex items-center gap-3">
                <span className="text-2xl">{formData.gmailOAuth?.isConfigured ? '🟢' : '🟡'}</span>
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider">
                    {formData.gmailOAuth?.isConfigured ? 'Gmail Connected (Read-Only Active)' : 'Authorization Pending'}
                  </h4>
                  <p className="text-xs opacity-80 mt-0.5">
                    {formData.gmailOAuth?.isConfigured
                      ? `Connected account: ${formData.gmailOAuth.userEmail || 'nagendra@tksrproductservices.com'} (Refresh token stored)`
                      : 'Client credentials saved. Authorize access to begin tracking incoming replies.'}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                {formData.gmailOAuth?.isConfigured ? (
                  <>
                    <button
                      type="button"
                      onClick={handleSyncGmailNow}
                      disabled={syncingGmail}
                      className="px-4 py-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white text-xs font-bold rounded-xl transition-all shadow-xs flex items-center gap-1.5 disabled:opacity-50"
                      title="Fetch recent replies from read-only Gmail inbox"
                    >
                      <span className={syncingGmail ? 'animate-spin' : ''}>{syncingGmail ? '🔄' : '📥'}</span>
                      <span>{syncingGmail ? 'Syncing...' : 'Sync Gmail Replies Now'}</span>
                    </button>
                    <button
                      type="button"
                      onClick={handleDisconnectGmail}
                      disabled={disconnectingGmail}
                      className="px-4 py-2 bg-white border border-rose-200 text-rose-700 hover:bg-rose-50 text-xs font-bold rounded-xl transition-all shadow-xs disabled:opacity-50"
                    >
                      {disconnectingGmail ? 'Disconnecting...' : 'Disconnect Account'}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={handleConnectGmail}
                    disabled={connectingGmail || !formData.gmailOAuth?.clientId}
                    className="px-5 py-2.5 bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-700 hover:to-blue-700 text-white text-xs font-bold rounded-xl transition-all shadow-md flex items-center gap-2 disabled:opacity-50"
                  >
                    <span>{connectingGmail ? '⏳' : '🔑'}</span>
                    <span>{connectingGmail ? 'Redirecting to Google...' : 'Authorize with Google'}</span>
                  </button>
                )}
              </div>
            </div>

            {/* Sync Result Metrics Banner */}
            {gmailSyncResult && (
              <div className="p-4 bg-emerald-50/90 border border-emerald-200 rounded-2xl text-xs text-emerald-950 space-y-3 animate-fadeIn">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-bold flex items-center gap-1.5">
                      <span>✓</span> {gmailSyncResult.message}
                    </span>
                  </div>
                  <Link
                    to="/outbox"
                    className="text-xs font-bold text-indigo-700 hover:text-indigo-900 underline flex items-center gap-1"
                  >
                    <span>Open Outreach Outbox &rarr;</span>
                  </Link>
                </div>
                {gmailSyncResult.stats && (
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 pt-1 font-mono text-[11px]">
                    <div className="bg-white/80 p-2.5 rounded-xl border border-emerald-200/60 shadow-2xs">
                      <span className="text-slate-500 block text-[10px] font-sans font-bold uppercase">Total Checked</span>
                      <strong className="text-base text-slate-800">{gmailSyncResult.stats.total ?? 0}</strong>
                    </div>
                    <div className="bg-white/80 p-2.5 rounded-xl border border-emerald-200/60 shadow-2xs">
                      <span className="text-emerald-700 block text-[10px] font-sans font-bold uppercase">Matched</span>
                      <strong className="text-base text-emerald-700">{gmailSyncResult.stats.correlated ?? 0}</strong>
                    </div>
                    <div className="bg-white/80 p-2.5 rounded-xl border border-emerald-200/60 shadow-2xs">
                      <span className="text-amber-700 block text-[10px] font-sans font-bold uppercase">Unmatched/Review</span>
                      <strong className="text-base text-amber-700">{gmailSyncResult.stats.unmatched ?? 0}</strong>
                    </div>
                    <div className="bg-white/80 p-2.5 rounded-xl border border-emerald-200/60 shadow-2xs">
                      <span className="text-blue-700 block text-[10px] font-sans font-bold uppercase">New Ingested</span>
                      <strong className="text-base text-blue-700">{gmailSyncResult.stats.inserted ?? 0}</strong>
                    </div>
                    <div className="bg-white/80 p-2.5 rounded-xl border border-emerald-200/60 shadow-2xs">
                      <span className="text-slate-500 block text-[10px] font-sans font-bold uppercase">Already Skipped</span>
                      <strong className="text-base text-slate-700">{gmailSyncResult.stats.alreadyProcessed ?? 0}</strong>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Client Credentials Form */}
            <div className="space-y-4 pt-2">
              <h3 className="text-xs font-bold uppercase text-slate-400 tracking-wider">OAuth Client Configuration</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1">Google OAuth Client ID</label>
                  <input
                    type="text"
                    value={formData.gmailOAuth.clientId}
                    onChange={(e) => setFormData({
                      ...formData,
                      gmailOAuth: { ...formData.gmailOAuth, clientId: e.target.value }
                    })}
                    className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-mono focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                    placeholder="...apps.googleusercontent.com"
                  />
                </div>

                <div>
                  <div className="flex justify-between items-center mb-1">
                    <label className="text-xs font-bold text-slate-700">Client Secret</label>
                    {formData.gmailOAuth.hasClientSecret && (
                      <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded">✓ Secret stored</span>
                    )}
                  </div>
                  <input
                    type="password"
                    placeholder={formData.gmailOAuth.hasClientSecret ? '•••••••• (leave blank to keep current)' : 'Google OAuth Client Secret'}
                    value={formData.gmailOAuth.clientSecret}
                    onChange={(e) => setFormData({
                      ...formData,
                      gmailOAuth: { ...formData.gmailOAuth, clientSecret: e.target.value }
                    })}
                    className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-mono focus:ring-2 focus:ring-indigo-500 focus:outline-none bg-slate-50/50"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1">Gmail Account Address (Login Hint)</label>
                <input
                  type="email"
                  value={formData.gmailOAuth.userEmail}
                  onChange={(e) => setFormData({
                    ...formData,
                    gmailOAuth: { ...formData.gmailOAuth, userEmail: e.target.value }
                  })}
                  className="w-full md:w-1/2 px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-medium focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                  placeholder="nagendra@tksrproductservices.com"
                />
              </div>
            </div>

            {/* Desktop / Manual Code Exchange Box */}
            {!formData.gmailOAuth?.isConfigured && (
              <div className="border border-slate-200/80 rounded-2xl p-5 bg-slate-50/50 space-y-3">
                <div className="flex items-center gap-2">
                  <span className="text-base">📋</span>
                  <h4 className="text-xs font-bold text-slate-800">Desktop / Manual Authorization Code Exchange</h4>
                </div>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  If using a Desktop App client or manual code flow, paste the authorization code returned by Google below to complete the handshake:
                </p>
                <form onSubmit={handleExchangeManualCode} className="flex flex-col sm:flex-row gap-3">
                  <input
                    type="text"
                    placeholder="Paste 4/... authorization code here"
                    value={manualCode}
                    onChange={(e) => setManualCode(e.target.value)}
                    className="flex-1 px-3.5 py-2 border border-slate-200 rounded-xl text-xs font-mono focus:ring-2 focus:ring-indigo-500 focus:outline-none bg-white"
                  />
                  <button
                    type="submit"
                    disabled={exchangingCode || !manualCode.trim()}
                    className="px-5 py-2 bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold rounded-xl transition-all shadow-xs disabled:opacity-50 shrink-0"
                  >
                    {exchangingCode ? 'Exchanging Code...' : 'Exchange Code & Connect'}
                  </button>
                </form>
              </div>
            )}

            <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200/80 rounded-2xl p-4 text-xs text-blue-900 leading-relaxed space-y-1">
              <p>🔒 <strong>Strictly Read-Only Scope:</strong> Only requests <code>https://www.googleapis.com/auth/gmail.readonly</code>. The outreach tool cannot send emails, delete messages, modify drafts, or alter your Gmail inbox settings through this connection.</p>
            </div>
          </div>
        )}

        <div className="flex justify-end pt-2">
          <button
            type="submit"
            disabled={saving}
            className="px-8 py-3 bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-700 hover:to-blue-700 text-white rounded-xl text-xs font-bold shadow-md shadow-indigo-600/20 transition-all hover:scale-102 disabled:opacity-50"
          >
            {saving ? 'Saving Changes...' : 'Save Configuration'}
          </button>
        </div>
      </form>
    </div>
  );
}
