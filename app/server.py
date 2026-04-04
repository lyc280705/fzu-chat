from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .graph import graph, summary_chain

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
ASSETS_DIR = BASE_DIR / "png"
STORAGE_DIR = BASE_DIR / "storage"
STORAGE_DIR.mkdir(exist_ok=True)
STORE_PATH = Path(os.getenv("FZU_CHAT_STORAGE_PATH", STORAGE_DIR / "conversations.json"))

MODEL_OPTIONS = {
    "qwen-max-latest": "通义千问 Max",
    "deepseek-chat": "DeepSeek V3",
    "ERNIE-4.5-Turbo-32K": "文心一言 4.5 Turbo",
    "Moonshot-Kimi-K2-Instruct": "Kimi K2",
}

store_lock = Lock()
app = FastAPI(title="FZU Chat API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_store() -> None:
    if STORE_PATH.exists():
        return
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps({"conversations": {}}, ensure_ascii=False, indent=2), encoding="utf-8")


@app.on_event("startup")
def startup() -> None:
    ensure_store()


@app.get("/api/health")
def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


def load_store() -> Dict[str, Any]:
    ensure_store()
    return json.loads(STORE_PATH.read_text(encoding="utf-8"))



def save_store(payload: Dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STORE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(STORE_PATH)



def make_conversation_summary(record: Dict[str, Any]) -> Dict[str, Any]:
    preview = ""
    for message in reversed(record.get("messages", [])):
        preview = (message.get("content") or "").strip()
        if preview:
            break
    return {
        "id": record["id"],
        "title": record["title"],
        "model": record["model"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "preview": preview[:80],
        "message_count": len(record.get("messages", [])),
    }



def sorted_summaries(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    conversations = store.get("conversations", {}).values()
    return sorted(
        (make_conversation_summary(conversation) for conversation in conversations),
        key=lambda item: item["updated_at"],
        reverse=True,
    )



def get_conversation_or_404(store: Dict[str, Any], conversation_id: str) -> Dict[str, Any]:
    conversation = store.get("conversations", {}).get(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation



def create_conversation_record(model: str) -> Dict[str, Any]:
    timestamp = now_iso()
    return {
        "id": str(uuid4()),
        "title": "新对话",
        "model": model if model in MODEL_OPTIONS else "qwen-max-latest",
        "thread_id": str(uuid4()),
        "created_at": timestamp,
        "updated_at": timestamp,
        "messages": [],
    }



def serialize_event(event: str, data: Dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")



def extract_urls_from_tool_message(content: str) -> List[str]:
    urls: List[str] = []
    for line in content.splitlines():
        if line.startswith("Article url:"):
            url = line.replace("Article url:", "").strip()
            if url and url not in urls:
                urls.append(url)
        if line.startswith("URL:"):
            url = line.replace("URL:", "").strip()
            if url and url not in urls:
                urls.append(url)
    return urls



def combine_tool_calls(message_chunk: Any) -> Any:
    if not hasattr(message_chunk, "tool_calls") or not message_chunk.tool_calls:
        return message_chunk
    for tool_call in message_chunk.tool_calls:
        if not isinstance(tool_call, dict):
            continue
        args = tool_call.get("args")
        if isinstance(args, dict):
            continue
        if isinstance(args, str) and args.startswith('{"query":"'):
            tool_call["args"] = {"query": args.replace('{"query":"', "").rstrip('"}')}
    return message_chunk



def clean_tool_call_id(tool_call_id: str | None) -> str:
    if not tool_call_id:
        return ""
    return tool_call_id[:22] if tool_call_id.startswith("call_") else tool_call_id



def matching_tool_call_id(candidates: Iterable[str], target: str) -> str | None:
    for candidate in candidates:
        if candidate == target:
            return candidate
        if candidate.startswith(target) or target.startswith(candidate):
            return candidate
    return None



def extract_urls(content: str, artifact: Any) -> List[str]:
    urls = extract_urls_from_tool_message(content)
    if isinstance(artifact, list):
        for item in artifact:
            source = None
            if isinstance(item, dict):
                source = item.get("url") or item.get("source")
            else:
                metadata = getattr(item, "metadata", None)
                if isinstance(metadata, dict):
                    source = metadata.get("source")
            if source and source not in urls:
                urls.append(source)
    return urls



def summarize_title(messages: List[Dict[str, Any]]) -> str:
    transcript = "\n".join(
        f"{message['role']}: {(message.get('content') or '').strip()}"
        for message in messages
        if (message.get("content") or "").strip()
    )
    if not transcript:
        return "新对话"
    try:
        summary = summary_chain.invoke({"input": transcript}).strip()
        return summary[:20] or "新对话"
    except Exception:
        return "新对话"


@app.get("/api/models")
def list_models() -> List[Dict[str, str]]:
    return [{"id": model_id, "label": label} for model_id, label in MODEL_OPTIONS.items()]


@app.get("/api/conversations", response_model=List[ConversationSummary])
def list_conversations() -> List[Dict[str, Any]]:
    with store_lock:
        return sorted_summaries(load_store())


@app.post("/api/conversations", response_model=ConversationRecord)
def create_conversation(request: ConversationCreateRequest) -> Dict[str, Any]:
    with store_lock:
        store = load_store()
        conversation = create_conversation_record(request.model)
        store["conversations"][conversation["id"]] = conversation
        save_store(store)
        return conversation


@app.get("/api/conversations/{conversation_id}", response_model=ConversationRecord)
def get_conversation(conversation_id: str) -> Dict[str, Any]:
    with store_lock:
        store = load_store()
        return get_conversation_or_404(store, conversation_id)


@app.patch("/api/conversations/{conversation_id}", response_model=ConversationRecord)
def update_conversation(conversation_id: str, request: ConversationUpdateRequest) -> Dict[str, Any]:
    with store_lock:
        store = load_store()
        conversation = get_conversation_or_404(store, conversation_id)
        if request.title is not None:
            conversation["title"] = request.title.strip() or conversation["title"]
        if request.model is not None and request.model in MODEL_OPTIONS:
            conversation["model"] = request.model
        conversation["updated_at"] = now_iso()
        save_store(store)
        return conversation


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> Dict[str, bool]:
    with store_lock:
        store = load_store()
        if conversation_id not in store.get("conversations", {}):
            raise HTTPException(status_code=404, detail="Conversation not found")
        del store["conversations"][conversation_id]
        save_store(store)
    return {"ok": True}


@app.post("/api/conversations/{conversation_id}/feedback")
def update_feedback(conversation_id: str, request: FeedbackUpdateRequest) -> Dict[str, bool]:
    with store_lock:
        store = load_store()
        conversation = get_conversation_or_404(store, conversation_id)
        for message in conversation["messages"]:
            if message["id"] == request.message_id:
                message["feedback"] = request.feedback
                conversation["updated_at"] = now_iso()
                save_store(store)
                return {"ok": True}
    raise HTTPException(status_code=404, detail="Message not found")


@app.post("/api/conversations/{conversation_id}/messages")
def create_message(conversation_id: str, request: MessageCreateRequest) -> StreamingResponse:
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty")

    with store_lock:
        store = load_store()
        conversation = get_conversation_or_404(store, conversation_id)
        selected_model = request.model if request.model in MODEL_OPTIONS else conversation["model"]
        conversation["model"] = selected_model
        user_message = {
            "id": str(uuid4()),
            "role": "user",
            "content": content,
            "timestamp": now_iso(),
            "parts": [{"type": "text", "content": content}],
            "feedback": None,
        }
        conversation["messages"].append(user_message)
        conversation["updated_at"] = now_iso()
        thread_id = conversation["thread_id"]
        save_store(store)

    def event_stream() -> Iterable[bytes]:
        assistant_text = ""
        pending_tools: Dict[str, Dict[str, Any]] = {}
        tool_parts: List[Dict[str, Any]] = []
        try:
            yield serialize_event("user", user_message)
            for step in graph.stream(
                {"messages": [{"role": "user", "content": content}]},
                stream_mode="messages",
                config={"configurable": {"thread_id": thread_id, "model": selected_model}},
            ):
                message_chunk, _ = step
                if hasattr(message_chunk, "tool_calls") and message_chunk.tool_calls:
                    message_chunk = combine_tool_calls(message_chunk)
                    for tool_call in message_chunk.tool_calls:
                        if not isinstance(tool_call, dict):
                            continue
                        tool_name = tool_call.get("name")
                        if tool_name not in {"retrieve", "bocha_websearch_tool"}:
                            continue
                        tool_id = clean_tool_call_id(tool_call.get("id", ""))
                        args = tool_call.get("args") or {}
                        query = args.get("query", "") if isinstance(args, dict) else ""
                        tool_part = {
                            "type": "tool",
                            "tool_id": tool_id,
                            "tool_name": tool_name,
                            "query": query,
                            "status": "running",
                            "status_label": "正在搜索网络" if tool_name == "bocha_websearch_tool" else "正在查询数据库",
                            "urls": [],
                        }
                        pending_tools[tool_id] = tool_part
                        tool_parts.append(tool_part)
                        yield serialize_event("tool_call", tool_part)
                elif type(message_chunk).__name__ == "ToolMessage":
                    clean_id = clean_tool_call_id(getattr(message_chunk, "tool_call_id", ""))
                    matched_id = matching_tool_call_id(pending_tools.keys(), clean_id)
                    if not matched_id:
                        continue
                    tool_part = pending_tools[matched_id]
                    tool_part["status"] = "complete"
                    tool_part["status_label"] = (
                        "网络搜索完成"
                        if tool_part["tool_name"] == "bocha_websearch_tool"
                        else "数据库查询完成"
                    )
                    tool_part["urls"] = extract_urls(
                        getattr(message_chunk, "content", ""),
                        getattr(message_chunk, "artifact", None),
                    )
                    yield serialize_event("tool_result", tool_part)
                elif getattr(message_chunk, "content", None):
                    delta = message_chunk.content
                    assistant_text += delta
                    yield serialize_event("chunk", {"delta": delta})

            assistant_message = {
                "id": str(uuid4()),
                "role": "assistant",
                "content": assistant_text.strip(),
                "timestamp": now_iso(),
                "parts": ([{"type": "text", "content": assistant_text.strip()}] if assistant_text.strip() else []) + tool_parts,
                "feedback": None,
            }

            with store_lock:
                store = load_store()
                conversation = get_conversation_or_404(store, conversation_id)
                conversation["messages"].append(assistant_message)
                if conversation["title"] == "新对话":
                    conversation["title"] = summarize_title(conversation["messages"])
                conversation["model"] = selected_model
                conversation["updated_at"] = now_iso()
                save_store(store)
                summary = make_conversation_summary(conversation)

            yield serialize_event(
                "done",
                {
                    "message": assistant_message,
                    "conversation": summary,
                },
            )
        except Exception as exc:
            yield serialize_event("error", {"message": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
if (FRONTEND_DIST / "ui").exists():
    app.mount("/ui", StaticFiles(directory=FRONTEND_DIST / "ui"), name="ui")


@app.get("/{full_path:path}")
def serve_frontend(full_path: str) -> Any:
    requested_path = FRONTEND_DIST / full_path
    if full_path and requested_path.exists() and requested_path.is_file():
        return FileResponse(requested_path)
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse(
        {
            "message": "Frontend build not found. Run `npm run build` in /frontend or use the Vite dev server.",
        },
        status_code=503,
    )
