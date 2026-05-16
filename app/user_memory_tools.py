from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from langchain_core.tools import tool

from .memory_store import clamp_int, extract_memory_keywords, user_memory_store


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


SENSITIVE_RE = re.compile(
    r"(密码|口令|验证码|身份证|证件号|银行卡|银行卡号|手机号|电话号码|邮箱|email|token|api[_ -]?key|secret|cookie|session|准考证)",
    re.I,
)
SENSITIVE_VALUE_RE = re.compile(
    r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|1[3-9]\d{9}|\b\d{17}[\dXx]\b|sk-[A-Za-z0-9_-]{20,})"
)
EPHEMERAL_RE = re.compile(r"(今天|明天|后天|今晚|本周|这周|下周|刚才|临时|这次|本次|现在|马上|稍后|待会儿|当前这)")
DURABLE_RE = re.compile(
    r"(以后|长期|总是|默认|每次|习惯|偏好|喜欢|不喜欢|不吃|不喝|讨厌|希望你|请叫我|叫我|称呼|回答风格|输出风格|目标|计划|规划|优先|倾向|推荐|展示|格式)",
    re.I,
)
FZU_EDU_FACT_RE = re.compile(
    r"(绩点|成绩|排名|学分|课表|考试安排|考场|选课结果|已选课程|候选课程|校历|培养方案|学生信息|学号|学院|专业|班级|年级|入学年份|教务)",
    re.I,
)
FZU_IDENTITY_FACT_RE = re.compile(r"(我是|我在|我的).{0,12}(学院|专业|班级|年级|学号|入学年份)")
FZU_PREFERENCE_RE = re.compile(r"(偏好|习惯|默认|每次|以后|优先|倾向|推荐|筛选|展示|格式|提醒|规划|目标|希望|不想|不喜欢|喜欢)")
STABLE_CATEGORIES = {
    "称呼偏好",
    "输出风格",
    "表达风格",
    "餐饮偏好",
    "校区偏好",
    "校园生活偏好",
    "学习目标",
    "学业规划",
    "课程偏好",
    "选课偏好",
    "教务查询偏好",
    "时间展示偏好",
    "使用习惯",
    "长期偏好",
    "沟通偏好",
}
FZU_TRANSIENT_CATEGORIES = {
    "成绩",
    "绩点",
    "排名",
    "课表",
    "考场",
    "考试安排",
    "选课结果",
    "学生信息",
    "教务数据",
    "培养方案",
    "校历",
}
CATEGORY_ALIASES = {
    "饮食偏好": "餐饮偏好",
    "食堂偏好": "餐饮偏好",
    "校内餐饮": "餐饮偏好",
    "宿舍偏好": "校园生活偏好",
    "校园偏好": "校园生活偏好",
    "学习偏好": "学业规划",
    "学习规划": "学业规划",
    "学业目标": "学业规划",
    "课程推荐偏好": "课程偏好",
    "选课推荐": "选课偏好",
    "选课策略": "选课偏好",
    "查教务偏好": "教务查询偏好",
    "教务偏好": "教务查询偏好",
    "课表展示偏好": "时间展示偏好",
}


