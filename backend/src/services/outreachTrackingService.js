const XLSX = require('xlsx');
const OutreachRecord = require('../models/OutreachRecord');
const Company = require('../models/Company');
const Contact = require('../models/Contact');

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/**
 * Format a Date object to DD-MMM-YYYY (e.g. 31-Aug-2026)
 */
const formatDate = (date) => {
  if (!date) return '';
  const d = new Date(date);
  if (isNaN(d.getTime())) return '';
  const day = String(d.getDate()).padStart(2, '0');
  const month = MONTH_NAMES[d.getMonth()];
  const year = d.getFullYear();
  return `${day}-${month}-${year}`;
};

/**
 * Format a Date object to hh:mm A (e.g. 10:30 AM)
 */
const formatTime = (date) => {
  if (!date) return '';
  const d = new Date(date);
  if (isNaN(d.getTime())) return '';
  let hours = d.getHours();
  const minutes = String(d.getMinutes()).padStart(2, '0');
  const ampm = hours >= 12 ? 'PM' : 'AM';
  hours = hours % 12;
  hours = hours ? hours : 12; // 0 becomes 12
  const formattedHours = String(hours).padStart(2, '0');
  return `${formattedHours}:${minutes} ${ampm}`;
};

/**
 * Get configured delay intervals in days
 */
const getFollowUpDelays = () => {
  const followUp1Days = Number(process.env.FOLLOW_UP_1_DELAY_DAYS) || 3;
  const followUp2Days = Number(process.env.FOLLOW_UP_2_DELAY_DAYS) || 5;
  return { followUp1Days, followUp2Days };
};

/**
 * Automatically create or update OutreachRecord when an email is dispatched or fails
 */
