# Changelog

This file tracks notable tagged releases for FZU-Chat.
本文件记录 FZU-Chat 的对外发布版本变更。

## [v7.1] - 2026-05-19

FZU-Chat v7.1 fixes persisted tool-result continuity across turns. Tool cards still render as before, but completed tool calls are now replayed into later model history as LangChain `AIMessage(tool_calls=...)` plus matching `ToolMessage` entries so follow-up answers can use the original tool evidence.

### Highlights

- Persisted tool history. Completed tool parts are reconstructed into model history instead of being reduced to the assistant's final text.
- Original tool payload preservation. Newly streamed tool calls now store JSON-safe original `args` and raw `ToolMessage.content`; later turns prefer these original fields to avoid unnecessary context rewrites and cache churn.
- Legacy compatibility. Older conversations that do not have raw tool payloads still fall back to stable structured tool context, without UI-only status labels.
- Tool-only assistant turns are retained. Messages that contain completed tool results but little or no final assistant text are no longer dropped from the next model request.

### Validation

- `conda run -n langchain python -m compileall app`
- `conda run -n langchain python -m unittest discover tests`
- `cd frontend && npm run lint`
- `cd frontend && npm run build`

---

## 福大灵犀 v7.1

福大灵犀 v7.1 修复了工具调用结果跨轮对话不进入模型上下文的问题。界面上的工具卡片保持原有展示方式，但下一轮对话会把已完成的工具调用还原为 LangChain 的 `AIMessage(tool_calls=...)` 和对应 `ToolMessage`，让模型继续基于原始工具证据回答。

### 版本亮点

- 工具历史真正回灌。已完成的工具卡片不再只保留为最终助手文本，而是会被重建进后续模型历史。
- 原始工具载荷保留。新产生的工具调用会保存 JSON 安全的原始 `args` 和原始 `ToolMessage.content`；后续轮次优先使用这些原始字段，减少不必要的上下文重写和缓存失效。
- 兼容旧对话。历史对话没有原始工具载荷时，会退回到稳定结构化工具上下文，并避免把 UI 展示状态塞进模型上下文。
- 工具结果独立保留。即使某条助手消息只有工具结果、没有明显最终文本，也不会在下一轮模型请求中被丢弃。

### 验证

- `conda run -n langchain python -m compileall app`
- `conda run -n langchain python -m unittest discover tests`
- `cd frontend && npm run lint`
- `cd frontend && npm run build`

---

## [v7.0] - 2026-05-18

FZU-Chat v7.0 makes low-intrusion campus intelligence more cache-friendly and less UI-driven. Recommendation signals now live in a conversation-level runtime context snapshot, while the old prompt-button recommendation surface has been removed from the empty chat page and frontend remnants.

### Highlights

- Conversation-stable runtime context. A new conversation builds the short runtime `SystemMessage` once and stores it on the conversation; later turns append new messages without rewriting old prompt content.
- Long-context preservation. Chat history trimming now uses LangChain's approximate token counter and waits until roughly 200k tokens, reducing accidental loss of useful tool results.
- Teaching-week context. The backend warms a public JWCH teaching-week cache outside the educational tools and injects the cached week into runtime context when available.
- Smarter natural reminders. Near-meal windows now generate a lightweight dining hint even without a recent class, and the model can remind users to enable location or describe their campus/building instead of requiring a homepage button.
- Meal-time reminders no longer depend on a fresh course snapshot, so breakfast/lunch/dinner hints can still be injected when the academic snapshot cache is empty or expired.
- Recommendation cleanup. Removed the old click-to-send recommendation prompt UI path, including unused homepage recommendation panel styles and follow-up prompt buttons; explicit `recommend_campus_context` tool results still render as normal tool cards.
- Recommendation card polish. `recommend_campus_context` tool calls now show a Chinese scene/location summary and parse legacy JSON payloads into the dedicated recommendation card instead of exposing raw tool JSON.
- Place corrections. Removed the nonexistent staff-activity-center study area entry, kept Taoliyuan at the staff activity center, and verified dining/study recommendations avoid the inaccurate legacy locations.
- Snack-time dining removal. Removed snack-time (夜宵) period detection and context bonus logic; dining recommendations now focus on three main meals (breakfast, lunch, dinner).
- Empty-chat polish. The new-chat quick prompts keep the original three groups, with slightly roomier buttons and tighter unused bottom space without forcing scroll.

