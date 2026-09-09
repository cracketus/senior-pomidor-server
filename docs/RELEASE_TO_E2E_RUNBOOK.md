# Подготовка Server/Core release до E2E qualification

> Выполняйте **только один пронумерованный шаг за раз**. После каждого шага прочитайте
> **Ожидается**, **STOP** и **GO**. Не вставляйте в PowerShell команды из нескольких шагов сразу.

## 0. Границы и обозначения

Этот runbook доводит Server/Core release от чистого `main` до проверенного GitHub Release,
immutable GHCR image и локальной operator-записи. На этом он заканчивается: реальная Edge/Core
qualification выполняется отдельно по
[`POST_MERGE_PREPRODUCTION_QUALIFICATION.md`](POST_MERGE_PREPRODUCTION_QUALIFICATION.md).

Места выполнения:

| Метка | Среда | Разрешено этим runbook |
| --- | --- | --- |
| `L` | рабочий ноутбук Windows, PowerShell 7, отдельный чистый Core checkout | локальные проверки, tag и чтение публичных release artifacts |
| `G` | GitHub Actions | обязательные CI/release workflows, запущенные push-событиями |
| `S` | production Ubuntu server | **не использовать и не изменять** |
| `P` | production Raspberry Pi Edge | **не использовать и не изменять** |

Критически важное различие:

- обязательный CI job `docker-e2e` должен пройти на точном `$CoreSha` **до** создания release tag;
- push annotated SemVer tag запускает `.github/workflows/release.yml`, но этот workflow отдельный
  `docker-e2e` не запускает;
- локальный Docker E2E на `L` — дополнительное подтверждение, а CI `docker-e2e` — обязательный gate;
- документ не разрешает production deployment, production Edge qualification, canary или создание
  `docs/release-evidence/*`.

Любое несовпадение SHA, digest, tag, OCI revision или workflow identity означает `STOP`. Не
«исправляйте» identity заменой одной переменной: откройте новую release/qualification campaign.

### Переменные кампании

**Где:** `L`, PowerShell 7, из корня отдельного чистого Core checkout.

Заполните все значения заранее. `$CoreImage` и `$EdgeImage` — только immutable references с
`@sha256:...`; digest нельзя вычислять из Git SHA.

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repo = 'cracketus/senior-pomidor-server'
$ImageRepo = 'ghcr.io/cracketus/senior-pomidor-server'
$EdgeRepo = 'cracketus/senior-pomidor-plant-v2'
$EdgeImageRepo = 'ghcr.io/cracketus/senior-pomidor-edge'
$Version = 'vX.Y.Z'
$CoreSha = '<40-lowercase-hex>'
$CoreImage = 'ghcr.io/cracketus/senior-pomidor-server@sha256:<64-lowercase-hex>'
$CoreDigest = 'sha256:<64-lowercase-hex>'
$EdgeSha = '<40-lowercase-hex>'
$EdgeImage = "$EdgeImageRepo@sha256:<64-lowercase-hex>"
$EdgeDigest = 'sha256:<64-lowercase-hex>'
$EdgeRcRunId = 0

function Assert-NativeSuccess {
  param([Parameter(Mandatory)][string]$Command)
  if ($LASTEXITCODE -ne 0) {
    throw "$Command failed with exit code $LASTEXITCODE"
  }
}
```

Датированный пример первой pinned-пары на 2026-09-05 (не подставляйте его автоматически в новую
кампанию):

```powershell
$CoreSha = '3bcbc15bc94b2eca1d45be8e3713c26d5b0b5c73'
$CoreDigest = 'sha256:7b14b208bab3181fd5234581c5e851d44d4e78fa024f334b90d3611ff04864c0'
$CoreImage = "ghcr.io/cracketus/senior-pomidor-server@$CoreDigest"
$EdgeSha = '553eb44ca7add9a99031f9a096683c1502c5a5a8'
$EdgeDigest = 'sha256:acaef9ffbfe32d9f4bd88dfce714026ea191d8271a5172b531861c6094bf4c43'
$EdgeImage = "$EdgeImageRepo@$EdgeDigest"
$EdgeRcRunId = 33548751432
```

Для примера Core required CI подтверждён
[run 33738751416](https://github.com/cracketus/senior-pomidor-server/actions/runs/33738751416),
а Edge RC CI —
[run 33548751432](https://github.com/cracketus/senior-pomidor-plant-v2/actions/runs/33548751432).

**Ожидается:** одна явно выбранная версия и одна неизменная Core/Edge identity-пара.
**STOP:** используются mutable tags, сокращённые SHA, неизвестный Edge candidate или production paths.
**GO:** значения занесены в приватную operator-запись и не содержат secrets.

## 1. Проверить инструменты и безопасный Docker endpoint

**Где:** `L`. Команд на `S` и `P` нет.

```powershell
$PSVersionTable.PSVersion
Get-Command git, gh, python, nox, docker

