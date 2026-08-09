# Known-failures index

Owner: the maintainer resolving or reviewing an incident. The canonical full records are in
[`known-failures.yaml`](known-failures.yaml). Agents receive the full content only for IDs selected by
`.ai/context-manifest.yaml`; this compact index is for navigation and compatibility during the
one-release-cycle transition from the former Markdown registry.

Never include secrets, private keys, exact addresses, private hostnames, or unsanitized production
payloads in a known-failure record. A validated resolution must have observed evidence. New IDs are
permanent and monotonically increasing; supersede rather than reuse or silently rewrite history.

## Generated index

<!-- BEGIN GENERATED SUMMARY -->
| ID | Category | Symptom | Verification |
| --- | --- | --- | --- |
| `SP-FAIL-001` | infrastructure | Compose interpolation fails or services use an empty/unintended image. | `software` |
| `SP-FAIL-002` | infrastructure | A worker container starts but becomes unhealthy or stops refreshing output. | `software_and_rehearsal` |
| `SP-FAIL-003` | infrastructure | Rehearsal writes to production paths/ports or sends duplicate public metrics. | `software_and_manual` |
| `SP-FAIL-004` | infrastructure | A rehearsal passes with files/topology that differ from the production release bundle. | `rehearsal` |
| `SP-FAIL-005` | infrastructure | Backup files exist but recovery readiness is unknown or restore fails. | `rehearsal_and_manual` |
| `SP-FAIL-006` | edge | Edge telemetry/photos disappear after Wi-Fi profile or connectivity loss. | `software_and_manual` |
| `SP-FAIL-007` | edge | Raspberry Pi storage becomes read-only, disappears, or fails under heat. | `manual_physical` |
| `SP-FAIL-008` | edge | Camera times out, is absent, or flickers/corrupts frames on a long cable. | `software_and_manual_physical` |
| `SP-FAIL-009` | schema | A consumer expects flat state fields while producer emits nested canonical state, or vice versa. | `software` |
| `SP-FAIL-010` | schema | Moisture/humidity/confidence thresholds are off by a factor of 100. | `software` |
| `SP-FAIL-011` | testing | Contract fixtures pass validators but fail through the real HTTP/MQTT execution path. | `software` |
| `SP-FAIL-012` | llm | Model returns malformed JSON, extra prose, schema-grammar errors, or an overlong response. | `software` |
| `SP-FAIL-013` | llm | Hidden reasoning or prompt internals appear in user-visible/persisted final output. | `software` |
| `SP-FAIL-014` | testing | Pytest passes on Linux but fails on Windows around temp cleanup, open files, or path semantics. | `software_cross_platform` |
| `SP-FAIL-015` | testing | Editable install/build reports multiple top-level packages or omits application modules. | `software` |
| `SP-FAIL-016` | security | SSH authentication is broken or private key material is exposed via authorized_keys/source/logs. | `manual_security` |
| `SP-FAIL-017` | infrastructure | Router/switch/Wi-Fi symptoms are misdiagnosed as an application defect or vice versa. | `software_and_manual` |
<!-- END GENERATED SUMMARY -->

## Usage

Planners copy applicable IDs and concrete regression checks into the approved brief. Coders implement
selected software checks and keep manual checks `NOT_RUN` until a human supplies evidence. Reviewers
verify selected IDs independently and propose, rather than silently make, unrelated registry changes.

Run `python -m tools.ai_context_docs` to reject drift between canonical YAML and this generated index.