### Validation

- conda run -n langchain python -m compileall app
- conda run -n langchain python -m unittest discover tests
- cd frontend && npm run lint
- cd frontend && npm run build
- Browser/API smoke test with real educational login: location options, signal refresh, dining/study/auto recommendations, and a new-conversation SSE answer all completed successfully.

---

## 福大灵犀 v7.0

福大灵犀 v7.0 让低侵入校园智能更稳定、更利于缓存，也更少依赖界面按钮。推荐信号改为对话级运行时上下文快照，旧的“点击推荐按钮发送 prompt”入口和残留样式已从空对话页清理。

### 版本亮点

- 对话级运行时上下文。新对话只生成并保存一次短运行时 `SystemMessage`；后续回合只追加新消息，不反复改写旧提示内容。
- 长上下文保留。历史裁剪改用 LangChain 近似 token 计数，接近 200k token 才裁剪，减少工具结果在长对话中被过早删除。
- 教学周上下文。后端通过公开 JWCH 教学周接口后台预热缓存，不依赖教务工具；有缓存时会注入当前教学周。
- 更自然的提醒。接近饭点时即使没有刚下课信号，也会生成轻量食堂提醒；缺少定位时模型会自然提示用户开启定位或说明所在校区/教学楼，而不是让用户点首页推荐按钮。
- 饭点提醒不再依赖新鲜课表快照，即使教务摘要缓存为空或过期，也能在早餐、午餐、晚餐时段注入轻量提醒。
- 推荐入口清理。删除旧的点击发送推荐 prompt UI 链路，包括未使用的首页推荐面板样式和追问 prompt 按钮；用户明确询问时的 `recommend_campus_context` 工具结果仍作为普通工具卡片展示。
- 推荐卡片打磨。`recommend_campus_context` 工具调用现在显示中文场景/位置摘要，并把历史 JSON 载荷解析成专用推荐卡片，不再直接暴露原始工具 JSON。
- 地点纠偏。移除不存在的教工活动中心公共学习区，保留位于教工活动中心的桃李园餐厅，并验证食堂/自习推荐不会返回旧的不准确地点。
- 夜宵功能移除。移除夜宵(22:00-24:00)时段检测和上下文加权逻辑，食堂推荐现聚焦三个主要餐饮时段(早餐、午餐、晚餐)。
- 新对话页微调。保留原有三组快捷问题，只让按钮略微宽松，并减少下方空白，同时避免首屏滚动。

### 验证

- conda run -n langchain python -m compileall app
- conda run -n langchain python -m unittest discover tests
- cd frontend && npm run lint
- cd frontend && npm run build
- 真实教务登录浏览器/API 冒烟测试：位置列表、信号刷新、食堂/自习/自动推荐和新对话 SSE 回复均正常完成。

---

## [v6.2] - 2026-05-18

FZU-Chat v6.2 replaces the prominent homepage suggestion card with low-intrusion dynamic context. Campus reminders now come from cached academic summaries injected into a short runtime system message, allowing the model to decide whether a natural end-of-answer reminder is useful without delaying the first response.

### Highlights

- Low-latency dynamic context. The stable system prompt is separated from runtime context so the long prompt remains cache-friendly; current time, confirmed memory, and campus events live in a second short `SystemMessage`.
- No blocking reminder fetches. Login, educational reconnect, and the privacy location switch can refresh course, exam, course-selection, and grade-summary snapshots in the background; message generation only reads fresh cached summaries and skips reminders when data is unavailable.
- Reminder suppression. The backend records only event type, digest, cooldown, and expiry so grades, full schedules, exam locations, and coordinates are not persisted in reminder state.
- Natural reminder coverage. Generic follow-ups such as “what should I pay attention to today” now count as dynamic-context requests, and exam reminders cool down daily so early reminders do not suppress the 48-hour exam window.
- Less intrusive frontend. Empty chats no longer show automatic “Today’s suggestions”; location is managed from Privacy & Data and is used only as transient context when sending the first message of a new conversation.
- Better mobile sidebar. The mobile drawer is narrower, denser, and gives the conversation history list its own scrollable space at 390px widths.

