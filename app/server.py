from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import (
    create_session,
    get_session,
    invalidate_session,
    update_session,
    user_store_path,
)
from .edu_tools import set_current_edu_session
from .graph import graph, summary_chain
from .jwch_client import JwchClient, JwchLoginError

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
ASSETS_DIR = BASE_DIR / "png"
MAX_TITLE_LENGTH = int(os.getenv("FZU_CHAT_MAX_TITLE_LENGTH", "20"))

MODEL_OPTIONS = {
    "qwen-max-latest": "通义千问 Max",
    "deepseek-chat": "DeepSeek V3",
    "ERNIE-4.5-Turbo-32K": "文心一言 4.5 Turbo",
    "Moonshot-Kimi-K2-Instruct": "Kimi K2",
}

TOOL_LABELS: Dict[str, Dict[str, str]] = {
    "retrieve": {"running": "正在查询知识库", "complete": "知识库查询完成"},
    "bocha_websearch_tool": {"running": "正在搜索网络", "complete": "网络搜索完成"},
    "query_grades": {"running": "正在查询成绩", "complete": "成绩查询完成"},
    "query_courses": {"running": "正在查询课表", "complete": "课表查询完成"},
    "query_student_info": {"running": "正在查询学生信息", "complete": "学生信息查询完成"},
    "query_exam_scores": {"running": "正在查询考试成绩", "complete": "考试成绩查询完成"},
}

store_locks: Dict[str, Lock] = {}
_global_lock = Lock()
logger = logging.getLogger(__name__)


def _get_user_lock(user_id: str) -> Lock:
    with _global_lock:
        if user_id not in store_locks:
            store_locks[user_id] = Lock()
        return store_locks[user_id]


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


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

class AuthUser(BaseModel):
    user_id: str
    student_type: str
    display_name: str
    edu_authenticated: bool
    token: str


def require_auth(authorization: str | None = Header(default=None)) -> AuthUser:
    token: str | None = None
    if authorization:
        token = authorization[7:] if authorization.startswith("Bearer ") else authorization
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
    model: str = "qwen-max-latest"


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=40)
    model: str | None = None


class MessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    model: str | None = None


class FeedbackUpdateRequest(BaseModel):
    message_id: str
    feedback: Literal["up", "down"]


