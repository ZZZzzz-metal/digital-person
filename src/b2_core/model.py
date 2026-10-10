"""A 分工的模型入口：``MockEngine`` 与真实 ``ModelEngine``。

对外合同（B 只依赖这两条）：

.. code-block:: python

    engine = ModelEngine("weights/inference_config.json")
    reply = engine.generate(CoreRequest(...))            # -> CoreReply
    pred  = engine.generate_official(OfficialRequest(...))  # -> OfficialPrediction

三条硬约束：

1. ``MockEngine.is_mock is True``，``ModelEngine.is_mock is False``；
   真实推理失败抛出 ``ModelUnavailableError`` / ``GenerationError``，
   **不会**悄悄退回 mock，也不会用固定文案冒充真实结果。
2. 模型只从**完整本地文件**加载（``local_files_only=True``，运行时不下载）；
   不读演示数据库、不写数据库、不保存记忆。
3. 情绪与画像是 A 的**规则**估计；回复文本始终来自模型。报告里必须这样写，
   不能把规则输出宣传成训练出来的识别能力。

共享类型优先使用 B 的 ``b2_core.contracts``，B 的合同尚未落地时退到
``b2_core.a_impl.dtos`` 的同字段兜底类型（见该模块说明）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

try:  # 作为包导入（B 的用法）
    from .a_impl import dtos, emotion_rules, official_spec
    from .a_impl.dtos import RequestError
    from .a_impl.local_llm import (
        ContextTooLongError,
        GenerationError,
        LocalCausalLM,
        ModelLoadError,
    )
    from .prompts import empathy
except ImportError:  # 直接以脚本或把 src/ 加入 sys.path 时
    from b2_core.a_impl import dtos, emotion_rules, official_spec  # type: ignore
    from b2_core.a_impl.dtos import RequestError  # type: ignore
    from b2_core.a_impl.local_llm import (  # type: ignore
        ContextTooLongError,
        GenerationError,
        LocalCausalLM,
        ModelLoadError,
    )
    from b2_core.prompts import empathy  # type: ignore

__all__ = [
    "ModelEngine",
    "MockEngine",
    "ModelUnavailableError",
    "GenerationError",
    "InvalidRequestError",
    "create_engine",
    "MOCK_MODEL_VERSION",
]

MOCK_MODEL_VERSION = "mock-v1"

#: 模型不可用（目录缺失/文件不齐/加载失败）。B 的 API 应映射成 503。
ModelUnavailableError = ModelLoadError
#: 参数不符合合同。B 的 API 应映射成 400。
InvalidRequestError = RequestError


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
DEFAULT_GENERATION: dict[str, Any] = {
    "max_new_tokens": 256,
    "do_sample": True,
    "temperature": 0.3,
    "top_p": 0.9,
    "repetition_penalty": 1.05,
}

#: 官方参考入口的默认生成参数（``participant/configs/inference_config.json``）。
DEFAULT_OFFICIAL_GENERATION: dict[str, Any] = {
    "max_new_tokens": 1200,
    "do_sample": False,
    "temperature": 1.0,
    "top_p": 1.0,
    "repetition_penalty": 1.0,
}

DEFAULT_RETRY_GENERATION: dict[str, Any] = {
    "max_new_tokens": 256,
    "do_sample": False,
    "temperature": 1.0,
    "top_p": 1.0,
    "repetition_penalty": 1.0,
}

DEFAULT_FALLBACK: dict[str, Any] = {
    "max_new_tokens": 160,
    "do_sample": False,
    "temperature": 1.0,
    "top_p": 1.0,
    "repetition_penalty": 1.05,
}

#: 官方输出不合法时，重试时追加的强化说明。
_OFFICIAL_RETRY_SUFFIX = (
    "\n\n再次强调：你的整条回复必须是一个合法的 JSON object，"
    "第一个字符就是 {，最后一个字符就是 }，不要有任何解释、前言或 Markdown 代码块。"
)


def load_inference_config(config_path: str | Path) -> dict[str, Any]:
    """读取推理配置；相对路径一律相对**配置文件所在目录**解析。

    这样 B 把 ``weights/`` 整个目录搬进镜像后，只要保持目录结构，
    配置里的相对路径就继续有效，不依赖开发机的绝对路径。
    """
    path = Path(config_path)
    if not path.is_file():
        raise ModelUnavailableError(f"推理配置不存在: {path}")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelUnavailableError(f"推理配置不是合法 JSON: {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise ModelUnavailableError(f"推理配置必须是 JSON object: {path}")

    base_dir = path.resolve().parent
    config["_config_path"] = str(path.resolve())
    config["_base_dir"] = str(base_dir)

    model_dir = config.get("model_dir") or config.get("model_path")
    if not model_dir:
        raise ModelUnavailableError("推理配置缺少 model_dir")
    model_dir_path = Path(str(model_dir))
    config["model_dir"] = str(
        model_dir_path if model_dir_path.is_absolute() else (base_dir / model_dir_path)
    )

    for key in ("adapter_dir", "patch_file", "license_file"):
        value = config.get(key)
        if value:
            candidate = Path(str(value))
            config[key] = str(
                candidate if candidate.is_absolute() else (base_dir / candidate)
            )
    return config


def _merge_generation(base: dict[str, Any], override: Any) -> dict[str, Any]:
    merged = dict(base)
    if isinstance(override, dict):
        merged.update(override)
    return merged


# --------------------------------------------------------------------------- #
# MockEngine
# --------------------------------------------------------------------------- #
class MockEngine:
    """A0 的 mock 引擎：不联网、不加载模型、不读写数据库。

    只验证程序链路：输入输出格式、字段合法性、``is_mock`` 标记。
    回复内容由固定模板生成，**不能**用来评价模型效果。
    """

    is_mock = True

    def __init__(self, config_path: str | None = None, *, model_version: str = MOCK_MODEL_VERSION) -> None:
        self.config_path = str(config_path) if config_path else None
        self.model_version = model_version
        self._binding = dtos.resolve_contracts()

    # ------------------------------------------------------------------ #
    def generate(self, request: Any) -> Any:
        normalized = dtos.normalize_core_request(request)
        latest = normalized.messages[-1].content
        emotion = emotion_rules.estimate_demo_emotion(latest)
        reply = self._template_reply(latest, emotion)
        return dtos.build_reply(
            self._binding,
            reply=reply,
            emotion=emotion,
            expression=emotion_rules.map_expression(emotion),
            model_version=self.model_version,
            is_mock=True,
        )

    def generate_official(self, request: Any) -> Any:
        prediction, _trace = self.official_trace(request)
        return prediction

    def official_trace(self, request: Any) -> tuple[Any, dict[str, Any]]:
        normalized = dtos.normalize_official_request(request)
        latest = normalized.history[-1].content
        payload = {
            "response_text": self._template_reply(latest, emotion_rules.estimate_demo_emotion(latest)),
            "emotion_label": emotion_rules.estimate_official_emotion(latest),
            "user_profile": emotion_rules.infer_profile(normalized.history),
            "memory_refs": list(official_spec.PUBLIC_TEST_MEMORY_REFS),
        }
        prediction = dtos.build_prediction(self._binding, payload)
        trace = {
            "mode": "mock",
            "is_mock": True,
            "model_version": self.model_version,
            "parse_failed": False,
            "emotion_source": "rules",
            "profile_source": "rules",
            "response_source": "template",
            "memory_refs_policy": "public_test_empty",
            "elapsed_ms": 0.0,
            "prompt_tokens": 0,
            "new_tokens": 0,
            "dropped_turns": 0,
            "contract_source": self._binding.source,
        }
        return prediction, trace

    # ------------------------------------------------------------------ #
    @staticmethod
    def _template_reply(text: str, emotion: str) -> str:
        """刻意**不复述**用户原话：mock 只验证链路，不该假装理解内容。"""
        openings = {
            "anxious": "听起来这件事让你一直悬着心。",
            "sad": "这件事确实让人不好受。",
            "angry": "换谁遇上都会觉得憋屈。",
            "happy": "听得出来你心情不错。",
            "neutral": "我在听，你继续说。",
            "unknown": "我在听，你继续说。",
        }
        followups = {
            "anxious": "你愿意说说最让你悬心的那部分吗？",
            "sad": "想的话可以多讲一点，我在这儿听。",
            "angry": "当时具体发生什么了？",
            "happy": "想多讲讲是什么让你这么高兴吗？",
            "neutral": "你想从哪件事说起？",
            "unknown": "你想从哪件事说起？",
        }
        key = emotion if emotion in openings else "unknown"
        return openings[key] + followups[key]

    # ------------------------------------------------------------------ #
    def describe(self) -> dict[str, Any]:
        return {
            "engine": "MockEngine",
            "is_mock": True,
            "model_version": self.model_version,
            "contract_source": self._binding.source,
            "config_path": self.config_path,
            "note": "mock 只验证程序链路，不能用于评价模型效果。",
        }


# --------------------------------------------------------------------------- #
# ModelEngine
# --------------------------------------------------------------------------- #
class ModelEngine:
    """真实本地推理引擎。

    - 进程启动时加载一次，``generate`` 被连续调用不会重新加载；
    - 每次调用都只使用传入的 ``messages`` / ``history``，不保留任何跨样本状态；
    - 模型文件缺失或生成失败时抛出可识别错误，绝不返回假回复。
    """

    is_mock = False

    def __init__(self, config_path: str | Path, *, auto_load: bool = True) -> None:
        self.config = load_inference_config(config_path)
        self.config_path = self.config["_config_path"]
        self.model_version = str(self.config.get("model_version") or "unversioned")
        self._binding = dtos.resolve_contracts()

        self.generation = _merge_generation(DEFAULT_GENERATION, self.config.get("generation"))
        self.official_generation = _merge_generation(
            DEFAULT_OFFICIAL_GENERATION, self.config.get("official_generation")
        )
        self.retry_generation = _merge_generation(
            DEFAULT_RETRY_GENERATION, self.config.get("retry_generation")
        )
        self.fallback_generation = _merge_generation(
            DEFAULT_FALLBACK, self.config.get("fallback_generation")
        )
        self.official_system_prompt = official_spec.build_system_prompt()
        self.patch_file = self.config.get("patch_file")
        self.patch_report: dict[str, Any] | None = None

        self._llm = LocalCausalLM(
            self.config["model_dir"],
            device=str(self.config.get("device", "auto")),
            dtype=self.config.get("dtype", "float32"),
            max_input_tokens=int(self.config.get("max_input_tokens", 3072)),
            torch_threads=self.config.get("torch_threads"),
            trust_remote_code=bool(self.config.get("trust_remote_code", False)),
        )
        self.load_report = None
        if auto_load:
            self.load()

    # ------------------------------------------------------------------ #
    def load(self) -> Any:
        """加载模型（幂等）。"""
        report = self._llm.load()
        if self.patch_file:
            self.patch_report = self._apply_patch(self.patch_file)
        self.load_report = report
        return report

    def _apply_patch(self, patch_file: str) -> dict[str, Any]:
        """把训练产出的张量补丁叠加到已加载模型上（可选，无第三方依赖）。"""
        import torch
        from safetensors.torch import load_file

        path = Path(patch_file)
        if not path.is_file():
            raise ModelUnavailableError(f"权重补丁不存在: {path}")
        tensors = load_file(str(path))
        state = self._llm.model.state_dict()
        applied, missing, mismatched = 0, [], []
        for name, tensor in tensors.items():
            if name not in state:
                missing.append(name)
                continue
            if tuple(state[name].shape) != tuple(tensor.shape):
                mismatched.append(name)
                continue
            state[name] = tensor.to(state[name].dtype)
            applied += 1
        self._llm.model.load_state_dict(state, strict=True)
        self._llm.model.eval()
        report = {
            "patch_file": str(path),
            "tensors_in_patch": len(tensors),
            "applied": applied,
            "unknown_names": missing,
            "shape_mismatch": mismatched,
        }
        if missing or mismatched:
            raise ModelUnavailableError(f"权重补丁与模型不匹配: {report}")
        return report

    # ------------------------------------------------------------------ #
    @property
    def loaded(self) -> bool:
        return self._llm.loaded

    def describe(self) -> dict[str, Any]:
        report = self.load_report
        return {
            "engine": "ModelEngine",
            "is_mock": False,
            "model_version": self.model_version,
            "config_path": self.config_path,
            "model_dir": self.config["model_dir"],
            "contract_source": self._binding.source,
            "loaded": self.loaded,
            "load_seconds": round(report.load_seconds, 3) if report else None,
            "params": report.params if report else None,
            "param_dtypes": report.dtypes if report else None,
            "device": report.device if report else None,
            "threads": report.threads if report else None,
            "max_input_tokens": self._llm.max_input_tokens,
            "generation": self.generation,
            "official_generation": self.official_generation,
            "patch": self.patch_report,
        }

    # ------------------------------------------------------------------ #
    # 演示合同：CoreRequest -> CoreReply
    # ------------------------------------------------------------------ #
    def generate(self, request: Any) -> Any:
        normalized = dtos.normalize_core_request(request)
        summary = self.generate_with_trace(request)
        return summary["reply"]

    def generate_with_trace(self, request: Any) -> dict[str, Any]:
        """``generate`` 的带元数据版本，供评测/日志使用；不改变对外合同。"""
        if not self.loaded:
            self.load()
        normalized = dtos.normalize_core_request(request)

        messages = empathy.build_chat_messages(
            normalized.messages,
            persona=normalized.persona,
            memory_context=normalized.memory_context,
        )
        temperature = float(normalized.temperature)
        result = self._llm.generate(
            messages,
            max_new_tokens=int(normalized.max_new_tokens),
            do_sample=temperature > 0,
            temperature=temperature if temperature > 0 else 1.0,
            top_p=float(self.generation.get("top_p", 0.9)),
            repetition_penalty=self.generation.get("repetition_penalty"),
        )

        reply_text = empathy.strip_model_noise(result.text)
        if not reply_text:
            raise GenerationError(
                "真实模型返回了空回复；不填入固定文案，交由调用方按模型不可用处理。"
            )
        latest_user = normalized.messages[-1].content
        emotion = emotion_rules.estimate_demo_emotion(latest_user)
        reply = dtos.build_reply(
            self._binding,
            reply=reply_text,
            emotion=emotion,
            expression=emotion_rules.map_expression(emotion),
            model_version=self.model_version,
            is_mock=False,
        )
        return {
            "reply": reply,
            "latest_user": latest_user,
            "emotion": emotion,
            "emotion_source": "rules",
            "elapsed_ms": result.elapsed_ms,
            "prompt_tokens": result.prompt_tokens,
            "new_tokens": result.new_tokens,
            "dropped_turns": result.dropped_turns,
            "dropped_messages": result.dropped_messages,
            "device": result.device,
            "system_prompt_chars": len(messages[0]["content"]),
        }

    # ------------------------------------------------------------------ #
    # 官方合同：OfficialRequest -> OfficialPrediction
    # ------------------------------------------------------------------ #
    def generate_official(self, request: Any) -> Any:
        prediction, _trace = self.official_trace(request)
        return prediction

    def official_trace(self, request: Any) -> tuple[Any, dict[str, Any]]:
        """官方生成的带元数据版本。

        流程（每一步都记进 trace，便于如实汇报）：

        1. 用官方 prompt 生成一次，按官方 ``parse_prediction`` 解析；
        2. 解析失败或回复为空时，用强化「只输出 JSON」的 prompt 重试一次；
        3. 仍然不可用时进入 **fallback**：用共情 prompt 让模型真正生成一段回复文本，
           情绪与画像改用 A 的规则估计。``response_text`` 始终来自模型，
           不会用固定文案取代；情绪/画像的来源会在 trace 里标明。

        ``memory_refs`` 一律为 ``[]``：公开测试没有 memory bank，
        训练标注里的 ``mem_XXXXXX`` 没有对应内容，不能凭空编造引用。
        """
        if not self.loaded:
            self.load()
        normalized = dtos.normalize_official_request(request)
        latest_user = normalized.history[-1].content
        started = time.perf_counter()

        messages = empathy.build_official_messages(
            normalized.sample_id,
            normalized.history,
            system_prompt=self.official_system_prompt,
        )
        first = self._llm.generate(
            messages,
            max_new_tokens=int(self.official_generation.get("max_new_tokens", 1200)),
            do_sample=bool(self.official_generation.get("do_sample", False)),
            temperature=float(self.official_generation.get("temperature", 1.0)),
            top_p=float(self.official_generation.get("top_p", 1.0)),
            repetition_penalty=self.official_generation.get("repetition_penalty"),
        )
        payload, parse_failed = official_spec.parse_prediction(first.text)
        mode = "json"
        parse_failures = 1 if parse_failed else 0
        prompt_tokens = first.prompt_tokens
        new_tokens = first.new_tokens
        dropped_turns = first.dropped_turns

        if parse_failed or not payload["response_text"].strip():
            retry_messages = [
                messages[0] | {"content": messages[0]["content"] + _OFFICIAL_RETRY_SUFFIX},
                messages[1],
            ]
            retry = self._llm.generate(
                retry_messages,
                max_new_tokens=int(self.retry_generation.get("max_new_tokens", 256)),
                do_sample=False,
                temperature=1.0,
                top_p=1.0,
                repetition_penalty=self.retry_generation.get("repetition_penalty"),
            )
            retry_payload, retry_failed = official_spec.parse_prediction(retry.text)
            prompt_tokens += retry.prompt_tokens
            new_tokens += retry.new_tokens
            dropped_turns += retry.dropped_turns
            if retry_failed:
                parse_failures += 1
            if not retry_failed and retry_payload["response_text"].strip():
                payload = retry_payload
                parse_failed = False
                mode = "json_retry"
            else:
                mode = "fallback_rules"

        emotion_source = "model"
        profile_source = "model"
        if mode == "fallback_rules":
            plain = self._plain_reply(normalized)
            prompt_tokens += plain.prompt_tokens
            new_tokens += plain.new_tokens
            dropped_turns += plain.dropped_turns
            text = empathy.strip_model_noise(plain.text)
            if not text:
                raise GenerationError(
                    f"样本 {normalized.sample_id}: 官方解析失败且兜底生成也为空，"
                    "不输出任何伪造结果。"
                )
            payload["response_text"] = text
            payload["emotion_label"] = emotion_rules.estimate_official_emotion(latest_user)
            payload["user_profile"] = emotion_rules.infer_profile(normalized.history)
            emotion_source = "rules"
            profile_source = "rules"

        # 官方 schema 要求成功回复非空、情绪非空；缺了就在这里如实降级并记录，
        # 不编造标签，也不把失败占位当成第 17 类情绪。
        if not payload["response_text"].strip():
            raise GenerationError(
                f"样本 {normalized.sample_id}: 未能得到非空 response_text；不生成假预测。"
            )
        if payload["emotion_label"] not in official_spec.EMOTION_SET:
            payload["emotion_label"] = emotion_rules.estimate_official_emotion(latest_user)
            emotion_source = "rules"
        payload["memory_refs"] = list(official_spec.PUBLIC_TEST_MEMORY_REFS)

        prediction = dtos.build_prediction(self._binding, payload)
        as_dict = dtos.prediction_as_dict(prediction)
        schema_ok, problems = official_spec.is_schema_valid(as_dict)

        trace = {
            "sample_id": normalized.sample_id,
            "mode": mode,
            "is_mock": False,
            "model_version": self.model_version,
            "parse_failed": parse_failed,
            "parse_failures": parse_failures,
            "emotion_source": emotion_source,
            "profile_source": profile_source,
            "response_source": "model",
            "memory_refs_policy": "public_test_empty",
            "schema_valid": schema_ok,
            "schema_problems": problems,
            "raw_head": empathy.strip_model_noise(first.text)[:200],
            "elapsed_ms": (time.perf_counter() - started) * 1000.0,
            "prompt_tokens": prompt_tokens,
            "new_tokens": new_tokens,
            "dropped_turns": dropped_turns,
            "contract_source": self._binding.source,
        }
        return prediction, trace

    def _plain_reply(self, normalized: dtos.NormalizedOfficialRequest) -> Any:
        """兜底路径：用共情 prompt 让模型生成真正的回复文本。"""
        messages = empathy.build_chat_messages(
            normalized.history,
            persona=None,
            memory_context=normalized.memory_context,
        )
        return self._llm.generate(
            messages,
            max_new_tokens=int(self.fallback_generation.get("max_new_tokens", 160)),
            do_sample=False,
            temperature=1.0,
            top_p=1.0,
            repetition_penalty=self.fallback_generation.get("repetition_penalty"),
        )


# --------------------------------------------------------------------------- #
def create_engine(config_path: str | Path | None = None, *, mode: str = "real") -> Any:
    """按模式构造引擎。``mode`` 只接受 ``"real"`` 与 ``"mock"``。

    真实模式不会因为配置或权重问题自动退回 mock；反之亦然。
    """
    if mode == "mock":
        return MockEngine(config_path)
    if mode == "real":
        if config_path is None:
            raise InvalidRequestError("真实模式必须提供推理配置路径")
        return ModelEngine(config_path)
    raise InvalidRequestError(f"未知引擎模式: {mode!r}（只支持 real / mock）")