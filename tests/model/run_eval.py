#!/usr/bin/env python3
"""A5：12 案例最小自动评测。

评测集固定为 ``data/eval/cases.json``（6 个多轮案例 × 6 轮 + 6 个边界案例）。
基线与训练候选**使用完全相同的案例与参数**，只是 ``--config`` 指向不同配置。

检查项（都只看接口、非空回复、合法字段、mock 标记、当前输入未重复、
错误可识别、跨样本不串状态）：

- 每个多轮案例的 6 轮都真正跑一次生成，记录回复、情绪、表情、耗时与 token 数；
- 边界案例区分「应当成功」与「应当明确失败」，失败必须抛可识别的异常类型；
- ``forbidden_anywhere`` / ``turn_expect``（``must_include_any`` / ``must_not_include`` /
  ``must_not_exceed_chars``）只做规则匹配，**不是官方分数，也不是全面安全保证**；
- 评测结束后把第一个案例的第一轮重跑一次，与套件里的结果比对，
  用来检查引擎没有跨样本累积状态。

用法::

    python tests/model/run_eval.py --config weights/inference_config.json --label baseline
    python tests/model/run_eval.py --mock --label mock
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import DATA_DIR, REPO_ROOT, WEIGHTS_DIR, bootstrap, write_report  # noqa: E402

bootstrap()

from b2_core.a_impl.dtos import RequestError  # noqa: E402
from b2_core.model import (  # noqa: E402
    ModelEngine,
    MockEngine,
    ModelUnavailableError,
)

CASES_PATH = DATA_DIR / "eval" / "cases.json"
EMOTIONS = {"neutral", "happy", "sad", "anxious", "angry", "unknown"}
EXPRESSIONS = {"neutral", "smile", "concern", "listening"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A5 12 案例最小自动评测")
    parser.add_argument("--config", type=Path, default=WEIGHTS_DIR / "inference_config.json")
    parser.add_argument("--label", default="run")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--mock", action="store_true", help="用 MockEngine 只验证程序链路")
    parser.add_argument("--only", default=None, help="只跑某个案例，如 MT1 / BD3")
    return parser.parse_args()


def render_prompt(engine, messages, persona: str, memory_context: str) -> str | None:
    """取渲染后的 prompt 文本，用于检查当前 user 是否被送了两次。"""
    llm = getattr(engine, "_llm", None)
    if llm is None or not getattr(llm, "loaded", False):
        return None
    from b2_core.prompts import empathy

    return llm._render(
        empathy.build_chat_messages(messages, persona=persona, memory_context=memory_context)
    )


def check_turn_rules(reply: str, rules: dict | None) -> list[str]:
    violations: list[str] = []
    if not rules:
        return violations
    must_any = rules.get("must_include_any")
    if must_any and not any(token in reply for token in must_any):
        violations.append(f"must_include_any 未命中: {must_any}")
    must_not = rules.get("must_not_include")
    if must_not:
        for token in must_not:
            if token in reply:
                violations.append(f"must_not_include 命中: {token}")
    limit = rules.get("must_not_exceed_chars")
    if isinstance(limit, int) and len(reply) > limit:
        violations.append(f"must_not_exceed_chars 超限: {len(reply)} > {limit}")
    return violations


def check_forbidden(reply: str, forbidden: list[str] | None) -> list[str]:
    if not forbidden:
        return []
    return [f"出现禁止表述: {token}" for token in forbidden if token in reply]


def check_degeneration(reply: str, gram: int = 10, threshold: int = 3) -> dict:
    """复读退化检测：同一段 n 字片段反复出现。

    这是**质量观察**，不是案例规则违规。单独统计并在报告里列出，
    是为了避免把「0 条规则违规」误读成「回复正常」——
    实测候选模型确实会在长上下文里退化成重复句式。
    """
    text = reply.strip()
    if len(text) < gram:
        return {"max_repeat": 1, "repeated_gram": "", "degenerate": False}
    counts: dict[str, int] = {}
    for index in range(len(text) - gram + 1):
        piece = text[index : index + gram]
        counts[piece] = counts.get(piece, 0) + 1
    piece, count = max(counts.items(), key=lambda kv: kv[1])
    return {
        "max_repeat": count,
        "repeated_gram": piece,
        "degenerate": count >= threshold,
        "threshold": threshold,
        "gram": gram,
    }


# --------------------------------------------------------------------------- #
def run_multiturn(engine, case: dict, params: dict, *, record_prompt: bool) -> dict:
    from b2_core.a_impl import dtos as dtos_mod

    history: list[dict[str, str]] = []
    turn_records: list[dict] = []
    case_violations: list[str] = []

    for turn in case["turns"]:
        index = turn["index"]
        user_text = turn["text"]
        history.append({"role": "user", "content": user_text})
        request = {
            "messages": list(history),
            "memory_context": case.get("memory_context", ""),
            "persona": case.get("persona", "伴学：中文日常陪伴助手"),
            "max_new_tokens": params["max_new_tokens"],
            "temperature": params["temperature"],
        }
        trace = engine.generate_with_trace(request)
        reply = trace["reply"]

        violations = []
        if not reply.reply.strip():
            violations.append("回复为空")
        if reply.emotion not in EMOTIONS:
            violations.append(f"非法情绪: {reply.emotion!r}")
        if reply.expression not in EXPRESSIONS:
            violations.append(f"非法表情: {reply.expression!r}")
        if reply.is_mock is not bool(params["mock"]):
            violations.append(
                f"is_mock 与运行模式不一致: {reply.is_mock}（应为 {bool(params['mock'])}）"
            )
        violations += check_turn_rules(reply.reply, case.get("turn_expect", {}).get(str(index)))
        violations += check_forbidden(reply.reply, case.get("forbidden_anywhere"))

        occurrences = None
        if record_prompt:
            prompt = render_prompt(engine, request["messages"], request["persona"], request["memory_context"])
            if prompt is not None:
                occurrences = prompt.count(user_text)
                if occurrences != 1:
                    violations.append(f"当前 user 在 prompt 中出现 {occurrences} 次（应为 1）")

        turn_records.append(
            {
                "index": index,
                "user": user_text,
                "reply": reply.reply,
                "emotion": reply.emotion,
                "expression": reply.expression,
                "model_version": reply.model_version,
                "is_mock": reply.is_mock,
                "elapsed_ms": round(trace["elapsed_ms"], 1),
                "prompt_tokens": trace["prompt_tokens"],
                "new_tokens": trace["new_tokens"],
                "dropped_turns": trace.get("dropped_turns", 0),
                "current_user_occurrences_in_prompt": occurrences,
                "check_hint": turn.get("check"),
                "degeneration": check_degeneration(reply.reply),
                "violations": violations,
            }
        )
        case_violations += [f"turn{index}: {v}" for v in violations]
        history.append({"role": "assistant", "content": reply.reply})

    return {
        "case_id": case["case_id"],
        "title": case["title"],
        "expect": case["expect"],
        "memory_context": case.get("memory_context", ""),
        "turns": turn_records,
        "violations": case_violations,
    }


def run_boundary(engine, case: dict, params: dict, scratch_config: Path) -> dict:
    kind = case.get("error_kind")
    record: dict = {
        "case_id": case["case_id"],
        "title": case["title"],
        "expect": case["expect"],
        "error_kind": kind,
        "note": case.get("note", ""),
        "outcome": None,
        "error_type": None,
        "reply": None,
        "violations": [],
    }

    request = {
        "messages": case["messages"],
        "memory_context": case.get("memory_context", ""),
        "persona": case.get("persona", "伴学：中文日常陪伴助手"),
        "max_new_tokens": params["max_new_tokens"],
        "temperature": params["temperature"],
    }

    if kind == "model_missing":
        # 用一个指向不存在目录的配置构造引擎：必须抛出 ModelUnavailableError。
        try:
            ModelEngine(scratch_config)
            record["outcome"] = "unexpected_success"
            record["violations"].append("权重缺失时应当报错，却成功构造了引擎")
        except ModelUnavailableError as exc:
            record["outcome"] = "error"
            record["error_type"] = type(exc).__name__
            record["error_message"] = str(exc)[:300]
        return record

    started = time.perf_counter()
    try:
        trace = engine.generate_with_trace(request)
        record["outcome"] = "success"
        record["reply"] = trace["reply"].reply
        record["emotion"] = trace["reply"].emotion
        record["expression"] = trace["reply"].expression
        record["elapsed_ms"] = round(trace["elapsed_ms"], 1)
        record["prompt_tokens"] = trace["prompt_tokens"]
        record["dropped_turns"] = trace.get("dropped_turns", 0)
        record["violations"] += check_forbidden(trace["reply"].reply, case.get("forbidden_anywhere"))
        if not trace["reply"].reply.strip():
            record["violations"].append("回复为空")
    except (RequestError, ModelUnavailableError) as exc:
        record["outcome"] = "error"
        record["error_type"] = type(exc).__name__
        record["error_message"] = str(exc)[:300]
    except Exception as exc:  # noqa: BLE001
        record["outcome"] = "error"
        record["error_type"] = type(exc).__name__
        record["error_message"] = str(exc)[:300]
    record["elapsed_ms_total"] = round((time.perf_counter() - started) * 1000.0, 1)

    if case["expect"] == "error" and record["outcome"] != "error":
        record["violations"].append("应当明确失败，但成功了")
    if case["expect"] == "success" and record["outcome"] != "success":
        record["violations"].append("应当成功，但失败了")
    if case["expect"] == "error" and record["error_type"] != "RequestError":
        # BD1/BD2 期望的是合同校验错误
        record["violations"].append(
            f"期望 RequestError，实际 {record['error_type']}"
        )
    return record


# --------------------------------------------------------------------------- #
def main() -> int:
    args = parse_args()
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    params = dict(cases["meta"]["eval_params"])
    params["mock"] = args.mock
    # CoreRequest 合同里没有 do_sample 字段，只有 temperature；
    # 用 temperature=0 表达「贪心解码」，这样基线与候选在同一套确定性参数下比较，
    # 也才能用「重跑同一输入」检查跨样本状态。
    params["temperature"] = (
        float(params.get("temperature", 1.0)) if params.get("do_sample", False) else 0.0
    )
    params["decoding"] = "sample" if params.get("do_sample", False) else "greedy"

    scratch = WEIGHTS_DIR / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    missing_dir = scratch / "missing-model-check"
    shutil.rmtree(missing_dir, ignore_errors=True)
    scratch_config = scratch / "inference_config.missing_model.json"
    scratch_config.write_text(
        json.dumps({"model_dir": "does-not-exist-model", "model_version": "should-not-load"}),
        encoding="utf-8",
    )

    if args.mock:
        engine = MockEngine()
        engine_label = "MockEngine"
    else:
        engine = ModelEngine(args.config)
        engine_label = "ModelEngine"

    started = time.perf_counter()
    multiturn = []
    boundary = []

    selected = args.only
    for case in cases["multiturn_cases"]:
        if selected and case["case_id"] != selected:
            continue
        multiturn.append(run_multiturn(engine, case, params, record_prompt=not args.mock))
    for case in cases["boundary_cases"]:
        if selected and case["case_id"] != selected:
            continue
        boundary.append(run_boundary(engine, case, params, scratch_config))

    # 跨样本状态检查：把第一个多轮案例的第一轮重跑一次，结果应完全一致
    independence = None
    if multiturn and not args.mock:
        first = multiturn[0]
        first_turn = first["turns"][0]
        replay_request = {
            "messages": [{"role": "user", "content": first_turn["user"]}],
            "memory_context": first["memory_context"],
            "persona": cases["multiturn_cases"][0].get("persona", "伴学：中文日常陪伴助手"),
            "max_new_tokens": params["max_new_tokens"],
            "temperature": params["temperature"],
        }
        replay = engine.generate_with_trace(replay_request)
        independence = {
            "case_id": first["case_id"],
            "first_run_reply": first_turn["reply"],
            "replay_reply": replay["reply"].reply,
            "identical": replay["reply"].reply == first_turn["reply"],
        }

    elapsed = time.perf_counter() - started

    turn_violations = sum(len(case["violations"]) for case in multiturn)
    boundary_violations = sum(len(case["violations"]) for case in boundary)
    error_turns = sum(
        1 for case in multiturn for turn in case["turns"] if turn["violations"]
    )
    latencies = [
        turn["elapsed_ms"] for case in multiturn for turn in case["turns"]
    ]
    degenerate_turns = [
        {"case_id": case["case_id"], "turn": turn["index"], "repeat": turn["degeneration"]["max_repeat"],
         "gram": turn["degeneration"]["repeated_gram"]}
        for case in multiturn
        for turn in case["turns"]
        if turn.get("degeneration", {}).get("degenerate")
    ]
    reply_chars = [len(turn["reply"]) for case in multiturn for turn in case["turns"]]

    summary = {
        "label": args.label,
        "engine": engine_label,
        "config": None if args.mock else str(args.config),
        "params": params,
        "multiturn_cases": len(multiturn),
        "multiturn_turns": sum(len(case["turns"]) for case in multiturn),
        "boundary_cases": len(boundary),
        "boundary_expected_errors": sum(1 for r in boundary if r["expect"] == "error"),
        "boundary_expected_success": sum(1 for r in boundary if r["expect"] == "success"),
        "boundary_outcome_match": sum(
            1
            for r in boundary
            if (r["expect"] == "error") == (r["outcome"] == "error")
        ),
        "turns_with_violations": error_turns,
        "total_violations": turn_violations + boundary_violations,
        "degenerate_turns": len(degenerate_turns),
        "degenerate_turn_details": degenerate_turns,
        "mean_reply_chars": round(sum(reply_chars) / len(reply_chars), 1) if reply_chars else None,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "max_latency_ms": round(max(latencies), 1) if latencies else None,
        "total_eval_seconds": round(elapsed, 1),
        "model_version": getattr(engine, "model_version", None),
        "is_mock": getattr(engine, "is_mock", None),
        "independence_check": independence,
        "checks_note": (
            "规则匹配只检查接口、字段合法性、禁止表述与关键事实命中；"
            "不是官方测评分，也不构成全面安全保证。"
        ),
    }

    failures = []
    if turn_violations:
        failures.append(f"多轮案例有 {turn_violations} 条规则违规")
    for record in boundary:
        if record["violations"]:
            failures.append(f"{record['case_id']}: {record['violations']}")
    if independence is not None and not independence["identical"]:
        failures.append("跨样本状态检查失败：重跑同一输入得到不同结果")
    if getattr(engine, "is_mock", None) != args.mock:
        failures.append(f"is_mock 标记与运行模式不一致: {getattr(engine, 'is_mock', None)}")

    report = {
        "node": "A5 12 案例最小自动评测",
        "summary": summary,
        "failures": failures,
        "multiturn": multiturn,
        "boundary": boundary,
    }
    out = args.out or (REPO_ROOT / "reports" / "model" / f"a5_eval_{args.label}.json")
    path = write_report(out.name, report)

    print(f"引擎        : {engine_label}  is_mock={summary['is_mock']}  version={summary['model_version']}")
    print(f"多轮案例    : {summary['multiturn_cases']} 个 / {summary['multiturn_turns']} 轮")
    print(f"边界案例    : {summary['boundary_cases']} 个，期望失败 {summary['boundary_expected_errors']} 个，"
          f"结果符合预期 {summary['boundary_outcome_match']} 个")
    print(f"违规        : {summary['total_violations']} 条（{summary['turns_with_violations']} 轮）")
    print(f"复读退化    : {summary['degenerate_turns']} 轮（{summary['multiturn_turns']} 轮中，"
          f"同一 10 字片段重复 >=3 次即计入）")
    print(f"平均字数    : {summary['mean_reply_chars']} 字 / 轮")
    print(f"平均耗时    : {summary['avg_latency_ms']} ms / 轮")
    print(f"总耗时      : {summary['total_eval_seconds']} s")
    if independence:
        print(f"独立样本    : 重跑一致={independence['identical']}")
    for record in boundary:
        print(f"  {record['case_id']:<4} expect={record['expect']:<8} outcome={record['outcome']:<8} "
              f"{record['error_type'] or ''}")
    print(f"报告: {path}")
    if failures:
        print(f"NOTE: {len(failures)} 条规则违规（见报告，不等同官方评分）")
        for item in failures[:12]:
            print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())