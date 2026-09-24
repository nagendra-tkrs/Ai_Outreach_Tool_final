from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

class EmailStep(BaseModel):
    scheduledAt: Optional[datetime] = None
    sentAt: Optional[datetime] = None
    status: Optional[str] = "PENDING"  # PENDING, SENT, FAILED
    error: Optional[str] = None
    messageId: Optional[str] = None

class OutreachRecord(BaseModel):
    companyId: Any
    companyName: str
    companyWebsite: Optional[str] = ""
    contactId: Optional[Any] = None
    contactName: Optional[str] = ""
    contactDesignation: Optional[str] = ""
    recipientEmail: str
    cc: Optional[List[str]] = Field(default_factory=list)
    bcc: Optional[List[str]] = Field(default_factory=list)
    emailSubject: Optional[str] = ""
    emailType: Optional[str] = "INITIAL"
    initialEmail: Optional[EmailStep] = Field(default_factory=EmailStep)
    followUp1: Optional[EmailStep] = Field(default_factory=EmailStep)
    followUp2: Optional[EmailStep] = Field(default_factory=EmailStep)
    lastContactedAt: Optional[datetime] = None
    replyStatus: Optional[str] = "NO_REPLY"  # NO_REPLY, REPLIED
    repliedAt: Optional[datetime] = None
    campaignStatus: Optional[str] = "PENDING"  # PENDING, INITIAL_SENT, FOLLOW_UP_1_SENT, FOLLOW_UP_2_SENT, REPLIED, COMPLETED, FAILED
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
