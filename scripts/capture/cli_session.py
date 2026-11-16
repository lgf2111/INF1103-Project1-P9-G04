"""Drive the real CLI through a pty and record everything it prints.

Usage:
    python scripts/capture/cli_session.py <out.json> <scenario>

Scenarios: assess, summary. The script answers the documented prompts in order and
records each output chunk with a timestamp, so the recording can be replayed as a
terminal animation.
"""

from __future__ import annotations

import json
import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path("/tmp/phishreport-demo")

MESSAGE_LINES = [
    "Dear customer, your DBS account has been locked due to unusual activity.",
    "",
    "Verify your identity within 24 hours or your account will be suspended:",
    "https://dbs-secure-verify.example/login",
    "",
    "DBS Security Team",
]

PROMPTS = {
    "menu": "Choose 1-6: ",
    "channel": "Enter channel (Email/SMS/Chat): ",
    "sender": "Enter sender information (press Enter if unknown): ",
    "message": "Enter the suspicious message: ",
    "link": "Was a link included? (yes/no): ",
    "link_text": "Enter the link: ",
    "file": "Was a file included? (yes/no): ",
    "clicked": "Did you click the link? (yes/no): ",
    "downloaded": "Did you download the file? (yes/no): ",
    "submitted": "Did you give a password or code? (password/otp/no): ",
    "feedback": "Would you like to leave feedback about this assessment? (yes/no): ",
    "category": "Choose a feedback category (1-7): ",
    "comment": "Additional details (press Enter to skip): ",
    "priority": "Priority to include (high, medium, low, or Enter for all): ",
    "channel_filter": "Channel to include (email, sms, chat, or Enter for all): ",
}

ASSESS = [
    ("menu", "1"),
    ("channel", "sms"),
    ("sender", "+65 9123 4567"),
    ("message", "\n".join(MESSAGE_LINES) + "\nEND"),
    ("link", "yes"),
    ("link_text", "https://dbs-secure-verify.example/login"),
    ("file", "no"),
    ("clicked", "yes"),
    ("submitted", "password"),
    ("feedback", "yes"),
    ("category", "4"),
    ("comment", "Trace was clear, the band matched what happened."),
    ("menu", "6"),
]

SQLITE = [
    ("menu", "1"),
    ("channel", "email"),
    ("sender", "billing@example.test"),
    ("message", "Invoice 8891 is overdue. Settle it at https://billing-portal.example\nEND"),
    ("link", "yes"),
    ("link_text", "https://billing-portal.example"),
    ("file", "no"),
    ("clicked", "no"),
    ("submitted", "no"),
    ("feedback", "no"),
    ("menu", "4"),
    ("menu", "6"),
]

SUMMARY = [
    ("menu", "4"),
    ("menu", "5"),
    ("priority", ""),
    ("channel_filter", "sms"),
    ("menu", "6"),
]


def drain(master: int, buffer: bytes) -> bytes:
    while True:
        ready, _, _ = select.select([master], [], [], 0.05)
        if not ready:
            return buffer
        try:
            chunk = os.read(master, 65536)
        except OSError:
            return buffer
        if not chunk:
            return buffer
        buffer += chunk


def run(scenario: list[tuple[str, str]], out_path: Path) -> None:
    env = dict(os.environ)
    env["PHISHREPORT_REPORTS_PATH"] = str(DATA / "reports.json")
    if os.environ.get("CAPTURE_SQLITE") == "1":
        env["PHISHREPORT_STORAGE"] = "sqlite"
        env["PHISHREPORT_REPORTS_PATH"] = str(DATA / "demo-reports.json")
    env["PYTHONUNBUFFERED"] = "1"
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [
            "uv", "run", "--python", "3.14", "--no-project",
            "--with-requirements", "requirements.txt",
            "python", "-m", "phishreport.cli",
        ],
        cwd=ROOT,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        close_fds=True,
    )
    os.close(slave)
    started = time.monotonic()
    chunks: list[dict] = []
    buffer = b""
    index = 0
    try:
        while index < len(scenario) and process.poll() is None:
            buffer = drain(master, buffer)
            if not buffer:
                time.sleep(0.05)
                continue
            prompt = PROMPTS[scenario[index][0]].encode()
            if prompt and not buffer.rstrip().endswith(prompt.rstrip()):
                time.sleep(0.05)
                continue
            chunks.append({
                "t": round(time.monotonic() - started, 2),
                "text": buffer.decode("utf-8", "replace"),
            })
            answer, index = scenario[index][1], index + 1
            os.write(master, (answer + "\n").encode())
            buffer = b""
            time.sleep(0.15)
        # final output until the process exits
        deadline = time.monotonic() + 30
        while process.poll() is None and time.monotonic() < deadline:
            chunk = os.read(master, 65536) if select.select([master], [], [], 0.2)[0] else b""
            if chunk:
                buffer += chunk
        if buffer:
            chunks.append({
                "t": round(time.monotonic() - started, 2),
                "text": buffer.decode("utf-8", "replace"),
            })
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        os.close(master)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"chunks": chunks}, indent=1), encoding="utf-8")
    print(f"{len(chunks)} chunks -> {out_path}")


def main() -> int:
    out = Path(sys.argv[1])
    scenario = sys.argv[2] if len(sys.argv) > 2 else "assess"
    DATA.mkdir(parents=True, exist_ok=True)
    if scenario == "assess" and not (DATA / "reports.json").exists():
        (DATA / "reports.json").write_text("[]", encoding="utf-8")
    scenario_map = {"assess": ASSESS, "summary": SUMMARY, "sqlite": SQLITE}
    run(scenario_map[scenario], out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
