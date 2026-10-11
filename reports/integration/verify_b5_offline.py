"""Run the actual B5 CLI with pinned, read-only A sources and local assets.

This is a local CPU acceptance helper, not the production inference entrypoint.
It retains candidate files in a new work directory, runs the independent output
checker, and compares the first/third samples in reverse order in a new process.
No model output or raw input text is copied into the public report or console.
Running this helper performs real inference; --help and compilation do not.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "reports/integration"
TIMEOUT_SECONDS = 15 * 60
TRACE_KEYS = {
    "sample_id", "mode", "is_mock", "model_version", "parse_failed",
    "parse_failures", "emotion_source", "profile_source", "response_source",
    "memory_refs_policy", "schema_valid", "elapsed_ms",
    "prompt_tokens", "new_tokens", "dropped_turns", "contract_source",
}
EVENT_KEYS = {
    "event", "id", "sample_id", "index", "samples", "initializations",
    "is_mock", "model_version", "device", "versions", "runtime_packages",
    "history_count", "history_messages", "history_sha256", "current_user_once",
    "fresh_store_created", "fresh_store_closed", "memory_context_empty",
    "elapsed_ms", "parse_trace", "trace", "code", "type", "rounds",
    "complete", "required_rounds", "network_guard_enabled", "offline",
    "submission_sha256", "performance_report_sha256", "input_sha256",
    "sha256", "torch_version", "cuda_available", *TRACE_KEYS,
}
KNOWN_EVENTS = {"model_ready", "runtime", "sample_complete", "sample_failed",
                "batch_complete", "output_valid", "output_invalid", "batch_failed"}
PERFORMANCE_KEYS = {
    "version", "backend", "timing_scope", "model_version", "is_mock",
    "device", "hardware_label", "complete", "required_rounds", "rounds",
    "average_latency_ms", "median_latency_ms", "p95_latency_ms",
    "min_latency_ms", "max_latency_ms", "latencies_ms", "test_file_sha256",
    "submission_sha256", "samples", "parse_failure_count", "parse_failure_ids",
}

# Only this child runner receives --a-source-root. Production CLI arguments do
# not contain that option and the production package remains unchanged.
CHILD_RUNNER = r'''from __future__ import annotations
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import runpy
import socket
import sys

def denied(*args, **kwargs):
    raise OSError("B5 local acceptance runner blocks network connections")

socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.socket.sendto = denied
if hasattr(socket.socket, "sendmsg"):
    socket.socket.sendmsg = denied

p = argparse.ArgumentParser()
p.add_argument("--action", choices=("runtime", "inference", "check"), required=True)
p.add_argument("--root", required=True)
p.add_argument("--a-source-root", required=True)
p.add_argument("--config", required=True)
p.add_argument("--test")
p.add_argument("--result")
a = p.parse_args()
root = Path(a.root)
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))
import b2_core
b2_core.__path__.append(str(Path(a.a_source_root) / "b2_core"))

if a.action == "runtime":
    import torch
    packages = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            packages[name] = dist.version
    observed = {
        "event": "helper_runtime", "python_version": platform.python_version(),
        "platform": platform.platform(), "machine": platform.machine(),
        "cpu_count": os.cpu_count(), "distribution_versions": dict(sorted(packages.items())),
        "torch_version": torch.__version__, "torch_cuda_build": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_count": torch.cuda.device_count(),
        "torch_threads": torch.get_num_threads(), "network_guard_enabled": True,
    }
    if observed["cuda_available"]:
        observed["cuda_devices"] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    print(json.dumps(observed, ensure_ascii=True, allow_nan=False), flush=True)
elif a.action == "inference":
    entry = root / "submission/participant/run_inference.py"
    sys.argv = [str(entry), a.test, a.result, "--config", a.config,
                "--hardware-label", "local Windows CPU; independent B5 acceptance, not official GPU"]
    runpy.run_path(str(entry), run_name="__main__")
else:
    entry = root / "submission/participant/check_output.py"
    sys.argv = [str(entry), a.test, a.result]
    runpy.run_path(str(entry), run_name="__main__")
'''


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def strict_json(text: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject(_):
        raise ValueError("non-finite JSON")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=reject)
    # Also reject finite-looking numbers that overflow Python's float parser.
    json.dumps(value, ensure_ascii=True, allow_nan=False)
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def label(path: Path) -> str:
    path = path.resolve()
    for base, prefix in ((ROOT, ""), (ROOT.parent, "workspace/")):
        try:
            return prefix + path.relative_to(base).as_posix()
        except ValueError:
            pass
    return "external-read-only/" + path.name


def json_write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def history_digest(row: dict) -> str:
    projected = [{"role": item["role"], "content": item["content"]} for item in row["history"]]
    encoded = json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def checked(report: dict, name: str, condition: bool) -> None:
    report["checks"].append({"name": name, "passed": bool(condition)})
    if not condition:
        raise ValueError(name)


def verify_sources(a_source_root: Path) -> dict:
    manifest_path = ROOT.parent / "tmp/b5_20261010/prerequisite.json"
    manifest = strict_json(manifest_path.read_text(encoding="utf-8"))
    files = {}
    for entry in manifest["A_readonly_review_copies"]:
        relative = entry["path"]
        if relative.startswith("src/b2_core/") and relative.endswith(".py"):
            path = a_source_root / relative.removeprefix("src/")
            actual = sha256(path)
            if actual != entry["sha256"] or path.stat().st_size != entry["bytes"]:
                raise ValueError("pinned A source mismatch")
            files[relative] = {"sha256": actual, "bytes": path.stat().st_size}
    if "src/b2_core/model.py" not in files:
        raise ValueError("pinned A ModelEngine source missing")
    return {"source_root": label(a_source_root), "main_sha": manifest["main_sha"],
            "prerequisite_sha256": sha256(manifest_path), "files": files}


def verify_assets(config_path: Path) -> dict:
    source = config_path.parent / "asset-preparation.json"
    manifest = strict_json(source.read_text(encoding="utf-8"))
    config = strict_json(config_path.read_text(encoding="utf-8"))
    config_hash = sha256(config_path)
    if config_hash != manifest["baseline_config"]["sha256"]:
        raise ValueError("original baseline config mismatch")
    model_dir = (config_path.parent / config["model_dir"]).resolve()
    files = []
    for entry in manifest["files"]:
        path = model_dir / entry["name"]
        actual = sha256(path)
        if actual != entry["A_expected_sha256"] or path.stat().st_size != entry["A_expected_bytes"]:
            raise ValueError("local model asset checksum mismatch")
        files.append({"name": entry["name"], "sha256": actual, "bytes": path.stat().st_size})
    if len(files) != 8:
        raise ValueError("baseline must contain all eight pinned files")
    license_path = config_path.parent / config["license_file"]
    license_hash = sha256(license_path)
    if license_hash != manifest["license_copy"]["sha256"]:
        raise ValueError("local license copy mismatch")
    return {"reused_B4_assets": True, "source": manifest["source"],
            "repo_id": manifest["repo_id"], "revision": manifest["revision"],
            "config_path": label(config_path), "config_sha256": config_hash,
            "model_version": config["model_version"], "configured_device": config["device"],
            "configured_max_input_tokens": config["max_input_tokens"],
            "model_dir": label(model_dir), "files": files,
            "license_sha256": license_hash, "checked_at_utc": utc_now(),
            "sft_short_used": False, "asset_preparation_sha256": sha256(source)}


def safe_events(stdout: str, action: str) -> tuple[list[dict], int]:
    events, rejected = [], 0
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            raw = strict_json(line)
            if not isinstance(raw, dict) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", raw.get("event", "")):
                raise ValueError("not a JSON event")
            if action == "runtime" and raw["event"] == "helper_runtime":
                events.append(raw)
                continue
            if raw["event"] not in KNOWN_EVENTS:
                raise ValueError("unknown stdout event")
            event = {key: value for key, value in raw.items() if key in EVENT_KEYS}
            for key in ("trace", "parse_trace"):
                if key in event:
                    if not isinstance(event[key], dict):
                        raise ValueError("invalid trace")
                    # raw_head contains decoded model text and is deliberately excluded.
                    event[key] = {k: v for k, v in event[key].items() if k in TRACE_KEYS}
            events.append(event)
        except (ValueError, TypeError):
            rejected += 1
    return events, rejected


def run_child(python: Path, runner: Path, action: str, args, work: Path,
              test: Path | None = None, result: Path | None = None) -> dict:
    command = [str(python), "-X", "utf8", str(runner), "--action", action,
               "--root", str(ROOT), "--a-source-root", str(args.a_source_root),
               "--config", str(args.config)]
    if test is not None:
        command += ["--test", str(test), "--result", str(result)]
    env = dict(os.environ)
    env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
                "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
                "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT))),
                "HF_HOME": str(work / "cache"), "TMP": str(work / "tmp"),
                "TEMP": str(work / "tmp")})
    (work / "tmp").mkdir(exist_ok=True)
    began, started = utc_now(), time.perf_counter()
    timed_out, stdout, stderr, returncode = False, "", "", None
    child = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             encoding="utf-8", errors="replace")
    try:
        stdout, stderr = child.communicate(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        child.kill()
        stdout, stderr = child.communicate()
    finally:
        returncode = child.returncode
    events, rejected = safe_events(stdout, action)
    tag = action + ("-" + result.name if result is not None else "")
    event_path, stderr_path = work / (tag + ".events.jsonl"), work / (tag + ".stderr-safe.json")
    event_path.write_text("".join(json.dumps(event, ensure_ascii=True, allow_nan=False) + "\n" for event in events), encoding="utf-8")
    # Retain a safe log summary, never third-party stderr or exception bodies.
    categories = ("RuntimeWarning", "UserWarning", "DeprecationWarning", "FutureWarning",
                  "ModelLoadError", "GenerationError", "ContextTooLongError", "SubmissionError",
                  "RuntimeError", "ImportError", "ModuleNotFoundError", "ValueError", "TypeError",
                  "OSError", "PermissionError", "TimeoutError")
    classes = Counter({category: len(re.findall(r"\b" + category + r"\b", stderr))
                       for category in categories if re.search(r"\b" + category + r"\b", stderr)})
    stderr_summary = {"raw_text_retained": False, "nonempty_lines": sum(bool(line.strip()) for line in stderr.splitlines()),
                      "bytes_utf8": len(stderr.encode("utf-8")),
                      "sha256_utf8": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
                      "category_counts": dict(sorted(classes.items()))}
    json_write(stderr_path, stderr_summary)
    return {"action": action, "pid": child.pid, "exit_code": returncode,
            "timed_out": timed_out, "timeout_seconds": TIMEOUT_SECONDS,
            "started_at_utc": began, "finished_at_utc": utc_now(),
            "wall_seconds": round(time.perf_counter() - started, 6),
            "owned_process_stopped": child.poll() is not None,
            "events": events, "non_json_stdout_lines": rejected,
            "stdout_sha256_utf8": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
            "safe_events_path": label(event_path), "safe_stderr_path": label(stderr_path),
            "stderr": stderr_summary}


def assert_diagnostics(report: dict, run: dict, rows: list[dict], name: str, version: str) -> None:
    events = run["events"]
    ready = [event for event in events if event["event"] == "model_ready"]
    runtime = [event for event in events if event["event"] == "runtime"]
    samples = [event for event in events if event["event"] == "sample_complete"]
    complete = [event for event in events if event["event"] == "batch_complete"]
    checked(report, name + "_safe_json_stdout", run["non_json_stdout_lines"] == 0)
    checked(report, name + "_one_real_engine", len(ready) == 1 and ready[0].get("initializations") == 1
            and ready[0].get("is_mock") is False and ready[0].get("model_version") == version)
    checked(report, name + "_actual_engine_CPU_device", len(runtime) == 1 and runtime[0].get("device") == "cpu"
            and runtime[0].get("cuda_available") is False and runtime[0].get("is_mock") is False
            and runtime[0].get("model_version") == version)
    checked(report, name + "_batch_complete", len(complete) == 1 and complete[0].get("samples") == len(rows)
            and complete[0].get("rounds") == len(rows) and complete[0].get("complete") is False)
    checked(report, name + "_sample_diagnostic_count", len(samples) == len(rows))
    for index, (event, row) in enumerate(zip(samples, rows), 1):
        sample_id = event.get("sample_id", event.get("id"))
        prefix = name + "_sample_" + str(index)
        checked(report, prefix + "_full_history_once", sample_id == row["id"]
                and event.get("history_messages") == len(row["history"])
                and event.get("history_sha256") == history_digest(row)
                and event.get("index") == index)
        checked(report, prefix + "_fresh_empty_store_closed", event.get("fresh_store_created") is True
                and event.get("fresh_store_closed") is True and event.get("memory_context_empty") is True)
        trace = {key: value for key, value in event.items() if key in TRACE_KEYS}
        checked(report, prefix + "_truthful_parse_trace", isinstance(trace, dict)
                and trace.get("mode") in ("json", "json_retry", "fallback_rules")
                and trace.get("emotion_source") in ("model", "rules")
                and trace.get("profile_source") in ("model", "rules")
                and trace.get("response_source") == "model"
                and type(trace.get("parse_failures")) is int and trace["parse_failures"] >= 0
                and type(trace.get("parse_failed")) is bool
                and trace.get("schema_valid") is True)
        # A trace may report parse_failed=false after a retry or for empty JSON;
        # mode and each field's source are retained rather than inferred from it.


def read_outputs(report: dict, result: Path, rows: list[dict], name: str) -> tuple[list[dict], dict]:
    submission = result / "submission.jsonl"
    performance = result / "performance_report.json"
    predictions = [strict_json(line) for line in submission.read_text(encoding="utf-8").split("\n") if line]
    perf = strict_json(performance.read_text(encoding="utf-8"))
    checked(report, name + "_ids_count_and_order", [row.get("id") for row in predictions] == [row["id"] for row in rows])
    checked(report, name + "_all_real_nonempty_successes", all(isinstance(row.get("response_text"), str)
            and row["response_text"].strip() and row.get("emotion_label") and row.get("memory_refs") == []
            and set(row) == {"id", "response_text", "emotion_label", "user_profile", "memory_refs"}
            for row in predictions))
    checked(report, name + "_short_sample_timing_boundary", perf.get("samples") == len(rows)
            and perf.get("required_rounds") == 100 and perf.get("rounds") == len(rows)
            and perf.get("complete") is False and len(perf.get("latencies_ms", [])) == len(rows))
    checked(report, name + "_submission_digest", perf.get("submission_sha256") == sha256(submission))
    metadata = {"input_ids": [row["id"] for row in rows], "output_ids": [row["id"] for row in predictions],
                "submission_path": label(submission), "submission_sha256": sha256(submission),
                "performance_path": label(performance), "performance_sha256": sha256(performance),
                "performance": {key: value for key, value in perf.items() if key in PERFORMANCE_KEYS}}
    return predictions, metadata


def main(args) -> int:
    args.python, args.a_source_root, args.config = (Path(value).resolve() for value in (args.python, args.a_source_root, args.config))
    work, report_path = Path(args.work_dir).resolve(), Path(args.report).resolve()
    # This helper has no reason to touch a previous B4 report or another area.
    work.relative_to((INTEGRATION / ".b5-work").resolve())
    report_path.relative_to(INTEGRATION.resolve())
    if report_path.name.lower().startswith("b4") or report_path == Path(__file__).resolve():
        raise ValueError("report must not overwrite B4 artifacts or the helper")
    report = {"started_at_utc": utc_now(), "passed": False, "checks": [], "runs": {},
              "python_path": label(args.python), "work_dir": label(work),
              "model_inference_verified": False, "real_generation_performed": False,
              "raw_input_or_model_text_in_public_report": False, "protocol_fixture_only": False,
              "training_performed": False, "gpu_coupon_used": False,
              "official_container_verified": False, "official_gpu_verified": False,
              "platform_submission_performed": False,
              "scope": "B5 actual Windows CPU public-sample CLI; B6 Linux/conda/container/GPU not executed"}
    original = ROOT / "submission/official-reference/test_inference_data.jsonl"
    original_hash = None
    try:
        work.mkdir(parents=True, exist_ok=False)
        checked(report, "runtime_python_exists", args.python.is_file())
        for name in ("run_inference.py", "check_output.py"):
            checked(report, "production_" + name + "_exists", (ROOT / "submission/participant" / name).is_file())
        report["A_source"] = verify_sources(args.a_source_root)
        checked(report, "fixed_A_sources_match_prerequisite", True)
        report["assets"] = verify_assets(args.config)
        checked(report, "original_baseline_config_eight_assets_and_license_match", True)
        original_bytes = original.read_bytes()
        original_hash = hashlib.sha256(original_bytes).hexdigest()
        lines = [line for line in original_bytes.decode("utf-8-sig").split("\n") if line.strip()]
        rows = [strict_json(line) for line in lines]
        checked(report, "exactly_three_official_public_samples", len(rows) == 3)
        main_input = work / "official-original-copy.jsonl"
        main_input.write_bytes(original_bytes)
        reverse_input = work / "first-third-reversed.jsonl"
        reverse_rows = [rows[2], rows[0]]
        reverse_input.write_text(lines[2] + "\n" + lines[0] + "\n", encoding="utf-8")
        report["inputs"] = {"official_source": label(original), "official_source_sha256": original_hash,
                            "original_copy_sha256": sha256(main_input), "reverse_sha256": sha256(reverse_input),
                            "original_ids": [row["id"] for row in rows], "reverse_ids": [row["id"] for row in reverse_rows],
                            "history_counts": [len(row["history"]) for row in rows],
                            "history_sha256": [history_digest(row) for row in rows]}
        runner = work / "child_runner.py"
        runner.write_text(CHILD_RUNNER, encoding="utf-8")
        report["child_runner_sha256"] = sha256(runner)
        runtime = run_child(args.python, runner, "runtime", args, work)
        report["runs"]["runtime"] = runtime
        checked(report, "actual_runtime_metadata_process", runtime["exit_code"] == 0 and not runtime["timed_out"]
                and runtime["non_json_stdout_lines"] == 0 and len(runtime["events"]) == 1)
        report["runtime"] = runtime["events"][0]
        checked(report, "actual_runtime_is_CPU", report["runtime"].get("torch_cuda_build") is None
                and report["runtime"].get("cuda_available") is False)
        candidates = {}
        for name, input_path, input_rows in (("original", main_input, rows), ("reversed", reverse_input, reverse_rows)):
            result = work / (name + "-result")
            # Each call starts its own real process and the CLI owns this new result directory.
            run = run_child(args.python, runner, "inference", args, work, input_path, result)
            report["runs"][name] = run
            checked(report, name + "_CLI_exit_zero", run["exit_code"] == 0 and not run["timed_out"])
            assert_diagnostics(report, run, input_rows, name, report["assets"]["model_version"])
            checker = run_child(args.python, runner, "check", args, work, input_path, result)
            report["runs"][name + "_independent_check"] = checker
            checked(report, name + "_independent_check_exit_zero", checker["exit_code"] == 0
                    and not checker["timed_out"] and checker["non_json_stdout_lines"] == 0)
            valid_events = [event for event in checker["events"] if event["event"] == "output_valid"]
            checked(report, name + "_independent_check_confirms_samples", len(valid_events) == 1
                    and valid_events[0].get("samples") == len(input_rows))
            predictions, metadata = read_outputs(report, result, input_rows, name)
            checked(report, name + "_input_hash_in_performance", metadata["performance"].get("test_file_sha256") == sha256(input_path))
            sample_events = [event for event in run["events"] if event["event"] == "sample_complete"]
            expected_parse_ids = [event["id"] for event in sample_events if event["parse_failures"] > 0]
            checked(report, name + "_parse_failures_match_actual_trace", metadata["performance"].get("parse_failure_ids") == expected_parse_ids
                    and metadata["performance"].get("parse_failure_count") == len(expected_parse_ids))
            metadata["parse_trace_by_id"] = {event["id"]: {key: value for key, value in event.items()
                    if key in TRACE_KEYS} for event in sample_events}
            report[name + "_candidate"] = metadata
            candidates[name] = {row["id"]: row for row in predictions}
        # Process IDs can eventually be reused by the OS. Each run_child call
        # starts a new process and waits for its termination before this next run.
        checked(report, "separate_inference_processes", report["runs"]["original"]["owned_process_stopped"]
                and report["runs"]["reversed"]["owned_process_stopped"]
                and report["runs"]["original"]["started_at_utc"] != report["runs"]["reversed"]["started_at_utc"])
        equality = {sample_id: candidates["original"][sample_id] == candidates["reversed"][sample_id]
                    for sample_id in report["inputs"]["reverse_ids"]}
        report["reverse_comparison"] = {"comparison": "complete prediction dictionaries, by unchanged ID",
                                        "equal_by_id": equality, "raw_predictions_in_report": False}
        checked(report, "first_and_third_predictions_equal_in_reversed_fresh_process", all(equality.values()))
        report["model_inference_verified"] = True
        report["passed"] = True
    except Exception as exc:
        # A failure reason is a fixed helper check name or exception category;
        # never include model exception text, stdout, stderr, or raw JSON rows.
        report["error_type"] = type(exc).__name__
        failed = [check["name"] for check in report["checks"] if not check["passed"]]
        report["failed_check"] = failed[-1] if failed else "preparation_or_result_read_failed"
    finally:
        report["official_input_unchanged"] = original_hash is not None and original.is_file() and sha256(original) == original_hash
        if not report["official_input_unchanged"]:
            report["passed"] = False
        report["successful_sample_events"] = sum(event.get("event") == "sample_complete"
                for run in report["runs"].values() if run["action"] == "inference" for event in run["events"])
        report["real_generation_performed"] = report["successful_sample_events"] > 0
        report["all_owned_processes_stopped"] = all(run["owned_process_stopped"] for run in report["runs"].values())
        # Preserve and identify any published candidate even if a later metadata
        # check failed; never delete or overwrite it as part of this probe.
        report["retained_candidate_files"] = [{"path": label(path), "sha256": sha256(path), "bytes": path.stat().st_size}
                for name in ("original-result", "reversed-result")
                for filename in ("submission.jsonl", "performance_report.json")
                if (path := work / name / filename).is_file()]
        report["checks_passed"] = sum(check["passed"] for check in report["checks"])
        report["checks_total"] = len(report["checks"])
        report["finished_at_utc"] = utc_now()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        json_write(report_path, report)
    print(json.dumps({"report": label(report_path), "passed": report["passed"],
                      "checks_passed": report["checks_passed"], "checks_total": report["checks_total"],
                      "failed_check": report.get("failed_check")}, ensure_ascii=True, allow_nan=False))
    return 0 if report["passed"] else 1


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=str(ROOT / ".runtime/b4-real-env/Scripts/python.exe"))
    parser.add_argument("--a-source-root", default=str(ROOT.parent / "tmp/b5_20261010/upstream-A/src"))
    parser.add_argument("--config", default=str(INTEGRATION / ".b4-work/real-assets/inference_config.base.json"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parser.add_argument("--work-dir", default=str(INTEGRATION / ".b5-work" / ("real-" + stamp + "-" + uuid4().hex[:8])))
    parser.add_argument("--report", default=str(INTEGRATION / "b5-real-offline.json"))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main(parse_args()))
