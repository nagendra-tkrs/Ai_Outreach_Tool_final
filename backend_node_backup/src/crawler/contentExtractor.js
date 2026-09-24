const cheerio = require('cheerio');

const extractContent = (html, url) => {
  const $ = cheerio.load(html);

  $('script, style, noscript, nav, footer, header, iframe, form, [role="navigation"], [role="banner"], [role="contentinfo"]').remove();

  const title = $('title').first().text().trim() || '';

  const metaDescription = $('meta[name="description"]').attr('content') || '';

  const canonicalUrl = $('link[rel="canonical"]').attr('href') || '';

  const ogTitle = $('meta[property="og:title"]').attr('content') || '';
  const ogDescription = $('meta[property="og:description"]').attr('content') || '';

  const headings = [];
  $('h1, h2, h3').each((_, el) => {
    const text = $(el).text().trim();
    if (text) headings.push({ level: parseInt(el.tagName[1]), text });
  });

  $('body').find('*').each((_, el) => {
    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'NAV', 'FOOTER', 'HEADER'].includes(el.tagName)) {
      $(el).remove();
    }
  });

  let content = '';
  const mainContent = $('main, article, [role="main"], .content, .main-content').first();
  if (mainContent.length) {
    content = mainContent.text();
  } else {
    content = $('body').text();
  }

  content = content
    .replace(/\s+/g, ' ')
    .replace(/\n+/g, '\n')
    .trim();

  const wordCount = content.split(/\s+/).filter(w => w.length > 0).length;

  return {
    title: ogTitle || title,
    metaDescription: ogDescription || metaDescription,
    canonicalUrl,
    headings,
    content,
    wordCount
  };
};

module.exports = { extractContent };
