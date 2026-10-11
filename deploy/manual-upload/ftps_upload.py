"""One-shot, pinned, encrypted FTPS upload. No connection without --approved-pin.

Credentials: one JSON object on stdin with only username/password keys.
This program never prints server replies, account names, or passwords.
--self-test performs only local mocks, without opening any sockets.
"""
from __future__ import annotations

import argparse
import ftplib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import sys
import time
from unittest import mock

HOST = "183.222.230.93"
PORT = 50001
PIN = "a92d9e4cd61b1147eed8778af1b3aa6d9034c10f0aac82e3997418e41c63f86e"
EXPECTED_SIZE = 9322866688
EXPECTED_SHA256 = "0082322b4cac4637baffed4b3caae42a80ceb21322ded6a8e84c7b9647589742"
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,190}\Z")
MANUAL_NAME = re.compile(r"b7-601aaf08-[0-9a-f]{32}\.tar\Z")


class UploadError(Exception):
    pass


def emit(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=True), flush=True)


def checked_name(value: str) -> str:
    if not isinstance(value, str) or not SAFE_NAME.fullmatch(value):
        raise UploadError("unsafe_remote_basename")
    return value


def check_pin(sock, expected: str) -> None:
    cert = sock.getpeercert(binary_form=True)
    if not cert or hashlib.sha256(cert).hexdigest() != expected:
        raise UploadError("peer_certificate_pin_mismatch")


def reply_code(exc: BaseException) -> str | None:
    # Only the numeric reply prefix is allowed into logs.
    value = str(exc)
    return value[:3] if re.match(r"\A[1-5][0-9]{2}(?:\s|$)", value) else None


def safe_ftp_reason(exc: BaseException) -> str | None:
    value = str(exc).lower()
    for fragment, code in (("could not create file", "server_could_not_create_file"),
                           ("permission denied", "server_permission_denied"),
                           ("file name not allowed", "server_rejected_filename"),
                           ("quota", "server_quota_error"),
                           ("no space left", "server_no_space_left")):
        if fragment in value:
            return code
    return None


def remaining(deadline: float, ceiling: float = 120.0) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise UploadError("overall_timeout")
    return min(left, ceiling)


class PinnedFTPS(ftplib.FTP_TLS):
    def __init__(self, *, context, pin: str, deadline: float):
        super().__init__(context=context, timeout=30, encoding="utf-8")
        self.pin = pin
        self.deadline = deadline
        self.control_verified = False
        self.capture_transfer_reply = False
        self.transfer_reply = ""
        self.data_sessions: list[bool] = []
        # Ignore a PASV reply's advertised host; use the control connection peer.
        self.trust_server_pasv_ipv4_address = False

    def putcmd(self, line):
        self.timeout = remaining(self.deadline)
        if self.sock is not None:
            self.sock.settimeout(self.timeout)
        return super().putcmd(line)

    def getresp(self):
        response = super().getresp()
        if self.capture_transfer_reply and response.startswith("1"):
            self.transfer_reply = response
        return response

    def auth(self):
        response = super().auth()
        check_pin(self.sock, self.pin)
        self.control_verified = True
        return response

    def login(self, user="", passwd="", acct=""):
        if not self.control_verified or not isinstance(self.sock, ssl.SSLSocket):
            raise UploadError("login_requires_pinned_tls")
        check_pin(self.sock, self.pin)
        return super().login(user, passwd, acct)

    def ntransfercmd(self, cmd, rest=None):
        if not self.control_verified or not self._prot_p:
            raise UploadError("transfer_requires_protected_pinned_tls")
        check_pin(self.sock, self.pin)
        self.capture_transfer_reply = True
        self.transfer_reply = ""
        conn = None
        try:
            # FTP_TLS's default implementation does not reuse the control session.
            conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
            conn.settimeout(remaining(self.deadline))
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
            conn = self.context.wrap_socket(
                conn, server_hostname=self.host, session=self.sock.session
            )
            check_pin(conn, self.pin)
            self.data_sessions.append(bool(conn.session_reused))
            command = cmd.partition(" ")[0].upper()
            safe_command = command if command in {"NLST", "LIST", "MLSD", "STOR", "STOU", "RETR"} else "OTHER"
            emit("data_tls_connected", session_reused=bool(conn.session_reused),
                 transfer_command=safe_command,
                 send_buffer_bytes=conn.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF),
                 tls_version=conn.version())
            return conn, size
        except BaseException:
            if conn is not None:
                conn.close()
            raise
        finally:
            self.capture_transfer_reply = False


