"""A 分工的提示词模块：人设、共情与输出约束。"""

from .empathy import (
    DEFAULT_PERSONA,
    build_chat_messages,
    build_system_prompt,
    strip_model_noise,
)

__all__ = [
    "DEFAULT_PERSONA",
    "build_chat_messages",
    "build_system_prompt",
    "strip_model_noise",
]