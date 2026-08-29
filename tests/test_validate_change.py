from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import cast

import pytest

from tools.agent_task import RepositoryContext, create_task
from tools.validate_change import (
    CommandResult,
    _harness_validation_mode,
    _nox_reuse_ready,
    _validation_storage_paths,
    validate_change,
)

ROOT = Path(__file__).resolve().parents[1]


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def validation_repo(tmp_path: Path) -> tuple[Path, RepositoryContext, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    for relative in (
        ".ai/CORE_INVARIANTS.md",
        ".ai/DEVELOPMENT_RULES.md",
        ".ai/context-manifest.yaml",
        ".ai/known-failures.yaml",
        ".ai/test-matrix.yaml",
        ".ai/model-routing.yaml",
        ".ai/tool-routing.yaml",
        ".ai/agents/coding-agent.md",
    ):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    (repo / ".gitignore").write_text(".agent-tasks/\n.agent-worktrees/\n.agent-usage/\n", encoding="utf-8")
    (repo / "tools").mkdir()
    (repo / "tools" / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    git(repo, "init")
    git(repo, "config", "user.email", "agent-test@example.invalid")
    git(repo, "config", "user.name", "Agent Test")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "baseline")
    base = git(repo, "rev-parse", "HEAD")
    context = RepositoryContext(repo.resolve(), repo.resolve(), (repo / ".git").resolve())
    return repo, context, base


def test_full_validation_caches_commands_and_invalidates_only_relevant_diff(
    validation_repo: tuple[Path, RepositoryContext, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, context, base = validation_repo
    metadata = create_task(
        context, "TOMATO-AI-41", "validation", "feature", worktree=False, task_classes=("pure_software",)
    )
    for session in ("lint", "format_check", "types"):
        (repo / ".nox" / session).mkdir(parents=True)
    (repo / "tools" / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "must-not-reach-validation")
    calls: list[list[str]] = []
    environments: list[dict[str, str]] = []

    def runner(command: list[str], **kwargs: object) -> CommandResult:
        calls.append(command)
        environments.append(cast(dict[str, str], kwargs["env"]))
        return CommandResult(0, 12, 0.01)

    first_code, _first = validate_change(
        root=repo, base=base, task_key=metadata["task_key"], force_full=True, runner=runner
    )
    second_code, second = validate_change(
        root=repo, base=base, task_key=metadata["task_key"], force_full=True, runner=runner
    )
    full_pytest_runs = sum(
        command[1:4] == ["-m", "pytest", "-q"] and not any(arg.startswith("tests/") for arg in command)
        for command in calls
    )
    quality_runs = sum(bool(command) and command[0] == "nox" for command in calls)
    pytest_command = next(
        command
        for command in calls
        if command[1:4] == ["-m", "pytest", "-q"] and not any(arg.startswith("tests/") for arg in command)
    )
    quality_command = next(command for command in calls if command and command[0] == "nox")
    pytest_basetemp = Path(pytest_command[pytest_command.index("--basetemp") + 1])
    nox_envdir = Path(quality_command[quality_command.index("--envdir") + 1])

    assert first_code == second_code == 0
    assert full_pytest_runs == 1
    assert quality_runs == 1
    assert pytest_basetemp.is_absolute()
    assert pytest_basetemp.parent.parent == repo.resolve()
    assert metadata["task_key"] not in str(pytest_basetemp)
    assert "--reuse-existing-virtualenvs" in quality_command
    assert "--no-install" in quality_command
    assert nox_envdir == repo.resolve() / ".nox"
    assert all("GITHUB_PERSONAL_ACCESS_TOKEN" not in environment for environment in environments)
    assert all(environment["GIT_CONFIG_KEY_0"] == "safe.directory" for environment in environments)
    assert all(environment["GIT_CONFIG_VALUE_0"] == str(repo.resolve()) for environment in environments)
    assert any(item["cached"] for item in second["checks"] if item["selected"] and "command" in item)
    assert not any("compose" in command for command in calls)

    (repo / "notes.md").write_text("docs only addition\n", encoding="utf-8")
    validate_change(root=repo, base=base, task_key=metadata["task_key"], force_full=True, runner=runner)
    assert (
        sum(
            command[1:4] == ["-m", "pytest", "-q"] and not any(arg.startswith("tests/") for arg in command)
            for command in calls
        )
        == 1
    )

    (repo / "tools" / "sample.py").write_text("VALUE = 3\n", encoding="utf-8")
    validate_change(root=repo, base=base, task_key=metadata["task_key"], force_full=True, runner=runner)
    assert (
        sum(
            command[1:4] == ["-m", "pytest", "-q"] and not any(arg.startswith("tests/") for arg in command)
            for command in calls
        )
        == 2
    )
    payload = json.loads(Path(metadata["state_dir"], "validation.json").read_text(encoding="utf-8"))
    assert payload["schema"] == "senior-pomidor.validation.v1"
    assert not Path(metadata["state_dir"], "validation.json.tmp").exists()


def test_validation_storage_uses_short_control_root_paths(tmp_path: Path) -> None:
    control_root = tmp_path / "repo"
    checkout_root = control_root / ".agent-worktrees" / ("deep-task-name-" * 6)
    context = RepositoryContext(checkout_root, control_root, control_root / ".git")
    task_key = "tomato-ai-43-" + ("long-validation-task-" * 8)

    pytest_basetemp, nox_envdir = _validation_storage_paths(context, "123456789abc", task_key, "first-input")
    changed_basetemp, _ = _validation_storage_paths(context, "123456789abc", task_key, "second-input")

    assert pytest_basetemp.parent == control_root / ".agent-validation-tmp-123456789abc"
    assert len(pytest_basetemp.name) == 12
    assert task_key not in str(pytest_basetemp)
    assert checkout_root not in pytest_basetemp.parents
    assert changed_basetemp != pytest_basetemp
    assert nox_envdir == control_root / ".nox"


def test_nox_skips_install_only_for_complete_unchanged_shared_environments(tmp_path: Path) -> None:
    args = ["nox", "-s", "lint", "format_check", "types"]
    envdir = tmp_path / ".nox"

    assert not _nox_reuse_ready(args, str(envdir), ("tools/sample.py",))
    for session in ("lint", "format_check", "types"):
        (envdir / session).mkdir(parents=True)

    assert _nox_reuse_ready(args, str(envdir), ("tools/sample.py",))
    assert not _nox_reuse_ready(args, str(envdir), ("pyproject.toml",))
    assert not _nox_reuse_ready(args, str(envdir), ("noxfile.py",))


def test_docs_only_skips_pytest_and_compose(validation_repo: tuple[Path, RepositoryContext, str]) -> None:
    repo, context, base = validation_repo
    metadata = create_task(
        context, "TOMATO-AI-42", "docs", "feature", worktree=False, task_classes=("documentation_only",)
    )
    (repo / "README.md").write_text("documentation change\n", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(command: list[str], **_: object) -> CommandResult:
        calls.append(command)
        return CommandResult(0, 0, 0.01)

    code, payload = validate_change(root=repo, base=base, task_key=metadata["task_key"], force_full=True, runner=runner)

    assert code == 0
    assert not any("pytest" in command or "compose" in command for command in calls)
    by_id = {item["id"]: item for item in payload["checks"]}
    assert by_id["full_pytest"]["selected"] is False
    assert by_id["compose_config"]["selected"] is False


def test_harness_python_changes_run_only_mapped_focused_tests(
    validation_repo: tuple[Path, RepositoryContext, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, context, base = validation_repo
    metadata = create_task(
        context, "TOMATO-AI-41", "harness-focused", "feature", worktree=False, task_classes=("pure_software",)
    )
    source = repo / "tools" / "agent_task.py"
    source.write_text("HARNESS_CHANGE = True\n", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(command: list[str], **_: object) -> CommandResult:
        calls.append(command)
        return CommandResult(0, 0, 0.01)

    code, payload = validate_change(root=repo, base=base, task_key=metadata["task_key"], force_full=True, runner=runner)

    assert code == 0
    assert len(calls) == 1
    assert calls[0][1:4] == ["-m", "pytest", "-q"]
    assert "tests/test_agent_task.py" in calls[0]
    assert not any("nox" in command for command in calls)
    assert {item["id"] for item in payload["checks"] if item["selected"]} == {"focused_tests"}
    assert payload["validation_mode"] == "harness_focused"


def test_harness_documentation_changes_run_no_tests(validation_repo: tuple[Path, RepositoryContext, str]) -> None:
    repo, context, base = validation_repo
    metadata = create_task(
        context, "TOMATO-AI-42", "harness-docs", "feature", worktree=False, task_classes=("pure_software",)
    )
    docs_path = repo / "docs" / "AI_VALIDATION_WORKFLOW.md"
    docs_path.parent.mkdir(parents=True)
    docs_path.write_text("harness documentation change\n", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(command: list[str], **_: object) -> CommandResult:
        calls.append(command)
        return CommandResult(0, 0, 0.01)

    code, payload = validate_change(root=repo, base=base, task_key=metadata["task_key"], force_full=True, runner=runner)

    assert code == 0
    assert calls == []
    assert not any(item["selected"] for item in payload["checks"])
    assert payload["validation_mode"] == "harness_no_tests"


def test_mixed_harness_and_application_changes_keep_matrix_mode() -> None:
    assert _harness_validation_mode(("tools/agent_task.py", "app/api.py")) is None
    assert _harness_validation_mode(("tools/agent_task.py", ".ai/agent-runs/run.json")) == "harness_focused"
    assert _harness_validation_mode((".ai/implementation-briefs/run.md",)) == "harness_no_tests"
