# Ubuntu mini-PC provisioning

This runbook targets a currently supported Ubuntu Server LTS installation on a trusted LAN. Public internet exposure is not supported.

## Provision

1. Install the current Ubuntu Server LTS, apply updates, and create a non-default administrator account. Configure the router's DHCP reservation (and local DNS, if available) to give this host the laptop's stable LAN identity.
2. Install Docker Engine and the Compose plugin using Docker's official Ubuntu apt repository. Follow the current [Docker Ubuntu installation instructions](https://docs.docker.com/engine/install/ubuntu/); do not use the distro `docker.io` package or the convenience script. Verify `docker compose version`.
3. Create the deployment account and directory:

   ```sh
   sudo adduser --system --group --home /opt/senior-pomidor-server senior-pomidor
   sudo usermod -aG docker senior-pomidor
   sudo install -d -o senior-pomidor -g senior-pomidor -m 0750 /opt/senior-pomidor-server
   sudo -u senior-pomidor git clone <repository-url> /opt/senior-pomidor-server
   ```

4. Copy `.env.example` to `.env`, replace every `CHANGE_ME`, URL-encode the database password in `DATABASE_URL`, and set `LAN_BIND_ADDRESS` to the reserved LAN IPv4 address. Keep `POSTGRES_BIND_ADDRESS=127.0.0.1`.

   ```sh
   sudo install -o root -g senior-pomidor -m 0640 .env.example /opt/senior-pomidor-server/.env
   sudoedit /opt/senior-pomidor-server/.env
   sudo -u senior-pomidor docker compose --project-directory /opt/senior-pomidor-server config --quiet
   ```

5. Restrict the host firewall to SSH from the administration network and API/MQTT from authorized edge-device addresses. Open Grafana only if the observability profile is enabled. Never allow TCP 5432 from the LAN.
6. Install unattended security updates and the service:

   ```sh
   sudo apt-get install unattended-upgrades curl
   sudo install -m 0644 deploy/apt/20auto-upgrades /etc/apt/apt.conf.d/20auto-upgrades
   sudo install -m 0644 deploy/systemd/senior-pomidor.service /etc/systemd/system/senior-pomidor.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now senior-pomidor.service
   curl -fsS http://127.0.0.1:8000/ready
   ```

Confirm PostgreSQL is host-local with `ss -lnt | grep 5432`, and test from a different LAN host that TCP 5432 is refused. Reboot the host and restart Docker separately; after each operation verify `systemctl status senior-pomidor`, `docker compose ps`, and `GET /ready` without issuing manual container commands.

## Upgrade and rollback

Before an upgrade, take and verify a database backup and record the current commit with `git rev-parse HEAD`. Fetch the intended release, inspect `.env.example` changes, run `docker compose config --quiet`, then run `sudo systemctl reload senior-pomidor`. Verify health and logs. To roll back, check out the recorded commit, restore the matching backup if its migrations are incompatible, and reload the unit. Do not delete volumes as part of rollback.

## Credential rotation

Back up first. Rotate upload tokens and Grafana credentials in the root-owned `.env`, recreate affected services, and test clients. PostgreSQL credentials stored in an existing database volume are not changed by editing `POSTGRES_PASSWORD`: use `ALTER ROLE`, update both `POSTGRES_PASSWORD` and the URL-encoded `DATABASE_URL`, then reload the stack. Rotate the Grafana reader with `ALTER ROLE`, update `GRAFANA_DB_PASSWORD`, and recreate Grafana. Keep `.env`, backups, Docker volumes, and generated data outside Git.
