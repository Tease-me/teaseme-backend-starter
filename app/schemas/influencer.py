from pydantic import BaseModel, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone


class InfluencerBase(BaseModel):
    display_name: str
    voice_id: Optional[str] = None
    prompt_template: Optional[str] = None
    daily_scripts: Optional[List[str]] = None
    bio_json: Optional[Dict[str, Any]] = None

    influencer_agent_id_third_part: Optional[str] = None
    created_at: Optional[datetime] = None
    native_language: Optional[str] = None
    date_of_birth: Optional[datetime] = None

    @field_validator("created_at")
    @classmethod
    def convert_to_naive_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)


class InfluencerCreate(InfluencerBase):
    id: str


class InfluencerUpdate(BaseModel):
    display_name: Optional[str] = None
    voice_id: Optional[str] = None
    prompt_template: Optional[str] = None
    daily_scripts: Optional[List[str]] = None
    bio_json: Optional[Dict[str, Any]] = None
    influencer_agent_id_third_part: Optional[str] = None
    native_language: Optional[str] = None
    date_of_birth: Optional[datetime] = None


class InfluencerOut(InfluencerBase):
    id: str
    profile_photo_key: Optional[str] = None
    profile_video_key: Optional[str] = None

    class Config:
        from_attributes = True


class InfluencerDetail(InfluencerOut):
    about: Optional[str] = None
    photo_url: Optional[str] = None
    video_url: Optional[str] = None