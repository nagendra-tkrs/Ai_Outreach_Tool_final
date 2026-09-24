const mongoose = require('mongoose');

const companyResearchSchema = new mongoose.Schema({
  companyId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'Company',
    required: true,
    index: true,
    unique: true
  },
  summary: {
    type: String,
    default: ''
  },
  valueProposition: {
    type: String,
    default: ''
  },
  coreOfferings: [{
    type: String
  }],
  targetAudience: {
    type: String,
    default: ''
  },
  detectedPainPoints: [{
    title: String,
    description: String
  }],
  techStack: [{
    type: String
  }],
  competitors: [{
    type: String
  }],
  icebreakers: [{
    type: String
  }],
  icpFitScore: {
    type: Number,
    min: 0,
    max: 100,
    default: 75
  },
  icpFitReasoning: {
    type: String,
    default: ''
  },
  keyPersonnel: [{
    name: String,
    title: String
  }],
  sourcesUsed: [{
    url: String,
    title: String,
    pageType: String
  }],
  researchSource: {
    type: String,
    enum: ['website_crawl', 'public_sources', 'hybrid', 'system_guard'],
    default: 'website_crawl'
  },
  researchMethod: {
    type: String,
    enum: ['WEBSITE_CRAWLED', 'WEBSITE_BLOCKED_FALLBACK_USED', 'WEBSITE_BLOCKED_NO_FALLBACK', 'CRAWL_FAILED'],
    default: 'WEBSITE_CRAWLED'
  },
  fallbackUsed: {
    type: Boolean,
    default: false
  },
  blockReason: {
    type: String,
    default: ''
  },
  evidenceItems: [{
    sourceUrl: String,
    sourceTitle: String,
    sourceType: String,
    evidenceText: String,
    retrievedAt: {
      type: Date,
      default: Date.now
    }
  }],
  aiProvider: {
    type: String,
    default: 'gemini'
  },
  aiModel: {
    type: String,
    default: 'gemini-2.5-flash'
  },
  researchedAt: {
    type: Date,
    default: Date.now
  }
}, {
  timestamps: true
});

module.exports = mongoose.model('CompanyResearch', companyResearchSchema);
