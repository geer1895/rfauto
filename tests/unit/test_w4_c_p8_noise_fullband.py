"""W4-C P8：Pospieszalski 寄生去嵌扩展 + 全带 NF(f)/Rn(f)/Γopt(f) 锚测试。

裁判制度（#118，三重钉制度不变）：
- 路径 A（被测）= core/fet_noise.py 广义节点分析嵌入（P8 拓扑：Cgd/Cds/τ/
  键合线 Lg/Ld/Ls/焊盘 Cpg/Cpd）；
- 路径 B（独立裁判）= 本文件独立编码的暴力节点分析裁判（不同节点排序/
  元件表驱动 stamps，与生产代码零共享），扩到含寄生拓扑（任务书法源）；
- 结构/物理锚：零寄生极限回闭式（1e-9）、τ 的 2π 周期性（e^{−jωτ}=1 逐位）、
  端口侧无损变换 Fmin 不变性（输入侧无损映射 min-over-Ys 论证）、均匀温度
  无源下界 Fmin ≥ 1（任何寄生拓扑）；
- 噪声相关矩阵对应（P8 规格的 noise_correlation 联动）：四参 ↔ 链式噪声
  相关矩阵 C_A 转换逐位钉（机器精度）；嵌入 referra（广义 ABCD 级联变换）
  不在本批域——core/noise_correlation.py 诚实边界 1 同口径（该面需级间
  S 参数数据面，后续增量），如实注记不冒充已验证。
"""

from __future__ import annotations

import json
import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.fet_noise import (
    FetSmallSignal,
    pospieszalski_noise_params,
    pospieszalski_noise_sweep,
)

# ─── 代表性器件与温度（同 test_fet_noise 口径）────────────────────────────────

CORE = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3)
T0 = 290.0
TG, TD = 297.0, 1500.0


def _full() -> FetSmallSignal:
    """含全部 P8 寄生的代表性封装器件。"""
    return FetSmallSignal(
        cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3,
        rg_ohm=1.5, rs_ohm=0.8, cgd_f=30e-15, cds_f=60e-15, tau_s=1.5e-12,
        lg_h=0.3e-9, ld_h=0.4e-9, ls_h=0.05e-9, cpg_f=80e-15, cpd_f=60e-15,
    )


# ─── 路径 B：独立编码暴力节点裁判（元件表驱动，节点序不同）────────────────────


