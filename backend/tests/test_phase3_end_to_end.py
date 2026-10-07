import io
import pytest
import openpyxl
from bson import ObjectId
from datetime import datetime, timezone, timedelta
import httpx

from app.main import app
from app.config.database import connect_db, close_db, get_db
from app.services.scheduler_service import schedule_sequence_steps, process_automated_follow_ups
from app.services.email_service import send_outreach_email
from app.services.contact_service import extract_contacts_from_website

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

# =========================================================================
# TEST A: Realistic Excel Import -> MongoDB Integrity
# =========================================================================
@pytest.mark.asyncio
async def test_phase3_a_realistic_excel_import_to_mongodb(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    comp_name = "Phase3 Apex Logistics"
    await db.companies.delete_many({"companyName": comp_name})

    headers = [
        "Company Name", "Website", "Industry", "Country",
        "Evidence", "Recommended Service", "Contact Name", "Contact Email"
    ]
    evidence_text = "Deploying IoT telematics across 500 delivery vehicles to reduce transit fuel burn."
    service_text = "AI & Automation Workshops"
    rows = [
        [
            comp_name, "https://apexlogistics-p3.com", "Logistics", "United States",
            evidence_text, service_text, "Morgan Drake", "morgan@apexlogistics-p3.com"
        ]
    ]
    excel_bytes = create_excel_bytes(headers, rows)

    try:
        # Step 1: Upload Excel
        files = {"file": ("phase3_import.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        res = await client.post("/api/import/excel", files=files)
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["summary"]["valid"] == 1
        assert data["rows"][0]["evidence"] == evidence_text
        assert data["rows"][0]["recommendedService"] == service_text

        # Step 2: Confirm Batch Import
        batch_id = data["batchId"]
        confirm_res = await client.post(f"/api/import/{batch_id}/confirm")
        assert confirm_res.status_code == 200
        assert confirm_res.json()["data"]["imported"] == 1

        # Step 3: MongoDB Verification
        company = await db.companies.find_one({"companyName": comp_name})
        assert company is not None
        assert company["evidence"] == evidence_text
        assert company["recommendedService"] == service_text
        assert company["website"] == "https://apexlogistics-p3.com"
    finally:
        await db.companies.delete_many({"companyName": comp_name})
        if "batch_id" in locals():
            await db.importbatches.delete_one({"_id": ObjectId(batch_id)})

# =========================================================================
# TEST B: Phase 1 Validation Regression (Strict Validation)
# =========================================================================
@pytest.mark.asyncio
async def test_phase3_b_validation_regression_blocks_invalid_rows(client):
    db = get_db()
    headers = ["Company Name", "Website", "Evidence", "Recommended Service"]
    rows = [
        ["Valid Co", "https://valid-p3.com", "Valid evidence text", "AI Strategy Consulting"],
        ["Missing Evidence Co", "https://no-ev-p3.com", "", "AI Strategy Consulting"],
        ["Invalid Service Co", "https://inv-svc-p3.com", "Has evidence", "AI General Consulting"]
    ]
    excel_bytes = create_excel_bytes(headers, rows)

    files = {"file": ("phase3_invalid.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    response = await client.post("/api/import/excel", files=files)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["summary"]["total"] == 3
    assert data["summary"]["valid"] == 1
    assert data["summary"]["invalid"] == 2

    # Check row errors
    invalid_rows = [r for r in data["rows"] if r["status"] == "invalid"]
    assert len(invalid_rows) == 2
    err_msgs = [e for r in invalid_rows for e in r.get("validationErrors", [])]
    assert any("Evidence" in msg for msg in err_msgs)
    assert any("Recommended Service" in msg for msg in err_msgs)

    # Confirm batch: Only the 1 valid row is imported, invalid rows rejected
    batch_id = data["batchId"]
    try:
        confirm_res = await client.post(f"/api/import/{batch_id}/confirm")
        assert confirm_res.status_code == 200
        assert confirm_res.json()["data"]["imported"] == 1

        # Verify invalid companies were never inserted into MongoDB
        assert await db.companies.find_one({"companyName": "Missing Evidence Co"}) is None
        assert await db.companies.find_one({"companyName": "Invalid Service Co"}) is None
    finally:
        await db.companies.delete_many({"companyName": "Valid Co"})
        await db.importbatches.delete_one({"_id": ObjectId(batch_id)})

# =========================================================================
# TEST C: Company Retrieval & UI Display Compatibility
# =========================================================================
@pytest.mark.asyncio
async def test_phase3_c_company_retrieval_and_legacy_compatibility(client):
    db = get_db()
    now = datetime.now(timezone.utc)

    # 1. Company with fields
    c_new = await db.companies.insert_one({
        "companyName": "Phase3 Modern Co",
        "website": "https://modern-p3.com",
        "normalizedWebsite": "modern-p3.com",
        "evidence": "Robotic automated quality control line.",
        "recommendedService": "AI Readiness and Opportunity Assessments",
        "createdAt": now,
        "updatedAt": now
    })
    # 2. Legacy company without fields
    c_legacy = await db.companies.insert_one({
        "companyName": "Phase3 Legacy Co",
        "website": "https://legacy-p3.com",
        "normalizedWebsite": "legacy-p3.com",
        "createdAt": now,
        "updatedAt": now
    })

    try:
        # Retrieve modern
        res_new = await client.get(f"/api/companies/{str(c_new.inserted_id)}")
        assert res_new.status_code == 200
        d_new = res_new.json()["data"]
        assert d_new["evidence"] == "Robotic automated quality control line."
        assert d_new["recommendedService"] == "AI Readiness and Opportunity Assessments"

        # Retrieve legacy (graceful handling, no 500 error)
        res_legacy = await client.get(f"/api/companies/{str(c_legacy.inserted_id)}")
        assert res_legacy.status_code == 200
        d_legacy = res_legacy.json()["data"]
        assert d_legacy.get("evidence") in (None, "")
        assert d_legacy.get("recommendedService") in (None, "")
    finally:
        await db.companies.delete_one({"_id": c_new.inserted_id})
        await db.companies.delete_one({"_id": c_legacy.inserted_id})

# =========================================================================
# TEST D & E: Decision Maker Discovery & Public Email Classification
# =========================================================================
@pytest.mark.asyncio
async def test_phase3_d_e_decision_maker_and_email_classification():
    db = get_db()
    comp_res = await db.companies.insert_one({
        "companyName": "Phase3 Pharma Tech",
        "website": "https://phase3pharmatech.com",
        "normalizedWebsite": "phase3pharmatech.com",
        "industry": "Pharmaceuticals",
        "status": "pending"
    })
    cid = str(comp_res.inserted_id)

    # Crawled leadership page with 1 exact public email and 1 name without email
    team_html = """
    <div class="team">
        <h3>Dr. Evelyn Reed</h3>
        <p>Chief Technology Officer of Phase3 Pharma Tech</p>
        <a href="mailto:evelyn.reed@phase3pharmatech.com">evelyn.reed@phase3pharmatech.com</a>
        <h3>Marcus Vance</h3>
        <p>Chief Operating Officer of Phase3 Pharma Tech</p>
    </div>
    """
    await db.crawledpages.insert_one({
        "companyId": comp_res.inserted_id,
        "url": "https://phase3pharmatech.com/leadership",
        "pageType": "team",
        "crawlStatus": "completed",
        "content": "Dr. Evelyn Reed, Chief Technology Officer. Marcus Vance, Chief Operating Officer.",
        "html": team_html,
        "wordCount": 100
    })

    try:
        contacts = await extract_contacts_from_website(cid)
        assert len(contacts) >= 2
        evelyn = next((c for c in contacts if "Evelyn Reed" in c["name"]), None)
        marcus = next((c for c in contacts if "Marcus Vance" in c["name"]), None)

        assert evelyn is not None
        assert evelyn["email"] == "evelyn.reed@phase3pharmatech.com"
        assert evelyn.get("emailStatus") in ("EXACT_FOUND", "VERIFIED")

        # Marcus has no public email on page -> MUST NOT hallucinate synthetic email
        assert marcus is not None
        assert marcus.get("emailStatus") in ("NOT_FOUND", "PATTERN_GENERATED")
        if marcus.get("emailStatus") == "NOT_FOUND":
            assert marcus.get("email") is None or marcus.get("email") == ""
    finally:
        await db.companies.delete_one({"_id": comp_res.inserted_id})
        await db.crawledpages.delete_many({"companyId": comp_res.inserted_id})
        await db.contacts.delete_many({"companyId": comp_res.inserted_id})

# =========================================================================
# TEST G-M: Outreach Generation, Service Consistency, Anti-Hallucination, Audit Fields
# =========================================================================
@pytest.mark.asyncio
async def test_phase3_g_to_m_outreach_generation_full_consistency(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    comp_name = "Phase3 Consistency Dynamics"
    await db.companies.delete_many({"companyName": comp_name})

    evidence_text = "Scaling multi-site industrial cold storage automation and predictive maintenance."
    service_text = "AI Data Strategy"

    comp = {
        "companyName": comp_name,
        "website": "https://phase3consistency.com",
        "normalizedWebsite": "phase3consistency.com",
        "evidence": evidence_text,
        "recommendedService": service_text,
        "createdAt": now,
        "updatedAt": now
    }
    c_res = await db.companies.insert_one(comp)
    comp_id = str(c_res.inserted_id)

    # Decision maker
    contact = {
        "companyId": c_res.inserted_id,
        "name": "Sarah Connor",
        "title": "Chief Technology Officer",
        "email": "sarah.connor@phase3consistency.com",
        "roleCategory": "cto",
        "createdAt": now,
        "updatedAt": now
    }
    await db.contacts.insert_one(contact)

    # Ensure NO CompanyResearch exists (Test G)
    await db.companyresearches.delete_many({"companyId": c_res.inserted_id})
    assert await db.companyresearches.count_documents({"companyId": c_res.inserted_id}) == 0

    try:
        # Frontend attempts to override service with "AI Consulting" (Test J: Override protection)
        payload = {
            "focusService": "AI Consulting",
            "selectedFocusService": "AI Strategy Consulting"
        }
        res = await client.post(f"/api/companies/{comp_id}/outreach/generate", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        messages = data["data"]
        assert len(messages) == 3

        # Test L: 3-step sequence consistency
        for i, msg in enumerate(messages, 1):
            assert msg["step"] == i
            assert msg["status"] == "draft"  # Starts as draft for human approval (Test N)
            # Test M: Audit fields persisted
            assert msg["evidenceUsed"] == evidence_text
            assert msg["recommendedServiceUsed"] == service_text
            # Anti-hallucination check
            combined_text = (msg["subject"] + " " + msg["bodyText"]).lower()
            assert "ai data strategy" in combined_text

        # Verify audit fields directly in MongoDB
        db_messages = await db.outreachmessages.find({"companyId": c_res.inserted_id}).to_list(10)
        assert len(db_messages) == 3
        for m in db_messages:
            assert m["evidenceUsed"] == evidence_text
            assert m["recommendedServiceUsed"] == service_text
    finally:
        await db.companies.delete_one({"_id": c_res.inserted_id})
        await db.contacts.delete_many({"companyId": c_res.inserted_id})
        await db.outreachmessages.delete_many({"companyId": c_res.inserted_id})

# =========================================================================
# TEST N & O: Human Approval Gate & Safe SMTP Dispatch
# =========================================================================
@pytest.mark.asyncio
async def test_phase3_n_o_human_approval_gate_and_safe_smtp(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    comp_name = "Phase3 Approval Aerospace"
    await db.companies.delete_many({"companyName": comp_name})

    comp = {
        "companyName": comp_name,
        "website": "https://phase3aero.com",
        "normalizedWebsite": "phase3aero.com",
        "evidence": "Manufacturing high-precision turbine components with sensor analytics.",
        "recommendedService": "AI Governance and Responsible AI",
        "createdAt": now,
        "updatedAt": now
    }
    c_res = await db.companies.insert_one(comp)
    comp_id = str(c_res.inserted_id)

    try:
        # Generate sequence -> drafts
        gen_res = await client.post(f"/api/companies/{comp_id}/outreach/generate", json={})
        assert gen_res.status_code == 200
        messages = gen_res.json()["data"]
        step1_id = messages[0].get("_id") or messages[0].get("id")

        # 1. Verify draft status initially
        msg_db = await db.outreachmessages.find_one({"_id": ObjectId(step1_id)})
        assert msg_db["status"] == "draft"

        # 2. Human approval via schedule endpoint
        sched_res = await client.post(
            f"/api/companies/{comp_id}/outreach/schedule",
            json={"schedules": [{"step": 1, "delayDays": 0}, {"step": 2, "delayDays": 3}]}
        )
        assert sched_res.status_code == 200
        msg_approved = await db.outreachmessages.find_one({"_id": ObjectId(step1_id)})
        assert msg_approved["status"] == "approved"

        # 3. Safe Dispatch (Test O)
        send_res = await client.post(
            f"/api/outreach/{step1_id}/send",
            json={"recipientEmail": "director@phase3aero.com"}
        )
        assert send_res.status_code == 200
        assert send_res.json()["success"] is True

        # Verify status transitions to sent and sentAt timestamp is recorded
        msg_sent = await db.outreachmessages.find_one({"_id": ObjectId(step1_id)})
        assert msg_sent["status"] == "sent"
        assert msg_sent.get("sentAt") is not None
        assert msg_sent.get("recipientEmail") == "director@phase3aero.com"
    finally:
        await db.companies.delete_one({"_id": c_res.inserted_id})
        await db.outreachmessages.delete_many({"companyId": c_res.inserted_id})
        await db.outreachrecords.delete_many({"companyId": c_res.inserted_id})

# =========================================================================
# TEST P & Q: Follow-Up Scheduler & Reply-Aware Stopping
# =========================================================================
@pytest.mark.asyncio
async def test_phase3_p_q_scheduler_stops_on_prospect_reply():
    db = get_db()
    now = datetime.now(timezone.utc)
    comp_oid = ObjectId()

    # Create an OutreachRecord where Initial Email was SENT, Follow-up 1 is due (scheduledAt <= now)
    record = {
        "companyId": comp_oid,
        "companyName": "Phase3 Reply Corp",
        "recipientEmail": "prospect@phase3reply.com",
        "initialEmail": {
            "status": "SENT",
            "sentAt": now - timedelta(days=4)
        },
        "followUp1": {
            "status": "PENDING",
            "scheduledAt": now - timedelta(hours=1)  # Due!
        },
        "followUp2": {
            "status": "PENDING",
            "scheduledAt": now + timedelta(days=3)
        },
        "replyStatus": "REPLIED",  # Prospect replied!
        "updatedAt": now
    }
    rec_res = await db.outreachrecords.insert_one(record)

    try:
        # Run automated follow-up processor
        await process_automated_follow_ups()

        # Follow-up 1 must remain PENDING because replyStatus is REPLIED
        updated_rec = await db.outreachrecords.find_one({"_id": rec_res.inserted_id})
        assert updated_rec["followUp1"]["status"] == "PENDING"
        assert updated_rec["replyStatus"] == "REPLIED"
    finally:
        await db.outreachrecords.delete_one({"_id": rec_res.inserted_id})

# =========================================================================
# TEST R: Open Pixel & Link Click Tracking
# =========================================================================
@pytest.mark.asyncio
async def test_phase3_r_open_and_click_tracking(client):
    db = get_db()
    now = datetime.now(timezone.utc)

    msg = {
        "companyId": ObjectId(),
        "step": 1,
        "status": "sent",
        "subject": "Intro",
        "bodyText": "Hello",
        "openCount": 0,
        "clickCount": 0,
        "createdAt": now,
        "updatedAt": now
    }
    m_res = await db.outreachmessages.insert_one(msg)
    mid = str(m_res.inserted_id)

    try:
        # 1. Trigger Open Pixel Tracking
        open_res = await client.get(f"/api/track/open/{mid}.png")
        assert open_res.status_code == 200
        assert open_res.headers["content-type"] == "image/gif"

        # Verify DB updated
        m_after_open = await db.outreachmessages.find_one({"_id": m_res.inserted_id})
        assert m_after_open["openCount"] == 1
        assert m_after_open.get("openedAt") is not None

        # 2. Trigger Link Click Tracking
        dest_url = "https://tksr.io/services/ai-strategy"
        click_res = await client.get(f"/api/track/click/{mid}?url={dest_url}", follow_redirects=False)
        assert click_res.status_code == 307
        assert click_res.headers["location"] == dest_url

        # Verify DB updated
        m_after_click = await db.outreachmessages.find_one({"_id": m_res.inserted_id})
        assert m_after_click["clickCount"] == 1
        assert m_after_click.get("clickedAt") is not None
    finally:
        await db.outreachmessages.delete_one({"_id": m_res.inserted_id})

# =========================================================================
# TEST S, T, U: Missing Field Blockers & Legacy Company Graceful Handling
# =========================================================================
@pytest.mark.asyncio
async def test_phase3_s_t_u_missing_field_blockers(client):
    db = get_db()
    now = datetime.now(timezone.utc)

    # S: Missing Evidence
    c_s = await db.companies.insert_one({
        "companyName": "Phase3 Test S",
        "website": "https://tests-p3.com",
        "normalizedWebsite": "tests-p3.com",
        "evidence": "",
        "recommendedService": "AI Strategy Consulting",
        "createdAt": now
    })

    # T: Missing Service
    c_t = await db.companies.insert_one({
        "companyName": "Phase3 Test T",
        "website": "https://testt-p3.com",
        "normalizedWebsite": "testt-p3.com",
        "evidence": "Valid evidence text",
        "recommendedService": "",
        "createdAt": now
    })

    # U: Legacy company (both missing)
    c_u = await db.companies.insert_one({
        "companyName": "Phase3 Test U Legacy",
        "website": "https://testu-p3.com",
        "normalizedWebsite": "testu-p3.com",
        "createdAt": now
    })

    try:
        # S blocks with 400
        res_s = await client.post(f"/api/companies/{str(c_s.inserted_id)}/outreach/generate", json={})
        assert res_s.status_code == 400
        assert "Evidence" in res_s.json()["message"]

        # T blocks with 400
        res_t = await client.post(f"/api/companies/{str(c_t.inserted_id)}/outreach/generate", json={})
        assert res_t.status_code == 400
        assert "Recommended Service" in res_t.json()["message"]

        # U blocks with 400 without crashing
        res_u = await client.post(f"/api/companies/{str(c_u.inserted_id)}/outreach/generate", json={})
        assert res_u.status_code == 400
        assert "Evidence" in res_u.json()["message"] or "Recommended Service" in res_u.json()["message"]
    finally:
        await db.companies.delete_one({"_id": c_s.inserted_id})
        await db.companies.delete_one({"_id": c_t.inserted_id})
        await db.companies.delete_one({"_id": c_u.inserted_id})

# =========================================================================
# TEST V: Independent CompanyResearch Regression
# =========================================================================
@pytest.mark.asyncio
async def test_phase3_v_independent_company_research_capability(client):
    db = get_db()
    now = datetime.now(timezone.utc)

    comp = await db.companies.insert_one({
        "companyName": "Phase3 Research Regression Co",
        "website": "https://research-reg-p3.com",
        "normalizedWebsite": "research-reg-p3.com",
        "createdAt": now
    })
    cid = str(comp.inserted_id)

    # Insert a crawled page so research service has input
    await db.crawledpages.insert_one({
        "companyId": comp.inserted_id,
        "crawlStatus": "completed",
        "contentAvailable": True,
        "wordCount": 100,
        "depth": 1,
        "content": "Leading developer of next generation robotics and automated optical scanning.",
        "url": "https://research-reg-p3.com"
    })

    try:
        # GET research returns empty message gracefully
        get_res = await client.get(f"/api/companies/{cid}/research")
        assert get_res.status_code == 200
        assert get_res.json()["data"] is None

        # POST research triggers independent research
        post_res = await client.post(f"/api/companies/{cid}/research")
        assert post_res.status_code == 200
        assert post_res.json()["success"] is True

        # Verify research stored in MongoDB companyresearches
        r_doc = await db.companyresearches.find_one({"companyId": comp.inserted_id})
        assert r_doc is not None
        assert "summary" in r_doc
    finally:
        await db.companies.delete_one({"_id": comp.inserted_id})
        await db.crawledpages.delete_many({"companyId": comp.inserted_id})
        await db.companyresearches.delete_many({"companyId": comp.inserted_id})

# =========================================================================
# TEST Z: Complete End-to-End Pipeline Dry Run
# =========================================================================
@pytest.mark.asyncio
async def test_phase3_z_full_end_to_end_pipeline_dry_run(client):
    db = get_db()
    comp_name = "Phase3 End2End Pipeline Corp"
    await db.companies.delete_many({"companyName": comp_name})

    evidence_text = "Integrating AI computer vision cameras into automotive parts manufacturing."
    service_text = "AI Readiness and Opportunity Assessments"

    # Step 1: Excel Import via /api/import/excel and confirm
    headers = ["Company Name", "Website", "Evidence", "Recommended Service", "Contact Name", "Contact Email"]
    rows = [[comp_name, "https://e2e-pipeline-p3.com", evidence_text, service_text, "Alex Mercer", "alex@e2e-pipeline-p3.com"]]
    excel_bytes = create_excel_bytes(headers, rows)

    files = {"file": ("e2e.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    import_res = await client.post("/api/import/excel", files=files)
    assert import_res.status_code == 200
    batch_id = import_res.json()["data"]["batchId"]

    confirm_res = await client.post(f"/api/import/{batch_id}/confirm")
    assert confirm_res.status_code == 200
    assert confirm_res.json()["data"]["imported"] == 1

    company = await db.companies.find_one({"companyName": comp_name})
    assert company is not None
    cid = str(company["_id"])

    try:
        # Step 2: Contact Check (Imported with company)
        assert company.get("contactName") == "Alex Mercer"
        assert company.get("contactEmail") == "alex@e2e-pipeline-p3.com"

        # Step 3: Outreach Generation (Decoupled from CompanyResearch)
        gen_res = await client.post(f"/api/companies/{cid}/outreach/generate", json={})
        assert gen_res.status_code == 200
        messages = gen_res.json()["data"]
        assert len(messages) == 3

        step1_id = messages[0].get("_id") or messages[0].get("id")
        assert messages[0]["evidenceUsed"] == evidence_text
        assert messages[0]["recommendedServiceUsed"] == service_text

        # Step 4: Human Approval
        sched_res = await client.post(
            f"/api/companies/{cid}/outreach/schedule",
            json={"schedules": [{"step": 1, "delayDays": 0}]}
        )
        assert sched_res.status_code == 200

        # Step 5: Safe Dispatch
        send_res = await client.post(f"/api/outreach/{step1_id}/send", json={"recipientEmail": "alex@e2e-pipeline-p3.com"})
        assert send_res.status_code == 200

        # Step 6: Engagement Tracking
        open_res = await client.get(f"/api/track/open/{step1_id}.png")
        assert open_res.status_code == 200
        click_res = await client.get(f"/api/track/click/{step1_id}?url=https://example.com", follow_redirects=False)
        assert click_res.status_code == 307

        m_sent = await db.outreachmessages.find_one({"_id": ObjectId(step1_id)})
        assert m_sent["openCount"] >= 1
        assert m_sent["clickCount"] >= 1

        # Step 7: Prospect Reply Simulation & Follow-up Halting
        record = await db.outreachrecords.find_one({"companyId": company["_id"]})
        if record:
            # Mark prospect as replied
            await client.patch(f"/api/outreach/records/{str(record['_id'])}/reply", json={"replyStatus": "REPLIED"})
            rec_updated = await db.outreachrecords.find_one({"_id": record["_id"]})
            assert rec_updated["replyStatus"] == "REPLIED"

            # Verify scheduler respects reply and halts follow-ups
            await process_automated_follow_ups()
            rec_check = await db.outreachrecords.find_one({"_id": record["_id"]})
            assert rec_check["followUp1"]["status"] != "SENT"

    finally:
        await db.companies.delete_many({"companyName": comp_name})
        await db.contacts.delete_many({"companyId": company["_id"]})
        await db.outreachmessages.delete_many({"companyId": company["_id"]})
        await db.outreachrecords.delete_many({"companyId": company["_id"]})
        await db.importbatches.delete_one({"_id": ObjectId(batch_id)})