const recordEmailDispatch = async (message, dispatchResult) => {
  if (!message) return null;

  const companyId = message.companyId?._id || message.companyId;
  const contactId = message.contactId?._id || message.contactId || null;
  const targetEmail = (dispatchResult.recipientEmail || message.recipientEmail || '').trim().toLowerCase();

  if (!companyId || !targetEmail) {
    return null;
  }

  // Fetch company details if not populated
  let companyName = message.companyId?.companyName;
  let companyWebsite = message.companyId?.website;
  if (!companyName && companyId) {
    const comp = await Company.findById(companyId).select('companyName website').lean();
    companyName = comp?.companyName || 'Unknown Company';
    companyWebsite = comp?.website || '';
  }

  // Fetch contact details if available
  let contactName = message.recipientName || message.contactId?.name || '';
  let contactDesignation = message.contactId?.title || message.contactId?.designation || '';
  if ((!contactName || !contactDesignation) && contactId) {
    const cont = await Contact.findById(contactId).select('name title designation').lean();
    if (cont) {
      contactName = contactName || cont.name || '';
      contactDesignation = contactDesignation || cont.title || cont.designation || '';
    }
  }

  const ccList = Array.isArray(dispatchResult.ccRecipients)
    ? dispatchResult.ccRecipients
    : Array.isArray(message.ccRecipients)
    ? message.ccRecipients
    : [];

  const bccList = Array.isArray(dispatchResult.bccRecipients)
    ? dispatchResult.bccRecipients
    : Array.isArray(message.bccRecipients)
    ? message.bccRecipients
    : [];

  const { followUp1Days, followUp2Days } = getFollowUpDelays();
  const isSuccess = Boolean(dispatchResult.success);
  const now = dispatchResult.sentAt || new Date();
  const step = Number(message.step) || 1;

  // Find existing tracking record for this company & recipient email
  let record = await OutreachRecord.findOne({ companyId, recipientEmail: targetEmail });
  if (!record) {
    record = new OutreachRecord({
      companyId,
      companyName,
      companyWebsite,
      contactId,
      contactName,
      contactDesignation,
      recipientEmail: targetEmail,
      cc: ccList,
      bcc: bccList,
      emailSubject: message.subject || '',
      emailType: step === 1 ? 'INITIAL' : step === 2 ? 'FOLLOW_UP_1' : 'FOLLOW_UP_2',
      replyStatus: 'NO_REPLY',
      campaignStatus: 'PENDING'
    });
  } else {
    // Update contact and company info if missing or updated
    record.companyName = companyName || record.companyName;
    record.companyWebsite = companyWebsite || record.companyWebsite;
    if (contactId) record.contactId = contactId;
    if (contactName) record.contactName = contactName;
    if (contactDesignation) record.contactDesignation = contactDesignation;
    record.cc = ccList;
    record.bcc = bccList;
    record.emailSubject = message.subject || record.emailSubject;
  }

  if (step === 1) {
    record.emailType = 'INITIAL';
    if (isSuccess) {
      record.initialEmail = {
        scheduledAt: message.scheduledAt || now,
        sentAt: now,
        status: 'SENT',
        messageId: dispatchResult.messageId || null,
        error: null
      };
      record.lastContactedAt = now;

      // Schedule follow-up 1 and follow-up 2 if not already sent
      if (!record.followUp1 || record.followUp1.status !== 'SENT') {
        const f1Date = new Date(now.getTime() + followUp1Days * 24 * 60 * 60 * 1000);
        record.followUp1 = {
          scheduledAt: f1Date,
          sentAt: null,
          status: 'PENDING',
          error: null
        };
      }

      if (!record.followUp2 || record.followUp2.status !== 'SENT') {
        const f2Date = new Date(now.getTime() + (followUp1Days + followUp2Days) * 24 * 60 * 60 * 1000);
        record.followUp2 = {
          scheduledAt: f2Date,
          sentAt: null,
          status: 'PENDING',
          error: null
        };
      }

      if (record.replyStatus !== 'REPLIED') {
        record.campaignStatus = 'INITIAL_SENT';
      }
    } else {
      record.initialEmail = {
        scheduledAt: message.scheduledAt || now,
        sentAt: null,
        status: 'FAILED',
        error: dispatchResult.error || 'Initial email sending failed',
        messageId: null
      };
      record.campaignStatus = 'FAILED';
    }
  } else if (step === 2) {
    record.emailType = 'FOLLOW_UP_1';
    if (isSuccess) {
      record.followUp1 = {
        scheduledAt: record.followUp1?.scheduledAt || message.scheduledAt || now,
        sentAt: now,
        status: 'SENT',
        messageId: dispatchResult.messageId || null,
        error: null
      };
      record.lastContactedAt = now;

      // Recalculate or keep followUp2 schedule
      if (!record.followUp2 || record.followUp2.status !== 'SENT') {
        const f2Date = new Date(now.getTime() + followUp2Days * 24 * 60 * 60 * 1000);
        record.followUp2 = {
          scheduledAt: record.followUp2?.scheduledAt || f2Date,
          sentAt: null,
          status: 'PENDING',
          error: null
        };
      }

      if (record.replyStatus !== 'REPLIED') {
        record.campaignStatus = 'FOLLOW_UP_1_SENT';
      }
    } else {
      record.followUp1 = {
        scheduledAt: record.followUp1?.scheduledAt || message.scheduledAt || now,
        sentAt: null,
        status: 'FAILED',
        error: dispatchResult.error || 'Follow-up 1 sending failed',
        messageId: null
      };
    }
  } else if (step === 3) {
    record.emailType = 'FOLLOW_UP_2';
    if (isSuccess) {
      record.followUp2 = {
        scheduledAt: record.followUp2?.scheduledAt || message.scheduledAt || now,
        sentAt: now,
        status: 'SENT',
        messageId: dispatchResult.messageId || null,
        error: null
      };
      record.lastContactedAt = now;

      if (record.replyStatus !== 'REPLIED') {
        record.campaignStatus = 'FOLLOW_UP_2_SENT';
      }
    } else {
      record.followUp2 = {
        scheduledAt: record.followUp2?.scheduledAt || message.scheduledAt || now,
        sentAt: null,
        status: 'FAILED',
        error: dispatchResult.error || 'Follow-up 2 sending failed',
        messageId: null
      };
    }
  }

  await record.save();
  return record;
};

