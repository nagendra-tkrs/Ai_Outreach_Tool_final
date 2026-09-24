const mongoose = require('mongoose');

const crawledPageSchema = new mongoose.Schema({
  companyId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'Company',
    required: true,
    index: true
  },
  url: {
    type: String,
    required: true
  },
  normalizedUrl: {
    type: String,
    required: true
  },
  title: {
    type: String,
    default: ''
  },
  metaDescription: {
    type: String,
    default: ''
  },
  headings: [{
    level: Number,
    text: String
  }],
  content: {
    type: String,
    default: ''
  },
  statusCode: {
    type: Number,
    default: 0
  },
  contentType: {
    type: String,
    default: ''
  },
  depth: {
    type: Number,
    default: 0
  },
  pageType: {
    type: String,
    enum: ['about', 'services', 'products', 'industries', 'customers', 'case-study', 'leadership', 'careers', 'contact', 'blog', 'resources', 'support', 'legal', 'pricing', 'other'],
    default: 'other'
  },
  wordCount: {
    type: Number,
    default: 0
  },
  finalUrl: {
    type: String,
    default: ''
  },
  contentAvailable: {
    type: Boolean,
    default: false
  },
  contentQuality: {
    type: String,
    enum: ['valid', 'low', 'empty', 'error'],
    default: 'error'
  },
  crawlStatus: {
    type: String,
    enum: ['pending', 'completed', 'failed', 'blocked', 'rate_limited', 'robots_disallowed', 'timeout', 'not_found', 'server_error', 'invalid_content'],
    default: 'pending'
  },
  error: {
    type: String,
    default: ''
  },
  errorReason: {
    type: String,
    default: ''
  },
  contentLength: {
    type: Number,
    default: 0
  },
  retryCount: {
    type: Number,
    default: 0
  },
  isChallengePage: {
    type: Boolean,
    default: false
  },
  crawledAt: {
    type: Date,
    default: null
  }
}, {
  timestamps: true
});

crawledPageSchema.index({ companyId: 1, normalizedUrl: 1 }, { unique: true });

module.exports = mongoose.model('CrawledPage', crawledPageSchema);
