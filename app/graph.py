# Copyright © 2024-2026 林昱辰&章勋. All Rights Reserved.
# 
# 福大灵犀 - 基于LangGraph和Streamlit的福州大学智能问答系统
# 
# 本代码仅供教育和学习目的使用。未经许可，禁止复制、修改、分发或用于商业目的。
# 
# 代码: 林昱辰
# 电子邮箱: 102304226@fzu.edu.cn
# 提示词: 章勋
# 电子邮箱: 3134429813@qq.com
# 最后修改: 2025年6月7日
from contextvars import ContextVar
from datetime import datetime, timedelta
import json
import logging
import os
from pathlib import Path
import re
import requests
import ssl
import tempfile
from threading import Lock, Thread
from typing import Any, Dict, List
from urllib.parse import urlparse
from uuid import uuid4

from langchain_classic.retrievers.multi_vector import MultiVectorRetriever
from langchain_classic.storage import LocalFileStore
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage, ToolMessage, trim_messages
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
import langchain_openai.chat_models.base as langchain_openai_base
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from .memory_store import user_memory_store
from .security_utils import ensure_private_dir, ensure_private_file, env_flag

try:
    import certifi
except ImportError:  # pragma: no cover - requests normally installs certifi.
    certifi = None


logger = logging.getLogger(__name__)

_ORIGINAL_CONVERT_DICT_TO_MESSAGE = langchain_openai_base._convert_dict_to_message
_ORIGINAL_CONVERT_MESSAGE_TO_DICT = langchain_openai_base._convert_message_to_dict
_ORIGINAL_CONVERT_DELTA_TO_MESSAGE_CHUNK = langchain_openai_base._convert_delta_to_message_chunk

BASE_DIR = Path(__file__).resolve().parent
FAISS_DIR = BASE_DIR / "faiss" / "fzu_chat"
DATA_DIR = BASE_DIR / "data"
CHECKPOINT_PATH = Path(
    os.getenv("FZU_CHAT_CHECKPOINT_PATH", str(BASE_DIR / "storage" / "conversation_history.sqlite"))
)
HUAWEICLOUD_OPENAI_BASE_URL = os.getenv(
    "HUAWEICLOUD_OPENAI_BASE_URL",
    "https://api.modelarts-maas.com/openai/v1",
)
DEFAULT_CHAT_MODEL = "glm-5.1"
KIMI_CHAT_MODEL = "kimi-k2.6"
DEEPSEEK_V4_PRO_CHAT_MODEL = "deepseek-v4-pro"
TITLE_SUMMARY_MODEL = "qwen3-30b-a3b"
CHAT_MODEL_OPTIONS = {
    DEFAULT_CHAT_MODEL: "GLM-5.1",
    KIMI_CHAT_MODEL: "Kimi K2.6",
    DEEPSEEK_V4_PRO_CHAT_MODEL: "DeepSeek V4 Pro"
}
SEARCH_RESULT_TOOL_NAMES = {"retrieve", "bocha_websearch_tool"}
SEARCH_RESULT_CITATION_RE = re.compile(r"^\[(\d+)\]$")
SEARCH_RESULT_INLINE_CITATION_RE = re.compile(r"\[(\d+)\](?!\()")
SEARCH_CITATION_COUNTER: ContextVar[int] = ContextVar("search_citation_counter", default=0)
MAX_HISTORY_TOKENS = 200_000
JWCH_LOCATE_DATE_URL = "https://jwcjwxt2.fzu.edu.cn:82/week.asp"
JWCH_LOCATE_DATE_TIMEOUT = 5
JWCH_LOCATE_DATE_RE = re.compile(
    r'var\s+week\s*=\s*"(?P<week>\d+)".*?var\s+xn\s*=\s*"(?P<year>\d{4})".*?var\s+xq\s*=\s*"(?P<term>\d{2})"',
    re.S,
)
JWCH_LOCATE_DATE_EXTRA_CA_PATH = BASE_DIR / "certs" / "digicert_basic_ov_g2_tls_cn_rsa4096_sha256_2022_ca1.pem"
JWCH_LOCATE_DATE_CA_BUNDLE_PATH = Path(tempfile.gettempdir()) / "fzu_chat_jwch_locate_date_ca_bundle.pem"
WEEK_LOCATE_CACHE: Dict[str, Any] = {}
WEEK_LOCATE_CACHE_LOCK = Lock()
JWCH_LOCATE_DATE_CA_BUNDLE_LOCK = Lock()
JWCH_LOCATE_DATE_WARMUP_LOCK = Lock()
JWCH_LOCATE_DATE_WARMUP_RUNNING = False


def _normalize_reasoning_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return str(value)


