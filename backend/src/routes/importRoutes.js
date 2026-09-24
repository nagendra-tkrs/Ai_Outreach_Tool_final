const express = require('express');
const router = express.Router();
const upload = require('../middleware/upload');
const { uploadExcel, confirmBatchImport, getImportBatch } = require('../controllers/importController');

router.post('/excel', upload.single('file'), uploadExcel);
router.get('/:id', getImportBatch);
router.post('/:id/confirm', confirmBatchImport);

module.exports = router;
