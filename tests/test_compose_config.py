from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.yml"
GRAFANA_READER_INIT_PATH = ROOT / "docker/postgres/init-grafana-reader.sh"
SYSTEMD_PATH = ROOT / "deploy/systemd/senior-pomidor.service"
ENV_EXAMPLE_PATH = ROOT / ".env.example"


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


def test_production_network_and_database_configuration_is_parameterized() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    example = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")

    assert "${LAN_BIND_ADDRESS:-127.0.0.1}:${API_PUBLISHED_PORT:-8000}:8000" in compose
    assert "${LAN_BIND_ADDRESS:-127.0.0.1}:${MQTT_PUBLISHED_PORT:-1883}:1883" in compose
    assert "${POSTGRES_BIND_ADDRESS:-127.0.0.1}:${POSTGRES_PUBLISHED_PORT:-5432}:5432" in compose
    assert "POSTGRES_DB: ${POSTGRES_DB:-senior_pomidor}" in compose
    assert "POSTGRES_USER: ${POSTGRES_USER:-senior_pomidor}" in compose
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-senior_pomidor}" in compose
    assert "POSTGRES_PASSWORD=CHANGE_ME_DATABASE_PASSWORD" in example
    assert "POSTGRES_BIND_ADDRESS=127.0.0.1" in example


def test_optional_llm_profile_is_local_pinned_and_bootstrapped() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    example = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")

    assert "image: ${OLLAMA_IMAGE:-ollama/ollama:0.31.1}" in compose
    assert '"127.0.0.1:${OLLAMA_PUBLISHED_PORT:-11434}:11434"' in compose
    assert "ollama_models:/root/.ollama" in compose
    assert "ollama-model-pull:" in compose
    assert 'command: ["pull", "${DAILY_STORY_OLLAMA_MODEL:-llama3.2:3b}"]' in compose
    assert "daily-story-worker:" in compose
    assert "command: python -m app.daily_story_worker" in compose
    assert compose.count("- llm") == 3
    assert "daily_story_skipped_no_data" in compose
    assert "DAILY_STORY_OLLAMA_KEEP_ALIVE=0" in example
    assert "DAILY_STORY_MAX_ATTEMPTS=3" in example
    assert "DAILY_STORY_RETRY_DELAY_MINUTES=15" in example


def test_systemd_unit_waits_for_docker_and_readiness() -> None:
    unit = SYSTEMD_PATH.read_text(encoding="utf-8")

    assert "Requires=docker.service" in unit
    assert "After=docker.service network-online.target" in unit
    assert "WorkingDirectory=/opt/senior-pomidor-server" in unit
    assert "EnvironmentFile=/opt/senior-pomidor-server/.env" in unit
    assert "docker compose up -d --remove-orphans" in unit
    assert "/ready" in unit
    assert "ExecStop=/usr/bin/docker compose stop" in unit
    assert "WantedBy=multi-user.target" in unit
