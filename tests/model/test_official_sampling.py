#!/usr/bin/env python3
"""官方样本整理逻辑的自检。

官方 ``train_public.jsonl`` / ``val_public.jsonl`` 没有进 Git，本机也没有，
所以这里用**合成 fixture** 按官方 schema 造数据，专门覆盖第 5 步的硬性约束：

- 参考答案不能进输入（history 必须以目标 user 轮结尾，且不含该条回复）
- 4 个顺序异常点必须被隔离（这里用真实黑名单里的 train_conv_000628 造）
- 重复完整对话只保留一份
- 训练/验证会话零重叠
- ≤200 条上限

刻意**不测真实官方数据**：那需要真文件。本测试只证明整理逻辑本身正确，
不能替代对官方数据的实际整理结果。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import WEIGHTS_DIR  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "training" / "gpu"))
import prepare_official_samples as P  # noqa: E402

FIXTURE = WEIGHTS_DIR / ".scratch" / "official_fixture"
OUT = WEIGHTS_DIR / ".scratch" / "official_out"

EMOTIONS = list(P.EMOTIONS)

PROFILES = [
    {"personality_traits": ["introverted"], "interests": ["study_exam"], "style": ["brief"]},
    {"personality_traits": ["open", "casual"], "interests": ["music", "games"], "style": ["humorous"]},
    {"personality_traits": [], "interests": [], "style": []},
]


def make_conversation(conv_id: str, n_points: int, emotion: str, *, seed: int = 0) -> dict:
    """造一个结构合法的会话：user 在奇数轮，assistant 在偶数轮。"""
    turns = []
    max_turn = 2 * n_points + 2
    for tid in range(1, max_turn + 1):
        role = "user" if tid % 2 == 1 else "assistant"
        turns.append({"turn_id": tid, "role": role, "content": f"{conv_id}-t{tid}-{role}"})
    points = []
    for i in range(n_points):
        target_user = 2 * i + 1
        response = target_user + 1
        points.append({
            "target_user_turn_id": target_user,
            "assistant_response_turn_id": response,
            "target": {
                "response_text": f"{conv_id}-t{response}-assistant",
                "emotion_label": emotion,
                "user_profile": PROFILES[seed % len(PROFILES)],
                "memory_refs": [],
            },
        })
    return {"conversation_id": conv_id, "turns": turns, "prediction_points": points}


def make_nonadjacent(conv_id: str, target_user: int, response: int) -> dict:
    """目标回复在目标 user 轮**之前**——B 报告里的那类顺序异常。"""
    turns = []
    for tid in range(1, target_user + 1):
        role = "user" if tid % 2 == 1 else "assistant"
        prefix = f"{conv_id}-t{tid}-{role}"
        turns.append({"turn_id": tid, "role": role, "content": prefix})
    return {
        "conversation_id": conv_id,
        "turns": turns,
        "prediction_points": [{
            "target_user_turn_id": target_user,
            "assistant_response_turn_id": response,
            "target": {
                "response_text": f"{conv_id}-t{response}-assistant",
                "emotion_label": "neutral",
                "user_profile": PROFILES[0],
                "memory_refs": [],
            },
        }],
    }


def build_fixture() -> tuple[Path, Path]:
    FIXTURE.mkdir(parents=True, exist_ok=True)
    train_rows = []
    for i in range(40):
        train_rows.append(make_conversation(
            f"train_conv_{i:06d}", 4, EMOTIONS[i % len(EMOTIONS)], seed=i))

    # 训练集里 4 个已知顺序异常点之一，用真实 ID
    train_rows.append(make_nonadjacent("train_conv_000628", 15, 14))
    # 另一类异常：回复轮号和 target 相同
    train_rows.append(make_nonadjacent("train_conv_009999", 7, 7))
    # 完整对话与第 0 个会话逐字相同 -> 应当被去重丢掉
    dup = make_conversation("train_conv_008888", 4, EMOTIONS[0], seed=0)
    dup["turns"] = json.loads(json.dumps(train_rows[0]["turns"]))
    train_rows.append(dup)
    # 结构违规：情绪不在 16 类里（这是**预测点级**违规，只丢这一个点）
    bad = make_conversation("train_conv_007777", 2, "neutral")
    bad["prediction_points"][0]["target"]["emotion_label"] = "not_an_emotion"
    train_rows.append(bad)

    # 结构违规：role 非法（这是**会话级**违规，整行进 结构违规行）
    broken = make_conversation("train_conv_006666", 2, "neutral")
    broken["turns"][0]["role"] = "system"
    train_rows.append(broken)

    val_rows = [make_conversation(f"train_conv_{i:06d}", 2, EMOTIONS[(i + 5) % len(EMOTIONS)], seed=i)
                for i in range(500, 512)]

    train_path = FIXTURE / "train_public.jsonl"
    val_path = FIXTURE / "val_public.jsonl"
    for path, rows in ((train_path, train_rows), (val_path, val_rows)):
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return train_path, val_path


def main() -> int:
    train_path, val_path = build_fixture()
    out_dir = OUT
    if out_dir.exists():
        for old in out_dir.glob("*.json*"):
            old.unlink()

    rc = P.main([
        "--train", str(train_path),
        "--val", str(val_path),
        "--out-dir", str(out_dir),
        "--limit", "200",
        "--valid-limit", "60",
    ])

    failures: list[str] = []
    if rc != 0:
        failures.append(f"prepare 脚本退出码 {rc}")

    train_out = out_dir / "train.jsonl"
    valid_out = out_dir / "valid.jsonl"
    if not train_out.is_file():
        print("FAIL: 没有产出 train.jsonl")
        return 1

    train = [json.loads(l) for l in train_out.read_text(encoding="utf-8").splitlines() if l.strip()]
    valid = [json.loads(l) for l in valid_out.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if valid_out.is_file() else []
    report = json.loads((out_dir / "official_samples_report.json").read_text(encoding="utf-8"))

    # 1. 上限
    if len(train) > 200:
        failures.append(f"训练样本 {len(train)} 超过 200 上限")
    if not train:
        failures.append("训练样本为空")

    # 2. 顺序异常必须被隔离
    ids = {r["conversation_id"] for r in train}
    for conv_id in ("train_conv_000628", "train_conv_009999"):
        if conv_id in ids:
            failures.append(f"顺序异常会话 {conv_id} 没有被隔离")

    # 3. 重复完整对话只保留一份
    if "train_conv_008888" in ids:
        failures.append("重复完整对话 train_conv_008888 没有被去重")

    # 4. 会话级结构违规进「结构违规行」，预测点级违规进「拒绝原因」
    if not report.get("结构违规行"):
        failures.append("会话级结构违规（role 非法）没有被记录到 结构违规行")
    if "train_conv_006666" in ids:
        failures.append("结构违规会话 train_conv_006666 不该产出样本")
    rejects = report.get("train_拒绝原因", {})
    if not any("emotion_label" in str(k) for k in rejects):
        failures.append("预测点级的非法情绪没有被记入拒绝原因")
    if not any("顺序异常" in str(k) for k in rejects):
        failures.append("顺序异常没有被记入拒绝原因")

    # 5. 参考答案绝不进输入 + history 以目标 user 轮结尾
    for record in train + valid:
        history = record["history"]
        if not history:
            failures.append(f"{record['example_id']}: history 为空")
            continue
        last = history[-1]
        if last["role"] != "user" or last["turn_id"] != record["target_user_turn_id"]:
            failures.append(f"{record['example_id']}: history 最后一轮不是目标 user 轮")
        target_text = json.loads(record["target_json"])["response_text"]
        if any(t["content"] == target_text for t in history):
            failures.append(f"{record['example_id']}: 参考答案出现在输入里")
        if any(t["turn_id"] > record["target_user_turn_id"] for t in history):
            failures.append(f"{record['example_id']}: 输入里有晚于目标 user 轮的轮次")

    # 6. 训练/验证会话零重叠
    overlap = {r["session_id"] for r in train} & {r["session_id"] for r in valid}
    if overlap:
        failures.append(f"训练与验证会话重叠: {sorted(overlap)[:5]}")

    # 7. 情绪都在 16 类里
    for record in train + valid:
        emotion = json.loads(record["target_json"])["emotion_label"]
        if emotion not in P.EMOTIONS:
            failures.append(f"{record['example_id']}: 情绪 {emotion} 不在 16 类里")

    print()
    print(f"训练样本   : {len(train)}")
    print(f"验证样本   : {len(valid)}")
    print(f"训练情绪   : {report.get('train_情绪分布')}")
    print(f"拒绝原因   : {dict(report.get('train_拒绝原因', {}))}")
    print(f"结构违规行 : {len(report.get('结构违规行', []))}")
    print(f"去重丢弃   : {report.get('train_去重丢弃会话数')}")
    print(f"覆盖会话数 : {report.get('train_覆盖会话数')} / {report.get('valid_覆盖会话数')}")

    if failures:
        print(f"\nFAIL: {len(failures)} 项未通过")
        for item in failures[:20]:
            print(f"  - {item}")
        return 1
    print("\nPASS: 上限 / 参考答案隔离 / 顺序异常隔离 / 去重 / 训练验证零重叠 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())