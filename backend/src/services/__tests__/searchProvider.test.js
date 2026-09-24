const dns = require('dns').promises;
const mongoose = require('mongoose');
const {
  getActiveSearchProviderConfig,
  executeSearch,
  buildDecisionMakerQueries,
  MAX_WEB_SEARCH_QUERIES,
  MAX_SEARCH_RESULTS_PER_QUERY
} = require('../search/searchProvider');
const {
  resolveDecisionMakerEmail,
  discoverAndVerifyDecisionMakerEmail
} = require('../contactService');

describe('Web Search Provider Abstraction (DuckDuckGo only / Free)', () => {
  let dnsSpy;
  const savedProvider = process.env.SEARCH_PROVIDER;
  const savedEnabled = process.env.ENABLE_PUBLIC_WEB_SEARCH;

  beforeAll(async () => {
    const testUri = process.env.MONGODB_TEST_URI || 'mongodb://127.0.0.1:27017/ai_client_outreach_test';
    if (mongoose.connection.readyState === 0) {
      await mongoose.connect(testUri);
    }
  });

  beforeEach(() => {
    dnsSpy = jest.spyOn(dns, 'resolveMx').mockResolvedValue([{ exchange: 'mail.test.com' }]);
    process.env.ENABLE_PUBLIC_WEB_SEARCH = 'true';
    // Keep unit tests fast: no retry backoff sleeps between mock searches.
    process.env.SEARCH_MAX_RETRIES = '0';
  });

  afterEach(() => {
    if (dnsSpy) dnsSpy.mockRestore();
    if (savedEnabled === undefined) delete process.env.ENABLE_PUBLIC_WEB_SEARCH;
    else process.env.ENABLE_PUBLIC_WEB_SEARCH = savedEnabled;
    delete process.env.SEARCH_MAX_RETRIES;
    if (savedProvider === undefined) delete process.env.SEARCH_PROVIDER;
    else process.env.SEARCH_PROVIDER = savedProvider;
    if (global.fetch && global.fetch.mockRestore) global.fetch.mockRestore();
    global.fetch = undefined;
  });

  afterAll(async () => {
    if (dnsSpy) dnsSpy.mockRestore();
    await mongoose.disconnect();
  });

  describe('Active provider selection (DuckDuckGo only)', () => {
    test('DuckDuckGo (public_web) is selected by default', async () => {
      const cfg = getActiveSearchProviderConfig();
      expect(cfg.providerName).toBe('public_web');
      expect(cfg.isConfigured).toBe(true);
      expect(cfg.reason).toBe('DUCKDUCKGO_ONLY');
    });

    test('none is selected when search is explicitly disabled', async () => {
      process.env.SEARCH_PROVIDER = 'none';
      const cfg = getActiveSearchProviderConfig();
      expect(cfg.providerName).toBe('none');
      expect(cfg.isConfigured).toBe(false);
    });

    test('unknown provider disables search (never falls back to a paid provider)', async () => {
      process.env.SEARCH_PROVIDER = 'google';
      const cfg = getActiveSearchProviderConfig();
      expect(cfg.providerName).toBe('none');
      expect(cfg.isConfigured).toBe(false);
    });
  });

  describe('executeSearch dispatch', () => {
    test('dispatches to DuckDuckGo (public_web) for the active free provider', async () => {
      global.fetch = jest.fn(async (url) => {
        const s = typeof url === 'string' ? url : url.toString();
        if (s.includes('html.duckduckgo.com/html')) {
          return {
            ok: true,
            status: 200,
            text: async () => {
              return `<div class="result results_links results_links_deep web_result result__body">` +
                `<a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fapex.com%2Fceo">Apex CEO</a>` +
                `<a class="result__snippet" href="#">Jane Doe runs Apex.</a>` +
                `</div></div></div>`;
            }
          };
        }
        return { ok: false, status: 404, text: async () => 'not found' };
      });

      const res = await executeSearch('"Apex" CEO');
      expect(res.provider).toBe('public_web');
      expect(res.source).toBe('duckduckgo');
      expect(res.results.length).toBeGreaterThan(0);
    });

    test('parses live-style DuckDuckGo HTML (nested result__body on a child div)', async () => {
      // Real html.duckduckgo.com structure: outer .result wraps an inner
      // `<div class="links_main links_deep result__body">` block.
      const realHtml =
        `<div class="result results_links results_links_deep web-result ">` +
        `<div class="links_main links_deep result__body">` +
        `<h2 class="result__title"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fapex.com%2Fceo&amp;rut=abc">Apex CEO</a></h2>` +
        `<div class="result__extras"><div class="result__extras__url"></div></div>` +
        `<a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fapex.com%2Fceo&amp;rut=abc">Jane Doe runs Apex.</a>` +
        `<div class="clear"></div>` +
        `</div>` +
        `</div>` +
        `<div class="result results_links results_links_deep web-result ">` +
        `<div class="links_main links_deep result__body">` +
        `<h2 class="result__title"><a rel="nofollow" class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fapex.com%2Fteam">Apex Team</a></h2>` +
        `<div class="result__extras"></div>` +
        `<a class="result__snippet">The team page.</a>` +
        `<div class="clear"></div>` +
        `</div>` +
        `</div>`;

      global.fetch = jest.fn(async (url) => {
        const s = typeof url === 'string' ? url : url.toString();
        if (s.includes('html.duckduckgo.com/html')) {
          return { ok: true, status: 200, text: async () => realHtml };
        }
        return { ok: false, status: 404, text: async () => 'not found' };
      });

      const res = await executeSearch('"Apex" CEO');
      expect(res.provider).toBe('public_web');
      expect(res.results.length).toBe(2);
      expect(res.results[0].title).toBe('Apex CEO');
      expect(res.results[0].url).toBe('https://apex.com/ceo');
      expect(res.results[0].snippet).toContain('Jane Doe runs Apex.');
      expect(res.results[1].url).toBe('https://apex.com/team');
    });

    test('returns controlled NO_RESULTS for empty search response', async () => {
      global.fetch = jest.fn(async () => ({
        ok: true,
        status: 200,
        text: async () => ''
      }));

      const res = await executeSearch('"Apex" CEO');
      expect(res.configured).toBe(true);
      expect(['NO_RESULTS', 'SEARCH_BLOCKED', 'SEARCH_TIMEOUT', 'SEARCH_UNAVAILABLE']).toContain(res.state);
      expect(res.results).toEqual([]);
    });

    test('returns empty, unconfigured result when search is disabled', async () => {
      process.env.SEARCH_PROVIDER = 'none';
      const res = await executeSearch('"Apex" CEO');
      expect(res.provider).toBe('none');
      expect(res.configured).toBe(false);
      expect(res.error).toBe('SEARCH_PROVIDER_NOT_CONFIGURED');
      expect(res.results).toEqual([]);
    });

    test('never calls any paid search API endpoint', async () => {
      const endpoints = ['googleapis.com/customsearch', 'api.bing.com', 'serpapi.com', 'api.tavily.com', 'exa.io', 'serper.dev', 'api.perplexity.ai'];
      const hits = [];

      global.fetch = jest.fn(async (url) => {
        const s = typeof url === 'string' ? url : url.toString();
        hits.push(s.split('?')[0]);
        if (s.includes('html.duckduckgo.com/html')) {
          return {
            ok: true,
            status: 200,
            text: async () =>
              `<div class="result results_links results_links_deep web_result result__body">` +
              `<a class="result__a" href="https://x.example">Title</a>` +
              `<a class="result__snippet">Snippet.</a></div></div></div>`
          };
        }
        return { ok: false, status: 404, text: async () => 'not found' };
      });

      const res = await executeSearch('"Acme" CEO');
      expect(res.results.length).toBeGreaterThan(0);
      expect(hits.some(h => endpoints.some(e => h.includes(e)))).toBe(false);
    });
  });

  describe('Query / result limits', () => {
    test('buildDecisionMakerQueries returns a controlled, bounded query set', () => {
      const queries = buildDecisionMakerQueries('Acme', 'acme.com', 'AI', 'US', 'AI Strategy & Solutions');
      expect(queries.length).toBeGreaterThan(0);
      expect(queries.length).toBeLessThanOrEqual(MAX_WEB_SEARCH_QUERIES);
      // Base role queries always present
      expect(queries[0]).toContain('"Acme"');
      expect(queries[0]).toContain('CEO');
    });

    test('site query is included when a domain is present', () => {
      const queries = buildDecisionMakerQueries('Acme', 'acme.com');
      expect(queries.some(q => q.includes('site:acme.com'))).toBe(true);
    });

    test('public web results are sliced to MAX_SEARCH_RESULTS_PER_QUERY', async () => {
      const anchorHtml = Array.from({ length: 12 }, (_, i) =>
        `<div class="result results_links results_links_deep web_result result__body">` +
        `<a class="result__a" href="https://example.com/${i}">Result ${i}</a>` +
        `<a class="result__snippet" href="#">Snippet ${i}</a>` +
        `</div></div></div>`
      ).join('');

      global.fetch = jest.fn(async (url) => {
        const s = typeof url === 'string' ? url : url.toString();
        if (s.includes('html.duckduckgo.com/html')) {
          return { ok: true, status: 200, text: async () => anchorHtml };
        }
        return { ok: false, status: 404, text: async () => 'not found' };
      });

      const res = await executeSearch('"Acme" CEO', { limit: 5 });
      expect(res.provider).toBe('public_web');
      expect(res.results.length).toBeLessThanOrEqual(5);
    });
  });

  describe('Email discovery never fabricates', () => {
    test('NOT_FOUND when no evidence (DuckDuckGo returns nothing) and email is never guessed', async () => {
      global.fetch = jest.fn(async () => ({
        ok: true,
        status: 200,
        text: async () => ''
      }));

      const result = await discoverAndVerifyDecisionMakerEmail(
        { name: 'Unknown Exec', designation: 'CEO', roleStatus: 'current', candidateEmployer: 'Unconfigured Co' },
        { companyName: 'Unconfigured Co', website: 'https://unconfigured.com', officialDomain: 'unconfigured.com' }
      );

      expect(result.email).toBeNull();
      expect(['NOT_FOUND', 'REJECTED']).toContain(result.emailStatus);
    }, 15000);

    test('explicit published email is honored (not rejected) via resolveDecisionMakerEmail', async () => {
      const result = await resolveDecisionMakerEmail(
        'Jane Admin',
        'Apex Systems',
        'apex.com',
        ['jane.admin@apex.com']
      );
      expect(result.email).toBe('jane.admin@apex.com');
      expect(result.emailStatus).toBe('DIRECTLY_VERIFIED');
      expect(result.isExactPublished).toBe(true);
    });
  });
});