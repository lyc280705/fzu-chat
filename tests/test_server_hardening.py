from __future__ import annotations

import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth import create_session, delete_user_storage, get_session, invalidate_session
from app.server import GLOBAL_STREAM_LIMIT, USER_STREAM_LIMIT, app


class ServerHardeningTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_public_openapi_docs_are_disabled_by_default(self):
        self.assertIsNone(app.openapi_url)
        self.assertIsNone(app.docs_url)
        self.assertIsNone(app.redoc_url)

    def test_scanner_paths_return_404_before_spa_fallback(self):
        for path in ("/.git/config", "/.env", "/env", "/containers/json", "/phpunit/vendor/phpunit"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)

    def test_metrics_endpoint_is_restricted(self):
        response = self.client.get("/api/metrics")

        self.assertEqual(response.status_code, 403)

    def test_metrics_endpoint_rejects_public_forwarded_for(self):
        response = self.client.get("/api/metrics", headers={"x-forwarded-for": "8.8.8.8"})

        self.assertEqual(response.status_code, 403)

    def test_health_reports_relaxed_launch_limits(self):
        self.assertEqual(GLOBAL_STREAM_LIMIT, 80)
        self.assertEqual(USER_STREAM_LIMIT, 5)

    def test_delete_account_revokes_all_sessions_and_signs_out(self):
        user_id = f"delete-account-{uuid4()}"
        current_token = create_session(user_id, student_type="visitor")
        second_token = create_session(user_id, student_type="visitor")
        self.addCleanup(invalidate_session, current_token)
        self.addCleanup(invalidate_session, second_token)
        self.addCleanup(delete_user_storage, user_id)
        self.client.cookies.set("fzu_session", current_token)

        response = self.client.delete("/api/account")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["revoked_session_count"], 2)
        self.assertEqual(
            payload["cleared"],
            {"conversation_count": 0, "message_count": 0, "memory_count": 0},
        )
        self.assertIsNone(get_session(current_token))
        self.assertIsNone(get_session(second_token))
        self.assertIsNone(self.client.cookies.get("fzu_session"))


if __name__ == "__main__":
    unittest.main()
