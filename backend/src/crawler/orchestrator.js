const Company = require('../models/Company');
const CrawledPage = require('../models/CrawledPage');
const ResearchJob = require('../models/ResearchJob');
const { fetchPage } = require('./fetcher');
const { extractContent } = require('./contentExtractor');
const { extractLinks } = require('./linkExtractor');
const { classifyPage, getPagePriority } = require('./pageClassifier');
const { normalizeUrl, extractDomain, isSameDomain, filterSameDomainLinks } = require('./urlUtils');
const { fetchSitemap } = require('./sitemapParser');
const { isAllowed } = require('./robotsHandler');
const { validateCrawledPage } = require('./contentValidator');

const getConfig = () => ({
  maxPagesPerCompany: parseInt(process.env.MAX_PAGES_PER_COMPANY, 10) || 25,
  maxCrawlDepth: parseInt(process.env.MAX_CRAWL_DEPTH, 10) || 2,
  requestTimeout: parseInt(process.env.CRAWLER_TIMEOUT_MS, 10) || parseInt(process.env.REQUEST_TIMEOUT, 10) || 10000,
  concurrency: parseInt(process.env.CRAWL_CONCURRENCY, 10) || 3
});

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

const runWithConcurrency = async (tasks, concurrency) => {
  const results = [];
  let index = 0;

  const worker = async () => {
    while (index < tasks.length) {
      const i = index++;
      results[i] = await tasks[i]();
    }
  };

  const workers = Array(Math.min(concurrency, tasks.length)).fill(null).map(() => worker());
  await Promise.all(workers);
  return results;
};

