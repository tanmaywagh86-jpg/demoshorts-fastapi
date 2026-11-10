import os

# Tests must never touch the real database: force in-memory SQLite before any project import.
os.environ["DATABASE_URL"] = "sqlite://"

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from ingestion.candidate_merger import (
    merge_and_deduplicate_candidates,
    validate_candidate,
)
from ingestion.ingest_song import ingest_song
from ingestion.llm import generate_llm_candidates
from ingestion.transcript import extract_video_id, format_transcript_for_llm
import models

TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=test_engine,
)


class IngestionPipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)

    def setUp(self):
        Base.metadata.drop_all(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)
        self.db = TestingSessionLocal()

    def tearDown(self):
        self.db.close()

    # ----------------------------------------------------
    # 1. Video ID Extraction Tests
    # ----------------------------------------------------
    def test_extract_video_id(self):
        self.assertEqual(
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            extract_video_id("https://youtu.be/dQw4w9WgXcQ?si=abc123xyz"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            extract_video_id("dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(extract_video_id(""), "")

    # ----------------------------------------------------
    # 2. Transcript Formatting & Token Compaction Tests
    # ----------------------------------------------------
    def test_format_transcript_for_llm(self):
        data = [
            {"start": 0.0, "duration": 4.5, "text": "First line of song"},
            {"start": 12.3, "duration": 3.2, "text": "Second line"},
        ]
        formatted = format_transcript_for_llm(data)
        self.assertIn("[0] First line of song", formatted)
        self.assertIn("[12] Second line", formatted)

    def test_format_transcript_filters_noise_and_compacts(self):
        data = [
            {"start": 0.0, "duration": 5.0, "text": "[Music]"},
            {"start": 6.0, "duration": 2.0, "text": "Hello world"},
            {"start": 7.0, "duration": 1.5, "text": "this is a test"},
            {"start": 15.0, "duration": 3.0, "text": "[Applause]"},
            {"start": 20.0, "duration": 2.0, "text": "♪♪♪"},
            {"start": 25.0, "duration": 4.0, "text": "Real lyric here"},
        ]
        formatted = format_transcript_for_llm(data)
        # Noise should be filtered out
        self.assertNotIn("[Music]", formatted)
        self.assertNotIn("[Applause]", formatted)
        self.assertNotIn("♪", formatted)
        # Close timestamps (6s and 7s) should be compacted onto one line
        self.assertIn("[6] Hello world this is a test", formatted)
        self.assertIn("[25] Real lyric here", formatted)

    # ----------------------------------------------------
    # 3. Candidate Validation Tests
    # ----------------------------------------------------
    def test_validate_candidate(self):
        # Valid 45-second candidate
        self.assertTrue(validate_candidate({"start_time": 10, "end_time": 55}))

        # Negative start time
        self.assertFalse(validate_candidate({"start_time": -5, "end_time": 20}))

        # end_time <= start_time
        self.assertFalse(validate_candidate({"start_time": 30, "end_time": 30}))
        self.assertFalse(validate_candidate({"start_time": 40, "end_time": 20}))

        # Duration too short (< 25s)
        self.assertFalse(validate_candidate({"start_time": 10, "end_time": 30}))

        # Duration too long (> 65s)
        self.assertFalse(validate_candidate({"start_time": 10, "end_time": 80}))

        # Beyond song duration
        self.assertFalse(
            validate_candidate(
                {"start_time": 200, "end_time": 245}, song_duration=180
            )
        )

    # ----------------------------------------------------
    # 4. Candidate Merging and Deduplication Tests
    # ----------------------------------------------------
    def test_merge_and_deduplicate_candidates(self):
        groq_cands = [
            {"start_time": 20, "end_time": 65, "reason": "Catchy verse + chorus"},
            {"start_time": 100, "end_time": 145, "reason": "Guitar hook"},
        ]
        audio_cands = [
            {"start_time": 22, "end_time": 68, "reason": "High RMS energy region"},
            {"start_time": 180, "end_time": 225, "reason": "Drop / chorus"},
        ]

        merged = merge_and_deduplicate_candidates(
            groq_candidates=groq_cands,
            audio_candidates=audio_cands,
            song_duration=240,
        )

        # Candidate 1 (20-65 and 22-68) should overlap and merge to source="both"
        self.assertEqual(len(merged), 3)

        first_cand = merged[0]
        self.assertEqual(first_cand["source"], "both")
        self.assertIn("Catchy verse", first_cand["reason"])
        # Lyrics decide the boundaries: the Groq start/end survive, not the audio window's
        self.assertEqual((first_cand["start_time"], first_cand["end_time"]), (20, 65))

        second_cand = merged[1]
        self.assertEqual(second_cand["start_time"], 100)
        self.assertEqual(second_cand["source"], "groq")

        third_cand = merged[2]
        self.assertEqual(third_cand["start_time"], 180)
        self.assertEqual(third_cand["source"], "audio")

    def test_merge_caps_clips_and_ranks_by_source_then_energy(self):
        groq_cands = [
            {"start_time": 0, "end_time": 45, "reason": "Verse"},
            {"start_time": 60, "end_time": 105, "reason": "Chorus"},
        ]
        audio_cands = [
            {"start_time": 62, "end_time": 108, "reason": "Loud chorus"},
            {"start_time": 120, "end_time": 165, "reason": "Loud outro"},
            {"start_time": 180, "end_time": 225, "reason": "Quiet bridge"},
        ]
        energy = {0: 0.2, 60: 0.9, 120: 0.8, 180: 0.1}

        merged = merge_and_deduplicate_candidates(
            groq_candidates=groq_cands,
            audio_candidates=audio_cands,
            energy_fn=lambda start, end: energy[start],
            max_clips=3,
        )

        # Kept: the lyric+audio match, the other lyric clip, then the louder audio-only window
        self.assertEqual([c["start_time"] for c in merged], [0, 60, 120])
        self.assertEqual([c["source"] for c in merged], ["groq", "both", "audio"])
        self.assertEqual(merged[1]["energy"], 0.9)

    def test_merge_drops_duplicate_candidates_from_same_source(self):
        merged = merge_and_deduplicate_candidates(
            groq_candidates=[
                {"start_time": 20, "end_time": 65, "reason": "Chorus"},
                {"start_time": 22, "end_time": 67, "reason": "Chorus again"},
            ],
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0]["start_time"], merged[0]["end_time"]), (20, 65))

    # ----------------------------------------------------
    # 5. Groq LLM Graceful Fallback Test
    # ----------------------------------------------------
    @patch("ingestion.llm.get_groq_client")
    def test_generate_llm_candidates_graceful_error(self, mock_client):
        # When client is None or raises an exception
        mock_client.return_value = None
        candidates = generate_llm_candidates("sample transcript")
        self.assertEqual(candidates, [])

    # ----------------------------------------------------
    # 6. End-to-End Orchestrator Ingestion Test
    # ----------------------------------------------------
    @patch("ingestion.ingest_song.get_timestamped_transcript")
    @patch("ingestion.ingest_song.get_transcript_with_fallback")
    @patch("ingestion.ingest_song.generate_llm_candidates")
    def test_ingest_uses_whisper_fallback_unless_disabled(
        self, mock_llm, mock_fallback, mock_captions_only
    ):
        mock_llm.return_value = []
        mock_fallback.return_value = []
        mock_captions_only.return_value = []

        ingest_song(youtube_url_or_id="fallback_01", db=self.db)
        mock_fallback.assert_called_once()
        mock_captions_only.assert_not_called()

        ingest_song(youtube_url_or_id="fallback_02", db=self.db, use_whisper=False)
        mock_fallback.assert_called_once()
        mock_captions_only.assert_called_once()

    @patch("ingestion.ingest_song.get_transcript_with_fallback")
    @patch("ingestion.ingest_song.generate_llm_candidates")
    def test_ingest_song_orchestration(self, mock_llm, mock_transcript):
        mock_transcript.return_value = [
            {"start": 0.0, "duration": 5.0, "text": "Intro lyrics"},
            {"start": 20.0, "duration": 45.0, "text": "Chorus lyrics"},
        ]
        mock_llm.return_value = [
            {"start_time": 20, "end_time": 65, "reason": "Chorus section"}
        ]

        summary = ingest_song(
            youtube_url_or_id="https://www.youtube.com/watch?v=test_vid_123",
            title="Automated Discovery Track",
            artist="Demo Artist",
            genre="indie",
            db=self.db,
        )

        self.assertEqual(summary["youtube_id"], "test_vid_123")
        self.assertEqual(summary["title"], "Automated Discovery Track")
        self.assertEqual(summary["genre"], "indie")
        self.assertEqual(summary["saved_clips_count"], 1)

        # Verify in DB
        db_song = (
            self.db.query(models.Song)
            .filter(models.Song.youtube_id == "test_vid_123")
            .first()
        )
        self.assertIsNotNone(db_song)
        self.assertEqual(len(db_song.clips), 1)
        self.assertEqual(db_song.clips[0].start_time, 20)
        self.assertEqual(db_song.clips[0].end_time, 65)

        # Running ingest again should not duplicate clips
        second_summary = ingest_song(
            youtube_url_or_id="test_vid_123",
            title="Updated Title",
            db=self.db,
        )
        self.assertEqual(second_summary["saved_clips_count"], 0)
        self.assertEqual(len(second_summary["clips"]), 1)


if __name__ == "__main__":
    unittest.main()
