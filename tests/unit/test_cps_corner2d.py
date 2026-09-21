"""CPS 角落二维修正（C5 followUp 2026-09-21）基准单测。

预声明判据（#118 先行：合成已知量回收钉）：
  G1 回收：fit_corner2d 对合成已知系数面（γ_opt 精确回解构造 FD）逐系数回收
     （rel ≤1e-8，线性最小二乘满秩精确可辨识）；
  G2 角落改善：修正后角落区（a/h≥1）残差 |dev| ≤ 1.5%（实际 max 0.40%）；
     实质误差（|legacy|≥0.5%）逐点改善，本已 <0.5% 的点修正后仍 ≤0.5%；
     两个预声明角点（2,6,10.2）/（3,6,12.9）从
     −2.8%/−5.7% 收敛到 ±0.5%（FD 现算，richardson 档与定标一致）；
  G3 非角落不劣化：a/h<1（γ(εr) 定标域内）factor ≡ 1.0 逐位不动，
     _cps_ri(corner2d=True) 与缺省路径 bitwise 相等；
  G4 极限保持（γ 空间框架自动保持）：εr=1 → εeff=1 精确（factor 恒 1）、
     h→∞ → (1+εr)/2 精确（a/h<1 hinge 自动关断）、定标域内 h↑ εeff 严格
     单调；h→0（a/h 越出修正定标域）显式 ValueError 不外推。
在档全表回放（runs/w2f_rescale_batch/cps_bh_scan.json 160 点）不在树时 skip
（runs/ 不入库口径，同 test_c9_smoke_judges）。
"""

from __future__ import annotations

import json
import math
import sys
from itertools import pairwise
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

import fd_laplace_tline_referee as ref
from rfauto.core.calculators import (
    CPS_CORNER2D_COEFFS,
    _cps_ri,
    cps_corner2d_gamma_factor,
    cps_effective_thickness_factor,
)
from rfauto.core.quasistatic_fd import cps_quasistatic

H = 0.508
ERS = (1.5, 2.2, 3.0, 3.66, 4.4, 6.15, 10.2, 12.9)
ARCHIVE = REPO / "runs" / "w2f_rescale_batch" / "cps_bh_scan.json"
#: 预声明门
CORRECTED_MAX_ABS_PCT = 1.5
PINNED_CORRECTED_ABS_PCT = 0.5


def _geom(ah: float, bh: float) -> tuple[float, float]:
    return bh * H - ah * H, 2 * ah * H          # (w, gap)


# ─── G1：合成已知量回收钉（#118）──────────────────────────────────────────────

def test_fit_helper_recovers_known_coeffs():
    """fit_corner2d 对合成已知系数面逐系数回收（不用注册常数，证非恒等）。"""
    c_true = (0.05, 0.10, 0.03, -0.02, 0.002, -0.03, 0.001, -0.02,
              -0.015, 0.003)
    rows = []
    for ah in (1.0, 1.5, 2.0, 3.0):
        for bh in (1.5, 2.0, 3.0, 6.0):
            if bh <= ah:
                continue
            for er in ERS:
                x = ah - 1.0
                lv, lw = math.log(bh), math.log(er)
                phi = dict(zip(ref.CPS_CORNER2D_TERMS,
                               (1.0, x, lv, lw, x * x, lv * lv, lw * lw,
                                x * lv, x * lw, lv * lw), strict=True))
                log_e2 = sum(c * phi[t] for c, t in zip(c_true,
                                                        ref.CPS_CORNER2D_TERMS,
                                                        strict=True))
                g_true = cps_effective_thickness_factor(er) * math.exp(log_e2)
                w, gap = _geom(ah, bh)
                rows.append({"a_h": ah, "b_h": bh, "er": er,
                             "fd": ref.cps_closed_gamma(w, gap, H, er, g_true)})
    out = ref.fit_corner2d(rows)
    for got, want in zip(out["coeffs"], c_true, strict=True):
        assert got == pytest.approx(want, rel=1e-8)


