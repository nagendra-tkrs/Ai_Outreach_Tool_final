import math
from datetime import datetime
from fastapi import HTTPException
from app.config.database import get_db
from app.utils.bson_utils import to_object_id, serialize_doc

async def confirm_import(batch_id: str):
    db = get_db()
    oid = to_object_id(batch_id)
    if not oid:
        raise HTTPException(status_code=400, detail="Invalid batch ID")

    batch = await db.importbatches.find_one({"_id": oid})
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")

    if batch.get("status") == "completed":
        raise HTTPException(status_code=409, detail="This import has already been completed")

    if batch.get("status") != "uploaded":
        raise HTTPException(status_code=400, detail="Import batch cannot be confirmed")

    valid_rows = [r for r in batch.get("rows", []) if r.get("status") == "valid"]
    if not valid_rows:
        raise HTTPException(status_code=400, detail="No valid rows to import")

    imported = []
    skipped = []
    now = datetime.utcnow()

    for row in valid_rows:
        existing = await db.companies.find_one({"normalizedWebsite": row["normalizedWebsite"]})
        if existing:
            skipped_row = dict(row)
            skipped_row["skipReason"] = "Already exists in database"
            skipped.append(skipped_row)
            continue

        company_doc = {
            "companyName": row["companyName"],
            "website": row["website"],
            "normalizedWebsite": row["normalizedWebsite"],
            "industry": row.get("industry", ""),
            "country": row.get("country", ""),
            "contactName": row.get("contactName", ""),
            "contactEmail": row.get("contactEmail", ""),
            "revenue": row.get("revenue", ""),
            "employeeCount": row.get("employeeCount", ""),
            "notes": row.get("notes", ""),
            "source": "bulk",
            "importBatchId": oid,
            "crawlStatus": "pending",
            "lastCrawlJobId": None,
            "researchStatus": "pending",
            "lastResearchAt": None,
            "outreachStatus": "none",
            "createdAt": now,
            "updatedAt": now
        }
        res = await db.companies.insert_one(company_doc)
        company_doc["_id"] = res.inserted_id
        imported.append(company_doc)

    await db.importbatches.update_one(
        {"_id": oid},
        {"$set": {
            "importedRows": len(imported),
            "status": "completed",
            "updatedAt": now
        }}
    )

    return {
        "batchId": str(batch["_id"]),
        "imported": len(imported),
        "skipped": len(skipped),
        "total": batch.get("totalRows", 0)
    }

async def get_batch(batch_id: str):
    db = get_db()
    oid = to_object_id(batch_id)
    if not oid:
        raise HTTPException(status_code=400, detail="Invalid batch ID")

    batch = await db.importbatches.find_one({"_id": oid})
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return serialize_doc(batch)

async def list_companies(page: int = 1, limit: int = 50, search: str = ""):
    db = get_db()
    query = {}
    if search:
        regex_pattern = {"$regex": search, "$options": "i"}
        query["$or"] = [
            {"companyName": regex_pattern},
            {"website": regex_pattern},
            {"industry": regex_pattern},
            {"country": regex_pattern}
        ]

    total = await db.companies.count_documents(query)
    skip = (page - 1) * limit
    cursor = db.companies.find(query).sort("createdAt", -1).skip(skip).limit(limit)
    companies = await cursor.to_list(length=limit)

    return {
        "companies": serialize_doc(companies),
        "pagination": {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": math.ceil(total / limit) if limit > 0 else 1
        }
    }

async def delete_company(company_id: str):
    db = get_db()
    cid = to_object_id(company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid company ID")

    company = await db.companies.find_one({"_id": cid})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    await db.companies.delete_one({"_id": cid})
    await db.crawledpages.delete_many({"companyId": cid})
    await db.contacts.delete_many({"companyId": cid})
    await db.companyresearches.delete_many({"companyId": cid})
    await db.researchjobs.delete_many({"companyId": cid})
    await db.outreachrecords.delete_many({"companyId": cid})
    await db.outreachmessages.delete_many({"companyId": cid})

    return {"message": "Company and all associated data deleted successfully"}

async def clear_all_companies():
    db = get_db()
    collections_to_clear = [
        'companies',
        'crawledpages',
        'companyresearches',
        'contacts',
        'importbatches',
        'researchjobs',
        'outreachrecords',
        'outreachmessages'
    ]
    summary = {}
    for col in collections_to_clear:
        res = await db[col].delete_many({})
        summary[col] = res.deleted_count

    return {
        "message": "All companies and associated data cleared successfully",
        "deletedCounts": summary
    }
