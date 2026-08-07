# Safety rules

Owner: safety/operations maintainer. Review before every physical-control, deployment, security, or public-data brief and after any safety incident.

1. Treat sensor data, network input, files, and LLM/VLM output as untrusted. Validate structure, semantics, freshness, units, identity, and bounds.
2. No direct model-to-actuator path. Every physical action must be deterministic after model input, pass Guardrails, and execute through an idempotent Executor and approved adapter.
3. Standard tests use simulation/fake GPIO/I2C/camera/device backends. Real hardware requires explicit human authorization, a bounded procedure, safe physical supervision, and recorded manual results.
4. On stale, missing, contradictory, low-confidence, timed-out, or uncertain execution state, fail safe and do not invent control-critical values.
5. Production secrets, private keys, exact location/infrastructure details, real GPIO, production deployment, and production database writes are unavailable to coding agents by default.
6. Never copy `.env`, secrets, raw private datasets, or production logs into source, prompts, fixtures, public output, or issue comments. Use synthetic/redacted evidence.
7. No destructive database/volume operation without an approved recovery plan, verified target, recent restorable backup, and explicit authorization. Never use `down -v` in production/rehearsal recovery.
8. Rehearsal is isolated and external export is off. Production rollout includes rollback and independent health/data checks.
9. CI cannot validate wiring, heat, moisture, mechanics, radio conditions, camera cables, actuator motion, or plant response. Mark these checks manual; never report inferred success.
10. Active-season changes stay narrow, reversible, observable, and biased toward continued ingestion and data preservation.

If a requested change conflicts with these rules, stop implementation, record the conflict in the brief, and request a human safety/architecture decision.
