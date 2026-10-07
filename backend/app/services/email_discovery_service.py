import os
import re
import time
import asyncio
import logging
from urllib.parse import urlparse, urljoin
import httpx
from bs4 import BeautifulSoup

from app.services.search_service import search_public_web, decode_redirect_url
from app.services.email_extraction_service import extract_emails_from_html, extract_emails_from_text, clean_email
from app.services.email_validation_service import (
    is_generic_email,
    is_free_email,
    validate_domain_match,
    match_person_to_email,
    normalize_text_token
)

logger = logging.getLogger("email_discovery")

# Target page crawl cache: url -> (timestamp, html_content)
_page_cache = {}
PAGE_CACHE_TTL = 3600.0  # 1 hour

async def crawl_target_page(url: str, timeout: float = 7.0) -> str:
    """Safely crawls a target webpage discovered from search results with caching."""
    if not url or not url.startswith("http"):
        return ""

    # Don't crawl obvious non-HTML media files
    ext = url.split("?")[0].split(".")[-1].lower()
    if ext in ("pdf", "docx", "xlsx", "zip", "png", "jpg", "jpeg", "mp4", "mp3"):
        return ""

    now = time.time()
    if url in _page_cache:
        cached_time, content = _page_cache[url]
        if now - cached_time < PAGE_CACHE_TTL:
            return content

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            res = await client.get(url, headers=headers)
            if res.status_code == 200 and "text/html" in res.headers.get("content-type", "").lower():
                content = res.text
                _page_cache[url] = (now, content)
                return content
    except Exception as e:
        logger.debug(f"[TargetPageCrawl] Failed to crawl {url}: {e}")
    return ""

def canonical_domain(url_or_domain: str) -> str:
    if not url_or_domain:
        return ""
    d = re.sub(r"^https?://", "", url_or_domain, flags=re.I)
    d = re.sub(r"^www\.", "", d, flags=re.I).split("/")[0].split(":")[0].strip().lower()
    return d

def render_pattern_email(pattern: str, person_name: str, domain: str) -> str:
    """Generates an email candidate from a verified pattern."""
    tokens = [normalize_text_token(t) for t in person_name.replace("-", " ").split() if normalize_text_token(t)]
    if not tokens:
        return ""
    first = tokens[0]
    last = tokens[-1] if len(tokens) > 1 else ""
    f_init = first[0] if first else ""
    l_init = last[0] if last else ""

    pat = pattern.lower().strip()
    local = ""
    if pat == "first.last" and first and last:
        local = f"{first}.{last}"
    elif pat == "first" and first:
        local = first
    elif pat == "firstlast" and first and last:
        local = f"{first}{last}"
    elif pat == "flast" and first and last:
        local = f"{f_init}{last}"
    elif pat == "f.last" and first and last:
        local = f"{f_init}.{last}"
    elif pat == "firstl" and first and last:
        local = f"{first}{l_init}"
    elif pat == "first.l" and first and last:
        local = f"{first}.{l_init}"
    elif pat == "last.first" and first and last:
        local = f"{last}.{first}"
    elif pat == "last" and last:
        local = last
    elif pat == "first_last" and first and last:
        local = f"{first}_{last}"

    if local and domain:
        return f"{local}@{domain}"
    return ""

def detect_email_pattern_from_pairs(pairs: list[dict], domain: str) -> dict:
    """
    Infers the company email pattern given confirmed (name, email) pairs.
    Anti-fabrication rules:
    - 0 pairs -> None
    - 1 pair -> INSUFFICIENT / WEAK (cannot generate)
    - 2 pairs -> Candidate pattern (SUPPORTED)
    - 3+ pairs -> Strong pattern evidence (STRONG)
    """
    if not pairs or len(pairs) < 2:
        return {
            "pattern": None,
            "confidence": "NONE" if not pairs else "INSUFFICIENT",
            "evidence_count": len(pairs),
            "patterns_observed": [],
            "can_generate": False
        }

    pattern_counts = {}
    distinct_people = set()

    for p in pairs:
        name = p.get("name", "")
        email = p.get("email", "")
        match_info = match_person_to_email(name, email)
        if match_info["matched"] and match_info["pattern"] != "none":
            pat = match_info["pattern"]
            pattern_counts[pat] = pattern_counts.get(pat, 0) + 1
            distinct_people.add(normalize_text_token(name))

    if not pattern_counts:
        return {
            "pattern": None,
            "confidence": "NONE",
            "evidence_count": 0,
            "patterns_observed": [],
            "can_generate": False
        }

    # Sort by frequency
    sorted_patterns = sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True)
    best_pattern, best_count = sorted_patterns[0]

    # Minimum 2 distinct people required
    if best_count >= 3 and len(distinct_people) >= 3:
        conf = "STRONG"
        can_gen = True
    elif best_count >= 2 and len(distinct_people) >= 2:
        conf = "SUPPORTED"
        can_gen = True
    else:
        conf = "INSUFFICIENT"
        can_gen = False

    return {
        "pattern": best_pattern if can_gen else None,
        "confidence": conf,
        "evidence_count": best_count,
        "patterns_observed": [{"pattern": k, "count": v} for k, v in sorted_patterns],
        "can_generate": can_gen
    }

