# digital-person
综合情感陪伴对话模型(数字人)任务:聚焦情感理解、记忆融合与共情表达。

三人各自启动一个 AI Agent，并行完成模型、后端部署和前端作品材料，优先把可运行的参赛闭环做出来。

先阅读 [开始这里](开始这里.md) 和 [总约定](docs/分工/00-总约定.md)，再复制各自任务书中的 Agent 启动指令：

| 分工 | 任务书 |
|---|---|
| A：模型训练与评测 | [A 任务书](docs/分工/A-模型训练与评测.md) |
| B：记忆、后端与参赛部署 | [B 任务书](docs/分工/B-记忆后端与参赛部署.md) |
| C：前端数字人与作品交付 | [C 任务书](docs/分工/C-前端数字人与作品交付.md) |

当前 B4 已接入聊天编排、历史与记忆、成功去重和失败重试；B5 增加直接调用 A 本地模型的官方离线入口、严格输入输出校验与计时报告。入口代码见 [submission/participant](submission/participant/README.md)，本阶段实际结果见 [B5 验收](reports/integration/B5验收.md)。Linux/GPU 禁网镜像在 B6 实测。

后续接手先读 [B 进度记录](reports/integration/B-进度记录.md)，核对分支和工作区变化，只补读当前阶段需要的资料。Agent 负责推送分支和 PR，用户手动合并、拉取；每完成用户点名的阶段就停止。

## 开发演示后端（B1–B4）

在项目根目录执行以下 PowerShell 命令。实际验收使用 Windows、Python 3.12.14；下列锁只包含后端与协议测试，A 的训练/模型依赖及最终 GPU 容器依赖另行确定。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-backend.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
$env:B2_MODE = "stub"
.\.venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

另开一个 PowerShell 窗口检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

默认 stub 返回 `status=ok`、`model_ready=true`、`is_mock=true`、`model_version=stub-b1`。`model_ready` 表示演示 engine 已初始化，不是模型效果或正式测评通过。当前提供健康、四个会话操作、五个记忆操作和 POST `/api/chat`。

默认数据文件 `.runtime/b2.sqlite3` 位于项目根目录下，自动创建且被 Git 忽略；如需更换本项目数据文件，启动前设置 `$env:B2_DB_PATH = ".runtime/other.sqlite3"`。后端重启后，同一浏览器 cookie 可以继续读取旧会话。首次 `/api` 访问由服务端分配匿名 cookie `b2_anon`，前端不传 user_id；未知 cookie 不会获得他人的身份。丢失 cookie 会创建新匿名用户，这里没有账号恢复流程。

会话接口使用同一个 cookie，返回原共享 schema：

| 操作 | 方法与路径 | 输入/结果 |
|---|---|---|
| 创建 | POST `/api/sessions` | `{}` 或 `{\"title\":\"新会话\"}` → SessionDTO |
| 列表 | GET `/api/sessions` | 当前用户 SessionDTO 数组 |
| 消息历史 | GET `/api/sessions/{id}/messages` | 按保存顺序的 Message 数组，新会话为 `[]` |
| 删除 | DELETE `/api/sessions/{id}` | `{\"ok\":true}`，只删该会话及 messages/turns |

不属于当前 cookie 的会话和不存在的会话统一返回 404/error 对象；参数错误返回 400/error 对象。有有效 pending 的会话删除返回 409，完成或释放后可重试删除。成功删除只触及该会话，用户级长期记忆保留。C 可对接聊天、会话和记忆接口，页面需清楚显示 health/回复中的 is_mock。

另开一个 PowerShell 窗口可以连续检查同一用户：

```powershell
$b2Session = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/sessions -ContentType application/json -Body '{"title":"B2演示会话"}' -SessionVariable b2Cookies
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/sessions -WebSession $b2Cookies
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/sessions/$($b2Session.id)/messages" -WebSession $b2Cookies
Invoke-RestMethod -Method Delete -Uri "http://127.0.0.1:8000/api/sessions/$($b2Session.id)" -WebSession $b2Cookies
```

