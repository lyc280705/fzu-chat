"""Synthetic protocol fixtures derived from yjsy v0.0.11, not real student pages.

Every network operation is mocked. These checks do not prove live login success.
"""

import base64
import unittest
from unittest.mock import patch

import requests

from app.jwch_client import JwchLoginError, JwchSessionError
from app.yjsy_client import (
    BASE_URL, COURSES_URL, EXAM_ROOMS_URL, LOGIN_URL, MARKS_URL, ORIGIN,
    REFERER, STUDENT_INFO_URL, TERMS_URL, USER_AGENT, YjsyClient, YjsyError,
)


def response(html="", status=200):
    result = requests.Response()
    result.status_code = status
    result._content = html.encode("utf-8")
    result.url = LOGIN_URL
    result.headers["Content-Type"] = "text/html; charset=utf-8"
    return result


def login_response(value="synthetic-auth"):
    result = response(status=302)
    result.headers["Location"] = "/Index.aspx"
    result.cookies.set(".ASPXAUTH", value, path="/", domain="yjsglxt.fzu.edu.cn")
    result.cookies.set(".ASPXAUTH", "discard-subpath-cookie", path="/login.aspx", domain="yjsglxt.fzu.edu.cn")
    result.cookies.set("ASP.NET_SessionId", "synthetic-session", path="/", domain="yjsglxt.fzu.edu.cn")
    return result


def content_table(rows, next_link=""):
    return f'<div id="divContent"><table><tr><th>synthetic header</th></tr>{rows}</table></div>{next_link}'


def course_row(term="2026-2027-1", name="示例课程一", schedule="1-8周 星期3:9-11节 东3-109"):
    values = [term, "synthetic-code", name, "not-a-credit", "not-a-score", "示例教师", schedule,
              '<a href="../kcgl/example.aspx">授课计划</a>', "示例备注"]
    return "<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>"


def marks_page():
    header = '<tr><td colspan="7">synthetic header</td></tr>' * 6
    # Position mapping is independently transcribed from mark.go cells[1,2,3,5,6].
    return ('<table align="center"><tr><td>not marks</td></tr></table>'
            '<table align="center">' + header +
            '<tr><td>1</td><td>示例研究方法</td><td>学位课</td><td>2026-2027-1</td><td>48</td><td>3</td><td>88</td></tr>'
            '<tr><td>2</td><td>示例学术活动</td><td>必修环节</td><td>2026-2027-1</td><td>16</td><td>1</td><td>合格</td></tr>'
            '<tr><td colspan="7">汇总</td></tr></table>')


