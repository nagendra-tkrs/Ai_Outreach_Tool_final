"""
Phase 17 hardening regression tests (D1-D8, E2-E10).

These tests lock the behavior introduced during the production-hardening pass:

  D1  categorize_role specialized-role precedence
  D2  email verification semantics (search sighting != published)
  D4  GET /contacts is read-only; explicit discover endpoint exists
  D5  role_supported_by_evidence meaningful role support + final validation
  D6  single canonical person-email matcher + delegation back-compat
  D7  tri-state MX (YES/NO/UNKNOWN) with neutral scoring for UNKNOWN
  D8  structured purge of synthetic contacts
  E2  scheduler evidence gate (no generic fallback, BLOCKED status)
  E3  duplicate-send 409 + configurable daily/per-domain limits
  E4  suppression + unsubscribe endpoint
  E5  get_outreach_records status/sort filters
  E6  datetime.utcnow() fully removed from backend
  E7  click-tracking URL scheme hardening + link rewriting
  E8  recipient email syntax validation
  E9  test/sandbox sends excluded from production stats
  E10 sender-identity mismatch warning in settings
"""
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
import httpx
from bson import ObjectId
from fastapi import HTTPException
from unittest.mock import patch, AsyncMock

from app.main import app
from app.config.database import connect_db, close_db, get_db, get_database

# ---------------- shared fixtures (same pattern as test_api_integration) -------

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


# =====================================================================
# D1: categorize_role specialized-role precedence
# =====================================================================
def test_d1_specialized_roles_beat_generic_director_vp():
    from app.services.contact_service import categorize_role

    cases = {
        "Head of AI": "head_of_ai",
        "Director of AI": "head_of_ai",
        "VP of AI": "head_of_ai",
        "Vice President of Data": "head_of_data",
        "Director of Technology": "head_of_technology",
        "VP of Engineering": "head_of_technology",
        "Director of Sales": "head_of_sales",
        "Chief Revenue Officer": "head_of_sales",
        "Director of Product": "head_of_product",
        "Chief Product Officer": "head_of_product",
        "Head of Operations": "head_of_operations",
        "Chief Marketing Officer": "head_of_marketing",
        "Head of HR": "head_of_hr",
        "Chief People Officer": "head_of_hr",
        "General Counsel": "head_of_legal",
        "Director of Finance": "head_of_finance",
    }
    for title, expected in cases.items():
        res = categorize_role(title)
        assert res["roleCategory"] == expected, f"{title} -> {res['roleCategory']} (expected {expected})"


def test_d1_generic_levels_still_classified():
    from app.services.contact_service import categorize_role

    assert categorize_role("Director of Marketing")["roleCategory"] == "head_of_marketing"
    assert categorize_role("Director")["roleCategory"] == "director"
    assert categorize_role("Vice President")["roleCategory"] == "vp"
    assert categorize_role("Manager")["roleCategory"] == "manager"
    assert categorize_role("Senior Consultant")["roleCategory"] == "lead"


# =====================================================================
# D2: email verification semantics (sighting != published)
# =====================================================================
async def test_d2_pattern_sighting_is_not_published():
    from app.services import contact_service

    pattern_info = {
        "pattern": "first.last",
        "emailDomain": "acme.com",
        "confidence": 80,
        "patternConfidence": "SUPPORTED",
        "examples": ["john.doe@acme.com"],
        "sources": ["https://acme.com/team"],
        "verifiedAssociations": [{"email": "jane.doe@acme.com", "person": "Jane Doe"}],
    }
    # Third-party search index sighting -> must stay PATTERN_GENERATED
    with patch.object(contact_service, "search_online_for_generated_email",
                      new=AsyncMock(return_value={
                          "verified": True,
                          "email": "john.q.public@acme.com",
                          "onOfficialSource": False,
                          "source": "Public Web Search Index",
                      })):
        res = await contact_service.resolve_decision_maker_email(
            name="John Q Public", company_name="Acme Corp", domain="acme.com", pattern_info=pattern_info
        )
    assert res["emailStatus"] == "PATTERN_GENERATED"
    assert res["isExactPublished"] is False
    assert res["emailVerificationState"] == "PATTERN_GENERATED"
    assert res["verificationMethod"] == "PATTERN_INFERENCE"
    assert res["mailboxVerification"] == "UNVERIFIED"
    assert res.get("searchIndexSighting") is True


