from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from langchain_core.tools import tool

from .memory_store import user_memory_store


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: str, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _normalize_category(value: str) -> str:
    return str(value or "").strip()[:40]


def _normalize_reason(value: str) -> str:
    return str(value or "").strip()[:200]


def _normalize_content(value: str) -> str:
    return str(value or "").strip()[:300]


def _normalize_memory_ids(value: str) -> List[str]:
    if not value:
        return []
    tokens = [token.strip() for token in re.split(r"[\s,，]+", str(value))]
    return [token for token in dict.fromkeys(tokens) if token]


def _filter_memory_items(items: List[Dict[str, Any]], category: str) -> List[Dict[str, Any]]:
    if not category:
        return items
    return [item for item in items if str(item.get("category") or "").strip() == category]


def _format_memory_summary(items: List[Dict[str, Any]], query: str, category: str) -> str:
    lines = ["## 个性化记忆", ""]
    if query:
        lines.append(f"- 查询：{query}")
    if category:
        lines.append(f"- 分类：{category}")
    lines.append(f"- 命中：{len(items)} 条")
    lines.append("")
    for index, item in enumerate(items, start=1):
        category = item.get("category") or "未分类"
        lines.append(f"{index}. ID: {item.get('id')}")
        lines.append(f"   - 分类：{category}")
        lines.append(f"   - 内容：{item.get('content')}")
        if item.get("reason"):
            lines.append(f"   - 说明：{item.get('reason')}")
        if item.get("updated_at"):
            lines.append(f"   - 更新时间：{item.get('updated_at')}")
    return "\n".join(lines)


def _format_delete_summary(items: List[Dict[str, Any]], reason: str) -> str:
    lines = ["## 记忆删除建议", "", f"- 待删除：{len(items)} 条", ""]
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. ID: {item.get('id')}")
        lines.append(f"   - 分类：{item.get('category') or '未分类'}")
        lines.append(f"   - 内容：{item.get('content')}")
        if item.get("reason"):
            lines.append(f"   - 原备注：{item.get('reason')}")
    if reason:
        lines.extend(["", f"- 删除原因：{reason}"])
    lines.extend(["", "> 已生成待确认删除卡片，需用户点击确认后才会真正删除。"])
    return "\n".join(lines)