def _clean_text(value: str, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _normalize_category(value: str) -> str:
    category = str(value or "").strip()[:40]
    return CATEGORY_ALIASES.get(category, category)


def _normalize_reason(value: str) -> str:
    return str(value or "").strip()[:200]


def _normalize_content(value: str) -> str:
    return str(value or "").strip()[:300]


def _normalize_importance(value: int | str | None, default: int = 50) -> int:
    return clamp_int(value, default, 1, 100)


def _normalize_memory_ids(value: str) -> List[str]:
    if not value:
        return []
    tokens = [token.strip() for token in re.split(r"[\s,，]+", str(value))]
    return [token for token in dict.fromkeys(tokens) if token]


def _validate_memory_candidate(content: str, category: str, reason: str) -> Tuple[bool, str]:
    text = " ".join(part for part in (content, category, reason) if part)
    if len(content.strip()) < 4:
        return False, "内容过短，无法形成稳定的长期记忆。"
    if SENSITIVE_RE.search(text) or SENSITIVE_VALUE_RE.search(text):
        return False, "内容包含敏感信息，不适合保存为长期记忆。"
    if category in FZU_TRANSIENT_CATEGORIES:
        return False, "这类教务事实应通过福大教务工具实时查询，不适合保存为长期记忆。"
    if FZU_IDENTITY_FACT_RE.search(text):
        return False, "学院、专业、班级、年级、学号等身份事实应以教务系统为准；如需保存，请改写为不含身份事实的长期偏好。"
    if FZU_EDU_FACT_RE.search(text) and not FZU_PREFERENCE_RE.search(text):
        return False, "成绩、课表、考场、选课结果等教务事实会变化，应实时查询教务系统而不是写入长期记忆。"
    has_durable_signal = bool(DURABLE_RE.search(text)) or category in STABLE_CATEGORIES
    has_ephemeral_signal = bool(EPHEMERAL_RE.search(text))
    if has_ephemeral_signal and not has_durable_signal:
        return False, "内容更像临时状态或一次性需求，不适合保存为长期记忆。"
    if not has_durable_signal and len(content) < 12:
        return False, "缺少长期稳定或未来可复用的信号。"
    return True, ""


def _estimate_importance(content: str, category: str, reason: str, requested: int | str | None = None) -> int:
    if requested not in (None, "", 0, "0"):
        return _normalize_importance(requested)

    text = " ".join(part for part in (content, category, reason) if part)
    score = 50
    if category in STABLE_CATEGORIES:
        score += 10
    if category in {"称呼偏好", "输出风格", "表达风格", "餐饮偏好", "校区偏好", "选课偏好", "教务查询偏好"}:
        score += 8
    if re.search(r"(默认|每次|总是|以后|长期)", text):
        score += 14
    if re.search(r"(不喜欢|喜欢|不吃|不喝|习惯|偏好|请叫我|叫我)", text):
        score += 10
    if re.search(r"(选课|课程|课表|成绩|绩点|学分|考场|校历)", text) and FZU_PREFERENCE_RE.search(text):
        score += 8
    if re.search(r"(临时|今天|明天|这次|本次)", text):
        score -= 18
    return _normalize_importance(score)


def _format_memory_summary(items: List[Dict[str, Any]], query: str, category: str) -> str:
    lines = ["## 个性化记忆", ""]
    if query:
        lines.append(f"- 查询：{query}")
    if category:
        lines.append(f"- 分类：{category}")
    lines.append(f"- 命中：{len(items)} 条")
    lines.append("- 排序：相关性、重要度、最近使用与更新时间综合排序")
    lines.append("")
    for index, item in enumerate(items, start=1):
        category = item.get("category") or "未分类"
        lines.append(f"{index}. ID: {item.get('id')}")
        lines.append(f"   - 分类：{category}")
        lines.append(f"   - 内容：{item.get('content')}")
        if item.get("score") is not None:
            lines.append(f"   - 匹配分：{item.get('score')}")
        lines.append(f"   - 重要度：{item.get('importance', 50)}/100")
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

        适用于称呼偏好、长期习惯、餐饮禁忌、学习目标、输出风格、选课/课程推荐偏好、教务查询展示偏好等长期稳定信息。
        参数:
        - query: 想检索的偏好或背景关键词，例如“称呼偏好”“餐饮禁忌”“输出风格”“选课偏好”
        - category: 可选，限制记忆分类，例如“餐饮偏好”“输出风格”“教务查询偏好”
        - limit: 返回数量上限，建议在需要管理全部记忆时适当调大
        """
        normalized_category = _normalize_category(category)
        safe_limit = max(1, min(int(limit), 50))
        if not user_id:
            artifact = {"mode": "list", "query": query, "category": normalized_category, "items": []}
            return "当前会话未绑定用户，无法查询个性化记忆。", artifact

        items = user_memory_store.search_memories(user_id, query=query, category=normalized_category, limit=safe_limit)
        artifact = {
            "mode": "list",
            "query": query,
            "category": normalized_category,
            "ranking": "relevance_importance_usage_recency",
            "items": items,
        }
        if not items:
            return "当前还没有可用的个性化记忆。", artifact
        return _format_memory_summary(items, query, normalized_category), artifact

    @tool(response_format="content_and_artifact")
    def save_user_memory(content: str, category: str = "", reason: str = "", importance: int = 0) -> Tuple[str, Any]:
        """为当前用户生成一条待确认保存的个性化记忆建议。

        仅适用于长期稳定、未来对回答有帮助的信息。该工具不会直接写入数据库，必须等待前端用户确认。
        不要用于保存密码、证件号、临时安排、一次性情绪或其他敏感信息。

        参数:
        - content: 要记住的核心内容，例如“用户不吃香菜”
        - category: 记忆类别，例如“餐饮偏好”“表达风格”“选课偏好”“教务查询偏好”
        - reason: 保存原因，说明为什么这条记忆未来有用
        - importance: 可选，1-100 的重要度；不确定时留空或传 0，由系统自动估算
        """
        if not user_id:
            artifact = {"mode": "save_request", "status": "unavailable", "content": content, "category": category, "reason": reason}
            return "当前会话未绑定用户，无法保存个性化记忆。", artifact

        normalized_content = _normalize_content(content)
        normalized_category = _normalize_category(category)
        normalized_reason = _normalize_reason(reason)
        safe_importance = _estimate_importance(normalized_content, normalized_category, normalized_reason, importance)
        if not normalized_content:
            artifact = {"mode": "save_request", "status": "invalid", "content": content, "category": category, "reason": reason}
            return "要保存的记忆内容不能为空。", artifact

        is_valid, invalid_reason = _validate_memory_candidate(normalized_content, normalized_category, normalized_reason)
        if not is_valid:
            artifact = {
                "mode": "save_request",
                "proposal_id": str(uuid4()),
                "status": "invalid",
                "content": normalized_content,
                "category": normalized_category,
                "reason": normalized_reason,
                "importance": safe_importance,
                "validation": invalid_reason,
                "created_at": now_iso(),
            }
            return f"这条内容不适合保存为长期个性化记忆：{invalid_reason}", artifact

        existing = user_memory_store.find_similar_memory(user_id, normalized_content, normalized_category)
        if existing is not None:
            artifact = {
                "mode": "save_request",
                "proposal_id": str(uuid4()),
                "status": "already_saved",
                "content": normalized_content,
                "category": normalized_category,
                "reason": normalized_reason,
                "importance": safe_importance,
                "keywords": extract_memory_keywords(normalized_content, normalized_category, normalized_reason),
                "created_at": now_iso(),
                "saved_memory": existing,
                "memory_id": existing["id"],
                "duplicate_similarity": existing.get("similarity", 1.0),
            }
            return "相似的个性化记忆已经存在，无需再次保存。", artifact

        artifact = {
            "mode": "save_request",
            "proposal_id": str(uuid4()),
            "status": "pending_confirmation",
            "content": normalized_content,
            "category": normalized_category,
            "reason": normalized_reason,
            "importance": safe_importance,
            "keywords": extract_memory_keywords(normalized_content, normalized_category, normalized_reason),
            "created_at": now_iso(),
        }
        lines = [
            "## 记忆保存建议",
            "",
            f"- 分类：{normalized_category or '未分类'}",
            f"- 内容：{normalized_content}",
            f"- 重要度：{safe_importance}/100",
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
            else:
                similar = user_memory_store.find_similar_memory(
                    user_id,
                    normalized_content,
                    normalized_category,
                    threshold=0.78,
                    include_inactive=False,
                )
                if similar is not None:
                    target_items.append(similar)

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
