async function test(term) {
  const headers = { 'User-Agent': 'AIOutreachClient/1.0 (https://tksrproductservices.com; info@tksrproductservices.com)' };
  const searchUrl = `https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(term)}&format=json`;
  const res = await fetch(searchUrl, { headers });
  const data = await res.json();
  console.log(`Search for "${term}":`, data?.query?.search?.map(s => ({ title: s.title, pageid: s.pageid })));
  
  if (data?.query?.search?.[0]) {
    const pageId = data.query.search[0].pageid;
    const detailUrl = `https://en.wikipedia.org/w/api.php?action=parse&pageid=${pageId}&prop=wikitext|sections&format=json`;
    const detailRes = await fetch(detailUrl, { headers });
    const detailData = await detailRes.json();
    const raw = detailData?.parse?.wikitext?.['*'] || '';
    const keyMatch = raw.match(/key_people\s*=\s*([^\n\r]+(?:\n\r?[*|{<][^\n\r]+)*)/i);
    console.log(`[${term}] Key people block:`, keyMatch ? keyMatch[0].slice(0, 300) : 'NOT FOUND');
  }
}

async function run() {
  await test('Stripe, Inc.');
  await test('Notion (productivity software)');
}

run();
