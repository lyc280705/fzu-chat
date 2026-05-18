# 福大灵犀 (FZU-Chat)

[English](README.md)

基于 LangGraph、FastAPI 和 React 构建的福州大学智能问答系统，支持学生登录认证和教务系统集成。

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-009688.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)

当前已标记版本：[v7.0](CHANGELOG.md)

版本记录：[CHANGELOG.md](CHANGELOG.md)

## 概述

福大灵犀为福州大学学生提供类 ChatGPT 的对话体验。每个学生使用学号登录后，拥有独立的对话记录，并可通过 AI 助手查询成绩、课表等教务信息。

## 功能特性

- **学生登录认证**：基于学号的登录系统，每个学生对话完全隔离
- **教务系统工具**：查询成绩、课表、考试成绩、学生信息（基于 [west2-online/jwch](https://github.com/west2-online/jwch) 对接教务系统）
- **教务会话安全清理**：登录时仅在服务端暂存教务系统会话 Cookie，不保存教务密码；退出登录会同时清除站点登录态和暂存的教务会话 Cookie
- **ChatGPT 风格界面**：现代暗色主题，侧边栏历史记录、快捷操作、流式回复
- **消息修改与重新生成**：纯图标操作支持复制回复、重新生成助手回答、修改已发送问题并重建后续回复分支
- **无障碍交互优化**：补充键盘焦点、跳过链接、屏幕阅读器状态、弹窗焦点管理和聊天日志播报
- **低侵入校园智能提醒**：登录/教务重连后后台刷新课表、考试、选课和成绩摘要快照；每个新对话只固化一次紧凑运行时上下文，让模型在回答末尾自然判断是否提醒，同时避免旧消息反复变化
- **丰富的工具卡片**：可视化工具调用过程，结构化展示成绩表格和课表
- **多模型支持**：华为云 MaaS 的 GLM-5.1、Kimi K2.6、DeepSeek V4 Pro 可选，标题总结内部使用 qwen3-30b-a3b
- **福大场景个性化记忆**：在用户确认后保存称呼、回答风格、选课习惯、教务查询展示、校园生活、餐饮与校区等长期偏好；成绩、绩点、课表、考场等易变教务事实仍通过工具实时查询
- **知识库 + 网络搜索**：FAISS 本地检索 + 博查网络搜索兜底
- **Docker 部署**：多阶段构建，React 前端 + Python 后端

## 项目结构

```
fzu-chat/
├── app/
│   ├── server.py          # FastAPI 后端（认证 + 按用户隔离对话）
│   ├── graph.py           # LangGraph 工作流（含教务工具）
│   ├── auth.py            # Token 认证与会话管理
│   ├── jwch_client.py     # 福大本科教务系统客户端（Python 实现）
│   ├── edu_tools.py       # LangGraph 教务查询工具
│   ├── campus_recommendations.py # 情境食堂/自习推荐服务
│   ├── campus_dynamic_context.py # 低延迟校园动态上下文与提醒抑制
│   ├── user_memory_tools.py # 需用户确认的个性化记忆工具
│   ├── memory_store.py    # SQLite 长期记忆存储
│   ├── data/              # 知识库文档
│   ├── faiss/             # FAISS 向量数据库
│   ├── png/               # 静态资源
│   └── storage/           # 按用户存储对话数据
├── frontend/
│   ├── src/App.jsx        # React 聊天界面（含登录）
│   ├── src/App.css        # 现代暗色主题样式
│   └── vite.config.js     # Vite 配置
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 必需的 API 密钥

- `HUAWEICLOUD_MAAS_API_KEY` – 华为云 MaaS OpenAI 兼容接口，用于 GLM-5.1、Kimi K2.6、DeepSeek V4 Pro 与 qwen3-30b-a3b 标题总结
- `DASHSCOPE_API_KEY` – 阿里云 DashScope 向量化，用于本地知识库 embedding
- `BOCHA_API_KEY` – 博查网络搜索
- `LANGSMITH_API_KEY` – LangSmith 追踪
- `AMAP_WEB_SERVICE_KEY` – 可选，高德 Web 服务 Key，用于补充周边 POI 和计算步行路线；本地开发也可使用 `amap_web_service_key.txt` 或 `AMAP_WEB_SERVICE_KEY_FILE`；请求默认限速不超过 5 QPS；未配置时校园推荐会使用内置福大地点库和估算距离降级

本地开发时，如果未配置容器 secret 或环境变量，后端也会读取项目根目录下的 `huaweicloud_maas_api_key.txt`、`dashscope_api_key.txt`、`bocha_api_key.txt` 等密钥文件。

## 本地开发

```bash
# 1. 安装后端依赖
pip install -r requirements.txt

# 2. 设置环境变量
export HUAWEICLOUD_MAAS_API_KEY=...
export DASHSCOPE_API_KEY=...
export BOCHA_API_KEY=...
export LANGSMITH_API_KEY=...
export AMAP_WEB_SERVICE_KEY=... # 可选，用于校园推荐步行路线

# 3. 启动后端
uvicorn app.server:app --host 0.0.0.0 --port 8000

# 4. 启动前端开发服务器
cd frontend && npm install && npm run dev

# 5. 访问 http://localhost:5173
```

## Docker 部署

```bash
# 1. 创建 API 密钥文件
echo "your-key" > huaweicloud_maas_api_key.txt
echo "your-key" > dashscope_api_key.txt
echo "your-key" > bocha_api_key.txt
echo "your-key" > langsmith_api_key.txt
echo "your-key" > amap_web_service_key.txt # 可选，用于情境推荐

# 2. 构建并运行
docker compose up -d --build

# 3. 访问 http://localhost:80
```

## API 接口

### 认证
- `POST /api/auth/login` – 学号 + 密码登录
- `POST /api/auth/logout` – 退出登录，同时清除站点登录态和服务端暂存的教务会话 Cookie
- `GET /api/auth/me` – 当前用户信息

### 聊天
- `GET /api/models` – 可用模型列表
- `GET /api/conversations` – 用户对话列表
- `POST /api/conversations` – 创建新对话
- `GET /api/conversations/{id}` – 对话详情
- `DELETE /api/conversations/{id}` – 删除对话
- `POST /api/conversations/{id}/messages` – 流式生成回复（SSE）
- `POST /api/conversations/{id}/messages` 携带 `rerun_message_id` – 基于既有用户消息修改或重新生成，SSE 事件格式保持兼容
- `POST /api/conversations/{id}/messages` 可携带 `context.location` – 本次消息临时定位上下文，仅用于动态提醒判断，不写入历史
- `POST /api/conversations/{id}/feedback` – 提交反馈
- `POST /api/conversations/{id}/memory-proposals/{tool_id}` – 确认或忽略记忆保存/删除建议

### 情境推荐
- `GET /api/recommendations/locations` – 内置手动校区/位置选项
- `POST /api/recommendations/signal-refresh` – 登录态下异步刷新低侵入提醒所需的非敏感教务摘要快照
- `POST /api/recommendations/contextual` – 根据 `scenario`、可选浏览器 `location`、`manual_location_id` 和可选 `seen_grade_digest` 生成一次性校园建议

低侵入提醒不会在首页自动展示推荐卡片，也不会在发送消息时同步抓取慢速教务数据。后端只读取已缓存的非敏感摘要和提醒冷却状态，将少量动态事件放入第二条短 `SystemMessage`，并在每个对话中只保存第一次生成的运行时上下文，后续回合仅追加新消息，不改旧提示内容。对话历史使用 LangChain 近似 token 计数，接近 200k token 时才裁剪，尽量保留长对话里的工具结果。浏览器经纬度仅随本次消息临时传入，不写入会话存储或长期记忆；成绩摘要只保存 digest、学期和录入数量，不保存具体分数；高德 Key 仅通过后端环境变量或 Docker secret 使用，不暴露给前端。手机定位需要通过 HTTPS 域名访问，普通服务器 HTTP 地址不会弹出浏览器定位授权。

### 教务工具（Agent 自动调用）
AI 助手在学生询问教务数据时自动调用：
- `query_grades` – 课程成绩和绩点
- `query_courses` – 课程表
- `query_student_info` – 学生个人信息
- `query_exam_scores` – 四六级/等级考试成绩
- `recommend_campus_context` – 在用户提供或授权位置后生成校园事务、食堂与自习情境推荐

## 验证

```bash
# 前端
cd frontend && npm run lint && npm run build

# 后端
python -m compileall app
```
