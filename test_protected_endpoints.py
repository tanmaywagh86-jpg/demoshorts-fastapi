import os

# Tests must never touch the real database: force in-memory SQLite before any project import.
os.environ["DATABASE_URL"] = "sqlite://"

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
            is_admin=True,
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

        # User B has no interactions yet (cold start): they still get every clip, in clip order
        resp_b = self.client.get(
            "/feed/personalized",
            headers={"Authorization": f"Bearer {self.token_b}"},
        )
        self.assertEqual(resp_b.status_code, 200)
        items_b = resp_b.json()["items"]
        self.assertEqual(
            [item["clip_id"] for item in items_b],
            [self.clip_pop_1_id, self.clip_pop_2_id, self.clip_rock_id],
        )

    # 6. Cold-start feed paginates without repeating or losing clips
    def test_cold_start_feed_paginates(self):
        seen = []
        cursor = None
        for _ in range(5):
            params = {"limit": 2}
            if cursor is not None:
                params["cursor"] = cursor
            resp = self.client.get(
                "/feed/personalized",
                headers={"Authorization": f"Bearer {self.token_b}"},
                params=params,
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            seen.extend(item["clip_id"] for item in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(seen, [self.clip_pop_1_id, self.clip_pop_2_id, self.clip_rock_id])

    # 7. Repeating the same action on a clip does not create a second record
    def test_repeated_interaction_is_not_duplicated(self):
        headers = {"Authorization": f"Bearer {self.token_a}"}
        payload = {"clip_id": self.clip_rock_id, "action": "like"}
        first = self.client.post("/interactions", headers=headers, json=payload)
        second = self.client.post("/interactions", headers=headers, json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])

        db = TestingSessionLocal()
        count = (
            db.query(models.Interaction)
            .filter(
                models.Interaction.user_id == self.user_a_id,
                models.Interaction.clip_id == self.clip_rock_id,
            )
            .count()
        )
        db.close()
        self.assertEqual(count, 1)

    # 8. "save" is accepted and counts as a positive signal for the genre
    def test_save_action_is_accepted_and_boosts_genre(self):
        resp = self.client.post(
            "/interactions",
            headers={"Authorization": f"Bearer {self.token_b}"},
            json={"clip_id": self.clip_pop_1_id, "action": "save"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"], "save")

        feed = self.client.get(
            "/feed/personalized",
            headers={"Authorization": f"Bearer {self.token_b}"},
        ).json()["items"]
        self.assertEqual(
            [item["clip_id"] for item in feed], [self.clip_pop_2_id, self.clip_rock_id]
        )

    # 9. Creating a song needs an admin login; listing songs works
    def test_song_creation_requires_admin_and_listing_works(self):
        payload = {"youtube_id": "new_yt_0001", "title": "New", "artist": "Someone"}

        anonymous = self.client.post("/songs", json=payload)
        self.assertEqual(anonymous.status_code, 401)

        # user_b is logged in but not an admin
        non_admin = self.client.post(
            "/songs", headers={"Authorization": f"Bearer {self.token_b}"}, json=payload
        )
        self.assertEqual(non_admin.status_code, 403)
        self.assertIn("Admin access required", non_admin.json()["detail"])

        created = self.client.post(
            "/songs", headers={"Authorization": f"Bearer {self.token_a}"}, json=payload
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["youtube_id"], "new_yt_0001")

        listing = self.client.get("/api/songs")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(
            [song["youtube_id"] for song in listing.json()],
            ["pop_yt", "rock_yt", "new_yt_0001"],
        )

        # The broken legacy creation endpoint is gone
        self.assertEqual(self.client.post("/api/songs", json=payload).status_code, 405)

    # 10. Admin rights come only from make_admin, never from registration
    def test_admin_is_granted_by_script_not_by_registration(self):
        from make_admin import set_admin

        registered = self.client.post(
            "/auth/register",
            json={"username": "sneaky", "password": "pass_s", "is_admin": True},
        )
        self.assertEqual(registered.status_code, 201)
        token = self.client.post(
            "/auth/login", json={"username": "sneaky", "password": "pass_s"}
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"youtube_id": "new_yt_0002", "title": "New", "artist": "Someone"}

        self.assertEqual(
            self.client.post("/songs", headers=headers, json=payload).status_code, 403
        )

        db = TestingSessionLocal()
        self.assertFalse(set_admin("nobody_here", True, db=db))
        self.assertTrue(set_admin("sneaky", True, db=db))
        db.close()
        self.assertEqual(
            self.client.post("/songs", headers=headers, json=payload).status_code, 200
        )

        db = TestingSessionLocal()
        self.assertTrue(set_admin("sneaky", False, db=db))
        db.close()
        payload["youtube_id"] = "new_yt_0003"
        self.assertEqual(
            self.client.post("/songs", headers=headers, json=payload).status_code, 403
        )


if __name__ == "__main__":
    unittest.main()
