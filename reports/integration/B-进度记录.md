# B 分工进度记录

更新日期：2026-10-10（北京时间）。本文件是 Agent 的工作进度记忆，不是产品的长期记忆数据库。每次阶段交付更新；恢复工作时先读本文件、核对分支/工作区，只补读有变化的约定和当前阶段必要内容，不重复已经验收的资料获取或检查。

## 当前阶段与操作边界

- 用户已要求 **继续 B2**；B2 已完成验证、提交、推送和 PR，现在停止等待用户合并/拉取及下一阶段指令；不进入 B3–B8。
- Agent 负责上传分支和 PR，用户手动合并和拉取；Agent 不 fetch/pull/merge。项目仓库为 [digital-person](https://github.com/ZZZzzz-metal/digital-person)。
- 当前工作分支 `codex/b2-storage-sessions`，从 B1 最后文档提交 `c85e9717d4e960e76169c9f35215de8cfdb32ef3` 开始。工作目录 `C:/Users/20964/Documents/ChatGPT/MC/digital-person-b0` 历史名不代表当前阶段。
- 旁边的旧 `digital-person` 目录还有早期混合 B1–B5 提交及后续未提交文件，没有按本次逐阶段流程发布，不能当成当前已交付内容或整批带入本轮。
- B 只改自己的 contracts/core 类型、server、tests/server、环境声明、README、总约定、集成报告。A 的 model/prompts/a_impl 和 C 的前端由各自主责；不代写或覆盖。共享合同变更先更新总约定/schema，由队伍合并拉取同步。

## 已完成：B0

- 核心官方入口、输入/输出和赛事规则核对完成；官方答复来源为用户转贴，原文和结构化记录已保存。
- B0 提交 `3b1e45fad523c8a789a446abdbc3effdbcae6bae`，对应 [PR #3](https://github.com/ZZZzzz-metal/digital-person/pull/3)。B1 启动时通过 GitHub 只读查询确认该 PR 已合并，远端 main 为 `0432ac9bdbed23442e64a85f203d8d849818cd3b`；这是当时观察，不是永久最新值。
- 实际通过 34/34 协议检查，12/12 原始参考摘要一致。没有模型预测、训练、镜像构建、正式容器验收或赛事提交；缺资源的启动失败日志不是推理通过。
- ID 必须原样回填对应输入，旧 test_ 正则仅为原始快照证据。当前团队有效输出合同为 `contracts/official/effective_submission.schema.json`，只去掉 id.pattern，仍须单独检查逐项 ID 相等。
- 官方不提供镜像外部下载，平台版本可参考且不限制；不要再要求用户取得官方 registry/digest。所选镜像摘要/依赖在 B6 实测。
- 正式评测两张 4090，答复为 24g，按每卡标称 24G 规划；官方不设超时/上下文限制。全量输入输出，只计前 100 条耗时。
- memory_refs 不评分，团队默认 []；原 schema 其他结构限制保留。题 4 的使用限制答复为“无限制”，实际选用模型许可由 A 核查。
- 标准 Docker 镜像“50G以内”，外部存储按作品提交页引导。未说明的 CPU/系统内存/磁盘、短输入 complete、评分换算、50G 单位/压缩口径、截止时区等，用户同意不影响开发就不追问，保留未知即可，不重新阻塞 B0。
- 团队继续遵循原参考计时/complete 逻辑、镜像大小留余量，目标北京时间 10/19 18:00 前提交；这些是内部策略，不是官方新增规则。
- 算力券最后读取值为 20/20 4090 GPU 卡时，显示有效至 10/16 23:17:54；未开机耗券。该记录不是此后实时余额，不含账号/券标识。

## 已完成：B1（已合并）

- 目标：共享 Pydantic 类型、生成 schema 与虚构协议样例、只导出类型的包入口、FastAPI 健康接口、明确演示 stub、真实模式失败不降级、独立可安装环境。
- 已交付共享 Pydantic DTO、21 schemas/21 虚构协议样例及检查脚本、只导出类型的包入口、server 骨架、独立后端环境与版本锁。`GET /health` 是本轮唯一实际业务路由；其他 API 留到 B2–B4，C 先使用本地 mock。
- 后端 `B2_MODE=stub|real`；默认 stub，必须报告 is_mock=true。real 使用 A 的 ModelEngine 和 B2_MODEL_CONFIG，缺本地实现/资产时健康状态 degraded、model_ready=false、is_mock=false，不偷偷返回演示成功。
- 已只读确认远端有 A 的 `model.py`、`a_impl/` 和 prompts；本工作分支尚未拉取它们。不要把本分支缺 A 文件写成“队伍没有 A 实现”。真实模型接入与效果验收不属于本轮。
- 独立新 `.venv` 为 Python 3.12.14；editable 项目安装与版本锁检查成功，pip check 无冲突。首次受限临时目录失败改用项目临时目录；受限运行器中的首次异步/HTTP 检查卡住，终止自有进程后在允许本地运行的环境重跑成功。
- 实际 **64/64 测试通过**；21/21 schema 和 21/21 fixture 一致。两个独立 Uvicorn 进程实际在 127.0.0.1:8000 验证 stub 就绪/mock、real 缺本地 A 模块时 degraded/non-mock；均已关闭自有进程。real 结果是失败路径检查，不是模型推理通过。
- 与已合并 A 的只读 DTO 模块核对实际通过 5 项。发现 A 输入规范化需要 `sample_id`，已先更新总约定并修正共享 OfficialRequest 原样传入 ID；模型四字段结果仍不含 ID，原始轮次关联留到 B5。
- 实现及验收提交 `8224955bb2f41d297f6733d233a4a37d61694acb` 已实际推送，创建 [PR #5](https://github.com/ZZZzzz-metal/digital-person/pull/5)，目标 main。创建时状态 open、未合并；不把后来用户合并状态预写为已完成。本文的发布记录另作一次文档提交，同样推送到本 PR。
- 完整结果见 [B1 验收](B1验收.md)、[结构化记录](b1-verification.json)、[A 接口核对](b1-a-contract-compatibility.json)。没有等待用户解决的 B1 技术阻塞。

## 已完成：B2（已推送，等待用户合并/拉取）

- 启动时只读确认 PR #5 已合并，远端 main 当时为 `6c6bb78b8d754a28405585a491cb2b68d6453202`；没有 fetch/pull/merge。从本地已验证的 B1 提交继续，避免重复资料获取和环境安装。
- 已先在总约定增加 B2 存储/匿名身份合同；现有 API DTO/schema 不改字段。当前任务为 SQLiteStore/InMemoryStore、随机匿名 cookie、会话 CRUD/消息历史和 turn 原子保存/去重/并发控制。
- `/api/chat` 编排与产品长期记忆不在本轮实现；用测试 fixture 检查存储成功/失败语义，不声称真实模型已验收。保留 B1 的明确 mock/real 健康行为。
- SQLiteStore/InMemoryStore、匿名身份、四个会话操作和 turn 占用/完成/释放已实现；内存版本为每实例独立 SQLite :memory:，不复用演示文件。有效 pending 删除 409，过期后可恢复；complete 返回 None，成功重试通过 reserve 取原 ChatResponse。
- 实际 **123/123 测试通过**（44 合同、20 健康、28 API、31 存储），21 schemas/21 fixtures 一致，pip check 无冲突；沿用 B1 环境，无新增依赖。已实际验证 SQLite 第二条消息写入失败回滚整轮、两连接竞争、租期旧 token、重试、归属和深副本。
- 实际 HTTP **8 项通过**，两个自建 Uvicorn 进程验证两用户、消息 fixture 读取和 SQLite 重启持久化，均已关闭。没有模型生成或聊天路由，没有原始 cookie 入报告。
- 实现及验收提交 `f2b54797be85f69b3cb6a52d08e05435e31b8f95` 已实际推送，创建 [PR #6](https://github.com/ZZZzzz-metal/digital-person/pull/6)，目标 main，17 个文件，仅 B 分工区域。创建时 open、未合并；发布记录另作一次文档提交并推送到同一 PR。
- 结果见 [B2 验收](B2验收.md)、[结构化记录](b2-verification.json)、[HTTP 实测](b2-http-smoke.json)。没有 B2 人工技术阻塞。

## 恢复与下一步

1. 核对当前分支和工作区，再阅读本轮验收记录。若记录说已通过而代码/锁/样例后来改变，仅重跑受影响的最小检查。
2. B0–B2 已验证，未变的部分不重复从头核对或全部测试。当前只核对 B2 提交/PR 发布及用户是否已合并/拉取；不要重新安装已验证的环境。
3. B2 发布后停止等待 B3 指令。B3 接手读总约定第 6/8 节、B 任务书 B3、store.py 和现有 API，增加 memory.py 与记忆 CRUD；可扩展 users.memory_enabled 和用户级 memories 表，不改 A/C 实现，也不提前做 B4 聊天编排。
4. 正式模型、训练、GPU 容器、可回退参赛候选和赛事上传尚未验收；需要相应后续阶段实际运行，不能由 B1 演示成功替代。

主要依据：[总约定](../../docs/分工/00-总约定.md)、[B 任务书](../../docs/分工/B-记忆后端与参赛部署.md)、[B0 验收](B0验收.md)、[官方答复](B0-官方答复-2026-10-10.md)。本文件不保存账号、密码、cookie、token 或真实聊天。
