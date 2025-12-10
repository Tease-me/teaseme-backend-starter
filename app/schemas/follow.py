from datetime import datetime
from pydantic import BaseModel


class FollowStatus(BaseModel):
    influencer_id: str
    user_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class FollowActionResponse(BaseModel):
    influencer_id: str
    user_id: int
    following: bool
    created_at: datetime | None = None


class FollowListResponse(BaseModel):
    count: int
    items: list[FollowStatus]
