const express = require('express');
const router = express.Router({ mergeParams: true });
const { triggerResearch, getResearch } = require('../controllers/researchController');

router.post('/research', triggerResearch);
router.get('/research', getResearch);

module.exports = router;
