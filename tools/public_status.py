from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = "senior-pomidor.status.v1"
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_STATUS_PATH = "status/status.json"
EDGE_STALE_AFTER_MINUTES = 15
CRITICAL_CORE_SERVICES = {"api", "worker", "postgres", "mosquitto"}


@dataclass(frozen=True)
class PublishResult:
    changed: bool
    committed: bool
    pushed: bool
    message: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_utc(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def load_compose_ps(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        payload = json.loads(stripped)
        return payload if isinstance(payload, list) else []

    services: list[dict[str, Any]] = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            services.append(payload)
    return services


def normalize_compose_service(raw: dict[str, Any]) -> dict[str, Any]:
    service = str(raw.get("Service") or raw.get("Name") or "unknown")
    state = str(raw.get("State") or raw.get("Status") or "unknown").lower()
    health = str(raw.get("Health") or "").lower() or None
    exit_code = raw.get("ExitCode")
    normalized_exit_code = int(exit_code) if isinstance(exit_code, int | str) and str(exit_code).isdigit() else None
    category = "core" if service in CRITICAL_CORE_SERVICES else "support"
    return {
        "service": service,
        "category": category,
        "state": state,
        "health": health,
        "exit_code": normalized_exit_code,
        "status": core_service_status(service, state, health, normalized_exit_code),
    }


def core_service_status(service: str, state: str, health: str | None, exit_code: int | None) -> str:
    if service == "migrate":
        return "ok" if exit_code == 0 and state in {"exited", "completed"} else "degraded"
    if state != "running":
        return "degraded"
    if health in {None, "", "healthy"}:
        return "ok"
    return "degraded"


def docker_compose_ps(project_dir: Path) -> list[dict[str, Any]]:
    result = subprocess.run(  # nosec B603 B607
        ["docker", "compose", "ps", "--format", "json"],
        cwd=project_dir,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return load_compose_ps(result.stdout)


def get_json(url: str, timeout_seconds: float = 5.0) -> Any:
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are supported")
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))


def collect_readiness(api_base_url: str) -> dict[str, Any]:
    try:
        payload = get_json(f"{api_base_url.rstrip('/')}/ready")
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ready": False, "status": "degraded", "error": exc.__class__.__name__}
    return {
        "ready": bool(payload.get("ready")),
        "status": "ok" if payload.get("ready") is True else "degraded",
        "database": payload.get("database"),
        "migration": payload.get("migration"),
    }


def collect_latest_devices(api_base_url: str) -> list[dict[str, Any]]:
    try:
        payload = get_json(f"{api_base_url.rstrip('/')}/api/v1/devices/latest")
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def normalize_edge_device(event: dict[str, Any], now: datetime) -> dict[str, Any]:
    received_at = parse_utc(str(event.get("received_at") or ""))
    minutes_since = None
    if received_at is not None:
        minutes_since = max(0, round((now - received_at).total_seconds() / 60, 1))
    raw_health_alerts = event.get("health_alerts")
    health_alerts = raw_health_alerts if isinstance(raw_health_alerts, list) else []
    rpi_core: dict[str, Any] = {}
    system_health = event.get("system_health")
    if isinstance(system_health, dict) and isinstance(system_health.get("rpi_core"), dict):
        rpi_core = system_health["rpi_core"]
    status = edge_status(minutes_since, len(health_alerts))
    return {
        "device_id": str(event.get("device_id") or "unknown"),
        "status": status,
        "last_telemetry_received_at": format_utc(received_at) if received_at else None,
        "minutes_since_telemetry": minutes_since,
        "health_alert_count": len(health_alerts),
        "telemetry_buffer_file_count": numeric_or_none(rpi_core.get("telemetry_buffer_file_count")),
        "photo_buffer_file_count": numeric_or_none(rpi_core.get("photo_buffer_file_count")),
        "disk_free_percent": numeric_or_none(rpi_core.get("disk_free_percent")),
    }


def numeric_or_none(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    return None


def edge_status(minutes_since: float | None, health_alert_count: int) -> str:
    if minutes_since is None:
        return "unknown"
    if minutes_since > EDGE_STALE_AFTER_MINUTES:
        return "stale"
    if health_alert_count > 0:
        return "degraded"
    return "ok"


def calculate_overall_status(
    core_services: list[dict[str, Any]],
    readiness: dict[str, Any],
    edge_devices: list[dict[str, Any]],
) -> str:
    if not core_services and readiness.get("status") != "ok":
        return "unknown"
    critical = [service for service in core_services if service["service"] in CRITICAL_CORE_SERVICES]
    if readiness.get("status") != "ok" or any(service["status"] != "ok" for service in critical):
        return "degraded"
    if not edge_devices:
        return "unknown"
    if any(device["status"] == "degraded" for device in edge_devices):
        return "degraded"
    if all(device["status"] in {"stale", "unknown"} for device in edge_devices):
        return "stale"
    return "ok"


def build_status_document(project_dir: Path, api_base_url: str, now: datetime | None = None) -> dict[str, Any]:
    now = now or utc_now()
    core_services = sorted(
        [normalize_compose_service(service) for service in docker_compose_ps(project_dir)],
        key=lambda service: service["service"],
    )
    readiness = collect_readiness(api_base_url)
    edge_devices = sorted(
        [normalize_edge_device(event, now) for event in collect_latest_devices(api_base_url)],
        key=lambda device: device["device_id"],
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": format_utc(now),
        "overall_status": calculate_overall_status(core_services, readiness, edge_devices),
        "core": {
            "readiness": readiness,
            "services": core_services,
        },
        "edge_devices": edge_devices,
    }


def write_status_file(status: dict[str, Any], target_path: Path) -> bool:
    body = json.dumps(status, indent=2, sort_keys=True) + "\n"
    if target_path.exists() and target_path.read_text(encoding="utf-8") == body:
        return False
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(body, encoding="utf-8")
    return True


def publish_status(repo_dir: Path, status_path: str, commit_message: str, push: bool) -> PublishResult:
    target = Path(status_path)
    subprocess.run(["git", "add", "--", str(target)], cwd=repo_dir, check=True)  # nosec B603 B607
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo_dir, check=False)  # nosec B603 B607
    if diff.returncode == 0:
        return PublishResult(changed=False, committed=False, pushed=False, message="status unchanged")
    subprocess.run(["git", "commit", "-m", commit_message], cwd=repo_dir, check=True)  # nosec B603 B607
    pushed = False
    if push:
        subprocess.run(["git", "push"], cwd=repo_dir, check=True)  # nosec B603 B607
        pushed = True
    return PublishResult(changed=True, committed=True, pushed=pushed, message="status published")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish sanitized Senior Pomidor status for GitHub Pages.")
    parser.add_argument("--project-dir", default=".", help="Core server Docker Compose project directory.")
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL, help="Local Core API base URL.")
    parser.add_argument("--output", help="Write status JSON to this path without committing.")
    parser.add_argument("--pages-repo", help="Checkout/worktree of senior-pomidor-plant-v2 status-data branch.")
    parser.add_argument("--status-path", default=DEFAULT_STATUS_PATH, help="Status JSON path inside pages repo.")
    parser.add_argument("--push", action="store_true", help="Push the status commit after committing.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = build_status_document(Path(args.project_dir), args.api_base_url)
    if args.output:
        changed = write_status_file(status, Path(args.output))
        print("status file written" if changed else "status file unchanged")
        return 0
    if not args.pages_repo:
        json.dump(status, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    repo_dir = Path(args.pages_repo)
    changed = write_status_file(status, repo_dir / args.status_path)
    if not changed:
        print("status file unchanged")
        return 0
    result = publish_status(
        repo_dir,
        args.status_path,
        f"Update public status {status['generated_at_utc']}",
        args.push,
    )
    print(result.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
