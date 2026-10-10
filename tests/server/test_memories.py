"""B3 HTTP memory management with two isolated anonymous users."""

from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from b2_core.contracts import MemoryItem, MemoryList
from b2_core.store import InMemoryStore, SQLiteStore
from server.app import create_app


@pytest.fixture(params=["memory", "sqlite"])
def memory_storage(request, tmp_path, monkeypatch):
    monkeypatch.setenv("B2_COOKIE_SECURE", "0")
    instance = InMemoryStore() if request.param == "memory" else SQLiteStore(tmp_path / "api-memory.sqlite3")
    yield instance
    instance.close()


def assert_error(response, status, code):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"].strip()


def test_confirm_save_correct_and_reuse_across_sessions_without_chat(memory_storage):
    with TestClient(create_app(mode="stub", store=memory_storage)) as client:
        assert client.get("/api/memories").json() == {"enabled": True, "items": []}
        first_session = client.post("/api/sessions", json={}).json()["id"]
        original_response = client.put("/api/memories/exam_subject", json={"value": " 高数 "})
        assert original_response.status_code == 200
        original = MemoryItem.model_validate(original_response.json())
        assert original.value == "高数"
        corrected_response = client.put("/api/memories/exam_subject", json={"value": "线代"})
        assert corrected_response.status_code == 200
        corrected = MemoryItem.model_validate(corrected_response.json())
        assert corrected.id == original.id and corrected.value == "线代"
        second_session = client.post("/api/sessions", json={}).json()["id"]
        assert client.get(f"/api/sessions/{second_session}/messages").json() == []
        assert client.delete(f"/api/sessions/{first_session}").json() == {"ok": True}
        assert MemoryList.model_validate(client.get("/api/memories").json()).items == [corrected]
        assert client.delete(f"/api/memories/{corrected.id}").json() == {"ok": True}
        assert client.get("/api/memories").json()["items"] == []


def test_disabled_save_conflicts_reenable_recovers_and_explicit_clear_preserves_switch(memory_storage):
    with TestClient(create_app(mode="stub", store=memory_storage)) as client:
        saved = client.put("/api/memories/exam_subject", json={"value": "高数"}).json()
        assert client.put("/api/memories/settings", json={"enabled": False}).json() == {"enabled": False, "items": []}
        assert client.get("/api/memories").json() == {"enabled": False, "items": []}
        assert_error(client.put("/api/memories/exam_subject", json={"value": "线代"}), 409, "MEMORY_DISABLED")
        assert client.put("/api/memories/settings", json={"enabled": True}).json()["items"] == [saved]
        client.put("/api/memories/hobby", json={"value": "围棋"})
        client.put("/api/memories/settings", json={"enabled": False})
        assert client.delete(f"/api/memories/{saved['id']}").json() == {"ok": True}
        assert client.get("/api/memories").json()["enabled"] is False
        restored = client.put("/api/memories/settings", json={"enabled": True}).json()
        assert [m["key"] for m in restored["items"]] == ["hobby"]
        client.put("/api/memories/settings", json={"enabled": False})
        assert client.delete("/api/memories").json() == {"ok": True}
        assert client.get("/api/memories").json() == {"enabled": False, "items": []}
        assert client.put("/api/memories/settings", json={"enabled": True}).json() == {"enabled": True, "items": []}


def test_two_cookie_users_cannot_list_or_delete_each_others_facts(memory_storage):
    application = create_app(mode="stub", store=memory_storage)
    with ExitStack() as stack:
        alice = stack.enter_context(TestClient(application))
        bob = stack.enter_context(TestClient(application))
        a = alice.put("/api/memories/exam_subject", json={"value": "高数"}).json()
        b = bob.put("/api/memories/exam_subject", json={"value": "线代"}).json()
        assert alice.cookies.get("b2_anon") != bob.cookies.get("b2_anon")
        assert alice.get("/api/memories").json()["items"] == [a]
        assert bob.get("/api/memories").json()["items"] == [b]
        foreign = bob.delete(f"/api/memories/{a['id']}")
        missing = bob.delete("/api/memories/nonexistent")
        assert_error(foreign, 404, "NOT_FOUND")
        assert foreign.json() == missing.json()
        assert alice.delete("/api/memories").json() == {"ok": True}
        assert bob.get("/api/memories").json()["items"] == [b]


