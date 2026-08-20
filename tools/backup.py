from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import signal
import stat
import subprocess  # nosec B404
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urlsplit

MANIFEST_SCHEMA_V1 = "senior-pomidor.backup-manifest.v1"
MANIFEST_SCHEMA = "senior-pomidor.backup-manifest.v2"
RESULT_SCHEMA = "senior-pomidor.backup-result.v1"
VERIFY_RESULT_SCHEMA = "senior-pomidor.backup-verification.v1"
ALPINE_IMAGE = "alpine:3.22"
POSTGRES_CLIENT_IMAGE = "postgres:16-alpine"
COMMAND_TIMEOUT_SECONDS = 900.0
RECOVERY_COMMAND_TIMEOUT_SECONDS = 30.0
RECOVERY_HEALTH_TIMEOUT_SECONDS = 60.0
RECOVERY_POLL_INTERVAL_SECONDS = 1.0
WRITER_SERVICES = (
    "api",
    "worker",
    "state-estimator-worker",
    "daily-story-worker",
    "grafana-cloud-exporter",
    "grafana",
    "mosquitto",
)
RECOVERY_ORDER = (
    "mosquitto",
    "grafana",
    "api",
    "worker",
    "state-estimator-worker",
    "daily-story-worker",
    "grafana-cloud-exporter",
)
ARCHIVE_COMPONENTS = {
    "photo_data": ("api", "/app/data/photos", "photo_data.tar.gz"),
    "estimator_private_data": (
        "state-estimator-worker",
        "/app/data/private",
        "estimator_private_data.tar.gz",
    ),
    "mosquitto_data": ("mosquitto", "/mosquitto/data", "mosquitto_data.tar.gz"),
    "grafana_data": ("grafana", "/var/lib/grafana", "grafana_data.tar.gz"),
}
V1_COMPONENT_ARTIFACT_NAMES = {
    "database": "database.dump",
    "database_globals_audit": "globals-audit.sql",
    "photo_data": "photo_data.tar.gz",
    "estimator_private_data": "estimator_private_data.tar.gz",
    "mosquitto_data": "mosquitto_data.tar.gz",
    "grafana_data": "grafana_data.tar.gz",
    "environment": "environment.age",
}
RESTORE_BASELINE_COMPONENTS = {
    "restore_baseline_counts": "baseline-counts.csv",
    "representative_photo_data": "representative-photo-sha256.txt",
    "representative_estimator_private_data": "representative-estimator-private-sha256.txt",
    "representative_mosquitto_data": "representative-mosquitto-sha256.txt",
}
REPRESENTATIVE_COMPONENTS = {
    "photo_data": "representative_photo_data",
    "estimator_private_data": "representative_estimator_private_data",
    "mosquitto_data": "representative_mosquitto_data",
}
COMPONENT_ARTIFACT_NAMES = {**V1_COMPONENT_ARTIFACT_NAMES, **RESTORE_BASELINE_COMPONENTS}
BASELINE_COUNT_SQL = """SELECT 'telemetry_events', count(*) FROM telemetry_events
UNION ALL SELECT 'pod_readings', count(*) FROM pod_readings
UNION ALL SELECT 'photos', count(*) FROM photos
UNION ALL SELECT 'state_snapshots', count(*) FROM state_snapshots
UNION ALL SELECT 'sensor_health_snapshots', count(*) FROM sensor_health_snapshots
UNION ALL SELECT 'anomaly_records', count(*) FROM anomaly_records
UNION ALL SELECT 'estimator_diagnostics', count(*) FROM estimator_diagnostics
ORDER BY 1"""


class SafeCommandError(RuntimeError):
    def __init__(self, label: str, returncode: int) -> None:
        super().__init__(f"{label} failed with exit code {returncode}")
        self.label = label
        self.returncode = returncode


class SafeCommandTimeoutError(RuntimeError):
    def __init__(self, label: str) -> None:
        super().__init__(f"{label} exceeded its time limit")
        self.label = label


class CommandRunner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        label: str,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
    ) -> str: ...

    def run_to_file(
        self,
        args: list[str],
        target: Path,
        *,
        cwd: Path,
        label: str,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
    ) -> None: ...


