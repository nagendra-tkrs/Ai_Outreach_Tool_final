"""
Production send-safety guards (E3 / E4 / E8 / E9):

- Configurable daily send limit and per-domain daily recipient limit.
- Recipient suppression (opt-out) support with a persistent collection.
- Recipient email syntax validation.
- Configurable send time-window (used by the scheduler for auto-sends).
- Ethereal / test-send isolation: test sends never consume production limits
  and never pollute production delivery statistics (isTestSend flag).

Limits are all configurable via environment variables (and therefore easy to
override in tests):

    DAILY_SEND_LIMIT            (default 50)
    PER_DOMAIN_DAILY_LIMIT      (default 5)
    SEND_WINDOW_START           (default 09:00)
    SEND_WINDOW_END             (default 18:00)
    APP_TZ_OFFSET_MINUTES       (offset from UTC of the application timezone, default 0)

Counting is based on actual SENT messages (status == "sent") stored in
outreachmessages. Test/sandbox sends (isTestSend == true) are excluded.
"""
import os
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.config.database import get_db
from app.utils.bson_utils import to_object_id

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

_SINGLE_LETTER_OR_DIGIT_RE = re.compile(r"^[^@\s]+@[^@\s]+$")


def get_app_tz_offset_minutes() -> int:
    """Application timezone offset from UTC in minutes (default 0 = UTC)."""
    try:
        return int(os.getenv("APP_TZ_OFFSET_MINUTES", "0") or "0")
    except (TypeError, ValueError):
        return 0


def get_send_limits() -> dict:
    return {
        "dailyLimit": int(os.getenv("DAILY_SEND_LIMIT", "50") or "50"),
        "perDomainLimit": int(os.getenv("PER_DOMAIN_DAILY_LIMIT", "5") or "5"),
        "windowStart": os.getenv("SEND_WINDOW_START", "09:00") or "09:00",
        "windowEnd": os.getenv("SEND_WINDOW_END", "18:00") or "18:00",
    }


def normalize_domain_for_limit(email: str) -> str:
    """Bare lowercase domain of an email, without www/. (used for per-domain counting)."""
    if not email or "@" not in email:
        return ""
    d = email.rsplit("@", 1)[1].lower().strip()
    d = re.sub(r"^www\.", "", d)
    return d


def _utc_day_bounds() -> tuple:
    """[start, end) of the current day in application timezone, expressed in UTC."""
    offset = get_app_tz_offset_minutes()
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc + timedelta(minutes=offset)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local - timedelta(minutes=offset)
    end_utc = start_utc + timedelta(days=1)
    return start_utc, end_utc


async def count_daily_sent_emails(domain: str = "") -> int:
    """Count actual SENT (non-test) outreach emails today.

    Pass a bare domain to count recipients for that domain only.
    """
    db = get_db()
    if db is None:
        return 0
    start, end = _utc_day_bounds()
    query = {
        "status": "sent",
        "sentAt": {"$gte": start, "$lt": end},
        "isTestSend": {"$ne": True},
    }
    if domain:
        query["recipientEmail"] = {"$regex": f"@{re.escape(domain)}$", "$options": "i"}
    return await db.outreachmessages.count_documents(query)


def validate_recipient_email(email) -> bool:
    """Basic SMTP recipient email syntax validation."""
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_RE.match(email.strip()))


async def assert_send_limits(recipient_email: str, is_test: bool = False):
    """Enforce daily + per-domain limits before a real send.

    Test/sandbox (Ethereal) sends never consume production limits so automated
    test suites cannot be mistaken for real production delivery statistics.
    """
    if is_test:
        return

    recipient_email = (recipient_email or "").strip().lower()
    if not validate_recipient_email(recipient_email):
        raise HTTPException(status_code=400, detail="Invalid recipient email address format.")

    limits = get_send_limits()
    daily = await count_daily_sent_emails()
    if daily >= limits["dailyLimit"]:
        logger_warning = (
            f"Send blocked: daily limit reached ({daily}/{limits['dailyLimit']} sent today)."
        )
        import logging
        logging.getLogger("send_guard").warning(logger_warning)
        raise HTTPException(
            status_code=429,
            detail=f"Daily send limit reached ({limits['dailyLimit']} emails/day). No further sends allowed today.",
        )

    domain = normalize_domain_for_limit(recipient_email)
    if domain:
        dom_count = await count_daily_sent_emails(domain)
        if dom_count >= limits["perDomainLimit"]:
            import logging
            logging.getLogger("send_guard").warning(
                f"Per-domain limit reached for @{domain} ({dom_count}/{limits['perDomainLimit']} today)."
            )
            raise HTTPException(
                status_code=429,
                detail=f"Per-domain daily limit reached for @{domain} ({limits['perDomainLimit']} recipients/day).",
            )


