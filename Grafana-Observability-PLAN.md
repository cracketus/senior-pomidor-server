# Grafana Observability Roadmap

## Summary

Add Grafana as an optional Docker Compose profile, not as a required runtime dependency. Use PostgreSQL as the first datasource because telemetry is already persisted in Grafana-friendly tables. Add Prometheus later only if app/runtime metrics and alerting become important.

Recommended path: **Postgres-backed Grafana dashboards first**, then optional Prometheus.

## Variants

- **Variant A: Keep built-in dashboard**
  - Best for: latest telemetry, recent photos, simple LAN status.
  - Changes: improve `/dashboard` with time-series charts and filters.
  - Lowest complexity, no extra containers.

- **Variant B: Grafana + PostgreSQL datasource**
  - Best for: historical sensor dashboards, per-device/per-pod trends, quick SQL-driven panels.
  - Changes: add `grafana` service, readonly DB user, provisioned datasource, starter dashboards.
  - Recommended default.

- **Variant C: Grafana + Prometheus**
  - Best for: API latency, request counts, worker health, scrape-based service metrics, alerts.
  - Changes: add `/metrics`, Prometheus service, Grafana Prometheus datasource.
  - Useful later, but premature for sensor-data visualization alone.

- **Variant D: Home Assistant / Node-RED**
  - Best for: home automation workflows and device-control dashboards.
  - Better if Senior Pomidor becomes part of broader smart-home automation.

## Key Implementation Changes

- Add optional Compose profile:
  - `grafana` service on port `3000`.
  - persistent `grafana_data` volume.
  - provisioned datasource pointing at existing `postgres`.
  - keep Grafana disabled unless started with an observability profile.

- Add readonly database access:
  - create a dedicated `grafana_reader` PostgreSQL role.
  - grant read-only access to telemetry/photo/device tables.
  - document credentials in `.env.example` without exposing production secrets.

- Add starter dashboards:
  - soil moisture, soil temperature, air temperature, humidity, pressure, light, leaf temperature.
  - filters for `device_id`, `pod_key`, and time range.
  - latest reading/status panels.
  - photo metadata table linking back to existing API photo endpoints.

- Add SQL views only if dashboard queries become repetitive:
  - one flattened telemetry view joining `telemetry_events` and `pod_readings`.
  - keep raw tables unchanged.

- Keep Prometheus out of v1 unless needed:
  - if added later, expose FastAPI metrics at `/metrics`.
  - track request count, latency, error rate, ingestion acceptance/rejection counts, MQTT worker counters.

## Test Plan

- Unit/static checks:
  - existing `python -m pytest -q`.
  - verify no API behavior changes for ingestion/read endpoints.

- Docker checks:
  - start normal stack without Grafana and confirm existing behavior still works.
  - start observability profile and confirm Grafana can connect to Postgres.
  - run a sample telemetry ingestion and verify dashboard panels return data.

- Manual acceptance:
  - Grafana opens at `http://localhost:3000`.
  - dashboard shows sensor trends by device/pod.
  - readonly Grafana DB user cannot write to telemetry tables.

## Assumptions

- Deployment remains a trusted home-LAN Docker Compose stack.
- The first useful goal is historical sensor visualization, not full production service monitoring.
- Grafana should be optional so Raspberry Pi/server deployment stays simple.
- Existing `/dashboard` remains available as the lightweight fallback.
