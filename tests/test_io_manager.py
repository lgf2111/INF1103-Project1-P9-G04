import io_manager
import pytest


def test_ask_yes_no_accepts_yes(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "YES")

    result = io_manager.ask_yes_no("Test: ")

    assert result is True


def test_ask_yes_no_accepts_no(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "No")

    result = io_manager.ask_yes_no("Test: ")

    assert result is False

def test_ask_yes_no_reprompts_invalid_input(monkeypatch):
    answers = iter(["hello", "yes"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.ask_yes_no("Test: ")

    assert result is True

def test_main_menu_accepts_valid_choice(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "2")

    result = io_manager.main_menu()

    assert result == "2"


def test_main_menu_reprompts_invalid_choice(monkeypatch):
    answers = iter(["5", "hello", "1"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.main_menu()

    assert result == "1"

def test_get_channel_accepts_case_insensitive_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "EMAIL")

    result = io_manager.get_channel()

    assert result == "email"


def test_get_channel_reprompts_invalid_input(monkeypatch):
    answers = iter(["discord", "Chat"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_channel()

    assert result == "chat"

def test_get_sender_returns_sender(monkeypatch):
    monkeypatch.setattr(
        "builtins.input",
        lambda _: "update@micr0soft.com"
    )

    result = io_manager.get_sender()

    assert result == "update@micr0soft.com"


def test_get_sender_allows_blank_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")

    result = io_manager.get_sender()

    assert result is None

def test_get_message_accepts_valid_message(monkeypatch):
    monkeypatch.setattr(
        "builtins.input",
        lambda _: "Download Update.exe immediately."
    )

    result = io_manager.get_message()

    assert result == "Download Update.exe immediately."


def test_get_message_reprompts_blank_input(monkeypatch):
    answers = iter(["", "   ", "Suspicious message"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_message()

    assert result == "Suspicious message"

def test_get_link_information_no_link(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "no")

    result = io_manager.get_link_information()

    assert result == (False, None)


def test_get_link_information_with_link(monkeypatch):
    answers = iter(["yes", "https://example.com"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_link_information()

    assert result == (True, "https://example.com")


def test_get_link_information_reprompts_blank_link(monkeypatch):
    answers = iter(["yes", "", "   ", "https://example.com"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_link_information()

    assert result == (True, "https://example.com")

def test_get_file_information_no_file(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "no")

    result = io_manager.get_file_information()

    assert result == (False, None)


def test_get_file_information_with_file(monkeypatch):
    answers = iter(["yes", "Update.exe"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_file_information()

    assert result == (True, "Update.exe")


def test_get_file_information_reprompts_blank_file(monkeypatch):
    answers = iter(["yes", "", "   ", "Update.exe"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_file_information()

    assert result == (True, "Update.exe")


def test_get_submitted_category_password(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "password")

    result = io_manager.get_submitted_category()

    assert result == "password"


def test_get_submitted_category_accepts_case_insensitive_otp(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "OTP")

    result = io_manager.get_submitted_category()

    assert result == "otp"


def test_get_submitted_category_no_returns_none(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "no")

    result = io_manager.get_submitted_category()

    assert result is None


def test_get_submitted_category_reprompts_invalid_input(monkeypatch):
    answers = iter(["hello", "credit card", "otp"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_submitted_category()

    assert result == "otp"

def test_collect_user_actions_with_link_and_file(monkeypatch):
    answers = iter(["no", "yes", "no"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.collect_user_actions(True, True)

    assert result == {
        "clicked": False,
        "downloaded": True,
        "submitted_category": None,
    }


def test_collect_user_actions_without_link(monkeypatch):
    answers = iter(["yes", "password"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.collect_user_actions(False, True)

    assert result == {
        "clicked": False,
        "downloaded": True,
        "submitted_category": "password",
    }


def test_collect_user_actions_without_link_or_file(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "no")

    result = io_manager.collect_user_actions(False, False)

    assert result == {
        "clicked": False,
        "downloaded": False,
        "submitted_category": None,
    }

def test_collect_input_returns_complete_record(monkeypatch):
    answers = iter([
    "Email",
    "1",
    "update@micr0soft.com",
    "Download Update.exe immediately.",
    "no",
    "yes",
    "Update.exe",
    "yes",
    "no",
])

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


def test_get_valid_choice_accepts_valid_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "  B  ")

    result = io_manager.get_valid_choice(
        "Choose: ",
        ("a", "b"),
        "Invalid: ",
    )

    assert result == "b"


def test_get_valid_choice_reprompts_invalid_input(monkeypatch):
    answers = iter(["wrong", "A"])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = io_manager.get_valid_choice(
        "Choose: ",
        ("a", "b"),
        "Invalid: ",
    )

    assert result == "a"

def test_read_eml_details_extracts_email_content(tmp_path):
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

def test_get_eml_input_reprompts_invalid_path(monkeypatch, tmp_path):
    email_file = tmp_path / "valid.eml"

    email_file.write_text(
        "From: test@example.com\n"
        "Subject: Test Email\n"
        'Content-Type: text/plain; charset="utf-8"\n'
        "\n"
        "This is a test message.\n",
        encoding="utf-8",
    )

    answers = iter([
        "",
        "invalid.txt",
        str(tmp_path / "missing.eml"),
        str(email_file),
    ])

    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    sender, message = io_manager.get_eml_input()

    assert sender == "test@example.com"
    assert message == "Subject: Test Email\n\nThis is a test message."

def test_get_eml_input_reprompts_empty_message(
    monkeypatch, tmp_path, capsys
):
    # Create an email with an empty message body
    empty_email = tmp_path / "empty.eml"

    empty_email.write_text(
        "From: sender@example.com\n"
        "Subject: Empty Message\n"
        'Content-Type: text/plain; charset="utf-8"\n'
        "\n",
        encoding="utf-8",
    )

    # Create a valid email
    valid_email = tmp_path / "valid.eml"

    valid_email.write_text(
        "From: test@example.com\n"
        "Subject: Test Email\n"
        'Content-Type: text/plain; charset="utf-8"\n'
        "\n"
        "This is a valid message.\n",
        encoding="utf-8",
    )

    # First attempt is invalid, second is valid
    answers = iter([
        str(empty_email),
        str(valid_email),
    ])

    monkeypatch.setattr(
        "builtins.input",
        lambda _: next(answers)
    )

    sender, message = io_manager.get_eml_input()

    # Verify the valid email was accepted
    assert sender == "test@example.com"

    assert message == (
        "Subject: Test Email\n\n"
        "This is a valid message."
    )

    # Verify the first email was rejected
    output = capsys.readouterr().out

    assert "Unable to read the email file." in output
    assert "Email loaded successfully." in output

def test_collect_input_eml_with_follow_up_questions(
    monkeypatch, tmp_path
):
    email_file = tmp_path / "suspicious.eml"

    email_file.write_text(
        "From: update@micr0soft.com\n"
        "Subject: Private Microsoft Beta\n"
        'Content-Type: text/plain; charset="utf-8"\n'
        "\n"
        "Download Update.exe immediately.\n",
        encoding="utf-8",
    )

    answers = iter([
        "email",                       # Channel
        "2",                           # Import .eml
        str(email_file),               # Email file path
        "yes",                         # Link included?
        "https://example.com/verify",  # Link
        "yes",                         # File included?
        "Update.exe",                  # File name
        "yes",                         # Clicked link?
        "no",                          # Downloaded file?
        "otp",                         # Password/OTP disclosed?
    ])

    prompts = []

    def fake_input(prompt):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)

    record = io_manager.collect_input()

    assert record == {
        "channel": "email",
        "sender": "update@micr0soft.com",
        "message": (
            "Subject: Private Microsoft Beta\n\n"
            "Download Update.exe immediately."
        ),
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

def test_get_eml_input_recovers_from_deeply_nested_mime(
    monkeypatch, tmp_path, capsys
):
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
            lines.extend([
                f'Content-Type: multipart/mixed; boundary="part{i + 1}"',
                "",
            ])
        else:
            lines.extend([
                'Content-Type: text/plain; charset="utf-8"',
                "",
                "This is a test message.",
            ])

    for i in reversed(range(depth)):
        lines.append(f"--part{i}--")

    nested_email.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    # Create a normal email that should work.
    valid_email = tmp_path / "valid.eml"

    valid_email.write_text(
        "From: test@example.com\n"
        "Subject: Valid Email\n"
        'Content-Type: text/plain; charset="utf-8"\n'
        "\n"
        "This is a valid message.\n",
        encoding="utf-8",
    )

    # User enters the nested email first, then a valid email.
    answers = iter([
        str(nested_email),
        str(valid_email),
    ])

    monkeypatch.setattr(
        "builtins.input",
        lambda _: next(answers),
    )

    sender, message = io_manager.get_eml_input()

    # The application should recover and accept the valid email.
    assert sender == "test@example.com"
    assert message == (
        "Subject: Valid Email\n\n"
        "This is a valid message."
    )

    output = capsys.readouterr().out

    assert "Unable to read the email file." in output
    assert "Email loaded successfully." in output

def test_read_eml_details_rejects_too_many_mime_parts(tmp_path):
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
        lines.extend([
            "--section",
            'Content-Type: text/plain; charset="utf-8"',
            "",
            f"Message part {number}",
            "",
        ])

    lines.append("--section--")

    email_file.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="too many MIME parts"):
        io_manager.read_eml_details(email_file)

def test_read_eml_details_rejects_excessive_mime_depth(tmp_path):
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
            lines.extend([
                f'Content-Type: multipart/mixed; boundary="part{i + 1}"',
                "",
            ])
        else:
            lines.extend([
                'Content-Type: text/plain; charset="utf-8"',
                "",
                "This is a test message.",
                "",
            ])

    # Close every MIME boundary.
    for i in reversed(range(depth)):
        lines.append(f"--part{i}--")

    email_file.write_bytes(
        ("\r\n".join(lines) + "\r\n").encode("utf-8")
)

    parsed_email = io_manager.BytesParser(
        policy=io_manager.policy.default
    ).parsebytes(email_file.read_bytes())


    with pytest.raises(ValueError, match="nesting is too deep"):
        io_manager.validate_mime_limits(parsed_email)

    with pytest.raises(ValueError, match="nesting is too deep"):
        io_manager.read_eml_details(email_file)

def test_read_eml_details_accepts_exactly_100_mime_parts(tmp_path):
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
        lines.extend([
            "--section",
            'Content-Type: text/plain; charset="utf-8"',
            "",
            f"Message part {number}",
            "",
        ])

    lines.append("--section--")

    # Write exact CRLF bytes to avoid Windows newline conversion.
    email_file.write_bytes(
        ("\r\n".join(lines) + "\r\n").encode("utf-8")
    )

    sender, message = io_manager.read_eml_details(email_file)

    assert sender == "sender@example.com"
    assert "Subject: MIME Boundary Test" in message
    assert "Message part 0" in message

def test_read_eml_details_accepts_exactly_32_mime_depth(tmp_path):
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
            lines.extend([
                f'Content-Type: multipart/mixed; boundary="part{i + 1}"',
                "",
            ])
        else:
            lines.extend([
                'Content-Type: text/plain; charset="utf-8"',
                "",
                "This email is within the allowed MIME depth.",
                "",
            ])

    # Close all MIME boundaries.
    for i in reversed(range(depth)):
        lines.append(f"--part{i}--")

    # Use write_bytes to preserve CRLF on Windows.
    email_file.write_bytes(
        ("\r\n".join(lines) + "\r\n").encode("utf-8")
    )

    sender, message = io_manager.read_eml_details(email_file)

    assert sender == "sender@example.com"
    assert message == (
        "Subject: MIME Depth Boundary Test\n\n"
        "This email is within the allowed MIME depth."
    )

def test_read_eml_details_accepts_exactly_2_mib(tmp_path):
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
    email_file.write_bytes(
        email_content + b" " * padding_size
    )

    # Confirm the file is exactly 2 MiB.
    assert email_file.stat().st_size == io_manager.MAX_EML_BYTES

    sender, message = io_manager.read_eml_details(email_file)

    assert sender == "sender@example.com"
    assert message == (
        "Subject: File Size Boundary Test\n\n"
        "This is a valid email."
    )

def test_read_eml_details_rejects_over_2_mib(tmp_path):
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

    email_file.write_bytes(
        email_content + b" " * padding_size
    )

    # Verify the file exceeds the limit by 1 byte.
    assert email_file.stat().st_size == target_size

    # The importer must reject the oversized email.
    with pytest.raises(ValueError, match="size limit"):
        io_manager.read_eml_details(email_file)

def test_read_eml_details_rejects_message_over_50000_chars(tmp_path):
    email_file = tmp_path / "long_message.eml"

    email_content = (
        b"From: sender@example.com\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: text/plain; charset="utf-8"\r\n'
        b"\r\n"
        + b"A" * 50001
    )

    email_file.write_bytes(email_content)

    # Confirm the raw file is within the 2 MiB limit.
    assert email_file.stat().st_size < io_manager.MAX_EML_BYTES

    # The decoded message contains 50,001 characters.
    with pytest.raises(ValueError, match="message length limit"):
        io_manager.read_eml_details(email_file)

def test_read_eml_details_accepts_exactly_50000_chars(tmp_path):
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

def test_read_eml_details_rejects_duplicate_from_header(tmp_path):
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

def test_read_eml_details_rejects_duplicate_subject_header(tmp_path):
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

def test_read_eml_details_rejects_missing_mime_boundary(tmp_path):
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

def test_read_eml_details_rejects_missing_header_body_separator(tmp_path):
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

def test_read_eml_details_rejects_invalid_base64(tmp_path):
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

def test_read_eml_details_rejects_invalid_base64_padding(tmp_path):
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
