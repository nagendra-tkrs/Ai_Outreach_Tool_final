const { extractDomain, isSameDomain } = require('./urlUtils');

/**
 * Common bot protection, CAPTCHA, and WAF challenge patterns
 */
const CHALLENGE_SIGNATURES = [
  // Cloudflare
  /cf-browser-verification/i,
  /cf-challenge/i,
  /cf_chl_opt/i,
  /cf-turnstile/i,
  /__cf_chl_/i,
  /_cf_chl_tk/i,
  /challenge-form/i,
  /challenge-running/i,
  /Ray ID:\s*<code/i,
  /Cloudflare Ray ID:/i,
  /Attention Required!\s*\|\s*Cloudflare/i,
  /Just a moment\.\.\./i,
  /Checking your browser before accessing/i,
  /DDoS protection by Cloudflare/i,
  
  // CAPTCHAs & Bot Verification
  /g-recaptcha/i,
  /hcaptcha/i,
  /recaptcha\/api\.js/i,
  /hcaptcha\.com/i,
  /Verify you are human/i,
  /Complete the security check/i,
  /Solve the challenge/i,
  /Please verify that you are not a robot/i,
  /I'm not a robot/i,
  /captcha-box/i,
  /captcha-container/i,
  /bot verification/i,
  /security check/i,
  
  // WAF / Access Denials / Akamai / EdgeSuite
  /Access Denied/i,
  /403 Forbidden/i,
  /Forbidden - You don't have permission/i,
  /You don't have permission to access/i,
  /You do not have permission to access/i,
  /errors\.edgesuite\.net/i,
  /Reference\s*#/i,
  /Reference&#32;&#35;/i,
  /Request blocked/i,
  /Protected by DataDome/i,
  /datadome\.js/i,
  /Incapsula/i,
  /Imperva/i,
  /AkamaiGHost/i,
  /Akamai/i,
  /EdgeSuite/i,
  /PerimeterX/i,
  /Human Security/i,
  
  // Anti-bot JS interstitials
  /Please enable JavaScript and cookies to continue/i,
  /Turn on JavaScript and reload/i,
  /JavaScript is required to access this site/i,
  /You need to enable JavaScript to run this app/i
];

/**
 * Specific title signatures that indicate error or challenge pages
 */
const CHALLENGE_TITLE_PATTERNS = [
  /just a moment/i,
  /access denied/i,
  /attention required/i,
  /cloudflare/i,
  /403 forbidden/i,
  /forbidden/i,
  /bot verification/i,
  /verify you are human/i,
  /security check/i,
  /ddos-guard/i,
  /page not found/i,
  /404 not found/i,
  /500 internal server error/i,
  /502 bad gateway/i,
  /503 service unavailable/i,
  /504 gateway timeout/i
];

/**
 * Detect whether HTML, title, text, or headers represent a challenge or bot-protection block
 */
const detectBotProtection = (html = '', title = '', text = '', headers = {}) => {
  const cleanHtml = html || '';
  const cleanTitle = title || '';
  const cleanText = text || '';

  // 1. Check Response Headers
  if (headers && typeof headers === 'object') {
    const cfMitigated = headers['cf-mitigated'];
    if (cfMitigated === 'challenge' || cfMitigated === 'blocked') {
      return { isBlocked: true, reason: 'Cloudflare challenge header detected (cf-mitigated)' };
    }
    const serverHeader = (headers['server'] || '').toLowerCase();
    if (serverHeader.includes('cloudflare') && (cleanTitle.toLowerCase().includes('just a moment') || cleanText.toLowerCase().includes('ray id'))) {
      return { isBlocked: true, reason: 'Cloudflare challenge page detected' };
    }
  }

  // 2. Check Title
  for (const pat of CHALLENGE_TITLE_PATTERNS) {
    if (pat.test(cleanTitle)) {
      return { isBlocked: true, reason: `Challenge or error title detected: "${cleanTitle}"` };
    }
  }

  // 3. Check HTML and Body text for known challenge signatures
  for (const sig of CHALLENGE_SIGNATURES) {
    if (sig.test(cleanHtml) || sig.test(cleanText)) {
      return { isBlocked: true, reason: `Bot-protection signature matched: ${sig}` };
    }
  }

  return { isBlocked: false, reason: '' };
};

/**
 * Validate a crawled page response before storing it or passing it to AI
 */
