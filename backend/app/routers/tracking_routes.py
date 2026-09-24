import base64
import re
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

    if url:
        return RedirectResponse(url=url, status_code=307)
    return RedirectResponse(url="/", status_code=307)
