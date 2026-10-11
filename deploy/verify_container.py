"""Build and verify the B6 candidate. Never infer GPU success from preparation.

Requires a working Linux Docker daemon with NVIDIA GPU support. Only containers
created by this invocation are removed; images and successful results remain.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import uuid

from prepare_bundle import verify_bundle

LIMIT_BYTES = 50_000_000_000  # Team budget, not a clarification of official 50G.
DEPLOY = Path(__file__).resolve().parent
PYTHON = "/opt/conda/envs/conda_env/bin/python"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def execute(args: list[str], log: Path | None = None) -> str:
    if log is None:
        r = subprocess.run(args, capture_output=True, text=True, check=False)
        if r.returncode:
            raise RuntimeError(f"Command failed ({r.returncode}): {args[0:2]}")
        return r.stdout
    with log.open("xb") as stream:
        r = subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if r.returncode:
        raise RuntimeError(f"Command failed ({r.returncode}); see {log.name}")
    return ""


def inspect(kind: str, identity: str) -> dict:
    records = json.loads(execute(["docker", kind, "inspect", identity]))
    if len(records) != 1:
        raise RuntimeError("Ambiguous Docker inspect result")
    return records[0]


def validate_container(info: dict, image_id: str, gpu: bool) -> dict:
    host = info["HostConfig"]
    if info["Image"] != image_id or host["NetworkMode"] != "none":
        raise RuntimeError("Image identity or OS network isolation mismatch")
    requests = host.get("DeviceRequests") or []
    if gpu and not any("gpu" in caps for r in requests for caps in r.get("Capabilities", [])):
        raise RuntimeError("Container was not created with GPU access")
    state = info["State"]
    if state["Running"] or state["ExitCode"] != 0:
        raise RuntimeError("Container did not finish successfully")
    return {"image_id": info["Image"], "network_mode": host["NetworkMode"],
            "device_requests": requests, "exit_code": state["ExitCode"],
            "started_at": state["StartedAt"], "finished_at": state["FinishedAt"]}


def mount(path: Path, target: str, readonly: bool = False) -> list[str]:
    if "," in str(path):
        raise ValueError("Docker mount paths containing commas are unsupported")
    return ["--mount", f"type=bind,source={path.resolve()},target={target}" + (",readonly" if readonly else "")]


def validate_inference_events(log: Path, model_version: str, performance: dict) -> dict:
    events = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and "event" in item:
            events.append(item)
    runtime = [e for e in events if e["event"] == "runtime"]
    ready = [e for e in events if e["event"] == "model_ready"]
    batches = [e for e in events if e["event"] == "batch_complete"]
    samples = [e for e in events if e["event"] == "sample_complete"]
    if len(runtime) != 1 or len(ready) != 1 or len(batches) != 1:
        raise RuntimeError("Missing or ambiguous actual model process events")
    actual = runtime[0]
    if (actual.get("device") != "cuda" or actual.get("cuda_available") is not True
            or actual.get("is_mock") is not False or actual.get("model_version") != model_version):
        raise RuntimeError("Inference process did not report the real bundled model on CUDA")
    if (ready[0].get("initializations") != 1 or ready[0].get("is_mock") is not False
            or ready[0].get("model_version") != model_version):
        raise RuntimeError("Model initialization identity mismatch")
    if (len(samples) != performance["samples"]
            or batches[0].get("samples") != performance["samples"]
            or batches[0].get("rounds") != performance["rounds"]
            or batches[0].get("complete") is not performance["complete"]):
        raise RuntimeError("Model events do not cover the validated complete input")
    if any(e.get("schema_valid") is not True or e.get("fresh_store_closed") is not True
           or e.get("response_source") != "model" for e in samples):
        raise RuntimeError("Sample did not record a validated actual model prediction")
    return {"runtime": actual, "model_ready": ready[0], "batch_complete": batches[0], "sample_events": len(samples)}


def run_container(image_id: str, command: list[str], mounts: list[str], work: Path,
                  name: str, *, gpu: bool = False, entrypoint: str | None = None) -> dict:
    args = ["docker", "container", "create", "--name", "b2-b6-" + uuid.uuid4().hex,
            "--network", "none"]
    if gpu:
        args += ["--gpus", "all"]
    if entrypoint:
        args += ["--entrypoint", entrypoint]
    args += mounts + [image_id] + command
    cid = execute(args).strip()
    if not cid or any(c not in "0123456789abcdef" for c in cid):
        raise RuntimeError("Docker did not return a valid new container ID")
    try:
        log = work / (name + ".log")
        failure = None
        try:
            execute(["docker", "container", "start", "--attach", cid], log)
        except (Exception, KeyboardInterrupt) as exc:
            failure = exc
            subprocess.run(["docker", "container", "stop", "--time", "10", cid],
                           capture_output=True, check=False, timeout=20)
        info = inspect("container", cid)
        evidence = {"container_id": cid, "create_command": args,
                    "image_id": info["Image"], "network_mode": info["HostConfig"]["NetworkMode"],
                    "device_requests": info["HostConfig"].get("DeviceRequests"),
                    "state": info["State"], "log_sha256": sha(log)}
        (work / (name + "-inspect.json")).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        if failure:
            raise failure
        return {**validate_container(info, image_id, gpu), "container_id": cid,
                "log_sha256": evidence["log_sha256"], "create_command": args}
    finally:
        # No broad prune, daemon reset, image deletion or foreign resource stop.
        cleanup = {"container_id": cid, "removed": False, "timed_out": False}
        try:
            removed = subprocess.run(["docker", "container", "rm", "--force", cid],
                                     capture_output=True, check=False, timeout=20)
            cleanup.update(exit_code=removed.returncode, removed=removed.returncode == 0)
        except subprocess.TimeoutExpired:
            cleanup["timed_out"] = True
        finally:
            (work / (name + "-cleanup.json")).write_text(json.dumps(cleanup, indent=2) + "\n", encoding="utf-8")
        if not cleanup["removed"]:
            raise RuntimeError("Own container cleanup failed; see " + name + "-cleanup.json")


def prepare_context(bundle: Path, context: Path) -> dict:
    checked = verify_bundle(bundle)
    if context.exists():
        raise FileExistsError("Build context must be a new directory")
    context.mkdir()
    shutil.copytree(bundle, context / "participant")
    tools = context / "tools"
    tools.mkdir()
    for name in ("prepare_bundle.py", "runtime_probe.py", "bundle_manifest.schema.json"):
        shutil.copy2(DEPLOY / name, tools / name)
    for name in ("Dockerfile", "requirements-gpu.txt", ".dockerignore"):
        shutil.copy2(DEPLOY / name, context / name)
    # Recheck the actual bytes copied into the build context.
    return verify_bundle(context / "participant")


def run(args) -> dict:
    if args.work.exists():
        raise FileExistsError("Evidence directory must be new")
    args.work.mkdir(parents=True)
    report = {"started_at_utc": datetime.now(timezone.utc).isoformat(),
              "image_built": False, "gpu_offline_verified": False, "fallback_image_verified": False,
              "official_score_verified": False, "contest_submitted": False,
              "image_id": None, "repo_digests": [], "save_tar_sha256": None,
              "team_size_limit_bytes": LIMIT_BYTES, "runs": {}}
    started = time.perf_counter()
    try:
        if shutil.which("docker") is None:
            raise RuntimeError("Docker CLI is missing; requires Linux Docker + NVIDIA GPU access")
        daemon = json.loads(execute(["docker", "info", "--format", "{{json .}}"] ))
        if daemon.get("OSType") != "linux":
            raise RuntimeError("A Linux Docker daemon is required")
        report["docker_server"] = {k: daemon.get(k) for k in ("ServerVersion", "OSType", "Architecture")}
        checked = prepare_context(args.bundle, args.work / "context")
        report["bundle"] = checked
        iid_file = args.work / "image-id.txt"
        execute(["docker", "build", "--iidfile", str(iid_file), "--tag", args.tag,
                 str(args.work / "context")], args.work / "build.log")
        iid = iid_file.read_text().strip()
        image = inspect("image", iid)
        if image["Id"] != iid or not iid.startswith("sha256:"):
            raise RuntimeError("Built image ID mismatch")
        report.update(image_built=True, image_id=iid, repo_digests=image.get("RepoDigests") or [],
                      image_size_bytes=image["Size"])
        if image["Size"] >= LIMIT_BYTES:
            raise RuntimeError("Image exceeds the team size budget")
        # Copy immutable input: the original may change while Docker is running.
        original_sha = sha(args.test_file)
        test = args.work / "test-input.jsonl"
        shutil.copy2(args.test_file, test)
        if sha(test) != original_sha:
            raise RuntimeError("Input changed during copy")
        report["input_sha256"] = original_sha
        probe_dir = args.work / "probe"
        probe_dir.mkdir()
        report["runs"]["gpu_probe"] = run_container(iid,
            ["-c", "source activate conda_env && exec python /opt/b2-tools/runtime_probe.py /b2-probe/runtime.json"],
            mount(probe_dir, "/b2-probe"), args.work, "gpu-probe", gpu=True, entrypoint="bash")
        probe = json.loads((probe_dir / "runtime.json").read_text(encoding="utf-8"))
        if not probe.get("gpu_verified") or probe.get("device_count", 0) < 1:
            raise RuntimeError("Actual CUDA kernel execution is missing")
        if probe.get("bundle", {}).get("manifest_sha256") != checked["manifest_sha256"]:
            raise RuntimeError("Image contains a different participant bundle")
        report["runtime"] = probe
        result = args.work / "result"
        result.mkdir()
        report["runs"]["inference"] = run_container(iid, ["/b2-input.jsonl", "/b2-result"],
            mount(test, "/b2-input.jsonl", True) + mount(result, "/b2-result"),
            args.work, "inference", gpu=True)
        report["runs"]["checker"] = run_container(iid,
            ["/root/participant/check_output.py", "/b2-input.jsonl", "/b2-result"],
            mount(test, "/b2-input.jsonl", True) + mount(result, "/b2-result", True),
            args.work, "checker", entrypoint=PYTHON)
        perf = json.loads((result / "performance_report.json").read_text(encoding="utf-8"))
        if perf.get("model_version") != checked["model_version"]:
            raise RuntimeError("Output model version differs from the bundled model")
        report["inference_process"] = validate_inference_events(args.work / "inference.log", checked["model_version"], perf)
        report["result_hashes"] = {name: sha(result / name) for name in ("submission.jsonl", "performance_report.json")}
        report["performance"] = perf
        # Save the same verified image, rather than a mutable tag resolving later.
        tar = args.work / "fallback-image.tar"
        execute(["docker", "image", "save", "--output", str(tar), iid], args.work / "save.log")
        report["save_tar_bytes"] = tar.stat().st_size
        report["save_tar_sha256"] = sha(tar)
        with tarfile.open(tar, "r") as archive:
            manifests = json.load(archive.extractfile("manifest.json"))
            if len(manifests) != 1:
                raise RuntimeError("Saved image archive is ambiguous")
            config = archive.extractfile(manifests[0]["Config"]).read()
            if "sha256:" + hashlib.sha256(config).hexdigest() != iid:
                raise RuntimeError("Saved archive config differs from the verified image ID")
        report["save_tar_image_id_verified"] = True
        if report["save_tar_bytes"] >= LIMIT_BYTES:
            raise RuntimeError("Saved Docker image exceeds the team size budget")
        report.update(gpu_offline_verified=True, fallback_image_verified=True)
    except (Exception, KeyboardInterrupt) as exc:
        report["failure_type"] = type(exc).__name__
        report["failure"] = str(exc) if isinstance(exc, (RuntimeError, FileExistsError, ValueError)) else "See local command logs"
    finally:
        report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        (args.work / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--test-file", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--tag", default="b2-candidate:b6")
    args = parser.parse_args()
    report = run(args)
    print(json.dumps({k: report.get(k) for k in ("image_built", "gpu_offline_verified", "fallback_image_verified", "image_id", "failure")}))
    return 0 if report["gpu_offline_verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
