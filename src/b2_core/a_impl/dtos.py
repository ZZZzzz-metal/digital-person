"""A 分工的类型解析层：优先使用 B 的共享合同，缺失时用同字段兜底类型。

这条线的三条规则：

1. **不另建一套对外共享类型。** 共享类型由 B 在 ``src/b2_core/contracts.py`` 维护。
   本模块只做「能导到 B 的类就用 B 的类」。
2. **引擎不依赖调用方的类型。** ``generate`` / ``generate_official`` 只按属性读取输入
   （也接受 dict），所以 B 用 pydantic 构造的对象可以直接传进来，A 不需要装 pydantic。
3. **B 的合同还没落地时 A 仍然能独立运行。** 兜底类型字段与
   ``docs/分工/00-总约定.md`` 第 5 节完全一致，并在返回值上标记来源，
   便于交接时说明「当前跑的是兜底合同，合同到位后应切换到 B 的类」。
"""
from __future__ import annotations

import dataclasses
import typing
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

CONTRACT_SOURCE_B = "b2_core.contracts"
CONTRACT_SOURCE_FALLBACK = "b2_core.a_impl.dtos (A 兜底合同)"

Emotion = Literal["neutral", "happy", "sad", "anxious", "angry", "unknown"]
Expression = Literal["neutral", "smile", "concern", "listening"]

EMOTIONS: tuple[str, ...] = ("neutral", "happy", "sad", "anxious", "angry", "unknown")
EXPRESSIONS: tuple[str, ...] = ("neutral", "smile", "concern", "listening")


# --------------------------------------------------------------------------- #
# A 兜底类型（字段与 00-总约定.md 第 5 节一致；B 的 contracts.py 到位后不再使用）
# --------------------------------------------------------------------------- #
@dataclass
class Message:
    role: str
    content: str


@dataclass
class CoreRequest:
    messages: list[Message] = field(default_factory=list)
    memory_context: str = ""
    persona: str = "伴学：中文日常陪伴助手"
    max_new_tokens: int = 256
    temperature: float = 0.3


@dataclass
class CoreReply:
    reply: str
    emotion: str = "unknown"
    expression: str = "listening"
    model_version: str = ""
    is_mock: bool = False


@dataclass
class OfficialTurn:
    """官方输入 history 的一项。"""

    role: str
    content: str
    turn_id: int | None = None


@dataclass
class OfficialRequest:
    """官方单样本生成请求。

    对应官方 ``test_inference_data.jsonl`` 的一行：``id`` / ``conversation_id`` /
    ``target_user_turn_id`` / ``history``。历史**已经包含**目标 user 轮，
    调用方与引擎都不得再追加当前问题，也不得把上一条预测追加回历史。

    ``id`` 由 B 原样回填到官方输出，所以 A 的生成结果里不含 ``id``。
    """

    sample_id: str
    history: list[OfficialTurn] = field(default_factory=list)
    conversation_id: str | None = None
    target_user_turn_id: int | None = None
    memory_context: str = ""


@dataclass
class UserProfile:
    personality_traits: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    style: list[str] = field(default_factory=list)


@dataclass
class OfficialPrediction:
    """成功生成的官方结果；不含 id（B 回填），不含 is_mock / 表情 / 耗时。

    只包含 ``contracts/official/model_prediction.schema.json`` 允许的四个字段。
    """

    response_text: str
    emotion_label: str
    user_profile: UserProfile = field(default_factory=UserProfile)
    memory_refs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "response_text": self.response_text,
            "emotion_label": self.emotion_label,
            "user_profile": {
                "personality_traits": list(self.user_profile.personality_traits),
                "interests": list(self.user_profile.interests),
                "style": list(self.user_profile.style),
            },
            "memory_refs": list(self.memory_refs),
        }

    # 与 pydantic 接口对齐，方便 B 的既有代码直接调用
    def model_dump(self) -> dict[str, Any]:
        return self.as_dict()

    def dict(self) -> dict[str, Any]:
        return self.as_dict()


