#!/usr/bin/env python3
"""A0：MockEngine 冒烟检查。

只验证程序链路，不评价模型效果：

- ``generate(CoreRequest) -> CoreReply`` 可调用，回复非空；
- 情绪只出现合同里的 6 类，表情只出现 4 类，非法值归 unknown / neutral；
- ``is_mock`` 恒为 True，``model_version`` 固定为 ``mock-v1``；
- 不联网、不加载大模型、不读写数据库（本脚本不导入 torch，也不打开任何库文件）；
- 同时验证官方合同 ``generate_official`` 能产出 schema 合法的四字段结果。

结果写入 ``reports/model/a0_mock_smoke.json``，供 B 直接替换自己的 stub。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap, write_report  # noqa: E402

REPO_ROOT = bootstrap()

from b2_core.a_impl import official_spec  # noqa: E402
from b2_core.model import MOCK_MODEL_VERSION, MockEngine  # noqa: E402

EMOTIONS = {"neutral", "happy", "sad", "anxious", "angry", "unknown"}
EXPRESSIONS = {"neutral", "smile", "concern", "listening"}

CASES = [
    ("我最近一想到考试就紧张，晚上也睡不好。", "anxious"),
    ("今天面试终于过了，太开心了！", "happy"),
    ("室友总是半夜打游戏，说了也不听，烦死了。", "angry"),
    ("感觉最近做什么都没意思，有点低落。", "sad"),
    ("今天天气还行，没什么特别的。", "neutral"),
    # 没有情绪关键词的非空输入归 neutral；unknown 只保留给空输入（见下方规则检查）。
    ("嗯，就这样吧。", "neutral"),
]


def main() -> int:
    failures: list[str] = []
    engine = MockEngine()
    describe = engine.describe()

    # 1) 逐案例调用
    samples = []
    for text, expected in CASES:
        request = {
            "messages": [{"role": "user", "content": text}],
            "memory_context": "",
            "persona": "伴学：中文日常陪伴助手",
            "max_new_tokens": 128,
            "temperature": 0.3,
        }
        reply = engine.generate(request)
        record = {
            "input": text,
            "expected_emotion": expected,
            "reply": reply.reply,
            "emotion": reply.emotion,
            "expression": reply.expression,
            "model_version": reply.model_version,
            "is_mock": reply.is_mock,
        }
        samples.append(record)

        if not isinstance(reply.reply, str) or not reply.reply.strip():
            failures.append(f"回复为空: {text}")
        if reply.emotion not in EMOTIONS:
            failures.append(f"非法情绪 {reply.emotion!r}: {text}")
        if reply.expression not in EXPRESSIONS:
            failures.append(f"非法表情 {reply.expression!r}: {text}")
        if reply.is_mock is not True:
            failures.append(f"is_mock 必须为 True: {text}")
        if reply.model_version != MOCK_MODEL_VERSION:
            failures.append(f"model_version 必须是 {MOCK_MODEL_VERSION}: {text}")
        if reply.expression != {
            "happy": "smile",
            "sad": "concern",
            "anxious": "concern",
            "angry": "listening",
            "neutral": "neutral",
            "unknown": "neutral",
        }[reply.emotion]:
            failures.append(f"情绪→表情映射不符合总约定: {text} {reply.emotion}->{reply.expression}")
        if reply.emotion != expected:
            failures.append(f"情绪估计与预期不符: {text} 期望 {expected} 实际 {reply.emotion}")

    # 2) 多轮输入 + 记忆上下文：mock 也不能重复当前问题
    multi = {
        "messages": [
            {"role": "user", "content": "我下周要考高数。"},
            {"role": "assistant", "content": "听起来你有点惦记这件事。"},
            {"role": "user", "content": "对，我特别怕考砸。"},
        ],
        "memory_context": "小然在读大二。小然在准备高数考试。",
        "persona": "伴学：中文日常陪伴助手",
        "max_new_tokens": 128,
        "temperature": 0.3,
    }
    multi_reply = engine.generate(multi)
    if multi_reply.reply.count("我特别怕考砸") > 0:
        failures.append("mock 回复不该原样复述当前输入作为唯一内容")
    if not multi_reply.reply.strip():
        failures.append("多轮 mock 回复为空")

    # 3) 非法情绪/表情归位：直接构造一个非法值走映射函数
    from b2_core.a_impl import emotion_rules

    if emotion_rules.map_expression("not_an_emotion") != "neutral":
        failures.append("非法情绪必须映射到 neutral 表情")
    if emotion_rules.estimate_demo_emotion("") != "unknown":
        failures.append("空输入情绪必须归 unknown")

    # 4) 官方合同（mock 路径）
    official_samples = []
    test_file = REPO_ROOT / "submission" / "official-reference" / "test_inference_data.jsonl"
    if test_file.is_file():
        import json

        for line in test_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            prediction, trace = engine.official_trace(
                {
                    "sample_id": row["id"],
                    "conversation_id": row.get("conversation_id"),
                    "target_user_turn_id": row.get("target_user_turn_id"),
                    "history": row["history"],
                }
            )
            from b2_core.a_impl import dtos as dtos_mod

            as_dict = dtos_mod.prediction_as_dict(prediction)
            ok, problems = official_spec.is_schema_valid(as_dict)
            official_samples.append(
                {"sample_id": row["id"], "prediction": as_dict, "schema_valid": ok, "problems": problems}
            )
            if not ok:
                failures.append(f"mock 官方输出不合法 {row['id']}: {problems}")
            if trace["is_mock"] is not True:
                failures.append(f"mock 官方 trace is_mock 必须为 True: {row['id']}")

    # 5) 边界输入必须明确报错，不能产出空壳回复
    from b2_core.a_impl.dtos import RequestError

    for bad, label in (
        ({"messages": [{"role": "user", "content": "   "}]}, "空输入"),
        ({"messages": [{"role": "assistant", "content": "你好"}]}, "最后一条不是 user"),
        ({"messages": []}, "空 messages"),
        ({"messages": [{"role": "user", "content": "hi"}], "max_new_tokens": 0}, "非法 max_new_tokens"),
    ):
        try:
            engine.generate(bad)
            failures.append(f"{label} 应当抛出 RequestError，但成功了")
        except RequestError:
            pass
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{label} 抛出了非预期异常 {type(exc).__name__}: {exc}")

    report = {
        "node": "A0 MockEngine 冒烟检查",
        "engine": describe,
        "checks": {
            "cases": len(CASES),
            "multi_turn_cases": 1,
            "official_samples": len(official_samples),
            "failures": failures,
        },
        "samples": samples,
        "multi_turn": {"input": multi, "reply": multi_reply.reply, "emotion": multi_reply.emotion},
        "official_samples": official_samples,
    }
    path = write_report("a0_mock_smoke.json", report)

    print(f"MockEngine 冒烟检查：{len(CASES)} 个案例，{len(official_samples)} 条官方样例")
    for record in samples:
        print(f"  [{record['emotion']:>7} / {record['expression']:>8}] {record['reply']}")
    print(f"报告: {path}")
    if failures:
        print(f"FAIL: {len(failures)} 项未通过")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("PASS: A0 mock 检查全部通过（is_mock=True, model_version=mock-v1）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())