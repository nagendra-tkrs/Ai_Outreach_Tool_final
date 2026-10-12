import asyncio
import logging
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from app.config.database import get_database
from app.utils.bson_utils import serialize_doc, to_object_id
from app.services.email_service import send_outreach_email
from app.services.outreach_tracking_service import cancel_pending_followups
from app.services.send_guard import is_within_sending_window, is_message_quarantined, validate_recipient_email

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_is_processing = False


def _as_utc(value):
    """MongoDB returns CPython datetimes as offset-naive (client is
    tz_aware=False). Normalize anything read back for a Python-side comparison
    to an aware UTC datetime so it can be compared with `datetime.now(timezone.utc)`."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

# ---------------------------------------------------------------------------
# Scheduling policy
# ---------------------------------------------------------------------------
# The outreachmessage document is the single source of truth for whether an
# email may be dispatched automatically:
#
#   draft      -> generated only, NEVER auto-dispatched
#   approved   -> approved for a deliberate MANUAL send, NEVER auto-dispatched
#   scheduled  -> armed for automatic dispatch once scheduledAt is due, and
#                 only while the sequence's drip schedule is active
#   sending    -> claimed by a worker (atomic) and currently being dispatched
#   sent       -> terminal
#   failed     -> dispatch failed and will not be retried automatically
#
# Activation lifecycle:
#   * Generating a sequence creates `draft` messages only. This never activates
#     automatic sending.
#   * POST /companies/{id}/outreach/schedule is the explicit operator action
#     that activates the drip: step 1 becomes `approved` (manual, delay 0) and
#     each follow-up with delay > 0 becomes `scheduled` with the operator's
#     exact delayDays stored on the message.
#   * When step 1 is actually sent, follow-up schedules are anchored to that
#     send time using each message's own `delayDays` (never an environment
#     default), and the matching outreachrecord mirrors the same scheduledAt.
#   * A prospect reply cancels/skips pending follow-ups (message -> draft with
#     cancelledReason, record follow-up -> CANCELLED).
#
# Only `scheduled` messages are ever dispatched by the workers. Both the
# scheduled-message worker and the record reconciler claim a message atomically
# (status scheduled -> sending) so a message can never be dispatched twice.


async def _find_step_message(db, company_id, step, recipient_email=None, status=None,
                             exclude_quarantined=False):
    """Find the outreachmessage for a company/step, preferring a recipient match.

    `exclude_quarantined` is used by dispatch-selection callers so a quarantined
    message is never picked up for sending; lookups for bookkeeping (e.g. the
    previous step's send time) keep the message visible.
    """
    query = {"companyId": company_id, "step": step}
    if recipient_email:
        query["recipientEmail"] = recipient_email
    if status:
        query["status"] = status
    if exclude_quarantined:
        query["quarantined"] = {"$ne": True}
        query["quarantine.active"] = {"$ne": True}
    msg = await db.outreachmessages.find_one(query, sort=[("updatedAt", -1)])
    if not msg and recipient_email:
        # Fall back to the step's message regardless of recipient so legacy
        # messages whose recipient was normalised/changed are still found.
        fallback = {"companyId": company_id, "step": step}
        if status:
            fallback["status"] = status
        if exclude_quarantined:
            fallback["quarantined"] = {"$ne": True}
            fallback["quarantine.active"] = {"$ne": True}
        msg = await db.outreachmessages.find_one(fallback, sort=[("updatedAt", -1)])
    return msg


async def _step_base_time(db, company_id, step, recipient_email, now):
    """Anchor a follow-up to the previous step's actual send time when available.

    If an intermediate prior step has not been sent yet (e.g. Step 3 being scheduled
    while Step 2 is still scheduled), search earlier prior steps down to Step 1 so
    the sequence remains anchored to Step 1's actual send time rather than falling
    back to the current execution time.
    """
    if step <= 1:
        return now
    for prior_step in range(step - 1, 0, -1):
        prior = await _find_step_message(db, company_id, prior_step, recipient_email)
        if prior and prior.get("status") == "sent" and prior.get("sentAt"):
            return _as_utc(prior["sentAt"])
    return now


async def _sync_record_schedule(db, company_id, recipient_email, step, scheduled_time, now):
    """Mirror an activated follow-up schedule onto the matching outreachrecord."""
    if step < 2 or not recipient_email:
        return
    key = {2: "followUp1", 3: "followUp2"}.get(step)
    if not key:
        return
    record = await db.outreachrecords.find_one({"companyId": company_id, "recipientEmail": recipient_email})
    if not record:
        return
    prior_key = "initialEmail" if step == 2 else "followUp1"
    if record.get(prior_key, {}).get("status") != "SENT":
        # The previous step has not gone out yet; record_email_dispatch will set
        # the schedule the moment it does.
        return
    if record.get(key, {}).get("status") == "SENT":
        return
    await db.outreachrecords.update_one(
        {"_id": record["_id"]},
        {"$set": {f"{key}.scheduledAt": scheduled_time, f"{key}.status": "PENDING", "updatedAt": now}},
    )


async def schedule_sequence_steps(company_id: str, schedules: list = None) -> list:
    """Activate the drip schedule. This is the ONLY operator action that arms
    automatic follow-up sending.

    Step 1 (delay 0) becomes `approved` for manual sending. Every step with a
    positive delay becomes `scheduled` with the operator's exact delay stored on
    the message.
    """
    if schedules is None:
        schedules = []

    db = get_database()
    now = datetime.now(timezone.utc)
    comp_oid = to_object_id(company_id)
    updated_messages = []

    for s in schedules:
        try:
            delay_days = int(s.get("delayDays", 0) or 0)
        except (TypeError, ValueError):
            delay_days = 0
        step = s.get("step")
        if not step:
            continue
        if delay_days < 0:
            delay_days = 0

        new_status = "approved" if delay_days == 0 else "scheduled"

        # Q1: quarantine hard-stop at the ONLY arming path — an explicitly
        # quarantined message is never approved/scheduled/activated, whatever
        # its current status. A missing `quarantined` field (legacy message)
        # remains eligible, exactly as before. The filter is inside the atomic
        # update so no race can arm a message between check and write.
        msg = await db.outreachmessages.find_one_and_update(
            {
                "companyId": comp_oid,
                "step": step,
                "status": {"$in": ["draft", "approved", "scheduled"]},
                "quarantined": {"$ne": True},
                "quarantine.active": {"$ne": True},
            },
            {"$set": {"status": new_status, "delayDays": delay_days, "updatedAt": now}},
            return_document=True,
        )
        if not msg:
            # Nothing to activate for this step (missing, already sent, or
            # quarantined — a quarantined message is skipped with its status
            # and quarantine metadata left completely untouched).
            quarantined = await db.outreachmessages.find_one(
                {
                    "companyId": comp_oid,
                    "step": step,
                    "$or": [{"quarantined": True}, {"quarantine.active": True}],
                }
            )
            if quarantined:
                logger.warning(
                    f"[Scheduler] Step {step} for company {company_id} remains "
                    f"QUARANTINED (message {quarantined['_id']}); not armed."
                )
            continue

        recipient_email = msg.get("recipientEmail")
        # If follow-up has blank/placeholder recipient, attempt sync from Step 1
        if delay_days > 0 and (not recipient_email or not validate_recipient_email(recipient_email)):
            step1_msg = await _find_step_message(db, comp_oid, 1)
            if step1_msg and validate_recipient_email(step1_msg.get("recipientEmail")):
                step1_recip = step1_msg["recipientEmail"]
                await db.outreachmessages.update_one(
                    {"_id": msg["_id"]},
                    {"$set": {"recipientEmail": step1_recip, "updatedAt": now}},
                )
                msg["recipientEmail"] = step1_recip
                recipient_email = step1_recip

        # Validate recipient email for automatic scheduling (delay_days > 0).
        # Automatic follow-ups can NEVER be scheduled with invalid or placeholder recipients.
        if delay_days > 0 and (not recipient_email or not validate_recipient_email(recipient_email) or recipient_email in ("Not publicly available", "Not publicly verified")):
            logger.warning(
                f"[Scheduler] Step {step} for company {company_id} has invalid recipient '{recipient_email}'; "
                f"reverting to draft and refusing to schedule."
            )
            await db.outreachmessages.update_one(
                {"_id": msg["_id"]},
                {"$set": {"status": "draft", "updatedAt": now}, "$unset": {"scheduledAt": ""}},
            )
            msg["status"] = "draft"
            msg.pop("scheduledAt", None)
            continue

        if delay_days > 0:
            base_time = await _step_base_time(db, comp_oid, step, recipient_email, now)
            scheduled_time = base_time + timedelta(days=delay_days)
            await db.outreachmessages.update_one(
                {"_id": msg["_id"]},
                {"$set": {"scheduledAt": scheduled_time, "updatedAt": now}},
            )
            msg["scheduledAt"] = scheduled_time
            await _sync_record_schedule(db, comp_oid, recipient_email, step, scheduled_time, now)
        else:
            # Manual step: make sure no stale schedule can auto-fire it.
            await db.outreachmessages.update_one(
                {"_id": msg["_id"]},
                {"$unset": {"scheduledAt": ""}, "$set": {"updatedAt": now}},
            )
            msg.pop("scheduledAt", None)

        updated_messages.append(serialize_doc(msg))

    return updated_messages


def _company_evidence_gate(company: dict) -> tuple:
    """E2: Identical evidence gate to manual outreach generation.

    Returns (ok, blocked_reason).
    """
    if not company:
        return False, "Missing company Evidence or Recommended Service"
    company_evidence = (company.get('evidence') or '').strip()
    company_rec_service = (company.get('recommendedService') or '').strip()
    if not company_evidence:
        return False, "Missing company Evidence or Recommended Service"
    if not company_rec_service:
        return False, "Missing company Evidence or Recommended Service"
    return True, ""


async def _prior_step_sent(db, msg) -> bool:
    """A follow-up may only go out once its previous step has actually been sent."""
    step = int(msg.get("step", 1) or 1)
    if step <= 1:
        return True
    prior = await _find_step_message(db, msg.get("companyId"), step - 1, msg.get("recipientEmail"))
    return bool(prior and prior.get("status") == "sent")


async def _release_or_fail(claimed_msg, err, now, deferrable: bool):
    """Recover a claimed message so it is never stuck in `sending`.

    Deferrable errors (rate limits) return the message to `scheduled` so it can
    be retried once quota resets. Permanent errors mark it `failed`.
    """
    db = get_database()
    if deferrable:
        await db.outreachmessages.update_one(
            {"_id": claimed_msg["_id"], "status": "sending"},
            {"$set": {"status": "scheduled", "lastError": str(err), "updatedAt": now}},
        )
    else:
        # send_outreach_email already marks SMTP failures as failed; this only
        # applies to guard failures raised before its own try/except.
        await db.outreachmessages.update_one(
            {"_id": claimed_msg["_id"], "status": "sending"},
            {"$set": {"status": "failed", "error": str(err), "updatedAt": now}},
        )


async def _dispatch_scheduled_message(msg: dict, now, send_options: dict = None):
    """Atomically claim then dispatch one `scheduled` message.

    Returns one of: sent | failed | deferred | not_ready | skipped | quarantined.
    """
    db = get_database()
    message_id = msg.get("_id")

    # Q2: quarantine hard-stop at the dispatch boundary — never claim, never
    # mutate, never send any quarantined message, even if bad data
    # ever put one in `scheduled`. Defence in depth on top of the selection
    # filters; the message's status and quarantine metadata stay untouched.
    if is_message_quarantined(msg):
        logger.warning(
            f"[Scheduler] Message {message_id} is quarantined; refusing to dispatch."
        )
        return "quarantined"

    # E3.5: outside the configured sending window -> defer without sending.
    if not is_within_sending_window(now):
        logger.info(f"[Scheduler] Outside sending window; deferring message {message_id}.")
        return "deferred"

    # Never send a follow-up before the previous step has actually gone out.
    if not await _prior_step_sent(db, msg):
        logger.info(f"[Scheduler] Previous step not sent; deferring follow-up {message_id}.")
        return "not_ready"

    # Strict recipient validation: never dispatch a message with missing or invalid email
    recipient_email = msg.get("recipientEmail")
    if not validate_recipient_email(recipient_email):
        logger.error(f"[Scheduler] Message {message_id} has invalid recipient '{recipient_email}'; marking failed.")
        await db.outreachmessages.update_one(
            {"_id": message_id},
            {"$set": {"status": "failed", "error": f"Invalid recipient email: {recipient_email}", "updatedAt": now}},
        )
        return "failed"

    # Atomic claim: only one worker (message worker or record reconciler) can
    # transition scheduled -> sending for a given message. Q2: the claim itself
    # also refuses quarantined messages, so no worker can ever take ownership
    # of one.
    claimed = await db.outreachmessages.find_one_and_update(
        {
            "_id": message_id,
            "status": "scheduled",
            "quarantined": {"$ne": True},
            "quarantine.active": {"$ne": True},
        },
        {"$set": {"status": "sending", "updatedAt": now}},
        return_document=True,
    )
    if not claimed:
        return "skipped"

    try:
        await send_outreach_email(str(message_id), send_options)
        logger.info(f"[Scheduler] Successfully dispatched message ID: {message_id}")
        return "sent"
    except HTTPException as http_err:
        deferrable = http_err.status_code == 429
        logger.error(f"[Scheduler] Message {message_id} blocked ({http_err.status_code}): {http_err.detail}")
        await _release_or_fail(claimed, http_err, now, deferrable)
        return "deferred" if deferrable else "failed"
    except Exception as err:
        logger.error(f"[Scheduler] Failed to dispatch message ID {message_id}: {err}")
        await _release_or_fail(claimed, err, now, deferrable=False)
        return "failed"


async def process_automated_follow_ups():
    """Reconcile record-level follow-ups against the authoritative messages.

    This worker NEVER generates or fabricates a message and NEVER dispatches a
    draft/unapproved/inactive message. It only:
      * marks a due follow-up BLOCKED when the evidence gate fails, and
      * dispatches the matching `scheduled` message when one is due (using the
        same atomic claim as the scheduled-message worker, so the two paths can
        never dispatch the same message twice).
    """
    db = get_database()
    now = datetime.now(timezone.utc)

    follow_up_steps = [
        # (step number, query key 'followUp1'/'followUp2', priorStatusKey)
        (2, "followUp1", "initialEmail"),
        (3, "followUp2", "followUp1"),
    ]

    for step, follow_key, prior_key in follow_up_steps:
        cursor = db.outreachrecords.find(
            {
                f"{prior_key}.status": "SENT",
                f"{follow_key}.status": "PENDING",
                f"{follow_key}.scheduledAt": {"$lte": now},
                "replyStatus": "NO_REPLY",
            }
        ).limit(10)

        due_records = await cursor.to_list(length=10)

        for record in due_records:
            current = await db.outreachrecords.find_one({"_id": record["_id"]})
            if (
                not current
                or current.get("replyStatus") == "REPLIED"
                or current.get(follow_key, {}).get("status") == "SENT"
            ):
                continue

            company = await db.companies.find_one({"_id": record["companyId"]}) or {}
            ok, blocked_reason = _company_evidence_gate(company)
            if not ok:
                # E2: never fabricate a generic fallback. Mark BLOCKED so the
                # operator can see exactly why automation halted. The armed
                # message is intentionally left scheduled so restoring evidence
                # lets it resume.
                await db.outreachrecords.update_one(
                    {"_id": record["_id"]},
                    {"$set": {
                        f"{follow_key}.status": "BLOCKED",
                        f"{follow_key}.blockedReason": blocked_reason,
                        "updatedAt": now,
                    }},
                )
                logger.warning(
                    f"[Scheduler] Follow-up {step - 1} blocked for {record.get('recipientEmail')}: {blocked_reason}"
                )
                continue

            # The message is authoritative: only an explicitly `scheduled`
            # message may auto-dispatch. Draft/approved/inactive sequences and
            # missing messages are simply skipped (never generated here). Q3:
            # quarantined messages are excluded from dispatch selection.
            msg = await _find_step_message(
                db, record["companyId"], step, record.get("recipientEmail"),
                status="scheduled", exclude_quarantined=True,
            )
            if not msg:
                # The message is authoritative: only an explicitly
                # `scheduled` message may auto-dispatch. A `draft`
                # message means the sequence is inactive (never armed,
                # or demoted back to draft). We NEVER activate a draft
                # here — arming is the operator's explicit scheduling
                # action (POST /outreach/schedule) or the Step-1-send
                # activation in record_email_dispatch. Instead we
                # reconcile the stale tracking record so it agrees with
                # the inactive message and is not re-selected: clear the
                # stale scheduledAt. Quarantined drafts are left
                # completely untouched (quarantine is a hard stop that
                # requires human action).
                draft = await _find_step_message(
                    db, record["companyId"], step, record.get("recipientEmail"),
                    status="draft", exclude_quarantined=True,
                )
                if draft:
                    await db.outreachrecords.update_one(
                        {"_id": record["_id"]},
                        {"$unset": {f"{follow_key}.scheduledAt": ""},
                         "$set": {"updatedAt": now}},
                    )
                    logger.info(
                        f"[Scheduler] Step {step} message is draft (inactive) "
                        f"for {record.get('recipientEmail')}; reconciled record "
                        f"to PENDING with no scheduledAt. Follow-up stays inactive."
                    )
                else:
                    logger.info(
                        f"[Scheduler] No armed (scheduled) Step {step} message for "
                        f"{record.get('recipientEmail')}; leaving follow-up pending."
                    )
                continue
            if msg.get("scheduledAt") and _as_utc(msg["scheduledAt"]) > now:
                continue

            logger.info(
                f"[Scheduler] Dispatching Follow-up {step - 1} for {record.get('companyName')} to {record.get('recipientEmail')}"
            )
            dispatch_status = await _dispatch_scheduled_message(
                msg,
                now,
                {
                    "recipientEmail": record.get("recipientEmail"),
                    "ccRecipients": record.get("cc", []),
                    "bccRecipients": record.get("bcc", []),
                },
            )
            if dispatch_status == "failed":
                await db.outreachrecords.update_one(
                    {"_id": record["_id"]},
                    {"$set": {
                        f"{follow_key}.status": "FAILED",
                        f"{follow_key}.error": "Scheduler dispatch failed",
                        "updatedAt": now,
                    }},
                )


async def process_scheduled_emails():
    """Background worker checking for due scheduled emails and automated follow-ups."""
    global _is_processing
    if _is_processing:
        return
    _is_processing = True

    try:
        db = get_database()
        now = datetime.now(timezone.utc)

        # 1. Dispatch due `scheduled` messages (drafts/approved are never
        #    selected because the query filters on status == "scheduled").
        #    Q3: explicitly quarantined messages are never selected either.
        cursor = db.outreachmessages.find(
            {
                "status": "scheduled",
                "scheduledAt": {"$lte": now},
                "quarantined": {"$ne": True},
                "quarantine.active": {"$ne": True},
            }
        ).limit(10)

        due_messages = await cursor.to_list(length=10)

        for msg in due_messages:
            if is_message_quarantined(msg):
                logger.warning(f"[Scheduler] Skipping quarantined message {msg.get('_id')}")
                continue
            tracking_record = await db.outreachrecords.find_one(
                {
                    "companyId": msg["companyId"],
                    "recipientEmail": msg.get("recipientEmail"),
                }
            )

            if tracking_record and tracking_record.get("replyStatus") == "REPLIED":
                logger.info(f"[Scheduler] Skipping message {msg['_id']} because contact already replied.")
                await cancel_pending_followups(
                    msg.get("companyId"), msg.get("recipientEmail"), reason="prospect_replied"
                )
                continue

            # Evidence gate applies to automatic dispatch too.
            company = await db.companies.find_one({"_id": msg.get("companyId")}) or {}
            ok, blocked_reason = _company_evidence_gate(company)
            if not ok:
                logger.warning(
                    f"[Scheduler] Skipping scheduled message {msg['_id']}: {blocked_reason}"
                )
                continue

            logger.info(
                f"[Scheduler] Auto-dispatching scheduled Step {msg.get('step')} to {msg.get('recipientEmail', 'prospect')}..."
            )
            dispatch_status = await _dispatch_scheduled_message(msg, now)
            if dispatch_status == "failed":
                logger.error(f"[Scheduler] Failed to dispatch scheduled message ID {msg['_id']}")
                if tracking_record:
                    step = int(msg.get("step") or 1)
                    key = {2: "followUp1", 3: "followUp2"}.get(step)
                    if key:
                        await db.outreachrecords.update_one(
                            {"_id": tracking_record["_id"]},
                            {"$set": {
                                f"{key}.status": "FAILED",
                                f"{key}.error": "Scheduler dispatch failed",
                                "updatedAt": now,
                            }},
                        )

        # 2. Reconcile record-level follow-ups (evidence gate + safe dispatch).
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
