from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import socket

# This bounded local workflow intentionally invokes only Git and Docker argv lists.
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ISSUE_RE = re.compile(r"[A-Z][A-Z0-9-]*-\d+")
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
TASK_KEY_RE = re.compile(r"[a-z0-9-]+")
PORT_START = 22000
PORT_END = 59990
PORT_BLOCK_SIZE = 10
EMPTY_CLOUD_VALUE = ""
ALLOWED_PROFILES = {"observability", "daily-story"}
PUBLISHED_PORT_NAMES = (
    "API_PUBLISHED_PORT",
    "MQTT_PUBLISHED_PORT",
    "POSTGRES_PUBLISHED_PORT",
    "GRAFANA_PUBLISHED_PORT",
    "OLLAMA_PUBLISHED_PORT",
)
FORBIDDEN_PATH_PARTS = ("/srv/apps", "/srv/secrets", "/srv/logs", "/var/lib/docker")
HARDWARE_PATH_PARTS = ("/dev/gpio", "/dev/i2c", "/dev/mem", "/sys/class/gpio")
SAFE_HOST_ENV = {
    "COMSPEC",
    "HOME",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
}


class AgentTaskError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepositoryContext:
    checkout_root: Path
    control_root: Path
    git_common_dir: Path


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    # All callers construct argv lists from fixed Git/Docker verbs; shell execution is never used.
    result = subprocess.run(  # nosec B603
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise AgentTaskError(f"command failed ({result.returncode}): {' '.join(args)}\n{detail}")
    return result


def repository_context(cwd: Path | None = None) -> RepositoryContext:
    location = (cwd or Path.cwd()).resolve()
    checkout = Path(_run(["git", "rev-parse", "--show-toplevel"], cwd=location).stdout.strip()).resolve()
    common_value = _run(["git", "rev-parse", "--git-common-dir"], cwd=checkout).stdout.strip()
    common = Path(common_value)
    if not common.is_absolute():
        common = (checkout / common).resolve()
    control = common.parent if common.name == ".git" else checkout
    return RepositoryContext(checkout, control.resolve(), common)


def validate_identity(issue: str, slug: str, kind: str) -> tuple[str, str]:
    normalized_issue = issue.upper()
    normalized_slug = slug.lower()
    if not ISSUE_RE.fullmatch(normalized_issue):
        raise AgentTaskError("issue must look like TOMATO-123 or TOMATO-AI-123")
    if not SLUG_RE.fullmatch(normalized_slug):
        raise AgentTaskError("slug must contain lowercase letters/numbers separated by single hyphens")
    if kind not in {"feature", "fix"}:
        raise AgentTaskError("kind must be feature or fix")
    return normalized_issue, normalized_slug


def task_key(issue: str, slug: str) -> str:
    return f"{issue.lower()}-{slug}"


def ensure_clean_worktree(path: Path) -> None:
    status = _run(["git", "status", "--porcelain"], cwd=path).stdout.strip()
    if status:
        raise AgentTaskError(f"worktree is dirty; commit, stash, or explicitly handle changes first: {path}")


def _state_root(context: RepositoryContext) -> Path:
    return context.control_root / ".agent-tasks"


def _allocation_path(state_root: Path, port_base: int) -> Path:
    return state_root / "allocations" / f"ports-{port_base}.lock"


def _allocate_port_block(state_root: Path, owner: str) -> tuple[int, Path]:
    allocation_dir = state_root / "allocations"
    allocation_dir.mkdir(parents=True, exist_ok=True)
    for base in range(PORT_START, PORT_END + 1, PORT_BLOCK_SIZE):
        lock = _allocation_path(state_root, base)
        if any(allocation_dir.glob(f"ports-{base}.releasing-*")):
            continue
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"owner": owner, "allocated_at_utc": datetime.now(UTC).isoformat()}, stream)
            stream.write("\n")
        return base, lock
    raise AgentTaskError("no free agent port block is available")


