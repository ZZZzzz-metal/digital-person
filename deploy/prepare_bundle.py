"""Build and verify the fixed B6 baseline bundle without loading any model.

Source manifests are trusted handoff inputs, not a replacement for a signed
release. Verification proves layout and byte integrity, not tensor validity,
GPU execution, model quality, or Docker/network isolation.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator


class BundleError(ValueError):
    """A fixed public category/message, without underlying exception text."""

    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


A_SOURCES = (
    "src/b2_core/model.py", "src/b2_core/a_impl/__init__.py",
    "src/b2_core/a_impl/dtos.py", "src/b2_core/a_impl/emotion_rules.py",
    "src/b2_core/a_impl/local_llm.py", "src/b2_core/a_impl/official_spec.py",
    "src/b2_core/prompts/__init__.py", "src/b2_core/prompts/empathy.py",
)
B_CORE = ("src/b2_core/__init__.py", "src/b2_core/contracts.py", "src/b2_core/store.py")
PARTICIPANT = ("__init__.py", "adapter.py", "run_inference.py", "check_output.py", "start.sh", "README.md")
OFFICIAL_SCHEMAS = ("contracts/official/inference_input.schema.json", "contracts/official/effective_submission.schema.json")
DEPLOY_SCHEMA = "contracts/deploy/bundle_manifest.schema.json"
CONFIG_PATH = "weights/inference_config.base.json"
MODEL_FILES = frozenset(("config.json", "generation_config.json", "LICENSE", "merges.txt",
                         "model.safetensors", "tokenizer.json", "tokenizer_config.json", "vocab.json"))
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise BundleError(code, message)


def _relative(value: Any) -> str:
    _require(isinstance(value, str) and bool(value) and "\\" not in value and ":" not in value
             and not any(ord(char) < 32 for char in value), "UNSAFE_PATH", "Paths must be canonical relative POSIX paths")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and all(part not in ("", ".", "..") for part in value.split("/"))
             and path.as_posix() == value, "UNSAFE_PATH", "Absolute, parent, and noncanonical paths are forbidden")
    return value


def _no_links(path: Path) -> None:
    for candidate in (*reversed(path.absolute().parents), path.absolute()):
        if os.path.lexists(candidate):
            mode = candidate.lstat()
            _require(not stat.S_ISLNK(mode.st_mode)
                     and not (getattr(mode, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)),
                     "UNSAFE_PATH", "Symbolic links and reparse points are forbidden")


def _root(path: Path | str) -> Path:
    result = Path(path).absolute()
    _no_links(result)
    _require(result.is_dir(), "SOURCE_MISSING", "Required source directory is missing")
    return result.resolve()


def _file(root: Path, relative: str) -> Path:
    result = root / _relative(relative)
    _no_links(result)
    _require(result.is_file() and stat.S_ISREG(result.stat().st_mode), "FILE_MISSING", "A required regular file is missing")
    return result


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> Any:
    _no_links(path)

    def unique(pairs: list[tuple[str, Any]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def constant(_: str) -> None:
        raise ValueError("nonfinite number")

    try:
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique, parse_constant=constant)
    except Exception:
        raise BundleError("INVALID_JSON", "A required JSON file is unreadable or ambiguous") from None


def _digest_entry(entry: Any) -> tuple[str, int]:
    _require(isinstance(entry, dict), "INVALID_MANIFEST", "Manifest entries must be objects")
    digest, size = entry.get("sha256"), entry.get("bytes")
    _require(isinstance(digest, str) and SHA_RE.fullmatch(digest) is not None
             and type(size) is int and size >= 0, "INVALID_MANIFEST", "Invalid digest or byte count")
    return digest, size


def _match(path: Path, digest: str, size: int | None = None) -> tuple[str, int]:
    _no_links(path)
    _require(path.is_file(), "FILE_MISSING", "A required source file is missing")
    actual_size = path.stat().st_size
    _require((size is None or actual_size == size) and _sha(path) == digest,
             "DIGEST_MISMATCH", "Source or bundle bytes differ from the expected digest")
    return digest, actual_size


def _inventory(root: Path) -> tuple[set[str], set[str]]:
    files, directories = set(), set()
    for current, dirs, names in os.walk(root, followlinks=False):
        for name in (*dirs, *names):
            candidate = Path(current) / name
            _no_links(candidate)
            relative = _relative(candidate.relative_to(root).as_posix())
            if candidate.is_dir():
                directories.add(relative)
            else:
                _require(stat.S_ISREG(candidate.stat().st_mode), "UNSAFE_PATH", "Special files are forbidden")
                files.add(relative)
    return files, directories


def _config_layout(config: Any) -> tuple[str, str]:
    _require(isinstance(config, dict), "INVALID_CONFIG", "Original model configuration must be an object")
    model_dir, license_file = _relative(config.get("model_dir")), _relative(config.get("license_file"))
    _require(isinstance(config.get("model_version"), str) and bool(config["model_version"].strip()),
             "INVALID_CONFIG", "Original configuration requires a model version")
    _require(config.get("patch_file") is None and config.get("adapter_dir") is None,
             "UNSUPPORTED_MODEL", "This bundle supports only the complete unpatched baseline")
    _require(not model_dir.startswith("LICENSES/") and license_file.startswith("LICENSES/"),
             "INVALID_CONFIG", "Model and license directories must preserve the original layout")
    return model_dir, license_file


def _expected_paths(config: dict) -> dict[str, str]:
    model_dir, license_file = _config_layout(config)
    expected = {path: "A" for path in A_SOURCES}
    expected.update({path: "B" for path in B_CORE})
    expected.update({name: "B" for name in PARTICIPANT})
    expected.update({path: "schema" for path in (*OFFICIAL_SCHEMAS, DEPLOY_SCHEMA)})
    expected[CONFIG_PATH] = "config"
    expected["weights/" + license_file] = "license"
    expected.update({"weights/" + model_dir + "/" + name: "model" for name in MODEL_FILES})
    _require(len(expected) == len(A_SOURCES) + len(B_CORE) + len(PARTICIPANT) + len(OFFICIAL_SCHEMAS) + 3 + len(MODEL_FILES),
             "INVALID_CONFIG", "Original configuration produces colliding bundle paths")
    return expected


def _schema_validate(manifest: dict, schema_path: Path) -> None:
    schema = _json(schema_path)

    def no_refs(value: Any) -> None:
        if isinstance(value, dict):
            _require(not any(key in value for key in ("$ref", "$dynamicRef")),
                     "INVALID_SCHEMA", "Deployment schema must not resolve external references")
            for item in value.values():
                no_refs(item)
        elif isinstance(value, list):
            for item in value:
                no_refs(item)

    no_refs(schema)
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(manifest)
    except Exception:
        raise BundleError("INVALID_MANIFEST", "Bundle manifest does not satisfy its deployment schema") from None


def verify_bundle(bundle_dir: Path | str) -> dict:
    """Recheck fixed required files as well as every manifest byte and path."""
    try:
        root = _root(bundle_dir)
        manifest_path = _file(root, "bundle_manifest.json")
        manifest = _json(manifest_path)
        _require(isinstance(manifest, dict) and type(manifest.get("version")) is int and manifest["version"] == 1,
                 "INVALID_MANIFEST", "Unsupported bundle manifest version")
        for key in ("code_commit", "a_source_commit"):
            _require(isinstance(manifest.get(key), str) and COMMIT_RE.fullmatch(manifest[key]) is not None,
                     "INVALID_MANIFEST", "Bundle source commits must be explicit full hashes")
        _require(manifest.get("config_path") == CONFIG_PATH, "INVALID_MANIFEST", "The fixed original configuration path is required")
        config = _json(_file(root, CONFIG_PATH))
        expected = _expected_paths(config)
        _require(manifest.get("model_version") == config["model_version"], "INVALID_MANIFEST", "Model version differs from original configuration")
        entries = manifest.get("files")
        _require(isinstance(entries, list) and len(entries) == len(expected), "INCOMPLETE_BUNDLE", "The complete fixed runtime and model files are required")
        seen: set[str] = set()
        total = 0
        for entry in entries:
            digest, size = _digest_entry(entry)
            _require(set(entry) == {"path", "role", "sha256", "bytes"}, "INVALID_MANIFEST", "Unexpected file-entry fields")
            relative = _relative(entry.get("path"))
            _require(relative.casefold() not in seen and relative in expected and entry.get("role") == expected[relative],
                     "INVALID_MANIFEST", "File paths must be unique members of the fixed bundle layout")
            seen.add(relative.casefold())
            _match(_file(root, relative), digest, size)
            if entry["role"] in ("model", "config", "license"):
                _require(size > 0, "INCOMPLETE_BUNDLE", "Model, tokenizer, configuration and license files cannot be empty")
            total += size
        expected_files = set(expected) | {"bundle_manifest.json"}
        actual_files, actual_dirs = _inventory(root)
        expected_dirs = {parent.as_posix() for path in expected_files for parent in PurePosixPath(path).parents if parent.as_posix() != "."}
        _require(actual_files == expected_files and actual_dirs == expected_dirs,
                 "EXTRA_FILES", "Missing, extra, or unlisted bundle content is forbidden")
        model_dir, license_file = _config_layout(config)
        _require(_sha(root / ("weights/" + license_file)) == _sha(root / ("weights/" + model_dir + "/LICENSE")),
                 "DIGEST_MISMATCH", "The original model license and preserved license copy differ")
        _schema_validate(manifest, _file(root, DEPLOY_SCHEMA))
        return {"verified": True, "file_count": len(entries), "total_bytes": total,
                "manifest_sha256": _sha(manifest_path), **{key: manifest[key] for key in
                ("code_commit", "a_source_commit", "model_version", "config_path")}}
    except BundleError:
        raise
    except Exception:
        raise BundleError("BUNDLE_IO", "Bundle verification could not read the required files") from None


def _checkout_commit(root: Path) -> str:
    """Read Git metadata only; no git process, checkout, or mutation."""
    marker = root / ".git"
    _no_links(marker)
    if marker.is_dir():
        git_dir = marker
    else:
        text = marker.read_text(encoding="utf-8").strip()
        _require(text.startswith("gitdir: "), "SOURCE_COMMIT", "Provide an explicit B source commit")
        git_dir = (root / text[8:]).resolve()
    _no_links(git_dir)
    head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
    if COMMIT_RE.fullmatch(head):
        return head
    _require(head.startswith("ref: refs/"), "SOURCE_COMMIT", "Provide an explicit B source commit")
    reference = _relative(head[5:])
    common = git_dir
    if (git_dir / "commondir").is_file():
        common = (git_dir / (git_dir / "commondir").read_text(encoding="utf-8").strip()).resolve()
    for directory in (git_dir, common):
        candidate = directory / reference
        _no_links(candidate)
        if candidate.is_file():
            return candidate.read_text(encoding="ascii").strip()
    packed = common / "packed-refs"
    _no_links(packed)
    if packed.is_file():
        for line in packed.read_text(encoding="ascii").splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[1] == reference:
                return fields[0]
    raise BundleError("SOURCE_COMMIT", "Provide an explicit B source commit")


def _publish_new_directory(stage: Path, output: Path) -> None:
    """Atomic no-replace publication on the supported Windows/Linux hosts."""
    if os.name == "nt":
        os.rename(stage, output)  # Windows refuses any existing destination.
    elif sys.platform.startswith("linux"):
        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, "renameat2", None)
        _require(rename is not None, "OUTPUT_UNSUPPORTED", "Atomic no-replace directory publication is unavailable")
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(stage), -100, os.fsencode(output), 1) != 0:
            number = ctypes.get_errno()
            if number in (errno.EEXIST, errno.ENOTEMPTY):
                raise BundleError("OUTPUT_EXISTS", "Bundle output must be a new directory")
            raise BundleError("BUNDLE_IO", "Could not publish the verified bundle directory")
    else:
        raise BundleError("OUTPUT_UNSUPPORTED", "Bundle preparation currently supports Windows and Linux hosts")


def prepare_bundle(project_root: Path | str, a_source_root: Path | str,
                   source_manifest_path: Path | str, asset_root: Path | str,
                   asset_manifest_path: Path | str, output_dir: Path | str,
                   source_commit: str | None = None) -> dict:
    """Copy only the fixed baseline after verifying all trusted source bytes."""
    stage: Path | None = None
    try:
        project, a_root, assets = _root(project_root), _root(a_source_root), _root(asset_root)
        output = Path(output_dir).absolute()
        _no_links(output)
        output = output.resolve()
        _require(not os.path.lexists(output), "OUTPUT_EXISTS", "Bundle output must be a new directory")
        _require(not any(output == source or source in output.parents for source in (a_root, assets)),
                 "UNSAFE_PATH", "Bundle output must not be inside its A source or asset tree")
        code_commit = source_commit if source_commit is not None else _checkout_commit(project)
        _require(isinstance(code_commit, str) and COMMIT_RE.fullmatch(code_commit) is not None,
                 "SOURCE_COMMIT", "Provide an explicit full B source commit")
        source_manifest = _json(Path(source_manifest_path))
        _require(isinstance(source_manifest, dict) and isinstance(source_manifest.get("main_sha"), str)
                 and COMMIT_RE.fullmatch(source_manifest["main_sha"]) is not None,
                 "INVALID_MANIFEST", "A handoff requires an explicit source commit")
        sources = source_manifest.get("A_readonly_review_copies")
        _require(isinstance(sources, list), "INVALID_MANIFEST", "A source handoff entries are required")
        source_index: dict[str, dict] = {}
        for entry in sources:
            _require(isinstance(entry, dict), "INVALID_MANIFEST", "A source entries must be objects")
            relative = _relative(entry.get("path"))
            _require(relative.casefold() not in source_index, "INVALID_MANIFEST", "Duplicate A source entries are forbidden")
            _digest_entry(entry)
            source_index[relative.casefold()] = entry
        _require(all(path in source_index for path in A_SOURCES), "INCOMPLETE_SOURCE", "All fixed A runtime source files are required")
        asset_manifest = _json(Path(asset_manifest_path))
        _require(isinstance(asset_manifest, dict), "INVALID_MANIFEST", "Asset handoff must be an object")
        asset_entries = asset_manifest.get("files")
        _require(isinstance(asset_entries, list), "INVALID_MANIFEST", "Complete baseline asset entries are required")
        asset_index: dict[str, dict] = {}
        for entry in asset_entries:
            _require(isinstance(entry, dict), "INVALID_MANIFEST", "Asset entries must be objects")
            name = _relative(entry.get("name"))
            _require("/" not in name and name not in asset_index, "INVALID_MANIFEST", "Asset names must be unique basenames")
            _digest_entry(entry)
            asset_index[name] = entry
        _require(set(asset_index) == MODEL_FILES, "INCOMPLETE_MODEL", "Exactly the eight complete baseline assets are required; shards and adapters are unsupported")
        config_record, license_record = asset_manifest.get("baseline_config"), asset_manifest.get("license_copy")
        _require(isinstance(config_record, dict) and isinstance(license_record, dict), "INVALID_MANIFEST", "Original configuration and license digests are required")
        for record in (config_record, license_record):
            _require(isinstance(record.get("sha256"), str) and SHA_RE.fullmatch(record["sha256"]) is not None,
                     "INVALID_MANIFEST", "Original configuration or license digest is invalid")
        config_file = _file(assets, "inference_config.base.json")
        config_digest, config_size = _match(config_file, config_record["sha256"])
        config = _json(config_file)
        model_dir, license_file = _config_layout(config)
        model_root = _root(assets / model_dir)
        model_inventory, model_dirs = _inventory(model_root)
        _require(model_inventory == MODEL_FILES and not model_dirs, "INCOMPLETE_MODEL", "Unlisted shards, indexes, or model files are forbidden")
        expected = _expected_paths(config)
        plan: list[tuple[Path, str, str, str, int]] = []

        def add(origin: Path, destination: str, role: str, digest: str | None = None, size: int | None = None) -> None:
            _no_links(origin)
            digest = _sha(origin) if digest is None else digest
            digest, actual_size = _match(origin, digest, size)
            plan.append((origin, destination, role, digest, actual_size))

        for path in B_CORE:
            add(_file(project, path), path, "B")
        for name in PARTICIPANT:
            add(_file(project, "submission/participant/" + name), name, "B")
        for path in A_SOURCES:
            digest, size = _digest_entry(source_index[path])
            add(_file(a_root, path), path, "A", digest, size)
        for path in OFFICIAL_SCHEMAS:
            add(_file(project, path), path, "schema")
        add(_file(project, "deploy/bundle_manifest.schema.json"), DEPLOY_SCHEMA, "schema")
        add(config_file, CONFIG_PATH, "config", config_digest, config_size)
        license_digest, license_size = _digest_entry(asset_index["LICENSE"])
        _require(license_record["sha256"] == license_digest, "DIGEST_MISMATCH", "License copy must match the model license")
        add(_file(assets, license_file), "weights/" + license_file, "license", license_digest, license_size)
        for name in sorted(MODEL_FILES):
            digest, size = _digest_entry(asset_index[name])
            add(_file(model_root, name), "weights/" + model_dir + "/" + name, "model", digest, size)
        _require({destination: role for _, destination, role, _, _ in plan} == expected,
                 "INCOMPLETE_BUNDLE", "Fixed bundle copy plan is incomplete")
        output.parent.mkdir(parents=True, exist_ok=True)
        _no_links(output.parent)
        stage = Path(tempfile.mkdtemp(prefix=".b6-bundle-", dir=output.parent))
        files = []
        for origin, destination, role, digest, size in sorted(plan, key=lambda item: item[1]):
            target = stage / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            _no_links(origin)
            shutil.copyfile(origin, target)
            _match(target, digest, size)
            files.append({"path": destination, "role": role, "sha256": digest, "bytes": size})
        manifest = {"version": 1, "code_commit": code_commit, "a_source_commit": source_manifest["main_sha"],
                    "model_version": config["model_version"], "config_path": CONFIG_PATH, "files": files}
        (stage / "bundle_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        verify_bundle(stage)
        _publish_new_directory(stage, output)
        stage = None
        return manifest
    except BundleError:
        raise
    except Exception:
        raise BundleError("BUNDLE_IO", "Bundle preparation failed; no verified bundle was published") from None
    finally:
        if stage is not None:
            # This uniquely named directory was created by this invocation only.
            shutil.rmtree(stage)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    for name in ("project_root", "a_source_root", "source_manifest_path", "asset_root", "asset_manifest_path", "output_dir"):
        prepare.add_argument("--" + name.replace("_", "-"), required=True, type=Path)
    prepare.add_argument("--source-commit")
    verify = commands.add_parser("verify")
    verify.add_argument("bundle_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare_bundle(**{key: value for key, value in vars(args).items() if key != "command"})
            result = verify_bundle(args.output_dir)
        else:
            result = verify_bundle(args.bundle_dir)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except BundleError as error:
        print(json.dumps({"verified": False, "code": error.code, "message": str(error)}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
