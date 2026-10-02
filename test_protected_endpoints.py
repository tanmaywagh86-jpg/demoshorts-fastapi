import os
import unittest
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
from database import Base, get_db
from main import app
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


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class ProtectedEndpointsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)

    def setUp(self):
        Base.metadata.drop_all(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        db = TestingSessionLocal()
        user_a = models.User(
            username="user_a",
            hashed_password=auth.hash_password("pass_a"),
        )
        user_b = models.User(
            username="user_b",
            hashed_password=auth.hash_password("pass_b"),
        )
        song_pop = models.Song(
            title="Pop Song",
            artist="Pop Artist",
            youtube_id="pop_yt",
            genre="pop",
        )
        song_rock = models.Song(
            title="Rock Song",
            artist="Rock Artist",
            youtube_id="rock_yt",
            genre="rock",
        )
        db.add_all([user_a, user_b, song_pop, song_rock])
        db.flush()

        clip_pop_1 = models.Clip(song_id=song_pop.id, start_time=0, end_time=30)
        clip_pop_2 = models.Clip(song_id=song_pop.id, start_time=30, end_time=60)
        clip_rock = models.Clip(song_id=song_rock.id, start_time=0, end_time=30)
        db.add_all([clip_pop_1, clip_pop_2, clip_rock])
        db.flush()

        # User A likes clip_pop_1 (establishing affinity for 'pop')
        db.add(models.Interaction(user_id=user_a.id, clip_id=clip_pop_1.id, action="like"))
        db.commit()

        self.user_a_id = user_a.id
        self.user_b_id = user_b.id
        self.clip_pop_1_id = clip_pop_1.id
        self.clip_pop_2_id = clip_pop_2.id
        self.clip_rock_id = clip_rock.id
        db.close()

        # Generate JWT tokens
        self.token_a = auth.create_access_token(
            {"sub": str(self.user_a_id), "username": "user_a"}
        )
        self.token_b = auth.create_access_token(
            {"sub": str(self.user_b_id), "username": "user_b"}
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    # 1. Valid token works
    def test_valid_token_allows_interaction_and_feed(self):
        # Post interaction with valid token
        response = self.client.post(
            "/interactions",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"clip_id": self.clip_rock_id, "action": "like"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["user_id"], self.user_a_id)
        self.assertEqual(data["clip_id"], self.clip_rock_id)
        self.assertEqual(data["action"], "like")

        # Get personalized feed with valid token
        feed_resp = self.client.get(
            "/feed/personalized",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(feed_resp.status_code, 200)
        feed_data = feed_resp.json()
        self.assertIn("items", feed_data)

    # 2. Missing token returns 401
    def test_missing_token_returns_401(self):
        # /interactions without Authorization header
        resp_inter = self.client.post(
            "/interactions",
            json={"clip_id": self.clip_pop_2_id, "action": "like"},
        )
        self.assertEqual(resp_inter.status_code, 401)
        self.assertIn("Missing authentication token", resp_inter.json()["detail"])

        # /feed/personalized without Authorization header
        resp_feed = self.client.get("/feed/personalized")
        self.assertEqual(resp_feed.status_code, 401)
        self.assertIn("Missing authentication token", resp_feed.json()["detail"])

    # 3. Invalid / expired token returns 401
    def test_invalid_and_expired_token_returns_401(self):
        # Invalid token
        resp_invalid = self.client.get(
            "/feed/personalized",
            headers={"Authorization": "Bearer invalid.token.value"},
        )
        self.assertEqual(resp_invalid.status_code, 401)
        self.assertIn("Invalid or expired", resp_invalid.json()["detail"])

        # Expired token
        expired_token = auth.create_access_token(
            {"sub": str(self.user_a_id), "username": "user_a"},
            expires_delta=timedelta(seconds=-10),
        )
        resp_expired = self.client.post(
            "/interactions",
            headers={"Authorization": f"Bearer {expired_token}"},
            json={"clip_id": self.clip_pop_2_id, "action": "like"},
        )
        self.assertEqual(resp_expired.status_code, 401)
        self.assertIn("Invalid or expired", resp_expired.json()["detail"])

    # 4. User A cannot submit an interaction as User B
    def test_user_a_cannot_submit_interaction_as_user_b(self):
        # Interaction is bound strictly to authenticated User A
        response = self.client.post(
            "/interactions",
            headers={"Authorization": f"Bearer {self.token_a}"},
            json={"clip_id": self.clip_pop_2_id, "action": "replay"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["user_id"], self.user_a_id)
        self.assertEqual(data["clip_id"], self.clip_pop_2_id)
        self.assertEqual(data["action"], "replay")
        self.assertIn("id", data)

    # 5. Personalized feed uses the authenticated user
    def test_personalized_feed_uses_authenticated_user(self):
        # User A has liked clip_pop_1 (pop). Feed recommends unseen clip_pop_2 (pop) and excludes seen clip_pop_1
        resp_a = self.client.get(
            "/feed/personalized",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(resp_a.status_code, 200)
        items_a = resp_a.json()["items"]
        recommended_clip_ids_a = [item["clip_id"] for item in items_a]

        # Seen clip is excluded
        self.assertNotIn(self.clip_pop_1_id, recommended_clip_ids_a)
        # Unseen pop clip is recommended based on user A's genre affinity
        self.assertIn(self.clip_pop_2_id, recommended_clip_ids_a)

        # User B has no interactions yet, so no recommendations are generated
        resp_b = self.client.get(
            "/feed/personalized",
            headers={"Authorization": f"Bearer {self.token_b}"},
        )
        self.assertEqual(resp_b.status_code, 200)
        items_b = resp_b.json()["items"]
        self.assertEqual(len(items_b), 0)


if __name__ == "__main__":
    unittest.main()
