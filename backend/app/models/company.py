from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, Field

def extract_normalized_domain(website: str) -> str:
    if not website:
        return ""
    import re
    cleaned = re.sub(r'^https?://', '', website, flags=re.IGNORECASE)
    cleaned = re.sub(r'^www\.', '', cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.split('/')[0].lower().strip()
    return cleaned

class CompanyBase(BaseModel):
    companyName: str
    website: str
    normalizedWebsite: Optional[str] = None
    evidence: Optional[str] = ""
    recommendedService: Optional[str] = ""
    officialDomain: Optional[str] = ""
    legalCompanyName: Optional[str] = ""
    corporateEmailDomain: Optional[str] = ""
    domainEvidence: Optional[List[Any]] = Field(default_factory=list)
    headquarters: Optional[str] = ""
    location: Optional[str] = ""
    description: Optional[str] = ""
    companyAliases: Optional[List[str]] = Field(default_factory=list)
    parentCompany: Optional[str] = ""
    industry: Optional[str] = ""
    country: Optional[str] = ""
    contactName: Optional[str] = ""
    contactEmail: Optional[str] = ""
    revenue: Optional[str] = ""
    employeeCount: Optional[str] = ""
    notes: Optional[str] = ""
    source: Optional[str] = "bulk"
    importBatchId: Optional[str] = None
    crawlStatus: Optional[str] = "pending"
    lastCrawlJobId: Optional[str] = None
    researchStatus: Optional[str] = "pending"
    lastResearchAt: Optional[datetime] = None
    outreachStatus: Optional[str] = "none"
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    def model_post_init(self, __context: Any) -> None:
        if self.website and not self.normalizedWebsite:
            self.normalizedWebsite = extract_normalized_domain(self.website)
