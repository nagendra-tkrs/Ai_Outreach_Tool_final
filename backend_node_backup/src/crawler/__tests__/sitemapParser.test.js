const { parseSitemap } = require('../sitemapParser');

describe('sitemapParser', () => {
  test('parses XML sitemap with urls', () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/about</loc></url>
  <url><loc>https://example.com/contact</loc></url>
</urlset>`;
    const urls = parseSitemap(xml);
    expect(urls).toHaveLength(3);
    expect(urls).toContain('https://example.com/');
    expect(urls).toContain('https://example.com/about');
  });

  test('parses sitemap index', () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap2.xml</loc></sitemap>
</sitemapindex>`;
    const urls = parseSitemap(xml);
    expect(urls).toHaveLength(2);
    expect(urls).toContain('https://example.com/sitemap1.xml');
  });

  test('handles empty sitemap', () => {
    const xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>';
    const urls = parseSitemap(xml);
    expect(urls).toEqual([]);
  });
});
