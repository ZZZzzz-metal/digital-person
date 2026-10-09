# 官方合同快照

原始来源、压缩包及文件 SHA256 见 [source-manifest.json](source-manifest.json)。以下三份 schema 保留官方原始字节，不修补包内问题：

目录内 .gitattributes 保护原始 schema 换行；参考脚本目录也禁用文本换行转换，避免 Windows 拉取后改变摘要或破坏 Bash 入口。

- [submission.schema.json](submission.schema.json)：正式输出；也是参考 participant/templates/submission_schema.json 的原样副本。
- [train_public.schema.json](train_public.schema.json)、[val_public.schema.json](val_public.schema.json)：每行会话及预测点标签，不适用于推理测试行。

[model_prediction.schema.json](model_prediction.schema.json) 是团队派生的成功生成约束：由官方输出移除 B 原样回填的 id，要求回复非空，移除情绪失败空字符串。它不是官方原文件，也没有修正官方 id 正则。画像枚举与 memory_refs 格式保留。

公开测试 prompt 要求 memory_refs=[]；训练标注存在引用但无 memory bank。小样例 id 与输出正则不一致，不能静默改名。完整解释见 [官方接口核对](../../docs/官方接口核对.md)。

这里提供 schema 和证据，不表示已实现 Python DTO、训练模型或通过官方运行验收。
