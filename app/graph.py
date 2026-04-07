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
from langchain_classic.retrievers.multi_vector import MultiVectorRetriever
from langchain_community.vectorstores import FAISS
from langchain_classic.storage import LocalFileStore
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.messages import trim_messages
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableConfig
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from datetime import datetime
import requests
import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
FAISS_DIR = BASE_DIR / "faiss" / "fzu_chat"
DATA_DIR = BASE_DIR / "data"
CHECKPOINT_PATH = Path(
    os.getenv("FZU_CHAT_CHECKPOINT_PATH", str(BASE_DIR / "conversation_history.sqlite"))
)

def get_langsmith_api_key():
    """从Docker Secret或环境变量获取API密钥"""
    secret_path = "/run/secrets/langsmith_api_key"
    if os.path.exists(secret_path):
        with open(secret_path, "r") as f:
            return f.read().strip()
    return os.getenv("LANGSMITH_API_KEY")
LANGSMITH_API_KEY = get_langsmith_api_key()
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY
LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
if not LANGSMITH_API_KEY:
    raise ValueError("Langsmith API密钥未设置")

def get_dashscope_api_key():
    """从Docker Secret或环境变量获取API密钥"""
    secret_path = "/run/secrets/dashscope_api_key"
    if os.path.exists(secret_path):
        with open(secret_path, "r") as f:
            return f.read().strip()
    return os.getenv("DASHSCOPE_API_KEY")
dashscope_api_key = get_dashscope_api_key()

if not dashscope_api_key:
    raise ValueError("DashScope API密钥未设置")

def get_deepseek_api_key():
    """从Docker Secret或环境变量获取API密钥"""
    secret_path = "/run/secrets/deepseek_api_key"
    if os.path.exists(secret_path):
        with open(secret_path, "r") as f:
            return f.read().strip()
    return os.getenv("DEEPSEEK_API_KEY")
deepseek_api_key = get_deepseek_api_key()

if not deepseek_api_key:
    raise ValueError("DeepSeek API密钥未设置")

def get_qianfan_api_key():
    """从Docker Secret或环境变量获取API密钥"""
    secret_path = "/run/secrets/qianfan_api_key"
    if os.path.exists(secret_path):
        with open(secret_path, "r") as f:
            return f.read().strip()
    return os.getenv("QIANFAN_API_KEY")
qianfan_api_key = get_qianfan_api_key()
if not qianfan_api_key:
    raise ValueError("Qianfan API密钥未设置")

def get_bocha_api_key():
    """从Docker Secret或环境变量获取API密钥"""
    secret_path = "/run/secrets/bocha_api_key"
    if os.path.exists(secret_path):
        with open(secret_path, "r") as f:
            return f.read().strip()
    return os.getenv("BOCHA_API_KEY")
BOCHA_API_KEY= get_bocha_api_key()

if not BOCHA_API_KEY:
    raise ValueError("Bocha API密钥未设置")

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
from langgraph.graph import MessagesState, StateGraph
from langchain_core.tools import tool

@tool(response_format="content_and_artifact")
def bocha_websearch_tool(query: str,freshness: str) -> tuple[str, any]:
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
            formatted_results = ""
            for idx, page in enumerate(webpages, start=1):
                formatted_results += (
                    f"引用: {idx}\n"
                    f"标题: {page['name']}\n"
                    f"URL: {page['url']}\n"
                    f"摘要: {page['summary']}\n"
                    f"网站名称: {page['siteName']}\n"
                    f"发布时间: {page['dateLastCrawled']}\n\n"
                )
            return formatted_results.strip(), webpages
        except Exception as e:
            return f"搜索API请求失败，原因是：搜索结果解析失败 {str(e)}", None
    else:
        return f"搜索API请求失败，状态码: {response.status_code}, 错误信息: {response.text}", None


@tool(response_format="content_and_artifact")
def retrieve(query: str):
    """从校内知识库返回**可能**和查询语句(query)相关的有关福州大学信息的文档片段，查询语句需要包含福州大学，并且查询中只能包含一个问题，注意：检索到的信息可能不完整、被截断或和query不相关，必须判断返回的信息是否和query相关后再使用。"""
    retrieved_docs = retriever.invoke(query)
    serialized = "\n\n".join(
        (f"Source ID: {i+1}\nArticle url: {doc.metadata['source']}\nArticle Snippet:\n{doc.page_content}")
        for i ,doc in enumerate(retrieved_docs)
    )
    return serialized, retrieved_docs

from langchain_core.messages import SystemMessage
from langgraph.prebuilt import ToolNode
from langchain_community.chat_models import ChatTongyi

from typing import (
    Any,
    Dict,
    Iterator,
    List,
    Optional,

)

from langchain_core.callbacks import (
    CallbackManagerForLLMRun,
)

from langchain_core.messages import (
    BaseMessage,
    SystemMessage,

)

from langchain_core.outputs import (
    ChatGenerationChunk,
)


from langchain_community.llms.tongyi import (
    generate_with_last_element_mark,
)


