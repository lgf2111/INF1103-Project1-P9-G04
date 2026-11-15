"""Architecture contracts for the canonical report and AI prompt modules."""

import ast
import importlib
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path

import pytest

from phishreport.model import Report

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "phishreport"


def test_schema_version_literal_is_owned_only_by_model():
    owners = {
        path.relative_to(APP).as_posix()
        for path in APP.rglob("*.py")
        if any(
            isinstance(node, ast.Constant) and node.value == "schema_version"
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        )
    }
    assert owners == {"model.py"}


def test_report_has_one_canonical_frozen_definition():
    definitions = [
        path.relative_to(APP).as_posix()
        for path in APP.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef) and node.name == "Report"
    ]
    assert definitions == ["model.py"]
    assert Report.__module__ == "phishreport.model"
    assert is_dataclass(Report)
    report = Report({"message": "Fictional message"})
    with pytest.raises(FrozenInstanceError):
        report.message = "changed"


def test_ai_prompt_module_is_singular_and_removed_plural_is_not_imported():
    prompt = importlib.import_module("phishreport.ai.prompt")
    assert Path(prompt.__file__).resolve() == (APP / "ai" / "prompt.py").resolve()
    assert not (APP / "ai" / "prompts.py").exists()
    paths = list(APP.rglob("*.py")) + list((ROOT / "tests").rglob("*.py"))
    paths += list(ROOT.glob("*.py"))
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    package = ".".join(path.parent.relative_to(ROOT).parts)
                    module = importlib.util.resolve_name("." * node.level + module, package)
                imports = [module, *(module + "." + alias.name for alias in node.names)]
            elif isinstance(node, ast.Call) and node.args and (
                isinstance(node.func, ast.Name) and node.func.id == "__import__"
                or isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
            ):
                target = node.args[0]
                imports = [target.value] if (
                    isinstance(target, ast.Constant) and isinstance(target.value, str)
                ) else []
            else:
                continue
            assert not any(
                name == "phishreport.ai.prompts" or name.startswith("phishreport.ai.prompts.")
                for name in imports
            ), f"Removed prompt module imported at {path}:{node.lineno}"
