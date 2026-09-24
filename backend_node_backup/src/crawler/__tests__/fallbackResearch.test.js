const mongoose = require('mongoose');
const { fetchCompanyPublicOverview } = require('../../services/webSearchService');
const { runCompanyResearch } = require('../../services/researchService');
const Company = require('../../models/Company');
const CrawledPage = require('../../models/CrawledPage');
const CompanyResearch = require('../../models/CompanyResearch');

describe('Blocked-Website Fallback Research Pipeline', () => {
  const originalFetch = global.fetch;

  beforeAll(async () => {
    process.env.ENABLE_PUBLIC_WEB_SEARCH = 'true';
    const testUri = process.env.MONGODB_TEST_URI || 'mongodb://127.0.0.1:27017/ai_client_outreach_test';
    if (mongoose.connection.readyState === 0) {
      await mongoose.connect(testUri);
    }
  });

  beforeEach(() => {
    // Mock global.fetch to intercept Wikipedia, DuckDuckGo, and AI endpoints
    global.fetch = jest.fn(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();

      // 1. Mock Wikipedia Search API
      if (urlStr.includes('en.wikipedia.org') && urlStr.includes('list=search')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            query: {
              search: [
                {
                  title: 'Tata Consultancy Services',
                  snippet: '<span>Tata Consultancy Services</span> (TCS) is an Indian multinational information technology services and consulting company headquartered in Mumbai.',
                  pageid: 123456
                }
              ]
            }
          }),
          text: async () => JSON.stringify({
            query: {
              search: [
                {
                  title: 'Tata Consultancy Services',
                  snippet: '<span>Tata Consultancy Services</span> (TCS) is an Indian multinational information technology services and consulting company headquartered in Mumbai.',
                  pageid: 123456
                }
              ]
            }
          })
        };
      }

      // 2. Mock Wikipedia Infobox Parse API
      if (urlStr.includes('en.wikipedia.org') && urlStr.includes('action=parse')) {
        const mockInfoboxHtml = `
          <table class="infobox vcard">
            <tr><th scope="row" class="infobox-label">Type</th><td class="infobox-data">Public</td></tr>
            <tr><th scope="row" class="infobox-label">Industry</th><td class="infobox-data">Information technology</td></tr>
            <tr><th scope="row" class="infobox-label">Key people</th><td class="infobox-data"><a href="/wiki/K._Krithivasan">K. Krithivasan</a> (CEO and MD)</td></tr>
          </table>
        `;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            parse: {
              title: 'Tata Consultancy Services',
              text: {
                '*': mockInfoboxHtml
              }
            }
          }),
          text: async () => JSON.stringify({
            parse: {
              title: 'Tata Consultancy Services',
              text: {
                '*': mockInfoboxHtml
              }
            }
          })
        };
      }

      // 3. Mock DuckDuckGo HTML Search (free provider - the only active one)
      if (urlStr.includes('html.duckduckgo.com')) {
        const ddgHtml = `
          <html><body>
            <div class="result results_links results_links_deep web_result result__body">
              <h2 class="result__title">
                <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.tcs.com%2Fwhat-we-do">Tata Consultancy Services - IT Services &amp; Consulting</a>
              </h2>
              <a class="result__snippet">Tata Consultancy Services is a global leader in IT services, digital transformation, and business solutions partnering with global enterprises.</a>
            </div></div></div>
            <div class="result results_links results_links_deep web_result result__body">
              <h2 class="result__title">
                <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.tcs.com%2Fleadership">Tata Consultancy Services Leadership &amp; Executive Management</a>
              </h2>
              <a class="result__snippet">K. Krithivasan serves as Chief Executive Officer and Managing Director of Tata Consultancy Services.</a>
            </div></div></div>
          </body></html>
        `;
        return {
          ok: true,
          status: 200,
          text: async () => ddgHtml,
          json: async () => ({})
        };
      }

      // 4. Mock Gemini / OpenAI API calls if triggered
      if (urlStr.includes('generativelanguage.googleapis.com') || urlStr.includes('api.openai.com')) {
        const mockAiJson = {
          candidates: [
            {
              content: {
                parts: [
                  {
                    text: JSON.stringify({
                      summary: 'Tata Consultancy Services is an Indian multinational information technology services and consulting company.',
                      valueProposition: 'Delivering end-to-end enterprise IT, digital engineering, and AI automation solutions.',
                      coreOfferings: ['IT Consulting', 'Cloud Transformation', 'Enterprise AI & Automation'],
                      targetAudience: 'Global Fortune 500 and enterprise businesses',
                      detectedPainPoints: [
                        { title: 'Enterprise AI Governance', description: 'Managing data compliance across hybrid clouds.' }
                      ],
                      techStack: ['Cloud Platforms', 'Enterprise Software', 'AI Infrastructure'],
                      competitors: ['Infosys', 'Wipro', 'Accenture'],
                      icebreakers: [
                        'I noticed TCS\'s strong momentum in accelerating enterprise AI transformations.'
                      ],
                      icpFitScore: 92,
                      icpFitReasoning: 'Excellent ICP match for AI and automation consulting.',
                      keyPersonnel: [
                        { name: 'K. Krithivasan', title: 'Chief Executive Officer & MD' }
                      ]
                    })
                  }
                ]
              }
            }
          ]
        };

        return {
          ok: true,
          status: 200,
          json: async () => mockAiJson,
          text: async () => JSON.stringify(mockAiJson)
        };
      }

      // Default fallback for any other HTTP calls
      return {
        ok: false,
        status: 404,
        text: async () => 'Not Found',
        json: async () => ({})
      };
    });
  });

  afterEach(async () => {
    global.fetch = originalFetch;
    await Company.deleteMany({ normalizedWebsite: 'tcs.com' });
    await CrawledPage.deleteMany({});
    await CompanyResearch.deleteMany({});
  });

  test('fetchCompanyPublicOverview retrieves structured evidence with title, url, and snippet', async () => {
    const overview = await fetchCompanyPublicOverview('Tata Consultancy Services', 'tcs.com', 'Information Technology', 'India');

    expect(overview).toBeDefined();
    expect(Array.isArray(overview.evidenceItems)).toBe(true);
    expect(overview.evidenceItems.length).toBeGreaterThan(0);

    const firstEvidence = overview.evidenceItems[0];
    expect(firstEvidence.sourceUrl).toBeDefined();
    expect(firstEvidence.sourceTitle).toBeDefined();
    expect(firstEvidence.evidenceText).toBeDefined();
    expect(firstEvidence.sourceType).toBeDefined();
  });

  test('automatically triggers Fallback Research when website is BLOCKED by Akamai/403', async () => {
    await Company.deleteMany({ normalizedWebsite: 'tcs.com' });
    const testCompany = await Company.create({
      companyName: 'Tata Consultancy Services',
      website: 'https://www.tcs.com/',
      normalizedWebsite: 'tcs.com',
      industry: 'Information Technology',
      country: 'India'
    });
    const cid = testCompany._id;

    // Record a blocked page simulation (TCS Akamai 403 / errors.edgesuite.net)
    await CrawledPage.create({
      companyId: cid,
      url: 'https://www.tcs.com/',
      normalizedUrl: 'https://www.tcs.com/',
      title: 'Access Denied',
      content: '',
      statusCode: 403,
      wordCount: 0,
      crawlStatus: 'blocked',
      contentAvailable: false,
      contentQuality: 'error',
      isChallengePage: true,
      errorReason: 'Akamai Access Denied (errors.edgesuite.net)',
      crawledAt: new Date()
    });

    await Company.findByIdAndUpdate(cid, { crawlStatus: 'blocked' });

    const research = await runCompanyResearch(cid);

    expect(research).toBeDefined();
    expect(research.fallbackUsed).toBe(true);
    expect(research.researchSource).toBe('public_sources');
    expect(research.researchMethod).toBe('WEBSITE_BLOCKED_FALLBACK_USED');
    expect(research.summary).toBeDefined();
    expect(research.summary.length).toBeGreaterThan(20);
    expect(research.summary).not.toContain('errors.edgesuite.net');
    expect(research.summary).not.toContain('You don\'t have permission');
    expect(Array.isArray(research.evidenceItems)).toBe(true);
    expect(research.evidenceItems.length).toBeGreaterThan(0);

    const updatedCompany = await Company.findById(cid);
    expect(updatedCompany).toBeDefined();
    expect(updatedCompany.researchStatus).toBe('completed');
  });

  afterAll(async () => {
    delete process.env.ENABLE_PUBLIC_WEB_SEARCH;
    await Company.deleteMany({ normalizedWebsite: 'tcs.com' });
    await CrawledPage.deleteMany({});
    await CompanyResearch.deleteMany({});
    await mongoose.disconnect();
  });
});
