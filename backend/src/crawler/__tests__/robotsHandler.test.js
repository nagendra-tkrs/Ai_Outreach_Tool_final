const { clearCache } = require('../robotsHandler');
const { isAllowed, getSitemaps } = require('../robotsHandler');

afterEach(() => {
  clearCache();
});

describe('robotsHandler', () => {
  test('returns true for non-existent robots.txt (allow all)', async () => {
    const allowed = await isAllowed('https://nonexistent-domain-xyz-12345.com/page');
    expect(allowed).toBe(true);
  }, 15000);

  test('getSitemaps returns array for non-existent domain', async () => {
    const sitemaps = await getSitemaps('https://nonexistent-domain-xyz-12345.com');
    expect(Array.isArray(sitemaps)).toBe(true);
  }, 15000);
});