async def test_d2_official_domain_sighting_is_published():
    from app.services import contact_service

    pattern_info = {
        "pattern": "first.last",
        "emailDomain": "acme.com",
        "confidence": 80,
        "patternConfidence": "SUPPORTED",
        "examples": ["john.doe@acme.com"],
        "sources": [],
        "verifiedAssociations": [],
    }
    # Sighting hosted on the company's OWN official domain -> legitimately published
    with patch.object(contact_service, "search_online_for_generated_email",
                      new=AsyncMock(return_value={
                          "verified": True,
                          "email": "john.q.public@acme.com",
                          "onOfficialSource": True,
                          "source": "Public Web Search Index",
                          "sourceUrl": "https://acme.com/team",
                      })):
        res = await contact_service.resolve_decision_maker_email(
            name="John Q Public", company_name="Acme Corp", domain="acme.com", pattern_info=pattern_info
        )
    assert res["emailStatus"] == "DIRECTLY_VERIFIED"
    assert res["isExactPublished"] is True
    assert res["emailVerificationState"] == "EXACT_PUBLISHED"
    assert res["verificationMethod"] == "DIRECT_SOURCE_MATCH"


async def test_d2_generated_email_search_marks_on_official_source():
    from app.services.web_search_service import search_online_for_generated_email
    from unittest.mock import patch, AsyncMock

    async def fake_official(*args, **kwargs):
        return {"status": "OK", "results": [
            {"title": "Acme Corp team", "snippet": "john.q.public@acme.com is our AI lead",
             "url": "https://acme.com/team"}
        ]}

    async def fake_external(*args, **kwargs):
        return {"status": "OK", "results": [
            {"title": "Acme Corp on LinkedIn", "snippet": "john.q.public@acme.com listed",
             "url": "https://www.linkedin.com/company/acme"}
        ]}

    with patch("app.services.web_search_service.execute_search", new=AsyncMock(side_effect=fake_official)):
        res = await search_online_for_generated_email(
            "john.q.public@acme.com", "John Q Public", "Acme Corp", "https://acme.com"
        )
    assert res["verified"] is True
    assert res["onOfficialSource"] is True
    assert res["isSighting"] is True

    with patch("app.services.web_search_service.execute_search", new=AsyncMock(side_effect=fake_external)):
        res2 = await search_online_for_generated_email(
            "john.q.public@acme.com", "John Q Public", "Acme Corp", "https://acme.com"
        )
    assert res2["verified"] is True
    assert res2["onOfficialSource"] is False


