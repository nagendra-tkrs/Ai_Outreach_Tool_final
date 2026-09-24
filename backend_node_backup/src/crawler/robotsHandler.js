const robotsParser = require('robots-parser');
const { fetchPage, DEFAULT_USER_AGENT } = require('./fetcher');

const robotsCache = new Map();

const fetchRobotsTxt = async (baseUrl) => {
  try {
    const domain = new URL(baseUrl).origin;
    if (robotsCache.has(domain)) return robotsCache.get(domain);

    const robotsUrl = `${domain}/robots.txt`;
    try {
      const result = await fetchPage(robotsUrl, { timeout: 5000, maxRetries: 1 });
      if (result && result.statusCode === 200 && result.body) {
        const parser = robotsParser(robotsUrl, result.body);
        if (parser) {
          robotsCache.set(domain, parser);
          return parser;
        }
      }
    } catch {
      // If robots.txt returns 404 or fails to fetch, allow crawling by default
    }

    const allowAll = robotsParser(`${domain}/robots.txt`, 'User-agent: *\nAllow: /');
    robotsCache.set(domain, allowAll);
    return allowAll;
  } catch {
    return robotsParser('https://example.com/robots.txt', 'User-agent: *\nAllow: /');
  }
};

const isAllowed = async (url, userAgent = DEFAULT_USER_AGENT) => {
  try {
    const domain = new URL(url).origin;
    const parser = await fetchRobotsTxt(domain);
    if (!parser) return true;
    const allowed = parser.isAllowed(url, userAgent);
    // If undefined or boolean, return boolean
    return allowed !== false;
  } catch {
    return true;
  }
};

const getSitemaps = async (baseUrl) => {
  try {
    const domain = new URL(baseUrl).origin;
    const parser = await fetchRobotsTxt(domain);
    if (!parser) return [];
    const sitemaps = parser.getSitemaps();
    return Array.isArray(sitemaps) ? sitemaps : [];
  } catch {
    return [];
  }
};

const clearCache = () => {
  robotsCache.clear();
};

module.exports = { fetchRobotsTxt, isAllowed, getSitemaps, clearCache };