const validateCrawledPage = ({
  url,
  finalUrl,
  statusCode = 200,
  contentType = '',
  body = '',
  extracted = {},
  baseDomain = ''
}) => {
  const finalUrlStr = finalUrl || url;
  const content = extracted.content || '';
  const title = extracted.title || '';
  const wordCount = extracted.wordCount || 0;
  const bodyLength = (body || '').length;

  // 1. HTTP Status Code validation
  if (statusCode === 403) {
    return {
      isValid: false,
      crawlStatus: 'blocked',
      contentAvailable: false,
      contentQuality: 'error',
      errorReason: 'HTTP 403 Access Denied / Forbidden',
      isChallengePage: true
    };
  }

  if (statusCode === 429) {
    return {
      isValid: false,
      crawlStatus: 'rate_limited',
      contentAvailable: false,
      contentQuality: 'error',
      errorReason: 'HTTP 429 Too Many Requests / Rate Limited',
      isChallengePage: false
    };
  }

  if (statusCode === 404) {
    return {
      isValid: false,
      crawlStatus: 'not_found',
      contentAvailable: false,
      contentQuality: 'error',
      errorReason: 'HTTP 404 Page Not Found',
      isChallengePage: false
    };
  }

  if (statusCode >= 500 && statusCode < 600) {
    return {
      isValid: false,
      crawlStatus: 'server_error',
      contentAvailable: false,
      contentQuality: 'error',
      errorReason: `HTTP ${statusCode} Server Error`,
      isChallengePage: false
    };
  }

  if (statusCode !== 200 && statusCode !== 201) {
    return {
      isValid: false,
      crawlStatus: 'failed',
      contentAvailable: false,
      contentQuality: 'error',
      errorReason: `HTTP status ${statusCode}`,
      isChallengePage: false
    };
  }

  // 2. Content-Type validation
  const cleanContentType = (contentType || '').toLowerCase();
  if (
    cleanContentType &&
    !cleanContentType.includes('text/html') &&
    !cleanContentType.includes('application/xhtml+xml') &&
    !cleanContentType.includes('text/plain')
  ) {
    return {
      isValid: false,
      crawlStatus: 'invalid_content',
      contentAvailable: false,
      contentQuality: 'error',
      errorReason: `Unsupported content type: ${contentType}`,
      isChallengePage: false
    };
  }

  // 3. Domain validation
  if (baseDomain && !isSameDomain(finalUrlStr, baseDomain)) {
    return {
      isValid: false,
      crawlStatus: 'blocked',
      contentAvailable: false,
      contentQuality: 'error',
      errorReason: `Redirected to external domain: ${finalUrlStr}`,
      isChallengePage: false
    };
  }

  // 4. Challenge / Bot-Protection detection (even when HTTP is 200)
  const challengeCheck = detectBotProtection(body, title, content);
  if (challengeCheck.isBlocked) {
    return {
      isValid: false,
      crawlStatus: 'blocked',
      contentAvailable: false,
      contentQuality: 'error',
      errorReason: challengeCheck.reason,
      isChallengePage: true
    };
  }

  // 5. Content Length & Quality validation
  if (bodyLength < 100) {
    return {
      isValid: false,
      crawlStatus: 'invalid_content',
      contentAvailable: false,
      contentQuality: 'empty',
      errorReason: `Response body too small (${bodyLength} bytes)`,
      isChallengePage: false
    };
  }

  if (wordCount < 15 || content.trim().length < 50) {
    // Check if it's an empty JavaScript SPA shell
    if (body.includes('<div id="root">') || body.includes('<div id="app">') || body.includes('__NEXT_DATA__')) {
      return {
        isValid: false,
        crawlStatus: 'invalid_content',
        contentAvailable: false,
        contentQuality: 'empty',
        errorReason: 'Client-side rendered SPA shell with no static text content',
        isChallengePage: false
      };
    }

    return {
      isValid: false,
      crawlStatus: 'invalid_content',
      contentAvailable: false,
      contentQuality: 'low',
      errorReason: `Insufficient meaningful text content (${wordCount} words)`,
      isChallengePage: false
    };
  }

  // All checks passed!
  return {
    isValid: true,
    crawlStatus: 'completed',
    contentAvailable: true,
    contentQuality: 'valid',
    errorReason: '',
    isChallengePage: false
  };
};

module.exports = {
  detectBotProtection,
  validateCrawledPage,
  CHALLENGE_SIGNATURES,
  CHALLENGE_TITLE_PATTERNS
};