# =====================================================================
# D4: GET /contacts is strictly read-only
# =====================================================================
async def test_d4_get_contacts_is_read_only(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    comp = await db.companies.insert_one({
        "companyName": "D4 ReadOnly Corp",
        "website": "https://d4readonly.example",
        "normalizedWebsite": "d4readonly.example",
        "createdAt": now,
        "updatedAt": now,
    })
    cid = str(comp.inserted_id)

    # No contacts exist yet; a read must NOT trigger extraction side effects
    res = await client.get(f"/api/companies/{cid}/contacts")
    assert res.status_code == 200
    assert res.json()["data"] == []

    left = await db.contacts.count_documents({"companyId": comp.inserted_id})
    assert left == 0, "GET /contacts must not create contacts (no auto-extraction)"

    # Explicit discovery endpoint still exists (frontend contract)
    res2 = await client.post(f"/api/companies/{cid}/contacts/discover")
    assert res2.status_code in (200, 201, 400, 500)  # endpoint exists (may lack evidence/data)


# =====================================================================
# D5: role_supported_by_evidence meaningful role support
# =====================================================================
def test_d5_role_support_requires_name_role_proximity():
    from app.services.decision_maker_engine import role_supported_by_evidence

    # Long unrelated text that never mentions the person or role -> reject
    unrelated = (
        "Our company has grown rapidly over the past decade with offices in "
        "multiple countries serving enterprise customers across the globe. "
        "We focus on quality, innovation, and long-term partnerships."
    )
    assert role_supported_by_evidence("Chief Executive Officer", unrelated, "Sarah Connor", "Cyberdyne") is False

    # Person mentioned but not the claimed role -> reject
    assert role_supported_by_evidence(
        "Chief Executive Officer",
        "Sarah Connor leads the engineering division at Cyberdyne Systems.",
        "Sarah Connor", "Cyberdyne"
    ) is False

    # Name + role in the same sentence -> accept
    assert role_supported_by_evidence(
        "Chief Executive Officer",
        "Sarah Connor serves as the Chief Executive Officer of Cyberdyne Systems.",
        "Sarah Connor", "Cyberdyne"
    ) is True

    # CEO/CFO shorthand equivalence preserved
    assert role_supported_by_evidence(
        "CEO",
        "Sarah Connor is the CEO of Cyberdyne Systems.",
        "Sarah Connor", "Cyberdyne"
    ) is True


def test_d5_final_validate_wires_role_support():
    from app.services.decision_maker_engine import final_validate_candidate

    unrelated_cand = {
        "name": "Sarah Connor",
        "role": "Chief Executive Officer",
        "source_url": "https://cyberdyne.test/leadership",
        "evidence": "The management team drives our global technology architecture and solutions.",
    }
    assert final_validate_candidate(unrelated_cand, "Cyberdyne Systems", "https://cyberdyne.test") is False

    supported_cand = {
        "name": "Sarah Connor",
        "role": "Chief Executive Officer",
        "source_url": "https://cyberdyne.test/leadership",
        "evidence": "Sarah Connor serves as the Chief Executive Officer of Cyberdyne Systems.",
    }
    assert final_validate_candidate(supported_cand, "Cyberdyne Systems", "https://cyberdyne.test") is True


# =====================================================================
# D6: single canonical matcher + delegation back-compat
# =====================================================================
def test_d6_canonical_matcher_contract():
    from app.services.email_validation_service import canonical_person_email_match

    res = canonical_person_email_match("Paul K. Oswal", "paul.oswal@acme.com", "acme.com")
    assert res["matched"] is True
    assert res["personEmailMatch"] == "true"
    assert res["domainMatched"] is True

    res_bad = canonical_person_email_match("Paul K. Oswal", "info@acme.com", "acme.com")
    assert res_bad["matched"] is False  # generic channel rejected


def test_d6_email_matches_person_back_compat():
    from app.services.decision_maker_engine import email_matches_person

    # Historical test anchors must keep behaving identically
    assert email_matches_person("paul.oswal@tksrproductservices.com", "Paul K. Oswal") is True
    assert email_matches_person("paul.k.oswal@tksrproductservices.com", "Paul K. Oswal") is True
    assert email_matches_person("rajesh.rathi@tksrproductservices.com", "RATHI RAJESH") is True


def test_d6_evaluate_person_email_match_delegates():
    from app.services.contact_service import evaluate_person_email_match

    res = evaluate_person_email_match("Paul K. Oswal", "paul.oswal@acme.com", "acme.com")
    assert res["match"] is True
    assert res["personEmailMatch"] == "true"

    res_bad = evaluate_person_email_match("Paul K. Oswal", "support@acme.com", "acme.com")
    assert res_bad["match"] is False


# =====================================================================
# D7: tri-state MX with neutral scoring
# =====================================================================
async def test_d7_mx_unknown_semantics():
    from app.services.contact_service import check_domain_mx

    # Empty/no domain -> UNKNOWN, never a hard False
    res = await check_domain_mx("")
    assert res["mxState"] == "UNKNOWN"
    assert res["hasMxRecords"] is None

    # DNS failure -> UNKNOWN with hasMxRecords None
    original_resolver = None
    import dns.resolver as dnsr
    class BoomResolver:
        lifetime = 2.0
        def resolve(self, *a, **k):
            raise dnsr.NXDOMAIN
    with patch.object(dnsr, "Resolver", return_value=BoomResolver()):
        res2 = await check_domain_mx("nonexistent.invalid")
    assert res2["mxState"] == "UNKNOWN"
    assert res2["hasMxRecords"] is None
    assert res2.get("dnsError") is True


async def test_d7_mx_yes_no_states():
    from app.services.contact_service import check_domain_mx
    import dns.resolver as dnsr

    class HasMx:
        lifetime = 2.0
        def resolve(self, *a, **k):
            class Ans:
                exchange = "aspmx.l.google.com"
            return [Ans()]
    with patch.object(dnsr, "Resolver", return_value=HasMx()):
        res = await check_domain_mx("gmail.com")
    assert res["mxState"] == "YES"
    assert res["hasMxRecords"] is True

    class NoMx:
        lifetime = 2.0
        def resolve(self, *a, **k):
            return []
    with patch.object(dnsr, "Resolver", return_value=NoMx()):
        res2 = await check_domain_mx("plaindomain.com")
    assert res2["mxState"] == "NO"
    assert res2["hasMxRecords"] is False


def test_d7_unknown_mx_neutral_scoring():
    from app.services.contact_service import calculate_explainable_confidence

    base = {
        "isGeneric": False,
        "isExactPublished": False,
        "isPatternDerived": True,
        "hasMxRecords": True,
        "mxState": "YES",
        "personEmailMatch": "true",
        "sourceType": "official_team_page",
        "designationVerified": "true",
    }
    known_mx = calculate_explainable_confidence(base)
    unknown_mx = calculate_explainable_confidence({**base, "hasMxRecords": None, "mxState": "UNKNOWN"})

    assert known_mx["confidenceScore"] > unknown_mx["confidenceScore"]
    assert any("neutral" in r for r in unknown_mx["confidenceReasoning"])


# =====================================================================
# D8: structured purge (synthetic contacts removed, discovered kept)
# =====================================================================
async def test_d8_structured_purge_keeps_discovered_removes_synthetic():
    from app.services import contact_service

    db = get_db()
    now = datetime.now(timezone.utc)

    await db.companies.delete_many({"normalizedWebsite": "d8purgetest.com"})
    comp = await db.companies.insert_one({
        "companyName": "D8 Purge Test Corp",
        "website": "https://d8purgetest.com",
        "normalizedWebsite": "d8purgetest.com",
        "industry": "Tech",
        "status": "pending",
        "evidence": "D8 Purge Test Corp provides AI automation services.",
        "recommendedService": "AI consulting",
        "createdAt": now,
        "updatedAt": now,
    })
    cid = str(comp.inserted_id)

    await db.crawledpages.insert_one({
        "companyId": comp.inserted_id,
        "url": "https://d8purgetest.com/team",
        "pageType": "leadership",
        "crawlStatus": "completed",
        "content": "Sundar Pichai is Chief Executive Officer of D8 Purge Test Corp.",
        "html": "<div><h3>Sundar Pichai</h3><p>Chief Executive Officer</p></div>",
        "wordCount": 50,
    })

    # Seed a synthetic contact that must be purged + a legit one kept
    await db.contacts.insert_one({
        "companyId": comp.inserted_id,
        "name": "D8 Synthetic Executive Officer",
        "title": "CEO",
        "evidence": {"snippet": "D8 Synthetic Executive Officer is verified as CEO", "personEvidence": ""},
        "createdAt": now, "updatedAt": now,
    })
    await db.contacts.insert_one({
        "companyId": comp.inserted_id,
        "name": "Jane Smith",
        "title": "CFO",
        "evidence": {"snippet": "Jane Smith listed in company records", "personEvidence": "Jane Smith"},
        "createdAt": now, "updatedAt": now,
    })

    with patch.object(contact_service, "check_domain_mx",
                      new=AsyncMock(return_value={"mxStatus": "MX_ACTIVE", "mxProvider": "test", "hasMxRecords": True, "mxState": "YES"})):
        contacts = await contact_service.extract_contacts_from_website(cid)

    names = [c.get("name") for c in contacts]
    assert isinstance(contacts, list)
    assert len(contacts) >= 1  # discovered Sundar Pichai etc.

    remains = await db.contacts.find({"companyId": comp.inserted_id}).to_list(length=50)
    remain_names = [c.get("name") for c in remains]
    assert "D8 Synthetic Executive Officer" not in remain_names, "synthetic contact must be purged"
    assert "Jane Smith" in remain_names, "legit non-matching contact must be kept"
    assert any("Sundar" in n for n in remain_names), "discovered contact must be kept"


# =====================================================================
# E2: scheduler evidence gate (BLOCKED instead of generic fallback)
# =====================================================================
async def test_e2_scheduler_blocks_without_evidence():
    from app.services.scheduler_service import process_automated_follow_ups

    db = get_db()
    now = datetime.now(timezone.utc)

    # Company WITHOUT evidence / recommendedService -> gate must fail
    comp = await db.companies.insert_one({
        "companyName": "E2 No Evidence Corp",
        "website": "https://e2noevidence.example",
        "normalizedWebsite": "e2noevidence.example",
        "createdAt": now, "updatedAt": now,
    })
    cid = comp.inserted_id

    record = await db.outreachrecords.insert_one({
        "companyId": cid,
        "contactId": None,
        "companyName": "E2 No Evidence Corp",
        "contactName": "Sarah Connor",
        "recipientEmail": "sarah.connor@e2noevidence.example",
        "initialEmail": {"status": "SENT"},
        "followUp1": {"status": "PENDING", "scheduledAt": now},
        "followUp2": {"status": "PENDING", "scheduledAt": now},
        "replyStatus": "NO_REPLY",
        "createdAt": now, "updatedAt": now,
    })

    try:
        await process_automated_follow_ups()
        updated = await db.outreachrecords.find_one({"_id": record.inserted_id})
        assert updated["followUp1"]["status"] == "BLOCKED"
        assert updated["followUp1"]["blockedReason"] == "Missing company Evidence or Recommended Service"

        # No generic fallback message must have been fabricated/inserted
        fallback_count = await db.outreachmessages.count_documents({
            "companyId": cid,
            "step": 2,
            "subject": {"$regex": "Practical Value & Workflow Proof"},
        })
        assert fallback_count == 0
    finally:
        await db.outreachrecords.delete_many({"_id": record.inserted_id})
        await db.companies.delete_many({"_id": cid})


# =====================================================================
# E3: duplicate-send 409 + configurable limits
# =====================================================================
async def test_e3_duplicate_send_blocked():
    from app.services.email_service import send_outreach_email

    db = get_db()
    now = datetime.now(timezone.utc)
    msg = await db.outreachmessages.insert_one({
        "companyId": ObjectId(),
        "step": 1,
        "subject": "Duplicate test",
        "status": "sent",
        "recipientEmail": "dup@example.com",
        "bodyHtml": "<p>hi</p>",
        "bodyText": "hi",
        "createdAt": now, "updatedAt": now,
    })
    try:
        with pytest.raises(HTTPException) as exc:
            await send_outreach_email(str(msg.inserted_id))
        assert exc.value.status_code == 409
    finally:
        await db.outreachmessages.delete_many({"_id": msg.inserted_id})


async def test_e3_limit_guard_short_circuits_test_sends():
    from app.services.send_guard import assert_send_limits, get_send_limits

    prev_daily = os.environ.get("DAILY_SEND_LIMIT")
    try:
        os.environ["DAILY_SEND_LIMIT"] = "0"
        os.environ["PER_DOMAIN_DAILY_LIMIT"] = "0"
        # Real send hitting the cap -> blocked
        with pytest.raises(HTTPException) as exc:
            await assert_send_limits("somebody@example.com", is_test=False)
        assert exc.value.status_code == 429
        # Test/sandbox send -> never blocked
        await assert_send_limits("somebody@example.com", is_test=True)
    finally:
        if prev_daily is None:
            os.environ.pop("DAILY_SEND_LIMIT", None)
        else:
            os.environ["DAILY_SEND_LIMIT"] = prev_daily
        os.environ.pop("PER_DOMAIN_DAILY_LIMIT", None)


def test_e3_send_window_helpers():
    from app.services.send_guard import is_within_sending_window, get_app_tz_offset_minutes

    prev_start = os.environ.get("SEND_WINDOW_START")
    prev_end = os.environ.get("SEND_WINDOW_END")
    prev_offset = os.environ.get("APP_TZ_OFFSET_MINUTES")
    try:
        os.environ["SEND_WINDOW_START"] = "09:00"
        os.environ["SEND_WINDOW_END"] = "18:00"
        os.environ["APP_TZ_OFFSET_MINUTES"] = "0"
        noon = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        night = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)
        inside = is_within_sending_window(noon)
        outside = is_within_sending_window(night)
        assert inside is True
        assert outside is False
        # window applies to scheduler auto-dispatch, verified indirectly: the
        # window check is only consulted by scheduler whole_* paths
        assert get_app_tz_offset_minutes() == 0
    finally:
        for key, prev in (("SEND_WINDOW_START", prev_start), ("SEND_WINDOW_END", prev_end), ("APP_TZ_OFFSET_MINUTES", prev_offset)):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev


