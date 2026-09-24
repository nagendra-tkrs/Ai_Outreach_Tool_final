import re
from app.crawler.url_utils import is_same_domain

CHALLENGE_SIGNATURES = [
    # Cloudflare
    re.compile(r'cf-browser-verification', re.I),
    re.compile(r'cf-challenge', re.I),
    re.compile(r'cf_chl_opt', re.I),
    re.compile(r'cf-turnstile', re.I),
    re.compile(r'__cf_chl_', re.I),
    re.compile(r'_cf_chl_tk', re.I),
    re.compile(r'challenge-form', re.I),
    re.compile(r'challenge-running', re.I),
    re.compile(r'Ray ID:\s*<code', re.I),
    re.compile(r'Cloudflare Ray ID:', re.I),
    re.compile(r'Attention Required!\s*\|\s*Cloudflare', re.I),
    re.compile(r'Just a moment\.\.\.', re.I),
    re.compile(r'Checking your browser before accessing', re.I),
    re.compile(r'DDoS protection by Cloudflare', re.I),

    # CAPTCHAs & Bot Verification (Gate/Interstitial Signatures)
    re.compile(r'Verify you are human', re.I),
    re.compile(r'Complete the security check', re.I),
    re.compile(r'Solve the challenge', re.I),
    re.compile(r'Please verify that you are not a robot', re.I),
    re.compile(r"I'm not a robot", re.I),
    re.compile(r'captcha-box', re.I),
    re.compile(r'captcha-container', re.I),
    re.compile(r'bot verification', re.I),
    re.compile(r'security check', re.I),

    # WAF / Access Denials / Akamai
    re.compile(r'Access Denied', re.I),
    re.compile(r'403 Forbidden', re.I),
    re.compile(r"Forbidden - You don't have permission", re.I),
    re.compile(r"You don't have permission to access", re.I),
    re.compile(r"You do not have permission to access", re.I),
    re.compile(r'errors\.edgesuite\.net', re.I),
    re.compile(r'Reference\s*#', re.I),
    re.compile(r'Reference&#32;&#35;', re.I),
    re.compile(r'Request blocked', re.I),
    re.compile(r'Protected by DataDome', re.I),
    re.compile(r'datadome\.js', re.I),
    re.compile(r'Incapsula', re.I),
    re.compile(r'Imperva', re.I),
    re.compile(r'AkamaiGHost', re.I),
    re.compile(r'Akamai', re.I),
    re.compile(r'EdgeSuite', re.I),
    re.compile(r'PerimeterX', re.I),
    re.compile(r'Human Security', re.I),

    # Anti-bot JS interstitials
    re.compile(r'Please enable JavaScript and cookies to continue', re.I),
    re.compile(r'Turn on JavaScript and reload', re.I),
    re.compile(r'JavaScript is required to access this site', re.I),
    re.compile(r'You need to enable JavaScript to run this app', re.I)
]

CHALLENGE_TITLE_PATTERNS = [
    re.compile(r'just a moment', re.I),
    re.compile(r'access denied', re.I),
    re.compile(r'attention required', re.I),
    re.compile(r'cloudflare', re.I),
    re.compile(r'403 forbidden', re.I),
    re.compile(r'forbidden', re.I),
    re.compile(r'bot verification', re.I),
    re.compile(r'verify you are human', re.I),
    re.compile(r'security check', re.I),
    re.compile(r'ddos-guard', re.I),
    re.compile(r'page not found', re.I),
    re.compile(r'404 not found', re.I),
    re.compile(r'500 internal server error', re.I),
    re.compile(r'502 bad gateway', re.I),
    re.compile(r'503 service unavailable', re.I),
    re.compile(r'504 gateway timeout', re.I)
]

def detect_bot_protection(html: str = '', title: str = '', text: str = '', headers: dict = None) -> dict:
    clean_html = html or ''
    clean_title = title or ''
    clean_text = text or ''

    # 1. Response headers
    if headers and isinstance(headers, dict):
        cf_mitigated = str(headers.get('cf-mitigated', '')).lower()
        if cf_mitigated in ('challenge', 'blocked'):
            return {'isBlocked': True, 'reason': 'Cloudflare challenge header detected (cf-mitigated)'}
        server_header = str(headers.get('server', '')).lower()
        if 'cloudflare' in server_header and ('just a moment' in clean_title.lower() or 'ray id' in clean_text.lower()):
            return {'isBlocked': True, 'reason': 'Cloudflare challenge page detected'}

    # 2. Title patterns
    for pat in CHALLENGE_TITLE_PATTERNS:
        if pat.search(clean_title):
            return {'isBlocked': True, 'reason': f'Challenge or error title detected: "{clean_title}"'}

    # 3. HTML and Body text signatures
    for sig in CHALLENGE_SIGNATURES:
        if sig.search(clean_html) or sig.search(clean_text):
            return {'isBlocked': True, 'reason': f'Bot-protection signature matched: {sig.pattern}'}

    # 4. Form CAPTCHA signatures: only block if page is an interstitial challenge (minimal text or challenge title)
    form_captcha_patterns = [
        re.compile(r'g-recaptcha', re.I),
        re.compile(r'hcaptcha', re.I),
        re.compile(r'recaptcha/api\.js', re.I),
        re.compile(r'hcaptcha\.com', re.I),
    ]
    words_count = len(clean_text.split())
    if words_count < 30:
        for fpat in form_captcha_patterns:
            if fpat.search(clean_html) or fpat.search(clean_text):
                return {'isBlocked': True, 'reason': f'Captcha challenge gate detected ({fpat.pattern})'}

    return {'isBlocked': False, 'reason': ''}

