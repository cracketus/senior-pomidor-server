#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 vX.Y.Z [output-directory]" >&2
  exit 2
}

version="${1:-}"
output_dir="${2:-dist}"
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || usage

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source_revision="${SOURCE_REVISION:-}"
if [[ -z "$source_revision" ]]; then
  source_revision="$(git -C "$repo_root" rev-parse --verify HEAD)"
fi
[[ "$source_revision" =~ ^[0-9a-fA-F]{40}$ ]] || {
  echo "SOURCE_REVISION must be a full 40-character Git commit" >&2
  exit 1
}
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

install -m 0644 "$repo_root/docker-compose.yml" "$stage/docker-compose.yml"
install -m 0644 "$repo_root/docker-compose.prod.yml" "$stage/docker-compose.prod.yml"
install -m 0644 "$repo_root/mosquitto.conf" "$stage/mosquitto.conf"
install -m 0644 "$repo_root/deploy/senior-pomidor.env.example" "$stage/senior-pomidor.env.example"
printf '%s\n' "$version" > "$stage/VERSION"
printf '%s\n' "$source_revision" > "$stage/REVISION"

install -d "$stage/config" "$stage/deploy/apt" "$stage/deploy/systemd" "$stage/scripts"
cp -a "$repo_root/config/daily_story" "$stage/config/"
cp -a "$repo_root/deploy/apt/." "$stage/deploy/apt/"
for unit in "$repo_root"/deploy/systemd/*; do
  install -m 0644 "$unit" "$stage/deploy/systemd/$(basename "$unit")"
done
for script in "$repo_root"/deploy/scripts/*.sh; do
  install -m 0755 "$script" "$stage/scripts/$(basename "$script")"
done

if find "$stage" -type f -name '*.py' -print -quit | grep -q .; then
  echo "runtime bundle unexpectedly contains Python source" >&2
  exit 1
fi

archive="$output_dir/senior-pomidor-runtime-$version.tar.gz"
tar --sort=name --owner=0 --group=0 --numeric-owner \
  --mtime='UTC 1970-01-01' -C "$stage" -czf "$archive" .
(
  cd "$output_dir"
  sha256sum "$(basename "$archive")" > "$(basename "$archive").sha256"
)
echo "$archive"
