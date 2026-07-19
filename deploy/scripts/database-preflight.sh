#!/usr/bin/env bash
set -euo pipefail

env_file=/srv/secrets/senior-pomidor/runtime.env
[[ -r "$env_file" ]] || { echo "missing environment file: $env_file" >&2; exit 1; }

read_env() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1
}

postgres_host="$(read_env POSTGRES_HOST)"
postgres_port="$(read_env POSTGRES_PORT)"
postgres_db="$(read_env POSTGRES_DB)"
postgres_user="$(read_env POSTGRES_USER)"
postgres_password="$(read_env POSTGRES_PASSWORD)"
platform_network="$(read_env PLATFORM_DOCKER_NETWORK)"
postgres_host="${postgres_host:-postgres}"
postgres_port="${postgres_port:-5432}"
platform_network="${platform_network:-srv-platform}"
[[ -n "$postgres_db" && -n "$postgres_user" && -n "$postgres_password" ]] || {
  echo "POSTGRES_DB, POSTGRES_USER, and POSTGRES_PASSWORD are required" >&2
  exit 1
}

for _ in $(seq 1 60); do
  if docker run --rm --network "$platform_network" \
    -e PGPASSWORD="$postgres_password" postgres:16-alpine \
    pg_isready -h "$postgres_host" -p "$postgres_port" -U "$postgres_user" -d "$postgres_db"; then
    exit 0
  fi
  sleep 2
done
echo "platform PostgreSQL did not become ready" >&2
exit 1
