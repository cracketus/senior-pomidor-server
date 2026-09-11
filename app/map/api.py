from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import engine
from app.map import TopologyMode
from app.map.service import MapService, MapServiceError, decode_cursor, encode_cursor, request_id

router = APIRouter(prefix="/api/v1/map", tags=["map"])
logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 1_048_576


def _bounded_response(body: dict[str, Any], rid: str) -> JSONResponse:
    raw = json.dumps(body, separators=(",", ":")).encode()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise MapServiceError("QUERY_LIMIT_EXCEEDED", 422)
    return JSONResponse(body, headers={"X-Request-ID": rid})


def _error(exc: MapServiceError, rid: str) -> JSONResponse:
    return JSONResponse(
        {
            "schema_version": "senior-pomidor.map.v1",
            "request_id": rid,
            "error": {"code": exc.code, "message": str(exc)},
        },
        status_code=exc.status,
        headers={"X-Request-ID": rid},
    )


def _time(value: str | None, name: str, default: datetime) -> datetime:
    if value is None:
        return default
    try:
        if not value.endswith("Z"):
            raise ValueError
        timestamp = value[:-1]
        if "." in timestamp:
            fraction = timestamp.rsplit(".", 1)[1]
            if not fraction.isdigit() or len(fraction) > 6:
                raise ValueError
        parsed = datetime.fromisoformat(timestamp + "+00:00")
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError
        return parsed.astimezone(UTC)
    except ValueError as exc:
        raise MapServiceError("INVALID_QUERY", 400, f"invalid {name}") from exc


def _mode(value: str) -> TopologyMode:
    try:
        return TopologyMode(value)
    except ValueError as exc:
        raise MapServiceError("INVALID_QUERY", 400, "invalid mode") from exc


