import pytest
import asyncio
from app.config.database import get_db, connect_db, close_db
from app.services.decision_maker_engine import (
    looks_like_organization_name,
    is_strict_person_name,
    is_valid_decision_maker,
    infer_pattern_from_known_people,
    attach_emails_to_candidates,
    extract_official_candidates,
    discover_exact_email_for_person,
)
from app.services.contact_service import extract_contacts_from_website

# 1. Zero Candidates on Empty Content
@pytest.mark.asyncio
async def test_zero_candidates_on_empty_content():
    candidates = extract_official_candidates("", "https://empty-test.com", "Empty Test Corp")
    assert len(candidates) == 0

    candidates_garbage = extract_official_candidates("<html><body>Welcome to our website! Copyright 2026</body></html>", "https://empty-test.com", "Empty Test Corp")
    assert len(candidates_garbage) == 0

# 2. Evidence Must Contain Person Name
def test_evidence_must_contain_person_name():
    # Candidate name does NOT appear in evidence text
    candidate_bad = {
        "name": "Sarah Connor",
        "role": "Chief Executive Officer",
        "source_url": "https://cyberdyne.test/leadership",
        "evidence": "The management team drives our global technology architecture and solutions."
    }
    assert is_valid_decision_maker(candidate_bad, "Cyberdyne Systems") is False

    # Candidate name DOES appear in evidence text
    candidate_good = {
        "name": "Sarah Connor",
        "role": "Chief Executive Officer",
        "source_url": "https://cyberdyne.test/leadership",
        "evidence": "Sarah Connor serves as the Chief Executive Officer of Cyberdyne Systems."
    }
    assert is_valid_decision_maker(candidate_good, "Cyberdyne Systems") is True

# 3. Source URL Must Be Real Valid URL
def test_source_url_must_be_real_url():
    candidate_relative = {
        "name": "Bruce Miller",
        "role": "Managing Director",
        "source_url": "/about/leadership",
        "evidence": "Bruce Miller is Managing Director of Gotham Corp."
    }
    assert is_valid_decision_maker(candidate_relative, "Gotham Corp") is False

    candidate_empty = {
        "name": "Bruce Miller",
        "role": "Managing Director",
        "source_url": "",
        "evidence": "Bruce Miller is Managing Director of Gotham Corp."
    }
    assert is_valid_decision_maker(candidate_empty, "Gotham Corp") is False

    candidate_valid = {
        "name": "Bruce Miller",
        "role": "Managing Director",
        "source_url": "https://gotham.test/leadership",
        "evidence": "Bruce Miller is Managing Director of Gotham Corp."
    }
    assert is_valid_decision_maker(candidate_valid, "Gotham Corp") is True

# 4. Target 6 Is Target, Not Guarantee (No Padding)
@pytest.mark.asyncio
async def test_target_6_is_target_not_guarantee():
    await connect_db()
    db = get_db()
    # Clean up stale test data
    await db.companies.delete_many({"normalizedWebsite": "twoleaders.test"})
    comp_res = await db.companies.insert_one({
        "companyName": "Two Leaders Ltd",
        "website": "https://twoleaders.test",
        "normalizedWebsite": "twoleaders.test",
        "industry": "Consulting",
        "status": "pending"
    })
    cid = str(comp_res.inserted_id)

    # Crawled page with exactly 2 real executives and no other people
    await db.crawledpages.insert_one({
        "companyId": comp_res.inserted_id,
        "url": "https://twoleaders.test/about",
        "pageType": "leadership",
        "crawlStatus": "completed",
        "content": "Two Leaders Ltd is led by Arthur Dent, Chief Executive Officer and Ford Prefect, Chief Technology Officer.",
        "html": "<div><p>Arthur Dent, Chief Executive Officer</p><p>Ford Prefect, Chief Technology Officer</p></div>",
        "wordCount": 50
    })

    contacts = await extract_contacts_from_website(cid)

    # Strictly verify: exactly 2 decision makers returned, NEVER padded to 6 with fake blueprints
    assert len(contacts) == 2
    names = {c["name"] for c in contacts}
    assert names == {"Arthur Dent", "Ford Prefect"}

    # Cleanup
    await db.companies.delete_one({"_id": comp_res.inserted_id})
    await db.crawledpages.delete_many({"companyId": comp_res.inserted_id})
    await db.contacts.delete_many({"companyId": comp_res.inserted_id})

