from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from app.map.capability import (
    AssertionKind,
    CapabilityEvaluation,
    CapabilityFidelity,
    CapabilityInterval,
    CapabilityOperator,
    CapabilityReason,
    CapabilityStatus,
    EvidenceReference,
    FreshnessStatus,
    TargetCapabilityExpression,
    TargetCapabilityResult,
    compute_capability_digest,
)
from app.map.models import ResolvedTopology, TopologyMode
from app.map.raw_evidence import (
    ChannelSelector,
    EvidenceFidelity,
    EvidenceKind,
    EvidenceValidity,
    RawEvidenceBatch,
    RawEvidenceItem,
    RawEvidenceRequest,
    compute_evidence_digest,
)


class CapabilityEvaluationError(ValueError):
    """The immutable inputs do not describe one coherent evaluation."""


def _fidelity(batch: RawEvidenceBatch, mode: TopologyMode) -> CapabilityFidelity:
    if mode is TopologyMode.RECONSTRUCTED:
        return CapabilityFidelity.RECONSTRUCTED
    if batch.fidelity is EvidenceFidelity.INGEST_TIME_PROXY:
        return CapabilityFidelity.INGEST_TIME_PROXY
    return CapabilityFidelity.UNKNOWN


def _ref(item: RawEvidenceItem, fidelity: CapabilityFidelity) -> EvidenceReference:
    identity = f"{item.event_identity}\x00{item.child_identity}".encode("utf-8", errors="replace")
    return EvidenceReference(
        evidence_id=hashlib.sha256(identity).hexdigest(), evidence_kind=item.evidence_kind.value, fidelity=fidelity
    )


def _validate_inputs(topology: ResolvedTopology, request: RawEvidenceRequest, batch: RawEvidenceBatch) -> None:
    if request.schema_version != "senior-pomidor.map.v1" or batch.schema_version != "senior-pomidor.map.v1":
        raise CapabilityEvaluationError("schema version mismatch")
    if compute_evidence_digest(batch) != batch.digest:
        raise CapabilityEvaluationError("evidence digest mismatch")
    if request.mode.value != batch.mode.value or request.mode.value != topology.mode.value:
        raise CapabilityEvaluationError("evaluation mode mismatch")
    if request.window_start != batch.window_start or request.window_end != batch.window_end:
        raise CapabilityEvaluationError("evaluation window mismatch")
    if request.topology_revision_id != topology.revision_id or request.topology_digest != topology.digest:
        raise CapabilityEvaluationError("topology revision or digest mismatch")
    if batch.topology_revision_id != topology.revision_id or batch.topology_digest != topology.digest:
        raise CapabilityEvaluationError("evidence topology revision or digest mismatch")
    if request.data_cutoff is not None and request.data_cutoff != batch.data_cutoff:
        raise CapabilityEvaluationError("data cutoff mismatch")
    selector_channels = {selector.channel_id for selector in request.selectors}
    if any(item.channel_id is not None and item.channel_id not in selector_channels for item in batch.items):
        raise CapabilityEvaluationError("evidence contains an unrequested channel")
    profiles = {(p.profile_id, p.version) for p in topology.profile_identities}
    if {(p.profile_id, p.version) for p in batch.profile_identities} != profiles:
        raise CapabilityEvaluationError("profile snapshot mismatch")
    topology_channels = {channel.channel_id: channel for channel in topology.source_channels}
    topology_profiles = {profile.profile_id: profile for profile in topology.capability_profiles}
    for selector in request.selectors:
        channel = topology_channels.get(selector.channel_id)
        profile = topology_profiles.get(selector.profile_id)
        if channel is None or profile is None or selector.profile_version != profile.version:
            raise CapabilityEvaluationError("selector does not match topology profile")
        if channel.value_range.unit != selector.unit or profile.input_range.unit != selector.unit:
            raise CapabilityEvaluationError("selector unit does not match topology")