class CustomChatTongyi(ChatTongyi):
    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        params: Dict[str, Any] = self._invocation_params(
            messages=messages, stop=stop, stream=True, **kwargs
        )

        for stream_resp, is_last_chunk in generate_with_last_element_mark(
            self.stream_completion_with_retry(**params)
        ):
            choice = stream_resp["output"]["choices"][0]
            message = choice["message"]
            if (
                choice["finish_reason"] == "null"
                and message["content"] == ""
                and message.get("reasoning_content", "") == "" #修改
                and "tool_calls" not in message
            ):
                continue

            chunk = ChatGenerationChunk(
                **self._chat_generation_from_qwen_resp(
                    stream_resp, is_chunk=True, is_last_chunk=is_last_chunk
                )
            )
            if run_manager:
                run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk

    def subtract_client_response(self, resp: Any, prev_resp: Any) -> Any:
        """Subtract prev response from curr response with safer handling of function fields"""
        resp_copy = json.loads(json.dumps(resp))
        choice = resp_copy["output"]["choices"][0]
        message = choice["message"]

        prev_resp_copy = json.loads(json.dumps(prev_resp))
        prev_choice = prev_resp_copy["output"]["choices"][0]
        prev_message = prev_choice["message"]

        message["content"] = message["content"].replace(prev_message["content"], "")

        if message.get("tool_calls"):
            for index, tool_call in enumerate(message["tool_calls"]):
                if "function" in tool_call:
                    function = tool_call["function"]
                    
                    # 确保function字典中有name字段
                    if "name" not in function:
                        function["name"] = ""
                    
                    if prev_message.get("tool_calls") and index < len(prev_message["tool_calls"]):
                        prev_tool_call = prev_message["tool_calls"][index]
                        if "function" in prev_tool_call:
                            prev_function = prev_tool_call["function"]
                            
                            # 安全获取prev_function中的name
                            prev_name = prev_function.get("name", "")
                            function["name"] = function["name"].replace(prev_name, "")
                            
                            # 同样安全处理arguments
                            if "arguments" in function and "arguments" in prev_function:
                                function["arguments"] = function["arguments"].replace(
                                    prev_function["arguments"], ""
                                )

        return resp_copy
    
# llm = CustomChatTongyi(model="qwen-max-latest", temperature=0.4, streaming=True,dashscope_api_key=dashscope_api_key,    model_kwargs={
#         "enable_thinking": False,
#         "stop": "请用以下风格与用户交流"
#     })

def _build_query_or_respond(edu_tools, user_memory_tools):
    def query_or_respond(state: MessagesState, config: RunnableConfig | None = None):
        """Generate tool call for retrieval or respond."""
        config = config or {}
        configurable = config.get("configurable", {})
        model_name = configurable.get("model", "qwen-max-latest")
        if model_name == "deepseek-chat":
            llm = ChatDeepSeek(
                model="deepseek-chat",
                temperature=0.4,
                streaming=True,
                api_key=deepseek_api_key,
                model_kwargs={
                    "stop": "请用以下风格与用户交流"
                }
            )
        elif model_name == "ERNIE-4.5-Turbo-32K":
            llm = ChatOpenAI(
                model="ernie-4.5-turbo-32k",
                temperature=0.4,
                streaming=True,
                api_key=qianfan_api_key,
                model_kwargs={
                    "stop": ["请用以下风格与用户交流"]
                },
                base_url="https://qianfan.baidubce.com/v2"
            )
        else:
            llm = CustomChatTongyi(
                model=model_name,
                temperature=0.4,
                streaming=True,
                dashscope_api_key=dashscope_api_key,
                model_kwargs={
                    "enable_thinking": False,
                    "stop": "请用以下风格与用户交流"
                }
            )
        all_tools = [retrieve, bocha_websearch_tool] + edu_tools + user_memory_tools
        llm_with_tools = llm.bind_tools(all_tools)
        current_time = datetime.now().strftime("%Y年%m月%d日")
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

当前时间：{current_time}，请注意校内知识库可能不包含最新信息哦～

工具使用要求：
- 若有现成工具可完成任务，则应直接使用工具，而非要求用户手动操作
- 若你已声明将执行某项操作，便应直接调用工具完成，无需再征求用户许可
- 使用工具前不要主观猜测问题的答案，而是直接使用工具获取信息
- **不要自己编造信息或用基础知识回答**"""
        trimmer = trim_messages(strategy="last", token_counter=len,max_tokens=8,allow_partial=False)
        prompt = [SystemMessage(sys_prompt)] + trimmer.invoke(state["messages"])
        response = llm_with_tools.invoke(prompt)
        return {"messages": [response]}

    return query_or_respond


from langgraph.graph import END
from langgraph.prebuilt import ToolNode, tools_condition

from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(str(CHECKPOINT_PATH), check_same_thread=False)
memory = SqliteSaver(conn)


def build_graph(edu_session: Dict[str, Any] | None = None, use_checkpointer: bool = True):
    from .edu_tools import build_edu_tools
    from .user_memory_tools import build_user_memory_tools

    edu_tools = build_edu_tools(edu_session)
    user_memory_tools = build_user_memory_tools(edu_session)
    query_or_respond = _build_query_or_respond(edu_tools, user_memory_tools)
    tools = ToolNode([retrieve, bocha_websearch_tool] + edu_tools + user_memory_tools)
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
    | ChatTongyi(model="qwen-turbo-latest", temperature=0.3, dashscope_api_key=dashscope_api_key)
    | StrOutputParser()
)
