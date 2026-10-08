# Offline dataset quality and privacy checks (#97)

This is a validator for a bounded snapshot, not a database exporter or public dataset.
Input is UTF-8 JSONL, one existing `/api/v1/devices/{device_id}/telemetry` response item
per line, including `readings`, `schema_version`, `timestamp_utc`, `received_at` and
nullable legacy `record_id`. Preserve source values when preparing a private snapshot.
Do not put raw snapshots in Git. No production extraction is authorized by this command.

```bash
python -m tools.dataset_quality approved-snapshot.jsonl
python -m tools.dataset_quality approved-snapshot.jsonl --expected-interval-seconds 300
```

Maximum 10,000 rows, 256 KiB per line, 500 detailed findings. Empty, malformed, oversized
or unavailable input cannot pass. Output uses `senior-pomidor.dataset-quality.v1`, with
fixed finding codes, row numbers, aggregate counts and input SHA-256; never raw values,
device identifiers, filenames, error text, location, photos or arbitrary payload fields.
Exit0 means inspected rows have no flagged findings; exit1 means findings; exit2 means
input could not be processed. This is not a statement about full-season completeness.

Checks cover supported telemetry v1/v2, safe device/record identifiers, UTC timestamps,
duplicate record IDs and observation identities, observations later than receive time,
out-of-order input, and explicit-unit numeric bounds. Nonfinite values and booleans in
numeric fields are invalid. Nullable/missing metrics are counted, not filled or labelled
healthy. Unknown extra input fields are ignored and never copied to the report.
Plausibility bounds are recorded in `tools/dataset_quality.py`; they do not calibrate
sensors or change ingestion. Leaf VPD may be negative; air VPD cannot.

Cadence is unknown unless explicitly supplied. Gap estimates use sorted distinct times
per device and count unobserved slots between observations; they cannot detect missing
beginning/end intervals or prove why a gap occurred. No observation or receive time is
rewritten. The source file remains byte-identical. Real Season1 acceptance still requires
an owner-approved snapshot and interpretation of known gaps under #302.

Public status hardening follows the existing privacy policy: allowed network fields now
also enforce value types; recovery results use a bounded enum and unknown strings become
null. Service/state/readiness values are allowlisted; unknown service names never fall
back to private container names. Device labels reuse the existing Grafana sanitizer.
Field names/schema remain unchanged; malformed values degrade rather than being published.
This is filtering under the existing policy, not a guarantee that arbitrary user-chosen
identifiers are anonymous. Published IDs still require an owner-approved naming policy.

Run `python -m pytest -q tests/test_dataset_quality.py tests/test_public_status.py
 tests/test_grafana_cloud_exporter.py` on one line. Tests consume actual stored API readback,
validate report schema, preserve the input, and inject synthetic private markers into
unknown fields and allowed fields with wrong types. Existing Grafana exporter tests
continue to guard its exact public metric/label projection. No data is published by tests.