# --------------------------------------------------------------------------- #
# 合同解析
# --------------------------------------------------------------------------- #
@dataclass
class ContractBinding:
    """描述当前实际使用的是哪一套类型。"""

    source: str
    CoreReply: Any
    CoreRequest: Any
    Message: Any
    OfficialPrediction: Any
    OfficialRequest: Any
    OfficialTurn: Any
    messages: tuple[str, ...]


def _try_import_contracts() -> Any | None:
    try:  # B 的共享合同
        from b2_core import contracts  # type: ignore
    except Exception:
        return None
    return contracts


def resolve_contracts() -> ContractBinding:
    """解析共享类型：B 的 contracts 优先，缺失则用 A 的兜底类型。

    只要 B 的模块导得进来、且所需名字齐全，就用 B 的；否则整体退到兜底，
    避免出现「一半 B 一半 A」的混合类型。
    """
    module = _try_import_contracts()
    wanted = ("CoreRequest", "CoreReply", "Message", "OfficialRequest", "OfficialPrediction")
    reason = "b2_core.contracts 不存在或导入失败"
    if module is not None:
        # 连「检查属性」也要防：B 的模块可能在属性访问或类型构造时才抛异常
        # （例如 pydantic 版本不匹配）。任何一种异常都必须整体退回兜底，
        # 不能让适配层把异常抛给调用方，也不能留下半套类型。
        try:
            missing = [name for name in wanted if not hasattr(module, name)]
        except Exception as exc:  # noqa: BLE001
            missing = None
            reason = f"b2_core.contracts 读取属性失败: {type(exc).__name__}: {exc}"
        if missing is not None and not missing:
            try:
                official_turn = getattr(module, "OfficialTurn", OfficialTurn)
                return ContractBinding(
                    source=CONTRACT_SOURCE_B,
                    CoreReply=module.CoreReply,
                    CoreRequest=module.CoreRequest,
                    Message=module.Message,
                    OfficialPrediction=module.OfficialPrediction,
                    OfficialRequest=module.OfficialRequest,
                    OfficialTurn=official_turn,
                    messages=(),
                )
            except Exception as exc:  # noqa: BLE001
                reason = f"b2_core.contracts 读取类型失败: {type(exc).__name__}: {exc}"
        elif missing:
            reason = f"b2_core.contracts 缺少: {missing}"

    return ContractBinding(
        source=CONTRACT_SOURCE_FALLBACK,
        CoreReply=CoreReply,
        CoreRequest=CoreRequest,
        Message=Message,
        OfficialPrediction=OfficialPrediction,
        OfficialRequest=OfficialRequest,
        OfficialTurn=OfficialTurn,
        messages=(reason,),
    )


# --------------------------------------------------------------------------- #
# 输入规范化：接受 dict / 对象 / 元组，避免引擎绑死在某一种类型上
# --------------------------------------------------------------------------- #
class RequestError(ValueError):
    """输入不符合合同（B 的 API 应把它映射成 400）。"""