async def discover_decision_maker_emails(
    candidates: list[dict],
    company_name: str,
    website: str,
    crawled_pages: list[dict] = None,
    direct_emails: list[str] = None,
    allowed_domains: list[str] = None,
    mx_status: str = "UNKNOWN"
) -> list[dict]:
    """
    Central Authoritative Email Discovery Pipeline:
    1. Official company website (direct crawled pages, leadership blocks, DOM cards, mailto:).
    2. Person-specific public search & TARGET PAGE CRAWLING (crawl target webpage from search results).
    3. Multi-person pattern detection (strict evidence threshold >= 2).
    4. Accurate status assignment without blanket NOT_FOUND coercion.
    """
    primary_domain = canonical_domain(website)
    domains_to_check = list(allowed_domains) if allowed_domains else ([primary_domain] if primary_domain else [])

    logger.info(f"EMAIL_DISCOVERY_START company='{company_name}' candidates={len(candidates)} domain='{primary_domain}'")

    verified_pairs = []
    enriched_candidates = []

    # -------------------------------------------------------------
    # STEP 1: Search Official Company Website Pages
    # -------------------------------------------------------------
    logger.info(f"OFFICIAL_SITE_SEARCH pages_available={len(crawled_pages or [])}")

    # Index emails on crawled pages with their surrounding HTML containers
    crawled_email_records = []
    if direct_emails:
        for em in direct_emails:
            crawled_email_records.append({
                "email": clean_email(em),
                "source_type": "official_website",
                "source_url": website,
                "context": "Direct website email"
            })

    if crawled_pages:
        for page in crawled_pages:
            p_html = page.get("html") or page.get("content") or ""
            p_url = page.get("url") or website
            if p_html:
                extracted = extract_emails_from_html(p_html, base_url=p_url)
                for item in extracted:
                    item["source_url"] = p_url
                    crawled_email_records.append(item)

    for cand in candidates:
        item = dict(cand)
        person_name = item.get("name", "").strip()
        exact_email = item.get("exact_email")
        source_url = item.get("source_url") or website
        source_type = item.get("source_type") or "official_website"
        evidence_text = item.get("evidence", "")

        # 1. Match from official crawled emails
        if not exact_email:
            for rec in crawled_email_records:
                em = rec["email"]
                if is_generic_email(em) or is_free_email(em):
                    continue
                dom_eval = validate_domain_match(em, primary_domain, domains_to_check)
                if not dom_eval["matched"]:
                    continue

                match_eval = match_person_to_email(person_name, em)
                if match_eval["matched"]:
                    exact_email = em
                    source_url = rec.get("source_url", website)
                    source_type = "official_website"
                    evidence_text = f"Found on official company page ({source_url}): {em} ({match_eval['reason']})"
                    logger.info(f"EMAIL_MATCH candidate='{em}' person='{person_name}' confidence={match_eval['confidence']}")
                    break

        item["exact_email"] = exact_email
        item["source_url"] = source_url
        item["source_type"] = source_type
        item["evidence"] = evidence_text
        enriched_candidates.append(item)

        if exact_email:
            verified_pairs.append({
                "name": person_name,
                "email": exact_email,
                "source_url": source_url,
                "evidence": evidence_text
            })

    # -------------------------------------------------------------
    # STEP 2: Person-Specific Search & TARGET PAGE CRAWLING
    # -------------------------------------------------------------
    for item in enriched_candidates:
        if item.get("exact_email"):
            continue

        person_name = item.get("name", "").strip()
        if not person_name:
            item["email_status"] = "NOT_FOUND"
            item["emailStatus"] = "NOT_FOUND"
            item["email_reason"] = "No person name provided"
            continue

        queries = [
            f'"{person_name}" "@{primary_domain}"',
            f'"{person_name}" "{company_name}" email',
            f'site:{primary_domain} "{person_name}"'
        ]

        search_attempts = 0
        search_status_encountered = "COMPLETED"
        search_error_encountered = None
        exact_found = None
        source_url_found = ""
        evidence_found = ""

        logger.info(f"DDG_SEARCH person='{person_name}' queries={len(queries)}")

        for q in queries:
            search_attempts += 1
            search_res = await search_public_web(q, max_results=3, timeout=10.0)
            status = search_res.get("status", "OK")

            if status in ("SEARCH_TIMEOUT", "SEARCH_UNAVAILABLE"):
                search_status_encountered = status
                search_error_encountered = search_res.get("error")
                continue

            results = search_res.get("results", [])
            if not results:
                continue

            # First pass: check snippet text
            for r in results:
                snippet_text = f"{r.get('title', '')} {r.get('snippet', '')}"
                snippet_emails = extract_emails_from_text(snippet_text)
                for em in snippet_emails:
                    if is_generic_email(em) or is_free_email(em):
                        continue
                    dom_eval = validate_domain_match(em, primary_domain, domains_to_check)
                    if dom_eval["matched"]:
                        match_eval = match_person_to_email(person_name, em)
                        if match_eval["matched"]:
                            exact_found = em
                            source_url_found = r.get("url", "")
                            evidence_found = f"Extracted from public search result for '{person_name}': {snippet_text[:200]}"
                            break
                if exact_found:
                    break

            if exact_found:
                break

            # CRITICAL STEP 2b: CRAWL TARGET WEBPAGES!
            # Search snippets rarely contain corporate emails directly, but target pages do!
            target_urls_to_crawl = [r.get("url") for r in results if r.get("url")][:2]
            for target_url in target_urls_to_crawl:
                if not target_url:
                    continue
                logger.info(f"TARGET_PAGE_CRAWL url='{target_url}' person='{person_name}'")
                page_html = await crawl_target_page(target_url, timeout=7.0)
                if not page_html:
                    continue

                page_extracted = extract_emails_from_html(page_html, base_url=target_url)
                for rec in page_extracted:
                    em = rec["email"]
                    if is_generic_email(em) or is_free_email(em):
                        continue
                    dom_eval = validate_domain_match(em, primary_domain, domains_to_check)
                    if dom_eval["matched"]:
                        match_eval = match_person_to_email(person_name, em)
                        if match_eval["matched"]:
                            exact_found = em
                            source_url_found = target_url
                            context_txt = rec.get("context") or "Found on target leadership/profile webpage"
                            evidence_found = f"Verified on public page ({target_url}): {em} ({context_txt[:150]})"
                            logger.info(f"EMAIL_MATCH candidate='{em}' person='{person_name}' confidence={match_eval['confidence']}")
                            break
                if exact_found:
                    break

            if exact_found:
                break

        if exact_found:
            item["exact_email"] = exact_found
            item["source_url"] = source_url_found
            item["source_type"] = "public_search"
            item["evidence"] = evidence_found
            verified_pairs.append({
                "name": person_name,
                "email": exact_found,
                "source_url": source_url_found,
                "evidence": evidence_found
            })
        else:
            item["search_status"] = search_status_encountered
            item["search_error"] = search_error_encountered

    # -------------------------------------------------------------
    # STEP 3: Pattern Detection Across Verified Company Emails
    # -------------------------------------------------------------
    pattern_info = detect_email_pattern_from_pairs(verified_pairs, primary_domain)
    detected_pattern = pattern_info.get("pattern")
    pattern_confidence = pattern_info.get("confidence", "NONE")
    can_generate_pattern = pattern_info.get("can_generate", False)

    logger.info(f"PATTERN_DETECTION pairs={len(verified_pairs)} pattern={detected_pattern} confidence={pattern_confidence}")

    # -------------------------------------------------------------
    # STEP 4: Final Status Assignment (Honest, Differentiated Statuses)
    # -------------------------------------------------------------
    final_contacts = []
    for item in enriched_candidates:
        exact_em = item.get("exact_email")
        person_name = item.get("name", "").strip()

        if exact_em:
            item["email"] = exact_em
            item["email_status"] = "EXACT_FOUND"
            item["emailStatus"] = "EXACT_FOUND"
            item["status"] = "verified"
            item["email_reason"] = f"Verified in public source ({item.get('source_url', website)})"
            item["emailReason"] = item["email_reason"]
            item["email_source_url"] = item.get("source_url", website)
            item["email_source_type"] = "OFFICIAL_WEBSITE" if item.get("source_type") == "official_website" else "PUBLIC_SEARCH"
            item["email_evidence"] = item.get("evidence", "")
            item["email_verification"] = "PUBLIC_EVIDENCE"
            item["emailVerificationMethod"] = "PUBLIC_EVIDENCE"
            item["mailbox_status"] = "UNVERIFIED"
            item["mailboxVerification"] = "UNVERIFIED"
            item["email_domain"] = exact_em.split("@")[1] if "@" in exact_em else primary_domain
            item["emailDomain"] = item["email_domain"]
            item["confidenceScore"] = 96
            item["generatedPattern"] = "none"
            item["generated_pattern"] = "none"
            item["pattern_confidence"] = "none"
            item["patternConfidence"] = "none"
            item["isExactPublished"] = True
            logger.info(f"EMAIL_DISCOVERY_RESULT person='{person_name}' status='EXACT_FOUND' email='{exact_em}'")

        elif can_generate_pattern and detected_pattern:
            generated_em = render_pattern_email(detected_pattern, person_name, primary_domain)
            if generated_em:
                item["email"] = generated_em
                item["email_status"] = "PATTERN_GENERATED"
                item["emailStatus"] = "PATTERN_GENERATED"
                item["status"] = "pattern_derived"
                item["email_reason"] = f"Inferred from {pattern_info['evidence_count']} verified company emails using pattern '{detected_pattern}'"
                item["emailReason"] = item["email_reason"]
                item["email_source_url"] = website
                item["email_source_type"] = "PATTERN_INFERENCE"
                item["email_evidence"] = f"Inferred with pattern '{detected_pattern}' on '{primary_domain}' ({pattern_confidence})"
                item["email_verification"] = "PATTERN_INFERENCE"
                item["emailVerificationMethod"] = "PATTERN_INFERENCE"
                item["mailbox_status"] = "UNVERIFIED"
                item["mailboxVerification"] = "UNVERIFIED"
                item["email_domain"] = primary_domain
                item["emailDomain"] = primary_domain
                item["confidenceScore"] = 80 if pattern_confidence == "STRONG" else 70
                item["generatedPattern"] = detected_pattern
                item["generated_pattern"] = detected_pattern
                item["pattern_confidence"] = pattern_confidence
                item["patternConfidence"] = pattern_confidence
                item["isExactPublished"] = False
                logger.info(f"EMAIL_DISCOVERY_RESULT person='{person_name}' status='PATTERN_GENERATED' email='{generated_em}'")
            else:
                item["email"] = None
                item["email_status"] = "NOT_FOUND"
                item["emailStatus"] = "NOT_FOUND"
                item["status"] = "not_found"
                item["email_reason"] = "Could not format name into company pattern"
                item["emailReason"] = item["email_reason"]
                item["isExactPublished"] = False

        else:
            # Not found or search failed
            search_st = item.get("search_status")
            item["email"] = None
            item["status"] = "not_found"
            item["isExactPublished"] = False

            if search_st == "SEARCH_TIMEOUT":
                item["email_status"] = "SEARCH_TIMEOUT"
                item["emailStatus"] = "SEARCH_TIMEOUT"
                item["email_reason"] = "DuckDuckGo search timed out within configured timeout limit"
            elif search_st == "SEARCH_UNAVAILABLE":
                item["email_status"] = "SEARCH_UNAVAILABLE"
                item["emailStatus"] = "SEARCH_UNAVAILABLE"
                item["email_reason"] = item.get("search_error") or "Public search service is currently rate-limited or unavailable"
            else:
                item["email_status"] = "NOT_FOUND"
                item["emailStatus"] = "NOT_FOUND"
                item["email_reason"] = "Discovery completed successfully but no public email was found for this person"

            item["emailReason"] = item["email_reason"]
            item["email_domain"] = primary_domain
            item["emailDomain"] = primary_domain
            item["confidenceScore"] = 0
            item["generatedPattern"] = "none"
            item["generated_pattern"] = "none"
            item["pattern_confidence"] = pattern_confidence
            item["patternConfidence"] = pattern_confidence
            logger.info(f"EMAIL_DISCOVERY_RESULT person='{person_name}' status='{item['email_status']}'")

        final_contacts.append(item)

    return final_contacts
