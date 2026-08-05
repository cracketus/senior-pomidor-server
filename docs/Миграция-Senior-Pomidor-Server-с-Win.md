# Миграция Senior Pomidor Server с Windows на Ubuntu

> **Актуальная схема deployment.** PostgreSQL, Grafana и Ollama управляются платформой отдельно
> в `/srv/docker` и `/srv/data` и подключены к внешней сети `srv-platform`. Production Compose
> Senior Pomidor не создаёт, не останавливает и не удаляет эти сервисы. Секрет приложения хранится
> в `/srv/secrets/senior-pomidor/runtime.env` (`root:root`, `0600`), backup sets — в
> `/srv/backups/senior-pomidor/{daily,weekly,migration}`, private estimator logs — в
> `/srv/logs/senior-pomidor/estimator-private`, а временные release assets — в
> `/srv/apps/senior-pomidor/releases/.incoming`. Старые app-local каталоги `backups`, `secrets` и
> `logs` не используются и автоматически не перемещаются. При расхождении последующих старых
> примеров с этим блоком и `UBUNTU_HOST.md` следовать актуальной схеме.
>
> Перед restore checksum проверяется, вход разрешён только из migration root, app-owned target
> directories должны быть пустыми, а target database не должна содержать user tables. Legacy
> `grafana.tar.gz` игнорируется. Локальный SHA-256 выявляет повреждение, но не подтверждает
> подлинность off-host копии: требуется отдельный зашифрованный off-host backup, ключ которого
> хранится вне `/srv/backups`. Grafana reader создаёт platform administrator; его credential
> хранится в `/srv/secrets/grafana/senior-pomidor.env`.

## 1. Цель и исходные условия

Перенести production-инсталляцию `cracketus/senior-pomidor-server` со старой Windows-машины на новый Ubuntu-сервер с сохранением:

* PostgreSQL;
* фотографий;
* private JSONL и данных State Estimator;
* Grafana dashboards, alerts и datasource provisioning; filesystem state старой Grafana не переносится
  в новую platform-managed Grafana;
* данных Mosquitto;
* upload tokens;
* Grafana Cloud credentials;
* текущих API и MQTT-контрактов.

На Ubuntu уже выполнены:

* установка и обновление ОС;
* установка Docker Engine и Docker Compose plugin;
* создание пользователя `senior-pomidor`;
* настройка SSH;
* создание production-каталогов;
* установка systemd units и automation scripts;
* настройка сетевых сервисов и firewall.

Миграция выполняется как **cold cutover**: на короткое время прекращается приём данных от Raspberry Pi, создаётся финальный backup, данные восстанавливаются на Ubuntu, после чего edge nodes переключаются на новый IP.

Старую Windows-инсталляцию не удалять и не изменять не менее семи дней после миграции.

---

# 2. Как устроен production deployment

Production не запускается из Git checkout.

Git checkout в:

```text
/srv/git/senior-pomidor-server
```

используется только для администрирования и изучения кода. Compose, systemd, секреты и bind mounts не должны ссылаться на него.

Активный runtime находится по пути:

```text
/srv/apps/senior-pomidor/app
```

Это symlink на конкретную версию:

```text
/srv/apps/senior-pomidor/releases/vX.Y.Z
```

Приложение запускается из Docker image:

```text
ghcr.io/cracketus/senior-pomidor-server:vX.Y.Z
```

или из образа, закреплённого digest:

```text
ghcr.io/cracketus/senior-pomidor-server@sha256:...
```

Тег `latest` в production не используется.

Секреты находятся только в:

```text
/srv/secrets/senior-pomidor/runtime.env
```

---

# 3. Как собирается релиз

## 3.1 Триггер релиза

Release workflow запускается при push тега формата:

```text
vX.Y.Z
```

Например:

```text
v0.2.0
```

Тег обязан быть:

* SemVer-тегом;
* annotated tag, а не lightweight tag;
* привязанным к конкретному commit.

## 3.2 Проверки перед публикацией

GitHub Actions выполняет:

1. Проверку формата и типа тега.
2. Python tests.
3. Lint.
4. Format check.
5. Type checking.
6. Security checks.
7. Dependency audit.
8. Trivy scan файлов репозитория.
9. Trivy scan Docker image.

Публикация начинается только после прохождения всех блокирующих проверок.

## 3.3 Docker image

Workflow собирает multi-architecture image:

```text
linux/amd64
linux/arm64
```

Публикуются два неизменяемых идентификатора:

```text
ghcr.io/cracketus/senior-pomidor-server:vX.Y.Z
ghcr.io/cracketus/senior-pomidor-server:<commit-sha>
```

Workflow не перезаписывает существующий version tag образом из другого commit.

После публикации проверяется, что GHCR image доступен анонимно.

## 3.4 Runtime bundle

GitHub Actions создаёт:

```text
senior-pomidor-runtime-vX.Y.Z.tar.gz
senior-pomidor-runtime-vX.Y.Z.tar.gz.sha256
```

Bundle содержит:

```text
docker-compose.yml
docker-compose.prod.yml
mosquitto.conf
VERSION
senior-pomidor.env.example
config/daily_story/
deploy/apt/
deploy/systemd/
scripts/
```

Python source code в runtime bundle не включается. Код приложения находится внутри Docker image.
Development overlay `docker-compose.dev.yml` и platform provisioning из `docker/` в runtime bundle
не входят. Для rehearsal используется Git checkout того же release tag в
`/srv/git/senior-pomidor-server`; production по-прежнему запускается только из установленного
runtime bundle.

После сборки архив и checksum прикрепляются к GitHub Release.

---

# 4. Фаза A — подготовка релиза в репозитории

Все команды этого раздела выполняются на машине разработчика в Git checkout.

## Шаг A1. Обновить локальный `main`

```powershell
git switch main
git pull --ff-only origin main
git status
```

Ожидаемый результат:

```text
working tree clean
```

## Шаг A2. Запустить полный quality harness

```powershell
python -m pip install -e ".[dev]"
nox -s tests lint format_check types security deps_audit
```

Дополнительно рекомендуется проверить Docker Compose:

```powershell
Copy-Item .env.example .env
docker compose -f docker-compose.yml -f docker-compose.dev.yml config
```

При наличии возможности запустить Docker E2E:

```powershell
$env:RUN_DOCKER_E2E='1'
python -m pytest -q tests/test_docker_e2e.py
Remove-Item Env:RUN_DOCKER_E2E
```

## Шаг A3. Проверить текущую Alembic head revision

На текущей Windows production-машине:

Перед командами задать Windows production Compose context:

```powershell
$env:COMPOSE_FILE = 'docker-compose.yml;docker-compose.dev.yml'
$env:COMPOSE_PROFILES = 'observability,cloud-export'
```

Также задать immutable `APP_IMAGE` по инструкции в блоке «Контекст Docker Compose для Windows
production» Фазы B. Без overlay команда не увидит сервис `postgres`.

```powershell
docker compose exec -T postgres `
  psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB `
  -Atc "SELECT version_num FROM alembic_version"
```

Также проверить head из кода:

```powershell
docker compose run --rm migrate alembic heads
```

Значения должны соответствовать ожидаемой release revision.

На момент текущей документации runbook ожидает:

```text
0008_story_environment
```

Перед каждым новым релизом это значение необходимо сверять. Если migration head изменился, следует обновить:

```text
docs/MIGRATION_WINDOWS_TO_UBUNTU.md
deploy/scripts/restore-migration.sh
```

## Шаг A4. Обновить CHANGELOG

Добавить release section в:

```text
CHANGELOG.md
```

Включить:

* изменения приложения;
* изменения схемы БД;
* изменения deployment;
* известные ограничения;
* rollback compatibility;
* необходимость ручных действий.

## Шаг A5. Создать annotated release tag

Пример:

```powershell
git tag -a v0.2.0 -m "Senior Pomidor Server v0.2.0"
git show v0.2.0
```

Проверить, что tag указывает на нужный commit:

```powershell
git rev-list -n 1 v0.2.0
git rev-parse HEAD
```

SHA должны совпасть.

## Шаг A6. Отправить tag

```powershell
git push origin v0.2.0
```

Push тега запускает `.github/workflows/release.yml`.

## Шаг A7. Проверить GitHub Actions

Проверить успешное завершение jobs:

```text
validate-tag
test-quality-security
image-scans
publish
```

Не продолжать миграцию при skipped, cancelled или failed job.

## Шаг A8. Проверить GitHub Release

В release должны присутствовать:

```text
senior-pomidor-runtime-v0.2.0.tar.gz
senior-pomidor-runtime-v0.2.0.tar.gz.sha256
```

Проверить, что GHCR image доступен без авторизации:

```powershell
docker logout ghcr.io
docker pull ghcr.io/cracketus/senior-pomidor-server:v0.2.0
```

Зафиксировать digest:

```powershell
docker image inspect `
  ghcr.io/cracketus/senior-pomidor-server:v0.2.0 `
  --format '{{index .RepoDigests 0}}'
```

Сохранить:

```text
release version
release commit SHA
image tag
image digest
GitHub Actions run
release URL
```

---

# 5. Фаза B — предварительный baseline Windows

Все команды выполняются в production checkout на старой Windows-машине.

### Контекст Docker Compose для Windows production

В текущей схеме `docker-compose.yml` является application-only base-файлом. PostgreSQL и
Grafana находятся в локальном infrastructure overlay `docker-compose.dev.yml`. Поэтому на
Windows production нельзя использовать просто `docker compose`: в этом случае Compose не видит
сервис `postgres`, хотя ранее созданные контейнеры ещё могут отображаться в `docker compose ps`.

Перед первой Compose-командой в каждом новом PowerShell-сеансе задать контекст:

```powershell
$env:COMPOSE_FILE = 'docker-compose.yml;docker-compose.dev.yml'
$env:COMPOSE_PROFILES = 'observability,cloud-export'
```

`APP_IMAGE` обязателен даже для команды `ps`, потому что он используется в base-файле для
application services. Значение должно быть immutable image текущего Windows release, а не `latest`:

```powershell
$appImageLine = Get-Content -LiteralPath '.env' |
  Where-Object { $_ -match '^APP_IMAGE=' } |
  Select-Object -First 1

if (-not $appImageLine) {
    throw 'APP_IMAGE is missing from .env. Set the current immutable release image explicitly.'
}

$env:APP_IMAGE = ($appImageLine -split '=', 2)[1].Trim().Trim('"')

if ([string]::IsNullOrWhiteSpace($env:APP_IMAGE) -or
    $env:APP_IMAGE -match '(^|:)latest$') {
    throw "APP_IMAGE must reference an immutable release image: $env:APP_IMAGE"
}

$env:APP_IMAGE
```

Проверить выбранный Compose context:

```powershell
docker compose config --services
docker compose ps
```

В списке services должен присутствовать `postgres`. Если в новом PowerShell-сеансе контекст не
задан повторно, команды `docker compose ps -q postgres` и `tools\backup_data.ps1` могут завершиться
ошибкой `no such service: postgres`.

## Шаг B1. Зафиксировать состояние Git

```powershell
git status
git rev-parse HEAD
git describe --tags --always
```

Незакоммиченных production-изменений быть не должно.

Если они есть, их необходимо отдельно сохранить и проанализировать. Не включать `.env` в Git.

## Шаг B2. Сохранить inventory контейнеров

```powershell
docker compose ps
docker compose images
```

Не использовать:

```powershell
docker compose config
```

с выводом в публичный файл, если он раскрывает environment variables.

## Шаг B3. Зафиксировать health

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/ready
docker compose ps
```

Все неожиданные unhealthy states должны быть объяснены до переноса.

Особенно проверить:

```text
state-estimator-worker
worker
api
postgres
mosquitto
grafana
grafana-cloud-exporter
```

## Шаг B4. Зафиксировать Alembic revision

```powershell
docker compose exec -T postgres `
  psql -U <POSTGRES_USER> -d <POSTGRES_DB> `
  -Atc "SELECT version_num FROM alembic_version"
```

## Шаг B5. Зафиксировать размер БД

```powershell
docker compose exec -T postgres `
  psql -U <POSTGRES_USER> -d <POSTGRES_DB> `
  -c "SELECT pg_size_pretty(pg_database_size(current_database()));"
