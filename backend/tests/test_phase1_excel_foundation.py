import io
import pytest
import openpyxl
from bson import ObjectId
from datetime import datetime, timezone
import httpx

from app.main import app
from app.config.database import connect_db, close_db, get_db
from app.utils.validators import (
    validate_row,
    REQUIRED_COLUMNS,
    VALID_RECOMMENDED_SERVICES
)
from app.services.excel_service import process_excel

@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    await connect_db()
    yield
    await close_db()

@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

def create_excel_bytes(headers, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()

# Test A: Valid Excel row imports successfully
@pytest.mark.asyncio
async def test_a_valid_excel_row_imports_successfully(client):
    db = get_db()
    test_comp_name = "Phase1 Test A Logistics"
    await db.companies.delete_many({"companyName": test_comp_name})

    headers = ["Company Name", "Website", "Evidence", "Recommended Service"]
    rows = [
        [test_comp_name, "https://phase1-test-a.com", "Expanding modern warehouse logistics.", "AI & Automation Workshops"]
    ]
    excel_bytes = create_excel_bytes(headers, rows)

    files = {"file": ("test_a.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    res = await client.post("/api/import/excel", files=files)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["summary"]["valid"] == 1
    assert data["rows"][0]["status"] == "valid"
    assert data["rows"][0]["evidence"] == "Expanding modern warehouse logistics."
    assert data["rows"][0]["recommendedService"] == "AI & Automation Workshops"

    batch_id = data["batchId"]
    confirm_res = await client.post(f"/api/import/{batch_id}/confirm")
    assert confirm_res.status_code == 200
    c_data = confirm_res.json()["data"]
    assert c_data["imported"] == 1

    stored = await db.companies.find_one({"companyName": test_comp_name})
    assert stored is not None
    assert stored["companyName"] == test_comp_name
    assert stored["website"] == "https://phase1-test-a.com"
    assert stored["evidence"] == "Expanding modern warehouse logistics."
    assert stored["recommendedService"] == "AI & Automation Workshops"

    # Cleanup
    await db.companies.delete_one({"_id": stored["_id"]})
    await db.importbatches.delete_one({"_id": ObjectId(batch_id)})

# Test B: Missing Evidence is rejected/flagged
def test_b_missing_evidence_is_rejected():
    row_missing_evidence = {
        "companyName": "Acme Corp",
        "website": "https://acme.com",
        "evidence": "",
        "recommendedService": "AI Strategy Consulting"
    }
    errors = validate_row(row_missing_evidence)
    assert any("Evidence is required" in err for err in errors)

# Test C: Missing Recommended Service is rejected/flagged
def test_c_missing_recommended_service_is_rejected():
    row_missing_service = {
        "companyName": "Acme Corp",
        "website": "https://acme.com",
        "evidence": "Acme is scaling cloud infrastructure.",
        "recommendedService": ""
    }
    errors = validate_row(row_missing_service)
    assert any("Recommended Service is required" in err for err in errors)

# Test D: Invalid Recommended Service is rejected/flagged
def test_d_invalid_recommended_service_is_rejected():
    row_invalid_service = {
        "companyName": "Acme Corp",
        "website": "https://acme.com",
        "evidence": "Acme is scaling cloud infrastructure.",
        "recommendedService": "AI Consulting"  # Invalid! Not in accepted set
    }
    errors = validate_row(row_invalid_service)
    assert any("Invalid Recommended Service" in err for err in errors)
    # Ensure it did NOT get automatically converted
    assert row_invalid_service["recommendedService"] == "AI Consulting"

# Test E: Valid Recommended Service is stored exactly
@pytest.mark.asyncio
async def test_e_valid_recommended_service_is_stored_exactly(client):
    db = get_db()
    test_comp_name = "Phase1 Test E Corp"
    await db.companies.delete_many({"companyName": test_comp_name})

    exact_service = "AI Governance and Responsible AI"
    headers = ["Company Name", "Website", "Evidence", "Recommended Service"]
    rows = [
        [test_comp_name, "https://phase1-test-e.com", "Building enterprise compliance models.", exact_service]
    ]
    excel_bytes = create_excel_bytes(headers, rows)

    files = {"file": ("test_e.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    res = await client.post("/api/import/excel", files=files)
    assert res.status_code == 200
    batch_id = res.json()["data"]["batchId"]

    confirm_res = await client.post(f"/api/import/{batch_id}/confirm")
    assert confirm_res.status_code == 200

    stored = await db.companies.find_one({"companyName": test_comp_name})
    assert stored is not None
    assert stored["recommendedService"] == exact_service

    # Cleanup
    await db.companies.delete_one({"_id": stored["_id"]})
    await db.importbatches.delete_one({"_id": ObjectId(batch_id)})

# Test F: Evidence is stored correctly
@pytest.mark.asyncio
async def test_f_evidence_is_stored_correctly(client):
    db = get_db()
    test_comp_name = "Phase1 Test F Corp"
    await db.companies.delete_many({"companyName": test_comp_name})

    exact_evidence = "Company is expanding warehouse automation and digital supply-chain operations."
    headers = ["Company Name", "Website", "Evidence", "Recommended Service"]
    rows = [
        [test_comp_name, "https://phase1-test-f.com", exact_evidence, "AI & Automation Workshops"]
    ]
    excel_bytes = create_excel_bytes(headers, rows)

    files = {"file": ("test_f.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    res = await client.post("/api/import/excel", files=files)
    assert res.status_code == 200
    batch_id = res.json()["data"]["batchId"]

    confirm_res = await client.post(f"/api/import/{batch_id}/confirm")
    assert confirm_res.status_code == 200

    stored = await db.companies.find_one({"companyName": test_comp_name})
    assert stored is not None
    assert stored["evidence"] == exact_evidence

    # Cleanup
    await db.companies.delete_one({"_id": stored["_id"]})
    await db.importbatches.delete_one({"_id": ObjectId(batch_id)})

# Test G: Existing Excel optional columns still work
@pytest.mark.asyncio
async def test_g_optional_columns_still_work(client):
    db = get_db()
    test_comp_name = "Phase1 Test G MultiField"
    await db.companies.delete_many({"companyName": test_comp_name})

    headers = [
        "Company Name", "Website", "Evidence", "Recommended Service",
        "Industry", "Country", "Contact Name", "Contact Email",
        "Revenue", "Employee Count", "Notes", "Source"
    ]
    rows = [
        [
            test_comp_name, "https://phase1-test-g.com",
            "Multi-national supply chain modernization.",
            "AI Data Strategy",
            "Manufacturing", "Germany", "Hans Gruber", "hans@phase1-test-g.com",
            "$50M", "250", "High priority account", "custom_source"
        ]
    ]
    excel_bytes = create_excel_bytes(headers, rows)

    files = {"file": ("test_g.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    res = await client.post("/api/import/excel", files=files)
    assert res.status_code == 200
    batch_id = res.json()["data"]["batchId"]

    confirm_res = await client.post(f"/api/import/{batch_id}/confirm")
    assert confirm_res.status_code == 200

    stored = await db.companies.find_one({"companyName": test_comp_name})
    assert stored is not None
    assert stored["industry"] == "Manufacturing"
    assert stored["country"] == "Germany"
    assert stored["contactName"] == "Hans Gruber"
    assert stored["contactEmail"] == "hans@phase1-test-g.com"
    assert stored["revenue"] == "$50M"
    assert stored["employeeCount"] == "250"
    assert stored["notes"] == "High priority account"
    assert stored["evidence"] == "Multi-national supply chain modernization."
    assert stored["recommendedService"] == "AI Data Strategy"

    # Cleanup
    await db.companies.delete_one({"_id": stored["_id"]})
    await db.importbatches.delete_one({"_id": ObjectId(batch_id)})

# Test H: Old Company records without new fields do not crash the UI/API
@pytest.mark.asyncio
async def test_h_old_company_records_backward_compatibility(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    old_comp_name = "Legacy Old Company Without New Fields"
    await db.companies.delete_many({"companyName": old_comp_name})

    # Insert old record without evidence or recommendedService
    old_doc = {
        "companyName": old_comp_name,
        "website": "https://legacy-old-company.com",
        "normalizedWebsite": "legacy-old-company.com",
        "industry": "Legacy Industry",
        "country": "USA",
        "createdAt": now,
        "updatedAt": now
    }
    insert_res = await db.companies.insert_one(old_doc)
    old_id = str(insert_res.inserted_id)

    try:
        # 1. API list companies should include it without error
        res_list = await client.get("/api/companies", params={"search": old_comp_name})
        assert res_list.status_code == 200
        data = res_list.json()["data"]["companies"]
        found = next((c for c in data if c["_id"] == old_id), None)
        assert found is not None
        # Does not crash, field is absent or empty
        assert found.get("evidence") in (None, "")
        assert found.get("recommendedService") in (None, "")
    finally:
        await db.companies.delete_one({"_id": ObjectId(old_id)})