/**
 * Query outreach records with filtering and pagination
 */
const getOutreachRecords = async (query = {}) => {
  const filter = {};

  if (query.companyId) {
    filter.companyId = query.companyId;
  }

  if (query.status) {
    if (query.status === 'SENT') {
      filter.$or = [
        { 'initialEmail.status': 'SENT' },
        { 'followUp1.status': 'SENT' },
        { 'followUp2.status': 'SENT' }
      ];
    } else if (query.status === 'FAILED') {
      filter.$or = [
        { 'initialEmail.status': 'FAILED' },
        { 'followUp1.status': 'FAILED' },
        { 'followUp2.status': 'FAILED' }
      ];
    } else if (query.status === 'PENDING') {
      filter.$or = [
        { 'initialEmail.status': 'PENDING' },
        { 'followUp1.status': 'PENDING' },
        { 'followUp2.status': 'PENDING' }
      ];
    } else {
      filter.campaignStatus = query.status;
    }
  }

  if (query.campaignStatus) {
    filter.campaignStatus = query.campaignStatus;
  }

  if (query.replyStatus) {
    filter.replyStatus = query.replyStatus;
  }

  if (query.emailType) {
    filter.emailType = query.emailType;
  }

  if (query.search) {
    const searchRegex = new RegExp(query.search.trim(), 'i');
    filter.$or = [
      { companyName: searchRegex },
      { contactName: searchRegex },
      { recipientEmail: searchRegex },
      { emailSubject: searchRegex }
    ];
  }

  if (query.dateFrom || query.dateTo) {
    filter.lastContactedAt = {};
    if (query.dateFrom) filter.lastContactedAt.$gte = new Date(query.dateFrom);
    if (query.dateTo) filter.lastContactedAt.$lte = new Date(query.dateTo);
  }

  const page = Math.max(1, parseInt(query.page) || 1);
  const limit = Math.min(100, Math.max(1, parseInt(query.limit) || 50));
  const skip = (page - 1) * limit;

  const [records, total] = await Promise.all([
    OutreachRecord.find(filter)
      .populate('companyId', 'companyName website industry country')
      .populate('contactId', 'name title email roleCategory')
      .sort({ updatedAt: -1 })
      .skip(skip)
      .limit(limit)
      .lean(),
    OutreachRecord.countDocuments(filter)
  ]);

  return {
    records,
    pagination: {
      total,
      page,
      limit,
      pages: Math.ceil(total / limit)
    }
  };
};

/**
 * Get aggregate statistics for outreach tracking
 */
const getOutreachStats = async () => {
  const [
    totalRecords,
    initialSent,
    followUp1Sent,
    followUp2Sent,
    followUpsPending,
    failedEmails,
    repliesReceived,
    completedCampaigns
  ] = await Promise.all([
    OutreachRecord.countDocuments(),
    OutreachRecord.countDocuments({ 'initialEmail.status': 'SENT' }),
    OutreachRecord.countDocuments({ 'followUp1.status': 'SENT' }),
    OutreachRecord.countDocuments({ 'followUp2.status': 'SENT' }),
    OutreachRecord.countDocuments({
      'initialEmail.status': 'SENT',
      replyStatus: 'NO_REPLY',
      $or: [
        { 'followUp1.status': 'PENDING' },
        { 'followUp1.status': 'SENT', 'followUp2.status': 'PENDING' }
      ]
    }),
    OutreachRecord.countDocuments({
      $or: [
        { 'initialEmail.status': 'FAILED' },
        { 'followUp1.status': 'FAILED' },
        { 'followUp2.status': 'FAILED' }
      ]
    }),
    OutreachRecord.countDocuments({ replyStatus: 'REPLIED' }),
    OutreachRecord.countDocuments({
      $or: [
        { campaignStatus: 'COMPLETED' },
        { campaignStatus: 'REPLIED' },
        { 'followUp2.status': 'SENT' }
      ]
    })
  ]);

  const totalFollowUpsSent = followUp1Sent + followUp2Sent;
  const replyRate = initialSent > 0 ? Math.round((repliesReceived / initialSent) * 100) : 0;

  return {
    totalRecords,
    initialSent,
    followUp1Sent,
    followUp2Sent,
    totalFollowUpsSent,
    followUpsPending,
    failedEmails,
    repliesReceived,
    completedCampaigns,
    replyRate
  };
};

