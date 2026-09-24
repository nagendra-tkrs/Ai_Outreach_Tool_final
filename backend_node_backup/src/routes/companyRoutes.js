const express = require('express');
const router = express.Router();
const { getCompanies } = require('../controllers/importController');
const crawlRoutes = require('./crawlRoutes');
const researchRoutes = require('./researchRoutes');
const contactRoutes = require('./contactRoutes');
const outreachRoutes = require('./outreachRoutes');

router.get('/', getCompanies);
router.use('/:companyId', crawlRoutes);
router.use('/:companyId', researchRoutes);
router.use('/:companyId', contactRoutes);
router.use('/:companyId', outreachRoutes);

module.exports = router;

