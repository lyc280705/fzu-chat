# Changelog

This file tracks notable tagged releases for FZU-Chat.
本文件记录 FZU-Chat 的对外发布版本变更。

## [v3.1] - 2026-04-27

FZU-Chat v3.1 focuses on Kimi K2.6 compatibility and release-quality follow-up after v3.0. This release restores true multi-turn thinking support for Kimi on Huawei MaaS by preserving provider-specific reasoning metadata across storage, streaming, and history replay, and also moves conversation title summarization to qwen3-30b-a3b for more stable short titles.

### Highlights

- True Kimi K2.6 thinking-mode support. The backend now preserves `reasoning_content` from Kimi responses, replays it in later assistant history messages, and patches the current LangChain OpenAI adapter gap so Huawei MaaS no longer rejects multi-turn conversations with missing reasoning metadata.
- Compatible history persistence. Assistant messages can now store reasoning metadata alongside normal content and tool-card parts, allowing new Kimi conversations to continue across turns without losing the model's required context.
- Safer backward compatibility. Older conversations that do not yet contain stored reasoning metadata are replayed with an empty `reasoning_content` field for Kimi, preventing the previous `ModelArts.81001` validation error on follow-up turns.
- Updated title model. Conversation title summarization now uses `qwen3-30b-a3b`, improving stability while keeping the existing short-title prompt behavior.

### Included in this release

- A compatibility patch for `langchain_openai` message conversion so `reasoning_content` is parsed from MaaS responses, kept on streamed assistant chunks, and serialized back into later Kimi requests.
- Message-store schema evolution and server-side persistence for assistant reasoning metadata.
- History replay logic that sends `AIMessage` objects with `reasoning_content` back to Kimi instead of flattening every prior assistant message to plain text.
- Title-summary model update from the earlier qwen3 title route to `qwen3-30b-a3b`.

### Validation

- python3 -m py_compile app/graph.py app/chat_store.py app/server.py
- docker compose up -d --build
- curl -sS http://127.0.0.1/api/health
- docker exec fzu-chat python -c "from app.graph import KIMI_CHAT_MODEL, build_chat_llm; from langchain_core.messages import HumanMessage; llm=build_chat_llm(KIMI_CHAT_MODEL, temperature=0.1, streaming=False, thinking_enabled=True); first=llm.invoke([HumanMessage(content='请只用一句话回答：1+1等于几？')]); second=llm.invoke([HumanMessage(content='请只用一句话回答：1+1等于几？'), first, HumanMessage(content='继续只用一句话说明原因。')]); print(bool((first.additional_kwargs.get('reasoning_content') or '').strip())); print(second.content)"

---

## 福大灵犀 v3.1

福大灵犀 v3.1 重点修复了 Kimi K2.6 在华为云 MaaS 上的思考模式兼容性问题，并补齐了 v3.0 后的版本跟进。本次版本让 Kimi 的多轮思考模式真正可用：系统会保存并回放 `reasoning_content`，不再因为缺少推理字段而在后续轮次被 MaaS 拒绝；同时将对话标题总结模型切换为 `qwen3-30b-a3b`。

### 版本亮点

- 真正支持 Kimi K2.6 思考模式。后端现在会保留 Kimi 返回的 `reasoning_content`，在后续轮次把它重新带回 assistant 历史消息，并补齐当前 LangChain OpenAI 适配层缺失的字段传递，使 MaaS 不再因缺少推理元数据而拒绝多轮对话。
- 历史消息兼容持久化。assistant 消息除了正文和工具卡片外，现在还能存储推理元数据，新生成的 Kimi 对话可以在多轮之间持续保留模型所需上下文。
- 旧会话兼容兜底。对于还没有保存过推理字段的旧会话，系统会在回放给 Kimi 时补一个空的 `reasoning_content`，避免再次触发 `ModelArts.81001` 这类参数校验错误。
- 标题模型更新。对话标题总结模型已切换到 `qwen3-30b-a3b`，在保留现有短标题提示词行为的前提下提高稳定性。

### 本次发布包含

- 为 `langchain_openai` 增加兼容补丁，使 `reasoning_content` 能从 MaaS 响应中被解析、在流式 assistant chunk 中保留，并在后续 Kimi 请求里重新序列化。
- 消息存储结构演进，以及服务端对 assistant 推理元数据的持久化能力。
- 历史回放逻辑改为向 Kimi 发送带 `reasoning_content` 的 `AIMessage`，而不是把所有 assistant 历史都压平成普通文本。
- 标题总结模型更新为 `qwen3-30b-a3b`。

### 验证

