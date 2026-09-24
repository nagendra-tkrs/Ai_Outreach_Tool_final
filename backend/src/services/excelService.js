const XLSX = require('xlsx');
const { REQUIRED_COLUMNS, OPTIONAL_COLUMNS, normalizeWebsite, isValidUrl, normalizeCompanyName, validateRow } = require('../utils/validators');
const Company = require('../models/Company');

const FIELD_MAP = {
  'Company Name': 'companyName',
  'Website': 'website',
  'Industry': 'industry',
  'Country': 'country',
  'Contact Name': 'contactName',
  'Contact Email': 'contactEmail',
  'Revenue': 'revenue',
  'Employee Count': 'employeeCount',
  'Notes': 'notes',
  'Source': 'source'
};

const parseExcelFile = (buffer) => {
  const workbook = XLSX.read(buffer, { type: 'buffer' });
  const sheetName = workbook.SheetNames[0];
  if (!sheetName) {
    throw new Error('Excel file contains no sheets');
  }
  const sheet = workbook.Sheets[sheetName];
  const data = XLSX.utils.sheet_to_json(sheet, { defval: '' });
  return { data, sheetName };
};

const validateHeaders = (headers) => {
  const missing = REQUIRED_COLUMNS.filter(col => !headers.includes(col));
  if (missing.length > 0) {
    throw new Error(`Missing required columns: ${missing.join(', ')}`);
  }
};

const normalizeRow = (rawRow) => {
  const normalized = {};
  for (const [header, field] of Object.entries(FIELD_MAP)) {
    normalized[field] = rawRow[header] || '';
  }
  normalized.companyName = normalizeCompanyName(normalized.companyName);
  normalized.website = normalized.website.trim();
  normalized.normalizedWebsite = normalizeWebsite(normalized.website);
  return normalized;
};

const processExcel = async (buffer, originalFilename) => {
  const { data } = parseExcelFile(buffer);

  if (data.length === 0) {
    throw new Error('Excel file is empty or has no data rows');
  }

  const headers = Object.keys(data[0]);
  validateHeaders(headers);

  const normalizedRows = data.map((row, index) => ({
    ...normalizeRow(row),
    rowNumber: index + 2
  }));

  const seenNames = new Map();
  const seenWebsites = new Map();

  const existingCompanies = await Company.find({}).select('normalizedWebsite').lean();
  const existingWebsiteSet = new Set(existingCompanies.map(c => c.normalizedWebsite));

  const processedRows = normalizedRows.map(row => {
    const errors = validateRow(row);
    let status = errors.length > 0 ? 'invalid' : 'valid';

    if (status === 'valid') {
      const nameLower = row.companyName.toLowerCase();
      if (seenNames.has(nameLower)) {
        status = 'duplicate_in_file';
        errors.push(`Duplicate company name (also row ${seenNames.get(nameLower)})`);
      } else {
        seenNames.set(nameLower, row.rowNumber);
      }
    }

    if (status === 'valid') {
      if (seenWebsites.has(row.normalizedWebsite)) {
        status = 'duplicate_in_file';
        errors.push(`Duplicate website (also row ${seenWebsites.get(row.normalizedWebsite)})`);
      } else {
        seenWebsites.set(row.normalizedWebsite, row.rowNumber);
      }
    }

    if (status === 'valid' && existingWebsiteSet.has(row.normalizedWebsite)) {
      status = 'existing_in_db';
      errors.push('Company already exists in database');
    }

    return { ...row, status, validationErrors: errors };
  });

  const summary = {
    total: processedRows.length,
    valid: processedRows.filter(r => r.status === 'valid').length,
    invalid: processedRows.filter(r => r.status === 'invalid').length,
    duplicates: processedRows.filter(r => r.status === 'duplicate_in_file').length,
    existingInDb: processedRows.filter(r => r.status === 'existing_in_db').length
  };

  return {
    originalFilename,
    summary,
    rows: processedRows
  };
};

module.exports = { parseExcelFile, validateHeaders, normalizeRow, validateRow, processExcel };
