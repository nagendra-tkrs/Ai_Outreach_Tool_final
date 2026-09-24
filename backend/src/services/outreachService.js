const OutreachMessage = require('../models/OutreachMessage');
const Company = require('../models/Company');
const Contact = require('../models/Contact');
const CompanyResearch = require('../models/CompanyResearch');
const Setting = require('../models/Setting');
const { getAiConfig, callGemini, callOpenAI, callAI, canUseAI, generateFallbackOutreach } = require('./aiService');

/**
 * Generate 3-step personalized outreach sequence tailored to the selected decision maker
 */
const generateOutreachSequence = async (companyId, options = {}) => {
  const {
    contactId = null,
    angle = 'pain_point',
    tone = 'conversational',
    focusService = 'AI Strategy Consulting'
  } = options;

  const company = await Company.findById(companyId);
  if (!company) throw Object.assign(new Error('Company not found'), { status: 404 });

  let contact = null;
  if (contactId) {
    contact = await Contact.findById(contactId);
  }
  if (!contact) {
    contact = await Contact.findOne({ companyId }).sort({ seniority: 1 });
  }

  const research = await CompanyResearch.findOne({ companyId });

  // Get sender profile from Settings
  let sender = {
    senderName: 'Nagendra',
    senderTitle: 'Business Analyst',
    companyName: 'TKSR Product Services',
    senderEmail: 'nagendra@tksrproductservices.com'
  };

  try {
    const setting = await Setting.findOne({ key: 'global_settings' });
    if (setting?.profile) {
      sender.senderName = setting.profile.senderName || sender.senderName;
      sender.senderTitle = setting.profile.senderTitle || sender.senderTitle;
      sender.companyName = setting.profile.companyName || sender.companyName;
    }
  } catch (err) {
    console.warn('Could not fetch sender profile, using default:', err.message);
  }

  const aiConfig = await getAiConfig();
  let generatedSteps = [];

  if (canUseAI(aiConfig)) {
    const contactName = contact?.name || company.contactName || 'there';
    const contactTitle = contact?.title || 'Executive Leadership';
    const companyName = company.companyName;

    const systemPrompt = `You are a world-class enterprise AI B2B copywriter representing "${sender.companyName}".
You write short, punchy, professional, and evidence-based outreach emails to decision makers.
CRITICAL RULES:
- Focus on the SINGLE MOST RELEVANT problem for the prospect and explain how "${focusService}" from ${sender.companyName} solves that specific challenge.
- DO NOT dump a bulleted laundry list of all services.
- Directly address the recipient by name (${contactName}) and acknowledge their role as ${contactTitle} at ${companyName}.
- Keep each email under 130 words.
- Tone: ${tone}.
- Angle: ${angle}.
- Output strict JSON with key "sequence".`;

    const userPrompt = `Generate a 3-step cold outreach sequence from ${sender.senderName} (${sender.senderTitle}, ${sender.companyName}) to:
Prospect: ${contactName}
Designation: ${contactTitle}
Company: ${companyName} (${company.website})
Industry: ${company.industry || 'B2B'}
Target Service Focus: ${focusService}

Company Research & AI Context:
${research?.summary || 'Growing technology company scaling operations.'}
Pain Points: ${JSON.stringify(research?.detectedPainPoints || [])}

Return a strict JSON object with this exact schema:
{
  "sequence": [
    {
      "step": 1,
      "stepLabel": "Step 1: Strategic AI Opportunity",
      "subject": "Concise compelling subject line (under 7 words)",
      "bodyText": "Plain text email under 130 words tailored specifically to ${focusService}",
      "bodyHtml": "<p>HTML email body with clean paragraph formatting</p>",
      "linkedinNote": "Short LinkedIn connection note under 280 characters",
      "linkedinInmail": "Direct InMail message copy"
    },
    {
      "step": 2,
      "stepLabel": "Step 2: Practical Value & Workflow Proof",
      "subject": "Re: Follow up subject line",
      "bodyText": "Follow-up email under 100 words",
      "bodyHtml": "<p>HTML email body for step 2</p>",
      "linkedinNote": "Follow-up connection note",
      "linkedinInmail": "Follow-up InMail copy"
    },
    {
      "step": 3,
      "stepLabel": "Step 3: Low-Friction Invitation",
      "subject": "Final check-in subject line",
      "bodyText": "Low-friction breakup/check-in email under 80 words",
      "bodyHtml": "<p>HTML email body for step 3</p>",
      "linkedinNote": "Final check-in note",
      "linkedinInmail": "Final check-in InMail copy"
    }
  ]
}`;

    try {
      let resData = null;
      if (aiConfig.provider === 'gemini' && aiConfig.geminiKey) {
        resData = await callGemini(userPrompt, systemPrompt, aiConfig.geminiKey, aiConfig.model);
      } else if (aiConfig.provider === 'openai' && aiConfig.openaiKey) {
        resData = await callOpenAI(userPrompt, systemPrompt, aiConfig.openaiKey, aiConfig.model);
      } else if (aiConfig.provider === 'ollama') {
        resData = await callAI(userPrompt, systemPrompt, aiConfig);
      }
      if (resData && Array.isArray(resData.sequence) && resData.sequence.length > 0) {
        generatedSteps = resData.sequence;
      }
    } catch (err) {
      console.warn('AI sequence generation failed, using fallback generator:', err.message);
      generatedSteps = generateFallbackOutreach(company, research, contact, sender, angle, tone, focusService);
    }
  }

  if (generatedSteps.length === 0) {
    generatedSteps = generateFallbackOutreach(company, research, contact, sender, angle, tone, focusService);
  }

  // Preserve existing CC and BCC recipients
  const existingDrafts = await OutreachMessage.find({ companyId, status: 'draft' });
  const existingMetaMap = {};
  for (const d of existingDrafts) {
    existingMetaMap[d.step] = {
      cc: d.ccRecipients || [],
      bcc: d.bccRecipients || []
    };
  }

  const savedMessages = [];
  for (const item of generatedSteps) {
    const prevMeta = existingMetaMap[item.step] || { cc: [], bcc: [] };
    const msg = await OutreachMessage.findOneAndUpdate(
      { companyId, step: item.step, status: 'draft' },
      {
        companyId,
        contactId: contact?._id || null,
        step: item.step,
        stepLabel: item.stepLabel || `Step ${item.step}`,
        subject: item.subject,
        bodyHtml: item.bodyHtml,
        bodyText: item.bodyText || item.bodyHtml.replace(/<[^>]*>?/gm, ''),
        focusService: focusService || 'AI Strategy Consulting',
        linkedinNote: item.linkedinNote || '',
        linkedinInmail: item.linkedinInmail || '',
        angle: item.angle || angle,
        tone: item.tone || tone,
        status: 'draft',
        isManuallyEdited: false,
        recipientEmail: contact?.email || '',
        recipientName: contact?.name || company.contactName || 'Lead',
        ccRecipients: prevMeta.cc,
        bccRecipients: prevMeta.bcc
      },
      { upsert: true, new: true, setDefaultsOnInsert: true }
    );
    savedMessages.push(msg);
  }

  company.outreachStatus = 'generated';
  await company.save();

  return savedMessages;
};

