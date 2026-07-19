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
* данных Grafana;
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
mosquitto.conf
VERSION
senior-pomidor.env.example
config/daily_story/
docker/grafana/
docker/postgres/
deploy/apt/
deploy/systemd/
scripts/
```

Python source code в runtime bundle не включается. Код приложения находится внутри Docker image.

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
* Grafana;
* Mosquitto;
* estimator private data;
* минимум одной дополнительной копии migration set.

---

# 6. Фаза C — обязательная rehearsal migration

Rehearsal проводится до финального cutover.

Цель — проверить restore на Ubuntu без использования production bind mounts.

## Шаг C1. Создать предварительный Windows backup

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
grafana.tar.gz
mosquitto.tar.gz
representative-photo-sha256.txt
SHA256SUMS
```

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

Рекомендуемый вариант через `scp`:

```powershell
scp -r `
  D:\senior-pomidor-backups\migration-YYYYMMDD-HHMMSS `
  senior-pomidor@<UBUNTU_IP>:/srv/backups/senior-pomidor/
```

Если пользователь `senior-pomidor` не имеет права писать непосредственно в backup root:

```powershell
scp -r `
  D:\senior-pomidor-backups\migration-YYYYMMDD-HHMMSS `
  senior-pomidor@<UBUNTU_IP>:/tmp/
```

Затем на Ubuntu:

```bash
sudo mv /tmp/migration-YYYYMMDD-HHMMSS \
  /srv/backups/senior-pomidor/
sudo chown -R root:senior-pomidor \
  /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
sudo chmod -R o-rwx \
  /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
```

## Шаг C4. Проверить checksums на Ubuntu

```bash
cd /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
sha256sum --check SHA256SUMS
```

Каждая строка должна завершиться:

```text
OK
```

## Шаг C5. Выполнить rehearsal в изолированных каталогах

Не использовать production paths.

Создать отдельные каталоги, например:

```text
/srv/rehearsal/senior-pomidor/postgres
/srv/rehearsal/senior-pomidor/grafana
/srv/rehearsal/senior-pomidor/mosquitto
/srv/rehearsal/senior-pomidor/photos
/srv/rehearsal/senior-pomidor/estimator-private
```

Использовать отдельный Compose project name:

```bash
export COMPOSE_PROJECT_NAME=senior-pomidor-rehearsal
```

Переопределить:

```text
POSTGRES_DATA_DIR
GRAFANA_DATA_DIR
MOSQUITTO_DATA_DIR
PHOTO_DATA_DIR
ESTIMATOR_PRIVATE_DATA_DIR
API_PUBLISHED_PORT
MQTT_PUBLISHED_PORT
GRAFANA_PUBLISHED_PORT
LAN_BIND_ADDRESS
```

Обязательно:

```text
GRAFANA_CLOUD_EXPORT_ENABLED=false
```

В rehearsal нельзя отправлять duplicate metrics в Grafana Cloud.

## Шаг C6. Проверить rehearsal

Проверить:

```bash
docker compose ps
curl -fsS http://127.0.0.1:<REHEARSAL_API_PORT>/health
curl -fsS http://127.0.0.1:<REHEARSAL_API_PORT>/ready
```

Проверить:

* Alembic revision;
* counts из `baseline-counts.csv`;
* representative photo SHA-256;
* получение фото через API;
* Grafana datasource;
* dashboard provisioning;
* alert provisioning;
* MQTT ingestion;
* создание нового State Estimator snapshot;
* отсутствие unexplained unhealthy containers.

Cutover нельзя начинать, пока rehearsal не завершён успешно.

---

# 7. Фаза D — установка production release на Ubuntu

Эта фаза может быть выполнена до остановки Windows, но Ubuntu stack не должен принимать edge traffic до восстановления данных.

## Шаг D1. Скачать release assets

Поместить файлы в:

```text
/srv/apps/senior-pomidor/releases/.incoming
```

Например, через браузер и `scp`, GitHub CLI или `curl` с release URL.

Получиться должны:

```text
/srv/apps/senior-pomidor/releases/.incoming/
  senior-pomidor-runtime-v0.2.0.tar.gz
  senior-pomidor-runtime-v0.2.0.tar.gz.sha256
```

## Шаг D2. Проверить checksum

