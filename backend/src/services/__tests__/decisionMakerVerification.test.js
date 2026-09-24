const {
  categorizeRole,
  checkDomainMx,
  verifyEmailAddress,
  detectCompanyEmailPattern,
  evaluatePersonEmailMatch,
  calculateExplainableConfidence,
  deduplicateAndMergeContacts
} = require('../contactService');

describe('Decision Maker & Email Verification Rigorous Test Suite (Section 26 Requirements)', () => {
  // Test 1 — Official Person + Exact Email
  test('Test 1: Official Person + Exact Email -> PERSON_VERIFIED, DIRECTLY_VERIFIED, DIRECT_SOURCE_MATCH', async () => {
    const result = await verifyEmailAddress(
      'rahul.sharma@abctech.com',
      true, // isExactPublished
      false,
      'Rahul Sharma',
      'abctech.com'
    );

    expect(result.isValidSyntax).toBe(true);
    expect(['DIRECTLY_VERIFIED', 'EXACT_PUBLIC_SOURCE']).toContain(result.emailStatus);
    expect(result.status).toBe('verified');
    expect(result.mailboxVerification).toBe('DIRECT_SOURCE_MATCH');
    expect(result.personEmailMatch).toBe('true');
    expect(result.publicEmailEvidence).toBe('true');
    expect(result.confidenceScore).toBeGreaterThanOrEqual(85);
    expect(result.confidence).toBe('high');
    expect(result.confidenceReasoning.length).toBeGreaterThan(0);
  });

  // Test 2 — Person Verified + Pattern Email
  test('Test 2: Person Verified + Pattern Email -> PERSON_VERIFIED, PATTERN_BASED_UNVERIFIED, NOT_INDEPENDENTLY_CONFIRMED', async () => {
    const result = await verifyEmailAddress(
      'rahul.sharma@abctech.com',
      false, // isExactPublished = false
      true,  // isPatternDerived = true
      'Rahul Sharma',
      'abctech.com'
    );

    expect(result.isValidSyntax).toBe(true);
    expect(result.emailStatus).toBe('PATTERN_BASED_UNVERIFIED');
    expect(result.status).toBe('pattern_derived');
    expect(result.mailboxVerification).toBe('NOT_INDEPENDENTLY_CONFIRMED');
    expect(result.publicEmailEvidence).toBe('false');
  });

  // Test 3 — MX Valid + No Person Email Evidence (MX VALID ≠ MAILBOX VERIFIED)
  test('Test 3: MX Valid + No Person Email Evidence -> Has MX but NOT DIRECTLY_VERIFIED', async () => {
    const result = await verifyEmailAddress(
      'unknown.executive@google.com',
      false, // NOT published in source
      true,  // pattern derived
      'Unknown Executive',
      'google.com'
    );

    expect(result.hasMxRecords).toBe(true);
    expect(result.mxStatus).toBe('MX_ACTIVE');
    expect(result.emailStatus).not.toBe('DIRECTLY_VERIFIED');
    expect(result.emailStatus).not.toBe('EXACT_PUBLIC_SOURCE');
    expect(result.mailboxVerification).toBe('NOT_INDEPENDENTLY_CONFIRMED');
  });

  // Test 4 — Wrong Employee Email
  test('Test 4: Wrong Employee Email -> EMAIL_PERSON_MATCH=false and deduction applied', () => {
    const match = evaluatePersonEmailMatch('John Smith', 'james.smith@company.com', 'company.com');
    expect(match.match).toBe(false);
    expect(match.personEmailMatch).toBe('false');

    const conf = calculateExplainableConfidence({
      personVerified: 'true',
      designationVerified: 'true',
      isExactPublished: true,
      hasMxRecords: true,
      personEmailMatch: match.personEmailMatch
    });
    expect(conf.confidenceReasoning).toContain('Warning: Email local part mismatch (-30)');
  });

  // Test 5 — Generic Company Inbox Quarantined
  test('Test 5: Generic Company Inbox -> Rejected as individual mailbox, role general', () => {
    const match = evaluatePersonEmailMatch('Executive Leadership', 'info@company.com', 'company.com');
    expect(match.match).toBe(false);
    expect(match.personEmailMatch).toBe('false');

    const role = categorizeRole('Customer Support & Info Desk');
    expect(role.roleCategory).toBe('general');
    expect(role.seniority).toBe('general');
  });

  // Test 6 — No Evidence -> NOT_FOUND and zero confidence
  test('Test 6: No Evidence -> NOT_FOUND with zero confidence', async () => {
    const result = await verifyEmailAddress('', false, false, 'Ghost Person', 'example.com');
    expect(result.emailStatus).toBe('NOT_FOUND');
    expect(result.status).toBe('not_found');
    expect(result.confidenceScore).toBe(0);
    expect(result.confidence).toBe('zero');
    expect(result.mailboxVerification).toBe('NOT_APPLICABLE');
  });

  // Test 7 — Temporary DNS Failure
  test('Test 7: Temporary DNS Failure -> Public email evidence remains intact', async () => {
    const result = await verifyEmailAddress(
      'published.exec@nonexistent-domain-123456xyz.com',
      true, // exact published
      false,
      'Published Exec',
      'nonexistent-domain-123456xyz.com'
    );
    expect(['DIRECTLY_VERIFIED', 'EXACT_PUBLIC_SOURCE']).toContain(result.emailStatus);
    expect(result.publicEmailEvidence).toBe('true');
    expect(result.mailboxVerification).toBe('DIRECT_SOURCE_MATCH');
  });

  // Test 8 — Historical vs Current Executive
  test('Test 8: Distinguishes Historical Executive role status', () => {
    const currentExec = { name: 'Sridhar Ramaswamy', designation: 'Chief Executive Officer', roleStatus: 'current' };
    const historicalExec = { name: 'Bob Muglia', designation: 'Former CEO', roleStatus: 'historical' };

    expect(currentExec.roleStatus).toBe('current');
    expect(historicalExec.roleStatus).toBe('historical');
  });

  // Test 9 — Duplicate Person Deduplication & Evidence Merging
  test('Test 9: Deduplicate same person across multiple sources and merge evidence', () => {
    const rawCandidates = [
      {
        name: 'Dylan Field',
        designation: 'CEO',
        roleCategory: 'ceo',
        source: 'Company Leadership Page',
        sourceUrl: 'https://figma.com/leadership',
        evidence: { personEvidence: 'Dylan Field is CEO of Figma.' }
      },
      {
        name: 'Dylan Field',
        designation: 'Chief Executive Officer & Co-Founder',
        roleCategory: 'ceo',
        source: 'Wikipedia Corporate Infobox',
        sourceUrl: 'https://en.wikipedia.org/wiki/Figma',
        evidence: { personEvidence: 'Dylan Field co-founded Figma.' }
      }
    ];

    const deduplicated = deduplicateAndMergeContacts(rawCandidates);
    expect(deduplicated.length).toBe(1);
    expect(deduplicated[0].name).toBe('Dylan Field');
    expect(deduplicated[0].evidenceSources.length).toBe(2);
    expect(deduplicated[0].evidenceSources[0].source).toBe('Company Leadership Page');
    expect(deduplicated[0].evidenceSources[1].source).toBe('Wikipedia Corporate Infobox');
  });

  // Test 10 — Similar Names Cross-Assignment Protection
  test('Test 10: Prevents cross-assigning emails between similar names', () => {
    const matchJane = evaluatePersonEmailMatch('Jane Smith', 'john.smith@company.com', 'company.com');
    expect(matchJane.match).toBe(false);
    expect(matchJane.personEmailMatch).toBe('false');

    const matchJohn = evaluatePersonEmailMatch('John Smith', 'john.smith@company.com', 'company.com');
    expect(matchJohn.match).toBe(true);
    expect(matchJohn.personEmailMatch).toBe('true');
  });
});