### Validation

- conda run -n langchain python -m compileall app
- conda run -n langchain python -m unittest tests.test_campus_dynamic_context tests.test_campus_recommendations
- cd frontend && npm run lint
- cd frontend && npm run build
- Live browser smoke test with real educational login: first message in a new conversation injected the cached exam signal and produced a natural reminder within the assistant reply.

---

## 福大灵犀 v6.2

福大灵犀 v6.2 将突出的首页建议卡片重构为低侵入动态上下文提醒。校园提醒来自后台缓存的教务摘要，并注入到短运行时 system 消息中，由模型判断是否在回答末尾自然提醒，不再拖慢首轮响应。

### 版本亮点

- 低延迟动态上下文。稳定主提示词与运行时上下文拆分，长提示词尽量保持缓存友好；当前时间、确认记忆和校园事件放入第二条短 `SystemMessage`。
- 不阻塞消息发送。登录、教务重连和隐私页定位开关会后台刷新课表、考试、选课和成绩摘要；生成回复时只读新鲜缓存，读不到就跳过提醒。
- 重复提醒抑制。后端仅记录事件类型、digest、冷却时间和过期时间，不把成绩明细、完整课表、考试地点或经纬度写入提醒状态。
- 自然提醒覆盖。类似“今天有什么需要注意”的泛问会触发动态上下文；考试提醒按每日冷却，避免提前提醒一次后覆盖临近 48 小时的复习窗口。
- 前端更克制。空对话不再自动展示“今日建议”；定位集中在隐私页管理，只在新对话首条消息发送时作为临时上下文使用。
- 移动侧栏修复。移动抽屉更窄、更紧凑，390px 宽度下历史对话列表拥有独立滚动空间。

### 验证

- conda run -n langchain python -m compileall app
- conda run -n langchain python -m unittest tests.test_campus_dynamic_context tests.test_campus_recommendations
- cd frontend && npm run lint
- cd frontend && npm run build
- 真实教务登录浏览器冒烟测试：新对话首条消息成功注入缓存考试信号，并在助手回复中自然提醒。

---

## [v6.1] - 2026-05-17

FZU-Chat v6.1 expands contextual recommendations from dining/study hints into broader campus intelligence. The homepage can now surface course-selection windows, grade-summary changes, exam prep, class-location-aware study spots, and corrected FZU place recommendations.

### Highlights

- Wider recommendation scope. “Today’s suggestions” now considers open or upcoming course-selection windows, soon-ending selection periods, grade-summary digest changes, upcoming exams, recent/next classes, meal periods, and campus location.
- Better place intelligence. The built-in place library now includes Taoliyuan at the staff activity center, Haitangyuan, Jinjiang Building Learning Center, and more manual fallback locations; the inaccurate “Innovation Building public learning area” entry was removed.
- Smarter ranking. When browser location is unavailable, the service can infer an approximate origin from course locations such as Jinjiang Building, library, teaching buildings, living areas, Yishan, or Tongpan. Study and dining candidates are ranked by both walking cost and contextual fit.
- Privacy-preserving grade awareness. Grade-change recommendations compare only a browser-local digest and do not persist grade details, locations, course schedules, or exam arrangements to recommendation storage.
- Deployment clarity. The UI and docs now explain that mobile geolocation requires HTTPS; plain HTTP server URLs will not show the browser permission prompt.

### Validation

- conda run -n langchain python -m compileall app
- conda run -n langchain python -m unittest tests.test_campus_recommendations
- cd frontend && npm run lint
- cd frontend && npm run build

---

## 福大灵犀 v6.1

福大灵犀 v6.1 将情境推荐从食堂/自习提示扩展为更完整的校园智能建议。首页现在可以主动展示选课窗口、成绩摘要变化、考试复习、结合课程地点的自习推荐和更准确的福大地点建议。

### 版本亮点

