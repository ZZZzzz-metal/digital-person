"""Prepare immutable B7 reviewer documents; no downloads or model changes."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from review_materials import DIRECTORY_NAME, MANIFEST_NAME, verify_review_materials

A_REPORT_COMMIT = "f2c1fbd5638ef58f3f23130dc6dad4831814d126"
BASE_IMAGE_ID = "sha256:94f7c4741860ccc0bd1f8ad8ecae03c35806551c845b04e120f16ae33fbc1290"
A_FILES = (
    "reports/model/A2-数据来源与许可清单.md", "reports/model/A4-训练尝试记录.md",
    "reports/model/a4_training_short.json", "training/logs/sft-short.steps.jsonl",
    "reports/model/A5-评测结果.md", "reports/model/a5_eval_compare.json",
    "reports/model/A8-官方数据整理记录.md", "data/training/processed_official/official_samples_report.json",
)
B_FILES = (
    "reports/integration/B7-材料索引.md", "reports/integration/B7-技术方案.md",
    "reports/integration/B7-实验设计与报告.md", "reports/integration/B7-A交接核对.md",
    "reports/integration/B7-平台GPU尝试记录.md",
    "reports/integration/b6-gpu-offline.json", "reports/integration/b6-gpu-samples.json",
    "reports/integration/b6-gpu-environment.json", "deploy/requirements-gpu.actual.txt",
    "deploy/conda-gpu.actual.txt",
)

def prepare(repo: Path, source_export: Path, output: Path) -> dict:
    repo = repo.resolve()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    exported = json.loads(source_export.read_text(encoding="utf-8"))
    if exported["source_commit"] != A_REPORT_COMMIT:
        raise ValueError("A report source differs from the reviewed commit")
    entries = exported["files"]
    if len(entries) != len(A_FILES) or {e["path"] for e in entries} != set(A_FILES):
        raise ValueError("A report export is not the exact reviewed file set")
    payloads = []
    for item in entries:
        raw = item["content"].encode("utf-8")
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        if blob != item["git_blob_sha"]:
            raise ValueError("Exported A content differs from the GitHub blob identity")
        payloads.append(("A/" + item["path"], raw, "GitHub:" + A_REPORT_COMMIT + ":" + item["path"]))
    for name in B_FILES:
        path = repo / name
        raw = path.read_bytes()
        committed = subprocess.check_output(["git", "show", head + ":" + name], cwd=repo)
        # Git may normalize CRLF in working files; use committed bytes for snapshots.
        if raw.replace(b"\r\n", b"\n") != committed.replace(b"\r\n", b"\n"):
            raise ValueError("B material has uncommitted changes: " + name)
        target = "B/" + path.name if name.startswith("reports/integration/B7-") else "B/evidence/" + path.name
        payloads.append((target, committed, "Git:" + head + ":" + name))
    if output.exists():
        raise FileExistsError("Material output must be a new directory")
    if output.name != DIRECTORY_NAME:
        raise ValueError("Material directory must use the registered team name")
    output.mkdir(parents=True)
    files = []
    for name, raw, source in sorted(payloads):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
        files.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "source": source})
    manifest = {"schema_version": 1, "directory_name": DIRECTORY_NAME, "code_commit": head,
        "team_name": "AI队", "model_version": "b2-a-qwen2.5-0.5b-instruct-base-v1",
        "base_image_id": BASE_IMAGE_ID, "a_model_source_commit": "fce84b354ca0e6ab9cd1ec650198c0d45ab994bd",
        "a_report_commit": A_REPORT_COMMIT, "bundle_manifest_sha256": "c384dfbaa3b1e51558afb7db64e0628f778a4e157825f7a69a3f8b76de3150ca",
        "files": files}
    (output / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return verify_review_materials(output)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--a-source-export", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.repo, args.a_source_export, args.output), ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
