const nodemailer = require('nodemailer');
const mongoose = require('mongoose');
const OutreachMessage = require('../models/OutreachMessage');
const Company = require('../models/Company');
const Setting = require('../models/Setting');
const { recordEmailDispatch } = require('./outreachTrackingService');

let cachedTestAccount = null;

/**
 * Get or create nodemailer transporter based on settings
 */
const getTransporter = async (customConfig = null) => {
  let smtp = customConfig;
  if (!smtp && mongoose.connection.readyState === 1) {
    try {
      const setting = await Setting.findOne({ key: 'global_settings' });
      smtp = setting?.smtp;
    } catch {
      // ignore
    }
  }

  // If host and user are provided, require pass
  if (smtp && smtp.host && smtp.user) {
    if (!smtp.pass || !smtp.pass.trim()) {
      throw Object.assign(
        new Error(`SMTP password / App Password is missing for ${smtp.user}. Please enter your 16-character App Password in Settings > Email & SMTP Sending.`),
        { status: 400 }
      );
    }

    return {
      transporter: nodemailer.createTransport({
        host: smtp.host,
        port: Number(smtp.port) || 587,
        secure: smtp.secure === true || Number(smtp.port) === 465,
        auth: {
          user: smtp.user,
          pass: smtp.pass
        }
      }),
      from: `"${smtp.fromName || 'AI Outreach'}" <${smtp.fromEmail || smtp.user}>`,
      isTest: false
    };
  }

  // Otherwise, create/reuse an Ethereal test account for sandbox testing
  if (!cachedTestAccount) {
    try {
      const timeoutPromise = new Promise((_, reject) => setTimeout(() => reject(new Error('Ethereal timeout')), 4000));
      cachedTestAccount = await Promise.race([nodemailer.createTestAccount(), timeoutPromise]);
    } catch {
      cachedTestAccount = {
        user: 'sandbox_test_user@ethereal.email',
        pass: 'sandbox_test_pass'
      };
    }
  }

  const testAccount = cachedTestAccount;
  const testTransporter = nodemailer.createTransport({
    host: 'smtp.ethereal.email',
    port: 587,
    secure: false,
    auth: {
      user: testAccount.user,
      pass: testAccount.pass
    }
  });

  return {
    transporter: testTransporter,
    from: `"${smtp?.fromName || 'AI Client Outreach'}" <${testAccount.user}>`,
    isTest: true,
    account: testAccount
  };
};

/**
 * Send a verification/test email
 */
const sendTestEmail = async (customConfig = null, recipientEmail = 'test@example.com') => {
  const { transporter, from, isTest } = await getTransporter(customConfig);

  const mailOptions = {
    from,
    to: recipientEmail,
    subject: 'AI Client Outreach - SMTP Test Verification',
    text: 'This is a test verification email from your AI Client Outreach platform. If you received this, your SMTP settings are configured properly.',
    html: `
      <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e5e7eb; border-radius: 8px;">
        <h2 style="color: #2563eb;">AI Client Outreach</h2>
        <p>This is a verification test email from your AI Client Outreach platform.</p>
        <div style="background-color: #f3f4f6; padding: 15px; border-radius: 6px; margin: 15px 0;">
          <p style="margin: 0; color: #16a34a; font-weight: bold;"> SMTP connection is active and verified!</p>
          <p style="margin: 5px 0 0 0; color: #6b7280; font-size: 13px;">Timestamp: ${new Date().toISOString()}</p>
        </div>
        <p style="color: #4b5563; font-size: 14px;">You can now dispatch personalized AI email sequences directly to prospects.</p>
      </div>
    `
  };

  const info = await transporter.sendMail(mailOptions);
  const previewUrl = isTest ? nodemailer.getTestMessageUrl(info) : null;

  return {
    success: true,
    messageId: info.messageId,
    previewUrl,
    isTest
  };
};

/**
 * Send an outreach message email with CC and BCC recipients support
 */
