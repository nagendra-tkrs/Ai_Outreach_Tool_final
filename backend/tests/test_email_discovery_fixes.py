import pytest
import asyncio
from unittest.mock import patch, AsyncMock

from app.services.email_discovery_service import (
    discover_decision_maker_emails,
    detect_email_pattern_from_pairs,
    render_pattern_email
)
from app.services.email_validation_service import (
    match_person_to_email,
    validate_domain_match,
    is_generic_email,
    is_free_email
)
from app.services.email_extraction_service import (
    extract_emails_from_html,
    extract_emails_from_text,
    clean_email
)

@pytest.mark.asyncio
async def test_1_official_website_contains_email():
    """Test 1: Official website contains email -> EXACT_FOUND."""
    candidates = [{"name": "Sarah Connor", "title": "VP Engineering"}]
    crawled_pages = [
        {
            "url": "https://acme.com/team",
            "html": '<div>Sarah Connor - VP Engineering <a href="mailto:sarah.connor@acme.com">Email Sarah</a></div>'
        }
    ]

    results = await discover_decision_maker_emails(
        candidates=candidates,
        company_name="Acme Corp",
        website="https://acme.com",
        crawled_pages=crawled_pages
    )

    assert len(results) == 1
    res = results[0]
    assert res["email_status"] == "EXACT_FOUND"
    assert res["email"] == "sarah.connor@acme.com"
    assert res["isExactPublished"] is True
    assert "acme.com" in res["email_source_url"]


@pytest.mark.asyncio
async def test_2_target_leadership_page_via_ddg_has_email():
    """Test 2: Target leadership page found via DDG has email -> EXACT_FOUND."""
    candidates = [{"name": "John Doe", "title": "Chief Technology Officer"}]

    mock_search_res = {
        "status": "OK",
        "results": [
            {
                "title": "Leadership Team | Acme Corp",
                "snippet": "Meet John Doe, our CTO, and the leadership team.",
                "url": "https://acme.com/leadership"
            }
        ]
    }

    mock_html = """
    <html>
        <body>
            <div class="team-member">
                <h3>John Doe</h3>
                <p>Chief Technology Officer</p>
                <a href="mailto:john.doe@acme.com">Contact John</a>
            </div>
        </body>
    </html>
    """

    with patch("app.services.email_discovery_service.search_public_web", new_callable=AsyncMock) as mock_search, \
         patch("app.services.email_discovery_service.crawl_target_page", new_callable=AsyncMock) as mock_crawl:
        
        mock_search.return_value = mock_search_res
        mock_crawl.return_value = mock_html

        results = await discover_decision_maker_emails(
            candidates=candidates,
            company_name="Acme Corp",
            website="https://acme.com",
            crawled_pages=[]
        )

    assert len(results) == 1
    res = results[0]
    assert res["email_status"] == "EXACT_FOUND"
    assert res["email"] == "john.doe@acme.com"
    assert res["isExactPublished"] is True
    assert res["email_source_url"] == "https://acme.com/leadership"


@pytest.mark.asyncio
async def test_3_ddg_snippet_no_email_target_page_has_email():
    """Test 3: DDG snippet has no email, but target page has email -> EXACT_FOUND."""
    candidates = [{"name": "Jane Smith", "title": "Chief Executive Officer"}]

    # Snippet has zero email addresses
    mock_search_res = {
        "status": "OK",
        "results": [
            {
                "title": "About Us - Management Team",
                "snippet": "Jane Smith is CEO of Acme Corp. Learn about our executive vision and company history.",
                "url": "https://acme.com/about/executive-team"
            }
        ]
    }

    mock_target_html = """
    <div class="bio">
        <h3>Jane Smith</h3>
        <p>CEO</p>
        <p>Direct inquiries: jane.smith@acme.com</p>
    </div>
    """

    with patch("app.services.email_discovery_service.search_public_web", new_callable=AsyncMock) as mock_search, \
         patch("app.services.email_discovery_service.crawl_target_page", new_callable=AsyncMock) as mock_crawl:
        
        mock_search.return_value = mock_search_res
        mock_crawl.return_value = mock_target_html

        results = await discover_decision_maker_emails(
            candidates=candidates,
            company_name="Acme Corp",
            website="https://acme.com",
            crawled_pages=[]
        )

    assert len(results) == 1
    res = results[0]
    assert res["email_status"] == "EXACT_FOUND"
    assert res["email"] == "jane.smith@acme.com"
    assert res["isExactPublished"] is True


