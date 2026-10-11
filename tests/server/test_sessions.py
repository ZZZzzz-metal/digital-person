"""B2 anonymous session API checks; stored replies are explicit mock fixtures."""

from __future__ import annotations

from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from b2_core.contracts import ChatResponse, SessionDTO
from b2_core.store import InMemoryStore, SQLiteStore
from server.app import create_app


@pytest.fixture(params=["memory", "sqlite"])
def storage(request, tmp_path, monkeypatch):
    monkeypatch.setenv("B2_COOKIE_SECURE", "0")
    instance = InMemoryStore() if request.param == "memory" else SQLiteStore(tmp_path / "api.sqlite3")
    yield instance
    instance.close()


def assert_error(response, status, code):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"].strip()


def commit_mock_fixture(instance, cookie_token, session_id):
    owner = instance.resolve_user(cookie_token)
    reservation = instance.reserve_turn(owner.user_id, session_id, "fixture-turn")
    instance.complete_turn(reservation, "虚构的用户输入", ChatResponse(
        session_id=session_id,
        client_turn_id="fixture-turn",
        reply="【演示数据】固定测试回复",
        emotion="unknown", expression="listening", retrieved_memories=[],
        model_version="unit-only-mock", elapsed_ms=0, is_mock=True,
    ))
    return owner.user_id


