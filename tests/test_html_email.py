"""Fictional MIME/HTML fixtures: preserve source evidence without executing it."""
import io_manager
import pytest
from misc.email_html import html_to_text


def _email(html, headers=b""):
    return (b"From: fictional@example.test\r\nSubject: Fictional request\r\n"
            + headers + b"Content-Type: text/html; charset=utf-8\r\n\r\n" + html.encode())


def test_html_only_keeps_visible_text_and_different_link_target():
    raw = _email('<p>Account notice</p><a href="https://credential.example.test/login?a=1&amp;b=2">'
                 'https://legitimate.example.test</a><p>Reply with a password</p>')
    sender, message = io_manager.read_eml_bytes(raw)
    assert sender == "fictional@example.test"
    assert "Subject: Fictional request" in message
    assert "https://credential.example.test/login?a=1&b=2" in message
    assert "https://legitimate.example.test" in message
    assert "Reply with a password" in message
    assert "<a " not in message and "Content-Type:" not in message


def test_alternatives_retain_conflicting_html_instead_of_selecting_benign_plain():
    raw = (b'Content-Type: multipart/alternative; boundary=x\r\n\r\n'
           b'--x\r\nContent-Type: text/plain\r\n\r\nA routine notice.\r\n'
           b'--x\r\nContent-Type: text/html\r\n\r\n'
           b'<a href="https://credential.example.test">Enter password and OTP</a>\r\n--x--\r\n')
    message = io_manager.read_eml_bytes(raw)[1]
    assert "A routine notice." in message
    assert "Enter password and OTP" in message
    assert "https://credential.example.test" in message


def test_related_images_do_not_block_html_or_get_decoded_as_text():
    raw = (b'Content-Type: multipart/related; boundary=x\r\n\r\n'
           b'--x\r\nContent-Type: text/html\r\n\r\n<p>Fictional notice</p>'
           b'<img src="cid:logo" alt="Account alert">\r\n'
           b'--x\r\nContent-Type: image/png\r\nContent-ID: <logo>\r\n\r\n\xff\x00\r\n'
           b'--x--\r\n')
    message = io_manager.read_eml_bytes(raw)[1]
    assert "Account alert" in message and "Fictional notice" in message
    assert "cid:logo" not in message


def test_html_resources_and_scripts_are_never_requested_or_executed(monkeypatch):
    import urllib.request

    def no_network(*args, **kwargs):
        pytest.fail("HTML conversion must never fetch a resource")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    text = html_to_text('<head><style>BAD_STYLE</style></head><script>BAD_SCRIPT</script>'
                        '<p>Readable &amp; safe</p><img src="https://tracking.example.test/pixel" '
                        'alt="Alert"><form action="https://credential.example.test">Password</form>',
                        50000)
    assert "BAD_STYLE" not in text and "BAD_SCRIPT" not in text
    assert "Readable & safe" in text and "Password" in text
    assert "https://tracking.example.test/pixel" in text
    assert "https://credential.example.test" in text


@pytest.mark.parametrize("html", ["<script>only script</script>", "<p> </p>", "<img src='cid:x'>"])
def test_html_without_usable_content_is_rejected(html):
    with pytest.raises(ValueError, match="no usable"):
        io_manager.read_eml_bytes(_email(html))


def test_html_output_limits_include_attribute_expansion():
    with pytest.raises(ValueError, match="length limit"):
        html_to_text('<a href="' + 'a' * 50000 + '">x</a>', 50000)


def test_forged_sender_is_preserved_as_untrusted_text_not_repaired():
    sender, message = io_manager.read_eml_bytes(b"From: a@@example.test\r\n\r\nHello")
    assert sender == "a@@example.test"
    assert message == "Hello"


def test_raw_utf8_headers_are_decoded_without_surrogates():
    sender, message = io_manager.read_eml_bytes(
        "From: Caf\u00e9 <fictional@example.test>\r\nSubject: Caf\u00e9\r\n\r\nHello".encode()
    )
    assert sender == "Caf\u00e9 <fictional@example.test>"
    assert message == "Subject: Caf\u00e9\n\nHello"
    message.encode("utf-8")


