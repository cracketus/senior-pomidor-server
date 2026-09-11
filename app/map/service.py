from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

from sqlalchemy import Engine

from app.map import (
    CapabilityEvaluation,
    CapabilityFidelity,
    CapabilityOperator,
    CapabilityResultInterval,
    EntityNamespace,
    EvidenceMode,
    RawEvidenceErrorCode,
    RawEvidenceReader,
    RawEvidenceReadError,
    RawEvidenceRequest,
    ResolvedTopology,
    TargetCapabilityExpression,
    TargetCapabilityResult,
    TopologyMode,
    TopologyProvider,
    evaluate_capabilities,
)
from app.map.adapter import AdapterConfig, AdapterConfigError, load_adapter_config

MAX_TARGETS = 50
MAX_PAGE_SIZE = 500
MAX_RESPONSE_BYTES = 1_048_576
MAX_CURSOR_BODY_BYTES = 4096
MAX_CURSOR_ENCODED_LENGTH = ((MAX_CURSOR_BODY_BYTES + 1 + hashlib.sha256().digest_size + 2) // 3) * 4
_semaphore = threading.BoundedSemaphore(2)


class MapServiceError(RuntimeError):
    def __init__(self, code: str, status: int, message: str = "request cannot be completed") -> None:
        super().__init__(message)
        self.code, self.status = code, status


def utc_now() -> datetime:
    return datetime.now(UTC)


class MapService:
    def __init__(self, settings: Any, engine: Engine, *, clock: Callable[[], datetime] = utc_now) -> None:
        self.settings = settings
        self.engine = engine
        self.clock = clock
        self.provider = TopologyProvider(settings.map_api_topology_path)

    def ensure_enabled(self) -> None:
        if self.settings.deployment_mode != "development" or not self.settings.map_api_enabled:
            raise MapServiceError("MAP_DISABLED", 503)
        if not self.settings.map_api_token:
            raise MapServiceError("MAP_UNAVAILABLE", 503)

    def allowed_targets(self) -> set[str]:
        try:
            value = json.loads(self.settings.map_api_allowed_target_ids)
            if not isinstance(value, list) or not value or len(value) > MAX_TARGETS:
                raise ValueError
            if any(not isinstance(item, str) or not item or len(item) > 64 for item in value):
                raise ValueError
            result = set(value)
            if len(result) != len(value) or any(not item or len(item) > 64 for item in result):
                raise ValueError
            return result
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MapServiceError("MAP_UNAVAILABLE", 503) from exc

    def authorize(self, token: str | None, targets: list[str]) -> tuple[str, ...]:
        self.ensure_enabled()
        if not token or not hmac.compare_digest(token, self.settings.map_api_token or ""):
            raise MapServiceError("FORBIDDEN", 403)
        if not targets or len(targets) > MAX_TARGETS or len(set(targets)) != len(targets):
            raise MapServiceError("INVALID_QUERY", 400)
        allowlist = self.allowed_targets()
        if any(target not in allowlist for target in targets):
            raise MapServiceError("FORBIDDEN", 403)
        return tuple(sorted(targets))

    def adapter(self) -> AdapterConfig:
        try:
            return load_adapter_config(self.settings.map_api_adapter_config_path)
        except AdapterConfigError as exc:
            raise MapServiceError("MAP_UNAVAILABLE", 503) from exc

    def _validate_adapter(self, config: AdapterConfig, topology: ResolvedTopology) -> None:
        catalog = self.provider.catalog
        if catalog is None:
            raise MapServiceError("MAP_UNAVAILABLE", 503)
        channels = {
            channel.channel_id: channel for revision in catalog.revisions for channel in revision.source_channels
        }
        sources = {source.source_id for revision in catalog.revisions for source in revision.sources}
        for mapping in config.mappings:
            channel = channels.get(mapping.channel_id)
            if channel is None or mapping.source_id not in sources:
                raise MapServiceError("MAP_UNAVAILABLE", 503)
            quantity = mapping.metric_name.value.replace("_", "-").replace("-percent", "-pct")
            if (
                channel.source_id != mapping.source_id
                or channel.source_local_key != mapping.pod_key
                or channel.quantity != quantity
                or channel.value_range.unit != mapping.unit
                or channel.value_range.minimum != mapping.minimum
                or channel.value_range.maximum != mapping.maximum
            ):
                raise MapServiceError("MAP_UNAVAILABLE", 503)
        mapped = {mapping.channel_id for mapping in config.mappings}
        if any(binding.channel_id not in mapped for binding in topology.bindings):
            raise MapServiceError("MAP_UNAVAILABLE", 503)

    def topology(
        self, targets: tuple[str, ...], at: datetime, mode: TopologyMode, cutoff: datetime
    ) -> ResolvedTopology:
        try:
            topology = self.provider.snapshot(at, mode, cutoff)
        except Exception as exc:
            raise MapServiceError("TOPOLOGY_UNAVAILABLE", 503) from exc
        known = {item.target_id for item in topology.targets}
        if any(target not in known for target in targets):
            raise MapServiceError("NOT_FOUND", 404)
        self._validate_adapter(self.adapter(), topology)
        target_set = set(targets)
        scoped_bindings = tuple(binding for binding in topology.bindings if binding.target_id in target_set)
        scoped_deployments = tuple(item for item in topology.deployments if item.target_id in target_set)
        channel_ids = {item.channel_id for item in scoped_bindings}
        channels = tuple(item for item in topology.source_channels if item.channel_id in channel_ids)
        source_ids = {item.source_id for item in channels}
        sources = tuple(item for item in topology.sources if item.source_id in source_ids)
        profile_ids = {item.profile_id for item in scoped_bindings}
        profiles = tuple(item for item in topology.capability_profiles if item.profile_id in profile_ids)
        profile_identities = tuple(
            identity for identity in topology.profile_identities if identity.profile_id in profile_ids
        )
        asset_ids = {item.asset_id for item in scoped_deployments}
        assets = tuple(item for item in topology.physical_assets if item.asset_id in asset_ids)
        allowed_refs = {
            EntityNamespace.PHYSICAL_ASSET: asset_ids,
            EntityNamespace.SOURCE: source_ids,
            EntityNamespace.SOURCE_CHANNEL: channel_ids,
            EntityNamespace.TARGET: target_set,
            EntityNamespace.DEPLOYMENT: {item.deployment_id for item in scoped_deployments},
            EntityNamespace.CAPABILITY_PROFILE: profile_ids,
        }
        relationships = tuple(
            item
            for item in topology.relationships
            if item.from_ref.entity_id in allowed_refs.get(item.from_ref.namespace, set())
            and item.to_ref.entity_id in allowed_refs.get(item.to_ref.namespace, set())
        )
        return topology.model_copy(
            update={
                "physical_assets": assets,
                "sources": sources,
                "source_channels": channels,
                "targets": tuple(item for item in topology.targets if item.target_id in target_set),
                "deployments": scoped_deployments,
                "relationships": relationships,
                "bindings": scoped_bindings,
                "capability_profiles": profiles,
                "profile_identities": profile_identities,
            }
        )

    def _timeline_boundaries(self, start: datetime, end: datetime) -> tuple[datetime, ...]:
        catalog = self.provider.catalog
        if catalog is None:
            raise MapServiceError("TOPOLOGY_UNAVAILABLE", 503)
        points = {start, end}
        for revision in catalog.revisions:
            for point in (revision.recorded_at, revision.interval.effective_from, revision.interval.effective_to):
                if point is not None and start < point < end:
                    points.add(point)
        return tuple(sorted(points))

    def evaluate_timeline(
        self,
        targets: tuple[str, ...],
        start: datetime,
        end: datetime,
        mode: TopologyMode,
        cutoff: datetime,
        point_query_at: datetime | None = None,
    ) -> tuple[ResolvedTopology, CapabilityEvaluation, str]:
        segment_inputs: list[tuple[ResolvedTopology, RawEvidenceRequest]] = []
        boundaries = self._timeline_boundaries(start, end)
        for segment_start, segment_end in pairwise(boundaries):
            topology = self.topology(targets, segment_start, mode, cutoff)
            segment_inputs.append(
                (
                    topology,
                    self._build_request(topology, targets, segment_start, segment_end, segment_start, mode, cutoff),
                )
            )
        if not segment_inputs:
            raise MapServiceError("TOPOLOGY_UNAVAILABLE", 503)
        if not _semaphore.acquire(blocking=False):
            raise MapServiceError("BUSY", 429)
        try:
            try:
                batches = RawEvidenceReader(self.engine, clock=self.clock).read_many(
                    tuple(request for _, request in segment_inputs)
                )
            except RawEvidenceReadError as exc:
                if exc.code is RawEvidenceErrorCode.QUERY_TIMEOUT:
                    raise MapServiceError("QUERY_TIMEOUT", 504) from exc
                if exc.code is RawEvidenceErrorCode.QUERY_LIMIT_EXCEEDED:
                    raise MapServiceError("QUERY_LIMIT_EXCEEDED", 422) from exc
                raise MapServiceError("BACKEND_UNAVAILABLE", 503) from exc
            except Exception as exc:
                raise MapServiceError("BACKEND_UNAVAILABLE", 503) from exc
            evaluations = [
                (topology, self._evaluate_batch(topology, request, batch, targets), batch.digest)
                for (topology, request), batch in zip(segment_inputs, batches, strict=True)
            ]
        finally:
            _semaphore.release()
        base_topology, base, _ = evaluations[0]
        grouped: dict[tuple[str, str, str], list[CapabilityResultInterval]] = {}
        operators: dict[tuple[str, str, str], Any] = {}
        for _, evaluation, _ in evaluations:
            for target in evaluation.targets:
                key = (target.target_id, target.capability, target.operator.value)
                intervals = grouped.setdefault(key, [])
                for interval in target.intervals:
                    if (
                        intervals
                        and intervals[-1].end == interval.start
                        and intervals[-1].model_dump(exclude={"start", "end"})
                        == interval.model_dump(exclude={"start", "end"})
                    ):
                        intervals[-1] = intervals[-1].model_copy(update={"end": interval.end})
                    else:
                        intervals.append(interval)
                operators[key] = target.operator
        results = tuple(
            TargetCapabilityResult(
                target_id=key[0], capability=key[1], operator=operators[key], intervals=tuple(grouped[key])
            )
            for key in sorted(grouped)
        )
        topology_digest = hashlib.sha256(
            "|".join(evaluation.topology_digest for _, evaluation, _ in evaluations).encode()
        ).hexdigest()
        combined = base.model_copy(
            update={
                "window_start": start,
                "window_end": end,
                "coverage_start": min(item.coverage_start for _, item, _ in evaluations),
                "coverage_end": max(item.coverage_end for _, item, _ in evaluations),
                "topology_revision_id": "timeline-" + topology_digest[:16],
                "topology_digest": topology_digest,
                "profile_identities": tuple(
                    sorted(
                        {identity for _, item, _ in evaluations for identity in item.profile_identities},
                        key=lambda value: (value.profile_id, value.version),
                    )
                ),
                "fidelity": CapabilityFidelity.RECONSTRUCTED if mode is TopologyMode.RECONSTRUCTED else base.fidelity,
                "targets": results,
            }
        )
        from app.map.capability import compute_capability_digest

        evidence_digest = hashlib.sha256("|".join(digest for _, _, digest in evaluations).encode()).hexdigest()
        return (
            base_topology,
            combined.model_copy(update={"digest": compute_capability_digest(combined)}),
            evidence_digest,
        )

    def _build_request(
        self,
        topology: ResolvedTopology,
        targets: tuple[str, ...],
        start: datetime,
        end: datetime,
        at: datetime,
        mode: TopologyMode,
        cutoff: datetime,
        point_query_at: datetime | None = None,
    ) -> RawEvidenceRequest:
        config = self.adapter()
        self._validate_adapter(config, topology)
        mappings = {item.channel_id: item for item in config.mappings}
        selectors = []
        for target in targets:
            bindings = [b for b in topology.bindings if b.target_id == target and b.interval.contains(at)]
            for binding in bindings:
                mapping = mappings.get(binding.channel_id)
                profile = next((p for p in topology.capability_profiles if p.profile_id == binding.profile_id), None)
                if mapping is not None and profile is not None:
                    selectors.append(mapping.selector(binding, profile.version))
        return RawEvidenceRequest(
            selectors=tuple({item.channel_id: item for item in selectors}.values()),
            window_start=start,
            window_end=end,
            mode=EvidenceMode(mode.value),
            data_cutoff=cutoff,
            receipt_cutoff=point_query_at if mode is TopologyMode.AS_KNOWN_CORE else None,
            allow_empty_selectors=not selectors,
            topology_revision_id=topology.revision_id,
            topology_digest=topology.digest,
            point_query_at=point_query_at,
        )

    @staticmethod
    def _evaluate_batch(
        topology: ResolvedTopology,
        request: RawEvidenceRequest,
        batch: Any,
        targets: tuple[str, ...],
    ) -> CapabilityEvaluation:
        expressions = tuple(
            TargetCapabilityExpression(
                target_id=binding.target_id,
                capability=binding.capability,
                operator=CapabilityOperator.ALL_OF,
            )
            for binding in topology.bindings
        )
        if not expressions:
            expressions = tuple(
                TargetCapabilityExpression(target_id=target, capability="unknown", operator=CapabilityOperator.ALL_OF)
                for target in targets
            )
        return evaluate_capabilities(
            topology,
            request,
            batch,
            tuple({(item.target_id, item.capability): item for item in expressions}.values()),
            evaluated_at=batch.evaluation_time,
        )

    def evaluate(
        self,
        targets: tuple[str, ...],
        start: datetime,
        end: datetime,
        at: datetime,
        mode: TopologyMode,
        cutoff: datetime,
        point_query_at: datetime | None = None,
    ) -> Any:
        topology = self.topology(targets, at, mode, cutoff)
        request = self._build_request(topology, targets, start, end, at, mode, cutoff, point_query_at)
        if not _semaphore.acquire(blocking=False):
            raise MapServiceError("BUSY", 429)
        try:
            try:
                batch = RawEvidenceReader(self.engine, clock=self.clock).read(request)
            except RawEvidenceReadError as exc:
                if exc.code is RawEvidenceErrorCode.QUERY_TIMEOUT:
                    raise MapServiceError("QUERY_TIMEOUT", 504) from exc
                if exc.code is RawEvidenceErrorCode.QUERY_LIMIT_EXCEEDED:
                    raise MapServiceError("QUERY_LIMIT_EXCEEDED", 422) from exc
                raise MapServiceError("BACKEND_UNAVAILABLE", 503) from exc
            except Exception as exc:
                raise MapServiceError("BACKEND_UNAVAILABLE", 503) from exc
            return topology, self._evaluate_batch(topology, request, batch, targets), batch.digest
        finally:
            _semaphore.release()

    def evidence(
        self, targets: tuple[str, ...], evidence_id: str, at: datetime, cutoff: datetime, mode: TopologyMode
    ) -> dict[str, Any]:
        for target in targets:
            try:
                return self._evidence_one(target, evidence_id, at, cutoff, mode)
            except MapServiceError as exc:
                if exc.code != "NOT_FOUND":
                    raise
        raise MapServiceError("NOT_FOUND", 404)

    def _evidence_one(
        self, target: str, evidence_id: str, at: datetime, cutoff: datetime, mode: TopologyMode
    ) -> dict[str, Any]:
        topology = self.topology((target,), at, mode, cutoff)
        config = self.adapter()
        selectors = []
        for binding in topology.bindings:
            if binding.target_id != target or not binding.interval.contains(at):
                continue
            mapping = next((item for item in config.mappings if item.channel_id == binding.channel_id), None)
            profile = next(
                (item for item in topology.capability_profiles if item.profile_id == binding.profile_id), None
            )
            if mapping is not None and profile is not None:
                selectors.append(mapping.selector(binding, profile.version))
        if not selectors:
            raise MapServiceError("NOT_FOUND", 404)
        start = at - max((timedelta(seconds=item.max_age_seconds) for item in selectors), default=timedelta(hours=24))
        request = RawEvidenceRequest(
            selectors=tuple({item.channel_id: item for item in selectors}.values()),
            window_start=start,
            window_end=at + timedelta(microseconds=1),
            mode=EvidenceMode(mode.value),
            data_cutoff=cutoff,
            receipt_cutoff=at if mode is TopologyMode.AS_KNOWN_CORE else None,
            allow_empty_selectors=not selectors,
            topology_revision_id=topology.revision_id,
            topology_digest=topology.digest,
            point_query_at=at if at == cutoff else None,
        )
        try:
            batch = RawEvidenceReader(self.engine, clock=self.clock).read(request)
        except RawEvidenceReadError as exc:
            if exc.code is RawEvidenceErrorCode.QUERY_TIMEOUT:
                raise MapServiceError("QUERY_TIMEOUT", 504) from exc
            if exc.code is RawEvidenceErrorCode.QUERY_LIMIT_EXCEEDED:
                raise MapServiceError("QUERY_LIMIT_EXCEEDED", 422) from exc
            raise MapServiceError("BACKEND_UNAVAILABLE", 503) from exc
        except Exception as exc:
            raise MapServiceError("BACKEND_UNAVAILABLE", 503) from exc
        for item in batch.items:
            identity = f"{item.event_identity}\x00{item.child_identity}".encode("utf-8", errors="replace")
            if hashlib.sha256(identity).hexdigest() == evidence_id:
                return item.model_dump(mode="json", exclude={"event_identity", "child_identity", "record_id"})
        raise MapServiceError("NOT_FOUND", 404)


def encode_cursor(secret: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + b"." + signature).decode().rstrip("=")


def decode_cursor(secret: str, value: str) -> dict[str, Any]:
    try:
        if len(value) > MAX_CURSOR_ENCODED_LENGTH:
            raise ValueError
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        body, signature = raw.rsplit(b".", 1)
        if not hmac.compare_digest(signature, hmac.new(secret.encode(), body, hashlib.sha256).digest()):
            raise ValueError
        result = json.loads(body)
        if not isinstance(result, dict) or len(body) > MAX_CURSOR_BODY_BYTES:
            raise ValueError
        return result
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeError) as exc:
        raise MapServiceError("INVALID_CURSOR", 400) from exc


def request_id(value: str | None) -> str:
    if value and len(value) <= 128 and all(char.isalnum() or char in "-_." for char in value):
        return value
    return str(uuid.uuid4())
