# Implementation Brief: Server #247 — системная верификация Edge → Core

Status: approved

Planner/version: Codex / Feature Planner 1.1.

Approver/date: user, 2026-09-27; explicit request to implement the six-step plan.

Issue/decision: продолжить существующий эпик #247, первым реализовать #248; затем остаток #249, #252, #250, #251. Не создавать дублирующий эпик.

Implementation audit: `20260927-issue-247-coder`, `.ai/agent-runs/20260927-issue-247-coder.json`.

Historical planning snapshot follows. User subsequently created v0.3.1 and authorized all six implementation steps; release/tag instructions below are historical, not pending work. Current delivery evidence is in `docs/implementation-reports/ISSUE-247-cross-repo.md`.

## Problem

Компонентные тесты и Docker E2E Server уже существуют, но в проверенных путях нет завершённого воспроизводимого стенда с реальным приложением Edge, его spool и реальным Core. RC workflow валидирует заранее подготовленное свидетельство, а staging controller оставляет сценарии NOT_RUN. Поэтому зелёный CI нельзя приравнять к доказательству сохранности наблюдений при сбоях между двумя репозиториями.

## Desired outcome

Одна документированная команда и CI запускают точные версии Edge/Core с синтетическими сенсорами, реальными HTTP/MQTT/PostgreSQL и State Estimator; проверяют сохранность, дедупликацию, исходное время наблюдения, восстановление и корректные read models. Результат — воспроизводимый машинный отчёт с идентичностью артефактов и статусом каждого сценария.

## Current behavior and evidence

### Зафиксированный кандидат v0.3.1

- Repository: `cracketus/senior-pomidor-server`.
- Main SHA на момент фиксации: `aea94fd6235f0ecc242e5d1806332715fd7b85ce`.
- Git tree: `2bfff39963cd4757c5e24fbe372a6a5e522b5c8f`.
- Создана удалённая ветка `release/v0.3.1-candidate` на этот SHA. Ветка — удобная ссылка; неизменяемая идентичность кандидата — полный SHA. Защита ветки не настраивалась.
- Включены merged PR #363 (Server) и #364 (документация); согласованный Edge PR #154 был смержен отдельно.
- CI run 36006222795: SUCCESS на этом SHA; jobs test, quality, security, docker-e2e, core-release-candidate — success. RC artifact `senior-pomidor.core.release-candidate.v1`, ID 10810562679, доступен до 2026-10-24T13:39:43Z; его archive digest не является OCI image digest. Это software evidence, не подтверждение production qualification.
- Тег `v0.3.1` и GitHub Release в этой задаче не создавались: пользователь отложил публикацию.
- OCI digest и checksum будущего runtime bundle в данном документе НЕ зафиксированы. Перед квалификацией получить digest из RC artifact этого CI и проверить OCI revision; bundle checksum получить после сборки релиза. Не подставлять исторические значения из roadmap.
- Ранее проверенный Edge SHA: `d14b9367b359ab260bdb62c6364ccd542fbbbd26`; это историческая привязка предыдущей проверки, не новая квалифицированная пара. При начале кампании заново подтвердить Edge SHA/digest и его CI.
- Реальные compatibility/soak/restore/rollback/canary/production evidence для этой пары: NOT_RUN/не представлены в этой проверке.

Когда появится доступ, тег ставится именно на зафиксированный SHA:

```bash
git fetch origin release/v0.3.1-candidate
git cat-file -e aea94fd6235f0ecc242e5d1806332715fd7b85ce^{commit}
git tag -a v0.3.1 aea94fd6235f0ecc242e5d1806332715fd7b85ce -m "Release v0.3.1"
git push origin refs/tags/v0.3.1
```

Перед выполнением убедиться, что локальный и удалённый `v0.3.1` отсутствуют. Существующий тег не перемещать и не перезаписывать. Push запускает release workflow: проверки, публикация образов, GitHub Release и runtime bundle. Новые изменения эпика не добавлять в candidate-ветку. Если в ней нужен исправленный кандидат — отдельно выбрать новый SHA и повторить квалификацию, не смешивая evidence.