/**
 * Get all outreach messages for a company
 */
const getOutreachMessages = async (companyId) => {
  const company = await Company.findById(companyId);
  if (!company) throw Object.assign(new Error('Company not found'), { status: 404 });

  return OutreachMessage.find({ companyId })
    .populate('contactId', 'name title email status roleCategory')
    .sort({ step: 1 });
};

/**
 * Update an outreach draft message (preserving user edits)
 */
const updateOutreachMessage = async (messageId, updateData) => {
  const message = await OutreachMessage.findById(messageId);
  if (!message) throw Object.assign(new Error('Outreach message not found'), { status: 404 });

  if (message.status === 'sent') {
    throw Object.assign(new Error('Cannot edit an already sent message'), { status: 400 });
  }

  if (updateData.subject !== undefined) message.subject = updateData.subject;
  if (updateData.bodyHtml !== undefined) message.bodyHtml = updateData.bodyHtml;
  if (updateData.bodyText !== undefined) message.bodyText = updateData.bodyText;
  if (updateData.recipientEmail !== undefined) message.recipientEmail = updateData.recipientEmail;
  if (updateData.recipientName !== undefined) message.recipientName = updateData.recipientName;
  if (updateData.ccRecipients !== undefined) message.ccRecipients = updateData.ccRecipients;
  if (updateData.bccRecipients !== undefined) message.bccRecipients = updateData.bccRecipients;
  if (updateData.focusService !== undefined) message.focusService = updateData.focusService;
  if (updateData.linkedinNote !== undefined) message.linkedinNote = updateData.linkedinNote;
  if (updateData.linkedinInmail !== undefined) message.linkedinInmail = updateData.linkedinInmail;

  // Mark as manually edited so auto-tasks don't override user's custom changes
  message.isManuallyEdited = true;

  await message.save();
  return message;
};

