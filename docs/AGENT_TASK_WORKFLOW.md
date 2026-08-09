# Isolated Coding Agent task workflow

Use this workflow for implementation tasks that need a branch/worktree or any local Compose
mutation. It is a development-only boundary: it cannot authorize production access, deployment,
external export, hardware activation, or manual acceptance claims.

## What the wrapper guarantees

`python -m tools.agent_task` creates one `feature/ISSUE-slug` or `fix/ISSUE-slug` branch and, by
default, one nested ignored worktree. A central ignored `.agent-tasks/` registry allocates a unique
ten-port block atomically, a unique Compose project name, and task-owned bind directories. Generated
values use loopback bindings, synthetic local credentials, fake Executor/hardware backends, disabled
GPIO, and empty/disabled Grafana Cloud settings.

Checks and Compose are invoked with an explicit generated env file and a small inherited host-environment
allowlist. The wrapper accepts only `config`, `up`, `down`, and `ps`; optional profiles are limited to
`observability` and `daily-story`. Every action first renders and validates the exact base, development,
and [`docker-compose.agent.yml`](../docker-compose.agent.yml) files. It rejects non-loopback ports,
writable bind mounts outside task data, read-only binds outside task data/worktree, host namespaces,
devices, privileged services, added capabilities, external resources, Compose secrets,
production/hardware paths, active external export, or non-fake backends. Before `up`, it also checks
that all five allocated loopback ports appear free. This is best-effort: another process can still
claim a port between the check and Docker's bind (TOCTOU). Before a stateful Docker action the wrapper
rejects active contexts whose endpoint is not a local `unix://` socket or Windows `npipe://`. It never
uses `down -v`.

## Create and inspect

Start from the repository root on the intended base commit. The source worktree must be clean,
including untracked files; commit, stash, move, or explicitly preserve existing work first.

```powershell
python -m tools.agent_task create --issue TOMATO-AI-128 --slug agent-sandbox --kind feature
python -m tools.agent_task inspect tomato-ai-128-agent-sandbox
```

Use `--no-worktree` only when a separate worktree is unnecessary. It switches the current clean
checkout to the new task branch, so it is unsuitable for concurrent tasks. Generated state is under `.agent-tasks/<task-key>/`; worktrees are
under `.agent-worktrees/<task-key>/`. Both paths are ignored by Git.

Two tasks created from the same control checkout receive different branches, project names, port
blocks, and data roots. Run each task's commands from any checkout belonging to that repository; the
shared Git common directory locates the central registry.

## Bounded Compose actions

Validate without starting containers:

```powershell
python -m tools.agent_task compose tomato-ai-128-agent-sandbox config
python -m tools.agent_task compose tomato-ai-128-agent-sandbox config --profile observability
```

Start, inspect, and stop the isolated local stack:

```powershell
python -m tools.agent_task compose tomato-ai-128-agent-sandbox up
python -m tools.agent_task compose tomato-ai-128-agent-sandbox ps
python -m tools.agent_task compose tomato-ai-128-agent-sandbox down
```

The `daily-story` profile may download a public local-model image/model and is never selected by
default. The `cloud-export` profile cannot be selected. Do not bypass the wrapper with raw Compose
commands for an agent task, because shell variables and `.env` precedence can defeat isolation.

Task metadata and secret-free command/return-code records are stored in `metadata.json` and
`commands.jsonl` for copying into the Implementation Report. Do not paste generated local passwords
or env-file contents into the report. Creation first proves that a temporary Git ref lock can be
created and removed. Only then does it record an owned port allocation and a `creating` metadata
record. A partial failure becomes `creation_failed` with the failed stage and created-resource
inventory; its allocation remains reserved for diagnosis and recovery.

Resume a recorded partial creation without allocating another port block:

```powershell
python -m tools.agent_task resume tomato-ai-128-agent-sandbox
```

`resume` verifies allocation ownership, reconciles only the recorded branch/worktree, recreates the
synthetic environment, and is idempotent after activation. If the exact task branch was deliberately
checked out in the control checkout after an older Git-write failure, use `--no-worktree` to adopt
that checkout. It never adopts a differently named or unproven branch.

Run standard checks through the same sanitized environment. Check names expand to fixed repository
commands and do not accept additional shell arguments:

```powershell
python -m tools.agent_task check tomato-ai-128-agent-sandbox pytest
python -m tools.agent_task check tomato-ai-128-agent-sandbox quality
python -m tools.agent_task check tomato-ai-128-agent-sandbox security
python -m tools.agent_task check tomato-ai-128-agent-sandbox planner
python -m tools.agent_task check tomato-ai-128-agent-sandbox reviewer-corpus
```

This removes inherited database/cloud/Docker-target variables and does not load `.env`; production
secret files and hardware devices are not mounted. It is not an operating-system security boundary:
normal host ACLs must still deny the developer account access to production secrets and devices.

The fixed `check` commands remain supported for one release cycle. New tasks should use the unified
validation orchestrator documented in [`AI_VALIDATION_WORKFLOW.md`](AI_VALIDATION_WORKFLOW.md).

## Cleanup and recovery

First run the bounded `compose down` action. Cleanup refuses a task marked as running and refuses a
worktree with staged, unstaged, or untracked changes:

```powershell
python -m tools.agent_task cleanup tomato-ai-128-agent-sandbox
```

Successful cleanup removes only the clean worktree. It also accepts a `creation_failed` task when the
wrapper can prove that any created worktree belongs to that task and is clean. Cleanup deliberately
preserves the branch, task data, metadata, command history, and owned port allocation. It never
force-removes a branch or worktree. If creation fails partway, inspect the recorded stage/resources,
`git worktree list`, the named branch, `.agent-worktrees/`, and `.agent-tasks/`; account for dirty or
unowned paths manually.

After cleanup, retire the task to release only its owned port allocation:

```powershell
python -m tools.agent_task retire tomato-ai-128-agent-sandbox
```

Retirement requires `compose_running=false` and status `cleaned`. It atomically claims the matching
owner-tagged allocation before release, changes the task to `retired`, and preserves its branch,
task data, metadata, and command history. Repeated retirement fails safely. Legacy metadata remains
inspectable, but an ownerless legacy allocation is never released automatically. If the process
stops during allocation release, rerun `retire`; the internal `retiring` state and owned release
marker make that recovery idempotent.

## Platform limitations and manual checks

The Python/Git workflow is tested on Windows and uses platform-neutral `pathlib` paths. Docker bind
mount rendering still depends on Docker Desktop path sharing on Windows; Linux requires the invoking
user to have explicitly approved local Docker access. POSIX generated env files are mode `0600`;
Windows ACLs are inherited from the checkout, so keep the checkout private to the developer account.

Automated config validation cannot prove that a host port is unused between render and startup or
that physical wiring/services are safe. Before any manual Docker start, confirm the allocated ports
are free and no real device is mounted. Production or physical verification remains a human-owned manual step and is
reported `NOT RUN` unless separately authorized and observed.
