"""Serve a browser form and accept one email per upload session."""

import http.server
import os
import re
from email import policy
from email.parser import BytesHeaderParser

from phishreport.io.eml import MAX_EML_BYTES
from phishreport.io.manager import UPLOAD_TYPE_MESSAGE

MAX_UPLOAD_BYTES = MAX_EML_BYTES
SIZE_ERROR = "Email file exceeds the 2 MiB size limit."
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 64 * 1024

# Bind to all interfaces so the server is reachable from the host when running
# inside Docker; override with UPLOAD_HOST if needed. The link we PRINT uses a
# browser-friendly host (localhost), since 0.0.0.0 isn't meant to be typed.
BIND_HOST = os.environ.get("UPLOAD_HOST", "0.0.0.0")
DISPLAY_HOST = os.environ.get("UPLOAD_DISPLAY_HOST", "localhost")
PORT = int(os.environ.get("UPLOAD_PORT", "8000"))

_STYLE = """
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: flex; align-items: center;
    justify-content: center; font-family: -apple-system, BlinkMacSystemFont,
    'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%); color: #e2e8f0;
  }
  .card {
    width: min(90vw, 420px); padding: 48px 36px; text-align: center;
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
    border-radius: 20px; backdrop-filter: blur(8px);
    box-shadow: 0 20px 60px rgba(0,0,0,0.35); cursor: pointer;
    transition: transform .15s ease, border-color .15s ease;
  }
  .card:hover { transform: translateY(-3px); border-color: #60a5fa; }
  .icon { font-size: 52px; line-height: 1; }
  h1 { margin: 18px 0 6px; font-size: 20px; font-weight: 600; }
  p { margin: 0; font-size: 14px; color: #94a3b8; }
  .pulse { margin-top: 22px; font-size: 13px; color: #60a5fa; }
"""

_PAGE = (
    "<!doctype html><html><head><meta charset='utf-8'>"
    "<title>PhishReport upload</title><meta name='viewport' "
    "content='width=device-width, initial-scale=1'>"
    f"<style>{_STYLE}</style></head><body>"
    "<div class='card' id='card'>"
    "<div class='icon'>&#128228;</div>"
    "<h1>Upload an email (.eml file)</h1>"
    f"<p>{UPLOAD_TYPE_MESSAGE}</p>"
    "<p>Click anywhere to choose an email (maximum 2 MiB).</p>"
    "<div class='pulse'>Waiting for your file&hellip;</div>"
    "</div>"
    "<form id='f' method='post' enctype='multipart/form-data'>"
    "<input id='file' type='file' name='file' accept='.eml' hidden></form>"
    "<script>"
    # Opening a file dialog needs a user gesture, so open it on the first click
    # anywhere; auto-submit as soon as a file is chosen (no Upload button).
    "var inp=document.getElementById('file');"
    "document.body.addEventListener('click',function(){inp.click();});"
    "inp.addEventListener('change',function(){"
    "if(inp.files.length){document.getElementById('f').submit();}});"
    "</script></body></html>"
).encode()

_DONE_PAGE = (
    "<!doctype html><html><head><meta charset='utf-8'>"
    "<title>PhishReport</title><meta name='viewport' "
    "content='width=device-width, initial-scale=1'>"
    f"<style>{_STYLE}</style></head><body>"
    "<div class='card' style='cursor:default'>"
    "<div class='icon'>&#9989;</div>"
    "<h1>File received</h1>"
    "<p>You can close this tab and return to the terminal.</p>"
    "</div></body></html>"
).encode()


