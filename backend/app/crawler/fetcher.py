import os
import asyncio
import email.utils
import time
from urllib.parse import urljoin
import httpx

DEFAULT_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (compatible; B2BOutreachBot/1.0; +https://example.com/bot)'

DEFAULT_HEADERS = {
    'User-Agent': DEFAULT_USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Cache-Control': 'no-cache',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1'
}

USER_AGENT = DEFAULT_USER_AGENT

class FetchError(Exception):
    def __init__(self, message: str, status_code: int = 0, crawl_status: str = 'failed',
                 error_reason: str = '', content_type: str = '', body: str = '',
                 headers: dict = None, final_url: str = '', retry_after_ms: int = 0,
                 is_challenge_page: bool = False):
        super().__init__(message)
        self.statusCode = status_code
        self.crawlStatus = crawl_status
        self.errorReason = error_reason or message
        self.contentType = content_type
        self.body = body
        self.headers = headers or {}
        self.finalUrl = final_url
        self.retryAfterMs = retry_after_ms
        self.isChallengePage = is_challenge_page

def parse_retry_after(header_val: str) -> int:
    if not header_val:
        return 0
    try:
        seconds = int(header_val)
        return min(seconds * 1000, 10000)
    except ValueError:
        pass
    try:
        date_tuple = email.utils.parsedate_tz(header_val)
        if date_tuple:
            timestamp = email.utils.mktime_tz(date_tuple)
            diff = (timestamp - time.time()) * 1000
            return int(min(diff, 10000)) if diff > 0 else 1000
    except Exception:
        pass
    return 2000

async def fetch_single_attempt(client: httpx.AsyncClient, target_url: str,
                               timeout: float, max_page_size: int,
                               headers: dict = None, redirect_history: list = None):
    if redirect_history is None:
        redirect_history = []

    if len(redirect_history) > 5:
        raise FetchError('Too many redirects (> 5)', status_code=310, crawl_status='failed',
                         error_reason='Too many redirects (> 5)', final_url=target_url)

    if target_url in redirect_history:
        raise FetchError('Redirect loop detected', status_code=310, crawl_status='failed',
                         error_reason=f'Redirect loop detected for {target_url}', final_url=target_url)

    current_history = list(redirect_history) + [target_url]
    req_headers = {**DEFAULT_HEADERS, **(headers or {})}

    try:
        res = await client.get(target_url, headers=req_headers, follow_redirects=False, timeout=timeout)
    except httpx.TimeoutException:
        raise FetchError(f'Request timed out after {int(timeout*1000)}ms', status_code=0,
                         crawl_status='timeout', error_reason=f'Request timed out after {int(timeout*1000)}ms',
                         final_url=target_url)
    except Exception as e:
        raise FetchError(f'Network connection error: {str(e)}', status_code=0,
                         crawl_status='failed', error_reason=f'Network error: {str(e)}',
                         final_url=target_url)

    status_code = res.status_code
    content_type = res.headers.get('content-type', '')
    response_headers = dict(res.headers)

    # 1. Handle Redirects (301, 302, 303, 307, 308)
    if 300 <= status_code < 400:
        location = res.headers.get('location')
        if not location:
            raise FetchError(f'Redirect status {status_code} with no location header', status_code=status_code,
                             crawl_status='failed', error_reason=f'Redirect {status_code} missing Location header',
                             final_url=target_url)
        next_url = urljoin(target_url, location)
        return await fetch_single_attempt(client, next_url, timeout, max_page_size, headers, current_history)

    # 2. Handle HTTP 403 Forbidden / Blocked
    if status_code == 403:
        body = res.text if res else ""
        raise FetchError('HTTP 403: Access Denied / Forbidden', status_code=403, crawl_status='blocked',
                         error_reason='HTTP 403 Access Denied', content_type=content_type, body=body,
                         headers=response_headers, final_url=target_url, is_challenge_page=True)

    # 3. Handle HTTP 429 Rate Limit
    if status_code == 429:
        body = res.text if res else ""
        retry_after_ms = parse_retry_after(res.headers.get('retry-after')) or 2000
        raise FetchError('HTTP 429: Too Many Requests / Rate Limited', status_code=429, crawl_status='rate_limited',
                         error_reason='HTTP 429 Too Many Requests', content_type=content_type, body=body,
                         headers=response_headers, final_url=target_url, retry_after_ms=retry_after_ms)

    # 4. Handle HTTP 404 Not Found
    if status_code == 404:
        raise FetchError('HTTP 404: Page Not Found', status_code=404, crawl_status='not_found',
                         error_reason='HTTP 404 Page Not Found', final_url=target_url)

    # 5. Handle HTTP 5xx Server Errors
    if 500 <= status_code < 600:
        body = res.text if res else ""
        raise FetchError(f'HTTP {status_code}: Server Error', status_code=status_code, crawl_status='server_error',
                         error_reason=f'HTTP {status_code} Server Error', content_type=content_type, body=body,
                         headers=response_headers, final_url=target_url)

    # 6. Handle other 4xx errors
    if 400 <= status_code < 500:
        raise FetchError(f'HTTP {status_code}: Client Error', status_code=status_code, crawl_status='failed',
                         error_reason=f'HTTP {status_code} Client Error', final_url=target_url)

    # 7. Check Content-Type
    clean_type = content_type.lower()
    if ('text/html' not in clean_type and
        'application/xhtml+xml' not in clean_type and
        'text/plain' not in clean_type):
        raise FetchError(f'Unsupported content type: {content_type}', status_code=status_code,
                         crawl_status='invalid_content', error_reason=f'Unsupported content type: {content_type}',
                         final_url=target_url)

    # 8. Read Body with size limit
    body = res.text
    if len(body) > max_page_size:
        raise FetchError(f'Page size exceeds maximum limit ({len(body)} > {max_page_size})',
                         status_code=status_code, crawl_status='invalid_content',
                         error_reason='Page size too large', final_url=target_url)

    return {
        'statusCode': status_code,
        'contentType': content_type,
        'body': body,
        'finalUrl': target_url,
        'headers': response_headers
    }

try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

async def fetch_with_browser(url: str, timeout_sec: float = 12.0) -> dict:
    if not HAS_PLAYWRIGHT:
        raise FetchError("Playwright not installed", crawl_status="unsupported")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(user_agent=DEFAULT_USER_AGENT)
            res = await page.goto(url, timeout=int(timeout_sec * 1000), wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            content = await page.content()
            final_url = page.url or url
            status_code = res.status if res else 200
            return {
                'statusCode': status_code,
                'contentType': 'text/html',
                'body': content,
                'finalUrl': final_url,
                'headers': {}
            }
        finally:
            await browser.close()

async def fetch_page(url: str, options: dict = None) -> dict:
    if options is None:
        options = {}

    timeout_ms = options.get('timeout') or int(os.getenv('CRAWLER_TIMEOUT_MS', 10000))
    timeout_sec = timeout_ms / 1000.0
    max_page_size = options.get('maxPageSize') or int(os.getenv('MAX_PAGE_SIZE', 5000000))
    max_retries = options.get('maxRetries') if options.get('maxRetries') is not None else int(os.getenv('MAX_RETRIES', 2))
    headers = options.get('headers', {})

    # Attempt Playwright render if explicitly enabled or modern JS render requested
    if options.get("use_browser") and HAS_PLAYWRIGHT:
        try:
            return await fetch_with_browser(url, timeout_sec)
        except Exception:
            # Fall back seamlessly to httpx
            pass

    last_error = None

    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    async with httpx.AsyncClient(limits=limits, verify=False) as client:
        for attempt in range(max_retries + 1):
            try:
                return await fetch_single_attempt(client, url, timeout_sec, max_page_size, headers)
            except FetchError as err:
                last_error = err
                # Do not retry non-retryable errors
                if (err.statusCode in (403, 404, 401, 410) or
                    err.crawlStatus in ('blocked', 'not_found', 'invalid_content')):
                    raise err

                if attempt < max_retries:
                    backoff_sec = (1000 * (2 ** attempt)) / 1000.0
                    if err.crawlStatus == 'rate_limited' and err.retryAfterMs:
                        backoff_sec = max(backoff_sec, err.retryAfterMs / 1000.0)
                    await asyncio.sleep(backoff_sec)

    raise last_error

async def fetch_url(url: str, options: dict = None) -> dict:
    return await fetch_page(url, options)
