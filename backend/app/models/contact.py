from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

class Contact(BaseModel):
    companyId: Any
    name: str
    designation: Optional[str] = ""
    title: Optional[str] = ""
    roleCategory: Optional[str] = "other"
    designationOriginal: Optional[str] = ""
    designationNormalized: Optional[str] = ""
    personVerified: Optional[str] = "unknown"
    designationVerified: Optional[str] = "unknown"
    companyAssociationVerified: Optional[str] = "unknown"
    roleStatus: Optional[str] = "current"
    email: Optional[str] = ""
    emailDomain: Optional[str] = ""
    corporateEmailDomain: Optional[str] = ""
    alternativeEmails: Optional[List[Any]] = Field(default_factory=list)
    emailStatus: Optional[str] = "UNVERIFIED"
    domainStatus: Optional[str] = "UNKNOWN"
    status: Optional[str] = "unverified"
    emailSyntaxValid: Optional[str] = "unknown"
    emailDomainValid: Optional[str] = "unknown"
    publicEmailEvidence: Optional[str] = "unknown"
    personEmailMatch: Optional[str] = "unknown"
    mailboxVerification: Optional[str] = "NOT_INDEPENDENTLY_CONFIRMED"
    emailSource: Optional[str] = "Official Leadership Page"
    emailSourceUrl: Optional[str] = ""
    emailVerificationMethod: Optional[str] = "None"
    mxStatus: Optional[str] = "UNKNOWN"
    mxProvider: Optional[str] = ""
    patternUsed: Optional[str] = "first.last"
    emailPattern: Optional[str] = "first.last"
    patternExamples: Optional[List[str]] = Field(default_factory=list)
    patternSources: Optional[List[str]] = Field(default_factory=list)
    patternConfidence: Optional[str] = "unverified"
    source: Optional[str] = "Official Company Leadership Page"
    sourceType: Optional[str] = "official_team_page"
    sourceUrl: Optional[str] = ""
    sourceTitle: Optional[str] = ""
    sourceDate: Optional[str] = ""
    roleSourceUrl: Optional[str] = ""
    roleSourceDate: Optional[str] = ""
    isCurrentRole: Optional[str] = "likely_current"
    confidenceScore: Optional[int] = 85
    confidence: Optional[str] = "medium"
    dataQuality: Optional[str] = "UNKNOWN"
    confidenceReasoning: Optional[List[str]] = Field(default_factory=list)
    evidenceSources: Optional[List[Any]] = Field(default_factory=list)
    evidence: Optional[Dict[str, Any]] = Field(default_factory=lambda: {
        "personEvidence": "",
        "roleEvidence": "",
        "emailEvidence": "",
        "snippet": "",
        "sourceDate": "",
        "retrievedAt": None
    })
    auditTrail: Optional[Dict[str, Any]] = Field(default_factory=lambda: {
        "sourcesSearched": [],
        "queriesUsed": [],
        "emailsDiscovered": [],
        "rejectedEmails": [],
        "selectedEmail": "",
        "verificationStatus": "",
        "confidence": 0
    })
    verificationDetails: Optional[Dict[str, Any]] = Field(default_factory=lambda: {
        "isValidSyntax": None,
        "hasMxRecords": None,
        "patternConfidence": "unverified",
        "statusReason": "",
        "verifiedAt": None
    })
    verificationNotes: Optional[str] = ""
    lastVerifiedAt: Optional[datetime] = None
    phone: Optional[str] = ""
    linkedinUrl: Optional[str] = ""
    seniority: Optional[str] = "unknown"
    department: Optional[str] = ""
    isPrimaryDecisionMaker: Optional[bool] = False
    relevanceScore: Optional[int] = 75
    verificationScore: Optional[int] = 85
    overallScore: Optional[int] = 80
    selectionReason: Optional[str] = ""
    candidateEmployer: Optional[str] = ""
    companyMatchStatus: Optional[str] = "UNKNOWN"
    evidenceTier: Optional[str] = "unknown"
    employmentStatus: Optional[str] = "CURRENT"
    decisionMakerStatus: Optional[str] = "VERIFIED"
    targetOpportunity: Optional[str] = ""
    searchProvider: Optional[str] = "none"
    searchConfigured: Optional[bool] = False
    searchReason: Optional[str] = ""
    searchQueriesUsed: Optional[int] = 0
    searchResultsFound: Optional[int] = 0
    aiProvider: Optional[str] = ""
    aiModel: Optional[str] = ""
    discoveredAt: Optional[datetime] = None
    notes: Optional[str] = ""
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
