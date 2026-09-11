# ISSUE-335 implementation report

The additive, development-only Map boundary is implemented under `app/map/`.
It adds strict adapter configuration validation, bearer authentication, explicit target
allowlisting, request correlation, bounded topology/evaluation routes, signed continuation
cursors, response-size checks, and the `senior-pomidor.map.v1` envelope schema. The default
configuration remains disabled and non-development deployments are hard-disabled.

Validation evidence:

- PASS — `python -m pytest -q tests/test_map_evaluator.py tests/test_map_reader.py tests/test_map_topology.py tests/test_api.py tests/test_compose_config.py -p no:cacheprovider` (136 passed)
- PASS — `ruff check app/map/adapter.py app/map/service.py app/map/api.py app/config.py app/main.py`
- PASS — `python -m compileall -q app`
- PASS — `git diff --check`
- NOT_RUN — PostgreSQL/Docker rehearsal, production or staging activation, real data, hardware, and independent review.

The isolated task wrapper could not create a branch because this checkout's Git index metadata is
read-only (`.git/index.lock: Permission denied`). No production, external export, or physical
activation was attempted. Rollback is additive: disable `MAP_API_ENABLED` and remove the Map
router/configuration files; durable storage and existing ingestion paths are untouched.
