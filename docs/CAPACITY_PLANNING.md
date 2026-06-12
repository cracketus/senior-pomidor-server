# Senior Pomidor Capacity Planning

This guide estimates hardware, storage, and operating requirements for running the
Senior Pomidor server continuously for 3, 6, and 12 months. It also outlines a
scaling plan for expanding the monitored environment to 4, 8, and 16 pods.

The server stack covered here is the Docker Compose deployment in this repository:

- `api`: FastAPI ingestion and read API
- `worker`: MQTT telemetry subscriber
- `postgres`: telemetry, photo metadata, and device state database
- `mosquitto`: MQTT broker
- `grafana`: optional observability UI

The offline Ollama-based image analysis tool is not part of the always-on server
stack. If it is scheduled to run regularly, size the machine separately for local
AI inference.

## Baseline Measurements

These measurements were taken from the local Compose stack on 2026-06-12 after
starting the observability profile.

Runtime memory at light load:

| Service | Memory | CPU |
| --- | ---: | ---: |
| API | 67 MB | 0.10% |
| MQTT worker | 51 MB | 0.01% |
| Grafana | 358 MB | 1.16% |
| PostgreSQL | 43 MB | idle |
| Mosquitto | 8 MB | 0.02% |
| **Total containers** | **~530 MB** | **low single-digit CPU** |

Current data sample:

| Item | Measured value |
| --- | ---: |
| Telemetry events | 540 |
| Telemetry span | ~19 hours |
| Observed telemetry rate | ~685 events/day |
| Photos | 51 |
| Observed photo rate | ~66 photos/day |
| Average uploaded photo | ~76 KB |
| PostgreSQL database logical size | ~9.7 MB |
| PostgreSQL Docker volume size | ~66.8 MB |
| Grafana Docker volume size | ~52.3 MB |
| Photo Docker volume size | ~3.95 MB |

The current telemetry rate is equivalent to roughly one telemetry payload every
2 minutes from one edge device. Each telemetry payload creates one
`telemetry_events` row and one `pod_readings` row per pod included in the payload.

## Sizing Assumptions

The estimates below assume:

- one edge device sends one telemetry payload about every 2 minutes
- each payload includes all pods currently attached to that edge device
- each pod sends the existing known metrics such as soil moisture, soil
  temperature, air temperature, humidity, pressure, light, and leaf temperature
- Grafana is enabled and used for local observation
- photos remain on the same capture schedule unless otherwise noted
- PostgreSQL, Grafana, and uploaded photos are stored on persistent Docker volumes
- no local AI inference is running continuously

If you add more edge devices, multiply telemetry events by the number of devices.
If each device has its own camera, also multiply photo storage by the number of
cameras.

## Hardware Recommendation

Minimum viable 24/7 host:

| Component | Recommendation |
| --- | --- |
| CPU | 2 cores |
| RAM | 4 GB |
| Disk | 32 GB SSD |
| Network | stable LAN; wired Ethernet preferred |

Comfortable 24/7 host:

| Component | Recommendation |
| --- | --- |
| CPU | 2-4 cores |
| RAM | 8 GB |
| Disk | 64-128 GB SSD |
| Network | wired Ethernet, static DHCP lease or static IP |

Growth host for 16 pods, longer retention, and larger photos:

| Component | Recommendation |
| --- | --- |
| CPU | 4 cores |
| RAM | 8-16 GB |
| Disk | 128-256 GB SSD |
| Network | wired Ethernet; avoid exposing ingestion ports publicly |

CPU is not expected to be the bottleneck for API, MQTT, PostgreSQL, and Grafana.
Disk reliability, predictable power, and enough RAM for Docker and filesystem
cache are more important.

## 3/6/12 Month Runtime Estimates

The base estimate uses the observed rate of ~685 telemetry events/day and
~66 photos/day.

| Period | Days | Telemetry events | Photos |
| --- | ---: | ---: | ---: |
| 3 months | 90 | ~61,600 | ~5,900 |
| 6 months | 180 | ~123,000 | ~11,900 |
| 12 months | 365 | ~250,000 | ~24,100 |

For the current deployment, telemetry database growth should remain modest for a
year. Photo storage is the main variable.

## Storage Estimate By Photo Size

The current average stored photo is ~76 KB. Real camera deployments may upload
larger JPEGs, so plan disk around the expected image size.

