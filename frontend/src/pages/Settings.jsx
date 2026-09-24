import { useState, useEffect } from 'react';
import api from '../api';

export default function Settings() {
  const [activeTab, setActiveTab] = useState('ai');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingSmtp, setTestingSmtp] = useState(false);
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
      setTestResult(res.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setTestingSmtp(false);
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
        <h1 className="text-2xl font-black tracking-tight text-slate-900">Platform Settings &amp; SMTP</h1>
        <p className="text-xs text-slate-500 mt-0.5">
          Configure your AI engine, pitch profile, and outbound Google Workspace / SMTP credentials.
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
                    onChange={(e) => setFormData({
                      ...formData,
                      smtp: { ...formData.smtp, port: Number(e.target.value) }
                    })}
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
