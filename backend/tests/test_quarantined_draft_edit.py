"""
Quarantined-draft manual-edit workflow regression suite.

Proves the safe edit workflow for quarantined follow-up drafts:

  1. An operator can open a quarantined draft and edit its To/recipient
     email, CC, recipient name, subject and body — the save persists via the
     real `PUT /outreach/{id}` route AND the service function.
  2. Saving never sends, schedules, approves or activates: `status` stays
     `draft`, no SMTP call happens, no `scheduledAt`/`approvedAt`/`delayDays`
     is created, and the arming/send functions are never invoked.
  3. Quarantine state is preserved byte-for-byte: `quarantined=true`, the
     quarantine batch/metadata (`quarantine`) and the preimage
     (`quarantineOriginal`) are never cleared or overwritten — even when a
     payload explicitly tries to set them (bypass attempt).
  4. Each follow-up keeps its own independent subject/body: editing one step
     never rewrites another step's content, and a Step-1 recipient edit never
     touches quarantined follow-ups.
  5. Malformed email addresses are rejected with a clear HTTP 400 and the
     message document stays byte-identical (no partial write).
  6. Already-sent messages remain immutable history (content edits rejected).

Isolation: dedicated MongoDB database (`ai_client_outreach_test_quarantine_edit`)
dropped between runs — never touches the live `ai_client_outreach` database.
aiosmtplib.send is stubbed for the whole module, so no email can leave the
test process under any circumstance.
"""
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

import app.config.database as db_module
from app.routers.outreach_routes import update_message
from app.services.outreach_service import update_outreach_message

TEST_DB_NAME = "ai_client_outreach_test_quarantine_edit"

