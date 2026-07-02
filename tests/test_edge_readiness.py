from pathlib import Path

from tools import edge_readiness


def test_run_checks_reports_all_ready(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        edge_readiness,
        "get_json",
        lambda url, _timeout: (
            200,
            {"status": "ok"} if url.endswith("/health") else {"ready": True, "database": "ok", "migration": "current"},
            None,
        ),
    )

    class FakeSocket:
        def __enter__(self) -> "FakeSocket":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(edge_readiness.socket, "create_connection", lambda *_args, **_kwargs: FakeSocket())

    checks = edge_readiness.run_checks(
        api_base_url="http://test",
        mqtt_host="broker",
        mqtt_port=1883,
        photo_storage_dir=tmp_path / "photos",
        timeout_seconds=1,
    )

    assert [check.name for check in checks] == ["api", "readiness", "mqtt", "photo_storage"]
    assert all(check.status == "ok" for check in checks)


def test_readiness_check_reports_migration_details(monkeypatch) -> None:
    monkeypatch.setattr(
        edge_readiness,
        "get_json",
        lambda _url, _timeout: (
            503,
            {
                "ready": False,
                "database": "ok",
                "migration": "mismatch",
                "current_revision": "old",
                "head_revision": "new",
            },
            None,
        ),
    )

    check = edge_readiness.check_readiness("http://test", 1)

    assert check.status == "failed"
    assert check.details["migration"] == "mismatch"
    assert check.details["current_revision"] == "old"
    assert check.details["head_revision"] == "new"
