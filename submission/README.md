# 官方参考入口

`official-reference/` 是队伍提供工程包的**小文件原样快照**：两份 README、participant 脚本/配置/模板、3 条推理输入。训练/验证 JSONL 大文件与平台教程 DOCX 未发布，所以原始 README 中提到的这些文件在此子目录并不存在。完整清单和 SHA256 在 [source-manifest.json](../contracts/official/source-manifest.json)。

参考代码确实会调用模型，并非 mock；但包里没有模型权重。本次没有安装依赖或实际推理，不能把此目录当成已通过验收的提交包。A 提供完整本地模型后，B 在实际 Linux/GPU 镜像把 participant 准备到 `/root/participant`，保留固定 `conda_env` 和启动路径。

官方 Linux 调用示例（来自原包，尚未在本队环境验证）：

```bash
bash /root/participant/start.sh /root/test_inference_data.jsonl /root/result
```

结果为 `/root/result/submission.jsonl` 与 `/root/result/performance_report.json`。默认 Transformers 直接加载 `/root/participant/model`；兼容模式由入口自主启动本地 vLLM。不需要演示 FastAPI 或浏览器，不调用外部模型 API。

3 条样例与官方 id 正则存在矛盾，默认 100 轮性能也无法用 3 条完成。请先读 [官方接口核对](../docs/官方接口核对.md)，不要仅凭脚本打印 PASS 或结果文件存在判定正式成功。参考文件不在本次核对中擅自修补；后续团队适配文件与原始快照分开维护。
