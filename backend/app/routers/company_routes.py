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


@router.delete("/{company_id}")
async def remove_company(company_id: str):
    res = await delete_company(company_id)
    return {"success": True, "message": res["message"]}


@router.delete("")
@router.delete("/")
async def remove_all_companies():
    res = await clear_all_companies()
    return {"success": True, "message": res["message"], "data": res.get("deletedCounts", {})}
