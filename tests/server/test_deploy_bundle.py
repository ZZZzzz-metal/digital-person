"""B6 packaging fixtures use tiny bytes, never runnable weights or Docker evidence."""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from deploy.prepare_bundle import BundleError, prepare_bundle, verify_bundle


PROJECT = Path(__file__).resolve().parents[2]
B_FILES = (
    "submission/participant/__init__.py", "submission/participant/adapter.py",
    "submission/participant/run_inference.py", "submission/participant/check_output.py",
    "submission/participant/start.sh", "submission/participant/README.md",
    "src/b2_core/__init__.py", "src/b2_core/contracts.py", "src/b2_core/store.py",
    "contracts/official/inference_input.schema.json",
    "contracts/official/effective_submission.schema.json", "deploy/bundle_manifest.schema.json",
)
A_FILES = (
    "src/b2_core/model.py", "src/b2_core/a_impl/__init__.py", "src/b2_core/a_impl/dtos.py",
    "src/b2_core/a_impl/emotion_rules.py", "src/b2_core/a_impl/local_llm.py",
    "src/b2_core/a_impl/official_spec.py", "src/b2_core/prompts/__init__.py",
    "src/b2_core/prompts/empathy.py",
)
MODEL_FILES = (
    "config.json", "generation_config.json", "LICENSE", "merges.txt", "model.safetensors",
    "tokenizer.json", "tokenizer_config.json", "vocab.json",
)
MODEL_DIRECTORY = "base-qwen2.5-0.5b-instruct"
LICENSE_PATH = "LICENSES/Qwen2.5-0.5B-Instruct-LICENSE.txt"
B_COMMIT = "b" * 40
A_COMMIT = "a" * 40


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass
class TinyBundleFixture:
    project: Path
    a_source: Path
    source_manifest: Path
    assets: Path
    asset_manifest: Path
    output: Path

    def prepare(self):
        return prepare_bundle(
            self.project, self.a_source, self.source_manifest, self.assets,
            self.asset_manifest, self.output, source_commit=B_COMMIT,
        )

    def manifest(self, asset=False):
        return json.loads((self.asset_manifest if asset else self.source_manifest).read_text(encoding="utf-8"))

    def update_manifest(self, value, asset=False):
        write_json(self.asset_manifest if asset else self.source_manifest, value)


@pytest.fixture
def tiny_bundle(tmp_path):
    """Sources can import DTOs/checker; fixture tensors cannot run any model."""
    project, source = tmp_path / "project", tmp_path / "a-readonly"
    assets, output = tmp_path / "assets", tmp_path / "participant"
    source_manifest, asset_manifest = tmp_path / "sources.json", tmp_path / "assets.json"
    for relative in B_FILES:
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / relative, target)
    for relative in ("src/server/private.py", ".git/config", ".runtime/secret.sqlite3", "src/b2_core/__pycache__/private.pyc"):
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"DO_NOT_BUNDLE_PRIVATE_FIXTURE")
    entries = []
    for relative in A_FILES:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('"""Synthetic packaging source only; never a real model engine."""\n', encoding="utf-8")
        entries.append({"path": relative, "sha256": digest(target), "bytes": target.stat().st_size})
    write_json(source_manifest, {"main_sha": A_COMMIT, "A_readonly_review_copies": entries})
    model = assets / MODEL_DIRECTORY
    model.mkdir(parents=True)
    asset_entries = []
    for name in MODEL_FILES:
        target = model / name
        if name.endswith(".json"):
            write_json(target, {"fixture_only": True, "not_model_load_validation": True})
        else:
            target.write_bytes(b"TINY_PACKAGING_FIXTURE_NOT_A_REAL_MODEL\n" + name.encode("ascii"))
        asset_entries.append({"name": name, "sha256": digest(target), "bytes": target.stat().st_size})
    license_file = assets / LICENSE_PATH
    license_file.parent.mkdir(parents=True)
    shutil.copyfile(model / "LICENSE", license_file)
    config_file = assets / "inference_config.base.json"
    write_json(config_file, {
        "config_version": "fixture-only", "engine": "local_transformers",
        "model_version": "tiny-packaging-fixture-not-a-real-model", "model_dir": MODEL_DIRECTORY,
        "license_file": LICENSE_PATH, "patch_file": None, "device": "auto", "dtype": "float32",
        "max_input_tokens": 3072, "trust_remote_code": False,
        "generation": {"do_sample": True, "temperature": 0.3, "max_new_tokens": 256},
    })
    write_json(asset_manifest, {
        "files": asset_entries, "baseline_config": {"sha256": digest(config_file)},
        "license_copy": {"sha256": digest(license_file)}, "fixture_only": True,
    })
    return TinyBundleFixture(project, source, source_manifest, assets, asset_manifest, output)


