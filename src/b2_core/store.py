"""Local anonymous session storage; short transactions never enclose inference.

SQLiteStore and InMemoryStore have identical semantics. Pending turns are leases,
not startup state: opening another store must never clear a live reservation.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Callable, Iterator, Protocol, runtime_checkable
from uuid import uuid4

from .contracts import ChatRequest, ChatResponse, Message, SessionCreate, SessionDTO


class StoreError(RuntimeError):
    code = "STORE_ERROR"

    def __init__(self, message: str = "storage operation failed") -> None:
        self.message = message
        super().__init__(message)


class ResourceNotFound(StoreError):
    code = "RESOURCE_NOT_FOUND"

    def __init__(self, message: str = "resource not found") -> None:
        super().__init__(message)


# Both spellings identify the same exception; ownership is never exposed.
NotFound = ResourceNotFound


class TurnInProgress(StoreError):
    code = "TURN_IN_PROGRESS"

    def __init__(
        self,
        message: str = "session has a pending turn",
        *,
        session_id: str | None = None,
        client_turn_id: str | None = None,
        lease_expires_at: float | None = None,
    ) -> None:
        self.session_id = session_id
        self.client_turn_id = client_turn_id
        self.lease_expires_at = lease_expires_at
        super().__init__(message)


class StoreBusy(StoreError):
    code = "STORE_BUSY"

    def __init__(self, message: str = "storage is busy; retry later") -> None:
        super().__init__(message)


class StoreClosed(StoreError):
    code = "STORE_CLOSED"

    def __init__(self, message: str = "storage is closed") -> None:
        super().__init__(message)


class StaleReservation(StoreError):
    code = "STALE_RESERVATION"

    def __init__(self, message: str = "turn reservation is missing, expired or replaced") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class AnonymousIdentity:
    user_id: str
    cookie_token: str | None


@dataclass(frozen=True)
class TurnReservation:
    user_id: str
    session_id: str
    client_turn_id: str
    token: str
    lease_expires_at: float


@runtime_checkable
class Store(Protocol):
    def resolve_user(self, token: str | None) -> AnonymousIdentity: ...
    def create_session(self, user_id: str, title: str = "新会话") -> SessionDTO: ...
    def list_sessions(self, user_id: str) -> list[SessionDTO]: ...
    def get_messages(self, user_id: str, session_id: str) -> list[Message]: ...
    def delete_session(self, user_id: str, session_id: str) -> None: ...
    def reserve_turn(self, user_id: str, session_id: str, client_turn_id: str) -> TurnReservation | ChatResponse: ...
    def complete_turn(self, reservation: TurnReservation, user_text: str, response: ChatResponse) -> None: ...
    def abort_turn(self, reservation: TurnReservation) -> None: ...
    def close(self) -> None: ...


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError(f"{name} must contain 1-128 characters and not be blank")


def _finite_number(value: float, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return float(value)


def _timestamp(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_reservation(reservation: TurnReservation) -> None:
    if not isinstance(reservation, TurnReservation):
        raise ValueError("reservation must be a TurnReservation")
    for name in ("user_id", "session_id", "client_turn_id", "token"):
        _identifier(getattr(reservation, name), name)
    _finite_number(reservation.lease_expires_at, "lease_expires_at")


def _storage_exception(error: sqlite3.Error) -> StoreError:
    primary_code = getattr(error, "sqlite_errorcode", 0) & 0xFF
    if primary_code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return StoreBusy()
    return StoreError()


class SQLiteStore:
    """Thread-safe SQLite storage, also safe for competing instances on one file.

    ``clock`` returns UNIX seconds; its production default is time.time. All
    instances sharing a file must use compatible clocks and lease settings.
    Connections do not retain a transaction between method calls.
    """

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        clock: Callable[[], float] = time.time,
        lease_seconds: float = 300.0,
        timeout: float = 5.0,
    ) -> None:
        if not callable(clock):
            raise ValueError("clock must be callable")
        self._lease_seconds = _finite_number(lease_seconds, "lease_seconds")
        if self._lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        timeout = _finite_number(timeout, "timeout", minimum=0)
        self._clock = clock
        self._lock = RLock()
        self._closed = False
        self.path = str(path)
        if self.path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.path, timeout=timeout, check_same_thread=False, isolation_level=None)
        except sqlite3.Error as error:
            raise _storage_exception(error) from error
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA foreign_keys = ON")
            with self._transaction(write=True):
                for statement in (
                    """CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        token_sha256 TEXT NOT NULL UNIQUE,
                        memory_enabled INTEGER NOT NULL DEFAULT 1 CHECK(memory_enabled IN (0, 1)),
                        created_at TEXT NOT NULL
                    )""",
                    """CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        title TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )""",
                    """CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                        role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )""",
                    """CREATE TABLE IF NOT EXISTS turns (
                        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                        client_turn_id TEXT NOT NULL,
                        token TEXT NOT NULL,
                        lease_expires_at REAL NOT NULL,
                        status TEXT NOT NULL CHECK(status IN ('pending', 'completed')),
                        response_json TEXT,
                        CHECK((status = 'pending' AND response_json IS NULL)
                            OR (status = 'completed' AND response_json IS NOT NULL)),
                        PRIMARY KEY(session_id, client_turn_id)
                    )""",
                    "CREATE INDEX IF NOT EXISTS sessions_by_user ON sessions(user_id)",
                    "CREATE INDEX IF NOT EXISTS messages_by_session ON messages(session_id, id)",
                    """CREATE UNIQUE INDEX IF NOT EXISTS one_pending_turn_per_session
                        ON turns(session_id) WHERE status = 'pending'""",
                ):
                    self._conn.execute(statement)
        except BaseException:
            self._conn.close()
            self._closed = True
            raise

    def _now(self) -> float:
        return _finite_number(self._clock(), "clock result")

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[None]:
        with self._lock:
            if self._closed:
                raise StoreClosed()
            begun = False
            try:
                self._conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                begun = True
                yield
                self._conn.commit()
                begun = False
            except BaseException as error:
                if begun:
                    try:
                        self._conn.rollback()
                    except sqlite3.Error:
                        # Preserve the operation's actual failure, never mask it.
                        pass
                if isinstance(error, sqlite3.Error):
                    raise _storage_exception(error) from error
                raise

    def _user(self, user_id: str) -> sqlite3.Row:
        row = self._conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ResourceNotFound()
        return row

    def _session(self, user_id: str, session_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT id, title, created_at FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
        if row is None:
            raise ResourceNotFound()
        return row

    @staticmethod
    def _session_dto(row: sqlite3.Row) -> SessionDTO:
        return SessionDTO(id=row["id"], title=row["title"], created_at=row["created_at"])

    @staticmethod
    def _in_progress(row: sqlite3.Row, session_id: str) -> TurnInProgress:
        return TurnInProgress(session_id=session_id, client_turn_id=row["client_turn_id"],
                              lease_expires_at=row["lease_expires_at"])

    def resolve_user(self, token: str | None) -> AnonymousIdentity:
        if token is not None and not isinstance(token, str):
            raise ValueError("cookie token must be a string or None")
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else None
        with self._transaction(write=True):
            if token_hash is not None:
                row = self._conn.execute("SELECT id FROM users WHERE token_sha256 = ?", (token_hash,)).fetchone()
                if row is not None:
                    return AnonymousIdentity(user_id=row["id"], cookie_token=None)
            new_token = secrets.token_urlsafe(32)
            user_id = "user_" + uuid4().hex
            self._conn.execute(
                "INSERT INTO users(id, token_sha256, memory_enabled, created_at) VALUES (?, ?, 1, ?)",
                (user_id, hashlib.sha256(new_token.encode("utf-8")).hexdigest(), _timestamp(self._now())),
            )
            return AnonymousIdentity(user_id=user_id, cookie_token=new_token)

    def create_session(self, user_id: str, title: str = "新会话") -> SessionDTO:
        _identifier(user_id, "user_id")
        validated = SessionCreate(title=title)
        with self._transaction(write=True):
            self._user(user_id)
            session = SessionDTO(id="session_" + uuid4().hex, title=validated.title, created_at=_timestamp(self._now()))
            self._conn.execute(
                "INSERT INTO sessions(id, user_id, title, created_at) VALUES (?, ?, ?, ?)",
                (session.id, user_id, session.title, session.created_at),
            )
            return session

    def list_sessions(self, user_id: str) -> list[SessionDTO]:
        _identifier(user_id, "user_id")
        with self._transaction():
            self._user(user_id)
            rows = self._conn.execute(
                "SELECT id, title, created_at FROM sessions WHERE user_id = ? ORDER BY created_at DESC, id",
                (user_id,),
            ).fetchall()
            return [self._session_dto(row) for row in rows]

    def get_messages(self, user_id: str, session_id: str) -> list[Message]:
        _identifier(user_id, "user_id")
        _identifier(session_id, "session_id")
        with self._transaction():
            self._session(user_id, session_id)
            rows = self._conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
            ).fetchall()
            return [Message(role=row["role"], content=row["content"]) for row in rows]

    def delete_session(self, user_id: str, session_id: str) -> None:
        _identifier(user_id, "user_id")
        _identifier(session_id, "session_id")
        with self._transaction(write=True):
            self._session(user_id, session_id)
            pending = self._conn.execute(
                "SELECT client_turn_id, lease_expires_at FROM turns WHERE session_id = ? AND status = 'pending' AND lease_expires_at > ?",
                (session_id, self._now()),
            ).fetchone()
            if pending is not None:
                raise self._in_progress(pending, session_id)
            self._conn.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))

    def reserve_turn(self, user_id: str, session_id: str, client_turn_id: str) -> TurnReservation | ChatResponse:
        for name, value in (("user_id", user_id), ("session_id", session_id), ("client_turn_id", client_turn_id)):
            _identifier(value, name)
        with self._transaction(write=True):
            self._session(user_id, session_id)
            completed = self._conn.execute(
                "SELECT response_json FROM turns WHERE session_id = ? AND client_turn_id = ? AND status = 'completed'",
                (session_id, client_turn_id),
            ).fetchone()
            if completed is not None:
                return ChatResponse.model_validate_json(completed["response_json"])
            now = self._now()
            self._conn.execute(
                "DELETE FROM turns WHERE session_id = ? AND status = 'pending' AND lease_expires_at <= ?",
                (session_id, now),
            )
            pending = self._conn.execute(
                "SELECT client_turn_id, lease_expires_at FROM turns WHERE session_id = ? AND status = 'pending'",
                (session_id,),
            ).fetchone()
            if pending is not None:
                raise self._in_progress(pending, session_id)
            reservation = TurnReservation(user_id=user_id, session_id=session_id, client_turn_id=client_turn_id,
                                          token=secrets.token_urlsafe(32), lease_expires_at=now + self._lease_seconds)
            self._conn.execute(
                """INSERT INTO turns(session_id, client_turn_id, token, lease_expires_at, status, response_json)
                   VALUES (?, ?, ?, ?, 'pending', NULL)""",
                (session_id, client_turn_id, reservation.token, reservation.lease_expires_at),
            )
            return reservation

    def complete_turn(self, reservation: TurnReservation, user_text: str, response: ChatResponse) -> None:
        # Force validation through a fresh DTO even if an existing DTO was mutated.
        _validate_reservation(reservation)
        request = ChatRequest(session_id=reservation.session_id, client_turn_id=reservation.client_turn_id, text=user_text)
        payload = response.model_dump(mode="python") if isinstance(response, ChatResponse) else response
        validated = ChatResponse.model_validate(payload)
        if validated.session_id != reservation.session_id or validated.client_turn_id != reservation.client_turn_id:
            raise ValueError("response IDs must match the reserved turn")
        user_message = Message(role="user", content=request.text)
        assistant_message = Message(role="assistant", content=validated.reply)
        response_json = validated.model_dump_json()
        with self._transaction(write=True):
            self._session(reservation.user_id, reservation.session_id)
            turn = self._conn.execute(
                "SELECT status, token, lease_expires_at FROM turns WHERE session_id = ? AND client_turn_id = ?",
                (reservation.session_id, reservation.client_turn_id),
            ).fetchone()
            if turn is None or turn["token"] != reservation.token or turn["lease_expires_at"] != reservation.lease_expires_at:
                raise StaleReservation()
            if turn["status"] == "completed":
                # A duplicate success cannot alter the previously saved response.
                return
            now = self._now()
            if turn["lease_expires_at"] <= now:
                raise StaleReservation()
            timestamp = _timestamp(now)
            self._conn.executemany(
                "INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                ((reservation.session_id, user_message.role, user_message.content, timestamp),
                 (reservation.session_id, assistant_message.role, assistant_message.content, timestamp)),
            )
            cursor = self._conn.execute(
                """UPDATE turns SET status = 'completed', response_json = ?
                   WHERE session_id = ? AND client_turn_id = ? AND token = ? AND status = 'pending'""",
                (response_json, reservation.session_id, reservation.client_turn_id, reservation.token),
            )
            if cursor.rowcount != 1:
                raise StaleReservation()

    def abort_turn(self, reservation: TurnReservation) -> None:
        _validate_reservation(reservation)
        with self._transaction(write=True):
            self._session(reservation.user_id, reservation.session_id)
            self._conn.execute(
                """DELETE FROM turns WHERE session_id = ? AND client_turn_id = ?
                   AND token = ? AND status = 'pending'""",
                (reservation.session_id, reservation.client_turn_id, reservation.token),
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._conn.close()
            except sqlite3.Error as error:
                raise _storage_exception(error) from error
            self._closed = True


class InMemoryStore(SQLiteStore):
    """One isolated SQLite :memory: database per instance, with the same contract."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        lease_seconds: float = 300.0,
        timeout: float = 5.0,
    ) -> None:
        super().__init__(":memory:", clock=clock, lease_seconds=lease_seconds, timeout=timeout)
