const XLSX = require('xlsx');

jest.mock('../../models/Company', () => ({
  find: jest.fn().mockReturnValue({ select: jest.fn().mockReturnValue({ lean: jest.fn().mockResolvedValue([]) }) })
}));

const { processExcel, normalizeRow } = require('../excelService');

const createExcelBuffer = (rows, headers) => {
  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.aoa_to_sheet([headers, ...rows]);
  XLSX.utils.book_append_sheet(wb, ws, 'Sheet1');
  return XLSX.write(wb, { type: 'buffer', bookType: 'xlsx' });
};

const REQUIRED_HEADERS = ['Company Name', 'Website'];
const ALL_HEADERS = ['Company Name', 'Website', 'Industry', 'Country'];

describe('excelService', () => {
  describe('normalizeRow', () => {
    test('normalizes company name and website', () => {
      const raw = { 'Company Name': '  ABC Pharma  ', 'Website': 'https://ABCPharma.com/' };
      const result = normalizeRow(raw);
      expect(result.companyName).toBe('ABC Pharma');
      expect(result.normalizedWebsite).toBe('https://abcpharma.com');
    });
  });

  describe('processExcel', () => {
    test('processes valid Excel file', async () => {
      const buffer = createExcelBuffer(
        [['ABC Pharma', 'https://abcpharma.com'], ['XYZ Health', 'https://xyzhealth.com']],
        REQUIRED_HEADERS
      );
      const result = await processExcel(buffer, 'test.xlsx');
      expect(result.summary.total).toBe(2);
      expect(result.summary.valid).toBe(2);
      expect(result.summary.invalid).toBe(0);
    });

    test('handles missing required column', async () => {
      const buffer = createExcelBuffer(
        [['ABC Pharma', 'Pharma']],
        ['Company Name', 'Industry']
      );
      await expect(processExcel(buffer, 'test.xlsx')).rejects.toThrow('Missing required columns: Website');
    });

    test('handles empty Excel', async () => {
      const buffer = createExcelBuffer([], REQUIRED_HEADERS);
      await expect(processExcel(buffer, 'test.xlsx')).rejects.toThrow('Excel file is empty');
    });

    test('validates invalid URLs', async () => {
      const buffer = createExcelBuffer(
        [['ABC Pharma', 'not-a-url']],
        REQUIRED_HEADERS
      );
      const result = await processExcel(buffer, 'test.xlsx');
      expect(result.summary.invalid).toBe(1);
      expect(result.rows[0].validationErrors).toContain('Invalid website URL');
    });

    test('handles empty rows gracefully', async () => {
      const buffer = createExcelBuffer(
        [['ABC Pharma', 'https://abc.com'], ['', '']],
        REQUIRED_HEADERS
      );
      const result = await processExcel(buffer, 'test.xlsx');
      expect(result.summary.valid).toBe(1);
      expect(result.summary.invalid).toBe(1);
    });

    test('detects duplicate company names (case-insensitive)', async () => {
      const buffer = createExcelBuffer(
        [['ABC Pharma', 'https://abc.com'], ['abc pharma', 'https://abc2.com']],
        REQUIRED_HEADERS
      );
      const result = await processExcel(buffer, 'test.xlsx');
      expect(result.summary.valid).toBe(1);
      expect(result.summary.duplicates).toBe(1);
    });

    test('detects duplicate websites after normalization', async () => {
      const buffer = createExcelBuffer(
        [['ABC Pharma', 'https://abc.com'], ['XYZ Pharma', 'https://ABC.COM/']],
        REQUIRED_HEADERS
      );
      const result = await processExcel(buffer, 'test.xlsx');
      expect(result.summary.valid).toBe(1);
      expect(result.summary.duplicates).toBe(1);
    });

    test('normalizes URLs without protocol', async () => {
      const buffer = createExcelBuffer(
        [['ABC Pharma', 'abc.com']],
        REQUIRED_HEADERS
      );
      const result = await processExcel(buffer, 'test.xlsx');
      expect(result.rows[0].normalizedWebsite).toBe('https://abc.com');
    });

    test('handles optional columns', async () => {
      const buffer = createExcelBuffer(
        [['ABC Pharma', 'https://abc.com', 'Pharma', 'India']],
        ALL_HEADERS
      );
      const result = await processExcel(buffer, 'test.xlsx');
      expect(result.rows[0].industry).toBe('Pharma');
      expect(result.rows[0].country).toBe('India');
    });
  });
});
