# Infrastructure-change planning workflow

Use for Docker/Compose, CI, systemd/deploy, environment, ports/networks/mounts, release, backup or restore changes.

1. Apply the Feature Planner infrastructure gate and classify production availability/data/security risks.
2. Identify application-owned versus shared platform services and exact changed overlays/profiles.
3. Validate required/optional environment variables without printing secret values.
4. Define an immutable local candidate and isolated rehearsal: distinct project, credentials, paths and loopback ports; no cloud/external export.
5. Require startup/dependency/readiness failure injection, health/data evidence, permissions and shared-service independence.
6. Define backup/restore proof where relevant, abort point, rollback command/owner and post-rollback checks.

No planner command starts/stops production services or renders secret-bearing config to output. Output only the draft brief and evidence list.
