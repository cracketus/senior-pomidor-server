from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from app.operator_tui.client import OperatorSnapshot, ViewName, ViewResult

UNAVAILABLE = "UNAVAILABLE"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> Sequence[Any]:
    return value if isinstance(value, list) else ()


def _text(value: Any, default: str = UNAVAILABLE) -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _number(value: Any, suffix: str = "", digits: int = 1) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return UNAVAILABLE
    return f"{float(value):.{digits}f}{suffix}"


def _timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return UNAVAILABLE
    return value.replace("+00:00", "Z")


def _envelope(result: ViewResult | None) -> Mapping[str, Any]:
    return _mapping(result.payload) if result is not None else {}


def _data(result: ViewResult | None) -> Mapping[str, Any]:
    return _mapping(_envelope(result).get("data"))


def _transport_notice(result: ViewResult | None) -> list[str]:
    if result is None:
        return ["TRANSPORT: DISCONNECTED — no response received"]
    if result.error is None:
        return []
    if result.payload is None:
        return [f"TRANSPORT: DISCONNECTED — {result.error}"]
    last = result.last_success_at_utc.isoformat().replace("+00:00", "Z") if result.last_success_at_utc else UNAVAILABLE
    return [f"TRANSPORT: STALE LAST-KNOWN DATA — {result.error}; last success {last}"]


def _header(title: str, result: ViewResult | None) -> list[str]:
    envelope = _envelope(result)
    lines = [title, "=" * len(title)]
    lines.extend(_transport_notice(result))
    if envelope:
        lines.append(
            " | ".join(
                [
                    f"status={_text(envelope.get('status'))}",
                    f"freshness={_text(envelope.get('freshness'))}",
                    f"availability={_text(envelope.get('availability'))}",
                    f"completeness={_text(envelope.get('completeness'))}",
                ]
            )
        )
        lines.append(f"generated={_timestamp(envelope.get('generated_at_utc'))}")
    lines.append("")
    return lines


def connection_summary(snapshot: OperatorSnapshot) -> str:
    if not snapshot.views:
        return "LOADING — no operator snapshot yet"
    results = list(snapshot.views.values())
    failed = [result for result in results if result.error is not None]
    no_payload = [result for result in failed if result.payload is None]
    if len(no_payload) == len(results):
        return f"DISCONNECTED — {len(no_payload)}/{len(results)} operator views unavailable"
    if failed:
        return f"DEGRADED TRANSPORT — {len(failed)}/{len(results)} views failed; last-known data is marked stale"
    return f"CONNECTED — {len(results)}/{len(results)} operator views refreshed"


def _state_lines(state: Mapping[str, Any]) -> list[str]:
    if not state:
        return ["Current state: UNAVAILABLE"]
    env = _mapping(state.get("env"))
    soil = _mapping(state.get("soil"))
    plant = _mapping(state.get("plant"))
    lines = [
        f"State: node={_text(state.get('node_id'))} status={_text(state.get('status'))} "
        f"confidence={_number(state.get('confidence'), digits=2)} observed={_timestamp(state.get('observed_at_utc'))}",
        "Air: "
        f"{_number(env.get('air_temp_c'), '°C')}  RH {_number(env.get('rh_pct'), '%')}  "
        f"VPD {_number(env.get('vpd_kpa'), ' kPa', 2)}  light {_number(env.get('lux'), ' lux', 0)}",
        f"Soil temp: {_number(soil.get('temp_c'), '°C')} | leaf temp: {_number(plant.get('leaf_temp_c'), '°C')}",
    ]
    probes = _items(soil.get("probes"))
    if not probes:
        lines.append("Soil probes: UNAVAILABLE")
    for raw_probe in probes:
        probe = _mapping(raw_probe)
        lines.append(
            f"  probe {_text(probe.get('id'))}/{_text(probe.get('position'))}: "
            f"moisture {_number(probe.get('moisture_pct'), '%')} "
            f"threshold {_number(probe.get('dry_threshold_pct'), '%')} "
            f"confidence {_number(probe.get('confidence'), digits=2)} status {_text(probe.get('status'))}"
        )
    return lines