def _patch_langchain_openai_reasoning_support() -> None:
    if getattr(langchain_openai_base, "_fzu_reasoning_content_patch_applied", False):
        return

    def patched_convert_dict_to_message(_dict: Any) -> Any:
        message = _ORIGINAL_CONVERT_DICT_TO_MESSAGE(_dict)
        if isinstance(message, AIMessage) and isinstance(_dict, dict) and "reasoning_content" in _dict:
            message.additional_kwargs["reasoning_content"] = _normalize_reasoning_content(_dict.get("reasoning_content"))
        return message

    def patched_convert_message_to_dict(message: Any, api: str = "chat/completions") -> Dict[str, Any]:
        message_dict = _ORIGINAL_CONVERT_MESSAGE_TO_DICT(message, api=api)
        if isinstance(message, AIMessage) and "reasoning_content" in message.additional_kwargs:
            message_dict["reasoning_content"] = _normalize_reasoning_content(message.additional_kwargs.get("reasoning_content"))
        return message_dict

    def patched_convert_delta_to_message_chunk(_dict: Any, default_class: Any) -> Any:
        chunk = _ORIGINAL_CONVERT_DELTA_TO_MESSAGE_CHUNK(_dict, default_class)
        if isinstance(chunk, AIMessageChunk) and isinstance(_dict, dict) and "reasoning_content" in _dict:
            chunk.additional_kwargs["reasoning_content"] = _normalize_reasoning_content(_dict.get("reasoning_content"))
        return chunk

    langchain_openai_base._convert_dict_to_message = patched_convert_dict_to_message
    langchain_openai_base._convert_message_to_dict = patched_convert_message_to_dict
    langchain_openai_base._convert_delta_to_message_chunk = patched_convert_delta_to_message_chunk
    langchain_openai_base._fzu_reasoning_content_patch_applied = True


_patch_langchain_openai_reasoning_support()


def reset_search_citation_counter() -> None:
    SEARCH_CITATION_COUNTER.set(0)


def next_search_citation_id() -> int:
    citation_id = SEARCH_CITATION_COUNTER.get() + 1
    SEARCH_CITATION_COUNTER.set(citation_id)
    return citation_id


