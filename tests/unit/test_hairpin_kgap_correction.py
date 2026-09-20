"""hairpin 级间耦合结构经验修正 c(gap) 单测（2026-09-17；#212 离线零真机）。

背景（早前真机轮判读记录）：pt5 插损 −8.60dB FAIL 归因「KJ 平行耦合线 k
对并排同向 hairpin 结构性高估」。本项先离线分离两个假设（#1b）：
① 闭式错？——NGSolve 2D 准静态偶/奇模独立源：k_NG/k_KJ=1.003/1.018/1.049 @gap
   0.8/1.1328/1.6（收敛向 HJ 单线 <1%）→ 闭式在自身假设类内无误，且方向为略低估；
② 反提链错？——N=3 归档 5 点×24 口径重提 k∈[0.016,0.50] 跨 30× 不可辨识；旧 0.29×
   出自 pt2 病态自耦配置（arm_gap=1.0）。
→ 真机 N=2 τ0.43 弱抽头双谐振器（对称同步，Q_e/Q_u 取 B1 同 τ 实测）峰电平/全线形
双估计 + 3dB 宽一致性门（≤25%）得 c(gap)=k_EM/k_KJ 表（HAIRPIN_KGAP_TABLE_MM）。
修正只作用于 hairpin 通道、显式 opt-in、域外不外推（设计反解 raise / fake 前向 clamp）。
"""
from __future__ import annotations

import importlib.util
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from rfauto.core import coupled_microstrip as cm
from rfauto.core.synthesis import hairpin_design_from_order

_SPEC = importlib.util.spec_from_file_location(
    "_hairpin_q_extract_kgap",
    str(Path(__file__).resolve().parents[2] / "scripts" / "hairpin_q_extract.py"))
assert _SPEC is not None and _SPEC.loader is not None
qx = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(qx)

W_MM = 1.1117
TABLE = cm.HAIRPIN_KGAP_TABLE_MM


# ─── 标定表本体 ───────────────────────────────────────────────────────────────

def test_table_calibrated_ascending_and_structural_deficit():
    """表非空、gap 升序、c∈(0,1)（结构性相消=有效耦合低于平行线闭式）、域=首末 gap。"""
    assert len(TABLE) >= 3
    gaps = [g for g, _ in TABLE]
    assert gaps == sorted(gaps) and len(set(gaps)) == len(gaps)
    assert all(0.0 < c < 1.0 for _, c in TABLE)
    assert cm.hairpin_kgap_domain_mm() == (gaps[0], gaps[-1])
    calib = cm.HAIRPIN_KGAP_CALIB
    assert calib["w_mm"] == W_MM and calib["order"] == 2 and calib["tap_frac"] == 0.43
    assert calib["qe_em"] == pytest.approx(34.69064166747507)


def test_correction_interpolates_table_exactly_and_linearly():
    for g, c in TABLE:
        assert cm.hairpin_kgap_correction(g) == pytest.approx(c, rel=1e-12)
    (g0, c0), (g1, c1) = TABLE[0], TABLE[1]
    assert cm.hairpin_kgap_correction(0.5 * (g0 + g1)) == pytest.approx(0.5 * (c0 + c1), rel=1e-12)


def test_domain_guard_raise_and_clamp():
    lo, hi = cm.hairpin_kgap_domain_mm()
    for bad in (lo - 0.01, hi + 0.01):
        with pytest.raises(ValueError, match="标定域"):
            cm.hairpin_kgap_correction(bad)
    assert cm.hairpin_kgap_correction(lo - 0.3, extrapolate="clamp") == TABLE[0][1]
    assert cm.hairpin_kgap_correction(hi + 0.3, extrapolate="clamp") == TABLE[-1][1]
    with pytest.raises(ValueError, match="extrapolate"):
        cm.hairpin_kgap_correction(lo, extrapolate="linear")


# ─── gap↔k 映射 ───────────────────────────────────────────────────────────────

