import logging
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from app.config.database import get_database
from app.services.email_service import send_outreach_email
from app.services.quarantine_service import (
    QuarantineReleaseRequest,
    reconcile_missing_quarantine_audit_logs,
    release_quarantined_message_service,
    verify_admin_release_key,
)
from app.services.outreach_service import (
    bulk_generate_outreach,
    delete_outreach_message,
    generate_outreach_sequence,
    get_all_outreach,
    get_company_outreach,
    regenerate_outreach_message,
    update_outreach_message,
)
from app.services.outreach_tracking_service import (
    generate_outreach_excel_buffer,
    get_outreach_records,
    get_outreach_stats,
    update_reply_status,
)
from app.services.scheduler_service import schedule_sequence_steps
from app.services.gmail_reply_service import sync_gmail_replies_service, get_gmail_oauth_settings
from app.utils.bson_utils import is_valid_object_id, serialize_doc, to_object_id

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------- Company-specific outreach routes ----------------


@router.post("/companies/{company_id}/outreach/generate")
@router.post("/{company_id}/outreach/generate")
async def generate_sequence(company_id: str, payload: dict = Body(...)):
    messages = await generate_outreach_sequence(company_id, payload)
    return {
        "success": True,
        "message": "Personalized outreach sequence generated",
        "data": messages,
    }


@router.post("/companies/{company_id}/outreach/schedule")
@router.post("/{company_id}/outreach/schedule")
async def schedule_sequence(company_id: str, payload: dict = Body(...)):
    schedules = payload.get("schedules", [])
    updated = await schedule_sequence_steps(company_id, schedules)

    # Q6: surface quarantined messages the arming step refused to touch, so
    # the operator gets an explicit, safe result. Read-only: nothing about the
    # quarantined messages (status, quarantine metadata) is modified here.
    quarantined_skipped = []
    comp_oid = to_object_id(company_id)
    if comp_oid:
        steps = {
            s.get("step") for s in (schedules or [])
            if isinstance(s, dict) and s.get("step")
        }
        query = {"companyId": comp_oid, "quarantined": True}
        if steps:
            query["step"] = {"$in": sorted(steps)}
        cursor = get_database().outreachmessages.find(query, {"step": 1, "status": 1})
        quarantined_skipped = [
            {"messageId": str(m["_id"]), "step": m.get("step"), "status": m.get("status")}
            for m in await cursor.to_list(length=100)
        ]

    message = "Automated sequence schedule activated"
    if quarantined_skipped:
        message += (
            f"; {len(quarantined_skipped)} quarantined message(s) were skipped "
            "and remain quarantined"
        )
    return {
        "success": True,
        "message": message,
        "data": updated,
        "quarantinedSkipped": quarantined_skipped,
    }


@router.get("/companies/{company_id}/outreach")
@router.get("/{company_id}/outreach")
async def get_outreach(company_id: str):
    messages = await get_company_outreach(company_id)
    return {"success": True, "data": messages}


# ---------------- Global Outreach Tracking & Reporting ----------------


@router.get("/records")
async def get_tracking_records(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1),
    status: Optional[str] = Query(None),
    replyStatus: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sortBy: Optional[str] = Query("updatedAt"),
    sortDir: Optional[str] = Query("desc"),
):
    params = {
        "page": page,
        "limit": limit,
        "status": status,
        "replyStatus": replyStatus,
        "search": search,
        "sortBy": sortBy,
        "sortDir": sortDir,
    }
    result = await get_outreach_records(params)
    return {
        "success": True,
        "data": result["records"],
        "pagination": result["pagination"],
    }


@router.get("/records/{record_id}")
async def get_single_tracking_record(record_id: str):
    if not is_valid_object_id(record_id):
        raise HTTPException(status_code=400, detail="Invalid record ID")

    db = get_database()
    record = await db.outreachrecords.find_one({"_id": to_object_id(record_id)})
    if not record:
        raise HTTPException(status_code=404, detail="Outreach tracking record not found")

    # Populate companyId
    if record.get("companyId"):
        comp = await db.companies.find_one(
            {"_id": record["companyId"]},
            {"companyName": 1, "website": 1, "industry": 1, "country": 1},
        )
        if comp:
            record["companyId"] = serialize_doc(comp)

    # Populate contactId
    if record.get("contactId"):
        cnt = await db.contacts.find_one(
            {"_id": record["contactId"]},
            {"name": 1, "title": 1, "email": 1, "roleCategory": 1},
        )
        if cnt:
            record["contactId"] = serialize_doc(cnt)

    return {"success": True, "data": serialize_doc(record)}


@router.patch("/records/{record_id}/reply")
@router.post("/records/{record_id}/reply")
async def update_tracking_reply(record_id: str, payload: dict = Body(...)):
    reply_status = payload.get("replyStatus")
    if not reply_status:
        raise HTTPException(status_code=400, detail="replyStatus is required")

    updated = await update_reply_status(record_id, reply_status)
    return {
        "success": True,
        "message": f"Reply status updated to {updated.get('replyStatus')}",
        "data": updated,
    }


@router.get("/stats")
async def get_tracking_stats():
    stats = await get_outreach_stats()
    return {"success": True, "data": stats}