def build_context(cert_path: Path, approved_pin: str) -> ssl.SSLContext:
    if approved_pin.replace(":", "").lower() != PIN:
        raise UploadError("explicit_approved_pin_required")
    pem = cert_path.read_text(encoding="ascii")
    blocks = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", pem, re.S)
    if len(blocks) != 1 or pem.strip() != blocks[0]:
        raise UploadError("trust_file_must_contain_exactly_one_certificate")
    if hashlib.sha256(ssl.PEM_cert_to_DER_cert(blocks[0])).hexdigest() != PIN:
        raise UploadError("trust_file_pin_mismatch")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # The approved endpoint certificate has no CN/SAN. Required chain validation
    # is retained, and leaf pin verification replaces only the absent hostname.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cadata=pem)
    return context


def credentials(stream) -> tuple[str, str]:
    line = stream.readline(65537)
    if len(line) > 65536:
        raise UploadError("credential_input_too_large")
    value = json.loads(line)
    if not isinstance(value, dict) or set(value) != {"username", "password"}:
        raise UploadError("invalid_credential_input")
    user, password = value["username"], value["password"]
    for item in (user, password):
        if not isinstance(item, str) or not item or len(item) > 4096 or any(c in item for c in "\r\n\x00"):
            raise UploadError("invalid_credential_input")
    return user, password


def refuse_existing(ftp, name: str) -> None:
    # NLST uses the same encrypted, pinned data connection implementation.
    # A server error is not treated as an empty directory: fail closed.
    listed = ftp.nlst()
    for entry in listed:
        basename = entry.rsplit("/", 1)[-1]
        if basename == name or basename.startswith(name + "."):
            raise UploadError("requested_remote_name_or_residue_exists")


def stou_name(reply: str) -> str:
    match = re.search(r"(?:^|\s)FILE:\s*(.+?)\s*$", reply, re.I)
    if not match:
        raise UploadError("stou_actual_name_not_reported")
    name = match.group(1)
    if len(name) >= 2 and name[0] == name[-1] and name[0] in "\"'":
        name = name[1:-1]
    return checked_name(name)


def remote_hash(ftp, name: str) -> tuple[bool, str]:
    try:
        features = ftp.sendcmd("FEAT").upper()
    except ftplib.error_perm:
        return False, "feature_discovery_unavailable"
    methods = []
    if re.search(r"(?:^|\n)\s*XSHA256(?:\s|$)", features):
        methods.append("XSHA256")
    if re.search(r"(?:^|\n)\s*HASH(?:\s|$)", features):
        methods.append("HASH")
    if not methods:
        return False, "sha256_not_advertised"
    for method in methods:
        try:
            if method == "HASH":
                ftp.sendcmd("OPTS HASH SHA-256")
            response = ftp.sendcmd(method + " " + name)
        except ftplib.error_perm:
            continue
        hashes = re.findall(r"(?<![A-Za-z0-9])[a-fA-F0-9]{64}(?![A-Za-z0-9])", response)
        if not response.startswith("2") or len(hashes) != 1:
            continue
        if hashes[0].lower() != EXPECTED_SHA256:
            raise UploadError("remote_sha256_mismatch")
        return True, method
    return False, "advertised_sha256_unavailable_or_unparseable"


