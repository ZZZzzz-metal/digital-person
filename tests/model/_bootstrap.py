"""A 分工测试脚本的公共引导：定位仓库、把 ``src/`` 加入 sys.path、写报告。

A 的入口脚本不依赖 pytest 或 conftest，也不改 B 负责的 pyproject/conftest，
所以每个脚本自己调用 ``bootstrap()``。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
REPORTS_DIR = REPO_ROOT / "reports" / "model"
DATA_DIR = REPO_ROOT / "data"
WEIGHTS_DIR = REPO_ROOT / "weights"


def bootstrap() -> Path:
    """把 ``src/`` 放到 sys.path 首位并返回仓库根目录。"""
    src = str(SRC_DIR)
    if src not in sys.path:
        sys.path.insert(0, src)
    return REPO_ROOT


def write_report(name: str, payload: Any) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: JSON 解析失败: {exc.msg}") from exc
    return rows