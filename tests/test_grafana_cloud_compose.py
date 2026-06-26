from pathlib import Path

import pytest

from app.config import Settings
from app.grafana_cloud_exporter import ExporterConfigError, validate_export_settings

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.yml"
ENV_EXAMPLE_PATH = ROOT / ".env.example"


def test_grafana_cloud_exporter_compose_service_is_optional():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "grafana-cloud-exporter:" in compose
    assert "command: python -m app.grafana_cloud_exporter" in compose
    assert "profiles:" in compose
    assert "- cloud-export" in compose
    assert "GRAFANA_CLOUD_API_TOKEN: ${GRAFANA_CLOUD_API_TOKEN:-}" in compose
    assert "depends_on:\n      - postgres" in compose
    assert "api:" in compose
    assert "worker:" in compose
    assert "grafana:" in compose
    assert "- observability" in compose


def test_grafana_cloud_env_defaults_do_not_require_token_until_enabled():
    env_example = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")

    assert "GRAFANA_CLOUD_EXPORT_ENABLED=false" in env_example
    assert "# GRAFANA_CLOUD_API_TOKEN=" in env_example
    validate_export_settings(Settings(grafana_cloud_export_enabled=False, grafana_cloud_api_token=None))

    with pytest.raises(ExporterConfigError, match="GRAFANA_CLOUD_API_TOKEN"):
        validate_export_settings(Settings(grafana_cloud_export_enabled=True, grafana_cloud_api_token=None))
