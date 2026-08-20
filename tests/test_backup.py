import json
import os
import stat
import subprocess
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

import tools.backup as backup_module
from tools.backup import (
    BASELINE_COUNT_SQL,
    COMMAND_TIMEOUT_SECONDS,
    MANIFEST_SCHEMA,
    MANIFEST_SCHEMA_V1,
    RESTORE_BASELINE_COMPONENTS,
    BackupConfig,
    SafeCommandError,
    SafeCommandTimeoutError,
    SubprocessRunner,
    compose_command,
    create_backup,
    host_identity,
    main,
    select_archive_components,
    verify_manifest,
)


class FakeRunner:
    def __init__(
        self,
        *,
        fail_label: str | None = None,
        interrupt_label: str | None = None,
        grafana: bool = False,
        service_statuses: Mapping[str, str] | None = None,
    ) -> None:
        self.fail_label = fail_label
        self.interrupt_label = interrupt_label
        self.grafana = grafana
        self.service_statuses = dict(
            service_statuses
            or {
                "api": "running",
                "worker": "running",
                "state-estimator-worker": "running",
                "mosquitto": "running",
            }
        )
        if grafana:
            self.service_statuses.setdefault("grafana", "running")
        self.calls: list[tuple[str, list[str]]] = []
        self.environments: dict[str, dict[str, str] | None] = {}
        self.timeouts: dict[str, float] = {}

    def _before(self, label: str, args: list[str]) -> None:
        self.calls.append((label, args))
        if label == self.interrupt_label:
            raise KeyboardInterrupt
        if label == self.fail_label:
            raise SafeCommandError(label, 9)

    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        label: str,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
    ) -> str:
        self._before(label, args)
        self.environments[label] = dict(environment) if environment is not None else None
        self.timeouts[label] = timeout_seconds
        if label == "compose_config":
            configured_services = {
                "api": {"image": "example/api@sha256:abc"},
                "worker": {"image": "example/api@sha256:abc"},
                "state-estimator-worker": {"image": "example/api@sha256:abc"},
                "mosquitto": {"image": "eclipse-mosquitto:2"},
                "postgres": {"image": "postgres:16-alpine"},
                "migrate": {"image": "example/api@sha256:abc"},
            }
            if self.grafana:
                configured_services["grafana"] = {"image": "grafana/grafana-oss:11.5.0"}
            return json.dumps(
                {
                    "name": "backup-test",
                    "services": configured_services,
                }
            )
        if label == "git_commit":
            return "a" * 40 + "\n"
        if label == "windows_acl_identity":
            return "synthetic-domain\\backup-operator\n"
        if label == "running_services":
            services = ["api", "worker", "state-estimator-worker", "mosquitto"]
            if self.grafana:
                services.append("grafana")
            return "\n".join(services) + "\n"
        if label.startswith("container:"):
            service = label.split(":", 1)[1]
            if service == "grafana" and not self.grafana:
                return ""
            return f"container-{service}\n"
        if label.startswith("container-state:"):
            service = label.split(":", 1)[1]
            status = self.service_statuses.get(service, "exited")
            return (
                json.dumps(
                    {
                        "Status": status,
                        "Running": status == "running",
                        "Restarting": status == "restarting",
                        "Paused": status == "paused",
                    }
                )
                + "\n"
            )
        if label == "alembic_revision":
            return "0008_story_environment\n"
        if label.startswith("recover-health:"):
            container_count = len(args[4:])
            return "\n".join(json.dumps({"Running": True}) for _item in range(container_count)) + "\n"
        if label == "environment_encryption":
            output = Path(args[args.index("--output") + 1])
            output.write_bytes(b"encrypted-not-plaintext")
            return ""
        if label in {
            "photo_data",
            "estimator_private_data",
            "mosquitto_data",
            "grafana_data",
        }:
            archive_arg = args[args.index("backup-archive") + 1]
            archive_name = Path(archive_arg).name
            mount = args[args.index("--mount") + 1]
            source = mount.split("src=", 1)[1].split(",dst=", 1)[0]
            (Path(source) / archive_name).write_bytes(f"archive:{label}".encode())
        return ""

    def run_to_file(
        self,
        args: list[str],
        target: Path,
        *,
        cwd: Path,
        label: str,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        self._before(label, args)
        self.environments[label] = dict(environment) if environment is not None else None
        self.timeouts[label] = timeout_seconds
        target.write_bytes(f"artifact:{label}".encode())


def config(tmp_path: Path, *, env_file: Path | None = None) -> BackupConfig:
    return BackupConfig(
        project_dir=tmp_path,
        backup_root=tmp_path / "backups",
        compose_files=(tmp_path / "docker-compose.yml", tmp_path / "docker-compose.dev.yml"),
        project_name="backup-test",
        env_file=env_file,
        age_recipient="age1testrecipient" if env_file else None,
    )


def fixed_now() -> datetime:
    return datetime(2026, 8, 11, 12, 30, tzinfo=UTC)


def test_subprocess_runner_bounds_text_and_file_commands(tmp_path: Path, monkeypatch) -> None:
    observed_timeouts: list[float] = []

    def time_out(*_args, **kwargs):
        observed_timeouts.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired(cmd=["synthetic"], timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", time_out)
    runner = SubprocessRunner()

    with pytest.raises(SafeCommandTimeoutError):
        runner.run(["synthetic"], cwd=tmp_path, label="text", timeout_seconds=2.0)
    with pytest.raises(SafeCommandTimeoutError):
        runner.run_to_file(
            ["synthetic"],
            tmp_path / "partial.bin",
            cwd=tmp_path,
            label="file",
            timeout_seconds=3.0,
        )

    assert observed_timeouts == [2.0, 3.0]


def test_compose_command_preserves_explicit_files_project_and_env(tmp_path: Path) -> None:
    env_file = tmp_path / "runtime.env"
    backup_config = config(tmp_path, env_file=env_file)

    command = compose_command(backup_config, "config", "--format", "json")

    assert command == [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(tmp_path / "docker-compose.yml"),
        "-f",
        str(tmp_path / "docker-compose.dev.yml"),
        "-p",
        "backup-test",
        "config",
        "--format",
        "json",
    ]


def test_component_selection_requires_app_data_and_marks_grafana_absent() -> None:
    selected = select_archive_components(
        {
            "api": "api-id",
            "state-estimator-worker": "estimator-id",
            "mosquitto": "mqtt-id",
            "grafana": None,
        }
    )

    assert selected["photo_data"]["required"] is True
    assert selected["estimator_private_data"]["status"] == "pending"
    assert selected["mosquitto_data"]["archive_name"] == "mosquitto_data.tar.gz"
    assert selected["grafana_data"]["status"] == "absent"
    assert selected["grafana_data"]["archive_name"] is None


def test_missing_required_component_refuses_success_before_stopping_services(tmp_path: Path) -> None:
    class MissingPhotoRunner(FakeRunner):
        def run(
            self,
            args: list[str],
            *,
            cwd: Path,
            label: str,
            environment: Mapping[str, str] | None = None,
            timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
        ) -> str:
            if label == "container:api":
                self._before(label, args)
                return ""
            return super().run(args, cwd=cwd, label=label, environment=environment)

    runner = MissingPhotoRunner()

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "failed"
    assert result["components"]["photo_data"]["status"] == "missing"
    assert not any(label.startswith("stop:") for label, _args in runner.calls)


def test_create_backup_writes_complete_manifest_and_verifies_checksums(tmp_path: Path) -> None:
    runner = FakeRunner()

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now, hostname="private-host")

    assert result["status"] == "complete"
    backup_dir = Path(result["backup_directory"])
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == MANIFEST_SCHEMA
    assert manifest["compose_project_name"] == "backup-test"
    assert manifest["git_commit"] == "a" * 40
    assert manifest["alembic_revision"] == "0008_story_environment"
    assert manifest["host_identity"]["value"] == host_identity("private-host")["value"]
    assert "private-host" not in json.dumps(manifest)
    assert manifest["components"]["grafana_data"]["status"] == "absent"
    verification = verify_manifest(backup_dir)
    assert verification["schema_version"] == "senior-pomidor.backup-verification.v1"
    assert verification["valid"] is True
    assert verification["errors"] == []


def test_manifest_v2_contains_restore_baselines_and_v1_remains_verifiable(tmp_path: Path) -> None:
    runner = FakeRunner()
    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)
    backup_dir = Path(result["backup_directory"])
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == MANIFEST_SCHEMA
    assert set(RESTORE_BASELINE_COMPONENTS) <= manifest["components"].keys()
    assert set(RESTORE_BASELINE_COMPONENTS.values()) <= {artifact["archive_name"] for artifact in manifest["artifacts"]}
    calls = dict(runner.calls)
    assert BASELINE_COUNT_SQL in calls["restore_baseline_counts"]
    for component in (
        "representative_photo_data",
        "representative_estimator_private_data",
        "representative_mosquitto_data",
    ):
        assert "sha256sum" in " ".join(calls[component])

    manifest["schema_version"] = MANIFEST_SCHEMA_V1
    for component in RESTORE_BASELINE_COMPONENTS:
        manifest["components"].pop(component)
    baseline_names = set(RESTORE_BASELINE_COMPONENTS.values())
    manifest["artifacts"] = [
        artifact for artifact in manifest["artifacts"] if artifact["archive_name"] not in baseline_names
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert verify_manifest(backup_dir)["valid"] is True


def test_create_backup_uses_packaged_revision_without_git_checkout(tmp_path: Path) -> None:
    (tmp_path / "REVISION").write_text("b" * 40 + "\n", encoding="utf-8")
    runner = FakeRunner()

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "complete"
    assert "git_commit" not in {label for label, _args in runner.calls}
    manifest = json.loads((Path(result["backup_directory"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["git_commit"] == "b" * 40


def test_invalid_packaged_revision_fails_before_stopping_services(tmp_path: Path) -> None:
    (tmp_path / "REVISION").write_text("not-a-commit\n", encoding="utf-8")
    runner = FakeRunner()

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "failed"
    assert result["failures"] == [{"kind": "backup_failed", "component": "backup", "error_type": "ValueError"}]
    assert not any(label.startswith("stop:") for label, _args in runner.calls)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not available on Windows")
def test_create_backup_uses_private_posix_permissions(tmp_path: Path) -> None:
    result = create_backup(config(tmp_path), runner=FakeRunner(), now=fixed_now)

    assert result["status"] == "complete"
    backup_dir = Path(result["backup_directory"])
    assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in backup_dir.iterdir() if path.is_file())


def test_archive_container_reads_as_root_then_assigns_private_archive_to_invoking_identity(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(backup_module, "_is_windows", lambda: False)
    monkeypatch.setattr(backup_module.os, "getuid", lambda: 1234, raising=False)
    monkeypatch.setattr(backup_module.os, "getgid", lambda: 5678, raising=False)

    command = backup_module._archive_command("container-api", "/app/data/photos", tmp_path, "photos.tar.gz")

    assert command[:3] == ["docker", "run", "--rm"]
    assert "--user" not in command
    assert 'chown "$3:$4" "$1"' in command[command.index("-c") + 1]
    assert 'chmod 600 "$1"' in command[command.index("-c") + 1]
    assert command[-2:] == ["1234", "5678"]


def test_windows_snapshot_applies_user_only_inheritable_acl_before_writes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(backup_module, "_is_windows", lambda: True)
    runner = FakeRunner()

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "complete"
    labels = [label for label, _args in runner.calls]
    assert labels.index("windows_private_acl") < labels.index("compose_config")
    acl_commands = [args for label, args in runner.calls if label == "windows_private_acl"]
    assert len(acl_commands) == 2
    assert all(
        args[2:]
        == [
            "/inheritance:r",
            "/grant:r",
            "synthetic-domain\\backup-operator:(OI)(CI)F",
            "/T",
        ]
        for args in acl_commands
    )
    file_acl_commands = [args for label, args in runner.calls if label == "windows_private_acl_files"]
    assert file_acl_commands
    assert all(
        args[2:] == ["/inheritance:r", "/grant:r", "synthetic-domain\\backup-operator:F"] for args in file_acl_commands
    )


def test_windows_acl_failure_aborts_before_collecting_private_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(backup_module, "_is_windows", lambda: True)
    runner = FakeRunner(fail_label="windows_private_acl")

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "failed"
    assert result["failures"] == [
        {"kind": "command_failed", "component": "windows_private_acl", "exit_code": 9},
    ]
    assert not any(label == "compose_config" for label, _args in runner.calls)


def test_restore_drill_uses_an_explicit_isolated_environment_file() -> None:
    operations = (Path(__file__).resolve().parents[1] / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    drill = operations.split("Restore drill (required", 1)[1].split("## Data Lifecycle Dry Run", 1)[0]

    assert "--env-file $drillEnv" in drill
    assert drill.count("--env-file $drillEnv") >= 4
    for required_setting in (
        "DATABASE_URL=postgresql+psycopg://restore_drill:",
        "POSTGRES_PASSWORD=synthetic-restore-drill-only",
        "COMPOSE_PROFILES=",
        "LAN_BIND_ADDRESS=127.0.0.1",
        "POSTGRES_BIND_ADDRESS=127.0.0.1",
        "API_PUBLISHED_PORT=0",
        "GRAFANA_CLOUD_EXPORT_ENABLED=false",
        "GRAFANA_CLOUD_REMOTE_WRITE_URL=",
        "GRAFANA_DB_PASSWORD=synthetic-restore-drill-reader-only",
        "MQTT_HOST=mosquitto",
        "MQTT_PASSWORD=",
        "TELEMETRY_UPLOAD_TOKEN=",
        '"DATABASE_URL",',
        '"COMPOSE_PROFILES",',
        '"MQTT_HOST",',
        '"DOCKER_HOST",',
        'docker context inspect --format "{{.Endpoints.docker.Host}}"',
        "Restore drill requires a local Docker engine",
    ):
        assert required_setting in drill
    assert "up -d --build migrate mosquitto api worker state-estimator-worker" in drill
    assert "up -d grafana-cloud-exporter" not in drill


def test_present_grafana_is_archived_and_marked_complete(tmp_path: Path) -> None:
    result = create_backup(config(tmp_path), runner=FakeRunner(grafana=True), now=fixed_now)

    assert result["status"] == "complete"
    backup_dir = Path(result["backup_directory"])
    assert (backup_dir / "grafana_data.tar.gz").is_file()
    assert result["components"]["grafana_data"]["status"] == "complete"


def test_external_postgres_uses_rendered_network_and_secret_free_client_argv(tmp_path: Path) -> None:
    database_url = "postgresql+psycopg://backup_user:synthetic_value@postgres:5432/backup_db?sslmode=disable"

    class ProductionRunner(FakeRunner):
        def run(
            self,
            args: list[str],
            *,
            cwd: Path,
            label: str,
            environment: Mapping[str, str] | None = None,
            timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
        ) -> str:
            if label == "compose_config":
                self._before(label, args)
                return json.dumps(
                    {
                        "name": "backup-production-test",
                        "services": {
                            "migrate": {"environment": {"DATABASE_URL": database_url}},
                            "api": {"image": "example/api@sha256:abc"},
                            "worker": {"image": "example/api@sha256:abc"},
                            "state-estimator-worker": {"image": "example/api@sha256:abc"},
                            "mosquitto": {"image": "eclipse-mosquitto:2"},
                        },
                        "networks": {"default": {"name": "synthetic-platform-network"}},
                    }
                )
            return super().run(args, cwd=cwd, label=label, environment=environment)

    runner = ProductionRunner()

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "complete"
    assert database_url not in json.dumps(result)
    assert result["components"]["grafana_data"]["status"] == "absent"
    assert "container:grafana" not in {label for label, _args in runner.calls}
    for label in ("database", "database_globals_audit", "alembic_revision"):
        args = next(args for call_label, args in runner.calls if call_label == label)
        assert args[:5] == [
            "docker",
            "run",
            "--rm",
            "--network",
            "synthetic-platform-network",
        ]
        assert database_url not in args
        assert args[args.index("postgres:16-alpine")] == "postgres:16-alpine"
        assert runner.environments[label] == {
            "PGHOST": "postgres",
            "PGPORT": "5432",
            "PGUSER": "backup_user",
            "PGPASSWORD": "synthetic_value",
            "PGDATABASE": "backup_db",
            "PGSSLMODE": "disable",
        }


def test_external_postgres_rejects_unsupported_uri_query_parameters() -> None:
    with pytest.raises(ValueError, match="unsupported query parameter"):
        backup_module._external_postgres_client(
            {
                "services": {
                    "migrate": {
                        "environment": {
                            "DATABASE_URL": "postgresql://user:pass@db:5432/name?sslmode=disable&search_path=public"
                        }
                    }
                },
                "networks": {"default": {"name": "synthetic-network"}},
            }
        )


def test_external_postgres_configuration_failure_is_bounded_before_stopping_writers(tmp_path: Path) -> None:
    class MissingDatabaseConfigRunner(FakeRunner):
        def run(
            self,
            args: list[str],
            *,
            cwd: Path,
            label: str,
            environment: Mapping[str, str] | None = None,
            timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
        ) -> str:
            if label == "compose_config":
                self._before(label, args)
                return json.dumps(
                    {
                        "name": "backup-production-test",
                        "services": {
                            "migrate": {"environment": {}},
                            "api": {"image": "example/api@sha256:abc"},
                            "worker": {"image": "example/api@sha256:abc"},
                            "state-estimator-worker": {"image": "example/api@sha256:abc"},
                            "mosquitto": {"image": "eclipse-mosquitto:2"},
                        },
                        "networks": {"default": {"name": "synthetic-platform-network"}},
                    }
                )
            return super().run(args, cwd=cwd, label=label, environment=environment)

    runner = MissingDatabaseConfigRunner()

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "failed"
    assert result["failures"] == [{"kind": "backup_failed", "component": "backup", "error_type": "ValueError"}]
    assert result["service_recovery"] == []
    assert not any(label.startswith("stop:") for label, _args in runner.calls)


def test_manifest_verification_detects_corrupted_artifact(tmp_path: Path) -> None:
    result = create_backup(config(tmp_path), runner=FakeRunner(), now=fixed_now)
    backup_dir = Path(result["backup_directory"])
    with (backup_dir / "database.dump").open("ab") as output:
        output.write(b"corruption")

    verification = verify_manifest(backup_dir)

    assert verification["valid"] is False
    assert verification["errors"] == [{"artifact": "database.dump", "reason": "size_mismatch"}]


def test_partial_failure_recovers_every_service_that_was_stopped(tmp_path: Path) -> None:
    runner = FakeRunner(fail_label="photo_data")

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "failed"
    assert result["failures"] == [{"kind": "command_failed", "component": "photo_data", "exit_code": 9}]
    assert {item["service"] for item in result["service_recovery"]} == {
        "api",
        "worker",
        "state-estimator-worker",
        "mosquitto",
    }
    assert all(item["status"] == "recovered" for item in result["service_recovery"])
    assert not (Path(result["backup_directory"]) / "manifest.json").exists()


def test_database_timeout_uses_failure_and_recovery_flow(tmp_path: Path) -> None:
    class TimeoutRunner(FakeRunner):
        def run_to_file(
            self,
            args: list[str],
            target: Path,
            *,
            cwd: Path,
            label: str,
            environment: Mapping[str, str] | None = None,
            timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
        ) -> None:
            if label == "database":
                self._before(label, args)
                raise SafeCommandTimeoutError(label)
            super().run_to_file(
                args,
                target,
                cwd=cwd,
                label=label,
                environment=environment,
                timeout_seconds=timeout_seconds,
            )

    result = create_backup(config(tmp_path), runner=TimeoutRunner(), now=fixed_now)

    assert result["status"] == "failed"
    assert result["failures"] == [{"kind": "command_timeout", "component": "database"}]
    assert all(item["status"] == "recovered" for item in result["service_recovery"])


def test_recovery_requires_bounded_running_or_healthy_state(tmp_path: Path, monkeypatch) -> None:
    class UnhealthyRecoveryRunner(FakeRunner):
        def run(
            self,
            args: list[str],
            *,
            cwd: Path,
            label: str,
            environment: Mapping[str, str] | None = None,
            timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
        ) -> str:
            if label == "recover-health:api":
                self._before(label, args)
                self.timeouts[label] = timeout_seconds
                return json.dumps({"Running": False}) + "\n"
            return super().run(
                args,
                cwd=cwd,
                label=label,
                environment=environment,
                timeout_seconds=timeout_seconds,
            )

    monotonic_values = iter((0.0, 61.0))
    monkeypatch.setattr(backup_module.time, "monotonic", lambda: next(monotonic_values))
    runner = UnhealthyRecoveryRunner(service_statuses={"api": "running"})

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "failed"
    assert result["failures"] == [{"kind": "command_timeout", "component": "recover-health:api"}]
    assert result["service_recovery"] == [{"service": "api", "status": "failed", "failure": result["failures"][0]}]
    assert runner.timeouts["recover:api"] == backup_module.RECOVERY_COMMAND_TIMEOUT_SECONDS
    assert runner.timeouts["recover-health:api"] == backup_module.RECOVERY_COMMAND_TIMEOUT_SECONDS


def test_recovery_failure_is_reported_and_prevents_success(tmp_path: Path) -> None:
    runner = FakeRunner(fail_label="recover:api")

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "failed"
    assert result["failures"] == [{"kind": "command_failed", "component": "recover:api", "exit_code": 9}]
    expected_recovery = {"service": "api", "status": "failed", "failure": result["failures"][0]}
    assert expected_recovery in result["service_recovery"]


def test_active_migration_refuses_snapshot_without_stopping_any_service(tmp_path: Path) -> None:
    runner = FakeRunner(service_statuses={"migrate": "restarting"})

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "failed"
    assert not any(label.startswith("stop:") for label, _args in runner.calls)


def test_restarting_writer_is_stopped_before_snapshot_commands(tmp_path: Path) -> None:
    runner = FakeRunner(service_statuses={"worker": "restarting"})

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "complete"
    labels = [label for label, _args in runner.calls]
    assert labels.index("stop:worker") < labels.index("restore_baseline_counts")
    assert result["service_recovery"] == [{"service": "worker", "status": "recovered"}]


def test_stop_failure_recovers_services_stopped_before_the_failure(tmp_path: Path) -> None:
    runner = FakeRunner(fail_label="stop:worker")

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "failed"
    assert result["service_recovery"] == [
        {"service": "api", "status": "recovered"},
        {"service": "worker", "status": "recovered"},
    ]


def test_interruption_after_stop_starts_exact_existing_containers_without_compose_up(tmp_path: Path) -> None:
    class StopThenInterruptRunner(FakeRunner):
        def run(
            self,
            args: list[str],
            *,
            cwd: Path,
            label: str,
            environment: Mapping[str, str] | None = None,
            timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
        ) -> str:
            if label == "stop:worker":
                self.calls.append((label, args))
                raise KeyboardInterrupt
            return super().run(args, cwd=cwd, label=label, environment=environment)

    runner = StopThenInterruptRunner()

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "failed"
    assert result["failures"] == [{"kind": "interrupted", "component": "backup"}]
    recovery_calls = {label: args for label, args in runner.calls if label.startswith("recover:")}
    assert recovery_calls == {
        "recover:api": ["docker", "start", "container-api"],
        "recover:worker": ["docker", "start", "container-worker"],
    }
    assert not any("up" in args for args in recovery_calls.values())


def test_recovery_starts_only_replicas_that_were_active_before_backup(tmp_path: Path) -> None:
    class ScaledWriterRunner(FakeRunner):
        def run(
            self,
            args: list[str],
            *,
            cwd: Path,
            label: str,
            environment: Mapping[str, str] | None = None,
            timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
        ) -> str:
            if label == "container:worker":
                self._before(label, args)
                return "worker-active\nworker-exited\n"
            if label == "container-state:worker":
                self._before(label, args)
                return (
                    "\n".join(
                        (
                            json.dumps({"Status": "running", "Running": True}),
                            json.dumps({"Status": "exited", "Running": False}),
                        )
                    )
                    + "\n"
                )
            return super().run(
                args,
                cwd=cwd,
                label=label,
                environment=environment,
                timeout_seconds=timeout_seconds,
            )

    runner = ScaledWriterRunner()

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "complete"
    recovery_calls = {label: args for label, args in runner.calls if label.startswith("recover:")}
    assert recovery_calls["recover:worker"] == ["docker", "start", "worker-active"]
    assert "worker-exited" not in recovery_calls["recover:worker"]


def test_interruption_during_database_dump_still_recovers_services(tmp_path: Path) -> None:
    runner = FakeRunner(interrupt_label="database")

    result = create_backup(config(tmp_path), runner=runner, now=fixed_now)

    assert result["status"] == "failed"
    assert result["failures"] == [{"kind": "interrupted", "component": "backup"}]
    assert all(item["status"] == "recovered" for item in result["service_recovery"])


def test_environment_is_only_persisted_as_encrypted_artifact(tmp_path: Path) -> None:
    env_file = tmp_path / "runtime.env"
    env_file.write_text("POSTGRES_PASSWORD=do-not-expose\n", encoding="utf-8")

    result = create_backup(config(tmp_path, env_file=env_file), runner=FakeRunner(), now=fixed_now)

    rendered = json.dumps(result)
    backup_dir = Path(result["backup_directory"])
    assert result["status"] == "complete"
    assert (backup_dir / "environment.age").read_bytes() == b"encrypted-not-plaintext"
    assert not (backup_dir / env_file.name).exists()
    assert "do-not-expose" not in rendered


def test_command_failure_does_not_copy_subprocess_output_into_json(tmp_path: Path) -> None:
    class SecretFailureRunner(FakeRunner):
        def run_to_file(
            self,
            args: list[str],
            target: Path,
            *,
            cwd: Path,
            label: str,
            environment: Mapping[str, str] | None = None,
            timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
        ) -> None:
            if label == "database":
                raise SafeCommandError(label, 1)
            super().run_to_file(args, target, cwd=cwd, label=label, environment=environment)

    result = create_backup(config(tmp_path), runner=SecretFailureRunner(), now=fixed_now)

    assert "POSTGRES_PASSWORD" not in json.dumps(result)
    assert result["failures"][0] == {"kind": "command_failed", "component": "database", "exit_code": 1}


def test_non_object_manifest_is_rejected_without_exception(tmp_path: Path) -> None:
    backup_dir = tmp_path / "snapshot"
    backup_dir.mkdir()
    (backup_dir / "manifest.json").write_text("[]\n", encoding="utf-8")

    verification = verify_manifest(backup_dir)

    assert verification == {
        "schema_version": "senior-pomidor.backup-verification.v1",
        "valid": False,
        "errors": [{"artifact": "manifest.json", "reason": "invalid_manifest"}],
    }


def test_invalid_utf8_manifest_is_rejected_without_exception(tmp_path: Path) -> None:
    backup_dir = tmp_path / "snapshot"
    backup_dir.mkdir()
    (backup_dir / "manifest.json").write_bytes(b"{\xff}")

    verification = verify_manifest(backup_dir)

    assert verification == {
        "schema_version": "senior-pomidor.backup-verification.v1",
        "valid": False,
        "errors": [{"artifact": "manifest.json", "reason": "unreadable_manifest"}],
    }


def test_cli_invalid_utf8_manifest_returns_bounded_json(tmp_path: Path, capsys) -> None:
    backup_dir = tmp_path / "snapshot"
    backup_dir.mkdir()
    (backup_dir / "manifest.json").write_bytes(b"{\xff}")

    return_code = main(["--verify", str(backup_dir), "--json"])

    captured = capsys.readouterr()
    assert return_code == 1
    assert json.loads(captured.out) == {
        "schema_version": "senior-pomidor.backup-verification.v1",
        "valid": False,
        "errors": [{"artifact": "manifest.json", "reason": "unreadable_manifest"}],
    }
    assert captured.err == ""


def test_manifest_rejects_reused_artifact_for_required_components(tmp_path: Path) -> None:
    result = create_backup(config(tmp_path), runner=FakeRunner(), now=fixed_now)
    backup_dir = Path(result["backup_directory"])
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    database_artifact = next(
        artifact for artifact in manifest["artifacts"] if artifact["archive_name"] == "database.dump"
    )
    for component in (
        "database",
        "database_globals_audit",
        "photo_data",
        "estimator_private_data",
        "mosquitto_data",
    ):
        manifest["components"][component]["archive_name"] = "database.dump"
    manifest["artifacts"] = [database_artifact]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    verification = verify_manifest(backup_dir)

    assert verification["valid"] is False
    assert {
        "artifact": "database_globals_audit",
        "reason": "component_artifact_name_mismatch",
    } in verification["errors"]
    assert {"artifact": "photo_data", "reason": "component_artifact_reused"} in verification["errors"]


def test_manifest_rejects_empty_artifact_even_with_matching_checksum(tmp_path: Path) -> None:
    result = create_backup(config(tmp_path), runner=FakeRunner(), now=fixed_now)
    backup_dir = Path(result["backup_directory"])
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    database_artifact = next(
        artifact for artifact in manifest["artifacts"] if artifact["archive_name"] == "database.dump"
    )
    (backup_dir / "database.dump").write_bytes(b"")
    database_artifact["size_bytes"] = 0
    database_artifact["sha256"] = backup_module.sha256_file(backup_dir / "database.dump")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    verification = verify_manifest(backup_dir)

    assert verification["valid"] is False
    assert {"artifact": "database.dump", "reason": "invalid_artifact_record"} in verification["errors"]


@pytest.mark.parametrize(("field", "corrupted_value"), [("size_bytes", 999), ("sha256", "0" * 64)])
def test_manifest_rejects_component_metadata_that_disagrees_with_artifact_record(
    tmp_path: Path,
    field: str,
    corrupted_value: int | str,
) -> None:
    result = create_backup(config(tmp_path), runner=FakeRunner(), now=fixed_now)
    backup_dir = Path(result["backup_directory"])
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["components"]["database"][field] = corrupted_value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    verification = verify_manifest(backup_dir)

    assert verification["valid"] is False
    assert {
        "artifact": "database",
        "reason": "component_artifact_metadata_mismatch",
    } in verification["errors"]


def test_manifest_rejects_missing_or_malformed_provenance_and_recovery_metadata(tmp_path: Path) -> None:
    result = create_backup(config(tmp_path), runner=FakeRunner(), now=fixed_now)
    backup_dir = Path(result["backup_directory"])
    manifest_path = backup_dir / "manifest.json"
    original = json.loads(manifest_path.read_text(encoding="utf-8"))
    invalid_values = {
        "created_at_utc": None,
        "host_identity": {"kind": "sha256_hostname", "value": "short"},
        "git_commit": "not-a-commit",
        "compose_project_name": "",
        "image_references": {},
        "alembic_revision": "",
        "service_recovery": [{"service": "api", "status": "failed"}],
    }

    for field, invalid_value in invalid_values.items():
        manifest = deepcopy(original)
        if invalid_value is None:
            manifest.pop(field)
        else:
            manifest[field] = invalid_value
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        verification = verify_manifest(backup_dir)

        assert verification["valid"] is False, field
        assert {"artifact": "manifest.json", "reason": f"invalid_{field}"} in verification["errors"]


def test_unreadable_artifact_is_bounded_verification_failure(tmp_path: Path, monkeypatch) -> None:
    result = create_backup(config(tmp_path), runner=FakeRunner(), now=fixed_now)
    backup_dir = Path(result["backup_directory"])
    original_sha256 = backup_module.sha256_file

    def fail_artifact_read(path: Path) -> str:
        if path.name == "database.dump":
            raise PermissionError("synthetic access denial")
        return original_sha256(path)

    monkeypatch.setattr(backup_module, "sha256_file", fail_artifact_read)

    verification = verify_manifest(backup_dir)

    assert verification["valid"] is False
    assert {"artifact": "database.dump", "reason": "unreadable"} in verification["errors"]
    assert "synthetic access denial" not in json.dumps(verification)


def test_backup_root_creation_failure_returns_bounded_result(tmp_path: Path) -> None:
    backup_root = tmp_path / "not-a-directory"
    backup_root.write_text("occupied", encoding="utf-8")
    backup_config = BackupConfig(
        project_dir=tmp_path,
        backup_root=backup_root,
        compose_files=(tmp_path / "docker-compose.yml",),
    )

    result = create_backup(backup_config, runner=FakeRunner(), now=fixed_now)

    assert result["status"] == "failed"
    assert result["failures"][0]["kind"] == "backup_failed"
    assert result["failures"][0]["component"] == "backup"
    assert result["failures"][0]["error_type"] in {"FileExistsError", "NotADirectoryError"}
    assert result["service_recovery"] == []


def test_cli_backup_root_failure_returns_nonzero_without_traceback(tmp_path: Path, capsys) -> None:
    backup_root = tmp_path / "not-a-directory"
    backup_root.write_text("occupied", encoding="utf-8")

    return_code = main(["--backup-root", str(backup_root), "--json"])

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert return_code == 1
    assert result["status"] == "failed"
    assert result["failures"][0]["error_type"] in {"FileExistsError", "NotADirectoryError"}
    assert captured.err == ""


def test_manifest_write_failure_is_bounded_after_service_recovery(tmp_path: Path, monkeypatch) -> None:
    original_write_text = Path.write_text

    def fail_manifest_write(path: Path, data: str, *args, **kwargs) -> int:
        if path.name == "manifest.json":
            raise PermissionError("synthetic manifest denial")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_manifest_write)

    result = create_backup(config(tmp_path), runner=FakeRunner(), now=fixed_now)

    assert result["status"] == "failed"
    assert result["failures"] == [{"kind": "backup_failed", "component": "backup", "error_type": "PermissionError"}]
    assert {item["service"] for item in result["service_recovery"]} == {
        "api",
        "worker",
        "state-estimator-worker",
        "mosquitto",
    }
    assert "synthetic manifest denial" not in json.dumps(result)


def test_permission_enforcement_failure_is_bounded_after_service_recovery(tmp_path: Path, monkeypatch) -> None:
    def fail_file_permissions(_path: Path) -> None:
        raise PermissionError("synthetic permission denial")

    monkeypatch.setattr(backup_module, "_make_backup_files_private", fail_file_permissions)

    result = create_backup(config(tmp_path), runner=FakeRunner(), now=fixed_now)

    assert result["status"] == "failed"
    assert result["failures"] == [{"kind": "backup_failed", "component": "backup", "error_type": "PermissionError"}]
    assert all(item["status"] == "recovered" for item in result["service_recovery"])
    assert "synthetic permission denial" not in json.dumps(result)
