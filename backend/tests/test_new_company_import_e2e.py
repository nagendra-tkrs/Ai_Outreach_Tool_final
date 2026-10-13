"""
End-to-End Verification of New Company Excel Import and Follow-up Workflow.

Strict Safety Rules:
- Isolated disposable database: ai_client_outreach_test_e2e_new_company
- Mocked SMTP: zero real email delivery, zero network SMTP connections
- Dropped cleanly before and after the test run
- Zero mutation of the production database
"""

import io
from unittest.mock import AsyncMock, patch
import pytest
import openpyxl
import httpx
from motor.motor_asyncio import AsyncIOMotorClient

import app.config.database as db_module
from app.main import app

TEST_DB_NAME = "ai_client_outreach_test_e2e_new_company"
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
async def test_new_company_excel_import_to_scheduling_e2e(client, isolated_test_db, mock_smtp_guard):
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

    # All steps start as ordinary drafts (no quarantine fields).
    for step_doc in (step1, step2, step3):
        assert step_doc["status"] == "draft"
        assert step_doc.get("quarantined") is None
    assert step1["recipientName"] == "Alice Green"
    # Note: When initially generated without crawler/contact discovery, recipientEmail is ""
    assert step1.get("recipientEmail", "") == ""

    # -------------------------------------------------------------------------
    # 5. Editing Step 1 recipient synchronizes eligible unsent follow-ups
    # -------------------------------------------------------------------------
    step1_id = str(step1["_id"])
    put_res = await client.put(
        f"/api/outreach/{step1_id}",
        json={"recipientEmail": "alice@alpha.example"},
    )
    assert put_res.status_code == 200, f"PUT failed: {put_res.text}"
    sync_data = put_res.json().get("recipientSync", {})
    # Steps 2 and 3 are eligible unsent drafts -> both are synchronized.
    assert sync_data.get("updated", 0) == 2

    step1 = await db.outreachmessages.find_one({"_id": step1["_id"]})
    step2 = await db.outreachmessages.find_one({"_id": step2["_id"]})
    step3 = await db.outreachmessages.find_one({"_id": step3["_id"]})
    assert step1["recipientEmail"] == "alice@alpha.example"
    assert step2["recipientEmail"] == "alice@alpha.example"
    assert step3["recipientEmail"] == "alice@alpha.example"

    # -------------------------------------------------------------------------
    # 6. Sequence Scheduling: Step 1 approved, follow-ups armed
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

    step1_post_sched = await db.outreachmessages.find_one({"_id": step1["_id"]})
    step2_post_sched = await db.outreachmessages.find_one({"_id": step2["_id"]})
    step3_post_sched = await db.outreachmessages.find_one({"_id": step3["_id"]})

    assert step1_post_sched["status"] == "approved"
    assert step2_post_sched["status"] == "scheduled"
    assert step2_post_sched.get("scheduledAt") is not None
    assert step3_post_sched["status"] == "scheduled"
    assert step3_post_sched.get("scheduledAt") is not None

    # -------------------------------------------------------------------------
    # 7. Duplicate Detection on Re-Import: Upload the exact same Excel sheet
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
    # 8. Transport Safety: Zero real delivery calls
    # -------------------------------------------------------------------------
    assert mock_smtp_guard.call_count == 0
