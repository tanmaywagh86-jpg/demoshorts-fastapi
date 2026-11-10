# DEMOSHORT work log

A running record of what was changed, why, and what is still planned.
Newest entries go at the top of "Log". Update this file whenever code changes.

## Log

### 2026-11-11 — Clip length changed to 30–60 s (Tanmay's decision)

- `ingestion/settings.py`: target 30–60 s, accepted 25–65 s (5 s tolerance so a complete
  section is not rejected for being slightly outside). Audio windows now target 45 s.
- Two candidates sharing 15 s or more count as the same section (was 12 s).
- Tests updated to the new lengths; 32 pass.
- The entry below says 20–30 s; this entry replaces that.

### 2026-11-11 — Backend fixes (branch `fix/backend-pipeline-and-feed`)

**Incident: the local database was reset by the test suite.**
Running the whole suite with `python -m unittest` made `test_collaborative_feed.py` drop and
recreate every table in the real `demoshorts_db` (it reused the application's database
connection, which pointed at PostgreSQL once another test file had been loaded first).
The database now holds only that test's sample rows (3 users without names, 4 sample songs,
4 clips, 5 interactions). Anything stored before is gone and must be re-ingested / re-registered.
Fixed so it cannot happen again: every test file now forces in-memory SQLite before importing
project code, and that test uses its own private engine.

**Setup**
- `database.py`: no password in code any more. `DATABASE_URL` is read from `.env`
  (the same value was added to `.env`); the app stops with a clear message if it is missing.
  The old password is still visible in git history.
- `.gitignore`: added `transcript_cache/`. The six `*_transcript.txt` files moved from the repo
  root into `transcript_cache/` and are no longer tracked by git (still on disk).

**Ingestion pipeline**
- New `ingestion/settings.py`: one place for clip rules. Target 20–30 s, accepted 15–35 s,
  at most 5 clips per song. The prompt, validator and pipeline all read from it.
- Whisper fallback is now used: `ingest_song` calls `get_transcript_with_fallback`
  (cache, then YouTube captions, then Whisper). `--no-whisper` turns it off. Model is `small`.
  Whisper is imported only when needed; yt-dlp is run through the venv's Python.
- Captions: prefers human-written captions over auto-generated ones.
- Audio analysis also runs when `<video_id>.mp3` already exists in the project folder
  (e.g. downloaded by the Whisper fallback), not only with `--audio`.
- `audio_analysis/analyzer.py`: `load_audio_features` converts and loads the audio once
  (it was done three times per song); removed the old demo script at the bottom and the
  unused matplotlib import.
- `ingestion/candidate_merger.py` rewritten, lyrics-first: when a Groq clip and an audio window
  cover the same section, the Groq start/end are kept and the clip is tagged `both`. Energy is
  used only to rank. If a song has more than 5 candidates, keep `both`, then `groq`, then
  `audio`, louder first.
- Removed `clip_selection/` (old 30–60 s selector, superseded by `ingestion/llm.py`).

**API (`main.py`, `schemas.py`)**
- `/feed/personalized`: every unseen clip is now a candidate, so a new user gets a feed
  (clip order) instead of an empty list. Scored clips come first, disliked genres last.
- `POST /interactions`: repeating the same action on the same clip returns the existing record.
- New interaction `save` (scored like `like`).
- `POST /songs` now needs a login. Any logged-in user can add a song; there is no admin role yet.
- Removed broken `POST /api/songs`; fixed `GET /api/songs` (it failed as soon as a song existed).

**Tests**: 32 pass (`venv\Scripts\python.exe -m unittest`), 8 new. They use SQLite only.
Also checked by hand: audio analysis and merging on a real local mp3; the app imports and
connects with the `.env` settings.
**Not run**: a real Groq call, a real Whisper transcription, a live YouTube caption fetch.

### 2026-11-11 — Review of the project, no code changed

- Read every source file except the tests and compared the code with the project write-up.
- Created branch `fix/backend-pipeline-and-feed` from `main`.
- Added this file.

## Still to do

### Needs a decision from Tanmay

- **Playback.** Clips are YouTube IDs plus timestamps, so playback means the visible YouTube
  embed with start/end times. An audio-only feed from YouTube sources is not allowed by
  YouTube's terms. Alternative: host audio we have rights to (e.g. Creative Commons catalogues).
- **Admin role** for song creation: recommended, not built yet (see Follow-ups).

### Follow-ups

- **Re-ingest songs** into the reset database (cached transcripts are in `transcript_cache/`).
- **Beat snapping of clip boundaries** was not done: `start_time`/`end_time` are whole seconds,
  so sub-second beat alignment would be rounded away. Needs fractional-second columns (a migration).
- **Metadata fetch.** Title still defaults to the video ID, artist to "Unknown", genre to empty.
  Empty genre weakens the genre half of the personalized ranking.
- **Admin role** for song creation and ingestion: an `is_admin` flag on users, set by hand in
  the database, required by `POST /songs`. Needs one new column on the `users` table.
- **Database-level uniqueness** for interactions (currently enforced in the endpoint only).
- `POST /songs/ingest` endpoint and CSV batch ingestion (ingestion is CLI-only today).
- Alembic migrations (tables are created with `create_all`).
- Frontend and player.
- Redis caching and a background job queue (deliberately deferred until measured).

### Write-up corrections

- Personalized feed (genre + collaborative scoring) and cursor pagination on both feeds are
  implemented; the write-up lists them as planned.
- The LLM sees only the transcript, not audio features.
- Clip length, Whisper model and the interaction list should match the entries above.
