"""B1 lifecycle and metadata checks; no weights or real model are used."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from b2_core.contracts import CoreRequest, Message
from server.app import create_app
from server.stub import StubEngine


class UnitEngine:
    """Unit-only non-mock metadata fixture, not a model implementation."""

    is_mock = False
    model_version = "unit-only-engine"

    def generate(self, request):
        raise AssertionError("GET /health must not call generate")


@pytest.fixture(autouse=True)
def isolate_default_database(tmp_path, monkeypatch):
    monkeypatch.setenv("B2_DB_PATH", str(tmp_path / "health.sqlite3"))


def test_default_stub_health_and_b3_business_routes(monkeypatch):
    monkeypatch.delenv("B2_MODE", raising=False)
    application = create_app()
    assert application.state.engine is None
    with TestClient(application) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "model_ready": True,
            "is_mock": True,
            "model_version": "stub-b1",
        }
        assert "set-cookie" not in response.headers
        paths = client.get("/openapi.json").json()["paths"]
        assert set(paths) == {
            "/health",
            "/api/sessions",
            "/api/sessions/{session_id}/messages",
            "/api/sessions/{session_id}",
            "/api/memories",
            "/api/memories/settings",
            "/api/memories/{key}",
            "/api/memories/{memory_id}",
        }
        assert sum(len(operations) for operations in paths.values()) == 10
        assert client.post("/api/chat", json={}).status_code == 404
        assert client.get("/api/sessions").json() == []
        assert client.get("/api/memories").json() == {"enabled": True, "items": []}


def test_stub_reply_is_explicit_demonstration():
    reply = StubEngine().generate(
        CoreRequest(messages=[Message(role="user", content="你好")])
    )
    assert reply.is_mock is True
    assert reply.model_version == "stub-b1"
    assert "演示数据" in reply.reply
    assert "尚未调用真实模型" in reply.reply


def test_real_without_a_is_degraded_without_stub_fallback(monkeypatch):
    # Deterministically simulate a missing A module without changing A's files.
    monkeypatch.setitem(sys.modules, "b2_core.model", None)
    application = create_app(mode="real")
    with TestClient(application) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "degraded",
            "model_ready": False,
            "is_mock": False,
            "model_version": "unavailable",
        }
        assert application.state.engine is None
        assert "ModuleNotFoundError" in application.state.initialization_error


@pytest.mark.parametrize(
    "candidate",
    [
        StubEngine(),
        SimpleNamespace(is_mock=0, model_version="unit-only", generate=lambda _: None),
        SimpleNamespace(model_version="unit-only", generate=lambda _: None),
        SimpleNamespace(is_mock=False, model_version="", generate=lambda _: None),
        SimpleNamespace(is_mock=False, model_version="  ", generate=lambda _: None),
        SimpleNamespace(is_mock=False, model_version=1, generate=lambda _: None),
        SimpleNamespace(is_mock=False, generate=lambda _: None),
        SimpleNamespace(is_mock=False, model_version="unit-only", generate=None),
    ],
    ids=["mock", "nonbool", "no-mock-flag", "empty-version", "blank-version", "nonstring-version", "no-version", "no-generate"],
)
def test_real_rejects_mock_or_missing_explicit_metadata(candidate):
    application = create_app(mode="real", engine=candidate)
    with TestClient(application) as client:
        assert client.get("/health").json() == {
            "status": "degraded",
            "model_ready": False,
            "is_mock": False,
            "model_version": "unavailable",
        }
        assert application.state.engine is None
        assert application.state.initialization_error is not None


def test_factory_called_once_at_startup_and_health_does_not_reload():
    calls = []

    def factory():
        calls.append("initialize")
        return UnitEngine()

    application = create_app(mode="real", engine_factory=factory)
    assert calls == []
    with TestClient(application) as client:
        for _ in range(3):
            assert client.get("/health").json() == {
                "status": "ok",
                "model_ready": True,
                "is_mock": False,
                "model_version": "unit-only-engine",
            }
        assert calls == ["initialize"]
    # Reusing an app's lifespan must not silently initialize its model twice.
    with TestClient(application) as client:
        assert client.get("/health").json()["model_ready"] is True
    assert calls == ["initialize"]


def test_factory_failure_is_not_retried_or_replaced_with_stub():
    calls = []

    def factory():
        calls.append("initialize")
        raise RuntimeError("unit-only missing weights")

    application = create_app(mode="real", engine_factory=factory)
    with TestClient(application) as client:
        for _ in range(2):
            body = client.get("/health").json()
            assert body["status"] == "degraded"
            assert body["model_ready"] is False
            assert body["is_mock"] is False
        assert application.state.engine is None
    assert calls == ["initialize"]


def test_default_real_loader_uses_config_once_at_startup(monkeypatch):
    calls = []

    def unit_constructor(config_path):
        calls.append(config_path)
        return UnitEngine()

    monkeypatch.setitem(
        sys.modules, "b2_core.model", SimpleNamespace(ModelEngine=unit_constructor)
    )
    monkeypatch.setenv("B2_MODE", "real")
    monkeypatch.setenv("B2_MODEL_CONFIG", "weights/unit-only-config.json")
    application = create_app()
    assert calls == []
    with TestClient(application) as client:
        assert client.get("/health").json()["model_ready"] is True
        assert client.get("/health").json()["is_mock"] is False
    assert calls == ["weights/unit-only-config.json"]


@pytest.mark.parametrize("mode", ["mock", "REAL", "", "other"])
def test_invalid_mode_reports_configuration_error(mode):
    with pytest.raises(ValueError, match="B2_MODE must be 'stub' or 'real'"):
        create_app(mode=mode)


def test_invalid_environment_mode_is_not_replaced_with_default(monkeypatch):
    monkeypatch.setenv("B2_MODE", "")
    with pytest.raises(ValueError, match="B2_MODE"):
        create_app()


def test_engine_and_factory_are_mutually_exclusive():
    with pytest.raises(ValueError, match="either engine or engine_factory"):
        create_app(engine=StubEngine(), engine_factory=StubEngine)
