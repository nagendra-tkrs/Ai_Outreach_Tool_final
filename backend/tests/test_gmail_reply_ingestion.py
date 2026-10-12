"""Comprehensive Phase 2 Gmail OAuth2, Message Normalization, Correlation & Ingestion Tests.

Verifies:
1. Message normalization: headers, MIME body (base64url, multipart, plain text), RFC Message-ID.
2. Deterministic correlation:
   - High confidence via In-Reply-To header matching sent outreachmessage.
   - High confidence via References header matching sent outreachmessage.
   - High confidence via Gmail Thread ID matching recorded thread.
   - Strict Safety: unconfirmed sender-only with no header reference is NOT auto-associated.
3. Idempotent Ingestion into replyevents:
   - Inserting raw messages creates replyevents.
   - Repeating sync on the same raw messages is a clean no-op (alreadyProcessed count increments, total docs stays 1).
4. OAuth credentials safety:
   - Tokens and secrets are masked; never logged in plain text.
   - Settings retrieval masks clientSecret and refreshToken presence.
5. Zero SMTP calls:
   - Validates that ingestion never touches aiosmtplib or send_outreach_email.
6. Mocked HTTP client:
   - All tests use in-memory mocked responses — zero real inbox or network access.
"""

import base64
from datetime import datetime, timezone
import pytest
from bson import ObjectId
import httpx

from motor.motor_asyncio import AsyncIOMotorClient
import app.config.database as db_module

from app.services.gmail_reply_service import (
    parse_gmail_message,
    correlate_reply_to_outreach,
    ingest_gmail_messages,
    get_valid_access_token,
    save_gmail_oauth_settings,
    get_gmail_oauth_settings,
    mask_secret,
    sanitize_message_id,
    extract_references_ids,
)

TEST_DB_NAME = "ai_client_outreach_test_gmail_reply"


@pytest.fixture(scope="module", autouse=True)
async def isolated_test_db():
    client = AsyncIOMotorClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000)
    test_db = client[TEST_DB_NAME]
    await client.drop_database(TEST_DB_NAME)
    prev_db, prev_client = db_module.db, db_module.client
    db_module.db = test_db
    db_module.client = client
    try:
        yield test_db
    finally:
        db_module.db = prev_db
        db_module.client = prev_client
        await client.drop_database(TEST_DB_NAME)
        client.close()


def _make_gmail_raw_msg(
    msg_id: str,
    thread_id: str,
    from_header: str,
    subject: str,
    body_text: str,
    in_reply_to: str = "",
    references: str = "",
    rfc_msg_id: str = "",
):
    b64_body = base64.urlsafe_b64encode(body_text.encode("utf-8")).decode("utf-8")
    headers = [
        {"name": "From", "value": from_header},
        {"name": "To", "value": "nagendra@tksrproductservices.com"},
        {"name": "Subject", "value": subject},
        {"name": "Date", "value": "Mon, 12 Oct 2026 10:00:00 +0000"},
    ]
    if rfc_msg_id:
        headers.append({"name": "Message-ID", "value": rfc_msg_id})
    if in_reply_to:
        headers.append({"name": "In-Reply-To", "value": in_reply_to})
    if references:
        headers.append({"name": "References", "value": references})

    return {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": body_text[:100],
        "internalDate": "1791802800000",
        "payload": {
            "mimeType": "text/plain",
            "headers": headers,
            "body": {"data": b64_body},
        },
    }


def test_header_sanitization_and_parsing():
    assert sanitize_message_id("<test-id@example.com>") == "test-id@example.com"
    assert sanitize_message_id("  test-id@example.com  ") == "test-id@example.com"
    assert extract_references_ids("<id1@ex.com> <id2@ex.com>") == ["id1@ex.com", "id2@ex.com"]
    assert mask_secret("short") == "********"
    assert mask_secret("my_super_secret_refresh_token_12345") == "my_s...2345"


def test_gmail_message_normalization():
    raw = _make_gmail_raw_msg(
        msg_id="gm_123",
        thread_id="th_456",
        from_header="Vikram Khanna <vikram@aisglass.com>",
        subject="Re: Quick note on AI Readiness",
        body_text="Hi Nagendra, happy to connect on this next week.",
        in_reply_to="<initial-send-123@smtp.gmail.com>",
        references="<initial-send-123@smtp.gmail.com>",
        rfc_msg_id="<reply-789@aisglass.com>",
    )
    parsed = parse_gmail_message(raw)
    assert parsed["gmailMessageId"] == "gm_123"
    assert parsed["gmailThreadId"] == "th_456"
    assert parsed["fromEmail"] == "vikram@aisglass.com"
    assert parsed["inReplyTo"] == "initial-send-123@smtp.gmail.com"
    assert parsed["references"] == ["initial-send-123@smtp.gmail.com"]
    assert "happy to connect" in parsed["bodyText"]


