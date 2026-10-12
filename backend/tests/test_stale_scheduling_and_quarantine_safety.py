"""
Isolated Regression Suite: Stale Scheduling & Quarantine Safety Invariants.

Verifies the core invariants:
  "A draft remains inactive. A quarantined message remains blocked.
   Neither a stale timestamp nor reconciliation may override those conditions."

Test Matrix:
  1. Quarantined draft with stale scheduledAt -> never selected, never dispatched.
  2. Non-quarantined draft with stale scheduledAt -> never selected, never dispatched.
  3. Quarantined scheduled message with stale scheduledAt -> never dispatched, claim refused.
  4. Reconciler attempting to activate a draft -> draft stays inactive, never dispatched.
  5. Scheduler candidate selection -> selects ONLY eligible scheduled messages.
  6. Quarantine release operation -> preserves draft status strictly (never scheduled/approved).
  7. No implicit scheduling or sending after release -> released draft stays draft, no auto-send.

Safety & Isolation:
  - Dedicated MongoDB database (`ai_client_outreach_test_stale_sched_safety`).
  - Never touches production `ai_client_outreach`.
  - SMTP completely stubbed (no outbound network traffic).
"""
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

import app.config.database as db_module
import app.services.scheduler_service as sched_mod
from app.services.scheduler_service import (
    process_scheduled_emails,
    process_automated_follow_ups,
    _dispatch_scheduled_message,
)
from app.services.quarantine_service import (
    release_quarantined_message_service,
    QuarantineReleaseRequest,
)

TEST_DB_NAME = "ai_client_outreach_test_stale_sched_safety"
TEST_ADMIN_KEY = "test-stale-safety-key-2026"


@pytest.fixture(scope="module", autouse=True)
async def isolated_test_db():
    assert TEST_DB_NAME != "ai_client_outreach", "Safety violation: test database must never be live database!"
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


async def make_test_company(db, name="Test Co"):
    now = datetime.now(timezone.utc)
    res = await db.companies.insert_one({
        "companyName": name,
        "website": "https://example.com",
        "evidence": "Enterprise evidence for testing scheduling invariants.",
        "recommendedService": "AI Strategy",
        "createdAt": now,
        "updatedAt": now,
    })
    return res.inserted_id


# ---------------------------------------------------------------------------
# Test 1: Quarantined draft with stale scheduledAt is never selected or dispatched
# ---------------------------------------------------------------------------
async def test_quarantined_draft_with_stale_scheduled_at_never_dispatched(isolated_test_db):
    db = isolated_test_db
    cid = await make_test_company(db, "Quarantined Draft Co")
    now = datetime.now(timezone.utc)
    stale_time = now - timedelta(days=5)

    msg_res = await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 2,
        "status": "draft",
        "recipientEmail": "prospect@example.com",
        "subject": "Follow up",
        "bodyHtml": "<p>Hello</p>",
        "scheduledAt": stale_time,
        "delayDays": 3,
        "quarantined": True,
        "quarantine": {
            "batch": "quarantine-20261009",
            "active": True,
            "reason": "pre_deployment_safety_review",
        },
        "createdAt": stale_time,
        "updatedAt": now,
    })
    mid = msg_res.inserted_id

    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails()

    send_mock.assert_not_awaited()
    msg = await db.outreachmessages.find_one({"_id": mid})
    assert msg["status"] == "draft", "Status must remain draft"
    assert msg["quarantined"] is True, "Quarantine flag must remain True"


