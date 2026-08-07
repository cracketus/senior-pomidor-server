# Hardware-integration planning workflow

Use for sensors, cameras, GPIO/I2C/SPI/UART, indicators, power, wiring or actuator adapters.

1. Apply the Feature Planner hardware gate and edge/server compatibility analysis.
2. Record device/interface, power/voltage/current, level shifting/grounding, pin/address allocation and conflicts. Unknown electrical facts block implementation.
3. Specify boot/default safe state, startup self-test, disconnected/stuck/noisy/timeout behavior and bounded retry.
4. Define a protocol/fake backend first; CI uses it for absence, failure and recovery tests.
5. Separate software acceptance from a supervised physical checklist covering wiring, heat, cable stability, reboot and rollback.
6. For status indicators, define priority/arbitration, stale-state behavior and rate limits; for actuators, also apply Control/Guardrails/Executor rules.

Output only the draft brief and evidence list. Real hardware activation requires separate explicit authorization.
