"""石英晶体族内核单元测试（PK-3 锚树，规格深案 §A-3）。

锚树预声明（先写后跑，#122；规格 §A-3 锚）：
- A1 fL 公式恒等回收（合成逐位）：crystal_load_resonance 与测试内独立
  展开（同表达式序）**逐位相等**（==，三组参数）；规范例 10MHz/7fF/3.5pF/
  10pF 手算锚=级数展开独立来源（sqrt(1+x)=1+x/2−x²/8，截断误差 <1e-5 Hz）；
  恒 fL>fs；CL→∞ 极限（cl=1mF 时 fL−fs <1e-5 ppm）。
- A2 trim 灵敏度锚：规范例 ∈ (−12,−8) ppm/pF（规格「−10ppm/pF ±20%」
  自检锚；手算 −9.6022）；exact 档=近似/(1+x) 逐位式 + 中心差分（h=1fF）
  校核 rel ≤1e-6；近似档 fs 无关性逐位（docstring 口径）。
- A3 预算键：trim 项=fL 精确比逐位；温漂/老化线性恒等逐位；total 线性
  和逐位；trim 项 ≈ trim_sensitivity(exact=True)·d_cl（rel ≤1e-2，二阶
  ~0.4%）；符号语义 d_cl>0→trim<0。
- A4 负例守卫（守卫策略 declared=ValueError，不 warning 不夹持）：
  fL/trim 的 fs/c1/c0/cl≤0、budget 的 cl+dcl≤0 与 years<0、ladder 的
  n_crystals 0/2.5/True（bool 拒绝）/cc≤0/rm<0/rs≤0/f_grid 非法
  （负值/空/2-D）。
- A5 梯形最小形态通带：
  · N=1 无损 @fs：动态臂串联谐振=短路 → |S21(fs)|=1（≤1e-9，独立来源
    解析锚）、无损酉性 |S11|²+|S21|²=1（±1e-9）；
  · N=3 无损 @fs：晶体精确短路（δ=0 实测）→ 双 shunt 电容网络独立闭式
    （ABCD=[[1,0],[2yp,1]]、den=100+5000·yp）allclose ≤1e-12；fa_hz 元数据
    与 PK-1 bvd_resonances 逐位相等；
  · N=3 有损（Q≈5e4）：通带峰落 (fs,fa) 感性区间且 |f_peak/fs−1|≤2e-3
    （非平凡：栅格 ±5e-3）、峰对 0.995fs 与 1.5fs 双侧阻带 ≥40dB、
    无源 max|S|≤1+1e-9、q_series=1/(ωs·C1·Rm) 回收 rel ≤1e-9；
  · 等端接 rs=rl=50 时 _abcd_to_s_2port 与 baw_ladder._abcd_to_s
    （equal-z0 口径，×z0 标度相消）allclose ≤1e-12；
  · 栅格排序契约（乱序入参→f_hz 升序+矩阵对齐）+ skrf Touchstone
    写出读回 |S21| ≤1e-6 + 互易 S12=S21（≤1e-12）。
- A6 PK-1 对接与 Q 档表：crystal_impedance @fs |Z|≈Rm（rel ≤1e-4，C0
  并联加载闭式折算）、fs..fa 感性/fs 以下与 fa 以上容性（符号结构锚）、
  100·fs 高频极限→1/(jωC0)（rel ≤1e-4）；CRYSTAL_Q_TABLE 四档 0<lo<hi、note 含
  UNVERIFIED 标注、crystal_q0 geo=√(lo·hi)/lo/hi 三态、未知档 ValueError。

数值裁判纪律（#118）：A5 短路恒等/酉性/通带区间=独立来源解析值（电路
理论）；A2 有限差分=fL 闭式的独立数值裁判；A6 符号结构与极限=电路理论。
规范例数字（10MHz/7fF/3.5pF/10pF→−9.6ppm/pF）为规格钉定的自检锚。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import skrf

from rfauto.core.acoustic_resonator import bvd_resonances, mbvd_impedance
from rfauto.core.baw_ladder import _abcd_to_s
from rfauto.core.crystal import (
    CRYSTAL_Q_TABLE,
    crystal_freq_error_budget_ppm,
    crystal_impedance,
    crystal_ladder_filter,
    crystal_load_resonance,
    crystal_q0,
    trim_sensitivity_ppm_pf,
)

FS = 10.0e6  # 规范例：10 MHz AT 切量级
C1 = 7e-15  # 7 fF（规格锚）
C0 = 3.5e-12  # 3.5 pF（规格锚）
CL = 10e-12  # 10 pF（规格锚）
CC = 15e-12  # 梯形耦合电容
RM_Q50K = 1.0 / (2.0 * math.pi * FS * C1 * 5.0e4)  # Q=5e4 → 45.47 Ω


# ── A1 fL 恒等回收 ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fs,c1,c0,cl",
    [
        (10.0e6, 7e-15, 3.5e-12, 10e-12),
        (26.0e6, 5e-15, 2.0e-12, 12e-12),
        (32.768e3, 3.0e-15, 1.2e-12, 12.5e-12),
    ],
)
def test_load_resonance_bitwise_identity(fs, c1, c0, cl):
    """A1：与测试内独立展开（同表达式序）逐位相等。"""
    assert crystal_load_resonance(fs, c1, c0, cl) == fs * math.sqrt(
        1.0 + c1 / (2.0 * (c0 + cl)))


def test_load_resonance_canonical_hand_anchor():
    """A1：规范例级数展开独立来源 + fL>fs + CL→∞ 极限。"""
    f_l = crystal_load_resonance(FS, C1, C0, CL)
    x = C1 / (2.0 * 13.5e-12)
    expected = FS * (1.0 + x / 2.0 - x * x / 8.0)  # sqrt(1+x) 级数，截断 <1e-5 Hz
    assert abs(f_l - expected) < 0.01
    assert f_l > FS
    f_l_big_cl = crystal_load_resonance(FS, C1, C0, 1.0e-3)
    assert (f_l_big_cl - FS) / FS * 1e6 < 1e-5  # CL→∞ 时 fL→fs（<1e-5 ppm）


# ── A2 微调灵敏度 ───────────────────────────────────────────────────────────


def test_trim_sensitivity_spec_anchor():
    """A2：规格自检锚 −10ppm/pF ±20%；手算独立值 −9.6022。"""
    s = trim_sensitivity_ppm_pf(FS, C1, C0, CL)
    assert -12.0 < s < -8.0
    # 手算：−1e6·7e-15·1e-12/(4·(13.5e-12)²) = −7e-21/7.29e-22
    assert s == pytest.approx(-9.602194787379974, rel=1e-12)


def test_trim_exact_vs_finite_difference():
    """A2：exact 档=近似/(1+x) 逐位式 + 中心差分（h=1fF）校核 rel ≤1e-6。"""
    s_approx = trim_sensitivity_ppm_pf(FS, C1, C0, CL)
    s_exact = trim_sensitivity_ppm_pf(FS, C1, C0, CL, exact=True)
    x = C1 / (2.0 * (C0 + CL))
    assert s_exact == pytest.approx(s_approx / (1.0 + x), rel=1e-15)
    h = 1e-15
    fl_p = crystal_load_resonance(FS, C1, C0, CL + h)
    fl_m = crystal_load_resonance(FS, C1, C0, CL - h)
    fd_ppm_pf = (fl_p - fl_m) / (2.0 * h) * 1e-12 * 1e6 / fl_p
    assert fd_ppm_pf == pytest.approx(s_exact, rel=1e-6)


def test_trim_fs_independent_bitwise():
    """A2：相对灵敏度与 fs 无关（两个 fs 同值逐位，docstring 口径）。"""
    a = trim_sensitivity_ppm_pf(10.0e6, C1, C0, CL)
    b = trim_sensitivity_ppm_pf(26.0e6, C1, C0, CL)
    assert a == b


# ── A3 预算键 ───────────────────────────────────────────────────────────────


def test_budget_keys_consistency_and_sign():
    """A3：三分量逐位恒等 + trim 与灵敏度一致性（二阶 ~0.4%）+ 符号语义。"""
    tca, dt, aging, years, d_cl = -0.05, 20.0, 3.0, 5.0, 0.05
    b = crystal_freq_error_budget_ppm(
        FS, C1, C0, CL, d_cl_pf=d_cl, tca_ppm_k=tca, dt_k=dt,
        aging_ppm_per_year=aging, years=years)
    fl0 = crystal_load_resonance(FS, C1, C0, CL)
    fl1 = crystal_load_resonance(FS, C1, C0, CL + d_cl * 1e-12)
    assert b["trim_ppm"] == 1e6 * (fl1 / fl0 - 1.0)  # 逐位
    assert b["temp_ppm"] == tca * dt  # 逐位
    assert b["aging_ppm"] == aging * years  # 逐位
    assert b["total_ppm"] == b["trim_ppm"] + b["temp_ppm"] + b["aging_ppm"]  # 逐位
    assert b["f_l_hz"] == fl0
    assert b["trim_ppm"] == pytest.approx(
        trim_sensitivity_ppm_pf(FS, C1, C0, CL, exact=True) * d_cl, rel=1e-2)
    assert b["trim_ppm"] < 0.0  # 负载电容加大→fL 下移


def test_budget_zero_defaults_identity():
    """A3：全零扰动档 total=0、fL 溯源键在位。"""
    b = crystal_freq_error_budget_ppm(FS, C1, C0, CL)
    assert b["total_ppm"] == 0.0
    assert b["trim_ppm"] == 0.0
    assert b["f_l_hz"] == crystal_load_resonance(FS, C1, C0, CL)


# ── A4 负例守卫 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "args",
    [
        (0.0, C1, C0, CL),
        (-1.0, C1, C0, CL),
        (FS, 0.0, C0, CL),
        (FS, C1, 0.0, CL),
        (FS, C1, C0, 0.0),
        (FS, C1, C0, -1e-12),
    ],
)
def test_guards_load_resonance_and_trim(args):
    """A4：fL/trim 非正入参（含 cl≤0 规格负例）→ ValueError。"""
    with pytest.raises(ValueError):
        crystal_load_resonance(*args)
    with pytest.raises(ValueError):
        trim_sensitivity_ppm_pf(*args)


def test_guards_budget():
    """A4：cl+dcl≤0 与 years<0 → ValueError。"""
    with pytest.raises(ValueError):
        crystal_freq_error_budget_ppm(FS, C1, C0, CL, d_cl_pf=-1.0e6)
    with pytest.raises(ValueError):
        crystal_freq_error_budget_ppm(FS, C1, C0, CL, years=-1.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_crystals": 0},
        {"n_crystals": 2.5},
        {"n_crystals": True},  # bool 拒绝（baw_ladder 同口径）
        {"c_coupling_f": 0.0},
        {"c_coupling_f": -1e-12},
        {"rm_ohm": -1.0},
        {"rs_ohm": 0.0},
        {"rl_ohm": -50.0},
    ],
)
def test_guards_ladder_scalar_inputs(kwargs):
    """A4：梯形标量入参守卫。"""
    full = dict(n_crystals=3, fs_hz=FS, c1_f=C1, c0_f=C0, c_coupling_f=CC)
    full.update(kwargs)
    with pytest.raises(ValueError):
        crystal_ladder_filter(np.array([FS]), **full)


@pytest.mark.parametrize(
    "grid",
    [np.array([]), np.array([FS, -1.0]), np.array([[FS], [2.0 * FS]])],
)
def test_guards_ladder_grid(grid):
    """A4：f_grid 空/含负值/2-D → ValueError（baw._validated_grid 同契约）。"""
    with pytest.raises(ValueError):
        crystal_ladder_filter(grid, 3, FS, C1, C0, CC)


# ── A5 梯形最小形态通带 ─────────────────────────────────────────────────────


def test_ladder_single_crystal_short_identity_and_unitarity():
    """A5：N=1 无损 @fs 动态臂短路 → |S21|=1；无损酉性 ±1e-9。"""
    grid = np.array([FS * 0.999, FS, FS * 1.0005])
    ret = crystal_ladder_filter(grid, 1, FS, C1, C0, CC)
    i_fs = int(np.argmin(np.abs(grid - FS)))
    assert abs(ret["s"][i_fs, 1, 0]) == pytest.approx(1.0, abs=1e-9)
    p = np.abs(ret["s"][:, 0, 0]) ** 2 + np.abs(ret["s"][:, 1, 0]) ** 2
    assert np.allclose(p, 1.0, rtol=0, atol=1e-9)
    assert np.max(np.abs(ret["s"])) <= 1.0 + 1e-9


def test_ladder_three_crystal_fs_independent_formula():
    """A5：N=3 无损 @fs=双 shunt 电容网络独立闭式（晶体=短路），≤1e-8。"""
    grid = np.sort(np.array([2.0 * FS, FS, 0.5 * FS]))
    ret = crystal_ladder_filter(grid, 3, FS, C1, C0, CC)
    assert np.array_equal(ret["f_hz"], grid)  # 排序栅格返回口径
    i_fs = int(np.argmin(np.abs(grid - FS)))
    # 独立闭式：无损晶体 @fs 精确短路（δ=0，实测）→ ABCD=(Sh@Sh)=[[1,0],[2yp,1]]，
    # den=A·rl+B+C·rs·rl+D·rs=100+5000·yp（草稿批教训：对角是 1 不是 1−y²——
    # 串臂 Z=0 时无 (1+Zy) 项，漏/多项即 4.7%/8.8e-7 级假差）
    y = 1j * 2.0 * math.pi * FS * CC
    den = 1.0 * 50.0 + 0.0 + (2.0 * y) * 50.0 * 50.0 + 1.0 * 50.0
    s21_indep = 2.0 * math.sqrt(50.0 * 50.0) / den
    assert ret["s"][i_fs, 1, 0] == pytest.approx(s21_indep, rel=1e-12, abs=1e-12)
    # fa_hz 元数据与 PK-1 bvd_resonances 逐位相等（同表达式序）
    lm = 1.0 / (2.0 * math.pi * FS) ** 2 / C1
    reso = bvd_resonances(lm, C1, C0)
    assert ret["fs_hz"] == reso["fs_hz"]
    assert ret["fa_hz"] == reso["fa_hz"]
    assert ret["lm_h"] == lm


def test_ladder_passband_structure_lossy():
    """A5：N=3 有损——峰落 (fs,fa) 感性区间、双侧阻带 ≥40dB、无源、Q 回收。"""
    grid = np.sort(np.concatenate([
        FS * (1.0 + np.linspace(-5.0e-3, 5.0e-3, 4001)),
        [FS * 0.9949, FS * 1.5],  # 阻带探针（避开栅格端点重复，防 skrf 非单调告警）
    ]))
    ret = crystal_ladder_filter(grid, 3, FS, C1, C0, CC, rm_ohm=RM_Q50K)
    s21_db = 20.0 * np.log10(np.abs(ret["s"][:, 1, 0]))
    i_pk = int(np.argmax(s21_db))
    f_pk = ret["f_hz"][i_pk]
    # 峰落晶体感性区间 (fs, fa)，且 ±5e-3 栅格内非平凡
    assert FS < f_pk < ret["fa_hz"]
    assert abs(f_pk / FS - 1.0) <= 2.0e-3
    i_lo = int(np.argmin(np.abs(grid - FS * 0.9949)))
    i_hi = int(np.argmin(np.abs(grid - FS * 1.5)))
    assert s21_db[i_pk] - s21_db[i_lo] >= 40.0
    assert s21_db[i_pk] - s21_db[i_hi] >= 40.0
    # 无源（有损网 max|S|≤1+1e-9）与 Q 回收
    assert np.max(np.abs(ret["s"])) <= 1.0 + 1e-9
    assert ret["q_series"] == pytest.approx(5.0e4, rel=1e-9)


def test_ladder_matches_baw_abcd_to_s_equal_termination():
    """A5：等端接 rs=rl 时广义转换式与 baw_ladder._abcd_to_s 对拍 ≤1e-12。"""
    grid = np.array([FS * 0.999, FS * 1.0005, 2.0 * FS])  # 离极点良态采样
    ret = crystal_ladder_filter(grid, 2, FS, C1, C0, CC, rm_ohm=RM_Q50K)
    s_baw = _abcd_to_s(ret["abcd"], 50.0)
    assert np.allclose(ret["s"], s_baw, rtol=1e-12, atol=1e-14)


def test_ladder_sorted_grid_reciprocity_touchstone(tmp_path):
    """A5：乱序栅格排序契约 + 互易 S12=S21 + skrf Touchstone 往返。"""
    grid = np.array([FS * 2.0, FS * 0.9999, FS * 1.0002])
    ret = crystal_ladder_filter(grid, 3, FS, C1, C0, CC, rm_ohm=RM_Q50K)
    assert np.array_equal(ret["f_hz"], np.sort(grid))
    assert np.allclose(ret["s"][:, 0, 1], ret["s"][:, 1, 0], rtol=0, atol=1e-12)
    assert np.array_equal(ret["network"].s, ret["s"])
    path = tmp_path / "pk3_ladder.s2p"
    ret["network"].write_touchstone(str(path))
    back = skrf.Network(str(path))
    assert np.allclose(back.f, ret["f_hz"], rtol=1e-12)
    assert np.allclose(back.s, ret["s"], rtol=0, atol=1e-6)


# ── A6 PK-1 对接与 Q 档表 ───────────────────────────────────────────────────


def test_crystal_impedance_sign_structure_and_limits():
    """A6：Z(fs)≈Rm、fs..fa 感性/两侧容性符号锚、高频极限→1/(jωC0)。"""
    z_fs = crystal_impedance(FS, FS, C1, C0, RM_Q50K)
    # C0 并联加载：Z(fs)=Rm∥(1/jωC0)，|Z|=Rm/√(1+(Rm/Rc)²)（Rc=4547Ω→
    # 偏低 ~5e-5 rel、虚部容性微载 −0.46Ω）——量级锚 rel 1e-4，非逐位
    assert abs(z_fs) == pytest.approx(RM_Q50K, rel=1e-4)
    assert z_fs.real > 0.0 and z_fs.imag < 0.0
    fa = FS * math.sqrt(1.0 + C1 / C0)
    assert crystal_impedance(0.999 * FS, FS, C1, C0, RM_Q50K).imag < 0.0
    assert crystal_impedance(1.0005 * FS, FS, C1, C0, RM_Q50K).imag > 0.0
    assert crystal_impedance(1.002 * FS, FS, C1, C0, RM_Q50K).imag < 0.0
    assert 1.0005 * FS < fa < 1.002 * FS  # 符号结构区间确在 (fs, fa) 内
    f_hi = 100.0 * FS
    z_hi = crystal_impedance(f_hi, FS, C1, C0, RM_Q50K)
    z_c0 = 1.0 / (1j * 2.0 * math.pi * f_hi * C0)
    assert abs(z_hi - z_c0) <= 1e-4 * abs(z_c0)
    # 无损档 @fs 精确短路（rm=0）
    assert abs(crystal_impedance(FS, FS, C1, C0, 0.0)) <= 1e-6


def test_crystal_impedance_matches_mbvd_direct():
    """A6：封装面与 mbvd_impedance 直调（同 lm 闭式）逐位相等。"""
    lm = 1.0 / (2.0 * math.pi * FS) ** 2 / C1
    f = np.array([FS * 0.999, FS * 1.0005])
    z_wrap = crystal_impedance(f, FS, C1, C0, RM_Q50K)
    z_direct = mbvd_impedance(f, C0, 0.0, lm, C1, RM_Q50K, 0.0)
    assert np.array_equal(np.asarray(z_wrap, dtype=complex), z_direct)


def test_q_table_bands_and_lookup():
    """A6：四档 0<lo<hi、UNVERIFIED 标注在位、geo/lo/hi 三态取值。"""
    assert set(CRYSTAL_Q_TABLE) == {
        "tuning_fork", "at_cut_fundamental", "at_cut_overtone", "sc_cut"}
    for grade, entry in CRYSTAL_Q_TABLE.items():
        lo, hi = entry["q0_typ_band"]
        assert 0.0 < lo < hi
        assert "UNVERIFIED" in entry["note"]  # 规格 §A-3「UNVERIFIED 标注」
        assert crystal_q0(grade) == math.sqrt(lo * hi)
        assert crystal_q0(grade, stat="lo") == lo
        assert crystal_q0(grade, stat="hi") == hi
        assert lo <= crystal_q0(grade) <= hi


def test_q0_unknown_grade_and_stat_raise():
    """A6：未知档名/非法 stat → ValueError。"""
    with pytest.raises(ValueError):
        crystal_q0("nope")
    with pytest.raises(ValueError):
        crystal_q0("sc_cut", stat="median")
