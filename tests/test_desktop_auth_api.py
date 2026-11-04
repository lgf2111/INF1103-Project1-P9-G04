import http.server
import json
import threading

import pytest

from gui.auth_api import AuthApiClient, AuthApiError


class AuthHandler(http.server.BaseHTTPRequestHandler):
    calls = []

    def do_GET(self):
        type(self).calls.append((self.command, self.path, self.headers.get("Cookie")))
        if self.path == "/api/auth/me":
            if self.headers.get("Cookie") != "session=test-session":
                self.send_json(
                    401,
                    {"error": {"code": "UNAUTHENTICATED", "message": "Sign in required."}},
                )
                return
            self.send_json(
                200, {"user": {"id": "user-1", "email": "person@example.com"}}
            )
            return
        self.send_json(404, {"error": {"message": "Not found."}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).calls.append((self.command, self.path, body))
        if self.path == "/api/auth/login":
            if body.get("password") != "valid-password":
                self.send_json(
                    401,
                    {
                        "error": {
                            "code": "INVALID_CREDENTIALS",
                            "message": "Email or password is incorrect.",
                            "fieldErrors": {"email": "Check your email."},
                        }
                    },
                )
                return
            self.send_json(
                200,
                {"user": {"id": "user-1", "email": body["email"], "name": "Pat"}},
                cookie=True,
            )
            return
        if self.path == "/api/auth/logout":
            self.send_response(204)
            self.end_headers()
            return
        if self.path == "/api/auth/password/reset-request":
            self.send_json(202, {"message": "If an account matches, instructions will be sent."})
            return
        if self.path == "/api/auth/password/reset":
            self.send_json(200, {"message": "Password updated."})
            return
        if self.path == "/api/auth/register":
            self.send_json(201, {"verificationRequired": True})
            return
        self.send_json(404, {"error": {"message": "Not found."}})

    def send_json(self, status, payload, cookie=False):
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        if cookie:
            self.send_header(
                "Set-Cookie", "session=test-session; HttpOnly; SameSite=Lax; Path=/"
            )
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format, *_args):
        return


@pytest.fixture
def api_server():
    AuthHandler.calls = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), AuthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_login_keeps_cookie_in_memory_for_current_user_and_logout(api_server):
    client = AuthApiClient(api_server)

    assert client.sign_in("person@example.com", "valid-password") == {
        "id": "user-1",
        "email": "person@example.com",
        "name": "Pat",
    }
    assert client.current_user() == {
        "id": "user-1",
        "email": "person@example.com",
    }
    client.sign_out()

    assert AuthHandler.calls[1][2] == "session=test-session"
    assert len(client._cookie_jar) == 0


def test_api_error_exposes_message_and_field_errors(api_server):
    client = AuthApiClient(api_server)

    with pytest.raises(AuthApiError) as raised:
        client.sign_in("person@example.com", "wrong-password")

    assert raised.value.status == 401
    assert raised.value.code == "INVALID_CREDENTIALS"
    assert raised.value.field_errors == {"email": "Check your email."}
    assert str(raised.value) == "Email or password is incorrect."


def test_registration_can_require_email_verification(api_server):
    assert AuthApiClient(api_server).create_account(
        "person@example.com", "long-enough-password"
    ) == {"verificationRequired": True, "user": None}


def test_password_reset_requests_use_expected_payloads(api_server):
    client = AuthApiClient(api_server)
    client.request_password_reset("person@example.com")
    client.reset_password("one-time-token", "long-enough-password")

    assert AuthHandler.calls[-2:] == [
        (
            "POST",
            "/api/auth/password/reset-request",
            {"email": "person@example.com"},
        ),
        (
            "POST",
            "/api/auth/password/reset",
            {"token": "one-time-token", "password": "long-enough-password"},
        ),
    ]


def test_invalid_success_response_is_rejected(api_server):
    class InvalidHandler(AuthHandler):
        def do_POST(self):
            self.send_json(200, {"user": {"email": "person@example.com"}})

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), InvalidHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(AuthApiError, match="unexpected response"):
            AuthApiClient(f"http://127.0.0.1:{server.server_port}").sign_in(
                "person@example.com", "valid-password"
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
