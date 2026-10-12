"""
Future Import Quarantine & Multi-Layer Safety Regression Suite.

Verifies the 10 critical security and safety invariants identified in the audit:
1. Newly generated Step 2 and Step 3 messages default to quarantined: True.
2. Newly generated Step 1 messages default to quarantined: False (or unquarantined draft).
3. Import batch identity is derived stably (importBatchId -> quarantine-import-{id}, or quarantine-{cid}).
4. Re-running generation does not clear an authorized release (quarantined == False preserved).
5. Direct send route rejects newly quarantined messages with HTTP 409.
6. Step 1 dispatch activates drip record but does NOT arm quarantined follow-ups (remains PENDING, no scheduledAt).
7. Background scheduler skips/refuses quarantined messages even if manually placed in status="scheduled".
8. Quarantine release works correctly on future-imported messages, leaving them as unquarantined drafts.
9. Domain mismatch between recipient and company website is correctly flagged or enforced.
10. Contact name and greeting continuity anomalies are non-destructively flagged in reviewReasons.

Safety constraints:
- Uses isolated disposable test DB: ai_client_outreach_test_future_quarantine
- Mocked SMTP: zero network connections, zero emails sent.
- Zero mutation of production DB or batch quarantine-20261009.
"""

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
import pytest
from bson import ObjectId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

import app.config.database as db_module
from app.services.outreach_service import generate_outreach_sequence
from app.services.send_guard import (
    is_message_quarantined,
    check_recipient_domain_alignment,
    check_contact_and_greeting_consistency,
    assert_domain_match_if_enforced,
)
from app.services.email_service import send_outreach_email
from app.services.scheduler_service import (
    schedule_sequence_steps,
    _dispatch_scheduled_message,
    process_scheduled_emails,
)
from app.services.outreach_tracking_service import activate_followups_on_send
from app.services.quarantine_service import (
    release_quarantined_message_service,
    QuarantineReleaseRequest,
)

TEST_DB_NAME = "ai_client_outreach_test_future_quarantine"
TEST_ADMIN_KEY = "test-future-quarantine-admin-key-2026"


@pytest.fixture(scope="module", autouse=True)
async def isolated_test_db():
    assert TEST_DB_NAME != "ai_client_outreach", "Safety violation: test DB cannot be production DB"
    client = AsyncIOMotorClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000)
    test_db = client[TEST_DB_NAME]
    await client.drop_database(TEST_DB_NAME)
    prev_db, prev_client = db_module.db, db_module.client
    db_module.db = test_db
    db_module.client = client
    try:
        yield test_db
    finally:
        await client.drop_database(TEST_DB_NAME)
        db_module.db = prev_db
        db_module.client = prev_client


@pytest.fixture(autouse=True)
def mock_smtp_guard():
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mocked_send:
        mocked_send.side_effect = RuntimeError("SAFETY ERROR: SMTP attempted during tests!")
        yield mocked_send


@pytest.fixture(autouse=True)
def mock_llm_generation():
    """Mock can_use_ai to return False so generation uses fast, deterministic fallback templates."""
    with patch("app.services.outreach_service.can_use_ai", return_value=False):
        yield


# ---------------------------------------------------------------------------
# Test 1 & 2: Steps 2 and 3 default to quarantined; Step 1 is unquarantined
# ---------------------------------------------------------------------------
async def test_new_generation_defaults_followups_to_quarantined(isolated_test_db):
    db = isolated_test_db
    cid = ObjectId()
    await db.companies.insert_one({
        "_id": cid,
        "name": "Acme Logistics",
        "website": "https://acmelogistics.com",
        "email": "contact@acmelogistics.com",
        "evidence": "Expanded fleet by 40 vehicles",
        "recommendedService": "Fleet Dispatch AI",
        "decisionMaker": {"name": "Alice Smith", "title": "COO", "email": "alice@acmelogistics.com"},
        "importBatchId": "batch-2026-xyz",
    })

    messages = await generate_outreach_sequence(str(cid), options={"force_regenerate": True})
    assert len(messages) == 3

    step1 = await db.outreachmessages.find_one({"companyId": cid, "step": 1})
    step2 = await db.outreachmessages.find_one({"companyId": cid, "step": 2})
    step3 = await db.outreachmessages.find_one({"companyId": cid, "step": 3})

    # Step 1 is draft and NOT quarantined
    assert step1["status"] == "draft"
    assert step1.get("quarantined") is False or step1.get("quarantined") is None

    # Step 2 & 3 are quarantined drafts
    assert step2["status"] == "draft"
    assert step2.get("quarantined") is True
    assert step2["quarantine"]["active"] is True
    assert step2["quarantine"]["batch"] == "quarantine-import-batch-2026-xyz"
    assert is_message_quarantined(step2) is True

    assert step3["status"] == "draft"
    assert step3.get("quarantined") is True
    assert step3["quarantine"]["active"] is True
    assert step3["quarantine"]["batch"] == "quarantine-import-batch-2026-xyz"
    assert is_message_quarantined(step3) is True


