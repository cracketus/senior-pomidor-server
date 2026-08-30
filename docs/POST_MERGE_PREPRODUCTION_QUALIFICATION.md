# Post-merge pre-production qualification

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

## Дорожная карта участка вокруг эпика #225

| Этап | Что доказывает | Где выполняется | Статус/результат |
| --- | --- | --- | --- |
| #225 foundation | telemetry, persistence, reads, reliability contracts | server CI + local tests | реализовано |
| #247 / PR #268 | Docker E2E, evidence schemas, invariant checks, fail-closed workflow | laptop + GitHub CI | реализовано |
| #260 / PR #270 | Core SHA-only RC, staging boundary, preproduction/full validator | laptop + GitHub CI | реализовано |
| Edge RC | immutable Edge image, spool/retry/watchdog paths, Edge/Core compatibility | Edge repo + Edge node | требует проверки |
| Pre-production qualification | 10 cross-repository scenarios, 24h soak, exact bundle, rollback | isolated laptop rehearsal или отдельный staging host | следующий этап |
| Canary | один production Edge после Core rollout | production server + production Edge | NOT_RUN, human approval |
| Production observation | стабильность после canary и rollback | production | NOT_RUN, human approval |

Результат pre-production не закрывает #225 полностью: canary, production rollout и 24-hour production
observation остаются отдельными этапами.

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

## Как пользоваться

Работайте блоками сверху вниз. После каждого блока проверяйте ожидаемый результат.

Если результат не совпал: STOP. Не переходить к следующему шагу.

Запрещено:

- `docker compose down -v`;
- использовать production `.env`, paths, volumes или Compose project;
- включать Grafana Cloud export;
- выполнять команды против GPIO/актуаторов;
- вручную менять production database.

## Текущий статус предусловий

### Server repository

| Предусловие | Статус |
| --- | --- |
| PR #270 влит в main | PASS |
| Merge SHA | `2ba13b784e96a200a9f06462e728e28371d41aa9` |
| Approved brief #260 | PASS |
| Core RC workflow и staging controller | PASS |
| Server tests | PASS: `483 passed, 3 skipped` |
| Bandit и pip-audit | PASS |
| Staging Compose rendering | PASS |
| GitHub CI и GHCR artifact | NOT VERIFIED: GitHub API ранее вернул 401 |
| Docker на локальной Windows машине | NOT AVAILABLE: нет доступа к Docker daemon |

### Edge repository

Edge checkout в текущей рабочей среде отсутствует. Не подтверждены:

- Edge SHA `76c36179edceaedde454d8229b7ec814adebf628`;
- Edge RC digest и multi-platform manifest;
- Edge OCI revision и CI;
- staging identity `edge-staging-*`;
- container `senior-pomidor-edge-staging`;
- безопасный fault injection для watchdog/spool/replay.

Не считать эти пункты PASS без реального Edge artifact или CI evidence.

## 1. Проверить server merge и CI

Откройте:

    https://github.com/cracketus/senior-pomidor-server/actions

Для merge SHA `2ba13b784e96a200a9f06462e728e28371d41aa9` jobs должны быть PASS:

- `test`
- `quality`
- `security`
- `docker-e2e`
- `core-release-candidate`

На server checkout:

    cd /path/to/senior-pomidor-server
    git checkout main
    git pull --ff-only origin main
    git rev-parse HEAD
    git status --short --branch

Ожидается полный merge SHA и чистое дерево.

## 2. Получить Core RC artifact

Скачайте artifact `senior-pomidor.core.release-candidate.v1` из job `core-release-candidate`.

    jq . senior-pomidor.core.release-candidate.v1.json
    export CORE_SHA="$(jq -r '.git_sha' senior-pomidor.core.release-candidate.v1.json)"
    export CORE_IMAGE="$(jq -r '.image_ref' senior-pomidor.core.release-candidate.v1.json)"
    export CORE_DIGEST="$(jq -r '.image_digest' senior-pomidor.core.release-candidate.v1.json)"
    test "$CORE_SHA" = "2ba13b784e96a200a9f06462e728e28371d41aa9"
    test "$CORE_IMAGE" = *"@$CORE_DIGEST"
    test "$CORE_DIGEST" =~ ^sha256:[0-9a-f]{64}$
    jq -e '.platforms == ["linux/amd64", "linux/arm64"]' \
      senior-pomidor.core.release-candidate.v1.json

Проверить registry manifest и OCI revision:

    docker buildx imagetools inspect "$CORE_IMAGE" --raw \
      | jq '[.manifests[] | .platform | "\(.os)/\(.architecture)"]'
    docker pull "$CORE_IMAGE"
    docker image inspect "$CORE_IMAGE" \
      --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'

Последняя команда должна вывести полный CORE_SHA.