### Что уже реализовано

- #246 закрыт; `.github/workflows/ci.yml` содержит `docker-e2e`. Обязательность через branch protection в этой задаче не проверена.
- `tests/test_docker_e2e.py`: реальный стек Core, синтетические payloads, persistence/read/estimator/observability assertions.
- `docs/system-invariants-v1.yaml`, `tools/release_qualification.py`: каталог и строгая валидация evidence уже существуют; создавать заново не нужно.
- `tests/test_temporal_integrity.py`: есть delayed/out-of-order, duplicate receive-time, freshness/skew, DST fold; требуется расширение через настоящий Edge.
- `.github/workflows/release-qualification.yml`: job `edge-core-e2e` читает готовый отчёт из evidence_ref; сам Edge не запускает.
- `tools/staging_qualification.py`: умеет preflight и stop/start API, но сценарии, soak и finalize возвращают NOT_RUN; это заготовка orchestration, не законченный измеритель.
- Edge `docker-compose.integration.yml` использует mock-core; это не заменяет #248.
- #260 закрыт, но его единственный проверенный комментарий явно оставляет runtime qualification NOT_RUN. Закрытый issue не является PASS. На этапе 1 необходимо согласовать отдельную открытую tracking-задачу для отсутствующих свидетельств.

### Почему этот эпик следующий

#247 — P0, напрямую защищает данные и релиз. Он соответствует сентябрьско-октябрьскому этапу `docs/ROADMAP_2027.md` и приоритетам `.ai/planning/PRIORITY_RULES.md`. После него — #302, фиксация Season 1 manifest/replay corpus. World Model, Weather Adapter и Control зависят от достоверной временной и наблюдательной основы. Map/operator UI полезны, но не закрывают этот пробел.

Приложенные архитектура v1, техническое задание и dataset specification рассматриваются как проектные входы, не доказательство наличия runtime. Например, timezone-less timestamp из dataset example нельзя переносить в активный контракт: действующие правила требуют UTC. Научные диапазоны из review v1.3 в этом эпике не переопределяются и не становятся правилами управления. Остальные исторические версии и BOM не нужны для software-only стенда и не аудировались.

## Scope

- Реальный Edge formatter/spool/delivery worker → HTTP/MQTT → Core → PostgreSQL → State Estimator → API/operator projections.
- Изолированный воспроизводимый runner, bounded faults, отчёты с exact SHA/digest, scenario IDs, counts и invariant IDs.
- Восемь базовых сценариев: normal; cross-transport duplicate; outage/spool growth; full drain; lost ACK after commit; restart with pending; fresh while draining; high-VPD derived state.
- Расширение time/compatibility/property coverage без изменения активных wire-контрактов.
- CI разделение: небольшой current/current набор для PR; полная матрица и failure suite для nightly/RC; 24h soak отдельно.

## Out of scope

Автономный Control, World Model, Weather Adapter, новые API/UI функции, реальные GPIO/камера/актуаторы, hardware validation, production deployment, частные данные, публичный dataset export. Не переписывать ingestion и estimator без воспроизведённого дефекта. Не включать весь P2 backlog #247 в первый инкремент.

## Architecture placement

Владельцы: тестовая orchestration/CI и qualification tooling. Расширять `tools/staging_qualification.py` только для его staging boundary; независимый disposable runner разместить отдельным тестовым модулем. Реальное Edge приложение остаётся владельцем spool/retry, Core — durable ingestion и canonical state. Fault proxy разрывает транспорт, но не подделывает бизнес-результат. Executor и физическое управление не затрагиваются.

## Affected contracts and consumers

Сохраняются `senior-pomidor.edge.telemetry.v1/v2`, `state_v1`, `health_summary_v1`, operator v1, `senior-pomidor.system-invariants.v1`, `senior-pomidor.edge-core-compatibility-report.v1`, `senior-pomidor.release-validation.v1`.

