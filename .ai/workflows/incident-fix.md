# Incident-fix planning workflow

Use when availability, ingestion, data integrity, security, edge connectivity, or physical behavior is currently/recently degraded.

1. Prioritize containment, data preservation and service safety over refactoring. Record timeline/timezone, impact and current state without secrets.
2. Separate observed facts, operator reports, hypotheses and unknowns. Do not perform production mutation in planning.
3. Test the relevant layers in order and identify an abort/escalation boundary.
4. Require an incident-to-regression artifact, observability improvement and [`KNOWN_FAILURES.md`](../KNOWN_FAILURES.md) update when resolution is validated.
5. Define staged recovery, rollback, post-recovery health/data checks and manual owner.

Security, data-loss, production-availability and physical-action flags are cumulative. Output only the draft brief and evidence list; emergency execution authorization is separate.
