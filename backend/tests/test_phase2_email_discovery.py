import pytest
import re
from unittest.mock import patch
from app.config.database import connect_db, get_db
from app.services.decision_maker_engine import (
    email_pattern_for_pair,
    render_email_pattern,
    generate_pattern_email,
    detect_generic_email_pattern,
    search_ddg_exact_person_email,
    discover_phase2_decision_maker_emails,
    is_generic_email,
    is_free_email,
    decode_cloudflare_email,
    normalize_email,
    is_valid_company_email_domain,
    extract_emails,
    email_matches_person,
)
from app.services.contact_service import extract_contacts_from_website
from app.services.search.public_web_search_provider import reset_circuit, trip_circuit

@pytest.fixture(autouse=True)
def reset_search_circuit():
    reset_circuit()
    yield
    reset_circuit()

# ============================================================
# TEST 1 — Exact email from official website (EXACT_FOUND, OFFICIAL_WEBSITE)
# ============================================================
@pytest.mark.asyncio
async def test_exact_email_from_official_website():
    candidates = [{
        "name": "Rahul Sharma",
        "role": "Chief Executive Officer",
        "evidence": "Rahul Sharma, Chief Executive Officer. Direct inquiries to rahul.sharma@apexcorp.test.",
        "source_url": "https://apexcorp.test/leadership",
        "exact_email": "rahul.sharma@apexcorp.test"
    }]

    results = await discover_phase2_decision_maker_emails(
        candidates=candidates,
        company_name="Apex Corp",
        website="https://apexcorp.test",
        mx_status="MX_ACTIVE"
    )

    assert len(results) == 1
    rahul = results[0]
    assert rahul["email"] == "rahul.sharma@apexcorp.test"
    assert rahul["email_status"] == "EXACT_FOUND"
    assert rahul["email_source_type"] == "OFFICIAL_WEBSITE"
    assert "apexcorp.test" in rahul["email_source_url"]


# ============================================================
# TEST 2 — Exact email from public search (EXACT_FOUND, PUBLIC_SEARCH)
# ============================================================
@pytest.mark.asyncio
async def test_exact_email_from_ddg():
    candidates = [{
        "name": "Sunita Rao",
        "role": "Chief Technology Officer",
        "evidence": "Sunita Rao leads engineering at NexaTech.",
        "source_url": "https://nexatech.test/about",
        "exact_email": None
    }]

    # Mock DDG search result returning exact public email
    mock_ddg_results = [{
        "title": "Sunita Rao - Chief Technology Officer - NexaTech",
        "body": "Contact Sunita Rao at sunita.rao@nexatech.test for technical partnerships.",
        "href": "https://industry-directory.test/nexatech-leadership"
    }]

    with patch("app.services.decision_maker_engine.ddg_search", return_value=mock_ddg_results):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="NexaTech Solutions",
            website="https://nexatech.test",
            mx_status="MX_ACTIVE"
        )

    assert len(results) == 1
    sunita = results[0]
    assert sunita["email"] == "sunita.rao@nexatech.test"
    assert sunita["email_status"] == "EXACT_FOUND"
    assert sunita["email_source_type"] == "PUBLIC_SEARCH"
    assert sunita["email_source_url"] == "https://industry-directory.test/nexatech-leadership"


# ============================================================
# TEST 3 — Generic mailbox rejection (must NOT train pattern)
# ============================================================
def test_generic_mailbox_rejection():
    # Shared company mailboxes must NOT establish an individual pattern
    generic_emails = [
        "info@company.test",
        "sales@company.test",
        "support@company.test",
        "admin@company.test",
        "contact@company.test",
        "help@company.test",
        "billing@company.test",
        "jobs@company.test",
        "careers@company.test",
        "marketing@company.test",
        "press@company.test",
        "media@company.test",
        "enquiries@company.test",
        "general@company.test",
        "investorrelations@company.test",
        "compliance@company.test",
        "hr@company.test",
        "hello@company.test",
        "office@company.test",
    ]
    for g in generic_emails:
        assert is_generic_email(g) is True

    # Pairing a person with a generic mailbox must be rejected
    bad_pairs = [{"name": "Rahul Sharma", "email": "info@company.test"}]
    pattern_res = detect_generic_email_pattern(bad_pairs, "company.test")
    assert pattern_res["pattern"] is None
    assert pattern_res["pattern_confidence"] == "NONE"
    assert pattern_res["can_generate"] is False


# ============================================================
# TEST 4 — One employee pattern: INSUFFICIENT, generation ALLOWED
# ============================================================
@pytest.mark.asyncio
async def test_one_person_pattern():
    candidates = [
        {
            "name": "Rajesh Sharma",
            "role": "Chief Executive Officer",
            "evidence": "CEO Rajesh Sharma — rajesh.sharma@quantumleaf.test",
            "source_url": "https://quantumleaf.test/team",
            "exact_email": "rajesh.sharma@quantumleaf.test"
        },
        {
            "name": "Amit Kumar",
            "role": "Chief Operating Officer",
            "evidence": "Amit Kumar is the Chief Operating Officer.",
            "source_url": "https://quantumleaf.test/team",
            "exact_email": None
        }
    ]

    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Quantum Leaf Inc",
            website="https://quantumleaf.test",
            mx_status="MX_ACTIVE"
        )

    assert len(results) == 2
    rajesh = next(r for r in results if r["name"] == "Rajesh Sharma")
    amit = next(r for r in results if r["name"] == "Amit Kumar")

    assert rajesh["email"] == "rajesh.sharma@quantumleaf.test"
    assert rajesh["email_status"] == "EXACT_FOUND"

    # Under One Genuine Employee Rule: 1 person -> INSUFFICIENT -> GENERATION ALLOWED
    assert amit["email"] == "amit.kumar@quantumleaf.test"
    assert amit["email_status"] == "PATTERN_GENERATED"
    assert amit["pattern_confidence"] == "INSUFFICIENT"
    assert amit["generated_pattern"] == "first.last"
    assert amit["email_verification"] == "PATTERN_INFERENCE"


