from urllib.parse import urlparse
from bs4 import BeautifulSoup
from app.crawler.fetcher import fetch_page

def parse_sitemap(xml_content: str) -> list[str]:
    urls = []
    try:
        soup = BeautifulSoup(xml_content, "html.parser")
        for loc in soup.find_all("loc"):
            text = loc.get_text().strip()
            if text:
                urls.append(text)
    except Exception:
        pass
    return urls

async def fetch_sitemap(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    domain = f"{parsed.scheme}://{parsed.netloc}".lower()
    sitemap_urls = [
        f"{domain}/sitemap.xml",
        f"{domain}/sitemap_index.xml",
        f"{domain}/sitemap.txt"
    ]

    for sitemap_url in sitemap_urls:
        try:
            result = await fetch_page(sitemap_url, {"timeout": 5000})
            if result and result.get("statusCode") == 200:
                body = result.get("body", "")
                if sitemap_url.endswith(".txt"):
                    return [line.strip() for line in body.splitlines() if line.strip().startswith("http")]
                urls = parse_sitemap(body)
                if urls:
                    return urls
        except Exception:
            continue
    return []
