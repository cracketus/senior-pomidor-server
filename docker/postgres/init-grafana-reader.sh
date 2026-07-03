#!/usr/bin/env sh
set -eu

: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"

GRAFANA_DB_USER="${GRAFANA_DB_USER:-grafana_reader}"
GRAFANA_DB_PASSWORD="${GRAFANA_DB_PASSWORD:-grafana_reader}"

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -v postgres_db="$POSTGRES_DB" \
  -v app_owner="$POSTGRES_USER" \
  -v grafana_user="$GRAFANA_DB_USER" \
  -v grafana_password="$GRAFANA_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'grafana_user', :'grafana_password')
WHERE NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = :'grafana_user'
)
\gexec

ALTER ROLE :"grafana_user" WITH LOGIN PASSWORD :'grafana_password';
GRANT CONNECT ON DATABASE :"postgres_db" TO :"grafana_user";
GRANT USAGE ON SCHEMA public TO :"grafana_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"app_owner" IN SCHEMA public GRANT SELECT ON TABLES TO :"grafana_user";

WITH required_tables(table_name) AS (
    VALUES
        ('devices'),
        ('telemetry_events'),
        ('pod_readings'),
        ('pod_errors'),
        ('photos'),
        ('telemetry_pod_readings_flat'),
        ('state_snapshots'),
        ('sensor_health_snapshots'),
        ('anomaly_records'),
        ('estimator_diagnostics')
)
SELECT format('GRANT SELECT ON TABLE public.%I TO %I', table_name, :'grafana_user')
FROM required_tables
WHERE to_regclass(format('public.%I', table_name)) IS NOT NULL
\gexec
SQL
