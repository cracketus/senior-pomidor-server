#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 <runtime.tar.gz> <runtime.tar.gz.sha256>" >&2
  exit 2
}

[[ "${EUID}" -eq 0 ]] || { echo "run as root" >&2; exit 1; }
archive="${1:-}"
checksum="${2:-}"
[[ -f "$archive" && -f "$checksum" ]] || usage

archive="$(readlink -f "$archive")"
checksum="$(readlink -f "$checksum")"
(
  cd "$(dirname "$archive")"
  sha256sum --check "$checksum"
)

app_root=/srv/apps/senior-pomidor
active_link="$app_root/app"
stage="$(mktemp -d "$app_root/releases/.incoming/install.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
tar -xzf "$archive" -C "$stage"
version="$(tr -d '\r\n' < "$stage/VERSION")"
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "invalid bundle VERSION" >&2; exit 1; }
if find "$stage" -type f -name '*.py' -print -quit | grep -q .; then
  echo "refusing runtime bundle containing Python source" >&2
  exit 1
fi

release_dir="$app_root/releases/$version"
[[ ! -e "$release_dir" ]] || { echo "$release_dir already exists" >&2; exit 1; }
previous_release="$(readlink -f "$active_link" 2>/dev/null || true)"
install -d -o root -g root -m 0755 "$release_dir"
cp -a "$stage/." "$release_dir/"
chown -R root:root "$release_dir"
find "$release_dir" -type d -exec chmod 0755 {} +
find "$release_dir" -type f -exec chmod 0644 {} +
find "$release_dir/scripts" -type f -name '*.sh' -exec chmod 0755 {} +

env_file=/srv/secrets/senior-pomidor/runtime.env
[[ -f "$env_file" ]] || { echo "missing environment file: $env_file" >&2; exit 1; }
app_image="$(sed -n 's/^APP_IMAGE=//p' "$env_file" | tail -n 1)"
case "$app_image" in
  ghcr.io/cracketus/senior-pomidor-server:"$version"|ghcr.io/cracketus/senior-pomidor-server@sha256:*) ;;
  *) echo "APP_IMAGE must be this release tag or an immutable GHCR digest" >&2; exit 1 ;;
esac

docker pull "$app_image"
(cd "$release_dir" && docker compose --env-file "$env_file" \
  -f docker-compose.yml -f docker-compose.prod.yml config --quiet)
ln -s "$release_dir" "$app_root/.app-new"
mv -Tf "$app_root/.app-new" "$active_link"
if [[ -n "$previous_release" && "$previous_release" != "$release_dir" \
  && "$previous_release" == "$app_root"/releases/* ]]; then
  archive_dir=/srv/apps/archive/senior-pomidor
  install -d -o root -g root -m 0755 "$archive_dir"
  [[ ! -e "$archive_dir/$(basename "$previous_release")" ]] || {
    echo "active release changed, but archive target already exists: $previous_release" >&2
    exit 1
  }
  mv "$previous_release" "$archive_dir/"
fi
echo "Installed $version. Run: systemctl reload-or-restart senior-pomidor"
