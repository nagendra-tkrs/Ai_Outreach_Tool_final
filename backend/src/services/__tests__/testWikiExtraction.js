async function getWikiLeadership(companyName) {
  try {
    const headers = {
      'User-Agent': 'AIOutreachClient/1.0 (https://tksrproductservices.com; info@tksrproductservices.com)'
    };
    const searchUrl = `https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(companyName)}&format=json`;
    const searchRes = await fetch(searchUrl, { headers });
    if (!searchRes.ok) return null;
    const searchData = await searchRes.json();
    const topPage = searchData?.query?.search?.[0];
    if (!topPage) return null;

    const pageId = topPage.pageid;
    // Fetch wikitext of first section
    const detailUrl = `https://en.wikipedia.org/w/api.php?action=parse&pageid=${pageId}&prop=wikitext|sections&format=json`;
    const detailRes = await fetch(detailUrl, { headers });
    if (!detailRes.ok) return null;
    const detailData = await detailRes.json();
    const rawWikitext = detailData?.parse?.wikitext?.['*'] || '';

    const executives = [];

    // Extract key people from wikitext
    // Matches patterns like:
    // | key_people = {{ubl|[[Patrick Collison]] (CEO)|[[John Collison]] (President)}}
    // | key_people = [[Sam Altman]] (CEO)<br>[[Greg Brockman]] (President)
    const keyPeopleBlockMatch = rawWikitext.match(/key_people\s*=\s*([^\n\r]+(?:\n\r?[*|{][^\n\r]+)*)/i);

    if (keyPeopleBlockMatch) {
      const block = keyPeopleBlockMatch[1];
      // Regex for names and roles
      const matches = block.matchAll(/(?:\[\[)?([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)(?:\]\])?\s*(?:\(([^)]+)\)|-\s*([A-Za-z\s]+))/g);
      for (const m of matches) {
        const rawName = m[1].replace(/\[\[|\]\]/g, '').trim();
        const rawTitle = (m[2] || m[3] || 'Executive').replace(/\[\[|\]\]/g, '').trim();
        if (rawName.split(' ').length >= 2 && !['United States', 'San Francisco', 'New York', 'Chief Executive', 'Vice President'].includes(rawName)) {
          executives.push({
            name: rawName,
            title: rawTitle,
            source: 'Wikipedia Verified Executive Listing',
            sourceUrl: `https://en.wikipedia.org/wiki/${encodeURIComponent(topPage.title)}`
          });
        }
      }
    }

    // Also look for "founded by X and Y" in wikitext
    const foundedMatch = rawWikitext.match(/(?:founded|co-founded)\s+(?:in\s+\d{4}\s+)?by\s+\[\[([^\]|]+)(?:\|[^\]]+)?\]\](?:\s*(?:,|and)\s*\[\[([^\]|]+)(?:\|[^\]]+)?\]\])?/i);
    if (foundedMatch) {
      if (foundedMatch[1] && !executives.some(e => e.name.toLowerCase().includes(foundedMatch[1].toLowerCase()))) {
        executives.push({
          name: foundedMatch[1].trim(),
          title: 'Founder & Executive',
          source: 'Wikipedia Verified Leadership',
          sourceUrl: `https://en.wikipedia.org/wiki/${encodeURIComponent(topPage.title)}`
        });
      }
      if (foundedMatch[2] && !executives.some(e => e.name.toLowerCase().includes(foundedMatch[2].toLowerCase()))) {
        executives.push({
          name: foundedMatch[2].trim(),
          title: 'Co-Founder & Executive',
          source: 'Wikipedia Verified Leadership',
          sourceUrl: `https://en.wikipedia.org/wiki/${encodeURIComponent(topPage.title)}`
        });
      }
    }

    return {
      title: topPage.title,
      url: `https://en.wikipedia.org/wiki/${encodeURIComponent(topPage.title)}`,
      executives
    };
  } catch (err) {
    console.error(`Wiki fetch error for ${companyName}:`, err.message);
    return null;
  }
}

async function testAll() {
  const list = ['Stripe, Inc.', 'Shopify', 'Datadog', 'Snowflake Inc.', 'HubSpot', 'Atlassian', 'Figma', 'Notion (app)', 'OpenAI'];
  for (const c of list) {
    const res = await getWikiLeadership(c);
    console.log(`\n================== ${c} ==================`);
    console.log(`URL: ${res?.url}`);
    console.log(`Executives found (${res?.executives?.length || 0}):`, res?.executives);
  }
}

testAll();
