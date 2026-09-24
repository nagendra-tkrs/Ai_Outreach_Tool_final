/**
 * Active Web Search Provider Factory.
 *
 * Active provider:
 *   duckduckgo - free DuckDuckGo HTML search (the ONLY active runtime provider).
 *
 * Paid / credit-based search providers (Google CSE, Bing API, SerpAPI, Serper,
 * Tavily, Brave, Exa, Perplexity, Firecrawl...) are intentionally NOT part of
 * the active runtime path. Setting SEARCH_PROVIDER to anything other than
 * duckduckgo / public_web / html disables search rather than falling back to a
 * paid provider.
 *
 * All web search consumers route through executeSearch() so they are
 * provider-agnostic. Centralizes the bounded query / result-limit controls:
 *   MAX_WEB_SEARCH_QUERIES       - max number of distinct queries per discovery run
 *   MAX_SEARCH_RESULTS_PER_QUERY  - max results consumed from a single query
 */

const { executePublicWebSearch } = require('./publicWebSearchProvider');

const envInt = (name, fallback) => {
  const raw = process.env[name];
  if (raw === undefined || raw === null || raw === '') return fallback;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
};

const MAX_WEB_SEARCH_QUERIES = envInt('MAX_WEB_SEARCH_QUERIES', 20);
const MAX_SEARCH_RESULTS_PER_QUERY = envInt('MAX_SEARCH_RESULTS_PER_QUERY', 5);

// Free-search opt-out: forces 'none' when disabled.
// Evaluated at call-time so it can be toggled via env.
const isPublicWebFallbackEnabled = () => {
  const explicit = process.env.ENABLE_PUBLIC_WEB_SEARCH;
  if (explicit !== undefined) {
    return String(explicit).toLowerCase() !== 'false';
  }
  return process.env.NODE_ENV !== 'test';
};

/**
 * Returns which search provider is currently active for the app.
 * Only DuckDuckGo (public_web) is ever active; anything else means disabled.
 * @returns {{ providerName: 'public_web'|'none', isConfigured: boolean, reason: string }}
 */
const getActiveSearchProviderConfig = () => {
  const provider = (process.env.SEARCH_PROVIDER || 'duckduckgo').toLowerCase().trim();

  const duckduckgoActive = provider === 'duckduckgo' || provider === 'public_web' || provider === 'html' || provider === 'ddg';

  if (duckduckgoActive && isPublicWebFallbackEnabled()) {
    return { providerName: 'public_web', isConfigured: true, reason: 'DUCKDUCKGO_ONLY' };
  }

  return { providerName: 'none', isConfigured: false, reason: 'SEARCH_PROVIDER_NOT_CONFIGURED' };
};

/**
 * Executes a query through the active search provider (DuckDuckGo).
 * Result shape is normalized; controlled error states are passed through
 * (SEARCH_TIMEOUT / SEARCH_BLOCKED / SEARCH_UNAVAILABLE / NO_RESULTS).
 */
const executeSearch = async (query, options = {}) => {
  const active = getActiveSearchProviderConfig();

  if (active.providerName === 'public_web') {
    const res = await executePublicWebSearch(query, options);
    // Enforce per-query result limit on normalized results
    const limit = options.limit || MAX_SEARCH_RESULTS_PER_QUERY;
    if (Array.isArray(res.results) && res.results.length > limit) {
      res.results = res.results.slice(0, limit);
    }
    return res;
  }

  return {
    query,
    results: [],
    provider: 'none',
    configured: false,
    error: 'SEARCH_PROVIDER_NOT_CONFIGURED',
    state: 'SEARCH_UNAVAILABLE',
    retrievedAt: new Date().toISOString()
  };
};

/**
 * Build a bounded list of leadership-discovery queries for a company.
 * Honors MAX_WEB_SEARCH_QUERIES.
 */
const buildDecisionMakerQueries = (companyName, domain, industry = '', country = '', opportunityContext = '') => {
  const cleanDomain = (domain || '').replace(/https?:\/\//, '').replace(/^www\./, '').split('/')[0].toLowerCase();

  const queries = [
    `"${companyName}" "Chief Executive Officer" OR "CEO"`,
    `"${companyName}" "Chief Technology Officer" OR "CTO" OR "Head of AI"`,
    `"${companyName}" "Chief Information Officer" OR "CIO" OR "Chief Operating Officer" OR "COO"`
  ];

  if (cleanDomain) {
    queries.push(`site:${cleanDomain} (leadership OR team OR executives OR management)`);
  }

  if (/governance|compliance|responsible ai|risk/i.test(opportunityContext)) {
    queries.push(`"${companyName}" "CIO" OR "Chief Data Officer" OR "Chief Digital Officer"`);
  } else if (/sales|customer|support|revenue/i.test(opportunityContext)) {
    queries.push(`"${companyName}" "Chief Customer Officer" OR "Chief Revenue Officer" OR "Head of Sales"`);
  }

  return queries.slice(0, MAX_WEB_SEARCH_QUERIES);
};

module.exports = {
  executeSearch,
  getActiveSearchProviderConfig,
  buildDecisionMakerQueries,
  MAX_WEB_SEARCH_QUERIES,
  MAX_SEARCH_RESULTS_PER_QUERY
};