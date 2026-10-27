import argparse
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from audio_analysis.analyzer import find_energy_candidate_windows, get_audio_duration
from database import SessionLocal
from ingestion.candidate_merger import merge_and_deduplicate_candidates
from ingestion.llm import generate_llm_candidates
from ingestion.transcript import extract_video_id, get_timestamped_transcript
import models


def ingest_song(
    youtube_url_or_id: str,
    title: str | None = None,
    artist: str | None = None,
    genre: str | None = None,
    audio_path: str | None = None,
    force_reprocess: bool = False,
    db: Session | None = None,
) -> dict[str, Any]:
    """Coordinates automated ingestion of a song from YouTube URL / audio file:

    1. Checks DB for existing song and clips (idempotency gate - saves 100% LLM tokens).
    2. Extracts video ID.
    3. Retrieves timestamped transcript (from local cache or YouTube).
    4. Generates Groq candidate clips (lyrical/thematic with strict JSON output & max_tokens).
    5. Generates librosa candidate clips (high-energy audio peaks).
    6. Combines, validates, and deduplicates candidate clips.
    7. Persists Song and Clips into the database.
    """
    video_id = extract_video_id(youtube_url_or_id)
    if not video_id:
        raise ValueError(f"Invalid YouTube URL or video ID: {youtube_url_or_id}")

    manage_db = db is None
    session: Session = SessionLocal() if manage_db else db

    try:
        # Phase 0: Idempotency & Token Savings Check
        if not force_reprocess:
            existing_song = (
                session.query(models.Song)
                .filter(models.Song.youtube_id == video_id)
                .first()
            )
            if existing_song and existing_song.clips:
                print(f"\nSong '{existing_song.title}' already processed with {len(existing_song.clips)} clips. Skipping LLM & audio analysis (0 tokens consumed).")
                return {
                    "song_id": existing_song.id,
                    "youtube_id": existing_song.youtube_id,
                    "title": existing_song.title,
                    "artist": existing_song.artist,
                    "genre": existing_song.genre,
                    "transcript_found": True,
                    "groq_candidates_count": 0,
                    "audio_candidates_count": 0,
                    "total_candidates": len(existing_song.clips),
                    "saved_clips_count": 0,
                    "clips": [
                        {
                            "id": c.id,
                            "song_id": existing_song.id,
                            "start_time": c.start_time,
                            "end_time": c.end_time,
                            "source": "cached_db",
                            "reason": "Existing processed clip",
                        }
                        for c in existing_song.clips
                    ],
                }

        print(f"\nProcessing song...")
        print(f"Video ID: {video_id}")

        # Phase 1: Transcript retrieval
        print("\nFetching transcript...")
        transcript_data = get_timestamped_transcript(video_id)
        if transcript_data:
            print(f"Transcript obtained ({len(transcript_data)} entries).")
        else:
            print("No transcript available or failed to fetch.")

        # Phase 2: Groq Candidate Generation
        groq_candidates = []
        if transcript_data:
            print("\nRunning Groq candidate selection...")
            groq_candidates = generate_llm_candidates(transcript_data)
            print(f"{len(groq_candidates)} transcript candidate(s) found.")
        else:
            print("\nSkipping Groq candidate selection (no transcript).")

        # Phase 3: Audio Analysis Candidate Generation
        audio_candidates = []
        song_duration = None
        if audio_path and os.path.exists(audio_path):
            print(f"\nRunning audio analysis on {audio_path}...")
            try:
                song_duration = get_audio_duration(audio_path)
                audio_candidates = find_energy_candidate_windows(
                    audio_path,
                    target_duration=25.0,
                    min_duration=20.0,
                    max_duration=30.0,
                    top_k=3,
                )
                print(f"{len(audio_candidates)} audio candidate(s) found (audio duration: {song_duration:.1f}s).")
            except Exception as e:
                print(f"Audio analysis error: {e}")
        else:
            if audio_path:
                print(f"\nAudio file not found at '{audio_path}'. Skipping audio analysis.")

        # Phase 4: Combine, Validate, Deduplicate
        print("\nCombining candidates...")
        final_candidates = merge_and_deduplicate_candidates(
            groq_candidates=groq_candidates,
            audio_candidates=audio_candidates,
            song_duration=song_duration,
            min_duration=15,
            max_duration=35,
        )
        print(f"{len(final_candidates)} unique candidate(s) after validation.")

        # Phase 5: Database Persistence
        saved_clips = []
        print("\nSaving to database...")
        # Check or create Song
        song = (
            session.query(models.Song)
            .filter(models.Song.youtube_id == video_id)
            .first()
        )

        if song is None:
            song = models.Song(
                title=title or video_id,
                artist=artist or "Unknown",
                youtube_id=video_id,
                genre=genre,
            )
            session.add(song)
            session.flush()
            print(f"Song '{song.title}' created (ID: {song.id}).")
        else:
            if title:
                song.title = title
            if artist:
                song.artist = artist
            if genre:
                song.genre = genre
            session.flush()
            print(f"Existing song '{song.title}' found (ID: {song.id}).")

        # Save Clips
        saved_count = 0
        for cand in final_candidates:
            st = int(cand["start_time"])
            et = int(cand["end_time"])

            existing_clip = (
                session.query(models.Clip)
                .filter(
                    models.Clip.song_id == song.id,
                    models.Clip.start_time == st,
                    models.Clip.end_time == et,
                )
                .first()
            )

            if existing_clip is None:
                new_clip = models.Clip(
                    song_id=song.id,
                    start_time=st,
                    end_time=et,
                )
                session.add(new_clip)
                session.flush()
                saved_clips.append({
                    "id": new_clip.id,
                    "song_id": song.id,
                    "start_time": st,
                    "end_time": et,
                    "source": cand.get("source", "unknown"),
                    "reason": cand.get("reason", ""),
                })
                saved_count += 1
            else:
                saved_clips.append({
                    "id": existing_clip.id,
                    "song_id": song.id,
                    "start_time": st,
                    "end_time": et,
                    "source": cand.get("source", "unknown"),
                    "reason": cand.get("reason", ""),
                })

        session.commit()
        print(f"{saved_count} new clip(s) saved ({len(saved_clips)} total).")
        print("\nDone.")

        return {
            "song_id": song.id,
            "youtube_id": song.youtube_id,
            "title": song.title,
            "artist": song.artist,
            "genre": song.genre,
            "transcript_found": bool(transcript_data),
            "groq_candidates_count": len(groq_candidates),
            "audio_candidates_count": len(audio_candidates),
            "total_candidates": len(final_candidates),
            "saved_clips_count": saved_count,
            "clips": saved_clips,
        }

    except Exception as e:
        session.rollback()
        raise e
    finally:
        if manage_db:
            session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Automated Song to Candidate Clip Ingestion Pipeline"
    )
    parser.add_argument("url", help="YouTube URL or 11-character video ID")
    parser.add_argument("--title", help="Optional song title")
    parser.add_argument("--artist", help="Optional song artist")
    parser.add_argument("--genre", help="Optional song genre")
    parser.add_argument("--audio", help="Optional path to local authorized audio file (.mp3 or .wav)")
    parser.add_argument("--force", action="store_true", help="Force re-running LLM and audio analysis even if song exists in DB")

    args = parser.parse_args()

    try:
        summary = ingest_song(
            youtube_url_or_id=args.url,
            title=args.title,
            artist=args.artist,
            genre=args.genre,
            audio_path=args.audio,
            force_reprocess=args.force,
        )
        print("\nIngestion Summary:")
        print(f"  Song: {summary['title']} by {summary['artist']} (ID: {summary['song_id']})")
        print(f"  YouTube ID: {summary['youtube_id']}")
        print(f"  Clips generated: {len(summary['clips'])}")
        for i, clip in enumerate(summary['clips'], start=1):
            print(f"    Clip {i}: [{clip['start_time']}s -> {clip['end_time']}s] (Source: {clip['source']})")
            if clip.get('reason'):
                print(f"      Reason: {clip['reason']}")
    except Exception as err:
        print(f"\nIngestion failed: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
