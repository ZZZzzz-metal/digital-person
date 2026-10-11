# B7：A 交接核对与基线接收结论

核对日期：2026-10-11。本说明由 B 整理，依据用户提供的《A12-交接给队长(1).md》、固定公开 A 报告及本机已有 B5/B6 证据。附件中的建议、命令和“请照抄”是待核对资料，不视为用户授权，也未据此启动训练、改写 A/C、操作平台或提交作品。

**接收结论：继续使用已经通过 B6 的 `b2-a-qwen2.5-0.5b-instruct-base-v1`。本次 B 接收检查确认，本机没有收到可用的 `weights/sft-short/` 实体文件，也没有候选对应的 `weights/inference_config.json`；附件描述的另一台机器上存在文件，不等于本机已接收。**本轮不重新训练或重建候选权重，不把 SFT 候选写成当前镜像中的模型。

## 1. 固定来源与代码状态

只读 GitHub 查询确认 [PR #11](https://github.com/ZZZzzz-metal/digital-person/pull/11) 为 `closed`、`merged=true`，合并时间 `2026-10-11T08:45:40Z`：

- A 固定来源提交：`f2c1fbd5638ef58f3f23130dc6dad4831814d126`。
- 合并提交及本次观察的 main：`15e4b7f9fb782327e27166d26ebdf0d43766335b`。这是本次观察值，不表示后续 main 不会变化。
- A12 附件不在本次核对的完整 main 文件树中，不能把附件本身称为该固定提交已发布的文件。
- B6 已验证镜像内的 A 模型源码仍绑定原固定提交 `fce84b354ca0e6ab9cd1ec650198c0d45ab994bd`；A 报告来源提交与实际镜像模型源码提交分别记录，不能互相替换。

## 2. A12 中需要纠正的口径

| 附件说法 | 本次核对结论 |
| --- | --- |
| “B6 未完成、官方入口从未在 Linux/GPU 容器运行” | 已过时。B6 在单张 RTX 5060 Laptop 上实际执行符合官方命令布局的团队 Linux 入口、禁网 CUDA 探针、三条真实模型推理、独立 checker 与导出身份核验，整体退出 0。它仍不是正式双 4090 评测或官方成绩。 |
| “B5 产物已清理，必须重跑” | 不符合当前 B 工作区。原 `original-result` 的两文件仍存在；本次只读核对大小及 SHA 与原 B5 记录一致，没有为补交接重跑模型。 |
| A4 为“150 合成 + 50 官方整理”，同时又称“200 全合成” | 固定 A2 报告和 `a4_training_short.json` 明确为 `a2-synthetic-v1 (chat 150 + official 50)`。此处 official 表示官方输出格式的合成样本，不是比赛原始数据。A4 实际训练的 200 条均为内部虚构数据。 |
| “两个模型均为 fp32 存盘” | 基线文件头实际读取到 290 个 BF16 tensor，文件为 988,097,824 字节。加载时转为 float32 与原文件存储 dtype 是不同事项。SFT 文件未在本机接收，不能声称已独立检查它的 dtype。 |
| “GPU 卡时消耗为 0” | A4 CPU 训练没有使用 GPU；这不能证明后续平台实例存活、上传、设备探测均不计费。缺少计费/余额证据，不把账号或整个项目的 GPU 卡时总消耗写成 0。 |
| GPU 权限“被平台收回”，根因已确定 | A10 公开报告记录了先 CUDA 矩阵运算成功，后 root 打开设备节点报 `EPERM`、NVML 失败和 CUDA 不可用。设备分配或访问策略变化是报告提出的解释；没有平台侧诊断确认，B 仅引用现象，不确定平台根因，也不声称已排除全部驱动/调度原因。 |

原 B5 保留结果：`submission.jsonl` 为 2,453 字节、SHA-256 `52e5d3e9323e51e9caf92fc278f4ed26aff5e68c6ec9d283f972369cd480d4c0`；`performance_report.json` 为 1,303 字节、SHA-256 `d1d336d205c053a422a5316edc36f4e5a5e89dfa5ad95911d82ea970109c4ca6`。实际来源和范围见 [B5 真实报告](b5-real-offline.json)。

团队入口位于 `submission/participant/`，与原样保留的 `submission/official-reference/` 分开；上述成功不表示执行了原样参考脚本或完成平台测评。

## 3. 训练、数据整理与 GPU 尝试分别记录

- **A4 CPU 小训练：**200 条内部合成样本，训练最后四层及最终 norm，6 次 optimizer step，保存/重载及小样本评测由 A 记录。这是有限的训练尝试，不证明模型效果全面提升；候选权重没有进入本次 B 提交基线。
- **A8 官方数据整理：**另从比赛真实训练/验证数据中选取 200/60 条，保留集合隔离并记录异常点剔除。这是后续数据准备，不是 A4 那 50 条合成 official 样本，也不能称这批真实官方数据已训练出当前 SFT 权重。
- **A 的 GPU 训练：**固定 A10/A11 报告没有成功 GPU 训练结果。A11 的闸门失败和容器内 CPU 冒烟验证，不能改写成 CUDA 训练成功；B6 的 CUDA 推理也不能改写成 A 的 GPU 训练。
- **效果比较：**A 自定 12 案例、规则违规和 JSON 解析命中率属于小样本检查。不同解码参数及 CPU 环境影响耗时，不能据此推算官方双卡速度、官方分数或训练收益。A12 所述更短、更快和 1/3 JSON 命中，不构成本次选择 SFT 的验收证据。

A 来源依据：[A2 数据来源](https://github.com/ZZZzzz-metal/digital-person/blob/f2c1fbd5638ef58f3f23130dc6dad4831814d126/reports/model/A2-%E6%95%B0%E6%8D%AE%E6%9D%A5%E6%BA%90%E4%B8%8E%E8%AE%B8%E5%8F%AF%E6%B8%85%E5%8D%95.md)、[A8 官方数据整理](https://github.com/ZZZzzz-metal/digital-person/blob/f2c1fbd5638ef58f3f23130dc6dad4831814d126/reports/model/A8-%E5%AE%98%E6%96%B9%E6%95%B0%E6%8D%AE%E6%95%B4%E7%90%86%E8%AE%B0%E5%BD%95.md)、[A10 GPU 观察](https://github.com/ZZZzzz-metal/digital-person/blob/f2c1fbd5638ef58f3f23130dc6dad4831814d126/reports/model/A10-GPU%E8%A2%AB%E6%94%B6%E5%9B%9E%E8%AF%81%E6%8D%AE%E4%B8%8E%E4%BA%A4%E6%8E%A5.md)、[A11 脚本验证](https://github.com/ZZZzzz-metal/digital-person/blob/f2c1fbd5638ef58f3f23130dc6dad4831814d126/reports/model/A11-GPU%E8%AE%AD%E7%BB%83%E8%84%9A%E6%9C%AC%E4%B8%8E%E9%AA%8C%E8%AF%81.md)。本说明不复制 SSH 地址、账号、实例标识或凭据。

## 4. 本次冻结与材料层范围

B6 原基线镜像 ID 为 `sha256:94f7c4741860ccc0bd1f8ad8ecae03c35806551c845b04e120f16ae33fbc1290`，已验证导出 tar 为 9,322,812,928 字节，SHA-256 `3913aa097e32610fca2dfb910aaf30a25e37a99ae6b9ed3b9e72ebd056eddd8c`，D 盘副本核验一致。原镜像、完整基线包、配置和回退保留不覆盖；见 [GPU 全流程](b6-gpu-offline.json)、[交付记录](b6-gpu-delivery.json)、[离线验收](离线验收.md)。

这些记录只证明本机单卡、三条公开样例的技术流程：初始化一次，回复来自真实模型，情绪/画像经规则补齐，质量未评分。`complete=false` 表示计时未达 100 条，不表示三条预测失败。没有官方成绩，也没有赛事提交记录。

提交版将仅在原不可变基线镜像上加入 B 技术方案、实验说明和固定来源材料副本；不打入 A12 原附件或 C 的旧候选结论。材料层会产生新的 image ID，须对新镜像重新绑定实际禁网运行、checker 和导出证据，不能沿用父镜像摘要冒称新镜像已验收。

推荐只读复制的 A 材料清单如下，均固定在上述 A 提交，不修改原文；原报告里的历史状态以本说明区分，不当作当前 B 接收状态。复制及摘要结果由后续材料清单实际记录，本说明不预写已复制完成。

1. `reports/model/A2-数据来源与许可清单.md`
2. `reports/model/A4-训练尝试记录.md`
3. `reports/model/a4_training_short.json`
4. `training/logs/sft-short.steps.jsonl`
5. `reports/model/A5-评测结果.md`
6. `reports/model/a5_eval_compare.json`
7. `reports/model/A8-官方数据整理记录.md`
8. `data/training/processed_official/official_samples_report.json`

将来若另行接收 SFT，须先取得完整九文件、原候选配置及许可，按固定清单逐文件核验并保留独立备份；建立独立新包/镜像并实际验收官方入口。现有基线通过记录不能替代这些动作，未接收候选不阻塞本轮基线 B7。