# ---------------------------------------------------------------------------
# Test 2: Non-quarantined draft with stale scheduledAt is never dispatched
# ---------------------------------------------------------------------------
async def test_non_quarantined_draft_with_stale_scheduled_at_never_dispatched(isolated_test_db):
    db = isolated_test_db
    cid = await make_test_company(db, "Ordinary Draft Co")
    now = datetime.now(timezone.utc)
    stale_time = now - timedelta(days=2)

    msg_res = await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 2,
        "status": "draft",
        "recipientEmail": "prospect2@example.com",
        "subject": "Follow up 2",
        "bodyHtml": "<p>Hello 2</p>",
        "scheduledAt": stale_time,
        "delayDays": 3,
        "quarantined": False,
        "createdAt": stale_time,
        "updatedAt": now,
    })
    mid = msg_res.inserted_id

    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails()

    send_mock.assert_not_awaited()
    msg = await db.outreachmessages.find_one({"_id": mid})
    assert msg["status"] == "draft", "Draft must remain draft despite stale scheduledAt"


# ---------------------------------------------------------------------------
# Test 3: Quarantined scheduled message is blocked from dispatch and claim
# ---------------------------------------------------------------------------
async def test_quarantined_scheduled_message_never_dispatched(isolated_test_db):
    db = isolated_test_db
    cid = await make_test_company(db, "Quarantined Scheduled Co")
    now = datetime.now(timezone.utc)
    stale_time = now - timedelta(minutes=10)

    # Prior step was sent
    await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 1,
        "status": "sent",
        "recipientEmail": "prospect3@example.com",
        "sentAt": stale_time - timedelta(days=3),
    })

    # Message is scheduled but quarantined
    msg_res = await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 2,
        "status": "scheduled",
        "recipientEmail": "prospect3@example.com",
        "subject": "Follow up 3",
        "bodyHtml": "<p>Hello 3</p>",
        "scheduledAt": stale_time,
        "delayDays": 3,
        "quarantined": True,
        "quarantine": {
            "batch": "quarantine-test",
            "active": True,
        },
        "createdAt": stale_time,
        "updatedAt": now,
    })
    mid = msg_res.inserted_id

    # 1. process_scheduled_emails skips it
    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails()
    send_mock.assert_not_awaited()

    # 2. direct dispatch call returns "quarantined"
    msg_doc = await db.outreachmessages.find_one({"_id": mid})
    result = await _dispatch_scheduled_message(msg_doc, now)
    assert result == "quarantined"

    # Status must not be mutated to sending
    msg_after = await db.outreachmessages.find_one({"_id": mid})
    assert msg_after["status"] == "scheduled"
    assert msg_after["quarantined"] is True


# ---------------------------------------------------------------------------
# Test 4: Reconciler never activates a draft message
# ---------------------------------------------------------------------------
async def test_reconciler_never_activates_or_dispatches_draft(isolated_test_db):
    db = isolated_test_db
    cid = await make_test_company(db, "Reconciler Draft Co")
    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=2)

    msg_res = await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 2,
        "status": "draft",
        "recipientEmail": "reconcile@example.com",
        "subject": "Reconcile subject",
        "bodyHtml": "<p>Body</p>",
        "quarantined": False,
        "createdAt": past,
        "updatedAt": now,
    })
    mid = msg_res.inserted_id

    # Tracking record looks due
    rec_res = await db.outreachrecords.insert_one({
        "companyId": cid,
        "companyName": "Reconciler Draft Co",
        "recipientEmail": "reconcile@example.com",
        "initialEmail": {"status": "SENT", "sentAt": past - timedelta(days=3)},
        "followUp1": {"status": "PENDING", "scheduledAt": past},
        "followUp2": {"status": "PENDING"},
        "replyStatus": "NO_REPLY",
        "campaignStatus": "INITIAL_SENT",
        "createdAt": past,
        "updatedAt": now,
    })

    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_automated_follow_ups()

    send_mock.assert_not_awaited()

    # Message must NEVER be activated to scheduled
    msg = await db.outreachmessages.find_one({"_id": mid})
    assert msg["status"] == "draft", "Reconciler must never convert draft to scheduled"

    # Tracking record scheduledAt was cleared to reconcile with inactive message
    rec = await db.outreachrecords.find_one({"_id": rec_res.inserted_id})
    assert "scheduledAt" not in rec["followUp1"] or rec["followUp1"]["scheduledAt"] is None


