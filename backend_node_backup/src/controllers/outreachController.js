const {
  generateOutreachSequence,
  bulkGenerateOutreach,
  getCompanyOutreach,
  getAllOutreach,
  updateOutreachMessage,
  deleteOutreachMessage
} = require('../services/outreachService');
const { sendOutreachEmail } = require('../services/emailService');
const { scheduleSequenceSteps } = require('../services/schedulerService');
const {
  getOutreachRecords,
  getOutreachStats,
  updateReplyStatus,
  generateOutreachExcelBuffer
} = require('../services/outreachTrackingService');
const OutreachRecord = require('../models/OutreachRecord');

const generateSequence = async (req, res, next) => {
  try {
    const { companyId } = req.params;
    const messages = await generateOutreachSequence(companyId, req.body);
    res.json({
      success: true,
      message: 'Personalized outreach sequence generated',
      data: messages
    });
  } catch (err) {
    next(err);
  }
};

const scheduleSequence = async (req, res, next) => {
  try {
    const { companyId } = req.params;
    const { schedules } = req.body;
    const updated = await scheduleSequenceSteps(companyId, schedules);
    res.json({
      success: true,
      message: 'Automated sequence schedule activated',
      data: updated
    });
  } catch (err) {
    next(err);
  }
};

const bulkGenerate = async (req, res, next) => {
  try {
    const { companyIds, options } = req.body;
    const results = await bulkGenerateOutreach(companyIds, options);
    res.json({
      success: true,
      message: 'Bulk outreach generation completed',
      data: results
    });
  } catch (err) {
    next(err);
  }
};

const getOutreach = async (req, res, next) => {
  try {
    const { companyId } = req.params;
    const messages = await getCompanyOutreach(companyId);
    res.json({
      success: true,
      data: messages
    });
  } catch (err) {
    next(err);
  }
};

const getGlobalOutbox = async (req, res, next) => {
  try {
    const messages = await getAllOutreach(req.query);
    res.json({
      success: true,
      data: messages
    });
  } catch (err) {
    next(err);
  }
};

const updateMessage = async (req, res, next) => {
  try {
    const { messageId } = req.params;
    const message = await updateOutreachMessage(messageId, req.body);
    res.json({
      success: true,
      message: 'Draft updated successfully',
      data: message
    });
  } catch (err) {
    next(err);
  }
};

const removeMessage = async (req, res, next) => {
  try {
    const { messageId } = req.params;
    const result = await deleteOutreachMessage(messageId);
    res.json({
      success: true,
      message: result.message
    });
  } catch (err) {
    next(err);
  }
};

const sendEmail = async (req, res, next) => {
  try {
    const { messageId } = req.params;
    const { recipientEmail, ccRecipients, bccRecipients } = req.body;
    const result = await sendOutreachEmail(messageId, { recipientEmail, ccRecipients, bccRecipients });
    res.json({
      success: true,
      message: 'Email dispatched successfully',
      data: result
    });
  } catch (err) {
    next(err);
  }
};

/**
 * Outreach Tracking Controllers
 */
const getTrackingRecords = async (req, res, next) => {
  try {
    const result = await getOutreachRecords(req.query);
    res.json({
      success: true,
      data: result.records,
      pagination: result.pagination
    });
  } catch (err) {
    next(err);
  }
};

const getSingleTrackingRecord = async (req, res, next) => {
  try {
    const { recordId } = req.params;
    const record = await OutreachRecord.findById(recordId)
      .populate('companyId', 'companyName website industry country')
      .populate('contactId', 'name title email roleCategory');

    if (!record) {
      throw Object.assign(new Error('Outreach tracking record not found'), { status: 404 });
    }

    res.json({
      success: true,
      data: record
    });
  } catch (err) {
    next(err);
  }
};

const updateTrackingReply = async (req, res, next) => {
  try {
    const { recordId } = req.params;
    const { replyStatus } = req.body;
    const updated = await updateReplyStatus(recordId, replyStatus);
    res.json({
      success: true,
      message: `Reply status updated to ${updated.replyStatus}`,
      data: updated
    });
  } catch (err) {
    next(err);
  }
};

const getTrackingStats = async (req, res, next) => {
  try {
    const stats = await getOutreachStats();
    res.json({
      success: true,
      data: stats
    });
  } catch (err) {
    next(err);
  }
};

const exportOutreachExcel = async (req, res, next) => {
  try {
    const { buffer, filename } = await generateOutreachExcelBuffer(req.query);

    res.setHeader(
      'Content-Type',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    );
    res.setHeader(
      'Content-Disposition',
      `attachment; filename="${filename}"`
    );
    res.setHeader('Content-Length', buffer.length);
    res.end(buffer);
  } catch (err) {
    next(err);
  }
};

module.exports = {
  generateSequence,
  scheduleSequence,
  bulkGenerate,
  getOutreach,
  getGlobalOutbox,
  updateMessage,
  removeMessage,
  sendEmail,
  getTrackingRecords,
  getSingleTrackingRecord,
  updateTrackingReply,
  getTrackingStats,
  exportOutreachExcel
};
