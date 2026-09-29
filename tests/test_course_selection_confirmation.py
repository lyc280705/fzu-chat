from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app import auth, edu_tools, server
from app.chat_store import ChatStore
from app.jwch_client import JwchClient, JwchError


COURSE = {"course_name": "机器学习", "teacher": "示例教师", "credits": "3.0", "schedule": "周一 1-2 节"}


class FakePreviewClient:
    def __init__(self):
        self.preview_calls = []

    def preview_course_selection(self, **kwargs):
        self.preview_calls.append(kwargs)
        return {"category": "semester", "category_label": "学期选课", "course": dict(COURSE), "points": kwargs.get("points", "")}

    def select_course(self, **kwargs):
        raise AssertionError("the tool must never submit a selection")


class SelectCourseToolTests(unittest.TestCase):
    def test_tool_creates_pending_request_without_submitting(self):
        fake = FakePreviewClient()
        with patch.object(edu_tools, "_build_client", return_value=fake):
            content, artifact = edu_tools._request_course_selection_impl("学期选课", "机器学习", "示例教师")

        self.assertEqual(len(fake.preview_calls), 1)
        self.assertEqual(artifact["mode"], "select_request")
        self.assertEqual(artifact["status"], "pending_confirmation")
        self.assertEqual(artifact["category"], "semester")
        self.assertEqual(artifact["course_name"], "机器学习")
        self.assertEqual(artifact["teacher"], "示例教师")
        self.assertGreater(datetime.fromisoformat(artifact["expires_at"]), datetime.now(timezone.utc))
        self.assertIn("尚未提交", content)
        self.assertIn("不要声称已经选上", content)

    def test_tool_reports_preview_errors_without_artifact(self):
        fake = FakePreviewClient()
        fake.preview_course_selection = Mock(side_effect=JwchError("学期选课当前不可提交选课"))
        with patch.object(edu_tools, "_build_client", return_value=fake):
            content, artifact = edu_tools._request_course_selection_impl("学期选课", "机器学习")

        self.assertIsNone(artifact)
        self.assertIn("不可提交", content)

    def test_bound_tool_description_says_it_does_not_submit(self):
        select_tool = next(t for t in edu_tools.build_edu_tools({}) if t.name == "select_course")
        self.assertIn("不会提交", select_tool.description)


class PreviewCourseSelectionTests(unittest.TestCase):
    def test_preview_only_uses_read_requests(self):
        client = JwchClient.__new__(JwchClient)
        client._logged_in = True
        requests_made = []

        def fake_request(path, data=None, referer="", allow_redirects=False):
            requests_made.append(data)
            return SimpleNamespace(text="<form></form>", url="https://jwch.example/list")

        candidate = {**COURSE, "controls": [{"type": "radio", "name": "pick", "value": "1"}]}
        with patch.object(client, "get_course_selection_overview", return_value={"categories": [{"key": "semester", "status": "open"}]}), \
                patch.object(client, "_selection_request", side_effect=fake_request), \
                patch.object(client, "_parse_selection_candidates", return_value=[candidate]), \
                patch.object(client, "_selection_form_defaults", return_value=({}, "submit", "确定选课")):
            preview = client.preview_course_selection("学期选课", "机器学习", "示例教师")

        self.assertEqual(preview["course"]["course_name"], "机器学习")
        self.assertTrue(requests_made)
        self.assertTrue(all(data is None for data in requests_made))


