"""Structural checks for the four manager modules."""

import ast
import importlib
from pathlib import Path

import pytest

REAL_EMAILS = Path(__file__).resolve().parents[1] / "fixtures"


# ============================================================================
# Manager Contract
# ============================================================================
manager_contract_ROOT = Path(__file__).resolve().parents[2]
manager_contract_APP = manager_contract_ROOT / "phishreport"
manager_contract_REQUIRED = ("io_manager", "ai_manager", "logic_manager", "data_manager")


@pytest.mark.parametrize("name", manager_contract_REQUIRED)
def test_manager_contract_required_manager_modules_are_importable(name):
    """Keep the four manager modules identifiable while permitting class-based APIs."""
    path = manager_contract_APP / (name + ".py")
    assert path.is_file(), "Required manager module is missing: " + name
    assert not (manager_contract_APP / name / "__init__.py").exists()
    module = importlib.import_module("phishreport." + name)
    assert Path(module.__file__).resolve() == path.resolve()


def test_manager_contract_raw_terminal_io_stays_in_console_adapter():
    """Keep direct terminal interaction inside the I/O layer's console adapter."""
    console_adapter = manager_contract_APP / "io" / "terminal.py"
    # The Telegram launcher reports startup errors on stderr and has no console UI.
    paths = [
        path
        for path in manager_contract_APP.rglob("*.py")
        if "bot" not in path.relative_to(manager_contract_APP).parts
    ] + list((manager_contract_ROOT / "tests").rglob("*.py"))
    paths += list(manager_contract_ROOT.glob("*.py"))
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if isinstance(function, ast.Name):
                if function.id in {"input", "print"}:
                    assert path == console_adapter, str(path)
