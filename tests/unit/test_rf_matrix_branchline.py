"""rf_matrix 理想分支线耦合器闭式锚树（Q-X83，aurora_q）。

被测：core/calc_families/rf_matrix.branchline_ideal_sparams（理想 TL 半
电路 ABCD 级联 4×4 逐频点闭式）+ branchline_arm_impedances /
branchline_arm_media / branchline_ideal_design。

裁判口径（#118 家法：裁判=独立来源解析值，非同义反复）：
- 教科书理想值锚：f0 处 3dB 等分 |S21|=|S31|=1/√2（−3.0103dB 功率等分）、
  S21=−90°/S31=180° 相位、S11=S41=0（Pozar §7.5 经典口径）；
- 双路径互证锚：vs aurora_l G1 branchline_coupler_design._branchline_s
  （奇偶模**节点导纳矩阵**解析合成）——与本模块奇偶**半电路 ABCD 级联**
  两条独立推导路径逐元素互证（构造级独立，≤1e-10）；
- 一般耦合回收锚：设计闭式 Z1=c·Z0、Z2=Z0·c/√(1−c²) 正向进半电路级联 →
  f0 处回收 |S21|=c、|S31|=√(1−c²)（设计方程 ↔ 正向物理闭环）；
- 幺正性/互易性构造恒等式（无耗 TEM 级联由构造保证，机器精度钉）；
- em_bench campaign 判据链预告值（Q-X55 as-recorded FAIL 迁移面：
  s21_db_at_dip/s11_db_min_in_band/closedform_match dev）。

物理口径声明（如实）：±10% 偏离处定向性 ~11.8dB（任务书预估 >20dB 与
理想 branchline 窄带物理不符——实测 20dB 定向性带宽 ~±4%，按 #122 不凑
绿：钉实测值并声明）；er 只进 λ/4 臂长（θ(f)=π/2·f/f0 恒等式钉——电响
应与介质无关是理想 TEM 口径的直接推论）。

零湖写入（#144 纪律）：纯函数断言，零 IO。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.calc_families.branchline_coupler import _branchline_s
from rfauto.core.rf_matrix import (
    branchline_arm_impedances,
    branchline_arm_media,
    branchline_ideal_design,
    branchline_ideal_sparams,
)

Z0 = 50.0
F0 = 2.4
ER = 3.66
H_MM = 0.508
IDEAL_3DB_DB = 10.0 * math.log10(0.5)  # −3.0102999566398...


def _s_single(freq: float = F0, **kw) -> np.ndarray:
    return branchline_ideal_sparams(np.array([freq]), z0_ohm=Z0, f0_ghz=F0,
                                    er=ER, h_mm=H_MM, **kw)[0]


def _s_band(n: int = 41) -> np.ndarray:
    """全带 (n,4,4) 频扫（对称性逐位核对用）。"""
    return branchline_ideal_sparams(
        np.linspace(0.7 * F0, 1.3 * F0, n), z0_ohm=Z0, f0_ghz=F0,
        er=ER, h_mm=H_MM)


# ─── ① 中心频率教科书理想值（3dB）───────────────────────────────────────────

def test_f0_power_split_exact_amplitude():
    """|S21|=|S31|=1/√2（3dB 功率等分，幅度 0.7071=−3.0103dB 口径）。"""
    s = _s_single()
    assert abs(s[1, 0]) == pytest.approx(1.0 / math.sqrt(2.0), abs=1e-12)
    assert abs(s[2, 0]) == pytest.approx(1.0 / math.sqrt(2.0), abs=1e-12)


def test_f0_power_split_exact_db():
    """dB 口径：20·log10(0.7071)=−3.0103dB（等分偏差=机器精度级）。"""
    s = _s_single()
    s21_db = 20.0 * math.log10(abs(s[1, 0]))
    s31_db = 20.0 * math.log10(abs(s[2, 0]))
    assert s21_db == pytest.approx(IDEAL_3DB_DB, abs=1e-10)
    assert s31_db == pytest.approx(IDEAL_3DB_DB, abs=1e-10)


def test_f0_isolation_machine_zero():
    """S11=S41≈0（<1e-12 机器精度级，偶奇匹配由构造保证）。"""
    s = _s_single()
    assert abs(s[0, 0]) < 1e-12
    assert abs(s[3, 0]) < 1e-12


def test_f0_phase_through_minus90():
    """S21 相位 =−90°（直通滞后 λ/4；1e-9 级）。"""
    s = _s_single()
    ph = math.degrees(math.atan2(s[1, 0].imag, s[1, 0].real))
    assert ph == pytest.approx(-90.0, abs=1e-9)


def test_f0_phase_coupled_180():
    """S31 相位 =180°（耦合臂 λ/2 路径；1e-9 级）。"""
    s = _s_single()
    ph = math.degrees(math.atan2(s[2, 0].imag, s[2, 0].real))
    assert abs(ph) == pytest.approx(180.0, abs=1e-9)


def test_f0_energy_conservation_through_coupled():
    """中心频率能量守恒：|S21|²+|S31|²=1（无耗等分，残差 ≤1e-12）。"""
    s = _s_single()
    resid = abs(abs(s[1, 0]) ** 2 + abs(s[2, 0]) ** 2 - 1.0)
    assert resid <= 1e-12


def test_f0_energy_conservation_all_rows():
    """全行能量守恒（每端口 |Sij|² 行和=1，残差 ≤1e-12）。"""
    s = _s_single()
    row_pow = np.sum(np.abs(s) ** 2, axis=1)
    assert np.allclose(row_pow, 1.0, atol=1e-12)


def test_f0_unitarity_full_matrix():
    """幺正性 S·S†=I（无耗充要判据，最大偏差 ≤1e-12）。"""
    s = _s_single()
    dev = np.max(np.abs(s @ s.conj().T - np.eye(4)))
    assert dev <= 1e-12


def test_f0_reciprocity_exact():
    """互易性 S=Sᵀ（逐位，TL 级联构造保证）。"""
    s = _s_single()
    assert np.array_equal(s, s.T)


# ─── ② 双路径互证锚（vs aurora_l G1 节点导纳矩阵合成）──────────────────────

@pytest.mark.parametrize("c_v", [None, 0.3, 0.5, 0.9])
def test_cross_check_g1_independent_derivation(c_v):
    """两条独立推导逐元素互证：半电路 ABCD 级联 vs G1 节点导纳矩阵合成
    （≤1e-10；含 3dB 与一般耦合 c∈{0.3,0.5,0.9}）。"""
    z1, z2 = branchline_arm_impedances(Z0, c_v)
    s_mine = _s_single(coupling_c=c_v)
    s_ref = np.array(_branchline_s(z1, z2, Z0))
    dev = np.max(np.abs(s_mine - s_ref))
    assert dev <= 1e-10


def test_cross_check_g1_structure_pattern():
    """3dB 元素位形逐位核对：零位（对角+1-4 隔离对）/−j 位（直通对）/
    −1 位（耦合对）——与 G1 结构模式同构。"""
    s = _s_single()
    zero_idx = [(0, 0), (1, 1), (2, 2), (3, 3), (0, 3), (3, 0), (1, 2), (2, 1)]
    for i, j in zero_idx:
        assert abs(s[i, j]) < 1e-12, f"S{i+1}{j+1} 应为零位"
    for i, j in [(0, 1), (1, 0), (2, 3), (3, 2)]:
        assert s[i, j] == pytest.approx(-1j / math.sqrt(2.0), abs=1e-12)
    for i, j in [(0, 2), (2, 0), (1, 3), (3, 1)]:
        assert s[i, j] == pytest.approx(-1.0 / math.sqrt(2.0), abs=1e-12)


# ─── ③ 结构对称性 ───────────────────────────────────────────────────────────

def test_symmetry_diagonal_equal():
    """四端口镜像对称：Sii 全等（结构对称的直接推论）。"""
    s = _s_band()
    for k in range(s.shape[0]):
        assert np.array_equal(s[k, 0, 0], s[k, 1, 1])
        assert np.array_equal(s[k, 1, 1], s[k, 2, 2])
        assert np.array_equal(s[k, 2, 2], s[k, 3, 3])


def test_symmetry_through_pair_equal():
    """直通对位形：S21=S12=S34=S43（逐位全带）。"""
    s = _s_band()
    for k in range(s.shape[0]):
        assert np.array_equal(s[k, 0, 1], s[k, 1, 0])
        assert np.array_equal(s[k, 1, 0], s[k, 2, 3])
        assert np.array_equal(s[k, 2, 3], s[k, 3, 2])


def test_symmetry_coupled_pair_equal():
    """耦合对位形：S31=S13=S24=S42（逐位全带）。"""
    s = _s_band()
    for k in range(s.shape[0]):
        assert np.array_equal(s[k, 0, 2], s[k, 2, 0])
        assert np.array_equal(s[k, 2, 0], s[k, 1, 3])
        assert np.array_equal(s[k, 1, 3], s[k, 3, 1])


def test_symmetry_isolated_pair_equal():
    """隔离对位形：S41=S14=S32=S23（逐位全带）。"""
    s = _s_band()
    for k in range(s.shape[0]):
        assert np.array_equal(s[k, 0, 3], s[k, 3, 0])
        assert np.array_equal(s[k, 3, 0], s[k, 1, 2])
        assert np.array_equal(s[k, 1, 2], s[k, 2, 1])


# ─── ④ 频扫形状（0.7–1.3 f0，401 点）───────────────────────────────────────

def _band_s() -> np.ndarray:
    return branchline_ideal_sparams(
        np.linspace(0.7 * F0, 1.3 * F0, 401), z0_ohm=Z0, f0_ghz=F0,
        er=ER, h_mm=H_MM)


def test_band_unitarity_all_points():
    """全带 401 点逐点幺正（≤1e-12）——TL 级联无耗由构造保证。"""
    s = _band_s()
    for k in range(s.shape[0]):
        dev = np.max(np.abs(s[k] @ s[k].conj().T - np.eye(4)))
        assert dev <= 1e-12, f"频点 {k} 幺正超差 {dev:.3e}"


def test_band_reciprocity_all_points():
    """全带互易逐位（S=Sᵀ）。"""
    s = _band_s()
    assert np.array_equal(s, np.transpose(s, (0, 2, 1)))


def test_band_smoothness_no_jumps():
    """响应平滑过渡：|S21| dB 逐相邻步进 ≤0.05dB（0.7–1.3f0 401 点）。"""
    s = _band_s()
    s21_db = 20.0 * np.log10(np.abs(s[:, 1, 0]))
    assert float(np.max(np.abs(np.diff(s21_db)))) <= 0.05


def test_band_all_finite():
    """全带全元素有限（无 inf/nan——f→0 奇异面在守卫外）。"""
    s = _band_s()
    assert np.all(np.isfinite(s.view(float)))


def test_s11_min_at_f0():
    """|S11| 全带谷位在设计频率 f0（argmin 复核）。"""
    f = np.linspace(0.7 * F0, 1.3 * F0, 401)
    s = branchline_ideal_sparams(f, z0_ohm=Z0, f0_ghz=F0, er=ER, h_mm=H_MM)
    s11_db = 20.0 * np.log10(np.abs(s[:, 0, 0]) + 1e-30)
    assert f[int(np.argmin(s11_db))] == F0


def test_off_center_symmetric_response():
    """f0±δ 响应幅度对称（理想 TEM 对 f/f0 镜像；相位共轭翻转——幅度
    逐元素近似相等 1e-12）。"""
    f = [F0 * 0.9, F0 * 1.1]
    s = branchline_ideal_sparams(np.array(f), z0_ohm=Z0, f0_ghz=F0,
                                 er=ER, h_mm=H_MM)
    assert np.allclose(np.abs(s[0]), np.abs(s[1]), atol=1e-12)


def test_directivity_inside_band_2p5pct():
    """±2.5% 偏离定向性 >20dB（实测 23.50dB——理想 branchline 20dB 带）。"""
    for frac in (0.975, 1.025):
        s = _s_single(F0 * frac)
        directivity_db = 20.0 * math.log10(abs(s[2, 0]) / abs(s[3, 0]))
        assert directivity_db > 20.0


def test_directivity_10pct_as_recorded_physics():
    """±10% 偏离实测定向性 ~11.8dB（任务书预估 >20dB 与理想 branchline
    窄带物理不符——#122 如实钉实测值不凑绿；20dB 定向性带宽 ~±4%）。"""
    s = _s_single(F0 * 1.1)
    directivity_db = 20.0 * math.log10(abs(s[2, 0]) / abs(s[3, 0]))
    assert directivity_db == pytest.approx(11.81, abs=0.05)
    s_lo = _s_single(F0 * 0.9)
    assert 20.0 * math.log10(abs(s_lo[2, 0]) / abs(s_lo[3, 0])) \
        == pytest.approx(11.81, abs=0.05)


