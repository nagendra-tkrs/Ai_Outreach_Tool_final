from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field

class AISettings(BaseModel):
    provider: Optional[str] = "ollama"
    ollamaBaseUrl: Optional[str] = "http://localhost:11434"
    model: Optional[str] = "llama3"


class SMTPSettings(BaseModel):
    host: Optional[str] = ""
    port: Optional[int] = 587
    secure: Optional[bool] = False
    user: Optional[str] = ""
    pass_: Optional[str] = Field(default="", alias="pass")
    fromName: Optional[str] = "AI Outreach"
    fromEmail: Optional[str] = ""

    model_config = {
        "populate_by_name": True
    }

class SenderProfile(BaseModel):
    companyName: Optional[str] = "GrowthAI Solutions"
    senderName: Optional[str] = "Alex"
    senderTitle: Optional[str] = "Head of Partnerships"
    productDescription: Optional[str] = "We help high-growth B2B companies automate client research and outreach pipeline with AI, increasing meeting booking rates by 3.5x."
    targetPitch: Optional[str] = "Offering a quick 10-minute workflow demo to showcase tailored B2B growth opportunities."

class Setting(BaseModel):
    key: str = "global_settings"
    ai: Optional[AISettings] = Field(default_factory=AISettings)
    smtp: Optional[SMTPSettings] = Field(default_factory=SMTPSettings)
    senderProfile: Optional[SenderProfile] = Field(default_factory=SenderProfile)
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None

    model_config = {
        "populate_by_name": True
    }
