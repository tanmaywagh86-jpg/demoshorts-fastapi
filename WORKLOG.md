# DEMOSHORT work log

A running record of what was changed, why, and what is still planned.
Newest entries go at the top of "Log". Update this file whenever code changes.

## Log

### 2026-11-11 — Review of the project, no code changed yet

- Read every source file except the tests and compared the code with the project write-up.
- Created branch `fix/backend-pipeline-and-feed` from `main`. It has no commits yet.
- Tried to run the tests for a baseline: `pytest` is not installed in `venv`, so nothing ran.
  The tests are written with `unittest`, so `python -m unittest` should work without it (not yet tried).
- Work was stopped at the user's request before any file was edited.
- Added this file.

## Planned changes (not started)

### Main changes

1. **Decide playback.** Clips are YouTube IDs plus timestamps, so playback means the visible
   YouTube embed with start/end times. An audio-only feed from YouTube sources is not allowed by
   YouTube's terms. Alternative: host audio we have rights to (e.g. Creative Commons catalogues).
   *Needs a decision from Tanmay before the frontend is built.*
2. **Lyrics-first merging.** In `ingestion/candidate_merger.py`, an overlapping audio window
   currently replaces the LLM's lyric-aligned boundaries. Change to: LLM picks boundaries, snap them
   to the nearest beat with `refine_boundaries` (`audio_analysis/analyzer.py`), use energy only to
   rank candidates.
3. **Cold start in `/feed/personalized`** (`main.py`). A user with no interactions gets an empty
   feed. Fall back to the plain or popular feed.
4. **One clip-length rule, one selector.** Ingestion uses 20–30 s (validator 15–35 s);
   the old `clip_selection/selector.py` and the write-up say 30–60 s. Pick one and retire the old selector.

### Pipeline gaps

- **Whisper fallback is not wired in.** `ingest_song.py` calls `get_timestamped_transcript`
  (captions only) instead of `get_transcript_with_fallback`. The model is `base`, the write-up says `small`.
- **Audio analysis only runs with `--audio`.** Without a local file, clips are Groq-only.
- **No metadata fetch.** Title defaults to the video ID, artist to "Unknown", genre to empty.
  Empty genre also weakens the genre half of the personalized ranking.
- **Caption choice is arbitrary.** The first available transcript is used, in any language.

### Smaller issues

- `POST /api/songs` fails: its schema has `start_time`/`end_time`, which `Song` does not have.
- Song creation endpoints need no login.
- Repeated interactions are not deduplicated, so repeat likes inflate scores.
- `database.py` has a default database password in committed code; move it to `.env` only.
- Transcript cache files (`*_transcript.txt`) sit in the repo root and are committed;
  move them to an ignored cache folder.
- "save" is in the write-up but not an accepted interaction (only like, skip, replay, complete).

### Not built yet (from the write-up)

- `POST /songs/ingest` endpoint and CSV batch ingestion (ingestion is CLI-only today).
- Alembic migrations (tables are created with `create_all`).
- Frontend and player.
- Redis caching and a background job queue (deliberately deferred until measured).

### Write-up corrections

- Personalized feed (genre + collaborative scoring) and cursor pagination on both feeds are
  already implemented; the write-up lists them as planned.
- The LLM sees only the transcript, not audio features.
