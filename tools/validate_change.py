from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import queue
import shlex
import subprocess  # nosec B404
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from tools.agent_context import ContextSelection, select_context
from tools.agent_task import (
    AgentTaskError,
    RepositoryContext,
    _read_env,
    load_task,
    repository_context,
    sanitized_process_environment,
)
from tools.agent_usage import make_usage_record, record_usage
from tools.model_routing import route_model

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = Path(".ai/test-matrix.yaml")
CONFIG_PATHS = (
    Path(".ai/context-manifest.yaml"),
    Path(".ai/test-matrix.yaml"),
    Path(".ai/model-routing.yaml"),
    Path(".ai/tool-routing.yaml"),
    Path("tools/agent_context.py"),
    Path("tools/agent_task.py"),
    Path("tools/model_routing.py"),
    Path("tools/tool_routing.py"),
    Path("tools/validate_change.py"),
)
HEAVY_CHECKS = {"full_pytest", "quality", "security", "dependency_audit", "compose_config"}
TIMEOUTS = {
    "full_pytest": 1800,
    "quality": 1200,
    "security": 1200,
    "dependency_audit": 1200,
    "feature_planner_evaluation": 600,
    "reviewer_evaluation": 600,
    "compose_config": 180,
    "diff_check": 120,
}


class ValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output_bytes: int
    elapsed_seconds: float
    timed_out: bool = False


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(  # nosec B603 B607
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise ValidationError((result.stderr or result.stdout).strip())
    return result.stdout


def _effective_identity() -> str:
    if os.name != "nt":
        get_effective_uid = getattr(os, "geteuid", lambda: 0)
        return f"uid:{get_effective_uid()}"
    process = subprocess.run(  # nosec B603 B607
        ["whoami"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode or not process.stdout.strip():
        raise ValidationError("could not determine the effective Windows identity for safe temp isolation")
    return process.stdout.strip().casefold()


def collect_changes(root: Path, base: str) -> tuple[str, tuple[str, ...], str, dict[str, str]]:
    base_sha = _git(root, "rev-parse", "--verify", f"{base}^{{commit}}").strip()
    tracked = _git(root, "diff", "--name-only", "--diff-filter=ACMRTUXB", base_sha, "--").splitlines()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    changed = tuple(sorted(dict.fromkeys(path.replace("\\", "/") for path in (*tracked, *untracked) if path)))
    file_hashes: dict[str, str] = {}
    for relative in changed:
        path = root / relative
        file_hashes[relative] = _sha256_file(path) if path.is_file() else "deleted"
    tracked_diff = _git(root, "diff", "--binary", base_sha, "--").encode("utf-8", "replace")
    untracked_manifest = "\n".join(f"{path}\0{file_hashes[path]}" for path in untracked).encode()
    diff_hash = _sha256_bytes(tracked_diff + b"\0UNTRACKED\0" + untracked_manifest)
    return base_sha, changed, diff_hash, file_hashes


def _matrix(root: Path) -> dict[str, Any]:
    loaded = yaml.safe_load((root / MATRIX_PATH).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or not isinstance(loaded.get("checks"), dict):
        raise ValidationError(".ai/test-matrix.yaml must define checks")
    return loaded


def _actual_command(
    check_id: str,
    definition: dict[str, Any],
    task_key: str,
    base_sha: str,
    changed_files: tuple[str, ...],
    file_hashes: dict[str, str],
    pytest_basetemp: str,
    nox_envdir: str,
) -> list[str] | None:
    if check_id == "compose_config":
        return [sys.executable, "-m", "tools.agent_task", "compose", task_key, "config"]
    if check_id == "diff_check":
        return ["git", "-C", ".", "diff", "--check", base_sha, "--"]
    if check_id == "focused_tests":
        changed_tests = [
            path
            for path in changed_files
            if path.startswith("tests/") and path.endswith(".py") and file_hashes[path] != "deleted"
        ]
        return (
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                pytest_basetemp,
                *changed_tests,
            ]
            if changed_tests
            else None
        )
    command = definition.get("command")
    if not isinstance(command, str):
        return None
    args = shlex.split(command, posix=os.name != "nt")
    if args and args[0] == "nox" and "--reuse-existing-virtualenvs" not in args:
        args.insert(1, "--reuse-existing-virtualenvs")
    if args and args[0] == "nox" and _nox_reuse_ready(args, nox_envdir, changed_files):
        args.insert(1, "--no-install")
    if args and args[0] == "nox" and "--envdir" not in args:
        args[1:1] = ["--envdir", nox_envdir]
    if args[:2] == ["python", "-m"]:
        args[0] = sys.executable
    if args[1:4] == ["-m", "pytest", "-q"]:
        args.extend(["-p", "no:cacheprovider", "--basetemp", pytest_basetemp])
    return args


def _nox_reuse_ready(args: list[str], nox_envdir: str, changed_files: tuple[str, ...]) -> bool:
    if any(path.casefold() in {"noxfile.py", "pyproject.toml"} for path in changed_files):
        return False
    try:
        session_index = args.index("-s") + 1
    except ValueError:
        return False
    sessions = [value for value in args[session_index:] if not value.startswith("-")]
    return bool(sessions) and all((Path(nox_envdir) / session).is_dir() for session in sessions)


def _validation_storage_paths(
    context: RepositoryContext, identity_hash: str, task_key: str, pytest_input_hash: str
) -> tuple[Path, Path]:
    run_hash = _sha256_bytes(f"{task_key}|{pytest_input_hash}".encode("utf-8", "replace"))[:12]
    pytest_basetemp = context.control_root / f".agent-validation-tmp-{identity_hash}" / run_hash
    nox_envdir = context.control_root / ".nox"
    return pytest_basetemp, nox_envdir


def _pytest_input_hash(changed_files: tuple[str, ...], file_hashes: dict[str, str]) -> str:
    relevant = {path: file_hashes[path] for path in changed_files if _is_relevant("full_pytest", path)}
    return _sha256_bytes(json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode())


def _is_relevant(check_id: str, path: str) -> bool:
    lower = path.casefold()
    python_change = lower.endswith(".py") or lower in {"pyproject.toml", "noxfile.py"}
    if check_id in {"full_pytest", "quality", "focused_tests"}:
        return python_change
    if check_id == "security":
        return python_change or "auth" in lower or "security" in lower
    if check_id == "dependency_audit":
        return lower in {"pyproject.toml", "requirements.txt"} or lower.startswith("requirements")
    if check_id == "compose_config":
        return lower.startswith(("docker/", "deploy/", "docker-compose")) or lower == ".env.example"
    if check_id == "feature_planner_evaluation":
        return lower.startswith(
            (
                ".ai/agents/feature-planner",
                ".ai/evaluations/feature-planner",
                ".ai/workflows/",
                ".ai/templates/",
                ".ai/model-routing.yaml",
                ".ai/tool-routing.yaml",
            )
        )
    if check_id == "reviewer_evaluation":
        return lower.startswith(
            (
                ".ai/agents/reviewer",
                ".ai/evaluations/reviewer",
                ".ai/templates/",
                ".ai/model-routing.yaml",
                ".ai/tool-routing.yaml",
            )
        )
    if check_id == "changed_links_paths_commands":
        return lower.endswith((".md", ".yaml", ".yml"))
    return True


def _fingerprint(
    root: Path,
    check_id: str,
    command: list[str],
    changed_files: tuple[str, ...],
    file_hashes: dict[str, str],
) -> str:
    relevant = {path: file_hashes[path] for path in changed_files if _is_relevant(check_id, path)}
    configs = {
        str(path).replace("\\", "/"): _sha256_file(root / path) for path in CONFIG_PATHS if (root / path).is_file()
    }
    if check_id in {"full_pytest", "quality", "security", "dependency_audit"}:
        for relative in (Path("pyproject.toml"), Path("noxfile.py")):
            if (root / relative).is_file():
                configs[str(relative)] = _sha256_file(root / relative)
    payload = {
        "check": check_id,
        "command": command,
        "relevant_diff": relevant,
        "environment": {
            "os_name": os.name,
            "platform": sys.platform,
            "python_cache_tag": sys.implementation.cache_tag,
            "machine": platform.machine(),
        },
        "config_hashes": configs,
    }
    if check_id == "reviewer_evaluation":
        payload["repository_refs_sha256"] = _sha256_bytes(_git(root, "show-ref").encode("utf-8", "replace"))
    return _sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def run_streaming(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
    heartbeat_seconds: int = 30,
) -> CommandResult:
    started = time.monotonic()
    process = subprocess.Popen(  # nosec B603
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    stdout = process.stdout
    if stdout is None:
        raise ValidationError("validation command output pipe was not created")
    output_queue: queue.Queue[bytes | None] = queue.Queue()

    def read_output() -> None:
        for line in iter(stdout.readline, b""):
            output_queue.put(line)
        output_queue.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    output_bytes = 0
    finished_output = False
    next_heartbeat = started + heartbeat_seconds
    timed_out = False
    while not finished_output or process.poll() is None:
        now = time.monotonic()
        if now - started > timeout_seconds:
            timed_out = True
            process.kill()
            break
        try:
            item = output_queue.get(timeout=min(1.0, max(0.01, next_heartbeat - now)))
        except queue.Empty:
            item = b""
        if item is None:
            finished_output = True
        elif item:
            output_bytes += len(item)
            print(item.decode("utf-8", "replace"), end="")
        now = time.monotonic()
        if now >= next_heartbeat and process.poll() is None:
            print(f"[validate-change heartbeat: {int(now - started)}s]")
            next_heartbeat = now + heartbeat_seconds
    reader.join(timeout=2)
    returncode = process.wait(timeout=5)
    if timed_out:
        returncode = 124
    return CommandResult(returncode, output_bytes, round(time.monotonic() - started, 3), timed_out)


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema": "senior-pomidor.validation-cache.v1", "entries": {}}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if loaded.get("schema") != "senior-pomidor.validation-cache.v1" or not isinstance(loaded.get("entries"), dict):
        raise ValidationError("validation cache has an unknown schema")
    return loaded


def _selection(root: Path, changed_files: tuple[str, ...], metadata: dict[str, Any]) -> ContextSelection:
    task_classes = metadata.get("task_classes", ())
    risk_flags = metadata.get("risk_flags", ())
    if not isinstance(task_classes, list) or not isinstance(risk_flags, list):
        raise ValidationError("task classification metadata must contain lists")
    return select_context(
        "coder",
        changed_files,
        task_class_overrides=task_classes,
        risk_flag_overrides=risk_flags,
        root=root,
    )


def validate_change(
    *,
    root: Path,
    base: str,
    task_key: str,
    explain: bool = False,
    force_full: bool = False,
    runner: Callable[..., CommandResult] = run_streaming,
) -> tuple[int, dict[str, Any]]:
    started = time.monotonic()
    root = root.resolve()
    context = repository_context(root)
    task_dir, metadata = load_task(context, task_key)
    if metadata.get("status") != "active":
        raise ValidationError("agent task must be active before validation")
    if Path(metadata.get("worktree", "")).resolve() != root:
        raise ValidationError("validation must run from the task checkout recorded in metadata")
    base_sha, changed_files, diff_hash, file_hashes = collect_changes(root, base)
    if not changed_files:
        raise ValidationError("no changed files were found relative to the base")
    selection = _selection(root, changed_files, metadata)
    matrix = _matrix(root)
    definitions: dict[str, dict[str, Any]] = matrix["checks"]
    selected_definitions = {item["id"]: item for item in selection.checks}
    route = route_model("pure_software_implementation", risk_flags=selection.risk_flags)
    cache_path = task_dir / "validation-cache.json"
    cache = _load_cache(cache_path)
    environment = sanitized_process_environment(_read_env(Path(metadata["env_file"])))
    identity_source = "|".join(
        [
            _effective_identity(),
            *(os.environ.get(name, "") for name in ("USERDOMAIN", "USERNAME", "USERPROFILE", "HOME")),
        ]
    )
    identity_hash = _sha256_bytes(identity_source.encode("utf-8", "replace"))[:12]
    pytest_basetemp, nox_envdir = _validation_storage_paths(
        context, identity_hash, task_key, _pytest_input_hash(changed_files, file_hashes)
    )
    pytest_basetemp.parent.mkdir(exist_ok=True)
    environment.update(
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": str(root),
        }
    )
    check_results: list[dict[str, Any]] = []
    tool_output_bytes = 0

    for check_id, _definition in definitions.items():
        selected = check_id in selected_definitions
        result: dict[str, Any] = {"id": check_id, "selected": selected, "status": "NOT_RUN", "cached": False}
        if not selected:
            result["reason"] = "not_selected_by_task_classes_or_risk_flags"
            check_results.append(result)
            continue
        command = _actual_command(
            check_id,
            selected_definitions[check_id],
            task_key,
            base_sha,
            changed_files,
            file_hashes,
            str(pytest_basetemp),
            str(nox_envdir),
        )
        if command is None:
            result["reason"] = "selected_check_requires_explicit_focused_or_manual_evidence"
            check_results.append(result)
            continue
        result["command"] = command
        if not force_full and check_id in HEAVY_CHECKS:
            result["reason"] = "deferred_until_force_full"
            check_results.append(result)
            continue
        fingerprint = _fingerprint(root, check_id, command, changed_files, file_hashes)
        result["fingerprint"] = fingerprint
        cached = cache["entries"].get(fingerprint)
        if isinstance(cached, dict) and cached.get("status") in {"PASS", "FAIL"}:
            result.update(
                status=cached["status"],
                cached=True,
                reason="cached_identical_relevant_diff_command_environment_and_config",
                elapsed_seconds=cached.get("elapsed_seconds", 0.0),
            )
            check_results.append(result)
            continue
        print(f"[validate-change] {check_id}: {' '.join(command)}")
        command_result = runner(
            command,
            cwd=root,
            env=environment,
            timeout_seconds=TIMEOUTS.get(check_id, 600),
        )
        tool_output_bytes += command_result.output_bytes
        status = "PASS" if command_result.returncode == 0 else "FAIL"
        reason = "command_completed" if not command_result.timed_out else "command_timed_out"
        result.update(
            status=status,
            reason=reason,
            returncode=command_result.returncode,
            elapsed_seconds=command_result.elapsed_seconds,
        )
        cache["entries"][fingerprint] = {
            "check_id": check_id,
            "status": status,
            "returncode": command_result.returncode,
            "elapsed_seconds": command_result.elapsed_seconds,
            "recorded_at_utc": datetime.now(UTC).isoformat(),
        }
        _atomic_json(cache_path, cache)
        check_results.append(result)

    for manual_id in selection.manual_checks:
        check_results.append(
            {
                "id": manual_id,
                "selected": True,
                "manual": True,
                "status": "NOT_RUN",
                "cached": False,
                "reason": "manual_evidence_not_provided",
            }
        )
    payload = {
        "schema": "senior-pomidor.validation.v1",
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "task_key": task_key,
        "base": base,
        "base_sha": base_sha,
        "diff_sha256": diff_hash,
        "mode": "full" if force_full else "focused",
        "changed_files": list(changed_files),
        "task_classes": list(selection.task_classes),
        "risk_flags": list(selection.risk_flags),
        "selection_reasons": list(selection.selection_reasons),
        "model_route": asdict(route),
        "checks": check_results,
    }
    _atomic_json(task_dir / "validation.json", payload)
    usage_reasons = tuple(reason for reason in route.escalation_reasons if reason != "none") or ("none",)
    usage = make_usage_record(
        role="coder",
        file_count=selection.file_count,
        input_characters=selection.context_characters,
        tool_output_bytes=tool_output_bytes,
        model_tier=route.model_tier,
        elapsed_seconds=round(time.monotonic() - started, 3),
        escalation_reasons=usage_reasons,
    )
    record_usage(usage, output=task_dir / "usage.jsonl", root=context.control_root)
    if explain:
        for item in check_results:
            state = "selected" if item["selected"] else "skipped"
            print(f"{item['id']}: {state}, {item['status']} ({item['reason']})")
    failed = any(item["selected"] and item["status"] == "FAIL" for item in check_results)
    return (1 if failed else 0), payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan, cache, run, and record deterministic change validation.")
    parser.add_argument("--base", required=True)
    parser.add_argument("--task-key", required=True)
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--force", choices=("full",))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return validate_change(
            root=Path.cwd(),
            base=args.base,
            task_key=args.task_key,
            explain=args.explain,
            force_full=args.force == "full",
        )[0]
    except (AgentTaskError, OSError, ValidationError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"validate-change: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
