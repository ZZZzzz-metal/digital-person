"""Tiny synthetic material directories test integrity, never actual delivery acceptance."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
DIRECTORY_NAME = "AI技术赛道-数字人综合情感对话模型-AI队"
MANIFEST_NAME = "REVIEW-MANIFEST.json"
FIXTURE_COMMIT = "b" * 40


@pytest.fixture
def material_tools(monkeypatch):
    monkeypatch.syspath_prepend(str(DEPLOY))
    spec = importlib.util.spec_from_file_location("b7_materials_unit_only", DEPLOY / "review_materials.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_manifest(directory, manifest):
    path = directory / MANIFEST_NAME
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def synthetic_materials(tmp_path):
    directory = tmp_path / DIRECTORY_NAME
    directory.mkdir()
    contents = {
        "技术方案.md": b"Synthetic unit fixture, not the team's technical proposal.\n",
        "records/运行.json": b'{"synthetic_unit_fixture":true}\n',
    }
    entries = []
    for name, data in contents.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entries.append({"path": name, "bytes": len(data), "sha256": sha256(data),
                        "source": "synthetic unit-fixture bytes; not actual project materials"})
    manifest = {"schema_version": 1, "directory_name": DIRECTORY_NAME,
                "code_commit": FIXTURE_COMMIT, "files": entries}
    write_manifest(directory, manifest)
    return directory, manifest


def test_valid_synthetic_materials_are_bound_to_expected_manifest_without_modification(material_tools, tmp_path):
    directory, manifest = synthetic_materials(tmp_path)
    manifest.update({"team_name": "synthetic unit-fixture team", "model_version": "synthetic-not-a-model",
                     "base_image_id": "sha256:" + "a" * 64, "bundle_manifest_sha256": "a" * 64,
                     "a_model_source_commit": "a" * 40, "a_report_commit": "c" * 40})
    write_manifest(directory, manifest)
    original = {path.relative_to(directory).as_posix(): path.read_bytes()
                for path in directory.rglob("*") if path.is_file()}
    expected = tmp_path / "expected-review-manifest.json"
    expected.write_bytes(original[MANIFEST_NAME])
    checksum = sha256(expected.read_bytes())
    assert material_tools.DIRECTORY_NAME == DIRECTORY_NAME
    assert material_tools.MANIFEST_NAME == MANIFEST_NAME
    assert material_tools.load_review_manifest(directory / MANIFEST_NAME) == manifest
    evidence = material_tools.verify_review_materials(directory, expected, expected_manifest_sha256=checksum)
    assert evidence["verified"] is True
    assert evidence["directory_name"] == DIRECTORY_NAME and evidence["code_commit"] == FIXTURE_COMMIT
    assert evidence["file_count"] == 2
    assert evidence["total_bytes"] == sum(entry["bytes"] for entry in manifest["files"])
    assert evidence["manifest_sha256"] == checksum and evidence["files"] == manifest["files"]
    assert "gpu_offline_verified" not in evidence and "contest_submitted" not in evidence
    assert original == {path.relative_to(directory).as_posix(): path.read_bytes()
                        for path in directory.rglob("*") if path.is_file()}


def test_expected_manifest_bytes_and_expected_digest_each_prevent_identity_substitution(material_tools, tmp_path):
    directory, manifest = synthetic_materials(tmp_path)
    checksum = sha256((directory / MANIFEST_NAME).read_bytes())
    with pytest.raises(RuntimeError):
        material_tools.verify_review_materials(directory, expected_manifest_sha256="0" * 64)
    expected = tmp_path / "different-expected.json"
    changed = deepcopy(manifest)
    changed["code_commit"] = "a" * 40
    expected.write_text(json.dumps(changed, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        material_tools.verify_review_materials(directory, expected, expected_manifest_sha256=checksum)


@pytest.mark.parametrize("issue", [
    "boolean_version", "boolean_size", "invalid_hash", "invalid_commit", "blank_source",
    "extra_entry_field", "empty_inventory", "wrong_directory_name",
])
def test_manifest_rejects_wrong_types_invalid_identity_or_inexact_entry_fields(material_tools, tmp_path, issue):
    directory, manifest = synthetic_materials(tmp_path)
    if issue == "boolean_version":
        manifest["schema_version"] = True
    elif issue == "boolean_size":
        manifest["files"][0]["bytes"] = True
    elif issue == "invalid_hash":
        manifest["files"][0]["sha256"] = "G" * 64
    elif issue == "invalid_commit":
        manifest["code_commit"] = "z" * 40
    elif issue == "blank_source":
        manifest["files"][0]["source"] = " \t\n"
    elif issue == "extra_entry_field":
        manifest["files"][0]["unexpected"] = "must not be silently accepted"
    elif issue == "empty_inventory":
        manifest["files"] = []
    else:
        manifest["directory_name"] = "different-team-directory"
    path = write_manifest(directory, manifest)
    with pytest.raises(RuntimeError):
        material_tools.load_review_manifest(path)


def test_manifest_rejects_duplicate_json_keys_instead_of_accepting_last_value(material_tools, tmp_path):
    directory, _ = synthetic_materials(tmp_path)
    path = directory / MANIFEST_NAME
    original = path.read_text(encoding="utf-8")
    path.write_text(original.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'),
                    encoding="utf-8")
    with pytest.raises(RuntimeError):
        material_tools.load_review_manifest(path)


@pytest.mark.parametrize("name", ["../outside.md", "records\\运行.json", MANIFEST_NAME])
def test_manifest_rejects_escape_nonposix_or_self_references(material_tools, tmp_path, name):
    directory, manifest = synthetic_materials(tmp_path)
    manifest["files"][0]["path"] = name
    with pytest.raises(RuntimeError):
        material_tools.load_review_manifest(write_manifest(directory, manifest))


def test_manifest_rejects_repeated_paths(material_tools, tmp_path):
    directory, manifest = synthetic_materials(tmp_path)
    manifest["files"].append(deepcopy(manifest["files"][0]))
    with pytest.raises(RuntimeError):
        material_tools.load_review_manifest(write_manifest(directory, manifest))


@pytest.mark.parametrize("issue", ["missing_file", "wrong_hash", "wrong_size", "extra_file", "empty_extra_directory"])
def test_material_directory_rejects_missing_changed_or_unlisted_content(material_tools, tmp_path, issue):
    directory, manifest = synthetic_materials(tmp_path)
    path = directory / manifest["files"][0]["path"]
    if issue == "missing_file":
        path.unlink()
    elif issue == "wrong_hash":
        original = path.read_bytes()
        path.write_bytes(b"!" + original[1:])
    elif issue == "wrong_size":
        path.write_bytes(path.read_bytes() + b"ADDED")
        # The hash is correct for the new bytes; only the declared size is stale.
        manifest["files"][0]["sha256"] = sha256(path.read_bytes())
        write_manifest(directory, manifest)
    elif issue == "extra_file":
        (directory / "unlisted.txt").write_bytes(b"unit fixture extra")
    else:
        (directory / "unlisted-empty-directory").mkdir()
    with pytest.raises(RuntimeError):
        material_tools.verify_review_materials(directory)


def test_material_directory_refuses_file_symlink_even_when_target_bytes_match(material_tools, tmp_path):
    directory, manifest = synthetic_materials(tmp_path)
    path = directory / manifest["files"][0]["path"]
    target = tmp_path / "synthetic-outside-target.txt"
    target.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(target)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"This OS/user cannot create the synthetic symlink fixture: {error}")
    with pytest.raises(RuntimeError):
        material_tools.verify_review_materials(directory)


@pytest.mark.parametrize("valid", [False, True])
def test_independent_cli_reports_real_fixture_result_and_refuses_existing_report(tmp_path, valid):
    directory, manifest = synthetic_materials(tmp_path)
    checksum = sha256((directory / MANIFEST_NAME).read_bytes())
    if not valid:
        path = directory / manifest["files"][0]["path"]
        path.write_bytes(path.read_bytes() + b"TAMPER")
    report = tmp_path / "new-unit-only-report.json"
    command = [sys.executable, "-B", str(DEPLOY / "review_materials.py"), str(directory), str(report),
               "--expected-manifest-sha256", checksum]
    run = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == (0 if valid else 1)
    stored = json.loads(report.read_text(encoding="utf-8"))
    assert stored["verified"] is valid
    if valid:
        assert stored["manifest_sha256"] == checksum and stored["file_count"] == 2
    assert "gpu_offline_verified" not in stored and "contest_submitted" not in stored
    original_report = report.read_bytes()
    repeated = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert repeated.returncode == 1
    assert report.read_bytes() == original_report
