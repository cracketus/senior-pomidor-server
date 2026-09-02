# Public Research Dashboard

Issue: #310  
Parent epic: #309

## Purpose

The public dashboard is a deliberately bounded research view of the live Senior Pomidor experiment.

It is **not** the operator/debug dashboard and it is **not** Mission Control. Its job is to let an external visitor understand the plant/environment observations that are currently running and the quality of those observations without exposing raw production data or implying roadmap-only capabilities.

Current public dashboard source:

```text
docker/grafana/public/senior-pomidor-public-research.json
```

The existing local PostgreSQL-backed dashboards remain under:

```text
docker/grafana/provisioning/dashboards/json/
```

The public dashboard is intentionally stored separately because Grafana Cloud receives the public metric projection through Prometheus remote write, while the local dashboards query PostgreSQL and include broader operator-only data.

## Current v1 information architecture

### Senior Pomidor right now

Compact latest-state panels:

- telemetry age;
- air temperature;
- relative humidity;
- air VPD;
- average public soil moisture;
- leaf temperature.

### Plant ↔ Environment

Primary research charts:

- air temperature vs leaf temperature;
- derived `leaf - air` temperature difference;
- air VPD vs leaf VPD.

### Root zone

- soil moisture by public `pod_key`;
- soil temperature by public `pod_key`.

### Solar load

- BH1750 illuminance in lux.

No lux→PPFD/DLI conversion is shown because the current project does not have a validated/calibrated public conversion contract.

### System reliability

Collapsed by default:

- edge reliability OK state;
- edge reliability freshness;
- spool backlog;
- edge spool disk usage.

Detailed watchdog/process/reboot diagnostics remain an engineering/operator concern and are not the main public narrative.

## Metric semantics

The v1 dashboard uses only metrics that are already part of the public Grafana Cloud exporter allowlist or bounded public edge-reliability projection.

| Dashboard concept | Metric | Classification |
|---|---|---|
| Air temperature | `senior_pomidor_air_temperature_c` | measured |
| Relative humidity | `senior_pomidor_air_humidity_percent` | measured |
| Air VPD | `senior_pomidor_air_vpd_kpa` | derived |
| Soil moisture | `senior_pomidor_soil_moisture_percent` | measured/calibrated observation |
| Soil temperature | `senior_pomidor_soil_temperature_c` | measured |
| Leaf temperature | `senior_pomidor_leaf_temp_c` | measured |
| Leaf VPD | `senior_pomidor_leaf_vpd_kpa` | derived |
| Light | `senior_pomidor_light_lux` | measured |
| Telemetry age | `senior_pomidor_telemetry_freshness_seconds` | derived operational freshness |
| Leaf-air ΔT | PromQL subtraction of leaf and air temperature | derived dashboard quantity |
| Edge reliability | `senior_pomidor_edge_reliability_*` | bounded operational projection |

`air_pressure_hpa` remains publicly exported but is intentionally omitted from the primary dashboard story because it currently has low explanatory value for the plant-centric public view.

## Runtime thresholds shown in v1

These values reflect current StateEstimator runtime behavior and must not be presented as universal tomato optimum ranges.

| Quantity | Current project threshold |
|---|---:|
| Low VPD risk | `< 0.5 kPa` |
| High VPD risk | `> 1.6 kPa` |
| Leaf-air temperature stress proxy | `|ΔT| > 3 °C` |
| Low soil temperature warning | `< 15 °C` |
| High soil temperature warning | `> 28 °C` |
| StateEstimator maximum sensor age | `1200 s` |

If runtime configuration changes, the dashboard and this documentation must be reviewed together.

## Grafana Cloud import

The JSON is an importable Grafana dashboard and contains a datasource input named:

```text
DS_PROMETHEUS
```

On import, bind it to the Grafana Cloud Prometheus datasource that receives Senior Pomidor remote-write metrics.

The datasource selection is an import-time input, not a dashboard template variable.

## Important externally-shared-dashboard limitation

As of 2026-09-02, Grafana externally shared dashboards do not support dashboard variables or queries that include variables.

For that reason v1 deliberately contains:

```json
"templating": {"list": []}
```

and no `$device_id` / `$pod_key` selectors in PromQL.

Pod-level time-series panels distinguish series using the already-public `pod_key` label in the legend. This is less interactive than an authenticated dashboard, but it keeps the external shared dashboard functional and avoids relying on unsupported behavior.

Before adding a variable later, re-check the deployed Grafana Cloud version and externally shared dashboard documentation.

## Default time behavior

- dashboard default: `24h`;
- refresh: `1m`;
- useful time choices configured in the JSON: `6h`, `24h`, `48h`, `7d`, `30d`.

The ordinary Grafana time picker is independent from template variables and should be verified manually in the actual externally shared view.

## Public-data boundary

`docs/PUBLIC_DATA_POLICY.md` remains authoritative.

This dashboard must never become a shortcut around the public projection. In particular it must not query or expose:

- raw telemetry payload JSON;
- unrestricted `metrics_jsonb`;
- private network/host/path/log data;
- exact private location;
- unreviewed photos/EXIF;
- arbitrary anomaly/debug strings;
- raw StateEstimator payloads;
- private sensor/hardware topology beyond approved public labels.

## Implemented vs planned

The v1 dashboard intentionally does **not** contain panels claiming live:

- World Model forecasts;
- dynamic Targets;
- WeatherAdapter decisions;
- predictive/MPC decisions;
- autonomous watering or other actuator decisions;
- water budgets;
- VLM diagnosis/stress scores;
- AI Scientist conclusions.

Those panels may only be added after the underlying runtime artifact exists, is persisted/versioned, and has an explicit public-safe projection.

## Validation checklist

Before publishing or updating the externally shared dashboard:

- [ ] Import JSON into Grafana Cloud using the intended Prometheus datasource.
- [ ] Confirm every panel returns the expected public series.
- [ ] Confirm the externally shared view loads without authentication.
- [ ] Confirm no panel depends on dashboard variables.
- [ ] Confirm the 24h default and time picker behave as expected.
- [ ] Confirm stale/no-data behavior does not make old telemetry look current.
- [ ] Confirm pod legends expose only approved public labels.
- [ ] Confirm no private/raw fields appear in query inspector/output.
- [ ] Review threshold wording as project runtime configuration, not agronomic universal truth.
- [ ] Capture a public-safe screenshot after the shared view has been manually verified.

## Next step

Issue #311 adds a deliberate public StateEstimator confidence/quality projection. Issue #312 adds bounded public anomaly/risk state. Those two additions will extend the public narrative from:

```text
measurement
```

to:

```text
measurement -> confidence -> bounded interpretation
```

without exposing raw estimator internals.
