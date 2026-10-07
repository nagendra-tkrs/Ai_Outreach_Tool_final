import pytest
from unittest.mock import AsyncMock, patch
from email.message import EmailMessage
from fastapi import HTTPException
import httpx

from app.main import app
from app.config.database import get_db, connect_db, close_db
from app.services.email_service import (
    get_smtp_config,
    send_test_email,
    is_masked_secret,
)


@pytest.fixture(scope="session", autouse=True)
async def setup_test_db():
    await connect_db()
    yield
    await close_db()


@pytest.fixture(autouse=True)
async def isolate_settings_per_test():
    db = get_db()
    current = await db.settings.find_one({"key": "global_settings"})
    yield
    if current is not None:
        await db.settings.replace_one({"key": "global_settings"}, current, upsert=True)
    else:
        await db.settings.delete_one({"key": "global_settings"})



@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# =========================================================================
# TEST A: Saved password = real password
# GET returns masked password
# POST settings with masked password -> DB password remains unchanged.
# =========================================================================
@pytest.mark.asyncio
async def test_a_masked_password_does_not_overwrite_db(client):
    db = get_db()
    original_pass = "super_secret_real_password_123"

    await db.settings.update_one(
        {"key": "global_settings"},
        {"$set": {
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "user": "user@example.com",
                "pass": original_pass,
                "fromName": "Test Sender",
                "fromEmail": "user@example.com"
            }
        }},
        upsert=True
    )

    # 1. GET settings returns masked password
    get_res = await client.get("/api/settings")
    assert get_res.status_code == 200
    smtp_data = get_res.json()["data"]["smtp"]
    masked_pass = smtp_data["pass"]
    assert masked_pass != original_pass
    assert is_masked_secret(masked_pass) is True

    # 2. POST settings back with the masked password
    update_res = await client.post("/api/settings", json={
        "smtp": {
            "host": "smtp.example.com",
            "port": 587,
            "user": "user@example.com",
            "pass": masked_pass,
            "fromName": "Test Sender Updated",
            "fromEmail": "user@example.com"
        }
    })
    assert update_res.status_code == 200

    # 3. Verify DB password remains completely unchanged
    stored = await db.settings.find_one({"key": "global_settings"})
    assert stored["smtp"]["pass"] == original_pass
    assert stored["smtp"]["fromName"] == "Test Sender Updated"


# =========================================================================
# TEST B: Saved password = real password
# Test SMTP request contains masked password -> SMTP service uses stored real password
# =========================================================================
@pytest.mark.asyncio
async def test_b_test_smtp_with_masked_password_uses_stored_real_password():
    db = get_db()
    real_pass = "stored_real_app_secret_999"

    await db.settings.update_one(
        {"key": "global_settings"},
        {"$set": {
            "smtp": {
                "host": "smtp.testb.com",
                "port": 587,
                "user": "agent@testb.com",
                "pass": real_pass,
            }
        }},
        upsert=True
    )

    # Custom config containing masked password
    custom_cfg = {
        "host": "smtp.testb.com",
        "port": 587,
        "user": "agent@testb.com",
        "pass": "stor...t_999"  # masked
    }

    resolved = await get_smtp_config(custom_cfg)
    assert resolved["pass"] == real_pass
    assert resolved["isTest"] is False


# =========================================================================
# TEST C: Saved password = real password
# Test SMTP request contains empty password -> SMTP service uses stored real password
# =========================================================================
@pytest.mark.asyncio
async def test_c_test_smtp_with_empty_password_uses_stored_real_password():
    db = get_db()
    real_pass = "stored_real_app_secret_888"

    await db.settings.update_one(
        {"key": "global_settings"},
        {"$set": {
            "smtp": {
                "host": "smtp.testc.com",
                "port": 587,
                "user": "agent@testc.com",
                "pass": real_pass,
            }
        }},
        upsert=True
    )

    custom_cfg = {
        "host": "smtp.testc.com",
        "port": 587,
        "user": "agent@testc.com",
        "pass": ""  # empty
    }

    resolved = await get_smtp_config(custom_cfg)
    assert resolved["pass"] == real_pass


