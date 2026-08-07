# Feature Planner workflows

Choose by the request's changed behavior; workflows are cumulative:

| Workflow | Use when |
| --- | --- |
| [`feature.md`](feature.md) | new capability without a more specific primary boundary |
| [`bugfix.md`](bugfix.md) | reproducible incorrect behavior, not an active incident |
| [`incident-fix.md`](incident-fix.md) | active/recent availability, data, security, edge or physical degradation |
| [`schema-change.md`](schema-change.md) | schema/API/MQTT/storage/unit/timezone/fixture/dashboard/public contract changes |
| [`infrastructure-change.md`](infrastructure-change.md) | Docker/Compose/CI/deploy/env/topology/backup/restore/release changes |
| [`hardware-integration.md`](hardware-integration.md) | sensor/camera/GPIO/bus/power/wiring/adapter work |

Each workflow applies the [Feature Planner](../agents/feature-planner.md) and produces the same [Implementation Brief](../templates/implementation-brief.md). A workflow narrows planning but cannot override [`SAFETY_RULES.md`](../SAFETY_RULES.md), [`ARCHITECTURE_RULES.md`](../ARCHITECTURE_RULES.md), known-failure checks, or test-matrix requirements.
