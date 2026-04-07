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
from datetime import datetime
import os
from pathlib import Path
import re
import requests
from typing import Any, Dict, List
from urllib.parse import urlparse

from langchain_classic.retrievers.multi_vector import MultiVectorRetriever
from langchain_classic.storage import LocalFileStore
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.messages import SystemMessage, ToolMessage, trim_messages
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from .security_utils import ensure_private_dir, ensure_private_file, env_flag

BASE_DIR = Path(__file__).resolve().parent
FAISS_DIR = BASE_DIR / "faiss" / "fzu_chat"
DATA_DIR = BASE_DIR / "data"
CHECKPOINT_PATH = Path(
    os.getenv("FZU_CHAT_CHECKPOINT_PATH", str(BASE_DIR / "conversation_history.sqlite"))
)
HUAWEICLOUD_OPENAI_BASE_URL = os.getenv(
    "HUAWEICLOUD_OPENAI_BASE_URL",
    "https://api.modelarts-maas.com/openai/v1",
)
DEFAULT_CHAT_MODEL = "glm-5"
SECONDARY_CHAT_MODEL = "deepseek-v3.2"
TITLE_SUMMARY_MODEL = "qwen3-32b"
CHAT_MODEL_OPTIONS = {
    DEFAULT_CHAT_MODEL: "GLM-5",
    SECONDARY_CHAT_MODEL: "DeepSeek V3.2",
}
SEARCH_RESULT_TOOL_NAMES = {"retrieve", "bocha_websearch_tool"}
SEARCH_RESULT_CITATION_RE = re.compile(r"^\[(\d+)\]$")
SEARCH_RESULT_INLINE_CITATION_RE = re.compile(r"\[(\d+)\](?!\()")
SEARCH_CITATION_COUNTER: ContextVar[int] = ContextVar("search_citation_counter", default=0)
MAX_HISTORY_MESSAGES = 32


def reset_search_citation_counter() -> None:
    SEARCH_CITATION_COUNTER.set(0)


def next_search_citation_id() -> int:
    citation_id = SEARCH_CITATION_COUNTER.get() + 1
    SEARCH_CITATION_COUNTER.set(citation_id)
    return citation_id


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


def read_secret_or_env(secret_path: str, *env_names: str) -> str | None:
    if os.path.exists(secret_path):
        with open(secret_path, "r") as secret_file:
            secret_value = secret_file.read().strip()
            if secret_value:
                return secret_value
    for env_name in env_names:
        env_value = os.getenv(env_name)
        if env_value:
            return env_value.strip()
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