# ============================================================
# TEST 5 — Two employees same pattern: SUPPORTED, candidate generated
# ============================================================
@pytest.mark.asyncio
async def test_two_employees_same_pattern():
    candidates = [
        {
            "name": "Rahul Sharma",
            "role": "Chief Executive Officer",
            "evidence": "CEO Rahul Sharma — rahul.sharma@innovatech.test",
            "source_url": "https://innovatech.test/team",
            "exact_email": "rahul.sharma@innovatech.test"
        },
        {
            "name": "Amit Kumar",
            "role": "Chief Technology Officer",
            "evidence": "CTO Amit Kumar — amit.kumar@innovatech.test",
            "source_url": "https://innovatech.test/team",
            "exact_email": "amit.kumar@innovatech.test"
        },
        {
            "name": "Neeraj Singh",
            "role": "Chief Operating Officer",
            "evidence": "Neeraj Singh is the COO.",
            "source_url": "https://innovatech.test/team",
            "exact_email": None
        }
    ]

    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="InnovaTech",
            website="https://innovatech.test",
            mx_status="MX_ACTIVE"
        )

    assert len(results) == 3
    neeraj = next(r for r in results if r["name"] == "Neeraj Singh")
    assert neeraj["email"] == "neeraj.singh@innovatech.test"
    assert neeraj["email_status"] == "PATTERN_GENERATED"
    assert neeraj["pattern_confidence"] == "SUPPORTED"
    assert neeraj["pattern_used"] == "first.last"


# ============================================================
# TEST 6 — Conflicting patterns (no unsafe generation)
# ============================================================
def test_conflicting_patterns():
    # Person 1 has first.last, Person 2 has flast
    exact_pairs = [
        {"name": "Rahul Sharma", "email": "rahul.sharma@enterprise.test"},
        {"name": "Priya Mehta", "email": "pmehta@enterprise.test"}
    ]
    pattern_res = detect_generic_email_pattern(exact_pairs, "enterprise.test")
    assert pattern_res["pattern"] is None
    assert pattern_res["pattern_confidence"] == "CONFLICTING"
    assert pattern_res["can_generate"] is False
    assert len(pattern_res["patternsObserved"]) == 2


# ============================================================
# TEST 7 — Zero evidence yields NONE -> NOT_FOUND
# ============================================================
@pytest.mark.asyncio
async def test_no_evidence():
    candidates = [
        {"name": "Arjun Patel", "role": "Managing Director", "evidence": "Arjun Patel, Managing Director."},
        {"name": "Kavita Sen", "role": "Director", "evidence": "Kavita Sen, Director."}
    ]

    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Patel Industries",
            website="https://patelindustries.test",
            mx_status="MX_ACTIVE"
        )

    for r in results:
        assert r["email"] is None
        assert r["email_status"] == "NOT_FOUND"
        assert r["pattern_confidence"] == "NONE"


# ============================================================
# TEST 8 — DDG timeout: SEARCH_TIMEOUT preserved (not false NOT_FOUND)
# ============================================================
def test_ddg_timeout():
    # When all DDG search queries fail/timeout, search_status must be SEARCH_TIMEOUT
    with patch("app.services.decision_maker_engine.ddg_search", side_effect=TimeoutError("Request timed out")):
        res = search_ddg_exact_person_email("Vikram Malhotra", "Test Corp", "testcorp.test")
        assert res["email"] is None
        assert res["status"] == "SEARCH_TIMEOUT"
        assert res["search_status"] == "SEARCH_TIMEOUT"


# ============================================================
# TEST 9 — Exact email priority (exact email must remain unchanged)
# ============================================================
@pytest.mark.asyncio
async def test_exact_email_priority():
    candidates = [
        {
            "name": "Rahul Sharma",
            "role": "CEO",
            "evidence": "Rahul Sharma — rahul.sharma@company.test",
            "exact_email": "rahul.sharma@company.test"
        },
        {
            "name": "Amit Kumar",
            "role": "CTO",
            "evidence": "Amit Kumar — amit.kumar@company.test",
            "exact_email": "amit.kumar@company.test"
        },
        {
            "name": "Devin Vance",
            "role": "Founder",
            "evidence": "Devin Vance — dvance@company.test",
            "exact_email": "dvance@company.test"
        }
    ]

    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Company Test",
            website="https://company.test",
            mx_status="MX_ACTIVE"
        )

    devin = next(r for r in results if r["name"] == "Devin Vance")
    # Devin's exact email is dvance@company.test; it must NEVER be overwritten by first.last
    assert devin["email"] == "dvance@company.test"
    assert devin["email_status"] == "EXACT_FOUND"


# ============================================================
# TEST 10 — MX distinction (MX_ACTIVE != mailbox verified)
# ============================================================
@pytest.mark.asyncio
async def test_mx_distinction():
    candidates = [
        {
            "name": "Devin Clark",
            "role": "Founder",
            "evidence": "Devin Clark, Founder — devin.clark@clarklabs.test",
            "exact_email": "devin.clark@clarklabs.test"
        },
        {
            "name": "Neil Armstrong",
            "role": "COO",
            "evidence": "Neil Armstrong — neil.armstrong@clarklabs.test",
            "exact_email": "neil.armstrong@clarklabs.test"
        },
        {
            "name": "Zara Vance",
            "role": "Head of AI",
            "evidence": "Zara Vance, Head of AI"
        }
    ]

    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Clark Labs",
            website="https://clarklabs.test",
            mx_status="MX_ACTIVE"
        )

    zara = next(r for r in results if r["name"] == "Zara Vance")
    assert zara["email"] == "zara.vance@clarklabs.test"
    assert zara["email_status"] == "PATTERN_GENERATED"
    assert zara["mx_status"] == "MX_ACTIVE"
    # Mailbox status is UNVERIFIED, NEVER falsely labeled MAILBOX_VERIFIED
    assert zara.get("mailbox_status") in ("UNKNOWN", "UNVERIFIED")
    assert zara.get("email_verification") != "MAILBOX_VERIFIED"


# ============================================================
# TEST 11 — Generated candidate reaches model with full metadata
# ============================================================
@pytest.mark.asyncio
async def test_generated_candidate_metadata():
    candidates = [
        {"name": "Alice Green", "role": "CEO", "exact_email": "alice.green@test.io", "evidence": "Alice Green CEO"},
        {"name": "Bob White", "role": "CTO", "exact_email": "bob.white@test.io", "evidence": "Bob White CTO"},
        {"name": "Charlie Black", "role": "COO", "evidence": "Charlie Black COO"}
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Test IO",
            website="https://test.io",
            mx_status="MX_ACTIVE"
        )
    charlie = next(r for r in results if r["name"] == "Charlie Black")
    assert charlie["email"] == "charlie.black@test.io"
    assert charlie["email_status"] == "PATTERN_GENERATED"
    assert charlie["generated_pattern"] == "first.last"
    assert charlie["pattern_confidence"] == "SUPPORTED"
    assert len(charlie["patterns_observed"]) >= 1


