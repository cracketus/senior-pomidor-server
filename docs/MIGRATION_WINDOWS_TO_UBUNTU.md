# Windows to Ubuntu migration

Keep Windows unchanged for at least seven days after cutover. Provision Ubuntu and the shared
PostgreSQL, Grafana, and Ollama services as described in [UBUNTU_HOST.md](UBUNTU_HOST.md). The
platform administrator creates `srv-platform`, the application database/role, and Grafana's reader
role before migration.

## Prepare the migration set

Stop edge writers and create a cold Windows set with `tools/backup_data.ps1`:

- `database.dump` from `pg_dump --format=custom --no-owner --no-acl`;
- `globals-audit.sql` without role password verifiers, for audit only;
- `photos.tar.gz`, `estimator-private.tar.gz`, and `mosquitto.tar.gz`;
- baseline counts, representative photo hashes, sanitized image/config inventory;
- `SHA256SUMS` for every other artifact.

Do not include `.env`, credentials, or shared filesystem state. Older archives may include
`grafana.tar.gz`; the restore script intentionally ignores it. Preserve all other legacy Windows
artifacts. Verify the checksums on Windows and again after transfer.

Local checksums detect corruption but do not prove off-host authenticity. Make a separately
encrypted off-host copy and keep its key outside `/srv/backups`.

## Transfer and cut over

Install the runtime secret separately as root-owned mode `0600`; never place it in the archive:

```bash
sudo install -o root -g root -m 0600 senior-pomidor.env \
  /srv/secrets/senior-pomidor/runtime.env
sudoedit /srv/secrets/senior-pomidor/runtime.env
```

Transfer the set beneath the migration root and lock it down:

```bash
sudo install -d -o root -g root -m 0700 \
  /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
sudo cp -a ./migration-YYYYMMDD-HHMMSS/. \
  /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS/
sudo chown -R root:root /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
sudo chmod -R go-rwx /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
```

Provisioning never moves temporary app-local secrets or backups. If an earlier draft used them,
follow the explicit copy-and-hash procedure in `UBUNTU_HOST.md`; leave originals untouched until
recovery is proven.

Before restore, confirm `/srv/apps/senior-pomidor/data/public/photos`,
`/srv/apps/senior-pomidor/data/private/mosquitto`, and
`/srv/logs/senior-pomidor/estimator-private` are empty. The target platform database must contain
no user tables. Then run:

```bash
sudo /srv/automation/scripts/senior-pomidor/restore-migration.sh \
  /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
sudo systemctl start senior-pomidor
```

Restore verifies checksums first, uses a pinned PostgreSQL 16 client on `srv-platform`, restores
only the logical dump and application-owned data, runs Alembic, and ignores legacy Grafana state.
It never starts, stops, or modifies platform PostgreSQL, Grafana, or Ollama containers.

## Validate and roll back

Compare database counts and photo checksums, exercise telemetry/photo ingestion and retrieval,
verify `/health` and `/ready`, inspect app worker health, and confirm platform Grafana dashboards.
Stop and upgrade Senior Pomidor once while independently confirming PostgreSQL, Grafana, and Ollama
remain available to other applications.

If acceptance fails, stop only `senior-pomidor.service`, return DNS/edge endpoints to Windows, and
restart Windows writers. Do not run `down -v` against either platform services or the retained
Windows installation. Reconcile any data accepted after the cutover boundary before retrying.
