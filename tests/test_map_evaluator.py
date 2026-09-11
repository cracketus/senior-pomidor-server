from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.map import (
    AssertionKind,
    CapabilityEvaluationError,
    CapabilityFidelity,
    CapabilityInterval,
    CapabilityOperator,
    CapabilityReason,
    CapabilityStatus,
    ChannelMetric,
    ChannelSelector,
    EvidenceFidelity,
    EvidenceKind,
    EvidenceMode,
    EvidenceReason,
    EvidenceValidity,
    FreshnessStatus,
    RawEvidenceBatch,
    RawEvidenceItem,
    RawEvidenceRequest,
    TargetCapabilityExpression,
    TopologyMode,
    TopologyProvider,
    Unit,
    compute_capability_digest,
    compute_evidence_digest,
    evaluate_capabilities,
    reduce_capability,
)

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _inputs(mode=EvidenceMode.RECONSTRUCTED, *, item=True):
    topology = TopologyProvider(ROOT / "config/topology").snapshot(T0, TopologyMode(mode.value), T0)
    binding = next(b for b in topology.bindings if b.target_id == "synthetic-target-a")
    profile = next(p for p in topology.capability_profiles if p.profile_id == binding.profile_id)
    selector = ChannelSelector(
        source_id="synthetic-source-1",
        storage_device_id="synthetic-device",
        channel_id=binding.channel_id,
        pod_key="pod-a",
        metric_name=ChannelMetric.SOIL_MOISTURE_PERCENT,
        error_sensors=("soil",),
        unit=Unit.PERCENT,
        minimum=0,
        maximum=100,
        max_age_seconds=1200,
        effective_interval=binding.interval,
        profile_id=profile.profile_id,
        profile_version=profile.version,
    )
    request = RawEvidenceRequest(
        selectors=(selector,),
        window_start=T0,
        window_end=T0 + timedelta(seconds=2400),
        mode=mode,
        data_cutoff=T0 + timedelta(seconds=2400),
        topology_revision_id=topology.revision_id,
        topology_digest=topology.digest,
    )
    items: tuple[RawEvidenceItem, ...] = ()
    if item:
        items = (
            RawEvidenceItem(
                observation_at=T0,
                received_at=T0,
                event_identity="event:1",
                child_identity="reading:1",
                source_id="synthetic-source-1",
                source_schema_version="senior-pomidor.edge.telemetry.v2",
                channel_id=binding.channel_id,
                pod_key="pod-a",
                metric_name=ChannelMetric.SOIL_MOISTURE_PERCENT,
                unit=Unit.PERCENT,
                value=50,
                validity=EvidenceValidity.VALID,
                evidence_kind=EvidenceKind.CHANNEL_VALUE,
            ),
        )
    batch = RawEvidenceBatch(
        mode=mode,
        window_start=request.window_start,
        window_end=request.window_end,
        evaluation_time=T0 + timedelta(seconds=2400),
        data_cutoff=request.data_cutoff,
        coverage_start=T0,
        coverage_end=request.window_end,
        topology_revision_id=topology.revision_id,
        topology_digest=topology.digest,
        profile_identities=topology.profile_identities,
        fidelity=EvidenceFidelity.INGEST_TIME_PROXY,
        row_count=len(items),
        items=items,
        digest="0" * 64,
    )
    batch = batch.model_copy(update={"digest": compute_evidence_digest(batch)})
    return topology, request, batch, binding


def _with_batch_update(batch: RawEvidenceBatch, **update) -> RawEvidenceBatch:
    updated = batch.model_copy(update=update)
    return updated.model_copy(update={"digest": compute_evidence_digest(updated)})


def test_evidence_digest_mismatch_fails_closed():
    topology, request, batch, _ = _inputs()
    tampered = batch.model_copy(update={"digest": "f" * 64})
    with pytest.raises(CapabilityEvaluationError, match="evidence digest mismatch"):
        evaluate_capabilities(
            topology,
            request,
            tampered,
            (
                TargetCapabilityExpression(
                    target_id="synthetic-target-a",
                    capability="soil-moisture-observation",
                    operator=CapabilityOperator.ALL_OF,
                ),
            ),
        )


