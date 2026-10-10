"""B2 storage checks use explicit mock fixtures, never model inference."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import sqlite3
from threading import Barrier

import pytest

from b2_core.contracts import ChatResponse, MemoryItem
from b2_core.store import (
    InMemoryStore,
    ResourceNotFound,
    SQLiteStore,
    StoreError,
    StaleReservation,
    TurnInProgress,
    TurnReservation,
)


class ControlledClock:
    def __init__(self):
        self.now = 1_760_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    clock = ControlledClock()
    if request.param == "memory":
        instance = InMemoryStore(clock=clock, lease_seconds=10)
    else:
        instance = SQLiteStore(tmp_path / "store.sqlite3", clock=clock, lease_seconds=10)
    yield instance, clock
    instance.close()


def owner_and_session(store, title="虚构会话"):
    identity = store.resolve_user(None)
    return identity, store.create_session(identity.user_id, title)


def mock_response(session_id, turn_id, reply="【演示数据】固定测试回复"):
    return ChatResponse(
        session_id=session_id,
        client_turn_id=turn_id,
        reply=reply,
        emotion="unknown",
        expression="listening",
        retrieved_memories=[MemoryItem(
            id="fixture-memory", key="hobby", value="围棋",
            updated_at="2026-10-10T00:00:00Z",
        )],
        model_version="unit-only-mock",
        elapsed_ms=0,
        is_mock=True,
    )


def test_opaque_identity_unknown_token_cannot_select_user(store):
    instance, _ = store
    first = instance.resolve_user(None)
    assert first.cookie_token and first.cookie_token != first.user_id
    reused = instance.resolve_user(first.cookie_token)
    assert reused.user_id == first.user_id
    assert reused.cookie_token is None
    unknown = instance.resolve_user("forged-token")
    supplied_user_id = instance.resolve_user(first.user_id)
    assert len({first.user_id, unknown.user_id, supplied_user_id.user_id}) == 3
    assert unknown.cookie_token != "forged-token"
    assert supplied_user_id.cookie_token != first.user_id


def test_sessions_and_messages_check_ownership(store):
    instance, _ = store
    alice, session = owner_and_session(instance)
    bob, bob_session = owner_and_session(instance, "另一个虚构会话")
    assert [s.id for s in instance.list_sessions(alice.user_id)] == [session.id]
    assert [s.id for s in instance.list_sessions(bob.user_id)] == [bob_session.id]
    assert instance.get_messages(alice.user_id, session.id) == []
    for session_id in (session.id, "nonexistent-session"):
        with pytest.raises(ResourceNotFound):
            instance.get_messages(bob.user_id, session_id)
        with pytest.raises(ResourceNotFound):
            instance.delete_session(bob.user_id, session_id)
        with pytest.raises(ResourceNotFound):
            instance.reserve_turn(bob.user_id, session_id, "turn-1")
    assert [s.id for s in instance.list_sessions(alice.user_id)] == [session.id]


def test_pending_is_per_session_and_engine_failure_leaves_no_half_pair(store):
    instance, _ = store
    owner, session = owner_and_session(instance)
    other = instance.create_session(owner.user_id, "不同会话")
    reservation = instance.reserve_turn(owner.user_id, session.id, "turn-1")
    with pytest.raises(TurnInProgress):
        instance.reserve_turn(owner.user_id, session.id, "turn-1")
    with pytest.raises(TurnInProgress):
        instance.reserve_turn(owner.user_id, session.id, "turn-2")
    unrelated = instance.reserve_turn(owner.user_id, other.id, "turn-1")
    assert isinstance(unrelated, TurnReservation)
    try:
        raise RuntimeError("fixture-only engine failure")
    except RuntimeError:
        instance.abort_turn(reservation)
    assert instance.get_messages(owner.user_id, session.id) == []
    retry = instance.reserve_turn(owner.user_id, session.id, "turn-1")
    assert isinstance(retry, TurnReservation)
    assert retry.token != reservation.token
    instance.abort_turn(retry)
    instance.abort_turn(unrelated)


def test_completed_retry_returns_original_response_and_text_does_not_deduplicate(store):
    instance, _ = store
    owner, session = owner_and_session(instance)
    reservation = instance.reserve_turn(owner.user_id, session.id, "turn-1")
    response = mock_response(session.id, "turn-1")
    instance.complete_turn(reservation, "同一段虚构输入", response)
    assert instance.reserve_turn(owner.user_id, session.id, "turn-1") == response
    instance.complete_turn(reservation, "同一段虚构输入", response)
    assert [(m.role, m.content) for m in instance.get_messages(owner.user_id, session.id)] == [
        ("user", "同一段虚构输入"), ("assistant", response.reply),
    ]
    next_reservation = instance.reserve_turn(owner.user_id, session.id, "turn-2")
    instance.complete_turn(next_reservation, "同一段虚构输入", mock_response(session.id, "turn-2"))
    assert [m.role for m in instance.get_messages(owner.user_id, session.id)] == [
        "user", "assistant", "user", "assistant",
    ]


@pytest.mark.parametrize("invalid", ["session", "turn", "blank-user", "long-user", "blank-reply", "nonbool-mock"])
def test_invalid_complete_is_atomic_and_pending_can_be_completed_afterward(store, invalid):
    instance, _ = store
    owner, session = owner_and_session(instance)
    reservation = instance.reserve_turn(owner.user_id, session.id, "turn-1")
    response = mock_response(session.id, "turn-1")
    text = "虚构输入"
    if invalid == "session":
        response.session_id = "different-session"
    elif invalid == "turn":
        response.client_turn_id = "different-turn"
    elif invalid == "blank-user":
        text = " \t"
    elif invalid == "long-user":
        text = "字" * 2001
    elif invalid == "blank-reply":
        response.reply = "  "
    elif invalid == "nonbool-mock":
        response.is_mock = 1
    with pytest.raises(ValueError):
        instance.complete_turn(reservation, text, response)
    assert instance.get_messages(owner.user_id, session.id) == []
    valid = mock_response(session.id, "turn-1")
    instance.complete_turn(reservation, "虚构输入", valid)
    assert instance.reserve_turn(owner.user_id, session.id, "turn-1") == valid
    assert len(instance.get_messages(owner.user_id, session.id)) == 2


def test_forged_and_expired_reservation_cannot_commit_or_release_new_pending(store):
    instance, clock = store
    owner, session = owner_and_session(instance)
    original = instance.reserve_turn(owner.user_id, session.id, "turn-1")
    with pytest.raises(StaleReservation):
        instance.complete_turn(replace(original, token="forged-token"), "虚构输入", mock_response(session.id, "turn-1"))
    clock.now += 11
    with pytest.raises(StaleReservation):
        instance.complete_turn(original, "过期虚构输入", mock_response(session.id, "turn-1"))
    replacement = instance.reserve_turn(owner.user_id, session.id, "turn-1")
    assert replacement.token != original.token
    instance.abort_turn(original)
    with pytest.raises(TurnInProgress):
        instance.reserve_turn(owner.user_id, session.id, "turn-2")
    with pytest.raises(StaleReservation):
        instance.complete_turn(original, "过期虚构输入", mock_response(session.id, "turn-1"))
    assert instance.get_messages(owner.user_id, session.id) == []
    instance.complete_turn(replacement, "新虚构输入", mock_response(session.id, "turn-1"))
    assert instance.get_messages(owner.user_id, session.id)[0].content == "新虚构输入"


def test_delete_active_pending_conflicts_then_completed_session_is_removed(store):
    instance, _ = store
    owner, session = owner_and_session(instance)
    reservation = instance.reserve_turn(owner.user_id, session.id, "turn-1")
    with pytest.raises(TurnInProgress):
        instance.delete_session(owner.user_id, session.id)
    instance.complete_turn(reservation, "虚构输入", mock_response(session.id, "turn-1"))
    instance.delete_session(owner.user_id, session.id)
    assert instance.list_sessions(owner.user_id) == []
    with pytest.raises(ResourceNotFound):
        instance.get_messages(owner.user_id, session.id)
    with pytest.raises(ResourceNotFound):
        instance.reserve_turn(owner.user_id, session.id, "turn-1")


def test_expired_pending_does_not_prevent_session_delete(store):
    instance, clock = store
    owner, session = owner_and_session(instance)
    instance.reserve_turn(owner.user_id, session.id, "turn-1")
    clock.now += 11
    instance.delete_session(owner.user_id, session.id)
    assert instance.list_sessions(owner.user_id) == []


def test_returned_dto_mutation_does_not_change_stored_objects(store):
    instance, _ = store
    owner, session = owner_and_session(instance)
    original_title = session.title
    session.title = "客户端篡改"
    listed = instance.list_sessions(owner.user_id)
    assert listed[0].title == original_title
    listed[0].title = "再次篡改"
    assert instance.list_sessions(owner.user_id)[0].title == original_title
    reservation = instance.reserve_turn(owner.user_id, session.id, "turn-1")
    response = mock_response(session.id, "turn-1")
    instance.complete_turn(reservation, "原始虚构输入", response)
    response.reply = "篡改原对象"
    response.retrieved_memories[0].value = "篡改引用"
    retrieved = instance.reserve_turn(owner.user_id, session.id, "turn-1")
    assert retrieved.reply == "【演示数据】固定测试回复"
    assert retrieved.retrieved_memories[0].value == "围棋"
    retrieved.retrieved_memories[0].value = "篡改读取副本"
    assert instance.reserve_turn(owner.user_id, session.id, "turn-1").retrieved_memories[0].value == "围棋"
    messages = instance.get_messages(owner.user_id, session.id)
    messages[0].content = "篡改历史副本"
    assert instance.get_messages(owner.user_id, session.id)[0].content == "原始虚构输入"


def test_sqlite_reopen_keeps_identity_completed_response_and_message_pair(tmp_path):
    path = tmp_path / "persistent.sqlite3"
    instance = SQLiteStore(path)
    owner, session = owner_and_session(instance)
    reservation = instance.reserve_turn(owner.user_id, session.id, "turn-1")
    response = mock_response(session.id, "turn-1")
    instance.complete_turn(reservation, "虚构持久化输入", response)
    instance.close()
    reopened = SQLiteStore(path)
    try:
        assert reopened.resolve_user(owner.cookie_token).user_id == owner.user_id
        assert reopened.list_sessions(owner.user_id)[0].id == session.id
        assert reopened.reserve_turn(owner.user_id, session.id, "turn-1") == response
        assert len(reopened.get_messages(owner.user_id, session.id)) == 2
    finally:
        reopened.close()


def test_two_sqlite_instances_competing_for_same_session_have_one_winner(tmp_path):
    path = tmp_path / "competing.sqlite3"
    first, second = SQLiteStore(path), SQLiteStore(path)
    owner, session = owner_and_session(first)
    barrier = Barrier(2)

    def attempt(instance, turn_id):
        barrier.wait(timeout=5)
        try:
            return instance.reserve_turn(owner.user_id, session.id, turn_id)
        except TurnInProgress:
            return "conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(attempt, first, "turn-a")
            b = pool.submit(attempt, second, "turn-b")
            results = [a.result(timeout=10), b.result(timeout=10)]
        assert sum(isinstance(item, TurnReservation) for item in results) == 1
        assert results.count("conflict") == 1
        assert first.get_messages(owner.user_id, session.id) == []
    finally:
        first.close()
        second.close()


def test_sqlite_persists_cookie_hash_and_rolls_back_a_database_write_failure(tmp_path):
    path = tmp_path / "atomic.sqlite3"
    instance = SQLiteStore(path)
    owner, session = owner_and_session(instance)
    reservation = instance.reserve_turn(owner.user_id, session.id, "turn-1")
    try:
        with sqlite3.connect(path) as observer:
            stored_hash = observer.execute("SELECT token_sha256 FROM users WHERE id = ?", (owner.user_id,)).fetchone()[0]
            assert stored_hash == hashlib.sha256(owner.cookie_token.encode("utf-8")).hexdigest()
            assert stored_hash != owner.cookie_token
            # An actual SQLite failure on the second message must roll back
            # the first message too, without fabricating a successful turn.
            observer.execute("""CREATE TRIGGER fixture_fail_assistant
                BEFORE INSERT ON messages WHEN NEW.role = 'assistant'
                BEGIN SELECT RAISE(ABORT, 'fixture-only write failure'); END""")
        with pytest.raises(StoreError):
            instance.complete_turn(reservation, "虚构输入", mock_response(session.id, "turn-1"))
        assert instance.get_messages(owner.user_id, session.id) == []
        with sqlite3.connect(path) as observer:
            assert observer.execute("SELECT status FROM turns").fetchone()[0] == "pending"
            observer.execute("DROP TRIGGER fixture_fail_assistant")
        instance.complete_turn(reservation, "虚构输入", mock_response(session.id, "turn-1"))
        instance.delete_session(owner.user_id, session.id)
        with sqlite3.connect(path) as observer:
            assert observer.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
            assert observer.execute("SELECT count(*) FROM turns").fetchone()[0] == 0
            assert observer.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
            assert observer.execute("SELECT count(*) FROM users").fetchone()[0] == 1
    finally:
        instance.close()
