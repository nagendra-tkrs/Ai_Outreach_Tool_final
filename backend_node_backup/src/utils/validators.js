const REQUIRED_COLUMNS = ['Company Name', 'Website'];

const OPTIONAL_COLUMNS = [
  'Industry',
  'Country',
  'Contact Name',
  'Contact Email',
  'Revenue',
  'Employee Count',
  'Notes',
  'Source'
];

const normalizeWebsite = (url) => {
  if (!url || typeof url !== 'string') return '';
  let normalized = url.trim();
  normalized = normalized.replace(/\/+$/, '');
  if (!/^https?:\/\//i.test(normalized)) {
    normalized = 'https://' + normalized;
  }
  try {
    const parsed = new URL(normalized);
    normalized = parsed.origin + parsed.pathname.replace(/\/+$/, '') + parsed.search;
    return normalized.toLowerCase();
  } catch {
    return normalized.toLowerCase();
  }
};

const isValidUrl = (url) => {
  if (!url || typeof url !== 'string') return false;
  const trimmed = url.trim();
  if (!trimmed) return false;
  const withProtocol = /^https?:\/\//i.test(trimmed) ? trimmed : 'https://' + trimmed;
  try {
    const parsed = new URL(withProtocol);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false;
    if (!parsed.hostname.includes('.')) return false;
    return true;
  } catch {
    return false;
  }
};

const normalizeCompanyName = (name) => {
  if (!name || typeof name !== 'string') return '';
  return name.trim().replace(/\s+/g, ' ');
};

const validateRow = (row) => {
  const errors = [];
  if (!row.companyName) {
    errors.push('Company Name is required');
  }
  if (!row.website) {
    errors.push('Website is required');
  } else if (!isValidUrl(row.website)) {
    errors.push('Invalid website URL');
  }
  return errors;
};

module.exports = {
  REQUIRED_COLUMNS,
  OPTIONAL_COLUMNS,
  normalizeWebsite,
  isValidUrl,
  normalizeCompanyName,
  validateRow
};