class CourseSelectionConfirmationEndpointTests(unittest.TestCase):
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
        self.store = ChatStore(Path(directory.name) / "chat.sqlite")
        self.enterContext(patch.object(server, "chat_store", self.store))
        self.enterContext(patch.object(server, "refresh_edu_session_status", side_effect=auth.get_session))
        self.submit = Mock(return_value=("## 选课提交结果", {"status": "success", "message": "已在学期选课中选上《机器学习》", "course": dict(COURSE), "alerts": []}))
        self.enterContext(patch.object(server, "submit_confirmed_course_selection", self.submit))
        self.user_id = f"student-{uuid4()}"
        self.token = auth.create_session(self.user_id)
        auth.update_user_edu_session(self.user_id, {
            "edu_authenticated": True,
            "edu_cookies": [{"name": "sid", "value": "cookie"}],
            "edu_identifier": "example",
            "edu_status_message": "",
            "edu_session_expires_at": time.time() + 300,
        })
        self.client = TestClient(server.app)
        self.client.cookies.set("fzu_session", self.token, domain="testserver.local", path="/")

    def make_request(self, user_id=None, expires_in=600, status="pending_confirmation"):
        user_id = user_id or self.user_id
        now = datetime.now(timezone.utc)
        cid, mid, tool_id = str(uuid4()), str(uuid4()), f"call_{uuid4().hex[:8]}"
        self.store.create_conversation(user_id, {
            "id": cid, "title": "选课", "model": "glm", "thread_id": str(uuid4()),
            "created_at": now.isoformat(), "updated_at": now.isoformat(),
        })
        data = {
            "mode": "select_request", "status": status, "proposal_id": str(uuid4()),
            "category": "semester", "category_label": "学期选课",
            "course_name": "机器学习", "teacher": "示例教师", "points": "", "course": dict(COURSE),
            "created_at": now.isoformat(), "expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
        }
        part = {"type": "tool", "tool_id": tool_id, "tool_name": "select_course", "status": "complete",
                "status_label": "选课待确认", "raw_content": "尚未提交", "data": data}
        self.store.append_message(user_id, cid, {
            "id": mid, "role": "assistant", "content": "请确认", "timestamp": now.isoformat(), "parts": [part],
        })
        return cid, mid, tool_id

    def post(self, cid, mid, tool_id, action, **extra):
        return self.client.post(f"/api/conversations/{cid}/course-selections/{tool_id}", json={"message_id": mid, "action": action, **extra})

    def stored_data(self, cid, user_id=None):
        conversation = self.store.get_conversation(user_id or self.user_id, cid)
        return conversation["messages"][0]["parts"][0]

    def test_confirm_submits_once_with_stored_parameters(self):
        cid, mid, tool_id = self.make_request()

        first = self.post(cid, mid, tool_id, "confirm", course_name="别的课", category="重修")
        second = self.post(cid, mid, tool_id, "confirm")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["part"]["data"]["status"], "success")
        self.assertEqual(second.status_code, 200)
        self.submit.assert_called_once()
        submitted, edu_ctx = self.submit.call_args.args
        self.assertEqual(submitted["course_name"], "机器学习")
        self.assertEqual(submitted["category"], "semester")
        self.assertTrue(edu_ctx["edu_authenticated"])
        stored = self.stored_data(cid)
        self.assertEqual(stored["data"]["status"], "success")
        self.assertEqual(stored["raw_content"], "## 选课提交结果")

    def test_dismissed_request_cannot_be_confirmed(self):
        cid, mid, tool_id = self.make_request()

        dismissed = self.post(cid, mid, tool_id, "dismiss")
        confirmed = self.post(cid, mid, tool_id, "confirm")

        self.assertEqual(dismissed.json()["part"]["data"]["status"], "dismissed")
        self.assertEqual(confirmed.status_code, 409)
        self.submit.assert_not_called()

    def test_expired_request_is_not_submitted(self):
        cid, mid, tool_id = self.make_request(expires_in=-1)

        response = self.post(cid, mid, tool_id, "confirm")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(self.stored_data(cid)["data"]["status"], "expired")
        self.submit.assert_not_called()

    def test_other_users_request_is_not_found(self):
        other_user = f"student-{uuid4()}"
        cid, mid, tool_id = self.make_request(user_id=other_user)

        response = self.post(cid, mid, tool_id, "confirm")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.stored_data(cid, other_user)["data"]["status"], "pending_confirmation")
        self.submit.assert_not_called()

    def test_disconnected_edu_session_keeps_request_pending(self):
        auth.update_user_edu_session(self.user_id, {"edu_authenticated": False, "edu_cookies": None, "edu_status_message": "已过期"})
        cid, mid, tool_id = self.make_request()

        response = self.post(cid, mid, tool_id, "confirm")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.stored_data(cid)["data"]["status"], "pending_confirmation")
        self.submit.assert_not_called()

    def test_visitor_cannot_confirm(self):
        visitor_id = f"visitor-{uuid4()}"
        token = auth.create_session(visitor_id, student_type="visitor")
        self.client.cookies.set("fzu_session", token, domain="testserver.local", path="/")
        cid, mid, tool_id = self.make_request(user_id=visitor_id)

        response = self.post(cid, mid, tool_id, "confirm")

        self.assertEqual(response.status_code, 403)
        self.submit.assert_not_called()

    def test_concurrent_confirmation_is_rejected_while_locked(self):
        cid, mid, tool_id = self.make_request()

        with patch.object(server, "acquire_dedupe_lock", return_value=False):
            response = self.post(cid, mid, tool_id, "confirm")

        self.assertEqual(response.status_code, 409)
        self.submit.assert_not_called()

    def test_submission_error_is_recorded(self):
        self.submit.side_effect = JwchError("学期选课当前不可提交选课")
        cid, mid, tool_id = self.make_request()

        response = self.post(cid, mid, tool_id, "confirm")

        self.assertEqual(response.status_code, 200)
        data = response.json()["part"]["data"]
        self.assertEqual(data["status"], "error")
        self.assertIn("不可提交", data["message"])

    def test_non_request_parts_cannot_be_confirmed(self):
        cid, mid, tool_id = self.make_request()
        conversation = self.store.get_conversation(self.user_id, cid)
        parts = conversation["messages"][0]["parts"]
        parts[0]["data"]["mode"] = "submit"
        self.store.update_message_parts(self.user_id, cid, mid, parts)

        response = self.post(cid, mid, tool_id, "confirm")

        self.assertEqual(response.status_code, 404)
        self.submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
