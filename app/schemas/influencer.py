from pydantic import BaseModel
from typing import List, Optional

class InfluencerBase(BaseModel):
    display_name: str
    voice_id: Optional[str] = None
    prompt_template: Optional[str] = None
    daily_scripts: Optional[List[str]] = None

class InfluencerCreate(InfluencerBase):
    id: str 

class InfluencerUpdate(InfluencerBase):
    pass

class InfluencerOut(InfluencerBase):
    id: str

    class Config:
        from_attributes = True