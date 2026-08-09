# Adjudication: 20260809-c339e8d-oracle-blind-01

Verdict: `CALIBRATION_FAILED_RERUN_REQUIRED`

All ten reports were frozen before adjudication. The run met critical recall, severity, ordering and
manual-evidence detection, but failed false-positive and actionable-quality gates. Oracle v1 omitted
supported historical, manual, edge-compatibility and LLM negative-path findings. The general scorer
also rejected observable unified-diff excerpts and embedded implementation-report evidence too
aggressively.

One historical artifact caused a Reviewer to repeat private-infrastructure detail in raw evidence.
That raw run is retained only in the ignored local task registry and is deliberately not published.
The corpus replaces that historical case with a safe pinned commit. Oracle v1 remains unchanged;
`oracles/v2.json` records the rationale and requires a completely fresh blind rerun.
