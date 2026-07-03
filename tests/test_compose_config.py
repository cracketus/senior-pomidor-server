from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.yml"
GRAFANA_READER_INIT_PATH = ROOT / "docker/postgres/init-grafana-reader.sh"


def test_compose_runs_state_estimator_worker_with_private_log_volume() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "state-estimator-worker:" in compose
    assert "command: python -m app.state_estimator_worker" in compose
    assert "restart: unless-stopped" in compose
    assert "STATE_ESTIMATOR_ENABLED: ${STATE_ESTIMATOR_ENABLED:-true}" in compose
    assert "STATE_ESTIMATOR_TIMEZONE: ${STATE_ESTIMATOR_TIMEZONE:-Europe/Vienna}" in compose
    assert "STATE_ESTIMATOR_PRIVATE_LOG_DIR: /app/data/private" in compose
    assert "WORKER_HEALTH_FILE: /tmp/senior-pomidor-state-estimator-health.json" in compose
    assert 'test: ["CMD", "python", "-m", "app.worker_healthcheck", "state_estimator_healthy"]' in compose
    assert "estimator_private_data:/app/data/private" in compose
    assert "estimator_private_data:" in compose
    assert "condition: service_completed_successfully" in compose
    assert "condition: service_healthy" in compose


def test_grafana_reader_grants_include_estimator_tables() -> None:
    init_script = GRAFANA_READER_INIT_PATH.read_text(encoding="utf-8")

    for table in (
        "state_snapshots",
        "sensor_health_snapshots",
        "anomaly_records",
        "estimator_diagnostics",
    ):
        assert f"('{table}')" in init_script
