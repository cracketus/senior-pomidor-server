from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / ".ai" / "context-manifest.yaml"
MATRIX_PATH = ROOT / ".ai" / "test-matrix.yaml"
FAILURES_PATH = ROOT / ".ai" / "known-failures.yaml"
ROLES = ("planner", "coder", "reviewer")
TASK_CLASSES = (
    "pure_software",
    "schema_data_contract",
    "infrastructure_deployment",
    "edge_hardware_integration",
    "control_guardrails_executor",
    "llm_vision",
    "documentation_only",
)
RISK_FLAGS = (
    "physical_action",
    "data_loss_migration",
    "security_secrets",
    "edge_server_compatibility",
    "production_availability",
    "public_contract",
)


@dataclass(frozen=True)
class ContextFile:
    path: str
    sha256: str
    characters: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ContextSelection:
    schema: str
    role: str
    changed_files: tuple[str, ...]
    task_classes: tuple[str, ...]
    risk_flags: tuple[str, ...]
    full_context: bool
    selection_reasons: tuple[str, ...]
    escalation_reasons: tuple[str, ...]
    files: tuple[ContextFile, ...]
    known_failures: tuple[dict[str, Any], ...]
    checks: tuple[dict[str, Any], ...]
    manual_checks: tuple[str, ...]
    source_hashes: dict[str, str]
    file_count: int
    context_characters: int


def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a YAML mapping")
    return loaded


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _repo_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"Context path escapes repository root: {relative}")
    if not path.is_file():
        raise ValueError(f"Required context file is missing: {relative}")
    return path


def normalize_changed_file(value: str, *, root: Path = ROOT) -> str:
    candidate = Path(value)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"Changed file escapes repository root: {value}")
        candidate = resolved.relative_to(root)
    normalized = str(PurePosixPath(str(candidate).replace("\\", "/")))
    if normalized in {"", "."} or normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"Invalid changed file: {value}")
    return normalized


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern) or (pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]))


def _string_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must be a string list")
    return value


