# misc/web_upload.py
# EXPERIMENTAL: minimal, lazy, one-shot file upload using only the standard
# library (http.server) - no extra dependencies, no classes defined (C1 safe).
#
# start_and_wait_for_upload() serves a tiny upload page, waits for one file,
# then shuts the server down and returns the file's text.

import http.server
import os

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
    "<h1>Upload a file to assess</h1>"
    "<p>Click anywhere to choose a file.</p>"
    "<div class='pulse'>Waiting for your file&hellip;</div>"
    "</div>"
    "<form id='f' method='post' enctype='multipart/form-data'>"
    "<input id='file' type='file' name='file' hidden></form>"
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

# Shared state between the request handler and the waiting CLI.
_result = {"text": None, "done": False}


def _handle(handler):
    """Serve the form on GET, store the uploaded file on POST. Plain function."""
    if handler.command == "GET":
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html")
        handler.end_headers()
        handler.wfile.write(_PAGE)
        return

    # Minimal multipart parse (cgi was removed in Python 3.13+): read the body,
    # split on the boundary, and take the bytes after the part's blank line.
    length = int(handler.headers.get("Content-Length", 0))
    body = handler.rfile.read(length)
    boundary = handler.headers["Content-Type"].split("boundary=")[1].encode()
    part = body.split(b"--" + boundary)[1]
    file_bytes = part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
    _result["text"] = file_bytes.decode("utf-8", errors="replace")
    _result["done"] = True

    handler.send_response(200)
    handler.send_header("Content-Type", "text/html")
    handler.end_headers()
    handler.wfile.write(_DONE_PAGE)


def start_and_wait_for_upload():
    """Serve the upload page, handle requests until one file arrives, return its text."""
    _result["text"] = None
    _result["done"] = False

    # Build a request-handler class from the stdlib base WITHOUT defining a class
    # in our code: type() creates it, and GET/POST both delegate to _handle().
    handler_cls = type(
        "UploadHandler",
        (http.server.BaseHTTPRequestHandler,),
        {
            "do_GET": lambda self: _handle(self),
            "do_POST": lambda self: _handle(self),
            "log_message": lambda self, *args: None,  # silence request logging
        },
    )

    http.server.HTTPServer.allow_reuse_address = True
    server = http.server.HTTPServer((BIND_HOST, PORT), handler_cls)
    print(f"\nOpen http://{DISPLAY_HOST}:{PORT} in your browser to upload a file.")
    print("Waiting for upload... (Ctrl+C to cancel)")

    try:
        while not _result["done"]:
            server.handle_request()  # handles one request at a time
    finally:
        # Always release the port, even if the user pressed Ctrl+C to cancel.
        server.server_close()
    return _result["text"]
