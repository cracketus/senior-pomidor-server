# Установка нового Server/Core release на production server

> СДВГ-режим: выполняйте **только один пронумерованный шаг за раз**. После каждого шага остановитесь,
> прочитайте блоки **Ожидается**, **STOP** и **GO**, поставьте галочку в журнале и только потом
> переходите дальше. Не вставляйте в терминал сразу несколько следующих блоков.

## 0. Сначала прочитайте это

Этот runbook предназначен для source-free Ubuntu production layout Senior Pomidor. Он описывает
Core-first rollout одного заранее протестированного immutable release. Он не разрешает deployment:
production change window и оператор должны быть отдельно одобрены человеком.

На момент 2026-08-29 umbrella issue #189 и обязательные #77, #78, #84, #85, #86, #185 и #186 имеют
состояние `OPEN`. Если для устанавливаемого кандидата нет принятых `PASS`-evidence по этим gate,
остановитесь на шаге 2. Слова «тесты прошли» без точных SHA/digest и evidence references недостаточно.

### Карта риска

| Уровень | Значение | Что делать при неожиданном результате |
| --- | --- | --- |
| `1 — низкий` | Read-only; состояние сервера не меняется | Остановиться и разобраться, но outage не ожидается |
| `2 — умеренный` | Download/copy; production runtime ещё не меняется | Не продолжать, исправить входные данные |
| `3 — высокий` | Backup останавливает writers или меняется runtime configuration | Не повторять команду вслепую; проверить service/data state |
| `4 — критический` | Переключается release или перезапускается application | При failed acceptance выполнить раздел rollback |
| `5 — запрет` | Нет recovery proof, identity расходится или требуется destructive action | Не выполнять; нужен отдельный human decision |

### Никогда не делать

- не использовать `docker compose down -v`;
- не удалять и не пересоздавать PostgreSQL, Grafana, Ollama, named volumes или backup repositories;
- не выполнять restore поверх production database;
- не использовать `latest`, rebuild или другой image после начала окна;
- не печатать и не копировать целиком `/srv/secrets/senior-pomidor/runtime.env`;
- не коммитить production logs, payloads, hostnames, addresses, paths или credentials;
- не обновлять Edge до успешной установки и проверки Core;
- не откатывать additive database migration и не удалять новую telemetry.

## 1. Организуйте работу

**Где:** рабочий ноутбук и две независимые SSH-сессии на production server.  
**Риск:** `1 — низкий`.

Откройте:

- `L` — PowerShell 7 на рабочем ноутбуке Windows, из корня Git checkout;
- `S1` — основной SSH-терминал на production server;
- `S2` — резервный SSH-терминал, который остаётся открытым для диагностики/rollback;
- приватную change record, не находящуюся в Git.

Проверьте локальные инструменты в `L`. `tar.exe` входит в актуальные Windows, а `ssh.exe` и `scp.exe`
предоставляет компонент OpenSSH Client; все дальнейшие блоки для `L` рассчитаны на PowerShell, а блоки для
`S1`/`S2` — на Bash в Ubuntu:

```powershell
$PSVersionTable.PSVersion
Get-Command git, gh, python, tar.exe, ssh.exe, scp.exe
```

В change record запишите:

```text
[ ] human approval reference
[ ] maintenance window start/end UTC
[ ] operator and approver
[ ] new version
[ ] new Core Git SHA
[ ] new immutable image ref and digest
[ ] new runtime bundle SHA-256
[ ] previous version, accepted Core Git SHA and immutable image ref
[ ] release evidence report ID
[ ] rollback decision owner
```

**Ожидается:** у оператора есть резервная SSH-сессия и приватный журнал.  
**STOP:** нет второй административной сессии, approval или rollback decision owner.  
**GO:** всё перечисленное зафиксировано.

## 2. Проверка разрешения на rollout

**Где:** `L`, GitHub/evidence checkout.  
**Риск:** `5 — запрет`, если evidence неполные.

Для одной и той же пары Core/Edge должны быть `PASS`:

```text
[ ] exact Core SHA/image/digest identity
[ ] exact Edge SHA/image/digest identity
[ ] required CI, docker-e2e and branch protection
[ ] #84 contract compatibility
[ ] #85 MQTT/HTTP ingestion and failure paths
[ ] #86 canonical Compose/readiness proof
[ ] real Edge/Core compatibility report
[ ] 24-hour isolated staging soak
[ ] exact-bundle application-only rollback rehearsal
[ ] #77 encrypted local + off-site backup gate
[ ] #78 clean-host restore drill: RPO < 24 h, RTO < 4 h
[ ] #185 actual Ubuntu host baseline
[ ] #186 actual SSH/LAN exposure audit
```

Проверьте pre-production reports для точных identities в PowerShell:

```powershell
$ReportId = '<accepted-report-id>'
$CoreSha = '<40-lowercase-hex>'
$CoreImage = 'ghcr.io/cracketus/senior-pomidor-server@sha256:<64-lowercase-hex>'
$CoreDigest = 'sha256:<64-lowercase-hex>'
$EdgeSha = '<40-lowercase-hex>'
$EdgeImage = '<exact-immutable-edge-image-ref>'
$EdgeDigest = 'sha256:<64-lowercase-hex>'

python -m tools.release_qualification validate `
  --kind edge-core-compatibility `
  --report "docs/release-evidence/$ReportId/edge-core-compatibility.json" `
  --require-pass `
  --core-sha $CoreSha --core-image $CoreImage --core-digest $CoreDigest `
  --edge-sha $EdgeSha --edge-image $EdgeImage --edge-digest $EdgeDigest

python -m tools.release_qualification validate `
  --kind release-validation --mode preproduction --require-pass `
  --report "docs/release-evidence/$ReportId/release-validation.json" `
  --core-sha $CoreSha --core-image $CoreImage --core-digest $CoreDigest `
  --edge-sha $EdgeSha --edge-image $EdgeImage --edge-digest $EdgeDigest
