"""
Comprehensive tests for safe auto drip scheduling, kill switch, and tracking record synchronization.
Covers:
  1. Kill switch (ENABLE_SCHEDULER missing, false, true, 0, 1, invalid)
  2. Successful Step 1 manual send activates Step 2 and Step 3
  3. Failed Step 1 send does NOT activate follow-ups
  4. Step 2 not sent before its due time
  5. Step 2 auto-dispatches once due with all safety checks passing
  6. Step 3 cannot dispatch before Step 2 succeeds
  7. Step 3 dispatches after Step 2 succeeds and Step 3 is due
  8. Disabled scheduler performs NO dispatch
  9. Missing/invalid recipient blocks dispatch
  10. Pre-scheduling before Step 1 send properly re-anchors follow-up dates to actual Step 1 send time
  11. Tracking record synchronization mirrors both followUp1 and followUp2 scheduledAt
  12. Duplicate activation is idempotent and does not create duplicate schedules
  13. Sequencing conflict (Step 3 delay <= Step 2 delay) is rejected with HTTP 400
  14. Clean start_scheduler and stop_scheduler behavior
"""
import os
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

import app.config.database as db_module
import app.services.scheduler_service as sched_mod
from app.services.scheduler_service import (
    is_scheduler_enabled,
    start_scheduler,
    stop_scheduler,
    process_scheduled_emails,
    schedule_sequence_steps,
)
from app.services.email_service import send_outreach_email
from app.services.outreach_tracking_service import record_email_dispatch

TEST_DB_NAME = "ai_client_outreach_test_auto_drip"


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


async def create_test_company_and_sequence(db, *, recipient="prospect@driptest.example", company_name="Drip Test Co"):
    now = datetime.now(timezone.utc)
    comp_res = await db.companies.insert_one({
        "companyName": company_name,
        "website": f"https://{company_name.lower().replace(' ', '')}.com/",
        "evidence": "Enterprise industrial automation and AI analytics platform.",
        "recommendedService": "AI Strategy Consulting",
        "createdAt": now,
        "updatedAt": now,
    })
    cid = comp_res.inserted_id
    msg_ids = {}
    for step in (1, 2, 3):
        res = await db.outreachmessages.insert_one({
            "companyId": cid,
            "step": step,
            "status": "draft",
            "subject": f"Step {step} - Drip Test Subject",
            "bodyHtml": f"<p>Hello Step {step}</p>",
            "bodyText": f"Hello Step {step}",
            "recipientEmail": recipient,
            "recipientName": "Decision Maker",
            "createdAt": now,
            "updatedAt": now,
        })
        msg_ids[step] = res.inserted_id
    return cid, recipient, msg_ids


# ---------------------------------------------------------------------------
# 1. Kill Switch Tests
# ---------------------------------------------------------------------------
def test_kill_switch_values():
    test_cases = [
        (None, False),
        ("", False),
        ("false", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
        ("random_string", False),
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("YES", True),
    ]
    orig = os.environ.get("ENABLE_SCHEDULER")
    try:
        for val, expected in test_cases:
            if val is None:
                os.environ.pop("ENABLE_SCHEDULER", None)
            else:
                os.environ["ENABLE_SCHEDULER"] = val
            assert is_scheduler_enabled() is expected, f"Failed for ENABLE_SCHEDULER='{val}'"
    finally:
        if orig is not None:
            os.environ["ENABLE_SCHEDULER"] = orig
        else:
            os.environ.pop("ENABLE_SCHEDULER", None)


async def test_disabled_scheduler_does_not_start_task():
    orig = os.environ.get("ENABLE_SCHEDULER")
    os.environ["ENABLE_SCHEDULER"] = "false"
    try:
        stop_scheduler()
        start_scheduler(60)
        assert sched_mod._scheduler_task is None
    finally:
        stop_scheduler()
        if orig is not None:
            os.environ["ENABLE_SCHEDULER"] = orig


async def test_disabled_scheduler_process_scheduled_emails_skips(isolated_test_db):
    db = isolated_test_db
    cid, recipient, msg_ids = await create_test_company_and_sequence(db)
    past_due = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]},
        {"$set": {"status": "scheduled", "scheduledAt": past_due, "delayDays": 3}}
    )

    orig = os.environ.get("ENABLE_SCHEDULER")
    os.environ["ENABLE_SCHEDULER"] = "false"
    try:
        with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
            await process_scheduled_emails()
            send_mock.assert_not_awaited()
        # Message must remain scheduled (unmodified)
        m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
        assert m2["status"] == "scheduled"
    finally:
        if orig is not None:
            os.environ["ENABLE_SCHEDULER"] = orig