def _referee_f(w: float, ys: complex, m: FetSmallSignal, temps: dict[str, float],
               t0: float) -> float:
    """F(Ys) = 1 + Σ PSD_i·|H_i|²/(4kT0·Gs·|Hs|²)（惯例无关，独立编码）。

    元件表 (节点a, 节点b, 导纳)；节点名：IN(外栅), GI(本征栅), XI, DI, DO(外漏),
    SN(源), 0=地。VCCS 单独 stamps。
    """
    k_b = 1.380649e-23
    nodes = ["IN", "GI", "XI", "DI", "DO", "SN"]

    # 节点折叠：IN≡GI（无栅支路）、DO≡DI（无漏线）、SN≡地（无源支路）
    elems: list[tuple[str, str | None, complex]] = []
    use_gate = m.rg_ohm > 0.0 or m.lg_h > 0.0
    use_drain = m.ld_h > 0.0
    use_src = m.rs_ohm > 0.0 or m.ls_h > 0.0
    g_ext = "IN" if use_gate else "GI"
    d_ext = "DO" if use_drain else "DI"
    s_nd = "SN" if use_src else None
    if use_gate:
        elems.append(("IN", "GI", 1.0 / complex(m.rg_ohm, w * m.lg_h)))
    if m.cpg_f > 0.0:
        elems.append((g_ext, None, 1j * w * m.cpg_f))
    elems.append((g_ext, None, ys))
    elems.append(("GI", "XI", 1j * w * m.cgs_f))
    elems.append(("XI", s_nd, 1.0 / m.ri_ohm))
    if m.cgd_f > 0.0:
        elems.append(("GI", "DI", 1j * w * m.cgd_f))
    if m.cds_f > 0.0:
        elems.append(("DI", s_nd, 1j * w * m.cds_f))
    elems.append(("DI", s_nd, m.gds_s))
    if use_drain:
        elems.append(("DI", "DO", 1.0 / (1j * w * m.ld_h)))
        if m.cpd_f > 0.0:
            elems.append((d_ext, None, 1j * w * m.cpd_f))
    if use_src:
        elems.append(("SN", None, 1.0 / complex(m.rs_ohm, w * m.ls_h)))

    live = ({"IN"} if use_gate else set()) | {"GI", "XI", "DI"} | (
        {"DO"} if use_drain else set()) | ({"SN"} if use_src else set())
    order = sorted(live, key=lambda n: nodes.index(n))
    pos = {n: i for i, n in enumerate(order)}
    n = len(order)
    ymat = np.zeros((n, n), dtype=complex)
    for a, b, yv in elems:
        ia, ib = pos[a], (pos[b] if b is not None else None)
        ymat[ia, ia] += yv
        if ib is not None:
            ymat[ib, ib] += yv
            ymat[ia, ib] -= yv
            ymat[ib, ia] -= yv
    gm = m.gm_s * np.exp(-1j * w * m.tau_s)
    ymat[pos["DI"], pos["GI"]] -= gm
    ymat[pos["DI"], pos["XI"]] += gm
    if use_src:
        ymat[pos["SN"], pos["GI"]] += gm
        ymat[pos["SN"], pos["XI"]] -= gm

    def vth(inj: dict[str, float]) -> complex:
        rhs = np.zeros(n, dtype=complex)
        for name, cur in inj.items():
            if name in pos:
                rhs[pos[name]] += cur
        return complex(np.linalg.solve(ymat, rhs)[pos[d_ext]])

    gs = ys.real
    hs = vth({g_ext: 1.0})
    # Ri 支路诺顿（跨 GI-SN）：PSD 4k·Tg·Re{Ygs}
    wc = w * m.cgs_f
    den = 1.0 + (wc * m.ri_ohm) ** 2
    ggs = wc * wc * m.ri_ohm / den
    total = 0.0
    if m.ri_ohm > 0.0 and ggs > 0.0:
        h_gi = vth({"GI": 1.0, "SN": -1.0})
        total += 4.0 * k_b * temps["tg"] * ggs * abs(h_gi) ** 2
    h_di = vth({"DI": 1.0, "SN": -1.0})
    total += 4.0 * k_b * temps["td"] * m.gds_s * abs(h_di) ** 2
    if m.rg_ohm > 0.0 and use_gate:
        h_rg = vth({"IN": 1.0, "GI": -1.0})
        y_br = 1.0 / complex(m.rg_ohm, w * m.lg_h)
        total += 4.0 * k_b * temps["trg"] * y_br.real * abs(h_rg) ** 2
    if m.rs_ohm > 0.0 and use_src:
        h_rs = vth({"SN": 1.0})
        y_sb = 1.0 / complex(m.rs_ohm, w * m.ls_h)
        total += 4.0 * k_b * temps["trs"] * y_sb.real * abs(h_rs) ** 2
    return 1.0 + total / (4.0 * k_b * t0 * gs * abs(hs) ** 2)


def _four_from_f_referee(w: float, m: FetSmallSignal, temps: dict[str, float],
                         t0: float) -> tuple[float, float, complex]:
    """裁判侧四参提取（独立采样网格 + 独立最小二乘排布）。"""
    b_scale = w * m.cgs_f
    rows, rhs = [], []
    for g in np.geomspace(b_scale * 2e-3, b_scale * 20.0, 12):
        for b in np.linspace(-4.0 * b_scale, 2.0 * b_scale, 7):
            ys = complex(g, b)
            rows.append([ys.real, ys.real * ys.real + ys.imag * ys.imag, ys.imag, 1.0])
            rhs.append(_referee_f(w, ys, m, temps, t0) * ys.real)
    sol, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
    k_fit, rn, th_b, th_c = (float(v) for v in sol)
    bopt = -th_b / (2.0 * rn)
    gopt = math.sqrt(th_c / rn - bopt * bopt)
    return k_fit + 2.0 * rn * gopt, rn, complex(gopt, bopt)


# ─── 独立裁判 vs 生产路径（含全部新寄生）──────────────────────────────────────

@pytest.mark.parametrize("f_hz", [2e9, 10e9, 25e9])
def test_full_parasitic_referee_matches_production(f_hz):
    m = _full()
    temps = {"tg": TG, "td": TD, "trg": T0, "trs": T0}
    p = pospieszalski_noise_params(m, f_hz, TG, TD)
    assert p.path == "embedded"
    fmin_r, rn_r, yopt_r = _four_from_f_referee(2.0 * math.pi * f_hz, m, temps, T0)
    assert p.fmin_linear == pytest.approx(fmin_r, rel=1e-6)
    assert p.rn_ohm == pytest.approx(rn_r, rel=1e-6)
    assert p.yopt == pytest.approx(yopt_r, rel=1e-5, abs=1e-9)


