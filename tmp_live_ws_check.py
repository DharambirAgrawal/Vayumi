import asyncio
import json
import time
import urllib.error
import urllib.request

import websockets

BASE = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws/vayumi"


def request(method: str, path: str, payload: dict | None = None, headers: dict | None = None):
    headers = headers or {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(BASE + path, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


async def main():
    email = f"wsfix_{int(time.time())}@example.com"
    password = "TestPass123!"

    status, body = request(
        "POST",
        "/api/auth/register",
        {"display_name": "WS Fix User", "email": email, "password": password},
    )
    print("register", status, body)

    status, body = request(
        "POST",
        "/api/auth/login",
        {"email": email, "password": password},
    )
    print("login", status, body)

    if status != 200:
        return

    token = json.loads(body)["token"]

    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({"type": "auth", "token": token}))
        msg = await ws.recv()
        print("ws_auth_reply", msg)


if __name__ == "__main__":
    asyncio.run(main())