| Period | Current avg, 76 KB/photo | 1 MB/photo | 5 MB/photo | 25 MB/photo |
| --- | ---: | ---: | ---: | ---: |
| 3 months | ~0.5 GB | ~6 GB | ~30 GB | ~148 GB |
| 6 months | ~0.9 GB | ~12 GB | ~59 GB | ~297 GB |
| 12 months | ~1.8 GB | ~24 GB | ~121 GB | ~602 GB |

Add Docker images, PostgreSQL volume overhead, Grafana storage, logs, and backup
headroom on top of raw photo storage. For a practical deployment:

| Use case | Disk target |
| --- | ---: |
| telemetry-first, small photos | 64 GB SSD |
| normal photos and 6-12 month retention | 128 GB SSD |
| full-size photos or multiple cameras | 256 GB+ SSD |
| 25 MB photos retained for a year | 1 TB class storage |

## Database Growth By Pod Count

Pod count scales the `pod_readings` table linearly. The `telemetry_events` table
does not multiply by pod count when one edge device sends all pods in one payload.

| Period | Telemetry events | 4 pods readings | 8 pods readings | 16 pods readings |
| --- | ---: | ---: | ---: | ---: |
| 3 months | ~61,600 | ~246,000 | ~493,000 | ~986,000 |
| 6 months | ~123,000 | ~493,000 | ~986,000 | ~1,970,000 |
| 12 months | ~250,000 | ~1,000,000 | ~2,000,000 | ~4,000,000 |

These row counts are well within PostgreSQL's normal operating range on a small
SSD-backed host. Keep backups and basic maintenance in place before relying on
multi-month retention.

## Expansion Plan: 4, 8, And 16 Pods

The server accepts pods dynamically. A telemetry payload can provide pods as a
list or object, and each pod is stored with its `pod_key`. The existing Grafana
dashboard discovers pods from `telemetry_pod_readings_flat`, so new pods appear
in the `Pod` filter after data arrives.

### 4 Pods

Target:

- single edge device
- one telemetry payload every 1-2 minutes
- one camera or low-frequency photo uploads
- Grafana used interactively, not as a public dashboard

Server work:

- no backend schema change expected
- keep stable pod keys such as `pod-1`, `pod-2`, `pod-3`, `pod-4`
- verify `/api/v1/devices/{device_id}/latest` shows all four readings
- verify Grafana `Pod` filter includes all four pods
- keep hardware at 2 cores, 4-8 GB RAM, 64 GB SSD

Operational checks:

```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/devices/pi-001/latest"
docker compose exec -T postgres psql -U senior_pomidor senior_pomidor -c "SELECT pod_key, count(*) FROM pod_readings GROUP BY pod_key ORDER BY pod_key;"
```

### 8 Pods

Target:

- higher sensor density on one edge device, or two smaller edge devices
- dashboard still useful with pod filtering, but trend panels may become visually
  crowded when all pods are selected

Server work:

- no database schema change expected for standard pod telemetry
- validate payload size and edge publish latency under normal sampling interval
- review Grafana panels and use the `Pod` filter during troubleshooting
- consider adding dashboard rows or repeated panels by pod if all-pod charts are
  too dense
- move to 8 GB RAM and 128 GB SSD if photos are retained for 6-12 months

Operational checks:

```powershell
docker compose logs --tail 100 worker
docker compose exec -T postgres psql -U senior_pomidor senior_pomidor -c "SELECT count(*) FROM telemetry_events; SELECT count(*) FROM pod_readings;"
```

### 16 Pods

Target:

- dense installation, multiple grow areas, or multiple devices reporting to one
  server
- Grafana needs deliberate filtering or additional dashboards to stay readable
- photo storage policy should be explicit before deployment

Server work:

- keep pod keys stable and short; avoid renaming pods after data collection starts
- confirm edge payload generation remains reliable at the selected interval
- consider lowering telemetry frequency if sensors do not need 2-minute data
- add Grafana dashboard variants for grouped pod views, for example pods 1-4,
  5-8, 9-12, and 13-16
- monitor PostgreSQL query latency for Grafana time ranges of 30 days or more
- use 4 CPU cores, 8-16 GB RAM, and 128-256 GB SSD as the default host class

Operational checks:

