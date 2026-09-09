# Senior Pomidor No-Diagnosis Policy

Status: current public-data and AI interpretation boundary  
Last reviewed: 2026-09-03

Senior Pomidor may use sensors, images, deterministic processing, ML, VLMs, LLMs, and human review to describe plant condition and generate hypotheses. These outputs are **not confirmed plant-disease or pathogen diagnoses** unless a future, separately governed dataset or workflow explicitly contains independently validated diagnostic ground truth.

## What the system may report

Appropriate observation/proxy language includes:

- visible yellowing, wilting, spots, deformation, damage, or other described image features;
- environmental or root-zone stress indicators such as high VPD, heat, low moisture, or sensor/data-quality anomalies;
- a plant-health **risk proxy**;
- one or more hypotheses compatible with the available evidence;
- competing abiotic, infrastructure, nutritional, pest-related, or disease-like explanations;
- uncertainty / insufficient evidence / `UNKNOWN`;
- a suggestion for additional observation, measurement, or expert review.

Examples:

> “Visible yellowing is present in this reviewed image.”

> “The available telemetry indicates high atmospheric water-demand stress; the image alone does not establish a disease cause.”

> “The visual pattern is compatible with several hypotheses. More evidence is required.”

## What the system must not claim from current data

Without independently validated diagnostic evidence, do not publish statements such as:

- “This plant has disease X.”
- “Pathogen Y is confirmed.”
- “The model diagnosed fungal/bacterial/viral disease.”
- “This visual label is ground truth.”
- “Apply pesticide/biological treatment Z because the AI identified pathogen Y.”

Confidence scores do not turn a proxy or hypothesis into a diagnosis.

## Evidence provenance

Plant-health records should preserve how a statement was produced:

- `measured` — instrument reading;
- `observed` — contextual human/image observation;
- `derived` / `inferred` — documented computation or inference;
- `model_generated` — ML/LLM/VLM output;
- `human_reviewed` — reviewed by a person/process;
- `synthetic` — constructed fixture/example.

A `human_reviewed` visual label remains a reviewed visual observation unless the review method itself provides validated diagnostic evidence. Human review is not a substitute for laboratory or otherwise accepted diagnostic confirmation.

## Model behavior

LLM/VLM workflows used for plant-health analysis must:

- permit `UNKNOWN` / insufficient-evidence outcomes;
- distinguish visible evidence from inferred causes;
- avoid collapsing plausible competing explanations into one diagnosis without evidence;
- retain model/workflow/version provenance where feasible;
- expose uncertainty and known limitations;
- remain advisory and have no direct actuator authority.

Model-generated labels must remain distinguishable from human-reviewed labels in datasets and evaluation artifacts.

## Treatment and physical-control boundary

No automatic pesticide or biological-treatment control is authorized by a visual/model hypothesis.

Future physical actions, including ordinary cultivation actions such as irrigation, ventilation, or shading, remain subject to deterministic action contracts, Guardrails, data freshness/confidence checks, edge validation, and the wider [`../SAFETY_BOUNDARIES.md`](../SAFETY_BOUNDARIES.md) policy.

Stronger intervention recommendations based on plant-health hypotheses require human review and appropriate domain expertise.

## Dataset and publication requirements

Any public dataset or benchmark containing plant-health fields must:

- state whether labels are measured, observed, derived/inferred, model-generated, human-reviewed, synthetic, or externally validated;
- describe the source of any ground truth;
- document missing diagnostic confirmation as a limitation;
- avoid filenames, column names, prose, or charts that silently imply diagnostic certainty;
- retain false-positive/UNKNOWN behavior when relevant to evaluation;
- pass privacy review under [`../PUBLIC_DATA_POLICY.md`](../PUBLIC_DATA_POLICY.md).

The current dataset interpretation rules are documented in [`DATASET_CARD.md`](DATASET_CARD.md).

## Future validated diagnostic work

If Senior Pomidor later enters a research collaboration that provides validated disease/pathogen ground truth, that does not silently supersede this policy. The new data/workflow must document:

- who or what established the ground truth;
- diagnostic/validation method;
- applicable scientific, biosafety, ethics, legal, and data-governance review;
- label confidence and limitations;
- exactly which records are validated and which remain proxies/hypotheses.

Until then, Senior Pomidor plant-health AI outputs are evidence and hypotheses, **not diagnosis**.