# =========================================================================
# TEST D: New real password supplied -> DB updates to new password
# =========================================================================
@pytest.mark.asyncio
async def test_d_new_real_password_updates_db(client):
    db = get_db()
    old_pass = "old_password_111"
    new_pass = "brand_new_real_password_222"

    await db.settings.update_one(
        {"key": "global_settings"},
        {"$set": {
            "smtp": {
                "host": "smtp.testd.com",
                "port": 587,
                "user": "user@testd.com",
                "pass": old_pass,
            }
        }},
        upsert=True
    )

    post_res = await client.post("/api/settings", json={
        "smtp": {
            "host": "smtp.testd.com",
            "port": 587,
            "user": "user@testd.com",
            "pass": new_pass,
        }
    })
    assert post_res.status_code == 200

    stored = await db.settings.find_one({"key": "global_settings"})
    assert stored["smtp"]["pass"] == new_pass


# =========================================================================
# TEST E: No SMTP credentials configured -> clear error, NO Ethereal fallback in production
# =========================================================================
@pytest.mark.asyncio
async def test_e_no_smtp_credentials_raises_clear_error_no_ethereal():
    # Calling get_smtp_config with empty custom_config and empty DB
    with patch.dict("os.environ", {"ALLOW_ETHEREAL_TEST": "false", "ENABLE_ETHEREAL": "false"}, clear=False):
        with pytest.raises(HTTPException) as exc_info:
            await get_smtp_config({
                "host": "",
                "user": "",
                "pass": ""
            })
        assert exc_info.value.status_code == 400
        assert "SMTP credentials are not configured" in exc_info.value.detail


# =========================================================================
# TEST F: Successful test email -> response contains messageId -> email Message-ID equals messageId
# =========================================================================
@pytest.mark.asyncio
async def test_f_successful_test_email_returns_message_id():
    custom_cfg = {
        "host": "smtp.mocktest.com",
        "port": 587,
        "user": "tester@mocktest.com",
        "pass": "real_mock_pass",
        "fromName": "Mock Tester",
        "fromEmail": "tester@mocktest.com"
    }

    dispatched_messages = []

    async def mock_send(msg, **kwargs):
        dispatched_messages.append(msg)
        return ("250", "OK")

    with patch("aiosmtplib.send", new=AsyncMock(side_effect=mock_send)):
        res = await send_test_email(custom_cfg, "recipient@destination.com")

        assert res["success"] is True
        assert res["recipient"] == "recipient@destination.com"
        assert "messageId" in res
        assert res["messageId"].startswith("<")
        assert res["messageId"].endswith(">")

        # Verify the actual email message has the exact same Message-ID
        assert len(dispatched_messages) == 1
        actual_msg = dispatched_messages[0]
        assert actual_msg["Message-ID"] == res["messageId"]


# =========================================================================
# TEST G: Port 587 -> STARTTLS flow works correctly (start_tls=True, use_tls=False)
# =========================================================================
@pytest.mark.asyncio
async def test_g_port_587_uses_start_tls():
    custom_cfg = {
        "host": "smtp.gmail.com",
        "port": 587,
        "user": "test@gmail.com",
        "pass": "real_pass",
        "secure": False
    }

    send_calls = []

    async def mock_send(msg, **kwargs):
        send_calls.append(kwargs)
        return ("250", "OK")

    with patch("aiosmtplib.send", new=AsyncMock(side_effect=mock_send)):
        await send_test_email(custom_cfg, "recipient@test.com")

        assert len(send_calls) == 1
        kwargs = send_calls[0]
        assert kwargs["port"] == 587
        assert kwargs["start_tls"] is True
        assert kwargs["use_tls"] is False


# =========================================================================
# TEST H: Port 465 -> SSL flow works correctly (use_tls=True, start_tls=False)
# =========================================================================
@pytest.mark.asyncio
async def test_h_port_465_uses_implicit_ssl():
    custom_cfg = {
        "host": "smtp.gmail.com",
        "port": 465,
        "user": "test@gmail.com",
        "pass": "real_pass",
        "secure": False  # Even if secure flag is false, port 465 must use SSL
    }

    send_calls = []

    async def mock_send(msg, **kwargs):
        send_calls.append(kwargs)
        return ("250", "OK")

    with patch("aiosmtplib.send", new=AsyncMock(side_effect=mock_send)):
        await send_test_email(custom_cfg, "recipient@test.com")

        assert len(send_calls) == 1
        kwargs = send_calls[0]
        assert kwargs["port"] == 465
        assert kwargs["use_tls"] is True
        assert kwargs["start_tls"] is False
