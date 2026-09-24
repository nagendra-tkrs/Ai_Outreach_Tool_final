import os
import io
import math
from datetime import datetime, timedelta
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from fastapi import HTTPException
from app.config.database import get_db
from app.utils.bson_utils import to_object_id, serialize_doc

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

def get_follow_up_delays() -> tuple[int, int]:
    f1 = int(os.getenv('FOLLOW_UP_1_DELAY_DAYS', 3))
    f2 = int(os.getenv('FOLLOW_UP_2_DELAY_DAYS', 5))
    return f1, f2

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
    f1_days, f2_days = get_follow_up_delays()
    is_success = bool(dispatch_result.get('success'))
    now = dispatch_result.get('sentAt') or datetime.utcnow()
    step = int(message.get('step', 1))

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
            "createdAt": now,
            "updatedAt": now
        }
        res = await db.outreachrecords.insert_one(record)
        record["_id"] = res.inserted_id

    if step == 1:
        record["emailSubject"] = message.get('subject', '')
        if is_success:
            record["initialEmail"] = {
                "sentAt": now,
                "status": 'SENT',
                "error": None,
                "messageId": str(message.get('_id', ''))
            }
            record["followUp1"] = {
                "scheduledAt": now + timedelta(days=f1_days),
                "status": 'PENDING'
            }
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
            record["followUp2"] = {
                "scheduledAt": now + timedelta(days=f2_days),
                "status": 'PENDING'
            }
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

    total = await db.outreachrecords.count_documents(query)
    cursor = db.outreachrecords.find(query).sort("updatedAt", -1).skip(skip).limit(limit)
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

    now = datetime.utcnow()
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
    return serialize_doc(updated)

async def get_outreach_stats():
    db = get_db()
    total = await db.outreachrecords.count_documents({})
    initial_sent = await db.outreachrecords.count_documents({"initialEmail.status": "SENT"})
    f1_sent = await db.outreachrecords.count_documents({"followUp1.status": "SENT"})
    f2_sent = await db.outreachrecords.count_documents({"followUp2.status": "SENT"})
    replied = await db.outreachrecords.count_documents({"replyStatus": "REPLIED"})
    no_reply = await db.outreachrecords.count_documents({"replyStatus": "NO_REPLY"})

    reply_rate = round((replied / initial_sent * 100), 1) if initial_sent > 0 else 0

    return {
        "totalProspects": total,
        "initialSent": initial_sent,
        "followUp1Sent": f1_sent,
        "followUp2Sent": f2_sent,
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

    filename = f"outreach_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return {"buffer": excel_bytes, "filename": filename}