```

## Шаг B6. Зафиксировать counts

```sql
SELECT 'telemetry_events', count(*) FROM telemetry_events
UNION ALL SELECT 'pod_readings', count(*) FROM pod_readings
UNION ALL SELECT 'photos', count(*) FROM photos
UNION ALL SELECT 'state_snapshots', count(*) FROM state_snapshots
UNION ALL SELECT 'sensor_health_snapshots', count(*) FROM sensor_health_snapshots
UNION ALL SELECT 'anomaly_records', count(*) FROM anomaly_records
UNION ALL SELECT 'estimator_diagnostics', count(*) FROM estimator_diagnostics
ORDER BY 1;
```

## Шаг B7. Проверить свободное место

```powershell
Get-PSDrive -PSProvider FileSystem
docker system df
```

В backup location должно быть достаточно места для:

* database dump;
* фотографий;
* Mosquitto;
* estimator private data;
* минимум одной дополнительной копии migration set.

---

# 6. Фаза C — обязательная rehearsal migration

Rehearsal проводится до финального cutover.

Цель — проверить restore на Ubuntu без использования production bind mounts.

## Шаг C1. Создать предварительный Windows backup

Перед этим шагом в текущем PowerShell-сеансе должны быть заданы `COMPOSE_FILE`,
`COMPOSE_PROFILES` и `APP_IMAGE` из блока «Контекст Docker Compose для Windows production».

Остановить процессы, которые пишут в БД и файловые volumes, кроме PostgreSQL.

Например:

```powershell
docker compose stop api worker state-estimator-worker grafana grafana-cloud-exporter
```

Если используются другие file-writing services, остановить и их.

Создать migration set:

```powershell
.\tools\backup_data.ps1 `
  -Mode migration `
  -BackupRoot D:\senior-pomidor-backups `
  -ProjectName senior-pomidor-server
```

Снова запустить Windows stack:

```powershell
docker compose up -d
```

## Шаг C2. Проверить backup

Открыть созданный каталог:

```powershell
Get-ChildItem D:\senior-pomidor-backups\migration-*
```

Обязательные файлы:

```text
database.dump
globals-audit.sql
baseline-counts.csv
compose-services.jsonl
compose-images.jsonl
photos.tar.gz
estimator-private.tar.gz
mosquitto.tar.gz
representative-photo-sha256.txt
SHA256SUMS
```

Старый backup tool мог дополнительно создать `grafana.tar.gz`. В актуальной platform-managed схеме
этот файл не обязателен и при restore намеренно игнорируется.

Проверить SHA-256 в PowerShell:

```powershell
Get-Content .\SHA256SUMS
```

Можно повторно вычислить hashes:

```powershell
Get-ChildItem -File |
  Where-Object Name -ne 'SHA256SUMS' |
  Get-FileHash -Algorithm SHA256
```

## Шаг C3. Передать rehearsal set на Ubuntu

Передавать set через временный каталог. Пользователь `senior-pomidor` намеренно не имеет права
писать в root-owned backup root:

```powershell
scp -r `
  D:\senior-pomidor-backups\migration-YYYYMMDD-HHMMSS `
  senior-pomidor@<UBUNTU_IP>:/tmp/
```

Затем на Ubuntu:

```bash
set -euo pipefail
set_name=migration-YYYYMMDD-HHMMSS
source_dir="/tmp/$set_name"
target_dir="/srv/backups/senior-pomidor/migration/$set_name"

test -d "$source_dir"
if sudo test -e "$target_dir"; then
  echo "target already exists: $target_dir" >&2
  exit 1
fi
sudo install -d -o root -g root -m 0700 "$target_dir"
sudo cp -a "$source_dir/." "$target_dir/"
sudo find "$target_dir" -type d -exec chown root:root {} + -exec chmod 0700 {} +
sudo find "$target_dir" -type f -exec chown root:root {} + -exec chmod 0600 {} +
```

Исходную копию в `/tmp` не удалять до успешной проверки checksum целевой копии. После проверки её
можно удалить отдельной явной командой, предварительно ещё раз проверив точный путь.

## Шаг C4. Проверить checksums на Ubuntu

```bash
sudo bash -c '
  cd /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
  sha256sum --check SHA256SUMS
'
```

Каждая строка должна завершиться:

```text
OK
```

## Шаг C5. Выполнить rehearsal в изолированных каталогах

Все команды этого шага выполняются на Ubuntu. Rehearsal не должен использовать production paths,
`/srv/secrets/senior-pomidor/runtime.env`, external network `srv-platform` или platform PostgreSQL,
Grafana и Ollama.

Штатный `restore-migration.sh` предназначен только для production и здесь не запускается: он жёстко
использует production migration root, runtime secret, app symlink и platform network. Rehearsal
выполняется вручную через `docker-compose.dev.yml` из Git checkout. Приложение запускается из
опубликованного release image с `--no-build`.

### C5.1. Задать значения текущей проверки

Подставить фактические timestamp и release version:

```bash
set -euo pipefail
BACKUP=/srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
REHEARSAL=/srv/rehearsal/senior-pomidor
REPO=/srv/git/senior-pomidor-server
RELEASE_VERSION=v0.2.0
APP_IMAGE="ghcr.io/cracketus/senior-pomidor-server:$RELEASE_VERSION"

sudo test -d "$BACKUP"
sudo test -f "$BACKUP/database.dump"
sudo test -f "$BACKUP/SHA256SUMS"
```

После нового SSH-входа shell variables необходимо задать повторно.

### C5.2. Проверить rehearsal checkout

```bash
cd "$REPO"
git status --short
git describe --tags --always
git rev-parse HEAD
```

Checkout должен быть чистым и соответствовать `$RELEASE_VERSION`. При необходимости:

```bash
git fetch --tags origin
git switch --detach "$RELEASE_VERSION"
```

Проверить обязательные файлы:

```bash
test -f docker-compose.yml
test -f docker-compose.dev.yml
test -f docker/postgres/init-grafana-reader.sh
test -d docker/grafana/provisioning
```

### C5.3. Выбрать loopback-only порты

В примере используются API `18000`, MQTT `11883`, Grafana `13000` и PostgreSQL `15432`:

```bash
sudo ss -lntp | grep -E ':(18000|11883|13000|15432)\b' || true
```

Если есть вывод, выбрать другие порты. `LAN_BIND_ADDRESS` и `POSTGRES_BIND_ADDRESS` должны
оставаться `127.0.0.1`; не использовать LAN IP или `0.0.0.0`.

### C5.4. Создать пустые rehearsal-каталоги

```bash
sudo install -d -m 0750 "$REHEARSAL"
sudo install -d -m 0777 \
  "$REHEARSAL/postgres" \
  "$REHEARSAL/grafana" \
  "$REHEARSAL/mosquitto" \
  "$REHEARSAL/photos" \
  "$REHEARSAL/estimator-private"
```

Mode `0777` используется только для временных bind mounts с разными container UID. Проверить, что
data-каталоги пусты:

```bash
for target in postgres grafana mosquitto photos estimator-private; do
  test -z "$(sudo find "$REHEARSAL/$target" -mindepth 1 -maxdepth 1 -print -quit)" || {
    echo "rehearsal target is not empty: $REHEARSAL/$target" >&2
    exit 1
  }
done
```

Непустой каталог не очищать автоматически: использовать другой rehearsal root или предварительно
архивировать результаты предыдущей проверки.

### C5.5. Создать отдельный environment file

```bash
sudo install -o root -g root -m 0600 /dev/null "$REHEARSAL/rehearsal.env"
sudoedit "$REHEARSAL/rehearsal.env"
```

Пример содержимого:

```dotenv
APP_IMAGE=ghcr.io/cracketus/senior-pomidor-server:v0.2.0

LAN_BIND_ADDRESS=127.0.0.1
API_PUBLISHED_PORT=18000
MQTT_PUBLISHED_PORT=11883
GRAFANA_PUBLISHED_PORT=13000
POSTGRES_BIND_ADDRESS=127.0.0.1
POSTGRES_PUBLISHED_PORT=15432

POSTGRES_DB=senior_pomidor
POSTGRES_USER=senior_pomidor
POSTGRES_PASSWORD=CHANGE_ME_REHEARSAL_DB_PASSWORD
DATABASE_URL=postgresql+psycopg://senior_pomidor:CHANGE_ME_REHEARSAL_DB_PASSWORD@postgres:5432/senior_pomidor

POSTGRES_DATA_DIR=/srv/rehearsal/senior-pomidor/postgres
GRAFANA_DATA_DIR=/srv/rehearsal/senior-pomidor/grafana
MOSQUITTO_DATA_DIR=/srv/rehearsal/senior-pomidor/mosquitto
PHOTO_DATA_DIR=/srv/rehearsal/senior-pomidor/photos
ESTIMATOR_PRIVATE_DATA_DIR=/srv/rehearsal/senior-pomidor/estimator-private

GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=CHANGE_ME_REHEARSAL_GRAFANA_PASSWORD
GRAFANA_DB_USER=grafana_reader
GRAFANA_DB_PASSWORD=CHANGE_ME_REHEARSAL_READER_PASSWORD

API_DOCS_ENABLED=false
PHOTO_UPLOAD_TOKEN=REHEARSAL_PHOTO_TOKEN
TELEMETRY_UPLOAD_TOKEN=REHEARSAL_TELEMETRY_TOKEN

MQTT_HOST=mosquitto
MQTT_PORT=1883
MQTT_TOPIC_PREFIX=senior-pomidor
MQTT_USERNAME=
MQTT_PASSWORD=

GRAFANA_CLOUD_EXPORT_ENABLED=false
STATE_ESTIMATOR_ENABLED=true
STATE_ESTIMATOR_TIMEZONE=Europe/Vienna
```

Использовать отдельные rehearsal credentials, не production secrets. Для простого URL-compatible
пароля можно использовать вывод `openssl rand -hex 24`. Проверить права:

```bash
sudo stat -c '%U:%G %a %n' "$REHEARSAL/rehearsal.env"
```

Ожидается `root:root 600`.

### C5.6. Подготовить и проверить Compose

```bash
cd "$REPO"
compose=(
  sudo docker compose
  -p senior-pomidor-rehearsal
  --env-file "$REHEARSAL/rehearsal.env"
  -f docker-compose.yml
  -f docker-compose.dev.yml
)

"${compose[@]}" --profile observability config --quiet
sudo docker pull "$APP_IMAGE"
sudo docker image inspect "$APP_IMAGE" --format '{{index .RepoDigests 0}}'
```

Сравнить digest с шагом A8. Project name всегда задаётся через `-p senior-pomidor-rehearsal`.

### C5.7. Запустить только rehearsal PostgreSQL

```bash
"${compose[@]}" up -d postgres

until "${compose[@]}" exec -T postgres \
  pg_isready -U senior_pomidor -d senior_pomidor; do
  sleep 2
done

"${compose[@]}" ps
"${compose[@]}" port postgres 5432
```

Адрес должен быть `127.0.0.1:15432` или другой выбранный loopback-порт, а контейнер должен
относиться к project `senior-pomidor-rehearsal`.

### C5.8. Восстановить database dump

```bash
PG_ID="$("${compose[@]}" ps -q postgres)"
test -n "$PG_ID"
sudo docker cp "$BACKUP/database.dump" "$PG_ID:/tmp/database.dump"

"${compose[@]}" exec -T postgres \
  pg_restore --exit-on-error --no-owner --no-acl \
  -U senior_pomidor -d senior_pomidor /tmp/database.dump
```

`globals-audit.sql` не выполнять: он предназначен только для аудита.

### C5.9. Восстановить application-owned files

```bash
sudo tar --numeric-owner -C "$REHEARSAL/photos" \
  -xzf "$BACKUP/photos.tar.gz"
sudo tar --numeric-owner -C "$REHEARSAL/estimator-private" \
  -xzf "$BACKUP/estimator-private.tar.gz"
sudo tar --numeric-owner -C "$REHEARSAL/mosquitto" \
  -xzf "$BACKUP/mosquitto.tar.gz"

sudo find "$REHEARSAL/photos" -type f | head
sudo find "$REHEARSAL/estimator-private" -type f | head
sudo find "$REHEARSAL/mosquitto" -type f | head
```

Legacy `grafana.tar.gz` не распаковывать. Актуальная Grafana является platform-managed; rehearsal
проверяет provisioning datasource, dashboards и alerts на чистом Grafana data directory.

