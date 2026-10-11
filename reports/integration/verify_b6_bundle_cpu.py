"""Run one original public sample from the independent B6 bundle on real CPU.

No downloads or installations. This is a CPU packaging smoke, not Docker/GPU or
official competition acceptance. Chat input/output stays in the new work folder;
the repository report stores only safe runtime metadata, checks and digests.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


PROJECT = Path(__file__).resolve().parents[2]
EXPECTED_MANIFEST = "c384dfbaa3b1e51558afb7db64e0628f778a4e157825f7a69a3f8b76de3150ca"
EXPECTED_CODE = "a34f8df7bd089f5d975c2ec1d0760bb4cb6ce394"
EXPECTED_MODEL = "b2-a-qwen2.5-0.5b-instruct-base-v1"
EXPECTED_OFFICIAL_INPUT = "194f824a70fcc5a73e05e818eb0968045c165edc0cdf31e197d135103b910ebd"
EVENT_FIELDS = {
    "runtime": ("device", "torch_version", "cuda_available", "model_version", "is_mock"),
    "model_ready": ("is_mock", "model_version", "initializations"),
    "sample_complete": ("index", "id", "history_messages", "history_sha256", "memory_context_empty",
                        "fresh_store_created", "fresh_store_closed", "elapsed_ms", "mode", "parse_failures",
                        "parse_failed", "emotion_source", "profile_source", "response_source", "prompt_tokens",
                        "new_tokens", "dropped_turns", "schema_valid"),
    "batch_complete": ("samples", "rounds", "complete", "result_dir"),
    "output_valid": ("samples", "sha256", "rounds", "complete"),
    "batch_failed": ("code", "exception_type"),
    "output_invalid": ("code", "exception_type"),
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_process(command: list[str], cwd: Path, env: dict[str, str], timeout: float) -> dict:
    started = time.perf_counter()
    process = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=timeout, check=False)
    events, unknown_json, non_json = [], 0, 0
    for line in process.stdout.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            non_json += 1
            continue
        if not isinstance(value, dict) or value.get("event") not in EVENT_FIELDS:
            unknown_json += 1
            continue
        kind = value["event"]
        events.append({"event": kind, **{key: value[key] for key in EVENT_FIELDS[kind] if key in value}})
    return {
        "command": command, "cwd": str(cwd), "exit_code": process.returncode,
        "duration_ms": round((time.perf_counter() - started) * 1000, 6), "events": events,
        "non_json_stdout_lines": non_json, "unknown_json_stdout_lines": unknown_json,
        "stdout_bytes": len(process.stdout), "stdout_sha256": hashlib.sha256(process.stdout).hexdigest(),
        "stderr_bytes": len(process.stderr), "stderr_sha256": hashlib.sha256(process.stderr).hexdigest(),
        "raw_stdout_or_stderr_saved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=PROJECT / ".runtime/b4-real-env/Scripts/python.exe")
    parser.add_argument("--report", type=Path, default=PROJECT / "reports/integration/b6-bundle-cpu-smoke.json")
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()
    bundle, work, python, report_path = (path.resolve() for path in (args.bundle, args.work, args.python, args.report))
    if work.exists() or report_path.exists():
        raise FileExistsError("CPU smoke work/report must be new; nothing was overwritten")
    if not report_path.is_relative_to(PROJECT / "reports/integration"):
        raise ValueError("The safe report must stay in this project's reports/integration directory")
    report = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(), "scope": "B6 independent bundle, one real public sample on Windows CPU",
        "passed": False, "docker_run": False, "gpu_verified": False, "official_score_verified": False,
        "competition_submitted": False, "model_training_performed": False,
        "bundle_path": str(bundle), "work_path": str(work), "checks": [], "processes": {},
        "cpu_runtime_reused_without_installation": str(python), "chat_body_in_report": False,
    }

    def check(name: str, passed: bool) -> None:
        report["checks"].append({"name": name, "passed": bool(passed)})
        if not passed:
            raise RuntimeError("A CPU bundle smoke check failed: " + name)

    spec = importlib.util.spec_from_file_location("b6_bundle_cpu_verifier", PROJECT / "deploy/prepare_bundle.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    source = PROJECT / "submission/official-reference/test_inference_data.jsonl"
    input_original_sha = None
    started = time.perf_counter()
    try:
        before = verifier.verify_bundle(bundle)
        report["bundle_before"] = before
        check("all_30_bundle_files_verified_before_run", before["verified"] is True and before["file_count"] == 30)
        check("manifest_matches_fixed_candidate", before["manifest_sha256"] == EXPECTED_MANIFEST)
        check("candidate_code_commit_matches", before["code_commit"] == EXPECTED_CODE)
        check("candidate_model_version_matches", before["model_version"] == EXPECTED_MODEL)
        check("existing_real_cpu_python_available", python.is_file())
        input_original_sha = sha(source)
        report["original_official_file_sha256"] = input_original_sha
        check("official_source_unchanged_since_B5", input_original_sha == EXPECTED_OFFICIAL_INPUT)
        first_line = next(line for line in source.read_bytes().splitlines(keepends=True) if line.strip())
        original_sample = json.loads(first_line)
        work.mkdir()
        temp = work / "temp"
        temp.mkdir()
        input_path, result_dir = work / "input.jsonl", work / "result"
        with input_path.open("xb") as stream:
            stream.write(first_line)
        input_sha = sha(input_path)
        report["input"] = {"path": str(input_path), "sha256": input_sha, "samples": 1,
                           "id": original_sample["id"], "history_messages": len(original_sample["history"])}
        check("one_original_sample_bytes_copied_without_edits", input_path.read_bytes() == first_line)
        env = os.environ.copy()
        env.update(PYTHONPATH=str(bundle / "src"), PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1",
                   TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", CUDA_VISIBLE_DEVICES="",
                   B2_OFFICIAL_MODEL_CONFIG=str(bundle / before["config_path"]), TEMP=str(temp), TMP=str(temp))
        report["child_environment_overrides"] = {key: env[key] for key in (
            "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
            "HF_HUB_DISABLE_TELEMETRY", "CUDA_VISIBLE_DEVICES", "B2_OFFICIAL_MODEL_CONFIG")}
        inference = safe_process([
            str(python), "-B", str(bundle / "run_inference.py"), str(input_path), str(result_dir),
            "--config", str(bundle / before["config_path"]), "--hardware-label",
            "local Windows CPU; B6 independent-bundle smoke only, not Docker/GPU acceptance",
        ], work, env, args.timeout)
        report["processes"]["inference"] = inference
        check("real_bundle_inference_exit_zero", inference["exit_code"] == 0)
        groups = {kind: [event for event in inference["events"] if event["event"] == kind]
                  for kind in ("runtime", "model_ready", "sample_complete", "batch_complete")}
        for kind, values in groups.items():
            check("exactly_one_" + kind + "_event", len(values) == 1)
        runtime, ready, sample, batch = (groups[kind][0] for kind in ("runtime", "model_ready", "sample_complete", "batch_complete"))
        check("runtime_is_actual_cpu_without_cuda", runtime.get("device") == "cpu" and runtime.get("cuda_available") is False)
        check("runtime_is_real_bundled_model", runtime.get("is_mock") is False and runtime.get("model_version") == EXPECTED_MODEL)
        check("model_initialized_once_with_expected_real_identity", ready.get("initializations") == 1 and ready.get("is_mock") is False and ready.get("model_version") == EXPECTED_MODEL)
        check("sample_keeps_original_id_and_full_history_once", sample.get("id") == original_sample["id"] and sample.get("history_messages") == len(original_sample["history"]))
        history_json = json.dumps([{"role": item["role"], "content": item["content"]} for item in original_sample["history"]],
                                  ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        check("sample_original_history_digest_matches", sample.get("history_sha256") == hashlib.sha256(history_json.encode("utf-8")).hexdigest())
        check("sample_has_empty_memory_and_fresh_closed_store", sample.get("memory_context_empty") is True and sample.get("fresh_store_created") is True and sample.get("fresh_store_closed") is True)
        check("sample_response_is_real_model_and_schema_valid", sample.get("response_source") == "model" and sample.get("schema_valid") is True)
        check("batch_has_one_sample_one_round_complete_false", batch.get("samples") == 1 and batch.get("rounds") == 1 and batch.get("complete") is False)
        checker = safe_process([str(python), "-B", str(bundle / "check_output.py"), str(input_path), str(result_dir)], work, env, args.timeout)
        report["processes"]["checker"] = checker
        check("independent_bundle_checker_exit_zero", checker["exit_code"] == 0)
        checked = [event for event in checker["events"] if event["event"] == "output_valid"]
        check("independent_checker_confirms_one_output", len(checked) == 1 and checked[0].get("samples") == 1 and checked[0].get("rounds") == 1 and checked[0].get("complete") is False)
        check("result_contains_only_two_success_files", {path.name for path in result_dir.iterdir()} == {"submission.jsonl", "performance_report.json"})
        outputs = {name: {"path": str(result_dir / name), "sha256": sha(result_dir / name), "bytes": (result_dir / name).stat().st_size}
                   for name in ("submission.jsonl", "performance_report.json")}
        report["outputs"] = outputs
        perf = json.loads((result_dir / "performance_report.json").read_text(encoding="utf-8"))
        report["performance"] = perf
        check("output_and_input_digests_bind_to_performance", perf.get("submission_sha256") == outputs["submission.jsonl"]["sha256"] == checked[0].get("sha256") and perf.get("test_file_sha256") == input_sha)
        check("performance_matches_bundled_model", perf.get("model_version") == EXPECTED_MODEL)
        check("performance_truthfully_records_one_not_100", perf.get("samples") == 1 and perf.get("rounds") == 1 and perf.get("required_rounds") == 100 and perf.get("complete") is False)
        check("original_test_copy_unchanged", sha(input_path) == input_sha)
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
        if getattr(exc, "code", None):
            report["failure_code"] = exc.code
        report["failure"] = "See failed check name; raw exception/model/chat text is not stored"
    finally:
        try:
            after = verifier.verify_bundle(bundle)
            report["bundle_after"] = after
            check("all_30_bundle_files_verified_after_run", after["verified"] is True and after["file_count"] == 30)
            check("bundle_manifest_and_source_identity_unchanged", after["manifest_sha256"] == EXPECTED_MANIFEST and after == report.get("bundle_before"))
            if input_original_sha is not None:
                check("original_official_file_not_modified", sha(source) == input_original_sha)
        except Exception as exc:
            report["post_verification_failure_type"] = type(exc).__name__
        report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        report["checks_passed"] = sum(item["passed"] for item in report["checks"])
        report["checks_total"] = len(report["checks"])
        report["passed"] = ("failure_type" not in report and "post_verification_failure_type" not in report
                            and report["checks_passed"] == report["checks_total"])
        with report_path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=True, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps({"passed": report["passed"], "checks_passed": report["checks_passed"],
                      "checks_total": report["checks_total"], "report": str(report_path),
                      "docker_run": False, "gpu_verified": False}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
