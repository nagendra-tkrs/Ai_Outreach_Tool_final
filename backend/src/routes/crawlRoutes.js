const express = require('express');
const router = express.Router({ mergeParams: true });
const { triggerCrawl, getCrawlStatusForCompany, getCompanyPages, getPageContent } = require('../controllers/crawlController');

router.post('/crawl', triggerCrawl);
router.get('/crawl', getCrawlStatusForCompany);
router.get('/pages', getCompanyPages);
router.get('/pages/:pageId', getPageContent);

module.exports = router;
