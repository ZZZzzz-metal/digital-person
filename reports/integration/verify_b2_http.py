"""Exercise B2 sessions on our own localhost processes and a fresh fixture DB.

No model generation. The one saved message pair is an explicitly labelled
fictional fixture, written through the store to check HTTP history reading.
Raw anonymous cookie tokens are never written to the report or logs here.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from uuid import uuid4

import httpx

from b2_core.contracts import ChatResponse, Health, Message, SessionDTO
from b2_core.store import SQLiteStore
from verify_b1_http import select_port


ROOT = Path(__file__).resolve().parents[2]
COOKIE = "b2_anon"


def stop_owned(child: subprocess.Popen) -> None:
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def start_owned(port: int, db_path: Path, log, children: list) -> subprocess.Popen:
    environment = os.environ.copy()
    environment.update({"B2_MODE": "stub", "B2_DB_PATH": str(db_path), "B2_COOKIE_SECURE": "0"})
    environment.pop("PYTHONPATH", None)
    child = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
    )
    children.append(child)
    deadline = time.monotonic() + 25
    with httpx.Client(trust_env=False, timeout=1) as probe:
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError(f"owned server exited: {child.returncode}")
            try:
                response = probe.get(f"http://127.0.0.1:{port}/health")
                response.raise_for_status()
                health = Health.model_validate(response.json())
                assert health.model_ready and health.is_mock
                assert "set-cookie" not in response.headers
                return child
            except httpx.TransportError:
                time.sleep(0.1)
    raise TimeoutError("B2 probe's local startup window exceeded 25 seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    scratch = ROOT / "reports/integration/.b2-work"
    scratch.mkdir(parents=True, exist_ok=True)
    db_path = scratch / f"http-{uuid4().hex}.sqlite3"
    log_path = scratch / "http.log"
    report_path = ROOT / "reports/integration/b2-http-smoke.json"
    children = []
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "B2 actual localhost sessions + SQLite persistence; fictional stored message fixture",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "passed": False,
        "checks": [],
        "all_owned_processes_stopped": False,
        "raw_cookies_recorded": False,
        "real_generation_performed": False,
        "official_container_verified": False,
    }

    def checked(name: str) -> None:
        result["checks"].append({"name": name, "passed": True})

    try:
        port = select_port(args.port)
        result["port"] = port
        result["command"] = ["python", "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", str(port)]
        base = f"http://127.0.0.1:{port}"
        with log_path.open("w", encoding="utf-8") as log:
            first = start_owned(port, db_path, log, children)
            checked("actual_stub_startup_and_health_without_identity_cookie")
            with httpx.Client(base_url=base, trust_env=False, timeout=3) as a, httpx.Client(base_url=base, trust_env=False, timeout=3) as b:
                created = a.post("/api/sessions", json={"title": "B2虚构会话A"})
                created.raise_for_status()
                session_a = SessionDTO.model_validate(created.json())
                cookie_header = created.headers.get("set-cookie", "").lower()
                assert "httponly" in cookie_header and "samesite=lax" in cookie_header and "path=/" in cookie_header
                assert a.cookies.get(COOKIE)
                created_b = b.post("/api/sessions", json={"title": "B2虚构会话B"})
                created_b.raise_for_status()
                session_b = SessionDTO.model_validate(created_b.json())
                assert a.cookies.get(COOKIE) != b.cookies.get(COOKIE)
                checked("server_generated_separate_cookies_with_HttpOnly_SameSite_Path")
                assert a.get("/api/sessions").json() == [session_a.model_dump()]
                assert b.get("/api/sessions").json() == [session_b.model_dump()]
                assert a.get(f"/api/sessions/{session_a.id}/messages").json() == []
                assert b.get(f"/api/sessions/{session_a.id}/messages").status_code == 404
                assert b.delete(f"/api/sessions/{session_a.id}").status_code == 404
                checked("two_cookie_users_have_isolated_list_history_and_delete")
                invalid = a.post("/api/sessions", json={"title": " ", "user_id": "untrusted-client-value"})
                assert invalid.status_code == 400 and set(invalid.json()) == {"error"}
                checked("invalid_input_returns_contract_400_error")

                # Store fixture only: no engine or /api/chat is used here.
                fixture_store = SQLiteStore(db_path)
                try:
                    user_a = fixture_store.resolve_user(a.cookies.get(COOKIE)).user_id
                    reservation = fixture_store.reserve_turn(user_a, session_a.id, "b2-http-fixture-turn")
                    fixture = ChatResponse(
                        session_id=session_a.id, client_turn_id="b2-http-fixture-turn",
                        reply="【B2虚构fixture】仅验证历史读取，没有调用模型。",
                        emotion="unknown", expression="listening", retrieved_memories=[],
                        model_version="b2-http-fixture", elapsed_ms=0, is_mock=True,
                    )
                    fixture_store.complete_turn(reservation, "【B2虚构fixture】存储输入。", fixture)
                finally:
                    fixture_store.close()
                messages = a.get(f"/api/sessions/{session_a.id}/messages").json()
                assert [Message.model_validate(item).role for item in messages] == ["user", "assistant"]
                assert messages[-1]["content"] == fixture.reply
                checked("HTTP_history_reads_atomic_pair_from_explicit_fictional_store_fixture")

                openapi = a.get("/openapi.json").json()
                assert set(openapi["paths"]) == {"/health", "/api/sessions", "/api/sessions/{session_id}/messages", "/api/sessions/{session_id}"}
                operations = sum(method in ("get", "post", "delete", "put", "patch") for path in openapi["paths"].values() for method in path)
                assert operations == 5
                result["openapi_operations"] = operations
                checked("exactly_health_plus_four_session_operations")
                stop_owned(first)
                start_owned(port, db_path, log, children)
                assert a.get("/api/sessions").json() == [session_a.model_dump()]
                assert a.get(f"/api/sessions/{session_a.id}/messages").json() == messages
                assert b.get("/api/sessions").json() == [session_b.model_dump()]
                checked("restart_preserves_both_anonymous_users_and_completed_messages")
                deleted = a.delete(f"/api/sessions/{session_a.id}")
                assert deleted.status_code == 200 and deleted.json() == {"ok": True}
                assert a.get("/api/sessions").json() == []
                assert a.get(f"/api/sessions/{session_a.id}/messages").status_code == 404
                assert b.get("/api/sessions").json() == [session_b.model_dump()]
                checked("owner_delete_removes_only_own_session_and_history")
            result["passed"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for child in children:
            stop_owned(child)
        result["owned_processes_started"] = len(children)
        result["all_owned_processes_stopped"] = all(child.poll() is not None for child in children)
        if log_path.exists():
            result["startup_log"] = log_path.read_text(encoding="utf-8", errors="replace")[-12000:]
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "passed": result["passed"], "checks_passed": len(result["checks"]), "error": result.get("error")}, ensure_ascii=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