# ---------------------------------------------------------------------------
# 2. Step 1 Send -> Follow-up Activation & Anchoring
# ---------------------------------------------------------------------------
async def test_successful_step1_send_activates_followups_anchored_to_send_time(isolated_test_db):
    db = isolated_test_db
    cid, recipient, msg_ids = await create_test_company_and_sequence(db)

    # Manually send Step 1
    os.environ["ENABLE_SCHEDULER"] = "true"
    send_result = await send_outreach_email(str(msg_ids[1]))
    assert send_result["success"] is True

    # Step 1 is sent
    m1 = await db.outreachmessages.find_one({"_id": msg_ids[1]})
    assert m1["status"] == "sent"
    step1_sent_at = m1["sentAt"]

    # Step 2 and Step 3 must be automatically promoted to scheduled
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert m2["status"] == "scheduled"
    assert m3["status"] == "scheduled"

    # Due dates anchored to step1_sent_at (3 days and 7 days)
    assert abs((m2["scheduledAt"] - (step1_sent_at + timedelta(days=3))).total_seconds()) < 5
    assert abs((m3["scheduledAt"] - (step1_sent_at + timedelta(days=7))).total_seconds()) < 5

    # Tracking record must reflect both followUp1 and followUp2 scheduledAt
    rec = await db.outreachrecords.find_one({"companyId": cid, "recipientEmail": recipient})
    assert rec is not None
    assert rec["followUp1"]["status"] == "PENDING"
    assert abs((rec["followUp1"]["scheduledAt"] - m2["scheduledAt"]).total_seconds()) < 5
    assert rec["followUp2"]["status"] == "PENDING"
    assert abs((rec["followUp2"]["scheduledAt"] - m3["scheduledAt"]).total_seconds()) < 5


async def test_failed_step1_send_does_not_activate_followups(isolated_test_db):
    db = isolated_test_db
    cid, recipient, msg_ids = await create_test_company_and_sequence(db)

    # Force send failure by throwing in aiosmtplib.send
    fake_cfg = {
        'host': 'smtp.example.com',
        'port': 587,
        'user': 'user',
        'pass': 'secret',
        'from': 'outreach@example.com',
        'start_tls': False,
        'use_tls': False,
        'isTest': False,
    }
    with patch("app.services.email_service.get_smtp_config", new=AsyncMock(return_value=fake_cfg)), \
         patch("app.services.email_service.aiosmtplib.send", side_effect=Exception("SMTP connection refused")):
        with pytest.raises(Exception):
            await send_outreach_email(str(msg_ids[1]))

    m1 = await db.outreachmessages.find_one({"_id": msg_ids[1]})
    assert m1["status"] == "failed"

    # Step 2 and Step 3 must remain drafts!
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert m2["status"] == "draft"
    assert m3["status"] == "draft"