def is_within_sending_window(now_utc: datetime = None) -> bool:
    """True when now is inside the configurable sending window (app timezone)."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    limits = get_send_limits()
    try:
        sh, sm = (int(x) for x in str(limits["windowStart"]).split(":"))
        eh, em = (int(x) for x in str(limits["windowEnd"]).split(":"))
    except (ValueError, AttributeError):
        return True  # misconfigured window -> do not hard-block

    local = now_utc + timedelta(minutes=get_app_tz_offset_minutes())
    cur_min = local.hour * 60 + local.minute
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    if start_min == end_min:
        return True
    if start_min < end_min:
        return start_min <= cur_min < end_min
    # overnight window, e.g. 22:00 -> 06:00
    return cur_min >= start_min or cur_min < end_min


# ---------------- Suppression / opt-out (E4) ----------------

async def find_suppression(email: str):
    """Return the suppression record for an email address, or None."""
    db = get_db()
    if db is None:
        return None
    emp = (email or "").strip().lower()
    if not emp or "@" not in emp:
        return None
    return await db.suppressions.find_one({"email": emp})


async def add_suppression(
    email: str,
    reason: str = "",
    source: str = "",
    company_id=None,
    contact_id=None,
):
    """Register (idempotently) a suppressed recipient."""
    db = get_db()
    emp = (email or "").strip().lower()
    if not emp or "@" not in emp or db is None:
        return None
    now = datetime.now(timezone.utc)
    doc = {
        "email": emp,
        "suppressedAt": now,
        "updatedAt": now,
    }
    if reason:
        doc["reason"] = reason
    if source:
        doc["source"] = source
    if company_id:
        try:
            doc["companyId"] = to_object_id(company_id)
        except Exception:
            pass
    if contact_id:
        try:
            doc["contactId"] = to_object_id(contact_id)
        except Exception:
            pass
    await db.suppressions.update_one(
        {"email": emp},
        {"$set": doc, "$setOnInsert": {"createdAt": now}},
        upsert=True,
    )
    return await db.suppressions.find_one({"email": emp})


async def add_suppression_record(
    email: str,
    reason: str = "",
    source: str = "",
    company_id=None,
    contact_id=None,
):
    """Alias for add_suppression (used by the unsubscribe endpoint)."""
    return await add_suppression(
        email,
        reason=reason,
        source=source,
        company_id=company_id,
        contact_id=contact_id,
    )


async def remove_suppression(email: str) -> bool:
    db = get_db()
    emp = (email or "").strip().lower()
    if not emp or db is None:
        return False
    res = await db.suppressions.delete_one({"email": emp})
    return res.deleted_count > 0


async def assert_not_suppressed(recipient_email: str, cc_recipients=None):
    """Block the send if the target (or any CC) is suppressed."""
    target = (recipient_email or "").strip().lower()
    if target:
        supp = await find_suppression(target)
        if supp:
            raise HTTPException(
                status_code=403,
                detail=f"Recipient {target} is suppressed and cannot receive outreach emails.",
            )
    cc_recipients = cc_recipients or []
    if isinstance(cc_recipients, str):
        cc_recipients = [cc_recipients]
    for cc in cc_recipients:
        cc = (cc or "").strip().lower()
        if not cc:
            continue
        supp = await find_suppression(cc)
        if supp:
            raise HTTPException(
                status_code=403,
                detail=f"Recipient {cc} (CC) is suppressed and cannot receive outreach emails.",
            )


def enforce_recipient_domain_match() -> bool:
    """Configuration flag for E8 recipient domain-match enforcement (default off)."""
    return os.getenv("ENFORCE_RECIPIENT_DOMAIN_MATCH", "false").lower() in ("true", "1")


PUBLIC_EMAIL_PROVIDERS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.co.uk",
    "hotmail.com", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com",
    "proton.me", "protonmail.com", "zoho.com", "aol.com", "mail.com"
}

SUSPICIOUS_NAME_TOKENS = {
    "north", "south", "east", "west", "college", "university", "school",
    "hospital", "media", "kit", "department", "support", "admin", "info",
    "contact", "sales", "team", "office", "branch", "hq", "headquarters",
    "services", "solutions", "limited", "ltd", "inc", "corp", "corporation",
    "co", "group", "holdings", "technologies", "technology", "partners", "partner"
}


def normalize_website_domain(url_or_domain: str) -> str:
    """Extract and normalize bare domain from website URL or string."""
    if not url_or_domain:
        return ""
    d = str(url_or_domain).strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0].split("?")[0].split("#")[0].strip()
    d = re.sub(r"^www\.", "", d)
    return d


def check_recipient_domain_alignment(recipient_email: str, company_website: str) -> dict:
    """Evaluate alignment between recipient email domain and company website.

    - Exact domain or subdomain match -> aligned.
    - Known public webmail providers (gmail, yahoo, etc.) -> aligned (legitimate third-party/small business).
    - Unrelated corporate domains -> flagged as potential mismatch for manual review.
    """
    email_domain = normalize_domain_for_limit(recipient_email)
    web_domain = normalize_website_domain(company_website)

    if not email_domain or not web_domain:
        return {
            "aligned": True,
            "matchType": "insufficient_data",
            "emailDomain": email_domain,
            "websiteDomain": web_domain,
        }

    if email_domain == web_domain or email_domain.endswith("." + web_domain) or web_domain.endswith("." + email_domain):
        return {
            "aligned": True,
            "matchType": "exact_or_subdomain",
            "emailDomain": email_domain,
            "websiteDomain": web_domain,
        }

    if email_domain in PUBLIC_EMAIL_PROVIDERS:
        return {
            "aligned": True,
            "matchType": "public_webmail",
            "emailDomain": email_domain,
            "websiteDomain": web_domain,
        }

    return {
        "aligned": False,
        "matchType": "domain_mismatch",
        "emailDomain": email_domain,
        "websiteDomain": web_domain,
        "reason": f"Recipient domain '@{email_domain}' differs from company website domain '{web_domain}'.",
    }


def assert_domain_match_if_enforced(recipient_email: str, company_website: str) -> None:
    """Enforce domain match only when ENFORCE_RECIPIENT_DOMAIN_MATCH is active.

    When active, corporate domain mismatches raise HTTP 400. Public webmail providers
    are accepted so legitimate small-business accounts are not blocked.
    """
    if not enforce_recipient_domain_match():
        return
    res = check_recipient_domain_alignment(recipient_email, company_website)
    if not res.get("aligned"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Recipient domain mismatch: '@{res.get('emailDomain')}' does not match "
                f"company domain '{res.get('websiteDomain')}'. Route to manual review or "
                "disable ENFORCE_RECIPIENT_DOMAIN_MATCH."
            ),
        )


def check_contact_and_greeting_consistency(
    recipient_name: str,
    greeting: str,
    step1_greeting: str = None
) -> dict:
    """Non-destructive validation of contact names and greeting continuity.

    Flags suspicious non-person names (locations, orgs) and thread greeting
    discontinuities without inventing or silently overwriting anything.
    """
    findings = []
    suspicious_name = False
    discontinuity = False

    name_clean = (recipient_name or "").strip()
    if name_clean:
        tokens = set(re.findall(r"[A-Za-z]+", name_clean.lower()))
        flagged_tokens = tokens & SUSPICIOUS_NAME_TOKENS
        if len(flagged_tokens) >= 1 and (len(tokens) <= 2 or "north" in tokens or "college" in tokens):
            suspicious_name = True
            findings.append(
                f"Contact name '{name_clean}' contains organizational/location tokens ({', '.join(sorted(flagged_tokens))})."
            )

    greet_clean = (greeting or "").strip()
    s1_clean = (step1_greeting or "").strip()
    if greet_clean and s1_clean and greet_clean.lower() != s1_clean.lower():
        discontinuity = True
        findings.append(
            f"Follow-up greeting '{greet_clean}' differs from Step 1 greeting '{s1_clean}'."
        )

    return {
        "valid": not (suspicious_name or discontinuity),
        "suspiciousName": suspicious_name,
        "greetingDiscontinuity": discontinuity,
        "findings": findings,
    }