"""HS-3 core/shield_cavity_mode.py 单测（round4 中件包一判据，先写后跑 #122）。

裁判口径（#118 双路径，不自证）：
- 路径 A（被测）：rect_cavity_modes 经 pdn.plane_cavity_modes 面内网格 +
  hypot 正交合成（f_mnp² = f_mn² + f_p²）；
- 路径 B（独立闭式）：测试内直写 f_mnp = (c0/(2√εr))·√((m/a)²+(n/b)²+(p/h)²)
  逐模式全量对拍（rel 1e-12）。
- 立方腔简并：闭式只含 (m,n,p) 指数二次型，a=b=h 时置换组同频——简并组
  计数按容许集（p≥1 且 (m,n)≠(0,0)）手推钉死：阶 ≤2 的 16 个容许模按频率
  分组为 [2,1,4,3,2,3,1]（s=m²+n²+p² ∈ {2,3,5,6,8,9,12} 的重数）。
- preflight 边界：最长边恰等于 λ_min/2 判 fail（严格小于才 pass），
  margin_m=0.0 逐位留痕。
"""

from __future__ import annotations

import json
import math

import pytest

from rfauto.core.pdn import C0, plane_cavity_modes
from rfauto.core.shield_cavity_mode import (
    ShieldCavityMode,
    rect_cavity_modes,
    shield_cavity_preflight,
)


def _direct_mode_freq(a: float, b: float, h: float, er: float, m: int, n: int, p: int) -> float:
    """路径 B：独立直写三维腔模闭式（与被测合成路径无共享代码）。"""
    return C0 / (2.0 * math.sqrt(er)) * math.sqrt((m / a) ** 2 + (n / b) ** 2 + (p / h) ** 2)


def _degenerate_group_sizes(modes: list[ShieldCavityMode], rel: float = 1e-12) -> list[int]:
    """按升序相邻频率相对差 ≤rel 分组的简并组大小列表。"""
    groups: list[list[ShieldCavityMode]] = []
    for mode in modes:
        if groups and abs(mode.f_hz - groups[-1][-1].f_hz) <= rel * max(mode.f_hz, groups[-1][-1].f_hz):
            groups[-1].append(mode)
        else:
            groups.append([mode])
    return [len(group) for group in groups]


# ─── 1. rect_cavity_modes：解析回收钉 ────────────────────────────────────────


def test_rect_cavity_modes_f101_analytic_recycle():
    # TE_101（n=0）：f = (c/2√εr)·√(1/a² + 1/h²)，手算量级 ~15.45 GHz
    a, b, h, er = 0.04, 0.03, 0.01, 1.0
    expected = C0 / (2.0 * math.sqrt(er)) * math.sqrt((1.0 / a) ** 2 + (1.0 / h) ** 2)
    assert 1.5e10 < expected < 1.6e10
    modes = rect_cavity_modes(a, b, h, er, 1, 1, 1)
    f101 = next(m for m in modes if (m.m, m.n, m.p) == (1, 0, 1))
    assert f101.f_hz == pytest.approx(expected, rel=1e-12)


def test_rect_cavity_modes_all_match_direct_closed_form():
    # 阶 ≤2 全部 16 个容许模 vs 独立闭式逐点对拍（rel 1e-12）
    a, b, h, er = 0.05, 0.04, 0.02, 4.0
    modes = rect_cavity_modes(a, b, h, er, 2, 2, 2)
    assert len(modes) == 16  # (m,n) 8 个非零对 × p∈{1,2}
    for mode in modes:
        expected = _direct_mode_freq(a, b, h, er, mode.m, mode.n, mode.p)
        assert mode.f_hz == pytest.approx(expected, rel=1e-12), (mode.m, mode.n, mode.p)


def test_rect_cavity_modes_ascending_and_admissible():
    modes = rect_cavity_modes(0.05, 0.04, 0.02, 4.0, 3, 2, 2)
    freqs = [mode.f_hz for mode in modes]
    assert freqs == sorted(freqs)  # 升序单调
    triples = [(mode.m, mode.n, mode.p) for mode in modes]
    assert len(set(triples)) == len(triples)  # 三元组唯一
    for m, n, p in triples:
        assert p >= 1  # 容许集：p ≥ 1（TE_mn0/(0,0,p) 非平凡场不存在）
        assert (m, n) != (0, 0)  # 直流模排除


