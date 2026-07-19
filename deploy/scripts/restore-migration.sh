#!/usr/bin/env bash
set -euo pipefail

backup_dir="${1:-}"
[[ "${EUID}" -eq 0 ]] || { echo "run as root" >&2; exit 1; }
[[ -d "$backup_dir" && -f "$backup_dir/database.dump" && -f "$backup_dir/SHA256SUMS" ]] || {
  echo "usage: $0 <verified-migration-directory>" >&2
  exit 2
}
backup_dir="$(readlink -f "$backup_dir")"
migration_root="$(readlink -f /srv/backups/senior-pomidor/migration)"
[[ "$backup_dir" == "$migration_root"/* ]] || {
  echo "refusing restore outside $migration_root" >&2
  exit 1
}
(cd "$backup_dir" && sha256sum --check SHA256SUMS)

app_dir=/srv/apps/senior-pomidor/app
env_file=/srv/secrets/senior-pomidor/runtime.env
[[ -r "$env_file" ]] || { echo "missing environment file: $env_file" >&2; exit 1; }
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
  echo "database restore settings are incomplete" >&2
  exit 1
}

for target in "$photo_dir" "$estimator_dir" "$mosquitto_dir"; do
  [[ -d "$target" ]] || { echo "missing application directory: $target" >&2; exit 1; }
  [[ -z "$(find "$target" -mindepth 1 -maxdepth 1 -print -quit)" ]] || {
    echo "refusing restore: $target is not empty" >&2
    exit 1
  }
done

pg_client=(docker run --rm --network "$platform_network" -e PGPASSWORD="$postgres_password" postgres:16-alpine)
for _ in $(seq 1 60); do
  "${pg_client[@]}" pg_isready -h "$postgres_host" -p "$postgres_port" \
    -U "$postgres_user" -d "$postgres_db" && break
  sleep 2
done
"${pg_client[@]}" pg_isready -h "$postgres_host" -p "$postgres_port" \
  -U "$postgres_user" -d "$postgres_db"
user_table_count="$("${pg_client[@]}" psql -h "$postgres_host" -p "$postgres_port" \
  -U "$postgres_user" -d "$postgres_db" -Atc \
  "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema')")"
[[ "$user_table_count" == 0 ]] || {
  echo "refusing restore: database $postgres_db contains $user_table_count user tables" >&2
  exit 1
}
"${pg_client[@]}" pg_restore -h "$postgres_host" -p "$postgres_port" \
  --no-owner --no-acl -U "$postgres_user" -d "$postgres_db" < "$backup_dir/database.dump"

[[ ! -f "$backup_dir/photos.tar.gz" ]] || tar --numeric-owner -C "$photo_dir" -xzf "$backup_dir/photos.tar.gz"
[[ ! -f "$backup_dir/estimator-private.tar.gz" ]] || tar --numeric-owner -C "$estimator_dir" -xzf "$backup_dir/estimator-private.tar.gz"
[[ ! -f "$backup_dir/mosquitto.tar.gz" ]] || tar --numeric-owner -C "$mosquitto_dir" -xzf "$backup_dir/mosquitto.tar.gz"
if [[ -f "$backup_dir/grafana.tar.gz" ]]; then
  echo "Ignoring legacy grafana.tar.gz; shared Grafana is platform-managed." >&2
fi

compose=(docker compose --env-file "$env_file" -f docker-compose.yml -f docker-compose.prod.yml)
(cd "$app_dir" && "${compose[@]}" run --rm migrate)
"${pg_client[@]}" psql -h "$postgres_host" -p "$postgres_port" \
  -U "$postgres_user" -d "$postgres_db" -Atc \
  "SELECT version_num FROM alembic_version" | grep -Fx 0008_story_environment
echo "Restore and migration completed; start the stack with systemctl start senior-pomidor."
