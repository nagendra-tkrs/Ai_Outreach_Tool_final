import pytest
from app.config.database import get_db, connect_db, close_db
from app.services.decision_maker_engine import (
    ROLE_PRIORITY,
    extract_official_candidates,
    extract_table_candidates,
    extract_structured_card_candidates,
    extract_json_ld_candidates,
    extract_image_caption_candidates,
    role_is_historical,
    is_valid_decision_maker,
    is_strict_person_name,
    looks_like_organization_name,
    discover_official_website_decision_makers,
)
from app.services.contact_service import extract_contacts_from_website


# ============================================================
# 1. HTML Table Decision-Maker Extraction
# ============================================================
def test_extract_table_decision_makers():
    table_html = """
    <html>
    <body>
        <h2>Board of Directors</h2>
        <table class="table-leadership">
            <thead>
                <tr>
                    <th>Director Name</th>
                    <th>Designation</th>
                    <th>Email Address</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>Rajesh Mandawewala</td>
                    <td>Managing Director</td>
                    <td>rajesh.m@acme-enterprises.test</td>
                </tr>
                <tr>
                    <td>Balkrishan Goenka</td>
                    <td>Chairman & Managing Director</td>
                    <td>balkrishan.g@acme-enterprises.test</td>
                </tr>
                <tr>
                    <td>Dipali Goenka</td>
                    <td>Whole-Time Director</td>
                    <td>dipali.g@acme-enterprises.test</td>
                </tr>
            </tbody>
        </table>
    </body>
    </html>
    """
    candidates = extract_official_candidates(table_html, "https://acme-enterprises.test/directors", "Acme Enterprises")
    names = [c["name"] for c in candidates]
    assert "Rajesh Mandawewala" in names
    assert "Balkrishan Goenka" in names
    assert "Dipali Goenka" in names

    # Exact emails extracted from table cells
    balkrishan = next(c for c in candidates if c["name"] == "Balkrishan Goenka")
    assert balkrishan.get("exact_email") == "balkrishan.g@acme-enterprises.test"
    assert "Chairman & Managing Director" in balkrishan["role"]


# ============================================================
# 2. Modern Card / Grid Decision-Maker Extraction
# ============================================================
def test_extract_card_grid_decision_makers():
    cards_html = """
    <section class="our-leadership-team">
        <div class="team-card">
            <h3>Sarah Connor</h3>
            <p class="role">Chief Executive Officer</p>
            <p class="bio">Sarah has led technology innovation for over 15 years.</p>
            <a href="mailto:sarah.connor@cyberdyne.test">Contact Sarah</a>
        </div>
        <div class="team-card">
            <h3>Miles Bennett Dyson</h3>
            <p class="role">Chief Technology Officer</p>
            <p class="bio">Miles is the chief architect of our neural network systems.</p>
        </div>
        <div class="team-card">
            <h3>John Connor</h3>
            <p class="role">Chief Strategy Officer</p>
            <p class="bio">John drives strategic market alliances and operations.</p>
        </div>
    </section>
    """
    candidates = extract_official_candidates(cards_html, "https://cyberdyne.test/team", "Cyberdyne Systems")
    names = [c["name"] for c in candidates]
    assert "Sarah Connor" in names
    assert "Miles Bennett Dyson" in names
    assert "John Connor" in names

    sarah = next(c for c in candidates if c["name"] == "Sarah Connor")
    assert sarah["role"] == "Chief Executive Officer"
    assert sarah.get("exact_email") == "sarah.connor@cyberdyne.test"


