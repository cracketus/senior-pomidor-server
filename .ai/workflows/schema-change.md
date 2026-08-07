# Schema-change planning workflow

Use for any versioned payload, API response, database shape/migration, unit/timezone/optionality, fixture, dashboard/export or public field change.

1. Apply the Feature Planner schema gate.
2. Inventory producer and every consumer: edge, MQTT/HTTP, API, storage/migration, fixtures, State Estimator/Control, Grafana, export/public dataset and docs.
3. Specify old/new schemas, units, ranges, timezone/DST, optional/null/unknown behavior and compatibility window.
4. Prefer additive versioning and tolerant readers. Name rollout order and retirement criteria; never silently reinterpret an existing field.
5. Require old/current/new fixture replay through real execution boundaries, serialization round-trip and downstream queries/panels.
6. If durable data changes, require isolated migration/restore, backup evidence and rollback/forward-fix decision.

Any unknown consumer or ambiguous unit is blocking. Output only the draft brief and evidence list.
