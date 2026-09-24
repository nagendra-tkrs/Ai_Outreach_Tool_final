const { URL } = require('url');

const normalizeUrl = (urlStr) => {
  if (!urlStr || typeof urlStr !== 'string') return '';
  try {
    const url = new URL(urlStr);
    url.hash = '';
    let path = url.pathname.replace(/\/+$/, '') || '/';
    url.pathname = path;
    const params = [...url.searchParams.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join('&');
    url.search = params ? `?${params}` : '';
    return url.toString().toLowerCase();
  } catch {
    return urlStr.trim().toLowerCase();
  }
};

const extractDomain = (urlStr) => {
  try {
    const url = new URL(urlStr);
    return url.hostname.replace(/^www\./, '').toLowerCase();
  } catch {
    return '';
  }
};

const isSameDomain = (urlStr, baseDomain) => {
  const domain = extractDomain(urlStr);
  return domain === baseDomain || domain.endsWith(`.${baseDomain}`);
};

const resolveUrl = (baseUrl, relativeUrl) => {
  try {
    return new URL(relativeUrl, baseUrl).toString();
  } catch {
    return '';
  }
};

const filterSameDomainLinks = (links, baseDomain) => {
  const seen = new Set();
  const results = [];
  for (const link of links) {
    if (!link) continue;
    if (!isSameDomain(link, baseDomain)) continue;
    const normalized = normalizeUrl(link);
    if (!normalized || seen.has(normalized)) continue;
    if (/\.(jpg|jpeg|png|gif|svg|webp|ico|css|js|pdf|zip|tar|gz|mp4|mp3|woff|woff2|ttf|eot)$/i.test(normalized)) continue;
    seen.add(normalized);
    results.push(normalized);
  }
  return results;
};

const urlsAreEqual = (a, b) => {
  return normalizeUrl(a) === normalizeUrl(b);
};

module.exports = { normalizeUrl, extractDomain, isSameDomain, resolveUrl, filterSameDomainLinks, urlsAreEqual };
