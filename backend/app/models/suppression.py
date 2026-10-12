from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field


class Suppression(BaseModel):
    """E4: Recipient opt-out / suppression record.

    Any email listed here is permanently blocked from outreach (initial,
    follow-ups, scheduler, and manual sends). Registered idempotently via the
    List-Unsubscribe header + unsubscribe endpoint, or programmatically.
    """

    email: str
    reason: Optional[str] = ""
    source: Optional[str] = ""
    companyId: Optional[Any] = None
    contactId: Optional[Any] = None
    suppressedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class SuppressionCreate(BaseModel):
    email: str = Field(..., description="Email address to suppress")
    reason: Optional[str] = ""
    source: Optional[str] = ""