const OutreachMessage = require('../models/OutreachMessage');
const OutreachRecord = require('../models/OutreachRecord');
const { sendOutreachEmail } = require('./emailService');
const { generateOutreachSequence } = require('./outreachService');

let intervalId = null;
let isProcessing = false;

/**
 * Schedule automated sequence steps with day delays
 */
const scheduleSequenceSteps = async (companyId, schedules = []) => {
  // schedules: [{ step: 1, delayDays: 0 }, { step: 2, delayDays: 3 }, { step: 3, delayDays: 6 }]
  const now = Date.now();
  const updatedMessages = [];

  for (const s of schedules) {
    const scheduledTime = new Date(now + (s.delayDays || 0) * 24 * 60 * 60 * 1000);
    const msg = await OutreachMessage.findOneAndUpdate(
      { companyId, step: s.step, status: { $in: ['draft', 'approved', 'scheduled'] } },
      {
        status: s.delayDays === 0 ? 'approved' : 'scheduled',
        delayDays: s.delayDays || 0,
        scheduledAt: scheduledTime
      },
      { new: true }
    );
    if (msg) updatedMessages.push(msg);
  }

  return updatedMessages;
};

/**
 * Process automated follow-ups from OutreachRecord
 */
const processAutomatedFollowUps = async () => {
  const now = new Date();

  // 1. Process Follow-up 1
  const dueFollowUp1Records = await OutreachRecord.find({
    'initialEmail.status': 'SENT',
    'followUp1.status': 'PENDING',
    'followUp1.scheduledAt': { $lte: now },
    replyStatus: 'NO_REPLY'
  }).limit(10);

  for (const record of dueFollowUp1Records) {
    // Re-verify reply status before sending
    const current = await OutreachRecord.findById(record._id);
    if (!current || current.replyStatus === 'REPLIED' || current.followUp1.status === 'SENT') {
      continue;
    }

    console.log(`[Scheduler] Dispatching Follow-up 1 for ${record.companyName} to ${record.recipientEmail}`);

    try {
      // Find or create Step 2 message for this company
      let msg = await OutreachMessage.findOne({
        companyId: record.companyId,
        step: 2,
        status: { $ne: 'sent' }
      });

      if (!msg) {
        // Try generating sequence if missing
        try {
          const generated = await generateOutreachSequence(record.companyId, {
            contactId: record.contactId
          });
          msg = generated.find(m => m.step === 2);
        } catch (genErr) {
          console.warn('[Scheduler] Could not generate sequence step 2:', genErr.message);
        }
      }

      if (msg) {
        await sendOutreachEmail(msg._id, {
          recipientEmail: record.recipientEmail,
          ccRecipients: record.cc,
          bccRecipients: record.bcc
        });
      } else {
        // Fallback: Create a direct follow-up message if not present
        const fallbackMsg = new OutreachMessage({
          companyId: record.companyId,
          contactId: record.contactId,
          step: 2,
          stepLabel: 'Step 2: Practical Value & Workflow Proof',
          subject: `Re: AI Strategic Collaboration with ${record.companyName}`,
          bodyHtml: `<p>Hi ${record.contactName || 'there'},</p><p>Following up on my previous message regarding how AI automation can accelerate ${record.companyName}. Would you have 10 minutes this week for a brief conversation?</p>`,
          bodyText: `Hi ${record.contactName || 'there'},\n\nFollowing up on my previous message regarding how AI automation can accelerate ${record.companyName}. Would you have 10 minutes this week for a brief conversation?`,
          recipientEmail: record.recipientEmail,
          ccRecipients: record.cc,
          bccRecipients: record.bcc,
          status: 'draft'
        });
        await fallbackMsg.save();
        await sendOutreachEmail(fallbackMsg._id, {
          recipientEmail: record.recipientEmail,
          ccRecipients: record.cc,
          bccRecipients: record.bcc
        });
      }
    } catch (err) {
      console.error(`[Scheduler] Follow-up 1 failed for ${record.recipientEmail}:`, err.message);
    }
  }

  // 2. Process Follow-up 2
  const dueFollowUp2Records = await OutreachRecord.find({
    'followUp1.status': 'SENT',
    'followUp2.status': 'PENDING',
    'followUp2.scheduledAt': { $lte: now },
    replyStatus: 'NO_REPLY'
  }).limit(10);

  for (const record of dueFollowUp2Records) {
    const current = await OutreachRecord.findById(record._id);
    if (!current || current.replyStatus === 'REPLIED' || current.followUp2.status === 'SENT') {
      continue;
    }

    console.log(`[Scheduler] Dispatching Follow-up 2 for ${record.companyName} to ${record.recipientEmail}`);

    try {
      let msg = await OutreachMessage.findOne({
        companyId: record.companyId,
        step: 3,
        status: { $ne: 'sent' }
      });

      if (!msg) {
        try {
          const generated = await generateOutreachSequence(record.companyId, {
            contactId: record.contactId
          });
          msg = generated.find(m => m.step === 3);
        } catch (genErr) {
          console.warn('[Scheduler] Could not generate sequence step 3:', genErr.message);
        }
      }

      if (msg) {
        await sendOutreachEmail(msg._id, {
          recipientEmail: record.recipientEmail,
          ccRecipients: record.cc,
          bccRecipients: record.bcc
        });
      } else {
        const fallbackMsg = new OutreachMessage({
          companyId: record.companyId,
          contactId: record.contactId,
          step: 3,
          stepLabel: 'Step 3: Low-Friction Invitation',
          subject: `Final Check-in: AI Strategy for ${record.companyName}`,
          bodyHtml: `<p>Hi ${record.contactName || 'there'},</p><p>I know you're busy, so I'll keep this brief. If you're open to exploring whether our AI consulting can help ${record.companyName}, let me know. Otherwise, I will step back.</p>`,
          bodyText: `Hi ${record.contactName || 'there'},\n\nI know you're busy, so I'll keep this brief. If you're open to exploring whether our AI consulting can help ${record.companyName}, let me know. Otherwise, I will step back.`,
          recipientEmail: record.recipientEmail,
          ccRecipients: record.cc,
          bccRecipients: record.bcc,
          status: 'draft'
        });
        await fallbackMsg.save();
        await sendOutreachEmail(fallbackMsg._id, {
          recipientEmail: record.recipientEmail,
          ccRecipients: record.cc,
          bccRecipients: record.bcc
        });
      }
    } catch (err) {
      console.error(`[Scheduler] Follow-up 2 failed for ${record.recipientEmail}:`, err.message);
    }
  }
};

