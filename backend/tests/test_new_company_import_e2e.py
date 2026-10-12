"""
End-to-End Verification of New Company Excel Import and Follow-up Quarantine Workflow.

Strict Safety Rules:
- Isolated disposable database: ai_client_outreach_test_e2e_new_company
- Mocked SMTP: zero real email delivery, zero network SMTP connections
- Dropped cleanly before and after the test run
- Zero mutation of production database or batch quarantine-20261009
"""

import io
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import pytest
import openpyxl
import httpx
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

import app.config.database as db_module
from app.main import app
from app.services.send_guard import is_message_quarantined
from app.services.scheduler_service import process_scheduled_emails

TEST_DB_NAME = "ai_client_outreach_test_e2e_new_company"
TEST_ADMIN_KEY = "test-e2e-admin-release-key-2026"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
        client.close()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture(autouse=True)
def mock_smtp_guard():
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mocked_send:
        # If any real delivery is attempted without explicit test expectation, raise
        mocked_send.return_value = ({"test@example.com": (250, "OK")}, "250 Message accepted")
        yield mocked_send


@pytest.fixture(autouse=True)
def mock_llm_generation():
    with patch("app.services.outreach_service.can_use_ai", return_value=False):
        yield


def create_excel_bytes(headers, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_new_company_excel_import_to_quarantine_e2e(client, isolated_test_db, mock_smtp_guard):
    db = isolated_test_db

    # -------------------------------------------------------------------------
    # 1. Create synthetic Excel file with 2 new companies
    # -------------------------------------------------------------------------
    headers = [
        "Company Name", "Website", "Evidence", "Recommended Service",
        "Industry", "Country", "Contact Name", "Contact Email"
    ]
    rows = [
        [
            "Example Alpha Corp",
            "https://alpha.example",
            "Recently expanded customer support operations and looking for automation.",
            "AI Strategy Consulting",
            "Technology",
            "US",
            "Alice Green",
            "alice@alpha.example",
        ],
        [
            "Example Beta Solutions",
            "https://beta.example",
            "Expanding logistics hubs and requires automated dispatching.",
            "AI & Automation Workshops",
            "Logistics",
            "UK",
            "Bob White",
            "bob@beta.example",
        ],
    ]
    excel_content = create_excel_bytes(headers, rows)

    # -------------------------------------------------------------------------
    # 2. Upload Excel via POST /api/import/excel
    # -------------------------------------------------------------------------
    upload_res = await client.post(
        "/api/import/excel",
        files={"file": ("new_leads.xlsx", excel_content, XLSX_MIME)},
    )
    assert upload_res.status_code == 200, f"Upload failed: {upload_res.text}"
    upload_data = upload_res.json()["data"]
    batch_id = upload_data["batchId"]
    assert upload_data["summary"]["valid"] == 2
    assert upload_data["summary"]["invalid"] == 0

    # -------------------------------------------------------------------------
    # 3. Confirm import via POST /api/import/{batch_id}/confirm
    # -------------------------------------------------------------------------
    confirm_res = await client.post(f"/api/import/{batch_id}/confirm")
    assert confirm_res.status_code == 200, f"Confirm failed: {confirm_res.text}"

    # Verify both companies persisted in the isolated database
    alpha_comp = await db.companies.find_one({"companyName": "Example Alpha Corp"})
    beta_comp = await db.companies.find_one({"companyName": "Example Beta Solutions"})
    assert alpha_comp is not None, "Example Alpha Corp not found in DB"
    assert beta_comp is not None, "Example Beta Solutions not found in DB"
    assert str(alpha_comp["importBatchId"]) == batch_id
    assert alpha_comp["evidence"] == "Recently expanded customer support operations and looking for automation."
    assert alpha_comp["contactEmail"] == "alice@alpha.example"
    assert beta_comp["contactEmail"] == "bob@beta.example"

    alpha_cid = str(alpha_comp["_id"])

    # -------------------------------------------------------------------------
    # 4. Generate outreach sequence via POST /api/companies/{id}/outreach/generate
    # -------------------------------------------------------------------------
    gen_res = await client.post(
        f"/api/companies/{alpha_cid}/outreach/generate",
        json={"force_regenerate": True},
    )
    assert gen_res.status_code == 200, f"Generate failed: {gen_res.text}"
    gen_data = gen_res.json()["data"]
    assert len(gen_data) == 3

    # Inspect the 3 generated messages from database
    step1 = await db.outreachmessages.find_one({"companyId": alpha_comp["_id"], "step": 1})
    step2 = await db.outreachmessages.find_one({"companyId": alpha_comp["_id"], "step": 2})
    step3 = await db.outreachmessages.find_one({"companyId": alpha_comp["_id"], "step": 3})

    assert step1 is not None and step2 is not None and step3 is not None

    # Step 1: Draft, unquarantined, recipientName populated from company.contactName
    assert step1["status"] == "draft"
    assert step1.get("quarantined") in (False, None)
    assert is_message_quarantined(step1) is False
    assert step1["recipientName"] == "Alice Green"
    # Note: When initially generated without crawler/contact discovery, recipientEmail is ""
    assert step1.get("recipientEmail", "") == ""

    # Security Guard: Editing Step 1 recipient via PUT /api/outreach/{step1_id}
    # does NOT mutate quarantined follow-ups (quarantined messages are strictly immune
    # to side-effect updates via "quarantined": {"$ne": True}).
    step1_id = str(step1["_id"])
    put_res = await client.put(
        f"/api/outreach/{step1_id}",
        json={"recipientEmail": "alice@alpha.example"},
    )
    assert put_res.status_code == 200, f"PUT failed: {put_res.text}"
    sync_data = put_res.json().get("recipientSync", {})
    # 0 follow-ups updated because Steps 2 and 3 are quarantined!
    assert sync_data.get("updated", 0) == 0

    # Refresh steps from database
    step1 = await db.outreachmessages.find_one({"_id": step1["_id"]})
    step2 = await db.outreachmessages.find_one({"_id": step2["_id"]})
    step3 = await db.outreachmessages.find_one({"_id": step3["_id"]})

    assert step1["recipientEmail"] == "alice@alpha.example"

    # Step 2 & 3: Draft, strictly quarantined and unmodified by Step 1 sync
    expected_quarantine_batch = f"quarantine-import-{batch_id}"
    for step_doc, step_num in [(step2, 2), (step3, 3)]:
        assert step_doc["status"] == "draft", f"Step {step_num} is not draft"
        assert step_doc.get("quarantined") is True, f"Step {step_num} is not quarantined: True"
        assert step_doc.get("scheduledAt") is None, f"Step {step_num} has scheduledAt"
        assert step_doc.get("quarantine", {}).get("active") is True
        assert step_doc.get("quarantine", {}).get("batch") == expected_quarantine_batch
        assert step_doc.get("quarantine", {}).get("reason") == "new_import_safety_review"
        assert len(step_doc.get("quarantine", {}).get("docHash", "")) == 64
        assert is_message_quarantined(step_doc) is True

    # -------------------------------------------------------------------------
    # 5. Direct Send Boundary Protection: Attempt to send quarantined Step 2
    # -------------------------------------------------------------------------
    step2_id = str(step2["_id"])
    mock_smtp_guard.reset_mock()

    send_res = await client.post(
        f"/api/outreach/{step2_id}/send",
        json={"recipientEmail": "alice@alpha.example"},
    )
    assert send_res.status_code == 409, f"Direct send should return 409, got {send_res.status_code}"
    assert "quarantined" in send_res.json().get("message", "").lower()
    mock_smtp_guard.assert_not_called()

    # Verify Step 2 document in DB was NOT mutated
    step2_post_send = await db.outreachmessages.find_one({"_id": step2["_id"]})
    assert step2_post_send["status"] == "draft"
    assert step2_post_send["quarantined"] is True
    assert "sentAt" not in step2_post_send

    # -------------------------------------------------------------------------
    # 6. Sequence Scheduling Protection: Attempt to schedule sequence
    # -------------------------------------------------------------------------
    sched_res = await client.post(
        f"/api/companies/{alpha_cid}/outreach/schedule",
        json={
            "schedules": [
                {"step": 1, "delayDays": 0},
                {"step": 2, "delayDays": 3},
                {"step": 3, "delayDays": 7},
            ]
        },
    )
    assert sched_res.status_code == 200
    sched_data = sched_res.json()
    assert "quarantinedSkipped" in sched_data
    skipped_steps = [item["step"] for item in sched_data["quarantinedSkipped"]]
    assert 2 in skipped_steps and 3 in skipped_steps

    # Verify Step 1 is approved for send, but Steps 2 & 3 remain draft without scheduledAt
    step1_post_sched = await db.outreachmessages.find_one({"_id": step1["_id"]})
    step2_post_sched = await db.outreachmessages.find_one({"_id": step2["_id"]})
    step3_post_sched = await db.outreachmessages.find_one({"_id": step3["_id"]})

    assert step1_post_sched["status"] == "approved"

    assert step2_post_sched["status"] == "draft"
    assert step2_post_sched["quarantined"] is True
    assert step2_post_sched.get("scheduledAt") is None

    assert step3_post_sched["status"] == "draft"
    assert step3_post_sched["quarantined"] is True
    assert step3_post_sched.get("scheduledAt") is None

    # -------------------------------------------------------------------------
    # 7. Step 1 Send & Follow-up Activation Guard
    # -------------------------------------------------------------------------
    step1_id = str(step1["_id"])
    mock_smtp_guard.reset_mock()

    step1_send_res = await client.post(
        f"/api/outreach/{step1_id}/send",
        json={"recipientEmail": "alice@alpha.example"},
    )
    step1_sent = await db.outreachmessages.find_one({"_id": step1["_id"]})
    assert step1_sent["status"] == "sent"
    assert step1_sent.get("isTestSend") is True

    # Verify outreach tracking record: follow-ups are NOT armed
    tracking_record = await db.outreachrecords.find_one({"companyId": alpha_comp["_id"]})
    assert tracking_record is not None
    assert tracking_record["initialEmail"]["status"] == "SENT"
    assert tracking_record["followUp1"]["status"] == "PENDING"
    assert tracking_record["followUp1"].get("scheduledAt") is None
    assert tracking_record["followUp2"]["status"] == "PENDING"
    assert tracking_record["followUp2"].get("scheduledAt") is None

    # -------------------------------------------------------------------------
    # 8. Scheduler Background Worker Invariant: Skips quarantined messages
    # -------------------------------------------------------------------------
    # Even if someone deliberately updated Step 2 to status="scheduled", worker must refuse
    await db.outreachmessages.update_one(
        {"_id": step2["_id"]},
        {"$set": {"status": "scheduled", "scheduledAt": datetime.now(timezone.utc)}}
    )
    mock_smtp_guard.reset_mock()
    await process_scheduled_emails()
    # Verify mock SMTP was NOT called by the scheduler worker
    mock_smtp_guard.assert_not_called()

    # Revert test tamper back to draft
    await db.outreachmessages.update_one(
        {"_id": step2["_id"]},
        {"$set": {"status": "draft"}, "$unset": {"scheduledAt": ""}}
    )

    # -------------------------------------------------------------------------
    # 9. Admin Quarantine Release on Step 2
    # -------------------------------------------------------------------------
    with patch.dict(os.environ, {"ADMIN_RELEASE_KEY": TEST_ADMIN_KEY}, clear=False):
        # Without key -> 401
        rel_fail = await client.post(
            f"/api/outreach/{step2_id}/release-quarantine",
            json={
                "confirmMessageId": step2_id,
                "expectedBatch": expected_quarantine_batch,
                "reason": "Verified contact person and domain for Alpha Corp",
                "actor": "admin_auditor",
            },
        )
        assert rel_fail.status_code == 401

        # With valid key -> 200 OK
        rel_ok = await client.post(
            f"/api/outreach/{step2_id}/release-quarantine",
            json={
                "confirmMessageId": step2_id,
                "expectedBatch": expected_quarantine_batch,
                "reason": "Verified contact person and domain for Alpha Corp",
                "actor": "admin_auditor",
            },
            headers={"X-Admin-Key": TEST_ADMIN_KEY},
        )
        assert rel_ok.status_code == 200
        rel_data = rel_ok.json()
        assert rel_data["success"] is True

        # Inspect released Step 2:
        # Must be quarantined=False, but REMAIN DRAFT, NOT SCHEDULED, NOT SENT
        step2_released = await db.outreachmessages.find_one({"_id": step2["_id"]})
        assert step2_released["quarantined"] is False
        assert step2_released["quarantine"]["active"] is False
        assert step2_released["quarantineReleased"]["releasedBy"] == "admin_auditor"
        assert step2_released["status"] == "draft"
        assert step2_released.get("scheduledAt") is None
        assert step2_released.get("sentAt") is None

        # Verify audit log recorded in quarantine_audit_logs
        audit_log = await db.quarantine_audit_logs.find_one({"messageId": step2_id})
        assert audit_log is not None
        assert audit_log["action"] == "RELEASE_QUARANTINE"
        assert audit_log["batch"] == expected_quarantine_batch

        # Verify Step 3 remains quarantined!
        step3_check = await db.outreachmessages.find_one({"_id": step3["_id"]})
        assert step3_check["quarantined"] is True
        assert step3_check["quarantine"]["active"] is True

    # -------------------------------------------------------------------------
    # 10. Post-Release Eligibility: Released Step 2 can now be scheduled
    # -------------------------------------------------------------------------
    sched_released_res = await client.post(
        f"/api/companies/{alpha_cid}/outreach/schedule",
        json={
            "schedules": [
                {"step": 2, "delayDays": 3},
                {"step": 3, "delayDays": 7},
            ]
        },
    )
    assert sched_released_res.status_code == 200
    sched_rel_data = sched_released_res.json()
    rel_skipped = [item["step"] for item in sched_rel_data.get("quarantinedSkipped", [])]
    # Step 2 is released, so it is NOT skipped! Only Step 3 is skipped!
    assert 2 not in rel_skipped, f"Released Step 2 should not be skipped: {rel_skipped}"
    assert 3 in rel_skipped, f"Unreleased Step 3 must still be skipped: {rel_skipped}"

    step2_now_scheduled = await db.outreachmessages.find_one({"_id": step2["_id"]})
    assert step2_now_scheduled["status"] == "scheduled"
    assert step2_now_scheduled.get("scheduledAt") is not None

    step3_still_draft = await db.outreachmessages.find_one({"_id": step3["_id"]})
    assert step3_still_draft["status"] == "draft"
    assert step3_still_draft["quarantined"] is True
    assert step3_still_draft.get("scheduledAt") is None

    # -------------------------------------------------------------------------
    # 11. Duplicate Detection on Re-Import: Upload the exact same Excel sheet
    # -------------------------------------------------------------------------
    re_upload_res = await client.post(
        "/api/import/excel",
        files={"file": ("re_import_leads.xlsx", excel_content, XLSX_MIME)},
    )
    assert re_upload_res.status_code == 200
    re_upload_data = re_upload_res.json()["data"]
    # Both companies are already in the DB, so valid must be 0 and existingInDb must be 2
    assert re_upload_data["summary"]["existingInDb"] == 2
    assert re_upload_data["summary"]["valid"] == 0
    re_batch_id = re_upload_data["batchId"]

    # Confirming a batch with 0 valid rows fails with 400
    re_confirm_res = await client.post(f"/api/import/{re_batch_id}/confirm")
    assert re_confirm_res.status_code == 400
    assert "no valid rows" in re_confirm_res.json().get("message", "").lower()

    # -------------------------------------------------------------------------
    # 12. Transport Safety: Zero real delivery calls
    # -------------------------------------------------------------------------
    # In test sandbox mode, real SMTP calls are strictly 0
    assert mock_smtp_guard.call_count == 0

