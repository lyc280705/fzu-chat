from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from app import auth, server


class EduSessionSyncTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, value in (("_sessions", {}), ("_edu_sessions", {}), ("USERS_DIR", Path(directory.name))):
            self.enterContext(patch.object(auth, name, value))
        self.enterContext(patch.object(auth, "get_redis_client", return_value=None))
        self.enterContext(patch.object(auth, "redis_configured", return_value=False))
        self.enterContext(patch.object(auth, "redis_get_json", return_value=None))
        self.enterContext(patch.object(auth, "redis_set_json", return_value=False))
        self.enterContext(patch.object(auth, "redis_delete", return_value=False))
        self.first = auth.create_session("sync-student")
        self.second = auth.create_session("sync-student")
        self.other = auth.create_session("other-student")
        self.visitor = auth.create_session("sync-student", student_type="visitor")
        self.client = TestClient(server.app)

    def connect(self, cookie="new-session"):
        auth.update_user_edu_session("sync-student", {
            "edu_authenticated": True,
            "edu_cookies": [{"name": "sid", "value": cookie}],
            "edu_identifier": "example",
            "edu_status_message": "",
            "edu_session_expires_at": time.time() + 300,
        })

    def test_reconnect_and_expiry_reach_both_devices_only(self):
        self.connect()
        self.assertTrue(auth.get_session(self.first)["edu_authenticated"])
        self.assertEqual(auth.get_session(self.first)["edu_cookies"], auth.get_session(self.second)["edu_cookies"])
        self.assertFalse(auth.get_session(self.other)["edu_authenticated"])
        self.assertFalse(auth.get_session(self.visitor)["edu_authenticated"])
        server.clear_edu_session(self.first, "连接已过期")
        for token in (self.first, self.second):
            self.assertFalse(auth.get_session(token)["edu_authenticated"])
            self.assertIsNone(auth.get_session(token)["edu_cookies"])
            self.assertEqual(auth.get_session(token)["edu_status_message"], "连接已过期")

    def test_stale_validation_cannot_clear_a_new_connection(self):
        self.connect("old-session")

        def old_validation():
            self.connect("replacement-session")
            raise server.JwchSessionError("old session expired")

        with patch.object(server.JwchClient, "from_cookies", return_value=Mock(validate_session=old_validation)):
            result = server.refresh_edu_session_status(self.first)
        self.assertTrue(result["edu_authenticated"])
        self.assertEqual(auth.get_session(self.second)["edu_cookies"][0]["value"], "replacement-session")

    def test_timeout_sync_is_credential_free(self):
        self.connect()
        state = auth.get_session(self.first)
        auth.update_user_edu_session("sync-student", {**state, "edu_session_expires_at": time.time() - 1})
        snapshot = server.public_auth_sync_state(self.second)
        self.assertFalse(snapshot["edu_authenticated"])
        self.assertEqual(set(snapshot), {"authenticated", "edu_authenticated", "edu_error"})
        self.assertIsNone(auth.get_session(self.first)["edu_cookies"])

    def test_logout_is_device_local_but_account_revocation_purges_shared_credentials(self):
        self.connect()
        self.client.cookies.set("fzu_session", self.first)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertIsNone(auth.get_session(self.first))
        self.assertTrue(auth.get_session(self.second)["edu_authenticated"])
        auth.invalidate_user_sessions("sync-student")
        self.assertIsNone(auth.get_session(self.second))
        self.assertEqual(auth._edu_sessions, {})

    def test_relogin_endpoint_updates_other_device(self):
        fake = Mock(identifier="new-identifier", session=SimpleNamespace(cookies=[SimpleNamespace(name="sid", value="example")]))
        self.client.cookies.set("fzu_session", self.second)
        with patch.object(server, "JwchClient", return_value=fake), patch.object(server, "warm_teaching_week_cache_async"), patch.object(server, "schedule_signal_snapshot_refresh"):
            response = self.client.post("/api/auth/edu-login", json={"password": "test-only-password"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(auth.get_session(self.first)["edu_authenticated"])
        self.assertNotIn("test-only-password", json.dumps(auth.get_session(self.first)))

    def test_event_stream_emits_auth_changes_without_upstream_requests(self):
        async def check():
            request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
            user = server.AuthUser(user_id="sync-student", student_type="undergraduate", display_name="示例", edu_authenticated=False, token=self.first)
            response = await server.stream_conversation_events(request, user)
            stream = response.body_iterator
            try:
                initial = await anext(stream)
                self.assertIn(b'"edu_authenticated": false', initial)
                self.connect()
                # A title event wakes the existing queue without a test-only delay.
                server.publish_conversation_event("sync-student", "title", {})
                await anext(stream)
                changed = await anext(stream)
                self.assertIn(b'"edu_authenticated": true', changed)
                self.assertNotIn(b"edu_cookies", changed)
                self.assertNotIn(b"edu_identifier", changed)
            finally:
                await stream.aclose()
        asyncio.run(check())

    def test_unknown_tool_arguments_are_not_shown_as_json(self):
        self.assertEqual(server.summarize_tool_args({"internal_options": {"debug": True}}), "")
        self.assertEqual(server.summarize_tool_args('{"query":"图书馆开放时间"}'), "图书馆开放时间")
        self.assertEqual(server.summarize_tool_args('{"unfinished":'), "")
        self.assertEqual(server.summarize_tool_args({"query": {"internal": "value"}}), "")


if __name__ == "__main__":
    unittest.main()
