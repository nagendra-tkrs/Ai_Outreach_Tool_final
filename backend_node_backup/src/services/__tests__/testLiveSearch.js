const cheerio = require('cheerio');

async function testCompanyDiscovery(companyName, domain) {
  console.log(`\n================ Testing ${companyName} (${domain}) ================`);

  const queries = [
    `"${companyName}" CEO OR founder OR "Chief Executive Officer"`,
    `"${companyName}" leadership executive team COO CFO CTO`,
    `site:${domain} leadership OR team OR about`
  ];

  const snippets = [];

  for (const q of queries) {
    try {
      const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(q)}`;
      const res = await fetch(url, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
          'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
      });
      if (res.ok) {
        const html = await res.text();
        const $ = cheerio.load(html);
        $('.result__body').each((i, el) => {
          const title = $(el).find('.result__title').text().trim();
          const snippet = $(el).find('.result__snippet').text().trim();
          let link = $(el).find('.result__url').attr('href') || $(el).find('.result__url').text().trim();
          if (title || snippet) {
            snippets.push({ title, snippet, link: link.startsWith('http') ? link : `https://${link}` });
          }
        });
      }
    } catch (err) {
      console.warn('Search error for query', q, err.message);
    }
  }

  // Also query Wikipedia API as high-authority public source
  try {
    const wikiUrl = `https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(companyName + ' company')}&format=json`;
    const wikiRes = await fetch(wikiUrl);
    if (wikiRes.ok) {
      const wikiData = await wikiRes.json();
      const topPage = wikiData?.query?.search?.[0];
      if (topPage) {
        const pageId = topPage.pageid;
        const detailUrl = `https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro&explaintext&pageids=${pageId}&format=json`;
        const detailRes = await fetch(detailUrl);
        if (detailRes.ok) {
          const detailData = await detailRes.json();
          const extract = detailData?.query?.pages?.[pageId]?.extract;
          if (extract) {
            snippets.unshift({
              title: `${topPage.title} - Wikipedia`,
              snippet: extract.slice(0, 1000),
              link: `https://en.wikipedia.org/wiki/${encodeURIComponent(topPage.title)}`
            });
          }
        }
      }
    }
  } catch (err) {
    console.warn('Wiki search error:', err.message);
  }

  console.log(`Found ${snippets.length} snippets.`);
  snippets.slice(0, 3).forEach((s, idx) => {
    console.log(`[Snippet ${idx + 1}] (${s.link}):\n${s.title}\n${s.snippet.slice(0, 200)}...\n`);
  });
}

async function run() {
  await testCompanyDiscovery('Stripe', 'stripe.com');
  await testCompanyDiscovery('Shopify', 'shopify.com');
  await testCompanyDiscovery('Datadog', 'datadoghq.com');
  await testCompanyDiscovery('OpenAI', 'openai.com');
}

run();
