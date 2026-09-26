import os
import unittest

os.environ["DATABASE_URL"] = "sqlite://"

import models
from database import Base, SessionLocal, engine
from main import get_personalized_feed


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
        first_page = get_personalized_feed(
            user_id=1, limit=1, cursor=None, db=self.db
        )

        self.assertEqual(first_page["items"][0]["youtube_id"], "recommended")
        self.assertNotIn("target", [item["youtube_id"] for item in first_page["items"]])
        self.assertIsNotNone(first_page["next_cursor"])

        second_page = get_personalized_feed(
            user_id=1, limit=1, cursor=first_page["next_cursor"], db=self.db
        )

        self.assertEqual(
            second_page["items"][0]["youtube_id"], "recommended-2"
        )
        self.assertIsNone(second_page["next_cursor"])


if __name__ == "__main__":
    unittest.main()
