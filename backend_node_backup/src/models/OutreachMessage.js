const mongoose = require('mongoose');

const outreachMessageSchema = new mongoose.Schema({
  companyId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'Company',
    required: true,
    index: true
  },
  contactId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'Contact',
    default: null
  },
  step: {
    type: Number,
    required: true,
    enum: [1, 2, 3],
    default: 1
  },
  stepLabel: {
    type: String,
    default: 'Initial Outreach'
  },
  subject: {
    type: String,
    required: true,
    trim: true
  },
  bodyHtml: {
    type: String,
    required: true
  },
  bodyText: {
    type: String,
    default: ''
  },
  angle: {
    type: String,
    enum: ['pain_point', 'value_prop', 'icebreaker', 'case_study', 'custom'],
    default: 'pain_point'
  },
  tone: {
    type: String,
    enum: ['conversational', 'professional', 'direct', 'friendly'],
    default: 'conversational'
  },
  focusService: {
    type: String,
    default: 'AI Strategy Consulting'
  },
  status: {
    type: String,
    enum: ['draft', 'approved', 'scheduled', 'sending', 'sent', 'failed'],
    default: 'draft'
  },
  isManuallyEdited: {
    type: Boolean,
    default: false
  },
  scheduledAt: {
    type: Date,
    default: null
  },
  delayDays: {
    type: Number,
    default: 0
  },
  recipientEmail: {
    type: String,
    trim: true,
    default: ''
  },
  recipientName: {
    type: String,
    trim: true,
    default: ''
  },
  ccRecipients: [{
    type: String,
    trim: true
  }],
  bccRecipients: [{
    type: String,
    trim: true
  }],
  sentAt: {
    type: Date,
    default: null
  },
  openedAt: {
    type: Date,
    default: null
  },
  openCount: {
    type: Number,
    default: 0
  },
  clickedAt: {
    type: Date,
    default: null
  },
  clickCount: {
    type: Number,
    default: 0
  },
  messageId: {
    type: String,
    default: null
  },
  trackingId: {
    type: String,
    default: null
  },
  error: {
    type: String,
    default: null
  },
  linkedinNote: {
    type: String,
    default: ''
  },
  linkedinInmail: {
    type: String,
    default: ''
  }
}, {
  timestamps: true
});

outreachMessageSchema.index({ companyId: 1, step: 1 });
outreachMessageSchema.index({ trackingId: 1 });
outreachMessageSchema.index({ status: 1, scheduledAt: 1 });

module.exports = mongoose.model('OutreachMessage', outreachMessageSchema);
