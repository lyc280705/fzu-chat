# Changelog

This file tracks notable tagged releases for FZU-Chat.
本文件记录 FZU-Chat 的对外发布版本变更。

## [v2.0] - 2026-04-14

### Highlights / 亮点

- Added automatic teaching-week context from the FZU academic affairs system and cached semester week data for more accurate date-aware responses.
- Added a unified thinking mode toggle and mapped provider-specific thinking parameters consistently across the frontend and backend.
- Improved multi-model chat routing around GLM-5.1 and DeepSeek-V3.2, while keeping title summarization on Qwen.

### Changed / 变更

- Refactored streaming state management so send and stop actions are tracked per conversation instead of one global state.
- Hardened authentication token handling, logout cleanup, and expired educational-session relogin behavior.

### Fixed / 修复

- Recovered invalid streamed tool calls from model providers to prevent downstream tool execution failures.
- Fixed thinking indicator initialization and related UI state and style regressions.

## [v1.0] - 2026-04-08

### Initial Release / 首次发布

- Added student authentication and per-user conversation isolation.
- Added educational-system tools, memory tooling, and a React chat frontend with rich tool cards.
- Added Docker-based deployment and baseline knowledge retrieval with FAISS plus web-search fallback.