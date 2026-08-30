# Проверка готовности к production promotion по тикету #189

## Назначение

Эта инструкция описывает проверку кандидата Server/Core перед следующим production-релизом после
эпика #225. Она не относится ретроспективно к `v0.2.4`, не назначает номер следующей версии и не
разрешает production deployment.

Итог проверки — только один из статусов:

- `PASS` — все обязательные программные, pre-production и production-проверки выполнены для одной
  неизменной пары Core/Edge artifacts;
- `FAIL` — хотя бы одна обязательная проверка завершилась ошибкой или обнаружено условие остановки;
- `NOT_RUN` — обязательная проверка не выполнена или доказательство недоступно.

Любой обязательный `FAIL` или `NOT_RUN` блокирует promotion. CI, synthetic fixtures и успешный запуск
контейнеров не заменяют реальные backup/restore, Edge/Core, canary и production evidence.

## Границы и разрешения

До отдельного письменного разрешения владельца production разрешены только локальные, CI,
pre-production и read-only проверки. Эта инструкция сама по себе не разрешает:

- deployment или запись в production;
- чтение, копирование или публикацию production secrets;
- подключение production Edge к staging;
- реальный GPIO или actuator access;
- изменение production database вручную;
- удаление или пересоздание PostgreSQL, Grafana, Ollama, Docker volumes, backup repositories или
  release evidence;
- внешний экспорт во время rehearsal.

Запрещено использовать `docker compose down -v`. Rollback всегда application-only и сохраняет
shared services и durable data.

## Текущий fail-closed статус

Состояние ниже зафиксировано 2026-08-29 и должно быть перепроверено перед началом окна:

| Gate | Тикет | Текущее состояние | Что требуется для `PASS` |
| --- | --- | --- | --- |
| Encrypted 3-2-1 backup | #77 | OPEN | Реализация принята, local и off-site snapshots проверены |
| Clean-host restore/DR | #78 | OPEN | Реальный restore drill уложился в RPO < 24 h и RTO < 4 h |
| Contract compatibility | #84 | OPEN | Есть criterion-to-test mapping и legacy telemetry proof |
| Reliable ingestion | #85 | OPEN | MQTT/HTTP, duplicate, reconnect, failure и read-back paths доказаны |
| Canonical Compose proof | #86 | OPEN | Критерии сопоставлены с `docker-e2e`/qualification; пробелы закрыты |
| Ubuntu host baseline | #185 | OPEN | Фактический host прошёл non-secret host audit |
| SSH/LAN boundary | #186 | OPEN | SSH, listeners, Docker ports и exposure matrix прошли audit |

Promotion нельзя начинать, пока каждый обязательный gate не имеет проверяемого `PASS`. Закрытый
тикет #225 или #260 сам по себе не доказывает прохождение gate: нужны отчёты для точных SHA/digest.

## Где выполнять проверки

| Среда | Разрешённая работа |
| --- | --- |
| Рабочая машина / CI | Tests, schemas, validators, `docker-e2e`, проверка artifacts и sanitized reports |
| Изолированный staging | Реальные Core и Edge artifacts, failure scenarios, 24-hour soak, rehearsal и rollback |
| Clean/disposable host | Restore drill из реального release-candidate backup |
| Production host | Сначала read-only baseline; deployment только после отдельного approval |
| Один production Edge | Canary только после Core rollout и отдельного approval |

Pre-production порядок и команды описаны в
[`POST_MERGE_PREPRODUCTION_QUALIFICATION.md`](POST_MERGE_PREPRODUCTION_QUALIFICATION.md), граница
staging — в [`STAGING.md`](STAGING.md), production host — в [`UBUNTU_HOST.md`](UBUNTU_HOST.md).

## 1. Открыть запись проверки

До запуска gate создайте приватную operator record и зафиксируйте:

