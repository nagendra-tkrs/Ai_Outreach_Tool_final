const { fetchPage } = require('./fetcher');
const { normalizeUrl } = require('./urlUtils');
const cheerio = require('cheerio');

const parseSitemap = (xml) => {
  const $ = cheerio.load(xml, { xmlMode: true });
  const urls = [];

  $('url > loc').each((_, el) => {
    const url = $(el).text().trim();
    if (url) urls.push(url);
  });

  $('sitemap > loc').each((_, el) => {
    const url = $(el).text().trim();
    if (url) urls.push(url);
  });

  return urls;
};

const fetchSitemap = async (baseUrl) => {
  const domain = new URL(baseUrl).origin;
  const sitemapUrls = [
    `${domain}/sitemap.xml`,
    `${domain}/sitemap_index.xml`,
    `${domain}/sitemap.txt`
  ];

  for (const sitemapUrl of sitemapUrls) {
    try {
      const result = await fetchPage(sitemapUrl, { timeout: 5000 });
      if (result.statusCode === 200) {
        const urls = parseSitemap(result.body);
        return urls;
      }
    } catch {
      continue;
    }
  }

  return [];
};

module.exports = { parseSitemap, fetchSitemap };