def _safe_data_path(path: Path, data_root: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(data_root.resolve()):
        raise AgentTaskError(f"agent data path escapes its task root: {resolved}")
    normalized = resolved.as_posix().lower()
    if any(part in normalized for part in FORBIDDEN_PATH_PARTS + HARDWARE_PATH_PARTS):
        raise AgentTaskError(f"production or hardware path is forbidden: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved.as_posix()


def build_environment(task_dir: Path, key: str, port_base: int) -> dict[str, str]:
    data_root = task_dir / "data"
    normalized_key = re.sub(r"[^a-z0-9-]", "-", key).strip("-")
    key_digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    project_suffix = f"{normalized_key[:29].rstrip('-')}-{key_digest}"
    environment = {
        "COMPOSE_PROJECT_NAME": f"sp-agent-{project_suffix}",
        "COMPOSE_PROFILES": "",
        "APP_IMAGE": "senior-pomidor-server:agent",
        "LAN_BIND_ADDRESS": "127.0.0.1",
        "POSTGRES_BIND_ADDRESS": "127.0.0.1",
        "API_PUBLISHED_PORT": str(port_base),
        "MQTT_PUBLISHED_PORT": str(port_base + 1),
        "POSTGRES_PUBLISHED_PORT": str(port_base + 2),
        "GRAFANA_PUBLISHED_PORT": str(port_base + 3),
        "OLLAMA_PUBLISHED_PORT": str(port_base + 4),
        "POSTGRES_DB": f"agent_{port_base}",
        "POSTGRES_USER": "agent_local",
        "POSTGRES_PASSWORD": f"agent_local_{port_base}",
        "GRAFANA_DB_USER": "agent_grafana",
        "GRAFANA_DB_PASSWORD": f"agent_grafana_{port_base}",
        "GRAFANA_ADMIN_USER": "agent_admin",
        "GRAFANA_ADMIN_PASSWORD": f"agent_admin_{port_base}",
        "DATABASE_URL": f"postgresql+psycopg://agent_local:agent_local_{port_base}@postgres:5432/agent_{port_base}",
        "PHOTO_DATA_DIR": _safe_data_path(data_root / "photos", data_root),
        "ESTIMATOR_PRIVATE_DATA_DIR": _safe_data_path(data_root / "estimator-private", data_root),
        "MOSQUITTO_DATA_DIR": _safe_data_path(data_root / "mosquitto", data_root),
        "POSTGRES_DATA_DIR": _safe_data_path(data_root / "postgres", data_root),
        "GRAFANA_DATA_DIR": _safe_data_path(data_root / "grafana", data_root),
        "OLLAMA_DATA_DIR": _safe_data_path(data_root / "ollama", data_root),
        "GRAFANA_CLOUD_EXPORT_ENABLED": "false",
        "GRAFANA_CLOUD_REMOTE_WRITE_URL": EMPTY_CLOUD_VALUE,
        "GRAFANA_CLOUD_INSTANCE_ID": EMPTY_CLOUD_VALUE,
        "GRAFANA_CLOUD_API_TOKEN": EMPTY_CLOUD_VALUE,
        "EXECUTOR_BACKEND": "fake",
        "HARDWARE_BACKEND": "fake",
        "GPIO_ENABLED": "false",
        "AGENT_TASK_ISOLATED": "true",
    }
    validate_environment(environment, data_root)
    return environment


def validate_environment(environment: dict[str, str], data_root: Path) -> None:
    if environment.get("LAN_BIND_ADDRESS") != "127.0.0.1" or environment.get("POSTGRES_BIND_ADDRESS") != "127.0.0.1":
        raise AgentTaskError("agent services must bind to loopback only")
    if environment.get("GRAFANA_CLOUD_EXPORT_ENABLED", "").lower() != "false":
        raise AgentTaskError("Grafana Cloud export must be disabled")
    if any(
        environment.get(name)
        for name in ("GRAFANA_CLOUD_REMOTE_WRITE_URL", "GRAFANA_CLOUD_INSTANCE_ID", "GRAFANA_CLOUD_API_TOKEN")
    ):
        raise AgentTaskError("Grafana Cloud credentials/endpoints must be empty")
    if environment.get("EXECUTOR_BACKEND") != "fake" or environment.get("HARDWARE_BACKEND") != "fake":
        raise AgentTaskError("agent hardware and Executor backends must be fake")
    if environment.get("GPIO_ENABLED", "").lower() != "false":
        raise AgentTaskError("GPIO must be disabled")
    if environment.get("AGENT_TASK_ISOLATED", "").lower() != "true":
        raise AgentTaskError("agent test isolation marker must be enabled")
    if environment.get("COMPOSE_PROFILES"):
        raise AgentTaskError("profiles are selected only through the bounded compose command")
    for name in (
        "PHOTO_DATA_DIR",
        "ESTIMATOR_PRIVATE_DATA_DIR",
        "MOSQUITTO_DATA_DIR",
        "POSTGRES_DATA_DIR",
        "GRAFANA_DATA_DIR",
        "OLLAMA_DATA_DIR",
    ):
        value = environment.get(name)
        if not value or not Path(value).resolve().is_relative_to(data_root.resolve()):
            raise AgentTaskError(f"{name} must stay below the task data directory")
        normalized = Path(value).resolve().as_posix().lower()
        if any(part in normalized for part in FORBIDDEN_PATH_PARTS + HARDWARE_PATH_PARTS):
            raise AgentTaskError(f"{name} targets a forbidden path")


def _write_env(path: Path, environment: dict[str, str]) -> None:
    content = "\n".join(f"{name}={value}" for name, value in sorted(environment.items())) + "\n"
    path.write_text(content, encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def _read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator:
            raise AgentTaskError(f"malformed generated env line: {name}")
        result[name] = value
    return result


def _creation_checkpoint(stage: str) -> None:
    """Fault-injection seam used by tests; production creation performs no extra action."""


def create_task(
    context: RepositoryContext, issue: str, slug: str, kind: str, *, worktree: bool = True
) -> dict[str, Any]:
    issue, slug = validate_identity(issue, slug, kind)
    ensure_clean_worktree(context.checkout_root)
    key = task_key(issue, slug)
    state_root = _state_root(context)
    task_dir = state_root / key
    if task_dir.exists():
        raise AgentTaskError(f"agent task already exists: {key}")
    branch = f"{kind}/{issue}-{slug}"
    worktree_path = context.control_root / ".agent-worktrees" / key if worktree else context.checkout_root
    port_base, allocation = _allocate_port_block(state_root, key)
    task_dir.mkdir(parents=True)
    metadata: dict[str, Any] = {
        "schema": "senior-pomidor.agent-task.v1",
        "task_key": key,
        "issue": issue,
        "slug": slug,
        "branch": branch,
        "worktree": str(worktree_path.resolve()),
        "uses_worktree": worktree,
        "state_dir": str(task_dir.resolve()),
        "env_file": str((task_dir / "agent.env").resolve()),
        "port_base": port_base,
        "allocation_file": str(allocation.resolve()),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "compose_running": False,
        "status": "creating",
        "creation_stage": "metadata",
        "resources": {
            "allocation_created": True,
            "branch_created": False,
            "worktree_created": False,
            "environment_created": False,
        },
    }
    _write_metadata(task_dir, metadata)
    stage = "metadata"
    try:
        stage = "allocation"
        metadata["creation_stage"] = stage
        _write_metadata(task_dir, metadata)
        _creation_checkpoint("allocation")
        stage = "metadata"
        metadata["creation_stage"] = stage
        _write_metadata(task_dir, metadata)
        _creation_checkpoint("metadata")
        stage = "branch-check"
        metadata["creation_stage"] = stage
        _write_metadata(task_dir, metadata)
        if (
            _run(
                ["git", "show-ref", "--verify", f"refs/heads/{branch}"], cwd=context.checkout_root, check=False
            ).returncode
            == 0
        ):
            raise AgentTaskError(f"branch already exists: {branch}")
        stage = "branch"
        metadata["creation_stage"] = stage
        _write_metadata(task_dir, metadata)
        _run(["git", "branch", branch, "HEAD"], cwd=context.checkout_root)
        metadata["resources"]["branch_created"] = True
        _write_metadata(task_dir, metadata)
        _creation_checkpoint("branch")
        if worktree:
            stage = "worktree"
            metadata["creation_stage"] = stage
            _write_metadata(task_dir, metadata)
            worktree_path.parent.mkdir(parents=True, exist_ok=True)
            _run(["git", "worktree", "add", str(worktree_path), branch], cwd=context.checkout_root)
            metadata["resources"]["worktree_created"] = True
            _write_metadata(task_dir, metadata)
            _creation_checkpoint("worktree")
        else:
            stage = "checkout"
            metadata["creation_stage"] = stage
            _write_metadata(task_dir, metadata)
            _run(["git", "switch", branch], cwd=context.checkout_root)
        stage = "environment"
        metadata["creation_stage"] = stage
        _write_metadata(task_dir, metadata)
        environment = build_environment(task_dir, key, port_base)
        env_path = task_dir / "agent.env"
        _write_env(env_path, environment)
        metadata["resources"]["environment_created"] = True
        _write_metadata(task_dir, metadata)
        stage = "finalize"
        metadata["creation_stage"] = stage
        _write_metadata(task_dir, metadata)
        head = _run(["git", "rev-parse", "HEAD"], cwd=context.checkout_root).stdout.strip()
        metadata["source_head"] = head
        metadata["status"] = "active"
        metadata["creation_stage"] = "complete"
        _write_metadata(task_dir, metadata)
        return metadata
    except Exception as exc:
        if stage in {"branch", "worktree", "checkout", "environment", "finalize"}:
            metadata["resources"]["branch_created"] = (
                _run(
                    ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
                    cwd=context.checkout_root,
                    check=False,
                ).returncode
                == 0
            )
        if worktree and stage in {"worktree", "environment", "finalize"}:
            metadata["resources"]["worktree_created"] = worktree_path.is_dir()
        metadata["status"] = "creation_failed"
        metadata["creation_stage"] = stage
        metadata["creation_failed_at_utc"] = datetime.now(UTC).isoformat()
        metadata["creation_error"] = f"{type(exc).__name__}: {exc}"
        _write_metadata(task_dir, metadata)
        raise


def _metadata_path(task_dir: Path) -> Path:
    return task_dir / "metadata.json"


def _write_metadata(task_dir: Path, metadata: dict[str, Any]) -> None:
    path = _metadata_path(task_dir)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_task(context: RepositoryContext, key: str) -> tuple[Path, dict[str, Any]]:
    if not TASK_KEY_RE.fullmatch(key):
        raise AgentTaskError("invalid task key")
    task_dir = _state_root(context) / key
    metadata_path = _metadata_path(task_dir)
    if not metadata_path.is_file():
        raise AgentTaskError(f"unknown agent task: {key}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("task_key") != key or metadata.get("schema") != "senior-pomidor.agent-task.v1":
        raise AgentTaskError("agent task metadata is inconsistent")
    return task_dir, metadata


def sanitized_process_environment(generated: dict[str, str]) -> dict[str, str]:
    safe = {name: value for name, value in os.environ.items() if name.upper() in SAFE_HOST_ENV}
    safe.update(generated)
    safe["COMPOSE_PROFILES"] = ""
    return safe


def _compose_prefix(context: RepositoryContext, metadata: dict[str, Any], profiles: list[str]) -> list[str]:
    invalid = set(profiles) - ALLOWED_PROFILES
    if invalid:
        raise AgentTaskError(f"unsupported agent Compose profile(s): {', '.join(sorted(invalid))}")
    worktree = Path(metadata["worktree"])
    command = [
        "docker",
        "compose",
        "--env-file",
        metadata["env_file"],
        "--project-directory",
        str(worktree),
        "-f",
        str(worktree / "docker-compose.yml"),
        "-f",
        str(worktree / "docker-compose.dev.yml"),
        "-f",
        str(worktree / "docker-compose.agent.yml"),
    ]
    for profile in profiles:
        command.extend(["--profile", profile])
    return command


def _is_external(resource: Any) -> bool:
    if not isinstance(resource, dict):
        return False
    external = resource.get("external", False)
    return bool(external) if not isinstance(external, dict) else True


def _validate_rendered_compose(
    rendered: dict[str, Any], data_root: Path, worktree_root: Path, active_profiles: list[str]
) -> None:
    services = rendered.get("services", {})
    if rendered.get("secrets"):
        raise AgentTaskError("rendered Compose declares secrets")
    for resource_kind in ("volumes", "networks"):
        for resource_name, resource in rendered.get(resource_kind, {}).items():
            if _is_external(resource):
                raise AgentTaskError(f"{resource_kind[:-1]} {resource_name} is external")
            if (
                resource_kind == "networks"
                and isinstance(resource, dict)
                and str(resource.get("driver", "")).lower() == "host"
            ):
                raise AgentTaskError(f"network {resource_name} uses the host driver")
    exporter = services.get("grafana-cloud-exporter")
    if exporter is not None:
        exporter_env = exporter.get("environment", {})
        if str(exporter_env.get("GRAFANA_CLOUD_EXPORT_ENABLED", "false")).lower() != "false":
            raise AgentTaskError("rendered Compose enables Grafana Cloud export")
        exporter_profiles = set(exporter.get("profiles", []))
        if not exporter_profiles or exporter_profiles.intersection(active_profiles):
            raise AgentTaskError("Grafana Cloud exporter is active in the agent Compose selection")
    for service_name, service in services.items():
        if service.get("devices"):
            raise AgentTaskError(f"{service_name} maps host devices")
        if service.get("privileged"):
            raise AgentTaskError(f"{service_name} is privileged")
        if service.get("cap_add"):
            raise AgentTaskError(f"{service_name} adds Linux capabilities")
        if service.get("secrets"):
            raise AgentTaskError(f"{service_name} consumes Compose secrets")
        for namespace in ("network_mode", "pid", "ipc", "uts", "userns_mode", "cgroup"):
            if str(service.get(namespace, "")).lower() == "host":
                raise AgentTaskError(f"{service_name} uses the host {namespace} namespace")
        for port in service.get("ports", []):
            host_ip = str(port.get("host_ip", "")) if isinstance(port, dict) else str(port)
            try:
                loopback = ipaddress.ip_address(host_ip).is_loopback
            except ValueError:
                loopback = False
            if not loopback:
                raise AgentTaskError(f"{service_name} publishes a non-loopback port")
        for volume in service.get("volumes", []):
            if not isinstance(volume, dict) or volume.get("type") != "bind":
                continue
            source = Path(str(volume.get("source", ""))).resolve()
            normalized = source.as_posix().lower()
            if any(part in normalized for part in FORBIDDEN_PATH_PARTS + HARDWARE_PATH_PARTS):
                raise AgentTaskError(f"{service_name} mounts a forbidden path: {source}")
            if volume.get("read_only", False):
                if not (source.is_relative_to(data_root.resolve()) or source.is_relative_to(worktree_root.resolve())):
                    raise AgentTaskError(f"{service_name} has a read-only bind outside task data/worktree: {source}")
            elif not source.is_relative_to(data_root.resolve()):
                raise AgentTaskError(f"{service_name} has a writable bind outside task data: {source}")
    for volume_name, volume in rendered.get("volumes", {}).items():
        device = str(volume.get("driver_opts", {}).get("device", ""))
        if not device:
            continue
        source = Path(device).resolve()
        if not source.is_relative_to(data_root.resolve()):
            raise AgentTaskError(f"{volume_name} binds outside task data: {source}")


def _require_available_ports(task_dir: Path, environment: dict[str, str]) -> None:
    unavailable: list[str] = []
    exclusive_address_use = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    for name in PUBLISHED_PORT_NAMES:
        raw_port = environment.get(name, "<missing>")
        try:
            port = int(raw_port)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                if os.name == "nt" and exclusive_address_use is not None:
                    probe.setsockopt(socket.SOL_SOCKET, exclusive_address_use, 1)
                probe.bind(("127.0.0.1", port))
        except (KeyError, OSError, ValueError):
            unavailable.append(raw_port)
    _record_command(
        task_dir,
        action="port-preflight",
        args=["loopback-port-check", *[str(environment[name]) for name in PUBLISHED_PORT_NAMES]],
        returncode=1 if unavailable else 0,
    )
    if unavailable:
        raise AgentTaskError(f"agent loopback port(s) are already occupied or unavailable: {unavailable}")


def _record_command(task_dir: Path, *, action: str, args: list[str], returncode: int) -> None:
    record = {
        "at_utc": datetime.now(UTC).isoformat(),
        "action": action,
        "argv": args,
        "returncode": returncode,
    }
    with (task_dir / "commands.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def _require_local_docker_context(task_dir: Path, cwd: Path, environment: dict[str, str]) -> None:
    show_args = ["docker", "context", "show"]
    show = _run(show_args, cwd=cwd, env=environment, check=False)
    _record_command(task_dir, action="docker-context-show", args=show_args, returncode=show.returncode)
    if show.returncode != 0 or not show.stdout.strip():
        raise AgentTaskError("cannot verify the active Docker context")
    context_name = show.stdout.strip()
    inspect_args = ["docker", "context", "inspect", context_name, "--format", "{{.Endpoints.docker.Host}}"]
    inspect = _run(inspect_args, cwd=cwd, env=environment, check=False)
    audit_args = ["docker", "context", "inspect", "<active-context>", "--format", "<docker-host>"]
    _record_command(task_dir, action="docker-context-inspect", args=audit_args, returncode=inspect.returncode)
    endpoint = inspect.stdout.strip().lower()
    if inspect.returncode != 0 or not endpoint.startswith(("unix://", "npipe://")):
        raise AgentTaskError("agent Docker actions require a verified local unix:// or npipe:// context")


def compose_task(context: RepositoryContext, key: str, action: str, profiles: list[str]) -> int:
    task_dir, metadata = load_task(context, key)
    if metadata.get("status") != "active":
        raise AgentTaskError("agent task is not active")
    worktree = Path(metadata["worktree"])
    if not worktree.is_dir():
        raise AgentTaskError("agent worktree is missing")
    environment = _read_env(Path(metadata["env_file"]))
    validate_environment(environment, task_dir / "data")
    safe_env = sanitized_process_environment(environment)
    if action != "config":
        _require_local_docker_context(task_dir, worktree, safe_env)
    prefix = _compose_prefix(context, metadata, profiles)
    render_args = [*prefix, "config", "--format", "json"]
    rendered_result = _run(render_args, cwd=worktree, env=safe_env, check=False)
    _record_command(task_dir, action="config-preflight", args=render_args, returncode=rendered_result.returncode)
    if rendered_result.returncode != 0:
        detail = (rendered_result.stderr or rendered_result.stdout).strip()
        raise AgentTaskError(f"Compose preflight failed: {detail}")
    _validate_rendered_compose(json.loads(rendered_result.stdout), task_dir / "data", worktree, profiles)
    if action == "config":
        print(json.dumps({"task_key": key, "profiles": profiles, "validated": True}, indent=2))
        return 0
    suffix = {
        "up": ["up", "-d", "--build"],
        "down": ["down", "--remove-orphans"],
        "ps": ["ps"],
    }.get(action)
    if suffix is None:
        raise AgentTaskError("unsupported Compose action")
    command = [*prefix, *suffix]
    if action == "up":
        _require_available_ports(task_dir, environment)
        # Compose may create resources before returning a startup failure. Mark the stack as
        # potentially running first so cleanup requires an explicit bounded `down` attempt.
        metadata["compose_running"] = True
        _write_metadata(task_dir, metadata)
    result = _run(command, cwd=worktree, env=safe_env, check=False)
    _record_command(task_dir, action=action, args=command, returncode=result.returncode)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode == 0 and action == "down":
        metadata["compose_running"] = False
        _write_metadata(task_dir, metadata)
    return result.returncode


def cleanup_task(context: RepositoryContext, key: str) -> dict[str, Any]:
    task_dir, metadata = load_task(context, key)
    if metadata.get("compose_running"):
        raise AgentTaskError("agent Compose stack may be running; run the bounded 'compose down' action first")
    status = metadata.get("status")
    if status not in {"active", "creation_failed"}:
        raise AgentTaskError("agent task is already cleaned")
    worktree = Path(metadata["worktree"])
    resources = metadata.get("resources", {})
    if (
        status == "creation_failed"
        and metadata.get("uses_worktree")
        and worktree.exists()
        and not resources.get("worktree_created")
    ):
        raise AgentTaskError("failed creation left an unowned worktree path; inspect it manually")
    if metadata.get("uses_worktree") and worktree.exists():
        ensure_clean_worktree(worktree)
        _run(["git", "worktree", "remove", str(worktree)], cwd=context.control_root)
    metadata["status"] = "cleaned"
    metadata["cleaned_at_utc"] = datetime.now(UTC).isoformat()
    metadata["cleanup_note"] = "Branch, task data, command history, and port allocation were preserved."
    _write_metadata(task_dir, metadata)
    return metadata


def _allocation_owner(path: Path) -> str:
    try:
        allocation = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentTaskError("port allocation is missing or unreadable; refusing to release it") from exc
    owner = allocation.get("owner")
    if not isinstance(owner, str):
        raise AgentTaskError("legacy port allocation has no owner; refusing to release it automatically")
    return owner


def retire_task(context: RepositoryContext, key: str) -> dict[str, Any]:
    task_dir, metadata = load_task(context, key)
    if metadata.get("compose_running"):
        raise AgentTaskError("agent Compose stack may be running; retire is forbidden")
    if metadata.get("status") == "retired":
        raise AgentTaskError("agent task is already retired")
    if metadata.get("status") not in {"cleaned", "retiring"}:
        raise AgentTaskError("agent task must be cleaned before retirement")
    port_base = metadata.get("port_base")
    if not isinstance(port_base, int):
        raise AgentTaskError("agent task has no valid port allocation")
    allocation = _allocation_path(_state_root(context), port_base)
    recorded = metadata.get("allocation_file")
    if recorded and Path(recorded).resolve() != allocation.resolve():
        raise AgentTaskError("agent task allocation path is inconsistent")
    release_marker = allocation.with_name(f"ports-{port_base}.releasing-{key}")
    if release_marker.exists():
        if _allocation_owner(release_marker) != key:
            raise AgentTaskError("port allocation release marker belongs to another task")
    elif metadata.get("status") == "cleaned" or allocation.exists():
        if _allocation_owner(allocation) != key:
            raise AgentTaskError("port allocation belongs to another task")
        try:
            os.replace(allocation, release_marker)
        except OSError as exc:
            raise AgentTaskError("could not atomically claim the port allocation for release") from exc
    metadata["status"] = "retiring"
    metadata["retirement_started_at_utc"] = metadata.get("retirement_started_at_utc", datetime.now(UTC).isoformat())
    _write_metadata(task_dir, metadata)
    if release_marker.exists():
        try:
            release_marker.unlink()
        except OSError as exc:
            raise AgentTaskError("port allocation remains reserved; retry retire to finish release") from exc
    metadata["status"] = "retired"
    metadata["retired_at_utc"] = datetime.now(UTC).isoformat()
    metadata["allocation_released"] = True
    metadata["retire_note"] = "Branch, task data, metadata, and command history were preserved."
    _write_metadata(task_dir, metadata)
    return metadata


def check_task(context: RepositoryContext, key: str, check_name: str) -> int:
    task_dir, metadata = load_task(context, key)
    if metadata.get("status") != "active":
        raise AgentTaskError("agent task is not active")
    worktree = Path(metadata["worktree"])
    environment = _read_env(Path(metadata["env_file"]))
    validate_environment(environment, task_dir / "data")
    commands = {
        "pytest": [sys.executable, "-m", "pytest", "-q"],
        "quality": ["nox", "-s", "lint", "format_check", "types"],
        "security": ["nox", "-s", "security", "deps_audit"],
        "planner": [sys.executable, "-m", "tools.evaluate_feature_planner"],
        "reviewer-corpus": [sys.executable, "-m", "tools.evaluate_reviewer"],
    }
    command = commands.get(check_name)
    if command is None:
        raise AgentTaskError("unsupported check")
    result = _run(command, cwd=worktree, env=sanitized_process_environment(environment), check=False)
    _record_command(task_dir, action=f"check-{check_name}", args=command, returncode=result.returncode)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return result.returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create and operate isolated Senior Pomidor agent tasks.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="create one issue branch and optional worktree")
    create.add_argument("--issue", required=True)
    create.add_argument("--slug", required=True)
    create.add_argument("--kind", choices=("feature", "fix"), default="feature")
    create.add_argument("--no-worktree", action="store_true")
    inspect = subparsers.add_parser("inspect", help="print secret-free task metadata")
    inspect.add_argument("task_key")
    compose = subparsers.add_parser("compose", help="run one bounded local Compose action")
    compose.add_argument("task_key")
    compose.add_argument("action", choices=("config", "up", "down", "ps"))
    compose.add_argument("--profile", action="append", choices=sorted(ALLOWED_PROFILES), default=[])
    check = subparsers.add_parser("check", help="run one fixed check with the generated test environment")
    check.add_argument("task_key")
    check.add_argument("check_name", choices=("pytest", "quality", "security", "planner", "reviewer-corpus"))
    cleanup = subparsers.add_parser("cleanup", help="remove only a clean worktree; preserve branch and data")
    cleanup.add_argument("task_key")
    retire = subparsers.add_parser("retire", help="release a cleaned task's owned port allocation")
    retire.add_argument("task_key")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        context = repository_context()
        if args.command == "create":
            result = create_task(context, args.issue, args.slug, args.kind, worktree=not args.no_worktree)
        elif args.command == "inspect":
            _, result = load_task(context, args.task_key)
        elif args.command == "compose":
            return compose_task(context, args.task_key, args.action, args.profile)
        elif args.command == "check":
            return check_task(context, args.task_key, args.check_name)
        elif args.command == "cleanup":
            result = cleanup_task(context, args.task_key)
        elif args.command == "retire":
            result = retire_task(context, args.task_key)
        else:
            raise AgentTaskError("unsupported command")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except AgentTaskError as exc:
        print(f"agent-task: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
