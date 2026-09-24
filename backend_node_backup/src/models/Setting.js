const mongoose = require('mongoose');

const settingSchema = new mongoose.Schema({
  key: {
    type: String,
    required: true,
    unique: true,
    default: 'global_settings'
  },
  ai: {
    provider: {
      type: String,
      enum: ['gemini', 'openai', 'ollama'],
      default: 'gemini'
    },
    geminiApiKey: {
      type: String,
      default: ''
    },
    openaiApiKey: {
      type: String,
      default: ''
    },
    ollamaBaseUrl: {
      type: String,
      default: 'http://localhost:11434'
    },
    model: {
      type: String,
      default: 'gemini-2.5-flash'
    }
  },
  smtp: {
    host: {
      type: String,
      default: ''
    },
    port: {
      type: Number,
      default: 587
    },
    secure: {
      type: Boolean,
      default: false
    },
    user: {
      type: String,
      default: ''
    },
    pass: {
      type: String,
      default: ''
    },
    fromName: {
      type: String,
      default: 'AI Outreach'
    },
    fromEmail: {
      type: String,
      default: ''
    }
  },
  senderProfile: {
    companyName: {
      type: String,
      default: 'GrowthAI Solutions'
    },
    senderName: {
      type: String,
      default: 'Alex'
    },
    senderTitle: {
      type: String,
      default: 'Head of Partnerships'
    },
    productDescription: {
      type: String,
      default: 'We help high-growth B2B companies automate client research and outreach pipeline with AI, increasing meeting booking rates by 3.5x.'
    },
    targetPitch: {
      type: String,
      default: 'Offering a quick 10-minute workflow demo to showcase tailored B2B growth opportunities.'
    }
  }
}, {
  timestamps: true
});

module.exports = mongoose.model('Setting', settingSchema);
