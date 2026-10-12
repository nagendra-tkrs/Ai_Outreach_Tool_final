"""
Quarantine hard-stop regression suite (fixes the 2026-10-09 audit finding).

Locks in the safety behaviour that an explicitly `quarantined=true` outreach
message can NEVER be armed, approved, scheduled, activated, or sent through
any code path:

  1. A quarantined draft cannot be armed/scheduled (Q1 arming filter).
  2. A quarantined approved/scheduled message cannot pass the final send
     boundary (Q4 in send_outreach_email -> HTTP 409, no mutation, no SMTP).
  3. A mixed sequence (quarantined + ordinary drafts) only ever arms the
     ordinary messages; quarantined ones are skipped untouched.
  4. Legacy non-quarantined messages (missing `quarantined`, or
     `quarantined=False`) retain their existing behaviour.
  5. Quarantine metadata, batch, `quarantineOriginal` and `docHash` remain
     byte-identical across every blocked path.
  6. No SMTP call or dispatch occurs for a blocked message (worker selection
     Q3, atomic claim Q2, dispatch pre-check Q2, reconciler lookup Q3).
  7. API route and service-level paths cannot bypass the guard; the schedule
     route reports `quarantinedSkipped` and changes nothing on those messages.

Isolation: dedicated MongoDB database (`ai_client_outreach_test_quarantine`)
dropped between runs — never touches the live `ai_client_outreach` database.
aiosmtplib.send is stubbed for the whole module, so no email can leave the
test process under any circumstance.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

import app.config.database as db_module
import app.services.scheduler_service as sched_mod
from app.routers.outreach_routes import schedule_sequence, send_email
from app.services.email_service import send_outreach_email
from app.services.scheduler_service import (
    _dispatch_scheduled_message,
    process_scheduled_emails,
    schedule_sequence_steps,
)

TEST_DB_NAME = "ai_client_outreach_test_quarantine"


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


QUARANTINE_META = {
    "quarantined": True,
    "quarantine": {
        "batch": "quarantine-test-batch",
        "reason": "pre_deployment_safety_review",
        "docHash": "0" * 64,
        "appliedAt": datetime(2026, 10, 9, 8, 48, 7),
        "originalStatus": "scheduled",
    },
    "quarantineOriginal": {"status": "scheduled", "step": 2, "subject": "pre-image"},
}


async def make_sequence(db, *, quarantine_steps=()):
    """Insert a company + 3 draft messages; apply full quarantine metadata to
    the requested steps (mirrors the real quarantine-20261009 documents)."""
    now = datetime.now(timezone.utc)
    comp_res = await db.companies.insert_one({
        "companyName": "Quarantine Guard Test Co",
        "website": "https://qguard.example",
        "normalizedWebsite": "qguard.example",
        "evidence": "Evidence for the quarantine guard regression suite.",
        "recommendedService": "AI Strategy Consulting",
        "createdAt": now,
        "updatedAt": now,
    })
    cid = comp_res.inserted_id
    recipient = "prospect@qguard.example"
    msg_ids = {}
    for step in (1, 2, 3):
        doc = {
            "companyId": cid,
            "step": step,
            "status": "draft",
            "subject": f"Step {step} - Quarantine Guard",
            "bodyHtml": "<p>Hello</p>",
            "bodyText": "Hello",
            "recipientEmail": recipient,
            "recipientName": "Prospect",
            "createdAt": now,
            "updatedAt": now,
        }
        if step in quarantine_steps:
            doc.update(QUARANTINE_META)
        res = await db.outreachmessages.insert_one(doc)
        msg_ids[step] = res.inserted_id
    return cid, recipient, msg_ids


async def quarantine_snapshot(db, message_id):
    """Full-document snapshot used to prove byte-level immutability."""
    doc = await db.outreachmessages.find_one({"_id": message_id})
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Requirement 1: a quarantined draft can never be armed/scheduled.
# ---------------------------------------------------------------------------
async def test_quarantined_draft_cannot_be_armed(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    cid, _recipient, msg_ids = await make_sequence(db, quarantine_steps=(1, 2))

    updated = await schedule_sequence_steps(str(cid), [
        {"step": 1, "delayDays": 0},    # would become `approved`
        {"step": 2, "delayDays": 3},    # would become `scheduled`
        {"step": 3, "delayDays": 6},    # ordinary -> must still arm
    ])

    # Only the ordinary step 3 was armed.
    assert [m["step"] for m in updated] == [3]

    s1 = await db.outreachmessages.find_one({"_id": msg_ids[1]})
    assert s1["status"] == "draft", "quarantined step 1 must never become approved"
    assert s1.get("scheduledAt") is None
    assert s1.get("delayDays") is None

    s2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert s2["status"] == "draft", "quarantined step 2 must never become scheduled"
    assert s2.get("scheduledAt") is None
    assert s2.get("delayDays") is None
    assert s2["quarantine"]["batch"] == "quarantine-test-batch"

    s3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert s3["status"] == "scheduled", "eligible non-quarantined step must still arm"


# ---------------------------------------------------------------------------
# Requirement 2: the final send boundary always rejects quarantined messages.
# ---------------------------------------------------------------------------
async def test_quarantined_message_cannot_pass_send_boundary(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    cid, _recipient, msg_ids = await make_sequence(db, quarantine_steps=(1, 2))

    # Legacy-inconsistent state: somehow `approved` while quarantined.
    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]}, {"$set": {"status": "approved"}}
    )

    for mid in (msg_ids[1], msg_ids[2]):
        before = await quarantine_snapshot(db, mid)
        with pytest.raises(HTTPException) as exc:
            await send_outreach_email(str(mid))
        assert exc.value.status_code == 409
        assert "quarantined" in exc.value.detail.lower()
        after = await quarantine_snapshot(db, mid)
        assert after == before, "send rejection must not mutate the message"

    block_real_smtp.assert_not_called(), "no SMTP activity for blocked messages"


# ---------------------------------------------------------------------------
# Requirement 3: mixed sequence arms only the ordinary drafts.
# ---------------------------------------------------------------------------
async def test_mixed_sequence_never_schedules_quarantined_items(isolated_test_db):
    db = isolated_test_db
    cid, _recipient, msg_ids = await make_sequence(db, quarantine_steps=(2,))

    updated = await schedule_sequence_steps(str(cid), [
        {"step": 2, "delayDays": 3},
        {"step": 3, "delayDays": 6},
    ])
    assert [m["step"] for m in updated] == [3]

    q = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert q["status"] == "draft" and q.get("scheduledAt") is None
    assert q["quarantined"] is True and q["quarantine"]["batch"] == "quarantine-test-batch"

    ok = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert ok["status"] == "scheduled" and ok.get("scheduledAt") is not None


# ---------------------------------------------------------------------------
# Requirement 4: legacy non-quarantined messages keep existing behaviour.
# ---------------------------------------------------------------------------
async def test_legacy_non_quarantined_messages_retain_existing_behavior(isolated_test_db):
    db = isolated_test_db
    cid, recipient, msg_ids = await make_sequence(db)  # no `quarantined` field at all

    # `quarantined=False` must behave exactly like a missing field.
    await db.outreachmessages.update_one(
        {"_id": msg_ids[3]}, {"$set": {"quarantined": False}}
    )

    updated = await schedule_sequence_steps(str(cid), [
        {"step": 1, "delayDays": 0},
        {"step": 2, "delayDays": 10},
        {"step": 3, "delayDays": 20},
    ])
    assert len(updated) == 3, "legacy/falsy-quarantine messages must arm as before"

    s1 = await db.outreachmessages.find_one({"_id": msg_ids[1]})
    assert s1["status"] == "approved" and s1.get("scheduledAt") is None
    s2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert s2["status"] == "scheduled" and s2["delayDays"] == 10

    # Manual send through the real sandbox pipeline still works.
    await send_outreach_email(str(msg_ids[1]))
    s1 = await db.outreachmessages.find_one({"_id": msg_ids[1]})
    assert s1["status"] == "sent"
    record = await db.outreachrecords.find_one({"companyId": cid, "recipientEmail": recipient})
    assert record is not None and record["initialEmail"]["status"] == "SENT"


# ---------------------------------------------------------------------------
# Requirement 5: quarantine metadata is byte-identical across every blocked
# path (arming attempt, send attempt, worker pass, direct dispatch, route).
# ---------------------------------------------------------------------------
async def test_quarantine_metadata_unchanged_by_all_blocked_paths(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    cid, _recipient, msg_ids = await make_sequence(db, quarantine_steps=(2,))

    # 1) Arming attempt on the quarantined draft: full-document equality.
    before = await quarantine_snapshot(db, msg_ids[2])
    await schedule_sequence_steps(str(cid), [{"step": 2, "delayDays": 3}])
    assert await quarantine_snapshot(db, msg_ids[2]) == before

    # 2) Service-level send attempt: full-document equality.
    with pytest.raises(HTTPException):
        await send_outreach_email(str(msg_ids[2]))
    assert await quarantine_snapshot(db, msg_ids[2]) == before

    # 3) Legacy bad state (quarantined + scheduled + due), then a full worker
    #    pass: the worker must change nothing at all.
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]}, {"$set": {"status": "sent", "sentAt": past}}
    )
    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]}, {"$set": {"status": "scheduled", "scheduledAt": past}}
    )
    armed = await quarantine_snapshot(db, msg_ids[2])
    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails()
    send_mock.assert_not_awaited()
    assert await quarantine_snapshot(db, msg_ids[2]) == armed, \
        "worker must leave the quarantined message exactly as found"

    # 4) Direct dispatch call on the quarantined message.
    armed_doc = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    result = await _dispatch_scheduled_message(armed_doc, past)
    assert result == "quarantined"
    assert await quarantine_snapshot(db, msg_ids[2]) == armed

    # 5) Route-level schedule attempt: still nothing changes on the message.
    resp = await schedule_sequence(str(cid), {"schedules": [{"step": 2, "delayDays": 3}]})
    assert resp["data"] == []
    assert len(resp["quarantinedSkipped"]) == 1
    assert await quarantine_snapshot(db, msg_ids[2]) == armed

    # The quarantine sub-structure is intact end-to-end.
    final = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert final["quarantine"] == before["quarantine"]
    assert final["quarantineOriginal"] == before["quarantineOriginal"]
    assert final["quarantine"]["docHash"] == "0" * 64
    assert final["quarantine"]["batch"] == "quarantine-test-batch"

    block_real_smtp.assert_not_called()


# ---------------------------------------------------------------------------
# Requirement 6: no SMTP call or dispatch occurs for a blocked message —
# worker selection, atomic claim and the record reconciler all refuse it.
# ---------------------------------------------------------------------------
async def test_no_smtp_or_dispatch_for_blocked_message(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    # Fully isolated state for this example.
    await db.outreachmessages.delete_many({})
    await db.outreachrecords.delete_many({})
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    cid, recipient, msg_ids = await make_sequence(db, quarantine_steps=(2,))
    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]}, {"$set": {"status": "sent", "sentAt": past - timedelta(days=3)}}
    )
    # Legacy bad state: the quarantined follow-up looks armed AND due.
    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]},
        {"$set": {"status": "scheduled", "delayDays": 3, "scheduledAt": past}},
    )
    await db.outreachrecords.insert_one({
        "companyId": cid,
        "companyName": "Quarantine Guard Test Co",
        "recipientEmail": recipient,
        "initialEmail": {"status": "SENT", "sentAt": past - timedelta(days=3)},
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

    send_mock.assert_not_awaited(), "workers must never dispatch a quarantined message"
    block_real_smtp.assert_not_called(), "no SMTP activity whatsoever"

    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "scheduled", "blocked message must not be claimed or failed"
    rec = await db.outreachrecords.find_one({"companyId": cid})
    assert rec["followUp1"]["status"] == "PENDING", "record must not be marked FAILED"

    # The atomic claim itself also refuses quarantined messages.
    claimed = await db.outreachmessages.find_one_and_update(
        {"_id": msg_ids[2], "status": "scheduled", "quarantined": {"$ne": True}},
        {"$set": {"status": "sending"}},
        return_document=True,
    )
    assert claimed is None
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "scheduled"


# ---------------------------------------------------------------------------
# Requirement 7: API and service-level paths cannot bypass the guard, and the
# schedule route reports quarantined messages as skipped (clear safe result).
# ---------------------------------------------------------------------------
async def test_api_and_service_paths_cannot_bypass(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    cid, _recipient, msg_ids = await make_sequence(db, quarantine_steps=(2,))

    # API: schedule route — arms step 3, reports step 2 as skipped.
    resp = await schedule_sequence(str(cid), {
        "schedules": [{"step": 2, "delayDays": 3}, {"step": 3, "delayDays": 6}],
    })
    assert resp["success"] is True
    assert [m["step"] for m in resp["data"]] == [3]
    assert len(resp["quarantinedSkipped"]) == 1
    skipped = resp["quarantinedSkipped"][0]
    assert skipped["step"] == 2 and skipped["status"] == "draft"
    assert "remain quarantined" in resp["message"]

    q = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert q["status"] == "draft" and q["quarantine"]["batch"] == "quarantine-test-batch"

    # API: send route — 409, nothing dispatched.
    with pytest.raises(HTTPException) as exc:
        await send_email(str(msg_ids[2]), {})
    assert exc.value.status_code == 409
    block_real_smtp.assert_not_called()

    # Service: direct send_outreach_email — same hard-stop.
    with pytest.raises(HTTPException) as exc:
        await send_outreach_email(str(msg_ids[2]))
    assert exc.value.status_code == 409

    # Nothing was ever unquarantined.
    n_quarantined = await db.outreachmessages.count_documents(
        {"companyId": cid, "quarantined": True}
    )
    assert n_quarantined == 1


# ---------------------------------------------------------------------------
# Requirement 7 (matrix completion): a quarantined message in legacy
# `approved` or `scheduled` state is refused by BOTH the API route and the
# service-level send, and the worker never selects it — byte-for-byte
# immutability and zero SMTP throughout.
# ---------------------------------------------------------------------------
async def test_quarantined_approved_and_scheduled_blocked_at_route_service_and_worker(
        isolated_test_db, block_real_smtp):
    db = isolated_test_db
    cid, _recipient, msg_ids = await make_sequence(db, quarantine_steps=(1, 2))
    past = datetime.now(timezone.utc) - timedelta(minutes=1)

    # Legacy bad states that guards must tolerate without ever acting on them.
    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]}, {"$set": {"status": "approved"}}
    )
    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]},
        {"$set": {"status": "scheduled", "delayDays": 3, "scheduledAt": past}},
    )
    snap1 = await quarantine_snapshot(db, msg_ids[1])
    snap2 = await quarantine_snapshot(db, msg_ids[2])

    # API send route on the quarantined `approved` message -> 409, unchanged.
    with pytest.raises(HTTPException) as exc:
        await send_email(str(msg_ids[1]), {})
    assert exc.value.status_code == 409
    assert await quarantine_snapshot(db, msg_ids[1]) == snap1

    # API send route on the quarantined `scheduled` message -> 409, unchanged.
    with pytest.raises(HTTPException) as exc:
        await send_email(str(msg_ids[2]), {})
    assert exc.value.status_code == 409
    assert await quarantine_snapshot(db, msg_ids[2]) == snap2

    # Service-level send on the `scheduled` state -> 409, unchanged.
    with pytest.raises(HTTPException) as exc:
        await send_outreach_email(str(msg_ids[2]))
    assert exc.value.status_code == 409
    assert await quarantine_snapshot(db, msg_ids[2]) == snap2

    # Worker pass: the due quarantined `scheduled` message is never selected,
    # never claimed, never dispatched — everything stays byte-identical.
    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails()
    send_mock.assert_not_awaited()
    block_real_smtp.assert_not_called()
    assert await quarantine_snapshot(db, msg_ids[1]) == snap1
    assert await quarantine_snapshot(db, msg_ids[2]) == snap2

    final = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert final["status"] == "scheduled"   # not claimed, not failed, not sent
    assert final["quarantined"] is True     # never unquarantined
    assert final["quarantine"]["batch"] == "quarantine-test-batch"