def build_user_memory_tools(request_context: Dict[str, Any] | None = None):
    user_id = str((request_context or {}).get("user_id") or "").strip()

    @tool(response_format="content_and_artifact")
    def query_user_memory(query: str = "", category: str = "", limit: int = 20) -> Tuple[str, Any]:
        """查询当前用户已确认保存的个性化记忆。

        适用于称呼偏好、长期习惯、饮食禁忌、学习目标、输出风格偏好等长期稳定信息。
        参数:
        - query: 想检索的偏好或背景关键词，例如“称呼偏好”“饮食禁忌”“输出风格”
        - category: 可选，限制记忆分类，例如“饮食偏好”“输出风格”
        - limit: 返回数量上限，建议在需要管理全部记忆时适当调大
        """
        normalized_category = _normalize_category(category)
        safe_limit = max(1, min(int(limit), 50))
        if not user_id:
            artifact = {"mode": "list", "query": query, "category": normalized_category, "items": []}
            return "当前会话未绑定用户，无法查询个性化记忆。", artifact

        items = user_memory_store.search_memories(user_id, query=query, limit=safe_limit)
        items = _filter_memory_items(items, normalized_category)
        artifact = {"mode": "list", "query": query, "category": normalized_category, "items": items}
        if not items:
            return "当前还没有可用的个性化记忆。", artifact
        return _format_memory_summary(items, query, normalized_category), artifact

    @tool(response_format="content_and_artifact")
    def save_user_memory(content: str, category: str = "", reason: str = "") -> Tuple[str, Any]:
        """为当前用户生成一条待确认保存的个性化记忆建议。

        仅适用于长期稳定、未来对回答有帮助的信息。该工具不会直接写入数据库，必须等待前端用户确认。
        不要用于保存密码、证件号、临时安排、一次性情绪或其他敏感信息。

        参数:
        - content: 要记住的核心内容，例如“用户不吃香菜”
        - category: 记忆类别，例如“饮食偏好”“表达风格”“个人背景”
        - reason: 保存原因，说明为什么这条记忆未来有用
        """
        if not user_id:
            artifact = {"mode": "save_request", "status": "unavailable", "content": content, "category": category, "reason": reason}
            return "当前会话未绑定用户，无法保存个性化记忆。", artifact

        normalized_content = _normalize_content(content)
        normalized_category = _normalize_category(category)
        normalized_reason = _normalize_reason(reason)
        if not normalized_content:
            artifact = {"mode": "save_request", "status": "invalid", "content": content, "category": category, "reason": reason}
            return "要保存的记忆内容不能为空。", artifact

        existing = user_memory_store.find_exact_memory(user_id, normalized_content, normalized_category)
        if existing is not None:
            artifact = {
                "mode": "save_request",
                "proposal_id": str(uuid4()),
                "status": "already_saved",
                "content": normalized_content,
                "category": normalized_category,
                "reason": normalized_reason,
                "created_at": now_iso(),
                "saved_memory": existing,
                "memory_id": existing["id"],
            }
            return "这条个性化记忆已经存在，无需再次保存。", artifact

        artifact = {
            "mode": "save_request",
            "proposal_id": str(uuid4()),
            "status": "pending_confirmation",
            "content": normalized_content,
            "category": normalized_category,
            "reason": normalized_reason,
            "created_at": now_iso(),
        }
        lines = [
            "## 记忆保存建议",
            "",
            f"- 分类：{normalized_category or '未分类'}",
            f"- 内容：{normalized_content}",
        ]
        if normalized_reason:
            lines.append(f"- 原因：{normalized_reason}")
        lines.extend(["", "> 已生成待确认保存卡片，需用户点击确认后才会真正写入记忆库。"])
        return "\n".join(lines), artifact

    @tool(response_format="content_and_artifact")
    def delete_user_memory(memory_ids: str = "", content: str = "", category: str = "", reason: str = "") -> Tuple[str, Any]:
        """为当前用户生成一条待确认删除的个性化记忆建议。

        删除前应尽量先调用 query_user_memory 查看现有记忆和对应 ID。
        该工具不会直接删除数据，必须等待前端用户确认。

        参数:
        - memory_ids: 要删除的记忆 ID，可传一个或多个，多个用逗号或空格分隔
        - content: 若没有 ID，可传要删除的记忆原文进行精确匹配
        - category: 配合 content 使用时可进一步限定分类
        - reason: 删除原因，说明为什么这条记忆不该继续保留
        """
        normalized_ids = _normalize_memory_ids(memory_ids)
        normalized_content = _normalize_content(content)
        normalized_category = _normalize_category(category)
        normalized_reason = _normalize_reason(reason)

        if not user_id:
            artifact = {
                "mode": "delete_request",
                "status": "unavailable",
                "memory_ids": normalized_ids,
                "content": normalized_content,
                "category": normalized_category,
                "reason": normalized_reason,
                "items": [],
            }
            return "当前会话未绑定用户，无法删除个性化记忆。", artifact

        if not normalized_ids and not normalized_content:
            artifact = {
                "mode": "delete_request",
                "status": "invalid",
                "memory_ids": [],
                "content": normalized_content,
                "category": normalized_category,
                "reason": normalized_reason,
                "items": [],
            }
            return "删除记忆时至少需要提供记忆 ID，或提供要删除的精确内容。", artifact

        target_items: List[Dict[str, Any]] = []
        missing_ids: List[str] = []
        already_deleted_ids: List[str] = []

        if normalized_ids:
            active_items = user_memory_store.get_memories_by_ids(user_id, normalized_ids, include_inactive=False)
            all_items = user_memory_store.get_memories_by_ids(user_id, normalized_ids, include_inactive=True)
            active_map = {item["id"]: item for item in active_items}
            all_map = {item["id"]: item for item in all_items}
            for memory_id in normalized_ids:
                if memory_id in active_map:
                    target_items.append(active_map[memory_id])
                elif memory_id in all_map:
                    already_deleted_ids.append(memory_id)
                else:
                    missing_ids.append(memory_id)
        else:
            active_matches = user_memory_store.find_memories_by_content(
                user_id,
                normalized_content,
                category=normalized_category or None,
                include_inactive=False,
            )
            all_matches = user_memory_store.find_memories_by_content(
                user_id,
                normalized_content,
                category=normalized_category or None,
                include_inactive=True,
            )
            if active_matches:
                target_items.extend(active_matches)
            elif all_matches:
                already_deleted_ids.extend(item["id"] for item in all_matches)

        created_at = now_iso()
        if target_items:
            artifact = {
                "mode": "delete_request",
                "proposal_id": str(uuid4()),
                "status": "pending_confirmation",
                "memory_ids": [item["id"] for item in target_items],
                "content": normalized_content,
                "category": normalized_category,
                "reason": normalized_reason,
                "items": target_items,
                "missing_ids": missing_ids,
                "already_deleted_ids": already_deleted_ids,
                "created_at": created_at,
            }
            return _format_delete_summary(target_items, normalized_reason), artifact

        status = "already_deleted" if already_deleted_ids and not missing_ids else "not_found"
        artifact = {
            "mode": "delete_request",
            "proposal_id": str(uuid4()),
            "status": status,
            "memory_ids": normalized_ids,
            "content": normalized_content,
            "category": normalized_category,
            "reason": normalized_reason,
            "items": [],
            "missing_ids": missing_ids,
            "already_deleted_ids": already_deleted_ids,
            "created_at": created_at,
        }
        if status == "already_deleted":
            return f"这些记忆已经处于删除状态：{', '.join(already_deleted_ids)}", artifact
        if missing_ids:
            return f"未找到可删除的记忆：{', '.join(missing_ids)}", artifact
        return "没有找到可删除的已保存记忆。", artifact

    return [query_user_memory, save_user_memory, delete_user_memory]