def _leaf(
    item: RawEvidenceItem | None,
    *,
    now: datetime,
    selector: ChannelSelector,
    fidelity: CapabilityFidelity,
) -> CapabilityInterval:
    end = now + timedelta(microseconds=1)
    if item is None:
        return CapabilityInterval(
            start=now,
            end=end,
            capability=CapabilityStatus.UNKNOWN,
            freshness=FreshnessStatus.UNKNOWN,
            reason=CapabilityReason.UNKNOWN_HISTORY,
            assertion=AssertionKind.UNKNOWN,
            fidelity=fidelity,
        )
    ref = (_ref(item, fidelity),)
    if item.validity is EvidenceValidity.CLOCK_INVALID:
        status, fresh, reason, assertion = (
            CapabilityStatus.UNKNOWN,
            FreshnessStatus.UNKNOWN,
            CapabilityReason.CLOCK_INVALID,
            AssertionKind.UNKNOWN,
        )
    elif item.evidence_kind is EvidenceKind.DISABLED_CHANNEL:
        status, fresh, reason, assertion = (
            CapabilityStatus.NOT_APPLICABLE,
            FreshnessStatus.NOT_APPLICABLE,
            CapabilityReason.DISABLED,
            AssertionKind.FACT,
        )
    elif item.evidence_kind is EvidenceKind.EXPLICIT_ERROR:
        status, fresh, reason, assertion = (
            CapabilityStatus.UNAVAILABLE,
            FreshnessStatus.UNKNOWN,
            CapabilityReason.EXPLICIT_READ_FAILURE,
            AssertionKind.FACT,
        )
    elif item.validity is not EvidenceValidity.VALID:
        status, fresh, reason, assertion = (
            CapabilityStatus.UNAVAILABLE,
            FreshnessStatus.UNKNOWN,
            CapabilityReason.INVALID_OBSERVATION,
            AssertionKind.FACT,
        )
    elif item.value is None:
        status, fresh, reason, assertion = (
            CapabilityStatus.UNKNOWN,
            FreshnessStatus.UNKNOWN,
            CapabilityReason.MISSING_CALIBRATION,
            AssertionKind.UNKNOWN,
        )
    elif item.observation_at + timedelta(seconds=selector.max_age_seconds) + timedelta(microseconds=1) > now:
        status, fresh, reason, assertion = (
            CapabilityStatus.AVAILABLE,
            FreshnessStatus.FRESH,
            CapabilityReason.NO_FRESH_VALID_OBSERVATION,
            AssertionKind.INFERENCE,
        )
    else:
        status, fresh, reason, assertion = (
            CapabilityStatus.UNAVAILABLE,
            FreshnessStatus.STALE,
            CapabilityReason.MISSING_UPDATE,
            AssertionKind.INFERENCE,
        )
    return CapabilityInterval(
        start=now,
        end=end,
        capability=status,
        freshness=fresh,
        reason=reason,
        assertion=assertion,
        fidelity=fidelity,
        evidence_refs=ref,
    )


_ALL_RANK = {
    CapabilityStatus.AVAILABLE: 0,
    CapabilityStatus.DEGRADED: 1,
    CapabilityStatus.UNKNOWN: 2,
    CapabilityStatus.UNAVAILABLE: 3,
    CapabilityStatus.NOT_APPLICABLE: -1,
}
_ANY_RANK = {
    CapabilityStatus.UNAVAILABLE: 0,
    CapabilityStatus.UNKNOWN: 1,
    CapabilityStatus.DEGRADED: 2,
    CapabilityStatus.AVAILABLE: 3,
    CapabilityStatus.NOT_APPLICABLE: -1,
}


