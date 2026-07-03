# Changelog

## server-v0.1.0 - 2026-07-03

First public server-side release for the Senior Pomidor open embodied AI tomato-growing project.

This release provides a trusted-LAN server for collecting edge-node telemetry, storing plant and system-health data, serving read APIs, uploading photos, supporting local dashboards, and preparing the data foundation for future state estimation, world modeling, control, and public datasets.

Included:

- FastAPI server with `/api/v1` telemetry, device, history, photo, health, readiness, and dashboard endpoints.
- HTTP telemetry ingestion and MQTT telemetry worker.
- Telemetry schemas `senior-pomidor.edge.telemetry.v1` and `senior-pomidor.edge.telemetry.v2`.
- Photo upload, metadata storage, and local photo retrieval with idempotent `photo_id` handling.
- PostgreSQL storage via Docker Compose, with Alembic migrations.
- Grafana provisioning for telemetry panels and alerts.
- Optional sanitized Grafana Cloud metrics export.
- Operations, backup/restore, Raspberry Pi integration, capacity planning, and public data policy docs.
- CI coverage for tests, linting, typing, security checks, dependency audit, and Docker vulnerability scans.

Known limitations:

- Designed for trusted LAN deployment, not direct public internet exposure.
- HTTP telemetry and photo upload bearer tokens are optional and disabled unless configured.
- MQTT auth is not enabled by default.
- Public dataset export is not implemented yet.
- Future contracts such as `state_v1`, `action_v1`, `anomaly_v1`, `forecast_36h_v1`, `targets_v1`, and `weather_adapter_log_v1` are not implemented in this release.
- Photo metadata can theoretically exist without a file after a crash between the database commit and final file placement.
- Retention cleanup is dry-run only.
