from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import state_estimator_worker
from app.config import settings
from app.models import AnomalyRecord, Base, EstimatorDiagnostic, SensorHealthSnapshot, StateSnapshot
from app.services import persist_telemetry
from app.validation import TELEMETRY_SCHEMA


def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def dispose_session_factory(testing_session_local) -> None:
    testing_session_local.kw["bind"].dispose()


def telemetry_payload() -> dict:
    return {
        "schema_version": TELEMETRY_SCHEMA,
        "device_id": "pi-001",
        "timestamp_utc": "2026-07-02T08:00:00Z",
        "pods": {
            "pod-1": {
                "enabled": True,
                "air_temperature_c": 33.0,
                "air_humidity_percent": 35.0,
                "soil_moisture_percent": 42.0,
                "soil_temperature_c": 20.0,
                "light_lux": 12000.0,
                "leaf_temp_c": 23.5,
            }
        },
    }


def test_state_estimator_worker_run_once_persists_rows_and_private_jsonl(monkeypatch, tmp_path) -> None:
    TestingSessionLocal = session_factory()
    private_log_dir = tmp_path / "private"
    try:
        monkeypatch.setattr(state_estimator_worker, "SessionLocal", TestingSessionLocal)
        monkeypatch.setattr(settings, "state_estimator_timezone", "Europe/Vienna")
        monkeypatch.setattr(settings, "state_estimator_private_log_dir", str(private_log_dir))

        with TestingSessionLocal() as db:
            persist_telemetry(db, telemetry_payload(), source="http")

        assert state_estimator_worker.run_once() == 1

        with TestingSessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(StateSnapshot)) == 1
            assert db.scalar(select(func.count()).select_from(SensorHealthSnapshot)) == 1
            assert db.scalar(select(func.count()).select_from(AnomalyRecord)) >= 1
            assert db.scalar(select(func.count()).select_from(EstimatorDiagnostic)) == 1

        assert (private_log_dir / "states_2026-07.jsonl").is_file()
        assert (private_log_dir / "sensor_health_2026-07.jsonl").is_file()
        assert (private_log_dir / "anomalies_2026-07.jsonl").is_file()
        assert (private_log_dir / "estimator_diagnostics_2026-07-02.jsonl").is_file()
    finally:
        dispose_session_factory(TestingSessionLocal)
