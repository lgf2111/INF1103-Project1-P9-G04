"""Structural checks for the four canonical manager packages."""

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
manager_contract_REQUIRED = (
    ("io", "IOManager"),
    ("ai", "AIManager"),
    ("logic", "LogicManager"),
    ("data", "DataManager"),
)


@pytest.mark.parametrize("package_name,class_name", manager_contract_REQUIRED)
def test_manager_contract_canonical_packages_export_manager_classes(package_name, class_name):
    """Public package exports must resolve to the canonical manager implementation."""
    package = importlib.import_module("phishreport." + package_name)
    module = importlib.import_module("phishreport." + package_name + ".manager")
    package_path = manager_contract_APP / package_name
    assert Path(package.__file__).resolve() == (package_path / "__init__.py").resolve()
    assert Path(module.__file__).resolve() == (package_path / "manager.py").resolve()
    assert getattr(package, class_name) is getattr(module, class_name)
    assert not (manager_contract_APP / (package_name + "_manager.py")).exists()


def test_manager_contract_no_static_imports_of_removed_shims():
    """Production and tests must use the canonical manager packages."""
    shim_names = {name + "_manager" for name, _ in manager_contract_REQUIRED}
    shim_modules = {"phishreport." + name for name in shim_names}
    paths = list(manager_contract_APP.rglob("*.py"))
    paths += list((manager_contract_ROOT / "tests").rglob("*.py"))
    paths += list(manager_contract_ROOT.glob("*.py"))
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if node.level:
                    package = ".".join(path.parent.relative_to(manager_contract_ROOT).parts)
                    module_name = importlib.util.resolve_name(
                        "." * node.level + module_name, package
                    )
                imports = [module_name]
                if module_name == "phishreport":
                    imports += ["phishreport." + alias.name for alias in node.names]
            else:
                continue
            assert not any(
                imported == shim or imported.startswith(shim + ".")
                for imported in imports
                for shim in shim_modules
            ), f"Removed manager shim imported at {path}:{node.lineno}"



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