def test_off_center_split_db_smooth():
    """±10% 处等分平滑退化：|S21|≈−3.63dB（实测钉；无跳变无谷散）。"""
    s = _s_single(F0 * 1.1)
    s21_db = 20.0 * math.log10(abs(s[1, 0]))
    assert s21_db == pytest.approx(-3.626, abs=0.01)


def test_band_edge_return_loss_bound():
    """带缘（±30%）回损有界（|S11|≤0.51——失谐反射有界非发散；
    实测 max 0.50642 @0.7f0，钉实测值+1e-3 余量）。"""
    s = _band_s()
    assert float(np.max(np.abs(s[:, 0, 0]))) <= 0.51


# ─── ⑤ 一般耦合设计闭式 ↔ 正向回收（#340 合成回收家法）────────────────────

@pytest.mark.parametrize("c_v", [0.3, 0.5, 0.9])
def test_general_c_forward_recover(c_v):
    """设计闭式正向进半电路 → f0 回收 |S21|=c、|S31|=√(1−c²)、隔离
    机器零（设计方程↔正向物理闭环，非回代自洽）。"""
    s = _s_single(coupling_c=c_v)
    assert abs(s[1, 0]) == pytest.approx(c_v, abs=1e-12)
    assert abs(s[2, 0]) == pytest.approx(math.sqrt(1.0 - c_v * c_v),
                                         abs=1e-12)
    assert abs(s[0, 0]) < 1e-12
    assert abs(s[3, 0]) < 1e-12


