"""Account-free integration checks; school and model calls are synthetic."""

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from app import auth, campus_recommendations, edu_tools, graph, server
from app.edu_identity import education_user_id
from app.yjsy_client import COURSES_URL, EXAM_ROOMS_URL, TERMS_URL, SUPPORTED_TOOLS
from test_yjsy_client import content_table, course_row, login_response, marks_page, response


class GraduateIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, value in (("_sessions", {}), ("_edu_sessions", {}), ("USERS_DIR", Path(directory.name))):
            self.enterContext(patch.object(auth, name, value))
        for name, value in (("get_redis_client", None), ("redis_configured", False), ("redis_get_json", None),
                            ("redis_set_json", False), ("redis_delete", False)):
            self.enterContext(patch.object(auth, name, return_value=value))
        self.enterContext(patch.object(server, "_enforce_rate_limit"))
        self.enterContext(patch.object(server, "_acquire_edu_login_slot", return_value=object()))
        self.enterContext(patch.object(server, "release_slot"))
        self.enterContext(patch.object(server, "warm_teaching_week_cache_async"))
        self.enterContext(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("unexpected live network")))
        edu_tools.set_current_edu_session(None)
        self.addCleanup(edu_tools.set_current_edu_session, None)
        self.client = TestClient(server.app)
        self.addCleanup(self.client.close)

    def login(self):
        with patch.object(requests.Session, "post", return_value=login_response()):
            result = self.client.post("/api/auth/login", json={
                "student_id": "synthetic-001", "password": "synthetic-password", "student_type": "graduate", "accepted_legal": True,
            })
        self.assertEqual(result.status_code, 200, result.text)
        token = self.client.cookies.get(server.AUTH_COOKIE_NAME)
        return result.json(), token, auth.get_session(token)

    def test_login_session_tools_and_public_profile_end_to_end(self):
        payload, token, session = self.login()
        self.assertEqual(payload["user"]["student_type"], "graduate")
        self.assertEqual(payload["user"]["student_id"], "synthetic-001")
        self.assertEqual(session["user_id"], "graduate:synthetic-001")
        self.assertNotIn("synthetic-password", json.dumps(session))
        self.assertNotIn("edu_cookies", json.dumps(payload))
        self.assertTrue(session["edu_authenticated"])
        tools = {tool.name: tool for tool in edu_tools.build_edu_tools(session)}
        self.assertEqual(set(tools), SUPPORTED_TOOLS)
        with patch.object(requests.Session, "get", return_value=response(marks_page())):
            public = self.client.get("/api/auth/me").json()
            content, artifact = tools["query_grades"].func("")
        self.assertEqual(public["student_id"], "synthetic-001")
        self.assertTrue(public["edu_authenticated"])
        self.assertEqual(artifact[0]["score"], "88")
        self.assertNotIn("绩点", content)
        self.assertNotIn("edu_cookies", public)
        self.assertEqual(auth.get_session(token)["edu_identifier"], "")

    def test_same_school_id_isolated_from_undergraduate_and_visitor(self):
        undergraduate = auth.create_session("synthetic-001")
        auth.update_user_edu_session("synthetic-001", {"edu_authenticated": True, "edu_cookies": [{"name": "sid", "value": "undergrad"}]})
        payload, _, graduate = self.login()
        visitor = auth.create_session(graduate["user_id"], student_type="visitor")
        self.assertEqual(auth.get_session(undergraduate)["edu_cookies"][0]["value"], "undergrad")
        self.assertNotEqual(auth.user_dir("synthetic-001"), auth.user_dir(graduate["user_id"]))
        self.assertFalse(auth.get_session(visitor)["edu_authenticated"])
        self.assertEqual(edu_tools.build_edu_tools(auth.get_session(visitor)), [])
        self.assertEqual(payload["user"]["display_name"], "synthetic-001")

    def test_reconnect_updates_both_graduate_devices_using_original_student_id(self):
        _, token, session = self.login()
        other_token = auth.create_session(session["user_id"], student_type="graduate", display_name="synthetic-001")
        server.clear_edu_session(token, "连接已过期")
        with patch.object(requests.Session, "post", return_value=login_response("replacement")) as post:
            result = self.client.post("/api/auth/edu-login", json={"password": "new-synthetic-password"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(post.call_args.kwargs["data"]["muser"], "synthetic-001")
        for current in (token, other_token):
            self.assertTrue(auth.get_session(current)["edu_authenticated"])
            self.assertEqual(auth.get_session(current)["edu_cookies"][0]["value"], "replacement")
            self.assertNotIn("new-synthetic-password", json.dumps(auth.get_session(current)))

    def test_http_200_expiry_clears_shared_credentials_on_all_devices(self):
        _, token, session = self.login()
        other = auth.create_session(session["user_id"], student_type="graduate")
        with patch.object(requests.Session, "get", return_value=response("<script>当前登录用户已过期</script>")):
            public = self.client.get("/api/auth/me")
        self.assertFalse(public.json()["edu_authenticated"])
        for current in (token, other):
            self.assertIsNone(auth.get_session(current)["edu_cookies"])

    def test_timeout_and_stale_revision_behave_like_undergraduate_sync(self):
        _, token, session = self.login()
        auth.update_user_edu_session(session["user_id"], {**session, "edu_session_expires_at": time.time() - 1})
        self.assertFalse(server.public_auth_sync_state(token)["edu_authenticated"])
        with patch.object(requests.Session, "post", return_value=login_response("replacement")):
            self.client.post("/api/auth/edu-login", json={"password": "synthetic-password"})
        server.clear_edu_session(token, "stale failure", expected_revision=session["edu_revision"])
        self.assertTrue(auth.get_session(token)["edu_authenticated"])

    def test_failed_login_and_unknown_provider_never_create_session(self):
        body = {"student_id": "synthetic-001", "password": "synthetic-password", "student_type": "graduate", "accepted_legal": True}
        with patch.object(requests.Session, "post", return_value=response("登录失败")):
            self.assertEqual(self.client.post("/api/auth/login", json=body).status_code, 401)
        self.assertEqual(auth._sessions, {})
        self.assertEqual(auth._edu_sessions, {})
        body["student_type"] = "teacher"
        self.assertEqual(self.client.post("/api/auth/login", json=body).status_code, 422)

    def test_only_supported_tools_and_prompt_are_bound_to_model(self):
        _, _, session = self.login()
        model = Mock()
        model.bind_tools.return_value.invoke.return_value = AIMessage(content="synthetic response")
        context = {**session, "runtime_system_context": "synthetic runtime"}
        tools = edu_tools.build_edu_tools(context)
        with patch.object(graph, "build_chat_llm", return_value=model):
            handler = graph._build_query_or_respond(tools, [], [], context)
            handler({"messages": [HumanMessage(content="查成绩")]}, {})
        names = {tool.name for tool in model.bind_tools.call_args.args[0]}
        self.assertTrue(SUPPORTED_TOOLS.issubset(names))
        self.assertFalse({"select_course", "query_gpa_ranking", "query_cultivate_plan", "query_academic_calendar"} & names)
        prompt = model.bind_tools.return_value.invoke.call_args.args[0][0].content
        self.assertIn("研究生教务查询", prompt)
        self.assertNotIn("select_course:", prompt)
        self.assertIn("不套用本科接口或本科绩点算法", prompt)

    def test_semester_course_query_keeps_raw_term_and_does_not_call_undergraduate(self):
        _, _, session = self.login()
        terms = content_table(course_row("2026-2027-1") + course_row("2025-2026-2"))
        courses = content_table(course_row("2025-2026-2"))
        with patch.object(requests.Session, "get", side_effect=[response(terms), response(courses)]) as get:
            text, data = edu_tools._query_courses_impl("上学期课表", session)
        self.assertEqual(data[0]["semester"], "2025-2026-2")
        self.assertIn("示例课程一", text)
        self.assertEqual(get.call_args_list[0].args, (TERMS_URL,))
        self.assertEqual(get.call_args_list[1].args, (COURSES_URL,))
        self.assertEqual(get.call_args_list[1].kwargs["params"], {"strwhere": "XNXQ='2025-2026-2'"})

    def test_graduate_never_enters_undergraduate_recommendation_client(self):
        _, _, session = self.login()
        with patch.object(campus_recommendations, "JwchClient") as jwch, patch.object(server, "acquire_dedupe_lock") as lock:
            self.assertIsNone(campus_recommendations._build_client(session))
            server.schedule_signal_snapshot_refresh(session["user_id"], session)
        jwch.assert_not_called()
        lock.assert_not_called()

    def test_full_year_term_with_zero_padded_suffix_is_never_normalized_as_undergraduate(self):
        _, _, session = self.login()
        html = marks_page().replace("2026-2027-1", "2026-2027-01")
        with patch.object(requests.Session, "get", return_value=response(html)):
            content, marks = edu_tools._query_grades_impl("查询2026-2027-01成绩", session)
        self.assertEqual(len(marks), 2)
        self.assertIn("2026-2027-01", content)
        terms = content_table(course_row("2026-2027-01"))
        exams = content_table('<tr><td>1</td><td>示例考试</td><td></td><td></td><td>2027/01/05 09:00-11:00</td><td>东3-109</td></tr>')
        with patch.object(requests.Session, "get", side_effect=[response(terms), response(exams)]) as get:
            _, artifact = edu_tools._query_exam_rooms_impl("2026-2027-01考场", session)
        self.assertEqual(artifact["term"], "2026-2027-01")
        self.assertEqual(get.call_args.args, (EXAM_ROOMS_URL,))
        self.assertEqual(get.call_args.kwargs["params"], {"strwhere": "XNXQ='2026-2027-01'"})

    def test_initial_login_and_reconnect_share_one_account_attempt_budget(self):
        with patch.object(server, "_enforce_rate_limit") as limit:
            self.login()
            with patch.object(requests.Session, "post", return_value=login_response()):
                self.client.post("/api/auth/edu-login", json={"password": "synthetic-password"})
        graduate_calls = [call for call in limit.call_args_list if call.args[0].startswith("graduate-edu-login:")]
        self.assertEqual(len(graduate_calls), 2)
        self.assertEqual(graduate_calls[0].args, graduate_calls[1].args)
        self.assertEqual(graduate_calls[0].args[1:3], (5, 1800))

    def test_undergraduate_tools_and_client_remain_available(self):
        session = {"user_id": "synthetic-001", "student_type": "undergraduate", "edu_authenticated": True, "edu_cookies": []}
        self.assertIn("select_course", {t.name for t in edu_tools.build_edu_tools(session)})
        with patch.object(edu_tools.JwchClient, "from_cookies", return_value="undergraduate") as factory:
            self.assertEqual(edu_tools._build_client(session), "undergraduate")
        factory.assert_called_once_with("synthetic-001", [], "")
        self.assertEqual(education_user_id("synthetic-001", "undergraduate"), "synthetic-001")


if __name__ == "__main__":
    unittest.main()
