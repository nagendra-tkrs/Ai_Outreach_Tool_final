import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';

export default function Dashboard() {
  const [stats, setStats] = useState({
    totalCompanies: 0,
    crawledCompanies: 0,
    researchedCompanies: 0,
    emailsSent: 0,
    openRate: 0,
    loading: true,
  });

  useEffect(() => {
    const fetchDashboardStats = async () => {
      try {
        const [compRes, outboxRes] = await Promise.all([
          api.get('/companies?limit=1000').catch(() => ({ data: { companies: [], pagination: { total: 0 } } })),
          api.get('/outreach/all').catch(() => ({ data: [] })),
        ]);

        const companies = compRes.data?.companies || [];
        const total = compRes.data?.pagination?.total || companies.length;
        const crawled = companies.filter((c) => c.crawlStatus === 'completed').length;
        const researched = companies.filter((c) => c.researchStatus === 'completed').length;
        const sentMessages = (outboxRes.data || []).filter((m) => m.status === 'sent');
        const openedMessages = sentMessages.filter((m) => m.openCount > 0);
        const openRate = sentMessages.length > 0 ? Math.round((openedMessages.length / sentMessages.length) * 100) : 0;

        setStats({
          totalCompanies: total,
          crawledCompanies: crawled,
          researchedCompanies: researched,
          emailsSent: sentMessages.length,
          openRate: openRate,
          loading: false,
        });
      } catch {
        setStats((prev) => ({ ...prev, loading: false }));
      }
    };
    fetchDashboardStats();
  }, []);

  const pipelineSteps = [
    { num: '01', title: 'Excel Import', desc: 'Ingest company datasets & auto-map column headers', icon: '📥', to: '/import', gradient: 'from-blue-500 to-cyan-500' },
    { num: '02', title: 'Web Crawl', desc: 'Priority BFS crawler extracts multi-page content', icon: '🌐', to: '/companies', gradient: 'from-cyan-500 to-teal-500' },
    { num: '03', title: 'AI Research', desc: 'Synthesizes pain points, ICP score & icebreakers', icon: '🧠', to: '/companies', gradient: 'from-purple-500 to-indigo-500' },
    { num: '04', title: 'Decision Makers', desc: 'Extracts leadership & predicts work emails', icon: '👥', to: '/companies', gradient: 'from-indigo-500 to-blue-500' },
    { num: '05', title: 'Personalized Dispatch', desc: 'Sends 3-step sequence from your verified SMTP', icon: '✉️', to: '/outbox', gradient: 'from-emerald-500 to-teal-500' },
  ];

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Modern Hero Header Banner */}
      <div className="relative overflow-hidden rounded-3xl bg-gradient-to-r from-slate-900 via-indigo-950 to-slate-900 p-8 md:p-10 text-white shadow-xl border border-slate-800">
        <div className="absolute top-0 right-0 -mr-16 -mt-16 w-80 h-80 rounded-full bg-indigo-500/15 blur-3xl pointer-events-none" />
        <div className="absolute bottom-0 right-1/3 -mb-16 w-60 h-60 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />

        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="max-w-2xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/20 border border-indigo-500/30 text-indigo-300 text-xs font-semibold uppercase tracking-wider mb-4">
              <span className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse"></span>
              Autonomous Client Acquisition Engine
            </div>
            <h1 className="text-3xl md:text-4xl font-extrabold tracking-tight text-white leading-tight">
              B2B Client Research &amp; Personalized Outreach
            </h1>
            <p className="text-slate-300 text-sm md:text-base mt-2.5 leading-relaxed">
              Upload lead sheets, automatically crawl websites, extract real decision makers, and send hyper-personalized multi-touch cold email sequences directly from <span className="text-indigo-300 font-semibold underline decoration-indigo-400">nagendra@tksrproductservices.com</span>.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row gap-3 shrink-0">
            <Link
              to="/import"
              className="px-5 py-3 rounded-xl bg-gradient-to-r from-indigo-500 to-blue-600 hover:from-indigo-600 hover:to-blue-700 text-white font-bold text-sm shadow-lg shadow-indigo-500/25 transition-all hover:scale-102 flex items-center justify-center gap-2"
            >
              <span>📥</span>
              <span>Import Leads</span>
            </Link>
            <Link
              to="/companies"
              className="px-5 py-3 rounded-xl bg-white/10 hover:bg-white/15 text-white font-bold text-sm border border-white/20 transition-all flex items-center justify-center gap-2 backdrop-blur-sm"
            >
              <span>🏢</span>
              <span>View Directory</span>
            </Link>
          </div>
        </div>
      </div>

      {/* KPI Metrics Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        {/* Card 1: Total Companies */}
        <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-sm hover:shadow-md transition-all duration-200 hover:-translate-y-0.5 relative overflow-hidden group">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Total Leads</span>
            <div className="w-9 h-9 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center text-lg group-hover:scale-110 transition-transform">
              🏢
            </div>
          </div>
          <p className="text-3xl font-black text-slate-900 mt-3 tracking-tight">
            {stats.loading ? '—' : stats.totalCompanies}
          </p>
          <p className="text-[11px] text-slate-400 mt-1 font-medium">In Pipeline Database</p>
        </div>

        {/* Card 2: Websites Crawled */}
        <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-sm hover:shadow-md transition-all duration-200 hover:-translate-y-0.5 relative overflow-hidden group">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Websites Crawled</span>
            <div className="w-9 h-9 rounded-xl bg-cyan-50 text-cyan-600 flex items-center justify-center text-lg group-hover:scale-110 transition-transform">
              🌐
            </div>
          </div>
          <p className="text-3xl font-black text-cyan-600 mt-3 tracking-tight">
            {stats.loading ? '—' : stats.crawledCompanies}
          </p>
          <p className="text-[11px] text-slate-400 mt-1 font-medium">Multi-Page Indexed</p>
        </div>

        {/* Card 3: AI Researched */}
        <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-sm hover:shadow-md transition-all duration-200 hover:-translate-y-0.5 relative overflow-hidden group">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">AI Researched</span>
            <div className="w-9 h-9 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center text-lg group-hover:scale-110 transition-transform">
              🧠
            </div>
          </div>
          <p className="text-3xl font-black text-purple-600 mt-3 tracking-tight">
            {stats.loading ? '—' : stats.researchedCompanies}
          </p>
          <p className="text-[11px] text-slate-400 mt-1 font-medium">ICP Scored &amp; Analyzed</p>
        </div>

        {/* Card 4: Emails Dispatched */}
        <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-sm hover:shadow-md transition-all duration-200 hover:-translate-y-0.5 relative overflow-hidden group">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Emails Sent</span>
            <div className="w-9 h-9 rounded-xl bg-emerald-50 text-emerald-600 flex items-center justify-center text-lg group-hover:scale-110 transition-transform">
              🚀
            </div>
          </div>
          <p className="text-3xl font-black text-emerald-600 mt-3 tracking-tight">
            {stats.loading ? '—' : stats.emailsSent}
          </p>
          <p className="text-[11px] text-slate-400 mt-1 font-medium">Dispatched via SMTP</p>
        </div>

        {/* Card 5: Open Rate */}
        <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-sm hover:shadow-md transition-all duration-200 hover:-translate-y-0.5 relative overflow-hidden group">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Open Rate</span>
            <div className="w-9 h-9 rounded-xl bg-indigo-50 text-indigo-600 flex items-center justify-center text-lg group-hover:scale-110 transition-transform">
              👁️
            </div>
          </div>
          <p className="text-3xl font-black text-indigo-600 mt-3 tracking-tight">
            {stats.loading ? '—' : `${stats.openRate || 0}%`}
          </p>
          <p className="text-[11px] text-slate-400 mt-1 font-medium">Tracking Pixel Verified</p>
        </div>
      </div>

      {/* 5-Phase Visual Roadmap Architecture */}
      <div className="bg-white rounded-3xl border border-slate-200/80 p-6 md:p-8 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-6">
          <div>
            <h2 className="text-lg font-bold text-slate-900">5-Phase Pipeline Architecture</h2>
            <p className="text-xs text-slate-500 mt-0.5">End-to-end workflow from raw Excel leads to verified sequence dispatch</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            <span className="text-xs font-bold text-emerald-700 bg-emerald-50 px-3 py-1 rounded-full border border-emerald-200">
              All 5 Phases Operational
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
          {pipelineSteps.map((step, idx) => (
            <Link
              key={step.num}
              to={step.to}
              className="relative p-5 rounded-2xl bg-gradient-to-b from-slate-50 to-white border border-slate-200/80 hover:border-indigo-300 hover:shadow-md transition-all duration-200 flex flex-col justify-between group hover:-translate-y-1"
            >
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className={`w-10 h-10 rounded-xl bg-gradient-to-r ${step.gradient} text-white flex items-center justify-center text-lg shadow-sm`}>
                    {step.icon}
                  </div>
                  <span className="text-xs font-black text-slate-300 group-hover:text-indigo-600 transition-colors">
                    Phase {step.num}
                  </span>
                </div>
                <h3 className="font-bold text-slate-900 text-sm group-hover:text-indigo-600 transition-colors">
                  {step.title}
                </h3>
                <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">
                  {step.desc}
                </p>
              </div>

              <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between text-xs font-bold text-indigo-600">
                <span>Launch Step</span>
                <span className="group-hover:translate-x-1 transition-transform">&rarr;</span>
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* Quick Launchpad & Features */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Launchpad 1 */}
        <Link
          to="/import"
          className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-sm hover:shadow-md transition-all hover:-translate-y-0.5 group flex items-start gap-4"
        >
          <div className="w-12 h-12 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center text-2xl shrink-0 group-hover:scale-110 transition-transform">
            📥
          </div>
          <div>
            <h3 className="font-bold text-slate-900 text-base group-hover:text-blue-600 transition-colors">
              Import Excel Leads
            </h3>
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">
              Upload multi-column B2B spreadsheets with automatic header mapping and duplicate detection.
            </p>
          </div>
        </Link>

        {/* Launchpad 2 */}
        <Link
          to="/companies"
          className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-sm hover:shadow-md transition-all hover:-translate-y-0.5 group flex items-start gap-4"
        >
          <div className="w-12 h-12 rounded-2xl bg-purple-50 text-purple-600 flex items-center justify-center text-2xl shrink-0 group-hover:scale-110 transition-transform">
            ⚡
          </div>
          <div>
            <h3 className="font-bold text-slate-900 text-base group-hover:text-purple-600 transition-colors">
              Bulk Pipeline Runner
            </h3>
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">
              Select multiple companies to run automated Bulk Crawling, AI Research, and Sequence Generation in 1 click.
            </p>
          </div>
        </Link>

        {/* Launchpad 3 */}
        <Link
          to="/outbox"
          className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-sm hover:shadow-md transition-all hover:-translate-y-0.5 group flex items-start gap-4"
        >
          <div className="w-12 h-12 rounded-2xl bg-emerald-50 text-emerald-600 flex items-center justify-center text-2xl shrink-0 group-hover:scale-110 transition-transform">
            📬
          </div>
          <div>
            <h3 className="font-bold text-slate-900 text-base group-hover:text-emerald-600 transition-colors">
              Outbox &amp; Drip Scheduler
            </h3>
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">
              Track live email opens, link clicks, automated drip schedules, and multi-channel LinkedIn copy.
            </p>
          </div>
        </Link>
      </div>
    </div>
  );
}
