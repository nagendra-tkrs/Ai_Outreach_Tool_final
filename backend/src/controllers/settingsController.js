const Setting = require('../models/Setting');
const { sendTestEmail } = require('../services/emailService');

/**
 * Mask secret key or password for client response
 */
const maskSecret = (secret) => {
  if (!secret) return '';
  if (secret.length <= 8) return '********';
  return `${secret.slice(0, 4)}...${secret.slice(-4)}`;
};

const getSettings = async (req, res, next) => {
  try {
    let setting = await Setting.findOne({ key: 'global_settings' });
    if (!setting) {
      setting = await Setting.create({ key: 'global_settings' });
    }

    const safeSetting = {
      ai: {
        provider: setting.ai?.provider || 'gemini',
        geminiApiKey: maskSecret(setting.ai?.geminiApiKey || process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY || ''),
        openaiApiKey: maskSecret(setting.ai?.openaiApiKey || process.env.OPENAI_API_KEY || ''),
        ollamaBaseUrl: setting.ai?.ollamaBaseUrl || process.env.OLLAMA_BASE_URL || 'http://localhost:11434',
        model: setting.ai?.model || 'gemini-2.5-flash',
        hasGeminiKey: Boolean(setting.ai?.geminiApiKey || process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY),
        hasOpenaiKey: Boolean(setting.ai?.openaiApiKey || process.env.OPENAI_API_KEY)
      },
      smtp: {
        host: setting.smtp?.host || '',
        port: setting.smtp?.port || 587,
        secure: setting.smtp?.secure || false,
        user: setting.smtp?.user || '',
        pass: maskSecret(setting.smtp?.pass || ''),
        hasPass: Boolean(setting.smtp?.pass),
        fromName: setting.smtp?.fromName || 'AI Outreach',
        fromEmail: setting.smtp?.fromEmail || ''
      },
      senderProfile: setting.senderProfile || {}
    };

    res.json({
      success: true,
      data: safeSetting
    });
  } catch (err) {
    next(err);
  }
};

const updateSettings = async (req, res, next) => {
  try {
    const { ai, smtp, senderProfile } = req.body;

    let setting = await Setting.findOne({ key: 'global_settings' });
    if (!setting) {
      setting = new Setting({ key: 'global_settings' });
    }

    // Update AI settings if provided
    if (ai) {
      if (ai.provider) setting.ai.provider = ai.provider;
      if (ai.model) setting.ai.model = ai.model;
      if (ai.ollamaBaseUrl) setting.ai.ollamaBaseUrl = ai.ollamaBaseUrl.trim();
      // Only overwrite API keys if a new unmasked value is provided
      if (ai.geminiApiKey && !ai.geminiApiKey.includes('...')) {
        setting.ai.geminiApiKey = ai.geminiApiKey.trim();
      }
      if (ai.openaiApiKey && !ai.openaiApiKey.includes('...')) {
        setting.ai.openaiApiKey = ai.openaiApiKey.trim();
      }
    }

    // Update SMTP settings if provided
    if (smtp) {
      if (smtp.host !== undefined) setting.smtp.host = smtp.host.trim();
      if (smtp.port !== undefined) setting.smtp.port = Number(smtp.port);
      if (smtp.secure !== undefined) setting.smtp.secure = Boolean(smtp.secure);
      if (smtp.user !== undefined) setting.smtp.user = smtp.user.trim();
      if (smtp.fromName !== undefined) setting.smtp.fromName = smtp.fromName.trim();
      if (smtp.fromEmail !== undefined) setting.smtp.fromEmail = smtp.fromEmail.trim();
      if (smtp.pass && !smtp.pass.includes('...')) {
        setting.smtp.pass = smtp.pass;
      }
    }

    // Update sender profile if provided
    if (senderProfile) {
      setting.senderProfile = {
        ...setting.senderProfile,
        ...senderProfile
      };
    }

    await setting.save();

    res.json({
      success: true,
      message: 'Settings updated successfully'
    });
  } catch (err) {
    next(err);
  }
};

const testSmtp = async (req, res, next) => {
  try {
    const { smtp, recipientEmail } = req.body;
    const result = await sendTestEmail(smtp, recipientEmail);
    res.json({
      success: true,
      message: result.isTest 
        ? 'Test email generated using Ethereal sandbox (view preview link)' 
        : `Test email dispatched to ${recipientEmail}`,
      data: result
    });
  } catch (err) {
    next(err);
  }
};

module.exports = {
  getSettings,
  updateSettings,
  testSmtp
};
