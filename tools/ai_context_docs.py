from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / ".ai" / "test-matrix.yaml"
MATRIX_DOC_PATH = ROOT / ".ai" / "TEST_MATRIX.md"
FAILURES_PATH = ROOT / ".ai" / "known-failures.yaml"
FAILURES_DOC_PATH = ROOT / ".ai" / "KNOWN_FAILURES.md"
START = "<!-- BEGIN GENERATED SUMMARY -->"
END = "<!-- END GENERATED SUMMARY -->"


def _load(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a YAML mapping")
    return loaded


def _items(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a string list")
    return value


def render_matrix_summary(document: dict[str, Any]) -> str:
    classes = document.get("classes")
    flags = document.get("risk_flags")
    if not isinstance(classes, dict) or not isinstance(flags, dict):
        raise ValueError("Test matrix must define classes and risk_flags")
    lines = [
        "| Task class | Required check IDs |",
        "| --- | --- |",
    ]
    for name, raw_rule in classes.items():
        if not isinstance(raw_rule, dict):
            raise ValueError(f"classes.{name} must be a mapping")
        required = ", ".join(f"`{item}`" for item in _items(raw_rule.get("required", []), label=str(name)))
        lines.append(f"| `{name}` | {required} |")
    lines.extend(["", "| Risk flag | Added automated checks | Manual evidence |", "| --- | --- | --- |"])
    for name, raw_rule in flags.items():
        if not isinstance(raw_rule, dict):
            raise ValueError(f"risk_flags.{name} must be a mapping")
        added = ", ".join(f"`{item}`" for item in _items(raw_rule.get("add", []), label=str(name))) or "none"
        manual = ", ".join(f"`{item}`" for item in _items(raw_rule.get("manual", []), label=str(name))) or "none"
        lines.append(f"| `{name}` | {added} | {manual} |")
    return "\n".join(lines)


def render_failures_summary(document: dict[str, Any]) -> str:
    failures = document.get("failures")
    if not isinstance(failures, list):
        raise ValueError("Known failures must define a failures list")
    lines = ["| ID | Category | Symptom | Verification |", "| --- | --- | --- | --- |"]
    seen: set[str] = set()
    for entry in failures:
        if not isinstance(entry, dict):
            raise ValueError("Each known failure must be a mapping")
        failure_id = entry.get("failure_id")
        if not isinstance(failure_id, str) or failure_id in seen:
            raise ValueError(f"Invalid or duplicate known failure ID: {failure_id}")
        seen.add(failure_id)
        cells = [failure_id, entry.get("category"), entry.get("symptom"), entry.get("verification")]
        if not all(isinstance(cell, str) and "|" not in cell and "\n" not in cell for cell in cells):
            raise ValueError(f"Known failure {failure_id} has an invalid summary field")
        lines.append(f"| `{failure_id}` | {cells[1]} | {cells[2]} | `{cells[3]}` |")
    return "\n".join(lines)


def _replace_generated(document: str, generated: str) -> str:
    if document.count(START) != 1 or document.count(END) != 1:
        raise ValueError("Document must contain exactly one generated-summary marker pair")
    before, remainder = document.split(START, 1)
    _, after = remainder.split(END, 1)
    return f"{before}{START}\n{generated}\n{END}{after}"


def expected_documents(root: Path = ROOT) -> dict[Path, str]:
    matrix_doc = root / MATRIX_DOC_PATH.relative_to(ROOT)
    failures_doc = root / FAILURES_DOC_PATH.relative_to(ROOT)
    matrix = _load(root / MATRIX_PATH.relative_to(ROOT))
    failures = _load(root / FAILURES_PATH.relative_to(ROOT))
    return {
        matrix_doc: _replace_generated(matrix_doc.read_text(encoding="utf-8"), render_matrix_summary(matrix)),
        failures_doc: _replace_generated(failures_doc.read_text(encoding="utf-8"), render_failures_summary(failures)),
    }


def sync_documents(*, write: bool, root: Path = ROOT) -> list[str]:
    drift: list[str] = []
    for path, expected in expected_documents(root).items():
        current = path.read_text(encoding="utf-8")
        if current == expected:
            continue
        drift.append(str(path.relative_to(root)).replace("\\", "/"))
        if write:
            path.write_text(expected, encoding="utf-8", newline="\n")
    return drift


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check or update generated AI context summaries.")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        drift = sync_documents(write=args.write)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise SystemExit(f"ai-context-docs: {exc}") from exc
    if drift and not args.write:
        raise SystemExit(f"Generated AI context summaries are stale: {', '.join(drift)}")
    if args.write:
        print(f"updated: {', '.join(drift) if drift else 'none'}")
    else:
        print("AI context summaries are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
