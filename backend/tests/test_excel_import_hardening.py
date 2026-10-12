"""Excel import hardening tests.

Covers: service synonym mapping, flexible headers, URL/dedup normalization,
multiple contacts, CSV + XLS import, template download, invalid-row report
export, and clear upload errors.
"""
import io
import csv
import pytest
import openpyxl
import httpx
from bson import ObjectId
from datetime import datetime, timezone

from app.main import app
from app.config.database import connect_db, close_db, get_db
from app.services.excel_service import (
    TEMPLATE_HEADERS,
    build_import_template,
)
from app.utils.validators import resolve_service, resolve_header

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS_MIME = "application/vnd.ms-excel"
CSV_MIME = "text/csv"


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


# ----------------------------------------------------------------- helpers ---

def create_excel_bytes(headers, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def create_csv_bytes(headers, rows):
    sio = io.StringIO()
    writer = csv.writer(sio)
    writer.writerow(headers)
    for r in rows:
        writer.writerow(r)
    return sio.getvalue().encode("utf-8")


def create_xls_bytes(headers, rows):
    import xlwt
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Sheet1")
    for c, h in enumerate(headers):
        ws.write(0, c, h)
    for r, row in enumerate(rows, start=1):
        for c, val in enumerate(row):
            ws.write(r, c, val or "")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def upload(client, filename, content, mime=None):
    files = {"file": (filename, content, mime)}
    return await client.post("/api/import/excel", files=files)


async def confirm(client, batch_id):
    return await client.post(f"/api/import/{batch_id}/confirm")


# ----------------------------------------------------------------- unit ---

def test_service_synonym_resolution_unit():
    cases = {
        "AI Governance & Council Development": ("AI Governance and Responsible AI", True),
        "AI Governance": ("AI Governance and Responsible AI", True),
        "AI Readiness Assessment": ("AI Readiness and Opportunity Assessments", True),
        "AI Readiness": ("AI Readiness and Opportunity Assessments", True),
        "AI Workshop": ("AI & Automation Workshops", True),
        "Automation Workshop": ("AI & Automation Workshops", True),
        "AI Data Strategy": ("AI Data Strategy", False),          # exact, unmapped
        "AI General Consulting": (None, False),                   # unmappable
    }
    for raw, expected in cases.items():
        canonical, mapped = resolve_service(raw)
        assert (canonical, mapped) == expected, f"{raw!r} -> {(canonical, mapped)}"


def test_flexible_header_resolution_unit():
    cases = {
        "Company": "Company Name",
        "Company Name": "Company Name",
        "Website": "Website",
        "Website URL": "Website",
        "Company Website": "Website",
        "URL": "Website",
        "Evidence": "Evidence",
        "Reason": "Evidence",
        "Trigger": "Evidence",
        "AI Trigger": "Evidence",
        "Recommended Service": "Recommended Service",
        "Service": "Recommended Service",
        "TKSR Service": "Recommended Service",
        "Contact Email": "Contact Email",
    }
    for header, expected in cases.items():
        assert resolve_header(header) == expected, f"{header!r}"


# ----------------------------------------------------------------- services ---

@pytest.mark.asyncio
async def test_service_synonyms_map_to_canonical(client):
    db = get_db()
    synonyms = {
        "AI Governance & Council Development": "AI Governance and Responsible AI",
        "AI Governance": "AI Governance and Responsible AI",
        "AI Readiness Assessment": "AI Readiness and Opportunity Assessments",
        "AI Readiness": "AI Readiness and Opportunity Assessments",
        "AI Workshop": "AI & Automation Workshops",
        "Automation Workshop": "AI & Automation Workshops",
    }
    rows = [
        [f"Synonym Co {i}", f"https://synonym{i}.com", "Expanding AI-ready operations.", raw]
        for i, (raw, _canon) in enumerate(synonyms.items())
    ]
    xlsx = create_excel_bytes(["Company Name", "Website", "Evidence", "Recommended Service"], rows)
    res = await upload(client, "synonyms.xlsx", xlsx)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["summary"]["valid"] == len(synonyms)
    assert data["summary"]["invalid"] == 0

    for row in data["rows"]:
        assert row["status"] == "valid"
        assert row["serviceMapped"] is True
        assert row["recommendedService"] == synonyms[row["originalService"]]
        assert row["mappedService"] == synonyms[row["originalService"]]

    # Confirm into Mongo and verify the logged mapping fields survive
    batch_id = data["batchId"]
    try:
        confirm_res = await confirm(client, batch_id)
        assert confirm_res.status_code == 200
        assert confirm_res.json()["data"]["imported"] == len(synonyms)

        first_raw = list(synonyms)[0]
        # Scope the lookup to THIS test's own fixture row — never a company
        # that merely shares the same originalService value.
        stored = await db.companies.find_one({"companyName": "Synonym Co 0"})
        assert stored is not None
        assert stored["recommendedService"] == synonyms[first_raw]
        assert stored["originalService"] == first_raw
        assert stored["mappedService"] == synonyms[first_raw]
    finally:
        # SAFETY (2026-10-09 incident): delete ONLY the fixture companies this
        # test created ("Synonym Co 0..N"). Never delete by a shared
        # originalService/synonym condition — that wiped 17 real imported
        # companies. Defence in depth: fixture-name AND service must both match.
        fixture_names = [f"Synonym Co {i}" for i in range(len(synonyms))]
        await db.companies.delete_many({
            "companyName": {"$in": fixture_names},
            "originalService": {"$in": list(synonyms)},
        })
        await db.importbatches.delete_one({"_id": ObjectId(batch_id)})


@pytest.mark.asyncio
async def test_exact_canonical_service_stays_unmapped(client):
    xlsx = create_excel_bytes(
        ["Company Name", "Website", "Evidence", "Recommended Service"],
        [["Exact Co", "https://exactco.com", "Valid evidence text.", "AI Strategy Consulting"]],
    )
    res = await upload(client, "exact.xlsx", xlsx)
    assert res.status_code == 200
    row = res.json()["data"]["rows"][0]
    assert row["status"] == "valid"
    assert row["recommendedService"] == "AI Strategy Consulting"
    assert row["serviceMapped"] is False
    assert row["mappedService"] == ""


# ------------------------------------------------------------------ contacts ---

@pytest.mark.asyncio
async def test_multiple_contacts_stored_without_rejection(client):
    db = get_db()
    headers = ["Company Name", "Website", "Evidence", "Recommended Service", "Contact Name", "Contact Email"]
    rows = [[
        "Multi Contact Co", "https://multicontact.com", "Expanding sales automation.",
        "AI Training", "John Doe; Jane Smith", "john@abc.com; jane@abc.com",
    ]]
    xlsx = create_excel_bytes(headers, rows)
    res = await upload(client, "contacts.xlsx", xlsx)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["summary"]["valid"] == 1
    row = data["rows"][0]
    assert row["status"] == "valid"
    assert row["contactName"] == "John Doe; Jane Smith"
    assert row["contactNames"] == ["John Doe", "Jane Smith"]
    assert row["contactEmails"] == ["john@abc.com", "jane@abc.com"]

    batch_id = data["batchId"]
    try:
        confirm_res = await confirm(client, batch_id)
        assert confirm_res.status_code == 200
        stored = await db.companies.find_one({"companyName": "Multi Contact Co"})
        assert stored is not None
        assert stored["contactName"] == "John Doe; Jane Smith"
        assert len(stored["contactNames"]) == 2
        assert len(stored["contactEmails"]) == 2
    finally:
        await db.companies.delete_many({"companyName": "Multi Contact Co"})
        await db.importbatches.delete_one({"_id": ObjectId(batch_id)})


# ------------------------------------------------------- CSV / XLS support ---

@pytest.mark.asyncio
async def test_csv_import(client):
    db = get_db()
    csv_bytes = create_csv_bytes(
        ["Company Name", "Website", "Evidence", "Recommended Service"],
        [["CSV Import Co", "https://csvimport.com", "Expanding export operations with AI.", "AI Training"]],
    )
    res = await upload(client, "leads.csv", csv_bytes, CSV_MIME)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["summary"]["valid"] == 1
    batch_id = data["batchId"]
    try:
        assert (await confirm(client, batch_id)).status_code == 200
        assert await db.companies.find_one({"companyName": "CSV Import Co"}) is not None
    finally:
        await db.companies.delete_many({"companyName": "CSV Import Co"})
        await db.importbatches.delete_one({"_id": ObjectId(batch_id)})


@pytest.mark.asyncio
async def test_xls_import(client):
    db = get_db()
    xls_bytes = create_xls_bytes(
        ["Company Name", "Website", "Evidence", "Recommended Service"],
        [["XLS Import Co", "https://xlsimport.com", "Legacy systems modernisation.", "AI Readiness Assessment"]],
    )
    res = await upload(client, "leads.xls", xls_bytes, XLS_MIME)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["summary"]["valid"] == 1
    row = data["rows"][0]
    assert row["recommendedService"] == "AI Readiness and Opportunity Assessments"
    assert row["serviceMapped"] is True
    batch_id = data["batchId"]
    try:
        assert (await confirm(client, batch_id)).status_code == 200
        assert await db.companies.find_one({"companyName": "XLS Import Co"}) is not None
    finally:
        await db.companies.delete_many({"companyName": "XLS Import Co"})
        await db.importbatches.delete_one({"_id": ObjectId(batch_id)})


# -------------------------------------------------------------- dedup/URLs ---

@pytest.mark.asyncio
async def test_duplicate_website_variants(client):
    variants = [
        "acme.com",
        "www.acme.com",
        "https://acme.com",
        "https://www.acme.com/",
        "ACME.COM/",
    ]
    rows = [[f"Dup Site Co {i}", v, "Valid evidence text.", "AI Strategy Consulting"] for i, v in enumerate(variants)]
    xlsx = create_excel_bytes(["Company Name", "Website", "Evidence", "Recommended Service"], rows)
    res = await upload(client, "dups.xlsx", xlsx)
    assert res.status_code == 200
    data = res.json()["data"]
    # First variant valid; every other variant is a duplicate of the same domain
    assert data["summary"]["valid"] == 1
    assert data["summary"]["duplicates"] == len(variants) - 1
    assert all(r["status"] == "duplicate_in_file" for r in data["rows"][1:])
    assert data["rows"][1]["normalizedWebsite"] == "acme.com"


@pytest.mark.asyncio
async def test_duplicate_website_existing_in_db_detected_at_preview(client):
    """Rows whose domain already exists are flagged existing_in_db at preview time."""
    db = get_db()
    now = datetime.now(timezone.utc)
    await db.companies.insert_one({
        "companyName": "Existing Dup Co",
        "website": "https://dupetest.com",
        "normalizedWebsite": "dupetest.com",
        "evidence": "already here",
        "recommendedService": "AI Training",
        "createdAt": now,
        "updatedAt": now,
    })
    xlsx = create_excel_bytes(
        ["Company Name", "Website", "Evidence", "Recommended Service"],
        [["Existing Dup Co (again)", "https://www.dupetest.com", "Evidence text.", "AI Training"]],
    )
    try:
        res = await upload(client, "redup.xlsx", xlsx)
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["summary"]["existingInDb"] == 1
        assert data["summary"]["valid"] == 0
        assert data["rows"][0]["status"] == "existing_in_db"
        assert data["rows"][0]["normalizedWebsite"] == "dupetest.com"
    finally:
        await db.companies.delete_many({"companyName": "Existing Dup Co"})
        await db.importbatches.delete_one({"_id": ObjectId(data["batchId"])})


@pytest.mark.asyncio
async def test_confirm_skips_database_collision_detected_after_preview(client):
    """A row that was valid at preview but collides with the DB before Commit
    must be skipped by the confirm-time re-check, never duplicated."""
    db = get_db()
    xlsx = create_excel_bytes(
        ["Company Name", "Website", "Evidence", "Recommended Service"],
        [["Race Condition Co", "https://racecond.com", "Evidence text.", "AI Training"]],
    )
    res = await upload(client, "race.xlsx", xlsx)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["summary"]["valid"] == 1
    batch_id = data["batchId"]
    try:
        # Simulate another import winning the race between preview and confirm
        now = datetime.now(timezone.utc)
        await db.companies.insert_one({
            "companyName": "Race Condition Co",
            "website": "https://racecond.com",
            "normalizedWebsite": "racecond.com",
            "evidence": "inserted by another batch",
            "recommendedService": "AI Training",
            "source": "bulk",
            "createdAt": now,
            "updatedAt": now,
        })
        confirm_res = await confirm(client, batch_id)
        assert confirm_res.status_code == 200
        assert confirm_res.json()["data"]["imported"] == 0
        assert confirm_res.json()["data"]["skipped"] == 1
        assert await db.companies.count_documents({"companyName": "Race Condition Co"}) == 1
    finally:
        await db.companies.delete_many({"companyName": "Race Condition Co"})
        await db.importbatches.delete_one({"_id": ObjectId(batch_id)})


# ------------------------------------------------------------- validation ---

@pytest.mark.asyncio
async def test_missing_evidence_is_invalid_with_fix(client):
    xlsx = create_excel_bytes(
        ["Company Name", "Website", "Evidence", "Recommended Service"],
        [["No Evidence Co", "https://noevidence.com", "", "AI Training"]],
    )
    res = await upload(client, "noev.xlsx", xlsx)
    assert res.status_code == 200
    row = res.json()["data"]["rows"][0]
    assert row["status"] == "invalid"
    assert any("Evidence is required" in e for e in row["validationErrors"])
    assert any("Evidence" in f for f in row["suggestedFix"])


@pytest.mark.asyncio
async def test_invalid_website_shows_url_message(client):
    xlsx = create_excel_bytes(
        ["Company Name", "Website", "Evidence", "Recommended Service"],
        [["Bad URL Co", "company", "Valid evidence text.", "AI Training"]],
    )
    res = await upload(client, "badurl.xlsx", xlsx)
    assert res.status_code == 200
    row = res.json()["data"]["rows"][0]
    assert row["status"] == "invalid"
    assert any("Invalid website URL" in e for e in row["validationErrors"])
    assert any("URL" in f for f in row["suggestedFix"])


# ---------------------------------------------------------------- headers ---

@pytest.mark.asyncio
async def test_flexible_headers_accepted(client):
    # Flexible headers: Company, Website URL, Reason (Evidence), Service
    xlsx = create_excel_bytes(
        ["Company", "Website URL", "Reason", "Service"],
        [["Flex Co", "flexco.com", "Expanding cloud data ops with AI automation.", "AI Training"]],
    )
    res = await upload(client, "flex.xlsx", xlsx)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["summary"]["valid"] == 1
    row = data["rows"][0]
    assert row["companyName"] == "Flex Co"
    assert row["recommendedService"] == "AI Training"


@pytest.mark.asyncio
async def test_missing_required_column_clear_error(client):
    xlsx = create_excel_bytes(
        ["Company", "Website URL", "Reason"],
        [["No Service Co", "nosvc.com", "Evidence here."]],
    )
    res = await upload(client, "missing.xlsx", xlsx)
    assert res.status_code == 400
    body = res.json()
    assert body["success"] is False
    assert "Recommended Service" in body["message"]


# --------------------------------------------------- template / report -----

@pytest.mark.asyncio
async def test_template_endpoint(client):
    res = await client.get("/api/import/template")
    assert res.status_code == 200
    assert "TKSR_Import_Template.xlsx" in res.headers.get("content-disposition", "")
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    ws = wb.active
    headers = [c.value for c in ws[1]]
    assert headers == TEMPLATE_HEADERS
    assert ws.max_row == 4  # 1 header + 3 sample rows


@pytest.mark.asyncio
async def test_template_bytes_match_endpoint(client):
    # Both builders produce identical readable workbooks
    assert len(build_import_template()) > 1000


@pytest.mark.asyncio
async def test_invalid_report_endpoint(client):
    headers = ["Company Name", "Website", "Evidence", "Recommended Service"]
    rows = [
        ["Report Valid Co", "https://repvalid.com", "Good evidence.", "AI Training"],
        ["Report Bad Co", "https://repbad.com", "", "AI Training"],  # missing evidence
    ]
    xlsx = create_excel_bytes(headers, rows)
    res = await upload(client, "report.xlsx", xlsx)
    assert res.status_code == 200
    batch_id = res.json()["data"]["batchId"]
    try:
        rep = await client.get(f"/api/import/{batch_id}/invalid-report")
        assert rep.status_code == 200
        assert "invalid_rows.xlsx" in rep.headers.get("content-disposition", "")
        wb = openpyxl.load_workbook(io.BytesIO(rep.content))
        ws = wb.active
        col_headers = [c.value for c in ws[1]]
        assert col_headers == ["Row Number", "Company Name", "Status", "Error", "Suggested Fix"]
        rows_in_report = list(ws.iter_rows(min_row=2, values_only=True))
        assert len(rows_in_report) == 1
        assert rows_in_report[0][1] == "Report Bad Co"
        assert rows_in_report[0][3] is not None
    finally:
        await db_cleanup(batch_id)


async def db_cleanup(batch_id):
    db = get_db()
    await db.importbatches.delete_one({"_id": ObjectId(batch_id)})
    await db.companies.delete_many({"companyName": "Report Valid Co"})
    await db.companies.delete_many({"companyName": "Report Bad Co"})


# ------------------------------------------------------------- errors -------

@pytest.mark.asyncio
async def test_unsupported_format_clear_error(client):
    res = await upload(client, "data.txt", b"not an excel file", "text/plain")
    assert res.status_code == 400
    assert "Unsupported file format" in res.json()["message"]


@pytest.mark.asyncio
async def test_oversize_file_413(client):
    big = b"x" * (11 * 1024 * 1024)
    res = await upload(client, "big.xlsx", big, XLSX_MIME)
    assert res.status_code == 413
    assert "too large" in res.json()["message"].lower()


@pytest.mark.asyncio
async def test_confirm_imports_full_end_to_end_with_hardening(client):
    db = get_db()
    headers = ["Company", "Website URL", "Reason", "Service", "Contact Name", "Contact Email"]
    rows = [[
        "Hardening E2E Co", "www.hardening-e2e.com", "Evidence-driven AI readiness gap.",
        "AI Governance", "Alice; Bob", "alice@h-e2e.com; bob@h-e2e.com",
    ]]
    xlsx = create_excel_bytes(headers, rows)
    res = await upload(client, "e2e.xlsx", xlsx)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["summary"]["valid"] == 1
    batch_id = data["batchId"]
    try:
        assert (await confirm(client, batch_id)).status_code == 200
        stored = await db.companies.find_one({"companyName": "Hardening E2E Co"})
        assert stored is not None
        assert stored["normalizedWebsite"] == "hardening-e2e.com"
        assert stored["recommendedService"] == "AI Governance and Responsible AI"
        assert stored["originalService"] == "AI Governance"
        assert len(stored["contactNames"]) == 2
    finally:
        await db.companies.delete_many({"companyName": "Hardening E2E Co"})
        await db.importbatches.delete_one({"_id": ObjectId(batch_id)})