def test_browser_and_folder_email_imports_produce_identical_records(tmp_path, monkeypatch):
    raw = _email('<p>Reply with a password</p><a href="https://credential.example.test">Verify</a>')
    path = tmp_path / "fictional.eml"
    path.write_bytes(raw)
    monkeypatch.setattr(io_manager, "get_eml_from_folder",
                        lambda: io_manager.read_eml_details(path))
    answers = iter(["yes", "https://credential.example.test", "yes", "invoice.pdf",
                    "yes", "yes", "otp"] * 2)
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    folder = io_manager.collect_input_from_folder()
    browser = io_manager.collect_input_from_upload({"filename":"fictional.eml", "content":raw})
    assert folder == browser
    assert browser["clicked"] and browser["downloaded"]
    assert browser["submitted_category"] == "otp"
    assert browser["file_name"] == "invoice.pdf"
    assert "fictional.eml" not in browser["message"]


@pytest.mark.parametrize("filename, content", [
    ("invalid.eml", _email("Invalid \xff").replace(b'\xc3\xbf', b'\xff')),
    ("empty.txt", b" "), ("invalid.txt", b"\xff"), ("unsupported.pdf", b"Fictional"),
])
def test_bad_uploads_fail_before_exposure_questions(monkeypatch, filename, content):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("Bad import asked follow-up input"))
    with pytest.raises(ValueError):
        io_manager.collect_input_from_upload({"filename":filename, "content":content})


@pytest.mark.parametrize("filename", ["sample-1.eml", "sample-2.eml", "sample-3.eml"])
def test_tracked_real_email_samples_are_readable(filename):
    # Already tracked public samples; parsing only, never send their content to AI.
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "emails" / filename
    sender, message = io_manager.read_eml_details(path)
    assert sender and message and len(message) <= io_manager.MAX_MESSAGE_CHARS
    assert "[HTML body]" in message


@pytest.mark.parametrize("filename", ["sample-1.eml", "sample-2.eml", "sample-3.eml"])
def test_empty_plain_alternative_does_not_block_real_email_body(filename):
    from email import policy
    from email.parser import BytesParser
    from pathlib import Path

    raw = (Path(__file__).resolve().parent.parent / "emails" / filename).read_bytes()
    expected = io_manager.read_eml_body(BytesParser(policy=policy.default).parsebytes(raw))
    # Keep the original real message intact inside a MIME wrapper containing
    # an empty alternative. No invented phishing text or live provider is used.
    wrapped = (b'Content-Type: multipart/alternative; boundary=real-empty-alternative\r\n\r\n'
               b'--real-empty-alternative\r\nContent-Type: text/plain\r\n\r\n \r\n'
               b'--real-empty-alternative\r\n' + raw
               + b'\r\n--real-empty-alternative--\r\n')
    # MIME nesting can normalize CRLF to LF; message content must be unchanged.
    actual = io_manager.read_eml_bytes(wrapped)[1]
    assert actual.replace("\r\n", "\n") == expected.replace("\r\n", "\n")


def test_inline_image_under_mixed_does_not_block_readable_html():
    from email.message import EmailMessage

    email = EmailMessage()
    email.set_content("<p>A readable notice.</p>", subtype="html")
    email.add_attachment(b"IMAGE_BYTES", maintype="image", subtype="png",
                         filename="logo.png", disposition="inline")
    message = io_manager.read_eml_bytes(email.as_bytes())[1]
    assert "A readable notice." in message
    assert "IMAGE_BYTES" not in message


def test_empty_html_alternative_does_not_block_valid_plain_text():
    from email.message import EmailMessage

    email = EmailMessage()
    email.set_content("A valid plain-text message.")
    email.add_alternative("<html><body></body></html>", subtype="html")
    assert io_manager.read_eml_bytes(email.as_bytes())[1] == "A valid plain-text message."


def test_html_whitespace_does_not_count_as_final_message_text():
    raw = b"Content-Type: text/html; charset=utf-8\r\n\r\n<p>" + b" " * 51000 + b"Hello</p>"
    assert io_manager.read_eml_bytes(raw)[1] == "[HTML body]\nHello"
    assert html_to_text("<p>  Hello  </p><p>  world  </p>", 11) == "Hello\nworld"
    with pytest.raises(ValueError, match="length limit"):
        html_to_text("<p>Hello</p><p>world</p>", 10)
