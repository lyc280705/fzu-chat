"""Stepped load test for a running FZU-Chat deployment.

Two modes, each run as a series of concurrency steps:

  http  Repeatedly GET one path for --duration seconds per step.
        python scripts/load_test.py http --base https://example.cn --path /api/health \
            --steps 10,25,50,100,200 --duration 20 --out .benchmarks/loadtest

        With --tokens-file, requests carry the first token (for signed-in endpoints).

  chat  Send one real chat message per concurrent stream and read the SSE reply.
        Needs a JSON file listing session tokens, one per test account; each stream
        uses its own account and conversation. This calls the model and costs money.
        python scripts/load_test.py chat --base https://example.cn --tokens-file tokens.json \
            --steps 1,4,8,12,16 --out .benchmarks/loadtest

A step whose error rate exceeds --max-error-rate stops the escalation. Results are
written as JSON lines (one per step) plus per-request CSV rows.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path
import statistics
import time
from typing import Any, Dict, List

import aiohttp

CHAT_QUESTIONS = [
    "福州大学图书馆的开放时间是怎样的？",
    "福州大学本科生转学需要满足哪些条件？",
    "福州大学学生申请查询试卷的流程是什么？",
    "补办毕业证明书需要准备什么材料？",
    "福州大学课程安排管理办法对调课有什么规定？",
    "福州大学网球馆的开放和预约规定是什么？",
    "赴高水平大学访学交流的课程学分怎么认定？",
    "福州大学体育课的学时和考核是怎么安排的？",
]


def percentile(values: List[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[index], 4)


def summarize(step: int, rows: List[Dict[str, Any]], elapsed: float, extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    ok = [row for row in rows if row["ok"]]
    latencies = [row["seconds"] for row in ok]
    statuses: Dict[str, int] = {}
    for row in rows:
        statuses[str(row["status"])] = statuses.get(str(row["status"]), 0) + 1
    summary = {
        "concurrency": step,
        "requests": len(rows),
        "ok": len(ok),
        "errors": len(rows) - len(ok),
        "error_rate": round((len(rows) - len(ok)) / len(rows), 4) if rows else None,
        "rps": round(len(rows) / elapsed, 2) if elapsed else None,
        "p50": percentile(latencies, 0.50),
        "p95": percentile(latencies, 0.95),
        "p99": percentile(latencies, 0.99),
        "mean": round(statistics.mean(latencies), 4) if latencies else None,
        "statuses": statuses,
        "elapsed": round(elapsed, 2),
    }
    summary.update(extra or {})
    return summary


async def http_step(session: aiohttp.ClientSession, url: str, concurrency: int, duration: float,
                    headers: Dict[str, str] | None = None) -> tuple[List[Dict[str, Any]], float]:
    rows: List[Dict[str, Any]] = []
    deadline = time.perf_counter() + duration

    async def worker() -> None:
        while time.perf_counter() < deadline:
            start = time.perf_counter()
            status: Any = "exception"
            try:
                async with session.get(url, headers=headers) as response:
                    await response.read()
                    status = response.status
            except Exception as exc:
                status = type(exc).__name__
            seconds = time.perf_counter() - start
            rows.append({"t": time.time(), "status": status, "ok": status == 200, "seconds": seconds})

    begin = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return rows, time.perf_counter() - begin


async def chat_stream(session: aiohttp.ClientSession, base: str, token: str, cid: str, question: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Origin": base}
    start = time.perf_counter()
    first_chunk = None
    events: Dict[str, int] = {}
    status: Any = "exception"
    ok = False
    try:
        async with session.post(f"{base}/api/conversations/{cid}/messages", json={"content": question}, headers=headers) as response:
            status = response.status
            if response.status == 200:
                event = ""
                async for raw in response.content:
                    line = raw.decode("utf-8", "replace").strip()
                    if line.startswith("event:"):
                        event = line[6:].strip()
                        events[event] = events.get(event, 0) + 1
                        if event == "chunk" and first_chunk is None:
                            first_chunk = time.perf_counter() - start
                    if event in {"done", "error"} and line.startswith("data:"):
                        break
                ok = "done" in events and "error" not in events
            else:
                await response.read()
    except Exception as exc:
        status = type(exc).__name__
    return {"t": time.time(), "status": status, "ok": ok, "seconds": time.perf_counter() - start,
            "first_chunk": first_chunk, "events": events}


async def ensure_conversations(session: aiohttp.ClientSession, base: str, tokens: List[str]) -> List[str]:
    conversations = []
    for token in tokens:
        headers = {"Authorization": f"Bearer {token}", "Origin": base}
        async with session.post(f"{base}/api/conversations", json={}, headers=headers) as response:
            response.raise_for_status()
            conversations.append((await response.json())["id"])
    return conversations


def write_rows(path: Path, rows: List[Dict[str, Any]], step: int) -> None:
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new:
            writer.writerow(["concurrency", "unix_time", "status", "ok", "seconds", "first_chunk_seconds", "events"])
        for row in rows:
            writer.writerow([step, round(row["t"], 3), row["status"], int(row["ok"]), round(row["seconds"], 4),
                             "" if row.get("first_chunk") is None else round(row["first_chunk"], 4),
                             json.dumps(row.get("events") or {}, ensure_ascii=False)])


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["http", "chat"])
    parser.add_argument("--base", required=True)
    parser.add_argument("--path", default="/api/health")
    parser.add_argument("--steps", default="10,25,50,100")
    parser.add_argument("--duration", type=float, default=20)
    parser.add_argument("--pause", type=float, default=5, help="seconds between steps")
    parser.add_argument("--tokens-file", type=Path)
    parser.add_argument("--max-error-rate", type=float, default=0.05)
    parser.add_argument("--label", default="")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    base = args.base.rstrip("/")
    steps = [int(value) for value in args.steps.split(",") if value.strip()]
    label = args.label or (args.path.strip("/").replace("/", "_") or "root" if args.mode == "http" else "chat")
    args.out.mkdir(parents=True, exist_ok=True)
    summary_path = args.out / f"{args.mode}_{label}_summary.jsonl"
    rows_path = args.out / f"{args.mode}_{label}_requests.csv"

    connector = aiohttp.TCPConnector(limit=max(steps) + 10, ttl_dns_cache=300)
    timeout = aiohttp.ClientTimeout(total=300 if args.mode == "chat" else 30)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        conversations: List[str] = []
        tokens: List[str] = []
        if args.tokens_file:
            tokens = json.loads(args.tokens_file.read_text())
        if args.mode == "chat":
            if len(tokens) < max(steps):
                raise SystemExit("chat mode needs at least one test account per concurrent stream")
            conversations = await ensure_conversations(session, base, tokens[: max(steps)])

        for step in steps:
            if args.mode == "http":
                headers = {"Authorization": f"Bearer {tokens[0]}"} if tokens else None
                rows, elapsed = await http_step(session, base + args.path, step, args.duration, headers)
                summary = summarize(step, rows, elapsed)
            else:
                begin = time.perf_counter()
                rows = await asyncio.gather(*(
                    chat_stream(session, base, tokens[i], conversations[i], CHAT_QUESTIONS[i % len(CHAT_QUESTIONS)])
                    for i in range(step)
                ))
                elapsed = time.perf_counter() - begin
                firsts = [row["first_chunk"] for row in rows if row["ok"] and row["first_chunk"] is not None]
                summary = summarize(step, list(rows), elapsed, {
                    "first_chunk_p50": percentile(firsts, 0.50),
                    "first_chunk_p95": percentile(firsts, 0.95),
                    "rejected_429": sum(1 for row in rows if row["status"] == 429),
                })
            summary["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            write_rows(rows_path, list(rows), step)
            with summary_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(summary, ensure_ascii=False) + "\n")
            print(json.dumps(summary, ensure_ascii=False), flush=True)
            # 429s from the stream limiter are expected once the limit is reached; do not count them as failures.
            unexpected = summary["errors"] - summary.get("rejected_429", 0)
            if summary["requests"] and unexpected / summary["requests"] > args.max_error_rate:
                print(f"stopping: error rate above {args.max_error_rate:.0%} at concurrency {step}", flush=True)
                return 1
            await asyncio.sleep(args.pause)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
