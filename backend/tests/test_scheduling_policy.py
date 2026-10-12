"""
FIX 2 / FIX 6 regression suite: authoritative drip-scheduling policy.

Locks in the new policy:

  1. Sequence generation creates `draft` messages only; it NEVER activates
     automatic sending.
  2. Activation is explicit (POST /outreach/schedule): step 1 (delay 0)
     becomes `approved` (manual send), follow-ups with a positive delay become
     `scheduled` with the operator's exact `delayDays` on the message.
  3. The record's follow-up schedule is anchored to the actual Step 1 send time
     using the message's own delay — never an environment default (so a 10-day
     custom delay is never short-circuited to a 3-day env default).
  4. Drafts / unapproved / inactive sequences never auto-dispatch, even if a
     legacy record looks overdue.
  5. Both worker paths (scheduled-message worker + record reconciler) share an
     atomic claim (scheduled -> sending), so a message is never dispatched
     twice, no duplicate from the two workers.
  6. A reply cancels pending follow-ups (message -> draft + cancelledReason,
     record -> CANCELLED) and workers never dispatch cancelled follow-ups.
  7. Failed sends are handled: message -> failed, record follow-up -> FAILED.
  8. The evidence gate is preserved (BLOCKED, never a generic fallback).
  9. Sent messages can never be dispatched again (409 + atomic-claim skip).

Isolation: this module runs against a dedicated MongoDB database
(`ai_client_outreach_test_scheduling`) that is dropped between runs. It never
touches the live `ai_client_outreach` database. SMTP transport is stubbed so no
real email can ever be sent; `ALLOW_ETHEREAL_TEST=true` (conftest) also routes
the sandbox pipeline through the no-network test path.
"""
import asyncio
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

import app.config.database as db_module
import app.services.scheduler_service as sched_mod
from app.services.email_service import send_outreach_email
from app.services.outreach_tracking_service import (
    get_outreach_stats,
    update_reply_status,
)
from app.services.scheduler_service import (
    process_scheduled_emails,
    schedule_sequence_steps,
)

TEST_DB_NAME = "ai_client_outreach_test_scheduling"


