const { generateFallbackResearch, generateFallbackOutreach, TKSR_SERVICES } = require('../aiService');
const { sendTestEmail } = require('../emailService');
const { categorizeRole, verifyEmailAddress, checkDomainMx } = require('../contactService');

describe('AI Outreach Pipeline & Decision Makers Intelligence', () => {
  const sampleCompany = {
    _id: '64a123456789012345678901',
    companyName: 'Acme Health Systems',
    website: 'https://acmehealth.com',
    industry: 'Healthcare Technology',
    country: 'United States',
    contactName: 'Jane Smith',
    contactEmail: 'jane.smith@acmehealth.com'
  };

  const samplePages = [
    {
      title: 'Acme Health - Modern EHR and Analytics Solutions',
      pageType: 'about',
      headings: [{ level: 1, text: 'Transforming Patient Care' }, { level: 2, text: 'Clinical Workflow Suite' }],
      content: 'Acme Health delivers intelligent data integration and patient management solutions for healthcare networks.'
    },
    {
      title: 'Our Products & Platform',
      pageType: 'products',
      headings: [{ level: 2, text: 'Analytics Cloud' }, { level: 2, text: 'Automated Billing' }],
      content: 'Empowering providers with fast claims processing and unified records.'
    }
  ];

  describe('Decision Makers Role Categorization & Email Intelligence', () => {
    test('accurately categorizes key executive leadership roles (CEO, COO, CFO, CTO, CIO, CDO, Managing Director, VP, Head of AI, Head of Data, etc.)', () => {
      expect(categorizeRole('Chief Executive Officer & Founder').roleCategory).toBe('ceo');
      expect(categorizeRole('Chief Operating Officer').roleCategory).toBe('coo');
      expect(categorizeRole('Chief Financial Officer').roleCategory).toBe('cfo');
      expect(categorizeRole('Chief Technology Officer').roleCategory).toBe('cto');
      expect(categorizeRole('Chief Information Officer').roleCategory).toBe('cio');
      expect(categorizeRole('Chief Digital Officer').roleCategory).toBe('cdo');
      expect(categorizeRole('Managing Director').roleCategory).toBe('managing_director');
      expect(categorizeRole('VP of Engineering').roleCategory).toBe('head_of_technology');
      expect(categorizeRole('Head of Sales').roleCategory).toBe('head_of_sales');
      expect(categorizeRole('President').roleCategory).toBe('president');
      expect(categorizeRole('Co-Founder').roleCategory).toBe('co_founder');
      expect(categorizeRole('Head of AI & Machine Learning').roleCategory).toBe('head_of_ai');
      expect(categorizeRole('Head of Data Strategy').roleCategory).toBe('head_of_data');
      expect(categorizeRole('Support Desk Channel').roleCategory).toBe('general');
    });

    test('strictly separates DIRECTLY_VERIFIED from PATTERN_BASED_UNVERIFIED and NOT_FOUND email verification', async () => {
      // 1. Exact published email test
      const exactVerified = await verifyEmailAddress('executive@acmehealth.com', true, false);
      expect(exactVerified.isValidSyntax).toBe(true);
      expect(['DIRECTLY_VERIFIED', 'EXACT_PUBLIC_SOURCE']).toContain(exactVerified.emailStatus);
      expect(exactVerified.status).toBe('verified');
      expect(exactVerified.confidenceScore).toBeGreaterThanOrEqual(90);

      // 2. Pattern derived email test
      const patternEmail = await verifyEmailAddress('john.smith@acmehealth.com', false, true);
      expect(patternEmail.isValidSyntax).toBe(true);
      expect(patternEmail.emailStatus).toBe('PATTERN_BASED_UNVERIFIED');
      expect(patternEmail.status).toBe('pattern_derived');

      // 3. Invalid syntax test
      const invalid = await verifyEmailAddress('invalid-email-string');
      expect(invalid.isValidSyntax).toBe(false);
      expect(['INVALID', 'NOT_FOUND']).toContain(invalid.emailStatus);
      expect(['bounced', 'not_found']).toContain(invalid.status);
    }, 15000);

    test('checks domain MX status without converting it to mailbox verification', async () => {
      const mx = await checkDomainMx('google.com');
      expect(mx.hasMxRecords).toBe(true);
      expect(mx.mxStatus).toBe('MX_ACTIVE');
    }, 10000);
  });

  describe('AI Company Research Synthesis', () => {
    test('synthesizes structured intelligence from crawled pages with TKSR recommendations', () => {
      const research = generateFallbackResearch(sampleCompany, samplePages);

      expect(research).toBeDefined();
      expect(research.summary).toContain('Acme Health Systems');
      expect(research.valueProposition).toBeDefined();
      expect(Array.isArray(research.coreOfferings)).toBe(true);
      expect(research.coreOfferings.length).toBeGreaterThan(0);
      expect(Array.isArray(research.detectedPainPoints)).toBe(true);
      expect(research.detectedPainPoints.length).toBe(3);
      expect(research.icpFitScore).toBeGreaterThanOrEqual(70);
      expect(Array.isArray(research.icebreakers)).toBe(true);
      expect(Array.isArray(research.recommendedTksrServices)).toBe(true);
      expect(research.recommendedTksrServices).toContain('AI Strategy Consulting');
    });
  });

  describe('Personalized 3-Step Outreach Generation with TKSR Services', () => {
    test('generates personalized multi-step sequence highlighting specific TKSR AI Services', () => {
      const research = generateFallbackResearch(sampleCompany, samplePages);
      const contact = { name: 'Jane Smith', email: 'jane.smith@acmehealth.com', title: 'VP of Operations', roleCategory: 'vp' };
      const senderProfile = {
        companyName: 'TKSR Product Services',
        senderName: 'Nagendra',
        senderTitle: 'Business Analyst',
        productDescription: 'Enterprise AI Strategy Consulting & Automation',
        targetPitch: 'a 10-minute demo'
      };

      const sequence = generateFallbackOutreach(
        sampleCompany,
        research,
        contact,
        senderProfile,
        'pain_point',
        'conversational',
        'AI Strategy Consulting'
      );

      expect(Array.isArray(sequence)).toBe(true);
      expect(sequence.length).toBe(3);

      // Step 1 check
      expect(sequence[0].step).toBe(1);
      expect(sequence[0].subject).toContain('Acme Health Systems');
      expect(sequence[0].bodyText).toContain('Jane');
      expect(sequence[0].bodyText).toContain('AI Strategy Consulting');
      expect(sequence[0].bodyHtml).toContain('TKSR Product Services');

      // Step 2 check
      expect(sequence[1].step).toBe(2);
      expect(sequence[1].bodyText).toContain('Jane');
      expect(sequence[1].bodyText).toContain('AI Strategy Consulting');

      // Step 3 check
      expect(sequence[2].step).toBe(3);
      expect(sequence[2].subject).toContain('Acme Health Systems');
      expect(sequence[2].bodyText).toContain('Jane');
      expect(sequence[2].bodyText).toContain('AI Strategy Consulting');
    });
  });

  describe('Email Sandbox Dispatch', () => {
    test('generates test email via Ethereal sandbox with valid messageId', async () => {
      const result = await sendTestEmail(null, 'test-prospect@example.com');

      expect(result.success).toBe(true);
      expect(result.messageId).toBeDefined();
      expect(result.isTest).toBe(true);
      expect(result.previewUrl).toBeDefined();
    }, 20000);
  });
});