### C5.10. Выполнить Alembic migration и Grafana grants

```bash
cd "$REPO"
"${compose[@]}" run --rm migrate
"${compose[@]}" exec -T postgres \
  psql -U senior_pomidor -d senior_pomidor \
  -Atc 'SELECT version_num FROM alembic_version'
```

Revision должна соответствовать release head; сейчас ожидается `0008_story_environment`.
Повторно применить grants после появления восстановленных таблиц:

```bash
"${compose[@]}" exec -T postgres \
  sh /docker-entrypoint-initdb.d/20-grafana-reader.sh
```

### C5.11. Сравнить baseline counts до запуска writers

Не выполнять все `count(*)` одним `UNION ALL`: до завершения всех scan PostgreSQL не покажет ни
одной строки. Не направлять `docker compose exec` непосредственно в `tee`: открытый stdin Compose
может удерживать pipeline. Выполнять counts по одному через non-interactive `docker exec`:

```bash
PG_ID="$("${compose[@]}" ps -q postgres)"
test -n "$PG_ID"

tables=(
  anomaly_records
  estimator_diagnostics
  photos
  pod_readings
  sensor_health_snapshots
  state_snapshots
  telemetry_events
)

counts_file=/tmp/rehearsal-counts.csv
: > "$counts_file"

for table in "${tables[@]}"; do
  echo "Counting $table..." >&2
  count="$(
    sudo timeout 1810s docker exec \
      -e PGOPTIONS='-c statement_timeout=1800000 -c lock_timeout=30000' \
      "$PG_ID" \
      psql --no-psqlrc --no-password \
      -U senior_pomidor -d senior_pomidor \
      --set=ON_ERROR_STOP=1 --tuples-only --no-align \
      -c "SELECT count(*) FROM \"$table\";"
  )" || {
    echo "Failed while counting $table" >&2
    exit 1
  }
  printf '%s,%s\n' "$table" "$count" | tee -a "$counts_file"
done
```

Некоторые старые Windows migration sets не содержат запятую из-за передачи PowerShell-аргумента
`--field-separator=,`. В актуальном `backup_data.ps1` separator передаётся отдельным quoted
аргументом `--field-separator ','`; новые sets должны содержать запятую. Старый checksummed backup
не изменять. Нормализовать только временные копии и сортировать обе стороны:

```bash
sudo cat "$BACKUP/baseline-counts.csv" \
  | tr -d '\r' \
  | sed '1s/^\xEF\xBB\xBF//' \
  | sed -E 's/^([a-z_]+)([0-9]+)$/\1,\2/' \
  | LC_ALL=C sort \
  > /tmp/baseline-counts-normalized.csv

tr -d '\r' < "$counts_file" \
  | LC_ALL=C sort \
  > /tmp/rehearsal-counts-normalized.csv

diff -u \
  /tmp/baseline-counts-normalized.csv \
  /tmp/rehearsal-counts-normalized.csv
```

Нормальный результат — `diff` ничего не выводит и `echo $?` возвращает `0`. При несовпадении
counts остановиться.

### C5.12. Запустить application services

```bash
"${compose[@]}" --profile observability up -d --no-build \
  api worker grafana
"${compose[@]}" --profile observability ps
```

Profile `cloud-export` не включён, а `grafana-cloud-exporter` не должен запускаться.
State Estimator пока также не запускается, чтобы он не изменил counts до завершения baseline
comparison.

## Шаг C6. Проверить rehearsal

### C6.1. Проверить API, контейнеры и логи

```bash
curl -fsS http://127.0.0.1:18000/health
curl -fsS http://127.0.0.1:18000/ready
"${compose[@]}" --profile observability ps
"${compose[@]}" ps -a grafana-cloud-exporter
```

При ошибке:

```bash
"${compose[@]}" logs --tail=200 \
  postgres migrate mosquitto api worker state-estimator-worker grafana
```

Не должно быть restart loops, `permission denied`, ошибок подключения к production или
необъяснимых unhealthy states.

### C6.2. Проверить representative photo SHA-256

Windows manifest содержит пути от `/data`; заменить только этот префикс:

```bash
sudo sed 's#  /data/#  #' "$BACKUP/representative-photo-sha256.txt" |
sudo sh -c 'cd "$1" && sha256sum --check -' sh "$REHEARSAL/photos"
```

Каждая строка должна завершаться `OK`.

### C6.3. Получить восстановленное фото через API

```bash
curl -fsS 'http://127.0.0.1:18000/api/v1/photos/recent?limit=5'
PHOTO_ID='<photo_id из ответа>'
curl -fS "http://127.0.0.1:18000/api/v1/photos/$PHOTO_ID" \
  -o /tmp/rehearsal-photo.jpg
file /tmp/rehearsal-photo.jpg
sha256sum /tmp/rehearsal-photo.jpg
```

### C6.4. Проверить Grafana provisioning

```bash
curl -fsS http://127.0.0.1:13000/api/health
```

Grafana работает от непривилегированного UID, обычно `472`. Сначала проверить mount и доступ к
provisioning files:

```bash
GRAFANA_ID="$("${compose[@]}" ps -q grafana)"
test -n "$GRAFANA_ID"

sudo docker inspect \
  --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}' \
  "$GRAFANA_ID"

sudo docker exec --user 0 "$GRAFANA_ID" \
  find /etc/grafana/provisioning -maxdepth 4 -type f -print

sudo docker exec "$GRAFANA_ID" \
  find /etc/grafana/provisioning -maxdepth 4 -type f -print
```

Обе команды `find` должны показать datasource, dashboard provider, dashboard JSON и alert rules.
Если root видит файлы, а последняя команда возвращает `Permission denied`, выдать container UID
минимальные ACL на checkout:

```bash
GRAFANA_UID="$(sudo docker exec --user 0 "$GRAFANA_ID" id -u grafana)"

sudo setfacl -m "u:$GRAFANA_UID:--x" \
  /srv /srv/git "$REPO" "$REPO/docker" "$REPO/docker/grafana"
sudo setfacl -R -m "u:$GRAFANA_UID:rX" \
  "$REPO/docker/grafana/provisioning"

"${compose[@]}" up -d --no-build --force-recreate grafana
```

Не использовать `chmod -R 777`. Если `setfacl` отсутствует, установить пакет `acl` штатным
пакетным менеджером либо отдельно согласовать read/execute permissions на checkout.

С рабочей машины открыть tunnel:

```powershell
ssh -L 13000:127.0.0.1:13000 senior-pomidor@<UBUNTU_IP>
```

В `http://127.0.0.1:13000` открыть `Dashboards -> Browse -> Senior Pomidor` и проверить datasource
`Senior Pomidor PostgreSQL`, единственный provisioned dashboard `Senior Pomidor Telemetry`, panels
без datasource errors и alert rules. Прямой dashboard UID: `senior-pomidor-telemetry`.

### C6.5. Проверить MQTT ingestion

```bash
TEST_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

"${compose[@]}" exec -T mosquitto mosquitto_pub \
  -h 127.0.0.1 \
  -t senior-pomidor/rehearsal-pi/telemetry \
  -m "{\"schema_version\":\"senior-pomidor.edge.telemetry.v1\",\"device_id\":\"rehearsal-pi\",\"timestamp_utc\":\"$TEST_TS\",\"pods\":[{\"pod_key\":\"pod-1\",\"soil_moisture_percent\":42.5,\"soil_temperature_c\":20.0,\"air_temperature_c\":24.0,\"air_humidity_percent\":60.0}]}"

"${compose[@]}" logs --tail=100 worker

sudo docker exec "$PG_ID" \
  psql --no-psqlrc --no-password \
  -U senior_pomidor -d senior_pomidor \
  -c "SELECT device_id, received_at FROM telemetry_events
      WHERE device_id = 'rehearsal-pi'
      ORDER BY received_at DESC LIMIT 5;"
```

Worker должен записать `Accepted MQTT telemetry`, а новая строка должна появиться в БД.

### C6.6. Проверить State Estimator

Убедиться, что в `$REHEARSAL/rehearsal.env` установлено:

```dotenv
STATE_ESTIMATOR_ENABLED=true
```

```bash
"${compose[@]}" up -d --no-build --force-recreate state-estimator-worker
```

Worker выполняет первый цикл сразу, затем ждёт `600` секунд. Поэтому сначала повторить MQTT publish
из C6.5 с новым `TEST_TS`, затем перезапустить worker для немедленной обработки и проверить health
file. Пустой обычный log без ошибок сам по себе допустим:

```bash
"${compose[@]}" restart state-estimator-worker
"${compose[@]}" exec -T state-estimator-worker \
  cat /tmp/senior-pomidor-state-estimator-health.json </dev/null

sudo docker exec "$PG_ID" \
  psql --no-psqlrc --no-password \
  -U senior_pomidor -d senior_pomidor \
  -c "SELECT node_id, ts, state_id, generated_at FROM state_snapshots
      WHERE node_id = 'rehearsal-pi'
      ORDER BY ts DESC LIMIT 5;"

sudo find "$REHEARSAL/estimator-private" -type f -mmin -10 -ls
```

В health JSON ожидается `state_estimator_healthy`. Должны появиться новый state snapshot и свежая
private JSONL запись. Timestamp column называется `ts`, не `state_ts`.

### C6.7. Сохранить результаты и остановить rehearsal

Не писать evidence напрямую в root-owned `$REHEARSAL`: `tee` завершится с `Permission denied`, а
при `set -o pipefail` успешная проверка ошибочно получит общий status `FAIL`. Сначала создать
user-owned рабочий каталог в `/tmp`:

```bash
EVIDENCE_TS="$(date -u +%Y%m%d-%H%M%S)"
EVIDENCE_DIR="/tmp/senior-pomidor-evidence-$EVIDENCE_TS"
install -d -m 0750 "$EVIDENCE_DIR"
printf 'write_test=OK\n' | tee "$EVIDENCE_DIR/write-test.txt"
```

Если SSH-сессия прервалась, повторно запускать rehearsal не нужно. Найти рабочий каталог и
восстановить variables:

```bash
find /tmp -maxdepth 1 -type d -name 'senior-pomidor-evidence-*' \
  -printf '%TY-%Tm-%Td %TH:%TM:%TS %p\n' | sort

EVIDENCE_DIR=/tmp/senior-pomidor-evidence-YYYYMMDD-HHMMSS
test -d "$EVIDENCE_DIR"
evidence_name="$(basename "$EVIDENCE_DIR")"
EVIDENCE_TS="${evidence_name#senior-pomidor-evidence-}"
```

Сохранить metadata без secrets:

```bash
IMAGE_DIGEST="$(sudo docker image inspect "$APP_IMAGE" \
  --format '{{index .RepoDigests 0}}')"

{
  printf 'captured_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'release_version=%s\n' "$RELEASE_VERSION"
  printf 'app_image=%s\n' "$APP_IMAGE"
  printf 'image_digest=%s\n' "$IMAGE_DIGEST"
  printf 'backup_directory=%s\n' "$BACKUP"
  printf 'git_revision=%s\n' "$(git -C "$REPO" rev-parse HEAD)"
} | tee "$EVIDENCE_DIR/metadata.txt"
```

Сохранить checksum status. Из-за `pipefail` ошибка записи evidence также считается ошибкой, поэтому
write test выше обязателен:

```bash
set -o pipefail
if sudo sh -c 'cd "$1" && sha256sum --check SHA256SUMS' \
  sh "$BACKUP" 2>&1 | tee "$EVIDENCE_DIR/backup-checksums.txt"; then
  echo 'checksum_status=PASS' | tee "$EVIDENCE_DIR/checksum-status.txt"
else
  echo 'checksum_status=FAIL' | tee "$EVIDENCE_DIR/checksum-status.txt"
  exit 1
fi
```

Сохранить Alembic revision без Compose pipeline:

```bash
ALEMBIC_REVISION="$(
  sudo timeout 15s docker exec \
    -e PGOPTIONS='-c statement_timeout=10000 -c lock_timeout=5000' \
    "$PG_ID" \
    psql --no-psqlrc --no-password \
    -U senior_pomidor -d senior_pomidor \
    -Atc 'SELECT version_num FROM alembic_version'
)"
printf '%s\n' "$ALEMBIC_REVISION" \
  | tee "$EVIDENCE_DIR/alembic-revision.txt"
```

