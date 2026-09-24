import { NavLink, Outlet, useLocation } from 'react-router-dom';

const navItems = [
  { to: '/', label: 'Dashboard', icon: '📊', description: 'Overview & pipeline metrics' },
  { to: '/import', label: 'Excel Ingestion', icon: '📥', description: 'Upload B2B leads' },
  { to: '/companies', label: 'Companies', icon: '🏢', description: 'Crawl, research & leads' },
  { to: '/outbox', label: 'Tracking & Outbox', icon: '✉️', description: 'Email tracker & Excel export' },
  { to: '/settings', label: 'Settings & SMTP', icon: '⚙️', description: 'AI keys & email dispatch' },
];

export default function Layout() {
  const location = useLocation();

  return (
    <div className="min-h-screen bg-slate-50/70 flex flex-col md:flex-row antialiased selection:bg-indigo-500 selection:text-white">
      {/* Sleek Modern Sidebar */}
      <aside className="w-full md:w-72 bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 text-white flex flex-col shrink-0 border-r border-slate-800/80 shadow-2xl relative z-20">
        {/* Brand Header */}
        <div className="p-6 border-b border-slate-800/70">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-blue-600 to-cyan-400 p-0.5 shadow-lg shadow-indigo-500/20 flex items-center justify-center">
              <span className="text-xl">⚡</span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-extrabold tracking-tight text-white">OutreachAI</h1>
                <span className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                  v2.0
                </span>
              </div>
              <p className="text-[11px] text-slate-400 font-medium mt-0.5">Autonomous B2B Pipeline</p>
            </div>
          </div>
        </div>

        {/* Navigation Items */}
        <nav className="flex-1 p-4 space-y-1.5 overflow-y-auto">
          <p className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-500">
            Pipeline Navigation
          </p>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `group flex items-center gap-3.5 px-3.5 py-3 rounded-xl text-sm transition-all duration-200 relative ${
                  isActive
                    ? 'bg-gradient-to-r from-indigo-600 to-blue-600 text-white font-semibold shadow-lg shadow-indigo-600/30'
                    : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/60'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-base transition-colors ${
                    isActive ? 'bg-white/20 text-white' : 'bg-slate-800/80 text-slate-400 group-hover:bg-slate-700/80 group-hover:text-slate-200'
                  }`}>
                    {item.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold truncate leading-tight">{item.label}</p>
                    <p className={`text-[11px] truncate mt-0.5 ${isActive ? 'text-indigo-100/90' : 'text-slate-500 group-hover:text-slate-400'}`}>
                      {item.description}
                    </p>
                  </div>
                  {isActive && (
                    <span className="w-1.5 h-6 bg-white rounded-full absolute right-2" />
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Sender Profile & System Status Badge */}
        <div className="p-4 border-t border-slate-800/70 space-y-3">
          {/* Active Sender Card */}
          <div className="bg-slate-800/50 rounded-xl p-3 border border-slate-800 text-xs">
            <div className="flex items-center justify-between text-slate-400 mb-1">
              <span className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Active Sender</span>
              <span className="text-[10px] text-indigo-400 font-bold">Google SMTP</span>
            </div>
            <p className="text-slate-200 font-semibold truncate">nagendra@tksrproductservices.com</p>
          </div>

          {/* Engine Status */}
          <div className="bg-slate-900/90 rounded-xl p-3 border border-slate-800/80 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
              <span className="text-slate-300 font-medium text-[11px]">Pipeline Active</span>
            </div>
            <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
              5 Phases Live
            </span>
          </div>
        </div>
      </aside>

      {/* Main Workspace Container */}
      <main className="flex-1 flex flex-col min-w-0 overflow-y-auto">
        {/* Top Header Bar */}
        <header className="h-16 bg-white/80 backdrop-blur-md border-b border-slate-200/80 sticky top-0 z-10 px-8 flex items-center justify-between shadow-xs">
          <div className="flex items-center gap-3">
            <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Workspace</span>
            <span className="text-slate-300">/</span>
            <span className="text-sm font-semibold text-slate-800 capitalize">
              {location.pathname === '/' ? 'Dashboard' : location.pathname.split('/')[1]?.replace('-', ' ')}
            </span>
          </div>

          <div className="flex items-center gap-4">
            <div className="hidden sm:flex items-center gap-2 text-xs font-medium text-slate-500 bg-slate-100/80 px-3 py-1.5 rounded-full border border-slate-200/60">
              <span>🤖</span>
              <span>AI Engine: Local Ollama &amp; Deep Crawl</span>
            </div>
            <a
              href="http://localhost:5000/api/health"
              target="_blank"
              rel="noreferrer"
              className="text-xs font-semibold text-indigo-600 hover:text-indigo-700 bg-indigo-50 hover:bg-indigo-100/80 px-3 py-1.5 rounded-lg transition-colors border border-indigo-100 flex items-center gap-1.5"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-600"></span>
              <span>API Live</span>
            </a>
          </div>
        </header>

        {/* Content Body */}
        <div className="max-w-7xl w-full mx-auto p-6 md:p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
