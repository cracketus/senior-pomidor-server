# VPD Alert Ranges for Tomato Monitoring

Project: **Senior Pomidor**
Metric: `state_snapshots.payload_jsonb #>> '{env,vpd_kpa}'`
Unit: `kPa`
Purpose: Grafana alerting and plant stress interpretation
Status: Implemented v1

---

## 1. Overview

VPD, or **Vapor Pressure Deficit**, describes how strongly the air pulls water from the plant through transpiration.

In practical terms:

* **Low VPD** means the air is too humid and transpiration is weak.
* **Optimal VPD** means the plant can transpire normally.
* **High VPD** means the air is too dry or too hot, and the plant may lose water faster than the roots can supply it.

For tomato monitoring in the Senior Pomidor project, VPD is one of the primary climate stress indicators.

---

## 2. Primary Metric

The preferred local Grafana alert metric is the canonical state estimator value:

```text
state_snapshots.payload_jsonb #>> '{env,vpd_kpa}'
```

This value represents VPD recalculated by the state estimator from air temperature and relative humidity, with quality and sensor health context.
Legacy raw telemetry alerts using `telemetry_pod_readings_flat.air_vpd_kpa` remain provisioned temporarily for debugging and comparison.

Optional supporting metrics:

```text
leaf_vpd_kpa
leaf_air_delta_c
air_temp_c
rh_pct
soil_moisture_pct
```

`leaf_vpd_kpa` can be used as a stronger plant-level stress indicator when leaf temperature is available.

---

## 3. VPD Interpretation Table

| VPD range, kPa | State             | Interpretation                                                              | Plant risk                                                                             | Recommended Grafana severity |
| -------------: | ----------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ---------------------------- |
|        `< 0.4` | Extremely low VPD | Air is close to saturation. Transpiration is very weak.                     | Condensation risk, fungal disease risk, weak water and calcium transport.              | `alert`                      |
|    `0.4 - 0.6` | Low VPD           | Humid air, reduced evaporative demand.                                      | Disease risk, slow transpiration, possible condensation during night or early morning. | `warning`                    |
|    `0.6 - 0.8` | Slightly low VPD  | Acceptable for seedlings or recovery, but below the main production target. | Reduced transpiration and slower water movement.                                       | `info`                       |
|    `0.8 - 1.3` | Optimal VPD       | Target range for active tomato growth and fruiting.                         | Normal transpiration and water flow.                                                   | `ok`                         |
|    `1.3 - 1.6` | Slightly high VPD | Air is becoming too dry or too warm.                                        | Faster substrate drying, early leaf curling, increased irrigation demand.              | `warning`                    |
|    `1.6 - 2.5` | High VPD / stress | Water stress threshold exceeded.                                            | Stomatal closure, reduced photosynthesis, flower or fruit stress if persistent.        | `alert`                      |
|    `2.5 - 4.0` | Critical VPD      | Severe evaporative demand.                                                  | Rapid wilting risk, leaf overheating, strong water deficit.                            | `critical`                   |
|        `> 4.0` | Emergency VPD     | Extreme "hot dry air" condition.                                            | High risk of plant damage, especially under direct sun or low soil moisture.           | `emergency`                  |

---

## 4. Default Grafana Alert Rules

Recommended alert rules for canonical `env.vpd_kpa`.
These rules are provisioned in `docker/grafana/provisioning/alerting/senior-pomidor-alerts.yml`.

| Rule name               |           Condition | Severity    | Suggested duration | Notes                                     |
| ----------------------- | ------------------: | ----------- | -----------------: | ----------------------------------------- |
| `VPD too low`           | `air_vpd_kpa < 0.5` | `warning`   |              `15m` | Humid air / weak transpiration.           |
| `VPD condensation risk` | `air_vpd_kpa < 0.4` | `alert`     |              `10m` | Higher disease and condensation risk.     |
| `VPD high`              | `air_vpd_kpa > 1.3` | `warning`   |              `10m` | Above optimal range.                      |
| `VPD stress`            | `air_vpd_kpa > 1.6` | `alert`     |               `5m` | Senior Pomidor stress guardrail exceeded. |
| `VPD critical`          | `air_vpd_kpa > 2.5` | `critical`  |               `3m` | Severe water stress risk.                 |
| `VPD emergency`         | `air_vpd_kpa > 4.0` | `emergency` |               `1m` | Immediate intervention required.          |

---

## 5. Recommended Grafana Threshold Lines

For the VPD panel, add horizontal thresholds at:

```text
0.4
0.5
0.8
1.3
1.6
2.5
4.0
```

Suggested visual meaning:

| Threshold | Meaning                          |
| --------: | -------------------------------- |
|     `0.4` | Condensation / disease risk zone |
|     `0.5` | Low VPD guardrail                |
|     `0.8` | Lower bound of optimal range     |
|     `1.3` | Upper bound of optimal range     |
|     `1.6` | Water stress guardrail           |
|     `2.5` | Critical stress                  |
|     `4.0` | Emergency stress                 |

---

## 6. Stage-Specific VPD Targets

The general alert rules above are suitable for production monitoring. However, target ranges may be adjusted by growth stage.

| Growth stage           | Target VPD, kPa | Notes                                                                          |
| ---------------------- | --------------: | ------------------------------------------------------------------------------ |
| Seedling               |     `0.6 - 1.0` | Lower VPD reduces excessive evaporation.                                       |
| Vegetative             |     `0.8 - 1.3` | Main biomass growth target.                                                    |
| Flowering              |     `0.9 - 1.2` | Avoid heat and water stress to protect pollen viability.                       |
| Fruiting               |     `0.8 - 1.3` | Balance yield, transpiration, and water use.                                   |
| Ripening / flavor mode |     `1.1 - 1.3` | Moderate deficit may improve fruit quality, but strong stress must be avoided. |

