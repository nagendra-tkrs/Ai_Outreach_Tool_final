import os
import io
import math
from datetime import datetime, timedelta, timezone
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from fastapi import HTTPException
from app.config.database import get_db
from app.utils.bson_utils import to_object_id, serialize_doc
from app.services.send_guard import validate_recipient_email

MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

def format_date(date_val) -> str:
    if not date_val:
        return ''
    if isinstance(date_val, str):
        try:
            date_val = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
        except Exception:
            return ''
    if not isinstance(date_val, datetime):
        return ''
    return f"{date_val.day:02d}-{MONTH_NAMES[date_val.month - 1]}-{date_val.year}"

def format_time(date_val) -> str:
    if not date_val:
        return ''
    if isinstance(date_val, str):
        try:
            date_val = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
        except Exception:
            return ''
    if not isinstance(date_val, datetime):
        return ''
    hour = date_val.hour
    ampm = 'PM' if hour >= 12 else 'AM'
    hour = hour % 12 or 12
    return f"{hour:02d}:{date_val.minute:02d} {ampm}"

async def _find_step_message(db, company_id, step, recipient_email=None):
    """Find the outreachmessage for a company/step, preferring a recipient match."""
    query = {"companyId": company_id, "step": step}
    if recipient_email:
        query["recipientEmail"] = recipient_email
    msg = await db.outreachmessages.find_one(query, sort=[("updatedAt", -1)])
    if not msg and recipient_email:
        msg = await db.outreachmessages.find_one(
            {"companyId": company_id, "step": step}, sort=[("updatedAt", -1)]
        )
    return msg


# Default follow-up delays (days from the prior step's send) applied only when
# a message carries no explicit `delayDays` — the 3-day (Step 2) / 7-day (Step 3)
# drip policy. An explicit per-message delayDays is always authoritative.
DEFAULT_FOLLOWUP_DELAYS = {2: 3, 3: 7}


