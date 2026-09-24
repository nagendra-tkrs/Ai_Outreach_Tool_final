import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';

const CRAWL_STATUS_STYLES = {
  pending: 'bg-slate-100 text-slate-600 border-slate-200',
  crawling: 'bg-blue-50 text-blue-700 border-blue-200 animate-pulse',
  completed: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  blocked: 'bg-amber-50 text-amber-800 border-amber-300',
  failed: 'bg-red-50 text-red-700 border-red-200',
};

const RESEARCH_STATUS_STYLES = {
  pending: 'bg-slate-100 text-slate-500 border-slate-200',
  researching: 'bg-purple-50 text-purple-700 border-purple-200 animate-pulse',
  completed: 'bg-purple-50 text-purple-800 border-purple-200',
  failed: 'bg-red-50 text-red-700 border-red-200',
};

const OUTREACH_STATUS_STYLES = {
  none: 'bg-slate-100 text-slate-400 border-slate-200',
  generated: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  sent: 'bg-emerald-50 text-emerald-700 border-emerald-200',
};

export default function CompanyList() {
  const [companies, setCompanies] = useState([]);
  const [pagination, setPagination] = useState({ total: 0, page: 1, pages: 1 });
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [crawlingId, setCrawlingId] = useState(null);

  // Bulk Actions State
  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkProcessing, setBulkProcessing] = useState(false);
  const [bulkStatusText, setBulkStatusText] = useState('');

  const fetchCompanies = async (page = 1, query = '') => {
    setLoading(true);
    try {
      const res = await api.get('/companies', {
        params: { page, limit: 20, search: query },
      });
      setCompanies(res.data.companies);
      setPagination(res.data.pagination);
    } catch (err) {
      console.error('Failed to load companies:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCompanies();
  }, []);

  const handleSearch = (e) => {
    e.preventDefault();
    fetchCompanies(1, search);
  };

  const handlePageChange = (page) => {
    fetchCompanies(page, search);
  };

  const handleCrawl = async (companyId) => {
    setCrawlingId(companyId);
    try {
      await api.post(`/companies/${companyId}/crawl`);
      await fetchCompanies(pagination.page, search);
    } catch (err) {
      console.error('Crawl failed:', err);
    } finally {
      setCrawlingId(null);
    }
  };

  // Bulk Select Handlers
  const handleSelectAll = () => {
    if (selectedIds.length === companies.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(companies.map((c) => c._id));
    }
  };

  const handleToggleSelect = (id) => {
    if (selectedIds.includes(id)) {
      setSelectedIds(selectedIds.filter((item) => item !== id));
    } else {
      setSelectedIds([...selectedIds, id]);
    }
  };

  // Bulk Action Execution
  const handleBulkCrawl = async () => {
    if (selectedIds.length === 0) return;
    setBulkProcessing(true);
    setBulkStatusText(`Crawling ${selectedIds.length} websites...`);
    try {
      for (const id of selectedIds) {
        try {
          await api.post(`/companies/${id}/crawl`, null, { timeout: 600000 });
        } catch {
          // ignore single fail
        }
      }
      await fetchCompanies(pagination.page, search);
      setBulkStatusText(`Bulk crawl complete!`);
      setTimeout(() => setBulkStatusText(''), 3000);
    } finally {
      setBulkProcessing(false);
    }
  };

  const handleBulkResearch = async () => {
    if (selectedIds.length === 0) return;
    setBulkProcessing(true);
    setBulkStatusText(`Synthesizing AI research for ${selectedIds.length} companies...`);
    try {
      for (const id of selectedIds) {
        try {
          await api.post(`/companies/${id}/research`, null, { timeout: 900000 });
        } catch {
          // ignore single fail
        }
      }
      await fetchCompanies(pagination.page, search);
      setBulkStatusText(`Bulk AI research complete!`);
      setTimeout(() => setBulkStatusText(''), 3000);
    } finally {
      setBulkProcessing(false);
    }
  };

  const handleBulkOutreach = async () => {
    if (selectedIds.length === 0) return;
    setBulkProcessing(true);
    setBulkStatusText(`Generating 3-step outreach for ${selectedIds.length} companies...`);
    try {
      await api.post('/outreach/bulk-generate', {
        companyIds: selectedIds,
        options: { angle: 'pain_point', tone: 'conversational' },
      });
      await fetchCompanies(pagination.page, search);
      setBulkStatusText(`Bulk sequences generated!`);
      setTimeout(() => setBulkStatusText(''), 3000);
    } finally {
      setBulkProcessing(false);
    }
  };

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header & Search Toolbar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black tracking-tight text-slate-900">Company Pipeline</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            {pagination.total} verified company profiles ready for research and personalized outreach
          </p>
        </div>

        <div className="flex items-center gap-3">
          <form onSubmit={handleSearch} className="relative flex items-center">
            <span className="absolute left-3.5 text-slate-400 text-sm">🔍</span>
            <input
              type="text"
              placeholder="Search companies, website, industry..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 pr-20 py-2 bg-white border border-slate-200 rounded-xl text-xs font-medium text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent w-72 shadow-xs transition-all"
            />
            {search && (
              <button
                type="button"
                onClick={() => {
                  setSearch('');
                  fetchCompanies(1, '');
                }}
                className="absolute right-12 text-slate-400 hover:text-slate-600 text-xs font-bold"
              >
                &times;
              </button>
            )}
            <button
              type="submit"
              className="absolute right-1.5 px-2.5 py-1 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-bold transition-colors"
            >
              Go
            </button>
          </form>

          <Link
            to="/import"
            className="px-4 py-2 bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-700 hover:to-blue-700 text-white rounded-xl text-xs font-bold shadow-sm transition-all hover:scale-102 flex items-center gap-1.5 shrink-0"
          >
            <span>+</span>
            <span>Import Leads</span>
          </Link>
        </div>
      </div>

      {/* Floating Glassmorphic Bulk Action Bar */}
      {selectedIds.length > 0 && (
        <div className="bg-gradient-to-r from-indigo-900/95 via-slate-900/95 to-indigo-900/95 backdrop-blur-md border border-indigo-500/30 rounded-2xl p-4 shadow-xl flex flex-col md:flex-row items-center justify-between gap-4 text-white animate-fadeIn">
          <div className="flex items-center gap-3">
            <span className="w-8 h-8 rounded-xl bg-indigo-500 text-white flex items-center justify-center font-black text-sm shadow-md">
              {selectedIds.length}
            </span>
            <div>
              <p className="font-bold text-sm text-white">Companies Selected</p>
              <p className="text-[11px] text-indigo-300">Run parallel automated operations on selected prospects</p>
            </div>
            {bulkStatusText && (
              <span className="text-xs text-indigo-200 bg-indigo-800/80 px-3 py-1 rounded-full font-semibold border border-indigo-400/30 animate-pulse">
                {bulkStatusText}
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={handleBulkCrawl}
              disabled={bulkProcessing}
              className="px-3.5 py-2 bg-white/10 hover:bg-white/20 border border-white/20 text-white rounded-xl text-xs font-bold transition-colors disabled:opacity-50 flex items-center gap-1.5"
            >
              <span>🌐</span>
              <span>Bulk Crawl</span>
            </button>
            <button
              onClick={handleBulkResearch}
              disabled={bulkProcessing}
              className="px-3.5 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-bold transition-colors disabled:opacity-50 flex items-center gap-1.5 shadow-md shadow-purple-600/30"
            >
              <span>✨</span>
              <span>Bulk AI Research</span>
            </button>
            <button
              onClick={handleBulkOutreach}
              disabled={bulkProcessing}
              className="px-3.5 py-2 bg-gradient-to-r from-indigo-500 to-blue-600 hover:from-indigo-600 hover:to-blue-700 text-white rounded-xl text-xs font-bold transition-colors disabled:opacity-50 flex items-center gap-1.5 shadow-md shadow-indigo-500/30"
            >
              <span>🚀</span>
              <span>Bulk Generate Outreach</span>
            </button>
            <button
              onClick={() => setSelectedIds([])}
              className="px-3 py-2 text-xs text-slate-400 hover:text-slate-200 font-medium ml-2"
            >
              Clear Selection
            </button>
          </div>
        </div>
      )}

      {/* Main Table */}
      {loading ? (
        <div className="bg-white rounded-2xl border border-slate-200 p-16 text-center text-slate-400">
          <div className="inline-block w-8 h-8 border-3 border-indigo-600 border-t-transparent rounded-full animate-spin mb-3"></div>
          <p className="font-semibold text-sm">Loading company pipeline...</p>
        </div>
      ) : companies.length === 0 ? (
        <div className="bg-white rounded-3xl border border-slate-200 p-16 text-center">
          <div className="w-16 h-16 rounded-3xl bg-slate-100 text-slate-600 flex items-center justify-center text-3xl mx-auto mb-4">
            🏢
          </div>
          <h3 className="font-bold text-slate-900 text-lg">No companies found</h3>
          <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1 mb-6">
            Upload an Excel sheet with your client list to begin automated crawling, AI research, and personalized sequence dispatch.
          </p>
          <Link
            to="/import"
            className="inline-block px-5 py-2.5 bg-gradient-to-r from-indigo-600 to-blue-600 text-white rounded-xl text-xs font-bold shadow-md hover:from-indigo-700 hover:to-blue-700"
          >
            Import Leads Spreadsheet
          </Link>
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-slate-200/80 overflow-hidden shadow-xs">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50/80 border-b border-slate-200/80 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                <tr>
                  <th className="px-4 py-3.5 w-10">
                    <input
                      type="checkbox"
                      checked={selectedIds.length === companies.length && companies.length > 0}
                      onChange={handleSelectAll}
                      className="rounded text-indigo-600 focus:ring-indigo-500 h-4 w-4 cursor-pointer"
                    />
                  </th>
                  <th className="px-5 py-3.5">Company &amp; Domain</th>
                  <th className="px-5 py-3.5">Industry &amp; Region</th>
                  <th className="px-4 py-3.5">Crawl Status</th>
                  <th className="px-4 py-3.5">AI Intelligence</th>
                  <th className="px-4 py-3.5">Outreach</th>
                  <th className="px-5 py-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {companies.map((company) => {
                  const isSelected = selectedIds.includes(company._id);
                  const initial = company.companyName ? company.companyName.charAt(0).toUpperCase() : 'C';
                  return (
                    <tr
                      key={company._id}
                      className={`transition-colors duration-150 ${
                        isSelected ? 'bg-indigo-50/40' : 'hover:bg-slate-50/80'
                      }`}
                    >
                      <td className="px-4 py-4">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => handleToggleSelect(company._id)}
                          className="rounded text-indigo-600 focus:ring-indigo-500 h-4 w-4 cursor-pointer"
                        />
                      </td>

                      <td className="px-5 py-4">
                        <div className="flex items-center gap-3">
                          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-slate-800 to-indigo-700 text-white font-black text-sm flex items-center justify-center shrink-0 shadow-xs">
                            {initial}
                          </div>
                          <div className="min-w-0">
                            <Link
                              to={`/companies/${company._id}`}
                              className="font-bold text-slate-900 hover:text-indigo-600 truncate block text-sm transition-colors"
                            >
                              {company.companyName}
                            </Link>
                            <a
                              href={company.website}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs text-indigo-600 hover:underline inline-flex items-center gap-0.5 truncate max-w-xs mt-0.5"
                            >
                              <span>{company.website?.replace(/https?:\/\//, '')}</span>
                              <span className="text-[10px]">&rarr;</span>
                            </a>
                          </div>
                        </div>
                      </td>

                      <td className="px-5 py-4">
                        <span className="font-semibold text-slate-800 block truncate max-w-[160px]">
                          {company.industry || 'General B2B'}
                        </span>
                        <span className="text-[11px] text-slate-400 font-medium">
                          {company.country || 'Global'}
                        </span>
                      </td>

                      <td className="px-4 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold uppercase border ${CRAWL_STATUS_STYLES[company.crawlStatus || 'pending']}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${company.crawlStatus === 'completed' ? 'bg-emerald-500' : company.crawlStatus === 'crawling' ? 'bg-blue-500' : 'bg-slate-400'}`} />
                          {company.crawlStatus || 'pending'}
                        </span>
                      </td>

                      <td className="px-4 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold uppercase border ${RESEARCH_STATUS_STYLES[company.researchStatus || 'pending']}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${company.researchStatus === 'completed' ? 'bg-purple-600' : company.researchStatus === 'researching' ? 'bg-purple-400 animate-ping' : 'bg-slate-400'}`} />
                          {company.researchStatus || 'pending'}
                        </span>
                      </td>

                      <td className="px-4 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold uppercase border ${OUTREACH_STATUS_STYLES[company.outreachStatus || 'none']}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${company.outreachStatus === 'sent' ? 'bg-emerald-500' : company.outreachStatus === 'generated' ? 'bg-indigo-500' : 'bg-slate-400'}`} />
                          {company.outreachStatus || 'none'}
                        </span>
                      </td>

                      <td className="px-5 py-4 whitespace-nowrap text-right space-x-2">
                        <button
                          onClick={() => handleCrawl(company._id)}
                          disabled={crawlingId === company._id || company.crawlStatus === 'crawling'}
                          className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-bold transition-colors disabled:opacity-50"
                        >
                          {crawlingId === company._id || company.crawlStatus === 'crawling' ? 'Crawling...' : 'Crawl'}
                        </button>
                        <Link
                          to={`/companies/${company._id}`}
                          className="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-bold transition-colors inline-flex items-center gap-1 shadow-xs"
                        >
                          <span>Open</span>
                          <span>&rarr;</span>
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Modern Pagination */}
      {pagination.pages > 1 && (
        <div className="flex justify-center items-center gap-2 pt-2">
          {Array.from({ length: pagination.pages }, (_, i) => i + 1).map((page) => (
            <button
              key={page}
              onClick={() => handlePageChange(page)}
              className={`w-9 h-9 rounded-xl text-xs font-bold transition-all ${
                page === pagination.page
                  ? 'bg-slate-900 text-white shadow-md'
                  : 'bg-white border border-slate-200 text-slate-700 hover:bg-slate-50'
              }`}
            >
              {page}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
