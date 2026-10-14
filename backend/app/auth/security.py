import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Optional, Tuple

logger = logging.getLogger("ai_outreach.auth")

# In-memory runtime fallback key if AUTH_SECRET_KEY is not configured
_RUNTIME_SECRET_KEY = secrets.token_hex(32)


def get_secret_key() -> str:
    key = os.getenv("AUTH_SECRET_KEY")
    if key and key.strip():
        return key.strip()
    return _RUNTIME_SECRET_KEY


def get_admin_username() -> str:
    return os.getenv("ADMIN_USERNAME", "admin").strip()


def get_admin_password() -> Optional[str]:
    pwd = os.getenv("ADMIN_PASSWORD")
    if pwd and pwd.strip():
        return pwd.strip()
    return None


def get_admin_api_key() -> Optional[str]:
    key = os.getenv("ADMIN_API_KEY")
    if key and key.strip():
        return key.strip()
    return None


def get_token_expire_hours() -> int:
    try:
        return int(os.getenv("AUTH_TOKEN_EXPIRE_HOURS", "24"))
    except ValueError:
        return 24


# In-memory brute-force protection
# Format: { ip_address: [timestamp1, timestamp2, ...] }
_FAILED_LOGINS: dict = {}
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300  # 5 minutes


def is_login_rate_limited(ip: str) -> bool:
    """Check if the given IP address is temporarily locked out due to excessive failed logins."""
    now = time.time()
    attempts = [t for t in _FAILED_LOGINS.get(ip, []) if now - t < LOGIN_LOCKOUT_SECONDS]
    _FAILED_LOGINS[ip] = attempts
    return len(attempts) >= MAX_FAILED_LOGIN_ATTEMPTS


def record_failed_login(ip: str) -> int:
    """Record a failed login attempt for the given IP address. Returns remaining attempts before lockout."""
    now = time.time()
    attempts = [t for t in _FAILED_LOGINS.get(ip, []) if now - t < LOGIN_LOCKOUT_SECONDS]
    attempts.append(now)
    _FAILED_LOGINS[ip] = attempts
    return max(0, MAX_FAILED_LOGIN_ATTEMPTS - len(attempts))


def reset_failed_logins(ip: str) -> None:
    """Clear failed login attempts upon successful authentication."""
    _FAILED_LOGINS.pop(ip, None)


def is_production() -> bool:
    env = os.getenv("NODE_ENV", "").strip().lower()
    app_env = os.getenv("ENVIRONMENT", "").strip().lower()
    return env in ("production", "prod") or app_env in ("production", "prod") or bool(os.getenv("RENDER"))


def validate_auth_config_for_production() -> None:
    """Ensure production startup fails safely if required credentials or signing secrets are missing or weak."""
    if not is_production():
        return

    admin_pass = get_admin_password()
    secret_key = os.getenv("AUTH_SECRET_KEY")

    if not admin_pass or admin_pass == "change_this_to_a_secure_password" or len(admin_pass) < 8:
        raise RuntimeError(
            "FATAL: In production, ADMIN_PASSWORD must be configured with a strong, non-default value of at least 8 characters."
        )

    if not secret_key or secret_key == "generate_a_random_32_character_secret_key" or len(secret_key) < 32:
        raise RuntimeError(
            "FATAL: In production, AUTH_SECRET_KEY must be configured with a random secret key of at least 32 characters."
        )


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (4 - (len(data) % 4)) if len(data) % 4 != 0 else ""
    return base64.urlsafe_b64decode((data + padding).encode("utf-8"))


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with 100,000 rounds and random salt."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    )
    return f"pbkdf2_sha256$100000${salt}${dk.hex()}"


def verify_password(plain_password: str, stored_hash_or_plain: str) -> bool:
    """Verify password against either a PBKDF2 hash or plain string using timing-safe comparison."""
    if not plain_password or not stored_hash_or_plain:
        return False

    if stored_hash_or_plain.startswith("pbkdf2_sha256$"):
        parts = stored_hash_or_plain.split("$")
        if len(parts) == 4:
            try:
                rounds = int(parts[1])
                salt = parts[2]
                expected_hex = parts[3]
                dk = hashlib.pbkdf2_hmac(
                    "sha256",
                    plain_password.encode("utf-8"),
                    salt.encode("utf-8"),
                    rounds,
                )
                return secrets.compare_digest(dk.hex(), expected_hex)
            except Exception:
                return False

    # Direct constant-time string comparison for simple environment password
    return secrets.compare_digest(plain_password, stored_hash_or_plain)


def authenticate_credentials(username: str, password: str) -> bool:
    """Authenticate administrator credentials against environment variables."""
    expected_user = get_admin_username()
    expected_pass = get_admin_password()

    if not username or not password:
        return False

    user_matches = secrets.compare_digest(username.strip(), expected_user)
    if not user_matches:
        return False

    # In production, ADMIN_PASSWORD must be set.
    # In development/test environments, if unset, we disallow login unless ALLOW_DEV_DEFAULT_AUTH is set.
    if not expected_pass:
        allow_dev = os.getenv("ALLOW_DEV_DEFAULT_AUTH", "").lower() in ("true", "1")
        if allow_dev:
            # Fallback dev credential
            return secrets.compare_digest(password, "admin")
        logger.error("ADMIN_PASSWORD is not configured in environment. Login rejected for safety.")
        return False

    return verify_password(password, expected_pass)


def create_access_token(username: str, expires_in_seconds: Optional[int] = None) -> str:
    """Generate a tamper-proof HMAC-SHA256 signed access token."""
    now = int(time.time())
    expiry = now + (expires_in_seconds or get_token_expire_hours() * 3600)
    payload = {
        "sub": username,
        "iat": now,
        "exp": expiry,
        "jti": secrets.token_hex(8),
    }

    payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64url_encode(payload_json)

    secret = get_secret_key().encode("utf-8")
    sig = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)

    return f"{payload_b64}.{sig_b64}"


def verify_access_token(token: str) -> Optional[dict]:
    """Verify an HMAC-SHA256 signed access token."""
    if not token or "." not in token:
        return None

    parts = token.split(".")
    if len(parts) != 2:
        return None

    payload_b64, sig_b64 = parts[0], parts[1]

    # Verify signature in constant time
    secret = get_secret_key().encode("utf-8")
    expected_sig = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    expected_sig_b64 = _b64url_encode(expected_sig)

    if not secrets.compare_digest(sig_b64, expected_sig_b64):
        return None

    try:
        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return None

    # Verify expiration
    now = int(time.time())
    exp = payload.get("exp")
    if not exp or not isinstance(exp, (int, float)) or now > exp:
        return None

    return payload


def verify_request_auth(
    auth_header: Optional[str] = None,
    api_key_header: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Validate either an Authorization: Bearer <token> or X-API-Key header.
    Returns (is_valid, username_or_error_message).
    """
    admin_api_key = get_admin_api_key()

    # 1. Check X-API-Key if configured
    if api_key_header and admin_api_key:
        if secrets.compare_digest(api_key_header.strip(), admin_api_key):
            return True, "api_key"

    # 2. Check Authorization header
    if auth_header and auth_header.strip():
        parts = auth_header.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()

            # If bearer token matches the static ADMIN_API_KEY, accept it
            if admin_api_key and secrets.compare_digest(token, admin_api_key):
                return True, "api_key"

            # Otherwise, verify as signed access token
            payload = verify_access_token(token)
            if payload and payload.get("sub"):
                return True, payload["sub"]

    return False, None
