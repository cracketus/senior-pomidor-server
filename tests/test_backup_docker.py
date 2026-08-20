import json
import os
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

import pytest

from tools.backup import BackupConfig, create_backup, verify_manifest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BACKUP_DOCKER_E2E") != "1",
    reason="set RUN_BACKUP_DOCKER_E2E=1 to run the isolated backup snapshot test",
)

ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "senior-pomidor-backup-e2e"


def compose(data_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "APP_IMAGE": "senior-pomidor-server:backup-e2e",
            "API_PUBLISHED_PORT": "28080",
            "POSTGRES_PUBLISHED_PORT": "25432",
            "MQTT_PUBLISHED_PORT": "21883",
            "PHOTO_DATA_DIR": str(data_root / "photos"),
            "ESTIMATOR_PRIVATE_DATA_DIR": str(data_root / "estimator-private"),
            "MOSQUITTO_DATA_DIR": str(data_root / "mosquitto"),
            "POSTGRES_DATA_DIR": str(data_root / "postgres"),
            "GRAFANA_DATA_DIR": str(data_root / "grafana"),
            "OLLAMA_DATA_DIR": str(data_root / "ollama"),
        }
    )
    return subprocess.run(  # nosec B603 B607
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.dev.yml",
            "-p",
            PROJECT_NAME,
            *args,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=check,
    )


def wait_for_postgres(data_root: Path) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = compose(
            data_root,
            "exec",
            "-T",
            "postgres",
            "pg_isready",
            "-U",
            "senior_pomidor",
            "-d",
            "senior_pomidor",
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise AssertionError("postgres did not become ready")


def test_compose_snapshot_contains_custom_dump_and_representative_archives(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.TemporaryDirectory(prefix="senior-pomidor-backup-e2e-") as temp:
        data_root = Path(temp)
        for name in ("photos", "estimator-private", "mosquitto", "postgres", "grafana", "ollama"):
            (data_root / name).mkdir()
        (data_root / "photos" / "representative.jpg").write_bytes(b"representative-photo")
        (data_root / "estimator-private" / "state.jsonl").write_text("{}\n", encoding="utf-8")
        try:
            compose(
                data_root,
                "up",
                "-d",
                "--build",
                "postgres",
                "mosquitto",
                "api",
                "worker",
                "state-estimator-worker",
            )
            wait_for_postgres(data_root)
            protected_mosquitto = compose(
                data_root,
                "exec",
                "-T",
                "--user",
                "1883:1883",
                "mosquitto",
                "sh",
                "-eu",
                "-c",
                "umask 027; printf protected-service-data > /mosquitto/data/protected.db; "
                "chmod 750 /mosquitto/data; chmod 640 /mosquitto/data/protected.db",
                check=False,
            )
            assert protected_mosquitto.returncode == 0, protected_mosquitto.stderr
            monkeypatch.setenv("APP_IMAGE", "senior-pomidor-server:backup-e2e")
            monkeypatch.setenv("PHOTO_DATA_DIR", str(data_root / "photos"))
            monkeypatch.setenv("ESTIMATOR_PRIVATE_DATA_DIR", str(data_root / "estimator-private"))
            monkeypatch.setenv("MOSQUITTO_DATA_DIR", str(data_root / "mosquitto"))
            monkeypatch.setenv("POSTGRES_DATA_DIR", str(data_root / "postgres"))
            monkeypatch.setenv("GRAFANA_DATA_DIR", str(data_root / "grafana"))
            result = create_backup(
                BackupConfig(
                    project_dir=ROOT,
                    backup_root=data_root / "backups",
                    compose_files=(ROOT / "docker-compose.yml", ROOT / "docker-compose.dev.yml"),
                    project_name=PROJECT_NAME,
                )
            )
            assert result["status"] == "complete", json.dumps(result, indent=2)
            backup_dir = Path(result["backup_directory"])
            assert verify_manifest(backup_dir)["valid"] is True
            assert (backup_dir / "database.dump").read_bytes()[:5] == b"PGDMP"
            with tarfile.open(backup_dir / "photo_data.tar.gz", "r:gz") as archive:
                names = {Path(name).name for name in archive.getnames()}
            assert "representative.jpg" in names
            with tarfile.open(backup_dir / "estimator_private_data.tar.gz", "r:gz") as archive:
                names = {Path(name).name for name in archive.getnames()}
            assert "state.jsonl" in names
            with tarfile.open(backup_dir / "mosquitto_data.tar.gz", "r:gz") as archive:
                names = {Path(name).name for name in archive.getnames()}
            assert "protected.db" in names
        finally:
            compose(data_root, "down", check=False)
