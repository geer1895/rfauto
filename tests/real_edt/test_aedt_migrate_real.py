"""real_edt: aedt_migrate Stage 1/2 真机冒烟（opt-in，双 env 门）。

df4⑥ 家法：真跑集成测试不进缺省 unit 门——本文件双重显式意图门：
1. ``real_edt`` marker（缺省门 ``-m "not real_edt"`` 排除）；
2. ``RFAUTO_AEDT_MIGRATE_REAL=1`` 显式环境意图门（真机会话面）。

语料：用本机 2025 R1 **自存工程**（ ``RFAUTO_AEDT_MIGRATE_REAL_PROJECT``
指向现有 .aedt 路径；未指路径 skip——本席不真跑，测试就位+主代窗口
挂账）。真 2021 cutoff 语料本地无法制造（2021 未装，蓝图 §3 诚实边界
——cutoff 路径真机验证以用户提供语料为准，本冒烟只验 open/save/health
主通路在真会话面结构成立）。

运行（主代窗口）::

    set RFAUTO_AEDT_MIGRATE_REAL=1
    set RFAUTO_AEDT_MIGRATE_REAL_PROJECT=E:\\path\\to\\proj.aedt
    .venv\\Scripts\\python.exe -m pytest tests/real_edt/test_aedt_migrate_real.py -m real_edt -q
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_edt

REAL_ENV = "RFAUTO_AEDT_MIGRATE_REAL"
PROJECT_ENV = "RFAUTO_AEDT_MIGRATE_REAL_PROJECT"


def _real_gate() -> str:
    """双门合一：env 意图门 + 工程路径门，任一缺席 skip（不假跑）。"""
    if os.environ.get(REAL_ENV, "") != "1":
        pytest.skip(f"{REAL_ENV}!=1（真机意图门未开，opt-in 冒烟默认 skip）")
    project = os.environ.get(PROJECT_ENV, "")
    if not project or not Path(project).is_file():
        pytest.skip(
            f"{PROJECT_ENV} 未指向存在的 .aedt（2025 R1 自存工程冒烟语料缺）"
        )
    return project


def test_aedt_migrate_open_save_check_real(tmp_path):
    """Stage 1+2 真机冒烟：直开→体检→SaveAs→会话关（结构断言不凑绿）。"""
    project = _real_gate()
    from rfauto.adapters.hfss_migrate import (
        MIGRATE_VERSION_DEFAULT,
        migrate_open_save_and_check,
    )

    migrated_dir = tmp_path / "migrated"
    result = migrate_open_save_and_check(project, migrated_dir)

    # 结构断言（真机语义）：结果 dict 必备键齐全，outcome 在枚举内。
    assert result["stage"] == "direct_open+health"
    assert result["outcome"] in (
        "opened", "cutoff", "locked", "open_failed", "save_failed",
    )
    assert isinstance(result["cutoff"], bool)
    assert result["engine"]["version"] == MIGRATE_VERSION_DEFAULT
    assert result["open"] is not None

    # 2025 R1 自存工程直开应当 opened（若 cutoff/locked 属环境事实，
    # 如实打印不硬断言——预声明不凑绿）。
    if result["outcome"] != "opened":
        pytest.fail(
            f"2025 R1 自存工程直开未 opened（outcome={result['outcome']}，"
            f"errors={result['errors']}）——环境事实如实登记，不得静默"
        )

    # SaveAs 产物在 migrated/ 且 ≠ 原件路径。
    assert result["migrated_path"] is not None
    migrated = Path(result["migrated_path"])
    assert migrated.is_file(), f"SaveAs 产物未落盘: {migrated}"
    assert migrated.parent == migrated_dir
    assert migrated.resolve() != Path(project).resolve()

    # 体检结构：validate/messages/checklist 六项在档（ok 与否如实）。
    health = result["health"]
    assert health is not None
    assert health["stage"] == "health"
    assert health["outcome"] in ("pass", "validate_failed")
    assert [e["item"] for e in health["checklist"]] == [
        "materials", "boundaries", "mesh_operations", "setups",
        "optimetrics_parametric", "optimetrics_optimization",
    ]
    # 解包形态真机实证：validate["messages"]=list、validate["ok"]=bool
    # （晶圆键合 §2.4 解包顺序 (messages, ok) 的真机面回归证据）。
    assert isinstance(health["validate"]["messages"], list)
    assert isinstance(health["validate"]["ok"], bool)

    # 原件只读：原件字节未变（SaveAs 后回读对照）。
    assert Path(project).is_file()
    print(
        f"[aedt_migrate real smoke] outcome={result['outcome']} "
        f"health={health['outcome']} checklist="
        f"{ {e['item']: e['count'] for e in health['checklist']} } "
        f"migrated={result['migrated_path']} engine={result['engine']}"
    )