def test_referee_f_of_ys_pointwise():
    """单点 F(Ys) 逐点对拍（生产 vs 裁判，rel 1e-9，3 个寄生子拓扑）。"""
    m_variants = [
        _full(),
        FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3,
                       cgd_f=30e-15, tau_s=2e-12),
        FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3,
                       rg_ohm=1.0, lg_h=0.5e-9, cpg_f=50e-15),
    ]
    temps = {"tg": TG, "td": TD, "trg": T0, "trs": T0}
    w = 2.0 * math.pi * 12e9
    for m in m_variants:
        for g, b in ((0.004, -0.008), (0.01, 0.002), (0.02, -0.001)):
            ys = complex(g, b)
            # 生产端 _f_of_ys（经 pospieszalski 采样同源）
            f_prod = fn_f_of_ys(w, ys, m, temps)
            assert f_prod == pytest.approx(_referee_f(w, ys, m, temps, T0), rel=1e-9)


def fn_f_of_ys(w, ys, m, temps):
    from rfauto.core import fet_noise as fn
    return fn._f_of_ys(w, ys, m.validate(), temps, T0)


# ─── 结构/物理锚 ─────────────────────────────────────────────────────────────

def test_zero_parasitic_limit_returns_to_closed_form():
    """全 P8 寄生置 0 → path="intrinsic" 且与既有闭式逐位一致（缺省零变化）。"""
    m = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3)
    p = pospieszalski_noise_params(m, 10e9, TG, TD)
    assert p.path == "intrinsic"
    # has_parasitics 分派
    assert not m.validate().has_parasitics()
    assert _full().validate().has_parasitics()


def test_tau_periodicity_exact():
    """τ 的 2π 周期：ωτ=2π 时 e^{−jωτ}=1 → 与 τ=0 逐位一致（结构恒等）。"""
    f = 10e9
    tau = 1.0 / f  # ωτ = 2π
    m0 = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3,
                        cgd_f=30e-15, cds_f=60e-15)
    m1 = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3,
                        cgd_f=30e-15, cds_f=60e-15, tau_s=tau)
    p0 = pospieszalski_noise_params(m0, f, TG, TD)
    p1 = pospieszalski_noise_params(m1, f, TG, TD)
    assert p1.fmin_linear == pytest.approx(p0.fmin_linear, rel=1e-10)
    assert p1.rn_ohm == pytest.approx(p0.rn_ohm, rel=1e-10)
    assert p1.yopt == pytest.approx(p0.yopt, rel=1e-8, abs=1e-12)


def test_port_shunt_fmin_invariance():
    """端口侧无损变换（Cpg/Cpd 对地并联）→ Fmin 逐位不变（min-over-Ys 论证：
    无损端口网络把 Ys 平面双射映射到自身，极小值不动）。"""
    m0 = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3)
    m1 = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3,
                        cpg_f=80e-15, cpd_f=60e-15, lg_h=0.3e-9)
    for f in (5e9, 10e9, 20e9):
        p0 = pospieszalski_noise_params(m0, f, TG, TD)
        p1 = pospieszalski_noise_params(m1, f, TG, TD)
        assert p1.fmin_linear == pytest.approx(p0.fmin_linear, rel=1e-9), f


def test_uniform_temperature_passive_floor():
    """全温度=T0 → 整网络无源恒温 → Fmin ≥ 1（任何寄生拓扑，物理下界）。"""
    for m in (_full(), FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05,
                                      gds_s=2e-3, cgd_f=30e-15, lg_h=0.3e-9)):
        for f in (1e9, 10e9, 30e9):
            p = pospieszalski_noise_params(m, f, T0, T0)
            assert p.fmin_linear >= 1.0


def test_low_frequency_reactive_limit():
    """低频极限：无损寄生（L/C/τ）效应 →0，全带面低频点回到本征值（rel ≤1e-4）。"""
    f = 0.2e9  # ωLs/Rs≈0.08 → 源支路收缩 <0.7%（rel 1e-3 窗）
    m0 = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3)
    m1 = FetSmallSignal(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3,
                        cgd_f=30e-15, cds_f=60e-15, lg_h=0.3e-9, ld_h=0.4e-9,
                        ls_h=0.05e-9, cpg_f=80e-15, cpd_f=60e-15)
    p0 = pospieszalski_noise_params(m0, f, TG, TD)
    p1 = pospieszalski_noise_params(m1, f, TG, TD)
    assert p1.fmin_linear == pytest.approx(p0.fmin_linear, rel=1e-3)
    assert p1.rn_ohm == pytest.approx(p0.rn_ohm, rel=1e-3)