```text
release_version: <назначается при promotion>
report_id: <bounded-lowercase-id>
window_start_utc: <YYYY-MM-DDTHH:MM:SSZ>
core_git_sha: <40 lowercase hex>
core_image: <immutable ref ending in @sha256:...>
core_image_digest: <sha256:64 lowercase hex>
core_bundle_sha256: <64 lowercase hex>
edge_git_sha: <40 lowercase hex>
edge_image: <immutable ref ending in @sha256:...>
edge_image_digest: <sha256:64 lowercase hex>
previous_core_image: <previous immutable ref>
operator: <private change-record identity>
approver: <private change-record identity>
```

После начала проверки нельзя пересобирать или подменять artifacts. При любом identity drift текущая
проверка получает `FAIL`; для новой пары artifacts открывается новая запись и все gate выполняются
заново.

В репозиторий разрешено добавлять только два sanitized artifact:

```text
docs/release-evidence/<report-id>/edge-core-compatibility.json
docs/release-evidence/<report-id>/release-validation.json
```

Не коммитьте `.env`, credentials, hostnames, addresses, network identifiers, private paths, raw
payloads/logs, dumps, process/boot IDs или private error details.

## 2. Проверить immutable identity, CI и branch protection

На чистом checkout Core:

```bash
git rev-parse HEAD
git status --short --branch
sha256sum senior-pomidor-runtime-vX.Y.Z.tar.gz
sha256sum --check senior-pomidor-runtime-vX.Y.Z.tar.gz.sha256
docker buildx imagetools inspect "${CORE_IMAGE}" --raw
docker pull "${CORE_IMAGE}"
docker image inspect "${CORE_IMAGE}" \
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
```

Требуется:

- checkout SHA, OCI revision, bundle metadata и Core report указывают на один `CORE_SHA`;
- image reference оканчивается заявленным immutable digest;
- manifest содержит одобренные платформы кандидата;
- для точного SHA прошли `test`, `quality`, `security`, `docker-e2e` и RC workflow;
- branch protection требует точное имя статуса `docker-e2e`;
- успешный run `docker-e2e` относится к проверяемому candidate SHA, а не к другой ветке или rebuild.

Повторите identity-проверку для Edge artifact. Git SHA нельзя использовать вместо image digest.

Результат шага `PASS` только при полном совпадении identities и required checks. Отсутствующий доступ
к CI/registry — `NOT_RUN`, несовпадение — `FAIL`.

## 3. Закрыть contract и ingestion gates

Подготовьте criterion-to-test/CI mapping для #84, #85 и #86. Для каждого критерия укажите точный
test, workflow job и evidence reference либо отдельный ограниченный follow-up.

Минимально должны быть доказаны:

- telemetry v1 и v2, включая payload без `record_id` в документированном one-release-cycle window;
- MQTT и HTTP ingestion через реальные transport boundaries;
- first delivery, identical replay, lost acknowledgement, cross-transport duplicate и conflict paths;
- reconnect, malformed message и transient storage failure;
- отсутствие unintended duplicate scientific rows;
- persistence и latest/history read-back;
- migration/readiness ordering, missing dependency и recovery;
- bounded diagnostic output без database details и secrets.

Validator-only test не является доказательством transport/persistence/read path. Если release diff
получил новую migration или destructive data change, заново активируйте #83. Если изменилось
State Estimator ownership/decision behavior, заново активируйте #87.

## 4. Принять pre-production evidence

Для точной пары Core/Edge должны быть `PASS`:

- system invariants для реализованных сценариев;
- реальный Edge/Core compatibility report;
- все десять cross-repository scenarios из #260;
- runtime transitions четырёх edge-reliability alerts;
- 24-hour staging soak;
- exact-bundle rehearsal;
- application-only rollback rehearsal к предыдущему immutable Core image.

Soak получает `FAIL` при crash, unrecovered unhealthy state, unbounded resource/spool growth, silent
durable loss, неожиданном duplicate, freshness/privacy mismatch, count mismatch или внешнем export.

Проверьте отчёты локально:

