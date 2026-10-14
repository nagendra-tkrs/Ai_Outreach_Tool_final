import os
import time
import pytest
import httpx
from app.config.database import connect_db, close_db
from app.main import app
from app.auth.security import (
    create_access_token,
    hash_password,
    verify_password,
    verify_access_token,
)


@pytest.fixture(scope="session", autouse=True)
async def setup_test_db():
    await connect_db()
    yield
    await close_db()


@pytest.fixture(scope="module", autouse=True)
def setup_auth_env():
    # Configure test admin credentials and static API key
    os.environ["ADMIN_USERNAME"] = "testadmin"
    os.environ["ADMIN_PASSWORD"] = "testpassword123"
    os.environ["AUTH_SECRET_KEY"] = "test_secret_key_for_unit_tests_32_bytes_long"
    os.environ["ADMIN_API_KEY"] = "test_api_key_xyz_789"
    os.environ["AUTH_TOKEN_EXPIRE_HOURS"] = "24"
    yield
    # No teardown needed as process ends after pytest


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def valid_token():
    return create_access_token("testadmin")


# ---------------------------------------------------------------------------
# 1. Public Allowlist Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check_remains_public(client):
    """Health check endpoint must remain accessible without credentials for Render/monitoring."""
    res = await client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_tracking_routes_remain_public(client):
    """Tracking routes must remain accessible without auth for email recipients."""
    # Open pixel (transparent GIF)
    res_open = await client.get("/api/track/open/507f1f77bcf86cd799439011.gif")
    assert res_open.status_code == 200
    assert res_open.headers["content-type"] == "image/gif"

    # Click tracking (redirect)
    res_click = await client.get(
        "/api/track/click/507f1f77bcf86cd799439011",
        params={"url": "https://example.com"},
        follow_redirects=False,
    )
    assert res_click.status_code == 307

    # Unsubscribe (redirect)
    res_unsub = await client.get(
        "/api/track/unsubscribe/507f1f77bcf86cd799439011",
        follow_redirects=False,
    )
    assert res_unsub.status_code == 307


# ---------------------------------------------------------------------------
# 2. Unauthorized Access Blocked (HTTP 401)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthorized_settings_get_blocked(client):
    """Accessing settings without credentials returns 401."""
    res = await client.get("/api/settings")
    assert res.status_code == 401
    assert res.json()["success"] is False


@pytest.mark.asyncio
async def test_unauthorized_settings_update_blocked(client):
    """Updating settings without credentials returns 401."""
    res = await client.post("/api/settings", json={"smtp": {"host": "smtp.evil.com"}})
    assert res.status_code == 401
    assert res.json()["success"] is False


@pytest.mark.asyncio
async def test_unauthorized_smtp_test_blocked(client):
    """Triggering SMTP test email without credentials returns 401."""
    res = await client.post("/api/settings/test-smtp", json={"recipientEmail": "target@example.com"})
    assert res.status_code == 401
    assert res.json()["success"] is False


@pytest.mark.asyncio
async def test_unauthorized_outreach_send_blocked(client):
    """Triggering outreach email dispatch without credentials returns 401."""
    res = await client.post(
        "/api/outreach/507f1f77bcf86cd799439011/send",
        json={"recipientEmail": "lead@target.com"},
    )
    assert res.status_code == 401
    assert res.json()["success"] is False


@pytest.mark.asyncio
async def test_unauthorized_outreach_records_and_export_blocked(client):
    """Accessing outbox records and Excel exports without credentials returns 401."""
    res_records = await client.get("/api/outreach/records")
    assert res_records.status_code == 401

    res_export = await client.get("/api/outreach/export")
    assert res_export.status_code == 401


@pytest.mark.asyncio
async def test_unauthorized_company_destructive_blocked(client):
    """Wiping all companies or deleting a single company without credentials returns 401."""
    res_delete_all = await client.delete("/api/companies")
    assert res_delete_all.status_code == 401

    res_delete_one = await client.delete("/api/companies/507f1f77bcf86cd799439011")
    assert res_delete_one.status_code == 401


@pytest.mark.asyncio
async def test_unauthorized_company_and_contact_reads_blocked(client):
    """Accessing company list or contact lists without credentials returns 401."""
    res_comp = await client.get("/api/companies")
    assert res_comp.status_code == 401

    res_cont = await client.get("/api/contacts")
    assert res_cont.status_code == 401