## 3. Проверить Edge repository

В Edge checkout:

    cd /path/to/senior-pomidor-edge
    git fetch --all --tags
    git checkout 76c36179edceaedde454d8229b7ec814adebf628
    git rev-parse HEAD
    git status --short

Должен быть SHA:

    76c36179edceaedde454d8229b7ec814adebf628

Проверьте Edge CI для этого SHA и получите Edge RC artifact. Digest нельзя вычислять из Git SHA.

    export EDGE_SHA=76c36179edceaedde454d8229b7ec814adebf628
    export EDGE_IMAGE='immutable Edge image ref из artifact'
    export EDGE_DIGEST='sha256:... из artifact'
    test "$EDGE_IMAGE" = *"@$EDGE_DIGEST"
    test "$EDGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$
    docker pull "$EDGE_IMAGE"
    docker image inspect "$EDGE_IMAGE" \
      --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'

Ожидается OCI revision `76c36179edceaedde454d8229b7ec814adebf628`.

Edge maintainer дополнительно подтверждает staging identity, MQTT topic prefix, container name,
interop network и безопасные software-only fault paths. Недоступный Edge path остаётся NOT_RUN.

### Что делать с production Edge node

На production Edge node разрешена только read-only проверка текущей версии и health. Не подключайте
его к `senior-pomidor-staging-interop`, не переименовывайте production identity в `edge-staging-*`
и не направляйте его telemetry в staging без отдельного human-approved maintenance window.

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
    git checkout main
    git pull --ff-only origin main
    test "$(git rev-parse HEAD)" = "2ba13b784e96a200a9f06462e728e28371d41aa9"

Создать staging data directories:

    mkdir -p "$STAGING_ROOT/data/postgres" \
      "$STAGING_ROOT/data/mosquitto" "$STAGING_ROOT/data/photos" \
      "$STAGING_ROOT/data/estimator-private" "$STAGING_ROOT/data/grafana" \
      "$STAGING_ROOT/secrets"
    chmod 700 "$STAGING_ROOT/data" "$STAGING_ROOT/secrets"

## 5. Подготовить env и MQTT credentials

    cp deploy/senior-pomidor-staging.env.example \
      "$STAGING_ROOT/secrets/staging.env"
    chmod 600 "$STAGING_ROOT/secrets/staging.env"
    nano "$STAGING_ROOT/secrets/staging.env"

Если файл был создан или отредактирован в Windows, перед `source` удалите CRLF,
не выводя содержимое файла:

    sed -i 's/\r$//' "$STAGING_ROOT/secrets/staging.env"

Обязательные значения:

    APP_IMAGE=<точный immutable CORE_IMAGE>
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
    chmod 600 "$STAGING_ROOT/secrets/mosquitto.password"

Создать и проверить ACL:

    cp deploy/staging/mosquitto.acl.example "$STAGING_ROOT/secrets/mosquitto.acl"
    chmod 600 "$STAGING_ROOT/secrets/mosquitto.acl"
    grep -F 'topic senior-pomidor-staging/#' "$STAGING_ROOT/secrets/mosquitto.acl"

Не выводить env/password/token в terminal log, issue или evidence.

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
      ghcr.io/cracketus/senior-pomidor-edge@sha256:<64-hex-digest> \
      <40-hex-edge-commit-sha>

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

## 7. Запустить локальный staging-like Core и подключить только dedicated Edge

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

    test -d "$STAGING_ROOT/data/postgres"
    test -f "$STAGING_ROOT/secrets/mosquitto.password"
    test -f "$STAGING_ROOT/secrets/mosquitto.acl"
    test -f "$SERVER_ROOT/deploy/staging/mosquitto.conf"
    test ! -d "$STAGING_ROOT/secrets/mosquitto.password"
    test ! -d "$STAGING_ROOT/secrets/mosquitto.acl"
    test ! -d "$SERVER_ROOT/deploy/staging/mosquitto.conf"
    chmod 700 "$STAGING_ROOT/data/postgres"
    sudo chmod 600 "$STAGING_ROOT/secrets/mosquitto.password" \
      "$STAGING_ROOT/secrets/mosquitto.acl"

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

## 8. Выполнить controller preflight

    cd "$SERVER_ROOT"
    set -a
    source "$STAGING_ROOT/secrets/staging.env"
    set +a
    python -m tools.staging_qualification preflight

Ожидается `status=PASS`, `edge_connected=true`, fixed network и `external_export=disabled`.

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

## 10.1. Проверить PostgreSQL и Grafana во время soak

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

### Grafana

Сначала загрузить credentials только из защищённого staging env-файла; не печатать файл и значения:

    set -a
    source "$STAGING_ROOT/secrets/staging.env"
    set +a

Проверить саму Grafana:

    curl --fail --silent --show-error http://127.0.0.1:13000/api/health | jq .

