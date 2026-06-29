from __future__ import annotations

from dataclasses import dataclass

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError


@dataclass(frozen=True)
class ReadinessState:
    ready: bool
    database: str
    migration: str
    current_revision: str | None
    head_revision: str | None
    error: str | None = None


def get_alembic_head(alembic_ini_path: str = "alembic.ini") -> str:
    script = ScriptDirectory.from_config(Config(alembic_ini_path))
    head_revision = script.get_current_head()
    if head_revision is None:
        raise RuntimeError("Alembic head revision is unavailable")
    return head_revision


def get_database_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return context.get_current_revision()


def check_readiness(engine: Engine, alembic_ini_path: str = "alembic.ini") -> ReadinessState:
    head_revision = get_alembic_head(alembic_ini_path)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            context = MigrationContext.configure(connection)
            current_revision = context.get_current_revision()
    except SQLAlchemyError as exc:
        return ReadinessState(
            ready=False,
            database="unavailable",
            migration="unknown",
            current_revision=None,
            head_revision=head_revision,
            error=exc.__class__.__name__,
        )

    migration = "current" if current_revision == head_revision else "mismatch"
    return ReadinessState(
        ready=migration == "current",
        database="ok",
        migration=migration,
        current_revision=current_revision,
        head_revision=head_revision,
    )
