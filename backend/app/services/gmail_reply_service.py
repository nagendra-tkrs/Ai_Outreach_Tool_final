"""Gmail OAuth2 & Reply Ingestion Service (Phase 2 Foundation).

Provides:
- OAuth2 token management with minimal `https://www.googleapis.com/auth/gmail.readonly` scope.
- Secure storage of OAuth configuration and refresh tokens in MongoDB `settings.gmailOAuth`.
  (Secrets and tokens are strictly masked in logs and API responses; SMTP credentials are untouched).
- Raw Gmail message fetching and normalization (message ID, thread ID, sender, subject, date, headers, body text).
- Deterministic correlation engine using RFC 2822 In-Reply-To, References, and threadId linking.
  (Subject alone is NEVER treated as a definitive match).
- Idempotent reply events store in the `replyevents` collection with unique index on `gmailMessageId`.
- Read-only Gmail API calls via httpx. Zero SMTP calls, zero automated sending.
"""

import base64
import email.utils
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config.database import get_db
from app.utils.bson_utils import to_object_id

logger = logging.getLogger(__name__)

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


def mask_secret(value: str) -> str:
    """Mask credentials/tokens for safe logging and UI display."""
    if not value:
        return ""
    s = str(value).strip()
    if len(s) <= 8:
        return "********"
    return f"{s[:4]}...{s[-4:]}"


def sanitize_message_id(msg_id: str) -> str:
    """Strip whitespace and angle brackets from RFC 2822 Message-ID."""
    if not msg_id:
        return ""
    cleaned = msg_id.strip()
    if cleaned.startswith("<") and cleaned.endswith(">"):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def extract_references_ids(references_header: str) -> List[str]:
    """Extract individual Message-IDs from a References or In-Reply-To header."""
    if not references_header:
        return []
    # Pattern to match <id@domain> or whitespace-separated tokens
    raw_ids = re.findall(r"<([^>]+)>", references_header)
    if not raw_ids:
        raw_ids = [tok.strip() for tok in references_header.split() if tok.strip()]
    return [sanitize_message_id(r) for r in raw_ids if sanitize_message_id(r)]


def normalize_email_address(raw_address: str) -> str:
    """Extract and lowercase the pure email address from a From/To header value."""
    if not raw_address:
        return ""
    _, addr = email.utils.parseaddr(raw_address)
    return (addr or raw_address).strip().lower()


def decode_base64_url_data(data_str: str) -> str:
    """Decode Gmail API base64url-encoded body payload."""
    if not data_str:
        return ""
    try:
        # base64url padding
        padding = 4 - (len(data_str) % 4)
        if padding and padding < 4:
            data_str += "=" * padding
        raw_bytes = base64.urlsafe_b64decode(data_str)
        return raw_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug(f"Failed to decode base64 payload: {e}")
        return ""


def extract_body_text_from_payload(payload: Dict[str, Any]) -> str:
    """Recursively extract plain text body from Gmail message payload parts."""
    if not payload:
        return ""

    mime_type = payload.get("mimeType", "")
    body_data = (payload.get("body") or {}).get("data", "")

    if mime_type == "text/plain" and body_data:
        return decode_base64_url_data(body_data)

    parts = payload.get("parts") or []
    # 1. Prefer text/plain part
    for part in parts:
        if part.get("mimeType") == "text/plain":
            text = extract_body_text_from_payload(part)
            if text:
                return text

    # 2. Check multipart / nested parts
    for part in parts:
        nested = extract_body_text_from_payload(part)
        if nested:
            return nested

    # 3. Fallback to html stripped if plain text not available
    if mime_type == "text/html" and body_data:
        html = decode_base64_url_data(body_data)
        return re.sub(r"<[^>]+>", " ", html).strip()

    return ""


