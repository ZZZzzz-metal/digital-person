# 虚构协议样例

这里的 JSON 由 `../export_schema.py` 从 Pydantic DTO 生成，全部仅用于结构检查。

CoreRequest、CoreReply、ChatResponse 是同一组虚构会话，两个回复 DTO 显式 `is_mock=true`。Health 也是虚构 stub 状态，非实际服务状态；OfficialPrediction 是独立官方格式 fixture，不能带 is_mock 或 ID。回复与耗时均不代表真实推理结果，不用于正式 submission。
