# Senior Pomidor agent router

Before planning, editing, or reviewing, read in this order:

1. [`.ai/PROJECT.md`](.ai/PROJECT.md) — stable purpose and ownership boundaries.
2. [`.ai/CURRENT_STATE.md`](.ai/CURRENT_STATE.md) — what is deployed and what is not.
3. [`.ai/ARCHITECTURE_RULES.md`](.ai/ARCHITECTURE_RULES.md) and [`.ai/SAFETY_RULES.md`](.ai/SAFETY_RULES.md).
4. [`.ai/DEVELOPMENT_RULES.md`](.ai/DEVELOPMENT_RULES.md).
5. [`.ai/KNOWN_FAILURES.md`](.ai/KNOWN_FAILURES.md) and [`.ai/TEST_MATRIX.md`](.ai/TEST_MATRIX.md).

Work only from an approved Implementation Brief: an accepted issue with explicit scope and acceptance criteria, or a human-approved copy of [`.ai/templates/implementation-brief.md`](.ai/templates/implementation-brief.md). Use the read-only [Feature Planner](.ai/agents/feature-planner.md) and matching workflow when a request needs planning. Classify the task and its risk flags using `TEST_MATRIX.md`; record applicable known-failure IDs and required checks in the brief before implementation.

Standard validation from the repository root:

```text
python -m pytest -q
nox -s lint format_check types
$env:APP_IMAGE='senior-pomidor-server:agent'; docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile observability --profile daily-story config --quiet; Remove-Item Env:APP_IMAGE
```

Run security, dependency, Docker E2E, replay, migration, rehearsal, and manual checks when selected by `TEST_MATRIX.md`. Never assume CI can verify a physical-world change.

Prohibited: production deployment or writes; reading or exposing production secrets/private infrastructure; real GPIO/actuator use; bypassing Guardrails or Executor; direct LLM-to-actuator paths; destructive database/volume operations; enabling external export in rehearsal; unapproved contract breaks. Coding agents have no production secrets, real GPIO, or production deployment access by default.

Active-season reliability fixes take priority. Keep their scope narrow and avoid unrelated refactoring.
