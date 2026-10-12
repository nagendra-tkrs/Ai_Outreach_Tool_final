import os
from datetime import datetime, timezone
from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from app.config.database import get_database
from app.services.excel_service import (
    process_excel,
    build_import_template,
    build_invalid_rows_report,
    SUPPORTED_EXTENSIONS,
    MAX_FILE_SIZE,
)
from app.services.import_service import confirm_import, get_batch

router = APIRouter()

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/template")
async def download_import_template():
    """Download TKSR_Import_Template.xlsx with all headers + 3 sample rows."""
    data = build_import_template()
    return Response(
        content=data,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="TKSR_Import_Template.xlsx"'},
    )


@router.post("/excel")
async def upload_excel(file: UploadFile = File(...)):
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        display = ext if ext else "(no extension)"
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{display}'. Please upload a .xlsx, .xls, or .csv file.",
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large ({len(content) / (1024 * 1024):.1f} MB). Maximum size is 10 MB.",
        )

    try:
        result = await process_excel(content, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

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


@router.get("/{batch_id}/invalid-report")
async def download_invalid_report(batch_id: str):
    """Download invalid_rows.xlsx for this batch (must be defined after /template)."""
    batch = await get_batch(batch_id)
    rows = batch.get("rows") or []
    data = build_invalid_rows_report(rows)
    return Response(
        content=data,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="invalid_rows.xlsx"'},
    )


@router.post("/{batch_id}/confirm")
async def confirm_batch_import(batch_id: str):
    result = await confirm_import(batch_id)
    return {
        "success": True,
        "message": "Import completed successfully",
        "data": result,
    }