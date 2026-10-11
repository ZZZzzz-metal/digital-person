# B 分工进度记录

更新日期：2026-10-11（北京时间）。本文件是 Agent 的工作进度记忆，不是产品的长期记忆数据库。每次阶段交付更新；恢复工作时先读本文件、核对分支/工作区，只补读有变化的约定和当前阶段必要内容，不重复已经验收的资料获取或检查。

## 当前阶段与操作边界

- 用户已要求 **继续 B6**，并明确允许 B 使用卡券。完整打包/容器验收准备完成；正式 GPU 禁网 Docker 验收因平台权限阻塞，不能记成 B6 完成，不进入 B7–B8。PR #9 已只读确认合并，当前远端 C 页面已存在但本轮未联调。
- Agent 负责上传分支和 PR，用户手动合并和拉取；Agent 不 fetch/pull/merge。项目仓库为 [digital-person](https://github.com/ZZZzzz-metal/digital-person)。
- 当前工作分支 `codex/b6-container`，从 B5 最后文档提交 `23ddfedbdbdd65d82c0a1fb14635dd1d89007b19` 开始。工作目录 `C:/Users/20964/Documents/ChatGPT/MC/digital-person-b0` 历史名不代表当前阶段。
- 用户新增偏好：**所有后续本机下载、大模型、打包产物与镜像放 D 盘**，C 盘空间不足。B6 实际包在 `D:/B2-B6-20261011/candidate-a34f8df`；已验证旧 B4/B5 资产不重下，保留原位置。云端下载使用实例磁盘。
- **最新续做状态**：用户明确要求 Agent 自行安装配置。本机官方 WSL3.0.1 已实际安装，MSI退出0；VirtualMachinePlatform启用退出3010，需要Windows重启。WSL/Ubuntu两个安装包已在D下载并核对官方SHA/微软签名；交换盘也已设D。当前只待用户保存工作、手动重启，再回复继续。下一条实际命令 `.venv/Scripts/python.exe -B deploy/resume_b6_local.py --verify`；先核对boot和专用发行版D路径，不重复下载安装、不再开平台实例。详见 [本机环境续做](B6-本机环境续做.md)/[实际状态](b6-local-setup.json)。Ubuntu/Docker/NVIDIA工具包/正式镜像还未安装验收，不预写成功。
- 续做工具增加Linux侧限时与超时输出记录；原容器验证工具补充自有CID限时停止/移除和cleanup失败记录。变更后仅重跑相关容器控制模块，实际33项通过（3项新增取消/清理风险场景，模拟Docker，非真实GPU验收）；Python/PowerShell/Bash静态检查和CLI通过。原79项/CPU30项保持历史证据，不重新下载/运行旧模型。
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

## B4：后端与真实基线已验证并推送（已合并）

- 先更新总约定第8节聊天合同，再实现纯 build_core_request/run_turn 和 POST /api/chat；DTO/schema不改字段，不修改A/C文件。模型启动一次，相关候选记忆接入，成功缓存原样返回，失败/超时/取消不保存半轮并允许原ID重试。
- 实际 **294/294 测试通过**：新聊天49、纯turn29、旧回归216；21 schemas/21 fixtures一致，后端pip check无冲突，原后端环境与锁沿用。额外验证旧超时线程跨lifespan保持gate、直接cancel清理、模型自身ChatError不透传原输入；迟到结果不落库。
- 实际独立stub HTTP 7项/8次明确mock生成通过；真实A公开基线HTTP 7项/8次真实生成通过，其中同会话6轮、12条有序消息、成功重复不增调用/消息、新会话记忆和另一cookie隔离。两个模式各自创建一个服务，均已关闭，无原始cookie入报告。
- 真实版本 `b2-a-qwen2.5-0.5b-instruct-base-v1`，494,032,768参数、float32/CPU/16线程，原始采样配置保留，初始化一次，A代码固定main `259fac62d8d5bc8ceb6104e1d49b68cfd063996b` 的只读副本，使用当前B Pydantic合同；当前main dtos摘要不同于旧A6清单，实际源码逐文件SHA另存。
- 原样基线8文件999,597,690字节，SHA全部匹配A，HF revision `7ae557604adf67be50417f59c2c2f167def9a775`。已验证资源在 `reports/integration/.b4-work/real-assets/`，原配置/许可保留；独立 `.runtime/b4-real-env/` Python3.12.14/torch2.14.1+cpu/transformers5.19.0，pip check通过。这些本地资源被忽略，不上传Git，不是正式GPU容器候选。
- 真实候选记忆输入符合高数→线代/关闭规则，但基线第三轮没有回答线代，而是询问考试科目；未声称模型记忆准确率或训练质量通过。B不修A模型。情绪/表情是A规则，回复是真实模型。
- C前端当前未交付，页面联调performed=false，准确缺项见 b4-c-handoff-check.json。A的sft-short完整训练权重在别人的电脑，未在这里验收；继续使用已验证公开基线。无B代码技术阻塞，正式适配/禁网GPU容器/镜像/赛事提交为后续阶段。
- 本轮报告 [B4验收](B4验收.md)、[结构化结果](b4-verification.json)、[真实HTTP](b4-real-http.json)、资源/环境/源码摘要均已保存。未消耗算力券、未训练、未fetch/pull/merge。
- 实现/验收提交 `8b5d43b94acc5da1cc5e4d35c1bde56e118ce729` 已实际推送，创建 [PR #8](https://github.com/ZZZzzz-metal/digital-person/pull/8)，目标main，23个文件仅B分工区域。创建时open/未合并，head与本地一致；不把用户未来合并预写为完成。本文发布记录另作一次文档提交并推送到同一PR。

## B6：准备完成，正式 GPU 禁网验收因环境权限未通过

- 先改总约定与 bundle schema，再实现完整打包、GPU 运行探针和 Docker 自动验收。B 实现提交 `a34f8df7bd089f5d975c2ec1d0760bb4cb6ce394`；单次新增专项 **79/79 通过，14.19 秒**，包含模拟 GPU/Docker 与失败路径，不能称 79 次实际 GPU 验收。
- 完整包 `D:/B2-B6-20261011/candidate-a34f8df`，30 文件/999,760,049 字节，manifest SHA `c384dfbaa3b1e51558afb7db64e0628f778a4e157825f7a69a3f8b76de3150ca`。绑定 B 实现提交 a34f8df 与 A 固定来源 fce84b3，沿用原基线/配置/许可；未改 A/C 文件或下载新权重。另保留 D:/B2-B6-20261011/participant 早期包，主候选以 candidate-a34f8df 为准。
- 本轮只读确认 PR #9 已合并，merge SHA `44bc9301b8b42f033526261d95b30d36545abda5`；main 观察值 `9bb9ba9a79156b40887117a4de22838c6f2075d2`，八个 A Python 文件与 fce84b3 固定副本一致。无 fetch/pull/merge，无重复取得源内容。
- 候选 Dockerfile 固定 public PyTorch2.8/CUDA12.8 镜像 digest 与四个直接依赖；base-source 仅公开元数据，镜像未拉取/构建，不是已验证 GPU 完整锁。自动工具以同 image ID 执行 network none/gpus all、GPU 内核、实际模型 CUDA 事件、独立 checker、标准 docker save/大小/摘要；成功才置正式标志。
- 用户授权后创建自有平台实例 b6-offline-test-1011；公有 vLLM0.19.0 镜像实际 torch2.10+cu128，两张4090每卡24,564MiB内核计算成功。此能力探测没有 B2 模型推理，不能代替禁网镜像验收。
- 官方静态 Docker29.8.2 自建服务可启动，微型 Bash 镜像可导入；容器启动因只读 /sys/fs/cgroup/cpuset/docker 失败。备用 runc 新 keyring 无权限；单次 no-new-keyring 后仍 proc mount EPERM。runc 默认 rootless 配置未请求 network namespace，不算网络隔离。没有改变平台宿主权限/安全限制。
- 自有 Docker 服务已请求停止，实例已实际关机；最终页面总卡时余额29.23，最初30，显示差额0.77，包含不同券种，不称GPU-only余额。该值仅为本轮观察。截图本机 `.b6-work/platform-stopped-final.png`，不上传账号截图/认证值。
- 第一轮收尾时本机无 Docker CLI/可用 WSL，进程非管理员；当时没有安装或重启系统。之后用户明确授权 Agent 自行安装配置，已实际完成 WSL MSI 与 VMP 启用，当前需要一次Windows重启，最新动作以文首续做状态为准；无需等待 A/C。
- 单样例独立完整包真实 CPU 检查 **30/30通过**；推理/独立checker各退出0，原样5条历史、初始化1次、真实回复、独立空store关闭，原包前后30文件摘要一致。实际生成24,691.3615ms，两次JSON失败后A真实fallback_rules，情绪/画像rules，质量未评分。结果 D:/B2-B6-20261011/cpu-smoke-a34f8df/result，submission SHA7683a393a46353bc250b83bb1646d9f77491cc1cb969f8db0d353b21fd936828；安全报告 [b6-bundle-cpu-smoke.json](b6-bundle-cpu-smoke.json)，可复现helper verify_b6_bundle_cpu.py。它不等于 GPU/容器验收。B5原始CPU回退保留，不覆盖。
- 本轮运行方法和准确缺项：[离线验收](离线验收.md)、[部署说明](../../deploy/README.md)、[结构化结果](b6-verification.json)。正式候选image ID/tar/GPULock均未取得，gpu_offline_verified=false、fallback_image_verified=false、contest_submitted=false，B7未开始。
- 实现与验收报告已实际推送，报告提交 `92b57f92e70506bf65ae47538771902c91f0cf1e`，创建 [PR #10](https://github.com/ZZZzzz-metal/digital-person/pull/10)，目标 main，共23文件，仅B负责区域。创建后只读核对 open/未合并、head与本地一致、mergeable=true/clean；不把用户未来合并预写为完成。GitHub连接器创建返回403，使用同仓库既有Git凭据成功创建，凭据不保存/输出。本文发布记忆另作一次文档提交并推送到同PR，最终head另在实际远端核对。
- 下一步待Windows重启完成后运行 deploy/resume_b6_local.py --verify，自行准备D上的专用WSL发行版、Docker/NVIDIA环境并运行完整公开输入；不再重跑未变的 B0–B5、不重新领券/开机徒耗卡时、不把能力镜像当参赛镜像。上传工作仍由 Agent，用户合并/拉取。

## B5 历史验收与恢复依据（后续以当前 B6 状态为准）

- B5 已验收：共享合同/schema先改、团队官方独立入口/结果检查器已实现。沿用B4已验证CPU环境/完整基线，不重装/重下、不改A模型配置；启动只读确认PR#8合并，main `fce84b354ca0e6ab9cd1ec650198c0d45ab994bd`，A源码固定副本在 `../tmp/b5_20261010/upstream-A/src`，源摘要在b5-real-offline.json。没有fetch/pull/merge。
- 实际新旧全回归368通过；最后仅改初始化异常脱敏/字节码缓存，受影响官方专项最终76通过，未变后端294保留。21 schemas/21 examples、pip check、Bash-n、原始参考12份摘要一致。不同测试合计370，不能写成单次全370。
- 官方完整3条+独立新进程第1/第3条逆序，共5条真实预测，53/53检查通过；按ID完整预测一致、初始化每进程一次、每样本独立空store关闭、完整历史摘要不变、A dropped_turns=0。每条2次JSON解析失败后A真实文本fallback_rules，回复来自模型、情绪/画像rules；质量/官方分数未测。
- 原始3条CPU均值26,560.4208ms，samples=rounds=3、required_rounds=100、complete=false按参考算法，不是假失败/漏生成；不能与双4090分数等同。成功输出SHA `52e5d3e9323e51e9caf92fc278f4ed26aff5e68c6ec9d283f972369cd480d4c0`。
- 回退开发候选原结果保留 `reports/integration/.b5-work/real-20261010T154147Z-f99da41f/original-result`，逆序在同级reversed-result。A原配置/8文件/许可仍在 `.b4-work/real-assets`，实际CPU环境 `.runtime/b4-real-env`。这些忽略资产留本机，不上传大权重。所有自建模型/checker进程已停止。
- B5运行/范围与结果：[B5验收](B5验收.md)、[结构化结果](b5-verification.json)、[真实报告](b5-real-offline.json)。生产运行 `python submission/participant/run_inference.py TEST RESULT --config LOCAL_CONFIG`，校验 `python submission/participant/check_output.py TEST RESULT`。禁止覆盖已有任一官方结果文件；真实helper见验收，不重复下载资源。
- 无B5人工技术缺项；进程socketguard与CPU候选不等于B6禁网GPU Docker。Linux conda_env/镜像、挂载硬链接、GPU运行、50G冻结与参赛回退留B6，平台上传留B7；A训练候选/C页面由各自交付。
- 实现/验收提交 `a571fcf846dbeb8bde7b7bb661b396d3e5ea5e73` 已实际推送，创建 [PR #9](https://github.com/ZZZzzz-metal/digital-person/pull/9)，目标main，21个文件仅B分工区域，创建时open/未合并且head与本地一致。本文发布记录另作文档提交并推送到同一PR；不得把用户未来合并预写成已完成。下一轮只读核对PR#9实际状态后再做用户点名的B6。

- B4 启动只读确认 PR #7 已合并，main 当时为 `259fac62d8d5bc8ceb6104e1d49b68cfd063996b`；A model/a_impl/prompts 与 A0–A7 报告已取得只读参考副本，不改项目 A 文件或 fetch/pull/merge。共享聊天合同已先更新。
- B4当前实际运行方法与剩余项见上节/B4验收；A源码只读副本为 `../tmp/b4_20261010/upstream-A/src`，可配合公开 b4-a-source-check.json 核验后复现，不需要重下载基线或重装环境。不得将准备报告的 model_inference_verified=false 误读为最终真实HTTP未通过，它们是不同时间/范围的记录。

1. 核对当前分支和工作区，再阅读本轮验收记录。若记录说已通过而代码/锁/样例后来改变，仅重跑受影响的最小检查。
2. B0–B5已验证，未变的部分不重复从头核对、重装或重测；用户手动合并/拉取。下一轮先读当前 B6 状态/发布记录，仅继续未通过的环境验证。
3. 用户已点名B6；不提前进入B7上传。C页面现已交付，本轮未联调；本机真实CPU结果不能替代A训练候选/正式容器验收。
4. 正式模型、训练、GPU 容器、可回退参赛候选和赛事上传尚未验收；需要相应后续阶段实际运行，不能由 B1 演示成功替代。

主要依据：[总约定](../../docs/分工/00-总约定.md)、[B 任务书](../../docs/分工/B-记忆后端与参赛部署.md)、[B0 验收](B0验收.md)、[官方答复](B0-官方答复-2026-10-10.md)。本文件不保存账号、密码、cookie、token 或真实聊天。
