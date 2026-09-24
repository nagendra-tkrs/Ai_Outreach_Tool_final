import os
import re
import html as html_lib
import asyncio
import time
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, unquote
import httpx

_circuit_broken_until = 0.0

def is_circuit_open() -> bool:
    global _circuit_broken_until
    return time.time() < _circuit_broken_until

def trip_circuit(cooldown_sec: float = 120.0):
    global _circuit_broken_until
    _circuit_broken_until = time.time() + cooldown_sec

def reset_circuit():
    global _circuit_broken_until
    _circuit_broken_until = 0.0

def env_int(name: str, fallback: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == '':
        return fallback
    try:
        n = int(raw)
        return n if n >= 0 else fallback
    except ValueError:
        return fallback

SEARCH_TIMEOUT_MS = env_int('SEARCH_TIMEOUT_MS', 2500)
SEARCH_MAX_RETRIES = env_int('SEARCH_MAX_RETRIES', 0)
SEARCH_RETRY_DELAY_MS = env_int('SEARCH_RETRY_DELAY_MS', 300)

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
DUMPLING_URL = 'https://html.duckduckgo.com/html'

def decode_redirect_url(raw_url: str = '') -> str:
    if not raw_url:
        return ''
    try:
        parsed = urlparse(raw_url)
        query_params = parse_qs(parsed.query)
        uddg = query_params.get('uddg')
        if uddg:
            return unquote(uddg[0])
        return raw_url if raw_url.startswith('http') else ''
    except Exception:
        return raw_url

def is_configured() -> bool:
    return True

def is_challenge_or_blocked_page(html_text: str = '') -> bool:
    if not html_text:
        return False
    lower = html_text[:20000].lower()
    markers = [
        'anomaly', 'unusual traffic', 'captcha', 'are you a robot',
        'verify you are human', 'attention required', 'ddg_anomaly',
        'please wait while we redirect', '<title>blocked</title>',
        'access denied', '403 forbidden'
    ]
    return any(m in lower for m in markers)

def strip_html(input_str: str = '') -> str:
    if not input_str:
        return ''
    text = re.sub(r'<[^>]+>', ' ', input_str)
    text = html_lib.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_domain(url: str = '') -> str:
    try:
        hostname = urlparse(url).hostname or ''
        return re.sub(r'^www\.', '', hostname, flags=re.IGNORECASE).lower()
    except Exception:
        return ''

def parse_duckduckgo_html(html_text: str) -> list[dict]:
    results = []
    if not html_text:
        return results
    seen = set()

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_text, 'html.parser')
        bodies = soup.find_all('div', class_=re.compile(r'result__body'))
        for body in bodies:
            a_title = body.find('a', class_=re.compile(r'result__a'))
            a_snippet = body.find('a', class_=re.compile(r'result__snippet')) or body.find('div', class_=re.compile(r'result__snippet'))

            title = a_title.get_text().strip() if a_title else ''
            raw_href = a_title.get('href', '') if a_title else ''
            url = decode_redirect_url(raw_href)
            snippet = a_snippet.get_text().strip() if a_snippet else ''

            if not title or not url or url in seen:
                continue
            seen.add(url)
            results.append({
                'title': title,
                'url': url,
                'snippet': snippet,
                'sourceDomain': extract_domain(url),
                'position': len(results) + 1
            })
    except Exception:
        return []

async def execute_public_web_search(query: str, options: dict = None) -> dict:
    if options is None:
        options = {}

    if not query:
        return {
            'query': query,
            'results': [],
            'provider': 'public_web',
            'source': 'duckduckgo',
            'configured': True,
            'error': 'EMPTY_QUERY',
            'state': 'NO_RESULTS',
            'retrievedAt': datetime.now(timezone.utc).isoformat()
        }

    if is_circuit_open():
        return {
            'query': query,
            'results': [],
            'provider': 'public_web',
            'source': 'duckduckgo',
            'configured': True,
            'error': 'SEARCH_CIRCUIT_OPEN',
            'state': 'SEARCH_UNAVAILABLE',
            'retrievedAt': datetime.utcnow().isoformat()
        }

    timeout_ms = options.get('timeoutMs') or SEARCH_TIMEOUT_MS
    timeout_sec = min(timeout_ms / 1000.0, 3.5)
    max_retries = env_int('SEARCH_MAX_RETRIES', SEARCH_MAX_RETRIES)
    retry_delay_sec = env_int('SEARCH_RETRY_DELAY_MS', SEARCH_RETRY_DELAY_MS) / 1000.0
    url = f"{DUMPLING_URL}/"

    last_error = ''
    last_state = 'SEARCH_UNAVAILABLE'

    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'User-Agent': USER_AGENT,
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache'
    }

    async with httpx.AsyncClient(verify=False) as client:
        # First attempt DuckDuckGo
        ddg_success = False
        for attempt in range(max_retries + 1):
            try:
                res = await client.get(url, params={'q': query}, headers=headers, timeout=timeout_sec)
                status_code = res.status_code
                if status_code in (403, 401, 429):
                    last_error = f'DuckDuckGo blocked the request (HTTP {status_code})'
                    last_state = 'SEARCH_BLOCKED'
                    trip_circuit(60.0)
                    break

                if status_code != 200:
                    last_error = f'DuckDuckGo returned HTTP {status_code}'
                    last_state = 'SEARCH_UNAVAILABLE'
                    break

                html_content = res.text
                if is_challenge_or_blocked_page(html_content):
                    last_error = 'DuckDuckGo served a challenge/rate-limit page'
                    last_state = 'SEARCH_BLOCKED'
                    trip_circuit(60.0)
                    break

                results = parse_duckduckgo_html(html_content)
                if results:
                    return {
                        'query': query,
                        'results': results,
                        'provider': 'public_web',
                        'source': 'duckduckgo',
                        'configured': True,
                        'state': 'OK',
                        'retrievedAt': datetime.utcnow().isoformat()
                    }

                last_error = 'DuckDuckGo returned no results'
                last_state = 'NO_RESULTS'
                break
            except (httpx.TimeoutException, Exception) as e:
                last_error = str(e) or 'DuckDuckGo request failed'
                last_state = 'SEARCH_TIMEOUT' if isinstance(e, httpx.TimeoutException) else 'SEARCH_UNAVAILABLE'
                break

            if attempt < max_retries:
                await asyncio.sleep(retry_delay_sec)

    return {
        'query': query,
        'results': [],
        'provider': 'public_web',
        'source': 'duckduckgo',
        'configured': True,
        'state': last_state,
        'error': last_error or 'NO_RESULTS',
        'retrievedAt': datetime.now(timezone.utc).isoformat()
    }
