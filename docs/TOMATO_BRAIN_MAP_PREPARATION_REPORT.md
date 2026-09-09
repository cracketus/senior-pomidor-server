# Implementation Brief: Tomato Brain Map preparation

Status: approved for documentation/backlog preparation by project owner, 2026-09-09.
Planner/version: Codex, preparation v1.
Approver/date: project owner request to finish preimplementation work after ADR merge, 2026-09-09.
Issue/decision: [umbrella #120](https://github.com/cracketus/senior-pomidor/issues/120); accepted TBM-ADR-001 through 010.
Agent run ID / audit artifact: tbm-prep-20260909; embedded audit below.

## Problem
Merged architecture needs concrete owning specifications, dependencies and test acceptance before coding.

## Desired outcome
Server, Edge and umbrella each have a bounded handoff and linked implementation issues.

## Current behavior and evidence
Pinned Server and Edge references are in [R1 specification](TOMATO_BRAIN_MAP_R1_SPEC.md). These are source inspections, not deployment verification.

## Scope
Markdown specification, navigation, producer handoff and issue backlog only.

## Out of scope
Runtime code, executable configuration/schemas/fixtures, production access, deployment and hardware.

## Architecture placement
Server owns projection; Edge owns producer evidence; umbrella owns programme coordination.

## Affected contracts and consumers
Future Map v1 design affects implementation planning and operator-client planning. Existing Edge/API/MQTT/storage/estimator/control/Grafana/export runtime consumers are unaffected: this change contains Markdown only. No runtime contract is installed or changed.

## Safety/risk classification
Task class: documentation_only. Risk flags: none for this preparation.
Selected context: AGENTS.md, .ai/CORE_INVARIANTS.md, .ai/DEVELOPMENT_RULES.md, .ai/agents/feature-planner.md, .ai/workflows/feature.md, context-manifest.yaml and test-matrix.yaml.
The documentation path rule selects no SP-FAIL records; future executable issues must independently select their records and risk overlays.
Production/physical verification remains outside this task.

## Proposed implementation sequence
Prepare owning documents, inspect existing backlog, add bounded missing issues, validate documentation, independently review, publish focused PRs.

## Failure modes
Temporal ambiguity -> explicit seed/boundary regressions. Broken links -> repository-tree validation. Duplicate backlog -> inspect existing open issues and reuse operator/compatibility work. Unsupported deployment claim -> keep NOT_IMPLEMENTED/UNVERIFIED.

## Backward compatibility
No executable behavior changes. Future Map is additive; Edge wire format remains unchanged.

## Testing plan
Required now: whitespace/diff checks and changed Markdown links/repository paths. Runtime pytest, quality, Compose, hardware, staging and production: NOT_RUN, outside Markdown-only scope.

## Observability
Preparation evidence is this bounded report and linked issues/PRs; no private source payloads or production logs.

## Documentation updates
TOMATO_BRAIN_MAP_R1_SPEC.md, this report and README.md; companion Edge and umbrella preparation documents.

## Rollout and rollback
Publish documentation PRs against main. Merge remains human-owned under AGENT_TASK_WORKFLOW.md. Revert documentation commit if needed; no database or runtime rollback required.

## Acceptance criteria
- [x] Owning specifications and concrete issue acceptance checklists prepared.
- [x] Existing operator/compatibility issues reused rather than replaced.
- [x] Runtime status and missing real-world evidence separated from accepted design.
- [x] Local Markdown validation passed for 7 files and 14 relative links; independent follow-up content review approved after both findings were fixed.

## Blocking open questions
None for synthetic implementation. Actual bindings/calibration/private boundary remain activation gates.

## Evidence and references
[R1 specification](TOMATO_BRAIN_MAP_R1_SPEC.md); [accepted decisions](https://github.com/cracketus/senior-pomidor/blob/main/docs/architecture/tomato-brain-map/implementation-decisions.md); .ai/context-manifest.yaml; .ai/test-matrix.yaml.
Unverified: runtime deployment, private configuration, physical assets and calibration quality.

## Implementation report
Preparation contains Markdown only and seven new scoped issues. No runtime tests have been claimed.
Independent review found ambiguous pre-range seed selection and repeated query-parameter handling; both clarified with explicit regression cases in the Server specification.
Publication uses GitHub Git Data API branches/commits, with local Markdown copies for validation. No runtime implementation worktree or Compose environment is created in this preparation.

## Embedded agent_run_v1 audit

The counters cover the bounded documentation-validation handoff (document characters and normalized validation output), not total conversation/token usage. PR reference is null because this record precedes publication; the GitHub PR provides the containing change identity.

```json
{
  "schema": "agent_run_v1",
  "run_id": "tbm-prep-20260909",
  "issue_ref": "https://github.com/cracketus/senior-pomidor/issues/120",
  "pr_ref": null,
  "role": "planner",
  "agent_id": "codex-preparation",
  "prompt_version": "preparation-v1",
  "started_at_utc": "2026-09-09T05:39:03.391Z",
  "finished_at_utc": "2026-09-09T05:40:46.254Z",
  "input_refs": [
    ".ai/context-manifest.yaml",
    ".ai/test-matrix.yaml",
    "https://github.com/cracketus/senior-pomidor/commit/5b532c696c96ceba3d0c1e2ac5a18b39b27aea11"
  ],
  "output_refs": [
    "docs/TOMATO_BRAIN_MAP_R1_SPEC.md",
    "docs/TOMATO_BRAIN_MAP_PREPARATION_REPORT.md",
    "README.md"
  ],
  "status": "completed",
  "commands": [
    {
      "name": "local Python Markdown whitespace/fence/relative-link validation",
      "exit_code": 0
    }
  ],
  "validation_results": [
    {
      "check": "documentation_validation",
      "status": "PASS",
      "files": 7,
      "relative_links_checked": 14,
      "errors": []
    },
    {
      "check": "independent_content_review",
      "status": "PASS",
      "reviewer": "review_preparation",
      "resolved_findings": [
        "TBM-PREP-REVIEW-01",
        "TBM-PREP-REVIEW-02"
      ]
    },
    {
      "check": "runtime_and_physical",
      "status": "NOT_RUN",
      "reason": "Markdown-only preparation"
    }
  ],
  "human_edits": [],
  "findings": [],
  "errors": [],
  "usage": {
    "file_count": 7,
    "input_characters": 81359,
    "tool_output_bytes": 51,
    "elapsed_seconds": 102.863
  }
}
```
