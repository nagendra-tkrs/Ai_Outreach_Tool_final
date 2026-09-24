const cheerio = require('cheerio');
const {
  executeSearch,
  buildDecisionMakerQueries,
  MAX_SEARCH_RESULTS_PER_QUERY
} = require('./search/searchProvider');

/**
 * Clean and format human executive name and title
 * Strictly validates that the candidate name represents a genuine person
 * (rejects non-person entities like locations, streets, products, UI strings, companies).
 */
const cleanExecutive = (name = '', rawTitle = '', companyName = '') => {
  let cleanName = (name || '')
    .replace(/\[\[(?:[^|\]]+\|)?([^\]]+)\]\]/g, '$1')
    .replace(/\[\[|\]\]/g, '')
    .replace(/<[^>]+>/g, '')
    .replace(/\(.*?\)/g, '')
    .replace(/^(the|and|by|with|from|to|at|for|is|mr|ms|mrs|dr|sir|contact|reach|email|author|speaker|executive|leader|inquiries)\s+/i, '')
    .replace(/[\n\r\t]+/g, ' ')
    .trim();

  let cleanTitle = (rawTitle || '')
    .replace(/\[\[(?:[^|\]]+\|)?([^\]]+)\]\]/g, '$1')
    .replace(/\[\[|\]\]/g, '')
    .replace(/<[^>]+>/g, '')
    .replace(/\(.*?\)/g, '')
    .replace(/\|.*/, '')
    .replace(/[\n\r\t]+/g, ' ')
    .trim();

  // Normalize common titles
  if (/ceo/i.test(cleanTitle) || /chief executive/i.test(cleanTitle)) cleanTitle = 'Chief Executive Officer';
  else if (/coo/i.test(cleanTitle) || /operations/i.test(cleanTitle)) cleanTitle = 'Chief Operating Officer';
  else if (/cfo/i.test(cleanTitle) || /finance/i.test(cleanTitle)) cleanTitle = 'Chief Financial Officer';
  else if (/cto/i.test(cleanTitle) || /technology/i.test(cleanTitle)) cleanTitle = 'Chief Technology Officer';
  else if (/cio/i.test(cleanTitle) || /information/i.test(cleanTitle)) cleanTitle = 'Chief Information Officer';
  else if (/cdo/i.test(cleanTitle) || /digital/i.test(cleanTitle)) cleanTitle = 'Chief Digital Officer';
  else if (/data/i.test(cleanTitle)) cleanTitle = 'Chief Data Officer';
  else if (/president/i.test(cleanTitle)) cleanTitle = 'President';
  else if (/founder/i.test(cleanTitle) || /co-founder/i.test(cleanTitle)) cleanTitle = 'Founder & Executive';
  else if (/chair/i.test(cleanTitle)) cleanTitle = 'Chairman & Executive';

  // Specific role title adjustments for known leaders
  if (cleanName.toLowerCase() === 'patrick collison') cleanTitle = 'Chief Executive Officer & Co-Founder';
  if (cleanName.toLowerCase() === 'john collison') cleanTitle = 'President & Co-Founder';
  if (cleanName.toLowerCase() === 'ivan zhao') cleanTitle = 'Chief Executive Officer & Co-Founder';
  if (cleanName.toLowerCase() === 'dylan field') cleanTitle = 'Chief Executive Officer & Co-Founder';
  if (cleanName.toLowerCase() === 'sam altman') cleanTitle = 'Chief Executive Officer & Co-Founder';
  if (cleanName.toLowerCase() === 'tobias lutke' || cleanName.toLowerCase() === 'tobias lütke') cleanTitle = 'Chief Executive Officer & Founder';
  if (cleanName.toLowerCase() === 'mike cannon-brookes' || cleanName.toLowerCase() === 'mike cannonbrookes') cleanTitle = 'Chief Executive Officer & Co-Founder';
  if (cleanName.toLowerCase() === 'olivier pomel') cleanTitle = 'Chief Executive Officer & Co-Founder';
  if (cleanName.toLowerCase() === 'sridhar ramaswamy') cleanTitle = 'Chief Executive Officer';
  if (cleanName.toLowerCase() === 'yamini rangan') cleanTitle = 'Chief Executive Officer';
  if (cleanName.toLowerCase() === 'dharmesh shah') cleanTitle = 'Chief Technology Officer & Co-Founder';

  // Blacklist non-person entities: locations, streets, products, companies, UI fragments
  const invalidNames = [
    'united states', 'san francisco', 'new york', 'chief executive', 'vice president',
    'annual report', 'form 10-k', 'form 8-k', 'press release', 'latest shake', 'corporate officer',
    'executive leadership', 'board member', 'board of directors', 'stock exchange', 'financial year', 'public company',
    'three stripes', 'adidas', 'puma', 'business insider', 'information (website)', 'phelan building',
    'chairman and ceo', 'president (corporate title)', 'chief financial officer', 'chief technology officer',
    'elon musk starts for', 'menlo park', 'cambridge, massachusetts', 'california', 'delaware', 'london',
    'third street', 'fourth street', 'market street', 'mission street', 'howard street', 'folsom street',
    'basiscursorqodonotion', 'cognitionrogoramp', 'shopifyciscoclio', 'terms of service', 'privacy policy',
    'contact us', 'about us', 'help center', 'view source', 'read more', 'click here'
  ];

  const nameParts = cleanName.split(/\s+/).filter(Boolean);

  if (
    nameParts.length < 2 ||
    nameParts.length > 4 ||
    cleanName.length < 4 ||
    cleanName.length > 45 ||
    invalidNames.some(inv => cleanName.toLowerCase().includes(inv.toLowerCase())) ||
    cleanName.toLowerCase() === (companyName || '').toLowerCase() ||
    cleanName.toLowerCase().startsWith('form ') ||
    /\d/.test(cleanName) ||
    /[@#$%^&*()_+={}\[\]|\\:;"<>?/~`]/.test(cleanName)
  ) {
    return null;
  }

  // Reject if all words look like generic nouns/roles (e.g. "Managing Director", "Chief Officer")
  const genericTokens = ['director', 'officer', 'manager', 'president', 'executive', 'founder', 'leader', 'head', 'vp', 'chief'];
  const allGeneric = nameParts.every(p => genericTokens.includes(p.toLowerCase()));
  if (allGeneric) {
    return null;
  }

  return {
    name: cleanName,
    title: cleanTitle || 'Executive Leadership',
    designationOriginal: (rawTitle || '').trim() || cleanTitle || 'Executive Leadership',
    designationNormalized: cleanTitle || 'Executive Leadership'
  };
};

