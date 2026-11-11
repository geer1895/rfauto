"""动图批 4 测试 fixtures 构造器（Q-W2-4；**只落 tmp_path，禁写 runs/ 湖**）。

数据面=显式字面量构造（零随机零示意数据混入渲染链——这些文件是"数据源"
本身，供渲染器确定性消费）：

- :func:`make_stackup_layout_json` —— stackup_growth 用 layout_json
  （厚度分层字面量：底板 h=2.0 / 双段走线层 / 顶层单图元——段揭示锚用）；
- :func:`make_symbols_json` —— symbols_json 契约（单云/帧序列双形态；
  符号=显式字面量 [i,q] 对）；
- :func:`make_budget_json` —— budget_json 契约（发射→接收扣减级表）；
- tuning_replay 复用批 1 fixtures（``_anim_fixtures.make_run_dir`` +
  ``make_sparams_csv``），本文件不重复构造。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ── 缺省字面量（测试独立复算锚引用的原始数值）─────────────────────────────────
# 叠层：substrate(1 图元 h=2.0) → traces(2 图元=1 段) → mask(1 图元 h=1.0)
# 帧槽=1+0(无段)+1+1(1 段)+1+0 = 5；高度∝厚度锚：substrate 像素高 : mask
# 像素高 = 2.0 : 1.0（同一 uniform scale）
STACKUP_LAYERS: tuple[tuple[str, tuple[dict[str, Any], ...]], ...] = (
    ("substrate", ({"shape": "rect", "x": 0.0, "y": 0.0,
                    "w": 10.0, "h": 2.0},)),
    ("traces", ({"shape": "rect", "x": 1.0, "y": 2.6,
                 "w": 3.0, "h": 0.4},
                {"shape": "rect", "x": 6.0, "y": 2.6,
                 "w": 3.0, "h": 0.4})),
    ("mask", ({"shape": "rect", "x": 0.0, "y": 3.4,
               "w": 10.0, "h": 1.0},)),
)

# 星座符号（单云 4 符号；帧序列=2 帧 [2,2]——轨迹跨帧断开锚用）
SYMBOLS_FLAT: tuple[tuple[float, float], ...] = (
    (1.0, 0.5), (-0.5, 1.0), (0.25, -0.75), (-1.0, -0.5),
)

# 预算级表：发射 +20 → 馈线 −3 → 滤波 −1.5 → 混频 −5（累计 20/17/15.5/10.5）
BUDGET_STAGES: tuple[dict[str, Any], ...] = (
    {"name": "Tx", "value_db": 20.0},
    {"name": "feed", "value_db": -3.0},
    {"name": "filter", "value_db": -1.5},
    {"name": "mixer", "value_db": -5.0},
)


def make_stackup_layout_json(tmp_path: Path,
                             name: str = "stackup.json", *,
                             layers: tuple[tuple[str,
                                           tuple[dict[str, Any], ...]], ...]
                             | None = None) -> Path:
    """写 stackup_growth 用 layout_json（缺省三层：底板/双段走线/顶膜）。"""
    if layers is None:
        layers = STACKUP_LAYERS
    payload = {"layers": [{"name": nm,
                           "primitives": [dict(prim) for prim in prims]}
                          for nm, prims in layers]}
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def make_symbols_json(tmp_path: Path, name: str = "symbols.json", *,
                      symbols: tuple[tuple[float, float], ...]
                      | None = None,
                      frames: tuple[tuple[tuple[float, float], ...], ...]
                      | None = None) -> Path:
    """写 symbols_json（恰一形态：symbols=单云 / frames=帧序列）。

    缺省=单云 4 符号（SYMBOLS_FLAT）；frames 给定时走帧序列形态。
    """
    if frames is not None:
        payload: dict[str, Any] = {
            "frames": [{"symbols": [[i, q] for i, q in fr]}
                       for fr in frames]}
    else:
        syms = symbols if symbols is not None else SYMBOLS_FLAT
        payload = {"symbols": [[i, q] for i, q in syms]}
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def make_budget_json(tmp_path: Path, name: str = "budget.json", *,
                     stages: tuple[dict[str, Any], ...] | None = None
                     ) -> Path:
    """写 budget_json（契约=``{"stages":[{"name"?,"value_db"}]}``）。"""
    payload = {"stages": [dict(s) for s in
                          (stages if stages is not None else BUDGET_STAGES)]}
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p
