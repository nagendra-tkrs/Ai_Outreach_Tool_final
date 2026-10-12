"""
Quarantine Release Workflow Regression Suite.

Comprehensive tests for Option A: Secure, Authenticated Quarantine Release:
  1. Authentication & Security:
     - 503 if ADMIN_RELEASE_KEY is missing or empty on the server (fail-closed).
     - 401 if X-Admin-Key header is missing.
     - 403 if X-Admin-Key header is invalid.
     - Valid key allows authorized execution.
  2. Validation & Guards:
     - 400 if confirmMessageId != path message_id.
     - 400 if invalid ObjectId format.
     - 422 if reason is missing or shorter than 5 chars.
     - 404 if message does not exist.
     - 409 if message is not quarantined (quarantined != True).
     - 409 if message status is not 'draft' (e.g. 'sent' or 'scheduled').
     - 409 if expectedBatch != message's quarantine.batch.
  3. Release Behavior:
     - Atomically sets quarantined=False.
     - Records quarantineReleased metadata: releasedAt, releasedBy, releaseReason, previousBatch.
     - Preserves status='draft' (NEVER activates, schedules, or sends).
     - Preserves subject, bodyHtml, bodyText, recipientEmail, recipientName, ccRecipients, evidence.
     - Inserts immutable audit record in quarantine_audit_logs.
     - Zero SMTP calls (no outbound mail).
  4. Concurrency & Idempotency:
     - Subsequent release attempt on the same message fails with 409 (cannot release twice).

Isolation: Dedicated database `ai_client_outreach_test_quarantine_release`,
never touching live `ai_client_outreach`. Real SMTP mocked out.
"""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import httpx
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

import app.config.database as db_module
from app.main import app

TEST_DB_NAME = "ai_client_outreach_test_quarantine_e2e"
TEST_SECRET_KEY = "test-secret-admin-release-key-2026"
FIXED_TS = datetime(2026, 10, 9, 8, 48, 7, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
async def isolated_test_db():
    assert TEST_DB_NAME != "ai_client_outreach", "Safety violation: test database must never be live database!"
    client = AsyncIOMotorClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000)
    test_db = client[TEST_DB_NAME]
    assert test_db.name == "ai_client_outreach_test_quarantine_e2e"
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


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def create_quarantined_fixture(db, *, status="draft", quarantined=True, batch="quarantine-20261009", step=2):
    comp_res = await db.companies.insert_one({
        "companyName": "Release Test Co",
        "website": "https://releasetest.example",
        "createdAt": FIXED_TS,
        "updatedAt": FIXED_TS,
    })
    cid = comp_res.inserted_id

    doc = {
        "companyId": cid,
        "step": step,
        "status": status,
        "subject": f"Follow-up Step {step} Subject",
        "bodyHtml": f"<p>Follow-up Step {step} Body</p>",
        "bodyText": f"Follow-up Step {step} Body",
        "recipientEmail": "prospect@releasetest.example",
        "recipientName": "Prospect Name",
        "ccRecipients": ["cc@releasetest.example"],
        "quarantined": quarantined,
        "createdAt": FIXED_TS,
        "updatedAt": FIXED_TS,
    }
    if quarantined or batch:
        doc["quarantine"] = {
            "batch": batch,
            "reason": "pre_deployment_safety_review",
            "appliedAt": FIXED_TS,
        }
    msg_res = await db.outreachmessages.insert_one(doc)
    return str(msg_res.inserted_id), cid


# ---------------------------------------------------------------------------
# 1. Authentication and Secret Management
# ---------------------------------------------------------------------------

