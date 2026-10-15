"""aurora72 A4-B 席锚树：rcs_targets 两键（金属球 Mie/典型目标峰值 RCS）+
detector_device 两键（平方律检波/TSS-NEP）+ pim_cascade 两键（多节点累计/
PIM 级联预算）。

数值断言口径（#118 不自证——恒等式/独立常数/独立路线/跨键互证，不用
自身推导互证）：
- 金属球 Mie：双解析极限独立锚（Rayleigh 9πa²(ka)⁴ 闭式窗 ka≤0.1
  rel≤2e-3 + 光学 πa² 窗 ka≥30 |dev|≤0.1dB）+ f⁴ 标度（ρ0.02×2 →
  比值 16±0.01 高阶项实测带）+ 测试侧独立 Mie 实现（对数导数 D_n 降序
  递推 + Riccati-Bessel 三项上行递推 + 导数递推恒等式 ψ'_n=ψ_{n-1}−
  n/ρ·ψ_n——与本键 scipy 球 Bessel 直算不同路线）六点 ρ 互证 ≤1e-9；
  三区判据边界双侧钉（0.499/0.501、9.99/10.01 构造半径）；ka 稳定域
  守卫（>200 拒绝）。
- 峰值库：全闭式测试侧独立重算（平板 4πA²/λ²/二面角 8πa²b²/λ²/
  三方角 4πa⁴/(3λ²)/圆柱 2πL²r/λ 四式）；1m² 平板@10GHz=41.45dBsm
  常数窗；板族 λ⁻² 与圆柱 λ⁻¹ 双标度逐位；二面角(a=b)=2×同单面平板
  与三方角等效孔径 a²/√3 回代平板式两结构恒等；dBsm 换算恒等。
- 检波：I_dc=k·R_j·P_in 测试侧独立重算逐位（−30dBm/50µA V⁻²/250Ω →
  12.5nA 常数）；P×2→I×2 线性标度逐位；β 常数性两功率点同值；
  V_video=I·R_v 回代；平方律域守卫双侧（−19/−121 拒绝）。
- TSS/NEP：v_n=√(4k_BT·R_v·B_v) 测试侧独立常数（k_B=1.380649e-23
  精确定义值）重算（γ=1000V/W/1MΩ/1MHz/290K → NEP=−38.977dBm 窗）；
  B×4→NEP 恰 +3.0103dB；TSS−NEP=snr/2 恒等（8→4.0、6→3.0 两点）；
  守卫族。
- PIM 合成：N=1 退化恒等（双口径=本级、spread=0）；两等电平 +3.0103/
  +6.0206dB 解析钉；N=4 等电平 +10log10(4)/+20log10(4) 恒等；混合
  三节点双口径测试侧独立重算；spread∈[0,20log10N] 界；占比和=100。
- PIM 预算：p_carrier=p_ref → 与合成键同电平逐位互证（跨键）；ΔP=
  +1dB/IM3 → 每节点与总量恰 +3.0dB（精确律）；单节点退化=本级平移；
  斜率覆盖 2.5×ΔP=2 → 恰 +5.0dB；限值裕量恒等式+相干负裕量如实
  报告；守卫族（order 域/类型、空节点、缺 level_dbm、斜率 ≤0）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

_C_MM_GHZ = 299.792458          # mm·GHz（测试侧独立常量，同注册表锚值）
_K_B = 1.380649e-23             # 玻尔兹曼常数（SI 2019 精确定义值）


# ─── 公共小工具 ──────────────────────────────────────────────────────────────


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"] is True, f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


def _reject(key: str, params: dict, needle: str | None = None) -> None:
    out = run_calculator(key, params)
    assert out["ok"] is False, f"{key} 越界输入未拒绝: {params!r}"
    if needle is not None:
        assert needle in str(out.get("error")), (
            f"{key} 拒绝语义不符: {out.get('error')!r}")


def _ka(radius_mm: float, f_ghz: float) -> float:
    """尺寸参数 ka=2πa/λ（测试侧独立换算，λ=C_MM_GHZ/f mm 口径）。"""
    return 2.0 * math.pi * (radius_mm * 1e-3) / (_C_MM_GHZ / f_ghz * 1e-3)


def _sigma_mie_logder(rho: float) -> float:
    """测试侧独立 Mie 实现（PEC 球后向散射，对数导数降序递推路线）。

    返回归一效率 |S_b|²/ρ²（σ=πa²·效率，与内核效率口径同轴）。
    与内核 scipy 球 Bessel 直算不同数值路线：D_n=ψ'_n/ψ_n 降序递推起
    D_{N+1}=0；ψ/χ 三项上行递推（sin/cos 种子）；导数用递推恒等式
    ψ'_n=ψ_{n-1}−(n/ρ)ψ_n。同物理异实现（#118 双实现互证载体）。
    """
    n_max = max(int(rho + 4.05 * rho ** (1.0 / 3.0)) + 8, 8)
    # 对数导数降序递推：D_{n-1} = n/ρ − 1/(D_n + n/ρ)，种子 D_{N+1}=0
    dn = 0.0
    log_der: dict[int, float] = {}
    for n in range(n_max + 1, 0, -1):
        dn = n / rho - 1.0 / (dn + n / rho)
        log_der[n] = dn
    psi = [0.0] * (n_max + 1)
    chi = [0.0] * (n_max + 1)
    psi[0] = math.sin(rho)
    chi[0] = math.cos(rho)
    psi[1] = math.sin(rho) / rho - math.cos(rho)
    chi[1] = math.cos(rho) / rho + math.sin(rho)
    for n in range(1, n_max):
        psi[n + 1] = (2 * n + 1) / rho * psi[n] - psi[n - 1]
        chi[n + 1] = (2 * n + 1) / rho * chi[n] - chi[n - 1]
    s_b = 0.0 + 0j
    for n in range(1, n_max + 1):
        psi_d = psi[n - 1] - n / rho * psi[n]
        chi_d = chi[n - 1] - n / rho * chi[n]
        xi = psi[n] - 1j * chi[n]
        xi_d = psi_d - 1j * chi_d
        a_n = -psi_d / xi_d
        b_n = -psi[n] / xi
        s_b += (-1.0) ** n * (2 * n + 1) * (a_n - b_n)
    return abs(s_b) ** 2 / rho ** 2


# ─── rcs_sphere_mie：双解析极限 / f⁴ 标度 / 独立路线互证 / 三区判据 ──────────


@pytest.mark.parametrize("radius_mm,f_ghz,window", [
    (0.5, 2.0, 2e-4),    # ka≈0.021 深瑞利
    (1.0, 10.0, 1e-2),   # ka≈0.209
    (2.0, 10.0, 5e-2),   # ka≈0.419 瑞利窗沿（高阶项偏离增大，窗如实放宽）
])
def test_sphere_rayleigh_limit_closed_form(radius_mm, f_ghz, window):
    """Rayleigh 闭式锚：σ→9πa²(ka)⁴（测试侧独立闭式，逐点窗）。"""
    r = _run("rcs_sphere_mie", {"radius_mm": radius_mm, "f_ghz": f_ghz})
    ka = _ka(radius_mm, f_ghz)
    assert r["ka"] == pytest.approx(ka, rel=1e-12)
    assert r["region"] == "rayleigh"
    ray_m2 = 9.0 * math.pi * (radius_mm * 1e-3) ** 2 * ka ** 4
    assert abs(r["sigma_m2"] - ray_m2) / ray_m2 <= window
    assert r["rayleigh_rel_dev"] == pytest.approx(
        (r["sigma_m2"] - ray_m2) / ray_m2, abs=1e-12)


def test_sphere_rayleigh_deep_window_tight():
    """深瑞利窗（ka≈0.02）：对闭式偏差 ≤1e-4（高阶项收敛实测带）。"""
    f_ghz = 0.02 * _C_MM_GHZ / (2.0 * math.pi * 0.5)  # radius 0.5mm
    r = _run("rcs_sphere_mie", {"radius_mm": 0.5, "f_ghz": f_ghz})
    assert _ka(0.5, f_ghz) == pytest.approx(0.02, rel=1e-9)
    assert abs(r["rayleigh_rel_dev"]) <= 1e-4


def test_sphere_f4_scaling():
    """f⁴ 标度（瑞利区）：f×2 → σ×16（高阶项偏差 ≤0.01，实测 3.6e-3）。"""
    r1 = _run("rcs_sphere_mie", {"radius_mm": 0.5, "f_ghz": 2.0})
    r2 = _run("rcs_sphere_mie", {"radius_mm": 0.5, "f_ghz": 4.0})
    ratio = r2["sigma_m2"] / r1["sigma_m2"]
    assert abs(ratio - 16.0) < 0.01


@pytest.mark.parametrize("radius_mm,f_ghz,window_db", [
    (50.0, 30.0, 0.1),   # ρ≈31.4
    (30.0, 30.0, 0.25),  # ρ≈18.9
])
def test_sphere_optical_limit(radius_mm, f_ghz, window_db):
    """光学极限锚：σ→πa²（消光佯谬后向版；ka≥19 窗 |dev|≤0.25dB）。"""
    r = _run("rcs_sphere_mie", {"radius_mm": radius_mm, "f_ghz": f_ghz})
    assert r["region"] == "optical"
    assert abs(r["optical_dev_db"]) <= window_db
    assert r["optical_m2"] == pytest.approx(
        math.pi * (radius_mm * 1e-3) ** 2, rel=1e-15)


@pytest.mark.parametrize("rho", [0.05, 0.3, 1.0, 3.0, 7.0, 15.0])
def test_sphere_independent_mie_route(rho):
    """独立路线互证：对数导数降序递推实现 vs 内核 ≤1e-9（六点 ρ）。

    两路线同归一效率口径（|S_b|²/ρ²；内核 σ/(πa²) 还原，测试路线原生）。
    """
    radius_mm = 10.0
    f_ghz = rho * _C_MM_GHZ / (2.0 * math.pi * (radius_mm * 1e-3)) / 1e3
    r = _run("rcs_sphere_mie", {"radius_mm": radius_mm, "f_ghz": f_ghz})
    assert r["ka"] == pytest.approx(rho, rel=1e-9)
    eff_kernel = r["sigma_m2"] / (math.pi * (radius_mm * 1e-3) ** 2)
    eff_test = _sigma_mie_logder(rho)
    assert eff_kernel == pytest.approx(eff_test, rel=1e-9)


def test_sphere_region_boundaries():
    """三区判据边界双侧钉（工程带 0.5/10，docstring 口径）。"""
    # ka=0.499 → rayleigh；ka=0.501 → mie；ka=9.99 → mie；ka=10.02 → optical
    a_f = 0.499 * _C_MM_GHZ / (2.0 * math.pi)
    assert _run("rcs_sphere_mie", {"radius_mm": a_f, "f_ghz": 1.0}
                )["region"] == "rayleigh"
    a_f = 0.501 * _C_MM_GHZ / (2.0 * math.pi)
    assert _run("rcs_sphere_mie", {"radius_mm": a_f, "f_ghz": 1.0}
                )["region"] == "mie"
    a_f = 9.99 * _C_MM_GHZ / (2.0 * math.pi)
    assert _run("rcs_sphere_mie", {"radius_mm": a_f, "f_ghz": 1.0}
                )["region"] == "mie"
    a_f = 10.02 * _C_MM_GHZ / (2.0 * math.pi)
    assert _run("rcs_sphere_mie", {"radius_mm": a_f, "f_ghz": 1.0}
                )["region"] == "optical"


def test_sphere_mie_region_oscillation_reported():
    """Mie 过渡区单点振荡：10GHz/10mm 球（ρ≈2.1）非极限值，如实出 note。"""
    r = _run("rcs_sphere_mie", {"radius_mm": 10.0, "f_ghz": 10.0})
    assert r["region"] == "mie"
    assert "振荡" in r["note"]


def test_sphere_dbsm_identity_and_stability_guard():
    """dBsm 换算恒等 + ka 稳定域守卫（>200 显式拒绝）。"""
    r = _run("rcs_sphere_mie", {"radius_mm": 10.0, "f_ghz": 10.0})
    assert r["sigma_dbsm"] == pytest.approx(
        10.0 * math.log10(r["sigma_m2"]), abs=1e-9)
    # ka=200 边界：a·f = 200·299.792458/(2π) ≈ 9542.97 mm·GHz → 恰域内
    a_f = 200.0 * _C_MM_GHZ / (2.0 * math.pi)
    assert _run("rcs_sphere_mie", {"radius_mm": a_f, "f_ghz": 1.0})["ka"] == (
        pytest.approx(200.0, rel=1e-9))
    _reject("rcs_sphere_mie", {"radius_mm": a_f * 1.01, "f_ghz": 1.0},
            "稳定域")


# ─── rcs_peak_canonical：四式独立重算 / 双标度 / 两结构恒等 / 守卫 ────────────


def test_peak_flat_plate_constant():
    """平板常数锚：1m²@10GHz → σ=4π/0.03²=13962.6 m² = 41.45 dBsm 窗。"""
    r = _run("rcs_peak_canonical", {"shape": "flat_plate", "f_ghz": 10.0,
                                    "a_mm": 1000.0, "b_mm": 1000.0})
    lam = _C_MM_GHZ / 10.0 * 1e-3
    expect = 4.0 * math.pi * 1.0 ** 2 / lam ** 2
    assert r["sigma_m2"] == pytest.approx(expect, rel=1e-12)
    assert r["sigma_dbsm"] == pytest.approx(41.45, abs=0.01)
    assert r["effective_aperture_m2"] == pytest.approx(1.0, rel=1e-12)


@pytest.mark.parametrize("shape,extra", [
    ("flat_plate", {"b_mm": 80.0}),
    ("dihedral", {"b_mm": 60.0}),
    ("square_trihedral", {}),
    ("cylinder_broadside", {"b_mm": 150.0}),
])
def test_peak_closed_forms_independent_recompute(shape, extra):
    """四闭式测试侧独立重算（峰值库逐式逐位）。"""
    params = {"shape": shape, "f_ghz": 10.0, "a_mm": 40.0, **extra}
    r = _run("rcs_peak_canonical", params)
    lam = _C_MM_GHZ / 10.0 * 1e-3
    a_m, b_m = 0.04, extra.get("b_mm", 0.0) * 1e-3
    if shape == "flat_plate":
        expect = 4.0 * math.pi * (a_m * b_m) ** 2 / lam ** 2
    elif shape == "dihedral":
        expect = 8.0 * math.pi * (a_m * b_m) ** 2 / lam ** 2
    elif shape == "square_trihedral":
        expect = 4.0 * math.pi * a_m ** 4 / (3.0 * lam ** 2)
    else:
        expect = 2.0 * math.pi * b_m ** 2 * a_m / lam
    assert r["sigma_m2"] == pytest.approx(expect, rel=1e-12)
    assert r["sigma_dbsm"] == pytest.approx(10.0 * math.log10(expect),
                                            rel=1e-12)


def test_peak_lambda_scaling_two_laws():
    """双标度结构钉：板族 f×2 → σ×4（λ⁻²）；圆柱 f×2 → σ×2（λ⁻¹）。"""
    for shape in ("flat_plate", "dihedral", "square_trihedral"):
        extra = {} if shape == "square_trihedral" else {"b_mm": 50.0}
        r1 = _run("rcs_peak_canonical", {"shape": shape, "f_ghz": 6.0,
                                         "a_mm": 30.0, **extra})
        r2 = _run("rcs_peak_canonical", {"shape": shape, "f_ghz": 12.0,
                                         "a_mm": 30.0, **extra})
        assert r2["sigma_m2"] == pytest.approx(4.0 * r1["sigma_m2"],
                                               rel=1e-12)
    c1 = _run("rcs_peak_canonical", {"shape": "cylinder_broadside",
                                     "f_ghz": 6.0, "a_mm": 20.0,
                                     "b_mm": 100.0})
    c2 = _run("rcs_peak_canonical", {"shape": "cylinder_broadside",
                                     "f_ghz": 12.0, "a_mm": 20.0,
                                     "b_mm": 100.0})
    assert c2["sigma_m2"] == pytest.approx(2.0 * c1["sigma_m2"], rel=1e-12)


def test_peak_dihedral_equals_two_flat_plates():
    """结构恒等：二面角(a=b)=2×同单面面积平板（8πa⁴ = 2·4πa⁴）。"""
    d = _run("rcs_peak_canonical", {"shape": "dihedral", "f_ghz": 10.0,
                                    "a_mm": 40.0, "b_mm": 40.0})
    p = _run("rcs_peak_canonical", {"shape": "flat_plate", "f_ghz": 10.0,
                                    "a_mm": 40.0, "b_mm": 40.0})
    assert d["sigma_m2"] == pytest.approx(2.0 * p["sigma_m2"], rel=1e-12)
    assert d["effective_aperture_m2"] == pytest.approx(
        math.sqrt(2.0) * 0.04 ** 2, rel=1e-12)


def test_peak_trihedral_effective_aperture_flat_plate_route():
    """结构恒等：三方角按等效孔径 a²/√3 回代平板式（4π(a²/√3)²=4πa⁴/3）。"""
    t = _run("rcs_peak_canonical", {"shape": "square_trihedral",
                                    "f_ghz": 10.0, "a_mm": 40.0})
    a_eff = t["effective_aperture_m2"]
    lam = _C_MM_GHZ / 10.0 * 1e-3
    assert a_eff == pytest.approx(0.04 ** 2 / math.sqrt(3.0), rel=1e-12)
    flat_route = 4.0 * math.pi * a_eff ** 2 / lam ** 2
    assert t["sigma_m2"] == pytest.approx(flat_route, rel=1e-12)


def test_peak_guards():
    """守卫族：非法 shape/缺 b/b≤0/a≤0/f≤0/三方角多给 b。"""
    _reject("rcs_peak_canonical", {"shape": "cone_tip", "f_ghz": 10.0,
                                   "a_mm": 40.0}, "shape")
    _reject("rcs_peak_canonical", {"shape": "flat_plate", "f_ghz": 10.0,
                                   "a_mm": 40.0}, "b_mm")
    _reject("rcs_peak_canonical", {"shape": "flat_plate", "f_ghz": 10.0,
                                   "a_mm": 40.0, "b_mm": 0.0}, "b_mm")
    _reject("rcs_peak_canonical", {"shape": "square_trihedral",
                                   "f_ghz": 10.0, "a_mm": 0.0}, "a_mm")
    _reject("rcs_peak_canonical", {"shape": "square_trihedral",
                                   "f_ghz": -1.0, "a_mm": 40.0}, "f_ghz")
    _reject("rcs_peak_canonical", {"shape": "square_trihedral",
                                   "f_ghz": 10.0, "a_mm": 40.0,
                                   "b_mm": 10.0}, "b_mm")


# ─── diode_square_law_detect：恒等式/线性标度/β 常数性/守卫 ──────────────────


def test_detect_constant_anchor():
    """常数锚：−30dBm/k=50µAV⁻²/R_j=250Ω → I_dc=12.5nA（独立链重算）。"""
    r = _run("diode_square_law_detect", {"p_in_dbm": -30.0, "k_uav2": 50.0,
                                         "r_j_ohm": 250.0})
    p_w = 10.0 ** (-3.0) * 1e-3            # −30dBm → 1e-6 W（独立换算）
    v_rms = math.sqrt(p_w * 250.0)
    i_dc = 50.0e-6 * v_rms ** 2
    assert r["p_in_w"] == pytest.approx(p_w, rel=1e-12)
    assert r["v_rms_v"] == pytest.approx(v_rms, rel=1e-12)
    assert r["i_dc_a"] == pytest.approx(i_dc, rel=1e-12)
    assert r["i_dc_a"] == pytest.approx(12.5e-9, rel=1e-12)
    assert r["v_video_v"] == pytest.approx(i_dc * 1e6, rel=1e-12)


def test_detect_identity_and_linearity():
    """I_dc=k·R_j·P_in 恒等逐位 + P×2→I×2 线性标度逐位（平方律恒等锚）。"""
    for p_dbm in (-40.0, -30.0, -21.0):
        r = _run("diode_square_law_detect", {"p_in_dbm": p_dbm,
                                             "k_uav2": 50.0,
                                             "r_j_ohm": 250.0})
        p_w = 10.0 ** (p_dbm / 10.0) * 1e-3
        assert r["i_dc_a"] == pytest.approx(50.0e-6 * 250.0 * p_w,
                                            rel=1e-12)
    lo = _run("diode_square_law_detect", {"p_in_dbm": -34.0, "k_uav2": 20.0,
                                          "r_j_ohm": 100.0})
    hi = _run("diode_square_law_detect",
              {"p_in_dbm": -34.0 + 3.0102999566398, "k_uav2": 20.0,
               "r_j_ohm": 100.0})
    assert hi["p_in_w"] == pytest.approx(2.0 * lo["p_in_w"], rel=1e-9)
    assert hi["i_dc_a"] == pytest.approx(2.0 * lo["i_dc_a"], rel=1e-9)


def test_detect_sensitivity_beta_constant():
    """β=k·R_j 常数性：两功率点 beta_a_per_w 同值（平方律区灵敏度不变）。"""
    r1 = _run("diode_square_law_detect", {"p_in_dbm": -40.0, "k_uav2": 50.0,
                                          "r_j_ohm": 250.0})
    r2 = _run("diode_square_law_detect", {"p_in_dbm": -22.0, "k_uav2": 50.0,
                                          "r_j_ohm": 250.0})
    assert r1["beta_a_per_w"] == pytest.approx(0.0125, rel=1e-12)
    assert r1["beta_a_per_w"] == r2["beta_a_per_w"]
    assert r1["beta_xcheck_rel_dev"] <= 1e-12


def test_detect_video_load_scaling_and_guards():
    """V_video=I·R_v 回代 + 平方律域双侧守卫（−19 越上沿/−121 越下沿）。"""
    r = _run("diode_square_law_detect", {"p_in_dbm": -30.0, "k_uav2": 50.0,
                                         "r_j_ohm": 250.0, "r_v_ohm": 1e4})
    assert r["v_video_v"] == pytest.approx(r["i_dc_a"] * 1e4, rel=1e-12)
    _reject("diode_square_law_detect", {"p_in_dbm": -19.0, "k_uav2": 50.0,
                                        "r_j_ohm": 250.0}, "平方律有效域")
    _reject("diode_square_law_detect", {"p_in_dbm": -121.0, "k_uav2": 50.0,
                                        "r_j_ohm": 250.0}, "平方律有效域")
    _reject("diode_square_law_detect", {"p_in_dbm": -30.0, "k_uav2": 0.0,
                                        "r_j_ohm": 250.0}, "k_uav2")
    _reject("diode_square_law_detect", {"p_in_dbm": -30.0, "k_uav2": 50.0,
                                        "r_j_ohm": 0.0}, "r_j_ohm")
    _reject("diode_square_law_detect", {"p_in_dbm": -30.0, "k_uav2": 50.0,
                                        "r_j_ohm": 250.0, "r_v_ohm": -1.0},
            "r_v_ohm")
    # 上沿自定义：p_sq_max_dbm=−10 → −19dBm 合法入域
    r = _run("diode_square_law_detect", {"p_in_dbm": -19.0, "k_uav2": 50.0,
                                         "r_j_ohm": 250.0,
                                         "p_sq_max_dbm": -10.0})
    assert r["region"] == "square_law"


# ─── detector_tss_nep：v_n 独立重算 / √B 标度 / TSS−NEP 恒等 / 守卫 ──────────


def test_tss_noise_chain_constant():
    """噪声链常数锚：γ=1000V/W/1MΩ/1MHz/290K → v_n/NEP/TSS 全链独立重算。"""
    r = _run("detector_tss_nep", {"gamma_v_per_w": 1000.0})
    v_n = math.sqrt(4.0 * _K_B * 290.0 * 1e6 * 1e6)
    nep_w = v_n / 1000.0
    tss_w = nep_w * 10.0 ** (0.4)
    assert r["v_noise_rms_v"] == pytest.approx(v_n, rel=1e-12)
    assert r["nep_w"] == pytest.approx(nep_w, rel=1e-12)
    assert r["nep_dbm"] == pytest.approx(10.0 * math.log10(nep_w) + 30.0,
                                         abs=1e-9)
    assert r["nep_dbm"] == pytest.approx(-38.98, abs=0.01)
    assert r["tss_w"] == pytest.approx(tss_w, rel=1e-12)
    assert r["tss_dbm"] == pytest.approx(10.0 * math.log10(tss_w) + 30.0,
                                         abs=1e-9)


def test_tss_sqrt_bandwidth_scaling():
    """√B 标度逐位：B×4 → v_n×2 → NEP×2（恰 +3.0103dB）。"""
    r1 = _run("detector_tss_nep", {"gamma_v_per_w": 2000.0,
                                   "b_video_hz": 1e6})
    r2 = _run("detector_tss_nep", {"gamma_v_per_w": 2000.0,
                                   "b_video_hz": 4e6})
    assert r2["nep_w"] == pytest.approx(2.0 * r1["nep_w"], rel=1e-12)
    assert r2["nep_dbm"] - r1["nep_dbm"] == pytest.approx(3.0102999566, abs=1e-9)


def test_tss_minus_nep_identity():
    """TSS−NEP=snr/2 dB 恒等（8dB 判据→4.0dB；自定义 6dB→3.0dB 两点）。"""
    r8 = _run("detector_tss_nep", {"gamma_v_per_w": 1000.0})
    assert r8["tss_minus_nep_db"] == pytest.approx(4.0, abs=1e-12)
    assert r8["tss_dbm"] - r8["nep_dbm"] == pytest.approx(4.0, abs=1e-9)
    r6 = _run("detector_tss_nep", {"gamma_v_per_w": 1000.0,
                                   "snr_tss_db": 6.0})
    assert r6["tss_dbm"] - r6["nep_dbm"] == pytest.approx(3.0, abs=1e-9)
    assert "8.0" in r8["convention"]


def test_tss_temperature_and_load_scaling():
    """T×4 → v_n×2（√T 标度）；R_v×4 → NEP×2（√R_v 标度）逐位。"""
    r1 = _run("detector_tss_nep", {"gamma_v_per_w": 1000.0, "t_kelvin": 290.0})
    r2 = _run("detector_tss_nep", {"gamma_v_per_w": 1000.0, "t_kelvin": 1160.0})
    assert r2["v_noise_rms_v"] == pytest.approx(2.0 * r1["v_noise_rms_v"],
                                                rel=1e-12)
    r3 = _run("detector_tss_nep", {"gamma_v_per_w": 1000.0, "r_v_ohm": 4e6})
    assert r3["nep_w"] == pytest.approx(2.0 * r1["nep_w"], rel=1e-12)


def test_tss_guards():
    """守卫族：γ/R_v/B/T 非正 + snr 域外（0/40/−1）。"""
    _reject("detector_tss_nep", {"gamma_v_per_w": 0.0}, "gamma_v_per_w")
    _reject("detector_tss_nep", {"gamma_v_per_w": 1000.0, "r_v_ohm": 0.0},
            "r_v_ohm")
    _reject("detector_tss_nep", {"gamma_v_per_w": 1000.0, "b_video_hz": -1.0},
            "b_video_hz")
    _reject("detector_tss_nep", {"gamma_v_per_w": 1000.0, "t_kelvin": 0.0},
            "t_kelvin")
    _reject("detector_tss_nep", {"gamma_v_per_w": 1000.0, "snr_tss_db": 0.0},
            "snr_tss_db")
    _reject("detector_tss_nep", {"gamma_v_per_w": 1000.0, "snr_tss_db": 40.0},
            "snr_tss_db")
    _reject("detector_tss_nep", {"gamma_v_per_w": 1000.0, "snr_tss_db": -1.0},
            "snr_tss_db")


# ─── pim_nodes_combine：退化恒等 / 等电平恒等 / 独立重算 / 界 / 守卫 ─────────


def test_pim_single_node_degenerate():
    """N=1 退化恒等：双口径=本级电平、spread=0、占比 100。"""
    r = _run("pim_nodes_combine", {"levels_dbm": [-100.0]})
    assert r["n_nodes"] == 1
    assert r["p_incoherent_dbm"] == pytest.approx(-100.0, abs=1e-12)
    assert r["p_coherent_dbm"] == pytest.approx(-100.0, abs=1e-12)
    assert r["spread_db"] == pytest.approx(0.0, abs=1e-12)
    assert r["dominant_index"] == 0
    assert r["shares_pct"] == pytest.approx([100.0], abs=1e-9)


@pytest.mark.parametrize("n", [2, 4, 8])
def test_pim_equal_levels_laws(n):
    """等电平恒等：+10log10N（非相干）/ +20log10N（相干）解析钉。"""
    r = _run("pim_nodes_combine", {"levels_dbm": [-110.0] * n})
    assert r["p_incoherent_dbm"] == pytest.approx(-110.0 + 10.0 * math.log10(n),
                                                  abs=1e-9)
    assert r["p_coherent_dbm"] == pytest.approx(-110.0 + 20.0 * math.log10(n),
                                                abs=1e-9)
    assert r["spread_db"] == pytest.approx(10.0 * math.log10(n), abs=1e-9)


def test_pim_two_equal_analytic():
    """两等电平解析钉：+3.0103 / +6.0206 dB。"""
    r = _run("pim_nodes_combine", {"levels_dbm": [-110.0, -110.0]})
    assert r["p_incoherent_dbm"] == pytest.approx(-106.989700043, abs=1e-6)
    assert r["p_coherent_dbm"] == pytest.approx(-103.979400087, abs=1e-6)


def test_pim_mixed_independent_recompute():
    """混合三节点双口径测试侧独立重算 + 占比和=100 + spread 界。"""
    levels = [-110.0, -115.0, -120.0]
    r = _run("pim_nodes_combine", {"levels_dbm": levels})
    p_lin = [10.0 ** (lv / 10.0) for lv in levels]
    assert r["p_incoherent_dbm"] == pytest.approx(
        10.0 * math.log10(sum(p_lin)), abs=1e-9)
    assert r["p_coherent_dbm"] == pytest.approx(
        20.0 * math.log10(sum(math.sqrt(p) for p in p_lin)), abs=1e-9)
    assert sum(r["shares_pct"]) == pytest.approx(100.0, abs=1e-9)
    assert r["shares_pct"][0] == pytest.approx(
        100.0 * p_lin[0] / sum(p_lin), abs=1e-9)
    assert r["dominant_index"] == 0
    assert 0.0 <= r["spread_db"] <= 20.0 * math.log10(3.0) + 1e-12


def test_pim_combine_guards():
    """守卫族：空列表/非列表/非法元素（字符串→float 拒绝/None→TypeError）。"""
    _reject("pim_nodes_combine", {"levels_dbm": []}, "非空")
    _reject("pim_nodes_combine", {"levels_dbm": "-110"}, "数值列表")
    _reject("pim_nodes_combine", {"levels_dbm": [-110.0, "x"]}, "float")
    _reject("pim_nodes_combine", {"levels_dbm": [-110.0, None]})


# ─── pim_cascade_budget：跨键互证 / 精确律 / 退化 / 覆盖斜率 / 裕量 / 守卫 ────


def test_pim_budget_zero_shift_cross_key():
    """跨键互证：p_carrier=p_ref → 预算键双口径与合成键逐位一致。"""
    levels = [-110.0, -115.0, -118.0]
    comb = _run("pim_nodes_combine", {"levels_dbm": levels})
    bud = _run("pim_cascade_budget", {
        "nodes": [{"level_dbm": lv} for lv in levels],
        "p_carrier_dbm": 43.0})
    assert bud["shift_db"] == pytest.approx(0.0, abs=1e-12)
    assert bud["p_incoherent_dbm"] == comb["p_incoherent_dbm"]
    assert bud["p_coherent_dbm"] == comb["p_coherent_dbm"]
    assert bud["spread_db"] == comb["spread_db"]
    assert bud["order"] == 3 and bud["p_ref_dbm"] == 43.0


def test_pim_budget_exact_power_law():
    """精确律：ΔP=+1dB/IM3 → 每节点恰 +3.0dB、总量恰 +3.0dB。"""
    nodes = [{"level_dbm": -110.0}, {"level_dbm": -115.0}]
    base = _run("pim_cascade_budget", {"nodes": nodes, "p_carrier_dbm": 43.0})
    shifted = _run("pim_cascade_budget", {"nodes": nodes,
                                          "p_carrier_dbm": 44.0})
    assert shifted["shift_db"] == pytest.approx(3.0, abs=1e-12)
    for row in shifted["nodes"]:
        assert row["level_at_carrier_dbm"] == pytest.approx(
            row["level_ref_dbm"] + 3.0, abs=1e-12)
    assert shifted["p_incoherent_dbm"] == pytest.approx(
        base["p_incoherent_dbm"] + 3.0, abs=1e-9)
    assert shifted["p_coherent_dbm"] == pytest.approx(
        base["p_coherent_dbm"] + 3.0, abs=1e-9)
    assert shifted["spread_db"] == pytest.approx(base["spread_db"], abs=1e-9)


def test_pim_budget_im2_order_and_single_node():
    """IM2 阶数（斜率 2）+ 单节点退化=本级平移（双口径同值 spread=0）。"""
    r = _run("pim_cascade_budget", {"nodes": [{"level_dbm": -100.0}],
                                    "p_carrier_dbm": 45.0, "order": 2})
    assert r["shift_db"] == pytest.approx(4.0, abs=1e-12)
    assert r["p_incoherent_dbm"] == pytest.approx(-96.0, abs=1e-12)
    assert r["p_coherent_dbm"] == pytest.approx(-96.0, abs=1e-12)
    assert r["spread_db"] == pytest.approx(0.0, abs=1e-12)


def test_pim_budget_slope_override_and_names():
    """实测斜率覆盖：slope=2.5/ΔP=2 → 恰 +5.0dB；节点名透传。"""
    r = _run("pim_cascade_budget", {
        "nodes": [{"level_dbm": -110.0, "name": "joint_a"},
                  {"level_dbm": -112.0, "name": "connector_b"}],
        "p_carrier_dbm": 45.0, "slope_db_per_db": 2.5})
    assert r["shift_db"] == pytest.approx(5.0, abs=1e-12)
    assert [row["name"] for row in r["nodes"]] == ["joint_a", "connector_b"]


def test_pim_budget_limit_margin():
    """限值裕量恒等式 + 相干负裕量如实报告（不拒绝）。"""
    r = _run("pim_cascade_budget", {
        "nodes": [{"level_dbm": -110.0}, {"level_dbm": -110.0}],
        "p_carrier_dbm": 43.0, "pim_limit_dbm": -105.0})
    assert r["margin_incoherent_db"] == pytest.approx(
        -105.0 - r["p_incoherent_dbm"], abs=1e-12)
    assert r["margin_coherent_db"] == pytest.approx(
        -105.0 - r["p_coherent_dbm"], abs=1e-12)
    assert r["margin_coherent_db"] < 0.0  # 两等电平相干 +6.02 > 非相干 +3.01
    assert "超限" in r["note"]


def test_pim_budget_guards():
    """守卫族：order 域/类型、空节点、节点结构、斜率 ≤0、p_carrier 缺失。"""
    nodes = [{"level_dbm": -110.0}]
    _reject("pim_cascade_budget", {"nodes": nodes, "p_carrier_dbm": 43.0,
                                   "order": 1}, "order")
    _reject("pim_cascade_budget", {"nodes": nodes, "p_carrier_dbm": 43.0,
                                   "order": 2.5}, "整数")
    _reject("pim_cascade_budget", {"nodes": [], "p_carrier_dbm": 43.0}, "非空")
    _reject("pim_cascade_budget", {"nodes": "x", "p_carrier_dbm": 43.0},
            "list")
    _reject("pim_cascade_budget", {"nodes": [{"name": "a"}],
                                   "p_carrier_dbm": 43.0}, "level_dbm")
    _reject("pim_cascade_budget", {"nodes": [-110.0],
                                   "p_carrier_dbm": 43.0}, "dict")
    _reject("pim_cascade_budget", {"nodes": nodes, "p_carrier_dbm": 43.0,
                                   "slope_db_per_db": 0.0}, ">0")
    _reject("pim_cascade_budget", {"nodes": nodes, "p_carrier_dbm": 43.0,
                                   "slope_db_per_db": -2.0}, ">0")
    _reject("pim_cascade_budget", {"nodes": nodes}, "缺少必需参数")
    _reject("pim_cascade_budget", {"nodes": nodes, "p_carrier_dbm": 43.0,
                                   "pim_limit_dbm": "x"}, "float")


# ─── 注册面元数据：中文名形态 / group / 描述参数自洽 ─────────────────────────


_A4B_KEYS = ("rcs_sphere_mie", "rcs_peak_canonical",
             "diode_square_law_detect", "detector_tss_nep",
             "pim_nodes_combine", "pim_cascade_budget")


def test_a4b_registry_meta_shape():
    """中文名形态（冒号前首段含 CJK 且 ≤24 字）+ group 归组断言。"""
    import re

    has_cjk = re.compile(r"[\u4e00-\u9fff]")
    by_name = {r["name"]: r
               for r in CALCULATOR_REGISTRY.describe(include_experimental=True)}
    for key in _A4B_KEYS:
        assert key in by_name, f"{key} 未注册"
        row = by_name[key]
        prefix = row["description"].split("：", 1)[0]
        assert has_cjk.search(prefix), f"{key} 中文名缺 CJK: {prefix!r}"
        assert len(prefix) <= 24, f"{key} 中文名超长: {prefix!r}"
        assert row["params"], f"{key} 参数面为空"
    assert by_name["rcs_sphere_mie"]["group"] == "雷达"
    assert by_name["rcs_peak_canonical"]["group"] == "雷达"
    assert by_name["diode_square_law_detect"]["group"] == "测量与校准"
    assert by_name["detector_tss_nep"]["group"] == "测量与校准"
    assert by_name["pim_nodes_combine"]["group"] == "收发链路·频综"
    assert by_name["pim_cascade_budget"]["group"] == "收发链路·频综"
