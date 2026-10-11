# B6 独立打包与禁网 GPU 验证

2026-10-11 已完成本机单 RTX 5060 Laptop 的 B6 禁网 GPU Docker 验收：同一镜像执行 CUDA 探针、三条官方样例推理和独立校验，均退出 0，随后成功导出并核验归档。专用 WSL `B2-B6-Ubuntu22` 的磁盘位于 D 盘，Docker 为 29.9.0；本次不是正式双 4090 评测、训练或质量评分，也未提交比赛。

| 已验证交付 | 实际值 |
|---|---|
| 不可变 image ID（OCI index） | `sha256:94f7c4741860ccc0bd1f8ad8ecae03c35806551c845b04e120f16ae33fbc1290` |
| Docker inspect Size | 25,969,069,324 字节 |
| 回退归档 | `D:/B2-B6-20261011/gpu-verified-20261011T050300Z/fallback-image.tar`，9,322,812,928 字节 |
| 归档 SHA-256 | `3913aa097e32610fca2dfb910aaf30a25e37a99ae6b9ed3b9e72ebd056eddd8c`；D 盘副本已核对 |
| 推理 | 3 条全部输出，模型初始化一次，平均 8,890.429456 ms；`rounds=3`、`complete=false` |
| 全流程 | 2026-10-11 13:00:44–13:04:26 北京时间，231.688 秒 |

完整包仍为 `D:/B2-B6-20261011/candidate-a34f8df`，30 个清单文件、999,760,049 字节；此数值不是镜像/归档大小。三条回复来自真实模型，每条两次 JSON 解析失败后 A 使用 `fallback_rules` 补齐情绪/画像。实际报告见 [GPU 验收](../reports/integration/b6-gpu-offline.json)、[逐样本来源](../reports/integration/b6-gpu-samples.json)、[D 盘交付](../reports/integration/b6-gpu-delivery.json)。

此前云端两张 4090 的 CUDA 运算成功，但嵌套 Docker 因只读 cgroup、备用 runc 因 `/proc` 挂载权限失败；这些历史没有改为镜像通过。随后本机安装、重启、DNS 与容器运行环境已实际解决，见 [历史平台记录](../reports/integration/b6-cloud-capabilities.json) 和 [本机续做](../reports/integration/B6-本机环境续做.md)。用户通常只需合并、拉取 PR，下面的命令用于需要自行复现时。

## 文件与候选环境

- `prepare_bundle.py`：准备/校验完整包；不下载、不安装依赖、不加载模型。
- `Dockerfile`、`requirements-gpu.txt`：已实际构建的配方。公开 PyTorch Linux amd64 基础镜像固定为 `pytorch/pytorch@sha256:417bd75df6365104c283ea4c1651fb3530d9eb5a4c2fafa51943cff2a94e6385`，标签来源为 `2.8.0-cuda12.8-cudnn9-runtime`；见 [base-source.json](base-source.json)。实测 Python 3.11.13、Torch 2.8.0+cu128、Transformers 5.19.0、Accelerate 1.12.0、Pydantic 2.14.0、jsonschema 4.26.0，`pip check` 成功。四个直接版本由配方固定，传递依赖构建时解析；[pip 实际清单](requirements-gpu.actual.txt) 与 [conda 实际清单](conda-gpu.actual.txt) 是冻结镜像的观察元数据，含上游 `file:///` 构建路径，不能当作独立 `pip install -r` 重装锁。来源与摘要见 [环境记录](../reports/integration/b6-gpu-environment.json)。
- `runtime_probe.py`：在激活的 `conda_env` 中核对依赖/包摘要，并在每张可见 GPU 上实际分配、执行 CUDA matmul、同步；它自身不验模型推理或容器网络。
- `verify_container.py`：构建镜像，以实际 image ID 依次进行 GPU 探测、官方入口推理、独立输出校验和 Docker save，汇总真实证据。
- `saved_image.py`：只读核验经典或 OCI 归档的镜像身份链和实际字节，不导入或启动镜像；归档专项与容器风险检查共 63 项通过，另计于先前 79 项准备检查。

构建阶段需要访问公开基础镜像和依赖来源；模型文件已经在本地，不在构建或运行时下载。运行容器统一使用 `--network none`，GPU 探测/推理另加 `--gpus all`。镜像固定保留 `conda_env` 和 `bash /root/participant/start.sh TEST_FILE RESULT_DIR`，通过 `B2_OFFICIAL_MODEL_CONFIG` 选择包内原配置。

## 1. 准备完整包

