from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Iterable

ROLLOUT_GLOB = "rollout-*.jsonl"
DEFAULT_METADATA_SCAN_LINES = 64
DEFAULT_MAX_METADATA_LINE_BYTES = 1024 * 1024
MATCH_MODES = ("auto", "path", "name", "substring")
OUTPUT_FORMATS = ("text", "json", "jsonl")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:/")


@dataclass(frozen=True)
class SessionMatch:
    path: str
    archived: bool
    size_bytes: int
    modified_at_utc: str
    session_id: str | None
    cwd: str
    cli_version: str | None
    source: str | None
    metadata_line: int


@dataclass(frozen=True)
class ScanProblem:
    path: str
    reason: str


def resolve_codex_home(explicit: Path | None = None) -> Path:
    """Resolve Codex home without assuming Windows or POSIX."""
    if explicit is not None:
        return explicit.expanduser()
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex"


def _normalize_path_text(value: str) -> str:
    text = value.strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    if len(text) > 1:
        text = text.rstrip("/")
    return text


def _looks_like_path(value: str) -> bool:
    normalized = _normalize_path_text(value)
    return (
        "/" in normalized
        or normalized.startswith((".", "~"))
        or bool(_WINDOWS_DRIVE_RE.match(normalized))
    )


def _is_windows_path(value: str) -> bool:
    return bool(_WINDOWS_DRIVE_RE.match(_normalize_path_text(value)))


def _normalize_selector(project: str, mode: str) -> tuple[str, str]:
    if mode not in MATCH_MODES:
        raise ValueError(f"unsupported match mode: {mode}")

    effective_mode = mode
    if effective_mode == "auto":
        effective_mode = "path" if _looks_like_path(project) else "name"

    selector = project
    if effective_mode == "path":
        expanded = os.path.expandvars(os.path.expanduser(project))
        candidate = Path(expanded)
        try:
            if candidate.exists():
                expanded = str(candidate.resolve())
        except OSError:
            # Matching can still proceed using the caller-provided path text.
            pass
        selector = expanded

    selector = _normalize_path_text(selector)
    if not selector:
        raise ValueError("project selector must not be empty")
    return selector, effective_mode


def cwd_matches_project(
    cwd: str,
    project: str,
    *,
    mode: str = "auto",
    ignore_case: bool = False,
) -> bool:
    """Match a session cwd against a project path, directory name, or substring."""
    selector, effective_mode = _normalize_selector(project, mode)
    normalized_cwd = _normalize_path_text(cwd)
    if not normalized_cwd:
        return False

    fold_case = ignore_case or _is_windows_path(normalized_cwd) or _is_windows_path(selector)

    def comparable(value: str) -> str:
        return value.casefold() if fold_case else value

    cwd_cmp = comparable(normalized_cwd)
    selector_cmp = comparable(selector)

    if effective_mode == "path":
        return cwd_cmp == selector_cmp or cwd_cmp.startswith(f"{selector_cmp}/")
    if effective_mode == "substring":
        return selector_cmp in cwd_cmp

    # Directory-name matching is deliberately component based. A query for "server"
    # must not accidentally match a cwd whose component is "server-old".
    selector_name = selector.casefold()
    return any(component.casefold() == selector_name for component in normalized_cwd.split("/") if component)


def _read_bounded_line(stream: BinaryIO, max_bytes: int) -> tuple[bytes, bool]:
    if max_bytes <= 0:
        raise ValueError("max metadata line bytes must be positive")

    data = stream.readline(max_bytes + 1)
    oversized = len(data) > max_bytes
    if oversized and not data.endswith(b"\n"):
        # Discard the remainder without materializing an arbitrarily large line.
        while True:
            chunk = stream.readline(64 * 1024)
            if not chunk or chunk.endswith(b"\n"):
                break
    return data[:max_bytes], oversized


