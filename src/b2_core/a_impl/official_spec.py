"""官方生成合同的本地实现：枚举、提示词、解析与归一化。

这一模块对 ``contracts/official/`` 的快照负责，不引入任何自己的规则：

- 16 类情绪与三组画像枚举来自 ``contracts/official/submission.schema.json``；
- system prompt 与 ``submission/official-reference/participant/run_inference.py``
  的 ``SYSTEM_PROMPT`` 保持一致（含「测试集没有公开 memory bank，``memory_refs`` 固定 ``[]``」）；
- ``render_conversation`` 与官方 ``conversation_text`` 输出同样的文本；
- ``normalize`` 与官方一样：非法情绪/画像/引用降级为空，不猜测、不补造。

官方输出 schema 的五个字段里 ``id`` 由 B 原样回填，A 只生成
``response_text`` / ``emotion_label`` / ``user_profile`` / ``memory_refs``。
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

# --------------------------------------------------------------------------- #
# 枚举（官方 schema 原样）
# --------------------------------------------------------------------------- #
EMOTIONS: tuple[str, ...] = (
    "joy",
    "gratitude",
    "relaxed",
    "care",
    "pride",
    "neutral",
    "surprise",
    "mixed",
    "sadness",
    "loneliness",
    "anxiety",
    "anger",
    "fear",
    "disgust",
    "shame",
    "helplessness",
)
EMOTION_SET = frozenset(EMOTIONS)

PROFILE_LABELS: dict[str, tuple[str, ...]] = {
    "personality_traits": (
        "extroverted",
        "introverted",
        "open",
        "conservative",
        "high_conscientiousness",
        "casual",
        "agreeable",
        "assertive",
        "emotionally_stable",
        "sensitive",
    ),
    "interests": (
        "study_exam",
        "programming_technology",
        "reading_writing",
        "film_animation",
        "music",
        "games",
        "sports_fitness",
        "travel_outdoor",
        "pets",
        "social",
        "career_development",
        "art_design",
    ),
    "style": (
        "brief",
        "detailed",
        "colloquial",
        "formal",
        "direct",
        "indirect",
        "humorous",
        "rational",
        "high_emotional_expression",
        "low_emotional_expression",
        "emoji_user",
    ),
}
PROFILE_GROUP_NAMES: tuple[str, ...] = ("personality_traits", "interests", "style")
PROFILE_SETS = {name: frozenset(values) for name, values in PROFILE_LABELS.items()}

MEMORY_RE = re.compile(r"^mem_[0-9]{6}$")

# 公开测试协议：没有公开 memory bank，固定输出空引用。
PUBLIC_TEST_MEMORY_REFS: list[str] = []

SYSTEM_PROMPT_TEMPLATE = """你正在参加数字情感陪伴比赛。根据截止到最新用户消息的对话历史，完成下一轮 Assistant 回复预测。

只输出一个 JSON object，不要输出 Markdown 或解释。object 必须且只能包含：
- response_text: 非空中文回复，应自然、贴合上下文和用户偏好；
- emotion_label: 最新用户消息的情绪，只能从 {emotions} 中选择；
- user_profile: object，包含 personality_traits、interests、style 三个字符串数组；
- memory_refs: 固定输出 []，因为测试集没有公开 memory bank。

