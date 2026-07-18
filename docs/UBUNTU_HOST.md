# Ubuntu production host

Production runs from a tagged, source-free runtime bundle. The checkout at
`/srv/git/senior-pomidor-server` is administrative only and must never be referenced by Compose,
systemd, secrets, or bind mounts.

## Provision the operating system

1. Install Ubuntu Server 26.04 LTS, apply all updates, configure administrator SSH keys and time
   synchronization, and disable password SSH login. Install `unattended-upgrades`; the provisioning
   script installs the bundled automatic-update policy.
2. Install Docker Engine and the Compose plugin from Docker's official apt repository, following
   the current [Docker Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/). Do not
   install Ubuntu's `docker.io` package or use Docker's convenience script.
3. Copy the extracted bundle to a temporary location and run:

   ```bash
   sudo ./scripts/provision-host.sh
   sudo install -o root -g senior-pomidor -m 0640 \
     senior-pomidor.env.example /srv/secret/senior-pomidor.env
   sudoedit /srv/secret/senior-pomidor.env
   ```

   Generate new strong application-database and Grafana-reader passwords. URL-encode the database
   password in `DATABASE_URL`. Securely copy the existing photo/telemetry tokens and Grafana Cloud
   credentials. Keep `API_DOCS_ENABLED=false`, `POSTGRES_BIND_ADDRESS=127.0.0.1`, and
   `COMPOSE_PROFILES=observability,cloud-export`. Do not add `llm`.

4. Before the first production tag, publish a disposable GHCR image from this repository, open its
   package settings, link it to the public repository, and set visibility to **Public**. GitHub's
   Packages REST API does not provide a visibility-update endpoint. Release CI verifies anonymous
   access and fails before publishing the GitHub release if this setting is wrong.

5. Download a release archive and its `.sha256` into `/srv/backups/senior-pomidor/releases`, then:

   ```bash
   sudo /srv/automation/install-release.sh \
     senior-pomidor-runtime-vX.Y.Z.tar.gz \
     senior-pomidor-runtime-vX.Y.Z.tar.gz.sha256
   sudo systemctl enable senior-pomidor.service
   sudo systemctl enable --now senior-pomidor-backup-daily.timer \
     senior-pomidor-backup-weekly.timer
   ```

The active release is `/srv/apps/senior-pomidor/current`, a symlink to
`/srv/apps/senior-pomidor/releases/vX.Y.Z`. The environment file must remain root-owned, group
`senior-pomidor`, mode `0640`.

## Network policy

Reserve a stable LAN address. Permit SSH only from the administration subnet, API `8000` and MQTT
`1883` only from authorized edge/admin addresses, and Grafana `3000` only from administrators.
Never permit `5432` or `11434` from the LAN.

Docker-published traffic can bypass ordinary UFW `INPUT` rules. Apply equivalent restrictions in
`DOCKER-USER`, matching the original published port after DNAT. Replace the example interface and
CIDRs, and persist the reviewed rules with the host's firewall tooling:

```bash
sudo iptables -I DOCKER-USER 1 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -I DOCKER-USER 2 -i eno1 -s <EDGE_OR_ADMIN_CIDR> \
  -p tcp -m conntrack --ctorigdstport 8000 -j ACCEPT
sudo iptables -I DOCKER-USER 3 -i eno1 -s <EDGE_OR_ADMIN_CIDR> \
  -p tcp -m conntrack --ctorigdstport 1883 -j ACCEPT
sudo iptables -I DOCKER-USER 4 -i eno1 -s <ADMIN_CIDR> \
  -p tcp -m conntrack --ctorigdstport 3000 -j ACCEPT
sudo iptables -A DOCKER-USER -i eno1 -p tcp -m conntrack \
  --ctorigdstport 8000 -j DROP
sudo iptables -A DOCKER-USER -i eno1 -p tcp -m conntrack \
  --ctorigdstport 1883 -j DROP
sudo iptables -A DOCKER-USER -i eno1 -p tcp -m conntrack \
  --ctorigdstport 3000 -j DROP
```

See Docker's [firewall guidance](https://docs.docker.com/engine/network/packet-filtering-firewalls/).
Anonymous MQTT is retained temporarily for contract compatibility and depends on this allow-list.

## Startup and upgrade

`senior-pomidor.service` validates Compose, enables only `observability,cloud-export`, starts after
Docker/networking, and waits for `/ready`. Install a release with `install-release.sh`, then run
`sudo systemctl reload-or-restart senior-pomidor`. The installer moves the superseded release to
`/srv/apps/archive/senior-pomidor`. Never deploy `latest`.

After changes and after a reboot, verify:

```bash
systemctl status senior-pomidor
cd /srv/apps/senior-pomidor/current && docker compose ps
curl -fsS "http://${NEW_SERVER_LAN_IP}:8000/health"
curl -fsS "http://${NEW_SERVER_LAN_IP}:8000/ready"
ss -lnt | grep 5432
```

Test from another LAN host that PostgreSQL is unreachable. Switch `current` to an archived release
only when its image and schema compatibility are known.
