#!/usr/bin/env python3
"""合同绑定检查：验证「B 的 ``b2_core.contracts`` 一落地，A 的引擎就自动切换」。

A 的引擎是**按引擎实例**解析合同的（``ModelEngine.__init__`` 里调 ``resolve_contracts()``），
所以这里不需要改 A 的代码，只要在构造引擎之前把 ``b2_core.contracts`` 装进
``sys.modules`` 就行。

检查四件事：

1. 没有 ``b2_core.contracts`` 时，用 A 的兜底 dataclass，引擎照常工作；
2. 有完整的 ``b2_core.contracts`` 时，``generate`` 返回**对方的** ``CoreReply``，
   ``generate_official`` 返回**对方的** ``OfficialPrediction``，且画像字段是对方的嵌套类型；
3. ``b2_core.contracts`` 少一个必需名字时，**整体退回兜底**，不出现「一半 B 一半 A」；
4. ``b2_core.contracts`` 导入就抛异常时，同样安全退回。

**不会在仓库里创建 ``src/b2_core/contracts.py``**（那是 B 的文件），
伪造模块只存在于内存里，脚本结束即消失。

结果写入 ``reports/model/a5_contract_binding.json``。
"""
from __future__ import annotations

import dataclasses
import json
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import WEIGHTS_DIR, bootstrap, write_report  # noqa: E402

bootstrap()

from b2_core.a_impl import dtos as dtos_mod  # noqa: E402
from b2_core.model import MockEngine, ModelEngine  # noqa: E402


# --------------------------------------------------------------------------- #
# 伪造 B 的合同模块
#
# 这些类必须定义在**模块级**：本文件用了 ``from __future__ import annotations``，
# 注解是字符串，``typing.get_type_hints`` 需要用模块全局命名空间来解析
# ``user_profile: UserProfile`` 这种嵌套注解。定义在函数局部作用域里会解析失败，
# 那样就测不到「嵌套画像类型」这条路径了。
# --------------------------------------------------------------------------- #
@dataclasses.dataclass
class Message:
    role: str
    content: str


@dataclasses.dataclass
class CoreRequest:
    messages: list
    memory_context: str = ""
    persona: str = ""
    max_new_tokens: int = 256
    temperature: float = 0.3


@dataclasses.dataclass
class CoreReply:
    reply: str
    emotion: str
    expression: str
    model_version: str
    is_mock: bool


@dataclasses.dataclass
class OfficialTurn:
    turn_id: int
    role: str
    content: str


@dataclasses.dataclass
class OfficialRequest:
    sample_id: str
    history: list
    conversation_id: str | None = None
    target_user_turn_id: int | None = None


@dataclasses.dataclass
class UserProfile:
    personality_traits: list
    interests: list
    style: list


@dataclasses.dataclass
class OfficialPrediction:
    response_text: str
    emotion_label: str
    user_profile: UserProfile
    memory_refs: list


FAKE_NAMES = {
    "Message": Message,
    "CoreRequest": CoreRequest,
    "CoreReply": CoreReply,
    "OfficialTurn": OfficialTurn,
    "OfficialRequest": OfficialRequest,
    "UserProfile": UserProfile,
    "OfficialPrediction": OfficialPrediction,
}


def build_fake_contracts(*, omit: str | None = None) -> types.ModuleType:
    module = types.ModuleType("b2_core.contracts")
    module.__doc__ = "测试用的伪造合同，只在内存里存在。"
    for name, value in FAKE_NAMES.items():
        if name == omit:
            continue
        setattr(module, name, value)
    return module


def install(module: types.ModuleType | None) -> None:
    """把伪造模块装进/移出 sys.modules，并同步包属性。"""
    import b2_core

    if module is None:
        sys.modules.pop("b2_core.contracts", None)
        if hasattr(b2_core, "contracts"):
            delattr(b2_core, "contracts")
        return
    sys.modules["b2_core.contracts"] = module
    b2_core.contracts = module


class ExplodingModule(types.ModuleType):
    def __getattr__(self, name):  # pragma: no cover - 只用于制造导入异常
        raise ImportError("伪造的导入失败")


# --------------------------------------------------------------------------- #
CORE_REQUEST = {
    "messages": [
        {"role": "user", "content": "我下周要考高数。"},
        {"role": "assistant", "content": "听起来你有点惦记这件事。"},
        {"role": "user", "content": "对，我特别怕考砸。"},
    ],
    "memory_context": "小然在读大二。小然在准备高数考试。",
    "persona": "伴学：中文日常陪伴助手",
    "max_new_tokens": 48,
    "temperature": 0.0,
}