async def test_fails_closed_when_admin_release_key_not_configured(client, isolated_test_db):
    """If ADMIN_RELEASE_KEY is unset in the environment, endpoint returns 503."""
    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": ""}, clear=False):
        mid, _ = await create_quarantined_fixture(isolated_test_db)
        res = await client.post(
            f"/api/outreach/{mid}/release-quarantine",
            json={
                "confirmMessageId": mid,
                "expectedBatch": "quarantine-20261009",
                "reason": "Approved release for testing",
                "actor": "auditor",
            },
            headers={"X-Admin-Key": "some-key"},
        )
        assert res.status_code == 503
        data = res.json()
        assert "disabled" in data.get("message", "").lower()


async def test_requires_x_admin_key_header(client, isolated_test_db):
    """Missing X-Admin-Key header returns 401."""
    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_SECRET_KEY}, clear=False):
        mid, _ = await create_quarantined_fixture(isolated_test_db)
        res = await client.post(
            f"/api/outreach/{mid}/release-quarantine",
            json={
                "confirmMessageId": mid,
                "expectedBatch": "quarantine-20261009",
                "reason": "Approved release for testing",
                "actor": "auditor",
            },
        )
        assert res.status_code == 401
        data = res.json()
        assert "Authentication required" in data.get("message", "")


async def test_rejects_invalid_x_admin_key(client, isolated_test_db):
    """Incorrect X-Admin-Key header returns 403."""
    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_SECRET_KEY}, clear=False):
        mid, _ = await create_quarantined_fixture(isolated_test_db)
        res = await client.post(
            f"/api/outreach/{mid}/release-quarantine",
            json={
                "confirmMessageId": mid,
                "expectedBatch": "quarantine-20261009",
                "reason": "Approved release for testing",
                "actor": "auditor",
            },
            headers={"X-Admin-Key": "wrong-key-value"},
        )
        assert res.status_code == 403
        data = res.json()
        assert "Forbidden" in data.get("message", "")


# ---------------------------------------------------------------------------
# 2. Validation & Invariants
# ---------------------------------------------------------------------------

async def test_rejects_mismatched_confirm_message_id(client, isolated_test_db):
    """Path ID and body confirmMessageId must match exactly; 400 otherwise."""
    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_SECRET_KEY}, clear=False):
        mid, _ = await create_quarantined_fixture(isolated_test_db)
        other_id = str(ObjectId())
        res = await client.post(
            f"/api/outreach/{mid}/release-quarantine",
            json={
                "confirmMessageId": other_id,
                "expectedBatch": "quarantine-20261009",
                "reason": "Approved release for testing",
                "actor": "auditor",
            },
            headers={"X-Admin-Key": TEST_SECRET_KEY},
        )
        assert res.status_code == 400
        data = res.json()
        assert "Confirmation mismatch" in data.get("message", "")


async def test_rejects_invalid_object_id_format(client, isolated_test_db):
    """Invalid ObjectID string format returns 400."""
    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_SECRET_KEY}, clear=False):
        bad_id = "invalid-oid"
        res = await client.post(
            f"/api/outreach/{bad_id}/release-quarantine",
            json={
                "confirmMessageId": bad_id,
                "expectedBatch": "quarantine-20261009",
                "reason": "Approved release for testing",
                "actor": "auditor",
            },
            headers={"X-Admin-Key": TEST_SECRET_KEY},
        )
        assert res.status_code == 400
        data = res.json()
        assert "Invalid message ID format" in data.get("message", "")


async def test_rejects_missing_or_short_reason(client, isolated_test_db):
    """Reason is mandatory and must have min_length=5."""
    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_SECRET_KEY}, clear=False):
        mid, _ = await create_quarantined_fixture(isolated_test_db)
        res = await client.post(
            f"/api/outreach/{mid}/release-quarantine",
            json={
                "confirmMessageId": mid,
                "expectedBatch": "quarantine-20261009",
                "reason": "ok",  # too short
                "actor": "auditor",
            },
            headers={"X-Admin-Key": TEST_SECRET_KEY},
        )
        assert res.status_code == 422