def test_k_from_gap_default_is_pure_kj_and_corrected_is_c_times_kj():
    for g, c in TABLE:
        k_kj = cm.hairpin_k_from_gap_mm(g, W_MM)
        assert k_kj == cm.hairpin_k_from_gap_mm(g, W_MM, structural_correction=False)
        assert cm.hairpin_k_from_gap_mm(g, W_MM, structural_correction=True) == \
            pytest.approx(c * k_kj, rel=1e-12)
    # 纯 KJ 口径不受表域限制（U 内臂自耦 k_self(3.0) 等消费方照旧）
    assert cm.hairpin_k_from_gap_mm(3.0) == pytest.approx(0.0115, abs=5e-4)


def test_corrected_k_is_nonmonotone_with_interior_peak():
    """真机事实：k_EM(g)=c(g)·k_KJ(g) 在域内非单调——gap 0.5 的净耦合低于 0.8（更近反而
    相消更强），极大点 g_peak 在域内部；设计支 = [g_peak, g_max]。"""
    k = {g: cm.hairpin_k_from_gap_mm(g, W_MM, structural_correction=True)
         for g, _ in TABLE}
    assert k[0.5] < k[0.65] > k[0.8] > k[1.1328]      # 极大在 0.65，两侧回落
    lo, hi = cm.hairpin_kgap_domain_mm()
    g_peak, g_max = cm.hairpin_kgap_design_branch_mm(W_MM)
    assert lo < g_peak < hi and g_max == hi
    assert cm.hairpin_k_from_gap_mm(g_peak, W_MM, structural_correction=True) == \
        pytest.approx(max(k.values()), rel=0.02)
    assert max(k.values()) < 0.02                      # 结构 k_EM 上限（拓扑能力）


def test_corrected_k_monotone_decreasing_on_design_branch():
    """设计支上 c(g)·k_KJ(g) 单调递减（反解唯一性前提）。"""
    g_peak, g_max = cm.hairpin_kgap_design_branch_mm(W_MM)
    gs = np.linspace(g_peak, g_max, 61)
    ks = [cm.hairpin_k_from_gap_mm(g, W_MM, structural_correction=True) for g in gs]
    assert all(a >= b for a, b in pairwise(ks)), ks
    assert ks[0] > ks[-1]


def test_gap_from_k_corrected_round_trip_and_range_error():
    g_peak, g_max = cm.hairpin_kgap_design_branch_mm(W_MM)
    k_hi = cm.hairpin_k_from_gap_mm(g_peak, W_MM, structural_correction=True)
    k_lo = cm.hairpin_k_from_gap_mm(g_max, W_MM, structural_correction=True)
    for k in np.linspace(k_lo * 1.05, k_hi * 0.95, 7):
        g = cm.hairpin_gap_mm_from_k(k, W_MM, structural_correction=True)
        assert g_peak <= g <= g_max
        assert cm.hairpin_k_from_gap_mm(g, W_MM, structural_correction=True) == \
            pytest.approx(k, rel=1e-9)
    with pytest.raises(ValueError, match="可达范围"):
        cm.hairpin_gap_mm_from_k(k_hi * 1.5, W_MM, structural_correction=True)
    with pytest.raises(ValueError, match="可达范围"):
        cm.hairpin_gap_mm_from_k(0.0515, W_MM, structural_correction=True)   # FBW 5% 名义 k
    # 纯 KJ 反解不受域限制（原行为逐位不变）
    assert cm.hairpin_gap_mm_from_k(0.0515, W_MM) == pytest.approx(1.1331, abs=5e-4)


# ─── 设计链 ───────────────────────────────────────────────────────────────────

def test_design_chain_default_unchanged_and_corrected_flag():
    """默认链（名义冻结口径）逐位不变：gap 1.1328、kgap_corrected=False、gaps_mm_kj==gaps_mm。"""
    d = hairpin_design_from_order(3, 2.5, 0.05, 20.0)
    assert d["kgap_corrected"] is False
    assert d["gaps_mm"] == d["gaps_mm_kj"]
    assert round(d["gap_mm"], 4) == 1.1328
    assert d["k_list"][0] == pytest.approx(0.05151, abs=5e-5)