/**
 * Schedule a sequence
 */
const scheduleSequence = async (companyId, scheduleConfig) => {
  const company = await Company.findById(companyId);
  if (!company) throw Object.assign(new Error('Company not found'), { status: 404 });

  const messages = await OutreachMessage.find({ companyId, status: { $in: ['draft', 'approved'] } });
  if (messages.length === 0) {
    throw Object.assign(new Error('No draft messages to schedule'), { status: 400 });
  }

  const { schedules = [] } = scheduleConfig;
  const scheduleMap = {};
  for (const s of schedules) {
    scheduleMap[s.step] = s.delayDays;
  }

  const updatedMessages = [];
  const now = new Date();

  for (const msg of messages) {
    const delayDays = scheduleMap[msg.step] !== undefined ? scheduleMap[msg.step] : msg.delayDays;
    const scheduledAt = new Date(now.getTime() + delayDays * 24 * 60 * 60 * 1000);

    msg.delayDays = delayDays;
    msg.scheduledAt = scheduledAt;
    msg.status = 'scheduled';
    await msg.save();
    updatedMessages.push(msg);
  }

  return updatedMessages;
};

/**
 * Get all outreach messages across all companies (global outbox)
 */
const getAllOutreach = async (query = {}) => {
  const filter = {};
  if (query.status) filter.status = query.status;
  if (query.companyId) filter.companyId = query.companyId;

  return OutreachMessage.find(filter)
    .populate('companyId', 'companyName website industry')
    .populate('contactId', 'name title email status roleCategory')
    .sort({ createdAt: -1 });
};

/**
 * Bulk generate outreach sequences for multiple companies
 */
const bulkGenerateOutreach = async (companyIds = [], options = {}) => {
  const results = [];
  for (const companyId of companyIds) {
    try {
      const messages = await generateOutreachSequence(companyId, options);
      results.push({ companyId, success: true, count: messages.length });
    } catch (err) {
      results.push({ companyId, success: false, error: err.message });
    }
  }
  return {
    total: companyIds.length,
    successful: results.filter(r => r.success).length,
    results
  };
};

/**
 * Delete a message
 */
const deleteOutreachMessage = async (messageId) => {
  const message = await OutreachMessage.findByIdAndDelete(messageId);
  if (!message) throw Object.assign(new Error('Message not found'), { status: 404 });
  return { success: true, message: 'Message deleted' };
};

const getCompanyOutreach = getOutreachMessages;

module.exports = {
  generateOutreachSequence,
  getOutreachMessages,
  getCompanyOutreach,
  getAllOutreach,
  bulkGenerateOutreach,
  updateOutreachMessage,
  scheduleSequence,
  deleteOutreachMessage
};
