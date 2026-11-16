"""Keep docs/exception-matrix.md honest: every citation must resolve."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "exception-matrix.md"
CITATION = re.compile(r"`(tests/[^`]+\.py)::([A-Za-z_][A-Za-z0-9_]*)`")


def matrix_text() -> str:
    if not DOC.exists():
        pytest.fail(f"{DOC.relative_to(ROOT)} is missing")
    return DOC.read_text(encoding="utf-8")


def rows() -> list[str]:
    """Return the table rows that describe a failure (one per matrix entry)."""
    return [line for line in matrix_text().splitlines() if line.startswith("| ") and "::" in line]


def test_the_matrix_exists_and_covers_each_required_failure_class():
    text = matrix_text().lower()

    required = [
        "api connection failure",
        "malformed api response",
        "corrupt data file",
        "missing data file",
        "invalid user input",
        "write failure",
    ]
    missing = [name for name in required if name not in text]
    assert missing == [], f"matrix does not cover: {missing}"


def test_every_row_cites_a_test_that_exists():
    problems = []
    for row in rows():
        for path, name in CITATION.findall(row):
            source = ROOT / path
            if not source.exists():
                problems.append(f"{path} does not exist")
                continue
            body = source.read_text(encoding="utf-8")
            if not re.search(rf"^def {re.escape(name)}\(", body, re.MULTILINE):
                problems.append(f"{path} has no test named {name}")

    assert problems == [], "\n".join(problems)


def test_each_typed_failure_is_documented():
    errors_source = (ROOT / "phishreport" / "errors.py").read_text(encoding="utf-8")
    pattern = r"^class ([A-Z][A-Za-z0-9_]*)\(AssessmentError\):"
    documented = set(re.findall(pattern, errors_source, re.MULTILINE))
    assert documented, "no AssessmentError subclasses found"
    text = matrix_text()
    missing = sorted(name for name in documented if name not in text)
    assert missing == [], f"matrix never names: {missing}"


def test_the_matrix_is_not_a_placeholder():
    assert len(rows()) >= 12
    assert "propagate" in matrix_text().lower()