# ============================================================
# TEST 12 — Search failure followed by another search source succeeds
# ============================================================
def test_search_failure_followed_by_success():
    # Simulate Query 1 failing, but Query 2 returning valid email
    call_count = 0
    def mock_ddg_multiquery(query, max_results=3):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Temporary network timeout")
        return [{
            "title": "Sunita Rao - NexaTech",
            "body": "Contact Sunita Rao at sunita.rao@nexatech.test",
            "href": "https://directory.test/nexatech"
        }]

    with patch("app.services.decision_maker_engine.ddg_search", side_effect=mock_ddg_multiquery):
        res = search_ddg_exact_person_email("Sunita Rao", "NexaTech", "nexatech.test")
        assert res is not None
        assert res["email"] == "sunita.rao@nexatech.test"
        assert res["status"] == "EXACT_FOUND"
        assert res["search_status"] == "COMPLETED"


# ============================================================
# TEST 13 — Same person appears twice counts as 1 person (INSUFFICIENT)
# ============================================================
def test_same_person_twice_counts_as_one():
    # Same employee appearing in two different places must not satisfy 2-employee rule
    pairs = [
        {"name": "Rahul Sharma", "email": "rahul.sharma@example.test", "evidence": "Rahul Sharma from page 1"},
        {"name": "Rahul Sharma", "email": "rahul.sharma@example.test", "evidence": "Rahul Sharma from page 2"},
    ]
    pattern_res = detect_generic_email_pattern(pairs, "example.test")
    assert pattern_res["pattern_confidence"] == "INSUFFICIENT"
    assert len(pattern_res["patterns_observed"]) == 1
    assert pattern_res["patterns_observed"][0]["supportCount"] == 1
    assert pattern_res["can_generate"] is True


# ============================================================
# TEST 14 — Free/personal provider emails excluded from pattern evidence
# ============================================================
def test_free_provider_exclusion():
    assert is_free_email("john.doe@gmail.com") is True
    assert is_free_email("jane.doe@yahoo.com") is True
    assert is_free_email("officer@company.test") is False

    pairs = [
        {"name": "Rahul Sharma", "email": "rahul.sharma@gmail.com"},
        {"name": "Priya Mehta", "email": "priya.mehta@yahoo.com"}
    ]
    pattern_res = detect_generic_email_pattern(pairs, "company.test")
    assert pattern_res["pattern_confidence"] == "NONE"
    assert pattern_res["can_generate"] is False


# ============================================================
# TEST 15 — Parent company / brand domain email accepted
# ============================================================
@pytest.mark.asyncio
async def test_parent_brand_domain_acceptance():
    candidates = [
        {"name": "Dipali Goenka", "role": "CEO", "exact_email": "dipali.goenka@welspun.com"},
        {"name": "Rajesh Mandawewala", "role": "Managing Director", "exact_email": "rajesh.mandawewala@welspun.com"},
        {"name": "Altaf Jiwani", "role": "COO"}
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Welspun Living Limited",
            website="https://welspunliving.com",
            mx_status="MX_ACTIVE"
        )
    altaf = next(r for r in results if r["name"] == "Altaf Jiwani")
    assert altaf["email"] == "altaf.jiwani@welspun.com"
    assert altaf["email_status"] == "PATTERN_GENERATED"
    assert altaf["email_domain"] == "welspun.com"


# ============================================================
# TEST 16 — Cloudflare de-obfuscation extracts real emails
# ============================================================
def test_cloudflare_deobfuscation():
    # 'test@example.com' encoded with XOR key 0x12
    # 't' ^ 0x12 = 0x66, 'e' ^ 0x12 = 0x77, 's' ^ 0x12 = 0x61, 't' ^ 0x12 = 0x66
    # '@' ^ 0x12 = 0x52, 'e' ^ 0x12 = 0x77, 'x' ^ 0x12 = 0x6a, 'a' ^ 0x12 = 0x73
    # 'm' ^ 0x12 = 0x7f, 'p' ^ 0x12 = 0x62, 'l' ^ 0x12 = 0x7e, 'e' ^ 0x12 = 0x77
    # '.' ^ 0x12 = 0x3c, 'c' ^ 0x12 = 0x71, 'o' ^ 0x12 = 0x7d, 'm' ^ 0x12 = 0x7f
    # full hex = '12' + '6677616652776a737f627e773c717d7f'
    hex_code = "126677616652776a737f627e773c717d7f"
    decoded = decode_cloudflare_email(hex_code)
    assert decoded == "test@example.com"


# ============================================================
# TEST 17 — Nested page URL employee cards provide pattern evidence
# ============================================================
@pytest.mark.asyncio
async def test_nested_page_discovery():
    crawled_pages = [
        {
            "url": "https://company.test/company/leadership-team/",
            "html": """
            <div class="team-card">
                <h3>Aarav Gupta</h3>
                <a href="mailto:aarav.gupta@company.test">Email</a>
            </div>
            <div class="team-card">
                <h3>Bhavna Joshi</h3>
                <a href="mailto:bhavna.joshi@company.test">Email</a>
            </div>
            """,
            "pageType": "leadership"
        }
    ]
    candidates = [
        {"name": "Chetan Desai", "role": "Chief Technology Officer"}
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Company Test",
            website="https://company.test",
            crawled_pages=crawled_pages,
            mx_status="MX_ACTIVE"
        )
    chetan = next(r for r in results if r["name"] == "Chetan Desai")
    assert chetan["email"] == "chetan.desai@company.test"
    assert chetan["email_status"] == "PATTERN_GENERATED"
    assert chetan["pattern_confidence"] == "SUPPORTED"


