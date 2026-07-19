#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

if ! getent group senior-pomidor >/dev/null; then
  groupadd --system senior-pomidor
fi
if ! id senior-pomidor >/dev/null 2>&1; then
  useradd --system --gid senior-pomidor --home-dir /srv/apps/senior-pomidor \
    --shell /usr/sbin/nologin senior-pomidor
fi
if id -nG senior-pomidor | tr ' ' '\n' | grep -Fxq docker; then
  gpasswd -d senior-pomidor docker
fi

app_root=/srv/apps/senior-pomidor
install -d -o root -g root -m 0755 \
  "$app_root" "$app_root/data" "$app_root/data/private" "$app_root/data/public" \
  "$app_root/releases" "$app_root/releases/.incoming" /srv/apps/archive
install -d -o senior-pomidor -g senior-pomidor -m 0750 \
  "$app_root/data/public/photos"
install -d -o 1883 -g 1883 -m 0750 "$app_root/data/private/mosquitto"
install -d -o root -g root -m 0700 \
  /srv/secrets/senior-pomidor \
  /srv/backups/senior-pomidor \
  /srv/backups/senior-pomidor/daily \
  /srv/backups/senior-pomidor/weekly \
  /srv/backups/senior-pomidor/migration \
  /srv/logs/senior-pomidor/estimator-private

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -e /srv/secrets/senior-pomidor/runtime.env ]]; then
  install -o root -g root -m 0600 "$bundle_root/senior-pomidor.env.example" \
    /srv/secrets/senior-pomidor/runtime.env
fi
install -d -o root -g root -m 0755 \
  /srv/automation /srv/automation/ansible /srv/automation/cron \
  /srv/automation/scripts /srv/automation/scripts/senior-pomidor \
  /srv/automation/systemd
for script in "$bundle_root"/scripts/*.sh; do
  install -o root -g root -m 0755 "$script" \
    "/srv/automation/scripts/senior-pomidor/$(basename "$script")"
done
for unit in "$bundle_root"/deploy/systemd/*; do
  install -o root -g root -m 0644 "$unit" "/srv/automation/systemd/$(basename "$unit")"
  install -o root -g root -m 0644 "/srv/automation/systemd/$(basename "$unit")" \
    "/etc/systemd/system/$(basename "$unit")"
done
install -o root -g root -m 0644 "$bundle_root/deploy/apt/20auto-upgrades" \
  /etc/apt/apt.conf.d/20auto-upgrades
systemctl daemon-reload

echo "Host directories and automation installed. Install the environment file and release before enabling systemd."
