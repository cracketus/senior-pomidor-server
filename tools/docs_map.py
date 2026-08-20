"""Validate the versioned, read-only documentation ownership map."""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

SCHEMA = "docs_map_v1"
REQUIRED_ENTRY_FIELDS = {
    "id",
    "area",
    "lifecycle",
    "source_paths",
    "authoritative_documents",
    "owner",
    "authority_direction",
    "mechanical_fields",
    "semantic_review_required",
    "conflict_behavior",
    "cross_repository_impact",
    "required_checks",
}
AUTHORITY_DIRECTIONS = {
    "shared_semantic_review",
    "source_to_documentation_mechanical",
    "future_boundary_only",
}
CONFLICT_BEHAVIORS = {"human_review_no_truth_selection"}
IMPACT_LEVELS = {"none", "possible", "required", "unknown"}
LIFECYCLES = {"current", "future"}


class DocsMapError(ValueError):
    """Raised when a map violates its versioned contract."""


def _normalise_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DocsMapError(f"{field} must contain a non-empty path")
    path = value.replace("\\", "/").strip()
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        raise DocsMapError(f"{field} contains an unsafe path: {value!r}")
    return path


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise DocsMapError(f"{field} must be a list of non-empty strings")
    return [item.strip() for item in value]


def load_docs_map(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise DocsMapError(f"could not read map: {exc}") from exc
    if not isinstance(value, dict):
        raise DocsMapError("map must be an object")
    return value


def validate_docs_map(data: dict[str, Any], repository_root: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    if data.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if not isinstance(data.get("map_version"), int) or data["map_version"] < 1:
        errors.append("map_version must be a positive integer")
    if not isinstance(data.get("producer"), str) or not data["producer"].strip():
        errors.append("producer must be a non-empty string")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("entries must be a non-empty list")
        entries = []

    seen_ids: set[str] = set()
    seen_sources: dict[str, tuple[str, Any]] = {}
    normalised_entries: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        prefix = f"entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing = REQUIRED_ENTRY_FIELDS - entry.keys()
        if missing:
            errors.append(f"{prefix} missing fields: {', '.join(sorted(missing))}")
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            errors.append(f"{prefix}.id must be a non-empty string")
            entry_id = f"<entry-{index}>"
        elif entry_id in seen_ids:
            errors.append(f"duplicate entry id: {entry_id}")
        seen_ids.add(entry_id)

        source_paths: list[str] = []
        for path in entry.get("source_paths", []) if isinstance(entry.get("source_paths", []), list) else []:
            try:
                source_paths.append(_normalise_path(path, f"{prefix}.source_paths"))
            except DocsMapError as exc:
                errors.append(str(exc))
        documents: list[str] = []
        raw_documents = entry.get("authoritative_documents", [])
        for path in raw_documents if isinstance(raw_documents, list) else []:
            try:
                documents.append(_normalise_path(path, f"{prefix}.authoritative_documents"))
            except DocsMapError as exc:
                errors.append(str(exc))
        if not source_paths:
            errors.append(f"{prefix}.source_paths must not be empty")
        if not documents:
            errors.append(f"{prefix}.authoritative_documents must not be empty")
        owner = entry.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            errors.append(f"{prefix}.owner must be a non-empty string")
        direction = entry.get("authority_direction")
        if direction not in AUTHORITY_DIRECTIONS:
            errors.append(f"{prefix}.authority_direction is unsupported: {direction!r}")
        conflict = entry.get("conflict_behavior")
        if conflict not in CONFLICT_BEHAVIORS:
            errors.append(f"{prefix}.conflict_behavior must fail closed: {conflict!r}")
        if entry.get("lifecycle") not in LIFECYCLES:
            errors.append(f"{prefix}.lifecycle is unsupported: {entry.get('lifecycle')!r}")
        if entry.get("cross_repository_impact") not in IMPACT_LEVELS:
            errors.append(f"{prefix}.cross_repository_impact is unsupported")
        if not isinstance(entry.get("semantic_review_required"), bool):
            errors.append(f"{prefix}.semantic_review_required must be boolean")
        for field in ("mechanical_fields", "required_checks"):
            try:
                _string_list(entry.get(field), f"{prefix}.{field}")
            except DocsMapError as exc:
                errors.append(str(exc))
        for source in source_paths:
            previous = seen_sources.get(source)
            if previous and previous != (entry_id, direction):
                errors.append(f"authority conflict for source path {source!r}: {previous[0]} vs {entry_id}")
            seen_sources[source] = (entry_id, direction)
        normalised_entries.append({**entry, "source_paths": source_paths, "authoritative_documents": documents})

    missing_documents: list[str] = []
    if repository_root is not None:
        for entry in normalised_entries:
            for document in entry["authoritative_documents"]:
                if not (repository_root / document).is_file() and document not in missing_documents:
                    missing_documents.append(document)
        errors.extend(f"authoritative document does not exist: {path}" for path in missing_documents)

    return {
        "schema": "docs_map_validation_v1",
        "map_schema": data.get("schema"),
        "map_version": data.get("map_version"),
        "valid": not errors,
        "entry_count": len(normalised_entries),
        "errors": sorted(set(errors)),
        "entries": normalised_entries,
    }


def _matches(path: str, pattern: str) -> bool:
    normal = path.replace("\\", "/")
    return PurePosixPath(normal).match(pattern) or fnmatch.fnmatchcase(normal, pattern)


def coverage_report(validation: dict[str, Any], source_paths: list[str]) -> dict[str, Any]:
    entries = validation.get("entries", [])
    matched: dict[str, list[str]] = {}
    unknown: list[str] = []
    for raw_path in source_paths:
        path = raw_path.replace("\\", "/")
        ids = [entry["id"] for entry in entries if any(_matches(path, pattern) for pattern in entry["source_paths"])]
        if ids:
            matched[path] = sorted(ids)
        else:
            unknown.append(path)
    return {
        "schema": "docs_map_coverage_v1",
        "map_valid": validation.get("valid", False),
        "source_path_count": len(source_paths),
        "mapped_source_paths": len(matched),
        "unknown_source_paths": sorted(unknown),
        "coverage_percent": round((len(matched) / len(source_paths) * 100), 2) if source_paths else 100.0,
        "matches": {key: matched[key] for key in sorted(matched)},
        "validation_errors": validation.get("errors", []),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", dest="map_path", type=Path, default=Path("docs-map.yaml"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--source-path", action="append", default=[], help="path to include in coverage (repeatable)")
    parser.add_argument("--report", type=Path, help="optional JSON report path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        data = load_docs_map(args.map_path)
        validation = validate_docs_map(data, args.root)
    except DocsMapError as exc:
        report = {"schema": "docs_map_validation_v1", "valid": False, "errors": [str(exc)]}
        validation = report
    report = coverage_report(validation, args.source_path)
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0 if validation.get("valid") and not report["unknown_source_paths"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
