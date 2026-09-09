from __future__ import annotations

import copy
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.map import (
    TOPOLOGY_INVALID,
    TOPOLOGY_UNAVAILABLE,
    EntityNamespace,
    TopologyCatalog,
    TopologyMode,
    TopologyProvider,
    TopologyRevision,
    TopologyUnavailableError,
    TopologyValidationError,
    canonical_revision_bytes,
    compute_revision_digest,
    load_topology_catalog,
)
from app.map.provider import MAX_YAML_BYTES

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "config/topology"
MAY = datetime(2026, 5, 1, tzinfo=UTC)
JULY = datetime(2026, 7, 1, tzinfo=UTC)
SEPTEMBER = datetime(2026, 9, 1, tzinfo=UTC)


def _seed_data(name: str = "001-initial.yaml") -> dict[str, Any]:
    data = yaml.safe_load((SEED / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _set_digest(data: dict[str, Any]) -> None:
    revision = TopologyRevision.model_validate(data)
    data["digest"] = compute_revision_digest(revision)


def _write_revision(directory: Path, data: dict[str, Any], name: str = "revision.yaml") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    _set_digest(data)
    destination = directory / name
    destination.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return destination


def _write_seed_copy(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for source in SEED.glob("*.yaml"):
        (directory / source.name).write_bytes(source.read_bytes())


def test_synthetic_seed_loads_distinct_targets_and_exposes_versions_and_provenance() -> None:
    provider = TopologyProvider(SEED)

    snapshot = provider.snapshot(datetime(2026, 6, 1, tzinfo=UTC))
    target_a = provider.resolve_bindings("synthetic-target-a", "soil-moisture-observation", snapshot.selected_at)
    target_b = provider.resolve_bindings("synthetic-target-b", "soil-moisture-observation", snapshot.selected_at)

    assert provider.status.available is True
    assert snapshot.revision_id == "synthetic-r003-relocation"
    assert len(snapshot.digest) == 64
    assert snapshot.profile_identities[0].model_dump() == {
        "profile_id": "synthetic-soil-profile",
        "version": "v3",
    }
    assert snapshot.provenance.kind.value == "SYNTHETIC"
    assert target_a[0].channel.channel_id == "synthetic-channel-b-v1"
    assert target_b[0].channel.channel_id == "synthetic-channel-a-v2"
    assert target_a[0].profile.calibration_provenance.kind.value == "SYNTHETIC"
    with pytest.raises(ValidationError):
        snapshot.targets[0].label = "changed"


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        (datetime(2026, 1, 1, tzinfo=UTC), "synthetic-r001-initial"),
        (datetime(2026, 3, 31, 23, 59, 59, 999999, tzinfo=UTC), "synthetic-r001-initial"),
        (datetime(2026, 4, 1, tzinfo=UTC), "synthetic-r002-replacement"),
        (datetime(2026, 6, 1, tzinfo=UTC), "synthetic-r003-relocation"),
    ],
)
def test_s06_s07_half_open_replacement_and_relocation_boundaries(at: datetime, expected: str) -> None:
    assert TopologyProvider(SEED).snapshot(at).revision_id == expected


def test_s08_retroactive_correction_obeys_mode_and_cutoff() -> None:
    provider = TopologyProvider(SEED)

    assert provider.snapshot(MAY, TopologyMode.AS_KNOWN_CORE, JULY).revision_id == "synthetic-r002-replacement"
    assert (
        provider.snapshot(MAY, TopologyMode.RECONSTRUCTED, datetime(2026, 6, 30, tzinfo=UTC)).revision_id
        == "synthetic-r002-replacement"
    )
    corrected = provider.snapshot(MAY, TopologyMode.RECONSTRUCTED, JULY)

    assert corrected.revision_id == "synthetic-r004-correction"
    assert corrected.profile_identities[0].version == "v2-corrected"
    assert (
        provider.resolve_bindings(
            "synthetic-target-a", "soil-moisture-observation", MAY, TopologyMode.RECONSTRUCTED, JULY
        )[0].channel.channel_id
        == "synthetic-channel-b-v1"
    )


def test_digest_serialization_has_a_deterministic_round_trip() -> None:
    revision = load_topology_catalog(SEED).revisions[0]
    canonical = canonical_revision_bytes(revision)
    decoded = json.loads(canonical)
    decoded["digest"] = revision.digest
    round_tripped = TopologyRevision.model_validate(decoded)

    assert canonical == canonical_revision_bytes(round_tripped)
    assert compute_revision_digest(round_tripped) == revision.digest
    assert b'"recorded_at":"2026-01-01T00:00:00.000000Z"' in canonical


def test_same_source_local_key_on_different_sources_does_not_collide(tmp_path: Path) -> None:
    data = _seed_data()
    sources = data["sources"]
    channels = data["source_channels"]
    assert isinstance(sources, list)
    assert isinstance(channels, list)
    sources.append({"source_id": "synthetic-source-2", "kind": "SIMULATOR", "label": "Second source"})
    extra = copy.deepcopy(channels[0])
    extra["channel_id"] = "synthetic-channel-c-v1"
    extra["source_id"] = "synthetic-source-2"
    channels.append(extra)

    catalog = load_topology_catalog(_write_revision(tmp_path, data).parent)

    assert len(catalog.revisions[0].source_channels) == 3


def test_same_source_local_key_on_one_source_is_rejected(tmp_path: Path) -> None:
    data = _seed_data()
    duplicate = copy.deepcopy(data["source_channels"][0])
    duplicate["channel_id"] = "synthetic-channel-duplicate"
    data["source_channels"].append(duplicate)
    _write_revision(tmp_path, data)

    with pytest.raises(TopologyValidationError, match="source-local"):
        load_topology_catalog(tmp_path)


@pytest.mark.parametrize(
    "invalid_text",
    [
        "schema_version: senior-pomidor.map.v1\nschema_version: senior-pomidor.map.v1\n",
        "schema_version: &version senior-pomidor.map.v1\ncopy: *version\n",
        "---\nschema_version: senior-pomidor.map.v1\n---\nrevision_id: second\n",
        "schema_version: !private senior-pomidor.map.v1\n",
    ],
    ids=["duplicate-key", "alias", "multiple-documents", "custom-tag"],
)
def test_unsafe_or_malformed_yaml_is_rejected(tmp_path: Path, invalid_text: str) -> None:
    (tmp_path / "revision.yaml").write_text(invalid_text, encoding="utf-8")

    with pytest.raises(TopologyValidationError):
        load_topology_catalog(tmp_path)


@pytest.mark.parametrize(
    ("mutate", "recompute_digest"),
    [
        (lambda data: data.__setitem__("unknown", True), False),
        (lambda data: data.__setitem__("schema_version", "senior-pomidor.map.v2"), False),
        (lambda data: data["sources"].append(copy.deepcopy(data["sources"][0])), True),
        (lambda data: data["source_channels"][0].__setitem__("source_id", "synthetic-target-a"), True),
        (lambda data: data["interval"].__setitem__("effective_to", data["interval"]["effective_from"]), False),
        (lambda data: data["source_channels"][0]["value_range"].__setitem__("minimum", float("nan")), False),
        (lambda data: data["targets"][0].__setitem__("target_id", "x" * 65), False),
        (lambda data: data.__setitem__("sources", data["sources"] * 257), False),
    ],
    ids=[
        "unknown-field",
        "unknown-version",
        "duplicate-id",
        "wrong-reference-type",
        "empty-interval",
        "non-finite-number",
        "identifier-bound",
        "collection-bound",
    ],
)
def test_invalid_revision_contracts_are_rejected(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None], recompute_digest: bool
) -> None:
    data = _seed_data()
    mutate(data)
    tmp_path.mkdir(exist_ok=True)
    if recompute_digest:
        _set_digest(data)
    (tmp_path / "revision.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(TopologyValidationError):
        load_topology_catalog(tmp_path)


def test_oversized_yaml_is_rejected_before_parsing(tmp_path: Path) -> None:
    (tmp_path / "revision.yaml").write_bytes(b"x" * (MAX_YAML_BYTES + 1))

    with pytest.raises(TopologyValidationError, match="size"):
        load_topology_catalog(tmp_path)


def test_non_regular_yaml_entry_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "revision.yaml").mkdir()

    with pytest.raises(TopologyValidationError, match="regular file"):
        load_topology_catalog(tmp_path)


