# 训练数据来源与许可

## 一句话结论

A 的训练数据**全部是本地自动生成的虚构对话**，不含任何真实用户数据，
**也不是比赛官方训练数据**。它的作用是打通「数据处理 → 训练 → 保存 → 重载 → 评测」这条链路，
以及给出一份可复现的基线，而不是刷分。

## 文件链路

```
data/training/make_synthetic_sessions.py   ← 生成脚本（标准库，固定种子，确定性）
        ↓
data/training/raw/sessions.jsonl           ← 200 个虚构会话（原始）
        ↓
data/training/build_dataset.py             ← 校验 / 去重 / 按会话划分 / 渲染
        ↓
data/training/processed/train.jsonl        ← 200 条有效训练样本（chat 150 + official 50）
data/training/processed/valid.jsonl        ← 120 条验证样本
data/training/processed/holdout.jsonl      ← 80 条留出样本
data/training/processed/dataset_report.json← 划分与统计报告
```

## 来源与许可

| 项 | 内容 |
| --- | --- |
| 来源 | `make_synthetic_sessions.py` 自动生成，固定种子 `20251012` |
| 语料性质 | 全虚构。人物只有 小然 / 小林 / 小舟 / 小雨 / 阿哲 / 小满，均为虚构角色 |
| 许可 | 内部虚构数据，可用于本项目；不含真实个人信息 |
| 可复现性 | 同一种子下多次运行输出 sha256 完全一致（已实测） |
| 原始文件 sha256 | `327A2E34229543F4CC52A5257A6928EEB66317970BD31E196DC651E19A111D99`（279,971 B） |

## 数据结构

- 200 个会话，6 类各 33–34 个：
  学习压力 / 宿舍相处 / 日常倾诉 / 话题切换 / 积极分享 / 记忆引用与纠正。
- 每会话 6–14 条消息，严格 user/assistant 交替，**以 user 开头、以 assistant 结尾**。
- 每条会话可带 0–3 条 `memory_context`（`fact` / `event` / `preference`）。

## 划分方式

- **按完整会话划分**，同一会话只落在一个集合里。
- 划分由 `session_id` 的 sha1 排序决定，与输入顺序无关，重复运行结果一致。
- 训练 160 / 验证 20 / 留出 20 个会话。
- `data/eval/cases.json` 的 12 个评测案例来自 A 手工编写，**与训练会话没有重叠**，
  也不参与训练。

## 训练样本的构造

- 一个预测点 = 「截至某条 user 的上下文」+「它的下一条 assistant 回复」。
- 上下文最后一条一定是该 user，**绝不含它的回复及其后的任何内容** → 训练输入不混入答案。
- 两种渲染：
  - `chat`（150 条）：演示合同，system 用 `src/b2_core/prompts/empathy.py` 的人设与记忆块。
  - `official`（50 条）：官方合同，system 用 `_official.py` 的官方 system prompt，
    整段历史渲染成一条 user 消息。
- 超长样本**裁剪最旧的完整轮次**（保留 system 与当前问题），不丢弃样本；
  这与推理时的上下文裁剪是同一套规则。

## 必须知道的质量限制

1. **助手回复来自模板池组合**，与用户具体内容的相关性有限；它教的是格式、长度和承接方式，
   不是高质量共情。
2. **official 样本的情绪与画像由 A 的规则标注**（`src/b2_core/a_impl/emotion_rules.py`），
   不是人工标注，也不是官方标签。用它训练只能学「输出格式与分布」，不能指望学到官方判分标准。
3. **合成 `memory_context` 是会话级的，没有时间戳**。构建时只在第 2 个预测点之后注入，
   避免首轮凭空出现背景；但它仍不是严格按时间累积的记忆。
4. 数据量很小（200 条有效样本），是**打通链路的最小规模**，不足以带来明显的能力提升。
5. 全部为简体中文，没有多语言、没有方言、没有真实口语噪声。

这些限制在 `data/training/processed/dataset_report.json` 的 `limitations` 字段里也有记录。