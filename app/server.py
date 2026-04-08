from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
from threading import Lock
from threading import Event
from typing import Any, AsyncIterator, Dict, Iterable, List, Literal
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .auth import (
    SESSION_TTL,
    create_session,
    get_session,
    invalidate_session,
    update_session,
)
from .chat_store import chat_store
from .edu_tools import set_current_edu_session
from .graph import CHAT_MODEL_OPTIONS, DEFAULT_CHAT_MODEL, build_graph, reset_search_citation_counter, summary_chain
from .jwch_client import JwchClient, JwchLoginError, JwchSessionError
from .memory_store import user_memory_store
from .security_utils import mask_user_id

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
ASSETS_DIR = BASE_DIR / "png"
MAX_TITLE_LENGTH = int(os.getenv("FZU_CHAT_MAX_TITLE_LENGTH", "20"))
AUTH_COOKIE_NAME = os.getenv("FZU_CHAT_AUTH_COOKIE_NAME", "fzu_session")
AUTH_COOKIE_SECURE_MODE = os.getenv("FZU_CHAT_AUTH_COOKIE_SECURE", "auto").strip().lower()
AUTH_COOKIE_SAMESITE = os.getenv("FZU_CHAT_AUTH_COOKIE_SAMESITE", "lax").strip().lower()
API_NO_STORE = "no-store, no-cache, must-revalidate, max-age=0, private"

if AUTH_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    AUTH_COOKIE_SAMESITE = "lax"

MODEL_OPTIONS = dict(CHAT_MODEL_OPTIONS)

TOOL_LABELS: Dict[str, Dict[str, str]] = {
    "retrieve": {"running": "正在查询知识库", "complete": "知识库查询完成"},
    "bocha_websearch_tool": {"running": "正在搜索网络", "complete": "网络搜索完成"},
    "query_user_memory": {"running": "正在查询个性化记忆", "complete": "个性化记忆查询完成"},
    "save_user_memory": {"running": "正在生成记忆建议", "complete": "记忆建议已生成"},
    "delete_user_memory": {"running": "正在生成删除建议", "complete": "记忆删除建议已生成"},
    "query_grades": {"running": "正在查询成绩", "complete": "成绩查询完成"},
    "query_gpa_ranking": {"running": "正在查询绩点排名", "complete": "绩点排名查询完成"},
    "query_credit_statistics": {"running": "正在查询学分统计", "complete": "学分统计查询完成"},
    "query_courses": {"running": "正在查询课表", "complete": "课表查询完成"},
    "query_course_selection": {"running": "正在查询选课情况", "complete": "选课情况查询完成"},
    "select_course": {"running": "正在提交选课", "complete": "选课提交完成"},
    "query_exam_rooms": {"running": "正在查询考场安排", "complete": "考场安排查询完成"},
    "query_student_info": {"running": "正在查询学生信息", "complete": "学生信息查询完成"},
    "query_exam_scores": {"running": "正在查询考试成绩", "complete": "考试成绩查询完成"},
    "query_academic_calendar": {"running": "正在查询校历", "complete": "校历查询完成"},
    "query_cultivate_plan": {"running": "正在查询培养方案", "complete": "培养方案查询完成"},
}
logger = logging.getLogger(__name__)

active_stream_stops: Dict[tuple[str, str], Event] = {}
active_stream_stops_lock = Lock()


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
                if path.startswith("/api/"):
                    headers["Cache-Control"] = API_NO_STORE
                    headers["Pragma"] = "no-cache"
                    headers["Expires"] = "0"
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


def _request_is_secure(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if forwarded_proto:
        return forwarded_proto.split(",", 1)[0].strip().lower() == "https"
    return request.url.scheme == "https"


def _use_secure_cookie(request: Request) -> bool:
    if AUTH_COOKIE_SECURE_MODE in {"1", "true", "yes", "on"}:
        return True
    if AUTH_COOKIE_SECURE_MODE in {"0", "false", "no", "off"}:
        return False
    return _request_is_secure(request)


def _set_auth_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL,
        httponly=True,
        secure=_use_secure_cookie(request),
        samesite=AUTH_COOKIE_SAMESITE,
        path="/",
    )


def _clear_auth_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        httponly=True,
        secure=_use_secure_cookie(request),
        samesite=AUTH_COOKIE_SAMESITE,
        path="/",
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="FZU Chat API", version="3.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

class AuthUser(BaseModel):
    user_id: str
    student_type: str
    display_name: str
    edu_authenticated: bool
    token: str


def require_auth(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> AuthUser:
    token: str | None = None
    if authorization:
        token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    elif session_cookie:
        token = session_cookie
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    session = get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="会话已过期，请重新登录")
    return AuthUser(
        user_id=session["user_id"],
        student_type=session["student_type"],
        display_name=session["display_name"],
        edu_authenticated=session.get("edu_authenticated", False),
        token=token,
    )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    student_id: str = Field(min_length=1, max_length=30)
    password: str = Field(min_length=1, max_length=100)
    student_type: str = "undergraduate"


