import os

# Tests must never touch the real database: force in-memory SQLite before any project import.
os.environ["DATABASE_URL"] = "sqlite://"

import unittest
from datetime import timedelta

import jwt

from auth import (
    ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_access_token,
    verify_password,
)
from make_admin import set_admin
import models
from database import Base, SessionLocal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class AuthTest(unittest.TestCase):
    def test_password_hashing_and_verification(self):
        plain_password = "super-secret-password-123"
        hashed = hash_password(plain_password)

        self.assertNotEqual(plain_password, hashed)
        self.assertTrue(verify_password(plain_password, hashed))
        self.assertFalse(verify_password("wrong-password", hashed))

        # Salt randomness check
        second_hashed = hash_password(plain_password)
        self.assertNotEqual(hashed, second_hashed)
        self.assertTrue(verify_password(plain_password, second_hashed))

    def test_invalid_hash_verification(self):
        self.assertFalse(verify_password("test", "invalid_hash_string"))

    def test_jwt_encode_and_decode(self):
        payload = {"sub": "tanmay", "user_id": 1}
        token = create_access_token(payload, expires_delta=timedelta(minutes=15))

        decoded = decode_access_token(token)
        self.assertEqual(decoded["sub"], "tanmay")
        self.assertEqual(decoded["user_id"], 1)
        self.assertIn("exp", decoded)

        # verify_access_token helper
        verified = verify_access_token(token)
        self.assertIsNotNone(verified)
        self.assertEqual(verified["sub"], "tanmay")

    def test_jwt_expired_token(self):
        payload = {"sub": "tanmay"}
        token = create_access_token(payload, expires_delta=timedelta(seconds=-10))

        with self.assertRaises(jwt.ExpiredSignatureError):
            decode_access_token(token)

        self.assertIsNone(verify_access_token(token))

    def test_jwt_invalid_token(self):
        invalid_token = "invalid.token.structure"
        with self.assertRaises(jwt.PyJWTError):
            decode_access_token(invalid_token)

        self.assertIsNone(verify_access_token(invalid_token))

    def test_user_model_has_auth_fields(self):
        user_columns = {c.name: c for c in models.User.__table__.columns}
        self.assertIn("id", user_columns)
        self.assertIn("username", user_columns)
        self.assertIn("hashed_password", user_columns)

    def test_set_admin_create_and_update(self):
        engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        TestingSession = sessionmaker(bind=engine)
        db = TestingSession()

        # 1. Non-existent user without password returns False
        self.assertFalse(set_admin("admin_user", is_admin=True, db=db))

        # 2. Non-existent user with password creates admin user
        self.assertTrue(set_admin("admin_user", is_admin=True, password="secretpassword", db=db))
        user = db.query(models.User).filter(models.User.username == "admin_user").first()
        self.assertIsNotNone(user)
        self.assertTrue(user.is_admin)
        self.assertTrue(verify_password("secretpassword", user.hashed_password))

        # 3. Revoke admin
        self.assertTrue(set_admin("admin_user", is_admin=False, db=db))
        db.refresh(user)
        self.assertFalse(user.is_admin)

        db.close()


if __name__ == "__main__":
    unittest.main()
