"""Actual B4 localhost chat probe; all conversation inputs are fictional.

Stub and real results go to different reports. A source snapshots may be read
from outside this checkout without modifying A's project files. Real mode uses
only verified local assets, with outgoing non-loopback socket calls blocked.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import ipaddress
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx

from b2_core.contracts import ChatResponse, Health
from verify_b1_http import select_port
from verify_b2_http import stop_owned


ROOT = Path(__file__).resolve().parents[2]


def read_a_sources(args) -> dict:
    if not args.a_source_root:
        return {"source": "current project A implementation"}
    if not args.a_manifest:
        raise ValueError("A snapshot requires --a-manifest with pinned source hashes")
    manifest = json.loads(Path(args.a_manifest).read_text(encoding="utf-8"))
    checked = {}
    for entry in manifest["A_readonly_review_copies"]:
        path = entry["path"]
        if path.startswith("src/b2_core/") and path.endswith(".py"):
            raw = (Path(args.a_source_root) / path.removeprefix("src/")).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != entry["sha256"]:
                raise ValueError("A source checksum mismatch: " + path)
            checked[path] = digest
    if "src/b2_core/model.py" not in checked:
        raise ValueError("A model source missing from pinned snapshot")
    return {"source": "read-only remote main snapshot", "main_sha": manifest["main_sha"], "sha256": checked}


def block_outgoing_network() -> None:
    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def allowed(connection, address):
        if connection.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0]
            if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
                raise OSError("B4 probe blocks non-loopback network connections")

    def connect(connection, address):
        allowed(connection, address)
        return original_connect(connection, address)

    def connect_ex(connection, address):
        allowed(connection, address)
        return original_connect_ex(connection, address)

    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex


def serve(args) -> int:
    import uvicorn
    from server.app import create_app
    from server.stub import StubEngine

    read_a_sources(args)
    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
    block_outgoing_network()
    if args.a_source_root:
        import b2_core
        b2_core.__path__.append(str(Path(args.a_source_root) / "b2_core"))
    trace_path = Path(args.trace)
    trace = {"initializations": 0, "requests": [], "completed_generations": 0,
             "outbound_network_guard_enabled": True}

    def save_trace():
        trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    class Recorder:
        def __init__(self, target):
            self.target = target
            self.is_mock = target.is_mock
            self.model_version = target.model_version

        def generate(self, request):
            trace["requests"].append(request.model_dump())
            reply = self.target.generate(request)
            trace["completed_generations"] += 1
            save_trace()
            return reply

    def factory():
        trace["initializations"] += 1
        if args.mode == "real":
            from b2_core.model import ModelEngine
            target = ModelEngine(args.config)
            trace["description"] = target.describe()
        else:
            target = StubEngine()
        trace["is_mock"], trace["model_version"] = target.is_mock, target.model_version
        save_trace()
        return Recorder(target)

    app = create_app(mode=args.mode, engine_factory=factory, db_path=args.db, chat_timeout_seconds=60)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    return 0


def main(args) -> int:
    if args.mode == "real" and not args.config:
        raise ValueError("real mode requires --config with complete local model assets")
    scratch = ROOT / "reports/integration/.b4-work"
    scratch.mkdir(parents=True, exist_ok=True)
    name = args.mode + "-" + uuid4().hex
    db_path, trace_path, log_path = (scratch / (name + suffix) for suffix in (".sqlite3", ".trace.json", ".log"))
    report_path = ROOT / f"reports/integration/b4-{args.mode}-http.json"
    children = []
    result = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "mode": args.mode,
              "python_version": platform.python_version(), "platform": platform.platform(),
              "passed": False, "checks": [], "responses": [], "raw_cookies_recorded": False,
              "real_generation_performed": False, "official_container_verified": False}

    def checked(name):
        result["checks"].append({"name": name, "passed": True})

    try:
        result["A_source"] = read_a_sources(args) if args.mode == "real" else None
        port = select_port(args.port)
        result["port"] = port
        command = [sys.executable, str(Path(__file__)), "--serve", "--mode", args.mode, "--port", str(port), "--db", str(db_path), "--trace", str(trace_path)]
        for option, value in (("--config", args.config), ("--a-source-root", args.a_source_root), ("--a-manifest", args.a_manifest)):
            if value:
                command.extend([option, str(Path(value).resolve())])
        result["command"] = command
        with log_path.open("w", encoding="utf-8") as log:
            child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            children.append(child)
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=base, trust_env=False, timeout=65) as a, httpx.Client(base_url=base, trust_env=False, timeout=65) as b:
                deadline = time.monotonic() + 60
                while True:
                    if child.poll() is not None:
                        raise RuntimeError("owned server exited during startup")
                    try:
                        health_response = a.get("/health", timeout=1)
                        break
                    except httpx.TransportError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("owned server startup exceeded local 60-second probe window")
                        time.sleep(0.1)
                health = Health.model_validate(health_response.json())
                assert health.model_ready and health.is_mock == (args.mode == "stub")
                assert "set-cookie" not in health_response.headers
                checked("actual_startup_truthful_health_and_no_identity_cookie")
                session = a.post("/api/sessions", json={}).json()["id"]
                a.put("/api/memories/exam_subject", json={"value": "高数"}).raise_for_status()
                texts = ["我这几天一想到考试就紧张。", "这门考试让我有些压力。", "你记得我担心哪门考试吗？", "这次考试让我有些担心。", "帮我想一个考试复习的小步骤。", "今天和室友相处有点烦。"]
                responses = []
                for index, text in enumerate(texts):
                    if index == 2:
                        a.put("/api/memories/exam_subject", json={"value": "线代"}).raise_for_status()
                    if index in (3, 4):
                        a.put("/api/memories/settings", json={"enabled": index == 4}).raise_for_status()
                    body = {"session_id": session, "client_turn_id": f"six-turn-{index}", "text": text}
                    response = a.post("/api/chat", json=body)
                    response.raise_for_status()
                    dto = ChatResponse.model_validate(response.json())
                    assert dto.is_mock == health.is_mock and dto.model_version == health.model_version
                    assert dto.reply.strip() and any("\u4e00" <= character <= "\u9fff" for character in dto.reply)
                    expected = [] if index in (3, 5) else ["高数" if index < 2 else "线代"]
                    assert [item.value for item in dto.retrieved_memories] == expected
                    responses.append(response.json())
                    repeated = a.post("/api/chat", json=body)
                    assert repeated.json() == response.json()
                result["responses"] = responses
                checked("six_completed_turns_and_exact_success_retry_without_duplicate_messages")
                history = a.get(f"/api/sessions/{session}/messages").json()
                assert len(history) == 12 and [item["content"] for item in history[::2]] == texts
                checked("history_is_six_ordered_user_assistant_pairs")
                checked("corrected_memory_disabled_memory_and_unrelated_topic_candidates")

                next_session = a.post("/api/sessions", json={}).json()["id"]
                cross = a.post("/api/chat", json={"session_id": next_session, "client_turn_id": "cross-session", "text": "我又开始担心考试了。"})
                cross.raise_for_status()
                assert [item["value"] for item in cross.json()["retrieved_memories"]] == ["线代"]
                assert b.get(f"/api/sessions/{session}/messages").status_code == 404
                bob_session = b.post("/api/sessions", json={}).json()["id"]
                bob = b.post("/api/chat", json={"session_id": bob_session, "client_turn_id": "other-user", "text": "我担心考试。"})
                bob.raise_for_status()
                assert bob.json()["retrieved_memories"] == []
                checked("cross_session_memory_and_second_cookie_isolation")

                trace = json.loads(trace_path.read_text(encoding="utf-8"))
                assert trace["initializations"] == 1 and len(trace["requests"]) == 8
                for index, received in enumerate(trace["requests"][:6]):
                    assert len(received["messages"]) == 2 * index + 1
                    assert received["messages"][-1] == {"role": "user", "content": texts[index]}
                    assert [item["content"] for item in received["messages"][::2]] == texts[:index + 1]
                assert "线代" in trace["requests"][2]["memory_context"] and "高数" not in trace["requests"][2]["memory_context"]
                assert trace["requests"][3]["memory_context"] == trace["requests"][5]["memory_context"] == trace["requests"][7]["memory_context"] == ""
                assert len(trace["requests"][6]["messages"]) == len(trace["requests"][7]["messages"]) == 1
                result["engine_trace"] = trace
                result["real_generation_performed"] = args.mode == "real"
                checked("actual_engine_initialized_once_current_input_once_and_retry_calls_not_repeated")
                paths = a.get("/openapi.json").json()["paths"]
                assert len(paths) == 9 and sum(len(methods) for methods in paths.values()) == 11
                assert "422" not in paths["/api/chat"]["post"]["responses"]
                assert a.post("/api/chat", json={}).status_code == 400
                checked("chat_OpenAPI_and_invalid_input_match_contract")
                result["passed"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for child in children:
            stop_owned(child)
        result["owned_processes_started"] = len(children)
        result["all_owned_processes_stopped"] = all(child.poll() is not None for child in children)
        if trace_path.exists() and "engine_trace" not in result:
            result["partial_engine_trace"] = json.loads(trace_path.read_text(encoding="utf-8"))
        observed_trace = result.get("engine_trace", result.get("partial_engine_trace", {}))
        result["completed_generations"] = observed_trace.get("completed_generations", 0)
        result["real_generation_performed"] = args.mode == "real" and result["completed_generations"] > 0
        if log_path.exists():
            result["startup_log"] = log_path.read_text(encoding="utf-8", errors="replace")[-14000:]
        result["runtime_packages"] = {name: importlib.metadata.version(name) for name in ("fastapi", "pydantic", "uvicorn")}
        for name in ("torch", "transformers"):
            try:
                result["runtime_packages"][name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                pass
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "passed": result["passed"], "checks_passed": len(result["checks"]), "error": result.get("error")}, ensure_ascii=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--mode", choices=("stub", "real"), default="stub")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--config")
    parser.add_argument("--a-source-root")
    parser.add_argument("--a-manifest")
    parser.add_argument("--db")
    parser.add_argument("--trace")
    arguments = parser.parse_args()
    raise SystemExit(serve(arguments) if arguments.serve else main(arguments))
