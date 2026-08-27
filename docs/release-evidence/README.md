# Release evidence

This directory may contain sanitized, reviewable RC reports for the manually dispatched release-qualification
workflow. Use one bounded lowercase report ID per candidate and keep the two required filenames:

```text
<report-id>/edge-core-compatibility.json
<report-id>/release-validation.json
```

Start from the `NOT_RUN` templates under `tests/fixtures/release_qualification/`. Replace template identities and
evidence only after the named real workflow has run. Never convert synthetic, CI-only, inferred, or unavailable
evidence into `PASS`.

Do not commit credentials, environment files, raw telemetry, logs, database exports, hostnames, addresses,
network identifiers, service names, paths, boot/process IDs, private reasons/errors, or production secrets. Use
bounded run/issue/artifact references and counts. The validator rejects incomplete status/identity semantics but
cannot determine whether a human-supplied statement is truthful; independent review remains required.
