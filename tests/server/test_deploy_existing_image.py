"""Synthetic B7 boundary fixtures never build images, run Docker, or claim GPU success."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
FIXTURE_IMAGE_ID = "sha256:" + "a" * 64
CONTROLLED_GPU_STOP = "Synthetic test stops before any GPU execution"


@pytest.fixture
def container_tools(monkeypatch):
    monkeypatch.syspath_prepend(str(DEPLOY))
    spec = importlib.util.spec_from_file_location("b7_existing_image_unit_only", DEPLOY / "verify_container.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_args(tmp_path, *, existing_image=FIXTURE_IMAGE_ID, review_materials=None):
    test_file = tmp_path / "synthetic-input-not-official.jsonl"
    test_file.write_bytes(b'{"synthetic_unit_fixture":true}\n')
    return SimpleNamespace(work=tmp_path / "new-unit-evidence", bundle=tmp_path / "synthetic-bundle",
                           test_file=test_file, tag="synthetic-mutable-tag:must-not-be-used",
                           existing_image=existing_image, review_materials=review_materials)


def prepare_synthetic_reuse(monkeypatch, tools, *, wrong_image=False):
    calls = []
    monkeypatch.setattr(tools.shutil, "which", lambda name: "synthetic-not-real-docker")

    def execute(command, log=None):
        calls.append(("execute", command))
        assert command == ["docker", "info", "--format", "{{json .}}"] and log is None
        return json.dumps({"OSType": "linux", "Architecture": "x86_64", "ServerVersion": "synthetic-only"})

    def verify_bundle(path):
        calls.append(("verify_bundle", path))
        return {"manifest_sha256": "b" * 64, "model_version": "synthetic-not-a-runnable-model"}

    def inspect(kind, image_id):
        calls.append(("inspect", kind, image_id))
        assert kind == "image" and image_id == FIXTURE_IMAGE_ID
        return {"Id": "sha256:" + "c" * 64 if wrong_image else FIXTURE_IMAGE_ID,
                "Size": 123, "RepoDigests": [], "Descriptor": None}

    monkeypatch.setattr(tools, "execute", execute)
    monkeypatch.setattr(tools, "verify_bundle", verify_bundle)
    monkeypatch.setattr(tools, "inspect", inspect)
    monkeypatch.setattr(tools, "prepare_context", lambda *args: pytest.fail("Existing image must never prepare/build context"))
    return calls


def assert_no_gpu_or_submission_success(report):
    for name in ("image_built", "gpu_offline_verified", "fallback_image_verified", "official_score_verified", "contest_submitted"):
        assert report[name] is False
    assert report["save_tar_sha256"] is None


def synthetic_review_manifest(tmp_path, tools):
    data = b"x"
    manifest = {"schema_version": 1, "directory_name": tools.DIRECTORY_NAME, "code_commit": "b" * 40,
                "files": [{"path": "synthetic-not-project-material.md", "bytes": len(data),
                           "sha256": hashlib.sha256(data).hexdigest(), "source": "synthetic fixture only"}]}
    path = tmp_path / "frozen-unit-review-manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, manifest


def synthetic_material_evidence(manifest, checksum):
    return {"verified": True, "directory_name": manifest["directory_name"], "code_commit": manifest["code_commit"],
            "file_count": len(manifest["files"]), "total_bytes": sum(item["bytes"] for item in manifest["files"]),
            "manifest_sha256": checksum, "files": deepcopy(manifest["files"])}


def assert_material_call(tools, image_id, command, mounts, work, name, gpu, entrypoint, frozen):
    assert image_id == FIXTURE_IMAGE_ID and name == "materials"
    assert gpu is False and entrypoint == tools.PYTHON
    expected = work / "review-materials.expected.json"
    assert expected.read_bytes() == frozen.read_bytes()
    checksum = hashlib.sha256(frozen.read_bytes()).hexdigest()
    assert command == ["/opt/b2-tools/review_materials.py", "/root/" + tools.DIRECTORY_NAME,
                       "/b2-materials-evidence/materials-verify.json", "--expected-manifest-sha256", checksum]
    assert mounts[0] == "--mount" and mounts[1].startswith("type=bind,source=")
    assert mounts[1].endswith("target=/b2-materials-evidence")
    return checksum


@pytest.mark.parametrize("image_id", [
    "synthetic-tag:latest", "registry.invalid/unit@sha256:" + "a" * 64,
    "sha256:abcd", "sha256:" + "A" * 64,
])
def test_existing_image_rejects_mutable_registry_short_or_uppercase_id_before_docker(container_tools, tmp_path, monkeypatch, image_id):
    args = make_args(tmp_path, existing_image=image_id)
    monkeypatch.setattr(container_tools.shutil, "which", lambda name: pytest.fail("Invalid ID must not look up Docker"))
    monkeypatch.setattr(container_tools, "execute", lambda *args: pytest.fail("Invalid ID must not execute Docker"))
    report = container_tools.run(args)
    assert_no_gpu_or_submission_success(report)
    assert report["image_reused"] is False and report["image_id"] is None and report["runs"] == {}
    assert "immutable full sha256 image ID" in report["failure"]
    assert json.loads((args.work / "verification.json").read_text()) == report


def test_valid_existing_id_verifies_bundle_inspects_fixed_id_and_skips_build(container_tools, tmp_path, monkeypatch):
    args = make_args(tmp_path)
    calls = prepare_synthetic_reuse(monkeypatch, container_tools)

    def stop_before_gpu(image_id, command, mounts, work, name, *, gpu=False, entrypoint=None):
        assert image_id == FIXTURE_IMAGE_ID and name == "gpu-probe" and gpu is True
        raise RuntimeError(CONTROLLED_GPU_STOP)

    monkeypatch.setattr(container_tools, "run_container", stop_before_gpu)
    report = container_tools.run(args)
    assert calls[1] == ("verify_bundle", args.bundle)
    assert calls[2] == ("inspect", "image", FIXTURE_IMAGE_ID) and len(calls) == 3
    assert report["image_reused"] is True and report["build_skipped"] is True
    assert report["image_id"] == FIXTURE_IMAGE_ID and report["failure"] == CONTROLLED_GPU_STOP
    assert report["review_materials_verified"] is False and report["runs"] == {}
    assert not (args.work / "context").exists() and not (args.work / "build.log").exists()
    assert_no_gpu_or_submission_success(report)


def test_existing_image_inspect_mismatch_fails_before_any_container(container_tools, tmp_path, monkeypatch):
    args = make_args(tmp_path)
    prepare_synthetic_reuse(monkeypatch, container_tools, wrong_image=True)
    monkeypatch.setattr(container_tools, "run_container", lambda *args, **kwargs: pytest.fail("Wrong inspected ID must never run a container"))
    report = container_tools.run(args)
    assert report["image_id"] is None and report["runs"] == {}
    assert "image ID mismatch" in report["failure"]
    assert_no_gpu_or_submission_success(report)


@pytest.mark.parametrize("issue", ["wrong_sha", "unverified", "boolean_file_count", "changed_inventory"])
def test_material_evidence_mismatch_stops_before_gpu_and_cannot_set_success(container_tools, tmp_path, monkeypatch, issue):
    frozen, manifest = synthetic_review_manifest(tmp_path, container_tools)
    args = make_args(tmp_path, review_materials=frozen)
    prepare_synthetic_reuse(monkeypatch, container_tools)
    names = []

    def only_materials(image_id, command, mounts, work, name, *, gpu=False, entrypoint=None):
        names.append(name)
        checksum = assert_material_call(container_tools, image_id, command, mounts, work, name, gpu, entrypoint, frozen)
        evidence = synthetic_material_evidence(manifest, checksum)
        if issue == "wrong_sha":
            evidence["manifest_sha256"] = "0" * 64
        elif issue == "unverified":
            evidence["verified"] = False
        elif issue == "boolean_file_count":
            evidence["file_count"] = True  # Numerically equals 1; a strict integer is required.
        else:
            evidence["files"][0]["source"] = "different synthetic source"
        (work / "materials-verify.json").write_text(json.dumps(evidence), encoding="utf-8")
        return {"image_id": image_id, "network_mode": "none", "exit_code": 0, "synthetic_unit_fixture": True}

    monkeypatch.setattr(container_tools, "run_container", only_materials)
    report = container_tools.run(args)
    assert names == ["materials"]
    assert report["review_materials_required"] is True and report["review_materials_verified"] is False
    assert report["review_materials_expected_sha256"] == hashlib.sha256(frozen.read_bytes()).hexdigest()
    assert "frozen manifest" in report["failure"] and set(report["runs"]) == {"materials"}
    assert not (args.work / "probe").exists()
    assert_no_gpu_or_submission_success(report)


def test_material_container_failure_propagates_without_gpu_or_material_success(container_tools, tmp_path, monkeypatch):
    frozen, _ = synthetic_review_manifest(tmp_path, container_tools)
    args = make_args(tmp_path, review_materials=frozen)
    prepare_synthetic_reuse(monkeypatch, container_tools)

    def fail_materials(image_id, command, mounts, work, name, *, gpu=False, entrypoint=None):
        assert_material_call(container_tools, image_id, command, mounts, work, name, gpu, entrypoint, frozen)
        raise RuntimeError("Synthetic material-container failure")

    monkeypatch.setattr(container_tools, "run_container", fail_materials)
    report = container_tools.run(args)
    assert report["failure"] == "Synthetic material-container failure"
    assert report["review_materials_verified"] is False and report["runs"] == {}
    assert_no_gpu_or_submission_success(report)


def test_valid_fixture_material_evidence_reaches_gpu_boundary_but_never_claims_gpu_success(container_tools, tmp_path, monkeypatch):
    frozen, manifest = synthetic_review_manifest(tmp_path, container_tools)
    args = make_args(tmp_path, review_materials=frozen)
    prepare_synthetic_reuse(monkeypatch, container_tools)
    names = []

    def stop_at_gpu(image_id, command, mounts, work, name, *, gpu=False, entrypoint=None):
        names.append(name)
        if name == "gpu-probe":
            assert image_id == FIXTURE_IMAGE_ID and gpu is True
            raise RuntimeError(CONTROLLED_GPU_STOP)
        checksum = assert_material_call(container_tools, image_id, command, mounts, work, name, gpu, entrypoint, frozen)
        evidence = synthetic_material_evidence(manifest, checksum)
        (work / "materials-verify.json").write_text(json.dumps(evidence), encoding="utf-8")
        return {"image_id": image_id, "network_mode": "none", "exit_code": 0, "synthetic_unit_fixture": True}

    monkeypatch.setattr(container_tools, "run_container", stop_at_gpu)
    report = container_tools.run(args)
    assert names == ["materials", "gpu-probe"] and set(report["runs"]) == {"materials"}
    assert report["review_materials_verified"] is True and report["failure"] == CONTROLLED_GPU_STOP
    assert report["review_materials"]["files"] == manifest["files"]
    assert_no_gpu_or_submission_success(report)


def test_malformed_host_material_manifest_fails_before_docker(container_tools, tmp_path, monkeypatch):
    frozen = tmp_path / "invalid-unit-manifest.json"
    frozen.write_bytes(b"not JSON; synthetic fixture")
    args = make_args(tmp_path, review_materials=frozen)
    monkeypatch.setattr(container_tools.shutil, "which", lambda name: pytest.fail("Invalid material manifest must not look up Docker"))
    report = container_tools.run(args)
    assert report["review_materials_required"] is True and report["review_materials_verified"] is False
    assert report["image_id"] is None and report["runs"] == {}
    assert_no_gpu_or_submission_success(report)


def test_material_container_creation_uses_fixed_id_and_network_none_without_gpu(container_tools, tmp_path, monkeypatch):
    work = tmp_path / "synthetic-container-evidence"
    work.mkdir()
    cid = "c" * 64
    created = []
    command = ["/opt/b2-tools/review_materials.py", "/root/" + container_tools.DIRECTORY_NAME,
               "/b2-materials-evidence/materials-verify.json"]

    def execute(args, log=None):
        if args[:3] == ["docker", "container", "create"]:
            created.append(args)
            return cid
        assert args == ["docker", "container", "start", "--attach", cid]
        log.write_bytes(b"Synthetic material-container fixture, not Docker output.\n")
        return ""

    def inspect(kind, identity):
        assert kind == "container" and identity == cid
        return {"Image": FIXTURE_IMAGE_ID, "HostConfig": {"NetworkMode": "none", "DeviceRequests": []},
                "State": {"Running": False, "ExitCode": 0, "StartedAt": "synthetic-start", "FinishedAt": "synthetic-finish"}}

    def cleanup(args, **kwargs):
        assert args == ["docker", "container", "rm", "--force", cid]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(container_tools, "execute", execute)
    monkeypatch.setattr(container_tools, "inspect", inspect)
    monkeypatch.setattr(container_tools.subprocess, "run", cleanup)
    evidence = container_tools.run_container(FIXTURE_IMAGE_ID, command, container_tools.mount(work, "/b2-materials-evidence"),
                                            work, "materials", entrypoint=container_tools.PYTHON)
    assert len(created) == 1
    create = created[0]
    assert create[create.index("--network") + 1] == "none" and "--gpus" not in create
    assert create[create.index("--entrypoint") + 1] == container_tools.PYTHON
    assert create[-len(command) - 1:] == [FIXTURE_IMAGE_ID] + command
    assert evidence["image_id"] == FIXTURE_IMAGE_ID and evidence["network_mode"] == "none"
    assert "gpu_offline_verified" not in evidence
