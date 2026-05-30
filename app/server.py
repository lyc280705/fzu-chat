from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import requests
import time
from threading import Event
from threading import Lock
from threading import Thread
from typing import Any, AsyncIterator, Dict, Iterable, List, Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
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
from .campus_recommendations import (
    build_contextual_recommendation,
    get_cached_browser_location_text,
    manual_location_options,
    schedule_browser_location_text_refresh,
)
from .campus_dynamic_context import (
    build_dynamic_campus_context,
    is_dynamic_context_request,
    purge_dynamic_context_user_data,
    refresh_signal_snapshots,
)
from .chat_store import chat_store
from .edu_tools import set_current_edu_session
from .graph import (
    CHAT_MODEL_OPTIONS,
    DEFAULT_CHAT_MODEL,
    KIMI_CHAT_MODEL,
    build_graph,
    build_runtime_system_context,
    build_transient_location_system_context,
    reset_search_citation_counter,
    summary_chain,
    warm_teaching_week_cache_async,
)
from .jwch_client import JwchClient, JwchLoginError, JwchSessionError
from .memory_store import user_memory_store
from .oauth import (
    OAuthConfigError,
    OAuthError,
    build_authorization_url,
    consume_oauth_state,
    create_oauth_state,
    fetch_visitor_profile,
    get_provider_config,
    list_provider_status,
    provider_display_name,
)
from .runtime_state import (
    acquire_dedupe_lock,
    acquire_pair_slot,
    acquire_slot,
    fixed_window_rate_limit,
    increment_counter,
    record_http_request,
    redis_health,
    release_slot,
    render_prometheus_metrics,
    set_gauge,
)
from .security_utils import env_flag, mask_user_id

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
ASSETS_DIR = BASE_DIR / "png"
MAX_TITLE_LENGTH = int(os.getenv("FZU_CHAT_MAX_TITLE_LENGTH", "20"))
AUTH_COOKIE_NAME = os.getenv("FZU_CHAT_AUTH_COOKIE_NAME", "fzu_session")
AUTH_COOKIE_SECURE_MODE = os.getenv("FZU_CHAT_AUTH_COOKIE_SECURE", "auto").strip().lower()
AUTH_COOKIE_SAMESITE = os.getenv("FZU_CHAT_AUTH_COOKIE_SAMESITE", "strict").strip().lower()
EDU_SESSION_TTL = max(300, int(os.getenv("FZU_CHAT_EDU_SESSION_TTL", "14400")))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = max(60, int(os.getenv("FZU_CHAT_LOGIN_RATE_LIMIT_WINDOW", "900")))
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = max(1, int(os.getenv("FZU_CHAT_LOGIN_RATE_LIMIT_ATTEMPTS", "8")))
EDU_RELOGIN_RATE_LIMIT_WINDOW_SECONDS = max(60, int(os.getenv("FZU_CHAT_EDU_RELOGIN_RATE_LIMIT_WINDOW", "600")))
EDU_RELOGIN_RATE_LIMIT_MAX_ATTEMPTS = max(1, int(os.getenv("FZU_CHAT_EDU_RELOGIN_RATE_LIMIT_ATTEMPTS", "6")))
CONVERSATION_CREATE_RATE_LIMIT_WINDOW_SECONDS = max(60, int(os.getenv("FZU_CHAT_CONVERSATION_CREATE_RATE_LIMIT_WINDOW", "300")))
CONVERSATION_CREATE_RATE_LIMIT_MAX_ATTEMPTS = max(1, int(os.getenv("FZU_CHAT_CONVERSATION_CREATE_RATE_LIMIT_ATTEMPTS", "20")))
MESSAGE_RATE_LIMIT_WINDOW_SECONDS = max(10, int(os.getenv("FZU_CHAT_MESSAGE_RATE_LIMIT_WINDOW", "60")))
MESSAGE_RATE_LIMIT_MAX_ATTEMPTS = max(1, int(os.getenv("FZU_CHAT_MESSAGE_RATE_LIMIT_ATTEMPTS", "12")))
TOOL_HISTORY_MAX_CHARS = max(2000, int(os.getenv("FZU_CHAT_TOOL_HISTORY_MAX_CHARS", "120000")))
PUBLIC_DOCS = env_flag("FZU_CHAT_PUBLIC_DOCS", False)
GLOBAL_STREAM_LIMIT = max(1, int(os.getenv("FZU_CHAT_GLOBAL_STREAM_LIMIT", "80")))
USER_STREAM_LIMIT = max(1, int(os.getenv("FZU_CHAT_USER_STREAM_LIMIT", "5")))
STREAM_SLOT_TTL_SECONDS = max(60, int(os.getenv("FZU_CHAT_STREAM_SLOT_TTL_SECONDS", "900")))
EDU_LOGIN_CONCURRENCY_LIMIT = max(1, int(os.getenv("FZU_CHAT_EDU_LOGIN_CONCURRENCY", "8")))
STATIC_FALLBACK_MODE = os.getenv("FZU_CHAT_STATIC_FALLBACK", "strict").strip().lower()
METRICS_ENABLED = env_flag("FZU_CHAT_METRICS_ENABLED", True)
METRICS_TOKEN = os.getenv("FZU_CHAT_METRICS_TOKEN", "").strip()
API_NO_STORE = "no-store, no-cache, must-revalidate, max-age=0, private"
BROWSER_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "connect-src 'self'",
        "img-src 'self' data:",
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self' data:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

if AUTH_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    AUTH_COOKIE_SAMESITE = "strict"

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
    "recommend_campus_context": {"running": "正在生成校园推荐", "complete": "校园推荐已生成"},
}
logger = logging.getLogger(__name__)

