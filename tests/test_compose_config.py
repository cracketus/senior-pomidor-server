from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DEV = (ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")
PROD = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
ENV = (ROOT / "deploy/senior-pomidor.env.example").read_text(encoding="utf-8")
PROVISION = (ROOT / "deploy/scripts/provision-host.sh").read_text(encoding="utf-8")
INSTALL = (ROOT / "deploy/scripts/install-release.sh").read_text(encoding="utf-8")
BACKUP = (ROOT / "deploy/scripts/backup.sh").read_text(encoding="utf-8")
RESTORE = (ROOT / "deploy/scripts/restore-migration.sh").read_text(encoding="utf-8")
PREFLIGHT = (ROOT / "deploy/scripts/database-preflight.sh").read_text(encoding="utf-8")
SYSTEMD = (ROOT / "deploy/systemd/senior-pomidor.service").read_text(encoding="utf-8")


def test_production_compose_is_application_only_and_uses_platform_network() -> None:
    for service in ("postgres", "grafana", "ollama", "ollama-model-pull"):
        assert f"  {service}:" not in BASE
        assert f"  {service}:" not in PROD
    assert "external: true" in PROD
    assert "${PLATFORM_DOCKER_NETWORK:-srv-platform}" in PROD
    assert "condition: service_healthy\n      postgres:" not in BASE
    assert "/srv/data/postgres" not in BASE + PROD
    assert "/srv/data/grafana" not in BASE + PROD
    assert "/srv/data/ollama" not in BASE + PROD


def test_local_overlay_contains_complete_shared_infrastructure() -> None:
    for service in ("postgres", "grafana", "ollama", "ollama-model-pull"):
        assert f"  {service}:" in DEV
    assert "init-grafana-reader.sh" in DEV
    assert 'command: ["pull", "${DAILY_STORY_OLLAMA_MODEL:-llama3.2:3b}"]' in DEV
    assert "condition: service_healthy" in DEV
    assert "build: ." in DEV


def test_production_environment_exposes_only_platform_interfaces() -> None:
    for setting in ("PLATFORM_DOCKER_NETWORK", "POSTGRES_HOST", "POSTGRES_PORT", "DATABASE_URL"):
        assert f"{setting}=" in ENV
    for removed in (
        "POSTGRES_DATA_DIR",
        "GRAFANA_DATA_DIR",
        "OLLAMA_DATA_DIR",
        "GRAFANA_ADMIN_USER",
        "GRAFANA_ADMIN_PASSWORD",
        "GRAFANA_DB_PASSWORD",
    ):
        assert removed not in ENV
    assert "COMPOSE_PROFILES=cloud-export" in ENV
    assert "DAILY_STORY_OLLAMA_HOST=http://ollama:11434" in ENV


def test_secure_central_paths_and_root_orchestration() -> None:
    assert "/srv/secrets/senior-pomidor" in PROVISION
    assert "/srv/backups/senior-pomidor/daily" in PROVISION
    assert "/srv/backups/senior-pomidor/weekly" in PROVISION
    assert "/srv/backups/senior-pomidor/migration" in PROVISION
    assert "/srv/logs/senior-pomidor/estimator-private" in PROVISION
    assert "-m 0700" in PROVISION
    assert "-m 0600" in PROVISION
    assert "gpasswd -d senior-pomidor docker" in PROVISION
    assert "usermod -aG docker" not in PROVISION
    assert "User=senior-pomidor" not in SYSTEMD
    assert "EnvironmentFile=/srv/secrets/senior-pomidor/runtime.env" in SYSTEMD
    assert "database-preflight.sh" in SYSTEMD
    assert "docker-compose.prod.yml" in SYSTEMD


def test_releases_are_root_controlled_and_stage_under_incoming() -> None:
    assert 'stage="$(mktemp -d "$app_root/releases/.incoming/install.XXXXXX")"' in INSTALL
    assert "chown -R root:root" in INSTALL
    assert "docker-compose.prod.yml" in INSTALL
    assert "$app_root/backups" not in INSTALL


def test_backup_uses_retention_classes_and_pinned_platform_client() -> None:
    assert 'target="$backup_root/$mode/$timestamp"' in BACKUP
    assert "postgres:16-alpine" in BACKUP
    assert '--network "$platform_network"' in BACKUP
    assert "pg_dump" in BACKUP
    assert "pg_dumpall --globals-only --no-role-passwords" in BACKUP
    assert 'find "$backup_root/daily"' in BACKUP
    assert 'find "$backup_root/weekly"' in BACKUP
    assert "grafana" not in BACKUP.lower()
    assert "exec -T postgres" not in BACKUP
    assert "/srv/secrets/senior-pomidor/runtime.env" in BACKUP


def test_restore_guards_shared_services_and_app_data() -> None:
    assert '[[ "$backup_dir" == "$migration_root"/* ]]' in RESTORE
    assert "sha256sum --check SHA256SUMS" in RESTORE
    assert "contains $user_table_count user tables" in RESTORE
    assert "Ignoring legacy grafana.tar.gz" in RESTORE
    assert "postgres:16-alpine" in RESTORE
    assert "exec -T postgres" not in RESTORE
    assert "/srv/data/postgres" not in RESTORE
    assert "/srv/data/grafana" not in RESTORE
    assert "/srv/apps/senior-pomidor/data/public/photos" in RESTORE
    assert "/srv/logs/senior-pomidor/estimator-private" in RESTORE


def test_database_readiness_uses_explicit_platform_settings() -> None:
    for setting in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        assert setting in PREFLIGHT
    assert "postgres:16-alpine" in PREFLIGHT
    assert "pg_isready" in PREFLIGHT


def test_state_estimator_private_logs_use_central_private_log_path() -> None:
    assert "state-estimator-worker:" in BASE
    assert "STATE_ESTIMATOR_PRIVATE_LOG_DIR: /app/data/private" in BASE
    assert "${ESTIMATOR_PRIVATE_DATA_DIR:-/srv/logs/senior-pomidor/estimator-private}" in BASE
