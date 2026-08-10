# GitHub agent workflow

This repository keeps planning, implementation, review, and merge authority visible in GitHub. The
templates and labels are navigation and evidence aids; they do not grant production access or replace
the repository safety rules.

## Lifecycle

```text
idea
  -> needs-planning
  -> planned
  -> ready-for-agent
  -> in-progress
  -> review-required
  -> changes-requested / ready-for-human-review
  -> merged
```

The Planner produces a draft Implementation Brief. A human maintainer approves the scope, acceptance
criteria, task classes, risk flags, rollback, consumers, and checks before the Coder starts. The Coder
links the brief and returns an Implementation Report. The Reviewer works independently, records
findings in a Review Report, and never merges or claims physical/production evidence. A human retains
final approval and merge authority.

## Labels

Use existing labels when they express the same meaning. Do not create near-duplicate labels.

| Dimension | Labels |
| --- | --- |
| Role | `agent:planner`, `agent:coder`, `agent:reviewer` |
| Area | `area:server`, `area:edge`, `area:control`, `area:executor`, `area:vision`, `area:infrastructure`, `area:hardware`, `area:docs` |
| Risk | `risk:physical`, `risk:data-loss`, `risk:schema`, `risk:security`, `risk:deployment` |
| Workflow | `workflow:feature`, `workflow:bugfix`, `workflow:incident`, `workflow:schema`, `workflow:hardware` |
| Status | `status:needs-planning`, `status:planned`, `status:ready-for-agent`, `status:review-required`, `status:changes-requested`, `status:ready-for-human-review` |

Apply one workflow and one or more applicable area/risk labels. Status labels are updated as the
issue advances; `status:ready-for-agent` requires an approved brief link.

## Issue and pull request evidence

Choose the issue template that matches the change. Every issue records current/expected behavior,
evidence, affected environment and consumers, risks, acceptance criteria, and the Implementation
Brief link. Schema, infrastructure, and hardware issues additionally record compatibility or
rehearsal/manual evidence and rollback boundaries.

Every agent-generated PR must link its issue and brief, state scope and contract impact, list safety
and operational impact, record exact checks as `PASS`, `FAIL`, or `NOT RUN`, and link the
Implementation and Review Reports. Missing manual, rehearsal, edge-consumer, or physical evidence
stays `NOT RUN`; CI cannot convert it to success.

## Authentication preflight

GitHub CLI authentication must be verified before any issue, branch, push, or pull-request
automation. Git credentials used by `git push` and the token used by `gh` may come from different
stores, so a successful push does not prove that PR metadata and CI status can be read.

Run these checks without printing credentials:

```powershell
gh auth status -h github.com
gh api user
```

If either check fails, stop before GitHub mutations and re-authenticate interactively:

```powershell
gh auth logout -h github.com -u <account>
gh auth login -h github.com --git-protocol https --web
gh auth status -h github.com
gh api user
```

For non-interactive automation, provide a short-lived `GH_TOKEN` from the environment or a secret
manager. Use least-privilege repository access for contents, pull requests, issues, and Actions read
status as required; never commit or echo the token. Organization SSO authorization may be required.

After creating a PR, verify the remote result and CI explicitly:

```powershell
gh pr view <number> --json url,mergeStateStatus,statusCheckRollup
```

An authentication failure is `NOT_RUN` for remote PR/CI evidence and must be reported as a workflow
blocker, not as a clean or merged status.

## Automated PR handoff

Before branch or commit automation, run `python -m tools.agent_task preflight`. The command must
report writable Git metadata and a clean worktree. If it fails, stop and move the approved brief and
implementation to a normal writable clone; do not edit `main`, delete lock files, or bypass the
preflight. In a writable clone, the handoff is:

```powershell
gh auth status -h github.com
gh api user
git checkout -b feature/TOMATO-AI-12-health-summary
git add <approved implementation files only>
git commit -m "feat: add health summary endpoint"
git push -u origin feature/TOMATO-AI-12-health-summary
gh pr create --draft --base main --head feature/TOMATO-AI-12-health-summary
gh pr view <number> --json url,mergeStateStatus,statusCheckRollup
```

The PR body must link issue #132, the approved brief, Implementation Report, and later the
independent Review Report. Authentication and remote writes remain explicit operator-authorized
steps; a local sandbox cannot infer or manufacture GitHub credentials.

## Examples

### Planner

1. Open an issue with `status:needs-planning` and the relevant workflow/area/risk labels.
2. Produce the draft brief using `.ai/templates/implementation-brief.md`.
3. Attach the brief and request human approval; move to `status:planned` only after approval.

### Coder

1. Confirm the approved brief and move the issue to `status:ready-for-agent`.
2. Use the isolated task workflow and a dedicated branch; never use production secrets or hardware.
3. Open a PR from the branch, fill every evidence section, and move the issue to `status:review-required`.

### Reviewer and maintainer

1. Review from a separate context and link the completed Review Report.
2. Use `status:changes-requested` for actionable findings or `status:ready-for-human-review` when
   only human-owned/manual evidence remains.
3. The maintainer verifies required evidence, resolves follow-ups or creates separate issues, and
   performs the final merge.

## Safety boundary

Labels, templates, and lifecycle updates are metadata. They never authorize deployment, production
writes, production database writes, private-infrastructure access, external export, real GPIO/actuator use, destructive data
operations, or a Guardrails/Executor bypass.
