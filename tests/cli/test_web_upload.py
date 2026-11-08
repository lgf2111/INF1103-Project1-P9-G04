"""Browser-based .eml upload."""

import http.client
import io
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from phishreport.cli import web_upload
from phishreport.io import IOManager
from phishreport.io.terminal import ConsoleTerminal

REAL_EMAILS = Path(__file__).resolve().parents[1] / "fixtures"
io_manager = IOManager(ConsoleTerminal())


# ============================================================================
# Web Upload
# ============================================================================
@pytest.mark.parametrize(
    "media_type, name",
    [
        ("message/rfc822", "sample-1.eml"),
        ("application/octet-stream", "sample-2.eml"),
        ("text/plain", "sample-3.eml"),
    ],
)
def test_web_upload_real_tracked_email_upload_preserves_bytes_for_browser_media_types(
    media_type, name
):
    content = (Path(__file__).resolve().parents[2] / "tests" / "fixtures" / name).read_bytes()
    body = (
        b'--real-boundary\r\nContent-Disposition: form-data; name="file"; filename="'
        + name.encode()
        + b'"\r\nContent-Type: '
        + media_type.encode()
        + b"\r\n\r\n"
        + content
        + b"\r\n--real-boundary--\r\n"
    )
    assert web_upload.UploadParser().parse(
        'multipart/form-data; boundary="real-boundary"', body
    ) == {
        "filename": name,
        "content": content,
    }


def web_upload_form(content=b"Fictional message\r\n", filename="fictional.eml"):
    return (
        b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="'
        + filename.encode()
        + b'"\r\nContent-Type: application/octet-stream\r\n\r\n'
        + content
        + b"\r\n--boundary--\r\n"
    )


def test_web_upload_quoted_multipart_boundary_preserves_original_bytes():
    content = b"From: fictional@example.test\r\n\r\nOriginal \xff\r\n--not-the-boundary\r\n"
    assert web_upload.UploadParser().parse(
        'multipart/form-data; boundary="boundary"', web_upload_form(content)
    ) == {
        "filename": "fictional.eml",
        "content": content,
    }


@pytest.mark.parametrize(
    "content_type, body",
    [
        (None, b"bad"),
        ("text/plain", b"bad"),
        ("multipart/form-data", b"bad"),
        ("multipart/form-data; boundary=boundary", web_upload_form()[:-16]),
        ("multipart/form-data; boundary=boundary", web_upload_form(b"")),
        ("multipart/form-data; boundary=boundary", web_upload_form(filename="file.pdf")),
    ],
    ids=["missing-type", "wrong-type", "missing-boundary", "truncated", "empty", "wrong-file-type"],
)
def test_web_upload_invalid_http_uploads_are_rejected(content_type, body):
    with pytest.raises(ValueError):
        web_upload.UploadParser().parse(content_type, body)


def test_web_upload_oversize_http_upload_is_rejected():
    with pytest.raises(ValueError, match="size limit"):
        web_upload.UploadParser().parse(
            "multipart/form-data; boundary=boundary",
            web_upload_form(b"x" * (web_upload.MAX_UPLOAD_BYTES + 1)),
        )


@pytest.mark.parametrize("length", ["invalid", "-1", str(web_upload.MAX_REQUEST_BYTES + 1)])
def test_web_upload_invalid_length_is_rejected_without_reading_or_completing(length):
    handler = web_upload_request_handler(b"")
    handler.headers["Content-Length"] = length
    handler.rfile = Mock()
    handler.do_POST()
    handler.rfile.read.assert_not_called()
    handler.send_error.assert_called_once()
    handler.server.accept_upload.assert_not_called()


def test_web_upload_incomplete_request_is_rejected_without_completing():
    handler = web_upload_request_handler(b"short")
    handler.headers["Content-Length"] = "100"
    handler.do_POST()
    handler.send_error.assert_called_once()
    handler.server.accept_upload.assert_not_called()


def test_web_upload_real_http_server_recovers_from_bad_request_then_preserves_email_bytes(
    monkeypatch,
):
    ready = threading.Event()
    servers = []
    original = web_upload._UploadServer

    def make_server(address, parser):
        server = original(address, parser)
        servers.append(server)
        ready.set()
        return server

    service = web_upload.BrowserUploadService(host="127.0.0.1", port=0, server_factory=make_server)
    results = []
    worker = threading.Thread(target=lambda: results.append(service.receive_upload()), daemon=True)
    worker.start()
    assert ready.wait(5)
    connection = http.client.HTTPConnection("127.0.0.1", servers[0].server_port, timeout=5)
    connection.request("GET", "/")
    response = connection.getresponse()
    assert response.status == 200
    assert b"Upload an email" in response.read()
    connection.request("POST", "/", body=b"bad", headers={"Content-Type": "text/plain"})
    response = connection.getresponse()
    assert response.status == 400
    response.read()
    content = b"Content-Type: text/html\r\n\r\n<p>Fictional email</p>\r\n"
    connection.request(
        "POST",
        "/",
        body=web_upload_form(content),
        headers={"Content-Type": 'multipart/form-data; boundary="boundary"'},
    )
    response = connection.getresponse()
    assert response.status == 200
    response.read()
    connection.close()
    worker.join(5)
    assert not worker.is_alive()
    assert results == [{"filename": "fictional.eml", "content": content}]
    assert servers[0].socket.fileno() == -1


