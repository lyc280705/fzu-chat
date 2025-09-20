# Copyright © 2024-2025 林昱辰&袁浩. All Rights Reserved.
# 
# 福大灵犀 - 基于LangGraph和Streamlit的福州大学智能问答系统
# 
# 本代码仅供教育和学习目的使用。未经许可，禁止复制、修改、分发或用于商业目的。
# 
# 此部分代码作者: 林昱辰&袁浩
# 电子邮箱: 102304226@fzu.edu.cn
# 最后修改: 2025年6月7日
import streamlit as st
import base64
import uuid
import re
import asyncio
from graph import graph
from graph import summary_chain
from datetime import datetime
import pytz

api_summary = summary_chain 

# 页面配置
st.set_page_config(page_title="福大灵犀", layout="wide", page_icon="app/png/FZU.png", menu_items={"About": "福大灵犀，福州大学的智能问答系统。"})

@st.cache_data
def get_image_base64(image_path):
    with open(f"{image_path}", "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")

@st.cache_resource
def get_avatar(avatar_path):
    return avatar_path
def initialize_session_state():
    """初始化会话状态，确保只初始化一次"""
    if "initialized" not in st.session_state:
        st.session_state.conversations = {}
        st.session_state.initialized = True
        st.session_state.selected_conversation = None
        st.session_state.conversation_count = 0  # 添加计数器
        st.session_state.selected_model = "qwen-max-latest"
        st.session_state.model_switched = False
        st.session_state.model_switch_message = "" 
        create_new_conversation()

# 从工具消息中提取URLs
def extract_urls_from_tool_message(content):
    urls = []
    
    # 处理retrieve工具返回的格式
    for line in content.split('\n'):
        if line.startswith("Article url:"):
            urls.append(line.replace("Article url:", "").strip())
    
    # 处理bocha_websearch_tool返回的格式
    url_pattern = re.compile(r"URL: (https?://\S+)")
    url_matches = url_pattern.findall(content)
    for url in url_matches:
        if url not in urls:
            urls.append(url)
            
    return urls

# 改进工具调用ID匹配函数
def is_same_tool_call(id1, id2):
    """更精确地匹配工具调用ID"""
    if not id1 or not id2:
        return False
    # 清理两个ID以便比较
    clean_id1 = clean_tool_call_id(id1)
    clean_id2 = clean_tool_call_id(id2)
    # 检查一个ID是否是另一个的子串，或者它们是否相等
    return (clean_id1 == clean_id2 or 
            (len(clean_id1) >= 5 and len(clean_id2) >= 5 and 
             (clean_id1.startswith(clean_id2) or clean_id2.startswith(clean_id1))))

# 清理工具调用ID（移除可能的重复部分）
def clean_tool_call_id(tool_call_id):
    if not tool_call_id:
        return ""
    # 处理可能重复的ID
    if tool_call_id.startswith("call_"):
        base_id = tool_call_id[:22]  # 取前22个字符作为基础ID
        return base_id
    return tool_call_id

# 合并不完整的工具调用参数
def combine_tool_calls(message_chunk):
    """合并可能被分割的工具调用参数"""
    if not hasattr(message_chunk, 'tool_calls') or not message_chunk.tool_calls:
        return message_chunk
    
    for tc in message_chunk.tool_calls:
        if isinstance(tc, dict) and tc.get('name') == 'retrieve':
            # 检查args参数是否是有效的JSON
            args = tc.get('args', {})
            if isinstance(args, dict) and 'query' in args:
                # 如果已经是完整的dict结构，不需处理
                continue
            
            # 尝试修复不完整的JSON字符串
            if isinstance(tc.get('args'), str) and tc.get('args').startswith('{"query":"'):
                # 提取查询内容，直接设置为正确格式
                query_text = tc.get('args').replace('{"query":"', '').rstrip('"}')
                tc['args'] = {'query': query_text}
    
    return message_chunk