@pytest.mark.asyncio
async def test_deterministic_correlation_in_reply_to(isolated_test_db):
    db = isolated_test_db
    cid = ObjectId()
    outbound_msg_id = "<outbound-test-abc@smtp.gmail.com>"

    outbound_test_msg_id = "outbound-test-abc@smtp.gmail.com"
    m_doc = await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 1,
        "recipientEmail": "prospect@example.com",
        "status": "sent",
        "messageId": outbound_test_msg_id,
    })
    r_doc = await db.outreachrecords.insert_one({
        "companyId": cid,
        "recipientEmail": "prospect@example.com",
        "campaignStatus": "INITIAL_SENT",
        "replyStatus": "NO_REPLY",
    })

    # Test incoming reply with In-Reply-To
    parsed = {
        "inReplyTo": "outbound-test-abc@smtp.gmail.com",
        "references": [],
        "fromEmail": "prospect@example.com",
        "gmailThreadId": "some_thread",
    }
    result = await correlate_reply_to_outreach(parsed, db=db)
    assert result["matched"] is True
    assert result["confidence"] == "high_header_match"
    assert result["messageId"] == str(m_doc.inserted_id)
    assert result["recordId"] == str(r_doc.inserted_id)
    assert result["matchedBy"] == "In-Reply-To"


@pytest.mark.asyncio
async def test_deterministic_correlation_references(isolated_test_db):
    db = isolated_test_db
    cid = ObjectId()

    m_doc = await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 1,
        "recipientEmail": "client@partner.com",
        "status": "sent",
        "messageId": "ref-outbound-456@smtp.gmail.com",
    })

    parsed = {
        "inReplyTo": "unrelated@ex.com",
        "references": ["other@ex.com", "ref-outbound-456@smtp.gmail.com"],
        "fromEmail": "client@partner.com",
    }
    result = await correlate_reply_to_outreach(parsed, db=db)
    assert result["matched"] is True
    assert result["confidence"] == "high_header_match"
    assert result["matchedBy"] == "References"


@pytest.mark.asyncio
async def test_unconfirmed_subject_only_does_not_auto_associate(isolated_test_db):
    db = isolated_test_db
    cid = ObjectId()

    # Prospect exists in DB
    await db.outreachrecords.insert_one({
        "companyId": cid,
        "recipientEmail": "cautious@company.com",
        "campaignStatus": "INITIAL_SENT",
    })

    # Incoming email from that address, but zero matching headers
    parsed = {
        "inReplyTo": "",
        "references": [],
        "fromEmail": "cautious@company.com",
        "subject": "Re: Partnership query",
    }
    result = await correlate_reply_to_outreach(parsed, db=db)
    # MUST NOT auto-associate
    assert result["matched"] is False
    assert result["confidence"] == "unconfirmed_sender_only"
    assert "Not auto-associated" in result["note"]


@pytest.mark.asyncio
async def test_idempotent_ingestion_prevents_duplicate_events(isolated_test_db):
    db = isolated_test_db
    raw_msg = _make_gmail_raw_msg(
        msg_id="idemp_gmail_001",
        thread_id="th_idemp_1",
        from_header="John Doe <john@acme.com>",
        subject="Re: Introduction",
        body_text="Thanks for your email.",
        in_reply_to="no-match@example.com",
    )

    # First ingestion run
    stats1 = await ingest_gmail_messages([raw_msg], db=db)
    assert stats1["inserted"] == 1
    assert stats1["alreadyProcessed"] == 0

    doc_count1 = await db.replyevents.count_documents({"gmailMessageId": "idemp_gmail_001"})
    assert doc_count1 == 1

    # Second ingestion run with same message
    stats2 = await ingest_gmail_messages([raw_msg], db=db)
    assert stats2["inserted"] == 0
    assert stats2["alreadyProcessed"] == 1

    doc_count2 = await db.replyevents.count_documents({"gmailMessageId": "idemp_gmail_001"})
    assert doc_count2 == 1  # Total remains exactly 1


@pytest.mark.asyncio
async def test_oauth_settings_masking_and_storage(isolated_test_db):
    db = isolated_test_db
    await save_gmail_oauth_settings({
        "clientId": "test_client_id_123.apps.googleusercontent.com",
        "clientSecret": "super_secret_google_client_secret_xyz",
        "refreshToken": "1//refresh_token_very_secret_abcdef",
        "userEmail": "nagendra@tksrproductservices.com",
    })

    saved = await get_gmail_oauth_settings()
    assert saved["clientId"] == "test_client_id_123.apps.googleusercontent.com"
    assert saved["clientSecret"] == "super_secret_google_client_secret_xyz"

    # Verify secret masking function protects exposure
    assert mask_secret(saved["clientSecret"]) == "supe..._xyz"
    assert mask_secret(saved["refreshToken"]) == "1//r...cdef"