Скопировать результаты counts и сохранить service state/logs:

```bash
cp /tmp/baseline-counts-normalized.csv \
  /tmp/rehearsal-counts-normalized.csv \
  "$EVIDENCE_DIR/"

if diff -u \
  "$EVIDENCE_DIR/baseline-counts-normalized.csv" \
  "$EVIDENCE_DIR/rehearsal-counts-normalized.csv" \
  > "$EVIDENCE_DIR/baseline-counts.diff"; then
  printf 'baseline_counts_status=PASS\n' \
    | tee "$EVIDENCE_DIR/baseline-counts-status.txt"
else
  printf 'baseline_counts_status=FAIL\n' \
    | tee "$EVIDENCE_DIR/baseline-counts-status.txt"
  cat "$EVIDENCE_DIR/baseline-counts.diff"
  exit 1
fi

"${compose[@]}" --profile observability ps -a </dev/null \
  > "$EVIDENCE_DIR/compose-ps.txt"
"${compose[@]}" logs --no-color --no-log-prefix --tail=500 \
  postgres migrate mosquitto api worker state-estimator-worker grafana \
  </dev/null > "$EVIDENCE_DIR/services.log" 2>&1
```

Evidence можно собирать повторно с места остановки. Проверить обязательные файлы и создавать заново
только отмеченные `MISSING`:

```bash
required_files=(
  metadata.txt
  backup-checksums.txt
  checksum-status.txt
  alembic-revision.txt
  baseline-counts-normalized.csv
  rehearsal-counts-normalized.csv
  baseline-counts-status.txt
  compose-ps.txt
  services.log
)

for file in "${required_files[@]}"; do
  if test -s "$EVIDENCE_DIR/$file"; then
    printf 'PRESENT %s\n' "$file"
  else
    printf 'MISSING %s\n' "$file"
  fi
done
```

`baseline-counts.diff` при успешном сравнении имеет размер `0`, поэтому его нельзя проверять через
`test -s`; нулевой размер вместе с `baseline_counts_status=PASS` является ожидаемым результатом.

Создать `$EVIDENCE_DIR/rehearsal-report.md` в редакторе и явно записать `PASS`/`FAIL` для checksum,
Alembic, baseline counts, photo hashes, API `/health` и `/ready`, Grafana datasource/dashboard/
alerts, MQTT ingestion, State Estimator snapshot/private JSONL и unhealthy containers. Для каждой
ошибки записать symptom, cause, resolution и retest result. Не включать passwords, tokens, полный
environment file или чувствительные логи.

Как минимум отдельно отразить, если они встретились: несовпадение `POSTGRES_PASSWORD` и password в
`DATABASE_URL`, отсутствующий CSV delimiter в Windows baseline, отклонённый сокращённый telemetry
schema, ошибочное имя `state_ts` вместо `ts`, отсутствие Grafana access к provisioning bind mount,
зависание Compose pipeline с открытым stdin и невозможность писать evidence в root-owned path.

После заполнения отчёта создать manifest самого evidence и проверить его до копирования:

```bash
(
  cd "$EVIDENCE_DIR"
  find . -type f ! -name EVIDENCE_SHA256SUMS -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum \
    > EVIDENCE_SHA256SUMS
  sha256sum --check EVIDENCE_SHA256SUMS
)
```

После заполнения отчёта перенести evidence в root-owned storage. Команды выполнять отдельно, не
объединять в незакрытый `if` block:

```bash
FINAL_EVIDENCE="$REHEARSAL/evidence/$EVIDENCE_TS"
sudo test ! -e "$FINAL_EVIDENCE" || {
  echo "target already exists: $FINAL_EVIDENCE" >&2
  false
}

sudo install -d -o root -g root -m 0700 "$FINAL_EVIDENCE"
sudo cp -a "$EVIDENCE_DIR/." "$FINAL_EVIDENCE/"

sudo find "$FINAL_EVIDENCE" -type d \
  -exec chown root:root {} + -exec chmod 0700 {} +
sudo find "$FINAL_EVIDENCE" -type f \
  -exec chown root:root {} + -exec chmod 0600 {} +
```

Проверить число файлов и права, затем остановить rehearsal:

```bash
find "$EVIDENCE_DIR" -type f | wc -l
sudo find "$FINAL_EVIDENCE" -type f | wc -l
sudo find "$FINAL_EVIDENCE" -maxdepth 2 -printf '%M %u:%g %p\n'

sudo sh -c 'cd "$1" && sha256sum --check EVIDENCE_SHA256SUMS' \
  sh "$FINAL_EVIDENCE"

"${compose[@]}" --profile observability down --remove-orphans
```

Количество файлов должно совпасть, а каждая строка final evidence checksum verification должна
завершиться `OK`. Только после этого останавливать rehearsal. Rehearsal data directories и
root-owned evidence сохранить как минимум до успешного production cutover. Не выполнять `down` без
project name. Cutover нельзя начинать, пока все проверки C6 не завершены успешно.

---

# 7. Фаза D — установка production release на Ubuntu

Эта фаза выполняется на Ubuntu до остановки Windows. Она устанавливает release assets, но не
запускает production application services и не должна принимать edge traffic.

## Шаг D0. Проверить gates перед production preparation

Продолжать только если rehearsal report имеет итог `PASS`, image digest совпал с A8, а unresolved
blockers отсутствуют. Проверить, что production service не активен:

```bash
if systemctl is-active --quiet senior-pomidor; then
  echo 'senior-pomidor is unexpectedly active' >&2
  exit 1
fi
systemctl is-enabled senior-pomidor 2>/dev/null || true
```

`enabled` допустим, `active` до restore — нет. Зафиксировать точные release version, image digest и
путь к успешному rehearsal evidence.

### D0.1. Проверить shared platform

PostgreSQL, Grafana и Ollama являются отдельным platform stack и не создаются Senior Pomidor
Compose. Внешняя сеть сама по себе недостаточна: в ней должны находиться запущенные production
containers. Rehearsal network `senior-pomidor-rehearsal_default` не заменяет `srv-platform`.

Если сеть ещё не создана, создать её один раз:

```bash
if ! sudo docker network inspect srv-platform >/dev/null 2>&1; then
  sudo docker network create --driver bridge srv-platform
fi
```

Platform Compose должен использовать явное имя внешней сети:

```yaml
services:
  postgres:
    networks:
      srv-platform:
        aliases: [postgres]
  grafana:
    networks: [srv-platform]
  ollama:
    networks:
      srv-platform:
        aliases: [ollama]

networks:
  srv-platform:
    external: true
    name: srv-platform
```

Не публиковать PostgreSQL и Ollama через `ports`. Persistent mounts должны указывать на
`/srv/data/postgres`, `/srv/data/grafana` и `/srv/data/ollama`. Для Grafana data directory
необходим владелец UID/GID `472`, так как контейнер Grafana работает непривилегированным:

```bash
sudo chown -R 472:472 /srv/data/grafana
sudo chmod 0750 /srv/data/grafana
```

Grafana provisioning копировать в platform-owned каталог, например:

```bash
sudo install -d -o root -g root -m 0755 \
  /srv/docker/platform/grafana/provisioning
sudo cp -a \
  /srv/git/senior-pomidor-server/docker/grafana/provisioning/. \
  /srv/docker/platform/grafana/provisioning/
```

После запуска platform stack проверить именно running containers:

```bash
sudo docker network inspect srv-platform \
  --format '{{range .Containers}}{{println .Name}}{{end}}'
```

Должны присутствовать production PostgreSQL и Grafana. Если Grafana отсутствует, проверить также
остановленные containers и её логи, поскольку `docker network inspect` не показывает остановленный
container:

```bash
sudo docker ps -a --filter name=srv-platform-grafana
sudo docker logs --tail=200 srv-platform-grafana
```

Не продолжать D5, пока PostgreSQL не доступен в сети под DNS-именем `postgres`, а Grafana не
запущена без ошибок прав на `/var/lib/grafana`.

До запуска `provision-host.sh` проверить наличие host UID/GID `1883`, который используется для
application-owned Mosquitto data directory:

```bash
getent passwd 1883 || true
getent group 1883 || true
```

Если UID и GID свободны, создать системные записи:

```bash
sudo groupadd --system --gid 1883 senior-pomidor-mosquitto
sudo useradd --system --uid 1883 --gid 1883 \
  --no-create-home --shell /usr/sbin/nologin senior-pomidor-mosquitto
```

Если UID или GID уже заняты другой записью, не создавать дубликат и остановить preparation до
проверки конфликта.

## Шаг D1. Скачать release assets

Поместить файлы в:

```text
/srv/apps/senior-pomidor/releases/.incoming
```

Например, через браузер и `scp`, GitHub CLI или `curl` с release URL.

Служебные host-скрипты не запускаются непосредственно из Git checkout
`/srv/git/senior-pomidor-server`. В production они устанавливаются из распакованного runtime
bundle командой `provision-host.sh` в `/srv/automation/scripts/senior-pomidor`. Git checkout
используется только для администрирования и rehearsal.

Если host provisioning ещё не выполнялся, распаковать именно runtime bundle (не Git checkout) и
запустить скрипт через `bash`; executable bit внутри исходного checkout может отсутствовать:

```bash
sudo install -d -m 0755 /tmp/senior-pomidor-runtime-v0.2.0
sudo tar -xzf \
  /srv/apps/senior-pomidor/releases/.incoming/senior-pomidor-runtime-v0.2.0.tar.gz \
  -C /tmp/senior-pomidor-runtime-v0.2.0
sudo bash /tmp/senior-pomidor-runtime-v0.2.0/scripts/provision-host.sh
```

После этого проверить:

```bash
sudo ls -l /srv/automation/scripts/senior-pomidor/install-release.sh
```

Практический вариант — сначала скачать файлы на рабочую машину, затем передать во временный
каталог Ubuntu:

```powershell
scp senior-pomidor-runtime-v0.2.0.tar.gz `
  senior-pomidor-runtime-v0.2.0.tar.gz.sha256 `
  senior-pomidor@<UBUNTU_IP>:/tmp/
```

На Ubuntu установить их в root-owned incoming directory:

```bash
sudo install -o root -g root -m 0644 \
  /tmp/senior-pomidor-runtime-v0.2.0.tar.gz \
  /srv/apps/senior-pomidor/releases/.incoming/senior-pomidor-runtime-v0.2.0.tar.gz
sudo install -o root -g root -m 0644 \
  /tmp/senior-pomidor-runtime-v0.2.0.tar.gz.sha256 \
  /srv/apps/senior-pomidor/releases/.incoming/senior-pomidor-runtime-v0.2.0.tar.gz.sha256
```

Получиться должны:

```text
/srv/apps/senior-pomidor/releases/.incoming/
  senior-pomidor-runtime-v0.2.0.tar.gz
  senior-pomidor-runtime-v0.2.0.tar.gz.sha256
```

## Шаг D2. Проверить checksum

```bash
sudo bash -c '
  cd /srv/apps/senior-pomidor/releases/.incoming
  sha256sum --check senior-pomidor-runtime-v0.2.0.tar.gz.sha256
'
```

Ожидается одна строка с `OK`. Не продолжать при `FAILED`, отсутствии файла или несовпадении имени в
checksum manifest.

## Шаг D3. Настроить production environment

Открыть:

```bash
sudoedit /srv/secrets/senior-pomidor/runtime.env
```

Проверить как минимум:

```dotenv
APP_IMAGE=ghcr.io/cracketus/senior-pomidor-server:v0.2.0

POSTGRES_USER=<new-production-user>
POSTGRES_PASSWORD=<new-strong-password>
POSTGRES_DB=<production-database>
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
DATABASE_URL=postgresql+psycopg://<new-production-user>:<same-password>@postgres:5432/<production-database>
PLATFORM_DOCKER_NETWORK=srv-platform

TELEMETRY_UPLOAD_TOKEN=<existing-token>
PHOTO_UPLOAD_TOKEN=<existing-token>

API_DOCS_ENABLED=false
COMPOSE_PROFILES=cloud-export
GRAFANA_CLOUD_EXPORT_ENABLED=true
GRAFANA_CLOUD_REMOTE_WRITE_URL=<existing-value>
GRAFANA_CLOUD_INSTANCE_ID=<existing-value>
GRAFANA_CLOUD_API_TOKEN=<existing-value>
```