# ---------------------------------------------------------------------------
# Test 3: Stable batch identity derivation
# ---------------------------------------------------------------------------
async def test_stable_batch_identity_derivation(isolated_test_db):
    db = isolated_test_db
    # Case A: Company with importBatchId
    cid_a = ObjectId()
    await db.companies.insert_one({
        "_id": cid_a,
        "name": "Beta Freight",
        "website": "https://betafreight.com",
        "email": "ops@betafreight.com",
        "evidence": "New shipping hubs opened",
        "recommendedService": "Hub AI",
        "importBatchId": "batch-alpha-99",
    })
    await generate_outreach_sequence(str(cid_a))
    s2_a = await db.outreachmessages.find_one({"companyId": cid_a, "step": 2})
    assert s2_a["quarantine"]["batch"] == "quarantine-import-batch-alpha-99"

    # Case B: Company without importBatchId -> uses quarantine-{companyId}
    cid_b = ObjectId()
    await db.companies.insert_one({
        "_id": cid_b,
        "name": "Gamma Courier",
        "website": "https://gammacourier.com",
        "email": "ops@gammacourier.com",
        "evidence": "Acquired regional carrier",
        "recommendedService": "Route Optimization AI",
    })
    await generate_outreach_sequence(str(cid_b))
    s2_b = await db.outreachmessages.find_one({"companyId": cid_b, "step": 2})
    assert s2_b["quarantine"]["batch"] == f"quarantine-{str(cid_b)}"


# ---------------------------------------------------------------------------
# Test 4: Re-generation preserves authorized release
# ---------------------------------------------------------------------------
async def test_regeneration_preserves_authorized_release(isolated_test_db):
    db = isolated_test_db
    cid = ObjectId()
    await db.companies.insert_one({
        "_id": cid,
        "name": "Delta Delivery",
        "website": "https://deltadelivery.com",
        "email": "team@deltadelivery.com",
        "evidence": "High manual order processing time",
        "recommendedService": "Automated Order AI",
        "importBatchId": "batch-delta",
    })
    await generate_outreach_sequence(str(cid))
    s2 = await db.outreachmessages.find_one({"companyId": cid, "step": 2})
    assert s2["quarantined"] is True

    # Simulate authorized release
    await db.outreachmessages.update_one(
        {"_id": s2["_id"]},
        {"$set": {
            "quarantined": False,
            "quarantineReleased": {
                "releasedAt": datetime.now(timezone.utc),
                "releasedBy": "admin",
                "releaseReason": "Approved after human review",
            }
        }}
    )

    # Re-generate sequence for company
    await generate_outreach_sequence(str(cid), options={"force_regenerate": True})
    s2_updated = await db.outreachmessages.find_one({"_id": s2["_id"]})
    assert s2_updated["quarantined"] is False, "Authorized release must be preserved upon re-generation"
    assert "quarantineReleased" in s2_updated


