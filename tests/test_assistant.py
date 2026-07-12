import asyncio
import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.assistant import (
    AssistantCapabilities,
    AssistantContext,
    AssistantContextBounds,
    AssistantContextError,
    AssistantErrorCode,
    AssistantModality,
    AssistantProviderError,
    AssistantProviderRegistry,
    AssistantService,
    AssistantSessionBootstrap,
    AssistantSessionRequest,
    AssistantTransportCapability,
    SqlAlchemyAssistantContextProvider,
    build_default_tools,
)
from app.assistant.tools import AssistantToolError
from app.models import (
    AnomalyRecord,
    Base,
    Device,
    Photo,
    PodReading,
    SensorHealthSnapshot,
    StateSnapshot,
    TelemetryEvent,
)

NOW = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _add_device(db: Session, node_id: str) -> None:
    db.add(Device(device_id=node_id, first_seen_at=NOW, last_seen_at=NOW, last_payload_at=NOW))


def _add_event(db: Session, node_id: str, *, timestamp: datetime, marker: float, secret: str) -> None:
    event = TelemetryEvent(
        device_id=node_id,
        timestamp_utc=timestamp,
        schema_version="telemetry_v1",
        source="http",
        raw_payload_jsonb={"permanent_api_key": secret},
        system_health_jsonb={"status": "ok", "access_token": secret},
        received_at=timestamp,
    )
    db.add(event)
    db.flush()
    db.add(
        PodReading(
            telemetry_event_id=event.id,
            device_id=node_id,
            pod_key="pod-1",
            enabled=True,
            air_temperature_c=marker,
            metrics_jsonb={"custom_metric": marker, "password": secret},
        )
    )


def _seed_context(db: Session) -> None:
    _add_device(db, "pi-001")
    _add_device(db, "pi-002")
    _add_event(db, "pi-001", timestamp=NOW - timedelta(minutes=5), marker=25.0, secret="secret-one")
    _add_event(db, "pi-001", timestamp=NOW - timedelta(days=2), marker=10.0, secret="old-secret")
    _add_event(db, "pi-002", timestamp=NOW - timedelta(minutes=5), marker=99.0, secret="secret-two")
    db.add_all(
        [
            StateSnapshot(
                state_id="state-1",
                node_id="pi-001",
                ts=NOW,
                payload_jsonb={
                    "node_id": "pi-001",
                    "env": {"air_temp_c": 25.0},
                    "private_storage_path": "C:/private/state.jsonl",
                    "provider_secret": "secret-one",
                },
                generated_at=NOW,
            ),
            StateSnapshot(
                state_id="state-2",
                node_id="pi-002",
                ts=NOW,
                payload_jsonb={"node_id": "pi-002", "env": {"air_temp_c": 99.0}},
                generated_at=NOW,
            ),
            SensorHealthSnapshot(
                health_id="health-1",
                node_id="pi-001",
                ts=NOW,
                payload_jsonb={"node_id": "pi-001", "status": "GOOD"},
            ),
            AnomalyRecord(
                anomaly_id="anomaly-1",
                node_id="pi-001",
                type="HIGH_HEAT",
                status="ACTIVE",
                severity="WARN",
                ts=NOW,
                state_id="state-1",
                payload_jsonb={"node_id": "pi-001", "type": "HIGH_HEAT", "status": "ACTIVE"},
            ),
            AnomalyRecord(
                anomaly_id="anomaly-other",
                node_id="pi-002",
                type="OTHER_NODE",
                status="ACTIVE",
                severity="CRITICAL",
                ts=NOW,
                state_id="state-2",
                payload_jsonb={"node_id": "pi-002", "type": "OTHER_NODE", "status": "ACTIVE"},
            ),
            Photo(
                photo_id="photo-1",
                device_id="pi-001",
                captured_at_utc=NOW,
                schema_version="photo_v1",
                sharpness_score=12.0,
                content_type="image/jpeg",
                file_size_bytes=123,
                storage_path="C:/private/photos/pi-001/photo-1.jpg",
                sha256="a" * 64,
                received_at=NOW,
            ),
        ]
    )
    db.commit()


def test_context_is_bounded_redacted_and_isolated_to_selected_node(db: Session) -> None:
    _seed_context(db)
    bounds = AssistantContextBounds(history_lookback=timedelta(hours=24), max_history_items=1)
    provider = SqlAlchemyAssistantContextProvider(db, bounds=bounds, clock=lambda: NOW)

    context = provider.build_context("pi-001")
    serialized = json.dumps(context.as_dict(), sort_keys=True)

    assert context.node_id == "pi-001"
    assert context.current_state is not None
    assert context.current_state["env"]["air_temp_c"] == 25.0
    assert len(context.recent_history) == 1
    assert context.recent_history[0]["readings"][0]["metrics"]["air_temperature_c"] == 25.0
    assert {item["type"] for item in context.active_anomalies} == {"HIGH_HEAT"}
    assert context.recent_photos[0]["photo_id"] == "photo-1"
    assert "storage_path" not in serialized
    assert "C:/private" not in serialized
    assert "secret-one" not in serialized
    assert "secret-two" not in serialized
    assert "99.0" not in serialized
    assert "10.0" not in serialized
    assert "[redacted]" in serialized


