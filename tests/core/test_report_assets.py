"""The report artefacts must exist and cite real code."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "docs" / "report"
REFERENCE = re.compile(r"`(phishreport/[^`:]+\.py):(\d+)`")

# docs/report/ holds locally generated submission artefacts and is git-ignored,
# so it is absent from a clean checkout such as CI. Run
# `python scripts/report_assets.py` to check the artefacts locally.
pytestmark = pytest.mark.skipif(
    not REPORT_DIR.is_dir(), reason="docs/report is not present in a clean checkout"
)


def text(name: str) -> str:
    path = REPORT_DIR / name
    if not path.exists():
        pytest.fail(f"{path.relative_to(ROOT)} is missing; run scripts/report_assets.py")
    return path.read_text(encoding="utf-8")


def test_the_generated_artefacts_exist():
    for name in ("class-diagram.mmd", "data-flow.mmd", "oop-evidence.md"):
        assert text(name).strip(), f"{name} is empty"


def test_the_class_diagram_names_the_four_managers():
    diagram = text("class-diagram.mmd")

    for manager in ("IOManager", "AIManager", "LogicManager", "DataManager"):
        assert f"class {manager} " in diagram, f"{manager} is missing from the diagram"


def test_the_diagram_records_both_contract_relationships():
    diagram = text("class-diagram.mmd")

    assert "ReportStorage <|-- JsonReportStorage" in diagram
    assert "ReportStorage <|-- SqliteReportStorage" in diagram
    assert "PriorityRule <|--" in diagram


def test_every_evidence_reference_points_at_a_real_line():
    problems = []
    for path, line in REFERENCE.findall(text("oop-evidence.md")):
        source = ROOT / path
        if not source.exists():
            problems.append(f"{path} does not exist")
            continue
        total = len(source.read_text(encoding="utf-8").splitlines())
        if not 1 <= int(line) <= total:
            problems.append(f"{path}:{line} is outside the file ({total} lines)")

    assert problems == [], "\n".join(problems)


def test_the_report_covers_each_required_section():
    report = text("engineering-report.md").lower()

    for section in (
        "class diagram",
        "data flow",
        "mandatory oop concepts",
        "solid justification",
        "new feature",
        "advanced feature",
        "exception handling",
    ):
        assert section in report, f"the report never mentions {section}"