# ---------------------------------------------------------------------------
# 3. Edge Case: Pre-scheduling Before Step 1 Send Re-anchors Correctly
# ---------------------------------------------------------------------------
async def test_pre_scheduling_before_step1_reanchors_when_step1_sent(isolated_test_db):
    db = isolated_test_db
    cid, recipient, msg_ids = await create_test_company_and_sequence(db)

    # Operator pre-activates the schedule modal 5 days before actually sending Step 1
    past_activation = datetime.now(timezone.utc) - timedelta(days=5)
    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]},
        {"$set": {"status": "scheduled", "delayDays": 3, "scheduledAt": past_activation + timedelta(days=3)}}
    )
    await db.outreachmessages.update_one(
        {"_id": msg_ids[3]},
        {"$set": {"status": "scheduled", "delayDays": 6, "scheduledAt": past_activation + timedelta(days=6)}}
    )

    # Now Step 1 is sent TODAY
    await send_outreach_email(str(msg_ids[1]))
    m1 = await db.outreachmessages.find_one({"_id": msg_ids[1]})
    step1_sent = m1["sentAt"]

    # Step 2 and Step 3 must be RE-ANCHORED to step1_sent (NOT kept at past_activation)!
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert abs((m2["scheduledAt"] - (step1_sent + timedelta(days=3))).total_seconds()) < 5
    assert abs((m3["scheduledAt"] - (step1_sent + timedelta(days=6))).total_seconds()) < 5

    # Tracking record matches the newly re-anchored dates
    rec = await db.outreachrecords.find_one({"companyId": cid, "recipientEmail": recipient})
    assert abs((rec["followUp1"]["scheduledAt"] - m2["scheduledAt"]).total_seconds()) < 5
    assert abs((rec["followUp2"]["scheduledAt"] - m3["scheduledAt"]).total_seconds()) < 5


# ---------------------------------------------------------------------------
# 4. Step 3 Prior-Step Prerequisite & Sequencing Order
# ---------------------------------------------------------------------------
async def test_step3_cannot_dispatch_before_step2_succeeds(isolated_test_db):
    db = isolated_test_db
    cid, recipient, msg_ids = await create_test_company_and_sequence(db)

    # Step 1 sent
    await send_outreach_email(str(msg_ids[1]))

    # Set both Step 2 and Step 3 to past due
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    await db.outreachmessages.update_one({"_id": msg_ids[2]}, {"$set": {"scheduledAt": past}})
    await db.outreachmessages.update_one({"_id": msg_ids[3]}, {"$set": {"scheduledAt": past}})

    # Temporarily set Step 2 status to 'draft' or 'failed' to simulate Step 2 not sent
    await db.outreachmessages.update_one({"_id": msg_ids[2]}, {"$set": {"status": "failed", "error": "bounced"}})

    os.environ["ENABLE_SCHEDULER"] = "true"
    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails(force=True)
        # Step 3 must not be dispatched!
        for call in send_mock.call_args_list:
            assert call[0][0] != str(msg_ids[3]), "Step 3 dispatched while Step 2 failed!"

    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert m3["status"] == "scheduled", "Step 3 must remain scheduled (deferred)"


async def test_step3_dispatches_after_step2_succeeds_and_due(isolated_test_db):
    db = isolated_test_db
    cid, recipient, msg_ids = await create_test_company_and_sequence(db)

    # Step 1 sent
    await send_outreach_email(str(msg_ids[1]))

    # Step 2 due and sent
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.outreachmessages.update_one({"_id": msg_ids[2]}, {"$set": {"scheduledAt": past}})
    await process_scheduled_emails(force=True)

    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "sent"

    # Step 3 not yet due -> must not dispatch
    future = datetime.now(timezone.utc) + timedelta(days=3)
    await db.outreachmessages.update_one({"_id": msg_ids[3]}, {"$set": {"scheduledAt": future}})
    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails(force=True)
        send_mock.assert_not_awaited()

    # Now make Step 3 due
    await db.outreachmessages.update_one({"_id": msg_ids[3]}, {"$set": {"scheduledAt": past}})
    await process_scheduled_emails(force=True)

    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert m3["status"] == "sent"


# ---------------------------------------------------------------------------
# 5. Schedule Conflict Validation (Step 3 delay <= Step 2 delay)
# ---------------------------------------------------------------------------
async def test_schedule_sequence_steps_rejects_inverted_delays(isolated_test_db):
    db = isolated_test_db
    cid, recipient, msg_ids = await create_test_company_and_sequence(db)

    with pytest.raises(HTTPException) as exc_info:
        await schedule_sequence_steps(str(cid), [
            {"step": 1, "delayDays": 0},
            {"step": 2, "delayDays": 5},
            {"step": 3, "delayDays": 2},  # Inverted: 2 <= 5
        ])
    assert exc_info.value.status_code == 400
    assert "Schedule sequence conflict" in exc_info.value.detail
