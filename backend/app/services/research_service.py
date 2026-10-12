import os
import asyncio
from datetime import datetime, timezone
from fastapi import HTTPException
from app.config.database import get_db
from app.utils.bson_utils import to_object_id, serialize_doc
from app.services.ai_service import (
    get_ai_config,
    call_ai,
    generate_fallback_research
)
from app.services.web_search_service import fetch_company_public_overview

def env_int(name: str, fallback: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == '':
        return fallback
    try:
        n = int(raw)
        return n if n > 0 else fallback
    except ValueError:
        return fallback

async def run_company_research(company_id: str):
    db = get_db()
    cid = to_object_id(company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid company ID")

    company = await db.companies.find_one({"_id": cid})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    now = datetime.now(timezone.utc)
    await db.companies.update_one({"_id": cid}, {"$set": {"researchStatus": "researching", "updatedAt": now}})

    research_timeout_ms = env_int('RESEARCH_TIMEOUT_MS', 600000)
    research_timeout_sec = research_timeout_ms / 1000.0

    try:
        return await asyncio.wait_for(do_company_research(company), timeout=research_timeout_sec)
    except asyncio.TimeoutError:
        print(f"[RESEARCH] Research job timed out after {research_timeout_ms}ms for {company.get('companyName')}")
        await db.companies.update_one({"_id": cid}, {"$set": {"researchStatus": "failed", "updatedAt": datetime.now(timezone.utc)}})
        raise HTTPException(status_code=504, detail=f"Research job timed out after {research_timeout_ms}ms")
    except Exception as e:
        print(f"[RESEARCH] Research failed for {company.get('companyName')}: {e}")
        await db.companies.update_one({"_id": cid}, {"$set": {"researchStatus": "failed", "updatedAt": datetime.now(timezone.utc)}})
        raise e

async def do_company_research(company: dict):
    db = get_db()
    cid = company["_id"]

    cursor = db.crawledpages.find({
        "companyId": cid,
        "crawlStatus": "completed",
        "contentAvailable": True,
        "wordCount": {"$gte": 15}
    }).sort([("depth", 1), ("wordCount", -1)]).limit(3)
    pages = await cursor.to_list(length=3)

    research_source = 'website_crawl'
    research_method = 'WEBSITE_CRAWLED'
    fallback_used = False
    block_reason = ''
    evidence_items = []
    sources_used = []
    research_data = None
    ai_config = await get_ai_config()

    if pages:
        research_source = 'website_crawl'
        research_method = 'WEBSITE_CRAWLED'
        fallback_used = False
        sources_used = [{
            'url': p.get('url', ''),
            'title': p.get('title') or p.get('url', ''),
            'pageType': p.get('pageType') or 'website_page'
        } for p in pages]

        page_summaries = [{
            'url': p.get('url', ''),
            'pageType': p.get('pageType', ''),
            'title': p.get('title', ''),
            'headings': [h.get('text', '') for h in p.get('headings', [])][:8],
            'contentSnippet': (p.get('content') or '')[:600]
        } for p in pages]

        system_prompt = "You are a world-class B2B sales intelligence analyst. You analyze company websites and synthesize accurate, insightful sales intelligence and actionable outreach triggers. You always respond in valid JSON format matching the requested schema."
        import json
        user_prompt = f"""Analyze the following website data for the company "{company.get('companyName')}" ({company.get('website')}):

Industry tag: {company.get('industry') or 'Unknown'}
Country: {company.get('country') or 'Unknown'}

Crawled Website Pages ({len(page_summaries)} pages):
{json.dumps(page_summaries, indent=2)}

Produce a comprehensive JSON report with the following exact keys:
{{
  "summary": "2-3 sentences explaining what this company does, its market, and main business",
  "valueProposition": "Their core value proposition to their customers",
  "coreOfferings": ["List of 3 to 5 core products, services, or solutions they sell"],
  "targetAudience": "Who their primary ideal buyers or clients are",
  "detectedPainPoints": [
    {{ "title": "Pain point title", "description": "Specific business or technical challenge this company likely faces" }},
    {{ "title": "Pain point title 2", "description": "Another specific challenge" }},
    {{ "title": "Pain point title 3", "description": "Another specific challenge" }}
  ],
  "techStack": ["List of modern tools, cloud, technologies, or frameworks identified from their site"],
  "competitors": ["2 to 4 potential competitors or peer companies in their industry"],
  "icebreakers": [
    "Compelling opening hook 1 based on their specific product/blog/recent announcement",
    "Compelling opening hook 2 based on their company mission or unique feature",
    "Compelling opening hook 3 based on their industry positioning"
  ],
  "icpFitScore": 85,
  "icpFitReasoning": "Why this company is a high/medium fit for B2B outreach solutions",
  "keyPersonnel": [
    {{ "name": "Discovered leader/founder/contact name if mentioned", "title": "Their title" }}
  ]
}}"""

        try:
            if ai_config.get('provider') == 'ollama':
                research_data = await call_ai(user_prompt, system_prompt, ai_config)
            else:
                research_data = generate_fallback_research(company, pages)
        except Exception as e:
            print(f"AI research call failed, falling back to smart heuristic: {e}")
            research_data = generate_fallback_research(company, pages)
    else:
        blocked_count = await db.crawledpages.count_documents({
            "companyId": cid,
            "crawlStatus": {"$in": ['blocked', 'rate_limited', 'robots_disallowed']}
        })
        is_blocked = blocked_count > 0 or company.get("crawlStatus") == "blocked"
        block_reason = 'Official website access was blocked by CDN/Access Controls.' if is_blocked else 'No direct website pages were accessible.'

        public_overview = None
        try:
            public_overview = await fetch_company_public_overview(
                company.get('companyName'),
                company.get('normalizedWebsite') or company.get('website'),
                company.get('industry', ''),
                company.get('country', '')
            )
        except Exception as e:
            print(f"[RESEARCH] Fallback public-source lookup failed: {e}")

        evidence_items = public_overview.get('evidenceItems', []) if public_overview else []

        if evidence_items:
            research_source = 'public_sources'
            research_method = 'WEBSITE_BLOCKED_FALLBACK_USED'
            fallback_used = True
            sources_used = [{
                'url': e['sourceUrl'],
                'title': e['sourceTitle'],
                'pageType': e['sourceType']
            } for e in evidence_items]

            evidence_text = "\n\n".join([
                f"[Source {idx+1}] Title: {e['sourceTitle']} ({e['sourceUrl']})\nType: {e['sourceType']}\nEvidence: {e['evidenceText']}"
                for idx, e in enumerate(evidence_items)
            ])

            system_prompt = "You are a precision B2B intelligence analyst. The target company's official website was blocked by CDN/access controls, so you must synthesize your analysis STRICTLY from the verified public search results and corporate records provided below. Never hallucinate information not supported by the evidence. Respond in valid JSON matching the requested schema."
            user_prompt = f"""Target Company: "{company.get('companyName')}" ({company.get('website')})
Industry: {company.get('industry') or 'Unknown'}
Country: {company.get('country') or 'Unknown'}
Research Mode: Fallback Public-Source Analysis

Verified Public Sources & Corporate Records ({len(evidence_items)} sources):
{evidence_text}

Synthesize a comprehensive JSON report with the following exact keys:
{{
  "summary": "2-3 sentences explaining what this company does based on verified public records",
  "valueProposition": "Their core value proposition to their customers",
  "coreOfferings": ["List of 3 to 5 core products, services, or solutions they sell"],
  "targetAudience": "Who their primary ideal buyers or clients are",
  "detectedPainPoints": [
    {{ "title": "Pain point title", "description": "Specific business or technical challenge this company likely faces" }},
    {{ "title": "Pain point title 2", "description": "Another specific challenge" }},
    {{ "title": "Pain point title 3", "description": "Another specific challenge" }}
  ],
  "techStack": ["Modern tools, cloud, technologies, or frameworks mentioned in public records"],
  "competitors": ["2 to 4 potential competitors or peer companies in their industry"],
  "icebreakers": [
    "Compelling opening hook 1 based on recent corporate initiatives or announcements",
    "Compelling opening hook 2 based on their market positioning",
    "Compelling opening hook 3 based on industry trends"
  ],
  "icpFitScore": 88,
  "icpFitReasoning": "Why this company is a high/medium fit for enterprise AI & automation solutions",
  "keyPersonnel": [
    {{ "name": "Discovered executive name from public records", "title": "Their title" }}
  ]
}}"""
            try:
                if ai_config.get('provider') == 'ollama':
                    research_data = await call_ai(user_prompt, system_prompt, ai_config)
                else:
                    research_data = generate_fallback_research(company, [])

                if public_overview and public_overview.get('keyPersonnel'):
                    curr_people = [(p.get('name') or '').lower() for p in (research_data.get('keyPersonnel') or [])]
                    for kp in public_overview['keyPersonnel']:
                        if kp.get('name', '').lower() not in curr_people:
                            if not research_data.get('keyPersonnel'):
                                research_data['keyPersonnel'] = []
                            research_data['keyPersonnel'].append(kp)
            except Exception as e:
                print(f"AI fallback research call failed: {e}")
                research_data = generate_fallback_research(company, [])
        else:
            research_source = 'system_guard'
            research_method = 'WEBSITE_BLOCKED_NO_FALLBACK' if is_blocked else 'CRAWL_FAILED'
            fallback_used = False
            sources_used = []
            research_data = generate_fallback_research(company, [])
            research_data['summary'] = f"{company.get('companyName')} ({company.get('industry') or 'B2B Enterprise'}). {block_reason} Intelligence synthesized from industry baseline profile."

    now = datetime.now(timezone.utc)
    research_doc = {
        'companyId': cid,
        'summary': research_data.get('summary', ''),
        'valueProposition': research_data.get('valueProposition', ''),
        'coreOfferings': research_data.get('coreOfferings', []),
        'targetAudience': research_data.get('targetAudience', ''),
        'detectedPainPoints': research_data.get('detectedPainPoints', []),
        'techStack': research_data.get('techStack', []),
        'competitors': research_data.get('competitors', []),
        'icebreakers': research_data.get('icebreakers', []),
        'icpFitScore': research_data.get('icpFitScore', 80) if isinstance(research_data.get('icpFitScore'), (int, float)) else 80,
        'icpFitReasoning': research_data.get('icpFitReasoning', ''),
        'keyPersonnel': research_data.get('keyPersonnel', []),
        'sourcesUsed': sources_used,
        'researchSource': research_source,
        'researchMethod': research_method,
        'fallbackUsed': fallback_used,
        'blockReason': block_reason,
        'evidenceItems': evidence_items,
        'aiProvider': ai_config.get('provider'),
        'aiModel': ai_config.get('model'),
        'researchedAt': now,
        'updatedAt': now
    }

    await db.companyresearches.update_one(
        {"companyId": cid},
        {"$set": research_doc, "$setOnInsert": {"createdAt": now}},
        upsert=True
    )

    await db.companies.update_one(
        {"_id": cid},
        {"$set": {"researchStatus": "completed", "lastResearchAt": now, "updatedAt": now}}
    )

    saved = await db.companyresearches.find_one({"companyId": cid})
    return serialize_doc(saved)

async def get_company_research(company_id: str):
    db = get_db()
    cid = to_object_id(company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid company ID")
    res = await db.companyresearches.find_one({"companyId": cid})
    return serialize_doc(res)
