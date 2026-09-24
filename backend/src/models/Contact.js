const mongoose = require('mongoose');

const contactSchema = new mongoose.Schema({
  companyId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'Company',
    required: true,
    index: true
  },
  name: {
    type: String,
    required: [true, 'Contact name is required'],
    trim: true
  },
  designation: {
    type: String,
    trim: true,
    default: ''
  },
  title: {
    type: String,
    trim: true,
    default: ''
  },
  roleCategory: {
    type: String,
    enum: [
      'ceo',
      'founder',
      'co_founder',
      'president',
      'managing_director',
      'coo',
      'cfo',
      'cto',
      'cio',
      'cdo',
      'vp',
      'dept_head',
      'head_of_ai',
      'head_of_data',
      'head_of_technology',
      'head_of_operations',
      'head_of_sales',
      'head_of_product',
      'director',
      'manager',
      'lead',
      'general',
      'other'
    ],
    default: 'other'
  },
  designationOriginal: {
    type: String,
    trim: true,
    default: ''
  },
  designationNormalized: {
    type: String,
    trim: true,
    default: ''
  },
  personVerified: {
    type: String,
    enum: ['true', 'false', 'unknown'],
    default: 'unknown'
  },
  designationVerified: {
    type: String,
    enum: ['true', 'false', 'unknown'],
    default: 'unknown'
  },
  companyAssociationVerified: {
    type: String,
    enum: ['true', 'false', 'unknown'],
    default: 'unknown'
  },
  roleStatus: {
    type: String,
    enum: ['current', 'former', 'historical', 'unknown'],
    default: 'current'
  },
  email: {
    type: String,
    trim: true,
    lowercase: true,
    default: ''
  },
  emailDomain: {
    type: String,
    trim: true,
    lowercase: true,
    default: ''
  },
  corporateEmailDomain: {
    type: String,
    trim: true,
    lowercase: true,
    default: ''
  },
  alternativeEmails: {
    type: [mongoose.Schema.Types.Mixed],
    default: []
  },
  emailStatus: {
    type: String,
    enum: [
      'VERIFIED',
      'DIRECTLY_VERIFIED',
      'PATTERN_VERIFIED',
      'LIKELY',
      'PATTERN_BASED_UNVERIFIED',
      'CATCH_ALL',
      'INVALID',
      'REJECTED',
      'UNKNOWN',
      'NOT_FOUND',
      'EXACT_PUBLIC_SOURCE',
      'EXACT_SOURCE_VERIFIED',
      'DOMAIN_VALID_ONLY',
      'UNVERIFIED'
    ],
    default: 'UNVERIFIED'
  },
  domainStatus: {
    type: String,
    default: 'UNKNOWN'
  },
  status: {
    type: String,
    enum: ['verified', 'pattern_derived', 'unverified', 'not_found', 'inferred', 'discovered', 'bounced'],
    default: 'unverified'
  },
  emailSyntaxValid: {
    type: String,
    enum: ['true', 'false', 'unknown'],
    default: 'unknown'
  },
  emailDomainValid: {
    type: String,
    enum: ['true', 'false', 'unknown'],
    default: 'unknown'
  },
  publicEmailEvidence: {
    type: String,
    enum: ['true', 'false', 'unknown'],
    default: 'unknown'
  },
  personEmailMatch: {
    type: String,
    enum: ['true', 'false', 'unknown'],
    default: 'unknown'
  },
  mailboxVerification: {
    type: String,
    enum: [
      'DIRECT_SOURCE_MATCH',
      'MAILBOX_VERIFIED',
      'NOT_INDEPENDENTLY_CONFIRMED',
      'CATCH_ALL',
      'MAILBOX_INVALID',
      'NOT_APPLICABLE',
      'UNKNOWN'
    ],
    default: 'NOT_INDEPENDENTLY_CONFIRMED'
  },
  emailSource: {
    type: String,
    default: 'Official Leadership Page'
  },
  emailSourceUrl: {
    type: String,
    default: ''
  },
  emailVerificationMethod: {
    type: String,
    default: 'None'
  },
  mxStatus: {
    type: String,
    enum: ['MX_ACTIVE', 'MX_NOT_FOUND', 'UNKNOWN'],
    default: 'UNKNOWN'
  },
  mxProvider: {
    type: String,
    default: ''
  },
  patternUsed: {
    type: String,
    default: 'first.last'
  },
  emailPattern: {
    type: String,
    default: 'first.last'
  },
  patternExamples: {
    type: [String],
    default: []
  },
  patternSources: {
    type: [String],
    default: []
  },
  patternConfidence: {
    type: String,
    default: 'unverified'
  },
  source: {
    type: String,
    default: 'Official Company Leadership Page'
  },
  sourceType: {
    type: String,
    enum: ['official_website', 'official_team_page', 'official_news', 'authoritative_record', 'public_search', 'pattern_inference', 'excel_import', 'manual'],
    default: 'official_team_page'
  },
  sourceUrl: {
    type: String,
    default: ''
  },
  sourceTitle: {
    type: String,
    default: ''
  },
  sourceDate: {
    type: String,
    default: ''
  },
  roleSourceUrl: {
    type: String,
    default: ''
  },
  roleSourceDate: {
    type: String,
    default: ''
  },
  isCurrentRole: {
    type: String,
    enum: ['confirmed_current', 'likely_current', 'uncertain'],
    default: 'likely_current'
  },
  confidenceScore: {
    type: Number,
    min: 0,
    max: 100,
    default: 85
  },
  confidence: {
    type: String,
    enum: ['high', 'medium', 'low', 'zero'],
    default: 'medium'
  },
  dataQuality: {
    type: String,
    enum: ['HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'],
    default: 'UNKNOWN'
  },
  confidenceReasoning: {
    type: [String],
    default: []
  },
  evidenceSources: {
    type: [mongoose.Schema.Types.Mixed],
    default: []
  },
  evidence: {
    personEvidence: { type: String, default: '' },
    roleEvidence: { type: String, default: '' },
    emailEvidence: { type: String, default: '' },
    snippet: { type: String, default: '' },
    sourceDate: { type: String, default: '' },
    retrievedAt: { type: Date, default: Date.now }
  },
  auditTrail: {
    sourcesSearched: { type: [String], default: [] },
    queriesUsed: { type: [String], default: [] },
    emailsDiscovered: { type: [String], default: [] },
    rejectedEmails: { type: [mongoose.Schema.Types.Mixed], default: [] },
    selectedEmail: { type: String, default: '' },
    verificationStatus: { type: String, default: '' },
    confidence: { type: Number, default: 0 }
  },
  verificationDetails: {
    isValidSyntax: { type: Boolean, default: null },
    hasMxRecords: { type: Boolean, default: null },
    patternConfidence: { type: String, default: 'unverified' },
    statusReason: { type: String, default: '' },
    verifiedAt: { type: Date, default: null }
  },
  verificationNotes: {
    type: String,
    default: ''
  },
  lastVerifiedAt: {
    type: Date,
    default: null
  },
  phone: {
    type: String,
    trim: true,
    default: ''
  },
  linkedinUrl: {
    type: String,
    trim: true,
    default: ''
  },
  seniority: {
    type: String,
    enum: ['executive', 'director', 'manager', 'lead', 'staff', 'senior', 'individual_contributor', 'general', 'other', 'unknown'],
    default: 'unknown'
  },
  department: {
    type: String,
    trim: true,
    default: ''
  },
  isPrimaryDecisionMaker: {
    type: Boolean,
    default: false
  },
  relevanceScore: {
    type: Number,
    min: 0,
    max: 100,
    default: 75
  },
  verificationScore: {
    type: Number,
    min: 0,
    max: 100,
    default: 85
  },
  overallScore: {
    type: Number,
    min: 0,
    max: 100,
    default: 80
  },
  selectionReason: {
    type: String,
    default: ''
  },
  candidateEmployer: {
    type: String,
    default: ''
  },
  companyMatchStatus: {
    type: String,
    enum: ['VERIFIED', 'FAILED', 'UNKNOWN'],
    default: 'UNKNOWN'
  },
  evidenceTier: {
    type: String,
    enum: ['tier1', 'tier2', 'tier3', 'unknown'],
    default: 'unknown'
  },
  employmentStatus: {
    type: String,
    enum: ['CURRENT', 'FORMER', 'UNKNOWN'],
    default: 'CURRENT'
  },
  decisionMakerStatus: {
    type: String,
    enum: ['CANDIDATE', 'VERIFIED', 'NOT_VERIFIED', 'REJECTED', 'FORMER', 'INFERRED', 'NEEDS_REVIEW'],
    default: 'VERIFIED'
  },
  targetOpportunity: {
    type: String,
    default: ''
  },
  searchProvider: {
    type: String,
    enum: ['google', 'public_web', 'none'],
    default: 'none'
  },
  searchConfigured: {
    type: Boolean,
    default: false
  },
  searchReason: {
    type: String,
    default: ''
  },
  searchQueriesUsed: {
    type: Number,
    default: 0
  },
  searchResultsFound: {
    type: Number,
    default: 0
  },
  aiProvider: {
    type: String,
    default: ''
  },
  aiModel: {
    type: String,
    default: ''
  },
  discoveredAt: {
    type: Date,
    default: Date.now
  },
  notes: {
    type: String,
    default: ''
  }
}, {
  timestamps: true
});

contactSchema.index({ companyId: 1, email: 1 });
contactSchema.index({ companyId: 1, roleCategory: 1 });
contactSchema.index({ companyId: 1, emailStatus: 1 });

module.exports = mongoose.model('Contact', contactSchema);
