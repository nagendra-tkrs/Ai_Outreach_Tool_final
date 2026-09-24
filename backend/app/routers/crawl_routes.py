from fastapi import APIRouter, Query
from app.services.crawl_service import (
    get_crawl_status,
    get_crawled_page_content,
    get_crawled_pages,
    start_crawl,
)

router = APIRouter()


@router.post("/companies/{company_id}/crawl")
@router.post("/{company_id}/crawl")
async def trigger_crawl(company_id: str):
    result = await start_crawl(company_id)
    return {"success": True, "data": result}


@router.get("/companies/{company_id}/crawl")
@router.get("/{company_id}/crawl")
async def get_crawl_status_for_company(company_id: str):
    result = await get_crawl_status(company_id)
    return {"success": True, "data": result}


@router.get("/companies/{company_id}/pages")
@router.get("/{company_id}/pages")
async def get_company_pages(
    company_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1),
    status: str = Query(None),
):
    result = await get_crawled_pages(company_id, page, limit, status)
    return {"success": True, "data": result}


@router.get("/companies/{company_id}/pages/{page_id}")
@router.get("/{company_id}/pages/{page_id}")
async def get_page_content(company_id: str, page_id: str):
    result = await get_crawled_page_content(company_id, page_id)
    return {"success": True, "data": result}

