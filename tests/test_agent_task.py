from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import tools.agent_task as agent_task_module
from tools.agent_task import (
    AgentTaskError,
    RepositoryContext,
    _validate_rendered_compose,
    build_environment,
    check_task,
    cleanup_task,
    create_task,
    retire_task,
    sanitized_process_environment,
    validate_environment,
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> tuple[Path, RepositoryContext]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "agent-test@example.invalid")
    git(repo, "config", "user.name", "Agent Test")
    (repo / ".gitignore").write_text(".agent-tasks/\n.agent-worktrees/\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    git(repo, "add", ".gitignore", "tracked.txt")
    git(repo, "commit", "-m", "baseline")
    context = RepositoryContext(repo.resolve(), repo.resolve(), (repo / ".git").resolve())
    return repo, context


def test_two_tasks_use_distinct_branches_ports_projects_and_data(git_repo: tuple[Path, RepositoryContext]) -> None:
    _, context = git_repo

    first = create_task(context, "TOMATO-AI-127", "coding-agent", "feature")
    second = create_task(context, "TOMATO-AI-128", "agent-sandbox", "feature")

    first_env = read_env(Path(first["env_file"]))
    second_env = read_env(Path(second["env_file"]))
    assert first["branch"] != second["branch"]
    assert first["port_base"] != second["port_base"]
    assert first_env["COMPOSE_PROJECT_NAME"] != second_env["COMPOSE_PROJECT_NAME"]
    assert first_env["POSTGRES_DATA_DIR"] != second_env["POSTGRES_DATA_DIR"]
    assert Path(first["worktree"]).is_dir()
    assert Path(second["worktree"]).is_dir()


def test_generated_environment_is_local_fake_and_export_disabled(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    environment = build_environment(task_dir, "tomato-ai-128-agent-sandbox", 22000)

    assert environment["LAN_BIND_ADDRESS"] == "127.0.0.1"
    assert environment["POSTGRES_BIND_ADDRESS"] == "127.0.0.1"
    assert environment["GRAFANA_CLOUD_EXPORT_ENABLED"] == "false"
    assert environment.get("GRAFANA_CLOUD_REMOTE_WRITE_URL", "") == ""
    assert environment["GRAFANA_CLOUD_INSTANCE_ID"] == ""
    assert environment["GRAFANA_CLOUD_API_TOKEN"] == ""
    assert environment["EXECUTOR_BACKEND"] == "fake"
    assert environment["HARDWARE_BACKEND"] == "fake"
    assert environment["GPIO_ENABLED"] == "false"
    assert environment["AGENT_TASK_ISOLATED"] == "true"
    assert len({environment[name] for name in published_port_names()}) == 5
    for name in data_path_names():
        assert Path(environment[name]).resolve().is_relative_to((task_dir / "data").resolve())


def test_long_task_keys_keep_distinct_compose_project_names(tmp_path: Path) -> None:
    shared_prefix = "tomato-ai-128-" + ("a" * 60)
    first = build_environment(tmp_path / "first", f"{shared_prefix}-first", 22000)
    second = build_environment(tmp_path / "second", f"{shared_prefix}-second", 22010)

    assert first["COMPOSE_PROJECT_NAME"] != second["COMPOSE_PROJECT_NAME"]
    assert len(first["COMPOSE_PROJECT_NAME"]) <= 51


def test_environment_rejects_production_path_and_external_export(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    environment = build_environment(task_dir, "tomato-ai-128-agent-sandbox", 22000)
    environment["POSTGRES_DATA_DIR"] = "/srv/apps/senior-pomidor/data"
    with pytest.raises(AgentTaskError, match="POSTGRES_DATA_DIR"):
        validate_environment(environment, task_dir / "data")

    environment = build_environment(task_dir, "tomato-ai-128-agent-sandbox", 22000)
    environment["GRAFANA_CLOUD_EXPORT_ENABLED"] = "true"
    with pytest.raises(AgentTaskError, match="Cloud export"):
        validate_environment(environment, task_dir / "data")


def test_sanitized_process_environment_drops_production_sensitive_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://production.invalid/live")
    monkeypatch.setenv("DOCKER_HOST", "ssh://production.invalid")
    monkeypatch.setenv("GRAFANA_CLOUD_API_TOKEN", "must-not-leak")
    monkeypatch.setenv("PROGRAMFILES", r"C:\Program Files")

    sanitized = sanitized_process_environment({"DATABASE_URL": "sqlite:///agent.db", "GPIO_ENABLED": "false"})

    assert sanitized["DATABASE_URL"] == "sqlite:///agent.db"
    assert "DOCKER_HOST" not in sanitized
    assert "GRAFANA_CLOUD_API_TOKEN" not in sanitized
    assert sanitized["GPIO_ENABLED"] == "false"
    assert sanitized["PROGRAMFILES"] == r"C:\Program Files"


def test_subprocess_output_uses_bounded_utf8_replacement(tmp_path: Path) -> None:
    result = agent_task_module._run(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([0x81]))"], cwd=tmp_path
    )
    assert result.stdout == "�"


def test_cleanup_refuses_dirty_worktree_and_preserves_branch_and_data(git_repo: tuple[Path, RepositoryContext]) -> None:
    repo, context = git_repo
    metadata = create_task(context, "TOMATO-AI-128", "cleanup", "fix")
    worktree = Path(metadata["worktree"])
    uncommitted = worktree / "uncommitted.txt"
    uncommitted.write_text("keep me\n", encoding="utf-8")

    with pytest.raises(AgentTaskError, match="dirty"):
        cleanup_task(context, metadata["task_key"])
    assert uncommitted.read_text(encoding="utf-8") == "keep me\n"
    assert git(repo, "show-ref", "--verify", f"refs/heads/{metadata['branch']}")

    uncommitted.unlink()
    result = cleanup_task(context, metadata["task_key"])
    assert result["status"] == "cleaned"
    assert not worktree.exists()
    assert Path(metadata["state_dir"]).is_dir()
    assert git(repo, "show-ref", "--verify", f"refs/heads/{metadata['branch']}")


def test_create_refuses_dirty_source_worktree(git_repo: tuple[Path, RepositoryContext]) -> None:
    repo, context = git_repo
    (repo / "dirty.txt").write_text("untracked\n", encoding="utf-8")

    with pytest.raises(AgentTaskError, match="dirty"):
        create_task(context, "TOMATO-AI-128", "refuse-dirty", "feature")


@pytest.mark.parametrize("failed_stage", ["allocation", "metadata", "branch", "worktree"])
def test_create_failure_remains_diagnosable_and_keeps_allocation(
    git_repo: tuple[Path, RepositoryContext], monkeypatch: pytest.MonkeyPatch, failed_stage: str
) -> None:
    repo, context = git_repo

    def fail_at(stage: str) -> None:
        if stage == failed_stage:
            raise RuntimeError(f"injected failure after {stage}")

    monkeypatch.setattr(agent_task_module, "_creation_checkpoint", fail_at)
    with pytest.raises(RuntimeError, match="injected failure"):
        create_task(context, "TOMATO-AI-128", f"fail-{failed_stage}", "feature")

    key = f"tomato-ai-128-fail-{failed_stage}"
    task_dir = repo / ".agent-tasks" / key
    metadata = json.loads((task_dir / "metadata.json").read_text(encoding="utf-8"))
    allocation = Path(metadata["allocation_file"])
    assert metadata["status"] == "creation_failed"
    assert metadata["creation_stage"] == failed_stage
    assert failed_stage in metadata["creation_error"]
    assert allocation.is_file()
    assert json.loads(allocation.read_text(encoding="utf-8"))["owner"] == key

    monkeypatch.setattr(agent_task_module, "_creation_checkpoint", lambda stage: None)
    second = create_task(context, "TOMATO-AI-129", f"after-{failed_stage}", "feature")
    assert second["port_base"] != metadata["port_base"]


def test_cleanup_allows_clean_creation_failed_worktree(
    git_repo: tuple[Path, RepositoryContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, context = git_repo

    def fail_after_worktree(stage: str) -> None:
        if stage == "worktree":
            raise RuntimeError("injected failure after worktree")

    monkeypatch.setattr(agent_task_module, "_creation_checkpoint", fail_after_worktree)
    with pytest.raises(RuntimeError):
        create_task(context, "TOMATO-AI-128", "failed-cleanup", "fix")
    _, failed = agent_task_module.load_task(context, "tomato-ai-128-failed-cleanup")
    dirty = Path(failed["worktree"]) / "untracked.txt"
    dirty.write_text("preserve\n", encoding="utf-8")
    with pytest.raises(AgentTaskError, match="dirty"):
        cleanup_task(context, "tomato-ai-128-failed-cleanup")
    dirty.unlink()
    result = cleanup_task(context, "tomato-ai-128-failed-cleanup")
    assert result["status"] == "cleaned"
    assert not Path(result["worktree"]).exists()


def test_retire_releases_only_owned_allocation_and_preserves_task_artifacts(
    git_repo: tuple[Path, RepositoryContext],
) -> None:
    repo, context = git_repo
    metadata = create_task(context, "TOMATO-AI-128", "retire", "feature")
    task_dir = Path(metadata["state_dir"])
    history = task_dir / "commands.jsonl"
    history.write_text('{"action":"test"}\n', encoding="utf-8")
    data_root = task_dir / "data"
    cleaned = cleanup_task(context, metadata["task_key"])
    allocation = Path(cleaned["allocation_file"])
    assert allocation.is_file()

    retired = retire_task(context, metadata["task_key"])
    assert retired["status"] == "retired"
    assert not allocation.exists()
    assert data_root.is_dir()
    assert history.is_file()
    assert git(repo, "show-ref", "--verify", f"refs/heads/{metadata['branch']}")
    with pytest.raises(AgentTaskError, match="already retired"):
        retire_task(context, metadata["task_key"])


def test_retire_refuses_foreign_allocation(git_repo: tuple[Path, RepositoryContext]) -> None:
    _, context = git_repo
    metadata = create_task(context, "TOMATO-AI-128", "foreign-allocation", "feature")
    cleanup_task(context, metadata["task_key"])
    allocation = Path(metadata["allocation_file"])
    allocation.write_text('{"owner":"another-task"}\n', encoding="utf-8")
    with pytest.raises(AgentTaskError, match="belongs to another task"):
        retire_task(context, metadata["task_key"])
    assert allocation.is_file()


def test_retire_requires_cleanup_and_stopped_compose(git_repo: tuple[Path, RepositoryContext]) -> None:
    _, context = git_repo
    metadata = create_task(context, "TOMATO-AI-128", "retire-state", "feature")
    with pytest.raises(AgentTaskError, match="must be cleaned"):
        retire_task(context, metadata["task_key"])
    cleaned = cleanup_task(context, metadata["task_key"])
    cleaned["compose_running"] = True
    agent_task_module._write_metadata(Path(cleaned["state_dir"]), cleaned)
    with pytest.raises(AgentTaskError, match="retire is forbidden"):
        retire_task(context, metadata["task_key"])


def test_retire_recovers_after_allocation_was_atomically_claimed(git_repo: tuple[Path, RepositoryContext]) -> None:
    _, context = git_repo
    metadata = create_task(context, "TOMATO-AI-128", "retire-recovery", "feature")
    cleaned = cleanup_task(context, metadata["task_key"])
    allocation = Path(cleaned["allocation_file"])
    marker = allocation.with_name(f"ports-{cleaned['port_base']}.releasing-{cleaned['task_key']}")
    os.replace(allocation, marker)

    retired = retire_task(context, metadata["task_key"])
    assert retired["status"] == "retired"
    assert not marker.exists()


def test_agent_compose_overlay_and_docs_exclude_unsafe_controls() -> None:
    root = Path(__file__).resolve().parents[1]
    overlay = (root / "docker-compose.agent.yml").read_text(encoding="utf-8")
    workflow = (root / "docs/AGENT_TASK_WORKFLOW.md").read_text(encoding="utf-8")
    template = (root / ".ai/templates/agent-task.env.example").read_text(encoding="utf-8")

    assert 'GRAFANA_CLOUD_EXPORT_ENABLED: "false"' in overlay
    assert "cloud-export" not in template
    assert "GRAFANA_CLOUD_EXPORT_ENABLED=false" in template
    assert "EXECUTOR_BACKEND=fake" in template
    assert "GPIO_ENABLED=false" in template
    assert "down -v" in workflow
    assert "cannot be selected" in workflow
    assert "/dev/" not in overlay


def test_rendered_compose_allows_absent_exporter_and_rejects_active_exporter(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    safe: dict[str, Any] = {
        "services": {
            "api": {
                "ports": [{"host_ip": "127.0.0.1", "published": "22000", "target": 8000}],
                "volumes": [{"type": "bind", "source": str(data_root / "photos"), "target": "/app/data"}],
            }
        }
    }
    _validate_rendered_compose(safe, data_root, tmp_path, [])

    unsafe = {
        "services": {
            "grafana-cloud-exporter": {
                "profiles": ["cloud-export"],
                "environment": {"GRAFANA_CLOUD_EXPORT_ENABLED": "true"},
            }
        }
    }
    with pytest.raises(AgentTaskError, match="enables Grafana Cloud export"):
        _validate_rendered_compose(unsafe, data_root, tmp_path, [])


@pytest.mark.parametrize(
    ("rendered", "message"),
    [
        ({"services": {"api": {"ports": [{"host_ip": "127.0.0.1.evil", "published": "22000"}]}}}, "non-loopback"),
        ({"services": {"api": {"network_mode": "host"}}}, "host network_mode"),
        ({"services": {"api": {"devices": ["/dev/null:/dev/null"]}}}, "maps host devices"),
        ({"services": {"api": {"privileged": True}}}, "privileged"),
        ({"services": {"api": {"cap_add": ["SYS_ADMIN"]}}}, "capabilities"),
        ({"services": {}, "volumes": {"shared": {"external": True}}}, "volume shared is external"),
        ({"services": {}, "networks": {"shared": {"external": {"name": "shared"}}}}, "network shared is external"),
        ({"services": {}, "networks": {"hostnet": {"driver": "host"}}}, "uses the host driver"),
        ({"services": {}, "secrets": {"token": {"file": "token.txt"}}}, "declares secrets"),
    ],
)
def test_rendered_compose_rejects_unsafe_features(tmp_path: Path, rendered: dict[str, object], message: str) -> None:
    data_root = tmp_path / "data"
    worktree = tmp_path / "worktree"
    data_root.mkdir()
    worktree.mkdir()
    with pytest.raises(AgentTaskError, match=message):
        _validate_rendered_compose(rendered, data_root, worktree, [])


def test_rendered_compose_mount_roots_and_ipv6_loopback(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    worktree = tmp_path / "worktree"
    outside = tmp_path / "outside"
    data_root.mkdir()
    worktree.mkdir()
    outside.mkdir()
    safe: dict[str, Any] = {
        "services": {
            "api": {
                "ports": [{"host_ip": "::1", "published": "22000"}],
                "volumes": [
                    {"type": "bind", "source": str(data_root), "read_only": False},
                    {"type": "bind", "source": str(worktree), "read_only": True},
                ],
            }
        }
    }
    _validate_rendered_compose(safe, data_root, worktree, [])
    safe["services"]["api"]["volumes"][1]["source"] = str(outside)
    with pytest.raises(AgentTaskError, match="read-only bind outside"):
        _validate_rendered_compose(safe, data_root, worktree, [])
    safe["services"]["api"]["volumes"][1] = {
        "type": "bind",
        "source": str(outside),
        "read_only": False,
    }
    with pytest.raises(AgentTaskError, match="writable bind outside"):
        _validate_rendered_compose(safe, data_root, worktree, [])


def test_port_preflight_rejects_occupied_port_and_accepts_free_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_task_module, "PUBLISHED_PORT_NAMES", ("API_PUBLISHED_PORT",))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        with pytest.raises(AgentTaskError, match="occupied or unavailable"):
            agent_task_module._require_available_ports(tmp_path, {"API_PUBLISHED_PORT": str(port)})
    agent_task_module._require_available_ports(tmp_path, {"API_PUBLISHED_PORT": str(port)})


def test_generated_environment_matches_documented_template(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    template = read_env(root / ".ai/templates/agent-task.env.example")
    generated = build_environment(tmp_path / "task", "tomato-ai-128-template", 22000)
    assert set(template) == set(generated)


@pytest.mark.parametrize("status", ["active", "cleaned"])
def test_legacy_metadata_remains_readable(git_repo: tuple[Path, RepositoryContext], status: str) -> None:
    repo, context = git_repo
    key = f"tomato-ai-128-legacy-{status}"
    task_dir = repo / ".agent-tasks" / key
    task_dir.mkdir(parents=True)
    legacy = {"schema": "senior-pomidor.agent-task.v1", "task_key": key, "status": status}
    (task_dir / "metadata.json").write_text(json.dumps(legacy), encoding="utf-8")
    _, loaded = agent_task_module.load_task(context, key)
    assert loaded == legacy


def test_coding_agent_and_report_contract_have_required_sections() -> None:
    root = Path(__file__).resolve().parents[1]
    agent = (root / ".ai/agents/coding-agent.md").read_text(encoding="utf-8")
    report = (root / ".ai/templates/implementation-report.md").read_text(encoding="utf-8")

    for required in (
        "reconnaissance",
        "smallest coherent approved change",
        "PASS`, `FAIL`, or `NOT RUN",
        "production",
        "Stop and ask a human",
    ):
        assert required in agent
    for heading in (
        "## Implemented behavior",
        "## Files changed and purpose",
        "## Design decisions",
        "## Deviations from brief",
        "## Tests added",
        "## Commands run and results",
        "## Compatibility checks",
        "## Safety impact",
        "## Known limitations",
        "## Documentation changes",
        "## Manual verification steps",
    ):
        assert heading in report


def test_docker_context_guard_rejects_remote_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = iter(
        (
            subprocess.CompletedProcess(["docker", "context", "show"], 0, "production\n", ""),
            subprocess.CompletedProcess(["docker", "context", "inspect"], 0, "ssh://production.invalid\n", ""),
        )
    )

    def fake_run(
        args: list[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return next(calls)

    monkeypatch.setattr(agent_task_module, "_run", fake_run)
    with pytest.raises(AgentTaskError, match="verified local"):
        agent_task_module._require_local_docker_context(tmp_path, tmp_path, {})
    audit = (tmp_path / "commands.jsonl").read_text(encoding="utf-8")
    assert "production" not in audit
    assert "ssh://" not in audit


def test_failed_compose_up_blocks_cleanup(
    git_repo: tuple[Path, RepositoryContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, context = git_repo
    metadata = create_task(context, "TOMATO-AI-128", "partial-startup", "fix", worktree=False)
    rendered = subprocess.CompletedProcess(["docker", "compose", "config"], 0, '{"services": {}}', "")
    failed_up = subprocess.CompletedProcess(["docker", "compose", "up"], 1, "", "startup failed")
    results = iter((rendered, failed_up))

    monkeypatch.setattr(agent_task_module, "_require_local_docker_context", lambda *args: None)
    monkeypatch.setattr(agent_task_module, "_run", lambda *args, **kwargs: next(results))

    assert agent_task_module.compose_task(context, metadata["task_key"], "up", []) == 1
    persisted = json.loads(Path(metadata["state_dir"], "metadata.json").read_text(encoding="utf-8"))
    assert persisted["compose_running"] is True
    with pytest.raises(AgentTaskError, match="may be running"):
        cleanup_task(context, metadata["task_key"])


def read_env(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )


def published_port_names() -> tuple[str, ...]:
    return (
        "API_PUBLISHED_PORT",
        "MQTT_PUBLISHED_PORT",
        "POSTGRES_PUBLISHED_PORT",
        "GRAFANA_PUBLISHED_PORT",
        "OLLAMA_PUBLISHED_PORT",
    )


def data_path_names() -> tuple[str, ...]:
    return (
        "PHOTO_DATA_DIR",
        "ESTIMATOR_PRIVATE_DATA_DIR",
        "MOSQUITTO_DATA_DIR",
        "POSTGRES_DATA_DIR",
        "GRAFANA_DATA_DIR",
        "OLLAMA_DATA_DIR",
    )


def test_metadata_is_json_and_contains_no_generated_credentials(git_repo: tuple[Path, RepositoryContext]) -> None:
    repo, context = git_repo
    metadata = create_task(context, "TOMATO-AI-128", "metadata", "feature", worktree=False)
    serialized = json.loads(Path(metadata["state_dir"], "metadata.json").read_text(encoding="utf-8"))

    assert serialized["schema"] == "senior-pomidor.agent-task.v1"
    assert "PASSWORD" not in json.dumps(serialized).upper()
    assert "TOKEN" not in json.dumps(serialized).upper()
    assert os.path.samefile(serialized["worktree"], context.checkout_root)
    assert git(repo, "branch", "--show-current") == metadata["branch"]


def test_bounded_check_uses_sanitized_environment_and_records_result(
    git_repo: tuple[Path, RepositoryContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, context = git_repo
    metadata = create_task(context, "TOMATO-AI-128", "safe-check", "feature", worktree=False)
    monkeypatch.setenv("DOCKER_HOST", "ssh://production.invalid")
    observed: dict[str, object] = {}

    def fake_run(
        args: list[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        observed.update(args=args, cwd=cwd, env=env, check=check)
        return subprocess.CompletedProcess(args, 0, "ok\n", "")

    monkeypatch.setattr(agent_task_module, "_run", fake_run)
    assert check_task(context, metadata["task_key"], "pytest") == 0

    assert observed["args"] == [sys.executable, "-m", "pytest", "-q"]
    check_environment = observed["env"]
    assert isinstance(check_environment, dict)
    assert "DOCKER_HOST" not in check_environment
    assert check_environment["HARDWARE_BACKEND"] == "fake"
    assert check_task(context, metadata["task_key"], "reviewer-corpus") == 0
    assert observed["args"] == [sys.executable, "-m", "tools.evaluate_reviewer"]
    records = Path(metadata["state_dir"], "commands.jsonl").read_text(encoding="utf-8")
    assert '"action": "check-pytest"' in records
    assert '"action": "check-reviewer-corpus"' in records