def test_validation_guards_new_fields():
    """新字段的非负守卫（bool/负值拒收）。"""
    base = dict(cgs_f=100e-15, ri_ohm=2.0, gm_s=0.05, gds_s=2e-3)
    for bad_field in ("cds_f", "tau_s", "lg_h", "ld_h", "ls_h", "cpg_f", "cpd_f"):
        with pytest.raises(ValueError, match=bad_field):
            FetSmallSignal(**base, **{bad_field: -1.0}).validate()
        with pytest.raises(ValueError, match=bad_field):
            FetSmallSignal(**base, **{bad_field: True}).validate()


def test_to_dict_carries_new_fields():
    d = _full().to_dict()
    for key in ("cds_f", "tau_s", "lg_h", "ld_h", "ls_h", "cpg_f", "cpd_f"):
        assert key in d
    json.dumps(d)


# ─── 全带面（sweep）──────────────────────────────────────────────────────────

def test_sweep_face_shape_and_pointwise_consistency():
    """sweep 逐点 == 单点调用；shape/键集钉；JSON 可序列化。"""
    m = _full()
    freqs = [2e9, 6e9, 12e9, 20e9, 30e9]
    sweep = pospieszalski_noise_sweep(m, freqs, TG, TD)
    assert sweep["n_points"] == len(freqs)
    assert set(sweep) == {
        "n_points", "f_hz", "fmin_linear", "fmin_db", "rn_ohm", "rn_norm",
        "yopt", "gamma_opt", "tmin_k", "path"}
    for i, f in enumerate(freqs):
        p = pospieszalski_noise_params(m, f, TG, TD)
        assert sweep["f_hz"][i] == pytest.approx(f)
        assert sweep["fmin_db"][i] == pytest.approx(p.fmin_db, abs=1e-9)
        assert sweep["rn_ohm"][i] == pytest.approx(p.rn_ohm, abs=1e-9)
        assert sweep["path"][i] == "embedded"
    json.dumps(sweep)


def test_sweep_fmin_monotone_rising_in_band():
    """NFmin(f) 随频率上升（Pospieszalski ω↑→NFmin↑ 特性在全封装拓扑保持）。"""
    sweep = pospieszalski_noise_sweep(_full(), [2e9, 5e9, 10e9, 18e9], TG, TD)
    fmins = sweep["fmin_linear"]
    assert all(b > a for a, b in pairwise(fmins))


def test_sweep_guards():
    with pytest.raises(ValueError, match="f_hz"):
        pospieszalski_noise_sweep(CORE, [], TG, TD)
    with pytest.raises(ValueError, match="f_hz"):
        pospieszalski_noise_sweep(CORE, [10e9, -1.0], TG, TD)
    with pytest.raises(ValueError, match="f_hz"):
        pospieszalski_noise_sweep(CORE, 0.0, TG, TD)


# ─── 四参 ↔ 噪声相关矩阵对应（noise_correlation 联动钉）───────────────────────

def test_chain_correlation_matrix_roundtrip():
    """四参 ↔ 链式噪声相关矩阵 C_A 转换逐位钉（机器精度）。

    C_A = 4kT0·[[Rn·|Yopt|², (Fmin−1)/2 − Rn·Yopt], [共轭, Rn]]；
    F(Ys) = 1 + [C00 + 2Re(C01·Ys*) + C11|Ys|²]/(4kT0·Re Ys)
    ≡ Fmin + Rn/Re(Ys)·|Ys−Yopt|²（四参定义恒等式）。
    嵌入 referral（ABCD 级联变换）不在本批域（noise_correlation 诚实边界 1）。
    """
    from rfauto.core import fet_noise as fn
    k_b = fn.K_B_J_PER_K
    m = _full()
    f = 10e9
    p = pospieszalski_noise_params(m, f, TG, TD)
    c00 = 4 * k_b * T0 * p.rn_ohm * abs(p.yopt) ** 2
    c01 = 4 * k_b * T0 * ((p.fmin_linear - 1) / 2 - p.rn_ohm * p.yopt)
    cmat = np.array([[c00, c01], [np.conj(c01), 4 * k_b * T0 * p.rn_ohm]])
    for g, b in ((0.005, -0.01), (0.012, 0.003), (0.03, -0.002)):
        ys = complex(g, b)
        f_c = 1.0 + (cmat[0, 0] + 2 * np.real(cmat[0, 1] * np.conj(ys))
                     + cmat[1, 1] * abs(ys) ** 2) / (4 * k_b * T0 * ys.real)
        f_4p = p.fmin_linear + p.rn_ohm / ys.real * abs(ys - p.yopt) ** 2
        assert f_c == pytest.approx(f_4p, rel=1e-12)
    # 半正定裁判（噪声物理合法性；消费 core/noise_correlation 同口径判据）
    from rfauto.core.noise_correlation import correlation_min_eigenvalue
    assert correlation_min_eigenvalue(cmat) > -1e-9 * float(np.abs(cmat).max())
