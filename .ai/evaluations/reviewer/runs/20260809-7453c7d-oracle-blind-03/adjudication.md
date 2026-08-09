# Adjudication: 20260809-7453c7d-oracle-blind-03

Verdict: `CALIBRATION_FAILED_RERUN_REQUIRED`

BLOCKER recall remained complete, but HIGH recall fell below 85%: migration evidence, representative
local-model acceptance, edge canary and LLM negative-test evidence were missed. The run also confirmed
additional distinct safety, security, classification and missing-evidence findings now recorded in
`oracles/v3.json`; oracle v2 remains unchanged.

One historical report repeated a topology identifier from its pinned context-pack diff. Complete raw
evidence is retained only in the ignored local task registry. RV-02 is replaced by the neutral pinned
Dependabot commit `6ed02f5`. Reviewer instructions now require explicit risk/evidence passes and avoid
treating generic documented topology roles as private without concrete evidence. A full new blind run
is mandatory.
