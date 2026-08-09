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

Results are written atomically to `.agent-tasks/<key>/validation.json`. Every selected check is
`PASS`, `FAIL`, or `NOT_RUN`; manual evidence remains `NOT_RUN` until a human records it. Cached
results are keyed by the relevant diff content, exact command, bounded platform identity, and
canonical configuration hashes. A documentation-only addition therefore does not invalidate an
unchanged Python check, while Python/tool/test changes do. Nox checks reuse their existing local
virtual environments. Long-running commands stream output and periodic heartbeats and have bounded
per-check timeouts. Pytest disables only its local cache plugin and uses a task/user-scoped ignored
base-temp directory to avoid cross-identity Windows ACL and cleanup failures.

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
