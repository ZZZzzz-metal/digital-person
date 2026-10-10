# digital-person
综合情感陪伴对话模型(数字人)任务:聚焦情感理解、记忆融合与共情表达。

三人各自启动一个 AI Agent，并行完成模型、后端部署和前端作品材料，优先把可运行的参赛闭环做出来。

先阅读 [开始这里](开始这里.md) 和 [总约定](docs/分工/00-总约定.md)，再复制各自任务书中的 Agent 启动指令：

| 分工 | 任务书 |
|---|---|
| A：模型训练与评测 | [A 任务书](docs/分工/A-模型训练与评测.md) |
| B：记忆、后端与参赛部署 | [B 任务书](docs/分工/B-记忆后端与参赛部署.md) |
| C：前端数字人与作品交付 | [C 任务书](docs/分工/C-前端数字人与作品交付.md) |

当前 B1 交付共享类型、21 组 schema/虚构协议样例、可启动的后端健康接口和独立开发环境。B0 官方资料核对已经完成；聊天、会话、产品长期记忆和正式离线适配按 B2–B6 继续实施。

后续接手先读 [B 进度记录](reports/integration/B-进度记录.md)，核对分支和工作区变化，只补读当前阶段需要的资料。Agent 负责推送分支和 PR，用户手动合并、拉取；每完成用户点名的阶段就停止。

## 开发演示后端（B1）

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

默认 stub 返回 `status=ok`、`model_ready=true`、`is_mock=true`、`model_version=stub-b1`。`model_ready` 表示演示 engine 已初始化，不是模型效果或正式测评通过。本轮唯一业务路由是 `GET /health`；聊天、会话和记忆接口还未实现，访问会返回 404。

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

`.env.example` 仅为环境变量参考，本骨架不自动读取 `.env`；使用上面的 PowerShell 环境变量。前端 C 的开发代理目标为 `http://127.0.0.1:8000`，代理 `/health` 和后续 `/api`；当前 C 可按 [共享合同](contracts/README.md) 用自己的 mock 开工。

本轮检查方法：

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe contracts/export_schema.py --check
.\.venv\Scripts\python.exe -m pytest tests/server -q
.\.venv\Scripts\python.exe reports/integration/verify_b1_http.py --mode stub --port 8000
```

最后一项会短暂启动自己的后端、读取健康 JSON 并关闭该进程；运行时不要同时占用同一个端口，可用 `--port 0` 分配空闲端口。真实模式检查改为 `--mode real`，可能加载 A 的本地模型，不是正式离线测评。实测结果见 [B1 验收](reports/integration/B1验收.md)。

## 官方资料与离线入口

2026-10-09 收到官方工程包后的入口：

- [官方接口核对](docs/官方接口核对.md)：实际入口、输入输出、平台环境示例、包内问题和剩余缺项。
- [官方合同快照](contracts/official/README.md)：16 类情绪、三组用户画像、记忆引用及模型生成约束。
- [官方参考脚本](submission/README.md)：小文件原样快照，模型权重和训练大数据不在 Git 内。
- [静态核对记录](reports/integration/官方包静态核对.md)：真实数据规模、结构检查和异常位置，不是模型效果报告。
- [2026-10-10 官方答复](reports/integration/B0-官方答复-2026-10-10.md)：用户转贴的五条答复及执行口径；[有效输出合同](contracts/official/effective_submission.schema.json) 仅移除旧 ID 正则，保留原始文件。
- [B0 验收](reports/integration/B0验收.md)：34/34 协议检查通过；未说明的细项和后续模型/容器验收分别记录。

B0 核心协议核对完成；用户接受不阻碍开发的细项保留未知，不再主动追问。B1 已按用户点名启动。以上结论不表示模型、禁网容器或赛事提交已验收。

官方运行方式（需先准备实际 Linux Docker 镜像、参考入口的 conda_env 和完整本地模型；镜像版本可参考平台，不限制）：

```bash
bash /root/participant/start.sh TEST_FILE RESULT_DIR
```

生成 submission.jsonl 和 performance_report.json；可直接加载本地模型或由入口启动本地 vLLM。ID 按新答复原样回填，另做输入/输出对齐检查；只统计前 100 条耗时，全量输入仍须输出。正式评测为两张 4090，每卡标称 24G，官方不设超时/上下文限制；memory_refs 不评分，团队默认 []。标准 Docker 镜像须在“50G以内”，具体计量口径及不足 100 条时的 complete 规则尚未说明。该命令是原始参考入口说明，团队正式适配/镜像尚未验收；B1 健康后端不能替代它。

训练由 A Agent 执行，B 使用算力做集成与离线验收；人提供实例和必要权限。Agent 推送 PR，用户手动合并和拉取。
