# A0 MockEngine 交付说明

**结论：MockEngine 已交付并全部通过检查。`is_mock=True`、`model_version="mock-v1"`，不加载任何权重。**

> MockEngine 只验证程序链路（接口、字段、枚举、映射、边界），
> **不能用于评价模型效果**，也不代表真实引擎的行为。

## 交付物

| 文件 | 说明 |
| --- | --- |
| [src/b2_core/model.py](../../src/b2_core/model.py) | `MockEngine` / `ModelEngine` / `create_engine` |
| [tests/model/smoke_mock.py](../../tests/model/smoke_mock.py) | A0 冒烟检查 |
| [a0_mock_smoke.json](a0_mock_smoke.json) | 检查报告 |
| [a5_eval_mock.json](a5_eval_mock.json) | MockEngine 跑完整的 12 案例 |

## 检查结果（全部通过）

| 检查 | 结果 |
| --- | --- |
| `is_mock` | `True` ✓ |
| `model_version` | `"mock-v1"` ✓ |
| 6 个演示用例 | 情绪与 `is_mock` 全部符合预期 ✓ |
| 多轮用例（3 条消息） | 正常返回，未复述用户原话 ✓ |
| 官方样本 3 条 | `schema_valid=True`，`problems=[]` ✓ |
| 失败项 | **0** |

## Mock 的行为约定

| 项 | 行为 |
| --- | --- |
| 加载 | **不加载任何权重**，构造即可用 |
| 情绪 | 6 类演示情绪：`neutral / happy / sad / anxious / angry / unknown` |
| 演示表情映射 | `happy→smile`、`sad/anxious→concern`、`angry→listening`、`neutral/unknown→neutral` |
| 官方情绪 | 映射到官方 16 类，供 `generate_official` 使用 |
| 回复 | 按情绪选**固定片段**组合，**不回显用户输入**（回归检查项） |
| 空输入 | 演示合同下归为 `unknown`，不抛异常 |
| 非空但无关键词 | 归为 `neutral`（不是 `unknown`） |
| 官方输出 | 四字段齐全、枚举合法、`memory_refs=[]` |

## Mock 评测的已知不足

MockEngine 跑 12 案例时有 **1 条规则违规**（[a5_eval_mock.json](a5_eval_mock.json)）。
这是预期的：mock 是模板拼接，本来就不会"记住"多轮上下文里用户纠正过的科目。
**mock 的作用是让 B/C 在没有权重时也能联调，不是拿来刷分的。**