@pytest.mark.asyncio
async def test_unauthorized_excel_import_blocked(client):
    """Uploading Excel files without credentials returns 401."""
    res = await client.post(
        "/api/import/excel",
        files={"file": ("leads.xlsx", b"dummy content", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# 3. Authentication & Login Endpoint Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_with_invalid_credentials_rejected(client):
    """Login with wrong password returns 401."""
    res = await client.post("/api/auth/login", json={"username": "testadmin", "password": "wrongpassword"})
    assert res.status_code == 401
    assert "Invalid username or password" in res.json()["message"]


@pytest.mark.asyncio
async def test_login_with_valid_credentials_succeeds(client):
    """Login with valid credentials returns 200 and access token."""
    res = await client.post("/api/auth/login", json={"username": "testadmin", "password": "testpassword123"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "token" in data
    assert data["user"]["username"] == "testadmin"

    # Verify the generated token using security helper
    token = data["token"]
    payload = verify_access_token(token)
    assert payload is not None
    assert payload["sub"] == "testadmin"


@pytest.mark.asyncio
async def test_auth_me_endpoint(client, valid_token):
    """GET /api/auth/me returns current user identity when token provided."""
    res_unauth = await client.get("/api/auth/me")
    assert res_unauth.status_code == 401

    res_auth = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {valid_token}"})
    assert res_auth.status_code == 200
    assert res_auth.json()["user"]["username"] == "testadmin"


# ---------------------------------------------------------------------------
# 4. Authorized Access Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorized_settings_get_with_bearer_token(client, valid_token):
    """GET /api/settings succeeds with valid Bearer token."""
    res = await client.get("/api/settings", headers={"Authorization": f"Bearer {valid_token}"})
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert "smtp" in res.json()["data"]


@pytest.mark.asyncio
async def test_authorized_with_api_key(client):
    """Protected endpoints succeed when valid X-API-Key header is provided."""
    res = await client.get("/api/settings", headers={"X-API-Key": "test_api_key_xyz_789"})
    assert res.status_code == 200
    assert res.json()["success"] is True


@pytest.mark.asyncio
async def test_authorized_with_bearer_api_key(client):
    """Protected endpoints accept static API key passed in Authorization: Bearer <key>."""
    res = await client.get("/api/companies", headers={"Authorization": "Bearer test_api_key_xyz_789"})
    assert res.status_code == 200
    assert res.json()["success"] is True


# ---------------------------------------------------------------------------
# 5. Tampered & Expired Token Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tampered_token_rejected(client, valid_token):
    """Token with modified payload or signature is rejected with 401."""
    parts = valid_token.split(".")
    tampered = f"{parts[0]}xyz.{parts[1]}"
    res = await client.get("/api/settings", headers={"Authorization": f"Bearer {tampered}"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_rejected(client):
    """Token that has expired in the past is rejected with 401."""
    # Create token expired 10 seconds ago
    expired_token = create_access_token("testadmin", expires_in_seconds=-10)
    res = await client.get("/api/settings", headers={"Authorization": f"Bearer {expired_token}"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# 6. Password Hashing Utility Tests
# ---------------------------------------------------------------------------


def test_password_hashing_and_verification():
    """PBKDF2 password hashing and verification function correctly."""
    pwd = "MySecretPassword2026!"
    hashed = hash_password(pwd)
    assert hashed.startswith("pbkdf2_sha256$100000$")
    assert verify_password(pwd, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


# ---------------------------------------------------------------------------
# 7. Brute-Force Rate Limiting Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_brute_force_rate_limiting(client):
    """5 consecutive failed logins trigger HTTP 429 lockout."""
    from app.auth.security import reset_failed_logins

    reset_failed_logins("127.0.0.1")

    # Send 5 failed login attempts
    for i in range(5):
        res = await client.post("/api/auth/login", json={"username": "testadmin", "password": f"wrong_{i}"})
        assert res.status_code == 401

    # 6th attempt must be rate-limited with HTTP 429
    res_locked = await client.post("/api/auth/login", json={"username": "testadmin", "password": "wrong_6"})
    assert res_locked.status_code == 429
    assert "Too many failed login attempts" in res_locked.json()["message"]

    # Even with correct password, locked IP is blocked until lockout window or reset
    res_blocked_correct = await client.post("/api/auth/login", json={"username": "testadmin", "password": "testpassword123"})
    assert res_blocked_correct.status_code == 429

    # Clean up state for subsequent tests
    reset_failed_logins("127.0.0.1")


# ---------------------------------------------------------------------------
# 8. Production Startup Configuration Safety Tests
# ---------------------------------------------------------------------------


def test_production_startup_validation_fails_safely():
    """Production startup raises RuntimeError if credentials or signing secrets are missing or weak."""
    from app.auth.security import validate_auth_config_for_production

    # 1. Non-production environment passes safely
    os.environ["NODE_ENV"] = "development"
    validate_auth_config_for_production()  # does not raise

    # 2. Production environment with missing/weak password raises
    try:
        os.environ["NODE_ENV"] = "production"
        os.environ["ADMIN_PASSWORD"] = "short"  # < 8 chars
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
            validate_auth_config_for_production()

        # Weak placeholder password raises
        os.environ["ADMIN_PASSWORD"] = "change_this_to_a_secure_password"
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
            validate_auth_config_for_production()

        # Valid password but weak secret key raises
        os.environ["ADMIN_PASSWORD"] = "AStrongProductionPassword123!"
        os.environ["AUTH_SECRET_KEY"] = "short_key"  # < 32 chars
        with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
            validate_auth_config_for_production()

        # Both valid passes
        os.environ["AUTH_SECRET_KEY"] = "a_super_strong_production_signing_key_at_least_32_bytes_long"
        validate_auth_config_for_production()  # passes without exception
    finally:
        # Restore test environment
        os.environ["NODE_ENV"] = "development"
        os.environ["ADMIN_PASSWORD"] = "testpassword123"
        os.environ["AUTH_SECRET_KEY"] = "test_secret_key_for_unit_tests_32_bytes_long"

