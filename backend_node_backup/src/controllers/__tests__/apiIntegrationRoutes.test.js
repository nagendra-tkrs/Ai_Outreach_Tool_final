const request = require('supertest');
const mongoose = require('mongoose');
const { app } = require('../../server');
const Company = require('../../models/Company');
const Contact = require('../../models/Contact');
const OutreachMessage = require('../../models/OutreachMessage');
const CrawledPage = require('../../models/CrawledPage');
const CompanyResearch = require('../../models/CompanyResearch');

describe('API Integration Routes: Pattern, Outreach & Research Endpoints', () => {
  let testCompany;
  let testCompanyNoPattern;

  beforeAll(async () => {
    const testUri = process.env.MONGODB_TEST_URI || 'mongodb://127.0.0.1:27017/ai_client_outreach_test';
    if (mongoose.connection.readyState === 0) {
      await mongoose.connect(testUri);
    }
  });

  beforeEach(async () => {
    // 1. Create company with established pattern
    testCompany = await Company.create({
      companyName: 'PatternTech Enterprises',
      website: 'https://patterntech.com',
      normalizedWebsite: 'patterntech.com',
      officialDomain: 'patterntech.com',
      corporateEmailDomain: 'patterntech.com'
    });

    // Known employee contacts to establish first.last pattern
    await Contact.create([
      {
        companyId: testCompany._id,
        name: 'Sarah Connor',
        designation: 'VP Engineering',
        roleCategory: 'vp',
        email: 'sarah.connor@patterntech.com',
        personVerified: 'true',
        companyMatchStatus: 'VERIFIED',
        emailStatus: 'DIRECTLY_VERIFIED'
      },
      {
        companyId: testCompany._id,
        name: 'John Connor',
        designation: 'Head of Data',
        roleCategory: 'head_of_data',
        email: 'john.connor@patterntech.com',
        personVerified: 'true',
        companyMatchStatus: 'VERIFIED',
        emailStatus: 'DIRECTLY_VERIFIED'
      }
    ]);

    // 2. Create company with no pattern evidence
    testCompanyNoPattern = await Company.create({
      companyName: 'Unknown Corp',
      website: 'https://unknowncorp.io',
      normalizedWebsite: 'unknowncorp.io',
      officialDomain: 'unknowncorp.io'
    });
  });

  afterEach(async () => {
    if (testCompany && testCompanyNoPattern) {
      await Company.deleteMany({ _id: { $in: [testCompany._id, testCompanyNoPattern._id] } });
      await Contact.deleteMany({ companyId: { $in: [testCompany._id, testCompanyNoPattern._id] } });
      await OutreachMessage.deleteMany({ companyId: { $in: [testCompany._id, testCompanyNoPattern._id] } });
      await CrawledPage.deleteMany({ companyId: { $in: [testCompany._id, testCompanyNoPattern._id] } });
      await CompanyResearch.deleteMany({ companyId: { $in: [testCompany._id, testCompanyNoPattern._id] } });
    }
  });

  afterAll(async () => {
    await Company.deleteMany({ normalizedWebsite: { $regex: /patterntech|unknowncorp/ } });
    await Contact.deleteMany({});
    await OutreachMessage.deleteMany({});
    await CrawledPage.deleteMany({});
    await CompanyResearch.deleteMany({});
    await mongoose.disconnect();
  });

  describe('GET /api/companies/:companyId/contacts/pattern', () => {
    test('1. Returns 200 with valid pattern data when evidence exists', async () => {
      const res = await request(app)
        .get('/api/companies/' + testCompany._id + '/contacts/pattern')
        .expect(200);

      expect(res.body.success).toBe(true);
      expect(res.body.data).toBeDefined();
      expect(res.body.data.pattern).toBe('first.last');
      expect(res.body.data.emailDomain).toBe('patterntech.com');
      expect(res.body.data.confidence).toBeGreaterThanOrEqual(80);
      expect(res.body.data.evidence.length).toBeGreaterThanOrEqual(2);
      expect(res.body.data.status).toBe('PATTERN_VERIFIED');
    });

    test('2. Returns 200 + NOT_FOUND stable schema when no email pattern exists', async () => {
      const res = await request(app)
        .get('/api/companies/' + testCompanyNoPattern._id + '/contacts/pattern')
        .expect(200);

      expect(res.body.success).toBe(true);
      expect(res.body.data).toBeDefined();
      expect(res.body.data.pattern).toBeNull();
      expect(res.body.data.confidence).toBe(0);
      expect(res.body.data.evidence).toEqual([]);
      expect(res.body.data.status).toBe('NOT_FOUND');
    });

    test('3. Returns 404 for a non-existent company ID', async () => {
      const fakeId = new mongoose.Types.ObjectId();
      const res = await request(app)
        .get('/api/companies/' + fakeId + '/contacts/pattern')
        .expect(404);

      expect(res.body.success).toBe(false);
      expect(res.body.message).toContain('Company not found');
    });
  });

  describe('GET /api/companies/:companyId/outreach', () => {
    test('4. Returns 200 with empty array when no outreach is generated yet', async () => {
      const res = await request(app)
        .get('/api/companies/' + testCompany._id + '/outreach')
        .expect(200);

      expect(res.body.success).toBe(true);
      expect(Array.isArray(res.body.data)).toBe(true);
      expect(res.body.data.length).toBe(0);
    });

    test('5. Returns 200 with real stored outreach messages', async () => {
      await OutreachMessage.create([
        {
          companyId: testCompany._id,
          step: 1,
          stepLabel: 'Step 1: Strategic AI Opportunity',
          subject: 'AI Strategy for PatternTech',
          bodyHtml: '<p>Hi Sarah</p>',
          bodyText: 'Hi Sarah',
          focusService: 'AI Strategy Consulting',
          status: 'draft',
          recipientEmail: 'sarah.connor@patterntech.com',
          recipientName: 'Sarah Connor'
        },
        {
          companyId: testCompany._id,
          step: 2,
          stepLabel: 'Step 2: Practical Value & Workflow Proof',
          subject: 'Re: AI Strategy for PatternTech',
          bodyHtml: '<p>Following up</p>',
          bodyText: 'Following up',
          focusService: 'AI Strategy Consulting',
          status: 'draft',
          recipientEmail: 'sarah.connor@patterntech.com',
          recipientName: 'Sarah Connor'
        }
      ]);

      const res = await request(app)
        .get('/api/companies/' + testCompany._id + '/outreach')
        .expect(200);

      expect(res.body.success).toBe(true);
      expect(res.body.data.length).toBe(2);
      expect(res.body.data[0].step).toBe(1);
      expect(res.body.data[0].subject).toBe('AI Strategy for PatternTech');
      expect(res.body.data[1].step).toBe(2);
      expect(res.body.data[0].recipientName).toBe('Sarah Connor');
    });

    test('6. Returns 404 for a non-existent company ID on outreach', async () => {
      const fakeId = new mongoose.Types.ObjectId();
      const res = await request(app)
        .get('/api/companies/' + fakeId + '/outreach')
        .expect(404);

      expect(res.body.success).toBe(false);
      expect(res.body.message).toContain('Company not found');
    });
  });

  describe('GET /api/companies/:companyId/research', () => {
    test('7. Returns 200 with data: null when existing company has no research generated yet', async () => {
      const res = await request(app)
        .get('/api/companies/' + testCompany._id + '/research')
        .expect(200);

      expect(res.body.success).toBe(true);
      expect(res.body.data).toBeNull();
      expect(res.body.message).toContain('No research found');
    });

    test('8. Returns 200 with full research payload when existing research is present', async () => {
      await CompanyResearch.create({
        companyId: testCompany._id,
        summary: 'PatternTech develops advanced AI pattern matching software.',
        valueProposition: 'Automate pattern detection with deep neural pipelines.',
        coreOfferings: ['Pattern Matcher', 'Neural Pipeline', 'Data Ops'],
        targetAudience: 'Enterprise Data Leaders',
        detectedPainPoints: [
          { title: 'Scaling pipelines', description: 'Bottlenecks in processing large datasets' }
        ],
        techStack: ['Node.js', 'Python', 'PyTorch'],
        competitors: ['PatternX', 'DataCorp'],
        icebreakers: ['Loved your recent AI release!'],
        icpFitScore: 92,
        icpFitReasoning: 'Strong fit for TKSR AI strategy consulting.',
        fallbackUsed: false,
        researchSource: 'website_crawl',
        researchMethod: 'WEBSITE_CRAWLED',
        sourcesUsed: [{ url: 'https://patterntech.com/about', title: 'About Us', pageType: 'about' }]
      });

      const res = await request(app)
        .get('/api/companies/' + testCompany._id + '/research')
        .expect(200);

      expect(res.body.success).toBe(true);
      expect(res.body.data).toBeDefined();
      expect(res.body.data.summary).toContain('PatternTech develops');
      expect(res.body.data.coreOfferings).toHaveLength(3);
      expect(res.body.data.icpFitScore).toBe(92);
      expect(res.body.data.fallbackUsed).toBe(false);
      expect(res.body.data.sourcesUsed).toHaveLength(1);
    });

    test('9. Returns 200 with fallback research evidence and citations', async () => {
      await CompanyResearch.create({
        companyId: testCompany._id,
        summary: 'PatternTech fallback intelligence synthesized from public web records.',
        valueProposition: 'Public corporate intelligence.',
        coreOfferings: ['Enterprise Intelligence'],
        targetAudience: 'B2B Buyers',
        detectedPainPoints: [{ title: 'Access Controls', description: 'Website protected by Akamai' }],
        icpFitScore: 85,
        fallbackUsed: true,
        blockReason: 'Official website access was blocked by CDN/Access Controls (Akamai / Cloudflare / Access Denied).',
        researchSource: 'public_sources',
        researchMethod: 'WEBSITE_BLOCKED_FALLBACK_USED',
        evidenceItems: [
          {
            sourceUrl: 'https://en.wikipedia.org/wiki/PatternTech',
            sourceTitle: 'PatternTech - Wikipedia',
            sourceType: 'WIKIPEDIA_CORPORATE_RECORD',
            evidenceText: 'PatternTech is a multinational AI enterprise.'
          }
        ]
      });

      const res = await request(app)
        .get('/api/companies/' + testCompany._id + '/research')
        .expect(200);

      expect(res.body.success).toBe(true);
      expect(res.body.data.fallbackUsed).toBe(true);
      expect(res.body.data.blockReason).toContain('Akamai / Cloudflare');
      expect(res.body.data.evidenceItems).toHaveLength(1);
      expect(res.body.data.evidenceItems[0].sourceType).toBe('WIKIPEDIA_CORPORATE_RECORD');
    });

    test('10. Returns 404 for non-existent company ID on research', async () => {
      const fakeId = new mongoose.Types.ObjectId();
      const res = await request(app)
        .get('/api/companies/' + fakeId + '/research')
        .expect(404);

      expect(res.body.success).toBe(false);
      expect(res.body.message).toContain('Company not found');
    });

    test('11. Returns 400 for invalid MongoDB ObjectId on research', async () => {
      const res = await request(app)
        .get('/api/companies/invalid-id-12345/research')
        .expect(400);

      expect(res.body.success).toBe(false);
      expect(res.body.message).toContain('Invalid company ID');
    });
  });

  describe('POST /api/companies/:companyId/contacts/apply-pattern', () => {
    test('12. Applies pattern to contacts without directly published emails', async () => {
      const targetContact = await Contact.create({
        companyId: testCompany._id,
        name: 'Kyle Reese',
        designation: 'Operations Director',
        roleCategory: 'director',
        email: '',
        personVerified: 'true'
      });

      const res = await request(app)
        .post('/api/companies/' + testCompany._id + '/contacts/apply-pattern')
        .send({ pattern: 'first.last' })
        .expect(200);

      expect(res.body.success).toBe(true);

      const updated = await Contact.findById(targetContact._id);
      expect(updated.email).toBe('kyle.reese@patterntech.com');
      expect(updated.emailStatus).toBe('PATTERN_BASED_UNVERIFIED');
      expect(updated.patternUsed).toBe('first.last');
    });
  });
});
