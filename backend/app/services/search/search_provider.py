import os
import re
from datetime import datetime
from app.services.search.public_web_search_provider import execute_public_web_search

def env_int(name: str, fallback: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == '':
        return fallback
    try:
        n = int(raw)
        return n if n > 0 else fallback
    except ValueError:
        return fallback

MAX_WEB_SEARCH_QUERIES = env_int('MAX_WEB_SEARCH_QUERIES', 20)
MAX_SEARCH_RESULTS_PER_QUERY = env_int('MAX_SEARCH_RESULTS_PER_QUERY', 5)

def is_public_web_fallback_enabled() -> bool:
    explicit = os.getenv('ENABLE_PUBLIC_WEB_SEARCH')
    if explicit is not None:
        return str(explicit).lower() != 'false'
    return os.getenv('NODE_ENV') != 'test'

def get_active_search_provider_config() -> dict:
    provider = (os.getenv('SEARCH_PROVIDER') or 'duckduckgo').lower().strip()
    duckduckgo_active = provider in ('duckduckgo', 'public_web', 'html', 'ddg')

    if duckduckgo_active and is_public_web_fallback_enabled():
        return {'providerName': 'public_web', 'isConfigured': True, 'reason': 'DUCKDUCKGO_ONLY'}

    return {'providerName': 'none', 'isConfigured': False, 'reason': 'SEARCH_PROVIDER_NOT_CONFIGURED'}

async def execute_search(query: str, options: dict = None) -> dict:
    if options is None:
        options = {}
    active = get_active_search_provider_config()

    if active['providerName'] == 'public_web':
        res = await execute_public_web_search(query, options)
        limit = options.get('limit') or MAX_SEARCH_RESULTS_PER_QUERY
        if isinstance(res.get('results'), list) and len(res['results']) > limit:
            res['results'] = res['results'][:limit]
        return res

    return {
        'query': query,
        'results': [],
        'provider': 'none',
        'configured': False,
        'error': 'SEARCH_PROVIDER_NOT_CONFIGURED',
        'state': 'SEARCH_UNAVAILABLE',
        'retrievedAt': datetime.utcnow().isoformat()
    }

def build_decision_maker_queries(company_name: str, domain: str, industry: str = '', country: str = '', opportunity_context: str = '') -> list[str]:
    clean_domain = re.sub(r'^https?://', '', domain or '')
    clean_domain = re.sub(r'^www\.', '', clean_domain).split('/')[0].lower()

    queries = [
        f'"{company_name}" "Chief Executive Officer" OR "CEO"',
        f'"{company_name}" "Chief Technology Officer" OR "CTO" OR "Head of AI"',
        f'"{company_name}" "Chief Information Officer" OR "CIO" OR "Chief Operating Officer" OR "COO"'
    ]

    if clean_domain:
        queries.append(f'site:{clean_domain} (leadership OR team OR executives OR management)')

    if re.search(r'governance|compliance|responsible ai|risk', opportunity_context, re.I):
        queries.append(f'"{company_name}" "CIO" OR "Chief Data Officer" OR "Chief Digital Officer"')
    elif re.search(r'sales|customer|support|revenue', opportunity_context, re.I):
        queries.append(f'"{company_name}" "Chief Customer Officer" OR "Chief Revenue Officer" OR "Head of Sales"')

    return queries[:MAX_WEB_SEARCH_QUERIES]
