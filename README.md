# FZU-Chat

[简体中文](README.zh.md)

A Fuzhou University intelligent Q&A system with student authentication and educational system integration, built with LangGraph, FastAPI, and React.

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-009688.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)

Current tagged release: [v7.14](CHANGELOG.md)

Release notes: [CHANGELOG.md](CHANGELOG.md)

## Overview

FZU-Chat provides a ChatGPT-style conversation experience for Fuzhou University students. Each student logs in with their student ID to get isolated conversations and access to educational system tools (grade queries, course schedules, etc.); external visitors can use third-party guest login for public Q&A and campus-life guidance.

## Features

- **Student authentication**: Per-student login with conversation isolation
- **Third-party guest mode**: WeChat, QQ, Microsoft, Apple, and GitHub OAuth can create visitor sessions with public Q&A, knowledge retrieval, web search, and campus-life recommendations, without binding personal grade, schedule, selection, or academic-affairs tools
- **Educational system tools**: Query grades, courses, exam scores, and student info via the FZU academic affairs system (based on [west2-online/jwch](https://github.com/west2-online/jwch))
- **Educational session cleanup**: The app only keeps educational-system session cookies on the server side and never stores the raw password; logging out clears both the site login state and the cached educational-session cookies
- **ChatGPT-style interface**: Modern dark UI with sidebar history, quick actions, and streaming replies
- **Message editing and regeneration**: Icon-only actions for copying replies, regenerating an assistant answer, or editing a sent user message and rebuilding the following response branch
- **Accessible interaction polish**: Keyboard-friendly focus rings, skip link, screen-reader status updates, dialog focus handling, and live chat-log announcements
- **Low-intrusion campus intelligence**: After login or educational reconnect, the backend refreshes cached course, exam, selection, and grade-summary snapshots; each new conversation freezes one compact runtime context so the model can decide whether a gentle end-of-answer reminder is useful without changing old messages
- **Rich tool cards**: Visual display of tool calls with structured data tables for grades and courses
- **Multi-model support**: Huawei Cloud MaaS GLM-5.1, Kimi K2.6, and DeepSeek V4 Pro selection, with qwen3-30b-a3b for title summarization
- **FZU-aware personalized memory**: Confirmed long-term preferences for names, answer style, course-selection habits, academic-query presentation, campus-life needs, and dining/campus preferences, while volatile educational facts remain live tool queries
- **Knowledge + web search**: FAISS retrieval plus Bocha web search fallback
- **Launch-ready single-node hardening**: Strict SPA fallback, scanner-path 404s, Redis-backed sessions/rate limits, readiness and Prometheus-style metrics
- **Docker deployment**: Multi-stage build for React frontend + Python backend, plus production Compose with internal Redis

## Project Structure

```
fzu-chat/
├── app/
│   ├── server.py          # FastAPI backend with auth + per-user conversations
│   ├── graph.py           # LangGraph workflow with edu tools
│   ├── auth.py            # Token-based authentication & session management
│   ├── oauth.py           # Third-party visitor OAuth helpers
│   ├── jwch_client.py     # FZU undergraduate system client (Python port)
│   ├── edu_tools.py       # LangGraph tools for educational queries
│   ├── campus_recommendations.py # Contextual dining/study recommendation service
│   ├── campus_dynamic_context.py # Low-latency dynamic context and reminder suppression
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
├── docker-compose.prod.yml
├── scripts/              # Deploy, rollback, and SQLite backup helpers
├── docker-compose.yml
└── requirements.txt
```

## Required API Keys

- `HUAWEICLOUD_MAAS_API_KEY` – Huawei Cloud MaaS OpenAI-compatible API for GLM-5.1, Kimi K2.6, DeepSeek V4 Pro, and qwen3-30b-a3b title summarization
- `DASHSCOPE_API_KEY` – Alibaba Cloud DashScope embeddings for the local knowledge base
- `BOCHA_API_KEY` – Bocha web search
- `LANGSMITH_API_KEY` – LangSmith tracing
- `AMAP_WEB_SERVICE_KEY` – Optional AMap Web Service key for reverse geocoding browser location into text, POI supplementation, and walking/bicycling route distance; local development can also use `amap_web_service_key.txt` or `AMAP_WEB_SERVICE_KEY_FILE`; requests are throttled to at most 5 QPS by default; reverse-geocoding uses a short timeout and 10-minute in-process cache; when unset, campus recommendations fall back to the built-in FZU place library and estimated distance
- `FZU_CHAT_OAUTH_PROVIDERS` – Optional comma-separated visible visitor-login provider allowlist, e.g. `microsoft,apple,github` for production while keeping WeChat and QQ available in the codebase
- `FZU_CHAT_WECHAT_CLIENT_ID` / `FZU_CHAT_WECHAT_CLIENT_SECRET`, `FZU_CHAT_QQ_CLIENT_ID` / `FZU_CHAT_QQ_CLIENT_SECRET`, `FZU_CHAT_MICROSOFT_CLIENT_ID` / `FZU_CHAT_MICROSOFT_CLIENT_SECRET`, `FZU_CHAT_APPLE_CLIENT_ID` / `FZU_CHAT_APPLE_CLIENT_SECRET`, `FZU_CHAT_GITHUB_CLIENT_ID` / `FZU_CHAT_GITHUB_CLIENT_SECRET` – Optional visitor OAuth credentials; the matching `*_REDIRECT_URI` variables can override the default `/api/auth/oauth/{provider}/callback` callback URL. Apple uses the generated client-secret JWT for `FZU_CHAT_APPLE_CLIENT_SECRET`; Microsoft can also set `FZU_CHAT_MICROSOFT_TENANT`, defaulting to `common`.

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
export AMAP_WEB_SERVICE_KEY=... # optional, for text location and campus routes
export FZU_CHAT_OAUTH_PROVIDERS=microsoft,apple,github # optional visible provider allowlist
export FZU_CHAT_GITHUB_CLIENT_ID=... # optional, for visitor GitHub login
export FZU_CHAT_GITHUB_CLIENT_SECRET=...

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
echo "your-key" > amap_web_service_key.txt # optional, for contextual recommendations

# 2. Build and run local Compose
docker compose up -d --build

# 3. Visit http://localhost:80
```

Production deployment can use `docker-compose.prod.yml` with an internal Redis container. Set a URL-safe `REDIS_PASSWORD` such as `openssl rand -hex 32`, then run `FZU_CHAT_VERSION=v7.14 ./scripts/deploy-ghcr.sh`; if GHCR image pull fails, the script falls back to a local production image build.

Useful production environment variables:

- `FZU_CHAT_REDIS_URL` – Redis URL for session, rate-limit, stream-slot, and background-task dedupe state
- `FZU_CHAT_PUBLIC_DOCS=false` – keep `/openapi.json`, Swagger, and ReDoc private by default
- `FZU_CHAT_GLOBAL_STREAM_LIMIT=80`, `FZU_CHAT_USER_STREAM_LIMIT=5` – active SSE generation caps for initial campus-scale launch
- `FZU_CHAT_STATIC_FALLBACK=strict` – return the SPA only for `/` and `index.html`
- `FZU_CHAT_METRICS_ENABLED=true` – enable restricted `/api/metrics`
- `FZU_CHAT_OAUTH_PROVIDERS=microsoft,apple,github` – show only Microsoft, Apple, and GitHub in production; omit it to show all repository-supported providers
- `FZU_CHAT_WECHAT_CLIENT_ID` / `FZU_CHAT_WECHAT_CLIENT_SECRET`, `FZU_CHAT_QQ_CLIENT_ID` / `FZU_CHAT_QQ_CLIENT_SECRET`, `FZU_CHAT_MICROSOFT_CLIENT_ID` / `FZU_CHAT_MICROSOFT_CLIENT_SECRET`, `FZU_CHAT_APPLE_CLIENT_ID` / `FZU_CHAT_APPLE_CLIENT_SECRET`, `FZU_CHAT_GITHUB_CLIENT_ID` / `FZU_CHAT_GITHUB_CLIENT_SECRET` – enable the matching visitor login entry; unconfigured providers are shown as unavailable in the login UI

## API Endpoints

### Authentication
- `POST /api/auth/login` – Login with student ID + password
- `GET /api/auth/oauth/providers` – Report visible visitor-login availability
- `GET /api/auth/oauth/{provider}/start` – Start a visible visitor OAuth redirect
- `GET|POST /api/auth/oauth/{provider}/callback` – OAuth callback that creates a visitor session without educational tools; POST is used for Apple `form_post`
- `POST /api/auth/logout` – Logout and clear both the site login state and the server-side educational-session cookies
- `GET /api/auth/me` – Current user info

### Chat
- `GET /api/models` – Available chat models
- `GET /api/health` – Lightweight liveness check
- `GET /api/ready` – Readiness check for Redis, SQLite writeability, and configured runtime limits
- `GET /api/metrics` – Restricted Prometheus-style operational metrics
- `GET /api/conversations?limit=50&cursor=...` – Paginated conversation list with preview and message counts
- `POST /api/conversations` – Create new conversation
- `GET /api/conversations/{id}` – Conversation detail
- `DELETE /api/conversations/{id}` – Delete conversation
- `POST /api/conversations/{id}/messages` – Stream assistant response (SSE)
- `POST /api/conversations/{id}/messages` with `rerun_message_id` – Edit or regenerate from an existing user message while preserving the SSE event format
- `POST /api/conversations/{id}/messages` may include `context.location` – One-message transient location context for dynamic reminders and campus recommendations, never persisted to chat history
- `POST /api/conversations/{id}/feedback` – Save feedback
- `POST /api/conversations/{id}/memory-proposals/{tool_id}` – Confirm or dismiss a memory save/delete proposal

### Contextual Recommendations
- `GET /api/recommendations/locations` – Built-in manual campus/location options
- `POST /api/recommendations/signal-refresh` – Asynchronously refresh non-sensitive academic summary snapshots used by low-intrusion reminders
- `POST /api/recommendations/contextual` – Generate one-time campus recommendations from `scenario`, optional browser `location`, `manual_location_id`, and optional `seen_grade_digest`

Low-intrusion reminders no longer render automatic homepage cards and do not synchronously fetch slow educational-system data when a user sends a message. The backend reads cached non-sensitive summaries plus reminder cooldown state, injects a few dynamic events into a second short `SystemMessage`, and stores that runtime context once per conversation so later turns append messages without rewriting prior prompt content. Conversation history uses LangChain's approximate token counter and is only trimmed around the 200k-token boundary, preserving tool results for long chats. Browser coordinates are transient per message: they are used server-side for campus recommendations and AMap reverse geocoding, while only the resulting text location can be injected into the current model prompt. Coordinates and text locations are not persisted to conversation storage or long-term memory. Grade summaries store only digests, term labels, and recorded counts, never concrete scores. Mobile geolocation requires an HTTPS origin; plain HTTP server URLs will not show the browser permission prompt. The AMap key stays server-side through environment variables or Docker secrets.

### Educational Tools (via Agent)
The LLM agent can automatically call these tools only in undergraduate educational-login sessions; visitor mode never binds these personal academic-affairs tools:
- `query_grades` – Course grades and GPA
- `query_courses` – Course schedule
- `query_student_info` – Student profile
- `query_exam_scores` – CET and unified exam scores
- `recommend_campus_context` – Contextual campus academic, dining, and study recommendations when the user supplies or authorizes a location

## Validation

```bash
# Frontend
cd frontend && npm run lint && npm run build

# Backend
python -m compileall app
```