数据库只保存 cookie token 的 SHA-256 和独立 user_id，不保存原 cookie；token 不写入验收报告。cookie 默认 HttpOnly、SameSite=Lax，Secure=false 用于本机 HTTP；HTTPS 部署时设置 `B2_COOKIE_SECURE=1`。

记忆接口沿用同一个 cookie，只有用户主动保存才写入：

| 操作 | 方法与路径 | 输入/结果 |
|---|---|---|
| 查看 | GET `/api/memories` | `{enabled,items}`；关闭时 items 为 `[]` |
| 开关 | PUT `/api/memories/settings` | `{\"enabled\":false}` 或 true → `{enabled,items}` |
| 保存/纠正 | PUT `/api/memories/{key}` | `{\"value\":\"线代\"}` → MemoryItem；同 key 替换旧值并保留 id |
| 删除一项 | DELETE `/api/memories/{id}` | `{\"ok\":true}`；他人的 id 与不存在均 404 |
| 清空 | DELETE `/api/memories` | `{\"ok\":true}`；只清当前用户，不改变开关 |

key 仅允许 preferred_name、study_goal、exam_subject、response_preference、hobby。value 去首尾空白后为 1–200 字符。关闭后不读取事实、不接受保存（409 `MEMORY_DISABLED`），事实仍保留；重新开启后可见。关闭期间仍允许用户明确删除或清空。新会话和删除会话都不会删除长期记忆。

以下用虚构值演示保存、纠正和开关，客户端须保留 cookie；`ConvertTo-Json` 和 UTF-8 字节避免中文正文编码问题：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/memories -SessionVariable b3Cookies
$b3Body = [Text.Encoding]::UTF8.GetBytes((@{value='高数'} | ConvertTo-Json -Compress))
$b3Fact = Invoke-RestMethod -Method Put -Uri http://127.0.0.1:8000/api/memories/exam_subject -ContentType 'application/json; charset=utf-8' -Body $b3Body -WebSession $b3Cookies
$b3Body = [Text.Encoding]::UTF8.GetBytes((@{value='线代'} | ConvertTo-Json -Compress))
Invoke-RestMethod -Method Put -Uri http://127.0.0.1:8000/api/memories/exam_subject -ContentType 'application/json; charset=utf-8' -Body $b3Body -WebSession $b3Cookies
Invoke-RestMethod -Method Put -Uri http://127.0.0.1:8000/api/memories/settings -ContentType application/json -Body '{"enabled":false}' -WebSession $b3Cookies
Invoke-RestMethod -Method Put -Uri http://127.0.0.1:8000/api/memories/settings -ContentType application/json -Body '{"enabled":true}' -WebSession $b3Cookies
Invoke-RestMethod -Method Delete -Uri "http://127.0.0.1:8000/api/memories/$($b3Fact.id)" -WebSession $b3Cookies
Invoke-RestMethod -Method Delete -Uri http://127.0.0.1:8000/api/memories -WebSession $b3Cookies
```

`build_memory_context(user_text,store.list_memories(user_id).items)` 为无模型、HTTP 或数据库依赖的纯检索函数，最多五条相关事实，以 JSON 数据加入说明，返回候选列表；不相关或关闭时文本为空。B4 将它传给 A 的 engine。返回候选不证明模型实际引用或完全抵抗提示注入；它不自动保存记忆。

聊天沿用同一个 cookie。服务端只写完整成功轮次；失败保留原输入和原 client_turn_id 后重试。下面是独立虚构演示：

```powershell
$b4Session = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/sessions -ContentType application/json -Body '{}' -SessionVariable b4Cookies
$b4Body = [Text.Encoding]::UTF8.GetBytes((@{session_id=$b4Session.id;client_turn_id='demo-turn-1';text='我担心考试。'} | ConvertTo-Json -Compress))
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/chat -ContentType 'application/json; charset=utf-8' -Body $b4Body -WebSession $b4Cookies
```

已成功的同 turn ID 返回原 response，不再次生成。相同文本但新 turn ID 是新的一轮。最近最多 12 条历史按完整轮次裁剪至 4,000 字符，当前输入最多 2,000 字符且只追加一次；A 再负责 tokenizer 上限。纯 `run_turn(CoreRequest,engine)` 不需要 HTTP、cookie、数据库或启动服务，不加载模型。B5 官方入口使用独立 OfficialRequest/OfficialPrediction，不套用这些演示长度限制。

同会话正在生成返回 409 `TURN_IN_PROGRESS`；同应用的模型正在生成返回 503 `MODEL_BUSY`；真实模型缺失/输出损坏/模型异常返回 503 `MODEL_UNAVAILABLE`；HTTP 等待超过 `B2_CHAT_TIMEOUT_SECONDS` 返回 503 `MODEL_TIMEOUT`。默认 60 秒，可设为大于 0 且不超过 240 秒，低于存储默认租期；这些是演示策略，不是官方限时。超时或取消不写消息、释放请求占用；Python 线程无法强杀，模型仍计算时 gate 保持占用，迟到结果丢弃。若模型一直卡住，需要重启该后端进程。

若 Windows 临时目录不可写，先在项目内准备临时目录，再重试环境安装：

```powershell
New-Item -ItemType Directory -Force .runtime/tmp | Out-Null
$env:TEMP = (Resolve-Path .runtime/tmp).Path
$env:TMP = $env:TEMP
```

真实模式先由 A 准备完整本地模型、配置和依赖，再停止旧进程，重新启动：

```powershell
$env:B2_MODE = "real"
$env:B2_MODEL_CONFIG = "weights/inference_config.json"
.\.venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

