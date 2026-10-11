# 权重与数据清单

生成时间：2026-10-11 11:29:25

## 权重包

| 包 | 路径 | 文件数 | 总大小 | 整包 sha256 |
| --- | --- | --- | --- | --- |
| base-qwen2.5-0.5b-instruct | `weights/base-qwen2.5-0.5b-instruct` | 8 | 953.3 MB | `bde887b1b7f886734663eda9c79fd2b1bba7e5c452af3342c1de4cfc59b545fe` |
| sft-short | `weights/sft-short` | 9 | 1.9 GB | `35bf0a2226babf58b4c8e392cde83e8a9150d2d2cfc9341407df836251fad2fd` |

### 逐文件明细

#### base-qwen2.5-0.5b-instruct

| 文件 | 大小 | sha256 |
| --- | --- | --- |
| `config.json` | 659 B | `18e18afcaccafade98daf13a54092927904649e1dd4eba8299ab717d5d94ff45` |
| `generation_config.json` | 242 B | `e558847a8b4402616f1273797b015104dc266fe4b520056fca88823ba8f8ebe6` |
| `LICENSE` | 11.1 KB | `832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e` |
| `merges.txt` | 1.6 MB | `599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3` |
| `model.safetensors` | 942.3 MB | `fdf756fa7fcbe7404d5c60e26bff1a0c8b8aa1f72ced49e7dd0210fe288fb7fe` |
| `tokenizer.json` | 6.7 MB | `c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539` |
| `tokenizer_config.json` | 7.1 KB | `5b5d4f65d0acd3b2d56a35b56d374a36cbc1c8fa5cf3b3febbbfabf22f359583` |
| `vocab.json` | 2.6 MB | `ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910` |

#### sft-short

| 文件 | 大小 | sha256 |
| --- | --- | --- |
| `config.json` | 659 B | `18e18afcaccafade98daf13a54092927904649e1dd4eba8299ab717d5d94ff45` |
| `generation_config.json` | 242 B | `e558847a8b4402616f1273797b015104dc266fe4b520056fca88823ba8f8ebe6` |
| `LICENSE` | 11.1 KB | `832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e` |
| `merges.txt` | 1.6 MB | `599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3` |
| `model.safetensors` | 1.8 GB | `6fb4dd30f4f2714811c4b612c40fc4d46348eb67debbf2cfde5ade2a63541985` |
| `tokenizer.json` | 6.7 MB | `c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539` |
| `tokenizer_config.json` | 7.1 KB | `5b5d4f65d0acd3b2d56a35b56d374a36cbc1c8fa5cf3b3febbbfabf22f359583` |
| `training_meta.json` | 1.5 KB | `7b1a8543e14c19eb2f2845efb8b98d36d670c27d3f3f71e64f8de2b23e8b911d` |
| `vocab.json` | 2.6 MB | `ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910` |

## 数据文件

| 文件 | 大小 | sha256 |
| --- | --- | --- |
| `data/training/raw/sessions.jsonl` | 273.4 KB | `327a2e34229543f4cc52a5257a6928eeb66317970bd31e196dc651e19a111d99` |
| `data/training/processed/train.jsonl` | 202.9 KB | `ffe527ad4cf6037cbe27a31413c4704219406560b05297e9c3906210b6ddf2eb` |
| `data/training/processed/valid.jsonl` | 121.4 KB | `83caaa2f3d3dae8ce39e719a4cd83962360335326bbe0490883ec1692039cb17` |
| `data/training/processed/holdout.jsonl` | 71.5 KB | `b82f177199858ef359bd4e6e529311011aa8919a2caad727091d6300de17af30` |
| `data/training/processed/dataset_report.json` | 1.9 KB | `b5816e6172cea1d4caeacb469dd220fae48ac3747110d7f199eef807dd9bb894` |
| `data/eval/cases.json` | 18.4 KB | `d3c247631a9bb1fe6355824fc64c3cdb07ee158664fe06a2b4f13da3c82a1220` |
| `weights/inference_config.json` | 1.3 KB | `c40a9468d11a7e0d4a4d282037c655b8333304d1019a6753efaae257b0a6f22b` |

