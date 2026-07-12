from __future__ import annotations

import secrets
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock


class AssistantSessionNotFoundError(ValueError):
    pass


class AssistantSessionExpiredError(ValueError):
    pass


@dataclass(frozen=True)
class AssistantSessionRecord:
    session_id: str
    provider: str
    provider_session_id: str
    node_id: str
    expires_at: datetime


class AssistantSessionStore:
    """Bounded in-memory metadata store; it never stores conversation content."""

    def __init__(self, *, max_sessions: int = 1_000, clock: Callable[[], datetime] | None = None) -> None:
        self._max_sessions = max_sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._records: dict[str, AssistantSessionRecord] = {}
        self._lock = Lock()

    def create(
        self,
        *,
        provider: str,
        provider_session_id: str,
        node_id: str,
        expires_at: datetime,
    ) -> AssistantSessionRecord:
        with self._lock:
            self._prune_expired()
            while len(self._records) >= self._max_sessions:
                oldest_id = min(self._records, key=lambda key: self._records[key].expires_at)
                del self._records[oldest_id]
            session_id = secrets.token_urlsafe(32)
            record = AssistantSessionRecord(session_id, provider, provider_session_id, node_id, expires_at)
            self._records[session_id] = record
            return record

    def get(self, session_id: str) -> AssistantSessionRecord:
        with self._lock:
            record = self._records.get(session_id)
            if record is None:
                raise AssistantSessionNotFoundError("assistant session not found")
            if record.expires_at <= self._now():
                del self._records[session_id]
                raise AssistantSessionExpiredError("assistant session expired")
            return record

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def _prune_expired(self) -> None:
        now = self._now()
        for session_id in [key for key, record in self._records.items() if record.expires_at <= now]:
            del self._records[session_id]

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class FixedWindowRateLimiter:
    def __init__(self, *, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = self._clock()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