git --version
Assert-NativeSuccess 'git --version'
gh --version
Assert-NativeSuccess 'gh --version'
python --version
Assert-NativeSuccess 'python --version'
nox --version
Assert-NativeSuccess 'nox --version'
docker --version
Assert-NativeSuccess 'docker --version'

$DockerOverrideNames = @('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH')
$DockerOverrides = @($DockerOverrideNames | Where-Object { Test-Path "Env:$_" })
if ($DockerOverrides.Count -ne 0) {
  throw "Unset Docker environment overrides before E2E: $($DockerOverrides -join ', ')"
}
$DockerContext = (docker context show).Trim()
Assert-NativeSuccess 'docker context show'
if ([string]::IsNullOrWhiteSpace($DockerContext)) { throw 'Current Docker context is empty' }
docker --context $DockerContext version
Assert-NativeSuccess 'docker version for current context'
$DockerOs = (docker --context $DockerContext info --format '{{.OSType}}').Trim()
Assert-NativeSuccess 'docker info for current context'
$DockerEndpoint = (docker context inspect $DockerContext `
  --format '{{.Endpoints.docker.Host}}').Trim()
Assert-NativeSuccess 'docker context inspect current context'
if ($DockerOs -ne 'linux') { throw "Linux Docker engine required; got $DockerOs" }
if ($DockerEndpoint -notmatch '^(npipe://|unix://)') {
  throw "Local Docker endpoint required; refusing $DockerEndpoint"
}

gh auth status --active --hostname github.com
Assert-NativeSuccess 'gh auth status'
```

Не используйте `gh auth status --show-token` и не копируйте auth output в committed документы.

**Ожидается:** доступны Git, GitHub CLI, Python, Nox и локальный Linux Docker engine; Docker environment
overrides отсутствуют; `$DockerContext` хранит имя проверенного текущего context; `gh` успешно аутентифицирован.
**STOP:** задана любая Docker override-переменная, Docker смотрит на TCP/SSH/production endpoint, engine
не Linux или authentication не работает.
**GO:** все native-команды завершились кодом `0`, локальный `$DockerContext` зафиксирован для шага 3.

## 2. Зафиксировать чистый `main`, новую версию и точный Core SHA

**Где:** `L`.

Сначала убедитесь, что это отдельный release checkout и в нём нет чужих или незавершённых изменений:

```powershell
$BeforeStatus = @(git status --porcelain)
Assert-NativeSuccess 'git status --porcelain'
if ($BeforeStatus.Count -ne 0) { throw 'Release checkout is not clean' }

git fetch origin --prune --tags
Assert-NativeSuccess 'git fetch origin --prune --tags'
git switch main
Assert-NativeSuccess 'git switch main'
git pull --ff-only origin main
Assert-NativeSuccess 'git pull --ff-only origin main'

if ($Version -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$') {
  throw 'Version must be vX.Y.Z without prerelease/build suffixes'
}
$LocalTag = @(git tag --list $Version)
Assert-NativeSuccess 'git tag --list'
$RemoteTag = @(git ls-remote --tags origin "refs/tags/$Version")
Assert-NativeSuccess 'git ls-remote --tags'
if ($LocalTag.Count -ne 0 -or $RemoteTag.Count -ne 0) { throw "$Version already exists" }

$CoreSha = (git rev-parse HEAD).Trim()
Assert-NativeSuccess 'git rev-parse HEAD'
if ($CoreSha -notmatch '^[0-9a-f]{40}$') { throw 'Core SHA is not full lowercase hex' }
$AfterStatus = @(git status --porcelain)
Assert-NativeSuccess 'git status --porcelain'
if ($AfterStatus.Count -ne 0) { throw 'Release checkout changed during preflight' }
git log -1 --format='%H %cI %s' $CoreSha
Assert-NativeSuccess 'git log'
```

**Ожидается:** `main` fast-forwarded к `origin/main`, checkout чист, `$Version` отсутствует локально и
на origin, `$CoreSha` содержит точные 40 lowercase hex.
**STOP:** dirty checkout, non-fast-forward, существующий tag или неожиданный SHA.
**GO:** `$CoreSha` записан и больше не меняется в этой кампании.

## 3. Выполнить локальные проверки до tag

**Где:** `L`. Все данные и Docker resources должны оставаться локальными и disposable.

```powershell
python -m pytest -q
Assert-NativeSuccess 'python -m pytest -q'
nox -s lint format_check types security deps_audit
Assert-NativeSuccess 'nox quality/security/dependency checks'

$DockerOverrides = @($DockerOverrideNames | Where-Object { Test-Path "Env:$_" })
if ($DockerOverrides.Count -ne 0) {
  throw "Docker environment overrides appeared after preflight: $($DockerOverrides -join ', ')"
}
docker context use $DockerContext | Out-Null
Assert-NativeSuccess 'docker context use validated local context'
$E2EDockerContext = (docker context show).Trim()
Assert-NativeSuccess 'docker context show before E2E'
if ($E2EDockerContext -ne $DockerContext) {
  throw "Docker context drifted before E2E: expected $DockerContext; got $E2EDockerContext"
}
$E2EDockerEndpoint = (docker context inspect $E2EDockerContext `
  --format '{{.Endpoints.docker.Host}}').Trim()