def test_context_rejects_invalid_and_unknown_nodes(db: Session) -> None:
    provider = SqlAlchemyAssistantContextProvider(db, clock=lambda: NOW)

    with pytest.raises(AssistantContextError, match="unsafe"):
        provider.build_context("../pi-001")
    with pytest.raises(AssistantContextError, match="not found"):
        provider.build_context("pi-404")


def test_context_enforces_serialized_size_ceiling(db: Session) -> None:
    _add_device(db, "pi-001")
    db.add(
        StateSnapshot(
            state_id="huge",
            node_id="pi-001",
            ts=NOW,
            payload_jsonb={"notes": "x" * 10_000},
            generated_at=NOW,
        )
    )
    db.commit()
    bounds = AssistantContextBounds(max_context_bytes=400, max_section_bytes=20_000, max_string_chars=20_000)

    context = SqlAlchemyAssistantContextProvider(db, bounds=bounds, clock=lambda: NOW).build_context("pi-001")

    assert len(json.dumps(context.as_dict(), separators=(",", ":")).encode()) <= 400


def test_default_tools_are_allow_listed_and_session_node_bound(db: Session) -> None:
    _seed_context(db)
    context = SqlAlchemyAssistantContextProvider(db, clock=lambda: NOW).build_context("pi-001")
    tools = build_default_tools()

    result = tools.execute("get_current_state", context)

    assert result["node_id"] == "pi-001"
    assert result["result"]["node_id"] == "pi-001"
    with pytest.raises(AssistantToolError, match="allow-listed"):
        tools.execute("delete_telemetry", context)
    with pytest.raises(AssistantToolError, match="does not accept"):
        tools.execute("get_current_state", context, {"node_id": "pi-002"})


class FakeContextProvider:
    def build_context(self, node_id: str) -> AssistantContext:
        return AssistantContext(node_id, NOW, {"node_id": node_id}, (), (), None, ())


class FakeProvider:
    def __init__(self, name: str) -> None:
        self._name = name
        self.received_context: AssistantContext | None = None
        self.received_tools: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self._name

    def capabilities(self) -> AssistantCapabilities:
        return AssistantCapabilities(
            provider=self.name,
            modalities=(AssistantModality.TEXT, AssistantModality.AUDIO_INPUT, AssistantModality.AUDIO_OUTPUT),
            transports=(AssistantTransportCapability.WEBRTC,),
            available=True,
        )

    async def create_session(self, request, context, tools) -> AssistantSessionBootstrap:
        self.received_context = context
        self.received_tools = tuple(tool.name for tool in tools)
        return AssistantSessionBootstrap(
            provider=self.name,
            session_id=f"{self.name}-session",
            expires_at=NOW + timedelta(minutes=1),
            transport=AssistantTransportCapability.WEBRTC,
            bootstrap={"opaque": True},
        )


def test_provider_can_be_substituted_without_changing_orchestration() -> None:
    first = FakeProvider("first")
    second = FakeProvider("planttalk_openai")
    registry = AssistantProviderRegistry((first, second), active_provider="planttalk_openai")
    service = AssistantService(providers=registry, context_provider=FakeContextProvider(), tools=build_default_tools())

    session = asyncio.run(service.create_session(AssistantSessionRequest(node_id="pi-001")))

    assert session.provider == "planttalk_openai"
    assert first.received_context is None
    assert second.received_context is not None
    assert second.received_context.node_id == "pi-001"
    assert second.received_tools == (
        "get_current_state",
        "get_recent_history",
        "get_active_anomalies",
        "get_sensor_health",
        "get_recent_photos",
    )


def test_registry_reports_stable_configuration_error() -> None:
    registry = AssistantProviderRegistry((), active_provider="planttalk_openai")

    with pytest.raises(AssistantProviderError) as caught:
        registry.get_active()

    assert caught.value.code is AssistantErrorCode.CONFIGURATION
    assert caught.value.retryable is False


@pytest.mark.parametrize(
    ("code", "retryable"),
    [
        (AssistantErrorCode.UNAVAILABLE, True),
        (AssistantErrorCode.TIMEOUT, True),
        (AssistantErrorCode.RATE_LIMITED, True),
        (AssistantErrorCode.CONFIGURATION, False),
        (AssistantErrorCode.EXPIRED_SESSION, False),
    ],
)
def test_provider_failures_have_normalized_categories(code: AssistantErrorCode, retryable: bool) -> None:
    error = AssistantProviderError(code, "safe message", retryable=retryable)

    assert error.code is code
    assert error.retryable is retryable
    assert str(error) == "safe message"
