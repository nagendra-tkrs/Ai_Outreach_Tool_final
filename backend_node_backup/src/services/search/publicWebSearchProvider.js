/**
 * Free / Public Web Search Provider (DuckDuckGo HTML endpoint ONLY).
 *
 * The active search provider is DuckDuckGo - a free, public search engine.
 * Bing, Google, and all paid/credit-based search APIs are intentionally NOT
 * used by the active runtime path.
 *
 * Robustness:
 *   - configurable timeout / retries / retry delay via env
 *   - controlled error states (never silently falls back to a paid provider):
 *       SEARCH_TIMEOUT     - request or wait timed out
 *       SEARCH_BLOCKED     - rate limited / challenge / captcha / 403
 *       SEARCH_UNAVAILABLE - network or HTTP server failure
 *       NO_RESULTS         - service responded but no results found
 *   - a single failed search never crashes a research job
 */

const envInt = (name, fallback) => {
  const raw = process.env[name];
  if (raw === undefined || raw === null || raw === '') return fallback;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) && n >= 0 ? n : fallback;
};

// Configurable settings (with sensible defaults per the free-architecture spec).
const SEARCH_TIMEOUT_MS = envInt('SEARCH_TIMEOUT_MS', 30000);
const SEARCH_MAX_RETRIES = envInt('SEARCH_MAX_RETRIES', 2);
const SEARCH_RETRY_DELAY_MS = envInt('SEARCH_RETRY_DELAY_MS', 1500);

const USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36';

const DUMPLING_URL = 'https://html.duckduckgo.com/html';

/**
 * Decode DuckDuckGo's encoded redirect URLs into the real destination.
 * ddg links look like: //duckduckgo.com/l/?uddg=<urlencoded>&rut=...
 */
const decodeRedirectUrl = (rawUrl = '') => {
  if (!rawUrl) return '';
  try {
    const parsed = new URL(rawUrl, 'https://duckduckgo.com');
    const uddg = parsed.searchParams.get('uddg');
    if (uddg) {
      return decodeURIComponent(uddg);
    }
    return rawUrl.startsWith('http') ? rawUrl : '';
  } catch {
    return rawUrl;
  }
};

const isConfigured = () => true; // DuckDuckGo is free and always "configured"

/**
 * Detect DDG challenge / rate-limit / anomaly pages even when HTTP returns 200.
 * Returns true when the page is not a results page.
 */
const isChallengeOrBlockedPage = (html = '') => {
  if (!html) return false;
  const lower = html.slice(0, 20000).toLowerCase();
  const markers = [
    'anomaly',
    'unusual traffic',
    'captcha',
    'are you a robot',
    'verify you are human',
    'attention required',
    'ddg_anomaly',
    'please wait while we redirect',
    '<title>blocked</title>',
    'access denied',
    '403 forbidden'
  ];
  return markers.some((m) => lower.includes(m));
};

/**
 * Root cause classification for fetch failures.
 */
const classifyError = (err, status) => {
  if (err && (err.name === 'AbortError' || err.name === 'TimeoutError')) {
    return { state: 'SEARCH_TIMEOUT', message: `DuckDuckGo search timed out` };
  }
  const code = status || (err && err.code);
  if (code === 403 || code === 401 || code === 429) {
    return { state: 'SEARCH_BLOCKED', message: `DuckDuckGo blocked the request (HTTP ${code})` };
  }
  if (code === 404 || code === 400) {
    return { state: 'SEARCH_UNAVAILABLE', message: `DuckDuckGo returned HTTP ${code}` };
  }
  if (typeof code === 'number' && code >= 500 && code <= 599) {
    return { state: 'SEARCH_UNAVAILABLE', message: `DuckDuckGo returned HTTP ${code}` };
  }
  return { state: 'SEARCH_UNAVAILABLE', message: (err && err.message) || 'Network failure' };
};

/**
 * Executes a query against DuckDuckGo HTML and normalizes results.
 * @param {string} query
 * @param {Object} options - (timeoutMs)
 * @returns {Promise<Object>} Normalized search results object.
 */