def _page_size(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise MapServiceError("INVALID_QUERY", 400, "invalid page_size") from exc
    return parsed


def _cursor_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise MapServiceError("INVALID_CURSOR", 400)
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError
        return parsed.astimezone(UTC)
    except ValueError as exc:
        raise MapServiceError("INVALID_CURSOR", 400) from exc


def _json_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _service(request: Request) -> MapService:
    provider = request.app.dependency_overrides.get(get_settings, get_settings)
    return MapService(provider(), engine)


def _auth(service: MapService, authorization: str | None, targets: list[str]) -> tuple[str, ...]:
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
    return service.authorize(token, targets)


def _reject_repeated_singletons(request: Request) -> None:
    singleton_names = {"at", "mode", "data_cutoff", "page_size", "cursor", "from", "to"}
    repeated = sorted(name for name in singleton_names if len(request.query_params.getlist(name)) > 1)
    if repeated:
        raise MapServiceError("INVALID_QUERY", 400, "repeated singleton query parameter")


@router.get("/topology")
def topology(
    request: Request,
    entity_id: Annotated[list[str] | None, Query()] = None,
    at: str | None = None,
    mode: str = "AS_KNOWN_CORE",
    data_cutoff: str | None = None,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    rid = request_id(request.headers.get("X-Request-ID"))
    try:
        _reject_repeated_singletons(request)
        service = _service(request)
        targets = _auth(service, authorization, entity_id or [])
        now = service.clock()
        cutoff = _time(data_cutoff, "data_cutoff", now)
        if cutoff > now:
            raise MapServiceError("INVALID_QUERY", 400, "data_cutoff must not be in the future")
        selected = _time(at, "at", cutoff)
        if selected > cutoff:
            raise MapServiceError("INVALID_QUERY", 400, "at must not exceed data_cutoff")
        result = service.topology(targets, selected, _mode(mode), cutoff)
        adapter = service.adapter()
        body = {
            "schema_version": "senior-pomidor.map.v1",
            "request_id": rid,
            "scope": {"entity_ids": targets},
            "query": {"at": _json_time(selected), "mode": mode, "data_cutoff": _json_time(cutoff)},
            "versions": {
                "topology_digest": result.digest,
                "adapter_version": adapter.adapter_version,
                "adapter_digest": adapter.digest,
                "ordering": "topology-v1",
            },
            "completeness": {"complete": True, "has_more": False},
            "topology": result.model_dump(mode="json"),
        }
        return _bounded_response(body, rid)
    except MapServiceError as exc:
        return _error(exc, rid)


@router.get("/snapshot")
def snapshot(
    request: Request,
    entity_id: Annotated[list[str] | None, Query()] = None,
    at: str | None = None,
    mode: str = "AS_KNOWN_CORE",
    data_cutoff: str | None = None,
    page_size: str = "500",
    cursor: str | None = None,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    return _evaluation(request, entity_id, at, None, mode, data_cutoff, page_size, cursor, authorization, False)


@router.get("/timeline")
def timeline(
    request: Request,
    entity_id: Annotated[list[str] | None, Query()] = None,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: str | None = None,
    data_cutoff: str | None = None,
    mode: str = "AS_KNOWN_CORE",
    page_size: str = "500",
    cursor: str | None = None,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    return _evaluation(request, entity_id, from_, to, mode, data_cutoff, page_size, cursor, authorization, True)


def _evaluation(
    request: Request,
    entity_id: list[str] | None,
    start_value: str | None,
    end_value: str | None,
    mode_value: str,
    cutoff_value: str | None,
    page_size_value: str,
    cursor: str | None,
    authorization: str | None,
    timeline_mode: bool,
) -> JSONResponse:
    rid = request_id(request.headers.get("X-Request-ID"))
    try:
        _reject_repeated_singletons(request)
        if timeline_mode and request.query_params.getlist("at"):
            raise MapServiceError("INVALID_QUERY", 400, "at is not valid for timeline")
        if not timeline_mode and (request.query_params.getlist("from") or request.query_params.getlist("to")):
            raise MapServiceError("INVALID_QUERY", 400, "from/to are not valid for snapshot")
        page_size = _page_size(page_size_value)
        service = _service(request)
        targets = _auth(service, authorization, entity_id or [])
        if timeline_mode and ((start_value is None) != (end_value is None)):
            raise MapServiceError("INVALID_QUERY", 400, "timeline requires both from and to")
        if not 1 <= page_size <= 500:
            raise MapServiceError("INVALID_QUERY", 400, "page_size must be between 1 and 500")
        mode = _mode(mode_value)
        now = service.clock()
        cursor_data: dict[str, Any] | None = None
        if cursor:
            cursor_data = decode_cursor(service.settings.map_api_token or "", cursor)
        cutoff = (
            _cursor_time(cursor_data.get("cutoff"))
            if cursor_data is not None and cutoff_value is None
            else _time(cutoff_value, "data_cutoff", now)
        )
        if cutoff > now:
            raise MapServiceError("INVALID_QUERY", 400, "data_cutoff must not be in the future")
        end = _time(start_value, "at", cutoff) if not timeline_mode else _time(end_value, "to", cutoff)
        start = _time(start_value, "from", end - timedelta(hours=24)) if timeline_mode else end
        logical_at = end
        if not timeline_mode:
            start, end = end, end + timedelta(microseconds=1)
        point_window = not timeline_mode and end == cutoff + timedelta(microseconds=1)
        if end <= start:
            raise MapServiceError("INVALID_QUERY", 400, "range must be non-empty and ordered")
        if end - start > timedelta(days=7) or (end > cutoff and not point_window):
            raise MapServiceError("QUERY_LIMIT_EXCEEDED", 422)
        input_digest = hashlib.sha256(
            json.dumps(
                {
                    "scope": targets,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "mode": mode.value,
                    "cutoff": cutoff.isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        offset = 0
        if cursor_data is not None:
            expected = {
                "scope": list(targets),
                "mode": mode.value,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "cutoff": cutoff.isoformat(),
                "page_size": page_size,
                "input_digest": input_digest,
            }
            if any(cursor_data.get(key) != value for key, value in expected.items()):
                raise MapServiceError("INVALID_CURSOR", 400)
            offset = cursor_data.get("offset", -1)
            if not isinstance(offset, int) or offset < 0:
                raise MapServiceError("INVALID_CURSOR", 400)
        if timeline_mode:
            _topology, evaluation, evidence_digest = service.evaluate_timeline(targets, start, end, mode, cutoff)
        else:
            _topology, evaluation, evidence_digest = service.evaluate(
                targets, start, end, logical_at, mode, cutoff, point_query_at=logical_at
            )
        versions = {
            "topology_digest": evaluation.topology_digest,
            "adapter_version": service.adapter().adapter_version,
            "adapter_digest": service.adapter().digest,
            "evidence_digest": evidence_digest,
            "profile_versions": [
                {"profile_id": item.profile_id, "version": item.version} for item in evaluation.profile_identities
            ],
            "ordering": "interval-v1",
        }
        if cursor_data is not None and any(cursor_data.get(key) != value for key, value in versions.items()):
            raise MapServiceError("SNAPSHOT_CHANGED", 409)
        flattened = [(target, interval) for target in evaluation.targets for interval in target.intervals]
        page = flattened[offset : offset + page_size]
        by_target: dict[str, list[Any]] = {}
        for target, interval in page:
            by_target.setdefault(target.target_id, []).append(interval)
        evaluation = evaluation.model_copy(
            update={
                "targets": tuple(
                    target.model_copy(update={"intervals": tuple(by_target.get(target.target_id, ()))})
                    for target in evaluation.targets
                    if target.target_id in by_target
                )
            }
        )
        next_cursor = None
        if offset + page_size < len(flattened):
            next_cursor = encode_cursor(
                service.settings.map_api_token or "",
                {
                    "scope": list(targets),
                    "mode": mode.value,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "cutoff": cutoff.isoformat(),
                    "page_size": page_size,
                    "input_digest": input_digest,
                    "offset": offset + page_size,
                    **versions,
                },
            )
        payload = evaluation.model_dump(mode="json")
        body = {
            "schema_version": "senior-pomidor.map.v1",
            "request_id": rid,
            "scope": {"entity_ids": targets},
            "query": {
                "window_start": _json_time(start),
                "window_end": _json_time(end),
                "mode": mode.value,
                "data_cutoff": _json_time(cutoff),
            },
            "versions": versions,
            "completeness": {
                "complete": next_cursor is None,
                "has_more": next_cursor is not None,
                "page_size": page_size,
            },
            "evaluation": payload,
            "next_cursor": next_cursor,
        }
        raw = json.dumps(body, separators=(",", ":")).encode()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MapServiceError("QUERY_LIMIT_EXCEEDED", 422)
        logger.info(
            "map_api_complete request_id=%s mode=%s entity_count=%s interval_count=%s response_bytes=%s result_code=OK",
            rid,
            mode.value,
            len(targets),
            sum(len(item.intervals) for item in evaluation.targets),
            len(raw),
        )
        return JSONResponse(body, headers={"X-Request-ID": rid})
    except MapServiceError as exc:
        return _error(exc, rid)


@router.get("/evidence/{evidence_id}")
def evidence(
    evidence_id: str,
    request: Request,
    entity_id: Annotated[list[str] | None, Query()] = None,
    at: str | None = None,
    mode: str = "AS_KNOWN_CORE",
    data_cutoff: str | None = None,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    rid = request_id(request.headers.get("X-Request-ID"))
    try:
        _reject_repeated_singletons(request)
        service = _service(request)
        targets = _auth(service, authorization, entity_id or [])
        if len(evidence_id) != 64 or any(char not in "0123456789abcdef" for char in evidence_id):
            raise MapServiceError("INVALID_QUERY", 400)
        now = service.clock()
        cutoff = _time(data_cutoff, "data_cutoff", now)
        if cutoff > now:
            raise MapServiceError("INVALID_QUERY", 400, "data_cutoff must not be in the future")
        selected = _time(at, "at", cutoff)
        if selected > cutoff:
            raise MapServiceError("INVALID_QUERY", 400, "at must not exceed data_cutoff")
        result = service.evidence(targets, evidence_id, selected, cutoff, _mode(mode))
        adapter = service.adapter()
        topology = service.topology(targets, selected, _mode(mode), cutoff)
        body = {
            "schema_version": "senior-pomidor.map.v1",
            "request_id": rid,
            "scope": {"entity_ids": targets},
            "query": {
                "at": _json_time(selected),
                "mode": mode,
                "data_cutoff": _json_time(cutoff),
            },
            "versions": {
                "topology_digest": topology.digest,
                "adapter_version": adapter.adapter_version,
                "adapter_digest": adapter.digest,
                "ordering": "evidence-v1",
            },
            "completeness": {"complete": True, "has_more": False},
            "evidence": result,
        }
        return _bounded_response(body, rid)
    except MapServiceError as exc:
        return _error(exc, rid)
