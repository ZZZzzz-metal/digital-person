"""B0 protocol checks and safe startup probes; never generates predictions.

Only runs the reference CLI's missing-model path. Shell startup is probed only
when neither conda nor an activate script is found. Full inference belongs to
the later model/GPU acceptance step.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "submission/official-reference"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "contracts/official/source-manifest.json").read_text(encoding="utf-8"))
    snapshots = []
    for item in manifest["copies"]:
        raw = (ROOT / item["path"]).read_bytes()
        matches = len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"]
        snapshots.append({"path": item["path"], "sha256_matches": matches})
    if not all(item["sha256_matches"] for item in snapshots):
        raise RuntimeError("Reference snapshot changed; refusing to execute it")

    script = REFERENCE / "participant/run_inference.py"
    spec = importlib.util.spec_from_file_location("b0_official_reference", script)
    reference = importlib.util.module_from_spec(spec)
    previous_bytecode_setting = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(reference)
    finally:
        sys.dont_write_bytecode = previous_bytecode_setting
    rows = reference.read_jsonl(REFERENCE / "test_inference_data.jsonl")
    schema = json.loads((ROOT / "contracts/official/submission.schema.json").read_text(encoding="utf-8"))
    pattern = schema["properties"]["id"]["pattern"]
    ids = [row["id"] for row in rows]
    id_matches = [bool(re.fullmatch(pattern, identifier)) for identifier in ids]
    versions = {}
    for name in ("torch", "transformers", "accelerate", "vllm", "jsonschema"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None

    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("EVALUATION_", "VLLM_"))}
    environment.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                        "PYTHONIOENCODING": "utf-8"})
    def portable(text, temporary):
        for original, label in ((str(temporary), "<TEMP_RESULT>"),
                                (str(ROOT.parent), "<WORKSPACE>"),
                                (str(Path(sys.executable).parent), "<PYTHON_RUNTIME>"),
                                (str(temporary), "<TEMP_RESULT>")):
            text = text.replace(original, label).replace(original.replace("\\", "/"), label)
        return text

    probes = {}
    scratch = (ROOT / "reports/integration/.b0-work").resolve()
    if not scratch.is_relative_to(ROOT):
        raise ValueError("Scratch directory is outside the project")
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="b2-b0-probe-", dir=scratch) as name:
        temporary = Path(name).resolve()
        if not temporary.is_relative_to(scratch):
            raise ValueError("Temporary cleanup target is outside the checked scratch directory")
        empty = temporary / "empty.jsonl"
        duplicate = temporary / "duplicate.jsonl"
        empty.write_text("\n", encoding="utf-8")
        duplicate.write_text('{"id":"fixture-1","history":[]}\n' * 2, encoding="utf-8")
        for label, path, expected in (("empty_input", empty, "测试文件为空"),
                                      ("duplicate_ids", duplicate, "重复 id")):
            try:
                reference.read_jsonl(path)
            except ValueError as error:
                message = portable(str(error), temporary)
                probes[label] = {"expected_error_observed": expected in message, "message": message}
            else:
                probes[label] = {"expected_error_observed": False}

        config = json.loads((REFERENCE / "participant/configs/inference_config.json").read_text(encoding="utf-8"))
        model = REFERENCE / "participant" / config["model_path"]
        if config["backend"] != "transformers" or model.exists():
            probes["python_missing_model"] = {"status": "skipped", "reason": "Not the unchanged missing-model configuration"}
        else:
            output = temporary / "python-result"
            completed = subprocess.run([sys.executable, "-B", "-X", "utf8", str(script),
                str(REFERENCE / "test_inference_data.jsonl"), str(output)], cwd=ROOT,
                env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
            probes["python_missing_model"] = {
                "command": "python submission/official-reference/participant/run_inference.py submission/official-reference/test_inference_data.jsonl <TEMP_RESULT>",
                "exit_code": completed.returncode,
                "expected_error_observed": completed.returncode != 0 and "本地模型目录不存在" in completed.stderr,
                "stdout": portable(completed.stdout, temporary), "stderr": portable(completed.stderr, temporary),
                "submission_created": (output / "submission.jsonl").exists(),
                "performance_report_created": (output / "performance_report.json").exists(),
            }

        bash = shutil.which("bash")
        if not bash and Path("C:/Program Files/Git/bin/bash.exe").is_file():
            bash = "C:/Program Files/Git/bin/bash.exe"
        # Avoid running a model if an unexpected activation script is available.
        if bash and not shutil.which("conda") and not shutil.which("activate") and not (ROOT / "activate").exists():
            output = temporary / "bash-result"
            completed = subprocess.run([bash, "--noprofile", "--norc",
                (REFERENCE / "participant/start.sh").as_posix(),
                (REFERENCE / "test_inference_data.jsonl").as_posix(), output.as_posix()],
                cwd=ROOT, env=environment, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30)
            probes["shell_missing_environment"] = {
                "command": "bash submission/official-reference/participant/start.sh submission/official-reference/test_inference_data.jsonl <TEMP_RESULT>",
                "runtime": "Git Bash on Windows" if os.name == "nt" else "local Bash",
                "exit_code": completed.returncode,
                "expected_error_observed": completed.returncode != 0 and "activate" in completed.stderr,
                "stdout": portable(completed.stdout, temporary), "stderr": portable(completed.stderr, temporary),
                "submission_created": (output / "submission.jsonl").exists(),
                "performance_report_created": (output / "performance_report.json").exists(),
                "official_linux_container_validation": False,
            }
        else:
            probes["shell_missing_environment"] = {"status": "skipped", "reason": "No Bash, or activation might succeed; no full inference requested"}

    predictions_generated = any(probe.get("submission_created", False) for probe in probes.values())
    performance_report_generated = any(probe.get("performance_report_created", False) for probe in probes.values())
    checks_ok = (all(probe.get("expected_error_observed", True) for probe in probes.values())
                 and not predictions_generated and not performance_report_generated)
    report = {
        "checked_at_beijing": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "scope": "B0 reference bytes, input reader and missing-resource startup paths; no model inference",
        "reference_files": snapshots, "python_version": sys.version.split()[0],
        "installed_package_versions": versions,
        "inference_sample": {"rows": len(rows), "unique_ids": len(set(ids)),
                             "ids": ids, "ids_matching_output_schema": sum(id_matches),
                             "schema_pattern": pattern},
        "probes": probes, "protocol_probes_as_expected": checks_ok,
        "predictions_generated": predictions_generated,
        "performance_report_generated": performance_report_generated,
        "model_inference_verified": False,
        "official_container_verified": False, "official_submission_ready": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"reference_hashes_match": True, "samples_read": len(rows),
                      "ids_matching_output_schema": sum(id_matches),
                      "startup_exit_codes": {key: value.get("exit_code") for key, value in probes.items() if "exit_code" in value},
                      "protocol_probes_as_expected": checks_ok,
                      "predictions_generated": predictions_generated,
                      "performance_report_generated": performance_report_generated,
                      "official_submission_ready": False}, ensure_ascii=False))
    return 0 if checks_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