@pytest.mark.parametrize("c_v", [0.3, 0.5, 0.9])
def test_general_c_phase_relation(c_v):
    """一般耦合相位不变量：直通 −90°/耦合 180°（拓扑 λ/4 结构决定）。"""
    s = _s_single(coupling_c=c_v)
    ph21 = math.degrees(math.atan2(s[1, 0].imag, s[1, 0].real))
    ph31 = math.degrees(math.atan2(s[2, 0].imag, s[2, 0].real))
    assert ph21 == pytest.approx(-90.0, abs=1e-9)
    assert abs(ph31) == pytest.approx(180.0, abs=1e-9)


@pytest.mark.parametrize("c_v,exp_z1,exp_z2", [
    (None, Z0 / math.sqrt(2.0), Z0),
    (0.5, 25.0, Z0 * 0.5 / math.sqrt(0.75)),
    (0.3, 15.0, Z0 * 0.3 / math.sqrt(0.91)),
    (0.9, 45.0, Z0 * 0.9 / math.sqrt(0.19)),
])
def test_arm_impedances_design_closed_form(c_v, exp_z1, exp_z2):
    """臂阻抗设计闭式表驱动：Z1=c·Z0、Z2=Z0·c/√(1−c²)（3dB=35.355/50
    教科书经典值）。"""
    z1, z2 = branchline_arm_impedances(Z0, c_v)
    assert z1 == pytest.approx(exp_z1, rel=1e-12)
    assert z2 == pytest.approx(exp_z2, rel=1e-12)