def build_chat_llm(
    model_name: str,
    *,
    temperature: float,
    streaming: bool,
    stop: List[str] | None = None,
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
        init_kwargs["model_kwargs"] = {"stop": stop}
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

def _build_query_or_respond(edu_tools, user_memory_tools):
    def query_or_respond(state: MessagesState, config: RunnableConfig | None = None):
        """Generate tool call for retrieval or respond."""
        config = config or {}
        configurable = config.get("configurable", {})
        model_name = configurable.get("model", DEFAULT_CHAT_MODEL)
        llm = build_chat_llm(
            model_name,
            temperature=0.4,
            streaming=True,
            stop=["请用以下风格与用户交流"],
        )
        all_tools = [retrieve, bocha_websearch_tool] + edu_tools + user_memory_tools
        llm_with_tools = llm.bind_tools(all_tools)
        now = datetime.now()
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        current_time = f"{now.strftime('%Y年%m月%d日')} {weekday_names[now.weekday()]}"
        sys_prompt = f"""作为福大灵犀，你是一个温暖亲切的福州大学AI助手。请用以下风格与用户交流：

1. 开场、结尾与身份：
    - 首次对话时，以温暖的语气简短介绍："你好呀！我是福大灵犀，很高兴能和你聊天呢！～"
    - 后续对话无需重复自我介绍
    - 不要在每次回答末尾机械重复固定结束语；只有在自然合适时，再简短追问下一步需求

2. 回答风格：
    - 使用温和、亲切但简洁的语气
    - 在工具调用前只用一句短提示，不要连续寒暄
    - 避免生硬或过于正式的表达
    - 工具型回复默认不使用 emoji，除非用户明显偏好这种风格
    - 对工具结果，优先直接给出结论和结构化信息，不要把同一信息先口语复述一遍、再列表重复一遍

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
    当用户询问自己的成绩、绩点、排名、学分、课表、选课、考场、个人信息、等级考试成绩、校历、培养方案等教务相关问题时，优先使用这些工具。
    如果工具返回"尚未登录教务系统"，请友善地提醒用户先在侧边栏登录教务系统。
    当工具已经返回结构化结果时：
    - 直接基于工具结果整理回答，保留关键字段，不要改写关键数字
    - 优先使用 markdown 列表或表格
    - 删除寒暄、重复总结、重复状态描述
    - 不要重复抄写工具卡片中已经明显展示的同一批字段
        对于 select_course：
        - 只有当用户明确要求“帮我选/提交某门课”时才调用
        - 必须拿到明确的选课类别和准确课程名；若同名课程可能有多门，还应补充教师信息
        - 如果用户只是询问“现在有什么可以选”或“我还差什么课”，先调用 query_course_selection，不要直接提交选课

3.1 个性化记忆工具：
    你拥有以下用户个性化记忆工具：
    - query_user_memory: 查询当前用户已确认保存的长期偏好、背景和习惯，也可在 query 为空时列出最近保存的全部记忆
    - save_user_memory: 生成一条待确认保存的记忆建议，只有用户在前端卡片点击确认后才会真正写入数据库
    - delete_user_memory: 生成一条待确认删除的记忆建议，只有用户在前端卡片点击确认后才会真正删除

    使用规则：
    - 当回答明显依赖用户的长期偏好、称呼、饮食习惯、学习目标、输出风格或其他稳定背景时，可先调用 query_user_memory
    - 当用户要求“看看你记住了什么”“管理/删除记忆”“忘掉某条偏好”等需求时，应先调用 query_user_memory 查看现有记忆及其 ID，再按需调用 delete_user_memory
    - 只有当用户在对话中明确表达了长期稳定、未来复用价值高的信息时，才调用 save_user_memory
    - 不要保存临时安排、一次性需求、短期情绪、教务账号密码、证件号、手机号、邮箱等敏感或易变信息
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

当前时间：{current_time}。1-4节在上午，5-8节在下午，9-11节在晚上。请注意校内知识库可能不包含最新信息哦～

工具使用要求：
- 若有现成工具可完成任务，则应直接使用工具，而非要求用户手动操作
- 若你已声明将执行某项操作，便应直接调用工具完成，无需再征求用户许可
- 使用工具前不要主观猜测问题的答案，而是直接使用工具获取信息
- **不要自己编造信息或用基础知识回答**"""
        prompt = trim_messages(
            [SystemMessage(sys_prompt), *state["messages"]],
            max_tokens=MAX_HISTORY_MESSAGES,
            token_counter=len,
            strategy="last",
            allow_partial=False,
            start_on="human",
            end_on=("human", "tool"),
            include_system=True,
        )
        response = llm_with_tools.invoke(prompt)
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
    from .edu_tools import build_edu_tools
    from .user_memory_tools import build_user_memory_tools

    edu_tools = build_edu_tools(edu_session)
    user_memory_tools = build_user_memory_tools(edu_session)
    query_or_respond = _build_query_or_respond(edu_tools, user_memory_tools)
    raw_tools = ToolNode([retrieve, bocha_websearch_tool] + edu_tools + user_memory_tools)

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


prompt = "请概括用户的问题作为对话的标题，标题需要简短概括，不多于20个字。注意你的输出直接作为标题，所以不要有其他输出，不要输出标题二字。请输出标题"
summary_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", prompt),
        ("human", "{input}"),
    ]
)
summary_chain = (
    summary_prompt
    | build_chat_llm(TITLE_SUMMARY_MODEL, temperature=0.3, streaming=False)
    | StrOutputParser()
)
