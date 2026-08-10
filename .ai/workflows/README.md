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

## Shared project context

Workflows that need project, research, publication, or planning context read the authoritative files
from these three groups before drafting recommendations:

| Context | Authoritative inputs | Update owner and cadence |
| --- | --- | --- |
| Research | [`../research/RESEARCH_SCOPE.md`](../research/RESEARCH_SCOPE.md), [`../research/scientific-topics.yaml`](../research/scientific-topics.yaml), [`../research/grant-sources.yaml`](../research/grant-sources.yaml) | Research owner; review sources and assumptions before each grant/publication decision |
| Content | [`../content/PUBLIC_VOICE.md`](../content/PUBLIC_VOICE.md), [`../content/CLAIMS_POLICY.md`](../content/CLAIMS_POLICY.md), [`../content/platform-profiles.yaml`](../content/platform-profiles.yaml) | Content owner; review when a platform or public policy changes |
| Planning | [`../planning/PRIORITY_RULES.md`](../planning/PRIORITY_RULES.md), [`../planning/project-goals.yaml`](../planning/project-goals.yaml), [`../planning/seasonal-calendar.yaml`](../planning/seasonal-calendar.yaml) | Project owner; review at season boundaries and during weekly planning |

The context pack contains stable inputs only. Frequently changing implementation/deployment facts
remain in `.ai/CURRENT_STATE.md`; task-specific evidence remains in the brief and report. All
workflow recommendations must preserve the priority order of plant safety, data continuity, and
seasonal windows over speculative software work.
