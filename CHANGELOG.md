# Changelog

This file tracks notable tagged releases for FZU-Chat.
本文件记录 FZU-Chat 的对外发布版本变更。

## [v2.0] - 2026-04-14

FZU-Chat v2.0 focuses on answer quality, runtime resilience, and conversation usability. This release adds teaching-week-aware academic context, improves multi-model behavior and thinking controls, and hardens streaming and tool-call handling across both the backend and frontend.

### Highlights

- Teaching-week aware academic context. The assistant now pulls current teaching-week information from the FZU academic affairs system, injects it into prompt context, and caches semester week data locally so date-sensitive questions are answered with more reliable campus timing information.
- Unified thinking mode toggle. The frontend now exposes one consistent thinking-mode switch, and the backend maps that preference to the correct provider-specific parameters so the behavior stays aligned across different model backends.
- Improved model routing and compatibility. Chat model handling was refined around GLM-5.1 and DeepSeek-V3.2, while title summarization remains separated for better stability and clearer model responsibilities.
- Per-conversation streaming state. Sending and stopping a response is now tracked per conversation instead of globally, which avoids UI lockups when users switch chats while another conversation is still streaming.
- More resilient streamed tool execution. The backend now recovers malformed streamed tool calls and normalizes tool-call identifiers before execution, reducing failures caused by provider-side streamed function-call quirks.

### Included in this release

- Automatic teaching-week retrieval plus semester-aware cache fallback for current academic-week context.
- Unified thinking-mode toggle UI, safer default initialization, and thinking-indicator behavior refinements.
- Better conversation streaming management, including per-conversation stop state and improved title refresh behavior.
- Hardened authentication token handling, logout cleanup, and expired educational-session relogin experience.
- Recovery logic for invalid streamed tool calls, reducing downstream tool execution failures.
- Release documentation improvements, including a repository changelog and README links for the current tagged release.

### Validation

- cd frontend && npm run build
- /opt/anaconda3/envs/langchain/bin/python -m compileall app

---

## 福大灵犀 v2.0

福大灵犀 v2.0 重点提升了回答质量、运行稳定性和对话可用性。本次版本加入了面向教务周次的上下文能力，完善了多模型与思考模式的联动，同时增强了前后端在流式回复和工具调用场景下的健壮性。

### 版本亮点

- 面向教务周次的上下文增强。系统现在会从福州大学教务侧获取当前教学周信息，并注入提示词上下文，同时在本地缓存学期周次数据，使涉及校历、学期进度、当前周数等问题时能给出更稳定的结果。
- 统一的思考模式开关。前端提供统一的思考模式切换入口，后端再按不同模型提供商映射到各自的参数格式，保证用户感知一致，模型行为也更可控。
- 更清晰的多模型路由。围绕 GLM-5.1 与 DeepSeek-V3.2 的聊天模型处理进行了调整和兼容性优化，同时保持标题总结链路独立，降低不同用途模型之间的互相干扰。
- 按会话隔离的流式状态管理。发送中和停止中的状态不再是全局共享，而是按对话分别跟踪，用户在一个会话生成回复时仍可切换到其他会话继续操作。
- 更稳健的工具调用恢复机制。后端会在执行前修复异常的流式工具调用数据，并规范化工具调用 ID，减少模型侧流式函数调用格式不稳定导致的执行失败。

### 本次发布包含

- 当前教学周自动获取能力，以及按学期缓存的周次推断与兜底逻辑。
- 思考模式开关、默认初始化行为、思考指示器展示逻辑与样式细节优化。
- 对话流状态管理重构，包括按会话停止响应和标题异步刷新体验改进。
- 登录态与认证令牌处理增强，退出登录清理优化，以及教务会话过期后的重新连接体验改进。
- 非法流式工具调用的恢复逻辑，降低工具执行阶段的异常概率。
- 发布文档补充，包括仓库级 CHANGELOG 和 README 中的版本记录入口。