def validate_crawled_page(data: dict) -> dict:
    url = data.get('url', '')
    final_url = data.get('finalUrl') or url
    status_code = data.get('statusCode', 200)
    content_type = data.get('contentType', '')
    body = data.get('body', '')
    extracted = data.get('extracted', {})
    base_domain = data.get('baseDomain', '')

    content = extracted.get('content', '')
    title = extracted.get('title', '')
    word_count = extracted.get('wordCount', 0)
    body_length = len(body or '')

    # 1. HTTP Status Code validation
    if status_code == 403:
        return {
            'isValid': False,
            'crawlStatus': 'blocked',
            'contentAvailable': False,
            'contentQuality': 'error',
            'errorReason': 'HTTP 403 Access Denied / Forbidden',
            'isChallengePage': True
        }

    if status_code == 429:
        return {
            'isValid': False,
            'crawlStatus': 'rate_limited',
            'contentAvailable': False,
            'contentQuality': 'error',
            'errorReason': 'HTTP 429 Too Many Requests / Rate Limited',
            'isChallengePage': False
        }

    if status_code == 404:
        return {
            'isValid': False,
            'crawlStatus': 'not_found',
            'contentAvailable': False,
            'contentQuality': 'error',
            'errorReason': 'HTTP 404 Page Not Found',
            'isChallengePage': False
        }

    if 500 <= status_code < 600:
        return {
            'isValid': False,
            'crawlStatus': 'server_error',
            'contentAvailable': False,
            'contentQuality': 'error',
            'errorReason': f'HTTP {status_code} Server Error',
            'isChallengePage': False
        }

    if status_code not in (200, 201):
        return {
            'isValid': False,
            'crawlStatus': 'failed',
            'contentAvailable': False,
            'contentQuality': 'error',
            'errorReason': f'HTTP status {status_code}',
            'isChallengePage': False
        }

    # 2. Content-Type validation
    clean_content_type = (content_type or '').lower()
    if (clean_content_type and
        'text/html' not in clean_content_type and
        'application/xhtml+xml' not in clean_content_type and
        'text/plain' not in clean_content_type):
        return {
            'isValid': False,
            'crawlStatus': 'invalid_content',
            'contentAvailable': False,
            'contentQuality': 'error',
            'errorReason': f'Unsupported content type: {content_type}',
            'isChallengePage': False
        }

    # 3. Domain validation
    if base_domain and not is_same_domain(final_url, base_domain):
        return {
            'isValid': False,
            'crawlStatus': 'blocked',
            'contentAvailable': False,
            'contentQuality': 'error',
            'errorReason': f'Redirected to external domain: {final_url}',
            'isChallengePage': False
        }

    # 4. Challenge / Bot-Protection detection
    challenge_check = detect_bot_protection(body, title, content)
    if challenge_check['isBlocked']:
        return {
            'isValid': False,
            'crawlStatus': 'blocked',
            'contentAvailable': False,
            'contentQuality': 'error',
            'errorReason': challenge_check['reason'],
            'isChallengePage': True
        }

    # 5. Content Length & Quality validation
    if body_length < 100:
        return {
            'isValid': False,
            'crawlStatus': 'invalid_content',
            'contentAvailable': False,
            'contentQuality': 'empty',
            'errorReason': f'Response body too small ({body_length} bytes)',
            'isChallengePage': False
        }

    if word_count < 15 or len(content.strip()) < 50:
        if '<div id="root">' in body or '<div id="app">' in body or '__NEXT_DATA__' in body:
            return {
                'isValid': False,
                'crawlStatus': 'invalid_content',
                'contentAvailable': False,
                'contentQuality': 'empty',
                'errorReason': 'Client-side rendered SPA shell with no static text content',
                'isChallengePage': False
            }

        return {
            'isValid': False,
            'crawlStatus': 'invalid_content',
            'contentAvailable': False,
            'contentQuality': 'low',
            'errorReason': f'Insufficient meaningful text content ({word_count} words)',
            'isChallengePage': False
        }

    return {
        'isValid': True,
        'crawlStatus': 'completed',
        'contentAvailable': True,
        'contentQuality': 'valid',
        'errorReason': '',
        'isChallengePage': False
    }
