#!/usr/bin/env python3
"""A 分工：本地模型环境探针。

用途：确认「完整本地权重目录能否在断网、local_files_only 条件下加载并生成」，
并测量本机实际设备与生成速度，供 A1 基线记录和 A4 训练预算使用。

本脚本只读模型目录，不写任何文件，不联网。
"""
from __future__ import annotations

import argparse
import inspect
import os
import platform
import sys
import time
from pathlib import Path

# 必须先于 transformers 导入设置离线标志，否则可能触发远端元数据请求。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="本地 Qwen2 兼容模型加载与生成探针")
    parser.add_argument("--model-dir", required=True, type=Path, help="完整本地模型目录")
    parser.add_argument("--max-new-tokens", type=int, default=48)
    parser.add_argument("--prompt", default="我最近一想到考试就紧张，晚上也睡不好。")
    parser.add_argument("--repeat", type=int, default=1, help="重复生成次数，用于测速")
    return parser.parse_args()


def dtype_kwargs() -> dict[str, object]:
    """transformers 5.x 用 dtype，旧版本用 torch_dtype；两者都传会报错。"""
    import transformers

    major = int(transformers.__version__.split(".")[0])
    if major >= 5:
        return {"dtype": "float32"}
    return {"torch_dtype": "float32"}


def main() -> int:
    args = parse_args()
    model_dir = args.model_dir.resolve()
    if not model_dir.is_dir():
        print(f"FAIL: 模型目录不存在: {model_dir}", file=sys.stderr)
        return 2

    print(f"python        : {sys.version.split()[0]} ({platform.machine()})")
    print(f"model_dir     : {model_dir}")

    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"torch         : {torch.__version__}")
    print(f"transformers  : {transformers.__version__}")
    print(f"cuda_available: {torch.cuda.is_available()}")
    print(f"device_count  : {torch.cuda.device_count()}")
    print(f"torch_threads : {torch.get_num_threads()}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device        : {device}")

    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        str(model_dir), local_files_only=True, **dtype_kwargs()
    )
    model.eval()
    load_seconds = time.perf_counter() - started
    params = sum(p.numel() for p in model.parameters())
    dtypes = {str(p.dtype) for p in model.parameters()}
    print(f"load_seconds  : {load_seconds:.2f}")
    print(f"params        : {params:,}")
    print(f"param_dtypes  : {sorted(dtypes)}")
    print(f"model_type    : {model.config.model_type}")
    print(f"chat_template : {bool(getattr(tokenizer, 'chat_template', None))}")

    messages = [
        {"role": "system", "content": "你是中文日常陪伴助手，回复简短、先承接情绪。"},
        {"role": "user", "content": args.prompt},
    ]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer(prompt, return_tensors="pt")
    prompt_tokens = int(inputs["input_ids"].shape[1])
    print(f"prompt_chars  : {len(prompt)}")
    print(f"prompt_tokens : {prompt_tokens}")

    generation_kwargs: dict[str, object] = {
        "max_new_tokens": args.max_new_tokens,
        "do_sample": False,
        "repetition_penalty": 1.05,
    }
    # transformers 5.x 在 do_sample=False 时不再接受 temperature/top_p。
    signature = inspect.signature(model.generate)
    if "temperature" in signature.parameters and args.max_new_tokens:
        pass  # 保持确定性：不传 temperature，走默认贪心

    for index in range(1, args.repeat + 1):
        started = time.perf_counter()
        with torch.inference_mode():
            output = model.generate(**inputs, **generation_kwargs)
        elapsed = time.perf_counter() - started
        new_ids = output[0, prompt_tokens:]
        text = tokenizer.decode(new_ids, skip_special_tokens=True)
        new_tokens = int(new_ids.shape[0])
        speed = new_tokens / elapsed if elapsed > 0 else 0.0
        print(f"--- run {index} ---")
        print(f"new_tokens    : {new_tokens}")
        print(f"elapsed_s     : {elapsed:.3f}")
        print(f"tokens_per_s  : {speed:.2f}")
        print(f"reply         : {text.strip()!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())