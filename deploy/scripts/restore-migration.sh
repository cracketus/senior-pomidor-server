#!/usr/bin/env bash
set -euo pipefail

backup_dir="${1:-}"
[[ "${EUID}" -eq 0 ]] || { echo "run as root" >&2; exit 1; }
[[ -d "$backup_dir" && -f "$backup_dir/database.dump" && -f "$backup_dir/SHA256SUMS" ]] || {
  echo "usage: $0 <verified-migration-directory>" >&2
  exit 2
}
backup_dir="$(readlink -f "$backup_dir")"
(cd "$backup_dir" && sha256sum --check SHA256SUMS)

for target in /srv/data/postgres /srv/data/grafana /srv/data/mosquitto \
  /srv/media/photos/senior-pomidor /srv/logs/senior-pomidor/estimator-private; do
  [[ -z "$(find "$target" -mindepth 1 -maxdepth 1 -print -quit)" ]] || {
    echo "refusing restore: $target is not empty" >&2
    exit 1
  }
done

cd /srv/apps/senior-pomidor/current
env_file=/srv/secret/senior-pomidor.env
postgres_user="$(sed -n 's/^POSTGRES_USER=//p' "$env_file" | tail -n 1)"
postgres_db="$(sed -n 's/^POSTGRES_DB=//p' "$env_file" | tail -n 1)"
compose=(docker compose --env-file "$env_file")
"${compose[@]}" up -d postgres
for _ in $(seq 1 60); do
  "${compose[@]}" exec -T postgres pg_isready -U "$postgres_user" -d "$postgres_db" && break
  sleep 2
done
"${compose[@]}" exec -T postgres pg_isready -U "$postgres_user" -d "$postgres_db"
"${compose[@]}" exec -T postgres pg_restore --no-owner --no-acl \
  -U "$postgres_user" -d "$postgres_db" < "$backup_dir/database.dump"

[[ ! -f "$backup_dir/photos.tar.gz" ]] || tar --numeric-owner -C /srv/media/photos/senior-pomidor -xzf "$backup_dir/photos.tar.gz"
[[ ! -f "$backup_dir/estimator-private.tar.gz" ]] || tar --numeric-owner -C /srv/logs/senior-pomidor/estimator-private -xzf "$backup_dir/estimator-private.tar.gz"
[[ ! -f "$backup_dir/grafana.tar.gz" ]] || tar --numeric-owner -C /srv/data/grafana -xzf "$backup_dir/grafana.tar.gz"
[[ ! -f "$backup_dir/mosquitto.tar.gz" ]] || tar --numeric-owner -C /srv/data/mosquitto -xzf "$backup_dir/mosquitto.tar.gz"

"${compose[@]}" run --rm migrate
"${compose[@]}" exec -T postgres sh /docker-entrypoint-initdb.d/20-grafana-reader.sh
"${compose[@]}" exec -T postgres psql -U "$postgres_user" -d "$postgres_db" \
  -Atc "SELECT version_num FROM alembic_version" | grep -Fx 0008_story_environment
echo "Restore and migration completed; start the stack with systemctl start senior-pomidor."