### 验证

- cd frontend && npm run build
- /opt/anaconda3/envs/langchain/bin/python -m compileall app

## [v1.0] - 2026-04-08

First stable release of FZU-Chat, an intelligent assistant for Fuzhou University students built with LangGraph, FastAPI, and React. This release established the project's core product shape: authenticated student access, educational-system integration, streaming chat, structured tool output, and a deployment-ready full-stack architecture.

### Highlights

- Student authentication with isolated conversations and per-user session history, giving each student an independent chat workspace tied to their own academic context.
- Educational-system integration for core academic workflows, including grades, course schedules, exam scores, student profile queries, and related campus data through the FZU academic affairs system.
- A modern React chat experience with login flow, sidebar conversation history, quick actions, streaming replies, rich tool cards, and feedback handling.
- Knowledge and web retrieval support through FAISS local search with Bocha web search fallback, plus improved citation handling for retrieved search results.
- A deployment-oriented architecture with FastAPI backend, React frontend, Docker support, and a foundation suitable for local development as well as server deployment.

### Included in this release

- The initial React frontend and API backend skeleton, followed by integrated login UI and per-user isolated backend conversation management.
- Educational tools for student information retrieval, along with memory tooling, cultivate-plan support, and stop-response controls added before the v1.0 milestone.
- Conversation experience improvements such as better previews, richer tool-card defaults, clearer message handling, and model-selection refinements.
- Security and reliability hardening, including auth-flow improvements, safer file serving, security response headers, tracing enablement, storage-path fixes, and more robust startup and streaming error handling.
- Search-result extraction and citation renumbering improvements so referenced retrieval results are presented more cleanly in assistant answers.
- Frontend and dependency cleanup for the release milestone, including UI polish, dependency refreshes, and release metadata preparation for v1.0.

### Validation

- cd frontend && npm run lint && npm run build
- python -m compileall app

---

## 福大灵犀 v1.0

这是福大灵犀的首个稳定版本，基于 LangGraph、FastAPI 和 React 构建。本次发布确立了项目的核心形态：学生身份认证、教务系统集成、流式对话、结构化工具展示，以及可部署的前后端一体化架构。

### 版本亮点

- 学生登录认证与按用户隔离的会话记录，每位学生都拥有独立的对话空间和与自身教务上下文对应的使用体验。
- 面向教务场景的核心能力接入，包括成绩、课表、考试成绩、学生信息等常见查询流程，并与福州大学教务系统联动。
- 现代化 React 聊天界面，覆盖登录流程、侧边栏历史记录、快捷提问、流式回复、结构化工具卡片和消息反馈能力。
- 知识库与网络检索能力结合，使用 FAISS 本地检索并以博查网络搜索兜底，同时改进了检索结果引用和展示方式。
- 面向部署的整体架构，包含 FastAPI 后端、React 前端与 Docker 方案，为本地开发和服务器部署提供统一基础。

### 本次发布包含

- React 前端与 API 后端基础骨架，并在此基础上完成登录界面接入和按用户隔离的后端会话管理。
- 面向学生场景的教务工具能力，以及在 v1.0 前补充完成的记忆工具、培养方案工具和停止响应功能。
- 对话体验改进，包括更合理的预览信息、更完善的工具卡片默认展示、更清晰的消息处理逻辑，以及模型选择相关优化。
- 安全性与稳定性增强，包括认证流程加固、静态文件服务收敛、安全响应头、Tracing 支持、存储路径修正，以及启动和流式报错处理优化。
- 检索结果项提取与引用编号优化，使知识库和联网搜索结果在回答中展示得更清晰、更可追踪。
- 面向正式发布的前端与依赖整理，包括界面细节打磨、依赖升级，以及 v1.0 版本发布元数据准备。

### 验证

- cd frontend && npm run lint && npm run build
- python -m compileall app