def test_cube_degenerate_groups():
    # 立方腔 a=b=h：频率只依赖指数二次型——阶 ≤2 手推简并组 [2,1,4,3,2,3,1]
    modes = rect_cavity_modes(0.02, 0.02, 0.02, 1.0, 2, 2, 2)
    assert len(modes) == 16
    assert _degenerate_group_sizes(modes) == [2, 1, 4, 3, 2, 3, 1]
    # 阶 ≤1：√2 组 {(1,0,1),(0,1,1)} 两重，√3 组 {(1,1,1)} 单条
    modes1 = rect_cavity_modes(0.02, 0.02, 0.02, 1.0, 1, 1, 1)
    assert _degenerate_group_sizes(modes1) == [2, 1]
    # 跨 p 置换同频：(2,0,1) 与 (0,1,2) 同为 s=5（rel 1e-15，合成路径 ulp 内）
    f201 = next(m for m in modes if (m.m, m.n, m.p) == (2, 0, 1))
    f012 = next(m for m in modes if (m.m, m.n, m.p) == (0, 1, 2))
    assert f201.f_hz == pytest.approx(f012.f_hz, rel=1e-15)


def test_rect_cavity_modes_reuse_pdn_plane_kernel():
    # 内核复用钉：p=1 每模频率 == hypot(pdn 平面腔网格, f_p) 逐位（#112 单源）
    a, b, h, er = 0.05, 0.04, 0.02, 4.0
    plane = {(mode.m, mode.n): mode.f_hz for mode in plane_cavity_modes(a, b, er, 3, 2)}
    modes = rect_cavity_modes(a, b, h, er, 3, 2, 1)
    f_p = C0 / (2.0 * math.sqrt(er) * h)
    for mode in modes:
        assert mode.f_hz == math.hypot(plane[(mode.m, mode.n)], f_p)  # 逐位


def test_shield_cavity_mode_to_dict():
    mode = ShieldCavityMode(m=1, n=0, p=2, f_hz=1.5e10)
    payload = mode.to_dict()
    assert payload == {"m": 1, "n": 0, "p": 2, "f_hz": 1.5e10}
    assert json.dumps(payload)  # JSON 可序列化


def test_rect_cavity_modes_guards():
    good = (0.05, 0.04, 0.02, 4.0)
    with pytest.raises(ValueError):
        rect_cavity_modes(0.0, good[1], good[2], good[3], 1, 1, 1)  # a ≤ 0
    with pytest.raises(ValueError):
        rect_cavity_modes(good[0], -0.04, good[2], good[3], 1, 1, 1)  # b ≤ 0
    with pytest.raises(ValueError):
        rect_cavity_modes(good[0], good[1], 0.0, good[3], 1, 1, 1)  # h ≤ 0
    with pytest.raises(ValueError):
        rect_cavity_modes(good[0], good[1], good[2], 0.0, 1, 1, 1)  # er ≤ 0
    with pytest.raises(ValueError):
        rect_cavity_modes(good[0], good[1], good[2], float("nan"), 1, 1, 1)
    with pytest.raises(ValueError):
        rect_cavity_modes(good[0], good[1], good[2], good[3], 1.5, 1, 1)  # 非整数模阶
    with pytest.raises(ValueError):
        rect_cavity_modes(good[0], good[1], good[2], good[3], 1, 1, 0)  # p_max=0 无容许模
    with pytest.raises(ValueError):
        rect_cavity_modes(good[0], good[1], good[2], good[3], -1, 1, 1)  # 负模阶
    with pytest.raises(ValueError):
        rect_cavity_modes(good[0], good[1], good[2], good[3], True, 1, 1)  # bool 拒收（df7+⑯）
    with pytest.raises(ValueError):
        rect_cavity_modes(good[0], good[1], good[2], good[3], 0, 0, 1)  # m_max=n_max=0 无容许模
    with pytest.raises(ValueError):
        rect_cavity_modes(1.0, 1.0, 1.0, 1.0, 10**3, 10**3, 10**3)  # 扫描规模超上限


# ─── 2. shield_cavity_preflight：门判据钉 ────────────────────────────────────


def test_preflight_pass_small_enclosure():
    # 60×40×20mm @εr=4、带 [0.5,1] GHz：最长边 60mm < λ_min/2=74.9mm → pass
    verdict = shield_cavity_preflight(0.06, 0.04, 0.02, 4.0, 0.5e9, 1.0e9)
    assert verdict.verdict == "pass"
    assert verdict.longest_edge_m == 0.06
    assert verdict.threshold_m == pytest.approx(C0 / (1.0e9 * 2.0) / 2.0, rel=1e-15)
    assert verdict.margin_m == pytest.approx(verdict.threshold_m - 0.06, rel=1e-15)
    assert verdict.modes == ()  # 几何 pass ⟹ 带内零腔模（充分条件）
    assert verdict.n_modes_in_band == 0
    assert verdict.suggestions == ()