```

**Ожидается:** обе команды завершаются с кодом `0`; все identities совпадают.  
**STOP:** любой `FAIL`, required `NOT_RUN`, synthetic report, identity drift или открытый необъяснённый
gate. Не переходите к backup/install.  
**GO:** reviewer/owner подтвердил все gate и отдельное production approval.

## 3. Скачать и проверить release assets

### 3.1 Скачать assets

**Где:** `L`.  
**Риск:** `2 — умеренный`.

Замените версии на фактические. Проверенный bundle предыдущего release обязателен для rollback.
Если его нельзя скачать и проверить, установка является `STOP`; human waiver не заменяет
работоспособный и проверенный путь отката.

```powershell
$NewVersion = 'vX.Y.Z'
$OldVersion = 'vA.B.C'
$ExpectedOldRevision = '<accepted-40-lowercase-previous-core-sha>'
$AssetRoot = Join-Path (Get-Location) 'senior-pomidor-release-assets'
$NewAssetDir = Join-Path $AssetRoot $NewVersion
$OldAssetDir = Join-Path $AssetRoot $OldVersion

git fetch origin --tags
New-Item -ItemType Directory -Force -Path $NewAssetDir

gh release download $NewVersion `
  --repo cracketus/senior-pomidor-server `
  --pattern "senior-pomidor-runtime-$NewVersion.tar.gz*" `
  --dir $NewAssetDir

New-Item -ItemType Directory -Force -Path $OldAssetDir
gh release download $OldVersion `
  --repo cracketus/senior-pomidor-server `
  --pattern "senior-pomidor-runtime-$OldVersion.tar.gz*" `
  --dir $OldAssetDir