```powershell
docker compose exec -T postgres psql -U senior_pomidor senior_pomidor -c "SELECT pod_key, max(timestamp_utc) FROM telemetry_pod_readings_flat GROUP BY pod_key ORDER BY pod_key;"
docker compose exec -T postgres psql -U senior_pomidor senior_pomidor -c "SELECT pg_size_pretty(pg_database_size('senior_pomidor'));"
```

## Grafana Capacity Notes

The provisioned dashboard is designed for dynamic device and pod filtering:

- `Device` filter reads from `devices`
- `Pod` filter reads from `telemetry_pod_readings_flat`
- time-series panels use PostgreSQL queries against the flattened pod view
- recent photo metadata links back to the API photo endpoint

For 4 pods, the default dashboard should remain readable. For 8 pods, use the
pod filter when inspecting trends. For 16 pods, plan either grouped dashboards or
repeated panels so each chart has a manageable number of series.

Grafana should remain behind the trusted LAN. If remote viewing is required, put
it behind a VPN or authenticated reverse proxy rather than exposing port `3000`
directly to the internet.

## Monitoring Checklist

Daily or weekly:

```powershell
docker compose --profile observability ps
docker compose logs --tail 100 api
docker compose logs --tail 100 worker
docker compose logs --tail 100 grafana
```

Database and photo growth:

```powershell
docker compose exec -T postgres psql -U senior_pomidor senior_pomidor -c "SELECT pg_size_pretty(pg_database_size('senior_pomidor'));"
docker system df -v
```

Telemetry freshness by pod:

```powershell
docker compose exec -T postgres psql -U senior_pomidor senior_pomidor -c "SELECT pod_key, max(timestamp_utc) AS latest FROM telemetry_pod_readings_flat GROUP BY pod_key ORDER BY pod_key;"
```

Grafana:

```text
http://localhost:3000/d/senior-pomidor-telemetry/senior-pomidor-telemetry
```

API dashboard:

```text
http://localhost:8000/dashboard
```

## Backup And Retention Plan

At minimum, back up PostgreSQL and uploaded photos before firmware changes,
server upgrades, or hardware changes.

Recommended cadence:

| Deployment | Backup cadence | Retention |
| --- | --- | --- |
| 4 pods, small photos | weekly | 4-8 weekly backups |
| 8 pods, regular photos | weekly plus before upgrades | 8-12 weekly backups |
| 16 pods or large photos | daily database, weekly photo archive | 30 daily DB backups and 8-12 weekly photo archives |

Keep backups outside the repository and preferably outside the same physical disk.

PostgreSQL backup:

```powershell
docker compose exec -T postgres pg_dump -U senior_pomidor senior_pomidor > backups\senior_pomidor.sql
```

Photo backup:

```powershell
docker run --rm -v senior-pomidor-server_photo_data:/data -v ${PWD}\backups:/backup alpine tar czf /backup/photo_data.tgz -C /data .
```

For large photo deployments, define a retention policy before the disk reaches
70% usage. Options are:

- keep all photos for 3 months, then archive to external storage
- keep daily representative photos long term and prune the rest
- reduce camera upload size or frequency
- separate photo storage onto a larger disk

## Power Estimate

For 24/7 operation, approximate energy use by runtime period:

| Host class | Typical draw | 3 months | 6 months | 12 months |
| --- | ---: | ---: | ---: | ---: |
| Raspberry Pi or low-power board with SSD | 8 W | ~17 kWh | ~35 kWh | ~70 kWh |
| Mini PC | 15 W | ~32 kWh | ~65 kWh | ~131 kWh |
| Older laptop or small desktop | 30 W | ~65 kWh | ~130 kWh | ~263 kWh |
| Desktop tower | 60 W | ~130 kWh | ~259 kWh | ~526 kWh |

For this workload, a low-power mini PC or Raspberry Pi class host with an SSD is
usually a better fit than a full desktop.

## When To Revisit Capacity

Recalculate sizing when any of these change:

- telemetry interval drops below 1 minute
- pod count exceeds 16
- more than one edge device reports to the same server
- photo size rises above 1 MB on average
- photos are captured more often than once every 15-20 minutes
- Grafana dashboards are used by multiple users at the same time
- local AI analysis is scheduled instead of run manually

The first likely bottleneck is disk growth from photos. The second is Grafana
query readability with many pod series selected. CPU and memory should remain
comfortable for normal API, MQTT, and PostgreSQL ingestion at the planned pod
counts.