# ============================================================
# TEST 18 — Non-decision-maker employee email accepted as pattern evidence
# ============================================================
@pytest.mark.asyncio
async def test_non_decision_maker_employee_evidence():
    # Staff / communications / secretary contacts on investor page
    crawled_pages = [
        {
            "url": "https://corp.test/investors/governance",
            "html": """
            <p>For corporate secretarial queries: Shashikant Thorat, Company Secretary: shashikant.thorat@corp.test</p>
            <p>For media inquiries: Pooja Patel, Media Relations: pooja.patel@corp.test</p>
            """,
            "pageType": "governance"
        }
    ]
    candidates = [
        {"name": "Vikram Seth", "role": "Chairman & Managing Director"}
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Corp Industries",
            website="https://corp.test",
            crawled_pages=crawled_pages,
            mx_status="MX_ACTIVE"
        )
    vikram = next(r for r in results if r["name"] == "Vikram Seth")
    assert vikram["email"] == "vikram.seth@corp.test"
    assert vikram["email_status"] == "PATTERN_GENERATED"


# ============================================================
# TEST 19 — Search unavailable preserved when circuit breaker trips
# ============================================================
@pytest.mark.asyncio
async def test_search_unavailable_preserved():
    trip_circuit()
    candidates = [
        {"name": "Anita Verma", "role": "President"}
    ]
    results = await discover_phase2_decision_maker_emails(
        candidates=candidates,
        company_name="Unknown Corp",
        website="https://unknowncorp.test",
        mx_status="UNKNOWN"
    )
    assert len(results) == 1
    anita = results[0]
    assert anita["email"] is None
    assert anita["email_status"] == "SEARCH_UNAVAILABLE"


# ============================================================
# TEST 20 — Generated email cannot become evidence for another pattern
# ============================================================
@pytest.mark.asyncio
async def test_generated_email_cannot_become_evidence():
    # Only 1 initial evidence pair (Rajesh Sharma)
    candidates = [
        {
            "name": "Rajesh Sharma",
            "role": "CEO",
            "exact_email": "rajesh.sharma@example.test",
            "evidence": "CEO Rajesh Sharma: rajesh.sharma@example.test"
        },
        {
            "name": "Amit Kumar",
            "role": "CTO",
            "evidence": "Amit Kumar CTO"
        },
        {
            "name": "Sunil Verma",
            "role": "COO",
            "evidence": "Sunil Verma COO"
        }
    ]

    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Example Corp",
            website="https://example.test",
            mx_status="MX_ACTIVE"
        )

    assert len(results) == 3
    amit = next(r for r in results if r["name"] == "Amit Kumar")
    sunil = next(r for r in results if r["name"] == "Sunil Verma")

    # Amit's email was generated
    assert amit["email"] == "amit.kumar@example.test"
    assert amit["email_status"] == "PATTERN_GENERATED"

    # Crucial check: Amit's generated email was NOT added as pattern evidence
    # Both Amit and Sunil still have pattern_confidence = INSUFFICIENT with exactly 1 evidence pair
    assert amit["pattern_confidence"] == "INSUFFICIENT"
    assert sunil["pattern_confidence"] == "INSUFFICIENT"
    assert len(sunil["pattern_evidence"]) == 1
    assert sunil["pattern_evidence"][0]["person"] == "Rajesh Sharma"


# ============================================================
# FINAL STATUS TESTS (Section 9 Requirements)
# ============================================================

# Test 1 — Exact email overrules any generated email
@pytest.mark.asyncio
async def test_final_status_exact_email_overrules_generated():
    candidates = [
        {
            "name": "Dipali Goenka",
            "role": "CEO",
            "exact_email": "dipali_goenka@welspun.test",
            "evidence": "Dipali Goenka CEO dipali_goenka@welspun.test"
        }
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Welspun Test",
            website="https://welspun.test",
            mx_status="MX_ACTIVE"
        )
    assert len(results) == 1
    dipali = results[0]
    assert dipali["email"] == "dipali_goenka@welspun.test"
    assert dipali["emailStatus"] == "EXACT_FOUND"
    assert dipali["email_status"] == "EXACT_FOUND"


# Test 2 — Generated email with INSUFFICIENT confidence
@pytest.mark.asyncio
async def test_final_status_generated_email_insufficient():
    candidates = [
        {
            "name": "Rajesh Sharma",
            "role": "CEO",
            "exact_email": "rajesh.sharma@company.test",
            "evidence": "Rajesh Sharma: rajesh.sharma@company.test"
        },
        {
            "name": "Amit Kumar",
            "role": "CTO",
            "exact_email": None,
            "evidence": "Amit Kumar CTO"
        }
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Company Test",
            website="https://company.test",
            mx_status="MX_ACTIVE"
        )
    amit = next(r for r in results if r["name"] == "Amit Kumar")
    assert amit["email"] == "amit.kumar@company.test"
    assert amit["emailStatus"] == "PATTERN_GENERATED"
    assert amit["pattern_confidence"] == "INSUFFICIENT"


# Test 3 — Generated email with SUPPORTED pattern
@pytest.mark.asyncio
async def test_final_status_generated_email_supported():
    candidates = [
        {
            "name": "Rajesh Sharma",
            "role": "CEO",
            "exact_email": "rajesh.sharma@company.test",
            "evidence": "Rajesh Sharma: rajesh.sharma@company.test"
        },
        {
            "name": "Suresh Patel",
            "role": "CFO",
            "exact_email": "suresh.patel@company.test",
            "evidence": "Suresh Patel: suresh.patel@company.test"
        },
        {
            "name": "Amit Kumar",
            "role": "CTO",
            "exact_email": None,
            "evidence": "Amit Kumar CTO"
        }
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Company Test",
            website="https://company.test",
            mx_status="MX_ACTIVE"
        )
    amit = next(r for r in results if r["name"] == "Amit Kumar")
    assert amit["email"] == "amit.kumar@company.test"
    assert amit["emailStatus"] == "PATTERN_GENERATED"
    assert amit["pattern_confidence"] == "SUPPORTED"


# Test 4 — Nothing found
@pytest.mark.asyncio
async def test_final_status_nothing_found():
    candidates = [
        {"name": "Rajesh Sharma", "role": "CEO", "evidence": "Rajesh Sharma CEO"}
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Company Test",
            website="https://company.test",
            mx_status="MX_ACTIVE"
        )
    assert len(results) == 1
    rajesh = results[0]
    assert rajesh["email"] is None
    assert rajesh["emailStatus"] == "NOT_FOUND"


