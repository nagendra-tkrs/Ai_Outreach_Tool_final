require('dotenv').config({ path: 'c:/Users/LENOVO/Desktop/new/ai-client-outreach-live/backend/.env' });
const mongoose = require('mongoose');
const Company = require('../../models/Company');
const Contact = require('../../models/Contact');
const CompanyResearch = require('../../models/CompanyResearch');
const OutreachMessage = require('../../models/OutreachMessage');
const { extractContactsFromWebsite } = require('../contactService');
const { generateOutreachSequence } = require('../outreachService');

async function testFlow() {
  const uri = process.env.MONGODB_URI || 'mongodb://127.0.0.1:27017/ai_client_outreach';
  await mongoose.connect(uri);
  console.log('Connected to MongoDB');

  // Test with Stripe
  console.log('\n--- 1. Testing with Stripe ---');
  let stripeCompany = await Company.findOne({ companyName: 'Stripe' });
  if (!stripeCompany) {
    stripeCompany = await Company.create({
      companyName: 'Stripe',
      website: 'https://stripe.com',
      industry: 'Fintech / Payments',
      country: 'United States'
    });
  }

  console.log('Extracting contacts for Stripe...');
  const contacts = await extractContactsFromWebsite(stripeCompany._id);
  console.log(`Discovered ${contacts.length} contacts for Stripe:`);
  for (const c of contacts) {
    console.log(`- ${c.name} (${c.designation}): ${c.email || 'No email'} [Status: ${c.emailStatus}, Conf: ${c.confidenceScore}%]`);
  }

  const topDecisionMaker = contacts.find(c => c.roleCategory !== 'general') || contacts[0];
  console.log(`\nSelected top decision maker: ${topDecisionMaker?.name} (${topDecisionMaker?.email})`);

  console.log('\nGenerating outreach sequence for Stripe...');
  const sequence = await generateOutreachSequence(stripeCompany._id, {
    contactId: topDecisionMaker?._id,
    angle: 'pain_point',
    tone: 'conversational',
    focusService: 'AI Strategy Consulting'
  });

  console.log(`Generated ${sequence.length} outreach steps:`);
  for (const s of sequence) {
    console.log(`\nStep ${s.step}: ${s.subject}`);
    console.log(`Recipient: ${s.recipientName} <${s.recipientEmail}>`);
    console.log(`Body:\n${s.bodyText.slice(0, 180)}...`);
  }

  // Clean up test data
  await Company.findByIdAndDelete(stripeCompany._id);
  await Contact.deleteMany({ companyId: stripeCompany._id });
  await CompanyResearch.deleteMany({ companyId: stripeCompany._id });
  await OutreachMessage.deleteMany({ companyId: stripeCompany._id });

  console.log('\n--- Test flow completed successfully! ---');
  await mongoose.disconnect();
}

testFlow().catch(console.error);
