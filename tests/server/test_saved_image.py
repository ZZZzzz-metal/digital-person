"""Tiny synthetic archives exercise integrity checks, never Docker/GPU acceptance."""

from copy import deepcopy
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest


DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_GZIP_LAYER = "application/vnd.oci.image.layer.v1.tar+gzip"
ATTESTATION_LAYER = "application/vnd.in-toto+json"


@pytest.fixture
def saved_image_tools(monkeypatch):
    monkeypatch.syspath_prepend(str(DEPLOY))
    spec = importlib.util.spec_from_file_location("b6_saved_image_unit_only", DEPLOY / "saved_image.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def blob_name(blob_digest):
    return "blobs/sha256/" + blob_digest.removeprefix("sha256:")


def descriptor(data, media_type, **fields):
    return {"mediaType": media_type, "digest": digest(data), "size": len(data), **fields}


def synthetic_layer():
    """A small real tar stream containing an explicit unit-fixture notice."""
    content = b"Synthetic archive unit fixture; not a runnable container image.\n"
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        item = tarfile.TarInfo("unit-fixture.txt")
        item.size = len(content)
        archive.addfile(item, io.BytesIO(content))
    return stream.getvalue()


def write_archive(path, files, *, duplicate=None):
    with tarfile.open(path, "w") as archive:
        for name, data in files.items():
            item = tarfile.TarInfo(name)
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
        if duplicate is not None:
            item = tarfile.TarInfo(duplicate)
            item.size = len(files[duplicate])
            archive.addfile(item, io.BytesIO(files[duplicate]))


def oci_fixture(*, direct=False, architecture="amd64", second_amd64=False,
                descriptor_issue=None, wrong_diff_id=False, invalid_gzip=False,
                malformed_layer_digest=False, compatibility_manifest=False):
    """Construct the full OCI identity chain from known tiny fixture bytes."""
    files = {"oci-layout": json_bytes({"imageLayoutVersion": "1.0.0"})}
    raw_layer = synthetic_layer()
    compressed = b"not-gzip-unit-fixture" if invalid_gzip else gzip.compress(raw_layer, mtime=0)
    config = {"architecture": architecture, "os": "linux", "rootfs": {
        "type": "layers", "diff_ids": ["sha256:" + "0" * 64 if wrong_diff_id else digest(raw_layer)],
    }}
    config_bytes = json_bytes(config)
    config_descriptor = descriptor(config_bytes, OCI_CONFIG)
    layer_descriptor = descriptor(compressed, OCI_GZIP_LAYER)
    if malformed_layer_digest:
        layer_descriptor["digest"] = "sha256:" + "z" * 64

    def mutate(kind, value):
        if descriptor_issue and descriptor_issue[0] == kind:
            value[descriptor_issue[1]] = descriptor_issue[2]
        return value

    manifest_bytes = json_bytes({
        "schemaVersion": 2, "mediaType": OCI_MANIFEST,
        "config": mutate("config", config_descriptor),
        "layers": [mutate("layer", layer_descriptor)],
    })
    platform_descriptor = mutate("platform", descriptor(
        manifest_bytes, OCI_MANIFEST, platform={"os": "linux", "architecture": architecture},
    ))
    for data in (config_bytes, compressed, manifest_bytes):
        files[blob_name(digest(data))] = data

    attest_config = json_bytes({})
    attest_layer = json_bytes({"_type": "synthetic-unit-fixture-only", "subject": []})
    attest_manifest = json_bytes({
        "schemaVersion": 2, "mediaType": OCI_MANIFEST,
        "config": descriptor(attest_config, OCI_CONFIG),
        "layers": [descriptor(attest_layer, ATTESTATION_LAYER)],
    })
    attestation_descriptor = descriptor(
        attest_manifest, OCI_MANIFEST,
        platform={"os": "unknown", "architecture": "unknown"},
        annotations={"vnd.docker.reference.type": "attestation-manifest",
                     "vnd.docker.reference.digest": digest(manifest_bytes)},
    )
    if direct:
        target_bytes = manifest_bytes
        root_descriptor = deepcopy(platform_descriptor)
    else:
        children = [platform_descriptor, attestation_descriptor]
        for data in (attest_config, attest_layer, attest_manifest):
            files[blob_name(digest(data))] = data
        if second_amd64:
            alternative_config = json_bytes({**config, "config": {"Labels": {"fixture": "second"}}})
            alternative_manifest = json_bytes({
                "schemaVersion": 2, "mediaType": OCI_MANIFEST,
                "config": descriptor(alternative_config, OCI_CONFIG),
                "layers": [descriptor(compressed, OCI_GZIP_LAYER)],
            })
            for data in (alternative_config, alternative_manifest):
                files[blob_name(digest(data))] = data
            children.append(descriptor(alternative_manifest, OCI_MANIFEST,
                                       platform={"os": "linux", "architecture": "amd64"}))
        target_bytes = json_bytes({"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": children})
        files[blob_name(digest(target_bytes))] = target_bytes
        root_descriptor = descriptor(target_bytes, OCI_INDEX)
    mutate("target", root_descriptor)
    files["index.json"] = json_bytes({"schemaVersion": 2, "mediaType": OCI_INDEX,
                                       "manifests": [root_descriptor]})
    if compatibility_manifest:
        # Docker's compatibility manifest may list attestation too. OCI is authoritative.
        files["manifest.json"] = json_bytes([
            {"Config": blob_name(digest(config_bytes)), "Layers": [blob_name(digest(compressed))]},
            {"Config": blob_name(digest(attest_config)), "Layers": [blob_name(digest(attest_layer))]},
        ])
    return {
        "files": files, "image_id": digest(target_bytes),
        "platform_manifest_digest": digest(manifest_bytes), "config_digest": digest(config_bytes),
        "layer_digest": digest(compressed), "layer_size": len(compressed), "diff_id": digest(raw_layer),
        "members": {"root_index": "index.json", "target_index": blob_name(digest(target_bytes)),
                    "manifest": blob_name(digest(manifest_bytes)), "config": blob_name(digest(config_bytes)),
                    "layer": blob_name(digest(compressed)), "attestation_config": blob_name(digest(attest_config)),
                    "attestation_layer": blob_name(digest(attest_layer)),
                    "attestation_manifest": blob_name(digest(attest_manifest))},
    }


def classic_fixture(*, wrong_count=False, escaping_reference=False):
    raw_layer = synthetic_layer()
    diff_ids = [digest(raw_layer)] + (["sha256:" + "0" * 64] if wrong_count else [])
    config_bytes = json_bytes({"architecture": "amd64", "os": "linux",
                               "rootfs": {"type": "layers", "diff_ids": diff_ids}})
    config_name = digest(config_bytes).removeprefix("sha256:") + ".json"
    layer_name = "../outside/layer.tar" if escaping_reference else "synthetic-layer/layer.tar"
    return {
        "files": {config_name: config_bytes, "synthetic-layer/layer.tar": raw_layer,
                  "manifest.json": json_bytes([{"Config": config_name, "Layers": [layer_name]}])},
        "image_id": digest(config_bytes), "config_digest": digest(config_bytes),
        "layer_digest": digest(raw_layer), "layer_size": len(raw_layer), "diff_id": digest(raw_layer),
        "members": {"config": config_name, "layer": "synthetic-layer/layer.tar"},
    }


def assert_verified_fixture(evidence, fixture, archive_format):
    assert evidence["verified"] is True
    assert evidence["format"] == archive_format
    assert evidence["image_id"] == fixture["image_id"]
    assert evidence["platform"] == "linux/amd64"
    assert evidence["config_digest"] == fixture["config_digest"]
    assert evidence["platform_manifest_digest"] == fixture.get("platform_manifest_digest")
    assert evidence["layers"] == [{"digest": fixture["layer_digest"], "size_bytes": fixture["layer_size"],
                                   "diff_id": fixture["diff_id"]}]
    assert type(evidence["verified_blob_count"]) is int and evidence["verified_blob_count"] > 0
    assert "gpu_offline_verified" not in evidence and "fallback_image_verified" not in evidence


@pytest.mark.parametrize("direct", [False, True])
def test_oci_verifies_selected_identity_chain_and_preserves_archive(saved_image_tools, tmp_path, direct):
    fixture = oci_fixture(direct=direct)
    path = tmp_path / "synthetic-oci.tar"
    write_archive(path, fixture["files"])
    original = path.read_bytes()
    evidence = saved_image_tools.verify_saved_image(
        path, fixture["image_id"], platform_manifest_digest=fixture["platform_manifest_digest"],
    )
    assert_verified_fixture(evidence, fixture, "oci-manifest" if direct else "oci-index")
    assert path.read_bytes() == original


def test_oci_chain_takes_precedence_over_compatibility_manifest_with_attestation(saved_image_tools, tmp_path):
    fixture = oci_fixture(compatibility_manifest=True)
    path = tmp_path / "synthetic-oci-with-compat.tar"
    write_archive(path, fixture["files"])
    evidence = saved_image_tools.verify_saved_image(path, fixture["image_id"])
    assert_verified_fixture(evidence, fixture, "oci-index")


@pytest.mark.parametrize("member", [
    "root_index", "target_index", "manifest", "config", "layer",
    "attestation_config", "attestation_layer", "attestation_manifest",
])
def test_oci_rejects_tampered_bytes_at_every_referenced_chain_level(saved_image_tools, tmp_path, member):
    fixture = oci_fixture()
    name = fixture["members"][member]
    fixture["files"][name] = b"!" + fixture["files"][name][1:]
    path = tmp_path / "synthetic-tamper.tar"
    write_archive(path, fixture["files"])
    with pytest.raises(RuntimeError):
        saved_image_tools.verify_saved_image(path, fixture["image_id"])


@pytest.mark.parametrize("issue", [
    ("target", "size", 1), ("platform", "size", True),
    ("config", "size", "1"), ("layer", "size", -1),
])
def test_oci_rejects_incorrect_or_noninteger_descriptor_sizes(saved_image_tools, tmp_path, issue):
    fixture = oci_fixture(descriptor_issue=issue)
    path = tmp_path / "synthetic-descriptor.tar"
    write_archive(path, fixture["files"])
    with pytest.raises(RuntimeError):
        saved_image_tools.verify_saved_image(path, fixture["image_id"])


@pytest.mark.parametrize("option", ["second_amd64", "wrong_diff_id", "invalid_gzip", "malformed_layer_digest"])
def test_oci_rejects_ambiguous_platform_or_invalid_layer_chain(saved_image_tools, tmp_path, option):
    fixture = oci_fixture(**{option: True})
    path = tmp_path / "synthetic-invalid-chain.tar"
    write_archive(path, fixture["files"])
    with pytest.raises(RuntimeError):
        saved_image_tools.verify_saved_image(path, fixture["image_id"])


def test_oci_rejects_missing_referenced_layer(saved_image_tools, tmp_path):
    fixture = oci_fixture()
    del fixture["files"][fixture["members"]["layer"]]
    path = tmp_path / "synthetic-missing-layer.tar"
    write_archive(path, fixture["files"])
    with pytest.raises(RuntimeError):
        saved_image_tools.verify_saved_image(path, fixture["image_id"])


def test_oci_rejects_non_amd64_platform(saved_image_tools, tmp_path):
    fixture = oci_fixture(architecture="arm64")
    path = tmp_path / "synthetic-arm64.tar"
    write_archive(path, fixture["files"])
    with pytest.raises(RuntimeError):
        saved_image_tools.verify_saved_image(path, fixture["image_id"])


def test_oci_rejects_platform_digest_that_disagrees_with_runtime_inspect(saved_image_tools, tmp_path):
    fixture = oci_fixture()
    path = tmp_path / "synthetic-mismatched-platform.tar"
    write_archive(path, fixture["files"])
    with pytest.raises(RuntimeError):
        saved_image_tools.verify_saved_image(path, fixture["image_id"],
                                           platform_manifest_digest="sha256:" + "0" * 64)


def test_oci_rejects_duplicate_archive_member_even_with_identical_bytes(saved_image_tools, tmp_path):
    fixture = oci_fixture()
    path = tmp_path / "synthetic-duplicate-member.tar"
    write_archive(path, fixture["files"], duplicate=fixture["members"]["layer"])
    with pytest.raises(RuntimeError):
        saved_image_tools.verify_saved_image(path, fixture["image_id"])


def test_classic_verifies_config_identity_and_uncompressed_diff_ids(saved_image_tools, tmp_path):
    fixture = classic_fixture()
    path = tmp_path / "synthetic-classic.tar"
    write_archive(path, fixture["files"])
    evidence = saved_image_tools.verify_saved_image(path, fixture["image_id"])
    assert_verified_fixture(evidence, fixture, "docker-classic")


@pytest.mark.parametrize("member", ["config", "layer"])
def test_classic_rejects_config_or_layer_byte_tampering(saved_image_tools, tmp_path, member):
    fixture = classic_fixture()
    name = fixture["members"][member]
    fixture["files"][name] += b"TAMPER"
    path = tmp_path / "synthetic-classic-tamper.tar"
    write_archive(path, fixture["files"])
    with pytest.raises(RuntimeError):
        saved_image_tools.verify_saved_image(path, fixture["image_id"])


@pytest.mark.parametrize("option", ["wrong_count", "escaping_reference"])
def test_classic_rejects_diff_id_count_or_reference_escape(saved_image_tools, tmp_path, option):
    fixture = classic_fixture(**{option: True})
    path = tmp_path / "synthetic-classic-invalid.tar"
    write_archive(path, fixture["files"])
    with pytest.raises(RuntimeError):
        saved_image_tools.verify_saved_image(path, fixture["image_id"])


@pytest.mark.parametrize("archive_type", ["oci", "classic"])
def test_archives_cannot_claim_a_different_image_id(saved_image_tools, tmp_path, archive_type):
    fixture = oci_fixture() if archive_type == "oci" else classic_fixture()
    path = tmp_path / "synthetic-wrong-image-id.tar"
    write_archive(path, fixture["files"])
    with pytest.raises(RuntimeError):
        saved_image_tools.verify_saved_image(path, "sha256:" + "0" * 64)