def test_freshness_threshold_is_inclusive_and_next_microsecond_stale():
    topology, request, batch, _ = _inputs()
    result = evaluate_capabilities(
        topology,
        request,
        batch,
        (
            TargetCapabilityExpression(
                target_id="synthetic-target-a",
                capability="soil-moisture-observation",
                operator=CapabilityOperator.ALL_OF,
            ),
        ),
    )
    intervals = result.targets[0].intervals
    assert intervals[0].capability is CapabilityStatus.AVAILABLE
    assert intervals[0].freshness is FreshnessStatus.FRESH
    assert any(interval.reason is CapabilityReason.MISSING_UPDATE for interval in intervals)
    assert result.digest == compute_capability_digest(result)


def test_missing_binding_is_fail_safe_and_unknown_history_is_not_fabricated_outage():
    topology, request, batch, _ = _inputs(item=False)
    expressions = (
        TargetCapabilityExpression(
            target_id="synthetic-target-a", capability="not-mapped", operator=CapabilityOperator.ANY_OF
        ),
        TargetCapabilityExpression(
            target_id="synthetic-target-a", capability="soil-moisture-observation", operator=CapabilityOperator.ALL_OF
        ),
    )
    result = evaluate_capabilities(topology, request, batch, expressions)
    assert result.targets[0].intervals[0].reason is CapabilityReason.MISSING_BINDING
    assert result.targets[1].intervals[0].capability is CapabilityStatus.UNKNOWN
    assert result.targets[1].intervals[0].reason is CapabilityReason.UNKNOWN_HISTORY


def test_binding_gap_is_missing_binding_not_unknown_history():
    topology, request, batch, binding = _inputs(item=False)
    active_from = T0 + timedelta(minutes=10)
    delayed_binding = binding.model_copy(
        update={"interval": binding.interval.model_copy(update={"effective_from": active_from})}
    )
    topology = topology.model_copy(
        update={
            "bindings": tuple(
                delayed_binding if item.binding_id == binding.binding_id else item for item in topology.bindings
            )
        }
    )

    result = evaluate_capabilities(
        topology,
        request,
        batch,
        (
            TargetCapabilityExpression(
                target_id="synthetic-target-a",
                capability="soil-moisture-observation",
                operator=CapabilityOperator.ALL_OF,
            ),
        ),
    )

    before_binding, active_without_evidence = result.targets[0].intervals
    assert before_binding.start == request.window_start
    assert before_binding.end == active_from
    assert before_binding.capability is CapabilityStatus.UNAVAILABLE
    assert before_binding.reason is CapabilityReason.MISSING_BINDING
    assert active_without_evidence.reason is CapabilityReason.UNKNOWN_HISTORY


def test_input_revision_mismatch_fails_closed():
    topology, request, batch, _ = _inputs()
    with pytest.raises(ValueError, match="topology revision"):
        evaluate_capabilities(
            topology,
            request.model_copy(update={"topology_digest": "b" * 64}),
            batch,
            (
                TargetCapabilityExpression(
                    target_id="synthetic-target-a",
                    capability="soil-moisture-observation",
                    operator=CapabilityOperator.ALL_OF,
                ),
            ),
        )


def test_late_receipt_is_mode_specific():
    topology, request, batch, _ = _inputs(mode=EvidenceMode.AS_KNOWN_CORE)
    late = batch.items[0].model_copy(update={"received_at": T0 + timedelta(minutes=10)})
    as_known = evaluate_capabilities(
        topology,
        request,
        _with_batch_update(batch, items=(late,)),
        (
            TargetCapabilityExpression(
                target_id="synthetic-target-a",
                capability="soil-moisture-observation",
                operator=CapabilityOperator.ALL_OF,
            ),
        ),
    )
    reconstructed_topology, reconstructed_request, reconstructed_batch, _ = _inputs(mode=EvidenceMode.RECONSTRUCTED)
    reconstructed = evaluate_capabilities(
        reconstructed_topology,
        reconstructed_request,
        _with_batch_update(reconstructed_batch, items=(late,)),
        (
            TargetCapabilityExpression(
                target_id="synthetic-target-a",
                capability="soil-moisture-observation",
                operator=CapabilityOperator.ALL_OF,
            ),
        ),
    )
    assert as_known.targets[0].intervals[0].reason is CapabilityReason.UNKNOWN_HISTORY
    assert reconstructed.targets[0].intervals[0].capability is CapabilityStatus.AVAILABLE


