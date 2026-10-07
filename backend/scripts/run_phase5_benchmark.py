import asyncio
import os
import sys
import json
import logging
import traceback
from datetime import datetime, timezone
from urllib.parse import urlparse

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config.database import connect_db, get_db, close_db
from app.services.contact_service import extract_contacts_from_website, check_domain_mx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("phase5_benchmark")

BENCHMARK_COMPANIES = [
    {
        "name": "Acme United Corporation",
        "website": "https://acmeunited.com",
        "industry": "Consumer Goods / Manufacturing",
        "evidence": "Acme United Corporation is a leading worldwide supplier of innovative cutting, measuring and safety products.",
        "recommended_service": "AI & Automation Workshops"
    },
    {
        "name": "Hub Group",
        "website": "https://hubgroup.com",
        "industry": "Logistics & Supply Chain",
        "evidence": "Hub Group delivers end-to-end supply chain solutions including intermodal, dedicated, and brokerage.",
        "recommended_service": "AI Data Strategy"
    },
    {
        "name": "ArcBest",
        "website": "https://arcb.com",
        "industry": "Freight & Logistics",
        "evidence": "ArcBest provides freight transportation and integrated logistics services across North America.",
        "recommended_service": "AI Strategy Consulting"
    },
    {
        "name": "US Foods",
        "website": "https://usfoods.com",
        "industry": "Food Distribution",
        "evidence": "US Foods distributes food and supplies to independent restaurants and healthcare facilities.",
        "recommended_service": "AI Readiness and Opportunity Assessments"
    },
    {
        "name": "Sysco Corporation",
        "website": "https://sysco.com",
        "industry": "Food Distribution",
        "evidence": "Sysco distributes fresh food products and equipment to foodservice operations worldwide.",
        "recommended_service": "AI Data Strategy"
    },
    {
        "name": "Cal-Maine Foods",
        "website": "https://calmainefoods.com",
        "industry": "Agriculture / Food Production",
        "evidence": "Cal-Maine Foods produces, grades, packages, and markets fresh shell eggs.",
        "recommended_service": "AI & Automation Workshops"
    },
    {
        "name": "Steelcase",
        "website": "https://steelcase.com",
        "industry": "Furniture & Manufacturing",
        "evidence": "Steelcase designs and manufactures architecture, furniture and technology products for workplaces.",
        "recommended_service": "AI Strategy Consulting"
    },
    {
        "name": "MillerKnoll",
        "website": "https://millerknoll.com",
        "industry": "Furniture & Design",
        "evidence": "MillerKnoll manufactures modern furniture designs for residential and commercial environments.",
        "recommended_service": "AI Readiness and Opportunity Assessments"
    },
    {
        "name": "Fastenal Company",
        "website": "https://fastenal.com",
        "industry": "Industrial Distribution",
        "evidence": "Fastenal is a wholesale distributor of industrial and construction supplies through branch and vending networks.",
        "recommended_service": "AI Data Strategy"
    },
    {
        "name": "W.W. Grainger",
        "website": "https://grainger.com",
        "industry": "Industrial Supply",
        "evidence": "Grainger distributes motors, lighting, material handling, fasteners, and maintenance supplies.",
        "recommended_service": "AI Strategy Consulting"
    },
    {
        "name": "Ferguson Enterprises",
        "website": "https://ferguson.com",
        "industry": "Plumbing & HVAC Distribution",
        "evidence": "Ferguson distributes plumbing fixtures, pipes, valves, fittings, and HVAC equipment.",
        "recommended_service": "AI & Automation Workshops"
    },
    {
        "name": "Watsco",
        "website": "https://watsco.com",
        "industry": "HVAC Distribution",
        "evidence": "Watsco distributes air conditioning, heating, and refrigeration equipment and related parts.",
        "recommended_service": "AI Readiness and Opportunity Assessments"
    },
    {
        "name": "Owens Corning",
        "website": "https://owenscorning.com",
        "industry": "Building Materials",
        "evidence": "Owens Corning develops and produces insulation, roofing, and fiberglass composite materials.",
        "recommended_service": "AI Data Strategy"
    },
    {
        "name": "Vulcan Materials",
        "website": "https://vulcanmaterials.com",
        "industry": "Construction Aggregates",
        "evidence": "Vulcan Materials produces construction aggregates including crushed stone, sand, gravel, and asphalt.",
        "recommended_service": "AI Strategy Consulting"
    },
    {
        "name": "Martin Marietta Materials",
        "website": "https://martinmarietta.com",
        "industry": "Building Materials",
        "evidence": "Martin Marietta supplies aggregates and heavy building materials for infrastructure and residential construction.",
        "recommended_service": "AI & Automation Workshops"
    },
    {
        "name": "Lennox International",
        "website": "https://lennoxinternational.com",
        "industry": "HVAC & Climate Control",
        "evidence": "Lennox International designs climate control products for heating, ventilation, and air conditioning.",
        "recommended_service": "AI Readiness and Opportunity Assessments"
    },
    {
        "name": "The Toro Company",
        "website": "https://thetorocompany.com",
        "industry": "Machinery & Equipment",
        "evidence": "The Toro Company designs and manufactures turf maintenance equipment, irrigation systems, and lighting solutions.",
        "recommended_service": "AI Data Strategy"
    },
    {
        "name": "Donaldson Company",
        "website": "https://donaldson.com",
        "industry": "Industrial Filtration",
        "evidence": "Donaldson manufactures filtration systems and replacement parts for engines and industrial equipment.",
        "recommended_service": "AI Strategy Consulting"
    },
    {
        "name": "Snap-on Incorporated",
        "website": "https://snapon.com",
        "industry": "Tools & Equipment",
        "evidence": "Snap-on manufactures high-end tools, diagnostics, and shop equipment for professional technicians.",
        "recommended_service": "AI & Automation Workshops"
    },
    {
        "name": "Dover Corporation",
        "website": "https://dovercorporation.com",
        "industry": "Diversified Manufacturing",
        "evidence": "Dover delivers innovative equipment, components, and specialty systems for industrial markets.",
        "recommended_service": "AI Readiness and Opportunity Assessments"
    },
    {
        "name": "Packaging Corporation of America",
        "website": "https://packagingcorp.com",
        "industry": "Packaging & Containers",
        "evidence": "Packaging Corporation of America produces containerboard and corrugated packaging products.",
        "recommended_service": "AI Data Strategy"
    },
    {
        "name": "Silgan Holdings",
        "website": "https://silganholdings.com",
        "industry": "Rigid Packaging",
        "evidence": "Silgan Holdings manufactures rigid packaging including metal containers, closures, and plastic containers.",
        "recommended_service": "AI Strategy Consulting"
    },
    {
        "name": "Sonoco Products Company",
        "website": "https://sonoco.com",
        "industry": "Packaging",
        "evidence": "Sonoco manufactures consumer packaging, industrial products, and protective packaging solutions.",
        "recommended_service": "AI & Automation Workshops"
    },
    {
        "name": "Graphic Packaging Holding",
        "website": "https://graphicpkg.com",
        "industry": "Paper Packaging",
        "evidence": "Graphic Packaging designs sustainable fiber-based packaging solutions for food, beverage, and consumer goods.",
        "recommended_service": "AI Readiness and Opportunity Assessments"
    },
    {
        "name": "AptarGroup",
        "website": "https://aptar.com",
        "industry": "Dispensing Packaging",
        "evidence": "AptarGroup provides drug delivery, consumer dispensing, and active material science solutions.",
        "recommended_service": "AI Data Strategy"
    },
    {
        "name": "Brady Corporation",
        "website": "https://bradycorp.com",
        "industry": "Identification & Safety",
        "evidence": "Brady manufactures identification solutions, safety signs, labels, printers, and precision materials.",
        "recommended_service": "AI Strategy Consulting"
    },
    {
        "name": "H.B. Fuller Company",
        "website": "https://hbfuller.com",
        "industry": "Specialty Chemicals / Adhesives",
        "evidence": "H.B. Fuller manufactures industrial adhesives, sealants, and specialty chemical products globally.",
        "recommended_service": "AI & Automation Workshops"
    },
    {
        "name": "Carlisle Companies",
        "website": "https://carlisle.com",
        "industry": "Building Products",
        "evidence": "Carlisle designs and manufactures energy-efficient building envelope products and commercial roofing.",
        "recommended_service": "AI Readiness and Opportunity Assessments"
    },
    {
        "name": "Werner Enterprises",
        "website": "https://werner.com",
        "industry": "Transportation & Logistics",
        "evidence": "Werner Enterprises is a premier transportation and logistics carrier operating across North America.",
        "recommended_service": "AI Data Strategy"
    },
    {
        "name": "C.H. Robinson",
        "website": "https://chrobinson.com",
        "industry": "Logistics & Freight Brokerage",
        "evidence": "C.H. Robinson provides freight transportation services and logistics solutions globally.",
        "recommended_service": "AI Strategy Consulting"
    }
]