@pytest.mark.parametrize(
    "value",
    ["2026-01-01T00:00:00", "2026-01-01T01:00:00+01:00"],
    ids=["naive", "non-utc"],
)
def test_non_utc_revision_timestamps_are_rejected(tmp_path: Path, value: str) -> None:
    data = _seed_data()
    data["recorded_at"] = value
    (tmp_path / "revision.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(TopologyValidationError):
        load_topology_catalog(tmp_path)


def test_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    data = _seed_data()
    data["digest"] = "f" * 64
    (tmp_path / "revision.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(TopologyValidationError, match="digest"):
        load_topology_catalog(tmp_path)


def test_ambiguous_overlap_requires_explicit_supersession(tmp_path: Path) -> None:
    first = _seed_data()
    second = copy.deepcopy(first)
    second["revision_id"] = "synthetic-conflict"
    second["recorded_at"] = datetime(2026, 2, 1, tzinfo=UTC)
    second["provenance"]["recorded_at"] = datetime(2026, 2, 1, tzinfo=UTC)
    _write_revision(tmp_path, first, "001.yaml")
    _write_revision(tmp_path, second, "002.yaml")

    with pytest.raises(TopologyValidationError, match="supersession"):
        load_topology_catalog(tmp_path)


@pytest.mark.parametrize("supersedes", ["missing-revision", "synthetic-forward"])
def test_missing_and_forward_supersession_are_rejected(tmp_path: Path, supersedes: str) -> None:
    first = _seed_data()
    first["supersedes"] = supersedes
    if supersedes == "synthetic-forward":
        second = copy.deepcopy(first)
        second["revision_id"] = "synthetic-forward"
        second["supersedes"] = None
        second["recorded_at"] = datetime(2026, 2, 1, tzinfo=UTC)
        second["interval"] = {
            "effective_from": datetime(2026, 4, 1, tzinfo=UTC),
            "effective_to": datetime(2026, 5, 1, tzinfo=UTC),
        }
        for collection in (second["deployments"], second["bindings"]):
            for item in collection:
                item["interval"] = copy.deepcopy(second["interval"])
        _write_revision(tmp_path, second, "002.yaml")
    _write_revision(tmp_path, first, "001.yaml")

    with pytest.raises(TopologyValidationError, match="supers"):
        load_topology_catalog(tmp_path)


def test_cyclic_supersession_is_rejected(tmp_path: Path) -> None:
    first = _seed_data()
    second = copy.deepcopy(first)
    first["supersedes"] = "synthetic-cycle-b"
    second["revision_id"] = "synthetic-cycle-b"
    second["supersedes"] = "synthetic-r001-initial"
    second["recorded_at"] = datetime(2026, 2, 1, tzinfo=UTC)
    _write_revision(tmp_path, first, "001.yaml")
    _write_revision(tmp_path, second, "002.yaml")

    with pytest.raises(TopologyValidationError, match="cycle"):
        load_topology_catalog(tmp_path)


def test_superseding_revision_must_overlap_effective_history(tmp_path: Path) -> None:
    first = _seed_data()
    second = copy.deepcopy(first)
    second["revision_id"] = "synthetic-disjoint-supersession"
    second["supersedes"] = "synthetic-r001-initial"
    second["recorded_at"] = datetime(2026, 2, 1, tzinfo=UTC)
    second["interval"] = {
        "effective_from": datetime(2026, 4, 1, tzinfo=UTC),
        "effective_to": datetime(2026, 5, 1, tzinfo=UTC),
    }
    for collection in (second["deployments"], second["bindings"]):
        for item in collection:
            item["interval"] = copy.deepcopy(second["interval"])
    _write_revision(tmp_path, first, "001.yaml")
    _write_revision(tmp_path, second, "002.yaml")

    with pytest.raises(TopologyValidationError, match="overlap"):
        load_topology_catalog(tmp_path)


def _relationship(kind: str, source: str, target: str, namespace: str, suffix: str) -> dict[str, Any]:
    return {
        "relationship_id": f"synthetic-{suffix}",
        "kind": kind,
        "from_ref": {"namespace": namespace, "entity_id": source},
        "to_ref": {"namespace": namespace, "entity_id": target},
    }


def test_containment_cycle_is_rejected(tmp_path: Path) -> None:
    data = _seed_data()
    data["relationships"] = [
        _relationship("CONTAINMENT", "synthetic-target-a", "synthetic-target-b", "TARGET", "contains-a-b"),
        _relationship("CONTAINMENT", "synthetic-target-b", "synthetic-target-a", "TARGET", "contains-b-a"),
    ]
    _write_revision(tmp_path, data)

    with pytest.raises(TopologyValidationError, match="cycle"):
        load_topology_catalog(tmp_path)


def test_relationship_endpoint_namespace_must_match_kind(tmp_path: Path) -> None:
    data = _seed_data()
    data["relationships"] = [
        {
            "relationship_id": "synthetic-wrong-types",
            "kind": "PHYSICAL_LINK",
            "from_ref": {"namespace": "TARGET", "entity_id": "synthetic-target-a"},
            "to_ref": {"namespace": "TARGET", "entity_id": "synthetic-target-b"},
        }
    ]
    _write_revision(tmp_path, data)

    with pytest.raises(TopologyValidationError, match="endpoint types"):
        load_topology_catalog(tmp_path)


def test_capability_cycle_is_rejected(tmp_path: Path) -> None:
    data = _seed_data()
    profiles = data["capability_profiles"]
    profiles.append(copy.deepcopy(profiles[0]))
    profiles[1]["profile_id"] = "synthetic-dependent-profile"
    profiles[1]["calibration_provenance"]["provenance_id"] = "synthetic-dependent-calibration"
    data["relationships"] = [
        _relationship(
            "CAPABILITY_DEPENDENCY",
            "synthetic-soil-profile",
            "synthetic-dependent-profile",
            "CAPABILITY_PROFILE",
            "capability-a-b",
        ),
        _relationship(
            "CAPABILITY_DEPENDENCY",
            "synthetic-dependent-profile",
            "synthetic-soil-profile",
            "CAPABILITY_PROFILE",
            "capability-b-a",
        ),
    ]
    _write_revision(tmp_path, data)

    with pytest.raises(TopologyValidationError, match="cycle"):
        load_topology_catalog(tmp_path)


@pytest.mark.parametrize("kind", ["PHYSICAL_LINK", "DATA_FLOW"])
def test_physical_and_data_flow_cycles_are_accepted(tmp_path: Path, kind: str) -> None:
    data = _seed_data()
    if kind == "PHYSICAL_LINK":
        namespace = EntityNamespace.PHYSICAL_ASSET.value
        source, target = "synthetic-probe-a-v1", "synthetic-probe-b-v1"
    else:
        namespace = EntityNamespace.SOURCE_CHANNEL.value
        source, target = "synthetic-channel-a-v1", "synthetic-channel-b-v1"
    data["relationships"] = [
        _relationship(kind, source, target, namespace, "allowed-a-b"),
        _relationship(kind, target, source, namespace, "allowed-b-a"),
    ]

    assert len(load_topology_catalog(_write_revision(tmp_path, data).parent).revisions) == 1


def test_failed_reload_retains_exact_prior_catalog_and_bounded_status(tmp_path: Path) -> None:
    _write_seed_copy(tmp_path)
    provider = TopologyProvider(tmp_path)
    original = provider.catalog
    original_digest = provider.status.digest
    (tmp_path / "001-initial.yaml").write_text("not: [valid", encoding="utf-8")

    assert provider.reload() is False
    assert provider.catalog is original
    assert provider.status.available is True
    assert provider.status.digest == original_digest
    assert provider.status.error_code == TOPOLOGY_INVALID
    assert str(tmp_path) not in provider.status.model_dump_json()


@pytest.mark.parametrize("create_invalid", [False, True])
def test_missing_or_invalid_first_load_is_unavailable(tmp_path: Path, create_invalid: bool) -> None:
    if create_invalid:
        (tmp_path / "bad.yaml").write_text("bad: [", encoding="utf-8")
    provider = TopologyProvider(tmp_path)

    assert provider.catalog is None
    assert provider.status.error_code == TOPOLOGY_UNAVAILABLE
    with pytest.raises(TopologyUnavailableError):
        provider.snapshot(MAY)


def test_concurrent_reload_exposes_only_complete_old_or_new_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = TopologyProvider(SEED)
    old_catalog = provider.catalog
    assert old_catalog is not None
    new_revision = old_catalog.revisions[2].model_copy(
        update={
            "revision_id": "synthetic-r005-complete",
            "recorded_at": datetime(2026, 8, 1, tzinfo=UTC),
            "digest": "b" * 64,
        }
    )
    new_catalog = TopologyCatalog(revisions=(*old_catalog.revisions[:2], new_revision, *old_catalog.revisions[3:]))
    entered = threading.Event()
    release = threading.Event()

    def delayed_load(_directory: object) -> TopologyCatalog:
        entered.set()
        assert release.wait(timeout=5)
        return new_catalog

    monkeypatch.setattr("app.map.provider.load_topology_catalog", delayed_load)
    thread = threading.Thread(target=provider.reload)
    thread.start()
    assert entered.wait(timeout=5)

    while not release.is_set():
        assert provider.catalog is old_catalog
        assert provider.snapshot(SEPTEMBER).revision_id == "synthetic-r003-relocation"
        release.set()
    thread.join(timeout=5)

    assert provider.catalog is new_catalog
    assert provider.status.revision_id == "synthetic-r005-complete"
    assert provider.snapshot(SEPTEMBER).revision_id == "synthetic-r005-complete"


def test_snapshot_rejects_naive_non_utc_and_time_after_cutoff() -> None:
    provider = TopologyProvider(SEED)

    with pytest.raises(ValueError, match="UTC"):
        provider.snapshot(datetime(2026, 5, 1, tzinfo=UTC).replace(tzinfo=None))
    with pytest.raises(ValueError, match="UTC"):
        provider.snapshot(datetime.fromisoformat("2026-05-01T01:00:00+01:00"))
    with pytest.raises(ValueError, match="cutoff"):
        provider.snapshot(JULY, data_cutoff=MAY)
