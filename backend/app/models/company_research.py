from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, Field

class PainPoint(BaseModel):
    title: Optional[str] = ""
    description: Optional[str] = ""

class KeyPersonnel(BaseModel):
    name: Optional[str] = ""
    title: Optional[str] = ""

class SourceUsed(BaseModel):
    url: Optional[str] = ""
    title: Optional[str] = ""
    pageType: Optional[str] = ""

class EvidenceItem(BaseModel):
    sourceUrl: Optional[str] = ""
    sourceTitle: Optional[str] = ""
    sourceType: Optional[str] = ""
    evidenceText: Optional[str] = ""
    retrievedAt: Optional[datetime] = None

class CompanyResearch(BaseModel):
    companyId: Any
    summary: Optional[str] = ""
    valueProposition: Optional[str] = ""
    coreOfferings: Optional[List[str]] = Field(default_factory=list)
    targetAudience: Optional[str] = ""
    detectedPainPoints: Optional[List[PainPoint]] = Field(default_factory=list)
    techStack: Optional[List[str]] = Field(default_factory=list)
    competitors: Optional[List[str]] = Field(default_factory=list)
    icebreakers: Optional[List[str]] = Field(default_factory=list)
    icpFitScore: Optional[int] = 75
    icpFitReasoning: Optional[str] = ""
    keyPersonnel: Optional[List[KeyPersonnel]] = Field(default_factory=list)
    sourcesUsed: Optional[List[SourceUsed]] = Field(default_factory=list)
    researchSource: Optional[str] = "website_crawl"
    researchMethod: Optional[str] = "WEBSITE_CRAWLED"
    fallbackUsed: Optional[bool] = False
    blockReason: Optional[str] = ""
    evidenceItems: Optional[List[EvidenceItem]] = Field(default_factory=list)
    aiProvider: Optional[str] = "ollama"
    aiModel: Optional[str] = "llama3"

    researchedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
