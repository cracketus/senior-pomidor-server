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

stage="$(mktemp -d /srv/apps/senior-pomidor/.install.XXXXXX)"
trap 'rm -rf "$stage"' EXIT
tar -xzf "$archive" -C "$stage"
version="$(tr -d '\r\n' < "$stage/VERSION")"
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "invalid bundle VERSION" >&2; exit 1; }
if find "$stage" -type f -name '*.py' -print -quit | grep -q .; then
  echo "refusing runtime bundle containing Python source" >&2
  exit 1
fi

release_dir="/srv/apps/senior-pomidor/releases/$version"
[[ ! -e "$release_dir" ]] || { echo "$release_dir already exists" >&2; exit 1; }
previous_release="$(readlink -f /srv/apps/senior-pomidor/current 2>/dev/null || true)"
install -d -o senior-pomidor -g senior-pomidor -m 0750 "$release_dir"
cp -a "$stage/." "$release_dir/"
chown -R senior-pomidor:senior-pomidor "$release_dir"

env_file=/srv/secret/senior-pomidor.env
app_image="$(sed -n 's/^APP_IMAGE=//p' "$env_file" | tail -n 1)"
case "$app_image" in
  ghcr.io/cracketus/senior-pomidor-server:"$version"|ghcr.io/cracketus/senior-pomidor-server@sha256:*) ;;
  *) echo "APP_IMAGE must be this release tag or an immutable GHCR digest" >&2; exit 1 ;;
esac

docker pull "$app_image"
(cd "$release_dir" && docker compose --env-file "$env_file" config --quiet)
ln -s "$release_dir" /srv/apps/senior-pomidor/.current-new
mv -Tf /srv/apps/senior-pomidor/.current-new /srv/apps/senior-pomidor/current
if [[ -n "$previous_release" && "$previous_release" != "$release_dir" \
  && "$previous_release" == /srv/apps/senior-pomidor/releases/* ]]; then
  archive_dir=/srv/apps/archive/senior-pomidor
  install -d -o senior-pomidor -g senior-pomidor -m 0750 "$archive_dir"
  [[ ! -e "$archive_dir/$(basename "$previous_release")" ]] || {
    echo "active release changed, but archive target already exists: $previous_release" >&2
    exit 1
  }
  mv "$previous_release" "$archive_dir/"
fi
echo "Installed $version. Run: systemctl reload-or-restart senior-pomidor"
