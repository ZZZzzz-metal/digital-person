# A10：新实例 GPU 访问权被平台收回 —— 证据与交接

生成时间：2026-10-11（UTC 05:37–05:51 实测）
对应实例：`183.222.230.12:58832`（SSH）
结论：**新实例的 GPU 先可用、后被平台在运行中收回**；容器全程未重启。属于平台侧问题，容器内无法修复。

---

## 1. 一句话结论

同一容器内，`/dev/nvidia*` 的访问权**先正常、后被收回**：

- **05:37:42 UTC**：`nvidia-smi -L` 正常、root 打开 `/dev/nvidiactl` 成功、
  `torch.cuda.is_available()=True`、`device_count=1`、
  **2048×2048 fp32 矩阵运算实测通过**（`sum = -35980.6171875`，45.97 ms，sm_89，23.52 GB 显存）
- **05:43:55 UTC 起**：`nvidia-smi` 报 `Failed to initialize NVML: Unknown Error`，
  root 打开 `/dev/nvidiactl` 报 `PermissionError [Errno 1] Operation not permitted`，
  `torch.cuda.is_available()=False`、`device_count=0`
- **05:43–05:50 UTC**：连续 **16 次**重试（间隔 15–20 秒），**零恢复**

这不是「nvidia-smi 显示不出卡」的空壳故障：**故障前已经算出过真实矩阵结果并同步等待完成**，
故障后连设备节点都打不开。

## 2. 实例与容器身份（供平台定位）

| 项 | 值 |
| --- | --- |
| 申请规格 | **1 × NVIDIA GeForce RTX 4090** |
| 平台 | 咪咕仝学 AI 算力实例 |
| SSH | `root@183.222.230.12 -p 58832` |
| 实例名（hostname） | `ai-traininfer-a60eedc8-963ea058-f75578f6b-b4t8t` |
| pod | `kubepods-burstable-podf34da95a_95aa_4eaf_80e6_3b8bd6a42115` |
| 容器 scope | `cri-containerd-5e12339147401e012ed5fdf63353f612a38dc6e627d58d1e4797bf49069d5c08` |
| 容器 PID1 启动 | 2026-10-11 05:27:36 UTC（**全程未重启**） |
| 宿主内核 | `5.10.0-60.18.0.50.oe2203.x86_64` |
| GPU UUID | `GPU-6eb99c9c-65f5-c86b-5fe0-6cd90c1f9856` |
| PCI | `0000:c1:00.0`，Device Minor **5** |
| 驱动 | 595.71.05（宿主机侧正常，仍枚举到该卡） |

## 3. 故障时的实测证据

| 检查项 | 结果 |
| --- | --- |
| `/dev/nvidia5`、`/dev/nvidiactl`、`/dev/nvidia-uvm`、`/dev/nvidia-uvm-tools` | **节点都在**（时间戳 Sep 9 15:21 = 镜像构建日，`195,5` / `195,255` / `508,0` / `508,1`） |
| `/dev/nvidia0` | **不存在**（容器分到的是 minor 5） |
| `/dev/nvidia-caps` | **不存在**（`/proc/devices` 显示主设备号 236 `nvidia-caps` 已注册） |
| root `open()` 上述四个节点 | **全部 `EPERM Operation not permitted`** ← 失败点 |
| `nvidia-smi` | `Failed to initialize NVML: Unknown Error`（**这是 C 程序**） |
| `dlopen("libcuda.so.1")` / `dlopen("libnvidia-ml.so.1")` | **均成功**（库本身完好） |
| `NVIDIA_VISIBLE_DEVICES` / `CUDA_VISIBLE_DEVICES` | **均未设置**（`env` 中无任何 nvidia/cuda 变量） |
| 宿主机 `/proc/driver/nvidia/gpus/*/information` | RTX 4090 正常，驱动 595.71.05，`GPU Excluded: No` |
| torch | 2.10.0+cu128，CUDA 12.8，`init()` → `RuntimeError: No CUDA GPUs are available` |

## 4. 已排除的原因（重要）

1. **不是用户态 Python 包导致的。** 失败点是对设备节点的内核级 `EPERM`，
   连 `nvidia-smi` 这个 C 程序都失败；`dlopen` 显卡库本身是成功的。
   pip 安装 Python 包不可能造成这种拒绝。
2. **不是容器重启导致的。** hostname 与 PID1 启动时间（05:27:36）在故障前后完全一致。
3. **不是驱动库缺失。** `libcuda.so.1`、`libnvidia-ml.so.1` 都在且可加载。
4. **不是显卡被拔掉。** 宿主机始终枚举到该 RTX 4090，`GPU Excluded: No`。

