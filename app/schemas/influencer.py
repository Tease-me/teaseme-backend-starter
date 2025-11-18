from pydantic import BaseModel, field_validator
from typing import List, Optional
from datetime import datetime, timezone
class InfluencerBase(BaseModel):
    display_name: str
    voice_id: Optional[str] = None
    prompt_template: Optional[str] = None
    daily_scripts: Optional[List[str]] = None
    voice_prompt: Optional[str] = None
    influencer_agent_id_third_part: Optional[str] = None
    created_at: Optional[datetime] = None

    @field_validator("created_at")
    @classmethod
    def convert_to_naive_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

class InfluencerCreate(InfluencerBase):
    id: str 

class InfluencerUpdate(InfluencerBase):
    pass

class InfluencerOut(InfluencerBase):
    id: str

    class Config:
        from_attributes = True