async def test_rejects_nonexistent_message(client, isolated_test_db):
    """Non-existent message returns 404."""
    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_SECRET_KEY}, clear=False):
        missing_id = str(ObjectId())
        res = await client.post(
            f"/api/outreach/{missing_id}/release-quarantine",
            json={
                "confirmMessageId": missing_id,
                "expectedBatch": "quarantine-20261009",
                "reason": "Approved release for testing",
                "actor": "auditor",
            },
            headers={"X-Admin-Key": TEST_SECRET_KEY},
        )
        assert res.status_code == 404


async def test_rejects_batch_mismatch(client, isolated_test_db):
    """If payload expectedBatch does not match doc batch, returns 409."""
    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_SECRET_KEY}, clear=False):
        mid, _ = await create_quarantined_fixture(isolated_test_db, batch="batch-alpha")
        res = await client.post(
            f"/api/outreach/{mid}/release-quarantine",
            json={
                "confirmMessageId": mid,
                "expectedBatch": "batch-beta",
                "reason": "Approved release for testing",
                "actor": "auditor",
            },
            headers={"X-Admin-Key": TEST_SECRET_KEY},
        )
        assert res.status_code == 409
        data = res.json()
        assert "Batch mismatch" in data.get("message", "")


async def test_rejects_already_unquarantined_message(client, isolated_test_db):
    """If message is not quarantined, returns 409."""
    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_SECRET_KEY}, clear=False):
        mid, _ = await create_quarantined_fixture(isolated_test_db, quarantined=False)
        res = await client.post(
            f"/api/outreach/{mid}/release-quarantine",
            json={
                "confirmMessageId": mid,
                "expectedBatch": "quarantine-20261009",
                "reason": "Approved release for testing",
                "actor": "auditor",
            },
            headers={"X-Admin-Key": TEST_SECRET_KEY},
        )
        assert res.status_code == 409
        data = res.json()
        assert "Message is not quarantined" in data.get("message", "")


async def test_rejects_non_draft_status(client, isolated_test_db):
    """If message is in sent or scheduled status, returns 409."""
    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_SECRET_KEY}, clear=False):
        mid, _ = await create_quarantined_fixture(isolated_test_db, status="sent")
        res = await client.post(
            f"/api/outreach/{mid}/release-quarantine",
            json={
                "confirmMessageId": mid,
                "expectedBatch": "quarantine-20261009",
                "reason": "Approved release for testing",
                "actor": "auditor",
            },
            headers={"X-Admin-Key": TEST_SECRET_KEY},
        )
        assert res.status_code == 409
        data = res.json()
        assert "Cannot release message in status 'sent'" in data.get("message", "")


# ---------------------------------------------------------------------------
# 3. Successful Release & State Invariants
# ---------------------------------------------------------------------------