/**
 * Background worker checking for due scheduled emails and automated follow-ups
 */
const processScheduledEmails = async () => {
  if (isProcessing) return;
  isProcessing = true;

  try {
    // 1. Check OutreachMessage scheduled queue
    const dueMessages = await OutreachMessage.find({
      status: 'scheduled',
      scheduledAt: { $lte: new Date() }
    }).limit(10);

    for (const msg of dueMessages) {
      // Check if contact already replied
      const trackingRecord = await OutreachRecord.findOne({
        companyId: msg.companyId,
        recipientEmail: msg.recipientEmail
      });

      if (trackingRecord?.replyStatus === 'REPLIED') {
        console.log(`[Scheduler] Skipping message ${msg._id} because contact already replied.`);
        msg.status = 'draft';
        await msg.save();
        continue;
      }

      console.log(`[Scheduler] Auto-dispatching scheduled Step ${msg.step} to ${msg.recipientEmail || 'prospect'}...`);
      try {
        await sendOutreachEmail(msg._id);
        console.log(`[Scheduler] Successfully dispatched message ID: ${msg._id}`);
      } catch (err) {
        console.error(`[Scheduler] Failed to dispatch scheduled message ID ${msg._id}:`, err.message);
      }
    }

    // 2. Check OutreachRecord automated follow-ups
    await processAutomatedFollowUps();
  } catch (err) {
    console.error('[Scheduler] Error processing scheduled emails:', err.message);
  } finally {
    isProcessing = false;
  }
};

/**
 * Start the background scheduler
 */
const startScheduler = (intervalMs = 60000) => {
  if (intervalId) return;
  console.log('Automated Drip Sequence & Follow-up Scheduler started (checking every 60s)');
  intervalId = setInterval(processScheduledEmails, intervalMs);
  // Run once immediately on start
  processScheduledEmails();
};

const stopScheduler = () => {
  if (intervalId) {
    clearInterval(intervalId);
    intervalId = null;
  }
};

module.exports = {
  scheduleSequenceSteps,
  processScheduledEmails,
  processAutomatedFollowUps,
  startScheduler,
  stopScheduler
};
