"""Inspect the image runtime and execute a small CUDA kernel on every visible GPU.

Usage: python /opt/b2-tools/runtime_probe.py /evidence/runtime.json
No model, test input, account information or general environment dump is read.
The bundle is /root/participant by default; output must be a new file outside it.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_PACKAGES = ("torch", "transformers", "accelerate", "pydantic", "jsonschema", "safetensors")


class ProbeError(ValueError):
    pass


def error_record(report: dict[str, Any], stage: str, exc: BaseException) -> None:
    report["errors"].append({"stage": stage, "type": type(exc).__name__, "message": safe_text(str(exc))[0]})


def safe_text(value: str | bytes | None) -> tuple[str, bool]:
    """pip direct-reference metadata must not disclose embedded credentials."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = value or ""
    cleaned = re.sub(r"(?i)((?:git\+)?https?|ssh)://[^\s/@]+@", r"\1://<redacted>@", text)
    cleaned = re.sub(
        r"(?i)([?&](?:access_token|token|api_key|signature|auth|password)=)[^&\s]+",
        r"\1<redacted>",
        cleaned,
    )
    return cleaned, cleaned != text


def run_pip(operation: str) -> dict[str, Any]:
    # Both commands read installed metadata. --isolated ignores user pip config
    # and environment options; neither freeze nor check fetches packages.
    command = [sys.executable, "-m", "pip", "--isolated", "--disable-pip-version-check", operation]
    if operation == "freeze":
        command.append("--all")
    started = time.perf_counter()
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
        stdout, out_redacted = safe_text(result.stdout)
        stderr, err_redacted = safe_text(result.stderr)
        return {
            "command": command,
            "exit_code": result.returncode,
            "timed_out": False,
            "duration_ms": round((time.perf_counter() - started) * 1000, 6),
            "stdout": stdout,
            "stderr": stderr,
            "credential_redaction_applied": out_redacted or err_redacted,
        }
    except subprocess.TimeoutExpired as exc:
        stdout, out_redacted = safe_text(exc.stdout)
        stderr, err_redacted = safe_text(exc.stderr)
        return {
            "command": command,
            "exit_code": None,
            "timed_out": True,
            "duration_ms": round((time.perf_counter() - started) * 1000, 6),
            "stdout": stdout,
            "stderr": stderr,
            "credential_redaction_applied": out_redacted or err_redacted,
        }


def probe_cuda(report: dict[str, Any]) -> None:
    """Force driver initialization, allocation, matmul and synchronization."""
    cuda_report: dict[str, Any] = {
        "version": None,
        "cuda_built_version": None,
        "cuda_available": False,
        "device_count": 0,
        "cuda_initialized": False,
        "devices": [],
    }
    report["torch"] = cuda_report
    try:
        import torch

        cuda_report["version"] = str(torch.__version__)
        cuda_report["cuda_built_version"] = torch.version.cuda
        cuda_report["cuda_available"] = bool(torch.cuda.is_available())
        cuda_report["device_count"] = int(torch.cuda.device_count())
        if not cuda_report["cuda_available"] or cuda_report["device_count"] < 1:
            raise ProbeError("CUDA GPU unavailable; a CPU runtime cannot pass B6 GPU checks")
        torch.cuda.init()
        cuda_report["cuda_initialized"] = True
        report["checks"]["cuda_init"] = True
    except Exception as exc:
        error_record(report, "cuda_initialization", exc)
        return

    for index in range(cuda_report["device_count"]):
        device_report: dict[str, Any] = {"index": index, "kernel_verified": False, "synchronize_succeeded": False}
        cuda_report["devices"].append(device_report)
        try:
            properties = torch.cuda.get_device_properties(index)
            device_report.update({
                "name": str(properties.name),
                "total_memory_bytes": int(properties.total_memory),
                "compute_capability": [int(properties.major), int(properties.minor)],
                "multiprocessor_count": int(properties.multi_processor_count),
            })
            with torch.cuda.device(index), torch.inference_mode():
                torch.cuda.synchronize(index)
                started = time.perf_counter()
                left = torch.ones((32, 32), device=f"cuda:{index}", dtype=torch.float32)
                right = torch.ones((32, 32), device=f"cuda:{index}", dtype=torch.float32)
                product = torch.mm(left, right)
                torch.cuda.synchronize(index)
                correct = bool(torch.all(product == 32.0).item())
                checksum = float(product.sum().item())
                torch.cuda.synchronize(index)
                elapsed_ms = (time.perf_counter() - started) * 1000
            device_report.update({
                "kernel": "float32 torch.mm of two 32x32 all-one matrices",
                "matrix_shape": [32, 32],
                "expected_element": 32.0,
                "result_sum": checksum,
                "elapsed_ms": round(elapsed_ms, 6),
                "synchronize_succeeded": True,
            })
            if not correct or checksum != 32768.0:
                raise ProbeError(f"CUDA device {index}: matmul produced an unexpected result")
            device_report["kernel_verified"] = True
            del left, right, product
        except Exception as exc:
            device_report["error"] = {"type": type(exc).__name__, "message": safe_text(str(exc))[0]}
            error_record(report, f"cuda_device_{index}", exc)
    report["checks"]["all_visible_devices_kernel_verified"] = (
        len(cuda_report["devices"]) == cuda_report["device_count"]
        and all(device["kernel_verified"] and device["synchronize_succeeded"] for device in cuda_report["devices"])
    )