```bash
python -m tools.release_qualification validate \
  --kind edge-core-compatibility \
  --report "docs/release-evidence/${REPORT_ID}/edge-core-compatibility.json" \
  --require-pass \
  --core-sha "${CORE_SHA}" --core-image "${CORE_IMAGE}" --core-digest "${CORE_DIGEST}" \
  --edge-sha "${EDGE_SHA}" --edge-image "${EDGE_IMAGE}" --edge-digest "${EDGE_DIGEST}"

python -m tools.release_qualification validate \
  --kind release-validation --mode preproduction --require-pass \
  --report "docs/release-evidence/${REPORT_ID}/release-validation.json" \
  --core-sha "${CORE_SHA}" --core-image "${CORE_IMAGE}" --core-digest "${CORE_DIGEST}" \
  --edge-sha "${EDGE_SHA}" --edge-image "${EDGE_IMAGE}" --edge-digest "${EDGE_DIGEST}"
```

Synthetic или server-only compatibility report остаётся `NOT_RUN` и блокирует promotion.

## 5. Проверить backup и clean-host restore

Этот gate выполняется в порядке `#76 DONE -> #77 -> #78`.

### 5.1 Backup

Подтвердите для release candidate:

- complete backup содержит PostgreSQL, photos, estimator private state, MQTT persistence, deployment
  metadata и Grafana state, если она применима;
- manifest и все checksums валидны;
- последний verified snapshot моложе 24 часов;
- encrypted repository на отдельном USB SSD действительно находится на ожидаемом mount;
- snapshot скопирован в независимый S3-compatible repository;
- retention составляет 14 daily, 8 weekly и 12 monthly recovery points;
- weekly integrity check прошёл;
- missing SSD, S3 outage, full repository, bad password и integrity failure видимы оператору;
- отказ off-site destination не удаляет и не инвалидирует успешный local snapshot;
- logs/status не содержат credentials или backup content.

Production source-free bundle использует установленные `backup.sh` и systemd units. Не подменяйте их
source-checkout командой, пока #77 не предоставит эквивалентный проверенный entry point.

### 5.2 Restore drill

На clean/disposable host восстановите выбранный реальный candidate snapshot сначала из одного, затем
в отдельном drill — из другого repository согласно принятой реализации #78. Требуется:

- integrity, manifest, checksums, components, revision и schema проверены до изменения target;
- target изначально пуст; production deployment не используется;
- восстановлены PostgreSQL и все применимые file-backed components;
- Alembic завершился успешно;
- `/health`, `/ready`, devices, representative telemetry, photo consistency/download, estimator output,
  MQTT reachability и optional Grafana прошли;
- counts и representative hashes совпали с backup baseline;
- возраст восстановленной точки < 24 h, полное время восстановления < 4 h;
- failure path оставляет понятную recovery instruction и не заявляет успех.

Checksum verification без restore drill — `NOT_RUN`, не `PASS`.

## 6. Проверить Ubuntu host и network boundary

Сначала выполните принятый non-destructive checker из #185, затем network/security audit из #186.
Сохраните raw output только в защищённой operator record; в release evidence перенесите bounded status.

### 6.1 Host baseline

Требуется `PASS` для:

- поддерживаемого Ubuntu Server LTS и required packages;
- Docker daemon и Compose;
- service account, groups, `/srv/...` layout, ownership и restrictive secret permissions;
- NTP и synchronized clock;
- UTC machine timestamps и `Europe/Vienna` только для operator schedules/displays;
- automatic security updates;
- automatic reboot disabled по умолчанию и видимого `reboot-required`;
- repository-owned systemd services/timers;
- diagnostic output без secrets.

Любое отклонение должно иметь явное human approval до promotion.

### 6.2 SSH и exposure

Не отключайте password/root access, пока не проверены новая key session и emergency recovery path.
После безопасного применения политики требуется:

- verified key access работает;
- `PermitRootLogin no` и password authentication disabled;
- `.ssh`/`authorized_keys` имеют безопасные ownership/mode;
- audit не обнаружил private-key material и не вывел key content;
- каждый listening socket и Docker-published port сопоставлен approved exposure matrix;
- SSH доступен только approved admin/LAN sources;
- API и MQTT доступны только требуемым LAN/Edge paths;
- PostgreSQL и Ollama не доступны из LAN/public network по умолчанию;
- нет unsolicited router/NAT forwarding и intentional public exposure.