def reduce_capability(
    leaves: Iterable[CapabilityInterval],
    operator: CapabilityOperator,
    *,
    start: datetime,
    end: datetime,
    fidelity: CapabilityFidelity,
) -> CapabilityInterval:
    values = tuple(leaves)
    if not values:
        return CapabilityInterval(
            start=start,
            end=end,
            capability=CapabilityStatus.UNKNOWN,
            freshness=FreshnessStatus.UNKNOWN,
            reason=CapabilityReason.UNKNOWN_HISTORY,
            assertion=AssertionKind.UNKNOWN,
            fidelity=fidelity,
        )
    if any(value.reason is CapabilityReason.CONTRADICTORY_EVIDENCE for value in values):
        status, reason, assertion = (
            CapabilityStatus.UNKNOWN,
            CapabilityReason.CONTRADICTORY_EVIDENCE,
            AssertionKind.UNKNOWN,
        )
    else:
        applicable = tuple(value for value in values if value.capability is not CapabilityStatus.NOT_APPLICABLE)
        if not applicable:
            return CapabilityInterval(
                start=start,
                end=end,
                capability=CapabilityStatus.NOT_APPLICABLE,
                freshness=FreshnessStatus.NOT_APPLICABLE,
                reason=CapabilityReason.DISABLED,
                assertion=AssertionKind.FACT,
                fidelity=fidelity,
            )
        rank = _ALL_RANK if operator is CapabilityOperator.ALL_OF else _ANY_RANK
        chosen = max(applicable, key=lambda value: rank[value.capability])
        status, reason, assertion = chosen.capability, chosen.reason, chosen.assertion
    fresh = (
        FreshnessStatus.FRESH
        if status is CapabilityStatus.AVAILABLE
        else (FreshnessStatus.NOT_APPLICABLE if status is CapabilityStatus.NOT_APPLICABLE else FreshnessStatus.UNKNOWN)
    )
    refs = tuple(ref for value in values for ref in value.evidence_refs)
    return CapabilityInterval(
        start=start,
        end=end,
        capability=status,
        freshness=fresh,
        reason=reason,
        assertion=assertion,
        fidelity=fidelity,
        evidence_refs=refs,
    )


