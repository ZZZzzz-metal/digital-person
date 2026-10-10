"""Pure demo turn helpers. No storage, HTTP, model loading or network access."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from .contracts import CoreReply, CoreRequest, Engine, Message


_EMOTIONS = frozenset(("neutral", "happy", "sad", "anxious", "angry", "unknown"))
_EXPRESSIONS = frozenset(("neutral", "smile", "concern", "listening"))


def _payload(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="python")
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise ValueError("turn input/output must be a DTO, dataclass or dictionary")


def build_core_request(user_text: str, history: list[Message], memory_context: str = "") -> CoreRequest:
    """Keep completed pairs only, then append the current input exactly once.

    The character budget applies to history only; the current user input stays
    intact. A's tokenizer remains responsible for the model's actual context.
    """
    messages = [Message.model_validate(_payload(message)) for message in history]
    if len(messages) % 2 or any(message.role != ("user" if index % 2 == 0 else "assistant") for index, message in enumerate(messages)):
        raise ValueError("history must contain completed user/assistant pairs")
    # Validate the current text using the same 2000-character boundary as HTTP.
    from .contracts import ChatRequest

    current = ChatRequest(session_id="pure-helper", client_turn_id="pure-helper", text=user_text)
    messages = messages[-12:]
    while sum(len(message.content) for message in messages) > 4000:
        messages = messages[2:]
    messages.append(Message(role="user", content=current.text))
    return CoreRequest(messages=messages, memory_context=memory_context)


def run_turn(request: CoreRequest, engine: Engine) -> CoreReply:
    """Revalidate input, call generate once, and validate truthful output.

    Bad emotion/expression enums can be normalized; missing text or inconsistent
    metadata is a failure. Exceptions propagate to the caller without a stub.
    """
    validated = CoreRequest.model_validate(_payload(request))
    is_mock = getattr(engine, "is_mock", None)
    version = getattr(engine, "model_version", None)
    if type(is_mock) is not bool or not isinstance(version, str) or not version.strip():
        raise ValueError("engine must declare a bool is_mock and nonblank model_version")
    if not callable(getattr(engine, "generate", None)):
        raise ValueError("engine must provide generate")
    payload = _payload(engine.generate(validated))
    emotion = payload.get("emotion", "unknown")
    expression = payload.get("expression", "listening")
    payload["emotion"] = emotion if isinstance(emotion, str) and emotion in _EMOTIONS else "unknown"
    payload["expression"] = expression if isinstance(expression, str) and expression in _EXPRESSIONS else "neutral"
    reply = CoreReply.model_validate(payload)
    if "is_mock" not in payload or reply.is_mock is not is_mock or reply.model_version != version:
        raise ValueError("reply metadata must explicitly match the current engine")
    return reply