def create_new_conversation():
    """创建新对话"""
    new_convo = "新对话"
    st.session_state.conversation_count += 1
    conversation_id = f"conversation_{st.session_state.conversation_count}"
    thread_id = str(uuid.uuid4())  # 添加thread_id用于graph调用
    
    # 创建新对话
    st.session_state.conversations[new_convo] = {
        "messages": [
            {
                "role": "assistant",
                "content": "您好，我是福大灵犀，请问有什么可以帮助您的吗？",
                "avatar": "app/png/FZU.png",
                "timestamp": datetime.now(pytz.timezone('Asia/Shanghai')),
                "citations": {},
                "type": "text"  # 添加类型标识
            }
        ],
        "thread_id": thread_id,  # 使用thread_id替代session_id
        "citations": {},
        "created_at": datetime.now(pytz.timezone('Asia/Shanghai')),
        "conversation_id": conversation_id
    }
    st.session_state.selected_conversation = new_convo
    return conversation_id
# 添加这个包装函数
def asyncio_coroutine_wrapper(coroutine):
    """包装异步协程以便在Streamlit中安全运行"""
    try:
        # 创建新的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coroutine)
    finally:
        # 关闭循环
        loop.close()
async def summarize_and_create_new_conversation():
    # 获取当前对话
    current_conversation = st.session_state.conversations.get(
        st.session_state.selected_conversation
    )
    
    if current_conversation and len(current_conversation["messages"]) > 1:
        # 提取对话内容用于生成摘要 - 修改这部分处理消息
        messages_text = "\n".join([
            f"{msg['role']}: {msg.get('content', '') if 'content' in msg else get_message_content(msg)}" 
            for msg in current_conversation["messages"]
        ])
        
        try:
            # 调用摘要API生成标题
            summary = await api_summary.ainvoke({"input": messages_text})
            new_title = summary[:20]  # 限制标题长度
            
            # 将当前对话重命名为摘要标题（如果当前是"新对话"的话）
            if st.session_state.selected_conversation == "新对话":
                st.session_state.conversations[new_title] = current_conversation
                del st.session_state.conversations[st.session_state.selected_conversation]
            
        except Exception as e:
            new_title = f"对话 {len(st.session_state.conversations)}"
            if st.session_state.selected_conversation == "新对话":
                st.session_state.conversations[new_title] = current_conversation
                del st.session_state.conversations[st.session_state.selected_conversation]
    
    # 创建新的对话，保留现有对话
    create_new_conversation()

# 帮助函数用于从复杂消息中提取内容
def get_message_content(message):
    """从可能有parts的消息中获取内容"""
    if "content" in message:
        return message["content"]
    elif "parts" in message:
        # 从parts中提取文本内容
        text_parts = [part["content"] for part in message["parts"] 
                     if part["type"] == "text" and "content" in part]
        return " ".join(text_parts)
    return ""  # 如果没有内容，返回空字符串