def evaluate_capabilities(
    topology: ResolvedTopology,
    request: RawEvidenceRequest,
    batch: RawEvidenceBatch,
    expressions: Iterable[TargetCapabilityExpression],
    *,
    evaluated_at: datetime | None = None,
) -> CapabilityEvaluation:
    _validate_inputs(topology, request, batch)
    expressions = tuple(sorted(expressions, key=lambda value: (value.target_id, value.capability)))
    if not expressions:
        raise CapabilityEvaluationError("at least one target capability expression is required")
    now = evaluated_at or batch.evaluation_time
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise CapabilityEvaluationError("evaluated_at must be UTC-aware")
    now = now.astimezone(UTC)
    fidelity = _fidelity(batch, topology.mode)
    selectors = {selector.channel_id: selector for selector in request.selectors}
    items_by_channel: dict[str, list[RawEvidenceItem]] = defaultdict(list)
    for item in batch.items:
        if item.channel_id is not None:
            items_by_channel[item.channel_id].append(item)
    results = []
    for expression in expressions:
        bindings = tuple(
            binding
            for binding in topology.bindings
            if binding.target_id == expression.target_id and binding.capability == expression.capability
        )
        points = {request.window_start, request.window_end}
        if not bindings:
            missing = CapabilityInterval(
                start=request.window_start,
                end=request.window_end,
                capability=CapabilityStatus.UNAVAILABLE,
                freshness=FreshnessStatus.UNKNOWN,
                reason=CapabilityReason.MISSING_BINDING,
                assertion=AssertionKind.FACT,
                fidelity=fidelity,
            )
            results.append(
                TargetCapabilityResult(
                    target_id=expression.target_id,
                    capability=expression.capability,
                    operator=expression.operator,
                    intervals=(missing,),
                )
            )
            continue
        for binding in bindings:
            if binding.interval.effective_from < request.window_end and (
                binding.interval.effective_to is None or binding.interval.effective_to > request.window_start
            ):
                points.add(max(request.window_start, binding.interval.effective_from))
                if binding.interval.effective_to is not None:
                    points.add(min(request.window_end, binding.interval.effective_to))
        for items in items_by_channel.values():
            for item in items:
                t = item.observation_at if topology.mode is TopologyMode.RECONSTRUCTED else item.received_at
                if request.window_start < t < request.window_end:
                    points.add(t)
                selector = next(
                    (candidate for candidate in request.selectors if candidate.channel_id == item.channel_id),
                    None,
                )
                if (
                    selector
                    and request.window_start
                    < item.observation_at + timedelta(seconds=selector.max_age_seconds) + timedelta(microseconds=1)
                    < request.window_end
                ):
                    points.add(
                        item.observation_at + timedelta(seconds=selector.max_age_seconds) + timedelta(microseconds=1)
                    )
        ordered = sorted(points)
        intervals: list[CapabilityInterval] = []
        for start, end in pairwise(ordered):
            leaves = []
            for binding in bindings:
                if not binding.interval.contains(start):
                    continue
                selector = selectors.get(binding.channel_id)
                profile = next((p for p in topology.capability_profiles if p.profile_id == binding.profile_id), None)
                if (
                    selector is None
                    or profile is None
                    or selector.profile_id != profile.profile_id
                    or selector.profile_version != profile.version
                ):
                    leaf = CapabilityInterval(
                        start=start,
                        end=end,
                        capability=CapabilityStatus.UNKNOWN,
                        freshness=FreshnessStatus.UNKNOWN,
                        reason=CapabilityReason.MISSING_CALIBRATION,
                        assertion=AssertionKind.UNKNOWN,
                        fidelity=fidelity,
                    )
                else:
                    eligible = [
                        item
                        for item in items_by_channel.get(binding.channel_id, ())
                        if item.observation_at <= start
                        and (
                            item.received_at <= start
                            if topology.mode is TopologyMode.AS_KNOWN_CORE
                            else item.received_at <= batch.data_cutoff
                        )
                    ]
                    latest_key = max(((item.observation_at, item.received_at) for item in eligible), default=None)
                    latest_items = (
                        [item for item in eligible if (item.observation_at, item.received_at) == latest_key]
                        if latest_key
                        else []
                    )
                    latest = max(
                        latest_items, key=lambda item: (item.event_identity, item.child_identity), default=None
                    )
                    if len({(item.evidence_kind, item.validity, item.value, item.reason) for item in latest_items}) > 1:
                        leaf = CapabilityInterval(
                            start=start,
                            end=end,
                            capability=CapabilityStatus.UNKNOWN,
                            freshness=FreshnessStatus.UNKNOWN,
                            reason=CapabilityReason.CONTRADICTORY_EVIDENCE,
                            assertion=AssertionKind.UNKNOWN,
                            fidelity=fidelity,
                            evidence_refs=tuple(_ref(item, fidelity) for item in latest_items),
                        )
                    else:
                        leaf = _leaf(latest, now=start, selector=selector, fidelity=fidelity)
                    leaf = leaf.model_copy(update={"end": end})
                leaves.append(leaf)
            if leaves:
                interval_result = reduce_capability(
                    leaves, expression.operator, start=start, end=end, fidelity=fidelity
                )
            else:
                interval_result = CapabilityInterval(
                    start=start,
                    end=end,
                    capability=CapabilityStatus.UNAVAILABLE,
                    freshness=FreshnessStatus.UNKNOWN,
                    reason=CapabilityReason.MISSING_BINDING,
                    assertion=AssertionKind.FACT,
                    fidelity=fidelity,
                )
            if intervals and intervals[-1].model_dump(exclude={"start", "end"}) == interval_result.model_dump(
                exclude={"start", "end"}
            ):
                intervals[-1] = intervals[-1].model_copy(update={"end": end})
            else:
                intervals.append(interval_result)
        results.append(
            TargetCapabilityResult(
                target_id=expression.target_id,
                capability=expression.capability,
                operator=expression.operator,
                intervals=tuple(intervals),
            )
        )
    evaluation = CapabilityEvaluation(
        evaluated_at=now,
        window_start=request.window_start,
        window_end=request.window_end,
        coverage_start=batch.coverage_start,
        coverage_end=batch.coverage_end,
        mode=topology.mode,
        data_cutoff=batch.data_cutoff,
        topology_revision_id=topology.revision_id,
        topology_digest=topology.digest,
        profile_identities=topology.profile_identities,
        fidelity=fidelity,
        targets=tuple(results),
        digest="0" * 64,
    )
    return evaluation.model_copy(update={"digest": compute_capability_digest(evaluation)})


evaluate = evaluate_capabilities