- python3 -m py_compile app/graph.py app/chat_store.py app/server.py
- docker compose up -d --build
- curl -sS http://127.0.0.1/api/health
- docker exec fzu-chat python -c "from app.graph import KIMI_CHAT_MODEL, build_chat_llm; from langchain_core.messages import HumanMessage; llm=build_chat_llm(KIMI_CHAT_MODEL, temperature=0.1, streaming=False, thinking_enabled=True); first=llm.invoke([HumanMessage(content='请只用一句话回答：1+1等于几？')]); second=llm.invoke([HumanMessage(content='请只用一句话回答：1+1等于几？'), first, HumanMessage(content='继续只用一句话说明原因。')]); print(bool((first.additional_kwargs.get('reasoning_content') or '').strip())); print(second.content)"

---

## [v3.0] - 2026-04-27

FZU-Chat v3.0 focuses on privacy controls, security hardening, and more explicit user-facing state management. This release adds legal-document acceptance during login, a dedicated privacy and data-management area, stronger protection for educational-system sessions and browser write requests, and clearer rate-limit feedback for expensive chat actions.

### Highlights

- Privacy and legal onboarding. The frontend now exposes dedicated privacy-policy and user-agreement pages, requires explicit acceptance before login, and adds a privacy dashboard for reviewing stored-data scope and clearing saved data in one step.
- Stronger session and request protection. Logging out now clears cached educational-system session cookies, educational sessions expire independently, auth cookies default to a stricter SameSite mode, and unsafe browser write requests are checked for same-origin integrity.
- Security hardening for the API surface. The backend now sends a tighter Content Security Policy and additional browser security headers, while authentication, educational relogin, conversation creation, and message sending are all rate-limited.
- Clearer UX for costly operations. The frontend now distinguishes between creating conversations too quickly and sending messages too quickly, improving recovery guidance when users hit server-side rate limits.
- Ongoing conversation and model polish. This release line also carries forward unified thinking-mode control, richer title-generation behavior, improved feedback toggling, mobile login/legal-page refinements, and the expanded chat model lineup including Kimi K2.6.

### Included in this release

- Privacy-policy and user-agreement content, login-time consent gating, and a dedicated privacy/data page with per-user data summary plus one-click purge.
- Server-side helpers for counting and deleting saved conversations and active long-term memories.
- Logout-time educational-session cleanup, educational-session TTL handling, and relogin guidance when the educational connection expires.
- Browser write-request integrity checks, stricter cookie defaults, CSP and related hardening headers, plus rate limits for login, educational relogin, conversation creation, and message sending.
- Frontend error handling refinements so rate-limited create/send actions surface distinct, readable messages.
- Title-summary prompt tuning for shorter, more stable conversation titles.

### Validation

- cd frontend && npm run build
- python3 -m py_compile app/server.py app/chat_store.py app/memory_store.py app/graph.py
- docker compose up -d --build
- curl -sS http://127.0.0.1/api/health

---

## 福大灵犀 v3.0

福大灵犀 v3.0 重点提升隐私管理、安全加固和高成本操作的状态提示。本次版本加入了登录前协议确认、独立的隐私与数据管理入口、更严格的教务会话与浏览器写请求保护，以及更明确的限流反馈文案。

### 版本亮点

- 隐私与协议接入完善。前端新增隐私政策和用户协议页面，登录前必须显式勾选同意，并提供统一的隐私与数据页，用于查看已保存数据范围和一键清空。
- 会话与请求保护增强。退出登录时会同步清理服务端暂存的教务会话 Cookie；教务会话支持独立超时；认证 Cookie 默认使用更严格的 SameSite；浏览器发起的危险写操作会校验同源来源。
- API 安全面进一步收紧。后端新增更严格的 Content Security Policy 及其他安全响应头，并对登录、教务重新连接、创建对话和发送消息增加限流保护。
- 高成本操作提示更清晰。前端现在会明确区分“创建对话过快”和“发送消息过快”，用户命中后端限流时能看到更准确的恢复提示。
- 对话与模型体验继续打磨。该版本同时纳入统一思考模式开关、标题生成体验优化、反馈可取消、移动端登录与协议页适配，以及 Kimi K2.6 等模型能力扩展。

### 本次发布包含

- 隐私政策与用户协议正文、登录时强制确认、隐私与数据页、按用户统计已保存会话/消息/长期记忆，以及一键清空入口。
- 服务端会话与长期记忆的计数、批量删除能力。
- 退出登录时的教务会话清理、教务会话 TTL 控制，以及教务失效后的重新连接提示。
- 浏览器写请求同源校验、更严格的 Cookie 默认配置、CSP 与相关安全响应头，以及登录、教务重连、创建对话、发送消息的限流机制。
- 前端错误处理优化，使创建对话和发送消息在限流时展示不同的可读提示。
- 标题总结提示词与采样参数调整，使生成标题更短、更稳定。

### 验证

- cd frontend && npm run build
- python3 -m py_compile app/server.py app/chat_store.py app/memory_store.py app/graph.py
- docker compose up -d --build
- curl -sS http://127.0.0.1/api/health

---

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