def assert_rejected_without_output(fixture):
    with pytest.raises(BundleError):
        fixture.prepare()
    assert not fixture.output.exists()


def test_complete_bundle_preserves_sources_original_configuration_and_excludes_noise(tiny_bundle):
    original = (tiny_bundle.assets / "inference_config.base.json").read_bytes()
    result = tiny_bundle.prepare()
    assert result["code_commit"] == B_COMMIT and result["a_source_commit"] == A_COMMIT
    assert result["config_path"] == "weights/inference_config.base.json"
    assert result["model_version"] == "tiny-packaging-fixture-not-a-real-model"
    assert (tiny_bundle.output / result["config_path"]).read_bytes() == original
    assert (tiny_bundle.assets / "inference_config.base.json").read_bytes() == original
    checked = verify_bundle(tiny_bundle.output)
    assert checked["verified"] is True
    assert checked["file_count"] == len(result["files"])
    assert checked["total_bytes"] == sum(entry["bytes"] for entry in result["files"])
    assert checked["code_commit"] == B_COMMIT and checked["a_source_commit"] == A_COMMIT
    assert len(checked["manifest_sha256"]) == 64
    paths = {entry["path"] for entry in result["files"]}
    assert not any("__pycache__" in path or path.startswith((".git/", ".runtime/", "src/server/")) for path in paths)
    assert not any(b"DO_NOT_BUNDLE_PRIVATE_FIXTURE" in file.read_bytes() for file in tiny_bundle.output.rglob("*") if file.is_file())
    for entry in result["files"]:
        file = tiny_bundle.output / entry["path"]
        assert digest(file) == entry["sha256"] and file.stat().st_size == entry["bytes"]
    for relative in A_FILES:
        assert (tiny_bundle.output / relative).read_bytes() == (tiny_bundle.a_source / relative).read_bytes()