Assert-NativeSuccess 'docker context inspect before E2E'
if ($E2EDockerEndpoint -ne $DockerEndpoint -or $E2EDockerEndpoint -notmatch '^(npipe://|unix://)') {
  throw "Validated local Docker endpoint drifted before E2E: $E2EDockerEndpoint"
}

try {
  $env:RUN_DOCKER_E2E = '1'
  python -m pytest -q tests/test_docker_e2e.py -p no:cacheprovider
  Assert-NativeSuccess 'isolated local Docker E2E'
}
finally {
  Remove-Item Env:RUN_DOCKER_E2E -ErrorAction SilentlyContinue
}
if (Test-Path Env:RUN_DOCKER_E2E) { throw 'RUN_DOCKER_E2E leaked into the environment' }

$VerifiedSha = (git rev-parse HEAD).Trim()
Assert-NativeSuccess 'git rev-parse HEAD after local checks'
if ($VerifiedSha -ne $CoreSha) { throw 'Checkout identity changed during local checks' }
```

E2E helper удаляет Docker override-переменные перед Compose, поэтому `docker context use` непосредственно
перед pytest принудительно направляет Compose в тот же сохранённый local context, который проверен в шаге 1.

**Ожидается:** pytest, quality, security, dependency audit и isolated Docker E2E завершаются кодом
`0`; E2E использует проверенные `$DockerContext` и `$DockerEndpoint`; `RUN_DOCKER_E2E` удалён даже при
ошибке теста.
**STOP:** любой check failed, появился Docker override, context/endpoint изменился, Docker E2E пропущен
или checkout SHA изменился. Не создавайте tag.
**GO:** локальные проверки `PASS`; это ещё не заменяет CI gate.

## 4. Найти обязательный CI run на точном SHA

**Где:** команды на `L`; проверяемое выполнение — `G` в `.github/workflows/ci.yml`.

```powershell
$CoreCiRunsJson = gh run list --repo $Repo --workflow ci.yml --branch main `
  --event push --commit $CoreSha --limit 10 `
  --json databaseId,headSha,status,conclusion,url
Assert-NativeSuccess 'gh run list for exact Core SHA'
$CoreCiRuns = @($CoreCiRunsJson | ConvertFrom-Json)
$CoreCiRun = $CoreCiRuns | Where-Object {
  $_.headSha -eq $CoreSha -and $_.status -eq 'completed' -and $_.conclusion -eq 'success'
} | Select-Object -First 1
if ($null -eq $CoreCiRun) { throw 'No successful completed CI run for exact Core SHA' }
$CoreCiRunId = [long]$CoreCiRun.databaseId

$CoreCiViewJson = gh run view $CoreCiRunId --repo $Repo `
  --json headSha,status,conclusion,jobs,url
Assert-NativeSuccess 'gh run view for Core CI'
$CoreCiView = $CoreCiViewJson | ConvertFrom-Json
if ($CoreCiView.headSha -ne $CoreSha -or $CoreCiView.conclusion -ne 'success') {
  throw 'Core CI run identity or conclusion mismatch'
}
$RequiredCoreJobs = @('test', 'quality', 'security', 'docker-e2e', 'core-release-candidate')
foreach ($JobName in $RequiredCoreJobs) {
  $Matches = @($CoreCiView.jobs | Where-Object { $_.name -eq $JobName })
  if ($Matches.Count -ne 1 -or $Matches[0].conclusion -ne 'success') {
    throw "Required Core CI job is not uniquely successful: $JobName"
  }
}
$CoreCiView.url
```

**Ожидается:** один выбранный successful run с `headSha == $CoreSha`; все пять jobs существуют
ровно по одному разу и имеют `success`.
**STOP:** run относится к другому SHA/ветке, job отсутствует, skipped/cancelled/failed или ещё идёт.
**GO:** required CI, включая отдельный `docker-e2e`, имеет `PASS` до tag.

## 5. Проверить Core RC metadata и выбранный Edge RC

**Где:** `L`; artifact создан job `core-release-candidate` на `G`.

```powershell
$RcDir = Join-Path $env:TEMP ("senior-pomidor-core-rc-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $RcDir | Out-Null
gh run download $CoreCiRunId --repo $Repo `
  --name senior-pomidor.core.release-candidate.v1 --dir $RcDir
Assert-NativeSuccess 'gh run download Core RC metadata'

