#!/usr/bin/env python3
"""官方合同冒烟检查：``generate_official(OfficialRequest) -> OfficialPrediction``。

用官方公开的 3 条推理输入（``submission/official-reference/test_inference_data.jsonl``）
逐条检查：

1. 真实引擎 ``is_mock=False``，有 ``model_version``；
2. 输出**只有**四个字段（``response_text`` / ``emotion_label`` / ``user_profile`` /
   ``memory_refs``）；没有 ``id``（由 B 回填）、没有 ``is_mock``、没有表情或耗时；
3. ``response_text`` 非空；``emotion_label`` 属于官方 16 类；
4. ``user_profile`` 三组齐全，取值全在官方枚举内且不重复；
5. 公开测试 ``memory_refs == []``（没有公开 memory bank，不许编造引用）；
6. 不混入答案、不重复当前 user：渲染出的 prompt 里每条历史只出现一次，
   且最后一条 user 就是目标轮，没有追加任何预测；
7. 独立样本不累积状态：同一条输入重跑一次结果应一致（贪心解码）；
8. 缺权重时必须报错，不能产出假预测；
9. 输入边界（最后一条不是 user）必须抛 ``RequestError``。

结果写入 ``reports/model/a5_official_contract.json``。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import REPO_ROOT, WEIGHTS_DIR, bootstrap, write_report  # noqa: E402

bootstrap()

from b2_core.a_impl import dtos as dtos_mod  # noqa: E402
from b2_core.a_impl import official_spec  # noqa: E402
from b2_core.a_impl.dtos import RequestError  # noqa: E402
from b2_core.model import (  # noqa: E402
    ModelEngine,
    MockEngine,
    ModelUnavailableError,
)

TEST_FILE = REPO_ROOT / "submission" / "official-reference" / "test_inference_data.jsonl"
ALLOWED_KEYS = {"response_text", "emotion_label", "user_profile", "memory_refs"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="官方生成合同冒烟检查")
    parser.add_argument("--config", type=Path, default=WEIGHTS_DIR / "inference_config.json")
    parser.add_argument("--report", default="a5_official_contract.json")
    return parser.parse_args()


def load_samples() -> list[dict]:
    rows = []
    for line in TEST_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def schema_checks(prediction: dict) -> list[str]:
    """按团队派生的 model_prediction.schema.json 逐条检查。"""
    problems: list[str] = []
    extra = set(prediction) - ALLOWED_KEYS
    if extra:
        problems.append(f"出现 schema 之外的字段: {sorted(extra)}")
    missing = ALLOWED_KEYS - set(prediction)
    if missing:
        problems.append(f"缺少必需字段: {sorted(missing)}")
    ok, detail = official_spec.is_schema_valid(prediction)
    if not ok:
        problems += detail
    profile = prediction.get("user_profile")
    if isinstance(profile, dict):
        groups = set(profile)
        if groups != set(official_spec.PROFILE_GROUP_NAMES):
            problems.append(f"画像组必须是三组，实际 {sorted(groups)}")
    return problems


def main() -> int:
    args = parse_args()
    failures: list[str] = []
    samples = load_samples()
    engine = ModelEngine(args.config)

    if engine.is_mock is not False:
        failures.append("真实引擎 is_mock 必须为 False")
    if not engine.model_version:
        failures.append("真实引擎必须有 model_version")

    results = []
    for row in samples:
        request = {
            "sample_id": row["id"],
            "conversation_id": row.get("conversation_id"),
            "target_user_turn_id": row.get("target_user_turn_id"),
            "history": row["history"],
        }
        started = time.perf_counter()
        prediction, trace = engine.official_trace(request)
        elapsed = time.perf_counter() - started
        as_dict = dtos_mod.prediction_as_dict(prediction)

        problems = schema_checks(as_dict)
        if trace["is_mock"] is not False:
            problems.append("trace.is_mock 必须为 False")
        if as_dict["memory_refs"] != []:
            problems.append(f"公开测试 memory_refs 必须为 []，实际 {as_dict['memory_refs']}")
        if not trace["response_source"] == "model":
            problems.append(f"response_text 必须来自模型，实际 {trace['response_source']}")

        # 不重复当前 user、不混入答案
        rendered = official_spec.render_conversation(row["id"], row["history"])
        target_text = row["history"][-1]["content"]
        occurrences = rendered.count(target_text)
        if occurrences != 1:
            problems.append(f"目标 user 在渲染文本中出现 {occurrences} 次（应为 1）")
        # 渲染文本的行数必须等于历史条数（说明没有追加任何内容）
        line_count = len([line for line in rendered.splitlines() if line.startswith(("user:", "assistant:"))])
        if line_count != len(row["history"]):
            problems.append(f"渲染文本包含 {line_count} 条发言，历史有 {len(row['history'])} 条")

        results.append(
            {
                "sample_id": row["id"],
                "history_turns": len(row["history"]),
                "prediction": as_dict,
                "trace": trace,
                "elapsed_seconds": round(elapsed, 2),
                "problems": problems,
            }
        )
        failures += [f"{row['id']}: {p}" for p in problems]

    # 独立样本不累积状态：重跑第一条
    first = samples[0]
    replay_request = {
        "sample_id": first["id"],
        "conversation_id": first.get("conversation_id"),
        "target_user_turn_id": first.get("target_user_turn_id"),
        "history": first["history"],
    }
    replay_prediction, _ = engine.official_trace(replay_request)
    replay_dict = dtos_mod.prediction_as_dict(replay_prediction)
    independence = {
        "sample_id": first["id"],
        "identical": replay_dict == results[0]["prediction"],
        "first": results[0]["prediction"],
        "replay": replay_dict,
    }
    if not independence["identical"]:
        failures.append("独立样本状态检查失败：同一条输入两次结果不同")

    # 输入边界：最后一条不是 user
    try:
        engine.generate_official(
            {"sample_id": "bad_1", "history": [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "在"}]}
        )
        failures.append("最后一条不是 user 时应当抛出 RequestError")
    except RequestError:
        pass

    # 缺权重必须报错
    scratch = WEIGHTS_DIR / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    missing_config = scratch / "inference_config.official_missing.json"
    missing_config.write_text(
        json.dumps({"model_dir": "nope-model", "model_version": "should-not-load"}),
        encoding="utf-8",
    )
    try:
        ModelEngine(missing_config)
        failures.append("权重缺失时应当抛出 ModelUnavailableError")
    except ModelUnavailableError:
        pass

    # MockEngine 对照（只验证链路，不评价效果）
    mock = MockEngine()
    mock_prediction, mock_trace = mock.official_trace(
        {
            "sample_id": samples[0]["id"],
            "history": samples[0]["history"],
        }
    )
    mock_dict = dtos_mod.prediction_as_dict(mock_prediction)
    mock_problems = schema_checks(mock_dict)
    if mock_trace["is_mock"] is not True:
        mock_problems.append("mock trace.is_mock 必须为 True")

    report = {
        "node": "官方生成合同冒烟检查",
        "test_file": str(TEST_FILE.relative_to(REPO_ROOT)),
        "engine": engine.describe(),
        "contract_source": engine._binding.source,
        "official_prompt_sha": __import__("hashlib").sha256(
            official_spec.build_system_prompt().encode("utf-8")
        ).hexdigest()[:16],
        "emotions_available": list(official_spec.EMOTIONS),
        "profile_groups": {k: list(v) for k, v in official_spec.PROFILE_LABELS.items()},
        "samples": results,
        "independence_check": independence,
        "mock_comparison": {
            "prediction": mock_dict,
            "is_mock": mock_trace["is_mock"],
            "problems": mock_problems,
        },
        "failures": failures,
    }
    path = write_report(args.report, report)

    print(f"引擎        : is_mock={engine.is_mock}  version={engine.model_version}")
    print(f"合同来源    : {engine._binding.source}")
    for record in results:
        pred = record["prediction"]
        print(f"--- {record['sample_id']}  ({record['history_turns']} 轮历史, {record['elapsed_seconds']}s) ---")
        print(f"  模式      : {record['trace']['mode']}  情绪来源={record['trace']['emotion_source']}")
        print(f"  回复      : {pred['response_text'][:90]}")
        print(f"  情绪      : {pred['emotion_label']}")
        print(f"  画像      : {json.dumps(pred['user_profile'], ensure_ascii=False)}")
        print(f"  引用      : {pred['memory_refs']}")
    print(f"独立样本    : 重跑一致={independence['identical']}")
    print(f"报告: {path}")
    if failures:
        print(f"FAIL: {len(failures)} 项未通过")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("PASS: 官方合同检查全部通过（is_mock=False，四字段合法，memory_refs=[]）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())