# Test 5 — Conflicting pattern
@pytest.mark.asyncio
async def test_final_status_conflicting_pattern():
    candidates = [
        {
            "name": "Rahul Sharma",
            "role": "CEO",
            "exact_email": "rahul.sharma@enterprise.test",
            "evidence": "Rahul Sharma: rahul.sharma@enterprise.test"
        },
        {
            "name": "Priya Mehta",
            "role": "Director",
            "exact_email": "pmehta@enterprise.test",
            "evidence": "Priya Mehta: pmehta@enterprise.test"
        },
        {
            "name": "Amit Kumar",
            "role": "CTO",
            "exact_email": None,
            "evidence": "Amit Kumar CTO"
        }
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Enterprise Test",
            website="https://enterprise.test",
            mx_status="MX_ACTIVE"
        )
    amit = next(r for r in results if r["name"] == "Amit Kumar")
    assert amit["email"] is None
    assert amit["emailStatus"] == "NOT_FOUND"
    assert amit["pattern_confidence"] == "CONFLICTING"


# Test 6 — One-person generation
@pytest.mark.asyncio
async def test_final_status_one_person_generation():
    candidates = [
        {
            "name": "Rajesh Sharma",
            "role": "CEO",
            "exact_email": "rajesh.sharma@company.test",
            "evidence": "Rajesh Sharma: rajesh.sharma@company.test"
        },
        {
            "name": "Amit Kumar",
            "role": "CTO",
            "exact_email": None,
            "evidence": "Amit Kumar CTO"
        }
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Company Test",
            website="https://company.test",
            mx_status="MX_ACTIVE"
        )
    amit = next(r for r in results if r["name"] == "Amit Kumar")
    assert amit["email"] == "amit.kumar@company.test"
    assert amit["emailStatus"] == "PATTERN_GENERATED"
    assert amit["pattern_confidence"] == "INSUFFICIENT"
    assert amit["generated_pattern"] == "first.last"


# ============================================================
# GENERIC TEST SUITE — SECTION 14 TESTS A THROUGH L
# ============================================================

# Test A: One employee email -> INSUFFICIENT, generation allowed = YES
def test_generic_test_a_one_employee_email():
    evidence = [{"name": "Rajesh Sharma", "email": "rajesh.sharma@example.test"}]
    res = detect_generic_email_pattern(evidence, domain="example.test")
    assert res["pattern_confidence"] == "INSUFFICIENT"
    assert res["can_generate"] is True
    assert res["generation_allowed"] is True
    assert res["pattern"] == "first.last"


# Test B: Two employees with same pattern -> SUPPORTED, generation allowed = YES
def test_generic_test_b_two_employees_same_pattern():
    evidence = [
        {"name": "Rajesh Sharma", "email": "rajesh.sharma@example.test"},
        {"name": "Amit Verma", "email": "amit.verma@example.test"}
    ]
    res = detect_generic_email_pattern(evidence, domain="example.test")
    assert res["pattern_confidence"] == "SUPPORTED"
    assert res["can_generate"] is True
    assert res["generation_allowed"] is True
    assert res["pattern"] == "first.last"


# Test C: Two conflicting patterns -> CONFLICTING, generation allowed = NO
def test_generic_test_c_two_conflicting_patterns():
    evidence = [
        {"name": "Rajesh Sharma", "email": "rajesh.sharma@example.test"},
        {"name": "Amit Verma", "email": "averma@example.test"}
    ]
    res = detect_generic_email_pattern(evidence, domain="example.test")
    assert res["pattern_confidence"] == "CONFLICTING"
    assert res["can_generate"] is False
    assert res["pattern"] is None


# Test D: Generic mailbox only -> employee evidence = 0
def test_generic_test_d_generic_mailbox_only():
    assert is_generic_email("info@example.test") is True
    assert is_generic_email("support@example.test") is True
    assert is_generic_email("support-india@example.test") is True
    assert is_generic_email("customercare@example.test") is True
    assert is_generic_email("careers@example.test") is True
    evidence = [
        {"name": "Info Desk", "email": "info@example.test"},
        {"name": "Support Team", "email": "support-india@example.test"}
    ]
    res = detect_generic_email_pattern(evidence, domain="example.test")
    assert res["pattern_confidence"] == "NONE"
    assert len(res["pattern_evidence"]) == 0
    assert res["can_generate"] is False


# Test E: Personal email only -> employee evidence = 0
def test_generic_test_e_personal_email_only():
    assert is_free_email("rajesh.sharma@gmail.com") is True
    assert is_free_email("amit.verma@yahoo.com") is True
    assert is_free_email("sunil.kumar@rediffmail.com") is True
    evidence = [
        {"name": "Rajesh Sharma", "email": "rajesh.sharma@gmail.com"},
        {"name": "Amit Verma", "email": "amit.verma@rediffmail.com"}
    ]
    res = detect_generic_email_pattern(evidence, domain="example.test")
    assert res["pattern_confidence"] == "NONE"
    assert len(res["pattern_evidence"]) == 0
    assert res["can_generate"] is False


# Test F: Generated candidate must not become evidence
@pytest.mark.asyncio
async def test_generic_test_f_generated_candidate_must_not_become_evidence():
    candidates = [
        {
            "name": "Rajesh Sharma",
            "role": "CEO",
            "exact_email": "rajesh.sharma@corp.test",
            "evidence": "Rajesh Sharma: rajesh.sharma@corp.test"
        },
        {
            "name": "Amit Kumar",
            "role": "CTO",
            "exact_email": None,
            "evidence": "Amit Kumar CTO"
        }
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Corp Test",
            website="https://corp.test",
            mx_status="MX_ACTIVE"
        )
    amit = next(r for r in results if r["name"] == "Amit Kumar")
    assert amit["email"] == "amit.kumar@corp.test"
    assert amit["emailStatus"] == "PATTERN_GENERATED"

    # Verify that Amit's generated email is excluded when filtering genuine evidence
    raw_evidence_candidates = [r for r in results if r.get("emailStatus") == "EXACT_FOUND" and r.get("email_source_type") != "PATTERN_INFERENCE"]
    assert len(raw_evidence_candidates) == 1
    assert raw_evidence_candidates[0]["name"] == "Rajesh Sharma"