# ============================================================
# 3. JSON-LD Schema.org Structured Data Extraction
# ============================================================
def test_extract_json_ld_decision_makers():
    json_ld_html = """
    <html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Omni Consumer Products",
            "employee": [
                {
                    "@type": "Person",
                    "name": "Richard Jones",
                    "jobTitle": "Senior Vice President",
                    "email": "dick.jones@ocp.test"
                },
                {
                    "@type": "Person",
                    "name": "Donald Johnson",
                    "jobTitle": "Chief Operating Officer"
                }
            ]
        }
        </script>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Person",
            "name": "Arthur Dent",
            "jobTitle": "President",
            "worksFor": {
                "@type": "Organization",
                "name": "Omni Consumer Products"
            }
        }
        </script>
    </head>
    <body>
        <h1>Omni Consumer Products</h1>
    </body>
    </html>
    """
    candidates = extract_official_candidates(json_ld_html, "https://ocp.test", "Omni Consumer Products")
    names = [c["name"] for c in candidates]
    assert "Richard Jones" in names
    assert "Donald Johnson" in names
    assert "Arthur Dent" in names

    dick = next(c for c in candidates if c["name"] == "Richard Jones")
    assert dick["role"] == "Senior Vice President"
    assert dick.get("exact_email") == "dick.jones@ocp.test"


# ============================================================
# 4. Image Alt and Figcaption Extraction
# ============================================================
def test_extract_image_caption_decision_makers():
    image_html = """
    <div class="team-gallery">
        <figure>
            <img src="/assets/exec1.jpg" alt="Dr. Aris Thorne, Chief Technology Officer" />
            <figcaption>Dr. Aris Thorne, Chief Technology Officer</figcaption>
        </figure>
        <figure>
            <img src="/assets/exec2.jpg" alt="Elena Vance - Managing Director" />
            <figcaption>Elena Vance - Managing Director</figcaption>
        </figure>
    </div>
    """
    candidates = extract_official_candidates(image_html, "https://blackmesa.test/about", "Black Mesa Research")
    names = [c["name"] for c in candidates]
    assert "Aris Thorne" in names
    assert "Elena Vance" in names


# ============================================================
# 5. Distinguish Current vs Historical / Former Roles
# ============================================================
def test_distinguish_historical_vs_current():
    evidence_text = """
    Acme Dynamics executive leadership update:
    Former CEO: Alice Brown stepped down in 2021.
    Current CEO: Bob Green currently leads the organization as Chief Executive Officer.
    David White served as Chief Financial Officer until 2023.
    Clara Oswald serves as the Chief Financial Officer.
    """
    assert role_is_historical(evidence_text, "Alice Brown", "Chief Executive Officer") is True
    assert role_is_historical(evidence_text, "Bob Green", "Chief Executive Officer") is False

    assert role_is_historical(evidence_text, "David White", "Chief Financial Officer") is True
    assert role_is_historical(evidence_text, "Clara Oswald", "Chief Financial Officer") is False


# ============================================================
# 6. Candidate Name Must Literally Appear in Evidence
# ============================================================
def test_candidate_name_literally_in_evidence():
    valid_candidate = {
        "name": "Marcus Vance",
        "role": "Chief Operating Officer",
        "source_url": "https://aperture.test/leadership",
        "evidence": "Marcus Vance serves as the Chief Operating Officer of Aperture Science."
    }
    assert is_valid_decision_maker(valid_candidate, "Aperture Science") is True

    # Candidate name completely missing from evidence
    invalid_candidate = {
        "name": "Marcus Vance",
        "role": "Chief Operating Officer",
        "source_url": "https://aperture.test/leadership",
        "evidence": "The Chief Operating Officer oversees testing operations and safety standards."
    }
    assert is_valid_decision_maker(invalid_candidate, "Aperture Science") is False


# ============================================================
# 7. Strictly NO External Search Engines in Phase 1
# ============================================================
@pytest.mark.asyncio
async def test_no_external_search_in_phase1(monkeypatch):
    search_called = False

    def fake_ddg(*args, **kwargs):
        nonlocal search_called
        search_called = True
        return []

    import app.services.decision_maker_engine as dme
    monkeypatch.setattr(dme, "search_duckduckgo_multi_round", fake_ddg)
    monkeypatch.setattr(dme, "ddg_search", fake_ddg)

    # Crawled page with fewer than 6 candidates (only 2)
    crawled_pages = [{
        "url": "https://solaris.test/leadership",
        "pageType": "leadership",
        "html": "<div><h3>Kelvin Kris</h3><p>Chief Executive Officer</p><h3>Hari Snaut</h3><p>Chief Technology Officer</p></div>"
    }]

    # In Phase 1, target is 6 but search fallback MUST NOT be invoked
    results = await discover_official_website_decision_makers(
        company_name="Solaris Station",
        website="https://solaris.test",
        crawled_pages=crawled_pages,
        max_decision_makers=6
    )
    assert search_called is False
    assert len(results) == 2
    assert {r["name"] for r in results} == {"Kelvin Kris", "Hari Snaut"}