def test_health_does_not_create_identity_or_cookie(storage):
    with TestClient(create_app(mode="stub", store=storage)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
        assert client.cookies.get("b2_anon") is None


def test_two_anonymous_clients_are_isolated_and_cookie_has_local_attributes(storage):
    application = create_app(mode="stub", store=storage)
    with ExitStack() as stack:
        alice = stack.enter_context(TestClient(application))
        bob = stack.enter_context(TestClient(application))
        first = alice.post("/api/sessions", json={"title": "虚构甲会话"})
        second = bob.post("/api/sessions", json={"title": "虚构乙会话"})
        assert first.status_code == second.status_code == 200
        first_session = SessionDTO.model_validate(first.json())
        second_session = SessionDTO.model_validate(second.json())
        assert first_session.id != second_session.id
        assert first_session.title == "虚构甲会话"
        header = first.headers["set-cookie"].lower()
        assert "b2_anon=" in header and "httponly" in header
        assert "samesite=lax" in header and "path=/" in header
        assert "secure" not in header
        assert alice.cookies.get("b2_anon") != bob.cookies.get("b2_anon")
        assert [s["id"] for s in alice.get("/api/sessions").json()] == [first_session.id]
        assert [s["id"] for s in bob.get("/api/sessions").json()] == [second_session.id]
        assert alice.get(f"/api/sessions/{first_session.id}/messages").json() == []
        owner_id = commit_mock_fixture(storage, alice.cookies.get("b2_anon"), first_session.id)
        messages = alice.get(f"/api/sessions/{first_session.id}/messages").json()
        assert messages == [
            {"role": "user", "content": "虚构的用户输入"},
            {"role": "assistant", "content": "【演示数据】固定测试回复"},
        ]
        private = bob.get(f"/api/sessions/{first_session.id}/messages")
        missing = bob.get("/api/sessions/nonexistent/messages")
        assert_error(private, 404, "NOT_FOUND")
        assert private.json() == missing.json()
        private_delete = bob.delete(f"/api/sessions/{first_session.id}")
        assert_error(private_delete, 404, "NOT_FOUND")
        assert private_delete.json() == bob.delete("/api/sessions/nonexistent").json()
        assert owner_id not in str(private.json())
        assert alice.delete(f"/api/sessions/{first_session.id}").json() == {"ok": True}
        assert alice.get("/api/sessions").json() == []
        assert [s["id"] for s in bob.get("/api/sessions").json()] == [second_session.id]
        assert_error(alice.get(f"/api/sessions/{first_session.id}/messages"), 404, "NOT_FOUND")


@pytest.mark.parametrize("payload", [[], 1, {"title": " "}, {"title": "字" * 101}, {"title": "可见标题", "user_id": "forged-user"}])
def test_invalid_session_body_returns_contract_error(storage, payload):
    with TestClient(create_app(mode="stub", store=storage)) as client:
        assert_error(client.post("/api/sessions", json=payload), 400, "INVALID_REQUEST")
        assert client.get("/api/sessions").json() == []


def test_malformed_json_and_client_user_id_are_rejected(storage):
    with TestClient(create_app(mode="stub", store=storage)) as client:
        assert_error(client.post("/api/sessions", content="{broken", headers={"content-type": "application/json"}), 400, "INVALID_REQUEST")
        assert_error(client.get("/api/sessions", params={"user_id": "forged-user"}), 400, "INVALID_REQUEST")
        assert client.get("/api/sessions").json() == []


@pytest.mark.parametrize("forged", ["unknown-token", "owner-user-id"])
def test_unknown_cookie_or_raw_user_id_cannot_access_owner(storage, forged):
    application = create_app(mode="stub", store=storage)
    with TestClient(application) as owner:
        session_id = owner.post("/api/sessions", json={}).json()["id"]
        token = owner.cookies.get("b2_anon")
        user_id = storage.resolve_user(token).user_id
        fake = user_id if forged == "owner-user-id" else forged
        with TestClient(application) as intruder:
            intruder.cookies.set("b2_anon", fake)
            response = intruder.get(f"/api/sessions/{session_id}/messages")
            assert_error(response, 404, "NOT_FOUND")
            assert "set-cookie" in response.headers
            # Read the exact Set-Cookie token: the supplied cookie may have a
            # different domain in the client's test cookie jar.
            replacement = response.cookies.get("b2_anon")
            assert replacement and replacement != fake
            assert storage.resolve_user(replacement).user_id != user_id
            assert storage.list_sessions(storage.resolve_user(replacement).user_id) == []


def test_injected_store_remains_usable_after_application_shutdown(storage):
    with TestClient(create_app(mode="stub", store=storage)) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        token = client.cookies.get("b2_anon")
    identity = storage.resolve_user(token)
    assert [s.id for s in storage.list_sessions(identity.user_id)] == [session_id]


def test_delete_pending_session_returns_409_without_removing_it(storage):
    with TestClient(create_app(mode="stub", store=storage)) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        owner = storage.resolve_user(client.cookies.get("b2_anon"))
        reservation = storage.reserve_turn(owner.user_id, session_id, "fixture-pending")
        response = client.delete(f"/api/sessions/{session_id}")
        assert response.status_code == 409
        assert set(response.json()) == {"error"}
        assert [s["id"] for s in client.get("/api/sessions").json()] == [session_id]
        storage.abort_turn(reservation)
        assert client.delete(f"/api/sessions/{session_id}").json() == {"ok": True}


def test_sqlite_application_restart_preserves_cookie_session_and_mock_history(tmp_path):
    path = tmp_path / "restart.sqlite3"
    first = create_app(mode="stub", db_path=path)
    with TestClient(first) as client:
        session_id = client.post("/api/sessions", json={"title": "虚构持久化会话"}).json()["id"]
        token = client.cookies.get("b2_anon")
        commit_mock_fixture(first.state.store, token, session_id)
    second = create_app(mode="stub", db_path=path)
    with TestClient(second) as client:
        client.cookies.set("b2_anon", token)
        response = client.get("/api/sessions")
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
        assert [s["id"] for s in response.json()] == [session_id]
        assert len(client.get(f"/api/sessions/{session_id}/messages").json()) == 2


def test_secure_cookie_can_be_enabled_for_https(tmp_path, monkeypatch):
    monkeypatch.setenv("B2_COOKIE_SECURE", "1")
    with TestClient(create_app(mode="stub", db_path=tmp_path / "https.sqlite3"), base_url="https://testserver") as client:
        response = client.get("/api/sessions")
        assert response.status_code == 200
        assert "secure" in response.headers["set-cookie"].lower()


def test_sessions_memory_and_chat_routes_are_available(storage):
    with TestClient(create_app(mode="stub", store=storage)) as client:
        paths = client.get("/openapi.json").json()["paths"]
        assert set(paths) == {
            "/health", "/api/sessions", "/api/sessions/{session_id}/messages",
            "/api/sessions/{session_id}", "/api/memories",
            "/api/memories/settings", "/api/memories/{key}",
            "/api/memories/{memory_id}",
            "/api/chat",
        }
        assert sum(len(operations) for operations in paths.values()) == 11
        assert_error(client.post("/api/chat", json={}), 400, "INVALID_REQUEST")
        assert client.get("/api/memories").json() == {"enabled": True, "items": []}