# =====================================================================
# E4: suppression + unsubscribe endpoint
# =====================================================================
async def test_e4_suppression_blocks_send():
    from app.services.send_guard import add_suppression, remove_suppression, assert_not_suppressed

    await add_suppression("blocked@example.com", reason="test")
    try:
        with pytest.raises(HTTPException) as exc:
            await assert_not_suppressed("blocked@example.com")
        assert exc.value.status_code == 403

        with pytest.raises(HTTPException) as exc2:
            await assert_not_suppressed("ok@example.com", cc_recipients=["blocked@example.com"])
        assert exc2.value.status_code == 403

        # Not suppressed -> no exception
        await assert_not_suppressed("ok@example.com")
    finally:
        await remove_suppression("blocked@example.com")


async def test_e4_unsubscribe_endpoint_registers_suppression(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    msg = await db.outreachmessages.insert_one({
        "companyId": ObjectId(),
        "step": 1,
        "subject": "Unsub test",
        "status": "sent",
        "recipientEmail": "unsub@example.com",
        "bodyHtml": "<p>hi</p>",
        "bodyText": "hi",
        "createdAt": now, "updatedAt": now,
    })
    mid = str(msg.inserted_id)
    try:
        res = await client.get(f"/api/track/unsubscribe/{mid}")
        assert res.status_code == 307
        supp = await db.suppressions.find_one({"email": "unsub@example.com"})
        assert supp is not None
    finally:
        await db.outreachmessages.delete_many({"_id": msg.inserted_id})
        from app.services.send_guard import remove_suppression
        await remove_suppression("unsub@example.com")


# =====================================================================
# E5: get_outreach_records status/sort filters
# =====================================================================
async def test_e5_records_status_and_sort_filters():
    from app.services.outreach_tracking_service import get_outreach_records

    db = get_db()
    now = datetime.now(timezone.utc)
    cid = ObjectId()
    await db.outreachrecords.delete_many({"companyId": cid})
    await db.outreachrecords.insert_many([
        {
            "companyId": cid,
            "companyName": "E5 Filter Co",
            "contactName": "Alice",
            "recipientEmail": "alice@e5filter.example",
            "initialEmail": {"status": "SENT"},
            "campaignStatus": "PENDING",
            "replyStatus": "NO_REPLY",
            "emailSubject": "E5 subject A",
            "createdAt": now, "updatedAt": now,
        },
        {
            "companyId": cid,
            "companyName": "E5 Filter Co",
            "contactName": "Bob",
            "recipientEmail": "bob@e5filter.example",
            "initialEmail": {"status": "SENT"},
            "campaignStatus": "SENT",
            "replyStatus": "NO_REPLY",
            "emailSubject": "E5 subject B",
            "createdAt": now, "updatedAt": now,
        },
    ])
    try:
        res = await get_outreach_records({"status": "SENT", "companyId": str(cid)})
        assert res["pagination"]["total"] == 1
        assert res["records"][0]["campaignStatus"] == "SENT"

        res_all = await get_outreach_records({"companyId": str(cid), "sortBy": "recipientEmail", "sortDir": "asc"})
        assert res_all["pagination"]["total"] == 2
        emails = [r["recipientEmail"] for r in res_all["records"]]
        assert emails == sorted(emails)

        # Unknown sort field safely falls back to updatedAt (no crash / injection)
        res_fb = await get_outreach_records({"companyId": str(cid), "sortBy": "__bad__field", "sortDir": "desc"})
        assert res_fb["pagination"]["total"] == 2
    finally:
        await db.outreachrecords.delete_many({"companyId": cid})


# =====================================================================
# E6: no datetime.utcnow() anywhere in backend application code
# =====================================================================
def test_e6_no_datetime_utcnow_in_backend():
    backend_app = Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for py in backend_app.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        if "datetime.utcnow(" in text:
            offenders.append(str(py))
    assert offenders == [], f"datetime.utcnow() still present in: {offenders}"


# =====================================================================
# E7: click-tracking URL hardening + link rewriting
# =====================================================================
async def test_e7_track_click_rejects_non_http_schemes(client):
    db = get_db()
    now = datetime.now(timezone.utc)
    msg = await db.outreachmessages.insert_one({
        "companyId": ObjectId(),
        "step": 1,
        "subject": "Click test",
        "status": "sent",
        "recipientEmail": "click@example.com",
        "bodyHtml": "<p>hi</p>",
        "bodyText": "hi",
        "createdAt": now, "updatedAt": now,
    })
    mid = str(msg.inserted_id)
    try:
        # javascript: URL must NOT be the redirect target (open-redirect blocked)
        res = await client.get(f"/api/track/click/{mid}", params={"url": "javascript:alert(1)"}, follow_redirects=False)
        assert res.status_code == 307
        assert res.headers.get("location", "/") == "/"

        # Valid http(s) URL allowed through
        res2 = await client.get(f"/api/track/click/{mid}", params={"url": "https://example.com/page?a=1"}, follow_redirects=False)
        assert res2.status_code == 307
        assert "example.com" in res2.headers.get("location", "")

        # Click counted
        updated = await db.outreachmessages.find_one({"_id": msg.inserted_id})
        assert updated.get("clickCount", 0) >= 2
    finally:
        await db.outreachmessages.delete_many({"_id": msg.inserted_id})


def test_e7_link_rewriting_only_http_links():
    from app.services.email_service import rewrite_tracking_links

    body = (
        '<a href="https://example.com/offer">Sign up</a> '
        '<a href="mailto:hello@example.com">Email</a> '
        '<a href="javascript:void(0)">JS</a> '
        '<a href="#local">Anchor</a>'
    )
    rewritten = rewrite_tracking_links(body, "abc123", "http://localhost:5000")
    assert "/api/track/click/abc123?url=" in rewritten
    assert "mailto:hello@example.com" in rewritten  # untouched
    assert "javascript:void(0)" in rewritten         # untouched
    assert '#local"' in rewritten                    # untouched


# =====================================================================
# E8: recipient email syntax validation
# =====================================================================
def test_e8_recipient_email_validation():
    from app.services.send_guard import validate_recipient_email

    assert validate_recipient_email("john.doe@example.com") is True
    assert validate_recipient_email("john+tag@sub.example.co.uk") is True
    assert validate_recipient_email("not-an-email") is False
    assert validate_recipient_email("john@noTLD") is False
    assert validate_recipient_email("") is False
    assert validate_recipient_email(None) is False
    assert validate_recipient_email("a b@example.com") is False


async def test_e8_invalid_recipient_blocked_in_send():
    from app.services.email_service import send_outreach_email

    db = get_db()
    now = datetime.now(timezone.utc)
    msg = await db.outreachmessages.insert_one({
        "companyId": ObjectId(),
        "step": 1,
        "subject": "Bad recipient",
        "status": "draft",
        "recipientEmail": "john.doe@invalid-domain",
        "bodyHtml": "<p>hi</p>",
        "bodyText": "hi",
        "createdAt": now, "updatedAt": now,
    })
    try:
        with pytest.raises(HTTPException) as exc:
            await send_outreach_email(str(msg.inserted_id))
        assert exc.value.status_code == 400
    finally:
        await db.outreachmessages.delete_many({"_id": msg.inserted_id})


# =====================================================================
# E9: test/sandbox sends excluded from production stats
# =====================================================================
async def test_e9_test_sends_excluded_from_stats():
    from app.services.outreach_tracking_service import get_outreach_stats

    db = get_db()
    before = await get_outreach_stats()

    now = datetime.now(timezone.utc)
    cid = ObjectId()
    await db.outreachrecords.delete_many({"companyId": cid})
    # Real record (no isTestSend flag) -> counted
    await db.outreachrecords.insert_one({
        "companyId": cid, "companyName": "E9 Real Co", "contactName": "R",
        "recipientEmail": "r@e9.example", "initialEmail": {"status": "SENT"},
        "followUp1": {"status": "PENDING"}, "replyStatus": "NO_REPLY",
        "createdAt": now, "updatedAt": now,
    })
    # Sandbox/test record -> excluded
    await db.outreachrecords.insert_one({
        "companyId": cid, "companyName": "E9 Sandbox Co", "contactName": "S",
        "recipientEmail": "s@e9.example", "initialEmail": {"status": "SENT"},
        "followUp1": {"status": "PENDING"}, "replyStatus": "NO_REPLY",
        "isTestSend": True,
        "createdAt": now, "updatedAt": now,
    })
    try:
        after = await get_outreach_stats()
        assert after["totalProspects"] == before["totalProspects"] + 1, "test/sandbox record must not be counted"
        assert after["initialSent"] == before["initialSent"] + 1
    finally:
        await db.outreachrecords.delete_many({"companyId": cid})


# =====================================================================
# E10: sender-identity mismatch warning
# =====================================================================
async def test_e10_sender_identity_mismatch_warning(client):
    # Preserve shared live settings — restore them afterward so this test is
    # non-destructive.
    before = (await client.get("/api/settings")).json()["data"]
    prev_from = (before.get("smtp") or {}).get("fromName", "")
    prev_sender = ((before.get("senderProfile") or {}).get("senderName") or "")

    try:
        res = await client.post("/api/settings", json={
            "smtp": {"fromName": "Different Sender Name"},
            "senderProfile": {"senderName": "Actual Agent Name"},
        })
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body.get("warnings"), list)
        assert any("mismatch" in w.lower() for w in body["warnings"])

        # No mismatch -> no warning
        res_ok = await client.post("/api/settings", json={
            "smtp": {"fromName": "Same Name"},
            "senderProfile": {"senderName": "Same Name"},
        })
        assert res_ok.status_code == 200
        assert res_ok.json().get("warnings") == []
    finally:
        # Restore prior values (matching names silently, no warning added).
        await client.post("/api/settings", json={
            "smtp": {"fromName": prev_from or "Test Outreach"},
            "senderProfile": {"senderName": prev_sender or prev_from or "Test Outreach"},
        })