def identity(info) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def run_upload(args) -> None:
    if args.host != HOST or args.port != PORT:
        raise UploadError("unapproved_endpoint")
    name = checked_name(args.remote_name)
    manual_stor = getattr(args, "manual_stor_unique", False)
    if type(manual_stor) is not bool or (manual_stor and not MANUAL_NAME.fullmatch(name)):
        raise UploadError("manual_stor_requires_fresh_random_basename")
    if not name.endswith(".tar"):
        raise UploadError("requested_remote_name_requires_tar_extension")
    if not 60 <= args.max_seconds <= 172800:
        raise UploadError("invalid_max_seconds")
    local = Path(args.local_tar)
    info = local.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
        raise UploadError("local_tar_requires_regular_non_reparse_file")
    if info.st_size != EXPECTED_SIZE:
        raise UploadError("local_tar_size_mismatch")
    context = build_context(Path(args.trusted_cert), args.approved_pin)
    user, password = credentials(sys.stdin)
    deadline = time.monotonic() + args.max_seconds
    started = time.monotonic()
    ftp = PinnedFTPS(context=context, pin=PIN, deadline=deadline)
    transferred = 0
    actual_name = None
    phase = "connecting"
    try:
        ftp.connect(HOST, PORT, timeout=remaining(deadline, 30))
        phase = "authenticating_tls"
        ftp.auth()  # Pin is checked before USER/PASS is ever sent.
        phase = "logging_in"
        ftp.login(user, password)
        user = password = ""
        phase = "protecting_data"
        ftp.prot_p()
        ftp.set_pasv(True)
        ftp.voidcmd("TYPE I")
        phase = "checking_remote_name"
        refuse_existing(ftp, name)
        emit("ready", expected_bytes=EXPECTED_SIZE, certificate_sha256=PIN,
             control_tls_version=ftp.sock.version(), encrypted_data_required=True,
             local_sha256_verified_this_run=False, expected_local_sha256=EXPECTED_SHA256,
             transfer_mode="STOR" if manual_stor else "STOU",
             atomic_no_overwrite=not manual_stor)
        last_progress = time.monotonic()
        source_hash = hashlib.sha256()
        phase = "opening_local_source"
        with local.open("rb") as source:
            if identity(os.fstat(source.fileno())) != identity(info):
                raise UploadError("local_tar_changed_before_transfer")
            # User-started compatibility mode uses a fresh 128-bit random name
            # plus NLST preflight. STOR cannot promise atomic no-overwrite.
            phase = "opening_transfer"
            emit("transfer_requested", requested_remote_name=name,
                 transfer_mode="STOR" if manual_stor else "STOU")
            data = ftp.transfercmd(("STOR " if manual_stor else "STOU ") + name)
            try:
                phase = "resolving_remote_name"
                actual_name = name if manual_stor else stou_name(ftp.transfer_reply)
                emit("upload_started", requested_remote_name=name, actual_remote_name=actual_name)
                phase = "transferring"
                while True:
                    data.settimeout(remaining(deadline))
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    data.sendall(block)
                    source_hash.update(block)
                    transferred += len(block)
                    now = time.monotonic()
                    if now - last_progress >= 30:
                        emit("progress", transferred_bytes=transferred, total_bytes=EXPECTED_SIZE,
                             elapsed_seconds=round(now - started, 1))
                        last_progress = now
                if identity(os.fstat(source.fileno())) != identity(info):
                    raise UploadError("local_tar_changed_during_transfer")
                phase = "closing_data_connection"
                data.settimeout(remaining(deadline))
                data.unwrap().close()
            finally:
                data.close()
        phase = "waiting_transfer_reply"
        ftp.voidresp()
        phase = "verifying_local_source"
        if transferred != EXPECTED_SIZE or identity(local.stat()) != identity(info):
            raise UploadError("local_transfer_length_or_identity_mismatch")
        if source_hash.hexdigest() != EXPECTED_SHA256:
            raise UploadError("uploaded_source_sha256_mismatch")
        phase = "verifying_remote_size"
        ftp.voidcmd("TYPE I")
        remote_size = ftp.size(actual_name)
        if remote_size != EXPECTED_SIZE:
            raise UploadError("remote_size_mismatch")
        phase = "verifying_remote_hash"
        hash_verified, hash_method = remote_hash(ftp, actual_name)
        emit("uploaded", actual_remote_name=actual_name, transferred_bytes=transferred,
             remote_size_bytes=remote_size, remote_size_verified=True,
             remote_hash_verified=hash_verified, remote_hash_method=hash_method,
             expected_sha256=EXPECTED_SHA256,
             uploaded_source_sha256=source_hash.hexdigest(), source_hash_verified=True,
             data_tls_session_reused=ftp.data_sessions,
             elapsed_seconds=round(time.monotonic() - started, 1),
             competition_submission_performed=False)
    except Exception as exc:
        emit("upload_not_verified", actual_remote_name=actual_name,
             transferred_bytes=transferred, phase=phase,
             ftp_reply_code=reply_code(exc), safe_ftp_reason=safe_ftp_reason(exc),
             no_remote_cleanup_performed=True)
        raise
    finally:
        # Close only this connection. No delete, rename or automatic retry.
        ftp.close()


