"""FZU graduate client, following west2-online/yjsy v0.0.11.

Protocol reference: d6180deb704c465e4572b62d6c9f505ab0cd3289.
See docs/yjsy-integration.md for the source-to-method mapping and the limited
defensive differences. No authenticated response has been verified locally.
"""

from __future__ import annotations

import base64
import os
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .jwch_client import JwchError, JwchLoginError, JwchSessionError

UPSTREAM_REVISION = "d6180deb704c465e4572b62d6c9f505ab0cd3289"
BASE_URL = "https://yjsglxt.fzu.edu.cn"
LOGIN_URL = f"{BASE_URL}/login.aspx"
MARKS_URL = f"{BASE_URL}/cjgl/xs_cjcx.aspx"
COURSES_URL = f"{BASE_URL}/xqxk/kbcx_list.aspx"
TERMS_URL = f"{COURSES_URL}?page=1&pageSize=1000"
STUDENT_INFO_URL = f"{BASE_URL}/xsgl/xsxx_show.aspx"
EXAM_ROOMS_URL = f"{BASE_URL}/ksgl/kscx.aspx"
REFERER = "https://yjsy.fzu.edu.cn/"
ORIGIN = "https://yjsy.fzu.edu.cn"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/5clea37.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
)
TIMEOUT = 15
SUPPORTED_TOOLS = frozenset({"query_grades", "query_courses", "query_student_info", "query_exam_rooms"})


class YjsyError(JwchError):
    """Graduate upstream or parsing failure (shared education error contract)."""


def _text(node: Any) -> str:
    # htmlquery.InnerText followed by strings.TrimSpace in the reference SDK.
    return node.get_text().strip() if node is not None else ""


def _content_rows(soup: BeautifulSoup) -> list:
    table = soup.select_one("#divContent table")
    if table is None:
        raise YjsyError("未找到研究生系统查询表格，请稍后重试。")
    return table.find_all("tr")[1:]


def _schedule_rules(cell: Any) -> list[dict[str, Any]]:
    """Use the SDK's range-week / numeric-weekday / range-period grammar."""
    rules = []
    for line in cell.get_text("\n").splitlines():
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        week = re.fullmatch(r"(\d+)-(\d+)周", parts[0])
        lesson = re.fullmatch(r"星期(\d+):(\d+)-(\d+)节", parts[1])
        if not week or not lesson:
            continue
        rules.append({
            "location": parts[2], "start_week": int(week[1]), "end_week": int(week[2]),
            "weekday": int(lesson[1]), "start_class": int(lesson[2]), "end_class": int(lesson[3]),
            "single": True, "double": True, "adjust": False,
        })
    return rules


