"""本地因果语言模型的加载与生成（A 分工）。

要求（来自 ``docs/分工/A-模型训练与评测.md`` A1/A3）：
- 权重、分词器、配置全部从**完整本地文件**加载，``local_files_only=True``，运行时不下载；
- 进程内只加载一次，``generate`` 被连续调用不会重复加载；
- 当前 user 已在 messages 末尾，**不追加第二次**；
- 上下文超长时从最旧的完整轮次开始移除，**不截断当前问题**；
- 加载失败或生成失败抛出可识别错误，绝不返回假回复。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

# 断网标志必须在导入 transformers 之前设置。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


class ModelLoadError(RuntimeError):
    """模型目录缺失、文件不完整或加载失败。B 的 API 应映射成 503。"""


class GenerationError(RuntimeError):
    """模型已加载但生成失败（显存/上下文/解码异常）。"""


class ContextTooLongError(GenerationError):
    """即使移除全部历史轮次，当前问题本身仍超长。"""


@dataclass
class GenerationResult:
    text: str
    prompt_tokens: int
    new_tokens: int
    elapsed_ms: float
    dropped_turns: int
    dropped_messages: int
    device: str
    max_input_tokens: int


@dataclass
class LoadReport:
    model_dir: str
    load_seconds: float
    params: int
    dtypes: list[str]
    model_type: str
    device: str
    threads: int
    chat_template: bool
    weights_sha256: str | None = None
    missing_files: list[str] = field(default_factory=list)


# 加载一个 Qwen2 因果模型至少需要这些文件；缺任何一个都视为「权重不齐」，
# 直接报错，而不是让 transformers 退回随机初始化。
REQUIRED_WEIGHT_FILES = ("config.json",)
WEIGHT_GLOBS = ("*.safetensors", "*.bin", "*.pt")


def _check_weight_files(model_dir: Path) -> list[str]:
    missing: list[str] = []
    for name in REQUIRED_WEIGHT_FILES:
        if not (model_dir / name).is_file():
            missing.append(name)
    if not any(list(model_dir.glob(pattern)) for pattern in WEIGHT_GLOBS):
        missing.append("weights(*.safetensors|*.bin|*.pt)")
    has_tokenizer = any(
        (model_dir / name).is_file()
        for name in ("tokenizer.json", "tokenizer_config.json", "vocab.json", "spiece.model")
    )
    if not has_tokenizer:
        missing.append("tokenizer(*.json|spiece.model)")
    return missing


def resolve_dtype(name: str | None, device: str) -> Any:
    import torch

    if device == "cpu":
        # CPU 上 bfloat16 既慢又可能不准；统一用 float32。
        return torch.float32
    mapping = {
        None: "auto",
        "auto": "auto",
        "float32": torch.float32,
        "fp32": torch.float32,
        "float16": torch.float16,
        "fp16": torch.float16,
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
    }
    if name not in mapping:
        raise ModelLoadError(f"不支持的 dtype: {name!r}")
    return mapping[name]


class LocalCausalLM:
    """一次性加载、可重复调用的本地生成器。"""

    def __init__(
        self,
        model_dir: str | Path,
        *,
        device: str = "auto",
        dtype: str | None = "float32",
        max_input_tokens: int = 3072,
        torch_threads: int | None = None,
        trust_remote_code: bool = False,
    ) -> None:
        self.model_dir = Path(model_dir).resolve()
        self.requested_device = device
        self.dtype_name = dtype
        self.max_input_tokens = int(max_input_tokens)
        self.torch_threads = torch_threads
        self.trust_remote_code = bool(trust_remote_code)
        self._tokenizer: Any = None
        self._model: Any = None
        self._torch: Any = None
        self.report: LoadReport | None = None

    # ------------------------------------------------------------------ #
    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def tokenizer(self) -> Any:
        return self._tokenizer

    @property
    def model(self) -> Any:
        return self._model

    # ------------------------------------------------------------------ #
    def load(self) -> LoadReport:
        """加载模型；重复调用直接返回首次结果，不会重新读盘。"""
        if self.report is not None:
            return self.report

        if not self.model_dir.is_dir():
            raise ModelLoadError(f"本地模型目录不存在: {self.model_dir}")
        missing = _check_weight_files(self.model_dir)
        if missing:
            raise ModelLoadError(
                f"本地模型目录文件不完整: {self.model_dir} 缺少 {missing}；"
                "拒绝以随机初始化继续，也不会退回 mock。"
            )

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:  # pragma: no cover - 依赖缺失时给出可识别错误
            raise ModelLoadError(f"缺少推理依赖 torch/transformers: {exc}") from exc

        if self.torch_threads:
            torch.set_num_threads(int(self.torch_threads))

        device = self.requested_device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        torch_dtype = resolve_dtype(self.dtype_name, device)

        started = time.perf_counter()
        try:
            tokenizer = AutoTokenizer.from_pretrained(
                str(self.model_dir),
                local_files_only=True,
                trust_remote_code=self.trust_remote_code,
            )
            load_kwargs: dict[str, Any] = {
                "local_files_only": True,
                "trust_remote_code": self.trust_remote_code,
            }
            # transformers 5.x 用 dtype=，4.x 用 torch_dtype=
            major = int(__import__("transformers").__version__.split(".")[0])
            if major >= 5:
                load_kwargs["dtype"] = torch_dtype
            else:
                load_kwargs["torch_dtype"] = torch_dtype
            if device == "cuda":
                load_kwargs["device_map"] = "auto"
            model = AutoModelForCausalLM.from_pretrained(str(self.model_dir), **load_kwargs)
            if device != "cuda":
                model = model.to(device)
            model.eval()
        except Exception as exc:
            raise ModelLoadError(
                f"本地模型加载失败（目录 {self.model_dir}）: {type(exc).__name__}: {exc}"
            ) from exc

        load_seconds = time.perf_counter() - started
        dtypes = sorted({str(p.dtype) for p in model.parameters()})
        self._torch = torch
        self._tokenizer = tokenizer
        self._model = model
        self.report = LoadReport(
            model_dir=str(self.model_dir),
            load_seconds=load_seconds,
            params=sum(p.numel() for p in model.parameters()),
            dtypes=dtypes,
            model_type=model.config.model_type,
            device=device,
            threads=int(torch.get_num_threads()),
            chat_template=bool(getattr(tokenizer, "chat_template", None)),
        )
        return self.report

    # ------------------------------------------------------------------ #
    def count_tokens(self, text: str) -> int:
        if self._tokenizer is None:
            self.load()
        return len(self._tokenizer(text, add_special_tokens=False)["input_ids"])

    def _render(self, messages: Sequence[dict[str, str]]) -> str:
        return self._tokenizer.apply_chat_template(
            list(messages), tokenize=False, add_generation_prompt=True
        )

    def _trim(
        self, messages: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], int, int]:
        """按 tokenizer 预算裁剪历史。

        保留第一条 system（如果有）；其余按「最旧的完整轮次」成对移除。
        当前问题（最后一条 user）永不截断，单独超预算时抛 ContextTooLongError。
        """
        system = [messages[0]] if messages and messages[0]["role"] == "system" else []
        body = messages[len(system):]

        prompt_tokens = len(
            self._tokenizer(self._render(system + body), add_special_tokens=False)["input_ids"]
        )
        if prompt_tokens <= self.max_input_tokens:
            return messages, 0, 0

        dropped_turns = 0
        dropped_messages = 0
        while len(body) > 1:
            # 从最旧开始移除一个完整轮次：一条 user 加紧随其后的 assistant（若有）。
            take = 1
            if len(body) >= 2 and body[0]["role"] == "user" and body[1]["role"] == "assistant":
                take = 2
            body = body[take:]
            dropped_turns += 1
            dropped_messages += take
            prompt_tokens = len(
                self._tokenizer(self._render(system + body), add_special_tokens=False)["input_ids"]
            )
            if prompt_tokens <= self.max_input_tokens:
                break

        if prompt_tokens > self.max_input_tokens:
            raise ContextTooLongError(
                f"移除全部历史轮次后提示词仍为 {prompt_tokens} tokens，"
                f"超过预算 {self.max_input_tokens}；不截断当前问题。"
            )
        return system + body, dropped_turns, dropped_messages

    # ------------------------------------------------------------------ #
    def generate(
        self,
        messages: Sequence[Any],
        *,
        max_new_tokens: int = 256,
        do_sample: bool = False,
        temperature: float = 1.0,
        top_p: float = 1.0,
        repetition_penalty: float | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        if not self.loaded:
            self.load()
        torch = self._torch

        normalized: list[dict[str, str]] = []
        for index, item in enumerate(messages):
            role = item.get("role") if isinstance(item, dict) else getattr(item, "role", None)
            content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
            if role not in ("user", "assistant", "system"):
                raise GenerationError(f"messages[{index}].role 非法: {role!r}")
            if not isinstance(content, str):
                raise GenerationError(f"messages[{index}].content 必须是字符串")
            normalized.append({"role": role, "content": content})
        if not normalized:
            raise GenerationError("messages 不能为空")

        trimmed, dropped_turns, dropped_messages = self._trim(normalized)
        prompt = self._render(trimmed)

        try:
            inputs = self._tokenizer(prompt, return_tensors="pt")
            param_device = next(self._model.parameters()).device
            inputs = {name: tensor.to(param_device) for name, tensor in inputs.items()}
            prompt_tokens = int(inputs["input_ids"].shape[1])

            kwargs: dict[str, Any] = {"max_new_tokens": int(max_new_tokens)}
            if do_sample:
                kwargs.update(
                    {
                        "do_sample": True,
                        "temperature": float(temperature),
                        "top_p": float(top_p),
                    }
                )
            else:
                # transformers 5.x 在贪心解码时不再接受 temperature/top_p。
                kwargs["do_sample"] = False
            if repetition_penalty is not None:
                kwargs["repetition_penalty"] = float(repetition_penalty)

            if seed is not None:
                torch.manual_seed(int(seed))

            started = time.perf_counter()
            with torch.inference_mode():
                output = self._model.generate(**inputs, **kwargs)
            if param_device.type == "cuda":
                torch.cuda.synchronize()
            elapsed_ms = (time.perf_counter() - started) * 1000.0

            new_ids = output[0, prompt_tokens:]
            text = self._tokenizer.decode(new_ids, skip_special_tokens=True)
        except ContextTooLongError:
            raise
        except Exception as exc:
            raise GenerationError(f"生成失败: {type(exc).__name__}: {exc}") from exc

        return GenerationResult(
            text=text,
            prompt_tokens=prompt_tokens,
            new_tokens=int(new_ids.shape[0]),
            elapsed_ms=elapsed_ms,
            dropped_turns=dropped_turns,
            dropped_messages=dropped_messages,
            device=str(param_device),
            max_input_tokens=self.max_input_tokens,
        )