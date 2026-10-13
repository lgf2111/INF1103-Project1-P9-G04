"""Protect the mandatory Phase 1 source layout and procedural boundaries."""

import ast
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
REQUIRED = {
    "io_manager": {"collect_input", "display_record", "display_list", "display_result"},
    "ai_manager": {"build_prompt", "call_api", "parse_response", "validate_response"},
    "logic_manager": {"evaluate", "score", "route"},
    "data_manager": {"save", "load", "query"},
}


@pytest.mark.parametrize("name", REQUIRED)
def test_required_manager_functions_live_in_named_module(name):
    """A re-export shim or same-named package does not satisfy the course response."""
    path = APP / (name + ".py")
    assert path.is_file(), "Required manager module is missing: " + name
    assert not (APP / name / "__init__.py").exists()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert REQUIRED[name] <= functions
    module = importlib.import_module(name)
    assert Path(module.__file__).resolve() == path.resolve()
    for function in REQUIRED[name]:
        assert callable(getattr(module, function))


def test_team_python_is_procedural_and_terminal_io_stays_in_io_manager():
    """Scan shipped source/tests, including dynamic class construction and I/O."""
    paths = list(APP.rglob("*.py")) + list((ROOT / "tests").rglob("*.py"))
    paths += list(ROOT.glob("*.py"))
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            assert not isinstance(node, ast.ClassDef), str(path)
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if isinstance(function, ast.Name):
                assert not (function.id == "type" and len(node.args) == 3), str(path)
                if function.id in {"input", "print"}:
                    assert path == APP / "io_manager.py", str(path)
