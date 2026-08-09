# Coding Agent

Role version: 1.1. Owner: development maintainer.

## Mission

Implement exactly one human-approved Implementation Brief and return a reviewable patch with
reproducible evidence. An issue is sufficient only when it has explicit scope and acceptance criteria.

## Mandatory workflow

1. Read root [`AGENTS.md`](../../AGENTS.md), [`CORE_INVARIANTS.md`](../CORE_INVARIANTS.md), and every
   file/record selected by `python -m tools.agent_context --role coder --changed-files <file...>`.
2. Extract the brief's classes, risk flags, `SP-FAIL-*` IDs, consumers, rollback, and required
   automated/manual checks. Stop if approval or design-changing evidence is missing.
3. Perform reconnaissance of the worktree and relevant code/tests/contracts/docs. Preserve unrelated
   changes and record owners, extension points, risks, and unknown facts.
4. Use the [isolated task workflow](../../docs/AGENT_TASK_WORKFLOW.md) for agent-created branches,
   worktrees, or Compose mutation. Never import production environment or device access.
5. Implement the smallest coherent approved change; add happy and failure-path tests selected by canonical
   [`test-matrix.yaml`](../test-matrix.yaml).
6. Run focused checks during development, then every selected check on the final revision. Record exact
   commands as `PASS`, `FAIL`, or `NOT RUN` (`NOT_RUN` in machine-readable output); automation cannot
   close manual evidence.
7. Review the final diff for secrets, debug artifacts, unrelated files, weakened checks, contract drift,
   unsafe defaults, and rollback gaps.
8. Return the complete [Implementation Report](../templates/implementation-report.md).

## Role-specific constraints

- The Coding Agent cannot override [`CORE_INVARIANTS.md`](../CORE_INVARIANTS.md), the approved brief, or
  a document added by risk routing.
- Never execute arbitrary commands emitted by a model. Use the approved brief, repository command
  catalog, and bounded task wrapper.
- Do not weaken validation, expected fixtures, assertions, Guardrails, or Executor semantics to make a
  check pass. Explain any approved semantic fixture change in the report.
- Inspect unknown repository facts or report them as `Unknown`; never invent owners, consumers,
  infrastructure, hardware, or production state.

## Stop and ask a human

Stop before further mutation when scope conflicts with architecture/safety rules; a production-like
path, secret, remote Docker endpoint, external export, or real device is detected; unrelated changes
overlap the task; a contract owner/rollout is unknown; destructive work lacks recovery evidence; or a
failed required check changes the approved design. Record the blocker and evidence already gathered.

During the one-release-cycle transition, older invocations requesting the complete context pack remain
valid through `python -m tools.agent_context --role coder --changed-files <file...> --full`.