/**
 * Update reply status of an outreach record
 */
const updateReplyStatus = async (recordId, replyStatus) => {
  const record = await OutreachRecord.findById(recordId);
  if (!record) throw Object.assign(new Error('Outreach record not found'), { status: 404 });

  const status = replyStatus === 'REPLIED' ? 'REPLIED' : 'NO_REPLY';
  record.replyStatus = status;

  if (status === 'REPLIED') {
    record.repliedAt = new Date();
    record.campaignStatus = 'REPLIED';
  } else {
    record.repliedAt = null;
    if (record.followUp2?.status === 'SENT') {
      record.campaignStatus = 'FOLLOW_UP_2_SENT';
    } else if (record.followUp1?.status === 'SENT') {
      record.campaignStatus = 'FOLLOW_UP_1_SENT';
    } else if (record.initialEmail?.status === 'SENT') {
      record.campaignStatus = 'INITIAL_SENT';
    } else {
      record.campaignStatus = 'PENDING';
    }
  }

  await record.save();
  return record;
};

/**
 * Format a record row for Excel export
 */
const formatRecordForExcel = (r) => {
  const ccString = Array.isArray(r.cc) && r.cc.length > 0 ? r.cc.join(', ') : '';

  return {
    'Company Name': r.companyName || r.companyId?.companyName || '',
    'Company Website': r.companyWebsite || r.companyId?.website || '',
    'Contact Name': r.contactName || r.contactId?.name || '',
    'Designation': r.contactDesignation || r.contactId?.title || r.contactId?.designation || '',
    'Recipient Email': r.recipientEmail || '',
    'CC': ccString,
    'Email Subject': r.emailSubject || '',
    'Email Type': r.emailType || 'INITIAL',
    'Initial Email Scheduled Date': formatDate(r.initialEmail?.scheduledAt),
    'Initial Email Sent Date': formatDate(r.initialEmail?.sentAt),
    'Initial Email Sent Time': formatTime(r.initialEmail?.sentAt),
    'Initial Email Status': r.initialEmail?.status || 'PENDING',
    'Follow-up 1 Scheduled Date': formatDate(r.followUp1?.scheduledAt),
    'Follow-up 1 Sent Date': formatDate(r.followUp1?.sentAt),
    'Follow-up 1 Sent Time': formatTime(r.followUp1?.sentAt),
    'Follow-up 1 Status': r.followUp1?.status || 'PENDING',
    'Follow-up 2 Scheduled Date': formatDate(r.followUp2?.scheduledAt),
    'Follow-up 2 Sent Date': formatDate(r.followUp2?.sentAt),
    'Follow-up 2 Sent Time': formatTime(r.followUp2?.sentAt),
    'Follow-up 2 Status': r.followUp2?.status || 'PENDING',
    'Last Contacted Date': formatDate(r.lastContactedAt),
    'Reply Status': r.replyStatus || 'NO_REPLY',
    'Campaign Status': r.campaignStatus || 'PENDING'
  };
};

/**
 * Auto-fit column widths for worksheet
 */
