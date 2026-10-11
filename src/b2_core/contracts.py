"""Shared demo DTOs and separate official generation DTOs; no model loading."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    field_validator,
    model_validator,
)

Emotion = Literal["neutral", "happy", "sad", "anxious", "angry", "unknown"]
Expression = Literal["neutral", "smile", "concern", "listening"]
MemoryKey = Literal["preferred_name", "study_goal", "exam_subject", "response_preference", "hobby"]
OfficialEmotion = Literal[
    "joy", "gratitude", "relaxed", "care", "pride", "neutral", "surprise", "mixed",
    "sadness", "loneliness", "anxiety", "anger", "fear", "disgust", "shame", "helplessness",
]
OfficialPersonality = Literal[
    "extroverted", "introverted", "open", "conservative", "high_conscientiousness",
    "casual", "agreeable", "assertive", "emotionally_stable", "sensitive",
]
OfficialInterest = Literal[
    "study_exam", "programming_technology", "reading_writing", "film_animation", "music",
    "games", "sports_fitness", "travel_outdoor", "pets", "social", "career_development", "art_design",
]
OfficialStyle = Literal[
    "brief", "detailed", "colloquial", "formal", "direct", "indirect", "humorous",
    "rational", "high_emotional_expression", "low_emotional_expression", "emoji_user",
]

NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"\S")]


def _trim_memory_value(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _valid_utc_timestamp(value: str) -> str:
    datetime.fromisoformat(value[:-1] + "+00:00")
    return value


MemoryValue = Annotated[
    str,
    BeforeValidator(_trim_memory_value),
    StringConstraints(min_length=1, max_length=200, pattern=r"\S"),
]
UtcTimestamp = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$"),
    AfterValidator(_valid_utc_timestamp),
    Field(json_schema_extra={"format": "date-time"}),
]
MemoryReference = Annotated[str, StringConstraints(pattern=r"^mem_[0-9]{6}$")]


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Message(DTO):
    role: Literal["user", "assistant"]
    content: NonBlank


class MemoryItem(DTO):
    id: Identifier
    key: MemoryKey
    value: MemoryValue
    updated_at: UtcTimestamp


class MemoryContext(DTO):
    prompt_text: str = ""
    retrieved_memories: list[MemoryItem] = Field(default_factory=list)


class CoreRequest(DTO):
    messages: list[Message] = Field(min_length=1)
    memory_context: str = ""
    persona: NonBlank = "伴学：中文日常陪伴助手"
    max_new_tokens: int = Field(default=256, ge=1, le=4096)
    temperature: float = Field(default=0.3, ge=0, le=2)

    @model_validator(mode="after")
    def current_user_is_last(self) -> CoreRequest:
        if self.messages[-1].role != "user":
            raise ValueError("messages must end with the current user input, included once")
        return self


class CoreReply(DTO):
    reply: NonBlank
    emotion: Emotion = "unknown"
    expression: Expression = "listening"
    model_version: NonBlank
    is_mock: bool = False


class ChatRequest(DTO):
    session_id: Identifier
    client_turn_id: Identifier
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000, pattern=r"\S")]


class ChatResponse(DTO):
    session_id: Identifier
    client_turn_id: Identifier
    reply: NonBlank
    emotion: Emotion
    expression: Expression
    retrieved_memories: list[MemoryItem]
    model_version: NonBlank
    elapsed_ms: int = Field(ge=0)
    is_mock: bool


class SessionDTO(DTO):
    id: Identifier
    title: Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=r"\S")]
    created_at: UtcTimestamp


class SessionCreate(DTO):
    title: Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=r"\S")] = "新会话"


class SessionList(RootModel[list[SessionDTO]]):
    model_config = ConfigDict(strict=True)


class MessageList(RootModel[list[Message]]):
    model_config = ConfigDict(strict=True)


class MemorySave(DTO):
    value: MemoryValue


class MemorySettings(DTO):
    enabled: bool


class MemoryList(DTO):
    enabled: bool
    items: list[MemoryItem]


class Health(DTO):
    status: Literal["ok", "degraded"]
    model_ready: bool
    is_mock: bool
    model_version: NonBlank


class ErrorDetail(DTO):
    code: NonBlank
    message: NonBlank


class ErrorResponse(DTO):
    error: ErrorDetail


class OkResponse(DTO):
    ok: Literal[True] = True


class Engine(Protocol):
    """Demo engine metadata must be checked by the application at startup."""

    is_mock: bool
    model_version: str

    def generate(self, request: CoreRequest) -> CoreReply: ...


class OfficialProfile(DTO):
    personality_traits: list[OfficialPersonality] = Field(json_schema_extra={"uniqueItems": True})
    interests: list[OfficialInterest] = Field(json_schema_extra={"uniqueItems": True})
    style: list[OfficialStyle] = Field(json_schema_extra={"uniqueItems": True})

    @field_validator("personality_traits", "interests", "style")
    @classmethod
    def items_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("official profile arrays must contain unique values")
        return values


class OfficialRequest(DTO):
    """Model input carries the unchanged source ID; generation never creates ID."""

    sample_id: NonBlank
    history: list[Message] = Field(min_length=1)
    memory_context: str = ""

    @model_validator(mode="after")
    def target_user_is_last(self) -> OfficialRequest:
        if self.history[-1].role != "user":
            raise ValueError("official history must end with the target user")
        return self


class OfficialPrediction(DTO):
    """Successful generation only. B preserves input ID outside this DTO."""

    response_text: NonBlank
    emotion_label: OfficialEmotion
    user_profile: OfficialProfile
    memory_refs: list[MemoryReference] = Field(json_schema_extra={"uniqueItems": True})

    @field_validator("memory_refs")
    @classmethod
    def references_are_unique_and_complete(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(re.fullmatch(r"mem_[0-9]{6}", value) is None for value in values):
            raise ValueError("memory refs must be unique mem_ followed by six ASCII digits")
        return values


class OfficialEngine(Protocol):
    """Independent official generator; metadata does not enter predictions."""

    is_mock: bool
    model_version: str

    def generate_official(self, request: OfficialRequest) -> OfficialPrediction: ...
