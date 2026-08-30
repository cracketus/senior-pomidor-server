from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "staging_overnight_check.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(
    BASH is None or os.name == "nt",
    reason="the staging overnight monitor runs in WSL2/Linux bash",
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _fake_commands(fake_bin: Path) -> None:
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "docker",
        """#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >>"$FAKE_COMMAND_LOG"
mode="${FAKE_MODE:-healthy}"

if [[ "${1:-}" == "context" && "${2:-}" == "inspect" ]]; then
  printf 'unix:///var/run/docker.sock\n'
  exit 0
fi
if [[ "${1:-}" == "compose" ]]; then
  if [[ "$*" == *" config --quiet"* ]]; then
    exit 0
  fi
  if [[ "$*" == *" ps -q "* ]]; then
    printf 'cid-%s\n' "${!#}"
    exit 0
  fi
  if [[ "$*" == *" ps" ]]; then
    if [[ "$mode" == "compose-hang" ]]; then
      sleep 10
    fi
    printf 'fake compose ps\n'
    exit 0
  fi
fi
if [[ "${1:-}" == "inspect" ]]; then
  target="${!#}"
  if [[ "$target" == "senior-pomidor-edge-staging" ]]; then
    if [[ "$mode" == "edge-down" ]]; then
      printf 'exited connected\n'
    else
      printf 'running connected\n'
    fi
    exit 0
  fi
  for target in "$@"; do
    [[ "$target" == senior-pomidor-staging-*-1 ]] || continue
    if [[ "$mode" == "worker-unhealthy" && "$target" == "senior-pomidor-staging-worker-1" ]]; then
      printf '/%s|running|unhealthy\n' "$target"
    else
      printf '/%s|running|healthy\n' "$target"
    fi
  done
  exit 0
fi
if [[ "${1:-}" == "exec" ]]; then
  [[ "$mode" != "spool-failure" ]]
  exit
fi
exit 1
""",
    )
    _write_executable(
        fake_bin / "curl",
        """#!/usr/bin/env bash
set -eu
url="${!#}"
mode="${FAKE_MODE:-healthy}"
case "$url" in
  */ready)
    [[ "$mode" == "invalid-ready" ]] && printf '{"ready":false}\n' || printf '{"ready":true}\n'
    ;;
  */health)
    printf '{"status":"ok"}\n'
    ;;
  *edge-staging-ubuntu-01/telemetry*)
    [[ "$mode" == "missing-telemetry" ]] && printf '[]\n' || printf '[{"device_id":"edge-staging-ubuntu-01"}]\n'
    ;;
  *) exit 22 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "date",
        """#!/usr/bin/env bash
set -eu
if [[ "${FAKE_MODE:-healthy}" == "clock-gap" && "${1:-}" == "+%s" ]]; then
  count=0
  [[ -f "$FAKE_DATE_STATE" ]] && count="$(cat "$FAKE_DATE_STATE")"
  case "$count" in
    0|1|2) value=1000 ;;
    *) value=1100 ;;
  esac
  printf '%d' "$((count + 1))" >"$FAKE_DATE_STATE"
  printf '%s\n' "$value"
  exit 0
fi
exec /usr/bin/date "$@"
""",
    )
    _write_executable(
        fake_bin / "sleep",
        """#!/usr/bin/env bash
