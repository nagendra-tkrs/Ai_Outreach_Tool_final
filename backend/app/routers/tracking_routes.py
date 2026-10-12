import base64
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Query, Response
from fastapi.responses import RedirectResponse
from app.config.database import get_database
from app.utils.bson_utils import is_valid_object_id, to_object_id

router = APIRouter()

TRANSPARENT_GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


@router.get("/open/{message_id}")
async def track_open(message_id: str):
    try:
        clean_id = re.sub(r"\.png|\.gif", "", message_id)
        if is_valid_object_id(clean_id):
            db = get_database()
            now = datetime.now(timezone.utc)
            await db.outreachmessages.update_one(
                {"_id": to_object_id(clean_id)},
                {
                    "$inc": {"openCount": 1},
                    "$set": {"openedAt": now},
                },
            )
    except Exception:
        pass

    return Response(
        content=TRANSPARENT_GIF,
        media_type="image/gif",
        headers={
            "Content-Length": str(len(TRANSPARENT_GIF)),
            "Cache-Control": "no-cache, no-store, must-revalidate, private",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/click/{message_id}")
async def track_click(message_id: str, url: Optional[str] = Query(None)):
    try:
        clean_id = re.sub(r"\.png|\.gif", "", message_id)
        if is_valid_object_id(clean_id):
            db = get_database()
            now = datetime.now(timezone.utc)
            await db.outreachmessages.update_one(
                {"_id": to_object_id(clean_id)},
                {
                    "$inc": {"clickCount": 1},
                    "$set": {"clickedAt": now},
                },
            )
    except Exception:
        pass

    # E7: never trust the raw redirect target. Only http/https URLs with an
    # explicit host are allowed through; javascript:, data:, vbscript:, file:,
    # and empty schemes are treated as an open-redirect vector and blocked.
    redirect_target = "/"
    if url:
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme in ("http", "https") and parsed.netloc:
            redirect_target = url.strip()
    return RedirectResponse(url=redirect_target, status_code=307)


@router.get("/unsubscribe/{message_id}")
async def track_unsubscribe(message_id: str, source: Optional[str] = Query(None)):
    """E4: one-click unsubscribe — registers the recipient as suppressed so no
    further outreach (initial, follow-ups, or manual) can be sent to them."""
    result = {"success": False, "message": "Invalid unsubscribe link"}
    try:
        clean_id = re.sub(r"\.png|\.gif", "", message_id)
        if is_valid_object_id(clean_id):
            db = get_database()
            msg = await db.outreachmessages.find_one({"_id": to_object_id(clean_id)})
            if msg and msg.get("recipientEmail"):
                from app.services.send_guard import add_suppression_record

                await add_suppression_record(
                    msg["recipientEmail"],
                    reason="Unsubscribed via List-Unsubscribe header or link",
                    source=source or f"message:{clean_id}",
                )
                result = {"success": True, "message": "You have been unsubscribed from further outreach emails."}
    except Exception:
        result = {"success": False, "message": "Invalid unsubscribe link"}

    return RedirectResponse(
        url="/unsubscribed",
        status_code=307,
    )
