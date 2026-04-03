import json
import time
from fastapi.testclient import TestClient

from server.main import app


def print_result(name: str, ok: bool, details: str = ""):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name} {details}")


def main():
    email = f"copilot_api_test_{int(time.time())}@example.com"
    password = "TestPass123!"

    with TestClient(app) as client:
        # Enumerate mounted HTTP endpoints from OpenAPI
        openapi = client.get("/openapi.json")
        print_result("GET /openapi.json", openapi.status_code == 200, f"status={openapi.status_code}")
        paths = sorted(openapi.json().get("paths", {}).keys()) if openapi.status_code == 200 else []
        print("OpenAPI paths:", paths)

        # Static root route
        root = client.get("/")
        print_result("GET /", root.status_code == 200, f"status={root.status_code}")

        # Register
        register_payload = {
            "display_name": "Copilot API Test",
            "email": email,
            "password": password,
            "profile": {"occupation": "tester"},
        }
        reg = client.post("/api/auth/register", json=register_payload)
        print_result("POST /api/auth/register", reg.status_code == 200, f"status={reg.status_code} body={reg.text}")

        # Duplicate register should fail
        reg_dup = client.post("/api/auth/register", json=register_payload)
        print_result("POST /api/auth/register duplicate", reg_dup.status_code == 400, f"status={reg_dup.status_code}")

        # Login
        login = client.post("/api/auth/login", json={"email": email, "password": password})
        print_result("POST /api/auth/login", login.status_code == 200, f"status={login.status_code}")
        token = login.json().get("token") if login.status_code == 200 else None

        # Wrong password should fail
        login_bad = client.post("/api/auth/login", json={"email": email, "password": "WrongPass"})
        print_result("POST /api/auth/login wrong password", login_bad.status_code == 401, f"status={login_bad.status_code}")

        # /me without auth
        me_no_auth = client.get("/api/users/me")
        print_result("GET /api/users/me (no token)", me_no_auth.status_code == 401, f"status={me_no_auth.status_code}")

        # /me with auth
        if token:
            me_auth = client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
            ok = me_auth.status_code == 200 and me_auth.json().get("email") == email
            print_result("GET /api/users/me (valid token)", ok, f"status={me_auth.status_code}")
        else:
            print_result("GET /api/users/me (valid token)", False, "no token from login")

        # WebSocket: reject if first message is not auth
        ws_invalid_ok = False
        try:
            with client.websocket_connect("/ws/vayumi") as ws:
                ws.send_json({"type": "text_input", "text": "hello"})
                msg = ws.receive_json()
                ws_invalid_ok = msg.get("type") == "auth_error"
        except Exception:
            ws_invalid_ok = True
        print_result("WS /ws/vayumi invalid first frame", ws_invalid_ok)

        # WebSocket: auth handshake
        ws_auth_ok = False
        ws_auth_details = ""
        if token:
            try:
                with client.websocket_connect("/ws/vayumi") as ws:
                    ws.send_json({"type": "auth", "token": token})
                    msg = ws.receive_json()
                    ws_auth_ok = msg.get("type") == "auth_ok" and msg.get("user_id") is not None
                    ws_auth_details = json.dumps(msg)
            except Exception as exc:
                ws_auth_ok = False
                ws_auth_details = repr(exc)
        print_result("WS /ws/vayumi auth handshake", ws_auth_ok, ws_auth_details)


if __name__ == "__main__":
    main()
