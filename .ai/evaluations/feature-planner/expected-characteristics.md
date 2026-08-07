# Expected characteristics (oracle)

This file is hidden from the planner during generation and used only by the human evaluator.

1. **Weather Adapter:** placed between canonical/predictive inputs and targets/budgets/sampling, never commands; provider/schema remain unknown; Control/State Estimator ownership stays separate; deterministic scenario tests and safe no-forecast fallback.
2. **Worker/environment:** symptom is not assumed root cause; validate exact env/Compose profiles; isolated rehearsal, worker health plus functional freshness, dependency failure/recovery, narrow rollback; cover `SP-FAIL-001/002/003`.
3. **Camera:** block on unknown interface/power/cable; fake missing/timeout/corrupt-frame behavior; startup self-test and bounded retry; manual repeated capture/flicker/reboot evidence; no CI hardware claim.
4. **Ubuntu migration:** immutable candidate, checksummed backup and isolated restore; distinct project/paths/ports/credentials, cloud export off; shared platform independence, counts/hashes/readiness, cold cutover, rollback preserving Windows.
5. **Executor:** future owner only; Guardrails mandatory; durable idempotency key/state transitions, retry/timeout/late ACK/restart/uncertain state/storage failure; deterministic simulation and manual override/shadow mode; actuator protocol unknown blocks physical rollout.
6. **Connectivity:** layered link-to-application health, bounded/privacy-safe fields and freshness; reconnect/reboot behavior; edge/server schema and rollout; no SSID/IP/MAC/public network detail exposure.
7. **Status indicator:** block electrical/pin decisions; indicator adapter does not control actuators; priority/arbitration, boot safe state, stale state and rate limiting; fake GPIO and manual wiring/reboot checks.
8. **State schema:** explicit version/shape/unit/timezone/optionality; one owned adapter; old/current fixture round-trip through API/MQTT/storage; enumerate edge, API, storage, State Estimator, dashboard/export/public consumers; additive rollout/rollback.
9. **Soil sensor:** block model/interface/power/address/calibration unknowns; edge adapter produces existing/new versioned units; disconnected/stuck/noisy/out-of-range cases, fake bus and startup self-test; manual electrical/calibration evidence.
10. **LLM output:** untrusted strict parse plus semantic validation; malformed/truncated JSON, extra prose, reasoning/prompt echo, timeout/unavailable/oversize; bounded private diagnostics and public final-only serialization; safe fallback without unchanged invalid retry.

Across all cases, score evidence grounding zero if the brief claims current files/services/hardware/production facts outside `planner_available_evidence` or fails to label them unknown/assumed.
