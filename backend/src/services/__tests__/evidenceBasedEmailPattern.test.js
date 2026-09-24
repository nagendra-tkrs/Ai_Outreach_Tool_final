const dns = require('dns').promises;
const mongoose = require('mongoose');
const {
  matchEmailToNamePattern,
  discoverCompanyEmailPattern,
  generateCandidateEmail,
  resolveDecisionMakerEmail,
  discoverAndVerifyDecisionMakerEmail,
  verifyEmailAddress,
  validateCompanyMatch
} = require('../contactService');
const { cleanExecutive, extractEmployeeFromText } = require('../webSearchService');

describe('Evidence-Based Decision Maker Email Pattern & Verification Pipeline', () => {
  let dnsSpy;

  beforeAll(async () => {
    const testUri = process.env.MONGODB_TEST_URI || 'mongodb://127.0.0.1:27017/ai_client_outreach_test';
    if (mongoose.connection.readyState === 0) {
      await mongoose.connect(testUri);
    }
  });

  beforeEach(() => {
    dnsSpy = jest.spyOn(dns, 'resolveMx').mockResolvedValue([{ exchange: 'mail.test.com' }]);
  });

  afterEach(() => {
    if (dnsSpy) dnsSpy.mockRestore();
  });

  afterAll(async () => {
    if (dnsSpy) dnsSpy.mockRestore();
    await mongoose.disconnect();
  });

  // Case 1: Direct public email -> DIRECTLY_VERIFIED
  test('1. Direct public email found -> DIRECTLY_VERIFIED', async () => {
    const verified = await verifyEmailAddress('sarah.connor@patterntech.com', true, false, 'Sarah Connor', 'patterntech.com');
    expect(verified.emailStatus).toBe('DIRECTLY_VERIFIED');
    expect(verified.mailboxVerification).toBe('DIRECT_SOURCE_MATCH');
    expect(verified.publicEmailEvidence).toBe('true');
    expect(verified.confidenceScore).toBeGreaterThanOrEqual(90);
  });

  // Case 2: One employee email -> low confidence
  test('2. One employee email -> detects pattern with low confidence', async () => {
    const directEmails = ['fserra@garwarefibres.com'];
    const patternInfo = await discoverCompanyEmailPattern(null, 'Garware Technical Fibres', 'garwarefibres.com', directEmails);

    expect(patternInfo.pattern).toBe('flast');
    expect(patternInfo.emailDomain).toBe('garwarefibres.com');
    expect(patternInfo.patternConfidence).toBe('low');
    expect(patternInfo.confidence).toBe(72);
  });

  // Case 3: Multiple employee emails -> high confidence
  test('3. Multiple employee emails -> detects pattern with high confidence', async () => {
    const directEmails = [
      'fserra@garwarefibres.com',
      'rsharma@garwarefibres.com',
      'mfernandes@garwarefibres.com'
    ];
    const patternInfo = await discoverCompanyEmailPattern(null, 'Garware Technical Fibres', 'garwarefibres.com', directEmails);

    expect(patternInfo.pattern).toBe('flast');
    expect(patternInfo.patternConfidence).toBe('high');
    expect(patternInfo.confidence).toBe(96);
    expect(patternInfo.examples.length).toBe(3);
  });

  // Case 4: firstInitial + lastName pattern (Garware Technical Fibres example)
  test('4. firstInitial + lastName pattern: Shujaul Rehman -> srehman@garwarefibres.com', async () => {
    // Verify name-email pattern extraction
    const detected = matchEmailToNamePattern('fserra', 'Francisco', 'Serra');
    expect(detected).toBe('flast');

    const generated = generateCandidateEmail('Shujaul Rehman', 'flast', 'garwarefibres.com');
    expect(generated).toBe('srehman@garwarefibres.com');
  });

  // Case 5: first.last pattern
  test('5. first.last pattern: John Smith -> john.smith@company.com', () => {
    const detected = matchEmailToNamePattern('john.smith', 'John', 'Smith');
    expect(detected).toBe('first.last');

    const generated = generateCandidateEmail('David Kim', 'first.last', 'company.com');
    expect(generated).toBe('david.kim@company.com');
  });

  // Case 6: firstlast pattern
  test('6. firstlast pattern: Jane Doe -> janedoe@company.com', () => {
    const detected = matchEmailToNamePattern('janedoe', 'Jane', 'Doe');
    expect(detected).toBe('firstlast');

    const generated = generateCandidateEmail('Alex Rivera', 'firstlast', 'company.com');
    expect(generated).toBe('alexrivera@company.com');
  });

  // Case 7: Corporate domain different from website domain
  test('7. Corporate domain different from website domain (example.io -> example.com)', async () => {
    const employeeEmails = [
      'john.smith@example.com',
      'sarah.jones@example.com',
      'mike.brown@example.com'
    ];
    const patternInfo = await discoverCompanyEmailPattern(null, 'Example Tech', 'example.io', employeeEmails);

    expect(patternInfo.emailDomain).toBe('example.com');
    expect(patternInfo.pattern).toBe('first.last');

    const candidate = generateCandidateEmail('Alice Williams', patternInfo.pattern, patternInfo.emailDomain);
    expect(candidate).toBe('alice.williams@example.com');
  });

  // Case 8: Foreign-company email rejection
  test('8. Foreign-company email rejection (Clio for OpenAI)', async () => {
    const foreignEmails = ['angel.faus@clio.com', 'support@clio.com'];
    const patternInfo = await discoverCompanyEmailPattern(null, 'OpenAI', 'openai.com', foreignEmails);

    expect(patternInfo.examples.length).toBe(0);
    expect(patternInfo.pattern).toBeNull();
    expect(patternInfo.confidence).toBe(0);
  });

  // Case 9: Generic inbox rejection
  test('9. Generic inbox rejection (info@, sales@, support@, privacy@)', async () => {
    const inboxes = ['info@company.com', 'sales@company.com', 'support@company.com', 'privacy@company.com'];
    const patternInfo = await discoverCompanyEmailPattern(null, 'Target Co', 'company.com', inboxes);

    expect(patternInfo.examples.length).toBe(0);
    expect(patternInfo.pattern).toBeNull();
  });

  // Case 10: Former employee rejection
  test('10. Former employee rejection from email discovery', async () => {
    const person = { name: 'Former CTO', designation: 'Former CTO', roleStatus: 'former', candidateEmployer: 'Target Co' };
    const company = { companyName: 'Target Co', website: 'https://targetco.com', officialDomain: 'targetco.com' };

    const result = await discoverAndVerifyDecisionMakerEmail(person, company);
    expect(result.email).toBeNull();
    expect(result.emailStatus).toBe('REJECTED');
    expect(result.currentRoleMatch).toBe(false);
  });

  // Case 11: Catch-all domain
  test('11. Catch-all domain marked CATCH_ALL', async () => {
    const result = await verifyEmailAddress('srehman@garwarefibres.com', false, true, 'Shujaul Rehman', 'garwarefibres.com', { isCatchAll: true });

    expect(result.emailStatus).toBe('CATCH_ALL');
    expect(result.mailboxVerification).toBe('CATCH_ALL');
    expect(result.status).toBe('unverified');
  });

  // Case 12: MX active but mailbox unconfirmed
  test('12. MX active but mailbox unconfirmed remains PATTERN_BASED_UNVERIFIED', async () => {
    const result = await verifyEmailAddress('srehman@garwarefibres.com', false, true, 'Shujaul Rehman', 'garwarefibres.com');

    expect(result.hasMxRecords).toBe(true);
    expect(result.mxStatus).toBe('MX_ACTIVE');
    expect(result.emailStatus).toBe('PATTERN_BASED_UNVERIFIED');
    expect(result.mailboxVerification).toBe('NOT_INDEPENDENTLY_CONFIRMED');
  });

  // Case 13: Pattern verified mailbox
  test('13. Pattern verified mailbox receives PATTERN_VERIFIED', async () => {
    const result = await verifyEmailAddress('srehman@garwarefibres.com', false, true, 'Shujaul Rehman', 'garwarefibres.com', { mailboxVerified: true });

    expect(result.emailStatus).toBe('PATTERN_VERIFIED');
    expect(result.mailboxVerification).toBe('MAILBOX_VERIFIED');
    expect(result.status).toBe('verified');
  });

  // Case 14: Pattern unverified mailbox
  test('14. Pattern unverified mailbox remains PATTERN_BASED_UNVERIFIED', async () => {
    const result = await verifyEmailAddress('srehman@garwarefibres.com', false, true, 'Shujaul Rehman', 'garwarefibres.com', { mailboxVerified: false });

    expect(result.emailStatus).toBe('PATTERN_BASED_UNVERIFIED');
    expect(result.mailboxVerification).toBe('NOT_INDEPENDENTLY_CONFIRMED');
  });

  // Case 15: No evidence -> NOT_FOUND with zero fabrication
  test('15. No evidence -> returns NOT_FOUND with zero fabrication', async () => {
    const patternInfo = await discoverCompanyEmailPattern(null, 'Silent Enterprise', 'silententerprise.com', []);
    expect(patternInfo.pattern).toBeNull();
    expect(patternInfo.confidence).toBe(0);

    const person = { name: 'Anonymous Leader', designation: 'CEO', roleStatus: 'current', candidateEmployer: 'Silent Enterprise' };
    const company = { companyName: 'Silent Enterprise', website: 'https://silententerprise.com', officialDomain: 'silententerprise.com' };

    const result = await discoverAndVerifyDecisionMakerEmail(person, company);
    expect(result.email).toBeNull();
    expect(result.emailStatus).toBe('NOT_FOUND');
    expect(result.emailConfidence).toBe(0);
  });

  // Case 16: Search disabled -> SEARCH_PROVIDER_NOT_CONFIGURED diagnostic
  test('16. DuckDuckGo is configured by default (no creds needed); disabling it exposes SEARCH_PROVIDER_NOT_CONFIGURED', async () => {
    const savedProvider = process.env.SEARCH_PROVIDER;
    const savedEnabled = process.env.ENABLE_PUBLIC_WEB_SEARCH;
    const originalFetch = global.fetch;
    process.env.ENABLE_PUBLIC_WEB_SEARCH = 'true';
    // Mock search to avoid any real network call.
    global.fetch = jest.fn(async () => ({
      ok: true,
      status: 200,
      text: async () => ''
    }));

    const person = { name: 'Unknown Exec', designation: 'CEO', roleStatus: 'current', candidateEmployer: 'Unconfigured Co' };
    const company = { companyName: 'Unconfigured Co', website: 'https://unconfigured.com', officialDomain: 'unconfigured.com' };

    // DuckDuckGo needs no API keys - search is configured by default.
    const configuredResult = await discoverAndVerifyDecisionMakerEmail(person, company);
    expect(configuredResult.searchConfigured).toBe(true);

    // Disabling search yields the controlled diagnostic, never a guess.
    process.env.SEARCH_PROVIDER = 'none';
    const disabledResult = await discoverAndVerifyDecisionMakerEmail(person, company);
    expect(disabledResult.emailStatus).toBe('NOT_FOUND');
    expect(disabledResult.searchConfigured).toBe(false);
    expect(disabledResult.searchProvider).toBe('none');
    expect(disabledResult.reason).toBe('SEARCH_PROVIDER_NOT_CONFIGURED');

    if (savedProvider === undefined) delete process.env.SEARCH_PROVIDER;
    else process.env.SEARCH_PROVIDER = savedProvider;
    if (savedEnabled === undefined) delete process.env.ENABLE_PUBLIC_WEB_SEARCH;
    else process.env.ENABLE_PUBLIC_WEB_SEARCH = savedEnabled;
    global.fetch = originalFetch;
  });

  // Case 17: Generated email publicly verified -> upgraded to DIRECTLY_VERIFIED
  test('17. Generated email publicly matched -> upgraded to DIRECTLY_VERIFIED', async () => {
    process.env.ENABLE_PUBLIC_WEB_SEARCH = 'true';

    const originalFetch = global.fetch;
    global.fetch = jest.fn().mockImplementation(async (url) => {
      const urlStr = url.toString().toLowerCase();

      // Only DuckDuckGo HTML is ever called by the free provider.
      if (!urlStr.includes('html.duckduckgo.com')) {
        return { ok: false, status: 404, text: async () => 'Not found' };
      }

      // Direct personal email queries for the person return no match.
      if (urlStr.includes('shujaul')) {
        return {
          ok: true,
          status: 200,
          text: async () => `<html><body></body></html>`
        };
      }

      // Generated candidate email search returns public confirmation.
      if (urlStr.includes('srehman')) {
        return {
          ok: true,
          status: 200,
          text: async () => `
            <div class="result results_links results_links_deep web_result result__body">
              <h2 class="result__title">
                <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fgarwarefibres.com%2Fteam">Garware Technical Fibres - Executive Directory</a>
              </h2>
              <a class="result__snippet">Contact CEO Shujaul Rehman directly at srehman@garwarefibres.com for investor inquiries.</a>
            </div></div></div>
          `
        };
      }

      // Company employee search returns employee evidence for pattern discovery.
      return {
        ok: true,
        status: 200,
        text: async () => `
          <div class="result results_links results_links_deep web_result result__body">
            <h2 class="result__title">
              <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fgarwarefibres.com%2Fteam">Garware Technical Fibres - Leadership &amp; Contacts</a>
            </h2>
            <a class="result__snippet">Francisco Serra (fserra@garwarefibres.com), VP of Business Development at Garware Technical Fibres.</a>
          </div></div></div>
        `
      };
    });

    const person = { name: 'Shujaul Rehman', designation: 'CEO', roleStatus: 'current', candidateEmployer: 'Garware Technical Fibres' };
    const company = { companyName: 'Garware Technical Fibres', website: 'https://garwarefibres.com', officialDomain: 'garwarefibres.com' };

    const result = await discoverAndVerifyDecisionMakerEmail(person, company);
    expect(result.email).toBe('srehman@garwarefibres.com');
    expect(result.emailStatus).toBe('DIRECTLY_VERIFIED');
    expect(result.emailPattern).toBe('flast');

    global.fetch = originalFetch;
    delete process.env.ENABLE_PUBLIC_WEB_SEARCH;
  });

  // Helper test: extractEmployeeFromText
  test('Helper: extractEmployeeFromText extracts person name associated with email in snippet', () => {
    const text = 'For sales inquiries, contact Francisco Serra (fserra@garwarefibres.com), VP Business Development at Garware Technical Fibres.';
    const extracted = extractEmployeeFromText('fserra@garwarefibres.com', text, 'Garware Technical Fibres', 'garwarefibres.com');

    expect(extracted).toBeDefined();
    expect(extracted.personName).toBe('Francisco Serra');
    expect(extracted.firstName).toBe('Francisco');
    expect(extracted.lastName).toBe('Serra');
  });
});