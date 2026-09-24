import os
import re
import urllib.parse
import asyncio
from datetime import datetime
import httpx
from bs4 import BeautifulSoup
from app.services.search.search_provider import (
    execute_search,
    build_decision_maker_queries,
    MAX_SEARCH_RESULTS_PER_QUERY
)
from app.utils.company_matcher import validate_company_match

def clean_executive(name: str = '', raw_title: str = '', company_name: str = '') -> dict:
    clean_name = re.sub(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', r'\1', name or '')
    clean_name = re.sub(r'\[\[|\]\]|<[^>]+>|\(.*?\)', '', clean_name)
    clean_name = re.sub(r'^(the|and|by|with|from|to|at|for|is|mr|ms|mrs|dr|sir|contact|reach|email|author|speaker|executive|leader|inquiries)\s+', '', clean_name, flags=re.I)
    clean_name = re.sub(r'[\n\r\t]+', ' ', clean_name).strip()

    clean_title = re.sub(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', r'\1', raw_title or '')
    clean_title = re.sub(r'\[\[|\]\]|<[^>]+>|\(.*?\)|\|.*', '', clean_title)
    clean_title = re.sub(r'[\n\r\t]+', ' ', clean_title).strip()

    # Normalize common titles
    if re.search(r'ceo|chief executive', clean_title, re.I):
        clean_title = 'Chief Executive Officer'
    elif re.search(r'coo|operations', clean_title, re.I):
        clean_title = 'Chief Operating Officer'
    elif re.search(r'cfo|finance', clean_title, re.I):
        clean_title = 'Chief Financial Officer'
    elif re.search(r'cto|technology', clean_title, re.I):
        clean_title = 'Chief Technology Officer'
    elif re.search(r'cio|information', clean_title, re.I):
        clean_title = 'Chief Information Officer'
    elif re.search(r'cdo|digital', clean_title, re.I):
        clean_title = 'Chief Digital Officer'
    elif re.search(r'data', clean_title, re.I):
        clean_title = 'Chief Data Officer'
    elif re.search(r'president', clean_title, re.I):
        clean_title = 'President'
    elif re.search(r'founder|co-founder', clean_title, re.I):
        clean_title = 'Founder & Executive'
    elif re.search(r'chair', clean_title, re.I):
        clean_title = 'Chairman & Executive'

    # Blacklist non-person entities
    invalid_names = [
        'united states', 'san francisco', 'new york', 'chief executive', 'vice president',
        'annual report', 'form 10-k', 'form 8-k', 'press release', 'latest shake', 'corporate officer',
        'executive leadership', 'board member', 'board of directors', 'stock exchange', 'financial year', 'public company',
        'three stripes', 'adidas', 'puma', 'business insider', 'information (website)', 'phelan building',
        'chairman and ceo', 'president (corporate title)', 'chief financial officer', 'chief technology officer',
        'elon musk starts for', 'menlo park', 'cambridge, massachusetts', 'california', 'delaware', 'london',
        'third street', 'fourth street', 'market street', 'mission street', 'howard street', 'folsom street',
        'basiscursorqodonotion', 'cognitionrogoramp', 'shopifyciscoclio', 'terms of service', 'privacy policy',
        'contact us', 'about us', 'help center', 'view source', 'read more', 'click here'
    ]

    clean_name = re.sub(r'\s+(in|at|of|by|for|during)\s*$', '', clean_name, flags=re.I).strip()
    name_parts = [p for p in clean_name.split() if p]

    # Blacklist non-person entities and corporate tokens
    invalid_tokens = {
        'group', 'usa', 'india', 'textiles', 'fibres', 'chemicals', 'technologies',
        'services', 'products', 'industries', 'company', 'corporation', 'director',
        'officer', 'president', 'managing', 'executive', 'leadership', 'board', 'limited', 'ltd'
    }

    if (len(name_parts) < 2 or
        len(name_parts) > 4 or
        len(clean_name) < 4 or
        len(clean_name) > 45 or
        any(inv in clean_name.lower() for inv in invalid_names) or
        any(p.lower() in invalid_tokens for p in name_parts) or
        clean_name.lower() == (company_name or '').lower() or
        clean_name.lower().startswith('form ') or
        re.search(r'\d', clean_name) or
        re.search(r'[@#$%^&*()_+={}\[\]|\\:;"<>?/~`]', clean_name)):
        return None

    generic_tokens = ['director', 'officer', 'manager', 'president', 'executive', 'founder', 'leader', 'head', 'vp', 'chief']
    if all(p.lower() in generic_tokens for p in name_parts):
        return None

    return {
        'name': clean_name,
        'title': clean_title or 'Executive Leadership',
        'designationOriginal': raw_title.strip() if raw_title else (clean_title or 'Executive Leadership'),
        'designationNormalized': clean_title or 'Executive Leadership'
    }

async def fetch_authoritative_public_records(company_name: str, domain: str = '') -> list[dict]:
    executives = []
    seen_names = set()
    headers = {
        'User-Agent': 'AIOutreachClient/1.0 (https://tksrproductservices.com; info@tksrproductservices.com)'
    }
    wiki_timeout_sec = float(os.getenv('WIKI_TIMEOUT_SEC', 5.0))

    clean_domain_name = re.sub(r'^https?://', '', domain or '')
    clean_domain_name = re.sub(r'^www\.', '', clean_domain_name).split('.')[0]

    clean_comp = re.sub(r'\b(limited|ltd|pvt|private|inc|corp|corporation|company|companies|llc|llp|plc|holdings|group)\b', '', company_name, flags=re.I).strip(' ,.-')
    clean_brand = clean_comp.split()[0] if clean_comp else company_name

    search_terms = [
        f'"{company_name}"',
        f'"{clean_comp}"',
        f'{clean_comp} company',
        f'{clean_comp}'
    ]

    target_page = None

    async with httpx.AsyncClient(headers=headers, timeout=wiki_timeout_sec) as client:
        for term in search_terms:
            try:
                search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(term)}&format=json"
                search_res = await client.get(search_url)
                if search_res.status_code == 200:
                    search_data = search_res.json()
                    results = search_data.get('query', {}).get('search', [])
                    c_clean = re.sub(r'\b(limited|ltd|pvt|private|inc|corp|corporation|company|companies|group|industries|llc|co)\b', '', company_name.lower())
                    c_tokens = [tok for tok in re.findall(r'[a-z0-9]+', c_clean) if len(tok) > 2]
                    clean_domain = clean_domain_name.lower()

                    for r in results:
                        t = (r.get('title') or '').lower()
                        snip = (r.get('snippet') or '').lower()
                        if 'disambiguation' in t:
                            continue

                        is_match = False
                        if c_tokens and all(token in t for token in c_tokens):
                            is_match = True
                        elif clean_brand.lower() in t:
                            if any(tok[:4] in snip or tok[:4] in t for tok in c_tokens[1:]) or (clean_domain and (clean_domain in t or clean_domain in snip)):
                                is_match = True
                        elif c_clean in snip and (clean_domain in snip or 'company' in snip or 'group' in snip):
                            is_match = True

                        if is_match:
                            target_page = r
                            break
                    if target_page:
                        break
            except Exception:
                continue

        if target_page:
            try:
                page_id = target_page.get('pageid')
                detail_url = f"https://en.wikipedia.org/w/api.php?action=parse&pageid={page_id}&prop=wikitext|sections&format=json"
                detail_res = await client.get(detail_url)
                if detail_res.status_code == 200:
                    detail_data = detail_res.json()
                    raw_wikitext = detail_data.get('parse', {}).get('wikitext', {}).get('*', '')
                    source_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(target_page.get('title', ''))}"

                    # 1. key_people block
                    kp_match = re.search(r'key_people\s*=\s*([^\n\r]+(?:\n\r?[*|{<][^\n\r]+)*)', raw_wikitext, re.I)
                    if kp_match:
                        block = kp_match.group(1)
                        matches = re.finditer(r'(?:\[\[)?([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)(?:\]\])?\s*(?:\(([^)]+)\)|-\s*([A-Za-z\s|]+)|<br\s*/?>|$)', block)
                        for m in matches:
                            raw_name = m.group(1)
                            raw_title = m.group(2) or m.group(3) or 'Executive Leadership'
                            raw_title = re.sub(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', r'\1', raw_title).strip()
                            raw_name = re.sub(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', r'\1', raw_name).strip()
                            cleaned = clean_executive(raw_name, raw_title, company_name)
                            if cleaned and cleaned['name'].lower() not in seen_names:
                                seen_names.add(cleaned['name'].lower())
                                raw_line = re.sub(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', r'\1', m.group(0)).strip()
                                raw_line = re.sub(r'<[^>]+>', ' ', raw_line).strip()
                                clean_line = ' '.join(raw_line.split())
                                executives.append({
                                    'name': cleaned['name'],
                                    'title': cleaned['title'],
                                    'employer': company_name,
                                    'source': 'Authoritative Business Record (Wikipedia Infobox)',
                                    'sourceType': 'authoritative_record',
                                    'evidenceTier': 'tier2',
                                    'sourceUrl': source_url,
                                    'confidenceScore': 98,
                                    'isCurrentRole': 'confirmed_current',
                                    'evidence': f"Wikipedia Infobox: {clean_line}" if clean_line else f"Wikipedia Infobox listing for {cleaned['name']}"
                                })

                    # 2. founders block
                    founders_match = re.search(r'founders?\s*=\s*([^\n\r]+(?:\n\r?[*|{<][^\n\r]+)*)', raw_wikitext, re.I)
                    if founders_match:
                        block = founders_match.group(1)
                        block = re.sub(r'<ref[^>]*>.*?(?:</ref>|/>)', '', block, flags=re.S)
                        raw_names = re.findall(r'(?:\[\[)?([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)(?:\]\])?', block)
                        for r_name in raw_names:
                            cleaned = clean_executive(r_name, 'Founder & Executive', company_name)
                            if cleaned and cleaned['name'].lower() not in seen_names:
                                seen_names.add(cleaned['name'].lower())
                                clean_founder_snippet = ""
                                for line in block.splitlines():
                                    if r_name.lower() in line.lower():
                                        cl = re.sub(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', r'\1', line).strip()
                                        cl = re.sub(r'<[^>]+>', ' ', cl).strip()
                                        clean_founder_snippet = f"Wikipedia Founders: {' '.join(cl.split())}"
                                        break
                                if not clean_founder_snippet:
                                    clean_founder_snippet = f"Wikipedia Founders entry: {cleaned['name']}"
                                executives.append({
                                    'name': cleaned['name'],
                                    'title': cleaned['title'],
                                    'employer': company_name,
                                    'source': 'Authoritative Business Record (Wikipedia Founders)',
                                    'sourceType': 'authoritative_record',
                                    'evidenceTier': 'tier2',
                                    'sourceUrl': source_url,
                                    'confidenceScore': 96,
                                    'isCurrentRole': 'confirmed_current',
                                    'evidence': clean_founder_snippet
                                })

                    # 3. headed by / led by in text
                    head_match = re.search(r'(?:headed|led)\s+by\s+(?:\[\[)?([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)', raw_wikitext, re.I)
                    if head_match:
                        cleaned = clean_executive(head_match.group(1), 'Chairman & Managing Director', company_name)
                        if cleaned and cleaned['name'].lower() not in seen_names:
                            seen_names.add(cleaned['name'].lower())
                            raw_head = re.sub(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', r'\1', head_match.group(0)).strip()
                            clean_head = ' '.join(raw_head.split())
                            executives.append({
                                'name': cleaned['name'],
                                'title': cleaned['title'],
                                'employer': company_name,
                                'source': 'Authoritative Business Record (Wikipedia Lead)',
                                'sourceType': 'authoritative_record',
                                'evidenceTier': 'tier2',
                                'sourceUrl': source_url,
                                'confidenceScore': 97,
                                'isCurrentRole': 'confirmed_current',
                                'evidence': f"Wikipedia: {clean_head}"
                            })

                    # 4. founded by
                    founded_match = re.search(r'(?:founded|created|started|established)\s+(?:in\s+\d{4}\s+)?by\s+(?:\[\[)?([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)(?:\]\])?(?:\s*(?:,|and)\s*(?:\[\[)?([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)(?:\]\])?)?', raw_wikitext, re.I)
                    if founded_match:
                        clean_founded_line = re.sub(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', r'\1', founded_match.group(0)).strip()
                        clean_founded = ' '.join(clean_founded_line.split())
                        if founded_match.group(1):
                            cleaned = clean_executive(founded_match.group(1), 'Founder & Executive', company_name)
                            if cleaned and cleaned['name'].lower() not in seen_names:
                                seen_names.add(cleaned['name'].lower())
                                executives.append({
                                    'name': cleaned['name'],
                                    'title': cleaned['title'],
                                    'employer': company_name,
                                    'source': 'Authoritative Business Record (Company History)',
                                    'sourceType': 'authoritative_record',
                                    'evidenceTier': 'tier2',
                                    'sourceUrl': source_url,
                                    'confidenceScore': 94,
                                    'isCurrentRole': 'confirmed_current',
                                    'evidence': f"Wikipedia: {clean_founded}"
                                })
                        if founded_match.group(2):
                            cleaned = clean_executive(founded_match.group(2), 'Co-Founder & Executive', company_name)
                            if cleaned and cleaned['name'].lower() not in seen_names:
                                seen_names.add(cleaned['name'].lower())
                                executives.append({
                                    'name': cleaned['name'],
                                    'title': cleaned['title'],
                                    'employer': company_name,
                                    'source': 'Authoritative Business Record (Company History)',
                                    'sourceType': 'authoritative_record',
                                    'evidenceTier': 'tier2',
                                    'sourceUrl': source_url,
                                    'confidenceScore': 94,
                                    'isCurrentRole': 'confirmed_current',
                                    'evidence': f"Wikipedia: {clean_founded}"
                                })
            except Exception as e:
                print(f"Public records lookup error for {company_name}: {e}")

    return executives

async def search_web_for_leadership(company_name: str, domain: str = '', industry: str = '', country: str = '', opportunity_context: str = '') -> list[dict]:
    query_list = build_decision_maker_queries(company_name, domain, industry, country, opportunity_context)
    all_snippets = []
    seen_urls = set()

    selected_queries = query_list[:2]
    tasks = [execute_search(q, {'limit': MAX_SEARCH_RESULTS_PER_QUERY}) for q in selected_queries]
    search_responses = await asyncio.gather(*tasks, return_exceptions=True)

    for search_res in search_responses:
        if isinstance(search_res, dict):
            for item in search_res.get('results', []):
                url = item.get('url')
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_snippets.append({
                        'title': item.get('title', ''),
                        'snippet': item.get('snippet', ''),
                        'link': url,
                        'sourceDomain': item.get('sourceDomain', '')
                    })

    return all_snippets

def extract_executives_from_snippets(snippets: list = None, target_company_name: str = '', domain: str = '') -> list[dict]:
    if snippets is None:
        snippets = []
    executives = []
    seen_names = set()

    patterns = [
        re.compile(r'([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)\s*(?:,|-|–|—|is|serves as|was appointed)\s+(?:the\s+)?(CEO|Chief Executive Officer|Founder|Co-Founder|COO|Chief Operating Officer|CFO|Chief Financial Officer|CTO|Chief Technology Officer|CIO|Chief Information Officer|CDO|Chief Digital Officer|Chief Data Officer|President|Vice President|VP of [A-Za-z\s]+|Head of [A-Za-z\s]+|Director of [A-Za-z\s]+)\s+(?:at|of|for)\s+([A-Za-z0-9\s.,&-]+?)(?:\.|\,|$|\n|\()', re.I),
        re.compile(r'([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)\s*(?:,|-|–|—)\s*(CEO|Chief Executive Officer|Founder|Co-Founder|COO|Chief Operating Officer|CFO|Chief Financial Officer|CTO|Chief Technology Officer|CIO|Chief Information Officer|CDO|Chief Digital Officer|Chief Data Officer|President|Vice President|VP of [A-Za-z\s]+|Head of [A-Za-z\s]+|Director of [A-Za-z\s]+)', re.I),
        re.compile(r'(?:CEO|Chief Executive Officer|Founder|Co-Founder|COO|CFO|CTO|CIO|CDO|President)\s*(?:[:\-])\s*([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)', re.I)
    ]

    for s in snippets:
        text = f"{s.get('title', '')}. {s.get('snippet', '')}"
        for pat in patterns:
            for match in pat.finditer(text):
                raw_name = ''
                raw_title = ''
                extracted_employer = ''

                groups = match.groups()
                if len(groups) >= 3 and groups[0] and groups[1] and groups[2]:
                    raw_name = groups[0].strip()
                    raw_title = groups[1].strip()
                    extracted_employer = groups[2].strip()
                elif len(groups) >= 2 and groups[0] and groups[1]:
                    raw_name = groups[0].strip()
                    raw_title = groups[1].strip()
                elif len(groups) >= 1 and groups[0]:
                    raw_name = groups[0].strip()
                    raw_title = 'Chief Executive Officer'

                cleaned = clean_executive(raw_name, raw_title, target_company_name)
                if cleaned and cleaned['name'].lower() not in seen_names:
                    seen_names.add(cleaned['name'].lower())
                    clean_employer = re.sub(r'\b(Inc|LLC|Ltd|Corp|Corporation)\b', '', extracted_employer, flags=re.I).strip()
                    executives.append({
                        'name': cleaned['name'],
                        'title': cleaned['title'],
                        'employer': clean_employer or target_company_name,
                        'source': 'Google Search Snippet (Candidate Discovery)',
                        'sourceType': 'public_search',
                        'evidenceTier': 'tier3',
                        'sourceUrl': s.get('link') or f"https://{domain or 'company.com'}",
                        'confidenceScore': 80,
                        'isCurrentRole': 'likely_current',
                        'evidence': text[:250]
                    })

    return executives

async def search_online_for_person_email(person_name: str, company_name: str = '', domain: str = '') -> dict:
    if not person_name or not domain:
        return None

    clean_domain = re.sub(r'^https?://', '', domain)
    clean_domain = re.sub(r'^www\.', '', clean_domain).split('/')[0].lower()
    normalized = re.sub(r'[^a-zA-Z\s]', '', person_name).strip().lower()
    parts = [p for p in normalized.split() if p]
    first = parts[0] if parts else ''
    last = parts[-1] if len(parts) > 1 else ''

    queries = [
        f'"{person_name}" "@{clean_domain}"',
        f'"{person_name}" "{company_name or ""}" email'
    ]

    email_regex = re.compile(rf'[a-zA-Z0-9._%+-]+@{re.escape(clean_domain)}', re.I)
    generic_prefixes = ['info@', 'contact@', 'support@', 'sales@', 'help@', 'press@', 'jobs@', 'careers@', 'media@', 'billing@', 'hello@', 'friction@']

    tasks = [execute_search(q, {'limit': 3}) for q in queries]
    search_responses = await asyncio.gather(*tasks, return_exceptions=True)

    for idx, search_res in enumerate(search_responses):
        if isinstance(search_res, dict):
            for item in search_res.get('results', []):
                text_to_scan = f"{item.get('title', '')} {item.get('snippet', '')}"
                matches = email_regex.findall(text_to_scan)
                for m in matches:
                    lower = m.lower().strip()
                    if any(lower.startswith(p) for p in generic_prefixes):
                        continue
                    local = lower.split('@')[0]
                    if (local == first or
                        (last and local == last) or
                        local == f"{first}.{last}" or
                        (first and last and local == f"{first[0]}{last}") or
                        local == f"{first}{last}" or
                        local == f"{last}.{first}"):
                        return {
                            'email': lower,
                            'source': 'Google Search Index',
                            'sourceUrl': item.get('url') or f"https://www.google.com/search?q={urllib.parse.quote(queries[idx])}",
                            'confidenceScore': 96
                        }

    return None

def extract_employee_from_text(email_str: str, text: str, company_name: str = '', domain: str = '') -> dict:
    if not email_str or not text:
        return None
    email_lower = email_str.lower().strip()
    parts = email_lower.split('@')
    if not parts or not parts[0]:
        return None
    local_part = parts[0]

    escaped_email = re.escape(email_lower)
    direct_patterns = [
        re.compile(rf'([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)\s*[<(\[]\s*{escaped_email}\s*[>)\]]', re.I),
        re.compile(rf'([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)\s*[-:,|•]\s*{escaped_email}', re.I),
        re.compile(rf'{escaped_email}\s*[<(\[]\s*([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)\s*[>)\]]', re.I),
        re.compile(rf'{escaped_email}\s*[-:,|•]\s*([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)', re.I),
        re.compile(rf'(?:contact|reach|email|author|speaker|executive|leader)?\s*:?\s*([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)[^.!?]{{0,60}}{escaped_email}', re.I),
        re.compile(rf'{escaped_email}[^.!?]{{0,60}}(?:contact|reach|name)?\s*:?\s*([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+)+)', re.I)
    ]

    for pat in direct_patterns:
        match = pat.search(text)
        if match and match.group(1):
            cleaned = clean_executive(match.group(1), 'Employee', company_name)
            if cleaned and cleaned.get('name'):
                p_parts = [p for p in cleaned['name'].split() if p]
                return {
                    'personName': cleaned['name'],
                    'firstName': p_parts[0] if p_parts else '',
                    'lastName': p_parts[-1] if len(p_parts) > 1 else ''
                }

    idx = text.lower().find(email_lower)
    if idx != -1:
        start = max(0, idx - 120)
        end = min(len(text), idx + len(email_lower) + 120)
        window = text[start:end]
        for nm in re.finditer(r'([A-Z][a-z\u00C0-\u017F]+(?:\s+[A-Z][a-z\u00C0-\u017F]+){1,2})', window):
            cand_name = nm.group(1)
            if company_name and cand_name.lower() == company_name.lower():
                continue
            cleaned = clean_executive(cand_name, 'Employee', company_name)
            if cleaned and cleaned.get('name'):
                p_parts = [p for p in cleaned['name'].split() if p]
                f = (p_parts[0] if p_parts else '').lower()
                l = (p_parts[-1] if len(p_parts) > 1 else '').lower()
                if f and (f in local_part or (l and l in local_part) or (l and local_part.startswith(f[0]) and l in local_part)):
                    return {
                        'personName': cleaned['name'],
                        'firstName': p_parts[0] if p_parts else '',
                        'lastName': p_parts[-1] if len(p_parts) > 1 else ''
                    }

    return None

async def search_company_employee_emails(company_name: str, domain: str = '') -> list[dict]:
    if not company_name and not domain:
        return []

    clean_domain = re.sub(r'^https?://', '', domain or '')
    clean_domain = re.sub(r'^www\.', '', clean_domain).split('/')[0].lower()
    queries = []

    if clean_domain:
        queries.extend([
            f'"@{clean_domain}" "{company_name}"',
            f'site:{clean_domain} "@{clean_domain}"'
        ])
    if company_name and not queries:
        queries.append(f'"{company_name}" employee email')

    email_regex = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', re.I)
    generic_prefixes = [
        'info@', 'contact@', 'support@', 'sales@', 'help@', 'press@', 'jobs@',
        'careers@', 'media@', 'billing@', 'hello@', 'friction@', 'desk@',
        'admin@', 'team@', 'inquiries@', 'privacy@', 'marketing@', 'feedback@'
    ]
    results = []
    seen_emails = set()

    tasks = [execute_search(q, {'limit': 5}) for q in queries[:2]]
    search_responses = await asyncio.gather(*tasks, return_exceptions=True)

    for search_res in search_responses:
        if isinstance(search_res, dict):
            for item in search_res.get('results', []):
                text_to_scan = f"{item.get('title', '')} {item.get('snippet', '')}"
                matches = email_regex.findall(text_to_scan)
                for m in matches:
                    lower = m.lower().strip()
                    if any(lower.startswith(p) for p in generic_prefixes):
                        continue
                    if lower in seen_emails:
                        continue

                    e_parts = lower.split('@')
                    if len(e_parts) != 2:
                        continue
                    local, em_domain = e_parts

                    cand_domain_base = em_domain.split('.')[0].lower()
                    target_domain_base = clean_domain.split('.')[0].lower()
                    is_comp_match = False
                    if em_domain == clean_domain:
                        is_comp_match = True
                    elif cand_domain_base and target_domain_base and (cand_domain_base == target_domain_base or target_domain_base in cand_domain_base or cand_domain_base in target_domain_base):
                        is_comp_match = True
                    else:
                        is_comp_match = validate_company_match(em_domain.split('.')[0], company_name, clean_domain)

                    if not is_comp_match:
                        continue

                    seen_emails.add(lower)
                    employee_info = extract_employee_from_text(lower, text_to_scan, company_name, clean_domain)
                    person_name = employee_info.get('personName', '') if employee_info else ''

                    results.append({
                        'email': lower,
                        'person': person_name,
                        'personName': person_name,
                        'firstName': employee_info.get('firstName', '') if employee_info else '',
                        'lastName': employee_info.get('lastName', '') if employee_info else '',
                        'company': company_name,
                        'domain': em_domain,
                        'corporateDomain': em_domain,
                        'evidenceUrl': item.get('url', ''),
                        'sourceUrl': item.get('url', ''),
                        'evidenceSource': item.get('title', ''),
                        'sourceTitle': item.get('title', ''),
                        'evidenceTier': 'tier2',
                        'evidenceType': 'PUBLIC_GOOGLE_RESULT',
                        'sourceSnippet': item.get('snippet', ''),
                        'sourceType': 'PUBLIC_SOURCE'
                    })

    return results

async def search_online_for_generated_email(candidate_email: str, person_name: str = '', company_name: str = '', domain: str = '') -> dict:
    if not candidate_email:
        return {'verified': False}

    clean_domain = re.sub(r'^https?://', '', domain or '')
    clean_domain = re.sub(r'^www\.', '', clean_domain).split('/')[0].lower()
    normalized_cand = candidate_email.lower().strip()

    queries = [
        f'"{normalized_cand}"',
        f'"{person_name}" "{normalized_cand}"'
    ]

    tasks = [execute_search(q, {'limit': 3}) for q in queries]
    search_responses = await asyncio.gather(*tasks, return_exceptions=True)

    for idx, search_res in enumerate(search_responses):
        if isinstance(search_res, dict):
            for item in search_res.get('results', []):
                text_to_scan = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
                if normalized_cand in text_to_scan:
                    name_parts = [p for p in (person_name or '').lower().split() if p]
                    has_person = name_parts and all(p in text_to_scan for p in name_parts)
                    has_company = (company_name and company_name.lower() in text_to_scan) or (clean_domain and clean_domain in text_to_scan)
                    if has_person or has_company:
                        return {
                            'verified': True,
                            'email': normalized_cand,
                            'source': 'Public Web Search Index',
                            'sourceUrl': item.get('url') or f"https://www.google.com/search?q={urllib.parse.quote(queries[idx])}",
                            'sourceTitle': item.get('title', ''),
                            'evidenceText': item.get('snippet') or item.get('title', ''),
                            'confidenceScore': 98
                        }

    return {'verified': False, 'email': normalized_cand}

async def fetch_company_public_overview(company_name: str, domain: str = '', industry: str = '', country: str = '') -> dict:
    clean_domain = re.sub(r'^https?://', '', domain or '')
    clean_domain = re.sub(r'^www\.', '', clean_domain).split('/')[0].lower()
    evidence_items = []
    seen_urls = set()

    # 1. Wikipedia Authoritative Records
    authoritative_records = []
    try:
        authoritative_records = await fetch_authoritative_public_records(company_name, domain)
        for rec in authoritative_records:
            url = rec.get('sourceUrl')
            if url and url not in seen_urls:
                seen_urls.add(url)
                evidence_items.append({
                    'sourceType': 'authoritative_record',
                    'evidenceTier': 'tier2',
                    'sourceTitle': f"{company_name} Corporate Profile (Wikipedia)",
                    'sourceUrl': url,
                    'evidenceText': rec.get('evidence') or f"{rec.get('name')} holds the position of {rec.get('title')} at {company_name}.",
                    'retrievedAt': datetime.utcnow().isoformat()
                })
    except Exception as e:
        print(f"Authoritative lookup warning for {company_name}: {e}")

    # 2. Targeted search queries
    search_queries = [
        f'"{company_name}" (overview OR "about us" OR "what we do" OR products OR services OR solutions)',
        f'"{company_name}" (leadership OR "executive team" OR management OR CEO OR CTO OR founder)',
        f'"{company_name}" (customers OR clients OR "case study" OR enterprise OR industry)'
    ]
    if industry:
        search_queries.append(f'"{company_name}" "{industry}" (solutions OR services OR technology)')
    if clean_domain:
        search_queries.append(f'"{company_name}" site:{clean_domain}')

    for query in search_queries:
        try:
            search_res = await execute_search(query, {'limit': 4})
            for item in search_res.get('results', []):
                snippet = item.get('snippet', '')
                if item.get('title') and snippet and len(snippet) > 20:
                    t_url = item.get('url') or (f"https://{clean_domain}" if clean_domain else 'https://www.google.com')
                    if t_url not in seen_urls:
                        seen_urls.add(t_url)
                        evidence_items.append({
                            'sourceType': 'search_result',
                            'evidenceTier': 'tier3',
                            'sourceTitle': item.get('title', '')[:120],
                            'sourceUrl': t_url,
                            'evidenceText': snippet[:400],
                            'retrievedAt': datetime.utcnow().isoformat()
                        })
            if len(evidence_items) >= 10:
                break
        except Exception:
            pass

    key_personnel = []
    seen_people = set()

    for ar in authoritative_records:
        n = ar.get('name')
        if n and n.lower() not in seen_people:
            seen_people.add(n.lower())
            key_personnel.append({
                'name': n,
                'title': ar.get('title') or 'Executive Leadership',
                'employer': company_name,
                'sourceType': 'authoritative_record',
                'evidenceTier': 'tier2'
            })

    snippet_execs = extract_executives_from_snippets(
        [{'title': e['sourceTitle'], 'snippet': e['evidenceText'], 'link': e['sourceUrl']} for e in evidence_items],
        company_name,
        clean_domain
    )

    for se in snippet_execs:
        n = se.get('name')
        if n and n.lower() not in seen_people:
            seen_people.add(n.lower())
            key_personnel.append({
                'name': n,
                'title': se.get('title') or 'Executive',
                'employer': se.get('employer') or company_name,
                'sourceType': 'public_search',
                'evidenceTier': 'tier3'
            })

    return {
        'evidenceItems': evidence_items,
        'keyPersonnel': key_personnel,
        'totalSources': len(evidence_items)
    }
