const { detectBotProtection, validateCrawledPage } = require('../contentValidator');

describe('Content Validator', () => {
  describe('detectBotProtection', () => {
    test('detects Cloudflare "Just a moment..." challenge title', () => {
      const result = detectBotProtection('<html><body>Checking...</body></html>', 'Just a moment...', 'Checking your browser');
      expect(result.isBlocked).toBe(true);
      expect(result.reason).toContain('Challenge or error title detected');
    });

    test('detects Cloudflare cf-browser-verification signature in HTML', () => {
      const html = '<div class="cf-browser-verification cf-challenge">Please wait...</div>';
      const result = detectBotProtection(html, 'Loading', 'Please wait');
      expect(result.isBlocked).toBe(true);
      expect(result.reason).toContain('Bot-protection signature matched');
    });

    test('detects Cloudflare Ray ID and cf-turnstile', () => {
      const html = '<div>Ray ID: <code class="ray-id">82736182736</code></div><div class="cf-turnstile"></div>';
      const result = detectBotProtection(html, 'Security', 'Ray ID: 82736182736');
      expect(result.isBlocked).toBe(true);
    });

    test('detects CAPTCHA signatures', () => {
      const html = '<div class="g-recaptcha" data-sitekey="xyz"></div><p>Verify you are human</p>';
      const result = detectBotProtection(html, 'Verification', 'Verify you are human');
      expect(result.isBlocked).toBe(true);
    });

    test('detects WAF / Access Denied text', () => {
      const html = '<h1>403 Forbidden</h1><p>Access Denied. You do not have permission.</p>';
      const result = detectBotProtection(html, 'Access Denied', 'Access Denied');
      expect(result.isBlocked).toBe(true);
    });

    test('detects TCS Akamai errors.edgesuite.net block signature', () => {
      const html = '<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD><BODY><H1>Access Denied</H1>You don\'t have permission to access "http://www.tcs.com/" on this server.<P>Reference&#32;&#35;18.82736182.1698273618.2837182<P>https://errors.edgesuite.net/18.82736182.1698273618.2837182</BODY></HTML>';
      const result = detectBotProtection(html, 'Access Denied', 'Access Denied You don\'t have permission to access on this server errors.edgesuite.net');
      expect(result.isBlocked).toBe(true);
    });

    test('returns isBlocked: false for normal valid company content', () => {
      const html = '<h1>Welcome to Acme Corp</h1><p>We build enterprise cloud analytics solutions for global teams.</p>';
      const result = detectBotProtection(html, 'Acme Corp - Enterprise Solutions', 'We build enterprise cloud analytics solutions for global teams.');
      expect(result.isBlocked).toBe(false);
      expect(result.reason).toBe('');
    });
  });

  describe('validateCrawledPage', () => {
    const validExtracted = {
      title: 'Acme Software Solutions',
      content: 'Acme Software provides enterprise grade cloud architecture, artificial intelligence consulting, data engineering pipelines, and cybersecurity services for Fortune 500 companies around the globe.',
      wordCount: 22
    };

    test('accepts valid 200 HTML with rich content', () => {
      const result = validateCrawledPage({
        url: 'https://acme.com',
        finalUrl: 'https://acme.com',
        statusCode: 200,
        contentType: 'text/html; charset=utf-8',
        body: '<html><head><title>Acme</title></head><body>' + validExtracted.content + '</body></html>',
        extracted: validExtracted,
        baseDomain: 'acme.com'
      });

      expect(result.isValid).toBe(true);
      expect(result.crawlStatus).toBe('completed');
      expect(result.contentAvailable).toBe(true);
      expect(result.contentQuality).toBe('valid');
      expect(result.errorReason).toBe('');
    });

    test('classifies HTTP 403 as BLOCKED', () => {
      const result = validateCrawledPage({
        url: 'https://acme.com',
        statusCode: 403,
        contentType: 'text/html',
        body: 'Access Denied',
        extracted: { content: 'Access Denied', wordCount: 2 },
        baseDomain: 'acme.com'
      });

      expect(result.isValid).toBe(false);
      expect(result.crawlStatus).toBe('blocked');
      expect(result.contentAvailable).toBe(false);
      expect(result.isChallengePage).toBe(true);
    });

    test('classifies HTTP 429 as RATE_LIMITED', () => {
      const result = validateCrawledPage({
        url: 'https://acme.com',
        statusCode: 429,
        contentType: 'text/html',
        body: 'Too Many Requests',
        extracted: { content: 'Too Many Requests', wordCount: 3 },
        baseDomain: 'acme.com'
      });

      expect(result.isValid).toBe(false);
      expect(result.crawlStatus).toBe('rate_limited');
      expect(result.contentAvailable).toBe(false);
    });

    test('classifies HTTP 404 as NOT_FOUND', () => {
      const result = validateCrawledPage({
        url: 'https://acme.com/old-page',
        statusCode: 404,
        contentType: 'text/html',
        body: 'Not Found',
        extracted: { content: 'Not Found', wordCount: 2 },
        baseDomain: 'acme.com'
      });

      expect(result.isValid).toBe(false);
      expect(result.crawlStatus).toBe('not_found');
      expect(result.contentAvailable).toBe(false);
    });

    test('classifies HTTP 500 as SERVER_ERROR', () => {
      const result = validateCrawledPage({
        url: 'https://acme.com',
        statusCode: 500,
        contentType: 'text/html',
        body: 'Internal Server Error',
        extracted: { content: 'Internal Server Error', wordCount: 3 },
        baseDomain: 'acme.com'
      });

      expect(result.isValid).toBe(false);
      expect(result.crawlStatus).toBe('server_error');
      expect(result.contentAvailable).toBe(false);
    });

    test('classifies HTTP 200 Cloudflare challenge page as BLOCKED', () => {
      const challengeBody = '<html><head><title>Just a moment...</title></head><body><div class="cf-browser-verification">Checking your browser before accessing acme.com</div></body></html>';
      const result = validateCrawledPage({
        url: 'https://acme.com',
        finalUrl: 'https://acme.com',
        statusCode: 200,
        contentType: 'text/html',
        body: challengeBody,
        extracted: { title: 'Just a moment...', content: 'Checking your browser before accessing acme.com', wordCount: 6 },
        baseDomain: 'acme.com'
      });

      expect(result.isValid).toBe(false);
      expect(result.crawlStatus).toBe('blocked');
      expect(result.contentAvailable).toBe(false);
      expect(result.isChallengePage).toBe(true);
    });

    test('classifies HTTP 200 CAPTCHA challenge as BLOCKED', () => {
      const captchaBody = '<html><head><title>Security Check</title></head><body><div class="g-recaptcha"></div><p>Please solve the challenge to continue.</p></body></html>';
      const result = validateCrawledPage({
        url: 'https://acme.com',
        finalUrl: 'https://acme.com',
        statusCode: 200,
        contentType: 'text/html',
        body: captchaBody,
        extracted: { title: 'Security Check', content: 'Please solve the challenge to continue', wordCount: 6 },
        baseDomain: 'acme.com'
      });

      expect(result.isValid).toBe(false);
      expect(result.crawlStatus).toBe('blocked');
      expect(result.contentAvailable).toBe(false);
    });

    test('classifies empty or ultra-short HTML as INVALID_CONTENT', () => {
      const result = validateCrawledPage({
        url: 'https://acme.com',
        finalUrl: 'https://acme.com',
        statusCode: 200,
        contentType: 'text/html',
        body: '<html><body></body></html>',
        extracted: { title: '', content: '', wordCount: 0 },
        baseDomain: 'acme.com'
      });

      expect(result.isValid).toBe(false);
      expect(result.crawlStatus).toBe('invalid_content');
      expect(result.contentAvailable).toBe(false);
    });

    test('classifies client-side JS empty SPA shell as INVALID_CONTENT', () => {
      const spaBody = '<html><head><title>App</title><script src="/bundle.js"></script></head><body><div id="root"></div></body></html>';
      const result = validateCrawledPage({
        url: 'https://acme.com',
        finalUrl: 'https://acme.com',
        statusCode: 200,
        contentType: 'text/html',
        body: spaBody,
        extracted: { title: 'App', content: '', wordCount: 0 },
        baseDomain: 'acme.com'
      });

      expect(result.isValid).toBe(false);
      expect(result.crawlStatus).toBe('invalid_content');
      expect(result.errorReason).toContain('SPA shell');
    });

    test('rejects off-domain redirect', () => {
      const result = validateCrawledPage({
        url: 'https://acme.com/promo',
        finalUrl: 'https://unrelated-third-party.com',
        statusCode: 200,
        contentType: 'text/html',
        body: '<html><body>' + validExtracted.content + '</body></html>',
        extracted: validExtracted,
        baseDomain: 'acme.com'
      });

      expect(result.isValid).toBe(false);
      expect(result.crawlStatus).toBe('blocked');
      expect(result.errorReason).toContain('Redirected to external domain');
    });
  });
});