---

## 7. Suggested YAML Configuration

This block can be used as a project-level reference configuration.

```yaml
vpd_alerts:
  metric: air_vpd_kpa
  unit: kPa

  thresholds:
    emergency_high:
      condition: "> 4.0"
      severity: emergency
      for: 1m
      meaning: "Extreme evaporative demand. Immediate intervention required."

    critical_high:
      condition: "> 2.5"
      severity: critical
      for: 3m
      meaning: "Severe water stress risk."

    alert_high:
      condition: "> 1.6"
      severity: alert
      for: 5m
      meaning: "Water stress guardrail exceeded."

    warning_high:
      condition: "> 1.3"
      severity: warning
      for: 10m
      meaning: "Above optimal VPD range."

    optimal:
      condition: ">= 0.8 and <= 1.3"
      severity: ok
      meaning: "Target range for active growth and fruiting."

    info_low:
      condition: "< 0.8"
      severity: info
      meaning: "Below production target, but may be acceptable for seedlings or recovery."

    warning_low:
      condition: "< 0.6"
      severity: warning
      for: 15m
      meaning: "Low transpiration due to humid air."

    alert_low:
      condition: "< 0.5"
      severity: alert
      for: 15m
      meaning: "Low VPD guardrail. Condensation or disease risk may increase."

    condensation_risk:
      condition: "< 0.4"
      severity: alert
      for: 10m
      meaning: "Very humid air. Condensation and disease risk zone."
```

---

## 8. Suggested Grafana Panel Description

```text
VPD - Vapor Pressure Deficit, kPa.

Target range for active tomato growth and fruiting: 0.8-1.3 kPa.
Warning zone: <0.6 or >1.3 kPa.
Stress guardrail: >1.6 kPa.
Critical: >2.5 kPa.
Emergency: >4.0 kPa.

Low VPD means humid air and weak transpiration.
High VPD means dry or hot air and increased water stress.
```

---

## 9. Alert Message Templates

### High VPD Warning

```text
VPD is above the optimal range.

Current air_vpd_kpa: {{ $values.A.Value }} kPa
Target range: 0.8-1.3 kPa

Interpretation:
The air is becoming too dry or too warm. The plant may increase transpiration and the substrate may dry faster.
```

### VPD Stress Alert

```text
VPD stress guardrail exceeded.

Current air_vpd_kpa: {{ $values.A.Value }} kPa
Guardrail: 1.6 kPa

Interpretation:
The tomato may be under water stress. Check soil moisture, leaf condition, direct sun exposure, and ventilation.
```

### VPD Emergency

```text
Emergency VPD condition.

Current air_vpd_kpa: {{ $values.A.Value }} kPa
Emergency threshold: 4.0 kPa

Interpretation:
The air is extremely dry or hot. Immediate action may be required: shading, wind protection, irrigation check, or moving the plant out of direct stress conditions.
```

### Low VPD Alert

```text
VPD is too low.

Current air_vpd_kpa: {{ $values.A.Value }} kPa
Low VPD threshold: 0.5 kPa

Interpretation:
The air is too humid and transpiration is weak. Check condensation risk, airflow, and night humidity.
```

---

## 10. Recommended Operational Response

| Condition             | Recommended response                                                            |
| --------------------- | ------------------------------------------------------------------------------- |
| Low VPD `< 0.5`       | Increase airflow if safe, check condensation, avoid unnecessary humidification. |
| High VPD `> 1.3`      | Watch soil moisture, check sun exposure, monitor leaf condition.                |
| Stress VPD `> 1.6`    | Trigger stress alert, increase observation frequency, verify watering need.     |
| Critical VPD `> 2.5`  | Add shading, reduce dry airflow, check substrate moisture immediately.          |
| Emergency VPD `> 4.0` | Treat as severe stress. Intervene quickly and capture plant state/photo.        |

---

## 11. Notes for Senior Pomidor

1. Canonical `env.vpd_kpa` from `state_snapshots.payload_jsonb` should be the primary local Grafana alert metric.
2. Raw telemetry `air_vpd_kpa` should be treated as a temporary debugging/comparison signal.
3. `leaf_vpd_kpa` should be used as a plant-level confirmation signal when leaf temperature is available.
4. `leaf_air_delta_c` helps distinguish between air stress and actual leaf stress.
5. VPD alerts should be interpreted together with:

   * soil moisture,
   * air temperature,
   * relative humidity,
   * sunlight,
   * wind exposure,
   * recent irrigation events.
5. Short spikes are less important than persistent exposure, except for emergency values above `4.0 kPa`.

---

## 12. Example Current-State Classification

Example:

```json
{
  "air_vpd_kpa": 6.02,
  "leaf_vpd_kpa": 3.66,
  "air_actual_vapor_pressure_kpa": 1.36,
  "air_saturation_vapor_pressure_kpa": 7.38,
  "leaf_saturation_vapor_pressure_kpa": 5.02
}
```

Classification:

```text
air_vpd_kpa = 6.02 -> EMERGENCY
leaf_vpd_kpa = 3.66 -> CRITICAL leaf-level stress
```

Interpretation:

The air is extremely dry or hot. The plant may still cool itself through transpiration if leaf temperature is lower than air temperature, but the evaporative demand is far above the safe operating range.

---

## 13. Versioning

Document version: `v1.0`
File path:

```text
docs/VPD_ALERTS.md
```

Future versions may include:

* separate alert profiles for indoor seedlings and outdoor balcony plants,
* weather-adapted VPD thresholds,
* combined alerts using VPD + soil moisture + leaf temperature,
* Grafana provisioning JSON.