def parse_gmail_message(raw_msg: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw Gmail API message dictionary into a standardized dict."""
    msg_id = raw_msg.get("id", "")
    thread_id = raw_msg.get("threadId", "")
    snippet = raw_msg.get("snippet", "")
    internal_date_ms = raw_msg.get("internalDate")

    date_dt = None
    if internal_date_ms:
        try:
            date_dt = datetime.fromtimestamp(int(internal_date_ms) / 1000.0, tz=timezone.utc)
        except Exception:
            date_dt = datetime.now(timezone.utc)

    headers_list = (raw_msg.get("payload") or {}).get("headers") or []
    headers_dict: Dict[str, str] = {}
    for h in headers_list:
        name = h.get("name", "").strip().lower()
        headers_dict[name] = h.get("value", "").strip()

    rfc_message_id = sanitize_message_id(headers_dict.get("message-id", ""))
    in_reply_to = sanitize_message_id(headers_dict.get("in-reply-to", ""))
    references_raw = headers_dict.get("references", "")
    references = extract_references_ids(references_raw)
    sender_raw = headers_dict.get("from", "")
    sender_email = normalize_email_address(sender_raw)
    subject = headers_dict.get("subject", "")
    to_email = normalize_email_address(headers_dict.get("to", ""))

    body_text = extract_body_text_from_payload(raw_msg.get("payload") or {})
    if not body_text and snippet:
        body_text = snippet

    return {
        "gmailMessageId": msg_id,
        "gmailThreadId": thread_id,
        "rfcMessageId": rfc_message_id,
        "inReplyTo": in_reply_to,
        "references": references,
        "fromRaw": sender_raw,
        "fromEmail": sender_email,
        "toEmail": to_email,
        "subject": subject,
        "date": date_dt or datetime.now(timezone.utc),
        "snippet": snippet,
        "bodyText": body_text,
        "headers": headers_dict,
    }


# ---------------------------------------------------------------------------
# OAuth2 Token & Settings Management
# ---------------------------------------------------------------------------

async def get_gmail_oauth_settings() -> Dict[str, Any]:
    """Retrieve Gmail OAuth2 configuration from the database."""
    db = get_db()
    if db is None:
        return {}
    settings = await db.settings.find_one({"key": "global_settings"}) or {}
    return settings.get("gmailOAuth") or {}


# In-memory CSRF state cache with TTL timestamps
_OAUTH_STATE_CACHE: Dict[str, float] = {}
OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes


def generate_oauth_state() -> str:
    """Generate a cryptographically secure CSRF state token and record in cache."""
    import secrets
    import time
    now = time.time()
    # Prune expired states
    expired = [k for k, exp in _OAUTH_STATE_CACHE.items() if exp < now]
    for k in expired:
        _OAUTH_STATE_CACHE.pop(k, None)

    state = secrets.token_urlsafe(32)
    _OAUTH_STATE_CACHE[state] = now + OAUTH_STATE_TTL_SECONDS
    return state


def verify_oauth_state(state: str) -> bool:
    """Validate CSRF state token. Single-use: consumes state upon validation."""
    import time
    if not state:
        return False
    expiry = _OAUTH_STATE_CACHE.pop(state, None)
    if expiry is None:
        return False
    return time.time() <= expiry


async def get_authorization_url(redirect_uri: str, state: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Build the Google OAuth 2.0 authorization URL with offline access and readonly scope."""
    import urllib.parse
    cfg = await get_gmail_oauth_settings()
    client_id = cfg.get("clientId")
    if not client_id:
        return None, "Gmail OAuth client ID is not configured in Settings."

    state_token = state or generate_oauth_state()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GMAIL_READONLY_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state_token,
    }
    user_email = cfg.get("userEmail")
    if user_email:
        params["login_hint"] = user_email

    auth_url = f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"
    return auth_url, None


