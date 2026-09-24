const { URL } = require('url');

const DEFAULT_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (compatible; B2BOutreachBot/1.0; +https://example.com/bot)';

const DEFAULT_HEADERS = {
  'User-Agent': DEFAULT_USER_AGENT,
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
  'Accept-Language': 'en-US,en;q=0.9',
  'Accept-Encoding': 'gzip, deflate, br',
  'Cache-Control': 'no-cache',
  'Upgrade-Insecure-Requests': '1',
  'Sec-Fetch-Dest': 'document',
  'Sec-Fetch-Mode': 'navigate',
  'Sec-Fetch-Site': 'none',
  'Sec-Fetch-User': '?1'
};

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

/**
 * Parse Retry-After header value into milliseconds
 */
const parseRetryAfter = (headerVal) => {
  if (!headerVal) return null;
  const seconds = parseInt(headerVal, 10);
  if (!isNaN(seconds)) {
    return Math.min(seconds * 1000, 10000); // capped at 10s
  }
  const dateMs = Date.parse(headerVal);
  if (!isNaN(dateMs)) {
    const diff = dateMs - Date.now();
    return diff > 0 ? Math.min(diff, 10000) : 1000;
  }
  return 2000;
};

/**
 * Fetch a URL following redirects safely up to maxRedirects
 */
const fetchSingleAttempt = async (targetUrl, { timeout, maxPageSize, headers = {} }, redirectHistory = []) => {
  if (redirectHistory.length > 5) {
    throw Object.assign(new Error('Too many redirects (> 5)'), {
      statusCode: 310,
      crawlStatus: 'failed',
      errorReason: 'Too many redirects (> 5)'
    });
  }

  if (redirectHistory.includes(targetUrl)) {
    throw Object.assign(new Error('Redirect loop detected'), {
      statusCode: 310,
      crawlStatus: 'failed',
      errorReason: `Redirect loop detected for ${targetUrl}`
    });
  }

  const currentHistory = [...redirectHistory, targetUrl];
  let res;

  try {
    res = await fetch(targetUrl, {
      method: 'GET',
      headers: { ...DEFAULT_HEADERS, ...headers },
      redirect: 'manual', // handle manually to track chain and prevent cross-domain hijacking
      signal: AbortSignal.timeout(timeout)
    });
  } catch (err) {
    if (err.name === 'TimeoutError' || err.name === 'AbortError') {
      throw Object.assign(new Error(`Request timed out after ${timeout}ms`), {
        statusCode: 0,
        crawlStatus: 'timeout',
        errorReason: `Request timed out after ${timeout}ms`
      });
    }
    throw Object.assign(new Error(`Network connection error: ${err.message}`), {
      statusCode: 0,
      crawlStatus: 'failed',
      errorReason: `Network error: ${err.message}`
    });
  }

  const statusCode = res.status;
  const contentType = res.headers.get('content-type') || '';
  const responseHeaders = Object.fromEntries(res.headers.entries());

  // 1. Handle Redirects (301, 302, 303, 307, 308)
  if (statusCode >= 300 && statusCode < 400) {
    const location = res.headers.get('location');
    if (!location) {
      throw Object.assign(new Error(`Redirect status ${statusCode} with no location header`), {
        statusCode,
        crawlStatus: 'failed',
        errorReason: `Redirect ${statusCode} missing Location header`
      });
    }

    let nextUrl;
    try {
      nextUrl = new URL(location, targetUrl).toString();
    } catch {
      throw Object.assign(new Error(`Invalid redirect location URL: ${location}`), {
        statusCode,
        crawlStatus: 'failed',
        errorReason: `Invalid redirect location URL: ${location}`
      });
    }

    return fetchSingleAttempt(nextUrl, { timeout, maxPageSize, headers }, currentHistory);
  }

  // 2. Handle HTTP 403 Forbidden / Blocked
  if (statusCode === 403) {
    let body = '';
    try { body = await res.text(); } catch { /* ignore */ }
    throw Object.assign(new Error('HTTP 403: Access Denied / Forbidden'), {
      statusCode: 403,
      crawlStatus: 'blocked',
      errorReason: 'HTTP 403 Access Denied',
      contentType,
      body,
      headers: responseHeaders,
      finalUrl: targetUrl
    });
  }

  // 3. Handle HTTP 429 Rate Limit
  if (statusCode === 429) {
    const retryAfterVal = res.headers.get('retry-after');
    const retryAfterMs = parseRetryAfter(retryAfterVal) || 2000;
    let body = '';
    try { body = await res.text(); } catch { /* ignore */ }
    throw Object.assign(new Error('HTTP 429: Too Many Requests / Rate Limited'), {
      statusCode: 429,
      crawlStatus: 'rate_limited',
      errorReason: 'HTTP 429 Too Many Requests',
      retryAfterMs,
      contentType,
      body,
      headers: responseHeaders,
      finalUrl: targetUrl
    });
  }

  // 4. Handle HTTP 404 Not Found
  if (statusCode === 404) {
    throw Object.assign(new Error('HTTP 404: Page Not Found'), {
      statusCode: 404,
      crawlStatus: 'not_found',
      errorReason: 'HTTP 404 Page Not Found',
      finalUrl: targetUrl
    });
  }

  // 5. Handle HTTP 5xx Server Errors
  if (statusCode >= 500 && statusCode < 600) {
    let body = '';
    try { body = await res.text(); } catch { /* ignore */ }
    throw Object.assign(new Error(`HTTP ${statusCode}: Server Error`), {
      statusCode,
      crawlStatus: 'server_error',
      errorReason: `HTTP ${statusCode} Server Error`,
      contentType,
      body,
      headers: responseHeaders,
      finalUrl: targetUrl
    });
  }

  // 6. Handle other 4xx errors
  if (statusCode >= 400 && statusCode < 500) {
    throw Object.assign(new Error(`HTTP ${statusCode}: Client Error`), {
      statusCode,
      crawlStatus: 'failed',
      errorReason: `HTTP ${statusCode} Client Error`,
      finalUrl: targetUrl
    });
  }

  // 7. Check Content-Type
  const cleanType = contentType.toLowerCase();
  if (!cleanType.includes('text/html') && !cleanType.includes('application/xhtml+xml') && !cleanType.includes('text/plain')) {
    throw Object.assign(new Error(`Unsupported content type: ${contentType}`), {
      statusCode,
      crawlStatus: 'invalid_content',
      errorReason: `Unsupported content type: ${contentType}`,
      finalUrl: targetUrl
    });
  }

  // 8. Read Body with size limit
  const body = await res.text();
  if (body.length > maxPageSize) {
    throw Object.assign(new Error(`Page size exceeds maximum limit (${body.length} > ${maxPageSize})`), {
      statusCode,
      crawlStatus: 'invalid_content',
      errorReason: 'Page size too large',
      finalUrl: targetUrl
    });
  }

  return {
    statusCode,
    contentType,
    body,
    finalUrl: targetUrl,
    headers: responseHeaders
  };
};

/**
 * Fetch a page with controlled exponential backoff retries for 429 and 5xx errors
 */
const fetchPage = async (url, options = {}) => {
  const {
    timeout = parseInt(process.env.CRAWLER_TIMEOUT_MS, 10) || parseInt(process.env.REQUEST_TIMEOUT, 10) || 10000,
    maxPageSize = parseInt(process.env.MAX_PAGE_SIZE, 10) || 5000000,
    maxRetries = parseInt(process.env.MAX_RETRIES, 10) || 2,
    headers = {}
  } = options;

  let lastError;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const result = await fetchSingleAttempt(url, { timeout, maxPageSize, headers });
      return result;
    } catch (err) {
      lastError = err;

      // Do NOT retry for non-retryable errors
      const statusCode = err.statusCode;
      if (
        statusCode === 403 ||
        statusCode === 404 ||
        statusCode === 401 ||
        statusCode === 410 ||
        err.crawlStatus === 'blocked' ||
        err.crawlStatus === 'not_found' ||
        err.crawlStatus === 'invalid_content'
      ) {
        throw err;
      }

      // If we still have retry attempts remaining
      if (attempt < maxRetries) {
        let backoffMs = 1000 * Math.pow(2, attempt); // 1s, 2s, 4s...
        if (err.crawlStatus === 'rate_limited' && err.retryAfterMs) {
          backoffMs = Math.max(backoffMs, err.retryAfterMs);
        }
        await sleep(backoffMs);
      }
    }
  }

  throw lastError;
};

const fetchUrl = async (url, options = {}) => {
  return fetchPage(url, options);
};

module.exports = {
  fetchPage,
  fetchUrl,
  parseRetryAfter,
  DEFAULT_USER_AGENT,
  DEFAULT_HEADERS,
  USER_AGENT: DEFAULT_USER_AGENT
};
