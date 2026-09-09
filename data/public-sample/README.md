# Senior Pomidor Public Sample

Status: public, synthetic, reviewer-oriented sample  
Last reviewed: 2026-09-03

This directory demonstrates the shape and relationships of selected Senior Pomidor data without publishing private production records.

## Important provenance statement

**Every record in this directory is synthetic.** Values were constructed to follow current public contracts and representative state/anomaly shapes. They are not measurements from a real plant, person, home, farm, or production deployment and must not be cited as experimental results.

The sample exists to make schemas and data relationships inspectable for reviewers, contributors, and integration experiments while preserving the local-first privacy boundary in [`../../docs/PUBLIC_DATA_POLICY.md`](../../docs/PUBLIC_DATA_POLICY.md).

## Files

| File | Status | Purpose |
|---|---|---|
| `telemetry_sample.jsonl` | synthetic / current contract-shaped | Reduced `senior-pomidor.edge.telemetry.v2` observation example |
| `photo_metadata_sample.jsonl` | synthetic / current contract-shaped | `senior-pomidor.edge.photo.v1` metadata example; no image is published |
| `state_sample.jsonl` | synthetic / current runtime-shaped | Example of current `state_v1` canonical state |
| `anomaly_sample.jsonl` | synthetic / current runtime-shaped | Example of current `anomaly_v1` environmental anomaly |

## Relationships

The records describe one fictional node and one fictional time window:

```text
telemetry observation
      ↓
canonical state_v1
      ↓
environmental anomaly_v1

photo metadata ──► independent reviewed observation channel
```

`state_sample.jsonl` references the anomaly identifier in `anomaly_sample.jsonl`. The identifiers are deliberately fictional (`public-demo-*`).

## Privacy review

This sample contains none of the following:

- secrets, bearer tokens, credentials, or environment variables;
- SSIDs, IP addresses, hostnames, local ports, usernames, or private paths;
- exact private location information;
- process IDs, boot IDs, service names, logs, or stack traces;
- raw production telemetry payloads;
- real photos, EXIF, or private background imagery;
- raw model analysis from private datasets.

The telemetry example intentionally contains only a reduced subset of fields permitted by the public schemas. Absence of a field here does not mean the field is absent from the private runtime contract.

## Evidence and diagnosis boundary

No record in this directory is a disease or pathogen diagnosis. The anomaly example is an environmental `HIGH_VPD` condition derived from synthetic environmental values.

The production plant-vision contract is still roadmap work tracked in [server #201](https://github.com/cracketus/senior-pomidor-server/issues/201). This directory therefore does **not** freeze or invent a canonical `plant_vision_observation_v1` schema before #201 defines and validates it.

Future model-generated labels must be explicitly distinguishable from measured/observed, derived/inferred, and human-reviewed evidence. A model-generated plant-health hypothesis is not a confirmed diagnosis.

## Contract references

- [`../../docs/schemas/telemetry-v2.schema.json`](../../docs/schemas/telemetry-v2.schema.json)
- [`../../docs/schemas/photo-v1.schema.json`](../../docs/schemas/photo-v1.schema.json)
- [`../../docs/CONTRACTS.md`](../../docs/CONTRACTS.md)
- current state/anomaly implementation under `app/state_estimator/`

## Intended use

Appropriate uses include:

- understanding public data shape;
- documentation and grant review;
- parser/integration examples;
- tutorials and demonstrations that explicitly retain the synthetic label;
- future public-data regression checks.

Do not use these records to evaluate plant-health accuracy, model performance, crop outcomes, sensor accuracy, or deployment reliability. They contain no empirical evidence.