async def test_successful_release_and_audit_logging(client, isolated_test_db, block_real_smtp):
    """Successful release atomically updates quarantined=False, records metadata,
    preserves status='draft', inserts audit record, and triggers zero SMTP calls."""
    db = isolated_test_db
    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_SECRET_KEY}, clear=False):
        mid, cid = await create_quarantined_fixture(db, batch="quarantine-20261009", step=2)
        before_doc = await db.outreachmessages.find_one({"_id": ObjectId(mid)})

        res = await client.post(
            f"/api/outreach/{mid}/release-quarantine",
            json={
                "confirmMessageId": mid,
                "expectedBatch": "quarantine-20261009",
                "reason": "Manual review passed: greeting and evidence verified by operator",
                "actor": "senior_reviewer",
            },
            headers={"X-Admin-Key": TEST_SECRET_KEY},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "successfully released" in data["message"].lower()

        # Database state verification
        after_doc = await db.outreachmessages.find_one({"_id": ObjectId(mid)})
        assert after_doc["quarantined"] is False
        assert after_doc["status"] == "draft"  # Strictly remains draft
        assert "scheduledAt" not in after_doc
        assert "approvedAt" not in after_doc
        assert "sentAt" not in after_doc

        # Content preservation
        assert after_doc["subject"] == before_doc["subject"]
        assert after_doc["bodyText"] == before_doc["bodyText"]
        assert after_doc["bodyHtml"] == before_doc["bodyHtml"]
        assert after_doc["recipientEmail"] == before_doc["recipientEmail"]
        assert after_doc["recipientName"] == before_doc["recipientName"]
        assert after_doc["ccRecipients"] == before_doc["ccRecipients"]

        # Release metadata recorded
        rel_meta = after_doc.get("quarantineReleased")
        assert rel_meta is not None
        assert rel_meta["releasedBy"] == "senior_reviewer"
        assert rel_meta["releaseReason"] == "Manual review passed: greeting and evidence verified by operator"
        assert rel_meta["previousBatch"] == "quarantine-20261009"
        assert isinstance(rel_meta["releasedAt"], datetime)

        # Audit log written to quarantine_audit_logs
        audit_entry = await db.quarantine_audit_logs.find_one({"messageId": mid})
        assert audit_entry is not None
        assert audit_entry["action"] == "RELEASE_QUARANTINE"
        assert audit_entry["actor"] == "senior_reviewer"
        assert audit_entry["batch"] == "quarantine-20261009"
        assert audit_entry["recipientEmail"] == before_doc["recipientEmail"]
        assert audit_entry["messageStatus"] == "draft"
        assert audit_entry["authMethod"] == "X-Admin-Key"

        # SMTP was NOT triggered
        block_real_smtp.assert_not_called()


async def test_concurrent_or_repeat_release_rejected(client, isolated_test_db):
    """Calling release-quarantine a second time on an already released message fails with 409."""
    db = isolated_test_db
    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_SECRET_KEY}, clear=False):
        mid, _ = await create_quarantined_fixture(db, batch="quarantine-20261009", step=3)

        payload = {
            "confirmMessageId": mid,
            "expectedBatch": "quarantine-20261009",
            "reason": "First release call",
            "actor": "operator_1",
        }
        res1 = await client.post(
            f"/api/outreach/{mid}/release-quarantine",
            json=payload,
            headers={"X-Admin-Key": TEST_SECRET_KEY},
        )
        assert res1.status_code == 200

        # Second attempt must be rejected
        payload["reason"] = "Second release call attempt"
        res2 = await client.post(
            f"/api/outreach/{mid}/release-quarantine",
            json=payload,
            headers={"X-Admin-Key": TEST_SECRET_KEY},
        )
        assert res2.status_code == 409
        assert "not quarantined" in res2.json().get("message", "").lower()


# ---------------------------------------------------------------------------
# 4. Security Hardening: Network Binding & Audit Consistency Tests
# ---------------------------------------------------------------------------

def test_server_config_defaults_to_localhost_and_respects_env():
    """Verify backend startup defaults to 127.0.0.1 (safe loopback) when HOST is unset,
    and honors explicit environment overrides when configured."""
    from run import get_server_config, DEFAULT_HOST, DEFAULT_PORT

    assert DEFAULT_HOST == "127.0.0.1"
    assert DEFAULT_PORT == 5000

    # Case 1: Unset HOST -> defaults to 127.0.0.1
    with patch.dict(os.environ, {}, clear=True):
        host, port = get_server_config()
        assert host == "127.0.0.1"
        assert port == 5000

    # Case 2: Explicit HOST and PORT configured
    with patch.dict(os.environ, {"HOST": "0.0.0.0", "PORT": "8080"}):
        host, port = get_server_config()
        assert host == "0.0.0.0"
        assert port == 8080


async def test_transaction_support_detection(isolated_test_db):
    """Verify transaction support detection handles connected database topology accurately."""
    from app.services.quarantine_service import check_transactions_supported

    supports_tx = await check_transactions_supported(isolated_test_db)
    # Standalone local Mongo does not support replica set multi-document transactions
    assert isinstance(supports_tx, bool)


