from __future__ import annotations

import stat
import threading
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent, CollectionStartEvent, DocumentStartEvent, ScalarEvent
from yaml.nodes import MappingNode

from app.map.models import (
    MAX_REVISIONS,
    EntityNamespace,
    ProfileIdentity,
    Relationship,
    RelationshipKind,
    ResolvedBinding,
    ResolvedTopology,
    TopologyCatalog,
    TopologyMode,
    TopologyRevision,
    TopologyStatus,
    compute_revision_digest,
)

MAX_YAML_BYTES = 1_048_576
MAX_YAML_EVENTS = 50_000
TOPOLOGY_UNAVAILABLE: Literal["TOPOLOGY_UNAVAILABLE"] = "TOPOLOGY_UNAVAILABLE"
TOPOLOGY_INVALID: Literal["TOPOLOGY_INVALID"] = "TOPOLOGY_INVALID"


class TopologyValidationError(ValueError):
    """A bounded topology validation failure safe to handle at the provider boundary."""


class TopologyUnavailableError(RuntimeError):
    code = TOPOLOGY_UNAVAILABLE


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: _UniqueKeySafeLoader, node: MappingNode, *, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise ConstructorError("mapping", node.start_mark, "unhashable mapping key", key_node.start_mark) from exc
        if duplicate:
            raise ConstructorError("mapping", node.start_mark, "duplicate mapping key", key_node.start_mark)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_topology_catalog(directory: str | Path) -> TopologyCatalog:
    root = Path(directory)
    try:
        root_stat = root.stat()
    except OSError as exc:
        raise TopologyValidationError("topology directory is unavailable") from exc
    if not stat.S_ISDIR(root_stat.st_mode) or root.is_symlink():
        raise TopologyValidationError("topology path must be a regular directory")

    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise TopologyValidationError("topology directory cannot be read") from exc
    if not entries or len(entries) > MAX_REVISIONS:
        raise TopologyValidationError("topology revision count is outside bounds")

    revisions: list[TopologyRevision] = []
    for path in entries:
        if path.suffix.lower() not in {".yaml", ".yml"}:
            raise TopologyValidationError("topology directory contains an unsupported entry")
        revisions.append(_load_revision(path))

    catalog = TopologyCatalog(revisions=tuple(revisions))
    _validate_catalog(catalog)
    return catalog


def _load_revision(path: Path) -> TopologyRevision:
    try:
        path_stat = path.stat()
    except OSError as exc:
        raise TopologyValidationError("topology revision cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISREG(path_stat.st_mode):
        raise TopologyValidationError("topology revision must be a regular file")
    if path_stat.st_size > MAX_YAML_BYTES:
        raise TopologyValidationError("topology revision exceeds the size limit")
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_YAML_BYTES + 1)
        if len(payload) > MAX_YAML_BYTES:
            raise TopologyValidationError("topology revision exceeds the size limit")
        document = payload.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise TopologyValidationError("topology revision cannot be read as UTF-8") from exc

    _validate_yaml_events(document)
    try:
        documents = list(yaml.load_all(document, Loader=_UniqueKeySafeLoader))
    except yaml.YAMLError as exc:
        raise TopologyValidationError("topology revision is malformed") from exc
    if len(documents) != 1 or not isinstance(documents[0], dict):
        raise TopologyValidationError("topology revision must contain one mapping document")
    try:
        revision = TopologyRevision.model_validate(documents[0])
    except ValidationError as exc:
        raise TopologyValidationError("topology revision schema validation failed") from exc
    if compute_revision_digest(revision) != revision.digest:
        raise TopologyValidationError("topology revision digest mismatch")
    return revision


def _validate_yaml_events(document: str) -> None:
    document_count = 0
    event_count = 0
    try:
        for event in yaml.parse(document, Loader=yaml.SafeLoader):
            event_count += 1
            if event_count > MAX_YAML_EVENTS:
                raise TopologyValidationError("topology revision exceeds the structural limit")
            if isinstance(event, DocumentStartEvent):
                document_count += 1
            if isinstance(event, AliasEvent):
                raise TopologyValidationError("YAML aliases are not permitted")
            if (
                isinstance(event, ScalarEvent | CollectionStartEvent)
                and event.tag is not None
                and not event.tag.startswith("tag:yaml.org,2002:")
            ):
                raise TopologyValidationError("custom YAML tags are not permitted")
    except yaml.YAMLError as exc:
        raise TopologyValidationError("topology revision is malformed") from exc
    if document_count != 1:
        raise TopologyValidationError("topology revision must contain one document")


