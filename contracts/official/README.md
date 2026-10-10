# 官方合同快照

原始来源、压缩包及文件 SHA256 见 [source-manifest.json](source-manifest.json)。以下三份 schema 保留官方原始字节，不修补包内问题：

目录内 .gitattributes 保护原始 schema 换行；参考脚本目录也禁用文本换行转换，避免 Windows 拉取后改变摘要或破坏 Bash 入口。

- [submission.schema.json](submission.schema.json)：正式输出；也是参考 participant/templates/submission_schema.json 的原样副本。
- [train_public.schema.json](train_public.schema.json)、[val_public.schema.json](val_public.schema.json)：每行会话及预测点标签，不适用于推理测试行。

[model_prediction.schema.json](model_prediction.schema.json) 是团队派生的成功生成约束：由官方输出移除 B 原样回填的 id，要求回复非空，移除情绪失败空字符串。它不是官方原文件，也没有修正官方 id 正则。画像枚举与 memory_refs 格式保留。

2026-10-10 用户转贴官方答复明确 **ID 原样回填输入**、**memory_refs 不参与评分**。原始 schema 不改，当前团队执行使用 [effective_submission.schema.json](effective_submission.schema.json)：只移除 properties.id.pattern，其他约束保留，新增来源说明；它不是官方发布的修正版。输入/输出 ID 完全相等须独立检查，不能改成 test_ 前缀来通过旧正则。

公开测试原 prompt 要求 memory_refs=[]；训练标注存在引用但无 memory bank。团队仍默认 []，将其标为团队选择。答复原文和解释见 [clarification-2026-10-10.json](clarification-2026-10-10.json)、[官方接口核对](../../docs/官方接口核对.md)。有效合同的 [实跑检查报告](../../reports/integration/b0-effective-schema-check.json) 为内存协议 fixture，不是模型预测或平台验收。

这里提供 schema 和证据，不表示已实现 Python DTO、训练模型或通过官方运行验收。