class ConversationCreateRequest(BaseModel):
    model: str = DEFAULT_CHAT_MODEL


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=40)
    model: str | None = None


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    model: str | None = None


class FeedbackUpdateRequest(BaseModel):
    message_id: str
    feedback: Literal["up", "down"]


class MemoryProposalActionRequest(BaseModel):
    message_id: str
    action: Literal["confirm", "dismiss"]


class MessageRecord(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    timestamp: str
    parts: List[Dict[str, Any]] = Field(default_factory=list)
    feedback: Literal["up", "down"] | None = None
    is_error_fallback: bool = False


class ConversationRecord(BaseModel):
    id: str
    title: str
    model: str
    thread_id: str
    created_at: str
    updated_at: str
    messages: List[MessageRecord] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    id: str
    title: str
    model: str
    created_at: str
    updated_at: str
    preview: str
    message_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_conversation_summary(rec: Dict[str, Any]) -> Dict[str, Any]:
    preview = ""
    messages = rec.get("messages", [])
    for skip_error_fallback in (True, False):
        for msg in reversed(messages):
            if skip_error_fallback and msg.get("is_error_fallback"):
                continue
            preview = (msg.get("content") or "").strip()
            if preview:
                break
        if preview:
            break
    return {
        "id": rec["id"], "title": rec["title"], "model": rec["model"],
        "created_at": rec["created_at"], "updated_at": rec["updated_at"],
        "preview": preview[:80], "message_count": len(rec.get("messages", [])),
    }


def create_conversation_record(model: str) -> Dict[str, Any]:
    ts = now_iso()
    return {
        "id": str(uuid4()), "title": "新对话",
        "model": model if model in MODEL_OPTIONS else DEFAULT_CHAT_MODEL,
        "thread_id": str(uuid4()), "created_at": ts, "updated_at": ts, "messages": [],
    }


def normalize_model_id(model: str | None) -> str:
    return model if model in MODEL_OPTIONS else DEFAULT_CHAT_MODEL


def serialize_event(event: str, data: Dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


def extract_urls_from_tool_message(content: str) -> List[str]:
    urls: List[str] = []
    for line in content.splitlines():
        for prefix in ("Article url:", "URL:"):
            if line.startswith(prefix):
                url = line[len(prefix):].strip()
                if url and url not in urls:
                    urls.append(url)
    return urls


def combine_tool_calls(mc: Any) -> Any:
    if not hasattr(mc, "tool_calls") or not mc.tool_calls:
        return mc
    for tc in mc.tool_calls:
        if not isinstance(tc, dict):
            continue
        args = tc.get("args")
        if isinstance(args, dict):
            continue
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
                if isinstance(parsed, dict):
                    tc["args"] = parsed
                    continue
            except json.JSONDecodeError:
                if args.startswith('{"query":"'):
                    tc["args"] = {"query": args.replace('{"query":"', "").rstrip('"}')}
    return mc


def clean_tool_call_id(tid: str | None) -> str:
    if not tid:
        return ""
    return tid[:22] if tid.startswith("call_") else tid


def matching_tool_call_id(candidates: Iterable[str], target: str) -> str | None:
    for c in candidates:
        if c == target or c.startswith(target) or target.startswith(c):
            return c
    return None


def extract_urls(content: str, artifact: Any) -> List[str]:
    urls = extract_urls_from_tool_message(content)
    if isinstance(artifact, list):
        for item in artifact:
            src = None
            if isinstance(item, dict):
                src = item.get("url") or item.get("source")
            else:
                md = getattr(item, "metadata", None)
                if isinstance(md, dict):
                    src = md.get("source")
            if src and src not in urls:
                urls.append(src)
    return urls


SEARCH_RESULT_TOOL_NAMES = {"retrieve", "bocha_websearch_tool"}
SEARCH_RESULT_CITATION_RE = re.compile(r"^\[(\d+)\]$")
SEARCH_RESULT_INLINE_CITATION_RE = re.compile(r"\[(\d+)\](?!\()")


def clone_tool_part(part: Dict[str, Any]) -> Dict[str, Any]:
    cloned = dict(part)
    urls = part.get("urls")
    if isinstance(urls, list):
        cloned["urls"] = list(urls)

    data = part.get("data")
    if isinstance(data, dict):
        cloned_data = dict(data)
        items = data.get("items")
        if isinstance(items, list):
            cloned_data["items"] = [dict(item) if isinstance(item, dict) else item for item in items]
        cloned["data"] = cloned_data

    return cloned


def prepare_search_result_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    prepared: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        prepared_item = dict(item)
        original_citation_id = str(
            prepared_item.get("original_citation_id") or prepared_item.get("citation_id") or ""
        ).strip()
        if original_citation_id:
            prepared_item["original_citation_id"] = original_citation_id
        prepared.append(prepared_item)
    return prepared


def renumber_search_tool_parts(parts: List[Dict[str, Any]]) -> tuple[Dict[str, str], List[Dict[str, Any]]]:
    next_citation_id = 1
    citation_id_map: Dict[str, str] = {}
    changed_parts: List[Dict[str, Any]] = []

    for part in parts:
        if part.get("type") != "tool" or part.get("tool_name") not in SEARCH_RESULT_TOOL_NAMES:
            continue

        data = part.get("data")
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            continue

        normalized_items: List[Dict[str, Any]] = []
        part_changed = False

        for item in items:
            if not isinstance(item, dict):
                continue

            normalized_item = dict(item)
            original_citation_id = str(
                normalized_item.get("original_citation_id") or normalized_item.get("citation_id") or ""
            ).strip()
            expected_label = f"[{next_citation_id}]"

            if original_citation_id:
                citation_id_map[original_citation_id] = str(next_citation_id)
                if normalized_item.get("original_citation_id") != original_citation_id:
                    part_changed = True
                normalized_item["original_citation_id"] = original_citation_id

            if normalized_item.get("citation_id") != next_citation_id:
                part_changed = True
            if normalized_item.get("label") != expected_label:
                part_changed = True

            normalized_item["citation_id"] = next_citation_id
            normalized_item["label"] = expected_label
            normalized_items.append(normalized_item)
            next_citation_id += 1

        if normalized_items != items:
            part_changed = True

        if part_changed:
            next_data = dict(data)
            next_data["items"] = normalized_items
            part["data"] = next_data
            changed_parts.append(clone_tool_part(part))

    return citation_id_map, changed_parts


def remap_search_citation_references(content: str, citation_id_map: Dict[str, str]) -> str:
    if not content or not citation_id_map:
        return content

    def replace_match(match: re.Match[str]) -> str:
        citation_id = match.group(1)
        return f"[{citation_id_map.get(citation_id, citation_id)}]"

    return SEARCH_RESULT_INLINE_CITATION_RE.sub(replace_match, content)


def parse_labeled_search_results(content: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None
    snippet_lines: List[str] = []
    active_multiline_field: str | None = None
    field_map = {
        "标题": "title",
        "URL": "url",
        "内容摘录": "snippet",
        "摘要": "snippet",
        "网站名称": "source_name",
        "发布时间": "published_at",
    }

    def flush_current() -> None:
        nonlocal current, snippet_lines, active_multiline_field
        if current is None:
            return
        if snippet_lines:
            current["snippet"] = "\n".join(snippet_lines).strip()
        current["label"] = f"[{current['citation_id']}]"
        items.append(current)
        current = None
        snippet_lines = []
        active_multiline_field = None

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        match = SEARCH_RESULT_CITATION_RE.match(stripped)
        if match:
            flush_current()
            current = {"citation_id": int(match.group(1))}
            continue
        if current is None:
            continue
        if not stripped:
            if active_multiline_field == "snippet" and snippet_lines:
                snippet_lines.append("")
            continue

        matched_field = False
        for prefix, field_name in field_map.items():
            marker = f"{prefix}:"
            if not line.startswith(marker):
                continue
            value = line[len(marker):].strip()
            matched_field = True
            if field_name == "snippet":
                snippet_lines = [value] if value else []
                active_multiline_field = "snippet"
            else:
                current[field_name] = value
                active_multiline_field = None
            break

        if matched_field:
            continue
        if active_multiline_field == "snippet":
            snippet_lines.append(line)

    flush_current()
    return items


def extract_structured_data(tool_name: str, artifact: Any, content: str = "") -> Any:
    if tool_name in SEARCH_RESULT_TOOL_NAMES:
        if isinstance(artifact, list):
            items = prepare_search_result_items([item for item in artifact if isinstance(item, dict)])
            if items:
                return {"items": items}
        parsed_items = prepare_search_result_items(parse_labeled_search_results(content))
        if parsed_items:
            return {"items": parsed_items}
    if tool_name in (
        "query_user_memory",
        "save_user_memory",
        "delete_user_memory",
        "query_grades",
        "query_gpa_ranking",
        "query_credit_statistics",
        "query_courses",
        "query_course_selection",
        "select_course",
        "query_exam_rooms",
        "query_student_info",
        "query_exam_scores",
        "query_academic_calendar",
        "query_cultivate_plan",
    ):
        if isinstance(artifact, (list, dict)):
            return artifact
    return None


def extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text") or block.get("content")
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return ""


def summarize_tool_args(args: Any) -> str:
    if isinstance(args, str):
        return args
    if not isinstance(args, dict):
        return str(args or "")
    if args.get("memory_ids"):
        raw_memory_ids = args.get("memory_ids", [])
        if isinstance(raw_memory_ids, str):
            memory_ids = [token.strip() for token in raw_memory_ids.replace("，", ",").replace(" ", ",").split(",") if token.strip()]
        else:
            memory_ids = [str(memory_id).strip() for memory_id in raw_memory_ids if str(memory_id).strip()]
        parts: List[str] = []
        if memory_ids:
            parts.append(f"记忆数：{len(memory_ids)}")
        content = str(args.get("content", "") or "").strip()
        if content:
            preview = content[:36] + ("…" if len(content) > 36 else "")
            parts.append(f"内容：{preview}")
        category = str(args.get("category", "") or "").strip()
        if category:
            parts.append(f"分类：{category}")
        reason = str(args.get("reason", "") or "").strip()
        if reason:
            preview = reason[:24] + ("…" if len(reason) > 24 else "")
            parts.append(f"原因：{preview}")
        if parts:
            return "；".join(parts)
    if args.get("query"):
        return str(args.get("query"))
    if args.get("content"):
        parts: List[str] = []
        category = str(args.get("category", "") or "").strip()
        content = str(args.get("content", "") or "").strip()
        reason = str(args.get("reason", "") or "").strip()
        if category:
            parts.append(f"分类：{category}")
        if content:
            preview = content[:36] + ("…" if len(content) > 36 else "")
            parts.append(f"内容：{preview}")
        if reason:
            preview = reason[:24] + ("…" if len(reason) > 24 else "")
            parts.append(f"原因：{preview}")
        if parts:
            return "；".join(parts)

    label_map = {
        "category": "类别",
        "course_name": "课程",
        "teacher": "教师",
        "points": "积分",
    }
    parts: List[str] = []
    for key in ("category", "course_name", "teacher", "points"):
        value = str(args.get(key, "") or "").strip()
        if value:
            parts.append(f"{label_map.get(key, key)}：{value}")
    if parts:
        return "；".join(parts)
    return json.dumps(args, ensure_ascii=False) if args else ""


def append_text_part(parts: List[Dict[str, Any]], delta: str) -> None:
    if not delta:
        return
    if parts and parts[-1].get("type") == "text":
        parts[-1]["content"] = f"{parts[-1].get('content', '')}{delta}"
        return
    parts.append({"type": "text", "content": delta})


def unseen_text(existing: str, incoming: str) -> str:
    if not incoming:
        return ""
    if not existing:
        return incoming
    if incoming == existing or existing.endswith(incoming):
        return ""
    if incoming.startswith(existing):
        return incoming[len(existing):]
    overlap = min(len(existing), len(incoming))
    for size in range(overlap, 0, -1):
        if existing.endswith(incoming[:size]):
            return incoming[size:]
    return incoming


def split_stream_step(step: Any) -> tuple[str, Any]:
    if isinstance(step, dict):
        mode = step.get("type")
        if isinstance(mode, str) and "data" in step:
            return mode, step.get("data")
    if isinstance(step, tuple) and len(step) >= 2 and isinstance(step[0], str):
        return step[0], step[1]
    return "updates", step


def iter_update_messages(update: Any) -> List[Any]:
    messages: List[Any] = []
    if not isinstance(update, dict):
        return messages
    for value in update.values():
        payload = value.get("messages") if isinstance(value, dict) else value
        if isinstance(payload, list):
            messages.extend(payload)
        elif payload is not None:
            messages.append(payload)
    return messages


def build_graph_input_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    history: List[Dict[str, str]] = []
    for msg in messages:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role not in ("user", "assistant") or not content or msg.get("is_error_fallback"):
            continue
        history.append({"role": role, "content": content})
    return history


def truncate_title(title: str) -> str:
    cleaned = title.strip()
    if not cleaned:
        return "新对话"
    if len(cleaned) <= MAX_TITLE_LENGTH:
        return cleaned
    return cleaned[:MAX_TITLE_LENGTH].rstrip(" ,，。；;") or "新对话"


def summarize_title(messages: List[Dict[str, Any]]) -> str:
    lines = []
    for m in messages:
        c = (m.get("content") or "").strip()
        if c:
            lines.append(f"{m['role']}: {c}")
    transcript = "\n".join(lines)
    if not transcript:
        return "新对话"
    try:
        return truncate_title(summary_chain.invoke({"input": transcript}).strip())
    except Exception:
        return "新对话"


def register_active_stream_stop(user_id: str, conversation_id: str) -> Event:
    stop_event = Event()
    stream_key = (user_id, conversation_id)
    with active_stream_stops_lock:
        previous = active_stream_stops.get(stream_key)
        if previous is not None:
            previous.set()
        active_stream_stops[stream_key] = stop_event
    return stop_event


def request_active_stream_stop(user_id: str, conversation_id: str) -> bool:
    with active_stream_stops_lock:
        stop_event = active_stream_stops.get((user_id, conversation_id))
    if stop_event is None:
        return False
    stop_event.set()
    return True


def clear_active_stream_stop(user_id: str, conversation_id: str, stop_event: Event) -> None:
    stream_key = (user_id, conversation_id)
    with active_stream_stops_lock:
        current = active_stream_stops.get(stream_key)
        if current is stop_event:
            active_stream_stops.pop(stream_key, None)


def finalize_stream_text(atxt: str, final_ai_text: str, parts: List[Dict[str, Any]]) -> str:
    if final_ai_text:
        if not atxt:
            atxt = final_ai_text
            append_text_part(parts, final_ai_text)
        elif final_ai_text.startswith(atxt):
            suffix = final_ai_text[len(atxt):]
            if suffix:
                atxt += suffix
                append_text_part(parts, suffix)
    return atxt


def mark_running_tool_parts_stopped(parts: List[Dict[str, Any]]) -> None:
    for part in parts:
        if part.get("type") != "tool" or part.get("status") != "running":
            continue
        part["status"] = "stopped"
        label = str(part.get("status_label") or part.get("tool_name") or "工具调用")
        part["status_label"] = f"{label}（已停止）"


def persist_assistant_message(
    user_id: str,
    conversation_id: str,
    model: str,
    content: str,
    parts: List[Dict[str, Any]],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    normalized_parts = [dict(part) for part in parts]
    normalized_content = content.strip()
    if not normalized_content and not normalized_parts:
        normalized_content = "已停止响应。"
        normalized_parts = [{"type": "text", "content": normalized_content}]

    amsg = {
        "id": str(uuid4()), "role": "assistant", "content": normalized_content,
        "timestamp": now_iso(),
        "parts": normalized_parts,
        "feedback": None,
    }
    c2 = chat_store.append_message(user_id, conversation_id, amsg, model=model)
    if c2 is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if c2["title"] == "新对话":
        c2 = chat_store.update_conversation(
            user_id,
            conversation_id,
            title=summarize_title(c2["messages"]),
            model=model,
            updated_at=now_iso(),
        )
        if c2 is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    return amsg, make_conversation_summary(c2)


def refresh_edu_session_status(token: str) -> Dict[str, Any] | None:
    session = get_session(token)
    if not session:
        return None
    if session.get("student_type") != "undergraduate":
        return session
    if not session.get("edu_authenticated"):
        return session

    cookies = session.get("edu_cookies") or []
    if not cookies:
        update_session(
            token,
            {
                "edu_authenticated": False,
                "edu_cookies": None,
                "edu_identifier": "",
                "edu_status_message": "教务登录已过期，请重新登录。",
            },
        )
        return get_session(token)

    try:
        client = JwchClient.from_cookies(
            session.get("user_id", ""),
            cookies,
            session.get("edu_identifier", ""),
        )
        client.validate_session()
        if session.get("edu_status_message"):
            update_session(token, {"edu_status_message": ""})
            return get_session(token)
        return session
    except JwchSessionError:
        logger.info("Edu session expired for %s", mask_user_id(session.get("user_id", "")))
        update_session(
            token,
            {
                "edu_authenticated": False,
                "edu_cookies": None,
                "edu_identifier": "",
                "edu_status_message": "教务登录已过期，请重新登录。",
            },
        )
        return get_session(token)
    except Exception as exc:
        logger.warning("Edu session validation failed: %s", type(exc).__name__)
        return session


def _resolve_memory_proposal(
    conversation: Dict[str, Any],
    message_id: str,
    tool_id: str,
) -> tuple[List[Dict[str, Any]], int, Dict[str, Any], Dict[str, Any]] | None:
    for message in conversation.get("messages", []):
        if message.get("id") != message_id:
            continue
        parts = list(message.get("parts") or [])
        for index, part in enumerate(parts):
            if part.get("type") != "tool":
                continue
            if part.get("tool_id") != tool_id:
                continue
            if part.get("tool_name") not in {"save_user_memory", "delete_user_memory"}:
                continue
            data = part.get("data")
            if isinstance(data, dict) and data.get("mode") in {"save_request", "delete_request"}:
                return parts, index, part, data
        return None
    return None


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(req: LoginRequest, request: Request) -> JSONResponse:
    if req.student_type != "undergraduate":
        raise HTTPException(status_code=403, detail="当前仅支持本科生通过教务系统登录，研究生登录暂未开放。")

    try:
        client = JwchClient(req.student_id, req.password)
        client.login()
    except JwchLoginError as exc:
        logger.warning("Edu login rejected for %s: %s", mask_user_id(req.student_id), type(exc).__name__)
        raise HTTPException(status_code=401, detail="教务系统登录失败，请检查学号和密码。") from exc
    except Exception as exc:
        logger.warning("Edu login unavailable for %s: %s", mask_user_id(req.student_id), type(exc).__name__)
        raise HTTPException(status_code=503, detail="教务系统连接失败，请稍后重试。") from exc

    existing_token = request.cookies.get(AUTH_COOKIE_NAME)
    if existing_token:
        invalidate_session(existing_token)

    token = create_session(
        user_id=req.student_id,
        student_type=req.student_type,
        display_name=req.student_id,
        edu_authenticated=True,
        edu_cookies=[{"name": c.name, "value": c.value} for c in client.session.cookies],
    )
    if client.identifier:
        update_session(token, {"edu_identifier": client.identifier, "edu_status_message": ""})

    response = JSONResponse(
        {
            "user": {
                "user_id": req.student_id,
                "student_type": req.student_type,
                "display_name": req.student_id,
                "edu_authenticated": True,
            },
            "edu_error": "",
        }
    )
    _set_auth_cookie(response, token, request)
    return response


@app.post("/api/auth/logout")
def logout(request: Request, user: AuthUser = Depends(require_auth)) -> JSONResponse:
    invalidate_session(user.token)
    response = JSONResponse({"ok": True})
    _clear_auth_cookie(response, request)
    return response


@app.get("/api/auth/me")
def auth_me(user: AuthUser = Depends(require_auth)) -> Dict[str, Any]:
    session = refresh_edu_session_status(user.token) or get_session(user.token) or {}
    return {
        "user_id": session.get("user_id", user.user_id),
        "student_type": session.get("student_type", user.student_type),
        "display_name": session.get("display_name", user.display_name),
        "edu_authenticated": session.get("edu_authenticated", user.edu_authenticated),
        "edu_error": session.get("edu_status_message", ""),
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@app.get("/api/models")
def list_models() -> List[Dict[str, str]]:
    return [{"id": mid, "label": lbl} for mid, lbl in MODEL_OPTIONS.items()]


# ---------------------------------------------------------------------------
# Conversations (auth-protected, per-user)
# ---------------------------------------------------------------------------


@app.get("/api/conversations", response_model=List[ConversationSummary])
def list_conversations(user: AuthUser = Depends(require_auth)):
    return chat_store.list_conversations(user.user_id)


@app.post("/api/conversations", response_model=ConversationRecord)
def create_conversation(req: ConversationCreateRequest, user: AuthUser = Depends(require_auth)):
    reusable = chat_store.find_reusable_conversation(user.user_id)
    if reusable is not None:
        requested_model = normalize_model_id(req.model)
        current_model = normalize_model_id(reusable.get("model"))
        if requested_model != reusable.get("model") or current_model != reusable.get("model"):
            updated = chat_store.update_conversation(
                user.user_id,
                reusable["id"],
                model=requested_model,
                updated_at=now_iso(),
            )
            if updated is not None:
                reusable = updated
        return reusable
    c = create_conversation_record(req.model)
    return chat_store.create_conversation(user.user_id, c)


@app.get("/api/conversations/{cid}", response_model=ConversationRecord)
def get_conversation(cid: str, user: AuthUser = Depends(require_auth)):
    conversation = chat_store.get_conversation(user.user_id, cid)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    normalized_model = normalize_model_id(conversation.get("model"))
    if normalized_model != conversation.get("model"):
        updated = chat_store.update_conversation(
            user.user_id,
            cid,
            model=normalized_model,
            updated_at=now_iso(),
        )
        if updated is not None:
            conversation = updated
    return conversation


@app.patch("/api/conversations/{cid}", response_model=ConversationRecord)
def update_conversation(cid: str, req: ConversationUpdateRequest, user: AuthUser = Depends(require_auth)):
    conversation = chat_store.update_conversation(
        user.user_id,
        cid,
        title=req.title.strip() if req.title is not None else None,
        model=req.model if req.model in MODEL_OPTIONS else None,
        updated_at=now_iso(),
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str, user: AuthUser = Depends(require_auth)):
    deleted = chat_store.delete_conversation(user.user_id, cid)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True}


@app.post("/api/conversations/{cid}/feedback")
def update_feedback(cid: str, req: FeedbackUpdateRequest, user: AuthUser = Depends(require_auth)):
    if chat_store.update_feedback(user.user_id, cid, req.message_id, req.feedback):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Message not found")


@app.post("/api/conversations/{cid}/memory-proposals/{tool_id}")
def update_memory_proposal(
    cid: str,
    tool_id: str,
    req: MemoryProposalActionRequest,
    user: AuthUser = Depends(require_auth),
):
    conversation = chat_store.get_conversation(user.user_id, cid)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    resolved = _resolve_memory_proposal(conversation, req.message_id, tool_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Memory proposal not found")

    parts, part_index, part, data = resolved
    current_status = str(data.get("status") or "")
    timestamp = now_iso()
    tool_name = str(part.get("tool_name") or "")

    if req.action == "confirm":
        if current_status in {"saved", "deleted"}:
            return {"ok": True, "part": part}
        if current_status != "pending_confirmation":
            raise HTTPException(status_code=409, detail="当前记忆建议无法确认执行")

        if tool_name == "save_user_memory":
            saved_memory = user_memory_store.save_memory(
                user_id=user.user_id,
                content=str(data.get("content") or "").strip(),
                category=str(data.get("category") or "").strip(),
                reason=str(data.get("reason") or "").strip(),
                source="assistant",
            )
            updated_part = {
                **part,
                "status_label": "记忆已保存",
                "data": {
                    **data,
                    "status": "saved",
                    "confirmed_at": timestamp,
                    "memory_id": saved_memory.get("id"),
                    "saved_memory": saved_memory,
                },
            }
        elif tool_name == "delete_user_memory":
            memory_ids = [str(memory_id).strip() for memory_id in data.get("memory_ids", []) if str(memory_id).strip()]
            deleted_items = user_memory_store.delete_memories(user.user_id, memory_ids)
            if deleted_items:
                updated_part = {
                    **part,
                    "status_label": "记忆已删除",
                    "data": {
                        **data,
                        "status": "deleted",
                        "deleted_at": timestamp,
                        "deleted_count": len(deleted_items),
                        "deleted_items": deleted_items,
                    },
                }
            else:
                existing_items = user_memory_store.get_memories_by_ids(user.user_id, memory_ids, include_inactive=True)
                next_status = "already_deleted" if existing_items else "not_found"
                next_label = "记忆已不存在" if next_status == "already_deleted" else "未找到待删除记忆"
                updated_part = {
                    **part,
                    "status_label": next_label,
                    "data": {
                        **data,
                        "status": next_status,
                        "deleted_at": timestamp,
                        "deleted_count": 0,
                        "deleted_items": [],
                    },
                }
        else:
            raise HTTPException(status_code=400, detail="未知的记忆操作类型")
    else:
        if current_status == "dismissed":
            return {"ok": True, "part": part}
        if current_status != "pending_confirmation":
            raise HTTPException(status_code=409, detail="当前记忆建议无法忽略")
        dismissed_label = "已忽略保存建议" if tool_name == "save_user_memory" else "已忽略删除建议"
        updated_part = {
            **part,
            "status_label": dismissed_label,
            "data": {
                **data,
                "status": "dismissed",
                "dismissed_at": timestamp,
            },
        }

    parts[part_index] = updated_part
    updated = chat_store.update_message_parts(user.user_id, cid, req.message_id, parts)
    if not updated:
        raise HTTPException(status_code=500, detail="更新记忆建议状态失败")
    return {"ok": True, "part": updated_part}


# ---------------------------------------------------------------------------
# Message streaming
# ---------------------------------------------------------------------------

@app.post("/api/conversations/{cid}/stop")
def stop_message_stream(cid: str, user: AuthUser = Depends(require_auth)):
    conversation = chat_store.get_conversation(user.user_id, cid)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": request_active_stream_stop(user.user_id, cid)}

@app.post("/api/conversations/{cid}/messages")
async def create_message(
    cid: str,
    req: MessageCreateRequest,
    request: Request,
    user: AuthUser = Depends(require_auth),
):
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty")

    conv = chat_store.get_conversation(user.user_id, cid)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    sel = normalize_model_id(req.model if req.model is not None else conv.get("model"))
    umsg = {
        "id": str(uuid4()), "role": "user", "content": content,
        "timestamp": now_iso(), "parts": [{"type": "text", "content": content}],
        "feedback": None,
    }
    conv = chat_store.append_message(user.user_id, cid, umsg, model=sel)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    graph_messages = build_graph_input_messages(conv["messages"])

    sess = refresh_edu_session_status(user.token) or get_session(user.token)
    edu_ctx = {
        "user_id": user.user_id,
        "edu_authenticated": sess.get("edu_authenticated", False) if sess else False,
        "edu_cookies": sess.get("edu_cookies") if sess else None,
        "edu_identifier": sess.get("edu_identifier", "") if sess else "",
        "edu_status_message": sess.get("edu_status_message", "") if sess else "",
    }
    runtime_graph = build_graph(edu_ctx, use_checkpointer=False)
    stop_event = register_active_stream_stop(user.user_id, cid)
    graph_config = {"configurable": {"model": sel, "thread_id": conv["thread_id"]}}

    async def event_stream() -> AsyncIterator[bytes]:
        set_current_edu_session(edu_ctx)
        reset_search_citation_counter()
        atxt = ""
        final_ai_text = ""
        pending: Dict[str, Dict[str, Any]] = {}
        parts: List[Dict[str, Any]] = []
        final_payload: Dict[str, Any] | None = None
        stream_stopped = False
        client_disconnected = False

        def build_done_payload(stopped: bool) -> Dict[str, Any]:
            nonlocal atxt, final_payload
            if final_payload is not None:
                return final_payload
            atxt = finalize_stream_text(atxt, final_ai_text, parts)
            if stopped:
                mark_running_tool_parts_stopped(parts)
            amsg, summary = persist_assistant_message(user.user_id, cid, sel, atxt, parts)
            final_payload = {"message": amsg, "conversation": summary, "stopped": stopped}
            return final_payload

        try:
            yield serialize_event("user", umsg)
            async for step in runtime_graph.astream(
                {"messages": graph_messages},
                stream_mode=["messages", "updates"],
                config=graph_config,
                version="v2",
            ):
                if stop_event.is_set():
                    stream_stopped = True
                    break
                if await request.is_disconnected():
                    stream_stopped = True
                    client_disconnected = True
                    break

                mode, payload = split_stream_step(step)

                if mode == "messages":
                    if not isinstance(payload, tuple) or not payload:
                        continue
                    mc = payload[0]
                    mc_type = type(mc).__name__
                    if mc_type == "ToolMessage" or not mc_type.startswith("AIMessage"):
                        continue
                    delta = unseen_text(atxt, extract_text_content(getattr(mc, "content", "")))
                    if delta:
                        atxt += delta
                        append_text_part(parts, delta)
                        yield serialize_event("chunk", {"delta": delta})
                    continue

                if mode != "updates":
                    continue

                for mc in iter_update_messages(payload):
                    mc_type = type(mc).__name__
                    if hasattr(mc, "tool_calls") and mc.tool_calls:
                        mc = combine_tool_calls(mc)
                        for tc in mc.tool_calls:
                            if not isinstance(tc, dict):
                                continue
                            tn = tc.get("name", "")
                            ti = clean_tool_call_id(tc.get("id", ""))
                            if ti in pending:
                                continue
                            a = tc.get("args") or {}
                            q = summarize_tool_args(a)
                            lb = TOOL_LABELS.get(tn, {"running": f"正在调用 {tn}", "complete": f"{tn} 完成"})
                            tp = {
                                "type": "tool", "tool_id": ti, "tool_name": tn,
                                "query": q, "status": "running", "status_label": lb["running"],
                                "urls": [], "data": None,
                            }
                            pending[ti] = tp
                            parts.append(tp)
                            yield serialize_event("tool_call", tp)
                        continue

                    if mc_type == "ToolMessage":
                        ci = clean_tool_call_id(getattr(mc, "tool_call_id", ""))
                        mi = matching_tool_call_id(pending.keys(), ci)
                        if not mi:
                            continue
                        tp = pending[mi]
                        tn = tp["tool_name"]
                        lb = TOOL_LABELS.get(tn, {"running": "", "complete": f"{tn} 完成"})
                        tp["status"] = "complete"
                        tp["status_label"] = lb["complete"]
                        rc = extract_text_content(getattr(mc, "content", ""))
                        af = getattr(mc, "artifact", None)
                        tp["urls"] = extract_urls(rc, af)
                        tp["data"] = extract_structured_data(tn, af, rc)
                        yield serialize_event("tool_result", tp)
                        continue

                    if not mc_type.startswith("AIMessage"):
                        continue

                    candidate = extract_text_content(getattr(mc, "content", ""))
                    if len(candidate) > len(final_ai_text):
                        final_ai_text = candidate

                if stop_event.is_set():
                    stream_stopped = True
                    break
                if await request.is_disconnected():
                    stream_stopped = True
                    client_disconnected = True
                    break

            payload = build_done_payload(stream_stopped)
            if not client_disconnected:
                yield serialize_event("done", payload)
        except asyncio.CancelledError:
            logger.info("Stream cancelled for %s", cid)
            build_done_payload(True)
            return
        except Exception:
            if final_payload is not None:
                logger.exception("Stream failed after completion for %s", cid)
                return
            logger.exception("Stream failed for %s", cid)
            fallback_text = "暂时无法生成回复，请稍后再试。"
            fallback_msg = {
                "id": str(uuid4()), "role": "assistant", "content": fallback_text,
                "timestamp": now_iso(),
                "parts": [{"type": "text", "content": fallback_text}],
                "feedback": None,
                "is_error_fallback": True,
            }
            fallback_summary: Dict[str, Any] | None = None
            try:
                c2 = chat_store.append_message(user.user_id, cid, fallback_msg, model=sel)
                if c2 is not None:
                    fallback_summary = make_conversation_summary(c2)
            except Exception:
                logger.exception("Persisting fallback message failed for %s", cid)
            yield serialize_event(
                "error",
                {
                    "message": "生成回复失败，请稍后重试。",
                    "fallback": fallback_msg,
                    "conversation": fallback_summary,
                },
            )
        finally:
            clear_active_stream_stop(user.user_id, cid, stop_event)
            reset_search_citation_counter()
            set_current_edu_session(None)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
if (FRONTEND_DIST / "ui").exists():
    app.mount("/ui", StaticFiles(directory=FRONTEND_DIST / "ui"), name="ui")


@app.get("/{full_path:path}")
def serve_frontend(full_path: str) -> Any:
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {"message": "Frontend build not found. Run `npm run build` in /frontend or use the Vite dev server."},
        status_code=503,
    )