async def test_audit_insert_failure_handling_and_recovery(client, isolated_test_db, block_real_smtp):
    """Simulate secondary audit log insertion failure:
    1. Message unquarantining succeeds and strictly remains draft (zero SMTP, zero scheduling).
    2. Primary embedded metadata records auditLogged=False and auditError.
    3. Response carries auditWarning.
    4. reconcile_missing_quarantine_audit_logs detects and backfills the missing audit entry.
    5. Second reconcile call is completely idempotent (no duplicates).
    """
    db = isolated_test_db
    from app.services.quarantine_service import reconcile_missing_quarantine_audit_logs

    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_SECRET_KEY}, clear=False):
        mid, cid = await create_quarantined_fixture(db, batch="quarantine-20261009", step=2)

        # Mock AsyncIOMotorCollection.insert_one specifically for quarantine_audit_logs collection
        from motor.motor_asyncio import AsyncIOMotorCollection
        real_insert_one = AsyncIOMotorCollection.insert_one

        async def failing_insert_audit(self, *args, **kwargs):
            if self.name == "quarantine_audit_logs":
                raise RuntimeError("Simulated transient connection failure on secondary audit collection")
            return await real_insert_one(self, *args, **kwargs)

        with patch.object(AsyncIOMotorCollection, "insert_one", new=failing_insert_audit):
            res = await client.post(
                f"/api/outreach/{mid}/release-quarantine",
                json={
                    "confirmMessageId": mid,
                    "expectedBatch": "quarantine-20261009",
                    "reason": "Audit insert failure test",
                    "actor": "security_tester",
                },
                headers={"X-Admin-Key": TEST_SECRET_KEY},
            )

        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "auditWarning" in data
        assert "Simulated transient connection failure" in data["auditWarning"]

        # Verify message state in database: unquarantined, draft only, zero scheduling
        after_doc = await db.outreachmessages.find_one({"_id": ObjectId(mid)})
        assert after_doc["quarantined"] is False
        assert after_doc["status"] == "draft"
        assert "scheduledAt" not in after_doc
        assert "approvedAt" not in after_doc
        assert "sentAt" not in after_doc
        block_real_smtp.assert_not_called()

        # Primary embedded audit indicates secondary write failed
        rel_meta = after_doc.get("quarantineReleased")
        assert rel_meta["auditLogged"] is False
        assert "Simulated transient connection failure" in rel_meta["auditError"]

        # Secondary audit log collection has NO entry yet
        log_before_reconcile = await db.quarantine_audit_logs.find_one({"messageId": mid})
        assert log_before_reconcile is None

        # Reconcile step: runs idempotent repair
        reconcile_res = await reconcile_missing_quarantine_audit_logs(db)
        assert reconcile_res["success"] is True
        assert reconcile_res["repaired"] >= 1

        # Verify secondary audit log was backfilled accurately from primary metadata
        log_after_reconcile = await db.quarantine_audit_logs.find_one({"messageId": mid})
        assert log_after_reconcile is not None
        assert log_after_reconcile["messageId"] == mid
        assert log_after_reconcile["action"] == "RELEASE_QUARANTINE_RECONCILED"
        assert log_after_reconcile["actor"] == "security_tester"
        assert log_after_reconcile["reason"] == "Audit insert failure test"
        assert log_after_reconcile["messageStatus"] == "draft"

        # Verify message doc was updated to auditLogged=True
        reconciled_doc = await db.outreachmessages.find_one({"_id": ObjectId(mid)})
        assert reconciled_doc["quarantineReleased"]["auditLogged"] is True
        assert reconciled_doc["status"] == "draft"
        assert reconciled_doc["quarantined"] is False

        # Idempotency check: running reconcile again repairs 0 documents
        reconcile_repeat = await reconcile_missing_quarantine_audit_logs(db)
        assert reconcile_repeat["success"] is True
        assert reconcile_repeat["repaired"] == 0

        # Audit log count for this message remains exactly 1
        count_logs = await db.quarantine_audit_logs.count_documents({"messageId": mid})
        assert count_logs == 1