```bash
cd /srv/apps/senior-pomidor/releases/.incoming
sha256sum --check senior-pomidor-runtime-v0.2.0.tar.gz.sha256
```

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
DATABASE_URL=postgresql+psycopg://...
PLATFORM_DOCKER_NETWORK=srv-platform

TELEMETRY_UPLOAD_TOKEN=<existing-token>
PHOTO_UPLOAD_TOKEN=<existing-token>

API_DOCS_ENABLED=false
COMPOSE_PROFILES=cloud-export
```

Не добавлять profile:

```text
daily-story
```

пока platform administrator не provisioned требуемую модель в shared Ollama.

Проверить права:

```bash
sudo chown root:root /srv/secrets/senior-pomidor/runtime.env
sudo chmod 0600 /srv/secrets/senior-pomidor/runtime.env
```

## Шаг D4. Установить release

```bash
cd /srv/apps/senior-pomidor/releases/.incoming

sudo /srv/automation/scripts/senior-pomidor/install-release.sh \
  senior-pomidor-runtime-v0.2.0.tar.gz \
  senior-pomidor-runtime-v0.2.0.tar.gz.sha256
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
```

Ожидается:

```text
/srv/apps/senior-pomidor/releases/v0.2.0
v0.2.0
```

Пока не запускать полный production stack, если восстановление ещё не выполнено.

---

# 8. Фаза E — финальный cold cutover

## Шаг E1. Объявить окно недоступности

На время migration остановятся:

* MQTT ingestion;
* HTTP telemetry ingestion;
* photo upload;
* dashboard/API;
* State Estimator;
* Grafana export.

## Шаг E2. Остановить все Raspberry Pi edge nodes

Остановить отправку:

* MQTT telemetry;
* HTTP telemetry;
* photo uploads.

Проверить на Windows, что counts больше не меняются.

Снять counts дважды с интервалом несколько минут.

## Шаг E3. Остановить Windows writers

Оставить только PostgreSQL:

```powershell
docker compose stop `
  api `
  worker `
  state-estimator-worker `
  grafana `
  grafana-cloud-exporter
```

Если присутствуют story worker или другие процессы записи, остановить их также.

Проверить:

```powershell
docker compose ps
```

PostgreSQL должен оставаться running.

## Шаг E4. Создать финальный migration set

```powershell
.\tools\backup_data.ps1 `
  -Mode migration `
  -BackupRoot D:\senior-pomidor-backups `
  -ProjectName senior-pomidor-server
```

## Шаг E5. Остановить оставшиеся Windows services

После успешного backup:

```powershell
docker compose stop
```

Не выполнять:

```powershell
docker compose down -v
```

Не удалять:

* containers;
* volumes;
* images;
* working directory;
* `.env`.

## Шаг E6. Проверить финальный backup

Проверить:

* список файлов;
* размеры;
* baseline counts;
* representative photo hashes;
* `SHA256SUMS`.

Этот backup является authoritative migration set.

## Шаг E7. Передать финальный backup на Ubuntu

```powershell
scp -r `
  D:\senior-pomidor-backups\migration-YYYYMMDD-HHMMSS `
  senior-pomidor@<UBUNTU_IP>:/tmp/
```

На Ubuntu:

```bash
sudo mv /tmp/migration-YYYYMMDD-HHMMSS \
  /srv/backups/senior-pomidor/

sudo chown -R root:senior-pomidor \
  /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS

sudo chmod -R o-rwx \
  /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
```

## Шаг E8. Проверить checksums на Ubuntu

```bash
cd /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
sha256sum --check SHA256SUMS
```

Не продолжать при любой ошибке.

---

# 9. Фаза F — восстановление на Ubuntu

## Шаг F1. Убедиться, что production data directories пусты

Проверить:

```bash
sudo find /srv/apps/senior-pomidor/data/private/mosquitto -mindepth 1 -maxdepth 1
sudo find /srv/apps/senior-pomidor/data/public/photos -mindepth 1 -maxdepth 1
sudo find /srv/logs/senior-pomidor/estimator-private -mindepth 1 -maxdepth 1
```

Команды не должны вывести файлов.

Не очищать непустой каталог автоматически. Сначала определить источник данных.

## Шаг F2. Выполнить restore

```bash
sudo /srv/automation/scripts/senior-pomidor/restore-migration.sh \
  /srv/backups/senior-pomidor/migration/migration-YYYYMMDD-HHMMSS
