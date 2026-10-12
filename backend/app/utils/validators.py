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

# ---------------------------------------------------------------------------
# Flexible header matching
# Aliases are matched after normalization (trim, lowercase, collapse spaces).
# The canonical header string is the dict key.
# ---------------------------------------------------------------------------
HEADER_ALIASES = {
    "Company Name": ["company", "company name"],
    "Website": ["website", "website url", "company website", "url"],
    "Evidence": ["evidence", "reason", "trigger", "ai trigger", "ai-trigger"],
    "Recommended Service": ["recommended service", "service", "tksr service", "recommendedservice", "service offered"],
    "Industry": ["industry", "sector"],
    "Country": ["country", "location"],
    "Contact Name": ["contact name", "contact", "contact person", "contactperson"],
    "Contact Email": ["contact email", "email", "contactmail"],
    "Revenue": ["revenue", "revenue usd"],
    "Employee Count": ["employee count", "employees", "headcount"],
    "Notes": ["notes", "note"],
    "Source": ["source", "lead source"],
}


def normalize_header(value) -> str:
    """Trim, lowercase, and collapse internal whitespace for header comparison."""
    if not value or not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip()).lower()


# Precomputed normalized alias lookup: normalized_alias -> canonical header.
# First mapping wins so canonical names take priority over any alias.
_NORMALIZED_ALIAS_MAP = {}
for _canonical, _aliases in HEADER_ALIASES.items():
    _all_names = [_canonical] + _aliases
    for _name in _all_names:
        _NORMALIZED_ALIAS_MAP.setdefault(normalize_header(_name), _canonical)


def resolve_header(header) -> str | None:
    """Return the canonical header name (e.g. 'Company Name') for any known alias."""
    norm = normalize_header(header)
    if not norm:
        return None
    return _NORMALIZED_ALIAS_MAP.get(norm)


# ---------------------------------------------------------------------------
# Recommended Service mapping (exact -> synonym table -> keyword fallback)
# ---------------------------------------------------------------------------
# Explicit one-to-one synonyms.
SERVICE_SYNONYMS = {
    "AI Governance & Council Development": "AI Governance and Responsible AI",
    "AI Governance": "AI Governance and Responsible AI",
    "AI Readiness Assessment": "AI Readiness and Opportunity Assessments",
    "AI Readiness": "AI Readiness and Opportunity Assessments",
    "AI Workshop": "AI & Automation Workshops",
    "Automation Workshop": "AI & Automation Workshops",
}

# Ordered keyword fallback (first match wins). Used only when the value is not
# an exact canonical service or an explicit synonym.
_SERVICE_KEYWORD_RULES = [
    ("data strategy", "AI Data Strategy"),
    ("governance", "AI Governance and Responsible AI"),
    ("readiness", "AI Readiness and Opportunity Assessments"),
    ("workshop", "AI & Automation Workshops"),
    ("training", "AI Training"),
    ("strategy", "AI Strategy Consulting"),
]


def _service_key(value: str) -> str:
    """Normalize a service description for comparison (alphanumeric tokens, lower)."""
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def resolve_service(service):
    """Map a service value to a canonical service.

    Returns (canonical_service or None, was_mapped: bool).
    was_mapped is True when a synonym/keyword mapping was applied, False for an
    exact (already-canonical) match, and (None, False) when unmappable.
    """
    key = _service_key(service)
    if not key:
        return None, False

    # 1. Exact canonical match (case/punctuation insensitive)
    for canonical in VALID_RECOMMENDED_SERVICES:
        if _service_key(canonical) == key:
            return canonical, False

    # 2. Explicit synonym table
    for raw, canonical in SERVICE_SYNONYMS.items():
        if _service_key(raw) == key:
            return canonical, True

    # 3. Keyword fallback for values that clearly match a service
    for token, canonical in _SERVICE_KEYWORD_RULES:
        if token in key:
            return canonical, True

    return None, False


# ---------------------------------------------------------------------------
# Website normalization / validation
# ---------------------------------------------------------------------------
def extract_domain(url) -> str:
    """Normalize any website string to a bare domain: 'acme.com'.

    Strips scheme, 'www.', path, query and fragment; lowercases.
    'www.acme.com', 'https://acme.com', 'https://www.acme.com/' -> 'acme.com'
    """
    if not url or not isinstance(url, str):
        return ""
    try:
        cleaned = url.strip().rstrip('/')
        cleaned = re.sub(r'^https?://', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'^www\.', '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.split('/')[0]
        cleaned = cleaned.split('?')[0].split('#')[0].strip().lower()
        return cleaned
    except Exception:
        return str(url).strip().lower()


def normalize_website(url) -> str:
    """Backward-compatible alias for extract_domain (used by import pipeline)."""
    return extract_domain(url)


def is_valid_url(url) -> bool:
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


def normalize_company_name(name) -> str:
    if not name or not isinstance(name, str):
        return ""
    return re.sub(r'\s+', ' ', name).strip()


# ---------------------------------------------------------------------------
# Row validation with actionable messages
# ---------------------------------------------------------------------------
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
        errors.append(f"Invalid website URL: '{website}'")

    if not evidence:
        errors.append('Evidence is required')

    if not recommended_service:
        errors.append('Recommended Service is required')
    elif recommended_service not in VALID_RECOMMENDED_SERVICES:
        errors.append(
            f'Invalid Recommended Service: "{recommended_service}". Allowed: {", ".join(sorted(VALID_RECOMMENDED_SERVICES))}'
        )

    return errors


def suggested_fixes(errors: list[str], row: dict) -> list[str]:
    """Human-readable next-action for every validation error."""
    fixes = []
    for err in errors:
        if 'Company Name is required' in err:
            fixes.append('Fill in the Company Name cell for this row.')
        elif 'Website is required' in err:
            fixes.append('Fill in the Website cell, e.g. https://acme.com')
        elif 'Invalid website URL' in err:
            fixes.append('Enter a valid URL with a real domain, e.g. https://acme.com')
        elif 'Evidence is required' in err:
            fixes.append('Fill in the Evidence cell describing why this company fits the service.')
        elif 'Recommended Service is required' in err:
            fixes.append('Fill in the Recommended Service cell from the allowed list.')
        elif 'Invalid Recommended Service' in err:
            fixes.append(
                f'Use one of the allowed services: {", ".join(sorted(VALID_RECOMMENDED_SERVICES))}'
            )
        else:
            fixes.append('Review the highlighted values and re-upload.')
    return fixes