def _failure_map(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    failures = document.get("failures")
    if not isinstance(failures, list):
        raise ValueError("known-failures.yaml.failures must be a list")
    result: dict[str, dict[str, Any]] = {}
    for entry in failures:
        if not isinstance(entry, dict) or not isinstance(entry.get("failure_id"), str):
            raise ValueError("Each known failure must have a string failure_id")
        failure_id = entry["failure_id"]
        if failure_id in result:
            raise ValueError(f"Duplicate known failure: {failure_id}")
        result[failure_id] = entry
    return result


def _matrix_checks(
    matrix: dict[str, Any], task_classes: set[str], risk_flags: set[str], changed_files: tuple[str, ...]
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    definitions = matrix.get("checks")
    class_rules = matrix.get("classes")
    flag_rules = matrix.get("risk_flags")
    if not isinstance(definitions, dict) or not isinstance(class_rules, dict) or not isinstance(flag_rules, dict):
        raise ValueError("test-matrix.yaml must define checks, classes, and risk_flags mappings")

    selected: set[str] = set()
    manual: set[str] = set()
    for task_class in task_classes:
        rule = class_rules.get(task_class)
        if not isinstance(rule, dict):
            raise ValueError(f"Unknown task class in manifest: {task_class}")
        selected.update(_string_list(rule.get("required", []), label=f"classes.{task_class}.required"))
    for risk_flag in risk_flags:
        rule = flag_rules.get(risk_flag)
        if not isinstance(rule, dict):
            raise ValueError(f"Unknown risk flag in manifest: {risk_flag}")
        selected.update(_string_list(rule.get("add", []), label=f"risk_flags.{risk_flag}.add"))
        manual.update(_string_list(rule.get("manual", []), label=f"risk_flags.{risk_flag}.manual"))

    if any(changed_path.startswith((".ai/agents/feature-planner", ".ai/workflows/")) for changed_path in changed_files):
        selected.add("feature_planner_evaluation")
    if any(
        changed_path.startswith((".ai/agents/reviewer", ".ai/evaluations/reviewer/")) for changed_path in changed_files
    ):
        selected.add("reviewer_evaluation")
    shared_agent_contracts = {
        "AGENTS.md",
        ".ai/CORE_INVARIANTS.md",
        ".ai/context-manifest.yaml",
        ".ai/known-failures.yaml",
        ".ai/model-routing.yaml",
        ".ai/test-matrix.yaml",
        ".ai/tool-routing.yaml",
    }
    if shared_agent_contracts.intersection(changed_files) or any(
        changed_path.startswith(".ai/templates/") for changed_path in changed_files
    ):
        selected.update(("feature_planner_evaluation", "reviewer_evaluation"))

    checks: list[dict[str, Any]] = []
    for check_id in sorted(selected):
        definition = definitions.get(check_id)
        if not isinstance(definition, dict):
            raise ValueError(f"Undefined check selected by matrix: {check_id}")
        checks.append({"id": check_id, **definition})
    return tuple(checks), tuple(sorted(manual))


def select_context(
    role: str,
    changed_files: list[str] | tuple[str, ...],
    *,
    full: bool = False,
    task_class_overrides: list[str] | tuple[str, ...] = (),
    risk_flag_overrides: list[str] | tuple[str, ...] = (),
    root: Path = ROOT,
) -> ContextSelection:
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role}")
    root = root.resolve()
    normalized = tuple(dict.fromkeys(normalize_changed_file(path, root=root) for path in changed_files))
    if not normalized:
        raise ValueError("At least one changed file is required")

    manifest_path = root / ".ai" / "context-manifest.yaml"
    matrix_path = root / ".ai" / "test-matrix.yaml"
    failures_path = root / ".ai" / "known-failures.yaml"
    manifest = _load_yaml(manifest_path)
    matrix = _load_yaml(matrix_path)
    failure_document = _load_yaml(failures_path)
    failures = _failure_map(failure_document)

    role_files = manifest.get("role_files")
    rules = manifest.get("path_rules")
    unknown_rule = manifest.get("unknown_path")
    if not isinstance(role_files, dict) or not isinstance(role_files.get(role), str):
        raise ValueError(f"Manifest has no role file for {role}")
    if not isinstance(rules, list) or not isinstance(unknown_rule, dict):
        raise ValueError("Manifest must define path_rules and unknown_path")

    task_classes: set[str] = set()
    risk_flags: set[str] = set()
    failure_ids: set[str] = set()
    includes: dict[str, set[str]] = {}
    selection_reasons: list[str] = []
    unknown_paths: list[str] = []

    invalid_classes = set(task_class_overrides) - set(TASK_CLASSES)
    invalid_flags = set(risk_flag_overrides) - set(RISK_FLAGS)
    if invalid_classes:
        raise ValueError(f"Unknown explicit task class: {sorted(invalid_classes)[0]}")
    if invalid_flags:
        raise ValueError(f"Unknown explicit risk flag: {sorted(invalid_flags)[0]}")
    task_classes.update(task_class_overrides)
    risk_flags.update(risk_flag_overrides)
    selection_reasons.extend(f"explicit_task_class:{value}" for value in task_class_overrides)
    selection_reasons.extend(f"explicit_risk_flag:{value}" for value in risk_flag_overrides)

    for changed_file in normalized:
        matched = False
        for raw_rule in rules:
            if not isinstance(raw_rule, dict) or not isinstance(raw_rule.get("id"), str):
                raise ValueError("Every path rule must have an id")
            patterns = _string_list(raw_rule.get("patterns"), label=f"path_rules.{raw_rule.get('id')}.patterns")
            if not any(_matches(changed_file, pattern) for pattern in patterns):
                continue
            matched = True
            rule_id = raw_rule["id"]
            selection_reasons.append(f"path_rule:{rule_id}:{changed_file}")
            task_classes.update(_string_list(raw_rule.get("task_classes", []), label=f"{rule_id}.task_classes"))
            risk_flags.update(_string_list(raw_rule.get("risk_flags", []), label=f"{rule_id}.risk_flags"))
            failure_ids.update(_string_list(raw_rule.get("known_failures", []), label=f"{rule_id}.known_failures"))
            for include in _string_list(raw_rule.get("include", []), label=f"{rule_id}.include"):
                includes.setdefault(include, set()).add(f"path_rule:{rule_id}")
        if not matched:
            unknown_paths.append(changed_file)

        changed_path = root / changed_file
        if changed_path.is_file() and changed_path.suffix.casefold() in {".md", ".yaml", ".yml"}:
            includes.setdefault(changed_file, set()).add("directly_changed_document")

    if unknown_paths:
        task_classes.update(_string_list(unknown_rule.get("task_classes", []), label="unknown_path.task_classes"))
        selection_reasons.extend(f"unknown_path:{path}" for path in unknown_paths)
    if "documentation_only" in task_classes and len(task_classes) > 1:
        task_classes.remove("documentation_only")

    class_context = manifest.get("task_class_context")
    flag_context = manifest.get("risk_flag_context")
    if not isinstance(class_context, dict) or not isinstance(flag_context, dict):
        raise ValueError("Manifest must define task_class_context and risk_flag_context mappings")
    for task_class in task_classes:
        for include in _string_list(class_context.get(task_class), label=f"task_class_context.{task_class}"):
            includes.setdefault(include, set()).add(f"task_class:{task_class}")
    for risk_flag in risk_flags:
        for include in _string_list(flag_context.get(risk_flag), label=f"risk_flag_context.{risk_flag}"):
            includes.setdefault(include, set()).add(f"risk_flag:{risk_flag}")

    full_flags = set(_string_list(manifest.get("full_context_flags"), label="full_context_flags"))
    force_full = full or bool(risk_flags & full_flags) or bool(unknown_paths)
    escalation_reasons: list[str] = []
    if full:
        escalation_reasons.append("explicit_full")
    escalation_reasons.extend(f"high_risk_flag:{flag}" for flag in sorted(risk_flags & full_flags))
    if unknown_paths:
        escalation_reasons.append(str(unknown_rule.get("reason", "unknown_path_fail_safe")))

    file_reasons: dict[str, set[str]] = {}
    core_file = manifest.get("core_file")
    if not isinstance(core_file, str):
        raise ValueError("Manifest core_file must be a string")
    file_reasons.setdefault(core_file, set()).add("mandatory_core")
    file_reasons.setdefault(role_files[role], set()).add(f"role:{role}")
    for include, reasons in includes.items():
        file_reasons.setdefault(include, set()).update(reasons)
    if force_full:
        for full_context_file in _string_list(manifest.get("full_context_files"), label="full_context_files"):
            file_reasons.setdefault(full_context_file, set()).add("full_context")

    selected_files: list[ContextFile] = []
    file_character_total = 0
    for relative in sorted(file_reasons):
        selected_path = _repo_file(root, relative)
        characters = len(selected_path.read_text(encoding="utf-8"))
        file_character_total += characters
        selected_files.append(
            ContextFile(relative, _sha256(selected_path), characters, tuple(sorted(file_reasons[relative])))
        )

    selected_failures: list[dict[str, Any]] = []
    for failure_id in sorted(failure_ids):
        if failure_id not in failures:
            raise ValueError(f"Manifest selects missing known failure: {failure_id}")
        selected_failures.append(failures[failure_id])

    checks, manual_checks = _matrix_checks(matrix, task_classes, risk_flags, normalized)
    structured_characters = len(
        json.dumps(
            {"known_failures": selected_failures, "checks": checks, "manual_checks": manual_checks},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    source_hashes = {
        str(path.relative_to(root)).replace("\\", "/"): _sha256(path)
        for path in (manifest_path, matrix_path, failures_path)
    }
    return ContextSelection(
        schema="senior-pomidor.agent-context.v1",
        role=role,
        changed_files=normalized,
        task_classes=tuple(sorted(task_classes)),
        risk_flags=tuple(sorted(risk_flags)),
        full_context=force_full,
        selection_reasons=tuple(dict.fromkeys(selection_reasons)),
        escalation_reasons=tuple(dict.fromkeys(escalation_reasons)),
        files=tuple(selected_files),
        known_failures=tuple(selected_failures),
        checks=checks,
        manual_checks=manual_checks,
        source_hashes=source_hashes,
        file_count=len(selected_files),
        context_characters=file_character_total + structured_characters,
    )


def _json_payload(selection: ContextSelection) -> dict[str, Any]:
    return asdict(selection)


def _text_payload(selection: ContextSelection) -> str:
    lines = [
        f"role: {selection.role}",
        f"task_classes: {', '.join(selection.task_classes)}",
        f"risk_flags: {', '.join(selection.risk_flags) or 'none'}",
        f"full_context: {str(selection.full_context).lower()}",
        f"context_characters: {selection.context_characters}",
        f"selection_reasons: {', '.join(selection.selection_reasons)}",
        "files:",
    ]
    lines.extend(
        f"  - {item.path} ({item.characters} chars, sha256={item.sha256}, reasons={','.join(item.reasons)})"
        for item in selection.files
    )
    lines.append("known_failures:")
    lines.extend(f"  - {item['failure_id']}: {item['symptom']}" for item in selection.known_failures)
    lines.append("checks:")
    lines.extend(f"  - {item['id']}: {item.get('command', item.get('description', ''))}" for item in selection.checks)
    if selection.manual_checks:
        lines.append("manual_checks:")
        lines.extend(f"  - {item}" for item in selection.manual_checks)
    if selection.escalation_reasons:
        lines.append(f"escalation_reasons: {', '.join(selection.escalation_reasons)}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Select a deterministic, read-only agent context pack.")
    parser.add_argument("--role", required=True, choices=ROLES)
    parser.add_argument("--changed-files", required=True, nargs="+")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--task-class", action="append", choices=TASK_CLASSES, default=[])
    parser.add_argument("--risk-flag", action="append", choices=RISK_FLAGS, default=[])
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        selection = select_context(
            args.role,
            args.changed_files,
            full=args.full,
            task_class_overrides=args.task_class,
            risk_flag_overrides=args.risk_flag,
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise SystemExit(f"agent-context: {exc}") from exc
    if args.format == "json":
        print(json.dumps(_json_payload(selection), indent=2, sort_keys=True))
    else:
        print(_text_payload(selection))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
