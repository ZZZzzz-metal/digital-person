"""Verify a saved image's content-addressed identity without extracting its tar.

Supports Docker classic configuration IDs and OCI index/manifest IDs. This is
archive integrity evidence, not a Docker load, GPU run, or competition result.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import re
import tarfile
from typing import Any
import zlib


INDEX_TYPES = {"application/vnd.oci.image.index.v1+json",
               "application/vnd.docker.distribution.manifest.list.v2+json"}
MANIFEST_TYPES = {"application/vnd.oci.image.manifest.v1+json",
                  "application/vnd.docker.distribution.manifest.v2+json"}
CONFIG_TYPES = {"application/vnd.oci.image.config.v1+json",
                "application/vnd.docker.container.image.v1+json"}
PLAIN_LAYERS = {"application/vnd.oci.image.layer.v1.tar",
                "application/vnd.docker.image.rootfs.diff.tar"}
GZIP_LAYERS = {"application/vnd.oci.image.layer.v1.tar+gzip",
               "application/vnd.docker.image.rootfs.diff.tar.gzip",
               "application/vnd.docker.image.rootfs.foreign.diff.tar.gzip"}
MAX_JSON_BYTES = 16 * 1024 * 1024


def _digest(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise RuntimeError("Saved image contains an invalid or unsupported digest")
    return value


def _path(value: Any) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
            or value.startswith("/") or re.match(r"^[A-Za-z]:", value)):
        raise RuntimeError("Saved image contains an unsafe archive path")
    while value.startswith("./"):
        value = value[2:]
    value = value.rstrip("/")
    if not value or any(part in ("", ".", "..") for part in value.split("/")):
        raise RuntimeError("Saved image contains an unsafe archive path")
    return value


def _json(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("Non-finite JSON constant")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError) as exc:
        raise RuntimeError("Saved image metadata is not valid unambiguous JSON") from exc


class _Archive:
    def __init__(self, archive: tarfile.TarFile):
        self.archive = archive
        self.members = {}
        self.hashes: dict[str, tuple[str, int]] = {}
        self.diff_hashes: dict[tuple[str, str], str] = {}
        for member in archive.getmembers():
            if member.isdir() and member.name in (".", "./"):
                continue
            name = _path(member.name)
            if name in self.members:
                raise RuntimeError("Saved image contains duplicate archive members")
            self.members[name] = member

    def member(self, name):
        name = _path(name)
        item = self.members.get(name)
        if item is None or not item.isfile():
            raise RuntimeError("Saved image is missing a required regular file")
        return item

    def read_json(self, name):
        item = self.member(name)
        if item.size > MAX_JSON_BYTES:
            raise RuntimeError("Saved image metadata exceeds the size limit")
        with self.archive.extractfile(item) as stream:
            return _json(stream.read())

    def hash(self, name):
        name = _path(name)
        item = self.member(name)
        if name not in self.hashes:
            digest = hashlib.sha256()
            size = 0
            with self.archive.extractfile(item) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            if size != item.size:
                raise RuntimeError("Saved image contains a truncated file")
            self.hashes[name] = ("sha256:" + digest.hexdigest(), size)
        return self.hashes[name]

    def blob(self, descriptor):
        if not isinstance(descriptor, dict):
            raise RuntimeError("Saved image contains an invalid descriptor")
        digest = _digest(descriptor.get("digest"))
        size = descriptor.get("size")
        if type(size) is not int or size < 0 or not isinstance(descriptor.get("mediaType"), str):
            raise RuntimeError("Saved image contains an invalid descriptor size or media type")
        name = "blobs/sha256/" + digest.split(":", 1)[1]
        if self.hash(name) != (digest, size):
            raise RuntimeError("Saved image blob digest or size mismatch")
        return name

    def diff_id(self, name, media_type):
        if media_type in PLAIN_LAYERS:
            return self.hash(name)[0]
        if media_type not in GZIP_LAYERS:
            raise RuntimeError("Saved image uses an unsupported runnable layer compression")
        key = (name, media_type)
        if key in self.diff_hashes:
            return self.diff_hashes[key]
        digest = hashlib.sha256()
        with self.archive.extractfile(self.member(name)) as source:
            with gzip.GzipFile(fileobj=source, mode="rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        self.diff_hashes[key] = "sha256:" + digest.hexdigest()
        return self.diff_hashes[key]


def _schema(value):
    if not isinstance(value, dict) or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 2:
        raise RuntimeError("Saved image index or manifest has an invalid schema version")


def _oci(store, image_id, expected_manifest):
    layout = store.read_json("oci-layout")
    if not isinstance(layout, dict) or layout.get("imageLayoutVersion") != "1.0.0":
        raise RuntimeError("Saved image OCI layout version is unsupported")
    outer = store.read_json("index.json")
    _schema(outer)
    roots = outer.get("manifests")
    if not isinstance(roots, list):
        raise RuntimeError("Saved image OCI root descriptors are invalid")
    matching = [item for item in roots if isinstance(item, dict) and item.get("digest") == image_id]
    if len(matching) != 1:
        raise RuntimeError("Saved image OCI entry point does not uniquely reference the verified image ID")
    root = matching[0]
    root_type = root.get("mediaType")
    if root_type not in INDEX_TYPES | MANIFEST_TYPES:
        raise RuntimeError("Saved image target is not a supported index or manifest")
    compatibility_records = set()

    def walk(descriptor, active=()):
        name = store.blob(descriptor)
        digest = descriptor["digest"]
        if digest in active or len(active) >= 32:
            raise RuntimeError("Saved image descriptor graph is cyclic or too deep")
        kind = descriptor["mediaType"]
        if kind not in INDEX_TYPES | MANIFEST_TYPES:
            return []
        document = store.read_json(name)
        _schema(document)
        if document.get("mediaType", kind) != kind:
            raise RuntimeError("Saved image descriptor media type mismatch")
        if kind in INDEX_TYPES:
            children = document.get("manifests")
            if not isinstance(children, list):
                raise RuntimeError("Saved image index has invalid child descriptors")
            candidates = []
            for child in children:
                candidates.extend(walk(child, active + (digest,)))
            return candidates

        config_descriptor = document.get("config")
        config_name = store.blob(config_descriptor)
        config = store.read_json(config_name)
        if not isinstance(config, dict):
            raise RuntimeError("Saved image configuration is invalid")
        descriptors = document.get("layers")
        if not isinstance(descriptors, list):
            raise RuntimeError("Saved image manifest has invalid layers")
        layers = []
        layer_names = []
        for layer in descriptors:
            layer_names.append(store.blob(layer))
            layers.append({"digest": layer["digest"], "size_bytes": layer["size"]})
        compatibility_records.add((config_name, tuple(layer_names)))

        platform = descriptor.get("platform")
        if platform is not None and not isinstance(platform, dict):
            raise RuntimeError("Saved image platform descriptor is invalid")
        annotations = descriptor.get("annotations", {})
        if not isinstance(annotations, dict):
            raise RuntimeError("Saved image descriptor annotations are invalid")
        attestation = annotations.get("vnd.docker.reference.type") == "attestation-manifest"
        eligible = not attestation and (platform is None or (
            platform.get("os") == "linux" and platform.get("architecture") == "amd64"))
        if not eligible:
            return []
        if config.get("os") != "linux" or config.get("architecture") != "amd64":
            raise RuntimeError("Saved image runnable configuration is not Linux amd64")
        if config_descriptor["mediaType"] not in CONFIG_TYPES:
            raise RuntimeError("Saved image runnable configuration media type is unsupported")
        rootfs = config.get("rootfs")
        if not isinstance(rootfs, dict) or rootfs.get("type") != "layers":
            raise RuntimeError("Saved image runnable configuration has no valid rootfs")
        diff_ids = rootfs.get("diff_ids")
        if not isinstance(diff_ids, list) or len(diff_ids) != len(layers):
            raise RuntimeError("Saved image configuration and layer counts differ")
        for entry, layer, name, expected in zip(layers, descriptors, layer_names, diff_ids):
            expected = _digest(expected)
            if store.diff_id(name, layer["mediaType"]) != expected:
                raise RuntimeError("Saved image uncompressed layer digest mismatch")
            entry["diff_id"] = expected
        return [{"platform_manifest_digest": digest, "config_digest": config_descriptor["digest"], "layers": layers}]

    candidates = walk(root)
    if len(candidates) != 1:
        raise RuntimeError("Saved image does not contain exactly one Linux amd64 runnable manifest")
    result = candidates[0]
    if expected_manifest is not None and result["platform_manifest_digest"] != expected_manifest:
        raise RuntimeError("Saved image platform manifest differs from the actual container")
    if "manifest.json" in store.members:
        entries = store.read_json("manifest.json")
        if not isinstance(entries, list) or not entries:
            raise RuntimeError("Saved image Docker compatibility manifest is invalid")
        selected = ("blobs/sha256/" + result["config_digest"].split(":", 1)[1],
                    tuple("blobs/sha256/" + layer["digest"].split(":", 1)[1] for layer in result["layers"]))
        matches = 0
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("Layers"), list):
                raise RuntimeError("Saved image Docker compatibility manifest is invalid")
            record = (_path(entry.get("Config")), tuple(_path(name) for name in entry["Layers"]))
            if record not in compatibility_records:
                raise RuntimeError("Saved image compatibility manifest is outside the verified OCI identity chain")
            matches += record == selected
        if matches != 1:
            raise RuntimeError("Saved image compatibility manifest does not uniquely match the runnable image")
    return {"format": "oci-index" if root_type in INDEX_TYPES else "oci-manifest", **result}


def _classic(store, image_id, expected_manifest):
    if expected_manifest is not None:
        raise RuntimeError("Classic saved image cannot prove a platform manifest digest")
    entries = store.read_json("manifest.json")
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise RuntimeError("Classic saved image is ambiguous")
    entry = entries[0]
    name = _path(entry.get("Config"))
    if store.hash(name)[0] != image_id:
        raise RuntimeError("Classic saved image configuration differs from the verified image ID")
    config = store.read_json(name)
    if not isinstance(config, dict) or config.get("os") != "linux" or config.get("architecture") != "amd64":
        raise RuntimeError("Classic saved image configuration is not Linux amd64")
    rootfs = config.get("rootfs")
    diff_ids = rootfs.get("diff_ids") if isinstance(rootfs, dict) and rootfs.get("type") == "layers" else None
    names = entry.get("Layers")
    if not isinstance(names, list) or not isinstance(diff_ids, list) or len(names) != len(diff_ids):
        raise RuntimeError("Classic saved image configuration and layer counts differ")
    layers = []
    for name, expected in zip(names, diff_ids):
        actual, size = store.hash(_path(name))
        if actual != _digest(expected):
            raise RuntimeError("Classic saved image layer digest mismatch")
        layers.append({"digest": actual, "size_bytes": size, "diff_id": actual})
    return {"format": "docker-classic", "platform_manifest_digest": None,
            "config_digest": image_id, "layers": layers}


def verify_saved_image(path: Path, image_id: str, *, platform_manifest_digest: str | None = None) -> dict:
    """Verify all referenced bytes and bind the runnable manifest to a fixed ID."""
    image_id = _digest(image_id)
    if platform_manifest_digest is not None:
        platform_manifest_digest = _digest(platform_manifest_digest)
    try:
        with tarfile.open(path, "r:*") as archive:
            store = _Archive(archive)
            if "index.json" in store.members or "oci-layout" in store.members:
                result = _oci(store, image_id, platform_manifest_digest)
            else:
                result = _classic(store, image_id, platform_manifest_digest)
            return {"verified": True, "image_id": image_id, "platform": "linux/amd64",
                    **result, "verified_blob_count": len(store.hashes)}
    except (OSError, EOFError, tarfile.TarError, ValueError, zlib.error) as exc:
        raise RuntimeError("Could not verify saved image archive bytes") from exc
