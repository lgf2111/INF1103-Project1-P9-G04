"""I/O manager functions, display, HTML email and .eml validation."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from phishreport import io_manager, logic_manager
from phishreport.ai import AIManager
from phishreport.email_html import html_to_text

REAL_EMAILS = Path(__file__).resolve().parents[1] / "fixtures"


# ============================================================================
# Io Manager
# ============================================================================
def test_io_manager_ask_yes_no_accepts_yes(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "YES")

    result = io_manager.ask_yes_no("Test: ")

    assert result is True


def test_io_manager_ask_yes_no_accepts_no(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "No")

    result = io_manager.ask_yes_no("Test: ")

    assert result is False


def test_io_manager_ask_yes_no_reprompts_invalid_input(monkeypatch):
    answers = iter(["hello", "yes"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.ask_yes_no("Test: ")

    assert result is True


@pytest.mark.parametrize("choice", ["1", "2", "3", "4", "5"])
def test_io_manager_main_menu_accepts_valid_choice(monkeypatch, choice):
    monkeypatch.setattr("builtins.input", lambda _: choice)

    result = io_manager.main_menu()

    assert result == choice


def test_io_manager_main_menu_reprompts_invalid_choice(monkeypatch):
    answers = iter(["6", "hello", "1"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.main_menu()

    assert result == "1"


def test_io_manager_get_channel_accepts_case_insensitive_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "EMAIL")

    result = io_manager.get_channel()

    assert result == "email"


def test_io_manager_get_channel_reprompts_invalid_input(monkeypatch):
    answers = iter(["discord", "Chat"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_channel()

    assert result == "chat"


def test_io_manager_get_sender_allows_blank_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")

    result = io_manager.get_sender()

    assert result is None


def test_io_manager_get_message_reprompts_blank_input(monkeypatch):
    answers = iter(["", "   ", "Suspicious message"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_message()

    assert result == "Suspicious message"


def test_io_manager_get_link_information_reprompts_blank_link(monkeypatch):
    answers = iter(["yes", "", "   ", "https://example.com"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_link_information()

    assert result == (True, "https://example.com")


def test_io_manager_get_file_information_reprompts_blank_file(monkeypatch):
    answers = iter(["yes", "", "   ", "Update.exe"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_file_information()

    assert result == (True, "Update.exe")


def test_io_manager_get_submitted_category_accepts_case_insensitive_otp(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "OTP")

    result = io_manager.get_submitted_category()

    assert result == "otp"


def test_io_manager_get_submitted_category_reprompts_invalid_input(monkeypatch):
    answers = iter(["hello", "credit card", "otp"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_submitted_category()

    assert result == "otp"


def test_io_manager_collect_user_actions_with_link_and_file(monkeypatch):
    answers = iter(["no", "yes", "no"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.collect_user_actions(True, True)

    assert result == {
        "clicked": False,
        "downloaded": True,
        "submitted_category": None,
    }


def test_io_manager_collect_user_actions_without_link(monkeypatch):
    answers = iter(["yes", "password"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.collect_user_actions(False, True)

    assert result == {
        "clicked": False,
        "downloaded": True,
        "submitted_category": "password",
    }


def test_io_manager_collect_user_actions_without_link_or_file(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "no")

    result = io_manager.collect_user_actions(False, False)

    assert result == {
        "clicked": False,
        "downloaded": False,
        "submitted_category": None,
    }


def test_io_manager_collect_input_returns_complete_record(monkeypatch):
    answers = iter(
        [
            "Email",
            "update@micr0soft.com",
            "Download Update.exe immediately.",
            "no",
            "yes",
            "Update.exe",
            "yes",
            "no",
        ]
    )

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.collect_input()

    assert result == {
        "channel": "email",
        "sender": "update@micr0soft.com",
        "message": "Download Update.exe immediately.",
        "has_link": False,
        "link": None,
        "has_file": True,
        "file_name": "Update.exe",
        "clicked": False,
        "downloaded": True,
        "submitted_category": None,
    }


def test_io_manager_get_valid_choice_reprompts_invalid_input(monkeypatch):
    answers = iter(["wrong", "A"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_valid_choice(
        "Choose: ",
        ("a", "b"),
        "Invalid: ",
    )

    assert result == "a"


def test_io_manager_read_eml_details_extracts_email_content(tmp_path):
    email_file = tmp_path / "sample.eml"

    email_file.write_text(
        "From: Microsoft Updates <update@micr0soft.com>\n"
        "Subject: Private Microsoft Beta\n"
        "MIME-Version: 1.0\n"
        'Content-Type: text/plain; charset="utf-8"\n'
        "\n"
        "You have been selected for our private Microsoft beta programme.\n"
        "Download Update.exe immediately.\n",
        encoding="utf-8",
    )

    sender, message = io_manager.read_eml_details(email_file)

    assert sender == "Microsoft Updates <update@micr0soft.com>"

    assert message == (
        "Subject: Private Microsoft Beta\n\n"
        "You have been selected for our private Microsoft beta programme.\n"
        "Download Update.exe immediately."
    )


def test_io_manager_read_eml_details_rejects_empty_message(tmp_path):
    # Create an email with an empty message body
    empty_email = tmp_path / "empty.eml"

    empty_email.write_text(
        "From: sender@example.com\n"
        "Subject: Empty Message\n"
        'Content-Type: text/plain; charset="utf-8"\n'
        "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="No readable email message"):
        io_manager.read_eml_details(empty_email)


def test_io_manager_collect_input_from_folder_with_follow_up_questions(monkeypatch, tmp_path):
    email_file = tmp_path / "suspicious.eml"

    email_file.write_text(
        "From: update@micr0soft.com\n"
        "Subject: Private Microsoft Beta\n"
        'Content-Type: text/plain; charset="utf-8"\n'
        "\n"
        "Download Update.exe immediately.\n",
        encoding="utf-8",
    )

    answers = iter(
        [
            "yes",  # Link included?
            "https://example.com/verify",  # Link
            "yes",  # File included?
            "Update.exe",  # File name
            "yes",  # Clicked link?
            "no",  # Downloaded file?
            "otp",  # Password/OTP disclosed?
        ]
    )

    prompts = []

    def fake_input(prompt):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)

    picker = io_manager.default_io_manager.folder_picker
    monkeypatch.setattr(picker, "get_eml_folder", lambda: str(tmp_path))
    monkeypatch.setattr(picker, "choose_eml_file", lambda folder: email_file)
    record = io_manager.collect_input_from_folder()

    assert record == {
        "channel": "email",
        "sender": "update@micr0soft.com",
        "message": ("Subject: Private Microsoft Beta\n\nDownload Update.exe immediately."),
        "has_link": True,
        "link": "https://example.com/verify",
        "has_file": True,
        "file_name": "Update.exe",
        "clicked": True,
        "downloaded": False,
        "submitted_category": "otp",
    }

    assert any("Was a link included?" in p for p in prompts)
    assert any("Was a file included?" in p for p in prompts)
    assert any("Did you click the link?" in p for p in prompts)
    assert any("Did you download the file?" in p for p in prompts)
    assert any("Did you give a password or code?" in p for p in prompts)


def test_io_manager_read_eml_details_rejects_deeply_nested_mime(tmp_path):
    # Create an email with 1,100 nested MIME containers.
    nested_email = tmp_path / "nested.eml"
    depth = 1100

    lines = [
        "From: nested@example.com",
        "Subject: Deeply Nested Email",
        "MIME-Version: 1.0",
        'Content-Type: multipart/mixed; boundary="part0"',
        "",
    ]

    for i in range(depth):
        lines.append(f"--part{i}")

        if i < depth - 1:
            lines.extend(
                [
                    f'Content-Type: multipart/mixed; boundary="part{i + 1}"',
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    'Content-Type: text/plain; charset="utf-8"',
                    "",
                    "This is a test message.",
                ]
            )

    for i in reversed(range(depth)):
        lines.append(f"--part{i}--")

    nested_email.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="deeply nested|nesting is too deep"):
        io_manager.read_eml_details(nested_email)


def test_io_manager_read_eml_details_rejects_too_many_mime_parts(tmp_path):
    email_file = tmp_path / "too_many_parts.eml"

    lines = [
        "From: sender@example.com",
        "Subject: Too Many Parts",
        "MIME-Version: 1.0",
        'Content-Type: multipart/mixed; boundary="section"',
        "",
    ]

    # Create 100 child MIME parts.
    # Together with the root email, that makes 101 parts.
    for number in range(100):
        lines.extend(
            [
                "--section",
                'Content-Type: text/plain; charset="utf-8"',
                "",
                f"Message part {number}",
                "",
            ]
        )

    lines.append("--section--")

    email_file.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="too many MIME parts"):
        io_manager.read_eml_details(email_file)


def test_io_manager_read_eml_details_rejects_excessive_mime_depth(tmp_path):
    from email import policy
    from email.parser import BytesParser

    email_file = tmp_path / "too_deep.eml"
    depth = 33

    lines = [
        "From: sender@example.com",
        "Subject: Deeply Nested Email",
        "MIME-Version: 1.0",
        'Content-Type: multipart/mixed; boundary="part0"',
        "",
    ]

    # Create nested MIME containers.
    for i in range(depth):
        lines.append(f"--part{i}")

        if i < depth - 1:
            lines.extend(
                [
                    f'Content-Type: multipart/mixed; boundary="part{i + 1}"',
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    'Content-Type: text/plain; charset="utf-8"',
                    "",
                    "This is a test message.",
                    "",
                ]
            )

    # Close every MIME boundary.
    for i in reversed(range(depth)):
        lines.append(f"--part{i}--")

    email_file.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))

    parsed_email = BytesParser(policy=policy.default).parsebytes(email_file.read_bytes())

    with pytest.raises(ValueError, match="nesting is too deep"):
        io_manager.validate_mime_limits(parsed_email)

    with pytest.raises(ValueError, match="nesting is too deep"):
        io_manager.read_eml_details(email_file)


def test_io_manager_read_eml_details_accepts_exactly_100_mime_parts(tmp_path):
    email_file = tmp_path / "exactly_100_parts.eml"

    lines = [
        "From: sender@example.com",
        "Subject: MIME Boundary Test",
        "MIME-Version: 1.0",
        'Content-Type: multipart/mixed; boundary="section"',
        "",
    ]

    # 99 child parts + 1 root email = 100 MIME parts.
    for number in range(99):
        lines.extend(
            [
                "--section",
                'Content-Type: text/plain; charset="utf-8"',
                "",
                f"Message part {number}",
                "",
            ]
        )

    lines.append("--section--")

    # Write exact CRLF bytes to avoid Windows newline conversion.
    email_file.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))

    sender, message = io_manager.read_eml_details(email_file)

    assert sender == "sender@example.com"
    assert "Subject: MIME Boundary Test" in message
    assert "Message part 0" in message


def test_io_manager_read_eml_details_accepts_exactly_32_mime_depth(tmp_path):
    email_file = tmp_path / "exactly_32_depth.eml"
    depth = 32

    lines = [
        "From: sender@example.com",
        "Subject: MIME Depth Boundary Test",
        "MIME-Version: 1.0",
        'Content-Type: multipart/mixed; boundary="part0"',
        "",
    ]

    # Create 32 levels of MIME nesting.
    for i in range(depth):
        lines.append(f"--part{i}")

        if i < depth - 1:
            lines.extend(
                [
                    f'Content-Type: multipart/mixed; boundary="part{i + 1}"',
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    'Content-Type: text/plain; charset="utf-8"',
                    "",
                    "This email is within the allowed MIME depth.",
                    "",
                ]
            )

    # Close all MIME boundaries.
    for i in reversed(range(depth)):
        lines.append(f"--part{i}--")

    # Use write_bytes to preserve CRLF on Windows.
    email_file.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))

    sender, message = io_manager.read_eml_details(email_file)

    assert sender == "sender@example.com"
    assert message == (
        "Subject: MIME Depth Boundary Test\n\nThis email is within the allowed MIME depth."
    )


def test_io_manager_read_eml_details_accepts_exactly_2_mib(tmp_path):
    email_file = tmp_path / "exactly_2_mib.eml"

    email_content = (
        b"From: sender@example.com\r\n"
        b"Subject: File Size Boundary Test\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: text/plain; charset="utf-8"\r\n'
        b"\r\n"
        b"This is a valid email.\r\n"
    )

    # Calculate how many bytes are needed to reach 2 MiB.
    padding_size = io_manager.MAX_EML_BYTES - len(email_content)

    # Add trailing whitespace without changing the actual message.
    email_file.write_bytes(email_content + b" " * padding_size)

    # Confirm the file is exactly 2 MiB.
    assert email_file.stat().st_size == io_manager.MAX_EML_BYTES

    sender, message = io_manager.read_eml_details(email_file)

    assert sender == "sender@example.com"
    assert message == ("Subject: File Size Boundary Test\n\nThis is a valid email.")


def test_io_manager_read_eml_details_rejects_over_2_mib(tmp_path):
    email_file = tmp_path / "over_2_mib.eml"

    email_content = (
        b"From: sender@example.com\r\n"
        b"Subject: Oversized Email\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: text/plain; charset="utf-8"\r\n'
        b"\r\n"
        b"This is a test message.\r\n"
    )

    # Create a file that exceeds 2 MiB by exactly 1 byte.
    target_size = io_manager.MAX_EML_BYTES + 1
    padding_size = target_size - len(email_content)

    email_file.write_bytes(email_content + b" " * padding_size)

    # Verify the file exceeds the limit by 1 byte.
    assert email_file.stat().st_size == target_size

    # The importer must reject the oversized email.
    with pytest.raises(ValueError, match="size limit"):
        io_manager.read_eml_details(email_file)


def test_io_manager_read_eml_details_rejects_message_over_50000_chars(tmp_path):
    email_file = tmp_path / "long_message.eml"

    email_content = (
        b"From: sender@example.com\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: text/plain; charset="utf-8"\r\n'
        b"\r\n" + b"A" * 50001
    )

    email_file.write_bytes(email_content)

    # Confirm the raw file is within the 2 MiB limit.
    assert email_file.stat().st_size < io_manager.MAX_EML_BYTES

    # The decoded message contains 50,001 characters.
    with pytest.raises(ValueError, match="message length limit"):
        io_manager.read_eml_details(email_file)


def test_io_manager_read_eml_details_accepts_exactly_50000_chars(tmp_path):
    email_file = tmp_path / "exactly_50000_chars.eml"

    subject = "Boundary Test"

    # This prefix is included in the final message.
    prefix = f"Subject: {subject}\n\n"

    # Fill the remaining space with 'A' characters.
    body = "A" * (io_manager.MAX_MESSAGE_CHARS - len(prefix))

    email_content = (
        "From: sender@example.com\r\n"
        f"Subject: {subject}\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n'
        "\r\n"
        f"{body}"
    )

    email_file.write_bytes(email_content.encode("utf-8"))

    # The raw email must remain below the 2 MiB limit.
    assert email_file.stat().st_size < io_manager.MAX_EML_BYTES

    sender, message = io_manager.read_eml_details(email_file)

    assert sender == "sender@example.com"
    assert len(message) == io_manager.MAX_MESSAGE_CHARS
    assert message == prefix + body


def test_io_manager_read_eml_details_rejects_duplicate_from_header(tmp_path):
    email_file = tmp_path / "duplicate_from.eml"

    email_file.write_bytes(
        b"From: support@microsoft.com\r\n"
        b"From: attacker@example.com\r\n"
        b"Subject: Account Verification\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: text/plain; charset="utf-8"\r\n'
        b"\r\n"
        b"Please verify your account.\r\n"
    )

    with pytest.raises(ValueError, match="Duplicate From header"):
        io_manager.read_eml_details(email_file)


def test_io_manager_read_eml_details_rejects_duplicate_subject_header(tmp_path):
    email_file = tmp_path / "duplicate_subject.eml"

    email_file.write_bytes(
        b"From: sender@example.com\r\n"
        b"Subject: Account Verification\r\n"
        b"Subject: Urgent Password Reset\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: text/plain; charset="utf-8"\r\n'
        b"\r\n"
        b"Please verify your account.\r\n"
    )

    with pytest.raises(ValueError, match="Duplicate Subject header"):
        io_manager.read_eml_details(email_file)


def test_io_manager_read_eml_details_rejects_missing_mime_boundary(tmp_path):
    email_file = tmp_path / "missing_boundary.eml"

    email_file.write_bytes(
        b"From: sender@example.com\r\n"
        b"Subject: Account Verification\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="section"\r\n'
        b"\r\n"
        b"--section\r\n"
        b'Content-Type: text/plain; charset="utf-8"\r\n'
        b"\r\n"
        b"Please verify your account.\r\n"
    )

    # The closing MIME boundary (--section--) is missing.
    with pytest.raises(ValueError, match="Malformed MIME structure"):
        io_manager.read_eml_details(email_file)


def test_io_manager_read_eml_details_rejects_missing_header_body_separator(tmp_path):
    email_file = tmp_path / "missing_separator.eml"

    email_file.write_bytes(
        b"From: sender@example.com\r\n"
        b"Subject: Account Verification\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: text/plain; charset="utf-8"\r\n'
        b"Please verify your account.\r\n"
    )

    # There is no blank line between the headers and body.
    with pytest.raises(ValueError, match="Malformed MIME structure"):
        io_manager.read_eml_details(email_file)


def test_io_manager_read_eml_details_rejects_invalid_base64(tmp_path):
    email_file = tmp_path / "invalid_base64.eml"

    email_file.write_bytes(
        b"From: sender@example.com\r\n"
        b"Subject: Invalid Base64 Test\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: text/plain; charset="utf-8"\r\n'
        b"Content-Transfer-Encoding: base64\r\n"
        b"\r\n"
        b"SGVsbG8gV29ybGQh$$$\r\n"
    )

    with pytest.raises(ValueError, match="Invalid Base64"):
        io_manager.read_eml_details(email_file)


def test_io_manager_read_eml_details_rejects_invalid_base64_padding(tmp_path):
    email_file = tmp_path / "invalid_padding.eml"

    email_file.write_bytes(
        b"From: sender@example.com\r\n"
        b"Subject: Invalid Base64 Padding\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: text/plain; charset="utf-8"\r\n'
        b"Content-Transfer-Encoding: base64\r\n"
        b"\r\n"
        b"SGVsbG8\r\n"
    )

    # Base64 content is missing its required padding.
    with pytest.raises(ValueError, match="Invalid Base64"):
        io_manager.read_eml_details(email_file)


def test_io_manager_collect_input_from_folder_without_link_or_file(monkeypatch, tmp_path):
    email_file = tmp_path / "sample.eml"

    email_file.write_bytes(
        b"From: sender@example.com\r\n"
        b"Subject: Test Email\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"This is a test message.\r\n"
    )

    answers = iter(
        [
            "no",  # Link included?
            "no",  # File included?
            "no",  # Password/OTP disclosed?
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda _: next(answers),
    )

    picker = io_manager.default_io_manager.folder_picker
    monkeypatch.setattr(picker, "get_eml_folder", lambda: str(tmp_path))
    monkeypatch.setattr(picker, "choose_eml_file", lambda folder: email_file)
    result = io_manager.collect_input_from_folder()

    assert result == {
        "channel": "email",
        "sender": "sender@example.com",
        "message": "Subject: Test Email\n\nThis is a test message.",
        "has_link": False,
        "link": None,
        "has_file": False,
        "file_name": None,
        "clicked": False,
        "downloaded": False,
        "submitted_category": None,
    }


def test_io_manager_collect_input_from_folder_cancel_skips_follow_up_questions(monkeypatch):
    picker = io_manager.default_io_manager.folder_picker
    monkeypatch.setattr(picker, "get_eml_from_folder", lambda: None)

    def unexpected_input(prompt):
        pytest.fail("Cancelled email selection must not ask follow-up questions")

    monkeypatch.setattr("builtins.input", unexpected_input)
    assert io_manager.collect_input_from_folder() is None


# ============================================================================
# Io Display
# ============================================================================
def test_io_display_display_result_shows_assessment(capsys):
    io_manager.display_result(
        {
            "priority": "insufficient_information",
            "score": 30,
            "reasons": ["More context is required."],
            "checklist": ["Give more details."],
        }
    )
    output = capsys.readouterr().out
    assert "Priority: Insufficient Information" in output
    assert "Rule-based score: 30" in output
    assert "More context is required." in output
    assert "1. Give more details." in output


def test_io_display_display_record_shows_complete_details(capsys):
    message = "Fictional message with enough words to exceed the preview limit of fifty characters."
    io_manager.display_record(
        {
            "channel": "email",
            "sender": None,
            "message": message,
            "link": None,
            "file_name": "example.txt",
            "clicked": False,
            "downloaded": True,
            "submitted_category": "otp",
            "result": {"priority": "high", "score": 90, "checklist": ["Tell IT."]},
        }
    )
    output = capsys.readouterr().out
    assert message in output
    assert "Sender: Unknown" in output
    assert "Included file: example.txt" in output
    assert "Clicked link: No" in output
    assert "Downloaded file: Yes" in output
    assert "Information submitted: One-time code" in output
    assert "Priority: High" in output


def test_io_display_display_record_without_assessment(capsys):
    io_manager.display_record({"message": "Older record"})
    output = capsys.readouterr().out
    assert "No assessment available." in output
    assert "No Clear Indicators" not in output


def test_io_display_display_list_shows_numbered_summaries(capsys):
    io_manager.display_list(
        [
            {
                "channel": "sms",
                "message": "Line one\nLine two",
                "result": {"priority": "review", "score": 50},
            },
            {
                "channel": "email",
                "message": "Second fictional message",
                "result": {"priority": "high", "score": 90},
            },
            {"channel": "chat", "message": "Database report", "priority": "MEDIUM", "score": 40},
            {"channel": "email", "message": "Legacy row", "priority": None, "score": None},
        ]
    )
    output = capsys.readouterr().out
    assert "1. SMS | Review | Score: 50" in output
    assert "2. Email | High | Score: 90" in output
    assert "3. Chat | Medium | Score: 40" in output
    assert "4. Email | Unavailable | Score: Unavailable" in output
    assert "Line one Line two" in output


def test_io_display_display_list_handles_empty_history(capsys):
    io_manager.display_list([])
    assert "No saved reports yet." in capsys.readouterr().out


def test_io_display_display_result_keeps_safety_wording(capsys):
    record = {
        "channel": "email",
        "sender": None,
        "message": "Test message",
        "has_link": False,
        "has_file": False,
        "link": None,
        "file_name": None,
        "clicked": False,
        "downloaded": False,
        "submitted_category": None,
    }
    details = {"emails": [], "phone_numbers": [], "ip_addresses": []}
    record["ai"] = {
        "credential_request": False,
        "suspicious": False,
        "insufficient_context": False,
        "details": details,
    }
    io_manager.display_result(logic_manager.evaluate(record))
    # Updated assertion to match the new LOW priority checklist
    assert "Remain cautious." in capsys.readouterr().out


def test_io_display_check_new_message_displays_full_record(cli, monkeypatch, capsys):
    message = "Fictional SMS message for the offline display integration test."
    record = {
        "channel": "sms",
        "sender": None,
        "message": message,
        "has_link": False,
        "link": None,
        "has_file": False,
        "file_name": None,
        "clicked": False,
        "downloaded": False,
        "submitted_category": None,
    }
    details = {"emails": [], "phone_numbers": [], "ip_addresses": []}
    findings = {
        "credential_request": False,
        "suspicious": False,
        "insufficient_context": False,
        "details": details,
    }
    saved = []
    api_calls = []

    def complete(prompt):
        """Return combined findings and extraction from one request."""
        api_calls.append(prompt)
        return json.dumps(findings)

    monkeypatch.setattr(cli.io_manager, "collect_input", lambda: record)
    client = SimpleNamespace(complete=complete)
    monkeypatch.setattr(cli.app, "_ai_manager", AIManager(client=client))
    monkeypatch.setattr(cli.data_manager, "save", saved.append)

    cli.app.check_message()
    output = capsys.readouterr().out

    # The new implementation displays the assessment result
    assert "Priority:" in output
    assert "Rule-based score:" in output  # Changed from "Score:"
    assert "Recommended actions:" in output

    # Verify the saved data structure
    assert len(saved) == 1
    assert saved[0]["channel"] == "sms"
    assert saved[0]["message"] == message
    assert set(saved[0]) == {"schema_version", "channel", "message", "result"}
    assert saved[0]["schema_version"] == 2
    assert set(saved[0]["result"]) == {"score", "priority", "reasons", "checklist"}

    assert len(api_calls) == 1


# ============================================================================
# Html Email
# ============================================================================
def html_email_email(html, headers=b""):
    return (
        b"From: fictional@example.test\r\nSubject: Fictional request\r\n"
        + headers
        + b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        + html.encode()
    )


def test_html_email_html_only_keeps_visible_text_and_different_link_target():
    raw = html_email_email(
        '<p>Account notice</p><a href="https://credential.example.test/login?a=1&amp;b=2">'
        "https://legitimate.example.test</a><p>Reply with a password</p>"
    )
    sender, message = io_manager.read_eml_bytes(raw)
    assert sender == "fictional@example.test"
    assert "Subject: Fictional request" in message
    assert "https://credential.example.test/login?a=1&b=2" in message
    assert "https://legitimate.example.test" in message
    assert "Reply with a password" in message
    assert "<a " not in message and "Content-Type:" not in message


def test_html_email_alternatives_retain_conflicting_html_instead_of_selecting_benign_plain():
    raw = (
        b"Content-Type: multipart/alternative; boundary=x\r\n\r\n"
        b"--x\r\nContent-Type: text/plain\r\n\r\nA routine notice.\r\n"
        b"--x\r\nContent-Type: text/html\r\n\r\n"
        b'<a href="https://credential.example.test">Enter password and OTP</a>\r\n--x--\r\n'
    )
    message = io_manager.read_eml_bytes(raw)[1]
    assert "A routine notice." in message
    assert "Enter password and OTP" in message
    assert "https://credential.example.test" in message


def test_html_email_related_images_do_not_block_html_or_get_decoded_as_text():
    raw = (
        b"Content-Type: multipart/related; boundary=x\r\n\r\n"
        b"--x\r\nContent-Type: text/html\r\n\r\n<p>Fictional notice</p>"
        b'<img src="cid:logo" alt="Account alert">\r\n'
        b"--x\r\nContent-Type: image/png\r\nContent-ID: <logo>\r\n\r\n\xff\x00\r\n"
        b"--x--\r\n"
    )
    message = io_manager.read_eml_bytes(raw)[1]
    assert "Account alert" in message and "Fictional notice" in message
    assert "cid:logo" not in message


def test_html_email_html_resources_and_scripts_are_never_requested_or_executed(monkeypatch):
    import urllib.request

    def no_network(*args, **kwargs):
        pytest.fail("HTML conversion must never fetch a resource")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    text = html_to_text(
        "<head><style>BAD_STYLE</style></head><script>BAD_SCRIPT</script>"
        '<p>Readable &amp; safe</p><img src="https://tracking.example.test/pixel" '
        'alt="Alert"><form action="https://credential.example.test">Password</form>',
        50000,
    )
    assert "BAD_STYLE" not in text and "BAD_SCRIPT" not in text
    assert "Readable & safe" in text and "Password" in text
    assert "https://tracking.example.test/pixel" in text
    assert "https://credential.example.test" in text


@pytest.mark.parametrize("html", ["<script>only script</script>", "<p> </p>", "<img src='cid:x'>"])
def test_html_email_html_without_usable_content_is_rejected(html):
    with pytest.raises(ValueError, match="no usable"):
        io_manager.read_eml_bytes(html_email_email(html))


def test_html_email_html_output_limits_include_attribute_expansion():
    with pytest.raises(ValueError, match="length limit"):
        html_to_text('<a href="' + "a" * 50000 + '">x</a>', 50000)


def test_html_email_forged_sender_is_preserved_as_untrusted_text_not_repaired():
    sender, message = io_manager.read_eml_bytes(b"From: a@@example.test\r\n\r\nHello")
    assert sender == "a@@example.test"
    assert message == "Hello"


def test_html_email_raw_utf8_headers_are_decoded_without_surrogates():
    sender, message = io_manager.read_eml_bytes(
        "From: Caf\u00e9 <fictional@example.test>\r\nSubject: Caf\u00e9\r\n\r\nHello".encode()
    )
    assert sender == "Caf\u00e9 <fictional@example.test>"
    assert message == "Subject: Caf\u00e9\n\nHello"
    message.encode("utf-8")


def test_html_email_browser_and_folder_email_imports_produce_identical_records(
    tmp_path, monkeypatch
):
    raw = html_email_email(
        '<p>Reply with a password</p><a href="https://credential.example.test">Verify</a>'
    )
    path = tmp_path / "fictional.eml"
    path.write_bytes(raw)
    monkeypatch.setattr(
        io_manager.default_io_manager.folder_picker,
        "get_eml_from_folder",
        lambda: io_manager.read_eml_details(path),
    )
    answers = iter(
        ["yes", "https://credential.example.test", "yes", "invoice.pdf", "yes", "yes", "otp"] * 2
    )
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    folder = io_manager.collect_input_from_folder()
    browser = io_manager.collect_input_from_upload({"filename": "fictional.eml", "content": raw})
    assert folder == browser
    assert browser["clicked"] and browser["downloaded"]
    assert browser["submitted_category"] == "otp"
    assert browser["file_name"] == "invoice.pdf"
    assert "fictional.eml" not in browser["message"]


@pytest.mark.parametrize(
    "filename, content",
    [
        ("invalid.eml", html_email_email("Invalid \xff").replace(b"\xc3\xbf", b"\xff")),
        ("empty.txt", b" "),
        ("invalid.txt", b"\xff"),
        ("unsupported.pdf", b"Fictional"),
    ],
)
def test_html_email_bad_uploads_fail_before_exposure_questions(monkeypatch, filename, content):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Bad import asked follow-up input"))
    with pytest.raises(ValueError):
        io_manager.collect_input_from_upload({"filename": filename, "content": content})


@pytest.mark.parametrize("filename", ["sample-1.eml", "sample-2.eml", "sample-3.eml"])
def test_html_email_tracked_real_email_samples_are_readable(filename):
    # Already tracked public samples; parsing only, never send their content to AI.
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / filename
    sender, message = io_manager.read_eml_details(path)
    assert sender and message and len(message) <= io_manager.MAX_MESSAGE_CHARS
    assert "[HTML body]" in message


@pytest.mark.parametrize("filename", ["sample-1.eml", "sample-2.eml", "sample-3.eml"])
def test_html_email_empty_plain_alternative_does_not_block_real_email_body(filename):
    from email import policy
    from email.parser import BytesParser
    from pathlib import Path

    raw = (Path(__file__).resolve().parents[2] / "tests" / "fixtures" / filename).read_bytes()
    expected = io_manager.read_eml_body(BytesParser(policy=policy.default).parsebytes(raw))
    # Keep the original real message intact inside a MIME wrapper containing
    # an empty alternative. No invented phishing text or live provider is used.
    wrapped = (
        b"Content-Type: multipart/alternative; boundary=real-empty-alternative\r\n\r\n"
        b"--real-empty-alternative\r\nContent-Type: text/plain\r\n\r\n \r\n"
        b"--real-empty-alternative\r\n" + raw + b"\r\n--real-empty-alternative--\r\n"
    )
    # MIME nesting can normalize CRLF to LF; message content must be unchanged.
    actual = io_manager.read_eml_bytes(wrapped)[1]
    assert actual.replace("\r\n", "\n") == expected.replace("\r\n", "\n")


def test_html_email_inline_image_under_mixed_does_not_block_readable_html():
    from email.message import EmailMessage

    email = EmailMessage()
    email.set_content("<p>A readable notice.</p>", subtype="html")
    email.add_attachment(
        b"IMAGE_BYTES", maintype="image", subtype="png", filename="logo.png", disposition="inline"
    )
    message = io_manager.read_eml_bytes(email.as_bytes())[1]
    assert "A readable notice." in message
    assert "IMAGE_BYTES" not in message


def test_html_email_empty_html_alternative_does_not_block_valid_plain_text():
    from email.message import EmailMessage

    email = EmailMessage()
    email.set_content("A valid plain-text message.")
    email.add_alternative("<html><body></body></html>", subtype="html")
    assert io_manager.read_eml_bytes(email.as_bytes())[1] == "A valid plain-text message."


def test_html_email_html_whitespace_does_not_count_as_final_message_text():
    raw = b"Content-Type: text/html; charset=utf-8\r\n\r\n<p>" + b" " * 51000 + b"Hello</p>"
    assert io_manager.read_eml_bytes(raw)[1] == "[HTML body]\nHello"
    assert html_to_text("<p>  Hello  </p><p>  world  </p>", 11) == "Hello\nworld"
    with pytest.raises(ValueError, match="length limit"):
        html_to_text("<p>Hello</p><p>world</p>", 10)


# ============================================================================
# Eml Validation
# ============================================================================
@pytest.mark.parametrize(
    "raw",
    [
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nHello \xff password",
        b"Content-Transfer-Encoding: base64\r\n\r\na",
        b"Subject: =?utf-8?b?/w==?=\r\n\r\nHello",
        b"Subject: =?unknown-charset?q?Hello?=\r\n\r\nHello",
        b"Subject: =?utf-8?b?SGVsbG8?=\r\n\r\nHello",
        b"Subject: =?utf-8?q?Hello=GG?=\r\n\r\nHello",
        b"Content-Transfer-Encoding: quoted-printable\r\n\r\nHello=GG",
        b"Content-Transfer-Encoding: unknown\r\n\r\nHello",
    ],
)
def test_eml_validation_malformed_import_is_rejected_by_parser(tmp_path, raw):
    bad = tmp_path / "bad.eml"
    bad.write_bytes(raw)
    with pytest.raises(ValueError):
        io_manager.read_eml_details(bad)


def eml_validation_multipart(*parts):
    return (
        b"Content-Type: multipart/mixed; boundary=x\r\n\r\n"
        + b"".join(b"--x\r\n" + part + b"\r\n" for part in parts)
        + b"--x--\r\n"
    )


def test_eml_validation_all_inline_plain_text_reaches_canonical_message(tmp_path):
    email = tmp_path / "mixed.eml"
    email.write_bytes(
        eml_validation_multipart(
            b"Content-Type: text/plain\r\n\r\nHello",
            b"Content-Type: text/plain\r\n\r\nReply with your password and OTP",
        )
    )
    assert io_manager.read_eml_details(email)[1] == ("Hello\n\nReply with your password and OTP")


@pytest.mark.parametrize(
    "raw",
    [
        eml_validation_multipart(
            b"Content-Type: text/plain\r\n\r\nHello",
            b"Content-Type: message/rfc822\r\n\r\nFrom: x@example.test\r\n\r\nOTP",
        ),
    ],
)
def test_eml_validation_unsupported_inline_body_is_rejected_not_partially_assessed(tmp_path, raw):
    email = tmp_path / "unsupported.eml"
    email.write_bytes(raw)
    with pytest.raises(ValueError, match="Unsupported"):
        io_manager.read_eml_details(email)


def test_eml_validation_explicit_attachment_is_not_an_inline_body(tmp_path):
    email = tmp_path / "attachment.eml"
    email.write_bytes(
        eml_validation_multipart(
            b"Content-Type: text/plain\r\n\r\nHello",
            b"Content-Type: application/octet-stream\r\n"
            b"Content-Disposition: attachment; filename=test.bin\r\n\r\nDATA",
        )
    )
    assert io_manager.read_eml_details(email)[1] == "Hello"


@pytest.mark.parametrize("content_type", ["text/plain", "text/html"])
def test_eml_validation_inline_filename_does_not_hide_body_content(tmp_path, content_type):
    email = tmp_path / "inline.eml"
    email.write_bytes(
        eml_validation_multipart(
            b"Content-Type: text/plain\r\n\r\nHello",
            (
                f"Content-Type: {content_type}\r\n"
                "Content-Disposition: inline; filename=message.txt\r\n\r\n"
                "Reply with your password"
            ).encode(),
        )
    )
    assert "Reply with your password" in io_manager.read_eml_details(email)[1]


@pytest.mark.parametrize(
    "raw, expected",
    [
        (b"Content-Type: text/plain; charset=utf-8\r\n\r\nHello \xef\xbf\xbd", "Hello \ufffd"),
        (b"Content-Type: text/plain; charset=iso-8859-1\r\n\r\nCaf\xe9", "Caf\u00e9"),
        (
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Content-Transfer-Encoding: base64\r\n\r\nQ2Fmw6k=",
            "Caf\u00e9",
        ),
        (
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Content-Transfer-Encoding: quoted-printable\r\n\r\nCaf=C3=A9",
            "Caf\u00e9",
        ),
        (b"Subject: =?utf-8?b?Q2Fmw6k=?=\r\n\r\nHello", "Subject: Caf\u00e9\n\nHello"),
    ],
)
def test_eml_validation_valid_decoding_preserves_characters(tmp_path, raw, expected):
    email = tmp_path / "valid.eml"
    email.write_bytes(raw)
    assert io_manager.read_eml_details(email)[1] == expected


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO requires POSIX")
@pytest.mark.parametrize("replace_after_check", [False, True])
def test_eml_validation_fifo_never_blocks_before_file_validation(tmp_path, replace_after_check):
    fifo = tmp_path / "pipe.eml"
    os.mkfifo(fifo)
    # Isolate the timeout so a regression cannot hang the test suite.
    script = (
        "from pathlib import Path\nfrom phishreport import io_manager\n"
        + ("Path.is_file = lambda self: True\n" if replace_after_check else "")
        + "try:\n    io_manager.read_eml_details("
        + repr(str(fifo))
        + ")\n"
        + "except ValueError:\n    pass\nelse:\n    raise AssertionError('FIFO accepted')\n"
    )
    env = dict(os.environ, PYTHONPATH=str(Path(io_manager.__file__).resolve().parents[1]))
    subprocess.run(
        [sys.executable, "-c", script], env=env, timeout=5, check=True, capture_output=True
    )