复用已取得的 B 仓库、经摘要核验的 A 源码交接副本，以及完整基线资产/交接清单。打包宿主需要 Python 3.10+ 和项目声明的 jsonschema；无需 GPU 或 Torch。以下 Linux 路径是迁移后的示例，先对应替换为已有资料的位置，在 B 仓库根目录执行：

```bash
python deploy/prepare_bundle.py prepare \
  --project-root . \
  --a-source-root /work/handoff/upstream-A \
  --source-manifest-path /work/handoff/prerequisite.json \
  --asset-root /work/handoff/real-assets \
  --asset-manifest-path /work/handoff/real-assets/asset-preparation.json \
  --output-dir /work/b2/candidate-new

python deploy/prepare_bundle.py verify /work/b2/candidate-new
```

`a-source-root` 是含 `src/` 的目录。源码清单需有完整 `main_sha`、`A_readonly_review_copies` 逐文件路径/SHA256/字节数；资产清单需有八份模型文件的 `files`，以及 `baseline_config.sha256`、`license_copy.sha256`。缺 Git 元数据的 B 源码副本须另传 `--source-commit`，值为实际 B 来源的完整 40 位提交 SHA。已有仓库默认只读 Git 元数据取得该值，不执行拉取或切换。

当前工具固定打包基础模型的八份文件：`config.json`、`generation_config.json`、`LICENSE`、`merges.txt`、`model.safetensors`、`tokenizer.json`、`tokenizer_config.json`、`vocab.json`。原 A 实现、`weights/inference_config.base.json`、其相对 `model_dir`、许可副本均按原字节保留，不改设备/精度/生成配置。此固定基线工具不支持把 LoRA、分片或索引作为替代资产。

输出目录必须不存在。工具先核验来源，再在自有临时目录复制并复验，成功后发布新目录；拒绝缺失、摘要不符、路径逃逸、链接、重复及额外文件。`bundle_manifest.json` 绑定 B/A 提交、模型版本和各文件摘要，清单本身不计入 30 个文件。校验成功仅证明完整性与布局，不证明模型效果或 GPU 能运行。

## 2. 在可用 GPU Docker 环境执行

需要 Linux amd64 Docker daemon、已配置的 NVIDIA 容器运行支持，以及可用 NVIDIA GPU。输入/结果/工作目录必须位于 Docker daemon 可访问的本机文件系统，结果挂载须支持 B5 的硬链接发布。工具检查至少一张可见 GPU，并验证所有可见卡；正式评测配置为两张 4090、每卡标称 24G，工具通过不能换算正式成绩。

把已核验包和现有 B 部署工具复制到该环境，仍在 B 仓库根目录执行；`--work` 必须是新目录，示例使用原始公开三条 JSONL 输入：

```bash
python deploy/verify_container.py \
  --bundle /work/b2/candidate-new \
  --test-file submission/official-reference/test_inference_data.jsonl \
  --work /work/b2/verify-new \
  --tag b2-candidate:b6
```

CLI 只有 `--bundle`、`--test-file`、`--work` 三个必填项，`--tag` 默认 `b2-candidate:b6`。它会先复验包，创建构建上下文并构建固定配方，无需手工修改包或 A 配置。构建成功后，所有运行使用得到的不可变 image ID，后续不再以可变标签选择镜像：

1. 禁网 GPU 容器激活 `conda_env`，核验包清单摘要、实际依赖与每张可见卡的 CUDA 内核。
2. 同镜像禁网 GPU 容器通过固定官方入口生成全量结果，只挂载只读输入及新结果目录。检查实际推理进程报告 CUDA、非 mock、模型版本、单次初始化和逐样本真实模型事件。
3. 同镜像禁网校验容器独立重读输入/输出、schema、ID 顺序/数量、摘要及性能字段；此校验不需要 GPU，也不加载模型。
4. 保存同一 image ID 的标准 `docker save` tar，核对归档完整身份链与 tar SHA256。经典镜像的 ID 对应 config 摘要；containerd 的 ID 可对应 OCI index/manifest，需从该 ID 找到唯一 linux/amd64 manifest，再核验 config、全部 layer 摘要及解压后的 diff_ids。运行容器实际 manifest 描述符也必须与归档一致，不能把 index ID 当作 config 摘要。

公开三条输入会全量生成，但前 100 条计时口径使其 `rounds=3`、`complete=false`；这不是三条生成失败，也不提供官方得分。详见 [B5 入口说明](../submission/participant/README.md)。

## 3. 直接复现本机已验证镜像

本机专用发行版与该镜像已经存在，无需重新安装或构建。收尾已清理三个验收容器并停止专用发行版，释放空闲资源，环境和镜像保留；见 [本机清理记录](../reports/integration/b6-local-cleanup.json)。先在 PowerShell 打开专用 Linux 终端，systemd 会启动已安装的 Docker：