def _validate_catalog(catalog: TopologyCatalog) -> None:
    revisions = catalog.revisions
    revision_by_id = _unique(revisions, "revision_id", "revision")
    for revision in revisions:
        _validate_revision(revision)
        if revision.supersedes is not None and revision.supersedes not in revision_by_id:
            raise TopologyValidationError("revision supersedes a missing revision")

    for revision in revisions:
        _assert_no_supersession_cycle(revision, revision_by_id)
        if revision.supersedes is not None:
            superseded = revision_by_id[revision.supersedes]
            if superseded.recorded_at >= revision.recorded_at:
                raise TopologyValidationError("revision supersession must point backward in recorded time")
            if not revision.interval.overlaps(superseded.interval):
                raise TopologyValidationError("superseding revisions must overlap in effective time")

    for index, left in enumerate(revisions):
        for right in revisions[index + 1 :]:
            if not left.interval.overlaps(right.interval):
                continue
            if not (_supersedes(left, right, revision_by_id) or _supersedes(right, left, revision_by_id)):
                raise TopologyValidationError("overlapping revisions require explicit supersession")


def _validate_revision(revision: TopologyRevision) -> None:
    assets = _unique(revision.physical_assets, "asset_id", "physical asset")
    sources = _unique(revision.sources, "source_id", "source")
    channels = _unique(revision.source_channels, "channel_id", "source channel")
    targets = _unique(revision.targets, "target_id", "target")
    deployments = _unique(revision.deployments, "deployment_id", "deployment")
    profiles = _unique(revision.capability_profiles, "profile_id", "capability profile")
    _unique(revision.relationships, "relationship_id", "relationship")
    _unique(revision.bindings, "binding_id", "binding")
    provenances = [revision.provenance]
    provenances.extend(binding.provenance for binding in revision.bindings)
    provenances.extend(profile.calibration_provenance for profile in revision.capability_profiles)
    _unique(provenances, "provenance_id", "provenance")

    local_keys: set[tuple[str, str]] = set()
    for channel in revision.source_channels:
        if channel.source_id not in sources:
            raise TopologyValidationError("source channel references a missing source")
        key = (channel.source_id, channel.source_local_key)
        if key in local_keys:
            raise TopologyValidationError("source-local channel identity is duplicated")
        local_keys.add(key)

    for deployment in revision.deployments:
        if deployment.asset_id not in assets or deployment.target_id not in targets:
            raise TopologyValidationError("deployment contains a dangling or type-invalid reference")
        if not _interval_within(deployment.interval, revision.interval):
            raise TopologyValidationError("deployment interval is outside its revision interval")

    for binding in revision.bindings:
        bound_channel = channels.get(binding.channel_id)
        profile = profiles.get(binding.profile_id)
        if bound_channel is None or binding.target_id not in targets or profile is None:
            raise TopologyValidationError("binding contains a dangling or type-invalid reference")
        if binding.capability != profile.capability or bound_channel.value_range.unit != profile.input_range.unit:
            raise TopologyValidationError("binding capability or unit conflicts with its profile/channel")
        if not _interval_within(binding.interval, revision.interval):
            raise TopologyValidationError("binding interval is outside its revision interval")

    entity_ids = {
        EntityNamespace.PHYSICAL_ASSET: set(assets),
        EntityNamespace.SOURCE: set(sources),
        EntityNamespace.SOURCE_CHANNEL: set(channels),
        EntityNamespace.TARGET: set(targets),
        EntityNamespace.DEPLOYMENT: set(deployments),
        EntityNamespace.CAPABILITY_PROFILE: set(profiles),
    }
    for relationship in revision.relationships:
        for reference in (relationship.from_ref, relationship.to_ref):
            if reference.entity_id not in entity_ids[reference.namespace]:
                raise TopologyValidationError("relationship contains a dangling or type-invalid reference")
        _validate_relationship_types(relationship)
    _validate_relationship_cycles(revision.relationships)


