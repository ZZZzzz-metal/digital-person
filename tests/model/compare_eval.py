#!/usr/bin/env python3
"""A5：把基线与候选的评测结果并排比较，写成一份可交接的表。

输入是 ``run_eval.py`` 生成的两份报告（``a5_eval_baseline.json`` /
``a5_eval_candidate.json``），逐案例、逐轮对齐后比较：

- 规则违规数是否变化（这是 A 自己定的规则，**不等同官方评分**）；
- 同一轮回复是否变化；
- 有长度约束的轮次是否更接近约束；
- 边界案例是否仍然按预期失败（不该"修好"）；
- 跨样本状态是否仍然独立。

输出 ``reports/model/a5_eval_compare.json`` 与 ``reports/model/a5_compare.md``。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS = REPO_ROOT / "reports" / "model"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="比较基线与候选评测")
    parser.add_argument("--baseline", default="a5_eval_baseline.json")
    parser.add_argument("--candidate", default="a5_eval_candidate.json")
    return parser.parse_args()


def load(name: str) -> dict:
    path = REPORTS / name
    if not path.is_file():
        raise SystemExit(f"缺少评测报告: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    baseline = load(args.baseline)
    candidate = load(args.candidate)

    base_cases = {c["case_id"]: c for c in baseline["multiturn"]}
    cand_cases = {c["case_id"]: c for c in candidate["multiturn"]}

    case_rows = []
    changed_turns = 0
    total_turns = 0
    for case_id in sorted(base_cases):
        base_case = base_cases[case_id]
        cand_case = cand_cases.get(case_id)
        if cand_case is None:
            continue
        turns = []
        for base_turn, cand_turn in zip(base_case["turns"], cand_case["turns"]):
            total_turns += 1
            changed = base_turn["reply"] != cand_turn["reply"]
            changed_turns += int(changed)
            turns.append(
                {
                    "index": base_turn["index"],
                    "user": base_turn["user"],
                    "baseline_reply": base_turn["reply"],
                    "candidate_reply": cand_turn["reply"],
                    "changed": changed,
                    "baseline_chars": len(base_turn["reply"]),
                    "candidate_chars": len(cand_turn["reply"]),
                }
            )
        case_rows.append(
            {
                "case_id": case_id,
                "title": base_case["title"],
                "case_type": base_case.get("case_type"),
                "baseline_violations": base_case["violations"],
                "candidate_violations": cand_case["violations"],
                "baseline_latency_ms": base_case.get("elapsed_ms"),
                "candidate_latency_ms": cand_case.get("elapsed_ms"),
                "turns": turns,
            }
        )

    base_edges = {c["case_id"]: c for c in baseline["boundary"]}
    cand_edges = {c["case_id"]: c for c in candidate["boundary"]}
    edge_rows = []
    for case_id in sorted(base_edges):
        base_edge = base_edges[case_id]
        cand_edge = cand_edges.get(case_id, {})
        outcome_changed = base_edge.get("outcome") != cand_edge.get("outcome")
        edge_rows.append(
            {
                "case_id": case_id,
                "title": base_edge.get("title"),
                "expect": base_edge.get("expect"),
                "baseline_outcome": base_edge.get("outcome"),
                "candidate_outcome": cand_edge.get("outcome"),
                "outcome_changed": outcome_changed,
                "baseline_ok": base_edge.get("ok"),
                "candidate_ok": cand_edge.get("ok"),
            }
        )

    base_violations = sum(len(c["violations"]) for c in baseline["multiturn"])
    cand_violations = sum(len(c["violations"]) for c in candidate["multiturn"])

    comparison = {
        "node": "A5 基线与候选对比",
        "baseline": {
            "file": args.baseline,
            "engine": baseline.get("engine"),
            "violations": base_violations,
            "violating_turns": sum(1 for c in baseline["multiturn"] if c["violations"]),
            "mean_latency_ms": baseline.get("mean_latency_ms"),
            "total_seconds": baseline.get("total_seconds"),
            "sample_independence_ok": baseline.get("sample_independence", {}).get("ok"),
        },
        "candidate": {
            "file": args.candidate,
            "engine": candidate.get("engine"),
            "violations": cand_violations,
            "violating_turns": sum(1 for c in candidate["multiturn"] if c["violations"]),
            "mean_latency_ms": candidate.get("mean_latency_ms"),
            "total_seconds": candidate.get("total_seconds"),
            "sample_independence_ok": candidate.get("sample_independence", {}).get("ok"),
        },
        "turns": {
            "total": total_turns,
            "changed": changed_turns,
            "changed_ratio": round(changed_turns / total_turns, 4) if total_turns else None,
        },
        "violation_delta": cand_violations - base_violations,
        "multiturn": case_rows,
        "boundary": edge_rows,
        "boundary_outcome_changes": [e for e in edge_rows if e["outcome_changed"]],
        "caveats": [
            "违规项是 A 自己写的规则（必须包含 / 长度上限 / 禁止词），不等同官方评分。",
            "12 个案例是 A 手写的小样本，样本量小，不能证明泛化能力。",
            "官方合同的回归只在公开的 3 条推理输入上跑通，不等于官方测试集表现。",
            "候选只训练了 200 条合成样本、最后 4 层，训练规模很小，效果差异不代表方法优劣。",
        ],
    }

    out_json = REPORTS / "a5_eval_compare.json"
    out_json.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 基线与候选评测对比",
        "",
        "| 项 | 基线 | 候选 |",
        "| --- | --- | --- |",
        f"| 模型版本 | `{baseline.get('engine', {}).get('model_version')}` | `{candidate.get('engine', {}).get('model_version')}` |",
        f"| 规则违规 | {base_violations} | {cand_violations} |",
        f"| 平均耗时 | {baseline.get('mean_latency_ms')} ms/轮 | {candidate.get('mean_latency_ms')} ms/轮 |",
        f"| 独立样本一致 | {baseline.get('sample_independence', {}).get('ok')} | {candidate.get('sample_independence', {}).get('ok')} |",
        f"| 回复变化的轮次 | — | {changed_turns}/{total_turns} |",
        "",
        "## 多轮案例",
        "",
        "| 案例 | 基线违规 | 候选违规 |",
        "| --- | --- | --- |",
    ]
    for row in case_rows:
        lines.append(
            f"| {row['case_id']} {row['title']} | {len(row['baseline_violations'])} | {len(row['candidate_violations'])} |"
        )
    lines += ["", "## 边界案例", "", "| 案例 | 期望 | 基线 | 候选 | 结果变化 |", "| --- | --- | --- | --- | --- |"]
    for row in edge_rows:
        lines.append(
            f"| {row['case_id']} | {row['expect']} | {row['baseline_outcome']} | {row['candidate_outcome']} | "
            f"{'是' if row['outcome_changed'] else '否'} |"
        )
    lines += ["", "## 注意", ""]
    lines += [f"- {item}" for item in comparison["caveats"]]
    lines.append("")
    (REPORTS / "a5_compare.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"基线违规 {base_violations} -> 候选违规 {cand_violations} (delta {cand_violations - base_violations})")
    print(f"回复变化轮次: {changed_turns}/{total_turns}")
    print(f"边界结果变化: {len(comparison['boundary_outcome_changes'])} 个")
    print(f"报告: {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())