# A11：GPU 训练脚本与端到端验证（卡被收回期间完成）

生成时间：2026-10-11 UTC
背景：实例 `183.222.230.12:58832` 的 GPU 在运行中被平台收回（见 [A10](A10-GPU被收回证据与交接.md)），
GPU 上无法训练。因此本轮把**重启后可以立刻开跑**的训练脚本写好并**在容器内用 CPU 端到端验证**，
同时修掉验证过程中暴露的两个真问题。

卡时消耗：**0 GPU 卡时**（所有验证都在 CPU 上跑）。

---

## 1. 新增产物

| 文件 | 说明 | SHA256（前 16） |
| --- | --- | --- |
| `training/gpu/train_gpu_sft.py` | GPU 训练脚本 | `e32bffd4878cfa68` |
| `training/gpu/model_config_gpu.json` | GPU 训练配置 | `ce0e2ac53abbe1d0` |

**CPU 基线 `training/train_sft.py` 未被改动**，SHA256 仍为
`1d94a26eb6553a4d95bd5cbf65a755834723207d2d8039b63ecc3c1890a11af9`（已验证）。

做法：先 **逐字节复制** CPU 基线，再用带断言的补丁脚本做定点修改
（每个替换模式必须恰好命中 1 次，否则整体失败不写回），共 17 + 5 处。
这样那 600 行已跑通逻辑保持逐字节不变，避免手抄引入错误。

### 与 CPU 基线的差异（全部改动）

1. `REPO_ROOT` 上移一级（本文件在 `training/gpu/`）。
2. 设备/精度由配置决定：`device` = `auto`/`cuda`/`cpu`，CUDA 上默认 `bfloat16`。
3. **CUDA 真实可算性闸门** `cuda_gate()`：必须在 GPU 上真算一次 2048×2048 矩阵乘法并
   `torch.cuda.synchronize()` 取回结果。**仅 `nvidia-smi` 能看到显卡不算通过**。
   未通过就写报告、返回 3、不开跑 —— 正是这次踩到的坑，写进脚本避免重犯。
4. **停止条件三层**：`max_steps` / `max_minutes` / `max_gpu_minutes`，另有
   `gpu_card_hours_cap` 上限；**停止条件超过上限时直接拒绝开跑**。
5. **零步数保护**：一次 `optimizer.step()` 都没发生就判 `failed`，见第 3 节。
6. 训练/验证的 batch 显式 `.to(device)`。

## 2. 验证一：CUDA 闸门确实拦得住

```
$ python -X utf8 training/gpu/train_gpu_sft.py --device cuda --smoke \
      --report a9_gpu_gate_check.json --log-name gate-check
FAIL: CUDA 闸门未通过 -> torch.cuda.is_available() = False
A_EXIT=3
```
报告如实记录：`status=failed`、`gpu_gate={'passed': False, 'reason': 'torch.cuda.is_available() = False'}`、
`failures=[...仅 nvidia-smi 能看到显卡不算通过...]`。
证据：`reports/model/gpu-evidence/a9_gpu_gate_check.json`。

## 3. 验证中发现并修掉的两个真问题

### 问题 A：`max_len=448` 对官方样本严重不足

用 tokenizer 实测官方样本**最短形式**（丢掉全部历史、只留 1 轮的极端裁剪）长度：

| 数据集 | p0 | p25 | p50 | p75 | p90 | p100 | 均值 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| train (200) | 397 | 474 | **514** | 596 | 770 | 1469 | 569.5 |
| valid (60) | 420 | 470 | **516** | 585 | 805 | 952 | 557.7 |

`max_len=448` 时：**train 只剩 16/200、valid 只剩 6/60**（实测与预测完全吻合）。

> 注意：A4 的 CPU 配置用 `max_len=448` 没出问题，是因为它用的是 A2 混合数据
> （chat 150 条短样本 + official 50 条）；**换成纯官方数据就崩了**。

修正：`max_len` 提到 **1280**（train 199/200、valid 60/60）。

### 问题 B：零步数"假成功"（更危险）

`max_len=448` 下只有 16 条可编码，而有效批 = `micro_batch 8 × grad_accum 8 = 64` 条，
16 条凑不满一个有效批 → **一次 `optimizer.step()` 都没发生**，脚本却报
`status=completed`、正常保存 1884 MB 权重、重载和生成也都"成功"。