def test_design_chain_corrected_mode_in_domain_and_out_of_domain():
    """修正链：设计支内可达设计点 gap 落支内且往返 k 精确；FBW=5% N=3（k=0.0515）在
    c(gap) 表下不可达 → 如实 ValueError（拓扑能力问题，不越域外推）。"""
    g_peak, g_max = cm.hairpin_kgap_design_branch_mm(W_MM)
    k_max = cm.hairpin_k_from_gap_mm(g_peak, W_MM, structural_correction=True)
    # 找一个支内可达的 FBW（k_target=fbw·|M12|，N=3 RL20 |M12|=1.0303）
    fbw_ok = 0.9 * k_max / 1.0303
    d = hairpin_design_from_order(3, 2.5, fbw_ok, 20.0, kgap_corrected=True)
    assert d["kgap_corrected"] is True
    g = d["gap_mm"]
    assert g is not None and g_peak <= g <= g_max
    assert g < d["gaps_mm_kj"][0]                      # 修正后缝更小（补偿结构相消）
    # 往返用设计链自身的 w（inverse_width 未舍入 1.11169…；W_MM 为 4 位舍入名义）
    assert cm.hairpin_k_from_gap_mm(g, d["w_mm"], structural_correction=True) == \
        pytest.approx(d["k_list"][0], rel=1e-9)
    assert any("结构修正" in n for n in d["notes"])
    assert k_max < 0.0515
    with pytest.raises(ValueError, match="可达范围"):
        hairpin_design_from_order(3, 2.5, 0.05, 20.0, kgap_corrected=True)


# ─── fake 电气通道同步 ────────────────────────────────────────────────────────

def _fake(variables: dict, n_pts: int = 301):
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="hairpin", n_ports=2, freq_ghz=(2.2, 2.8, n_pts), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables(dict(variables))
    report = ad.solve("hairpin_fake_kgap")
    assert report.success
    return ad.get_sparams()


def test_fake_hairpin_consumes_structural_correction():
    """fake gap→k 走 c(gap)·k_KJ（域外 clamp）：与直接以修正 k 构造的理想响应 ≤1e-9。"""
    from rfauto.adapters.fake_adapter import (
        _HAIRPIN_F0_CORR,
        _HAIRPIN_QE_CORR,
        _hairpin_sparams,
    )
    from rfauto.core.synthesis import Stackup, forward_z0

    arm_len, tau = 36.7799, 0.398159
    stack = Stackup(name="hairpin", epsilon_r=3.66, thickness_mm=0.508)
    _, eps_eff = forward_z0(W_MM, 2.5, stack)
    f0 = _HAIRPIN_F0_CORR * (299792458.0 / (2.0 * arm_len * 1e-3 * np.sqrt(eps_eff))) / 1e9
    qe = cm.hairpin_qe_from_tap_frac(tau) * (_HAIRPIN_QE_CORR[0] + _HAIRPIN_QE_CORR[1] * tau)
    lo, hi = cm.hairpin_kgap_domain_mm()
    for gap in (lo, 0.5 * (lo + hi), hi, hi + 0.6):     # 末项域外 → clamp 到 c(hi)
        nt = _fake({"order": "3", "w_mm": f"{W_MM}mm", "arm_len_mm": f"{arm_len}mm",
                    "gap_mm": f"{gap}mm", "tap_frac": str(tau)})
        k = cm.hairpin_k_from_gap_mm(gap, W_MM, structural_correction=True,
                                     extrapolate="clamp")
        ref = _hairpin_sparams(nt.frequency.f / 1e9, f0_ghz=f0, order=3, k_list=[k, k], qe=qe)
        assert float(np.max(np.abs(nt.s - ref))) <= 1e-9, gap
        assert k < cm.hairpin_k_from_gap_mm(gap, W_MM)   # 修正 k 严格低于纯 KJ


