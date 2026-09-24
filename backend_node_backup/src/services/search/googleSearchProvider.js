/**
 * LEGACY / DISABLED — Google Custom Search JSON API provider.
 *
 * IMPORTANT: This module is NOT part of the active runtime search path.
 * The active search provider is DuckDuckGo only (see searchProvider.js and
 * publicWebSearchProvider.js). Nothing in production imports this module.
 *
 * It is preserved ONLY for the legacy unit test that verifies graceful
 * unconfigured handling, and is retained here so that switching back to a
 * paid provider is never automatic from any env var.
 */

const getSearchProviderConfig = () => {
  const apiKey = process.env.GOOGLE_SEARCH_API_KEY || process.env.GOOGLE_API_KEY || process.env.GOOGLE_CSE_KEY || '';
  const searchEngineId = process.env.GOOGLE_SEARCH_ENGINE_ID || process.env.GOOGLE_CSE_ID || process.env.GOOGLE_CX || '';

  return {
    apiKey: apiKey.trim(),
    searchEngineId: searchEngineId.trim(),
    isConfigured: Boolean(apiKey.trim() && searchEngineId.trim())
  };
};

/**
 * Executes a query via Google Custom Search API and normalizes the response.
 * @param {string} query - The search query
 * @param {Object} options - Search options (num, start, siteSearch, etc.)
 * @returns {Promise<Object>} Normalized search results object
 */
const executeGoogleSearch = async (query, options = {}) => {
  const config = getSearchProviderConfig();

  if (!config.isConfigured) {
    return {
      query,
      results: [],
      provider: 'google',
      configured: false,
      error: 'SEARCH_PROVIDER_NOT_CONFIGURED',
      retrievedAt: new Date().toISOString()
    };
  }

  const num = Math.min(Math.max(options.num || 5, 1), 10);
  const searchUrl = new URL('https://www.googleapis.com/customsearch/v1');
  searchUrl.searchParams.set('key', config.apiKey);
  searchUrl.searchParams.set('cx', config.searchEngineId);
  searchUrl.searchParams.set('q', query);
  searchUrl.searchParams.set('num', String(num));

  if (options.siteSearch) {
    searchUrl.searchParams.set('siteSearch', options.siteSearch);
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), options.timeoutMs || 4000);

  try {
    const res = await fetch(searchUrl.toString(), {
      signal: controller.signal,
      headers: {
        'Accept': 'application/json',
        'User-Agent': 'AIClientOutreach/2.0'
      }
    });

    clearTimeout(timeoutId);

    if (!res.ok) {
      const errText = await res.text();
      return {
        query,
        results: [],
        provider: 'google',
        configured: true,
        error: `Google Search API returned status ${res.status}: ${errText.slice(0, 200)}`,
        retrievedAt: new Date().toISOString()
      };
    }

    const data = await res.json();
    const rawItems = data.items || [];

    const normalizedResults = rawItems.map((item, index) => {
      let sourceDomain = '';
      try {
        if (item.link) {
          sourceDomain = new URL(item.link).hostname.replace(/^www\./, '').toLowerCase();
        }
      } catch {
        sourceDomain = item.displayLink || '';
      }

      return {
        title: (item.title || '').trim(),
        url: item.link || '',
        snippet: (item.snippet || '').replace(/[\r\n\t]+/g, ' ').trim(),
        sourceDomain,
        position: index + 1
      };
    });

    return {
      query,
      results: normalizedResults,
      provider: 'google',
      configured: true,
      retrievedAt: new Date().toISOString()
    };
  } catch (err) {
    clearTimeout(timeoutId);
    return {
      query,
      results: [],
      provider: 'google',
      configured: true,
      error: err.name === 'AbortError' ? 'Google Search request timed out' : err.message,
      retrievedAt: new Date().toISOString()
    };
  }
};

/**
 * Factory to retrieve the active search provider
 */
const getSearchProvider = () => {
  return {
    providerName: 'google',
    isConfigured: () => getSearchProviderConfig().isConfigured,
    search: executeGoogleSearch
  };
};

module.exports = {
  executeGoogleSearch,
  getSearchProvider,
  getSearchProviderConfig
};
