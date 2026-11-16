# DEMOSHORT work log

A running record of what was changed, why, and what is still planned.
Newest entries go at the top of "Log". Update this file whenever code changes.

## Log

### 2026-11-16 — Instagram Reels / TikTok Touchpad Swiping & Vertical Scroll

- **Touchpad & Touch Gestures (`static/index.html`)**:
  - Implemented a dedicated `#gesture-surface` overlay sitting at `z-index: 22` directly above the YouTube iframe to prevent the cross-origin iframe from swallowing touchpad scroll and drag events.
  - Added physical pointer drag (`pointerdown`, `pointermove`, `pointerup`, `pointercancel`) so clips follow mouse/touchpad drag with real-time `translateY` offset and rubber-band boundary resistance.
  - Added two-finger touchpad `wheel` scroll listener with accumulator and threshold `28px` to seamlessly slide between candidate clips on laptop touchpads.
  - Implemented Instagram Reels card sliding transitions: current clip slides up/down out of view, and incoming clip slides in smoothly from opposite edge with layout reflow.
  - Added Instagram double-tap heart burst animation with floating heart and automatic like interaction.
  - Added single-tap play/pause toggle with animated center pulse feedback.
  - Added `Prev` button and keyboard navigation (Arrow Up / Arrow Down / Page Up / Page Down).
  - Added subtle swipe & scroll guidance badge.


### 2026-11-11 — Re-ingested six songs into the reset database (data only, no code change)

- Removed the leftover test rows (4 songs, 4 clips, 3 users, 5 interactions).
- Ingested the six songs with cached transcripts; 18 clips saved. First live Groq run of the new pipeline.
  Titles/artists came from YouTube; genres were assigned by hand and should be checked.

  | YouTube ID | Title | Artist | Genre | Clips |
  |---|---|---|---|---|
  | `-8C_2BBVWk8` | Zara Sa | KK | bollywood | 4 |
  | `FxGvi8O3mxM` | Fandry Song | Ajay-Atul | marathi | 1 |
  | `crOA1iriypE` | Har Kisi Ko Nahi Milta | Arijit Singh, Neeti Mohan | bollywood | 3 |
  | `mWRsgZuwf_8` | Demons | Imagine Dragons | rock | 4 |
  | `ri1Ar5nEq4s` | Aaj Ki Raat | Sachin-Jigar, Madhubanti Bagchi, Divya Kumar | bollywood | 3 |
  | `wqaF_so8RJs` | Mere Nishan | Mohammed | (none) | 3 |

- Problems seen in this run (not fixed):
  - Groq often returns clips shorter than asked. Several were rejected as under 25 s
    (Fandry Song kept 1 of 4, Mere Nishan kept 1 of 3) and several kept clips are 25–29 s.
  - Aaj Ki Raat has a clip ending at 285 s but the video is 278 s long. Without an audio file
    the song length is unknown, so the end is not clamped.
  - Demons has two clips that overlap by 5 s (12–40 and 35–71).
- No users exist yet: register, then `python make_admin.py <username>`.

### 2026-11-11 — Admin role for song creation

- `models.py`: new `is_admin` column on `users` (false by default).
- `auth.py`: new `get_current_admin` dependency; non-admins get 403 "Admin access required".
- `main.py`: `POST /songs` now requires an admin.
- New `make_admin.py`: `python make_admin.py <username>` grants admin, `--revoke` removes it.
  Registration can never grant it.