- Edge, HTTP/MQTT, PostgreSQL, estimator, private read API, operator views: affected как проверяемые реальные producer/consumer paths; production semantics не меняются.
- Fixtures, evidence validators, CI, operations docs: affected непосредственно.
- Grafana: affected как read-only consumer в расширенной RC acceptance; существующие alert transitions переиспользовать.
- Control/Executor: unaffected, в этом scope не реализуются; будущие actuator invariants остаются NOT_IMPLEMENTED.
- Public export: runtime unaffected, выключен в стенде; отчёт проходит privacy allowlist. Private dataset не экспортируется.
- CLI/TUI: API contract сохраняется; существующие operator contract/client tests обязательны, отдельная переработка интерфейса не нужна.

Идентичность: `record_id` сохраняется через повторную доставку; HTTP accepted/duplicate — авторитетный ACK, MQTT PUBACK не завершает spool. UTC timestamp наблюдения отделён от received/processing time; имена реальных полей брать из активной схемы, не добавлять фиктивный observed_at. RH/влажность — проценты 0..100, confidence — 0..1; missing/null и unknown fields — по существующим версиям схем. Неподдерживаемую версию отклонять явно. Любое изменение evidence shape требует отдельного version/compatibility решения.

## Safety/risk classification

Task classes: pure_software, schema_data_contract, infrastructure_deployment, edge_hardware_integration (fake backend only).
Risk flags: edge_server_compatibility, security_secrets, public_contract; production_availability — для последующей qualification интеграции. data_loss_migration не выбран: миграций данных в scope нет; при появлении пересчитать routing.

Applicable failures:
- SP-FAIL-001: проверять exact Compose config и обязательные параметры.
- SP-FAIL-002: проверять readiness, worker health и свежий функциональный результат после restart.
- SP-FAIL-003: отдельные project/network/paths/credentials, loopback, exporter отсутствует; нельзя доверять только строке external_export=disabled.
- SP-FAIL-004: связывать отчёт с digest/конфигурацией реального тестируемого артефакта.
- SP-FAIL-005: для release rehearsal нужен restore с counts/hashes, не факт существования backup.
- SP-FAIL-006/017: bounded disconnect/refused/timeout/reconnect, различать сеть и application ACK.
- SP-FAIL-009/010/011: реальные consumers, shape/unit boundaries, старые и новые fixtures через транспорт.
- SP-FAIL-014: переносимые пути, закрытие SQLite/log handles и Linux/Windows smoke для runner.

Операционные и физические свидетельства предоставляет сопровождающий проекта отдельно; software CI не подтверждает физические исходы.

## Proposed implementation sequence

| Шаг / PR | Содержание | Проверяемый выход |
|---|---|---|
| 1. #248 skeleton | Сверить текущее имя Edge repo с историческим plant-v2; exact revisions, test fake backend, isolated Compose/runner, budgets/timeouts, CI artifacts; актуализировать tracking qualification | Clean-machine запуск normal delivery, совпадают generated/persisted/readback identities; отрицательный preflight безопасно отказывает |
| 2. #248 recovery | Duplicate HTTP/MQTT; proxy теряет ACK после commit; outage → growth → drain; restart с сохранением spool; fresh during backlog; high VPD | Ноль потерянных durable records и unintended duplicates; spool не ack-нут от PUBACK; bounded recovery |
| 3. #249 + #252 | Привязать сценарии к существующим invariant IDs; delayed/future/stale/order, DST gap+fold, clock correction; не повторять уже готовые unit tests | Positive+negative evidence по каждому применимому инварианту, одинаковый UTC observation identity |
| 4. #250 | Документировать supported window; current/current, previous Edge/current Core, current Edge/rollback Core, legacy fixtures | Матрица exact artifacts; schema-only и full runtime результаты разделены; unsupported отмечен явно |
| 5. #251 | Ограниченные property suites identity/dedup, ordering, normalization/serialization; фиксируемые seed и минимизированные regression fixtures | Воспроизводимые результаты минимум по трём областям; тяжёлый профиль отдельно |
| 6. Qualification handoff | Подключить фактически полученный отчёт к existing release validator; retain logs/counts/config hashes; задокументировать 24h soak/restore/rollback/canary gates | Чистый CI и воспроизводимая software acceptance; реальные отсутствующие gates остаются NOT_RUN |

