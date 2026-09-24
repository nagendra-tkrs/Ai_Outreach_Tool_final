const mongoose = require('mongoose');
const request = require('supertest');
const { app } = require('../../server');
const Company = require('../../models/Company');
const CrawledPage = require('../../models/CrawledPage');
const ResearchJob = require('../../models/ResearchJob');

let companyId;

beforeAll(async () => {
  const testUri = process.env.MONGODB_TEST_URI || 'mongodb://127.0.0.1:27017/ai_client_outreach_test';
  await mongoose.connect(testUri);
});

afterAll(async () => {
  await Company.deleteMany({});
  await CrawledPage.deleteMany({});
  await ResearchJob.deleteMany({});
});

beforeEach(async () => {
  await Company.deleteMany({});
  await CrawledPage.deleteMany({});
  await ResearchJob.deleteMany({});

  const company = await Company.create({
    companyName: 'Test Corp',
    website: 'https://example.com',
    normalizedWebsite: 'https://example.com',
    industry: 'Technology',
    country: 'USA'
  });
  companyId = company._id;
});

describe('Crawl API', () => {
  describe('GET /api/companies/:companyId/crawl', () => {
    test('returns crawl status for company', async () => {
      const res = await request(app)
        .get(`/api/companies/${companyId}/crawl`)
        .expect(200);

      expect(res.body.success).toBe(true);
      expect(res.body.data.crawlStatus).toBe('pending');
      expect(res.body.data.job).toBeNull();
    });

    test('returns 404 for non-existent company', async () => {
      const fakeId = new mongoose.Types.ObjectId();
      const res = await request(app)
        .get(`/api/companies/${fakeId}/crawl`)
        .expect(404);

      expect(res.body.success).toBe(false);
    });
  });

  describe('POST /api/companies/:companyId/crawl', () => {
    test('starts crawl for a company', async () => {
      const res = await request(app)
        .post(`/api/companies/${companyId}/crawl`)
        .timeout(60000)
        .expect(200);

      expect(res.body.success).toBe(true);
      expect(res.body.data.status).toBe('completed');
      expect(res.body.data.pagesCrawled).toBeGreaterThanOrEqual(0);
    }, 60000);

    test('returns 404 for non-existent company', async () => {
      const fakeId = new mongoose.Types.ObjectId();
      const res = await request(app)
        .post(`/api/companies/${fakeId}/crawl`)
        .expect(404);

      expect(res.body.success).toBe(false);
    });
  });

  describe('GET /api/companies/:companyId/pages', () => {
    test('returns empty pages for non-crawled company', async () => {
      const res = await request(app)
        .get(`/api/companies/${companyId}/pages`)
        .expect(200);

      expect(res.body.success).toBe(true);
      expect(res.body.data.pages).toEqual([]);
    });

    test('returns 404 for non-existent company', async () => {
      const fakeId = new mongoose.Types.ObjectId();
      const res = await request(app)
        .get(`/api/companies/${fakeId}/pages`)
        .expect(404);

      expect(res.body.success).toBe(false);
    });
  });

  describe('CrawledPage model', () => {
    test('prevents duplicate pages for same company and URL', async () => {
      const pageData = {
        companyId,
        url: 'https://example.com/about',
        normalizedUrl: 'https://example.com/about',
        title: 'About',
        statusCode: 200,
        pageType: 'about',
        crawlStatus: 'completed',
        crawledAt: new Date()
      };

      await CrawledPage.create(pageData);

      await expect(CrawledPage.create(pageData)).rejects.toThrow();
    });

    test('allows same URL for different companies', async () => {
      const company2 = await Company.create({
        companyName: 'Other Corp',
        website: 'https://other.com',
        normalizedWebsite: 'https://other.com'
      });

      await CrawledPage.create({
        companyId,
        url: 'https://example.com/about',
        normalizedUrl: 'https://example.com/about',
        statusCode: 200,
        crawlStatus: 'completed',
        crawledAt: new Date()
      });

      const page2 = await CrawledPage.create({
        companyId: company2._id,
        url: 'https://example.com/about',
        normalizedUrl: 'https://example.com/about',
        statusCode: 200,
        crawlStatus: 'completed',
        crawledAt: new Date()
      });

      expect(page2).toBeDefined();
    });
  });

  describe('ResearchJob model', () => {
    test('creates crawl job', async () => {
      const job = await ResearchJob.create({
        companyId,
        type: 'website_crawl',
        status: 'running',
        startedAt: new Date()
      });

      expect(job.status).toBe('running');
      expect(job.type).toBe('website_crawl');
    });
  });
});
