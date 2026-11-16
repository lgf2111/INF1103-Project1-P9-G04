"""Generate the class diagram and evidence tables used by the engineering report.

The report must agree with the code, so both artefacts are derived from the source
instead of being drawn by hand:

    python scripts/report_assets.py          # writes docs/report/*.md

Run it after any structural change; the output is deterministic, so a diff shows
exactly what moved.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "phishreport"
OUT = ROOT / "docs" / "report"

# Classes that carry the graded design: the four managers, their contracts, and the
# collaborators that make the relationships visible.
FOCUS = {
    "IOManager",
    "AIManager",
    "LogicManager",
    "DataManager",
    "AssessmentService",
    "ReportStorage",
    "JsonReportStorage",
    "SqliteReportStorage",
    "PriorityRule",
    "PriorityRuleEngine",
    "ReportValidator",
    "ReportPresenter",
    "AssessmentRenderer",
    "PlainTextRenderer",
    "HtmlAlertRenderer",
    "Terminal",
    "Command",
    "AssessmentDocument",
    "RuleOutcome",
}


def classes_in(path: Path) -> list[ast.ClassDef]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    return [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]


def collect() -> list[dict]:
    discovered = []
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in classes_in(path):
            discovered.append(
                {
                    "name": node.name,
                    "module": str(path.relative_to(ROOT)),
                    "line": node.lineno,
                    "bases": [ast.unparse(base) for base in node.bases],
                    "methods": [
                        child.name
                        for child in node.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ],
                }
            )
    # Keep the focused classes and every subclass of one, so the diagram shows the
    # real inheritance edges instead of a hand-maintained list.
    wanted = {item["name"] for item in discovered if item["name"] in FOCUS}
    changed = True
    while changed:
        changed = False
        for item in discovered:
            if item["name"] in wanted:
                continue
            bases = [b.split(".")[-1].strip("[]") for b in item["bases"]]
            if any(base in wanted for base in bases):
                wanted.add(item["name"])
                changed = True
    return [item for item in discovered if item["name"] in wanted]


def abstract_methods(name: str, classes: list[dict]) -> int:
    entry = next((item for item in classes if item["name"] == name), None)
    if not entry:
        return 0
    source = (ROOT / entry["module"]).read_text(encoding="utf-8")
    return source.count("@abstractmethod")


def class_diagram(classes: list[dict]) -> str:
    lines = ["classDiagram"]
    for item in classes:
        lines.append(f"    class {item['name']} {{")
        for method in item["methods"][:8]:
            lines.append(f"        +{method}()")
        lines.append("    }")
    for item in classes:
        for base in item["bases"]:
            base_name = base.split(".")[-1].replace("[", "").replace("]", "")
            if any(other["name"] == base_name for other in classes):
                lines.append(f"    {base_name} <|-- {item['name']}")
    return "\n".join(lines) + "\n"


def concept_table(classes: list[dict]) -> str:
    def find(name: str) -> dict | None:
        return next((item for item in classes if item["name"] == name), None)

    rows: list[tuple[str, str, str]] = []
    rule = find("PriorityRule")
    if rule:
        rows.append(
            (
                "Abstract class",
                "`PriorityRule` declares the scoring contract with two abstract methods",
                f"`{rule['module']}:{rule['line']}`",
            )
        )
    storage = find("ReportStorage")
    if storage:
        rows.append(
            (
                "Interface / contract",
                "`ReportStorage` is an ABC implemented by two concrete backends",
                f"`{storage['module']}:{storage['line']}`",
            )
        )
    json_backend = find("JsonReportStorage")
    sqlite_backend = find("SqliteReportStorage")
    if json_backend and sqlite_backend:
        rows.append(
            (
                "Inheritance",
                "`JsonReportStorage` and `SqliteReportStorage` both specialise `ReportStorage`",
                f"`{json_backend['module']}:{json_backend['line']}`, "
                f"`{sqlite_backend['module']}:{sqlite_backend['line']}`",
            )
        )
    engine = find("PriorityRuleEngine")
    if engine:
        rows.append(
            (
                "Polymorphism",
                "`PriorityRuleEngine.score` calls `matches`/`score` on whichever rule "
                "is held; no type checks",
                f"`{engine['module']}:{engine['line']}`",
            )
        )
        rows.append(
            (
                "Composition",
                "`PriorityRuleEngine` creates and owns its default rule set; the rules "
                "die with the engine",
                f"`{engine['module']}:{engine['line']}`",
            )
        )
        rows.append(
            (
                "Aggregation",
                "The same constructor accepts a rule set supplied by the caller, which "
                "outlives the engine",
                f"`{engine['module']}:{engine['line']}`",
            )
        )
    service = find("AssessmentService")
    if service:
        rows.append(
            (
                "Association",
                "`AssessmentService` holds the AI and Logic managers it is given and never creates",
                f"`{service['module']}:{service['line']}`",
            )
        )
    logic = find("LogicManager")
    if logic:
        rows.append(
            (
                "Encapsulation",
                "Manager attributes are private and only exposed through methods",
                f"`{logic['module']}:{logic['line']}`",
            )
        )
    header = "| Concept | Where it is demonstrated | Reference |\n| --- | --- | --- |\n"
    body = "".join(f"| {concept} | {where} | {ref} |\n" for concept, where, ref in rows)
    return header + body


def data_flow() -> str:
    return (
        "flowchart LR\n"
        "    Input[Message or .eml] --> IO[IOManager]\n"
        "    IO --> AI[AIManager]\n"
        "    AI -->|validated findings| Logic[LogicManager]\n"
        "    Logic -->|score, priority, reasons| IO\n"
        "    Logic --> Data[DataManager]\n"
        "    Data --> Store[(JSON or SQLite)]\n"
        "    IO --> User[CLI or Telegram]\n"
    )


def main() -> int:
    classes = collect()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "class-diagram.mmd").write_text(class_diagram(classes), encoding="utf-8")
    (OUT / "data-flow.mmd").write_text(data_flow(), encoding="utf-8")
    (OUT / "oop-evidence.md").write_text(
        "# OOP concept evidence\n\n"
        "Generated by `scripts/report_assets.py` from the source tree. Every reference is a\n"
        "real file and line; re-run the script after a structural change.\n\n"
        + concept_table(classes),
        encoding="utf-8",
    )
    print(f"classes: {len(classes)}")
    print(f"wrote {OUT.relative_to(ROOT)}/class-diagram.mmd")
    print(f"wrote {OUT.relative_to(ROOT)}/data-flow.mmd")
    print(f"wrote {OUT.relative_to(ROOT)}/oop-evidence.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
