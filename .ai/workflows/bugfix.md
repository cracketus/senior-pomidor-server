# Bugfix planning workflow

Use for reproducible incorrect software behavior without an active operational incident.

1. Preserve the reported symptom, environment and minimal reproduction separately from the suspected cause.
2. Locate the first divergent behavior and current owner using code/tests/log-safe evidence.
3. Search [`KNOWN_FAILURES.md`](../KNOWN_FAILURES.md); do not assume a matching symptom proves the same root cause.
4. Bound the fix to the root cause and name behaviors that must remain unchanged.
5. Require a failing regression test before/with the fix, adjacent failure paths, and full class/risk checks.
6. Define safe rollback and how to detect recurrence.

Unknown reproduction or root cause remains an explicit blocking investigation item. Output only the draft brief and evidence list.