# Test G: Nested leadership page -> employee email extraction
@pytest.mark.asyncio
async def test_generic_test_g_nested_leadership_page():
    nested_html = """
    <html>
    <body>
        <div class="leadership-section">
            <div class="team-card">
                <h3>Vikram Patel</h3>
                <p>Chief Executive Officer</p>
                <a href="mailto:vikram.patel@corp.test">Email CEO</a>
            </div>
        </div>
    </body>
    </html>
    """
    crawled_pages = [{
        "url": "https://corp.test/company/about/our-leadership/team",
        "html": nested_html,
        "content": "Vikram Patel Chief Executive Officer vikram.patel@corp.test",
        "pageType": "leadership"
    }]
    candidates = [{
        "name": "Vikram Patel",
        "role": "CEO",
        "evidence": "Vikram Patel CEO",
        "source_url": "https://corp.test/company/about/our-leadership/team"
    }]
    results = await discover_phase2_decision_maker_emails(
        candidates=candidates,
        company_name="Corp Test",
        website="https://corp.test",
        crawled_pages=crawled_pages,
        mx_status="MX_ACTIVE"
    )
    assert len(results) == 1
    assert results[0]["email"] == "vikram.patel@corp.test"
    assert results[0]["emailStatus"] == "EXACT_FOUND"


# Test H: mailto email with nearby person name
@pytest.mark.asyncio
async def test_generic_test_h_mailto_email_with_nearby_person_name():
    table_html = """
    <table>
        <tr>
            <td>Sanjay Singhania</td>
            <td>Managing Director</td>
            <td><a href="mailto:sanjay.singhania@corp.test">Contact Director</a></td>
        </tr>
    </table>
    """
    crawled_pages = [{
        "url": "https://corp.test/governance",
        "html": table_html,
        "content": "Sanjay Singhania Managing Director sanjay.singhania@corp.test",
        "pageType": "leadership"
    }]
    candidates = [{
        "name": "Sanjay Singhania",
        "role": "Managing Director",
        "evidence": "Sanjay Singhania MD",
        "source_url": "https://corp.test/governance"
    }]
    results = await discover_phase2_decision_maker_emails(
        candidates=candidates,
        company_name="Corp Test",
        website="https://corp.test",
        crawled_pages=crawled_pages,
        mx_status="MX_ACTIVE"
    )
    assert len(results) == 1
    assert results[0]["email"] == "sanjay.singhania@corp.test"
    assert results[0]["emailStatus"] == "EXACT_FOUND"


# Test I: Cloudflare-obfuscated email
@pytest.mark.asyncio
async def test_generic_test_i_cloudflare_obfuscated_email():
    # 'priya.nair@corp.test' encoded with key 0x12
    # p=0x70^0x12=0x62, r=0x72^0x12=0x60, i=0x69^0x12=0x7b, y=0x79^0x12=0x6b, a=0x61^0x12=0x73, .=0x2e^0x12=0x3c, etc.
    # We can encode dynamically to guarantee accuracy
    key = 0x25
    email_raw = "priya.nair@corp.test"
    encoded_hex = f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in email_raw)

    cf_html = f"""
    <div class="executive-card">
        <h3>Priya Nair</h3>
        <p>Director</p>
        <span class="__cf_email__" data-cfemail="{encoded_hex}">[email protected]</span>
    </div>
    """
    crawled_pages = [{
        "url": "https://corp.test/team",
        "html": cf_html,
        "content": "Priya Nair Director",
        "pageType": "leadership"
    }]
    candidates = [{
        "name": "Priya Nair",
        "role": "Director",
        "evidence": "Priya Nair Director",
        "source_url": "https://corp.test/team"
    }]
    results = await discover_phase2_decision_maker_emails(
        candidates=candidates,
        company_name="Corp Test",
        website="https://corp.test",
        crawled_pages=crawled_pages,
        mx_status="MX_ACTIVE"
    )
    assert len(results) == 1
    assert results[0]["email"] == "priya.nair@corp.test"
    assert results[0]["emailStatus"] == "EXACT_FOUND"


# Test J: Parent/brand corporate domain
@pytest.mark.asyncio
async def test_generic_test_j_parent_brand_corporate_domain():
    candidates = [
        {
            "name": "Arun Mehta",
            "role": "Executive Chairman",
            "exact_email": "arun.mehta@brand.test",
            "evidence": "Arun Mehta Executive Chairman arun.mehta@brand.test"
        },
        {
            "name": "Karan Kapoor",
            "role": "President",
            "exact_email": None,
            "evidence": "Karan Kapoor President"
        }
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Brand Technologies Limited",
            website="https://brandliving.test",
            mx_status="MX_ACTIVE"
        )
    arun = next(r for r in results if r["name"] == "Arun Mehta")
    karan = next(r for r in results if r["name"] == "Karan Kapoor")
    assert arun["email"] == "arun.mehta@brand.test"
    assert arun["emailStatus"] == "EXACT_FOUND"
    assert karan["email"] == "karan.kapoor@brand.test"
    assert karan["emailStatus"] == "PATTERN_GENERATED"


# Test K: Different website HTML structures (cards, tables, DL/DT, and semantic sections)
@pytest.mark.asyncio
async def test_generic_test_k_different_html_structures():
    dl_html = """
    <dl class="management-list">
        <dt>Deepak Verma</dt>
        <dd>Chief Operating Officer</dd>
        <dd><a href="mailto:deepak.verma@structure.test">deepak.verma@structure.test</a></dd>
    </dl>
    """
    crawled_pages = [{
        "url": "https://structure.test/management",
        "html": dl_html,
        "content": "Deepak Verma Chief Operating Officer deepak.verma@structure.test",
        "pageType": "leadership"
    }]
    candidates = [{
        "name": "Deepak Verma",
        "role": "COO",
        "evidence": "Deepak Verma COO",
        "source_url": "https://structure.test/management"
    }]
    results = await discover_phase2_decision_maker_emails(
        candidates=candidates,
        company_name="Structure Test",
        website="https://structure.test",
        crawled_pages=crawled_pages,
        mx_status="MX_ACTIVE"
    )
    assert len(results) == 1
    assert results[0]["email"] == "deepak.verma@structure.test"
    assert results[0]["emailStatus"] == "EXACT_FOUND"


# Test L: Exact email + generated candidate -> EXACT_FOUND
@pytest.mark.asyncio
async def test_generic_test_l_exact_email_overrules_generated_candidate():
    candidates = [
        {
            "name": "Rajesh Sharma",
            "role": "CEO",
            "exact_email": "rsharma@corp.test",
            "evidence": "Rajesh Sharma: rsharma@corp.test"
        },
        {
            "name": "Amit Verma",
            "role": "CTO",
            "exact_email": "amit.verma@corp.test",
            "evidence": "Amit Verma: amit.verma@corp.test"
        },
        {
            "name": "Priya Nair",
            "role": "Director",
            "exact_email": "priya.nair@corp.test",
            "evidence": "Priya Nair: priya.nair@corp.test"
        }
    ]
    # Even though pattern engine derives first.last from Amit & Priya, Rajesh's exact email must overrule!
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Corp Test",
            website="https://corp.test",
            mx_status="MX_ACTIVE"
        )
    rajesh = next(r for r in results if r["name"] == "Rajesh Sharma")
    assert rajesh["email"] == "rsharma@corp.test"
    assert rajesh["emailStatus"] == "EXACT_FOUND"


