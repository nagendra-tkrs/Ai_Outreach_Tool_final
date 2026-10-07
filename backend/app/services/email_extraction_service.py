import re
import html
from urllib.parse import urlparse, unquote
from bs4 import BeautifulSoup

# File extensions that should never be considered top-level domains or email endings
INVALID_EMAIL_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "svg", "webp", "ico",
    "js", "css", "woff", "woff2", "ttf", "eot", "mp4",
    "mp3", "pdf", "zip", "tar", "gz", "exe"
}

EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# Common obfuscation patterns:
# name [at] domain.com
# name (at) domain.com
# name [dot] domain [dot] com
# name at domain dot com
OBFUSCATED_PATTERNS = [
    re.compile(r"([A-Za-z0-9._%+-]+)\s*\[\s*at\s*\]\s*([A-Za-z0-9.-]+)\s*\[\s*dot\s*\]\s*([A-Za-z]{2,})", re.I),
    re.compile(r"([A-Za-z0-9._%+-]+)\s*\(\s*at\s*\)\s*([A-Za-z0-9.-]+)\s*\(\s*dot\s*\)\s*([A-Za-z]{2,})", re.I),
    re.compile(r"([A-Za-z0-9._%+-]+)\s*\[\s*at\s*\]\s*([A-Za-z0-9.-]+\.[A-Za-z]{2,})", re.I),
    re.compile(r"([A-Za-z0-9._%+-]+)\s*\(\s*at\s*\)\s*([A-Za-z0-9.-]+\.[A-Za-z]{2,})", re.I),
    re.compile(r"([A-Za-z0-9._%+-]+)\s+at\s+([A-Za-z0-9.-]+)\s+dot\s+([A-Za-z]{2,})", re.I),
]

def decode_cloudflare_email(cf_hex: str) -> str:
    """Decodes Cloudflare's __cf_email__ protection."""
    try:
        r = int(cf_hex[:2], 16)
        email_chars = []
        for i in range(2, len(cf_hex), 2):
            email_chars.append(chr(int(cf_hex[i:i+2], 16) ^ r))
        return "".join(email_chars)
    except Exception:
        return ""

def clean_email(email_str: str) -> str:
    """Normalizes an email address, trimming punctuation and trailing characters."""
    if not email_str:
        return ""
    em = html.unescape(email_str).strip()
    # Strip query params if from mailto (e.g. ?subject=...)
    if "?" in em:
        em = em.split("?")[0]
    em = re.sub(r"^mailto:", "", em, flags=re.I).strip()
    em = em.strip(" \t\r\n.,;:<>\"'()[]{}")
    em = em.lower()

    if "@" not in em:
        return ""
    local, _, domain = em.partition("@")
    if not local or not domain or "." not in domain:
        return ""
    # Check trailing extension
    ext = domain.split(".")[-1].lower()
    if ext in INVALID_EMAIL_EXTENSIONS:
        return ""
    return f"{local}@{domain}"

def extract_emails_from_text(text: str) -> list[str]:
    """Extracts both direct and obfuscated emails from plain text."""
    if not text:
        return []
    found = set()
    unescaped = html.unescape(text)

    # 1. Standard regex matches
    for match in EMAIL_REGEX.findall(unescaped):
        cleaned = clean_email(match)
        if cleaned:
            found.add(cleaned)

    # 2. De-obfuscate common patterns
    for pat in OBFUSCATED_PATTERNS:
        for groups in pat.findall(unescaped):
            if len(groups) == 3:
                recovered = f"{groups[0]}@{groups[1]}.{groups[2]}"
            elif len(groups) == 2:
                recovered = f"{groups[0]}@{groups[1]}"
            else:
                continue
            cleaned = clean_email(recovered)
            if cleaned:
                found.add(cleaned)

    return sorted(list(found))

def extract_emails_from_html(html_content: str, base_url: str = "") -> list[dict]:
    """
    Extracts emails from an HTML page across all elements:
    - HTML text
    - <a href="mailto:...">
    - data-* attributes
    - Cloudflare protected emails
    Returns list of dicts:
        [{'email': str, 'source_type': str, 'context': str}]
    """
    if not html_content:
        return []

    results = []
    seen = set()

    def add_result(em: str, source_type: str, context: str = ""):
        cleaned = clean_email(em)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            results.append({
                "email": cleaned,
                "source_type": source_type,
                "context": (context[:300] if context else "").strip()
            })

    # 1. Cloudflare protected emails
    for cf_match in re.finditer(r'data-cfemail=["\']([a-f0-9]+)["\']', html_content, re.I):
        decoded = decode_cloudflare_email(cf_match.group(1))
        if decoded:
            add_result(decoded, "cloudflare_attribute", "Decoded Cloudflare protected email")

    try:
        soup = BeautifulSoup(html_content, "html.parser")

        # 2. Mailto links
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.lower().startswith("mailto:"):
                raw_mail = href[7:].split("?")[0]
                parent_text = a.parent.get_text() if a.parent else a.get_text()
                add_result(raw_mail, "mailto_link", parent_text)

        # 3. HTML attributes: data-email, data-mail, content
        for tag in soup.find_all(attrs=True):
            for attr_name in ["data-email", "data-mail", "data-user-email", "data-contact"]:
                if attr_name in tag.attrs:
                    val = tag.attrs[attr_name]
                    if val and isinstance(val, str) and "@" in val:
                        add_result(val, f"attribute:{attr_name}", tag.get_text())

        # 4. Text and obfuscated text within DOM
        plain_text = soup.get_text(separator=" ")
        for em in extract_emails_from_text(plain_text):
            add_result(em, "body_text")

    except Exception:
        # Fallback to direct text regex if soup parsing fails
        for em in extract_emails_from_text(html_content):
            add_result(em, "raw_html_regex")

    return results
