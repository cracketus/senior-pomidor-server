#!/usr/bin/env bash
set -euo pipefail

mode="${1:-daily}"
[[ "$mode" == daily || "$mode" == weekly ]] || { echo "usage: $0 [daily|weekly]" >&2; exit 2; }
[[ "${EUID}" -eq 0 ]] || { echo "run as root" >&2; exit 1; }

app_dir=/srv/apps/senior-pomidor/app
backup_root=/srv/backups/senior-pomidor
env_file=/srv/secrets/senior-pomidor/runtime.env
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$backup_root/$mode/$timestamp"
[[ -r "$env_file" ]] || { echo "missing environment file: $env_file" >&2; exit 1; }
install -d -m 0700 -o root -g root "$target"

read_env() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1
}
postgres_host="$(read_env POSTGRES_HOST)"
postgres_port="$(read_env POSTGRES_PORT)"
postgres_user="$(read_env POSTGRES_USER)"
postgres_db="$(read_env POSTGRES_DB)"
postgres_password="$(read_env POSTGRES_PASSWORD)"
platform_network="$(read_env PLATFORM_DOCKER_NETWORK)"
photo_dir="$(read_env PHOTO_DATA_DIR)"
estimator_dir="$(read_env ESTIMATOR_PRIVATE_DATA_DIR)"
mosquitto_dir="$(read_env MOSQUITTO_DATA_DIR)"
postgres_host="${postgres_host:-postgres}"
postgres_port="${postgres_port:-5432}"
platform_network="${platform_network:-srv-platform}"
photo_dir="${photo_dir:-/srv/apps/senior-pomidor/data/public/photos}"
estimator_dir="${estimator_dir:-/srv/logs/senior-pomidor/estimator-private}"
mosquitto_dir="${mosquitto_dir:-/srv/apps/senior-pomidor/data/private/mosquitto}"
[[ -n "$postgres_user" && -n "$postgres_db" && -n "$postgres_password" ]] || {
  echo "database backup settings are incomplete" >&2
  exit 1
}

compose=(docker compose --env-file "$env_file" -f docker-compose.yml -f docker-compose.prod.yml)
pg_client=(docker run --rm --network "$platform_network" -e PGPASSWORD="$postgres_password" postgres:16-alpine)

restart_writers=false
running_writers=()
restart_services() {
  if [[ "$restart_writers" == true && "${#running_writers[@]}" -gt 0 ]]; then
    (cd "$app_dir" && "${compose[@]}" up -d "${running_writers[@]}")
  fi
}
if [[ "$mode" == weekly ]]; then
  running_services="$(cd "$app_dir" && "${compose[@]}" ps --services --filter status=running)"
  for service in api worker state-estimator-worker daily-story-worker mosquitto; do
    if grep -Fxq "$service" <<< "$running_services"; then
      running_writers+=("$service")
    fi
  done
  restart_writers=true
  trap restart_services EXIT
  if [[ "${#running_writers[@]}" -gt 0 ]]; then
    (cd "$app_dir" && "${compose[@]}" stop "${running_writers[@]}")
  fi
fi

"${pg_client[@]}" pg_dump -h "$postgres_host" -p "$postgres_port" \
  --format=custom --no-owner --no-acl -U "$postgres_user" "$postgres_db" > "$target/database.dump"
"${pg_client[@]}" pg_dumpall --globals-only --no-role-passwords \
  -h "$postgres_host" -p "$postgres_port" -U "$postgres_user" > "$target/globals-audit.sql"

if [[ "$mode" == weekly ]]; then
  tar --numeric-owner -C "$photo_dir" -czf "$target/photos.tar.gz" .
  tar --numeric-owner -C "$estimator_dir" -czf "$target/estimator-private.tar.gz" .
  tar --numeric-owner -C "$mosquitto_dir" -czf "$target/mosquitto.tar.gz" .
  restart_services
  restart_writers=false
  trap - EXIT
fi

(
  cd "$target"
  sha256sum -- * > SHA256SUMS
  sha256sum --check SHA256SUMS
)
find "$backup_root/daily" -mindepth 1 -maxdepth 1 -type d -mtime +30 -print -exec rm -rf -- {} +
find "$backup_root/weekly" -mindepth 1 -maxdepth 1 -type d -mtime +56 -print -exec rm -rf -- {} +
echo "$target"