def test_bundle_imports_dtos_and_independent_checker_without_checkout_or_a_source(tiny_bundle):
    tiny_bundle.prepare()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    program = """
import json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path[:0] = [str(root), str(root / 'src')]
import b2_core.contracts as dtos
import adapter, check_output
assert pathlib.Path(dtos.__file__).resolve().is_relative_to(root)
assert pathlib.Path(adapter.__file__).resolve().is_relative_to(root)
assert pathlib.Path(check_output.__file__).resolve().is_relative_to(root)
assert adapter.runtime_root() == root
request = adapter.project_sample({'id': 'fixture-only', 'conversation_id': 'fixture', 'history': [{'role': 'user', 'content': 'Synthetic packaging check'}]})
assert request.sample_id == 'fixture-only'
assert 'torch' not in sys.modules and 'transformers' not in sys.modules
print(json.dumps({'standalone_import': True, 'model_started': False}))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", program, str(tiny_bundle.output)],
        cwd=tiny_bundle.output.parent, env=env, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"standalone_import": True, "model_started": False}


@pytest.mark.parametrize("existing_kind", ["directory", "file"])
def test_prepare_refuses_existing_target_and_preserves_foreign_files(tiny_bundle, existing_kind):
    side = tiny_bundle.output.parent / "foreign-side.txt"
    side.write_bytes(b"FOREIGN_SIDE")
    if existing_kind == "directory":
        tiny_bundle.output.mkdir()
        original = tiny_bundle.output / "foreign.txt"
    else:
        original = tiny_bundle.output
    original.write_bytes(b"FOREIGN_TARGET")
    with pytest.raises(BundleError):
        tiny_bundle.prepare()
    assert original.read_bytes() == b"FOREIGN_TARGET" and side.read_bytes() == b"FOREIGN_SIDE"


@pytest.mark.parametrize("target", ["source", "weight", "config", "license_copy"])
def test_prepare_rejects_tampered_sources_assets_and_configuration_before_output(tiny_bundle, target):
    path = {
        "source": tiny_bundle.a_source / "src/b2_core/model.py",
        "weight": tiny_bundle.assets / MODEL_DIRECTORY / "model.safetensors",
        "config": tiny_bundle.assets / "inference_config.base.json",
        "license_copy": tiny_bundle.assets / LICENSE_PATH,
    }[target]
    path.write_bytes(path.read_bytes() + b"TAMPER")
    assert_rejected_without_output(tiny_bundle)


@pytest.mark.parametrize("target", ["source", "weight", "tokenizer", "license", "b_contract"])
def test_prepare_rejects_missing_required_files(tiny_bundle, target):
    path = {
        "source": tiny_bundle.a_source / "src/b2_core/a_impl/local_llm.py",
        "weight": tiny_bundle.assets / MODEL_DIRECTORY / "model.safetensors",
        "tokenizer": tiny_bundle.assets / MODEL_DIRECTORY / "tokenizer.json",
        "license": tiny_bundle.assets / MODEL_DIRECTORY / "LICENSE",
        "b_contract": tiny_bundle.project / "src/b2_core/contracts.py",
    }[target]
    path.unlink()
    assert_rejected_without_output(tiny_bundle)


@pytest.mark.parametrize("section,mutation", [
    ("source", "missing"), ("source", "duplicate"), ("source", "bad_sha"),
    ("source", "bool_bytes"), ("source", "traversal"), ("source", "absolute"),
    ("asset", "missing"), ("asset", "duplicate"), ("asset", "bad_sha"),
    ("asset", "bool_bytes"), ("asset", "traversal"), ("asset", "absolute"),
])
def test_prepare_rejects_incomplete_ambiguous_or_unsafe_manifests(tiny_bundle, section, mutation):
    asset = section == "asset"
    value = tiny_bundle.manifest(asset=asset)
    entries = value["files" if asset else "A_readonly_review_copies"]
    field = "name" if asset else "path"
    if mutation == "missing":
        entries.pop()
    elif mutation == "duplicate":
        entries.append(deepcopy(entries[0]))
    elif mutation == "bad_sha":
        entries[0]["sha256"] = "not-a-sha"
    elif mutation == "bool_bytes":
        entries[0]["bytes"] = True
    elif mutation == "traversal":
        entries.append({field: "../foreign.txt", "sha256": "0" * 64, "bytes": 0})
    else:
        entries.append({field: "/foreign.txt", "sha256": "0" * 64, "bytes": 0})
    tiny_bundle.update_manifest(value, asset=asset)
    assert_rejected_without_output(tiny_bundle)


@pytest.mark.parametrize("field,value", [("model_dir", "../outside-model"), ("model_dir", "/outside-model"), ("license_file", "../outside-license")])
def test_prepare_rejects_configuration_path_escape_even_with_matching_configuration_hash(tiny_bundle, field, value):
    config_path = tiny_bundle.assets / "inference_config.base.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config[field] = value
    write_json(config_path, config)
    manifest = tiny_bundle.manifest(asset=True)
    manifest["baseline_config"]["sha256"] = digest(config_path)
    tiny_bundle.update_manifest(manifest, asset=True)
    assert_rejected_without_output(tiny_bundle)


def test_prepare_rejects_sharded_or_extra_model_files_instead_of_claiming_completeness(tiny_bundle):
    write_json(tiny_bundle.assets / MODEL_DIRECTORY / "model.safetensors.index.json", {"weight_map": {"fixture.weight": "missing-shard.safetensors"}})
    assert_rejected_without_output(tiny_bundle)


@pytest.mark.parametrize("mutation", ["changed", "missing", "extra", "manifest_partial", "duplicate", "traversal", "bad_sha", "bool_bytes"])
def test_verify_rejects_tampering_missing_assets_extras_and_invalid_inventory(tiny_bundle, mutation):
    tiny_bundle.prepare()
    manifest_path = tiny_bundle.output / "bundle_manifest.json"
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    model_entry = next(entry for entry in value["files"] if entry["path"].endswith("/model.safetensors"))
    target = tiny_bundle.output / model_entry["path"]
    if mutation == "changed":
        target.write_bytes(b"TAMPERED_BYTES")
    elif mutation in ("missing", "manifest_partial"):
        target.unlink()
        if mutation == "manifest_partial":
            value["files"].remove(model_entry)
    elif mutation == "extra":
        (tiny_bundle.output / "foreign.py").write_text("# not in verified source inventory\n", encoding="utf-8")
    elif mutation == "duplicate":
        value["files"].append(deepcopy(value["files"][0]))
    elif mutation == "traversal":
        value["files"].append({"path": "../foreign.txt", "role": "B", "sha256": "0" * 64, "bytes": 0})
    elif mutation == "bad_sha":
        value["files"][0]["sha256"] = "not-a-sha"
    else:
        value["files"][0]["bytes"] = True
    if mutation not in ("changed", "missing", "extra"):
        write_json(manifest_path, value)
    with pytest.raises(BundleError):
        verify_bundle(tiny_bundle.output)