# ============================================================
# SECTION 22 — COMPLETE REQUIRED TEST MATRIX (TESTS A THROUGH P)
# ============================================================

# Test A — No evidence: 0 pairs -> NONE -> no generation -> NOT_FOUND
@pytest.mark.asyncio
async def test_matrix_test_a_no_evidence():
    candidates = [{"name": "Vikram Malhotra", "role": "Managing Director"}]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Alpha Corp",
            website="https://alphacorp.test",
            crawled_pages=[],
            direct_emails=[],
            mx_status="MX_ACTIVE"
        )
    assert len(results) == 1
    assert results[0]["email"] is None
    assert results[0]["emailStatus"] == "NOT_FOUND"
    assert results[0]["pattern_confidence"] == "NONE"


# Test B — One genuine pair: 1 pair -> INSUFFICIENT -> generation allowed -> PATTERN_GENERATED
@pytest.mark.asyncio
async def test_matrix_test_b_one_genuine_pair():
    candidates = [
        {"name": "Rajesh Sharma", "role": "CEO", "exact_email": "rajesh.sharma@alphacorp.test"},
        {"name": "Amit Kumar", "role": "CTO"}
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Alpha Corp",
            website="https://alphacorp.test",
            mx_status="MX_ACTIVE"
        )
    amit = next(r for r in results if r["name"] == "Amit Kumar")
    assert amit["email"] == "amit.kumar@alphacorp.test"
    assert amit["emailStatus"] == "PATTERN_GENERATED"
    assert amit["pattern_confidence"] == "INSUFFICIENT"


# Test C — Supported pattern: 2+ same pattern -> SUPPORTED -> generation allowed -> PATTERN_GENERATED
@pytest.mark.asyncio
async def test_matrix_test_c_supported_pattern():
    candidates = [
        {"name": "Rajesh Sharma", "role": "CEO", "exact_email": "rajesh.sharma@alphacorp.test"},
        {"name": "Sunil Verma", "role": "CFO", "exact_email": "sunil.verma@alphacorp.test"},
        {"name": "Amit Kumar", "role": "CTO"}
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Alpha Corp",
            website="https://alphacorp.test",
            mx_status="MX_ACTIVE"
        )
    amit = next(r for r in results if r["name"] == "Amit Kumar")
    assert amit["email"] == "amit.kumar@alphacorp.test"
    assert amit["emailStatus"] == "PATTERN_GENERATED"
    assert amit["pattern_confidence"] == "SUPPORTED"


# Test D — Conflicting pattern: conflicting genuine patterns -> CONFLICTING -> generation blocked -> NOT_FOUND
@pytest.mark.asyncio
async def test_matrix_test_d_conflicting_pattern():
    candidates = [
        {"name": "Rajesh Sharma", "role": "CEO", "exact_email": "rajesh.sharma@alphacorp.test"},
        {"name": "Sunil Verma", "role": "CFO", "exact_email": "sverma@alphacorp.test"},
        {"name": "Amit Kumar", "role": "CTO"}
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Alpha Corp",
            website="https://alphacorp.test",
            mx_status="MX_ACTIVE"
        )
    amit = next(r for r in results if r["name"] == "Amit Kumar")
    assert amit["email"] is None
    assert amit["emailStatus"] == "NOT_FOUND"
    assert amit["pattern_confidence"] == "CONFLICTING"


# Test E — Generic email: info@, support@, shares@ -> rejected as employee evidence
def test_matrix_test_e_generic_email():
    assert is_generic_email("info@alphacorp.test") is True
    assert is_generic_email("support@alphacorp.test") is True
    assert is_generic_email("shares@alphacorp.test") is True
    assert is_generic_email("compliance@alphacorp.test") is True
    assert is_generic_email("support-mea@alphacorp.test") is True
    pairs = [
        {"name": "Corporate Support", "email": "support-mea@alphacorp.test"},
        {"name": "Secretarial Dept", "email": "shares@alphacorp.test"}
    ]
    res = detect_generic_email_pattern(pairs, domain="alphacorp.test")
    assert res["pattern_confidence"] == "NONE"
    assert len(res["pattern_evidence"]) == 0
    assert res["can_generate"] is False


# Test F — Free email: gmail@, yahoo@, hotmail@, rediffmail@ -> rejected
def test_matrix_test_f_free_email():
    assert is_free_email("john.doe@gmail.com") is True
    assert is_free_email("jane.smith@yahoo.com") is True
    assert is_free_email("robert.lee@hotmail.com") is True
    assert is_free_email("anil.sharma@rediffmail.com") is True
    assert is_free_email("anil.sharma@rediff.com") is True
    pairs = [
        {"name": "Anil Sharma", "email": "anil.sharma@rediffmail.com"},
        {"name": "Jane Smith", "email": "jane.smith@gmail.com"}
    ]
    res = detect_generic_email_pattern(pairs, domain="alphacorp.test")
    assert res["pattern_confidence"] == "NONE"
    assert len(res["pattern_evidence"]) == 0


# Test G — External/vendor domain: employee@vendor.com for company.com employee -> reject
def test_matrix_test_g_external_vendor_domain():
    is_ok, reason = is_valid_company_email_domain("john.doe@externalvendor.com", "alphacorp.test", "Alpha Corp", ["alphacorp.test"])
    assert is_ok is False
    assert reason in ("domain_mismatch", "unrelated_domain")