def test_arm_impedances_3db_matches_synthesize_branchline():
    """3dB 臂阻抗与模板级综合 synthesize_branchline 同值互证（35.35/50）。"""
    from rfauto.core.synthesis import synthesize_branchline
    res = synthesize_branchline(f0_ghz=F0, z0_ohm=Z0)
    z1, z2 = branchline_arm_impedances(Z0, None)
    assert z1 == pytest.approx(float(res.params["series_w_mm"]) * 0 + Z0
                               / math.sqrt(2.0), rel=1e-9)
    # 模板综合的臂阻抗不直接出数——以综合线宽回代正向阻抗互证（HJ 链）
    from rfauto.core.synthesis import Stackup, forward_z0
    stackup = Stackup(name="xref", epsilon_r=ER, thickness_mm=H_MM)
    z_ser, _ = forward_z0(float(res.params["series_w_mm"]), F0, stackup)
    z_sh, _ = forward_z0(float(res.params["shunt_w_mm"]), F0, stackup)
    assert z_ser == pytest.approx(z1, rel=2e-3)
    assert z_sh == pytest.approx(z2, rel=2e-3)


@pytest.mark.parametrize("bad_c", [0.0, 1.0, 1.5, -0.2, True, False])
def test_arm_impedances_guard_coupling(bad_c):
    """coupling_c 守卫：越开区间/bool 显式拒收（fail-closed）。"""
    with pytest.raises(ValueError):
        branchline_arm_impedances(Z0, bad_c)


