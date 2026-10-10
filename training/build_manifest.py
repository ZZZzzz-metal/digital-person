#!/usr/bin/env python3
"""A6：生成权重清单（大小 + sha256）与许可信息。

输出：

- ``weights/MANIFEST.json`` —— 机器可读的完整清单
- ``weights/MANIFEST.md``   —— 人可读的交接清单
- ``reports/model/a6_weights_manifest.json`` —— 报告副本

清单覆盖三层内容：模型权重包（基础模型 + 候选模型）、数据文件、关键源码文件。
每个权重包给出逐文件的 sha256 与整包聚合摘要，方便 B/C 校验拿到的权重没被改动。

大权重不进 Git（见 ``weights/.gitignore``），所以这里同时标注哪些文件在仓库里，
哪些需要单独拷贝，避免交接时以为「仓库里就有权重」。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEIGHTS_DIR = REPO_ROOT / "weights"

BUNDLES = {
    "base-qwen2.5-0.5b-instruct": "base-qwen2.5-0.5b-instruct",
    "sft-short": "sft-short",
}

DATA_FILES = [
    "data/training/raw/sessions.jsonl",
    "data/training/processed/train.jsonl",
    "data/training/processed/valid.jsonl",
    "data/training/processed/holdout.jsonl",
    "data/training/processed/dataset_report.json",
    "data/eval/cases.json",
    "weights/inference_config.json",
]

CODE_FILES = [
    "src/b2_core/model.py",
    "src/b2_core/a_impl/dtos.py",
    "src/b2_core/a_impl/official_spec.py",
    "src/b2_core/a_impl/local_llm.py",
    "src/b2_core/a_impl/emotion_rules.py",
    "src/b2_core/prompts/empathy.py",
    "training/train_sft.py",
    "training/model_config.json",
    "data/training/build_dataset.py",
    "data/training/make_synthetic_sessions.py",
    "tests/model/run_eval.py",
    "tests/model/smoke_official.py",
    "tests/model/check_memory_effect.py",
]

LICENSES = {
    "base_model": {
        "name": "Qwen2.5-0.5B-Instruct",
        "source": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct",
        "license": "Apache-2.0",
        "license_file": "weights/LICENSES/Qwen2.5-0.5B-Instruct-LICENSE.txt",
        "note": "本地已下载的完整权重，推理与训练都不联网下载。",
    },
    "candidate_model": {
        "name": "b2-a-qwen2.5-0.5b-instruct-sft-short-v1",
        "source": "本仓库 training/train_sft.py 在 Qwen2.5-0.5B-Instruct 上的小规模本地适配产物",
        "license": "Apache-2.0（沿用基础模型许可）",
        "note": "只训练了最后 4 层 Transformer 与最终 norm，其余参数与基础模型一致。",
    },
    "training_data": {
        "name": "data/training/raw/sessions.jsonl",
        "source": "本仓库 data/training/make_synthetic_sessions.py 自动生成的虚构对话",
        "license": "内部虚构数据，不含任何真实个人信息",
        "note": "不是真人语料，也不是官方训练数据；只用于打通 A4 训练与交接链路。",
    },
    "eval_data": {
        "name": "data/eval/cases.json",
        "source": "A 手写的 12 个固定案例（MT1–MT6、BD1–BD6）、",
        "license": "内部自建评测案例，不含真实个人信息",
        "note": "不参与训练；用于基线与候选的同口径对比。",
    },
    "official_reference": {
        "name": "submission/official-reference/",
        "source": "比赛方提供的公开推理输入与 schema 参考",
        "license": "赛事方材料，按赛事规则使用",
        "note": "只读参考，不修改、不并入 A 的训练数据。",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成权重清单")
    parser.add_argument("--out", type=Path, default=WEIGHTS_DIR / "MANIFEST.json")
    return parser.parse_args()


def sha256_of(path: Path, chunk: int = 1 << 22) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def scan_bundle(directory: Path) -> dict:
    files = []
    if not directory.is_dir():
        return {"path": str(directory.relative_to(REPO_ROOT)), "exists": False, "files": []}
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        files.append(
            {
                "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_of(path),
            }
        )
    digest = hashlib.sha256()
    for record in files:
        digest.update(record["path"].encode("utf-8"))
        digest.update(record["sha256"].encode("ascii"))
    return {
        "path": str(directory.relative_to(REPO_ROOT)).replace("\\", "/"),
        "exists": True,
        "file_count": len(files),
        "total_bytes": sum(f["bytes"] for f in files),
        "total_mb": round(sum(f["bytes"] for f in files) / (1024 * 1024), 2),
        "bundle_sha256": digest.hexdigest(),
        "files": files,
    }


def scan_files(paths: list[str]) -> list[dict]:
    out = []
    for relative in paths:
        path = REPO_ROOT / relative
        if not path.is_file():
            out.append({"path": relative, "exists": False})
            continue
        out.append(
            {
                "path": relative,
                "exists": True,
                "bytes": path.stat().st_size,
                "sha256": sha256_of(path),
            }
        )
    return out


def human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} GB"


def main() -> int:
    args = parse_args()
    manifest = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "generator": "training/build_manifest.py",
        "repo_root": str(REPO_ROOT),
        "bundles": {},
        "data_files": scan_files(DATA_FILES),
        "code_files": scan_files(CODE_FILES),
        "licenses": LICENSES,
        "git_policy": {
            "committed_to_git": "weights/inference_config.json、weights/MANIFEST.*、weights/LICENSES/、"
            "weights/*.json、src/、tests/、training/、data/、reports/",
            "not_in_git": "weights/base-qwen2.5-0.5b-instruct/、weights/sft-short/（大权重，见 weights/.gitignore）",
            "handoff_note": "B/C 若需要真实引擎，必须另外拿这两个权重目录的实体文件；"
            "仓库里只有清单与指纹，clone 之后不会有权重。",
        },
    }

    for name, relative in BUNDLES.items():
        manifest["bundles"][name] = scan_bundle(WEIGHTS_DIR / relative)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# 权重与数据清单",
        "",
        f"生成时间：{manifest['generated_at']}",
        "",
        "## 权重包",
        "",
        "| 包 | 路径 | 文件数 | 总大小 | 整包 sha256 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, info in manifest["bundles"].items():
        if not info.get("exists"):
            lines.append(f"| {name} | {info['path']} | 0 | （缺失） | — |")
            continue
        lines.append(
            f"| {name} | `{info['path']}` | {info['file_count']} | {human(info['total_bytes'])} | "
            f"`{info['bundle_sha256']}` |"
        )
    lines += ["", "### 逐文件明细", ""]
    for name, info in manifest["bundles"].items():
        lines.append(f"#### {name}")
        lines.append("")
        if not info.get("exists"):
            lines.append("- 目录缺失")
            lines.append("")
            continue
        lines.append("| 文件 | 大小 | sha256 |")
        lines.append("| --- | --- | --- |")
        for record in info["files"]:
            lines.append(f"| `{record['name']}` | {human(record['bytes'])} | `{record['sha256']}` |")
        lines.append("")

    lines += ["## 数据文件", "", "| 文件 | 大小 | sha256 |", "| --- | --- | --- |"]
    for record in manifest["data_files"]:
        if not record.get("exists"):
            lines.append(f"| `{record['path']}` | （缺失） | — |")
        else:
            lines.append(f"| `{record['path']}` | {human(record['bytes'])} | `{record['sha256']}` |")

    lines += ["", "## 关键源码", "", "| 文件 | 大小 | sha256 |", "| --- | --- | --- |"]
    for record in manifest["code_files"]:
        if not record.get("exists"):
            lines.append(f"| `{record['path']}` | （缺失） | — |")
        else:
            lines.append(f"| `{record['path']}` | {human(record['bytes'])} | `{record['sha256']}` |")

    lines += [
        "",
        "## 许可与来源",
        "",
        "| 对象 | 来源 | 许可 |",
        "| --- | --- | --- |",
    ]
    for key, info in LICENSES.items():
        lines.append(f"| {key} | {info['source']} | {info['license']} |")
    lines += [
        "",
        "## Git 策略",
        "",
        f"- 进仓库：{manifest['git_policy']['committed_to_git']}",
        f"- 不进仓库：{manifest['git_policy']['not_in_git']}",
        f"- 交接提醒：{manifest['git_policy']['handoff_note']}",
        "",
    ]

    (args.out.parent / "MANIFEST.md").write_text("\n".join(lines), encoding="utf-8")

    report_path = REPO_ROOT / "reports" / "model" / "a6_weights_manifest.json"
    report_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"清单: {args.out}")
    print(f"清单: {args.out.parent / 'MANIFEST.md'}")
    for name, info in manifest["bundles"].items():
        if info.get("exists"):
            print(f"  {name}: {info['file_count']} 个文件, {human(info['total_bytes'])}, sha256={info['bundle_sha256'][:16]}...")
        else:
            print(f"  {name}: 缺失")
    for record in manifest["data_files"] + manifest["code_files"]:
        if not record.get("exists"):
            print(f"  警告：清单里的文件不存在 -> {record['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())