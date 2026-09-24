const mongoose = require('mongoose');

const importBatchSchema = new mongoose.Schema({
  originalFilename: {
    type: String,
    required: true
  },
  totalRows: {
    type: Number,
    required: true
  },
  validRows: {
    type: Number,
    required: true
  },
  invalidRows: {
    type: Number,
    required: true
  },
  duplicateRows: {
    type: Number,
    required: true
  },
  existingInDbRows: {
    type: Number,
    required: true
  },
  importedRows: {
    type: Number,
    default: 0
  },
  status: {
    type: String,
    enum: ['uploaded', 'confirmed', 'completed'],
    default: 'uploaded'
  },
  rows: [{
    companyName: String,
    website: String,
    normalizedWebsite: String,
    industry: String,
    country: String,
    contactName: String,
    contactEmail: String,
    revenue: String,
    employeeCount: String,
    notes: String,
    rowNumber: Number,
    status: {
      type: String,
      enum: ['valid', 'invalid', 'duplicate_in_file', 'existing_in_db'],
      default: 'valid'
    },
    validationErrors: [String]
  }]
}, {
  timestamps: true
});

module.exports = mongoose.model('ImportBatch', importBatchSchema);
