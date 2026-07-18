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
usermod -aG docker senior-pomidor

install -d -o senior-pomidor -g senior-pomidor -m 0750 \
  /srv/apps/senior-pomidor/releases /srv/apps/archive \
  /srv/media/photos/senior-pomidor \
  /srv/logs/senior-pomidor/estimator-private \
  /srv/backups/senior-pomidor
install -d -o root -g senior-pomidor -m 0750 /srv/secret
install -d -o 70 -g 70 -m 0700 /srv/data/postgres
install -d -o 472 -g 472 -m 0750 /srv/data/grafana
install -d -o 1883 -g 1883 -m 0750 /srv/data/mosquitto
install -d -o root -g root -m 0750 /srv/data/ollama

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install -d -o root -g root -m 0755 /srv/automation /srv/automation/apt /srv/automation/systemd
for script in "$bundle_root"/scripts/*.sh; do
  install -o root -g root -m 0755 "$script" "/srv/automation/$(basename "$script")"
done
for unit in "$bundle_root"/deploy/systemd/*; do
  install -o root -g root -m 0644 "$unit" "/srv/automation/systemd/$(basename "$unit")"
  install -o root -g root -m 0644 "/srv/automation/systemd/$(basename "$unit")" \
    "/etc/systemd/system/$(basename "$unit")"
done
install -o root -g root -m 0644 "$bundle_root/deploy/apt/20auto-upgrades" \
  /srv/automation/apt/20auto-upgrades
install -o root -g root -m 0644 /srv/automation/apt/20auto-upgrades \
  /etc/apt/apt.conf.d/20auto-upgrades
systemctl daemon-reload

echo "Host directories and automation installed. Install the environment file and release before enabling systemd."
