"""B4 demo orchestration fixtures; these are not real model/GPU results."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import asyncio
import sys
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from b2_core.contracts import ChatRequest, ChatResponse, CoreReply, Health
from b2_core.store import InMemoryStore, SQLiteStore, TurnReservation
from server.app import create_app
from server.chat import ChatError, InferenceWorker, chat


class RecordingEngine:
    is_mock = True
    model_version = "unit-only-recording-mock"

    def __init__(self, reply_text=None):
        self.requests = []
        self.failure = None
        self.reply_text = reply_text
        self.lock = Lock()

    def generate(self, request):
        with self.lock:
            self.requests.append(request.model_copy(deep=True))
            number = len(self.requests)
        if self.failure == "exception":
            raise RuntimeError("fixture-only generation failure")
        if self.failure == "model-timeout":
            raise TimeoutError("fixture-only model-raised timeout")
        if self.failure == "public-error":
            raise ChatError("MODEL_TIMEOUT", request.messages[-1].content)
        result = CoreReply(
            reply=self.reply_text or f"【演示数据】测试回复-{number}",
            model_version=self.model_version, is_mock=True,
        )
        if self.failure == "blank":
            result.reply = "  "
        return result


class BlockingEngine(RecordingEngine):
    def __init__(self, block_on_call=1):
        super().__init__()
        self.entered = Event()
        self.release = Event()
        self.block_on_call = block_on_call

    def generate(self, request):
        with self.lock:
            number = len(self.requests) + 1
        if number == self.block_on_call:
            self.entered.set()
            if not self.release.wait(timeout=5):
                raise RuntimeError("fixture-only blocking deadline")
        return super().generate(request)


@pytest.fixture(params=["memory", "sqlite"])
def chat_storage(request, tmp_path, monkeypatch):
    monkeypatch.setenv("B2_COOKIE_SECURE", "0")
    instance = InMemoryStore() if request.param == "memory" else SQLiteStore(tmp_path / "chat.sqlite3")
    yield instance
    instance.close()


def session(client):
    response = client.post("/api/sessions", json={})
    assert response.status_code == 200
    return response.json()["id"]


def send(client, session_id, turn_id, text="虚构输入"):
    return client.post("/api/chat", json={"session_id": session_id, "client_turn_id": turn_id, "text": text})


def assert_error(response, status, code):
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) == {"code", "message"}


def test_eight_turns_have_completed_pairs_and_current_input_once(chat_storage):
    engine = RecordingEngine()
    with TestClient(create_app(mode="stub", store=chat_storage, engine=engine)) as client:
        session_id = session(client)
        replies = []
        for index in range(8):
            text = f"虚构当前输入-{index}"
            response = send(client, session_id, f"turn-{index}", text)
            assert response.status_code == 200
            dto = ChatResponse.model_validate(response.json())
            assert dto.is_mock is True and dto.model_version == engine.model_version
            assert dto.elapsed_ms >= 0
            replies.append(dto.reply)
            received = engine.requests[-1]
            first_index = max(0, index - 6)
            expected = [
                value for prior in range(first_index, index)
                for value in [("user", f"虚构当前输入-{prior}"), ("assistant", replies[prior])]
            ] + [("user", text)]
            assert [(message.role, message.content) for message in received.messages] == expected
            assert len(received.messages) <= 13
            assert sum(message.content == text for message in received.messages) == 1
        assert len(engine.requests) == 8
        assert len(client.get(f"/api/sessions/{session_id}/messages").json()) == 16


def test_api_history_character_limit_keeps_whole_pairs_and_current_untruncated(chat_storage):
    engine = RecordingEngine(reply_text="【演示数据】" + "回" * 1994)
    with TestClient(create_app(mode="stub", store=chat_storage, engine=engine)) as client:
        session_id = session(client)
        for index in range(3):
            text = "问" * 1999 + str(index)
            assert send(client, session_id, f"turn-{index}", text).status_code == 200
            received = engine.requests[-1]
            assert received.messages[-1].content == text and len(text) == 2000
            assert sum(len(message.content) for message in received.messages[:-1]) <= 4000
            assert len(received.messages) == (1 if index == 0 else 3)
            if index:
                assert received.messages[0].content == "问" * 1999 + str(index - 1)
            assert [message.role for message in received.messages[:-1]] == (["user", "assistant"] if index else [])


def test_successful_retry_returns_exact_cached_response_and_same_text_new_turn_is_new(chat_storage):
    engine = RecordingEngine()
    application = create_app(mode="stub", store=chat_storage, engine=engine)
    with TestClient(application) as client:
        session_id = session(client)
        original = send(client, session_id, "turn-1", "相同虚构文本")
        assert original.status_code == 200
        repeated = send(client, session_id, "turn-1", "更改文本也不能覆盖已经成功的轮次")
        assert repeated.json() == original.json()
        assert len(engine.requests) == 1
        assert len(client.get(f"/api/sessions/{session_id}/messages").json()) == 2
        assert send(client, session_id, "turn-2", "相同虚构文本").status_code == 200
        assert len(engine.requests) == 2
        assert len(client.get(f"/api/sessions/{session_id}/messages").json()) == 4
        application.state.engine = None
        assert send(client, session_id, "turn-1").json() == original.json()
        assert len(engine.requests) == 2


def test_memory_correction_cross_session_disable_and_two_cookie_isolation(chat_storage):
    engine = RecordingEngine()
    application = create_app(mode="stub", store=chat_storage, engine=engine)
    with ExitStack() as stack:
        alice = stack.enter_context(TestClient(application))
        bob = stack.enter_context(TestClient(application))
        a_session, b_session = session(alice), session(bob)
        alice.put("/api/memories/exam_subject", json={"value": "高数"})
        first = send(alice, a_session, "turn-1", "我担心考试")
        assert first.status_code == 200
        assert [m["value"] for m in first.json()["retrieved_memories"]] == ["高数"]
        assert "高数" in engine.requests[-1].memory_context
        alice.put("/api/memories/exam_subject", json={"value": "线代"})
        a_new_session = session(alice)
        corrected = send(alice, a_new_session, "turn-1", "你还记得我担心哪门考试吗")
        assert [m["value"] for m in corrected.json()["retrieved_memories"]] == ["线代"]
        assert "线代" in engine.requests[-1].memory_context and "高数" not in engine.requests[-1].memory_context
        assert len(engine.requests[-1].messages) == 1
        bob.put("/api/memories/exam_subject", json={"value": "英语"})
        bob_reply = send(bob, b_session, "turn-1", "我担心考试")
        assert [m["value"] for m in bob_reply.json()["retrieved_memories"]] == ["英语"]
        assert "线代" not in engine.requests[-1].memory_context and len(engine.requests[-1].messages) == 1
        calls = len(engine.requests)
        assert_error(send(bob, a_session, "turn-1"), 404, "NOT_FOUND")
        assert len(engine.requests) == calls
        alice.put("/api/memories/settings", json={"enabled": False})
        disabled = send(alice, a_new_session, "turn-2", "我还担心考试")
        assert disabled.status_code == 200 and disabled.json()["retrieved_memories"] == []
        assert engine.requests[-1].memory_context == ""


@pytest.mark.parametrize("failure", ["exception", "blank", "model-timeout", "public-error"])
def test_model_failure_returns_503_without_half_messages_and_same_turn_can_retry(chat_storage, failure):
    engine = RecordingEngine()
    engine.failure = failure
    with TestClient(create_app(mode="stub", store=chat_storage, engine=engine)) as client:
        session_id = session(client)
        failed = send(client, session_id, "turn-1", "虚构输入不应出现在错误中")
        assert_error(failed, 503, "MODEL_UNAVAILABLE")
        assert failed.json()["error"]["message"] == "模型暂不可用"
        assert client.get(f"/api/sessions/{session_id}/messages").json() == []
        engine.failure = None
        retry = send(client, session_id, "turn-1")
        assert retry.status_code == 200 and retry.json()["is_mock"] is True
        assert len(engine.requests) == 2
        assert len(client.get(f"/api/sessions/{session_id}/messages").json()) == 2


@pytest.mark.parametrize("payload", [{}, {"session_id": "s", "client_turn_id": "t", "text": " "}, {"session_id": "s", "client_turn_id": "t", "text": "字" * 2001}, {"session_id": "s", "client_turn_id": "t", "text": True}, {"session_id": "s", "client_turn_id": "t", "text": "ok", "user_id": "forged"}])
def test_chat_invalid_input_uses_contract_400(chat_storage, payload):
    engine = RecordingEngine()
    with TestClient(create_app(mode="stub", store=chat_storage, engine=engine)) as client:
        assert_error(client.post("/api/chat", json=payload), 400, "INVALID_REQUEST")
        assert engine.requests == []


def test_real_unavailable_does_not_generate_a_stub_reply(chat_storage, monkeypatch):
    monkeypatch.setitem(sys.modules, "b2_core.model", None)
    with TestClient(create_app(mode="real", store=chat_storage)) as client:
        session_id = session(client)
        assert client.get("/health").json()["is_mock"] is False
        assert_error(send(client, session_id, "turn-1"), 503, "MODEL_UNAVAILABLE")
        assert client.get(f"/api/sessions/{session_id}/messages").json() == []


def test_timeout_returns_before_release_keeps_engine_gate_and_discards_late_reply(chat_storage):
    engine = BlockingEngine()
    application = create_app(mode="stub", store=chat_storage, engine=engine, chat_timeout_seconds=0.15)
    with TestClient(application) as client, ThreadPoolExecutor(max_workers=1) as caller:
        first_session, other_session = session(client), session(client)
        future = caller.submit(send, client, first_session, "turn-1")
        try:
            assert engine.entered.wait(timeout=3)
            assert_error(future.result(timeout=3), 503, "MODEL_TIMEOUT")
            assert not engine.release.is_set()
            assert application.state.inference_gate.locked()
            assert client.get(f"/api/sessions/{first_session}/messages").json() == []
            assert_error(send(client, other_session, "turn-1"), 503, "MODEL_BUSY")
            assert_error(send(client, first_session, "turn-1"), 503, "MODEL_BUSY")
            engine.release.set()
            assert application.state.inference_gate.acquire(timeout=3)
            application.state.inference_gate.release()
            assert client.get(f"/api/sessions/{first_session}/messages").json() == []
            assert send(client, first_session, "turn-1").status_code == 200
            assert send(client, other_session, "turn-1").status_code == 200
            assert len(client.get(f"/api/sessions/{first_session}/messages").json()) == 2
        finally:
            engine.release.set()


def test_active_session_409_other_session_busy_and_completed_cache_bypasses_busy_engine(chat_storage):
    engine = BlockingEngine(block_on_call=2)
    application = create_app(mode="stub", store=chat_storage, engine=engine, chat_timeout_seconds=3)
    with TestClient(application) as client, ThreadPoolExecutor(max_workers=1) as caller:
        first_session, other_session = session(client), session(client)
        cached = send(client, first_session, "completed-turn")
        assert cached.status_code == 200
        future = caller.submit(send, client, first_session, "pending-turn")
        try:
            assert engine.entered.wait(timeout=3)
            assert_error(send(client, first_session, "pending-turn"), 409, "TURN_IN_PROGRESS")
            assert_error(send(client, first_session, "different-turn"), 409, "TURN_IN_PROGRESS")
            assert_error(send(client, other_session, "other-turn"), 503, "MODEL_BUSY")
            assert send(client, first_session, "completed-turn", "ignored replacement").json() == cached.json()
            engine.release.set()
            assert future.result(timeout=3).status_code == 200
            assert send(client, other_session, "other-turn").status_code == 200
            assert len(engine.requests) == 3
        finally:
            engine.release.set()


def test_sqlite_restart_returns_original_response_without_reinitializing_generation(tmp_path):
    path = tmp_path / "cached-chat.sqlite3"
    first_engine = RecordingEngine()
    with TestClient(create_app(mode="stub", db_path=path, engine=first_engine)) as client:
        session_id = session(client)
        original = send(client, session_id, "persisted-turn")
        token = client.cookies.get("b2_anon")
        assert original.status_code == 200
    second_engine = RecordingEngine()
    with TestClient(create_app(mode="stub", db_path=path, engine=second_engine)) as client:
        client.cookies.set("b2_anon", token)
        repeated = send(client, session_id, "persisted-turn", "replacement ignored")
        assert repeated.json() == original.json()
        assert second_engine.requests == []
        assert len(client.get(f"/api/sessions/{session_id}/messages").json()) == 2


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), 241, True])
def test_timeout_configuration_rejects_invalid_values(timeout):
    with pytest.raises(ValueError):
        create_app(chat_timeout_seconds=timeout)


@pytest.mark.parametrize("timeout", ["invalid", "inf", "0", "241"])
def test_invalid_timeout_environment_is_not_silently_replaced(monkeypatch, timeout):
    monkeypatch.setenv("B2_CHAT_TIMEOUT_SECONDS", timeout)
    with pytest.raises(ValueError):
        create_app()


def test_model_factory_initializes_once_across_multiple_chat_requests(chat_storage):
    calls = []
    engine = RecordingEngine()

    def factory():
        calls.append("initialize")
        return engine

    application = create_app(mode="stub", store=chat_storage, engine_factory=factory)
    assert calls == []
    with TestClient(application) as client:
        session_id = session(client)
        for index in range(2):
            assert send(client, session_id, f"turn-{index}").status_code == 200
        assert client.get("/health").json()["model_ready"] is True
    assert calls == ["initialize"] and len(engine.requests) == 2


def test_reused_lifespan_keeps_gate_while_old_timed_out_worker_is_still_running(chat_storage):
    engine = BlockingEngine()
    initialized = []

    def factory():
        initialized.append("initialize")
        return engine

    application = create_app(
        mode="stub", store=chat_storage, engine_factory=factory,
        chat_timeout_seconds=0.15,
    )
    try:
        with TestClient(application) as first:
            session_id = session(first)
            token = first.cookies.get("b2_anon")
            original_worker = application.state.inference_worker
            assert_error(send(first, session_id, "turn-1"), 503, "MODEL_TIMEOUT")
            assert engine.entered.is_set() and not engine.release.is_set()
            assert application.state.inference_gate.locked()
        assert original_worker.closed is True
        assert application.state.inference_worker is None
        assert application.state.inference_gate.locked()
        with TestClient(application) as second:
            second.cookies.set("b2_anon", token)
            assert initialized == ["initialize"]
            assert application.state.inference_worker is not original_worker
            assert_error(send(second, session_id, "turn-1"), 503, "MODEL_BUSY")
            assert second.get(f"/api/sessions/{session_id}/messages").json() == []
            engine.release.set()
            assert application.state.inference_gate.acquire(timeout=3)
            application.state.inference_gate.release()
            assert second.get(f"/api/sessions/{session_id}/messages").json() == []
            retry = send(second, session_id, "turn-1")
            assert retry.status_code == 200 and retry.json()["is_mock"] is True
            messages = second.get(f"/api/sessions/{session_id}/messages").json()
            assert len(messages) == 2
            assert messages[1]["content"] == retry.json()["reply"]
            assert len(engine.requests) == 2
        assert initialized == ["initialize"]
    finally:
        engine.release.set()


def test_cancelled_chat_aborts_reservation_and_discards_late_worker_result(chat_storage):
    engine = BlockingEngine()
    gate = Lock()
    worker = InferenceWorker(gate)
    owner = chat_storage.resolve_user(None)
    stored_session = chat_storage.create_session(owner.user_id)
    body = ChatRequest(session_id=stored_session.id, client_turn_id="cancelled-turn", text="虚构取消输入")
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            store=chat_storage,
            engine=engine,
            health=Health(status="ok", model_ready=True, is_mock=True, model_version=engine.model_version),
            inference_worker=worker,
            chat_timeout_seconds=3,
        )),
        state=SimpleNamespace(user_id=owner.user_id),
    )

    async def scenario():
        task = asyncio.create_task(chat(body, request))
        assert await asyncio.to_thread(engine.entered.wait, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert chat_storage.get_messages(owner.user_id, stored_session.id) == []
        replacement = chat_storage.reserve_turn(owner.user_id, stored_session.id, "cancelled-turn")
        assert isinstance(replacement, TurnReservation)
        chat_storage.abort_turn(replacement)
        assert gate.locked() and not engine.release.is_set()
        engine.release.set()
        assert await asyncio.to_thread(gate.acquire, True, 3)
        gate.release()
        assert chat_storage.get_messages(owner.user_id, stored_session.id) == []
        retry = await chat(body, request)
        assert retry.is_mock is True
        assert len(chat_storage.get_messages(owner.user_id, stored_session.id)) == 2
        assert len(engine.requests) == 2

    try:
        asyncio.run(scenario())
    finally:
        engine.release.set()
        worker.close()
