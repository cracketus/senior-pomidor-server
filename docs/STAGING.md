# Isolated software staging

This environment implements the server half of issue #202. It is persistent and disposable by operator
decision, but it is not production and must never use production credentials, paths, MQTT topics, devices,
or Grafana Cloud export.

Copy `deploy/senior-pomidor-staging.env.example` to a protected file outside the checkout. Replace every
`CHANGE_ME` value, pin `APP_IMAGE` to the exact candidate digest, and keep all published ports on loopback.
Use a stable, staging-only project name:

```console
docker compose --env-file /protected/staging.env \
  -f docker-compose.yml -f docker-compose.staging.yml \
  --project-name senior-pomidor-staging --profile observability config
docker compose --env-file /protected/staging.env \
  -f docker-compose.yml -f docker-compose.staging.yml \
  --project-name senior-pomidor-staging --profile observability up -d
```

Before accepting data, inspect the rendered configuration. Every application container must have
`DEPLOYMENT_MODE=staging`, the `senior-pomidor.environment=staging` label, the staging database URL and MQTT
namespace, staging-only bind paths, and `senior-pomidor.external-export=disabled`. The cloud exporter profile
must not be enabled and all remote-write values must be empty.

Only Edge identities beginning with the configured `STAGING_DEVICE_PREFIX` are accepted by staging HTTP,
photo, and MQTT ingress. Production rejects that same reserved prefix. Configure the real Edge staging target
with a matching identity and `STAGING_MQTT_TOPIC_PREFIX`; sensor values may be simulated, but the Edge and Core
applications must be real immutable artifacts for compatibility evidence.

Stopping staging uses `docker compose ... down` without `--volumes`. Data reset is intentionally not automated
here: a human must verify the exact staging project and resolved bind paths, retain required evidence, and use a
separately approved backup/reset procedure. Never point this overlay at production paths or shared volumes.
