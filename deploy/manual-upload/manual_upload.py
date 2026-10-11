"""User-started B7 upload with one-use CurrentUser DPAPI credentials.

No network operation in --prepare or --self-test. --upload is an explicit user
action. Standard STOR with a fresh 128-bit random name is NOT atomic no-overwrite;
the FTP helper must check for existing names before STOR. No retries/deletions.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import time
from types import SimpleNamespace

import ftps_upload as ftp_helper

MANIFEST_NAME = "manual-upload.json"
CREDENTIAL_NAME = "credentials.dpapi"
CERTIFICATE_NAME = "ftp-peer.pem"
REMOTE_PREFIX = "b7-601aaf08-"
LIFETIME_SECONDS = 86400
DPAPI_ENTROPY = b"B2-B7 CurrentUser one-use FTPS credentials v1"
UI_FORBIDDEN = 1


class HandoffError(Exception):
    pass


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(value: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise HandoffError("dpapi_requires_windows")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    api = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    api.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_wchar_p if protect else ctypes.c_void_p,
                    ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                    ctypes.c_uint32, ctypes.POINTER(DataBlob)]
    api.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    value_buffer = ctypes.create_string_buffer(value)
    entropy_buffer = ctypes.create_string_buffer(DPAPI_ENTROPY)
    input_blob = DataBlob(len(value), ctypes.cast(value_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    entropy_blob = DataBlob(len(DPAPI_ENTROPY), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output_blob = DataBlob()
    description = "B2 B7 one-use upload credentials" if protect else None
    try:
        # CurrentUser only: deliberately do not set CRYPTPROTECT_LOCAL_MACHINE.
        if not api(ctypes.byref(input_blob), description, ctypes.byref(entropy_blob),
                   None, None, UI_FORBIDDEN, ctypes.byref(output_blob)):
            raise HandoffError("dpapi_protect_failed" if protect else "dpapi_unprotect_failed")
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.memset(value_buffer, 0, len(value_buffer))
        if output_blob.pbData:
            ctypes.memset(output_blob.pbData, 0, output_blob.cbData)
            kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))


def load_manifest(directory: Path) -> dict:
    manifest = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8-sig"))
    expected = {
        "schema_version": 1,
        "host": ftp_helper.HOST,
        "port": ftp_helper.PORT,
        "certificate_sha256": ftp_helper.PIN,
        "certificate_file": CERTIFICATE_NAME,
        "credentials_file": CREDENTIAL_NAME,
        "approved_tar_name": "fallback-image.tar",
        "expected_tar_bytes": ftp_helper.EXPECTED_SIZE,
        "expected_tar_sha256": ftp_helper.EXPECTED_SHA256,
        "remote_prefix": REMOTE_PREFIX,
        "upload_mode": "manual_stor_unique",
        "credential_lifetime_seconds": LIFETIME_SECONDS,
    }
    if not isinstance(manifest, dict) or manifest != expected:
        raise HandoffError("manifest_does_not_match_frozen_upload")
    # Reject bool-as-int and other numerically equal but malformed JSON values.
    for name in ("schema_version", "port", "expected_tar_bytes", "credential_lifetime_seconds"):
        if type(manifest[name]) is not int:
            raise HandoffError("manifest_integer_type_invalid")
    return manifest


def regular_file(path: Path, maximum_bytes: int | None = None):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
        raise HandoffError("expected_regular_non_reparse_file")
    if maximum_bytes is not None and info.st_size > maximum_bytes:
        raise HandoffError("credential_blob_too_large")
    return info


def prepare(target: Path) -> None:
    if target.name != CREDENTIAL_NAME or not target.parent.is_dir():
        raise HandoffError("invalid_credential_target")
    manifest = load_manifest(target.parent)
    if target.exists() or target.is_symlink():
        raise HandoffError("credential_target_already_exists")
    username, password = ftp_helper.credentials(sys.stdin)
    now = int(time.time())
    payload = {
        "schema_version": 1,
        "created_at_unix": now,
        "expires_at_unix": now + LIFETIME_SECONDS,
        "manifest_binding": manifest,
        "username": username,
        "password": password,
    }
    plain = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    protected = dpapi(plain, protect=True)
    # Exclusive create; never overwrite a previous handoff blob.
    with target.open("xb") as stream:
        stream.write(protected)
        stream.flush()
        os.fsync(stream.fileno())
    ftp_helper.emit("credentials_prepared", credentials_file=CREDENTIAL_NAME,
                    lifetime_seconds=LIFETIME_SECONDS, current_user_only=True,
                    plaintext_credentials_saved=False, network_used=False)


def decode_payload(blob: bytes, manifest: dict, *, now: int, unprotect=None) -> tuple[str, str]:
    if unprotect is None:
        unprotect = lambda value: dpapi(value, protect=False)
    try:
        payload = json.loads(unprotect(blob).decode("utf-8"))
    except HandoffError:
        raise
    except (ValueError, UnicodeError, TypeError):
        raise HandoffError("credential_payload_invalid") from None
    keys = {"schema_version", "created_at_unix", "expires_at_unix", "manifest_binding", "username", "password"}
    if not isinstance(payload, dict) or set(payload) != keys or type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise HandoffError("credential_payload_invalid")
    created, expires = payload["created_at_unix"], payload["expires_at_unix"]
    if type(created) is not int or type(expires) is not int or expires != created + LIFETIME_SECONDS or created > now + 60:
        raise HandoffError("credential_validity_invalid")
    if now >= expires:
        raise HandoffError("credentials_expired")
    if payload["manifest_binding"] != manifest:
        raise HandoffError("credential_manifest_binding_mismatch")
    credential_json = json.dumps({"username": payload["username"], "password": payload["password"]})
    return ftp_helper.credentials(io.StringIO(credential_json))


def file_identity(info) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def verify_tar_before_credentials(local_tar: Path, expected_size: int, expected_sha256: str) -> None:
    info = regular_file(local_tar)
    if info.st_size != expected_size:
        raise HandoffError("selected_tar_size_does_not_match_frozen_artifact")
    ftp_helper.emit("archive_verification_started", expected_bytes=expected_size,
                    credentials_accessed=False, network_used=False)
    digest = hashlib.sha256()
    total = 0
    started = time.monotonic()
    last_progress = started
    with local_tar.open("rb") as source:
        if file_identity(os.fstat(source.fileno())) != file_identity(info):
            raise HandoffError("selected_tar_changed_before_verification")
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            total += len(block)
            now = time.monotonic()
            if now - last_progress >= 30:
                ftp_helper.emit("archive_verification_progress", checked_bytes=total,
                                expected_bytes=expected_size, network_used=False)
                last_progress = now
        if file_identity(os.fstat(source.fileno())) != file_identity(info):
            raise HandoffError("selected_tar_changed_during_verification")
    if file_identity(regular_file(local_tar)) != file_identity(info):
        raise HandoffError("selected_tar_path_changed_during_verification")
    if total != expected_size:
        raise HandoffError("selected_tar_read_length_mismatch")
    if digest.hexdigest() != expected_sha256:
        raise HandoffError("selected_tar_sha256_does_not_match_frozen_artifact")
    ftp_helper.emit("archive_verification_passed", checked_bytes=total,
                    sha256=expected_sha256, elapsed_seconds=round(time.monotonic() - started, 1),
                    credentials_accessed=False, network_used=False)


def upload(local_tar: Path) -> None:
    directory = Path(__file__).resolve().parent
    manifest = load_manifest(directory)
    if local_tar.name != manifest["approved_tar_name"]:
        raise HandoffError("selected_tar_name_does_not_match_frozen_artifact")
    verify_tar_before_credentials(local_tar, manifest["expected_tar_bytes"], manifest["expected_tar_sha256"])
    certificate = directory / manifest["certificate_file"]
    regular_file(certificate, maximum_bytes=65536)
    ftp_helper.build_context(certificate, manifest["certificate_sha256"])
    credential_file = directory / manifest["credentials_file"]
    info = regular_file(credential_file, maximum_bytes=65536)
    blob = credential_file.read_bytes()
    username, password = decode_payload(blob, manifest, now=int(time.time()))
    current = regular_file(credential_file, maximum_bytes=65536)
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns):
        raise HandoffError("credential_file_changed_before_consumption")
    remote_name = manifest["remote_prefix"] + secrets.token_hex(16) + ".tar"
    ftp_helper.checked_name(remote_name)
    args = SimpleNamespace(host=manifest["host"], port=manifest["port"],
                           trusted_cert=str(certificate), approved_pin=manifest["certificate_sha256"],
                           local_tar=str(local_tar), remote_name=remote_name,
                           max_seconds=86400, manual_stor_unique=True)
    # Consume before any connection. A failed upload requires a new handoff.
    credential_file.unlink()
    ftp_helper.emit("credentials_consumed", one_use=True,
                    upload_mode="manual_stor_unique", atomic_no_overwrite=False,
                    no_automatic_retry_or_remote_delete=True)
    original_stdin = sys.stdin
    credential_stream = io.StringIO(json.dumps({"username": username, "password": password}))
    try:
        sys.stdin = credential_stream
        ftp_helper.run_upload(args)
    finally:
        sys.stdin = original_stdin
        credential_stream.close()


def self_test() -> None:
    # Fake DPAPI output only: no Windows key access, file writes, or network.
    manifest = {"fake": "manifest"}
    now = 2000000000
    expired = {"schema_version": 1, "created_at_unix": now - LIFETIME_SECONDS,
               "expires_at_unix": now, "manifest_binding": manifest,
               "username": "fake", "password": "fake"}
    try:
        decode_payload(b"fake-encrypted-blob", manifest, now=now,
                       unprotect=lambda value: json.dumps(expired).encode("utf-8"))
    except HandoffError as exc:
        assert str(exc) == "credentials_expired"
    else:
        raise AssertionError("expired credentials accepted")
    try:
        decode_payload(b"fake-encrypted-blob", manifest, now=now,
                       unprotect=lambda value: b"invalid-json")
    except HandoffError as exc:
        assert str(exc) == "credential_payload_invalid"
    else:
        raise AssertionError("invalid credentials accepted")
    # Exercise upload() ordering using small in-memory fake files. Neither the
    # real 9 GB archive nor a DPAPI credential file is read by these tests.
    from unittest import mock
    info = SimpleNamespace(st_mode=stat.S_IFREG, st_dev=1, st_ino=2, st_size=5,
                           st_mtime_ns=3, st_file_attributes=0)
    test_manifest = {"approved_tar_name": "fallback-image.tar", "expected_tar_bytes": 5,
                     "expected_tar_sha256": hashlib.sha256(b"abcde").hexdigest()}
    for content, reason in (
        (b"wrong", "selected_tar_sha256_does_not_match_frozen_artifact"),
        (b"abc", "selected_tar_read_length_mismatch"),
    ):
        memory = io.BytesIO(content)
        source = mock.MagicMock()
        source.__enter__.return_value = source
        source.fileno.return_value = 123
        source.read.side_effect = memory.read
        path = mock.MagicMock(spec=Path)
        path.name = "fallback-image.tar"
        path.lstat.return_value = info
        path.open.return_value = source
        protected = mock.Mock()
        with mock.patch.dict(globals(), {"load_manifest": lambda directory: test_manifest, "dpapi": protected}), \
             mock.patch.object(os, "fstat", return_value=info), \
             mock.patch.object(Path, "read_bytes") as credential_read, \
             mock.patch.object(ftp_helper, "build_context") as context_build, \
             mock.patch.object(ftp_helper, "run_upload") as network_upload, \
             mock.patch.object(ftp_helper, "emit"):
            try:
                upload(path)
            except HandoffError as exc:
                assert str(exc) == reason
            else:
                raise AssertionError("invalid archive accepted before credentials")
            assert not credential_read.called and not protected.called
            assert not context_build.called and not network_upload.called
        memory.close()
    ftp_helper.emit("manual_self_test_passed", checks=["expired_payload_rejected", "invalid_payload_rejected",
                    "wrong_archive_hash_rejected_before_dpapi_and_network",
                    "truncated_archive_rejected_before_dpapi_and_network"],
                    actual_dpapi_roundtrip_verified=False, network_used=False,
                    platform_stor_verified=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--upload", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    parser.add_argument("--credentials-path")
    parser.add_argument("--local-tar")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.prepare:
            if not args.credentials_path or args.local_tar:
                raise HandoffError("prepare_requires_only_credential_target")
            prepare(Path(args.credentials_path).absolute())
        else:
            if not args.local_tar or args.credentials_path:
                raise HandoffError("upload_requires_only_local_tar")
            upload(Path(args.local_tar).absolute())
        return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, (HandoffError, ftp_helper.UploadError)) else None
        ftp_helper.emit("manual_upload_failed", exception_type=type(exc).__name__, reason=reason,
                        ftp_reply_code=ftp_helper.reply_code(exc),
                        no_automatic_retry_or_remote_delete=True, competition_submission_performed=False)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
