import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "docker/grafana/provisioning/dashboards/json/senior-pomidor-telemetry.json"
EDGE_DASHBOARD_PATH = ROOT / "docker/grafana/provisioning/dashboards/json/senior-pomidor-edge-reliability.json"
DATASOURCE_PATH = ROOT / "docker/grafana/provisioning/datasources/postgres.yml"
PROVIDER_PATH = ROOT / "docker/grafana/provisioning/dashboards/senior-pomidor.yml"
ALERTS_PATH = ROOT / "docker/grafana/provisioning/alerting/senior-pomidor-alerts.yml"
EDGE_ALERTS_PATH = ROOT / "docker/grafana/provisioning/alerting/edge-reliability-alerts.yml"
EDGE_SCREENSHOT_PATH = ROOT / "docs/images/edge-reliability-dashboard-demo.svg"


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
    assert "database: ${POSTGRES_DB}" in datasource
    assert "path: /etc/grafana/provisioning/dashboards/json" in provider
    assert DASHBOARD_PATH.is_file()
    assert ALERTS_PATH.is_file()
    assert EDGE_DASHBOARD_PATH.is_file()
    assert EDGE_ALERTS_PATH.is_file()
    assert EDGE_SCREENSHOT_PATH.is_file()


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
        "Latest Device And Network Status",
        "Recent Photo Metadata",
        "Latest State Summary",
        "Canonical Env VPD",
        "State Confidence",
        "Average Soil Moisture",
        "Latest Sensor Health Summary",
        "Active Anomalies",
        "Latest Guardrail Status",
        "Simulated Actions Over Time",
        "Blocked Actions By Reason",
        "Sampling Recommendations",
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
        "state_snapshots",
        "sensor_health_snapshots",
        "anomaly_records",
        "action_simulations",
        "payload_jsonb #>> '{env,vpd_kpa}'",
        "payload_jsonb #>> '{quality,state_confidence}'",
        "payload_jsonb #>> '{soil,avg_moisture_pct}'",
        "payload_jsonb #>> '{guardrails,level}'",
        "payload_jsonb #>> '{sampling_recommendation,recommended_poll_seconds}'",
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
        "Edge network health failures",
        "Critical dry soil",
        "VPD too low",
        "VPD condensation risk",
        "VPD high",
        "VPD stress",
        "VPD critical",
        "VPD emergency",
        "State VPD guardrail crossed",
        "State VPD critical",
        "State confidence low",
        "Active high or critical anomaly",
        "State snapshot stale",
    ):
        assert f"title: {title}" in alerts

    for table_or_view in (
        "devices",
        "telemetry_pod_readings_flat",
        "pod_errors",
        "telemetry_events",
        "state_snapshots",
        "anomaly_records",
    ):
        assert table_or_view in alerts

    for threshold in (
        "interval '10 minutes'",
        "interval '20 minutes'",
        "interval '15 minutes'",
        "for: 5m",
        "for: 30m",
        "cpu_temp_c",
        "75.0::double precision",
        "wifi_rssi_dbm",
        "-75.0::double precision",
        "wifi_connected",
        "wifi_profile_count",
        "internet_reachable",
        "last_recovery_exit_code",
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
        "payload_jsonb #>> '{env,vpd_kpa}'",
        "payload_jsonb #>> '{quality,state_confidence}'",
        "status = 'ACTIVE'",
        "latest_state_ts < now() - interval '20 minutes'",
    ):
        assert threshold in alerts