def _unique(items: Iterable[Any], attribute: str, namespace: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        identity = getattr(item, attribute)
        if identity in result:
            raise TopologyValidationError(f"duplicate identifier in {namespace} namespace")
        result[identity] = item
    return result


def _interval_within(inner: Any, outer: Any) -> bool:
    if inner.effective_from < outer.effective_from:
        return False
    if outer.effective_to is None:
        return True
    return inner.effective_to is not None and inner.effective_to <= outer.effective_to


def _validate_relationship_types(relationship: Relationship) -> None:
    pair = (relationship.from_ref.namespace, relationship.to_ref.namespace)
    allowed = {
        RelationshipKind.CONTAINMENT: {
            (EntityNamespace.PHYSICAL_ASSET, EntityNamespace.PHYSICAL_ASSET),
            (EntityNamespace.TARGET, EntityNamespace.TARGET),
        },
        RelationshipKind.PHYSICAL_LINK: {
            (EntityNamespace.PHYSICAL_ASSET, EntityNamespace.PHYSICAL_ASSET),
        },
        RelationshipKind.DATA_FLOW: {
            (EntityNamespace.SOURCE, EntityNamespace.SOURCE_CHANNEL),
            (EntityNamespace.SOURCE_CHANNEL, EntityNamespace.SOURCE_CHANNEL),
        },
        RelationshipKind.CAPABILITY_DEPENDENCY: {
            (EntityNamespace.CAPABILITY_PROFILE, EntityNamespace.CAPABILITY_PROFILE),
        },
    }
    if pair not in allowed[relationship.kind]:
        raise TopologyValidationError("relationship endpoint types do not match relationship kind")


def _validate_relationship_cycles(relationships: tuple[Relationship, ...]) -> None:
    adjacency: dict[tuple[EntityNamespace, str], set[tuple[EntityNamespace, str]]] = {}
    restricted_edges: list[tuple[tuple[EntityNamespace, str], tuple[EntityNamespace, str]]] = []
    for relationship in relationships:
        source = (relationship.from_ref.namespace, relationship.from_ref.entity_id)
        target = (relationship.to_ref.namespace, relationship.to_ref.entity_id)
        adjacency.setdefault(source, set()).add(target)
        if relationship.kind in {RelationshipKind.CONTAINMENT, RelationshipKind.CAPABILITY_DEPENDENCY}:
            restricted_edges.append((source, target))
    for source, target in restricted_edges:
        if source == target or _path_exists(target, source, adjacency):
            raise TopologyValidationError("containment or capability relationship cycle detected")


def _path_exists(
    start: tuple[EntityNamespace, str], goal: tuple[EntityNamespace, str], adjacency: dict[Any, set[Any]]
) -> bool:
    pending = [start]
    visited: set[tuple[EntityNamespace, str]] = set()
    while pending:
        current = pending.pop()
        if current == goal:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacency.get(current, ()))
    return False


def _assert_no_supersession_cycle(revision: TopologyRevision, revision_by_id: dict[str, TopologyRevision]) -> None:
    visited = {revision.revision_id}
    current = revision
    while current.supersedes is not None:
        if current.supersedes in visited:
            raise TopologyValidationError("revision supersession cycle detected")
        visited.add(current.supersedes)
        current = revision_by_id[current.supersedes]


def _supersedes(
    candidate: TopologyRevision, other: TopologyRevision, revision_by_id: dict[str, TopologyRevision]
) -> bool:
    current = candidate
    while current.supersedes is not None:
        if current.supersedes == other.revision_id:
            return True
        current = revision_by_id[current.supersedes]
    return False