# ============================================================
# 8. Strictly NO Email Pattern Generation in Phase 1
# ============================================================
@pytest.mark.asyncio
async def test_no_pattern_generation_in_phase1():
    # 2 executives on page without any email published
    crawled_pages = [{
        "url": "https://inGen.test/about",
        "pageType": "leadership",
        "html": "<div><h3>John Hammond</h3><p>Founder & CEO</p><h3>Henry Wu</h3><p>Chief Technology Officer</p></div>"
    }]

    results = await discover_official_website_decision_makers(
        company_name="InGen Bioengineering",
        website="https://inGen.test",
        crawled_pages=crawled_pages,
        max_decision_makers=6
    )

    for r in results:
        assert r["email"] is None
        assert r["email_status"] == "NOT_FOUND"
        assert r["email_verification"] == "NONE"
        assert r["pattern_used"] == "none"


# ============================================================
# 9. Target 6 is a Target, Not a Guarantee (No Padding)
# ============================================================
@pytest.mark.asyncio
async def test_target_6_is_target_not_padded():
    crawled_pages = [{
        "url": "https://weyland.test/leaders",
        "pageType": "leadership",
        "html": "<div><h3>Peter Weyland</h3><p>Founder & Chief Executive Officer</p></div>"
    }]

    results = await discover_official_website_decision_makers(
        company_name="Weyland Corp",
        website="https://weyland.test",
        crawled_pages=crawled_pages,
        max_decision_makers=6
    )

    # Exactly 1 real person exists -> returns exactly 1 (never pads to 6)
    assert len(results) == 1
    assert results[0]["name"] == "Peter Weyland"
    assert results[0]["role"] == "Founder & CEO" or "Chief Executive Officer" in results[0]["role"]


# ============================================================
# 10. Reject Organizations, Committees, and Department Names
# ============================================================
def test_reject_organization_and_department_names():
    invalid_entities = [
        "Audit Committee",
        "Nomination Committee",
        "Board of Directors",
        "Executive Leadership Team",
        "Corporate Governance",
        "Customer Support Services",
        "Investor Relations Dept",
        "Acme Global Holdings Ltd",
    ]
    for entity in invalid_entities:
        assert looks_like_organization_name(entity, "Acme Global") is True or is_strict_person_name(entity, "Acme Global") is False


# ============================================================
# 11. Reject Synthetic or Fabricated Placeholder Names
# ============================================================
def test_reject_synthetic_or_fabricated_names():
    synthetic_candidates = [
        {
            "name": "Acme Executive Officer",
            "role": "CEO",
            "source_url": "https://acme.test",
            "evidence": "Acme Executive Officer is verified as CEO"
        },
        {
            "name": "Global Technology Officer",
            "role": "CTO",
            "source_url": "https://global.test",
            "evidence": "Global Technology Officer overseeing engineering"
        },
        {
            "name": "Leadership Management",
            "role": "Director",
            "source_url": "https://acme.test",
            "evidence": "Corporate leadership channel for Acme"
        }
    ]
    for cand in synthetic_candidates:
        assert is_valid_decision_maker(cand, "Acme") is False


# ============================================================
# 12. Phase 1 Diagnostics Returned
# ============================================================
@pytest.mark.asyncio
async def test_phase1_diagnostics_returned():
    diagnostics = {}
    crawled_pages = [
        {
            "url": "https://diagnostics-test.com/about",
            "pageType": "about",
            "html": "<div><h3>Arthur Pendelton</h3><p>Chief Executive Officer</p><p>Audit Committee oversees finance.</p></div>"
        }
    ]

    results = await discover_official_website_decision_makers(
        company_name="Diagnostics Test Corp",
        website="https://diagnostics-test.com",
        crawled_pages=crawled_pages,
        diagnostics=diagnostics
    )

    assert "pages_crawled" in diagnostics
    assert diagnostics["pages_crawled"] >= 1
    assert "candidates_extracted" in diagnostics
    assert "candidates_validated" in diagnostics
    assert diagnostics["candidates_validated"] >= 1
    assert "rejected_reasons" in diagnostics
    assert "execution_time_ms" in diagnostics
    assert isinstance(diagnostics["execution_time_ms"], int)
    assert diagnostics["execution_time_ms"] >= 0


