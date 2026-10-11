"""Runtime probe control-flow tests; no real Torch/CUDA/container is executed."""
from __future__ import annotations

import contextlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import types
from unittest import mock

import pytest


@pytest.fixture
def probe():
    path = pathlib.Path(__file__).resolve().parents[2] / "deploy/runtime_probe.py"
    spec = importlib.util.spec_from_file_location("b6_runtime_probe_test_target", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def torch_fixture(*, available=True, kernel_failure=False, init_failure=False):
    cuda = mock.MagicMock()
    cuda.is_available.return_value = available
    cuda.device_count.return_value = 2 if available else 0
    cuda.get_device_properties.return_value = types.SimpleNamespace(
        name="unit fixture", total_memory=1024, major=8, minor=9, multi_processor_count=1
    )
    cuda.device.side_effect = lambda _: contextlib.nullcontext()
    if init_failure:
        cuda.init.side_effect = RuntimeError("unit initialization failure")
    product = mock.MagicMock()
    product.sum.return_value.item.return_value = 32768.0
    all_value = mock.MagicMock()
    all_value.item.return_value = True
    torch = types.SimpleNamespace(
        __version__="unit fixture",
        version=types.SimpleNamespace(cuda="unit fixture"),
        cuda=cuda,
        float32="float32",
        inference_mode=lambda: contextlib.nullcontext(),
        ones=mock.MagicMock(),
        mm=mock.MagicMock(return_value=product),
        all=mock.MagicMock(return_value=all_value),
    )
    if kernel_failure:
        torch.mm.side_effect = [product, RuntimeError("unit second GPU kernel failure")]
    return torch


def collect_fixture(probe, torch, *, failure=None):
    def verify(_):
        if failure == "bundle":
            raise ValueError("unit bundle digest mismatch")
        return {"verified": True, "manifest_sha256": "1" * 64, "file_count": 1}

    def version(package):
        if failure == "package" and package == "accelerate":
            raise probe.importlib.metadata.PackageNotFoundError(package)
        return "2.0.unit"

    def pip(operation):
        return {
            "exit_code": 1 if failure == "pip" and operation == "check" else 0,
            "timed_out": False,
            "stdout": "unit metadata fixture",
            "stderr": "",
        }

    env = mock.MagicMock(side_effect=lambda key, default=None: {
        "CONDA_DEFAULT_ENV": "other" if failure == "conda" else "conda_env",
        "CONDA_PREFIX": sys.prefix,
    }.get(key, default))
    with (
        mock.patch.dict(sys.modules, {"torch": torch, "prepare_bundle": types.SimpleNamespace(verify_bundle=verify)}),
        mock.patch.object(probe.platform, "system", return_value="Windows" if failure == "linux" else "Linux"),
        mock.patch.object(probe.platform, "release", return_value="unit release"),
        mock.patch.object(probe.platform, "machine", return_value="unit machine"),
        mock.patch.object(probe.os.environ, "get", env),
        mock.patch.object(probe.importlib.metadata, "version", side_effect=version),
        mock.patch.object(probe, "run_pip", side_effect=pip),
    ):
        report = probe.collect_report(pathlib.Path("/unit-bundle"))
    assert {call.args[0] for call in env.call_args_list} == {"CONDA_DEFAULT_ENV", "CONDA_PREFIX"}
    assert report["model_inference_verified"] is False
    assert report["container_network_verified"] is False
    return report


def test_all_visible_gpus_receive_matmul_and_synchronization(probe):
    torch = torch_fixture()
    report = collect_fixture(probe, torch)
    assert report["status"] == "passed" and report["gpu_verified"] is True
    assert report["device_count"] == 2
    assert torch.mm.call_count == 2 and torch.cuda.synchronize.call_count == 6
    assert [call.args[0] for call in torch.cuda.device.call_args_list] == [0, 1]
    assert all(device["kernel_verified"] for device in report["torch"]["devices"])


def test_cuda_unavailable_never_calls_kernel(probe):
    torch = torch_fixture(available=False)
    report = collect_fixture(probe, torch)
    assert report["status"] == "failed" and report["gpu_verified"] is False
    assert report["device_count"] == 0 and not report["checks"]["cuda_init"]
    torch.mm.assert_not_called()


def test_cuda_initialization_failure_never_calls_kernel(probe):
    torch = torch_fixture(init_failure=True)
    report = collect_fixture(probe, torch)
    assert report["gpu_verified"] is False
    torch.mm.assert_not_called()


def test_second_gpu_kernel_failure_cannot_pass(probe):
    report = collect_fixture(probe, torch_fixture(kernel_failure=True))
    assert report["status"] == "failed" and report["gpu_verified"] is False
    assert report["torch"]["devices"][0]["kernel_verified"] is True
    assert report["torch"]["devices"][1]["kernel_verified"] is False


@pytest.mark.parametrize("failure", ["bundle", "package", "pip", "linux", "conda"])
def test_non_gpu_prerequisite_failure_keeps_gpu_verified_false(probe, failure):
    report = collect_fixture(probe, torch_fixture(), failure=failure)
    assert report["checks"]["all_visible_devices_kernel_verified"] is True
    assert report["status"] == "failed" and report["gpu_verified"] is False


def test_pip_timeout_and_metadata_credential_redaction(probe):
    with mock.patch.object(probe.subprocess, "run", side_effect=subprocess.TimeoutExpired(["pip"], 30, output=b"unit fixture")):
        assert probe.run_pip("freeze")["timed_out"] is True
    text, redacted = probe.safe_text("x @ https://unit-user:unit-secret@example.invalid/x?token=unit-token")
    assert redacted and text == "x @ https://<redacted>@example.invalid/x?token=<redacted>"


def test_output_is_exclusive_and_failure_exit_is_nonzero(probe, tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    output = tmp_path / "runtime.json"
    monkeypatch.setattr(sys, "argv", ["runtime_probe.py", str(output), "--bundle", str(bundle)])
    failed = {"status": "failed", "gpu_verified": False, "device_count": 0}
    with mock.patch.object(probe, "collect_report", return_value=failed):
        assert probe.main() == 1
    previous = output.read_bytes()
    with mock.patch.object(probe, "collect_report") as called:
        assert probe.main() == 2
        called.assert_not_called()
    assert output.read_bytes() == previous and json.loads(previous)["gpu_verified"] is False


def test_report_inside_bundle_rejected_before_probe(probe, tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    output = bundle / "runtime.json"
    monkeypatch.setattr(sys, "argv", ["runtime_probe.py", str(output), "--bundle", str(bundle)])
    with mock.patch.object(probe, "collect_report") as called:
        assert probe.main() == 2
        called.assert_not_called()
    assert not output.exists()