def test_web_upload_overlapping_sessions_return_their_own_files(monkeypatch):
    def new_service():
        return web_upload.BrowserUploadService(host="127.0.0.1", port=0)

    original_handle_request = web_upload.http.server.HTTPServer.handle_request
    first_server = None
    second_upload = None
    first_content = b"First email\r\n"
    second_content = b"Second email\r\n"
    submitted = set()

    def serve_request(server, method, body=None):
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        try:
            connection.request(
                method,
                "/",
                body=body,
                headers={"Content-Type": "multipart/form-data; boundary=boundary"},
            )
            original_handle_request(server)
            response = connection.getresponse()
            assert response.status == 200
            response.read()
        finally:
            connection.close()

    def handle_request(server):
        nonlocal first_server, second_upload
        if first_server is None:
            first_server = server
            # Finish the second session while the first is still serving its page.
            second_upload = new_service().receive_upload()
            serve_request(server, "GET")
            return

        assert server not in submitted, "Session did not finish after a valid upload"
        submitted.add(server)
        if server is first_server:
            serve_request(server, "POST", web_upload_form(first_content, "first.eml"))
        else:
            serve_request(server, "POST", web_upload_form(second_content, "second.eml"))

    monkeypatch.setattr(web_upload.http.server.HTTPServer, "handle_request", handle_request)

    first_upload = new_service().receive_upload()
    assert second_upload == {"filename": "second.eml", "content": second_content}
    assert first_upload == {"filename": "first.eml", "content": first_content}


def web_upload_request_handler(body):
    # The real handler normally processes a socket in its constructor.
    handler = object.__new__(web_upload._UploadRequestHandler)
    handler.headers = {
        "Content-Type": "multipart/form-data; boundary=boundary",
        "Content-Length": str(len(body)),
    }
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.server = Mock()
    handler.server.parser = web_upload.UploadParser()
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.send_error = Mock()
    return handler


def test_web_upload_valid_web_eml_matches_folder_input(tmp_path, monkeypatch):
    from email.message import EmailMessage

    email = EmailMessage()
    email["From"] = "fictional@example.test"
    email["Subject"] = "Fictional verification"
    email.set_content(
        '<p>Caf\u00e9 account notice</p><a href="https://example.test/verify">Verify</a>',
        subtype="html",
        charset="utf-8",
        cte="base64",
    )
    raw = email.as_bytes()
    path = tmp_path / "valid.EML"
    path.write_bytes(raw)
    handler = web_upload_request_handler(web_upload_form(raw, filename="valid.EML"))
    handler.do_POST()
    handler.send_response.assert_called_once_with(200)
    handler.send_error.assert_not_called()
    handler.server.accept_upload.assert_called_once()
    answers = iter(["no", "no", "no"] * 2)
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(
        io_manager.folder_picker,
        "get_eml_from_folder",
        lambda: io_manager.eml_reader.read_path(path),
    )
    folder = io_manager.collect_input_from_folder()
    browser = io_manager.collect_input_from_upload(handler.server.accept_upload.call_args.args[0])
    assert browser == folder
    assert browser["sender"] == "fictional@example.test"
    assert browser["message"].startswith("Subject: Fictional verification\n\n")
    assert "Caf\u00e9 account notice" in browser["message"]
    assert "https://example.test/verify" in browser["message"]
    assert "Content-Transfer-Encoding" not in browser["message"]


@pytest.mark.parametrize(
    "filename",
    [
        "notes.txt",
        "image.png",
        "attachment.pdf",
        "archive.zip",
        "email.eml.exe",
    ],
)
def test_web_upload_web_upload_is_eml_only_with_clear_rejection(monkeypatch, filename):

    message = "Only .eml email files are supported. Images and attachments are not analysed."
    handler = web_upload_request_handler(web_upload_form(b"Not an email.", filename=filename))
    handler.do_POST()
    handler.send_error.assert_called_once_with(400, message)
    handler.server.accept_upload.assert_not_called()
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Invalid upload asked for input"))
    with pytest.raises(ValueError, match=r"Only \.eml email files"):
        io_manager.collect_input_from_upload({"filename": filename, "content": b"Not an email."})


@pytest.mark.parametrize("large_request", [False, True])
def test_web_upload_web_upload_limit_rejects_oversize_before_completion(large_request):
    handler = web_upload_request_handler(web_upload_form(b"x" * (web_upload.MAX_UPLOAD_BYTES + 1)))
    if large_request:
        handler.headers["Content-Length"] = str(web_upload.MAX_REQUEST_BYTES + 1)
        handler.rfile = Mock()
        handler.rfile.read.side_effect = AssertionError("Oversized request must not be read")
    handler.do_POST()
    handler.send_error.assert_called_once_with(413, "Email file exceeds the 2 MiB size limit.")
    handler.server.accept_upload.assert_not_called()
    if large_request:
        handler.rfile.read.assert_not_called()