def self_test() -> None:
    """Local security/control-flow tests only; no sockets or filesystem writes."""
    good_der = b"mock-certificate"
    good_pin = hashlib.sha256(good_der).hexdigest()
    good_sock = mock.Mock()
    good_sock.getpeercert.return_value = good_der
    check_pin(good_sock, good_pin)
    rejected = 0
    for der in (None, b"wrong-certificate"):
        bad_sock = mock.Mock()
        bad_sock.getpeercert.return_value = der
        try:
            check_pin(bad_sock, good_pin)
        except UploadError:
            rejected += 1
        else:
            raise AssertionError("bad certificate accepted")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ftp = PinnedFTPS(context=context, pin=good_pin, deadline=time.monotonic() + 60)
    ftp.sock = good_sock
    with mock.patch.object(ftplib.FTP_TLS, "login") as login_mock:
        try:
            ftp.login("never-print-this", "never-print-this")
        except UploadError:
            pass
        else:
            raise AssertionError("plaintext/unpinned login accepted")
        assert not login_mock.called
    for protected in (False, True):
        ftp.control_verified = protected
        ftp._prot_p = False
        with mock.patch.object(ftplib.FTP, "ntransfercmd") as transfer_mock:
            try:
                ftp.ntransfercmd("STOU sample.tar")
            except UploadError:
                pass
            else:
                raise AssertionError("unprotected transfer accepted")
            assert not transfer_mock.called
    ftp.control_verified = True
    ftp._prot_p = True
    bad_data = mock.Mock()
    bad_data.getpeercert.return_value = b"wrong-data-certificate"
    raw_data = mock.Mock()
    mock_context = mock.Mock()
    mock_context.wrap_socket.return_value = bad_data
    ftp.context = mock_context
    with mock.patch.object(ftplib.FTP, "ntransfercmd", return_value=(raw_data, None)):
        try:
            ftp.ntransfercmd("STOU sample.tar")
        except UploadError:
            pass
        else:
            raise AssertionError("wrong data pin accepted")
    assert bad_data.close.called and not bad_data.sendall.called
    assert mock_context.wrap_socket.call_args.kwargs["session"] is good_sock.session
    assert rejected == 2
    for invalid in ("../x.tar", "x\\y.tar", "x\r\nDELE x", "/x.tar", " x.tar"):
        try:
            checked_name(invalid)
        except UploadError:
            pass
        else:
            raise AssertionError("unsafe name accepted")
    assert stou_name("150 FILE: sample.tar") == "sample.tar"
    assert stou_name('150 FILE: "sample.tar.1"') == "sample.tar.1"
    listing = mock.Mock()
    listing.nlst.return_value = ["sample.tar.part"]
    try:
        refuse_existing(listing, "sample.tar")
    except UploadError:
        pass
    else:
        raise AssertionError("residue accepted")
    server = mock.Mock()
    server.sendcmd.side_effect = ["211-Features\n XSHA256\n211 End", "213 " + EXPECTED_SHA256]
    assert remote_hash(server, "sample.tar") == (True, "XSHA256")
    server.sendcmd.side_effect = ["211-Features\n HASH SHA-256;\n211 End", "200 SHA-256", "213 SHA-256 0-1 " + "0" * 64 + " sample.tar"]
    try:
        remote_hash(server, "sample.tar")
    except UploadError:
        pass
    else:
        raise AssertionError("remote hash mismatch accepted")
    server.sendcmd.side_effect = ["211-Features\n UTF8\n211 End"]
    assert remote_hash(server, "sample.tar") == (False, "sha256_not_advertised")
    assert credentials(io.StringIO('{"username":"fake","password":"fake"}\n')) == ("fake", "fake")
    assert reply_code(ftplib.error_perm("530 account must never appear in logs")) == "530"
    emit("self_test_passed", no_network=True,
         checks=["certificate_rejection", "login_before_pin_rejected", "unencrypted_data_rejected",
                 "data_pin_rejected_before_bytes", "control_session_passed_to_data_tls",
                 "unsafe_basename_rejected", "stou_filename_parse", "residue_rejected",
                 "remote_sha256_match_and_mismatch", "missing_remote_hash_reported"],
         live_session_reuse_compatibility_verified=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--trusted-cert")
    parser.add_argument("--approved-pin")
    parser.add_argument("--local-tar")
    parser.add_argument("--remote-name")
    parser.add_argument("--max-seconds", type=int, default=86400)
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        else:
            if not all((args.trusted_cert, args.approved_pin, args.local_tar, args.remote_name)):
                raise UploadError("required_upload_arguments_missing")
            run_upload(args)
        return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, UploadError) else None
        emit("failed", exception_type=type(exc).__name__, reason=reason,
             safe_ftp_reason=safe_ftp_reason(exc),
             ftp_reply_code=reply_code(exc),
             no_automatic_delete_or_retry=True, competition_submission_performed=False)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