def test_edge_reliability_dashboard_has_safe_current_and_history_views():
    dashboard = json.loads(EDGE_DASHBOARD_PATH.read_text(encoding="utf-8"))
    queries = panel_queries(dashboard)
    panel_titles = {panel["title"] for panel in dashboard["panels"]}

    assert dashboard["uid"] == "senior-pomidor-edge-reliability"
    assert dashboard["title"] == "Senior Pomidor Edge Reliability"
    assert {variable["name"] for variable in dashboard["templating"]["list"]} == {"device_id"}
    assert "senior-pomidor-postgres" in json.dumps(dashboard)
    assert {
        "Current Reliability States",
        "Suppression And Recovery Counters",
        "Telemetry And Reliability Freshness",
        "Backlog And Storage Pressure",
        "Restart And Reboot Timeline",
        "Backlog Timeline",
        "Recovery And Degradation State Timeline",
    }.issubset(panel_titles)

    current = find_panel(dashboard, "Current Reliability States")["targets"][0]["rawSql"]
    application_case = current.split("END AS spool_status,", 1)[1].split("END AS application_status", 1)[0]
    aggregate_case = current.split("END AS application_status,", 1)[1].split("END AS aggregate_status", 1)[0]
    overall_case = current.split("SELECT device_id,CASE", 1)[1].split("END AS overall_status", 1)[0]
    assert "FROM devices d" in current
    assert "LEFT JOIN LATERAL" in current
    assert "ORDER BY te.timestamp_utc DESC, te.id DESC" in current
    assert "THEN 'UNKNOWN'" in current
    assert "interval '20 minutes'" in current
    assert aggregate_case.startswith(
        "CASE WHEN timestamp_utc IS NULL OR timestamp_utc>now() "
        "OR timestamp_utc<now()-interval '20 minutes' THEN 'UNKNOWN'"
    )
    component_unknown = "WHEN 'UNKNOWN' IN (watchdog_status,spool_status,application_status) THEN 'UNKNOWN'"
    aggregate_warning = "WHEN 'WARN' IN (watchdog_status,spool_status,application_status,aggregate_status) THEN 'WARN'"
    assert component_unknown in overall_case
    assert aggregate_warning in overall_case
    assert overall_case.index(component_unknown) < overall_case.index(aggregate_warning)
    invalid_service_manager = (
        "WHEN system_health_jsonb->'application' ? 'service_manager' AND "
        "coalesce(system_health_jsonb #>> '{application,service_manager}','') "
        "NOT IN ('none','systemd') THEN 'UNKNOWN'"
    )
    healthy_systemd = (
        "WHEN system_health_jsonb #>> '{application,process_running}'='true' AND "
        "system_health_jsonb #>> '{application,systemd_available}'='true'"
    )
    assert invalid_service_manager in application_case
    assert healthy_systemd in application_case
    assert application_case.index(invalid_service_manager) < application_case.index(healthy_systemd)
    for allowlist in (
        "('suppressed','budget_exhausted','recovery_suppressed')",
        "('starting','cooldown','maintenance','recovering','recovered','suppression_cleared')",
        "('DEGRADED','CRITICAL')",
    ):
        assert allowlist in current
    for fail_safe_predicate in (
        "jsonb_typeof(system_health_jsonb->'aggregate')<>'object'",
        "system_health_jsonb #>> '{aggregate,schema_version}' IS NULL",
        "system_health_jsonb #>> '{aggregate,state}' IS NULL",
        "system_health_jsonb #>> '{application,service_manager}'='none'",
        "system_health_jsonb #>> '{application,service_manager}' IS NULL",
        "system_health_jsonb #> '{application,systemd_active_state}' IS NULL",
        "system_health_jsonb #> '{application,systemd_sub_state}' IS NULL",
    ):
        assert fail_safe_predicate in current
    assert (
        "system_health_jsonb #>> '{application,systemd_service_name}' IS NULL "
        "AND system_health_jsonb #>> '{application,process_running}'='true'"
    ) not in current

    assert "$__timeFilter(timestamp_utc)" in queries
    assert "database_size_bytes" in queries
    assert "free_space_bytes" in queries
    assert "backlog_bytes" not in queries
    for sensitive in (
        "reason",
        "last_error_code",
        "boot_id",
        "process_id",
        "ip_address",
        "ssid",
        "raw_payload_jsonb",
    ):
        assert sensitive not in queries


def test_edge_reliability_alerts_cover_five_failure_classes_without_hiding_missing_devices():
    alerts = EDGE_ALERTS_PATH.read_text(encoding="utf-8")
    rules = yaml.safe_load(alerts)["groups"][0]["rules"]

    assert len(rules) == 5
    assert alerts.count("      - uid: sp_edge_") == 5
    assert "dashboardUid: senior-pomidor-edge-reliability" in alerts
    assert alerts.count("noDataState: OK") == 5
    assert alerts.count("execErrState: Alerting") == 5
    assert "title: Edge reliability unavailable or stale" in alerts
    assert "title: Edge watchdog critical" in alerts
    assert "title: Edge spool or disk critical" in alerts
    assert "title: Edge aggregate critical" in alerts
    assert "title: Edge application inactive" in alerts
    assert "for: 5m" in alerts
    assert "for: 1m" in alerts

    unavailable_query = alerts.split("title: Edge reliability unavailable or stale", 1)[1].split(
        "title: Edge watchdog critical", 1
    )[0]
    assert "FROM devices d" in unavailable_query
    assert "LEFT JOIN LATERAL" in unavailable_query
    assert "e.timestamp_utc IS NULL" in unavailable_query
    assert "interval '20 minutes'" in unavailable_query
    assert "system_health_jsonb #>> '{watchdog,suppression}' = 'true'" in alerts
    assert "LIKE '%_failed'" in alerts
    assert "#>> '{spool,status}' IN ('DEGRADED','CRITICAL')" in alerts
    assert "#>> '{spool,disk_status}' IN ('DEGRADED','CRITICAL')" in alerts
    assert "#>> '{spool,worker_state}' = 'error'" in alerts
    assert "#>> '{aggregate,schema_version}' = 'senior-pomidor.edge.health.v1'" in alerts
    assert "#>> '{aggregate,state}' = 'CRITICAL'" in alerts
    application_query = alerts.split("title: Edge application inactive", 1)[1]
    assert "#>> '{application,process_running}' = 'false'" in application_query
    assert "#>> '{application,systemd_service_active}' = 'false'" in application_query
    assert "#>> '{application,service_manager}' = 'systemd'" in application_query
    assert "coalesce(e.system_health_jsonb->'application', '{}'::jsonb) ? 'service_manager'" in application_query


def test_edge_reliability_documentation_example_is_synthetic_and_sanitized():
    image = EDGE_SCREENSHOT_PATH.read_text(encoding="utf-8")

    assert "demo-edge-01" in image
    assert "SANITIZED SYNTHETIC DATA" in image
    assert "now - 24h" in image
    for sensitive in ("ssid", "ip_address", "boot_id", "service_name", "reason", "2026-"):
        assert sensitive not in image.lower()
