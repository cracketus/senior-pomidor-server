import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "docker/grafana/provisioning/dashboards/json/senior-pomidor-telemetry.json"
DATASOURCE_PATH = ROOT / "docker/grafana/provisioning/datasources/postgres.yml"
PROVIDER_PATH = ROOT / "docker/grafana/provisioning/dashboards/senior-pomidor.yml"


def load_dashboard() -> dict:
    return json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))


def panel_queries(dashboard: dict) -> str:
    queries: list[str] = []
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            queries.append(target.get("rawSql", ""))
    return "\n".join(queries)


def test_grafana_dashboard_provisioning_files_reference_checked_in_dashboard():
    datasource = DATASOURCE_PATH.read_text(encoding="utf-8")
    provider = PROVIDER_PATH.read_text(encoding="utf-8")

    assert "uid: senior-pomidor-postgres" in datasource
    assert "name: Senior Pomidor PostgreSQL" in datasource
    assert "path: /etc/grafana/provisioning/dashboards/json" in provider
    assert DASHBOARD_PATH.is_file()


def test_grafana_dashboard_json_covers_issue_15_acceptance_criteria():
    dashboard = load_dashboard()
    variables = {variable["name"] for variable in dashboard["templating"]["list"]}
    panel_titles = {panel["title"] for panel in dashboard["panels"]}
    queries = panel_queries(dashboard)

    assert dashboard["uid"] == "senior-pomidor-telemetry"
    assert variables == {"device_id", "pod_key"}
    assert "Senior Pomidor PostgreSQL" not in queries
    assert "senior-pomidor-postgres" in json.dumps(dashboard)
    assert "$__timeFilter" in queries
    assert "telemetry_pod_readings_flat" in queries
    assert "telemetry_events" in queries
    assert "photos" in queries
    assert "concat('/api/v1/photos/', photo_id)" in queries

    assert {
        "Soil Moisture",
        "Soil Temperature",
        "Air Temperature",
        "Air Humidity",
        "Air Pressure",
        "Light",
        "Leaf Temperature",
        "Latest Telemetry By Pod",
        "Latest Device Status",
        "Recent Photo Metadata",
    }.issubset(panel_titles)

    for metric in (
        "soil_moisture_percent",
        "soil_temperature_c",
        "air_temperature_c",
        "air_humidity_percent",
        "air_pressure_hpa",
        "light_lux",
        "leaf_temp_c",
    ):
        assert metric in queries
