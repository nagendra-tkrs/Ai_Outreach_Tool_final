import asyncio
import logging
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from app.config.database import get_database
from app.utils.bson_utils import serialize_doc, to_object_id
from app.services.email_service import send_outreach_email
from app.services.outreach_service import generate_outreach_sequence

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_is_processing = False


async def schedule_sequence_steps(company_id: str, schedules: list = None) -> list:
    """Schedule automated sequence steps with day delays."""
    if schedules is None:
        schedules = []

    db = get_database()
    now = datetime.now(timezone.utc)
    updated_messages = []
    comp_oid = to_object_id(company_id)

    for s in schedules:
        delay_days = s.get("delayDays", 0) or 0
        step = s.get("step")
        if not step:
            continue

        scheduled_time = now + timedelta(days=delay_days)
        new_status = "approved" if delay_days == 0 else "scheduled"

        msg = await db.outreachmessages.find_one_and_update(
            {
                "companyId": comp_oid,
                "step": step,
                "status": {"$in": ["draft", "approved", "scheduled"]},
            },
            {
                "$set": {
                    "status": new_status,
                    "delayDays": delay_days,
                    "scheduledAt": scheduled_time,
                    "updatedAt": now,
                }
            },
            return_document=True,
        )
        if msg:
            updated_messages.append(serialize_doc(msg))

    return updated_messages


async def process_automated_follow_ups():
    """Process automated follow-ups from OutreachRecord."""
    db = get_database()
    now = datetime.now(timezone.utc)

    # 1. Process Follow-up 1
    cursor_f1 = db.outreachrecords.find(
        {
            "initialEmail.status": "SENT",
            "followUp1.status": "PENDING",
            "followUp1.scheduledAt": {"$lte": now},
            "replyStatus": "NO_REPLY",
        }
    ).limit(10)

    due_f1_records = await cursor_f1.to_list(length=10)

    for record in due_f1_records:
        current = await db.outreachrecords.find_one({"_id": record["_id"]})
        if (
            not current
            or current.get("replyStatus") == "REPLIED"
            or current.get("followUp1", {}).get("status") == "SENT"
        ):
            continue

        logger.info(
            f"[Scheduler] Dispatching Follow-up 1 for {record.get('companyName')} to {record.get('recipientEmail')}"
        )

        try:
            msg = await db.outreachmessages.find_one(
                {
                    "companyId": record["companyId"],
                    "step": 2,
                    "status": {"$ne": "sent"},
                }
            )

            if not msg:
                try:
                    generated = await generate_outreach_sequence(
                        str(record["companyId"]),
                        {"contactId": str(record.get("contactId")) if record.get("contactId") else None},
                    )
                    for m in generated:
                        if m.get("step") == 2:
                            msg = await db.outreachmessages.find_one({"_id": to_object_id(m["id"])})
                            break
                except Exception as gen_err:
                    logger.warning(f"[Scheduler] Could not generate sequence step 2: {gen_err}")

            if msg:
                await send_outreach_email(
                    str(msg["_id"]),
                    {
                        "recipientEmail": record.get("recipientEmail"),
                        "ccRecipients": record.get("cc", []),
                        "bccRecipients": record.get("bcc", []),
                    },
                )
            else:
                contact_name = record.get("contactName") or "there"
                comp_name = record.get("companyName") or "your company"
                fallback_msg = {
                    "companyId": record["companyId"],
                    "contactId": record.get("contactId"),
                    "step": 2,
                    "stepLabel": "Step 2: Practical Value & Workflow Proof",
                    "subject": f"Re: AI Strategic Collaboration with {comp_name}",
                    "bodyHtml": f"<p>Hi {contact_name},</p><p>Following up on my previous message regarding how AI automation can accelerate {comp_name}. Would you have 10 minutes this week for a brief conversation?</p>",
                    "bodyText": f"Hi {contact_name},\n\nFollowing up on my previous message regarding how AI automation can accelerate {comp_name}. Would you have 10 minutes this week for a brief conversation?",
                    "recipientEmail": record.get("recipientEmail"),
                    "ccRecipients": record.get("cc", []),
                    "bccRecipients": record.get("bcc", []),
                    "status": "draft",
                    "createdAt": now,
                    "updatedAt": now,
                }
                insert_res = await db.outreachmessages.insert_one(fallback_msg)
                await send_outreach_email(
                    str(insert_res.inserted_id),
                    {
                        "recipientEmail": record.get("recipientEmail"),
                        "ccRecipients": record.get("cc", []),
                        "bccRecipients": record.get("bcc", []),
                    },
                )
        except Exception as err:
            logger.error(f"[Scheduler] Follow-up 1 failed for {record.get('recipientEmail')}: {err}")

    # 2. Process Follow-up 2
    cursor_f2 = db.outreachrecords.find(
        {
            "followUp1.status": "SENT",
            "followUp2.status": "PENDING",
            "followUp2.scheduledAt": {"$lte": now},
            "replyStatus": "NO_REPLY",
        }
    ).limit(10)

    due_f2_records = await cursor_f2.to_list(length=10)

    for record in due_f2_records:
        current = await db.outreachrecords.find_one({"_id": record["_id"]})
        if (
            not current
            or current.get("replyStatus") == "REPLIED"
            or current.get("followUp2", {}).get("status") == "SENT"
        ):
            continue

        logger.info(
            f"[Scheduler] Dispatching Follow-up 2 for {record.get('companyName')} to {record.get('recipientEmail')}"
        )

        try:
            msg = await db.outreachmessages.find_one(
                {
                    "companyId": record["companyId"],
                    "step": 3,
                    "status": {"$ne": "sent"},
                }
            )

            if not msg:
                try:
                    generated = await generate_outreach_sequence(
                        str(record["companyId"]),
                        {"contactId": str(record.get("contactId")) if record.get("contactId") else None},
                    )
                    for m in generated:
                        if m.get("step") == 3:
                            msg = await db.outreachmessages.find_one({"_id": to_object_id(m["id"])})
                            break
                except Exception as gen_err:
                    logger.warning(f"[Scheduler] Could not generate sequence step 3: {gen_err}")

            if msg:
                await send_outreach_email(
                    str(msg["_id"]),
                    {
                        "recipientEmail": record.get("recipientEmail"),
                        "ccRecipients": record.get("cc", []),
                        "bccRecipients": record.get("bcc", []),
                    },
                )
            else:
                contact_name = record.get("contactName") or "there"
                comp_name = record.get("companyName") or "your company"
                fallback_msg = {
                    "companyId": record["companyId"],
                    "contactId": record.get("contactId"),
                    "step": 3,
                    "stepLabel": "Step 3: Low-Friction Invitation",
                    "subject": f"Final Check-in: AI Strategy for {comp_name}",
                    "bodyHtml": f"<p>Hi {contact_name},</p><p>I know you're busy, so I'll keep this brief. If you're open to exploring whether our AI consulting can help {comp_name}, let me know. Otherwise, I will step back.</p>",
                    "bodyText": f"Hi {contact_name},\n\nI know you're busy, so I'll keep this brief. If you're open to exploring whether our AI consulting can help {comp_name}, let me know. Otherwise, I will step back.",
                    "recipientEmail": record.get("recipientEmail"),
                    "ccRecipients": record.get("cc", []),
                    "bccRecipients": record.get("bcc", []),
                    "status": "draft",
                    "createdAt": now,
                    "updatedAt": now,
                }
                insert_res = await db.outreachmessages.insert_one(fallback_msg)
                await send_outreach_email(
                    str(insert_res.inserted_id),
                    {
                        "recipientEmail": record.get("recipientEmail"),
                        "ccRecipients": record.get("cc", []),
                        "bccRecipients": record.get("bcc", []),
                    },
                )
        except Exception as err:
            logger.error(f"[Scheduler] Follow-up 2 failed for {record.get('recipientEmail')}: {err}")


