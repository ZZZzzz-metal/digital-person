# B5 官方离线入口

团队自写文件，不覆盖 `../official-reference/`。入口直接调用 A 的 ModelEngine/official_trace；不运行 Web、FastAPI 或 vLLM HTTP，不调用外部模型 API。成功 prediction 四字段经严格 DTO 重验、原样加 id、有效 schema 重验后写出。

## 模型已在本地的开发机

需要合并 A/B 的源码、完整模型目录、原配置和模型兼容的依赖；纯后端锁不含 Torch/Transformers。A 配置的相对 model_dir 以配置目录为基准。项目根目录执行：

```powershell
python submission/participant/run_inference.py submission/official-reference/test_inference_data.jsonl .runtime/b5-new-result --config weights/inference_config.base.json --hardware-label "local device"
python submission/participant/check_output.py submission/official-reference/test_inference_data.jsonl .runtime/b5-new-result
```

`--config` 也可用环境变量 B2_OFFICIAL_MODEL_CONFIG；未指定时为项目根目录 weights/inference_config.json。硬件归属说明可用 B2_OFFICIAL_HARDWARE_LABEL，实际设备另在 runtime 日志记录。没有 mock 参数；缺模型或配置退出 1，不生成成功占位文件。结果目录可已有旁文件，但两个官方文件任意一个已存在就拒绝覆盖，换一个新目录运行。

本机 B5 验收使用 B4 已准备的 Python/CPU 基线，原配置不改；因为用户手动拉取 A 源码，此 B 分支的验证 helper 会临时追加已核验 A 只读副本的包搜索路径。正常合并后的项目不需要该额外操作。复现 helper 和资源绝对路径见 B5验收.md。

## 固定 Linux 启动位置

```bash
bash /root/participant/start.sh TEST_FILE RESULT_DIR
```

入口保留固定 `source activate conda_env`。B6 打包时需把本目录脚本、B/A 的 `src/b2_core`、`contracts/official` 和 A 完整 `weights`/配置准备在 `/root/participant` 下；脚本能识别该自包含布局。此准备说明不是已构建镜像。B5 在 Windows 验证 Python CLI，Linux 环境激活、GPU/禁网 Docker 在 B6 实测。

运行强制 HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE，并阻止当前 Python 进程 socket 连接与 UDP 发送；这是进程 guard，实际 Docker `--network none` 仍须实测。模型加载仅一次；每条创建并关闭独立空 InMemoryStore，不读取演示库，也不把上一条的结果补进下一条历史。

## 输入、输出和计时

UTF-8 JSONL（输入允许 BOM/空行），要求非空唯一 id 和非空 history。全部 role/content 原顺序保留，末项必须 user，不额外追加，不按文本去重，不套演示 12 条/4,000 字符/2,000 字符限制。只投影 id/history，源文件额外标签/答案/记忆字段不进入模型。target 提供时须对应末项 turn_id；已提供的 turn_id 为严格正整数、唯一递增，前面可省略。A 模型自身 tokenizer 上限保持原配置，超限失败交 A 处理。

每条结果仅 id、response_text、emotion_label、user_profile、memory_refs；回复/16 类情绪必须非空，画像三组唯一枚举数组，团队公开输入引用 []。模型对象完整 dump 后复验，额外字段不丢弃来掩盖错误。运行先验证全部输入，生成到指定目录自有临时文件；全部重验后以拒覆盖的硬链接发布两个最终文件。任一步失败退出 1 并清理自有临时/新发布文件，保留原候选和旁文件；同目录并发拒绝。结果文件系统需支持硬链接，B6 验证实际挂载。

全量生成，前 min(样本数,100) 条计时；required_rounds=100、rounds=该数、complete=(rounds==100)。公开 3 条完整生成仍 complete=false。毫秒保留 6 位，p95 为排序后第 ceil(0.95*n) 项；均值/中位数/min/max 均据实际测量。计时包括 A 官方 prompt/tokenize/generate/decode/parse/重试/真实文本回退和 B 严格输出验证，前后同步全部可见 CUDA；排除加载、建 store 和写文件。

parse_failure_count/ids 统计“至少一次 A JSON 解析失败的样本”，每条最多计一次，包含重试；这是团队对多尝试路径的定义，区别于原参考单次解析。stdout 的安全 JSON 事件保留 mode、解析失败次数、回复/情绪/画像来源、历史摘要与新 store 关闭；不含输入文本或 raw_head。A 的 fallback_rules 也由本地模型生成回复，情绪/画像可由 A 规则填充，会如实记录。B 不生成固定假回复，不把字段结构合格当模型效果或官方分数。

check_output.py 不加载模型，独立重读严格 JSON、每条成功 DTO/schema、ID 顺序/数量、输入/输出摘要和计时/complete/解析计数。返回 0 表示文件协议通过，CPU 性能不能换算正式双 4090 得分。
