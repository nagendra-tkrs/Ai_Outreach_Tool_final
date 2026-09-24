const mongoose = require('mongoose');

const companySchema = new mongoose.Schema({
  companyName: {
    type: String,
    required: [true, 'Company name is required'],
    trim: true,
    index: true
  },
  website: {
    type: String,
    required: [true, 'Website is required'],
    trim: true
  },
  normalizedWebsite: {
    type: String,
    required: true,
    unique: true,
    trim: true,
    lowercase: true
  },
  officialDomain: {
    type: String,
    trim: true,
    lowercase: true,
    default: ''
  },
  legalCompanyName: {
    type: String,
    trim: true,
    default: ''
  },
  corporateEmailDomain: {
    type: String,
    trim: true,
    lowercase: true,
    default: ''
  },
  domainEvidence: {
    type: [mongoose.Schema.Types.Mixed],
    default: []
  },
  headquarters: {
    type: String,
    trim: true,
    default: ''
  },
  location: {
    type: String,
    trim: true,
    default: ''
  },
  description: {
    type: String,
    trim: true,
    default: ''
  },
  companyAliases: {
    type: [String],
    default: []
  },
  parentCompany: {
    type: String,
    trim: true,
    default: ''
  },
  industry: {
    type: String,
    trim: true,
    default: ''
  },
  country: {
    type: String,
    trim: true,
    default: ''
  },
  contactName: {
    type: String,
    trim: true,
    default: ''
  },
  contactEmail: {
    type: String,
    trim: true,
    default: ''
  },
  revenue: {
    type: String,
    trim: true,
    default: ''
  },
  employeeCount: {
    type: String,
    trim: true,
    default: ''
  },
  notes: {
    type: String,
    trim: true,
    default: ''
  },
  source: {
    type: String,
    enum: ['bulk', 'manual', 'api'],
    default: 'bulk'
  },
  importBatchId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'ImportBatch',
    default: null
  },
  crawlStatus: {
    type: String,
    enum: ['pending', 'crawling', 'completed', 'failed', 'blocked', 'partially_completed'],
    default: 'pending'
  },
  lastCrawlJobId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'ResearchJob',
    default: null
  },
  researchStatus: {
    type: String,
    enum: ['pending', 'researching', 'completed', 'failed'],
    default: 'pending'
  },
  lastResearchAt: {
    type: Date,
    default: null
  },
  outreachStatus: {
    type: String,
    enum: ['none', 'generated', 'sent'],
    default: 'none'
  }
}, {
  timestamps: true
});

companySchema.pre('validate', function(next) {
  if (this.website && !this.normalizedWebsite) {
    this.normalizedWebsite = this.website
      .replace(/https?:\/\//i, '')
      .replace(/^www\./i, '')
      .split('/')[0]
      .toLowerCase()
      .trim();
  }
  next();
});

module.exports = mongoose.model('Company', companySchema);