def render_overview(snapshot: OperatorSnapshot) -> str:
    result = snapshot.result("status")
    lines = _header("OVERVIEW", result)
    data = _data(result)
    host = _mapping(data.get("host"))
    lines.append(
        f"Host: status={_text(host.get('status'))} availability={_text(host.get('availability'))} "
        f"freshness={_text(host.get('freshness'))}"
    )
    if host.get("reason"):
        lines.append(f"  reason: {_text(host.get('reason'))}")
    lines.extend(_state_lines(_mapping(data.get("state"))))
    lines.append("")
    edges = _items(data.get("edge"))
    if edges:
        edge_statuses = ", ".join(
            f"{_text(_mapping(edge).get('device_id'))}:{_text(_mapping(edge).get('status'))}" for edge in edges
        )
        lines.append(f"Edges: {edge_statuses}")
    else:
        lines.append("Edges: UNAVAILABLE")
    anomalies = _items(_data(snapshot.result("anomalies")).get("items"))
    alert_count = sum(1 for item in anomalies if _mapping(item).get("severity") == "ALERT")
    warn_count = sum(1 for item in anomalies if _mapping(item).get("severity") == "WARN")
    lines.append(f"Recent anomalies: {len(anomalies)} (ALERT {alert_count}, WARN {warn_count})")
    decision_result = snapshot.result("decisions")
    decision_items = _items(_data(decision_result).get("items"))
    lines.append(
        f"Decisions: availability={_text(_envelope(decision_result).get('availability'))} items={len(decision_items)}"
    )
    photos = _items(_data(snapshot.result("photos")).get("items"))
    if photos:
        latest = _mapping(photos[0])
        lines.append(f"Latest photo: {_text(latest.get('photo_id'))} @ {_timestamp(latest.get('captured_at_utc'))}")
    else:
        lines.append("Latest photo: UNAVAILABLE")
    return "\n".join(lines)


def render_plants(snapshot: OperatorSnapshot) -> str:
    result = snapshot.result("plants")
    lines = _header("PLANTS / PODS", result)
    items = _items(_data(result).get("items"))
    if not items:
        lines.append("No plant/pod observations available.")
    for raw_node in items:
        node = _mapping(raw_node)
        lines.append(
            f"Node {_text(node.get('node_id'))} | observed {_timestamp(node.get('observed_at_utc'))} | "
            f"state {_text(node.get('state_id'))}"
        )
        for raw_pod in _items(node.get("pods")):
            pod = _mapping(raw_pod)
            metrics = _mapping(pod.get("metrics"))
            air = _number(metrics.get("air_temperature_c"), "°C")
            rh = _number(metrics.get("air_humidity_percent"), "%")
            vpd = _number(metrics.get("air_vpd_kpa"), " kPa", 2)
            light = _number(metrics.get("light_lux"), " lux", 0)
            lines.append(
                f"  {_text(pod.get('pod_key'))}: moisture {_number(metrics.get('soil_moisture_percent'), '%')} | "
                f"soil {_number(metrics.get('soil_temperature_c'), '°C')} | "
                f"air {air} / RH {rh} | VPD {vpd} | light {light}"
            )
    lines.extend(["", "Canonical current state"])
    lines.extend(_state_lines(_mapping(_data(snapshot.result("status")).get("state"))))
    lines.extend(
        [
            "",
            "Target/risk bands: UNAVAILABLE — operator.v1 does not expose canonical targets.",
            "Leaf VPD: UNAVAILABLE — operator.v1 exposes leaf temperature only.",
        ]
    )
    return "\n".join(lines)


def render_edges(snapshot: OperatorSnapshot) -> str:
    result = snapshot.result("edge")
    lines = _header("EDGE", result)
    items = _items(_data(result).get("items"))
    if not items:
        lines.append("No edge reliability records available.")
    for raw_edge in items:
        edge = _mapping(raw_edge)
        freshness = _mapping(edge.get("freshness"))
        spool = _mapping(edge.get("spool"))
        app = _mapping(edge.get("application"))
        watchdog = _mapping(edge.get("watchdog"))
        device_id = _text(edge.get("device_id"))
        edge_status = _text(edge.get("status"))
        freshness_status = _text(freshness.get("status"))
        oldest = _number(spool.get("oldest_pending_age_seconds"), "s", 0)
        disk = _number(spool.get("disk_usage_percent"), "%")
        lines.extend(
            [
                f"{device_id}: status={edge_status} freshness={freshness_status} "
                f"age={_number(freshness.get('age_seconds'), 's', 0)}",
                f"  app: status={_text(app.get('status'))} running={_text(app.get('process_running'))} "
                f"uptime={_number(app.get('process_uptime_seconds'), 's', 0)}",
                f"  watchdog: status={_text(watchdog.get('status'))} restarts={_text(watchdog.get('restart_count'))} "
                f"reboots={_text(watchdog.get('reboot_count'))}",
                f"  spool: status={_text(spool.get('status'))} pending={_text(spool.get('pending_count'))} "
                f"backlog={_text(spool.get('backlog_count'))} dead={_text(spool.get('dead_letter_count'))} "
                f"oldest={oldest} disk={disk}",
            ]
        )
        for raw_reason in _items(edge.get("reasons"))[:5]:
            reason = _mapping(raw_reason)
            lines.append(
                f"  reason: {_text(reason.get('status'))} {_text(reason.get('code'))} — {_text(reason.get('message'))}"
            )
    lines.extend(["", "CPU/network summary: UNAVAILABLE — not exposed by operator edge-reliability.v1."])
    return "\n".join(lines)