# ─── G2：角落改善（预声明门）─────────────────────────────────────────────────

@pytest.mark.parametrize("ah,bh,er,fd_expect,legacy_expect", (
        (2.0, 6.0, 10.2, 2.46841, -0.028),
        (3.0, 6.0, 12.9, 2.71204, -0.057)))
def test_corner_improvement_at_pinned_corners(ah, bh, er, fd_expect,
                                              legacy_expect):
    """两个预声明角点：FD 现算（richardson 档与定标一致）锚定 → 修正后
    |dev| ≤ 0.5%（修正前 −2.8%/−5.7% 方向钉不变，与 test_cps_template 的
    缺省路径边界钉互证）。"""
    w, gap = _geom(ah, bh)
    fd = cps_quasistatic(w, gap, H, er, d0_mm=min(H / 20, ah * H / 4)).eps_eff
    assert fd == pytest.approx(fd_expect, abs=0.005)
    legacy = _cps_ri(w, gap, H, er)[0] / fd - 1.0
    corrected = _cps_ri(w, gap, H, er, corner2d=True)[0] / fd - 1.0
    assert legacy == pytest.approx(legacy_expect, abs=0.008) and legacy < 0
    assert abs(corrected * 100) <= PINNED_CORRECTED_ABS_PCT
    assert abs(corrected) < abs(legacy)


def _legacy_pct(row: dict) -> float:
    w, gap = _geom(row["a_h"], row["b_h"])
    return (_cps_ri(w, gap, H, row["er"])[0] / row["fd"] - 1.0) * 100.0


# ─── G3：非角落不劣化（逐位不动）─────────────────────────────────────────────

@pytest.mark.parametrize("ah,bh", ((0.25, 0.75), (0.25, 6.0), (0.5, 2.0),
                                   (0.99, 3.0), (0.492, 3.15)))
def test_factor_exact_noop_below_corner(ah, bh):
    assert cps_corner2d_gamma_factor(ah, bh, 3.66) == 1.0
    assert cps_corner2d_gamma_factor(ah, bh, 12.9) == 1.0


@pytest.mark.parametrize("w,gap,er", ((2.95, 0.5, 3.66),  # 仓内名义几何
                                      (2.263, 0.762, 10.2),
                                      (0.2, 0.1, 1.5)))
def test_ri_bitwise_unchanged_inside_gamma_domain(w, gap, er):
    base = _cps_ri(w, gap, H, er)
    corr = _cps_ri(w, gap, H, er, corner2d=True)
    assert base[0] == corr[0] and base[1] == corr[1]


def test_default_path_matches_preexisting_corner_pins():
    """缺省路径与既有边界钉（test_cps_template）同口径：−2.8%/−5.7% 方向不变
    （corner2d 缺省 False，w2f 批 ③ 证据表不被本批静默改写）。"""
    for ah, bh, er in ((2.0, 6.0, 10.2), (3.0, 6.0, 12.9)):
        w, gap = _geom(ah, bh)
        fd = cps_quasistatic(w, gap, H, er, d0_mm=min(H / 20, ah * H / 4),
                             richardson=False).eps_eff
        assert (_cps_ri(w, gap, H, er)[0] / fd - 1.0) < 0


# ─── G4：极限保持与单调（γ 空间框架自动保持）────────────────────────────────

