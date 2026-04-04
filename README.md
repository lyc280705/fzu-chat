# FZU-Chat

[简体中文](README.zh.md)

A Fuzhou University intelligent Q&A system built with LangGraph, FastAPI, and React.

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-009688.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)

## Overview

FZU-Chat provides a ChatGPT-style conversation experience for Fuzhou University knowledge retrieval. It keeps the existing LangGraph + FAISS + Bocha search backend logic, adds a FastAPI HTTP layer, and replaces the old Streamlit UI with a React application.

## Features

- **ChatGPT-style interface**: Sidebar history, focused chat panel, and sticky composer
- **Saved conversations**: Persistent conversation list stored on the backend
- **Streaming replies**: Incremental assistant responses with tool status updates
- **Multi-model support**: Qwen, DeepSeek, ERNIE, and Kimi model selection
- **Knowledge + web search**: FAISS retrieval plus Bocha web search fallback
- **Docker deployment**: Multi-stage build for React frontend + Python backend

## Project Structure

```text
fzu-chat/
├── app/
│   ├── __init__.py
│   ├── graph.py                 # LangGraph workflow and model/tool setup
│   ├── server.py                # FastAPI API and static file serving
│   ├── storage/                 # Persistent conversation metadata/messages
│   ├── data/                    # Knowledge base document storage
│   ├── faiss/                   # Vector database
│   └── png/                     # Static assets
├── frontend/
│   ├── src/                     # React application source
│   ├── package.json
│   └── vite.config.js
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
└── README.zh.md
```

## Required API Keys

Set the following keys through environment variables or Docker secrets:

- `DASHSCOPE_API_KEY`
- `DEEPSEEK_API_KEY`
- `QIANFAN_API_KEY`
- `BOCHA_API_KEY`
- `LANGSMITH_API_KEY`

## Local Development

### 1. Install dependencies

```bash
pip install -r requirements.txt
cd frontend && npm install
```

### 2. Configure environment variables

```bash
export DASHSCOPE_API_KEY="your_key"
export BOCHA_API_KEY="your_key"
export LANGSMITH_API_KEY="your_key"
export DEEPSEEK_API_KEY="your_key"
export QIANFAN_API_KEY="your_key"
```

### 3. Start the backend

```bash
uvicorn app.server:app --host 0.0.0.0 --port 8000
```

### 4. Start the frontend dev server

```bash
cd frontend
npm run dev
```

Then open `http://localhost:5173`.

## Docker Deployment

1. Create the API key files:

   ```bash
   echo "your_dashscope_key" > dashscope_api_key.txt
   echo "your_bocha_key" > bocha_api_key.txt
   echo "your_langsmith_key" > langsmith_api_key.txt
   echo "your_deepseek_key" > deepseek_api_key.txt
   echo "your_qianfan_key" > qianfan_api_key.txt
   ```

2. Start the service:

   ```bash
   docker compose up -d --build
   ```

3. Visit `http://localhost:100`.

## API Overview

- `GET /api/models` — available chat models
- `GET /api/conversations` — conversation list
- `POST /api/conversations` — create a new conversation
- `GET /api/conversations/{id}` — full conversation detail
- `DELETE /api/conversations/{id}` — delete a conversation
- `POST /api/conversations/{id}/messages` — stream a new assistant response
- `POST /api/conversations/{id}/feedback` — save thumbs up/down feedback

## Validation

Frontend validation commands:

```bash
cd frontend
npm run lint
npm run build
```

Backend syntax validation:

```bash
python -m compileall app
```
