from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.orm import Session

import auth
import models
import schemas
from database import engine, SessionLocal, get_db


# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI()


# Test endpoint
@app.get("/api/test")
def say_hello():
    return {
        "message": "Hello from FastAPI! The Python server is running in the cs code as backend."
    }


# Authentication endpoints
@app.post("/auth/register", response_model=schemas.UserRegisterResponse, status_code=201)
def register(
    user_data: schemas.UserRegisterRequest,
    db: Session = Depends(get_db),
):
    existing_user = (
        db.query(models.User)
        .filter(models.User.username == user_data.username)
        .first()
    )
    if existing_user is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    db_user = models.User(
        username=user_data.username,
        hashed_password=auth.hash_password(user_data.password),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@app.post("/auth/login", response_model=schemas.TokenResponse)
def login(
    login_data: schemas.UserLoginRequest,
    db: Session = Depends(get_db),
):
    user = (
        db.query(models.User)
        .filter(models.User.username == login_data.username)
        .first()
    )
    if user is None or not auth.verify_password(
        login_data.password, user.hashed_password or ""
    ):
        raise HTTPException(
            status_code=401, detail="Invalid username or password"
        )

    access_token = auth.create_access_token(
        data={"sub": str(user.id), "username": user.username}
    )
    return schemas.TokenResponse(access_token=access_token, token_type="bearer")


# POST: Add a new song
@app.post("/api/songs", response_model=schemas.SongResponse)
def add_song(song: schemas.SongCreate, db: Session = Depends(get_db)):

    db_song = models.Song(**song.model_dump())

    db.add(db_song)
    db.commit()
    db.refresh(db_song)

    return db_song


# GET: Get all songs
@app.get("/api/songs", response_model=list[schemas.SongResponse])
def get_songs(db: Session = Depends(get_db)):

    songs = db.query(models.Song).all()
   
    return songs


@app.post("/songs", response_model=schemas.SongCreateResponse)
def create_song(
    song: schemas.SongCreateRequest,
    db: Session = Depends(get_db),
):
    existing_song = (
        db.query(models.Song)
        .filter(models.Song.youtube_id == song.youtube_id)
        .first()
    )
    if existing_song is not None:
        raise HTTPException(status_code=409, detail="YouTube ID already exists")

    db_song = models.Song(**song.model_dump())
    db.add(db_song)
    db.commit()
    db.refresh(db_song)
    return db_song


@app.get("/songs/{song_id}/clips")
def get_song_clips(song_id: int, db: Session = Depends(get_db)):

    song = (
        db.query(models.Song)
        .filter(models.Song.id == song_id)
        .first()
    )

    if song is None:
        raise HTTPException(
            status_code=404,
            detail="Song not found"
        )

    clips = (
        db.query(models.Clip)
        .filter(models.Clip.song_id == song_id)
        .all()
    )

    return [
        {
            "id": clip.id,
            "song_id": clip.song_id,
            "start_time": clip.start_time,
            "end_time": clip.end_time
        }
        for clip in clips
    ]


@app.get("/feed")
def get_feed(
    limit: int = Query(default=10, ge=1, le=20),
    cursor: int | None = Query(default=None, ge=1),
    genre: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = (
        db.query(models.Clip, models.Song)
        .join(models.Song, models.Clip.song_id == models.Song.id)
        .order_by(models.Clip.id)
    )

    if genre is not None:
        query = query.filter(models.Song.genre == genre)

    if cursor is not None:
        query = query.filter(models.Clip.id > cursor)

    feed_items = query.limit(limit + 1).all()
    has_next_page = len(feed_items) > limit
    feed_items = feed_items[:limit]

    items = [
        {
            "clip_id": clip.id,
            "song_id": clip.song_id,
            "title": song.title,
            "artist": song.artist,
            "youtube_id": song.youtube_id,
            "start_time": clip.start_time,
            "end_time": clip.end_time,
            "genre": song.genre,
        }
        for clip, song in feed_items
    ]

    return {
        "items": items,
        "next_cursor": items[-1]["clip_id"] if has_next_page else None,
    }


@app.post("/interactions", response_model=schemas.InteractionResponse)
def create_interaction(
    interaction: schemas.InteractionCreate,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    clip = db.query(models.Clip).filter(models.Clip.id == interaction.clip_id).first()
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    db_interaction = models.Interaction(
        user_id=current_user.id,
        clip_id=interaction.clip_id,
        action=interaction.action,
    )
    db.add(db_interaction)
    db.commit()
    db.refresh(db_interaction)
    return db_interaction


@app.get("/feed/personalized")
def get_personalized_feed(
    limit: int = Query(default=10, ge=1, le=20),
    cursor: str | None = Query(default=None),
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    action_score = case(
        (models.Interaction.action == "like", 3),
        (models.Interaction.action == "replay", 2),
        (models.Interaction.action == "complete", 2),
        (models.Interaction.action == "skip", -3),
        else_=0,
    )
    genre_scores = (
        db.query(
            models.Song.genre.label("genre"),
            func.sum(action_score).label("score"),
        )
        .join(models.Clip, models.Clip.song_id == models.Song.id)
        .join(
            models.Interaction,
            models.Interaction.clip_id == models.Clip.id,
        )
        .filter(
            models.Interaction.user_id == user_id,
            models.Song.genre.isnot(None),
        )
        .group_by(models.Song.genre)
        .subquery()
    )

    current_positive_clip_ids = (
        select(models.Interaction.clip_id)
        .where(
            models.Interaction.user_id == user_id,
            models.Interaction.action.in_(("like", "replay", "complete")),
        )
    )
    similar_users = (
        db.query(
            models.Interaction.user_id.label("user_id"),
            func.count(func.distinct(models.Interaction.clip_id)).label(
                "similarity"
            ),
        )
        .filter(
            models.Interaction.user_id != user_id,
            models.Interaction.action.in_(("like", "replay", "complete")),
            models.Interaction.clip_id.in_(current_positive_clip_ids),
        )
        .group_by(models.Interaction.user_id)
        .subquery()
    )
    collaborative_action_score = case(
        (models.Interaction.action == "like", 3),
        (models.Interaction.action == "replay", 2),
        (models.Interaction.action == "complete", 2),
        else_=0,
    )
    collaborative_scores = (
        db.query(
            models.Interaction.clip_id.label("clip_id"),
            func.sum(
                collaborative_action_score * similar_users.c.similarity
            ).label("score"),
        )
        .join(
            similar_users,
            models.Interaction.user_id == similar_users.c.user_id,
        )
        .filter(
            models.Interaction.action.in_(("like", "replay", "complete")),
        )
        .group_by(models.Interaction.clip_id)
        .subquery()
    )

    interacted_clip_ids = (
        db.query(models.Interaction.clip_id)
        .filter(models.Interaction.user_id == user_id)
    )

    query = (
        db.query(
            models.Clip,
            models.Song,
            (
                func.coalesce(genre_scores.c.score, literal(0))
                + func.coalesce(collaborative_scores.c.score, literal(0))
            ).label("score"),
        )
        .join(models.Song, models.Clip.song_id == models.Song.id)
        .outerjoin(genre_scores, models.Song.genre == genre_scores.c.genre)
        .outerjoin(
            collaborative_scores,
            models.Clip.id == collaborative_scores.c.clip_id,
        )
        .filter(
            ~models.Clip.id.in_(interacted_clip_ids),
            or_(
                genre_scores.c.genre.isnot(None),
                collaborative_scores.c.clip_id.isnot(None),
            ),
        )
        .order_by(
            (
                func.coalesce(genre_scores.c.score, literal(0))
                + func.coalesce(collaborative_scores.c.score, literal(0))
            ).desc(),
            models.Clip.id,
        )
    )

    if cursor is not None and isinstance(cursor, str):
        try:
            cursor_score, cursor_clip_id = map(int, cursor.split(":", 1))
        except ValueError as error:
            raise HTTPException(status_code=422, detail="Invalid cursor") from error

        query = query.filter(
            or_(
                (
                    func.coalesce(genre_scores.c.score, literal(0))
                    + func.coalesce(collaborative_scores.c.score, literal(0))
                )
                < cursor_score,
                (
                    (
                        func.coalesce(genre_scores.c.score, literal(0))
                        + func.coalesce(collaborative_scores.c.score, literal(0))
                    )
                    == cursor_score
                )
                & (models.Clip.id > cursor_clip_id),
            )
        )

    feed_items = query.limit(limit + 1).all()
    has_next_page = len(feed_items) > limit
    feed_items = feed_items[:limit]

    items = [
        {
            "clip_id": clip.id,
            "song_id": clip.song_id,
            "title": song.title,
            "artist": song.artist,
            "youtube_id": song.youtube_id,
            "start_time": clip.start_time,
            "end_time": clip.end_time,
            "genre": song.genre,
        }
        for clip, song, _score in feed_items
    ]

    return {
        "items": items,
        "next_cursor": (
            f"{feed_items[-1][2]}:{feed_items[-1][0].id}"
            if has_next_page
            else None
        ),
    }