OFFICIAL_REQUEST = {
    "sample_id": "bind_0001_t3",
    "conversation_id": "bind_0001",
    "target_user_turn_id": 3,
    "history": [
        {"turn_id": 1, "role": "user", "content": "我下周要考高数。"},
        {"turn_id": 2, "role": "assistant", "content": "听起来你有点惦记这件事。"},
        {"turn_id": 3, "role": "user", "content": "对，我特别怕考砸。"},
    ],
}


def scenario(label: str, module, note: str) -> dict:
    """在一个合同场景下跑一遍 MockEngine，返回可核对的记录。"""
    install(module)
    engine = MockEngine()
    source = engine._binding.source

    reply = engine.generate(CORE_REQUEST)
    prediction, trace = engine.official_trace(OFFICIAL_REQUEST)
    as_dict = dtos_mod.prediction_as_dict(prediction)

    reply_cls_name = type(reply).__module__ + "." + type(reply).__name__
    pred_cls_name = type(prediction).__module__ + "." + type(prediction).__name__
    profile = getattr(prediction, "user_profile", None)
    profile_cls_name = type(profile).__module__ + "." + type(profile).__name__

    # 用「是不是同一个类对象」判断，而不是比字符串名，避免被模块名骗过
    uses_a_types = all(
        cls.__module__.startswith("b2_core.a_impl")
        for cls in (type(reply), type(prediction), type(profile))
    )
    # 注意：module 可能在属性访问时抛异常（ExplodingModule），所以这里也要防
    try:
        uses_b_types = bool(
            module is not None
            and type(reply) is getattr(module, "CoreReply", None)
            and type(prediction) is getattr(module, "OfficialPrediction", None)
            and type(profile) is getattr(module, "UserProfile", None)
        )
    except Exception:  # noqa: BLE001
        uses_b_types = False

    allowed = {"response_text", "emotion_label", "user_profile", "memory_refs"}
    problems = []
    if set(as_dict) != allowed:
        problems.append(f"四字段不合规: {sorted(as_dict)}")
    if as_dict["memory_refs"] != []:
        problems.append(f"memory_refs 应为 []，实际 {as_dict['memory_refs']}")
    if not as_dict["response_text"]:
        problems.append("response_text 为空")

    return {
        "scenario": label,
        "note": note,
        "contract_source": source,
        "reply_class": reply_cls_name,
        "prediction_class": pred_cls_name,
        "profile_class": profile_cls_name,
        "uses_a_types": uses_a_types,
        "uses_b_types": uses_b_types,
        "prediction_as_dict": as_dict,
        "trace_is_mock": trace["is_mock"],
        "problems": problems,
    }


