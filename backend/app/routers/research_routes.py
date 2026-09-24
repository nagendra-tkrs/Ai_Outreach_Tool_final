from fastapi import APIRouter, HTTPException
from bson import ObjectId
from app.config.database import get_database
from app.services.research_service import get_company_research, run_company_research
from app.utils.bson_utils import is_valid_object_id, to_object_id

router = APIRouter()


@router.post("/companies/{company_id}/research")
@router.post("/{company_id}/research")
async def trigger_research(company_id: str):
    if not is_valid_object_id(company_id):
        raise HTTPException(status_code=400, detail="Invalid company ID")

    db = get_database()
    company = await db.companies.find_one({"_id": to_object_id(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    research = await run_company_research(company_id)
    return {
        "success": True,
        "message": "AI research generated successfully",
        "data": research,
    }


@router.get("/companies/{company_id}/research")
@router.get("/{company_id}/research")
async def get_research(company_id: str):
    if not is_valid_object_id(company_id):
        raise HTTPException(status_code=400, detail="Invalid company ID")

    db = get_database()
    company = await db.companies.find_one({"_id": to_object_id(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    research = await get_company_research(company_id)
    return {
        "success": True,
        "data": research or None,
        "message": (
            "Company research retrieved successfully"
            if research
            else "No research found for this company. Please run research first."
        ),
    }
