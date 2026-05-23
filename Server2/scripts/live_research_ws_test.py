#!/usr/bin/env python3
"""
Live WebSocket test — research delegate + task_step feedback + final chat.
Requires server: uvicorn server.app:app --port 8080

Run: python scripts/live_research_ws_test.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid

import websockets

URL = "ws://127.0.0.1:8080/ws/v1/session?token=dev"

SCENARIOS = [
    {
        "name": "quick web (main)",
        "chat": "what is going on with nvidia stock right now",
        "expect_tools": ("web_search",),
        "expect_task": False,
        "timeout": 90,
    },
    {
        "name": "deep research (sub-agent)",
        "chat": (
            "Do deep research on NVIDIA stock and AI chip news — "
            "read full articles and summarize with sources"
        ),
        "expect_tools": ("deep_search", "research"),
        "expect_task": True,
        "timeout": 180,
    },
]


async def run_scenario(spec: dict) -> bool:
    print("\n" + "=" * 72)
    print(f"SCENARIO: {spec['name']}")
    print("=" * 72)
    print(f"user: {spec['chat'][:100]}…")

    events: list[dict] = []
    chat_final: dict | None = None
    t_start = time.perf_counter()

    async with websockets.connect(URL, open_timeout=10) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "payload": {
                        "client": "web",
                        "capabilities": {"aec": False, "vad": False, "tts": False},
                        "session_id": f"live-{uuid.uuid4()}",
                    },
                }
            )
        )

        await ws.send(json.dumps({"type": "chat", "payload": {"text": spec["chat"]}}))

        deadline = t_start + spec["timeout"]
        while time.perf_counter() < deadline:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 30))
            except TimeoutError:
                continue
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "event":
                payload = msg["payload"]
                events.append(payload)
                elapsed = time.perf_counter() - t_start
                print(
                    f"  [{elapsed:5.1f}s] event {payload.get('kind')}: "
                    f"{payload.get('summary', '')[:100]}"
                )
            elif kind == "caption":
                pass
            elif kind == "chat_message" and msg["payload"].get("final"):
                chat_final = msg["payload"]
                break
            elif kind == "error":
                print(f"  ERROR: {msg.get('payload')}")
                return False

    elapsed = time.perf_counter() - t_start
    print(f"\n--- finished in {elapsed:.1f}s ---")

    tool_kinds = [e.get("kind") for e in events]
    has_task = any(k in ("task_step", "task_done", "task_error") for k in tool_kinds)
    has_tool = any(k in ("tool_started", "tool_done") for k in tool_kinds)

    print(f"events: {len(events)} — kinds: {', '.join(tool_kinds) or 'none'}")
    if chat_final:
        text = chat_final.get("text", "")
        print(f"\nassistant ({len(text)} chars):\n{_preview(text, 1200)}")
    else:
        print("no final chat_message")

    ok = chat_final is not None and len(chat_final.get("text", "").strip()) > 20
    if spec["expect_task"]:
        ok = ok and has_task
        if not has_task:
            print("FAIL: expected task_step/task_done events (activity feed)")
    if spec.get("expect_tools"):
        summaries = " ".join(e.get("summary", "") for e in events).lower()
        for needle in spec["expect_tools"]:
            if needle == "research":
                if not has_task:
                    print(f"WARN: expected research background (task events)")
            elif needle not in summaries and needle != "deep_search":
                pass
        if "deep_search" in spec["expect_tools"] and not has_task and not has_tool:
            print("WARN: no deep_search/tool activity visible in events")

    return ok


def _preview(text: str, limit: int = 900) -> str:
    t = text.strip()
    return t if len(t) <= limit else t[:limit] + "\n…"


async def main() -> int:
    print("Live WebSocket research test")
    print("Ensure server is running on :8080 with latest code + TAVILY_API_KEY")
    code = 0
    for spec in SCENARIOS:
        try:
            if not await run_scenario(spec):
                code = 1
        except Exception as exc:
            print(f"SCENARIO FAILED: {exc}")
            code = 1
    print("\n" + "=" * 72)
    print("DONE" if code == 0 else "SOME SCENARIOS FAILED")
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