- 推荐范围扩展。“今日建议”现在会综合正在进行或即将开始的选课、即将截止的选课窗口、成绩摘要变化、近期考试、刚下课/下一节课、饭点和校园位置。
- 地点库纠偏。补充桃李园餐厅（教工活动中心位置）、海棠园餐厅、晋江楼学习中心和更多手动位置兜底；移除不准确的“创新楼公共学习区”。
- 排序更智能。无浏览器定位时，可根据晋江楼、图书馆、教学楼、生活区、怡山、铜盘等课表地点推断推荐起点；自习与食堂候选会同时考虑步行成本和场景匹配度。
- 成绩提醒保护隐私。成绩变化只比较浏览器本地摘要哈希，不把成绩明细、当前位置、课表或考试安排写入推荐状态。
- 部署说明更清晰。界面和文档明确提示手机定位需要 HTTPS，普通 HTTP 服务器地址不会弹出浏览器定位授权。

### 验证

- conda run -n langchain python -m compileall app
- conda run -n langchain python -m unittest tests.test_campus_recommendations
- cd frontend && npm run lint
- cd frontend && npm run build

---

## [v6.0] - 2026-05-17

FZU-Chat v6.0 adds contextual campus recommendations. The chat home now surfaces lightweight “Today’s suggestions” from live course/exam context and current time, with optional location optimization managed from the privacy page.

### Highlights

- Smart homepage suggestions. Empty chats automatically show dining, study, or exam-prep prompts above the standard quick actions, without requiring users to choose a scenario first.
- Privacy-managed location. Users enable location optimization from “Privacy & Data”; once browser permission is granted, the homepage can use one-time location automatically for recommendations.
- AMap-backed campus routing. The backend keeps the AMap Web Service key server-side, supports Docker secrets and local `amap_web_service_key.txt`, throttles requests to 5 QPS, and falls back to the built-in FZU place library.
- Agent integration. The `recommend_campus_context` tool lets chat questions such as “where should I eat or study now” reuse the same recommendation service.
- Compact empty state. The new-chat page is denser so the main recommendations and quick actions fit in the first viewport more often.

### Validation

- conda run -n langchain python -m compileall app
- conda run -n langchain python -m unittest tests.test_campus_recommendations
- cd frontend && npm run lint
- cd frontend && npm run build
- Browser smoke test for logged-in homepage suggestions and privacy-page location controls

---

## 福大灵犀 v6.0

福大灵犀 v6.0 新增情境校园推荐。聊天首页会基于实时课表、考试安排和当前时段自动出现轻量“今日建议”，定位优化则集中放在“隐私与数据”页面管理。

### 版本亮点

- 首页智能建议。空对话会自动展示食堂、自习或考试复习建议，放在常规快捷问题上方，不需要用户先判断场景。
- 隐私页统一管理定位。用户在“隐私与数据”中开启定位优化；浏览器授权后，首页后续可自动使用一次性位置优化推荐。
- 高德地图后端集成。高德 Web 服务 Key 只留在后端，支持 Docker secret 和本地 `amap_web_service_key.txt`，请求默认限速 5 QPS，并可降级到内置福大地点库。
- Agent 工具接入。新增 `recommend_campus_context`，用户在聊天中问“现在去哪吃/去哪自习”也能复用同一套推荐服务。
- 空状态压缩。新对话页更紧凑，尽量让今日建议与常用快捷入口在首屏内可见。

### 验证

- conda run -n langchain python -m compileall app
- conda run -n langchain python -m unittest tests.test_campus_recommendations
- cd frontend && npm run lint
- cd frontend && npm run build
- 登录态浏览器冒烟测试：首页今日建议、隐私页定位控制

---

## [v5.0] - 2026-05-17

FZU-Chat v5.0 is a full interaction-experience release. It tightens the main chat loop with ChatGPT-style edit, copy, and regenerate actions; makes stopped streams preserve already generated content; improves mobile layout and local development startup; and adds accessibility affordances across the chat surface.

### Highlights

