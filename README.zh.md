# 福大灵犀

[简体中文](README.zh.md) | [English](README.md)

基于 LangGraph、FastAPI 和 React 的福州大学智能问答系统。

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-009688.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)

## 项目简介

福大灵犀现在采用 React + FastAPI 架构，界面与交互方式参考 ChatGPT，同时继续复用原有的 LangGraph、FAISS 和博查搜索能力，保持与现有后端检索和模型流程兼容。

## 核心特性

- **ChatGPT 风格界面**：左侧历史会话，右侧主聊天区，底部固定输入框
- **对话持久化**：后端保存会话列表、消息内容与反馈记录
- **流式输出**：逐步显示回答内容，并同步展示工具调用状态
- **多模型支持**：支持通义千问、DeepSeek、文心一言、Kimi
- **知识库 + 联网搜索**：保留 FAISS 检索与博查搜索补充能力
- **容器化部署**：Docker 多阶段构建前端与后端

## 项目结构

```text
fzu-chat/
├── app/
│   ├── __init__.py
│   ├── graph.py                 # LangGraph 工作流与模型/工具配置
│   ├── server.py                # FastAPI API 与静态资源服务
│   ├── storage/                 # 持久化会话数据
│   ├── data/                    # 知识库文档存储
│   ├── faiss/                   # 向量数据库
│   └── png/                     # 静态资源
├── frontend/
│   ├── src/                     # React 前端源码
│   ├── package.json
│   └── vite.config.js
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
└── README.zh.md
```

## 必需的 API 密钥

可通过环境变量或 Docker Secret 提供以下密钥：

- `DASHSCOPE_API_KEY`
- `DEEPSEEK_API_KEY`
- `QIANFAN_API_KEY`
- `BOCHA_API_KEY`
- `LANGSMITH_API_KEY`

## 本地开发

### 1. 安装依赖

```bash
pip install -r requirements.txt
cd frontend && npm install
```

### 2. 配置环境变量

```bash
export DASHSCOPE_API_KEY="your_key"
export BOCHA_API_KEY="your_key"
export LANGSMITH_API_KEY="your_key"
export DEEPSEEK_API_KEY="your_key"
export QIANFAN_API_KEY="your_key"
```

### 3. 启动后端

```bash
uvicorn app.server:app --host 0.0.0.0 --port 8000
```

### 4. 启动前端开发服务器

```bash
cd frontend
npm run dev
```

随后访问 `http://localhost:5173`。

## Docker 部署

1. 创建 API 密钥文件：

   ```bash
   echo "your_dashscope_key" > dashscope_api_key.txt
   echo "your_bocha_key" > bocha_api_key.txt
   echo "your_langsmith_key" > langsmith_api_key.txt
   echo "your_deepseek_key" > deepseek_api_key.txt
   echo "your_qianfan_key" > qianfan_api_key.txt
   ```

2. 启动服务：

   ```bash
   docker compose up -d --build
   ```

3. 访问 `http://localhost:100`。

## API 概览

- `GET /api/models`：可用模型列表
- `GET /api/conversations`：会话列表
- `POST /api/conversations`：创建新会话
- `GET /api/conversations/{id}`：获取完整会话内容
- `DELETE /api/conversations/{id}`：删除会话
- `POST /api/conversations/{id}/messages`：流式生成回复
- `POST /api/conversations/{id}/feedback`：保存点赞/点踩反馈

## 验证命令

前端校验：

```bash
cd frontend
npm run lint
npm run build
```

后端语法校验：

```bash
python -m compileall app
```