def collect_report(bundle_root: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "version": 1,
        "probe_scope": "runtime_dependencies_bundle_sha_cuda_kernels",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "failed",
        "gpu_verified": False,
        "device_count": 0,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "prefix": sys.prefix,
        },
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        # This is an explicit two-key whitelist, never an environment inventory.
        "conda": {"active_name": os.environ.get("CONDA_DEFAULT_ENV"), "active_prefix": os.environ.get("CONDA_PREFIX")},
        "packages": {},
        "bundle": None,
        "pip": {},
        "checks": {
            "linux_runtime": False,
            "conda_env_active": False,
            "required_packages_present": False,
            "bundle_verified": False,
            "pip_freeze_succeeded": False,
            "pip_check_succeeded": False,
            "cuda_init": False,
            "all_visible_devices_kernel_verified": False,
        },
        "model_inference_verified": False,
        "container_network_verified": False,
        "errors": [],
    }
    report["checks"]["linux_runtime"] = report["platform"]["system"] == "Linux"
    if not report["checks"]["linux_runtime"]:
        error_record(report, "platform", ProbeError("B6 image runtime must be Linux"))
    report["checks"]["conda_env_active"] = (
        report["conda"]["active_name"] == "conda_env"
        and bool(report["conda"]["active_prefix"])
        and Path(report["conda"]["active_prefix"]).resolve() == Path(sys.prefix).resolve()
    )
    if not report["checks"]["conda_env_active"]:
        error_record(report, "conda", ProbeError("Activate the fixed conda_env before running this probe; prefix must match this Python"))

    for package in REQUIRED_PACKAGES:
        try:
            report["packages"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as exc:
            report["packages"][package] = None
            error_record(report, "required_package_" + package, exc)
    report["checks"]["required_packages_present"] = all(report["packages"].values())

    try:
        # prepare_bundle.py is alongside this file in /opt/b2-tools.
        from prepare_bundle import verify_bundle

        verified = verify_bundle(bundle_root)
        if not isinstance(verified, dict) or verified.get("verified") is not True:
            raise ProbeError("Bundle verifier did not return verified=true")
        report["bundle"] = verified
        report["checks"]["bundle_verified"] = True
    except Exception as exc:
        error_record(report, "bundle_verification", exc)

    for operation in ("freeze", "check"):
        try:
            result = run_pip(operation)
            report["pip"][operation] = result
            passed = result["exit_code"] == 0 and not result["timed_out"]
            report["checks"]["pip_" + operation + "_succeeded"] = passed
            if not passed:
                raise ProbeError(f"pip {operation} failed or timed out; inspect its recorded output")
        except Exception as exc:
            error_record(report, "pip_" + operation, exc)

    probe_cuda(report)
    report["device_count"] = report["torch"]["device_count"]
    if all(report["checks"].values()) and not report["errors"]:
        report["status"] = "passed"
        report["gpu_verified"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_json", type=Path, help="New evidence path outside the participant bundle; never overwritten")
    parser.add_argument("--bundle", type=Path, default=Path("/root/participant"), help="Participant bundle root (default /root/participant)")
    args = parser.parse_args()
    bundle_root = args.bundle.resolve()
    output_path = args.output_json.absolute()
    resolved_output = output_path.resolve()
    if resolved_output == bundle_root or bundle_root in resolved_output.parents:
        print("Runtime evidence must be outside the participant bundle", file=sys.stderr)
        return 2
    if output_path.exists() or output_path.is_symlink():
        print("Runtime evidence path already exists; choose a new path", file=sys.stderr)
        return 2
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Reserve exclusively before any expensive check; preserve earlier runs.
        with output_path.open("x", encoding="utf-8") as handle:
            try:
                report = collect_report(bundle_root)
            except (Exception, KeyboardInterrupt) as exc:
                report = {
                    "version": 1,
                    "probe_scope": "runtime_dependencies_bundle_sha_cuda_kernels",
                    "status": "failed",
                    "gpu_verified": False,
                    "device_count": 0,
                    "model_inference_verified": False,
                    "container_network_verified": False,
                    "errors": [{"stage": "probe", "type": type(exc).__name__, "message": safe_text(str(exc))[0]}],
                }
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except (OSError, ValueError) as exc:
        print(f"Could not preserve runtime evidence: {safe_text(str(exc))[0]}", file=sys.stderr)
        return 2
    print(f"{report['status'].upper()}: runtime probe; output={output_path}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