# Fixed past timestamp for fixture docs so the service's `updatedAt = now`
# is provably newer (no same-millisecond ambiguity).
FIXED_TS = datetime(2026, 9, 1, 9, 0, 0)


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
    """Belt-and-braces: aiosmtplib.send is stubbed so no email can leave the
    test process under any circumstance."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as smtp_mock:
        yield smtp_mock


def qmeta(step: int) -> dict:
    """Full quarantine metadata mirroring the real quarantine-20261009 docs."""
    return {
        "quarantined": True,
        "quarantine": {
            "batch": "quarantine-20261009",
            "reason": "pre_deployment_safety_review",
            "docHash": "f" * 64,
            "appliedAt": datetime(2026, 10, 9, 8, 48, 7),
            "originalStatus": "scheduled",
        },
        "quarantineOriginal": {
            "status": "scheduled",
            "step": step,
            "subject": f"pre-image subject for step {step}",
        },
    }


async def make_sequence(db, *, quarantine_steps=(2, 3)):
    """Insert a company + 3 independent draft messages; apply full quarantine
    metadata to the requested steps (mirrors the real quarantined follow-ups)."""
    comp_res = await db.companies.insert_one({
        "companyName": "Quarantine Edit Test Co",
        "website": "https://qedit.example",
        "normalizedWebsite": "qedit.example",
        "evidence": "Evidence for the quarantined-draft manual-edit suite.",
        "recommendedService": "AI Strategy Consulting",
        "createdAt": FIXED_TS,
        "updatedAt": FIXED_TS,
    })
    cid = comp_res.inserted_id
    recipient = "prospect@qedit.example"
    msg_ids = {}
    for step in (1, 2, 3):
        doc = {
            "companyId": cid,
            "step": step,
            "status": "draft",
            "subject": f"Step {step} - Original Subject",
            "bodyHtml": f"<p>Step {step} original body</p>",
            "bodyText": f"Step {step} original body",
            "recipientEmail": recipient,
            "recipientName": "Prospect",
            "ccRecipients": ["cc@qedit.example"],
            "createdAt": FIXED_TS,
            "updatedAt": FIXED_TS,
        }
        if step in quarantine_steps:
            doc.update(qmeta(step))
        res = await db.outreachmessages.insert_one(doc)
        msg_ids[step] = res.inserted_id
    return cid, recipient, msg_ids


async def doc_snapshot(db, message_id):
    """Full-document snapshot used to prove byte-level (im)mutability."""
    doc = await db.outreachmessages.find_one({"_id": message_id})
    doc.pop("_id", None)
    return doc


QUARANTINE_FIELDS = ("quarantined", "quarantine", "quarantineOriginal")


# ---------------------------------------------------------------------------
# 1. Edits persist; quarantine fields, batch and preimage are preserved.
# ---------------------------------------------------------------------------
async def test_quarantined_draft_edit_persists_and_preserves_quarantine(
        isolated_test_db, block_real_smtp):
    db = isolated_test_db
    _cid, _recipient, msg_ids = await make_sequence(db)
    before = await doc_snapshot(db, msg_ids[2])
    steps_before = {s: await doc_snapshot(db, msg_ids[s]) for s in (1, 3)}

    resp = await update_message(str(msg_ids[2]), {
        "recipientEmail": "new.prospect@qedit.example",
        "recipientName": "New Prospect Name",
        "ccRecipients": ["legal@qedit.example", "ops@qedit.example"],
        "subject": "Manually corrected subject",
        "bodyHtml": "<p>Manually corrected body</p>",
        "bodyText": "Manually corrected body",
    })

    assert resp["success"] is True
    saved = resp["data"]
    # All five editable field groups persisted.
    assert saved["recipientEmail"] == "new.prospect@qedit.example"
    assert saved["recipientName"] == "New Prospect Name"
    assert saved["ccRecipients"] == ["legal@qedit.example", "ops@qedit.example"]
    assert saved["subject"] == "Manually corrected subject"
    assert saved["bodyHtml"] == "<p>Manually corrected body</p>"
    assert saved["bodyText"] == "Manually corrected body"

    after = await doc_snapshot(db, msg_ids[2])
    # Quarantine state + batch + preimage byte-identical; still a draft.
    assert after["status"] == "draft"
    for f in QUARANTINE_FIELDS:
        assert after[f] == before[f], f"quarantine field '{f}' must be preserved"
    assert after["quarantine"]["batch"] == "quarantine-20261009"
    assert "scheduledAt" not in after
    assert "approvedAt" not in after
    assert "delayDays" not in after
    # Edit bookkeeping only.
    assert after["isManuallyEdited"] is True
    assert after["updatedAt"] > before["updatedAt"]
    # Steps 1 and 3 untouched (their own subject/body intact).
    for s in (1, 3):
        assert await doc_snapshot(db, msg_ids[s]) == steps_before[s]
    # Nothing armed/approved/sending anywhere in this test database.
    armed = await db.outreachmessages.count_documents(
        {"status": {"$in": ["scheduled", "approved", "sending"]}}
    )
    assert armed == 0
    block_real_smtp.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Editing one follow-up never rewrites another step's subject/body.
# ---------------------------------------------------------------------------
async def test_editing_one_quarantined_step_never_rewrites_other_steps(
        isolated_test_db, block_real_smtp):
    db = isolated_test_db
    _cid, _recipient, msg_ids = await make_sequence(db)
    before = {s: await doc_snapshot(db, msg_ids[s]) for s in (1, 2, 3)}

    resp = await update_message(str(msg_ids[2]), {
        "subject": "Step 2 only subject",
        "bodyHtml": "<p>Step 2 only body</p>",
        "bodyText": "Step 2 only body",
    })
    assert resp["success"] is True

    after2 = await doc_snapshot(db, msg_ids[2])
    assert after2["subject"] == "Step 2 only subject"
    assert after2["bodyText"] == "Step 2 only body"
    # Steps 1 and 3 keep their own independent subject/body — byte-identical.
    for s in (1, 3):
        assert await doc_snapshot(db, msg_ids[s]) == before[s], \
            f"step {s} content must never be overwritten by another step's edit"
    # Every other field on the edited message (incl. quarantine) untouched.
    for f in ("recipientEmail", "recipientName", "ccRecipients", *QUARANTINE_FIELDS, "status"):
        assert after2[f] == before[2][f]
    block_real_smtp.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Malformed addresses -> clear HTTP 400, byte-identical (no partial write).
# ---------------------------------------------------------------------------
async def test_invalid_recipient_rejected_with_clear_error_and_no_write(
        isolated_test_db, block_real_smtp):
    db = isolated_test_db
    _cid, _recipient, msg_ids = await make_sequence(db)
    before = await doc_snapshot(db, msg_ids[2])

    with pytest.raises(HTTPException) as exc:
        await update_message(str(msg_ids[2]), {"recipientEmail": "not-an-email"})

    assert exc.value.status_code == 400
    detail = str(exc.value.detail)
    assert "not-an-email" in detail
    assert "invalid" in detail.lower()
    # Zero write: full document byte-identical (no updatedAt/no isManuallyEdited).
    assert await doc_snapshot(db, msg_ids[2]) == before
    block_real_smtp.assert_not_called()


async def test_invalid_cc_rejected_with_clear_error_and_no_write(
        isolated_test_db, block_real_smtp):
    db = isolated_test_db
    _cid, _recipient, msg_ids = await make_sequence(db)
    before = await doc_snapshot(db, msg_ids[3])

    with pytest.raises(HTTPException) as exc:
        await update_outreach_message(str(msg_ids[3]), {
            "subject": "Would-be edit",
            "ccRecipients": ["ok@qedit.example", "bad cc address"],
        })

    assert exc.value.status_code == 400
    detail = str(exc.value.detail)
    assert "CC" in detail
    assert "bad cc address" in detail
    assert await doc_snapshot(db, msg_ids[3]) == before
    block_real_smtp.assert_not_called()


async def test_blank_recipient_still_saves(isolated_test_db, block_real_smtp):
    """Blank is not a format violation: clearing the To field is allowed
    (sending stays blocked server-side for quarantined drafts anyway)."""
    db = isolated_test_db
    _cid, _recipient, msg_ids = await make_sequence(db)

    resp = await update_message(str(msg_ids[2]), {
        "recipientEmail": "",
        "subject": "Recipient cleared while reviewing",
    })
    assert resp["success"] is True

    after = await doc_snapshot(db, msg_ids[2])
    assert after["recipientEmail"] == ""
    assert after["status"] == "draft"
    assert after["quarantined"] is True
    assert after["quarantine"] == qmeta(2)["quarantine"]
    block_real_smtp.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Saving performs NO SMTP, scheduling, approval or activation.
# ---------------------------------------------------------------------------
async def test_save_triggers_no_smtp_no_scheduling_and_no_approval(
        isolated_test_db, block_real_smtp):
    db = isolated_test_db
    _cid, _recipient, msg_ids = await make_sequence(db)
    before = await doc_snapshot(db, msg_ids[3])

    with patch("app.routers.outreach_routes.send_outreach_email", new=AsyncMock()) as route_send, \
            patch("app.routers.outreach_routes.schedule_sequence_steps", new=AsyncMock()) as route_arm, \
            patch("app.services.scheduler_service.send_outreach_email", new=AsyncMock()) as worker_send:
        resp = await update_message(str(msg_ids[3]), {
            "subject": "Edited without side effects",
            "recipientEmail": "reviewer@qedit.example",
        })

    assert resp["success"] is True
    route_send.assert_not_awaited()
    route_arm.assert_not_awaited()
    worker_send.assert_not_awaited()
    block_real_smtp.assert_not_called()

    after = await doc_snapshot(db, msg_ids[3])
    assert after["subject"] == "Edited without side effects"  # the edit itself saved
    assert after["status"] == "draft"                          # never approved/armed/sent
    for f in ("scheduledAt", "approvedAt", "sentAt", "delayDays", "sendingStartedAt"):
        assert f not in after, f"'{f}' must never be created by a save"
    for f in QUARANTINE_FIELDS:
        assert after[f] == before[f]
    armed = await db.outreachmessages.count_documents(
        {"status": {"$in": ["scheduled", "approved", "sending"]}}
    )
    assert armed == 0


# ---------------------------------------------------------------------------
# 3. Bypass attempt: payload cannot arm, approve, send or un-quarantine.
# ---------------------------------------------------------------------------
async def test_bypass_payload_cannot_set_status_or_clear_quarantine(
        isolated_test_db, block_real_smtp):
    db = isolated_test_db
    _cid, _recipient, msg_ids = await make_sequence(db)
    before = await doc_snapshot(db, msg_ids[2])

    resp = await update_message(str(msg_ids[2]), {
        "subject": "Legit edit alongside the bypass attempt",
        "status": "approved",
        "quarantined": False,
        "quarantine": None,
        "quarantineOriginal": None,
        "scheduledAt": "2026-10-10T00:00:00Z",
        "delayDays": 0,
        "sentAt": "2026-10-10T00:00:00Z",
    })
    assert resp["success"] is True

    after = await doc_snapshot(db, msg_ids[2])
    # The legitimate edit saved...
    assert after["subject"] == "Legit edit alongside the bypass attempt"
    # ...but every protected field was ignored, not applied.
    assert after["status"] == "draft"
    assert after["quarantined"] is True
    for f in QUARANTINE_FIELDS:
        assert after[f] == before[f], f"'{f}' must never be cleared or overwritten"
    for f in ("scheduledAt", "sentAt", "delayDays"):
        assert f not in after
    armed = await db.outreachmessages.count_documents(
        {"status": {"$in": ["scheduled", "approved", "sending"]}}
    )
    assert armed == 0
    block_real_smtp.assert_not_called()


# ---------------------------------------------------------------------------
# 8. Already-sent messages are never content-editable.
# ---------------------------------------------------------------------------
async def test_sent_message_content_edit_rejected_and_unchanged(
        isolated_test_db, block_real_smtp):
    db = isolated_test_db
    comp_res = await db.companies.insert_one({
        "companyName": "Quarantine Edit Sent Co",
        "website": "https://qedit-sent.example",
        "normalizedWebsite": "qedit-sent.example",
        "evidence": "Evidence.",
        "recommendedService": "AI Strategy Consulting",
        "createdAt": FIXED_TS,
        "updatedAt": FIXED_TS,
    })
    sent_res = await db.outreachmessages.insert_one({
        "companyId": comp_res.inserted_id,
        "step": 1,
        "status": "sent",
        "subject": "Original sent subject",
        "bodyHtml": "<p>Original sent body</p>",
        "bodyText": "Original sent body",
        "recipientEmail": "someone@qedit-sent.example",
        "recipientName": "Someone",
        "createdAt": FIXED_TS,
        "updatedAt": FIXED_TS,
        "sentAt": FIXED_TS,
    })
    sent_id = sent_res.inserted_id
    before = await doc_snapshot(db, sent_id)

    with pytest.raises(HTTPException) as exc:
        await update_message(str(sent_id), {
            # Recipient present -> the rejection is about CONTENT, not a
            # missing field.
            "recipientEmail": "someone@qedit-sent.example",
            "subject": "Rewritten history",
            "bodyHtml": "<p>rewritten</p>",
            "bodyText": "rewritten",
        })

    assert exc.value.status_code == 400
    assert "sent" in str(exc.value.detail).lower()
    assert await doc_snapshot(db, sent_id) == before
    block_real_smtp.assert_not_called()


# ---------------------------------------------------------------------------
# 4b. A Step-1 recipient edit never touches quarantined follow-ups.
# ---------------------------------------------------------------------------
async def test_step1_recipient_edit_leaves_quarantined_followups_byte_identical(
        isolated_test_db, block_real_smtp):
    db = isolated_test_db
    _cid, _recipient, msg_ids = await make_sequence(db)  # steps 2+3 quarantined
    before = {s: await doc_snapshot(db, msg_ids[s]) for s in (1, 2, 3)}

    updated, sync_info = await update_outreach_message(
        str(msg_ids[1]), {"recipientEmail": "brand.new@qedit.example"}
    )

    assert updated["recipientEmail"] == "brand.new@qedit.example"
    # Quarantined follow-ups are never eligible for synchronization.
    assert sync_info.get("updated", 0) == 0
    assert not sync_info.get("conflicts")
    # Steps 1's own copy stayed content-identical (recipient-only change).
    after1 = await doc_snapshot(db, msg_ids[1])
    assert after1["subject"] == before[1]["subject"]
    assert after1["bodyText"] == before[1]["bodyText"]
    # Quarantined follow-ups byte-identical — recipients NOT redirected.
    for s in (2, 3):
        assert await doc_snapshot(db, msg_ids[s]) == before[s]
        assert (await doc_snapshot(db, msg_ids[s]))["quarantined"] is True
    block_real_smtp.assert_not_called()