@pytest.mark.parametrize(
    "kind", [EvidenceKind.CHANNEL_INVALID_VALUE, EvidenceKind.EXPLICIT_ERROR, EvidenceKind.DISABLED_CHANNEL]
)
def test_latest_non_green_evidence_does_not_reuse_older_value(kind):
    topology, request, batch, _ = _inputs()
    latest = batch.items[0].model_copy(
        update={
            "observation_at": T0 + timedelta(minutes=1),
            "evidence_kind": kind,
            "validity": EvidenceValidity.INVALID
            if kind is not EvidenceKind.DISABLED_CHANNEL
            else EvidenceValidity.VALID,
            "value": None if kind is not EvidenceKind.CHANNEL_INVALID_VALUE else 101.0,
            "reason": None
            if kind is EvidenceKind.CHANNEL_INVALID_VALUE
            else (EvidenceReason.EXPLICIT_ERROR if kind is EvidenceKind.EXPLICIT_ERROR else EvidenceReason.DISABLED),
        }
    )
    result = evaluate_capabilities(
        topology,
        request,
        _with_batch_update(batch, items=(batch.items[0], latest)),
        (
            TargetCapabilityExpression(
                target_id="synthetic-target-a",
                capability="soil-moisture-observation",
                operator=CapabilityOperator.ALL_OF,
            ),
        ),
    )
    assert result.targets[0].intervals[1].capability in {CapabilityStatus.UNAVAILABLE, CapabilityStatus.NOT_APPLICABLE}


def test_reducers_follow_truth_tables_and_preserve_contradiction():
    def leaf(status):
        return CapabilityInterval(
            start=T0,
            end=T0 + timedelta(seconds=1),
            capability=status,
            freshness=FreshnessStatus.FRESH if status is CapabilityStatus.AVAILABLE else FreshnessStatus.UNKNOWN,
            reason=CapabilityReason.NO_FRESH_VALID_OBSERVATION,
            assertion=AssertionKind.INFERENCE,
            fidelity=CapabilityFidelity.INGEST_TIME_PROXY,
        )

    assert (
        reduce_capability(
            (leaf(CapabilityStatus.AVAILABLE), leaf(CapabilityStatus.UNKNOWN)),
            CapabilityOperator.ALL_OF,
            start=T0,
            end=T0 + timedelta(seconds=1),
            fidelity=CapabilityFidelity.INGEST_TIME_PROXY,
        ).capability
        is CapabilityStatus.UNKNOWN
    )
    assert (
        reduce_capability(
            (leaf(CapabilityStatus.AVAILABLE), leaf(CapabilityStatus.UNAVAILABLE)),
            CapabilityOperator.ANY_OF,
            start=T0,
            end=T0 + timedelta(seconds=1),
            fidelity=CapabilityFidelity.INGEST_TIME_PROXY,
        ).capability
        is CapabilityStatus.AVAILABLE
    )
    contradiction = leaf(CapabilityStatus.AVAILABLE).model_copy(
        update={"reason": CapabilityReason.CONTRADICTORY_EVIDENCE}
    )
    assert (
        reduce_capability(
            (contradiction,),
            CapabilityOperator.ANY_OF,
            start=T0,
            end=T0 + timedelta(seconds=1),
            fidelity=CapabilityFidelity.INGEST_TIME_PROXY,
        ).capability
        is CapabilityStatus.UNKNOWN
    )