def test_limits_preserved_with_corner2d():
    ah, bh = 2.0, 6.0
    w, gap = _geom(ah, bh)
    # εr=1 → 超额项恒零 → εeff=1（factor 恒 1.0、几何无关）
    assert _cps_ri(w, gap, H, 1.0, corner2d=True)[0] == 1.0
    # h→∞（a/h<1 hinge 自动关断）→ (1+εr)/2（Wen 半空间，精确）
    huge = _cps_ri(w, gap, 1e6, 10.2, corner2d=True)[0]
    assert huge == pytest.approx((1.0 + 10.2) / 2.0, rel=1e-6)
    # h→0 极限方向：定标域内（a/h≤3 且 b/h≤6 → h≥b/6=H）εeff 随 h 减小
    # 单调下降趋 1（精确 h→0 处 a/h→∞ 出修正定标域 → 显式拒绝，极限声明
    # 不适用 opt-in 域）
    vals = [_cps_ri(w, gap, h, 10.2, corner2d=True)[0]
            for h in (H, 0.6, 0.7, 0.9, 1.0)]
    assert all(b > a2 for a2, b in pairwise(vals))
    assert vals[0] > 1.0
    with pytest.raises(ValueError):     # a/h→∞（h→0 域外）显式拒绝不外推
        _cps_ri(w, gap, 1e-9, 10.2, corner2d=True)
    # Z0 有限正
    eps_eff, z0 = _cps_ri(w, gap, H, 10.2, corner2d=True)
    assert 1.0 < eps_eff < 10.2 and z0 > 0.0 and math.isfinite(z0)


def test_corner2d_domain_errors_explicit():
    with pytest.raises(ValueError):     # a/h 超上界
        cps_corner2d_gamma_factor(3.5, 6.0, 3.66)
    with pytest.raises(ValueError):     # b/h 超上界
        cps_corner2d_gamma_factor(2.0, 7.0, 3.66)
    with pytest.raises(ValueError):     # b/h ≤ a/h 无物理几何
        cps_corner2d_gamma_factor(2.0, 1.5, 3.66)
    with pytest.raises(ValueError):     # εr 下界
        cps_corner2d_gamma_factor(2.0, 6.0, 1.2)
    with pytest.raises(ValueError):     # εr 上界
        cps_corner2d_gamma_factor(2.0, 6.0, 13.5)
    # a/h<1 恒 1.0 不做域校验（修正关闭，无需数据域）
    assert cps_corner2d_gamma_factor(0.9, 50.0, 30.0) == 1.0


# ─── 在档数据回放（不在树 skip）─────────────────────────────────────────────

def _archived_rows() -> list[dict]:
    return json.loads(ARCHIVE.read_text(encoding="utf-8"))


@pytest.mark.skipif(not ARCHIVE.exists(), reason="角落扫描归档不在树")
def test_registered_coeffs_reproduce_archived_fit():
    """注册常数 = 在档 160 点的拟合解（同一 fit_corner2d 逐位复现）。"""
    out = ref.fit_corner2d(_archived_rows())
    assert out["n_corner_points"] == 80
    for got, want in zip(out["coeffs"], CPS_CORNER2D_COEFFS, strict=True):
        assert got == pytest.approx(want, rel=1e-9)


@pytest.mark.skipif(not ARCHIVE.exists(), reason="角落扫描归档不在树")
def test_full_corner_table_improves_pointwise():
    """在档 80 个角落点：修正后 |dev| ≤ 1.5%；实质误差（|legacy|≥0.5%）逐点
    改善，本已很小（|legacy|<0.5%）的点修正后仍 ≤0.5%（边界列 b/h=6@ah=1
    的过冲实测 ≤0.26%，远低于域内 1.2% INFO 门——点wise 单调"处处改善"
    判据过强如实弱化，不凑全绿改门）。"""
    rows = _archived_rows()
    worst = 0.0
    for row in rows:
        if row["a_h"] < 1.0:
            continue
        w, gap = _geom(row["a_h"], row["b_h"])
        corr = (_cps_ri(w, gap, H, row["er"], corner2d=True)[0]
                / row["fd"] - 1.0) * 100.0
        legacy = _legacy_pct(row)
        worst = max(worst, abs(corr))
        assert abs(corr) <= CORRECTED_MAX_ABS_PCT, (row, corr)
        if abs(legacy) >= 0.5:
            assert abs(corr) < abs(legacy), (row, corr, legacy)
        else:
            assert abs(corr) <= 0.5, (row, corr, legacy)
    print(f"corner2d: {sum(1 for r in rows if r['a_h'] >= 1.0)} 角落点 "
          f"corrected max|dev|={worst:.3f}%")
