from datetime import datetime
from typing import Literal

from pydantic import BaseModel


InteractionAction = Literal["like", "save", "skip", "replay", "complete"]


class InteractionCreate(BaseModel):
    clip_id: int
    action: InteractionAction


class InteractionResponse(BaseModel):
    id: int
    user_id: int
    clip_id: int
    action: InteractionAction
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


class SongIngestRequest(BaseModel):
    url: str
    title: str | None = None
    artist: str | None = None
    genre: str | None = None
    use_whisper: bool = True


class IngestedClipSummary(BaseModel):
    id: int
    song_id: int
    start_time: int
    end_time: int
    source: str
    reason: str


class SongIngestResponse(BaseModel):
    song_id: int
    youtube_id: str
    title: str
    artist: str
    genre: str | None = None
    transcript_found: bool
    groq_candidates_count: int
    audio_candidates_count: int
    total_candidates: int
    saved_clips_count: int
    clips: list[IngestedClipSummary]


class UserRegisterRequest(BaseModel):
    username: str
    password: str


class UserRegisterResponse(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True


class UserProfileResponse(BaseModel):
    id: int
    username: str
    is_admin: bool

    class Config:
        from_attributes = True


class UserLoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