画像标签只能使用以下枚举；没有充分证据时宁可输出空数组：
personality_traits: {personality}
interests: {interests}
style: {styles}
"""


def build_system_prompt() -> str:
    """构造官方 system prompt（枚举顺序与官方脚本一致）。"""
    return SYSTEM_PROMPT_TEMPLATE.format(
        emotions=", ".join(EMOTIONS),
        personality=", ".join(sorted(PROFILE_LABELS["personality_traits"])),
        interests=", ".join(sorted(PROFILE_LABELS["interests"])),
        styles=", ".join(sorted(PROFILE_LABELS["style"])),
    )


def render_conversation(sample_id: str, history: Iterable[Any]) -> str:
    """与官方 ``conversation_text`` 等价：把完整历史渲染成一条 user 消息。

    ``history`` 已包含目标 user 轮，这里**不追加**当前问题，也不读取任何标签/答案。
    """
    rendered: list[str] = []
    for turn in history:
        role = turn.get("role") if isinstance(turn, dict) else getattr(turn, "role", None)
        content = turn.get("content") if isinstance(turn, dict) else getattr(turn, "content", None)
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise ValueError(f"样本 {sample_id} 的 history 格式无效")
        rendered.append(f"{role}: {content}")
    return "样本 ID: " + sample_id + "\n对话历史:\n" + "\n".join(rendered)


# --------------------------------------------------------------------------- #
# 解析（与官方 extract_object / recover_response_text 等价）
# --------------------------------------------------------------------------- #
THINK_BLOCK = r"<think>.*?</think>"


def extract_object(text: str) -> dict[str, Any]:
    text = re.sub(THINK_BLOCK, "", text, flags=re.S).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    candidate = fenced.group(1) if fenced else text
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", candidate):
        try:
            value, _ = decoder.raw_decode(candidate[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("模型输出中没有可解析的 JSON object")


def recover_response_text(text: str) -> str:
    cleaned = re.sub(THINK_BLOCK, "", text, flags=re.S).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I).strip()
    match = re.search(r'"response_text"\s*:\s*"((?:\\.|[^"\\])*)', cleaned, flags=re.S)
    if match:
        try:
            recovered = json.loads(f'"{match.group(1)}"')
            if isinstance(recovered, str):
                return recovered.strip()
        except json.JSONDecodeError:
            pass
    return cleaned


def clean_profile(raw: Any) -> dict[str, list[str]]:
    profile = raw if isinstance(raw, dict) else {}
    clean: dict[str, list[str]] = {}
    for name in PROFILE_GROUP_NAMES:
        values = profile.get(name)
        allowed = PROFILE_SETS[name]
        valid = (
            isinstance(values, list)
            and all(isinstance(value, str) for value in values)
            and len(values) == len(set(values))
            and set(values) <= allowed
        )
        clean[name] = list(values) if valid else []
    return clean


def clean_memory_refs(raw: Any) -> list[str]:
    valid = (
        isinstance(raw, list)
        and all(isinstance(value, str) and MEMORY_RE.fullmatch(value) for value in raw)
        and len(raw) == len(set(raw))
    )
    return list(raw) if valid else []


def normalize_prediction(raw: dict[str, Any]) -> dict[str, Any]:
    """按官方 normalize 的语义清洗一个已解析的 object（不含 id）。"""
    response = raw.get("response_text")
    emotion = raw.get("emotion_label")
    return {
        "response_text": response.strip() if isinstance(response, str) else "",
        "emotion_label": emotion if isinstance(emotion, str) and emotion in EMOTION_SET else "",
        "user_profile": clean_profile(raw.get("user_profile")),
        "memory_refs": clean_memory_refs(raw.get("memory_refs")),
    }


def parse_prediction(decoded: str) -> tuple[dict[str, Any], bool]:
    """解析模型文本，返回 (清洗后的四字段 dict, 是否 JSON 解析失败)。"""
    try:
        raw = extract_object(decoded)
        parse_failed = False
    except ValueError:
        raw = {
            "response_text": recover_response_text(decoded),
            "emotion_label": "",
            "user_profile": {},
            "memory_refs": [],
        }
        parse_failed = True
    return normalize_prediction(raw), parse_failed


def is_schema_valid(prediction: dict[str, Any]) -> tuple[bool, list[str]]:
    """按团队派生的 ``model_prediction.schema.json`` 检查成功生成结果。"""
    problems: list[str] = []
    if not isinstance(prediction.get("response_text"), str) or not prediction["response_text"].strip():
        problems.append("response_text 必须是非空字符串")
    if prediction.get("emotion_label") not in EMOTION_SET:
        problems.append(f"emotion_label 非法: {prediction.get('emotion_label')!r}")
    profile = prediction.get("user_profile")
    if not isinstance(profile, dict):
        problems.append("user_profile 必须是 object")
    else:
        extra = set(profile) - set(PROFILE_GROUP_NAMES)
        if extra:
            problems.append(f"user_profile 有额外字段: {sorted(extra)}")
        for name in PROFILE_GROUP_NAMES:
            values = profile.get(name)
            if not isinstance(values, list):
                problems.append(f"user_profile.{name} 必须是数组")
                continue
            if len(values) != len(set(values)):
                problems.append(f"user_profile.{name} 有重复值")
            illegal = [v for v in values if v not in PROFILE_SETS[name]]
            if illegal:
                problems.append(f"user_profile.{name} 有非法枚举: {illegal}")
    refs = prediction.get("memory_refs")
    if not isinstance(refs, list):
        problems.append("memory_refs 必须是数组")
    else:
        illegal_refs = [r for r in refs if not (isinstance(r, str) and MEMORY_RE.fullmatch(r))]
        if illegal_refs:
            problems.append(f"memory_refs 格式非法: {illegal_refs}")
        if len(refs) != len(set(refs)):
            problems.append("memory_refs 有重复值")
    return (not problems), problems