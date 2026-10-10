# B 分工进度记录

更新日期：2026-10-10（北京时间）。本文件是 Agent 的工作进度记忆，不是产品的长期记忆数据库。每次阶段交付更新；恢复工作时先读本文件、核对分支/工作区，只补读有变化的约定和当前阶段必要内容，不重复已经验收的资料获取或检查。

## 当前阶段与操作边界

- 用户已要求 **继续 B4**；本轮只做聊天编排与 A 引擎接入/验证，完成推送和 PR 后停止，不进入 B5–B8。
- Agent 负责上传分支和 PR，用户手动合并和拉取；Agent 不 fetch/pull/merge。项目仓库为 [digital-person](https://github.com/ZZZzzz-metal/digital-person)。
- 当前工作分支 `codex/b4-chat`，从 B3 最后文档提交 `44d7363101e96e9fc58a71d55f2fd4fcb9d8da64` 开始。工作目录 `C:/Users/20964/Documents/ChatGPT/MC/digital-person-b0` 历史名不代表当前阶段。
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

## 已完成：B2（已合并）

- 启动时只读确认 PR #5 已合并，远端 main 当时为 `6c6bb78b8d754a28405585a491cb2b68d6453202`；没有 fetch/pull/merge。从本地已验证的 B1 提交继续，避免重复资料获取和环境安装。
- 已先在总约定增加 B2 存储/匿名身份合同；现有 API DTO/schema 不改字段。当前任务为 SQLiteStore/InMemoryStore、随机匿名 cookie、会话 CRUD/消息历史和 turn 原子保存/去重/并发控制。
- `/api/chat` 编排与产品长期记忆不在本轮实现；用测试 fixture 检查存储成功/失败语义，不声称真实模型已验收。保留 B1 的明确 mock/real 健康行为。
- SQLiteStore/InMemoryStore、匿名身份、四个会话操作和 turn 占用/完成/释放已实现；内存版本为每实例独立 SQLite :memory:，不复用演示文件。有效 pending 删除 409，过期后可恢复；complete 返回 None，成功重试通过 reserve 取原 ChatResponse。
- 实际 **123/123 测试通过**（44 合同、20 健康、28 API、31 存储），21 schemas/21 fixtures 一致，pip check 无冲突；沿用 B1 环境，无新增依赖。已实际验证 SQLite 第二条消息写入失败回滚整轮、两连接竞争、租期旧 token、重试、归属和深副本。
- 实际 HTTP **8 项通过**，两个自建 Uvicorn 进程验证两用户、消息 fixture 读取和 SQLite 重启持久化，均已关闭。没有模型生成或聊天路由，没有原始 cookie 入报告。
- 实现及验收提交 `f2b54797be85f69b3cb6a52d08e05435e31b8f95` 已实际推送，创建 [PR #6](https://github.com/ZZZzzz-metal/digital-person/pull/6)，目标 main，17 个文件，仅 B 分工区域。创建时 open、未合并；发布记录另作一次文档提交并推送到同一 PR。
- 结果见 [B2 验收](B2验收.md)、[结构化记录](b2-verification.json)、[HTTP 实测](b2-http-smoke.json)。没有 B2 人工技术阻塞。

## 已完成：B3（已合并）

- B3 启动时只读确认 PR #6 已合并，head 为 `ac80f5892c2f1afce64cbec159fb02d496f02177`；发布前观察 main 为 `1826b1a5a9a6cb209184f73768db4e4110e49d52`。没有 fetch/pull/merge，也没有重装环境。
- 先更新总约定第 8 节记忆存储方法/关闭管理语义，再并行实现；沿用现有 DTO/schema 字段，不改 A/C 模型与前端。
- 用户确认的五项白名单事实 CRUD 已实现；同 key 更新保留 id，跨会话与删除会话保留记忆。关闭 list/settings 返回 false/[]，不读事实，save 返回 409 MEMORY_DISABLED；重新开启恢复旧值。关闭期间允许明确删除/清空，清空不改开关且只删本人。
- 纯 build_memory_context 最多五条相关事实；不相关为空，数据以 JSON 包装，不是系统指令。返回的是候选 DTO，不能称模型已使用或保证抗提示注入；不从情绪/画像自动落库。
- 实际 **216/216 测试通过**（44合同、20健康、28会话、31原存储、39记忆API、38记忆存储、16纯检索）。SQLite authorizer 实测关闭路径不查询 memories；两实例同 key 竞争唯一；旧 B2 布局补表保留已有数据；高数→线代和关闭的 CoreRequest 输入构造通过。
- 实际 HTTP **10 项通过**，两个自建 Uvicorn 进程检查身份隔离、纠正、开关/清空与 SQLite 重启，均已关闭，原始 cookie 不记录。没有模型生成；/api/chat 仍未实现。
- 21 schemas/21 fixtures 一致、pip check 无冲突，沿用 B1 环境无新增依赖。旧验收记录和 JSON 不替换为当前结果。
- 本轮结果见 [B3 验收](B3验收.md)、[结构化结果](b3-verification.json)、[HTTP 实测](b3-http-smoke.json)。无 B3 人工技术阻塞。
- 实现与验收提交 `f785f6be8199dfef2f91421daa6de77966dee5dd` 已实际推送，创建 [PR #7](https://github.com/ZZZzzz-metal/digital-person/pull/7)，目标 main，19 个文件仅 B 分工区域。创建时 open、未合并，head 与本地一致。本文发布记录另作一次文档提交并推送到同一 PR；不把用户未来的合并预写为已完成。

## B4：后端与真实基线已验证，待发布

- 先更新总约定第8节聊天合同，再实现纯 build_core_request/run_turn 和 POST /api/chat；DTO/schema不改字段，不修改A/C文件。模型启动一次，相关候选记忆接入，成功缓存原样返回，失败/超时/取消不保存半轮并允许原ID重试。
- 实际 **294/294 测试通过**：新聊天49、纯turn29、旧回归216；21 schemas/21 fixtures一致，后端pip check无冲突，原后端环境与锁沿用。额外验证旧超时线程跨lifespan保持gate、直接cancel清理、模型自身ChatError不透传原输入；迟到结果不落库。
- 实际独立stub HTTP 7项/8次明确mock生成通过；真实A公开基线HTTP 7项/8次真实生成通过，其中同会话6轮、12条有序消息、成功重复不增调用/消息、新会话记忆和另一cookie隔离。两个模式各自创建一个服务，均已关闭，无原始cookie入报告。
- 真实版本 `b2-a-qwen2.5-0.5b-instruct-base-v1`，494,032,768参数、float32/CPU/16线程，原始采样配置保留，初始化一次，A代码固定main `259fac62d8d5bc8ceb6104e1d49b68cfd063996b` 的只读副本，使用当前B Pydantic合同；当前main dtos摘要不同于旧A6清单，实际源码逐文件SHA另存。
- 原样基线8文件999,597,690字节，SHA全部匹配A，HF revision `7ae557604adf67be50417f59c2c2f167def9a775`。已验证资源在 `reports/integration/.b4-work/real-assets/`，原配置/许可保留；独立 `.runtime/b4-real-env/` Python3.12.14/torch2.14.1+cpu/transformers5.19.0，pip check通过。这些本地资源被忽略，不上传Git，不是正式GPU容器候选。
- 真实候选记忆输入符合高数→线代/关闭规则，但基线第三轮没有回答线代，而是询问考试科目；未声称模型记忆准确率或训练质量通过。B不修A模型。情绪/表情是A规则，回复是真实模型。
- C前端当前未交付，页面联调performed=false，准确缺项见 b4-c-handoff-check.json。A的sft-short完整训练权重在别人的电脑，未在这里验收；继续使用已验证公开基线。无B代码技术阻塞，正式适配/禁网GPU容器/镜像/赛事提交为后续阶段。
- 本轮报告 [B4验收](B4验收.md)、[结构化结果](b4-verification.json)、[真实HTTP](b4-real-http.json)、资源/环境/源码摘要均已保存。未消耗算力券、未训练、未fetch/pull/merge；本轮待提交推送后记录PR。

## 恢复与下一步

- B4 启动只读确认 PR #7 已合并，main 当时为 `259fac62d8d5bc8ceb6104e1d49b68cfd063996b`；A model/a_impl/prompts 与 A0–A7 报告已取得只读参考副本，不改项目 A 文件或 fetch/pull/merge。共享聊天合同已先更新。
- B4当前实际运行方法与剩余项见上节/B4验收；A源码只读副本为 `../tmp/b4_20261010/upstream-A/src`，可配合公开 b4-a-source-check.json 核验后复现，不需要重下载基线或重装环境。不得将准备报告的 model_inference_verified=false 误读为最终真实HTTP未通过，它们是不同时间/范围的记录。

1. 核对当前分支和工作区，再阅读本轮验收记录。若记录说已通过而代码/锁/样例后来改变，仅重跑受影响的最小检查。
2. B0–B4后端已验证，未变的部分不重复从头核对、重装或重测；用户手动合并/拉取。下次先核对B4实际发布记录及远端只读状态。
3. 本轮发布后停止，等待用户点名B5；不要提前写官方适配器。C交付后才补实际页面联调；本机真实CPU结果不能替代A训练候选/正式容器验收。
4. 正式模型、训练、GPU 容器、可回退参赛候选和赛事上传尚未验收；需要相应后续阶段实际运行，不能由 B1 演示成功替代。

主要依据：[总约定](../../docs/分工/00-总约定.md)、[B 任务书](../../docs/分工/B-记忆后端与参赛部署.md)、[B0 验收](B0验收.md)、[官方答复](B0-官方答复-2026-10-10.md)。本文件不保存账号、密码、cookie、token 或真实聊天。
