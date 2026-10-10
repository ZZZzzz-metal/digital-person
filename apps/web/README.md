# apps/web 前端数字人与伴学交互界面

> 分工 C（产品交付负责人）负责区域。
> 采用 React 18 + TypeScript + Vite 构建，包含前端代码、自研本地 SVG 表情素材与唯一前端锁文件 `package-lock.json`。
> 严格遵循 `docs/分工/00-总约定.md` §5、§8 合同。

## 目录结构

```text
apps/web/
├── package.json              前端依赖配置与脚本
├── package-lock.json         唯一前端锁文件（归 C 维护）
├── tsconfig.json             TypeScript 编译配置
├── vite.config.ts            开发服务器与反向代理配置
├── index.html                SPA 入口
├── .env.example              环境变量样例
├── .env                      默认环境配置（指向本地后端 http://127.0.0.1:8000）
├── .env.mock                 本地纯前端 Mock 模式配置
├── src/
│   ├── main.tsx              React 挂载入口
│   ├── App.tsx               主应用交互布局与状态机
│   ├── index.css             响应式界面样式
│   ├── api/
│   │   ├── types.ts          与合同一致的 DTO 类型定义与北京时间转换工具
│   │   ├── client.ts         固定 API 客户端（带 Cookie 凭证与真实错误映射）
│   │   ├── client.test.ts    单元测试（覆盖全部方法、Mock状态机、错误与格式化）
│   │   └── mock.ts           纯本地 Mock 演示服务（标记 is_mock: true，演示数据）
│   ├── assets/
│   │   ├── neutral.svg       平静注视（原创矢量表情，离线自包含）
│   │   ├── smile.svg         微笑陪伴（原创矢量表情，离线自包含）
│   │   ├── concern.svg       关切倾听（原创矢量表情，离线自包含）
│   │   ├── listening.svg     专注倾听（原创矢量表情，离线自包含）
│   │   └── AVATAR_LICENSE.md 本地素材许可与无 CDN 声明
│   └── components/
│       ├── Header.tsx        导航栏、模式标识、健康状态与故障模拟工具
│       ├── AvatarDisplay.tsx 数字人表情呈现、情绪估计与模型耗时元信息
│       ├── SessionList.tsx   会话管理列表、新建与删除（长期记忆保留说明）
│       ├── ChatWindow.tsx    对话气泡、参考记忆卡片、重试保留 turn_id 与输入限制
│       └── MemoryPanel.tsx   事实记忆 CRUD、开启/关闭切换与清空确认
```

## 常用脚本

```bash
# 1. 安装依赖（生成/校验 package-lock.json）
npm install

# 2. 真实后端模式启动（默认通过 Vite 代理访问 http://127.0.0.1:8000；若本地 8000 端口被占，可配置 VITE_BACKEND_URL=http://127.0.0.1:8001）
npm run dev

# 3. 纯本地 Mock 模式启动（不启动后端即可完整演示，页面显式标识“演示数据”）
npm run dev:mock

# 4. 类型检查
npm run typecheck

# 5. 单元测试与端到端集成测试（Vitest：覆盖接口契约、状态机、幂等、三大演示剧本与真实 FastAPI 端到端）
npm run test

# 6. 生产环境构建打包
npm run build
```

## 关键设计与合同遵守说明

1. **真实模式与 Mock 隔离**：
   - 默认模式连接真实后端，请求带 `credentials: 'include'`，由后端分配 `b2_anon` cookie。
   - 真实后端连接失败或返回 4xx/5xx 时，页面直接如实展示错误（如 `[MODEL_UNAVAILABLE] 模型暂不可用`），**绝不静默降级为假回复**。
   - Mock 模式仅在 `VITE_MOCK=1` 或界面明确切换时生效，所有响应标记 `is_mock: true`，页面顶部与卡片均浮动显示“演示数据”。
2. **幂等性与错误重试**：
   - 首次点击发送时生成 `client_turn_id`，等待期间禁用重复点击；
   - 若遭遇 503/409/网络错误，用户消息保留在界面并提供“重试”按钮，重试严格保持原 `client_turn_id`。
3. **长期记忆与心理边界**：
   - 严格支持五个白名单 key：`preferred_name`、`study_goal`、`exam_subject`、`response_preference`、`hobby`；
   - 仅在用户主动点击“确认保存”后持久化，不自动将模型推测的情绪或画像转为事实记忆；
   - “关闭记忆”保留已有数据但不做检索；“清空记忆”需二次确认；删除会话不删除记忆。
   - 情绪展示严格标注为“情绪估计”，不作为心理诊断；检索候选标记为“本轮参考记忆”。
4. **100% 本地自包含**：
   - 数字人四种表情为项目自制 SVG 图元，零外部图片、字体或 CDN 请求，满足离线断网运行验收要求。
