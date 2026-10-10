"""Start our own B1 process, inspect localhost health, then stop that process.

This checks HTTP/lifecycle only. --mode real can load A's local model but does
not generate a reply, measure inference, or verify the official container.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time

import httpx

from b2_core.contracts import Health


ROOT = Path(__file__).resolve().parents[2]


def select_port(requested: int) -> int:
    if not 0 <= requested <= 65535:
        raise ValueError("port must be in 0..65535")
    # Refuse an occupied port. Never stop a pre-existing service.
    with socket.socket() as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(("127.0.0.1", requested))
        return probe.getsockname()[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("stub", "real"), default="stub")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    scratch = ROOT / "reports/integration/.b1-work"
    scratch.mkdir(parents=True, exist_ok=True)
    log_path = scratch / f"http-{args.mode}.log"
    report_path = ROOT / f"reports/integration/b1-http-{args.mode}.json"
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "B1 HTTP/lifecycle only; no generation or official inference",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "mode": args.mode,
        "passed": False,
        "process_started": False,
        "owned_process_stopped": False,
        "real_inference_verified": False,
        "official_container_verified": False,
    }
    child = None
    try:
        port = select_port(args.port)
        result["port"] = port
        command = [
            sys.executable, "-m", "uvicorn", "server.app:app",
            "--host", "127.0.0.1", "--port", str(port),
        ]
        environment = os.environ.copy()
        environment["B2_MODE"] = args.mode
        environment.pop("PYTHONPATH", None)
        result["command"] = ["python", *command[1:]]
        with log_path.open("w", encoding="utf-8") as log:
            child = subprocess.Popen(
                command, cwd=ROOT, env=environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            )
            result["process_started"] = True
            deadline = time.monotonic() + 25
            body = None
            with httpx.Client(trust_env=False, timeout=1) as client:
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        raise RuntimeError(f"server exited with code {child.returncode}")
                    try:
                        response = client.get(f"http://127.0.0.1:{port}/health")
                        response.raise_for_status()
                        body = response.json()
                        break
                    except httpx.TransportError:
                        time.sleep(0.1)
                if body is None:
                    raise TimeoutError("B1 HTTP startup did not complete within probe's 25s window")
                health = Health.model_validate(body)
                if health.is_mock is not (args.mode == "stub"):
                    raise AssertionError("mode and health.is_mock disagree")
                if args.mode == "stub" and body != {
                    "status": "ok", "model_ready": True,
                    "is_mock": True, "model_version": "stub-b1",
                }:
                    raise AssertionError("default stub health differs from B1 contract")
                openapi = client.get(f"http://127.0.0.1:{port}/openapi.json")
                openapi.raise_for_status()
                paths = sorted(openapi.json()["paths"])
                if paths != ["/health"]:
                    raise AssertionError("unexpected business routes outside B1")
                result.update({
                    "http_status": response.status_code,
                    "health": body,
                    "openapi_paths": paths,
                    "passed": True,
                })
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if child is not None:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            result["owned_process_stopped"] = child.poll() is not None
        if log_path.exists() and result["process_started"]:
            result["startup_log"] = log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "passed": result["passed"],
                      "health": result.get("health"), "error": result.get("error")}, ensure_ascii=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