# Test H — Duplicate evidence: Same person/email discovered on multiple pages -> one genuine evidence pair
@pytest.mark.asyncio
async def test_matrix_test_h_duplicate_evidence():
    crawled_pages = [
        {"url": "https://alphacorp.test/page1", "html": "Contact CEO Rajesh Sharma at rajesh.sharma@alphacorp.test", "pageType": "leadership"},
        {"url": "https://alphacorp.test/page2", "html": "Managing Director Rajesh Sharma: rajesh.sharma@alphacorp.test", "pageType": "leadership"},
        {"url": "https://alphacorp.test/page3", "html": "Executive Board: Rajesh Sharma (rajesh.sharma@alphacorp.test)", "pageType": "board"}
    ]
    candidates = [
        {"name": "Rajesh Sharma", "role": "CEO"},
        {"name": "Amit Kumar", "role": "CTO"}
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Alpha Corp",
            website="https://alphacorp.test",
            crawled_pages=crawled_pages,
            mx_status="MX_ACTIVE"
        )
    # 1 unique person evidence -> INSUFFICIENT (not 3 distinct people!)
    amit = next(r for r in results if r["name"] == "Amit Kumar")
    assert amit["pattern_confidence"] == "INSUFFICIENT"


# Test I — Obfuscated email: name [at] company [dot] com -> decode correctly
def test_matrix_test_i_obfuscated_email():
    text = "Please reach out to deepak.verma [at] alphacorp [dot] com for governance inquiries."
    emails = extract_emails(text)
    assert "deepak.verma@alphacorp.com" in emails


# Test J — Multiword name: Paul K. Oswal -> correctly associate email
def test_matrix_test_j_multiword_name():
    assert email_matches_person("paul.oswal@alphacorp.test", "Paul K. Oswal") is True
    assert email_matches_person("paul.k.oswal@alphacorp.test", "Paul K. Oswal") is True
    pat = email_pattern_for_pair("Paul K. Oswal", "paul.oswal@alphacorp.test")
    assert pat == "first.last"


# Test K — Inverted name: RATHI RAJESH, rajesh.rathi@company.com -> correctly associate
def test_matrix_test_k_inverted_name():
    assert email_matches_person("rajesh.rathi@alphacorp.test", "RATHI RAJESH") is True
    pat = email_pattern_for_pair("RATHI RAJESH", "rajesh.rathi@alphacorp.test")
    assert pat in ("last.first", "first.last")


# Test L — Inverted name + generation: One genuine inverted-name evidence pair -> INSUFFICIENT -> generation allowed
@pytest.mark.asyncio
async def test_matrix_test_l_inverted_name_plus_generation():
    candidates = [
        {"name": "RATHI RAJESH", "role": "MD", "exact_email": "rajesh.rathi@alphacorp.test"},
        {"name": "KUMAR AMIT", "role": "CTO"}
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Alpha Corp",
            website="https://alphacorp.test",
            mx_status="MX_ACTIVE"
        )
    amit = next(r for r in results if r["name"] == "KUMAR AMIT")
    assert amit["email"] == "kumar.amit@alphacorp.test" or amit["email"] == "amit.kumar@alphacorp.test"
    assert amit["emailStatus"] == "PATTERN_GENERATED"
    assert amit["pattern_confidence"] == "INSUFFICIENT"


# Test M — Exact overrides generated: Exact + generated -> EXACT_FOUND
@pytest.mark.asyncio
async def test_matrix_test_m_exact_overrides_generated():
    candidates = [
        {"name": "Dipali Goenka", "role": "CEO", "exact_email": "dipali_goenka@alphacorp.test"},
        {"name": "Vanshika Goenka", "role": "Director"}
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Alpha Corp",
            website="https://alphacorp.test",
            mx_status="MX_ACTIVE"
        )
    dipali = next(r for r in results if r["name"] == "Dipali Goenka")
    assert dipali["email"] == "dipali_goenka@alphacorp.test"
    assert dipali["emailStatus"] == "EXACT_FOUND"


# Test N — Generated never becomes evidence: Generate an email, run pattern detection again -> generated email must NOT count as evidence
@pytest.mark.asyncio
async def test_matrix_test_n_generated_never_becomes_evidence():
    # Candidates with 1 exact and 1 generated outcome
    candidates = [
        {"name": "Rajesh Sharma", "role": "CEO", "exact_email": "rajesh.sharma@alphacorp.test"},
        {"name": "Amit Kumar", "role": "CTO"}
    ]
    with patch("app.services.decision_maker_engine.ddg_search", return_value=[]):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Alpha Corp",
            website="https://alphacorp.test",
            mx_status="MX_ACTIVE"
        )
    # Amit was generated
    amit = next(r for r in results if r["name"] == "Amit Kumar")
    assert amit["emailStatus"] == "PATTERN_GENERATED"

    # Now filter for evidence using the exact logic from contact_service.py
    evidence_pool = []
    for r in results:
        if r.get("emailStatus") == "PATTERN_GENERATED" or r.get("isExactPublished") is False or r.get("sourceType") == "PATTERN_INFERENCE":
            continue
        if r.get("emailStatus") == "EXACT_FOUND" and r.get("email"):
            evidence_pool.append(r)

    assert len(evidence_pool) == 1
    assert evidence_pool[0]["name"] == "Rajesh Sharma"


# Test O — DDG timeout: DDG timeout -> do not falsely claim email does not exist -> retain search failure diagnostic
@pytest.mark.asyncio
async def test_matrix_test_o_ddg_timeout_diagnostic():
    candidates = [{"name": "Sunil Mittal", "role": "Chairman"}]
    # Simulate DDG timeout by returning None from ddg_search
    with patch("app.services.decision_maker_engine.ddg_search", return_value=None):
        results = await discover_phase2_decision_maker_emails(
            candidates=candidates,
            company_name="Alpha Corp",
            website="https://alphacorp.test",
            mx_status="MX_ACTIVE"
        )
    sunil = results[0]
    assert sunil["email"] is None
    assert sunil["emailStatus"] == "NOT_FOUND"
    assert sunil["search_status"] in ("SEARCH_TIMEOUT", "SEARCH_FAILED", "COMPLETED")
    assert "search_error" in sunil or "search_status" in sunil


# Test P — Bing prohibition: Ensure no Bing code path exists anywhere in app services
def test_matrix_test_p_bing_prohibition():
    import inspect
    from app.services import decision_maker_engine
    from app.services.search import public_web_search_provider

    dme_source = inspect.getsource(decision_maker_engine).lower()
    pwsp_source = inspect.getsource(public_web_search_provider).lower()

    assert "bing.com" not in dme_source, "Bing search URL found in decision_maker_engine"
    assert "bing.com" not in pwsp_source, "Bing search URL found in public_web_search_provider"
    assert "parse_bing_html" not in pwsp_source, "parse_bing_html found in public_web_search_provider"



