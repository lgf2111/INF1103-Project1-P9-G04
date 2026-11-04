import threading
from http.server import ThreadingHTTPServer

import pytest

from gui.auth_api import AuthApiClient, AuthApiError
from gui.mock_auth_api import (
    DEMO_EMAIL,
    DEMO_PASSWORD,
    DEMO_USER,
    MockAuthHandler,
)


@pytest.fixture
def mock_api_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockAuthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_demo_login_returns_static_user_and_session(mock_api_server):
    client = AuthApiClient(mock_api_server)

    assert client.sign_in(DEMO_EMAIL, DEMO_PASSWORD) == DEMO_USER
    assert client.current_user() == DEMO_USER

    client.sign_out()
    with pytest.raises(AuthApiError) as raised:
        client.current_user()
    assert raised.value.status == 401


def test_login_rejects_non_demo_credentials(mock_api_server):
    client = AuthApiClient(mock_api_server)

    with pytest.raises(AuthApiError) as raised:
        client.sign_in(DEMO_EMAIL, "wrong-password")

    assert raised.value.code == "INVALID_CREDENTIALS"
    assert raised.value.status == 401


def test_registration_and_password_reset_are_static(mock_api_server):
    client = AuthApiClient(mock_api_server)

    assert client.create_account("new@example.com", "long-enough-password") == {
        "verificationRequired": True,
        "user": None,
    }
    with pytest.raises(AuthApiError) as raised:
        client.create_account("new@example.com", "too-short")
    assert raised.value.field_errors == {
        "password": "Use at least 12 characters."
    }

    client.request_password_reset("person@example.com")
    client.reset_password("demo-token", "long-enough-password")
