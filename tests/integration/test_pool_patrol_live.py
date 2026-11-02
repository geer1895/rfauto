"""pool_patrol 真仓活扫对照（opt-in；tests/unit/全量门收集面外）。

单元门等价物=tests/unit/test_pool_patrol.py::TestGoldCalibrationRealRepo::
test_default_gold_rate_is_one（读冻结帧夹具 tests/fixtures/pool_patrol_
frame.json，秒级）。本件对活仓全扫（git 全史两趟+impl 面 src/tests/
scripts 全树逐行扫，实测 ~4min 且随仓库增长膨胀），只在显式刷新验证/
夜档复核时启用（df4⑥ 家法：真跑集成不进缺省 unit 门）：

    RFAUTO_POOL_PATROL_LIVE=1 .venv/Scripts/python.exe -m pytest \\
        tests/integration/test_pool_patrol_live.py -q

断言与单元门夹具件逐字相同（同一性质钉：活帧上金标 rate=1.0）。用途：
① 夹具刷新后的显式活扫复核（刷新脚本另有内建等价门，本件是门外的
人工复核通道）；② 夹具被怀疑过期时对照活帧定分漂移归因（合法湖演化
vs 行为变化）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.service.pool_patrol_service import pool_patrol

REPO = Path(__file__).parent.parent.parent
POOL_DOC_REAL = REPO / "docs" / "plan_expansion_pool_20260924.md"


@pytest.mark.slow  # 终门 DURATIONS 慢件口径（真仓活扫 ~4min；本层不在门收集面）
def test_default_gold_rate_is_one_live():
    if os.environ.get("RFAUTO_POOL_PATROL_LIVE") != "1":
        pytest.skip("opt-in 真仓活扫对照：设 RFAUTO_POOL_PATROL_LIVE=1 启用"
                    "（git 全史+impl 面全扫 ~4min；单元门等价物读冻结帧夹具）")
    if not POOL_DOC_REAL.exists():
        pytest.skip("池登记文档不在帧内（公开仓无此文件）——真仓校准 skip")
    res = pool_patrol({"pool_doc": str(POOL_DOC_REAL), "gold": True})
    assert res["ok"] is True
    cal = res["calibration"]
    assert cal["rated"] >= 15, f"金标样本不足: {cal['rated']}"
    assert cal["rate"] == 1.0, (
        f"金标不一致={cal['mismatches']}（修工具不修金标）")
    assert res["calibration_gate"] == "PASS"
