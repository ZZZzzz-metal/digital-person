#!/usr/bin/env python3
"""官方训练集 -> A 的小样本训练/验证集（≤200 条有效样本）。

用途：把官方的 ``train_public.jsonl`` / ``val_public.jsonl`` 按**预测点**整理成
A 的训练格式。这一步是第 5 步的数据准备，**不改官方原始数据**，只读不写。

硬性约束（全部来自交接要求，脚本逐条强制执行并在报告里计数）：

1. **参考答案不能进输入**。``history`` 只取 ``turn_id <= target_user_turn_id`` 的轮次，
   且必须**以目标 user 轮结尾**；被预测的那条 assistant 回复只作为监督目标
   （``target_json``），永远不出现在输入里。
2. **验证集独立**。验证样本只从 ``val_public.jsonl`` 取，绝不与训练集共用会话。
3. **隔离 4 个顺序异常点**。判定规则是通用的：要求
   ``assistant_response_turn_id > target_user_turn_id``（回复必须在目标 user 轮**之后**），
   并且 ``target.response_text`` 必须等于该 assistant 轮的正文。
   已知的 4 个点（B 的核对报告）另外用显式黑名单兜底，双重保证。
4. **去重**。训练集里 202 组完整对话各出现两份，只保留第一次出现。
5. **≤200 条**。确定性挑样（固定种子），尽量在 16 类情绪上均衡。

没有官方数据文件时脚本会明确报错，不会生成假数据。

用法::

    python -X utf8 training/gpu/prepare_official_samples.py \
        --train "<解压根>/训练-验证-数据集/train/train_public.jsonl" \
        --val   "<解压根>/训练-验证-数据集/val/val_public.jsonl" \
        --out-dir data/training/processed_official \
        --limit 200 --valid-limit 60
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 16 类官方情绪，与 src/b2_core/a_impl/official_spec.py 保持一致
EMOTIONS = (
    "joy", "gratitude", "relaxed", "care", "pride", "neutral", "surprise", "mixed",
    "sadness", "loneliness", "anxiety", "anger", "fear", "disgust", "shame", "helplessness",
)

PROFILE_KEYS = ("personality_traits", "interests", "style")

# B 在 reports/integration/官方包静态核对.md 里记录的 4 个顺序异常点：
# 这些预测点引用的是目标 user **之前** 的 assistant，不适合作为下一轮回复监督。
KNOWN_NONADJACENT = (
    ("train_conv_000628", 15, 14),
    ("train_conv_000817", 33, 32),
    ("train_conv_003644", 7, 6),
    ("train_conv_003695", 9, 8),
)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_jsonl(path: Path) -> tuple[list[dict], list[str]]:
    """读 JSONL；坏行记录成问题而不是崩掉。"""
    rows: list[dict] = []
    problems: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                problems.append(f"{path.name}:{lineno} JSON 解析失败: {exc}")
    return rows, problems


def check_record(rec: dict) -> list[str]:
    """结构校验，覆盖官方 train schema 的实际约束。"""
    bad: list[str] = []
    if not isinstance(rec.get("conversation_id"), str):
        bad.append("conversation_id 不是字符串")
    turns = rec.get("turns")
    if not isinstance(turns, list) or not turns:
        bad.append("turns 不是非空数组")
        return bad
    seen_ids: set[int] = set()
    for turn in turns:
        if not isinstance(turn, dict):
            bad.append("turn 不是对象")
            continue
        tid = turn.get("turn_id")
        if not isinstance(tid, int) or tid < 1:
            bad.append(f"turn_id 非法: {tid!r}")
        elif tid in seen_ids:
            bad.append(f"turn_id 重复: {tid}")
        else:
            seen_ids.add(tid)
        if turn.get("role") not in ("user", "assistant"):
            bad.append(f"role 非法: {turn.get('role')!r}")
        if not isinstance(turn.get("content"), str) or not turn["content"]:
            bad.append(f"turn {tid} content 为空")
        if set(turn) - {"turn_id", "role", "content"}:
            bad.append(f"turn {tid} 有多余字段")
    points = rec.get("prediction_points")
    if not isinstance(points, list):
        bad.append("prediction_points 不是数组")
    return bad


def complete_dialog_signature(turns: list[dict]) -> str:
    """完整对话指纹，用于去掉训练集里成对出现的重复会话。"""
    payload = json.dumps(
        [[t.get("role"), t.get("content")] for t in turns], ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_history(turns: list[dict], target_user_turn_id: int) -> list[dict] | None:
    """取到目标 user 轮为止的输入；保证目标 user 轮是最后一轮、且不含参考答案。"""
    ordered = sorted(turns, key=lambda t: t.get("turn_id", 0))
    history = [t for t in ordered if t.get("turn_id", 0) <= target_user_turn_id]
    if not history:
        return None
    last = history[-1]
    if last.get("turn_id") != target_user_turn_id or last.get("role") != "user":
        return None
    return [{"turn_id": t["turn_id"], "role": t["role"], "content": t["content"]} for t in history]


def check_target(target: dict) -> list[str]:
    bad: list[str] = []
    if not isinstance(target, dict):
        return ["target 不是对象"]
    text = target.get("response_text")
    if not isinstance(text, str) or not text.strip():
        bad.append("response_text 为空")
    if target.get("emotion_label") not in EMOTIONS:
        bad.append(f"emotion_label 不在 16 类里: {target.get('emotion_label')!r}")
    profile = target.get("user_profile")
    if not isinstance(profile, dict):
        bad.append("user_profile 不是对象")
    else:
        for key in PROFILE_KEYS:
            value = profile.get(key)
            if not isinstance(value, list):
                bad.append(f"user_profile.{key} 不是数组")
            elif len(value) != len(set(value)):
                bad.append(f"user_profile.{key} 有重复项")
    refs = target.get("memory_refs")
    if not isinstance(refs, list):
        bad.append("memory_refs 不是数组")
    return bad


def iter_samples(rec: dict) -> list[dict]:
    """把一个会话拆成若干训练样本（每个预测点一条）。"""
    turns = rec["turns"]
    by_id = {t["turn_id"]: t for t in turns}
    out: list[dict] = []
    for point in rec.get("prediction_points", []):
        target_user_turn_id = point.get("target_user_turn_id")
        response_turn_id = point.get("assistant_response_turn_id")
        target = point.get("target")

        # 规则 3：回复必须在目标 user 轮之后
        if not isinstance(response_turn_id, int) or not isinstance(target_user_turn_id, int):
            out.append({"reject": "turn_id 非整数"})
            continue
        if response_turn_id <= target_user_turn_id:
            out.append({
                "reject": "顺序异常：回复轮不在目标 user 轮之后",
                "target_user_turn_id": target_user_turn_id,
                "assistant_response_turn_id": response_turn_id,
            })
            continue

        response_turn = by_id.get(response_turn_id)
        if response_turn is None or response_turn.get("role") != "assistant":
            out.append({"reject": "回复轮不是 assistant 或不存在"})
            continue

        bad = check_target(target)
        if bad:
            out.append({"reject": "target 不合规: " + "; ".join(bad)})
            continue

        # 规则 3 加强：target 正文必须就是那一轮 assistant 的正文
        if response_turn["content"] != target["response_text"]:
            out.append({"reject": "target.response_text 与回复轮正文不一致"})
            continue
        # 黑名单兜底
        if (rec["conversation_id"], target_user_turn_id, response_turn_id) in KNOWN_NONADJACENT:
            out.append({"reject": "在已知顺序异常黑名单里"})
            continue

        history = build_history(turns, target_user_turn_id)
        if history is None:
            out.append({"reject": "无法构造以目标 user 轮结尾的输入"})
            continue

        # 参考答案绝不能出现在输入里
        if any(t["content"] == target["response_text"] for t in history):
            out.append({"reject": "参考答案出现在输入里"})
            continue

        out.append({
            "conversation_id": rec["conversation_id"],
            "target_user_turn_id": target_user_turn_id,
            "assistant_response_turn_id": response_turn_id,
            "history": history,
            "target": target,
            "history_turns": len(history),
        })
    return out


def pick_balanced(samples: list[dict], limit: int, seed: int) -> list[dict]:
    """确定性挑样：先按情绪轮转，尽量覆盖 16 类，再补足到 limit。"""
    rng = random.Random(seed)
    by_emotion: dict[str, list[dict]] = defaultdict(list)
    for sample in samples:
        by_emotion[sample["target"]["emotion_label"]].append(sample)
    for bucket in by_emotion.values():
        rng.shuffle(bucket)

    chosen: list[dict] = []
    order = sorted(by_emotion, key=lambda e: (-len(by_emotion[e]), e))
    while len(chosen) < limit:
        progressed = False
        for emotion in order:
            bucket = by_emotion[emotion]
            if bucket and len(chosen) < limit:
                chosen.append(bucket.pop())
                progressed = True
        if not progressed:
            break
    return chosen


def to_record(sample: dict, index: int, split: str) -> dict:
    target = sample["target"]
    return {
        "kind": "official",
        "example_id": f"official-{split}-{sample['conversation_id']}-p{sample['target_user_turn_id']}",
        "session_id": sample["conversation_id"],
        "category": f"official_{target['emotion_label']}",
        "sample_id": f"{sample['conversation_id']}_t{sample['target_user_turn_id']}",
        "conversation_id": sample["conversation_id"],
        "target_user_turn_id": sample["target_user_turn_id"],
        "history": sample["history"],
        "target_json": json.dumps(target, ensure_ascii=False),
        "memory_refs": list(target.get("memory_refs", [])),
        "label_source": "official_train_public",
        "label_note": "标签来自官方 train_public.jsonl 的 target 字段。",
    }


def prepare_split(rows: list[dict], limit: int, seed: int, split: str,
                  report: dict) -> tuple[list[dict], list[dict]]:
    rejects: list[dict] = []
    accepted: list[dict] = []
    seen_dialogs: set[str] = set()
    duplicate_rows = 0

    for rec in rows:
        problems = check_record(rec)
        if problems:
            report["结构违规行"].append({"conversation_id": rec.get("conversation_id"), "问题": problems})
            continue
        signature = complete_dialog_signature(rec["turns"])
        if signature in seen_dialogs:
            duplicate_rows += 1
            continue
        seen_dialogs.add(signature)

        for item in iter_samples(rec):
            if "reject" in item:
                rejects.append({**item, "conversation_id": rec.get("conversation_id")})
            else:
                accepted.append(item)

    chosen = pick_balanced(accepted, limit, seed)
    records = [to_record(s, i, split) for i, s in enumerate(chosen)]

    report[f"{split}_会话数"] = len(rows)
    report[f"{split}_去重丢弃会话数"] = duplicate_rows
    report[f"{split}_可用预测点数"] = len(accepted)
    report[f"{split}_选中样本数"] = len(records)
    report[f"{split}_拒绝原因"].update(Counter(r["reject"] for r in rejects))
    report[f"{split}_情绪分布"] = dict(sorted(Counter(
        s["target"]["emotion_label"] for s in chosen).items()))
    report[f"{split}_输入轮数"] = {
        "最小": min((len(r["history"]) for r in records), default=0),
        "最大": max((len(r["history"]) for r in records), default=0),
    }
    sessions = len({r["session_id"] for r in records})
    report[f"{split}_覆盖会话数"] = sessions
    return records, rejects


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="官方训练集 -> A 的 ≤200 条小样本")
    parser.add_argument("--train", required=True, help="官方 train_public.jsonl")
    parser.add_argument("--val", default=None, help="官方 val_public.jsonl（可选，用于独立验证集）")
    parser.add_argument("--out-dir", default="data/training/processed_official")
    parser.add_argument("--limit", type=int, default=200, help="训练样本上限，默认 200")
    parser.add_argument("--valid-limit", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20261010)
    parser.add_argument("--report", default=None)
    args = parser.parse_args(argv)

    train_path = Path(args.train)
    if not train_path.is_file():
        print(f"ERROR: 找不到官方训练集 {train_path}", file=sys.stderr)
        print("官方原始大数据没有进 Git，需要先从官方包解压或从平台取得。", file=sys.stderr)
        print("本脚本不会用任何合成数据冒充官方数据。", file=sys.stderr)
        return 2

    report: dict = {
        "说明": "官方训练集 -> A 小样本；只读官方数据，不用合成数据冒充。",
        "官方训练集": {"path": str(train_path), "sha256": sha256_of(train_path)},
        "硬性规则": {
            "参考答案不进输入": "history 只取 turn_id <= target_user_turn_id，且以目标 user 轮结尾",
            "验证集独立": "验证样本只来自 val_public.jsonl，会话不与训练集重叠",
            "顺序异常隔离": "要求回复轮晚于目标 user 轮，并有已知黑名单兜底",
            "去重": "完整对话指纹相同只保留第一次出现",
            "上限": f"训练 {args.limit} 条",
        },
        "已知黑名单": [f"{c} t{u}<-a{a}" for c, u, a in KNOWN_NONADJACENT],
    }
    for key in ("结构违规行",):
        report[key] = []
    for split in ("train", "valid"):
        report[f"{split}_拒绝原因"] = Counter()

    train_rows, train_problems = load_jsonl(train_path)
    report["官方训练集"]["物理行数"] = len(train_rows)
    report["官方训练集"]["解析失败行"] = train_problems

    train_records, _ = prepare_split(train_rows, args.limit, args.seed, "train", report)

    valid_records: list[dict] = []
    if args.val:
        val_path = Path(args.val)
        if val_path.is_file():
            val_rows, val_problems = load_jsonl(val_path)
            report["官方验证集"] = {
                "path": str(val_path), "sha256": sha256_of(val_path),
                "物理行数": len(val_rows), "解析失败行": val_problems,
            }
            valid_records, _ = prepare_split(val_rows, args.valid_limit, args.seed + 1, "valid", report)
        else:
            report["官方验证集"] = {"path": str(val_path), "错误": "文件不存在，未生成验证集"}

    # 训练/验证会话必须零重叠
    overlap = {r["session_id"] for r in train_records} & {r["session_id"] for r in valid_records}
    report["训练验证会话重叠"] = sorted(overlap)
    if overlap:
        print(f"ERROR: 训练与验证会话重叠 {len(overlap)} 个，拒绝写出", file=sys.stderr)
        return 3

    out_dir = REPO_ROOT / args.out_dir if not Path(args.out_dir).is_absolute() else Path(args.out_dir)
    write_jsonl(out_dir / "train.jsonl", train_records)
    if valid_records:
        write_jsonl(out_dir / "valid.jsonl", valid_records)

    report["最终"] = {
        "训练样本": len(train_records),
        "验证样本": len(valid_records),
        "上限": args.limit,
        "未超上限": len(train_records) <= args.limit,
        "输出目录": str(out_dir),
    }
    report = json.loads(json.dumps(report, ensure_ascii=False, default=str))

    report_path = Path(args.report) if args.report else out_dir / "official_samples_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"训练样本 : {len(train_records)} / 上限 {args.limit}")
    print(f"验证样本 : {len(valid_records)}")
    print(f"训练情绪 : {report.get('train_情绪分布')}")
    print(f"拒绝原因 : {dict(report.get('train_拒绝原因', {}))}")
    print(f"报告     : {report_path}")
    if len(train_records) == 0:
        print("ERROR: 没有产出任何训练样本", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())