class UploadParser:
    """Validate one bounded multipart request and extract its .eml file."""

    def parse(self, content_type, body):
        """Return filename and original content bytes from one bounded multipart upload.

        Require a single .eml file field and valid framing; raise ValueError for
        rejected headers, structure or size. Email decoding belongs to the I/O
        layer after upload, so accepted bytes are not rewritten here.
        """
        if len(body) > MAX_REQUEST_BYTES:
            raise ValueError(SIZE_ERROR)
        if not isinstance(content_type, str) or "\r" in content_type or "\n" in content_type:
            raise ValueError("Invalid upload content type.")
        message = BytesHeaderParser(policy=policy.default).parsebytes(
            b"Content-Type: " + content_type.encode("ascii") + b"\r\n\r\n"
        )
        boundary = message.get_boundary()
        if message.get_content_type() != "multipart/form-data" or not boundary:
            raise ValueError("Expected a multipart file upload.")
        # Delimit only complete boundary lines. Do not MIME-parse the file itself:
        # message/rfc822 files otherwise become nested message objects and lose the
        # original-byte contract. The common email parser handles them afterwards.
        if len(boundary) > 70 or "\r" in boundary or "\n" in boundary:
            raise ValueError("Invalid upload boundary.")
        delimiters = list(
            re.finditer(
                rb"(?:\A|\r\n)--"
                + re.escape(boundary.encode("ascii"))
                + rb"(--)?[ \t]*(?:\r\n|\Z)",
                body,
            )
        )
        if len(delimiters) != 2 or delimiters[0].group(1) or not delimiters[1].group(1):
            raise ValueError("Upload exactly one file.")
        raw_part = body[delimiters[0].end() : delimiters[1].start()]
        headers, separator, content = raw_part.partition(b"\r\n\r\n")
        if not separator:
            raise ValueError("Invalid file upload headers.")
        part = BytesHeaderParser(policy=policy.default).parsebytes(headers + b"\r\n\r\n")
        if (
            part.defects
            or part.get_content_disposition() != "form-data"
            or part.get_param("name", header="content-disposition") != "file"
        ):
            raise ValueError("Invalid file upload field.")
        if part.get("Content-Transfer-Encoding", "binary").lower() not in ("binary", "8bit"):
            raise ValueError("Unsupported upload encoding.")
        filename = part.get_filename()
        if not filename or not filename.lower().endswith(".eml"):
            raise ValueError(UPLOAD_TYPE_MESSAGE)
        if not content:
            raise ValueError("Email file is empty.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError(SIZE_ERROR)
        return {"filename": filename, "content": content}


class _UploadRequestHandler(http.server.BaseHTTPRequestHandler):
    """Serve the upload form and pass accepted files to the session server."""

    timeout = 15

    def do_GET(self):
        self._send_page(_PAGE)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ValueError("Invalid upload length.")
            if length > MAX_REQUEST_BYTES:
                self.send_error(413, SIZE_ERROR)
                return
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete upload.")
            upload = self.server.parser.parse(self.headers.get("Content-Type"), body)
        except ValueError as error:
            self.send_error(413 if str(error) == SIZE_ERROR else 400, str(error))
            return
        except (OSError, RecursionError):
            self.send_error(400, "Upload failed. Please try again with an .eml email.")
            return

        self.server.accept_upload(upload)
        self._send_page(_DONE_PAGE)

    def log_message(self, format, *args):
        """Keep HTTP access logs out of the interactive terminal."""

    def _send_page(self, page):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(page)


class _UploadServer(http.server.HTTPServer):
    """Own the accepted file for a single upload session."""

    def __init__(self, address, parser):
        self._upload = None
        self.parser = parser
        super().__init__(address, _UploadRequestHandler)

    def accept_upload(self, upload):
        self._upload = upload

    def wait_for_upload(self):
        """Serve requests serially until a valid file arrives."""
        while self._upload is None:
            self.handle_request()
        return self._upload


class BrowserUploadService:
    """Run one browser upload session: serve the form, parse and return the email."""

    def __init__(self, host=None, port=None, parser=None, server_factory=None):
        self._host = BIND_HOST if host is None else host
        self._port = PORT if port is None else port
        self._parser = parser or UploadParser()
        self._server_factory = server_factory or _UploadServer

    def receive_upload(self):
        """Block until one valid upload arrives, then return its filename/content dict.

        Release the socket on exit, including cancellation. Configuration and
        server errors propagate to the application upload flow.
        """
        if type(self._port) is not int or not 0 <= self._port <= 65535:
            raise ValueError("UPLOAD_PORT must be an integer from 0 to 65535.")
        with self._server_factory((self._host, self._port), self._parser) as server:
            return server.wait_for_upload()
