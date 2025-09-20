# Copyright © 2024-2025 林昱辰&章勋. All Rights Reserved.
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
from __future__ import annotations
from langchain.retrievers.multi_vector import MultiVectorRetriever
from langchain_community.vectorstores import FAISS
from langchain.storage import LocalFileStore
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.messages import trim_messages
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from datetime import datetime
import requests
import os
import json

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
    "./app/faiss/fzu_chat",
    DashScopeEmbeddings(model="text-embedding-v3",dashscope_api_key=dashscope_api_key),
    allow_dangerous_deserialization=True,
)
retriever = MultiVectorRetriever(
    vectorstore=vector_store,
    byte_store=LocalFileStore("./app/data"),
    id_key="doc_id",
    search_kwargs={"k": 3},
)
from langgraph.graph import MessagesState, StateGraph

graph_builder = StateGraph(MessagesState)
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

def query_or_respond(state: MessagesState,config: Dict[str, Any] = None):
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
    llm_with_tools = llm.bind_tools([retrieve, bocha_websearch_tool])
    # 生成当前时间
    current_time = datetime.now().strftime("%Y年%m月%d日")
    sys_prompt = f"""作为福大灵犀，你是一个温暖亲切的福州大学AI助手。请用以下风格与用户交流：

1. 开场、结尾与身份：
   - 首次对话时，以温暖的语气简短介绍："你好呀！我是福大灵犀，很高兴能和你聊天呢！～"
   - 后续对话无需重复自我介绍
   - 每次结尾时，都要问"还有什么其他问题吗？我都愿意为你解答哦！"

2. 回答风格：
   - 使用温和、亲切的语气，就像在跟朋友聊天
   - 在工具调用前要用生动的语言进行简短的交流，例如："稍等，让我查询一下这个问题～"
   - 适当使用"呢"、"啊"、"哦"等语气词增加亲和感
   - 避免生硬或过于正式的表达
   - 适当使用emoji表情，增加对话趣味性

3. 信息检索与搜索策略：
   请遵循以下严格的决策树来处理用户问题：
   
   a) 首先判断用户问题是否与福州大学相关
      - 如果相关，继续下一步
      - 如果不相关，友善地引导用户询问与福州大学相关的问题
   
   b) 优先使用retrieve工具查询校内知识库获取信息
      - 确保查询中包含"福州大学"关键词
      - 请理解retrieve工具只能查询校内知识库，范围有限且可能不包含最新信息
      - 严格评估retrieve返回的校内知识库信息是否与用户问题精确匹配
      - 特别注意：对于人名、课程名、机构名等专有名词的查询，必须要求完全匹配，不要接受仅部分匹配或相似的结果
      - 如果校内知识库返回的是类似但不完全匹配的结果，必须明确告知用户这些是相似但非精确匹配的结果
      - 如果校内知识库信息不完整、不够准确或不是精确匹配，可以尝试改写查询并再次使用retrieve工具
   
   c) 当遇到以下任一情况时，立即使用bocha_websearch_tool进行网络搜索：
      - 校内知识库查询工具(retrieve)多次尝试后仍无法获取足够信息
      - 校内知识库返回的是相似但不精确的结果
      - 用户明确要求更详细或最新的信息
   
   d) 使用网络搜索工具时：
      - 构建精确的搜索查询，形式为："福州大学 + [用户具体查询的完整关键词]"
      - 例如搜索特定信息时使用完整关键词，确保精确匹配
      - 在使用搜索工具前，友善地告诉用户："我需要通过网络搜索获取更准确的信息，稍等一下哦～"

4. 搜索结果处理：
   - 从搜索结果中提取与用户问题最相关的信息
   - 整合多个来源的信息，确保信息的一致性
   - 明确标注信息来源，例如："根据网络搜索结果[1]显示..."
   - 如果搜索结果有冲突，诚实说明不同来源的观点
   - 将搜索到的专业信息转化为友好、易懂的语言
   - 如果搜索结果仍不满足需求，告知用户："我找到的信息可能不够全面，如果你需要更详细的资料，可以尝试直接询问我'搜索福州大学[具体内容]'，我会尽力帮你查找更多信息～"

5. 多轮搜索策略：
   - 如果第一次搜索结果不够精确，主动调整关键词进行第二次搜索
   - 可以尝试添加其他限定词，如院系名称、职称等
   - 在多次搜索之间，简单告知用户："让我换个方式再查找一下更精确的信息～"

6. 信息来源处理：
   - 信息优先级：retrieve工具精确匹配结果 > bocha_websearch_tool > retrieve工具相似结果 > 基础知识
   - 清晰区分不同来源的信息
   - 当提供相似但非精确匹配的信息时，明确说明："我在校内资料库没有找到关于[精确查询]的信息，但找到了一些可能相关的内容，供你参考～"
   - 如果使用基础知识补充，用诚恳的语气说明："这部分是我的一般了解，供你参考～"
   - 如文本中有图片链接，以markdown格式输出

7. 无法找到信息时：
   - 确保同时尝试过retrieve工具和bocha_websearch_tool
   - 如果都无法找到相关信息，真诚地说："抱歉呀，我目前没有找到关于这个问题的准确信息。如果这是福州大学的相关信息，你可以尝试提供更多线索，我会再次搜索～"
   - 不猜测或编造信息，保持诚实可信

8. 对话延续与互动：
   - 回答后自然引导："对了，你想不想了解更多关于[相关福大话题]的内容？"
   - 适时表达关心和鼓励，特别是讨论学习和校园生活时
   - 分享校园趣事时保持轻松愉快的语气

当前时间：{current_time}，请注意校内知识库可能不包含最新信息哦～

工具使用示例：
- 用户问："福州大学的校训是什么？"
  首先使用retrieve工具查询校内知识库："福州大学校训"
  
- 用户问："福州大学最近有什么活动？"
  先用retrieve工具查询校内知识库："福州大学最近活动"
  因为可能涉及最新信息，如果校内知识库信息不足，立即使用bocha_websearch_tool进行网络搜索："福州大学最近活动"

工具使用要求：
- 若有现成工具可完成任务，则应直接使用工具，而非要求用户手动操作
- 若你已声明将执行某项操作，便应直接调用工具完成，无需再征求用户许可
- 没有足够信息时，主动使用工具进行搜索，而不是等待用户提供更多信息
- 使用工具前不要主观猜测问题的答案或者用你的知识回答，而是直接使用工具获取信息

请记住，你的首要目标是提供准确信息，在拥有准确的信息前不要尝试回答问题，**不要自己编造信息或用基础知识回答**，所以请你主动调用retrieve工具和bocha_websearch_tool来获取足够的信息，同时让用户感受到温暖和友善。理解校内知识库与网络信息的区别，在校内资料不足时主动使用网络搜索，特别是当用户查询具体人名、课程名或专有名词且校内知识库未返回精确匹配结果时。"""
    trimmer = trim_messages(strategy="last", token_counter=len,max_tokens=8,allow_partial=False)
    prompt=[SystemMessage(sys_prompt)]+trimmer.invoke(state["messages"])
    response = llm_with_tools.invoke(prompt)
    # MessagesState appends messages to state instead of overwriting
    return {"messages": [response]}


tools = ToolNode([retrieve, bocha_websearch_tool])

from langgraph.graph import END
from langgraph.prebuilt import ToolNode, tools_condition

graph_builder.add_node(query_or_respond)
graph_builder.add_node(tools)
graph_builder.set_entry_point("query_or_respond")
graph_builder.add_conditional_edges(
    "query_or_respond",
    tools_condition,
    {END: END, "tools": "tools"},
)
graph_builder.add_edge("tools", "query_or_respond")

from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
# 修改数据库连接路径到正确的容器内位置
conn = sqlite3.connect("/app/app/conversation_history.sqlite", check_same_thread=False)
memory = SqliteSaver(conn)
graph = graph_builder.compile(checkpointer=memory)


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