Не расширяйте firewall как способ скрыть application defect. Проверяйте по слоям: link, IP, route,
DNS, TCP port, protocol, application health.

## 7. Зафиксировать pre-change production baseline

Шаг read-only. До отдельного deployment approval запишите:

- active release и immutable image digest;
- `/health`, `/ready` и node-scoped health summary;
- API/MQTT/State Estimator worker freshness;
- bounded representative database counts и photo consistency status;
- actual listeners и published ports относительно exposure matrix;
- backup snapshot ID, verification time и freshness;
- состояние scheduled backup timers;
- отсутствие unexpected external-export activation.

Пример read-only health checks с одобренного operator endpoint:

```bash
curl --fail --silent --show-error "${CORE_BASE_URL}/health"
curl --fail --silent --show-error "${CORE_BASE_URL}/ready"
curl --fail --silent --show-error \
  "${CORE_BASE_URL}/health/summary?node_id=${CANARY_EDGE_ID}"
```

Не вставляйте raw responses в публичный или committed report: перенесите только разрешённые статусы,
counts и bounded references.

## 8. Production rollout и один Edge canary

Выполнять только после отдельного human approval и подтверждения шагов 1–7.

1. Разверните Core первым из проверенного runtime bundle без rebuild.
2. Не обновляйте остальные Edge instances.
3. Проверьте candidate SHA/digest, `/health`, `/ready`, worker freshness и migration revision.
4. Отправьте одну canary observation через реальный Edge и проверьте путь
   `Edge -> MQTT/HTTP -> persistence -> latest/history API`.
5. Повторите тот же `record_id` и подтвердите duplicate ACK без второй scientific row.
6. Проверьте чтение historical telemetry и representative photos.
7. После стабильного Core обновите ровно один одобренный Edge canary.
8. Наблюдайте не менее 60 минут и двух freshness windows.

Canary получает `PASS` только при совпадающих generated/persisted/read-back counts, отсутствии missing
observations и unintended duplicates, корректных health/alert transitions и сохранённой privacy boundary.
CI не заменяет этот шаг.

## 9. Abort и application-only rollback

Немедленно остановите promotion при:

- любом required `FAIL` или `NOT_RUN`;
- identity или checksum mismatch;
- backup/restore mismatch или backup старше 24 часов;
- readiness, migration или worker freshness failure;
- unexpected listener, broad bind или credential exposure;
- data loss, count mismatch, duplicate scientific row или ingestion rejection;
- stale/future/unknown evidence, ошибочно представленном как healthy;
- Edge/Core incompatibility;
- privacy violation или external-export activation;
- crash/restart loop или unbounded spool/resource growth.

Rollback возвращает только предыдущий immutable application image через отдельно одобренную процедуру.
Не откатывайте additive migration, не удаляйте telemetry и не останавливайте/пересоздавайте shared
PostgreSQL, Grafana или Ollama. После rollback повторите шаг 7 и canary ingestion/read checks. Любые
записи, принятые после cutover boundary, должны быть сохранены и согласованы до следующей попытки.

Если exact rollback command для текущего layout не утверждён и не прошёл rehearsal, promotion остаётся
`NOT_RUN`: не изобретайте команду во время incident.

## 10. Production observation и следующий backup

После успешного canary наблюдайте точную Core/Edge пару не менее 24 часов. Зафиксируйте начало,
середину и конец интервала. Требуется:

- Core и workers остаются healthy/current без restart loop;
- MQTT/HTTP ingestion, persistence и reads продолжаются;
- generated/persisted/read-back counts согласованы;
- нет unintended duplicates, freshness, privacy или alert mismatch;
- spool/backlog возвращается к bounded steady state;
- historical telemetry и photos остаются читаемыми;
- listeners/exposure не изменились;
- следующий scheduled backup завершился успешно в local и off-site destinations и прошёл verification.

