#!/usr/bin/env python3
"""Quick WebSocket smoke test for tool + chat flow (dev token)."""
from __future__ import annotations

import asyncio
import json
import sys
import uuid

import websockets

URL = "ws://127.0.0.1:8080/ws/v1/session?token=dev"
CHAT = (
    "what is going on with nvidia stock and general internet news right now"
)
TIMEOUT_S = 120


async def main() -> int:
    events: list[dict] = []
    chat_message: dict | None = None
    errors: list[str] = []

    async with websockets.connect(URL, open_timeout=10) as ws:
        hello = {
            "type": "hello",
            "payload": {
                "client": "web",
                "capabilities": {"aec": True, "vad": False, "wake": False, "tts": False},
                "session_id": f"smoke-{uuid.uuid4()}",
            },
        }
        await ws.send(json.dumps(hello))

        chat = {"type": "chat", "payload": {"text": CHAT}}
        await ws.send(json.dumps(chat))

        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT_S)
                msg = json.loads(raw)
                kind = msg.get("type")
                if kind == "event":
                    events.append(msg["payload"])
                elif kind == "chat_message":
                    chat_message = msg["payload"]
                    if msg["payload"].get("final"):
                        break
                elif kind == "error":
                    errors.append(str(msg.get("payload")))
                    break
        except TimeoutError:
            errors.append("timed out waiting for final chat_message")

    print("=== tool events ===")
    for ev in events:
        if ev.get("kind") in ("tool_started", "tool_done"):
            print(f"  {ev.get('kind')}: {ev.get('summary')}")

    ok = True
    summaries = " ".join(e.get("summary", "") for e in events)
    if "web_search" not in summaries:
        print("FAIL: expected web_search in tool events")
        ok = False
    if "tool_search" in summaries and "web_search" not in summaries:
        print("FAIL: only tool_search ran (no real web fetch)")
        ok = False

    print("\n=== chat_message (first 500 chars) ===")
    if chat_message:
        text = chat_message.get("text", "")
        print(text[:500])
        if "[TOOL_RESULT" in text:
            print("FAIL: TOOL_RESULT leaked into chat_message")
            ok = False
        if "Found " in text and "tool(s) for" in text:
            print("FAIL: tool_search metadata leaked into chat_message")
            ok = False
        if len(text.strip()) < 40:
            print("FAIL: chat_message too short")
            ok = False
    else:
        print("(none)")
        ok = False

    if errors:
        print("\n=== errors ===")
        for err in errors:
            print(f"  {err}")
        ok = False

    print("\n=== result ===")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