set -eu
[[ "${FAKE_MODE:-healthy}" == "clock-gap" ]] && exit 0
exec /usr/bin/sleep "$@"
""",
    )


def _run_monitor(
    tmp_path: Path,
    *,
    mode: str = "healthy",
    extra_env: dict[str, str] | None = None,
    once: bool = True,
):
    server_root = tmp_path / "server"
    staging_root = tmp_path / "staging"
    fake_bin = tmp_path / "bin"
    server_root.mkdir()
    (server_root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (server_root / "docker-compose.staging.yml").write_text("services: {}\n", encoding="utf-8")
    (staging_root / "secrets").mkdir(parents=True)
    (staging_root / "secrets" / "staging.env").write_text(
        "\n".join(
            (
                "DEPLOYMENT_MODE=staging",
                "STAGING_INTEROP_NETWORK=senior-pomidor-staging-interop",
                "STAGING_EDGE_CONTAINER_NAME=senior-pomidor-edge-staging",
                "GRAFANA_CLOUD_EXPORT_ENABLED=false",
                "STAGING_API_PUBLISHED_PORT=18000",
                f"APP_IMAGE=ghcr.io/example/staging@sha256:{'a' * 64}",
                f"STAGING_POSTGRES_DATA_DIR={staging_root / 'data' / 'postgres'}",
                f"STAGING_MOSQUITTO_DATA_DIR={staging_root / 'data' / 'mosquitto'}",
                f"STAGING_PHOTO_DATA_DIR={staging_root / 'data' / 'photos'}",
                f"STAGING_ESTIMATOR_PRIVATE_DATA_DIR={staging_root / 'data' / 'estimator-private'}",
                f"STAGING_GRAFANA_DATA_DIR={staging_root / 'data' / 'grafana'}",
                f"STAGING_MOSQUITTO_PASSWORD_FILE={staging_root / 'secrets' / 'mosquitto.password'}",
                f"STAGING_MOSQUITTO_ACL_FILE={staging_root / 'secrets' / 'mosquitto.acl'}",
                f"STAGING_MOSQUITTO_CONFIG_FILE={server_root / 'deploy' / 'staging' / 'mosquitto.conf'}",
                "",
            )
        ),
        encoding="utf-8",
    )
    _fake_commands(fake_bin)

    command_log = tmp_path / "commands.log"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "SERVER_ROOT": str(server_root),
            "STAGING_ROOT": str(staging_root),
            "STAGING_SOAK_DURATION_SECONDS": "60",
            "STAGING_SOAK_INTERVAL_SECONDS": "30",
            "STAGING_SOAK_COMMAND_TIMEOUT_SECONDS": "1",
            "FAKE_MODE": mode,
            "FAKE_COMMAND_LOG": str(command_log),
            "FAKE_DATE_STATE": str(tmp_path / "date-state"),
        }
    )
    if extra_env:
        environment.update(extra_env)

    assert BASH is not None
    command = [BASH, str(SCRIPT)]
    if once:
        command.append("--once")
    result = subprocess.run(
        command,
        cwd=server_root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    result_path = staging_root / "logs" / "staging-overnight-result.json"
    report = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    log_path = staging_root / "logs" / "staging-overnight-check.log"
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    commands = command_log.read_text(encoding="utf-8") if command_log.exists() else ""
    return result, report, log, commands


def test_monitor_passes_only_when_core_edge_and_telemetry_are_healthy(tmp_path: Path) -> None:
    result, report, log, commands = _run_monitor(tmp_path)

    assert result.returncode == 0
    assert report is not None
    assert report["status"] == "PASS"
    assert report["failures"] == 0
    assert "PASS core-service-senior-pomidor-staging-worker-1" in log
    assert "PASS edge-running-and-connected" in log
    assert "PASS edge-spool-status" in log
    assert "PASS edge-telemetry-fresh" in log
    assert all(forbidden not in commands for forbidden in (" up", " down", " restart", " rm", " stop"))


@pytest.mark.parametrize(
    ("mode", "expected_log"),
    [
        ("worker-unhealthy", "FAIL core-service-senior-pomidor-staging-worker-1-not-healthy"),
        ("edge-down", "FAIL edge-not-running-or-connected"),
        ("spool-failure", "FAIL edge-spool-status"),
        ("missing-telemetry", "FAIL edge-telemetry-fresh-invalid-response"),
        ("invalid-ready", "FAIL ready-invalid-response"),
        ("compose-hang", "FAIL compose-ps"),
    ],
)
def test_monitor_fails_closed_for_service_and_command_failures(tmp_path: Path, mode: str, expected_log: str) -> None:
    result, report, log, _ = _run_monitor(tmp_path, mode=mode)

    assert result.returncode == 1
    assert report is not None
    assert report["status"] == "FAIL"
    assert report["failures"] >= 1
    assert expected_log in log


def test_monitor_rejects_non_loopback_api_and_other_compose_project(tmp_path: Path) -> None:
    result, report, _, commands = _run_monitor(
        tmp_path,
        extra_env={
            "STAGING_API_BASE_URL": "https://staging.example.invalid",
            "COMPOSE_PROJECT_NAME": "production-project",
        },
    )

    assert result.returncode == 2
    assert report is None
    assert commands == ""
    assert "COMPOSE_PROJECT_NAME must be senior-pomidor-staging" in result.stderr


def test_monitor_detects_a_suspended_or_missing_check_interval(tmp_path: Path) -> None:
    result, report, log, _ = _run_monitor(
        tmp_path,
        mode="clock-gap",
        extra_env={"STAGING_SOAK_MAX_GAP_SECONDS": "0"},
        once=False,
    )

    assert result.returncode == 1
    assert report is not None
    assert report["status"] == "FAIL"
    assert "FAIL check-gap-observed-100s-allowed-30s" in log
