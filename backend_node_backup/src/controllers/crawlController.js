const { startCrawl, getCrawlStatus, getCrawledPages, getCrawledPageContent } = require('../services/crawlService');

const triggerCrawl = async (req, res, next) => {
  try {
    const { companyId } = req.params;
    const result = await startCrawl(companyId);
    res.status(200).json({ success: true, data: result });
  } catch (error) {
    next(error);
  }
};

const getCrawlStatusForCompany = async (req, res, next) => {
  try {
    const { companyId } = req.params;
    const result = await getCrawlStatus(companyId);
    res.status(200).json({ success: true, data: result });
  } catch (error) {
    next(error);
  }
};

const getCompanyPages = async (req, res, next) => {
  try {
    const { companyId } = req.params;
    const page = parseInt(req.query.page, 10) || 1;
    const limit = parseInt(req.query.limit, 10) || 50;
    const status = req.query.status || null;
    const result = await getCrawledPages(companyId, page, limit, status);
    res.status(200).json({ success: true, data: result });
  } catch (error) {
    next(error);
  }
};

const getPageContent = async (req, res, next) => {
  try {
    const { companyId, pageId } = req.params;
    const result = await getCrawledPageContent(companyId, pageId);
    res.status(200).json({ success: true, data: result });
  } catch (error) {
    next(error);
  }
};

module.exports = { triggerCrawl, getCrawlStatusForCompany, getCompanyPages, getPageContent };
