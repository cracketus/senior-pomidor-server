from app.validation import TELEMETRY_SCHEMA


def telemetry_payload() -> dict:
    return {
        "schema_version": TELEMETRY_SCHEMA,
        "device_id": "pi-001",
        "timestamp_utc": "2026-07-02T08:00:00Z",
        "pods": {
            "pod-1": {
                "enabled": True,
                "air_temperature_c": 24.0,
                "air_humidity_percent": 60.0,
                "soil_moisture_percent": 42.0,
                "soil_temperature_c": 20.0,
                "light_lux": 12000.0,
                "leaf_temp_c": 23.5,
                "air_vpd_kpa": 9.99,
                "leaf_vpd_kpa": 9.99,
            }
        },
    }


def test_active_anomaly_is_deduped_and_cleared(client) -> None:
    hot = telemetry_payload()
    hot["pods"]["pod-1"]["air_temperature_c"] = 33.0
    hot["pods"]["pod-1"]["air_humidity_percent"] = 35.0
    assert client.post("/api/v1/edge/telemetry", json=hot).status_code == 202
    first_state = client.get("/api/v1/state/latest?node_id=pi-001").json()
    first_active = client.get("/api/v1/anomalies/active?node_id=pi-001").json()
    first_heat = next(item for item in first_active if item["type"] == "CRITICAL_HEAT")

    hotter = telemetry_payload()
    hotter["timestamp_utc"] = "2026-07-02T08:01:00Z"
    hotter["pods"]["pod-1"]["air_temperature_c"] = 34.0
    hotter["pods"]["pod-1"]["air_humidity_percent"] = 35.0
    assert client.post("/api/v1/edge/telemetry", json=hotter).status_code == 202
    second_state = client.get("/api/v1/state/latest?node_id=pi-001").json()
    second_active = client.get("/api/v1/anomalies/active?node_id=pi-001").json()
    second_heat = next(item for item in second_active if item["type"] == "CRITICAL_HEAT")
    assert second_heat["anomaly_id"] == first_heat["anomaly_id"]
    assert second_heat["duration_seconds"] == 60
    assert first_state["refs"]["anomaly_ids"]
    assert second_state["refs"]["anomaly_ids"]

    normal = telemetry_payload()
    normal["timestamp_utc"] = "2026-07-02T08:02:00Z"
    assert client.post("/api/v1/edge/telemetry", json=normal).status_code == 202
    cleared_state = client.get("/api/v1/state/latest?node_id=pi-001").json()
    cleared_active = client.get("/api/v1/anomalies/active?node_id=pi-001").json()
    assert "CRITICAL_HEAT" not in {item["type"] for item in cleared_active}
    assert first_heat["anomaly_id"] not in cleared_state["refs"]["anomaly_ids"]


def test_state_latest_generates_from_current_telemetry(client) -> None:
    assert client.post("/api/v1/edge/telemetry", json=telemetry_payload()).status_code == 202

    response = client.get("/api/v1/state/latest?node_id=pi-001")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "state_v1"
    assert body["node_id"] == "pi-001"
    assert body["env"]["air_temp_c"] == 24.0
    assert body["env"]["vpd_kpa"] != 9.99
    assert body["soil"]["avg_moisture_pct"] == 42.0
    assert body["quality"]["level"] in {"GOOD", "DEGRADED"}


def test_sensor_health_and_active_anomalies_read_persisted_outputs(client) -> None:
    payload = telemetry_payload()
    payload["pods"]["pod-1"]["air_temperature_c"] = 33.0
    payload["pods"]["pod-1"]["air_humidity_percent"] = 35.0
    assert client.post("/api/v1/edge/telemetry", json=payload).status_code == 202
    assert client.get("/api/v1/state/latest?node_id=pi-001").status_code == 200

    health = client.get("/api/v1/sensor-health/latest?node_id=pi-001")
    assert health.status_code == 200
    assert health.json()["schema_version"] == "sensor_health_v1"

    anomalies = client.get("/api/v1/anomalies/active?node_id=pi-001")
    assert anomalies.status_code == 200
    assert "CRITICAL_HEAT" in {item["type"] for item in anomalies.json()}


def test_replay_endpoint_is_disabled_by_default(client) -> None:
    response = client.post("/api/v1/state-estimator/replay", json={"observations": []})
    assert response.status_code == 404
