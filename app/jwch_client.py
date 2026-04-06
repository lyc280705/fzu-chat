"""Python client for the FZU Undergraduate Teaching System (JWCH).

Based on the Go implementation at https://github.com/west2-online/jwch.
Handles login (with automatic CAPTCHA recognition), grade queries,
course-schedule queries, and student-profile queries.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://jwcjwxt2.fzu.edu.cn"
CAPTCHA_URL = f"{BASE_URL}/plus/verifycode.asp"
LOGIN_URL = f"{BASE_URL}:82/logincheck.asp"
SSO_LOGIN_URL = f"{BASE_URL}/Sfrz/SSOLogin"
CAPTCHA_AI_URL = "https://statistics.fzuhelper.w2fzu.com/api/login/validateCode"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class JwchError(Exception):
    """Base error for JWCH client operations."""


class JwchLoginError(JwchError):
    """Raised when login to the educational system fails."""


class JwchSessionError(JwchError):
    """Raised when a query fails due to an invalid or expired session."""


class JwchClient:
    """Client for the FZU undergraduate academic-affairs system."""

    def __init__(self, student_id: str, password: str = ""):
        self.student_id = student_id
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _UA})
        self.identifier: str = ""
        self._logged_in = False

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """Authenticate with the JWCH system.

        Flow (mirroring the Go library):
        1. Fetch CAPTCHA image.
        2. Recognise CAPTCHA via the FZU-helper AI service.
        3. POST credentials (password MD5-hashed).
        4. Follow SSO redirects and extract session identifier.
        """
        try:
            # 1 – CAPTCHA
            resp = self.session.get(CAPTCHA_URL, timeout=10)
            resp.raise_for_status()
            captcha_text = self._recognise_captcha(resp.content)
            if not captcha_text:
                raise JwchLoginError("验证码识别失败")

            # 2 – Login (MD5 is required by the upstream FZU JWCH protocol, not used for storage)
            md5_pw = hashlib.md5(self.password.encode()).hexdigest()  # noqa: S324
            resp = self.session.post(
                LOGIN_URL,
                data={"muser": self.student_id, "passwd": md5_pw, "verifycode": captcha_text},
                timeout=10,
                allow_redirects=False,
            )

            # 3 – Handle redirects / SSO
            if resp.status_code in (301, 302):
                location = resp.headers.get("Location", "")
                resp = self.session.get(location, timeout=10, allow_redirects=True)

            # 4 – Extract identifier from final URL
            final_url = getattr(resp, "url", "")
            match = re.search(r"id=(\d+)", str(final_url))
            if match:
                self.identifier = match.group(1)

            self._logged_in = True
            return True

        except JwchError:
            raise
        except requests.RequestException as exc:
            raise JwchLoginError(f"教务系统网络连接失败: {exc}") from exc
        except Exception as exc:
            raise JwchLoginError(f"登录失败: {exc}") from exc

    def _recognise_captcha(self, image_bytes: bytes) -> str:
        try:
            b64 = base64.b64encode(image_bytes).decode()
            resp = requests.post(CAPTCHA_AI_URL, json={"image": b64}, timeout=10)
            if resp.status_code == 200:
                return resp.json().get("data", "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Captcha recognition failed: %s", exc)
        return ""

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def _get(self, path: str) -> BeautifulSoup:
        url = f"{BASE_URL}{path}"
        if self.identifier:
            sep = "&" if "?" in path else "?"
            url += f"{sep}id={self.identifier}"
        resp = self.session.get(url, timeout=15)
        resp.encoding = "utf-8"
        return BeautifulSoup(resp.text, "html.parser")

    def get_marks(self) -> List[Dict[str, Any]]:
        """Return all course grades."""
        self._require_login()
        soup = self._get("/student/xscj/Stu_MyScore_Rpt.aspx")
        marks: List[Dict[str, Any]] = []
        table = soup.find("table", id="ContentPlaceHolder1_DataList_xxk") or soup.find(
            "table", class_="dataList"
        )
        if not table:
            return marks
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            marks.append(
                {
                    "semester": cells[0].get_text(strip=True),
                    "name": cells[1].get_text(strip=True),
                    "credits": cells[2].get_text(strip=True),
                    "score": cells[3].get_text(strip=True),
                    "gpa": cells[4].get_text(strip=True) if len(cells) > 4 else "",
                    "type": cells[5].get_text(strip=True) if len(cells) > 5 else "",
                }
            )
        return marks

    def get_courses(self) -> List[Dict[str, Any]]:
        """Return the current semester's course schedule."""
        self._require_login()
        soup = self._get("/student/xkjg/wdxk/xkjg_list.aspx")
        courses: List[Dict[str, Any]] = []
        table = soup.find("table", class_="dataList")
        if not table:
            return courses
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            courses.append(
                {
                    "name": cells[0].get_text(strip=True),
                    "teacher": cells[1].get_text(strip=True) if len(cells) > 1 else "",
                    "credits": cells[2].get_text(strip=True) if len(cells) > 2 else "",
                    "time": cells[3].get_text(strip=True) if len(cells) > 3 else "",
                    "location": cells[4].get_text(strip=True) if len(cells) > 4 else "",
                }
            )
        return courses

    def get_student_info(self) -> Dict[str, Any]:
        """Return the student's profile information."""
        self._require_login()
        soup = self._get("/student/glbm/xjgl/xjgl_csxxcx.aspx")
        info: Dict[str, Any] = {}
        for label_tag in soup.find_all("span"):
            text = label_tag.get_text(strip=True)
            if text.endswith("：") or text.endswith(":"):
                key = text.rstrip("：:")
                sibling = label_tag.find_next_sibling("span")
                if sibling:
                    info[key] = sibling.get_text(strip=True)
        return info

    def get_cet_scores(self) -> List[Dict[str, Any]]:
        """Return CET / unified-exam scores."""
        self._require_login()
        soup = self._get("/student/xscj/Stu_djkscj_Rpt.aspx")
        scores: List[Dict[str, Any]] = []
        table = soup.find("table", class_="dataList")
        if not table:
            return scores
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            scores.append(
                {
                    "exam_name": cells[0].get_text(strip=True),
                    "score": cells[1].get_text(strip=True),
                    "date": cells[2].get_text(strip=True) if len(cells) > 2 else "",
                }
            )
        return scores

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_login(self) -> None:
        if not self._logged_in:
            raise JwchSessionError("尚未登录教务系统")

    @classmethod
    def from_cookies(
        cls, student_id: str, cookies: List[Dict[str, str]], identifier: str = ""
    ) -> "JwchClient":
        """Reconstruct a client from previously-saved cookies."""
        client = cls(student_id)
        for c in cookies:
            client.session.cookies.set(c["name"], c["value"])
        client.identifier = identifier
        client._logged_in = True
        return client