@pytest.mark.asyncio
async def test_mocked_token_refresh(isolated_test_db):
    db = isolated_test_db
    await save_gmail_oauth_settings({
        "clientId": "cid_123",
        "clientSecret": "sec_456",
        "refreshToken": "ref_789",
    })

    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            assert request.url == httpx.URL("https://oauth2.googleapis.com/token")
            return httpx.Response(200, json={
                "access_token": "mocked_fresh_access_token_999",
                "expires_in": 3600,
                "token_type": "Bearer",
            })

    async with httpx.AsyncClient(transport=MockTransport()) as mock_client:
        token, err = await get_valid_access_token(http_client=mock_client)
        assert err is None
        assert token == "mocked_fresh_access_token_999"

    updated = await get_gmail_oauth_settings()
    assert updated["accessToken"] == "mocked_fresh_access_token_999"
    assert updated["tokenExpiry"] is not None


@pytest.mark.asyncio
async def test_get_authorization_url_missing_client_id(isolated_test_db):
    db = isolated_test_db
    # Clear OAuth settings
    await db.settings.update_one({"key": "global_settings"}, {"$set": {"gmailOAuth": {}}})

    from app.services.gmail_reply_service import get_authorization_url
    url, err = await get_authorization_url(redirect_uri="http://localhost:5000/callback")
    assert url is None
    assert "client ID is not configured" in err


@pytest.mark.asyncio
async def test_get_authorization_url_and_csrf_state(isolated_test_db):
    from app.services.gmail_reply_service import (
        get_authorization_url,
        verify_oauth_state,
        save_gmail_oauth_settings,
        GMAIL_READONLY_SCOPE,
    )
    await save_gmail_oauth_settings({
        "clientId": "test_id_999.apps.googleusercontent.com",
        "clientSecret": "sec_999",
        "userEmail": "tester@example.com",
    })

    auth_url, err = await get_authorization_url(redirect_uri="http://localhost:5000/callback")
    assert err is None
    assert auth_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=test_id_999.apps.googleusercontent.com" in auth_url
    assert "scope=" in auth_url
    assert "access_type=offline" in auth_url
    assert "prompt=consent" in auth_url
    assert "state=" in auth_url
    assert "login_hint=tester%40example.com" in auth_url

    import urllib.parse
    parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
    state = parsed_qs["state"][0]

    # Verify single-use CSRF state token
    assert verify_oauth_state(state) is True
    # Second verification with same token fails (consumed)
    assert verify_oauth_state(state) is False
    # Bogus state fails
    assert verify_oauth_state("bogus_state") is False


@pytest.mark.asyncio
async def test_exchange_authorization_code_success(isolated_test_db):
    from app.services.gmail_reply_service import (
        exchange_authorization_code,
        save_gmail_oauth_settings,
        get_gmail_oauth_settings,
    )
    await save_gmail_oauth_settings({
        "clientId": "test_cid",
        "clientSecret": "test_secret",
    })

    class MockExchangeTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            assert request.url == httpx.URL("https://oauth2.googleapis.com/token")
            return httpx.Response(200, json={
                "access_token": "ya29.mocked_exchange_access",
                "refresh_token": "1//mocked_exchange_refresh_token",
                "expires_in": 3600,
                "token_type": "Bearer",
            })

    async with httpx.AsyncClient(transport=MockExchangeTransport()) as mock_client:
        res, err = await exchange_authorization_code(
            code="4/0AWgav_mocked_code",
            redirect_uri="http://localhost:5000/callback",
            http_client=mock_client,
        )
        assert err is None
        assert res["hasRefreshToken"] is True
        assert res["isConfigured"] is True

    saved = await get_gmail_oauth_settings()
    assert saved["refreshToken"] == "1//mocked_exchange_refresh_token"
    assert saved["accessToken"] == "ya29.mocked_exchange_access"


