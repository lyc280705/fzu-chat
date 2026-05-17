# FZU-Chat

[简体中文](README.zh.md)

A Fuzhou University intelligent Q&A system with student authentication and educational system integration, built with LangGraph, FastAPI, and React.

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-009688.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)

Current tagged release: [v5.0](CHANGELOG.md)

Release notes: [CHANGELOG.md](CHANGELOG.md)

## Overview

FZU-Chat provides a ChatGPT-style conversation experience for Fuzhou University students. Each student logs in with their student ID to get isolated conversations and access to educational system tools (grade queries, course schedules, etc.).

## Features

- **Student authentication**: Per-student login with conversation isolation
- **Educational system tools**: Query grades, courses, exam scores, and student info via the FZU academic affairs system (based on [west2-online/jwch](https://github.com/west2-online/jwch))
- **Educational session cleanup**: The app only keeps educational-system session cookies on the server side and never stores the raw password; logging out clears both the site login state and the cached educational-session cookies
- **ChatGPT-style interface**: Modern dark UI with sidebar history, quick actions, and streaming replies
- **Message editing and regeneration**: Icon-only actions for copying replies, regenerating an assistant answer, or editing a sent user message and rebuilding the following response branch
- **Accessible interaction polish**: Keyboard-friendly focus rings, skip link, screen-reader status updates, dialog focus handling, and live chat-log announcements
- **Rich tool cards**: Visual display of tool calls with structured data tables for grades and courses
- **Multi-model support**: Huawei Cloud MaaS GLM-5.1, Kimi K2.6, and DeepSeek V4 Pro selection, with qwen3-30b-a3b for title summarization
- **FZU-aware personalized memory**: Confirmed long-term preferences for names, answer style, course-selection habits, academic-query presentation, campus-life needs, and dining/campus preferences, while volatile educational facts remain live tool queries
- **Knowledge + web search**: FAISS retrieval plus Bocha web search fallback
- **Docker deployment**: Multi-stage build for React frontend + Python backend

## Project Structure

```
fzu-chat/
├── app/
│   ├── server.py          # FastAPI backend with auth + per-user conversations
│   ├── graph.py           # LangGraph workflow with edu tools
│   ├── auth.py            # Token-based authentication & session management
│   ├── jwch_client.py     # FZU undergraduate system client (Python port)
│   ├── edu_tools.py       # LangGraph tools for educational queries
│   ├── user_memory_tools.py # Confirmed personalized-memory tools
│   ├── memory_store.py    # SQLite-backed long-term memory store
│   ├── data/              # Knowledge base documents
│   ├── faiss/             # FAISS vector database
│   ├── png/               # Static assets
│   └── storage/           # Per-user conversation storage
├── frontend/
│   ├── src/App.jsx        # React chat UI with login
│   ├── src/App.css        # Modern dark theme styles
│   └── vite.config.js     # Vite config with API proxy
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Required API Keys

- `HUAWEICLOUD_MAAS_API_KEY` – Huawei Cloud MaaS OpenAI-compatible API for GLM-5.1, Kimi K2.6, DeepSeek V4 Pro, and qwen3-30b-a3b title summarization
- `DASHSCOPE_API_KEY` – Alibaba Cloud DashScope embeddings for the local knowledge base
- `BOCHA_API_KEY` – Bocha web search
- `LANGSMITH_API_KEY` – LangSmith tracing

For local development, the backend also reads root-level key files such as `huaweicloud_maas_api_key.txt`, `dashscope_api_key.txt`, and `bocha_api_key.txt` when container secrets and environment variables are not set.

## Local Development

```bash
# 1. Install backend dependencies
pip install -r requirements.txt

# 2. Set environment variables
export HUAWEICLOUD_MAAS_API_KEY=...
export DASHSCOPE_API_KEY=...
export BOCHA_API_KEY=...
export LANGSMITH_API_KEY=...

# 3. Start backend
uvicorn app.server:app --host 0.0.0.0 --port 8000

# 4. Start frontend dev server
cd frontend && npm install && npm run dev

# 5. Open http://localhost:5173
```

## Docker Deployment

```bash
# 1. Create API key files
echo "your-key" > huaweicloud_maas_api_key.txt
echo "your-key" > dashscope_api_key.txt
echo "your-key" > bocha_api_key.txt
echo "your-key" > langsmith_api_key.txt

# 2. Build and run
docker compose up -d --build

# 3. Visit http://localhost:80
```

## API Endpoints

### Authentication
- `POST /api/auth/login` – Login with student ID + password
- `POST /api/auth/logout` – Logout and clear both the site login state and the server-side educational-session cookies
- `GET /api/auth/me` – Current user info

### Chat
- `GET /api/models` – Available chat models
- `GET /api/conversations` – User's conversation list
- `POST /api/conversations` – Create new conversation
- `GET /api/conversations/{id}` – Conversation detail
- `DELETE /api/conversations/{id}` – Delete conversation
- `POST /api/conversations/{id}/messages` – Stream assistant response (SSE)
- `POST /api/conversations/{id}/messages` with `rerun_message_id` – Edit or regenerate from an existing user message while preserving the SSE event format
- `POST /api/conversations/{id}/feedback` – Save feedback
- `POST /api/conversations/{id}/memory-proposals/{tool_id}` – Confirm or dismiss a memory save/delete proposal

### Educational Tools (via Agent)
The LLM agent can automatically call these tools when students ask about their academic data:
- `query_grades` – Course grades and GPA
- `query_courses` – Course schedule
- `query_student_info` – Student profile
- `query_exam_scores` – CET and unified exam scores

## Validation

```bash
# Frontend
cd frontend && npm run lint && npm run build

# Backend
python -m compileall app
```
