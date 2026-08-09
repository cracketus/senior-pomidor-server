# Review Report: RV-07 unsafe Compose defaults and rehearsal export

Report schema: `senior-pomidor.review-report.v1`

Reviewer/version: Reviewer 1.0

Issue/brief: evaluation fixture RV-07

Base/head or diff artifact: `patches/06-compose-export.diff`

Independence statement: illustrative contract example only; not a raw report and not included in
published evaluation metrics.

## Verdict

`REQUEST CHANGES`

The rehearsal can contact an external exporter and the image contract no longer fails closed.

## Independent classification

- Task classes: `infrastructure_deployment`
- Risk flags: `production_availability`, `security_secrets`
- Differences from brief classification: fixture supplies no brief; classification is reviewer-owned.
- Applicable `SP-FAIL-*`: SP-FAIL-001 and SP-FAIL-003 are both reproduced by the patch.

## Scope and architecture assessment

- Both Compose changes are in scope for the fixture and violate operational isolation invariants.

## Findings

```yaml
- severity: BLOCKER
  category: operations
  location: docker-compose.rehearsal.yml:1
  finding: Rehearsal enables the Grafana Cloud exporter.
  evidence: The rehearsal profile sets GRAFANA_CLOUD_EXPORT_ENABLED to true.
  evidence_excerpt: 'GRAFANA_CLOUD_EXPORT_ENABLED: "true"'
  impact: Rehearsal data can be exported or duplicated outside the isolated environment.
  required_change: Remove the exporter and prove remote writes remain zero.
  suggested_test: Render rehearsal config and assert exporter and remote-write settings are absent.
- severity: HIGH
  category: operations
  location: docker-compose.yml:1
  finding: APP_IMAGE silently falls back to latest.
  evidence: Required interpolation was replaced by ${APP_IMAGE:-latest}.
  evidence_excerpt: '${APP_IMAGE:-latest}'
  impact: Validation or rollout can use an unintended image.
  required_change: Restore required interpolation and a clear missing-variable failure.
  suggested_test: Run Compose config without APP_IMAGE and assert failure.
```

## Contract and consumer review

- The image/environment contract and rehearsal operator are affected; production deployment is not run.

## Test and evidence matrix

| Status | Required/manual check | Evidence and reviewer assessment |
| --- | --- | --- |
| FAIL | exact rehearsal Compose config | External exporter is present. |
| NOT RUN | isolated rehearsal/rollback | Human evidence is unavailable. |

Passing CI alone does not close missing required manual/rehearsal/physical evidence.

## Operations, safety, security and privacy

- Isolation and external-export safety fail. No production or hardware action was performed.

## Documentation assessment

- The fixture includes no updated operator documentation.

## Follow-ups outside this PR

- None.

## Limitations and unverified evidence

- No Compose stack was started; this static seeded patch is evaluation-only.