## 关键源码

| 文件 | 大小 | sha256 |
| --- | --- | --- |
| `src/b2_core/model.py` | 24.7 KB | `9aeabec0536f706464d9b2616c108a18bb3a5cd7dc6b3503b3944a5441c5b7f6` |
| `src/b2_core/a_impl/dtos.py` | 16.6 KB | `b94b8205a96ab162b8dedf68b40f70cade642cbc756d167b7faee831772fc778` |
| `src/b2_core/a_impl/official_spec.py` | 9.5 KB | `99392294c04b53359111fb12555779fea3111cdb77f59c9e10a3ed762d73a9b8` |
| `src/b2_core/a_impl/local_llm.py` | 12.6 KB | `ca4e189cacd464c0d66cdae3b81812e7ca78dea219053ceab6596ce5c3b14896` |
| `src/b2_core/a_impl/emotion_rules.py` | 8.2 KB | `4a87f7bc61665cd51b0d692d47758bc991c2f7d8b9fdc712811abdb739075854` |
| `src/b2_core/prompts/empathy.py` | 3.9 KB | `2b4c91e5466b49809cb47d40d1bdc3ea528de2646bf909c33fc530f5dd6b09a4` |
| `training/train_sft.py` | 25.3 KB | `1d94a26eb6553a4d95bd5cbf65a755834723207d2d8039b63ecc3c1890a11af9` |
| `training/model_config.json` | 1.2 KB | `60000abaca1b0f64d28f58ad0c8e8bd13a3af0fb6720e5bb4da153f4768b945b` |
| `data/training/build_dataset.py` | 14.6 KB | `ad436e31777c887c02a94f8acc3b992ae2f172fd0eebd3b3308e868d7eedf069` |
| `data/training/make_synthetic_sessions.py` | 57.7 KB | `84c74b8fa8059e0736dc9bd3be3a1be20a592d12065c48112082a0eeb6935977` |
| `tests/model/run_eval.py` | 17.8 KB | `fab7c359c6326ffa9de36b3c0b144228c430fd697cbd58519d6c32a9be6da7c0` |
| `tests/model/smoke_official.py` | 9.4 KB | `ea365fe3fcb1436a7162a59f20c1202ce923866fa1c522bfa9191bede62062de` |
| `tests/model/check_memory_effect.py` | 7.3 KB | `523538774d55b9c418eaee9cd16522c73105fda74f14f3f47d8226c39bc0b9dc` |

## 许可与来源

| 对象 | 来源 | 许可 |
| --- | --- | --- |
| base_model | https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct | Apache-2.0 |
| candidate_model | 本仓库 training/train_sft.py 在 Qwen2.5-0.5B-Instruct 上的小规模本地适配产物 | Apache-2.0（沿用基础模型许可） |
| training_data | 本仓库 data/training/make_synthetic_sessions.py 自动生成的虚构对话 | 内部虚构数据，不含任何真实个人信息 |
| eval_data | A 手写的 12 个固定案例（MT1–MT6、BD1–BD6）、 | 内部自建评测案例，不含真实个人信息 |
| official_reference | 比赛方提供的公开推理输入与 schema 参考 | 赛事方材料，按赛事规则使用 |

## Git 策略

- 进仓库：weights/inference_config.json、weights/MANIFEST.*、weights/LICENSES/、weights/*.json、src/、tests/、training/、data/、reports/
- 不进仓库：weights/base-qwen2.5-0.5b-instruct/、weights/sft-short/（大权重，见 weights/.gitignore）
- 交接提醒：B/C 若需要真实引擎，必须另外拿这两个权重目录的实体文件；仓库里只有清单与指纹，clone 之后不会有权重。