@pytest.mark.asyncio
async def test_4_two_company_emails_demonstrate_pattern():
    """Test 4: Two company emails demonstrate first.last -> PATTERN_GENERATED with evidence."""
    # First 2 candidates have exact emails found on site
    candidates = [
        {"name": "Alice Cooper", "title": "VP Sales"},
        {"name": "Bob Vance", "title": "Head of Operations"},
        {"name": "Charlie Day", "title": "Head of Marketing"}
    ]

    crawled_pages = [
        {
            "url": "https://acme.com/team",
            "html": """
            <div>Alice Cooper: alice.cooper@acme.com</div>
            <div>Bob Vance: bob.vance@acme.com</div>
            <div>Charlie Day: Marketing Lead</div>
            """
        }
    ]

    # Charlie Day search returns nothing
    with patch("app.services.email_discovery_service.search_public_web", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = {"status": "OK", "results": []}

        results = await discover_decision_maker_emails(
            candidates=candidates,
            company_name="Acme Corp",
            website="https://acme.com",
            crawled_pages=crawled_pages
        )

    assert len(results) == 3
    alice = next(r for r in results if r["name"] == "Alice Cooper")
    bob = next(r for r in results if r["name"] == "Bob Vance")
    charlie = next(r for r in results if r["name"] == "Charlie Day")

    assert alice["email_status"] == "EXACT_FOUND"
    assert bob["email_status"] == "EXACT_FOUND"

    # Charlie must have generated pattern email
    assert charlie["email_status"] == "PATTERN_GENERATED"
    assert charlie["email"] == "charlie.day@acme.com"
    assert charlie["generatedPattern"] == "first.last"
    assert charlie["patternConfidence"] in ("SUPPORTED", "STRONG")
    assert charlie["isExactPublished"] is False


@pytest.mark.asyncio
async def test_5_search_timeout_produces_search_timeout():
    """Test 5: Search timeout -> SEARCH_TIMEOUT (NOT NOT_FOUND)."""
    candidates = [{"name": "Dennis Reynolds", "title": "Director of Logistics"}]

    with patch("app.services.email_discovery_service.search_public_web", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = {
            "status": "SEARCH_TIMEOUT",
            "error": "Request timed out after 10.0s",
            "results": []
        }

        results = await discover_decision_maker_emails(
            candidates=candidates,
            company_name="Paddy's Pub",
            website="https://paddyspub.com",
            crawled_pages=[]
        )

    assert len(results) == 1
    res = results[0]
    assert res["email_status"] == "SEARCH_TIMEOUT"
    assert res["emailStatus"] == "SEARCH_TIMEOUT"
    assert res["email"] is None
    assert "timed out" in res["emailReason"].lower()


@pytest.mark.asyncio
async def test_6_search_unavailable_produces_search_unavailable():
    """Test 6: Search returns 403/429 -> SEARCH_UNAVAILABLE (NOT NOT_FOUND)."""
    candidates = [{"name": "Mac McDonald", "title": "Head of Security"}]

    with patch("app.services.email_discovery_service.search_public_web", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = {
            "status": "SEARCH_UNAVAILABLE",
            "error": "HTTP 429 Too Many Requests (Rate limit)",
            "results": []
        }

        results = await discover_decision_maker_emails(
            candidates=candidates,
            company_name="Paddy's Pub",
            website="https://paddyspub.com",
            crawled_pages=[]
        )

    assert len(results) == 1
    res = results[0]
    assert res["email_status"] == "SEARCH_UNAVAILABLE"
    assert res["emailStatus"] == "SEARCH_UNAVAILABLE"
    assert res["email"] is None
    assert "rate-limited" in res["emailReason"].lower() or "429" in res["emailReason"]


def test_7_person_name_with_middle_name_and_initials():
    """Test 7: Person name with middle name/initials -> correct matching."""
    # Scenario A: Middle initial
    match_a = match_person_to_email("Robert J. Oppenheimer", "robert.oppenheimer@losalamos.gov")
    assert match_a["matched"] is True
    assert match_a["pattern"] == "first.last"

    match_b = match_person_to_email("Robert J. Oppenheimer", "r.oppenheimer@losalamos.gov")
    assert match_b["matched"] is True
    assert match_b["pattern"] == "f.last"

    # Scenario B: Hyphenated name
    match_c = match_person_to_email("Mary-Jane Watson", "maryjane.watson@dailybugle.com")
    assert match_c["matched"] is True

    # Scenario C: Three names
    match_d = match_person_to_email("George Raymond Richard Martin", "grrmartin@westeros.com")
    assert match_d["matched"] is True


def test_8_email_domain_mismatch():
    """Test 8: Email domain mismatch -> Rejected / filtered from company emails."""
    primary_domain = "acme.com"
    allowed_domains = ["acme.com", "acme-logistics.com"]

    # Match corporate domain
    dom_match_corp = validate_domain_match("john.doe@acme.com", primary_domain, allowed_domains)
    assert dom_match_corp["matched"] is True

    # Match subsidiary
    dom_match_sub = validate_domain_match("john.doe@acme-logistics.com", primary_domain, allowed_domains)
    assert dom_match_sub["matched"] is True

    # Foreign domain mismatch
    dom_mismatch = validate_domain_match("john.doe@externalvendor.com", primary_domain, allowed_domains)
    assert dom_mismatch["matched"] is False

    # Free email filter
    assert is_free_email("john.doe@gmail.com") is True
    assert is_free_email("john.doe@acme.com") is False

    # Generic email filter
    assert is_generic_email("info@acme.com") is True
    assert is_generic_email("contact@acme.com") is True
    assert is_generic_email("john.doe@acme.com") is False


@pytest.mark.asyncio
async def test_9_clean_search_with_zero_emails_produces_not_found():
    """Test 9: Clean search with zero emails -> NOT_FOUND."""
    candidates = [{"name": "Frank Reynolds", "title": "Owner"}]

    mock_search_res = {
        "status": "OK",
        "results": [
            {
                "title": "Frank Reynolds Profile",
                "snippet": "Frank Reynolds is a business magnate with various interests.",
                "url": "https://frankreynolds.com/bio"
            }
        ]
    }

    mock_target_html = "<html><body><h1>Frank Reynolds</h1><p>No contact details listed here.</p></body></html>"

    with patch("app.services.email_discovery_service.search_public_web", new_callable=AsyncMock) as mock_search, \
         patch("app.services.email_discovery_service.crawl_target_page", new_callable=AsyncMock) as mock_crawl:
        
        mock_search.return_value = mock_search_res
        mock_crawl.return_value = mock_target_html

        results = await discover_decision_maker_emails(
            candidates=candidates,
            company_name="Frank's Fluids",
            website="https://franksfluids.com",
            crawled_pages=[]
        )

    assert len(results) == 1
    res = results[0]
    assert res["email_status"] == "NOT_FOUND"
    assert res["emailStatus"] == "NOT_FOUND"
    assert res["email"] is None
    assert "no public email was found" in res["emailReason"]


@pytest.mark.asyncio
async def test_10_generated_pattern_labeled_unverified():
    """Test 10: Generated pattern labeled verification = UNVERIFIED, not exact."""
    candidates = [
        {"name": "Alan Grant", "title": "Paleontologist"},
        {"name": "Ellie Sattler", "title": "Paleobotanist"},
        {"name": "Ian Malcolm", "title": "Mathematician"}
    ]

    crawled_pages = [
        {
            "url": "https://jurassicpark.com/team",
            "html": """
            <div>Alan Grant: alan.grant@jurassicpark.com</div>
            <div>Ellie Sattler: ellie.sattler@jurassicpark.com</div>
            """
        }
    ]

    with patch("app.services.email_discovery_service.search_public_web", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = {"status": "OK", "results": []}

        results = await discover_decision_maker_emails(
            candidates=candidates,
            company_name="InGen",
            website="https://jurassicpark.com",
            crawled_pages=crawled_pages
        )

    malcolm = next(r for r in results if r["name"] == "Ian Malcolm")
    assert malcolm["email_status"] == "PATTERN_GENERATED"
    assert malcolm["email"] == "ian.malcolm@jurassicpark.com"
    # Strict anti-fabrication / verification rules:
    assert malcolm["isExactPublished"] is False
    assert malcolm["mailboxVerification"] == "UNVERIFIED"
    assert malcolm["emailVerificationMethod"] == "PATTERN_INFERENCE"