async def run_benchmark():
    await connect_db()
    db = get_db()

    results = []
    logger.info(f"Starting Phase 5 Real-World Email Discovery Benchmark on {len(BENCHMARK_COMPANIES)} companies...")

    for idx, comp in enumerate(BENCHMARK_COMPANIES, 1):
        c_name = comp["name"]
        c_web = comp["website"]
        logger.info(f"[{idx}/30] Processing: {c_name} ({c_web})")

        # 1. Upsert company in MongoDB
        norm_web = c_web.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0].lower()
        company_doc = await db.companies.find_one({"$or": [{"website": c_web}, {"normalizedWebsite": norm_web}]})
        
        now = datetime.now(timezone.utc)
        if not company_doc:
            comp_to_insert = {
                "companyName": c_name,
                "website": c_web,
                "normalizedWebsite": norm_web,
                "industry": comp["industry"],
                "evidence": comp["evidence"],
                "recommendedService": comp["recommended_service"],
                "source": "phase5_benchmark",
                "createdAt": now,
                "updatedAt": now
            }
            ins = await db.companies.insert_one(comp_to_insert)
            company_id = str(ins.inserted_id)
        else:
            company_id = str(company_doc["_id"])
            await db.companies.update_one(
                {"_id": company_doc["_id"]},
                {"$set": {
                    "evidence": comp["evidence"],
                    "recommendedService": comp["recommended_service"],
                    "updatedAt": now
                }}
            )

        # 2. Check MX status
        mx_info = await check_domain_mx(norm_web)
        mx_status = mx_info.get("mxStatus", "UNKNOWN")

        # 3. Run extract_contacts_from_website
        try:
            contacts, diagnostics = await extract_contacts_from_website(company_id, return_diagnostics=True, enable_phase2=True)
        except Exception as e:
            logger.error(f"Error extracting contacts for {c_name}: {e}")
            contacts = []

        # 4. Pick best decision maker
        decision_makers = [c for c in contacts if c.get("roleCategory") != "general" and c.get("seniority") != "general"]
        selected = next((c for c in decision_makers if c.get("isPrimaryDecisionMaker")), None) or (decision_makers[0] if decision_makers else (contacts[0] if contacts else None))

        if selected:
            dm_name = selected.get("name") or "Executive Team"
            designation = selected.get("title") or selected.get("designation") or "Executive"
            email = selected.get("email")
            email_status = selected.get("emailStatus") or selected.get("email_status") or "NOT_FOUND"
            email_type = selected.get("mailboxVerification") or ("EXACT" if email_status == "EXACT_FOUND" else ("DERIVED" if "PATTERN" in email_status else "NONE"))
            confidence = selected.get("confidenceScore", 0)
            source = selected.get("source") or "Official Website"
            source_url = selected.get("sourceUrl") or selected.get("email_source_url") or c_web
            evidence = selected.get("evidence", {}).get("personEvidence") if isinstance(selected.get("evidence"), dict) else str(selected.get("evidence") or "")
            if not evidence:
                evidence = selected.get("email_evidence") or f"Identified as leadership for {c_name}"
            email_reason = selected.get("emailReason") or selected.get("email_reason") or "Discovery completed"
            pattern = selected.get("generatedPattern") or selected.get("generated_pattern") or "none"
            pattern_conf = selected.get("patternConfidence") or selected.get("pattern_confidence") or "none"
        else:
            # Fallback if no person was discovered on the site
            dm_name = "Chief Executive Officer / Managing Director"
            designation = "Chief Executive Officer"
            email = None
            email_status = "NOT_FOUND"
            email_type = "NONE"
            confidence = 0
            source = "Official Website"
            source_url = c_web
            evidence = f"Checked official website {c_web} and search; no leadership profiles extracted"
            email_reason = "No usable public email was discovered from the sources searched"
            pattern = "none"
            pattern_conf = "none"

        # Record item
        item = {
            "Company": c_name,
            "Website": c_web,
            "Decision Maker": dm_name,
            "Designation": designation,
            "Email": email,
            "Email Status": email_status,
            "Email Type": email_type,
            "Confidence": confidence,
            "Source": source,
            "Source URL": source_url,
            "Evidence": str(evidence)[:300],
            "Email Reason": email_reason,
            "Pattern": pattern,
            "Pattern Confidence": pattern_conf,
            "MX Status": mx_status
        }
        results.append(item)
        logger.info(f"Result [{c_name}]: DM='{dm_name}' Status='{email_status}' Email='{email}' Reason='{email_reason}'")

        # Friendly pause to respect public search rate limits
        await asyncio.sleep(1.0)

    # Save benchmark results
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "phase5_benchmark_results.json"))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    logger.info(f"Phase 5 benchmark completed. Results written to {out_path}")

    # Compute Statistics
    counts = {
        "EXACT_FOUND": sum(1 for r in results if r["Email Status"] == "EXACT_FOUND"),
        "PATTERN_GENERATED": sum(1 for r in results if r["Email Status"] == "PATTERN_GENERATED"),
        "PATTERN_INFERRED": sum(1 for r in results if r["Email Status"] == "PATTERN_INFERRED"),
        "NOT_FOUND": sum(1 for r in results if r["Email Status"] == "NOT_FOUND"),
        "SEARCH_TIMEOUT": sum(1 for r in results if r["Email Status"] == "SEARCH_TIMEOUT"),
        "SEARCH_UNAVAILABLE": sum(1 for r in results if r["Email Status"] == "SEARCH_UNAVAILABLE"),
        "DOMAIN_BLOCKED": sum(1 for r in results if r["Email Status"] == "DOMAIN_BLOCKED"),
        "NEEDS_REVIEW": sum(1 for r in results if r["Email Status"] == "NEEDS_REVIEW"),
    }

    total = len(results)
    public_disc_rate = (counts["EXACT_FOUND"] / total) * 100
    pattern_disc_rate = ((counts["PATTERN_GENERATED"] + counts["PATTERN_INFERRED"]) / total) * 100
    search_failure_rate = ((counts["SEARCH_TIMEOUT"] + counts["SEARCH_UNAVAILABLE"]) / total) * 100
    clean_not_found_rate = (counts["NOT_FOUND"] / total) * 100

    print("\n" + "="*60)
    print("PHASE 5 BENCHMARK EXECUTION SUMMARY")
    print("="*60)
    print(f"Total companies = {total}")
    for k, v in counts.items():
        print(f"{k} = {v}")
    print(f"Public email discovery rate: {public_disc_rate:.1f}%")
    print(f"Pattern-based discovery rate: {pattern_disc_rate:.1f}%")
    print(f"Search failure rate: {search_failure_rate:.1f}%")
    print(f"Clean NOT_FOUND rate: {clean_not_found_rate:.1f}%")
    print("="*60 + "\n")

    await close_db()

if __name__ == "__main__":
    asyncio.run(run_benchmark())
