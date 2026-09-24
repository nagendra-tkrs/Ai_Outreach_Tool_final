const cheerio = require('cheerio');

async function searchPublicEmail(personName, companyName, domain) {
  const queries = [
    `"${personName}" "${domain}" email`,
    `"${personName}" "@${domain}"`,
    `"${personName}" email "${companyName}"`,
    `site:${domain} "${personName}"`
  ];

  console.log(`\nSearching for: ${personName} (${companyName} - ${domain})`);
  const foundEmails = [];

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
        const text = $('body').text();
        const emailRegex = new RegExp(`[a-zA-Z0-9._%+-]+@${domain.replace('.', '\\.')}`, 'gi');
        const matches = text.match(emailRegex) || [];
        for (const m of matches) {
          const clean = m.toLowerCase().trim();
          if (!['info@', 'contact@', 'support@', 'sales@', 'help@', 'press@', 'jobs@', 'careers@'].some(p => clean.startsWith(p))) {
            foundEmails.push({ email: clean, query: q });
          }
        }
      }
    } catch (e) {
      console.error(`Search error for "${q}":`, e.message);
    }
  }

  console.log(`Found emails for ${personName}:`, foundEmails);
}

async function run() {
  await searchPublicEmail('Sam Altman', 'OpenAI', 'openai.com');
  await searchPublicEmail('Patrick Collison', 'Stripe', 'stripe.com');
  await searchPublicEmail('Tobias Lütke', 'Shopify', 'shopify.com');
  await searchPublicEmail('Dylan Field', 'Figma', 'figma.com');
  await searchPublicEmail('Ivan Zhao', 'Notion', 'notion.so');
  await searchPublicEmail('Olivier Pomel', 'Datadog', 'datadoghq.com');
  await searchPublicEmail('Sridhar Ramaswamy', 'Snowflake', 'snowflake.com');
  await searchPublicEmail('Yamini Rangan', 'HubSpot', 'hubspot.com');
  await searchPublicEmail('Mike Cannon-Brookes', 'Atlassian', 'atlassian.com');
}

run();
