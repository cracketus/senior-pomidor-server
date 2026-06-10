from datetime import UTC, datetime, timedelta

from app.validation import TELEMETRY_SCHEMA, PHOTO_SCHEMA


def telemetry_payload(timestamp: str = "2026-06-07T12:00:00Z") -> dict:
    return {
        "schema_version": TELEMETRY_SCHEMA,
        "device_id": "pi-001",
        "timestamp_utc": timestamp,
        "pods": {
            "pod-1": {
                "enabled": True,
                "soil_moisture_percent": 42.5,
                "leaf_temp_c": 21.2,
                "battery_mv": 5010,
                "errors": [{"sensor": "soil", "message": "intermittent"}],
            },
            "pod-2": {"enabled": False},
        },
    }


def test_http_telemetry_ingest_and_latest(client):
    response = client.post("/api/v1/edge/telemetry", json=telemetry_payload())
    assert response.status_code == 202

    latest = client.get("/api/v1/devices/pi-001/latest")
    assert latest.status_code == 200
    body = latest.json()
    assert body["device_id"] == "pi-001"
    assert body["readings"][0]["metrics"]["soil_moisture_percent"] == 42.5
    assert body["readings"][0]["metrics"]["battery_mv"] == 5010.0
    assert body["errors"][0]["message"] == "intermittent"


def test_telemetry_persists_disabled_pod_and_unknown_metrics(client):
    response = client.post("/api/v1/edge/telemetry", json=telemetry_payload())
    assert response.status_code == 202

    latest = client.get("/api/v1/devices/pi-001/latest")
    readings = {reading["pod_key"]: reading for reading in latest.json()["readings"]}
    assert readings["pod-1"]["metrics"]["soil_moisture_percent"] == 42.5
    assert readings["pod-1"]["metrics"]["battery_mv"] == 5010.0
    assert readings["pod-2"]["enabled"] is False
    assert readings["pod-2"]["metrics"] == {}


def test_rejects_bad_schema(client):
    payload = telemetry_payload()
    payload["schema_version"] = "wrong"
    response = client.post("/api/v1/edge/telemetry", json=payload)
    assert response.status_code == 400


def test_rejects_timestamp_without_z(client):
    response = client.post("/api/v1/edge/telemetry", json=telemetry_payload("2026-06-07T12:00:00+00:00"))
    assert response.status_code == 400


def test_rejects_malformed_timestamp(client):
    response = client.post("/api/v1/edge/telemetry", json=telemetry_payload("not-a-timestampZ"))
    assert response.status_code == 400


def test_telemetry_history_filters_by_pod(client):
    client.post("/api/v1/edge/telemetry", json=telemetry_payload("2026-06-07T12:00:00Z"))
    client.post("/api/v1/edge/telemetry", json=telemetry_payload("2026-06-07T12:01:00Z"))

    response = client.get("/api/v1/devices/pi-001/telemetry?from=2026-06-07T12:00:30Z&pod=pod-2")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_telemetry_history_supports_since_hours_and_limit(client):
    recent = (datetime.now(UTC) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    older = (datetime.now(UTC) - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    client.post("/api/v1/edge/telemetry", json=telemetry_payload(older))
    client.post("/api/v1/edge/telemetry", json=telemetry_payload(recent))

    response = client.get("/api/v1/devices/pi-001/telemetry?since_hours=1&limit=1")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["timestamp_utc"] == recent


def test_latest_telemetry_by_device(client):
    client.post("/api/v1/edge/telemetry", json=telemetry_payload("2026-06-07T12:00:00Z"))

    response = client.get("/api/v1/devices/latest")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["device_id"] == "pi-001"


def test_photo_upload_is_idempotent(client):
    data = {
        "photo_id": "photo-1",
        "device_id": "pi-001",
        "captured_at_utc": "2026-06-07T12:00:00Z",
        "schema_version": PHOTO_SCHEMA,
        "sharpness_score": "0.91",
    }
    files = {"photo": ("photo.jpg", b"\xff\xd8fake-jpeg\xff\xd9", "image/jpeg")}

    first = client.post("/api/v1/edge/photos", data=data, files=files)
    assert first.status_code == 202
    assert first.json()["created"] is True

    second = client.post("/api/v1/edge/photos", data=data, files=files)
    assert second.status_code == 200
    assert second.json()["created"] is False

    photos = client.get("/api/v1/devices/pi-001/photos")
    assert len(photos.json()) == 1

    download = client.get("/api/v1/photos/photo-1")
    assert download.status_code == 200
    assert download.headers["content-type"] == "image/jpeg"
    assert download.content == b"\xff\xd8fake-jpeg\xff\xd9"


def test_recent_photos_and_photo_list_support_limits(client):
    first = {
        "photo_id": "photo-1",
        "device_id": "pi-001",
        "captured_at_utc": "2026-06-07T12:00:00Z",
        "schema_version": PHOTO_SCHEMA,
    }
    second = {**first, "photo_id": "photo-2", "captured_at_utc": "2026-06-07T12:01:00Z"}
    files = {"photo": ("photo.jpg", b"\xff\xd8fake-jpeg\xff\xd9", "image/jpeg")}

    assert client.post("/api/v1/edge/photos", data=first, files=files).status_code == 202
    assert client.post("/api/v1/edge/photos", data=second, files=files).status_code == 202

    recent = client.get("/api/v1/photos/recent?limit=1")
    assert recent.status_code == 200
    assert [photo["photo_id"] for photo in recent.json()] == ["photo-2"]

    device_photos = client.get("/api/v1/devices/pi-001/photos?limit=1")
    assert device_photos.status_code == 200
    assert len(device_photos.json()) == 1


def test_photo_rejects_non_jpeg(client):
    response = client.post(
        "/api/v1/edge/photos",
        data={
            "photo_id": "photo-1",
            "device_id": "pi-001",
            "captured_at_utc": "2026-06-07T12:00:00Z",
            "schema_version": PHOTO_SCHEMA,
        },
        files={"photo": ("photo.txt", b"not-jpeg", "text/plain")},
    )
    assert response.status_code == 400


def test_photo_requires_configured_bearer_token(client_factory):
    client = client_factory(photo_upload_token="secret")
    data = {
        "photo_id": "photo-1",
        "device_id": "pi-001",
        "captured_at_utc": "2026-06-07T12:00:00Z",
        "schema_version": PHOTO_SCHEMA,
    }
    files = {"photo": ("photo.jpg", b"\xff\xd8fake-jpeg\xff\xd9", "image/jpeg")}

    missing = client.post("/api/v1/edge/photos", data=data, files=files)
    assert missing.status_code == 401

    rejected = client.post("/api/v1/edge/photos", data=data, files=files, headers={"Authorization": "Bearer wrong"})
    assert rejected.status_code == 401

    accepted = client.post("/api/v1/edge/photos", data=data, files=files, headers={"Authorization": "Bearer secret"})
    assert accepted.status_code == 202


def test_photo_rejects_content_over_size_limit(client_factory):
    client = client_factory(photo_max_bytes=4)
    response = client.post(
        "/api/v1/edge/photos",
        data={
            "photo_id": "photo-1",
            "device_id": "pi-001",
            "captured_at_utc": "2026-06-07T12:00:00Z",
            "schema_version": PHOTO_SCHEMA,
        },
        files={"photo": ("photo.jpg", b"\xff\xd8fake-jpeg\xff\xd9", "image/jpeg")},
    )
    assert response.status_code == 413


def test_dashboard_is_served(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Senior Pomidor Dashboard" in response.text