```

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

---

# 10. Фаза G — запуск Ubuntu production

## Шаг G1. Запустить systemd service

```bash
sudo systemctl start senior-pomidor
```

## Шаг G2. Проверить systemd

```bash
systemctl status senior-pomidor --no-pager
journalctl -u senior-pomidor -n 200 --no-pager
```

## Шаг G3. Проверить контейнеры

```bash
cd /srv/apps/senior-pomidor/app
sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env \
  -f docker-compose.yml -f docker-compose.prod.yml ps
```

Все enabled containers должны быть running или healthy.

## Шаг G4. Проверить API

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```

Затем через LAN IP:

```bash
curl -fsS http://<NEW_SERVER_LAN_IP>:8000/health
curl -fsS http://<NEW_SERVER_LAN_IP>:8000/ready
```

## Шаг G5. Проверить Alembic revision

```bash
cd /srv/apps/senior-pomidor/app

sudo docker run --rm --network srv-platform \
  --env-file /srv/secrets/senior-pomidor/runtime.env postgres:16-alpine \
  sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version"'
```

## Шаг G6. Сравнить counts

Запустить baseline query и сравнить с:

```text
baseline-counts.csv
```

До запуска edge nodes counts должны совпадать.

## Шаг G7. Проверить фотографии

Проверить hashes нескольких восстановленных файлов:

```bash
sha256sum <photo-path>
```

Сравнить с:

```text
representative-photo-sha256.txt
```

Проверить получение фотографий через API.

## Шаг G8. Проверить Grafana

Проверить:

* вход;
* PostgreSQL datasource;
* dashboard `Senior Pomidor Telemetry`;
* dashboard panels;
* alert rules;
* отсутствие datasource errors.

## Шаг G9. Проверить Grafana Cloud exporter

Если exporter включён:

```bash
sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env \
  -f docker-compose.yml -f docker-compose.prod.yml \
  logs --tail=200 grafana-cloud-exporter
```

Не должно быть authorization, remote-write или repeated retry errors.

## Шаг G10. Проверить State Estimator

```bash
sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env \
  -f docker-compose.yml -f docker-compose.prod.yml \
  logs --tail=200 state-estimator-worker
```

Проверить создание новых:

* state snapshots;
* sensor health snapshots;
* diagnostics;
* private JSONL records.

До поступления свежей telemetry отсутствие нового state может быть ожидаемым.

---

# 11. Фаза H — переключение Raspberry Pi

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

## Шаг H2. Запустить только один node

Запустить первый Raspberry Pi.

Проверить на Ubuntu:

```bash
sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env \
  -f docker-compose.yml -f docker-compose.prod.yml \
  logs -f worker api state-estimator-worker
```

Подтвердить:

* поступление MQTT telemetry;
* поступление HTTP telemetry, если она включена;
* успешную загрузку хотя бы одной фотографии;
* отсутствие 401/403;
* создание нового state snapshot;
* корректный device ID и pod key.

## Шаг H3. Запустить остальные nodes

После успешного теста первого node переключить остальные.

Наблюдать не менее одного полного telemetry/photo cycle.

---

# 12. Итоговая acceptance checklist

Миграция считается завершённой только после выполнения всех пунктов.

## Release

* [ ] Используется SemVer release tag.
* [ ] GitHub Actions release workflow успешен.
* [ ] GHCR image доступен.
* [ ] Записан image digest.
* [ ] Runtime bundle checksum проверен.
* [ ] `APP_IMAGE` не использует `latest`.

## Database

* [ ] Alembic revision соответствует release.
* [ ] Все baseline counts совпадают до запуска edge nodes.
* [ ] Counts увеличиваются после запуска edge nodes.
* [ ] Старые PostgreSQL role passwords не восстановлены.
* [ ] Grafana reader grants применены.

## Files

* [ ] Фото восстановлены.
* [ ] Representative SHA-256 совпадают.
* [ ] Фото доступны через API.
* [ ] Estimator private data восстановлены.
* [ ] Grafana data восстановлены.
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

## Security

* [ ] `API_DOCS_ENABLED=false`.
* [ ] PostgreSQL слушает только loopback.
* [ ] PostgreSQL недоступен с другого LAN host.
* [ ] Ollama port не доступен из LAN.
* [ ] `.env` отсутствует в Git и release archives.
* [ ] Environment file имеет права `0640`.
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

