async function printIntro(pageId) {
  const headers = { 'User-Agent': 'AIOutreachClient/1.0 (https://tksrproductservices.com; info@tksrproductservices.com)' };
  const detailUrl = `https://en.wikipedia.org/w/api.php?action=parse&pageid=${pageId}&prop=wikitext|sections&format=json`;
  const res = await fetch(detailUrl, { headers });
  const data = await res.json();
  const raw = data?.parse?.wikitext?.['*'] || '';
  console.log(`PAGE ${pageId} WIKITEXT:\n`, raw.slice(0, 1500));
}

async function run() {
  await printIntro(32845520); // Stripe, Inc.
  console.log('\n----------------------------------------\n');
  await printIntro(58710893); // Notion
}

run();
