from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_is_annotated_tag_only_multiarch_and_immutable() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "git cat-file -t" in workflow
    assert "linux/amd64,linux/arm64" in workflow
    assert "ghcr.io/cracketus/senior-pomidor-server" in workflow
    assert "${{ env.IMAGE }}:${{ env.VERSION }}" in workflow
    assert "git rev-list -n 1" in workflow
    assert "${{ env.IMAGE }}:${{ env.COMMIT_SHA }}" in workflow
    assert ":latest" not in workflow
    assert "imagetools inspect" in workflow
    assert "org.opencontainers.image.revision" in workflow
    assert 'imagetools inspect "$IMAGE:$VERSION" --raw' in workflow
    assert "if: steps.existing-image.outputs.exists != 'true'" in workflow
    assert 'docker pull "$IMAGE:$COMMIT_SHA"' in workflow
    assert '--tag "$IMAGE:$VERSION"' in workflow
    assert "refusing release promotion" in workflow
    assert "already exists without" not in workflow
    assert workflow.count('echo "exists=false" >> "$GITHUB_OUTPUT"') == 1
    assert "gh release upload" in workflow
    assert "--clobber" in workflow
    assert "nox -s tests lint format_check types security deps_audit" in workflow
    assert workflow.count("aquasecurity/trivy-action") == 2


def test_release_test_job_fetches_history_for_historical_reviewer_fixtures() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))

    checkout = workflow["jobs"]["test-quality-security"]["steps"][0]
    assert checkout == {
        "uses": "actions/checkout@v7",
        "with": {"fetch-depth": 0},
    }


def test_runtime_bundle_builder_includes_operations_assets_without_source() -> None:
    builder = (ROOT / "deploy/scripts/build-runtime-bundle.sh").read_text(encoding="utf-8")

    for runtime_asset in (
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "mosquitto.conf",
        "config/daily_story",
        "deploy/apt",
        "deploy/systemd",
        "deploy/scripts",
    ):
        assert runtime_asset in builder
    assert "-name '*.py'" in builder
    assert '"$stage/REVISION"' in builder
    assert "SOURCE_REVISION" in builder
    assert "sha256sum" in builder


def test_production_environment_template_disables_docs_and_shared_service_profiles() -> None:
    environment = (ROOT / "deploy/senior-pomidor.env.example").read_text(encoding="utf-8")

    assert "COMPOSE_PROFILES=cloud-export" in environment
    assert "API_DOCS_ENABLED=false" in environment
    assert "APP_IMAGE=ghcr.io/cracketus/senior-pomidor-server:vX.Y.Z" in environment
    assert "observability" not in environment
    assert "OLLAMA_IMAGE" not in environment


def test_backup_audit_dumps_exclude_role_password_verifiers() -> None:
    linux_backup = (ROOT / "deploy/scripts/backup.sh").read_text(encoding="utf-8")
    windows_backup = (ROOT / "tools/backup_data.ps1").read_text(encoding="utf-8")

    assert "pg_dumpall --globals-only --no-role-passwords" in linux_backup
    assert "pg_dumpall --globals-only --no-role-passwords" in windows_backup


def test_windows_backup_quotes_csv_field_separator_for_powershell() -> None:
    windows_backup = (ROOT / "tools/backup_data.ps1").read_text(encoding="utf-8")

    assert "--field-separator ','" in windows_backup
    assert "--field-separator=," not in windows_backup


def test_operations_preserves_packaged_backup_retention_and_configured_restore_identity() -> None:
    operations = (ROOT / "docs/OPERATIONS.md").read_text(encoding="utf-8")

    assert "The source-free Linux production bundle does not contain `tools.backup`" in operations
    assert "senior-pomidor-backup@daily.service" in operations
    assert "senior-pomidor-backup@weekly.service" in operations
    assert "retain daily sets for 30 days" in operations
    assert "weekly sets for 56 days" in operations
    assert "--username $env:POSTGRES_USER --dbname $env:POSTGRES_DB" in operations
    assert "pg_dump -U $env:POSTGRES_USER $env:POSTGRES_DB" in operations
    assert "psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB" in operations


def test_production_installation_requires_verified_rollback_bundle() -> None:
    runbook = (ROOT / "docs/PRODUCTION_RELEASE_INSTALLATION_RUNBOOK.md").read_text(encoding="utf-8")

    assert "Проверенный bundle предыдущего release обязателен для rollback" in runbook
    assert "old image или проверенный old bundle недоступны" in runbook
    assert "HAVE_OLD_BUNDLE" not in runbook
    assert "HaveOldBundle" not in runbook
    assert "$ExpectedOldRevision = '<accepted-40-lowercase-previous-core-sha>'" in runbook
    assert "$OldBundleRevision -ne $ExpectedOldRevision" in runbook
    assert '[[ "${OLD_REVISION}" == "${EXPECTED_OLD_REVISION}" ]]' in runbook
    assert 'sudo tar -xOf "${OLD_ARCHIVE}" ./REVISION' in runbook


def test_production_runbook_skips_reliability_checks_without_canary() -> None:
    runbook = (ROOT / "docs/PRODUCTION_RELEASE_INSTALLATION_RUNBOOK.md").read_text(encoding="utf-8")
    section = runbook.split("### 12.3 Edge reliability и Grafana", 1)[1].split("## 13. Rollback", 1)[0]

    guard = 'if [[ -n "${CANARY_EDGE_ID}" ]]; then'
    operator_endpoint = '"${API_URL}/api/v1/operator/edges/${CANARY_EDGE_ID}/reliability"'
    summary_endpoint = '"${API_URL}/health/summary?node_id=${CANARY_EDGE_ID}"'
    not_run = "Canary Edge absent: reliability API checks are NOT_RUN"

    assert guard in section
    assert operator_endpoint in section
    assert summary_endpoint in section
    assert not_run in section
    assert section.index(guard) < section.index(operator_endpoint) < section.index(not_run)
    assert section.index(guard) < section.index(summary_endpoint) < section.index(not_run)