active_stream_stops: Dict[tuple[str, str], Event] = {}
active_stream_stops_lock = Lock()
pending_title_updates: Dict[tuple[str, str], asyncio.Task[None]] = {}
pending_title_updates_lock = Lock()
conversation_event_subscribers: Dict[str, List[asyncio.Queue[Dict[str, Any]]]] = {}
conversation_event_subscribers_lock = Lock()
SCAN_PATH_EXACT = {
    "/.env",
    "/env",
    "/containers/json",
    "/server-status",
    "/server-info",
}
SCAN_PATH_PREFIXES = (
    "/.git",
    "/.svn",
    "/.hg",
    "/.aws",
    "/.ssh",
    "/phpunit",
    "/vendor",
    "/wp",
    "/wordpress",
    "/thinkphp",
    "/geoserver",
    "/webui",
    "/actuator",
    "/cgi-bin",
    "/boaform",
    "/manager",
    "/solr",
    "/hudson",
    "/jenkins",
)
SCAN_PATH_SUBSTRINGS = (
    "phpunit",
    "thinkphp",
    "geoserver",
    "wp-admin",
    "wp-login",
    "laravel",
    "eval-stdin",
)


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
                headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
                headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(self)")
                headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
                headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
                headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
                headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
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


def _request_origin(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    scheme = forwarded_proto.split(",", 1)[0].strip().lower() if forwarded_proto else request.url.scheme
    forwarded_host = request.headers.get("x-forwarded-host", "")
    host = forwarded_host.split(",", 1)[0].strip() if forwarded_host else request.headers.get("host", request.url.netloc)
    return f"{scheme}://{host}"


def _is_same_origin_url(candidate: str, request: Request) -> bool:
    parsed = urlparse(candidate)
    expected = urlparse(_request_origin(request))
    if not parsed.scheme or not parsed.netloc:
        return False
    return parsed.scheme.lower() == expected.scheme.lower() and parsed.netloc.lower() == expected.netloc.lower()


def _enforce_browser_request_integrity(request: Request) -> None:
    if request.method.upper() not in BROWSER_UNSAFE_METHODS:
        return
    if not request.url.path.startswith("/api/"):
        return

    sec_fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
    if sec_fetch_site and sec_fetch_site not in {"same-origin", "same-site", "none"}:
        raise HTTPException(status_code=403, detail="检测到跨站写操作，请从本站页面重试。")

    origin = request.headers.get("origin", "").strip()
    if origin and not _is_same_origin_url(origin, request):
        raise HTTPException(status_code=403, detail="请求来源无效，请从本站页面重试。")

    referer = request.headers.get("referer", "").strip()
    if referer and not _is_same_origin_url(referer, request):
        raise HTTPException(status_code=403, detail="请求来源无效，请从本站页面重试。")


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _request_socket_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _is_private_or_loopback_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def _metrics_allowed(request: Request) -> bool:
    if METRICS_TOKEN:
        auth = request.headers.get("authorization", "").strip()
        if auth == f"Bearer {METRICS_TOKEN}":
            return True
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        return _is_private_or_loopback_ip(forwarded_for.split(",", 1)[0].strip())
    return _is_private_or_loopback_ip(_request_socket_ip(request))


def _is_scan_path(path: str) -> bool:
    normalized = "/" + path.lstrip("/")
    lower_path = normalized.lower()
    if lower_path in SCAN_PATH_EXACT:
        return True
    if any(lower_path.startswith(prefix) for prefix in SCAN_PATH_PREFIXES):
        return True
    if any(part in lower_path for part in SCAN_PATH_SUBSTRINGS):
        return True
    if "/." in lower_path and not lower_path.startswith("/.well-known/"):
        return True
    return False


def _route_metric_label(request: Request) -> str:
    route = request.scope.get("route")
    label = getattr(route, "path", "") if route is not None else ""
    if label:
        return str(label)
    path = request.url.path
    path = re.sub(r"/[0-9a-f]{8}-[0-9a-f-]{27,}", "/{uuid}", path, flags=re.IGNORECASE)
    path = re.sub(r"/\d+", "/{id}", path)
    return path or "/"


def _rate_limit_key(prefix: str, request: Request, subject: str = "") -> str:
    normalized_subject = re.sub(r"\s+", "", subject).strip()[:64] or "-"
    return f"{prefix}:{_client_ip(request)}:{normalized_subject}"


def _enforce_rate_limit(key: str, limit: int, window_seconds: int, detail: str) -> None:
    if not fixed_window_rate_limit(key, limit, window_seconds):
        increment_counter("fzu_chat_rate_limit_rejections_total")
        raise HTTPException(status_code=429, detail=detail)


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


def _extract_auth_token(authorization: str | None, session_cookie: str | None) -> str | None:
    if authorization:
        return authorization[7:] if authorization.startswith("Bearer ") else authorization
    if session_cookie:
        return session_cookie
    return None


@asynccontextmanager
async def lifespan(_: FastAPI):
    warm_teaching_week_cache_async()
    yield


app = FastAPI(
    title="FZU Chat API",
    version="7.7.0",
    lifespan=lifespan,
    docs_url="/docs" if PUBLIC_DOCS else None,
    redoc_url="/redoc" if PUBLIC_DOCS else None,
    openapi_url="/openapi.json" if PUBLIC_DOCS else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)


@app.middleware("http")
async def request_hardening_and_metrics(request: Request, call_next):
    started_at = time.perf_counter()
    if _is_scan_path(request.url.path):
        increment_counter("fzu_chat_scan_path_rejections_total")
        response = JSONResponse({"detail": "Not found"}, status_code=404)
        record_http_request(request.method, "scan_path", response.status_code, time.perf_counter() - started_at)
        return response
    try:
        _enforce_browser_request_integrity(request)
    except HTTPException as exc:
        response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        record_http_request(request.method, request.url.path, response.status_code, time.perf_counter() - started_at)
        return response
    try:
        response = await call_next(request)
    except Exception:
        record_http_request(request.method, _route_metric_label(request), 500, time.perf_counter() - started_at)
        raise
    duration = time.perf_counter() - started_at
    record_http_request(request.method, _route_metric_label(request), response.status_code, duration)
    if request.url.path == "/" or request.url.path.endswith("/index.html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    elif request.url.path.startswith("/ui/"):
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    return response


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
    token = _extract_auth_token(authorization, session_cookie)
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
    accepted_legal: bool = False


class EduReloginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=100)


class OAuthProviderStatus(BaseModel):
    provider: Literal["wechat", "qq"]
    label: str
    configured: bool


class ConversationCreateRequest(BaseModel):
    model: str = DEFAULT_CHAT_MODEL


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=40)
    model: str | None = None


