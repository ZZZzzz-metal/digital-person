#!/usr/bin/env python3
"""A9：GPU 实例上的一次受预算约束的小规模训练（保存 → 重载 → 生成验证）。

本文件是 ``training/train_sft.py``（已在 CPU 上跑通的 A4 脚本）的 GPU 变体：
**逐字节复制后只改设备相关部分**，CPU 基线脚本保持不动、可继续复现。

与 CPU 版的差别只有这几处：

1. ``REPO_ROOT`` 上移一级（本文件在 ``training/gpu/``）。
2. 设备/精度由配置决定：``device`` 可为 ``auto``/``cuda``/``cpu``；CUDA 上默认 bfloat16。
3. 开跑前有 **CUDA 真实可算性闸门**：必须在 GPU 上真算一次 2048×2048 矩阵乘法并
   ``torch.cuda.synchronize()`` 取回结果。仅 ``nvidia-smi`` 能看到显卡**不算通过** ——
   实例的 ``/dev/nvidia*`` 可能被平台收回，此时闸门会明确失败并写出报告，不浪费卡时。
4. 增加 **GPU 墙钟停止条件** ``stop_at_gpu_minutes`` 与 **卡时上限** ``gpu_card_hours_cap``：
   停止条件超过上限时拒绝开跑；跑完把实际卡时写进报告。
5. 训练/验证的 batch 显式搬到设备上。

做法与边界：

- 不从零预训练。只在基础模型的**最后 N 层 Transformer + 最终 norm** 上做小规模适配，
  其余参数冻结；不引入 peft/accelerate 等新依赖，只用已有的 torch。
- 数据是 A2 整理的 200 条有效样本（chat 150 + official 50），按完整会话划分，
  评测集不参与训练。
- 训练目标：chat 样本学「承接 + 简短回应」，official 样本学「只输出官方 JSON」。
- 到达 ``max_steps`` 或 ``max_minutes`` 就停止并保存当前检查点。
- 保存的是**完整可加载的模型目录**（config + tokenizer + 全量 fp32 权重），
  重载只需要把 ``inference_config.json`` 的 ``model_dir`` 指过去，不依赖任何适配器。
- 失败就如实记录失败原因并退回基线，不连续换工具、不扩大数据。

日志：
- 逐步日志 ``training/logs/<name>.steps.jsonl``（进 Git）
- 汇总 ``reports/model/<report>.json``（进 Git）
- 产物目录 ``weights/sft-short/``（大权重不进 Git，见 weights/.gitignore）
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "model"))

from _bootstrap import REPO_ROOT as _ROOT  # noqa: E402
from b2_core.a_impl import official_spec  # noqa: E402
from b2_core.prompts import empathy  # noqa: E402

DEFAULT_CONFIG = REPO_ROOT / "training" / "gpu" / "model_config_gpu.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A4 小规模 SFT 尝试")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, default=None, help="覆盖输出目录")
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--max-minutes", type=float, default=None)
    parser.add_argument("--smoke", action="store_true", help="冒烟模式：只跑 2 步，验证保存/重载")
    parser.add_argument("--report", default="a9_gpu_training.json")
    parser.add_argument("--log-name", default="sft-gpu")
    parser.add_argument(
        "--device",
        default=None,
        choices=["auto", "cuda", "cpu"],
        help="覆盖配置里的 device；auto = 有可用 CUDA 就用 CUDA",
    )
    parser.add_argument(
        "--max-gpu-minutes",
        type=float,
        default=None,
        help="GPU 墙钟停止条件（分钟），默认取配置 budget.stop_at_gpu_minutes",
    )
    return parser.parse_args()


def resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


# --------------------------------------------------------------------------- #
def candidate_message_sets(row: dict, official_prompt: str):
    """由长到短生成候选 messages：每次丢掉最旧的一个完整轮次。

    这和推理时的上下文裁剪是同一套规则（保留 system 与当前问题，不截断当前问题），
    所以长样本不必被丢弃，只是用得少一点的历史。
    """
    if row["kind"] == "chat":
        system = {
            "role": "system",
            "content": empathy.build_system_prompt(
                "伴学：中文日常陪伴助手", row.get("memory_context", "")
            ),
        }
        context = [{"role": m["role"], "content": m["content"]} for m in row["messages"]]
        while True:
            yield [system] + context
            if len(context) <= 1:
                return
            drop = (
                2
                if len(context) >= 2
                and context[0]["role"] == "user"
                and context[1]["role"] == "assistant"
                else 1
            )
            context = context[drop:]
    else:
        history = list(row["history"])
        while True:
            yield [
                {"role": "system", "content": official_prompt},
                {
                    "role": "user",
                    "content": official_spec.render_conversation(row["sample_id"], history),
                },
            ]
            if len(history) <= 1:
                return
            # 绝不丢掉最后的目标 user 轮
            drop = (
                2
                if len(history) >= 3
                and history[0]["role"] == "user"
                and history[1]["role"] == "assistant"
                else 1
            )
            history = history[drop:]


def encode(tokenizer, row: dict, official_prompt: str, max_len: int):
    """把一条样本编码成 (input_ids, labels)；超长时裁剪最旧轮次，不丢样本。"""
    completion = {
        "role": "assistant",
        "content": row["target"] if row["kind"] == "chat" else row["target_json"],
    }

    best = None
    dropped_turns = 0
    for turns_dropped, messages in enumerate(candidate_message_sets(row, official_prompt)):
        prompt_text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        full_text = tokenizer.apply_chat_template(
            messages + [completion], tokenize=False, add_generation_prompt=False
        )
        prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
        full_ids = tokenizer(full_text, add_special_tokens=False)["input_ids"]

        if full_ids[: len(prompt_ids)] == prompt_ids:
            split = len(prompt_ids)
        else:
            split = 0
            for index, token in enumerate(full_ids):
                if index < len(prompt_ids) and token == prompt_ids[index]:
                    split = index + 1
                else:
                    break
        if split >= len(full_ids):
            continue

        candidate = {
            "input_ids": full_ids,
            "labels": [-100] * split + list(full_ids[split:]),
            "prompt_tokens": split,
            "target_tokens": len(full_ids) - split,
            "kind": row["kind"],
            "example_id": row["example_id"],
            "turns_dropped": turns_dropped,
        }
        if best is None or len(full_ids) < len(best["input_ids"]):
            best = candidate
        if len(full_ids) <= max_len:
            return candidate, turns_dropped

    if best is None:
        return None, 0
    # 连最短的候选都超长：如实丢弃并在报告里计数
    if len(best["input_ids"]) > max_len:
        return None, best["turns_dropped"]
    return best, best["turns_dropped"]


def collate(batch: list[dict], pad_id: int, torch):
    max_len = max(len(item["input_ids"]) for item in batch)
    input_ids, labels, attention = [], [], []
    for item in batch:
        pad = max_len - len(item["input_ids"])
        input_ids.append(item["input_ids"] + [pad_id] * pad)
        labels.append(item["labels"] + [-100] * pad)
        attention.append([1] * len(item["input_ids"]) + [0] * pad)
    return (
        torch.tensor(input_ids, dtype=torch.long),
        torch.tensor(labels, dtype=torch.long),
        torch.tensor(attention, dtype=torch.long),
    )


# --------------------------------------------------------------------------- #
def write_report(report: dict, report_name: str) -> Path:
    """把报告写进 reports/model/。失败路径也要留证据，所以抽出来复用。"""
    reports_dir = REPO_ROOT / "reports" / "model"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / report_name
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def cuda_gate(torch) -> dict:
    """CUDA 真实可算性闸门：仅 nvidia-smi 能看到显卡**不算通过**。

    必须在 GPU 上真算一次矩阵乘法并用 ``torch.cuda.synchronize()`` 取回结果。
    实例的 ``/dev/nvidia*`` 被平台收回时（root 打开报 EPERM），
    这里会明确失败并带上原因，避免把卡时花在用不了的设备上。
    """
    result: dict = {"passed": False}
    if not torch.cuda.is_available():
        result["reason"] = "torch.cuda.is_available() = False"
        return result
    try:
        props = torch.cuda.get_device_properties(0)
        result["device_name"] = torch.cuda.get_device_name(0)
        result["capability"] = list(torch.cuda.get_device_capability(0))
        result["total_memory_gb"] = round(props.total_memory / 1024**3, 2)
        a = torch.randn(2048, 2048, device="cuda")
        b = torch.randn(2048, 2048, device="cuda")
        torch.cuda.synchronize()
        started = time.perf_counter()
        c = a @ b
        torch.cuda.synchronize()
        result.update(
            {
                "passed": True,
                "matmul_shape": [2048, 2048, 2048],
                "matmul_sum": float(c.sum()),
                "matmul_ms": round((time.perf_counter() - started) * 1000, 2),
                "max_memory_allocated_mb": round(
                    torch.cuda.max_memory_allocated() / 1024**2, 2
                ),
            }
        )
        del a, b, c
        torch.cuda.empty_cache()
    except Exception as exc:  # noqa: BLE001
        result["reason"] = f"{type(exc).__name__}: {exc}"
    return result


# --------------------------------------------------------------------------- #
def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    base_dir = config_path.parent

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.manual_seed(int(raw_config["seed"]))
    torch.set_num_threads(int(raw_config.get("torch_threads", 16)))

    base_model_dir = resolve(base_dir, raw_config["base_model_dir"])
    out_dir = args.out or resolve(base_dir, raw_config["output_dir"])
    train_path = resolve(base_dir, raw_config["data"]["train"])
    valid_path = resolve(base_dir, raw_config["data"]["valid"])
    max_steps = args.max_steps if args.max_steps is not None else int(raw_config["max_steps"])
    max_minutes = (
        args.max_minutes if args.max_minutes is not None else float(raw_config["max_minutes"])
    )
    if args.smoke:
        max_steps = 2
        max_minutes = min(max_minutes, 10.0)

    logs_dir = REPO_ROOT / "training" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    steps_log = logs_dir / f"{args.log_name}.steps.jsonl"
    steps_log.write_text("", encoding="utf-8")

    report: dict = {
        "node": "A4 小规模训练尝试",
        "config_path": str(config_path),
        "config": raw_config,
        "smoke_mode": bool(args.smoke),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "started",
        "device": None,
        "device_requested": None,
        "dtype": None,
        "gpu_available": False,
        "gpu_card_hours_used": 0,
        "gpu_card_hours_cap": None,
        "max_gpu_minutes": None,
        "gpu_gate": None,
        "notes": [],
        "blockers": [],
    }

    # ---------------------------------------------------------------- #
    # 1) 设备判定 + CUDA 真实可算性闸门
    # ---------------------------------------------------------------- #
    if not base_model_dir.is_dir():
        report["status"] = "failed"
        report["failures"] = [f"基础模型目录不存在: {base_model_dir}"]
        print(f"FAIL: 基础模型目录不存在: {base_model_dir}")
        write_report(report, args.report)
        return 2

    requested_device = args.device or str(raw_config.get("device", "cpu"))
    if requested_device == "auto":
        requested_device = "cuda" if torch.cuda.is_available() else "cpu"
    report["device_requested"] = requested_device
    report["gpu_available"] = bool(torch.cuda.is_available())

    budget = raw_config.get("budget", {})
    gpu_cap_hours = float(budget.get("gpu_card_hours_cap", 6))
    stop_at_gpu_minutes = (
        args.max_gpu_minutes
        if args.max_gpu_minutes is not None
        else float(budget.get("stop_at_gpu_minutes", gpu_cap_hours * 60 - 30))
    )
    report["gpu_card_hours_cap"] = gpu_cap_hours
    report["max_gpu_minutes"] = stop_at_gpu_minutes
    if stop_at_gpu_minutes > gpu_cap_hours * 60:
        report["status"] = "failed"
        report["failures"] = [
            f"停止条件 {stop_at_gpu_minutes} 分钟超过卡时上限 {gpu_cap_hours} 小时，拒绝开跑"
        ]
        print(f"FAIL: 停止条件超过卡时上限 {stop_at_gpu_minutes} > {gpu_cap_hours * 60} 分钟")
        write_report(report, args.report)
        return 2

    if requested_device == "cuda":
        gate = cuda_gate(torch)
        report["gpu_gate"] = gate
        if not gate.get("passed"):
            report["status"] = "failed"
            report["failures"] = [
                "CUDA 真实可算性闸门未通过："
                f"{gate.get('reason')}。仅 nvidia-smi 能看到显卡不算通过，"
                "因此不在该设备上开跑，以免浪费卡时。"
            ]
            print(f"FAIL: CUDA 闸门未通过 -> {gate.get('reason')}")
            write_report(report, args.report)
            return 3
        print(
            f"CUDA 闸门通过: {gate['device_name']}  capability={gate['capability']}  "
            f"mem={gate['total_memory_gb']} GB  matmul2048 sum={gate['matmul_sum']}  "
            f"{gate['matmul_ms']} ms",
            flush=True,
        )
        dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16}.get(
            str(raw_config.get("dtype", "bfloat16")), torch.bfloat16
        )
    else:
        dtype = torch.float32
    device = torch.device(requested_device)
    report["device"] = requested_device
    report["dtype"] = str(dtype).replace("torch.", "")

    tokenizer = AutoTokenizer.from_pretrained(str(base_model_dir), local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        str(base_model_dir), local_files_only=True, dtype=dtype
    )
    model.to(device)
    gpu_clock_started = time.perf_counter()
    if requested_device == "cpu":
        report["blockers"].append(
            "本次按 CPU 路径执行（--device cpu 或环境无可用 CUDA），未消耗 GPU 卡时。"
        )

    # ---------------------------------------------------------------- #
    # 2) 冻结 + 选择可训练参数
    # ---------------------------------------------------------------- #
    for param in model.parameters():
        param.requires_grad = False

    layers = model.model.layers
    trainable_layers = int(raw_config.get("trainable_layers", 6))
    selected_layers = layers[len(layers) - trainable_layers :]
    for layer in selected_layers:
        for param in layer.parameters():
            param.requires_grad = True
    for param in model.model.norm.parameters():
        param.requires_grad = True
    if raw_config.get("train_lm_head"):
        for param in model.lm_head.parameters():
            param.requires_grad = True
        report["notes"].append(
            "lm_head 与词嵌入权重共享（tie_word_embeddings=true），"
            "解冻 lm_head 会同时训练嵌入层，显存/内存开销显著上升。"
        )

    trainable = [p for p in model.parameters() if p.requires_grad]
    trainable_params = sum(p.numel() for p in trainable)
    total_params = sum(p.numel() for p in model.parameters())
    report["parametrization"] = {
        "total_params": total_params,
        "trainable_params": trainable_params,
        "trainable_ratio": round(trainable_params / total_params, 6),
        "trainable_layers": trainable_layers,
        "train_lm_head": bool(raw_config.get("train_lm_head")),
        "frozen_layers": len(layers) - trainable_layers,
    }

    optimizer = torch.optim.AdamW(
        trainable,
        lr=float(raw_config["lr"]),
        weight_decay=float(raw_config.get("weight_decay", 0.0)),
    )

    # 批大小口径（后面报告与循环都用这两个量，先在这里定好）：
    #   micro_batch —— 一次 forward/backward 喂多少条样本
    #   grad_accum  —— 累积多少次 micro-batch 才做一次 optimizer.step()
    #   有效批大小 = micro_batch × grad_accum（条样本），"1 step" 指一次 optimizer.step()
    grad_accum = int(raw_config["grad_accum"])
    micro_batch = int(raw_config.get("micro_batch", grad_accum))

    # ---------------------------------------------------------------- #
    # 3) 编码数据
    # ---------------------------------------------------------------- #
    official_prompt = official_spec.build_system_prompt()
    max_len = int(raw_config["max_len"])
    train_rows = load_jsonl(train_path)
    valid_rows = load_jsonl(valid_path)

    encoded_train, skipped_train, training_truncated = [], [], 0
    for row in train_rows:
        item, dropped = encode(tokenizer, row, official_prompt, max_len)
        if item is None:
            skipped_train.append(row["example_id"])
        else:
            encoded_train.append(item)
            if dropped:
                training_truncated += 1

    encoded_valid, skipped_valid, valid_truncated = [], [], 0
    for row in valid_rows:
        item, dropped = encode(tokenizer, row, official_prompt, max_len)
        if item is None:
            skipped_valid.append(row["example_id"])
        else:
            encoded_valid.append(item)
            if dropped:
                valid_truncated += 1

    report["data"] = {
        "train_file": str(train_path),
        "valid_file": str(valid_path),
        "train_examples": len(encoded_train),
        "train_skipped_over_length": len(skipped_train),
        "train_skipped_ids": skipped_train,
        "valid_examples": len(encoded_valid),
        "valid_skipped_over_length": len(skipped_valid),
        "train_examples_truncated": training_truncated,
        "valid_examples_truncated": valid_truncated,
        "mean_train_tokens": (
            round(sum(len(i["input_ids"]) for i in encoded_train) / len(encoded_train), 1)
            if encoded_train
            else None
        ),
        "max_len": max_len,
        "seed": int(raw_config["seed"]),
        "lr": float(raw_config["lr"]),
        "micro_batch": micro_batch,
        "grad_accum": grad_accum,
        "effective_batch_examples": micro_batch * grad_accum,
        "max_steps": max_steps,
        "max_minutes": max_minutes,
        "step_definition": "1 step = 1 次 optimizer.step() = micro_batch × grad_accum 条样本",
    }
    if not encoded_train:
        report["status"] = "failed"
        report["failures"] = ["没有一条训练样本能编码进 max_len"]
        print("FAIL: 训练样本为 0")
        return 2

    # ---------------------------------------------------------------- #
    # 4) 训练循环
    # ---------------------------------------------------------------- #
    grad_clip = float(raw_config.get("grad_clip", 1.0))
    log_every = int(raw_config.get("log_every", 5))
    val_every = int(raw_config.get("val_every", 10))
    warmup_steps = int(raw_config.get("warmup_steps", 5))
    max_epochs = int(raw_config.get("max_epochs", 2))
    pad_id = tokenizer.pad_token_id or tokenizer.eos_token_id

    def lr_at(step: int) -> float:
        if step < warmup_steps:
            return float(raw_config["lr"]) * (step + 1) / max(1, warmup_steps)
        progress = (step - warmup_steps) / max(1, max_steps - warmup_steps)
        return float(raw_config["lr"]) * max(0.0, 1.0 - progress)

    def validate() -> float | None:
        if not encoded_valid:
            return None
        model.eval()
        total, count = 0.0, 0
        with torch.inference_mode():
            for offset in range(0, len(encoded_valid), micro_batch):
                batch = encoded_valid[offset : offset + micro_batch]
                input_ids, labels, attention = collate(batch, pad_id, torch)
                input_ids = input_ids.to(device)
                labels = labels.to(device)
                attention = attention.to(device)
                out = model(input_ids=input_ids, attention_mask=attention, labels=labels)
                total += float(out.loss)
                count += 1
        model.train()
        return round(total / max(1, count), 6)

    model.train()
    start_time = time.perf_counter()
    losses: list[float] = []
    step_times: list[float] = []
    global_step = 0
    micro = 0
    epoch = 0
    stopped_reason = "epochs_done"

    import random

    rng = random.Random(int(raw_config["seed"]))

    while global_step < max_steps and epoch < max_epochs:
        epoch += 1
        order = list(range(len(encoded_train)))
        rng.shuffle(order)
        epoch_losses: list[float] = []
        for start in range(0, len(order), micro_batch):
            chunk = [encoded_train[i] for i in order[start : start + micro_batch]]
            if not chunk:
                continue
            step_started = time.perf_counter()
            input_ids, labels, attention = collate(chunk, pad_id, torch)
            input_ids = input_ids.to(device)
            labels = labels.to(device)
            attention = attention.to(device)
            out = model(input_ids=input_ids, attention_mask=attention, labels=labels)
            loss = out.loss / len(chunk)
            loss.backward()
            micro += 1
            epoch_losses.append(float(out.loss.detach()))
            losses.append(float(out.loss.detach()))

            if micro % grad_accum == 0:
                for group in optimizer.param_groups:
                    group["lr"] = lr_at(global_step)
                torch.nn.utils.clip_grad_norm_(trainable, grad_clip)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                global_step += 1
                step_seconds = time.perf_counter() - step_started
                step_times.append(step_seconds)

                if global_step % log_every == 0 or global_step == 1:
                    record = {
                        "step": global_step,
                        "epoch": epoch,
                        "loss": round(sum(epoch_losses[-grad_accum:]) / grad_accum, 6),
                        "lr": optimizer.param_groups[0]["lr"],
                        "elapsed_minutes": round((time.perf_counter() - start_time) / 60, 3),
                        "step_seconds": round(step_seconds, 3),
                    }
                    with steps_log.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    print(
                        f"step {global_step:>3}/{max_steps}  loss={record['loss']:.4f}  "
                        f"lr={record['lr']:.2e}  {record['elapsed_minutes']:.2f} min",
                        flush=True,
                    )

                if val_every and global_step % val_every == 0:
                    val_loss = validate()
                    with steps_log.open("a", encoding="utf-8") as handle:
                        handle.write(
                            json.dumps({"step": global_step, "val_loss": val_loss}, ensure_ascii=False)
                            + "\n"
                        )
                    print(f"  val_loss={val_loss}", flush=True)

                elapsed_minutes = (time.perf_counter() - start_time) / 60
                # GPU 卡时停止条件：先于普通 max_minutes 判定，避免超预算
                if requested_device == "cuda" and elapsed_minutes >= stop_at_gpu_minutes:
                    stopped_reason = "max_gpu_minutes"
                    break
                if elapsed_minutes >= max_minutes:
                    stopped_reason = "max_minutes"
                    break
                if global_step >= max_steps:
                    stopped_reason = "max_steps"
                    break
        if stopped_reason in ("max_minutes", "max_steps", "max_gpu_minutes"):
            break

    total_minutes = (time.perf_counter() - start_time) / 60
    gpu_wall_minutes = (time.perf_counter() - gpu_clock_started) / 60
    # 单卡：GPU 卡时 = GPU 墙钟小时数
    gpu_card_hours_used = (
        round(gpu_wall_minutes / 60, 4) if requested_device == "cuda" else 0.0
    )
    if requested_device == "cuda" and gpu_card_hours_used > gpu_cap_hours:
        report["blockers"].append(
            f"GPU 卡时 {gpu_card_hours_used} h 已超过上限 {gpu_cap_hours} h"
        )
    if global_step >= max_steps:
        stopped_reason = "max_steps"
    elif requested_device == "cuda" and total_minutes >= stop_at_gpu_minutes:
        stopped_reason = "max_gpu_minutes"
    elif total_minutes >= max_minutes:
        stopped_reason = "max_minutes"
    report["gpu_card_hours_used"] = gpu_card_hours_used
    # 零步数保护：一次 optimizer.step() 都没发生就等于什么都没训，
    # 绝不能报成功，否则会产出一个"假装训练过"的候选权重。
    zero_step_failure = global_step == 0
    if zero_step_failure:
        report["blockers"].append(
            "本次没有发生任何 optimizer.step()（0 步）：可编码样本数不足一个有效批"
            f"（micro_batch {micro_batch} × grad_accum {grad_accum} = "
            f"{micro_batch * grad_accum} 条），产物等同于未训练的基础模型。"
            "请检查 max_len 是否过小导致样本被大量丢弃，或 max_epochs 是否过少。"
        )
    final_val_loss = validate()

    # ---------------------------------------------------------------- #
    # 5) 保存完整可加载模型
    # ---------------------------------------------------------------- #
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "config.json",
        "generation_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
        "merges.txt",
        "LICENSE",
    ):
        source = base_model_dir / name
        if source.is_file():
            shutil.copy2(source, out_dir / name)

    from safetensors.torch import save_file

    # tie_word_embeddings=true 时 embed_tokens 与 lm_head 共享同一块存储；
    # safetensors 拒绝保存共享存储，加载时也会按 config 重新绑定，所以只存一份。
    # 排序时把 lm_head 放在后面，保证保留的是词嵌入。
    raw_state = model.state_dict()
    seen_ptrs: dict[int, str] = {}
    kept_names: list[str] = []
    tied_dropped: list[str] = []
    for name, tensor in sorted(
        raw_state.items(), key=lambda kv: (kv[0].startswith("lm_head"), kv[0])
    ):
        ptr = tensor.data_ptr()
        if ptr in seen_ptrs:
            tied_dropped.append(f"{name} 与 {seen_ptrs[ptr]} 共享存储，只保存后者")
            continue
        seen_ptrs[ptr] = name
        kept_names.append(name)

    state = {
        name: raw_state[name].detach().to(torch.float32).cpu().contiguous()
        for name in kept_names
    }
    save_file(state, str(out_dir / "model.safetensors"), metadata={"format": "pt"})
    size_bytes = (out_dir / "model.safetensors").stat().st_size

    # 重新加载验证：不能只凭训练日志宣称推理可用。
    reload_result: dict = {"attempted": True}
    try:
        reload_tokenizer = AutoTokenizer.from_pretrained(str(out_dir), local_files_only=True)
        reload_model = AutoModelForCausalLM.from_pretrained(
            str(out_dir), local_files_only=True, dtype=torch.float32
        )
        reload_model.eval()
        probe_messages = [
            {"role": "system", "content": "你是中文日常陪伴助手，回复简短。"},
            {"role": "user", "content": "我今天有点累。"},
        ]
        probe_prompt = reload_tokenizer.apply_chat_template(
            probe_messages, tokenize=False, add_generation_prompt=True
        )
        probe_inputs = reload_tokenizer(probe_prompt, return_tensors="pt")
        with torch.inference_mode():
            probe_out = reload_model.generate(
                **probe_inputs, max_new_tokens=24, do_sample=False
            )
        probe_text = reload_tokenizer.decode(
            probe_out[0, probe_inputs["input_ids"].shape[1] :], skip_special_tokens=True
        )
        reload_result.update(
            {
                "loaded": True,
                "params": sum(p.numel() for p in reload_model.parameters()),
                "probe_reply": probe_text.strip(),
                "probe_non_empty": bool(probe_text.strip()),
            }
        )
        del reload_model
    except Exception as exc:  # noqa: BLE001
        reload_result.update({"loaded": False, "error": f"{type(exc).__name__}: {exc}"})
    if not reload_result.get("loaded") or not reload_result.get("probe_non_empty"):
        report["blockers"].append("训练产物重新加载验证失败，不能作为可交接候选。")

    meta = {
        "candidate_model_version": raw_config.get("candidate_model_version"),
        "base_model_dir": str(base_model_dir),
        "base_model_version": raw_config.get("base_model_version"),
        "data_version": raw_config.get("data_version"),
        "train_file": str(train_path),
        "train_examples": len(encoded_train),
        "valid_examples": len(encoded_valid),
        "seed": int(raw_config["seed"]),
        "lr": float(raw_config["lr"]),
        "micro_batch": micro_batch,
        "grad_accum": grad_accum,
        "effective_batch_examples": micro_batch * grad_accum,
        "max_len": max_len,
        "trainable_layers": trainable_layers,
        "trainable_params": trainable_params,
        "total_params": total_params,
        "steps_done": global_step,
        "max_steps": max_steps,
        "max_minutes": max_minutes,
        "stopped_reason": stopped_reason,
        "zero_steps": zero_step_failure,
        "loss_first": losses[0] if losses else None,
        "loss_last": losses[-1] if losses else None,
        "val_loss": final_val_loss,
        "elapsed_minutes": round(total_minutes, 3),
        "started_at": report["started_at"],
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "device": requested_device,
        "dtype": report["dtype"],
        "gpu_card_hours_used": gpu_card_hours_used,
        "gpu_card_hours_cap": gpu_cap_hours,
        "gpu_wall_minutes": round(gpu_wall_minutes, 3),
        "gpu_gate": report.get("gpu_gate"),
        "tied_tensors_dropped": tied_dropped,
        "reload_check": reload_result,
        "budget_note": raw_config["budget"]["note"],
    }
    (out_dir / "training_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    report.update(
        {
            "status": "failed" if zero_step_failure else "completed",
            "zero_steps": zero_step_failure,
            "output_dir": str(out_dir),
            "weights_bytes": size_bytes,
            "weights_mb": round(size_bytes / (1024 * 1024), 2),
            "steps_done": global_step,
            "stopped_reason": stopped_reason,
            "train_minutes": round(total_minutes, 3),
            "loss_first": meta["loss_first"],
            "loss_last": meta["loss_last"],
            "val_loss": final_val_loss,
            "mean_step_seconds": round(sum(step_times) / len(step_times), 3) if step_times else None,
            "steps_log": str(steps_log.relative_to(REPO_ROOT)),
            "reload_check": reload_result,
            "tied_tensors_dropped": tied_dropped,
            "finished_at": meta["finished_at"],
            "gpu_card_hours_used": gpu_card_hours_used,
            "gpu_wall_minutes": round(gpu_wall_minutes, 3),
            "stop_at_gpu_minutes": stop_at_gpu_minutes,
            "dtype": report["dtype"],
        }
    )

    write_report(report, args.report)

    print()
    print(f"状态        : {report['status']}  停止原因={stopped_reason}")
    if zero_step_failure:
        print("警告        : 0 步！本次未发生任何 optimizer.step()，产物等于未训练的基础模型")
    print(f"步数        : {global_step}  用时 {total_minutes:.2f} min")
    print(f"loss        : {meta['loss_first']} -> {meta['loss_last']}  val={final_val_loss}")
    print(
        f"设备        : {requested_device} ({report['dtype']})  "
        f"GPU 卡时 {gpu_card_hours_used} h / 上限 {gpu_cap_hours} h"
    )
    print(f"可训练参数  : {trainable_params:,} / {total_params:,}")
    print(f"产物        : {out_dir}  ({report['weights_mb']} MB)")
    print(f"报告        : reports/model/{args.report}")
    return 4 if zero_step_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())