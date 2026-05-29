"""Python client for the FZU Undergraduate Teaching System (JWCH).

Based on the Go implementation at https://github.com/west2-online/jwch.
Handles login (with automatic CAPTCHA recognition), grade queries,
course-schedule queries, and student-profile queries.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta
import hashlib
import imghdr
import logging
import os
import re
from urllib.parse import parse_qs, urlparse
from typing import Any, Dict, List, Tuple

import requests
import urllib3
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://jwcjwxt2.fzu.edu.cn"
JWCH_PREFIX = f"{BASE_URL}:81"
JWCH_PORTAL = f"{BASE_URL}:82"
CAPTCHA_URL = f"{JWCH_PORTAL}/plus/verifycode.asp"
LOGIN_URL = f"{JWCH_PORTAL}/logincheck.asp"
LOGIN_REFERER = "https://jwch.fzu.edu.cn"
SSO_LOGIN_URL = f"{BASE_URL}/Sfrz/SSOLogin"
LOGINCHK_URL = f"{JWCH_PREFIX}/loginchk_xs.aspx"
MARKS_URL = f"{JWCH_PREFIX}/student/xyzk/cjyl/score_sheet.aspx"
COURSES_URL = f"{JWCH_PREFIX}/student/xkjg/wdxk/xkjg_list.aspx"
USER_INFO_URL = f"{JWCH_PREFIX}/jcxx/xsxx/StudentInformation.aspx"
CET_URL = f"{JWCH_PREFIX}/student/glbm/cet/cet_cszt.aspx"
JS_URL = f"{JWCH_PREFIX}/student/glbm/computer/jsj_cszt.aspx"
SCHOOL_CALENDAR_URL = f"{JWCH_PORTAL}/xl.asp"
CREDIT_URL = f"{JWCH_PREFIX}/student/xyzk/xftj/CreditStatistics.aspx"
GPA_URL = f"{JWCH_PREFIX}/student/xyzk/jdpm/GPA_sheet.aspx"
EXAM_ROOM_URL = f"{JWCH_PREFIX}/student/xkjg/examination/exam_list.aspx"
CULTIVATE_PLAN_URL = f"{JWCH_PREFIX}/pyfa/pyjh/pyjh_list.aspx"
CAPTCHA_AI_URL = "https://statistics.fzuhelper.w2fzu.com/api/login/validateCode?validateCode"
JWCH_LOGIN_TIMEOUT_SECONDS = float(os.getenv("FZU_CHAT_JWCH_LOGIN_TIMEOUT_SECONDS", "10"))
JWCH_QUERY_TIMEOUT_SECONDS = float(os.getenv("FZU_CHAT_JWCH_QUERY_TIMEOUT_SECONDS", "15"))
JWCH_CAPTCHA_TIMEOUT_SECONDS = float(os.getenv("FZU_CHAT_JWCH_CAPTCHA_TIMEOUT_SECONDS", "10"))
SEMESTER_CODE_RE = re.compile(r"^(20\d{2})(0[12])$")
SELECTION_TIME_RE = re.compile(
    r"(?P<label>[\u4e00-\u9fffA-Za-z（）()]+?)\s*时间[:：]\s*"
    r"(?P<start>20\d{2}-\d{2}-\d{2}\s+\d{2}[：:]\d{2})\s*至\s*"
    r"(?P<end>20\d{2}-\d{2}-\d{2}\s+\d{2}[：:]\d{2})"
)
CULTIVATE_PLAN_TEXT_TAGS: Tuple[str, ...] = (
    "p",
    "div",
    "section",
    "article",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "span",
    "strong",
    "b",
    "font",
)
CULTIVATE_PLAN_HEADING_PATTERNS: Tuple[Tuple[int, re.Pattern[str]], ...] = (
    (1, re.compile(r"^[一二三四五六七八九十百]+、")),
    (2, re.compile(r"^[（(][一二三四五六七八九十百]+[)）]")),
    (3, re.compile(r"^\d+[.．、](?!\d)")),
    (4, re.compile(r"^\[\d+\]")),
)
CULTIVATE_PLAN_SECTION_PREFIX_RE = re.compile(
    r"^(?:[一二三四五六七八九十百]+、|[（(][一二三四五六七八九十百]+[)）]|\d+[.．、](?!\d)|\[\d+\])\s*"
)
CULTIVATE_PLAN_INLINE_ITEM_RE = re.compile(
    r"(?:^|(?<=\s))(?P<label>\d{1,2}[.．、](?!\d)\s*[^：:]{1,20}[：:])"
)
CULTIVATE_PLAN_ITEM_RE = re.compile(
    r"^(?P<title>(?:\d{1,2}[.．、](?!\d)|\[\d+\])\s*[^：:]{1,30})[：:]\s*(?P<content>.*)$"
)

SELECTION_CATEGORY_CONFIG: Tuple[Dict[str, Any], ...] = (
    {
        "key": "semester",
        "label": "学期选课",
        "status_path": "/student/glxk/xqxk/xqxk_cszt.aspx",
        "list_path": "/student/glxk/xqxk/xqxk_kclist.aspx",
        "aliases": ("学期选课", "学期", "必修选课", "专业选课"),
    },
    {
        "key": "general",
        "label": "通识选修课",
        "status_path": "/student/glxk/xxk/xxk_cszt.aspx",
        "list_path": "/student/glxk/xxk/xxk_kclist.aspx",
        "aliases": ("通识选修课", "通识选修", "通识", "校选课"),
    },
    {
        "key": "restudy",
        "label": "重新学习选课",
        "status_path": "/student/glxk/cxxk/cxxk_cszt.aspx",
        "list_path": "/student/glxk/cxxk/cxxk_kclist.aspx",
        "aliases": ("重新学习选课", "重新学习", "重修选课", "重修"),
    },
    {
        "key": "minor",
        "label": "辅修专业选课",
        "status_path": "/student/glxk/erzyxk/erzyxk_cszt.aspx",
        "list_path": "/student/glxk/erzyxk/erzyxk_kclist.aspx",
        "aliases": ("辅修专业选课", "辅修", "辅修选课"),
    },
    {
        "key": "college",
        "label": "院选课",
        "status_path": "/student/glxk/yxk/yxk_cszt.aspx",
        "list_path": "/student/glxk/yxk/yxk_kclist.aspx",
        "aliases": ("院选课", "院系选课", "校级选修课"),
    },
    {
        "key": "national",
        "label": "国情类选课",
        "status_path": "/student/glxk/xck/xck_cszt.aspx",
        "list_path": "/student/glxk/xck/xck_kclist.aspx",
        "aliases": ("国情类选课", "国情类", "国情"),
    },
    {
        "key": "supplement",
        "label": "特殊补选",
        "status_path": "/student/glxk/bxk/bxk_cszt.aspx",
        "list_path": "/student/glxk/bxk/bxk_kclist.aspx",
        "aliases": ("特殊补选", "补选", "补选课"),
    },
)

SELECTION_STATUS_MARKERS = {"中选", "已选", "待审核", "审核通过", "审核中"}
SELECTION_ACTION_HEADERS = ("退选", "删除")
SELECTION_COLUMN_ALIASES = (
    ("选课状态", "selection_status"),
    ("审核状态", "audit_status"),
    ("课程名称", "course_name"),
    ("所投积分", "points"),
    ("购买教材方式", "textbook"),
    ("课程类型", "course_type"),
    ("选修类型", "elective_type"),
    ("上课专业", "major"),
    ("任课教师", "teacher"),
    ("学时", "hours"),
    ("学分", "credits"),
    ("上课时间", "schedule"),
    ("限选人数", "limit"),
    ("备注", "remark"),
    ("缴费状态", "payment_status"),
    ("考试类别", "exam_category"),
    ("免听理由", "waiver_reason"),
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def normalize_semester_code(value: str) -> str:
    text = re.sub(r"\D", "", str(value or ""))
    match = re.search(r"(20\d{2})(0[12])", text)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    return str(value or "").strip()


def format_semester_label(value: str) -> str:
    code = normalize_semester_code(value)
    match = SEMESTER_CODE_RE.fullmatch(code)
    if not match:
        return str(value or "").strip()
    start_year = int(match.group(1))
    term_label = "第一学期" if match.group(2) == "01" else "第二学期"
    return f"{start_year}-{start_year + 1}学年{term_label}"


def _text_content(node: Any) -> str:
    if node is None:
        return ""
    getter = getattr(node, "get_text", None)
    if callable(getter):
        text = getter(" ", strip=True)
    else:
        text = str(node)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_match_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _parse_float(value: Any) -> float | None:
    text = re.sub(r"[^0-9.]+", "", str(value or ""))
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_time_text(value: str) -> str:
    return str(value or "").replace("：", ":").replace("\xa0", " ").strip()


def _clean_cultivate_plan_text(value: Any) -> str:
    text = _text_content(value)
    text = text.strip("| ")
    return re.sub(r"\s+", " ", text).strip()


def _is_cultivate_plan_noise(text: str) -> bool:
    normalized = _normalize_match_text(text)
    if not normalized:
        return True
    if normalized in {"打印", "关闭", "返回", "确定", "查询", "重置", "登录", "退出", "首页"}:
        return True
    if any(token in normalized for token in ("当前位置", "教务", "版权所有", "系统提示")):
        return True
    return False


def _looks_like_cultivate_plan_title(text: str) -> bool:
    if _is_cultivate_plan_noise(text) or len(text) > 24:
        return False
    return any(keyword in text for keyword in ("计划", "课程", "模块", "环节", "要求", "体系", "类别", "方向", "实践", "毕业"))


def _is_generic_cultivate_plan_table_title(text: str) -> bool:
    normalized = _normalize_match_text(text)
    if not normalized:
        return True
    return normalized in {
        "课程类别",
        "课程类别学分数占课内教学总学分百分比",
        "课程名称",
        "开课单位",
        "学分",
        "学时数",
    }


def _normalize_cultivate_plan_heading(value: Any) -> str:
    return _clean_cultivate_plan_text(value).rstrip("：:").strip()


def _cultivate_plan_heading_level(text: str) -> int | None:
    normalized = _normalize_cultivate_plan_heading(text)
    if not normalized or _is_cultivate_plan_noise(normalized):
        return None
    if re.match(r"^(?:\d+[.．、](?!\d)|\[\d+\])", normalized) and re.search(r"[：:]", normalized):
        return None
    if any(keyword in normalized for keyword in ("专业培养计划", "培养方案", "培养计划")):
        return 0
    for level, pattern in CULTIVATE_PLAN_HEADING_PATTERNS:
        if pattern.match(normalized):
            return level
    if _looks_like_cultivate_plan_title(normalized):
        return 1
    return None


def _dedupe_cultivate_plan_blocks(blocks: List[str]) -> List[str]:
    results: List[str] = []
    seen = set()
    for block in blocks:
        normalized = _clean_cultivate_plan_text(block)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)
    return results


def _dedupe_cultivate_plan_items(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    seen = set()
    for item in items:
        title = _normalize_cultivate_plan_heading(item.get("title"))
        content = _clean_cultivate_plan_text(item.get("content"))
        signature = (title, content)
        if not title or signature in seen:
            continue
        seen.add(signature)
        results.append({"title": title, "content": content})
    return results


def _split_cultivate_plan_numbered_items(text: str) -> List[str]:
    normalized = _clean_cultivate_plan_text(text)
    if not normalized:
        return []
    matches = list(CULTIVATE_PLAN_INLINE_ITEM_RE.finditer(normalized))
    if len(matches) < 2:
        return [normalized]
    parts: List[str] = []
    for index, match in enumerate(matches):
        start = match.start("label")
        end = matches[index + 1].start("label") if index + 1 < len(matches) else len(normalized)
        part = normalized[start:end].strip()
        if part:
            parts.append(part)
    return parts or [normalized]


def _parse_cultivate_plan_item(text: str) -> Dict[str, str] | None:
    normalized = _clean_cultivate_plan_text(text)
    if not normalized:
        return None
    match = CULTIVATE_PLAN_ITEM_RE.match(normalized)
    if not match:
        return None
    return {
        "title": _normalize_cultivate_plan_heading(match.group("title")),
        "content": _clean_cultivate_plan_text(match.group("content")),
    }


def _refine_cultivate_plan_chapter(chapter: Dict[str, Any]) -> None:
    paragraphs = chapter.get("paragraphs") or []
    refined_paragraphs: List[str] = []
    items: List[Dict[str, str]] = list(chapter.get("items") or [])

    for paragraph in paragraphs:
        chunks = _split_cultivate_plan_numbered_items(paragraph)
        if len(chunks) > 1:
            extracted = False
            for chunk in chunks:
                item = _parse_cultivate_plan_item(chunk)
                if item is not None:
                    items.append(item)
                    extracted = True
                else:
                    refined_paragraphs.append(chunk)
            if extracted:
                continue

        item = _parse_cultivate_plan_item(paragraph)
        if item is not None:
            items.append(item)
        else:
            refined_paragraphs.append(paragraph)

    chapter["paragraphs"] = _dedupe_cultivate_plan_blocks(refined_paragraphs)
    chapter["items"] = _dedupe_cultivate_plan_items(items)


def _flatten_cultivate_plan_text_blocks(chapters: List[Dict[str, Any]]) -> List[str]:
    blocks: List[str] = []
    for chapter in chapters:
        title = _normalize_cultivate_plan_heading(chapter.get("title"))
        if title:
            blocks.append(title)
        blocks.extend(chapter.get("paragraphs") or [])
        for item in chapter.get("items") or []:
            item_title = _normalize_cultivate_plan_heading(item.get("title"))
            item_content = _clean_cultivate_plan_text(item.get("content"))
            blocks.append(f"{item_title}：{item_content}" if item_content else item_title)
    return _dedupe_cultivate_plan_blocks(blocks)


def _build_cultivate_plan_outline(chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "id": chapter.get("id"),
            "title": chapter.get("title"),
            "level": chapter.get("level", 1),
            "paragraph_count": len(chapter.get("paragraphs") or []),
            "item_count": len(chapter.get("items") or []),
            "table_count": len(chapter.get("tables") or []),
        }
        for chapter in chapters
        if chapter.get("title")
    ]


def _iter_cultivate_plan_blocks(root: Any):
    block_tags = set(CULTIVATE_PLAN_TEXT_TAGS) | {"table"}
    for tag in root.find_all(list(block_tags), recursive=True):
        if tag.name == "table":
            yield "table", tag
            continue
        if tag.find_parent("table"):
            continue
        if tag.find(list(block_tags), recursive=False):
            continue
        text = _clean_cultivate_plan_text(tag)
        if text:
            yield "text", text


def _parse_cultivate_plan_table(table: Any, signatures: set[Tuple[Tuple[str, ...], ...]]) -> Dict[str, Any] | None:
    tr_nodes = table.find_all("tr")
    if not tr_nodes:
        return None

    rows: List[List[str]] = []
    for tr in tr_nodes:
        cells = [
            _clean_cultivate_plan_text(cell)
            for cell in tr.find_all(["th", "td"], recursive=False)
        ]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(cells)

    if len(rows) < 2:
        return None

    width = max(len(row) for row in rows)
    if width < 2:
        return None

    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    signature = tuple(tuple(row) for row in normalized_rows[:8])
    if signature in signatures:
        return None
    signatures.add(signature)

    has_header = any(tr.find("th", recursive=False) for tr in tr_nodes)
    if has_header:
        headers = [cell or f"列{index + 1}" for index, cell in enumerate(normalized_rows[0])]
        body_rows = normalized_rows[1:]
    else:
        first_row = normalized_rows[0]
        if len(set(first_row)) == len(first_row):
            headers = [cell or f"列{index + 1}" for index, cell in enumerate(first_row)]
            body_rows = normalized_rows[1:]
        else:
            headers = [f"列{index + 1}" for index in range(width)]
            body_rows = normalized_rows

    body_rows = [row for row in body_rows if any(cell for cell in row)]
    if not body_rows:
        return None

    return {
        "title": _find_cultivate_plan_table_title(table),
        "headers": headers,
        "rows": body_rows,
    }


def _find_cultivate_plan_table_title(table: Any) -> str:
    caption = _clean_cultivate_plan_text(table.find("caption"))
    if caption and not _is_cultivate_plan_noise(caption):
        return caption

    title_cell = table.find(lambda tag: tag.name in {"th", "td"} and tag.get("colspan"))
    title_text = _clean_cultivate_plan_text(title_cell)
    if title_text and len(title_text) <= 40 and _looks_like_cultivate_plan_title(title_text):
        return title_text

    current = table
    for _ in range(4):
        sibling = getattr(current, "previous_sibling", None)
        while sibling is not None:
            text = _clean_cultivate_plan_text(sibling)
            if text and _looks_like_cultivate_plan_title(text):
                return text
            sibling = getattr(sibling, "previous_sibling", None)
        current = getattr(current, "parent", None)
        if current is None:
            break
    return ""


def _extract_cultivate_plan_details(soup: BeautifulSoup) -> Dict[str, Any]:
    root = soup.find("form") or soup.body or soup

    for anchor in root.find_all("a"):
        anchor.unwrap()
    for tag in root.find_all(["script", "style", "input", "select", "textarea", "button"]):
        tag.decompose()

    sections: List[Dict[str, Any]] = []
    chapters: List[Dict[str, Any]] = []
    signatures: set[Tuple[Tuple[str, ...], ...]] = set()
    chapter_index: Dict[str, Dict[str, Any]] = {}
    current_chapter: Dict[str, Any] | None = None

    def ensure_chapter(title: str, level: int | None = None) -> Dict[str, Any]:
        normalized_title = _normalize_cultivate_plan_heading(title) or f"未命名章节{len(chapters) + 1}"
        key = _normalize_match_text(normalized_title)
        chapter = chapter_index.get(key)
        if chapter is None:
            chapter = {
                "id": f"chapter_{len(chapters) + 1}",
                "title": normalized_title,
                "level": 1 if level is None else level,
                "paragraphs": [],
                "items": [],
                "tables": [],
            }
            chapters.append(chapter)
            if key:
                chapter_index[key] = chapter
        elif level is not None:
            chapter["level"] = min(int(chapter.get("level", level)), level)
        return chapter

    for block_type, payload in _iter_cultivate_plan_blocks(root):
        if block_type == "text":
            text = _clean_cultivate_plan_text(payload)
            if not text or _is_cultivate_plan_noise(text):
                continue
            level = _cultivate_plan_heading_level(text)
            if level is not None:
                current_chapter = ensure_chapter(text, level=level)
                continue
            if current_chapter is None:
                current_chapter = ensure_chapter("总览", level=0)
            current_chapter["paragraphs"].append(text)
            continue

        section = _parse_cultivate_plan_table(payload, signatures)
        if section is None:
            continue

        detected_title = _normalize_cultivate_plan_heading(section.get("title"))
        target_title = detected_title
        target_level = _cultivate_plan_heading_level(detected_title) if detected_title else None

        if current_chapter is not None and (
            int(current_chapter.get("level", 99)) >= 2
            or not target_title
            or _is_generic_cultivate_plan_table_title(target_title)
        ):
            target_title = current_chapter["title"]
            target_level = int(current_chapter.get("level", 1))
        elif current_chapter is not None and target_title == current_chapter.get("title"):
            target_level = int(current_chapter.get("level", 1))

        if not target_title:
            target_title = f"表格{len(sections) + 1}"
            target_level = 3

        section["title"] = target_title
        chapter = ensure_chapter(target_title, level=target_level)
        chapter["tables"].append(
            {
                "title": target_title,
                "headers": section["headers"],
                "rows": section["rows"],
            }
        )
        sections.append(section)

    for chapter in chapters:
        _refine_cultivate_plan_chapter(chapter)

    text_blocks = _flatten_cultivate_plan_text_blocks(chapters)

    if not text_blocks:
        fallback_root = BeautifulSoup(str(root), "html.parser")
        for table in fallback_root.find_all("table"):
            table.decompose()
        text_blocks = _dedupe_cultivate_plan_blocks(
            [
                _clean_cultivate_plan_text(text)
                for _, text in _iter_cultivate_plan_blocks(fallback_root)
                if _ == "text" and not _is_cultivate_plan_noise(_clean_cultivate_plan_text(text))
            ]
        )

    title = _clean_cultivate_plan_text(soup.title)
    if not title:
        title = _clean_cultivate_plan_text(root.find(["h1", "h2", "h3", "h4"]))

    document_title = next(
        (
            _normalize_cultivate_plan_heading(chapter.get("title"))
            for chapter in chapters
            if int(chapter.get("level", 1)) == 0 and chapter.get("title")
        ),
        "",
    )

    return {
        "title": title,
        "document_title": document_title,
        "text_blocks": text_blocks,
        "sections": sections,
        "outline": _build_cultivate_plan_outline(chapters),
        "chapters": chapters,
    }


def _parse_selection_datetime(value: str) -> datetime | None:
    text = _normalize_time_text(value)
    if not text:
        return None
    if text.endswith("24:00"):
        base = datetime.strptime(text[:-5] + "00:00", "%Y-%m-%d %H:%M")
        return base + timedelta(days=1)
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _selection_header_key(header: str) -> str:
    normalized = _normalize_match_text(header)
    for token, key in SELECTION_COLUMN_ALIASES:
        if token in normalized:
            return key
    return ""


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
        self.session.verify = False
        self.identifier: str = ""
        self._logged_in = False

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """Authenticate with the JWCH system.

        Flow mirrors west2-online/jwch:
        1. Fetch CAPTCHA image from the :82 portal.
        2. Recognise CAPTCHA via the FZU-helper service.
        3. POST credentials to logincheck.asp and extract token / id / num.
        4. Complete SSO login and bootstrap the :81 session.
        """
        try:
            self.session.cookies.clear()

            # 1 – CAPTCHA
            resp = self.session.get(CAPTCHA_URL, timeout=JWCH_LOGIN_TIMEOUT_SECONDS, allow_redirects=False)
            resp.raise_for_status()
            captcha_text = self._recognise_captcha(resp.content)
            if not captcha_text:
                raise JwchLoginError("验证码识别失败")

            # 2 – Login (the upstream protocol uses the 16-char MD5 variant)
            md5_pw = hashlib.md5(self.password.encode()).hexdigest()[8:24]  # noqa: S324
            resp = self.session.post(
                LOGIN_URL,
                headers={"Referer": LOGIN_REFERER, "Origin": LOGIN_REFERER},
                data={"Verifycode": captcha_text, "muser": self.student_id, "passwd": md5_pw},
                timeout=JWCH_LOGIN_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
            location = resp.headers.get("Location", "")
            if resp.status_code not in (301, 302) or not location:
                raise JwchLoginError("教务系统登录校验失败")

            params = parse_qs(urlparse(location).query)
            token = params.get("token", [""])[0]
            login_id = params.get("id", [""])[0]
            login_num = params.get("num", [""])[0]
            if not token or not login_id or not login_num:
                raise JwchLoginError("教务系统登录响应缺少必要参数")

            # 3 – SSO login
            resp = self.session.post(
                SSO_LOGIN_URL,
                headers={"X-Requested-With": "XMLHttpRequest"},
                data={"token": token},
                timeout=JWCH_LOGIN_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            sso_payload = resp.json()
            if sso_payload.get("code") != 200:
                raise JwchLoginError(sso_payload.get("info") or "SSO 登录失败")

            # 4 – Bootstrap the :81 authenticated session
            resp = self.session.get(
                LOGINCHK_URL,
                headers={"Referer": f"{JWCH_PORTAL}/", "Origin": JWCH_PORTAL},
                params={
                    "id": login_id,
                    "num": login_num,
                    "ssourl": BASE_URL,
                    "hosturl": JWCH_PREFIX,
                    "ssologin": "",
                },
                timeout=JWCH_LOGIN_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
            if resp.status_code not in (301, 302):
                raise JwchLoginError("教务系统会话初始化失败")

            location = resp.headers.get("Location", "")
            match = re.search(r"id=(\d+)", location)
            if not match:
                raise JwchLoginError("未能获取教务会话标识")
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
        image_type = imghdr.what(None, image_bytes) or "gif"
        data_url = f"data:image/{image_type};base64,{base64.b64encode(image_bytes).decode()}"
        try:
            resp = requests.post(CAPTCHA_AI_URL, data={"validateCode": data_url}, timeout=JWCH_CAPTCHA_TIMEOUT_SECONDS, verify=False)
            if resp.status_code == 200:
                payload = resp.json()
                code = payload.get("message") or payload.get("data") or ""
                if code:
                    return str(code).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Captcha recognition failed: %s", exc)

        try:
            b64 = base64.b64encode(image_bytes).decode()
            resp = requests.post(CAPTCHA_AI_URL.rsplit("?", 1)[0], json={"image": b64}, timeout=JWCH_CAPTCHA_TIMEOUT_SECONDS, verify=False)
            if resp.status_code == 200:
                return str(resp.json().get("data", "")).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Captcha recognition fallback failed: %s", exc)
        return ""

    def validate_session(self) -> bool:
        """Validate that the current cookies still map to an active JWCH session."""
        self._require_login()
        self._get(COURSES_URL)
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def _request_params(self, url: str) -> Dict[str, str] | None:
        if not self.identifier:
            return None
        query = parse_qs(urlparse(url).query)
        if query.get("id"):
            return None
        return {"id": self.identifier}

    def _get(self, url: str) -> BeautifulSoup:
        params = self._request_params(url)
        resp = self.session.get(url, params=params, headers={"Referer": f"{JWCH_PORTAL}/"}, timeout=JWCH_QUERY_TIMEOUT_SECONDS, allow_redirects=False)
        if resp.status_code in (301, 302):
            raise JwchSessionError("教务系统会话已过期，请重新登录")
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        if "重新登录" in resp.text or "处理URL失败" in resp.text:
            raise JwchSessionError("教务系统会话已过期，请重新登录")
        return BeautifulSoup(resp.text, "html.parser")

    def _post(self, url: str, data: Dict[str, str]) -> BeautifulSoup:
        params = self._request_params(url)
        resp = self.session.post(
            url,
            params=params,
            headers={"Referer": f"{JWCH_PORTAL}/", "Origin": JWCH_PREFIX},
            data=data,
            timeout=JWCH_QUERY_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
        if resp.status_code in (301, 302):
            raise JwchSessionError("教务系统会话已过期，请重新登录")
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        if "重新登录" in resp.text or "处理URL失败" in resp.text:
            raise JwchSessionError("教务系统会话已过期，请重新登录")
        return BeautifulSoup(resp.text, "html.parser")

    def _extract_state(self, soup: BeautifulSoup) -> Dict[str, str]:
        return {
            "__VIEWSTATE": (soup.find(id="__VIEWSTATE") or {}).get("value", ""),
            "__EVENTVALIDATION": (soup.find(id="__EVENTVALIDATION") or {}).get("value", ""),
            "__VIEWSTATEGENERATOR": (soup.find(id="__VIEWSTATEGENERATOR") or {}).get("value", ""),
        }

    def _get_course_terms(self) -> Dict[str, Any]:
        soup = self._get(COURSES_URL)
        state = self._extract_state(soup)
        options = soup.select("#ContentPlaceHolder1_DDL_xnxq option")
        terms = [option.get("value", "").strip() for option in options if option.get("value", "").strip()]
        if not terms:
            raise JwchError("未找到课表学期列表")
        return {
            "terms": terms,
            "view_state": state.get("__VIEWSTATE", ""),
            "event_validation": state.get("__EVENTVALIDATION", ""),
            "view_state_generator": state.get("__VIEWSTATEGENERATOR", ""),
        }

    def _get_exam_room_terms_state(self) -> Dict[str, Any]:
        soup = self._get(EXAM_ROOM_URL)
        state = self._extract_state(soup)
        options = soup.select("#ContentPlaceHolder1_DDL_xnxq option")
        terms = [
            normalize_semester_code(option.get("value", ""))
            for option in options
            if normalize_semester_code(option.get("value", ""))
        ]
        if not terms:
            raise JwchError("未找到考场查询学期列表")
        return {
            "terms": terms,
            "view_state": state.get("__VIEWSTATE", ""),
            "event_validation": state.get("__EVENTVALIDATION", ""),
        }

    def _parse_credit_table(self, table: BeautifulSoup) -> List[Dict[str, str]]:
        rows = table.find_all("tr")
        temp: List[List[str]] = [[], [], []]
        for index, row in enumerate(rows[:3]):
            for cell in row.find_all("td"):
                text = _text_content(cell)
                if text != "查":
                    temp[index].append(text)

        stats: List[Dict[str, str]] = []
        count = min(len(temp[0]), len(temp[1]), len(temp[2]))
        for index in range(count):
            type_name = temp[0][index].strip()
            if not type_name or "情况" in type_name:
                continue
            stats.append(
                {
                    "type": type_name,
                    "gain": temp[2][index].strip(),
                    "total": temp[1][index].strip(),
                }
            )
        return stats

    def _split_exam_schedule(self, value: str) -> Tuple[str, str, str]:
        if not value:
            return "", "", "暂无考场数据"
        parts = value.split()
        if len(parts) < 3:
            return value, "", "暂无考场数据"
        return parts[0], parts[1], " ".join(parts[2:])

    def _build_cultivate_plan_url(self, href: str) -> str:
        match = re.search(r"javascript:pop1\('([^']+)'\)", href or "")
        path = (match.group(1) if match else href or "").strip()
        if not path:
            return ""
        if path.startswith("http"):
            return path
        if path.startswith("/"):
            return f"{JWCH_PREFIX}{path}"
        return f"{JWCH_PREFIX}/pyfa/pyjh/{path.lstrip('./')}"

    def _selection_request(
        self,
        path: str,
        data: Dict[str, str] | None = None,
        referer: str | None = None,
        allow_redirects: bool = True,
    ) -> requests.Response:
        url = path if path.startswith("http") else f"{JWCH_PREFIX}{path}"
        params = {"id": self.identifier} if self.identifier else None
        headers = {"Referer": referer or f"{JWCH_PREFIX}/Home/index"}
        if data is None:
            resp = self.session.get(url, params=params, headers=headers, timeout=JWCH_QUERY_TIMEOUT_SECONDS, allow_redirects=allow_redirects)
        else:
            resp = self.session.post(
                url,
                params=params,
                headers={**headers, "Origin": JWCH_PREFIX},
                data=data,
                timeout=JWCH_QUERY_TIMEOUT_SECONDS,
                allow_redirects=allow_redirects,
            )
        if not allow_redirects and resp.status_code in (301, 302):
            return resp
        if resp.status_code in (301, 302) and "login" in resp.headers.get("Location", "").lower():
            raise JwchSessionError("教务系统会话已过期，请重新登录")
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        if "重新登录" in resp.text or "处理URL失败" in resp.text:
            raise JwchSessionError("教务系统会话已过期，请重新登录")
        return resp

    def _selection_soup(
        self,
        path: str,
        data: Dict[str, str] | None = None,
        referer: str | None = None,
        allow_redirects: bool = True,
    ) -> BeautifulSoup:
        return BeautifulSoup(
            self._selection_request(path, data=data, referer=referer, allow_redirects=allow_redirects).text,
            "html.parser",
        )

    def _extract_alert_messages(self, soup: BeautifulSoup) -> List[str]:
        messages: List[str] = []
        for script in soup.find_all("script"):
            content = (script.string or script.get_text("\n")).strip()
            if not content:
                continue
            for match in re.finditer(r"window\.alert\(\s*['\"]([^'\"]+)['\"]\s*\)", content):
                text = match.group(1).replace("\\n", " ").strip()
                if text and text not in messages:
                    messages.append(text)
        return messages

    def _extract_selection_messages(self, soup: BeautifulSoup, label: str) -> List[str]:
        messages: List[str] = []
        alert_messages = self._extract_alert_messages(soup)
        for message in alert_messages:
            if message not in messages:
                messages.append(message)
        body = soup.body
        if not body:
            return messages
        for row in body.find_all("tr"):
            text = _text_content(row)
            if not text:
                continue
            if any(token in text for token in (label, "时间", "当前不是", "当前是")) and text not in messages:
                messages.append(text)
        return messages

    def _parse_selection_window(self, messages: List[str]) -> Dict[str, str]:
        for message in messages:
            normalized = _normalize_time_text(message).replace("当前不是", "").replace("当前是", "")
            match = SELECTION_TIME_RE.search(normalized)
            if not match:
                continue
            return {
                "label": match.group("label").strip(),
                "start": _normalize_time_text(match.group("start")),
                "end": _normalize_time_text(match.group("end")),
            }
        return {}

    def _selection_state(self, messages: List[str], window: Dict[str, str]) -> str:
        if any("不是" in message for message in messages):
            return "closed"
        if any("当前是" in message for message in messages):
            return "open"
        start = _parse_selection_datetime(window.get("start", ""))
        end = _parse_selection_datetime(window.get("end", ""))
        if start and end:
            now = datetime.now()
            if now < start:
                return "upcoming"
            if now <= end:
                return "open"
            return "closed"
        return "unknown"

    def _parse_general_credit_progress(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        rows = soup.find_all("tr")
        header_row = next(
            (
                row
                for row in rows
                if row.find(id="ContentPlaceHolder1_Label01")
                and row.find(id="ContentPlaceHolder1_Label06")
                and row.find_all("td", recursive=False)
                and _text_content(row.find_all("td", recursive=False)[0]) == ""
            ),
            None,
        )
        required_row = next((row for row in rows if row.find("td") and _text_content(row.find("td")) == "要求学分"), None)
        earned_row = next((row for row in rows if row.find("td") and _text_content(row.find("td")) == "已获学分"), None)
        if not header_row or not required_row or not earned_row:
            return []

        headers = [_text_content(cell) for cell in header_row.find_all("td")][1:]
        required_values = [_text_content(cell) for cell in required_row.find_all("td")][1:]
        earned_values = [_text_content(cell) for cell in earned_row.find_all("td")][1:]

        progress: List[Dict[str, Any]] = []
        for header, required, earned in zip(headers, required_values, earned_values):
            if not header:
                continue
            required_value = required or "0"
            earned_value = earned or "0"
            required_number = _parse_float(required_value) or 0.0
            earned_number = _parse_float(earned_value) or 0.0
            missing_number = max(0.0, required_number - earned_number)
            progress.append(
                {
                    "category": header,
                    "required": required_value,
                    "earned": earned_value,
                    "missing": str(int(missing_number)) if missing_number.is_integer() else f"{missing_number:.1f}",
                    "missing_value": missing_number,
                }
            )
        return progress

    def _find_selection_table(self, soup: BeautifulSoup) -> Tuple[List[str], List[Any]]:
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for index, row in enumerate(rows):
                header_cells = row.find_all(["td", "th"], recursive=False)
                if len(header_cells) < 5:
                    continue
                header_texts = [_text_content(cell) for cell in header_cells]
                if not any("课程名称" in text for text in header_texts):
                    continue
                return header_texts, rows[index + 1 :]
        return [], []

    def _extract_row_controls(self, row: Any) -> List[Dict[str, Any]]:
        controls: List[Dict[str, Any]] = []
        for tag in row.find_all(["input", "select", "textarea"]):
            name = tag.get("name", "").strip()
            if not name:
                continue
            control: Dict[str, Any] = {
                "tag": tag.name,
                "name": name,
                "id": tag.get("id", "").strip(),
                "type": (tag.get("type") or ("select" if tag.name == "select" else "textarea")).lower(),
                "value": tag.get("value", "") if tag.name != "textarea" else tag.get_text("", strip=False),
                "checked": tag.has_attr("checked"),
            }
            if tag.name == "select":
                selected = tag.find("option", selected=True) or tag.find("option")
                control["value"] = selected.get("value", "") if selected else ""
                control["options"] = [
                    {"value": option.get("value", ""), "label": _text_content(option)}
                    for option in tag.find_all("option")
                ]
            controls.append(control)
        return controls

    def _row_to_selection_course(self, headers: List[str], row: Any, include_controls: bool = False) -> Dict[str, Any]:
        cells = row.find_all("td")
        if not cells:
            return {}
        course: Dict[str, Any] = {}
        for index, cell in enumerate(cells):
            header = headers[index] if index < len(headers) else ""
            if not header or any(token in header for token in SELECTION_ACTION_HEADERS):
                continue
            key = _selection_header_key(header)
            if not key:
                continue
            value = _text_content(cell)
            course[key] = value
        if include_controls:
            course["controls"] = self._extract_row_controls(row)
        if not course.get("course_name"):
            texts = [_text_content(cell) for cell in cells if _text_content(cell)]
            if texts:
                start_index = 1 if texts[0] in SELECTION_STATUS_MARKERS else 0
                course["course_name"] = texts[start_index] if len(texts) > start_index else ""
                if texts[0] in SELECTION_STATUS_MARKERS:
                    course.setdefault("selection_status", texts[0])
        if include_controls:
            suffix = next(
                (
                    control["id"].rsplit("_", 1)[-1]
                    for control in course.get("controls", [])
                    if control.get("id") and "_" in control.get("id", "")
                ),
                "",
            )
            if suffix:
                course["suffix"] = suffix
        return course

    def _parse_selection_current_courses(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        headers, rows = self._find_selection_table(soup)
        if not headers:
            return []
        courses: List[Dict[str, Any]] = []
        seen: set[Tuple[str, str, str]] = set()
        for row in rows:
            if not row.get("onmouseover"):
                continue
            course = self._row_to_selection_course(headers, row)
            name = course.get("course_name", "")
            teacher = course.get("teacher", "")
            schedule = course.get("schedule", "")
            if not name:
                continue
            signature = (name, teacher, schedule)
            if signature in seen:
                continue
            seen.add(signature)
            courses.append(course)
        return courses

    def _parse_selection_candidates(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        headers, rows = self._find_selection_table(soup)
        candidates: List[Dict[str, Any]] = []
        seen: set[Tuple[str, str, str]] = set()
        for row in rows:
            if not row.find(["input", "select", "textarea"]):
                continue
            course = self._row_to_selection_course(headers, row, include_controls=True)
            name = course.get("course_name", "")
            teacher = course.get("teacher", "")
            schedule = course.get("schedule", "")
            if not name:
                continue
            signature = (name, teacher, schedule)
            if signature in seen:
                continue
            seen.add(signature)
            candidates.append(course)
        return candidates

    def _selection_form_defaults(self, soup: BeautifulSoup) -> Tuple[Dict[str, str], str, str]:
        form = soup.find("form")
        if not form:
            raise JwchError("未找到选课提交表单")

        payload: Dict[str, str] = {}
        submit_name = ""
        submit_value = ""

        for tag in form.find_all(["input", "select", "textarea"]):
            name = tag.get("name", "").strip()
            if not name:
                continue

            if tag.name == "select":
                selected = tag.find("option", selected=True) or tag.find("option")
                payload[name] = selected.get("value", "") if selected else ""
                continue

            if tag.name == "textarea":
                payload[name] = tag.get_text("", strip=False)
                continue

            input_type = (tag.get("type") or "text").lower()
            if input_type in {"submit", "button", "reset", "file", "image"}:
                if not submit_name and "确定" in tag.get("value", ""):
                    submit_name = name
                    submit_value = tag.get("value", "")
                continue
            if input_type in {"checkbox", "radio"}:
                if tag.has_attr("checked"):
                    payload[name] = tag.get("value", "on") or "on"
                continue
            payload[name] = tag.get("value", "")

        if not submit_name:
            for button_name in ("ctl00$ContentPlaceHolder1$Button_xk", "ctl00$ContentPlaceHolder1$Button1"):
                if form.find(attrs={"name": button_name}):
                    submit_name = button_name
                    submit_value = form.find(attrs={"name": button_name}).get("value", "确定选课")
                    break
        return payload, submit_name, submit_value

    def _apply_course_selection(self, payload: Dict[str, str], course: Dict[str, Any], points: str = "") -> None:
        controls = course.get("controls") or []
        radio_or_checkbox = next(
            (control for control in controls if control.get("type") in {"radio", "checkbox"}),
            None,
        )
        if not radio_or_checkbox:
            raise JwchError("未找到可提交的选课控件")

        payload[radio_or_checkbox["name"]] = str(radio_or_checkbox.get("value") or "on")

        requested_points = points.strip()
        for control in controls:
            control_type = control.get("type")
            name = control.get("name", "")
            if not name:
                continue
            if control_type == "text":
                default_value = str(control.get("value") or "")
                if any(token in name.lower() for token in ("jf", "积分")):
                    if not requested_points and not default_value:
                        raise JwchError("该课程需要填写所投积分，请在选课时明确提供积分")
                    payload[name] = requested_points or default_value
                    continue
                payload[name] = default_value
            elif control_type == "select":
                options = control.get("options") or []
                payload[name] = next((option["value"] for option in options if "免听" not in option.get("label", "")), control.get("value", ""))
            elif control_type == "textarea":
                payload[name] = str(control.get("value") or "")

    def _public_course_entry(self, course: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "course_name": course.get("course_name", ""),
            "teacher": course.get("teacher", ""),
            "course_type": course.get("course_type") or course.get("elective_type", ""),
            "credits": course.get("credits", ""),
            "schedule": course.get("schedule", ""),
            "selection_status": course.get("selection_status") or course.get("audit_status", ""),
            "points": course.get("points", ""),
            "remark": course.get("remark", ""),
        }

    def _resolve_selection_category(self, category: str) -> Dict[str, Any]:
        normalized = _normalize_match_text(category)
        for config in SELECTION_CATEGORY_CONFIG:
            values = [config["key"], config["label"], *config.get("aliases", ())]
            if any(_normalize_match_text(value) == normalized for value in values if value):
                return dict(config)
        raise JwchError("未识别的选课类别，请使用学期选课、通识选修课、重新学习选课、辅修专业选课、院选课、国情类选课或特殊补选")

    def get_course_selection_overview(self) -> Dict[str, Any]:
        """Return selection windows, current courses, candidate rows and general-elective gaps."""
        self._require_login()

        categories: List[Dict[str, Any]] = []
        needed_credit_types: List[Dict[str, Any]] = []
        for config in SELECTION_CATEGORY_CONFIG:
            status_soup = self._selection_soup(config["status_path"])
            list_soup = self._selection_soup(config["list_path"], referer=f"{JWCH_PREFIX}{config['status_path']}")

            status_messages = self._extract_selection_messages(status_soup, config["label"])
            list_alerts = self._extract_alert_messages(list_soup)
            window = self._parse_selection_window(status_messages + list_alerts)
            current_courses = self._parse_selection_current_courses(status_soup)
            candidates = self._parse_selection_candidates(list_soup)
            state = self._selection_state(status_messages + list_alerts, window)

            info: Dict[str, Any] = {
                "key": config["key"],
                "label": config["label"],
                "status": state,
                "status_message": status_messages[0] if status_messages else (list_alerts[0] if list_alerts else ""),
                "time_window": window,
                "current_course_count": len(current_courses),
                "selected_count": sum(1 for course in current_courses if course.get("selection_status") in SELECTION_STATUS_MARKERS),
                "candidate_count": len(candidates),
                "current_courses": [self._public_course_entry(course) for course in current_courses[:20]],
                "candidates": [self._public_course_entry(course) for course in candidates[:20]],
                "alerts": list_alerts,
            }

            if config["key"] == "general":
                progress = self._parse_general_credit_progress(status_soup)
                info["credit_progress"] = progress
                info["needed_credit_types"] = [entry for entry in progress if entry.get("missing_value", 0) > 0]
                needed_credit_types.extend(info["needed_credit_types"])

            categories.append(info)

        return {
            "mode": "overview",
            "generated_at": datetime.now().isoformat(),
            "categories": categories,
            "needed_credit_types": needed_credit_types,
        }

    def select_course(
        self,
        category: str,
        course_name: str,
        teacher: str = "",
        points: str = "",
    ) -> Dict[str, Any]:
        """Submit a selection request for one explicitly specified course."""
        self._require_login()
        if not course_name.strip():
            raise JwchError("请提供要选的课程名称")

        config = self._resolve_selection_category(category)
        overview = self.get_course_selection_overview()
        category_info = next((item for item in overview["categories"] if item.get("key") == config["key"]), None)
        if category_info and category_info.get("status") not in {"open", "unknown"}:
            window = category_info.get("time_window") or {}
            window_text = ""
            if window.get("start") and window.get("end"):
                window_text = f"（时间：{window['start']} 至 {window['end']}）"
            raise JwchError(f"{config['label']}当前不可提交选课{window_text}")

        response = self._selection_request(config["list_path"], referer=f"{JWCH_PREFIX}{config['status_path']}")
        soup = BeautifulSoup(response.text, "html.parser")
        candidates = self._parse_selection_candidates(soup)
        if not candidates:
            raise JwchError(f"{config['label']}当前没有可操作的候选课程")

        normalized_name = _normalize_match_text(course_name)
        normalized_teacher = _normalize_match_text(teacher)
        matched = [
            course
            for course in candidates
            if _normalize_match_text(course.get("course_name", "")) == normalized_name
        ]
        if normalized_teacher:
            matched = [
                course
                for course in matched
                if _normalize_match_text(course.get("teacher", "")) == normalized_teacher
            ]

        if not matched:
            available = "、".join(sorted({course.get("course_name", "") for course in candidates if course.get("course_name")}))
            raise JwchError(f"在{config['label']}中未找到完全匹配的课程《{course_name}》。当前候选课程：{available or '无'}")
        if len(matched) > 1:
            names = "、".join(
                f"《{course.get('course_name', '')}》/{course.get('teacher', '教师未知')}"
                for course in matched
            )
            raise JwchError(f"匹配到多门同名课程，请补充教师信息后重试：{names}")

        target_course = matched[0]
        payload, submit_name, submit_value = self._selection_form_defaults(soup)
        self._apply_course_selection(payload, target_course, points=points)
        if submit_name:
            payload[submit_name] = submit_value or "确定选课"

        result_resp = self._selection_request(
            config["list_path"],
            data=payload,
            referer=response.url,
            allow_redirects=True,
        )
        result_soup = BeautifulSoup(result_resp.text, "html.parser")
        alerts = self._extract_alert_messages(result_soup)
        refreshed_status = self._selection_soup(config["status_path"], referer=result_resp.url)
        current_courses = self._parse_selection_current_courses(refreshed_status)
        success = any(
            _normalize_match_text(course.get("course_name", "")) == normalized_name
            and (not normalized_teacher or _normalize_match_text(course.get("teacher", "")) == normalized_teacher)
            and course.get("selection_status") in SELECTION_STATUS_MARKERS
            for course in current_courses
        )

        if success:
            status = "success"
            message = f"已在{config['label']}中选上《{course_name}》"
        elif alerts:
            status = "error"
            message = alerts[0]
        else:
            status = "submitted"
            message = f"已提交{config['label']}选课请求，请以教务系统结果页为准"

        return {
            "mode": "submit",
            "status": status,
            "message": message,
            "category": config["key"],
            "category_label": config["label"],
            "course": self._public_course_entry(target_course),
            "points": points.strip(),
            "alerts": alerts,
            "current_course_count": len(current_courses),
        }

    def get_marks(self) -> List[Dict[str, Any]]:
        """Return all course grades."""
        self._require_login()
        soup = self._get(MARKS_URL)
        marks: List[Dict[str, Any]] = []
        table = soup.find("table", id="ContentPlaceHolder1_DataList_xxk") or soup.find(
            "table", class_="dataList"
        )
        if not table:
            return marks
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 10 or len(cells) > 13:
                continue
            values = [cell.get_text(strip=True).replace("\xa0", " ") for cell in cells]
            if (
                not values
                or values[0] == "修读类别"
                or values[0].startswith("修读类别开课学期课程名称计划学分")
                or values[2] == "课程名称"
                or values[1:5] == ["修读类别", "开课学期", "课程名称", "计划学分"]
            ):
                continue
            semester_code = normalize_semester_code(values[1])
            marks.append(
                {
                    "type": values[0],
                    "semester": format_semester_label(semester_code),
                    "semester_code": semester_code,
                    "name": values[2],
                    "credits": values[3],
                    "score": values[4],
                    "gpa": values[5] if len(values) > 5 else "",
                    "earned_credits": values[6] if len(values) > 6 else "",
                    "elective_type": values[7] if len(values) > 7 else "",
                    "exam_type": values[8] if len(values) > 8 else "",
                    "teacher": values[9] if len(values) > 9 else "",
                    "schedule": values[10] if len(values) > 10 else "",
                    "exam_info": values[11] if len(values) > 11 else "",
                }
            )
        return marks

    def get_courses(self) -> List[Dict[str, Any]]:
        """Return the current semester's course schedule."""
        self._require_login()
        course_terms = self._get_course_terms()
        soup = self._post(
            COURSES_URL,
            {
                "ctl00$ContentPlaceHolder1$DDL_xnxq": course_terms["terms"][0],
                "ctl00$ContentPlaceHolder1$BT_submit": "确定",
                "__VIEWSTATE": course_terms["view_state"],
                "__EVENTVALIDATION": course_terms["event_validation"],
            },
        )
        courses: List[Dict[str, Any]] = []
        table = soup.find("table", id="ContentPlaceHolder1_DataList_xxk")
        if not table:
            return courses
        for row in table.find_all("tr")[2:]:
            if not row.get("style"):
                continue
            cells = row.find_all("td")
            if len(cells) < 12:
                continue
            schedule = cells[8].get_text("\n", strip=True).replace("\xa0", " ")
            location = ""
            time = schedule
            schedule_lines = [line.strip() for line in schedule.splitlines() if line.strip()]
            if schedule_lines:
                first_line_parts = schedule_lines[0].split()
                if len(first_line_parts) >= 3:
                    location = first_line_parts[-1]
            credits_node = cells[4].find("span")
            courses.append(
                {
                    "name": cells[1].get_text(strip=True),
                    "teacher": cells[7].get_text(strip=True),
                    "credits": credits_node.get_text(strip=True) if credits_node else cells[4].get_text(strip=True),
                    "time": time,
                    "location": location,
                    "exam_time": cells[9].get_text("\n", strip=True).replace("\xa0", " "),
                    "remark": cells[10].get_text(strip=True),
                    "adjust": cells[11].get_text("\n", strip=True).replace("\xa0", " "),
                    "semester": format_semester_label(course_terms["terms"][0]),
                    "semester_code": course_terms["terms"][0],
                }
            )
        return courses

    def get_student_info(self) -> Dict[str, Any]:
        """Return the student's profile information."""
        self._require_login()
        soup = self._get(USER_INFO_URL)
        field_ids = {
            "学号": "ContentPlaceHolder1_LB_xh",
            "姓名": "ContentPlaceHolder1_LB_xm",
            "生日": "ContentPlaceHolder1_LB_csrq",
            "性别": "ContentPlaceHolder1_LB_xb",
            "电话": "ContentPlaceHolder1_LB_lxdh",
            "邮箱": "ContentPlaceHolder1_LB_email",
            "学院": "ContentPlaceHolder1_LB_xymc",
            "年级": "ContentPlaceHolder1_LB_nj",
            "专业": "ContentPlaceHolder1_LB_zymc",
            "辅导员": "ContentPlaceHolder1_LB_zdy",
            "考生类别": "ContentPlaceHolder1_LB_kslb",
            "民族": "ContentPlaceHolder1_LB_mz",
            "国别": "ContentPlaceHolder1_LB_gb",
            "政治面貌": "ContentPlaceHolder1_LB_zzmm",
            "生源地": "ContentPlaceHolder1_LB_xssy",
        }
        info: Dict[str, Any] = {}
        for label, element_id in field_ids.items():
            node = soup.find(id=element_id)
            if not node:
                continue
            value = node.get_text(strip=True)
            if value:
                info[label] = value
        if info:
            return info

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
        scores = self._parse_exam_scores(CET_URL, "英语等级考试")
        scores.extend(self._parse_exam_scores(JS_URL, "计算机等级考试"))
        return scores

    def get_credit_statistics(self) -> Dict[str, List[Dict[str, str]]]:
        """Return grouped credit statistics for major / minor programmes."""
        self._require_login()
        soup = self._get(CREDIT_URL)
        container = soup.find(id="ContentPlaceHolder1_LB_kb")
        if not container:
            raise JwchError("未找到学分统计区域")

        tables = container.find_all("table", recursive=False) or container.find_all("table")
        if not tables:
            raise JwchError("未找到学分统计表格")
        tables = tables[:-1] if len(tables) > 1 else tables

        grouped = {"major": [], "minor": []}
        for index, table in enumerate(tables):
            stats = self._parse_credit_table(table)
            if index == 0:
                grouped["major"] = stats
            else:
                grouped["minor"].extend(stats)
        return grouped

    def get_gpa_ranking(self) -> Dict[str, Any]:
        """Return GPA / ranking data shown by the educational system."""
        self._require_login()
        soup = self._get(GPA_URL)
        time_text = _text_content(soup.find(id="ContentPlaceHolder1_Label1"))
        table = soup.find(id="ContentPlaceHolder1_DataList_xxk")
        if not table:
            return {"time": time_text, "items": []}

        rows = [row for row in table.find_all("tr") if row.find_all("td", attrs={"align": "center"})]
        if not rows:
            return {"time": time_text, "items": []}

        unique_rows = []
        seen_row_values = set()
        for row in rows:
            cells = row.find_all("td", attrs={"align": "center"}) or row.find_all("td")
            row_values = tuple(_text_content(cell) for cell in cells)
            if not any(row_values) or row_values in seen_row_values:
                continue
            seen_row_values.add(row_values)
            unique_rows.append(row)
        rows = unique_rows
        if not rows:
            return {"time": time_text, "items": []}

        title_row = next(
            (
                row
                for row in rows
                if "background:#efefef" in row.get("style", "").replace(" ", "").lower()
            ),
            rows[0],
        )
        headers = [_text_content(cell) for cell in title_row.find_all("td", attrs={"align": "center"})]
        if not headers:
            headers = [_text_content(cell) for cell in title_row.find_all(["td", "th"])]
        headers = [header for header in headers if header]
        if not headers:
            return {"time": time_text, "items": []}

        items: List[Dict[str, str]] = []
        title_index = rows.index(title_row)
        for row in rows[title_index + 1 :]:
            cells = row.find_all("td", attrs={"align": "center"}) or row.find_all("td")
            values = [_text_content(cell) for cell in cells]
            if len(values) < len(headers):
                continue
            for header, value in zip(headers, values):
                if header:
                    items.append({"type": header, "value": value})
        return {"time": time_text, "items": items}

    def get_exam_room_terms(self) -> List[str]:
        """Return the term codes available for exam-room queries."""
        self._require_login()
        return self._get_exam_room_terms_state()["terms"]

    def get_exam_rooms(self, term_code: str | None = None) -> Dict[str, Any]:
        """Return exam-room information for the selected term."""
        self._require_login()
        term_state = self._get_exam_room_terms_state()
        terms = term_state["terms"]
        selected_term = normalize_semester_code(term_code or "")
        if selected_term not in terms:
            selected_term = terms[0]

        soup = self._post(
            EXAM_ROOM_URL,
            {
                "__VIEWSTATE": term_state["view_state"],
                "__EVENTVALIDATION": term_state["event_validation"],
                "ctl00$ContentPlaceHolder1$DDL_xnxq": selected_term,
                "ctl00$ContentPlaceHolder1$BT_submit": "确定",
            },
        )
        table = soup.find(id="ContentPlaceHolder1_DataList_xxk")
        exams: List[Dict[str, str]] = []
        if table:
            for row in table.select("tr[onmouseover]"):
                cells = row.find_all("td")
                if len(cells) < 4:
                    continue
                date, time, location = self._split_exam_schedule(_text_content(cells[3]))
                exams.append(
                    {
                        "course_name": _text_content(cells[0]),
                        "credit": _text_content(cells[1]),
                        "teacher": _text_content(cells[2]),
                        "date": date,
                        "time": time,
                        "location": location,
                    }
                )
        return {
            "term": selected_term,
            "term_label": format_semester_label(selected_term),
            "available_terms": terms,
            "exams": exams,
        }

    def get_school_calendar(self) -> Dict[str, Any]:
        """Return recent school-calendar terms and the current term."""
        self._require_login()
        soup = self._get(SCHOOL_CALENDAR_URL)
        current_term_text = _text_content(soup.select_one("center div") or soup.find("div"))
        match = re.search(r"当前学期[:：]\s*(20\d{2}0[12])", current_term_text)

        terms: List[Dict[str, str]] = []
        for option in soup.select('select[name="xq"] option'):
            raw_value = option.get("value", "").strip()
            if len(raw_value) < 22:
                continue
            term_code = normalize_semester_code(raw_value)
            start_raw = raw_value[6:14]
            end_raw = raw_value[14:22]
            start_date = f"{start_raw[0:4]}-{start_raw[4:6]}-{start_raw[6:8]}" if len(start_raw) == 8 else ""
            end_date = f"{end_raw[0:4]}-{end_raw[4:6]}-{end_raw[6:8]}" if len(end_raw) == 8 else ""
            terms.append(
                {
                    "term_id": raw_value,
                    "school_year": raw_value[0:4],
                    "term": term_code,
                    "term_label": format_semester_label(term_code),
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )
            if len(terms) >= 16:
                break

        current_term = match.group(1) if match else (terms[0]["term"] if terms else "")
        return {
            "current_term": current_term,
            "current_term_label": format_semester_label(current_term) if current_term else "",
            "terms": terms,
        }

    def get_term_events(self, term_id: str) -> Dict[str, Any]:
        """Return school-calendar events for a specific term id."""
        self._require_login()
        soup = self._post(SCHOOL_CALENDAR_URL, {"xq": term_id, "submit": "提交"})

        tables = soup.find_all("table")
        detail_row = None
        if len(tables) >= 2:
            detail_row = tables[1].find("tr")

        events: List[Dict[str, str]] = []
        raw_detail = _text_content(detail_row)
        for event in re.split(r"[；;]", raw_detail):
            event = event.strip()
            if not event:
                continue
            match = re.match(r"(\d{4}-\d{2}-\d{2})(?:\s*至\s*(\d{4}-\d{2}-\d{2}))?\s*为\s*(.+)", event)
            if match:
                start_date = match.group(1)
                end_date = match.group(2) or start_date
                name = match.group(3).strip()
                events.append(
                    {
                        "name": name,
                        "start_date": start_date,
                        "end_date": end_date,
                    }
                )
            else:
                events.append({"name": event, "start_date": "", "end_date": ""})

        term_code = normalize_semester_code(term_id)
        return {
            "term_id": term_id,
            "term": term_code,
            "term_label": format_semester_label(term_code),
            "school_year": term_id[:4],
            "events": events,
        }

    def get_cultivate_plan(self) -> Dict[str, Any]:
        """Return the cultivate-plan details matched to the current student's major."""
        self._require_login()
        info = self.get_student_info()
        grade = info.get("年级", "")
        college = info.get("学院", "")
        major = info.get("专业", "")
        if not grade or not college or not major:
            raise JwchError("未能获取完整的学生学籍信息，无法匹配培养方案")

        initial_soup = self._get(CULTIVATE_PLAN_URL)
        state = self._extract_state(initial_soup)
        view_state_generator = state.get("__VIEWSTATEGENERATOR", "")

        def match_college_code() -> str:
            college_select = initial_soup.find("select", id="xymcdpl")
            if not college_select:
                return ""
            for option in college_select.find_all("option"):
                option_text = _text_content(option)
                option_value = option.get("value", "").strip()
                if not option_value:
                    continue
                if _normalize_match_text(option_text) == _normalize_match_text(college):
                    return option_value
                if "数学与计算机" in college and (
                    "计算机与大数据" in option_text or "数学与统计" in option_text
                ):
                    return option_value
            return ""

        def precise_match() -> str:
            college_code = match_college_code()
            if not college_code:
                return ""
            major_soup = self._post(
                CULTIVATE_PLAN_URL,
                {
                    "__VIEWSTATE": state.get("__VIEWSTATE", ""),
                    "__EVENTVALIDATION": state.get("__EVENTVALIDATION", ""),
                    "__EVENTTARGET": "ctl00$njdpl",
                    "__EVENTARGUMENT": "",
                    "__VIEWSTATEGENERATOR": view_state_generator,
                    "ctl00$njdpl": grade,
                    "ctl00$xymcdpl": college_code,
                    "ctl00$dldpl": "<-全部->",
                    "ctl00$zymcdpl": "<-全部->",
                    "ctl00$zylbdpl": "本专业",
                    "ctl00$ContentPlaceHolder1$DDL_syxw": "<-全部->",
                    "ctl00$ContentPlaceHolder1$BT_submit": "确定",
                },
            )
            major_select = major_soup.find("select", id="zymcdpl")
            if not major_select:
                return ""
            for option in major_select.find_all("option"):
                option_text = _text_content(option)
                option_value = option.get("value", "").strip()
                if option_value and _normalize_match_text(option_text) == _normalize_match_text(major):
                    return (
                        f"{JWCH_PREFIX}/pyfa/pyjh/pyfa_bzy.aspx?"
                        f"nj={grade}&xyh={college_code}&zyh={option_value}&zylb=本专业&id={self.identifier}"
                    )
            return ""

        url = precise_match()
        if not url:
            result_soup = self._post(
                CULTIVATE_PLAN_URL,
                {
                    "__VIEWSTATE": state.get("__VIEWSTATE", ""),
                    "__EVENTVALIDATION": state.get("__EVENTVALIDATION", ""),
                    "__EVENTTARGET": "",
                    "__EVENTARGUMENT": "",
                    "__VIEWSTATEGENERATOR": view_state_generator,
                    "ctl00$njdpl": grade,
                    "ctl00$dldpl": "<-全部->",
                    "ctl00$xymcdpl": "<-全部->",
                    "ctl00$zymcdpl": "<-全部->",
                    "ctl00$zylbdpl": "本专业",
                    "ctl00$ContentPlaceHolder1$DDL_syxw": "<-全部->",
                    "ctl00$ContentPlaceHolder1$BT_submit": "确定",
                },
            )
            major_key = _normalize_match_text(major)
            for row in result_soup.find_all("tr"):
                link = row.find("a", href=True)
                if not link or "pyfa" not in (link.get("href") or ""):
                    continue
                row_text = _normalize_match_text(_text_content(row))
                if re.search(rf"^（.*?）{re.escape(major_key)}$", row_text):
                    url = self._build_cultivate_plan_url(link.get("href", ""))
                    break

        if not url:
            raise JwchError("未找到与当前专业匹配的培养方案")

        details = _extract_cultivate_plan_details(self._get(url))

        return {
            "url": url,
            "grade": grade,
            "college": college,
            "major": major,
            "title": details.get("title", ""),
            "document_title": details.get("document_title", ""),
            "text_blocks": details.get("text_blocks", []),
            "sections": details.get("sections", []),
            "outline": details.get("outline", []),
            "chapters": details.get("chapters", []),
        }

    def _parse_exam_scores(self, url: str, default_name: str) -> List[Dict[str, Any]]:
        soup = self._get(url)
        scores: List[Dict[str, Any]] = []
        table = soup.find("table", id="ContentPlaceHolder1_DataList_xxk")
        if not table:
            return scores
        for row in table.find_all("tr"):
            if not row.get("onmouseover") and not row.get("style"):
                continue
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            exam_name = cells[0].get_text(strip=True) or default_name
            term = normalize_semester_code(cells[1].get_text(strip=True))
            score = cells[2].get_text(strip=True)
            if not exam_name or not term or not score or not SEMESTER_CODE_RE.fullmatch(term):
                continue
            scores.append(
                {
                    "exam_name": exam_name,
                    "score": score,
                    "date": format_semester_label(term),
                    "semester": format_semester_label(term),
                    "semester_code": term,
                    "category": default_name,
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
