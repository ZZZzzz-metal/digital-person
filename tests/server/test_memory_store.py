"""B3 user-confirmed facts; no automatic extraction or model calls."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
from threading import Barrier

import pytest

from b2_core.contracts import ChatResponse
from b2_core.store import InMemoryStore, MemoryDisabled, ResourceNotFound, SQLiteStore


class ControlledClock:
    now = 1_760_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture(params=["memory", "sqlite"])
def memory_store(request, tmp_path):
    clock = ControlledClock()
    instance = InMemoryStore(clock=clock) if request.param == "memory" else SQLiteStore(tmp_path / "memory.sqlite3", clock=clock)
    user_id = instance.resolve_user(None).user_id
    yield instance, user_id, clock
    instance.close()


def test_correction_replaces_value_with_stable_id_and_returns_independent_dtos(memory_store):
    instance, user_id, clock = memory_store
    assert instance.list_memories(user_id).model_dump() == {"enabled": True, "items": []}
    original = instance.save_memory(user_id, "exam_subject", "  高数 \n")
    assert original.value == "高数"
    clock.now += 1
    corrected = instance.save_memory(user_id, "exam_subject", "线代")
    assert corrected.id == original.id
    assert corrected.updated_at > original.updated_at
    assert instance.list_memories(user_id).items == [corrected]
    original.value = "篡改旧副本"
    corrected.value = "篡改新副本"
    listed = instance.list_memories(user_id)
    assert listed.items[0].value == "线代"
    listed.items[0].value = "篡改读取副本"
    listed.enabled = False
    assert instance.list_memories(user_id).enabled is True
    assert instance.list_memories(user_id).items[0].value == "线代"


def test_memory_belongs_to_user_across_sessions_and_survives_session_delete(memory_store):
    instance, user_id, _ = memory_store
    first = instance.create_session(user_id, "虚构第一会话")
    second = instance.create_session(user_id, "虚构第二会话")
    saved = instance.save_memory(user_id, "preferred_name", "小宁")
    instance.delete_session(user_id, first.id)
    assert instance.list_memories(user_id).items == [saved]
    assert [s.id for s in instance.list_sessions(user_id)] == [second.id]
    assert instance.get_messages(user_id, second.id) == []


def test_disabling_hides_and_blocks_save_without_erasing_facts(memory_store):
    instance, user_id, _ = memory_store
    saved = instance.save_memory(user_id, "exam_subject", "高数")
    assert instance.set_memory_enabled(user_id, False).model_dump() == {"enabled": False, "items": []}
    assert instance.list_memories(user_id).model_dump() == {"enabled": False, "items": []}
    with pytest.raises(MemoryDisabled):
        instance.save_memory(user_id, "exam_subject", "线代")
    with pytest.raises(MemoryDisabled):
        instance.save_memory(user_id, "hobby", "围棋")
    restored = instance.set_memory_enabled(user_id, True)
    assert restored.enabled is True and restored.items == [saved]


def test_explicit_delete_and_clear_work_while_disabled_without_changing_switch(memory_store):
    instance, user_id, _ = memory_store
    first = instance.save_memory(user_id, "exam_subject", "线代")
    instance.save_memory(user_id, "hobby", "围棋")
    instance.set_memory_enabled(user_id, False)
    instance.delete_memory(user_id, first.id)
    assert instance.list_memories(user_id).enabled is False
    assert [m.key for m in instance.set_memory_enabled(user_id, True).items] == ["hobby"]
    instance.set_memory_enabled(user_id, False)
    instance.clear_memories(user_id)
    assert instance.list_memories(user_id).model_dump() == {"enabled": False, "items": []}
    assert instance.set_memory_enabled(user_id, True).items == []


def test_user_isolation_foreign_delete_and_clear(memory_store):
    instance, alice, _ = memory_store
    bob = instance.resolve_user(None).user_id
    a = instance.save_memory(alice, "exam_subject", "高数")
    b = instance.save_memory(bob, "exam_subject", "线代")
    assert instance.list_memories(alice).items == [a]
    assert instance.list_memories(bob).items == [b]
    for memory_id in (a.id, "nonexistent-memory"):
        with pytest.raises(ResourceNotFound):
            instance.delete_memory(bob, memory_id)
    instance.clear_memories(alice)
    assert instance.list_memories(alice).items == []
    assert instance.list_memories(bob).items == [b]
    with pytest.raises(ResourceNotFound):
        instance.clear_memories("nonexistent-user")


@pytest.mark.parametrize("key,value", [
    ("diagnosis", "不允许的字段"), ("emotion", "anxious"),
    ("hobby", "  \n"), ("hobby", "字" * 201),
    ("hobby", 12), ("hobby", True), ("hobby", ["围棋"]),
])
def test_memory_validation_does_not_partially_write(memory_store, key, value):
    instance, user_id, _ = memory_store
    saved = instance.save_memory(user_id, "exam_subject", "线代")
    with pytest.raises(ValueError):
        instance.save_memory(user_id, key, value)
    assert instance.list_memories(user_id).items == [saved]


@pytest.mark.parametrize("enabled", [0, 1, "true", None])
def test_memory_switch_requires_strict_boolean(memory_store, enabled):
    instance, user_id, _ = memory_store
    with pytest.raises(ValueError):
        instance.set_memory_enabled(user_id, enabled)
    assert instance.list_memories(user_id).enabled is True


def test_trimmed_length_boundary_and_delete_then_save_creates_new_id(memory_store):
    instance, user_id, _ = memory_store
    first = instance.save_memory(user_id, "hobby", "  " + "字" * 200 + "  ")
    assert first.value == "字" * 200
    instance.delete_memory(user_id, first.id)
    recreated = instance.save_memory(user_id, "hobby", "围棋")
    assert recreated.id != first.id
    assert instance.list_memories(user_id).items == [recreated]


def test_sqlite_reopen_preserves_corrected_fact_and_disabled_switch(tmp_path):
    path = tmp_path / "reopen.sqlite3"
    first = SQLiteStore(path)
    owner = first.resolve_user(None)
    old = first.save_memory(owner.user_id, "exam_subject", "高数")
    corrected = first.save_memory(owner.user_id, "exam_subject", "线代")
    first.set_memory_enabled(owner.user_id, False)
    first.close()
    reopened = SQLiteStore(path)
    try:
        assert reopened.resolve_user(owner.cookie_token).user_id == owner.user_id
        assert reopened.list_memories(owner.user_id).model_dump() == {"enabled": False, "items": []}
        restored = reopened.set_memory_enabled(owner.user_id, True)
        assert restored.items == [corrected] and corrected.id == old.id
    finally:
        reopened.close()


def test_existing_b2_database_adds_memory_table_without_resetting_existing_data(tmp_path):
    path = tmp_path / "legacy-b2.sqlite3"
    first = SQLiteStore(path)
    owner = first.resolve_user(None)
    session = first.create_session(owner.user_id, "旧B2虚构会话")
    reservation = first.reserve_turn(owner.user_id, session.id, "legacy-turn")
    response = ChatResponse(
        session_id=session.id, client_turn_id="legacy-turn", reply="【演示数据】旧B2测试回复",
        emotion="unknown", expression="listening", retrieved_memories=[],
        model_version="unit-only-mock", elapsed_ms=0, is_mock=True,
    )
    first.complete_turn(reservation, "旧B2虚构输入", response)
    first.set_memory_enabled(owner.user_id, False)
    first.close()
    # B2 already has the memory_enabled column, but has no memories table.
    # Remove only the new empty table to model that exact older layout.
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT count(*) FROM memories").fetchone()[0] == 0
        connection.execute("DROP TABLE memories")
        connection.commit()
    migrated = SQLiteStore(path)
    try:
        assert migrated.resolve_user(owner.cookie_token).user_id == owner.user_id
        assert migrated.list_sessions(owner.user_id)[0] == session
        assert len(migrated.get_messages(owner.user_id, session.id)) == 2
        assert migrated.reserve_turn(owner.user_id, session.id, "legacy-turn") == response
        assert migrated.list_memories(owner.user_id).enabled is False
        migrated.set_memory_enabled(owner.user_id, True)
        saved = migrated.save_memory(owner.user_id, "exam_subject", "线代")
        assert migrated.list_memories(owner.user_id).items == [saved]
    finally:
        migrated.close()


def test_two_sqlite_instances_saving_same_key_keep_one_stable_record(tmp_path):
    path = tmp_path / "competing-memories.sqlite3"
    first, second = SQLiteStore(path), SQLiteStore(path)
    user_id = first.resolve_user(None).user_id
    barrier = Barrier(2)

    def save(instance, value):
        barrier.wait(timeout=5)
        return instance.save_memory(user_id, "exam_subject", value)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(save, first, "高数")
            b = pool.submit(save, second, "线代")
            results = [a.result(timeout=10), b.result(timeout=10)]
        assert results[0].id == results[1].id
        items = first.list_memories(user_id).items
        assert len(items) == 1 and items[0].value in {"高数", "线代"}
        with closing(sqlite3.connect(path)) as observer:
            assert observer.execute("SELECT count(*) FROM memories WHERE user_id=? AND key=?", (user_id, "exam_subject")).fetchone()[0] == 1
    finally:
        first.close()
        second.close()


def test_disabled_sqlite_operations_do_not_read_memory_table(tmp_path):
    instance = SQLiteStore(tmp_path / "disabled-no-read.sqlite3")
    user_id = instance.resolve_user(None).user_id
    saved = instance.save_memory(user_id, "exam_subject", "高数")
    instance.set_memory_enabled(user_id, False)
    attempted_reads = []

    def deny_memory_reads(action, table, column, database, source):
        if action == sqlite3.SQLITE_READ and table == "memories":
            attempted_reads.append((table, column))
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    try:
        instance._conn.set_authorizer(deny_memory_reads)
        assert instance.list_memories(user_id).model_dump() == {"enabled": False, "items": []}
        assert instance.set_memory_enabled(user_id, False).model_dump() == {"enabled": False, "items": []}
        with pytest.raises(MemoryDisabled):
            instance.save_memory(user_id, "exam_subject", "线代")
        assert attempted_reads == []
        instance._conn.set_authorizer(None)
        assert instance.set_memory_enabled(user_id, True).items == [saved]
    finally:
        instance._conn.set_authorizer(None)
        instance.close()