- Stopped responses now preserve generated content. If a user stops streaming, visible assistant text and completed tool parts remain available unless the user explicitly regenerates the response or edits the original user message.
- ChatGPT-style message actions. Users can copy a message with a clipboard fallback, regenerate an assistant response from the previous user prompt, or edit a sent user message and rebuild the following response branch.
- Branch-safe rerun behavior. `POST /api/conversations/{id}/messages` accepts `rerun_message_id` to truncate later history, optionally update the original user message, and stream a replacement assistant response without changing the SSE event format.
- Accessibility improvements. The UI now includes a skip link, clearer focus handling, screen-reader status announcements, a live chat log, dialog focus management, explicit composer labels, and stronger keyboard affordances.
- Mobile and visual polish. The mobile sidebar button no longer overlaps the chat title, the stop button uses a softer pause affordance, message action buttons are always visible, icon-only, and tooltip-backed, the scroll-to-bottom button sits farther to the right, and message/tool states are easier to scan.
- Native search clearing. The conversation-history search field now relies on the browser-native clear control, avoiding duplicate clear buttons in the sidebar.
- Localized tool states. Memory and tool-card status summaries now translate persisted states such as `saved`, `submitted`, and `success` into Chinese labels, including older conversation cards.
- Local key-file fallback. Development servers can read root-level `*_api_key.txt` files when container secrets and environment variables are unavailable.

### Included in this release

- Frontend safeguards that merge a stopped server response with the current visible draft when needed, preventing already rendered content from being replaced by a generic stopped message.
- Backend text recovery from persisted message parts before falling back to `已停止响应。`.
- Conversation-store support for truncating after an existing user message, which powers edit-and-regenerate flows.
- Login, sidebar, composer, privacy reset, message action, feedback, tool-card, and mobile table UX improvements from the interaction-optimization pass.
- API and documentation version updates for v5.0.

### Validation

- conda run -n langchain python -m compileall app
- cd frontend && npm run lint
- cd frontend && npm run build
- Temporary SQLite rerun-store smoke test
- Browser smoke test at 390px mobile width for header layout, stop button, stopped response state, copy, edit, and regenerate actions

---

## 福大灵犀 v5.0

福大灵犀 v5.0 是一次完整的人机交互体验发布。主聊天链路新增类似 ChatGPT 的复制、重新生成和修改已发送消息能力；停止流式响应后会保留已经生成的内容；同时补齐移动端布局、本地开发启动和无障碍体验。

### 版本亮点

- 停止响应后保留已生成内容。用户停止流式输出时，已经可见的助手文本和已完成工具结果会保留下来；只有点击重新生成或修改原始用户消息时，后续回复分支才会被替换。
- ChatGPT 风格消息操作。用户可以复制消息，复制操作带剪贴板兜底；也可以基于上一条用户问题重新生成助手回复，或修改已发送的问题并重建后续回答。
- 分支安全的重跑行为。`POST /api/conversations/{id}/messages` 支持 `rerun_message_id`，可截断后续历史、按需更新原始用户消息，并沿用原 SSE 事件格式流式返回新回复。
- 无障碍增强。界面补充跳过链接、清晰焦点、屏幕阅读器状态播报、聊天日志 live region、弹窗焦点管理、输入框显式标签和更稳定的键盘操作。
- 移动端与视觉打磨。移动端侧栏按钮不再遮挡标题，停止按钮改为更柔和的暂停图标，消息操作按钮常显、统一为纯图标并保留悬浮提示，“回到底部”按钮进一步右移，消息与工具状态更易扫读。
- 原生搜索清除。对话历史搜索框改用浏览器原生清除按钮，避免侧栏右侧出现两个叉。
- 工具状态中文化。记忆和工具卡片摘要会把 `saved`、`submitted`、`success` 等已持久化状态映射为中文，也能覆盖旧会话卡片。
- 本地密钥文件兜底。开发环境在没有容器 secret 或环境变量时，可读取项目根目录的 `*_api_key.txt` 文件启动。

### 本次发布包含

- 前端在停止响应时用当前可见草稿兜底合并服务端 stopped 消息，避免已渲染内容被通用“已停止响应”覆盖。
- 后端在落库前从消息 parts 恢复正文，只有没有任何可保存内容时才使用 `已停止响应。`。
- 对话存储新增按既有用户消息截断后续历史的能力，用于修改消息和重新生成。
- 登录、侧栏、输入区、隐私清空、消息操作、反馈、工具卡片和移动端表格等交互优化。
- API 与说明文档版本更新到 v5.0。

### 验证