**最可能的解释**：该 pod（`kubepods-burstable` 服务质量等级）的 **GPU 设备分配或 device cgroup
放行规则在运行中被平台撤销/转移**。请平台说明为何在容器未重启的情况下收回设备权限。

## 5. 给平台支持的话术

> 实例 `ai-traininfer-a60eedc8-963ea058-f75578f6b-b4t8t`
> （pod `f34da95a-95aa-4eaf-80e6-3b8bd6a42115`，容器
> `5e12339147401e012ed5fdf63353f612a38dc6e627d58d1e4797bf49069d5c08`，申请 1×RTX 4090）
> 在 2026-10-11 05:37 UTC（容器启动约 10 分钟后）**CUDA 真实计算是正常的**：
> 2048×2048 fp32 矩阵乘法成功并同步取回结果。
> 但到 05:43 UTC，同一容器内 `/dev/nvidiactl` 等设备节点以 root 打开报
> `Operation not permitted`，`nvidia-smi` 报 `Failed to initialize NVML: Unknown Error`，
> `torch.cuda.is_available()=False`，此后 16 次重试均失败。
> `/dev/nvidia-caps` 未创建，`NVIDIA_VISIBLE_DEVICES` 未设置。
> **容器在此期间没有重启**，宿主机驱动 595.71.05 正常且仍能看到该卡。
> 请检查该 pod 的 GPU 设备与 device cgroup 权限为何在运行中被收回。

## 6. 此时容器里已经做好的准备（若重启同一实例可直接复用）

- 依赖已补装并**把锁定版本恢复原状**：`transformers==4.57.6`、`tokenizers==0.22.2`、
  `safetensors==0.7.0`、`huggingface_hub==0.36.2`；新增 `peft 0.21.2`、`accelerate 1.15.0`。
- `/mnt/storage/b2-a/`（200 GB cephfs 持久盘）已建好 `repo/weights` 与 `runs/`。
- **基础模型上传已完成并逐字节校验**：8/8 文件 SHA256 与 `weights/MANIFEST.json` **全部一致**，
  含 `model.safetensors` 988,097,824 B（sha256 `fdf756fa7fcbe7404d5c60e26bff1a0c8b8aa1f72ced49e7dd0210fe288fb7fe`）。
  过程：首次整目录 scp 被连接重置截断（远端只有 944,963,584 B、缺 3 个文件），
  改为**分片上传（19×50 MB）+ 逐片大小校验 + 合并后整体 SHA256 比对**后通过。
- **官方原始数据与全套代码已上传**（资源包 80.35 MB，`b2a-assets.tar`，SHA256 `07fc10cc…`），
  解包到 `/mnt/storage/b2-a/repo`（266 文件）：
  `train_public.jsonl` `184a4747…`、`val_public.jsonl` `097c0639…` 与本机逐字节一致。
- **官方数据整理已在容器内复现**（纯 CPU，不需要 GPU）：200 训练 / 60 验证、
  16 类情绪每类 12–13 条，拒绝原因 `{顺序异常 4, 参考答案出现在输入里 30}`，
  产出 `train.jsonl` `93933f04…`、`valid.jsonl` `abecf3fc…` **与本机交付样本逐字节相同**；
  `tests/model/test_official_sampling.py` 自检 PASS。
- 容器内已写入就绪说明 `/mnt/storage/b2-a/README-状态.md`。

**遗留依赖问题（需报 B 核对）**：本轮为装 `peft/accelerate` 曾临时拉入 `datasets 5.1.0`，
它要求 `huggingface-hub>=1.31`，与已恢复的 `huggingface_hub 0.36.2` 冲突。
`datasets` **本次训练并未使用**（数据直接读 JSONL），建议从锁定清单中排除或改用它版。

## 7. 卡时与花费

- 实例存活期间约 **40 分钟**（05:27:36 启动 → 06:06 最后一次探测；其后交用户控制台关机），
  其中 GPU 真正可用约 **10 分钟**（05:27–05:37）。
- 关机前最后一次复查（06:06:42 UTC）**仍不可用**：`Failed to initialize NVML: Unknown Error`、
  `open("/dev/nvidiactl") EPERM`、`torch.cuda.is_available()=False`。
- **实际训练卡时消耗 = 0**：未开始任何训练，GPU 被收回前只做了一次 2048³ 矩阵验证。
- 上传消耗的是本机上行带宽与实例存活时间，不是训练卡时。

## 8. 原始证据文件

完整逐项原始输出（含命令与回显）已同时保存在：

- 容器内：`/mnt/storage/b2-a/evidence/gpu-revocation-evidence.txt`
- 本机：`reports/model/gpu-evidence/gpu-revocation-evidence.txt`