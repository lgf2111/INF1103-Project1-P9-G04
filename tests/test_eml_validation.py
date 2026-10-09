"""Malformed imports must never silently become a different assessment input."""
import os
import subprocess
import sys
from pathlib import Path

import io_manager
import pytest


@pytest.mark.parametrize("raw", [
    b"Content-Type: text/plain; charset=utf-8\r\n\r\nHello \xff password",
    b"Content-Transfer-Encoding: base64\r\n\r\na",
    b"From: a@@example.test\r\n\r\nHello",
    b"Subject: =?utf-8?b?/w==?=\r\n\r\nHello",
    b"Subject: =?unknown-charset?q?Hello?=\r\n\r\nHello",
    b"Subject: =?utf-8?b?SGVsbG8?=\r\n\r\nHello",
    b"Subject: =?utf-8?q?Hello=GG?=\r\n\r\nHello",
    b"Content-Transfer-Encoding: quoted-printable\r\n\r\nHello=GG",
    b"Content-Transfer-Encoding: unknown\r\n\r\nHello",
])
def test_malformed_import_reprompts_before_success(tmp_path, monkeypatch, capsys, raw):
    bad = tmp_path / "bad.eml"
    good = tmp_path / "good.eml"
    bad.write_bytes(raw)
    good.write_bytes(b"From: fictional@example.test\r\n\r\nValid message")
    answers = iter([str(bad), str(good)])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert io_manager.get_eml_input() == ("fictional@example.test", "Valid message")
    output = capsys.readouterr().out
    assert output.count("Unable to read") == 1
    assert output.count("Email loaded successfully") == 1


def _multipart(*parts):
    return (b"Content-Type: multipart/mixed; boundary=x\r\n\r\n"
            + b"".join(b"--x\r\n" + part + b"\r\n" for part in parts)
            + b"--x--\r\n")


def test_all_inline_plain_text_reaches_canonical_message(tmp_path):
    email = tmp_path / "mixed.eml"
    email.write_bytes(_multipart(
        b"Content-Type: text/plain\r\n\r\nHello",
        b"Content-Type: text/plain\r\n\r\nReply with your password and OTP",
    ))
    assert io_manager.read_eml_details(email)[1] == (
        "Hello\n\nReply with your password and OTP"
    )


@pytest.mark.parametrize("raw", [
    b"Content-Type: text/html\r\n\r\n<p>Reply with your password</p>",
    _multipart(b"Content-Type: text/plain\r\n\r\nHello",
               b"Content-Type: text/html\r\n\r\n<p>Reply with your password</p>"),
    _multipart(b"Content-Type: text/plain\r\n\r\nHello",
               b"Content-Type: message/rfc822\r\n\r\nFrom: x@example.test\r\n\r\nOTP"),
])
def test_unsupported_inline_body_is_rejected_not_partially_assessed(tmp_path, raw):
    email = tmp_path / "unsupported.eml"
    email.write_bytes(raw)
    with pytest.raises(ValueError, match="Unsupported"):
        io_manager.read_eml_details(email)


def test_explicit_attachment_is_not_an_inline_body(tmp_path):
    email = tmp_path / "attachment.eml"
    email.write_bytes(_multipart(
        b"Content-Type: text/plain\r\n\r\nHello",
        b"Content-Type: application/octet-stream\r\n"
        b"Content-Disposition: attachment; filename=test.bin\r\n\r\nDATA",
    ))
    assert io_manager.read_eml_details(email)[1] == "Hello"


@pytest.mark.parametrize("content_type", ["text/plain", "text/html"])
def test_inline_filename_does_not_hide_body_content(tmp_path, content_type):
    email = tmp_path / "inline.eml"
    email.write_bytes(_multipart(
        b"Content-Type: text/plain\r\n\r\nHello",
        (f"Content-Type: {content_type}\r\n"
         "Content-Disposition: inline; filename=message.txt\r\n\r\n"
         "Reply with your password").encode(),
    ))
    if content_type == "text/plain":
        assert "Reply with your password" in io_manager.read_eml_details(email)[1]
    else:
        with pytest.raises(ValueError, match="Unsupported"):
            io_manager.read_eml_details(email)


@pytest.mark.parametrize("raw, expected", [
    (b"Content-Type: text/plain; charset=utf-8\r\n\r\nHello \xef\xbf\xbd", "Hello \ufffd"),
    (b"Content-Type: text/plain; charset=iso-8859-1\r\n\r\nCaf\xe9", "Caf\u00e9"),
    (b"Content-Type: text/plain; charset=utf-8\r\n"
     b"Content-Transfer-Encoding: base64\r\n\r\nQ2Fmw6k=", "Caf\u00e9"),
    (b"Content-Type: text/plain; charset=utf-8\r\n"
     b"Content-Transfer-Encoding: quoted-printable\r\n\r\nCaf=C3=A9", "Caf\u00e9"),
    (b"Subject: =?utf-8?b?Q2Fmw6k=?=\r\n\r\nHello", "Subject: Caf\u00e9\n\nHello"),
])
def test_valid_decoding_preserves_characters(tmp_path, raw, expected):
    email = tmp_path / "valid.eml"
    email.write_bytes(raw)
    assert io_manager.read_eml_details(email)[1] == expected


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO requires POSIX")
@pytest.mark.parametrize("replace_after_check", [False, True])
def test_fifo_never_blocks_before_file_validation(tmp_path, replace_after_check):
    fifo = tmp_path / "pipe.eml"
    os.mkfifo(fifo)
    # Isolate the timeout so a regression cannot hang the test suite.
    script = (
        "from pathlib import Path\nimport io_manager\n"
        + ("Path.is_file = lambda self: True\n" if replace_after_check else "")
        + "try:\n    io_manager.read_eml_details(" + repr(str(fifo)) + ")\n"
        + "except ValueError:\n    pass\nelse:\n    raise AssertionError('FIFO accepted')\n"
    )
    env = dict(os.environ, PYTHONPATH=str(Path(io_manager.__file__).resolve().parent.parent))
    subprocess.run([sys.executable, "-c", script], env=env, timeout=5, check=True,
                   capture_output=True)
