from types import SimpleNamespace

import pytest

from phishreport.ai import AIManager
from phishreport.cli import main
from phishreport.data import DataManager
from phishreport.io import IOManager
from phishreport.io.terminal import ConsoleTerminal
from phishreport.logic import LogicManager


def pytest_configure(config):
    """Register the short feature showcase separately from regression checks."""
    config.addinivalue_line("markers", "demo: concise automated feature showcase")


@pytest.fixture
def cli():
    """Create a CLI with fresh managers and expose its collaborators to tests."""
    console = IOManager(ConsoleTerminal())
    logic = LogicManager()
    storage = DataManager()
    app = main.PhishReportApp(
        io_manager=console, ai_manager=AIManager(), logic_manager=logic, data_manager=storage
    )
    return SimpleNamespace(app=app, io_manager=console, logic_manager=logic, data_manager=storage)