`POSTGRES_PASSWORD` и password component в `DATABASE_URL` должны описывать один credential. Чтобы
не ошибиться в URL encoding, предпочтителен сильный hex password из `openssl rand -hex 32`. Если
используются reserved URL characters (`@`, `:`, `/`, `%`, `#`, `?`), password в `DATABASE_URL`
необходимо percent-encode, сохранив raw value в `POSTGRES_PASSWORD`.

При `GRAFANA_CLOUD_EXPORT_ENABLED=true` три `GRAFANA_CLOUD_*` значения также обязательны и
переносятся из старого production environment или из защищённого хранилища. Не публиковать их и
не выводить runtime environment целиком.

Не добавлять profile:

```text
daily-story
```

пока platform administrator не provisioned требуемую модель в shared Ollama.

Проверить права:

```bash
sudo chown root:root /srv/secrets/senior-pomidor/runtime.env
sudo chmod 0600 /srv/secrets/senior-pomidor/runtime.env
sudo stat -c '%U:%G %a %n' /srv/secrets/senior-pomidor/runtime.env
```

Ожидается `root:root 600`. Не выполнять `cat`, `grep` или `docker compose config` с выводом этого
файла в журнал или публичный terminal transcript.

## Шаг D4. Установить release

Перед запуском проверить, что активный путь не является обычным каталогом. Installer переключает
`/srv/apps/senior-pomidor/app` атомарно через временный symlink; существующий каталог на этом пути
приведёт к ошибке `cannot overwrite directory ... with non-directory`.

Проверить состояние:

```bash
sudo ls -ld \
  /srv/apps/senior-pomidor/app \
  /srv/apps/senior-pomidor/.app-new \
  /srv/apps/senior-pomidor/releases
sudo find /srv/apps/senior-pomidor/app -mindepth 1 -maxdepth 1 -print 2>/dev/null
```

Если `app` — пустой каталог, его можно удалить только как пустой каталог:

```bash
sudo rmdir /srv/apps/senior-pomidor/app
```

Если `app` не пустой, не удалять его: выяснить, что именно там находится, и остановить миграцию.
После неудачного переключения installer может оставить `.app-new`; если он является symlink на
текущий release и `app` пуст, завершить переключение можно так:

```bash
sudo mv -T \
  /srv/apps/senior-pomidor/.app-new \
  /srv/apps/senior-pomidor/app
```

В этом случае installer повторно не запускать: release уже скопирован и повторный запуск завершится
ошибкой о существующем каталоге версии.

```bash
sudo /srv/automation/scripts/senior-pomidor/install-release.sh \
  /srv/apps/senior-pomidor/releases/.incoming/senior-pomidor-runtime-v0.2.0.tar.gz \
  /srv/apps/senior-pomidor/releases/.incoming/senior-pomidor-runtime-v0.2.0.tar.gz.sha256
```

Installer:

* проверит SHA-256;
* проверит `VERSION`;
* отклонит bundle с Python source;
* создаст release directory;
* проверит соответствие `APP_IMAGE`;
* выполнит `docker pull`;
* проверит Compose config;
* атомарно переключит symlink `app`;
* переместит предыдущий release в archive.

## Шаг D5. Проверить установленный release

```bash
readlink -f /srv/apps/senior-pomidor/app
cat /srv/apps/senior-pomidor/app/VERSION
sudo docker compose \
  -p senior-pomidor \
  --env-file /srv/secrets/senior-pomidor/runtime.env \
  -f /srv/apps/senior-pomidor/app/docker-compose.yml \
  -f /srv/apps/senior-pomidor/app/docker-compose.prod.yml \
  config --quiet
```

Ожидается:

```text
/srv/apps/senior-pomidor/releases/v0.2.0
v0.2.0
```

Проверить согласованность `DATABASE_URL` с отдельными PostgreSQL settings без вывода credentials:

```bash
sudo docker run --rm \
  --env-file /srv/secrets/senior-pomidor/runtime.env \
  --entrypoint python \
  ghcr.io/cracketus/senior-pomidor-server:v0.2.0 \
  -c '
import os
from urllib.parse import unquote, urlsplit

url = urlsplit(os.environ["DATABASE_URL"])
checks = {
    "user": unquote(url.username or "") == os.environ["POSTGRES_USER"],
    "password": unquote(url.password or "") == os.environ["POSTGRES_PASSWORD"],
    "host": (url.hostname or "") == os.environ.get("POSTGRES_HOST", "postgres"),
    "port": (url.port or 5432) == int(os.environ.get("POSTGRES_PORT", "5432")),
    "database": url.path.lstrip("/") == os.environ["POSTGRES_DB"],
}
print(" ".join(f"{key}={value}" for key, value in checks.items()))
raise SystemExit(0 if all(checks.values()) else 1)
'
```

Все пять значений должны быть `True`. Если `APP_IMAGE` закреплён digest, использовать в команде тот
же digest вместо tag.

Проверить network credential против уже provisioned пустой platform database:

```bash
sudo docker run --rm --network srv-platform \
  --env-file /srv/secrets/senior-pomidor/runtime.env \
  postgres:16-alpine \
  sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql --no-password \
    -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -Atc "SELECT current_database(), current_user"'
```

Не продолжать при authentication failure. Успешный локальный `psql` внутри PostgreSQL container не
заменяет эту network-проверку. Production stack пока не запускать.

---

# 8. Фаза E — финальный cold cutover

Все Windows-команды E2–E6 выполняются с Compose-контекстом из Фазы B. Если открыт новый
PowerShell-сеанс, перед продолжением повторно задать:

```powershell
$env:COMPOSE_FILE = 'docker-compose.yml;docker-compose.dev.yml'
$env:COMPOSE_PROFILES = 'observability,cloud-export'
```

Также повторно проверить `APP_IMAGE` по инструкции Фазы B. Без этого Compose может либо не увидеть
`postgres`, либо завершиться ошибкой `APP_IMAGE must reference an immutable release image`.

## Шаг E1. Объявить окно недоступности

На время migration остановятся:

* MQTT ingestion;
* HTTP telemetry ingestion;
* photo upload;
* dashboard/API;
* State Estimator;
* Grafana export.

Зафиксировать planned cutover start UTC и ответственного за решение rollback/continue. С этого
момента не менять release, runtime environment или database roles без записи в migration report.

## Шаг E2. Остановить все Raspberry Pi edge nodes

Остановить отправку:

* MQTT telemetry;
* HTTP telemetry;
* photo uploads.

Проверить на Windows, что counts больше не меняются. Выполнить query B6 дважды с интервалом не менее
двух минут, сохранить оба результата и сравнить:

```powershell
$CutoverEvidence = 'D:\senior-pomidor-backups\cutover-evidence'
New-Item -ItemType Directory -Force $CutoverEvidence | Out-Null

$postgresId = (docker compose ps -q postgres).Trim()
if (-not $postgresId) { throw 'PostgreSQL container is not running.' }
$postgresUser = (docker exec $postgresId printenv POSTGRES_USER).Trim()
$postgresDb = (docker exec $postgresId printenv POSTGRES_DB).Trim()

$countSql = @"
SELECT 'telemetry_events', count(*) FROM telemetry_events
UNION ALL SELECT 'pod_readings', count(*) FROM pod_readings
UNION ALL SELECT 'photos', count(*) FROM photos
UNION ALL SELECT 'state_snapshots', count(*) FROM state_snapshots
UNION ALL SELECT 'sensor_health_snapshots', count(*) FROM sensor_health_snapshots
UNION ALL SELECT 'anomaly_records', count(*) FROM anomaly_records
UNION ALL SELECT 'estimator_diagnostics', count(*) FROM estimator_diagnostics
ORDER BY 1;
"@

docker exec $postgresId psql `
  --username $postgresUser --dbname $postgresDb `
  --csv --tuples-only --command $countSql `
  | Set-Content -Encoding ascii "$CutoverEvidence\counts-1.csv"

Start-Sleep -Seconds 120

docker exec $postgresId psql `
  --username $postgresUser --dbname $postgresDb `
  --csv --tuples-only --command $countSql `
  | Set-Content -Encoding ascii "$CutoverEvidence\counts-2.csv"

Compare-Object `
  (Get-Content "$CutoverEvidence\counts-1.csv") `
  (Get-Content "$CutoverEvidence\counts-2.csv")
```

`Compare-Object` не должен вывести различий. Если counts растут, найти неостановленный edge node
или другой writer; финальный backup пока не создавать.

## Шаг E3. Остановить Windows writers

Оставить только PostgreSQL:

```powershell
docker compose stop `
  api `
  worker `
  state-estimator-worker `
  grafana `
  grafana-cloud-exporter `
  mosquitto
```

Если присутствуют `daily-story-worker` или другие процессы записи, остановить их также. Mosquitto
останавливается после edge nodes, чтобы persistence archive снимался без параллельной записи.

Проверить:

```powershell
docker compose ps
```

PostgreSQL должен быть единственным running service этого Compose project. Не выполнять здесь
полную команду `docker compose stop` без списка сервисов: backup script использует работающий
PostgreSQL для `pg_dump`, counts и globals audit.

Проверить перед переходом к E4:

```powershell
$postgresId = (docker compose ps -q postgres).Trim()
if (-not $postgresId) {
    throw 'PostgreSQL must remain running until the migration backup is complete.'
}

docker inspect $postgresId --format '{{.State.Status}} {{.State.Health.Status}}'
```

Ожидается `running healthy` или `running` для конфигураций без healthcheck.

## Шаг E4. Создать финальный migration set

PostgreSQL должен оставаться запущенным на всём протяжении этого шага. Не останавливать его до
получения строки `Wrote migration backup set: ...` и сохранения точного пути финального set.

```powershell
.\tools\backup_data.ps1 `
  -Mode migration `
  -BackupRoot D:\senior-pomidor-backups `
  -ProjectName senior-pomidor-server
```

Сохранить полный путь, напечатанный script. Не выбирать set по принципу «самый новый» на следующих
шагах: далее везде использовать явно записанный timestamp финального set.

## Шаг E5. Остановить оставшиеся Windows services

После успешного backup:

```powershell
docker compose stop
```

Эта команда выполняется только после завершения E4. Она останавливает также PostgreSQL, потому
что database dump уже создан. До E4 останавливать весь Compose project нельзя.

Не выполнять:

```powershell
docker compose down
docker compose down -v
```

`docker compose down` удаляет containers и Compose network. `docker compose down -v` дополнительно
удаляет volumes проекта, где могут находиться PostgreSQL, photos, estimator private data, Mosquitto
или другие runtime data. Эти команды не удаляют `.env`, images или рабочий каталог, но удаление
containers и volumes ломает предусмотренный rollback и может привести к потере данных. Для cold
cutover разрешён только `docker compose stop`.

Не удалять:

* containers;
* volumes;
* images;
* working directory;
* `.env`.

## Шаг E6. Проверить финальный backup

Открыть точный каталог нового set и проверить:

```powershell
$FinalBackup = 'D:\senior-pomidor-backups\migration-YYYYMMDD-HHMMSS'
Get-ChildItem -LiteralPath $FinalBackup
Get-Content -LiteralPath (Join-Path $FinalBackup 'baseline-counts.csv')
Get-Content -LiteralPath (Join-Path $FinalBackup 'representative-photo-sha256.txt')

Push-Location $FinalBackup
$expected = @{}
Get-Content -LiteralPath '.\SHA256SUMS' | ForEach-Object {
    if ($_ -notmatch '^([0-9a-fA-F]{64})  (.+)$') {
        throw "Invalid SHA256SUMS line: $_"
    }
    $expected[$Matches[2]] = $Matches[1].ToLowerInvariant()
}

