"""Command foundation contracts, independent of CLI and Telegram services."""

import ast
from pathlib import Path

import pytest

from phishreport.io.commands import Command, CommandReply, CommandRequest, CommandRouter


class RecordingCommand(Command):
    name = "check"
    help_text = "Assess a pasted message."

    def __init__(self):
        self.requests = []
        self.reply = CommandReply("Assessed.", "assessment")

    def execute(self, request: CommandRequest) -> CommandReply:
        self.requests.append(request)
        return self.reply


@pytest.mark.parametrize("text,known,arguments", [
    ("/check hello", True, "hello"),
    ("/check", True, ""),
    ("  /check   hello  world  ", True, "hello  world  "),
    ("/check\nfirst line\n\nsecond line", True, "first line\n\nsecond line"),
    ("/check\tmessage", True, "message"),
    ("/unknown message", False, None),
    ("/checker message", False, None),
    ("/CHECK message", False, None),
    ("/", False, None),
    ("", False, None),
    ("   \n\t", False, None),
    ("message /check hello", False, None),
    ("Please send your OTP.\nhttps://example.test", False, None),
])
def test_router_table(text, known, arguments):
    command = RecordingCommand()
    router = CommandRouter([command])
    session = {"user": "fictional"}
    request = CommandRequest(text, "chat", session)

    assert router.resolve(text) is (command if known else None)
    assert command.requests == []  # Resolution alone never executes anything.
    reply = router.route(request)

    assert request.text == text
    assert request.session is session
    assert session == {"user": "fictional"}
    if known:
        assert reply is command.reply
        received, = command.requests
        assert received.text == arguments
        assert received.channel == "chat"
        assert received.session is session
    else:
        assert reply is None
        assert command.requests == []


def test_command_requires_metadata_and_execution():
    with pytest.raises(TypeError):
        Command()

    class MissingExecution(Command):
        name = "incomplete"
        help_text = "Incomplete."

    with pytest.raises(TypeError):
        MissingExecution()


def test_requests_have_independent_default_sessions():
    first = CommandRequest("one", "cli")
    second = CommandRequest("two", "chat")
    first.session["count"] = 1
    assert second.session == {}


def test_registration_extends_router_without_dispatch_changes():
    class OtherCommand(RecordingCommand):
        name = "other"

    router = CommandRouter([RecordingCommand()])
    other = OtherCommand()
    router.register(other)
    assert router.route(CommandRequest("/other content", "cli")) is other.reply
    assert other.requests[0].text == "content"


@pytest.mark.parametrize("name", ["", "/check", "CHECK", "two words", "check!", 1])
def test_invalid_registration_name(name):
    command = RecordingCommand()
    command.name = name
    with pytest.raises(ValueError):
        CommandRouter([command])


def test_duplicate_registration_does_not_replace_original():
    original = RecordingCommand()
    router = CommandRouter([original])
    with pytest.raises(ValueError, match="already registered"):
        router.register(RecordingCommand())
    assert router.resolve("/check") is original


def test_registration_requires_command():
    with pytest.raises(TypeError):
        CommandRouter([object()])


def test_service_failure_propagates_without_a_reply():
    class FailingCommand(RecordingCommand):
        def execute(self, request):
            raise RuntimeError("Service unavailable")

    with pytest.raises(RuntimeError, match="Service unavailable"):
        CommandRouter([FailingCommand()]).route(CommandRequest("/check text", "cli"))


def test_io_has_no_telegram_or_bot_imports():
    io_path = Path(__file__).resolve().parents[2] / "phishreport" / "io"
    for source in io_path.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package = ["phishreport", "io", *source.relative_to(io_path).parts[:-1]]
                    base = package[:len(package) - node.level + 1]
                    module = ".".join([*base, node.module or ""]).rstrip(".")
                else:
                    module = node.module or ""
                modules = [module, *(f"{module}.{alias.name}" for alias in node.names)]
            else:
                continue
            assert not any(
                module == root or module.startswith(root + ".")
                for module in modules for root in ("telegram", "phishreport.bot")
            ), f"Transport dependency in {source}: {modules}"
