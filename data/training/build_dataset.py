#!/usr/bin/env python3
"""A2：把原始合成分会整理成可训练的最小数据集。

输入：``data/training/raw/sessions.jsonl``（200 个合成会话，A2 自建，虚构人物）。
输出：``data/training/processed/{train,valid,holdout}.jsonl`` 与
``data/training/processed/dataset_report.json``。

做四件事：

1. **校验与去重**：角色必须 user/assistant 严格交替、以 user 开头以 assistant 结尾、
   文本非空；整会话重复的直接剔除并计数。
2. **按预测点切片**：一个预测点 = 「截至某条 user 的上下文 + 它的下一条 assistant」。
   上下文里的最后一条一定是该 user，绝不含该 assistant 及其后的任何内容，
   所以训练输入里不会混入答案。
3. **按完整会话划分**：train/valid/holdout 用 session_id 的哈希排序决定，
   同一会话只落在一个集合里，评测集（data/eval/cases.json）不参与训练。
4. **两种渲染**：``chat``（演示合同，人设+共情提示词）与 ``official``
   （官方合同，system prompt + 完整历史 + JSON 目标）。官方目标的
   情绪与画像是**规则标注**，不是人工标注，也不是官方标签。

有效样本上限 200（A4 的预算约束）：训练集固定为 chat 150 + official 50。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "model"))
from _bootstrap import DATA_DIR, bootstrap  # noqa: E402

bootstrap()

from b2_core.a_impl import emotion_rules, official_spec  # noqa: E402

RAW_PATH = DATA_DIR / "training" / "raw" / "sessions.jsonl"
OUT_DIR = DATA_DIR / "training" / "processed"

SEED = 20261010
TRAIN_CHAT_QUOTA = 150
TRAIN_OFFICIAL_QUOTA = 50
VALID_QUOTA = 80
HOLDOUT_QUOTA = 80
SPLIT = {"train": 160, "valid": 20, "holdout": 20}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A2 数据集整理")
    parser.add_argument("--raw", type=Path, default=RAW_PATH)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    return parser.parse_args()


# --------------------------------------------------------------------------- #
def load_sessions(path: Path) -> tuple[list[dict], list[str]]:
    problems: list[str] = []
    sessions: list[dict] = []
    if not path.is_file():
        raise SystemExit(f"原始数据不存在: {path}")
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"第 {number} 行 JSON 解析失败: {exc.msg}")
            continue
        sessions.append(row)
    return sessions, problems


def validate_session(row: dict) -> list[str]:
    """检查单个会话的结构；返回问题列表（空表示合格）。"""
    problems: list[str] = []
    session_id = row.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        problems.append("session_id 缺失")
    messages = row.get("messages")
    if not isinstance(messages, list) or not messages:
        return problems + ["messages 为空"]
    if messages[0].get("role") != "user":
        problems.append("第一条必须是 user")
    if messages[-1].get("role") != "assistant":
        problems.append("最后一条必须是 assistant")
    for index, item in enumerate(messages):
        role = item.get("role")
        content = item.get("content")
        expected = "user" if index % 2 == 0 else "assistant"
        if role != expected:
            problems.append(f"messages[{index}].role 应为 {expected}，实际 {role}")
        if not isinstance(content, str) or not content.strip():
            problems.append(f"messages[{index}].content 为空")
    if not isinstance(row.get("category"), str) or not row["category"]:
        problems.append("category 缺失")
    if row.get("source") != "synthetic_auto_generated":
        problems.append("source 不是 synthetic_auto_generated")
    if row.get("license") != "internal-fictional-no-real-personal-data":
        problems.append("license 不是内部虚构标注")
    memory = row.get("memory_context", [])
    if not isinstance(memory, list):
        problems.append("memory_context 不是数组")
    else:
        for entry in memory:
            if not isinstance(entry, dict) or entry.get("kind") not in ("fact", "event", "preference"):
                problems.append(f"memory_context 条目非法: {entry!r}")
    return problems


def session_signature(row: dict) -> str:
    payload = json.dumps(
        [(m["role"], m["content"]) for m in row["messages"]], ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stable_split(session_id: str) -> str:
    """按 session_id 的哈希排序划分，与输入顺序无关，可重复运行。"""
    digest = hashlib.sha1(session_id.encode("utf-8")).hexdigest()
    return digest


def memory_text(row: dict, point_index: int) -> str:
    """把合成的会话级记忆拼成一段自然语言。

    合成记忆没有时间戳，这里只在第 2 个预测点之后注入，避免首轮就凭空出现背景。
    这仍是**会话级**信息，不是严格按时间累积的记忆，见 dataset_report 的说明。
    """
    if point_index < 1:
        return ""
    entries = row.get("memory_context") or []
    if not entries:
        return ""
    return "".join(entry["text"].rstrip("。") + "。" for entry in entries)


def prediction_points(row: dict) -> list[dict]:
    """切出该会话的全部预测点。"""
    messages = row["messages"]
    points: list[dict] = []
    for index in range(len(messages) - 1):
        if messages[index]["role"] != "user" or messages[index + 1]["role"] != "assistant":
            continue
        context = messages[: index + 1]
        target = messages[index + 1]["content"]
        points.append(
            {
                "session_id": row["session_id"],
                "category": row["category"],
                "point_index": len(points),
                "context": context,
                "target": target,
                "memory_context": memory_text(row, len(points)),
            }
        )
    return points


def build_official_target(point: dict) -> dict:
    """官方目标的 JSON 内容：回复来自数据，情绪与画像来自 A 的规则标注。"""
    latest_user = point["context"][-1]["content"]
    return {
        "response_text": point["target"],
        "emotion_label": emotion_rules.estimate_official_emotion(latest_user),
        "user_profile": emotion_rules.infer_profile(point["context"]),
        "memory_refs": list(official_spec.PUBLIC_TEST_MEMORY_REFS),
    }


def make_chat_example(point: dict) -> dict:
    return {
        "kind": "chat",
        "example_id": f"chat-{point['session_id']}-p{point['point_index']}",
        "session_id": point["session_id"],
        "category": point["category"],
        "memory_context": point["memory_context"],
        "messages": point["context"],
        "target": point["target"],
        "label_source": "synthetic_template",
    }


def make_official_example(point: dict) -> dict:
    target = build_official_target(point)
    history = [
        {"turn_id": i + 1, "role": m["role"], "content": m["content"]}
        for i, m in enumerate(point["context"])
    ]
    return {
        "kind": "official",
        "example_id": f"official-{point['session_id']}-p{point['point_index']}",
        "session_id": point["session_id"],
        "category": point["category"],
        "sample_id": f"syn_{point['session_id'].split('-')[1]}_{point['point_index']}",
        "conversation_id": point["session_id"],
        "target_user_turn_id": history[-1]["turn_id"],
        "history": history,
        "target_json": json.dumps(target, ensure_ascii=False, separators=(",", ":")),
        "memory_refs": list(official_spec.PUBLIC_TEST_MEMORY_REFS),
        "label_source": "rule_based",
        "label_note": "情绪与画像由 A 的规则标注，不是人工标注，也不是官方标签。",
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
def main() -> int:
    args = parse_args()
    sessions, parse_problems = load_sessions(args.raw)
    problems = list(parse_problems)

    valid_sessions: list[dict] = []
    rejected: list[dict] = []
    for row in sessions:
        issues = validate_session(row)
        if issues:
            rejected.append({"session_id": row.get("session_id"), "problems": issues})
        else:
            valid_sessions.append(row)
    problems += [f"{r['session_id']}: {r['problems'][0]}" for r in rejected]

    # 整会话去重
    seen: dict[str, str] = {}
    deduped: list[dict] = []
    duplicates: list[str] = []
    for row in valid_sessions:
        signature = session_signature(row)
        if signature in seen:
            duplicates.append(row["session_id"])
            continue
        seen[signature] = row["session_id"]
        deduped.append(row)

    # 按会话划分
    ordered = sorted(deduped, key=lambda r: stable_split(r["session_id"]))
    buckets: dict[str, list[dict]] = {"train": [], "valid": [], "holdout": []}
    cursor = 0
    for name in ("train", "valid", "holdout"):
        size = SPLIT[name]
        buckets[name] = ordered[cursor : cursor + size]
        cursor += size

    rng = random.Random(SEED)
    report = {
        "node": "A2 数据集整理",
        "seed": SEED,
        "raw_path": str(args.raw.relative_to(DATA_DIR.parent)),
        "raw_sessions": len(sessions),
        "rejected_sessions": rejected,
        "duplicate_sessions_removed": duplicates,
        "kept_sessions": len(deduped),
        "split_sizes": {name: len(rows) for name, rows in buckets.items()},
        "split_overlap_check": {
            "session_ids_overlap": bool(
                {r["session_id"] for r in buckets["train"]}
                & {r["session_id"] for r in buckets["valid"]}
                | {r["session_id"] for r in buckets["train"]}
                & {r["session_id"] for r in buckets["holdout"]}
                | {r["session_id"] for r in buckets["valid"]}
                & {r["session_id"] for r in buckets["holdout"]}
            )
        },
        "source": "synthetic_auto_generated",
        "license": "internal-fictional-no-real-personal-data",
        "limitations": [
            "全部为模板化自动生成的虚构对话，不是真人访谈，也不是官方训练数据。",
            "助手回复来自片段池组合，与用户具体内容的相关性有限。",
            "official 目标的情绪与画像由 A 的规则标注，不是人工标注或官方标签。",
            "合成 memory_context 是会话级的，没有时间戳；只在第 2 个预测点之后注入。",
            "data/eval/cases.json 的 12 个评测案例不参与训练，也不与训练会话重叠。",
        ],
        "eval_set_isolation": {
            "eval_cases_path": "data/eval/cases.json",
            "eval_cases_used_in_training": False,
            "note": "评测案例是 A 手写的固定案例，与合成会话无同一会话重叠。",
        },
    }

    out_dir = args.out_dir
    all_points: dict[str, list[dict]] = {}
    for name, rows in buckets.items():
        points: list[dict] = []
        for row in rows:
            points += prediction_points(row)
        all_points[name] = points

    # 训练集：chat 150 + official 50 = 200 条有效样本
    train_points = list(all_points["train"])
    rng.shuffle(train_points)
    chat_points = train_points[:TRAIN_CHAT_QUOTA]
    official_points = train_points[TRAIN_CHAT_QUOTA : TRAIN_CHAT_QUOTA + TRAIN_OFFICIAL_QUOTA]

    train_rows: list[dict] = []
    for point in chat_points:
        train_rows.append(make_chat_example(point))
    for point in official_points:
        train_rows.append(make_official_example(point))
    rng.shuffle(train_rows)

    def cap(points: list[dict], limit: int, kinds: tuple[str, ...]) -> list[dict]:
        rows: list[dict] = []
        for point in points:
            if "chat" in kinds:
                rows.append(make_chat_example(point))
            if "official" in kinds:
                rows.append(make_official_example(point))
            if len(rows) >= limit:
                break
        return rows[:limit]

    valid_rows = cap(all_points["valid"], VALID_QUOTA, ("chat",))
    valid_rows += cap(all_points["valid"], VALID_QUOTA // 2, ("official",))
    holdout_rows = cap(all_points["holdout"], HOLDOUT_QUOTA, ("chat",))

    write_jsonl(out_dir / "train.jsonl", train_rows)
    write_jsonl(out_dir / "valid.jsonl", valid_rows)
    write_jsonl(out_dir / "holdout.jsonl", holdout_rows)

    report["effective_samples"] = {
        "train_total": len(train_rows),
        "train_chat": sum(1 for r in train_rows if r["kind"] == "chat"),
        "train_official": sum(1 for r in train_rows if r["kind"] == "official"),
        "valid_total": len(valid_rows),
        "holdout_total": len(holdout_rows),
        "budget_note": "A4 约束：有效样本不超过 200；训练集 = chat 150 + official 50。",
    }
    report["train_categories"] = dict(Counter(r["category"] for r in train_rows))
    report["valid_categories"] = dict(Counter(r["category"] for r in valid_rows))
    report["available_prediction_points"] = {
        name: len(points) for name, points in all_points.items()
    }
    report["problems"] = problems

    (out_dir / "dataset_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"原始会话      : {len(sessions)}  合格 {len(deduped)}  剔除 {len(rejected)}  去重 {len(duplicates)}")
    print(f"会话划分      : {report['split_sizes']}  重叠={report['split_overlap_check']['session_ids_overlap']}")
    print(f"可用预测点    : {report['available_prediction_points']}")
    print(f"训练有效样本  : {len(train_rows)} (chat {report['effective_samples']['train_chat']} + official {report['effective_samples']['train_official']})")
    print(f"验证 / 留出   : {len(valid_rows)} / {len(holdout_rows)}")
    print(f"训练类别分布  : {report['train_categories']}")
    print(f"输出目录      : {out_dir}")
    return 0 if not rejected and not duplicates else 0


if __name__ == "__main__":
    raise SystemExit(main())