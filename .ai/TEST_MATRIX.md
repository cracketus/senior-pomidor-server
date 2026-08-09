# Test routing

Owner: development maintainer. The canonical machine-readable source for check IDs, commands, task
classes, and risk overlays is [`.ai/test-matrix.yaml`](test-matrix.yaml). This document explains how
to apply it; the tables below are generated and must not be edited by hand.

## Classification rules

Classes accumulate. `pure_software` covers Python/tool behavior without a more specialized boundary.
Use `schema_data_contract` for versioned shapes, API/MQTT/storage, units, timezone, fixtures,
dashboards, export, or public fields. Use `infrastructure_deployment` for Docker, Compose, CI,
deployment, environment, topology, backup, restore, or release behavior. Edge connectivity and device
adapters use `edge_hardware_integration`; physical policy and execution use
`control_guardrails_executor`; prompts, providers, vision, and model-output contracts use
`llm_vision`.

Use `documentation_only` only when no executable configuration, schema, fixture, command, or runtime
behavior changes. If it occurs with another class, drop it. Unknown behavior defaults to
`pure_software` plus the closest specialized class.

Risk flags can only add checks and context: `physical_action`, `data_loss_migration`,
`security_secrets`, `edge_server_compatibility`, `production_availability`, and `public_contract`.
Manual evidence selected by a flag remains manual; CI cannot turn it into `PASS`.

## Generated routing summary

<!-- BEGIN GENERATED SUMMARY -->
| Task class | Required check IDs |
| --- | --- |
| `pure_software` | `focused_tests`, `full_pytest`, `quality`, `diff_check` |
| `schema_data_contract` | `full_pytest`, `quality`, `diff_check`, `schema_validation`, `serialization_round_trip`, `fixture_replay`, `named_consumers` |
| `infrastructure_deployment` | `full_pytest`, `quality`, `diff_check`, `compose_config` |
| `edge_hardware_integration` | `full_pytest`, `quality`, `diff_check`, `fixture_replay`, `edge_failure_paths` |
| `control_guardrails_executor` | `full_pytest`, `quality`, `diff_check`, `deterministic_simulation` |
| `llm_vision` | `full_pytest`, `quality`, `diff_check`, `model_failure_paths` |
| `documentation_only` | `diff_check`, `changed_links_paths_commands` |

| Risk flag | Added automated checks | Manual evidence |
| --- | --- | --- |
| `physical_action` | `deterministic_simulation` | `supervised_safe_hardware_and_rollback` |
| `data_loss_migration` | `fixture_replay` | `isolated_upgrade_restore_counts_hashes_backup_rollback` |
| `security_secrets` | `security`, `dependency_audit` | none |
| `edge_server_compatibility` | `fixture_replay`, `named_consumers` | `edge_canary` |
| `production_availability` | `compose_config` | `isolated_rehearsal_rollback_post_deploy_health` |
| `public_contract` | `schema_validation`, `serialization_round_trip`, `fixture_replay`, `named_consumers` | none |
<!-- END GENERATED SUMMARY -->

## Evidence rules

- Run focused checks while developing and the full selected set on the final revision.
- Record every selected automated and manual check as `PASS`, `FAIL`, or `NOT_RUN` with a reason.
- Validate contracts through real producer/consumer paths, not validators alone.
- Use fake hardware and deterministic simulations by default. Hardware evidence requires a supervised
  human procedure.
- Infrastructure rehearsal uses isolated paths, loopback ports, synthetic credentials, and no
  external export. Production deployment is never implied by this matrix.
- Database/data-loss work needs isolated upgrade/restore evidence, counts or hashes, backup, abort,
  rollback, and post-rollback data checks.

## Standard local commands

The exact baseline commands are defined under `checks` in `.ai/test-matrix.yaml`. Run them from the
repository root with local test resources only. Compose, Docker E2E, migration, edge canary, hardware,
and production/rehearsal checks are selected only by the matching class or risk flag.

When agent routing, role instructions, workflows, templates, or evaluation contracts change, run the
matching Feature Planner and Reviewer evaluations in addition to the selected matrix checks.
