"""Read-only B7 review-material verification; no model, network or Docker use."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


DIRECTORY_NAME = "AI技术赛道-数字人综合情感对话模型-AI队"
MANIFEST_NAME = "REVIEW-MANIFEST.json"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path(value: Any) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
            or ":" in value or value.startswith("/")
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise RuntimeError("Review materials contain an unsafe relative path")
    if value == MANIFEST_NAME:
        raise RuntimeError("Review manifest must not include itself")
    return value


def _not_link(path: Path) -> os.stat_result:
    item = path.lstat()
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(item.st_mode) or getattr(item, "st_file_attributes", 0) & reparse:
        raise RuntimeError("Review materials must not contain links")
    return item


def load_review_manifest(path: Path) -> dict:
    """Validate local or in-image metadata, without reading material contents."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("Non-finite constant")

    try:
        item = _not_link(path)
        if not stat.S_ISREG(item.st_mode) or item.st_size > MAX_MANIFEST_BYTES:
            raise RuntimeError("Review manifest is not a supported regular file")
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                          parse_constant=constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeError("Could not read an unambiguous review manifest") from exc
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
            or data["schema_version"] != 1 or data.get("directory_name") != DIRECTORY_NAME
            or not isinstance(data.get("code_commit"), str)
            or re.fullmatch(r"[0-9a-f]{40}", data["code_commit"]) is None):
        raise RuntimeError("Review manifest identity or version is invalid")
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("Review manifest requires material files")
    seen = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256", "source"}:
            raise RuntimeError("Review manifest file fields are invalid")
        name = _path(entry["path"])
        if name in seen:
            raise RuntimeError("Review manifest contains duplicate files")
        seen.add(name)
        if (type(entry["bytes"]) is not int or entry["bytes"] < 0
                or not isinstance(entry["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None
                or not isinstance(entry["source"], str) or not entry["source"].strip()):
            raise RuntimeError("Review manifest file metadata is invalid")
    return data


def verify_review_materials(directory: Path, expected_manifest_path: Path | None = None,
                            *, expected_manifest_sha256: str | None = None) -> dict:
    """Match the exact directory/file set and actual bytes to frozen metadata."""
    directory = Path(directory)
    try:
        if directory.name != DIRECTORY_NAME or not stat.S_ISDIR(_not_link(directory).st_mode):
            raise RuntimeError("Review materials directory identity is invalid")
        manifest_path = directory / MANIFEST_NAME
        manifest = load_review_manifest(manifest_path)
        manifest_sha = _sha(manifest_path)
        if expected_manifest_path is not None:
            expected_manifest_path = Path(expected_manifest_path)
            load_review_manifest(expected_manifest_path)
            expected = _sha(expected_manifest_path)
            if expected_manifest_sha256 is not None and expected_manifest_sha256 != expected:
                raise RuntimeError("Expected review manifest identities differ")
            expected_manifest_sha256 = expected
        if expected_manifest_sha256 is not None:
            if (not isinstance(expected_manifest_sha256, str)
                    or re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) is None
                    or manifest_sha != expected_manifest_sha256):
                raise RuntimeError("Image review manifest differs from the frozen local manifest")
        expected_files = {entry["path"] for entry in manifest["files"]} | {MANIFEST_NAME}
        expected_dirs = set()
        for name in expected_files:
            parts = name.split("/")
            expected_dirs.update("/".join(parts[:index]) for index in range(1, len(parts)))
        actual_files = set()
        actual_dirs = set()
        for current, names, files in os.walk(directory, followlinks=False):
            current = Path(current)
            for name in names:
                child = current / name
                if not stat.S_ISDIR(_not_link(child).st_mode):
                    raise RuntimeError("Review materials contain an invalid directory")
                actual_dirs.add(child.relative_to(directory).as_posix())
            for name in files:
                child = current / name
                if not stat.S_ISREG(_not_link(child).st_mode):
                    raise RuntimeError("Review materials contain a non-regular file")
                actual_files.add(child.relative_to(directory).as_posix())
        if actual_files != expected_files or actual_dirs != expected_dirs:
            raise RuntimeError("Review materials are missing files or contain extra files/directories")
        for entry in manifest["files"]:
            path = directory / entry["path"]
            if path.stat().st_size != entry["bytes"] or _sha(path) != entry["sha256"]:
                raise RuntimeError("Review material size or digest mismatch")
        return {"verified": True, "directory_name": DIRECTORY_NAME,
                "code_commit": manifest["code_commit"], "file_count": len(manifest["files"]),
                "total_bytes": sum(entry["bytes"] for entry in manifest["files"]),
                "manifest_sha256": manifest_sha, "files": manifest["files"]}
    except OSError as exc:
        raise RuntimeError("Could not read review material files") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--expected-manifest-sha256")
    args = parser.parse_args(argv)
    try:
        result = verify_review_materials(args.directory,
            expected_manifest_sha256=args.expected_manifest_sha256)
    except RuntimeError as exc:
        result = {"verified": False, "failure_type": type(exc).__name__, "failure": str(exc)}
    try:
        with args.report.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    except OSError:
        print(json.dumps({"verified": False, "failure": "Could not publish new material evidence"}))
        return 1
    print(json.dumps({key: result.get(key) for key in ("verified", "file_count", "manifest_sha256", "failure")},
                     ensure_ascii=False))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