@pytest.mark.parametrize("bad_z0", [0.0, -5.0, True, float("nan"),
                                    float("inf")])
def test_arm_impedances_guard_z0(bad_z0):
    """z0 守卫：非正/bool/非有限拒收。"""
    with pytest.raises(ValueError):
        branchline_arm_impedances(bad_z0, None)


# ─── ⑥ 臂介质解析（XA-3 各臂 εeff 口径）───────────────────────────────────

def test_arm_media_physical_windows():
    """两臂线宽/εeff/臂长物理窗：1≤εeff≤er、w>0、L>0。"""
    m = branchline_arm_media(Z0 / math.sqrt(2.0), Z0, F0, ER, H_MM)
    for tag in ("series", "shunt"):
        assert m[f"{tag}_w_mm"] > 0.0
        assert 1.0 <= m[f"{tag}_er_eff"] <= ER
        assert m[f"{tag}_len_mm"] > 0.0


def test_arm_media_length_formula_exact():
    """λ/4 反解式逐位：L=c/(4·f0·√εeff)（mm·GHz 光速单源）。"""
    m = branchline_arm_media(Z0 / math.sqrt(2.0), Z0, F0, ER, H_MM)
    assert m["series_len_mm"] == pytest.approx(
        299.792458 / (4.0 * F0 * math.sqrt(m["series_er_eff"])), rel=1e-12)
    assert m["shunt_len_mm"] == pytest.approx(
        299.792458 / (4.0 * F0 * math.sqrt(m["shunt_er_eff"])), rel=1e-12)


def test_arm_media_series_shorter_than_shunt():
    """串联臂（35Ω 宽线）εeff 高 → λ/4 物理长更短（XA-3 迭代序语义）。"""
    m = branchline_arm_media(Z0 / math.sqrt(2.0), Z0, F0, ER, H_MM)
    assert m["series_er_eff"] > m["shunt_er_eff"]
    assert m["series_len_mm"] < m["shunt_len_mm"]


def test_arm_media_bracket_fail_closed():
    """臂阻抗反解越括号（400Ω 超出 w∈[0.05,20]mm 可达面）显式报错。"""
    with pytest.raises(ValueError, match="越括号"):
        branchline_arm_media(Z0 / math.sqrt(2.0), 400.0, F0, ER, H_MM)


@pytest.mark.parametrize("kw", [dict(er=0.5), dict(h_mm=0.0),
                                dict(h_mm=-1.0), dict(series_z_ohm=0.0),
                                dict(shunt_z_ohm=-40.0)])
def test_arm_media_guard_fail_closed(kw):
    """media 守卫：er<1/厚度非正/臂阻抗非正 fail-closed。"""
    base = dict(series_z_ohm=Z0 / math.sqrt(2.0), shunt_z_ohm=Z0,
                f0_ghz=F0, er=ER, h_mm=H_MM)
    with pytest.raises(ValueError):
        branchline_arm_media(**{**base, **kw})


# ─── ⑦ 电长度恒等式与介质不变性 ────────────────────────────────────────────

@pytest.mark.parametrize("er_v", [2.2, 3.66, 10.2])
def test_er_only_enters_arm_length(er_v):
    """er 扫描 f0 响应逐位不变（θ=2πf√εeff·L/c，L=c/(4f0√εeff) 反解 ⇒
    θ(f0)=90° 与介质无关——理想 TEM 口径直接推论）。"""
    s = branchline_ideal_sparams(np.array([F0]), z0_ohm=Z0, f0_ghz=F0,
                                 er=er_v, h_mm=H_MM)[0]
    s_ref = _s_single()
    assert np.allclose(s, s_ref, atol=1e-12)


def test_design_theta_90_at_f0():
    """设计元数据电长复核：两臂 θ(f0)=90.0°（显式式回代）。"""
    d = branchline_ideal_design(z0_ohm=Z0, f0_ghz=F0, er=ER, h_mm=H_MM)
    assert d["series_theta_deg_at_f0"] == pytest.approx(90.0, abs=1e-9)
    assert d["shunt_theta_deg_at_f0"] == pytest.approx(90.0, abs=1e-9)


