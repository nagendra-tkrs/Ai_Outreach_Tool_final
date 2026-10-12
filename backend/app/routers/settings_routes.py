import os
from typing import Any, Dict, Optional
from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import RedirectResponse
from app.config.database import get_database
from app.services.email_service import send_test_email, is_masked_secret
from app.services.gmail_reply_service import (
    get_authorization_url,
    verify_oauth_state,
    exchange_authorization_code,
    get_gmail_oauth_settings,
    save_gmail_oauth_settings,
)

router = APIRouter()


def mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "********"
    return f"{secret[:4]}...{secret[-4:]}"


@router.get("")
@router.get("/")
async def get_settings():
    db = get_database()
    setting = await db.settings.find_one({"key": "global_settings"})
    if not setting:
        setting = {"key": "global_settings"}
        await db.settings.insert_one(setting)

    ai = setting.get("ai") or {}
    smtp = setting.get("smtp") or {}
    sender_profile = setting.get("senderProfile") or {}

    ollama_env = os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434"
    raw_pass = smtp.get("pass") or smtp.get("pass_") or ""

    gmail_oauth = setting.get("gmailOAuth") or {}
    raw_client_secret = gmail_oauth.get("clientSecret") or ""
    raw_refresh_token = gmail_oauth.get("refreshToken") or ""

    safe_setting = {
        "ai": {
            "provider": ai.get("provider") or "ollama",
            "ollamaBaseUrl": ai.get("ollamaBaseUrl") or ollama_env,
            "model": ai.get("model") or "llama3",
        },
        "smtp": {
            "host": smtp.get("host") or "",
            "port": smtp.get("port") or 587,
            "secure": bool(smtp.get("secure", False)),
            "user": smtp.get("user") or "",
            "pass": mask_secret(raw_pass),
            "hasPass": bool(raw_pass),
            "fromName": smtp.get("fromName") or "AI Outreach",
            "fromEmail": smtp.get("fromEmail") or "",
        },
        "senderProfile": sender_profile,
        "gmailOAuth": {
            "clientId": gmail_oauth.get("clientId") or "",
            "clientSecret": mask_secret(raw_client_secret),
            "hasClientSecret": bool(raw_client_secret),
            "hasRefreshToken": bool(raw_refresh_token),
            "userEmail": gmail_oauth.get("userEmail") or "",
            "isConfigured": bool(gmail_oauth.get("clientId") and raw_client_secret and raw_refresh_token),
        },
    }

    return {"success": True, "data": safe_setting}


@router.post("")
@router.post("/")
async def update_settings(payload: dict = Body(...)):
    db = get_database()
    setting = await db.settings.find_one({"key": "global_settings"})
    if not setting:
        setting = {"key": "global_settings", "ai": {}, "smtp": {}, "senderProfile": {}}

    ai = payload.get("ai")
    smtp = payload.get("smtp")
    sender_profile = payload.get("senderProfile")

    if "ai" not in setting or not isinstance(setting["ai"], dict):
        setting["ai"] = {}
    if "smtp" not in setting or not isinstance(setting["smtp"], dict):
        setting["smtp"] = {}
    if "senderProfile" not in setting or not isinstance(setting["senderProfile"], dict):
        setting["senderProfile"] = {}

    if ai:
        if ai.get("provider"):
            setting["ai"]["provider"] = ai["provider"]
        if ai.get("model"):
            setting["ai"]["model"] = ai["model"]
        if ai.get("ollamaBaseUrl"):
            setting["ai"]["ollamaBaseUrl"] = str(ai["ollamaBaseUrl"]).strip()

    if smtp:
        if "host" in smtp:
            setting["smtp"]["host"] = str(smtp["host"]).strip()
        if "port" in smtp:
            port_val = int(smtp["port"])
            setting["smtp"]["port"] = port_val
            # Auto-align secure flag if port 465 and secure not explicitly passed
            if port_val == 465 and "secure" not in smtp:
                setting["smtp"]["secure"] = True
        if "secure" in smtp:
            setting["smtp"]["secure"] = bool(smtp["secure"])
        if "user" in smtp:
            setting["smtp"]["user"] = str(smtp["user"]).strip()
        if "fromName" in smtp:
            setting["smtp"]["fromName"] = str(smtp["fromName"]).strip()
        if "fromEmail" in smtp:
            setting["smtp"]["fromEmail"] = str(smtp["fromEmail"]).strip()
        
        # Password preservation logic:
        # - If incoming smtp.pass is empty -> preserve existing DB password.
        # - If incoming smtp.pass is masked -> preserve existing DB password.
        # - If incoming smtp.pass is a new real password -> update the DB password.
        # - NEVER save ******** or abcd...1234 as the actual SMTP password.
        if "pass" in smtp:
            raw_pass = str(smtp["pass"]).strip() if smtp["pass"] is not None else ""
            if raw_pass and not is_masked_secret(raw_pass):
                setting["smtp"]["pass"] = raw_pass

    gmail_oauth = payload.get("gmailOAuth")
    if gmail_oauth and isinstance(gmail_oauth, dict):
        if "gmailOAuth" not in setting or not isinstance(setting["gmailOAuth"], dict):
            setting["gmailOAuth"] = {}
        if "clientId" in gmail_oauth and gmail_oauth["clientId"] is not None:
            setting["gmailOAuth"]["clientId"] = str(gmail_oauth["clientId"]).strip()
        if "userEmail" in gmail_oauth and gmail_oauth["userEmail"] is not None:
            setting["gmailOAuth"]["userEmail"] = str(gmail_oauth["userEmail"]).strip().lower()
        if "clientSecret" in gmail_oauth:
            secret = str(gmail_oauth["clientSecret"]).strip() if gmail_oauth["clientSecret"] is not None else ""
            if secret and not is_masked_secret(secret):
                setting["gmailOAuth"]["clientSecret"] = secret
        if "refreshToken" in gmail_oauth:
            rf_token = str(gmail_oauth["refreshToken"]).strip() if gmail_oauth["refreshToken"] is not None else ""
            if rf_token and not is_masked_secret(rf_token):
                setting["gmailOAuth"]["refreshToken"] = rf_token

    if sender_profile:
        setting["senderProfile"] = {**setting["senderProfile"], **sender_profile}

    await db.settings.update_one(
        {"key": "global_settings"},
        {"$set": setting},
        upsert=True,
    )

    # E10: warn (do not block) when the SMTP from-name and the sender profile
    # name disagree — the inbox From: field wins for what recipients actually
    # see, so a mismatch silently dilutes the sender identity/brand.
    warnings = []
    smtp_from = str(setting["smtp"].get("fromName") or "").strip()
    profile_name = str((setting.get("senderProfile") or {}).get("senderName") or "").strip()
    if smtp_from and profile_name and smtp_from.lower() != profile_name.lower():
        warnings.append(
            f"Sender identity mismatch: SMTP fromName is \"{smtp_from}\" but sender "
            f"profile name is \"{profile_name}\". Recipients will see the SMTP fromName "
            "in the From: field of delivered emails."
        )

    return {"success": True, "message": "Settings updated successfully", "warnings": warnings}


