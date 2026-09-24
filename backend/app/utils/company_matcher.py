import re

def validate_company_match(candidate_company_name: str = '', target_company_name: str = '', target_domain: str = '') -> bool:
    if not target_company_name or not candidate_company_name:
        return False

    def normalize_comp(s: str) -> str:
        stripped = (s or '').lower()
        stripped = re.sub(r'https?://', '', stripped)
        stripped = re.sub(r'^www\.', '', stripped)
        stripped = re.sub(r'[^a-z0-9\s]', ' ', stripped)
        stripped = re.sub(
            r'\b(inc|incorporated|llc|ltd|limited|corp|corporation|technologies|technology|solutions|services|group|co|holdings|pvt|private|gmbh|sa|bv|enterprises|international|global)\b',
            '',
            stripped
        ).strip()
        stripped = re.sub(r'\s+', ' ', stripped)
        if len(stripped) >= 2:
            return stripped
        return re.sub(r'[^a-z0-9]', '', (s or '').lower())

    norm_target = normalize_comp(target_company_name)
    norm_cand = normalize_comp(candidate_company_name)

    if not norm_target or not norm_cand:
        return False

    # 1. Exact normalized match
    if norm_target == norm_cand:
        return True

    # 2. Exact lowercase string match
    if target_company_name.strip().lower() == candidate_company_name.strip().lower():
        return True

    # 3. Substantive substring match
    if norm_target in norm_cand or norm_cand in norm_target:
        min_len = min(len(norm_target), len(norm_cand))
        max_len = max(len(norm_target), len(norm_cand))
        if min_len >= 3 and (min_len / max_len) >= 0.4:
            return True

    # 4. Domain match check
    if target_domain:
        domain_clean = re.sub(r'^https?://', '', target_domain)
        domain_clean = re.sub(r'^www\.', '', domain_clean).split('/')[0].lower()
        domain_base = domain_clean.split('.')[0]
        if domain_base and len(domain_base) >= 3:
            if norm_cand == domain_base or domain_base in norm_cand or domain_base in candidate_company_name.lower():
                return True

    return False
