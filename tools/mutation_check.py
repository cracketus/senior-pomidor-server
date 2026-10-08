"""Bounded, deterministic mutation checking in a disposable tracked-source copy."""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

TARGETS = {
    "app/validation.py": ("validate_safe_identifier", "validate_record_id", "parse_utc_z"),
    "app/state_estimator/validation.py": ("validate_hard_range",),
    "app/state_estimator/confidence.py": ("sensor_confidence", "quality_level"),
}
TESTS = ["tests/test_validation.py", "tests/test_telemetry_idempotency.py", "tests/state_estimator"]


def mutants(source: str, functions: tuple[str, ...]) -> list[dict]:
    tree = ast.parse(source)
    candidates = []
    for function in tree.body:
        if isinstance(function, ast.FunctionDef) and function.name in functions:
            for node in ast.walk(function):
                if isinstance(node, ast.If):
                    candidates.append({"function": function.name, "line": node.lineno})
                    break
    return candidates


def negate(source: str, line: int) -> str:
    tree = ast.parse(source)
    changed = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and node.lineno == line:
            node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
            changed += 1
    if changed != 1:
        raise ValueError("mutation target must identify exactly one condition")
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


def run_tests(root: Path, timeout: int) -> str:
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(root), DATABASE_URL="sqlite:///:memory:")
    try:
        result = subprocess.run(  # nosec B603
            [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    return {0: "SURVIVED", 1: "KILLED"}.get(result.returncode, "ERROR")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args(argv)
    if not 5 <= args.timeout <= 120:
        parser.error("timeout must be 5..120 seconds per baseline/mutant")
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()  # nosec B603 B607
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")  # nosec B603 B607
    report: dict = {
        "schema_version": "senior-pomidor.mutation-report.v1",
        "revision": revision,
        "status": "FAIL",
        "mutants": [],
    }
    try:
        with tempfile.TemporaryDirectory(prefix="pomidor-mutation-") as directory:
            checkout = Path(directory)
            for relative in filter(None, paths):
                source = root / relative
                if source.is_symlink() or not source.is_file():
                    raise ValueError("tracked mutation inputs must be regular files")
                target = checkout / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            baseline = run_tests(checkout, args.timeout)
            report["baseline"] = "PASS" if baseline == "SURVIVED" else baseline
            if baseline != "SURVIVED":
                return 1
            for path, functions in TARGETS.items():
                target = checkout / path
                original_source = target.read_text(encoding="utf-8")
                for candidate in mutants(original_source, functions):
                    target.write_text(negate(original_source, candidate["line"]), encoding="utf-8")
                    try:
                        outcome = run_tests(checkout, args.timeout)
                        report["mutants"].append(
                            {"path": path, **candidate, "operator": "negate-condition", "status": outcome}
                        )
                    finally:
                        target.write_text(original_source, encoding="utf-8")
            expected = sum(len(functions) for functions in TARGETS.values())
            if len(report["mutants"]) == expected and all(m["status"] == "KILLED" for m in report["mutants"]):
                report["status"] = "PASS"
            return 0 if report["status"] == "PASS" else 1
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