$RcPath = Join-Path $RcDir 'senior-pomidor.core.release-candidate.v1.json'
if (-not (Test-Path -LiteralPath $RcPath -PathType Leaf)) { throw 'Core RC metadata is missing' }
$Rc = Get-Content -LiteralPath $RcPath -Raw | ConvertFrom-Json
if ($Rc.schema_version -ne 'senior-pomidor.core.release-candidate.v1') {
  throw 'Unexpected Core RC metadata schema'
}
if ($Rc.git_sha -ne $CoreSha) { throw 'Core RC SHA mismatch' }
if ($Rc.image_digest -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Invalid Core digest' }
if ($Rc.image_ref -ne "$ImageRepo@$($Rc.image_digest)") { throw 'Core immutable ref mismatch' }
if ($CoreDigest -ne $Rc.image_digest -or $CoreImage -ne $Rc.image_ref) {
  throw 'Core RC artifact does not match the preselected identity'
}
$Platforms = @($Rc.platforms | Sort-Object)
if (($Platforms -join ',') -ne 'linux/amd64,linux/arm64') {
  throw "Unexpected Core platforms: $($Platforms -join ',')"
}

$CoreShaRef = "$ImageRepo`:$CoreSha"
$PinnedCoreRegistryDigest = docker buildx imagetools inspect $CoreImage `
  --format '{{json .Manifest.Digest}}' | ConvertFrom-Json
Assert-NativeSuccess 'inspect pinned Core manifest digest'
$CoreShaRegistryDigest = docker buildx imagetools inspect $CoreShaRef `
  --format '{{json .Manifest.Digest}}' | ConvertFrom-Json
Assert-NativeSuccess 'inspect Core SHA-tag manifest digest'
if ($PinnedCoreRegistryDigest -ne $CoreDigest -or $CoreShaRegistryDigest -ne $CoreDigest) {
  throw 'Core registry digest drifted from the pinned RC artifact'
}
docker pull $CoreImage
Assert-NativeSuccess 'docker pull pinned Core candidate'
$CoreOciRevision = (docker image inspect $CoreImage `
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}').Trim()
Assert-NativeSuccess 'inspect pinned Core OCI revision'
if ($CoreOciRevision -ne $CoreSha) { throw 'Pinned Core OCI revision mismatch' }

```

Проверьте отдельно выбранный Edge candidate. `$EdgeRcRunId` должен быть ID именно publishing run,
а не любого успешного workflow на том же SHA:

```powershell
if ($EdgeSha -notmatch '^[0-9a-f]{40}$') { throw 'Invalid Edge SHA' }
if ($EdgeDigest -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Invalid Edge digest' }
if ($EdgeImage -ne "$EdgeImageRepo@$EdgeDigest") {
  throw 'Edge immutable ref/digest mismatch'
}
if ($EdgeRcRunId -le 0) { throw 'Select the exact Edge RC publishing run ID' }

$EdgeRunJson = gh run view $EdgeRcRunId --repo $EdgeRepo `
  --json workflowName,headSha,status,conclusion,jobs,url
Assert-NativeSuccess 'gh run view Edge RC'
$EdgeRun = $EdgeRunJson | ConvertFrom-Json
if ($EdgeRun.workflowName -ne 'Edge release candidate' -or
    $EdgeRun.headSha -ne $EdgeSha -or $EdgeRun.status -ne 'completed' -or
    $EdgeRun.conclusion -ne 'success') {
  throw 'Edge RC workflow identity or conclusion mismatch'
}
$EdgePublishJobs = @($EdgeRun.jobs | Where-Object {
  $_.name -eq 'Publish multi-arch release candidate'
})
if ($EdgePublishJobs.Count -ne 1 -or $EdgePublishJobs[0].conclusion -ne 'success') {
  throw 'Edge RC publishing job is not uniquely successful'
}

$EdgeArtifactName = "edge-release-candidate-$EdgeSha"
$EdgeArtifactDir = Join-Path $env:TEMP ("senior-pomidor-edge-rc-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $EdgeArtifactDir | Out-Null
gh run download $EdgeRcRunId --repo $EdgeRepo `
  --name $EdgeArtifactName --dir $EdgeArtifactDir
Assert-NativeSuccess 'gh run download Edge RC metadata'
$EdgeRcPath = Join-Path $EdgeArtifactDir 'edge-release-candidate.json'
if (-not (Test-Path -LiteralPath $EdgeRcPath -PathType Leaf)) {
  throw 'Edge RC metadata is missing'
}
$EdgeRc = Get-Content -LiteralPath $EdgeRcPath -Raw | ConvertFrom-Json
$ExpectedEdgeShaTag = "$EdgeImageRepo`:$EdgeSha"
if ($EdgeRc.schema_version -ne 'senior-pomidor.edge.release-candidate.v1' -or
    $EdgeRc.commit_sha -ne $EdgeSha -or $EdgeRc.image -ne $EdgeImageRepo -or
    $EdgeRc.digest -ne $EdgeDigest -or $EdgeRc.immutable_ref -ne $EdgeImage -or
    $EdgeRc.sha_tag -ne $ExpectedEdgeShaTag -or $EdgeRc.workflow_run_url -ne $EdgeRun.url) {
  throw 'Edge RC metadata does not bind the selected run, SHA, image, and digest'
}
$EdgePlatforms = @($EdgeRc.platforms | Sort-Object)
if (($EdgePlatforms -join ',') -ne 'linux/amd64,linux/arm64') {
  throw "Unexpected Edge platforms: $($EdgePlatforms -join ',')"
}

$RegistryEdgeDigest = docker buildx imagetools inspect $EdgeImage `
  --format '{{json .Manifest.Digest}}' | ConvertFrom-Json
Assert-NativeSuccess 'inspect Edge manifest digest'
$RegistryEdgeShaDigest = docker buildx imagetools inspect $ExpectedEdgeShaTag `
  --format '{{json .Manifest.Digest}}' | ConvertFrom-Json
Assert-NativeSuccess 'inspect Edge SHA-tag manifest digest'
if ($RegistryEdgeDigest -ne $EdgeDigest -or $RegistryEdgeShaDigest -ne $EdgeDigest) {
  throw 'Edge registry digest or SHA-tag drifted from the selected RC run metadata'
}
docker pull $EdgeImage
Assert-NativeSuccess 'docker pull Edge candidate'
$EdgeOciRevision = (docker image inspect $EdgeImage `
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}').Trim()
Assert-NativeSuccess 'inspect Edge OCI revision'
if ($EdgeOciRevision -ne $EdgeSha) { throw 'Edge OCI revision mismatch' }
$EdgeRun.url
```

**Ожидается:** Core schema/SHA/digest/ref/platforms, pinned registry manifest, SHA-tag и OCI revision
совпали; скачанный из выбранного Edge run metadata artifact связывает run URL, SHA, immutable ref,
digest, SHA-tag и platforms, а registry и OCI revision подтверждают эту же identity.
**STOP:** artifact отсутствует/просрочен, Core SHA-tag больше не указывает на `$CoreDigest`, любая
identity расходится, Edge artifact не принадлежит `$EdgeRcRunId`, ref mutable, platform неожиданна
или Edge run не является успешным `Edge release candidate`.
**GO:** immutable Core/Edge identity, registry manifests и их RC runs зафиксированы.

## 6. Проверить changelog и подготовить annotated tag

**Где:** `L`. На этом шаге tag остаётся локальным.

```powershell
$PreviousVersion = (git describe --tags --abbrev=0 "$CoreSha^").Trim()
Assert-NativeSuccess 'git describe previous tag'
git log --oneline "$PreviousVersion..$CoreSha"
Assert-NativeSuccess 'git log release range'
git diff "$PreviousVersion..$CoreSha" -- CHANGELOG.md
Assert-NativeSuccess 'git diff CHANGELOG.md'
Get-Content -LiteralPath CHANGELOG.md

$StillClean = @(git status --porcelain)
Assert-NativeSuccess 'git status before tagging'
if ($StillClean.Count -ne 0) { throw 'Release checkout is not clean before tagging' }
if ((git rev-parse HEAD).Trim() -ne $CoreSha) { throw 'HEAD no longer matches Core SHA' }
Assert-NativeSuccess 'git rev-parse HEAD before tagging'

git tag -a $Version $CoreSha -m "Senior Pomidor Server $Version"
Assert-NativeSuccess 'git tag -a'
$TagType = (git cat-file -t "refs/tags/$Version").Trim()
Assert-NativeSuccess 'git cat-file tag type'
$TagRevision = (git rev-list -n 1 $Version).Trim()
Assert-NativeSuccess 'git rev-list tag revision'
if ($TagType -ne 'tag' -or $TagRevision -ne $CoreSha) {
  throw 'Annotated tag type or revision mismatch'
}
git show --no-patch --show-signature $Version
Assert-NativeSuccess 'git show annotated tag'
```

Перед `git tag` оператор обязан подтвердить, что `CHANGELOG.md` и автоматически генерируемые GitHub
release notes корректно описывают диапазон `$PreviousVersion..$CoreSha`, известные ограничения и
trusted-LAN boundary. Если notes требуют изменения, изменение должно пройти новый CI на новом SHA.

**Ожидается:** локальный объект имеет тип `tag` и разрешается ровно в `$CoreSha`.
**STOP:** changelog неполон, checkout изменён, tag lightweight или revision расходится.
**GO:** annotated tag готов к единственному разрешённому push.

## 7. Отправить tag и дождаться release workflow

**Где:** push выполняется на `L`; `.github/workflows/release.yml` выполняется на `G`.

```powershell
$PrePushPinnedDigest = docker buildx imagetools inspect $CoreImage `
  --format '{{json .Manifest.Digest}}' | ConvertFrom-Json
Assert-NativeSuccess 'recheck pinned Core digest before tag push'
$PrePushShaDigest = docker buildx imagetools inspect $CoreShaRef `
  --format '{{json .Manifest.Digest}}' | ConvertFrom-Json
Assert-NativeSuccess 'recheck Core SHA-tag digest before tag push'
if ($PrePushPinnedDigest -ne $CoreDigest -or $PrePushShaDigest -ne $CoreDigest) {
  throw 'Core registry identity drifted before tag push'
}

git push origin $Version
Assert-NativeSuccess 'git push origin release tag'

$RemoteRevision = (git ls-remote origin "refs/tags/$Version^{}" | ForEach-Object {
  ($_ -split '\s+')[0]
}).Trim()
Assert-NativeSuccess 'git ls-remote peeled release tag'
if ($RemoteRevision -ne $CoreSha) { throw 'Remote annotated tag revision mismatch' }

$ReleaseRun = $null
$DiscoveryWindow = [TimeSpan]::FromMinutes(10)
$DiscoveryDeadline = [DateTimeOffset]::UtcNow.Add($DiscoveryWindow)
$Attempt = 0
while ($null -eq $ReleaseRun -and [DateTimeOffset]::UtcNow -lt $DiscoveryDeadline) {
  $Attempt++
  $ReleaseRunsJson = gh run list --repo $Repo --workflow release.yml --event push `
    --commit $CoreSha --limit 10 `
    --json databaseId,headBranch,headSha,status,conclusion,url
  Assert-NativeSuccess 'gh run list release workflow'
  $ReleaseRun = @($ReleaseRunsJson | ConvertFrom-Json) | Where-Object {
    $_.headBranch -eq $Version -and $_.headSha -eq $CoreSha
  } | Select-Object -First 1
  if ($null -eq $ReleaseRun) {
    Write-Host "Release workflow registration is pending (attempt $Attempt); waiting 10 seconds."
    Start-Sleep -Seconds 10
  }
}
if ($null -eq $ReleaseRun) {
  throw "Release workflow registration is still pending after $($DiscoveryWindow.TotalMinutes) minutes; tag $Version is already pushed. Inspect gh run list and do not push the tag again."
}
$ReleaseRunStatus = [string]$ReleaseRun.status
if ($ReleaseRunStatus -eq 'completed') {
  Write-Host "Release workflow discovered with terminal status: $ReleaseRunStatus."
} else {
  Write-Host "Release workflow discovered with pending status: $ReleaseRunStatus; waiting for completion."
}
$ReleaseRunId = [long]$ReleaseRun.databaseId

gh run watch $ReleaseRunId --repo $Repo --compact --exit-status
Assert-NativeSuccess 'gh run watch release workflow'

$ReleaseViewJson = gh run view $ReleaseRunId --repo $Repo `
  --json headBranch,headSha,status,conclusion,jobs,url
Assert-NativeSuccess 'gh run view release workflow'
$ReleaseView = $ReleaseViewJson | ConvertFrom-Json
if ($ReleaseView.headBranch -ne $Version -or $ReleaseView.headSha -ne $CoreSha -or
    $ReleaseView.conclusion -ne 'success') {
  throw 'Release workflow identity or conclusion mismatch'
}
$RequiredReleaseJobs = @('validate-tag', 'test-quality-security', 'image-scans', 'publish')
foreach ($JobName in $RequiredReleaseJobs) {
  $Matches = @($ReleaseView.jobs | Where-Object { $_.name -eq $JobName })
  if ($Matches.Count -ne 1 -or $Matches[0].conclusion -ne 'success') {
    throw "Required release job is not uniquely successful: $JobName"
  }
}
$ReleaseView.url
```

`release.yml` повторяет tests/quality/security, scans и publish, но **не содержит `docker-e2e`**.
Его обязательное доказательство — exact-SHA CI run из шага 4.

Перед необратимым push Git tag команды повторно проверяют immutable `$CoreImage` и SHA-tag против
`$CoreDigest`. Локальная машина не публикует GHCR alias и не требует package-write token:
аутентифицированный `release.yml` создаёт version alias и повторно сравнивает его manifest с SHA-tag.

**Ожидается:** pinned ref и SHA-tag всё ещё указывают на `$CoreDigest`, remote annotated tag
разрешается в `$CoreSha`, workflow обнаружен в bounded 10-minute window (его pending/queued status
отдельно выведен), четыре release jobs успешны.
**STOP:** pre-push digest drift, push rejected, tag/revision drift, workflow не зарегистрировался за
10 минут или любой job не `success`. После успешного push tag не отправляйте повторно: проверьте
pending run через `gh run list`.
**GO:** authenticated release workflow опубликовал version alias, затем переходите к независимой
проверке artifacts.

## 8. Проверить GitHub Release и runtime bundle

**Где:** `L`.

```powershell
$ReleaseJson = gh release view $Version --repo $Repo `
  --json tagName,isDraft,isPrerelease,url,assets,body
Assert-NativeSuccess 'gh release view'
$Release = $ReleaseJson | ConvertFrom-Json
if ($Release.tagName -ne $Version -or $Release.isDraft -or $Release.isPrerelease) {
  throw 'GitHub Release tag/state mismatch'
}
if ([string]::IsNullOrWhiteSpace([string]$Release.body)) {
  throw 'Generated GitHub release notes are empty'
}
$Release.body

$AssetDir = Join-Path $env:TEMP ("senior-pomidor-release-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $AssetDir | Out-Null
gh release download $Version --repo $Repo `
  --pattern "senior-pomidor-runtime-$Version.tar.gz*" --dir $AssetDir
Assert-NativeSuccess 'gh release download runtime assets'

$Bundle = Join-Path $AssetDir "senior-pomidor-runtime-$Version.tar.gz"
$ChecksumPath = "$Bundle.sha256"
if (-not (Test-Path -LiteralPath $Bundle -PathType Leaf) -or
    -not (Test-Path -LiteralPath $ChecksumPath -PathType Leaf)) {
  throw 'Runtime bundle or checksum asset is missing'
}
$ExpectedBundleSha = ((Get-Content -LiteralPath $ChecksumPath -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
$ActualBundleSha = (Get-FileHash -LiteralPath $Bundle -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ExpectedBundleSha -notmatch '^[0-9a-f]{64}$' -or $ActualBundleSha -ne $ExpectedBundleSha) {
  throw 'Runtime bundle SHA-256 mismatch'
}

$BundleVersion = (tar.exe -xOf $Bundle './VERSION').Trim()
Assert-NativeSuccess 'read VERSION from runtime bundle'
$BundleRevision = (tar.exe -xOf $Bundle './REVISION').Trim()
Assert-NativeSuccess 'read REVISION from runtime bundle'
if ($BundleVersion -ne $Version -or $BundleRevision -ne $CoreSha) {
  throw 'Runtime bundle version/revision mismatch'
}
$PythonSources = @(tar.exe -tf $Bundle | Where-Object { $_ -match '(^|/)(app|migrations)/|\.py$' })
Assert-NativeSuccess 'list runtime bundle'
if ($PythonSources.Count -ne 0) { throw 'Runtime bundle unexpectedly contains Python source' }
$Release.url
```

**Ожидается:** GitHub Release опубликован для `$Version`, два assets скачаны, checksum совпадает,
bundle содержит `$Version`/`$CoreSha` и не содержит Python source.
**STOP:** draft/prerelease, отсутствующий asset, checksum или metadata mismatch.
**GO:** runtime bundle identity `PASS`.

## 9. Проверить GHCR manifest, digest и OCI revision

**Где:** `L`, через локальный Linux Docker engine.

```powershell
$VersionRef = "$ImageRepo`:$Version"
$ShaRef = "$ImageRepo`:$CoreSha"
$VersionDigest = docker buildx imagetools inspect $VersionRef `
  --format '{{json .Manifest.Digest}}' | ConvertFrom-Json
Assert-NativeSuccess 'inspect version manifest digest'
$ShaDigest = docker buildx imagetools inspect $ShaRef `
  --format '{{json .Manifest.Digest}}' | ConvertFrom-Json
Assert-NativeSuccess 'inspect SHA manifest digest'
if ($VersionDigest -ne $CoreDigest -or $ShaDigest -ne $CoreDigest) {
  throw 'Version/SHA tag does not resolve to the pinned Core digest'
}

$Manifest = docker buildx imagetools inspect $VersionRef --raw | ConvertFrom-Json
Assert-NativeSuccess 'inspect raw version manifest'
$PublishedPlatforms = @($Manifest.manifests | Where-Object {
  $_.platform.os -ne 'unknown' -and $_.platform.architecture -ne 'unknown'
} | ForEach-Object {
  "$($_.platform.os)/$($_.platform.architecture)"
} | Sort-Object -Unique)
if (($PublishedPlatforms -join ',') -ne 'linux/amd64,linux/arm64') {
  throw "Unexpected published platforms: $($PublishedPlatforms -join ',')"
}

docker pull $VersionRef
Assert-NativeSuccess 'docker pull release image'
$OciRevision = (docker image inspect $VersionRef `
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}').Trim()
Assert-NativeSuccess 'inspect OCI revision'
if ($OciRevision -ne $CoreSha) { throw 'Published OCI revision mismatch' }
```

**Ожидается:** version tag и full-SHA tag указывают на `$CoreDigest`, manifest содержит ровно
`linux/amd64` и `linux/arm64`, OCI revision равен `$CoreSha`.
**STOP:** registry unavailable, digest/platform/revision drift или pull требует неожиданного private access.
**GO:** Git, CI artifact, GitHub Release, runtime bundle и GHCR identity согласованы.

## 10. Сформировать локальную operator-запись и остановиться

**Где:** `L`. Запись создаётся в пользовательской папке Documents, не в Git checkout и не в
`docs/release-evidence/`.

```powershell
$RecordRoot = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'SeniorPomidorPrivateRecords'
$CheckoutRoot = [IO.Path]::GetFullPath((Get-Location).Path).TrimEnd('\')
$RecordRootFull = [IO.Path]::GetFullPath($RecordRoot).TrimEnd('\')
if ($RecordRootFull.StartsWith("$CheckoutRoot\", [StringComparison]::OrdinalIgnoreCase) -or
    $RecordRootFull -eq $CheckoutRoot) {
  throw 'Operator record must be outside the Git checkout'
}
New-Item -ItemType Directory -Force -Path $RecordRoot | Out-Null
$CampaignId = "core-$CoreSha-edge-$EdgeSha-edge-run-$EdgeRcRunId"
$RecordPath = Join-Path $RecordRoot "release-to-e2e-$Version-$CampaignId.txt"
if (Test-Path -LiteralPath $RecordPath) {
  throw "Operator record already exists; refusing to overwrite: $RecordPath"
}
$RecordLines = @(
  "recorded_at_utc=$([DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))",
  "campaign_id=$CampaignId",
  "version=$Version",
  "core_sha=$CoreSha",
  "core_image=$CoreImage",
  "core_digest=$CoreDigest",
  "edge_sha=$EdgeSha",
  "edge_image=$EdgeImage",
  "edge_digest=$EdgeDigest",
  "edge_rc_run=$($EdgeRun.url)",
  "core_ci_run=$($CoreCiView.url)",
  "release_run=$($ReleaseView.url)",
  "github_release=$($Release.url)",
  "runtime_bundle_sha256=$ActualBundleSha",
  'immutable_core_identity=PASS',
  'required_core_ci=PASS',
  'edge_identity_and_rc_ci=PASS',
  'real_edge_core_compatibility=NOT_RUN',
  'isolated_staging_scenarios=NOT_RUN',
  'staging_24h_soak=NOT_RUN',
  'application_only_rollback_rehearsal=NOT_RUN',
  'production_canary=NOT_RUN',
  'issue_189=BLOCKED'
)
$RecordLines | Out-File -LiteralPath $RecordPath -Encoding utf8 -NoClobber
Get-Item -LiteralPath $RecordPath | Select-Object FullName, Length, LastWriteTimeUtc
```

Не добавляйте credentials, tokens, private hostnames/addresses/paths, raw logs или production data.
Проверка шага 5 относится только к явно выбранному Edge SHA/image/digest и exact publishing run;
пример из раздела 0 не делает новую Edge identity автоматически принятой.

**Ожидается:** новая campaign-qualified локальная secret-free запись содержит exact identities, ссылки и
честные статусы; записи других кампаний сохранены.
**STOP:** Edge identity/RC CI не подтверждены, обнаружен identity drift, запись содержит private data или
путь записи этой кампании уже существует.
**GO:** Server/Core release готов **только к следующему отдельно разрешаемому pre-production этапу**.
На `S` и `P` ничего не выполнено и не изменено.

## Итоговая граница gate

| Gate | Условие `PASS` | Статус на границе этого runbook |
| --- | --- | --- |
| Immutable Core identity и required CI | exact `$CoreSha`, `$CoreDigest`, RC metadata, `test`, `quality`, `security`, `docker-e2e`, `core-release-candidate` совпадают | `PASS` только после шагов 4–9 |
| Edge identity и RC CI | явно выбранные `$EdgeSha`, `$EdgeImage`, `$EdgeDigest` и exact-SHA Edge RC run совпадают | `PASS` только после независимой проверки кандидата |
| Real Edge/Core compatibility | реальный Edge software path с той же immutable-парой | `NOT_RUN` |
| Isolated staging scenarios | все обязательные failure/recovery scenarios на изолированном staging | `NOT_RUN` |
| 24-hour soak | непрерывный 24-часовой интервал без fail-conditions | `NOT_RUN` |
| Application-only rollback rehearsal | возврат только application image с сохранением shared state | `NOT_RUN` |
| One-Edge production canary | отдельное production approval и реальный canary после Core-first rollout | `NOT_RUN` |
| Общий promotion status #189 | все обязательные последующие gates имеют evidence `PASS` | `BLOCKED` |

Synthetic fixtures, server-only tests и зелёный CI не дают `PASS` реальной compatibility,
staging/soak, rollback или canary. Любой identity drift требует новой кампании и повторения всех gate.
Canary требует отдельного production approval. Application-only rollback меняет только application
image и не изменяет PostgreSQL, Grafana, Ollama, volumes или release evidence.

Следующие документы, без дублирования их процедур:

- [`POST_MERGE_PREPRODUCTION_QUALIFICATION.md`](POST_MERGE_PREPRODUCTION_QUALIFICATION.md) — реальная
  Edge/Core compatibility, isolated staging, soak и exact-bundle rollback rehearsal;
- [`ISSUE_189_PRODUCTION_PROMOTION_VERIFICATION.md`](ISSUE_189_PRODUCTION_PROMOTION_VERIFICATION.md) —
  полный promotion gate и fail-closed статус;
- [`PRODUCTION_RELEASE_INSTALLATION_RUNBOOK.md`](PRODUCTION_RELEASE_INSTALLATION_RUNBOOK.md) — только
  после принятых pre-production evidence и отдельного production approval.
