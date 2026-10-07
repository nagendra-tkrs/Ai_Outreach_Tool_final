from fastapi import APIRouter, Query
from app.services.import_service import list_companies, delete_company, clear_all_companies

router = APIRouter()


@router.get("")
@router.get("/")
async def get_companies(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1),
    search: str = Query(""),
):
    result = await list_companies(page=page, limit=limit, search=search)
    return {"success": True, "data": result}


@router.get("/{company_id}")
async def get_company_by_id(company_id: str):
    from app.config.database import get_database
    from app.utils.bson_utils import is_valid_object_id, to_object_id, serialize_doc
    from fastapi import HTTPException

    if not is_valid_object_id(company_id):
        raise HTTPException(status_code=400, detail="Invalid company ID")
    db = get_database()
    comp = await db.companies.find_one({"_id": to_object_id(company_id)})
    if not comp:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"success": True, "data": serialize_doc(comp)}


@router.delete("/{company_id}")
async def remove_company(company_id: str):
    res = await delete_company(company_id)
    return {"success": True, "message": res["message"]}


@router.delete("")
@router.delete("/")
async def remove_all_companies():
    res = await clear_all_companies()
    return {"success": True, "message": res["message"], "data": res.get("deletedCounts", {})}
