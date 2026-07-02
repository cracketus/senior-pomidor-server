from __future__ import annotations

import argparse
import json
import socket
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    message: str
    details: dict[str, Any]


def get_json(url: str, timeout_seconds: float) -> tuple[int | None, Any | None, str | None]:
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"}:
        return None, None, "Only http and https URLs are supported"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
            return response.status, json.loads(response.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except json.JSONDecodeError:
            payload = None
        return exc.code, payload, None
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        return None, None, exc.__class__.__name__


def check_api(api_base_url: str, timeout_seconds: float) -> CheckResult:
    status_code, payload, error = get_json(f"{api_base_url.rstrip('/')}/health", timeout_seconds)
    ok = status_code == 200 and isinstance(payload, dict) and payload.get("status") == "ok"
    return CheckResult(
        name="api",
        status="ok" if ok else "failed",
        message="API health endpoint is reachable" if ok else "API health endpoint is not healthy",
        details={"status_code": status_code, "error": error},
    )


def check_readiness(api_base_url: str, timeout_seconds: float) -> CheckResult:
    status_code, payload, error = get_json(f"{api_base_url.rstrip('/')}/ready", timeout_seconds)
    ready = isinstance(payload, dict) and payload.get("ready") is True
    return CheckResult(
        name="readiness",
        status="ok" if ready else "failed",
        message="Database migrations are current" if ready else "Server readiness check is not passing",
        details={
            "status_code": status_code,
            "database": payload.get("database") if isinstance(payload, dict) else None,
            "migration": payload.get("migration") if isinstance(payload, dict) else None,
            "current_revision": payload.get("current_revision") if isinstance(payload, dict) else None,
            "head_revision": payload.get("head_revision") if isinstance(payload, dict) else None,
            "error": error or (payload.get("error") if isinstance(payload, dict) else None),
        },
    )


def check_mqtt(host: str, port: int, timeout_seconds: float) -> CheckResult:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            pass
    except OSError as exc:
        return CheckResult(
            name="mqtt",
            status="failed",
            message="MQTT broker TCP port is not reachable",
            details={"host": host, "port": port, "error": exc.__class__.__name__},
        )
    return CheckResult(
        name="mqtt",
        status="ok",
        message="MQTT broker TCP port is reachable",
        details={"host": host, "port": port},
    )


def check_photo_storage(photo_storage_dir: Path) -> CheckResult:
    try:
        photo_storage_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".edge-readiness-", dir=photo_storage_dir, delete=False) as handle:
            handle.write(b"ok")
            temp_path = Path(handle.name)
        temp_path.unlink()
    except OSError as exc:
        return CheckResult(
            name="photo_storage",
            status="failed",
            message="Photo storage is not writable",
            details={"path": str(photo_storage_dir), "error": exc.__class__.__name__},
        )
    return CheckResult(
        name="photo_storage",
        status="ok",
        message="Photo storage is writable",
        details={"path": str(photo_storage_dir)},
    )


def run_checks(
    *,
    api_base_url: str,
    mqtt_host: str,
    mqtt_port: int,
    photo_storage_dir: Path,
    timeout_seconds: float,
) -> list[CheckResult]:
    return [
        check_api(api_base_url, timeout_seconds),
        check_readiness(api_base_url, timeout_seconds),
        check_mqtt(mqtt_host, mqtt_port, timeout_seconds),
        check_photo_storage(photo_storage_dir),
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify server readiness for a Raspberry Pi edge device.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--photo-storage-dir", default="data/photos")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    checks = run_checks(
        api_base_url=args.api_base_url,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        photo_storage_dir=Path(args.photo_storage_dir),
        timeout_seconds=args.timeout_seconds,
    )
    ready = all(check.status == "ok" for check in checks)
    payload = {"ready": ready, "checks": [asdict(check) for check in checks]}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("ready" if ready else "not ready")
        for check in checks:
            print(f"{check.status.upper():7} {check.name}: {check.message}")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