def test_fake_gap_sweep_bandwidth_monotone_on_design_branch():
    """设计支及以上（含域外 clamp 段，k_KJ 递减保证）gap↑ → 修正 k↓ → 3dB 带宽单调窄；
    极大点左侧（相消加剧支）不在此单调断言内（见 nonmonotone 测试）。"""
    import math

    g_peak, g_max = cm.hairpin_kgap_design_branch_mm(W_MM)
    widths = []
    for gap in np.concatenate([np.linspace(g_peak, g_max, 4), [g_max + 0.6]]):
        nt = _fake({"gap_mm": f"{gap}mm"}, n_pts=2401)      # 0.25MHz 步（带宽差 ~1MHz 级）
        f = nt.frequency.f / 1e9
        s21 = np.abs(nt.s[:, 1, 0])
        widths.append(float(np.ptp(f[s21 >= s21.max() / math.sqrt(2.0)])))
    assert all(a > b for a, b in pairwise(widths)), widths


# ─── 提取器（纯函数，合成回代）──────────────────────────────────────────────────

QE43, QU43 = 34.69064166747507, 236.34736862539347
GRID = np.linspace(2.0e9, 3.2e9, 401)


@pytest.mark.parametrize("k_true", [0.008, 0.015, 0.025, 0.04, 0.07])
def test_kgap_point_recovers_k_across_regimes(k_true):
    """峰电平（k<0.03）/全线形（k≥0.03）互补估计：0.5% 幅噪 + 随机相位下 ≤3%；一致性门 OK。"""
    rng = np.random.default_rng(int(k_true * 1e4))
    s21_db, s11_db = qx.coupled_model_s_db(GRID, 2.487e9, k_true, QE43, 2, QU43)
    ph = np.exp(1j * rng.uniform(0.0, 2 * np.pi, GRID.size))
    s21 = 10 ** (s21_db / 20) * (1 + 0.005 * rng.standard_normal(GRID.size)) * ph
    s11 = 10 ** (s11_db / 20) * (1 + 0.005 * rng.standard_normal(GRID.size)) * ph
    r = qx.kgap_point(GRID, s11, s21, QE43, QU43, 0.0515)
    assert r["verdict"] == "OK"
    assert r["k_em"] == pytest.approx(k_true, rel=0.03)
    assert r["method"] == ("peak_level" if k_true < 0.03 else "full_fit")
    assert r["c_kgap"] == pytest.approx(k_true / 0.0515, rel=0.03)


def test_n2_peak_level_monotone_and_saturation_flag():
    """N=2 模型 |S21|peak(k) 在 k≤0.03 严格单调（反演唯一）；峰高于 k_hi 模型峰 → saturated。"""
    peaks = []
    for k in (0.005, 0.01, 0.02, 0.03):
        s21_db, _ = qx.coupled_model_s_db(GRID, 2.5e9, k, QE43, 2, QU43)
        peaks.append(float(s21_db.max()))
    assert all(a < b for a, b in pairwise(peaks))
    s21_db, _ = qx.coupled_model_s_db(GRID, 2.5e9, 0.06, QE43, 2, QU43)
    r = qx.n2_k_from_peak_level(GRID, 10 ** (s21_db / 20), QE43, QU43)
    assert r["saturated"] is True and r["k"] is None


def test_kgap_curve_table_and_powerlaw_diagnostic():
    c = qx.kgap_curve([1.1328, 0.5, 0.8], [0.26, 0.40, 0.31])
    assert c["table"] == [[0.5, 0.40], [0.8, 0.31], [1.1328, 0.26]]
    assert c["domain_mm"] == [0.5, 1.1328]
    assert c["powerlaw"]["b"] < 0 and c["powerlaw"]["max_rel_resid"] < 0.1


# ─── 闭式独立源核实（#1b：NGSolve 2D 准静态偶/奇模）──────────────────────────────