- conda run -n langchain python -m compileall app
- cd frontend && npm run lint
- cd frontend && npm run build
- 临时 SQLite 重跑分支存储测试
- 390px 移动端浏览器冒烟测试：标题布局、停止按钮、停止后的回复状态、复制、修改和重新生成

---

## [v4.0] - 2026-05-16

FZU-Chat v4.0 upgrades long-term memory from a simple confirmed note list into an FZU-aware personalization layer. The assistant now distinguishes durable user preferences from volatile academic facts, ranks memories by relevance and usefulness, blocks sensitive or short-lived data, and injects only high-value confirmed memory into the conversation context.

### Highlights

- FZU-aware personalized memory. Long-term memory now focuses on reusable campus scenarios such as name preferences, answer style, course-selection habits, academic-query presentation preferences, campus-life needs, dining preferences, and campus-location preferences.
- Clear boundary between memory and live educational data. Grades, GPA, rankings, credits, schedules, exam rooms, selected-course results, student profile facts, program-plan text, and calendar dates are kept out of memory and should be queried live through educational tools.
- Smarter memory retrieval and deduplication. Memory storage now keeps normalized text, keywords, importance, access counts, and last-access timestamps, then ranks matches by relevance, importance, recent usage, and recency.
- Safer memory proposals. Save requests are validated for long-term value, sensitive data, short-lived facts, and near-duplicate content before the user sees a confirmation card.
- Better memory management UX. Memory cards now show importance, match scores, duplicate similarity, and validation reasons so users can understand why a memory was suggested or rejected.
- Model lineup refresh. The selectable DeepSeek route is now DeepSeek V4 Pro, with title summarization continuing on `qwen3-30b-a3b`.

### Included in this release

- SQLite schema migration for `normalized_content`, `keywords`, `importance`, `access_count`, and `last_accessed_at`.
- Chinese-aware tokenization and similarity matching for memory search, duplicate detection, and deletion-by-content suggestions.
- FZU-specific category aliases and validation rules for course, selection, academic-query, campus-life, campus, and dining preferences.
- Prompt updates that instruct the agent to use confirmed memory only when relevant and to keep volatile academic facts in live educational-tool queries.
- Frontend memory-card improvements for importance, match score, similarity, and validation messaging.
- API and documentation version updates for v4.0.

### Validation

- python -m compileall app
- temporary SQLite memory-policy smoke test for save, confirm, dedupe, invalid academic facts, identity-fact blocking, retrieval ranking, and delete-by-similar-content
- cd frontend && npm run build
- cd frontend && npm run lint
- git diff --check

---

## 福大灵犀 v4.0

福大灵犀 v4.0 将长期记忆从“确认后保存的简单备注”升级为面向福大场景的个性化能力。系统现在会区分可长期复用的用户偏好和应实时查询的教务事实，并根据相关性、重要度、使用痕迹与更新时间综合检索记忆。

### 版本亮点

- 福大场景个性化记忆。长期记忆现在重点服务称呼偏好、回答风格、选课习惯、教务查询展示偏好、校园生活需求、餐饮偏好和校区偏好等可复用场景。
- 明确区分记忆与实时教务数据。成绩、绩点、排名、学分、课表、考场、考试安排、选课结果、学生身份事实、培养方案正文和校历日期不会写入长期记忆，应通过教务工具实时查询。
- 更智能的记忆检索与去重。记忆存储新增规范化文本、关键词、重要度、访问次数和最近访问时间，并按相关性、重要度、最近使用与更新时间综合排序。
- 更安全的记忆建议。保存建议会先经过长期价值、敏感信息、临时事实和相似重复检测，再展示给用户确认。
- 更清楚的记忆管理卡片。前端会展示重要度、匹配分、相似度和校验失败原因，用户能更直观看懂系统为什么建议保存或拒绝保存。
- 模型列表更新。DeepSeek 路由更新为 DeepSeek V4 Pro，标题总结继续使用 `qwen3-30b-a3b`。

### 本次发布包含

