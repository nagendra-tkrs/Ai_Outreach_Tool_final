const Company = require('../models/Company');
const ImportBatch = require('../models/ImportBatch');

const confirmImport = async (batchId) => {
  const batch = await ImportBatch.findById(batchId);
  if (!batch) {
    throw Object.assign(new Error('Import batch not found'), { status: 404 });
  }

  if (batch.status === 'completed') {
    throw Object.assign(new Error('This import has already been completed'), { status: 409 });
  }

  if (batch.status !== 'uploaded') {
    throw Object.assign(new Error('Import batch cannot be confirmed'), { status: 400 });
  }

  const validRows = batch.rows.filter(r => r.status === 'valid');
  if (validRows.length === 0) {
    throw Object.assign(new Error('No valid rows to import'), { status: 400 });
  }

  const imported = [];
  const skipped = [];

  for (const row of validRows) {
    const existing = await Company.findOne({ normalizedWebsite: row.normalizedWebsite });
    if (existing) {
      skipped.push({ ...row, skipReason: 'Already exists in database' });
      continue;
    }

    const company = await Company.create({
      companyName: row.companyName,
      website: row.website,
      normalizedWebsite: row.normalizedWebsite,
      industry: row.industry || '',
      country: row.country || '',
      contactName: row.contactName || '',
      contactEmail: row.contactEmail || '',
      revenue: row.revenue || '',
      employeeCount: row.employeeCount || '',
      notes: row.notes || '',
      source: 'bulk',
      importBatchId: batch._id
    });
    imported.push(company);
  }

  batch.importedRows = imported.length;
  batch.status = 'completed';
  await batch.save();

  return {
    batchId: batch._id,
    imported: imported.length,
    skipped: skipped.length,
    total: batch.totalRows
  };
};

const getBatch = async (batchId) => {
  const batch = await ImportBatch.findById(batchId);
  if (!batch) {
    throw Object.assign(new Error('Import batch not found'), { status: 404 });
  }
  return batch;
};

const listCompanies = async (page = 1, limit = 50, search = '') => {
  const query = {};
  if (search) {
    query.$or = [
      { companyName: { $regex: search, $options: 'i' } },
      { website: { $regex: search, $options: 'i' } },
      { industry: { $regex: search, $options: 'i' } },
      { country: { $regex: search, $options: 'i' } }
    ];
  }

  const total = await Company.countDocuments(query);
  const companies = await Company.find(query)
    .sort({ createdAt: -1 })
    .skip((page - 1) * limit)
    .limit(limit)
    .lean();

  return {
    companies,
    pagination: {
      total,
      page,
      limit,
      pages: Math.ceil(total / limit)
    }
  };
};

module.exports = { confirmImport, getBatch, listCompanies };