def _followup_delay(msg: dict, step: int) -> int:
    """The message's own explicit delayDays is authoritative; a MISSING delayDays
    falls back to the 3-day / 7-day policy default (an explicit 0 is kept)."""
    raw = msg.get("delayDays")
    if raw is None:
        return DEFAULT_FOLLOWUP_DELAYS.get(step, 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_FOLLOWUP_DELAYS.get(step, 0)


async def activate_followups_on_send(record: dict, db, company_id, recipient_email, now, triggering_step: int = 1):
    """Activate eligible Step 2/3 follow-ups when the prior step is sent.

    This ARMS draft follow-ups (draft -> scheduled) and RE-ANCHORS unsent
    follow-ups when Step 1 is sent to its actual send time (now), eliminating
    the drift edge-case where pre-scheduling before Step 1 caused follow-up
    dates to be calculated from the pre-activation time rather than the actual send time.

    Every state is handled explicitly and idempotently:
      * sent       -> record reflects SENT (idempotent re-send).
      * failed     -> record reflects FAILED.
      * scheduled (when triggering_step > 1) -> kept as-is since already anchored to Step 1.
      * draft / scheduled (when triggering_step == 1) -> armed/re-anchored to `now + delayDays`.
    """
    for step in (2, 3):
        key = {2: "followUp1", 3: "followUp2"}.get(step)
        if not key:
            continue
        msg = await _find_step_message(db, company_id, step, recipient_email)
        if not msg:
            record[key] = {"status": "PENDING"}
            continue
        status = msg.get("status")
        if status == "sent":
            record[key] = {
                "status": "SENT",
                "sentAt": msg.get("sentAt"),
                "messageId": str(msg.get("_id")),
            }
        elif status == "failed":
            record[key] = {"status": "FAILED", "error": msg.get("error") or "Previously failed"}
        elif triggering_step > 1 and status == "scheduled" and msg.get("scheduledAt"):
            # Subsequent step send (e.g. Step 2): keep Step 3's existing schedule that was already anchored to Step 1
            record[key] = {"scheduledAt": msg["scheduledAt"], "status": "PENDING"}
        else:
            # Step 1 was sent (or step was in draft): anchor or re-anchor to Step 1's actual send time (now)
            msg_recip = msg.get("recipientEmail") or recipient_email
            if not validate_recipient_email(msg_recip):
                record[key] = {"status": "PENDING"}
                continue

            delay = _followup_delay(msg, step)
            scheduled_at = now + timedelta(days=delay)
            armed = await db.outreachmessages.find_one_and_update(
                {
                    "_id": msg["_id"],
                    "status": {"$in": ["draft", "scheduled", "approved"]},
                },
                {"$set": {
                    "status": "scheduled",
                    "scheduledAt": scheduled_at,
                    "delayDays": delay,
                    "updatedAt": now,
                }},
                return_document=True,
            )
            if not armed:
                # Lost a race (sent/failed concurrently): leave the
                # record PENDING rather than claiming a schedule we do not own.
                record[key] = {"status": "PENDING"}
                continue
            record[key] = {"scheduledAt": scheduled_at, "status": "PENDING"}
    return record


async def cancel_pending_followups(company_id, recipient_email, reason: str = "prospect_replied"):
    """Cancel/skip every pending follow-up for a prospect (e.g. after a reply).

    Armed follow-up messages are returned to `draft` (never auto-sent again) and
    the matching record's pending follow-ups are marked CANCELLED. Already-sent
    steps are left untouched.
    """
    db = get_db()
    cid = to_object_id(company_id)
    if not cid or not recipient_email:
        return 0
    now = datetime.now(timezone.utc)
    res = await db.outreachmessages.update_many(
        {
            "companyId": cid,
            "recipientEmail": recipient_email,
            "step": {"$in": [2, 3]},
            "status": {"$in": ["scheduled", "approved"]},
        },
        {"$set": {"status": "draft", "cancelledReason": reason, "updatedAt": now}},
    )
    record = await db.outreachrecords.find_one({"companyId": cid, "recipientEmail": recipient_email})
    if record:
        updates = {"updatedAt": now}
        for key in ("followUp1", "followUp2"):
            if record.get(key, {}).get("status") == "PENDING":
                updates[f"{key}.status"] = "CANCELLED"
        await db.outreachrecords.update_one({"_id": record["_id"]}, {"$set": updates})
    return res.modified_count


async def record_email_dispatch(message: dict, dispatch_result: dict):
    if not message:
        return None

    db = get_db()
    cid = to_object_id(message.get('companyId'))
    contact_id = to_object_id(message.get('contactId'))
    target_email = (dispatch_result.get('recipientEmail') or message.get('recipientEmail') or '').strip().lower()

    if not cid or not target_email:
        return None

    company = await db.companies.find_one({"_id": cid}) or {}
    contact = await db.contacts.find_one({"_id": contact_id}) if contact_id else {}

    company_name = company.get('companyName') or 'Unknown Company'
    company_website = company.get('website') or ''
    contact_name = message.get('recipientName') or contact.get('name') or ''
    contact_designation = contact.get('title') or contact.get('designation') or ''

    cc_list = dispatch_result.get('ccRecipients') or message.get('ccRecipients') or []
    bcc_list = dispatch_result.get('bccRecipients') or message.get('bccRecipients') or []
    is_success = bool(dispatch_result.get('success'))
    now = dispatch_result.get('sentAt') or datetime.now(timezone.utc)
    step = int(message.get('step', 1))
    is_test_send = bool(dispatch_result.get('isTestSend') or message.get('isTestSend'))

    record = await db.outreachrecords.find_one({"companyId": cid, "recipientEmail": target_email})
    if not record:
        record = {
            "companyId": cid,
            "companyName": company_name,
            "companyWebsite": company_website,
            "contactId": contact_id,
            "contactName": contact_name,
            "contactDesignation": contact_designation,
            "recipientEmail": target_email,
            "cc": cc_list,
            "bcc": bcc_list,
            "emailSubject": message.get('subject', ''),
            "emailType": 'INITIAL',
            "initialEmail": {"status": 'PENDING'},
            "followUp1": {"status": 'PENDING'},
            "followUp2": {"status": 'PENDING'},
            "replyStatus": 'NO_REPLY',
            "campaignStatus": 'PENDING',
            "isTestSend": is_test_send,
            "createdAt": now,
            "updatedAt": now
        }
        res = await db.outreachrecords.insert_one(record)
        record["_id"] = res.inserted_id
    elif record.get('isTestSend') != is_test_send:
        # E9: keep the test/sandbox provenance tag consistent on existing records
        await db.outreachrecords.update_one(
            {"_id": record["_id"]}, {"$set": {"isTestSend": is_test_send}}
        )
        record["isTestSend"] = is_test_send

    if step == 1:
        record["emailSubject"] = message.get('subject', '')
        if is_success:
            record["initialEmail"] = {
                "sentAt": now,
                "status": 'SENT',
                "error": None,
                "messageId": str(message.get('_id', ''))
            }
            # Activate the drip: eligible Step 2/3 drafts are armed to `scheduled`
            # off this send (3-day / 7-day policy).
            await activate_followups_on_send(record, db, cid, target_email, now, triggering_step=1)
            record["campaignStatus"] = 'INITIAL_SENT'
            record["lastContactedAt"] = now
        else:
            record["initialEmail"]["status"] = 'FAILED'
            record["initialEmail"]["error"] = dispatch_result.get('error') or 'Dispatch failed'
            record["campaignStatus"] = 'FAILED'

    elif step == 2:
        if is_success:
            record["followUp1"] = {
                "sentAt": now,
                "status": 'SENT',
                "error": None,
                "messageId": str(message.get('_id', ''))
            }
            # Step 3 was normally armed when Step 1 went out; if it was only
            # activated later, arm it now from this send (idempotent).
            await activate_followups_on_send(record, db, cid, target_email, now, triggering_step=2)
            record["campaignStatus"] = 'FOLLOW_UP_1_SENT'
            record["lastContactedAt"] = now
        else:
            record["followUp1"]["status"] = 'FAILED'
            record["followUp1"]["error"] = dispatch_result.get('error') or 'Follow-up 1 failed'

    elif step == 3:
        if is_success:
            record["followUp2"] = {
                "sentAt": now,
                "status": 'SENT',
                "error": None,
                "messageId": str(message.get('_id', ''))
            }
            record["campaignStatus"] = 'FOLLOW_UP_2_SENT'
            record["lastContactedAt"] = now
        else:
            record["followUp2"]["status"] = 'FAILED'
            record["followUp2"]["error"] = dispatch_result.get('error') or 'Follow-up 2 failed'

    record["updatedAt"] = now
    await db.outreachrecords.update_one({"_id": record["_id"]}, {"$set": record})
    return record

async def get_outreach_records(query_params: dict = None):
    if query_params is None:
        query_params = {}

    db = get_db()
    query = {}
    if query_params.get('replyStatus'):
        query['replyStatus'] = query_params['replyStatus']
    if query_params.get('campaignStatus'):
        query['campaignStatus'] = query_params['campaignStatus']
    # E5: `status` query param maps to campaignStatus (same terminal field the
    # frontend uses for campaign stage filtering).
    if query_params.get('status'):
        query['campaignStatus'] = query_params['status']
    if query_params.get('companyId'):
        cid = to_object_id(query_params['companyId'])
        if cid:
            query['companyId'] = cid
    if query_params.get('search'):
        s = query_params['search']
        rx = {"$regex": s, "$options": "i"}
        query['$or'] = [
            {'companyName': rx},
            {'contactName': rx},
            {'recipientEmail': rx},
            {'emailSubject': rx}
        ]

    page = int(query_params.get('page', 1))
    limit = int(query_params.get('limit', 50))
    skip = (page - 1) * limit

    # E5: allowlist-driven sorting — no arbitrary field injection.
    allowed_sort_fields = {
        'updatedAt', 'createdAt', 'companyName', 'contactName',
        'recipientEmail', 'emailSubject', 'replyStatus', 'campaignStatus',
        'lastContactedAt'
    }
    sort_by = query_params.get('sortBy') or 'updatedAt'
    if sort_by not in allowed_sort_fields:
        sort_by = 'updatedAt'
    sort_dir = (query_params.get('sortDir') or 'desc').lower()
    sort_order = 1 if sort_dir == 'asc' else -1

    total = await db.outreachrecords.count_documents(query)
    cursor = db.outreachrecords.find(query).sort(sort_by, sort_order).skip(skip).limit(limit)
    records = await cursor.to_list(length=limit)

    return {
        "records": serialize_doc(records),
        "pagination": {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": math.ceil(total / limit) if limit > 0 else 1
        }
    }

async def update_reply_status(record_id: str, reply_status: str):
    db = get_db()
    rid = to_object_id(record_id)
    if not rid:
        raise HTTPException(status_code=400, detail="Invalid record ID")

    now = datetime.now(timezone.utc)
    update_data = {
        "replyStatus": reply_status,
        "updatedAt": now
    }
    if reply_status == 'REPLIED':
        update_data["repliedAt"] = now
        update_data["campaignStatus"] = 'REPLIED'

    await db.outreachrecords.update_one({"_id": rid}, {"$set": update_data})
    updated = await db.outreachrecords.find_one({"_id": rid})
    if not updated:
        raise HTTPException(status_code=404, detail="Record not found")
    if reply_status == 'REPLIED':
        # FIX 2 (requirement 8): a reply halts every pending follow-up. Armed
        # follow-up messages are cancelled so they can never auto-dispatch, and
        # the record's pending follow-ups are marked CANCELLED.
        await cancel_pending_followups(
            updated.get("companyId"), updated.get("recipientEmail"), reason="prospect_replied"
        )
        updated = await db.outreachrecords.find_one({"_id": rid})
    return serialize_doc(updated)

async def get_outreach_stats():
    db = get_db()
    # E9: production delivery stats must never count sandbox / test sends.
    real_only = {"isTestSend": {"$ne": True}}
    total = await db.outreachrecords.count_documents(real_only)
    initial_sent = await db.outreachrecords.count_documents({"initialEmail.status": "SENT", **real_only})
    f1_sent = await db.outreachrecords.count_documents({"followUp1.status": "SENT", **real_only})
    f2_sent = await db.outreachrecords.count_documents({"followUp2.status": "SENT", **real_only})
    replied = await db.outreachrecords.count_documents({"replyStatus": "REPLIED", **real_only})
    no_reply = await db.outreachrecords.count_documents({"replyStatus": "NO_REPLY", **real_only})

    # FIX 1: "Follow-ups Pending" = follow-ups that are armed (status PENDING with
    # a scheduledAt) and still awaiting dispatch. Unscheduled PENDING follow-ups
    # (an inactive sequence) are intentionally not counted.
    f1_pending = await db.outreachrecords.count_documents(
        {"followUp1.status": "PENDING", "followUp1.scheduledAt": {"$ne": None}, **real_only}
    )
    f2_pending = await db.outreachrecords.count_documents(
        {"followUp2.status": "PENDING", "followUp2.scheduledAt": {"$ne": None}, **real_only}
    )

    reply_rate = round((replied / initial_sent * 100), 1) if initial_sent > 0 else 0

    return {
        "totalProspects": total,
        "initialSent": initial_sent,
        "followUp1Sent": f1_sent,
        "followUp2Sent": f2_sent,
        "followUpsPending": f1_pending + f2_pending,
        "totalDispatched": initial_sent + f1_sent + f2_sent,
        "replied": replied,
        "noReply": no_reply,
        "replyRate": f"{reply_rate}%"
    }

async def generate_outreach_excel_buffer(query_params: dict = None):
    res = await get_outreach_records({**(query_params or {}), 'limit': 5000, 'page': 1})
    records = res['records']

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Outreach Tracking"

    headers = [
        "Company Name", "Website", "Contact Name", "Designation", "Recipient Email",
        "CC", "Subject", "Initial Sent Date", "Initial Status",
        "Follow-Up 1 Sent Date", "Follow-Up 1 Status",
        "Follow-Up 2 Sent Date", "Follow-Up 2 Status",
        "Reply Status", "Campaign Status"
    ]

    ws.append(headers)

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E40AF", end_color="1E40AF", fill_type="solid")

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for rec in records:
        init_step = rec.get('initialEmail') or {}
        f1_step = rec.get('followUp1') or {}
        f2_step = rec.get('followUp2') or {}

        ws.append([
            rec.get('companyName', ''),
            rec.get('companyWebsite', ''),
            rec.get('contactName', ''),
            rec.get('contactDesignation', ''),
            rec.get('recipientEmail', ''),
            ", ".join(rec.get('cc', [])),
            rec.get('emailSubject', ''),
            format_date(init_step.get('sentAt')),
            init_step.get('status', 'PENDING'),
            format_date(f1_step.get('sentAt')),
            f1_step.get('status', 'PENDING'),
            format_date(f2_step.get('sentAt')),
            f2_step.get('status', 'PENDING'),
            rec.get('replyStatus', 'NO_REPLY'),
            rec.get('campaignStatus', 'PENDING')
        ])

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    buf = io.BytesIO()
    wb.save(buf)
    excel_bytes = buf.getvalue()

    filename = f"outreach_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
    return {"buffer": excel_bytes, "filename": filename}
