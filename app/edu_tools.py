"""LangGraph tools for querying FZU educational systems.

These tools wrap :mod:`app.jwch_client` and expose grade / course / profile
information to the LLM agent.  Each tool reads the current user's educational
session from a thread-local variable (set by the request handler in
``server.py`` before the graph is invoked).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Tuple

from langchain_core.tools import tool

from .jwch_client import JwchClient, JwchError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thread-local storage for the current request's edu session.
# The server sets this before each ``graph.stream()`` call.
# ---------------------------------------------------------------------------
_local = threading.local()


def set_current_edu_session(session: Dict[str, Any] | None) -> None:
    """Store the educational-system session for the current thread."""
    _local.edu_session = session


def get_current_edu_session() -> Dict[str, Any] | None:
    """Return the educational-system session for the current thread."""
    return getattr(_local, "edu_session", None)


def _build_client() -> JwchClient:
    """Build a :class:`JwchClient` from the thread-local session, or raise."""
    session = get_current_edu_session()
    if not session or not session.get("edu_authenticated"):
        raise JwchError("当前用户尚未登录教务系统，无法查询教务信息。请提醒用户先在设置中登录教务系统。")
    cookies = session.get("edu_cookies") or []
    student_id = session.get("user_id", "")
    identifier = session.get("edu_identifier", "")
    return JwchClient.from_cookies(student_id, cookies, identifier)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(response_format="content_and_artifact")
def query_grades(query: str) -> Tuple[str, Any]:
    """查询当前登录学生的课程成绩和绩点信息。当用户询问自己的成绩、绩点、学分等信息时调用此工具。

    参数:
    - query: 用户的查询描述，例如"我的成绩"、"这学期的绩点"
    """
    try:
        client = _build_client()
        marks = client.get_marks()
        if not marks:
            return "未查询到成绩记录。可能是教务系统暂无数据或会话已过期。", None
        lines = ["学生成绩查询结果：\n"]
        for m in marks:
            lines.append(
                f"学期: {m['semester']}  课程: {m['name']}  "
                f"学分: {m['credits']}  成绩: {m['score']}  绩点: {m['gpa']}"
            )
        return "\n".join(lines), marks
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_grades failed")
        return f"查询成绩时发生错误: {exc}", None


@tool(response_format="content_and_artifact")
def query_courses(query: str) -> Tuple[str, Any]:
    """查询当前登录学生的课程表信息。当用户询问自己的课表、上课时间、上课地点等信息时调用此工具。

    参数:
    - query: 用户的查询描述，例如"我的课表"、"明天有什么课"
    """
    try:
        client = _build_client()
        courses = client.get_courses()
        if not courses:
            return "未查询到课表记录。可能是教务系统暂无数据或会话已过期。", None
        lines = ["课程表查询结果：\n"]
        for c in courses:
            lines.append(
                f"课程: {c['name']}  教师: {c['teacher']}  "
                f"学分: {c['credits']}  时间: {c['time']}  地点: {c['location']}"
            )
        return "\n".join(lines), courses
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_courses failed")
        return f"查询课表时发生错误: {exc}", None


@tool(response_format="content_and_artifact")
def query_student_info(query: str) -> Tuple[str, Any]:
    """查询当前登录学生的个人基本信息，包括姓名、学号、学院、专业等。当用户询问"我的信息"、"我是哪个学院的"等时调用此工具。

    参数:
    - query: 用户的查询描述
    """
    try:
        client = _build_client()
        info = client.get_student_info()
        if not info:
            return "未查询到学生信息。可能是教务系统暂无数据或会话已过期。", None
        lines = ["学生个人信息：\n"]
        for k, v in info.items():
            lines.append(f"{k}: {v}")
        return "\n".join(lines), info
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_student_info failed")
        return f"查询学生信息时发生错误: {exc}", None


@tool(response_format="content_and_artifact")
def query_exam_scores(query: str) -> Tuple[str, Any]:
    """查询当前登录学生的等级考试成绩（如英语四六级CET、计算机等级考试等）。当用户询问四六级成绩、等级考试成绩时调用此工具。

    参数:
    - query: 用户的查询描述，例如"我的四六级成绩"
    """
    try:
        client = _build_client()
        scores = client.get_cet_scores()
        if not scores:
            return "未查询到等级考试成绩记录。", None
        lines = ["等级考试成绩查询结果：\n"]
        for s in scores:
            lines.append(f"考试: {s['exam_name']}  成绩: {s['score']}  日期: {s['date']}")
        return "\n".join(lines), scores
    except JwchError as exc:
        return str(exc), None
    except Exception as exc:
        logger.exception("query_exam_scores failed")
        return f"查询等级考试成绩时发生错误: {exc}", None


# Convenience list for registering with the graph
ALL_EDU_TOOLS = [query_grades, query_courses, query_student_info, query_exam_scores]