Проверить PostgreSQL datasource:

    curl --fail --silent --show-error \
      -u "$STAGING_GRAFANA_ADMIN_USER:$STAGING_GRAFANA_ADMIN_PASSWORD" \
      http://127.0.0.1:13000/api/datasources/uid/senior-pomidor-postgres \
      | jq '{name, type, uid, url, database, readOnly}'

Проверить оба dashboard и provisioned alert rules:

    for uid in senior-pomidor-telemetry senior-pomidor-edge-reliability; do
      curl --fail --silent --show-error \
        -u "$STAGING_GRAFANA_ADMIN_USER:$STAGING_GRAFANA_ADMIN_PASSWORD" \
        "http://127.0.0.1:13000/api/dashboards/uid/$uid" \
        | jq --arg uid "$uid" '{expected_uid:$uid, actual_uid:.dashboard.uid, title:.dashboard.title, panels:(.dashboard.panels|length)}'
    done

    curl --fail --silent --show-error \
      -u "$STAGING_GRAFANA_ADMIN_USER:$STAGING_GRAFANA_ADMIN_PASSWORD" \
      http://127.0.0.1:13000/api/v1/provisioning/alert-rules \
      | jq '[.[] | {title, uid, state, health}]'

Проверить не только конфигурацию datasource, но и реальный read query через Grafana. Используйте
`jq` для генерации JSON, чтобы переносы строк не ломали JSON и не возникала ошибка `400`:

    sql="SELECT device_id, max(timestamp_utc) AS latest_telemetry_utc, count(*) AS events_last_hour FROM telemetry_events WHERE timestamp_utc >= now() - interval '1 hour' GROUP BY device_id ORDER BY device_id"
    payload="$(jq -n --arg sql "$sql" '{queries:[{refId:"A",datasource:{type:"postgres",uid:"senior-pomidor-postgres"},rawSql:$sql,format:"table"}],from:"now-1h",to:"now"}')"
    curl --fail --silent --show-error \
      -u "$STAGING_GRAFANA_ADMIN_USER:$STAGING_GRAFANA_ADMIN_PASSWORD" \
      -H 'Content-Type: application/json' \
      -X POST http://127.0.0.1:13000/api/ds/query \
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

## 11. Exact-bundle rehearsal и rollback

    cd "$SERVER_ROOT"
    git checkout 2ba13b784e96a200a9f06462e728e28371d41aa9
    export SOURCE_REVISION=2ba13b784e96a200a9f06462e728e28371d41aa9
    mkdir -p "$STAGING_ROOT/dist"
    bash deploy/scripts/build-runtime-bundle.sh v0.2.5 "$STAGING_ROOT/dist"
    sha256sum "$STAGING_ROOT/dist/senior-pomidor-runtime-v0.2.5.tar.gz"
    tar -tzf "$STAGING_ROOT/dist/senior-pomidor-runtime-v0.2.5.tar.gz" \
      | grep -E '(^|/)(app|migrations)/|\.py$'

Последняя команда не должна вывести source files.

Rollback — только application-only: вернуть immutable application image v0.2.4, не удалять
PostgreSQL/Grafana/Ollama volumes, не использовать `down -v`, проверить readiness, health, ingestion,
latest/history reads, старые durable rows и новый Edge payload.

## 12. Создать и проверить sanitized evidence

    cd "$SERVER_ROOT"
    export REPORT_ID=20260828-core-edge-staging-01
    mkdir -p "docs/release-evidence/$REPORT_ID"

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

## 13. Запустить GitHub qualification workflow

Откройте:

    https://github.com/cracketus/senior-pomidor-server/actions/workflows/release-qualification.yml

Нажмите `Run workflow` и заполните:

    core_sha:    2ba13b784e96a200a9f06462e728e28371d41aa9
    core_image:  точный immutable Core image ref
    core_digest: точный Core digest
    edge_sha:    76c36179edceaedde454d8229b7ec814adebf628
    edge_image:  точный immutable Edge image ref
    edge_digest: точный Edge digest
    evidence_ref: ветка или tag с docs/release-evidence/<REPORT_ID>/
    report_id:    20260828-core-edge-staging-01
    mode:         preproduction

Ожидается:

- `system-invariants` — PASS;
- `edge-core-e2e` — PASS;
- `release-validation` — PASS.

Это означает только pre-production qualification, не production readiness.

## 14. Финальные ограничения

До отдельного human approval остаются NOT_RUN:

- Edge/Core staging qualification, если evidence не собран;
- 24-hour soak, если не завершён непрерывный период;
- exact-bundle rollback, если не проверен оператором;
- canary;
- production deployment;
- production 24-hour observation.

Нельзя закрывать epic #225 только на основании software CI или synthetic fixtures.