- Local database: ran `ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE`.
  Any other copy of the database (a teammate's, a server) needs the same statement, because
  there are no migrations yet.
- Tests: 33 pass, 1 new plus the song-creation test extended.
- Not covered: the ingestion CLI writes to the database directly and is not behind the admin check.

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

### 2026-11-16 — Batch ingestion verification, make_admin creation support, live server launch & Reels navigation

- **Instagram Reels / Shorts Vertical Gestures**: Added smooth vertical swipe and mouse-wheel scrolling to the web player (`static/index.html`):
  - Scroll down / swipe up moves to the next clip with slide-up transition animation.
  - Scroll up / swipe down moves to the previous clip with slide-down transition animation.
  - Added dedicated `Prev` (`⏮️`) button in the action sidebar.
  - Added keyboard navigation (`ArrowDown` / `PageDown` for next, `ArrowUp` / `PageUp` for prev, `Space` for play/pause).
- **Batch Ingestion Execution**: Ran `ingestion/batch_ingest.py` on `sample_songs.csv`. Ingestion pipeline confirmed 18 clips across 6 songs (Imagine Dragons, KK, Ajay-Atul, Arijit Singh, Sachin-Jigar, Mohammed) correctly populated in PostgreSQL without redundant LLM token consumption.
- **Admin Management CLI**: Enhanced `make_admin.py` with `--password` option allowing direct creation of admin users without requiring prior manual API registration.
- **Tests**: Added tests in `test_auth.py` verifying admin creation, promotion, and revocation. 43 tests pass across the repository.
- **Server Deployment**: FastAPI server running live at `http://127.0.0.1:8000` serving the vertical short-form video player and personalized feed API.

### 2026-11-15 — Backend features, admin ingestion API, metadata extraction, database constraints & migrations

**Authentication & User Profile**
- Added `GET /auth/me` endpoint in `main.py` protected by `auth.get_current_user`. Returns user ID, username, and admin status (`schemas.UserProfileResponse`).
- Added tests in `test_auth_endpoints.py` covering authenticated profile fetch and 401 on missing/invalid token.

**Database & Integrity**
- Added `UniqueConstraint("user_id", "clip_id", "action", name="uq_interaction_user_clip_action")` to `models.Interaction`.
- Initialized Alembic migrations (`alembic init alembic`), configured `alembic/env.py` to auto-load `.env`, `models.Base.metadata`, and enabled `compare_type=True`.
- Autogenerated and applied initial migration (`63c551151221_initial_schema_with_admin_and_constraints`) enforcing the interaction constraint in PostgreSQL.
- Converted `models.Clip.start_time` and `models.Clip.end_time` from integer seconds to `Float` columns for sub-second beat alignment and snapping precision.
- Autogenerated and applied migration `1b24c02b4552_change_clip_timestamps_to_float` modifying columns in PostgreSQL.
- Added database-level duplicate interaction test in `test_protected_endpoints.py` verifying `IntegrityError`.

**Ingestion, Beat Snapping & Batch Processing**
- Added `fetch_video_metadata` in `ingestion/transcript.py` using `yt-dlp --dump-json --skip-download` to extract song title, artist/channel name, and total duration.
- Updated `ingestion/ingest_song.py` to auto-populate title and artist when not manually specified, and to clamp candidate clip durations to the true song length.
- Updated `audio_analysis/analyzer.py` and `ingestion/candidate_merger.py` to preserve sub-second float precision (e.g. 2 decimal places) for refined beat snapping boundaries instead of truncating to integers.
- Created `ingestion/batch_ingest.py` supporting bulk ingestion from CSV (with flexible column headers) or plain TXT files with polite rate-limiting, progress indicators, non-blocking failure recovery, and aggregated reporting.
- Created `sample_songs.csv` pre-populated with YouTube IDs from the cached transcripts for easy batch testing.
- Added admin-protected `POST /songs/ingest` endpoint in `main.py` using `auth.get_current_admin`. Accepts YouTube URL, optional genre, title, artist, audio file, and whisper toggle; returns detailed ingestion and clip summary (`schemas.SongIngestResponse`).
- Built an interactive, mobile-responsive vertical web player at `static/index.html` served at `GET /`:
  - Official YouTube IFrame Player API embedding with automatic start/end timestamp precision looping.
  - Full interaction controls: Like, Save, Replay, Skip, and automatic watch completion dispatch.
  - JWT Authentication modal (Register, Login, current user display, and admin ingestion drawer).
  - Cursor-based infinite scroll / pagination loading `GET /feed/personalized` (or candidate fallback).
- Added permissions, execution, and frontend endpoint tests in `test_protected_endpoints.py`.
- Added tests in `test_ingestion.py` verifying metadata extraction, clip duration clamping, sub-second float candidate validation & persistence, and CSV/TXT batch ingestion with error isolation.

**Tests**: 42 pass (`venv\Scripts\python.exe -m unittest discover -s . -p "test_*.py"`).

### 2026-11-11 — Review of the project, no code changed

- Read every source file except the tests and compared the code with the project write-up.
- Created branch `fix/backend-pipeline-and-feed` from `main`.
- Added this file.

## Still to do

### Needs a decision from Tanmay

- **Playback.** Clips are YouTube IDs plus timestamps, so playback means the visible YouTube
  embed with start/end times. An audio-only feed from YouTube sources is not allowed by
  YouTube's terms. Alternative: host audio we have rights to (e.g. Creative Commons catalogues).

### Follow-ups

- **Re-ingest songs** into the reset database (cached transcripts are in `transcript_cache/`, seed file in `sample_songs.csv`).
- **Make yourself admin**: register a user, then run `python make_admin.py <username>`.
- Redis caching and a background job queue (deferred until scale warrants).

### Write-up corrections

- Personalized feed (genre + collaborative scoring) and cursor pagination on both feeds are
  implemented; the write-up lists them as planned.
- The LLM sees only the transcript, not audio features.
- Clip length, Whisper model and the interaction list should match the entries above.
