from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

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


if __name__ == "__main__":
    unittest.main()
