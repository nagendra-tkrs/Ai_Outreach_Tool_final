const express = require('express');
const router = express.Router();
const { getSettings, updateSettings, testSmtp } = require('../controllers/settingsController');

router.get('/', getSettings);
router.post('/', updateSettings);
router.post('/test-smtp', testSmtp);

module.exports = router;
