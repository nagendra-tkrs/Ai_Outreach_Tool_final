const express = require('express');
const router = express.Router({ mergeParams: true });
const {
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
} = require('../controllers/outreachController');

// Company-specific routes
router.post('/outreach/generate', generateSequence);
router.post('/outreach/schedule', scheduleSequence);
router.get('/outreach', getOutreach);

// Global Outreach Tracking & Reporting
router.get('/records', getTrackingRecords);
router.get('/records/:recordId', getSingleTrackingRecord);
router.patch('/records/:recordId/reply', updateTrackingReply);
router.post('/records/:recordId/reply', updateTrackingReply);
router.get('/stats', getTrackingStats);
router.get('/export', exportOutreachExcel);

// Direct / Global Outbox Message routes
router.get('/all', getGlobalOutbox);
router.post('/bulk-generate', bulkGenerate);
router.put('/:messageId', updateMessage);
router.delete('/:messageId', removeMessage);
router.post('/:messageId/send', sendEmail);

module.exports = router;
