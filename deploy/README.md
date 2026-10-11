# B6 独立打包与禁网 GPU 验证

截至 2026-10-11，准备工具专项检查 79 项通过，完整基线包已生成并核验：本地 `D:/B2-B6-20261011/candidate-a34f8df`，清单 30 个文件、合计 999,760,049 字节。这个数字是包内清单文件总量，不是 Docker 镜像或导出 tar 的大小。**正式 Docker GPU 禁网验证尚未完成，B6 仍有环境阻塞。**

平台独立项目目录中的 Docker daemon 能启动，也能导入最小 Bash 镜像，但容器启动因只读 cgroup 失败；备用 runc 探测使用单次 `--no-new-keyring` 参数后仍因挂载 `/proc` 的 EPERM 失败。本机没有可用 Docker/WSL。平台两张 4090 的 CUDA 小矩阵运算、`unshare -n` 成功均只证明各自的能力，不能合并成同镜像禁网 GPU 推理成功。原始记录见 [平台能力探测](../reports/integration/b6-cloud-capabilities.json)。继续验证需要提供允许启动 GPU Docker 容器的 Linux 环境，无需等待 A/C 新实现。

## 文件与候选环境

- `prepare_bundle.py`：准备/校验完整包；不下载、不安装依赖、不加载模型。
- `Dockerfile`、`requirements-gpu.txt`：候选配方。公开 PyTorch Linux amd64 基础镜像固定为 `pytorch/pytorch@sha256:417bd75df6365104c283ea4c1651fb3530d9eb5a4c2fafa51943cff2a94e6385`，标签来源为 `2.8.0-cuda12.8-cudnn9-runtime`；来源记录见 [base-source.json](base-source.json)。四个直接依赖为 Transformers 5.19.0、Accelerate 1.12.0、Pydantic 2.14.0、jsonschema 4.26.0。它们尚不是经过实际 GPU 验证的依赖锁；传递依赖由构建时解析，真实 freeze/conda explicit 由成功构建保存。
- `runtime_probe.py`：在激活的 `conda_env` 中核对依赖/包摘要，并在每张可见 GPU 上实际分配、执行 CUDA matmul、同步；它自身不验模型推理或容器网络。
- `verify_container.py`：构建镜像，以实际 image ID 依次进行 GPU 探测、官方入口推理、独立输出校验和 Docker save，汇总真实证据。

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
4. 保存同一 image ID 的标准 `docker save` tar，核对归档配置摘要仍对应该 ID，并记录 tar SHA256。

公开三条输入会全量生成，但前 100 条计时口径使其 `rounds=3`、`complete=false`；这不是三条生成失败，也不提供官方得分。详见 [B5 入口说明](../submission/participant/README.md)。

## 3. 判定与保留证据

只有上述各步实际成功，CLI 才返回 0，并在 `--work/verification.json` 中将 `gpu_offline_verified`、`fallback_image_verified` 设为 true；失败返回 1并保留失败原因/已有日志。工作目录已存在会直接拒绝，请换新目录，不覆盖先前证据。

工作目录保存构建日志、实际 image ID、各容器 inspect/退出状态与日志、`probe/runtime.json`、`result/submission.jsonl`、`result/performance_report.json`、最终 `verification.json`，以及成功后的 `fallback-image.tar`。构建镜像内另保存 `/opt/b2-evidence/requirements.actual.txt` 与 `conda.actual.txt`。只清理本次创建的容器，镜像和证据保留。

image ID、registry RepoDigest、导出 tar SHA256 是不同标识；本地构建没有 RepoDigest 时记录空列表，不编造 registry 地址。团队保守预算要求 Docker inspect Size 和导出 tar 都 **小于 50,000,000,000 字节**；这是内部预算，不代表官方已明确“50G”的计量口径。基础镜像压缩层总量、完整包大小都不能代替这两个实际测量值。

当前尚无通过验收的参赛 GPU 镜像/导出回退。继续保留 [B5 已验证的 CPU 开发回退](../reports/integration/B5验收.md)，其范围为真实公开样例 Python 离线推理，不冒充禁网 GPU Docker 验证。此流程不上传赛事，不进入 B7；`official_score_verified`、`contest_submitted` 始终为 false。
