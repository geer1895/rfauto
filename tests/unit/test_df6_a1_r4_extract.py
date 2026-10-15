"""df6 A1（R4）判读内核单测：k 模分裂提取 + Qe 群时延 C 常数（零真机零引擎）。

钉面（criteria.md §一，runs/df6_a1_r4/selftest_result.json 同源判定）：
① C 常数裁决：无耗单端口（J 倒置器耦合谐振臂）S11 群时延 Lorentzian 拟合
   A=4Qe/ω0 ⇒ **C=4**（/2 口径被合成回收否决）；对称双馈 S21 口径 C=1（记
   录量）；tap2 弱加载的系统性偏移由点位配置钉 C_cfg 吸收（回收逐位）。
② k 主判精确式 (f2²−f1²)/(f2²+f1²)：合成 order=2 链已知 J12=k·b → 峰检
   → 偏置曲线（馈 tap 加载拉动，节点处负偏 ≤8%）log-log 逆映射回收逐位。
③ 群时延基线陷阱：带缘斜率法被谐振器电抗斜率污染（钉电路实测 0.625ns vs
   真线 0.193ns）——四参数拟合 D 项吸收，#118 家族（观察工具失真）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for _p in (SRC, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "_df6_a1_r4_runner", SCRIPTS / "df6_a1_r4_runner.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


@pytest.fixture(scope="module")
def st():
    p = REPO / "runs" / "df6_a1_r4" / "selftest_result.json"
    if not p.exists():
        pytest.skip("selftest_result.json 未生成（--selftest 先行）")
    return json.loads(p.read_text(encoding="utf-8"))


def test_c_s11_reflection_caliber_is_four(runner, st):
    """C=4 裁决：纯单端口钉电路（tap2 Qe=1e5）回收 C 落 4±0.2（/2 否决）。"""
    assert abs(st["c_s11_pure"] - 4.0) < 0.2
    # 配置钉（tap2 弱加载）贴近 4：qe_g02263 偏移 <0.1%、qe_g0800 <1%
    assert abs(st["c_by_pt"]["qe_g02263"]["c_cfg"] - 4.0) < 0.05
    assert abs(st["c_by_pt"]["qe_g0800"]["c_cfg"] - 4.0) < 0.05


def test_qe_recovery_independent_case(runner, st):
    """C_pure 定于 Qe=17.07 案例，独立案例 Qe=100 回收 ≤0.5%（#118 唯一确定）。"""
    assert abs(st["qe_recovery_case_b_rel"]) <= 0.005


def test_qe_cfg_pin_self_recovery_bitwise(runner, st):
    """点位配置钉自回收逐位（同合成数据回代 <1e-9）。"""
    for v in st["c_by_pt"].values():
        assert abs(v["self_recovery_rel"]) < 1e-9
        assert v["qe1_true"] > 0.0


def test_k_bias_curve_monotone_and_nodes_exact(runner, st):
    """偏置曲线（馈 tap 加载拉动）单调、设计节点逐位回收、栅格内偏置 ≤10%。"""
    kb = st["k_bias"]
    tg, rg = kb["true_grid"], kb["raw_grid"]
    assert tg == sorted(tg) and len(tg) >= len(runner.K_TARGETS)
    assert all(a < c for a, c in pairwise(rg))
    assert all(abs(r / t - 1.0) <= 0.10 for t, r in zip(tg, rg, strict=True))
    i_d = tg.index(runner.K_DESIGN)
    assert abs(runner.bias_invert(rg[i_d], np.asarray(rg), np.asarray(tg))
               / runner.K_DESIGN - 1.0) < 1e-9
    assert st["k_midnode"]["rel_err"] <= 5e-3


def test_k_extraction_roundtrip_synthetic(runner, st):
    """合成 order=2 链 → mode_split_k → 偏置逆映射回收 k_true（全节点 ≤0.5%）。"""
    b = runner.slope_b()
    z_r, ere = runner._zr_ere()
    fg = np.linspace(*runner.BAND_GHZ, 2401)
    f = fg * 1e9
    j_f, _ = runner.c3_coupling_j_from_gap(runner.W_MM, runner.S_FEED_K_MM,
                                           runner.F0_GHZ, runner.ER,
                                           runner.H_MM)
    kb = st["k_bias"]
    rg, tg = np.asarray(kb["raw_grid"]), np.asarray(kb["true_grid"])
    for k_t in (0.024, 0.045, 0.070):        # 全部非栅格节点
        s = runner.synthetic_schain([j_f, k_t * b, j_f], runner.RES_LEN_MM,
                                    z_r, ere, fg)
        ex = runner.extract_k_point(f, s[:, 1, 0], st)
        assert ex["k_raw"] is not None
        # 提取-逆映射回收（2401 粗栅格下的插值精度，比真机 1201 栅格松）
        assert abs(ex["k_corr"] / k_t - 1.0) < 0.01, k_t
        # 偏置方向：raw < true（弱 tap 拉动恒低估，hairpin pull 同号）
        assert ex["k_raw"] < k_t
    assert rg.size == tg.size


def test_mode_split_rejects_single_peak(runner):
    """无双峰（纯单谐振曲线）→ k_raw=None 如实不硬提（#122）。"""
    z_r, ere = runner._zr_ere()
    fg = np.linspace(2.45, 2.55, 2001)
    s = runner.synthetic_schain([0.002, 1e-7], runner.RES_LEN_MM,
                                z_r, ere, fg)
    ex = runner.mode_split_k(fg * 1e9, s[:, 1, 0])
    assert ex["k_raw"] is None


def test_group_delay_baseline_trap_documented(runner):
    """带缘斜率法失真钉：真线时延 0.193ns，斜率法测出 >3×（电抗斜率污染）。"""
    b = runner.slope_b()
    z_r, ere = runner._zr_ere()
    fg = np.linspace(2.42, 2.60, 36001)
    s = runner.synthetic_schain([runner.j_from_qe(17.07, b),
                                 runner.j_from_qe(1e5, b)],
                                runner.RES_LEN_MM, z_r, ere, fg)
    f = fg * 1e9
    t_line_fit = runner.line_delay_1way(f, s[:, 0, 0], (2.42e9, 2.47e9))
    t_true = runner.PIN_FEED_LEN_MM * 1e-3 / 299792458.0
    assert t_line_fit > 2.0 * t_true        # 污染方向钉（弃用依据）
    # 四参数拟合的 D 项应贴近常数线时延量级（≤3× 真线时延）
    ex = runner.extract_qe_point(f, s[:, 0, 0], 4.0)
    assert ex["d_fit_s"] < 3.0 * t_true
    assert abs(ex["qe_s11"] / 17.07 - 1.0) < 0.01


def test_point_table_shapes(runner):
    """点位表结构：8 点、k 点 gaps=[s_f,s_g,s_f]、qe 点 order=1 两缝。"""
    pts = runner.build_points()
    assert len(pts) == 8
    for d in pts:
        if d["kind"] == "k":
            assert len(d["params"]["gaps_mm"]) == 3
            assert d["params"]["order"] == 2
            assert d["params"]["gaps_mm"][0] == runner.S_FEED_K_MM
            assert abs(d["j12_target_s"] / runner.slope_b()
                       - d["k_target"]) < 1e-3
        else:
            assert d["params"]["order"] == 1
            assert len(d["params"]["gaps_mm"]) == 2
            assert d["params"]["gaps_mm"][1] == runner.S_TAP2_MM