def render_decisions(snapshot: OperatorSnapshot) -> str:
    result = snapshot.result("decisions")
    lines = _header("DECISIONS", result)
    items = _items(_data(result).get("items"))
    if not items:
        availability = _text(_envelope(result).get("availability"))
        lines.append(f"Decision feed: {availability}; no decision records exposed by operator.v1.")
        lines.append("No candidate action, guardrail result, execution result, or provenance is fabricated by the TUI.")
        return "\n".join(lines)
    for index, raw_item in enumerate(items, start=1):
        lines.append(f"#{index}: {_text(_mapping(raw_item))}")
    return "\n".join(lines)


def render_anomalies(snapshot: OperatorSnapshot) -> str:
    result = snapshot.result("anomalies")
    lines = _header("EVENTS / ANOMALIES", result)
    data = _data(result)
    items = _items(data.get("items"))
    if not items:
        lines.append("No recent anomalies exposed by the bounded operator view.")
    for raw_item in items:
        item = _mapping(raw_item)
        observed = _timestamp(item.get("observed_at_utc"))
        severity = _text(item.get("severity"))
        anomaly_type = _text(item.get("type"))
        node_id = _text(item.get("node_id"))
        status = _text(item.get("status"))
        anomaly_id = _text(item.get("anomaly_id"))
        lines.append(f"{observed} | {severity:<7} | {anomaly_type} | node={node_id} | status={status} | id={anomaly_id}")
        if item.get("state_id"):
            lines.append(f"  state_id={_text(item.get('state_id'))}")
    if data.get("has_more") is True:
        lines.append("More records exist; operator view is intentionally bounded.")
    lines.append("Correlation ID: UNAVAILABLE when not present in operator.v1 anomaly projection.")
    return "\n".join(lines)


def render_camera(snapshot: OperatorSnapshot) -> str:
    result = snapshot.result("photos")
    lines = _header("CAMERA", result)
    items = _items(_data(result).get("items"))
    if not items:
        lines.append("No photo metadata available.")
    for raw_item in items:
        item = _mapping(raw_item)
        sha = _text(item.get("sha256"))
        if sha != UNAVAILABLE:
            sha = sha[:12]
        captured = _timestamp(item.get("captured_at_utc"))
        photo_id = _text(item.get("photo_id"))
        node_id = _text(item.get("node_id"))
        content_type = _text(item.get("content_type"))
        size = _text(item.get("file_size_bytes"))
        sharpness = _number(item.get("sharpness_score"), digits=2)
        lines.append(
            f"{captured} | {photo_id} | node={node_id} | {content_type} | "
            f"size={size} B | sharpness={sharpness} | sha256={sha}…"
        )
    lines.extend(["", "Terminal image rendering: disabled in v1; photo metadata remains read-only."])
    return "\n".join(lines)


RENDERERS = {
    "overview": render_overview,
    "plants": render_plants,
    "edge": render_edges,
    "decisions": render_decisions,
    "anomalies": render_anomalies,
    "camera": render_camera,
}


def render_view(name: str, snapshot: OperatorSnapshot) -> str:
    renderer = RENDERERS.get(name)
    return "Unknown operator view" if renderer is None else renderer(snapshot)


def snapshot_generated_at(snapshot: OperatorSnapshot, view: ViewName = "status") -> datetime | None:
    result = snapshot.result(view)
    return result.fetched_at_utc if result is not None else None