def read_session_metadata(
    path: Path,
    *,
    scan_lines: int = DEFAULT_METADATA_SCAN_LINES,
    max_line_bytes: int = DEFAULT_MAX_METADATA_LINE_BYTES,
) -> tuple[dict[str, object] | None, int | None, list[str]]:
    """Read only an early bounded prefix until a session_meta record is found."""
    if scan_lines <= 0:
        raise ValueError("metadata scan lines must be positive")

    warnings: list[str] = []
    try:
        with path.open("rb") as stream:
            for line_number in range(1, scan_lines + 1):
                raw, oversized = _read_bounded_line(stream, max_line_bytes)
                if not raw:
                    break
                if oversized:
                    warnings.append(f"line {line_number} exceeds metadata line limit")
                    continue
                try:
                    record = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    warnings.append(f"line {line_number} is not valid UTF-8 JSON")
                    continue
                if not isinstance(record, dict) or record.get("type") != "session_meta":
                    continue
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    warnings.append(f"line {line_number} session_meta payload is not an object")
                    continue
                return payload, line_number, warnings
    except OSError as exc:
        warnings.append(f"cannot read file: {exc}")
        return None, None, warnings

    warnings.append(f"session_meta not found in first {scan_lines} lines")
    return None, None, warnings


def _walk_rollouts(root: Path, problems: list[ScanProblem]) -> Iterable[Path]:
    if not root.exists():
        return
    if not root.is_dir():
        problems.append(ScanProblem(path=str(root), reason="scan root is not a directory"))
        return

    def onerror(exc: OSError) -> None:
        problems.append(ScanProblem(path=getattr(exc, "filename", str(root)), reason=f"walk failed: {exc}"))

    for directory, _, filenames in os.walk(root, onerror=onerror, followlinks=False):
        for filename in filenames:
            if filename.startswith("rollout-") and filename.endswith(".jsonl"):
                yield Path(directory) / filename


def _mtime_utc(stat_result: os.stat_result) -> str:
    return datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat().replace("+00:00", "Z")


def _optional_string(payload: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def find_sessions(
    project: str,
    *,
    codex_home: Path | None = None,
    include_archived: bool = True,
    match_mode: str = "auto",
    ignore_case: bool = False,
    scan_lines: int = DEFAULT_METADATA_SCAN_LINES,
    max_line_bytes: int = DEFAULT_MAX_METADATA_LINE_BYTES,
) -> tuple[list[SessionMatch], list[ScanProblem]]:
    """Find Codex rollout files whose session cwd belongs to the requested project."""
    home = resolve_codex_home(codex_home)
    problems: list[ScanProblem] = []
    roots: list[tuple[Path, bool]] = [(home / "sessions", False)]
    if include_archived:
        roots.append((home / "archived_sessions", True))

    if not any(root.exists() for root, _ in roots):
        problems.append(ScanProblem(path=str(home), reason="no Codex session directories found"))
        return [], problems

    matches: list[SessionMatch] = []
    seen_paths: set[str] = set()

    for root, archived in roots:
        for path in _walk_rollouts(root, problems):
            path_key = os.path.normcase(os.path.abspath(path))
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)

            payload, metadata_line, warnings = read_session_metadata(
                path,
                scan_lines=scan_lines,
                max_line_bytes=max_line_bytes,
            )
            if payload is None or metadata_line is None:
                problems.extend(ScanProblem(path=str(path), reason=warning) for warning in warnings)
                continue

            # Preserve non-fatal parse warnings as diagnostics while still using valid metadata.
            problems.extend(ScanProblem(path=str(path), reason=warning) for warning in warnings)

            cwd = payload.get("cwd")
            if not isinstance(cwd, str) or not cwd:
                problems.append(ScanProblem(path=str(path), reason="session_meta has no usable cwd"))
                continue
            try:
                is_match = cwd_matches_project(cwd, project, mode=match_mode, ignore_case=ignore_case)
            except ValueError:
                raise
            if not is_match:
                continue

            try:
                stat_result = path.stat()
            except OSError as exc:
                problems.append(ScanProblem(path=str(path), reason=f"cannot stat file: {exc}"))
                continue

            matches.append(
                SessionMatch(
                    path=str(path),
                    archived=archived,
                    size_bytes=stat_result.st_size,
                    modified_at_utc=_mtime_utc(stat_result),
                    session_id=_optional_string(payload, "id", "session_id"),
                    cwd=cwd,
                    cli_version=_optional_string(payload, "cli_version"),
                    source=_optional_string(payload, "source"),
                    metadata_line=metadata_line,
                )
            )

    matches.sort(key=lambda item: (item.modified_at_utc, item.path), reverse=True)
    return matches, problems


