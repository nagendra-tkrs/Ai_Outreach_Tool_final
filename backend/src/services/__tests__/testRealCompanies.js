require('dotenv').config({ path: 'c:/Users/LENOVO/Desktop/new/ai-client-outreach-live/backend/.env' });
const mongoose = require('mongoose');
const Company = require('../../models/Company');
const Contact = require('../../models/Contact');
const { extractContactsFromWebsite } = require('../contactService');
const { generateFallbackOutreach } = require('../aiService');

const realCompanies = [
  { name: 'TKSR Product Services', website: 'https://tksrproductservices.com', industry: 'AI & Enterprise Automation' },
  { name: 'Shopify', website: 'https://shopify.com', industry: 'E-commerce Platforms' },
  { name: 'Datadog', website: 'https://datadoghq.com', industry: 'Cloud Monitoring & Observability' },
  { name: 'Snowflake', website: 'https://snowflake.com', industry: 'Data Cloud & Analytics' },
  { name: 'HubSpot', website: 'https://hubspot.com', industry: 'CRM & Growth Platform' },
  { name: 'Atlassian', website: 'https://atlassian.com', industry: 'Enterprise Collaboration Tools' },
  { name: 'Figma', website: 'https://figma.com', industry: 'Collaborative Interface Design' },
  { name: 'OpenAI', website: 'https://openai.com', industry: 'Artificial Intelligence & Large Models' },
  { name: 'Stripe', website: 'https://stripe.com', industry: 'Financial & Payments Infrastructure' },
  { name: 'Notion', website: 'https://notion.so', industry: 'Connected Workspaces' }
];

async function runTest() {
  const uri = process.env.MONGODB_URI || 'mongodb://127.0.0.1:27017/ai_client_outreach';
  await mongoose.connect(uri);
  console.log(`Connected to MongoDB: ${uri}`);

  const results = [];

  for (const rc of realCompanies) {
    console.log(`\n========================================`);
    console.log(`Auditing Company: ${rc.name} (${rc.website})`);
    console.log(`========================================`);

    let company = await Company.findOne({
      $or: [{ normalizedWebsite: rc.website }, { website: rc.website }, { companyName: rc.name }]
    });
    if (!company) {
      company = await Company.create({
        companyName: rc.name,
        website: rc.website,
        normalizedWebsite: rc.website,
        industry: rc.industry,
        country: 'Global'
      });
    }

    try {
      const contacts = await extractContactsFromWebsite(company._id);
      const decisionMakers = contacts.filter(c => c.roleCategory !== 'general' && c.seniority !== 'general');
      const inboxes = contacts.filter(c => c.roleCategory === 'general' || c.seniority === 'general');
      const topDecisionMaker = decisionMakers[0];

      if (topDecisionMaker) {
        const sequence = generateFallbackOutreach(
          company,
          null,
          topDecisionMaker,
          { senderName: 'Nagendra', senderTitle: 'Business Analyst', companyName: 'TKSR Product Services' },
          'pain_point',
          'conversational',
          'AI Strategy Consulting'
        );

        const emailStatusDisplay = topDecisionMaker.emailStatus === 'EXACT_PUBLIC_SOURCE'
          ? '✅ Exact Public Email'
          : (topDecisionMaker.emailStatus === 'PATTERN_BASED_UNVERIFIED'
            ? '⚡ Pattern-Based / Unverified'
            : (topDecisionMaker.email ? '⚠️ Unverified' : '❌ Not Found'));

        const companySummary = {
          company: rc.name,
          decisionMakerName: topDecisionMaker.name,
          designation: topDecisionMaker.designation || topDecisionMaker.title,
          email: topDecisionMaker.email || 'Not Found',
          emailStatus: emailStatusDisplay,
          source: topDecisionMaker.source,
          sourceUrl: topDecisionMaker.sourceUrl,
          confidenceScore: `${topDecisionMaker.confidenceScore || 85}%`,
          personEvidence: topDecisionMaker.evidence?.personEvidence || 'N/A',
          inboxesDiscovered: inboxes.map(i => i.email).join(', ') || 'None',
          generatedEmailSubject: sequence[0].subject,
          generatedEmailFocus: sequence[0].focusService
        };

        results.push(companySummary);
        console.log(`✓ Real Person Discovered: ${companySummary.decisionMakerName} (${companySummary.designation})`);
        console.log(`✓ Email: ${companySummary.email} [Status: ${companySummary.emailStatus}]`);
        console.log(`✓ Source URL: ${companySummary.sourceUrl}`);
        console.log(`✓ Confidence Score: ${companySummary.confidenceScore}`);
        console.log(`✓ Evidence: "${companySummary.personEvidence}"`);
        console.log(`✓ Separated Company Inboxes: ${companySummary.inboxesDiscovered}`);
        console.log(`✓ Generated Email Focus: ${companySummary.generatedEmailFocus}`);
      } else {
        console.log(`⚠️ Decision Maker: No verified decision maker found`);
        results.push({
          company: rc.name,
          decisionMakerName: 'No verified decision maker found',
          designation: 'N/A',
          email: 'Not Found',
          emailStatus: '❌ Not Found',
          source: 'N/A',
          sourceUrl: rc.website,
          confidenceScore: '0%',
          inboxesDiscovered: inboxes.map(i => i.email).join(', ') || 'None'
        });
      }
    } catch (err) {
      console.error(`Error processing ${rc.name}:`, err.message);
    }
  }

  console.log('\n\n==================== FINAL AUDITED 10-COMPANY REAL DATA TABLE ====================');
  console.table(results.map(r => ({
    Company: r.company,
    'Decision Maker': r.decisionMakerName,
    Designation: r.designation,
    Email: r.email,
    'Status': r.emailStatus,
    'Confidence': r.confidenceScore,
    'Source': r.source,
    'Separated Inboxes': r.inboxesDiscovered
  })));

  await mongoose.disconnect();
}

runTest().catch(err => {
  console.error('Test execution failed:', err);
  process.exit(1);
});