def main() -> int:
    failures: list[str] = []
    results = []

    # 场景 1：没有 b2_core.contracts
    results.append(
        scenario(
            "fallback",
            None,
            "仓库里没有 b2_core.contracts，应当用 A 的兜底 dataclass。",
        )
    )
    if results[-1]["contract_source"] != dtos_mod.CONTRACT_SOURCE_FALLBACK:
        failures.append("场景 fallback 没有使用兜底合同")
    if not results[-1]["uses_a_types"]:
        failures.append(f"场景 fallback 的类型不是 A 的: {results[-1]['reply_class']}")

    # 场景 2：完整的 b2_core.contracts
    fake = build_fake_contracts()
    results.append(
        scenario(
            "b_contracts_full",
            fake,
            "B 的合同齐全时，引擎应当自动改用 B 的类型。",
        )
    )
    last = results[-1]
    if last["contract_source"] != dtos_mod.CONTRACT_SOURCE_B:
        failures.append("场景 b_contracts_full 没有切到 b2_core.contracts")
    if not last["uses_b_types"]:
        failures.append(
            f"没有整体使用 B 的类型: reply={last['reply_class']} "
            f"prediction={last['prediction_class']} profile={last['profile_class']}"
        )
    if last["profile_class"] == "builtins.dict":
        failures.append(
            "user_profile 退化成了 dict，没有用 B 声明的嵌套类型"
            "（这一项以前在 pydantic 上出过 dict 访问错误）"
        )

    # 场景 3：少一个必需名字
    results.append(
        scenario(
            "b_contracts_incomplete",
            build_fake_contracts(omit="OfficialPrediction"),
            "B 的合同缺 OfficialPrediction 时，应当整体退回兜底，不能一半 B 一半 A。",
        )
    )
    last = results[-1]
    if last["contract_source"] != dtos_mod.CONTRACT_SOURCE_FALLBACK:
        failures.append("场景 b_contracts_incomplete 没有退回兜底")
    if not last["uses_a_types"]:
        failures.append("场景 b_contracts_incomplete 混用了 B 的类型")

    # 场景 4：属性访问就抛异常
    results.append(
        scenario(
            "b_contracts_explodes",
            ExplodingModule("b2_core.contracts"),
            "B 的合同在属性访问时抛异常，应当安全退回兜底而不是把异常抛给调用方。",
        )
    )
    if results[-1]["contract_source"] != dtos_mod.CONTRACT_SOURCE_FALLBACK:
        failures.append("场景 b_contracts_explodes 没有安全退回")
    if not results[-1]["uses_a_types"]:
        failures.append("场景 b_contracts_explodes 混用了 B 的类型")

    # 场景 5：真实引擎也用上 B 的合同
    real_fake = build_fake_contracts()
    install(real_fake)
    real = ModelEngine(WEIGHTS_DIR / "inference_config.json")
    started = time.perf_counter()
    core_reply = real.generate(CORE_REQUEST)
    official_prediction = real.generate_official(OFFICIAL_REQUEST)
    real_seconds = time.perf_counter() - started
    real_profile = getattr(official_prediction, "user_profile", None)
    real_record = {
        "scenario": "real_engine_with_b_contracts",
        "note": "交付的真实引擎在 B 的合同下也必须能跑通两个接口。",
        "contract_source": real._binding.source,
        "engine": real.describe(),
        "reply_class": type(core_reply).__module__ + "." + type(core_reply).__name__,
        "prediction_class": type(official_prediction).__module__ + "." + type(official_prediction).__name__,
        "profile_class": type(real_profile).__module__ + "." + type(real_profile).__name__,
        "uses_b_types": bool(
            type(core_reply) is real_fake.CoreReply
            and type(official_prediction) is real_fake.OfficialPrediction
            and type(real_profile) is real_fake.UserProfile
        ),
        "reply": core_reply.reply,
        "emotion": core_reply.emotion,
        "expression": core_reply.expression,
        "is_mock": core_reply.is_mock,
        "prediction": dtos_mod.prediction_as_dict(official_prediction),
        "seconds": round(real_seconds, 2),
        "problems": [],
    }
    if real._binding.source != dtos_mod.CONTRACT_SOURCE_B:
        real_record["problems"].append("真实引擎没有切到 B 的合同")
    if not real_record["uses_b_types"]:
        real_record["problems"].append(
            f"真实引擎没有整体使用 B 的类型: reply={real_record['reply_class']} "
            f"prediction={real_record['prediction_class']} profile={real_record['profile_class']}"
        )
    if real_record["is_mock"] is not False:
        real_record["problems"].append("真实引擎 is_mock 必须为 False")
    if real_record["prediction"]["memory_refs"] != []:
        real_record["problems"].append("公开测试 memory_refs 必须为 []")
    if real_record["seconds"] > 60:
        real_record["problems"].append(f"真实引擎两个接口耗时 {real_record['seconds']}s，过慢")
    failures += [f"real_engine: {p}" for p in real_record["problems"]]
    results.append(real_record)

    # 还原：不要把伪造模块留在 sys.modules 里
    install(None)
    if "b2_core.contracts" in sys.modules:
        failures.append("测试结束后没有清掉伪造的 b2_core.contracts")

    report = {
        "node": "合同绑定检查（B 的 contracts 自动切换）",
        "explanation": (
            "引擎在构造时解析合同：b2_core.contracts 齐全就用 B 的，否则整体退回 A 的兜底。"
            "伪造模块只存在于内存，仓库里不会出现 src/b2_core/contracts.py。"
        ),
        "scenarios": results,
        "failures": failures,
        "note": "这是集成路径检查，不是效果评估，也不是官方评分。",
    }
    path = write_report("a5_contract_binding.json", report)

    for record in results:
        print(f"--- {record['scenario']}")
        print(f"  合同来源  : {record['contract_source']}")
        print(f"  CoreReply : {record['reply_class']}")
        print(f"  预测类型  : {record['prediction_class']}")
        if "profile_class" in record:
            print(f"  画像类型  : {record['profile_class']}")
        if record.get("problems"):
            print(f"  问题      : {record['problems']}")
    print(f"报告: {path}")
    if failures:
        print(f"FAIL: {len(failures)} 项未通过")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("PASS: 有 B 的 contracts 就自动用 B 的，缺失或异常时整体安全退回兜底")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())