"""Local mocks only: no platform, real archive, credentials, dialog, or Edge."""
from __future__ import annotations

from contextlib import ExitStack
import ctypes
import hashlib
import io
import json
from pathlib import Path
import socket
import stat
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import ftps_upload as ftp
import manual_upload as manual
import upload_launcher as launcher

ASSERTIONS = 0
BODY = b"small fake Docker archive for local tests"
NAME = "b7-601aaf08-" + "1234567890abcdef" * 2 + ".tar"
INFO = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0, st_dev=1,
                       st_ino=2, st_size=len(BODY), st_mtime_ns=3)


class Source(io.BytesIO):
    def fileno(self):
        return 987654321


class Log(io.StringIO):
    def close(self):
        # Permit inspection after the mocked context-manager closes.
        pass


class LocalOnly(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for method in ("socket", "create_connection"):
            self.stack.enter_context(mock.patch.object(
                socket, method, side_effect=AssertionError("real network forbidden")))

    def equal(self, first, second):
        global ASSERTIONS
        ASSERTIONS += 1
        self.assertEqual(first, second)

    def check(self, condition):
        global ASSERTIONS
        ASSERTIONS += 1
        self.assertTrue(condition)

    def failure(self, reason, call):
        global ASSERTIONS
        ASSERTIONS += 1
        with self.assertRaises(ftp.UploadError) as caught:
            call()
        self.equal(str(caught.exception), reason)


class TransferModeTests(LocalOnly):
    def setup_upload(self, *, manual=None, name=NAME, listed=(), listing_error=None,
                     remote_size=None):
        args = SimpleNamespace(host=ftp.HOST, port=ftp.PORT, remote_name=name,
                               local_tar="fake-only.tar", trusted_cert="fake-only.pem",
                               approved_pin=ftp.PIN, max_seconds=60)
        if manual is not None:
            args.manual_stor_unique = manual
        source = Source(BODY)
        archive = mock.Mock()
        archive.lstat.return_value = INFO
        archive.stat.return_value = INFO
        archive.open.return_value = source
        server = mock.Mock()
        server.sock.version.return_value = "TLSv1.3"
        server.nlst.return_value = list(listed)
        if listing_error is not None:
            server.nlst.side_effect = listing_error
        server.transfer_reply = "150 Opening BINARY data connection"
        if manual is None or manual is False:
            server.transfer_reply = "150 FILE: " + name + ".1"
        server.data_sessions = [True]
        server.size.return_value = len(BODY) if remote_size is None else remote_size
        server.sendcmd.return_value = "211-Features\n UTF8\n211 End"
        data = mock.Mock()
        server.transfercmd.return_value = data
        emitted = []
        self.stack.enter_context(mock.patch.object(ftp, "EXPECTED_SIZE", len(BODY)))
        self.stack.enter_context(mock.patch.object(ftp, "EXPECTED_SHA256", hashlib.sha256(BODY).hexdigest()))
        self.stack.enter_context(mock.patch.object(ftp, "Path", return_value=archive))
        self.stack.enter_context(mock.patch.object(ftp.os, "fstat", return_value=INFO))
        self.context = self.stack.enter_context(mock.patch.object(ftp, "build_context"))
        self.factory = self.stack.enter_context(mock.patch.object(ftp, "PinnedFTPS", return_value=server))
        self.stack.enter_context(mock.patch.object(ftp.sys, "stdin", io.StringIO(
            '{"username":"fake-user-never-log","password":"fake-password-never-log"}\n')))
        self.stack.enter_context(mock.patch.object(ftp, "emit", side_effect=
            lambda event, **fields: emitted.append({"event": event, **fields})))
        return args, server, data, emitted

    def test_manual_stor_normal_reply_and_verified_success(self):
        args, server, data, events = self.setup_upload(manual=True)
        ftp.run_upload(args)
        self.equal(server.transfercmd.call_args.args, ("STOR " + NAME,))
        self.equal(server.size.call_args.args, (NAME,))
        self.equal(data.sendall.call_args.args, (BODY,))
        ready = next(e for e in events if e["event"] == "ready")
        self.equal(ready["transfer_mode"], "STOR")
        self.equal(ready["atomic_no_overwrite"], False)
        done = next(e for e in events if e["event"] == "uploaded")
        self.equal(done["actual_remote_name"], NAME)
        self.check(done["remote_size_verified"] and done["source_hash_verified"])
        self.equal(done["remote_hash_verified"], False)
        self.equal(done["competition_submission_performed"], False)
        logs = json.dumps(events)
        self.check("fake-user-never-log" not in logs and "fake-password-never-log" not in logs)
        self.equal(server.close.call_count, 1)
        self.equal(server.delete.call_count, 0)
        self.equal(server.rename.call_count, 0)

    def test_default_stou_retained_and_uses_server_name(self):
        args, server, data, events = self.setup_upload(name="candidate.tar")
        ftp.run_upload(args)
        self.equal(server.transfercmd.call_args.args, ("STOU candidate.tar",))
        self.equal(server.size.call_args.args, ("candidate.tar.1",))
        ready = next(e for e in events if e["event"] == "ready")
        self.equal(ready["transfer_mode"], "STOU")
        self.equal(ready["atomic_no_overwrite"], True)
        done = next(e for e in events if e["event"] == "uploaded")
        self.equal(done["actual_remote_name"], "candidate.tar.1")

    def test_invalid_manual_names_rejected_before_ftp(self):
        for name in ("candidate.tar", "b7-601aaf08-" + "a" * 31 + ".tar",
                     "b7-601aaf08-" + "A" * 32 + ".tar"):
            with self.subTest(name=name):
                args, server, data, events = self.setup_upload(manual=True, name=name)
                self.failure("manual_stor_requires_fresh_random_basename",
                             lambda: ftp.run_upload(args))
                self.equal(self.factory.call_count, 0)
                self.equal(self.context.call_count, 0)

    def test_non_boolean_manual_mode_rejected_before_ftp(self):
        args, server, data, events = self.setup_upload(manual=1)
        self.failure("manual_stor_requires_fresh_random_basename", lambda: ftp.run_upload(args))
        self.equal(self.factory.call_count, 0)

    def test_existing_name_blocks_stor(self):
        args, server, data, events = self.setup_upload(manual=True, listed=[NAME])
        self.failure("requested_remote_name_or_residue_exists", lambda: ftp.run_upload(args))
        self.equal(server.transfercmd.call_count, 0)
        self.equal(server.close.call_count, 1)
        self.equal(server.delete.call_count, 0)

    def test_existing_residue_blocks_stor(self):
        args, server, data, events = self.setup_upload(manual=True, listed=["/upload/" + NAME + ".part"])
        self.failure("requested_remote_name_or_residue_exists", lambda: ftp.run_upload(args))
        self.equal(server.transfercmd.call_count, 0)
        self.equal(server.close.call_count, 1)

    def test_listing_failure_does_not_assume_empty_or_leak_reply(self):
        args, server, data, events = self.setup_upload(manual=True,
            listing_error=ftp.ftplib.error_perm("550 fake-secret-account denied"))
        global ASSERTIONS
        ASSERTIONS += 1
        with self.assertRaises(ftp.ftplib.error_perm):
            ftp.run_upload(args)
        self.equal(server.transfercmd.call_count, 0)
        self.equal(server.close.call_count, 1)
        self.check("fake-secret-account" not in json.dumps(events))

    def test_remote_size_failure_is_not_reported_uploaded(self):
        args, server, data, events = self.setup_upload(manual=True, remote_size=1)
        self.failure("remote_size_mismatch", lambda: ftp.run_upload(args))
        self.check(not any(e["event"] == "uploaded" for e in events))
        self.equal(server.transfercmd.call_count, 1)
        self.equal(server.delete.call_count, 0)
        self.equal(server.rename.call_count, 0)

    def test_stor_553_is_classified_at_opening_transfer_without_reply_leak(self):
        args, server, data, events = self.setup_upload(manual=True)
        original_reply = "553 Could not create file for fake-secret-account fake-secret-password"
        server.transfercmd.side_effect = ftp.ftplib.error_perm(original_reply)
        with self.assertRaises(ftp.ftplib.error_perm):
            ftp.run_upload(args)
        request = next(e for e in events if e["event"] == "transfer_requested")
        self.equal(request, {"event": "transfer_requested", "requested_remote_name": NAME,
                             "transfer_mode": "STOR"})
        failure = next(e for e in events if e["event"] == "upload_not_verified")
        self.equal(failure["phase"], "opening_transfer")
        self.equal(failure["ftp_reply_code"], "553")
        self.equal(failure["safe_ftp_reason"], "server_could_not_create_file")
        self.equal(failure["transferred_bytes"], 0)
        self.equal(failure["actual_remote_name"], None)
        self.equal(data.sendall.call_count, 0)
        self.check(not any(e["event"] in {"upload_started", "uploaded"} for e in events))
        logged = json.dumps(events)
        self.check(original_reply not in logged and "fake-secret-account" not in logged
                   and "fake-secret-password" not in logged)
        self.equal(server.close.call_count, 1)
        self.equal(server.delete.call_count, 0)
        self.equal(server.rename.call_count, 0)

    def test_data_tls_log_identifies_nlst_without_command_arguments(self):
        certificate = b"local-only-fake-certificate"
        control = mock.Mock()
        control.getpeercert.return_value = certificate
        data = mock.Mock()
        data.getpeercert.return_value = certificate
        data.session_reused = True
        data.getsockopt.return_value = 4 * 1024 * 1024
        data.version.return_value = "TLSv1.3"
        context = mock.Mock()
        context.wrap_socket.return_value = data
        client = ftp.PinnedFTPS(context=context, pin=hashlib.sha256(certificate).hexdigest(),
                                deadline=time.monotonic() + 60)
        client.sock = control
        client.host = "local-only-invalid-host"
        client.control_verified = True
        client._prot_p = True
        events = []
        with mock.patch.object(ftp.ftplib.FTP, "ntransfercmd", return_value=(mock.Mock(), None)), \
             mock.patch.object(ftp, "emit", side_effect=lambda event, **fields: events.append({"event": event, **fields})):
            client.ntransfercmd("NLST fake-private-directory")
        connected = next(e for e in events if e["event"] == "data_tls_connected")
        self.equal(connected["transfer_command"], "NLST")
        self.check("fake-private-directory" not in json.dumps(events))
        self.equal(data.sendall.call_count, 0)


class ManualDiagnosticTests(LocalOnly):
    def test_manual_main_reports_safe_553_classification_only(self):
        events = []
        original_reply = "553 Could not create file for fake-secret-account fake-secret-password"
        with mock.patch.object(manual.sys, "argv", ["manual_upload.py", "--upload", "--local-tar", "fake-only.tar"]), \
             mock.patch.object(manual, "upload", side_effect=ftp.ftplib.error_perm(original_reply)), \
             mock.patch.object(ftp, "emit", side_effect=lambda event, **fields: events.append({"event": event, **fields})):
            result = manual.main()
        self.equal(result, 1)
        self.equal(len(events), 1)
        self.equal(events[0]["event"], "manual_upload_failed")
        self.equal(events[0]["ftp_reply_code"], "553")
        self.equal(events[0]["safe_ftp_reason"], "server_could_not_create_file")
        self.equal(events[0]["reason"], None)
        logged = json.dumps(events)
        self.check(original_reply not in logged and "fake-secret-account" not in logged
                   and "fake-secret-password" not in logged)


class LauncherTests(LocalOnly):
    def run_launcher(self, event, exit_code=0):
        child = mock.Mock()
        child.stdout = io.StringIO(json.dumps(event) + "\n")
        child.wait.return_value = exit_code
        child.poll.return_value = exit_code
        log = Log()
        chooser = self.stack.enter_context(mock.patch.object(launcher, "choose_file", return_value=Path("fake-selected/fallback-image.tar")))
        process = self.stack.enter_context(mock.patch.object(launcher.subprocess, "Popen", return_value=child))
        marker = self.stack.enter_context(mock.patch.object(Path, "write_text"))
        self.stack.enter_context(mock.patch.object(Path, "open", return_value=log))
        self.stack.enter_context(mock.patch.object(Path, "is_file", return_value=True))
        self.stack.enter_context(mock.patch.object(launcher.sys, "argv", ["launcher.py"]))
        self.stack.enter_context(mock.patch.object(launcher.sys, "stdout", io.StringIO()))
        result = launcher.main()
        return result, chooser, process, marker, log

    def success_event(self):
        return {"event": "uploaded", "remote_size_verified": True,
                "source_hash_verified": True, "remote_hash_verified": False,
                "actual_remote_name": NAME}

    def test_windows_dialog_structure_layout(self):
        self.equal(ctypes.sizeof(launcher.OpenFileName),
                   152 if ctypes.sizeof(ctypes.c_void_p) == 8 else 88)
        self.equal(launcher.DEFAULT_TAR.name, "fallback-image.tar")

    def test_success_marker_requires_both_checks_and_zero_exit(self):
        result, chooser, process, marker, log = self.run_launcher(self.success_event())
        self.equal(result, 0)
        self.equal(chooser.call_count, 1)
        self.equal(process.call_count, 2)  # Child and Edge are both mocks.
        self.equal(marker.call_count, 1)
        self.check("不是赛事提交成功" in marker.call_args.args[0])
        self.check(NAME in marker.call_args.args[0])
        self.equal(process.call_args.args[0][1], launcher.URL)

    def test_missing_source_hash_prevents_marker_and_browser(self):
        event = self.success_event()
        event["source_hash_verified"] = False
        result, chooser, process, marker, log = self.run_launcher(event)
        self.equal(result, 1)
        self.equal(marker.call_count, 0)
        self.equal(process.call_count, 1)

    def test_missing_remote_size_prevents_marker_and_browser(self):
        event = self.success_event()
        event["remote_size_verified"] = False
        result, chooser, process, marker, log = self.run_launcher(event)
        self.equal(result, 1)
        self.equal(marker.call_count, 0)
        self.equal(process.call_count, 1)

    def test_nonzero_child_exit_prevents_marker_and_browser(self):
        result, chooser, process, marker, log = self.run_launcher(self.success_event(), exit_code=9)
        self.equal(result, 9)
        self.equal(marker.call_count, 0)
        self.equal(process.call_count, 1)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"event": "local_manual_handoff_mock_result",
                      "tests": result.testsRun, "assertions": ASSERTIONS,
                      "passed": result.wasSuccessful(), "network_used": False,
                      "real_archive_or_credentials_read": False,
                      "gui_opened": False, "edge_launched": False}))
    raise SystemExit(0 if result.wasSuccessful() else 1)