def display_sidebar_ui():
    with st.sidebar:
        image_base64 = get_image_base64("app/png/FZU.png")
        st.markdown(
            f"""
            <div style="display: flex; align-items: center;">
                <img src="data:image/png;base64,{image_base64}" style="width: 50px; height: 50px;">
                <h1 style="margin-left: 10px;">福大灵犀</h1>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.subheader("2024-FZU-SRTP")
        
        # 模型选择
        with st.container():
            model_options = {
                "qwen-max-latest": "通义千问Max(默认)",
                "deepseek-chat":"DeepSeek-V3-0324",
                "ERNIE-4.5-Turbo-32K": "文心一言4.5-Turbo",
                "Moonshot-Kimi-K2-Instruct": "月暗之面Kimi-K2-Instruct",
            }
            model_keys = list(model_options.keys())
            current_index = model_keys.index(st.session_state.selected_model) if st.session_state.selected_model in model_keys else 0
            selected_model = st.selectbox(
                "选择对话模型\n(非默认模型未经广泛测试，仅供选择)",
                options=list(model_options.keys()),
                format_func=lambda x: model_options[x],
                index=current_index,
                key="model_selector"
            )
            # 更新模型选择
            if selected_model != st.session_state.selected_model:
                st.session_state.model_switch_message = f"已切换至 {model_options[selected_model]} 模型"
                st.session_state.model_switched = True
                # 更新选择的模型
                st.session_state.selected_model = selected_model
                # 重载页面
                st.rerun()
                
        # 操作按钮区
        with st.container():
            st.markdown("### 💡 操作菜单")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✨ 新对话", type="primary", use_container_width=True):
                    asyncio_coroutine_wrapper(summarize_and_create_new_conversation())
                    st.rerun()
            with col2:
                if st.button("🗑️ 清空", type="secondary", use_container_width=True):
                    st.session_state.conversations = {}
                    st.session_state.initialized = False
                    st.session_state.selected_conversation = None
                    create_new_conversation()
                    st.rerun()
        
        # 对话列表
        with st.container():
            st.markdown(
                """
                <h3 style='margin: 0; font-size: 1.1em;'>💬 对话列表</h3>
                """, 
                unsafe_allow_html=True
            )
            
            for convo in st.session_state.conversations.keys():
                cols = st.columns([6, 1])
                with cols[0]:
                    is_selected = st.session_state.selected_conversation == convo
                    if st.button(
                        convo,
                        key=f"convo_{convo}",
                        type="primary" if is_selected else "secondary",
                        use_container_width=True,
                    ):
                        st.session_state.selected_conversation = convo
                        st.rerun()
                
                with cols[1]:
                    if len(st.session_state.conversations) > 1:
                        if st.button("🗑", key=f"delete_{convo}", help="删除此对话"):
                            del st.session_state.conversations[convo]
                            if st.session_state.selected_conversation == convo:
                                st.session_state.selected_conversation = next(iter(st.session_state.conversations))
                            st.rerun()
                
        # 底部信息
        st.caption("Built by FZU_SRTP")
        # st.markdown('<div style="flex: 1;"></div>', unsafe_allow_html=True)
        
        # 添加AI内容声明
        st.markdown("""
        <div style="text-align: center; margin-top: 0px; font-size: 12px; color: #666;">
            AI生成内容仅供参考，请以官方信息为准
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div style="text-align: center; margin-top: 10px; font-size: 12px; color: #666;">
            Copyright © 2024-2025 福大灵犀. All Rights Reserved.<br>
        </div>
        """, unsafe_allow_html=True)

        # 在底部添加备案信息
        st.markdown("""
        <div style="text-align: center; margin-top: 20px; font-size: 12px; color: #666;">
            <a href="https://beian.miit.gov.cn/" target="_blank" style="color: #666; text-decoration: underline;">
                苏ICP备2025167431号
            </a>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div style="text-align: center; margin-top: 10px; font-size: 12px; color: #666; display: flex; align-items: center; justify-content: center;">
            <img src="https://beian.mps.gov.cn/img/logo01.dd7ff50e.png" style="height: 12px; margin-right: 3px;">
            <a href="https://beian.mps.gov.cn/#/query/appSearch?code=32030002001239" target="_blank" style="color: #666; text-decoration: underline;">
                苏公网安备32030002001239号
            </a>
        </div>
        """, unsafe_allow_html=True)


        

async def summarize_conversation(messages_text):
    try:
        summary = await api_summary.ainvoke({"input": messages_text})
        return summary[:20]  # 限制标题长度
    except Exception as e:
        return f"对话 {len(st.session_state.conversations)}"
    
@st.cache_data(ttl=3600)
def process_message_content(content):
    if content is None:
        return ""
    
    # 处理图片链接
    if "http://" in content or "https://" in content:
        # 更健壮的图片URL识别正则表达式
        image_urls = re.findall(r"(https?://\S+\.(?:png|jpg|jpeg|gif|appp))", content)
        for url in image_urls:
            try:
                content = content.replace(url, f"![Image]({url})")
            except Exception as e:
                st.warning(f"无法处理图片链接: {url}")
    
    return content

# 添加反馈保存回调函数
def save_feedback(conversation_id, message_idx):
    """保存用户反馈到会话状态"""
    # 获取当前会话和反馈值
    convo = st.session_state.selected_conversation
    conversation = st.session_state.conversations.get(convo)
    feedback_key = f"feedback_{conversation_id}_{message_idx}"
    
    # 将反馈保存到消息中
    if conversation and message_idx < len(conversation["messages"]):
        conversation["messages"][message_idx]["feedback"] = st.session_state[feedback_key]

@st.cache_data
def add_custom_styles():
    st.markdown("""
    <meta name="referrer" content="never">
    <html translate="no">
    <style>
        /* 侧边栏基础样式 */

        /* 按钮样式优化 */
        .stButton button {
            border-radius: 8px !important;
            padding: 0.5rem !important;
            font-weight: 500 !important;
            transition: all 0.2s ease !important;
            margin: 0.2rem 0 !important;
        }
        
        .stButton button:hover {
            transform: translateY(-1px) !important;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1) !important;
        }
        
        /* 选中状态的对话按钮 */
        .stButton [data-testid="baseButton-primary"] {
            background: linear-gradient(135deg, #007AFF, #00C6FF) !important;
            border: none !important;
            color: white !important;
        }
        
        /* 未选中状态的对话按钮 */
        .stButton [data-testid="baseButton-secondary"] {
            background: white !important;
            border: 1px solid #e0e3e9 !important;
            color: #333 !important;
        }
        
        /* 删除按钮样式 */
        .stButton button[data-testid="baseButton-secondary"]:last-child {
            padding: 0.3rem !important;
            min-width: 2rem !important;
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
        }
        /* 消息容器基础样式 */
        .stChatMessage > div {
            padding: 1rem 1.2rem !important;
            border-radius: 15px !important;
            margin: 0.5rem 0 !important;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1) !important;
            position: relative !important;
            max-width: 85% !important;
        }
        
        /* 用户消息样式 */
        .stChatMessage[data-testid="chat-message-user"] > div {
            background: linear-gradient(135deg, #007AFF, #00C6FF) !important;
            color: white !important;
            margin-left: auto !important;
            margin-right: 1rem !important;
        }
        
        /* AI消息样式 */
        .stChatMessage[data-testid="chat-message-assistant"] > div {
            background: linear-gradient(135deg, #f8f9fa, #e9ecef) !important;
            color: #2c3e50 !important;
            margin-right: auto !important;
            margin-left: 1rem !important;
        }
        
        /* 消息时间戳样式 */
        .message-timestamp {
            font-size: 0.75rem !important;
            opacity: 0.7 !important;
            position: relative !重要;  /* 改为 relative */
            margin-top: 0.5rem !important; /* 添加上边距 */
            text-align: right !important;  /* 右对齐 */
            font-family: "SF Mono", monospace !important;
            padding-right: 0.5rem !important; /* 添加右内边距 */
        }
        /* 深色模式适配 */
        @media (prefers-color-scheme: dark) {
            .stChatMessage[data-testid="chat-message-assistant"] > div {
                background: linear-gradient(135deg, #2d3436, #636e72) !important;
                color: #f8f9fa !important;
            }
            
            .message-timestamp {
                color: rgba(255,255,255,0.7) !important;
            }
        }
        
        /* 消息动画效果 */
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .stChatMessage {
            animation: slideIn 0.3s ease-out forwards !important;
        }
        
        /* 头像样式优化 */
        .stChatMessage .stImage {
            width: 40px !important;
            height: 40px !important;
            border-radius: 50% !important;
            border: 2px solid #fff !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important;
        }
        
        /* 输入框样式 */
        .stChatInputContainer {
            padding: 1rem !important;
            background: rgba(255,255,255,0.05) !important;
            border-radius: 12px !important;
            margin-top: 1rem !important;
        }
        
        /* 工具调用状态样式 */
        .stStatus {
            border-radius: 10px !important;
            padding: 0.75rem 1rem !important;
            margin: 0.5rem 0 !important;
            background: rgba(240, 242, 246, 0.7) !important;
            border: 1px solid #e0e3e9 !important;
        }
        
        .stStatus [data-testid="stStatusIcon"] {
            color: #007AFF !important;
        }
        
        /* 参考资料链接样式 */
        .stStatus a {
            color: #007AFF !important;
            text-decoration: none !important;
            font-weight: 500 !important;
        }
        
        .stStatus a:hover {
            text-decoration: underline !important;
        }
        
        /* 深色模式适配 */
        @media (prefers-color-scheme: dark) {
            .stStatus {
                background: rgba(46, 52, 64, 0.7) !important;
                border: 1px solid #4c566a !important;
            }
            
            .stStatus a {
                color: #88c0d0 !important;
            }
        }
        /* 反馈组件样式 */
        .feedback-container {
            margin-top: 5px;
            text-align: right;
        }
        
        /* 反馈按钮样式 */
        .stFeedback {
            opacity: 0.8;
            transition: all 0.2s ease;
        }
        
        .stFeedback:hover {
            opacity: 1;
            transform: scale(1.05);
        }
        
    </style>
    """, unsafe_allow_html=True)

def display_chat_interface():
    if not st.session_state.get("selected_conversation"):
        if st.session_state.conversations:
            st.session_state.selected_conversation = next(iter(st.session_state.conversations))
        else:
            # 如果没有对话，创建新对话
            create_new_conversation()
            return
    conversation_data = st.session_state.conversations.get(
        st.session_state.selected_conversation,
        {"messages": [], "thread_id": str(uuid.uuid4())}  # 使用thread_id替代session_id
    )
    messages = conversation_data["messages"]

    # 显示消息历史 - 确保按照正确顺序显示
    for i, message in enumerate(messages):
        with st.chat_message(
            message["role"], 
            avatar=message.get("avatar", "app/png/user.jpeg" if message["role"] == "user" else "app/png/FZU.png")
        ):
            # 处理不同的消息结构
            if "parts" in message:
                # 处理组合消息 (优先处理parts)
                for part in message["parts"]:
                    if part["type"] == "text":
                        st.markdown(process_message_content(part.get("content", "")), unsafe_allow_html=True)
                    elif part["type"] == "tool":
                        with st.status(part.get("status_label", "查询结果"), state="complete"):
                            if part.get("urls"):
                                st.write("参考资料:")
                                # 使用link_button替代简单的链接
                                for j, url in enumerate(part["urls"], 1):
                                    display_url = url if len(url) <= 40 else url[:37] + "..."
                                    link_text = f"[{j}] {display_url}"
                                    st.link_button(
                                        label=link_text,
                                        url=url,
                                        help=url,
                                        type="secondary",
                                        use_container_width=False
                                    )
            elif message.get("type") == "text" or not message.get("type"):
                # 使用安全的方式获取消息内容
                content = get_message_content(message)
                st.markdown(process_message_content(content), unsafe_allow_html=True)
            elif message.get("type") == "tool":
                # 显示工具调用消息
                with st.status(message.get("status_label", "查询结果"), state="complete"):
                    if message.get("urls"):
                        st.write("参考资料:")
                        # 使用link_button替代简单的链接
                        for j, url in enumerate(message["urls"], 1):
                            display_url = url if len(url) <= 40 else url[:37] + "..."
                            link_text = f"[{j}] {display_url}"
                            st.link_button(
                                label=link_text,
                                url=url,
                                help=url,
                                type="secondary",
                                use_container_width=False
                            )
            
            # 添加反馈组件 - 只为助手消息添加，但排除欢迎消息
            if message["role"] == "assistant" and not (i == 0 and "您好，我是福大灵犀" in message.get("content", "")):  # 排除第一条欢迎消息
                feedback_key = f"feedback_{st.session_state.selected_conversation}_{i}"
                conversation_id = st.session_state.selected_conversation
                
                # 获取已保存的反馈(如果有)
                feedback = message.get("feedback", None)
                st.session_state[feedback_key] = feedback
                
                # 添加反馈组件
                with st.container():
                    st.markdown("<div class='feedback-container'>", unsafe_allow_html=True)
                    st.feedback(
                        "thumbs",
                        key=feedback_key,
                        disabled=feedback is not None,
                        on_change=save_feedback,
                        args=[conversation_id, i],
                    )
                    st.markdown("</div>", unsafe_allow_html=True)
                
            # 添加时间戳
            if "timestamp" not in message:
                message["timestamp"] = datetime.now(pytz.timezone('Asia/Shanghai'))
            
            timestamp = message["timestamp"]
            st.markdown(
                f'<div class="message-timestamp">{timestamp.strftime("%Y-%m-%d %H:%M:%S")}</div>',
                unsafe_allow_html=True
            )
    # 处理用户输入
    if prompt := st.chat_input(" "):
        # 立即显示用户消息
        current_time = datetime.now(pytz.timezone('Asia/Shanghai'))
        
        # 先在界面上显示用户消息
        with st.chat_message("user", avatar="app/png/user.jpeg"):
            st.markdown(prompt)
            st.markdown(
                f'<div class="message-timestamp">{current_time.strftime("%Y-%m-%d %H:%M:%S")}</div>',
                unsafe_allow_html=True
            )
        
        # 添加到历史记录
        messages.append({
            "role": "user",
            "content": prompt,
            "avatar": "app/png/user.jpeg",
            "timestamp": current_time,
            "type": "text"
        })
        
        # 立即更新会话状态
        st.session_state.conversations[st.session_state.selected_conversation]["messages"] = messages.copy()
        
        with st.chat_message("assistant", avatar="app/png/FZU.png"):
            try:
                # 创建多个placeholder
                message_blocks = []  # 用于追踪消息块
                current_block = {"type": "text", "content": "", "placeholder": st.empty()}
                message_blocks.append(current_block)
                pending_tools = {}  # 跟踪进行中的工具调用
                response_parts = []  # 收集完整响应的各部分
                                
                # 获取当前会话的thread_id
                thread_id = conversation_data.get("thread_id", str(uuid.uuid4()))

                # 调用graph.stream获取流式响应
                for step in graph.stream(
                    {"messages": [{"role": "user", "content": prompt}]},
                    stream_mode="messages",
                    config={"configurable": {
                        "thread_id": thread_id,
                        "model": st.session_state.selected_model
                        }}
                ):
                    message_chunk, metadata = step
                    
                    # 处理工具调用开始
                    if hasattr(message_chunk, 'tool_calls') and message_chunk.tool_calls:
                        # 修复可能被分割的工具调用参数
                        message_chunk = combine_tool_calls(message_chunk)
                        
                        # 如果当前块是文本且有内容，完成当前文本块
                        if current_block["type"] == "text" and current_block["content"]:
                            current_block["placeholder"].markdown(current_block["content"])
                            response_parts.append({"type": "text", "content": current_block["content"]})
                        
                        # 处理每个工具调用
                        tool_calls = message_chunk.tool_calls
                        for tc in tool_calls:
                            if isinstance(tc, dict) and tc.get('name') in ['retrieve', 'bocha_websearch_tool']:
                                tool_id = tc.get('id', '')
                                clean_id = clean_tool_call_id(tool_id)
                                query = tc.get('args', {}).get('query', '')
                                
                                # 创建状态容器
                                tool_name = tc.get('name')
                                status_label = "正在搜索网络" if tool_name == 'bocha_websearch_tool' else "正在查询数据库"
                                status_container = st.status(f"{status_label}: {query}", expanded=True)
                                
                                # 创建新的工具调用块
                                tool_block = {
                                    "type": "tool",
                                    "tool_id": clean_id,
                                    "tool_name": tool_name,
                                    "query": query,
                                    "status_container": status_container,
                                    "urls": [],
                                    "completed": False
                                }
                                message_blocks.append(tool_block)
                                
                                # 记录此工具调用
                                pending_tools[clean_id] = tool_block
                                
                                # 为工具调用后的文本准备新块
                                current_block = {"type": "text", "content": "", "placeholder": st.empty()}
                                message_blocks.append(current_block)                    
                    # 处理工具响应
                    # 处理工具响应
                    elif type(message_chunk).__name__ == 'ToolMessage':
                        # 提取工具调用ID并清理
                        tool_call_id = getattr(message_chunk, 'tool_call_id', '')
                        clean_id = clean_tool_call_id(tool_call_id)
                        
                        # 处理可能包含artifact的情况
                        artifact = getattr(message_chunk, 'artifact', None)
                        content = getattr(message_chunk, 'content', '')
                        urls = extract_urls_from_tool_message(content)
                        
                        # 如果存在artifact元数据，从中提取URL
                        if artifact and isinstance(artifact, list):
                            for doc in artifact:
                                source = getattr(doc, 'metadata', {}).get('source', '')
                                if source and source not in urls:
                                    urls.append(source)
                        # 处理bocha_websearch_tool的返回结果
                        elif artifact and isinstance(artifact, list) and len(artifact) > 0:
                            for page in artifact:
                                if isinstance(page, dict) and 'url' in page:
                                    if page['url'] not in urls:
                                        urls.append(page['url'])
                        
                        # 查找匹配的工具调用
                        found = False
                        for pending_id, tool_block in list(pending_tools.items()):
                            if is_same_tool_call(pending_id, clean_id):
                                status_container = tool_block["status_container"]
                                
                                # 更新状态为完成
                                status_label = "网络搜索完成" if tool_block.get("tool_name") == 'bocha_websearch_tool' else "数据库查询完成"
                                status_container.update(label=status_label, state="complete")
                                
                                # 显示URLs
                                with status_container:
                                    if urls:
                                        st.write("参考资料:")
                                        for i, url in enumerate(urls, 1):
                                            # 使用link_button替代简单的链接
                                            display_url = url if len(url) <= 40 else url[:37] + "..."
                                            link_text = f"[{i}] {display_url}"
                                            st.link_button(
                                                label=link_text,
                                                url=url,
                                                help=url,
                                                type="secondary",
                                                use_container_width=False
                                            )
                                            if url not in tool_block["urls"]:
                                                tool_block["urls"].append(url)
                                
                                # 标记为已完成
                                tool_block["completed"] = True
                                found = True
                                
                                # 将此工具调用添加到响应部分
                                response_parts.append({
                                    "type": "tool",
                                    "tool_id": pending_id,
                                    "query": tool_block["query"],
                                    "urls": tool_block["urls"],
                                    "status_label": status_label
                                })
                                break                    
                    # 处理文本流式输出
                    elif hasattr(message_chunk, 'content') and message_chunk.content:
                        # 确保当前块是文本类型
                        if current_block["type"] != "text":
                            current_block = {"type": "text", "content": "", "placeholder": st.empty()}
                            message_blocks.append(current_block)
                        
                        # 累积文本内容
                        current_block["content"] += message_chunk.content
                        
                        # 更新显示
                        current_block["placeholder"].markdown(current_block["content"] + "▌")

                # 最后完成处理任何剩余的文本内容
                if current_block["type"] == "text" and current_block["content"]:
                    current_block["placeholder"].markdown(current_block["content"])
                    response_parts.append({"type": "text", "content": current_block["content"]})                
                # 创建并添加完整的消息
                current_time = datetime.now(pytz.timezone('Asia/Shanghai'))
                assistant_message = {
                    "role": "assistant",
                    "avatar": "app/png/FZU.png",
                    "timestamp": current_time,
                    "parts": response_parts,  # 包含所有响应部分
                    "citations": {}
                }
                
                # 为了兼容性，如果只有一个文本部分，也设置content字段
                if len(response_parts) == 1 and response_parts[0]["type"] == "text":
                    assistant_message["content"] = response_parts[0]["content"]
                    assistant_message["type"] = "text"
                
                # 添加反馈字段
                assistant_message["feedback"] = None
                
                # 添加到消息历史
                messages.append(assistant_message)
                
                # 添加反馈组件
                feedback_key = f"feedback_{st.session_state.selected_conversation}_{len(messages)-1}"
                with st.container():
                    st.markdown("<div class='feedback-container'>", unsafe_allow_html=True)
                    st.feedback(
                        "thumbs",
                        key=feedback_key,
                        disabled=False,
                        on_change=save_feedback,
                        args=[st.session_state.selected_conversation, len(messages)-1],
                    )
                    st.markdown("</div>", unsafe_allow_html=True)

                # 添加时间戳显示
                st.markdown(
                    f'<div class="message-timestamp">{current_time.strftime("%Y-%m-%d %H:%M:%S")}</div>',
                    unsafe_allow_html=True
                )
    

    
            except Exception as e:
                error_msg = "模型输出异常,可能原因:\n\n1.输入内容有敏感信息\n\n2.服务器异常" if str(e) == "Internal Server Error" else f"发生错误：{e}"
                st.error(error_msg)
    
        # 更新会话状态
        st.session_state.conversations[st.session_state.selected_conversation]["messages"] = messages
        st.session_state.conversations[st.session_state.selected_conversation]["thread_id"] = thread_id

def main():
    initialize_session_state()
    add_custom_styles()
    if st.session_state.get("model_switched"):
        st.toast(st.session_state.model_switch_message)
        # 重置标志，防止多次显示
        st.session_state.model_switched = False
    display_sidebar_ui()
    
    # 添加一个变量跟踪当前的输入ID
    if "last_processed_input" not in st.session_state:
        st.session_state.last_processed_input = None
    
    display_chat_interface()
    
if __name__ == "__main__":
    main()