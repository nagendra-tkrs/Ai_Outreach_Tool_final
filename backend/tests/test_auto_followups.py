"""
Automatic follow-up activation & reconciliation regression suite.

Covers the drip workflow end to end (all against an isolated test database,
SMTP stubbed, sandbox send path):

  1. A successful Step 1 send ACTIVATES eligible draft Step 2/3 follow-ups
     (draft -> scheduled) using the 3-day / 7-day policy — no pre-scheduling
     required.
  2. An explicit per-message delayDays overrides the policy default.
  3. The reconciler heals the "record PENDING+due but message draft" mismatch
     by re-activating the draft (prior step must actually be sent).
  4. The scheduler dispatches the LATEST saved content (edit after arming).
  5. Duplicate dispatch is prevented (atomic claim, exactly-once).
  6. A reply cancels pending follow-ups; a failed send marks the record FAILED.
  7. Editing a follow-up never sends or activates it by itself.

Isolation: dedicated MongoDB database (`ai_client_outreach_test_autofollow`)
dropped between runs — never touches the live `ai_client_outreach` database.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

import app.config.database as db_module
import app.services.scheduler_service as sched_mod
from app.services.email_service import send_outreach_email
from app.services.outreach_tracking_service import cancel_pending_followups
from app.services.outreach_service import update_outreach_message
from app.services.scheduler_service import (
    process_automated_follow_ups,
    process_scheduled_emails,
)
from app.utils.bson_utils import to_object_id

TEST_DB_NAME = "ai_client_outreach_test_autofollow"


@pytest.fixture(scope="module", autouse=True)
async def isolated_test_db():
    client = AsyncIOMotorClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000)
    test_db = client[TEST_DB_NAME]
    await client.drop_database(TEST_DB_NAME)
    prev_db, prev_client = db_module.db, db_module.client
    db_module.db = test_db
    db_module.client = client
    try:
        yield test_db
    finally:
        db_module.db = prev_db
        db_module.client = prev_client
        await client.drop_database(TEST_DB_NAME)
        client.close()


@pytest.fixture(scope="module", autouse=True)
def block_real_smtp():
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as smtp_mock:
        yield smtp_mock


async def make_sequence(db, *, evidence="Evidence for auto-followup test",
                        service="AI Strategy Consulting"):
    now = datetime.now(timezone.utc)
    comp_res = await db.companies.insert_one({
        "companyName": "Auto Followup Test Co",
        "website": "https://autofollow.example",
        "normalizedWebsite": "autofollow.example",
        "evidence": evidence,
        "recommendedService": service,
        "createdAt": now,
        "updatedAt": now,
    })
    cid = comp_res.inserted_id
    recipient = "prospect@autofollow.example"
    msg_ids = {}
    for step in (1, 2, 3):
        res = await db.outreachmessages.insert_one({
            "companyId": cid,
            "step": step,
            "status": "draft",
            "subject": f"Step {step} - Auto Followup",
            "bodyHtml": "<p>Hello</p>",
            "bodyText": "Hello",
            "recipientEmail": recipient,
            "recipientName": "Prospect",
            "createdAt": now,
            "updatedAt": now,
        })
        msg_ids[step] = res.inserted_id
    return cid, recipient, msg_ids


async def insert_record(db, cid, recipient, *, f1_status="PENDING", f1_at=None,
                       f2_status="PENDING", f2_at=None, reply_status="NO_REPLY"):
    now = datetime.now(timezone.utc)
    return await db.outreachrecords.insert_one({
        "companyId": cid,
        "companyName": "Auto Followup Test Co",
        "recipientEmail": recipient,
        "initialEmail": {"status": "SENT", "sentAt": now - timedelta(days=1)},
        "followUp1": {"status": f1_status, "scheduledAt": f1_at},
        "followUp2": {"status": f2_status, "scheduledAt": f2_at},
        "replyStatus": reply_status,
        "campaignStatus": "INITIAL_SENT",
        "isTestSend": False,
        "createdAt": now,
        "updatedAt": now,
    })


def close_to(actual, expected, tolerance_seconds=120):
    if actual is None:
        return False
    # DB datetimes are naive UTC; expected may be aware — normalise both.
    if actual.tzinfo is not None:
        actual = actual.replace(tzinfo=None)
    if expected.tzinfo is not None:
        expected = expected.replace(tzinfo=None)
    return abs((actual - expected).total_seconds()) <= tolerance_seconds


# ---------------------------------------------------------------------------
# 1. Step 1 send activates draft follow-ups (no pre-scheduling required).
# ---------------------------------------------------------------------------
async def test_step1_send_activates_draft_followups(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    cid, recipient, msg_ids = await make_sequence(db)

    # Fresh drafts, sequence NEVER explicitly scheduled. Step 1 goes out.
    await send_outreach_email(str(msg_ids[1]))

    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert m2["status"] == "scheduled", "Step 2 draft must be armed by the Step 1 send"
    assert m3["status"] == "scheduled", "Step 3 draft must be armed by the Step 1 send"
    # 3-day / 7-day policy defaults.
    assert close_to(m2["scheduledAt"], now + timedelta(days=3))
    assert close_to(m3["scheduledAt"], now + timedelta(days=7))
    assert m2["delayDays"] == 3
    assert m3["delayDays"] == 7

    rec = await db.outreachrecords.find_one({"companyId": cid, "recipientEmail": recipient})
    assert rec["initialEmail"]["status"] == "SENT"
    assert rec["followUp1"]["status"] == "PENDING"
    assert close_to(rec["followUp1"]["scheduledAt"], now + timedelta(days=3))
    assert rec["followUp2"]["status"] == "PENDING"
    assert close_to(rec["followUp2"]["scheduledAt"], now + timedelta(days=7))
    block_real_smtp.assert_not_called()


# ---------------------------------------------------------------------------
# 2. An explicit per-message delayDays overrides the policy default.
# ---------------------------------------------------------------------------
async def test_custom_delay_days_override_policy(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    cid, recipient, msg_ids = await make_sequence(db)
    await db.outreachmessages.update_one({"_id": msg_ids[2]}, {"$set": {"delayDays": 10}})
    await db.outreachmessages.update_one({"_id": msg_ids[3]}, {"$set": {"delayDays": 14}})

    await send_outreach_email(str(msg_ids[1]))

    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert close_to(m2["scheduledAt"], now + timedelta(days=10))
    assert close_to(m3["scheduledAt"], now + timedelta(days=14))


# ---------------------------------------------------------------------------
# 4. Reconciler reconciles "record PENDING+due but message draft".
#
#    A draft follow-up is INACTIVE. The reconciler must NEVER activate a
#    draft merely because its due date passed. Instead it reconciles the
#    stale tracking record to agree with the authoritative (draft) message
#    by clearing the stale scheduledAt — so the record and message can no
#    longer silently disagree, and the follow-up stays inactive.
# ---------------------------------------------------------------------------
async def test_reconciler_reconciles_pending_record_with_draft_message(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    cid, recipient, msg_ids = await make_sequence(db)
    # Step 1 sent; record says followUp1 PENDING+due, but the Step 2
    # message is still draft (the audit's silent-disagreement case).
    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]}, {"$set": {"status": "sent", "sentAt": now - timedelta(days=1)}}
    )
    rec_res = await insert_record(db, cid, recipient, f1_at=past)

    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_automated_follow_ups()

    # A draft follow-up is inactive — never dispatched just because it is due.
    send_mock.assert_not_awaited()
    # The message stays draft (never activated by reconciliation).
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "draft"
    # The record is reconciled: followUp1 stays PENDING but the stale
    # scheduledAt is cleared so record and message agree.
    rec = await db.outreachrecords.find_one({"_id": rec_res.inserted_id})
    assert rec["followUp1"]["status"] == "PENDING"
    assert "scheduledAt" not in rec["followUp1"]


# ---------------------------------------------------------------------------
# 6. Scheduler dispatches the LATEST saved content (edit after arming).
# ---------------------------------------------------------------------------
async def test_latest_edited_content_dispatched(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    cid, recipient, msg_ids = await make_sequence(db)
    await send_outreach_email(str(msg_ids[1]))  # arms Step 2 (+3d) / Step 3 (+7d)

    # Edit the armed Step 2 copy AFTER it was scheduled.
    await update_outreach_message(
        str(msg_ids[2]),
        {"subject": "LATEST SUBJECT", "bodyHtml": "<p>LATEST BODY</p>", "bodyText": "LATEST BODY"},
    )
    # Editing must not change status or send anything by itself.
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "scheduled"
    assert m2["subject"] == "LATEST SUBJECT"

    # Make the armed Step 2 due now.
    await db.outreachmessages.update_one({"_id": msg_ids[2]}, {"$set": {"scheduledAt": past}})

    captured = {}
    real_send = sched_mod.send_outreach_email

    async def capture_send(message_id, send_options=None):
        m = await db.outreachmessages.find_one({"_id": to_object_id(message_id)})
        captured["subject"] = m["subject"]
        captured["bodyText"] = m["bodyText"]
        return await real_send(message_id, send_options)

    with patch.object(sched_mod, "send_outreach_email", new=capture_send):
        await process_scheduled_emails()

    assert captured["subject"] == "LATEST SUBJECT"
    assert captured["bodyText"] == "LATEST BODY"


# ---------------------------------------------------------------------------
# 7. Duplicate dispatch is prevented (atomic claim, exactly-once).
# ---------------------------------------------------------------------------
async def test_duplicate_dispatch_prevented(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    cid, recipient, msg_ids = await make_sequence(db)
    await send_outreach_email(str(msg_ids[1]))  # arms Step 2 (+3d) / Step 3 (+7d)
    await db.outreachmessages.update_one({"_id": msg_ids[2]}, {"$set": {"scheduledAt": past}})

    real_send = sched_mod.send_outreach_email
    calls = {"n": 0}

    async def counting_send(message_id, send_options=None):
        calls["n"] += 1
        return await real_send(message_id, send_options)

    with patch.object(sched_mod, "send_outreach_email", new=counting_send):
        await process_scheduled_emails()
        await process_scheduled_emails()  # second pass must be a no-op

    assert calls["n"] == 1
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "sent"


# ---------------------------------------------------------------------------
# 8. A reply cancels pending follow-ups; reconciler skips replied records.
# ---------------------------------------------------------------------------
async def test_reply_cancels_pending_followups(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    cid, recipient, msg_ids = await make_sequence(db)
    # Step 1 sent; Step 2 armed and due; record says the prospect REPLIED.
    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]}, {"$set": {"status": "sent", "sentAt": now - timedelta(days=1)}}
    )
    await db.outreachmessages.update_one({"_id": msg_ids[2]}, {"$set": {"status": "scheduled", "scheduledAt": past}})
    rec_res = await insert_record(db, cid, recipient, f1_at=past, reply_status="REPLIED")

    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_automated_follow_ups()

    send_mock.assert_not_awaited(), "replied record must never auto-dispatch"

    # Explicit reply cancellation demotes armed follow-ups to draft.
    modified = await cancel_pending_followups(cid, recipient, reason="prospect_replied")
    assert modified >= 1
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "draft"
    assert m2["cancelledReason"] == "prospect_replied"
    rec = await db.outreachrecords.find_one({"_id": rec_res.inserted_id})
    assert rec["followUp1"]["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# 9. A failed send marks the message and record FAILED (never retried blind).
# ---------------------------------------------------------------------------
async def test_failed_send_marks_message_and_record_failed(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    cid, recipient, msg_ids = await make_sequence(db)
    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]}, {"$set": {"status": "sent", "sentAt": now - timedelta(days=1)}}
    )
    await db.outreachmessages.update_one({"_id": msg_ids[2]}, {"$set": {"status": "scheduled", "scheduledAt": past}})
    rec_res = await insert_record(db, cid, recipient, f1_at=past)

    async def failing_send(message_id, send_options=None):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="boom")

    with patch.object(sched_mod, "send_outreach_email", new=failing_send):
        await process_scheduled_emails()

    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "failed"
    rec = await db.outreachrecords.find_one({"_id": rec_res.inserted_id})
    assert rec["followUp1"]["status"] == "FAILED"


# ---------------------------------------------------------------------------
# 10. Correct scheduled timestamps for Steps 2 and 3 (3-day / 7-day policy).
# ---------------------------------------------------------------------------
async def test_scheduled_timestamps_follow_policy(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    cid, recipient, msg_ids = await make_sequence(db)
    await send_outreach_email(str(msg_ids[1]))

    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert close_to(m2["scheduledAt"], now + timedelta(days=3))
    assert close_to(m3["scheduledAt"], now + timedelta(days=7))
    # Step 3 must be strictly after Step 2.
    assert m3["scheduledAt"] > m2["scheduledAt"]
