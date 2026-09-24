const ImportBatch = require('../models/ImportBatch');
const { processExcel } = require('../services/excelService');
const { confirmImport, getBatch, listCompanies } = require('../services/importService');

const uploadExcel = async (req, res, next) => {
  try {
    if (!req.file) {
      return res.status(400).json({ success: false, message: 'No file uploaded' });
    }

    const result = await processExcel(req.file.buffer, req.file.originalname);

    const batch = await ImportBatch.create({
      originalFilename: result.originalFilename,
      totalRows: result.summary.total,
      validRows: result.summary.valid,
      invalidRows: result.summary.invalid,
      duplicateRows: result.summary.duplicates,
      existingInDbRows: result.summary.existingInDb,
      rows: result.rows
    });

    res.status(200).json({
      success: true,
      data: {
        batchId: batch._id,
        summary: result.summary,
        rows: result.rows
      }
    });
  } catch (error) {
    next(error);
  }
};

const confirmBatchImport = async (req, res, next) => {
  try {
    const { id } = req.params;
    const result = await confirmImport(id);
    res.status(200).json({
      success: true,
      message: 'Import completed successfully',
      data: result
    });
  } catch (error) {
    next(error);
  }
};

const getImportBatch = async (req, res, next) => {
  try {
    const batch = await getBatch(req.params.id);
    res.status(200).json({ success: true, data: batch });
  } catch (error) {
    next(error);
  }
};

const getCompanies = async (req, res, next) => {
  try {
    const page = parseInt(req.query.page) || 1;
    const limit = parseInt(req.query.limit) || 50;
    const search = req.query.search || '';
    const result = await listCompanies(page, limit, search);
    res.status(200).json({ success: true, data: result });
  } catch (error) {
    next(error);
  }
};

module.exports = { uploadExcel, confirmBatchImport, getImportBatch, getCompanies };
