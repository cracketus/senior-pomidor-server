import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "docker/grafana/provisioning/dashboards/json/senior-pomidor-telemetry.json"
DATASOURCE_PATH = ROOT / "docker/grafana/provisioning/datasources/postgres.yml"
PROVIDER_PATH = ROOT / "docker/grafana/provisioning/dashboards/senior-pomidor.yml"
ALERTS_PATH = ROOT / "docker/grafana/provisioning/alerting/senior-pomidor-alerts.yml"


def load_dashboard() -> dict:
    return json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))


def panel_queries(dashboard: dict) -> str:
    queries: list[str] = []
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            queries.append(target.get("rawSql", ""))
    return "\n".join(queries)


def find_panel(dashboard: dict, title: str) -> dict:
    return next(panel for panel in dashboard["panels"] if panel["title"] == title)


def test_grafana_dashboard_provisioning_files_reference_checked_in_dashboard():
    datasource = DATASOURCE_PATH.read_text(encoding="utf-8")
    provider = PROVIDER_PATH.read_text(encoding="utf-8")

    assert "uid: senior-pomidor-postgres" in datasource
    assert "name: Senior Pomidor PostgreSQL" in datasource
    assert "path: /etc/grafana/provisioning/dashboards/json" in provider
    assert DASHBOARD_PATH.is_file()
    assert ALERTS_PATH.is_file()


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
        "Air VPD",
        "Leaf VPD",
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
        "air_actual_vapor_pressure_kpa",
        "air_saturation_vapor_pressure_kpa",
        "air_vpd_kpa",
        "light_lux",
        "leaf_temp_c",
        "leaf_saturation_vapor_pressure_kpa",
        "leaf_vpd_kpa",
    ):
        assert metric in queries


def test_grafana_air_vpd_panel_shows_documented_thresholds():
    dashboard = load_dashboard()
    air_vpd_panel = find_panel(dashboard, "Air VPD")

    assert air_vpd_panel["fieldConfig"]["defaults"]["custom"]["thresholdsStyle"] == {"mode": "line"}
    assert air_vpd_panel["fieldConfig"]["defaults"]["thresholds"]["steps"] == [
        {"color": "red", "value": None},
        {"color": "orange", "value": 0.4},
        {"color": "yellow", "value": 0.5},
        {"color": "green", "value": 0.8},
        {"color": "yellow", "value": 1.3},
        {"color": "orange", "value": 1.6},
        {"color": "red", "value": 2.5},
        {"color": "dark-red", "value": 4},
    ]


def test_grafana_alerting_provisioning_covers_collection_and_health_alerts():
    alerts = ALERTS_PATH.read_text(encoding="utf-8")

    assert "apiVersion: 1" in alerts
    assert "folder: Senior Pomidor Alerts" in alerts
    assert "interval: 60s" in alerts
    assert "datasourceUid: senior-pomidor-postgres" in alerts
    assert "datasourceUid: __expr__" in alerts
    assert "dashboardUid: senior-pomidor-telemetry" in alerts
    assert "noDataState: OK" in alerts
    assert "execErrState: Alerting" in alerts

    for title in (
        "Device telemetry stale",
        "Pod telemetry stale",
        "Pod sensor errors",
        "System health threshold crossed",
        "System health probe errors",
        "Critical dry soil",
        "VPD too low",
        "VPD condensation risk",
        "VPD high",
        "VPD stress",
        "VPD critical",
        "VPD emergency",
    ):
        assert f"title: {title}" in alerts

    for table_or_view in (
        "devices",
        "telemetry_pod_readings_flat",
        "pod_errors",
        "telemetry_events",
    ):
        assert table_or_view in alerts

    for threshold in (
        "interval '10 minutes'",
        "interval '15 minutes'",
        "for: 5m",
        "for: 30m",
        "cpu_temp_c",
        "75.0::double precision",
        "wifi_rssi_dbm",
        "-75.0::double precision",
        "disk_usage_percent",
        "85.0::double precision",
        "io_wait_percent",
        "20.0::double precision",
        "bus_voltage_v",
        "3.1::double precision",
        "bus_current_ma",
        "500.0::double precision",
        "soil_moisture_percent < 10",
        "air_vpd_kpa",
        "air_vpd_kpa >= 0.4",
        "air_vpd_kpa < 0.5",
        "air_vpd_kpa < 0.4",
        "air_vpd_kpa > 1.3",
        "air_vpd_kpa <= 1.6",
        "air_vpd_kpa > 1.6",
        "air_vpd_kpa <= 2.5",
        "air_vpd_kpa > 2.5",
        "air_vpd_kpa <= 4.0",
        "air_vpd_kpa > 4.0",
        "for: 15m",
        "for: 10m",
        "for: 3m",
        "for: 1m",
        "severity: alert",
        "severity: critical",
        "severity: emergency",
    ):
        assert threshold in alerts
