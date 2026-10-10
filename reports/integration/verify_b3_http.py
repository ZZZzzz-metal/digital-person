"""Run B3 memory HTTP checks on two owned local stub server processes.

All facts are fictional. Cookies stay in client memory, never in the report.
CoreRequest checks construct fixture input only; no model generates a reply.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
from uuid import uuid4

import httpx

from b2_core.contracts import CoreRequest, MemoryItem, MemoryList, Message, SessionDTO
from b2_core.memory import build_memory_context
from b2_core.store import SQLiteStore
from verify_b1_http import select_port
from verify_b2_http import start_owned, stop_owned


ROOT = Path(__file__).resolve().parents[2]
COOKIE = "b2_anon"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    scratch = ROOT / "reports/integration/.b3-work"
    scratch.mkdir(parents=True, exist_ok=True)
    db_path = scratch / f"http-{uuid4().hex}.sqlite3"
    log_path = scratch / "http.log"
    report_path = ROOT / "reports/integration/b3-http-smoke.json"
    children = []
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "B3 actual localhost memory CRUD, SQLite restart, and pure CoreRequest fixture construction",
        "python_version": platform.python_version(), "platform": platform.platform(),
        "passed": False, "checks": [], "all_owned_processes_stopped": False,
        "raw_cookies_recorded": False, "real_generation_performed": False,
        "official_container_verified": False,
    }

    def checked(name: str) -> None:
        result["checks"].append({"name": name, "passed": True})

    def saved(client: httpx.Client, key: str, value: str) -> MemoryItem:
        response = client.put(f"/api/memories/{key}", json={"value": value})
        response.raise_for_status()
        return MemoryItem.model_validate(response.json())

    def listed(client: httpx.Client) -> MemoryList:
        response = client.get("/api/memories")
        response.raise_for_status()
        return MemoryList.model_validate(response.json())

    def setting(client: httpx.Client, enabled: bool) -> MemoryList:
        response = client.put("/api/memories/settings", json={"enabled": enabled})
        response.raise_for_status()
        return MemoryList.model_validate(response.json())

    try:
        port = select_port(args.port)
        result["port"] = port
        result["command"] = ["python", "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", str(port)]
        base = f"http://127.0.0.1:{port}"
        with log_path.open("w", encoding="utf-8") as log:
            first = start_owned(port, db_path, log, children)
            checked("actual_stub_health_ready_without_identity_cookie")
            with httpx.Client(base_url=base, trust_env=False, timeout=3) as a, httpx.Client(base_url=base, trust_env=False, timeout=3) as b:
                assert listed(a) == MemoryList(enabled=True, items=[])
                assert listed(b) == MemoryList(enabled=True, items=[])
                assert a.cookies.get(COOKIE) and a.cookies.get(COOKIE) != b.cookies.get(COOKIE)
                old = saved(a, "exam_subject", "高数")
                other = saved(b, "exam_subject", "英语")
                assert listed(a).items == [old] and listed(b).items == [other]
                foreign = b.delete(f"/api/memories/{old.id}")
                missing = b.delete("/api/memories/not-an-id")
                assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()
                checked("distinct_cookie_users_cannot_list_or_delete_each_others_facts")

                response = a.post("/api/sessions", json={"title": "B3虚构跨会话"})
                response.raise_for_status()
                session = SessionDTO.model_validate(response.json())
                assert listed(a).items == [old]
                updated = saved(a, "exam_subject", "  线代  ")
                assert updated.id == old.id and updated.value == "线代" and listed(a).items == [updated]
                assert a.delete(f"/api/sessions/{session.id}").json() == {"ok": True}
                assert listed(a).items == [updated]
                checked("same_key_correction_keeps_id_and_session_deletion_keeps_user_memory")

                # Resolve the HTTP identity in the same DB and build input only.
                store = SQLiteStore(db_path)
                try:
                    user_a = store.resolve_user(a.cookies.get(COOKIE)).user_id
                    context = build_memory_context("你记得我担心哪门考试吗？", store.list_memories(user_a).items)
                    request = CoreRequest(messages=[Message(role="user", content="你记得我担心哪门考试吗？")], memory_context=context.prompt_text)
                    assert "线代" in request.memory_context and "高数" not in request.memory_context
                    assert [item.id for item in context.retrieved_memories] == [updated.id]
                    assert build_memory_context("今天和室友有矛盾", store.list_memories(user_a).items).prompt_text == ""
                finally:
                    store.close()
                checked("next_CoreRequest_fixture_contains_only_corrected_related_fact")

                assert setting(a, False) == MemoryList(enabled=False, items=[])
                blocked = a.put("/api/memories/exam_subject", json={"value": "高数"})
                assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "MEMORY_DISABLED"
                assert listed(a) == MemoryList(enabled=False, items=[])
                store = SQLiteStore(db_path)
                try:
                    context = build_memory_context("聊聊考试", store.list_memories(user_a).items)
                    request = CoreRequest(messages=[Message(role="user", content="聊聊考试")], memory_context=context.prompt_text)
                    assert request.memory_context == "" and context.retrieved_memories == []
                finally:
                    store.close()
                checked("disabled_read_is_empty_save_is_rejected_and_CoreRequest_memory_is_empty")

                assert setting(a, True).items == [updated]
                assert listed(b).items == [other]
                checked("reenable_restores_corrected_fact_and_blocked_save_did_not_change_it")
                assert setting(b, False) == MemoryList(enabled=False, items=[])
                stop_owned(first)
                start_owned(port, db_path, log, children)
                assert listed(a).items == [updated]
                assert listed(b) == MemoryList(enabled=False, items=[])
                assert setting(b, True).items == [other]
                checked("SQLite_restart_preserves_cookies_facts_and_disabled_state")

                deleted = a.delete(f"/api/memories/{updated.id}")
                assert deleted.status_code == 200 and deleted.json() == {"ok": True}
                assert a.delete(f"/api/memories/{updated.id}").status_code == 404
                fresh = saved(a, "exam_subject", "线代")
                assert fresh.id != updated.id
                saved(a, "hobby", "围棋")
                assert setting(a, False).items == []
                assert a.delete(f"/api/memories/{fresh.id}").json() == {"ok": True}
                assert a.delete("/api/memories").json() == {"ok": True}
                assert listed(a) == MemoryList(enabled=False, items=[])
                assert setting(a, True).items == [] and listed(b).items == [other]
                checked("explicit_delete_and_clear_work_while_off_preserving_other_user_and_setting")

                for response in (
                    a.put("/api/memories/health_diagnosis", json={"value": "虚构字段"}),
                    a.put("/api/memories/hobby", json={"value": " "}),
                    a.put("/api/memories/hobby", json={"value": "围棋", "user_id": "untrusted"}),
                    a.put("/api/memories/settings", json={"enabled": "true"}),
                    a.get("/api/memories", params={"user_id": "untrusted"}),
                ):
                    assert response.status_code == 400 and set(response.json()) == {"error"}
                checked("whitelist_value_boolean_and_identity_validation_return_contract_400")

                paths = a.get("/openapi.json").json()["paths"]
                assert set(paths) == {"/health", "/api/sessions", "/api/sessions/{session_id}/messages", "/api/sessions/{session_id}", "/api/memories", "/api/memories/settings", "/api/memories/{key}", "/api/memories/{memory_id}"}
                operations = sum(method in ("get", "post", "delete", "put", "patch") for path in paths.values() for method in path)
                assert operations == 10 and a.post("/api/chat", json={}).status_code == 404
                assert all("422" not in operation.get("responses", {}) for path in paths.values() for operation in path.values())
                result["openapi_operations"] = operations
                checked("health_four_session_five_memory_operations_without_chat_or_422")
            result["passed"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for child in children:
            stop_owned(child)
        result["owned_processes_started"] = len(children)
        result["all_owned_processes_stopped"] = all(child.poll() is not None for child in children)
        if log_path.exists():
            result["startup_log"] = log_path.read_text(encoding="utf-8", errors="replace")[-16000:]
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "passed": result["passed"], "checks_passed": len(result["checks"]), "error": result.get("error")}, ensure_ascii=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
