const XLSX = require('xlsx');
const { normalizeWebsite, isValidUrl, normalizeCompanyName, validateRow } = require('../validators');

describe('validators', () => {
  describe('normalizeWebsite', () => {
    test('adds https:// if missing', () => {
      expect(normalizeWebsite('example.com')).toBe('https://example.com');
    });

    test('preserves https://', () => {
      expect(normalizeWebsite('https://example.com')).toBe('https://example.com');
    });

    test('preserves http://', () => {
      expect(normalizeWebsite('http://example.com')).toBe('http://example.com');
    });

    test('removes trailing slash', () => {
      expect(normalizeWebsite('https://example.com/')).toBe('https://example.com');
    });

    test('removes multiple trailing slashes', () => {
      expect(normalizeWebsite('https://example.com///')).toBe('https://example.com');
    });

    test('lowercases the URL', () => {
      expect(normalizeWebsite('https://Example.COM')).toBe('https://example.com');
    });

    test('trims whitespace', () => {
      expect(normalizeWebsite('  https://example.com  ')).toBe('https://example.com');
    });

    test('returns empty string for empty input', () => {
      expect(normalizeWebsite('')).toBe('');
    });

    test('returns empty string for null', () => {
      expect(normalizeWebsite(null)).toBe('');
    });

    test('handles URL with path', () => {
      expect(normalizeWebsite('https://example.com/page')).toBe('https://example.com/page');
    });
  });

  describe('isValidUrl', () => {
    test('valid https URL', () => {
      expect(isValidUrl('https://example.com')).toBe(true);
    });

    test('valid http URL', () => {
      expect(isValidUrl('http://example.com')).toBe(true);
    });

    test('URL without protocol (auto-adds https)', () => {
      expect(isValidUrl('example.com')).toBe(true);
    });

    test('empty string is invalid', () => {
      expect(isValidUrl('')).toBe(false);
    });

    test('null is invalid', () => {
      expect(isValidUrl(null)).toBe(false);
    });

    test('garbage text is invalid', () => {
      expect(isValidUrl('not-a-url')).toBe(false);
    });

    test('URL with spaces is invalid', () => {
      expect(isValidUrl('exam ple.com')).toBe(false);
    });
  });

  describe('normalizeCompanyName', () => {
    test('trims whitespace', () => {
      expect(normalizeCompanyName('  ABC Pharma  ')).toBe('ABC Pharma');
    });

    test('collapses multiple spaces', () => {
      expect(normalizeCompanyName('ABC  Pharma')).toBe('ABC Pharma');
    });

    test('returns empty string for null', () => {
      expect(normalizeCompanyName(null)).toBe('');
    });

    test('returns empty string for empty', () => {
      expect(normalizeCompanyName('')).toBe('');
    });
  });

  describe('validateRow', () => {
    test('valid row has no errors', () => {
      const row = { companyName: 'ABC', website: 'https://abc.com', normalizedWebsite: 'https://abc.com' };
      expect(validateRow(row)).toEqual([]);
    });

    test('missing company name', () => {
      const row = { companyName: '', website: 'https://abc.com' };
      const errors = validateRow(row);
      expect(errors).toContain('Company Name is required');
    });

    test('missing website', () => {
      const row = { companyName: 'ABC', website: '' };
      const errors = validateRow(row);
      expect(errors).toContain('Website is required');
    });

    test('invalid URL', () => {
      const row = { companyName: 'ABC', website: 'not-a-url' };
      const errors = validateRow(row);
      expect(errors).toContain('Invalid website URL');
    });
  });
});
