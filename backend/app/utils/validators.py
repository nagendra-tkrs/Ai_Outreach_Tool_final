import re
from urllib.parse import urlparse

REQUIRED_COLUMNS = [
    'Company Name',
    'Website',
    'Evidence',
    'Recommended Service'
]

VALID_RECOMMENDED_SERVICES = {
    'AI Strategy Consulting',
    'AI Readiness and Opportunity Assessments',
    'AI & Automation Workshops',
    'AI Training',
    'AI Governance and Responsible AI',
    'AI Data Strategy'
}

OPTIONAL_COLUMNS = [
    'Industry',
    'Country',
    'Contact Name',
    'Contact Email',
    'Revenue',
    'Employee Count',
    'Notes',
    'Source'
]

def normalize_website(url: str) -> str:
    if not url or not isinstance(url, str):
        return ""
    normalized = url.strip().rstrip('/')
    if not re.match(r'^https?://', normalized, re.IGNORECASE):
        normalized = 'https://' + normalized
    try:
        parsed = urlparse(normalized)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip('/')
        query = f"?{parsed.query}" if parsed.query else ""
        return f"{scheme}://{netloc}{path}{query}".lower()
    except Exception:
        return normalized.lower()

def is_valid_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    trimmed = url.strip()
    if not trimmed:
        return False
    with_protocol = trimmed if re.match(r'^https?://', trimmed, re.IGNORECASE) else 'https://' + trimmed
    try:
        parsed = urlparse(with_protocol)
        if parsed.scheme.lower() not in ('http', 'https'):
            return False
        hostname = parsed.hostname or ''
        if '.' not in hostname:
            return False
        return True
    except Exception:
        return False

def normalize_company_name(name: str) -> str:
    if not name or not isinstance(name, str):
        return ""
    return re.sub(r'\s+', ' ', name).strip()

def validate_row(row: dict) -> list[str]:
    errors = []
    company_name = (row.get('companyName') or '').strip()
    website = (row.get('website') or '').strip()
    evidence = (row.get('evidence') or '').strip()
    recommended_service = (row.get('recommendedService') or '').strip()

    if not company_name:
        errors.append('Company Name is required')
    if not website:
        errors.append('Website is required')
    elif not is_valid_url(website):
        errors.append('Invalid website URL')

    if not evidence:
        errors.append('Evidence is required')

    if not recommended_service:
        errors.append('Recommended Service is required')
    elif recommended_service not in VALID_RECOMMENDED_SERVICES:
        errors.append(
            f"Invalid Recommended Service: '{recommended_service}'. Must be one of: {', '.join(sorted(VALID_RECOMMENDED_SERVICES))}"
        )

    return errors