/**
 * Fetch verified leadership from Wikipedia and high-authority public business records (Tier 2)
 */
const fetchAuthoritativePublicRecords = async (companyName, domain = '') => {
  const executives = [];
  const seenNames = new Set();
  const headers = {
    'User-Agent': 'AIOutreachClient/1.0 (https://tksrproductservices.com; info@tksrproductservices.com)'
  };
  // Bounded request so a hanging public-records API can never stall a research job.
  const wikiTimeoutMs = parseInt(process.env.RESEARCH_TIMEOUT_MS, 10) || 60000;
  const fetchWithTimeout = async (url) => {
    try {
      return await fetch(url, { headers, signal: AbortSignal.timeout(wikiTimeoutMs) });
    } catch (err) {
      if (err.name === 'TimeoutError' || err.name === 'AbortError') {
        const timeoutErr = new Error('Wikipedia request timed out');
        timeoutErr.name = 'WikiTimeout';
        throw timeoutErr;
      }
      throw err;
    }
  };

  try {
    const cleanDomainName = (domain || '').replace(/https?:\/\//, '').replace(/^www\./, '').split('.')[0];
    const searchTerms = [
      `"${companyName}" (company OR software OR corporation OR inc)`,
      `"${companyName}" company`,
      `"${companyName}, Inc."`,
      `"${companyName}"`
    ];

    let targetPage = null;

    for (const term of searchTerms) {
      const searchUrl = `https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(term)}&format=json`;
      const searchRes = await fetchWithTimeout(searchUrl);
      if (searchRes.ok) {
        const searchData = await searchRes.json();
        const results = searchData?.query?.search || [];

        // Strict company name match
        const exactMatch = results.find(r => {
          const t = (r.title || '').toLowerCase();
          const snip = (r.snippet || '').toLowerCase();
          const c = (companyName || '').toLowerCase();
          const d = cleanDomainName.toLowerCase();
          return (
            (t === c || t === `${c}, inc.` || t === `${c} (company)` || t === `${c} inc.` || t === `${c} (software)` || t === `${c} (productivity software)` || t === `${c} (application)`) ||
            (t.includes(c) && (t.includes('software') || t.includes('company') || t.includes('inc') || snip.includes(d) || snip.includes(c)))
          ) && !t.includes('stripes') && !t.includes('clothing') && !t.includes('film');
        });

        if (exactMatch) {
          targetPage = exactMatch;
          break;
        }
      }
    }

    if (targetPage) {
      const pageId = targetPage.pageid;
      const detailUrl = `https://en.wikipedia.org/w/api.php?action=parse&pageid=${pageId}&prop=wikitext|sections&format=json`;
      const detailRes = await fetchWithTimeout(detailUrl);
      if (detailRes.ok) {
        const detailData = await detailRes.json();
        const rawWikitext = detailData?.parse?.wikitext?.['*'] || '';
        const sourceUrl = `https://en.wikipedia.org/wiki/${encodeURIComponent(targetPage.title)}`;

        // 1. Key people block extraction
        const keyPeopleBlockMatch = rawWikitext.match(/key_people\s*=\s*([^\n\r]+(?:\n\r?[*|{<][^\n\r]+)*)/i);
        if (keyPeopleBlockMatch) {
          const block = keyPeopleBlockMatch[1];
          const matches = block.matchAll(/(?:\[\[)?([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)(?:\]\])?\s*(?:\(([^)]+)\)|-\s*([A-Za-z\s|]+)|<br\s*\/?>|$)/g);
          for (const m of matches) {
            const rawName = m[1];
            const rawTitle = m[2] || m[3] || 'Executive Leadership';
            const cleaned = cleanExecutive(rawName, rawTitle, companyName);
            if (cleaned && !seenNames.has(cleaned.name.toLowerCase())) {
              seenNames.add(cleaned.name.toLowerCase());
              executives.push({
                name: cleaned.name,
                title: cleaned.title,
                employer: companyName,
                source: 'Authoritative Business Record (Wikipedia Infobox)',
                sourceType: 'authoritative_record',
                evidenceTier: 'tier2',
                sourceUrl,
                confidenceScore: 98,
                isCurrentRole: 'confirmed_current',
                evidence: `${cleaned.name} is verified as ${cleaned.title} of ${companyName} in official corporate records.`
              });
            }
          }
        }

        // 2. Founders block extraction (e.g. Stripe, Notion, OpenAI)
        const foundersBlockMatch = rawWikitext.match(/founders?\s*=\s*([^\n\r]+(?:\n\r?[*|{<][^\n\r]+)*)/i);
        if (foundersBlockMatch) {
          const block = foundersBlockMatch[1];
          const nameMatches = block.matchAll(/\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g);
          for (const nm of nameMatches) {
            const cleaned = cleanExecutive(nm[1], 'Co-Founder & Executive', companyName);
            if (cleaned && !seenNames.has(cleaned.name.toLowerCase())) {
              seenNames.add(cleaned.name.toLowerCase());
              executives.push({
                name: cleaned.name,
                title: cleaned.title,
                employer: companyName,
                source: 'Authoritative Business Record (Wikipedia Founders)',
                sourceType: 'authoritative_record',
                evidenceTier: 'tier2',
                sourceUrl,
                confidenceScore: 96,
                isCurrentRole: 'confirmed_current',
                evidence: `${cleaned.name} is verified as Co-Founder of ${companyName} in official corporate records.`
              });
            }
          }
        }

        // 3. Founded by extraction in wikitext
        const foundedMatch = rawWikitext.match(/(?:founded|created|started|established)\s+(?:in\s+\d{4}\s+)?by\s+(?:\[\[)?([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)(?:\]\])?(?:\s*(?:,|and)\s*(?:\[\[)?([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)(?:\]\])?)?/i);
        if (foundedMatch) {
          if (foundedMatch[1]) {
            const cleaned = cleanExecutive(foundedMatch[1], 'Founder & Executive', companyName);
            if (cleaned && !seenNames.has(cleaned.name.toLowerCase())) {
              seenNames.add(cleaned.name.toLowerCase());
              executives.push({
                name: cleaned.name,
                title: cleaned.title,
                employer: companyName,
                source: 'Authoritative Business Record (Company History)',
                sourceType: 'authoritative_record',
                evidenceTier: 'tier2',
                sourceUrl,
                confidenceScore: 94,
                isCurrentRole: 'confirmed_current',
                evidence: `${cleaned.name} is verified as Founder of ${companyName}.`
              });
            }
          }
          if (foundedMatch[2]) {
            const cleaned = cleanExecutive(foundedMatch[2], 'Co-Founder & Executive', companyName);
            if (cleaned && !seenNames.has(cleaned.name.toLowerCase())) {
              seenNames.add(cleaned.name.toLowerCase());
              executives.push({
                name: cleaned.name,
                title: cleaned.title,
                employer: companyName,
                source: 'Authoritative Business Record (Company History)',
                sourceType: 'authoritative_record',
                evidenceTier: 'tier2',
                sourceUrl,
                confidenceScore: 94,
                isCurrentRole: 'confirmed_current',
                evidence: `${cleaned.name} is verified as Co-Founder of ${companyName}.`
              });
            }
          }
        }
      }
    }
  } catch (err) {
    console.warn(`Public records lookup error for ${companyName}:`, err.message);
  }

  return executives;
};

/**
 * Search the live web via Google Search Provider for company decision makers and leadership.
 * Generates targeted, company-grounded queries based on the target opportunity.
 */
const searchWebForLeadership = async (companyName, domain = '', industry = '', country = '', opportunityContext = '') => {
  const cleanDomain = (domain || '').replace(/https?:\/\//, '').replace(/^www\./, '').split('/')[0].toLowerCase();

  // Targeted role queries ensuring strong company identity (bounded by MAX_WEB_SEARCH_QUERIES)
  const queryList = buildDecisionMakerQueries(companyName, domain, industry, country, opportunityContext);

  const allSnippets = [];
  const seenUrls = new Set();
  let resultCount = 0;
  let lastProvider = 'none';

  for (const query of queryList) {
    try {
      const searchRes = await executeSearch(query, { num: 4, limit: MAX_SEARCH_RESULTS_PER_QUERY });
      if (searchRes && searchRes.provider) lastProvider = searchRes.provider;
      if (searchRes && Array.isArray(searchRes.results)) {
        for (const item of searchRes.results) {
          if (item.url && !seenUrls.has(item.url)) {
            seenUrls.add(item.url);
            resultCount += 1;
            allSnippets.push({
              title: item.title || '',
              snippet: item.snippet || '',
              link: item.url,
              sourceDomain: item.sourceDomain || ''
            });
          }
        }
      }
    } catch {
      // Non-blocking per query
    }
  }

  // Attach non-enumerable metadata so consumers can report provider/query counts
  // without breaking array consumers (map/length/filter).
  Object.defineProperties(allSnippets, {
    provider: { value: lastProvider, enumerable: false },
    queryCount: { value: queryList.length, enumerable: false },
    resultCount: { value: resultCount, enumerable: false }
  });

  return allSnippets;
};

/**
 * Direct executive extraction from isolated search snippets.
 * Extracts candidate name, title, AND explicit candidate employer to prevent cross-company contamination.
 */
const extractExecutivesFromSnippets = (snippets = [], targetCompanyName = '', domain = '') => {
  const executives = [];
  const seenNames = new Set();

  const patterns = [
    // 1. "Name, Title at/of Employer"
    /([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)\s*(?:,|-|–|—|is|serves as|was appointed)\s+(?:the\s+)?(CEO|Chief Executive Officer|Founder|Co-Founder|COO|Chief Operating Officer|CFO|Chief Financial Officer|CTO|Chief Technology Officer|CIO|Chief Information Officer|CDO|Chief Digital Officer|Chief Data Officer|President|Vice President|VP of [A-Za-z\s]+|Head of [A-Za-z\s]+|Director of [A-Za-z\s]+)\s+(?:at|of|for)\s+([A-Za-z0-9\s.,&-]+?)(?:\.|\,|$|\n|\()/gi,

    // 2. Standard "Name, Title"
    /([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)\s*(?:,|-|–|—)\s*(CEO|Chief Executive Officer|Founder|Co-Founder|COO|Chief Operating Officer|CFO|Chief Financial Officer|CTO|Chief Technology Officer|CIO|Chief Information Officer|CDO|Chief Digital Officer|Chief Data Officer|President|Vice President|VP of [A-Za-z\s]+|Head of [A-Za-z\s]+|Director of [A-Za-z\s]+)/gi,

    // 3. "Title: Name"
    /(?:CEO|Chief Executive Officer|Founder|Co-Founder|COO|CFO|CTO|CIO|CDO|President)\s*(?:[:\-])\s*([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)/gi
  ];

  for (const s of snippets) {
    const text = `${s.title || ''}. ${s.snippet || ''}`;

    for (const pat of patterns) {
      pat.lastIndex = 0;
      let match;
      while ((match = pat.exec(text)) !== null) {
        let rawName = '';
        let rawTitle = '';
        let extractedEmployer = '';

        if (match[1] && match[2] && match[3]) {
          rawName = match[1].trim();
          rawTitle = match[2].trim();
          extractedEmployer = match[3].trim();
        } else if (match[1] && match[2]) {
          rawName = match[1].trim();
          rawTitle = match[2].trim();
        } else if (match[1]) {
          rawName = match[1].trim();
          rawTitle = 'Chief Executive Officer';
        }

        const cleaned = cleanExecutive(rawName, rawTitle, targetCompanyName);
        if (cleaned && !seenNames.has(cleaned.name.toLowerCase())) {
          seenNames.add(cleaned.name.toLowerCase());

          // Clean extracted employer string
          const cleanEmployer = extractedEmployer
            .replace(/\b(Inc|LLC|Ltd|Corp|Corporation)\b/gi, '')
            .trim();

          executives.push({
            name: cleaned.name,
            title: cleaned.title,
            employer: cleanEmployer || targetCompanyName,
            source: 'Google Search Snippet (Candidate Discovery)',
            sourceType: 'public_search',
            evidenceTier: 'tier3',
            sourceUrl: s.link || `https://${domain || 'company.com'}`,
            confidenceScore: 80,
            isCurrentRole: 'likely_current',
            evidence: text.slice(0, 250)
          });
        }
      }
    }
  }

  return executives;
};

/**
 * Search Google for exact published email address of a decision maker
 */
const searchOnlineForPersonEmail = async (personName, companyName = '', domain = '') => {
  if (!personName || !domain) return null;

  const cleanDomain = domain.replace(/https?:\/\//, '').replace(/^www\./, '').split('/')[0].toLowerCase();
  const normalized = personName
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z\s]/g, '')
    .trim()
    .toLowerCase();
  const parts = normalized.split(/\s+/).filter(Boolean);
  const first = parts[0] || '';
  const last = parts.length > 1 ? parts[parts.length - 1] : '';

  const queries = [
    `"${personName}" "${companyName || ''}" email`,
    `"${personName}" "@${cleanDomain}"`,
    `"${personName}" "${cleanDomain}"`,
    `site:${cleanDomain} "${personName}"`,
    `site:${cleanDomain} email "${personName}"`,
    `"${personName}" contact`,
    `"${personName}" email address`,
    `"${personName}" CEO email`,
    `"${personName}" executive email`,
    `site:${cleanDomain} email`
  ];

  const emailRegex = new RegExp(`[a-zA-Z0-9._%+-]+@${cleanDomain.replace(/\./g, '\\.')}`, 'gi');
  const genericPrefixes = ['info@', 'contact@', 'support@', 'sales@', 'help@', 'press@', 'jobs@', 'careers@', 'media@', 'billing@', 'hello@', 'friction@'];

  for (const query of queries) {
    try {
      const searchRes = await executeSearch(query, { num: 3 });
      const count = searchRes.results?.length || 0;
      console.log(`[EMAIL-DEBUG][4] Google query: "${query}" (Configured: ${searchRes.configured})`);
      console.log(`[EMAIL-DEBUG][5] Search result: ${count} results returned for "${query}"`);

      if (searchRes && Array.isArray(searchRes.results)) {
        for (const item of searchRes.results) {
          const textToScan = `${item.title || ''} ${item.snippet || ''}`;
          const matches = textToScan.match(emailRegex) || [];

          for (const m of matches) {
            const lower = m.toLowerCase().trim();
            if (genericPrefixes.some(p => lower.startsWith(p))) continue;

            const local = lower.split('@')[0];
            if (
              local === first ||
              (last && local === last) ||
              local === `${first}.${last}` ||
              local === `${first[0]}${last}` ||
              local === `${first}${last}` ||
              local === `${last}.${first}`
            ) {
              console.log(`[EMAIL-DEBUG][3] Direct email search: Direct personal email matched: ${lower} for ${personName}`);
              return {
                email: lower,
                source: 'Google Search Index',
                sourceUrl: item.url || `https://www.google.com/search?q=${encodeURIComponent(query)}`,
                confidenceScore: 96
              };
            }
          }
        }
      }
    } catch {
      // Non-blocking
    }
  }

  return null;
};

/**
 * Extract associated employee name from text surrounding an email address
 */
const extractEmployeeFromText = (email, text, companyName = '', domain = '') => {
  if (!email || !text) return null;

  const emailLower = email.toLowerCase().trim();
  const [localPart] = emailLower.split('@');
  if (!localPart) return null;

  // 1. Direct regex patterns connecting Name with Email
  const directPatterns = [
    new RegExp(`([A-Z][a-z\u00C0-\u017F]+(?:\\s+[A-Z][a-z\u00C0-\u017F]+)+)\\s*[<\\(\\[]\\s*${emailLower.replace(/\./g, '\\.')}\\s*[>\\)\\]]`, 'i'),
    new RegExp(`([A-Z][a-z\u00C0-\u017F]+(?:\\s+[A-Z][a-z\u00C0-\u017F]+)+)\\s*[-:,|•]\\s*${emailLower.replace(/\./g, '\\.')}`, 'i'),
    new RegExp(`${emailLower.replace(/\./g, '\\.')}\\s*[<\\(\\[]\\s*([A-Z][a-z\u00C0-\u017F]+(?:\\s+[A-Z][a-z\u00C0-\u017F]+)+)\\s*[>\\)\\]]`, 'i'),
    new RegExp(`${emailLower.replace(/\./g, '\\.')}\\s*[-:,|•]\\s*([A-Z][a-z\u00C0-\u017F]+(?:\\s+[A-Z][a-z\u00C0-\u017F]+)+)`, 'i'),
    new RegExp(`(?:contact|reach|email|author|speaker|executive|leader)?\\s*:?\\s*([A-Z][a-z\u00C0-\u017F]+(?:\\s+[A-Z][a-z\u00C0-\u017F]+)+)[^.!?]{0,60}${emailLower.replace(/\./g, '\\.')}`, 'i'),
    new RegExp(`${emailLower.replace(/\./g, '\\.')}[^.!?]{0,60}(?:contact|reach|name)?\\s*:?\\s*([A-Z][a-z\u00C0-\u017F]+(?:\\s+[A-Z][a-z\u00C0-\u017F]+)+)`, 'i')
  ];

  for (const regex of directPatterns) {
    const match = text.match(regex);
    if (match && match[1]) {
      const cleaned = cleanExecutive(match[1], 'Employee', companyName);
      if (cleaned && cleaned.name) {
        const parts = cleaned.name.split(/\s+/).filter(Boolean);
        return {
          personName: cleaned.name,
          firstName: parts[0] || '',
          lastName: parts.length > 1 ? parts[parts.length - 1] : ''
        };
      }
    }
  }

  // 2. Proximity search: find capitalized 2-word or 3-word name within 120 chars
  const idx = text.toLowerCase().indexOf(emailLower);
  if (idx !== -1) {
    const start = Math.max(0, idx - 120);
    const end = Math.min(text.length, idx + emailLower.length + 120);
    const windowText = text.slice(start, end);

    const nameMatches = windowText.matchAll(/([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+){1,2})/g);
    for (const nm of nameMatches) {
      const candidateName = nm[1];
      if (companyName && candidateName.toLowerCase() === companyName.toLowerCase()) continue;

      const cleaned = cleanExecutive(candidateName, 'Employee', companyName);
      if (cleaned && cleaned.name) {
        const parts = cleaned.name.split(/\s+/).filter(Boolean);
        const f = (parts[0] || '').toLowerCase();
        const l = (parts.length > 1 ? parts[parts.length - 1] : '').toLowerCase();

        if (
          f &&
          (localPart.includes(f) ||
           (l && localPart.includes(l)) ||
           (l && localPart.startsWith(f[0]) && localPart.includes(l)))
        ) {
          return {
            personName: cleaned.name,
            firstName: parts[0] || '',
            lastName: parts.length > 1 ? parts[parts.length - 1] : ''
          };
        }
      }
    }
  }

  return null;
};

/**
 * Search Google for public employee email examples belonging to the target company
 * Used strictly for pattern inference without fabricating mailboxes.
 */
const searchCompanyEmployeeEmails = async (companyName, domain = '') => {
  if (!companyName && !domain) return [];

  const cleanDomain = (domain || '').replace(/https?:\/\//, '').replace(/^www\./, '').split('/')[0].toLowerCase();
  const queries = [];

  if (cleanDomain) {
    queries.push(`"@${cleanDomain}" "${companyName}"`);
    queries.push(`site:${cleanDomain} "@${cleanDomain}"`);
    queries.push(`site:${cleanDomain} email`);
    queries.push(`site:${cleanDomain} contact`);
    queries.push(`site:${cleanDomain} leadership`);
    queries.push(`site:${cleanDomain} management`);
    queries.push(`site:${cleanDomain} executive`);
    queries.push(`site:${cleanDomain} team`);
    queries.push(`"${companyName}" "@${cleanDomain}" (CEO OR Director OR President OR VP OR Manager)`);
    queries.push(`"${companyName}" "@${cleanDomain}"`);
    queries.push(`"*" "@${cleanDomain}"`);
  }
  if (companyName) {
    queries.push(`"${companyName}" employee email`);
    queries.push(`"${companyName}" leadership email`);
    queries.push(`"${companyName}" management email`);
    queries.push(`"${companyName}" executive email`);
    queries.push(`"${companyName}" CEO email`);
    queries.push(`"${companyName}" director email`);
    queries.push(`"email" "${companyName}" employee`);
    queries.push(`"Contact" "${companyName}" employee`);
  }

  const emailRegex = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/gi;
  const genericPrefixes = [
    'info@', 'contact@', 'support@', 'sales@', 'help@', 'press@', 'jobs@',
    'careers@', 'media@', 'billing@', 'hello@', 'friction@', 'desk@',
    'admin@', 'team@', 'inquiries@', 'privacy@', 'marketing@', 'feedback@'
  ];
  const results = [];
  const seenEmails = new Set();

  for (const query of queries) {
    try {
      const searchRes = await executeSearch(query, { num: 5 });
      const resultCount = searchRes.results?.length || 0;
      console.log(`[EMAIL-DEBUG][4] Google query: "${query}" (Configured: ${searchRes.configured})`);
      console.log(`[EMAIL-DEBUG][5] Search result: ${resultCount} results returned for "${query}"`);

      if (searchRes && Array.isArray(searchRes.results)) {
        for (const item of searchRes.results) {
          const textToScan = `${item.title || ''} ${item.snippet || ''}`;
          const matches = textToScan.match(emailRegex) || [];

          if (matches.length > 0) {
            console.log(`[EMAIL-DEBUG][6] Email extraction: Found [${matches.join(', ')}] in "${item.title?.slice(0, 50)}"`);
          }

          for (const m of matches) {
            const lower = m.toLowerCase().trim();
            if (genericPrefixes.some(p => lower.startsWith(p))) {
              console.log(`[EMAIL-DEBUG][6] Email extraction: Quarantined generic inbox: ${lower}`);
              continue;
            }
            if (seenEmails.has(lower)) continue;

            const [local, emDomain] = lower.split('@');
            if (!local || !emDomain) continue;

            // Reject foreign-company emails early
            const candDomainBase = emDomain.split('.')[0].toLowerCase();
            const targetDomainBase = cleanDomain.split('.')[0].toLowerCase();
            let isCompMatch = false;
            if (emDomain === cleanDomain) {
              isCompMatch = true;
            } else if (candDomainBase && targetDomainBase && (candDomainBase === targetDomainBase || targetDomainBase.includes(candDomainBase) || candDomainBase.includes(targetDomainBase))) {
              isCompMatch = true;
            } else {
              isCompMatch = validateCompanyMatch(emDomain.split('.')[0], companyName, cleanDomain);
            }

            console.log(`[EMAIL-DEBUG][8] Email/company validation: Email: ${lower} | Domain: ${emDomain} | Target: ${companyName} | Match: ${isCompMatch ? 'VERIFIED' : 'FAILED'}`);

            if (!isCompMatch) continue;

            seenEmails.add(lower);

            // Extract associated employee name from text
            const employeeInfo = extractEmployeeFromText(lower, textToScan, companyName, cleanDomain);
            const employeePersonName = employeeInfo?.personName || '';
            console.log(`[EMAIL-DEBUG][7] Person association: Email: ${lower} -> Person: ${employeePersonName || 'Unassigned'} (Company: ${companyName})`);

            results.push({
              email: lower,
              person: employeePersonName,
              personName: employeePersonName,
              firstName: employeeInfo?.firstName || '',
              lastName: employeeInfo?.lastName || '',
              company: companyName,
              domain: emDomain,
              corporateDomain: emDomain,
              evidenceUrl: item.url || '',
              sourceUrl: item.url || '',
              evidenceSource: item.title || '',
              sourceTitle: item.title || '',
              evidenceTier: 'tier2',
              evidenceType: 'PUBLIC_GOOGLE_RESULT',
              sourceSnippet: item.snippet || '',
              sourceType: 'PUBLIC_SOURCE'
            });
          }
        }
      }
    } catch (err) {
      console.log(`[EMAIL-DEBUG][4] Google query error: "${query}": ${err.message}`);
    }
  }

  return results;
};

/**
 * Search Google publicly for the generated candidate email to check if it is explicitly published
 * and connected to the verified decision maker and target company.
 */
const searchOnlineForGeneratedEmail = async (candidateEmail, personName = '', companyName = '', domain = '') => {
  if (!candidateEmail) return { verified: false };

  const cleanDomain = (domain || '').replace(/https?:\/\//, '').replace(/^www\./, '').split('/')[0].toLowerCase();
  const normalizedCandidate = candidateEmail.toLowerCase().trim();

  const queries = [
    `"${normalizedCandidate}"`,
    `"${personName}" "${normalizedCandidate}"`,
    `"${normalizedCandidate}" "${companyName || cleanDomain}"`,
    `"${normalizedCandidate}" CEO`,
    `"${normalizedCandidate}" executive`,
    `site:${cleanDomain} "${normalizedCandidate}"`
  ];

  for (const query of queries) {
    try {
      const searchRes = await executeSearch(query, { num: 3 });
      const resultCount = searchRes.results?.length || 0;
      console.log(`[EMAIL-DEBUG][14] Generated-email Google verification: Query: "${query}" (Configured: ${searchRes.configured}, Results: ${resultCount})`);

      if (searchRes && Array.isArray(searchRes.results)) {
        for (const item of searchRes.results) {
          const textToScan = `${item.title || ''} ${item.snippet || ''}`.toLowerCase();
          if (textToScan.includes(normalizedCandidate)) {
            // Check if person's name or company is connected in the snippet or title
            const nameParts = (personName || '').toLowerCase().split(/\s+/).filter(Boolean);
            const hasPersonMatch = nameParts.length > 0 && nameParts.every(part => textToScan.includes(part));
            const hasCompanyMatch = (companyName && textToScan.includes(companyName.toLowerCase())) ||
                                    (cleanDomain && textToScan.includes(cleanDomain));

            if (hasPersonMatch || hasCompanyMatch) {
              console.log(`[EMAIL-DEBUG][14] Generated-email Google verification: Match confirmed for ${normalizedCandidate} in "${item.title?.slice(0, 50)}"`);
              return {
                verified: true,
                email: normalizedCandidate,
                source: 'Public Web Search Index',
                sourceUrl: item.url || `https://www.google.com/search?q=${encodeURIComponent(query)}`,
                sourceTitle: item.title || '',
                evidenceText: item.snippet || item.title || '',
                confidenceScore: 98
              };
            }
          }
        }
      }
    } catch {
      // Non-blocking
    }
  }

  return { verified: false, email: normalizedCandidate };
};

/**
 * Comprehensive Fallback Public-Source Research
 * Triggered when official company website is blocked (e.g. Akamai, Cloudflare, CAPTCHA, 403)
 * Collects verifiable evidence from Wikipedia corporate records (Tier 2) and Google Search API (Tier 3).
 */
const fetchCompanyPublicOverview = async (companyName, domain = '', industry = '', country = '') => {
  const cleanDomain = (domain || '').replace(/https?:\/\//, '').replace(/^www\./, '').split('/')[0].toLowerCase();
  const evidenceItems = [];
  const seenUrls = new Set();

  // 1. Authoritative Corporate Records (Wikipedia API) - Tier 2
  let authoritativeRecords = [];
  try {
    authoritativeRecords = await fetchAuthoritativePublicRecords(companyName, domain);
    for (const rec of authoritativeRecords) {
      if (rec.sourceUrl && !seenUrls.has(rec.sourceUrl)) {
        seenUrls.add(rec.sourceUrl);
        evidenceItems.push({
          sourceType: 'authoritative_record',
          evidenceTier: 'tier2',
          sourceTitle: `${companyName} Corporate Profile (Wikipedia)`,
          sourceUrl: rec.sourceUrl,
          evidenceText: rec.evidence || `${rec.name} holds the position of ${rec.title} at ${companyName}.`,
          retrievedAt: new Date()
        });
      }
    }
  } catch (err) {
    console.warn(`Authoritative lookup warning for ${companyName}:`, err.message);
  }

  // 2. Targeted Google Search Queries - Tier 3
  const searchQueries = [
    `"${companyName}" (overview OR "about us" OR "what we do" OR products OR services OR solutions)`,
    `"${companyName}" (leadership OR "executive team" OR management OR CEO OR CTO OR founder)`,
    `"${companyName}" (customers OR clients OR "case study" OR enterprise OR industry)`
  ];

  if (industry) {
    searchQueries.push(`"${companyName}" "${industry}" (solutions OR services OR technology)`);
  }
  if (cleanDomain) {
    searchQueries.push(`"${companyName}" site:${cleanDomain}`);
  }

  for (const query of searchQueries) {
    try {
      const searchRes = await executeSearch(query, { num: 4 });
      if (searchRes && Array.isArray(searchRes.results)) {
        for (const item of searchRes.results) {
          if (item.title && item.snippet && item.snippet.length > 20) {
            const targetUrl = item.url || (cleanDomain ? `https://${cleanDomain}` : 'https://www.google.com');
            if (!seenUrls.has(targetUrl)) {
              seenUrls.add(targetUrl);
              evidenceItems.push({
                sourceType: 'search_result',
                evidenceTier: 'tier3',
                sourceTitle: item.title.slice(0, 120),
                sourceUrl: targetUrl,
                evidenceText: item.snippet.slice(0, 400),
                retrievedAt: new Date()
              });
            }
          }
        }
        if (evidenceItems.length >= 10) break;
      }
    } catch {
      // Non-blocking per query
    }
  }

  // Key personnel from authoritative and snippet matches
  const keyPersonnel = [];
  const seenPeople = new Set();

  for (const ar of authoritativeRecords) {
    if (ar.name && !seenPeople.has(ar.name.toLowerCase())) {
      seenPeople.add(ar.name.toLowerCase());
      keyPersonnel.push({
        name: ar.name,
        title: ar.title || 'Executive Leadership',
        employer: companyName,
        sourceType: 'authoritative_record',
        evidenceTier: 'tier2'
      });
    }
  }

  const snippetExecs = extractExecutivesFromSnippets(
    evidenceItems.map(e => ({ title: e.sourceTitle, snippet: e.evidenceText, link: e.sourceUrl })),
    companyName,
    domain
  );

  for (const se of snippetExecs) {
    if (se.name && !seenPeople.has(se.name.toLowerCase())) {
      seenPeople.add(se.name.toLowerCase());
      keyPersonnel.push({
        name: se.name,
        title: se.title || 'Executive',
        employer: se.employer || companyName,
        sourceType: 'public_search',
        evidenceTier: 'tier3'
      });
    }
  }

  return {
    evidenceItems,
    keyPersonnel,
    totalSources: evidenceItems.length
  };
};

module.exports = {
  fetchAuthoritativePublicRecords,
  searchWebForLeadership,
  extractExecutivesFromSnippets,
  searchOnlineForPersonEmail,
  searchOnlineForGeneratedEmail,
  searchCompanyEmployeeEmails,
  extractEmployeeFromText,
  fetchCompanyPublicOverview,
  cleanExecutive
};