```powershell
wsl.exe --distribution B2-B6-Ubuntu22 --user root
```

在该 Linux 终端完整复制以下命令。输入路径对应本项目 checkout；若仓库位置不同，只改 `B2_INPUT` 这一行的路径。新工作目录位于专用发行版的 ext4 文件系统（其虚拟磁盘在 D 盘），避免将 Windows `/mnt/c` 或 `/mnt/d` 的结果目录直接绑定而影响硬链接发布。输入先复制，结果目录始终新建；不挂载外部模型覆盖镜像内容。

```bash
set -euo pipefail
B2_INPUT=/mnt/c/Users/20964/Documents/ChatGPT/MC/digital-person-b0/submission/official-reference/test_inference_data.jsonl
B2_IMAGE=sha256:94f7c4741860ccc0bd1f8ad8ecae03c35806551c845b04e120f16ae33fbc1290
docker image inspect "$B2_IMAGE" >/dev/null
B2_RUN=$(mktemp -d /root/b2-b6/runs/manual-XXXXXXXX)
cp -- "$B2_INPUT" "$B2_RUN/input.jsonl"
mkdir "$B2_RUN/result"
docker run --rm --network none --gpus all \
  --mount "type=bind,source=$B2_RUN/input.jsonl,target=/b2-input.jsonl,readonly" \
  --mount "type=bind,source=$B2_RUN/result,target=/b2-result" \
  "$B2_IMAGE" /b2-input.jsonl /b2-result
docker run --rm --network none \
  --entrypoint /opt/conda/envs/conda_env/bin/python \
  --mount "type=bind,source=$B2_RUN/input.jsonl,target=/b2-input.jsonl,readonly" \
  --mount "type=bind,source=$B2_RUN/result,target=/b2-result,readonly" \
  "$B2_IMAGE" /root/participant/check_output.py /b2-input.jsonl /b2-result
printf '结果目录：%s\n' "$B2_RUN/result"
```

第一个容器自动激活 `conda_env` 并生成 `submission.jsonl`、`performance_report.json`；第二个容器只读独立校验。此命令复用本机缓存的不可变镜像，不是从 D 盘归档恢复；本次未执行 `docker load` 后重跑，不能称恢复复验通过。原始归档、日志和结果继续保留，不覆盖。

## 4. 判定与保留证据

只有上述各步实际成功，CLI 才返回 0，并在 `--work/verification.json` 中将 `gpu_offline_verified`、`fallback_image_verified` 设为 true；失败返回 1并保留失败原因/已有日志。工作目录已存在会直接拒绝，请换新目录，不覆盖先前证据。

工作目录保存构建日志、实际 image ID、各容器 inspect/退出状态与日志、`probe/runtime.json`、`result/submission.jsonl`、`result/performance_report.json`、最终 `verification.json`，以及成功后的 `fallback-image.tar`。构建镜像内另保存 `/opt/b2-evidence/requirements.actual.txt` 与 `conda.actual.txt`。只清理本次创建的容器，镜像和证据保留。

本次 OCI index ID 为上面的 `94f7…`，三个实际容器均对应 linux/amd64 manifest `sha256:70cddf121d9b5d756a38086af9f4447f3a4cb37fc6ed706b1200a63645bb4312`，config 为 `sha256:9377c287feb1f31f350529174f6f3af9b769a402a265c5d75a1c60eefcd150a3`。归档核验了 17 个唯一 blob，包括 attestation 引用与重复层，详见 `save_tar_identity`。

image ID、registry RepoDigest、导出 tar SHA256 是不同标识；本次 `b2-candidate@sha256:94f7…` 是本地 Docker 构建元数据，不表示已上传远程 registry。本地构建没有 RepoDigest 时记录空列表，不编造地址。实测 inspect Size 与 tar 均小于团队保守预算 **50,000,000,000 字节**；这是内部预算，不代表官方已明确“50G”的计量口径。基础镜像压缩层总量、完整包大小都不能代替这两个实际测量值。

当前已有实际禁网运行的 GPU 候选镜像与同 ID 的已核验导出回退，D 盘副本 SHA 一致；尚未从归档重新导入并运行。另保留 [B5 CPU 开发回退](../reports/integration/B5验收.md) 和 [B6 CPU 独立包记录](../reports/integration/b6-bundle-cpu-smoke.json)。本轮没有需人处理的 B6 环境阻塞；用户手动合并、拉取 PR 后按需复现。此流程不上传赛事，不进入 B7，`official_score_verified`、`contest_submitted` 为 false，三条样例的 `complete=false` 保留原值。
