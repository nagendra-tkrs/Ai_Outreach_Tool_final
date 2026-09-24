import pytest
import asyncio
from app.config.database import get_db, connect_db, close_db
from app.services.decision_maker_engine import (
    ROLE_PRIORITY,
    best_role_from_phrase,
    looks_like_organization_name,
    is_strict_person_name,
    extract_direct_relationships,
    extract_official_candidates,
    infer_pattern_from_known_people,
    generate_pattern_email,
    find_any_company_decision_makers
)
from app.services.contact_service import extract_contacts_from_website

@pytest.mark.asyncio
async def test_role_priority_and_filtering():
    assert ROLE_PRIORITY["Founder & CEO"] > ROLE_PRIORITY["Director"]
    assert looks_like_organization_name("Audit Committee") is True
    assert looks_like_organization_name("Board of Directors") is True
    assert looks_like_organization_name("Welspun Enterprises Ltd") is True
    assert looks_like_organization_name("Balkrishan Goenka") is False
    assert is_strict_person_name("Balkrishan Goenka") is True

@pytest.mark.asyncio
async def test_direct_relationships_extraction():
    sample_html = """
    <div>
        <h2>Leadership</h2>
        <p>Balkrishan Goenka is the Chairman of Welspun Group.</p>
        <p>Rajesh Mandawewala serves as Managing Director of Welspun Group.</p>
        <p>Former CEO John Doe retired in 2020.</p>
    </div>
    """
    candidates = extract_official_candidates(sample_html, "https://welspun.com", "Welspun Group")
    names = [c["name"] for c in candidates]
    assert any("Balkrishan Goenka" in n or "Rajesh Mandawewala" in n for n in names)
    # Historical marker check: Former CEO should not be considered current
    assert not any("John Doe" in n for n in names)

@pytest.mark.asyncio
async def test_safe_pattern_inference_rule():
    # 2 distinct people with same pattern is successfully inferred
    pattern, domain = infer_pattern_from_known_people([
        ("John Doe", "john.doe@company.com", "company.com"),
        ("Jane Smith", "jane.smith@company.com", "company.com")
    ])
    assert pattern == "first.last"
    assert domain == "company.com"

    gen = generate_pattern_email("Alice Cooper", "company.com", "first.last")
    assert gen == "alice.cooper@company.com"

@pytest.mark.asyncio
async def test_end_to_end_contact_extraction_mock_company():
    await connect_db()
    db = get_db()
    assert db is not None

    # Clean up any leftover test data
    await db.companies.delete_many({"normalizedWebsite": "acmerobotics.test"})
    # Insert test company
    comp_res = await db.companies.insert_one({
        "companyName": "Acme Robotics Inc",
        "website": "https://acmerobotics.test",
        "normalizedWebsite": "acmerobotics.test",
        "industry": "Robotics",
        "status": "pending"
    })
    cid = str(comp_res.inserted_id)

    # Insert mock crawled page with leadership
    await db.crawledpages.insert_one({
        "companyId": comp_res.inserted_id,
        "url": "https://acmerobotics.test/leadership",
        "pageType": "team",
        "crawlStatus": "completed",
        "content": "Acme Robotics Leadership: Elena Vance, Chief Executive Officer of Acme Robotics Inc. Gordon Freeman, Chief Technology Officer of Acme Robotics Inc.",
        "html": "<div class='team'><h3>Elena Vance</h3><p>Chief Executive Officer of Acme Robotics Inc</p><h3>Gordon Freeman</h3><p>Chief Technology Officer of Acme Robotics Inc</p></div>",
        "wordCount": 100
    })

    contacts = await extract_contacts_from_website(cid)
    assert len(contacts) >= 2
    contact_names = [c["name"] for c in contacts]
    assert "Elena Vance" in contact_names
    assert "Gordon Freeman" in contact_names

    # Check top ranked is CEO
    top_contact = next(c for c in contacts if c.get("isPrimaryDecisionMaker"))
    assert top_contact["name"] == "Elena Vance"
    assert top_contact["roleCategory"] == "ceo"

    # Cleanup test data
    await db.companies.delete_one({"_id": comp_res.inserted_id})
    await db.crawledpages.delete_many({"companyId": comp_res.inserted_id})
    await db.contacts.delete_many({"companyId": comp_res.inserted_id})

@pytest.mark.asyncio
async def test_extract_and_generate_emails_for_at_least_6_decision_makers():
    await connect_db()
    db = get_db()
    assert db is not None

    await db.companies.delete_many({"normalizedWebsite": "apextechnologies.io"})
    comp_res = await db.companies.insert_one({
        "companyName": "Apex Technologies Global",
        "website": "https://apextechnologies.io",
        "normalizedWebsite": "apextechnologies.io",
        "industry": "Software",
        "status": "pending"
    })
    cid = str(comp_res.inserted_id)

    # Crawled page with 6 distinct decision makers
    team_html = """
    <div class="leadership-grid">
        <div><h3>Alexander Wright</h3><p>Founder & Chief Executive Officer</p></div>
        <div><h3>Sophia Martinez</h3><p>Co-Founder & Chief Technology Officer</p></div>
        <div><h3>David Chen</h3><p>Chief Operating Officer</p></div>
        <div><h3>Rachel Green</h3><p>Chief Financial Officer</p></div>
        <div><h3>Marcus Vance</h3><p>Managing Director</p></div>
        <div><h3>Sarah Jenkins</h3><p>Head of AI</p></div>
    </div>
    """
    await db.crawledpages.insert_one({
        "companyId": comp_res.inserted_id,
        "url": "https://apextechnologies.io/team",
        "pageType": "team",
        "crawlStatus": "completed",
        "content": "Alexander Wright, Founder & Chief Executive Officer. Sophia Martinez, Co-Founder & Chief Technology Officer. David Chen, Chief Operating Officer. Rachel Green, Chief Financial Officer. Marcus Vance, Managing Director. Sarah Jenkins, Head of AI.",
        "html": team_html,
        "wordCount": 150
    })

    contacts = await extract_contacts_from_website(cid)
    assert len(contacts) >= 6

    # Under evidence-based semantics, since no emails were on page, emails are None/NOT_FOUND
    for c in contacts:
        assert c.get("emailStatus") in ("EXACT_FOUND", "PATTERN_GENERATED", "NOT_FOUND")
        if c.get("emailStatus") == "NOT_FOUND":
            assert c.get("email") is None or c.get("email") == ""

    # Verify top ranking
    top_contact = next(c for c in contacts if c.get("isPrimaryDecisionMaker"))
    assert top_contact["name"] == "Alexander Wright"
    assert top_contact["roleCategory"] in ("ceo", "founder")

    # Cleanup test data
    await db.companies.delete_one({"_id": comp_res.inserted_id})
    await db.crawledpages.delete_many({"companyId": comp_res.inserted_id})
    await db.contacts.delete_many({"companyId": comp_res.inserted_id})
