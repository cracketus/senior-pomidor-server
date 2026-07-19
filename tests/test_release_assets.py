from pathlib import Path

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
    assert "gh release upload" in workflow
    assert "--clobber" in workflow
    assert "nox -s tests lint format_check types security deps_audit" in workflow
    assert workflow.count("aquasecurity/trivy-action") == 2


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
