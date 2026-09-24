# v0.3.1: аудит и условия выпуска

Проверено 2026-09-24. Это software-аудит, не свидетельство deployment или работы оборудования.

## Исходные revisions и CI

| Репозиторий | Проверенный main | CI |
| --- | --- | --- |
| Core | `fbbf13a7d3444cef73f10697cebba35faa6fe9cc` | [CI](https://github.com/cracketus/senior-pomidor-server/actions/runs/34775846793), success |
| Edge | `14d297ef1b18567d101876c143240d9354ddc860` | [Quality](https://github.com/cracketus/senior-pomidor-plant-v2/actions/runs/34773216107), [RC](https://github.com/cracketus/senior-pomidor-plant-v2/actions/runs/34773327810), success |

### После merge исправлений

| Репозиторий | Новый main | Проверка |
| --- | --- | --- |
| Core, PR #363 | `0a0832ec3589d276674a9508d792f465ea6fc223` | [CI](https://github.com/cracketus/senior-pomidor-server/actions/runs/35981229306): success |
| Edge, PR #154 | `d14b9367b359ab260bdb62c6364ccd542fbbbd26` | [Quality](https://github.com/cracketus/senior-pomidor-plant-v2/actions/runs/35980949385), [RC](https://github.com/cracketus/senior-pomidor-plant-v2/actions/runs/35981148395): success |

Code fixes уже в main. После merge документации выбрать окончательные Core/Edge RC metadata.
Нельзя использовать digest старой сборки с новым Git SHA. Успех RC workflow не заменяет проверку
самого metadata artifact и реальной совместимости выбранной пары.

## Дефекты, найденные на исходных revisions

| Приоритет | Проблема | Условие закрытия |
| --- | --- | --- |
| Release blocker | `tools.lifecycle` отсутствует в runtime image, хотя v0.3.1 требует эту CLI | Dockerfile включает модуль; `python -m tools.lifecycle show --help` работает в exact image |
| High | Повторный refresh TUI отменяет ожидание, но оставляет HTTP thread работающим | Регрессионный тест медленного fetch и repeated refresh; один запрос-пакет за раз |
| High | Составные TUI-экраны показывают cached anomalies/photos/state без собственного transport warning | Тесты partial failure; stale/disconnected виден у каждого зависимого раздела |
| Medium | CLI отвергает LF/CRLF token file; некорректный HTTP-header token может дать traceback | LF/CRLF принимается; некорректные символы дают bounded exit 4 |
| High | Edge продолжает доставку всего batch после stop, задерживая shutdown | Текущий ACK фиксируется; остальные записи возвращаются pending без новых attempts |
| High | Install/qualification инструкции используют старые SHA/digest и rollback version | Входы новой кампании проверены; current production baseline совпадает с rollback |
| Medium | Документы отрицают существующие TUI и Map API; HTTP ACK ошибочно описан как fallback | Описания согласованы с кодом |

Исправления влиты: [Core #363](https://github.com/cracketus/senior-pomidor-server/pull/363)
и [Edge #154](https://github.com/cracketus/senior-pomidor-plant-v2/pull/154). Их PR CI и post-merge CI успешны.
Документационные исправления представлены текущим PR.

## CLI/TUI acceptance

Проверить в operator virtual environment из exact accepted checkout, Python 3.12+:

```bash
python -m pip install '.[tui]'
pomidorctl --help
pomidorctl tui --help
python -m app.operator_tui --help
pomidorctl tui --demo
```

TUI не включён в базовый API image. Runtime tar.gz содержит Compose/scripts, а не Python project:
`pip install -e .` из распакованного runtime bundle не работает. Не добавляйте зависимости вручную
в production-контейнер. Для operator install используйте отдельный checkout/venv с зафиксированным SHA.

На изолированном API проверить шесть GET views, экраны `1..6`, `r`, `q`, размеры 80×24 и 60×18,
медленный API, отказ после успешного чтения, восстановление и частичный отказ views.
`--json`/`--verbose` относятся к обычным CLI-командам, не к TUI.

CLI exit codes: 0 OK, 1 WARN, 2 ALERT, 3 UNKNOWN/NOT_IMPLEMENTED, 4 configuration,
5 authentication, 6 unavailable, 7 protocol/contract. WARN/UNKNOWN — не ошибка запуска команды.
Host health и decisions могут законно быть NOT_IMPLEMENTED; TUI не должен выдумывать данные.

## Qualification v0.3.1

1. Влить проверенные code/docs PR. Зафиксировать окончательный Core SHA и выбранный Edge SHA.
2. Пройти [release-to-E2E](RELEASE_TO_E2E_RUNBOOK.md): exact-SHA CI, включая Docker E2E,
   immutable RC, annotated tag, version alias и checksummed bundle. Tag не является production approval.
3. В exact Core image проверить lifecycle help, migration readiness и project-scoped `worker-health`
   volume (API read-only, worker read-write). В изолированной БД проверить ACTIVE → DECOMMISSIONED → ACTIVE,
   expected-state mismatch, сохранение истории и исключение retired устройств из active aggregates.
4. Пройти [pre-production qualification](POST_MERGE_PREPRODUCTION_QUALIFICATION.md) для той же пары:
   HTTP/MQTT duplicates, потеря ACK, outage/spool/replay, restart, delayed/stale/future data, 24h soak,
   rollback только application. Mock-Core integration Edge не заменяет настоящий Edge/Core test.
5. Проверить fresh backup, isolated restore, текущий production baseline и отдельно согласовать rollout.
6. Выполнить [installation runbook](PRODUCTION_RELEASE_INSTALLATION_RUNBOOK.md): Core first,
   затем согласованный Edge canary, post-change наблюдение и rollback при fail-conditions.

Rollback v0.3.1 должен сохранять additive lifecycle schema и историю. Предыдущий API может иначе
агрегировать decommissioned устройства: проверить это на restored staging до установки. Нельзя
считать совместимость подтверждённой только потому, что старый контейнер стартовал.

## Ограничения аудита

- Локальная среда не содержит Docker. Compose config, image build, Docker E2E и exact-image lifecycle
  smoke остаются NOT_RUN локально. Core PR и post-merge CI успешны, включая Docker E2E;
  финальный release всё равно требует qualification на неизменяемых artifacts.
- Staging/24h soak, restore, production installation и Raspberry Pi hardware acceptance не выполнялись.
- `pyproject.toml` содержит distribution version `0.1.0`; текущая release identity задаётся Git tag,
  `REVISION` и OCI digest. Не определять установленный release только через `pip show`.
- Зависимости Core заданы диапазонами. Повторная сборка того же SHA позже может отличаться;
  promotion и rollback должны использовать уже проверенный digest без rebuild.

**Решение:** исправления кода влиты и CI успешен; Core/Edge готовы к следующему этапу
release qualification. Готовность к production v0.3.1 ещё не подтверждена. Разрешение на установку появляется только после evidence для окончательных artifacts.
