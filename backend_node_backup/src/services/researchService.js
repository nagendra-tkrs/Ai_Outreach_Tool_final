const Company = require('../models/Company');
const CrawledPage = require('../models/CrawledPage');
const CompanyResearch = require('../models/CompanyResearch');
const { getAiConfig, callGemini, callOpenAI, callAI, generateFallbackResearch } = require('./aiService');
const { fetchCompanyPublicOverview } = require('./webSearchService');

const envInt = (name, fallback) => {
  const raw = process.env[name];
  if (raw === undefined || raw === null || raw === '') return fallback;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
};

/**
 * Run AI Research on a Company's crawled website pages or fallback public search sources
 * STRICT PROTECTION: Never send blocked, challenge, CAPTCHA, or error HTML to LLMs
 *
 * Lifecycle guarantees:
 *   - Company.researchStatus moves: pending -> researching -> completed | failed
 *   - A job can never remain permanently 'researching': any error or timeout is
 *     caught and the company is marked 'failed' so it can be safely retried.
 *   - RESEARCH_TIMEOUT_MS bounds the total wall-clock time of a research run.
 */
const runCompanyResearch = async (companyId) => {
  const company = await Company.findById(companyId);
  if (!company) {
    throw Object.assign(new Error('Company not found'), { status: 404 });
  }

  await Company.findByIdAndUpdate(companyId, { researchStatus: 'researching' });

  const state = { aborted: false };
  const researchTimeoutMs = envInt('RESEARCH_TIMEOUT_MS', 600000);

  // Wall-clock guard: marks the run aborted after the budget expires.
  const budgetExceeded = new Promise((resolve) => {
    setTimeout(() => {
      state.aborted = true;
      resolve(true);
    }, researchTimeoutMs);
  });

  const performResearch = (async () => {
    try {
      return await doCompanyResearch(company, state);
    } catch (err) {
      console.error(`[RESEARCH] Research failed for ${company.companyName}:`, err.message);
      if (!state.aborted) {
        await Company.findByIdAndUpdate(companyId, { researchStatus: 'failed' }).catch(() => {});
      }
      throw err;
    }
  })();

  const timedOut = await Promise.race([performResearch.then(() => false), budgetExceeded.then(() => true)]);
  if (timedOut) {
    console.error(`[RESEARCH] Research job timed out after ${researchTimeoutMs}ms for ${company.companyName}`);
    await Company.findByIdAndUpdate(companyId, { researchStatus: 'failed' }).catch(() => {});
    throw Object.assign(new Error(`Research job timed out after ${researchTimeoutMs}ms`), {
      status: 504,
      code: 'RESEARCH_TIMEOUT'
    });
  }

  return await performResearch;
};

/**
 * Core research work. Guarantees a terminal Company.researchStatus before returning.
 */