```

### 3.2 Проверить checksums и metadata

**Где:** `L`.  
**Риск:** `1 — низкий`.

```powershell
function Test-ReleaseChecksum {
  param([string]$AssetDir, [string]$Version)

  $ArchiveName = "senior-pomidor-runtime-$Version.tar.gz"
  $Archive = Join-Path $AssetDir $ArchiveName
  $ChecksumFile = "$Archive.sha256"
  $Expected = ((Get-Content -LiteralPath $ChecksumFile -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
  $Actual = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($Expected -notmatch '^[0-9a-f]{64}$' -or $Actual -ne $Expected) {
    throw "SHA-256 mismatch: $Archive"
  }
  Write-Host "${ArchiveName}: OK"
}

Test-ReleaseChecksum -AssetDir $NewAssetDir -Version $NewVersion
$NewArchive = Join-Path $NewAssetDir "senior-pomidor-runtime-$NewVersion.tar.gz"
$BundleVersion = (tar.exe -xOf $NewArchive ./VERSION).Trim()
$BundleRevision = (tar.exe -xOf $NewArchive ./REVISION).Trim()
$TagRevision = (git rev-parse "${NewVersion}^{commit}").Trim()
$BundleEntries = @(tar.exe -tzf $NewArchive)
if ($LASTEXITCODE -ne 0) { throw 'Cannot read new runtime bundle' }
if ($BundleVersion -ne $NewVersion) { throw 'New bundle VERSION mismatch' }
if ($BundleRevision -ne $CoreSha) { throw 'New bundle REVISION mismatch' }
if ($TagRevision -ne $CoreSha) { throw 'Git tag does not point to the accepted Core revision' }
if ($BundleEntries | Select-String -Pattern '(^|/)(app|migrations)/|\.py$') {
  throw 'New runtime bundle contains Python source'
}
$BundleVersion
$BundleRevision

Test-ReleaseChecksum -AssetDir $OldAssetDir -Version $OldVersion
$OldArchive = Join-Path $OldAssetDir "senior-pomidor-runtime-$OldVersion.tar.gz"
$OldBundleVersion = (tar.exe -xOf $OldArchive ./VERSION).Trim()
$OldBundleRevision = (tar.exe -xOf $OldArchive ./REVISION).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot read previous runtime bundle' }
if ($OldBundleVersion -ne $OldVersion) { throw 'Previous bundle VERSION mismatch' }
if ($ExpectedOldRevision -notmatch '^[0-9a-f]{40}$') { throw 'Accepted previous revision is invalid' }
if ($OldBundleRevision -ne $ExpectedOldRevision) { throw 'Previous bundle REVISION mismatch' }
$OldBundleVersion
$OldBundleRevision
```

**Ожидается:** checksum выводит `OK`; `VERSION` совпадает с release; Git tag, accepted
`CORE_SHA` и `REVISION` в bundle указывают на один commit; bundle не содержит Python source.
**STOP:** любое identity/checksum не совпало или old bundle отсутствует.
**GO:** оба assets проверены и rollback bundle готов к передаче.

## 4. Передать assets на server без установки

### 4.1 Передать во временный каталог

**Где:** `L`.  
**Риск:** `2 — умеренный`.

```powershell
$AdminTarget = '<admin-user>@<approved-server>'
$TransferFiles = @(
  (Join-Path $NewAssetDir "senior-pomidor-runtime-$NewVersion.tar.gz"),
  (Join-Path $NewAssetDir "senior-pomidor-runtime-$NewVersion.tar.gz.sha256"),
  (Join-Path $OldAssetDir "senior-pomidor-runtime-$OldVersion.tar.gz"),
  (Join-Path $OldAssetDir "senior-pomidor-runtime-$OldVersion.tar.gz.sha256")
)

& scp.exe @TransferFiles "${AdminTarget}:/tmp/"
if ($LASTEXITCODE -ne 0) { throw 'SCP transfer failed' }
```

### 4.2 Установить ownership/mode для incoming assets

**Где:** `S1`.  
**Риск:** `2 — умеренный`. Это пишет только release assets, application ещё не меняется.

```bash
export NEW_VERSION='vX.Y.Z'
export OLD_VERSION='vA.B.C'
export INCOMING='/srv/apps/senior-pomidor/releases/.incoming'

sudo install -d -o root -g root -m 0755 "${INCOMING}"

sudo install -o root -g root -m 0644 \
  "/tmp/senior-pomidor-runtime-${NEW_VERSION}.tar.gz" \
  "${INCOMING}/senior-pomidor-runtime-${NEW_VERSION}.tar.gz"
sudo install -o root -g root -m 0644 \
  "/tmp/senior-pomidor-runtime-${NEW_VERSION}.tar.gz.sha256" \
  "${INCOMING}/senior-pomidor-runtime-${NEW_VERSION}.tar.gz.sha256"

sudo install -o root -g root -m 0644 \
  "/tmp/senior-pomidor-runtime-${OLD_VERSION}.tar.gz" \
  "${INCOMING}/senior-pomidor-runtime-${OLD_VERSION}.tar.gz"
sudo install -o root -g root -m 0644 \
  "/tmp/senior-pomidor-runtime-${OLD_VERSION}.tar.gz.sha256" \
  "${INCOMING}/senior-pomidor-runtime-${OLD_VERSION}.tar.gz.sha256"
```

Перепроверьте checksums уже на server:

```bash
(
  cd "${INCOMING}"
  sudo sha256sum --check "senior-pomidor-runtime-${NEW_VERSION}.tar.gz.sha256"
  sudo sha256sum --check "senior-pomidor-runtime-${OLD_VERSION}.tar.gz.sha256"
)
```

**Ожидается:** `OK` для каждого переданного release; файлы принадлежат `root:root`, mode `0644`.
**STOP:** checksum не совпадает или destination неожиданно является symlink/другим layout.  
**GO:** new и old releases доступны на server; пока ничего не перезапущено.

## 5. Создать карточку текущего состояния

**Где:** `S1`.  
**Риск:** `1 — низкий`, read-only.

Задайте только non-secret значения. `NEW_APP_IMAGE` копируется из принятого release evidence, не
вычисляется из Git SHA.

```bash
export NEW_REVISION='<accepted-40-lowercase-core-sha>'
export EXPECTED_OLD_REVISION='<accepted-40-lowercase-previous-core-sha>'
export NEW_APP_IMAGE='ghcr.io/cracketus/senior-pomidor-server@sha256:<accepted-64-hex-digest>'
export API_URL='http://<approved-server-address>:8000'
export CANARY_EDGE_ID='' # оставьте пустым, если approved Edge ещё нет

export APP_ROOT='/srv/apps/senior-pomidor'
export ACTIVE_LINK="${APP_ROOT}/app"
export ENV_FILE='/srv/secrets/senior-pomidor/runtime.env'
export INSTALLER='/srv/automation/scripts/senior-pomidor/install-release.sh'
export NEW_ARCHIVE="${INCOMING}/senior-pomidor-runtime-${NEW_VERSION}.tar.gz"
export NEW_CHECKSUM="${NEW_ARCHIVE}.sha256"
export OLD_ARCHIVE="${INCOMING}/senior-pomidor-runtime-${OLD_VERSION}.tar.gz"
export OLD_CHECKSUM="${OLD_ARCHIVE}.sha256"

export OLD_RELEASE_PATH="$(readlink -f "${ACTIVE_LINK}")"
export OLD_APP_IMAGE="$(sudo sed -n 's/^APP_IMAGE=//p' "${ENV_FILE}" | tail -n 1)"
export OLD_REVISION="$(sudo cat "${ACTIVE_LINK}/REVISION")"
```

Проверьте значения без вывода всего secret file:

```bash
printf 'active=%s\nold_version=%s\nold_revision=%s\nold_image=%s\n' \
  "${OLD_RELEASE_PATH}" "$(sudo cat "${ACTIVE_LINK}/VERSION")" \
  "${OLD_REVISION}" "${OLD_APP_IMAGE}"

[[ "${NEW_VERSION}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "${OLD_VERSION}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "${NEW_REVISION}" =~ ^[0-9a-f]{40}$ ]]
[[ "${EXPECTED_OLD_REVISION}" =~ ^[0-9a-f]{40}$ ]]
[[ "${OLD_REVISION}" == "${EXPECTED_OLD_REVISION}" ]]
[[ "${NEW_APP_IMAGE}" =~ ^ghcr\.io/cracketus/senior-pomidor-server@sha256:[0-9a-f]{64}$ ]]
[[ "${OLD_APP_IMAGE}" =~ ^ghcr\.io/cracketus/senior-pomidor-server@sha256:[0-9a-f]{64}$ ]]
[[ "$(sudo cat "${ACTIVE_LINK}/VERSION")" == "${OLD_VERSION}" ]]
[[ "${OLD_RELEASE_PATH}" == "${APP_ROOT}/releases/${OLD_VERSION}" ]]
```

`API_URL` должен содержать реальный published address из `LAN_BIND_ADDRESS`. Если API опубликован
только на LAN interface, `http://127.0.0.1:8000` на server не сработает. Не выводите весь `runtime.env`;
проверьте только фактическую публикацию в Compose `ps` на шаге 6.

Если current `runtime.env` содержит version tag вместо digest, не продолжайте с tag. Возьмите точный
предыдущий digest из принятого release/change evidence, вручную присвойте его `OLD_APP_IMAGE` и повторите
regex-проверку. Rollback image должен быть immutable.

**Ожидается:** все `[[ ... ]]` возвращают `0`; current release — ожидаемый rollback release.  
**STOP:** пустая переменная, regex/версия не совпадает, active symlink ведёт вне canonical releases
layout. Не редактируйте `runtime.env`.  
**GO:** сохраните четыре выведенных non-secret значения в приватной change record.

## 6. Preflight production host

### 6.1 Service, Docker, clock и filesystem

**Где:** `S1`.  
**Риск:** `1 — низкий`, read-only.

Выполняйте по одной команде:

```bash
systemctl is-active senior-pomidor.service
systemctl is-active docker.service
timedatectl show --property=NTPSynchronized --value
sudo docker info >/dev/null
df -h /srv /var/lib/docker
test ! -e /var/run/reboot-required
sudo test -r "${ENV_FILE}"
sudo test -x "${INSTALLER}"
```

Проверьте current Compose и health:

```bash
cd "${ACTIVE_LINK}"
sudo docker compose --project-name senior-pomidor --env-file "${ENV_FILE}" \
  -f docker-compose.yml -f docker-compose.prod.yml config --quiet
sudo docker compose --project-name senior-pomidor --env-file "${ENV_FILE}" \
  -f docker-compose.yml -f docker-compose.prod.yml ps
curl --fail --silent --show-error "${API_URL}/health"
curl --fail --silent --show-error "${API_URL}/ready"
curl --fail --silent --show-error "${API_URL}/health/summary"
if [[ -n "${CANARY_EDGE_ID}" ]]; then
  curl --fail --silent --show-error \
    "${API_URL}/health/summary?node_id=${CANARY_EDGE_ID}"
else
  echo 'Canary Edge absent: scoped preflight is NOT_RUN'
fi
```

Проверьте shared platform без изменения его lifecycle:

```bash
sudo docker network inspect srv-platform \
  --format '{{range .Containers}}{{println .Name}}{{end}}'
```

**Ожидается:** services active, `NTPSynchronized=yes`, достаточно места по утверждённому threshold,
нет pending reboot, Compose render проходит, `ps` показывает project `senior-pomidor`, `/health` и `/ready` успешны,
scoped health для заданного canary не содержит необъяснённого `ALERT/UNKNOWN`, platform network содержит
ожидаемые services. Без canary только scoped check записан как `NOT_RUN`.
**STOP:** Docker/clock/storage/service/ready problem, pending reboot, unexpected listener/service,
stale or unknown canary evidence. Сначала восстановите baseline; deployment не является лечением.  
**GO:** baseline записан.

### 6.2 Проверить paths, которые использует installer

**Где:** `S1`.  
**Риск:** `1 — низкий`, но failure здесь предотвращает partial switch.

```bash
sudo test -f "${NEW_ARCHIVE}"
sudo test -f "${NEW_CHECKSUM}"
sudo test -f "${OLD_ARCHIVE}"
sudo test -f "${OLD_CHECKSUM}"
sudo test ! -e "${APP_ROOT}/releases/${NEW_VERSION}"
sudo test ! -e "/srv/apps/archive/senior-pomidor/${OLD_VERSION}"
sudo test ! -e "/srv/apps/archive/senior-pomidor/${NEW_VERSION}"
```

Почему это важно: при успешной установке installer сначала переключает `app`, затем переносит прошлый
release в `/srv/apps/archive/senior-pomidor`. Конфликт archive path может дать non-zero уже после
переключения symlink.

**Ожидается:** все команды возвращают `0`.  
**STOP:** любой path уже существует. Не удаляйте его. Нужен отдельный operator decision о сохранении
и разрешении конфликта.  
**GO:** installation и rollback paths свободны.

## 7. Создать свежий backup

### 7.1 Обязательный #77/#78 gate

**Где:** approved backup system и clean/disposable restore host.  
**Риск:** `5 — запрет`, если gate не реализован.

Для #189 требуется:

```text
[ ] encrypted snapshot на отдельном local medium
[ ] независимая encrypted off-site copy
[ ] verified freshness < 24 h
[ ] integrity/checksum PASS
[ ] destination failure visibility PASS
[ ] clean-host restore proof для совместимого candidate
[ ] PostgreSQL/photos/estimator/MQTT/deployment metadata verified
[ ] RPO < 24 h и RTO < 4 h
```

В текущем checkout #77 и #78 открыты, поэтому canonical production-команда для этого полного gate
отсутствует. **Не заменяйте его только локальным `backup.sh`.** Если нет уже принятой human-owned
реализации и restore report, установка останавливается здесь.

**Ожидается:** принятый backup/restore report с `PASS`.  
**STOP:** backup существует только на системном диске, нет off-site copy, restore не выполнялся,
snapshot старше 24 часов или report недоступен.  
**GO:** recovery owner подтвердил реальную восстановимость.

### 7.2 Дополнительный local weekly snapshot текущего production

**Где:** `S1`.  
**Риск:** `3 — высокий`.

`senior-pomidor-backup@weekly.service` кратко останавливает работающие writers, архивирует local
application data, запускает writers обратно, проверяет SHA-256 и применяет legacy retention:
daily старше 30 дней и weekly старше 56 дней удаляются. Перед запуском убедитесь, что эта retention
операция одобрена и необходимые старые sets уже защищены принятой backup policy.

```bash
sudo systemctl start senior-pomidor-backup@weekly.service
sudo systemctl show senior-pomidor-backup@weekly.service \
  --property=Result --property=ExecMainStatus --property=ActiveState --no-pager
sudo journalctl -u senior-pomidor-backup@weekly.service -n 120 --no-pager
```

Найдите только что созданный set и проверьте его:

```bash
export LATEST_LOCAL_BACKUP="$(
  sudo find /srv/backups/senior-pomidor/weekly \
    -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
    | sort -nr | head -n 1 | cut -d' ' -f2-
)"

sudo test -n "${LATEST_LOCAL_BACKUP}"
sudo test -s "${LATEST_LOCAL_BACKUP}/database.dump"
sudo test -s "${LATEST_LOCAL_BACKUP}/photos.tar.gz"
sudo test -s "${LATEST_LOCAL_BACKUP}/estimator-private.tar.gz"
sudo test -s "${LATEST_LOCAL_BACKUP}/mosquitto.tar.gz"
sudo test -s "${LATEST_LOCAL_BACKUP}/SHA256SUMS"

sudo sh -c 'cd "$1" && sha256sum --check SHA256SUMS' \
  backup-verify "${LATEST_LOCAL_BACKUP}"
```

Проверьте восстановление writers и API:

```bash
systemctl is-active senior-pomidor.service
cd "${ACTIVE_LINK}"
sudo docker compose --project-name senior-pomidor --env-file "${ENV_FILE}" \
  -f docker-compose.yml -f docker-compose.prod.yml ps
curl --fail --silent --show-error "${API_URL}/ready"
```

**Ожидается:** `Result=success` и `ExecMainStatus=0`; `ActiveState=inactive` допустим для успешно
завершившегося oneshot service; все artifacts non-empty; каждый checksum `OK`; writers снова
running/healthy; `/ready` успешен.  
**STOP:** backup incomplete, checksum mismatch или writer не восстановился. Не запускайте backup
повторно вслепую и не начинайте install.  
**GO:** local snapshot зафиксирован как дополнительная защита; обязательный #77/#78 gate уже отдельно
имеет `PASS`.

## 8. Подготовить rollback до изменения configuration

**Где:** `S1`.  
**Риск:** `2 — умеренный`.

```bash
(
  cd "${INCOMING}"
  sudo sha256sum --check "$(basename "${OLD_CHECKSUM}")"
)
test "$(sudo tar -xOf "${OLD_ARCHIVE}" ./REVISION)" = "${OLD_REVISION}"

sudo docker pull "${OLD_APP_IMAGE}"
sudo docker pull "${NEW_APP_IMAGE}"
```

В приватной change record должны быть скопированы:

```text
OLD_VERSION
OLD_REVISION
OLD_APP_IMAGE
OLD_ARCHIVE/OLD_CHECKSUM
OLD_RELEASE_PATH
LATEST_LOCAL_BACKUP
```

**Ожидается:** оба images доступны; old bundle checksum `OK`; старые значения записаны.
**STOP:** old image или проверенный old bundle недоступны либо rollback rehearsal не использовал этот путь.
**GO:** rollback готов до изменения configuration.

## 9. Переключить только APP_IMAGE

**Где:** `S1`.  
**Риск:** `3 — высокий`. Secret file меняется; приложение пока не перезапускается.

Проверьте, что строка ровно одна и ещё содержит старое значение:

```bash
sudo test "$(sudo grep -c '^APP_IMAGE=' "${ENV_FILE}")" -eq 1
test "$(sudo sed -n 's/^APP_IMAGE=//p' "${ENV_FILE}")" = "${OLD_APP_IMAGE}"
```

Замените только эту строку:

```bash
sudo sed -i "s|^APP_IMAGE=.*$|APP_IMAGE=${NEW_APP_IMAGE}|" "${ENV_FILE}"
```

Проверьте только non-secret image value:

```bash
test "$(sudo sed -n 's/^APP_IMAGE=//p' "${ENV_FILE}")" = "${NEW_APP_IMAGE}"
sudo stat --format='%U:%G %a %n' "${ENV_FILE}"
```

**Ожидается:** `APP_IMAGE` равен exact digest; file остаётся `root:root 600`.  
**STOP:** строк больше одной, исходное значение изменилось, mode/owner стал другим. Верните только
`APP_IMAGE` к `OLD_APP_IMAGE`; не выводите весь файл.  
**GO:** configuration указывает на новый immutable image.

## 10. Установить runtime bundle

**Где:** `S1`, `S2` остаётся открытым.  
**Риск:** `4 — критический`.

```bash
sudo "${INSTALLER}" "${NEW_ARCHIVE}" "${NEW_CHECKSUM}"
```

**Ожидается:** последняя строка:

```text
Installed vX.Y.Z. Run: systemctl reload-or-restart senior-pomidor
```

До restart проверьте symlink и metadata:

```bash
readlink -f "${ACTIVE_LINK}"
sudo cat "${ACTIVE_LINK}/VERSION"
sudo cat "${ACTIVE_LINK}/REVISION"
```

Ожидается:

```text
/srv/apps/senior-pomidor/releases/vX.Y.Z
vX.Y.Z
<NEW_REVISION>
```

**STOP:** installer вернул non-zero, metadata не совпала или active link неожиданен. Не запускайте
installer второй раз.

- Если `app` всё ещё указывает на `OLD_RELEASE_PATH`, верните `APP_IMAGE` к `OLD_APP_IMAGE`; текущий
  service не перезапускайте до проверки.
- Если `app` уже указывает на новый release, переходите прямо к разделу 13 «Rollback».

**GO:** installer вернул `0`, symlink/version/revision точные.

## 11. Перезапустить только Senior Pomidor application

**Где:** `S1`.  
**Риск:** `4 — критический`. Начинается application outage window.

Запишите UTC start в приватную change record:

```bash
date -u +'%Y-%m-%dT%H:%M:%SZ'
sudo systemctl reload-or-restart senior-pomidor.service
```

Сразу проверьте status:

```bash
systemctl is-active senior-pomidor.service
sudo systemctl status senior-pomidor.service --no-pager
```

Проверьте точный Compose project:

```bash
cd "${ACTIVE_LINK}"
sudo docker compose --project-name senior-pomidor --env-file "${ENV_FILE}" \
  -f docker-compose.yml -f docker-compose.prod.yml ps
sudo docker compose --project-name senior-pomidor --env-file "${ENV_FILE}" \
  -f docker-compose.yml -f docker-compose.prod.yml ps -a migrate
```

`--project-name senior-pomidor` обязателен в interactive shell: `COMPOSE_PROJECT_NAME` задан в systemd unit и не
наследуется SSH-сессией. Без него `docker compose ps` может показать пустой, неправильно
именованный project, хотя production containers работают.

**Ожидается:** systemd command возвращает `0`; service active; `migrate` завершился без ошибки;
`api`, `worker`, `state-estimator-worker` и применимые profiles running/healthy. Shared PostgreSQL,
Grafana и Ollama не перезапускались этим действием.  
**STOP:** systemd non-zero, migration failure, unhealthy/restart loop или shared service impact.
Соберите bounded diagnostics и выполняйте rollback.  
**GO:** application запущено на новом release.

## 12. Быстрая проверка после rollout

### 12.1 Первые 5 минут

**Где:** `S1`.  
**Риск:** `1 — низкий`, read-only; последствия обнаруженной ошибки — `4`.

```bash
curl --fail --silent --show-error "${API_URL}/health"
curl --fail --silent --show-error "${API_URL}/ready"
curl --fail --silent --show-error "${API_URL}/health/summary"
test "$(sudo cat "${ACTIVE_LINK}/VERSION")" = "${NEW_VERSION}"
test "$(sudo cat "${ACTIVE_LINK}/REVISION")" = "${NEW_REVISION}"
test "$(sudo sed -n 's/^APP_IMAGE=//p' "${ENV_FILE}")" = "${NEW_APP_IMAGE}"
API_CONTAINER_ID="$(sudo docker compose --project-name senior-pomidor --env-file "${ENV_FILE}" \
  -f docker-compose.yml -f docker-compose.prod.yml ps -q api)"
sudo test -n "${API_CONTAINER_ID}"
test "$(sudo docker inspect --format '{{.Config.Image}}' "${API_CONTAINER_ID}")" = "${NEW_APP_IMAGE}"
if [[ -n "${CANARY_EDGE_ID}" ]]; then
  curl --fail --silent --show-error \
    "${API_URL}/health/summary?node_id=${CANARY_EDGE_ID}"
  curl --fail --silent --show-error \
    "${API_URL}/api/v1/devices/${CANARY_EDGE_ID}/latest"
  curl --fail --silent --show-error \
    "${API_URL}/api/v1/operator/edges/${CANARY_EDGE_ID}/reliability"
else
  echo 'Canary Edge absent: Edge-specific fast checks are NOT_RUN'
fi
```

Проверьте bounded logs только приватно:

```bash
sudo journalctl -u senior-pomidor.service --since '-10 minutes' -n 200 --no-pager
```

Сравните с pre-change baseline:

```text
[ ] exact VERSION/REVISION/image
[ ] /health PASS
[ ] /ready PASS
[ ] API worker fresh
[ ] MQTT worker fresh
[ ] State Estimator worker fresh
[ ] existing devices/telemetry readable
[ ] representative historical telemetry readable
[ ] representative photo metadata/download readable
[ ] no unexpected listener
[ ] no restart loop
[ ] no migration error
[ ] no external-export privacy violation
```

**Ожидается:** все checks совпадают с baseline или имеют заранее одобренное объяснение.  
**STOP и rollback:** `/ready` не стал успешным в пределах systemd 180-second start window; worker
stale; data missing; count mismatch; duplicate ingestion; unexpected listener/export; privacy leak;
любая migration error.  
**GO:** быстрый gate записан как `PASS`.

### 12.2 Реальный Core canary path

**Где:** production Edge + read-only проверки на `S1`; только в approved window.  
**Риск:** `4 — критический` из-за production data path.

Core устанавливается первым. Не обновляйте остальные Edge. Дождитесь следующей естественной telemetry
от одного approved canary Edge или выполните заранее одобренную Edge canary procedure. Не изобретайте
новый payload и не воспроизводите production `record_id` вручную.

Если canary не был выбран до rollout, не подставляйте вымышленный ID. После запуска реального Edge
получите его ID из read-only API и задайте его только после human confirmation:

```bash
curl --fail --silent --show-error "${API_URL}/api/v1/devices"
export CANARY_EDGE_ID='<confirmed-device-id-from-response>'
```

После новой observation повторите:

```bash
curl --fail --silent --show-error \
  "${API_URL}/api/v1/devices/${CANARY_EDGE_ID}/latest"
curl --fail --silent --show-error \
  "${API_URL}/api/v1/devices/${CANARY_EDGE_ID}/telemetry?since_hours=1&limit=20"
curl --fail --silent --show-error \
  "${API_URL}/health/summary?node_id=${CANARY_EDGE_ID}"
curl --fail --silent --show-error \
  "${API_URL}/api/v1/operator/edges/${CANARY_EDGE_ID}/reliability"
```

**Ожидается:** observation новая и fresh; persistence/read-back совпадают; нет unintended duplicate;
reliability не маскирует missing/stale evidence как healthy.  
**STOP и rollback:** ingestion rejected, count/identity mismatch, duplicate scientific row,
stale-to-healthy promotion, `ALERT/UNKNOWN` без объяснения или Edge/Core incompatibility.  
**GO:** canary data path `PASS`.

### 12.3 Edge reliability и Grafana

**Где:** `S1` для read-only API; `L` и UI общей Grafana для dashboard.
**Риск:** `1 — низкий` для проверок; импорт в shared Grafana требует platform-admin approval.

Проверьте bounded reliability view нового Edge:

```bash
if [[ -n "${CANARY_EDGE_ID}" ]]; then
  curl --fail --silent --show-error \
    "${API_URL}/api/v1/operator/edges/${CANARY_EDGE_ID}/reliability"
  curl --fail --silent --show-error \
    "${API_URL}/health/summary?node_id=${CANARY_EDGE_ID}"
else
  echo 'Canary Edge absent: reliability API checks are NOT_RUN'
fi
```

Ожидаемый healthy baseline: overall status равен `OK`, freshness равен `FRESH`, subsystem statuses равны `OK`, watchdog
имеет state `healthy`, application process running, spool backlog bounded. `UNKNOWN` при fresh telemetry означает,
что Edge не присылает все `system_health.watchdog`, `system_health.spool` и `system_health.application` blocks.
Если `CANARY_EDGE_ID` пуст, этот API baseline и device-specific проверка dashboard имеют status `NOT_RUN`, а не
`PASS`; отсутствие заранее одобренного canary само по себе не является stop-condition.

Production Compose не управляет shared Grafana, а source-free runtime bundle не содержит
`docker/grafana/provisioning`. Поэтому application rollout сам не добавляет new dashboard. После platform-admin
approval в `L` из exact tag извлеките dashboard JSON в Windows temp, не засоряя checkout:

```powershell
$DashboardFile = Join-Path ([System.IO.Path]::GetTempPath()) `
  "senior-pomidor-edge-reliability-$NewVersion.json"
git show "${NewVersion}:docker/grafana/provisioning/dashboards/json/senior-pomidor-edge-reliability.json" |
  Set-Content -LiteralPath $DashboardFile -Encoding utf8
Get-Content -LiteralPath $DashboardFile -Raw | ConvertFrom-Json | Out-Null
$DashboardFile
```

Затем в Grafana откройте `Dashboards` → `New` → `Import` и загрузите выведенный `$DashboardFile`.

Проверьте dashboard `Senior Pomidor Edge Reliability`, UID `senior-pomidor-edge-reliability`, datasource UID
`senior-pomidor-postgres` и выберите `CANARY_EDGE_ID` в фильтре. Dashboard JSON не содержит alert rules. Пять
rules из `docker/grafana/provisioning/alerting/edge-reliability-alerts.yml` требуют отдельного одобренного
shared-platform provisioning; не отмечайте alerts `PASS` только после dashboard import.

**STOP:** reliability stale/unavailable, необъяснённый `ALERT/UNKNOWN`, datasource error или shared Grafana change без
platform approval.
**GO:** при заданном canary API показывает fresh Edge reliability и dashboard показывает тот же device; при пустом
`CANARY_EDGE_ID` обе device-specific проверки честно записаны как `NOT_RUN`. Отдельный Grafana import также может
быть записан как `NOT_RUN`, если для него нет platform approval.

## 13. Rollback

Используйте этот раздел при любом stop-condition после шага 10. Rollback возвращает application
bundle/image, но сохраняет PostgreSQL, Grafana, Ollama, volumes и additive migration.

### 13.1 Проверить, какой release активен

**Где:** `S1` или `S2`.  
**Риск:** `1 — низкий`.

```bash
readlink -f "${ACTIVE_LINK}"
sudo cat "${ACTIVE_LINK}/VERSION"
sudo sed -n 's/^APP_IMAGE=//p' "${ENV_FILE}"
```

Если active release всё ещё старый и service не перезапускался, верните только `APP_IMAGE`:

```bash
sudo sed -i "s|^APP_IMAGE=.*$|APP_IMAGE=${OLD_APP_IMAGE}|" "${ENV_FILE}"
test "$(sudo sed -n 's/^APP_IMAGE=//p' "${ENV_FILE}")" = "${OLD_APP_IMAGE}"
```

После этого остановитесь и диагностируйте installer; повторный install не нужен.

### 13.2 Переустановить предыдущий immutable bundle

**Где:** `S1` или `S2`.  
**Риск:** `4 — критический`.

Выполняйте только если active link уже указывает на `NEW_VERSION`.

```bash
sudo test -f "${OLD_ARCHIVE}"
sudo test -f "${OLD_CHECKSUM}"
sudo test ! -e "${APP_ROOT}/releases/${OLD_VERSION}"
sudo test ! -e "/srv/apps/archive/senior-pomidor/${NEW_VERSION}"

(
  cd "${INCOMING}"
  sudo sha256sum --check "$(basename "${OLD_CHECKSUM}")"
)

sudo test "$(sudo grep -c '^APP_IMAGE=' "${ENV_FILE}")" -eq 1
sudo sed -i "s|^APP_IMAGE=.*$|APP_IMAGE=${OLD_APP_IMAGE}|" "${ENV_FILE}"
test "$(sudo sed -n 's/^APP_IMAGE=//p' "${ENV_FILE}")" = "${OLD_APP_IMAGE}"

sudo "${INSTALLER}" "${OLD_ARCHIVE}" "${OLD_CHECKSUM}"
sudo systemctl reload-or-restart senior-pomidor.service
```

Проверьте rollback:

```bash
test "$(sudo cat "${ACTIVE_LINK}/VERSION")" = "${OLD_VERSION}"
test "$(sudo cat "${ACTIVE_LINK}/REVISION")" = "${OLD_REVISION}"
systemctl is-active senior-pomidor.service
curl --fail --silent --show-error "${API_URL}/health"
curl --fail --silent --show-error "${API_URL}/ready"
if [[ -n "${CANARY_EDGE_ID}" ]]; then
  curl --fail --silent --show-error \
    "${API_URL}/api/v1/devices/${CANARY_EDGE_ID}/latest"
else
  echo 'Canary Edge absent: rollback Edge read is NOT_RUN'
fi
```

**Ожидается:** previous version/revision активны; application healthy/ready; historical и новая
telemetry читаются; shared services/data сохранены.  
**STOP:** rollback installer non-zero, path collision, old image unavailable или readiness не
восстановлена. Не удаляйте paths/volumes и не выполняйте database restore поверх production.
Эскалируйте recovery owner с `LATEST_LOCAL_BACKUP` и #78 procedure.  
**GO:** rollback записан как `PASS`; deployment остаётся `FAIL`, новую попытку не начинайте в том же
окне без нового решения.

### 13.3 Если verified previous bundle неожиданно стал недоступен после preflight

Не применяйте шаг 13.2 с пустыми переменными и не переключайте symlink вручную. Installer мог
уже переместить previous release из `releases/` в `/srv/apps/archive/senior-pomidor/`; такой recovery path не является
проверенным bundle rollback.

Оставьте `senior-pomidor.service` в текущем состоянии, соберите bounded diagnostics и эскалируйте recovery owner.
Если application недоступно, recovery owner выбирает между повторным получением verified old bundle и
отдельно одобренным emergency recovery. Не делайте database restore и не удаляйте release/archive paths.

## 14. Наблюдение 60 минут

**Где:** `S1`, Grafana/operator read surfaces.  
**Риск:** `1 — низкий`, но ошибка означает `4 — rollback`.

Не закрывайте окно сразу после первого зелёного `/ready`. Проверяйте минимум в моменты `T+0`, `T+20`,
`T+40`, `T+60` минут и не менее двух freshness windows.

В каждый момент повторите:

```bash
date -u +'%Y-%m-%dT%H:%M:%SZ'
systemctl is-active senior-pomidor.service
curl --fail --silent --show-error "${API_URL}/ready"
if [[ -n "${CANARY_EDGE_ID}" ]]; then
  curl --fail --silent --show-error \
    "${API_URL}/health/summary?node_id=${CANARY_EDGE_ID}"
  curl --fail --silent --show-error \
    "${API_URL}/api/v1/operator/edges/${CANARY_EDGE_ID}/reliability"
else
  echo 'Canary Edge absent: Edge observation is NOT_RUN'
fi
```

Проверяйте:

```text
[ ] no restart loop
[ ] no worker freshness gap
[ ] no silent loss
[ ] no unintended duplicates
[ ] bounded spool/backlog
[ ] expected alert non-firing/firing/recovery behavior
[ ] stable listeners and exposure
[ ] no privacy/export violation
```

**STOP и rollback:** любой required failure, data mismatch, unbounded backlog/resource growth,
freshness/alert/privacy anomaly.  
**GO:** 60-minute canary gate `PASS`; broader Edge rollout требует отдельного approved procedure.

## 15. Следующий backup и 24-hour observation

**Где:** production monitoring и принятая #77 backup system.  
**Риск:** `2 — умеренный`.

Не выключайте scheduled timers:

```bash
systemctl is-enabled senior-pomidor-backup-daily.timer
systemctl is-enabled senior-pomidor-backup-weekly.timer
systemctl list-timers \
  senior-pomidor-backup-daily.timer senior-pomidor-backup-weekly.timer
```

После следующего scheduled run:

```bash
sudo systemctl show senior-pomidor-backup@daily.service \
  --property=Result --property=ExecMainStatus --property=ActiveState --no-pager
sudo journalctl -u senior-pomidor-backup@daily.service -n 120 --no-pager
```

Для полного #189 gate подтверждается также encrypted local/off-site result из #77. Наблюдайте точную
Core/Edge пару непрерывно 24 часа. Разрыв интервала начинает 24-hour observation заново.

**Ожидается:** у завершившегося oneshot backup `Result=success` и `ExecMainStatus=0`
(`ActiveState=inactive` допустим); обе destinations имеют требуемый status, Core/Edge остаются
стабильными 24 часа.  
**STOP:** scheduled backup не выполнился, destination failure скрыт, observation прервано или появились
count/duplicate/freshness/privacy/resource mismatches. Итог остаётся `FAIL` или `NOT_RUN`.  
**GO:** production observation и backup gate `PASS`.

## 16. Финальная фиксация

**Где:** `L`, sanitized evidence checkout.  
**Риск:** `1 — низкий`.

После добавления bounded canary/production evidence:

```powershell
python -m tools.release_qualification validate `
  --kind release-validation --mode full --require-pass `
  --report "docs/release-evidence/$ReportId/release-validation.json" `
  --core-sha $CoreSha --core-image $CoreImage --core-digest $CoreDigest `
  --edge-sha $EdgeSha --edge-image $EdgeImage --edge-digest $EdgeDigest
```

В sanitized evidence не включайте raw logs, payloads, hostnames, addresses, network identifiers,
paths, service/process/boot IDs, credentials или dumps.

**Ожидается:** validator code `0`, overall `PASS`, independent review `PASS`.  
**STOP:** любой required `FAIL/NOT_RUN`, identity drift или reviewer concern. #189 не закрывать.  
**GO:** release owner может завершить change record и принять решение о закрытии promotion.

## Короткая аварийная карточка

```text
1. НЕ ПАНИКОВАТЬ И НЕ ПОВТОРЯТЬ FAILED COMMAND.
2. НЕ ЗАПУСКАТЬ down -v И НЕ ТРОГАТЬ PostgreSQL/Grafana/Ollama.
3. Проверить: readlink -f /srv/apps/senior-pomidor/app
4. Проверить: APP_IMAGE — вывести только эту строку, не весь runtime.env.
5. Если active=old: вернуть OLD_APP_IMAGE, service не перезапускать вслепую.
6. Если active=new: выполнить раздел 13 с OLD bundle/checksum/image.
7. Проверить /health, /ready, latest telemetry и historical reads.
8. Если rollback не восстановил readiness: STOP, recovery owner + #78; не делать in-place restore.
```

## Журнал выполнения

| Шаг | Status | UTC | Evidence/note |
| --- | --- | --- | --- |
| 1. Approval и две SSH-сессии | NOT_RUN | — | — |
| 2. Release gates | NOT_RUN | — | — |
| 3. New/old assets verified | NOT_RUN | — | — |
| 4. Assets transferred | NOT_RUN | — | — |
| 5. Current state recorded | NOT_RUN | — | — |
| 6. Production preflight | NOT_RUN | — | — |
| 7. #77/#78 recovery gate | NOT_RUN | — | — |
| 7.2 Local weekly backup | NOT_RUN | — | — |
| 8. Rollback assets ready | NOT_RUN | — | — |
| 9. APP_IMAGE switched | NOT_RUN | — | — |
| 10. Runtime installed | NOT_RUN | — | — |
| 11. Application restarted | NOT_RUN | — | — |
| 12. Fast checks | NOT_RUN | — | — |
| 12.2 Core canary path | NOT_RUN | — | — |
| 12.3 Edge reliability/Grafana | NOT_RUN | — | — |
| 14. 60-minute observation | NOT_RUN | — | — |
| 15. Backup + 24-hour observation | NOT_RUN | — | — |
| 16. Full validation/review | NOT_RUN | — | — |
| Rollback, если потребовался | NOT_RUN | — | — |

## Связанные документы

- [`ISSUE_189_PRODUCTION_PROMOTION_VERIFICATION.md`](ISSUE_189_PRODUCTION_PROMOTION_VERIFICATION.md)
- [`UBUNTU_HOST.md`](UBUNTU_HOST.md)
- [`OPERATIONS.md`](OPERATIONS.md)
- [`CONTRACTS.md`](CONTRACTS.md)
- [`POST_MERGE_PREPRODUCTION_QUALIFICATION.md`](POST_MERGE_PREPRODUCTION_QUALIFICATION.md)
- [`release-evidence/README.md`](release-evidence/README.md)
