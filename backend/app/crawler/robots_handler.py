import urllib.robotparser
from urllib.parse import urlparse
from app.crawler.fetcher import fetch_page, DEFAULT_USER_AGENT

robots_cache = {}

async def fetch_robots_txt(base_url: str):
    try:
        parsed = urlparse(base_url)
        domain = f"{parsed.scheme}://{parsed.netloc}".lower()
        if domain in robots_cache:
            return robots_cache[domain]

        robots_url = f"{domain}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        try:
            result = await fetch_page(robots_url, {"timeout": 5000, "maxRetries": 1})
            if result and result.get("statusCode") == 200 and result.get("body"):
                rp.parse(result["body"].splitlines())
                robots_cache[domain] = rp
                return rp
        except Exception:
            pass

        # Allow all by default
        rp.parse(["User-agent: *", "Allow: /"])
        robots_cache[domain] = rp
        return rp
    except Exception:
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(["User-agent: *", "Allow: /"])
        return rp

async def is_allowed(url: str, user_agent: str = DEFAULT_USER_AGENT) -> bool:
    try:
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}".lower()
        rp = await fetch_robots_txt(domain)
        if not rp:
            return True
        allowed = rp.can_fetch(user_agent, url)
        return allowed if allowed is not None else True
    except Exception:
        return True

async def get_sitemaps(base_url: str) -> list[str]:
    try:
        parsed = urlparse(base_url)
        domain = f"{parsed.scheme}://{parsed.netloc}".lower()
        rp = await fetch_robots_txt(domain)
        if not rp:
            return []
        sitemaps = rp.site_maps()
        return sitemaps if isinstance(sitemaps, list) else []
    except Exception:
        return []

def clear_cache():
    robots_cache.clear()