- 为长期记忆 SQLite 表增加 `normalized_content`、`keywords`、`importance`、`access_count`、`last_accessed_at` 的兼容迁移。
- 面向中文表达的分词与相似度匹配，用于记忆搜索、重复检测和按内容删除建议。
- 针对课程、选课、教务查询、校园生活、校区和餐饮偏好的福大专属分类别名与校验规则。
- 提示词更新：只在相关时使用已确认记忆，并要求成绩、课表、考场等易变事实继续实时调用教务工具。
- 前端记忆卡片补充重要度、匹配分、相似度和校验原因展示。
- API 与说明文档版本更新到 v4.0。

### 验证

- python -m compileall app
- 临时 SQLite 记忆策略测试：保存建议、确认写入、相似去重、教务事实拒绝、身份事实拦截、检索排序、按相似内容删除建议
- cd frontend && npm run build
- cd frontend && npm run lint
- git diff --check

---

## [v3.2] - 2026-04-28

FZU-Chat v3.2 focuses on polishing post-v3.1 chat behavior. This release fixes a model-selection regression when users start a new conversation while another one is still streaming, and moves the blank pre-tool-call chunk fix fully into the backend so Kimi's leading whitespace deltas are suppressed at the source instead of being hidden in the frontend.

### Highlights

- Backend-first Kimi stream cleanup. The server now ignores leading whitespace-only assistant deltas before any visible reply text has been emitted, preventing empty markdown containers ahead of tool cards without relying on frontend filtering.
- Stable model switching during concurrent streams. Creating or opening a new conversation while another conversation is still streaming no longer resets the model selector to the active stream's model.
- Cleaner responsibility split. The blank pre-tool-call rendering issue is now solved in the streaming pipeline itself, while the frontend keeps rendering ordinary whitespace and markdown content normally.

### Included in this release

- A server-side stream-delta gate that suppresses meaningless leading whitespace chunks but preserves normal spaces and newlines once visible assistant text has started.
- A narrower model-sync effect in the chat composer so only the active conversation's model can update the current selector.
- Removal of the temporary frontend whitespace workaround that had been added while diagnosing the Kimi tool-call issue.

### Validation

- cd frontend && npm run build
- python3 -m py_compile app/server.py
- docker compose up -d --build
- docker exec fzu-chat python -c "from app.server import should_emit_stream_delta; assert should_emit_stream_delta('', '你好'); assert not should_emit_stream_delta('', '  \\n\\t'); assert should_emit_stream_delta('已输出正文', '  \\n'); print('ok')"
- curl -sS http://127.0.0.1/api/health

---

## 福大灵犀 v3.2

福大灵犀 v3.2 继续收敛 v3.1 之后的对话体验问题。本次版本修复了“有对话正在流式输出时，新建对话无法稳定切换模型”的前端状态回退问题，并把 Kimi 在工具调用前出现空白块的问题彻底下沉到后端处理，从源头抑制无意义的前导空白 chunk，而不是继续依赖前端兜底隐藏。

### 版本亮点

- 后端根修复 Kimi 空白 chunk。服务端现在会在 assistant 还没输出任何可见正文前，忽略纯空白的流式增量，避免工具卡片前再出现空白 markdown 容器，同时不影响正常正文中的空格和换行。
- 并发流式场景下模型切换恢复稳定。当一个旧对话仍在流式输出时，新建或切换到其他对话不再被旧对话的模型回写覆盖。
- 前后端职责重新收敛。空白块问题已经在流式管线根上解决，前端恢复普通渲染逻辑，不再承担专门掩盖这类异常 chunk 的职责。

### 本次发布包含

- 服务端新增流式 delta 判定，抑制无意义的前导纯空白 chunk，同时保留已开始输出正文后的正常空格和换行。
- 聊天输入区的模型同步 effect 收窄为只响应当前活动对话的模型变化。
- 删除排查 Kimi 工具调用问题时临时加入的前端空白过滤兜底。

### 验证

- cd frontend && npm run build
- python3 -m py_compile app/server.py
- docker compose up -d --build
- docker exec fzu-chat python -c "from app.server import should_emit_stream_delta; assert should_emit_stream_delta('', '你好'); assert not should_emit_stream_delta('', '  \\n\\t'); assert should_emit_stream_delta('已输出正文', '  \\n'); print('ok')"
- curl -sS http://127.0.0.1/api/health

---

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