# ============================================================
# 13. End-to-End Crawl to Decision-Maker Discovery Pipeline
# ============================================================
@pytest.mark.asyncio
async def test_end_to_end_official_crawl_pipeline():
    await connect_db()
    db = get_db()
    assert db is not None

    # Clean up any leftover test records before inserting
    await db.companies.delete_many({"normalizedWebsite": "vandelay.test"})
    await db.crawledpages.delete_many({"normalizedUrl": {"$regex": "vandelay.test"}})
    await db.contacts.delete_many({"companyId": {"$exists": True}, "name": {"$in": ["George Costanza", "Art Vandelay", "Cosmo Kramer"]}})

    comp_res = await db.companies.insert_one({
        "companyName": "Vandelay Industries",
        "website": "https://vandelay.test",
        "normalizedWebsite": "vandelay.test",
        "industry": "Manufacturing",
        "status": "crawled"
    })
    cid = str(comp_res.inserted_id)

    # Multi-page crawled mock data
    await db.crawledpages.insert_many([
        {
            "companyId": comp_res.inserted_id,
            "url": "https://vandelay.test/team",
            "normalizedUrl": "vandelay.test/team",
            "pageType": "team",
            "crawlStatus": "completed",
            "html": """
            <div class="team-grid">
                <div class="team-card">
                    <h3>George Costanza</h3>
                    <p class="role">Chief Executive Officer</p>
                    <a href="mailto:george.costanza@vandelay.test">Email</a>
                </div>
                <div class="team-card">
                    <h3>Art Vandelay</h3>
                    <p class="role">Chief Technology Officer</p>
                </div>
            </div>
            """,
            "wordCount": 120
        },
        {
            "companyId": comp_res.inserted_id,
            "url": "https://vandelay.test/board",
            "normalizedUrl": "vandelay.test/board",
            "pageType": "board",
            "crawlStatus": "completed",
            "html": """
            <table>
                <tr><th>Director</th><th>Designation</th></tr>
                <tr><td>Cosmo Kramer</td><td>Whole-Time Director</td></tr>
            </table>
            """,
            "wordCount": 80
        }
    ])

    contacts, diagnostics = await extract_contacts_from_website(cid, return_diagnostics=True)
    assert len(contacts) >= 3

    names = {c["name"] for c in contacts}
    assert "George Costanza" in names
    assert "Art Vandelay" in names
    assert "Cosmo Kramer" in names

    # George Costanza has exact email from mailto
    george = next(c for c in contacts if c["name"] == "George Costanza")
    assert george["email"] == "george.costanza@vandelay.test"
    assert george["emailStatus"] == "EXACT_FOUND"
    assert george["isExactPublished"] is True

    # Art Vandelay has no published email -> None / NOT_FOUND
    art = next(c for c in contacts if c["name"] == "Art Vandelay")
    assert art["email"] is None
    assert art["emailStatus"] == "NOT_FOUND"

    # Verify primary decision maker is selected
    top_contact = next(c for c in contacts if c.get("isPrimaryDecisionMaker"))
    assert top_contact["name"] == "George Costanza"

    # Verify diagnostics returned and populated
    assert diagnostics["pages_crawled"] >= 2
    assert diagnostics["candidates_validated"] >= 3

    # Cleanup database records
    await db.companies.delete_one({"_id": comp_res.inserted_id})
    await db.crawledpages.delete_many({"companyId": comp_res.inserted_id})
    await db.contacts.delete_many({"companyId": comp_res.inserted_id})
    await db.companyresearches.delete_many({"companyId": comp_res.inserted_id})