$actualFiles = Get-ChildItem -File | Where-Object Name -ne 'SHA256SUMS'
foreach ($file in $actualFiles) {
    if (-not $expected.ContainsKey($file.Name)) {
        throw "File missing from SHA256SUMS: $($file.Name)"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
    if ($actual -ne $expected[$file.Name]) {
        throw "Checksum mismatch: $($file.Name)"
    }
    "OK $($file.Name)"
}
if ($actualFiles.Count -ne $expected.Count) {
    throw 'SHA256SUMS contains a missing or unexpected file.'
}
Pop-Location
```

Строки нового `baseline-counts.csv` должны иметь формат `table,count`. Если set создан старой
версией backup script и delimiter отсутствует, не редактировать checksummed set; отметить это в
evidence и применять нормализацию из C5.11 при сравнении.

Сопоставить вычисленные hashes со строками в `SHA256SUMS`. Проверить:

* список файлов;
* размеры;
* baseline counts;
* representative photo hashes;
* `SHA256SUMS`.

Этот backup является authoritative migration set.

Записать cold cutover boundary:

```powershell
@(
  "cutover_backup=$FinalBackup"
  "created_at_utc=$((Get-Date).ToUniversalTime().ToString('o'))"
  "windows_writers_stopped=true"
) | Set-Content -Encoding ascii "$CutoverEvidence\authoritative-set.txt"
```

## Шаг E7. Передать финальный backup на Ubuntu

```powershell
scp -r `
  D:\senior-pomidor-backups\migration-YYYYMMDD-HHMMSS `
  senior-pomidor@<UBUNTU_IP>:/tmp/
```

На Ubuntu:

```bash
set -euo pipefail
set_name=migration-YYYYMMDD-HHMMSS
source_dir="/tmp/$set_name"
target_dir="/srv/backups/senior-pomidor/migration/$set_name"

test -d "$source_dir"
if sudo test -e "$target_dir"; then
  echo "target already exists: $target_dir" >&2
  exit 1
fi
sudo install -d -o root -g root -m 0700 "$target_dir"
sudo cp -a "$source_dir/." "$target_dir/"
sudo find "$target_dir" -type d -exec chown root:root {} + -exec chmod 0700 {} +
sudo find "$target_dir" -type f -exec chown root:root {} + -exec chmod 0600 {} +
```

Не удалять staging copy до успешной проверки checksum целевой копии.

## Шаг E8. Проверить checksums на Ubuntu

```bash
sudo bash -c '
  cd /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
  sha256sum --check SHA256SUMS
'
```

Не продолжать при любой ошибке.

После успешной проверки записать точный Ubuntu path в migration report. Rehearsal set и final set
должны иметь разные timestamps; restore выполняется только из final authoritative set.

---

# 9. Фаза F — восстановление на Ubuntu

## Шаг F0. Зафиксировать restore target и остановленное состояние

```bash
set -euo pipefail
FINAL_BACKUP=/srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
RESTORE_EVIDENCE=/tmp/senior-pomidor-restore-$(date -u +%Y%m%d-%H%M%S)
install -d -m 0750 "$RESTORE_EVIDENCE"

sudo systemctl stop senior-pomidor 2>/dev/null || true
if systemctl is-active --quiet senior-pomidor; then
  echo 'senior-pomidor must be inactive before restore' >&2
  exit 1
fi

sudo test -d "$FINAL_BACKUP"
sudo test -f "$FINAL_BACKUP/database.dump"
sudo test -f "$FINAL_BACKUP/SHA256SUMS"
```

Ещё раз сверить `$FINAL_BACKUP` с authoritative path из E6. Ошибка выбора rehearsal set на этом
этапе является основанием остановиться.

## Шаг F1. Убедиться, что production data directories пусты

Проверить:

```bash
sudo find /srv/apps/senior-pomidor/data/private/mosquitto -mindepth 1 -maxdepth 1
sudo find /srv/apps/senior-pomidor/data/public/photos -mindepth 1 -maxdepth 1
sudo find /srv/logs/senior-pomidor/estimator-private -mindepth 1 -maxdepth 1
```

Команды не должны вывести файлов.

Не очищать непустой каталог автоматически. Сначала определить источник данных.

Также проверить, что целевая database не содержит user tables. Команда только читает состояние:

```bash
sudo docker run --rm --network srv-platform \
  --env-file /srv/secrets/senior-pomidor/runtime.env \
  postgres:16-alpine \
  sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
    "SELECT count(*) FROM pg_tables
     WHERE schemaname NOT IN ('\''pg_catalog'\'', '\''information_schema'\'')"'
```

Ожидается `0`. Если результат больше нуля, restore не запускать и не удалять таблицы автоматически:
проверить, правильные ли `POSTGRES_HOST`, `POSTGRES_DB` и целевая platform instance указаны в
runtime environment.

Зафиксировать preflight, не раскрывая credentials:

```bash
{
  printf 'checked_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'final_backup=%s\n' "$FINAL_BACKUP"
  printf 'service_inactive=true\n'
  printf 'target_directories_empty=true\n'
  printf 'target_user_tables=0\n'
} > "$RESTORE_EVIDENCE/preflight.txt"
```

## Шаг F2. Выполнить restore

```bash
set -o pipefail
if sudo /srv/automation/scripts/senior-pomidor/restore-migration.sh \
  "$FINAL_BACKUP" 2>&1 | tee "$RESTORE_EVIDENCE/restore.log"; then
  restore_status=0
else
  restore_status=${PIPESTATUS[0]}
fi
printf 'restore_exit_code=%s\n' "$restore_status" \
  | tee "$RESTORE_EVIDENCE/restore-status.txt"
test "$restore_status" -eq 0
```

Если restore завершился с ошибкой, не запускать его повторно автоматически: после частичного
restore database или target directories уже могут быть непустыми. Сохранить log, определить точку
отказа и согласовать очистку/retry либо повторное provision пустой target database.

Script:

1. Проверит `SHA256SUMS`.

2. Проверит, что production directories пусты.

3. Подключится к уже работающему platform PostgreSQL через pinned client container.

4. Дождётся readiness PostgreSQL.

5. Восстановит `database.dump` с:

   ```text
   --no-owner
   --no-acl
   ```

6. Восстановит:

   ```text
   photos.tar.gz
   estimator-private.tar.gz
   mosquitto.tar.gz
   ```

   Legacy `grafana.tar.gz` будет проигнорирован.

7. Запустит Alembic migrate.

8. Не изменит platform Grafana и его readonly role/grants.

9. Проверит ожидаемую Alembic revision.

Restore script использует `pg_restore` через stdin Docker-контейнера и поэтому запускает client
container с `docker run -i`. Без `-i` Docker закрывает stdin, `pg_restore` получает пустой поток и
завершается ошибкой `input file is too short`, даже если `database.dump` имеет корректный размер и
проходит `pg_restore --list`.

## Шаг F3. Не восстанавливать старые DB roles

Файл:

```text
globals-audit.sql
```

предназначен только для аудита.

Не выполнять его против новой БД.

На Ubuntu должны использоваться новые PostgreSQL passwords и роли из:

```text
/srv/secrets/senior-pomidor/runtime.env
```

## Шаг F4. Проверить platform boundaries и Grafana grants

Restore не должен останавливать, пересоздавать или изменять filesystem state shared PostgreSQL,
Grafana и Ollama. Platform administrator должен подтвердить, что эти services остались available.

Проверить наличие Grafana reader и SELECT grants без вывода его password:

```bash
sudo docker run --rm --network srv-platform \
  --env-file /srv/secrets/senior-pomidor/runtime.env \
  postgres:16-alpine \
  sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql --no-password \
    -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "
SELECT rolname FROM pg_roles WHERE rolname = '\''grafana_reader'\'';
SELECT has_table_privilege('\''grafana_reader'\'', '\''public.telemetry_events'\'', '\''SELECT'\'');
SELECT has_table_privilege('\''grafana_reader'\'', '\''public.photos'\'', '\''SELECT'\'');"'
```

Ожидаются role `grafana_reader` и два значения `t`. Если platform использует другое имя reader
role, platform administrator выполняет эквивалентную проверку. Не запускать legacy
`globals-audit.sql` и не восстанавливать `grafana.tar.gz`.

Если результатом является:

```text
ERROR: role "grafana_reader" does not exist
```

остановиться на F4. Это означает, что platform onboarding не завершён. Не создавать роль через
обычный application `POSTGRES_USER`, не использовать пароль из старого Windows `.env` и не
запускать restore повторно. Platform administrator должен создать readonly role и grants на
shared PostgreSQL с помощью утверждённой platform onboarding procedure или
`docker/postgres/init-grafana-reader.sh`, используя отдельный credential из
`/srv/secrets/grafana/senior-pomidor.env`. После этого повторить F4. До успешного F4 не запускать
`senior-pomidor.service`.

Onboarding script должен подключаться к PostgreSQL по Docker network, а не к локальному Unix
socket. Для client container требуются `PGHOST=postgres`, `PGPORT=5432` и `PGPASSWORD`; script
преобразует `POSTGRES_PASSWORD` в `PGPASSWORD`. Platform admin credential передаётся через
отдельный platform env file; application runtime secret не является platform admin credential.

Роль PostgreSQL cluster-wide, а grants привязаны к конкретной database. Если роль уже существует,
но `has_table_privilege` возвращает `f` или таблица отсутствует, сравнить `POSTGRES_DB` в platform
env и в `/srv/secrets/senior-pomidor/runtime.env`. Grants должны применяться к target database из
runtime secret, обычно `senior_pomidor`. Platform administrator может явно переопределить database:

```bash
sudo docker run --rm \
  --network srv-platform \
  -e PGHOST=postgres \
  -e PGPORT=5432 \
  -e POSTGRES_DB=senior_pomidor \
  --env-file /srv/secrets/platform/postgres.env \
  --env-file /srv/secrets/grafana/senior-pomidor.env \
  --mount type=bind,src=/srv/git/senior-pomidor-server/docker/postgres/init-grafana-reader.sh,dst=/init-grafana-reader.sh,readonly \
  postgres:16-alpine \
  sh /init-grafana-reader.sh
```

Не печатать значения passwords. После onboarding проверять grants через application runtime
secret и target database; ожидаются два значения `t`.

---

# 10. Фаза G — запуск Ubuntu production

Первые три шага этой фазы выполняются при остановленном `senior-pomidor.service`. Это последняя
точка, где восстановленные данные можно сравнить с authoritative baseline до запуска background
writers.

## Шаг G1. Подготовить pre-start verification

G1 и G2 выполняются в одной SSH-сессии: `FINAL_BACKUP`, `START_EVIDENCE` и функция
`production_psql` являются shell state и не сохраняются после выхода из SSH. Если открыта новая
сессия, выполнить весь блок G1 заново. Migration root принадлежит `root:root` и имеет закрытые
права, поэтому проверки `$FINAL_BACKUP` выполнять через `sudo`. Не использовать обычный `test -d`
для этого каталога вместе с `set -e`: отказ доступа завершит SSH-shell.

```bash
set -euo pipefail
FINAL_BACKUP=/srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
START_EVIDENCE=/tmp/senior-pomidor-start-$(date -u +%Y%m%d-%H%M%S)
install -d -m 0750 "$START_EVIDENCE"

if systemctl is-active --quiet senior-pomidor; then
  echo 'stop senior-pomidor before baseline verification' >&2
  exit 1
fi

production_psql() {
  sudo timeout 1810s docker run --rm --network srv-platform \
    --env-file /srv/secrets/senior-pomidor/runtime.env \
    postgres:16-alpine \
    sh -c '
      export PGPASSWORD="$POSTGRES_PASSWORD"
      export PGOPTIONS="-c statement_timeout=1800000 -c lock_timeout=30000"
      exec psql --no-password --no-psqlrc \
        -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
        -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
    ' sh "$@"
}
```

Function передаёт SQL arguments без раскрытия password и не использует интерактивный Compose
stdin.

## Шаг G2. Проверить Alembic и точные counts до старта

```bash
ALEMBIC_REVISION="$(production_psql -Atc \
  'SELECT version_num FROM alembic_version')"
printf '%s\n' "$ALEMBIC_REVISION" \
  | tee "$START_EVIDENCE/alembic-revision.txt"
test "$ALEMBIC_REVISION" = '0008_story_environment'
```

Считать таблицы по одной, чтобы видеть progress:

```bash
tables=(
  anomaly_records
  estimator_diagnostics
  photos
  pod_readings
  sensor_health_snapshots
  state_snapshots
  telemetry_events
)

PRODUCTION_COUNTS="$START_EVIDENCE/production-counts-before-start.csv"
: > "$PRODUCTION_COUNTS"

for table in "${tables[@]}"; do
  echo "Counting $table..." >&2
  count="$(production_psql --set=ON_ERROR_STOP=1 --tuples-only --no-align \
    -c "SELECT count(*) FROM \"$table\";")" || {
      echo "Failed while counting $table" >&2
      exit 1
    }
  printf '%s,%s\n' "$table" "$count" | tee -a "$PRODUCTION_COUNTS"