class TopologyProvider:
    def __init__(self, directory: str | Path = "config/topology", *, autoload: bool = True) -> None:
        self._directory = Path(directory)
        self._lock = threading.RLock()
        self._catalog: TopologyCatalog | None = None
        self._status = TopologyStatus(available=False, error_code=TOPOLOGY_UNAVAILABLE)
        if autoload:
            self.reload()

    @property
    def catalog(self) -> TopologyCatalog | None:
        with self._lock:
            return self._catalog

    @property
    def status(self) -> TopologyStatus:
        with self._lock:
            return self._status

    def reload(self) -> bool:
        try:
            candidate = load_topology_catalog(self._directory)
        except (OSError, TopologyValidationError):
            with self._lock:
                if self._catalog is None:
                    self._status = TopologyStatus(available=False, error_code=TOPOLOGY_UNAVAILABLE)
                else:
                    active = self._latest_revision(self._catalog)
                    self._status = TopologyStatus(
                        available=True,
                        revision_id=active.revision_id,
                        digest=active.digest,
                        error_code=TOPOLOGY_INVALID,
                    )
            return False

        active = self._latest_revision(candidate)
        with self._lock:
            self._catalog = candidate
            self._status = TopologyStatus(
                available=True,
                revision_id=active.revision_id,
                digest=active.digest,
                error_code=None,
            )
        return True

    def snapshot(
        self,
        at: datetime,
        mode: TopologyMode = TopologyMode.AS_KNOWN_CORE,
        data_cutoff: datetime | None = None,
    ) -> ResolvedTopology:
        at = self._validate_utc(at)
        cutoff = at if data_cutoff is None else self._validate_utc(data_cutoff)
        if at > cutoff:
            raise ValueError("selected topology time cannot exceed data_cutoff")
        mode = TopologyMode(mode)
        with self._lock:
            catalog = self._catalog
        if catalog is None:
            raise TopologyUnavailableError("topology is unavailable")

        recorded_bound = at if mode is TopologyMode.AS_KNOWN_CORE else cutoff
        applicable = [
            revision
            for revision in catalog.revisions
            if revision.recorded_at <= recorded_bound and revision.interval.contains(at)
        ]
        if not applicable:
            raise TopologyUnavailableError("topology is unavailable for the selected time")
        revision_by_id = {revision.revision_id: revision for revision in catalog.revisions}
        winners = [
            revision
            for revision in applicable
            if not any(other is not revision and _supersedes(other, revision, revision_by_id) for other in applicable)
        ]
        if len(winners) != 1:
            raise TopologyUnavailableError("topology selection is ambiguous")
        revision = winners[0]
        return ResolvedTopology(
            schema_version=revision.schema_version,
            selected_at=at,
            mode=mode,
            data_cutoff=cutoff,
            revision_id=revision.revision_id,
            digest=revision.digest,
            provenance=revision.provenance,
            profile_identities=tuple(
                ProfileIdentity(profile_id=profile.profile_id, version=profile.version)
                for profile in revision.capability_profiles
            ),
            physical_assets=revision.physical_assets,
            sources=revision.sources,
            source_channels=revision.source_channels,
            targets=revision.targets,
            deployments=revision.deployments,
            relationships=revision.relationships,
            bindings=revision.bindings,
            capability_profiles=revision.capability_profiles,
        )

    def resolve_bindings(
        self,
        target_id: str,
        capability: str,
        at: datetime,
        mode: TopologyMode = TopologyMode.AS_KNOWN_CORE,
        data_cutoff: datetime | None = None,
    ) -> tuple[ResolvedBinding, ...]:
        snapshot = self.snapshot(at, mode, data_cutoff)
        targets = {target.target_id: target for target in snapshot.targets}
        if target_id not in targets:
            return ()
        channels = {channel.channel_id: channel for channel in snapshot.source_channels}
        sources = {source.source_id: source for source in snapshot.sources}
        profiles = {profile.profile_id: profile for profile in snapshot.capability_profiles}
        matches: list[ResolvedBinding] = []
        for binding in snapshot.bindings:
            if binding.target_id != target_id or binding.capability != capability or not binding.interval.contains(at):
                continue
            channel = channels[binding.channel_id]
            matches.append(
                ResolvedBinding(
                    schema_version=snapshot.schema_version,
                    selected_at=snapshot.selected_at,
                    mode=snapshot.mode,
                    data_cutoff=snapshot.data_cutoff,
                    revision_id=snapshot.revision_id,
                    digest=snapshot.digest,
                    revision_provenance=snapshot.provenance,
                    target=targets[target_id],
                    binding=binding,
                    source=sources[channel.source_id],
                    channel=channel,
                    profile=profiles[binding.profile_id],
                )
            )
        return tuple(sorted(matches, key=lambda item: item.binding.binding_id))

    @staticmethod
    def _latest_revision(catalog: TopologyCatalog) -> TopologyRevision:
        return max(catalog.revisions, key=lambda revision: (revision.recorded_at, revision.revision_id))

    @staticmethod
    def _validate_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("timestamp must be UTC-aware")
        return value.astimezone(UTC)
