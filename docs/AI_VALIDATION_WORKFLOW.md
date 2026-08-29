# Agent validation and routing

The canonical validation entry point for an active isolated task is:

```text
python -m tools.validate_change --base <ref> --task-key <key> [--explain] [--force full]
```

The command classifies the working diff through `.ai/context-manifest.yaml`, then routes checks from
`.ai/test-matrix.yaml`. Task metadata may add task classes and risk flags, but cannot remove anything
inferred from changed paths. `--explain` reports selected and skipped checks. Development mode runs
the changed test files as a bounded focused check and defers full pytest, quality, security,
dependency, and Compose checks; `--force full` runs the complete selected final set.

Harness-only changes are a bounded exception: changes limited to the agent harness Python files and
their focused tests run only the mapped focused tests, even when `--force full` is supplied. Changes
limited to harness documentation/templates run no tests. A change mixed with application Python,
packaging, deployment, schema, or other non-harness paths uses the normal matrix.

Results are written atomically to `.agent-tasks/<key>/validation.json`. Every selected check is
`PASS`, `FAIL`, or `NOT_RUN`; manual evidence remains `NOT_RUN` until a human records it. Cached
results are keyed by the relevant diff content, exact command, bounded platform identity, and
canonical configuration hashes. A documentation-only addition therefore does not invalidate an
unchanged Python check, while Python/tool/test changes do. Nox checks reuse their existing local
virtual environments from the primary repository control root, including when validation runs from an
isolated worktree. Reused validation sessions skip their `session.install` steps; dependency or nox
configuration changes or missing selected session directories retain normal `session.install` behavior
to bootstrap/update the shared environments safely. Long-running commands stream output and periodic
heartbeats and have bounded per-check timeouts. Pytest disables only its local cache plugin and uses an
ignored, identity-scoped base-temp directory below the short primary control root. The
task-and-relevant-Python-input component is a bounded hash rather than the full task key, so an
invalidated Python/tooling diff receives a fresh directory while documentation-only changes retain
cached evidence. This avoids cross-identity Windows ACL failures, stale-directory cleanup, and
nested-worktree path overflow.

Compose rendering is selected only by infrastructure or matching risk routing and is executed through
the isolated `tools.agent_task compose ... config` boundary. Validation never starts services,
deploys, reads `.env`, enables export, accesses hardware, or contacts a model provider.

Model and tool selection are deterministic contracts:

- `.ai/model-routing.yaml` keeps classification, context selection, validation, metrics, schemas,
  whitespace, and secret scanning in scripts; low-risk documentation/support work may use a light
  tier; normal pure-software implementation/review uses medium; architecture, safety, security,
  migration/data-loss, public/edge contracts, critical findings, disputes, and unknowns use strong.
- `.ai/tool-routing.yaml` maps known GitHub lookups directly to the GitHub connector. `gh` is available
  only after a recorded connector failure; tool-catalog discovery is not part of the known path.
- Sub-agent routing uses `fork_turns=none`, compact JSON packets, and structured JSON output. The
  routing modules only return plans; they do not invoke models, connectors, or external providers.

Legacy explicit `tools.agent_task check` commands and the full context-pack fallback remain supported
for one release cycle. Rollback is to those explicit commands; existing validation evidence, task
metadata, allocations, durable data, and shared service state are preserved.