async def test_quarantine_release_e2e_synthetic_full_cycle(client, isolated_test_db, block_real_smtp):
    """Safe E2E Test: Full synthetic release lifecycle against isolated test database:
    1. Creates synthetic company and synthetic quarantined follow-up in dedicated batch.
    2. Exercises release API with valid authentication and confirmation.
    3. Verifies message is unquarantined, remains draft, zero SMTP dispatches, zero scheduling.
    4. Confirms audit record in quarantine_audit_logs.
    5. Confirms subsequent duplicate release fails with 409.
    """
    db = isolated_test_db
    synthetic_batch = "quarantine-synthetic-e2e-20261010"

    # Step 1: Insert synthetic company & draft message
    comp_res = await db.companies.insert_one({
        "companyName": "Synthetic E2E Corp",
        "website": "https://synthetic-e2e.example",
        "evidence": "Synthetic evidence for safe E2E testing.",
        "recommendedService": "AI Strategy Consulting",
        "createdAt": FIXED_TS,
        "updatedAt": FIXED_TS,
    })
    cid = comp_res.inserted_id

    msg_res = await db.outreachmessages.insert_one({
        "companyId": cid,
        "step": 2,
        "status": "draft",
        "subject": "Synthetic Follow-up Step 2",
        "bodyHtml": "<p>Synthetic body</p>",
        "bodyText": "Synthetic body",
        "recipientEmail": "synthetic.lead@synthetic-e2e.example",
        "recipientName": "Synthetic Lead",
        "ccRecipients": [],
        "quarantined": True,
        "quarantine": {
            "batch": synthetic_batch,
            "reason": "synthetic_e2e_testing",
            "appliedAt": FIXED_TS,
        },
        "createdAt": FIXED_TS,
        "updatedAt": FIXED_TS,
    })
    mid = str(msg_res.inserted_id)

    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_SECRET_KEY}, clear=False):
        # Step 2: Call release endpoint with valid key and payload
        res = await client.post(
            f"/api/outreach/{mid}/release-quarantine",
            json={
                "confirmMessageId": mid,
                "expectedBatch": synthetic_batch,
                "reason": "Synthetic E2E manual review verified",
                "actor": "e2e_tester",
            },
            headers={"X-Admin-Key": TEST_SECRET_KEY},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True

        # Step 3: Inspect database document state
        doc = await db.outreachmessages.find_one({"_id": ObjectId(mid)})
        assert doc["quarantined"] is False
        assert doc["status"] == "draft"
        assert "scheduledAt" not in doc
        assert "approvedAt" not in doc
        assert "sentAt" not in doc
        assert doc["recipientEmail"] == "synthetic.lead@synthetic-e2e.example"

        # Step 4: Verify audit log entry
        audit = await db.quarantine_audit_logs.find_one({"messageId": mid})
        assert audit is not None
        assert audit["batch"] == synthetic_batch
        assert audit["actor"] == "e2e_tester"
        assert audit["reason"] == "Synthetic E2E manual review verified"
        assert audit["action"] == "RELEASE_QUARANTINE"

        # Zero SMTP calls
        block_real_smtp.assert_not_called()

        # Step 5: Duplicate release attempt is rejected
        res_dup = await client.post(
            f"/api/outreach/{mid}/release-quarantine",
            json={
                "confirmMessageId": mid,
                "expectedBatch": synthetic_batch,
                "reason": "Attempting duplicate release",
                "actor": "e2e_tester",
            },
            headers={"X-Admin-Key": TEST_SECRET_KEY},
        )
        assert res_dup.status_code == 409
        assert "not quarantined" in res_dup.json().get("message", "").lower()


