import os
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
import models


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


if __name__ == "__main__":
    unittest.main()
