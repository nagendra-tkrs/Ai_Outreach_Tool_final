const mongoose = require('mongoose');
require('dotenv').config();

const clearAllData = async () => {
  try {
    const uri = process.env.MONGODB_URI || 'mongodb://127.0.0.1:27017/ai_client_outreach';
    await mongoose.connect(uri);
    console.log('Connected to MongoDB:', uri);

    const Company = require('../src/models/Company');
    const Contact = require('../src/models/Contact');
    const CompanyResearch = require('../src/models/CompanyResearch');
    const CrawledPage = require('../src/models/CrawledPage');
    const ImportBatch = require('../src/models/ImportBatch');
    const OutreachMessage = require('../src/models/OutreachMessage');
    const ResearchJob = require('../src/models/ResearchJob');

    await Promise.all([
      Company.deleteMany({}),
      Contact.deleteMany({}),
      CompanyResearch.deleteMany({}),
      CrawledPage.deleteMany({}),
      ImportBatch.deleteMany({}),
      OutreachMessage.deleteMany({}),
      ResearchJob.deleteMany({})
    ]);

    console.log('Successfully cleared all companies, contacts, research reports, crawls, batches, and outreach messages.');
    process.exit(0);
  } catch (err) {
    console.error('Error clearing data:', err.message);
    process.exit(1);
  }
};

clearAllData();
