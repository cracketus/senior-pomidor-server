#!/usr/bin/env bash
set -uo pipefail
umask 077

# Bounded, read-only soak monitor for the isolated staging project.
# It never restarts services, removes containers, or changes volumes.

readonly project_name="senior-pomidor-staging"
readonly edge_container="senior-pomidor-edge-staging"
readonly interop_network="senior-pomidor-staging-interop"
readonly edge_device_id="edge-staging-ubuntu-01"
readonly core_containers=(
  senior-pomidor-staging-api-1
  senior-pomidor-staging-grafana-1
  senior-pomidor-staging-mosquitto-1
  senior-pomidor-staging-postgres-1
  senior-pomidor-staging-state-estimator-worker-1
  senior-pomidor-staging-worker-1
)

duration_seconds="${STAGING_SOAK_DURATION_SECONDS:-86400}"
interval_seconds="${STAGING_SOAK_INTERVAL_SECONDS:-300}"
command_timeout_seconds="${STAGING_SOAK_COMMAND_TIMEOUT_SECONDS:-30}"
max_gap_seconds="${STAGING_SOAK_MAX_GAP_SECONDS:-60}"
max_log_bytes="${STAGING_SOAK_MAX_LOG_BYTES:-10485760}"
server_root="${SERVER_ROOT:-$(pwd)}"
staging_root="${STAGING_ROOT:-${HOME:?HOME is required}/.local-staging}"
env_file="${staging_root}/secrets/staging.env"
api_base_url="${STAGING_API_BASE_URL:-http://127.0.0.1:18000}"
log_file="${staging_root}/logs/staging-overnight-check.log"
result_file="${staging_root}/logs/staging-overnight-result.json"
lock_file="${staging_root}/run/staging-overnight-check.lock"
once=false

usage() {
  echo "Usage: bash tools/staging_overnight_check.sh [--once]" >&2
}