const crawlCompany = async (companyId) => {
  const config = getConfig();

  const company = await Company.findById(companyId);
  if (!company) throw Object.assign(new Error('Company not found'), { status: 404 });
  if (!company.website) throw Object.assign(new Error('Company has no website'), { status: 400 });

  const baseDomain = extractDomain(company.website);
  const normalizedBase = normalizeUrl(company.website);

  const existingJob = await ResearchJob.findOne({ companyId, type: 'website_crawl', status: 'running' });
  if (existingJob) throw Object.assign(new Error('Crawl already in progress'), { status: 409 });

  await Company.findByIdAndUpdate(companyId, { crawlStatus: 'crawling' });

  const job = await ResearchJob.create({
    companyId,
    type: 'website_crawl',
    status: 'running',
    startedAt: new Date()
  });

  console.log(`[CRAWLER] Starting crawl for: "${company.companyName}" (${company.website})`);

  try {
    const visited = new Set();
    const queue = [{ url: normalizedBase, depth: 0, priority: 100 }];
    const discoveredUrls = new Set();
    discoveredUrls.add(normalizedBase);
    let pagesCrawled = 0;
    let pagesFailed = 0;
    let pagesBlocked = 0;

    // Seed common leadership and about paths for high-probability discovery
    const seedPaths = ['/about', '/about-us', '/team', '/our-team', '/leadership', '/management', '/people', '/contact', '/contact-us', '/products', '/services'];
    for (const path of seedPaths) {
      try {
        const seedUrl = normalizeUrl(new URL(path, normalizedBase).href);
        if (seedUrl && !discoveredUrls.has(seedUrl)) {
          discoveredUrls.add(seedUrl);
          queue.push({ url: seedUrl, depth: 1, priority: getPagePriority(seedUrl) });
        }
      } catch {
        // ignore invalid URL
      }
    }

    // Discover from sitemap
    try {
      const sitemapUrls = await fetchSitemap(company.website);
      for (const sUrl of sitemapUrls) {
        const nUrl = normalizeUrl(sUrl);
        if (nUrl && isSameDomain(nUrl, baseDomain) && !discoveredUrls.has(nUrl)) {
          discoveredUrls.add(nUrl);
          queue.push({ url: nUrl, depth: 1, priority: getPagePriority(nUrl) });
        }
      }
    } catch {
      // sitemap not critical
    }

    // BFS crawl with priority queueing
    while (queue.length > 0 && pagesCrawled < config.maxPagesPerCompany) {
      // Sort queue by priority descending so high-value leadership/about pages are crawled first
      queue.sort((a, b) => (b.priority || 0) - (a.priority || 0) || a.depth - b.depth);

      const batch = [];
      while (queue.length > 0 && batch.length < config.concurrency) {
        const item = queue.shift();
        if (visited.has(item.url)) continue;
        if (item.depth > config.maxCrawlDepth) continue;
        if (pagesCrawled >= config.maxPagesPerCompany) break;
        batch.push(item);
      }

      if (batch.length === 0) break;

      const results = await runWithConcurrency(
        batch.map(item => async () => {
          visited.add(item.url);

          // 1. Robots.txt check
          try {
            const allowed = await isAllowed(item.url);
            if (!allowed) {
              pagesBlocked++;
              console.log(`[CRAWLER] Company: ${company.companyName} | URL: ${item.url} | Crawl Status: ROBOTS_DISALLOWED | Error Reason: Disallowed by robots.txt`);
              await CrawledPage.findOneAndUpdate(
                { companyId, normalizedUrl: item.url },
                {
                  companyId,
                  url: item.url,
                  normalizedUrl: item.url,
                  statusCode: 403,
                  depth: item.depth,
                  pageType: classifyPage(item.url),
                  crawlStatus: 'robots_disallowed',
                  contentAvailable: false,
                  contentQuality: 'error',
                  error: 'Disallowed by robots.txt',
                  errorReason: 'Disallowed by robots.txt',
                  crawledAt: new Date()
                },
                { upsert: true, new: true }
              );
              return null;
            }
          } catch (robotsErr) {
            console.warn(`[CRAWLER] Robots.txt check warning for ${item.url}:`, robotsErr.message);
          }

          // 2. Fetch page with retry & backoff
          let response;
          try {
            response = await fetchPage(item.url, {
              timeout: config.requestTimeout,
              maxRetries: 2
            });
          } catch (fetchErr) {
            const statusCode = fetchErr.statusCode || 0;
            const crawlStatus = fetchErr.crawlStatus || (statusCode === 403 ? 'blocked' : (statusCode === 429 ? 'rate_limited' : (statusCode === 404 ? 'not_found' : 'failed')));
            const isBlocked = crawlStatus === 'blocked' || crawlStatus === 'rate_limited' || statusCode === 403 || statusCode === 429;
            
            if (isBlocked) {
              pagesBlocked++;
            } else {
              pagesFailed++;
            }

            console.log(`[CRAWLER] Company: ${company.companyName} | URL: ${item.url} | HTTP Status: ${statusCode} | Crawl Status: ${crawlStatus.toUpperCase()} | Error Reason: ${fetchErr.errorReason || fetchErr.message}`);

            await CrawledPage.findOneAndUpdate(
              { companyId, normalizedUrl: item.url },
              {
                companyId,
                url: fetchErr.finalUrl || item.url,
                finalUrl: fetchErr.finalUrl || item.url,
                normalizedUrl: item.url,
                statusCode,
                contentType: fetchErr.contentType || '',
                depth: item.depth,
                pageType: classifyPage(item.url),
                crawlStatus,
                contentAvailable: false,
                contentQuality: 'error',
                error: fetchErr.message,
                errorReason: fetchErr.errorReason || fetchErr.message,
                isChallengePage: Boolean(fetchErr.isChallengePage || crawlStatus === 'blocked'),
                crawledAt: new Date()
              },
              { upsert: true, new: true }
            );

            return null;
          }

          // 3. Extract content & Validate HTML response
          const extracted = extractContent(response.body, response.finalUrl || item.url);
          const validation = validateCrawledPage({
            url: item.url,
            finalUrl: response.finalUrl,
            statusCode: response.statusCode,
            contentType: response.contentType,
            body: response.body,
            extracted,
            baseDomain
          });

          // 4. Handle invalid or challenge page
          if (!validation.isValid) {
            if (validation.crawlStatus === 'blocked') {
              pagesBlocked++;
            } else {
              pagesFailed++;
            }

            console.log(`[CRAWLER] Company: ${company.companyName} | URL: ${item.url} | Final URL: ${response.finalUrl} | HTTP Status: ${response.statusCode} | Crawl Status: ${validation.crawlStatus.toUpperCase()} | Error Reason: ${validation.errorReason}`);

            await CrawledPage.findOneAndUpdate(
              { companyId, normalizedUrl: item.url },
              {
                companyId,
                url: response.finalUrl || item.url,
                finalUrl: response.finalUrl || item.url,
                normalizedUrl: item.url,
                title: extracted.title,
                metaDescription: extracted.metaDescription,
                headings: extracted.headings,
                content: '', // Do NOT store bad/challenge content
                statusCode: response.statusCode,
                contentType: response.contentType,
                contentLength: (response.body || '').length,
                depth: item.depth,
                pageType: classifyPage(item.url, extracted.title, ''),
                wordCount: extracted.wordCount || 0,
                crawlStatus: validation.crawlStatus,
                contentAvailable: false,
                contentQuality: validation.contentQuality,
                error: validation.errorReason,
                errorReason: validation.errorReason,
                isChallengePage: validation.isChallengePage,
                crawledAt: new Date()
              },
              { upsert: true, new: true }
            );

            return null;
          }

          // 5. Save Valid Crawled Page
          const pageType = classifyPage(response.finalUrl || item.url, extracted.title, extracted.content);

          console.log(`[CRAWLER] Company: ${company.companyName} | URL: ${item.url} | Final URL: ${response.finalUrl} | HTTP Status: 200 | Content-Type: ${response.contentType} | Content Length: ${(response.body || '').length} | Crawl Status: SUCCESS | Word Count: ${extracted.wordCount}`);

          const savedPage = await CrawledPage.findOneAndUpdate(
            { companyId, normalizedUrl: item.url },
            {
              companyId,
              url: response.finalUrl || item.url,
              finalUrl: response.finalUrl || item.url,
              normalizedUrl: item.url,
              title: extracted.title,
              metaDescription: extracted.metaDescription,
              headings: extracted.headings,
              content: extracted.content,
              statusCode: response.statusCode,
              contentType: response.contentType,
              contentLength: (response.body || '').length,
              depth: item.depth,
              pageType,
              wordCount: extracted.wordCount,
              crawlStatus: 'completed',
              contentAvailable: true,
              contentQuality: 'valid',
              error: '',
              errorReason: '',
              isChallengePage: false,
              crawledAt: new Date()
            },
            { upsert: true, new: true }
          );

          pagesCrawled++;

          // Extract links for next crawl depth
          if (item.depth < config.maxCrawlDepth) {
            const links = extractLinks(response.body, response.finalUrl || item.url);
            for (const link of links) {
              if (!discoveredUrls.has(link) && discoveredUrls.size < config.maxPagesPerCompany * 2) {
                discoveredUrls.add(link);
                queue.push({ url: link, depth: item.depth + 1, priority: getPagePriority(link) });
              }
            }
          }

          return savedPage;
        }),
        config.concurrency
      );

      await sleep(150);
    }

    // Determine final job & company status
    let finalCompanyCrawlStatus = 'completed';
    if (pagesCrawled === 0) {
      if (pagesBlocked > 0) {
        finalCompanyCrawlStatus = 'blocked';
      } else {
        finalCompanyCrawlStatus = 'failed';
      }
    }

    job.status = pagesCrawled > 0 ? 'completed' : (pagesBlocked > 0 ? 'failed' : 'failed');
    job.completedAt = new Date();
    job.pagesDiscovered = discoveredUrls.size;
    job.pagesCrawled = pagesCrawled;
    job.pagesFailed = pagesFailed;
    job.pagesBlocked = pagesBlocked;
    if (pagesCrawled === 0) {
      job.error = pagesBlocked > 0 ? 'Website access blocked by bot protection / access controls' : 'Crawl completed with 0 accessible pages';
    }
    await job.save();

    await Company.findByIdAndUpdate(companyId, {
      crawlStatus: finalCompanyCrawlStatus,
      lastCrawlJobId: job._id
    });

    console.log(`[CRAWLER] Finished crawl for "${company.companyName}": ${pagesCrawled} crawled, ${pagesBlocked} blocked, ${pagesFailed} failed, status: ${finalCompanyCrawlStatus}`);

    return {
      jobId: job._id,
      status: job.status,
      crawlStatus: finalCompanyCrawlStatus,
      pagesDiscovered: discoveredUrls.size,
      pagesCrawled,
      pagesFailed,
      pagesBlocked
    };
  } catch (err) {
    job.status = 'failed';
    job.error = err.message;
    job.completedAt = new Date();
    await job.save();

    await Company.findByIdAndUpdate(companyId, { crawlStatus: 'failed' });

    console.error(`[CRAWLER] Fatal crawl error for "${company.companyName}":`, err.message);
    throw err;
  }
};

module.exports = { crawlCompany, getConfig };