def _week_anchor(value: datetime) -> datetime:
    return (value - timedelta(days=value.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _format_term_label(year: Any, term: Any) -> str:
    try:
        normalized_year = int(year)
    except (TypeError, ValueError):
        return ""

    normalized_term = str(term or "").strip()
    if normalized_term not in {"01", "02"}:
        return ""
    term_label = "第一学期" if normalized_term == "01" else "第二学期"
    return f"{normalized_year}-{normalized_year + 1}学年{term_label}"


def _format_teaching_week_context(week: Any, year: Any, term: Any) -> str:
    try:
        normalized_week = max(int(week), 1)
    except (TypeError, ValueError):
        return ""

    term_label = _format_term_label(year, term)
    if term_label:
        return f"{term_label}第{normalized_week}周"
    return f"第{normalized_week}周"


def _resolve_jwch_locate_date_verify_path() -> str | bool:
    source_paths: List[Path] = []

    if certifi is not None:
        certifi_path = Path(certifi.where())
        if certifi_path.is_file():
            source_paths.append(certifi_path)

    default_verify_paths = ssl.get_default_verify_paths()
    if default_verify_paths.cafile:
        default_cafile_path = Path(default_verify_paths.cafile)
        if default_cafile_path.is_file() and default_cafile_path not in source_paths:
            source_paths.append(default_cafile_path)

    if JWCH_LOCATE_DATE_EXTRA_CA_PATH.is_file() and JWCH_LOCATE_DATE_EXTRA_CA_PATH not in source_paths:
        source_paths.append(JWCH_LOCATE_DATE_EXTRA_CA_PATH)

    if not source_paths:
        if default_verify_paths.capath and Path(default_verify_paths.capath).is_dir():
            return default_verify_paths.capath
        return True

    if len(source_paths) == 1:
        return str(source_paths[0])

    with JWCH_LOCATE_DATE_CA_BUNDLE_LOCK:
        if not JWCH_LOCATE_DATE_CA_BUNDLE_PATH.exists():
            with JWCH_LOCATE_DATE_CA_BUNDLE_PATH.open("wb") as bundle_file:
                for source_path in source_paths:
                    cert_bytes = source_path.read_bytes()
                    bundle_file.write(cert_bytes)
                    if not cert_bytes.endswith(b"\n"):
                        bundle_file.write(b"\n")
        return str(JWCH_LOCATE_DATE_CA_BUNDLE_PATH)


def _fetch_jwch_locate_date() -> Dict[str, Any]:
    response = requests.get(
        JWCH_LOCATE_DATE_URL,
        timeout=JWCH_LOCATE_DATE_TIMEOUT,
        verify=_resolve_jwch_locate_date_verify_path(),
    )
    response.raise_for_status()
    match = JWCH_LOCATE_DATE_RE.search(response.text)
    if not match:
        raise ValueError("无法解析教务周次信息")
    return {
        "week": int(match.group("week")),
        "year": int(match.group("year")),
        "term": match.group("term"),
        "fetched_at": datetime.now(),
    }


def get_current_teaching_week_context() -> str:
    now = datetime.now()
    with WEEK_LOCATE_CACHE_LOCK:
        cached = dict(WEEK_LOCATE_CACHE)

    cached_at = cached.get("fetched_at")
    if isinstance(cached_at, datetime) and _week_anchor(cached_at) == _week_anchor(now):
        return _format_teaching_week_context(cached.get("week"), cached.get("year"), cached.get("term"))

    try:
        fresh = _fetch_jwch_locate_date()
    except Exception:
        logger.warning("Failed to refresh JWCH locate date; falling back to cached teaching week when available.", exc_info=True)
        if isinstance(cached_at, datetime):
            weeks_delta = max(((_week_anchor(now) - _week_anchor(cached_at)).days // 7), 0)
            return _format_teaching_week_context(
                int(cached.get("week") or 1) + weeks_delta,
                cached.get("year"),
                cached.get("term"),
            )
        return ""

    with WEEK_LOCATE_CACHE_LOCK:
        WEEK_LOCATE_CACHE.clear()
        WEEK_LOCATE_CACHE.update(fresh)
    return _format_teaching_week_context(fresh.get("week"), fresh.get("year"), fresh.get("term"))


def get_cached_teaching_week_context() -> str:
    now = datetime.now()
    with WEEK_LOCATE_CACHE_LOCK:
        cached = dict(WEEK_LOCATE_CACHE)
    cached_at = cached.get("fetched_at")
    if isinstance(cached_at, datetime):
        weeks_delta = max(((_week_anchor(now) - _week_anchor(cached_at)).days // 7), 0)
        return _format_teaching_week_context(
            int(cached.get("week") or 1) + weeks_delta,
            cached.get("year"),
            cached.get("term"),
        )
    return ""


def warm_teaching_week_cache_async() -> None:
    global JWCH_LOCATE_DATE_WARMUP_RUNNING
    with JWCH_LOCATE_DATE_WARMUP_LOCK:
        if JWCH_LOCATE_DATE_WARMUP_RUNNING:
            return
        JWCH_LOCATE_DATE_WARMUP_RUNNING = True

    def runner() -> None:
        global JWCH_LOCATE_DATE_WARMUP_RUNNING
        try:
            get_current_teaching_week_context()
        finally:
            with JWCH_LOCATE_DATE_WARMUP_LOCK:
                JWCH_LOCATE_DATE_WARMUP_RUNNING = False

    Thread(target=runner, name="jwch-teaching-week-warmup", daemon=True).start()


def get_result_source_label(url: str) -> str:
    cleaned = url.strip()
    if not cleaned:
        return ""
    parsed = urlparse(cleaned)
    return parsed.netloc or cleaned


def build_retrieve_citation_items(retrieved_docs) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for citation_id, doc in enumerate(retrieved_docs, start=1):
        metadata = getattr(doc, "metadata", {}) or {}
        source = str(metadata.get("source") or "").strip() if isinstance(metadata, dict) else ""
        items.append(
            {
                "citation_id": citation_id,
                "label": f"[{citation_id}]",
                "title": (
                    str(metadata.get("title") or "").strip() if isinstance(metadata, dict) else ""
                )
                or get_result_source_label(source)
                or f"知识库片段 {citation_id}",
                "url": source,
                "snippet": str(getattr(doc, "page_content", "") or "").strip(),
                "source_name": (
                    str(metadata.get("source_name") or "知识库").strip() if isinstance(metadata, dict) else "知识库"
                ),
            }
        )
    return items


def build_web_search_citation_items(webpages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for citation_id, page in enumerate(webpages, start=1):
        source = str(page.get("url") or "").strip()
        items.append(
            {
                "citation_id": citation_id,
                "label": f"[{citation_id}]",
                "title": str(page.get("name") or "").strip() or get_result_source_label(source) or f"网络结果 {citation_id}",
                "url": source,
                "snippet": str(page.get("summary") or "").strip(),
                "source_name": str(page.get("siteName") or "网络搜索").strip(),
                "published_at": str(page.get("dateLastCrawled") or "").strip(),
            }
        )
    return items


def format_retrieve_citation_item(item: Dict[str, Any]) -> str:
    lines = [str(item.get("label") or "")]
    if item.get("title"):
        lines.append(f"标题: {item['title']}")
    if item.get("url"):
        lines.append(f"URL: {item['url']}")
    if item.get("snippet"):
        lines.append(f"内容摘录: {item['snippet']}")
    return "\n".join(lines)


def format_web_search_citation_item(item: Dict[str, Any]) -> str:
    lines = [str(item.get("label") or "")]
    if item.get("title"):
        lines.append(f"标题: {item['title']}")
    if item.get("url"):
        lines.append(f"URL: {item['url']}")
    if item.get("snippet"):
        lines.append(f"摘要: {item['snippet']}")
    if item.get("source_name"):
        lines.append(f"网站名称: {item['source_name']}")
    if item.get("published_at"):
        lines.append(f"发布时间: {item['published_at']}")
    return "\n".join(lines)


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


def remap_search_citation_references(content: str, citation_id_map: Dict[str, str]) -> str:
    if not content or not citation_id_map:
        return content

    def replace_match(match: re.Match[str]) -> str:
        citation_id = match.group(1)
        return f"[{citation_id_map.get(citation_id, citation_id)}]"

    return SEARCH_RESULT_INLINE_CITATION_RE.sub(replace_match, content)


def extract_search_result_items_from_message(message: Any) -> List[Dict[str, Any]]:
    if not isinstance(message, ToolMessage):
        return []

    tool_name = str(getattr(message, "name", "") or "")
    if tool_name not in SEARCH_RESULT_TOOL_NAMES:
        return []

    artifact = getattr(message, "artifact", None)
    if isinstance(artifact, list):
        items = [dict(item) for item in artifact if isinstance(item, dict)]
        if items:
            return items

    return parse_labeled_search_results(extract_text_content(getattr(message, "content", "")))


def get_next_search_citation_start(messages: List[Any]) -> int:
    max_citation_id = 0

    for message in messages:
        for item in extract_search_result_items_from_message(message):
            try:
                citation_id = int(item.get("citation_id") or 0)
            except (TypeError, ValueError):
                continue
            max_citation_id = max(max_citation_id, citation_id)

    return max_citation_id + 1


def renumber_search_citation_items(
    items: List[Dict[str, Any]],
    start_citation_id: int,
) -> tuple[List[Dict[str, Any]], Dict[str, str], int]:
    normalized_items: List[Dict[str, Any]] = []
    citation_id_map: Dict[str, str] = {}
    next_citation = start_citation_id

    for item in items:
        if not isinstance(item, dict):
            continue
        normalized_item = dict(item)
        original_citation_id = str(normalized_item.get("citation_id") or "").strip()
        if original_citation_id:
            citation_id_map[original_citation_id] = str(next_citation)
        normalized_item["citation_id"] = next_citation
        normalized_item["label"] = f"[{next_citation}]"
        normalized_items.append(normalized_item)
        next_citation += 1

    return normalized_items, citation_id_map, next_citation


def normalize_search_tool_message(
    message: ToolMessage,
    start_citation_id: int,
) -> tuple[ToolMessage, int]:
    tool_name = str(getattr(message, "name", "") or "")
    if tool_name not in SEARCH_RESULT_TOOL_NAMES:
        return message, start_citation_id

    items = extract_search_result_items_from_message(message)
    if not items:
        return message, start_citation_id

    normalized_items, citation_id_map, next_citation_id = renumber_search_citation_items(items, start_citation_id)
    updated_content = getattr(message, "content", "")
    if isinstance(updated_content, str):
        updated_content = remap_search_citation_references(updated_content, citation_id_map)

    return (
        message.model_copy(
            update={
                "content": updated_content,
                "artifact": normalized_items,
            }
        ),
        next_citation_id,
    )


def normalize_search_tool_messages(messages: List[Any], prior_messages: List[Any] | None = None) -> List[Any]:
    normalized_messages: List[Any] = []
    next_citation_id = get_next_search_citation_start(prior_messages or [])

    for message in messages:
        if isinstance(message, ToolMessage):
            normalized_message, next_citation_id = normalize_search_tool_message(message, next_citation_id)
            normalized_messages.append(normalized_message)
        else:
            normalized_messages.append(message)
    return normalized_messages


def parse_tool_call_args(value: Any) -> Dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate:
        return {}

    attempts = [candidate]
    if not candidate.startswith("{"):
        attempts.append("{" + candidate)
    if not candidate.endswith("}"):
        attempts.append(candidate + "}")
    if not candidate.startswith("{") and not candidate.endswith("}"):
        attempts.append("{" + candidate + "}")

    for attempt in dict.fromkeys(attempts):
        try:
            parsed = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def recover_invalid_tool_calls(message: Any) -> Any:
    if not hasattr(message, "tool_calls") and not hasattr(message, "invalid_tool_calls"):
        return message

    raw_tool_calls = list(getattr(message, "tool_calls", None) or [])
    raw_invalid_tool_calls = list(getattr(message, "invalid_tool_calls", None) or [])
    if not raw_invalid_tool_calls:
        return message

    normalized_tool_calls: List[Dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    changed = False

    for tool_call in raw_tool_calls:
        if not isinstance(tool_call, dict):
            changed = True
            continue
        name = str(tool_call.get("name") or "").strip()
        tool_call_id = str(tool_call.get("id") or "").strip() or f"call_{uuid4().hex[:24]}"
        args = parse_tool_call_args(tool_call.get("args"))
        if not name or args is None:
            changed = True
            continue

        normalized_tool_call = {**tool_call, "name": name, "id": tool_call_id, "args": args}
        normalized_tool_calls.append(normalized_tool_call)
        seen_keys.add((name, tool_call_id))
        if normalized_tool_call != tool_call:
            changed = True

    remaining_invalid_tool_calls: List[Any] = []
    for invalid_tool_call in raw_invalid_tool_calls:
        if not isinstance(invalid_tool_call, dict):
            remaining_invalid_tool_calls.append(invalid_tool_call)
            continue

        name = str(invalid_tool_call.get("name") or "").strip()
        if not name:
            remaining_invalid_tool_calls.append(invalid_tool_call)
            continue

        args = parse_tool_call_args(invalid_tool_call.get("args"))
        if args is None:
            remaining_invalid_tool_calls.append(invalid_tool_call)
            continue

        tool_call_id = str(invalid_tool_call.get("id") or "").strip() or f"call_{uuid4().hex[:24]}"
        key = (name, tool_call_id)
        if key not in seen_keys:
            normalized_tool_calls.append({"name": name, "args": args, "id": tool_call_id, "type": "tool_call"})
            seen_keys.add(key)
        changed = True

    if not changed:
        return message

    return message.model_copy(
        update={
            "tool_calls": normalized_tool_calls,
            "invalid_tool_calls": remaining_invalid_tool_calls,
        }
    )


def read_secret_or_env(secret_path: str, *env_names: str) -> str | None:
    secret_file_path = Path(secret_path)
    if secret_file_path.exists():
        secret_value = secret_file_path.read_text(encoding="utf-8").strip()
        if secret_value:
            return secret_value

    for env_name in env_names:
        env_value = os.getenv(env_name)
        if env_value:
            return env_value.strip()

    project_root = BASE_DIR.parent
    candidate_paths = []
    for env_name in env_names:
        normalized_name = env_name.strip().lower()
        if normalized_name:
            candidate_paths.append(project_root / f"{normalized_name}.txt")

    for path in candidate_paths:
        if path.exists():
            secret_value = path.read_text(encoding="utf-8").strip()
            if secret_value:
                return secret_value
    return None


LANGSMITH_API_KEY = read_secret_or_env("/run/secrets/langsmith_api_key", "LANGSMITH_API_KEY")
LANGSMITH_TRACING_ENABLED = env_flag("FZU_CHAT_ENABLE_LANGSMITH_TRACING", default=False)

if LANGSMITH_TRACING_ENABLED:
    if not LANGSMITH_API_KEY:
        raise ValueError("已启用 LangSmith tracing，但未配置 LangSmith API 密钥")
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY
    os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
else:
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ.pop("LANGCHAIN_API_KEY", None)
    os.environ.pop("LANGCHAIN_ENDPOINT", None)

dashscope_api_key = read_secret_or_env("/run/secrets/dashscope_api_key", "DASHSCOPE_API_KEY")

if not dashscope_api_key:
    raise ValueError("DashScope API密钥未设置")

huawei_maas_api_key = read_secret_or_env(
    "/run/secrets/huaweicloud_maas_api_key",
    "HUAWEICLOUD_MAAS_API_KEY",
    "MAAS_API_KEY",
)
if not huawei_maas_api_key:
    raise ValueError("华为云 MaaS API密钥未设置")

BOCHA_API_KEY = read_secret_or_env("/run/secrets/bocha_api_key", "BOCHA_API_KEY")

if not BOCHA_API_KEY:
    raise ValueError("Bocha API密钥未设置")


def is_qwen_model(model_name: str) -> bool:
    return model_name.lower().startswith("qwen")


def build_thinking_config(thinking_enabled: bool | None, model_name: str | None = None) -> Dict[str, Any]:
    if thinking_enabled is None:
        return {}
    thinking_type = "enabled" if thinking_enabled else "disabled"
    config: Dict[str, Any] = {"thinking": {"type": thinking_type}}
    if model_name and is_qwen_model(model_name):
        config["chat_template_kwargs"] = {"enable_thinking": thinking_enabled}
    return config


def build_chat_llm(
    model_name: str,
    *,
    temperature: float,
    streaming: bool,
    stop: List[str] | None = None,
    thinking_enabled: bool | None = None,
    thinking_type: str | None = None,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    normalized_model = model_name if model_name in CHAT_MODEL_OPTIONS or model_name == TITLE_SUMMARY_MODEL else DEFAULT_CHAT_MODEL
    init_kwargs: Dict[str, Any] = {
        "model": normalized_model,
        "temperature": temperature,
        "streaming": streaming,
        "api_key": huawei_maas_api_key,
        "base_url": HUAWEICLOUD_OPENAI_BASE_URL,
    }
    if stop:
        init_kwargs["stop_sequences"] = stop
    if max_tokens is not None:
        init_kwargs["max_tokens"] = max_tokens

    extra_body = build_thinking_config(thinking_enabled, normalized_model)
    if thinking_type:
        extra_body["thinking"] = {"type": thinking_type}
        if is_qwen_model(normalized_model):
            extra_body["chat_template_kwargs"] = {"enable_thinking": thinking_type == "enabled"}
    if extra_body:
        init_kwargs["extra_body"] = extra_body
    return ChatOpenAI(**init_kwargs)

vector_store = FAISS.load_local(
    str(FAISS_DIR),
    DashScopeEmbeddings(model="text-embedding-v3",dashscope_api_key=dashscope_api_key),
    allow_dangerous_deserialization=True,
)
retriever = MultiVectorRetriever(
    vectorstore=vector_store,
    byte_store=LocalFileStore(str(DATA_DIR)),
    id_key="doc_id",
    search_kwargs={"k": 3},
)

@tool(response_format="content_and_artifact")
def bocha_websearch_tool(query: str,freshness: str) -> tuple[str, Any]:
    """在retrieve工具无法找到相关信息时调用，使用Bocha Web Search API 进行搜索互联网网页，输入应为搜索查询字符串，输出将返回搜索结果的详细信息，包括网页标题、网页URL、网页摘要、网站名称、网页发布时间等。
    参数:
    - query: 搜索关键词
    - freshness: 搜索的时间范围，例如 "oneDay", "oneWeek", "oneMonth", "oneYear", "noLimit"
    """
    url = 'https://api.bochaai.com/v1/web-search'
    headers = {
        'Authorization': f'Bearer {BOCHA_API_KEY}',  # 请替换为你的API密钥
        'Content-Type': 'application/json'
    }
    data = {
        "query": query,
        "freshness": freshness, # 搜索的时间范围，例如 "oneDay", "oneWeek", "oneMonth", "oneYear", "noLimit"
        "summary": True, # 是否返回长文本摘要
        "count": 3
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 200:
        json_response = response.json()
        try:
            if json_response["code"] != 200 or not json_response["data"]:
                return f"搜索API请求失败，原因是: {response.msg or '未知错误'}", None
            
            webpages = json_response["data"]["webPages"]["value"]
            if not webpages:
                return "未找到相关结果。", []
            citation_items = build_web_search_citation_items(webpages)
            formatted_results = "\n\n".join(format_web_search_citation_item(item) for item in citation_items)
            return formatted_results.strip(), citation_items
        except Exception as e:
            return f"搜索API请求失败，原因是：搜索结果解析失败 {str(e)}", None
    else:
        return f"搜索API请求失败，状态码: {response.status_code}, 错误信息: {response.text}", None


@tool(response_format="content_and_artifact")
def retrieve(query: str):
    """从校内知识库返回**可能**和查询语句(query)相关的有关福州大学信息的文档片段，查询语句需要包含福州大学，并且查询中只能包含一个问题，注意：检索到的信息可能不完整、被截断或和query不相关，必须判断返回的信息是否和query相关后再使用。"""
    retrieved_docs = retriever.invoke(query)
    citation_items = build_retrieve_citation_items(retrieved_docs)
    serialized = "\n\n".join(format_retrieve_citation_item(item) for item in citation_items)
    return serialized, citation_items


def build_confirmed_user_memory_context(user_id: str, limit: int = 8) -> str:
    if not user_id:
        return ""
    try:
        memories = user_memory_store.get_context_memories(user_id, limit=limit)
    except Exception:
        logger.warning("Failed to load user memory context.", exc_info=True)
        return ""
    if not memories:
        return ""

    lines = [
        "已确认的福大灵犀个性化长期记忆（仅在与当前问题相关时使用；教务事实仍应以教务工具实时查询为准；如果与用户本轮消息冲突，以用户本轮消息为准）：",
    ]
    for index, memory_item in enumerate(memories, start=1):
        category = memory_item.get("category") or "未分类"
        content = memory_item.get("content") or ""
        importance = memory_item.get("importance", 50)
        lines.append(f"{index}. [{category}] {content}（重要度 {importance}/100）")
    return "\n".join(lines)


def build_runtime_system_context(user_id: str, dynamic_campus_context: str = "") -> str:
    now = datetime.now()
    weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    current_time = f"{now.strftime('%Y年%m月%d日')} {weekday_names[now.weekday()]}"
    lines = [
        "运行时上下文（短生命周期信息；仅供本次回答参考，不要写入长期记忆）：",
        f"- 当前时间：{current_time}。",
    ]
    current_teaching_week = get_cached_teaching_week_context()
    if current_teaching_week:
        lines.append(f"- 当前教学周：{current_teaching_week}。")
    else:
        lines.append("- 当前教学周：后台正在同步；教务工具不能获取教学周，如果本轮问题依赖精确周次，请说明正在同步并建议结合校历核对。")
    lines.append("- 课程节次：1-4节在上午，5-8节在下午，9-11节在晚上。")

    user_memory_context = build_confirmed_user_memory_context(user_id)
    if user_memory_context:
        lines.append("")
        lines.append(user_memory_context)

    if dynamic_campus_context:
        lines.append("")
        lines.append(dynamic_campus_context)
    return "\n".join(lines)


def _build_query_or_respond(edu_tools, user_memory_tools, campus_recommendation_tools, request_context: Dict[str, Any] | None = None):
    request_context = request_context or {}
    user_id = str(request_context.get("user_id") or "").strip()

    def query_or_respond(state: MessagesState, config: RunnableConfig | None = None):
        """Generate tool call for retrieval or respond."""
        config = config or {}
        configurable = config.get("configurable", {})
        model_name = configurable.get("model", DEFAULT_CHAT_MODEL)
        thinking_enabled = configurable.get("thinking_enabled")
        if not isinstance(thinking_enabled, bool):
            thinking_enabled = None
        llm = build_chat_llm(
            model_name,
            temperature=0.4,
            streaming=True,
            stop=["请用以下风格与用户交流"],
            thinking_enabled=thinking_enabled,
        )
        all_tools = [retrieve, bocha_websearch_tool] + edu_tools + user_memory_tools + campus_recommendation_tools
        llm_with_tools = llm.bind_tools(all_tools)
        stable_sys_prompt = """作为福大灵犀，你是一个温暖亲切的福州大学AI助手。请用以下风格与用户交流：
1. 开场、结尾与身份：
    - 首次对话时，以温暖的语气简短介绍："你好呀！我是福大灵犀，很高兴能和你聊天呢！～"
    - 后续对话无需重复自我介绍
    - 不要在每次回答末尾机械重复固定结束语；只有在自然合适时，再简短追问下一步需求
2. 回答风格：
    - 使用温和、亲切但简洁的语气
    - 在工具调用前只用一句短提示，不要连续寒暄
    - 避免生硬或过于正式的表达
    - 工具型回复默认不使用 emoji，除非用户明显偏好这种风格
3. 教务系统查询工具：
   你拥有以下教务系统工具，可以直接查询当前登录学生的个人教务数据：
    - query_grades: 查询课程成绩和绩点
    - query_gpa_ranking: 查询绩点、专业排名、班级排名等统计信息
    - query_credit_statistics: 查询主修/辅修学分统计
    - query_courses: 查询课表和上课信息
    - query_course_selection: 查询各类选课时间、通识缺口和当前候选课程
    - select_course: 为用户提交真实选课请求
    - query_exam_rooms: 查询考试安排和考场地点
    - query_student_info: 查询学生个人基本信息
    - query_exam_scores: 查询等级考试成绩（四六级等）
    - query_academic_calendar: 查询校历、开学时间、放假安排、学期事件
    - query_cultivate_plan: 查询当前专业培养方案正文，也可按培养目标、毕业要求、核心课程、课程设置等特定章节检索
    - recommend_campus_context: 基于课表、考试安排、选课窗口、成绩摘要变化和用户明确提供/授权的位置，推荐校园事务、食堂、自习和复习安排

    当用户询问自己的成绩、绩点、排名、学分、课表、选课、考场、个人信息、等级考试成绩、校历、培养方案等教务相关问题时，优先使用这些工具。
    如果工具返回"尚未登录教务系统"或提示教务登录已过期，请友善地提醒用户先在侧边栏重新连接教务系统。
    当工具已经返回结构化结果时：
    - 直接基于工具结果整理回答，保留关键字段，不要改写关键数字
    - 优先使用 markdown 列表或表格
    - 不要重复抄写工具卡片中已经明显展示的同一批字段
        对于 select_course：
        - 只有当用户明确要求“帮我选/提交某门课”时才调用
        - 必须拿到明确的选课类别和准确课程名；若同名课程可能有多门，还应补充教师信息
        - 如果用户只是询问“现在有什么可以选”或“我还差什么课”，先调用 query_course_selection，不要直接提交选课
        对于 recommend_campus_context：
        - 推荐必须说明依据来自课表、考试安排、选课窗口、成绩变化、当前位置或用户手动选择的位置
        - 用户说步行、走路时传 travel_mode=walking；用户说骑车、骑行、自行车时传 travel_mode=bicycling；未说明时不要硬编码 travel_mode，让工具使用用户侧选择的出行偏好
        - 如果用户没有提供位置，也没有通过前端授权定位，请引导用户在隐私页开启定位智能提醒，或让用户说明所在校区/教学楼
        - 当用户询问食堂、饭点、去哪吃、附近自习等位置相关问题时，如果缺少定位，可自然提醒用户在隐私与数据页开启定位权限，以便下次按当前位置给出更顺路的建议
        - 不要把具体当前位置、当前课表、考试安排、成绩、选课状态写入长期记忆；只允许保存餐饮偏好、自习偏好、校区偏好、选课偏好等长期偏好

3.1 个性化记忆工具：
    你拥有以下用户个性化记忆工具：
    - query_user_memory: 查询当前用户已确认保存的长期偏好、背景和习惯，也可在 query 为空时列出最近保存的全部记忆
    - save_user_memory: 生成一条待确认保存的记忆建议，只有用户在前端卡片点击确认后才会真正写入数据库；系统会进行敏感信息、临时信息和相似重复检测
    - delete_user_memory: 生成一条待确认删除的记忆建议，只有用户在前端卡片点击确认后才会真正删除

    使用规则：
    - 福大灵犀的记忆重点是让校内问答、教务查询解释、选课建议、学习规划和校园生活推荐更贴合用户；不是替代教务系统数据库
    - 推荐保存的高价值类别：称呼偏好、输出风格、沟通偏好、餐饮偏好、校区偏好、校园生活偏好、学习目标、学业规划、课程偏好、选课偏好、教务查询偏好、时间展示偏好
    - 下面若出现“已确认的福大灵犀个性化长期记忆”，可直接作为背景参考；只有与当前问题相关时才使用，不要为了展示记忆而生硬提及
    - 当回答明显依赖用户的长期偏好、称呼、餐饮习惯、校区偏好、学习目标、课程/选课偏好、输出风格或其他稳定背景，但下方记忆不足或需要精确 ID 时，先调用 query_user_memory
    - 当用户要求“看看你记住了什么”“管理/删除记忆”“忘掉某条偏好”等需求时，应先调用 query_user_memory 查看现有记忆及其 ID，再按需调用 delete_user_memory
    - 保存前先问自己：未来回答会因为保存这条信息而明显更贴合用户吗？如果答案是否定的，不要调用 save_user_memory
    - 只有当用户消息本身明确表达了长期稳定、未来复用价值高的信息时，才调用 save_user_memory；不要把助手自己的猜测、一次性任务过程或临时状态保存为记忆
    - 记忆应是单条、原子化、可复用的事实或偏好，例如“用户选课推荐优先无早八”“用户查成绩时希望先看绩点和排名变化”“用户更关注旗山校区餐饮推荐”；内容要短而准确
    - 不要保存临时安排、一次性需求、短期情绪、教务账号密码、证件号、手机号、邮箱、准考证号等敏感或易变信息
    - 不要把成绩、绩点、排名、学分、课表、考场、考试安排、选课结果、培养方案正文、校历日期、学院/专业/班级/年级等教务事实写入长期记忆；这类信息应调用教务工具实时查询
    - 可以保存“如何展示或推荐教务信息”的长期偏好，例如默认按周几排序课表、成绩解释先给结论、选课推荐避开早八；但不能保存具体课表/成绩/考场数值本身
    - 用户本轮明确表达的偏好优先级高于旧记忆；如果用户纠正旧记忆，应查询旧记忆并发起删除或更新建议
    - 调用 save_user_memory 后，只能表述为“已发起保存建议，等待确认”，不能说成已经保存成功
    - 调用 delete_user_memory 后，只能表述为“已发起删除建议，等待确认”，不能说成已经删除成功
    - 如果用户要删除全部或一批记忆，可以多次调用 delete_user_memory 逐条发起删除建议

4. 信息检索与搜索策略：
   请遵循以下严格的决策树来处理用户问题：
   a) 如果用户询问自己的成绩、课表、个人信息等教务数据：
      → 使用教务系统查询工具（query_grades / query_gpa_ranking / query_credit_statistics / query_courses / query_course_selection / query_exam_rooms / query_student_info / query_exam_scores / query_academic_calendar / query_cultivate_plan）
   b) 如果用户询问福州大学的公共信息：
      → 优先使用 retrieve 工具查询校内知识库
      → 确保查询中包含"福州大学"关键词
      → 严格评估返回结果是否与用户问题精确匹配
   c) 当校内知识库信息不足时：
      → 使用 bocha_websearch_tool 进行网络搜索
      → 构建精确查询："福州大学 + [用户关键词]"
   d) 如果用户问题与福州大学无关：
      → 友善地引导用户询问福州大学相关的问题
5. 搜索结果处理：
   - 从搜索结果中提取与用户问题最相关的信息
   - 整合多个来源的信息，确保一致性
   - 明确标注信息来源
    - 对 retrieve 和 bocha_websearch_tool 返回结果里的 [数字] 引用标号，必须在最终回答中沿用原编号
    - 每条关键事实后尽量补上对应的 [数字]，不要自创、改写、合并或省略这些编号
   - 如果搜索结果有冲突，诚实说明不同来源的观点
   - 将专业信息转化为友好、易懂的语言
   - 如文本中有图片链接，以markdown格式输出
6. 无法找到信息时：
   - 确保尝试过所有相关工具
   - 真诚地表示歉意，建议用户提供更多线索
   - 不猜测或编造信息，保持诚实可信
7. 对话延续与互动：
   - 回答后自然引导相关话题
   - 适时表达关心和鼓励
8. 动态校园提醒：
   - 运行时上下文中可能出现“校园动态事件”。这些事件只用于判断是否在本次回答末尾自然提醒用户，不是用户显式提问
   - 必须先完整回答用户当前问题；只有提醒与本轮语境自然、不打扰时，才在末尾补一句简短提醒
   - 对考试、成绩、选课这类高优先级校园事件，若用户只是问候、泛泛询问今天安排或学习规划，可以更主动地在末尾补一句提醒
   - 如果动态事件提示接近饭点但没有当前位置，可提醒用户开启定位权限或说明所在校区/教学楼，再调用 recommend_campus_context 获取食堂建议
   - 最多提醒 1-2 条，不要机械列出所有事件，不要说“系统提示/隐藏上下文显示”
   - 如果没有校园动态事件，或事件与用户当前问题无关，就完全不要提
   - 不要把动态事件中的成绩摘要、课表、考试、选课状态、当前位置写入长期记忆
工具使用要求：
- 若有现成工具可完成任务，则应直接使用工具，而非要求用户手动操作
- 若你已声明将执行某项操作，便应直接调用工具完成，无需再征求用户许可
- 使用工具前不要主观猜测问题的答案，而是直接使用工具获取信息
- **不要自己编造信息或用基础知识回答**"""
        runtime_context = str(request_context.get("runtime_system_context") or "").strip()
        if not runtime_context:
            runtime_context = build_runtime_system_context(
                user_id,
                str(request_context.get("dynamic_campus_context") or "").strip(),
            )
        travel_mode = str(request_context.get("travel_mode") or "").strip()
        if travel_mode in {"walking", "bicycling"}:
            travel_mode_label = "骑行" if travel_mode == "bicycling" else "步行"
            runtime_context = "\n".join(
                part
                for part in (
                    runtime_context,
                    f"本轮校园路线出行偏好：{travel_mode_label}。recommend_campus_context 未显式传 travel_mode 时会按该用户侧选择执行。",
                )
                if part
            )
        history_prompt = trim_messages(
            state["messages"],
            max_tokens=MAX_HISTORY_TOKENS,
            token_counter=count_tokens_approximately,
            strategy="last",
            allow_partial=False,
            start_on="human",
            end_on=("human", "tool"),
            include_system=False,
        )
        prompt = [SystemMessage(stable_sys_prompt), SystemMessage(runtime_context), *history_prompt]
        response = recover_invalid_tool_calls(llm_with_tools.invoke(prompt))
        return {"messages": [response]}

    return query_or_respond

from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
ensure_private_dir(CHECKPOINT_PATH.parent)
conn = sqlite3.connect(str(CHECKPOINT_PATH), check_same_thread=False)
conn.execute("PRAGMA secure_delete=ON")
ensure_private_file(CHECKPOINT_PATH)
memory = SqliteSaver(conn)


def build_graph(edu_session: Dict[str, Any] | None = None, use_checkpointer: bool = True):
    from .campus_recommendations import build_campus_recommendation_tools
    from .edu_tools import build_edu_tools
    from .user_memory_tools import build_user_memory_tools

    edu_tools = build_edu_tools(edu_session)
    user_memory_tools = build_user_memory_tools(edu_session)
    campus_recommendation_tools = build_campus_recommendation_tools(edu_session)
    query_or_respond = _build_query_or_respond(edu_tools, user_memory_tools, campus_recommendation_tools, edu_session)
    raw_tools = ToolNode([retrieve, bocha_websearch_tool] + edu_tools + user_memory_tools + campus_recommendation_tools)

    def tools(state: MessagesState, config: RunnableConfig | None = None):
        result = raw_tools.invoke(state, config=config)
        messages = result.get("messages") if isinstance(result, dict) else None
        if not isinstance(messages, list):
            return result
        previous_messages = state.get("messages", []) if isinstance(state, dict) else []
        return {**result, "messages": normalize_search_tool_messages(messages, previous_messages)}

    graph_builder = StateGraph(MessagesState)
    graph_builder.add_node("query_or_respond", query_or_respond)
    graph_builder.add_node("tools", tools)
    graph_builder.set_entry_point("query_or_respond")
    graph_builder.add_conditional_edges(
        "query_or_respond",
        tools_condition,
        {END: END, "tools": "tools"},
    )
    graph_builder.add_edge("tools", "query_or_respond")
    compile_kwargs = {"checkpointer": memory} if use_checkpointer else {}
    return graph_builder.compile(**compile_kwargs)


graph = build_graph()


TITLE_SUMMARY_PROMPT = """你是聊天标题生成专家。只输出中文短标题，不要解释、引号或标点。
规则：概括user请求的主题，短且客观；优先2-8字，最多15字；保留福大、教务、API等专名和缩写；删去“帮我/请问/问题/需求/关于”等泛词；忽略assistant寒暄和工具过程；无明确任务时输出“问候”。
好例：今天晚饭去哪吃 -> 晚餐食堂；帮我查这学期成绩 -> 学期成绩；你好 -> 问候。
请求：
{input}
标题："""
summary_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", TITLE_SUMMARY_PROMPT),
    ]
)
summary_chain = (
    summary_prompt
    | build_chat_llm(TITLE_SUMMARY_MODEL, temperature=0.1, streaming=False, thinking_type="disabled", max_tokens=24)
    | StrOutputParser()
)
