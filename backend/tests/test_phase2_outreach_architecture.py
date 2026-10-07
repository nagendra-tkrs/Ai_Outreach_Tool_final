import io
import pytest
from bson import ObjectId
from datetime import datetime, timezone
import httpx

from app.main import app
from app.config.database import connect_db, close_db, get_db
from app.services.outreach_service import generate_outreach_sequence
from app.services.ai_service import generate_fallback_outreach

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

# TEST A — No CompanyResearch
@pytest.mark.asyncio
async def test_a_no_company_research_generates_outreach(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    comp_name = "Phase2 Test A Logistics"
    await db.companies.delete_many({"companyName": comp_name})

    # Create company with valid Evidence and Recommended Service
    comp = {
        "companyName": comp_name,
        "website": "https://phase2-test-a.com",
        "normalizedWebsite": "phase2-test-a.com",
        "evidence": "Expanding automated distribution operations and fleet tracking.",
        "recommendedService": "AI & Automation Workshops",
        "createdAt": now,
        "updatedAt": now
    }
    c_res = await db.companies.insert_one(comp)
    comp_id = str(c_res.inserted_id)

    # Insert decision maker
    contact = {
        "companyId": c_res.inserted_id,
        "name": "Alex Mercer",
        "title": "VP of Operations",
        "email": "alex.mercer@phase2-test-a.com",
        "roleCategory": "coo",
        "createdAt": now,
        "updatedAt": now
    }
    await db.contacts.insert_one(contact)

    # Explicitly ensure NO CompanyResearch exists for this company
    await db.companyresearches.delete_many({"companyId": c_res.inserted_id})
    research_count = await db.companyresearches.count_documents({"companyId": c_res.inserted_id})
    assert research_count == 0

    try:
        # Call API endpoint
        res = await client.post(f"/api/companies/{comp_id}/outreach/generate", json={})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        messages = data["data"]
        assert len(messages) == 3
        assert [m["step"] for m in messages] == [1, 2, 3]
    finally:
        await db.companies.delete_one({"_id": c_res.inserted_id})
        await db.contacts.delete_many({"companyId": c_res.inserted_id})
        await db.outreachmessages.delete_many({"companyId": c_res.inserted_id})

# TEST B — Service Consistency
@pytest.mark.asyncio
async def test_b_service_consistency_across_all_steps(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    comp_name = "Phase2 Test B Consistent"
    await db.companies.delete_many({"companyName": comp_name})

    target_service = "AI Data Strategy"
    comp = {
        "companyName": comp_name,
        "website": "https://phase2-test-b.com",
        "normalizedWebsite": "phase2-test-b.com",
        "evidence": "Modernizing data pipelines across cloud infrastructure.",
        "recommendedService": target_service,
        "createdAt": now,
        "updatedAt": now
    }
    c_res = await db.companies.insert_one(comp)
    comp_id = str(c_res.inserted_id)

    try:
        res = await client.post(f"/api/companies/{comp_id}/outreach/generate", json={})
        assert res.status_code == 200
        messages = res.json()["data"]
        assert len(messages) == 3

        # Every email step must consistently use target_service
        for m in messages:
            assert m["focusService"] == target_service
            assert m["recommendedServiceUsed"] == target_service
            assert target_service in m["bodyText"] or target_service in m["bodyHtml"] or target_service in m["subject"]
    finally:
        await db.companies.delete_one({"_id": c_res.inserted_id})
        await db.outreachmessages.delete_many({"companyId": c_res.inserted_id})

# TEST C — Evidence Personalization Changes
@pytest.mark.asyncio
async def test_c_evidence_personalization_changes_accordingly(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    comp_name = "Phase2 Test C Adaptive"
    await db.companies.delete_many({"companyName": comp_name})

    evidence_a = "Building decentralized microgrid power storage systems."
    comp = {
        "companyName": comp_name,
        "website": "https://phase2-test-c.com",
        "normalizedWebsite": "phase2-test-c.com",
        "evidence": evidence_a,
        "recommendedService": "AI Strategy Consulting",
        "createdAt": now,
        "updatedAt": now
    }
    c_res = await db.companies.insert_one(comp)
    comp_id = str(c_res.inserted_id)

    try:
        # Run with Evidence A
        res_a = await client.post(f"/api/companies/{comp_id}/outreach/generate", json={})
        assert res_a.status_code == 200
        msgs_a = res_a.json()["data"]
        assert msgs_a[0]["evidenceUsed"] == evidence_a

        # Now update company to Evidence B
        evidence_b = "Expanding cold-storage pharmaceutical transport fleets."
        await db.companies.update_one({"_id": c_res.inserted_id}, {"$set": {"evidence": evidence_b}})

        # Run with Evidence B
        res_b = await client.post(f"/api/companies/{comp_id}/outreach/generate", json={})
        assert res_b.status_code == 200
        msgs_b = res_b.json()["data"]
        assert msgs_b[0]["evidenceUsed"] == evidence_b
        assert msgs_b[0]["evidenceUsed"] != msgs_a[0]["evidenceUsed"]
    finally:
        await db.companies.delete_one({"_id": c_res.inserted_id})
        await db.outreachmessages.delete_many({"companyId": c_res.inserted_id})

# TEST D — Frontend Override Protection
@pytest.mark.asyncio
async def test_d_frontend_override_protection(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    comp_name = "Phase2 Test D Override"
    await db.companies.delete_many({"companyName": comp_name})

    authoritative_service = "AI Data Strategy"
    comp = {
        "companyName": comp_name,
        "website": "https://phase2-test-d.com",
        "normalizedWebsite": "phase2-test-d.com",
        "evidence": "Centralizing sensor logs and IoT telemetry data.",
        "recommendedService": authoritative_service,
        "createdAt": now,
        "updatedAt": now
    }
    c_res = await db.companies.insert_one(comp)
    comp_id = str(c_res.inserted_id)

    try:
        # Frontend maliciously or accidentally passes focusService = "AI Training"
        payload = {"focusService": "AI Training"}
        res = await client.post(f"/api/companies/{comp_id}/outreach/generate", json=payload)
        assert res.status_code == 200
        messages = res.json()["data"]

        # Backend MUST reject frontend override and use authoritative_service (AI Data Strategy)
        for m in messages:
            assert m["focusService"] == authoritative_service
            assert m["recommendedServiceUsed"] == authoritative_service
            assert m["recommendedServiceUsed"] != "AI Training"
    finally:
        await db.companies.delete_one({"_id": c_res.inserted_id})
        await db.outreachmessages.delete_many({"companyId": c_res.inserted_id})

# TEST E — Limited Evidence
@pytest.mark.asyncio
async def test_e_limited_evidence_no_hallucinations(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    comp_name = "Phase2 Test E Limited"
    await db.companies.delete_many({"companyName": comp_name})

    minimal_evidence = "The company is expanding its logistics operations."
    comp = {
        "companyName": comp_name,
        "website": "https://phase2-test-e.com",
        "normalizedWebsite": "phase2-test-e.com",
        "evidence": minimal_evidence,
        "recommendedService": "AI Strategy Consulting",
        "createdAt": now,
        "updatedAt": now
    }
    c_res = await db.companies.insert_one(comp)
    comp_id = str(c_res.inserted_id)

    try:
        res = await client.post(f"/api/companies/{comp_id}/outreach/generate", json={})
        assert res.status_code == 200
        messages = res.json()["data"]
        for m in messages:
            assert m["evidenceUsed"] == minimal_evidence
            assert m["recommendedServiceUsed"] == "AI Strategy Consulting"
    finally:
        await db.companies.delete_one({"_id": c_res.inserted_id})
        await db.outreachmessages.delete_many({"companyId": c_res.inserted_id})

# TEST F — Same Inputs Across All Emails
@pytest.mark.asyncio
async def test_f_same_inputs_across_all_emails(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    comp_name = "Phase2 Test F Uniform"
    await db.companies.delete_many({"companyName": comp_name})

    test_evidence = "Automating retail fulfillment inventory counters."
    test_service = "AI & Automation Workshops"
    comp = {
        "companyName": comp_name,
        "website": "https://phase2-test-f.com",
        "normalizedWebsite": "phase2-test-f.com",
        "evidence": test_evidence,
        "recommendedService": test_service,
        "createdAt": now,
        "updatedAt": now
    }
    c_res = await db.companies.insert_one(comp)
    comp_id = str(c_res.inserted_id)

    try:
        res = await client.post(f"/api/companies/{comp_id}/outreach/generate", json={})
        assert res.status_code == 200
        messages = res.json()["data"]
        assert len(messages) == 3

        # email1.evidenceUsed == company.evidence == email2.evidenceUsed == email3.evidenceUsed
        assert messages[0]["evidenceUsed"] == test_evidence
        assert messages[1]["evidenceUsed"] == test_evidence
        assert messages[2]["evidenceUsed"] == test_evidence

        # email1.recommendedServiceUsed == company.recommendedService == email2 == email3
        assert messages[0]["recommendedServiceUsed"] == test_service
        assert messages[1]["recommendedServiceUsed"] == test_service
        assert messages[2]["recommendedServiceUsed"] == test_service
    finally:
        await db.companies.delete_one({"_id": c_res.inserted_id})
        await db.outreachmessages.delete_many({"companyId": c_res.inserted_id})

# TEST G — Audit Fields in MongoDB
@pytest.mark.asyncio
async def test_g_audit_fields_persisted_in_mongodb(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    comp_name = "Phase2 Test G Audit"
    await db.companies.delete_many({"companyName": comp_name})

    test_evidence = "Deploying automated optical inspection for circuit boards."
    test_service = "AI Governance and Responsible AI"
    comp = {
        "companyName": comp_name,
        "website": "https://phase2-test-g.com",
        "normalizedWebsite": "phase2-test-g.com",
        "evidence": test_evidence,
        "recommendedService": test_service,
        "createdAt": now,
        "updatedAt": now
    }
    c_res = await db.companies.insert_one(comp)
    comp_id = str(c_res.inserted_id)

    try:
        res = await client.post(f"/api/companies/{comp_id}/outreach/generate", json={})
        assert res.status_code == 200

        # Query MongoDB directly
        db_messages = await db.outreachmessages.find({"companyId": c_res.inserted_id}).to_list(10)
        assert len(db_messages) == 3

        for msg in db_messages:
            assert "evidenceUsed" in msg
            assert "recommendedServiceUsed" in msg
            assert msg["evidenceUsed"] == test_evidence
            assert msg["recommendedServiceUsed"] == test_service
    finally:
        await db.companies.delete_one({"_id": c_res.inserted_id})
        await db.outreachmessages.delete_many({"companyId": c_res.inserted_id})

# TEST H — Missing Evidence Blocks Generation
@pytest.mark.asyncio
async def test_h_missing_evidence_blocks_generation(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    comp_name = "Phase2 Test H Missing Evidence"
    await db.companies.delete_many({"companyName": comp_name})

    comp = {
        "companyName": comp_name,
        "website": "https://phase2-test-h.com",
        "normalizedWebsite": "phase2-test-h.com",
        "evidence": "",  # Missing!
        "recommendedService": "AI Strategy Consulting",
        "createdAt": now,
        "updatedAt": now
    }
    c_res = await db.companies.insert_one(comp)
    comp_id = str(c_res.inserted_id)

    try:
        res = await client.post(f"/api/companies/{comp_id}/outreach/generate", json={})
        assert res.status_code == 400
        data = res.json()
        assert "Evidence" in data["message"]
        # Ensure no emails were created
        count = await db.outreachmessages.count_documents({"companyId": c_res.inserted_id})
        assert count == 0
    finally:
        await db.companies.delete_one({"_id": c_res.inserted_id})

# TEST I — Missing Recommended Service Blocks Generation
@pytest.mark.asyncio
async def test_i_missing_recommended_service_blocks_generation(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    comp_name = "Phase2 Test I Missing Service"
    await db.companies.delete_many({"companyName": comp_name})

    comp = {
        "companyName": comp_name,
        "website": "https://phase2-test-i.com",
        "normalizedWebsite": "phase2-test-i.com",
        "evidence": "Developing proprietary medical image analysis pipelines.",
        "recommendedService": "",  # Missing!
        "createdAt": now,
        "updatedAt": now
    }
    c_res = await db.companies.insert_one(comp)
    comp_id = str(c_res.inserted_id)

    try:
        res = await client.post(f"/api/companies/{comp_id}/outreach/generate", json={})
        assert res.status_code == 400
        data = res.json()
        assert "Recommended Service" in data["message"]
        # Ensure no emails were created
        count = await db.outreachmessages.count_documents({"companyId": c_res.inserted_id})
        assert count == 0
    finally:
        await db.companies.delete_one({"_id": c_res.inserted_id})
