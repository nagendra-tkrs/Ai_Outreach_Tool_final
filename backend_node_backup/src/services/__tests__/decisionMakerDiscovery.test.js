const dns = require('dns').promises;
const mongoose = require('mongoose');
const {
  rankDecisionMakers,
  validateCompanyMatch,
  extractContactsFromWebsite,
  categorizeRole,
  verifyEmailAddress,
  discoverCompanyEmailPattern,
  generateCandidateEmail,
  resolveDecisionMakerEmail,
  discoverAndVerifyDecisionMakerEmail
} = require('../contactService');
const { cleanExecutive } = require('../webSearchService');
const { executeGoogleSearch } = require('../search/googleSearchProvider');
const Company = require('../../models/Company');
const CrawledPage = require('../../models/CrawledPage');
const CompanyResearch = require('../../models/CompanyResearch');
const Contact = require('../../models/Contact');

describe('Decision Maker Discovery, Company Email Pattern & Layered Verification', () => {
  const originalFetch = global.fetch;
  let dnsSpy;

  beforeAll(async () => {
    process.env.GOOGLE_SEARCH_API_KEY = 'test-mock-api-key';
    process.env.GOOGLE_SEARCH_ENGINE_ID = 'test-mock-cx';

    const testUri = process.env.MONGODB_TEST_URI || 'mongodb://127.0.0.1:27017/ai_client_outreach_test';
    if (mongoose.connection.readyState === 0) {
      await mongoose.connect(testUri);
    }
  });

  beforeEach(() => {
    dnsSpy = jest.spyOn(dns, 'resolveMx').mockResolvedValue([{ exchange: 'mail.test.com' }]);

    // Mock global.fetch to intercept Wikipedia, Google Search API, and AI endpoints
    global.fetch = jest.fn(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();

      // Mock Wikipedia search
      if (urlStr.includes('en.wikipedia.org') && urlStr.includes('list=search')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            query: {
              search: [
                {
                  title: 'Apex Systems',
                  snippet: 'Apex Systems is a technology enterprise led by CEO Jane Doe and CTO Alex Rivera.',
                  pageid: 998877
                }
              ]
            }
          })
        };
      }

      // Mock Wikipedia parse
      if (urlStr.includes('en.wikipedia.org') && urlStr.includes('action=parse')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            parse: {
              title: 'Apex Systems',
              text: {
                '*': '<table class="infobox"><tr><th>Key people</th><td>Jane Doe (CEO)<br>Alex Rivera (CTO)</td></tr></table>'
              }
            }
          })
        };
      }

      // Mock Google Custom Search API
      if (urlStr.includes('googleapis.com/customsearch')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            items: [
              {
                title: 'Apex Systems Leadership - Executive Team',
                link: 'https://apexsystems.io/team',
                snippet: 'Alex Rivera leads engineering and AI automation as Chief Technology Officer at Apex Systems.',
                displayLink: 'apexsystems.io'
              },
              {
                title: 'Jane Doe - Chief Executive Officer at Apex Systems',
                link: 'https://apexsystems.io/about',
                snippet: 'Jane Doe is the CEO of Apex Systems, directing corporate growth and enterprise client strategy.',
                displayLink: 'apexsystems.io'
              }
            ]
          })
        };
      }

      // Default mock
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
    if (dnsSpy) dnsSpy.mockRestore();
    await Company.deleteMany({ normalizedWebsite: { $regex: /test-dm/ } });
    await CrawledPage.deleteMany({});
    await CompanyResearch.deleteMany({});
    await Contact.deleteMany({});
  });

  afterAll(async () => {
    if (dnsSpy) dnsSpy.mockRestore();
    await Company.deleteMany({ normalizedWebsite: { $regex: /test-dm/ } });
    await CrawledPage.deleteMany({});
    await CompanyResearch.deleteMany({});
    await Contact.deleteMany({});
    await mongoose.disconnect();
  });

  // 1. Correct CTO selected over CEO for AI automation opportunity
  test('1. Selects CTO over CEO for an AI automation opportunity', () => {
    const candidates = [
      {
        name: 'Jane Doe',
        title: 'Chief Executive Officer',
        designation: 'Chief Executive Officer',
        roleCategory: 'ceo',
        seniority: 'executive',
        confidenceScore: 95,
        sourceType: 'official_team_page',
        roleStatus: 'current'
      },
      {
        name: 'Alex Rivera',
        title: 'Chief Technology Officer',
        designation: 'Chief Technology Officer',
        roleCategory: 'cto',
        seniority: 'executive',
        confidenceScore: 95,
        sourceType: 'official_team_page',
        roleStatus: 'current'
      }
    ];

    const company = { companyName: 'Apex Systems', employeeCount: '500' };
    const research = {
      detectedPainPoints: [{ title: 'Manual workflows', description: 'Seeking enterprise AI and workflow automation' }],
      recommendedTksrServices: ['AI & Automation Workshops', 'Workflow Automation Engineering']
    };

    const { rankedCandidates, selectedDecisionMaker, targetOpportunity } = rankDecisionMakers(candidates, company, research);

    expect(targetOpportunity).toContain('Automation');
    expect(selectedDecisionMaker).toBeDefined();
    expect(selectedDecisionMaker.name).toBe('Alex Rivera');
    expect(selectedDecisionMaker.roleCategory).toBe('cto');
    expect(selectedDecisionMaker.isPrimaryDecisionMaker).toBe(true);
    expect(selectedDecisionMaker.overallScore).toBeGreaterThan(rankedCandidates[1].overallScore);
    expect(selectedDecisionMaker.selectionReason).toContain('technology architecture and AI transformation');
  });

  // 2. CEO selected when company is small and no technical executive exists
  test('2. Selects CEO/Founder for small company strategic consulting opportunity', () => {
    const candidates = [
      {
        name: 'David Kim',
        title: 'Founder & CEO',
        designation: 'Founder & CEO',
        roleCategory: 'founder',
        seniority: 'executive',
        confidenceScore: 94,
        sourceType: 'official_team_page',
        roleStatus: 'current'
      },
      {
        name: 'Sarah Chen',
        title: 'Office Operations Manager',
        designation: 'Office Operations Manager',
        roleCategory: 'manager',
        seniority: 'manager',
        confidenceScore: 80,
        sourceType: 'public_search',
        roleStatus: 'current'
      }
    ];

    const company = { companyName: 'Starlight Boutique', employeeCount: '15' };
    const research = {
      detectedPainPoints: [{ title: 'AI Strategy', description: 'Looking to formulate AI roadmap' }],
      recommendedTksrServices: ['AI Strategy Consulting']
    };

    const { selectedDecisionMaker, decisionMakerStatus } = rankDecisionMakers(candidates, company, research);

    expect(selectedDecisionMaker).toBeDefined();
    expect(selectedDecisionMaker.name).toBe('David Kim');
    expect(selectedDecisionMaker.roleCategory).toBe('founder');
    expect(selectedDecisionMaker.isPrimaryDecisionMaker).toBe(true);
    expect(decisionMakerStatus).toBe('VERIFIED');
    expect(selectedDecisionMaker.selectionReason).toContain('leads executive strategy and vendor decisions');
  });

  // 3. Wrong-company executive rejected by validateCompanyMatch
  test('3. Rejects executive from an unrelated company with similar or generic name', () => {
    expect(validateCompanyMatch('Apex Systems Inc', 'Apex Systems', 'apexsystems.io')).toBe(true);
    expect(validateCompanyMatch('TCS Global Services', 'Tata Consultancy Services', 'tcs.com')).toBe(true);
    expect(validateCompanyMatch('Completely Unrelated Corp', 'Example Tech Solutions', 'exampletech.com')).toBe(false);
  });

  // 4. Outdated/historical executive penalized and not selected over current
  test('4. Penalizes former/historical executives so current executives take priority', () => {
    const candidates = [
      {
        name: 'Former Exec',
        title: 'Former CTO',
        designation: 'Former CTO',
        roleCategory: 'cto',
        seniority: 'executive',
        confidenceScore: 90,
        sourceType: 'public_search',
        roleStatus: 'historical'
      },
      {
        name: 'Current VP Eng',
        title: 'VP of Engineering',
        designation: 'VP of Engineering',
        roleCategory: 'head_of_technology',
        seniority: 'director',
        confidenceScore: 92,
        sourceType: 'official_team_page',
        roleStatus: 'current'
      }
    ];

    const company = { companyName: 'CloudScale', employeeCount: '200' };
    const research = { recommendedTksrServices: ['AI & Automation Workshops'] };

    const { selectedDecisionMaker } = rankDecisionMakers(candidates, company, research);

    expect(selectedDecisionMaker.name).toBe('Current VP Eng');
    expect(selectedDecisionMaker.roleStatus).toBe('current');
  });

  // 5. Unverified person marked NOT_VERIFIED
  test('5. Returns decisionMakerStatus = NOT_VERIFIED when no reliable candidate exists', () => {
    const { rankedCandidates, selectedDecisionMaker, decisionMakerStatus } = rankDecisionMakers([], { companyName: 'Empty Co' }, {});

    expect(rankedCandidates.length).toBe(0);
    expect(selectedDecisionMaker).toBeNull();
    expect(decisionMakerStatus).toBe('NOT_VERIFIED');
  });

  // 6. Blocked website uses fallback public research evidence
  test('6. Ingests fallback public research evidence when website crawl is blocked', async () => {
    const testCompany = await Company.create({
      companyName: 'Shielded Enterprise',
      website: 'https://test-dm-shielded.com',
      normalizedWebsite: 'test-dm-shielded.com',
      crawlStatus: 'blocked'
    });

    await CompanyResearch.create({
      companyId: testCompany._id,
      researchSource: 'public_sources',
      researchMethod: 'WEBSITE_BLOCKED_FALLBACK_USED',
      fallbackUsed: true,
      keyPersonnel: [
        {
          name: 'Elena Rostova',
          title: 'Chief Information Officer',
          role: 'CIO'
        }
      ],
      recommendedTksrServices: ['AI Governance and Responsible AI']
    });

    const contacts = await extractContactsFromWebsite(testCompany._id);

    const elena = contacts.find(c => c.name === 'Elena Rostova');
    expect(elena).toBeDefined();
    expect(elena.roleCategory).toBe('cio');
    expect(elena.isPrimaryDecisionMaker).toBe(true);
    expect(elena.sourceType).toBe('authoritative_record');
    expect(elena.evidence.personEvidence).toContain('Elena Rostova');
  });

  // 7. Public evidence is attached to the decision maker
  test('7. Attaches provenance and evidence citations to discovered decision makers', async () => {
    const testCompany = await Company.create({
      companyName: 'Apex Data Systems',
      website: 'https://test-dm-apexdata.com',
      normalizedWebsite: 'test-dm-apexdata.com',
      crawlStatus: 'completed'
    });

    await CrawledPage.create({
      companyId: testCompany._id,
      url: 'https://test-dm-apexdata.com/team',
      normalizedUrl: 'https://test-dm-apexdata.com/team',
      pageType: 'leadership',
      title: 'Our Team',
      content: 'Marcus Vance serves as Chief Data Officer leading enterprise data strategy.',
      crawlStatus: 'completed'
    });

    const contacts = await extractContactsFromWebsite(testCompany._id);
    const marcus = contacts.find(c => c.name === 'Marcus Vance');

    expect(marcus).toBeDefined();
    expect(['cdo', 'head_of_data']).toContain(marcus.roleCategory);
    expect(marcus.sourceUrl).toBe('https://test-dm-apexdata.com/team');
    expect(marcus.evidence.personEvidence).toBeDefined();
    expect(marcus.evidenceSources.length).toBeGreaterThan(0);
  });

  // 8. Critical Regression: Target OpenAI accepts Sam Altman (Employer: OpenAI)
  test('8. Accepts Sam Altman as CEO of OpenAI', () => {
    expect(validateCompanyMatch('OpenAI', 'OpenAI', 'openai.com')).toBe(true);
    expect(validateCompanyMatch('OpenAI Inc.', 'OpenAI', 'openai.com')).toBe(true);
    expect(validateCompanyMatch('OpenAI, Inc', 'OpenAI', 'openai.com')).toBe(true);
  });

  // 9. Critical Regression: Target OpenAI strictly rejects Angel Faus @ Clio
  test('9. Strictly rejects Angel Faus from Clio when target company is OpenAI', () => {
    expect(validateCompanyMatch('Clio', 'OpenAI', 'openai.com')).toBe(false);
  });

  // 10. Critical Regression: Target OpenAI strictly rejects Danny Wu @ Canva & BBVA
  test('10. Strictly rejects Danny Wu (Canva) and Daniel Ordaz (BBVA) when target is OpenAI', () => {
    expect(validateCompanyMatch('Canva', 'OpenAI', 'openai.com')).toBe(false);
    expect(validateCompanyMatch('BBVA Mexico', 'OpenAI', 'openai.com')).toBe(false);
    expect(validateCompanyMatch('Ramp', 'OpenAI', 'openai.com')).toBe(false);
    expect(validateCompanyMatch('Shopify', 'OpenAI', 'openai.com')).toBe(false);
  });

  // 11. Critical Regression: Non-person entities are rejected by cleanExecutive
  test('11. Rejects non-person entities like "Third Street", "San Francisco", and UI strings', () => {
    expect(cleanExecutive('Third Street', 'Executive', 'OpenAI')).toBeNull();
    expect(cleanExecutive('Fourth Street', 'Director', 'OpenAI')).toBeNull();
    expect(cleanExecutive('San Francisco', 'VP', 'OpenAI')).toBeNull();
    expect(cleanExecutive('Annual Report', 'CEO', 'OpenAI')).toBeNull();
    expect(cleanExecutive('Press Release', 'Officer', 'OpenAI')).toBeNull();
    expect(cleanExecutive('Terms of Service', 'Manager', 'OpenAI')).toBeNull();
    expect(cleanExecutive('Head of Product at BasisCursorQodoNotionCognitionRogoRampShopifyCiscoClio', 'Executive', 'OpenAI')).toBeNull();
  });

  // =========================================================================
  // NEW PHASE TESTS: COMPANY EMAIL FORMAT -> EMAIL GENERATION -> VERIFICATION
  // =========================================================================

  // Test 1 — Direct email: Public email found -> DIRECTLY_VERIFIED
  test('Test 1 — Direct email: Directly published public email is DIRECTLY_VERIFIED with DIRECT_SOURCE_MATCH', async () => {
    const result = await verifyEmailAddress('john.smith@company.com', true, false, 'John Smith', 'company.com');

    expect(result.isValidSyntax).toBe(true);
    expect(result.emailStatus).toBe('DIRECTLY_VERIFIED');
    expect(result.status).toBe('verified');
    expect(result.mailboxVerification).toBe('DIRECT_SOURCE_MATCH');
    expect(result.publicEmailEvidence).toBe('true');
  });

  // Test 2 — Pattern discovery: Known employees -> michael.brown@company.com, status PATTERN_BASED_UNVERIFIED
  test('Test 2 — Pattern discovery: Generates single primary candidate with PATTERN_BASED_UNVERIFIED based on known employees', async () => {
    const knownEmails = ['john.smith@company.com', 'sarah.jones@company.com'];
    const resolved = await resolveDecisionMakerEmail('Michael Brown', 'Company Corp', 'company.com', knownEmails);

    expect(resolved.email).toBe('michael.brown@company.com');
    expect(resolved.patternUsed).toBe('first.last');
    expect(resolved.emailStatus).toBe('PATTERN_BASED_UNVERIFIED');
    expect(resolved.status).toBe('pattern_derived');
    expect(resolved.verificationMethod).toBe('COMPANY_PATTERN');
    expect(resolved.isExactPublished).toBe(false);
  });

  // Test 3 — Pattern mailbox verified: Mailbox verification confirmed -> PATTERN_VERIFIED
  test('Test 3 — Pattern mailbox verified: Pattern email with confirmed mailbox receives PATTERN_VERIFIED', async () => {
    const result = await verifyEmailAddress('michael.brown@company.com', false, true, 'Michael Brown', 'company.com', { mailboxVerified: true });

    expect(result.isValidSyntax).toBe(true);
    expect(result.emailStatus).toBe('PATTERN_VERIFIED');
    expect(result.status).toBe('verified');
    expect(result.mailboxVerification).toBe('MAILBOX_VERIFIED');
  });

  // Test 4 — Pattern but mailbox unknown -> PATTERN_BASED_UNVERIFIED
  test('Test 4 — Pattern but mailbox unknown: Unconfirmed mailbox remains PATTERN_BASED_UNVERIFIED and NOT_INDEPENDENTLY_CONFIRMED', async () => {
    const result = await verifyEmailAddress('michael.brown@company.com', false, true, 'Michael Brown', 'company.com');

    expect(result.isValidSyntax).toBe(true);
    expect(result.emailStatus).toBe('PATTERN_BASED_UNVERIFIED');
    expect(result.status).toBe('pattern_derived');
    expect(result.mailboxVerification).toBe('NOT_INDEPENDENTLY_CONFIRMED');
    expect(result.publicEmailEvidence).toBe('false');
  });

  // Test 5 — Invalid mailbox: Verification rejected / invalid -> INVALID
  test('Test 5 — Invalid mailbox: Rejected mailbox is marked INVALID with status bounced', async () => {
    const result = await verifyEmailAddress('michael.brown@company.com', false, true, 'Michael Brown', 'company.com', { mailboxInvalid: true });

    expect(result.emailStatus).toBe('INVALID');
    expect(result.status).toBe('bounced');
    expect(result.mailboxVerification).toBe('MAILBOX_INVALID');
  });

  // Test 6 — Catch-all domain -> CATCH_ALL
  test('Test 6 — Catch-all: Catch-all domain marked CATCH_ALL and never claimed as verified mailbox', async () => {
    const result = await verifyEmailAddress('michael.brown@company.com', false, true, 'Michael Brown', 'company.com', { isCatchAll: true });

    expect(result.emailStatus).toBe('CATCH_ALL');
    expect(result.status).toBe('unverified');
    expect(result.mailboxVerification).toBe('CATCH_ALL');
    expect(result.statusReason).toContain('individual mailbox existence could not be conclusively confirmed');
  });

  // Test 7 — No pattern: Insufficient evidence -> NOT_FOUND
  test('Test 7 — No pattern: When no pattern evidence exists, returns emailStatus = NOT_FOUND', async () => {
    const patternInfo = await discoverCompanyEmailPattern(null, 'Obscure Company', 'obscurecompany.com', []);
    expect(patternInfo.pattern).toBeNull();
    expect(patternInfo.confidence).toBe(0);

    const resolved = await resolveDecisionMakerEmail('Alex Morgan', 'Obscure Company', 'obscurecompany.com', []);
    expect(resolved.email).toBe('');
    expect(resolved.emailStatus).toBe('NOT_FOUND');
    expect(resolved.status).toBe('not_found');
  });

  // Test 8 — Wrong-company email evidence: Foreign company emails rejected from pattern inference
  test('Test 8 — Wrong-company email evidence: Foreign company emails (e.g. Clio for OpenAI) are rejected and not used for pattern inference', async () => {
    const foreignEmails = ['angel.faus@clio.com', 'support@clio.com'];
    const patternInfo = await discoverCompanyEmailPattern(null, 'OpenAI', 'openai.com', foreignEmails);

    expect(patternInfo.examples.length).toBe(0);
    expect(patternInfo.pattern).toBeNull();

    const resolved = await resolveDecisionMakerEmail('Sam Altman', 'OpenAI', 'openai.com', foreignEmails);
    // Because no OpenAI pattern or personal email was found, no Clio pattern is used
    expect(resolved.email).toBe('');
    expect(resolved.emailStatus).toBe('NOT_FOUND');
  });

  // Test 9 — Wrong email domain: Discovers real corporate email domain from employee evidence
  test('Test 9 — Wrong email domain: Distinguishes corporate email domain (company.com) from website domain (company.io)', async () => {
    const employeeEmails = ['alice.smith@company.com', 'bob.jones@company.com'];
    const patternInfo = await discoverCompanyEmailPattern(null, 'Company', 'company.io', employeeEmails);

    expect(patternInfo.emailDomain).toBe('company.com');
    expect(patternInfo.pattern).toBe('first.last');

    const candidate = generateCandidateEmail('Michael Brown', patternInfo.pattern, patternInfo.emailDomain);
    expect(candidate).toBe('michael.brown@company.com');
  });

  // Test 10 — No fabrication: When no evidence exists, email = null and decision maker remains verified
  test('Test 10 — No fabrication: Decision maker remains verified even when email is NOT_FOUND with zero fabrication', async () => {
    const candidateEmail = generateCandidateEmail('John Smith', null, 'company.com');
    expect(candidateEmail).toBeNull();

    const result = await verifyEmailAddress('', false, false, 'John Smith', 'company.com');
    expect(result.emailStatus).toBe('NOT_FOUND');
    expect(result.status).toBe('not_found');
    expect(result.confidenceScore).toBe(0);

    // Decision maker ranking verification independent of email
    const candidate = {
      name: 'John Smith',
      title: 'Chief Technology Officer',
      designation: 'Chief Technology Officer',
      roleCategory: 'cto',
      seniority: 'executive',
      confidenceScore: 92,
      sourceType: 'official_team_page',
      roleStatus: 'current'
    };
    const { selectedDecisionMaker, decisionMakerStatus } = rankDecisionMakers([candidate], { companyName: 'Company' }, { recommendedTksrServices: ['AI Strategy'] });
    expect(selectedDecisionMaker).toBeDefined();
    expect(selectedDecisionMaker.name).toBe('John Smith');
    expect(decisionMakerStatus).toBe('VERIFIED');
  });

  // Test 11 — Google Search Provider unconfigured graceful handling
  test('Test 11 — Gracefully handles unconfigured Google Search API without crashing', async () => {
    const savedKey = process.env.GOOGLE_SEARCH_API_KEY;
    const savedCx = process.env.GOOGLE_SEARCH_ENGINE_ID;
    delete process.env.GOOGLE_SEARCH_API_KEY;
    delete process.env.GOOGLE_SEARCH_ENGINE_ID;

    const result = await executeGoogleSearch('OpenAI CEO');
    expect(result.configured).toBe(false);
    expect(result.error).toBe('SEARCH_PROVIDER_NOT_CONFIGURED');
    expect(result.results).toEqual([]);

    process.env.GOOGLE_SEARCH_API_KEY = savedKey;
    process.env.GOOGLE_SEARCH_ENGINE_ID = savedCx;
  });

  // Test 12 — discoverAndVerifyDecisionMakerEmail on verified direct leadership email
  test('Test 12 — discoverAndVerifyDecisionMakerEmail: Verified direct email returns VERIFIED profile', async () => {
    const person = { name: 'Alex Rivera', designation: 'Chief Technology Officer', roleStatus: 'current', candidateEmployer: 'Apex Systems' };
    const company = { companyName: 'Apex Systems', website: 'https://apexsystems.io', officialDomain: 'apexsystems.io', directEmails: ['alex.rivera@apexsystems.io'] };

    const result = await discoverAndVerifyDecisionMakerEmail(person, company);

    expect(result.person).toBe('Alex Rivera');
    expect(result.currentRole).toBe('Chief Technology Officer');
    expect(result.company).toBe('Apex Systems');
    expect(result.email).toBe('alex.rivera@apexsystems.io');
    expect(['VERIFIED', 'DIRECTLY_VERIFIED']).toContain(result.emailStatus);
    expect(result.emailConfidence).toBeGreaterThanOrEqual(90);
    expect(result.personMatch).toBe(true);
    expect(result.companyMatch).toBe(true);
    expect(result.currentRoleMatch).toBe(true);
  });

  // Test 13 — discoverAndVerifyDecisionMakerEmail on company pattern
  test('Test 13 — discoverAndVerifyDecisionMakerEmail: Pattern discovery returns PATTERN_VERIFIED profile when mailbox is verified', async () => {
    const person = { name: 'Michael Brown', designation: 'VP of Engineering', roleStatus: 'current', candidateEmployer: 'DataCorp' };
    const company = { companyName: 'DataCorp', website: 'https://datacorp.com', officialDomain: 'datacorp.com', directEmails: ['john.smith@datacorp.com', 'sarah.jones@datacorp.com'] };

    const result = await discoverAndVerifyDecisionMakerEmail(person, company, { mailboxVerified: true });

    expect(result.email).toBe('michael.brown@datacorp.com');
    expect(result.emailStatus).toBe('PATTERN_VERIFIED');
    expect(result.emailPattern).toBe('first.last');
    expect(result.patternEvidence).toContain('john.smith@datacorp.com');
    expect(result.corporateEmailDomain).toBe('datacorp.com');
  });

  // Test 14 — discoverAndVerifyDecisionMakerEmail rejects former executive
  test('Test 14 — discoverAndVerifyDecisionMakerEmail: Strictly rejects former executive with REJECTED status', async () => {
    const person = { name: 'Former Leader', designation: 'Former CTO', roleStatus: 'former', candidateEmployer: 'Apex Systems' };
    const company = { companyName: 'Apex Systems', website: 'https://apexsystems.io', officialDomain: 'apexsystems.io' };

    const result = await discoverAndVerifyDecisionMakerEmail(person, company);

    expect(result.email).toBeNull();
    expect(result.emailStatus).toBe('REJECTED');
    expect(result.currentRoleMatch).toBe(false);
    expect(result.verificationReason).toContain('Former executive rejected');
  });

  // Test 15 — discoverAndVerifyDecisionMakerEmail rejects wrong-company candidate
  test('Test 15 — discoverAndVerifyDecisionMakerEmail: Strictly rejects wrong-company employer', async () => {
    const person = { name: 'Angel Faus', designation: 'VP Product', roleStatus: 'current', candidateEmployer: 'Clio' };
    const company = { companyName: 'OpenAI', website: 'https://openai.com', officialDomain: 'openai.com' };

    const result = await discoverAndVerifyDecisionMakerEmail(person, company);

    expect(result.email).toBeNull();
    expect(result.emailStatus).toBe('REJECTED');
    expect(result.companyMatch).toBe(false);
  });
});
