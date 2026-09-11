# Implementation Brief: #207 operator TUI

Approved issue: https://github.com/cracketus/senior-pomidor-server/issues/207

## Scope

Implement the read-only SSH/local operator TUI on top of #205 and the now-merged #206 `pomidorctl` client/configuration layer. Provide Overview, Plant/Pod, Edge, Decisions, Events/Anomalies, and Camera metadata views; keyboard navigation; bounded asynchronous refresh; explicit transport/freshness failure states; tests; and a synthetic public demo source.

## Integration decision

`app.operator_tui` must reuse `app.pomidorctl.client.OperatorClient` and `app.pomidorctl.config.Config`. The TUI must not maintain a parallel HTTP contract validator and must not shell out to `pomidorctl --json`. `pomidorctl tui` is the canonical entry point; `python -m app.operator_tui` remains a direct development entry point.

## Non-goals

- no PostgreSQL/internal-table reads;
- no actuator/control mutation path;
- no Grafana/time-series replacement;
- no terminal image rendering requirement;
- no new operator schema or reinterpretation of server-owned health semantics;
- no production deployment, private data capture, or hardware access.

## Classification and risks

Task class: `pure_software`; risk flag: `public_contract`.
Applicable known failures: `SP-FAIL-009`, `SP-FAIL-011`, `SP-FAIL-015`.

## Required checks

- focused TUI/client integration tests;
- full pytest;
- `nox -s lint format_check types`;
- package/entry-point validation;
- security scans from standard CI;
- sanitized `pomidorctl tui --demo` capture remains a manual/public-artifact follow-up.

## Rollback

Revert the additive `app/operator_tui` package, `pomidorctl tui` command wiring, tests/docs, and optional Textual dependency. No persisted or physical state is modified.