def _match_payload(match: SessionMatch) -> dict[str, object]:
    payload = asdict(match)
    payload["size_mib"] = round(match.size_bytes / (1024 * 1024), 3)
    return payload


def _print_text(matches: list[SessionMatch]) -> None:
    if not matches:
        print("No matching Codex sessions found.")
        return
    print(f"Found {len(matches)} Codex session(s):")
    for match in matches:
        archive_label = "archived" if match.archived else "current"
        size_mib = match.size_bytes / (1024 * 1024)
        session_id = match.session_id or "unknown"
        version = match.cli_version or "unknown"
        print(
            f"- {match.modified_at_utc} | {size_mib:.3f} MiB | {archive_label} | "
            f"session={session_id} | codex={version}"
        )
        print(f"  cwd:  {match.cwd}")
        print(f"  file: {match.path}")


def _print_output(matches: list[SessionMatch], output_format: str) -> None:
    if output_format == "text":
        _print_text(matches)
        return
    if output_format == "json":
        print(json.dumps([_match_payload(match) for match in matches], indent=2, ensure_ascii=False))
        return
    for match in matches:
        print(json.dumps(_match_payload(match), sort_keys=True, ensure_ascii=False))


def _print_problems(problems: list[ScanProblem]) -> None:
    for problem in problems:
        print(f"warning: {problem.path}: {problem.reason}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Find local Codex rollout sessions for a project without loading full JSONL files. "
            "The project may be a path or a directory name."
        )
    )
    parser.add_argument("project", help="Project path, directory name, or substring (with --match substring).")
    parser.add_argument(
        "--codex-home",
        type=Path,
        help="Codex home directory. Defaults to CODEX_HOME, then ~/.codex.",
    )
    parser.add_argument(
        "--match",
        choices=MATCH_MODES,
        default="auto",
        help="Matching mode. auto treats path-like selectors as paths and other selectors as directory names.",
    )
    parser.add_argument("--ignore-case", action="store_true", help="Use case-insensitive matching for POSIX paths too.")
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Search only sessions/, excluding archived_sessions/.",
    )
    parser.add_argument("--limit", type=int, help="Return at most N newest matching sessions.")
    parser.add_argument("--format", choices=OUTPUT_FORMATS, default="text", dest="output_format")
    parser.add_argument(
        "--metadata-scan-lines",
        type=int,
        default=DEFAULT_METADATA_SCAN_LINES,
        help=f"Maximum early JSONL records inspected per file (default: {DEFAULT_METADATA_SCAN_LINES}).",
    )
    parser.add_argument(
        "--max-metadata-line-bytes",
        type=int,
        default=DEFAULT_MAX_METADATA_LINE_BYTES,
        help=(
            "Maximum bytes materialized for one metadata candidate line "
            f"(default: {DEFAULT_MAX_METADATA_LINE_BYTES})."
        ),
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Return exit code 1 when individual session files could not be inspected.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("find-codex-sessions: --limit must be positive")
    if args.metadata_scan_lines <= 0:
        raise SystemExit("find-codex-sessions: --metadata-scan-lines must be positive")
    if args.max_metadata_line_bytes <= 0:
        raise SystemExit("find-codex-sessions: --max-metadata-line-bytes must be positive")

    try:
        matches, problems = find_sessions(
            args.project,
            codex_home=args.codex_home,
            include_archived=not args.active_only,
            match_mode=args.match,
            ignore_case=args.ignore_case,
            scan_lines=args.metadata_scan_lines,
            max_line_bytes=args.max_metadata_line_bytes,
        )
    except ValueError as exc:
        raise SystemExit(f"find-codex-sessions: {exc}") from exc

    if args.limit is not None:
        matches = matches[: args.limit]

    _print_output(matches, args.output_format)
    _print_problems(problems)

    home_missing = any(problem.reason == "no Codex session directories found" for problem in problems)
    if home_missing:
        return 2
    if args.fail_on_error and problems:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
