from __future__ import annotations

import unittest
from uuid import uuid4

from app.auth import (
    create_session,
    delete_user_storage,
    get_session,
    invalidate_session,
    invalidate_user_sessions,
    update_session,
    user_dir,
)


class AuthSessionTests(unittest.TestCase):
    def test_session_round_trip_and_update(self):
        user_id = f"student-{uuid4()}"
        token = create_session(user_id, display_name="测试用户", edu_authenticated=True, edu_cookies=[{"name": "sid", "value": "1"}])
        self.addCleanup(invalidate_session, token)
        self.addCleanup(delete_user_storage, user_id)

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
        user_id = f"student-{uuid4()}"
        token = create_session(user_id)
        self.addCleanup(delete_user_storage, user_id)

        invalidate_session(token)

        self.assertIsNone(get_session(token))

    def test_invalidate_user_sessions_revokes_only_matching_user(self):
        user_id = f"student-{uuid4()}"
        other_user_id = f"student-{uuid4()}"
        first_token = create_session(user_id)
        second_token = create_session(user_id)
        other_token = create_session(other_user_id)
        self.addCleanup(delete_user_storage, user_id)
        self.addCleanup(delete_user_storage, other_user_id)
        self.addCleanup(invalidate_session, other_token)

        revoked = invalidate_user_sessions(user_id)

        self.assertEqual(revoked, 2)
        self.assertIsNone(get_session(first_token))
        self.assertIsNone(get_session(second_token))
        self.assertIsNotNone(get_session(other_token))

    def test_delete_user_storage_removes_account_directory(self):
        user_id = f"student-{uuid4()}"
        path = user_dir(user_id)
        (path / "legacy.json").write_text("{}", encoding="utf-8")

        removed = delete_user_storage(user_id)

        self.assertTrue(removed)
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
