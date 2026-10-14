import logging
from fastapi import APIRouter, Body, HTTPException, Request
from app.auth.security import (
    authenticate_credentials,
    create_access_token,
    get_admin_username,
    is_login_rate_limited,
    record_failed_login,
    reset_failed_logins,
)

logger = logging.getLogger("ai_outreach.auth")

router = APIRouter()


@router.post("/login")
async def login(request: Request, payload: dict = Body(...)):
    client_ip = request.client.host if request.client else "127.0.0.1"

    if is_login_rate_limited(client_ip):
        logger.warning(f"Login rejected: IP {client_ip} is rate limited due to repeated failures.")
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Please wait 5 minutes before trying again.",
        )

    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()

    if not username or not password:
        raise HTTPException(
            status_code=400,
            detail="Username and password are required.",
        )

    if not authenticate_credentials(username, password):
        remaining = record_failed_login(client_ip)
        logger.warning(
            f"Failed login attempt for username '{username}' from {client_ip}. Remaining attempts before lockout: {remaining}"
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password.",
        )

    # Clear failed attempts on successful authentication
    reset_failed_logins(client_ip)
    logger.info(f"Successful admin login from {client_ip}")

    token = create_access_token(username=username)
    return {
        "success": True,
        "message": "Authentication successful",
        "token": token,
        "user": {
            "username": username,
        },
    }


@router.get("/me")
async def get_current_user(request: Request):
    user = getattr(request.state, "user", None) or get_admin_username()
    return {
        "success": True,
        "user": {
            "username": user,
        },
    }


@router.post("/logout")
async def logout():
    return {
        "success": True,
        "message": "Logged out successfully",
    }
