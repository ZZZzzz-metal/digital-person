# 官方入口与原始参考

当前团队代码在 [participant](participant/README.md)：直接调用 A 的本地 ModelEngine，完整官方历史 → 严格五字段结果与前 100 条计时报告，不依赖 HTTP 服务。B5 实际 CPU 验收见 [报告](../reports/integration/B5验收.md)，B6 再验证 Linux/conda/GPU 禁网容器。

`official-reference/` 是队伍提供工程包的**小文件原样快照**：两份 README、participant 脚本/配置/模板、3 条推理输入。训练/验证 JSONL 大文件与平台教程 DOCX 未发布，所以原始 README 中提到的这些文件在此子目录并不存在。完整清单和 SHA256 在 [source-manifest.json](../contracts/official/source-manifest.json)。

参考代码确实会调用模型，并非 mock；但包里没有模型权重。B0 的核对只运行失败路径，B5 真推理使用团队 participant 文件和另备的完整基线。B6 再把 participant 准备到实际 Linux/GPU 镜像 `/root/participant`，保留固定 `conda_env` 和启动路径。

官方 Linux 调用示例（来自原包，尚未在本队环境验证）：

```bash
bash /root/participant/start.sh /root/test_inference_data.jsonl /root/result
```

结果为 `/root/result/submission.jsonl` 与 `/root/result/performance_report.json`。默认 Transformers 直接加载 `/root/participant/model`；兼容模式由入口自主启动本地 vLLM。不需要演示 FastAPI 或浏览器，不调用外部模型 API。

原始参考脚本的 ID 正则冲突已由用户转贴答复澄清为“原样回填输入 ID”。团队使用有效 schema 并独立核对逐项 ID，保留旧 schema 字节作为证据。3 条全部输出时按原参考算法仍 complete=false，不补造成 100 条。请先读 [官方接口核对](../docs/官方接口核对.md)，参考脚本打印 PASS 或文件存在本身不能代表平台得分；团队入口仅全部输出重验后才发布文件，已有候选拒绝覆盖。