PR последовательны по зависимостям 1→2→3→4→6; шаг 5 можно выполнить после шага 3. Первый PR ограничен normal path и безопасной изоляцией; он не закрывает #248 целиком. Полный #247 дополнительно содержит #91/#96/#98/#97: после P0/P1 инкремента они остаются отдельным backlog, эпик преждевременно не закрывать.

## Failure modes

Lost ACK: Core durable row существует, Edge повторяет, итог одна строка. Core outage: spool растёт, после восстановления drains без потери identity. Restart: pending переживает процесс, не подменяется in-memory fake. Stale/future/missing: UNKNOWN/quality degradation, не ложный healthy. Неверный digest, counts mismatch, secret/private field, external export или чужой project: abort и FAIL. Timeout: bounded exit, сохранить очищенную диагностику, не проставлять PASS. Cleanup: только ресурсы этой задачи, volumes с evidence сохранять до проверки, никаких shared services.

## Backward compatibility

Не менять telemetry/ACK схемы. Сохранить действующее legacy окно из CURRENT_STATE: discriminator-absent systemd и отсутствие record_id поддерживаются один release cycle. Для #250 явно выбрать поддерживаемые предыдущие релизы и immutable digests; не наследовать v0.2.4 из старого issue без проверки. Core-first rollout, затем Edge canary — отдельная операция. Новые изменения не попадают автоматически в v0.3.1 candidate.

## Testing plan

Сейчас выполнена только read-only проверка и фиксация refs; новые тесты не запускались и код не изменялся.

Required после реализации:

```bash
python -m pytest -q tests/test_release_qualification.py tests/test_staging_qualification.py tests/test_temporal_integrity.py tests/test_contract_fixtures.py tests/test_edge_integration_fixtures.py tests/test_operator_summary.py tests/test_pomidorctl.py tests/test_operator_tui.py
python -m pytest -q
nox -s lint format_check types security deps_audit
git diff --check
```

Перед coding handoff подтвердить названия focused test files. Новую команду cross-repo runner определить и реализовать в PR1; сегодня её нет. Existing Docker suite: `RUN_DOCKER_E2E=1 python -m pytest -q tests/test_docker_e2e.py` — на изолированном Docker runner. Agent Compose operations — только через approved `tools.agent_task` workflow.

Required: exact Compose render, schema validation и serialization round-trip, old/current fixtures через HTTP/MQTT/storage, named consumers, fake-device disconnect/reconnect, negative evidence validation, privacy/bounds, CI artifacts на failure. Проверить независимость проекта и выключенный export.

Manual/deferred: Edge canary, isolated rehearsal/rollback/post-deploy health; backup restore и counts/hashes для будущего release qualification. 24h soak не сокращать до unit test. В этом planning run всё это NOT_RUN. Optional: heavier performance/mutation/fuzzing — отдельные P2/P1 задачи после основной цепочки.

## Observability

Sanitized report: run/scenario/invariant IDs; Edge/Core SHA+digest; UTC interval; generated/persisted/readback unique counts; duplicates/retries/pending/dead letters; bounded recovery timings; PASS/FAIL/NOT_RUN reason. Секреты, raw private payloads, hostnames/locations не сохранять. Fault injection и pipeline failures должны быть видимы в CI; отчёт валидируется существующим fail-closed validator.

## Documentation updates

