"""HTTP client for the desktop GUI's authentication API."""

from __future__ import annotations

import http.cookiejar
import json
import os
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


class AuthApiError(Exception):
    """A user-safe authentication API error."""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        code: str | None = None,
        field_errors: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.field_errors = field_errors or {}


class AuthApiClient:
    """Send authentication requests and keep the session cookie in memory."""

    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = (base_url or os.environ.get(
            "PHISHREPORT_API_URL", "http://127.0.0.1:8000"
        )).rstrip("/")
        self.timeout = timeout
        self._cookie_jar = http.cookiejar.CookieJar()
        self._opener = build_opener(HTTPCookieProcessor(self._cookie_jar))
        self._request_lock = threading.RLock()

    def sign_in(self, email: str, password: str) -> dict[str, str]:
        result = self._request(
            "POST", "/api/auth/login", {"email": email, "password": password}
        )
        return self._user_result(result)

    def create_account(self, email: str, password: str) -> dict[str, Any]:
        result = self._request(
            "POST", "/api/auth/register", {"email": email, "password": password}
        )
        if not isinstance(result, dict) or not isinstance(
            result.get("verificationRequired"), bool
        ):
            raise AuthApiError("The authentication service returned an unexpected response.")

        user = result.get("user")
        if user is not None and not self._valid_user(user):
            raise AuthApiError("The authentication service returned an unexpected response.")
        if not result["verificationRequired"] and user is None:
            raise AuthApiError("The authentication service returned an unexpected response.")

        return {"verificationRequired": result["verificationRequired"], "user": user}

    def request_password_reset(self, email: str) -> None:
        self._request("POST", "/api/auth/password/reset-request", {"email": email})

    def reset_password(self, token: str, password: str) -> None:
        self._request(
            "POST", "/api/auth/password/reset", {"token": token, "password": password}
        )

    def current_user(self) -> dict[str, str]:
        return self._user_result(self._request("GET", "/api/auth/me"))

    def sign_out(self) -> None:
        with self._request_lock:
            self._request("POST", "/api/auth/logout")
            self._cookie_jar.clear()

    def _request(
        self, method: str, path: str, body: dict[str, str] | None = None
    ) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=data, headers=headers, method=method)

        with self._request_lock:
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    if response.status == 204:
                        return None
                    return self._decode_json(response.read(), response.status)
            except HTTPError as error:
                payload = self._read_error_body(error)
                raise self._api_error(payload, error.code) from None
            except (URLError, TimeoutError, OSError):
                raise AuthApiError(
                    "Could not reach the authentication service. "
                    "Check the API address and try again."
                ) from None

    @staticmethod
    def _decode_json(payload: bytes, status: int) -> Any:
        try:
            return json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AuthApiError(
                "The authentication service returned an unexpected response.", status
            ) from None

    @classmethod
    def _read_error_body(cls, error: HTTPError) -> Any:
        try:
            return cls._decode_json(error.read(), error.code)
        except AuthApiError:
            return None

    @staticmethod
    def _api_error(payload: Any, status: int) -> AuthApiError:
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            return AuthApiError("That request could not be completed. Please try again.", status)

        message = error.get("message")
        code = error.get("code")
        raw_fields = error.get("fieldErrors")
        field_errors = (
            {key: value for key, value in raw_fields.items() if isinstance(value, str)}
            if isinstance(raw_fields, dict)
            else {}
        )
        return AuthApiError(
            message if isinstance(message, str) else "That request could not be completed.",
            status,
            code if isinstance(code, str) else None,
            field_errors,
        )

    @staticmethod
    def _valid_user(user: Any) -> bool:
        return (
            isinstance(user, dict)
            and isinstance(user.get("id"), str)
            and isinstance(user.get("email"), str)
        )

    @classmethod
    def _user_result(cls, result: Any) -> dict[str, str]:
        user = result.get("user") if isinstance(result, dict) else None
        if not cls._valid_user(user):
            raise AuthApiError("The authentication service returned an unexpected response.")
        clean_user = {"id": user["id"], "email": user["email"]}
        if isinstance(user.get("name"), str):
            clean_user["name"] = user["name"]
        return clean_user
