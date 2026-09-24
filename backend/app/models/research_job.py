from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel

class ResearchJob(BaseModel):
    companyId: Any
    type: str  # 'website_crawl', 'ai_research', 'competitor_research'
    status: Optional[str] = "queued"  # 'queued', 'running', 'completed', 'failed'
    startedAt: Optional[datetime] = None
    completedAt: Optional[datetime] = None
    pagesDiscovered: Optional[int] = 0
    pagesCrawled: Optional[int] = 0
    pagesFailed: Optional[int] = 0
    pagesBlocked: Optional[int] = 0
    error: Optional[str] = ""
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
