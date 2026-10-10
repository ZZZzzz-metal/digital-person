# B1 共享合同

类型来源为 `src/b2_core/contracts.py`。`schema/` 和 `examples/` 全部由 Pydantic 生成，供 A 实现模型接口、C 对接前端；B1 提供合同和健康骨架，B2 沿用这些 DTO 实现会话 API，聊天、记忆、官方适配在后续阶段实现。

| 使用方 | 输入与输出 | 边界 |
|---|---|---|
| 演示模型 A | `Engine.generate(CoreRequest) -> CoreReply` | 六类 `emotion`、四种 `expression`；engine 有布尔 `is_mock` 和非空 `model_version` |
| 演示页面 C | `ChatRequest`、`ChatResponse`、会话/记忆 DTO | 本轮参考记忆表示候选；当前已提供健康和会话 CRUD/消息读取，聊天/记忆 HTTP 等后续阶段 |
| 官方生成 A | `OfficialEngine.generate_official(OfficialRequest) -> OfficialPrediction` | 输入携带原样 sample_id；独立十六类情绪、三组唯一画像数组、四字段生成结果；不生成 ID 或演示元数据 |

`Engine` 与 `OfficialEngine` 是静态 Python Protocol，不会创建模型，也不替代应用对 metadata 和实际返回值的校验。`b2_core/__init__.py` 只导出类型，不导入 A 的模型、Torch、Transformers 或后端。

所有对象拒绝额外字段，采用严格类型，避免字符串 `"false"` 被当布尔值。消息和成功回复必须含非空白字符。演示输入最多 2,000 字符，记忆 key 使用总约定五项白名单，记忆值先 trim 再验证 1–200 字符。时间戳必须为 UTC ISO 8601 且以 `Z` 结尾。

`CoreRequest.messages` 与 `OfficialRequest.history` 非空且最后一条为本轮 user；传入历史已经包含当前输入，调用者不能再次追加。该末条角色规则是 Pydantic 跨字段校验，JSON Schema 本身不能完全表达；“当前输入一次”还需要后续历史编排负责，DTO 不按相同文本去重。画像/引用唯一性同时由 Pydantic 和生成 schema 验证。外部 JSON Schema 校验时间格式时应启用 `format` 检查；客户端记忆值先 trim 再校验 schema，以与服务端一致。

官方 DTO 的枚举和引用格式沿用 `official/model_prediction.schema.json`；成功输出额外拒绝纯空白回复。`OfficialRequest.sample_id` 是必填非空白字符串，从原始输入 `id` 完全原样传入，不 trim、不改前缀、无 ID 前缀正则；它用于接通 A 的现有输入规范化，不是模型生成的 ID。完整原始测试行还含 conversation_id、target_user_turn_id，历史还含 turn_id；后续 B5 验证这些对应关系后投影成 `Message`，不能将原始行直接传入 `OfficialRequest`。没有 memory bank 时 `memory_refs=[]` 是团队默认选择，不能填演示记忆 ID。画像不会自动落入记忆库。

`official/` 保留 B0 证据，不由本脚本修改。有效提交 schema 已按用户转述的官方答复移除旧 ID 前缀正则；后续 B5 从对应输入原样回填 ID，并单独验证完全相等。成功生成 DTO 不含 ID，不能直接称为完整正式提交行。正式输出不得附加 is_mock、表情、耗时或版本字段。

生成与检查（先安装根 README 说明的合同/开发环境）：

```powershell
python contracts/export_schema.py
python contracts/export_schema.py --check
python -m pytest tests/server/test_contracts.py -q
```

导出脚本以自身位置定位当前仓库；从其他目录执行时使用脚本绝对路径。`--check` 比对生成字节并拒绝缺失、变化或多余 JSON，不写文件。schema 采用 JSON Schema 2020-12。升级 Pydantic 后若产物变化，要同步导出并检查。

全部 `examples/` 都是 **fictional protocol fixtures**。配套 CoreReply、ChatResponse、Health 明确 `is_mock=true`；CoreRequest 按合同没有 is_mock 字段，虚构输入注明用途。OfficialPrediction 按合同不能带 is_mock，所以通过本说明和样例内文字注明虚构。`elapsed_ms=0` 是占位值，Health 样例不是运行状态记录。样例不证明实际模型推理、训练、性能、容器或赛事提交完成，不能作为 submission 预测文件。
