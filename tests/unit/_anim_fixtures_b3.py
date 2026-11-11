"""动图批 3 测试 fixtures 构造器（Q-W2-3；**只落 tmp_path，禁写 runs/ 湖**）。

数据面=显式字面量构造（零随机零示意数据混入渲染链——这些文件是"数据源"
本身，供渲染器确定性消费）：

- :func:`make_cascade_json` —— cascade_json 契约（级表对齐 core/cascade
  级表语义）；
- :func:`make_nf2ff_cuts_json` —— nf2ff_cut 契约（``db``/``pattern_db``
  双键名可选；freq_hz/phi_deg 切面标识）；
- :func:`make_chain_json` —— chain_json 契约（nodes/edges）；
- :func:`make_morph_csvs` —— filter_morphing 多源 sparams.csv 组（同栅
  同列集，值=显式字面量）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ── 缺省字面量（测试独立复算锚引用的原始数值）─────────────────────────────────
# Friis 锚：LNA(+20dB, NF2dB) → 滤波器(−3dB, NF3dB) → 混频器(+8dB, NF9dB)
# F_cum = 10^0.2 + (10^0.3−1)/10^2 + (10^0.9−1)/(10^2×10^-0.3)
CASCADE_STAGES: tuple[dict[str, Any], ...] = (
    {"name": "LNA", "gain_db": 20.0, "nf_db": 2.0},
    {"name": "filter", "gain_db": -3.0, "nf_db": 3.0},
    {"name": "mixer", "gain_db": 8.0, "nf_db": 9.0},
)

CHAIN_NODES: tuple[dict[str, Any], ...] = (
    {"id": "lna", "label": "LNA", "gain_db": 20.0},
    {"id": "pa", "label": "PA", "gain_db": 30.0},
    {"id": "ant", "label": "ANT"},
)
CHAIN_EDGES: tuple[dict[str, str], ...] = (
    {"from": "lna", "to": "pa"},
    {"from": "pa", "to": "ant"},
)


def make_cascade_json(tmp_path: Path, name: str = "cascade.json", *,
                      stages: tuple[dict[str, Any], ...] | None = None
                      ) -> Path:
    """写 cascade_json（契约=``{"stages":[{"name"?,"gain_db","nf_db"}]}``）。"""
    payload = {"stages": [dict(s) for s in
                           (stages if stages is not None else CASCADE_STAGES)]}
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def make_nf2ff_cuts_json(tmp_path: Path, name: str = "nf2ff_cuts.json", *,
                         cuts: tuple[dict[str, Any], ...] | None = None,
                         db_key: str = "db") -> Path:
    """写 nf2ff_cut（契约=``{"cuts":[{"theta_deg","db"|"pattern_db"}]}``）。

    缺省两幅切面：全向近理想（含 360° 跨度闭合面）+ freq_hz/phi_deg 标识
    双形态各一。cuts 给定时每项经 ``db_key`` 决定 dB 键名。
    """
    if cuts is None:
        cuts = (
            {"freq_hz": 2.45e9,
             "theta_deg": [0.0, 90.0, 180.0, 270.0, 360.0],
             db_key: [-0.1, -3.0, -20.0, -3.0, -0.1]},
            {"phi_deg": 0.0,
             "theta_deg": [0.0, 90.0, 180.0, 270.0],
             db_key: [-1.0, -6.0, -25.0, -6.0]},
        )
    payload = {"cuts": [dict(c) for c in cuts]}
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def make_chain_json(tmp_path: Path, name: str = "chain.json", *,
                    nodes: tuple[dict[str, Any], ...] | None = None,
                    edges: tuple[dict[str, str], ...] | None = None) -> Path:
    """写 chain_json（契约=``{"nodes":[{"id","label"?,"gain_db"?}],"edges"}``）。"""
    payload = {"nodes": [dict(n) for n in
                         (nodes if nodes is not None else CHAIN_NODES)],
               "edges": [dict(e) for e in
                         (edges if edges is not None else CHAIN_EDGES)]}
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def make_morph_csvs(tmp_path: Path, prefix: str = "morph",
                    steps: tuple[tuple[float, float], ...] = (
                        (-1.0, -10.0), (-2.0, -20.0), (-3.0, -30.0)),
                    freqs: tuple[float, ...] = (1e9, 2e9, 3e9)) -> list[Path]:
    """写 morph 用同栅同列集 sparams.csv 组（值=显式字面量）。

    每步 ``S21=re值,0.0``（S11 恒 0.1,0.0 列集守卫用）；返回按步序的路径
    列表（filter_morphing sources 消费）。
    """
    paths: list[Path] = []
    for k, (s21_re, _s11_re) in enumerate(steps):
        lines = ["freq_hz,re_S11,im_S11,re_S21,im_S21"]
        for f in freqs:
            lines.append(f"{f!r},0.1,0.0,{s21_re!r},0.0")
        p = tmp_path / f"{prefix}_{k}.csv"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.append(p)
    return paths
