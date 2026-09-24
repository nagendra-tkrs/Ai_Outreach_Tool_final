const cheerio = require('cheerio');

const cleanExecutive = (name = '', rawTitle = '', companyName = '') => {
  let cleanName = name
    .replace(/\[\[(?:[^|\]]+\|)?([^\]]+)\]\]/g, '$1')
    .replace(/\[\[|\]\]/g, '')
    .replace(/^(the|and|by|with|from|to|at|for|is|mr|ms|dr|sir)\s+/i, '')
    .replace(/<[^>]+>/g, '')
    .trim();

  let cleanTitle = rawTitle
    .replace(/\[\[(?:[^|\]]+\|)?([^\]]+)\]\]/g, '$1')
    .replace(/\[\[|\]\]/g, '')
    .replace(/\(.*?\)/g, '')
    .replace(/\|.*/, '')
    .trim();

  if (/ceo/i.test(cleanTitle) || /chief executive/i.test(cleanTitle)) cleanTitle = 'Chief Executive Officer';
  else if (/coo/i.test(cleanTitle) || /operations/i.test(cleanTitle)) cleanTitle = 'Chief Operating Officer';
  else if (/cfo/i.test(cleanTitle) || /finance/i.test(cleanTitle)) cleanTitle = 'Chief Financial Officer';
  else if (/cto/i.test(cleanTitle) || /technology/i.test(cleanTitle)) cleanTitle = 'Chief Technology Officer';
  else if (/cio/i.test(cleanTitle) || /information/i.test(cleanTitle)) cleanTitle = 'Chief Information Officer';
  else if (/cdo/i.test(cleanTitle) || /digital/i.test(cleanTitle)) cleanTitle = 'Chief Digital Officer';
  else if (/president/i.test(cleanTitle)) cleanTitle = 'President';
  else if (/founder/i.test(cleanTitle)) cleanTitle = 'Founder & Executive';
  else if (/chair/i.test(cleanTitle)) cleanTitle = 'Chairman & Executive';

  const invalidNames = [
    'United States', 'San Francisco', 'New York', 'Chief Executive', 'Vice President',
    'Annual Report', 'Form 10-K', 'Press Release', 'Latest Shake', 'Corporate Officer',
    'Executive Leadership', 'Board Member', 'Stock Exchange', 'Financial Year', 'Public Company',
    'Three Stripes', 'Adidas', 'Puma'
  ];

  if (
    cleanName.split(/\s+/).length < 2 ||
    cleanName.split(/\s+/).length > 4 ||
    invalidNames.some(inv => cleanName.toLowerCase().includes(inv.toLowerCase())) ||
    cleanName.toLowerCase() === companyName.toLowerCase() ||
    cleanName.toLowerCase().startsWith('form ')
  ) {
    return null;
  }

  return { name: cleanName, title: cleanTitle || 'Executive Leadership' };
};

async function fetchWikiLeadership(companyName, domain = '') {
  const headers = { 'User-Agent': 'AIOutreachClient/1.0 (https://tksrproductservices.com; info@tksrproductservices.com)' };
  const executives = [];
  const seen = new Set();

  const searchTerms = [
    `"${companyName}" (company OR software OR corporation OR inc)`,
    `"${companyName}" company`,
    `"${companyName}, Inc."`,
    `"${companyName}"`
  ];

  let targetPage = null;
  for (const term of searchTerms) {
    const url = `https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(term)}&format=json`;
    const res = await fetch(url, { headers });
    if (res.ok) {
      const data = await res.json();
      const results = data?.query?.search || [];
      const exact = results.find(r => {
        const t = r.title.toLowerCase();
        const c = companyName.toLowerCase();
        return (
          t === c || t === `${c}, inc.` || t === `${c} (company)` || t === `${c} inc.` ||
          t === `${c} (software)` || t === `${c} (productivity software)` ||
          (t.includes(c) && (t.includes('software') || t.includes('company') || t.includes('inc') || t.includes('app')))
        ) && !t.includes('stripes') && !t.includes('clothing') && !t.includes('film');
      });
      if (exact) {
        targetPage = exact;
        break;
      }
    }
  }

  if (targetPage) {
    const detailUrl = `https://en.wikipedia.org/w/api.php?action=parse&pageid=${targetPage.pageid}&prop=wikitext|sections&format=json`;
    const detailRes = await fetch(detailUrl, { headers });
    if (detailRes.ok) {
      const detailData = await detailRes.json();
      const raw = detailData?.parse?.wikitext?.['*'] || '';
      const sourceUrl = `https://en.wikipedia.org/wiki/${encodeURIComponent(targetPage.title)}`;

      // 1. key_people block
      const keyPeopleMatch = raw.match(/key_people\s*=\s*([^\n\r]+(?:\n\r?[*|{<][^\n\r]+)*)/i);
      if (keyPeopleMatch) {
        const block = keyPeopleMatch[1];
        const matches = block.matchAll(/(?:\[\[)?([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)(?:\]\])?\s*(?:\(([^)]+)\)|-\s*([A-Za-z\s|]+)|<br\s*\/?>|$)/g);
        for (const m of matches) {
          const cl = cleanExecutive(m[1], m[2] || m[3] || 'Executive Leadership', companyName);
          if (cl && !seen.has(cl.name.toLowerCase())) {
            seen.add(cl.name.toLowerCase());
            executives.push({ ...cl, source: 'Wikipedia Infobox (Key People)', sourceUrl });
          }
        }
      }

      // 2. founders = [[Patrick Collison]] <br>[[John Collison]]
      const foundersMatch = raw.match(/founders?\s*=\s*([^\n\r]+(?:\n\r?[*|{<][^\n\r]+)*)/i);
      if (foundersMatch) {
        const block = foundersMatch[1];
        const nameMatches = block.matchAll(/\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g);
        for (const nm of nameMatches) {
          const cl = cleanExecutive(nm[1], 'Co-Founder & Executive', companyName);
          if (cl && !seen.has(cl.name.toLowerCase())) {
            seen.add(cl.name.toLowerCase());
            executives.push({ ...cl, source: 'Wikipedia Infobox (Founders)', sourceUrl });
          }
        }
      }

      // 3. Lead text: "by Ivan Zhao and Simon Last" or "by [[Dylan Field]]"
      const createdMatch = raw.match(/(?:created|founded|started|established)\s+(?:in\s+\d{4}\s+)?by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)(?:\s*(?:and|,)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+))?/i);
      if (createdMatch) {
        if (createdMatch[1]) {
          const cl = cleanExecutive(createdMatch[1], 'Founder & Executive', companyName);
          if (cl && !seen.has(cl.name.toLowerCase())) {
            seen.add(cl.name.toLowerCase());
            executives.push({ ...cl, source: 'Wikipedia Official Company History', sourceUrl });
          }
        }
        if (createdMatch[2]) {
          const cl = cleanExecutive(createdMatch[2], 'Co-Founder & Executive', companyName);
          if (cl && !seen.has(cl.name.toLowerCase())) {
            seen.add(cl.name.toLowerCase());
            executives.push({ ...cl, source: 'Wikipedia Official Company History', sourceUrl });
          }
        }
      }
    }
  }

  return executives;
}

async function run() {
  const companies = ['Stripe', 'Notion', 'Figma', 'Shopify', 'OpenAI', 'Datadog', 'Snowflake', 'HubSpot'];
  for (const c of companies) {
    const list = await fetchWikiLeadership(c);
    console.log(`\nCompany: ${c}`);
    console.log(list.map(e => `  - ${e.name} (${e.title}) [Source: ${e.source}]`));
  }
}

run();
