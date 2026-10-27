import os
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
        # Valid 25-second candidate
        self.assertTrue(validate_candidate({"start_time": 10, "end_time": 35}))

        # Negative start time
        self.assertFalse(validate_candidate({"start_time": -5, "end_time": 20}))

        # end_time <= start_time
        self.assertFalse(validate_candidate({"start_time": 30, "end_time": 30}))
        self.assertFalse(validate_candidate({"start_time": 40, "end_time": 20}))

        # Duration too short (< 15s)
        self.assertFalse(validate_candidate({"start_time": 10, "end_time": 20}))

        # Duration too long (> 35s)
        self.assertFalse(validate_candidate({"start_time": 10, "end_time": 60}))

        # Beyond song duration
        self.assertFalse(
            validate_candidate(
                {"start_time": 200, "end_time": 225}, song_duration=180
            )
        )

    # ----------------------------------------------------
    # 4. Candidate Merging and Deduplication Tests
    # ----------------------------------------------------
    def test_merge_and_deduplicate_candidates(self):
        groq_cands = [
            {"start_time": 20, "end_time": 45, "reason": "Catchy verse + chorus"},
            {"start_time": 100, "end_time": 125, "reason": "Guitar hook"},
        ]
        audio_cands = [
            {"start_time": 22, "end_time": 48, "reason": "High RMS energy region"},
            {"start_time": 180, "end_time": 205, "reason": "Drop / chorus"},
        ]

        merged = merge_and_deduplicate_candidates(
            groq_candidates=groq_cands,
            audio_candidates=audio_cands,
            song_duration=240,
        )

        # Candidate 1 (20-45 and 22-48) should overlap and merge to source="both"
        self.assertEqual(len(merged), 3)

        first_cand = merged[0]
        self.assertEqual(first_cand["source"], "both")
        self.assertIn("Catchy verse", first_cand["reason"])

        second_cand = merged[1]
        self.assertEqual(second_cand["start_time"], 100)
        self.assertEqual(second_cand["source"], "groq")

        third_cand = merged[2]
        self.assertEqual(third_cand["start_time"], 180)
        self.assertEqual(third_cand["source"], "audio")

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
    @patch("ingestion.ingest_song.generate_llm_candidates")
    def test_ingest_song_orchestration(self, mock_llm, mock_transcript):
        mock_transcript.return_value = [
            {"start": 0.0, "duration": 5.0, "text": "Intro lyrics"},
            {"start": 20.0, "duration": 25.0, "text": "Chorus lyrics"},
        ]
        mock_llm.return_value = [
            {"start_time": 20, "end_time": 45, "reason": "Chorus section"}
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
        self.assertEqual(db_song.clips[0].end_time, 45)

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