def test_kj_closed_form_vs_ngsolve_quasistatic():
    """独立数值源：零厚条带（z=h 界面 Dirichlet 线）Laplace 能量法 C_air/C_d → Z0e/Z0o →
    k_NG；粗网格 k_NG/k_KJ∈[0.95,1.10]（细网格实测 1.018-1.020 @1.1328）。闭式不承担
    hairpin 3.9× 亏量——修正表是结构效应，不是闭式错误。"""
    pytest.importorskip("ngsolve")
    ratio = _ngsolve_k_ratio(W_MM, 1.1328)
    assert 0.95 <= ratio <= 1.10, ratio


def _ngsolve_k_ratio(w_mm: float, g_mm: float) -> float:
    from netgen.geom2d import SplineGeometry
    from ngsolve import (
        BND,
        CF,
        H1,
        BilinearForm,
        GridFunction,
        IfPos,
        Integrate,
        LinearForm,
        Mesh,
        dx,
        grad,
        y,
    )

    h_mm, er = 0.508, 3.66
    s = 1e-3
    h, lx, lz, near, far = h_mm * s, 25e-3, 12e-3, 0.12e-3, 1.2e-3
    strips = [(-g_mm / 2 - w_mm, -g_mm / 2, "strip1"), (g_mm / 2, g_mm / 2 + w_mm, "strip2")]

    def mesh_of():
        geo = SplineGeometry()

        def pt(a, b, mh=None):
            return geo.AppendPoint(a, b) if mh is None else geo.AppendPoint(a, b, maxh=mh)

        bl, br, rh, rt, tl, lh = (pt(-lx, 0), pt(lx, 0), pt(lx, h), pt(lx, lz),
                                  pt(-lx, lz), pt(-lx, h))
        geo.Append(["line", bl, br], bc="ground", leftdomain=1, rightdomain=0)
        geo.Append(["line", br, rh], bc="outer", leftdomain=1, rightdomain=0)
        geo.Append(["line", rh, rt], bc="outer", leftdomain=2, rightdomain=0)
        geo.Append(["line", rt, tl], bc="outer", leftdomain=2, rightdomain=0)
        geo.Append(["line", tl, lh], bc="outer", leftdomain=2, rightdomain=0)
        geo.Append(["line", lh, bl], bc="outer", leftdomain=1, rightdomain=0)
        cur = lh
        for x_lo, x_hi, name in strips:
            a, b = pt(x_lo * s, h, near), pt(x_hi * s, h, near)
            geo.Append(["line", cur, a], leftdomain=2, rightdomain=1)
            geo.Append(["line", a, b], bc=name, leftdomain=2, rightdomain=1, maxh=near)
            cur = b
        geo.Append(["line", cur, rh], leftdomain=2, rightdomain=1)
        geo.SetMaterial(1, "sub")
        geo.SetMaterial(2, "air")
        return Mesh(geo.GenerateMesh(maxh=far))

    def energy(eps_r: float, v2: float) -> float:
        msh = mesh_of()
        eps = IfPos(y - h, CF(1.0), CF(float(eps_r)))
        fes = H1(msh, order=2, dirichlet="ground|outer|strip1|strip2")
        u, v = fes.TnT()
        a = BilinearForm(fes)
        a += eps * grad(u) * grad(v) * dx
        a.Assemble()
        f = LinearForm(fes)
        f.Assemble()
        gfu = GridFunction(fes)
        gfu.Set(msh.BoundaryCF({"strip1": 1.0, "strip2": v2}, default=0.0), BND)
        res = f.vec.CreateVector()
        res.data = f.vec - a.mat * gfu.vec
        gfu.vec.data += a.mat.Inverse(fes.FreeDofs(), inverse="sparsecholesky") * res
        return float(Integrate(eps * grad(gfu) * grad(gfu), msh))

    c0 = 299792458.0
    z = {}
    for mode, v2 in (("even", 1.0), ("odd", -1.0)):
        c_d, c_a = energy(er, v2) / 2.0, energy(1.0, v2) / 2.0     # ε0 约去（比值/乘积同标）
        z[mode] = 1.0 / (c0 * np.sqrt(c_a * c_d))
    k_ng = (z["even"] - z["odd"]) / (z["even"] + z["odd"])
    return k_ng / cm.hairpin_k_from_gap_mm(g_mm, w_mm)
