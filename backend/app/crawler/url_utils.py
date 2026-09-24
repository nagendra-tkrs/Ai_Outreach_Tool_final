import re
from urllib.parse import urlparse, urljoin, parse_qsl, urlencode

def normalize_url(url_str: str) -> str:
    if not url_str or not isinstance(url_str, str):
        return ""
    try:
        url = urlparse(url_str.strip())
        scheme = url.scheme.lower()
        netloc = url.netloc.lower()
        path = url.path.rstrip('/') or '/'
        # Sort query params
        params = sorted(parse_qsl(url.query))
        query = f"?{urlencode(params)}" if params else ""
        return f"{scheme}://{netloc}{path}{query}".lower()
    except Exception:
        return url_str.strip().lower()

def extract_domain(url_str: str) -> str:
    try:
        url = urlparse(url_str.strip())
        hostname = url.hostname or ""
        return re.sub(r'^www\.', '', hostname, flags=re.IGNORECASE).lower()
    except Exception:
        return ""

def is_same_domain(url_str: str, base_domain: str) -> bool:
    domain = extract_domain(url_str)
    base = base_domain.lower().strip()
    return domain == base or domain.endswith(f".{base}")

def resolve_url(base_url: str, relative_url: str) -> str:
    try:
        return urljoin(base_url, relative_url)
    except Exception:
        return ""

def filter_same_domain_links(links: list[str], base_domain: str) -> list[str]:
    seen = set()
    results = []
    ignored_exts = re.compile(r'\.(jpg|jpeg|png|gif|svg|webp|ico|css|js|pdf|zip|tar|gz|mp4|mp3|woff|woff2|ttf|eot)$', re.I)
    for link in links:
        if not link or not is_same_domain(link, base_domain):
            continue
        norm = normalize_url(link)
        if not norm or norm in seen:
            continue
        if ignored_exts.search(norm):
            continue
        seen.add(norm)
        results.append(norm)
    return results

def urls_are_equal(a: str, b: str) -> bool:
    return normalize_url(a) == normalize_url(b)
