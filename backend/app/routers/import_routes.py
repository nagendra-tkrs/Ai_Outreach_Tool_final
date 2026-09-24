from datetime import datetime, timezone
from fastapi import APIRouter, File, HTTPException, UploadFile
from app.config.database import get_database
from app.services.excel_service import process_excel
from app.services.import_service import confirm_import, get_batch

router = APIRouter()


@router.post("/excel")
async def upload_excel(file: UploadFile = File(...)):
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    result = await process_excel(content, file.filename)

    db = get_database()
    now = datetime.now(timezone.utc)
    batch_doc = {
        "originalFilename": result["originalFilename"],
        "totalRows": result["summary"]["total"],
        "validRows": result["summary"]["valid"],
        "invalidRows": result["summary"]["invalid"],
        "duplicateRows": result["summary"]["duplicates"],
        "existingInDbRows": result["summary"]["existingInDb"],
        "rows": result["rows"],
        "status": "uploaded",
        "createdAt": now,
        "updatedAt": now,
    }

    insert_result = await db.importbatches.insert_one(batch_doc)
    batch_id = str(insert_result.inserted_id)

    return {
        "success": True,
        "data": {
            "batchId": batch_id,
            "summary": result["summary"],
            "rows": result["rows"],
        },
    }


@router.get("/{batch_id}")
async def get_import_batch(batch_id: str):
    batch = await get_batch(batch_id)
    return {"success": True, "data": batch}


@router.post("/{batch_id}/confirm")
async def confirm_batch_import(batch_id: str):
    result = await confirm_import(batch_id)
    return {
        "success": True,
        "message": "Import completed successfully",
        "data": result,
    }
