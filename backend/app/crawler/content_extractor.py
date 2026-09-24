import re
from bs4 import BeautifulSoup

def extract_content(html: str, url: str = "") -> dict:
    if not html:
        return {
            "title": "",
            "metaDescription": "",
            "canonicalUrl": "",
            "headings": [],
            "content": "",
            "wordCount": 0
        }

    soup = BeautifulSoup(html, "html.parser")

    # Metadata
    title_tag = soup.find("title")
    title = title_tag.get_text().strip() if title_tag else ""

    meta_desc = ""
    desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if desc_tag and desc_tag.get("content"):
        meta_desc = desc_tag["content"].strip()

    canonical_url = ""
    canonical_tag = soup.find("link", attrs={"rel": re.compile(r"^canonical$", re.I)})
    if canonical_tag and canonical_tag.get("href"):
        canonical_url = canonical_tag["href"].strip()

    og_title = ""
    og_title_tag = soup.find("meta", attrs={"property": "og:title"})
    if og_title_tag and og_title_tag.get("content"):
        og_title = og_title_tag["content"].strip()

    og_desc = ""
    og_desc_tag = soup.find("meta", attrs={"property": "og:description"})
    if og_desc_tag and og_desc_tag.get("content"):
        og_desc = og_desc_tag["content"].strip()

    # Headings
    headings = []
    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = tag.get_text().strip()
        if text:
            level = int(tag.name[1])
            headings.append({"level": level, "text": text})

    # Remove boilerplate elements
    for el in soup.find_all(["script", "style", "noscript", "nav", "footer", "header", "iframe", "form"]):
        el.decompose()

    for el in soup.find_all(attrs={"role": ["navigation", "banner", "contentinfo"]}):
        el.decompose()

    # Find main content
    main_el = (soup.find("main") or
               soup.find("article") or
               soup.find(attrs={"role": "main"}) or
               soup.find(class_=re.compile(r"\b(main-content|content)\b", re.I)))

    if main_el:
        raw_text = main_el.get_text()
    elif soup.body:
        raw_text = soup.body.get_text()
    else:
        raw_text = soup.get_text()

    # Normalize whitespace
    content = re.sub(r'[ \t]+', ' ', raw_text)
    content = re.sub(r'\n+', '\n', content).strip()

    words = [w for w in re.split(r'\s+', content) if w]
    word_count = len(words)

    return {
        "title": og_title or title,
        "metaDescription": og_desc or meta_desc,
        "canonicalUrl": canonical_url,
        "headings": headings,
        "content": content,
        "wordCount": word_count
    }
