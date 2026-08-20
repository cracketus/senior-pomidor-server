# Senior Pomidor Server v0.2.4

Release date: 2026-08-20

## Summary

v0.2.4 adds durable telemetry idempotency for edge-provided record IDs and makes HTTP acknowledgements compatible with the released edge spool. It also updates the Debian runtime packages in the Docker image so fixed security updates are installed during image build.

## Highlights

- Added nullable, globally unique telemetry_events.record_id.
- Added Alembic migration 0009_telemetry_record_id.
- Added strict record_id validation:
  - 1–128 characters;
  - only A–Z, a–z, 0–9, underscore, dot, colon, and hyphen.
- First delivery returns HTTP 202 with status accepted.
- Identical replay returns HTTP 202 with status duplicate.
- Permanent payload errors return HTTP 200 with status rejected and a bounded error_code.
- Temporary storage failures return HTTP 503 with status retry and storage_unavailable.
- Conflicting content never overwrites the original event.
- MQTT and HTTP now share the same record identity.
- Legacy telemetry without record_id remains supported for one release cycle.
- Added bounded structured ingestion logs without payloads or database exception details.
- Docker builds upgrade Debian runtime packages, including util-linux, before installing the application.

## HTTP acknowledgement contract

For a valid correlated request, the response is one of:

    {"record_id":"...","status":"accepted"}
    {"record_id":"...","status":"duplicate"}
    {"record_id":"...","status":"rejected","error_code":"invalid_payload"}
    {"record_id":"...","status":"rejected","error_code":"record_id_conflict"}
    {"record_id":"...","status":"rejected","error_code":"observation_identity_conflict"}
    {"record_id":"...","status":"retry","error_code":"storage_unavailable"}

Malformed JSON or an invalid record_id returns HTTP 400 because no trustworthy correlation ID exists.

Requests without record_id retain the legacy accepted/event_id response for the compatibility window.

## Database migration

The release upgrades the application database from revision 0008_story_environment to 0009_telemetry_record_id.

The migration is additive:

- historical telemetry rows are preserved;
- record_id is nullable;
- the existing observation identity constraint remains;
- a unique index is added for non-null record IDs.

Apply the migration before serving the new application image. Do not downgrade the migration in production. Application-only rollback is supported while retaining the new column and index.

## Compatibility

- Existing v1 and v2 telemetry fixtures remain readable.
- Existing clients without record_id continue to ingest during the one-release compatibility window.
- MQTT-first then HTTP replay produces duplicate rather than a second row.
- HTTP-first then MQTT replay produces duplicate rather than a second row.
- Edge spool records can treat both accepted and duplicate HTTP 202 responses as delivered.

## Verification

Automated checks for this release include:

- focused API, persistence, migration, MQTT, contract, and edge fixture tests;
- full pytest suite: 302 passed, 1 skipped;
- Ruff lint and format checks;
- mypy type checks;
- Bandit security scan;
- pip-audit dependency scan;
- Compose configuration validation;
- 500-record mixed backlog and replay coverage.

Docker/PostgreSQL E2E and the real production edge canary must be run by the release operator before production rollout.

## Upgrade requirements

Before upgrade:

1. Verify a fresh, restorable PostgreSQL and application-data backup.
2. Confirm the release checksum and immutable Docker image.
3. Confirm the current migration revision.
4. Apply the additive migration before enabling the new API and workers.
5. Send one canary record and replay it.
6. Confirm accepted, duplicate, and one stored row.
7. Monitor retry and 5xx rates during bounded backlog replay.

The Linux procedure is documented in [ISSUE-200-ROLLOUT-RUNBOOK.md](ISSUE-200-ROLLOUT-RUNBOOK.md).

## Rollback

Rollback is application-only:

1. Stop or pause backlog replay.
2. Restore the previous application release/image.
3. Keep migration 0009 and the record_id column/index.
4. Leave edge records in the durable spool until the forward fix is ready.

Do not delete telemetry, remove database volumes, or run an Alembic downgrade as part of rollback.

## Known limitations

- A production backup/restore rehearsal is operator-owned and must be recorded separately.
- Docker/PostgreSQL E2E and the physical edge canary are not substitutes for local tests and must be completed before production approval.
- Legacy clients without record_id remain on observation-identity deduplication and should migrate during the compatibility window.
- The service remains intended for a trusted LAN or an authenticated, TLS-protected network boundary.

