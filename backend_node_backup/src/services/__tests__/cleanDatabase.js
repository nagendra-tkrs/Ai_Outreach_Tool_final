require('dotenv').config({ path: 'c:/Users/LENOVO/Desktop/new/ai-client-outreach-live/backend/.env' });
const mongoose = require('mongoose');
const Company = require('../../models/Company');
const Contact = require('../../models/Contact');
const CrawledPage = require('../../models/CrawledPage');
const CompanyResearch = require('../../models/CompanyResearch');
const OutreachMessage = require('../../models/OutreachMessage');

const ResearchJob = require('../../models/ResearchJob');

async function cleanDatabase() {
  const uri = process.env.MONGODB_URI || 'mongodb://127.0.0.1:27017/ai_client_outreach';
  await mongoose.connect(uri);
  console.log(`Connected to MongoDB: ${uri}`);

  const companies = await Company.find({});
  console.log(`Current companies in DB (${companies.length}):`, companies.map(c => c.companyName));

  // Delete all companies, contacts, crawled pages, research, and outreach
  await Company.deleteMany({});
  await Contact.deleteMany({});
  await CrawledPage.deleteMany({});
  await CompanyResearch.deleteMany({});
  await OutreachMessage.deleteMany({});
  await ResearchJob.deleteMany({});

  console.log('Successfully cleaned all companies and related data from the database.');

  await mongoose.disconnect();
}

cleanDatabase().catch(console.error);
