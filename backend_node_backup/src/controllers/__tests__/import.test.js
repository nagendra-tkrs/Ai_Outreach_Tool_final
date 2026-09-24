const XLSX = require('xlsx');
const request = require('supertest');
const mongoose = require('mongoose');
const { app } = require('../../server');
const Company = require('../../models/Company');
const ImportBatch = require('../../models/ImportBatch');

const createExcelBuffer = (rows, headers) => {
  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.aoa_to_sheet([headers, ...rows]);
  XLSX.utils.book_append_sheet(wb, ws, 'Sheet1');
  return XLSX.write(wb, { type: 'buffer', bookType: 'xlsx' });
};

const HEADERS = ['Company Name', 'Website'];

beforeAll(async () => {
  const testUri = process.env.MONGODB_TEST_URI || 'mongodb://127.0.0.1:27017/ai_client_outreach_test';
  await mongoose.connect(testUri);
});

afterAll(async () => {
  await Company.deleteMany({});
  await ImportBatch.deleteMany({});
});

beforeEach(async () => {
  await Company.deleteMany({});
  await ImportBatch.deleteMany({});
});

describe('POST /api/import/excel', () => {
  test('uploads valid Excel', async () => {
    const buffer = createExcelBuffer(
      [['ABC Pharma', 'https://abc.com'], ['XYZ Health', 'https://xyz.com']],
      HEADERS
    );

    const res = await request(app)
      .post('/api/import/excel')
      .attach('file', buffer, { filename: 'test.xlsx', contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      .expect(200);

    expect(res.body.success).toBe(true);
    expect(res.body.data.summary.total).toBe(2);
    expect(res.body.data.summary.valid).toBe(2);
    expect(res.body.data.batchId).toBeDefined();
  });

  test('rejects when no file uploaded', async () => {
    const res = await request(app)
      .post('/api/import/excel')
      .expect(400);

    expect(res.body.success).toBe(false);
    expect(res.body.message).toBe('No file uploaded');
  });
});

describe('POST /api/import/:id/confirm', () => {
  test('confirms and imports valid batch', async () => {
    const buffer = createExcelBuffer(
      [['ABC Pharma', 'https://abc.com'], ['XYZ Health', 'https://xyz.com']],
      HEADERS
    );

    const uploadRes = await request(app)
      .post('/api/import/excel')
      .attach('file', buffer, { filename: 'test.xlsx', contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      .expect(200);

    const batchId = uploadRes.body.data.batchId;

    const confirmRes = await request(app)
      .post(`/api/import/${batchId}/confirm`)
      .expect(200);

    expect(confirmRes.body.success).toBe(true);
    expect(confirmRes.body.data.imported).toBe(2);
    expect(confirmRes.body.data.skipped).toBe(0);
  });

  test('prevents double confirmation', async () => {
    const buffer = createExcelBuffer(
      [['ABC Pharma', 'https://abc.com']],
      HEADERS
    );

    const uploadRes = await request(app)
      .post('/api/import/excel')
      .attach('file', buffer, { filename: 'test.xlsx', contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      .expect(200);

    const batchId = uploadRes.body.data.batchId;

    await request(app)
      .post(`/api/import/${batchId}/confirm`)
      .expect(200);

    const res = await request(app)
      .post(`/api/import/${batchId}/confirm`)
      .expect(409);

    expect(res.body.success).toBe(false);
  });

  test('does not create duplicate companies in database', async () => {
    const buffer = createExcelBuffer(
      [['ABC Pharma', 'https://abc.com']],
      HEADERS
    );

    const uploadRes = await request(app)
      .post('/api/import/excel')
      .attach('file', buffer, { filename: 'test.xlsx', contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      .expect(200);

    const batchId = uploadRes.body.data.batchId;

    await request(app)
      .post(`/api/import/${batchId}/confirm`)
      .expect(200);

    const companies = await Company.find({});
    expect(companies.length).toBe(1);
  });

  test('returns 404 for non-existent batch', async () => {
    const fakeId = new mongoose.Types.ObjectId();
    const res = await request(app)
      .post(`/api/import/${fakeId}/confirm`)
      .expect(404);

    expect(res.body.success).toBe(false);
  });
});

describe('GET /api/companies', () => {
  test('returns paginated companies', async () => {
    const buffer = createExcelBuffer(
      [['ABC Pharma', 'https://abc.com'], ['XYZ Health', 'https://xyz.com']],
      HEADERS
    );

    const uploadRes = await request(app)
      .post('/api/import/excel')
      .attach('file', buffer, { filename: 'test.xlsx', contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      .expect(200);

    await request(app)
      .post(`/api/import/${uploadRes.body.data.batchId}/confirm`)
      .expect(200);

    const res = await request(app)
      .get('/api/companies')
      .expect(200);

    expect(res.body.success).toBe(true);
    expect(res.body.data.companies.length).toBe(2);
    expect(res.body.data.pagination.total).toBe(2);
  });

  test('searches companies', async () => {
    const buffer = createExcelBuffer(
      [['ABC Pharma', 'https://abc.com'], ['XYZ Health', 'https://xyz.com']],
      HEADERS
    );

    const uploadRes = await request(app)
      .post('/api/import/excel')
      .attach('file', buffer, { filename: 'test.xlsx', contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      .expect(200);

    await request(app)
      .post(`/api/import/${uploadRes.body.data.batchId}/confirm`)
      .expect(200);

    const res = await request(app)
      .get('/api/companies?search=ABC')
      .expect(200);

    expect(res.body.data.companies.length).toBe(1);
    expect(res.body.data.companies[0].companyName).toBe('ABC Pharma');
  });
});

describe('GET /api/health', () => {
  test('returns health status', async () => {
    const res = await request(app)
      .get('/api/health')
      .expect(200);

    expect(res.body.success).toBe(true);
    expect(res.body.message).toBe('AI Client Outreach API is running');
  });
});
