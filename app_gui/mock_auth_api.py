"""Development-only static API for exercising the desktop authentication UI."""

from __future__ import annotations

import argparse
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

DEMO_EMAIL = "demo@phishreport.test"
DEMO_PASSWORD = "phishreport-demo"
DEMO_SESSION = "phishreport-demo-session"
DEMO_USER = {
    "id": "demo-user-001",
    "email": DEMO_EMAIL,
    "name": "Demo Analyst",
}
MAX_REQUEST_SIZE = 16_384


class MockAuthHandler(BaseHTTPRequestHandler):
    """Return fixed demo responses for the GUI's authentication endpoints."""

    server_version = "PhishReportMockAuth/1.0"
    sys_version = ""

    def do_GET(self) -> None:
        if urlsplit(self.path).path != "/api/auth/me":
            self._send_error(404, "NOT_FOUND", "Endpoint not found.")
            return
        if self.headers.get("Cookie") != f"session={DEMO_SESSION}":
            self._send_error(401, "UNAUTHENTICATED", "Sign in required.")
            return
        self._send_json(200, {"user": dict(DEMO_USER)})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/auth/logout":
            self.send_response(204)
            self.send_header(
                "Set-Cookie",
                "session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0",
            )
            self.end_headers()
            return
        if path not in {
            "/api/auth/login",
            "/api/auth/register",
            "/api/auth/password/reset-request",
            "/api/auth/password/reset",
        }:
            self._send_error(404, "NOT_FOUND", "Endpoint not found.")
            return
        try:
            body = self._read_json()
        except ValueError:
            self._send_error(400, "INVALID_REQUEST", "Request body must be a JSON object.")
            return

        if path == "/api/auth/login":
            self._login(body)
        elif path == "/api/auth/register":
            self._register(body)
        elif path == "/api/auth/password/reset-request":
            self._reset_request(body)
        else:
            self._reset_password(body)

    def _login(self, body: dict[str, Any]) -> None:
        email = body.get("email")
        password = body.get("password")
        if (
            email != DEMO_EMAIL
            or not isinstance(password, str)
            or not hmac.compare_digest(password, DEMO_PASSWORD)
        ):
            self._send_error(
                401, "INVALID_CREDENTIALS", "Email or password is incorrect."
            )
            return
        self._send_json(
            200,
            {"user": dict(DEMO_USER)},
            set_cookie=(
                f"session={DEMO_SESSION}; HttpOnly; SameSite=Lax; Path=/"
            ),
        )

    def _register(self, body: dict[str, Any]) -> None:
        password = body.get("password")
        if not isinstance(body.get("email"), str) or not isinstance(password, str):
            self._send_error(400, "INVALID_REQUEST", "Email and password are required.")
            return
        if len(password) < 12:
            self._send_error(
                400,
                "INVALID_PASSWORD",
                "Password must be at least 12 characters.",
                {"password": "Use at least 12 characters."},
            )
            return
        self._send_json(201, {"verificationRequired": True})

    def _reset_request(self, body: dict[str, Any]) -> None:
        if not isinstance(body.get("email"), str):
            self._send_error(400, "INVALID_REQUEST", "Email is required.")
            return
        self._send_json(
            202,
            {"message": "If an account matches, reset instructions will be sent."},
        )

    def _reset_password(self, body: dict[str, Any]) -> None:
        token = body.get("token")
        password = body.get("password")
        if not isinstance(token, str) or not token or not isinstance(password, str):
            self._send_error(
                400, "INVALID_REQUEST", "A reset token and new password are required."
            )
            return
        if len(password) < 12:
            self._send_error(
                400,
                "INVALID_PASSWORD",
                "Password must be at least 12 characters.",
                {"password": "Use at least 12 characters."},
            )
            return
        self._send_json(200, {"message": "Password reset simulated."})

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid content length.") from None
        if length < 1 or length > MAX_REQUEST_SIZE:
            raise ValueError("Request body size is invalid.")
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Request body is not valid JSON.") from None
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return payload

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        set_cookie: str | None = None,
    ) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error(
        self,
        status: int,
        code: str,
        message: str,
        field_errors: dict[str, str] | None = None,
    ) -> None:
        error: dict[str, Any] = {"code": code, "message": message}
        if field_errors:
            error["fieldErrors"] = field_errors
        self._send_json(status, {"error": error})


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the development-only static desktop auth API."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), MockAuthHandler)
    print(f"Mock auth API listening at http://{args.host}:{args.port}")
    print(f"Demo login: {DEMO_EMAIL} / {DEMO_PASSWORD}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping mock auth API.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