@pytest.mark.parametrize("payload", [
    {}, {"value": " "}, {"value": "字" * 201}, {"value": 12},
    {"value": True}, {"value": ["围棋"]},
    {"value": "围棋", "user_id": "forged-user"},
    {"value": "围棋", "id": "forged-memory"},
    {"value": "围棋", "updated_at": "2026-10-10T00:00:00Z"},
])
def test_invalid_save_body_returns_400_without_changing_existing_memory(memory_storage, payload):
    with TestClient(create_app(mode="stub", store=memory_storage)) as client:
        original = client.put("/api/memories/hobby", json={"value": "国际象棋"}).json()
        assert_error(client.put("/api/memories/hobby", json=payload), 400, "INVALID_REQUEST")
        assert client.get("/api/memories").json()["items"] == [original]


@pytest.mark.parametrize("payload", [{}, {"enabled": 0}, {"enabled": 1}, {"enabled": "false"}, {"enabled": False, "user_id": "forged-user"}])
def test_invalid_settings_requires_boolean_and_rejects_user_override(memory_storage, payload):
    with TestClient(create_app(mode="stub", store=memory_storage)) as client:
        assert_error(client.put("/api/memories/settings", json=payload), 400, "INVALID_REQUEST")
        assert client.get("/api/memories").json() == {"enabled": True, "items": []}


def test_unknown_key_query_identity_and_malformed_json_are_parameter_errors(memory_storage):
    with TestClient(create_app(mode="stub", store=memory_storage)) as client:
        assert_error(client.put("/api/memories/diagnosis", json={"value": "不可保存"}), 400, "INVALID_REQUEST")
        assert_error(client.get("/api/memories", params={"user_id": "forged-user"}), 400, "INVALID_REQUEST")
        assert_error(client.put("/api/memories/hobby", content="{broken", headers={"content-type": "application/json"}), 400, "INVALID_REQUEST")
        assert client.get("/api/memories").json()["items"] == []


def test_openapi_declares_five_memory_operations_and_real_error_statuses(memory_storage):
    with TestClient(create_app(mode="stub", store=memory_storage)) as client:
        paths = client.get("/openapi.json").json()["paths"]
        expected = {
            ("/api/memories", "get"), ("/api/memories", "delete"),
            ("/api/memories/settings", "put"), ("/api/memories/{key}", "put"),
            ("/api/memories/{memory_id}", "delete"),
        }
        actual = {(path, method) for path, operations in paths.items() if path.startswith("/api/memories") for method in operations}
        assert actual == expected
        for path, method in expected:
            responses = paths[path][method]["responses"]
            assert "400" in responses and "422" not in responses
        assert "409" in paths["/api/memories/{key}"]["put"]["responses"]
        assert "404" in paths["/api/memories/{memory_id}"]["delete"]["responses"]


def test_sqlite_api_restart_preserves_cookie_corrected_fact_and_disabled_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("B2_COOKIE_SECURE", "0")
    path = tmp_path / "memory-api-restart.sqlite3"
    with TestClient(create_app(mode="stub", db_path=path)) as client:
        original = client.put("/api/memories/exam_subject", json={"value": "高数"}).json()
        corrected = client.put("/api/memories/exam_subject", json={"value": "线代"}).json()
        assert corrected["id"] == original["id"]
        token = client.cookies.get("b2_anon")
        client.put("/api/memories/settings", json={"enabled": False})
    with TestClient(create_app(mode="stub", db_path=path)) as client:
        client.cookies.set("b2_anon", token)
        response = client.get("/api/memories")
        assert "set-cookie" not in response.headers
        assert response.json() == {"enabled": False, "items": []}
        assert client.put("/api/memories/settings", json={"enabled": True}).json()["items"] == [corrected]