done
```

Нормализовать старый или новый Windows CSV, не изменяя final backup:

```bash
sudo cat "$FINAL_BACKUP/baseline-counts.csv" \
  | tr -d '\r' \
  | sed '1s/^\xEF\xBB\xBF//' \
  | sed -E 's/^([a-z_]+)([0-9]+)$/\1,\2/' \
  | LC_ALL=C sort \
  > "$START_EVIDENCE/final-baseline-normalized.csv"

tr -d '\r' < "$PRODUCTION_COUNTS" \
  | LC_ALL=C sort \
  > "$START_EVIDENCE/production-counts-normalized.csv"

if diff -u \
  "$START_EVIDENCE/final-baseline-normalized.csv" \
  "$START_EVIDENCE/production-counts-normalized.csv" \
  > "$START_EVIDENCE/counts.diff"; then
  echo 'pre_start_counts=PASS' | tee "$START_EVIDENCE/counts-status.txt"
else
  echo 'pre_start_counts=FAIL' | tee "$START_EVIDENCE/counts-status.txt"
  cat "$START_EVIDENCE/counts.diff"
  exit 1
fi
```

Только exact `PASS` разрешает запуск service. Нулевой `counts.diff` — ожидаемый результат.

## Шаг G3. Проверить restored files до старта

```bash
set -o pipefail
if sudo sed 's#  /data/#  #' \
  "$FINAL_BACKUP/representative-photo-sha256.txt" \
  | sudo sh -c \
    'cd /srv/apps/senior-pomidor/data/public/photos && sha256sum --check -' \
  2>&1 | tee "$START_EVIDENCE/photo-checksums.txt"; then
  echo 'photo_hashes=PASS' | tee "$START_EVIDENCE/photo-status.txt"
else
  echo 'photo_hashes=FAIL' | tee "$START_EVIDENCE/photo-status.txt"
  exit 1
fi

sudo find /srv/logs/senior-pomidor/estimator-private -type f -print \
  | sed -n '1,20p' | tee "$START_EVIDENCE/estimator-files.txt"
sudo find /srv/apps/senior-pomidor/data/private/mosquitto -type f -print \
  | tee "$START_EVIDENCE/mosquitto-files.txt"
```

## Шаг G4. Запустить systemd service

```bash
sudo systemctl start senior-pomidor
systemctl status senior-pomidor --no-pager
journalctl -u senior-pomidor -n 200 --no-pager \
  | tee "$START_EVIDENCE/systemd-journal.txt"
```

При failed start не выполнять ручной `docker compose up`: сначала изучить systemd journal и
сохранить единый owner процесса запуска.

## Шаг G5. Проверить application containers

```bash
cd /srv/apps/senior-pomidor/app
prod_compose=(
  sudo docker compose
  -p senior-pomidor
  --env-file /srv/secrets/senior-pomidor/runtime.env
  -f docker-compose.yml
  -f docker-compose.prod.yml
)

"${prod_compose[@]}" ps -a </dev/null \
  | tee "$START_EVIDENCE/compose-ps.txt"
```

Ожидается:

* `migrate` — `Exited (0)`;
* `api`, `worker`, `state-estimator-worker`, `mosquitto` — running/healthy;
* `grafana-cloud-exporter` — running, если profile `cloud-export` включён;
* `daily-story-worker` отсутствует, пока модель не provisioned;
* PostgreSQL, Grafana и Ollama не являются services этого Compose project.

## Шаг G6. Проверить API и восстановленное фото

```bash
curl -fsS http://127.0.0.1:8000/health \
  | tee "$START_EVIDENCE/api-health.json"
curl -fsS http://127.0.0.1:8000/ready \
  | tee "$START_EVIDENCE/api-ready.json"

curl -fsS http://<NEW_SERVER_LAN_IP>:8000/health >/dev/null
curl -fsS http://<NEW_SERVER_LAN_IP>:8000/ready >/dev/null
```

Получить metadata существующего фото:

```bash
curl -fsS 'http://127.0.0.1:8000/api/v1/photos/recent?limit=5' \
  | tee "$START_EVIDENCE/recent-photos.json"
PHOTO_ID='<photo_id из ответа>'
curl -fS "http://127.0.0.1:8000/api/v1/photos/$PHOTO_ID" \
  -o "$START_EVIDENCE/restored-photo.bin"
file "$START_EVIDENCE/restored-photo.bin"
sha256sum "$START_EVIDENCE/restored-photo.bin"
```

## Шаг G7. Проверить platform Grafana

Grafana не является application Compose service. Проверку выполняет platform administrator:

* Grafana health и вход;
* datasource UID `senior-pomidor-postgres`;
* dashboard UID `senior-pomidor-telemetry`;
* folder `Senior Pomidor`;
* dashboard panels без datasource errors;
* provisioned alert rules;
* reader может выполнять SELECT и не может INSERT/UPDATE/DELETE.

Filesystem archive `grafana.tar.gz` в этой проверке не участвует.

Проверить, что readonly role имеет доступ ко всем таблицам, которые используются dashboard и alert
queries, включая `action_simulations` и `pod_errors`:

```bash
sudo docker run --rm \
  --network srv-platform \
  --env-file /srv/secrets/senior-pomidor/runtime.env \
  postgres:16-alpine \
  sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "
SELECT has_table_privilege('\''grafana_reader'\'', '\''public.action_simulations'\'', '\''SELECT'\'');
SELECT has_table_privilege('\''grafana_reader'\'', '\''public.pod_errors'\'', '\''SELECT'\'');"'
```

Ожидаются два значения `t`. Если dashboard или alert query получает `permission denied`, сначала
повторно применить platform onboarding grants к target database `senior_pomidor`; Grafana не должна
получать application write privileges.

Проверить alert provisioning:

```bash
sudo docker exec "$GRAFANA_CONTAINER" \
  find /etc/grafana/provisioning/alerting -maxdepth 1 -type f -print
```

В каталоге должны находиться только рабочие provisioning-файлы с расширением `.yml`, `.yaml` или
`.json`. Backup-файлы, например `*.before-delete-rules-test`, хранить вне provisioning directory:
Grafana пытается обработать каждый файл каталога и пишет `file has invalid suffix`.

Текущий `senior-pomidor-alerts.yml` должен содержать `groups`, но не должен одновременно содержать
`deleteRules` для тех же UID: в platform Grafana это приводило к пустому набору rules после
provisioning. После изменения файла перезапустить только platform Grafana и проверить:

```bash
sudo docker restart "$GRAFANA_CONTAINER"
sleep 10
sudo docker logs "$GRAFANA_CONTAINER" --since 2m \
  | grep -Ei 'provisioning.alerting|invalid suffix|permission denied|db query error'
```

Ожидаются `starting to provision alerting` и `finished to provision alerting`, без `invalid suffix`,
`permission denied` и `db query error`. В Web UI rules находятся в folder `Senior Pomidor Alerts`.
Browser WebSocket `user token not found` после устаревшей сессии не является Grafana datasource или
provisioning failure; выполнить logout/login или `Ctrl+F5`.

## Шаг G8. Проверить Grafana Cloud exporter

```bash
"${prod_compose[@]}" logs --tail=200 grafana-cloud-exporter \
  </dev/null | tee "$START_EVIDENCE/grafana-cloud-exporter.log"
```

Не должно быть authorization, remote-write или repeated retry errors. До свежей telemetry
допустимо отсутствие новых samples, но не бесконечный retry loop.

## Шаг G9. Проверить State Estimator без изменения baseline criteria

```bash
"${prod_compose[@]}" exec -T state-estimator-worker \
  cat /tmp/senior-pomidor-state-estimator-health.json </dev/null \
  | tee "$START_EVIDENCE/estimator-health.json"
"${prod_compose[@]}" logs --tail=200 state-estimator-worker </dev/null \
  | tee "$START_EVIDENCE/state-estimator.log"
```

Ожидается `status=state_estimator_healthy`. Пустой вывод `state-estimator.log` допустим,
если health-файл корректен и контейнер не перезапускается: worker может не писать новые строки
между циклами обработки.

Отдельно проверить Docker healthcheck контейнера:

```bash
"${prod_compose[@]}" ps -a state-estimator-worker
sudo docker inspect -f \
  'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} restarts={{.RestartCount}}' \
  senior-pomidor-state-estimator-worker-1
```

Если внутренний health-файл healthy, но Docker показывает `unhealthy`, выполнить ровно ту же
проверку вручную:

```bash
"${prod_compose[@]}" exec -T state-estimator-worker \
  python -m app.worker_healthcheck state_estimator_healthy </dev/null
printf 'exit_code=%s\n' "$?"
```

Ожидается `exit_code=0`. После этого подождать не менее одного интервала healthcheck и повторить
проверку статуса контейнера:

```bash
sleep 35
sudo docker inspect -f \
  'status={{.State.Status}} health={{.State.Health.Status}} failing={{.State.Health.FailingStreak}}' \
  senior-pomidor-state-estimator-worker-1
```

G9 считается пройденным при `status=running`, `health=healthy`, `restarts=0`, корректном
health-файле и ручном `exit_code=0`. Ненулевой `failing` допустим только как остаток предыдущего
healthcheck-сбоя, если текущий статус уже `healthy`; повторяющиеся ошибки или текущий
`unhealthy` требуют остановить gate и расследовать причину.

После старта estimator может создать app-generated rows из уже восстановленной telemetry. Это не
делает pre-start baseline invalid: authoritative exact comparison уже сохранён в G2. До свежей
telemetry от canary отсутствие нового snapshot может быть ожидаемым.

## Шаг G10. Зафиксировать pre-edge gate

До переключения Raspberry Pi должны быть `PASS`:

* Alembic revision;
* pre-start exact counts;
* representative photo hashes;
* systemd/container health;
* API health/ready и photo retrieval;
* platform Grafana datasource/dashboard/alerts;
* отсутствие необъяснимых exporter/worker errors.

Записать в `$START_EVIDENCE/pre-edge-gate.txt` UTC timestamp, `PASS`/`FAIL` каждого пункта и решение
`edge_canary_authorized=yes|no`. При `no` перейти к rollback до поступления данных на Ubuntu.

---

# 11. Фаза H — переключение Raspberry Pi

Edge nodes переключаются по одному. Первый node является canary. До его успешного полного цикла
остальные nodes остаются остановленными и настроенными на Windows.

## Шаг H0. Подготовить canary evidence и rollback boundary

На Ubuntu:

```bash
CANARY_STARTED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
CANARY_EVIDENCE=/tmp/senior-pomidor-canary-$(date -u +%Y%m%d-%H%M%S)
install -d -m 0750 "$CANARY_EVIDENCE"

printf 'canary_started_utc=%s\n' "$CANARY_STARTED_UTC" \
  > "$CANARY_EVIDENCE/boundary.txt"
```

Если после G10 открыта новая SSH-сессия, повторно определить `production_psql` из G1 и
`prod_compose` из G5; shell functions и arrays между сессиями не сохраняются. Проверить перед
продолжением:

```bash
declare -F production_psql >/dev/null || {
  echo 'redefine production_psql from G1' >&2
  false
}
declare -p prod_compose >/dev/null 2>&1 || {
  echo 'redefine prod_compose from G5' >&2
  false
}
```

Записать canary device ID, последний Windows event timestamp/count и выбранное telemetry/photo
cycle duration. До первой принятой Ubuntu записи rollback остаётся простым. После неё возникает
data divergence boundary, и rollback требует reconciliation по разделу 14.

## Шаг H1. Изменить адрес сервера на одном edge node

Обновить:

```dotenv
MQTT_HOST=<NEW_SERVER_LAN_IP>
MQTT_PORT=1883

CORE_HTTP_URL=http://<NEW_SERVER_LAN_IP>:8000/api/v1/edge/telemetry