# ---------------------------------------------------------------------------
# Test 5: Scheduler selects only eligible scheduled messages
# ---------------------------------------------------------------------------
async def test_scheduler_selects_only_eligible_scheduled_messages(isolated_test_db):
    db = isolated_test_db
    cid = await make_test_company(db, "Candidate Selection Co")
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=5)

    # 1. Draft with stale scheduledAt -> must NOT be selected
    await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 2,
        "status": "draft",
        "recipientEmail": "draft@example.com",
        "scheduledAt": past,
        "quarantined": False,
    })

    # 2. Quarantined draft with stale scheduledAt -> must NOT be selected
    await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 2,
        "status": "draft",
        "recipientEmail": "qdraft@example.com",
        "scheduledAt": past,
        "quarantined": True,
    })

    # 3. Quarantined scheduled message -> must NOT be selected
    await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 2,
        "status": "scheduled",
        "recipientEmail": "qscheduled@example.com",
        "scheduledAt": past,
        "quarantined": True,
    })

    # 4. Valid Step 1 sent for candidate 4
    await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 1,
        "status": "sent",
        "recipientEmail": "eligible@example.com",
        "sentAt": past - timedelta(days=3),
    })

    # 5. Eligible scheduled message -> MUST be selected
    eligible_res = await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 2,
        "status": "scheduled",
        "recipientEmail": "eligible@example.com",
        "subject": "Eligible Subject",
        "bodyHtml": "<p>Eligible</p>",
        "scheduledAt": past,
        "quarantined": False,
    })
    eligible_id = eligible_res.inserted_id

    dispatched = []

    async def mock_send(msg_id, options=None):
        dispatched.append(msg_id)

    with patch.object(sched_mod, "send_outreach_email", side_effect=mock_send):
        await process_scheduled_emails()

    assert dispatched == [str(eligible_id)], "Only the eligible scheduled message should be dispatched"


# ---------------------------------------------------------------------------
# Test 6 & 7: Quarantine release preserves draft status and never auto-sends
# ---------------------------------------------------------------------------
async def test_quarantine_release_preserves_draft_status_and_never_auto_sends(isolated_test_db):
    db = isolated_test_db
    cid = await make_test_company(db, "Release Draft Co")
    now = datetime.now(timezone.utc)
    stale_time = now - timedelta(days=3)

    msg_res = await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 2,
        "status": "draft",
        "recipientEmail": "release_test@example.com",
        "subject": "Release Me",
        "bodyHtml": "<p>Content</p>",
        "scheduledAt": stale_time,
        "delayDays": 3,
        "quarantined": True,
        "quarantine": {
            "batch": "batch-release-test",
            "active": True,
            "reason": "safety_review",
        },
        "createdAt": stale_time,
        "updatedAt": now,
    })
    mid = msg_res.inserted_id

    req = QuarantineReleaseRequest(
        confirmMessageId=str(mid),
        expectedBatch="batch-release-test",
        reason="Manual audit verified safe",
        actor="lead_operator",
    )

    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_ADMIN_KEY}):
        result = await release_quarantined_message_service(str(mid), req, TEST_ADMIN_KEY)

    assert result["success"] is True

    # Invariant: Released message REMAINS A DRAFT!
    released_msg = await db.outreachmessages.find_one({"_id": mid})
    assert released_msg["status"] == "draft", "Released message must remain draft"
    assert released_msg["quarantined"] is False, "Quarantined flag must now be False"
    assert released_msg.get("quarantineReleased") is not None, "Release audit metadata must be recorded"

    # Invariant: Running scheduler pass does NOT implicitly schedule or send the released draft
    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails()

    send_mock.assert_not_awaited(), "Released draft must never be auto-sent"
    still_draft = await db.outreachmessages.find_one({"_id": mid})
    assert still_draft["status"] == "draft"
