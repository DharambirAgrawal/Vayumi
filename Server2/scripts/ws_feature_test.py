"""End-to-end WebSocket feature test — simulates the frontend over text.

Connects to a running Server2 (`/ws/v1/session?token=dev`), sends a `hello` with
tts disabled (so responses are chat_only text), then runs a battery of turns that
exercise: plain chat, short-term memory (session history), long-term memory
(save/recall facts), native tool-calling (web_search), multi-agent delegation
(research sub-agent), task-status coordination, and multiple tasks in one turn.

Measures per-turn latency (time-to-first-token and time-to-final-answer) and
records every server event so we can see how the orchestration behaves.

Run the server first, then:  venv/bin/python scripts/ws_feature_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field

import websockets

URL = "ws://127.0.0.1:8080/ws/v1/session?token=dev"


@dataclass
class TurnResult:
    label: str
    sent: str
    answer: str = ""
    ttft_s: float | None = None   # time to first caption/chat token
    total_s: float | None = None  # time to final chat_message
    events: list[tuple[str, str]] = field(default_factory=list)  # (kind, summary)
    notifications: list[str] = field(default_factory=list)
    timed_out: bool = False


async def _recv_json(ws, timeout: float):
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    if isinstance(raw, bytes):
        return {"type": "_binary", "bytes": len(raw)}
    return json.loads(raw)


async def run_turn(
    ws,
    label: str,
    text: str,
    *,
    turn_timeout: float = 150.0,
    drain_after: float = 0.0,
) -> TurnResult:
    res = TurnResult(label=label, sent=text)
    t0 = time.monotonic()
    await ws.send(json.dumps({"type": "chat", "payload": {"text": text}}))

    final_text = ""
    deadline = t0 + turn_timeout
    got_final = False
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            msg = await _recv_json(ws, timeout=remaining)
        except asyncio.TimeoutError:
            res.timed_out = True
            break
        mtype = msg.get("type")
        payload = msg.get("payload", {})
        if mtype == "caption":
            if res.ttft_s is None:
                res.ttft_s = time.monotonic() - t0
        elif mtype == "event":
            res.events.append((payload.get("kind", "?"), payload.get("summary", "")))
        elif mtype == "notification":
            res.notifications.append(payload.get("text", ""))
        elif mtype == "chat_message":
            if res.ttft_s is None:
                res.ttft_s = time.monotonic() - t0
            final_text = payload.get("text", "")
            if payload.get("final", True):
                got_final = True
                break
        elif mtype == "error":
            final_text = f"[ERROR] {payload.get('message')}"
            got_final = True
            break
    res.total_s = time.monotonic() - t0
    res.answer = final_text
    if got_final and drain_after > 0:
        # Listen longer for background task events / proactive notifications.
        end = time.monotonic() + drain_after
        while time.monotonic() < end:
            try:
                msg = await _recv_json(ws, timeout=end - time.monotonic())
            except asyncio.TimeoutError:
                break
            payload = msg.get("payload", {})
            if msg.get("type") == "event":
                res.events.append((payload.get("kind", "?"), payload.get("summary", "")))
            elif msg.get("type") == "notification":
                res.notifications.append(payload.get("text", ""))
    return res


def _fmt(res: TurnResult) -> str:
    ttft = f"{res.ttft_s:.1f}s" if res.ttft_s is not None else "—"
    total = f"{res.total_s:.1f}s" if res.total_s is not None else "—"
    lines = [
        f"\n## {res.label}",
        f"  -> sent:   {res.sent}",
        f"  <- answer: {res.answer.strip()[:400] or '(empty)'}",
        f"  latency:   first={ttft}  final={total}" + ("  [TIMEOUT]" if res.timed_out else ""),
    ]
    if res.events:
        ev = ", ".join(f"{k}({s[:40]})" if s else k for k, s in res.events)
        lines.append(f"  events:    {ev}")
    if res.notifications:
        lines.append(f"  notifs:    {' | '.join(n[:120] for n in res.notifications)}")
    return "\n".join(lines)


async def main() -> int:
    async with websockets.connect(URL, max_size=None, open_timeout=30) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "payload": {
                        "client": "web",
                        "capabilities": {"tts": False, "vad": False, "wake": False, "aec": False},
                    },
                }
            )
        )
        welcome = await _recv_json(ws, timeout=30)
        print(f"connected. welcome={json.dumps(welcome)[:200]}", flush=True)

        results: list[TurnResult] = []

        async def step(*args, **kwargs):
            r = await run_turn(ws, *args, **kwargs)
            print(_fmt(r), flush=True)
            results.append(r)
            # Let the session leave its post-turn busy window before the next turn
            # so each feature runs on the clean main path (not the queue path).
            await asyncio.sleep(5.0)
            return r

        # 1. Plain chat — no tools expected.
        await step("1. Greeting (no tools)", "Hey Vayumi, how are you today?")
        # 2. Short-term memory — set facts in session history.
        await step("2. Short-term set", "By the way, my name is Dharam and I live in Mumbai.")
        # 3. Short-term recall — from session history, no tool.
        await step("3. Short-term recall", "Quick - what's my name and which city do I live in?")
        # 4. Long-term memory save.
        await step("4. Long-term save", "Please remember that my favourite programming language is Python.")
        # 5. Tool calling — current data via web_search.
        await step("5. Tool: web_search price", "What's the current price of Bitcoin right now?")
        # 6. Another tool call — weather.
        await step("6. Tool: web_search weather", "And what's the weather in Tokyo at the moment?")
        # 7. Long-term recall — should pull the saved fact.
        await step("7. Long-term recall", "What did I say my favourite programming language was?")
        # 8. Multi-agent delegation — background research sub-agent.
        await step(
            "8. Multi-agent delegate",
            "Do an in-depth research comparing the latest NVIDIA and AMD AI chips and summarise the trade-offs.",
            turn_timeout=150,
            drain_after=45,
        )
        # 9. Task-status coordination — Main paraphrases the task board.
        await step("9. Task status", "What's the status of that research you're doing?")
        # 10. Multiple things in one turn — direct + delegate.
        await step(
            "10. Multiple tasks",
            "Tell me a short one-line joke, and also kick off deep research on the best electric cars of 2026.",
            turn_timeout=150,
            drain_after=30,
        )

        print("\n" + "=" * 72 + "\nLATENCY SUMMARY (seconds)\n" + "=" * 72, flush=True)
        print(f"{'turn':<34}{'first':>8}{'final':>8}{'events':>8}")
        for r in results:
            ttft = f"{r.ttft_s:.1f}" if r.ttft_s is not None else "-"
            total = f"{r.total_s:.1f}" if r.total_s is not None else "-"
            print(f"{r.label[:34]:<34}{ttft:>8}{total:>8}{len(r.events):>8}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
