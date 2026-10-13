"""
Regression suite: evidence-based Primary Email + Step 2/3 recipient sync.

Locks in the new behaviour:

  1. Primary (Step 1) email is built from the persisted Evidence + Recommended
     Service, uses the canonical TKSR signature, and never fabricates facts.
  2. When evidence is missing/placeholder the email is conservative — no invented
     company observation, no crash.
  3. Generation requires Evidence + Recommended Service (400 otherwise).
  4. Manual edits on a draft survive re-generation; the explicit `regenerate`
     action is the only thing that replaces them.
  5. Sent messages are immutable history — only a recipient-only correction is
     allowed, and that pauses Steps 2/3 for review instead of silently
     redirecting the sequence.
  6. Editing the recipient of an unsent Step 1 synchronizes eligible unsent
     Step 2/3 messages (copy, CC/BCC, status, delays and dates preserved).
  7. Step 2/3 copy is purpose-specific and never the Step 1 body.
  8. The latest saved subject/body is what actually gets dispatched.
  9. Empty / "None" recipients are handled safely (E8 gate, no SMTP, no crash).
 10. Editing Step 1's CC list synchronizes that CC list onto eligible unsent
     Step 2/3 messages while their subject, bodies, primary recipient, recipient
     name, BCC, status and schedule stay untouched (CC is de-duplicated
     case-insensitively and never re-activates a parked sequence).

Isolation: dedicated MongoDB database (`ai_client_outreach_test_email_sync`) that
is dropped between runs. SMTP transport is stubbed so no email can leave the
process; `ALLOW_ETHEREAL_TEST=true` (conftest) routes the pipeline through the
no-network sandbox path. The live `ai_client_outreach` database is never touched.
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

import app.config.database as db_module
import app.services.outreach_service as osrv_mod
import app.services.scheduler_service as sched_mod
from app.services.ai_service import (
    build_followup_email,
    build_primary_email,
    sanitize_evidence,
)
from app.services.email_service import send_outreach_email
from app.services.outreach_service import (
    generate_outreach_sequence,
    regenerate_outreach_message,
    update_outreach_message,
)
from app.routers.outreach_routes import update_message as update_message_route
from app.services.scheduler_service import (
    process_scheduled_emails,
    schedule_sequence_steps,
)
from app.utils.bson_utils import to_object_id

TEST_DB_NAME = "ai_client_outreach_test_email_sync"

EVIDENCE = (
    "The company modernised its logistics operations and now manages a fleet of "
    "200 vehicles across Europe, with dispatch still coordinated through spreadsheets."
)
SERVICE = "AI & Automation Workshops"


@pytest.fixture(scope="module", autouse=True)
async def isolated_test_db():
    """Run this module against a dedicated test database, then restore the app's
    previous database binding and drop the test database."""
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
    """Belt-and-braces: aiosmtplib.send is stubbed so no email can be sent."""
    with patch("app.services.email_service.aiosmtplib.send", new=AsyncMock()) as smtp_mock:
        yield smtp_mock


async def make_company(db, *, name="Email Sync Test Co", evidence=EVIDENCE,
                       service=SERVICE, recipient="asha.patel@emailsync.example",
                       contact_name="Asha Patel"):
    now = datetime.now(timezone.utc)
    comp_res = await db.companies.insert_one({
        "companyName": name,
        "website": f"https://{name.lower().replace(' ', '')}.example",
        "normalizedWebsite": f"{name.lower().replace(' ', '')}.example",
        "industry": "Logistics",
        "evidence": evidence,
        "recommendedService": service,
        "createdAt": now,
        "updatedAt": now,
    })
    cid = comp_res.inserted_id
    contact_res = await db.contacts.insert_one({
        "companyId": cid,
        "name": contact_name,
        "title": "Head of Operations",
        "email": recipient,
        "roleCategory": "dept_head",
        "seniority": "head",
        "overallScore": 90,
        "createdAt": now,
        "updatedAt": now,
    })
    return cid, contact_res.inserted_id, recipient


async def make_sequence(db, **kwargs):
    """Company + contact + three raw draft messages (same recipient)."""
    cid, contact_id, recipient = await make_company(db, **kwargs)
    now = datetime.now(timezone.utc)
    msg_ids = {}
    for step in (1, 2, 3):
        res = await db.outreachmessages.insert_one({
            "companyId": cid,
            "contactId": contact_id,
            "step": step,
            "stepLabel": f"Step {step}",
            "status": "draft",
            "subject": f"Step {step} subject",
            "bodyHtml": f"<p>Step {step} body</p>",
            "bodyText": f"Step {step} body",
            "recipientEmail": recipient,
            "recipientName": "Asha Patel",
            "ccRecipients": [],
            "bccRecipients": [],
            "createdAt": now,
            "updatedAt": now,
        })
        msg_ids[step] = res.inserted_id
    return cid, contact_id, recipient, msg_ids


async def insert_record(db, cid, recipient, *, f1_status="PENDING", f1_at=None):
    now = datetime.now(timezone.utc)
    return await db.outreachrecords.insert_one({
        "companyId": cid,
        "companyName": "Email Sync Test Co",
        "recipientEmail": recipient,
        "initialEmail": {"status": "SENT", "sentAt": now - timedelta(days=1)},
        "followUp1": {"status": f1_status, "scheduledAt": f1_at or (now - timedelta(minutes=1))},
        "followUp2": {"status": "PENDING"},
        "replyStatus": "NO_REPLY",
        "campaignStatus": "INITIAL_SENT",
        "isTestSend": False,
        "createdAt": now,
        "updatedAt": now,
    })


# ---------------------------------------------------------------------------
# 1-2. Primary email: evidence-based, signed, conservative without evidence.
# ---------------------------------------------------------------------------
def test_build_primary_email_is_evidence_based_and_signed():
    company = {"companyName": "Ofload", "industry": "Logistics",
               "evidence": EVIDENCE, "recommendedService": SERVICE}
    contact = {"name": "Asha Patel", "email": "asha@ofload.example"}

    built = build_primary_email(company, contact, {"companyName": "TKSR Product Services"}, SERVICE)
    body = built["bodyText"]

    assert "Ofload" in built["subject"]
    assert SERVICE in built["subject"] or SERVICE in body
    assert "Hi Asha," in body
    assert "modernised its logistics operations" in body          # evidence embedded
    assert SERVICE in body                                        # recommended service exact
    assert "Nagendra Singh" in body
    assert "https://tksrproductservices.com/" in body
    assert "info@tksrproductservices.com" in body
    assert body.count("info@tksrproductservices.com") == 1        # single signature
    assert "no obligation" in body.lower()                        # low-pressure CTA
    for hype in ("revolutionize", "game-changing", "cutting-edge", "supercharge", "synergy"):
        assert hype not in body.lower()


def test_build_primary_email_conservative_without_evidence():
    company = {"companyName": "Quiet Co", "evidence": "", "recommendedService": "AI Strategy Consulting"}
    built = build_primary_email(company, {"name": "Sam", "email": "sam@quiet.example"}, None,
                                "AI Strategy Consulting")
    body = built["bodyText"]

    assert "Hi Sam," in body
    assert "AI Strategy Consulting" in body
    assert "info@tksrproductservices.com" in body
    # Conservative: no company-specific observation is invented.
    assert "noticed that" not in body.lower()
    assert "None" not in body
    assert built["subject"]


def test_sanitize_evidence_treats_placeholders_as_empty():
    for placeholder in ("None", "none", "N/A", "na", "-", "", None, "   "):
        assert sanitize_evidence(placeholder) == ""
    assert sanitize_evidence("  Real evidence  ") == "Real evidence"
    assert len(sanitize_evidence("x" * 500)) <= 320


def test_followup_copy_is_separate_from_primary():
    company = {"companyName": "Ofload", "evidence": EVIDENCE, "recommendedService": SERVICE}
    contact = {"name": "Asha Patel", "email": "asha@ofload.example"}

    step1 = build_primary_email(company, contact, None, SERVICE)
    step2 = build_followup_email(2, company, contact, None, SERVICE, EVIDENCE)
    step3 = build_followup_email(3, company, contact, None, SERVICE, EVIDENCE)

    assert step1["bodyText"] != step2["bodyText"]
    assert step2["bodyText"] != step3["bodyText"]
    # Step 2/3 must not reuse the Step 1 body.
    assert "I was looking into" not in step2["bodyText"]
    assert "I was looking into" not in step3["bodyText"]
    for s in (step1, step2, step3):
        assert "info@tksrproductservices.com" in s["bodyText"]


# ---------------------------------------------------------------------------
# 3. Generation requires Evidence + Recommended Service.
# ---------------------------------------------------------------------------
async def test_generation_requires_evidence_and_recommended_service(isolated_test_db):
    db = isolated_test_db
    cid, contact_id, _ = await make_company(db, name="No Evidence Co", evidence="")
    with pytest.raises(HTTPException) as ei:
        await generate_outreach_sequence(str(cid), {"contactId": str(contact_id)})
    assert ei.value.status_code == 400

    cid2, contact_id2, _ = await make_company(db, name="No Service Co", service="")
    with pytest.raises(HTTPException) as ei2:
        await generate_outreach_sequence(str(cid2), {"contactId": str(contact_id2)})
    assert ei2.value.status_code == 400


# ---------------------------------------------------------------------------
# 4. Generation output is signed + evidence grounded (deterministic fallback).
# ---------------------------------------------------------------------------
async def test_generation_evidence_based_and_signed_via_fallback(isolated_test_db):
    db = isolated_test_db
    cid, contact_id, _ = await make_company(db, name="Fallback Gen Co")

    with patch.object(osrv_mod, "call_ai", new=AsyncMock(side_effect=RuntimeError("no model"))):
        saved = await generate_outreach_sequence(str(cid), {"contactId": str(contact_id)})

    assert len(saved) == 3
    s1 = await db.outreachmessages.find_one({"companyId": cid, "step": 1})
    assert EVIDENCE in s1["bodyText"] or "modernised" in s1["bodyText"]
    assert SERVICE in s1["bodyText"]
    assert "info@tksrproductservices.com" in s1["bodyText"]
    assert s1["evidenceUsed"] == EVIDENCE
    assert s1["recommendedServiceUsed"] == SERVICE
    assert s1["isManuallyEdited"] is False


async def test_generation_normalizes_llm_output_with_canonical_signature(isolated_test_db):
    db = isolated_test_db
    cid, contact_id, _ = await make_company(db, name="LLM Gen Co")

    sequence = {"sequence": [
        {"step": 1, "stepLabel": "Step 1", "subject": "Evidence grounded subject",
         "bodyText": "Body one without any signature", "bodyHtml": "<p>Body one</p>",
         "linkedinNote": "note1", "linkedinInmail": "inmail1"},
        {"step": 2, "stepLabel": "Step 2", "subject": "Re: subject",
         "bodyText": "Body two", "bodyHtml": "<p>Body two</p>",
         "linkedinNote": "note2", "linkedinInmail": "inmail2"},
        {"step": 3, "stepLabel": "Step 3", "subject": "Closing",
         "bodyText": "Body three", "bodyHtml": "<p>Body three</p>",
         "linkedinNote": "note3", "linkedinInmail": "inmail3"},
    ]}

    with patch.object(osrv_mod, "get_ai_config", new=AsyncMock(return_value={"provider": "ollama", "model": "x"})), \
         patch.object(osrv_mod, "can_use_ai", new=lambda _cfg: True), \
         patch.object(osrv_mod, "call_ai", new=AsyncMock(return_value=sequence)):
        saved = await generate_outreach_sequence(str(cid), {"contactId": str(contact_id)})

    assert len(saved) == 3
    s1 = await db.outreachmessages.find_one({"companyId": cid, "step": 1})
    assert s1["subject"] == "Evidence grounded subject"
    assert "info@tksrproductservices.com" in s1["bodyText"]
    assert s1["bodyText"].count("info@tksrproductservices.com") == 1
    assert s1["evidenceUsed"] == EVIDENCE


# ---------------------------------------------------------------------------
# 5. Manual edits survive re-generation; regenerate is the explicit override.
# ---------------------------------------------------------------------------
async def test_generation_preserves_manually_edited_drafts(isolated_test_db):
    db = isolated_test_db
    cid, contact_id, _ = await make_company(db, name="Preserve Edit Co")

    with patch.object(osrv_mod, "call_ai", new=AsyncMock(side_effect=RuntimeError("no model"))):
        await generate_outreach_sequence(str(cid), {"contactId": str(contact_id)})

    s1 = await db.outreachmessages.find_one({"companyId": cid, "step": 1})
    updated, _sync = await update_outreach_message(
        str(s1["_id"]), {"subject": "MY CUSTOM SUBJECT", "bodyHtml": "<p>MY CUSTOM BODY</p>",
                         "bodyText": "MY CUSTOM BODY"}
    )
    assert updated["isManuallyEdited"] is True

    with patch.object(osrv_mod, "call_ai", new=AsyncMock(side_effect=RuntimeError("no model"))):
        await generate_outreach_sequence(str(cid), {"contactId": str(contact_id)})

    s1_after = await db.outreachmessages.find_one({"_id": s1["_id"]})
    assert s1_after["subject"] == "MY CUSTOM SUBJECT"
    assert "MY CUSTOM BODY" in s1_after["bodyText"]
    assert s1_after["isManuallyEdited"] is True

    # A draft that was NOT manually edited still gets the new signed content.
    s2_after = await db.outreachmessages.find_one({"companyId": cid, "step": 2})
    assert "info@tksrproductservices.com" in s2_after["bodyText"]


async def test_regenerate_only_for_unsent_step1(isolated_test_db):
    db = isolated_test_db
    cid, _contact_id, _recipient, msg_ids = await make_sequence(db, name="Regenerate Co")

    updated = await regenerate_outreach_message(str(msg_ids[1]), {"useAi": False})
    assert updated["isManuallyEdited"] is False
    assert updated.get("regeneratedAt")
    assert "info@tksrproductservices.com" in updated["bodyText"]
    assert updated["subject"] != "Step 1 subject"
    assert updated["recommendedServiceUsed"] == SERVICE

    with pytest.raises(HTTPException) as ei:
        await regenerate_outreach_message(str(msg_ids[2]))
    assert ei.value.status_code == 400

    await db.outreachmessages.update_one({"_id": msg_ids[1]}, {"$set": {"status": "sent"}})
    with pytest.raises(HTTPException) as ei2:
        await regenerate_outreach_message(str(msg_ids[1]))
    assert ei2.value.status_code == 400


# ---------------------------------------------------------------------------
# 6. Sent messages are immutable; recipient-only correction is allowed.
# ---------------------------------------------------------------------------
async def test_sent_message_content_immutable_recipient_correction_allowed(isolated_test_db):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    _cid, _contact_id, _recipient, msg_ids = await make_sequence(db, name="Sent Immutable Co")

    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]},
        {"$set": {"status": "sent", "sentAt": now, "subject": "Historical subject",
                  "bodyText": "Historical body"}},
    )

    with pytest.raises(HTTPException) as ei:
        await update_outreach_message(str(msg_ids[1]), {"subject": "changed"})
    assert ei.value.status_code == 400

    updated, _sync = await update_outreach_message(
        str(msg_ids[1]), {"recipientEmail": "corrected@newco.example"}
    )
    assert updated["recipientEmail"] == "corrected@newco.example"
    assert updated["subject"] == "Historical subject"
    assert updated["bodyText"] == "Historical body"


# ---------------------------------------------------------------------------
# 7. Sent Step 1 recipient change pauses follow-ups and never redirects.
# ---------------------------------------------------------------------------
async def test_sent_step1_recipient_change_pauses_followups(isolated_test_db):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    cid, _contact_id, recipient, msg_ids = await make_sequence(db, name="Pause After Send Co")

    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]}, {"$set": {"status": "sent", "sentAt": now - timedelta(days=1)}}
    )
    await db.outreachmessages.update_many(
        {"_id": {"$in": [msg_ids[2], msg_ids[3]]}},
        {"$set": {"status": "scheduled", "delayDays": 3, "scheduledAt": past}},
    )
    rec = await insert_record(db, cid, recipient, f1_at=past)

    updated, sync = await update_outreach_message(
        str(msg_ids[1]), {"recipientEmail": "corrected@newco.example"}
    )
    assert sync["paused"] >= 2
    assert updated["recipientEmail"] == "corrected@newco.example"

    for step in (2, 3):
        m = await db.outreachmessages.find_one({"_id": msg_ids[step]})
        assert m["status"] == "draft", "follow-up must be paused, not dispatched"
        assert m["requiresReview"] is True
        assert m["recipientChangedAfterSend"] is True
        assert m["recipientEmail"] == recipient, "old recipient must NOT be silently redirected"

    rec_after = await db.outreachrecords.find_one({"_id": rec.inserted_id})
    assert rec_after["followUp1"]["status"] == "REVIEW"
    assert rec_after["followUp2"]["status"] == "REVIEW"

    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails()
    send_mock.assert_not_awaited()
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "draft"


# ---------------------------------------------------------------------------
# 8. Unsent Step 1 recipient change syncs eligible unsent follow-ups.
# ---------------------------------------------------------------------------
async def test_unsent_step1_sync_preserves_copy_cc_bcc_schedule_and_status(isolated_test_db):
    db = isolated_test_db
    cid, _contact_id, _recipient, msg_ids = await make_sequence(db, name="Sync Followups Co")

    await schedule_sequence_steps(str(cid), [
        {"step": 1, "delayDays": 0},
        {"step": 2, "delayDays": 10},
        {"step": 3, "delayDays": 20},
    ])
    await db.outreachmessages.update_many(
        {"_id": {"$in": [msg_ids[2], msg_ids[3]]}},
        {"$set": {"ccRecipients": ["ops@tksr.example"], "bccRecipients": ["audit@tksr.example"]}},
    )
    before = {step: await db.outreachmessages.find_one({"_id": msg_ids[step]}) for step in (2, 3)}

    new_email = "new.contact@emailsync.example"
    updated, sync = await update_outreach_message(
        str(msg_ids[1]), {"recipientEmail": new_email, "recipientName": "New Contact"}
    )

    assert sync["updated"] == 2
    assert updated["status"] == "approved"               # status unchanged
    assert updated["isManuallyEdited"] is True

    for step in (2, 3):
        m = await db.outreachmessages.find_one({"_id": msg_ids[step]})
        b = before[step]
        assert m["recipientEmail"] == new_email
        assert m["recipientName"] == "New Contact"
        assert m["ccRecipients"] == b["ccRecipients"]    # CC preserved
        assert m["bccRecipients"] == b["bccRecipients"]  # BCC preserved
        assert m["subject"] == b["subject"]              # copy untouched
        assert m["bodyHtml"] == b["bodyHtml"]
        assert m["status"] == "scheduled"                # sequence state preserved
        assert m["delayDays"] == b["delayDays"]          # delay preserved
        assert m["scheduledAt"] == b["scheduledAt"]      # date preserved

    # An unsent sequence must not create a tracking record merely by editing.
    assert await db.outreachrecords.count_documents({"companyId": cid}) == 0


async def test_no_sync_when_recipient_unchanged(isolated_test_db):
    db = isolated_test_db
    _cid, _contact_id, _recipient, msg_ids = await make_sequence(db, name="No Sync Co")
    before2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})

    _updated, sync = await update_outreach_message(str(msg_ids[1]), {"subject": "Only subject changed"})
    assert sync["updated"] == 0

    after2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert after2["recipientEmail"] == before2["recipientEmail"]


# ---------------------------------------------------------------------------
# 9. The latest saved content is what gets dispatched.
# ---------------------------------------------------------------------------
async def test_latest_saved_content_is_used_at_dispatch(isolated_test_db):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    cid, _contact_id, recipient, msg_ids = await make_sequence(db, name="Latest Content Co")

    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]}, {"$set": {"status": "sent", "sentAt": now - timedelta(days=1)}}
    )
    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]}, {"$set": {"status": "scheduled", "delayDays": 1, "scheduledAt": past}}
    )
    await insert_record(db, cid, recipient, f1_at=past)

    # Edit the copy AFTER it was scheduled.
    await update_outreach_message(
        str(msg_ids[2]),
        {"subject": "LATEST SUBJECT", "bodyHtml": "<p>LATEST BODY</p>", "bodyText": "LATEST BODY"},
    )

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
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "sent"


# ---------------------------------------------------------------------------
# 10. Empty / "None" recipients are handled safely.
# ---------------------------------------------------------------------------
async def test_scheduled_message_with_none_recipient_fails_safely(isolated_test_db, block_real_smtp):
    db = isolated_test_db
    now = datetime.now(timezone.utc)
    past = now - timedelta(minutes=1)
    cid, _contact_id, _recipient, msg_ids = await make_sequence(db, name="Bad Recipient Co")

    # Legacy shape: Step 1 sent, Step 2 due with a literal "None" recipient.
    await db.outreachmessages.update_one(
        {"_id": msg_ids[1]}, {"$set": {"status": "sent", "sentAt": now - timedelta(days=1)}}
    )
    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]},
        {"$set": {"status": "scheduled", "delayDays": 1, "scheduledAt": past, "recipientEmail": "None"}},
    )
    await insert_record(db, cid, _recipient, f1_at=past)

    await process_scheduled_emails()

    # E8 validation runs before the transport, so nothing is transmitted.
    block_real_smtp.assert_not_awaited()
    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "failed"

    # Direct safety check for an empty recipient too.
    await db.outreachmessages.update_one(
        {"_id": msg_ids[3]},
        {"$set": {"status": "scheduled", "delayDays": 1, "scheduledAt": past, "recipientEmail": ""}},
    )
    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    with pytest.raises(HTTPException) as ei:
        await send_outreach_email(str(m3["_id"]))
    assert ei.value.status_code == 400
    block_real_smtp.assert_not_awaited()


async def test_recipient_sync_handles_none_and_invalid_safely(isolated_test_db):
    db = isolated_test_db
    _cid, _contact_id, _recipient, msg_ids = await make_sequence(db, name="Placeholder Sync Co")

    # All three steps carry a literal "None" recipient (legacy bad data).
    await db.outreachmessages.update_many(
        {"_id": {"$in": [msg_ids[1], msg_ids[2], msg_ids[3]]}},
        {"$set": {"recipientEmail": "None"}},
    )

    # Fixing Step 1 to a valid address synchronizes the follow-ups.
    _updated, sync = await update_outreach_message(
        str(msg_ids[1]), {"recipientEmail": "fixed@emailsync.example"}
    )
    assert sync["updated"] == 2
    for step in (2, 3):
        m = await db.outreachmessages.find_one({"_id": msg_ids[step]})
        assert m["recipientEmail"] == "fixed@emailsync.example"

    # An invalid new recipient is saved but never propagated.
    _updated2, sync2 = await update_outreach_message(
        str(msg_ids[1]), {"recipientEmail": "not-an-email"}
    )
    assert sync2["skippedInvalid"] is True
    for step in (2, 3):
        m = await db.outreachmessages.find_one({"_id": msg_ids[step]})
        assert m["recipientEmail"] == "fixed@emailsync.example"


# ---------------------------------------------------------------------------
# 11. Relationship-based sync repairs blank / placeholder follow-up recipients.
# ---------------------------------------------------------------------------
async def test_sync_repairs_blank_and_placeholder_followups(isolated_test_db):
    db = isolated_test_db
    cid, _contact_id, recipient, msg_ids = await make_sequence(db, name="Blank Followup Co")

    # Live-data shape: Step 1 valid, follow-ups unusable (blank / placeholder).
    other = recipient  # step1 keeps the valid address
    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]}, {"$set": {"recipientEmail": ""}},
    )
    await db.outreachmessages.update_one(
        {"_id": msg_ids[3]},
        {"$set": {
            "recipientEmail": "Not publicly available",
            "status": "scheduled",
            "delayDays": 6,
            "scheduledAt": datetime(2026, 10, 15, tzinfo=timezone.utc),
            "ccRecipients": ["ops@tksr.example"],
            "bccRecipients": ["audit@tksr.example"],
            "subject": "Step 3 keep me",
            "bodyHtml": "<p>Step 3 keep me</p>",
        }},
    )

    new_email = "fixed.blank@emailsync.example"
    _updated, sync = await update_outreach_message(
        str(msg_ids[1]), {"recipientEmail": new_email, "recipientName": "New Owner"}
    )

    assert sync["updated"] == 2
    assert sync["conflicts"] == []

    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["recipientEmail"] == new_email
    assert m2["recipientName"] == "New Owner"

    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert m3["recipientEmail"] == new_email
    # Recipient-only sync must preserve everything else.
    assert m3["status"] == "scheduled"
    assert m3["delayDays"] == 6
    assert m3["ccRecipients"] == ["ops@tksr.example"]
    assert m3["bccRecipients"] == ["audit@tksr.example"]
    assert m3["subject"] == "Step 3 keep me"
    assert m3["bodyHtml"] == "<p>Step 3 keep me</p>"
    assert other == recipient


async def test_sync_fixes_blank_step1_recipient(isolated_test_db):
    db = isolated_test_db
    _cid, _contact_id, _recipient, msg_ids = await make_sequence(db, name="Blank Step1 Co")

    # Blank Step 1 recipient used to short-circuit synchronization entirely.
    await db.outreachmessages.update_many(
        {"_id": {"$in": [msg_ids[1], msg_ids[2], msg_ids[3]]}},
        {"$set": {"recipientEmail": ""}},
    )

    _updated, sync = await update_outreach_message(
        str(msg_ids[1]), {"recipientEmail": "first.valid@emailsync.example"}
    )
    assert sync["updated"] == 2
    for step in (2, 3):
        m = await db.outreachmessages.find_one({"_id": msg_ids[step]})
        assert m["recipientEmail"] == "first.valid@emailsync.example"


# ---------------------------------------------------------------------------
# 12. A different *valid* recipient is a conflict: never silently overwritten.
# ---------------------------------------------------------------------------
async def test_sync_reports_conflict_and_pauses_armed_followup(isolated_test_db):
    db = isolated_test_db
    cid, _contact_id, recipient, msg_ids = await make_sequence(db, name="Conflict Sync Co")

    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]},
        {"$set": {
            "recipientEmail": "different.person@other.example",
            "status": "scheduled",
            "delayDays": 3,
            "scheduledAt": datetime(2026, 10, 12, tzinfo=timezone.utc),
            "ccRecipients": ["keep@tksr.example"],
            "subject": "Step 2 untouched",
            "bodyHtml": "<p>Step 2 untouched</p>",
        }},
    )

    new_email = "step1.new@emailsync.example"
    _updated, sync = await update_outreach_message(str(msg_ids[1]), {"recipientEmail": new_email})

    # Step 3 matched the old recipient -> synchronized; Step 2 is a conflict.
    assert sync["updated"] == 1
    assert len(sync["conflicts"]) == 1
    assert sync["conflicts"][0]["step"] == 2

    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["recipientEmail"] == "different.person@other.example"  # NOT overwritten
    assert m2["status"] == "draft"            # armed conflict paused for review
    assert m2["requiresReview"] is True
    assert m2["recipientConflict"] is True
    assert m2["previousRecipient"] == "different.person@other.example"
    assert m2["delayDays"] == 3               # schedule preserved
    assert m2["ccRecipients"] == ["keep@tksr.example"]
    assert m2["subject"] == "Step 2 untouched"
    assert m2["bodyHtml"] == "<p>Step 2 untouched</p>"

    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert m3["recipientEmail"] == new_email

    # A conflicting (draft-paused) message can never be auto-dispatched.
    with patch.object(sched_mod, "send_outreach_email", new=AsyncMock()) as send_mock:
        await process_scheduled_emails()
    send_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# 13. Sent history is never touched by sync.
# ---------------------------------------------------------------------------
async def test_sync_skips_sent_followups(isolated_test_db):
    db = isolated_test_db
    _cid, _contact_id, recipient, msg_ids = await make_sequence(db, name="Skip Sync Co")
    now = datetime.now(timezone.utc)

    await db.outreachmessages.update_one(
        {"_id": msg_ids[2]},
        {"$set": {"status": "sent", "sentAt": now, "subject": "sent history"}},
    )

    _updated, sync = await update_outreach_message(
        str(msg_ids[1]), {"recipientEmail": "new.recipient@emailsync.example"}
    )
    # Step 2 is sent (ineligible); Step 3 is still a draft (eligible).
    assert sync["updated"] == 1
    assert sync["conflicts"] == []

    m2 = await db.outreachmessages.find_one({"_id": msg_ids[2]})
    assert m2["status"] == "sent"
    assert m2["recipientEmail"] == recipient       # sent history untouched
    assert m2["subject"] == "sent history"

    m3 = await db.outreachmessages.find_one({"_id": msg_ids[3]})
    assert m3["recipientEmail"] == "new.recipient@emailsync.example"
    assert m3["status"] == "draft"


# ---------------------------------------------------------------------------
# 14. The API route surfaces recipientSync for sync, conflict and invalid.
# ---------------------------------------------------------------------------
async def test_route_surfaces_recipient_sync_updated_conflict_and_invalid(isolated_test_db):
    db = isolated_test_db

    # (a) successful synchronization is reported.
    _c1, _ct1, _r1, ids1 = await make_sequence(db, name="Route Sync Co")
    body = await update_message_route(
        str(ids1[1]), {"recipientEmail": "route.new@emailsync.example"}
    )
    assert body["success"] is True
    assert body["recipientSync"]["updated"] == 2
    assert "synchronized" in body["message"].lower()

    # (b) a conflicting valid follow-up is reported and not overwritten.
    _c2, _ct2, _r2, ids2 = await make_sequence(db, name="Route Conflict Co")
    await db.outreachmessages.update_one(
        {"_id": ids2[2]}, {"$set": {"recipientEmail": "route.other@emailsync.example"}}
    )
    body2 = await update_message_route(
        str(ids2[1]), {"recipientEmail": "route.new2@emailsync.example"}
    )
    assert body2["recipientSync"]["conflicts"]
    assert "different recipient" in body2["message"].lower() or "conflict" in body2["message"].lower()

    # (c) an invalid new recipient is reported as not synchronized.
    _c3, _ct3, _r3, ids3 = await make_sequence(db, name="Route Invalid Co")
    body3 = await update_message_route(str(ids3[1]), {"recipientEmail": "not-an-email"})
    assert body3["recipientSync"]["skippedInvalid"] is True
    assert "not a valid email" in body3["message"].lower()

    # (d) a plain content save carries no recipientSync signal.
    _c4, _ct4, _r4, ids4 = await make_sequence(db, name="Route Content Co")
    body4 = await update_message_route(str(ids4[1]), {"subject": "content only"})
    assert "recipientSync" not in body4


# ---------------------------------------------------------------------------
# 10. Production-shaped documents (the real runtime failure condition).
#     The live DB stores ObjectId company ids, integer steps, placeholder/blank
#     recipients, contact + evidence + schedule fields. Reproduce that shape and
#     the exact payload CompanyDetail.handleSaveDraft sends, then assert the
#     response contract the UI acts on.
# ---------------------------------------------------------------------------

_PROD_CONTACT = "Prasad Khadilkar"
_PROD_NEW_ADDR = "operator.newest@emailsync.example"
_PRESERVE_EXCEPT = {
    "recipientEmail", "recipientName", "updatedAt", "recipientSyncedFromStep1",
    "requiresReview", "previousRecipient", "recipientConflict", "recipientChangedAfterSend",
}


async def _insert_production_shaped_sequence(db, *, name, recipients):
    """Three draft messages shaped exactly like the live collection."""
    now = datetime.now(timezone.utc)
    cid, contact_id, _ = await make_company(db, name=name, recipient=recipients[1],
                                            contact_name=_PROD_CONTACT)
    ids = {}
    for step in (1, 2, 3):
        doc = {
            "companyId": cid,
            "contactId": contact_id,
            "step": step,                                   # int, as in production
            "stepLabel": f"Step {step}",
            "status": "draft",
            "subject": f"Step {step} subject",
            "bodyHtml": f"<p>Step {step} body</p>",
            "bodyText": f"Step {step} body",
            "recipientEmail": recipients[step],             # placeholder / blank / valid
            "recipientName": _PROD_CONTACT,
            "ccRecipients": [f"cc{step}@tksr.example"],
            "bccRecipients": [f"bcc{step}@tksr.example"],
            "isManuallyEdited": True,
            "evidenceUsed": EVIDENCE,
            "recommendedServiceUsed": SERVICE,
            "createdAt": now,
            "updatedAt": now,
        }
        if step != 1:
            doc["delayDays"] = step * 3
            doc["scheduledAt"] = datetime(2026, 10, 20, tzinfo=timezone.utc)
        ids[step] = (await db.outreachmessages.insert_one(doc)).inserted_id
    return cid, contact_id, ids


def _payload_for_step1():
    """Exactly the body CompanyDetail.handleSaveDraft builds for an unsent step."""
    return {
        "subject": "Step 1 subject",
        "bodyHtml": "<p>Step 1 body</p>",
        "bodyText": "Step 1 body",
        "recipientEmail": _PROD_NEW_ADDR,
        "recipientName": _PROD_CONTACT,
        "ccRecipients": ["cc1@tksr.example"],
        "bccRecipients": ["bcc1@tksr.example"],
        "focusService": SERVICE,
        "linkedinNote": "connection note",
        "linkedinInmail": "inmail body",
    }


async def test_production_shaped_step1_save_syncs_blank_and_placeholder_followups(isolated_test_db):
    db = isolated_test_db
    cid, contact_id, ids = await _insert_production_shaped_sequence(
        db, name="Prod Shape Sync Co",
        recipients={1: "Not publicly available", 2: "", 3: "Not publicly available"},
    )
    before = {s: await db.outreachmessages.find_one({"_id": ids[s]}) for s in (2, 3)}

    body = await update_message_route(str(ids[1]), _payload_for_step1())

    # Response contract the UI consumes (interceptor unwraps to this body).
    assert body["success"] is True
    assert body["data"]["_id"] == str(ids[1])
    sync = body["recipientSync"]
    assert sync == {"updated": 2, "paused": 0, "skippedInvalid": False, "conflicts": [],
                    "ccUpdated": 0}
    assert "2 unsent follow-up(s)" in body["message"]

    # Both blank and placeholder follow-ups were repaired to the new address.
    for s in (2, 3):
        m = await db.outreachmessages.find_one({"_id": ids[s]})
        assert m["recipientEmail"] == _PROD_NEW_ADDR
        assert m["recipientSyncedFromStep1"] is True
        assert m["recipientName"] == _PROD_CONTACT

        # ...and nothing else about the follow-up moved.
        changed = {k for k in set(before[s]) | set(m) if before[s].get(k) != m.get(k)}
        assert changed <= _PRESERVE_EXCEPT, f"step {s} changed {sorted(changed - _PRESERVE_EXCEPT)}"

    # Step 1 itself persisted with the same payload.
    step1 = await db.outreachmessages.find_one({"_id": ids[1]})
    assert step1["recipientEmail"] == _PROD_NEW_ADDR
    assert step1["isManuallyEdited"] is True
    assert step1["evidenceUsed"] == EVIDENCE
    assert step1["contactId"] == contact_id


async def test_production_shaped_conflict_and_invalid_recipient(isolated_test_db):
    db = isolated_test_db

    # (a) a different VALID follow-up recipient is a conflict and is never
    #     overwritten; the placeholder follow-up is still synchronized.
    cid, _ct, ids = await _insert_production_shaped_sequence(
        db, name="Prod Shape Conflict Co",
        recipients={1: "Not publicly available", 2: "different.valid@other.example",
                    3: "Not publicly available"},
    )
    body = await update_message_route(str(ids[1]), _payload_for_step1())

    assert body["recipientSync"]["updated"] == 1
    assert [c["step"] for c in body["recipientSync"]["conflicts"]] == [2]
    assert "different recipient" in body["message"].lower()

    m2 = await db.outreachmessages.find_one({"_id": ids[2]})
    assert m2["recipientEmail"] == "different.valid@other.example"   # never overwritten
    assert m2["requiresReview"] is True
    assert m2["recipientConflict"] is True
    assert m2["previousRecipient"] == "different.valid@other.example"

    m3 = await db.outreachmessages.find_one({"_id": ids[3]})
    assert m3["recipientEmail"] == _PROD_NEW_ADDR
    assert m3["status"] == "draft"

    # (b) an invalid new address is saved on Step 1 but never propagated.
    cid2, _ct2, ids2 = await _insert_production_shaped_sequence(
        db, name="Prod Shape Invalid Co",
        recipients={1: "Not publicly available", 2: "", 3: "Not publicly available"},
    )
    before2 = {s: await db.outreachmessages.find_one({"_id": ids2[s]}) for s in (2, 3)}
    bad = _payload_for_step1()
    bad["recipientEmail"] = "not-an-email"
    body2 = await update_message_route(str(ids2[1]), bad)

    assert body2["recipientSync"] == {"updated": 0, "paused": 0,
                                      "skippedInvalid": True, "conflicts": [],
                                      "ccUpdated": 0}
    assert "not a valid email" in body2["message"].lower()
    assert (await db.outreachmessages.find_one({"_id": ids2[1]}))["recipientEmail"] == "not-an-email"
    for s in (2, 3):
        m = await db.outreachmessages.find_one({"_id": ids2[s]})
        assert m["recipientEmail"] == before2[s]["recipientEmail"]     # unchanged
        assert m["recipientEmail"] != "not-an-email"


# ---------------------------------------------------------------------------
# 11. Step 1 CC synchronization onto unsent Step 2/3 follow-ups.
#     Only `ccRecipients` moves: each follow-up keeps its own subject, HTML and
#     plain-text body, its primary recipient + name, its BCC, its status, its
#     delays and its schedule. Sent rows are never eligible.
# ---------------------------------------------------------------------------

def _cc_only_payload(step1: dict, cc: list) -> dict:
    """Exactly the body CompanyDetail.handleSaveDraft builds for an unsent step,
    with the operator having touched ONLY the CC list (recipient, subject and
    body are echoed back unchanged, as the editor does)."""
    return {
        "subject": step1["subject"],
        "bodyHtml": step1["bodyHtml"],
        "bodyText": step1["bodyText"],
        "recipientEmail": step1["recipientEmail"],
        "recipientName": step1.get("recipientName"),
        "ccRecipients": cc,
        "bccRecipients": step1.get("bccRecipients") or [],
        "focusService": SERVICE,
        "linkedinNote": "connection note",
        "linkedinInmail": "inmail body",
    }


async def _cc_sequence(db, *, name):
    """Production-shaped sequence where all three steps share one recipient."""
    recipient = f"{name.lower().replace(' ', '.')}@tksr.example"
    return await _insert_production_shaped_sequence(
        db, name=name,
        recipients={1: recipient, 2: recipient, 3: recipient},
    )


async def test_step1_cc_save_synchronizes_followups_and_preserves_everything_else(isolated_test_db):
    db = isolated_test_db
    _cid, _ct, ids = await _cc_sequence(db, name="CC Sync Co")
    step1 = await db.outreachmessages.find_one({"_id": ids[1]})
    before = {s: await db.outreachmessages.find_one({"_id": ids[s]}) for s in (2, 3)}

    new_cc = ["legal@tksr.example", "ops@tksr.example"]
    body = await update_message_route(str(ids[1]), _cc_only_payload(step1, new_cc))

    # The UI acts on this exact contract (interceptor unwraps to this body).
    sync = body["recipientSync"]
    assert sync == {"updated": 0, "paused": 0, "skippedInvalid": False,
                    "conflicts": [], "ccUpdated": 2}
    assert "CC recipients synchronized to 2 unsent follow-up(s)" in body["message"]

    # Step 1 persisted its own update.
    step1_after = await db.outreachmessages.find_one({"_id": ids[1]})
    assert step1_after["ccRecipients"] == new_cc
    assert step1_after["isManuallyEdited"] is True
    assert step1_after["subject"] == step1["subject"]

    for s in (2, 3):
        m = await db.outreachmessages.find_one({"_id": ids[s]})
        # Each follow-up keeps its own content, recipient and recipient name.
        assert m["subject"] == before[s]["subject"]
        assert m["bodyHtml"] == before[s]["bodyHtml"]
        assert m["bodyText"] == before[s]["bodyText"]
        assert m["recipientEmail"] == before[s]["recipientEmail"]
        assert m["recipientName"] == before[s]["recipientName"]
        # BCC is never synchronized, and the arm/schedule state is untouched.
        assert m["bccRecipients"] == before[s]["bccRecipients"]
        assert m["status"] == before[s]["status"]
        assert m["delayDays"] == before[s]["delayDays"]
        assert m["scheduledAt"] == before[s]["scheduledAt"]
        assert m["ccRecipients"] == new_cc
        # Nothing beyond the CC list and the freshness stamp may move.
        changed = {k for k in set(before[s]) | set(m) if before[s].get(k) != m.get(k)}
        assert changed <= {"ccRecipients", "updatedAt"}, f"step {s} changed {sorted(changed)}"


async def test_step1_cc_sync_dedupes_and_normalizes_case_insensitively(isolated_test_db):
    db = isolated_test_db
    _cid, _ct, ids = await _cc_sequence(db, name="CC Dedupe Co")
    step1 = await db.outreachmessages.find_one({"_id": ids[1]})

    # The same mailbox three times (case + whitespace variants) plus one new one.
    messy = [" Ops@tksr.example ", "ops@TKSR.example", "ops@tksr.example",
             "legal@tksr.example"]
    expected = ["ops@tksr.example", "legal@tksr.example"]   # first occurrence, lower-cased

    body = await update_message_route(str(ids[1]), _cc_only_payload(step1, messy))

    assert body["recipientSync"]["ccUpdated"] == 2
    assert (await db.outreachmessages.find_one({"_id": ids[1]}))["ccRecipients"] == expected
    for s in (2, 3):
        m = await db.outreachmessages.find_one({"_id": ids[s]})
        assert m["ccRecipients"] == expected
        assert len({a.lower() for a in m["ccRecipients"]}) == len(m["ccRecipients"])


async def test_step1_save_with_unchanged_cc_touches_no_followup(isolated_test_db):
    db = isolated_test_db
    _cid, _ct, ids = await _cc_sequence(db, name="CC Unchanged Co")
    step1 = await db.outreachmessages.find_one({"_id": ids[1]})
    before = {s: await db.outreachmessages.find_one({"_id": ids[s]}) for s in (2, 3)}

    # The editor always posts ccRecipients; here only the case form differs
    # (a legacy mixed-case entry) — that is not a change and must not churn
    # a single follow-up row.
    same = [a.upper() for a in step1["ccRecipients"]]
    body = await update_message_route(str(ids[1]), _cc_only_payload(step1, same))

    assert "recipientSync" not in body          # no sync signal to act on
    assert body["message"] == "Draft updated successfully"
    for s in (2, 3):
        m = await db.outreachmessages.find_one({"_id": ids[s]})
        assert m == before[s], f"step {s} was rewritten despite an unchanged CC"


async def test_step1_recipient_and_cc_change_synchronize_together(isolated_test_db):
    db = isolated_test_db
    _cid, _ct, ids = await _insert_production_shaped_sequence(
        db, name="CC And Recipient Co",
        recipients={1: "Not publicly available", 2: "", 3: "Not publicly available"},
    )
    before = {s: await db.outreachmessages.find_one({"_id": ids[s]}) for s in (2, 3)}

    payload = _payload_for_step1()
    payload["recipientEmail"] = "paired.newest@emailsync.example"
    payload["ccRecipients"] = ["legal@tksr.example"]

    body = await update_message_route(str(ids[1]), payload)

    # Existing recipient synchronization still works — alongside the CC sync.
    sync = body["recipientSync"]
    assert sync == {"updated": 2, "paused": 0, "skippedInvalid": False,
                    "conflicts": [], "ccUpdated": 2}
    assert "synchronized to the new recipient" in body["message"]
    assert "CC recipients synchronized" in body["message"]

    for s in (2, 3):
        m = await db.outreachmessages.find_one({"_id": ids[s]})
        assert m["recipientEmail"] == "paired.newest@emailsync.example"
        assert m["recipientName"] == _PROD_CONTACT
        assert m["ccRecipients"] == ["legal@tksr.example"]
        assert m["bccRecipients"] == before[s]["bccRecipients"]      # BCC never moves
        assert m["subject"] == before[s]["subject"]
        assert m["bodyHtml"] == before[s]["bodyHtml"]
        assert m["bodyText"] == before[s]["bodyText"]


async def test_cc_edit_alone_never_raises_recipient_conflicts(isolated_test_db):
    db = isolated_test_db
    # Step 2 already carries a DIFFERENT valid recipient (a standing conflict
    # candidate). A CC-only save must not touch recipients at all, so no
    # conflict may be raised and nothing may be paused.
    _cid, _ct, ids = await _insert_production_shaped_sequence(
        db, name="CC Only Conflict Co",
        recipients={1: "cc.owner@tksr.example", 2: "different.valid@other.example",
                    3: "cc.owner@tksr.example"},
    )
    step1 = await db.outreachmessages.find_one({"_id": ids[1]})

    body = await update_message_route(str(ids[1]), _cc_only_payload(step1, ["legal@tksr.example"]))

    sync = body["recipientSync"]
    assert sync == {"updated": 0, "paused": 0, "skippedInvalid": False,
                    "conflicts": [], "ccUpdated": 2}
    m2 = await db.outreachmessages.find_one({"_id": ids[2]})
    assert m2["recipientEmail"] == "different.valid@other.example"
    assert "recipientConflict" not in m2 and "requiresReview" not in m2
    assert m2["ccRecipients"] == ["legal@tksr.example"]   # CC still mirrors Step 1


async def test_cc_sync_never_overwrites_a_conflicting_followup_recipient(isolated_test_db):
    db = isolated_test_db
    _cid, _ct, ids = await _insert_production_shaped_sequence(
        db, name="CC Conflict Recipient Co",
        recipients={1: "cc.owner@tksr.example", 2: "different.valid@other.example",
                    3: "cc.owner@tksr.example"},
    )
    step1 = await db.outreachmessages.find_one({"_id": ids[1]})
    before3 = await db.outreachmessages.find_one({"_id": ids[3]})

    payload = _cc_only_payload(step1, ["legal@tksr.example"])
    payload["recipientEmail"] = "changed.owner@tksr.example"

    body = await update_message_route(str(ids[1]), payload)

    sync = body["recipientSync"]
    assert sync["updated"] == 1                                   # only Step 3 followed
    assert [c["step"] for c in sync["conflicts"]] == [2]
    assert sync["ccUpdated"] == 2
    assert "different recipient" in body["message"].lower()

    m2 = await db.outreachmessages.find_one({"_id": ids[2]})
    assert m2["recipientEmail"] == "different.valid@other.example"  # never overwritten
    assert m2["recipientConflict"] is True
    assert m2["requiresReview"] is True
    assert m2["ccRecipients"] == ["legal@tksr.example"]             # CC still mirrors Step 1
    assert m2["status"] == "draft"

    m3 = await db.outreachmessages.find_one({"_id": ids[3]})
    assert m3["recipientEmail"] == "changed.owner@tksr.example"
    assert m3["ccRecipients"] == ["legal@tksr.example"]
    assert m3["subject"] == before3["subject"]


async def test_cc_sync_skips_sent_followups(isolated_test_db):
    db = isolated_test_db
    _cid, _ct, ids = await _cc_sequence(db, name="CC Skip Co")
    now = datetime.now(timezone.utc)
    await db.outreachmessages.update_one(
        {"_id": ids[2]},
        {"$set": {"status": "sent", "sentAt": now, "subject": "sent history"}},
    )
    step1 = await db.outreachmessages.find_one({"_id": ids[1]})
    before2 = await db.outreachmessages.find_one({"_id": ids[2]})

    _updated, sync = await update_outreach_message(
        str(ids[1]), _cc_only_payload(step1, ["legal@tksr.example"])
    )

    # Step 2 is sent (ineligible); Step 3 is still a draft and is synchronized.
    assert sync["ccUpdated"] == 1
    assert sync["updated"] == 0 and sync["paused"] == 0 and sync["conflicts"] == []

    m2 = await db.outreachmessages.find_one({"_id": ids[2]})
    assert m2 == before2                                   # sent history untouched
    assert m2["status"] == "sent"

    m3 = await db.outreachmessages.find_one({"_id": ids[3]})
    assert m3["ccRecipients"] == ["legal@tksr.example"]
    assert m3["status"] == "draft"