def test_design_metadata_keys_and_values():
    """元数据键闭集+设计值：Z1/Z2 教科书值、εeff 窗、长度正。"""
    d = branchline_ideal_design(z0_ohm=Z0, f0_ghz=F0, er=ER, h_mm=H_MM)
    assert d["series_z_ohm"] == pytest.approx(Z0 / math.sqrt(2.0), rel=1e-12)
    assert d["shunt_z_ohm"] == pytest.approx(Z0, rel=1e-12)
    assert 1.0 <= d["series_er_eff"] <= ER
    assert 1.0 <= d["shunt_er_eff"] <= ER
    assert d["series_w_mm"] > 0 and d["shunt_w_mm"] > 0
    assert "note" in d and "branchline_ideal_sparams" in d["note"]


# ─── ⑧ 接口形态/确定性/参考阻抗 ───────────────────────────────────────────

def test_output_shape_dtype_and_list_input():
    """标量/列表入参→(n,4,4) complex128；dtype 收敛。"""
    s1 = branchline_ideal_sparams(F0)
    assert s1.shape == (1, 4, 4) and s1.dtype == np.complex128
    s3 = branchline_ideal_sparams([F0 * 0.9, F0, F0 * 1.1])
    assert s3.shape == (3, 4, 4) and s3.dtype == np.complex128


def test_deterministic_bitwise():
    """确定性：同入参两次调用逐位一致（零随机零状态）。"""
    f = np.linspace(0.7 * F0, 1.3 * F0, 51)
    a = branchline_ideal_sparams(f)
    b = branchline_ideal_sparams(f)
    assert np.array_equal(a, b)


def test_unsorted_freq_preserved():
    """频点保序（乱序入参逐点独立评估，无排序假设）。"""
    f = np.array([F0 * 1.2, F0 * 0.8, F0])
    s = branchline_ideal_sparams(f)
    for k, fk in enumerate(f):
        s_ref = _s_single(float(fk))
        assert np.allclose(s[k], s_ref, atol=1e-14)


def test_z_ref_renormalization_unitary():
    """z_ref≠z0 伪波重归一仍幺正（60Ω：|S11|>0 但 S·S†=I ≤1e-12）。"""
    s = branchline_ideal_sparams(np.array([F0]), z0_ohm=Z0, f0_ghz=F0,
                                 er=ER, h_mm=H_MM, z_ref_ohm=60.0)[0]
    dev = np.max(np.abs(s @ s.conj().T - np.eye(4)))
    assert dev <= 1e-12
    assert abs(s[0, 0]) > 1e-3  # 重归一非匹配参考→可见反射
    assert abs(s[1, 0]) == pytest.approx(1 / math.sqrt(2.0), abs=5e-4)


def test_z_ref_default_bitwise_equals_explicit_z0():
    """z_ref 缺省=z0_ohm 逐位（显式传 50 与缺省逐位一致）。"""
    a = _s_single()
    b = branchline_ideal_sparams(np.array([F0]), z0_ohm=Z0, f0_ghz=F0,
                                 er=ER, h_mm=H_MM, z_ref_ohm=Z0)[0]
    assert np.array_equal(a, b)


def test_explicit_arm_overrides_change_response():
    """显式臂阻抗覆盖生效：Z1=40/Z2=55（失配对）与缺省响应可分辨。"""
    s_def = _s_single()
    s_ovr = _s_single(series_z_ohm=40.0, shunt_z_ohm=55.0)
    assert np.max(np.abs(s_ovr - s_def)) > 1e-3


def test_explicit_matched_pair_recovers_split():
    """显式覆盖=满足匹配条件 (1/Z1)²−(1/Z2)²=(1/Z0)² 的非缺省对
    （Z1=40 → c=0.8 → Z2=Z0·0.8/√(1−0.64)=66.667）→ f0 回收
    |S21|=0.8、|S31|=0.6、隔离机器零（匹配条件↔正向物理双证）。"""
    z1 = 40.0
    z2 = Z0 * 0.8 / math.sqrt(1.0 - 0.64)
    s = _s_single(series_z_ohm=z1, shunt_z_ohm=z2)
    assert abs(s[1, 0]) == pytest.approx(0.8, abs=1e-12)
    assert abs(s[2, 0]) == pytest.approx(0.6, abs=1e-12)
    assert abs(s[0, 0]) < 1e-12
    assert abs(s[3, 0]) < 1e-12


# ─── ⑨ 入参守卫 fail-closed（branchline_ideal_sparams）────────────────────

@pytest.mark.parametrize("bad_freq", [[], [0.0], [-1.0], [F0, float("nan")],
                                      [F0, float("inf")], "abc", None])
