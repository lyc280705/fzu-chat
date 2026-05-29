from __future__ import annotations

import unittest
from uuid import uuid4

from app.auth import create_session, get_session, invalidate_session, update_session


class AuthSessionTests(unittest.TestCase):
    def test_session_round_trip_and_update(self):
        user_id = f"student-{uuid4()}"
        token = create_session(user_id, display_name="测试用户", edu_authenticated=True, edu_cookies=[{"name": "sid", "value": "1"}])
        self.addCleanup(invalidate_session, token)

        session = get_session(token)
        self.assertIsNotNone(session)
        self.assertEqual(session["user_id"], user_id)
        self.assertTrue(session["edu_authenticated"])

        update_session(token, {"edu_authenticated": False, "edu_cookies": None})
        updated = get_session(token)
        self.assertIsNotNone(updated)
        self.assertFalse(updated["edu_authenticated"])
        self.assertIsNone(updated["edu_cookies"])

    def test_invalidate_session_removes_token(self):
        token = create_session(f"student-{uuid4()}")

        invalidate_session(token)

        self.assertIsNone(get_session(token))


if __name__ == "__main__":
    unittest.main()
