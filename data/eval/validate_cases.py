#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验 data/eval/cases.json 的结构约束。

只使用 Python 标准库。全部检查通过时退出码为 0，否则打印具体原因并退出码 1。

用法：
    python validate_cases.py [cases.json 的路径]
默认路径是本脚本同目录下的 cases.json。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CASES = os.path.join(HERE, "cases.json")

MT_IDS = ["MT1", "MT2", "MT3", "MT4", "MT5", "MT6"]
BD_IDS = ["BD1", "BD2", "BD3", "BD4", "BD5", "BD6"]
MIN_TURN_CHARS = 8
MAX_TURN_CHARS = 60


class Checker:
    """收集检查结果；每条检查都会计数，失败时记录原因。"""

    def __init__(self):
        self.passed = 0
        self.failures = []

    def check(self, condition, message):
        if condition:
            self.passed += 1
        else:
            self.failures.append(message)
        return bool(condition)


def is_nonempty_str(value):
    return isinstance(value, str) and value.strip() != ""


def get_meta(cases):
    meta = cases.get("meta")
    return meta if isinstance(meta, dict) else {}


def check_meta(c, cases):
    meta = get_meta(cases)
    c.check(isinstance(meta, dict), "meta 必须是一个对象")
    for key in ("name", "version", "disclaimer", "note"):
        c.check(is_nonempty_str(meta.get(key)), "meta.%s 必须是非空字符串" % key)
    c.check(meta.get("frozen") is True, "meta.frozen 必须为 true")
    c.check(meta.get("is_official") is False, "meta.is_official 必须为 false")

    params = meta.get("eval_params")
    c.check(isinstance(params, dict), "meta.eval_params 必须是一个对象")
    if isinstance(params, dict):
        c.check(params.get("max_new_tokens") == 128, "meta.eval_params.max_new_tokens 必须为 128")
        c.check(params.get("do_sample") is False, "meta.eval_params.do_sample 必须为 false")
        c.check(params.get("temperature") == 1.0, "meta.eval_params.temperature 必须为 1.0")
        c.check(params.get("top_p") == 1.0, "meta.eval_params.top_p 必须为 1.0")


def check_forbidden(c, where, forbidden):
    if forbidden is None:
        return
    c.check(isinstance(forbidden, list), "%s.forbidden_anywhere 必须是数组" % where)
    if not isinstance(forbidden, list):
        return
    for i, item in enumerate(forbidden):
        c.check(
            is_nonempty_str(item),
            "%s.forbidden_anywhere[%d] 必须是非空字符串" % (where, i),
        )


def check_multiturn(c, cases):
    mt = cases.get("multiturn_cases")
    if not c.check(isinstance(mt, list), "multiturn_cases 必须是数组"):
        return
    if not c.check(len(mt) == 6, "multiturn_cases 长度必须为 6，实际 %d" % len(mt)):
        return

    seen_ids = []
    for i, case in enumerate(mt):
        where = "multiturn_cases[%d]" % i
        if not c.check(isinstance(case, dict), "%s 必须是对象" % where):
            continue

        cid = case.get("case_id")
        seen_ids.append(cid)
        c.check(cid == MT_IDS[i], "%s.case_id 必须是 %s，实际 %r" % (where, MT_IDS[i], cid))
        c.check(is_nonempty_str(case.get("title")), "%s.title 必须是非空字符串" % where)
        c.check(case.get("expect") == "success", "%s.expect 必须为 'success'" % where)
        c.check(
            isinstance(case.get("persona"), str),
            "%s.persona 必须是字符串" % where,
        )
        c.check(
            isinstance(case.get("memory_context"), str),
            "%s.memory_context 必须是字符串（不是数组）" % where,
        )

        turns = case.get("turns")
        if not c.check(isinstance(turns, list), "%s.turns 必须是数组" % where):
            continue
        if not c.check(len(turns) == 6, "%s.turns 长度必须为 6，实际 %d" % (where, len(turns))):
            continue

        for j, turn in enumerate(turns):
            tw = "%s.turns[%d]" % (where, j)
            if not c.check(isinstance(turn, dict), "%s 必须是对象" % tw):
                continue
            c.check(turn.get("index") == j + 1, "%s.index 必须为 %d" % (tw, j + 1))
            text = turn.get("text")
            if not c.check(is_nonempty_str(text), "%s.text 必须是非空字符串" % tw):
                continue
            n = len(text)
            c.check(
                MIN_TURN_CHARS <= n <= MAX_TURN_CHARS,
                "%s.text 长度必须在 %d~%d 之间，实际 %d：%r"
                % (tw, MIN_TURN_CHARS, MAX_TURN_CHARS, n, text),
            )
            c.check(is_nonempty_str(turn.get("check")), "%s.check 必须是非空字符串" % tw)

        te = case.get("turn_expect")
        c.check(isinstance(te, dict), "%s.turn_expect 必须是对象" % where)
        if isinstance(te, dict):
            for key in te:
                c.check(
                    isinstance(key, str) and key.isdigit() and 1 <= int(key) <= 6,
                    "%s.turn_expect 的键必须是 '1'~'6' 的轮次字符串，实际 %r" % (where, key),
                )

        check_forbidden(c, where, case.get("forbidden_anywhere"))

    c.check(
        sorted(x for x in seen_ids if isinstance(x, str)) == MT_IDS,
        "multiturn_cases 的 case_id 必须恰好是 %s 且唯一，实际 %r" % (MT_IDS, seen_ids),
    )


