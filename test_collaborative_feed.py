import os

# Tests must never touch the real database: force in-memory SQLite before any project import.
os.environ["DATABASE_URL"] = "sqlite://"

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from main import get_personalized_feed

# A private in-memory engine: setUp drops every table, so this test must never
# share an engine with the application (database.engine).
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class CollaborativeFeedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()

        target_user = models.User(id=1)
        similar_user = models.User(id=2)
        unrelated_user = models.User(id=3)
        target_song = models.Song(
            title="Target song", artist="Target artist", youtube_id="target", genre="pop"
        )
        recommended_song = models.Song(
            title="Recommended song",
            artist="Recommended artist",
            youtube_id="recommended",
            genre="jazz",
        )
        second_recommended_song = models.Song(
            title="Second recommendation",
            artist="Recommended artist",
            youtube_id="recommended-2",
            genre="electronic",
        )
        unrelated_song = models.Song(
            title="Unrelated song",
            artist="Unrelated artist",
            youtube_id="unrelated",
            genre="rock",
        )
        self.db.add_all(
            [
                target_user,
                similar_user,
                unrelated_user,
                target_song,
                recommended_song,
                second_recommended_song,
                unrelated_song,
            ]
        )
        self.db.flush()

        target_clip = models.Clip(song_id=target_song.id, start_time=0, end_time=30)
        recommended_clip = models.Clip(
            song_id=recommended_song.id, start_time=10, end_time=40
        )
        second_recommended_clip = models.Clip(
            song_id=second_recommended_song.id, start_time=15, end_time=45
        )
        unrelated_clip = models.Clip(song_id=unrelated_song.id, start_time=20, end_time=50)
        self.db.add_all(
            [target_clip, recommended_clip, second_recommended_clip, unrelated_clip]
        )
        self.db.flush()
        self.db.add_all(
            [
                models.Interaction(user_id=1, clip_id=target_clip.id, action="like"),
                models.Interaction(user_id=2, clip_id=target_clip.id, action="like"),
                models.Interaction(
                    user_id=2, clip_id=recommended_clip.id, action="complete"
                ),
                models.Interaction(
                    user_id=2, clip_id=second_recommended_clip.id, action="replay"
                ),
                models.Interaction(user_id=3, clip_id=unrelated_clip.id, action="like"),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_similar_users_add_cross_genre_candidates_and_exclude_seen_clips(self):
        target_user = self.db.query(models.User).filter(models.User.id == 1).first()
        first_page = get_personalized_feed(
            limit=1, cursor=None, current_user=target_user, db=self.db
        )

        self.assertEqual(first_page["items"][0]["youtube_id"], "recommended")
        self.assertNotIn("target", [item["youtube_id"] for item in first_page["items"]])
        self.assertIsNotNone(first_page["next_cursor"])

        second_page = get_personalized_feed(
            limit=1, cursor=first_page["next_cursor"], current_user=target_user, db=self.db
        )

        self.assertEqual(
            second_page["items"][0]["youtube_id"], "recommended-2"
        )
        self.assertIsNotNone(second_page["next_cursor"])

        # Clips with no signal for this user still appear, after the scored ones
        third_page = get_personalized_feed(
            limit=1, cursor=second_page["next_cursor"], current_user=target_user, db=self.db
        )
        self.assertEqual(third_page["items"][0]["youtube_id"], "unrelated")
        self.assertIsNone(third_page["next_cursor"])

    def test_skipped_genre_ranks_below_unscored_clips(self):
        target_user = self.db.query(models.User).filter(models.User.id == 1).first()
        rock_song = self.db.query(models.Song).filter(models.Song.genre == "rock").first()
        other_rock_clip = models.Clip(song_id=rock_song.id, start_time=60, end_time=90)
        self.db.add(other_rock_clip)
        self.db.flush()
        unrelated_clip = (
            self.db.query(models.Clip)
            .filter(models.Clip.song_id == rock_song.id, models.Clip.start_time == 20)
            .first()
        )
        self.db.add(models.Interaction(user_id=1, clip_id=unrelated_clip.id, action="skip"))
        self.db.commit()

        feed = get_personalized_feed(limit=10, cursor=None, current_user=target_user, db=self.db)

        # The skipped clip is gone; the other rock clip (negative genre score) comes last
        self.assertEqual(
            [item["clip_id"] for item in feed["items"]][-1], other_rock_clip.id
        )
        self.assertNotIn(unrelated_clip.id, [item["clip_id"] for item in feed["items"]])


if __name__ == "__main__":
    unittest.main()