class YjsyProtocolTests(unittest.TestCase):
    def setUp(self):
        self.client = YjsyClient.from_cookies("synthetic-student", [{"name": ".ASPXAUTH", "value": "synthetic-auth"}])
        # Any unmocked HTTP request in these tests fails immediately.
        self.enterContext(patch.object(requests.sessions.Session, "request", side_effect=AssertionError("unexpected live network")))

    def test_login_matches_sdk_post_headers_base64_and_root_cookies(self):
        client = YjsyClient("synthetic-student", " 示例 password ")
        with patch.object(client.session, "post", return_value=login_response()) as post:
            self.assertTrue(client.login())
        args = post.call_args
        self.assertEqual(args.args, (LOGIN_URL,))
        self.assertEqual(args.kwargs["data"], {"muser": "synthetic-student", "passwd": base64.b64encode(" 示例 password ".encode()).decode()})
        self.assertEqual(args.kwargs["headers"], {"Referer": REFERER, "Origin": ORIGIN})
        self.assertFalse(args.kwargs["allow_redirects"])
        self.assertEqual(client.session.headers["User-Agent"], USER_AGENT)
        self.assertEqual({(c.name, c.path, c.value) for c in client.session.cookies}, {
            (".ASPXAUTH", "/", "synthetic-auth"), ("ASP.NET_SessionId", "/", "synthetic-session"),
        })
        self.assertEqual(client.password, "")
        self.assertTrue(client.session.verify)

    def test_failure_is_not_login_and_never_retried(self):
        for result in [response("登录失败"), response(status=302)]:
            client = YjsyClient("synthetic-student", "synthetic-password")
            with patch.object(client.session, "post", return_value=result) as post:
                with self.assertRaises(JwchLoginError):
                    client.login()
            post.assert_called_once()
            self.assertFalse(client._logged_in)
            self.assertEqual(list(client.session.cookies), [])
            self.assertEqual(client.password, "")

    def test_network_failure_is_not_treated_as_sdk_redirect_success(self):
        client = YjsyClient("synthetic-student", "synthetic-password")
        with patch.object(client.session, "post", side_effect=requests.Timeout) as post:
            with self.assertRaises(YjsyError):
                client.login()
        post.assert_called_once()
        self.assertFalse(client._logged_in)
        self.assertEqual(client.password, "")

    def test_cookie_restore_excludes_subpath_duplicate(self):
        client = YjsyClient.from_cookies("synthetic-student", [
            {"name": ".ASPXAUTH", "value": "root", "path": "/"},
            {"name": ".ASPXAUTH", "value": "subpath", "path": "/login.aspx"},
        ])
        self.assertEqual([(c.value, c.path, c.domain) for c in client.session.cookies], [("root", "/", "yjsglxt.fzu.edu.cn")])
        client = YjsyClient.from_cookies("synthetic-student", [{"name": "ASP.NET_SessionId", "value": "unauthenticated"}])
        with self.assertRaises(JwchSessionError):
            client.get_marks()

    def test_http_200_session_alert_system_error_and_login_form(self):
        for html, error in [
            ("<script>window.alert('您没有权限进入本页或当前登录用户已过期！');</script>", JwchSessionError),
            ("系统发生错误，该信息已被系统记录", YjsyError),
            ('<input id="tbxUserID">', JwchSessionError),
        ]:
            with patch.object(self.client.session, "get", return_value=response(html)):
                with self.assertRaises(error):
                    self.client.get_marks()

    def test_session_check_uses_marks_page_without_jwch_identifier(self):
        with patch.object(self.client.session, "get", return_value=response(marks_page())) as get:
            self.assertTrue(self.client.validate_session())
        self.assertEqual(get.call_args.args, (MARKS_URL,))
        self.assertIsNone(get.call_args.kwargs["params"])
        self.assertEqual(get.call_args.kwargs["headers"], {"Referer": REFERER})
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_grade_columns_and_non_numeric_scores_are_preserved(self):
        with patch.object(self.client.session, "get", return_value=response(marks_page())):
            marks = self.client.get_marks()
        self.assertEqual([(m["name"], m["type"], m["semester"], m["credits"], m["score"], m["gpa"]) for m in marks], [
            ("示例研究方法", "学位课", "2026-2027-1", "3", "88", ""),
            ("示例学术活动", "必修环节", "2026-2027-1", "1", "合格", ""),
        ])

    def test_six_column_grade_row_does_not_index_past_end(self):
        html = marks_page().replace('<td>48</td><td>3</td><td>88</td>', '<td>3</td><td>88</td>')
        with patch.object(self.client.session, "get", return_value=response(html)):
            self.assertEqual(len(self.client.get_marks()), 1)

    def test_v0011_term_placeholder_dedup_and_descending_order(self):
        html = content_table(course_row("2025-2026-2") + course_row() + course_row() + '<tr><td colspan="13">请选择查询条件</td></tr>')
        with patch.object(self.client.session, "get", return_value=response(html)) as get:
            self.assertEqual(self.client.get_terms(), ["2026-2027-1", "2025-2026-2"])
        self.assertEqual(get.call_args.args, (TERMS_URL,))

    def test_new_student_empty_terms_do_not_trigger_course_or_exam_requests(self):
        html = content_table('<tr><td colspan="13">请选择查询条件</td></tr>')
        with patch.object(self.client.session, "get", return_value=response(html)) as get:
            self.assertEqual(self.client.get_courses(), [])
            self.assertEqual(self.client.get_exam_rooms()["exams"], [])
        get.assert_called_once()

    def test_courses_follow_sdk_filter_pagination_columns_and_schedule(self):
        first = content_table(course_row(schedule="1-8周 星期3:9-11节 东3-109<br>9-16周 星期5:1-2节 东2-101"),
                              '<div id="divPage"><a href="?page=2&amp;strwhere=XNXQ%3D%272026-2027-1%27">下一页</a></div>')
        second = content_table(course_row(name="示例课程二"))
        with patch.object(self.client.session, "get", side_effect=[response(first), response(second)]) as get:
            courses = self.client.get_courses("2026-2027-1")
        self.assertEqual(get.call_args_list[0].kwargs["params"], {"strwhere": "XNXQ='2026-2027-1'"})
        self.assertEqual(get.call_args_list[1].args, (COURSES_URL + "?page=2&strwhere=XNXQ%3D%272026-2027-1%27",))
        self.assertIsNone(get.call_args_list[1].kwargs["params"])
        self.assertEqual([c["name"] for c in courses], ["示例课程一", "示例课程二"])
        self.assertEqual(courses[0]["teacher"], "示例教师")
        self.assertEqual(courses[0]["credits"], "")
        self.assertEqual(courses[0]["lesson_plan"], BASE_URL + "/kcgl/example.aspx")
        self.assertEqual(courses[0]["schedule_rules"], [
            {"location": "东3-109", "start_week": 1, "end_week": 8, "weekday": 3, "start_class": 9, "end_class": 11, "single": True, "double": True, "adjust": False},
            {"location": "东2-101", "start_week": 9, "end_week": 16, "weekday": 5, "start_class": 1, "end_class": 2, "single": True, "double": True, "adjust": False},
        ])

    def test_pagination_cannot_loop_or_send_cookies_to_another_host(self):
        for href in ["?page=2", "https://example.invalid/next"]:
            html = content_table(course_row(), f'<div id="divPage"><a href="{href}">下一页</a></div>')
            with patch.object(self.client.session, "get", return_value=response(html)) as get:
                with self.assertRaises(YjsyError):
                    self.client.get_courses("2026-2027-1")
            self.assertLessEqual(get.call_count, 2)

    def test_info_uses_the_seven_upstream_positions(self):
        rows = "".join('<tr>' + "".join(f'<td><span>r{row}c{col}</span></td>' for col in range(1, 5)) + '</tr>' for row in range(1, 16))
        for body in [rows, f"<tbody>{rows}</tbody>"]:
            with patch.object(self.client.session, "get", return_value=response(f'<div id="xxTable"><table>{body}</table></div>')) as get:
                info = self.client.get_student_info()
            self.assertEqual(get.call_args.args, (STUDENT_INFO_URL,))
            self.assertEqual(info, {"学号": "r1c2", "姓名": "r1c4", "生日": "r3c4", "性别": "r2c4", "学院": "r15c2", "年级": "r14c4", "专业": "r15c4"})

    def test_exam_filter_positions_missing_fields_and_dates(self):
        rows = ('<tr><td>1</td><td>示例考试</td><td>unused</td><td>unused</td><td>2027/01/05 09:00-11:00</td><td>东3-109</td></tr>'
                '<tr><td>2</td><td>未定时间</td><td></td><td></td><td>2027/01/06</td><td></td></tr>')
        with patch.object(self.client.session, "get", return_value=response(content_table(rows))) as get:
            exams = self.client.get_exam_rooms("2026-2027-1")
        self.assertEqual(get.call_args.args, (EXAM_ROOMS_URL,))
        self.assertEqual(get.call_args.kwargs["params"], {"strwhere": "XNXQ='2026-2027-1'"})
        self.assertEqual(exams["exams"][0], {"course_name": "示例考试", "credit": "", "teacher": "", "date": "2027-01-05", "time": "09:00-11:00", "location": "东3-109"})
        self.assertEqual(exams["exams"][1]["time"], "")


if __name__ == "__main__":
    unittest.main()