const sendOutreachEmail = async (messageId, sendOptions = null) => {
  const message = await OutreachMessage.findById(messageId).populate('companyId contactId');
  if (!message) throw Object.assign(new Error('Outreach message not found'), { status: 404 });

  let targetEmail = null;
  let ccList = message.ccRecipients || [];
  let bccList = message.bccRecipients || [];

  if (typeof sendOptions === 'string') {
    targetEmail = sendOptions;
  } else if (sendOptions && typeof sendOptions === 'object') {
    targetEmail = sendOptions.recipientEmail || sendOptions.targetEmail;
    if (sendOptions.ccRecipients !== undefined) {
      if (Array.isArray(sendOptions.ccRecipients)) {
        ccList = sendOptions.ccRecipients.filter(e => Boolean(e) && e.includes('@'));
      } else if (typeof sendOptions.ccRecipients === 'string') {
        ccList = sendOptions.ccRecipients.split(/[,;\s]+/).map(e => e.trim()).filter(e => Boolean(e) && e.includes('@'));
      }
    }
    if (sendOptions.bccRecipients !== undefined) {
      if (Array.isArray(sendOptions.bccRecipients)) {
        bccList = sendOptions.bccRecipients.filter(e => Boolean(e) && e.includes('@'));
      } else if (typeof sendOptions.bccRecipients === 'string') {
        bccList = sendOptions.bccRecipients.split(/[,;\s]+/).map(e => e.trim()).filter(e => Boolean(e) && e.includes('@'));
      }
    }
  }

  targetEmail = targetEmail || message.recipientEmail || message.contactId?.email || message.companyId?.contactEmail;
  if (!targetEmail) {
    throw Object.assign(new Error('Recipient email address is required. Please set an email address on the contact or message.'), { status: 400 });
  }

  await OutreachMessage.findByIdAndUpdate(messageId, { status: 'sending', error: '' });

  try {
    const { transporter, from, isTest } = await getTransporter();

    const baseUrl = process.env.API_BASE_URL || `http://localhost:${process.env.PORT || 5000}`;
    const trackingPixel = `<img src="${baseUrl}/api/track/open/${messageId}.png" width="1" height="1" style="display:none !important; width:1px; height:1px; border:0;" alt="" />`;

    const mailOptions = {
      from,
      to: targetEmail,
      subject: message.subject,
      text: message.bodyText,
      html: `
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.6; color: #1f2937;">
          ${message.bodyHtml}
          ${trackingPixel}
        </div>
      `
    };

    if (ccList && ccList.length > 0) {
      mailOptions.cc = ccList;
    }
    if (bccList && bccList.length > 0) {
      mailOptions.bcc = bccList;
    }

    const info = await transporter.sendMail(mailOptions);
    const previewUrl = isTest ? nodemailer.getTestMessageUrl(info) : null;

    const updatedMessage = await OutreachMessage.findByIdAndUpdate(
      messageId,
      {
        status: 'sent',
        recipientEmail: targetEmail,
        ccRecipients: ccList,
        bccRecipients: bccList,
        sentAt: new Date(),
        messageId: info.messageId,
        error: ''
      },
      { new: true }
    );

    if (message.companyId?._id) {
      await Company.findByIdAndUpdate(message.companyId._id, { outreachStatus: 'sent' });
    }

    // Automatically record tracking in OutreachRecord
    try {
      await recordEmailDispatch(updatedMessage, {
        success: true,
        messageId: info.messageId,
        recipientEmail: targetEmail,
        ccRecipients: ccList,
        bccRecipients: bccList,
        sentAt: updatedMessage.sentAt || new Date()
      });
    } catch (trackErr) {
      console.error('[EmailService] Failed to record outreach dispatch tracking:', trackErr.message);
    }

    return {
      success: true,
      message: updatedMessage,
      previewUrl,
      isTest
    };
  } catch (err) {
    const failedMessage = await OutreachMessage.findByIdAndUpdate(
      messageId,
      {
        status: 'failed',
        error: err.message
      },
      { new: true }
    );

    // Record failure in OutreachRecord
    try {
      await recordEmailDispatch(failedMessage || message, {
        success: false,
        error: err.message,
        recipientEmail: targetEmail,
        ccRecipients: ccList,
        bccRecipients: bccList
      });
    } catch (trackErr) {
      console.error('[EmailService] Failed to record failed outreach dispatch tracking:', trackErr.message);
    }

    throw err;
  }
};

module.exports = {
  getTransporter,
  sendTestEmail,
  sendOutreachEmail
};