@pytest.fixture(scope="module", autouse=True)
async def isolated_test_db():
    """Run this module against a dedicated test database, then restore the
    app's previous database binding and drop the test database."""
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
    """Belt-and-braces: even if SMTP config ever resolved to a real server,
    aiosmtplib.send is stubbed so no email can leave the test process."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as smtp_mock:
        yield smtp_mock


async def make_sequence(db, *, evidence="Evidence for scheduling policy test",
                        service="AI Strategy Consulting"):
    now = datetime.now(timezone.utc)
    comp_res = await db.companies.insert_one({
        "companyName": "Scheduling Policy Test Co",
        "website": "https://schedpolicy.example",
        "normalizedWebsite": "schedpolicy.example",
        "evidence": evidence,
        "recommendedService": service,
        "createdAt": now,
        "updatedAt": now,
    })
    cid = comp_res.inserted_id
    recipient = "prospect@schedpolicy.example"
    msg_ids = {}
    for step in (1, 2, 3):
        res = await db.outreachmessages.insert_one({
            "companyId": cid,
            "step": step,
            "status": "draft",
            "subject": f"Step {step} - Scheduling Policy",
            "bodyHtml": "<p>Hello</p>",
            "bodyText": "Hello",
            "recipientEmail": recipient,
            "recipientName": "Prospect",
            "createdAt": now,
            "updatedAt": now,
        })
        msg_ids[step] = res.inserted_id
    return cid, recipient, msg_ids


# ---------------------------------------------------------------------------
# Requirement 3: generation alone = drafts only; activation is explicit.
# ---------------------------------------------------------------------------
async def test_generation_creates_drafts_only_and_never_auto_dispatches(isolated_test_db):
    db = isolated_test_db
    cid, _recipient, _msg_ids = await make_sequence(db)

    msgs = await db.outreachmessages.find({"companyId": cid}).to_list(length=10)
    assert len(msgs) == 3
    for m in msgs:
        assert m["status"] == "draft"
        assert m.get("scheduledAt") is None

    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails()

    send_mock.assert_not_awaited()
    msgs = await db.outreachmessages.find({"companyId": cid}).to_list(length=10)
    assert all(m["status"] == "draft" for m in msgs)
    assert await db.outreachrecords.count_documents({}) == 0


async def test_explicit_schedule_activates_steps_and_stores_custom_delays(isolated_test_db):
    db = isolated_test_db
    cid, _recipient, msg_ids = await make_sequence(db)

    activated = await schedule_sequence_steps(str(cid), [
        {"step": 1, "delayDays": 0},
        {"step": 2, "delayDays": 10},
        {"step": 3, "delayDays": 20},
    ])
    assert len(activated) == 3

    s1 = await db.outreachmessages.find_one({"_id": msg_ids[1]})
    assert s1["status"] == "approved", "step 1 (delay 0) must be approved for manual send"
    assert s1.get("scheduledAt") is None, "manual step must never be auto-armed"

    s2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert s2["status"] == "scheduled"
    assert s2["delayDays"] == 10
    assert s2["scheduledAt"].replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)

    s3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert s3["status"] == "scheduled"
    assert s3["delayDays"] == 20

    # Step 1 has not been sent -> no tracking record yet (nothing to mirror).
    assert await db.outreachrecords.count_documents({"companyId": cid}) == 0


# ---------------------------------------------------------------------------
# Requirement 4/5: custom delays are authoritative; env defaults never apply.
# ---------------------------------------------------------------------------
async def test_custom_10_day_delay_not_overridden_by_env_3_day_default(isolated_test_db):
    db = isolated_test_db
    os.environ["FOLLOW_UP_1_DELAY_DAYS"] = "3"
    os.environ["FOLLOW_UP_2_DELAY_DAYS"] = "7"
    try:
        cid, recipient, msg_ids = await make_sequence(db)
        await schedule_sequence_steps(str(cid), [
            {"step": 1, "delayDays": 0},
            {"step": 2, "delayDays": 10},
            {"step": 3, "delayDays": 20},
        ])
        s2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
        assert s2["delayDays"] == 10

        # Actual Step 1 send (sandbox test path, SMTP stubbed).
        await send_outreach_email(str(msg_ids[1]))

        record = await db.outreachrecords.find_one({"companyId": cid, "recipientEmail": recipient})
        assert record is not None
        base = record["initialEmail"]["sentAt"]
        expected_f1 = base + timedelta(days=10)
        expected_f2 = base + timedelta(days=20)

        assert abs((record["followUp1"]["scheduledAt"] - expected_f1).total_seconds()) < 120
        assert abs((record["followUp2"]["scheduledAt"] - expected_f2).total_seconds()) < 120
        # The 3-day env default must NOT have been applied to the record...
        assert abs((record["followUp1"]["scheduledAt"] - (base + timedelta(days=3))).total_seconds()) > 120

        # ...and the message's own schedule matches the record (consistency).
        m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
        m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
        assert abs((m2["scheduledAt"] - expected_f1).total_seconds()) < 120
        assert abs((m3["scheduledAt"] - expected_f2).total_seconds()) < 120
    finally:
        os.environ.pop("FOLLOW_UP_1_DELAY_DAYS", None)
        os.environ.pop("FOLLOW_UP_2_DELAY_DAYS", None)


# ---------------------------------------------------------------------------
# Requirement 4: steps 2/3 never auto-send without activation.
# ---------------------------------------------------------------------------
async def test_inactive_sequence_never_dispatches_followups_even_when_due(isolated_test_db):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    cid, recipient, msg_ids = await make_sequence(db)

    # Step 1 went out, but the drip schedule was NEVER activated.
    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]},
        {"$set": {"status": "sent", "sentAt": now, "updatedAt": now}},
    )
    # A legacy record that would look "due" under the OLD policy.
    rec_res = await db.outreachrecords.insert_one({
        "companyId": cid,
        "companyName": "Scheduling Policy Test Co",
        "recipientEmail": recipient,
        "initialEmail": {"status": "SENT", "sentAt": now},
        "followUp1": {"status": "PENDING", "scheduledAt": now - timedelta(hours=1)},
        "followUp2": {"status": "PENDING"},
        "replyStatus": "NO_REPLY",
        "campaignStatus": "INITIAL_SENT",
        "isTestSend": False,
        "createdAt": now,
        "updatedAt": now,
    })

    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails()

    send_mock.assert_not_awaited()
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "draft", "a draft follow-up must never auto-dispatch"
    rec = await db.outreachrecords.find_one({"_id": rec_res.inserted_id})
    assert rec["followUp1"]["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Requirement 6/8/9: activated sequence dispatches once, both workers share
# the atomic claim.
# ---------------------------------------------------------------------------
async def test_activated_sequence_dispatches_exactly_once(isolated_test_db):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    cid, recipient, msg_ids = await make_sequence(db)
    await schedule_sequence_steps(str(cid), [
        {"step": 1, "delayDays": 0},
        {"step": 2, "delayDays": 10},
        {"step": 3, "delayDays": 20},
    ])

    # Manual Step 1 send through the real (sandboxed) pipeline.
    await send_outreach_email(str(msg_ids[1]))
    record = await db.outreachrecords.find_one({"companyId": cid, "recipientEmail": recipient})
    assert record["followUp1"]["status"] == "PENDING"
    assert record["followUp1"]["scheduledAt"].replace(tzinfo=timezone.utc) > now

    # Fast-forward the step-2 clocks so the worker sees the follow-up as due.
    await db.outreachmessages.update_one({"_id": msg_ids[2]}, {"$set": {"scheduledAt": past}})
    await db.outreachrecords.update_one(
        {"_id": record["_id"]}, {"$set": {"followUp1.scheduledAt": past}}
    )

    real_send = sched_mod.send_outreach_email
    calls = {"n": 0}

    async def counting_send(message_id, send_options=None):
        calls["n"] += 1
        return await real_send(message_id, send_options)

    with patch.object(sched_mod, "send_outreach_email", new=counting_send):
        await process_scheduled_emails()

    assert calls["n"] == 1, "message worker + reconciler must dispatch exactly once"
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "sent"
    rec = await db.outreachrecords.find_one({"_id": record["_id"]})
    assert rec["followUp1"]["status"] == "SENT"

    # A second pass must be a complete no-op.
    await process_scheduled_emails()
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "sent"
    rec = await db.outreachrecords.find_one({"_id": record["_id"]})
    assert rec["followUp1"]["status"] == "SENT"


async def test_atomic_claim_prevents_double_dispatch(isolated_test_db):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    cid, _recipient, msg_ids = await make_sequence(db)

    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]},
        {"$set": {"status": "sent", "sentAt": now - timedelta(days=1)}},
    )
    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]},
        {"$set": {"status": "scheduled", "delayDays": 1, "scheduledAt": past}},
    )
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})

    # Simulate the two worker paths racing on the same message.
    results = await asyncio.gather(
        sched_mod._dispatch_scheduled_message(m2, now),
        sched_mod._dispatch_scheduled_message(m2, now),
    )
    assert sorted(results) == ["sent", "skipped"]
    m2_after = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2_after["status"] == "sent"


# ---------------------------------------------------------------------------
# Requirement 8-bis: a reply halts everything, and workers never re-dispatch.
# ---------------------------------------------------------------------------
async def test_reply_stops_and_cancels_pending_followups(isolated_test_db):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=5)
    cid, _recipient, msg_ids = await make_sequence(db)
    await schedule_sequence_steps(str(cid), [
        {"step": 1, "delayDays": 0},
        {"step": 2, "delayDays": 1},
        {"step": 3, "delayDays": 2},
    ])
    await send_outreach_email(str(msg_ids[1]))
    record = await db.outreachrecords.find_one({"companyId": cid})

    # Arm both follow-ups and make them due.
    await db.outreachmessages.update_many(
        {"_id": {"$in": [msg_ids[2], msg_ids[3]]}},
        {"$set": {"scheduledAt": past}},
    )
    await db.outreachrecords.update_one(
        {"_id": record["_id"]},
        {"$set": {"followUp1.scheduledAt": past, "followUp2.scheduledAt": past}},
    )

    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        updated = await update_reply_status(str(record["_id"]), "REPLIED")
        assert updated["followUp1"]["status"] == "CANCELLED"
        assert updated["followUp2"]["status"] == "CANCELLED"

        m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
        m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
        assert m2["status"] == "draft"
        assert m2.get("cancelledReason") == "prospect_replied"
        assert m3["status"] == "draft"
        assert m3.get("cancelledReason") == "prospect_replied"

        # Workers must never dispatch cancelled follow-ups.
        await process_scheduled_emails()
        send_mock.assert_not_awaited()
        m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
        assert m2["status"] == "draft"


# ---------------------------------------------------------------------------
# Requirement 6: failed sends are handled safely on both message and record.
# ---------------------------------------------------------------------------
async def test_failed_dispatch_marks_message_and_record_failed(isolated_test_db):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    cid, recipient, msg_ids = await make_sequence(db)

    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]},
        {"$set": {"status": "sent", "sentAt": now - timedelta(days=1)}},
    )
    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]},
        {"$set": {"status": "scheduled", "delayDays": 1, "scheduledAt": past}},
    )
    rec_res = await db.outreachrecords.insert_one({
        "companyId": cid,
        "companyName": "Scheduling Policy Test Co",
        "recipientEmail": recipient,
        "initialEmail": {"status": "SENT", "sentAt": now - timedelta(days=1)},
        "followUp1": {"status": "PENDING", "scheduledAt": past},
        "followUp2": {"status": "PENDING"},
        "replyStatus": "NO_REPLY",
        "campaignStatus": "INITIAL_SENT",
        "isTestSend": False,
        "createdAt": now,
        "updatedAt": now,
    })

    with patch.object(
        sched_mod, "send_outreach_email", new=AsyncMock(side_effect=Exception("SMTP boom"))
    ):
        await process_scheduled_emails()

    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "failed"
    rec = await db.outreachrecords.find_one({"_id": rec_res.inserted_id})
    assert rec["followUp1"]["status"] == "FAILED"


# ---------------------------------------------------------------------------
# Requirement 7 (E2 preserved): evidence gate blocks auto-dispatch.
# ---------------------------------------------------------------------------
async def test_missing_evidence_blocks_auto_dispatch(isolated_test_db):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    cid, recipient, msg_ids = await make_sequence(db, evidence="", service="")

    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]},
        {"$set": {"status": "sent", "sentAt": now - timedelta(days=1)}},
    )
    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]},
        {"$set": {"status": "scheduled", "delayDays": 1, "scheduledAt": past}},
    )
    rec_res = await db.outreachrecords.insert_one({
        "companyId": cid,
        "companyName": "Scheduling Policy Test Co",
        "recipientEmail": recipient,
        "initialEmail": {"status": "SENT", "sentAt": now - timedelta(days=1)},
        "followUp1": {"status": "PENDING", "scheduledAt": past},
        "followUp2": {"status": "PENDING"},
        "replyStatus": "NO_REPLY",
        "campaignStatus": "INITIAL_SENT",
        "isTestSend": False,
        "createdAt": now,
        "updatedAt": now,
    })

    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails()

    send_mock.assert_not_awaited()
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "scheduled", "must skip, never send without evidence"
    rec = await db.outreachrecords.find_one({"_id": rec_res.inserted_id})
    assert rec["followUp1"]["status"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Requirement 9/13: sent messages are terminal — 409 + atomic-claim skip.
# ---------------------------------------------------------------------------
async def test_sent_message_cannot_be_dispatched_again(isolated_test_db):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    cid, _recipient, msg_ids = await make_sequence(db)

    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]},
        {"$set": {"status": "sent", "sentAt": now, "updatedAt": now}},
    )

    with pytest.raises(HTTPException) as exc:
        await send_outreach_email(str(msg_ids[1]))
    assert exc.value.status_code == 409  # backend duplicate protection intact

    sent = await db.outreachmessages.find_one({"_id": msg_ids[1]})
    result = await sched_mod._dispatch_scheduled_message(sent, now)
    assert result == "skipped"
    reloaded = await db.outreachmessages.find_one({"_id": msg_ids[1]})
    assert reloaded["status"] == "sent"


# ---------------------------------------------------------------------------
# Requirement 2 (stats): followUpsPending counts only armed follow-ups, and
# replyRate stays a formatted string (no double percent sign).
# ---------------------------------------------------------------------------
async def test_stats_followups_pending_and_reply_rate_format(isolated_test_db):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    # This example builds its own records; clear the previous examples so the
    # count only reflects records created below (isolated test database only).
    await db.outreachrecords.delete_many({})
    cid, recipient, _msg_ids = await make_sequence(db)
    base = {
        "companyId": cid,
        "companyName": "Scheduling Policy Test Co",
        "recipientEmail": recipient,
        "initialEmail": {"status": "SENT", "sentAt": now},
        "replyStatus": "NO_REPLY",
        "campaignStatus": "INITIAL_SENT",
        "isTestSend": False,
        "createdAt": now,
        "updatedAt": now,
    }
    # Armed (PENDING + scheduledAt) -> counted.
    await db.outreachrecords.insert_one({
        **base,
        "followUp1": {"status": "PENDING", "scheduledAt": now + timedelta(days=1)},
        "followUp2": {"status": "PENDING"},
    })
    # Unarmed PENDING (inactive sequence) -> NOT counted.
    await db.outreachrecords.insert_one({
        **base, "recipientEmail": "other@example.com",
        "followUp1": {"status": "PENDING"},
        "followUp2": {"status": "PENDING"},
    })
    # Follow-ups already sent -> NOT counted as pending.
    await db.outreachrecords.insert_one({
        **base, "recipientEmail": "third@example.com",
        "followUp1": {"status": "SENT", "sentAt": now},
        "followUp2": {"status": "SENT", "sentAt": now},
    })

    stats = await get_outreach_stats()
    assert stats["followUpsPending"] == 1, "only armed PENDING follow-ups count"
    assert stats["initialSent"] == 3
    assert stats["followUp1Sent"] == 1
    assert stats["followUp2Sent"] == 1
    assert stats["replied"] == 0
    assert isinstance(stats["replyRate"], str)
    assert stats["replyRate"] == "0.0%"
    assert "%%" not in stats["replyRate"]


# ---------------------------------------------------------------------------
# Regressions: _step_base_time multi-step anchoring and isolation
# ---------------------------------------------------------------------------
async def test_step3_anchors_to_step1_sent_when_step2_is_scheduled(isolated_test_db):
    """When Step 1 was sent earlier and the operator schedules follow-ups,
    Step 2 is anchored to Step 1 sentAt + delayDays, and Step 3 is also
    anchored to Step 1 sentAt + delayDays (not button click time)."""
    db = isolated_test_db
    cid, recipient, msg_ids = await make_sequence(db)
    step1_sent_at = datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc)

    # Step 1 was sent two days ago
    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]},
        {"$set": {"status": "sent", "sentAt": step1_sent_at, "updatedAt": step1_sent_at}},
    )

    # Operator schedules Step 2 (+3 days) and Step 3 (+6 days)
    # The anchoring must be based on step1_sent_at, completely independent of whatever `now` is.
    await schedule_sequence_steps(str(cid), [
        {"step": 2, "delayDays": 3},
        {"step": 3, "delayDays": 6},
    ])

    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})

    assert m2["status"] == "scheduled"
    assert m3["status"] == "scheduled"
    # Step 2 must be anchored to Step 1 sentAt (2026-10-10 + 3d = 2026-10-13 10:00:00)
    expected_m2 = step1_sent_at + timedelta(days=3)
    assert abs((m2["scheduledAt"].replace(tzinfo=timezone.utc) - expected_m2).total_seconds()) < 5
    # Step 3 must be anchored to Step 1 sentAt (2026-10-10 + 6d = 2026-10-16 10:00:00), NOT now + 6d
    expected_m3 = step1_sent_at + timedelta(days=6)
    assert abs((m3["scheduledAt"].replace(tzinfo=timezone.utc) - expected_m3).total_seconds()) < 5


async def test_step_base_time_falls_back_to_now_when_no_prior_step_sent(isolated_test_db):
    """If Step 1 has not been sent (draft/approved/missing sentAt),
    _step_base_time falls back to current time `now`."""
    db = isolated_test_db
    cid, recipient, msg_ids = await make_sequence(db)
    now = datetime(2026, 10, 12, 14, 0, 0, tzinfo=timezone.utc)

    # Case 1: Step 1 is draft
    base = await sched_mod._step_base_time(db, cid, 2, recipient, now)
    assert base == now
    base3 = await sched_mod._step_base_time(db, cid, 3, recipient, now)
    assert base3 == now

    # Case 2: Step 1 is sent but sentAt is None / missing
    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]},
        {"$set": {"status": "sent", "sentAt": None}},
    )
    base_invalid = await sched_mod._step_base_time(db, cid, 2, recipient, now)
    assert base_invalid == now
    base3_invalid = await sched_mod._step_base_time(db, cid, 3, recipient, now)
    assert base3_invalid == now


async def test_scheduling_anchoring_isolates_companies_and_recipients(isolated_test_db):
    """Ensure sent timestamps from one company or recipient never bleed into
    another company's or recipient's follow-up base time calculations."""
    db = isolated_test_db
    cid_a, recip_a, msg_ids_a = await make_sequence(db)
    cid_b, recip_b, msg_ids_b = await make_sequence(db)

    sent_a = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
    await db.outreachmessages.update_one(
        {"_id": msg_ids_a[1]},
        {"$set": {"status": "sent", "sentAt": sent_a}},
    )

    now = datetime(2026, 10, 12, 10, 0, 0, tzinfo=timezone.utc)
    # Company B has no sent Step 1: its base time must NOT use Company A's timestamp
    base_b = await sched_mod._step_base_time(db, cid_b, 3, recip_b, now)
    assert base_b == now

    # Company A uses its own sent timestamp
    base_a = await sched_mod._step_base_time(db, cid_a, 3, recip_a, now)
    assert base_a == sent_a


async def test_rescheduling_preserves_content_and_creates_no_duplicates(isolated_test_db):
    """Re-scheduling a sequence must be idempotent: updates scheduledAt and delayDays,
    leaves subject, bodies, recipient, and message IDs untouched, without inserting duplicates."""
    db = isolated_test_db
    cid, recipient, msg_ids = await make_sequence(db)
    step1_sent_at = datetime(2026, 10, 5, 8, 30, 0, tzinfo=timezone.utc)

    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]},
        {"$set": {"status": "sent", "sentAt": step1_sent_at, "subject": "Custom Step 1"}},
    )
    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]},
        {"$set": {"subject": "Unique Step 2 Subject", "bodyText": "Custom Step 2 Body"}},
    )
    await db.outreachmessages.update_one(
        {"_id": msg_ids[3]},
        {"$set": {"subject": "Unique Step 3 Subject", "bodyText": "Custom Step 3 Body"}},
    )

    # First schedule
    await schedule_sequence_steps(str(cid), [
        {"step": 2, "delayDays": 3},
        {"step": 3, "delayDays": 6},
    ])
    assert await db.outreachmessages.count_documents({"companyId": cid}) == 3

    # Second schedule with different delays
    await schedule_sequence_steps(str(cid), [
        {"step": 2, "delayDays": 4},
        {"step": 3, "delayDays": 8},
    ])
    assert await db.outreachmessages.count_documents({"companyId": cid}) == 3

    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert m2["subject"] == "Unique Step 2 Subject"
    assert m2["bodyText"] == "Custom Step 2 Body"
    assert m2["delayDays"] == 4
    assert abs((m2["scheduledAt"].replace(tzinfo=timezone.utc) - (step1_sent_at + timedelta(days=4))).total_seconds()) < 5

    assert m3["subject"] == "Unique Step 3 Subject"
    assert m3["bodyText"] == "Custom Step 3 Body"
    assert m3["delayDays"] == 8
    assert abs((m3["scheduledAt"].replace(tzinfo=timezone.utc) - (step1_sent_at + timedelta(days=8))).total_seconds()) < 5


async def test_schedule_sequence_steps_blocks_invalid_recipients(isolated_test_db):
    """Messages with missing, None, or placeholder recipient emails must NEVER be armed or scheduled.
    They must remain draft and scheduledAt must not be set."""
    db = isolated_test_db
    cid, _recip, msg_ids = await make_sequence(db)

    # Put invalid recipients on the messages
    await db.outreachmessages.update_one({"_id": msg_ids[1]}, {"$set": {"recipientEmail": "Not publicly available"}})
    await db.outreachmessages.update_one({"_id": msg_ids[2]}, {"$set": {"recipientEmail": None}})
    await db.outreachmessages.update_one({"_id": msg_ids[3]}, {"$set": {"recipientEmail": ""}})

    activated = await schedule_sequence_steps(str(cid), [
        {"step": 1, "delayDays": 0},
        {"step": 2, "delayDays": 3},
        {"step": 3, "delayDays": 6},
    ])
    # Step 1 (delay 0, manual) can be approved, but Steps 2 and 3 (automatic follow-ups) MUST be blocked
    # from being scheduled and must remain draft without scheduledAt.
    assert len(activated) == 1
    assert activated[0]["step"] == 1

    m1 = await db.outreachmessages.find_one({"_id": msg_ids[1]})
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})

    assert m1["status"] == "approved"
    assert m2["status"] == "draft", "Step 2 with invalid recipient must remain draft"
    assert m3["status"] == "draft", "Step 3 with invalid recipient must remain draft"
    assert m1.get("scheduledAt") is None
    assert m2.get("scheduledAt") is None
    assert m3.get("scheduledAt") is None


async def test_dispatch_worker_blocks_invalid_recipient_even_if_marked_scheduled(isolated_test_db):
    """If an invalid recipient message was somehow marked scheduled, the dispatch worker
    must refuse to claim or send it, and mark it failed."""
    db = isolated_test_db
    await db.outreachmessages.delete_many({})
    await db.outreachrecords.delete_many({})
    cid, _recip, msg_ids = await make_sequence(db)
    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=1)

    # Step 1 was sent
    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]},
        {"$set": {"status": "sent", "sentAt": past - timedelta(days=1)}},
    )
    # Step 2 has an invalid recipient placeholder but was flagged scheduled in database
    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]},
        {"$set": {"status": "scheduled", "recipientEmail": "Not publicly available", "scheduledAt": past}},
    )

    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails()

    send_mock.assert_not_awaited()
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "failed"
    assert "Invalid recipient" in m2.get("error", "")