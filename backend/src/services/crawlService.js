const Company = require('../models/Company');
const CrawledPage = require('../models/CrawledPage');
const ResearchJob = require('../models/ResearchJob');
const { crawlCompany, getConfig } = require('../crawler/orchestrator');

const startCrawl = async (companyId) => {
  return crawlCompany(companyId);
};

const getCrawlStatus = async (companyId) => {
  const company = await Company.findById(companyId);
  if (!company) throw Object.assign(new Error('Company not found'), { status: 404 });

  const latestJob = await ResearchJob.findOne({ companyId, type: 'website_crawl' })
    .sort({ createdAt: -1 })
    .lean();

  return {
    crawlStatus: company.crawlStatus,
    job: latestJob || null
  };
};

const getCrawledPages = async (companyId, page = 1, limit = 50, status = null) => {
  const company = await Company.findById(companyId);
  if (!company) throw Object.assign(new Error('Company not found'), { status: 404 });

  const query = { companyId };
  if (status) {
    query.crawlStatus = status;
  }

  const total = await CrawledPage.countDocuments(query);
  const pages = await CrawledPage.find(query)
    .sort({ depth: 1, crawlStatus: 1, pageType: 1 })
    .skip((page - 1) * limit)
    .limit(limit)
    .lean();

  return {
    pages,
    pagination: { total, page, limit, pages: Math.ceil(total / limit) }
  };
};

const getCrawledPageContent = async (companyId, pageId) => {
  const page = await CrawledPage.findOne({ _id: pageId, companyId }).lean();
  if (!page) throw Object.assign(new Error('Page not found'), { status: 404 });
  return page;
};

module.exports = { startCrawl, getCrawlStatus, getCrawledPages, getCrawledPageContent };
