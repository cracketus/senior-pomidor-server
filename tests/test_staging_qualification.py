from __future__ import annotations

import pytest

from tools import staging_qualification


def test_controller_rejects_non_staging_network_and_arbitrary_scenarios(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_MODE", "staging")
    monkeypatch.setenv("STAGING_INTEROP_NETWORK", "other-network")
    with pytest.raises(staging_qualification.QualificationControllerError, match="fixed staging network"):
        staging_qualification.preflight()

    with pytest.raises(staging_qualification.QualificationControllerError, match="unknown bounded"):
        staging_qualification.scenario("docker rm -f api")


def test_controller_never_returns_process_output(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_MODE", "staging")
    monkeypatch.setenv("STAGING_INTEROP_NETWORK", staging_qualification.NETWORK)
    monkeypatch.setenv("STAGING_EDGE_CONTAINER_NAME", staging_qualification.EDGE_CONTAINER)
    observed: list[list[str]] = []

    def fake_run(args, **kwargs):
        observed.append(args)
        stdout = '{"senior-pomidor-staging-interop": {}}' if args[1] == "inspect" else "PASSWORD=secret"
        return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": "private"})()

    monkeypatch.setattr(staging_qualification.subprocess, "run", fake_run)
    result = staging_qualification.preflight()

    assert result["status"] == "PASS"
    assert result["edge_connected"] is True
    assert "secret" not in str(result)
    assert observed[0][:8] == [
        "docker",
        "compose",
        "-p",
        staging_qualification.PROJECT,
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.staging.yml",
    ]
    assert all("shell" not in argument for argument in observed[0])
