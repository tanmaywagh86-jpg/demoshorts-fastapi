import os
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
from database import Base
from main import app, get_db
import models

# Setup isolated in-memory SQLite engine with StaticPool
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=test_engine
)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class AuthEndpointsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)

    def setUp(self):
        Base.metadata.drop_all(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_successful_registration(self):
        response = self.client.post(
            "/auth/register",
            json={"username": "alice", "password": "securepassword123"},
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["username"], "alice")
        self.assertIn("id", data)
        self.assertNotIn("hashed_password", data)
        self.assertNotIn("password", data)

        # Verify password is saved hashed in database
        db = TestingSessionLocal()
        user = db.query(models.User).filter(models.User.username == "alice").first()
        self.assertIsNotNone(user)
        self.assertNotEqual(user.hashed_password, "securepassword123")
        self.assertTrue(auth.verify_password("securepassword123", user.hashed_password))
        db.close()

    def test_duplicate_registration_returns_409(self):
        # First registration
        res1 = self.client.post(
            "/auth/register",
            json={"username": "bob", "password": "password123"},
        )
        self.assertEqual(res1.status_code, 201)

        # Second registration with same username
        res2 = self.client.post(
            "/auth/register",
            json={"username": "bob", "password": "differentpassword"},
        )
        self.assertEqual(res2.status_code, 409)
        self.assertIn("already exists", res2.json()["detail"])

    def test_successful_login(self):
        # Register user
        self.client.post(
            "/auth/register",
            json={"username": "charlie", "password": "mypassword123"},
        )

        # Login
        response = self.client.post(
            "/auth/login",
            json={"username": "charlie", "password": "mypassword123"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["token_type"], "bearer")

        # Verify token validity
        decoded = auth.decode_access_token(data["access_token"])
        self.assertEqual(decoded["username"], "charlie")
        self.assertIn("sub", decoded)

    def test_invalid_login_wrong_password(self):
        self.client.post(
            "/auth/register",
            json={"username": "david", "password": "correctpassword"},
        )

        response = self.client.post(
            "/auth/login",
            json={"username": "david", "password": "wrongpassword"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid username or password")

    def test_invalid_login_nonexistent_user(self):
        response = self.client.post(
            "/auth/login",
            json={"username": "nonexistent_user", "password": "anypassword"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid username or password")


if __name__ == "__main__":
    unittest.main()
