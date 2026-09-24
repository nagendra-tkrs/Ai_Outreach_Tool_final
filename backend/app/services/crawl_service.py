import math
from fastapi import HTTPException
from app.config.database import get_db
from app.utils.bson_utils import to_object_id, serialize_doc
from app.crawler.orchestrator import crawl_company

async def start_crawl(company_id: str):
    result = await crawl_company(company_id)
    try:
        from app.services.contact_service import extract_contacts_from_website
        contacts = await extract_contacts_from_website(company_id, enable_phase2=True)
        result["contactsFound"] = len(contacts) if isinstance(contacts, list) else 0
    except Exception as e:
        print(f"[CRAWLER] Auto decision-maker extraction error for company {company_id}: {e}")
    return result

async def get_crawl_status(company_id: str):
    db = get_db()
    cid = to_object_id(company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid company ID")

    company = await db.companies.find_one({"_id": cid})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    latest_job = await db.researchjobs.find_one(
        {"companyId": cid, "type": "website_crawl"},
        sort=[("createdAt", -1)]
    )

    return {
        "crawlStatus": company.get("crawlStatus", "pending"),
        "job": serialize_doc(latest_job)
    }

async def get_crawled_pages(company_id: str, page: int = 1, limit: int = 50, status: str = None):
    db = get_db()
    cid = to_object_id(company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid company ID")

    company = await db.companies.find_one({"_id": cid})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    query = {"companyId": cid}
    if status:
        query["crawlStatus"] = status

    total = await db.crawledpages.count_documents(query)
    skip = (page - 1) * limit
    cursor = db.crawledpages.find(query).sort([
        ("depth", 1),
        ("crawlStatus", 1),
        ("pageType", 1)
    ]).skip(skip).limit(limit)

    pages = await cursor.to_list(length=limit)

    return {
        "pages": serialize_doc(pages),
        "pagination": {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": math.ceil(total / limit) if limit > 0 else 1
        }
    }

async def get_crawled_page_content(company_id: str, page_id: str):
    db = get_db()
    cid = to_object_id(company_id)
    pid = to_object_id(page_id)
    if not cid or not pid:
        raise HTTPException(status_code=400, detail="Invalid ID")

    page = await db.crawledpages.find_one({"_id": pid, "companyId": cid})
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return serialize_doc(page)
