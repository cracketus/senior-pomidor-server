#!/usr/bin/env bash
set -euo pipefail

mode="${1:-daily}"
[[ "$mode" == daily || "$mode" == weekly ]] || { echo "usage: $0 [daily|weekly]" >&2; exit 2; }

app_dir=/srv/apps/senior-pomidor/current
backup_root=/srv/backups/senior-pomidor
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$backup_root/$mode-$timestamp"
install -d -m 0750 -o senior-pomidor -g senior-pomidor "$target"

cd "$app_dir"
env_file=/srv/secret/senior-pomidor.env
postgres_user="$(sed -n 's/^POSTGRES_USER=//p' "$env_file" | tail -n 1)"
postgres_db="$(sed -n 's/^POSTGRES_DB=//p' "$env_file" | tail -n 1)"
compose=(docker compose --env-file "$env_file")

restart_writers=false
restart_services() {
  if [[ "$restart_writers" == true ]]; then
    "${compose[@]}" up -d api worker state-estimator-worker mosquitto grafana
  fi
}
if [[ "$mode" == weekly ]]; then
  restart_writers=true
  trap restart_services EXIT
  "${compose[@]}" stop api worker state-estimator-worker grafana mosquitto
fi

"${compose[@]}" exec -T postgres pg_dump \
  --format=custom --no-owner --no-acl -U "$postgres_user" \
  "$postgres_db" > "$target/database.dump"
"${compose[@]}" exec -T postgres pg_dumpall --globals-only --no-role-passwords \
  -U "$postgres_user" > "$target/globals-audit.sql"

if [[ "$mode" == weekly ]]; then
  tar --numeric-owner -C /srv/media/photos/senior-pomidor -czf "$target/photos.tar.gz" .
  tar --numeric-owner -C /srv/logs/senior-pomidor/estimator-private -czf "$target/estimator-private.tar.gz" .
  tar --numeric-owner -C /srv/data/grafana -czf "$target/grafana.tar.gz" .
  tar --numeric-owner -C /srv/data/mosquitto -czf "$target/mosquitto.tar.gz" .
  restart_services
  restart_writers=false
  trap - EXIT
fi

(
  cd "$target"
  sha256sum -- * > SHA256SUMS
  sha256sum --check SHA256SUMS
)
find "$backup_root" -mindepth 1 -maxdepth 1 -type d -name 'daily-*' -mtime +30 -print -exec rm -rf -- {} +
find "$backup_root" -mindepth 1 -maxdepth 1 -type d -name 'weekly-*' -mtime +56 -print -exec rm -rf -- {} +
echo "$target"
