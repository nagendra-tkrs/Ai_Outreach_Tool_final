from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"success": True, "message": "AI Client Outreach API is running"}