真实 engine 在应用启动时创建一次，health 查询不会反复加载。导入共享包本身不加载模型。real 初始化失败时 health 仍返回 HTTP 200，但内容为 `status=degraded`、`model_ready=false`、`is_mock=false`、`model_version=unavailable`；详细原因写在启动日志，不能仅看 HTTP 200 判断可用。不会自动换成 stub。健康就绪也不代替真实生成验收。

`.env.example` 仅为环境变量参考，本骨架不自动读取 `.env`；使用上面的 PowerShell 环境变量。前端 C 的开发代理目标为 `http://127.0.0.1:8000`，代理 `/health` 和 `/api`；按 [共享合同](contracts/README.md) 对接。

本轮检查方法：

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe contracts/export_schema.py --check
.\.venv\Scripts\python.exe -m pytest tests/server -q
.\.venv\Scripts\python.exe reports/integration/verify_b4_http.py --mode stub --port 0
```

最后一项使用独立临时 SQLite 文件，启动自己的 stub 后端，实际检查六轮聊天、原请求重复、纠正/关闭、新会话记忆和两用户隔离，然后关闭自己创建的进程。全部事实为虚构，stub 结果不是真实模型验收。使用 `--port 0` 分配空闲端口，不关闭已有服务。历史 B1–B3 报告保留；其 HTTP 脚本检查历史路由快照，当前版本运行 B4 脚本。真实引擎复现方法与本机资源位置见 [B4 验收](reports/integration/B4验收.md)。

B2 存储提供 reserve/complete/abort，B4 已接入聊天：同会话一次占用，完成后按 turn ID 返回原结果，两条消息和 turn 结果原子保存，失败释放占用而不写半条消息。默认 pending 租期 300 秒，用于进程中断后的恢复；旧 token 无法提交或释放后来创建的占用。该租期是演示存储策略，不是官方推理限制。

## 官方资料与离线入口

2026-10-09 收到官方工程包后的入口：

- [官方接口核对](docs/官方接口核对.md)：实际入口、输入输出、平台环境示例、包内问题和剩余缺项。
- [官方合同快照](contracts/official/README.md)：16 类情绪、三组用户画像、记忆引用及模型生成约束。
- [官方参考脚本](submission/README.md)：小文件原样快照，模型权重和训练大数据不在 Git 内。
- [静态核对记录](reports/integration/官方包静态核对.md)：真实数据规模、结构检查和异常位置，不是模型效果报告。
- [2026-10-10 官方答复](reports/integration/B0-官方答复-2026-10-10.md)：用户转贴的五条答复及执行口径；[有效输出合同](contracts/official/effective_submission.schema.json) 仅移除旧 ID 正则，保留原始文件。
- [B0 验收](reports/integration/B0验收.md)：34/34 协议检查通过；未说明的细项和后续模型/容器验收分别记录。

B0 核心协议核对完成；用户接受不阻碍开发的细项保留未知，不再主动追问。B1–B4 演示后端已验收，B5 官方 CPU 离线流程的实际结果见本轮报告；这些结论不能替代禁网容器或赛事提交验收。

官方运行方式（需先准备实际 Linux Docker 镜像、参考入口的 conda_env 和完整本地模型；镜像版本可参考平台，不限制）：

```bash
bash /root/participant/start.sh TEST_FILE RESULT_DIR
```

团队 B5 入口生成 submission.jsonl 和 performance_report.json，直接加载本地模型，一次初始化，不启动 HTTP。ID 按答复原样回填并独立检查顺序/数量；全量输出，只统计前 100 条。3 条公开样例按参考逻辑 complete=false，表示不足 100 条计时，并非漏生成。正式评测为两张 4090，每卡标称 24G，官方不设超时/上下文限制；A 的选用模型仍有 tokenizer 上限，超限会失败，不修改 A 配置掩盖问题。memory_refs 不评分，团队默认 []。标准 Docker 镜像须在“50G以内”，具体计量口径仍未知。

合并 A/B 后，在 A 完整本地模型和兼容依赖已准备的环境中，开发机可直接执行：

```powershell
python submission/participant/run_inference.py submission/official-reference/test_inference_data.jsonl .runtime/b5-result --config weights/inference_config.base.json
python submission/participant/check_output.py submission/official-reference/test_inference_data.jsonl .runtime/b5-result
```

结果目录须为新目录，已有两个官方结果文件任意一个都会拒绝覆盖。详细配置、已验证本机资源和复现方法见 [入口说明](submission/participant/README.md) 与 [B5 验收](reports/integration/B5验收.md)。此处 python 必须是装有 A 模型依赖的解释器，纯后端 .venv 不含 Torch/Transformers。

训练由 A Agent 执行，B 使用算力做集成与离线验收；人提供实例和必要权限。Agent 推送 PR，用户手动合并和拉取。

## B6 完整包与容器验证

完整打包、镜像配方与自动验证工具已交付，79 项专项检查通过。实际完整包位于本机 `D:/B2-B6-20261011/candidate-a34f8df`，沿用 A 已发布基线/原配置，包含模型本体和 tokenizer。模型包不在 Git 中；后续本机下载、大模型与镜像均放 D 盘。

正式禁网 GPU Docker 验收仍因运行环境权限阻塞：平台两张 4090 的 CUDA 运算成功，但嵌套容器启动被只读 cgroup 限制；备用 runc 又因 proc 挂载无权限失败。用户授权自行配置后，本机已实际装好 WSL3.0.1、启用虚拟机组件，Windows要求一次重启；[本机续做](reports/integration/B6-本机环境续做.md)已保存自动准备容器与验收的下一步。平台测试实例已关机。GPU 能力和工具检查不等于参赛镜像已通过；现阶段仍保留 B5 已验证 CPU 开发回退，不进入 B7。

部署 CLI、完整清单、实际证据与仅需人解决的 Docker/GPU 环境条件见 [部署说明](deploy/README.md)、[离线验收](reports/integration/离线验收.md) 和 [进度记忆](reports/integration/B-进度记录.md)。环境到位后运行 `deploy/verify_container.py`，同一实际 image ID 禁网读取官方 JSONL、真实 GPU 推理、独立校验并导出回退镜像；成功才标记正式验收通过。