# 5. Exact Email Discovered
def test_exact_email_discovered():
    person = {
        "name": "Alice Johnson",
        "role": "Chief Executive Officer",
        "source_url": "https://company.test/leadership",
        "evidence": "Contact Alice Johnson directly at alice.johnson@company.test for executive inquiries."
    }
    exact = discover_exact_email_for_person(person, "Company Test", "https://company.test", allowed_domains=["company.test"])
    assert exact.get("status") == "EXACT_FOUND"
    assert exact.get("email") == "alice.johnson@company.test"

# 6. Pattern Generation Requires At Least Two Distinct People
def test_pattern_generation_requires_two_distinct_people():
    # Only 1 person: Must return None, None (strict anti-hallucination)
    single_person = [("John Doe", "john.doe@acme.test", "acme.test")]
    pattern, domain = infer_pattern_from_known_people(single_person)
    assert pattern is None
    assert domain is None

    # 2 distinct people with matching pattern: Successfully inferred
    two_people = [
        ("John Doe", "john.doe@acme.test", "acme.test"),
        ("Jane Smith", "jane.smith@acme.test", "acme.test")
    ]
    pattern, domain = infer_pattern_from_known_people(two_people)
    assert pattern == "first.last"
    assert domain == "acme.test"

# 7. No Pattern Yields NOT_FOUND
def test_no_pattern_yields_not_found():
    candidates = [
        {
            "name": "John Doe",
            "role": "CEO",
            "source_url": "https://company.test/about",
            "evidence": "John Doe is CEO of Company Test."
        }
    ]
    # No known pairs provided
    enriched = attach_emails_to_candidates(candidates, "Company Test", "https://company.test")
    assert len(enriched) == 1
    c = enriched[0]
    assert c.get("email") is None
    assert c.get("email_status") == "NOT_FOUND"
    assert c.get("email_verification") == "NONE"

# 8. Domain MX Does Not Imply Mailbox Verified
@pytest.mark.asyncio
async def test_domain_mx_does_not_imply_mailbox_verified():
    await connect_db()
    db = get_db()
    assert db is not None

    # Clean up stale test data
    await db.companies.delete_many({"normalizedWebsite": "google.com"})

    comp_res = await db.companies.insert_one({
        "companyName": "MX Test Corp",
        "website": "https://google.com",  # Has active MX records
        "normalizedWebsite": "google.com",
        "industry": "Tech",
        "status": "pending"
    })
    cid = str(comp_res.inserted_id)

    await db.crawledpages.insert_one({
        "companyId": comp_res.inserted_id,
        "url": "https://google.com/team",
        "pageType": "leadership",
        "crawlStatus": "completed",
        "content": "Sundar Pichai is Chief Executive Officer of MX Test Corp.",
        "html": "<div><h3>Sundar Pichai</h3><p>Chief Executive Officer</p></div>",
        "wordCount": 50
    })

    contacts = await extract_contacts_from_website(cid)
    assert len(contacts) >= 1
    for c in contacts:
        # Mailbox verification must remain UNVERIFIED regardless of domain MX active status
        assert c.get("mailboxVerification") == "UNVERIFIED"

    # Cleanup
    await db.companies.delete_one({"_id": comp_res.inserted_id})
    await db.crawledpages.delete_many({"companyId": comp_res.inserted_id})
    await db.contacts.delete_many({"companyId": comp_res.inserted_id})

# 9. No Synthetic Names Generated
def test_no_synthetic_names_generated():
    synthetic_samples = [
        {"name": "Welspun Executive Officer", "role": "CEO", "source_url": "https://welspun.test", "evidence": "Welspun Executive Officer is verified as CEO"},
        {"name": "Tksr Technology Officer", "role": "CTO", "source_url": "https://tksr.test", "evidence": "Tksr Technology Officer is verified as CTO"},
        {"name": "Acme Leadership", "role": "Executive Leadership", "source_url": "https://acme.test", "evidence": "Corporate leadership channel for Acme"},
        {"name": "Global Managing Director", "role": "Managing Director", "source_url": "https://global.test", "evidence": "Global Managing Director overseeing operations"},
    ]
    for sample in synthetic_samples:
        assert is_valid_decision_maker(sample, sample["name"].split()[0]) is False

# 10. Organization Names Never People
def test_organization_names_never_people():
    org_names = [
        "Audit Committee",
        "Nomination Committee",
        "Board of Directors",
        "Executive Committee",
        "CSR Committee",
        "Management Team",
        "Leadership Team",
        "Corporate Governance",
        "Investor Relations",
        "Welspun Enterprises Ltd",
    ]
    for org in org_names:
        assert looks_like_organization_name(org) is True or is_strict_person_name(org) is False
