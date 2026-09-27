from copy import deepcopy

import pytest

from tools.cross_repo.evidence import EvidenceError, validate_evidence
from tools.cross_repo.runner import SCENARIOS, HarnessError, compose_config, validate_isolation


def report():
    return {
        "schema_version": "senior-pomidor.cross-repo-e2e.v1",
        "status": "PASS",
        "evidence_scope": "CI",
        "started_at_utc": "2026-09-27T12:00:00Z",
        "finished_at_utc": "2026-09-27T12:01:00Z",
        "future_action_invariants": "NOT_IMPLEMENTED",
        "config_sha256": "c" * 64,
        "core": {"git_sha": "a" * 40, "image_id": "sha256:" + "1" * 64},
        "edge": {"git_sha": "b" * 40, "image_id": "sha256:" + "2" * 64},
        "scenarios": [
            {
                "scenario_id": name,
                "status": "PASS",
                "pending_expected": name
                in {"core-outage-spool-growth", "edge-restart-pending", "fresh-during-backlog-replay"},
                "counts": {
                    "generated": 3,
                    "persisted": 3,
                    "read_back": 3,
                    "duplicates": 0,
                    "missing": 0,
                    "unexpected": 0,
                },
            }
            for name in SCENARIOS
        ],
    }


def test_software_evidence_accepts_complete_results():
    validate_evidence(report(), core_sha="a" * 40, edge_sha="b" * 40)


@pytest.mark.parametrize(
    "fault",
    [
        "missing-scenario",
        "duplicate-scenario",
        "lost-row",
        "extra-row",
        "synthetic",
        "wrong-sha",
        "not-run",
        "cleanup",
        "fake-count",
    ],
)
def test_evidence_rejects_false_success(fault):
    data = report()
    if fault == "missing-scenario":
        data["scenarios"].pop()
    elif fault == "duplicate-scenario":
        data["scenarios"][-1] = deepcopy(data["scenarios"][0])
    elif fault == "lost-row":
        data["scenarios"][0]["counts"]["persisted"] = 2
    elif fault == "extra-row":
        data["scenarios"][0]["counts"]["duplicates"] = 1
    elif fault == "synthetic":
        data["evidence_scope"] = "SYNTHETIC"
    elif fault == "wrong-sha":
        data["core"]["git_sha"] = "d" * 40
    elif fault == "not-run":
        data["scenarios"][0]["status"] = "NOT_RUN"
    elif fault == "cleanup":
        data["cleanup_status"] = "FAIL"
    else:
        data["scenarios"][0]["counts"]["generated"] = True
    with pytest.raises(EvidenceError):
        validate_evidence(data, core_sha="a" * 40, edge_sha="b" * 40)


def test_config_is_private_without_host_mounts():
    config = compose_config("core", "edge", "driver")
    validate_isolation(config)
    assert "grafana-cloud-exporter" not in config["services"]


@pytest.mark.parametrize("fault", ["network", "host-port", "host-mount", "device", "export", "external-volume"])
def test_isolation_rejects_unsafe_config(fault):
    config = compose_config("core", "edge", "driver")
    if fault == "network":
        config["networks"]["isolated"]["internal"] = False
    elif fault == "host-port":
        config["services"]["api"]["ports"] = ["0.0.0.0:8000:8000"]
    elif fault == "host-mount":
        config["services"]["edge"]["volumes"].append("/srv:/data")
    elif fault == "device":
        config["services"]["edge"]["devices"] = ["/dev/gpiochip0"]
    elif fault == "export":
        config["services"]["api"]["environment"]["GRAFANA_CLOUD_EXPORT_ENABLED"] = "true"
    else:
        config["volumes"]["spool"] = {"external": True}
    with pytest.raises(HarnessError):
        validate_isolation(config)
