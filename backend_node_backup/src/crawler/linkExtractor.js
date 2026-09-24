const cheerio = require('cheerio');
const { normalizeUrl, extractDomain, resolveUrl, filterSameDomainLinks } = require('./urlUtils');

const extractLinks = (html, baseUrl) => {
  const $ = cheerio.load(html);
  const domain = extractDomain(baseUrl);
  const rawLinks = [];

  $('a[href]').each((_, el) => {
    const href = $(el).attr('href');
    if (href && !href.startsWith('#') && !href.startsWith('javascript:') && !href.startsWith('mailto:') && !href.startsWith('tel:')) {
      const absolute = resolveUrl(baseUrl, href);
      if (absolute) rawLinks.push(absolute);
    }
  });

  return filterSameDomainLinks(rawLinks, domain);
};

module.exports = { extractLinks };