@router.post("/sync-replies")
async def trigger_gmail_reply_sync(payload: dict = Body(default={})):
    """Manually trigger safe read-only Gmail reply sync.

    Never starts the production scheduler, never calls SMTP, never sends emails.
    Normalizes incoming messages and saves them idempotently to replyevents.
    """
    query = payload.get("query", "newer_than:7d")
    max_results = min(int(payload.get("maxResults", 20)), 50)
    result = await sync_gmail_replies_service(query=query, max_results=max_results)
    return result


@router.get("/reply-events")
async def get_reply_events(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """Retrieve ingested reply events from MongoDB."""
    db = get_database()
    skip = (page - 1) * limit
    cursor = db.replyevents.find({}).sort("receivedAt", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    total = await db.replyevents.count_documents({})
    return {
        "success": True,
        "data": [serialize_doc(d) for d in docs],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "totalPages": (total + limit - 1) // limit if limit > 0 else 1,
        },
    }



@router.get("/export")
async def export_outreach_excel(
    status: Optional[str] = Query(None),
    replyStatus: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    query_params = {
        "status": status,
        "replyStatus": replyStatus,
        "search": search,
    }
    export_data = await generate_outreach_excel_buffer(query_params)
    buffer = export_data["buffer"]
    filename = export_data["filename"]
    return Response(
        content=buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------- Direct / Global Outbox Message routes ----------------


@router.get("/all")
async def get_global_outbox(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1),
    status: Optional[str] = Query(None),
    step: Optional[int] = Query(None),
    companyId: Optional[str] = Query(None),
):
    query = {
        "page": page,
        "limit": limit,
        "status": status,
        "step": step,
        "companyId": companyId,
    }
    messages = await get_all_outreach(query)
    return {"success": True, "data": messages}


@router.post("/bulk-generate")
async def bulk_generate(payload: dict = Body(...)):
    company_ids = payload.get("companyIds", [])
    options = payload.get("options", {})
    results = await bulk_generate_outreach(company_ids, options)
    return {
        "success": True,
        "message": "Bulk outreach generation completed",
        "data": results,
    }


@router.put("/{message_id}")
async def update_message(message_id: str, payload: dict = Body(...)):
    message, sync_info = await update_outreach_message(message_id, payload)
    resp = {"success": True, "data": message}
    sync = sync_info or {}
    has_signal = any(
        (sync.get("updated"), sync.get("paused"), sync.get("conflicts"),
         sync.get("skippedInvalid"), sync.get("ccUpdated"))
    )
    if has_signal:
        resp["recipientSync"] = sync
        cc_note = ""
        if sync.get("ccUpdated"):
            cc_note = f" CC recipients synchronized to {sync['ccUpdated']} unsent follow-up(s)."
        if sync.get("paused"):
            resp["message"] = (
                "Step 1 recipient changed after send — affected follow-ups were paused for manual review."
                + cc_note
            )
        elif sync.get("conflicts"):
            resp["message"] = (
                f"Step 1 recipient updated — {sync.get('updated', 0)} follow-up(s) synchronized; "
                f"{len(sync['conflicts'])} follow-up(s) had a different recipient and were "
                "flagged/paused for review (not overwritten)." + cc_note
            )
        elif sync.get("updated"):
            resp["message"] = (
                f"Step 1 recipient updated — {sync['updated']} unsent follow-up(s) "
                "synchronized to the new recipient." + cc_note
            )
        elif sync.get("skippedInvalid"):
            resp["message"] = (
                "Recipient saved, but it is not a valid email — follow-ups were NOT synchronized."
                + cc_note
            )
        elif cc_note:
            resp["message"] = cc_note.strip()
        else:
            resp["message"] = "Draft updated successfully"
    else:
        resp["message"] = "Draft updated successfully"
    return resp


@router.post("/{message_id}/regenerate")
async def regenerate_message(message_id: str, payload: dict = Body(default={})):
    message = await regenerate_outreach_message(message_id, payload)
    return {
        "success": True,
        "message": "Step 1 email regenerated from Evidence + Recommended Service — review before sending.",
        "data": message,
    }


@router.delete("/{message_id}")
async def remove_message(message_id: str):
    result = await delete_outreach_message(message_id)
    return {"success": True, "message": result.get("message", "Message deleted")}


@router.post("/{message_id}/send")
async def send_email(message_id: str, payload: dict = Body(...)):
    recipient_email = payload.get("recipientEmail")
    cc_recipients = payload.get("ccRecipients")
    bcc_recipients = payload.get("bccRecipients")

    result = await send_outreach_email(
        message_id,
        {
            "recipientEmail": recipient_email,
            "ccRecipients": cc_recipients,
            "bccRecipients": bcc_recipients,
        },
    )
    return {
        "success": True,
        "message": "Email dispatched successfully",
        "data": result,
    }


@router.post("/quarantine/reconcile-audit-logs")
async def reconcile_quarantine_audit_logs(
    admin_key: str = Depends(verify_admin_release_key),
):
    return await reconcile_missing_quarantine_audit_logs()


@router.post("/{message_id}/release-quarantine")
async def release_quarantined_message(
    message_id: str,
    payload: QuarantineReleaseRequest = Body(...),
    admin_key: str = Depends(verify_admin_release_key),
):
    return await release_quarantined_message_service(message_id, payload, admin_key)

