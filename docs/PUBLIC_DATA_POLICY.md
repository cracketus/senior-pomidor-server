# Public Data And Privacy Policy

Senior Pomidor is local-first. Public outputs must be deliberate projections, not raw database exports.

## Publishable By Default

- low-cardinality plant metrics selected for Grafana Cloud export
- public status fields from `tools.public_status`
- aggregate freshness and service status
- sanitized network health fields: Wi-Fi connected state, Wi-Fi profile count, DNS/internet reachability, last recovery result, and last recovery exit code

## Not Publishable

- secrets, bearer tokens, database credentials, or environment variables
- raw telemetry payload JSON
- MQTT topics that expose device naming conventions beyond documented public device IDs
- SSID, IP address, hostnames, local ports, file paths, container IDs, logs, or stack traces
- exact private location or Wi-Fi environment details
- photo EXIF, private background imagery, or images not reviewed for public release
- sensor error details that reveal host paths, command output, local hardware inventory, or private network state

## Photos And AI Analysis

Photos and offline AI analysis JSONL are private by default. Before any image or model output is published:

- review the image for private background content
- strip or verify absence of sensitive image metadata
- confirm the analysis text uses observation language, not diagnosis claims
- remove exact timestamps or device identifiers when not needed

Plant-health language should be framed as a risk proxy, for example "dry-soil risk" or "VPD stress risk", not as a definitive disease diagnosis.

## Release Checklist

Before publishing metrics, images, reports, or datasets:

- confirm the output is a sanitized projection, not a raw export
- inspect for SSID, IP address, paths, logs, secrets, and private location data
- confirm images have been reviewed for background content and metadata
- document the schema, retention expectation, and intended audience
- keep PostgreSQL as the local source of truth