if [[ $# -gt 1 ]]; then
  usage
  exit 2
fi
if [[ $# -eq 1 ]]; then
  if [[ "$1" != "--once" ]]; then
    usage
    exit 2
  fi
  once=true
fi

validate_integer() {
  local name="$1"
  local value="$2"
  local minimum="$3"
  local maximum="$4"
  if ! [[ "$value" =~ ^(0|[1-9][0-9]*)$ ]] || (( value < minimum || value > maximum )); then
    echo "$name must be an integer in the range ${minimum}..${maximum}" >&2
    exit 2
  fi
}

validate_integer STAGING_SOAK_DURATION_SECONDS "$duration_seconds" 60 172800
validate_integer STAGING_SOAK_INTERVAL_SECONDS "$interval_seconds" 30 3600
validate_integer STAGING_SOAK_COMMAND_TIMEOUT_SECONDS "$command_timeout_seconds" 1 120
validate_integer STAGING_SOAK_MAX_GAP_SECONDS "$max_gap_seconds" 0 600
validate_integer STAGING_SOAK_MAX_LOG_BYTES "$max_log_bytes" 1048576 104857600

if (( interval_seconds > duration_seconds )); then
  echo "STAGING_SOAK_INTERVAL_SECONDS cannot exceed the duration" >&2
  exit 2
fi
if [[ -n "${COMPOSE_PROJECT_NAME:-}" && "$COMPOSE_PROJECT_NAME" != "$project_name" ]]; then
  echo "COMPOSE_PROJECT_NAME must be $project_name" >&2
  exit 2
fi
if [[ ! "$api_base_url" =~ ^http://127\.0\.0\.1:([0-9]{1,5})$ ]]; then
  echo "STAGING_API_BASE_URL must be an http://127.0.0.1:<port> URL" >&2
  exit 2
fi
api_port="${BASH_REMATCH[1]}"
if [[ ! "$api_port" =~ ^[1-9][0-9]*$ ]] || (( api_port < 1 || api_port > 65535 )); then
  echo "STAGING_API_BASE_URL port must be in the range 1..65535" >&2
  exit 2
fi

for required_command in docker curl timeout flock python3 date sleep wc dirname mkdir mv; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "required command not found: $required_command" >&2
    exit 2
  fi
done
if [[ ! -d "$server_root" || ! -f "$server_root/docker-compose.yml" || ! -f "$server_root/docker-compose.staging.yml" ]]; then
  echo "SERVER_ROOT must contain the staging Compose files" >&2
  exit 2
fi
if [[ ! -f "$env_file" ]]; then
  echo "staging env file not found: $env_file" >&2
  exit 2
fi

read_env_value() {
  local wanted_key="$1"
  local line key value
  local matches=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    if [[ "$key" == "$wanted_key" ]]; then
      matches=$((matches + 1))
      printf '%s' "$value"
    fi
  done <"$env_file"
  (( matches == 1 ))
}

if ! deployment_mode="$(read_env_value DEPLOYMENT_MODE)" || [[ "$deployment_mode" != "staging" ]]; then
  echo "staging env must contain exactly one DEPLOYMENT_MODE=staging" >&2
  exit 2
fi
if ! configured_network="$(read_env_value STAGING_INTEROP_NETWORK)" || [[ "$configured_network" != "$interop_network" ]]; then
  echo "staging env must select the fixed interop network" >&2
  exit 2
fi
if ! configured_edge="$(read_env_value STAGING_EDGE_CONTAINER_NAME)" || [[ "$configured_edge" != "$edge_container" ]]; then
  echo "staging env must select the fixed Edge container" >&2
  exit 2
fi
if ! external_export="$(read_env_value GRAFANA_CLOUD_EXPORT_ENABLED)" || [[ "$external_export" != "false" ]]; then
  echo "staging env must disable Grafana Cloud export" >&2
  exit 2
fi
if ! configured_api_port="$(read_env_value STAGING_API_PUBLISHED_PORT)" || [[ "$configured_api_port" != "$api_port" ]]; then
  echo "STAGING_API_BASE_URL must match STAGING_API_PUBLISHED_PORT" >&2
  exit 2
fi
if ! app_image="$(read_env_value APP_IMAGE)" || [[ ! "$app_image" =~ @sha256:[0-9a-f]{64}$ ]]; then
  echo "staging env must pin APP_IMAGE by sha256 digest" >&2
  exit 2
fi

path_is_within() {
  local root="$1"
  local candidate="$2"
  python3 -c '
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
candidate = Path(sys.argv[2]).resolve()
raise SystemExit(0 if candidate == root or root in candidate.parents else 1)
' "$root" "$candidate"
}

for staging_path_key in \
  STAGING_POSTGRES_DATA_DIR \
  STAGING_MOSQUITTO_DATA_DIR \
  STAGING_PHOTO_DATA_DIR \
  STAGING_ESTIMATOR_PRIVATE_DATA_DIR \
  STAGING_GRAFANA_DATA_DIR \
  STAGING_MOSQUITTO_PASSWORD_FILE \
  STAGING_MOSQUITTO_ACL_FILE; do
  if ! staging_path="$(read_env_value "$staging_path_key")" || ! path_is_within "$staging_root" "$staging_path"; then
    echo "$staging_path_key must resolve inside STAGING_ROOT" >&2
    exit 2
  fi
done
if ! mosquitto_config="$(read_env_value STAGING_MOSQUITTO_CONFIG_FILE)" || ! path_is_within "$server_root" "$mosquitto_config"; then
  echo "STAGING_MOSQUITTO_CONFIG_FILE must resolve inside SERVER_ROOT" >&2
  exit 2
fi

if ! mkdir -p "$(dirname "$log_file")" "$(dirname "$result_file")" "$(dirname "$lock_file")"; then
  echo "cannot create staging monitor directories" >&2
  exit 2
fi
if ! cd "$server_root"; then
  echo "cannot enter SERVER_ROOT" >&2
  exit 2
fi

exec 9>"$lock_file"
if ! flock -n 9; then
  echo "another staging overnight monitor is already running" >&2
  exit 2
fi

compose=(
  docker compose
  --env-file "$env_file"
  -f docker-compose.yml
  -f docker-compose.staging.yml
  --project-name "$project_name"
  --profile observability
)

finalized=0
failures=0
started_epoch="$(date +%s)"
started_utc="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
termination_reason=""

log() {
  printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >>"$log_file"
}

write_result() {
  local status="$1"
  local reason="$2"
  local completed_utc temporary_result
  completed_utc="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  temporary_result="${result_file}.tmp.$$"
  printf '{"schema_version":"senior-pomidor.staging-soak-result.v1","status":"%s","failures":%d,"started_at_utc":"%s","completed_at_utc":"%s","reason":"%s"}\n' \
    "$status" "$failures" "$started_utc" "$completed_utc" "$reason" >"$temporary_result"
  mv -f "$temporary_result" "$result_file"
}

on_signal() {
  termination_reason="$1"
  exit 130
}

on_exit() {
  local exit_code="$?"
  trap - EXIT
  if (( finalized == 0 )); then
    if [[ -n "$termination_reason" ]]; then
      log "END status=INTERRUPTED failures=$failures reason=$termination_reason"
      write_result "INTERRUPTED" "$termination_reason"
    else
      log "END status=ERROR failures=$failures reason=unexpected-exit"
      write_result "ERROR" "unexpected-exit"
    fi
  fi
  exit "$exit_code"
}

trap 'on_signal SIGINT' INT
trap 'on_signal SIGTERM' TERM
trap 'on_signal SIGHUP' HUP
trap on_exit EXIT

run_with_timeout() {
  timeout --signal=TERM --kill-after=5s "${command_timeout_seconds}s" "$@"
}

record_failure() {
  log "FAIL $1"
  failures=$((failures + 1))
}

run_logged_check() {
  local label="$1"
  shift
  if run_with_timeout "$@" >>"$log_file" 2>&1; then
    log "PASS $label"
    return 0
  fi
  record_failure "$label"
  return 1
}

run_quiet_check() {
  local label="$1"
  shift
  if run_with_timeout "$@" >/dev/null 2>&1; then
    log "PASS $label"
    return 0
  fi
  record_failure "$label"
  return 1
}

validate_json_response() {
  local response_kind="$1"
  python3 -c '
import json
import sys

kind = sys.argv[1]
payload = json.load(sys.stdin)
valid = (
    (kind == "ready" and isinstance(payload, dict) and payload.get("ready") is True)
    or (kind == "health" and isinstance(payload, dict) and payload.get("status") == "ok")
    or (kind == "edge-telemetry" and isinstance(payload, list) and len(payload) > 0)
)
raise SystemExit(0 if valid else 1)
' "$response_kind"
}

check_http_json() {
  local label="$1"
  local response_kind="$2"
  local url="$3"
  local response
  if ! response="$(curl --fail --silent --show-error --connect-timeout 5 --max-time 15 --max-filesize 1048576 "$url" 2>>"$log_file")"; then
    record_failure "$label"
    return 1
  fi
  if printf '%s' "$response" | validate_json_response "$response_kind"; then
    log "PASS $label"
    return 0
  fi
  record_failure "$label-invalid-response"
  return 1
}

check_core_services() {
  local states container state health
  declare -A observed_states=()
  if ! states="$(run_with_timeout docker inspect --format '{{.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "${core_containers[@]}" 2>>"$log_file")"; then
    record_failure "core-services-inspect"
    return 1
  fi
  while IFS='|' read -r container state health; do
    observed_states["${container#/}"]="$state $health"
  done <<<"$states"
  for container in "${core_containers[@]}"; do
    state="${observed_states[$container]:-missing missing}"
    if [[ "$state" != "running healthy" ]]; then
      log "STATE core-service-$container $state"
      record_failure "core-service-$container-not-healthy"
      continue
    fi
    log "PASS core-service-$container"
  done
}

check_edge() {
  local state
  if ! state="$(run_with_timeout docker inspect --format '{{.State.Status}} {{if index .NetworkSettings.Networks "senior-pomidor-staging-interop"}}connected{{else}}missing{{end}}' "$edge_container" 2>>"$log_file")"; then
    record_failure "edge-inspect"
    return 1
  fi
  if [[ "$state" != "running connected" ]]; then
    log "STATE edge $state"
    record_failure "edge-not-running-or-connected"
    return 1
  fi
  log "PASS edge-running-and-connected"
  run_quiet_check "edge-spool-status" docker exec "$edge_container" python scripts/telemetry_spool.py status || true
}

check_log_limit() {
  local current_size
  current_size="$(wc -c <"$log_file")"
  if (( current_size > max_log_bytes )); then
    record_failure "log-size-limit-exceeded"
    return 1
  fi
  return 0
}

docker_endpoint="$(run_with_timeout docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
if [[ ! "$docker_endpoint" =~ ^(unix://|npipe://) ]]; then
  echo "staging monitor requires a local Docker endpoint" >&2
  exit 2
fi
if ! run_with_timeout "${compose[@]}" config --quiet >/dev/null 2>&1; then
  echo "staging Compose configuration is invalid" >&2
  exit 2
fi

deadline=$((started_epoch + duration_seconds))
last_check_epoch=0
write_result "RUNNING" "monitor-active"
log "START duration_seconds=$duration_seconds interval_seconds=$interval_seconds project=$project_name"

while true; do
  now="$(date +%s)"
  if (( last_check_epoch > 0 )); then
    observed_gap=$((now - last_check_epoch))
    allowed_gap=$((interval_seconds + max_gap_seconds))
    if (( observed_gap < 0 || observed_gap > allowed_gap )); then
      record_failure "check-gap-observed-${observed_gap}s-allowed-${allowed_gap}s"
    fi
  fi
  if (( now >= deadline )); then
    break
  fi
  last_check_epoch="$now"

  log "CHECK"
  run_logged_check "compose-ps" "${compose[@]}" ps || true
  check_core_services || true
  check_http_json "ready" "ready" "$api_base_url/ready" || true
  check_http_json "health" "health" "$api_base_url/health" || true
  check_edge || true
  check_http_json "edge-telemetry-fresh" "edge-telemetry" \
    "$api_base_url/api/v1/devices/$edge_device_id/telemetry?since_hours=1&limit=1" || true

  if ! check_log_limit; then
    break
  fi
  if [[ "$once" == true ]]; then
    break
  fi

  now="$(date +%s)"
  remaining=$((deadline - now))
  (( remaining <= 0 )) && continue
  sleep_for="$interval_seconds"
  (( sleep_for > remaining )) && sleep_for="$remaining"
  sleep "$sleep_for"
done

if (( failures > 0 )); then
  status="FAIL"
  exit_code=1
else
  status="PASS"
  exit_code=0
fi
log "END status=$status failures=$failures"
write_result "$status" "monitor-complete"
finalized=1
exit "$exit_code"