def _get(source: Any, name: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def is_empty_text(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def coerce_message(raw: Any, *, index: int) -> Message:
    role = _get(raw, "role")
    content = _get(raw, "content")
    if isinstance(raw, (list, tuple)) and len(raw) == 2 and role is None:
        role, content = raw[0], raw[1]
    if role not in ("user", "assistant"):
        raise RequestError(f"messages[{index}].role 必须是 user 或 assistant，实际是 {role!r}")
    if not isinstance(content, str):
        raise RequestError(f"messages[{index}].content 必须是字符串")
    return Message(role=role, content=content)


def coerce_messages(raw: Any) -> list[Message]:
    if raw is None:
        raise RequestError("messages 不能为空")
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise RequestError("messages 必须是数组")
    return [coerce_message(item, index=i) for i, item in enumerate(raw)]


@dataclass
class NormalizedCoreRequest:
    """引擎内部使用的规范化请求（与调用方类型解耦）。"""

    messages: list[Message]
    memory_context: str
    persona: str
    max_new_tokens: int
    temperature: float


def normalize_core_request(raw: Any) -> NormalizedCoreRequest:
    """校验并规范化 CoreRequest。

    校验规则来自 ``00-总约定.md``：最后一条必须是本轮 user（不得追加两次），
    用户输入为空或超长由 B 的 API 处理成 400；这里对空输入同样拒绝，
    保证引擎单独被调用时也不会生成无意义回复。
    """
    messages = coerce_messages(_get(raw, "messages"))
    if not messages:
        raise RequestError("messages 不能为空")
    if messages[-1].role != "user":
        raise RequestError("messages 最后一条必须是本轮 user 输入")
    if is_empty_text(messages[-1].content):
        raise RequestError("当前用户输入不能为空")

    memory_context = _get(raw, "memory_context", "") or ""
    if not isinstance(memory_context, str):
        raise RequestError("memory_context 必须是字符串")

    persona = _get(raw, "persona", None)
    if persona is None:
        persona = "伴学：中文日常陪伴助手"
    if not isinstance(persona, str):
        raise RequestError("persona 必须是字符串")

    max_new_tokens = _get(raw, "max_new_tokens", None)
    if max_new_tokens is None:
        max_new_tokens = 256
    if isinstance(max_new_tokens, bool) or not isinstance(max_new_tokens, int) or max_new_tokens <= 0:
        raise RequestError("max_new_tokens 必须是正整数")

    temperature = _get(raw, "temperature", None)
    if temperature is None:
        temperature = 0.3
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise RequestError("temperature 必须是数字")

    return NormalizedCoreRequest(
        messages=messages,
        memory_context=memory_context,
        persona=persona,
        max_new_tokens=max_new_tokens,
        temperature=float(temperature),
    )


@dataclass
class NormalizedOfficialRequest:
    sample_id: str
    history: list[OfficialTurn]
    conversation_id: str | None
    target_user_turn_id: int | None
    memory_context: str


def normalize_official_request(raw: Any) -> NormalizedOfficialRequest:
    """校验并规范化 OfficialRequest。

    官方输入边界（``docs/官方接口核对.md``）：
    - ``id`` 必须是非空字符串，B 原样回填到输出；
    - ``history`` 必须是非空数组，每项 role ∈ {user, assistant}、content 是字符串；
    - 历史**最后一项必须是目标 user**，引擎不接受「需要自己补当前问题」的输入，
      这样就不会出现「当前 user 重复两次」或「把上一条预测追加回输入」。
    """
    sample_id = _get(raw, "sample_id", None)
    if sample_id is None:
        sample_id = _get(raw, "id")
    if is_empty_text(sample_id):
        raise RequestError("OfficialRequest.sample_id 必须是非空字符串")

    raw_history = _get(raw, "history")
    if raw_history is None:
        raise RequestError("OfficialRequest.history 不能为空")
    if isinstance(raw_history, (str, bytes)) or not isinstance(raw_history, Sequence):
        raise RequestError("OfficialRequest.history 必须是数组")

    history: list[OfficialTurn] = []
    for index, item in enumerate(raw_history):
        role = _get(item, "role")
        content = _get(item, "content")
        if role not in ("user", "assistant"):
            raise RequestError(f"history[{index}].role 必须是 user 或 assistant，实际是 {role!r}")
        if not isinstance(content, str):
            raise RequestError(f"history[{index}].content 必须是字符串")
        turn_id = _get(item, "turn_id")
        if turn_id is not None and (isinstance(turn_id, bool) or not isinstance(turn_id, int)):
            turn_id = None
        history.append(OfficialTurn(role=role, content=content, turn_id=turn_id))

    if not history:
        raise RequestError("OfficialRequest.history 不能为空数组")
    if history[-1].role != "user":
        raise RequestError("OfficialRequest.history 最后一项必须是目标 user 轮")
    if is_empty_text(history[-1].content):
        raise RequestError("OfficialRequest 最后一项 user 内容不能为空")

    conversation_id = _get(raw, "conversation_id")
    if conversation_id is not None and not isinstance(conversation_id, str):
        conversation_id = None

    target_turn = _get(raw, "target_user_turn_id")
    if isinstance(target_turn, bool) or not isinstance(target_turn, int):
        target_turn = None

    memory_context = _get(raw, "memory_context", "") or ""
    if not isinstance(memory_context, str):
        raise RequestError("OfficialRequest.memory_context 必须是字符串")

    return NormalizedOfficialRequest(
        sample_id=str(sample_id),
        history=history,
        conversation_id=conversation_id,
        target_user_turn_id=target_turn,
        memory_context=memory_context,
    )


def build_reply(binding: ContractBinding, **kwargs: Any) -> Any:
    """按当前绑定构造输出对象；pydantic 与 dataclass 都接受关键字构造。"""
    return binding.CoreReply(**kwargs)


def _profile_class(factory: Any) -> type | None:
    """找出 ``user_profile`` 字段声明的类型（pydantic 与 dataclass 都支持）。"""
    fields = getattr(factory, "model_fields", None)
    if isinstance(fields, dict):
        annotation = fields.get("user_profile")
        candidate = getattr(annotation, "annotation", None)
        if isinstance(candidate, type):
            return candidate
    try:
        hints = typing.get_type_hints(factory)
    except Exception:
        return None
    candidate = hints.get("user_profile")
    return candidate if isinstance(candidate, type) else None


def build_prediction(binding: ContractBinding, payload: dict[str, Any]) -> Any:
    """构造 OfficialPrediction，兼容 pydantic 的嵌套模型与兜底 dataclass。"""
    factory = binding.OfficialPrediction
    profile_payload = payload["user_profile"]
    profile_cls = _profile_class(factory)
    if profile_cls is not None:
        try:
            profile: Any = profile_cls(**profile_payload)
        except TypeError:
            profile = profile_payload
    else:
        profile = profile_payload

    kwargs = {
        "response_text": payload["response_text"],
        "emotion_label": payload["emotion_label"],
        "user_profile": profile,
        "memory_refs": payload["memory_refs"],
    }
    try:
        return factory(**kwargs)
    except TypeError:
        # 对方的类型不支持画像字段时，退化到最小字段集，避免整体失败。
        return factory(response_text=payload["response_text"], emotion_label=payload["emotion_label"])


def prediction_as_dict(prediction: Any) -> dict[str, Any]:
    """把任意实现的 OfficialPrediction 转成官方四字段 dict。"""
    if isinstance(prediction, dict):
        raw = prediction
    elif hasattr(prediction, "as_dict"):
        raw = prediction.as_dict()
    elif hasattr(prediction, "model_dump"):
        raw = prediction.model_dump()
    elif hasattr(prediction, "dict"):
        raw = prediction.dict()
    else:
        raw = {
            "response_text": getattr(prediction, "response_text", ""),
            "emotion_label": getattr(prediction, "emotion_label", ""),
            "user_profile": getattr(prediction, "user_profile", {}),
            "memory_refs": getattr(prediction, "memory_refs", []),
        }

    profile = raw.get("user_profile") or {}
    if not isinstance(profile, dict) and hasattr(profile, "model_dump"):
        profile = profile.model_dump()
    if not isinstance(profile, dict) and dataclasses.is_dataclass(profile):
        profile = dataclasses.asdict(profile)

    return {
        "response_text": raw.get("response_text", ""),
        "emotion_label": raw.get("emotion_label", ""),
        "user_profile": {
            "personality_traits": list((profile or {}).get("personality_traits", []) or []),
            "interests": list((profile or {}).get("interests", []) or []),
            "style": list((profile or {}).get("style", []) or []),
        },
        "memory_refs": list(raw.get("memory_refs", []) or []),
    }