# ---------------------------------------------------------------------------
# Test 5: Direct send route rejects newly quarantined messages with HTTP 409
# ---------------------------------------------------------------------------
async def test_direct_send_route_rejects_quarantined_message(isolated_test_db):
    db = isolated_test_db
    cid = ObjectId()
    await db.companies.insert_one({
        "_id": cid,
        "name": "Epsilon Corp",
        "website": "https://epsiloncorp.com",
        "email": "info@epsiloncorp.com",
        "evidence": "Growing supply chain operations",
        "recommendedService": "Supply Chain Copilot",
    })
    await generate_outreach_sequence(str(cid))
    s2 = await db.outreachmessages.find_one({"companyId": cid, "step": 2})

    with pytest.raises(HTTPException) as exc:
        await send_outreach_email(str(s2["_id"]))
    assert exc.value.status_code == 409
    assert "quarantined" in exc.value.detail.lower()

    # Verify message remains untouched in draft and quarantined state
    s2_after = await db.outreachmessages.find_one({"_id": s2["_id"]})
    assert s2_after["status"] == "draft"
    assert s2_after["quarantined"] is True


# ---------------------------------------------------------------------------
# Test 6: Step 1 dispatch activates drip record but does NOT arm follow-ups
# ---------------------------------------------------------------------------
async def test_step1_send_does_not_arm_quarantined_followups(isolated_test_db):
    db = isolated_test_db
    cid = ObjectId()
    rec_email = "lead@zetatransport.com"
    await db.companies.insert_one({
        "_id": cid,
        "name": "Zeta Transport",
        "website": "https://zetatransport.com",
        "email": rec_email,
        "evidence": "Operating in 5 states",
        "recommendedService": "Logistics AI",
    })
    await generate_outreach_sequence(str(cid))
    s1 = await db.outreachmessages.find_one({"companyId": cid, "step": 1})
    s2 = await db.outreachmessages.find_one({"companyId": cid, "step": 2})
    s3 = await db.outreachmessages.find_one({"companyId": cid, "step": 3})

    now = datetime.now(timezone.utc)
    # Simulate Step 1 sent
    await db.outreachmessages.update_one({"_id": s1["_id"]}, {"$set": {"status": "sent", "sentAt": now}})

    tracking_record = {
        "companyId": cid,
        "recipientEmail": rec_email,
        "initialEmail": {"status": "SENT", "sentAt": now},
        "followUp1": {"status": "PENDING"},
        "followUp2": {"status": "PENDING"},
    }

    # Call activate_followups_on_send
    updated_rec = await activate_followups_on_send(tracking_record, db, cid, rec_email, now)

    # Follow-ups must NOT receive scheduledAt in the record
    assert updated_rec["followUp1"].get("scheduledAt") is None
    assert updated_rec["followUp2"].get("scheduledAt") is None

    # Messages in DB must remain draft and quarantined, never status='scheduled'
    s2_check = await db.outreachmessages.find_one({"_id": s2["_id"]})
    s3_check = await db.outreachmessages.find_one({"_id": s3["_id"]})
    assert s2_check["status"] == "draft"
    assert s2_check.get("scheduledAt") is None
    assert s2_check["quarantined"] is True

    assert s3_check["status"] == "draft"
    assert s3_check.get("scheduledAt") is None
    assert s3_check["quarantined"] is True


# ---------------------------------------------------------------------------
# Test 7: Scheduler skips/refuses quarantined messages
# ---------------------------------------------------------------------------
async def test_scheduler_refuses_quarantined_messages(isolated_test_db):
    db = isolated_test_db
    cid = ObjectId()
    mid = ObjectId()
    now = datetime.now(timezone.utc)

    # Malicious or corrupted document: status is 'scheduled' but quarantined is True
    await db.outreachmessages.insert_one({
        "_id": mid,
        "companyId": cid,
        "step": 2,
        "recipientEmail": "ceo@etaenterprises.com",
        "subject": "Quick follow up",
        "status": "scheduled",
        "scheduledAt": now - timedelta(hours=1),
        "quarantined": True,
        "quarantine": {"active": True, "batch": "quarantine-eta"},
    })

    # Test _dispatch_scheduled_message hard stop
    msg_doc = await db.outreachmessages.find_one({"_id": mid})
    result = await _dispatch_scheduled_message(msg_doc, now)
    assert result == "quarantined"

    # Message must not have been claimed or transitioned to 'sending' or 'sent'
    after_dispatch = await db.outreachmessages.find_one({"_id": mid})
    assert after_dispatch["status"] == "scheduled"
    assert after_dispatch["quarantined"] is True


