"""Quick probe of search freshness/reliability over a few current-data queries."""

from __future__ import annotations

import asyncio
import json
import time

import websockets

URL = "ws://127.0.0.1:8080/ws/v1/session?token=dev"
QUERIES = [
    "What's the current price of Bitcoin right now?",
    "What's happening with SpaceX stock currently?",
    "What's the latest news on NVIDIA this week?",
    "Who is the current CEO of OpenAI?",
]


async def main() -> None:
    async with websockets.connect(URL, max_size=None, open_timeout=30) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "payload": {"client": "web", "capabilities": {"tts": False}},
                }
            )
        )
        await ws.recv()  # welcome
        for q in QUERIES:
            t0 = time.monotonic()
            await ws.send(json.dumps({"type": "chat", "payload": {"text": q}}))
            answer = ""
            while time.monotonic() - t0 < 120:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=120))
                if msg.get("type") == "chat_message":
                    answer = msg["payload"]["text"]
                    if msg["payload"].get("final", True):
                        break
                elif msg.get("type") == "error":
                    answer = "[ERROR] " + msg["payload"].get("message", "")
                    break
            print(f"\nQ: {q}\nA: {answer.strip()}", flush=True)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
