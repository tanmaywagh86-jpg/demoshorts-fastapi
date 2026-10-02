from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship
from database import Base


class Song(Base):
    __tablename__ = "songs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    artist = Column(String)
    youtube_id = Column(String, unique=True, index=True)
    genre = Column(String)

    clips = relationship(
        "Clip",
        back_populates="song",
        cascade="all, delete-orphan"
    )

class Clip(Base):
    __tablename__ = "clips"

    id = Column(Integer, primary_key=True, index=True)
    song_id = Column(Integer, ForeignKey("songs.id"))
    start_time = Column(Integer)
    end_time = Column(Integer)

    song = relationship("Song", back_populates="clips")
    interactions = relationship("Interaction", back_populates="clip")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)

    interactions = relationship("Interaction", back_populates="user")


class Interaction(Base):
    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    clip_id = Column(Integer, ForeignKey("clips.id"))
    action = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="interactions")
    clip = relationship("Clip", back_populates="interactions")