# ---------------------------------------------------------------------------
# Test 8: Quarantine release works and leaves message as unquarantined draft
# ---------------------------------------------------------------------------
async def test_quarantine_release_leaves_message_as_draft(isolated_test_db):
    db = isolated_test_db
    cid = ObjectId()
    mid = ObjectId()
    batch_name = "quarantine-theta"

    await db.outreachmessages.insert_one({
        "_id": mid,
        "companyId": cid,
        "step": 2,
        "recipientEmail": "director@thetaservices.com",
        "subject": "Follow up regarding automation",
        "bodyText": "Hello Director...",
        "bodyHtml": "<p>Hello Director...</p>",
        "status": "draft",
        "quarantined": True,
        "quarantine": {"active": True, "batch": batch_name, "reason": "new_import_safety_review"},
    })

    payload = QuarantineReleaseRequest(
        confirmMessageId=str(mid),
        expectedBatch=batch_name,
        reason="Manual security verification complete",
        actor="auditor",
    )

    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_ADMIN_KEY}):
        res = await release_quarantined_message_service(str(mid), payload, TEST_ADMIN_KEY)

    assert res["success"] is True
    released_doc = await db.outreachmessages.find_one({"_id": mid})
    assert released_doc["quarantined"] is False
    assert released_doc["status"] == "draft", "Released message must remain DRAFT, never armed"
    assert released_doc.get("scheduledAt") is None
    assert released_doc["quarantineReleased"]["releaseReason"] == "Manual security verification complete"

    # Verify audit log entry
    audit = await db.quarantine_audit_logs.find_one({"messageId": str(mid)})
    assert audit is not None
    assert audit["action"] == "RELEASE_QUARANTINE"


# ---------------------------------------------------------------------------
# Test 9: Domain mismatch checks and enforcement
# ---------------------------------------------------------------------------
def test_domain_alignment_and_enforcement():
    # Matching domain
    m1 = check_recipient_domain_alignment("john@acme.com", "https://acme.com")
    assert m1["aligned"] is True

    # Subdomain match
    m2 = check_recipient_domain_alignment("john@corp.acme.com", "https://acme.com")
    assert m2["aligned"] is True

    # Public webmail provider is permitted
    m3 = check_recipient_domain_alignment("founder@gmail.com", "https://mystartup.io")
    assert m3["aligned"] is True
    assert m3["matchType"] == "public_webmail"

    # Domain mismatch
    m4 = check_recipient_domain_alignment("john@wrongdomain.com", "https://acme.com")
    assert m4["aligned"] is False
    assert m4["matchType"] == "domain_mismatch"

    # Enforcement test with env var
    with patch.dict(os.environ, {"ENFORCE_RECIPIENT_DOMAIN_MATCH": "true"}):
        with pytest.raises(HTTPException) as exc:
            assert_domain_match_if_enforced("john@wrongdomain.com", "https://acme.com")
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Test 10: Non-destructive contact and greeting consistency checks
# ---------------------------------------------------------------------------
def test_contact_and_greeting_consistency_checks():
    # Clean case
    c1 = check_contact_and_greeting_consistency(
        recipient_name="Sarah Connor",
        greeting="Hi Sarah",
        step1_greeting="Hi Sarah"
    )
    assert c1["valid"] is True
    assert len(c1["findings"]) == 0

    # Suspicious organization / location token in name
    c2 = check_contact_and_greeting_consistency(
        recipient_name="Altona North",
        greeting="Hi Altona North",
        step1_greeting="Hi Altona North"
    )
    assert c2["valid"] is False
    assert c2["suspiciousName"] is True
    assert any("organizational/location tokens" in f for f in c2["findings"])

    # Greeting discontinuity across sequence steps
    c3 = check_contact_and_greeting_consistency(
        recipient_name="David Miller",
        greeting="Hi David",
        step1_greeting="Hello Mr. Miller"
    )
    assert c3["valid"] is False
    assert c3["greetingDiscontinuity"] is True
    assert any("differs from Step 1 greeting" in f for f in c3["findings"])