async def process_scheduled_emails():
    """Background worker checking for due scheduled emails and automated follow-ups."""
    global _is_processing
    if _is_processing:
        return
    _is_processing = True

    try:
        db = get_database()
        now = datetime.now(timezone.utc)

        # 1. Check OutreachMessage scheduled queue
        cursor = db.outreachmessages.find(
            {
                "status": "scheduled",
                "scheduledAt": {"$lte": now},
            }
        ).limit(10)

        due_messages = await cursor.to_list(length=10)

        for msg in due_messages:
            tracking_record = await db.outreachrecords.find_one(
                {
                    "companyId": msg["companyId"],
                    "recipientEmail": msg.get("recipientEmail"),
                }
            )

            if tracking_record and tracking_record.get("replyStatus") == "REPLIED":
                logger.info(f"[Scheduler] Skipping message {msg['_id']} because contact already replied.")
                await db.outreachmessages.update_one(
                    {"_id": msg["_id"]},
                    {"$set": {"status": "draft", "updatedAt": now}},
                )
                continue

            logger.info(
                f"[Scheduler] Auto-dispatching scheduled Step {msg.get('step')} to {msg.get('recipientEmail', 'prospect')}..."
            )
            try:
                await send_outreach_email(str(msg["_id"]))
                logger.info(f"[Scheduler] Successfully dispatched message ID: {msg['_id']}")
            except Exception as err:
                logger.error(f"[Scheduler] Failed to dispatch scheduled message ID {msg['_id']}: {err}")

        # 2. Check OutreachRecord automated follow-ups
        await process_automated_follow_ups()

    except Exception as err:
        logger.error(f"[Scheduler] Error processing scheduled emails: {err}")
    finally:
        _is_processing = False


async def _scheduler_loop(interval_sec: int = 60):
    logger.info(f"Automated Drip Sequence & Follow-up Scheduler started (checking every {interval_sec}s)")
    # Run once immediately on start
    await process_scheduled_emails()
    while True:
        try:
            await asyncio.sleep(interval_sec)
            await process_scheduled_emails()
        except asyncio.CancelledError:
            logger.info("[Scheduler] Scheduler loop cancelled.")
            break
        except Exception as e:
            logger.error(f"[Scheduler] Loop exception: {e}")


def start_scheduler(interval_sec: int = 60):
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_scheduler_loop(interval_sec))


def stop_scheduler():
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        _scheduler_task = None
