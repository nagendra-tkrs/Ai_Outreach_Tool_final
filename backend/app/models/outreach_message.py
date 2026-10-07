from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, Field

class OutreachMessage(BaseModel):
    companyId: Any
    contactId: Optional[Any] = None
    step: int = 1  # 1, 2, 3
    stepLabel: Optional[str] = "Initial Outreach"
    subject: str
    bodyHtml: str
    bodyText: Optional[str] = ""
    angle: Optional[str] = "pain_point"
    tone: Optional[str] = "conversational"
    focusService: Optional[str] = "AI Strategy Consulting"
    evidenceUsed: Optional[str] = ""
    recommendedServiceUsed: Optional[str] = ""
    status: Optional[str] = "draft"  # draft, approved, scheduled, sending, sent, failed
    isManuallyEdited: Optional[bool] = False
    scheduledAt: Optional[datetime] = None
    delayDays: Optional[int] = 0
    recipientEmail: Optional[str] = ""
    recipientName: Optional[str] = ""
    ccRecipients: Optional[List[str]] = Field(default_factory=list)
    bccRecipients: Optional[List[str]] = Field(default_factory=list)
    sentAt: Optional[datetime] = None
    openedAt: Optional[datetime] = None
    openCount: Optional[int] = 0
    clickedAt: Optional[datetime] = None
    clickCount: Optional[int] = 0
    messageId: Optional[str] = None
    trackingId: Optional[str] = None
    error: Optional[str] = None
    linkedinNote: Optional[str] = ""
    linkedinInmail: Optional[str] = ""
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