PHOTO_UPLOAD_URL=http://<NEW_SERVER_LAN_IP>:8000/api/v1/edge/photos
```

Сохранить существующие:

```dotenv
TELEMETRY_UPLOAD_TOKEN
PHOTO_UPLOAD_TOKEN
MQTT_TOPIC_PREFIX
device/node identifiers
```

Не генерировать новые upload tokens и не менять topic prefix/device ID во время смены адреса. Перед
запуском проверить конфигурацию node штатной командой проекта без печати token values.

## Шаг H2. Запустить только один node

Запустить только canary Raspberry Pi. Остальные nodes должны оставаться остановленными.

В отдельной Ubuntu SSH-сессии наблюдать application logs:

```bash
cd /srv/apps/senior-pomidor/app
sudo docker compose -p senior-pomidor \
  --env-file /srv/secrets/senior-pomidor/runtime.env \
  -f docker-compose.yml -f docker-compose.prod.yml \
  logs -f --since=2m worker api state-estimator-worker
```

После одного полного telemetry/photo cycle завершить follow через `Ctrl+C`; контейнеры продолжат
работать.

Зафиксировать первую принятую canary telemetry в БД:

```bash
CANARY_DEVICE_ID='<точный device_id>'

production_psql -c "
SELECT id, device_id, timestamp_utc, source, received_at
FROM telemetry_events
WHERE device_id = '$CANARY_DEVICE_ID'
  AND received_at >= '$CANARY_STARTED_UTC'::timestamptz
ORDER BY received_at DESC
LIMIT 10;" | tee "$CANARY_EVIDENCE/telemetry-events.txt"
```

После появления первой строки дописать её UTC timestamp в `boundary.txt`. Это момент перехода от
простого rollback к reconciliation rollback.

Проверить pod key и значения:

```bash
production_psql -c "
SELECT device_id, pod_key, soil_moisture_percent,
       soil_temperature_c, air_temperature_c, air_humidity_percent
FROM pod_readings
WHERE device_id = '$CANARY_DEVICE_ID'
ORDER BY id DESC
LIMIT 10;" | tee "$CANARY_EVIDENCE/pod-readings.txt"
```

Проверить фотографию, созданную после начала canary:

```bash
curl -fsS \
  "http://127.0.0.1:8000/api/v1/devices/$CANARY_DEVICE_ID/photos?limit=10" \
  | tee "$CANARY_EVIDENCE/canary-photos.json"

CANARY_PHOTO_ID='<photo_id после CANARY_STARTED_UTC>'
curl -fS "http://127.0.0.1:8000/api/v1/photos/$CANARY_PHOTO_ID" \
  -o "$CANARY_EVIDENCE/canary-photo.bin"
file "$CANARY_EVIDENCE/canary-photo.bin"
sha256sum "$CANARY_EVIDENCE/canary-photo.bin"
```

State Estimator cadence равен 600 seconds. Дождаться следующего штатного цикла, не перезапуская
production worker только ради теста:

```bash
production_psql -c "
SELECT node_id, ts, state_id, generated_at
FROM state_snapshots
WHERE node_id = '$CANARY_DEVICE_ID'
  AND generated_at >= '$CANARY_STARTED_UTC'::timestamptz
ORDER BY generated_at DESC
LIMIT 10;" | tee "$CANARY_EVIDENCE/state-snapshots.txt"

sudo find /srv/logs/senior-pomidor/estimator-private \
  -type f -newermt "$CANARY_STARTED_UTC" -print \
  | tee "$CANARY_EVIDENCE/estimator-private-files.txt"
```

Подтвердить:

* поступление MQTT telemetry;
* поступление HTTP telemetry, если она включена;
* успешную загрузку хотя бы одной фотографии;
* отсутствие 401/403;
* создание нового state snapshot;
* корректный device ID и pod key.

Дополнительно подтвердить отсутствие `401`, `403`, rejected schema, duplicate identity conflicts и
необъяснимых retries в logs:

```bash
"${prod_compose[@]}" logs --since "$CANARY_STARTED_UTC" \
  worker api state-estimator-worker </dev/null \
  > "$CANARY_EVIDENCE/application.log" 2>&1

grep -Ein '401|403|rejected|traceback|error|failed|duplicate' \
  "$CANARY_EVIDENCE/application.log" || true
```

## Шаг H3. Запустить остальные nodes

Canary считается успешным только если telemetry, photo upload/retrieval и estimator checks имеют
evidence, а Grafana показывает свежие данные canary без datasource errors.

После успешного canary переключать остальные nodes последовательно, сохраняя существующие tokens,
topic prefix и identifiers. После каждого node подтвердить первую новую telemetry строку и
отсутствие authentication/schema errors перед переходом к следующему.

Наблюдать не менее одного полного telemetry/photo cycle.

## Шаг H4. Выполнить post-cutover comparison

Снять production counts тем же per-table способом, что в G2, и сохранить отдельно. Ожидается:

* `telemetry_events`, `pod_readings` и при наличии новых upload `photos` увеличились;
* estimator tables увеличились после штатных estimator cycles;
* ни одна таблица не уменьшилась;
* device IDs соответствуют переключённым nodes;
* Windows counts после cold boundary не изменились.

Не сравнивать post-cutover counts на точное равенство с baseline: после первой принятой записи они
обязаны отличаться. Сравнение должно доказывать только ожидаемый монотонный рост.

## Шаг H5. Закрыть cutover evidence

Создать canary/final report с UTC timestamps, первой принятой записью каждого node, результатами
photo retrieval, State Estimator, Grafana и найденными ошибками. Создать `EVIDENCE_SHA256SUMS`,
проверить manifest и перенести каталог из `/tmp` в отдельный root-owned каталог под
`/srv/rehearsal/senior-pomidor/evidence` по процедуре C6.7.

После этого выполнить acceptance checklist и reboot test. Windows installation, volumes, `.env` и
final migration set не изменять и не удалять минимум семь дней.

---

# 12. Итоговая acceptance checklist

Миграция считается завершённой только после выполнения всех пунктов.

## Rehearsal

* [ ] Использован project name `senior-pomidor-rehearsal`.
* [ ] Все rehearsal ports привязаны только к `127.0.0.1`.
* [ ] Ни один rehearsal bind mount не указывает в production paths.
* [ ] Release image digest совпадает с результатом A8.
* [ ] Rehearsal baseline counts и representative photo hashes совпали.
* [ ] Rehearsal API, Grafana provisioning, MQTT ingestion и State Estimator проверены.
* [ ] Grafana Cloud exporter в rehearsal не запускался.

## Release

* [ ] Используется SemVer release tag.
* [ ] GitHub Actions release workflow успешен.
* [ ] GHCR image доступен.
* [ ] Записан image digest.
* [ ] Runtime bundle checksum проверен.
* [ ] `APP_IMAGE` не использует `latest`.
* [ ] `DATABASE_URL` согласован с отдельными PostgreSQL settings без вывода secrets.

## Cold cutover and restore

* [ ] Все edge nodes остановлены до final backup.
* [ ] Два Windows count snapshots перед backup совпали.
* [ ] PostgreSQL был единственным running Windows service во время backup.
* [ ] Между E3 и E4 PostgreSQL оставался running; полный `docker compose stop` выполнен только после backup.
* [ ] `docker compose down` и `docker compose down -v` не выполнялись на Windows production.
* [ ] Записан точный authoritative final set; rehearsal set не использован для production restore.
* [ ] Final set checksum повторно проверен на Ubuntu.
* [ ] Production service был inactive во время restore.
* [ ] Target database и application-owned directories были пустыми до restore.
* [ ] Restore завершился с exit code `0`; повторный частичный restore не выполнялся.
* [ ] Shared PostgreSQL, Grafana и Ollama не были пересозданы application scripts.

## Database

* [ ] Alembic revision соответствует release.
* [ ] Все baseline counts точно совпали до запуска `senior-pomidor.service`.
* [ ] Counts увеличиваются после запуска edge nodes.
* [ ] Старые PostgreSQL role passwords не восстановлены.
* [ ] Grafana reader grants применены.

## Files

* [ ] Фото восстановлены.
* [ ] Representative SHA-256 совпадают.
* [ ] Фото доступны через API.
* [ ] Estimator private data восстановлены.
* [ ] Platform Grafana datasource, dashboards и alerts provisioned и читают восстановленную БД.
* [ ] Mosquitto data восстановлены.

## Services

* [ ] `senior-pomidor.service` active.
* [ ] Все enabled containers healthy.
* [ ] `/health` успешен.
* [ ] `/ready` успешен.
* [ ] MQTT ingestion работает.
* [ ] HTTP telemetry ingestion работает.
* [ ] Photo upload работает.
* [ ] State Estimator создаёт новые snapshots.
* [ ] Grafana dashboards работают.
* [ ] Grafana alerts загружены.
* [ ] Cloud exporter пишет без ошибок.

## Canary and evidence

* [ ] Сначала переключён только один canary node.
* [ ] Зафиксирован timestamp первой принятой Ubuntu telemetry — data divergence boundary.
* [ ] Canary telemetry, pod readings, photo upload/retrieval и State Estimator подтверждены.
* [ ] Остальные nodes переключены только после canary PASS.
* [ ] Post-cutover counts показали только ожидаемый монотонный рост.
* [ ] Rehearsal, restore, pre-start и canary evidence сохранены с SHA-256 manifests.

## Security

* [ ] `API_DOCS_ENABLED=false`.
* [ ] PostgreSQL слушает только loopback.
* [ ] PostgreSQL недоступен с другого LAN host.
* [ ] Ollama port не доступен из LAN.
* [ ] `.env` отсутствует в Git и release archives.
* [ ] `/srv/secrets/senior-pomidor/runtime.env` принадлежит `root:root` и имеет права `0600`.
* [ ] API, MQTT и Grafana разрешены только нужным адресам.

## Reboot

* [ ] Ubuntu полностью перезагружен.
* [ ] Docker стартовал автоматически.
* [ ] `senior-pomidor.service` стартовал автоматически.
* [ ] Stack стал ready без ручных Docker-команд.
* [ ] Edge nodes восстановили передачу данных.

---

# 13. Включение резервного копирования

Проверить timer units:

```bash
sudo systemctl enable --now \
  senior-pomidor-backup-daily.timer \
  senior-pomidor-backup-weekly.timer
```

Проверить:

```bash
systemctl list-timers --all | grep senior-pomidor
```

Логи:

```bash
journalctl -u 'senior-pomidor-backup@*'
```

Ожидаемая политика:

* daily database dumps — 30 дней;
* weekly media/config data sets — 8 недель;
* checksum для каждого backup set.

Необходимо отдельно копировать verified backup sets на другой физический носитель или удалённое хранилище. Backup на том же серверном диске не защищает от потери этого диска.

---

# 14. План rollback

## До поступления данных на Ubuntu

Если Ubuntu не прошёл acceptance:

1. Остановить Ubuntu stack.
2. Не изменять Ubuntu restore data.
3. Вернуть edge nodes старый Windows IP.
4. Запустить Windows Compose stack.
5. Проверить `/health` и `/ready`.
6. Возобновить edge nodes.

## После поступления данных на Ubuntu

Предпочтителен forward fix.

Если необходим экстренный rollback:

1. Остановить все edge nodes.
2. Создать новый полный backup Ubuntu.
3. Остановить Ubuntu stack.
4. Зафиксировать последний Ubuntu timestamp и counts.
5. Переключить edge nodes на Windows.
6. Запустить Windows.
7. Не удалять данные Ubuntu.
8. Позже выполнить reconciliation данных, поступивших после cutover.

Не выполнять Alembic downgrade.

Не удалять volumes ни на одном сервере.

## Application-only rollback

Можно переключить:

```text
/srv/apps/senior-pomidor/app
```

на предыдущий archived release только после проверки, что его Docker image совместим с текущей схемой БД.

---

# 15. Что сохранить для публикации опыта

Для публичного migration report сохранить без секретов:

* версию Windows и Ubuntu;
* hardware configuration;
* размер БД;
* число telemetry records;
* число фотографий;
* длительность outage;
* размер migration archive;
* release version и commit SHA;
* image digest;
* найденные проблемы;
* результаты rehearsal;
* результаты checksum verification;
* результаты reboot test;
* реальные ошибки и способы исправления.

Не публиковать:

* точный домашний адрес;
* LAN topology;
* IP allow-lists;
* SSH keys;
* tokens;
* passwords;
* полный `.env`;
* Grafana Cloud credentials.