const doCompanyResearch = async (company, state) => {
  const companyId = company._id;

  // 1. Fetch only verified, completed pages with meaningful content available
  const pages = await CrawledPage.find({
    companyId,
    crawlStatus: 'completed',
    contentAvailable: true,
    wordCount: { $gte: 15 }
  }).sort({ depth: 1, wordCount: -1 }).limit(3);

  let researchSource = 'website_crawl';
  let researchMethod = 'WEBSITE_CRAWLED';
  let fallbackUsed = false;
  let blockReason = '';
  let evidenceItems = [];
  let sourcesUsed = [];
  let researchData = null;
  const aiConfig = await getAiConfig();

  // 2. Direct Website Content Pipeline
  if (pages.length > 0) {
    researchSource = 'website_crawl';
    researchMethod = 'WEBSITE_CRAWLED';
    fallbackUsed = false;
    sourcesUsed = pages.map(p => ({
      url: p.url,
      title: p.title || p.url,
      pageType: p.pageType || 'website_page'
    }));

    const pageSummaries = pages.map(p => ({
      url: p.url,
      pageType: p.pageType,
      title: p.title,
      headings: (p.headings || []).map(h => h.text).slice(0, 8),
      contentSnippet: (p.content || '').slice(0, 600)
    }));

    const systemPrompt = `You are a world-class B2B sales intelligence analyst. You analyze company websites and synthesize accurate, insightful sales intelligence and actionable outreach triggers. You always respond in valid JSON format matching the requested schema.`;

    const userPrompt = `Analyze the following website data for the company "${company.companyName}" (${company.website}):

Industry tag: ${company.industry || 'Unknown'}
Country: ${company.country || 'Unknown'}

Crawled Website Pages (${pageSummaries.length} pages):
${JSON.stringify(pageSummaries, null, 2)}

Produce a comprehensive JSON report with the following exact keys:
{
  "summary": "2-3 sentences explaining what this company does, its market, and main business",
  "valueProposition": "Their core value proposition to their customers",
  "coreOfferings": ["List of 3 to 5 core products, services, or solutions they sell"],
  "targetAudience": "Who their primary ideal buyers or clients are",
  "detectedPainPoints": [
    { "title": "Pain point title", "description": "Specific business or technical challenge this company likely faces" },
    { "title": "Pain point title 2", "description": "Another specific challenge" },
    { "title": "Pain point title 3", "description": "Another specific challenge" }
  ],
  "techStack": ["List of modern tools, cloud, technologies, or frameworks identified from their site"],
  "competitors": ["2 to 4 potential competitors or peer companies in their industry"],
  "icebreakers": [
    "Compelling opening hook 1 based on their specific product/blog/recent announcement",
    "Compelling opening hook 2 based on their company mission or unique feature",
    "Compelling opening hook 3 based on their industry positioning"
  ],
  "icpFitScore": 85,
  "icpFitReasoning": "Why this company is a high/medium fit for B2B outreach solutions",
  "keyPersonnel": [
    { "name": "Discovered leader/founder/contact name if mentioned", "title": "Their title" }
  ]
}`;

    try {
      if (aiConfig.provider === 'gemini' && aiConfig.geminiKey) {
        researchData = await callGemini(userPrompt, systemPrompt, aiConfig.geminiKey, aiConfig.model);
      } else if (aiConfig.provider === 'openai' && aiConfig.openaiKey) {
        researchData = await callOpenAI(userPrompt, systemPrompt, aiConfig.openaiKey, aiConfig.model);
      } else if (aiConfig.provider === 'ollama') {
        researchData = await callAI(userPrompt, systemPrompt, aiConfig);
      } else {
        researchData = generateFallbackResearch(company, pages);
      }
    } catch (err) {
      console.warn('AI research call failed, falling back to smart heuristic:', err.message);
      researchData = generateFallbackResearch(company, pages);
    }
  } else {
    // 3. Fallback Public-Source Research Pipeline (when direct crawl is blocked or empty)
    const blockedCount = await CrawledPage.countDocuments({
      companyId,
      crawlStatus: { $in: ['blocked', 'rate_limited', 'robots_disallowed'] }
    });

    const isBlocked = blockedCount > 0 || company.crawlStatus === 'blocked';
    blockReason = isBlocked
      ? 'Official website access was blocked by CDN/Access Controls (Akamai / Cloudflare / Access Denied).'
      : 'No direct website pages were accessible.';

    console.log(`[CRAWLER] Company: ${company.companyName} | Crawl Status: ${isBlocked ? 'BLOCKED' : 'FAILED'} | Block Reason: ${blockReason} | Fallback Research: STARTED`);

    // A search/provider failure is a controlled condition (never a crash of the
    // whole research job). On failure we degrade to the system_guard path below.
    let publicOverview = null;
    try {
      publicOverview = await fetchCompanyPublicOverview(
        company.companyName,
        company.normalizedWebsite || company.website,
        company.industry,
        company.country
      );
    } catch (err) {
      console.warn(`[RESEARCH] Fallback public-source lookup failed for ${company.companyName}:`, err.message);
    }

    evidenceItems = publicOverview ? (publicOverview.evidenceItems || []) : [];

    if (evidenceItems.length > 0) {
      researchSource = 'public_sources';
      researchMethod = 'WEBSITE_BLOCKED_FALLBACK_USED';
      fallbackUsed = true;
      sourcesUsed = evidenceItems.map(e => ({
        url: e.sourceUrl,
        title: e.sourceTitle,
        pageType: e.sourceType
      }));

      const evidenceText = evidenceItems.map((e, idx) => `[Source ${idx + 1}] Title: ${e.sourceTitle} (${e.sourceUrl})\nType: ${e.sourceType}\nEvidence: ${e.evidenceText}`).join('\n\n');

      const systemPrompt = `You are a precision B2B intelligence analyst. The target company's official website was blocked by CDN/access controls, so you must synthesize your analysis STRICTLY from the verified public search results and corporate records provided below. Never hallucinate information not supported by the evidence. Respond in valid JSON matching the requested schema.`;

      const userPrompt = `Target Company: "${company.companyName}" (${company.website})
Industry: ${company.industry || 'Unknown'}
Country: ${company.country || 'Unknown'}
Research Mode: Fallback Public-Source Analysis

Verified Public Sources & Corporate Records (${evidenceItems.length} sources):
${evidenceText}

Synthesize a comprehensive JSON report with the following exact keys:
{
  "summary": "2-3 sentences explaining what this company does based on verified public records",
  "valueProposition": "Their core value proposition to their customers",
  "coreOfferings": ["List of 3 to 5 core products, services, or solutions they sell"],
  "targetAudience": "Who their primary ideal buyers or clients are",
  "detectedPainPoints": [
    { "title": "Pain point title", "description": "Specific business or technical challenge this company likely faces" },
    { "title": "Pain point title 2", "description": "Another specific challenge" },
    { "title": "Pain point title 3", "description": "Another specific challenge" }
  ],
  "techStack": ["Modern tools, cloud, technologies, or frameworks mentioned in public records"],
  "competitors": ["2 to 4 potential competitors or peer companies in their industry"],
  "icebreakers": [
    "Compelling opening hook 1 based on recent corporate initiatives or announcements",
    "Compelling opening hook 2 based on their market positioning",
    "Compelling opening hook 3 based on industry trends"
  ],
  "icpFitScore": 88,
  "icpFitReasoning": "Why this company is a high/medium fit for enterprise AI & automation solutions",
  "keyPersonnel": [
    { "name": "Discovered executive name from public records", "title": "Their title" }
  ]
}`;

      try {
        if (aiConfig.provider === 'gemini' && aiConfig.geminiKey) {
          researchData = await callGemini(userPrompt, systemPrompt, aiConfig.geminiKey, aiConfig.model);
        } else if (aiConfig.provider === 'openai' && aiConfig.openaiKey) {
          researchData = await callOpenAI(userPrompt, systemPrompt, aiConfig.openaiKey, aiConfig.model);
        } else if (aiConfig.provider === 'ollama') {
          researchData = await callAI(userPrompt, systemPrompt, aiConfig);
        } else {
          researchData = generateFallbackResearch(company, []);
        }

        // Merge discovered public key personnel if AI missed any
        if (publicOverview.keyPersonnel && publicOverview.keyPersonnel.length > 0) {
          const currentPeople = (researchData.keyPersonnel || []).map(p => (p.name || '').toLowerCase());
          for (const kp of publicOverview.keyPersonnel) {
            if (!currentPeople.includes(kp.name.toLowerCase())) {
              if (!researchData.keyPersonnel) researchData.keyPersonnel = [];
              researchData.keyPersonnel.push(kp);
            }
          }
        }
      } catch (err) {
        console.warn('AI fallback research call failed, using heuristic synthesizer:', err.message);
        researchData = generateFallbackResearch(company, []);
      }
    } else {
      // 4. No direct pages AND no public search evidence found
      researchSource = 'system_guard';
      researchMethod = isBlocked ? 'WEBSITE_BLOCKED_NO_FALLBACK' : 'CRAWL_FAILED';
      fallbackUsed = false;
      sourcesUsed = [];

      researchData = generateFallbackResearch(company, []);
      researchData.summary = `${company.companyName} (${company.industry || 'B2B Enterprise'}). ${blockReason} Intelligence synthesized from industry baseline profile.`;
    }
  }

  // 4. Save or update CompanyResearch with full provenance
  const savedResearch = await CompanyResearch.findOneAndUpdate(
    { companyId },
    {
      companyId,
      summary: researchData.summary || '',
      valueProposition: researchData.valueProposition || '',
      coreOfferings: researchData.coreOfferings || [],
      targetAudience: researchData.targetAudience || '',
      detectedPainPoints: researchData.detectedPainPoints || [],
      techStack: researchData.techStack || [],
      competitors: researchData.competitors || [],
      icebreakers: researchData.icebreakers || [],
      icpFitScore: typeof researchData.icpFitScore === 'number' ? researchData.icpFitScore : 80,
      icpFitReasoning: researchData.icpFitReasoning || '',
      keyPersonnel: researchData.keyPersonnel || [],
      sourcesUsed,
      researchSource,
      researchMethod,
      fallbackUsed,
      blockReason,
      evidenceItems,
      aiProvider: aiConfig.provider,
      aiModel: aiConfig.model,
      researchedAt: new Date()
    },
    { upsert: true, new: true }
  );

  // Update Company record - always a terminal state. If the run was aborted by
  // the wall-clock guard, stay failed rather than overwriting with completed.
  if (state && state.aborted) {
    await Company.findByIdAndUpdate(companyId, {
      researchStatus: 'failed',
      lastResearchAt: new Date()
    });
  } else {
    await Company.findByIdAndUpdate(companyId, {
      researchStatus: 'completed',
      lastResearchAt: new Date()
    });
  }

  return savedResearch;
};

/**
 * Get existing research for a company
 */
const getCompanyResearch = async (companyId) => {
  const research = await CompanyResearch.findOne({ companyId });
  return research;
};

module.exports = {
  runCompanyResearch,
  getCompanyResearch
};
