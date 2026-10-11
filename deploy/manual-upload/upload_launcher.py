"""User-operated Windows file chooser. No upload at import or in --self-test."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import datetime as dt
import json
from pathlib import Path
import secrets
import subprocess
import sys

DEFAULT_TAR = Path(r"D:\B2-B7-20261011\final-verified-20261011T093309Z\fallback-image.tar")
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
URL = "https://aigpu.migu.cn/worksubmit"


class OpenFileName(ctypes.Structure):
    _fields_ = [("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND),
                ("hInstance", wintypes.HINSTANCE), ("lpstrFilter", wintypes.LPCWSTR),
                ("lpstrCustomFilter", wintypes.LPWSTR), ("nMaxCustFilter", wintypes.DWORD),
                ("nFilterIndex", wintypes.DWORD), ("lpstrFile", wintypes.LPWSTR),
                ("nMaxFile", wintypes.DWORD), ("lpstrFileTitle", wintypes.LPWSTR),
                ("nMaxFileTitle", wintypes.DWORD), ("lpstrInitialDir", wintypes.LPCWSTR),
                ("lpstrTitle", wintypes.LPCWSTR), ("Flags", wintypes.DWORD),
                ("nFileOffset", wintypes.WORD), ("nFileExtension", wintypes.WORD),
                ("lpstrDefExt", wintypes.LPCWSTR), ("lCustData", ctypes.c_ssize_t),
                ("lpfnHook", ctypes.c_void_p), ("lpTemplateName", wintypes.LPCWSTR),
                ("pvReserved", ctypes.c_void_p), ("dwReserved", wintypes.DWORD),
                ("FlagsEx", wintypes.DWORD)]


def choose_file() -> Path | None:
    buffer = ctypes.create_unicode_buffer(str(DEFAULT_TAR), 32768)
    dialog = OpenFileName()
    dialog.lStructSize = ctypes.sizeof(dialog)
    dialog.lpstrFilter = "Docker镜像归档 (*.tar)\0*.tar\0\0"
    dialog.nFilterIndex = 1
    dialog.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
    dialog.nMaxFile = len(buffer)
    dialog.lpstrInitialDir = str(DEFAULT_TAR.parent)
    dialog.lpstrTitle = "选中已准备好的 fallback-image.tar，再点打开开始上传"
    dialog.lpstrDefExt = "tar"
    # Existing path/file, keep current directory, Explorer dialog.
    dialog.Flags = 0x00001000 | 0x00000800 | 0x00000008 | 0x00080000
    api = ctypes.WinDLL("comdlg32", use_last_error=True)
    api.GetOpenFileNameW.argtypes = [ctypes.POINTER(OpenFileName)]
    api.GetOpenFileNameW.restype = wintypes.BOOL
    api.CommDlgExtendedError.restype = wintypes.DWORD
    if api.GetOpenFileNameW(ctypes.byref(dialog)):
        return Path(buffer.value)
    if api.CommDlgExtendedError() != 0:
        raise RuntimeError("file_dialog_failed")
    return None


def display_event(event: dict) -> None:
    kind = event.get("event")
    if kind == "archive_verification_started":
        print("正在检查镜像文件完整性，请稍等。", flush=True)
    elif kind == "archive_verification_progress":
        print(f"镜像完整性检查 {event['checked_bytes'] / event['expected_bytes']:.1%}", flush=True)
    elif kind == "archive_verification_passed":
        print("镜像完整性检查通过，开始连接上传。", flush=True)
    elif kind == "remote_directory_precheck_started":
        print("正在检查服务器目录是否为空；客服要求同一时间只能有一个文件。请勿并行启动。", flush=True)
    elif kind == "remote_directory_precheck":
        if event.get("directory_empty") is True:
            print("服务器目录空目录检查通过，准备上传。", flush=True)
        else:
            print("服务器目录已有文件，上传停止。请保留日志并让负责本项目的 Agent 核查；程序不会删除远端文件。", flush=True)
    elif kind == "upload_started":
        print("此次作品文件名：" + event["actual_remote_name"], flush=True)
    elif kind == "progress":
        sent, total = event["transferred_bytes"], event["total_bytes"]
        print(f"已上传 {sent / total:.1%}（{sent / 1e9:.2f}/{total / 1e9:.2f} GB）", flush=True)
    elif kind == "manual_upload_failed":
        if event.get("reason") in {"remote_directory_not_empty", "requested_remote_name_or_residue_exists"}:
            print("服务器目录不是空目录，不能开始新上传。请勿重试或在网页提交残缺文件；需要人工确认目录清理后重新配置一次性凭据。", flush=True)
            return
        if event.get("reason") == "remote_directory_listing_invalid":
            print("无法确认服务器目录为空，上传已停止。请保留日志核查；程序不会按空目录继续。", flush=True)
            return
        if event.get("ftp_reply_code") == "553":
            print("服务器拒绝创建文件（553），已停止。请保留日志核查目录和存储权限；此时不能在网页提交。", flush=True)
            return
        reason = event.get("reason") or event.get("ftp_reply_code") or event.get("exception_type")
        print("上传未通过检查，停止。错误：" + str(reason), flush=True)


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        assert ctypes.sizeof(OpenFileName) == (152 if ctypes.sizeof(ctypes.c_void_p) == 8 else 88)
        assert DEFAULT_TAR.name == "fallback-image.tar"
        assert EDGE.name == "msedge.exe"
        print(json.dumps({"event": "launcher_self_test_passed", "file_dialog_opened": False,
                          "network_used": False, "edge_launched": False}))
        return 0
    if len(sys.argv) != 1:
        raise RuntimeError("unexpected_launcher_arguments")
    print("选择现成镜像后开始上传；窗口请保持打开，电脑不要睡眠。", flush=True)
    selected = choose_file()
    if selected is None:
        print("已取消，未上传。", flush=True)
        return 0
    directory = Path(__file__).resolve().parent
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
    log_path = directory / ("upload-" + stamp + ".jsonl")
    success = None
    with log_path.open("x", encoding="utf-8", newline="\n") as log:
        process = subprocess.Popen([sys.executable, str(directory / "manual_upload.py"),
                                    "--upload", "--local-tar", str(selected)],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True, encoding="utf-8", creationflags=0x08000000)
        assert process.stdout is not None
        try:
            for line in process.stdout:
                log.write(line)
                log.flush()
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                display_event(event)
                if event.get("event") == "uploaded" and event.get("remote_size_verified") is True and event.get("source_hash_verified") is True:
                    success = event
            result = process.wait()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
    if result != 0 or success is None:
        print("没有可提交的成功结果。请保留日志：" + str(log_path), flush=True)
        print("不要在网页选旧残缺文件；此程序不会自动重试。", flush=True)
        return result or 1
    name = success["actual_remote_name"]
    marker = directory / ("UPLOAD-SUCCESS-" + stamp + ".txt")
    marker.write_text("上传完成（不是赛事提交成功）。\n网页外部平台/西南一区，刷新作品选择，选择：\n" + name +
                      "\n然后由你点击提交作品。\n源文件SHA与远端字节数已检查；远端SHA验证：" +
                      str(success["remote_hash_verified"]) + "\n日志：" + str(log_path) + "\n", encoding="utf-8")
    print("上传完成。回网页选择：" + name + "，然后点击提交作品。", flush=True)
    print("文件名记录：" + str(marker), flush=True)
    if EDGE.is_file():
        subprocess.Popen([str(EDGE), URL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print("请用Edge打开：" + URL, flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("启动失败：" + type(exc).__name__ + "。没有自动重试，请保留窗口。", flush=True)
        raise SystemExit(1)