Пропуск scheduled backup, разрыв непрерывного 24-hour interval или недоступный Edge evidence — `NOT_RUN`.

## 11. Финальная валидация

После добавления sanitized canary и production evidence выполните full validation:

```bash
python -m tools.release_qualification validate \
  --kind release-validation --mode full --require-pass \
  --report "docs/release-evidence/${REPORT_ID}/release-validation.json" \
  --core-sha "${CORE_SHA}" --core-image "${CORE_IMAGE}" --core-digest "${CORE_DIGEST}" \
  --edge-sha "${EDGE_SHA}" --edge-image "${EDGE_IMAGE}" --edge-digest "${EDGE_DIGEST}"
```

Закрывать #189 можно только когда:

- все обязательные зависимые gates приняты;
- validator завершился с кодом `0` и overall `PASS`;
- independent reviewer подтвердил identities, evidence scope, counts, privacy и rollback;
- нет required `FAIL`, `NOT_RUN`, synthetic substitution или unresolved deviation;
- operator подтвердил, что предыдущий immutable image и recovery material сохранены.

## Шаблон журнала gate

| Gate | Status | UTC interval | Evidence reference | Operator/reviewer note |
| --- | --- | --- | --- | --- |
| Immutable Core/Edge identity | NOT_RUN | — | — | — |
| Required CI and branch protection | NOT_RUN | — | — | — |
| #84 contract compatibility | NOT_RUN | — | — | — |
| #85 ingestion failure paths | NOT_RUN | — | — | — |
| #86 canonical Compose proof | NOT_RUN | — | — | — |
| Real Edge/Core compatibility | NOT_RUN | — | — | — |
| 24-hour staging soak | NOT_RUN | — | — | — |
| Exact-bundle rollback rehearsal | NOT_RUN | — | — | — |
| #77 backup and freshness | NOT_RUN | — | — | — |
| #78 clean-host restore | NOT_RUN | — | — | — |
| #185 host baseline | NOT_RUN | — | — | — |
| #186 SSH/LAN exposure | NOT_RUN | — | — | — |
| Core-first rollout | NOT_RUN | — | — | — |
| One-Edge canary | NOT_RUN | — | — | — |
| Production rollback verification | NOT_RUN | — | — | — |
| 24-hour production observation | NOT_RUN | — | — | — |
| Next scheduled backup | NOT_RUN | — | — | — |
| Full report validation | NOT_RUN | — | — | — |

## Известные failure patterns, применимые к проверке

- `SP-FAIL-001`: неверные Compose env/image interpolation;
- `SP-FAIL-002`: running container без свежего functional output;
- `SP-FAIL-003`: rehearsal использует production paths/ports или включает export;
- `SP-FAIL-004`: rehearsal и release используют разные artifacts;
- `SP-FAIL-005`: наличие backup ошибочно принято за recovery proof;
- `SP-FAIL-006`: Edge connectivity loss ошибочно диагностирован как Core defect;
- `SP-FAIL-011`: validator fixture прошёл, а real transport path — нет;
- `SP-FAIL-016`: SSH key material раскрыт или administrative access сломан;
- `SP-FAIL-017`: network-layer failure ошибочно диагностирован как application defect.

## Связанные документы

- [`OPERATIONS.md`](OPERATIONS.md) — release, backup и operational checks;
- [`CONTRACTS.md`](CONTRACTS.md) — telemetry, read APIs и release evidence contracts;
- [`POST_MERGE_PREPRODUCTION_QUALIFICATION.md`](POST_MERGE_PREPRODUCTION_QUALIFICATION.md) — подробная
  pre-production процедура;
- [`STAGING.md`](STAGING.md) — изоляция persistent staging;
- [`UBUNTU_HOST.md`](UBUNTU_HOST.md) — production topology и shared-service boundary;
- [`MIGRATION_WINDOWS_TO_UBUNTU.md`](MIGRATION_WINDOWS_TO_UBUNTU.md) — data-preserving cutover/rollback
  principles;
- [`release-evidence/README.md`](release-evidence/README.md) — правила sanitized evidence.
