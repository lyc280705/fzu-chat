"""Regression checks for JWCH HTML decoding and cultivate-plan tables."""

import unittest
from unittest.mock import PropertyMock, patch

import requests
from bs4 import BeautifulSoup

from app.jwch_client import JwchClient, _extract_cultivate_plan_details, _parse_cultivate_plan_table


def _response(html: str, encoding: str = "gb18030") -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = html.encode(encoding)
    response.headers["Content-Type"] = "text/html"
    return response


class JwchParsingTests(unittest.TestCase):
    def test_calendar_uses_declared_gb2312_even_when_detector_guesses_cyrillic(self):
        calendar_html = """<html><head><meta http-equiv="Content-Type" content="text/html; charset=gb2312"></head>
        <body><center><div>当前学期：202601</div></center>
        <select name="xq"><option value="2026012026083120270122">202601</option></select></body></html>"""
        events_html = """<html><head><meta charset="gb2312"></head><body>
        <table><tr><td>校历</td></tr></table>
        <table><tr><td>2026-08-29至2026-09-06为学生补考；2026-08-30为学生注册；</td></tr></table>
        </body></html>"""
        client = JwchClient("")
        client._logged_in = True
        with (
            patch.object(client.session, "get", return_value=_response(calendar_html)),
            patch.object(client.session, "post", return_value=_response(events_html)),
            patch.object(requests.Response, "apparent_encoding", new_callable=PropertyMock, return_value="windows-1251"),
        ):
            calendar = client.get_school_calendar()
            events = client.get_term_events(calendar["terms"][0]["term_id"])["events"]

        self.assertEqual(calendar["current_term"], "202601")
        self.assertEqual([event["name"] for event in events], ["学生补考", "学生注册"])
        self.assertEqual(events[0]["start_date"], "2026-08-29")
        self.assertEqual(events[0]["end_date"], "2026-09-06")

    def test_cultivate_plan_table_preserves_empty_cells_and_expands_spans(self):
        html = """<table>
        <tr><td colspan="5">课程设置</td></tr>
        <tr><td rowspan="2">课程类别</td><td rowspan="2">课程名称</td><td colspan="2">学时</td><td rowspan="2">学分</td></tr>
        <tr><td>理论</td><td>实践</td></tr>
        <tr><td rowspan="2">公共课</td><td>高等数学</td><td>64</td><td></td><td>4</td></tr>
        <tr><td>大学英语</td><td>32</td><td>16</td><td>3</td></tr>
        </table>"""
        table = _parse_cultivate_plan_table(BeautifulSoup(html, "html.parser").table, set())

        self.assertEqual(table["title"], "课程设置")
        self.assertEqual(table["headers"], ["课程类别", "课程名称", "学时-理论", "学时-实践", "学分"])
        self.assertEqual(table["rows"], [
            ["公共课", "高等数学", "64", "", "4"],
            ["公共课", "大学英语", "32", "16", "3"],
        ])

    def test_cultivate_plan_nested_layout_table_does_not_duplicate_rows(self):
        html = """<form><h1>培养方案</h1><table><tr><td>
        <table><tr><td>课程名称</td><td>学分</td><td>备注</td></tr>
        <tr><td>高等数学</td><td>4</td><td></td></tr>
        <tr><td>大学英语</td><td></td><td>必修</td></tr></table>
        </td></tr></table></form>"""
        details = _extract_cultivate_plan_details(BeautifulSoup(html, "html.parser"))

        self.assertEqual(len(details["sections"]), 1)
        self.assertEqual(details["sections"][0]["headers"], ["课程名称", "学分", "备注"])
        self.assertEqual(details["sections"][0]["rows"], [
            ["高等数学", "4", ""],
            ["大学英语", "", "必修"],
        ])


if __name__ == "__main__":
    unittest.main()