@router.post("/test-smtp")
async def test_smtp(payload: dict = Body(...)):
    smtp = payload.get("smtp")
    recipient_email = payload.get("recipientEmail")
    if not recipient_email or not str(recipient_email).strip():
        raise HTTPException(status_code=400, detail="Recipient email is required for test email.")
    result = await send_test_email(smtp, recipient_email.strip())
    msg = (
        "Test email generated using development sandbox"
        if result.get("isTest")
        else f"Test email dispatched to {recipient_email.strip()}"
    )
    return {
        "success": True,
        "message": msg,
        "data": result,
    }


# ---------------------------------------------------------------------------
# Gmail OAuth Handshake Routes
# ---------------------------------------------------------------------------

@router.get("/gmail/auth-url")
async def get_gmail_auth_url(redirectUri: Optional[str] = Query(None)):
    """Generate the Google OAuth authorization URL for Gmail read-only access."""
    # Default to the backend callback route if redirectUri is not specified
    port = os.getenv("PORT", "5000")
    fallback_redirect = f"http://localhost:{port}/api/settings/gmail/oauth/callback"
    target_redirect = redirectUri.strip() if redirectUri else fallback_redirect

    auth_url, err = await get_authorization_url(redirect_uri=target_redirect)
    if err:
        raise HTTPException(status_code=400, detail=err)

    return {
        "success": True,
        "authUrl": auth_url,
        "redirectUri": target_redirect,
    }


@router.get("/gmail/oauth/callback")
async def handle_gmail_oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    """Browser redirect callback from Google OAuth consent screen."""
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    settings_page_url = f"{frontend_url}/settings"

    if error:
        logger_msg = f"Google OAuth consent denied or failed: {error}"
        return RedirectResponse(
            url=f"{settings_page_url}?gmail=error&detail={error}",
            status_code=302,
        )

    if not code:
        return RedirectResponse(
            url=f"{settings_page_url}?gmail=error&detail=missing_code",
            status_code=302,
        )

    # Validate CSRF state
    if not state or not verify_oauth_state(state):
        return RedirectResponse(
            url=f"{settings_page_url}?gmail=error&detail=invalid_csrf_state",
            status_code=302,
        )

    port = os.getenv("PORT", "5000")
    redirect_uri = f"http://localhost:{port}/api/settings/gmail/oauth/callback"

    result, err = await exchange_authorization_code(code=code, redirect_uri=redirect_uri)
    if err:
        import urllib.parse
        encoded_err = urllib.parse.quote(err)
        return RedirectResponse(
            url=f"{settings_page_url}?gmail=error&detail={encoded_err}",
            status_code=302,
        )

    return RedirectResponse(
        url=f"{settings_page_url}?gmail=connected",
        status_code=302,
    )


@router.post("/gmail/exchange-code")
async def manual_exchange_code(payload: dict = Body(...)):
    """Exchange authorization code via direct API (e.g. for loopback, desktop apps, or modal flow)."""
    code = payload.get("code")
    redirect_uri = payload.get("redirectUri") or f"http://localhost:{os.getenv('PORT', '5000')}/api/settings/gmail/oauth/callback"
    state = payload.get("state")

    if state and not verify_oauth_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired CSRF state token.")

    if not code:
        raise HTTPException(status_code=400, detail="Authorization code is required.")

    result, err = await exchange_authorization_code(code=code, redirect_uri=redirect_uri)
    if err:
        raise HTTPException(status_code=400, detail=err)

    return {
        "success": True,
        "message": "Gmail account authorized successfully and refresh token saved.",
        "data": result,
    }


@router.post("/gmail/disconnect")
async def disconnect_gmail_oauth():
    """Disconnect Gmail OAuth by safely revoking/clearing tokens in DB settings."""
    await save_gmail_oauth_settings({
        "accessToken": "",
        "refreshToken": "",
        "tokenExpiry": None,
    })
    return {
        "success": True,
        "message": "Gmail account disconnected successfully.",
    }


