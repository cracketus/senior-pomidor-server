# Post-merge pre-production qualification — новая immutable campaign

Проверка процедуры: 2026-09-24. Для v0.3.1 заново фиксируются Core/Edge SHA, digest, CI и evidence.
Ни одна отметка старой кампании не переносится автоматически.

## Цель и мотивация

Эпик #225 проверяет не только то, что сервер собирается и unit-тесты зелёные. Он должен доказать,
что связка Edge → MQTT/HTTP → Core → PostgreSQL → API/Grafana сохраняет данные, корректно переживает
сбои и не смешивает staging с production.

У владельца сейчас есть только рабочий ноутбук, production server и production Edge node. Поэтому
эта инструкция разделяет места выполнения:

- рабочий ноутбук — все безопасные server tests, schema checks, Docker E2E и локальная staging-like
  репетиция, если на ноутбуке доступен Docker;
- production server — только read-only проверки статуса, backup/recovery evidence и отдельно
  авторизованное production наблюдение; staging Compose туда не устанавливать;
- production Edge node — только проверка текущего production identity/health и ручное подтверждение
  Edge release artifacts; не подключать production Edge к staging network и не менять его payload
  без отдельного окна и rollback plan.

Цель этого этапа — получить честный pre-production PASS или зафиксировать NOT_RUN. Это не разрешение
на production rollout и не доказательство физических или биологических результатов.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Границы laptop, staging и production определены |
| Переход | Все действия ниже выполняются только в указанной среде |

## Дорожная карта участка вокруг эпика #225

| Этап | Что доказывает | Где выполняется | Статус/результат |
| --- | --- | --- | --- |
| #225 foundation | telemetry, persistence, reads, reliability contracts | server CI + local tests | реализовано |
| #247 / PR #268 | Docker E2E, evidence schemas, invariant checks, fail-closed workflow | laptop + GitHub CI | реализовано |
| #260 / PR #270 | Core SHA-only RC, staging boundary, preproduction/full validator | laptop + GitHub CI | реализовано |
| Immutable Core/Edge RC pair | exact Git SHAs, image digests and green publishing CI | Core and Edge repositories | NOT_RUN для новой campaign |
| Pre-production qualification | real compatibility, isolated staging, 24h soak, exact bundle, rollback | isolated laptop rehearsal или отдельный staging host | NOT_RUN; следующий этап |
| Canary | один production Edge после Core rollout | production server + production Edge | NOT_RUN, human approval |
| Production observation | стабильность после canary и rollback | production | NOT_RUN, human approval |

Результат pre-production не закрывает #225 полностью: canary, production rollout и 24-hour production
observation остаются отдельными этапами.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Текущий этап — pre-production; canary и production observation отделены |
| Переход | Выполнять только pre-production steps 1–13 |

## Матрица: что где тестировать

| Область | Рабочий ноутбук | Production server | Production Edge |
| --- | --- | --- | --- |
| Python tests, schemas, validator | да | нет необходимости | нет |
| Docker E2E | да, только isolated project | нет | нет |
| Staging Compose | да, только local paths/ports | не запускать | не подключать |
| Edge image metadata | проверить artifact/registry | можно read-only pull/inspect | проверить running image read-only |
| Реальный Edge/Core transport | только если есть отдельный Edge container/simulator | только после approval | только production window |
| 24h compatibility soak | только с отдельным Edge или отдельным staging host | не на production данных | только human-owned evidence |
| Canary/production | нет | только с approval | только с approval |

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Для каждой проверки назначена единственная допустимая среда |
| Переход | Недоступная в допустимой среде проверка получает `NOT_RUN` |

## Как пользоваться

Работайте блоками сверху вниз. После каждого блока проверяйте ожидаемый результат.

Если результат не совпал: STOP. Не переходить к следующему шагу.

Каждый исполняемый раздел завершается таблицей:

| Поле | Правило |
| --- | --- |
| Ожидаемый результат | Наблюдаемое состояние после команд раздела |
| Переход | Проверяемое условие запуска следующего раздела |

`returncode: 0` подтверждает выполнение команды, но не заменяет `status: PASS`.
Обязательный `NOT_RUN`, `FAIL`, restart loop или identity mismatch блокирует переход.

Запрещено:

- `docker compose down -v`;
- использовать production `.env`, paths, volumes или Compose project;
- включать Grafana Cloud export;
- выполнять команды против GPIO/актуаторов;
- вручную менять production database.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Оператор применяет fail-closed переходы и запреты |
| Переход | Начать шаг 1 только после принятия этих правил |

## Текущий статус предусловий

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Выбрана одна immutable Core/Edge pair; текущие `PASS` и `NOT_RUN` перечислены ниже |
| Переход | Не заменять identity во время campaign |

### Выбрать identities до выполнения команд

После [release-to-E2E runbook](RELEASE_TO_E2E_RUNBOOK.md) перенесите только non-secret identities
из приватной записи новой кампании. В Bash/WSL:

```bash
set -euo pipefail
read -r -p 'Accepted Core Git SHA: ' EXPECTED_CORE_SHA
read -r -p 'Accepted Core digest (sha256:...): ' EXPECTED_CORE_DIGEST
read -r -p 'Accepted Edge Git SHA: ' EDGE_SHA
read -r -p 'Accepted Edge digest (sha256:...): ' EDGE_DIGEST
[[ "$EXPECTED_CORE_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$EDGE_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$EXPECTED_CORE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "$EDGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
export EXPECTED_CORE_SHA EXPECTED_CORE_DIGEST EDGE_SHA EDGE_DIGEST
export EDGE_IMAGE="ghcr.io/cracketus/senior-pomidor-edge@$EDGE_DIGEST"
```

Зафиксируйте exact-SHA Core CI и Edge RC run URLs отдельно. Green build не подтверждает
real Edge/Core compatibility, staging, soak или rollback. Эти gates начинают с `NOT_RUN`.
Core и Edge checkout должны быть чистыми; новую identity нельзя подставлять посреди qualification.

## 1. Проверить server merge и CI

Откройте:

    https://github.com/cracketus/senior-pomidor-server/actions

Для `EXPECTED_CORE_SHA` jobs должны быть `PASS` в exact-SHA CI run, записанном в этой кампании:

