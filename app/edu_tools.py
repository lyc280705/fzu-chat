"""LangGraph tools for querying FZU educational systems.

These tools wrap :mod:`app.jwch_client` and expose grade / course / profile
information to the LLM agent.  Each tool reads the current user's educational
session from a request-local context variable (set by the request handler in
``server.py`` before the graph is invoked).
"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime
import logging
import re
from typing import Any, Dict, List, Tuple

from langchain_core.tools import tool

from .jwch_client import (
    JwchClient,
    JwchError,
    SELECTION_CATEGORY_CONFIG,
    format_semester_label,
    normalize_semester_code,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request-local storage for the current request's edu session.
# The server sets this before each graph invocation.
# ---------------------------------------------------------------------------
_edu_session_var: ContextVar[Dict[str, Any] | None] = ContextVar("edu_session", default=None)


def set_current_edu_session(session: Dict[str, Any] | None) -> None:
    """Store the educational-system session for the current request context."""
    _edu_session_var.set(session)


def get_current_edu_session() -> Dict[str, Any] | None:
    """Return the educational-system session for the current request context."""
    return _edu_session_var.get()


def _resolve_edu_session(edu_session: Dict[str, Any] | None = None) -> Dict[str, Any] | None:
    return edu_session or get_current_edu_session()


def _build_client(edu_session: Dict[str, Any] | None = None) -> JwchClient:
    """Build a :class:`JwchClient` from the current request session, or raise."""
    session = _resolve_edu_session(edu_session)
    if not session or not session.get("edu_authenticated"):
        status_message = str((session or {}).get("edu_status_message") or "").strip()
        raise JwchError(status_message or "当前用户尚未登录教务系统，无法查询教务信息。请先使用学号和密码登录。")
    cookies = session.get("edu_cookies") or []
    student_id = session.get("user_id", "")
    identifier = session.get("edu_identifier", "")
    return JwchClient.from_cookies(student_id, cookies, identifier)


def _sorted_semester_codes(codes: List[str]) -> List[str]:
    return sorted(codes, key=lambda value: int(re.sub(r"\D", "", value) or 0), reverse=True)


def _current_semester_code(now: datetime | None = None) -> str:
    current = now or datetime.now()
    if current.month >= 8:
        return f"{current.year}01"
    if current.month == 1:
        return f"{current.year - 1}01"
    return f"{current.year - 1}02"


def _semester_aliases(code: str) -> set[str]:
    label = format_semester_label(code)
    match = re.fullmatch(r"(20\d{2})(0[12])", code)
    aliases = {code, label, label.replace("-", ""), label.replace("学年", "")}
    if not match:
        return aliases

    start_year = int(match.group(1))
    end_year = start_year + 1
    if match.group(2) == "01":
        aliases.update(
            {
                f"{start_year}-{end_year}学年第一学期",
                f"{start_year}至{end_year}学年第一学期",
                f"{start_year}秋季",
                f"{start_year}年秋季",
                f"{start_year}秋季学期",
                f"{start_year}年秋季学期",
            }
        )
    else:
        aliases.update(
            {
                f"{start_year}-{end_year}学年第二学期",
                f"{start_year}至{end_year}学年第二学期",
                f"{end_year}春季",
                f"{end_year}年春季",
                f"{end_year}春季学期",
                f"{end_year}年春季学期",
            }
        )
    return {alias.replace(" ", "") for alias in aliases if alias}


def _normalize_query_text(query: str) -> str:
    return re.sub(r"\s+", "", query or "")


def _find_matching_term_codes(query: str, available_codes: List[str]) -> List[str]:
    normalized_query = _normalize_query_text(query)
    if not normalized_query:
        return []
    return [code for code in available_codes if any(alias in normalized_query for alias in _semester_aliases(code))]


def _looks_like_semester_query(query: str) -> bool:
    normalized_query = _normalize_query_text(query)
    if not normalized_query:
        return False
    if re.search(r"20\d{2}", normalized_query):
        return True
    return any(
        token in normalized_query
        for token in ("学期", "春季", "秋季", "本学期", "这学期", "当前学期", "最新学期", "最近学期", "上学期", "上一学期")
    )


def _resolve_grade_semester_filter(query: str, marks: List[Dict[str, Any]]) -> Tuple[List[str], bool]:
    available_codes = _sorted_semester_codes(
        list(
            {
                normalize_semester_code(mark.get("semester_code") or mark.get("semester", ""))
                for mark in marks
                if mark.get("semester")
            }
        )
    )
    if not query or not available_codes:
        return [], False

    explicit_matches = _find_matching_term_codes(query, available_codes)
    if explicit_matches:
        return explicit_matches, True

    normalized_query = _normalize_query_text(query)
    if any(token in normalized_query for token in ("本学期", "这学期", "当前学期", "最新学期", "最近学期")):
        current_code = _current_semester_code()
        return ([current_code] if current_code in available_codes else available_codes[:1]), True

    if any(token in normalized_query for token in ("上学期", "上一学期")):
        current_code = _current_semester_code()
        if current_code in available_codes:
            current_index = available_codes.index(current_code)
            if current_index + 1 < len(available_codes):
                return [available_codes[current_index + 1]], True
        return available_codes[1:2], True

    if _looks_like_semester_query(query):
        return [], True
    return [], False


def _resolve_single_semester_code(
    query: str,
    available_codes: List[str],
    current_code: str | None = None,
) -> Tuple[str | None, bool]:
    ordered_codes = _sorted_semester_codes(list(dict.fromkeys(code for code in available_codes if code)))
    if not ordered_codes:
        return None, False

    explicit_matches = _find_matching_term_codes(query, ordered_codes)
    if explicit_matches:
        return explicit_matches[0], True

    normalized_query = _normalize_query_text(query)
    if any(token in normalized_query for token in ("本学期", "这学期", "当前学期", "最新学期", "最近学期")):
        if current_code and current_code in ordered_codes:
            return current_code, True
        return ordered_codes[0], True

    if any(token in normalized_query for token in ("上学期", "上一学期")):
        base_code = current_code if current_code in ordered_codes else ordered_codes[0]
        current_index = ordered_codes.index(base_code)
        if current_index + 1 < len(ordered_codes):
            return ordered_codes[current_index + 1], True
        return None, True

    if _looks_like_semester_query(query):
        return None, True

    if current_code and current_code in ordered_codes:
        return current_code, False
    return ordered_codes[0], False


def _available_semesters_text(codes: List[str]) -> str:
    return "、".join(format_semester_label(code) for code in _sorted_semester_codes(codes))


def _clean_text(value: Any, default: str = "—") -> str:
    text = str(value or "").replace("\xa0", " ").replace("\r", "\n")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    return text or default


def _markdown_cell(value: Any, default: str = "—") -> str:
    return _clean_text(value, default=default).replace("|", "\\|")


def _markdown_table(headers: List[str], rows: List[List[Any]]) -> str:
    if not rows:
        return ""
    column_count = len(headers)
    lines = [
        f"| {' | '.join(headers)} |",
        f"| {' | '.join(['---'] * column_count)} |",
    ]
    for row in rows:
        normalized_row = list(row[:column_count])
        if len(normalized_row) < column_count:
            normalized_row.extend(["—"] * (column_count - len(normalized_row)))
        lines.append(f"| {' | '.join(_markdown_cell(cell) for cell in normalized_row)} |")
    return "\n".join(lines)


CULTIVATE_PLAN_QUERY_STOPWORDS = {
    "培养方案",
    "培养计划",
    "专业培养计划",
    "我的",
    "当前",
    "专业",
    "章节",
    "内容",
    "里面",
    "中的",
    "关于",
    "查看",
    "查询",
    "读取",
    "特定",
    "部分",
    "一下",
    "告诉我",
    "请",
    "帮我",
    "看下",
    "看一看",
    "想看",
    "想知道",
    "详细",
    "介绍",
    "总结",
}


def _cultivate_plan_section_aliases(title: Any) -> List[str]:
    text = _clean_text(title, default="")
    if not text:
        return []
    variants = [text]
    stripped = re.sub(
        r"^(?:[一二三四五六七八九十百]+、|[（(][一二三四五六七八九十百]+[)）]|\d+[.．、](?!\d)|\[\d+\])\s*",
        "",
        text,
    ).rstrip("：:").strip()
    if stripped and stripped not in variants:
        variants.append(stripped)
    normalized = _normalize_query_text(stripped or text)
    if normalized and normalized not in variants:
        variants.append(normalized)
    return [variant for variant in variants if variant]


def _cultivate_plan_query_terms(query: str) -> List[str]:
    working_query = str(query or "")
    for token in sorted(CULTIVATE_PLAN_QUERY_STOPWORDS, key=len, reverse=True):
        working_query = working_query.replace(token, " ")
    terms: List[str] = []
    for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,20}", working_query):
        normalized = _normalize_query_text(token)
        if not normalized or normalized in CULTIVATE_PLAN_QUERY_STOPWORDS:
            continue
        if normalized not in terms:
            terms.append(normalized)
    return sorted(terms, key=len, reverse=True)


def _chapter_search_blob(chapter: Dict[str, Any]) -> str:
    parts = [chapter.get("title", "")]
    parts.extend(chapter.get("paragraphs") or [])
    for item in chapter.get("items") or []:
        parts.append(f"{item.get('title', '')} {item.get('content', '')}")
    for table in chapter.get("tables") or []:
        parts.append(table.get("title", ""))
        parts.extend(table.get("headers") or [])
        parts.extend(" ".join(_clean_text(cell, default="") for cell in row) for row in table.get("rows") or [])
    return _normalize_query_text(" ".join(part for part in parts if part))


def _match_cultivate_plan_chapters(chapters: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    normalized_query = _normalize_query_text(query)
    if not normalized_query:
        return []

    direct_matches: List[Dict[str, Any]] = []
    for chapter in chapters:
        chapter_hit = any(
            len(alias_key) >= 2 and alias_key not in CULTIVATE_PLAN_QUERY_STOPWORDS and alias_key in normalized_query
            for alias_key in (_normalize_query_text(alias) for alias in _cultivate_plan_section_aliases(chapter.get("title")))
        )
        matched_items = []
        for item in chapter.get("items") or []:
            if any(
                len(alias_key) >= 2 and alias_key not in CULTIVATE_PLAN_QUERY_STOPWORDS and alias_key in normalized_query
                for alias_key in (_normalize_query_text(alias) for alias in _cultivate_plan_section_aliases(item.get("title")))
            ):
                matched_items.append(item)
        has_content = bool((chapter.get("paragraphs") or []) or (chapter.get("items") or []) or (chapter.get("tables") or []))
        if matched_items or (chapter_hit and has_content):
            direct_matches.append({"chapter": chapter, "matched_items": matched_items})
    if direct_matches:
        return direct_matches

    query_terms = _cultivate_plan_query_terms(query)
    if not query_terms:
        return []

    fuzzy_matches: List[Dict[str, Any]] = []
    for chapter in chapters:
        blob = _chapter_search_blob(chapter)
        matched_items = [
            item
            for item in chapter.get("items") or []
            if any(term in _normalize_query_text(f"{item.get('title', '')}{item.get('content', '')}") for term in query_terms)
        ]
        has_content = bool((chapter.get("paragraphs") or []) or (chapter.get("items") or []) or (chapter.get("tables") or []))
        if matched_items or (has_content and any(term in blob for term in query_terms)):
            fuzzy_matches.append({"chapter": chapter, "matched_items": matched_items})
    return fuzzy_matches


def _render_cultivate_plan_outline(outline: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for entry in outline:
        title = _clean_text(entry.get("title"), default="")
        if not title:
            continue
        level = max(0, int(entry.get("level") or 1) - 1)
        suffix_parts = []
        if entry.get("item_count"):
            suffix_parts.append(f"{entry.get('item_count')} 个子项")
        if entry.get("table_count"):
            suffix_parts.append(f"{entry.get('table_count')} 张表")
        elif entry.get("paragraph_count"):
            suffix_parts.append(f"{entry.get('paragraph_count')} 段说明")
        suffix = f"（{'，'.join(suffix_parts)}）" if suffix_parts else ""
        lines.append(f"- {'  ' * level}{title}{suffix}")
    return lines


def _render_cultivate_plan_table(table: Dict[str, Any], row_limit: int) -> List[str]:
    headers = [_clean_text(header, default=f"列{index + 1}") for index, header in enumerate(table.get("headers") or [])]
    rows = table.get("rows") or []
    if len(headers) < 2 or not rows or row_limit <= 0:
        return []
    visible_rows = rows[:row_limit]
    lines = [_markdown_table(headers, visible_rows)]
    if len(visible_rows) < len(rows):
        lines.extend(["", f"该表其余 {len(rows) - len(visible_rows)} 行已省略。"])
    return lines


def _render_cultivate_plan_match(match: Dict[str, Any], row_budget: int = 36) -> List[str]:
    chapter = match.get("chapter") or {}
    matched_items = match.get("matched_items") or []
    lines = [f"### {_clean_text(chapter.get('title'), default='命中章节')}", ""]

    paragraphs = chapter.get("paragraphs") or []
    items = matched_items or (chapter.get("items") or [])
    tables = chapter.get("tables") or []

    if paragraphs and not matched_items:
        for paragraph in paragraphs[:3]:
            lines.append(f"- {_clean_text(paragraph, default='')}")
        if len(paragraphs) > 3:
            lines.append(f"- 该章节其余 {len(paragraphs) - 3} 段说明已收起。")

    if items:
        lines.extend(["", "#### 子项", ""])
        for item in items[:12]:
            title = _clean_text(item.get("title"), default="")
            content = _clean_text(item.get("content"), default="")
            lines.append(f"- {title}：{content}" if content else f"- {title}")
        if len(items) > 12:
            lines.append(f"- 其余 {len(items) - 12} 个子项已收起。")

    remaining_budget = row_budget
    rendered_table = False
    for table in tables[:3]:
        table_rows = table.get("rows") or []
        if not table_rows or remaining_budget <= 0:
            continue
        title = _clean_text(table.get("title"), default="")
        lines.extend(["", f"#### {title or '表格'}", ""])
        row_limit = min(len(table_rows), remaining_budget)
        lines.extend(_render_cultivate_plan_table(table, row_limit=row_limit))
        remaining_budget -= row_limit
        rendered_table = True
        if remaining_budget <= 0:
            break
    if tables and not rendered_table:
        lines.extend(["", "- 该章节包含表格内容，可继续按更细的章节名查询。"])

    return lines


def _artifact_cultivate_plan_match(match: Dict[str, Any]) -> Dict[str, Any]:
    chapter = match.get("chapter") or {}
    matched_items = match.get("matched_items") or []
    source_items = matched_items or (chapter.get("items") or [])
    source_tables = chapter.get("tables") or []

    return {
        "id": chapter.get("id"),
        "title": chapter.get("title"),
        "level": chapter.get("level", 1),
        "paragraphs": [] if matched_items else list(chapter.get("paragraphs") or []),
        "items": [
            {
                "title": item.get("title"),
                "content": item.get("content"),
            }
            for item in source_items
        ],
        "tables": [
            {
                "title": table.get("title"),
                "headers": list(table.get("headers") or []),
                "rows": [list(row) for row in (table.get("rows") or [])],
            }
            for table in source_tables
        ],
        "matched_item_count": len(matched_items),
        "is_partial_match": bool(matched_items),
    }


def _render_cultivate_plan_preview(chapters: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for chapter in chapters:
        title = _clean_text(chapter.get("title"), default="")
        if not title:
            continue
        summary = ""
        if chapter.get("paragraphs"):
            summary = _clean_text(chapter["paragraphs"][0], default="")
        elif chapter.get("items"):
            item_titles = [_clean_text(item.get("title"), default="") for item in chapter.get("items")[:4]]
            summary = "、".join(title for title in item_titles if title)
        elif chapter.get("tables"):
            summary = f"包含 {len(chapter.get('tables') or [])} 张表格"
        if summary:
            lines.append(f"- {title}：{summary}")
        else:
            lines.append(f"- {title}")
    return lines


def _format_course_schedule(value: Any) -> str:
    raw_lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in str(value or "").replace("\xa0", " ").splitlines()
        if line.strip()
    ]
    if not raw_lines:
        return "—"
    normalized_lines = [re.sub(r"(节)(?=\S)", r"\1 ", line) for line in raw_lines]
    return "；".join(normalized_lines)


def _safe_float(value: Any) -> float | None:
    text = re.sub(r"[^0-9.]+", "", str(value or ""))
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _credit_completion_text(gain: Any, total: Any) -> str:
    gain_value = _safe_float(gain)
    total_value = _safe_float(total)
    if gain_value is None or total_value in (None, 0):
        return "—"
    ratio = gain_value / total_value * 100
    if ratio.is_integer():
        return f"{ratio:.0f}%"
    return f"{ratio:.1f}%"


def _semester_labels_from_marks(marks: List[Dict[str, Any]]) -> List[str]:
    semester_map: Dict[str, str] = {}
    for mark in marks:
        code = normalize_semester_code(mark.get("semester_code") or mark.get("semester", ""))
        label = _clean_text(mark.get("semester") or format_semester_label(code), default="")
        if code and label:
            semester_map[code] = label
    return [semester_map[code] for code in _sorted_semester_codes(list(semester_map.keys())) if code in semester_map]


def _selection_status_label(status: str) -> str:
    return {
        "open": "进行中",
        "upcoming": "未开始",
        "closed": "已结束",
        "unknown": "状态未知",
    }.get(status or "", "状态未知")


def _filter_selection_categories(query: str, categories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized_query = _normalize_query_text(query)
    if not normalized_query:
        return categories

    matched_keys = set()
    for config in SELECTION_CATEGORY_CONFIG:
        aliases = [config.get("key", ""), config.get("label", ""), *(config.get("aliases") or ())]
        if any(_normalize_query_text(alias) in normalized_query for alias in aliases if alias):
            matched_keys.add(config.get("key"))
    if not matched_keys:
        return categories
    return [category for category in categories if category.get("key") in matched_keys]


def _query_grades_impl(query: str = "", edu_session: Dict[str, Any] | None = None) -> Tuple[str, Any]:
    try:
        client = _build_client(edu_session)
        marks = client.get_marks()
        if not marks:
            return "未查询到成绩记录。可能是教务系统暂无数据或会话已过期。", None

        matched_codes, has_semester_filter = _resolve_grade_semester_filter(query, marks)
        matched_code_set = set(matched_codes)
        filtered_marks = [mark for mark in marks if not has_semester_filter or mark.get("semester_code") in matched_code_set]
        if has_semester_filter and not filtered_marks:
            available = "、".join(_semester_labels_from_marks(marks))
            return f"未找到对应学期的成绩记录。\n\n可查询学期：{available}", None

        recorded_count = sum(1 for mark in filtered_marks if _clean_text(mark.get("score"), default="") not in ("", "成绩尚未录入"))
        lines = [
            "## 成绩查询",
            "",
            f"- 课程数：{len(filtered_marks)}",
            f"- 已录入成绩：{recorded_count} 门",
            "",
        ]
        current_semester = None
        semester_rows: List[List[Any]] = []
        for mark in filtered_marks:
            semester = _clean_text(mark.get("semester"))
            if semester != current_semester:
                if current_semester and semester_rows:
                    lines.extend(
                        [
                            f"### {current_semester}",
                            "",
                            _markdown_table(["课程", "学分", "成绩", "绩点"], semester_rows),
                            "",
                        ]
                    )
                current_semester = semester
                semester_rows = []
            semester_rows.append([mark.get("name"), mark.get("credits"), mark.get("score"), mark.get("gpa")])
        if current_semester and semester_rows:
            lines.extend(
                [
                    f"### {current_semester}",
                    "",
                    _markdown_table(["课程", "学分", "成绩", "绩点"], semester_rows),
                ]
            )
        if not has_semester_filter and len({mark.get('semester_code') for mark in filtered_marks}) > 1:
            lines.extend(["", "> 提示：可直接说“查询 2025-2026 学年第一学期成绩”或“查询 2026 春季成绩”。"])
        return "\n".join(lines), filtered_marks
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_grades failed")
        return f"查询成绩时发生错误: {exc}", None


def _query_courses_impl(query: str = "", edu_session: Dict[str, Any] | None = None) -> Tuple[str, Any]:
    try:
        client = _build_client(edu_session)
        courses = client.get_courses()
        if not courses:
            return "未查询到课表记录。可能是教务系统暂无数据或会话已过期。", None
        semester = _clean_text(courses[0].get("semester"), default="当前学期")
        rows = []
        for course in courses:
            time_and_location = _format_course_schedule(course.get("time"))
            if _clean_text(course.get("location"), default="") and _clean_text(course.get("location"), default="") not in time_and_location:
                time_and_location = f"{time_and_location}；{_clean_text(course.get('location'))}"
            rows.append([
                course.get("name"),
                course.get("teacher"),
                course.get("credits"),
                time_and_location,
            ])
        lines = [
            "## 课表查询",
            "",
            f"- 学期：{semester}",
            f"- 课程数：{len(courses)}",
            "",
            _markdown_table(["课程", "教师", "学分", "时间地点"], rows),
        ]
        return "\n".join(lines), courses
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_courses failed")
        return f"查询课表时发生错误: {exc}", None


def _query_student_info_impl(query: str = "", edu_session: Dict[str, Any] | None = None) -> Tuple[str, Any]:
    try:
        client = _build_client(edu_session)
        info = client.get_student_info()
        if not info:
            return "未查询到学生信息。可能是教务系统暂无数据或会话已过期。", None
        sections = {
            "基本信息": ["学号", "姓名", "性别", "生日", "学院", "专业", "年级"],
            "联系与学籍": ["电话", "邮箱", "辅导员", "考生类别", "民族", "国别", "政治面貌", "生源地"],
        }
        used_keys = set()
        lines = ["## 学生信息", ""]
        for title, keys in sections.items():
            rows = []
            for key in keys:
                value = info.get(key)
                if value:
                    rows.append([key, value])
                    used_keys.add(key)
            if rows:
                lines.extend([f"### {title}", "", _markdown_table(["字段", "内容"], rows), ""])
        extra_rows = [[key, value] for key, value in info.items() if key not in used_keys and value]
        if extra_rows:
            lines.extend(["### 其他信息", "", _markdown_table(["字段", "内容"], extra_rows)])
        return "\n".join(lines), info
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_student_info failed")
        return f"查询学生信息时发生错误: {exc}", None


def _query_exam_scores_impl(query: str = "", edu_session: Dict[str, Any] | None = None) -> Tuple[str, Any]:
    try:
        client = _build_client(edu_session)
        scores = client.get_cet_scores()
        if not scores:
            return "未查询到等级考试成绩记录。", None
        rows = [
            [score.get("category"), score.get("exam_name"), score.get("score"), score.get("semester") or score.get("date")]
            for score in scores
        ]
        lines = [
            "## 等级考试成绩",
            "",
            f"- 成绩数：{len(scores)}",
            "",
            _markdown_table(["类别", "项目", "成绩", "学期"], rows),
        ]
        return "\n".join(lines), scores
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_exam_scores failed")
        return f"查询等级考试成绩时发生错误: {exc}", None


def _query_gpa_ranking_impl(query: str = "", edu_session: Dict[str, Any] | None = None) -> Tuple[str, Any]:
    try:
        client = _build_client(edu_session)
        ranking = client.get_gpa_ranking()
        items = ranking.get("items") or []
        if not items:
            return "未查询到绩点与排名数据。", None
        rows = [[item.get("type"), item.get("value")] for item in items]
        lines = ["## 绩点与排名", ""]
        if ranking.get("time"):
            lines.append(f"- 统计时间：{_clean_text(ranking.get('time'))}")
            lines.append("")
        lines.append(_markdown_table(["指标", "数值"], rows))
        return "\n".join(lines), ranking
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_gpa_ranking failed")
        return f"查询绩点与排名时发生错误: {exc}", None


def _query_credit_statistics_impl(query: str = "", edu_session: Dict[str, Any] | None = None) -> Tuple[str, Any]:
    try:
        client = _build_client(edu_session)
        credit_stats = client.get_credit_statistics()
        major_stats = credit_stats.get("major") or []
        minor_stats = credit_stats.get("minor") or []
        if not major_stats and not minor_stats:
            return "未查询到学分统计数据。", None

        lines = ["## 学分统计", ""]
        if major_stats:
            lines.extend(
                [
                    "### 主修专业",
                    "",
                    _markdown_table(
                        ["类别", "已获", "应修", "完成度"],
                        [
                            [row.get("type"), row.get("gain"), row.get("total"), _credit_completion_text(row.get("gain"), row.get("total"))]
                            for row in major_stats
                        ],
                    ),
                    "",
                ]
            )
        if minor_stats:
            lines.extend(
                [
                    "### 辅修专业",
                    "",
                    _markdown_table(
                        ["类别", "已获", "应修", "完成度"],
                        [
                            [row.get("type"), row.get("gain"), row.get("total"), _credit_completion_text(row.get("gain"), row.get("total"))]
                            for row in minor_stats
                        ],
                    ),
                ]
            )
        return "\n".join(lines), credit_stats
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_credit_statistics failed")
        return f"查询学分统计时发生错误: {exc}", None


def _query_exam_rooms_impl(query: str = "", edu_session: Dict[str, Any] | None = None) -> Tuple[str, Any]:
    try:
        client = _build_client(edu_session)
        available_codes = client.get_exam_room_terms()
        current_code = None
        try:
            current_code = client.get_school_calendar().get("current_term")
        except Exception:  # noqa: BLE001
            current_code = None

        selected_code, has_term_filter = _resolve_single_semester_code(query, available_codes, current_code)
        if has_term_filter and not selected_code:
            return f"未找到对应学期的考场数据。\n\n可查询学期：{_available_semesters_text(available_codes)}", None

        exam_rooms = client.get_exam_rooms(selected_code)
        exams = exam_rooms.get("exams") or []
        if not exams:
            return f"{exam_rooms.get('term_label') or '该学期'}暂无考场安排。", exam_rooms

        rows = [
            [exam.get("course_name"), exam.get("teacher"), exam.get("date"), exam.get("time"), exam.get("location")]
            for exam in exams
        ]
        lines = [
            "## 考场查询",
            "",
            f"- 学期：{_clean_text(exam_rooms.get('term_label'))}",
            f"- 考试数：{len(exams)}",
            "",
            _markdown_table(["课程", "教师", "日期", "时间", "地点"], rows),
        ]
        return "\n".join(lines), exam_rooms
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_exam_rooms failed")
        return f"查询考场时发生错误: {exc}", None


def _query_academic_calendar_impl(query: str = "", edu_session: Dict[str, Any] | None = None) -> Tuple[str, Any]:
    try:
        client = _build_client(edu_session)
        calendar = client.get_school_calendar()
        terms = calendar.get("terms") or []
        available_codes = [normalize_semester_code(term.get("term_id") or term.get("term")) for term in terms]
        selected_code, has_term_filter = _resolve_single_semester_code(query, available_codes, calendar.get("current_term"))
        if has_term_filter and not selected_code:
            return f"未找到对应学期的校历。\n\n可查询学期：{_available_semesters_text(available_codes)}", None

        selected_term = next(
            (term for term in terms if normalize_semester_code(term.get("term_id") or term.get("term")) == selected_code),
            terms[0] if terms else None,
        )
        if not selected_term:
            return "未查询到校历数据。", None

        events_payload = client.get_term_events(selected_term.get("term_id", ""))
        events = events_payload.get("events") or []
        artifact = {
            "current_term": calendar.get("current_term"),
            "current_term_label": calendar.get("current_term_label"),
            "selected_term": selected_term.get("term"),
            "selected_term_label": selected_term.get("term_label"),
            "start_date": selected_term.get("start_date"),
            "end_date": selected_term.get("end_date"),
            "events": events,
        }
        lines = [
            "## 校历与学期事件",
            "",
            f"- 当前学期：{_clean_text(calendar.get('current_term_label'))}",
            f"- 查询学期：{_clean_text(selected_term.get('term_label'))}",
            f"- 学期区间：{_clean_text(selected_term.get('start_date'))} 至 {_clean_text(selected_term.get('end_date'))}",
            "",
        ]
        if events:
            lines.append(_markdown_table(["事件", "开始", "结束"], [[event.get("name"), event.get("start_date"), event.get("end_date")] for event in events]))
        else:
            lines.append("该学期暂无可展示的校历事件。")
        return "\n".join(lines), artifact
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_academic_calendar failed")
        return f"查询校历时发生错误: {exc}", None


def _query_cultivate_plan_impl(query: str = "", edu_session: Dict[str, Any] | None = None) -> Tuple[str, Any]:
    try:
        client = _build_client(edu_session)
        plan = client.get_cultivate_plan()
        chapters = plan.get("chapters") or []
        outline = plan.get("outline") or []
        sections = plan.get("sections") or []
        text_blocks = plan.get("text_blocks") or []
        matches = _match_cultivate_plan_chapters(chapters, query)
        matched_titles = [_clean_text(match.get("chapter", {}).get("title"), default="") for match in matches]
        artifact = {
            **plan,
            "query": query,
            "matched_titles": [title for title in matched_titles if title],
            "matched_chapter_ids": [match.get("chapter", {}).get("id") for match in matches if match.get("chapter", {}).get("id")],
            "matched_results": [_artifact_cultivate_plan_match(match) for match in matches],
        }
        lines = [
            "## 培养方案",
            "",
            f"- 年级：{_clean_text(plan.get('grade'))}",
            f"- 学院：{_clean_text(plan.get('college'))}",
            f"- 专业：{_clean_text(plan.get('major'))}",
        ]

        if plan.get("title"):
            lines.append(f"- 页面：{_clean_text(plan.get('title'), default='')}")
        if plan.get("document_title"):
            lines.append(f"- 文档：{_clean_text(plan.get('document_title'), default='')}")

        if outline:
            lines.extend(["", "### 章节索引", ""])
            lines.extend(_render_cultivate_plan_outline(outline))

        if matches:
            lines.extend(["", "### 命中章节", ""])
            rendered = 0
            for match in matches[:4]:
                row_budget = max(8, 48 - rendered)
                rendered_lines = _render_cultivate_plan_match(match, row_budget=row_budget)
                lines.extend(rendered_lines)
                rendered += sum(len(table.get("rows") or []) for table in (match.get("chapter", {}).get("tables") or [])[:3])
                if rendered >= 48:
                    break
            return "\n".join(lines), artifact

        if query and _cultivate_plan_query_terms(query):
            lines.extend(["", f"未直接定位到与“{_clean_text(query, default='当前查询')}”完全对应的章节，下面给出结构摘要供继续定位。"])

        if chapters:
            lines.extend(["", "### 结构摘要", ""])
            lines.extend(_render_cultivate_plan_preview(chapters))
            return "\n".join(lines), artifact

        if text_blocks:
            lines.extend(["", "### 页面说明", ""])
            for block in text_blocks[:8]:
                lines.append(f"- {_clean_text(block, default='')}")

        rendered_rows = 0
        for section in sections:
            headers = [
                _clean_text(header, default=f"列{index + 1}")
                for index, header in enumerate(section.get("headers") or [])
            ]
            rows = section.get("rows") or []
            if len(headers) < 2 or not rows:
                continue

            section_title = _clean_text(section.get("title"), default="")
            lines.extend(["", f"### {section_title or '计划内容'}", ""])
            remaining_rows = max(0, 80 - rendered_rows)
            if remaining_rows <= 0:
                lines.append("内容较多，完整正文已提取到工具卡片中，可直接展开查看。")
                break
            visible_rows = rows[:remaining_rows]
            lines.append(_markdown_table(headers, visible_rows))
            rendered_rows += len(visible_rows)
            if len(visible_rows) < len(rows):
                lines.extend(["", "该部分内容较长，剩余条目已保留在工具卡片中。"])

        if not sections and not text_blocks:
            lines.extend(["", "暂未提取到可展示的培养方案正文。"])

        return "\n".join(lines), artifact
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_cultivate_plan failed")
        return f"查询培养方案时发生错误: {exc}", None


def _query_course_selection_impl(query: str = "", edu_session: Dict[str, Any] | None = None) -> Tuple[str, Any]:
    try:
        client = _build_client(edu_session)
        overview = client.get_course_selection_overview()
        categories = _filter_selection_categories(query, overview.get("categories") or [])
        if not categories:
            return "未找到匹配的选课类别。", None

        needed_credit_types = overview.get("needed_credit_types") or []
        open_categories = [category.get("label") for category in categories if category.get("status") == "open"]

        lines = ["## 选课总览", ""]
        if open_categories:
            lines.append(f"- 当前处于选课时间：{'、'.join(open_categories)}")
        else:
            lines.append("- 当前没有处于选课时间的选课类别")

        if needed_credit_types:
            missing = [
                f"{entry.get('category')}（还差 {entry.get('missing')} 学分）"
                for entry in needed_credit_types
                if entry.get("missing_value", 0) > 0
            ]
            lines.append(f"- 通识缺口：{'、'.join(missing) if missing else '暂无'}")
        else:
            lines.append("- 通识缺口：暂无")
        lines.append("")

        for category in categories:
            window = category.get("time_window") or {}
            lines.extend([f"### {category.get('label')}", ""])
            lines.append(f"- 状态：{_selection_status_label(category.get('status', 'unknown'))}")
            if window.get("start") and window.get("end"):
                lines.append(f"- 时间：{window.get('start')} 至 {window.get('end')}")
            if category.get("current_course_count"):
                selected_count = int(category.get("selected_count") or 0)
                current_count = int(category.get("current_course_count") or 0)
                if selected_count and selected_count != current_count:
                    lines.append(f"- 结果页课程：{current_count} 门，其中已中选 {selected_count} 门")
                else:
                    lines.append(f"- 已选课程：{current_count} 门")
            else:
                lines.append("- 已选课程：0 门")
            lines.append(f"- 当前候选课程：{int(category.get('candidate_count') or 0)} 门")

            credit_progress = category.get("credit_progress") or []
            if credit_progress:
                lines.extend(
                    [
                        "",
                        _markdown_table(
                            ["通识类别", "已获", "要求", "还差"],
                            [
                                [
                                    row.get("category"),
                                    row.get("earned"),
                                    row.get("required"),
                                    row.get("missing"),
                                ]
                                for row in credit_progress
                            ],
                        ),
                    ]
                )

            candidates = category.get("candidates") or []
            if candidates:
                lines.extend(
                    [
                        "",
                        _markdown_table(
                            ["课程", "教师", "学分", "时间", "类型"],
                            [
                                [
                                    candidate.get("course_name"),
                                    candidate.get("teacher"),
                                    candidate.get("credits"),
                                    candidate.get("schedule"),
                                    candidate.get("course_type"),
                                ]
                                for candidate in candidates
                            ],
                        ),
                    ]
                )
            lines.append("")

        artifact = {
            "mode": "overview",
            "categories": categories,
            "needed_credit_types": needed_credit_types,
        }
        return "\n".join(lines).strip(), artifact
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_course_selection failed")
        return f"查询选课信息时发生错误: {exc}", None


def _select_course_impl(
    category: str,
    course_name: str,
    teacher: str = "",
    points: str = "",
    edu_session: Dict[str, Any] | None = None,
) -> Tuple[str, Any]:
    try:
        if not category.strip():
            return "执行选课前请明确选课类别，例如学期选课、通识选修课或重新学习选课。", None
        if not course_name.strip():
            return "执行选课前请明确课程名称。", None

        client = _build_client(edu_session)
        result = client.select_course(category=category, course_name=course_name, teacher=teacher, points=points)
        course = result.get("course") or {}
        lines = ["## 选课提交结果", ""]
        lines.append(f"- 类别：{_clean_text(result.get('category_label'))}")
        lines.append(f"- 课程：{_clean_text(course.get('course_name'))}")
        if course.get("teacher"):
            lines.append(f"- 教师：{_clean_text(course.get('teacher'))}")
        if points:
            lines.append(f"- 所投积分：{_clean_text(points)}")
        lines.append(f"- 结果：{_clean_text(result.get('message'))}")
        lines.append("")
        lines.append("> 提醒：涉及真实选课状态变更，请继续到教务系统“我的选课”或再次查询选课结果进行确认。")
        return "\n".join(lines), result
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("select_course failed")
        return f"提交选课时发生错误: {exc}", None


def build_edu_tools(edu_session: Dict[str, Any] | None = None):
    """Create a request-scoped tool set bound to *edu_session*."""

    @tool(response_format="content_and_artifact")
    def query_grades(query: str = "") -> Tuple[str, Any]:
        """查询当前登录学生的课程成绩和绩点信息，支持按学期筛选。

        参数:
        - query: 用户的查询描述，例如"我的成绩"、"这学期的绩点"、"2025-2026学年第一学期成绩"、"2026春季成绩"
        """
        return _query_grades_impl(query, edu_session)

    @tool(response_format="content_and_artifact")
    def query_courses(query: str = "") -> Tuple[str, Any]:
        """查询当前登录学生的课程表信息。当用户询问自己的课表、上课时间、上课地点等信息时调用此工具。

        参数:
        - query: 用户的查询描述，例如"我的课表"、"明天有什么课"
        """
        return _query_courses_impl(query, edu_session)

    @tool(response_format="content_and_artifact")
    def query_student_info(query: str = "") -> Tuple[str, Any]:
        """查询当前登录学生的个人基本信息，包括姓名、学号、学院、专业等。当用户询问"我的信息"、"我是哪个学院的"等时调用此工具。

        参数:
        - query: 用户的查询描述
        """
        return _query_student_info_impl(query, edu_session)

    @tool(response_format="content_and_artifact")
    def query_exam_scores(query: str = "") -> Tuple[str, Any]:
        """查询当前登录学生的等级考试成绩（如英语四六级CET、计算机等级考试等）。当用户询问四六级成绩、等级考试成绩时调用此工具。

        参数:
        - query: 用户的查询描述，例如"我的四六级成绩"
        """
        return _query_exam_scores_impl(query, edu_session)

    @tool(response_format="content_and_artifact")
    def query_gpa_ranking(query: str = "") -> Tuple[str, Any]:
        """查询当前登录学生的绩点、专业排名、班级排名等统计信息。当用户询问绩点、排名、GPA 时调用此工具。

        参数:
        - query: 用户的查询描述，例如"我的绩点排名"
        """
        return _query_gpa_ranking_impl(query, edu_session)

    @tool(response_format="content_and_artifact")
    def query_credit_statistics(query: str = "") -> Tuple[str, Any]:
        """查询当前登录学生的学分统计，包括主修和辅修的已获学分与应修学分。当用户询问学分完成情况、还差多少学分时调用此工具。

        参数:
        - query: 用户的查询描述，例如"我的学分统计"
        """
        return _query_credit_statistics_impl(query, edu_session)

    @tool(response_format="content_and_artifact")
    def query_exam_rooms(query: str = "") -> Tuple[str, Any]:
        """查询当前登录学生的考试安排和考场地点，支持按学期筛选。当用户询问期末考试安排、考场、考试地点时调用此工具。

        参数:
        - query: 用户的查询描述，例如"本学期考场"、"2024-2025学年第二学期考试安排"
        """
        return _query_exam_rooms_impl(query, edu_session)

    @tool(response_format="content_and_artifact")
    def query_academic_calendar(query: str = "") -> Tuple[str, Any]:
        """查询福州大学校历和学期事件，支持按学期筛选。当用户询问开学时间、放假时间、校历安排时调用此工具。

        参数:
        - query: 用户的查询描述，例如"本学期校历"、"2025秋季校历"
        """
        return _query_academic_calendar_impl(query, edu_session)

    @tool(response_format="content_and_artifact")
    def query_cultivate_plan(query: str = "") -> Tuple[str, Any]:
        """查询当前登录学生对应专业的培养方案正文结构，并支持按章节定位特定内容。

        参数:
        - query: 用户的查询描述，例如"我的培养方案"、"培养方案里的毕业要求"、"核心课程是什么"
        """
        return _query_cultivate_plan_impl(query, edu_session)

    @tool(response_format="content_and_artifact")
    def query_course_selection(query: str = "") -> Tuple[str, Any]:
        """查询当前登录学生各类选课状态、时间窗、通识缺口和当前候选课程。

        参数:
        - query: 用户的查询描述，例如"看看我现在有哪些课能选"、"通识选修还差什么"、"重修选课情况"
        """
        return _query_course_selection_impl(query, edu_session)

    @tool(response_format="content_and_artifact")
    def select_course(category: str, course_name: str, teacher: str = "", points: str = "") -> Tuple[str, Any]:
        """为当前登录学生提交一次真实选课请求。

        仅当用户明确要求“选某门课”且已提供足够精确的信息时调用。

        参数:
        - category: 选课类别，例如"学期选课"、"通识选修课"、"重新学习选课"
        - course_name: 要选的课程名称，必须与教务系统中的课程名完全匹配
        - teacher: 可选。若同名课程有多门，必须补充教师姓名以消除歧义
        - points: 可选。对于需要填写所投积分的课程，必须提供积分
        """
        return _select_course_impl(category, course_name, teacher, points, edu_session)

    return [
        query_grades,
        query_gpa_ranking,
        query_credit_statistics,
        query_courses,
        query_course_selection,
        select_course,
        query_exam_rooms,
        query_student_info,
        query_exam_scores,
        query_academic_calendar,
        query_cultivate_plan,
    ]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

# Convenience list for registering with the graph
ALL_EDU_TOOLS = build_edu_tools()