class MessageRecord(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    timestamp: str
    parts: List[Dict[str, Any]] = Field(default_factory=list)
    feedback: Literal["up", "down"] | None = None


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


def _ensure_store(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"conversations": {}}, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_store(path: Path) -> Dict[str, Any]:
    _ensure_store(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _save_store(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        tmp.replace(path)
    except OSError as exc:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError("Failed to persist conversation store") from exc


def make_conversation_summary(rec: Dict[str, Any]) -> Dict[str, Any]:
    preview = ""
    for msg in reversed(rec.get("messages", [])):
        preview = (msg.get("content") or "").strip()
        if preview:
            break
    return {
        "id": rec["id"], "title": rec["title"], "model": rec["model"],
        "created_at": rec["created_at"], "updated_at": rec["updated_at"],
        "preview": preview[:80], "message_count": len(rec.get("messages", [])),
    }


def sorted_summaries(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sorted(
        (make_conversation_summary(c) for c in store.get("conversations", {}).values()),
        key=lambda x: x["updated_at"], reverse=True,
    )


def get_conversation_or_404(store: Dict[str, Any], cid: str) -> Dict[str, Any]:
    c = store.get("conversations", {}).get(cid)
    if not c:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return c


def create_conversation_record(model: str) -> Dict[str, Any]:
    ts = now_iso()
    return {
        "id": str(uuid4()), "title": "新对话",
        "model": model if model in MODEL_OPTIONS else "qwen-max-latest",
        "thread_id": str(uuid4()), "created_at": ts, "updated_at": ts, "messages": [],
    }


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


def extract_structured_data(tool_name: str, artifact: Any) -> Any:
    if tool_name in ("query_grades", "query_courses", "query_student_info", "query_exam_scores"):
        if isinstance(artifact, (list, dict)):
            return artifact
    return None


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


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(req: LoginRequest) -> Dict[str, Any]:
    edu_authenticated = False
    edu_cookies: Any = None
    edu_identifier = ""
    edu_error = ""

    if req.student_type == "undergraduate":
        try:
            client = JwchClient(req.student_id, req.password)
            client.login()
            edu_authenticated = True
            edu_cookies = [{"name": c.name, "value": c.value} for c in client.session.cookies]
            edu_identifier = client.identifier
        except JwchLoginError as exc:
            logger.warning("Edu login error: %s", exc)
            edu_error = "教务系统登录失败，请检查学号和密码"
        except Exception as exc:
            logger.warning("Edu login error: %s", exc)
            edu_error = "教务系统连接失败，已创建本地会话"

    token = create_session(
        user_id=req.student_id, student_type=req.student_type,
        display_name=req.student_id, edu_authenticated=edu_authenticated,
        edu_cookies=edu_cookies,
    )
    if edu_identifier:
        update_session(token, {"edu_identifier": edu_identifier})

    return {
        "token": token,
        "user": {
            "user_id": req.student_id, "student_type": req.student_type,
            "display_name": req.student_id, "edu_authenticated": edu_authenticated,
        },
        "edu_error": edu_error,
    }


@app.post("/api/auth/logout")
def logout(user: AuthUser = Depends(require_auth)) -> Dict[str, bool]:
    invalidate_session(user.token)
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(user: AuthUser = Depends(require_auth)) -> Dict[str, Any]:
    return {
        "user_id": user.user_id, "student_type": user.student_type,
        "display_name": user.display_name, "edu_authenticated": user.edu_authenticated,
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

def _user_store(user: AuthUser):
    return user_store_path(user.user_id), _get_user_lock(user.user_id)


@app.get("/api/conversations", response_model=List[ConversationSummary])
def list_conversations(user: AuthUser = Depends(require_auth)):
    p, lk = _user_store(user)
    with lk:
        return sorted_summaries(_load_store(p))


@app.post("/api/conversations", response_model=ConversationRecord)
def create_conversation(req: ConversationCreateRequest, user: AuthUser = Depends(require_auth)):
    p, lk = _user_store(user)
    with lk:
        s = _load_store(p)
        c = create_conversation_record(req.model)
        s["conversations"][c["id"]] = c
        _save_store(p, s)
        return c


@app.get("/api/conversations/{cid}", response_model=ConversationRecord)
def get_conversation(cid: str, user: AuthUser = Depends(require_auth)):
    p, lk = _user_store(user)
    with lk:
        return get_conversation_or_404(_load_store(p), cid)


@app.patch("/api/conversations/{cid}", response_model=ConversationRecord)
def update_conversation(cid: str, req: ConversationUpdateRequest, user: AuthUser = Depends(require_auth)):
    p, lk = _user_store(user)
    with lk:
        s = _load_store(p)
        c = get_conversation_or_404(s, cid)
        if req.title is not None:
            c["title"] = req.title.strip() or c["title"]
        if req.model is not None and req.model in MODEL_OPTIONS:
            c["model"] = req.model
        c["updated_at"] = now_iso()
        _save_store(p, s)
        return c


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str, user: AuthUser = Depends(require_auth)):
    p, lk = _user_store(user)
    with lk:
        s = _load_store(p)
        if cid not in s.get("conversations", {}):
            raise HTTPException(status_code=404, detail="Conversation not found")
        del s["conversations"][cid]
        _save_store(p, s)
    return {"ok": True}


@app.post("/api/conversations/{cid}/feedback")
def update_feedback(cid: str, req: FeedbackUpdateRequest, user: AuthUser = Depends(require_auth)):
    p, lk = _user_store(user)
    with lk:
        s = _load_store(p)
        c = get_conversation_or_404(s, cid)
        for msg in c["messages"]:
            if msg["id"] == req.message_id:
                msg["feedback"] = req.feedback
                c["updated_at"] = now_iso()
                _save_store(p, s)
                return {"ok": True}
    raise HTTPException(status_code=404, detail="Message not found")


# ---------------------------------------------------------------------------
# Message streaming
# ---------------------------------------------------------------------------

@app.post("/api/conversations/{cid}/messages")
def create_message(cid: str, req: MessageCreateRequest, user: AuthUser = Depends(require_auth)):
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty")

    p, lk = _user_store(user)
    with lk:
        s = _load_store(p)
        conv = get_conversation_or_404(s, cid)
        sel = req.model if req.model in MODEL_OPTIONS else conv["model"]
        conv["model"] = sel
        umsg = {
            "id": str(uuid4()), "role": "user", "content": content,
            "timestamp": now_iso(), "parts": [{"type": "text", "content": content}],
            "feedback": None,
        }
        conv["messages"].append(umsg)
        conv["updated_at"] = now_iso()
        tid = conv["thread_id"]
        _save_store(p, s)

    sess = get_session(user.token)
    edu_ctx = {
        "user_id": user.user_id,
        "edu_authenticated": sess.get("edu_authenticated", False) if sess else False,
        "edu_cookies": sess.get("edu_cookies") if sess else None,
        "edu_identifier": sess.get("edu_identifier", "") if sess else "",
    }

    def event_stream() -> Iterable[bytes]:
        set_current_edu_session(edu_ctx)
        atxt = ""
        pending: Dict[str, Dict[str, Any]] = {}
        tparts: List[Dict[str, Any]] = []
        try:
            yield serialize_event("user", umsg)
            for step in graph.stream(
                {"messages": [{"role": "user", "content": content}]},
                stream_mode="messages",
                config={"configurable": {"thread_id": tid, "model": sel}},
            ):
                mc, _ = step
                if hasattr(mc, "tool_calls") and mc.tool_calls:
                    mc = combine_tool_calls(mc)
                    for tc in mc.tool_calls:
                        if not isinstance(tc, dict):
                            continue
                        tn = tc.get("name", "")
                        ti = clean_tool_call_id(tc.get("id", ""))
                        a = tc.get("args") or {}
                        q = a.get("query", "") if isinstance(a, dict) else str(a)
                        lb = TOOL_LABELS.get(tn, {"running": f"正在调用 {tn}", "complete": f"{tn} 完成"})
                        tp = {
                            "type": "tool", "tool_id": ti, "tool_name": tn,
                            "query": q, "status": "running", "status_label": lb["running"],
                            "urls": [], "data": None,
                        }
                        pending[ti] = tp
                        tparts.append(tp)
                        yield serialize_event("tool_call", tp)
                elif type(mc).__name__ == "ToolMessage":
                    ci = clean_tool_call_id(getattr(mc, "tool_call_id", ""))
                    mi = matching_tool_call_id(pending.keys(), ci)
                    if not mi:
                        continue
                    tp = pending[mi]
                    tn = tp["tool_name"]
                    lb = TOOL_LABELS.get(tn, {"running": "", "complete": f"{tn} 完成"})
                    tp["status"] = "complete"
                    tp["status_label"] = lb["complete"]
                    rc = getattr(mc, "content", "")
                    af = getattr(mc, "artifact", None)
                    tp["urls"] = extract_urls(rc, af)
                    tp["data"] = extract_structured_data(tn, af)
                    yield serialize_event("tool_result", tp)
                elif getattr(mc, "content", None):
                    d = mc.content
                    atxt += d
                    yield serialize_event("chunk", {"delta": d})

            amsg = {
                "id": str(uuid4()), "role": "assistant", "content": atxt.strip(),
                "timestamp": now_iso(),
                "parts": ([{"type": "text", "content": atxt.strip()}] if atxt.strip() else []) + tparts,
                "feedback": None,
            }
            with lk:
                s2 = _load_store(p)
                c2 = get_conversation_or_404(s2, cid)
                c2["messages"].append(amsg)
                if c2["title"] == "新对话":
                    c2["title"] = summarize_title(c2["messages"])
                c2["model"] = sel
                c2["updated_at"] = now_iso()
                _save_store(p, s2)
                sm = make_conversation_summary(c2)
            yield serialize_event("done", {"message": amsg, "conversation": sm})
        except Exception:
            logger.exception("Stream failed for %s", cid)
            yield serialize_event("error", {"message": "生成回复失败，请稍后重试。"})
        finally:
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
