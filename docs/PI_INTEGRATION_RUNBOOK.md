# Raspberry Pi Integration Runbook

Use this runbook after the server stack is running on the LAN.

## 1. Choose Server LAN IP

On the server, choose the address reachable from the Raspberry Pi, for example `192.168.1.50`. Verify from the Pi:

```bash
curl http://192.168.1.50:8000/health
curl http://192.168.1.50:8000/ready
```

## 2. Configure Pi Environment

```text
MQTT_HOST=192.168.1.50
MQTT_PORT=1883
MQTT_TOPIC_PREFIX=senior-pomidor
HTTP_ENABLED=true
CORE_HTTP_URL=http://192.168.1.50:8000/api/v1/edge/telemetry
PHOTO_UPLOAD_ENABLED=true
PHOTO_UPLOAD_URL=http://192.168.1.50:8000/api/v1/edge/photos
PHOTO_UPLOAD_TOKEN=<server PHOTO_UPLOAD_TOKEN, if configured>
TELEMETRY_UPLOAD_TOKEN=<server TELEMETRY_UPLOAD_TOKEN, if configured>
```

## 3. Verify Server Edge Readiness

Run on the server:

```powershell
python -m tools.edge_readiness --api-base-url http://127.0.0.1:8000 --mqtt-host 127.0.0.1 --photo-storage-dir data/photos
```

Run from the Pi with the server LAN IP:

```bash
curl http://192.168.1.50:8000/health
curl http://192.168.1.50:8000/ready
```

## 4. MQTT Telemetry Publish Test

From the Pi:

```bash
mosquitto_pub -h 192.168.1.50 -p 1883 -t senior-pomidor/pi-001/telemetry -m '{
  "schema_version":"senior-pomidor.edge.telemetry.v2",
  "device_id":"pi-001",
  "timestamp_utc":"2026-07-02T12:00:00Z",
  "pods":{"pod_1":{"enabled":true,"metrics":{"soil_moisture_percent":42.5}}},
  "system_health":{"network":{"wifi_connected":true,"wifi_profile_count":2,"internet_reachable":true,"dns_resolution_ok":true,"last_recovery_result":"not_needed","last_recovery_exit_code":0}}
}'
```

Confirm it is visible:

```bash
curl http://192.168.1.50:8000/api/v1/devices/pi-001/latest
```

## 5. HTTP Telemetry Fallback Test

```bash
curl -X POST http://192.168.1.50:8000/api/v1/edge/telemetry \
  -H 'Content-Type: application/json' \
  -d '{"schema_version":"senior-pomidor.edge.telemetry.v2","device_id":"pi-001","timestamp_utc":"2026-07-02T12:01:00Z","pods":{"pod_1":{"enabled":true,"metrics":{"soil_moisture_percent":41.0}}}}'
```

If `TELEMETRY_UPLOAD_TOKEN` is configured, add:

```bash
-H "Authorization: Bearer $TELEMETRY_UPLOAD_TOKEN"
```

## 6. Photo Upload Test

```bash
curl -X POST http://192.168.1.50:8000/api/v1/edge/photos \
  -F photo_id=pi-001-test-photo \
  -F device_id=pi-001 \
  -F captured_at_utc=2026-07-02T12:02:00Z \
  -F schema_version=senior-pomidor.edge.photo.v1 \
  -F photo=@test.jpg
```

If `PHOTO_UPLOAD_TOKEN` is configured, add:

```bash
-H "Authorization: Bearer $PHOTO_UPLOAD_TOKEN"
```

## 7. Confirm Read APIs

```bash
curl http://192.168.1.50:8000/api/v1/devices
curl http://192.168.1.50:8000/api/v1/devices/latest
curl 'http://192.168.1.50:8000/api/v1/devices/pi-001/telemetry?limit=10'
curl 'http://192.168.1.50:8000/api/v1/devices/pi-001/photos?limit=10'
curl http://192.168.1.50:8000/api/v1/photos/pi-001-test-photo --output downloaded-test.jpg
```
