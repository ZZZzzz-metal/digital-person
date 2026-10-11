#!/usr/bin/env python3
"""生成"传到 GPU 容器"的清单：只列必要文件，逐文件核对 SHA256 与体积。

第 4 步要求"上传/取得官方数据与完整本地模型，放好仓库与配置"。本脚本回答
"到底要传什么、多大、传完怎么确认没传坏"，**不执行上传**。

会用 ``weights/MANIFEST.json`` 里已记录的真实 SHA256 做交叉核对：
本地文件与清单不一致时直接报错，避免把一个坏的基础模型传到 GPU 上才发现。

用法::

    python -X utf8 training/gpu/make_transfer_bundle.py --out weights/.scratch/transfer_manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEIGHTS_DIR = REPO_ROOT / "weights"

# 容器上要放的位置（第 4 步：/mnt/storage 是平台给的持久盘）
REMOTE_ROOT = "/mnt/storage/b2-a"

# 跑训练和评测必须有的代码，按目录整体带走
CODE_DIRS = ("src", "training", "tests", "data", "contracts")
CODE_FILES = ("README.md", "开始这里.md")

# 基础模型：训练和推理都要，必须是完整的 8 个文件
BASE_BUNDLE = "base-qwen2.5-0.5b-instruct"
BASE_REQUIRED = (
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "LICENSE",
)

# 本地已训好的候选：不是训练必需，但作为"已运行基线"要留一份
OPTIONAL_BUNDLES = ("sft-short",)

SKIP_DIRS = {"__pycache__", ".git", ".scratch", ".pytest_cache", "official_raw"}
SKIP_SUFFIX = {".pyc", ".pyo"}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_code() -> list[Path]:
    out: list[Path] = []
    for name in CODE_FILES:
        path = REPO_ROOT / name
        if path.is_file():
            out.append(path)
    for dirname in CODE_DIRS:
        root = REPO_ROOT / dirname
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix in SKIP_SUFFIX:
                continue
            out.append(path)
    return out


def load_manifest() -> dict:
    path = WEIGHTS_DIR / "MANIFEST.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_index(manifest: dict) -> dict[str, str]:
    """把 MANIFEST.json 压成 {仓库相对路径: sha256} 便于逐个核对。

    实际结构：``bundles`` 是以包名为键的 dict，每个包含 ``files`` 列表；
    另有 ``data_files`` / ``code_files`` / ``licenses`` 列表。
    """
    index: dict[str, str] = {}
    bundles = manifest.get("bundles") or {}
    iterable = bundles.values() if isinstance(bundles, dict) else bundles
    for bundle in iterable:
        if not isinstance(bundle, dict):
            continue
        for item in bundle.get("files", []):
            if isinstance(item, dict) and item.get("path"):
                index[item["path"]] = item.get("sha256")
    for key in ("data_files", "code_files", "licenses"):
        for item in manifest.get(key) or []:
            if isinstance(item, dict) and item.get("path"):
                index.setdefault(item["path"], item.get("sha256"))
    return index


def verify_against_manifest(path: Path, index: dict[str, str]) -> tuple[str | None, str | None]:
    """返回 (清单里的 sha256, 不匹配说明)。没记录在清单里的文件返回 (None, None)。"""
    try:
        rel = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return None, None
    recorded = index.get(rel)
    if not recorded:
        return None, None
    actual = sha256_of(path)
    if actual != recorded:
        return recorded, f"sha256 不一致：清单 {recorded[:12]}… 实际 {actual[:12]}…"
    return recorded, None


def add_file(records: list[dict], path: Path, category: str, remote_subdir: str,
             manifest: dict, problems: list[str]) -> int:
    if not path.is_file():
        problems.append(f"{category}: 缺少 {path}")
        return 0
    size = path.stat().st_size
    entry = {
        "category": category,
        "local": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "remote": f"{REMOTE_ROOT}/{remote_subdir}/{path.name}" if remote_subdir else f"{REMOTE_ROOT}/{path.name}",
        "bytes": size,
        "sha256": sha256_of(path),
    }
    recorded, mismatch = verify_against_manifest(path, manifest)
    if recorded:
        entry["manifest_sha256"] = recorded
        entry["matches_manifest"] = mismatch is None
    if mismatch:
        problems.append(f"{entry['local']}: {mismatch}")
    records.append(entry)
    return size


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 GPU 容器上传清单")
    parser.add_argument("--out", default="weights/.scratch/transfer_manifest.json")
    parser.add_argument("--no-optional", action="store_true", help="不含本地已训好的候选模型")
    args = parser.parse_args(argv)

    manifest = load_manifest()
    index = manifest_index(manifest)
    problems: list[str] = []
    records: list[dict] = []

    code_bytes = 0
    for path in collect_code():
        code_bytes += add_file(records, path, "code", "", index, problems)

    base_dir = WEIGHTS_DIR / BASE_BUNDLE
    base_bytes = 0
    for name in BASE_REQUIRED:
        base_bytes += add_file(records, base_dir / name, "base_model", BASE_BUNDLE, index, problems)

    optional_bytes = 0
    if not args.no_optional:
        for bundle_name in OPTIONAL_BUNDLES:
            bundle_dir = WEIGHTS_DIR / bundle_name
            if not bundle_dir.is_dir():
                continue
            for path in sorted(bundle_dir.rglob("*")):
                if path.is_file() and path.suffix != ".pyc":
                    optional_bytes += add_file(records, path, f"trained:{bundle_name}",
                                               bundle_name, index, problems)

    # 数据：训练样本是本地已有的合成/整理结果；官方数据到位后由 prepare_official_samples.py 追加
    processed = REPO_ROOT / "data" / "training" / "processed"
    data_bytes = 0
    for path in sorted(processed.glob("*.jsonl")) if processed.is_dir() else []:
        data_bytes += add_file(records, path, "training_data", "data/processed", index, problems)

    report = {
        "说明": "GPU 容器上传清单；只读本地文件并核对 SHA256，不执行上传。",
        "远端根目录": REMOTE_ROOT,
        "远端布局": {
            "仓库": f"{REMOTE_ROOT}/repo",
            "基础模型": f"{REMOTE_ROOT}/{BASE_BUNDLE}",
            "已训候选": f"{REMOTE_ROOT}/sft-short",
            "训练数据": f"{REMOTE_ROOT}/data/processed",
            "训练产物": f"{REMOTE_ROOT}/runs/<run_name>",
        },
        "体积": {
            "代码": {"文件数": sum(1 for r in records if r["category"] == "code"), "MB": round(code_bytes / 1e6, 2)},
            "基础模型": {"文件数": len(BASE_REQUIRED), "MB": round(base_bytes / 1e6, 1)},
            "训练数据": {"文件数": sum(1 for r in records if r["category"] == "training_data"),
                         "MB": round(data_bytes / 1e6, 2)},
            "已训候选_可选": {"文件数": sum(1 for r in records if r["category"].startswith("trained:")),
                              "MB": round(optional_bytes / 1e6, 1)},
            "合计": {"文件数": len(records), "MB": round(sum(r["bytes"] for r in records) / 1e6, 1)},
        },
        "容器磁盘": {"平台给的持久盘": "/mnt/storage 200G", "系统盘": "/ 186G 可用"},
        "核对了清单的文件数": sum(1 for r in records if "manifest_sha256" in r),
        "文件": records,
        "问题": problems,
        "注意": [
            "官方 train_public.jsonl / val_public.jsonl 不在本清单里：它不在这台机器上，需队伍提供。",
            "拿到官方数据后先用 training/gpu/prepare_official_samples.py 整理成 ≤200 条再上传。",
            "上传后必须在容器里重算 SHA256 与本清单比对，不能只看传输成功。",
        ],
    }

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    for key, value in report["体积"].items():
        print(f"{key:<16} {value['文件数']:>4} 个  {value['MB']:>9} MB")
    print(f"核对清单文件数   : {report['核对了清单的文件数']}")
    print(f"清单             : {out_path}")
    if problems:
        print(f"\nFAIL: {len(problems)} 个问题")
        for item in problems[:15]:
            print(f"  - {item}")
        return 1
    print("\nPASS: 清单生成，所有可比对文件与 weights/MANIFEST.json 一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())