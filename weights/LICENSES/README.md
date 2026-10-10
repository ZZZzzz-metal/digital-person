# 许可与来源清单

本目录只放**许可与来源说明**，不放权重本身。权重是大文件，不进 Git。

## 1. 基础模型：Qwen2.5-0.5B-Instruct

| 项 | 内容 |
| --- | --- |
| 来源 | https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct |
| 本地目录 | `weights/base-qwen2.5-0.5b-instruct/` |
| 许可 | Apache-2.0，全文见 [Qwen2.5-0.5B-Instruct-LICENSE.txt](Qwen2.5-0.5B-Instruct-LICENSE.txt) |
| 参数 | 494,032,768，fp32，`model.safetensors` 988,097,824 B |
| 下载方式 | 一次性完整下载后离线使用；运行时不联网，`local_files_only=True` |

## 2. 候选模型：b2-a-qwen2.5-0.5b-instruct-sft-short-v1

| 项 | 内容 |
| --- | --- |
| 本地目录 | `weights/sft-short/` |
| 来源 | `training/train_sft.py` 在基础模型上的小规模本地适配产物 |
| 许可 | 沿用 Apache-2.0（基础模型许可），见上一节全文 |
| 改动范围 | 只训练最后 4 层 Transformer 与最终 norm（59,650,432 / 494,032,768 参数），其余与基础模型逐位一致 |
| 保存形式 | 完整 fp32 全量权重 + config + tokenizer，**不依赖任何适配器库**，可直接当普通模型加载 |

> 因为这个候选模型是基础模型的衍生品，它的分发同样受 Apache-2.0 约束；
> 分发时请连同本目录一起带上。

## 3. 训练数据

| 项 | 内容 |
| --- | --- |
| 文件 | `data/training/raw/sessions.jsonl` |
| 生成方式 | `data/training/make_synthetic_sessions.py`（固定种子，确定性可复现） |
| 内容 | 200 个**虚构**会话，人物均为虚构（小然/小林/小舟/小雨/阿哲/小满） |
| 许可 | 内部虚构数据，可自由用于本项目；**不含任何真实个人信息** |
| 重要说明 | 不是真人语料，不是访谈记录，**也不是比赛官方训练数据** |

处理后数据在 `data/training/processed/`，由 `data/training/build_dataset.py` 生成，
来源与限制见 `data/training/SOURCES.md`。

## 4. 评测数据

| 项 | 内容 |
| --- | --- |
| 文件 | `data/eval/cases.json` |
| 来源 | A 手写的 12 个固定案例（MT1–MT6 多轮、BD1–BD6 边界） |
| 许可 | 内部自建，可自由使用；不含真实个人信息 |
| 说明 | 不参与训练；只用于基线与候选的同口径对比，**不等同官方评分** |

## 5. 官方参考材料

| 项 | 内容 |
| --- | --- |
| 目录 | `submission/official-reference/` |
| 来源 | 比赛方提供的公开推理输入与输出 schema |
| 许可 | 赛事方材料，按赛事规则使用 |
| 说明 | A 只读不改；公开测试样本的 `memory_refs` 必须为空数组 |

## 6. 第三方依赖

A 一侧**没有引入任何新的第三方依赖**。用到的都是环境里已有的：
`torch 2.14.1+cpu`、`transformers 5.19.0`、`safetensors`、`numpy`。
标准库之外没有新增包，因此不需要 B 额外加锁。细节见
`reports/model/A7-最终报告.md` 的「依赖与锁文件」一节。