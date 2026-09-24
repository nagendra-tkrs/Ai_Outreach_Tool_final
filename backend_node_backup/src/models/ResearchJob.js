const mongoose = require('mongoose');

const researchJobSchema = new mongoose.Schema({
  companyId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'Company',
    required: true,
    index: true
  },
  type: {
    type: String,
    enum: ['website_crawl', 'ai_research', 'competitor_research'],
    required: true
  },
  status: {
    type: String,
    enum: ['queued', 'running', 'completed', 'failed'],
    default: 'queued'
  },
  startedAt: {
    type: Date,
    default: null
  },
  completedAt: {
    type: Date,
    default: null
  },
  pagesDiscovered: {
    type: Number,
    default: 0
  },
  pagesCrawled: {
    type: Number,
    default: 0
  },
  pagesFailed: {
    type: Number,
    default: 0
  },
  pagesBlocked: {
    type: Number,
    default: 0
  },
  error: {
    type: String,
    default: ''
  }
}, {
  timestamps: true
});

module.exports = mongoose.model('ResearchJob', researchJobSchema);
