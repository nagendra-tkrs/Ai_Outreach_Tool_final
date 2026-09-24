const mongoose = require('mongoose');
const request = require('supertest');
const XLSX = require('xlsx');
const { app } = require('../../server');
const Company = require('../../models/Company');
const Contact = require('../../models/Contact');
const OutreachMessage = require('../../models/OutreachMessage');
const OutreachRecord = require('../../models/OutreachRecord');
const {
  formatDate,
  formatTime,
  recordEmailDispatch,
  getOutreachRecords,
  getOutreachStats,
  updateReplyStatus,
  generateOutreachExcelBuffer
} = require('../outreachTrackingService');
const { processAutomatedFollowUps } = require('../schedulerService');
const { sendOutreachEmail } = require('../emailService');

describe('Email Outreach Tracking & Excel Export System', () => {
  let testCompany;
  let testContact;

  beforeAll(async () => {
    const testUri = process.env.MONGODB_TEST_URI || 'mongodb://127.0.0.1:27017/ai_client_outreach_test';
    if (mongoose.connection.readyState === 0) {
      await mongoose.connect(testUri);
    }
  });

  beforeEach(async () => {
    await OutreachRecord.deleteMany({});
    await OutreachMessage.deleteMany({});
    await Company.deleteMany({});
    await Contact.deleteMany({});

    testCompany = await Company.create({
      companyName: 'Acme AI Systems',
      website: 'https://acmeai.example.com',
      industry: 'Technology',
      country: 'United States'
    });

    testContact = await Contact.create({
      companyId: testCompany._id,
      name: 'Jane Doe',
      title: 'Chief Technology Officer',
      email: 'jane.doe@acmeai.example.com'
    });
  });

  afterAll(async () => {
    await OutreachRecord.deleteMany({});
    await OutreachMessage.deleteMany({});
    await Company.deleteMany({});
    await Contact.deleteMany({});
    await mongoose.connection.close();
  });

  describe('1. Date & Time Formatting Helpers', () => {
    it('should format dates as DD-MMM-YYYY', () => {
      const date = new Date(2026, 7, 31); // 31 Aug 2026
      expect(formatDate(date)).toBe('31-Aug-2026');
    });

    it('should format times as hh:mm A', () => {
      const date = new Date(2026, 7, 31, 10, 30);
      expect(formatTime(date)).toBe('10:30 AM');
    });

    it('should return empty string for null or invalid dates', () => {
      expect(formatDate(null)).toBe('');
      expect(formatTime(null)).toBe('');
      expect(formatDate('invalid-date')).toBe('');
    });
  });

  describe('2. Outreach Record Creation and Synchronization', () => {
    it('should create an OutreachRecord when initial email is successfully dispatched', async () => {
      const message = await OutreachMessage.create({
        companyId: testCompany._id,
        contactId: testContact._id,
        step: 1,
        stepLabel: 'Initial Outreach',
        subject: 'Strategic AI Partnership with Acme AI Systems',
        bodyHtml: '<p>Hello Jane, we would love to collaborate on AI consulting.</p>',
        recipientEmail: 'jane.doe@acmeai.example.com',
        recipientName: 'Jane Doe',
        ccRecipients: ['coo@acmeai.example.com', 'vp@acmeai.example.com'],
        status: 'draft'
      });

      const sentTime = new Date(2026, 7, 31, 10, 0);
      const record = await recordEmailDispatch(message, {
        success: true,
        messageId: '<msg-12345@ethereal.email>',
        recipientEmail: 'jane.doe@acmeai.example.com',
        ccRecipients: ['coo@acmeai.example.com', 'vp@acmeai.example.com'],
        sentAt: sentTime
      });

      expect(record).toBeDefined();
      expect(record.companyName).toBe('Acme AI Systems');
      expect(record.companyWebsite).toBe('https://acmeai.example.com');
      expect(record.contactName).toBe('Jane Doe');
      expect(record.contactDesignation).toBe('Chief Technology Officer');
      expect(record.recipientEmail).toBe('jane.doe@acmeai.example.com');
      expect(record.cc).toEqual(['coo@acmeai.example.com', 'vp@acmeai.example.com']);
      expect(record.emailSubject).toBe('Strategic AI Partnership with Acme AI Systems');
      expect(record.emailType).toBe('INITIAL');
      expect(record.initialEmail.status).toBe('SENT');
      expect(record.initialEmail.sentAt).toEqual(sentTime);
      expect(record.initialEmail.messageId).toBe('<msg-12345@ethereal.email>');
      expect(record.campaignStatus).toBe('INITIAL_SENT');
      expect(record.replyStatus).toBe('NO_REPLY');

      // Check follow-up schedules were auto-calculated
      expect(record.followUp1.status).toBe('PENDING');
      expect(record.followUp1.scheduledAt).toBeDefined();
      expect(record.followUp2.status).toBe('PENDING');
      expect(record.followUp2.scheduledAt).toBeDefined();

      const f1DiffDays = Math.round((record.followUp1.scheduledAt.getTime() - sentTime.getTime()) / (24 * 60 * 60 * 1000));
      expect(f1DiffDays).toBe(3); // Default 3 days
    });

    it('should mark initial email as FAILED when sending fails', async () => {
      const message = await OutreachMessage.create({
        companyId: testCompany._id,
        contactId: testContact._id,
        step: 1,
        subject: 'Intro to AI Systems',
        bodyHtml: '<p>Test</p>',
        recipientEmail: 'jane.doe@acmeai.example.com',
        status: 'draft'
      });

      const record = await recordEmailDispatch(message, {
        success: false,
        error: 'SMTP Connection timeout (ECONNREFUSED)',
        recipientEmail: 'jane.doe@acmeai.example.com'
      });

      expect(record).toBeDefined();
      expect(record.initialEmail.status).toBe('FAILED');
      expect(record.initialEmail.sentAt).toBeNull();
      expect(record.initialEmail.error).toContain('SMTP Connection timeout');
      expect(record.campaignStatus).toBe('FAILED');
    });

    it('should update follow-up 1 and follow-up 2 on subsequent dispatches', async () => {
      const message1 = await OutreachMessage.create({
        companyId: testCompany._id,
        contactId: testContact._id,
        step: 1,
        subject: 'Initial Step 1',
        bodyHtml: '<p>Step 1</p>',
        recipientEmail: 'jane.doe@acmeai.example.com',
        status: 'sent'
      });

      await recordEmailDispatch(message1, {
        success: true,
        messageId: '<step1@ethereal.email>',
        recipientEmail: 'jane.doe@acmeai.example.com'
      });

      // Dispatch Follow-up 1 (Step 2)
      const message2 = await OutreachMessage.create({
        companyId: testCompany._id,
        contactId: testContact._id,
        step: 2,
        subject: 'Re: Follow up 1',
        bodyHtml: '<p>Step 2</p>',
        recipientEmail: 'jane.doe@acmeai.example.com',
        status: 'sent'
      });

      const updatedRecord1 = await recordEmailDispatch(message2, {
        success: true,
        messageId: '<step2@ethereal.email>',
        recipientEmail: 'jane.doe@acmeai.example.com'
      });

      expect(updatedRecord1.followUp1.status).toBe('SENT');
      expect(updatedRecord1.followUp1.sentAt).toBeDefined();
      expect(updatedRecord1.campaignStatus).toBe('FOLLOW_UP_1_SENT');
      expect(updatedRecord1.emailType).toBe('FOLLOW_UP_1');

      // Dispatch Follow-up 2 (Step 3)
      const message3 = await OutreachMessage.create({
        companyId: testCompany._id,
        contactId: testContact._id,
        step: 3,
        subject: 'Re: Final Check-in',
        bodyHtml: '<p>Step 3</p>',
        recipientEmail: 'jane.doe@acmeai.example.com',
        status: 'sent'
      });

      const updatedRecord2 = await recordEmailDispatch(message3, {
        success: true,
        messageId: '<step3@ethereal.email>',
        recipientEmail: 'jane.doe@acmeai.example.com'
      });

      expect(updatedRecord2.followUp2.status).toBe('SENT');
      expect(updatedRecord2.followUp2.sentAt).toBeDefined();
      expect(updatedRecord2.campaignStatus).toBe('FOLLOW_UP_2_SENT');
    });
  });

  describe('3. Reply Handling & Automated Follow-up Scheduler', () => {
    it('should halt follow-ups when contact replies', async () => {
      const pastTime = new Date(Date.now() - 5 * 24 * 60 * 60 * 1000); // 5 days ago
      const record = await OutreachRecord.create({
        companyId: testCompany._id,
        companyName: testCompany.companyName,
        companyWebsite: testCompany.website,
        contactId: testContact._id,
        contactName: testContact.name,
        recipientEmail: 'jane.doe@acmeai.example.com',
        initialEmail: {
          scheduledAt: pastTime,
          sentAt: pastTime,
          status: 'SENT'
        },
        followUp1: {
          scheduledAt: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000), // Due yesterday
          status: 'PENDING'
        },
        followUp2: {
          scheduledAt: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000),
          status: 'PENDING'
        },
        replyStatus: 'REPLIED', // Contact has replied!
        campaignStatus: 'REPLIED'
      });

      await processAutomatedFollowUps();

      const freshRecord = await OutreachRecord.findById(record._id);
      // Follow-up 1 should remain PENDING (not sent because contact replied)
      expect(freshRecord.followUp1.status).toBe('PENDING');
      expect(freshRecord.replyStatus).toBe('REPLIED');
    });

    it('should allow updating reply status via updateReplyStatus', async () => {
      const record = await OutreachRecord.create({
        companyId: testCompany._id,
        companyName: testCompany.companyName,
        recipientEmail: 'jane.doe@acmeai.example.com',
        initialEmail: { status: 'SENT', sentAt: new Date() },
        replyStatus: 'NO_REPLY',
        campaignStatus: 'INITIAL_SENT'
      });

      const replied = await updateReplyStatus(record._id, 'REPLIED');
      expect(replied.replyStatus).toBe('REPLIED');
      expect(replied.campaignStatus).toBe('REPLIED');
      expect(replied.repliedAt).toBeDefined();

      const noReply = await updateReplyStatus(record._id, 'NO_REPLY');
      expect(noReply.replyStatus).toBe('NO_REPLY');
      expect(noReply.campaignStatus).toBe('INITIAL_SENT');
      expect(noReply.repliedAt).toBeNull();
    });
  });

  describe('4. Excel Export & Multi-Sheet Report Generation', () => {
    it('should generate an Excel report with all 3 sheets and required columns', async () => {
      const sentDate = new Date(2026, 7, 31, 10, 30);
      const f1Date = new Date(2026, 8, 3, 10, 30);
      const f2Date = new Date(2026, 8, 8, 10, 30);

      await OutreachRecord.create({
        companyId: testCompany._id,
        companyName: 'Acme AI Systems',
        companyWebsite: 'https://acmeai.example.com',
        contactId: testContact._id,
        contactName: 'Jane Doe',
        contactDesignation: 'CTO',
        recipientEmail: 'jane.doe@acmeai.example.com',
        cc: ['manager@acmeai.example.com', 'sales@acmeai.example.com'],
        emailSubject: 'AI Collaboration Hook',
        emailType: 'INITIAL',
        initialEmail: {
          scheduledAt: sentDate,
          sentAt: sentDate,
          status: 'SENT'
        },
        followUp1: {
          scheduledAt: f1Date,
          sentAt: f1Date,
          status: 'SENT'
        },
        followUp2: {
          scheduledAt: f2Date,
          sentAt: null,
          status: 'PENDING'
        },
        lastContactedAt: f1Date,
        replyStatus: 'NO_REPLY',
        campaignStatus: 'FOLLOW_UP_1_SENT'
      });

      const { buffer, filename } = await generateOutreachExcelBuffer();

      expect(buffer).toBeDefined();
      expect(Buffer.isBuffer(buffer)).toBe(true);
      expect(filename).toContain('AI_Outreach_Report_');

      // Parse the generated XLSX buffer to verify contents
      const wb = XLSX.read(buffer, { type: 'buffer' });
      expect(wb.SheetNames).toEqual(['Outreach Summary', 'Follow-up Tracking', 'Summary']);

      // 1. Verify Sheet 1: Outreach Summary
      const ws1 = wb.Sheets['Outreach Summary'];
      const data1 = XLSX.utils.sheet_to_json(ws1);
      expect(data1.length).toBe(1);
      const row = data1[0];

      expect(row['Company Name']).toBe('Acme AI Systems');
      expect(row['Company Website']).toBe('https://acmeai.example.com');
      expect(row['Contact Name']).toBe('Jane Doe');
      expect(row['Designation']).toBe('CTO');
      expect(row['Recipient Email']).toBe('jane.doe@acmeai.example.com');
      expect(row['CC']).toBe('manager@acmeai.example.com, sales@acmeai.example.com');
      expect(row['Email Subject']).toBe('AI Collaboration Hook');
      expect(row['Initial Email Sent Date']).toBe('31-Aug-2026');
      expect(row['Initial Email Sent Time']).toBe('10:30 AM');
      expect(row['Initial Email Status']).toBe('SENT');
      expect(row['Follow-up 1 Sent Date']).toBe('03-Sep-2026');
      expect(row['Follow-up 1 Status']).toBe('SENT');
      expect(row['Follow-up 2 Status']).toBe('PENDING');
      expect(row['Reply Status']).toBe('NO_REPLY');
      expect(row['Campaign Status']).toBe('FOLLOW_UP_1_SENT');

      // 2. Verify Sheet 2: Follow-up Tracking
      const ws2 = wb.Sheets['Follow-up Tracking'];
      const data2 = XLSX.utils.sheet_to_json(ws2);
      expect(data2.length).toBe(1);

      // 3. Verify Sheet 3: Summary Analytics
      const ws3 = wb.Sheets['Summary'];
      const data3 = XLSX.utils.sheet_to_json(ws3);
      expect(data3.length).toBeGreaterThan(5);

      const metricMap = {};
      data3.forEach(m => { metricMap[m.Metric] = m.Value; });
      expect(metricMap['Total Outreach Records']).toBe(1);
      expect(metricMap['Total Initial Emails Sent']).toBe(1);
      expect(metricMap['Total Follow-up 1 Sent']).toBe(1);
      expect(metricMap['Total Follow-up 2 Sent']).toBe(0);
    });
  });

  describe('5. REST API Integration Endpoints', () => {
    beforeEach(async () => {
      await OutreachRecord.create({
        companyId: testCompany._id,
        companyName: 'Acme AI Systems',
        recipientEmail: 'jane.doe@acmeai.example.com',
        initialEmail: { status: 'SENT', sentAt: new Date() },
        replyStatus: 'NO_REPLY',
        campaignStatus: 'INITIAL_SENT'
      });
    });

    it('GET /api/outreach/records should return tracking records', async () => {
      const res = await request(app).get('/api/outreach/records').expect(200);
      expect(res.body.success).toBe(true);
      expect(Array.isArray(res.body.data)).toBe(true);
      expect(res.body.data.length).toBe(1);
      expect(res.body.data[0].recipientEmail).toBe('jane.doe@acmeai.example.com');
    });

    it('GET /api/outreach/stats should return tracking stats', async () => {
      const res = await request(app).get('/api/outreach/stats').expect(200);
      expect(res.body.success).toBe(true);
      expect(res.body.data.totalRecords).toBe(1);
      expect(res.body.data.initialSent).toBe(1);
    });

    it('PATCH /api/outreach/records/:id/reply should update reply status', async () => {
      const listRes = await request(app).get('/api/outreach/records');
      const recordId = listRes.body.data[0]._id;

      const res = await request(app)
        .patch(`/api/outreach/records/${recordId}/reply`)
        .send({ replyStatus: 'REPLIED' })
        .expect(200);

      expect(res.body.success).toBe(true);
      expect(res.body.data.replyStatus).toBe('REPLIED');
      expect(res.body.data.campaignStatus).toBe('REPLIED');
    });

    it('GET /api/outreach/export should stream Excel file download', async () => {
      const res = await request(app)
        .get('/api/outreach/export')
        .buffer(true)
        .parse((res, callback) => {
          const data = [];
          res.on('data', (chunk) => { data.push(chunk); });
          res.on('end', () => { callback(null, Buffer.concat(data)); });
        })
        .expect('Content-Type', /spreadsheetml\.sheet/)
        .expect(200);

      expect(res.headers['content-disposition']).toContain('AI_Outreach_Report_');
      expect(res.body).toBeDefined();

      const wb = XLSX.read(res.body, { type: 'buffer' });
      expect(wb.SheetNames).toEqual(['Outreach Summary', 'Follow-up Tracking', 'Summary']);
    });
  });
});
