from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

class HeadingItem(BaseModel):
    level: Optional[int] = 0
    text: Optional[str] = ""

class CrawledPage(BaseModel):
    companyId: Any
    url: str
    normalizedUrl: str
    title: Optional[str] = ""
    metaDescription: Optional[str] = ""
    headings: Optional[List[HeadingItem]] = Field(default_factory=list)
    content: Optional[str] = ""
    statusCode: Optional[int] = 0
    contentType: Optional[str] = ""
    depth: Optional[int] = 0
    pageType: Optional[str] = "other"
    wordCount: Optional[int] = 0
    finalUrl: Optional[str] = ""
    contentAvailable: Optional[bool] = False
    contentQuality: Optional[str] = "error"
    crawlStatus: Optional[str] = "pending"
    error: Optional[str] = ""
    errorReason: Optional[str] = ""
    contentLength: Optional[int] = 0
    retryCount: Optional[int] = 0
    isChallengePage: Optional[bool] = False
    crawledAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
