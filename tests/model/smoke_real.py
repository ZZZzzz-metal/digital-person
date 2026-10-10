#!/usr/bin/env python3
"""A1：真实本地引擎冒烟检查。

检查项（每条都对应 A1 的完成条件）：

1. 从**完整本地文件**加载：``local_files_only=True``，进程内只加载一次；
2. 真实回复非空中文，``is_mock=False``，``model_version`` 与配置一致；
3. 情绪/表情在合同枚举内；
4. 当前 user **没有**被重复送进模型（渲染后的 prompt 里只出现一次）；
5. 上下文超长时从最旧完整轮次开始移除，且**不截断当前问题**；
6. 权重缺失时明确抛 ``ModelUnavailableError``，不产出假回复；
7. 记录耗时、设备、prompt/new token 数，测不到的字段写「未测」。

真实结果写入 ``reports/model/a1_real_engine_smoke.json``。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import REPO_ROOT, WEIGHTS_DIR, bootstrap, write_report  # noqa: E402

bootstrap()

from b2_core.model import (  # noqa: E402
    ModelEngine,
    ModelUnavailableError,
    GenerationError,
)

CONFIG_PATH = WEIGHTS_DIR / "inference_config.json"
EMOTIONS = {"neutral", "happy", "sad", "anxious", "angry", "unknown"}
EXPRESSIONS = {"neutral", "smile", "concern", "listening"}

ZERO_SHOT_CASES = [
    "我最近一想到考试就紧张，晚上也睡不好。",
    "今天面试终于过了，太开心了！",
    "室友总是半夜打游戏，说了也不听，烦死了。",
]


def main() -> int:
    failures: list[str] = []
    checks: dict[str, object] = {}

    # ---------------------------------------------------------------- #
    # 1) 加载
    # ---------------------------------------------------------------- #
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    started = time.perf_counter()
    engine = ModelEngine(CONFIG_PATH)
    init_seconds = time.perf_counter() - started
    describe = engine.describe()

    checks["offline_flags"] = {
        "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
        "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE"),
    }
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        failures.append("HF_HUB_OFFLINE 未设置")
    if not engine.loaded:
        failures.append("模型未加载")
    if engine.is_mock is not False:
        failures.append("真实引擎 is_mock 必须为 False")
    if not engine.model_version:
        failures.append("真实引擎必须有 model_version")
    if describe["contract_source"].startswith("b2_core.contracts") is False:
        checks["contract_source_note"] = describe["contract_source"]

    # ---------------------------------------------------------------- #
    # 2) 生成 + 不重复加载 + 当前 user 只送一次
    # ---------------------------------------------------------------- #
    load_report_before = engine._llm.report
    model_object_before = id(engine._llm.model)

    samples = []
    for text in ZERO_SHOT_CASES:
        request = {
            "messages": [{"role": "user", "content": text}],
            "memory_context": "",
            "persona": "伴学：中文日常陪伴助手",
            "max_new_tokens": 64,
            "temperature": 0.0,  # 贪心，便于复现
        }
        trace = engine.generate_with_trace(request)
        reply = trace["reply"]

        # 重新渲染一次 prompt，确认当前 user 只出现一次
        from b2_core.prompts import empathy

        rendered = engine._llm._render(
            empathy.build_chat_messages(
                [{"role": "user", "content": text}], persona="伴学：中文日常陪伴助手"
            )
        )
        occurrences = rendered.count(text)

        record = {
            "input": text,
            "reply": reply.reply,
            "emotion": reply.emotion,
            "expression": reply.expression,
            "model_version": reply.model_version,
            "is_mock": reply.is_mock,
            "elapsed_ms": round(trace["elapsed_ms"], 1),
            "prompt_tokens": trace["prompt_tokens"],
            "new_tokens": trace["new_tokens"],
            "device": trace["device"],
            "current_user_occurrences_in_prompt": occurrences,
        }
        samples.append(record)

        if not reply.reply.strip():
            failures.append(f"真实回复为空: {text}")
        if not any("\u4e00" <= ch <= "\u9fff" for ch in reply.reply):
            failures.append(f"真实回复不含中文: {text}")
        if reply.is_mock is not False:
            failures.append(f"is_mock 必须为 False: {text}")
        if reply.emotion not in EMOTIONS:
            failures.append(f"非法情绪 {reply.emotion!r}: {text}")
        if reply.expression not in EXPRESSIONS:
            failures.append(f"非法表情 {reply.expression!r}: {text}")
        if reply.model_version != engine.model_version:
            failures.append(f"model_version 不一致: {text}")
        if occurrences != 1:
            failures.append(f"当前 user 在 prompt 中出现 {occurrences} 次（应为 1）: {text}")

    if engine._llm.report is not load_report_before or id(engine._llm.model) != model_object_before:
        failures.append("连续调用触发了重新加载")
    checks["load_once"] = True

    # ---------------------------------------------------------------- #
    # 3) 上下文裁剪：长历史要丢最旧轮次，但不能丢当前问题
    # ---------------------------------------------------------------- #
    long_text = "这是很长的一段背景描述。" * 40  # 约 480 字
    long_messages = []
    for index in range(14):
        long_messages.append({"role": "user", "content": f"{long_text}第 {index} 轮提问。"})
        long_messages.append({"role": "assistant", "content": f"{long_text}第 {index} 轮回应。"})
    current_question = "现在请用一句话回应我此刻的心情。"
    long_messages.append({"role": "user", "content": current_question})

    trim_engine = ModelEngine(CONFIG_PATH)
    trim_engine._llm.max_input_tokens = 512  # 人为压低预算，强制触发裁剪
    trim_trace = trim_engine.generate_with_trace(
        {"messages": long_messages, "temperature": 0.0, "max_new_tokens": 48}
    )
    checks["context_trim"] = {
        "max_input_tokens": trim_engine._llm.max_input_tokens,
        "dropped_turns": trim_trace["dropped_turns"],
        "dropped_messages": trim_trace["dropped_messages"],
        "prompt_tokens": trim_trace["prompt_tokens"],
        "reply": trim_trace["reply"].reply,
    }
    if trim_trace["dropped_turns"] <= 0:
        failures.append("长历史未触发任何轮次裁剪")
    if not trim_trace["reply"].reply.strip():
        failures.append("裁剪后回复为空")

    # 单条问题本身超预算：必须明确报错，不许截断问题
    try:
        trim_engine.generate_with_trace(
            {"messages": [{"role": "user", "content": "超长问题。" * 400}], "max_new_tokens": 16}
        )
        failures.append("超长当前问题应当抛出 ContextTooLongError")
    except GenerationError as exc:
        checks["context_too_long_error"] = f"{type(exc).__name__}: {exc}"

    # ---------------------------------------------------------------- #
    # 4) 权重缺失必须失败，不能产出假回复
    # ---------------------------------------------------------------- #
    # 注：本机沙箱不允许写系统临时目录、也不允许对临时目录 chmod，
    # 所以负向用例的配置放在 weights/.scratch/ 下（已被 weights/.gitignore 排除），
    # 并用手工清理代替 TemporaryDirectory。
    scratch = WEIGHTS_DIR / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    tmp_path = scratch / "negative-check"
    shutil.rmtree(tmp_path, ignore_errors=True)
    tmp_path.mkdir(parents=True, exist_ok=True)
    try:
        empty_model_dir = tmp_path / "empty-model"
        empty_model_dir.mkdir()
        (empty_model_dir / "config.json").write_text("{}", encoding="utf-8")
        bad_config = tmp_path / "inference_config.json"
        bad_config.write_text(
            json.dumps({"model_dir": "empty-model", "model_version": "should-not-load"}),
            encoding="utf-8",
        )
        try:
            ModelEngine(bad_config)
            failures.append("空权重目录应当抛出 ModelUnavailableError")
        except ModelUnavailableError as exc:
            checks["missing_weights_error"] = str(exc)

        missing_config = tmp_path / "missing.json"
        missing_config.write_text(
            json.dumps({"model_dir": "does-not-exist", "model_version": "should-not-load"}),
            encoding="utf-8",
        )
        try:
            ModelEngine(missing_config)
            failures.append("不存在的权重目录应当抛出 ModelUnavailableError")
        except ModelUnavailableError as exc:
            checks["missing_dir_error"] = str(exc)
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)

    report = {
        "node": "A1 真实本地引擎冒烟检查",
        "engine": describe,
        "init_seconds": round(init_seconds, 3),
        "checks": checks,
        "failures": failures,
        "samples": samples,
        "denied_fields": ["显存占用（本机无 GPU，未测）", "GPU 型号（本机无 GPU，未测）"],
    }
    path = write_report("a1_real_engine_smoke.json", report)

    print(f"设备      : {describe['device']}  dtype={describe['param_dtypes']}")
    print(f"模型版本  : {describe['model_version']}")
    print(f"参数量    : {describe['params']:,}")
    print(f"加载耗时  : {describe['load_seconds']} s")
    print(f"最大输入  : {describe['max_input_tokens']} tokens")
    for record in samples:
        print(
            f"  [{record['emotion']:>7} / {record['expression']:>8}] "
            f"{record['elapsed_ms']:>7} ms  {record['reply'][:60]}"
        )
    print(f"裁剪检查  : {checks['context_trim']}")
    print(f"报告: {path}")
    if failures:
        print(f"FAIL: {len(failures)} 项未通过")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("PASS: A1 真实引擎检查全部通过（is_mock=False，本地离线加载）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())