class SubprocessRunner:
    @staticmethod
    def _environment(overrides: Mapping[str, str] | None) -> dict[str, str] | None:
        if overrides is None:
            return None
        environment = os.environ.copy()
        environment.update(overrides)
        return environment

    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        label: str,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
    ) -> str:
        try:
            completed = subprocess.run(  # nosec B603
                args,
                cwd=cwd,
                env=self._environment(environment),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise SafeCommandTimeoutError(label) from None
        if completed.returncode != 0:
            raise SafeCommandError(label, completed.returncode)
        return completed.stdout

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
        with target.open("wb") as output:
            try:
                completed = subprocess.run(  # nosec B603
                    args,
                    cwd=cwd,
                    env=self._environment(environment),
                    stdout=output,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                raise SafeCommandTimeoutError(label) from None
        if completed.returncode != 0:
            raise SafeCommandError(label, completed.returncode)


@dataclass(frozen=True)
class BackupConfig:
    project_dir: Path
    backup_root: Path
    compose_files: tuple[Path, ...]
    project_name: str | None = None
    env_file: Path | None = None
    age_recipient: str | None = None


def format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compose_command(config: BackupConfig, *args: str) -> list[str]:
    command = ["docker", "compose"]
    if config.env_file is not None:
        command.extend(("--env-file", str(config.env_file)))
    for compose_file in config.compose_files:
        command.extend(("-f", str(compose_file)))
    if config.project_name:
        command.extend(("-p", config.project_name))
    command.extend(args)
    return command


def parse_compose_config(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("services"), dict):
        raise ValueError("Compose config is not a JSON object with services")
    return payload


def configured_images(compose_config: dict[str, Any]) -> dict[str, str]:
    images: dict[str, str] = {}
    for service, value in sorted(compose_config["services"].items()):
        if isinstance(value, dict) and isinstance(value.get("image"), str):
            images[str(service)] = value["image"]
    return images


def source_revision(project_dir: Path, runner: CommandRunner) -> str:
    revision_path = project_dir / "REVISION"
    if revision_path.exists():
        if revision_path.is_symlink() or not revision_path.is_file():
            raise ValueError("REVISION must be a regular file")
        revision = revision_path.read_text(encoding="utf-8").strip()
    else:
        revision = runner.run(["git", "rev-parse", "HEAD"], cwd=project_dir, label="git_commit").strip()
    if len(revision) != 40 or any(char not in "0123456789abcdefABCDEF" for char in revision):
        raise ValueError("source revision is not a full Git commit")
    return revision


def _external_postgres_client(compose_config: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    database_url: str | None = None
    for service_name in ("migrate", "api"):
        service = compose_config["services"].get(service_name)
        service_environment = service.get("environment") if isinstance(service, dict) else None
        candidate = service_environment.get("DATABASE_URL") if isinstance(service_environment, dict) else None
        if isinstance(candidate, str) and candidate:
            database_url = candidate
            break
    if database_url is None or "\x00" in database_url or "\n" in database_url or "\r" in database_url:
        raise ValueError("rendered Compose configuration has no safe DATABASE_URL")
    if database_url.startswith("postgresql+psycopg://"):
        database_url = "postgresql://" + database_url.removeprefix("postgresql+psycopg://")
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("DATABASE_URL is not a PostgreSQL connection URI")

    try:
        parsed = urlsplit(database_url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("DATABASE_URL has invalid connection details") from exc
    database_name = unquote(parsed.path.removeprefix("/"))
    username = unquote(parsed.username) if parsed.username is not None else ""
    if not host or not database_name or not username:
        raise ValueError("DATABASE_URL must include host, database, and user")

    environment = {
        "PGHOST": host,
        "PGUSER": username,
        "PGDATABASE": database_name,
    }
    if port is not None:
        environment["PGPORT"] = str(port)
    if parsed.password is not None:
        environment["PGPASSWORD"] = unquote(parsed.password)

    query_environment = {
        "sslmode": "PGSSLMODE",
        "sslrootcert": "PGSSLROOTCERT",
        "sslcert": "PGSSLCERT",
        "sslkey": "PGSSLKEY",
        "connect_timeout": "PGCONNECT_TIMEOUT",
        "application_name": "PGAPPNAME",
        "gssencmode": "PGGSSENCMODE",
        "channel_binding": "PGCHANNELBINDING",
    }
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        target = query_environment.get(key)
        if target is None or len(values) != 1:
            raise ValueError(f"DATABASE_URL has unsupported query parameter: {key}")
        environment[target] = values[0]

    networks = compose_config.get("networks")
    default_network = networks.get("default") if isinstance(networks, dict) else None
    network_name = default_network.get("name") if isinstance(default_network, dict) else None
    if not isinstance(network_name, str) or not network_name or any(char in network_name for char in "\x00\r\n"):
        raise ValueError("rendered Compose configuration has no safe default network")

    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        network_name,
    ]
    for key in environment:
        command.extend(("-e", key))
    command.append(POSTGRES_CLIENT_IMAGE)
    return command, environment


def host_identity(hostname: str | None = None) -> dict[str, str]:
    private_name = hostname if hostname is not None else platform.node()
    return {
        "kind": "sha256_hostname",
        "value": hashlib.sha256(private_name.encode("utf-8")).hexdigest(),
        "system": platform.system().lower() or "unknown",
        "machine": platform.machine().lower() or "unknown",
    }


def select_archive_components(container_ids: dict[str, str | None]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for component, (service, target, archive) in ARCHIVE_COMPONENTS.items():
        container_id = container_ids.get(service)
        optional = component == "grafana_data"
        selected[component] = {
            "service": service,
            "container_id": container_id,
            "container_path": target,
            "archive_name": archive if container_id else None,
            "required": not optional,
            "status": "pending" if container_id else ("absent" if optional else "missing"),
        }
    return selected


def artifact_record(path: Path) -> dict[str, Any]:
    return {"archive_name": path.name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _is_bounded_text(value: Any, *, maximum: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= maximum and not any(char in value for char in "\x00\r\n")


def _is_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.utcoffset() == UTC.utcoffset(parsed)


def _manifest_metadata_errors(manifest: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    def reject(field: str) -> None:
        errors.append({"artifact": "manifest.json", "reason": f"invalid_{field}"})

    if not _is_utc_timestamp(manifest.get("created_at_utc")):
        reject("created_at_utc")
    host = manifest.get("host_identity")
    if not (
        isinstance(host, dict)
        and host.get("kind") == "sha256_hostname"
        and isinstance(host.get("value"), str)
        and len(host["value"]) == 64
        and all(char in "0123456789abcdef" for char in host["value"])
        and _is_bounded_text(host.get("system"), maximum=100)
        and _is_bounded_text(host.get("machine"), maximum=100)
    ):
        reject("host_identity")
    git_commit = manifest.get("git_commit")
    if not (
        isinstance(git_commit, str)
        and len(git_commit) == 40
        and all(char in "0123456789abcdefABCDEF" for char in git_commit)
    ):
        reject("git_commit")
    if not _is_bounded_text(manifest.get("compose_project_name"), maximum=180):
        reject("compose_project_name")
    images = manifest.get("image_references")
    if (
        not isinstance(images, dict)
        or not images
        or not all(
            _is_bounded_text(name, maximum=180) and _is_bounded_text(reference, maximum=500)
            for name, reference in images.items()
        )
    ):
        reject("image_references")
    if not _is_bounded_text(manifest.get("alembic_revision"), maximum=180):
        reject("alembic_revision")
    recovery = manifest.get("service_recovery")
    seen_services: set[str] = set()
    if not isinstance(recovery, list):
        valid_recovery = False
    else:
        valid_recovery = True
        for item in recovery:
            service = item.get("service") if isinstance(item, dict) else None
            if (
                not isinstance(item, dict)
                or not isinstance(service, str)
                or not _is_bounded_text(service, maximum=100)
                or item.get("status") != "recovered"
                or service in seen_services
            ):
                valid_recovery = False
                break
            seen_services.add(service)
    if not valid_recovery:
        reject("service_recovery")
    return errors


def verify_manifest(backup_dir: Path) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    manifest_path = backup_dir / "manifest.json"
    try:
        if manifest_path.is_symlink():
            raise OSError("manifest symlinks are not supported")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {
            "schema_version": VERIFY_RESULT_SCHEMA,
            "valid": False,
            "errors": [{"artifact": "manifest.json", "reason": "unreadable_manifest"}],
        }
    if not isinstance(manifest, dict):
        return {
            "schema_version": VERIFY_RESULT_SCHEMA,
            "valid": False,
            "errors": [{"artifact": "manifest.json", "reason": "invalid_manifest"}],
        }
    schema_version = manifest.get("schema_version")
    if schema_version not in {MANIFEST_SCHEMA_V1, MANIFEST_SCHEMA}:
        errors.append({"artifact": "manifest.json", "reason": "unsupported_schema"})
    expected_component_names = (
        COMPONENT_ARTIFACT_NAMES if schema_version == MANIFEST_SCHEMA else V1_COMPONENT_ARTIFACT_NAMES
    )
    errors.extend(_manifest_metadata_errors(manifest))
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append({"artifact": "manifest.json", "reason": "invalid_artifact_list"})
        artifacts = []
    components = manifest.get("components")
    required_components = [
        "database",
        "database_globals_audit",
        "photo_data",
        "estimator_private_data",
        "mosquitto_data",
    ]
    if schema_version == MANIFEST_SCHEMA:
        required_components.extend(RESTORE_BASELINE_COMPONENTS)
    if not isinstance(components, dict):
        errors.append({"artifact": "manifest.json", "reason": "invalid_components"})
        components = {}
    for component in sorted(set(components) - expected_component_names.keys()):
        errors.append({"artifact": str(component), "reason": "unexpected_component"})
    for component in required_components:
        value = components.get(component)
        if not isinstance(value, dict) or value.get("status") != "complete":
            errors.append({"artifact": component, "reason": "required_component_incomplete"})
    grafana = components.get("grafana_data")
    if (
        not isinstance(grafana, dict)
        or grafana.get("status") not in {"complete", "absent"}
        or (grafana.get("status") == "absent" and grafana.get("archive_name") is not None)
    ):
        errors.append({"artifact": "grafana_data", "reason": "invalid_optional_component_status"})
    environment = components.get("environment")
    if (
        not isinstance(environment, dict)
        or environment.get("status") not in {"complete", "not_configured"}
        or (environment.get("status") == "not_configured" and environment.get("archive_name") is not None)
    ):
        errors.append({"artifact": "environment", "reason": "invalid_optional_component_status"})
    artifact_names: set[str] = set()
    artifacts_by_name: dict[str, dict[str, Any]] = {}
    duplicate_artifact_names: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        name = artifact.get("archive_name")
        if not isinstance(name, str):
            continue
        if name in artifact_names:
            duplicate_artifact_names.add(name)
        artifact_names.add(name)
        artifacts_by_name.setdefault(name, artifact)
    for name in sorted(duplicate_artifact_names):
        errors.append({"artifact": name, "reason": "duplicate_artifact_record"})

    component_artifact_names: dict[str, str] = {}
    for component, value in components.items():
        if not isinstance(value, dict) or value.get("status") != "complete":
            continue
        archive_name = value.get("archive_name")
        expected_name = expected_component_names.get(str(component))
        if expected_name is None or archive_name != expected_name:
            errors.append({"artifact": str(component), "reason": "component_artifact_name_mismatch"})
        if not isinstance(archive_name, str) or archive_name not in artifact_names:
            errors.append({"artifact": str(component), "reason": "component_artifact_unlisted"})
            continue
        artifact = artifacts_by_name[archive_name]
        if value.get("size_bytes") != artifact.get("size_bytes") or value.get("sha256") != artifact.get("sha256"):
            errors.append({"artifact": str(component), "reason": "component_artifact_metadata_mismatch"})
        previous_component = component_artifact_names.get(archive_name)
        if previous_component is not None:
            errors.append({"artifact": str(component), "reason": "component_artifact_reused"})
        else:
            component_artifact_names[archive_name] = str(component)
    for name in sorted(artifact_names - component_artifact_names.keys()):
        errors.append({"artifact": name, "reason": "artifact_component_unlisted"})
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            errors.append({"artifact": "manifest.json", "reason": "invalid_artifact_record"})
            continue
        name = artifact.get("archive_name")
        if not isinstance(name, str) or Path(name).name != name:
            errors.append({"artifact": "manifest.json", "reason": "unsafe_artifact_name"})
            continue
        size_bytes = artifact.get("size_bytes")
        checksum = artifact.get("sha256")
        if (
            not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes <= 0
            or not isinstance(checksum, str)
            or len(checksum) != 64
            or any(char not in "0123456789abcdef" for char in checksum)
        ):
            errors.append({"artifact": name, "reason": "invalid_artifact_record"})
            continue
        path = backup_dir / name
        try:
            if path.is_symlink():
                errors.append({"artifact": name, "reason": "unsafe_artifact"})
                continue
            if not path.is_file():
                errors.append({"artifact": name, "reason": "missing"})
                continue
            if path.stat().st_size != size_bytes:
                errors.append({"artifact": name, "reason": "size_mismatch"})
                continue
            if sha256_file(path) != checksum:
                errors.append({"artifact": name, "reason": "checksum_mismatch"})
        except OSError:
            errors.append({"artifact": name, "reason": "unreadable"})
    return {"schema_version": VERIFY_RESULT_SCHEMA, "valid": not errors, "errors": errors}


def _safe_failure(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, SafeCommandTimeoutError):
        return {"kind": "command_timeout", "component": exc.label}
    if isinstance(exc, SafeCommandError):
        return {"kind": "command_failed", "component": exc.label, "exit_code": exc.returncode}
    if isinstance(exc, KeyboardInterrupt):
        return {"kind": "interrupted", "component": "backup"}
    return {"kind": "backup_failed", "component": "backup", "error_type": type(exc).__name__}


def _is_windows() -> bool:
    return os.name == "nt"


def _archive_owner_args() -> list[str]:
    if _is_windows():
        return []
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return []
    return [str(getuid()), str(getgid())]


def _archive_command(container_id: str, container_path: str, staging: Path, archive_name: str) -> list[str]:
    resolved = str(staging.resolve()).replace("\\", "/")
    if "," in resolved:
        raise ValueError("backup path may not contain a comma")
    return [
        "docker",
        "run",
        "--rm",
        "--volumes-from",
        f"{container_id}:ro",
        "--mount",
        f"type=bind,src={resolved},dst=/backup",
        ALPINE_IMAGE,
        "sh",
        "-eu",
        "-c",
        'umask 077; tar --numeric-owner -czf "$1" -C "$2" .; '
        'if [ "$#" -eq 4 ]; then chown "$3:$4" "$1"; chmod 600 "$1"; fi',
        "backup-archive",
        f"/backup/{archive_name}",
        container_path,
        *_archive_owner_args(),
    ]


def _representative_hash_command(container_id: str, container_path: str, component: str) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--volumes-from",
        f"{container_id}:ro",
        ALPINE_IMAGE,
        "sh",
        "-eu",
        "-c",
        'printf "# component=%s\\n" "$1"; inventory="$(mktemp)"; '
        'cd "$2"; find . -type f -exec sha256sum {} + > "$inventory"; '
        'LC_ALL=C sort "$inventory" | head -n 10; rm -f "$inventory"',
        "representative-hashes",
        component,
        container_path,
    ]


def _stop_writers(
    config: BackupConfig,
    runner: CommandRunner,
    active_container_ids: dict[str, tuple[str, ...]],
    stopped: list[tuple[str, tuple[str, ...]]],
) -> None:
    for service in WRITER_SERVICES:
        service_container_ids = active_container_ids.get(service, ())
        if not service_container_ids:
            continue
        stopped.append((service, service_container_ids))
        runner.run(compose_command(config, "stop", service), cwd=config.project_dir, label=f"stop:{service}")


def _parse_container_states(raw_states: str, expected_count: int) -> list[dict[str, Any]] | None:
    lines = [line for line in raw_states.splitlines() if line.strip()]
    if len(lines) != expected_count:
        return None
    states: list[dict[str, Any]] = []
    for line in lines:
        try:
            state = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(state, dict):
            return None
        states.append(state)
    return states


def _containers_are_ready(raw_states: str, expected_count: int) -> bool:
    states = _parse_container_states(raw_states, expected_count)
    if states is None:
        return False
    for state in states:
        if state.get("Running") is not True:
            return False
        health = state.get("Health")
        if health is not None and (not isinstance(health, dict) or health.get("Status") != "healthy"):
            return False
    return True


def _active_container_ids(container_ids: tuple[str, ...], raw_states: str) -> tuple[str, ...]:
    states = _parse_container_states(raw_states, len(container_ids))
    if states is None:
        raise ValueError("container state inventory is malformed")
    active: list[str] = []
    for container_id, state in zip(container_ids, states, strict=True):
        status = state.get("Status")
        if status in {"running", "restarting", "paused"}:
            active.append(container_id)
        elif status not in {"created", "exited", "dead"}:
            raise ValueError("container state inventory has an unknown status")
    return tuple(active)


def _wait_for_recovered_containers(
    config: BackupConfig,
    runner: CommandRunner,
    service: str,
    container_ids: tuple[str, ...],
) -> None:
    deadline = time.monotonic() + RECOVERY_HEALTH_TIMEOUT_SECONDS
    while True:
        raw_states = runner.run(
            ["docker", "inspect", "--format", "{{json .State}}", *container_ids],
            cwd=config.project_dir,
            label=f"recover-health:{service}",
            timeout_seconds=RECOVERY_COMMAND_TIMEOUT_SECONDS,
        )
        if _containers_are_ready(raw_states, len(container_ids)):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SafeCommandTimeoutError(f"recover-health:{service}")
        time.sleep(min(RECOVERY_POLL_INTERVAL_SECONDS, remaining))


def _recover_writers(
    config: BackupConfig,
    runner: CommandRunner,
    stopped: list[tuple[str, tuple[str, ...]]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    stopped_by_service = dict(stopped)
    for service in RECOVERY_ORDER:
        service_container_ids = stopped_by_service.get(service)
        if service_container_ids is None:
            continue
        try:
            runner.run(
                ["docker", "start", *service_container_ids],
                cwd=config.project_dir,
                label=f"recover:{service}",
                timeout_seconds=RECOVERY_COMMAND_TIMEOUT_SECONDS,
            )
            _wait_for_recovered_containers(config, runner, service, service_container_ids)
        except BaseException as exc:
            results.append({"service": service, "status": "failed", "failure": _safe_failure(exc)})
        else:
            results.append({"service": service, "status": "recovered"})
    return results


def _make_private_directory(path: Path, runner: CommandRunner) -> None:
    if not _is_windows():
        path.chmod(0o700)
        return
    identity = runner.run(
        ["whoami"],
        cwd=path.parent,
        label="windows_acl_identity",
        timeout_seconds=RECOVERY_COMMAND_TIMEOUT_SECONDS,
    ).strip()
    if not identity or "\n" in identity or "\r" in identity:
        raise ValueError("Windows identity is missing or ambiguous")
    runner.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{identity}:(OI)(CI)F",
            "/T",
        ],
        cwd=path.parent,
        label="windows_private_acl",
        timeout_seconds=RECOVERY_COMMAND_TIMEOUT_SECONDS,
    )
    files = sorted(
        (child for child in path.rglob("*") if child.is_file() and not child.is_symlink()),
        key=lambda child: str(child),
    )
    if files:
        for file in files:
            runner.run(
                [
                    "icacls",
                    str(file),
                    "/inheritance:r",
                    "/grant:r",
                    f"{identity}:F",
                ],
                cwd=path.parent,
                label="windows_private_acl_files",
                timeout_seconds=RECOVERY_COMMAND_TIMEOUT_SECONDS,
            )


def _make_backup_files_private(path: Path) -> None:
    if _is_windows():
        return
    for child in path.iterdir():
        if child.is_file() and not child.is_symlink() and stat.S_IMODE(child.stat().st_mode) != 0o600:
            child.chmod(0o600)


def create_backup(
    config: BackupConfig,
    *,
    runner: CommandRunner | None = None,
    now: Callable[[], datetime] | None = None,
    hostname: str | None = None,
) -> dict[str, Any]:
    command_runner = runner or SubprocessRunner()
    clock = now or (lambda: datetime.now(UTC))
    started = clock()
    suffix = uuid.uuid4().hex[:8]
    staging = config.backup_root / f".incomplete-{started:%Y%m%dT%H%M%SZ}-{suffix}"
    final_dir = config.backup_root / f"snapshot-{started:%Y%m%dT%H%M%SZ}-{suffix}"
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "status": "failed",
        "started_at_utc": format_utc(started),
        "backup_directory": str(staging.absolute()),
        "components": {},
        "failures": [],
        "service_recovery": [],
    }
    stopped: list[tuple[str, tuple[str, ...]]] = []
    private_directory_ready = False
    try:
        staging.mkdir(parents=True, exist_ok=False, mode=0o700)
        _make_private_directory(staging, command_runner)
        private_directory_ready = True
        raw_config = command_runner.run(
            compose_command(config, "config", "--format", "json"),
            cwd=config.project_dir,
            label="compose_config",
        )
        compose_config = parse_compose_config(raw_config)
        compose_project = str(compose_config.get("name") or config.project_name or "unknown")
        git_commit = source_revision(config.project_dir, command_runner)

        if config.env_file is not None:
            if config.age_recipient is None:
                raise ValueError("--env-file requires --age-recipient")
            if not config.env_file.is_file():
                raise FileNotFoundError("configured environment file is missing")
            encrypted_env = staging / "environment.age"
            command_runner.run(
                [
                    "age",
                    "--recipient",
                    config.age_recipient,
                    "--output",
                    str(encrypted_env),
                    str(config.env_file),
                ],
                cwd=config.project_dir,
                label="environment_encryption",
            )
            result["components"]["environment"] = {"status": "complete", **artifact_record(encrypted_env)}
        else:
            result["components"]["environment"] = {"status": "not_configured", "archive_name": None}

        configured_services = set(compose_config["services"])
        all_container_ids: dict[str, tuple[str, ...]] = {}
        archive_services = {value[0] for value in ARCHIVE_COMPONENTS.values()}
        services_to_query = (archive_services | set(WRITER_SERVICES) | {"migrate"}) & configured_services
        for service in services_to_query:
            raw_container_ids = command_runner.run(
                compose_command(config, "ps", "--all", "-q", service),
                cwd=config.project_dir,
                label=f"container:{service}",
            )
            all_container_ids[service] = tuple(line.strip() for line in raw_container_ids.splitlines() if line.strip())
        active_container_ids: dict[str, tuple[str, ...]] = {}
        for service, container_ids in all_container_ids.items():
            if not container_ids:
                continue
            raw_states = command_runner.run(
                ["docker", "inspect", "--format", "{{json .State}}", *container_ids],
                cwd=config.project_dir,
                label=f"container-state:{service}",
                timeout_seconds=RECOVERY_COMMAND_TIMEOUT_SECONDS,
            )
            active_ids = _active_container_ids(container_ids, raw_states)
            if active_ids:
                active_container_ids[service] = active_ids
        if "migrate" in active_container_ids:
            raise RuntimeError("refusing snapshot while the migration service is active")
        archive_container_ids = {
            service: ids[0] if len(ids) == 1 else None for service, ids in all_container_ids.items()
        }
        selected = select_archive_components(archive_container_ids)
        missing = [name for name, item in selected.items() if item["required"] and not item["container_id"]]
        if missing:
            result["components"].update(selected)
            raise RuntimeError(f"required containers missing: {','.join(sorted(missing))}")

        if "postgres" in configured_services:
            database_dump_command = compose_command(
                config,
                "exec",
                "-T",
                "postgres",
                "sh",
                "-eu",
                "-c",
                'exec pg_dump --format=custom --no-owner --no-acl --username "$POSTGRES_USER" "$POSTGRES_DB"',
            )
            globals_audit_command = compose_command(
                config,
                "exec",
                "-T",
                "postgres",
                "sh",
                "-eu",
                "-c",
                'exec pg_dumpall --globals-only --no-role-passwords --username "$POSTGRES_USER"',
            )
            alembic_revision_command = compose_command(
                config,
                "exec",
                "-T",
                "postgres",
                "sh",
                "-eu",
                "-c",
                'exec psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --tuples-only --no-align '
                "--command 'SELECT version_num FROM alembic_version'",
            )
            baseline_counts_command = compose_command(
                config,
                "exec",
                "-T",
                "postgres",
                "sh",
                "-eu",
                "-c",
                'exec psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" '
                '--tuples-only --no-align --field-separator=, --command "$1"',
                "baseline-counts",
                BASELINE_COUNT_SQL,
            )
            database_environment = None
        else:
            postgres_client, database_environment = _external_postgres_client(compose_config)
            database_dump_command = [
                *postgres_client,
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-acl",
            ]
            globals_audit_command = [
                *postgres_client,
                "pg_dumpall",
                "--globals-only",
                "--no-role-passwords",
            ]
            alembic_revision_command = [
                *postgres_client,
                "psql",
                "--tuples-only",
                "--no-align",
                "--command",
                "SELECT version_num FROM alembic_version",
            ]
            baseline_counts_command = [
                *postgres_client,
                "psql",
                "--tuples-only",
                "--no-align",
                "--field-separator=,",
                "--command",
                BASELINE_COUNT_SQL,
            ]

        _stop_writers(config, command_runner, active_container_ids, stopped)

        baseline_counts = staging / RESTORE_BASELINE_COMPONENTS["restore_baseline_counts"]
        command_runner.run_to_file(
            baseline_counts_command,
            baseline_counts,
            cwd=config.project_dir,
            label="restore_baseline_counts",
            environment=database_environment,
        )
        result["components"]["restore_baseline_counts"] = {
            "status": "complete",
            **artifact_record(baseline_counts),
        }

        database_dump = staging / "database.dump"
        command_runner.run_to_file(
            database_dump_command,
            database_dump,
            cwd=config.project_dir,
            label="database",
            environment=database_environment,
        )
        result["components"]["database"] = {"status": "complete", **artifact_record(database_dump)}

        globals_audit = staging / "globals-audit.sql"
        command_runner.run_to_file(
            globals_audit_command,
            globals_audit,
            cwd=config.project_dir,
            label="database_globals_audit",
            environment=database_environment,
        )
        result["components"]["database_globals_audit"] = {
            "status": "complete",
            **artifact_record(globals_audit),
        }

        alembic_revision = command_runner.run(
            alembic_revision_command,
            cwd=config.project_dir,
            label="alembic_revision",
            environment=database_environment,
        ).strip()
        if not alembic_revision or "\n" in alembic_revision:
            raise ValueError("Alembic revision is missing or ambiguous")

        for name, item in selected.items():
            if item["status"] == "absent":
                result["components"][name] = item
                continue
            archive_name = str(item["archive_name"])
            command_runner.run(
                _archive_command(str(item["container_id"]), str(item["container_path"]), staging, archive_name),
                cwd=config.project_dir,
                label=name,
            )
            archive_path = staging / archive_name
            result["components"][name] = {"status": "complete", **artifact_record(archive_path)}
            representative_component = REPRESENTATIVE_COMPONENTS.get(name)
            if representative_component is not None:
                representative_path = staging / RESTORE_BASELINE_COMPONENTS[representative_component]
                command_runner.run_to_file(
                    _representative_hash_command(
                        str(item["container_id"]),
                        str(item["container_path"]),
                        name,
                    ),
                    representative_path,
                    cwd=config.project_dir,
                    label=representative_component,
                )
                result["components"][representative_component] = {
                    "status": "complete",
                    **artifact_record(representative_path),
                }

    except BaseException as exc:
        failure = _safe_failure(exc)
        result["failures"].append(failure)
        component = failure.get("component")
        if isinstance(component, str) and component in {
            "database",
            "database_globals_audit",
            "photo_data",
            "estimator_private_data",
            "mosquitto_data",
            "grafana_data",
            "environment_encryption",
            *RESTORE_BASELINE_COMPONENTS,
        }:
            result["components"].setdefault(component, {"status": "failed"})
        compose_config = locals().get("compose_config", {"services": {}})
        compose_project = locals().get("compose_project", config.project_name or "unknown")
        git_commit = locals().get("git_commit", "unknown")
        alembic_revision = locals().get("alembic_revision", "unknown")
    finally:
        recovery = _recover_writers(config, command_runner, stopped)
        result["service_recovery"] = recovery
        for recovery_result in recovery:
            if recovery_result["status"] != "recovered":
                result["failures"].append(recovery_result["failure"])

    try:
        if private_directory_ready and staging.is_dir():
            _make_private_directory(staging, command_runner)
            _make_backup_files_private(staging)
    except BaseException as exc:
        result["failures"].append(_safe_failure(exc))

    if not result["failures"]:
        try:
            artifacts = [
                value
                for value in result["components"].values()
                if value.get("status") == "complete" and value.get("archive_name")
            ]
            manifest = {
                "schema_version": MANIFEST_SCHEMA,
                "created_at_utc": format_utc(clock()),
                "host_identity": host_identity(hostname),
                "git_commit": git_commit,
                "compose_project_name": compose_project,
                "image_references": configured_images(compose_config),
                "alembic_revision": alembic_revision,
                "components": result["components"],
                "service_recovery": recovery,
                "artifacts": sorted(artifacts, key=lambda item: str(item["archive_name"])),
            }
            manifest_path = staging / "manifest.json"
            if os.name != "nt":
                manifest_path.touch(mode=0o600, exist_ok=False)
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            if os.name != "nt":
                manifest_path.chmod(0o600)
            verification = verify_manifest(staging)
            if verification["valid"]:
                staging.rename(final_dir)
                result["backup_directory"] = str(final_dir.resolve())
                result["manifest"] = "manifest.json"
                result["status"] = "complete"
            else:
                result["failures"].append(
                    {"kind": "verification_failed", "component": "manifest", "errors": verification["errors"]}
                )
        except BaseException as exc:
            result["failures"].append(_safe_failure(exc))
    result["finished_at_utc"] = format_utc(clock())
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or verify a complete Senior Pomidor backup snapshot.")
    parser.add_argument("--verify", type=Path, help="Verify an existing manifest and its artifacts.")
    parser.add_argument("--backup-root", type=Path, default=Path("backups"))
    parser.add_argument("--project-dir", type=Path, default=Path.cwd())
    parser.add_argument(
        "--compose-file",
        action="append",
        type=Path,
        dest="compose_files",
        help="Compose file; repeat for overlays. Defaults to docker-compose.yml + docker-compose.dev.yml.",
    )
    parser.add_argument("--project-name")
    parser.add_argument("--env-file", type=Path, help="Environment file to use and include as environment.age.")
    parser.add_argument("--age-recipient", help="age recipient used to encrypt --env-file.")
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser.parse_args(argv)


def _print_result(result: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if "valid" in result:
        print("Backup verification: PASS" if result["valid"] else "Backup verification: FAIL")
        for error in result.get("errors", []):
            print(f"- {error['artifact']}: {error['reason']}")
        return
    print(f"Backup status: {result['status']}")
    print(f"Directory: {result['backup_directory']}")
    for name, component in sorted(result["components"].items()):
        print(f"- {name}: {component['status']}")
    for failure in result["failures"]:
        print(f"- failure: {failure['component']} ({failure['kind']})")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.verify is not None:
        result = verify_manifest(args.verify.resolve())
        _print_result(result, args.json_output)
        return 0 if result["valid"] else 1
    if bool(args.env_file) != bool(args.age_recipient):
        print("--env-file and --age-recipient must be supplied together", file=sys.stderr)
        return 2
    project_dir = args.project_dir.resolve()
    compose_files = tuple(args.compose_files or (Path("docker-compose.yml"), Path("docker-compose.dev.yml")))
    resolved_compose_files = tuple(
        path.resolve() if path.is_absolute() else (project_dir / path).resolve() for path in compose_files
    )
    config = BackupConfig(
        project_dir=project_dir,
        backup_root=args.backup_root.resolve(),
        compose_files=resolved_compose_files,
        project_name=args.project_name,
        env_file=args.env_file.resolve() if args.env_file else None,
        age_recipient=args.age_recipient,
    )
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def interrupt(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        result = create_backup(config)
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
    _print_result(result, args.json_output)
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