- `test`
- `quality`
- `security`
- `docker-e2e`
- `core-release-candidate`

На server checkout:

    cd /path/to/senior-pomidor-server
    test -z "$(git status --porcelain)"
    git fetch origin
    git checkout --detach "$EXPECTED_CORE_SHA"
    test "$(git rev-parse HEAD)" = "$EXPECTED_CORE_SHA"
    git rev-parse HEAD
    git status --short --branch

Ожидается полный merge SHA и чистое дерево.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Все пять required jobs — PASS; checkout указывает на выбранный Core SHA; дерево чистое |
| Переход | Нет failed/cancelled jobs; `git rev-parse HEAD` совпал; `git status --short` пуст |

## 2. Получить Core RC artifact

Скачайте artifact `senior-pomidor.core.release-candidate.v1` из job `core-release-candidate`.

    jq . senior-pomidor.core.release-candidate.v1.json
    export CORE_SHA="$(jq -r '.git_sha' senior-pomidor.core.release-candidate.v1.json)"
    export CORE_IMAGE="$(jq -r '.image_ref' senior-pomidor.core.release-candidate.v1.json)"
    export CORE_DIGEST="$(jq -r '.image_digest' senior-pomidor.core.release-candidate.v1.json)"
    test "$CORE_SHA" = "$EXPECTED_CORE_SHA"
    test "$CORE_IMAGE" = "ghcr.io/cracketus/senior-pomidor-server@$EXPECTED_CORE_DIGEST"
    test "$CORE_DIGEST" = "$EXPECTED_CORE_DIGEST"
    [[ "$CORE_IMAGE" == *"@$CORE_DIGEST" ]]
    [[ "$CORE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
    jq -e '.platforms == ["linux/amd64", "linux/arm64"]' \
      senior-pomidor.core.release-candidate.v1.json

Проверить registry manifest и OCI revision:

    docker buildx imagetools inspect "$CORE_IMAGE" --raw \
      | jq '[.manifests[] | .platform | "\(.os)/\(.architecture)"]'
    docker pull "$CORE_IMAGE"
    docker image inspect "$CORE_IMAGE" \
      --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'

Последняя команда должна вывести полный CORE_SHA.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Artifact identity, registry digest, platforms и OCI revision согласованы |
| Переход | Все `test`/`jq` завершились с кодом `0`; OCI revision равен `CORE_SHA` |

## 3. Проверить Edge repository

В Edge checkout:

    cd /path/to/senior-pomidor-plant-v2
    git fetch --all --tags
    test -z "$(git status --porcelain)"
    git checkout --detach "$EDGE_SHA"
    git rev-parse HEAD
    git status --short

Проверьте выбранный SHA:

    test "$(git rev-parse HEAD)" = "$EDGE_SHA"

Проверьте Edge CI для этого SHA и получите Edge RC artifact. Digest нельзя вычислять из Git SHA.

    [[ "$EDGE_IMAGE" == *"@$EDGE_DIGEST" ]]
    [[ "$EDGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
    docker pull "$EDGE_IMAGE"
    docker image inspect "$EDGE_IMAGE" \
      --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'

Ожидается OCI revision, равный `EDGE_SHA`. Независимо проверьте успешный Edge RC run для этой identity;
его artifact должен совпасть с `EDGE_IMAGE` и `EDGE_DIGEST`.

Edge maintainer дополнительно подтверждает staging identity, MQTT topic prefix, container name,
interop network и безопасные software-only fault paths. Недоступный Edge path остаётся NOT_RUN.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Edge checkout, immutable image digest, OCI revision и required CI согласованы |
| Переход | Identity совпала; Edge maintainer подтвердил staging-only software paths; иначе Edge gates — `NOT_RUN` |

### Что делать с production Edge node

На production Edge node разрешена только read-only проверка текущей версии и health. Не подключайте
его к `senior-pomidor-staging-interop`, не переименовывайте production identity в `edge-staging-*`
и не направляйте его telemetry в staging без отдельного human-approved maintenance window.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Production Edge не изменён и не подключён к staging |
| Переход | Для следующих шагов используется только dedicated Edge staging container |

Если отдельного staging Edge container или simulator нет, Edge/Core compatibility, fault scenarios
и 24-hour soak нельзя выполнить на ноутбуке. Их нужно оставить `NOT_RUN` и запросить отдельный staging
ресурс либо отдельное разрешение на production qualification.

## 4. Подготовить рабочий ноутбук

Основной безопасный вариант — запускать этот раздел на ноутбуке в WSL2/Linux shell или на Linux
ноутбуке. Если Docker daemon на ноутбуке недоступен, выполнить только Python/schema/validator проверки
и отметить Docker E2E и локальную staging-like репетицию `NOT_RUN`.

Никогда не использовать для этого раздела production server или production Edge node.

Используйте отдельный local staging path на WSL2/ext4, не production path. Исходные checkout
репозиториев могут оставаться в `/mnt/e`, но PostgreSQL, MQTT, Edge spool и secrets должны
находиться под `$STAGING_ROOT` в Linux filesystem:

    export STAGING_ROOT="$HOME/.local-staging"
    export SERVER_ROOT="/mnt/e/MyProjects/senior-pomidor-server"
    export EDGE_ROOT="/mnt/e/MyProjects/senior-pomidor-plant-v2"
    mkdir -p "$STAGING_ROOT"
    test -d "$SERVER_ROOT" -a -d "$EDGE_ROOT"
    cd "$SERVER_ROOT"
    git fetch origin
    git checkout --detach "$CORE_SHA"
    test "$(git rev-parse HEAD)" = "$CORE_SHA"

Создать staging data directories:

    mkdir -p "$STAGING_ROOT/data/postgres" \
      "$STAGING_ROOT/data/mosquitto" "$STAGING_ROOT/data/photos" \
      "$STAGING_ROOT/data/estimator-private" "$STAGING_ROOT/data/grafana" \
      "$STAGING_ROOT/secrets"
    chmod 700 "$STAGING_ROOT/data" "$STAGING_ROOT/secrets"

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Core checkout равен выбранному `CORE_SHA`; staging data и secrets находятся в `$STAGING_ROOT` на WSL2/ext4 |
| Переход | `test` и `git rev-parse` завершились с кодом `0`; Docker daemon доступен |

## 5. Подготовить env и MQTT credentials

    cp deploy/senior-pomidor-staging.env.example \
      "$STAGING_ROOT/secrets/staging.env"
    chmod 600 "$STAGING_ROOT/secrets/staging.env"
    nano "$STAGING_ROOT/secrets/staging.env"

Если файл был создан или отредактирован в Windows, перед `source` удалите CRLF,
не выводя содержимое файла:

    sed -i 's/\r$//' "$STAGING_ROOT/secrets/staging.env"
    sed -i '1s/^\xEF\xBB\xBF//' "$STAGING_ROOT/secrets/staging.env"
    ! grep -q $'\r' "$STAGING_ROOT/secrets/staging.env"

Обязательные значения:

    APP_IMAGE=<paste the exact value of CORE_IMAGE, not a literal variable>
    COMPOSE_PROFILES=observability
    DEPLOYMENT_MODE=staging
    STAGING_DEVICE_PREFIX=edge-staging-
    STAGING_MQTT_TOPIC_PREFIX=senior-pomidor-staging
    STAGING_INTEROP_NETWORK=senior-pomidor-staging-interop
    STAGING_EDGE_CONTAINER_NAME=senior-pomidor-edge-staging
    GRAFANA_CLOUD_EXPORT_ENABLED=false

Все STAGING_*_DATA_DIR должны быть внутри `$STAGING_ROOT`. Config/password/ACL
должны быть отдельными staging files, не production files.

В `staging.env` укажите для bind mounts абсолютные пути, полученные через `realpath`;
не оставляйте относительные `./data/...` и не записывайте `$STAGING_ROOT` как буквальный
текст. Конфиг является tracked-файлом checkout, password и ACL — внешними staging secrets:

    realpath "$STAGING_ROOT/data/postgres"
    realpath "$STAGING_ROOT/data/mosquitto"
    realpath "$STAGING_ROOT/data/photos"
    realpath "$STAGING_ROOT/data/estimator-private"
    realpath "$STAGING_ROOT/data/grafana"
    realpath "$SERVER_ROOT/deploy/staging/mosquitto.conf"
    realpath "$STAGING_ROOT/secrets/mosquitto.password"
    realpath "$STAGING_ROOT/secrets/mosquitto.acl"

Результаты этих команд должны стать значениями `STAGING_*_DATA_DIR`,
`STAGING_MOSQUITTO_CONFIG_FILE`, `STAGING_MOSQUITTO_PASSWORD_FILE` и
`STAGING_MOSQUITTO_ACL_FILE` в `staging.env`.

Создать password file интерактивно:

    mosquitto_passwd -c "$STAGING_ROOT/secrets/mosquitto.password" senior-pomidor-staging
    sudo chown 1883:1883 "$STAGING_ROOT/secrets/mosquitto.password"
    sudo chmod 600 "$STAGING_ROOT/secrets/mosquitto.password"

Создать и проверить ACL:

    cp deploy/staging/mosquitto.acl.example "$STAGING_ROOT/secrets/mosquitto.acl"
    sudo chown 1883:1883 "$STAGING_ROOT/secrets/mosquitto.acl"
    sudo chmod 600 "$STAGING_ROOT/secrets/mosquitto.acl"
    grep -F 'topic senior-pomidor-staging/#' "$STAGING_ROOT/secrets/mosquitto.acl"

Не выводить env/password/token в terminal log, issue или evidence.

Загрузить env и проверить несекретные ограничения:

    set -a
    source "$STAGING_ROOT/secrets/staging.env"
    set +a
    export STAGING_GRAFANA_URL="http://127.0.0.1:$STAGING_GRAFANA_PUBLISHED_PORT"
    test "$DEPLOYMENT_MODE" = staging
    test "$GRAFANA_CLOUD_EXPORT_ENABLED" = false
    test "$STAGING_INTEROP_NETWORK" = senior-pomidor-staging-interop
    test "$STAGING_EDGE_CONTAINER_NAME" = senior-pomidor-edge-staging

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Env загружается без `command not found`; password и ACL — regular files `600`, owner `1883:1883`; bind paths абсолютные |
| Переход | Все `test` завершились с кодом `0`; password, ACL и config существуют по точным путям из env |

### Подготовить отдельный Edge staging container

В `senior-pomidor-plant-v2` уже есть software-staging bundle:
`deploy/rehearsal/edge-staging/compose.yml`, `manage.sh` и `.env.example`.
Он запускает настоящее Edge-приложение с `MOCK_SENSORS=true`; production Edge node
для этой процедуры не используется.

Скопировать только bundle и создать его state вне checkout:

    export EDGE_STAGING_ROOT="$STAGING_ROOT/edge-staging"
    mkdir -p "$EDGE_STAGING_ROOT"
    cp "$EDGE_ROOT/deploy/rehearsal/edge-staging/compose.yml" \
      "$EDGE_ROOT/deploy/rehearsal/edge-staging/manage.sh" \
      "$EDGE_ROOT/deploy/rehearsal/edge-staging/.env.example" "$EDGE_STAGING_ROOT/"
    chmod 750 "$EDGE_STAGING_ROOT/manage.sh"
    cd "$EDGE_STAGING_ROOT"
    cp .env.example .env
    chmod 600 .env

Если Edge `.env` редактировался в Windows, нормализуйте его окончания строк:

    sed -i 's/\r$//' .env

Для локального Core укажите в `.env` staging-only значения:

    STAGING_MQTT_HOST=mosquitto
    STAGING_MQTT_PORT=1883
    STAGING_MQTT_USERNAME=senior-pomidor-staging
    STAGING_MQTT_PASSWORD=<тот же staging password, что в broker password file>
    STAGING_MQTT_TLS=false
    STAGING_CORE_HTTP_URL=http://api:8000/api/v1/edge/telemetry
    STAGING_TELEMETRY_UPLOAD_TOKEN=<тот же staging telemetry token>

Значения `EDGE_IMAGE` и Edge commit SHA берите из Edge RC artifact. Tags и локальные
непроверенные образы запрещены:

    ./manage.sh deploy \
      "$EDGE_IMAGE" \
      "$EDGE_SHA"

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Dedicated Edge bundle использует immutable Edge image, mock sensors и staging credentials |
| Переход | `./manage.sh deploy` завершился с кодом `0`; image digest и revision совпадают с выбранной Edge RC |

## 6. Проверить Compose до запуска

Все Core Compose команды этого раздела и шага 7 выполняйте из `$SERVER_ROOT`.
Команды Edge bundle выполняйте отдельно из `$EDGE_STAGING_ROOT`; эти каталоги не взаимозаменяемы.

    cd "$SERVER_ROOT"

    docker compose --env-file "$STAGING_ROOT/secrets/staging.env" \
      -f docker-compose.yml -f docker-compose.staging.yml \
      --project-name senior-pomidor-staging --profile observability \
      config --quiet

Проверить loopback ports:

    docker compose --env-file "$STAGING_ROOT/secrets/staging.env" \
      -f docker-compose.yml -f docker-compose.staging.yml \
      --project-name senior-pomidor-staging --profile observability config \
      | grep -E '127\.0\.0\.1:'

Проверить labels/export:

    docker compose --env-file "$STAGING_ROOT/secrets/staging.env" \
      -f docker-compose.yml -f docker-compose.staging.yml \
      --project-name senior-pomidor-staging config \
      | grep -E 'DEPLOYMENT_MODE|senior-pomidor.environment|external-export|GRAFANA_CLOUD_EXPORT_ENABLED'

Все ports должны быть `127.0.0.1:*`; export должен быть disabled.

Проверить доступность host ports до `up`:

    for port in \
      "$STAGING_API_PUBLISHED_PORT" "$STAGING_MQTT_PUBLISHED_PORT" \
      "$STAGING_POSTGRES_PUBLISHED_PORT" "$STAGING_GRAFANA_PUBLISHED_PORT"; do
      ! ss -ltn "sport = :$port" | tail -n +2 | grep -q .
    done

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Compose config валиден; published ports — loopback; external export отключён; host ports свободны |
| Переход | `config --quiet` и проверки портов завершились с кодом `0` |

## 7. Запустить локальный staging-like Core и подключить только dedicated Edge

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Core и dedicated Edge запущены в isolated staging topology |
| Переход | Выполнить bind-mount проверки до первого `up` |

### Обязательная проверка bind mounts перед запуском

Перед первым `up` проверьте staging-пути. `STAGING_POSTGRES_DATA_DIR` должен находиться
на Linux filesystem (например, внутри WSL2/ext4), где контейнер PostgreSQL может выполнить
`chmod` и `chown`. Обычный Windows bind mount может завершить инициализацию с
`initdb: error: could not change permissions of directory "/var/lib/postgresql/data":
Operation not permitted`.

`STAGING_MOSQUITTO_PASSWORD_FILE`, `STAGING_MOSQUITTO_ACL_FILE` и
`STAGING_MOSQUITTO_CONFIG_FILE` должны существовать до запуска и быть обычными файлами.
Если source-файл отсутствует, Docker может создать каталог с таким именем; Mosquitto
затем завершится с `password_file ... is not a file`. Не используйте production-файлы.

В WSL2/Linux shell:

    test -d "$STAGING_POSTGRES_DATA_DIR"
    test -d "$STAGING_GRAFANA_DATA_DIR"
    test -f "$STAGING_MOSQUITTO_PASSWORD_FILE"
    test -f "$STAGING_MOSQUITTO_ACL_FILE"
    test -f "$STAGING_MOSQUITTO_CONFIG_FILE"
    test ! -d "$STAGING_MOSQUITTO_PASSWORD_FILE"
    test ! -d "$STAGING_MOSQUITTO_ACL_FILE"
    test ! -d "$STAGING_MOSQUITTO_CONFIG_FILE"
    sudo chown 1883:1883 "$STAGING_MOSQUITTO_PASSWORD_FILE" \
      "$STAGING_MOSQUITTO_ACL_FILE"
    sudo chmod 600 "$STAGING_MOSQUITTO_PASSWORD_FILE" \
      "$STAGING_MOSQUITTO_ACL_FILE"
    sudo chown -R 472:472 "$STAGING_GRAFANA_DATA_DIR"
    sudo chmod -R u+rwX,go-rwx "$STAGING_GRAFANA_DATA_DIR"
    chmod 700 "$STAGING_POSTGRES_DATA_DIR"
    stat -c '%F %a %u:%g %n' \
      "$STAGING_MOSQUITTO_PASSWORD_FILE" "$STAGING_MOSQUITTO_ACL_FILE" \
      "$STAGING_MOSQUITTO_CONFIG_FILE" "$STAGING_GRAFANA_DATA_DIR"

Если staging уже запускался и `postgres` или `mosquitto` находится в restart loop,
остановите только этот staging project, исправьте пути, затем повторите запуск. Сначала
сохраните PostgreSQL data directory; не удаляйте bind-mounted data и не используйте
`docker compose down -v`.

    docker compose --env-file "$STAGING_ROOT/secrets/staging.env" \
      -f docker-compose.yml -f docker-compose.staging.yml \
      --project-name senior-pomidor-staging stop postgres mosquitto

После исправления mount sources проверьте конфигурацию и логи контейнеров. К следующему
шагу переходите только когда `postgres` и `mosquitto` перестали перезапускаться.

Этот шаг выполняется только на ноутбуке и только с отдельным Edge staging container из
`senior-pomidor-plant-v2/deploy/rehearsal/edge-staging`. Production Edge node сюда подключать
запрещено. Сначала запустите Core, затем Edge bundle из `$EDGE_STAGING_ROOT`. Оба контейнера
должны оказаться в `senior-pomidor-staging-interop`; внутри этой сети Edge использует DNS-имена
`mosquitto` и `api`, а не `localhost`.

    cd "$SERVER_ROOT"

    docker compose --env-file "$STAGING_ROOT/secrets/staging.env" \
      -f docker-compose.yml -f docker-compose.staging.yml \
      --project-name senior-pomidor-staging --profile observability up -d
    docker compose --env-file "$STAGING_ROOT/secrets/staging.env" \
      -f docker-compose.yml -f docker-compose.staging.yml \
      --project-name senior-pomidor-staging --profile observability ps
    curl --fail http://127.0.0.1:18000/ready
    curl --fail http://127.0.0.1:18000/health
    docker network inspect senior-pomidor-staging-interop

`curl` выполнять после статуса API `healthy`. `connection reset` при `health: starting` не является
результатом проверки. Дождаться bounded healthcheck; повторить `curl`.

Если Docker Desktop возвращает `/forwards/expose ... status: 500` для нескольких свободных портов:

1. Остановить только конфликтующий staging service.
2. Проверить выбранный порт через `ss -ltn` и `docker ps`.
3. Перезапустить Docker Desktop. `wsl --shutdown` выполнять только после остановки других WSL workloads.
4. Повторить `config --quiet` и `up`. Не использовать `down -v`.

| Симптом | Проверка | Исправление |
| --- | --- | --- |
| Mosquitto: `is not a file` | `stat` exact source из `docker inspect .Mounts` | Исправить env; создать regular file до `up` |
| Mosquitto: `Unable to open pwfile` | owner/mode password и ACL | `chown 1883:1883`; `chmod 600` |
| Grafana: `/var/lib/grafana is not writable` | source mount и owner data directory | `chown -R 472:472`; owner-only write permissions |
| Host port: `/forwards/expose ... 500` | порт свободен в `ss` и `docker ps` | Перезапустить Docker Desktop forwarding |

Запустить Edge bundle и подключить его к Core network:

    cd "$EDGE_STAGING_ROOT"
    ./manage.sh start
    docker network connect senior-pomidor-staging-interop senior-pomidor-edge-staging
    ./manage.sh restart
    ./manage.sh version

Проверить Edge image/container:

    docker inspect senior-pomidor-edge-staging --format '{{.Config.Image}}'
    docker image inspect \
      "$(docker inspect senior-pomidor-edge-staging --format '{{.Config.Image}}')" \
      --format '{{json .RepoDigests}}'
    docker inspect senior-pomidor-edge-staging \
      --format '{{json .NetworkSettings.Networks}}' \
      | jq -e 'has("senior-pomidor-staging-interop")'

Если Edge ещё не подключён, выполните:

    docker network connect senior-pomidor-staging-interop senior-pomidor-edge-staging

Ошибка `already connected` означает, что подключение уже выполнено; после неё достаточно
повторить последнюю проверку сети.
Если `senior-pomidor-edge-staging` отсутствует, остановите qualification: Edge/Core
scenarios должны иметь статус `NOT_RUN`, а не PASS.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | `postgres`, `mosquitto`, `api`, `worker`, `state-estimator-worker`, `grafana` — healthy; `migrate` — `Exited (0)`; `/ready` и `/health` — HTTP 200; Edge подключён к interop network |
| Переход | Нет restart loop; healthchecks завершены; Edge image, revision и network совпадают с выбранной RC |

## 8. Выполнить controller preflight

    cd "$SERVER_ROOT"
    set -a
    source "$STAGING_ROOT/secrets/staging.env"
    set +a
    python -m tools.staging_qualification preflight

Ожидается `status=PASS`, `edge_connected=true`, fixed network и `external_export=disabled`.

`command not found` во время `source` или ошибка `DEPLOYMENT_MODE=staging` при видимом значении
`staging` означает CRLF/BOM. Повторить нормализацию из шага 5; загрузить env заново.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | JSON содержит `status: PASS`, `edge_connected: true`, fixed network и `external_export: disabled` |
| Переход | Только `status: PASS`; любой другой статус блокирует шаг 9 |

## 9. Выполнить десять сценариев

    python -m tools.staging_qualification scenario normal-delivery
    python -m tools.staging_qualification scenario core-outage-spool-growth
    python -m tools.staging_qualification scenario core-recovery-full-drain
    python -m tools.staging_qualification scenario lost-ack-after-persistence
    python -m tools.staging_qualification scenario duplicate-http-mqtt
    python -m tools.staging_qualification scenario edge-restart-pending
    python -m tools.staging_qualification scenario fresh-during-backlog-replay
    python -m tools.staging_qualification scenario watchdog-recovering-suppressed
    python -m tools.staging_qualification scenario spool-degraded-critical
    python -m tools.staging_qualification scenario delayed-stale-future-out-of-order

Controller output не является PASS evidence. Для каждого сценария нужен реальный Edge/Core report.
Проверить generated > 0, generated = persisted = read_back, missing = 0, ожидаемые duplicates,
record_id, observation time, API/Grafana outcomes и отсутствие external export.

Если сценарий нельзя выполнить через реальный Edge software path, отметить NOT_RUN.

Текущий controller после boundary checks возвращает `status: NOT_RUN`. Для
`core-outage-spool-growth` он останавливает API; для `core-recovery-full-drain` запускает API.
`returncode: 0` означает успешный вызов controller, не успешный сценарий. После этой пары повторить
`preflight`, `/ready` и `/health`.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Для каждого сценария есть реальный sanitized Edge/Core report с counts, timestamps, duplicate и alert outcomes; controller-only результат остаётся `NOT_RUN` |
| Переход | Все 10 реальных сценариев имеют `PASS`; при любом `NOT_RUN` не запускать qualification workflow с `--require-pass` |

## 10. Провести 24-hour soak

На текущем наборе оборудования этот шаг обычно имеет статус `NOT_RUN`: рабочий ноутбук не заменяет
отдельный staging host, а production Edge нельзя использовать как staging Edge без отдельного
разрешённого окна. Не запускайте 24-hour soak против production server или production data.

    python -m tools.staging_qualification preflight
    date -u
    python -m tools.staging_qualification soak-check

Для автоматических ночных проверок запустите bounded monitor из `$SERVER_ROOT`. Каждые 5 минут
в течение 24 часов он проверяет health всех Core services, `/ready`, `/health`, отдельный Edge
container, его interop network и spool, а также наличие свежей telemetry за последний час.
Docker-команды ограничены timeout; пропущенный из-за сна ноутбука интервал делает результат `FAIL`.
Monitor работает только с фиксированным project `senior-pomidor-staging` и loopback API:

    cd "$SERVER_ROOT"
    nohup bash tools/staging_overnight_check.sh </dev/null >/dev/null 2>&1 &
    echo $!

Проверить ход monitor можно без остановки процесса:

    tail -f "$STAGING_ROOT/logs/staging-overnight-check.log"
    python3 -m json.tool "$STAGING_ROOT/logs/staging-overnight-result.json"

Result-файл имеет status `RUNNING`, `PASS`, `FAIL`, `INTERRUPTED` или `ERROR`. Скрипт не допускает
второй одновременный экземпляр, ограничивает размер лога, не перезапускает сервисы, не удаляет
контейнеры или volumes и после 24 часов завершает работу с кодом `0` только при непрерывном PASS.
Перезагрузка Windows/WSL не возобновляет процесс автоматически и не может считаться непрерывным soak.

Во время soak периодически выполнять Compose `ps`, `/ready` и `/health`.

    docker compose --env-file "$STAGING_ROOT/secrets/staging.env" \
      -f docker-compose.yml -f docker-compose.staging.yml \
      --project-name senior-pomidor-staging --profile observability ps
    curl --fail http://127.0.0.1:18000/ready
    curl --fail http://127.0.0.1:18000/health

Прервать soak при crash, unrecovered unhealthy state, бесконечном spool/resource growth,
count mismatch, duplicate rows, privacy leak или внешней отправке.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Monitor завершил непрерывные 24 часа со статусом `PASS`; Core/Edge health и telemetry freshness не прерывались |
| Переход | Только финальный `PASS`; sleep/reboot, `FAIL`, `ERROR`, `INTERRUPTED` или `NOT_RUN` блокирует шаг 11 |

## 10.1. Проверить PostgreSQL и Grafana во время soak

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Midpoint и final read-only snapshots подтверждают persistence, freshness, deduplication и Grafana reads |
| Переход | Выполнить обе группы проверок ниже; каждая должна завершиться `PASS` |

`staging_overnight_check.sh` проверяет состояние контейнеров, `/ready`, `/health`, Edge-связность и
свежесть telemetry, но сам по себе не доказывает, что PostgreSQL продолжает принимать новые записи,
что нет дублей `record_id`, а Grafana успешно выполняет запросы к PostgreSQL. Выполните эти read-only
проверки на середине soak и повторите их после 24 часов. Не используйте production credentials или paths.

### PostgreSQL

Проверить primary-состояние, размер БД, свежесть telemetry и отсутствие дублей:

    docker exec senior-pomidor-staging-postgres-1 \
      sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -x -c "SELECT now() AS checked_at_utc, current_database() AS database_name, pg_is_in_recovery() AS is_in_recovery, pg_size_pretty(pg_database_size(current_database())) AS database_size;"'

    docker exec senior-pomidor-staging-postgres-1 \
      sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -x -c "SELECT count(*) AS total_events, count(*) FILTER (WHERE timestamp_utc >= now() - interval '\''10 minutes'\'') AS events_last_10m, max(timestamp_utc) AS latest_event_utc, max(received_at) AS latest_received_utc FROM telemetry_events;"'

    docker exec senior-pomidor-staging-postgres-1 \
      sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -x -c "SELECT count(*) AS pod_readings_last_10m, max(timestamp_utc) AS latest_pod_reading_utc FROM telemetry_pod_readings_flat WHERE timestamp_utc >= now() - interval '\''10 minutes'\'';"'

    docker exec senior-pomidor-staging-postgres-1 \
      sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -x -c "SELECT coalesce(sum(event_count - 1), 0) AS duplicate_record_rows FROM (SELECT record_id, count(*) AS event_count FROM telemetry_events WHERE record_id IS NOT NULL GROUP BY record_id HAVING count(*) > 1) duplicates;"'

Ожидаемые условия:

- `is_in_recovery` равен `f`;
- `events_last_10m` больше нуля;
- `latest_event_utc` и `latest_pod_reading_utc` не старше 10 минут;
- `duplicate_record_rows` равен `0`;
- размер БД и количество строк растут постепенно, без резкого скачка.

Зафиксируйте значения на середине soak и сравните их с финальным snapshot. Это доказывает реальную
цепочку Edge -> MQTT/HTTP -> Core -> PostgreSQL, а не только healthcheck контейнера.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Primary доступен; telemetry свежая; duplicate `record_id` отсутствуют; финальные counts не меньше midpoint counts |
| Переход | Все четыре database evidence отмечены `PASS` |

### Grafana

Сначала загрузить credentials только из защищённого staging env-файла; не печатать файл и значения:

    set -a
    source "$STAGING_ROOT/secrets/staging.env"
    set +a
    export STAGING_GRAFANA_URL="http://127.0.0.1:$STAGING_GRAFANA_PUBLISHED_PORT"

Проверить саму Grafana:

    curl --fail --silent --show-error "$STAGING_GRAFANA_URL/api/health" | jq .

Проверить PostgreSQL datasource:

    curl --fail --silent --show-error \
      -u "$STAGING_GRAFANA_ADMIN_USER:$STAGING_GRAFANA_ADMIN_PASSWORD" \
      "$STAGING_GRAFANA_URL/api/datasources/uid/senior-pomidor-postgres" \
      | jq '{name, type, uid, url, database, readOnly}'

Проверить оба dashboard и provisioned alert rules:

    for uid in senior-pomidor-telemetry senior-pomidor-edge-reliability; do
      curl --fail --silent --show-error \
        -u "$STAGING_GRAFANA_ADMIN_USER:$STAGING_GRAFANA_ADMIN_PASSWORD" \
        "$STAGING_GRAFANA_URL/api/dashboards/uid/$uid" \
        | jq --arg uid "$uid" '{expected_uid:$uid, actual_uid:.dashboard.uid, title:.dashboard.title, panels:(.dashboard.panels|length)}'
    done

    curl --fail --silent --show-error \
      -u "$STAGING_GRAFANA_ADMIN_USER:$STAGING_GRAFANA_ADMIN_PASSWORD" \
      "$STAGING_GRAFANA_URL/api/v1/provisioning/alert-rules" \
      | jq '[.[] | {title, uid, state, health}]'

Проверить не только конфигурацию datasource, но и реальный read query через Grafana. Используйте
`jq` для генерации JSON, чтобы переносы строк не ломали JSON и не возникала ошибка `400`:

    sql="SELECT device_id, max(timestamp_utc) AS latest_telemetry_utc, count(*) AS events_last_hour FROM telemetry_events WHERE timestamp_utc >= now() - interval '1 hour' GROUP BY device_id ORDER BY device_id"
    payload="$(jq -n --arg sql "$sql" '{queries:[{refId:"A",datasource:{type:"postgres",uid:"senior-pomidor-postgres"},rawSql:$sql,format:"table"}],from:"now-1h",to:"now"}')"
    curl --fail --silent --show-error \
      -u "$STAGING_GRAFANA_ADMIN_USER:$STAGING_GRAFANA_ADMIN_PASSWORD" \
      -H 'Content-Type: application/json' \
      -X POST "$STAGING_GRAFANA_URL/api/ds/query" \
      --data-binary "$payload" \
      | jq .

Ожидаемый результат Grafana:

- `/api/health` возвращает HTTP 200 и `database: "ok"`;
- datasource возвращает HTTP 200, `uid: "senior-pomidor-postgres"`;
- оба dashboard возвращают HTTP 200 и ненулевое число panels;
- alert rules присутствуют и не имеют неожиданных `error`/`failed` состояний;
- `/api/ds/query` возвращает результат для `edge-staging-ubuntu-01`, свежий `latest_telemetry_utc`
  и `events_last_hour > 0`.

Если используется heredoc вместо `jq -n`, строка `SQL`/`JSON` должна начинаться строго с первой
позиции и быть отделена от `<<'SQL'`/`<<'JSON'` переводом строки. `401` означает отсутствие
Grafana authentication, а `400` обычно означает malformed JSON; оба результата не являются PASS.

Зафиксируйте результаты как отдельные evidence:

    PASS database-primary-and-size
    PASS database-telemetry-fresh
    PASS database-pod-readings-fresh
    PASS database-no-duplicate-record-ids
    PASS grafana-health
    PASS grafana-postgres-datasource
    PASS grafana-dashboards
    PASS grafana-alert-rules
    PASS grafana-read-query

Не выполняйте `UPDATE`, `DELETE`, `VACUUM FULL`, `docker compose down -v` или любые действия,
изменяющие staging volumes.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | PostgreSQL и все Grafana read-only проверки имеют `PASS`; telemetry свежая; alerts без unexpected error |
| Переход | Все девять перечисленных evidence имеют `PASS`; иначе soak/rehearsal не завершён |

## 11. Exact-bundle rehearsal и rollback

    (
      set -euo pipefail
      cd "$SERVER_ROOT"
      : "${CORE_SHA:?Complete candidate checks first}"
      read -r -p 'Published release version for this Core SHA (vX.Y.Z): ' RELEASE_VERSION
      [[ "$RELEASE_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]

      git fetch origin --tags
      test "$(git cat-file -t "refs/tags/$RELEASE_VERSION")" = tag
      test "$(git rev-list -n 1 "refs/tags/$RELEASE_VERSION")" = "$CORE_SHA"
      RELEASE_JSON="$(gh release view "$RELEASE_VERSION" \
        --repo cracketus/senior-pomidor-server \
        --json tagName,isDraft,isPrerelease)"
      jq -e --arg version "$RELEASE_VERSION" \
        '.tagName == $version and (.isDraft | not) and (.isPrerelease | not)' \
        <<<"$RELEASE_JSON" >/dev/null

      mkdir -p "$STAGING_ROOT/dist"
      BUNDLE_DIR="$(mktemp -d "$STAGING_ROOT/dist/release-$RELEASE_VERSION.XXXXXX")"
      BUNDLE="$BUNDLE_DIR/senior-pomidor-runtime-$RELEASE_VERSION.tar.gz"
      gh release download "$RELEASE_VERSION" \
        --repo cracketus/senior-pomidor-server \
        --pattern "senior-pomidor-runtime-$RELEASE_VERSION.tar.gz*" \
        --dir "$BUNDLE_DIR"
      test -f "$BUNDLE" -a -f "$BUNDLE.sha256"

      EXPECTED_BUNDLE_SHA="$(awk '{print $1}' "$BUNDLE.sha256")"
      ACTUAL_BUNDLE_SHA="$(sha256sum "$BUNDLE" | awk '{print $1}')"
      [[ "$EXPECTED_BUNDLE_SHA" =~ ^[0-9a-f]{64}$ ]]
      test "$ACTUAL_BUNDLE_SHA" = "$EXPECTED_BUNDLE_SHA"
      test "$(tar -xOf "$BUNDLE" './VERSION')" = "$RELEASE_VERSION"
      test "$(tar -xOf "$BUNDLE" './REVISION')" = "$CORE_SHA"
      tar -tzf "$BUNDLE" >"$BUNDLE_DIR/contents.txt"
      if grep -Eq '(^|/)(app|migrations)/|\.py$' "$BUNDLE_DIR/contents.txt"; then
        echo 'Runtime bundle unexpectedly contains Python source' >&2
        exit 1
      fi
      printf 'PASS release_version=%s core_sha=%s runtime_bundle_sha256=%s bundle=%s\n' \
        "$RELEASE_VERSION" "$CORE_SHA" "$ACTUAL_BUNDLE_SHA" "$BUNDLE"
    )

Используйте в rehearsal только bundle из пути `bundle=...`, напечатанного строкой `PASS`, без
локального rebuild.
Если release tag ещё не назначен этому SHA, GitHub Release или любой asset отсутствует, либо tag,
checksum, `VERSION` и `REVISION` не согласованы, оставьте exact-bundle rehearsal `NOT_RUN` и остановитесь.

Rollback — только application-only: вернуть предыдущий approved immutable Core application image. Он
не меняет и не останавливает PostgreSQL, Grafana или Ollama, не удаляет volumes или evidence и не
использует `down -v`. После rollback проверить readiness, health, ingestion, latest/history reads,
старые durable rows и новый Edge payload.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Published bundle checksum, `VERSION`, `REVISION` и Core identity совпадают; application-only rollback сохраняет data и восстанавливает health/ingestion/read paths |
| Переход | Exact-bundle rehearsal и rollback evidence имеют `PASS`; любой отсутствующий release asset или identity mismatch блокирует шаг 12 |

## 12. Создать и проверить sanitized evidence

    cd "$SERVER_ROOT"
    REPORT_ID="preprod-$(date -u +%Y%m%d-%H%M%S)-core${CORE_SHA:0:8}-edge${EDGE_SHA:0:8}"
    [[ "$REPORT_ID" =~ ^[a-z0-9][a-z0-9._-]{0,63}$ ]] || exit 1
    test ! -e "docs/release-evidence/$REPORT_ID"
    export REPORT_ID
    mkdir -p "docs/release-evidence/$REPORT_ID"

`REPORT_ID` идентифицирует одну immutable Core/Edge campaign. Не переиспользовать ID после identity drift.

Создать структуру из `NOT_RUN` templates:

    cp tests/fixtures/release_qualification/edge_core_compatibility_report_v1.json \
      "docs/release-evidence/$REPORT_ID/edge-core-compatibility.json"
    cp tests/fixtures/release_qualification/release_validation_v1.json \
      "docs/release-evidence/$REPORT_ID/release-validation.json"

Templates не являются evidence. Заполнять фактическими sanitized значениями только из завершённых
шагов 1–11. Не менять `NOT_RUN` на `PASS` без соответствующего evidence.

Разрешены только:

    docs/release-evidence/<report-id>/edge-core-compatibility.json
    docs/release-evidence/<report-id>/release-validation.json

Не включать passwords, tokens, `.env`, raw telemetry/logs, hostnames, IP addresses, network identifiers,
private paths, process IDs, database dumps или production secrets.

Проверить Edge/Core report:

    python -m tools.release_qualification validate \
      --kind edge-core-compatibility \
      --report "docs/release-evidence/$REPORT_ID/edge-core-compatibility.json" \
      --require-pass \
      --core-sha "$CORE_SHA" --core-image "$CORE_IMAGE" --core-digest "$CORE_DIGEST" \
      --edge-sha "$EDGE_SHA" --edge-image "$EDGE_IMAGE" --edge-digest "$EDGE_DIGEST"

Проверить pre-production report:

    python -m tools.release_qualification validate \
      --kind release-validation --mode preproduction --require-pass \
      --report "docs/release-evidence/$REPORT_ID/release-validation.json" \
      --core-sha "$CORE_SHA" --core-image "$CORE_IMAGE" --core-digest "$CORE_DIGEST" \
      --edge-sha "$EDGE_SHA" --edge-image "$EDGE_IMAGE" --edge-digest "$EDGE_DIGEST"

Ожидаемые gate statuses:

    software-ci: PASS
    docker-compose-e2e: PASS
    cross-repository-staging: PASS
    exact-bundle-rehearsal: PASS
    server-rollout-canary: NOT_RUN
    production-24h-observation: NOT_RUN

Проверка `--mode full` до canary/production должна завершиться ошибкой из-за NOT_RUN.

После успешной локальной проверки и независимого review закоммитить только два report-файла:

    EVIDENCE_BRANCH="evidence/$REPORT_ID"
    git switch -c "$EVIDENCE_BRANCH"
    git add \
      "docs/release-evidence/$REPORT_ID/edge-core-compatibility.json" \
      "docs/release-evidence/$REPORT_ID/release-validation.json"
    test "$(git diff --cached --name-only | wc -l)" -eq 2
    git commit -m "docs: add $REPORT_ID release evidence"
    git push -u origin "$EVIDENCE_BRANCH"
    EVIDENCE_REF="$(git rev-parse HEAD)"
    export EVIDENCE_REF

Workflow принимает branch, tag или commit SHA. Этот runbook требует immutable commit SHA.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Оба validators завершились с кодом `0`; commit содержит только два sanitized report-файла; `EVIDENCE_REF` доступен в origin |
| Переход | `REPORT_ID` совпадает с directory name; оба обязательных preproduction reports проходят `--require-pass`; commit SHA опубликован |

## 13. Запустить GitHub qualification workflow

Откройте:

    https://github.com/cracketus/senior-pomidor-server/actions/workflows/release-qualification.yml

Нажмите `Run workflow` и заполните:

    core_sha:    <CORE_SHA>
    core_image:  <CORE_IMAGE>
    core_digest: <CORE_DIGEST>
    edge_sha:    <EDGE_SHA>
    edge_image:  <EDGE_IMAGE>
    edge_digest: <EDGE_DIGEST>
    evidence_ref: <EVIDENCE_REF — immutable commit SHA из шага 12>
    report_id:    <REPORT_ID — directory name из шага 12>
    mode:         preproduction

Ожидается:

- `system-invariants` — PASS;
- `edge-core-e2e` — PASS;
- `release-validation` — PASS.

Это означает только pre-production qualification, не production readiness.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Jobs `system-invariants`, `edge-core-e2e`, `release-validation` имеют `PASS` для exact identities и evidence commit |
| Переход | Pre-production gate завершён; production/canary остаются `NOT_RUN` до отдельного human approval |

## 14. Финальные ограничения

До отдельного human approval остаются NOT_RUN:

- Edge/Core staging qualification, если evidence не собран;
- 24-hour soak, если не завершён непрерывный период;
- exact-bundle rollback, если не проверен оператором;
- canary;
- production deployment;
- production 24-hour observation.

Нельзя закрывать epic #225 только на основании software CI или synthetic fixtures.

| Поле | Значение |
| --- | --- |
| Ожидаемый результат | Итоговый статус каждого gate записан как `PASS`, `FAIL` или `NOT_RUN`; production operations не выполнялись |
| Переход | Следующего автоматического шага нет; canary начинается только по отдельному approved production plan |
## v0.3.1 Core lifecycle and health qualification

Before release-owner acceptance, verify in the isolated project that the API and MQTT worker share
the project-scoped `worker-health` volume, with read-only API and read-write worker mounts. Exercise
missing, malformed and stale health files and the guarded lifecycle CLI. Confirm a decommissioned
device remains readable, its ingress is retained without reactivation, and it is absent from active-fleet
operator, estimator and export aggregates. Cross-repository Edge discriminator/ACK scenarios remain
`NOT_RUN` here until the accepted #248 report covers the exact Core/Edge pair.