const executePublicWebSearch = async (query, options = {}) => {
  if (!query) {
    return {
      query,
      results: [],
      provider: 'public_web',
      source: 'duckduckgo',
      configured: true,
      error: 'EMPTY_QUERY',
      state: 'NO_RESULTS',
      retrievedAt: new Date().toISOString()
    };
  }

  const timeoutMs = options.timeoutMs || SEARCH_TIMEOUT_MS;
  const maxRetries = envInt('SEARCH_MAX_RETRIES', SEARCH_MAX_RETRIES);
  const retryDelayMs = envInt('SEARCH_RETRY_DELAY_MS', SEARCH_RETRY_DELAY_MS);
  const url = `${DUMPLING_URL}/?q=${encodeURIComponent(query)}`;

  let lastError = '';
  let lastState = 'SEARCH_UNAVAILABLE';

  // Deliberately bounded retry budget: never hammer a free endpoint. Each retry
  // is only attempted for transient failures (timeout / 429 / 5xx / network).
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const html = await fetchHtml(url, { timeoutMs });

      if (isChallengeOrBlockedPage(html)) {
        lastError = 'DuckDuckGo served a challenge/rate-limit page';
        lastState = 'SEARCH_BLOCKED';
        // A challenge page is not transient-empty; stop retrying to be polite.
        break;
      }

      const results = parseDuckDuckGoHtml(html);
      if (results.length > 0) {
        return {
          query,
          results,
          provider: 'public_web',
          source: 'duckduckgo',
          configured: true,
          state: 'OK',
          retrievedAt: new Date().toISOString()
        };
      }

      lastError = 'DuckDuckGo returned no results';
      lastState = 'NO_RESULTS';
      // NO_RESULTS is a definitive answer - do not burn retries on a re-query
      // of the same term. Treat like a terminal state and stop.
      break;
    } catch (err) {
      const forced = extractHttpStatus(err);
      const classified = classifyError(err, forced);
      lastError = classified.message;
      lastState = classified.state;

      // Challenge/blocked responses are terminal - do not retry a banned query.
      if (classified.state === 'SEARCH_BLOCKED') break;

      // Non-transient states should not burn retries.
      if (classified.state === 'SEARCH_UNAVAILABLE' && classified.message.includes('HTTP 404')) break;
    }

    if (attempt < maxRetries) {
      // Transient-state backoff before retrying to keep load polite.
      await sleep(retryDelayMs);
    }
  }

  return {
    query,
    results: [],
    provider: 'public_web',
    source: 'duckduckgo',
    configured: true,
    state: lastState,
    error: lastError || 'NO_RESULTS',
    retrievedAt: new Date().toISOString()
  };
};

const extractHttpStatus = (err) => {
  if (err && err.status) return err.status;
  const m = /HTTP\s+(\d{3})/.exec((err && err.message) || '');
  return m ? Number(m[1]) : null;
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const fetchHtml = async (url, options = {}) => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), options.timeoutMs || SEARCH_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      headers: {
        'Accept': 'text/html',
        'User-Agent': USER_AGENT,
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache'
      }
    });
    if (!res.ok) {
      const err = new Error(`HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return await res.text();
  } finally {
    clearTimeout(timeoutId);
  }
};

/**
 * Robust parser for DuckDuckGo HTML result blocks.
 * Gracefully returns [] for malformed HTML (treated as NO_RESULTS downstream).
 */
const parseDuckDuckGoHtml = (html) => {
  const results = [];
  if (!html || typeof html !== 'string') return results;
  const seen = new Set();

  try {
    const blockRegex = /<div[^>]*class="[^"]*result__body[^"]*"[^>]*>([\s\S]*?)<\/div>\s*<\/div>\s*<\/div>/g;
    let blockMatch;
    while ((blockMatch = blockRegex.exec(html)) !== null) {
      const block = blockMatch[1];
      const titleMatch = block.match(/<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/);
      const snippetMatch = block.match(/<a[^>]*class="result__snippet"[^>]*>([\s\S]*?)<\/a>/);

      const title = titleMatch ? stripHtml(titleMatch[2]) : '';
      const url = titleMatch ? decodeRedirectUrl(titleMatch[1]) : '';
      const snippet = snippetMatch ? stripHtml(snippetMatch[1]) : '';

      if (!title || !url || seen.has(url)) continue;
      seen.add(url);
      results.push({ title, url, snippet, sourceDomain: extractDomain(url), position: results.length + 1 });
    }
  } catch {
    return [];
  }

  return results.slice(0, 10);
};

const stripHtml = (input = '') =>
  input
    .replace(/<[^>]+>/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&#0183;/g, '•')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

const extractDomain = (url = '') => {
  try {
    return new URL(url).hostname.replace(/^www\./, '').toLowerCase();
  } catch {
    return '';
  }
};

module.exports = {
  executePublicWebSearch,
  isConfigured,
  providerName: 'public_web',
  parseDuckDuckGoHtml,
  decodeRedirectUrl,
  isChallengeOrBlockedPage,
  DUMPLING_URL,
  SEARCH_TIMEOUT_MS,
  SEARCH_MAX_RETRIES,
  SEARCH_RETRY_DELAY_MS
};