class YjsyClient:
    def __init__(self, student_id: str, password: str = ""):
        self.student_id = student_id
        self.password = password
        self.identifier = ""  # Graduate queries use cookies, without JWCH's id parameter.
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.session.verify = os.getenv("FZU_CHAT_YJSY_CA_BUNDLE", "").strip() or True
        self._logged_in = False
        self._terms: list[str] | None = None

    def login(self) -> bool:
        """Match user.go: one portal-style POST, Base64 and root-path cookies."""
        self._logged_in = False
        self.session.cookies.clear()
        try:
            response = self.session.post(
                LOGIN_URL,
                headers={"Referer": REFERER, "Origin": ORIGIN},
                data={"muser": self.student_id, "passwd": base64.b64encode(self.password.encode("utf-8")).decode("ascii")},
                timeout=TIMEOUT, allow_redirects=False,
            )
            response.raise_for_status()
            # A network error is never login success. Require the redirect and
            # root authentication cookie; a session cookie alone is insufficient.
            cookies = [cookie for cookie in response.cookies if cookie.path == "/"]
            self.session.cookies.clear()
            if response.status_code not in (301, 302, 303, 307, 308) or not any(
                cookie.name == ".ASPXAUTH" and cookie.value for cookie in cookies
            ):
                raise JwchLoginError("研究生系统登录失败，请检查学号和密码。")
            for cookie in cookies:
                self.session.cookies.set_cookie(cookie)
            self._logged_in = True
            return True
        except requests.RequestException as exc:
            self.session.cookies.clear()
            raise YjsyError("研究生系统网络连接失败，请稍后重试。") from exc
        finally:
            self.password = ""

    @classmethod
    def from_cookies(cls, student_id: str, cookies: list[dict[str, Any]], identifier: str = "") -> "YjsyClient":
        client = cls(student_id)
        for cookie in cookies:
            if cookie.get("path", "/") != "/":
                continue
            client.session.cookies.set(cookie["name"], cookie["value"], domain=urlparse(BASE_URL).hostname, path="/")
        client._logged_in = any(cookie.name == ".ASPXAUTH" and cookie.value for cookie in client.session.cookies)
        return client

    def _get(self, url: str, params: dict[str, str] | None = None) -> BeautifulSoup:
        if not self._logged_in:
            raise JwchSessionError("尚未登录研究生教务系统，请在侧栏重新连接教务。")
        if urlparse(url).scheme != "https" or urlparse(url).netloc != urlparse(BASE_URL).netloc:
            raise YjsyError("研究生系统返回了无效的查询地址。")
        try:
            response = self.session.get(url, params=params, headers={"Referer": REFERER}, timeout=TIMEOUT, allow_redirects=False)
            if response.is_redirect:
                raise JwchSessionError("研究生教务登录已过期，请重新连接教务。")
            response.raise_for_status()
        except requests.RequestException as exc:
            raise YjsyError("研究生系统连接失败，请稍后重试。") from exc
        # The Go SDK parses response bytes as UTF-8, including HTTP-200 alert pages.
        html = response.content.decode("utf-8", errors="replace")
        if "当前登录用户已过期" in html:
            raise JwchSessionError("研究生教务登录已过期，请重新连接教务。")
        if "系统发生错误" in html:
            raise YjsyError("研究生教务系统内部错误，请稍后重试。")
        soup = BeautifulSoup(html, "html.parser")
        if soup.find(id="tbxUserID") or soup.find("input", attrs={"name": "muser"}):
            raise JwchSessionError("研究生教务登录已过期，请重新连接教务。")
        return soup

    def validate_session(self) -> bool:
        self._get(MARKS_URL)  # user.go CheckSession uses the marks page.
        return True

    def get_marks(self) -> list[dict[str, Any]]:
        soup = self._get(MARKS_URL)
        tables = soup.find_all("table", attrs={"align": "center"})
        if len(tables) < 2:
            raise YjsyError("未找到研究生成绩表格。")
        marks = []
        for row in tables[1].find_all("tr")[6:]:
            cells = row.find_all("td", recursive=False)
            if len(cells) < 7:
                continue
            term = _text(cells[3])
            marks.append({
                "name": _text(cells[1]), "type": _text(cells[2]), "semester": term,
                "semester_code": term, "credits": _text(cells[5]), "score": _text(cells[6]),
                "gpa": "", "student_type": "graduate",
            })
        return marks

    def get_terms(self) -> list[str]:
        if self._terms is None:
            terms = []
            for row in _content_rows(self._get(TERMS_URL)):
                cells = row.find_all("td", recursive=False)
                if not cells or cells[0].has_attr("colspan"):
                    continue  # v0.0.11: new students may only see a placeholder row.
                term = _text(cells[0])
                if term:
                    terms.append(term)
            self._terms = sorted(set(terms), reverse=True)
        return list(self._terms)

    def get_courses(self, term: str | None = None) -> list[dict[str, Any]]:
        if term is None:
            terms = self.get_terms()
            if not terms:
                return []
            term = terms[0]
        # Preserve the exact upstream term string; never substitute a JWCH code.
        soup = self._get(COURSES_URL, {"strwhere": f"XNXQ='{term}'"})
        courses: list[dict[str, Any]] = []
        seen = set()
        while True:
            for row in _content_rows(soup):
                cells = row.find_all("td", recursive=False)
                if len(cells) < 9:
                    continue
                link = cells[7].find("a", href=True)
                rules = _schedule_rules(cells[6])
                courses.append({
                    "name": _text(cells[2]), "teacher": _text(cells[5]), "credits": "",
                    "time": cells[6].get_text("\n", strip=True),
                    "location": rules[0]["location"] if rules else "",
                    "remark": _text(cells[8]), "semester": _text(cells[0]), "semester_code": _text(cells[0]),
                    "lesson_plan": urljoin(COURSES_URL, link["href"]) if link else "",
                    "schedule_rules": rules, "student_type": "graduate",
                })
            next_link = next((a for a in soup.select("#divPage a[href]") if "下一页" in a.get_text()), None)
            if next_link is None:
                return courses
            next_url = urljoin(COURSES_URL, next_link["href"])
            if next_url in seen or len(seen) >= 100:
                raise YjsyError("研究生课表分页异常，未返回不完整结果。")
            seen.add(next_url)
            soup = self._get(next_url)

    def get_student_info(self) -> dict[str, str]:
        soup = self._get(STUDENT_INFO_URL)
        table = soup.select_one("#xxTable > table")
        if table is None:
            raise YjsyError("未找到研究生个人信息表格。")
        # info.go uses these exact one-based row and cell positions.
        rows = table.select(":scope > tbody > tr") or table.find_all("tr", recursive=False)
        positions = {"学号": (1, 2), "姓名": (1, 4), "生日": (3, 4), "性别": (2, 4),
                     "学院": (15, 2), "年级": (14, 4), "专业": (15, 4)}
        result = {}
        for name, (row, col) in positions.items():
            cells = rows[row - 1].find_all("td", recursive=False) if len(rows) >= row else []
            result[name] = _text(cells[col - 1]) if len(cells) >= col else ""
        return result

    def get_exam_room_terms(self) -> list[str]:
        return self.get_terms()

    def get_exam_rooms(self, term_code: str | None = None) -> dict[str, Any]:
        if term_code is None:
            terms = self.get_terms()
            term_code = terms[0] if terms else ""
        exams = []
        if term_code:
            soup = self._get(EXAM_ROOMS_URL, {"strwhere": f"XNXQ='{term_code}'"})
            for row in _content_rows(soup):
                cells = row.find_all("td", recursive=False)
                if len(cells) < 6:
                    continue
                date_time = _text(cells[4]).split()
                exams.append({
                    "course_name": _text(cells[1]), "credit": "", "teacher": "",
                    "date": date_time[0].replace("/", "-", 2) if date_time else "",
                    "time": date_time[1] if len(date_time) > 1 else "", "location": _text(cells[5]),
                })
        return {"term": term_code, "term_label": term_code, "available_terms": self._terms or [], "exams": exams}
