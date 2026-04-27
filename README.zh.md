# 福大灵犀 (FZU-Chat)

[English](README.md)

基于 LangGraph、FastAPI 和 React 构建的福州大学智能问答系统，支持学生登录认证和教务系统集成。

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-009688.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)

当前已标记版本：[v3.1](CHANGELOG.md)

版本记录：[CHANGELOG.md](CHANGELOG.md)

## 概述

福大灵犀为福州大学学生提供类 ChatGPT 的对话体验。每个学生使用学号登录后，拥有独立的对话记录，并可通过 AI 助手查询成绩、课表等教务信息。

## 功能特性

- **学生登录认证**：基于学号的登录系统，每个学生对话完全隔离
- **教务系统工具**：查询成绩、课表、考试成绩、学生信息（基于 [west2-online/jwch](https://github.com/west2-online/jwch) 对接教务系统）
- **教务会话安全清理**：登录时仅在服务端暂存教务系统会话 Cookie，不保存教务密码；退出登录会同时清除站点登录态和暂存的教务会话 Cookie
- **ChatGPT 风格界面**：现代暗色主题，侧边栏历史记录、快捷操作、流式回复
- **丰富的工具卡片**：可视化工具调用过程，结构化展示成绩表格和课表
- **多模型支持**：华为云 MaaS 的 GLM-5.1、Kimi K2.6、DeepSeek-V3.2 可选，标题总结内部使用 Qwen3-32B
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

- `HUAWEICLOUD_MAAS_API_KEY` – 华为云 MaaS OpenAI 兼容接口，用于 GLM-5.1、Kimi K2.6、DeepSeek-V3.2 与 Qwen3-32B 标题总结
- `DASHSCOPE_API_KEY` – 阿里云 DashScope 向量化，用于本地知识库 embedding
- `BOCHA_API_KEY` – 博查网络搜索
- `LANGSMITH_API_KEY` – LangSmith 追踪

## 本地开发

```bash
# 1. 安装后端依赖
pip install -r requirements.txt

# 2. 设置环境变量
export HUAWEICLOUD_MAAS_API_KEY=...
export DASHSCOPE_API_KEY=...
export BOCHA_API_KEY=...
export LANGSMITH_API_KEY=...

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
- `POST /api/conversations/{id}/feedback` – 提交反馈

### 教务工具（Agent 自动调用）
AI 助手在学生询问教务数据时自动调用：
- `query_grades` – 课程成绩和绩点
- `query_courses` – 课程表
- `query_student_info` – 学生个人信息
- `query_exam_scores` – 四六级/等级考试成绩

## 验证

```bash
# 前端
cd frontend && npm run lint && npm run build

# 后端
python -m compileall app
```
