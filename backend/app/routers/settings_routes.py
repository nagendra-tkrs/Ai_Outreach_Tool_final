import os
from fastapi import APIRouter, Body
from app.config.database import get_database
from app.services.email_service import send_test_email

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
            "pass": mask_secret(smtp.get("pass") or ""),
            "hasPass": bool(smtp.get("pass")),
            "fromName": smtp.get("fromName") or "AI Outreach",
            "fromEmail": smtp.get("fromEmail") or "",
        },
        "senderProfile": sender_profile,
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
            setting["smtp"]["port"] = int(smtp["port"])
        if "secure" in smtp:
            setting["smtp"]["secure"] = bool(smtp["secure"])
        if "user" in smtp:
            setting["smtp"]["user"] = str(smtp["user"]).strip()
        if "fromName" in smtp:
            setting["smtp"]["fromName"] = str(smtp["fromName"]).strip()
        if "fromEmail" in smtp:
            setting["smtp"]["fromEmail"] = str(smtp["fromEmail"]).strip()
        if smtp.get("pass") and "..." not in smtp["pass"]:
            setting["smtp"]["pass"] = smtp["pass"]

    if sender_profile:
        setting["senderProfile"] = {**setting["senderProfile"], **sender_profile}

    await db.settings.update_one(
        {"key": "global_settings"},
        {"$set": setting},
        upsert=True,
    )

    return {"success": True, "message": "Settings updated successfully"}


@router.post("/test-smtp")
async def test_smtp(payload: dict = Body(...)):
    smtp = payload.get("smtp")
    recipient_email = payload.get("recipientEmail")
    result = await send_test_email(smtp, recipient_email)
    msg = (
        "Test email generated using Ethereal sandbox (view preview link)"
        if result.get("isTest")
        else f"Test email dispatched to {recipient_email}"
    )
    return {
        "success": True,
        "message": msg,
        "data": result,
    }