def test_guard_freq_fail_closed(bad_freq):
    """freq 守卫：空/零/负/非有限/非法形态显式拒收。"""
    with pytest.raises(ValueError):
        branchline_ideal_sparams(bad_freq)


@pytest.mark.parametrize("kw", [
    dict(z0_ohm=0.0), dict(z0_ohm=-50.0), dict(z0_ohm=True),
    dict(f0_ghz=0.0), dict(f0_ghz=True), dict(f0_ghz=float("nan")),
    dict(er=0.5), dict(er=True), dict(er=float("inf")),
    dict(h_mm=0.0), dict(h_mm=-0.5), dict(h_mm=True),
    dict(coupling_c=0.0), dict(coupling_c=1.0), dict(coupling_c=True),
    dict(coupling_c=-0.1),
    dict(z_ref_ohm=0.0), dict(z_ref_ohm=-3.0), dict(z_ref_ohm=True),
    dict(series_z_ohm=0.0), dict(series_z_ohm=-40.0), dict(series_z_ohm=True),
    dict(shunt_z_ohm=0.0), dict(shunt_z_ohm=True),
])
def test_guard_scalars_fail_closed(kw):
    """标量守卫表驱动：bool 拒收（df7+⑯）/非正/非有限全 fail-closed。"""
    with pytest.raises(ValueError):
        branchline_ideal_sparams(np.array([F0]), **kw)


def test_guard_arm_media_bracket_fail_closed():
    """显式并联臂 400Ω（微带综合可达面外）fail-closed 不静默钳位。"""
    with pytest.raises(ValueError, match="越括号"):
        branchline_ideal_sparams(np.array([F0]), shunt_z_ohm=400.0)


def test_er_boundary_low_accepted():
    """er=1.01（近空气极限）合法且等分理想（守卫域下界 1.0 附近；恰
    1.0 触 skrf 上游 loss-tangent 除零警告，测试取近界避门噪声）。"""
    s = branchline_ideal_sparams(np.array([F0]), er=1.01)
    assert abs(s[0, 1, 0]) == pytest.approx(1 / math.sqrt(2.0), abs=1e-12)


def test_er_below_one_rejected():
    """er=0.999（<1 守卫下界）拒收（fail-closed）。"""
    with pytest.raises(ValueError):
        branchline_ideal_sparams(np.array([F0]), er=0.999)


# ─── ⑩ em_bench campaign 判据链预告（Q-X55 迁移面）────────────────────────

def test_em_bench_judge_chain_preview_values():
    """em_bench 判据链预告值（新模型接线后 branchline-campaign 应达带）：
    s21_db_at_dip=−3.0103（closedform_match dev≈7.4e-16 ≤0.10 带）、
    s11_db_min_in_band≈−317dB（≤−15dB 杆）——与 level2_design
    evaluate_metrics 同式（20·log10(|S11|+1e-30) argmin / S21@dip）。"""
    f = np.linspace(0.7 * F0, 1.3 * F0, 401)
    s = branchline_ideal_sparams(f, z0_ohm=Z0, f0_ghz=F0, er=ER, h_mm=H_MM)
    s11_db = 20.0 * np.log10(np.abs(s[:, 0, 0]) + 1e-30)
    idx = int(np.argmin(s11_db))
    s21_db_at_dip = float(20.0 * np.log10(abs(s[idx, 1, 0]) + 1e-30))
    dev = abs(s21_db_at_dip - IDEAL_3DB_DB) / abs(IDEAL_3DB_DB)
    assert dev <= 1e-12                      # 预告：closedform_match pass
    assert dev == pytest.approx(7.376e-16, rel=0.1)  # 实测预告值
    assert float(s11_db[idx]) <= -300.0      # 预告：gate_pass S11 杆深过
    assert f[idx] == F0                      # 谷位=设计频率


def test_module_not_registered_and_no_all():
    """纯函数模块口径：无 __all__、CALC 注册表零新键（金快照/注册序零
    漂移的构造级保证）。"""
    import rfauto.core.rf_matrix as mod
    from rfauto.core.calc_families.registry import CALCULATOR_REGISTRY
    assert not hasattr(mod, "__all__")
    keys = set(CALCULATOR_REGISTRY._specs) \
        if hasattr(CALCULATOR_REGISTRY, "_specs") else set()
    assert "branchline_ideal_sparams" not in keys
    assert "branchline_ideal_design" not in keys
