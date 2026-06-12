from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import get_db
from app.main import app
from app.models import Base


@pytest.fixture
def client_factory(tmp_path: Path) -> Generator[Callable[..., TestClient], None, None]:
    clients: list[TestClient] = []
    engines: list[Any] = []

    def create_client(**settings_overrides: Any) -> TestClient:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        engines.append(engine)
        Base.metadata.create_all(engine)
        TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

        def override_db() -> Generator[Session, None, None]:
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        def override_settings() -> Settings:
            values: dict[str, Any] = {
                "database_url": "sqlite:///:memory:",
                "photo_storage_dir": str(tmp_path / "photos"),
                "photo_upload_token": None,
            }
            values.update(settings_overrides)
            return Settings(**values)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_settings] = override_settings
        client = TestClient(app)
        clients.append(client)
        return client

    try:
        yield create_client
    finally:
        for client in clients:
            client.close()
        app.dependency_overrides.clear()
        for engine in engines:
            engine.dispose()


@pytest.fixture
def client(client_factory: Callable[..., TestClient]) -> TestClient:
    return client_factory()
