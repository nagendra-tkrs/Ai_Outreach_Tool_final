const cheerio = require('cheerio');

async function testEngines(query) {
  console.log('Testing queries for:', query);

  // 1. DuckDuckGo HTML
  try {
    const res = await fetch(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' }
    });
    const html = await res.text();
    console.log('DuckDuckGo HTML length:', html.length);
  } catch (e) {
    console.log('DDG error:', e.message);
  }

  // 2. DuckDuckGo Lite
  try {
    const res = await fetch(`https://lite.duckduckgo.com/lite/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
      },
      body: `q=${encodeURIComponent(query)}`
    });
    const html = await res.text();
    console.log('DDG Lite length:', html.length);
    const $ = cheerio.load(html);
    const snippets = [];
    $('.result-snippet, .result-link').each((i, el) => snippets.push($(el).text().trim()));
    console.log('DDG Lite snippets:', snippets.slice(0, 5));
  } catch (e) {
    console.log('DDG Lite error:', e.message);
  }

  // 3. Bing search
  try {
    const res = await fetch(`https://www.bing.com/search?q=${encodeURIComponent(query)}`, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9'
      }
    });
    const html = await res.text();
    console.log('Bing HTML length:', html.length);
    const $ = cheerio.load(html);
    const snippets = [];
    $('.b_caption p, .b_algo h2').each((i, el) => snippets.push($(el).text().trim()));
    console.log('Bing snippets:', snippets.slice(0, 5));
  } catch (e) {
    console.log('Bing error:', e.message);
  }
}

testEngines('site:tksrproductservices.com OR "tksrproductservices.com"');