При реализации: docs/OPERATIONS.md, docs/STAGING.md, docs/CONTRACTS.md при изменении evidence, docs/system-invariants-v1.yaml test mappings, .ai/CURRENT_STATE.md, reproducible harness runbook. В issue #247/#248/#249/#252 сверить residual scope; закрытие #260 согласовать с отсутствующим runtime evidence. Не редактировать исторические отчёты, чтобы они выглядели успешно выполненными.

## Rollout and rollback

Разработка от нового main в isolated branch/worktree; frozen release candidate не менять. Сначала runner и tests, затем обязательный небольшой CI gate после подтверждения стабильности и branch-protection настройки сопровождающим. Rollback tooling/CI — revert соответствующего PR без удаления evidence и данных. Остановить только task-owned application resources. Production rollout не входит в этот план; требует отдельного разрешения, точных rollback digest, restore evidence и post-rollback health/count checks.

## Acceptance criteria

- [ ] Clean-machine Docker запуск реального Edge и Core одной документированной командой; exact identities в отчёте.
- [ ] Все восемь базовых сценариев имеют assertions, timeout и положительное/отрицательное evidence.
- [ ] Durable records не теряются; дубликаты не умножают научные наблюдения; observation time сохранён.
- [ ] UNKNOWN/stale/future/invalid inputs не превращаются в healthy без основания.
- [ ] Existing invariants и report validators потребляют фактические результаты; synthetic fixture не выдаётся за qualification PASS.
- [ ] Supported matrix и legacy window утверждены и исполнимы; current/previous consumer paths проверены.
- [ ] CI/runtime artifacts sanitised; exporter и production resources недоступны стенду.
- [ ] CLI/TUI read contracts и текущие tests сохранены.
- [ ] Software delivery отдельно от operational acceptance; будущие actuator invariants NOT_IMPLEMENTED.
- [ ] Руководство повторения, troubleshooting, rollback и оставшиеся NOT_RUN gates актуальны.

## Blocking open questions

1. Для PR4: какие предыдущие Edge/Core версии и rollback digest поддерживаются? Владелец — maintainer; нужны exact artifacts. Не блокирует PR1 current/current.
2. Для начала PR1: подтвердить пригодный deterministic fake sensor интерфейс в выбранном Edge SHA. Если его недостаточно, нужен отдельный bounded Edge prerequisite; запрещено заменять Edge самописным mock sender и называть это cross-repo тестом.
3. Для operational acceptance: среда Docker/staging, исполнитель soak/restore и отдельное разрешение canary. Это не блокирует software реализацию, но блокирует полный release-validation PASS.
4. План утверждён пользователем 2026-09-27; создание candidate ref уже исполнено по явному поручению пользователя.

## Evidence and references

- Server commit: https://github.com/cracketus/senior-pomidor-server/commit/aea94fd6235f0ecc242e5d1806332715fd7b85ce
- Candidate branch: https://github.com/cracketus/senior-pomidor-server/tree/release/v0.3.1-candidate
- CI: https://github.com/cracketus/senior-pomidor-server/actions/runs/36006222795
- Inspected issues: #247, #248, #249, #246, #250, #251, #252, #260 с комментарием, #302.
- Server sources: AGENTS.md; полный context-router pack; .ai/planning/*; docs/ROADMAP_2027.md; .github/workflows/ci.yml и release-qualification.yml; tools/staging_qualification.py; tests/test_docker_e2e.py и test_temporal_integrity.py; docs/implementation-reports/ISSUE-247-release-qualification-225.md.
- Edge sources: docs/core-integration.md; docker-compose.integration.yml; обнаруженные src/telemetry_spool.py и recovery tests. Полный текущий Edge runtime в этой задаче не проверялся.
- Приложения: архитектура v1, scientific review v1.3 (выбранные разделы), TECHNICAL_SPECIFICATION (выбранные разделы), Plant Observation Dataset Specification. Это design inputs; агрономические утверждения и электрическая часть не проверялись.

Approval of this brief does not itself authorize production deployment, production data/secrets access, or real hardware activation.