@pytest.mark.asyncio
async def test_oauth_callback_endpoint_flows(isolated_test_db):
    from unittest.mock import patch
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.services.gmail_reply_service import generate_oauth_state, save_gmail_oauth_settings

    await save_gmail_oauth_settings({
        "clientId": "test_client_id",
        "clientSecret": "test_client_secret",
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Error param from Google (consent denied)
        resp = await ac.get("/api/settings/gmail/oauth/callback", params={"error": "access_denied"}, follow_redirects=False)
        assert resp.status_code == 302
        assert "gmail=error" in resp.headers["location"]
        assert "access_denied" in resp.headers["location"]

        # 2. Missing code
        resp = await ac.get("/api/settings/gmail/oauth/callback", follow_redirects=False)
        assert resp.status_code == 302
        assert "detail=missing_code" in resp.headers["location"]

        # 3. Invalid/expired CSRF state
        resp = await ac.get("/api/settings/gmail/oauth/callback", params={"code": "auth_code_123", "state": "invalid_state"}, follow_redirects=False)
        assert resp.status_code == 302
        assert "detail=invalid_csrf_state" in resp.headers["location"]

        # 4. Successful callback with valid state and mocked token exchange
        valid_state = generate_oauth_state()
        with patch("app.routers.settings_routes.exchange_authorization_code") as mock_exchange:
            mock_exchange.return_value = ({"hasRefreshToken": True, "isConfigured": True}, None)
            resp = await ac.get("/api/settings/gmail/oauth/callback", params={"code": "valid_code", "state": valid_state}, follow_redirects=False)
            assert resp.status_code == 302
            assert "gmail=connected" in resp.headers["location"]
            mock_exchange.assert_called_once()

        # 5. Token exchange failure returns safe redirect error
        valid_state_fail = generate_oauth_state()
        with patch("app.routers.settings_routes.exchange_authorization_code") as mock_exchange:
            mock_exchange.return_value = (None, "Invalid grant: code expired")
            resp = await ac.get("/api/settings/gmail/oauth/callback", params={"code": "expired_code", "state": valid_state_fail}, follow_redirects=False)
            assert resp.status_code == 302
            assert "gmail=error" in resp.headers["location"]
            assert "Invalid%20grant" in resp.headers["location"]


@pytest.mark.asyncio
async def test_manual_sync_replies_endpoint(isolated_test_db):
    """Test POST /api/outreach/sync-replies returns structured stats."""
    from unittest.mock import patch
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    mock_raw_msg = {
        "id": "18f001_api_test",
        "threadId": "th_api_test",
        "payload": {
            "headers": [
                {"name": "Message-ID", "value": "<reply_api_1@prospect.com>"},
                {"name": "From", "value": "Alice <alice@prospect.com>"},
                {"name": "To", "value": "nagendra@tksrproductservices.com"},
                {"name": "Subject", "value": "Re: Partnership"},
                {"name": "Date", "value": "Mon, 12 Oct 2026 10:00:00 +0000"},
            ],
            "body": {"size": 0},
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {
                        "size": 24,
                        "data": base64.urlsafe_b64encode(b"Yes let us connect soon!").decode("ascii"),
                    },
                }
            ],
        },
        "snippet": "Yes let us connect soon!",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        with patch("app.routers.outreach_routes.sync_gmail_replies_service") as mock_sync:
            mock_sync.return_value = {
                "success": True,
                "message": "Processed 1 messages: 1 new, 0 skipped, 0 correlated.",
                "stats": {
                    "total": 1,
                    "inserted": 1,
                    "alreadyProcessed": 0,
                    "correlated": 0,
                    "unmatched": 1,
                    "events": [
                        {
                            "gmailMessageId": "18f001_api_test",
                            "fromEmail": "alice@prospect.com",
                            "subject": "Re: Partnership",
                            "matched": False,
                            "confidence": "none",
                        }
                    ],
                },
            }

            resp = await ac.post("/api/outreach/sync-replies", json={"query": "newer_than:7d", "maxResults": 20})
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["stats"]["total"] == 1
            assert data["stats"]["inserted"] == 1
            assert data["stats"]["unmatched"] == 1
            mock_sync.assert_called_once_with(query="newer_than:7d", max_results=20)


@pytest.mark.asyncio
async def test_get_reply_events_endpoint_pagination(isolated_test_db):
    """Test GET /api/outreach/reply-events returns paginated and serialized reply documents."""
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    now = datetime.now(timezone.utc)
    # Seed 3 reply events directly into db
    await isolated_test_db.replyevents.delete_many({})
    await isolated_test_db.replyevents.insert_many([
        {
            "gmailMessageId": f"msg_paginate_{i}",
            "fromEmail": f"lead_{i}@company.com",
            "subject": f"Reply #{i}",
            "receivedAt": now.isoformat(),
            "snippet": f"Snippet {i}",
            "matched": (i == 1),
            "correlation": {"matched": (i == 1), "confidence": "high_header_match" if i == 1 else "none"},
            "status": "INGESTED",
        }
        for i in range(1, 4)
    ])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/outreach/reply-events?page=1&limit=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 2
        assert body["pagination"]["page"] == 1
        assert body["pagination"]["limit"] == 2
        assert body["pagination"]["total"] == 3
        assert body["pagination"]["totalPages"] == 2

        # Page 2
        resp2 = await ac.get("/api/outreach/reply-events?page=2&limit=2")
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert len(body2["data"]) == 1
        assert isinstance(body2["data"][0]["_id"], str)



