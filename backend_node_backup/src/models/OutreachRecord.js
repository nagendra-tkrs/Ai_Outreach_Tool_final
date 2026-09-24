const mongoose = require('mongoose');

const emailStepSchema = new mongoose.Schema({
  scheduledAt: {
    type: Date,
    default: null
  },
  sentAt: {
    type: Date,
    default: null
  },
  status: {
    type: String,
    enum: ['PENDING', 'SENT', 'FAILED'],
    default: 'PENDING'
  },
  error: {
    type: String,
    default: null
  },
  messageId: {
    type: String,
    default: null
  }
}, { _id: false });

const outreachRecordSchema = new mongoose.Schema({
  companyId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'Company',
    required: true,
    index: true
  },
  companyName: {
    type: String,
    required: true,
    trim: true
  },
  companyWebsite: {
    type: String,
    trim: true,
    default: ''
  },
  contactId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'Contact',
    default: null
  },
  contactName: {
    type: String,
    trim: true,
    default: ''
  },
  contactDesignation: {
    type: String,
    trim: true,
    default: ''
  },
  recipientEmail: {
    type: String,
    required: true,
    trim: true,
    lowercase: true,
    index: true
  },
  cc: [{
    type: String,
    trim: true,
    lowercase: true
  }],
  bcc: [{
    type: String,
    trim: true,
    lowercase: true
  }],
  emailSubject: {
    type: String,
    trim: true,
    default: ''
  },
  emailType: {
    type: String,
    enum: ['INITIAL', 'FOLLOW_UP_1', 'FOLLOW_UP_2'],
    default: 'INITIAL'
  },
  initialEmail: {
    type: emailStepSchema,
    default: () => ({ status: 'PENDING' })
  },
  followUp1: {
    type: emailStepSchema,
    default: () => ({ status: 'PENDING' })
  },
  followUp2: {
    type: emailStepSchema,
    default: () => ({ status: 'PENDING' })
  },
  lastContactedAt: {
    type: Date,
    default: null
  },
  replyStatus: {
    type: String,
    enum: ['NO_REPLY', 'REPLIED'],
    default: 'NO_REPLY',
    index: true
  },
  repliedAt: {
    type: Date,
    default: null
  },
  campaignStatus: {
    type: String,
    enum: ['PENDING', 'INITIAL_SENT', 'FOLLOW_UP_1_SENT', 'FOLLOW_UP_2_SENT', 'REPLIED', 'COMPLETED', 'FAILED'],
    default: 'PENDING',
    index: true
  }
}, {
  timestamps: true
});

outreachRecordSchema.index({ companyId: 1, recipientEmail: 1 });
outreachRecordSchema.index({ 'initialEmail.status': 1, 'followUp1.status': 1, 'followUp2.status': 1 });

module.exports = mongoose.model('OutreachRecord', outreachRecordSchema);
