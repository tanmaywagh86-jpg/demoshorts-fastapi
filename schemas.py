from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class SongCreate(BaseModel):
    title: str
    artist: str
    youtube_id: str
    start_time: int
    end_time: int


class SongResponse(SongCreate):
    id: int
    
    class Config:
        from_attributes = True


class InteractionCreate(BaseModel):
    user_id: int
    clip_id: int
    action: Literal["like", "skip", "replay", "complete"]


class InteractionResponse(InteractionCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class SongCreateRequest(BaseModel):
    youtube_id: str
    title: str
    artist: str
    genre: str | None = None


class SongCreateResponse(SongCreateRequest):
    id: int

    class Config:
        from_attributes = True