def check_boundary(c, cases):
    bd = cases.get("boundary_cases")
    if not c.check(isinstance(bd, list), "boundary_cases 必须是数组"):
        return
    if not c.check(len(bd) == 6, "boundary_cases 长度必须为 6，实际 %d" % len(bd)):
        return

    seen_ids = []
    by_id = {}
    for i, case in enumerate(bd):
        where = "boundary_cases[%d]" % i
        if not c.check(isinstance(case, dict), "%s 必须是对象" % where):
            continue

        cid = case.get("case_id")
        seen_ids.append(cid)
        if isinstance(cid, str):
            by_id[cid] = case

        c.check(cid == BD_IDS[i], "%s.case_id 必须是 %s，实际 %r" % (where, BD_IDS[i], cid))
        c.check(is_nonempty_str(case.get("title")), "%s.title 必须是非空字符串" % where)

        expect = case.get("expect")
        c.check(expect in ("success", "error"), "%s.expect 必须是 success 或 error，实际 %r" % (where, expect))
        if expect == "error":
            c.check(
                is_nonempty_str(case.get("error_kind")),
                "%s.expect=='error' 时 error_kind 必须是非空字符串" % where,
            )
        elif expect == "success":
            c.check(
                case.get("error_kind") is None,
                "%s.expect=='success' 时 error_kind 必须为 null，实际 %r" % (where, case.get("error_kind")),
            )

        c.check(isinstance(case.get("persona"), str), "%s.persona 必须是字符串" % where)
        c.check(isinstance(case.get("memory_context"), str), "%s.memory_context 必须是字符串" % where)
        c.check(is_nonempty_str(case.get("note")), "%s.note 必须是非空字符串" % where)

        messages = case.get("messages")
        if not c.check(isinstance(messages, list) and len(messages) > 0, "%s.messages 必须是非空数组" % where):
            continue
        for k, msg in enumerate(messages):
            mw = "%s.messages[%d]" % (where, k)
            if not c.check(isinstance(msg, dict), "%s 必须是对象" % mw):
                continue
            c.check(is_nonempty_str(msg.get("role")), "%s.role 必须是非空字符串" % mw)
            c.check(isinstance(msg.get("content"), str), "%s.content 必须是字符串" % mw)

        check_forbidden(c, where, case.get("forbidden_anywhere"))

    c.check(
        sorted(x for x in seen_ids if isinstance(x, str)) == BD_IDS,
        "boundary_cases 的 case_id 必须恰好是 %s 且唯一，实际 %r" % (BD_IDS, seen_ids),
    )

    # BD1：空输入
    bd1 = by_id.get("BD1")
    if c.check(bd1 is not None, "缺少 BD1"):
        msgs = bd1.get("messages") or []
        last_user = None
        for msg in reversed(msgs):
            if isinstance(msg, dict) and msg.get("role") == "user":
                last_user = msg
                break
        if c.check(last_user is not None, "BD1 必须包含至少一条 user 消息"):
            c.check(last_user.get("content") == "", "BD1 最后一条 user 的 content 必须为空字符串")
        c.check(bd1.get("error_kind") == "empty_input", "BD1 的 error_kind 必须为 'empty_input'")
        c.check(bd1.get("expect") == "error", "BD1 的 expect 必须为 'error'")

    # BD2：最后一条不是 user
    bd2 = by_id.get("BD2")
    if c.check(bd2 is not None, "缺少 BD2"):
        msgs = bd2.get("messages") or []
        c.check(len(msgs) > 0, "BD2 的 messages 不能为空")
        if msgs:
            last = msgs[-1]
            c.check(
                isinstance(last, dict) and last.get("role") == "assistant",
                "BD2 最后一条消息的 role 必须是 'assistant'",
            )
        c.check(bd2.get("error_kind") == "last_not_user", "BD2 的 error_kind 必须为 'last_not_user'")
        c.check(bd2.get("expect") == "error", "BD2 的 expect 必须为 'error'")

    # BD3：长历史
    bd3 = by_id.get("BD3")
    if c.check(bd3 is not None, "缺少 BD3"):
        msgs = bd3.get("messages") or []
        c.check(len(msgs) >= 30, "BD3 的 messages 数量必须 >= 30，实际 %d" % len(msgs))
        if msgs:
            last = msgs[-1]
            c.check(
                isinstance(last, dict) and last.get("role") == "user",
                "BD3 最后一条消息的 role 必须是 'user'",
            )
        long_users = [
            m for m in msgs
            if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str)
            and 300 <= len(m.get("content", "")) <= 800
        ]
        c.check(len(long_users) >= 1, "BD3 必须至少有一条长度 300~800 的 user 内容，实际 %d 条" % len(long_users))
        c.check(bd3.get("expect") == "success", "BD3 的 expect 必须为 'success'")
        c.check(bd3.get("error_kind") is None, "BD3 的 error_kind 必须为 null")

    # BD6：模型文件缺失
    bd6 = by_id.get("BD6")
    if c.check(bd6 is not None, "缺少 BD6"):
        c.check(bd6.get("error_kind") == "model_missing", "BD6 的 error_kind 必须为 'model_missing'")
        c.check(bd6.get("expect") == "error", "BD6 的 expect 必须为 'error'")

    # BD4 / BD5：应为 success 且有注入/安全相关的 forbidden_anywhere
    for cid in ("BD4", "BD5"):
        case = by_id.get(cid)
        if c.check(case is not None, "缺少 %s" % cid):
            c.check(case.get("expect") == "success", "%s 的 expect 必须为 'success'" % cid)
            c.check(case.get("error_kind") is None, "%s 的 error_kind 必须为 null" % cid)
            forbidden = case.get("forbidden_anywhere")
            c.check(
                isinstance(forbidden, list) and len(forbidden) >= 4,
                "%s 的 forbidden_anywhere 至少需要 4 条" % cid,
            )


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CASES
    c = Checker()

    try:
        with open(path, "r", encoding="utf-8") as fh:
            cases = json.load(fh)
    except FileNotFoundError:
        print("检查失败：找不到文件 %s" % path)
        return 1
    except json.JSONDecodeError as exc:
        print("检查失败：JSON 无法解析：%s" % exc)
        return 1
    except OSError as exc:
        print("检查失败：无法读取 %s：%s" % (path, exc))
        return 1

    if not c.check(isinstance(cases, dict), "顶层必须是 JSON 对象"):
        return report(c)

    c.check(isinstance(cases.get("meta"), dict), "缺少 meta")
    if isinstance(cases.get("meta"), dict):
        check_meta(c, cases)
    c.check(isinstance(cases.get("multiturn_cases"), list), "缺少 multiturn_cases 数组")
    c.check(isinstance(cases.get("boundary_cases"), list), "缺少 boundary_cases 数组")

    check_multiturn(c, cases)
    check_boundary(c, cases)

    return report(c)


def report(c):
    if c.failures:
        print("检查失败：共 %d 项检查，%d 项未通过。" % (c.passed + len(c.failures), len(c.failures)))
        for i, reason in enumerate(c.failures, 1):
            print("  [%d] %s" % (i, reason))
        return 1

    print("全部检查通过：%d 项。" % c.passed)
    print("  meta 校验通过（frozen/is_official/eval_params）。")
    print("  multiturn_cases：6 个案例，每个 6 轮，case_id 为 MT1..MT6，轮次文本长度 8~60。")
    print("  boundary_cases：6 个案例，case_id 为 BD1..BD6；BD1 空输入 / BD2 末条非 user / BD3 长历史 / BD4 诊断越界 / BD5 记忆注入 / BD6 权重缺失。")
    print("  forbidden_anywhere：所有元素均为非空字符串。")
    return 0


if __name__ == "__main__":
    sys.exit(main())