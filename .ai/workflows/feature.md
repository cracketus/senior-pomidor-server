# Feature planning workflow

Use for new user-visible or internal capability that is not primarily a schema, infrastructure, or hardware change.

1. Apply the [Feature Planner](../agents/feature-planner.md) procedure.
2. Establish the current user/system path and smallest owning extension point.
3. Separate MVP outcome from follow-ups; reject opportunistic refactoring.
4. Identify API/storage/worker/observability/docs impacts and whether a specialized class also applies.
5. Define success, degraded/unavailable behavior, compatibility, focused/full tests, rollout and rollback.

Output only a draft [Implementation Brief](../templates/implementation-brief.md) and evidence list. If the feature touches contracts, deployment, hardware, control, or LLM boundaries, also apply that specialized workflow; requirements accumulate.
