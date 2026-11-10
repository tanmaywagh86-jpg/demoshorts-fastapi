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


class UserRegisterRequest(BaseModel):
    username: str
    password: str


class UserRegisterResponse(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True


class UserLoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

