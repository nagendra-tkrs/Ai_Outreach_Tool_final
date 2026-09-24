const express = require('express');
const router = express.Router();
const { trackOpen, trackClick } = require('../controllers/trackingController');

router.get('/open/:messageId', trackOpen);
router.get('/click/:messageId', trackClick);

module.exports = router;