const autoFitColumns = (worksheet, data) => {
  if (!data || data.length === 0) return;
  const headers = Object.keys(data[0]);
  const colWidths = headers.map((header) => {
    let maxLen = header.length;
    data.forEach((row) => {
      const val = row[header] !== undefined && row[header] !== null ? String(row[header]) : '';
      if (val.length > maxLen) maxLen = val.length;
    });
    return { wch: Math.min(Math.max(maxLen + 3, 12), 45) };
  });
  worksheet['!cols'] = colWidths;
};

/**
 * Generate multi-sheet Excel report buffer
 */
const generateOutreachExcelBuffer = async (filterQuery = {}) => {
  const query = { ...filterQuery };
  delete query.page;
  delete query.limit;

  const result = await getOutreachRecords({ ...query, limit: 10000 });
  const records = result.records || [];
  const stats = await getOutreachStats();

  // Sheet 1: Outreach Summary
  const allRows = records.map(formatRecordForExcel);

  // Sheet 2: Follow-up Tracking
  const followUpRows = records
    .filter((r) => {
      return (
        r.followUp1?.status === 'SENT' ||
        r.followUp2?.status === 'SENT' ||
        r.followUp1?.status === 'PENDING' ||
        r.followUp2?.status === 'PENDING' ||
        r.initialEmail?.status === 'SENT'
      );
    })
    .map(formatRecordForExcel);

  // Sheet 3: Summary Analytics
  const summaryRows = [
    { Metric: 'Report Generated At', Value: new Date().toISOString() },
    { Metric: 'Total Outreach Records', Value: stats.totalRecords },
    { Metric: 'Total Initial Emails Sent', Value: stats.initialSent },
    { Metric: 'Total Follow-up 1 Sent', Value: stats.followUp1Sent },
    { Metric: 'Total Follow-up 2 Sent', Value: stats.followUp2Sent },
    { Metric: 'Total Follow-ups Sent', Value: stats.totalFollowUpsSent },
    { Metric: 'Follow-ups Pending Dispatch', Value: stats.followUpsPending },
    { Metric: 'Total Emails Failed', Value: stats.failedEmails },
    { Metric: 'Replies Received', Value: stats.repliesReceived },
    { Metric: 'Completed Campaigns', Value: stats.completedCampaigns },
    { Metric: 'Reply Rate (%)', Value: `${stats.replyRate}%` }
  ];

  const wb = XLSX.utils.book_new();

  // 1. Create Sheet 1
  const ws1 = XLSX.utils.json_to_sheet(allRows.length > 0 ? allRows : [formatRecordForExcel({})]);
  autoFitColumns(ws1, allRows.length > 0 ? allRows : [formatRecordForExcel({})]);
  XLSX.utils.book_append_sheet(wb, ws1, 'Outreach Summary');

  // 2. Create Sheet 2
  const ws2 = XLSX.utils.json_to_sheet(followUpRows.length > 0 ? followUpRows : [formatRecordForExcel({})]);
  autoFitColumns(ws2, followUpRows.length > 0 ? followUpRows : [formatRecordForExcel({})]);
  XLSX.utils.book_append_sheet(wb, ws2, 'Follow-up Tracking');

  // 3. Create Sheet 3
  const ws3 = XLSX.utils.json_to_sheet(summaryRows);
  autoFitColumns(ws3, summaryRows);
  XLSX.utils.book_append_sheet(wb, ws3, 'Summary');

  const buffer = XLSX.write(wb, { type: 'buffer', bookType: 'xlsx' });
  return {
    buffer,
    filename: `AI_Outreach_Report_${formatDate(new Date())}.xlsx`
  };
};

module.exports = {
  formatDate,
  formatTime,
  getFollowUpDelays,
  recordEmailDispatch,
  getOutreachRecords,
  getOutreachStats,
  updateReplyStatus,
  generateOutreachExcelBuffer
};