def test_preflight_fail_lists_in_band_modes_and_suggestions():
    # 500×400×300mm @εr=1、带 [100MHz,1GHz]：最长边 0.5m > 0.1499m → fail
    verdict = shield_cavity_preflight(0.5, 0.4, 0.3, 1.0, 100e6, 1.0e9)
    assert verdict.verdict == "fail"
    assert verdict.margin_m < 0.0
    assert len(verdict.suggestions) == 2
    assert all("分腔" in s or "吸波片" in s for s in verdict.suggestions)
    assert verdict.n_modes_in_band >= 1
    # 首个带内模 = TE_101 族：f = (c/2)·√((1/a)²+(1/h)²) ≈ 0.583 GHz ≤ 1 GHz
    assert verdict.modes[0].f_hz == pytest.approx(
        C0 / 2.0 * math.sqrt((1 / 0.5) ** 2 + (1 / 0.3) ** 2), rel=1e-12
    )


def test_preflight_boundary_equality_is_fail():
    # 最长边恰等于 λ_min/2 → 严格判 fail（< 才 pass），margin_m=0.0 逐位
    lam_half = C0 / (1.0e9 * math.sqrt(1.0)) / 2.0
    verdict = shield_cavity_preflight(lam_half, lam_half / 2.0, lam_half / 4.0, 1.0, 0.5e9, 1.0e9)
    assert verdict.verdict == "fail"
    assert verdict.longest_edge_m == lam_half
    assert verdict.threshold_m == lam_half
    assert verdict.margin_m == 0.0  # 逐位


def test_preflight_modes_ascending_within_band():
    verdict = shield_cavity_preflight(0.5, 0.4, 0.3, 1.0, 100e6, 1.0e9, n_report=64)
    freqs = [mode.f_hz for mode in verdict.modes]
    assert freqs == sorted(freqs)
    assert all(100e6 <= f <= 1.0e9 for f in freqs)
    assert len(freqs) == verdict.n_modes_in_band  # n_report=64 未截断


def test_preflight_n_report_truncation():
    verdict = shield_cavity_preflight(0.5, 0.4, 0.3, 1.0, 100e6, 1.0e9, n_report=2)
    assert len(verdict.modes) == 2
    assert verdict.n_modes_in_band > 2  # 总数与截断面分离


def test_preflight_to_dict_json_roundtrip():
    verdict = shield_cavity_preflight(0.5, 0.4, 0.3, 1.0, 100e6, 1.0e9, n_report=3)
    payload = verdict.to_dict()
    text = json.dumps(payload, ensure_ascii=False)
    assert json.loads(text)["verdict"] == "fail"
    assert payload["scan_orders"] == list(verdict.scan_orders)
    assert len(payload["modes"]) == 3
    assert set(payload["modes"][0]) == {"m", "n", "p", "f_hz"}


def test_preflight_guards():
    with pytest.raises(ValueError):
        shield_cavity_preflight(0.0, 0.04, 0.02, 4.0, 0.5e9, 1.0e9)  # a ≤ 0
    with pytest.raises(ValueError):
        shield_cavity_preflight(0.06, -1.0, 0.02, 4.0, 0.5e9, 1.0e9)  # b ≤ 0
    with pytest.raises(ValueError):
        shield_cavity_preflight(0.06, 0.04, -0.02, 4.0, 0.5e9, 1.0e9)  # h ≤ 0
    with pytest.raises(ValueError):
        shield_cavity_preflight(0.06, 0.04, 0.02, 0.0, 0.5e9, 1.0e9)  # er ≤ 0
    with pytest.raises(ValueError):
        shield_cavity_preflight(0.06, 0.04, 0.02, 4.0, 0.0, 1.0e9)  # f_min ≤ 0
    with pytest.raises(ValueError):
        shield_cavity_preflight(0.06, 0.04, 0.02, 4.0, 2.0e9, 1.0e9)  # f_min > f_max
    with pytest.raises(ValueError):
        shield_cavity_preflight(0.06, 0.04, 0.02, 4.0, 0.5e9, 1.0e9, n_report=0)  # n_report < 1
    with pytest.raises(ValueError):
        shield_cavity_preflight(0.06, 0.04, 0.02, 4.0, 0.5e9, 1.0e9, n_report=True)  # bool 拒收