async def exchange_authorization_code(
    code: str,
    redirect_uri: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Exchange an authorization code for access and refresh tokens, saving to settings."""
    cfg = await get_gmail_oauth_settings()
    client_id = cfg.get("clientId")
    client_secret = cfg.get("clientSecret")
    if not client_id or not client_secret:
        return None, "Gmail OAuth client ID or client secret is not configured in Settings."

    if not code or not code.strip():
        return None, "Authorization code is required."

    client = http_client or httpx.AsyncClient(timeout=15.0)
    should_close = http_client is None
    try:
        resp = await client.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code.strip(),
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        if resp.status_code != 200:
            logger.error(f"[GmailOAuth] Code exchange failed: HTTP {resp.status_code}")
            return None, f"Failed to exchange authorization code: HTTP {resp.status_code} - {resp.text}"

        token_data = resp.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)

        from datetime import timedelta
        new_expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)).isoformat()

        update_dict: Dict[str, Any] = {
            "accessToken": access_token,
            "tokenExpiry": new_expiry,
        }
        if refresh_token:
            update_dict["refreshToken"] = refresh_token

        saved = await save_gmail_oauth_settings(update_dict)
        return {
            "hasRefreshToken": bool(saved.get("refreshToken")),
            "isConfigured": bool(saved.get("clientId") and saved.get("clientSecret") and saved.get("refreshToken")),
        }, None
    except Exception as e:
        logger.error(f"[GmailOAuth] Error during code exchange: {e}")
        return None, f"Exception during code exchange: {e}"
    finally:
        if should_close:
            await client.aclose()


async def save_gmail_oauth_settings(oauth_config: Dict[str, Any]) -> Dict[str, Any]:
    """Persist or update Gmail OAuth2 credentials and token."""
    db = get_db()
    if db is None:
        raise RuntimeError("Database connection unavailable")

    current = await get_gmail_oauth_settings()
    updated = {**current}

    for field in ("clientId", "clientSecret", "refreshToken", "accessToken", "tokenExpiry", "userEmail"):
        if field in oauth_config and oauth_config[field] is not None:
            updated[field] = oauth_config[field]

    updated["updatedAt"] = datetime.now(timezone.utc)

    await db.settings.update_one(
        {"key": "global_settings"},
        {"$set": {"gmailOAuth": updated}},
        upsert=True,
    )
    return updated


async def get_valid_access_token(http_client: Optional[httpx.AsyncClient] = None) -> Tuple[Optional[str], Optional[str]]:
    """Return (access_token, None) if valid or refreshed, or (None, error_message)."""
    cfg = await get_gmail_oauth_settings()
    client_id = cfg.get("clientId")
    client_secret = cfg.get("clientSecret")
    refresh_token = cfg.get("refreshToken")
    access_token = cfg.get("accessToken")
    token_expiry = cfg.get("tokenExpiry")

    if not client_id or not client_secret:
        return None, "Gmail OAuth client ID or client secret is not configured in Settings."
    if not refresh_token:
        return None, "Gmail OAuth refresh token is missing. Authorization required."

    now = datetime.now(timezone.utc)
    if access_token and token_expiry:
        # Check if still valid with a 60-second safety margin
        if isinstance(token_expiry, str):
            try:
                token_expiry_dt = datetime.fromisoformat(token_expiry)
                if token_expiry_dt.tzinfo is None:
                    token_expiry_dt = token_expiry_dt.replace(tzinfo=timezone.utc)
            except Exception:
                token_expiry_dt = None
        elif isinstance(token_expiry, datetime):
            token_expiry_dt = token_expiry.replace(tzinfo=timezone.utc) if token_expiry.tzinfo is None else token_expiry
        else:
            token_expiry_dt = None

        if token_expiry_dt and token_expiry_dt > now:
            return access_token, None

    # Refresh the access token
    client = http_client or httpx.AsyncClient(timeout=15.0)
    should_close = http_client is None
    try:
        resp = await client.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            logger.error(f"[GmailOAuth] Refresh failed: HTTP {resp.status_code}")
            return None, f"Google token refresh failed: HTTP {resp.status_code}"

        token_data = resp.json()
        new_access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 3600)
        from datetime import timedelta
        new_expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)).isoformat()

        await save_gmail_oauth_settings({
            "accessToken": new_access_token,
            "tokenExpiry": new_expiry,
        })
        return new_access_token, None
    except Exception as e:
        logger.error(f"[GmailOAuth] Error refreshing token: {e}")
        return None, f"Failed to refresh Google access token: {e}"
    finally:
        if should_close:
            await client.aclose()


# ---------------------------------------------------------------------------
# Deterministic Correlation Engine
# ---------------------------------------------------------------------------

async def correlate_reply_to_outreach(parsed_msg: Dict[str, Any], db=None) -> Dict[str, Any]:
    """Find matching outreachrecord and outreachmessage using deterministic headers.

    Match Priorities:
    1. RFC 2822 `inReplyTo` matching an outbound `outreachmessages.messageId`.
    2. RFC 2822 `references` list containing an outbound `outreachmessages.messageId`.
    3. Matching `gmailThreadId` if previously recorded.

    Strict Safety Guard:
    Subject alone is NEVER treated as a match. If a message comes from an
    outreach recipient with 'Re: ...' but has no linking header, it is marked
    matchConfidence="unconfirmed_subject_only" and NOT auto-associated.
    """
    if db is None:
        db = get_db()
    if db is None:
        return {"matched": False, "reason": "database_unavailable"}

    in_reply_to = parsed_msg.get("inReplyTo")
    references = parsed_msg.get("references") or []
    from_email = parsed_msg.get("fromEmail")
    thread_id = parsed_msg.get("gmailThreadId")

    candidate_ids = set()
    if in_reply_to:
        candidate_ids.add(in_reply_to)
        candidate_ids.add(f"<{in_reply_to}>")
    for ref in references:
        candidate_ids.add(ref)
        candidate_ids.add(f"<{ref}>")

    # 1. Match against outreachmessages.messageId
    if candidate_ids:
        matched_msg = await db.outreachmessages.find_one({
            "messageId": {"$in": list(candidate_ids)},
            "status": "sent",
        })
        if matched_msg:
            # Find matching tracking record
            rec = await db.outreachrecords.find_one({
                "companyId": matched_msg.get("companyId"),
                "recipientEmail": matched_msg.get("recipientEmail"),
            })
            matched_outbound_id = matched_msg.get("messageId", "")
            sanitized_matched = sanitize_message_id(matched_outbound_id)
            is_in_reply_to = bool(in_reply_to and sanitize_message_id(in_reply_to) == sanitized_matched)
            matched_by_method = "In-Reply-To" if is_in_reply_to else "References"

            return {
                "matched": True,
                "confidence": "high_header_match",
                "messageId": str(matched_msg["_id"]),
                "recordId": str(rec["_id"]) if rec else None,
                "companyId": str(matched_msg.get("companyId")),
                "step": matched_msg.get("step"),
                "recipientEmail": matched_msg.get("recipientEmail"),
                "matchedBy": matched_by_method,
            }

    # 2. Match against recorded thread ID
    if thread_id:
        matched_msg_by_thread = await db.outreachmessages.find_one({
            "gmailThreadId": thread_id,
            "status": "sent",
        })
        if matched_msg_by_thread:
            rec = await db.outreachrecords.find_one({
                "companyId": matched_msg_by_thread.get("companyId"),
                "recipientEmail": matched_msg_by_thread.get("recipientEmail"),
            })
            return {
                "matched": True,
                "confidence": "high_thread_match",
                "messageId": str(matched_msg_by_thread["_id"]),
                "recordId": str(rec["_id"]) if rec else None,
                "companyId": str(matched_msg_by_thread.get("companyId")),
                "step": matched_msg_by_thread.get("step"),
                "recipientEmail": matched_msg_by_thread.get("recipientEmail"),
                "matchedBy": "Gmail-Thread-ID",
            }

    # 3. Check for prospect email match without valid header (Unconfirmed)
    if from_email:
        prospect_rec = await db.outreachrecords.find_one({"recipientEmail": from_email})
        if prospect_rec:
            return {
                "matched": False,
                "confidence": "unconfirmed_sender_only",
                "recordId": str(prospect_rec["_id"]),
                "companyId": str(prospect_rec.get("companyId")),
                "recipientEmail": from_email,
                "note": "Sender matches active prospect, but headers do not reference an outreach email. Not auto-associated.",
            }

    return {"matched": False, "confidence": "none"}


# ---------------------------------------------------------------------------
# Idempotent Ingestion Engine
# ---------------------------------------------------------------------------

async def ensure_reply_events_indexes():
    """Ensure unique index on replyevents.gmailMessageId."""
    db = get_db()
    if db is not None:
        try:
            await db.replyevents.create_index("gmailMessageId", unique=True)
            await db.replyevents.create_index([("recipientEmail", 1), ("receivedAt", -1)])
            await db.replyevents.create_index("recordId")
        except Exception as e:
            logger.debug(f"[replyevents] index verification: {e}")


async def ingest_gmail_messages(raw_messages: List[Dict[str, Any]], db=None) -> Dict[str, Any]:
    """Normalize and persist incoming Gmail messages idempotently into `replyevents`.

    Never duplicates events: uses unique index and upsert on `gmailMessageId`.
    Never calls SMTP or modifies follow-up schedules in Phase 2.
    """
    if db is None:
        db = get_db()
    if db is None:
        raise RuntimeError("Database unavailable")

    await ensure_reply_events_indexes()

    stats = {
        "total": len(raw_messages),
        "inserted": 0,
        "alreadyProcessed": 0,
        "correlated": 0,
        "unmatched": 0,
        "events": [],
    }

    for raw_msg in raw_messages:
        parsed = parse_gmail_message(raw_msg)
        gmail_id = parsed["gmailMessageId"]
        if not gmail_id:
            continue

        existing = await db.replyevents.find_one({"gmailMessageId": gmail_id})
        if existing:
            stats["alreadyProcessed"] += 1
            continue

        # Correlate
        correlation = await correlate_reply_to_outreach(parsed, db=db)
        if correlation.get("matched"):
            stats["correlated"] += 1
        else:
            stats["unmatched"] += 1

        now = datetime.now(timezone.utc)
        event_doc = {
            "gmailMessageId": gmail_id,
            "gmailThreadId": parsed.get("gmailThreadId"),
            "rfcMessageId": parsed.get("rfcMessageId"),
            "inReplyTo": parsed.get("inReplyTo"),
            "references": parsed.get("references"),
            "fromEmail": parsed.get("fromEmail"),
            "fromRaw": parsed.get("fromRaw"),
            "toEmail": parsed.get("toEmail"),
            "subject": parsed.get("subject"),
            "receivedAt": parsed.get("date"),
            "snippet": parsed.get("snippet"),
            "bodyText": parsed.get("bodyText"),
            "matched": correlation.get("matched", False),
            "correlation": correlation,
            "recordId": to_object_id(correlation.get("recordId")) if correlation.get("recordId") else None,
            "companyId": to_object_id(correlation.get("companyId")) if correlation.get("companyId") else None,
            "outreachMessageId": to_object_id(correlation.get("messageId")) if correlation.get("messageId") else None,
            "recipientEmail": correlation.get("recipientEmail") or parsed.get("fromEmail"),
            "status": "INGESTED",  # Phase 2 ingestion status (Phase 3 will add CLASSIFIED)
            "createdAt": now,
            "updatedAt": now,
        }

        try:
            await db.replyevents.insert_one(event_doc)
            stats["inserted"] += 1
            stats["events"].append({
                "gmailMessageId": gmail_id,
                "fromEmail": parsed.get("fromEmail"),
                "subject": parsed.get("subject"),
                "matched": correlation.get("matched", False),
                "confidence": correlation.get("confidence"),
            })
        except Exception as e:
            # Duplicate key error caught gracefully
            if "duplicate key" in str(e).lower() or "e11000" in str(e).lower():
                stats["alreadyProcessed"] += 1
            else:
                logger.error(f"[Ingest] Error saving reply event {gmail_id}: {e}")

    return stats


# ---------------------------------------------------------------------------
# Live Gmail API Fetcher (with Read-Only Client)
# ---------------------------------------------------------------------------

async def fetch_gmail_inbox_messages(
    query: str = "newer_than:7d",
    max_results: int = 20,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Fetch recent messages from Gmail using the read-only REST API.

    Returns: (list_of_raw_messages, error_string)
    """
    token, err = await get_valid_access_token(http_client=http_client)
    if err or not token:
        return [], err or "Unable to obtain Google access token"

    client = http_client or httpx.AsyncClient(timeout=20.0)
    should_close = http_client is None
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        # 1. List message IDs
        list_resp = await client.get(
            f"{GMAIL_API_BASE_URL}/messages",
            params={"q": query, "maxResults": max_results},
            headers=headers,
        )
        if list_resp.status_code != 200:
            return [], f"Gmail API list failed: HTTP {list_resp.status_code} - {list_resp.text}"

        list_data = list_resp.json()
        message_stubs = list_data.get("messages") or []
        if not message_stubs:
            return [], None

        # 2. Batch fetch full message payloads (read-only format=full)
        full_messages = []
        for stub in message_stubs:
            mid = stub.get("id")
            if not mid:
                continue
            get_resp = await client.get(
                f"{GMAIL_API_BASE_URL}/messages/{mid}",
                params={"format": "full"},
                headers=headers,
            )
            if get_resp.status_code == 200:
                full_messages.append(get_resp.json())
            else:
                logger.warning(f"[GmailAPI] Failed to fetch message {mid}: HTTP {get_resp.status_code}")

        return full_messages, None
    except Exception as e:
        logger.error(f"[GmailAPI] Error during message fetch: {e}")
        return [], f"Gmail API fetch error: {e}"
    finally:
        if should_close:
            await client.aclose()


async def sync_gmail_replies_service(query: str = "newer_than:7d", max_results: int = 20) -> Dict[str, Any]:
    """High-level service called by manual sync API route."""
    raw_messages, err = await fetch_gmail_inbox_messages(query=query, max_results=max_results)
    if err:
        return {"success": False, "message": err, "stats": None}

    stats = await ingest_gmail_messages(raw_messages)
    return {
        "success": True,
        "message": f"Processed {stats['total']} messages: {stats['inserted']} new, {stats['alreadyProcessed']} skipped, {stats['correlated']} correlated.",
        "stats": stats,
    }
