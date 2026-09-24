from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

class ImportBatchRow(BaseModel):
    companyName: Optional[str] = ""
    website: Optional[str] = ""
    normalizedWebsite: Optional[str] = ""
    industry: Optional[str] = ""
    country: Optional[str] = ""
    contactName: Optional[str] = ""
    contactEmail: Optional[str] = ""
    revenue: Optional[str] = ""
    employeeCount: Optional[str] = ""
    notes: Optional[str] = ""
    rowNumber: Optional[int] = 0
    status: Optional[str] = "valid"
    validationErrors: Optional[List[str]] = Field(default_factory=list)

class ImportBatch(BaseModel):
    originalFilename: str
    totalRows: int
    validRows: int
    invalidRows: int
    duplicateRows: int
    existingInDbRows: int
    importedRows: Optional[int] = 0
    status: Optional[str] = "uploaded"
    rows: Optional[List[ImportBatchRow]] = Field(default_factory=list)
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