**这会产出一个"假装训练过"的候选权重**（实际与基础模型等价），只看报告会以为训练有效。
证据：`reports/model/gpu-evidence/a9_gpu_script_smoke.json`
（`steps_done=0`、`stopped_reason=epochs_done`、`status=completed`）。

修正：加零步数保护，`steps_done==0` 时 `status=failed`、`zero_steps=true`、
写入 `blockers`、**退出码 4**。

## 4. 验证二：修复后完整跑通（CPU）

```
$ python -X utf8 training/gpu/train_gpu_sft.py --device cpu --smoke \
      --out /mnt/storage/b2-a/runs/smoke-cpu2 \
      --report a9_gpu_script_smoke2.json --log-name sft-gpu-smoke2
状态        : completed  停止原因=max_steps
步数        : 2  用时 3.82 min
loss        : 2.755275011062622 -> 2.1835265159606934  val=2.37801
设备        : cpu (float32)  GPU 卡时 0.0 h / 上限 6.0 h
可训练参数  : 59,650,432 / 494,032,768
产物        : /mnt/storage/b2-a/runs/smoke-cpu2  (1884.62 MB)
```

| 检查项 | 结果 |
| --- | --- |
| 可用样本 | **199 / 200**（丢 1 条超长），验证 60 / 60 |
| 真实步数 | **`steps_done = 2`**，`stopped_reason = max_steps`，`zero_steps = False` |
| 逐步日志 | `{"step": 1, "loss": 2.613778, "lr": 1e-05, "step_seconds": 14.048}` |
| **保存** | 9 个文件齐全，`model.safetensors` 1,976,163,472 B |
| **重载** | `loaded: True`，参数量 494,032,768 |
| **生成** | 探针回复 **"好，休息一下，慢慢来。"**（非空） |
| 共享权重处理 | `lm_head.weight` 与 `model.embed_tokens.weight` 共享，只存一份（safetensors 不接受共享存储） |

loss 从 2.755 降到 2.184、val 2.378，说明确实在学。

## 5. 卡时预算与停止条件（按要求）

| 项 | 值 |
| --- | --- |
| `gpu_card_hours_cap` | **6**（用户口径：累计训练最多 6 卡时且不超过剩余额度） |
| `stop_at_gpu_minutes` | **330**（5.5 小时，留 0.5 小时余量） |
| 超过上限时 | 脚本**拒绝开跑**并写报告（不是跑完才发现超了） |
| 卡时记账 | 单卡，GPU 卡时 = GPU 墙钟小时数，跑完写进报告与 `training_meta.json` |
| 其他停止条件 | `max_steps=30`、`max_minutes=30`（墙钟双保险） |

**步数可达性（纯算术验证）**：199 条样本、有效批 64 → 25 个 micro-batch/epoch → 3 步/epoch；
`max_epochs=10` 可达成 **31 步**，第 10 个 epoch 触及 `max_steps=30`。
（原配置 `max_epochs=2` 只够 6 步 —— 与 A4 CPU 基线实测的 6 步一致。）

预计 GPU 上 30 步的耗时：CPU 为 14.0 s/步，RTX 4090 上约 1–2 分钟量级，
**远低于 6 卡时上限**，实际卡时预计 **< 0.1 卡时**。

## 6. 重启后直接执行的命令

```bash
cd /mnt/storage/b2-a/repo
PY=/opt/conda/envs/conda_env/bin/python

# 1) 先过闸门（会真算一次 2048^3 矩阵乘法，失败即停，不浪费卡时）
$PY -X utf8 training/gpu/train_gpu_sft.py --device cuda --smoke \
    --out /mnt/storage/b2-a/runs/gpu-smoke \
    --report a9_gpu_smoke.json --log-name sft-gpu-smoke

# 2) 极短训练没问题后，再跑正式短训练（30 步）
$PY -X utf8 training/gpu/train_gpu_sft.py --device cuda \
    --out /mnt/storage/b2-a/runs/gpu-short \
    --report a9_gpu_short.json --log-name sft-gpu-short
```

第 1 步同时完成"极短训练 + 保存/重载/生成验证"；第 2 步是"短训练"。

## 7. 本轮未做的事（如实记录）

- **GPU 上一次训练都没跑**：卡自 05:43 UTC 起不可用，到 06:20 仍不可用。
- 因此没有 GPU 产物、没有 GPU 卡时消耗；所有验证均为 CPU。
- **尚未在真实 CUDA 上验证** bfloat16 路径与 `.to(device)` 搬批（闸门与 CPU 路径已验证）。
  重启后第 1 步的 smoke 会覆盖这段。