"""Exercise original-byte HTTP uploads without a custom handler class."""
import http.client
import io
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from misc import web_upload


@pytest.mark.parametrize("media_type", ["message/rfc822", "application/octet-stream", "text/plain"])
@pytest.mark.parametrize("name", ["sample-1.eml", "sample-2.eml", "sample-3.eml"])
def test_real_tracked_email_upload_preserves_bytes_for_browser_media_types(media_type, name):
    content = (Path(__file__).resolve().parents[1] / "emails" / name).read_bytes()
    body = (b'--real-boundary\r\nContent-Disposition: form-data; name="file"; filename="'
            + name.encode() + b'"\r\nContent-Type: ' + media_type.encode()
            + b'\r\n\r\n' + content + b'\r\n--real-boundary--\r\n')
    assert web_upload.parse_upload('multipart/form-data; boundary="real-boundary"', body) == {
        "filename": name, "content": content,
    }


def _form(content=b"Fictional message\r\n", filename="fictional.eml"):
    return (b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="'
            + filename.encode() + b'"\r\nContent-Type: application/octet-stream\r\n\r\n'
            + content + b'\r\n--boundary--\r\n')


def test_quoted_multipart_boundary_preserves_original_bytes():
    content = b'From: fictional@example.test\r\n\r\nOriginal \xff\r\n--not-the-boundary\r\n'
    assert web_upload.parse_upload('multipart/form-data; boundary="boundary"', _form(content)) == {
        "filename":"fictional.eml", "content":content,
    }


@pytest.mark.parametrize("content_type, body", [
    (None, b"bad"), ("text/plain", b"bad"), ("multipart/form-data", b"bad"),
    ("multipart/form-data; boundary=boundary", _form()[:-16]),
    ("multipart/form-data; boundary=boundary", _form(b"")),
    ("multipart/form-data; boundary=boundary", _form(filename="file.pdf")),
], ids=["missing-type", "wrong-type", "missing-boundary", "truncated", "empty", "wrong-file-type"])
def test_invalid_http_uploads_are_rejected(content_type, body):
    with pytest.raises(ValueError):
        web_upload.parse_upload(content_type, body)


def test_oversize_http_upload_is_rejected():
    with pytest.raises(ValueError, match="size limit"):
        web_upload.parse_upload("multipart/form-data; boundary=boundary",
                                _form(b"x" * (web_upload.MAX_UPLOAD_BYTES + 1)))


@pytest.mark.parametrize("length", ["invalid", "-1", str(web_upload.MAX_REQUEST_BYTES + 1)])
def test_invalid_length_is_rejected_without_reading_or_completing(length):
    handler = SimpleNamespace(command="POST", headers={"Content-Length":length},
                              rfile=Mock(), send_error=Mock())
    web_upload._result.update(upload=None, done=False)
    web_upload._handle(handler)
    handler.rfile.read.assert_not_called()
    handler.send_error.assert_called_once()
    assert not web_upload._result["done"]


def test_incomplete_request_is_rejected_without_completing():
    handler = SimpleNamespace(command="POST", headers={"Content-Length":"100"},
                              rfile=io.BytesIO(b"short"), send_error=Mock())
    web_upload._result.update(upload=None, done=False)
    web_upload._handle(handler)
    handler.send_error.assert_called_once()
    assert not web_upload._result["done"]


def test_real_http_server_recovers_from_bad_request_then_preserves_email_bytes(monkeypatch):
    ready = threading.Event()
    servers = []
    original = web_upload.http.server.HTTPServer

    def make_server(address, handler):
        server = original(address, handler)
        servers.append(server)
        ready.set()
        return server

    monkeypatch.setattr(web_upload, "BIND_HOST", "127.0.0.1")
    monkeypatch.setattr(web_upload, "PORT", 0)
    monkeypatch.setattr(web_upload.http.server, "HTTPServer", make_server)
    results = []
    worker = threading.Thread(target=lambda: results.append(web_upload.start_and_wait_for_upload()),
                              daemon=True)
    worker.start()
    assert ready.wait(5)
    connection = http.client.HTTPConnection("127.0.0.1", servers[0].server_port, timeout=5)
    connection.request("GET", "/")
    response = connection.getresponse()
    assert response.status == 200
    assert b"Upload a file" in response.read()
    connection.request("POST", "/", body=b"bad", headers={"Content-Type":"text/plain"})
    response = connection.getresponse()
    assert response.status == 400
    response.read()
    content = b"Content-Type: text/html\r\n\r\n<p>Fictional email</p>\r\n"
    connection.request("POST", "/", body=_form(content),
                       headers={"Content-Type":'multipart/form-data; boundary="boundary"'})
    response = connection.getresponse()
    assert response.status == 200
    response.read()
    connection.close()
    worker.join(5)
    assert not worker.is_alive()
    assert results == [{"filename":"fictional.eml", "content":content}]
    assert servers[0].socket.fileno() == -1
