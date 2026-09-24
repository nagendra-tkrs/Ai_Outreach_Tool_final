const mongoose = require('mongoose');
const { parseRetryAfter, DEFAULT_HEADERS, DEFAULT_USER_AGENT } = require('../fetcher');
const { isAllowed } = require('../robotsHandler');
const { runCompanyResearch } = require('../../services/researchService');
const Company = require('../../models/Company');
const CrawledPage = require('../../models/CrawledPage');
const CompanyResearch = require('../../models/CompanyResearch');

describe('Crawler Resilience & Pipeline Protection', () => {
  describe('Retry-After Parser', () => {
    test('parses integer seconds into milliseconds', () => {
      expect(parseRetryAfter('3')).toBe(3000);
      expect(parseRetryAfter('10')).toBe(10000);
    });

    test('caps extreme Retry-After seconds at 10000ms', () => {
      expect(parseRetryAfter('120')).toBe(10000);
    });

    test('handles null or invalid header gracefully', () => {
      expect(parseRetryAfter(null)).toBeNull();
      expect(parseRetryAfter('invalid')).toBe(2000);
    });
  });

  describe('Standard Request Headers', () => {
    test('uses standard compliant browser / crawler headers', () => {
      expect(DEFAULT_HEADERS['User-Agent']).toContain('Mozilla/5.0');
      expect(DEFAULT_HEADERS['Accept']).toContain('text/html');
      expect(DEFAULT_HEADERS['Accept-Language']).toBeDefined();
      expect(DEFAULT_HEADERS['Accept-Encoding']).toBeDefined();
    });
  });

  describe('AI Pipeline Protection (researchService)', () => {
    let companyId;
    const originalFetch = global.fetch;

    beforeAll(async () => {
      const testUri = process.env.MONGODB_TEST_URI || 'mongodb://127.0.0.1:27017/ai_client_outreach_test';
      if (mongoose.connection.readyState === 0) {
        await mongoose.connect(testUri);
      }
    });

    beforeEach(async () => {
      global.fetch = jest.fn(async () => ({
        ok: false,
        status: 404,
        text: async () => 'Not Found',
        json: async () => ({})
      }));

      await Company.deleteMany({ normalizedWebsite: 'shieldedtech.io' });
      await CrawledPage.deleteMany({});
      await CompanyResearch.deleteMany({});

      const company = await Company.create({
        companyName: 'Shielded Tech',
        website: 'https://shieldedtech.io',
        normalizedWebsite: 'shieldedtech.io',
        industry: 'Cybersecurity',
        country: 'USA'
      });
      companyId = company._id;
    });

    afterEach(async () => {
      global.fetch = originalFetch;
      await Company.deleteMany({ normalizedWebsite: 'shieldedtech.io' });
      await CrawledPage.deleteMany({});
      await CompanyResearch.deleteMany({});
    });

    test('NEVER passes blocked or challenge pages to AI research', async () => {
      // Create blocked / challenge pages only
      await CrawledPage.create({
        companyId,
        url: 'https://shieldedtech.io',
        normalizedUrl: 'https://shieldedtech.io',
        title: 'Just a moment...',
        content: 'Cloudflare challenge page text that must never reach AI',
        statusCode: 403,
        wordCount: 10,
        crawlStatus: 'blocked',
        contentAvailable: false,
        contentQuality: 'error',
        isChallengePage: true,
        crawledAt: new Date()
      });

      await CrawledPage.create({
        companyId,
        url: 'https://shieldedtech.io/about',
        normalizedUrl: 'https://shieldedtech.io/about',
        title: 'Access Denied',
        content: 'You do not have permission',
        statusCode: 403,
        wordCount: 5,
        crawlStatus: 'blocked',
        contentAvailable: false,
        contentQuality: 'error',
        isChallengePage: true,
        crawledAt: new Date()
      });

      const research = await runCompanyResearch(companyId);

      expect(research).toBeDefined();
      expect(research.summary).toBeDefined();
      expect(research.summary).not.toContain('Cloudflare challenge page text that must never reach AI');
      expect(research.summary).not.toContain('You do not have permission');
      expect(research.sourcesUsed.some(s => s.url === 'https://shieldedtech.io/about')).toBe(false);
    }, 20000);

    test('successfully ingests valid completed pages into AI research', async () => {
      // Create valid completed page
      await CrawledPage.create({
        companyId,
        url: 'https://shieldedtech.io',
        normalizedUrl: 'https://shieldedtech.io',
        title: 'Shielded Tech - Advanced Threat Protection',
        content: 'Shielded Tech builds enterprise zero-trust identity and threat monitoring solutions for distributed engineering teams. Our core platform enables continuous compliance, SOC2 automation, and cloud perimeter defense.',
        statusCode: 200,
        wordCount: 30,
        crawlStatus: 'completed',
        contentAvailable: true,
        contentQuality: 'valid',
        pageType: 'about',
        isChallengePage: false,
        crawledAt: new Date()
      });

      const research = await runCompanyResearch(companyId);

      expect(research).toBeDefined();
      expect(research.sourcesUsed.length).toBe(1);
      expect(research.sourcesUsed[0].url).toBe('https://shieldedtech.io');
    }, 20000);
  });
});
