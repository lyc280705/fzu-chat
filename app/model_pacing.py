"""Pace chat-completion requests to the model provider.

Huawei MaaS limits each model's requests per minute (RPM) and tokens per minute (TPM), and
also rejects more than 4 requests/s (ModelArts.81101), so when many students press send
together most calls would fail. Every model request goes through one shared httpx transport
that spaces request starts per model to stay under both limits, queues callers up to a
bounded wait, and retries provider 429s. A caller that would wait past the bound gets
an immediate local 429 marked not-retryable, which the chat stream reports as "busy".
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from threading import Lock
from typing import Dict

import httpx

from .runtime_state import increment_counter

logger = logging.getLogger(__name__)

# "model=RPM/TPM" from Huawei's model list (checked 2026-09-29):
# https://support.huaweicloud.com/intl/zh-cn/model-list-maas/model_list_0001.html
# kimi-k2.6 and qwen3-30b-a3b are not listed; kimi was rejected above about 1 request/s.
DEFAULT_MODEL_LIMITS = "glm-5.3=100/1000000,deepseek-v4.1-flash=100/1000000,qwen3-30b-a3b=100/1000000,kimi-k2.6=48/1000000"
QUEUE_FULL_CODE = "FZU.MODEL_QUEUE_FULL"
# Stay slightly under the published limits; retries and clock skew also count against them.
LIMIT_SAFETY = 0.95
# Tokens may run this many seconds ahead of the steady TPM rate before requests are delayed.
TOKEN_BURST_SECONDS = 10.0
# Request tokens are estimated from characters plus room for the reply. A real glm-5.3 chat request
# measured 0.45 prompt tokens per character (6,916 chars, 3,119 tokens); 0.6 leaves some margin.
TOKENS_PER_CHAR = 0.6
OUTPUT_TOKEN_RESERVE = 2000


def _parse_limits(value: str) -> Dict[str, tuple[float, float]]:
    limits: Dict[str, tuple[float, float]] = {}
    for item in value.split(","):
        name, _, pair = item.partition("=")
        rpm, _, tpm = pair.partition("/")
        try:
            if name.strip() and float(rpm) > 0 and float(tpm) > 0:
                limits[name.strip()] = (float(rpm), float(tpm))
        except ValueError:
            logger.warning("Ignoring invalid model limit %r", item)
    return limits


MODEL_LIMITS = _parse_limits(os.getenv("FZU_CHAT_MODEL_LIMITS", DEFAULT_MODEL_LIMITS))
DEFAULT_LIMIT = _parse_limits("default=" + os.getenv("FZU_CHAT_MODEL_DEFAULT_LIMIT", "100/1000000")).get("default", (100.0, 1_000_000.0))
MAX_QUEUE_SECONDS = max(1.0, float(os.getenv("FZU_CHAT_MODEL_QUEUE_MAX_SECONDS", "45")))
RATE_LIMIT_RETRIES = max(0, int(os.getenv("FZU_CHAT_MODEL_RATE_LIMIT_RETRIES", "4")))


class ModelQueueFull(Exception):
    pass


class RequestPacer:
    """Hands out request start times per model that respect its RPM and TPM.

    Requests are spaced evenly at the RPM rate (100 RPM is one every 0.63 s, well under 4/s).
    Tokens use a leaky bucket that may run TOKEN_BURST_SECONDS ahead of the TPM rate.
    """

    def __init__(self, limits: Dict[str, tuple[float, float]], default_limit: tuple[float, float], max_wait: float):
        self.limits = dict(limits)
        self.default_limit = default_limit
        self.max_wait = max_wait
        self._state: Dict[str, tuple[float, float]] = {}
        self._lock = Lock()

    def reserve(self, model: str, tokens: int = 0) -> float:
        """Return how long the caller must wait before sending, or raise ModelQueueFull."""
        rpm, tpm = self.limits.get(model, self.default_limit)
        interval = 60.0 / (rpm * LIMIT_SAFETY)
        token_seconds = max(0, tokens) * 60.0 / (tpm * LIMIT_SAFETY)
        with self._lock:
            now = time.monotonic()
            next_request, token_time = self._state.get(model, (0.0, 0.0))
            start = max(now, next_request, token_time - TOKEN_BURST_SECONDS)
            if start - now > self.max_wait:
                raise ModelQueueFull(model)
            self._state[model] = (start + interval, max(token_time, start) + token_seconds)
            return start - now

    def queued_seconds(self, model: str) -> float:
        with self._lock:
            next_request, _ = self._state.get(model, (0.0, 0.0))
            return max(0.0, next_request - time.monotonic())


pacer = RequestPacer(MODEL_LIMITS, DEFAULT_LIMIT, MAX_QUEUE_SECONDS)


def _request_model(request: httpx.Request) -> tuple[str, int] | None:
    """Return (model, estimated tokens) for chat completions; None for other requests."""
    if request.method != "POST" or not request.url.path.endswith("/chat/completions"):
        return None
    try:
        payload = json.loads(request.content)
        model = str(payload.get("model") or "")
    except (ValueError, AttributeError, httpx.RequestNotRead):
        return None
    if not model:
        return None
    prompt = json.dumps([payload.get("messages"), payload.get("tools")], ensure_ascii=False)
    reply = payload.get("max_tokens") or payload.get("max_completion_tokens") or OUTPUT_TOKEN_RESERVE
    return model, int(len(prompt) * TOKENS_PER_CHAR) + int(reply)


def _queue_full_response(request: httpx.Request, model: str) -> httpx.Response:
    increment_counter("fzu_chat_model_queue_full_total")
    logger.warning("Model queue full for %s (%.0fs ahead)", model, pacer.queued_seconds(model))
    return httpx.Response(
        429,
        headers={"x-should-retry": "false"},
        json={"error": {"code": QUEUE_FULL_CODE, "message": "model request queue is full", "type": "TooManyRequests"}},
        request=request,
    )


def _retry_delay(attempt: int) -> float:
    return 0.4 * (attempt + 1) + random.uniform(0, 0.4)


class PacedTransport(httpx.BaseTransport):
    def __init__(self, inner: httpx.BaseTransport):
        self.inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        target = _request_model(request)
        if target is None:
            return self.inner.handle_request(request)
        model, tokens = target
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                delay = pacer.reserve(model, tokens)
            except ModelQueueFull:
                return _queue_full_response(request, model)
            if delay > 0:
                time.sleep(delay)
            response = self.inner.handle_request(request)
            if response.status_code != 429 or attempt == RATE_LIMIT_RETRIES:
                return response
            response.read()
            response.close()
            increment_counter("fzu_chat_model_rate_limited_total")
            time.sleep(_retry_delay(attempt))
        return response

    def close(self) -> None:
        self.inner.close()


class AsyncPacedTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport):
        self.inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        target = _request_model(request)
        if target is None:
            return await self.inner.handle_async_request(request)
        model, tokens = target
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                delay = pacer.reserve(model, tokens)
            except ModelQueueFull:
                return _queue_full_response(request, model)
            if delay > 0:
                await asyncio.sleep(delay)
            response = await self.inner.handle_async_request(request)
            if response.status_code != 429 or attempt == RATE_LIMIT_RETRIES:
                return response
            await response.aread()
            await response.aclose()
            increment_counter("fzu_chat_model_rate_limited_total")
            await asyncio.sleep(_retry_delay(attempt))
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


_LIMITS = httpx.Limits(max_connections=256, max_keepalive_connections=64)
_clients_lock = Lock()
_sync_client: httpx.Client | None = None
_async_client: httpx.AsyncClient | None = None


def model_http_clients() -> tuple[httpx.Client, httpx.AsyncClient]:
    """Shared paced clients for every ChatOpenAI instance, so pacing covers all callers."""
    global _sync_client, _async_client
    with _clients_lock:
        if _sync_client is None:
            _sync_client = httpx.Client(transport=PacedTransport(httpx.HTTPTransport(limits=_LIMITS)), follow_redirects=True)
        if _async_client is None:
            _async_client = httpx.AsyncClient(transport=AsyncPacedTransport(httpx.AsyncHTTPTransport(limits=_LIMITS)), follow_redirects=True)
        return _sync_client, _async_client


def is_model_busy_error(exc: BaseException) -> bool:
    """True for provider 429s that survived retries and for local queue-full rejections."""
    return getattr(exc, "status_code", None) == 429
