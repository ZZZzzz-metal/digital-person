"""Evidence-validator fixtures are synthetic; these tests never run Docker/GPU."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
FIXTURE_IMAGE_ID = "sha256:" + "a" * 64


@pytest.fixture
def container_tools(monkeypatch):
    monkeypatch.syspath_prepend(str(DEPLOY))
    spec = importlib.util.spec_from_file_location("b6_container_unit_only", DEPLOY / "verify_container.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_inspect():
    """Docker-shaped unit fixture, expressly not an actual Docker inspect."""
    return {
        "Image": FIXTURE_IMAGE_ID,
        "HostConfig": {
            "NetworkMode": "none",
            "DeviceRequests": [{"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu"]]}],
        },
        "State": {
            "Running": False, "ExitCode": 0,
            "StartedAt": "2026-10-11T00:00:00Z", "FinishedAt": "2026-10-11T00:00:01Z",
        },
    }


def test_validator_only_returns_matching_inspect_fields_without_claiming_actual_gpu_acceptance(container_tools):
    info = synthetic_inspect()
    original = deepcopy(info)
    evidence = container_tools.validate_container(info, FIXTURE_IMAGE_ID, gpu=True)
    assert evidence["image_id"] == FIXTURE_IMAGE_ID
    assert evidence["network_mode"] == "none" and evidence["exit_code"] == 0
    assert evidence["device_requests"] == info["HostConfig"]["DeviceRequests"]
    assert evidence["started_at"] == info["State"]["StartedAt"]
    assert "gpu_offline_verified" not in evidence
    assert info == original


@pytest.mark.parametrize("mutation", ["wrong_image", "network_bridge", "missing_gpu", "cpu_capability", "running", "failure_exit"])
def test_validator_rejects_image_network_gpu_or_completion_mismatch(container_tools, mutation):
    info = synthetic_inspect()
    if mutation == "wrong_image":
        info["Image"] = "sha256:" + "b" * 64
    elif mutation == "network_bridge":
        info["HostConfig"]["NetworkMode"] = "bridge"
    elif mutation == "missing_gpu":
        info["HostConfig"]["DeviceRequests"] = []
    elif mutation == "cpu_capability":
        info["HostConfig"]["DeviceRequests"][0]["Capabilities"] = [["utility"]]
    elif mutation == "running":
        info["State"]["Running"] = True
    else:
        info["State"]["ExitCode"] = 1
    with pytest.raises(RuntimeError):
        container_tools.validate_container(info, FIXTURE_IMAGE_ID, gpu=True)


def test_checker_container_can_be_cpu_but_still_requires_same_image_and_no_network(container_tools):
    info = synthetic_inspect()
    info["HostConfig"]["DeviceRequests"] = []
    checked = container_tools.validate_container(info, FIXTURE_IMAGE_ID, gpu=False)
    assert checked["device_requests"] == []
    info["HostConfig"]["NetworkMode"] = "host"
    with pytest.raises(RuntimeError):
        container_tools.validate_container(info, FIXTURE_IMAGE_ID, gpu=False)


def test_missing_docker_records_failure_and_never_sets_image_gpu_or_fallback_success(container_tools, tmp_path, monkeypatch):
    work = tmp_path / "owned-new-evidence"
    side = tmp_path / "foreign-side.txt"
    side.write_bytes(b"FOREIGN")
    monkeypatch.setattr(container_tools.shutil, "which", lambda name: None)

    def no_command(*args, **kwargs):
        pytest.fail("Missing-Docker path must not run any command")

    monkeypatch.setattr(container_tools, "execute", no_command)
    returned = container_tools.run(SimpleNamespace(
        work=work, bundle=tmp_path / "no-bundle", test_file=tmp_path / "no-input", tag="unit-fixture:unused",
    ))
    stored = json.loads((work / "verification.json").read_text(encoding="utf-8"))
    assert stored == returned
    for field in ("image_built", "gpu_offline_verified", "fallback_image_verified", "official_score_verified", "contest_submitted"):
        assert stored[field] is False
    assert stored["image_id"] is None and stored["save_tar_sha256"] is None
    assert stored["repo_digests"] == [] and stored["runs"] == {}
    assert "Docker CLI is missing" in stored["failure"]
    assert {path.name for path in work.iterdir()} == {"verification.json"}
    assert side.read_bytes() == b"FOREIGN"


def test_nonlinux_daemon_is_failure_before_build_and_cannot_verify_gpu(container_tools, tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(container_tools.shutil, "which", lambda name: "unit-fixture-not-real-docker")

    def fixture_execute(command, log=None):
        commands.append(command)
        assert command[1] == "info" and log is None
        return json.dumps({"OSType": "windows"})

    monkeypatch.setattr(container_tools, "execute", fixture_execute)
    returned = container_tools.run(SimpleNamespace(
        work=tmp_path / "evidence", bundle=tmp_path / "unused-bundle", test_file=tmp_path / "unused-input", tag="unit-fixture:unused",
    ))
    assert len(commands) == 1
    assert returned["image_built"] is False and returned["gpu_offline_verified"] is False
    assert returned["fallback_image_verified"] is False and returned["image_id"] is None
    assert returned["runs"] == {} and "Linux Docker daemon is required" in returned["failure"]


def test_runner_refuses_existing_evidence_directory_without_touching_foreign_files(container_tools, tmp_path, monkeypatch):
    work = tmp_path / "foreign-evidence"
    work.mkdir()
    original = work / "verification.json"
    original.write_bytes(b"FOREIGN_EXISTING_EVIDENCE")
    monkeypatch.setattr(container_tools.shutil, "which", lambda name: pytest.fail("No Docker lookup on existing work"))
    with pytest.raises(FileExistsError):
        container_tools.run(SimpleNamespace(work=work, bundle=tmp_path, test_file=tmp_path / "unused", tag="unused"))
    assert original.read_bytes() == b"FOREIGN_EXISTING_EVIDENCE"


def test_bind_mount_marks_input_readonly_and_rejects_ambiguous_comma_path(container_tools, tmp_path):
    input_file = tmp_path / "input.jsonl"
    input_file.write_text("fixture only", encoding="utf-8")
    readonly = container_tools.mount(input_file, "/b2-input.jsonl", readonly=True)
    output = container_tools.mount(tmp_path / "new-output", "/b2-result")
    assert readonly[0] == output[0] == "--mount"
    assert readonly[1].endswith("target=/b2-input.jsonl,readonly")
    assert output[1].endswith("target=/b2-result") and "readonly" not in output[1]
    with pytest.raises(ValueError):
        container_tools.mount(tmp_path / "ambiguous,path", "/b2-input.jsonl", readonly=True)


def synthetic_inference_events():
    """Only the evidence parser is tested; CUDA/model claims below are invented fixtures."""
    version = "synthetic-event-validator-fixture-not-a-real-model"
    events = [
        {"event": "runtime", "device": "cuda", "cuda_available": True, "is_mock": False, "model_version": version},
        {"event": "model_ready", "initializations": 1, "is_mock": False, "model_version": version},
        {"event": "sample_complete", "id": "synthetic-1", "schema_valid": True, "fresh_store_closed": True, "response_source": "model"},
        {"event": "sample_complete", "id": "synthetic-2", "schema_valid": True, "fresh_store_closed": True, "response_source": "model"},
        {"event": "batch_complete", "samples": 2, "rounds": 2, "complete": False},
    ]
    performance = {"samples": 2, "rounds": 2, "complete": False, "model_version": version}
    return events, performance


def write_synthetic_events(path, events):
    path.write_text(
        "Synthetic parser fixture; not actual GPU runtime output\n"
        + "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def test_event_validator_matches_runtime_model_and_full_validated_batch_only(container_tools, tmp_path):
    events, performance = synthetic_inference_events()
    log = tmp_path / "synthetic-inference.log"
    write_synthetic_events(log, events)
    original = deepcopy(performance)
    result = container_tools.validate_inference_events(log, performance["model_version"], performance)
    assert result["runtime"] == events[0] and result["model_ready"] == events[1]
    assert result["batch_complete"] == events[-1] and result["sample_events"] == 2
    assert "gpu_offline_verified" not in result
    assert performance == original


@pytest.mark.parametrize("mutation", [
    "cpu", "cuda_unavailable", "runtime_mock", "ready_mock", "missing_runtime", "missing_ready",
    "missing_batch", "duplicate_runtime", "sample_count", "batch_samples", "batch_rounds",
    "batch_complete", "invalid_schema", "fixture_response", "store_open", "wrong_model", "initialized_twice",
])
def test_event_validator_rejects_cpu_mock_missing_or_mismatched_prediction_evidence(container_tools, tmp_path, mutation):
    events, performance = synthetic_inference_events()
    if mutation == "cpu":
        events[0]["device"] = "cpu"
    elif mutation == "cuda_unavailable":
        events[0]["cuda_available"] = False
    elif mutation == "runtime_mock":
        events[0]["is_mock"] = True
    elif mutation == "ready_mock":
        events[1]["is_mock"] = True
    elif mutation == "missing_runtime":
        events.pop(0)
    elif mutation == "missing_ready":
        events.pop(1)
    elif mutation == "missing_batch":
        events.pop()
    elif mutation == "duplicate_runtime":
        events.append(deepcopy(events[0]))
    elif mutation == "sample_count":
        events.pop(2)
    elif mutation == "batch_samples":
        events[-1]["samples"] = 1
    elif mutation == "batch_rounds":
        events[-1]["rounds"] = 1
    elif mutation == "batch_complete":
        events[-1]["complete"] = True
    elif mutation == "invalid_schema":
        events[2]["schema_valid"] = False
    elif mutation == "fixture_response":
        events[2]["response_source"] = "mock"
    elif mutation == "store_open":
        events[2]["fresh_store_closed"] = False
    elif mutation == "wrong_model":
        events[0]["model_version"] = "wrong-synthetic-model"
    else:
        events[1]["initializations"] = 2
    log = tmp_path / "synthetic-inference.log"
    write_synthetic_events(log, events)
    with pytest.raises(RuntimeError):
        container_tools.validate_inference_events(log, performance["model_version"], performance)
