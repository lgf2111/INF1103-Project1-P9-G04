import io_manager


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