class MessageContextLocation(BaseModel):
    lat: float
    lng: float
    accuracy: float | None = None
    timestamp: str | None = Field(default=None, max_length=80)


class MessageContext(BaseModel):
    location: MessageContextLocation | None = None
    travel_mode: Literal["walking", "bicycling"] = "walking"


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    model: str | None = None
    thinking_enabled: bool | None = None
    rerun_message_id: str | None = Field(default=None, max_length=80)
    context: MessageContext | None = None


class RecommendationLocation(BaseModel):
    lat: float
    lng: float
    accuracy: float | None = None


class ContextualRecommendationRequest(BaseModel):
    scenario: Literal["auto", "dining", "study"] = "auto"
    travel_mode: Literal["walking", "bicycling"] = "walking"
    location: RecommendationLocation | None = None
    manual_location_id: str | None = Field(default=None, max_length=80)
    seen_grade_digest: str | None = Field(default=None, max_length=80)


class LocationContextWarmupRequest(BaseModel):
    location: RecommendationLocation


class FeedbackUpdateRequest(BaseModel):
    message_id: str
    feedback: Literal["up", "down"] | None = None


class MemoryProposalActionRequest(BaseModel):
    message_id: str
    action: Literal["confirm", "dismiss"]


class MessageRecord(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    timestamp: str
    parts: List[Dict[str, Any]] = Field(default_factory=list)
    reasoning_content: str | None = None
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


class ConversationListResponse(BaseModel):
    items: List[ConversationSummary]
    next_cursor: str | None = None


class UserDataSummary(BaseModel):
    conversation_count: int
    message_count: int
    memory_count: int


class UserDataResetResponse(BaseModel):
    ok: bool = True
    cleared: UserDataSummary


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
        "thread_id": str(uuid4()), "created_at": ts, "updated_at": ts, "runtime_context": "", "messages": [],
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
        "recommend_campus_context",
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
    if any(key in args for key in ("scenario", "manual_location_id", "latitude", "longitude", "travel_mode")):
        scenario_label = {
            "auto": "智能校园推荐",
            "dining": "食堂推荐",
            "study": "自习/复习建议",
        }.get(str(args.get("scenario") or "auto").strip(), "智能校园推荐")
        travel_mode_label = {
            "walking": "步行",
            "bicycling": "骑行",
            "bicycle": "骑行",
            "bike": "骑行",
            "cycling": "骑行",
            "骑行": "骑行",
            "自行车": "骑行",
        }.get(str(args.get("travel_mode") or "walking").strip().lower(), "步行")
        location_label = {
            "qishan_center": "旗山校区中心区",
            "qishan_teaching": "旗山校区教学区",
            "qishan_dorm": "旗山校区生活区",
            "qishan_library": "旗山校区图书馆",
            "qishan_jinjiang": "晋江楼学习中心",
            "qishan_staff_center": "教工活动中心 / 桃李园",
            "qishan_life_zone_1": "旗山校区生活一区",
            "qishan_life_zone_3": "旗山校区生活三区",
            "yishan_center": "怡山校区",
            "tongpan_center": "铜盘校区",
        }.get(str(args.get("manual_location_id") or "").strip(), "")
        parts = [f"场景：{scenario_label}"]
        parts.append(f"出行：{travel_mode_label}")
        if location_label:
            parts.append(f"位置：{location_label}")
        elif args.get("latitude") and args.get("longitude"):
            parts.append("位置：本次授权定位")
        else:
            parts.append("位置：按校内地点库估算")
        return "；".join(parts)
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
        importance = str(args.get("importance", "") or "").strip()
        if category:
            parts.append(f"分类：{category}")
        if content:
            preview = content[:36] + ("…" if len(content) > 36 else "")
            parts.append(f"内容：{preview}")
        if reason:
            preview = reason[:24] + ("…" if len(reason) > 24 else "")
            parts.append(f"原因：{preview}")
        if importance and importance != "0":
            parts.append(f"重要度：{importance}")
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


def should_emit_stream_delta(existing: str, delta: str) -> bool:
    if not delta:
        return False
    if delta.strip():
        return True
    return bool(existing.strip())


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


def extract_reasoning_content(message: Any) -> str:
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(additional_kwargs, dict) or "reasoning_content" not in additional_kwargs:
        return ""
    value = additional_kwargs.get("reasoning_content")
    if isinstance(value, (str, list)):
        return extract_text_content(value)
    return str(value or "")


def _truncate_tool_history_text(text: str) -> str:
    if len(text) <= TOOL_HISTORY_MAX_CHARS:
        return text
    return f"{text[:TOOL_HISTORY_MAX_CHARS].rstrip()}\n\n[工具结果过长，历史上下文中已截断展示]"


def _safe_json_for_history(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _jsonable_for_storage(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError, json.JSONDecodeError):
        return str(value)


def _tool_args_from_part(part: Dict[str, Any]) -> Dict[str, Any]:
    args = part.get("args")
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    query = str(part.get("query") or "").strip()
    if query:
        return {"query": query}
    return {"source": "persisted_conversation_tool_part"}


def _tool_result_content_from_part(part: Dict[str, Any]) -> str:
    raw_content = part.get("raw_content")
    if isinstance(raw_content, str) and raw_content:
        return _truncate_tool_history_text(raw_content)

    payload: Dict[str, Any] = {"tool_name": part.get("tool_name") or "unknown_tool"}
    query = str(part.get("query") or "").strip()
    if query:
        payload["query"] = query
    data = part.get("data")
    if data is not None:
        payload["data"] = data
    urls = part.get("urls")
    if isinstance(urls, list) and urls:
        payload["urls"] = urls
    return _truncate_tool_history_text(_safe_json_for_history(payload))


def _tool_history_messages_from_parts(parts: List[Dict[str, Any]]) -> List[Any]:
    tool_calls: List[Dict[str, Any]] = []
    tool_messages: List[ToolMessage] = []
    for index, part in enumerate(parts):
        if not isinstance(part, dict) or part.get("type") != "tool":
            continue
        tool_name = str(part.get("tool_name") or "unknown_tool").strip() or "unknown_tool"
        tool_id = clean_tool_call_id(str(part.get("tool_id") or "")) or f"history_tool_{index}"
        status = str(part.get("status") or "").strip()
        if status == "running":
            continue
        tool_calls.append(
            {
                "name": tool_name,
                "args": _tool_args_from_part(part),
                "id": tool_id,
            }
        )
        tool_messages.append(
            ToolMessage(
                content=_tool_result_content_from_part(part),
                tool_call_id=tool_id,
                name=tool_name,
            )
        )
    if not tool_calls:
        return []
    return [AIMessage(content="", tool_calls=tool_calls), *tool_messages]


def build_graph_input_messages(messages: List[Dict[str, Any]], model: str) -> List[Any]:
    history: List[Any] = []
    for msg in messages:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        parts = msg.get("parts") if isinstance(msg.get("parts"), list) else []
        if role not in ("user", "assistant") or msg.get("is_error_fallback"):
            continue
        if role == "user":
            if not content:
                continue
            history.append(HumanMessage(content=content))
            continue

        tool_history_messages = _tool_history_messages_from_parts(parts)
        history.extend(tool_history_messages)
        if not content:
            continue
        reasoning_content = msg.get("reasoning_content")
        additional_kwargs: Dict[str, Any] = {}
        if reasoning_content is not None or model == KIMI_CHAT_MODEL:
            additional_kwargs["reasoning_content"] = str(reasoning_content or "")
        history.append(AIMessage(content=content, additional_kwargs=additional_kwargs))
    return history


def truncate_title(title: str) -> str:
    cleaned = title.strip()
    if not cleaned:
        return "新对话"
    if len(cleaned) <= MAX_TITLE_LENGTH:
        return cleaned
    return cleaned[:MAX_TITLE_LENGTH].rstrip(" ,，。；;") or "新对话"


def build_title_summary_transcript(messages: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        content = (message.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"user: {content}")
        if len(lines) >= 6:
            break
    return "\n".join(lines)


async def summarize_title(messages: List[Dict[str, Any]]) -> str:
    transcript = build_title_summary_transcript(messages)
    if not transcript:
        return "新对话"
    try:
        return truncate_title((await summary_chain.ainvoke({"input": transcript})).strip())
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


def register_conversation_event_subscriber(user_id: str) -> asyncio.Queue[Dict[str, Any]]:
    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=8)
    with conversation_event_subscribers_lock:
        conversation_event_subscribers.setdefault(user_id, []).append(queue)
    return queue


def unregister_conversation_event_subscriber(user_id: str, queue: asyncio.Queue[Dict[str, Any]]) -> None:
    with conversation_event_subscribers_lock:
        queues = conversation_event_subscribers.get(user_id)
        if not queues:
            return
        conversation_event_subscribers[user_id] = [item for item in queues if item is not queue]
        if not conversation_event_subscribers[user_id]:
            conversation_event_subscribers.pop(user_id, None)


def publish_conversation_event(user_id: str, event: str, data: Dict[str, Any]) -> None:
    with conversation_event_subscribers_lock:
        queues = list(conversation_event_subscribers.get(user_id, []))
    if not queues:
        return
    payload = {"event": event, "data": data}
    for queue in queues:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.debug("Dropping conversation event for %s due to a full subscriber queue", user_id)


async def update_conversation_title_in_background(
    user_id: str,
    conversation_id: str,
    messages: List[Dict[str, Any]],
) -> None:
    summary: Dict[str, Any] | None = None
    try:
        conversation = chat_store.get_conversation(user_id, conversation_id)
        if conversation is None:
            return
        if conversation.get("title") != "新对话":
            summary = make_conversation_summary(conversation)
            return

        next_title = await summarize_title(messages)
        if next_title != "新对话":
            updated = chat_store.update_conversation(
                user_id,
                conversation_id,
                title=next_title,
                updated_at=conversation["updated_at"],
            )
            if updated is None:
                logger.warning("Conversation disappeared before title update completed: %s", conversation_id)
            else:
                summary = make_conversation_summary(updated)
    except Exception:
        logger.exception("Async title update failed for %s", conversation_id)
    finally:
        if summary is None:
            conversation = chat_store.get_conversation(user_id, conversation_id)
            if conversation is not None:
                summary = make_conversation_summary(conversation)
        if summary is not None:
            publish_conversation_event(user_id, "title", {"conversation": summary})


def schedule_conversation_title_update(
    user_id: str,
    conversation_id: str,
    messages: List[Dict[str, Any]],
) -> None:
    stream_key = (user_id, conversation_id)
    with pending_title_updates_lock:
        existing = pending_title_updates.get(stream_key)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(
            update_conversation_title_in_background(user_id, conversation_id, messages),
            name=f"conversation-title-{conversation_id}",
        )
        pending_title_updates[stream_key] = task

    def cleanup(done_task: asyncio.Task[None]) -> None:
        with pending_title_updates_lock:
            current = pending_title_updates.get(stream_key)
            if current is done_task:
                pending_title_updates.pop(stream_key, None)

    task.add_done_callback(cleanup)


def finalize_stream_text(atxt: str, final_ai_text: str, parts: List[Dict[str, Any]]) -> str:
    if final_ai_text:
        if not atxt:
            if not should_emit_stream_delta(atxt, final_ai_text):
                return atxt
            atxt = final_ai_text
            append_text_part(parts, final_ai_text)
        elif final_ai_text.startswith(atxt):
            suffix = final_ai_text[len(atxt):]
            if should_emit_stream_delta(atxt, suffix):
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


def text_from_message_parts(parts: List[Dict[str, Any]]) -> str:
    return "".join(
        str(part.get("content") or "")
        for part in parts
        if part.get("type") == "text"
    ).strip()


async def persist_assistant_message(
    user_id: str,
    conversation_id: str,
    model: str,
    content: str,
    parts: List[Dict[str, Any]],
    reasoning_content: str = "",
) -> tuple[Dict[str, Any], Dict[str, Any], bool]:
    normalized_parts = [dict(part) for part in parts]
    normalized_content = content.strip() or text_from_message_parts(normalized_parts)
    normalized_reasoning_content = reasoning_content.strip() or None
    if not normalized_content and not normalized_parts:
        normalized_content = "已停止响应。"
        normalized_parts = [{"type": "text", "content": normalized_content}]

    amsg = {
        "id": str(uuid4()), "role": "assistant", "content": normalized_content,
        "timestamp": now_iso(),
        "parts": normalized_parts,
        "reasoning_content": normalized_reasoning_content,
        "feedback": None,
    }
    c2 = chat_store.append_message(user_id, conversation_id, amsg, model=model)
    if c2 is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    title_pending = c2["title"] == "新对话"
    if title_pending:
        schedule_conversation_title_update(user_id, conversation_id, c2["messages"])
    return amsg, make_conversation_summary(c2), title_pending


def refresh_edu_session_status(token: str) -> Dict[str, Any] | None:
    session = get_session(token)
    if not session:
        return None
    if session.get("student_type") != "undergraduate":
        return session
    if not session.get("edu_authenticated"):
        return session

    expires_at = float(session.get("edu_session_expires_at") or 0)
    if expires_at and expires_at <= time.time():
        logger.info("Edu session timed out for %s", mask_user_id(session.get("user_id", "")))
        clear_edu_session(token, "教务连接已超时，请在侧栏重新连接教务。")
        return get_session(token)

    cookies = session.get("edu_cookies") or []
    if not cookies:
        clear_edu_session(token, "教务登录已过期，请在侧栏重新连接教务。")
        return get_session(token)

    try:
        client = JwchClient.from_cookies(
            session.get("user_id", ""),
            cookies,
            session.get("edu_identifier", ""),
        )
        client.validate_session()
        if not expires_at:
            update_session(token, {"edu_session_expires_at": int(time.time()) + EDU_SESSION_TTL})
            session = get_session(token) or session
        if session.get("edu_status_message"):
            update_session(token, {"edu_status_message": ""})
            return get_session(token)
        return session
    except JwchSessionError:
        logger.info("Edu session expired for %s", mask_user_id(session.get("user_id", "")))
        clear_edu_session(token, "教务登录已过期，请在侧栏重新连接教务。")
        return get_session(token)
    except Exception as exc:
        logger.warning("Edu session validation failed: %s", type(exc).__name__)
        return session


def _build_edu_session_state(client: JwchClient) -> Dict[str, Any]:
    return {
        "edu_authenticated": True,
        "edu_cookies": [{"name": c.name, "value": c.value} for c in client.session.cookies],
        "edu_identifier": client.identifier,
        "edu_status_message": "",
        "edu_session_expires_at": int(time.time()) + EDU_SESSION_TTL,
    }


def _edu_context_from_session(user_id: str, session: Dict[str, Any] | None) -> Dict[str, Any]:
    session = session or {}
    return {
        "user_id": user_id,
        "student_type": session.get("student_type", ""),
        "auth_provider": session.get("auth_provider", ""),
        "edu_authenticated": session.get("edu_authenticated", False),
        "edu_cookies": session.get("edu_cookies"),
        "edu_identifier": session.get("edu_identifier", ""),
        "edu_status_message": session.get("edu_status_message", ""),
    }


def schedule_signal_snapshot_refresh(user_id: str, edu_ctx: Dict[str, Any] | None) -> None:
    if not user_id or not edu_ctx or not edu_ctx.get("edu_authenticated"):
        return
    if not acquire_dedupe_lock(f"signal-refresh:{user_id}", 120):
        return

    def runner() -> None:
        refresh_signal_snapshots(user_id, edu_ctx)

    Thread(target=runner, name=f"campus-signal-refresh-{mask_user_id(user_id)}", daemon=True).start()


def clear_edu_session(token: str, status_message: str = "") -> None:
    update_session(
        token,
        {
            "edu_authenticated": False,
            "edu_cookies": None,
            "edu_identifier": "",
            "edu_status_message": status_message,
            "edu_session_expires_at": None,
        },
    )


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


@app.get("/api/ready")
def readiness() -> JSONResponse:
    redis_status = redis_health()
    sqlite_status: Dict[str, Any]
    try:
        sqlite_status = chat_store.healthcheck()
    except Exception as exc:
        increment_counter("fzu_chat_sqlite_errors_total")
        logger.warning("SQLite readiness check failed: %s", type(exc).__name__)
        sqlite_status = {"ok": False, "detail": type(exc).__name__}
    ok = bool(redis_status.get("ok")) and bool(sqlite_status.get("ok"))
    payload = {
        "status": "ready" if ok else "degraded",
        "redis": redis_status,
        "sqlite": sqlite_status,
        "limits": {
            "global_stream": GLOBAL_STREAM_LIMIT,
            "user_stream": USER_STREAM_LIMIT,
            "edu_login_concurrency": EDU_LOGIN_CONCURRENCY_LIMIT,
        },
    }
    return JSONResponse(payload, status_code=200 if ok else 503)


@app.get("/api/metrics")
def metrics(request: Request) -> PlainTextResponse:
    if not METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    if not _metrics_allowed(request):
        raise HTTPException(status_code=403, detail="Metrics endpoint is restricted")
    with active_stream_stops_lock:
        set_gauge("fzu_chat_active_streams", float(len(active_stream_stops)))
    return PlainTextResponse(render_prometheus_metrics(), media_type="text/plain; version=0.0.4")


def _oauth_redirect_base(request: Request) -> str:
    return f"{_request_origin(request).rstrip('/')}/api/auth/oauth"


@app.get("/api/auth/oauth/providers", response_model=List[OAuthProviderStatus])
def oauth_providers(request: Request):
    return list_provider_status(_oauth_redirect_base(request))


@app.get("/api/auth/oauth/{provider}/start")
def oauth_start(provider: Literal["wechat", "qq"], request: Request, accepted_legal: bool = False):
    _enforce_rate_limit(
        _rate_limit_key("oauth-start", request, provider),
        LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        "登录尝试过于频繁，请稍后再试。",
    )
    if not accepted_legal:
        raise HTTPException(status_code=400, detail="请先阅读并同意用户协议与隐私政策。")

    redirect_uri = f"{_oauth_redirect_base(request)}/{provider}/callback"
    try:
        config = get_provider_config(provider, redirect_uri)
        state = create_oauth_state(provider, redirect_uri)
        return RedirectResponse(build_authorization_url(config, state), status_code=302)
    except OAuthConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/auth/oauth/{provider}/callback")
def oauth_callback(
    provider: Literal["wechat", "qq"],
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    if error:
        logger.warning("OAuth callback rejected by %s: %s", provider, error)
        raise HTTPException(status_code=400, detail=error_description or "第三方登录已取消或失败。")
    try:
        state_payload = consume_oauth_state(state or "", provider)
        config = get_provider_config(provider, str(state_payload.get("redirect_uri") or ""))
        profile = fetch_visitor_profile(config, code or "")
    except OAuthConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.warning("OAuth provider request failed for %s: %s", provider, type(exc).__name__)
        raise HTTPException(status_code=503, detail=f"{provider_display_name(provider)}登录服务暂不可用，请稍后再试。") from exc

    existing_token = request.cookies.get(AUTH_COOKIE_NAME)
    if existing_token:
        invalidate_session(existing_token)

    token = create_session(
        user_id=profile["user_id"],
        student_type="visitor",
        display_name=profile["display_name"],
        edu_authenticated=False,
        edu_cookies=None,
    )
    update_session(
        token,
        {
            "auth_provider": provider,
            "provider_subject_hash": profile["provider_subject_hash"],
            "avatar_url": profile.get("avatar_url", ""),
            "edu_status_message": "",
            "edu_session_expires_at": None,
        },
    )
    response = RedirectResponse("/", status_code=302)
    _set_auth_cookie(response, token, request)
    return response


@app.post("/api/auth/login")
def login(req: LoginRequest, request: Request) -> JSONResponse:
    _enforce_rate_limit(
        _rate_limit_key("auth-login", request, req.student_id),
        LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        "登录尝试过于频繁，请稍后再试。",
    )

    if not req.accepted_legal:
        raise HTTPException(status_code=400, detail="请先阅读并同意用户协议与隐私政策。")

    if req.student_type != "undergraduate":
        raise HTTPException(status_code=403, detail="当前仅支持本科生通过教务系统登录，研究生登录暂未开放。")

    login_slot = acquire_slot("edu-login", EDU_LOGIN_CONCURRENCY_LIMIT, ttl_seconds=60)
    if login_slot is None:
        raise HTTPException(status_code=429, detail="教务登录请求较多，请稍后再试。")
    try:
        try:
            client = JwchClient(req.student_id, req.password)
            client.login()
        except JwchLoginError as exc:
            logger.warning("Edu login rejected for %s: %s", mask_user_id(req.student_id), type(exc).__name__)
            raise HTTPException(status_code=401, detail="教务系统登录失败，请检查学号和密码。") from exc
        except Exception as exc:
            logger.warning("Edu login unavailable for %s: %s", mask_user_id(req.student_id), type(exc).__name__)
            raise HTTPException(status_code=503, detail="教务系统连接失败，请稍后重试。") from exc
    finally:
        release_slot(login_slot)

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
    update_session(token, _build_edu_session_state(client))
    warm_teaching_week_cache_async()
    schedule_signal_snapshot_refresh(req.student_id, _edu_context_from_session(req.student_id, get_session(token)))

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


@app.post("/api/auth/edu-login")
def relogin_edu(req: EduReloginRequest, request: Request, user: AuthUser = Depends(require_auth)) -> JSONResponse:
    _enforce_rate_limit(
        _rate_limit_key("edu-relogin", request, user.user_id),
        EDU_RELOGIN_RATE_LIMIT_MAX_ATTEMPTS,
        EDU_RELOGIN_RATE_LIMIT_WINDOW_SECONDS,
        "教务重新连接尝试过于频繁，请稍后再试。",
    )

    if user.student_type != "undergraduate":
        raise HTTPException(status_code=403, detail="当前账号不支持重新连接教务。")

    relogin_slot = acquire_slot("edu-login", EDU_LOGIN_CONCURRENCY_LIMIT, ttl_seconds=60)
    if relogin_slot is None:
        raise HTTPException(status_code=429, detail="教务登录请求较多，请稍后再试。")
    try:
        try:
            client = JwchClient(user.user_id, req.password)
            client.login()
        except JwchLoginError as exc:
            logger.warning("Edu relogin rejected for %s: %s", mask_user_id(user.user_id), type(exc).__name__)
            raise HTTPException(status_code=400, detail="教务系统重新连接失败，请检查密码后重试。") from exc
        except Exception as exc:
            logger.warning("Edu relogin unavailable for %s: %s", mask_user_id(user.user_id), type(exc).__name__)
            raise HTTPException(status_code=503, detail="教务系统连接失败，请稍后重试。") from exc
    finally:
        release_slot(relogin_slot)

    update_session(user.token, _build_edu_session_state(client))
    warm_teaching_week_cache_async()

    session = get_session(user.token) or {}
    schedule_signal_snapshot_refresh(user.user_id, _edu_context_from_session(user.user_id, session))
    return JSONResponse(
        {
            "user": {
                "user_id": session.get("user_id", user.user_id),
                "student_type": session.get("student_type", user.student_type),
                "display_name": session.get("display_name", user.display_name),
                "edu_authenticated": True,
            },
            "edu_error": "",
        }
    )


@app.post("/api/auth/logout")
def logout(
    request: Request,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
) -> JSONResponse:
    token = _extract_auth_token(authorization, session_cookie)
    if token:
        clear_edu_session(token)
        invalidate_session(token)
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
        "auth_provider": session.get("auth_provider", ""),
        "avatar_url": session.get("avatar_url", ""),
        "edu_authenticated": session.get("edu_authenticated", user.edu_authenticated),
        "edu_error": session.get("edu_status_message", ""),
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@app.get("/api/models")
def list_models() -> List[Dict[str, str]]:
    return [{"id": mid, "label": lbl} for mid, lbl in MODEL_OPTIONS.items()]


@app.get("/api/user-data", response_model=UserDataSummary)
def get_user_data_summary(user: AuthUser = Depends(require_auth)):
    summary = chat_store.get_user_data_summary(user.user_id)
    return {
        **summary,
        "memory_count": user_memory_store.count_active_memories(user.user_id),
    }


@app.delete("/api/user-data", response_model=UserDataResetResponse)
def reset_user_data(user: AuthUser = Depends(require_auth)):
    cleared_conversations = chat_store.delete_all_conversations(user.user_id)
    cleared_memories = user_memory_store.purge_all_memories(user.user_id)
    cleared_dynamic_context = purge_dynamic_context_user_data(user.user_id)
    return {
        "ok": True,
        "cleared": {
            **cleared_conversations,
            "memory_count": cleared_memories,
            **cleared_dynamic_context,
        },
    }


# ---------------------------------------------------------------------------
# Contextual campus recommendations
# ---------------------------------------------------------------------------

@app.get("/api/recommendations/locations")
def list_recommendation_locations(user: AuthUser = Depends(require_auth)) -> Dict[str, Any]:
    return {"locations": manual_location_options()}


@app.post("/api/recommendations/signal-refresh")
def refresh_recommendation_signals(user: AuthUser = Depends(require_auth)) -> Dict[str, Any]:
    session = refresh_edu_session_status(user.token) or get_session(user.token) or {}
    edu_ctx = _edu_context_from_session(user.user_id, session)
    schedule_signal_snapshot_refresh(user.user_id, edu_ctx)
    return {"ok": True, "scheduled": bool(edu_ctx.get("edu_authenticated"))}


@app.post("/api/recommendations/location-context")
def warm_recommendation_location_context(
    req: LocationContextWarmupRequest,
    user: AuthUser = Depends(require_auth),
) -> Dict[str, Any]:
    location = req.location.dict()
    cached_text = get_cached_browser_location_text(location)
    scheduled = schedule_browser_location_text_refresh(location)
    return {"ok": True, "cached": bool(cached_text), "scheduled": scheduled}


@app.post("/api/recommendations/contextual")
def contextual_recommendation(
    req: ContextualRecommendationRequest,
    user: AuthUser = Depends(require_auth),
) -> Dict[str, Any]:
    session = refresh_edu_session_status(user.token) or get_session(user.token) or {}
    edu_ctx = _edu_context_from_session(user.user_id, session)
    location = req.location.dict() if req.location else None
    return build_contextual_recommendation(
        scenario=req.scenario,
        location=location,
        manual_location_id=(req.manual_location_id or "").strip(),
        travel_mode=req.travel_mode,
        seen_grade_digest=(req.seen_grade_digest or "").strip(),
        edu_session=edu_ctx,
    )


# ---------------------------------------------------------------------------
# Conversations (auth-protected, per-user)
# ---------------------------------------------------------------------------


@app.get("/api/conversations", response_model=ConversationListResponse)
def list_conversations(
    limit: int = 50,
    cursor: str | None = None,
    user: AuthUser = Depends(require_auth),
):
    return chat_store.list_conversations_page(user.user_id, limit=limit, cursor=cursor)


@app.get("/api/conversations/events")
async def stream_conversation_events(request: Request, user: AuthUser = Depends(require_auth)):
    queue = register_conversation_event_subscriber(user.user_id)

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield b": keep-alive\n\n"
                    continue
                yield serialize_event(payload["event"], payload["data"])
        finally:
            unregister_conversation_event_subscriber(user.user_id, queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/conversations", response_model=ConversationRecord)
def create_conversation(req: ConversationCreateRequest, request: Request, user: AuthUser = Depends(require_auth)):
    _enforce_rate_limit(
        _rate_limit_key("conversation-create", request, user.user_id),
        CONVERSATION_CREATE_RATE_LIMIT_MAX_ATTEMPTS,
        CONVERSATION_CREATE_RATE_LIMIT_WINDOW_SECONDS,
        "创建对话过于频繁，请稍后再试。",
    )

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
    next_title: str | None = None
    if req.title is not None:
        next_title = req.title.strip()
        if not next_title:
            raise HTTPException(status_code=400, detail="对话标题不能为空。")
        if len(next_title) > MAX_TITLE_LENGTH:
            raise HTTPException(status_code=400, detail=f"对话标题最多 {MAX_TITLE_LENGTH} 个字符。")

    next_model: str | None = None
    if req.model is not None:
        if req.model not in MODEL_OPTIONS:
            raise HTTPException(status_code=400, detail="所选模型不可用，请刷新页面后重试。")
        next_model = req.model

    conversation = chat_store.update_conversation(
        user.user_id,
        cid,
        title=next_title,
        model=next_model,
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
                importance=data.get("importance") or 50,
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

    _enforce_rate_limit(
        _rate_limit_key("conversation-message", request, user.user_id),
        MESSAGE_RATE_LIMIT_MAX_ATTEMPTS,
        MESSAGE_RATE_LIMIT_WINDOW_SECONDS,
        "发送消息过于频繁，请稍后再试。",
    )

    sel = normalize_model_id(req.model if req.model is not None else conv.get("model"))
    rerun_message_id = (req.rerun_message_id or "").strip()
    if rerun_message_id:
        target_message = next((msg for msg in conv.get("messages", []) if msg.get("id") == rerun_message_id), None)
        if target_message is None:
            raise HTTPException(status_code=404, detail="未找到要重新生成的消息")
        if target_message.get("role") != "user":
            raise HTTPException(status_code=400, detail="只能基于已发送的问题重新生成回复")
        timestamp = now_iso()
        original_content = str(target_message.get("content") or "").strip()
        conv = chat_store.truncate_after_user_message(
            user.user_id,
            cid,
            rerun_message_id,
            content=content if content != original_content else None,
            model=sel,
            updated_at=timestamp,
        )
        if conv is None:
            raise HTTPException(status_code=404, detail="未找到要重新生成的消息")
        umsg = next((msg for msg in conv.get("messages", []) if msg.get("id") == rerun_message_id), None)
        if umsg is None:
            raise HTTPException(status_code=404, detail="未找到要重新生成的消息")
    else:
        umsg = {
            "id": str(uuid4()), "role": "user", "content": content,
            "timestamp": now_iso(), "parts": [{"type": "text", "content": content}],
            "feedback": None,
        }
        conv = chat_store.append_message(user.user_id, cid, umsg, model=sel)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    graph_messages = build_graph_input_messages(conv["messages"], sel)

    sess = refresh_edu_session_status(user.token) or get_session(user.token)
    edu_ctx = _edu_context_from_session(user.user_id, sess)
    user_turn_count = sum(1 for message in conv.get("messages", []) if message.get("role") == "user")
    message_location = req.context.location.dict() if req.context and req.context.location else None
    if message_location:
        edu_ctx["message_location"] = message_location
        message_location_text = get_cached_browser_location_text(message_location)
        if message_location_text:
            edu_ctx["message_location_text"] = message_location_text
            edu_ctx["message_location_context"] = build_transient_location_system_context(message_location_text)
        schedule_browser_location_text_refresh(message_location)
    if req.context:
        edu_ctx["travel_mode"] = req.context.travel_mode
    runtime_system_context = str(conv.get("runtime_context") or "").strip()
    if not runtime_system_context:
        warm_teaching_week_cache_async()
        dynamic_campus_context = build_dynamic_campus_context(
            user.user_id,
            message_content=content,
            is_first_user_turn=user_turn_count <= 1,
            location=message_location,
        )
        runtime_system_context = build_runtime_system_context(user.user_id, dynamic_campus_context)
        conv_with_runtime = chat_store.set_runtime_context(user.user_id, cid, runtime_system_context)
        if conv_with_runtime is not None:
            conv = conv_with_runtime
    if runtime_system_context:
        edu_ctx["runtime_system_context"] = runtime_system_context
    if user_turn_count <= 1 or is_dynamic_context_request(content):
        schedule_signal_snapshot_refresh(user.user_id, edu_ctx)
    runtime_graph = build_graph(edu_ctx, use_checkpointer=False)
    stop_event = register_active_stream_stop(user.user_id, cid)
    graph_config = {
        "configurable": {
            "model": sel,
            "thread_id": conv["thread_id"],
            "thinking_enabled": req.thinking_enabled,
        }
    }
    stream_slot = acquire_pair_slot(
        "chat-stream",
        "chat-stream:global",
        GLOBAL_STREAM_LIMIT,
        f"chat-stream:user:{user.user_id}",
        USER_STREAM_LIMIT,
        ttl_seconds=STREAM_SLOT_TTL_SECONDS,
    )
    if stream_slot is None:
        clear_active_stream_stop(user.user_id, cid, stop_event)
        raise HTTPException(status_code=429, detail="当前生成请求较多，请稍后再试。")

    async def event_stream() -> AsyncIterator[bytes]:
        set_current_edu_session(edu_ctx)
        reset_search_citation_counter()
        atxt = ""
        final_ai_text = ""
        final_reasoning_text = ""
        pending: Dict[str, Dict[str, Any]] = {}
        parts: List[Dict[str, Any]] = []
        final_payload: Dict[str, Any] | None = None
        stream_stopped = False
        client_disconnected = False

        async def build_done_payload(stopped: bool) -> Dict[str, Any]:
            nonlocal atxt, final_payload
            if final_payload is not None:
                return final_payload
            atxt = finalize_stream_text(atxt, final_ai_text, parts)
            if stopped:
                mark_running_tool_parts_stopped(parts)
            amsg, summary, title_pending = await persist_assistant_message(
                user.user_id,
                cid,
                sel,
                atxt,
                parts,
                reasoning_content=final_reasoning_text,
            )
            final_payload = {
                "message": amsg,
                "conversation": summary,
                "stopped": stopped,
                "title_pending": title_pending,
            }
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
                    if should_emit_stream_delta(atxt, delta):
                        atxt += delta
                        append_text_part(parts, delta)
                        yield serialize_event("chunk", {"delta": delta})
                    reasoning_delta = unseen_text(final_reasoning_text, extract_reasoning_content(mc))
                    if reasoning_delta:
                        final_reasoning_text += reasoning_delta
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
                            summary_args = a
                            if tn == "recommend_campus_context" and isinstance(a, dict) and not a.get("travel_mode"):
                                summary_args = {**a, "travel_mode": edu_ctx.get("travel_mode") or "walking"}
                            q = summarize_tool_args(summary_args)
                            lb = TOOL_LABELS.get(tn, {"running": f"正在调用 {tn}", "complete": f"{tn} 完成"})
                            tp = {
                                "type": "tool", "tool_id": ti, "tool_name": tn,
                                "query": q, "status": "running", "status_label": lb["running"],
                                "args": _jsonable_for_storage(a),
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
                        tp["raw_content"] = rc
                        tp["urls"] = extract_urls(rc, af)
                        tp["data"] = extract_structured_data(tn, af, rc)
                        yield serialize_event("tool_result", tp)
                        continue

                    if not mc_type.startswith("AIMessage"):
                        continue

                    candidate = extract_text_content(getattr(mc, "content", ""))
                    if len(candidate) > len(final_ai_text):
                        final_ai_text = candidate
                    candidate_reasoning = extract_reasoning_content(mc)
                    reasoning_delta = unseen_text(final_reasoning_text, candidate_reasoning)
                    if reasoning_delta:
                        final_reasoning_text += reasoning_delta

                if stop_event.is_set():
                    stream_stopped = True
                    break
                if await request.is_disconnected():
                    stream_stopped = True
                    client_disconnected = True
                    break

            payload = await build_done_payload(stream_stopped)
            if not client_disconnected:
                yield serialize_event("done", payload)
        except asyncio.CancelledError:
            logger.info("Stream cancelled for %s", cid)
            await build_done_payload(True)
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
            release_slot(stream_slot)
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
    normalized = full_path.strip("/")
    if index.exists() and (normalized in {"", "index.html"} or STATIC_FALLBACK_MODE != "strict"):
        return FileResponse(index)
    if index.exists():
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return JSONResponse(
        {"message": "Frontend build not found. Run `npm run build` in /frontend or use the Vite dev server."},
        status_code=503,
    )
