"""The combined launcher is the documented entry point; the old name is gone."""

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_combined_module_imports_and_both_does_not():
    assert importlib.import_module("phishreport.combined").main
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("phishreport.both")


def test_dockerfile_all_target_runs_the_combined_module():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    all_target = dockerfile.split("FROM base AS all", 1)[1].split("FROM base AS", 1)[0]

    assert 'CMD ["python", "-m", "phishreport.combined"]' in all_target


def test_readme_documents_the_combined_entry_point_and_never_the_old_one():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "python -m phishreport.combined" in readme
    assert not re.search(r"phishreport[./]both", readme)
    for path in ("run.sh", "Dockerfile"):
        assert not re.search(r"phishreport[./]both", (ROOT / path).read_text(encoding="utf-8"))
