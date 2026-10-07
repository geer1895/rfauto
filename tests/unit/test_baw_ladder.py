"""BAW 梯形/格型滤波器综合单元测试（PK-2 锚树，规格深案 §A-2）。

锚树预声明（先写后跑，#122；规格 §A-2 锚）：
- A1 1 节单元透射峰与零深（无损档）：S21@fs_series=0dB（|S21|−1 ≤1e-9，
  n=1 与 n=3 同点成立——fs_s 处每节为恒等阵的电路事实）；串臂反谐振
  fa_s 与并臂串联谐振 fs_p 两侧零深 ≥40dB（ε=1e-9 相对偏置采样，期望
  −145dB 量级）。
- A2 级联一致性：n_sections=3 的 ABCD 与 3 节矩阵乘积（同序左累积）
  **逐位相等**（np.array_equal）。
- A3 带缘语义（带通形态）：fs_shunt（低侧零）< fs_series < fa_series
  （高侧零）；带内 |S21| 峰 ≈1（@fs_s）、带缘外侧 ε=1e-4 处 ≤−30dB；
  无损档酉性 |S11|²+|S21|²=1（±1e-9）、max|S|≤1+1e-9、S12=S21（互易）。
- A4 相对带宽上限守卫：请求带宽超 keff²·√(1+c) 上限（r<1/(1+c)）→
  ValueError；r≥1（带阻退化）→ValueError；边界 r=1/(1+c)·(1+1e-9) 放行
  （守卫策略=ValueError，模块 docstring 已声明，不 warning 不夹持）。
- A5 skrf Network 往返：network.s 与返回 s **逐位相等**；手算 S（教科书
  转换式、同表达式序）与返回 s **逐位相等**，代数重排独立式 allclose
  ≤1e-9；Touchstone 写出→读回 |S21| 一致（≤1e-6）。
- A6 PK-1 谐振语义对接：合成 (Lm,Cm,C0) 过 bvd_resonances 回收 fs/fa
  （rtol 1e-12）；mbvd_impedance（无损档）与 baw_arm_impedance 独立实现
  对拍 rtol 1e-9（离极点 ≥1e-3 相对偏置采样，#118 双链裁判）。
- A7 格型变体：S21@fs_s≈1（≤1e-9，ulp 级 docstring 已注）、带内 Zi 实值、
  max|S|≤1+1e-9、远带（10·fs_s）零深 ≥40dB（Za/Zb→1 平衡归零）。
- A8 原语复用同构：_abcd_shunt 逐字 import 路径 + 串臂本地原语与
  metasurface_lut 原语级联结果 allclose ≤1e-12。

数值裁判纪律（#118）：A1/A3/A7 锚=独立来源解析值（电路理论：fs_s 处串臂
短路+并臂开路→恒等；无损→酉性）；A6=两独立实现互证。所有断言在无损档
（rm=r0=l0=0）。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import skrf

from rfauto.core.acoustic_resonator import bvd_resonances, keff2, mbvd_impedance
from rfauto.core.baw_ladder import (
    _DEFAULT_CM_C0_RATIO,
    baw_arm_admittance,
    baw_arm_impedance,
    ladder_filter_synthesis,
    lattice_variant,
)
from rfauto.core.metasurface_lut import _abcd_shunt

FS_S = 2.0e9  # 串臂 fs（Hz），与 test_acoustic_resonator 量级锚同口径
C = _DEFAULT_CM_C0_RATIO  # 0.08
R0 = 1.0 / (1.0 + C)  # 缺省工作点（fa_p=fs_s 最大透射对齐）：S21@fs_s=0dB
Z0 = 50.0


def _pole_safe(f: np.ndarray, poles: list[float], rel: float = 1e-6) -> np.ndarray:
    """剔除恰落/过近无损极点的样本（inf/nan 奇点，见模块 docstring）。"""
    mask = np.ones(f.size, dtype=bool)
    for p in poles:
        mask &= np.abs(f - p) > rel * p
    return f[mask]


def _design():
    """锚设计派生量（与模块同式）：fa_s/fa_p/fs_p 与带宽口径。"""
    fa_s = FS_S * math.sqrt(1.0 + C)
    fs_p = FS_S * math.sqrt(R0)
    fa_p = fs_p * math.sqrt(1.0 + C)
    return fa_s, fs_p, fa_p


def test_one_section_s21_zero_db_at_fs_series_and_null_depths():
    """A1：1 节 S21@fs_series=0dB（n=1/3 同点）+ fa_s/fs_p 双侧零深 ≥40dB。"""
    fa_s, fs_p, _ = _design()
    grid = np.sort(np.array([FS_S, fa_s * (1.0 - 1e-9), fa_s * (1.0 + 1e-9),
                             fs_p * (1.0 - 1e-9), fs_p * (1.0 + 1e-9)]))
    i_fs = int(np.argmin(np.abs(grid - FS_S)))
    for n_sec in (1, 3):
        ret = ladder_filter_synthesis(FS_S, R0, n_sec, grid, z0_ohm=Z0)
        assert np.array_equal(ret["f_hz"], grid)  # 排序栅格返回口径
        s21 = np.abs(ret["s"][:, 1, 0])
        # fs_s 处串臂短路+并臂开路（fa_p=fs_s 对齐）→ 每节恒等阵 → 0dB
        assert abs(s21[i_fs] - 1.0) <= 1e-9, f"n={n_sec} S21@fs_series={s21[i_fs]!r}"
        # 零深：并臂串联谐振 fs_p（低侧两样本）与串臂反谐振 fa_s（高侧两样本）
        depth_idx = [i for i in range(grid.size) if i != i_fs]
        depth_db = -20.0 * np.log10(s21[depth_idx])
        assert np.all(depth_db >= 40.0), f"n={n_sec} 零深不足: {depth_db}"


def test_cascade_abcd_bitwise_consistency():
    """A2：n_sections=3 的 ABCD 与 3 节矩阵乘积逐位相等（同序左累积）。"""
    fa_s, fs_p, fa_p = _design()
    f = np.linspace(0.90, 1.12, 401) * FS_S
    f = _pole_safe(f, [fs_p, fa_p, fa_s])
    ret = ladder_filter_synthesis(FS_S, R0, 3, f, z0_ohm=Z0)
    c0 = ret["c0_f"]
    zs = baw_arm_impedance(f, FS_S, fa_s, c0)
    yp = baw_arm_admittance(f, fs_p, fa_p, c0)  # 与模块同函数（逐位前提）
    for i in range(f.size):
        m_s = np.array([[1.0, zs[i]], [0.0, 1.0]], dtype=complex)
        m_p = _abcd_shunt(1.0 / yp[i])
        section = m_s @ m_p
        total = section
        for _ in range(2):
            total = total @ section
        assert np.array_equal(ret["abcd"][i], total), f"逐位失配 @ {f[i]}"


def test_band_edge_semantics_bandpass_form():
    """A3：带缘两侧零+带内峰+酉性+互易；元数据带宽口径逐位一致。"""
    fa_s, fs_p, fa_p = _design()
    inband = _pole_safe(np.linspace(0.965, 1.036, 401) * FS_S, [fs_p, fa_p, fa_s])
    ret = ladder_filter_synthesis(
        FS_S, R0, 2, np.concatenate([inband, [FS_S]]), z0_ohm=Z0)
    # 带缘次序：低侧零 fs_p < fs_s < 高侧零 fa_s
    assert ret["fs_shunt_hz"] < ret["fs_series_hz"] < ret["fa_series_hz"]
    assert ret["fs_shunt_hz"] == fs_p
    assert ret["fa_series_hz"] == fa_s
    # 带宽口径逐位（模块 bw=(fa_s−fs_p)/fs_s 同表达式）
    bw = (ret["fa_series_hz"] - ret["fs_shunt_hz"]) / ret["fs_series_hz"]
    assert ret["bw_rel"] == bw
    assert ret["bw_rel_max"] == ret["keff2"] * math.sqrt(1.0 + C)
    # 带内峰 ≈1（@fs_s，0dB），带缘外侧 1e-4 相对偏置 ≤−30dB
    s21 = np.abs(ret["s"][:, 1, 0])
    assert s21.max() >= 1.0 - 1e-9
    edge = ladder_filter_synthesis(
        FS_S, R0, 2,
        np.array([fs_p * (1.0 - 1e-4), fa_s * (1.0 + 1e-4)]), z0_ohm=Z0)
    assert np.all(-20.0 * np.log10(np.abs(edge["s"][:, 1, 0])) >= 30.0)
    # 无损档酉性与互易
    s = ret["s"]
    diag = np.abs(s[:, 0, 0]) ** 2 + np.abs(s[:, 1, 0]) ** 2
    assert np.all(np.abs(diag - 1.0) <= 1e-9)
    assert np.abs(s).max() <= 1.0 + 1e-9
    assert np.all(np.abs(s[:, 0, 1] - s[:, 1, 0]) <= 1e-12)


def test_relative_bandwidth_guard_value_error():
    """A4：带宽超上限/带阻退化 ValueError；上限边界放行；元数据 keff² 复用。"""
    fa_s, _, _ = _design()
    grid = np.array([FS_S])
    # r < 1/(1+c)：请求带宽超 keff²·√(1+c) 上限 → ValueError
    with pytest.raises(ValueError, match="超上限"):
        ladder_filter_synthesis(FS_S, R0 * 0.999, 1, grid, z0_ohm=Z0)
    # 上限边界（r 略大于 1/(1+c)）放行；keff² 逐位复用 PK-1 keff2(fs, fa)
    ret = ladder_filter_synthesis(FS_S, R0 * (1.0 + 1e-9), 1, grid, z0_ohm=Z0)
    assert ret["keff2"] == keff2(FS_S, fa_s, exact=False)
    assert math.isclose(ret["keff2"], C / (1.0 + C), rel_tol=1e-12)
    assert ret["bw_rel_max"] == ret["keff2"] * math.sqrt(1.0 + C)
    # r ≥1：带阻退化（通带内两臂同号）→ ValueError
    with pytest.raises(ValueError, match="带阻"):
        ladder_filter_synthesis(FS_S, 1.0, 1, grid, z0_ohm=Z0)
    with pytest.raises(ValueError, match="带阻"):
        ladder_filter_synthesis(FS_S, 1.5, 1, grid, z0_ohm=Z0)


def test_input_validation_errors():
    """A4 补：参数域与频栅校负例全走 ValueError。"""
    grid = np.array([FS_S])
    with pytest.raises(ValueError, match="fs_series_hz"):
        ladder_filter_synthesis(0.0, R0, 1, grid)
    with pytest.raises(ValueError, match="cm_c0_ratio"):
        ladder_filter_synthesis(FS_S, R0, 1, grid, cm_c0_ratio=0.0)
    with pytest.raises(ValueError, match="cm_c0_ratio"):
        ladder_filter_synthesis(FS_S, R0, 1, grid, cm_c0_ratio=0.31)
    with pytest.raises(ValueError, match="z0_ohm"):
        ladder_filter_synthesis(FS_S, R0, 1, grid, z0_ohm=-1.0)
    with pytest.raises(ValueError, match="n_sections"):
        ladder_filter_synthesis(FS_S, R0, 0, grid)
    with pytest.raises(ValueError, match="n_sections"):
        ladder_filter_synthesis(FS_S, R0, 1.5, grid)
    with pytest.raises(ValueError, match="n_sections"):
        ladder_filter_synthesis(FS_S, R0, True, grid)
    with pytest.raises(ValueError, match="f_area_ratio"):
        ladder_filter_synthesis(FS_S, 0.0, 1, grid)
    for bad in ([], [[1e9, 2e9]], [0.0, 1e9], [float("nan"), 1e9], [-1e9]):
        with pytest.raises(ValueError, match="f_grid"):
            ladder_filter_synthesis(FS_S, R0, 1, np.asarray(bad))


def test_skrf_network_roundtrip_and_touchstone(tmp_path):
    """A5：network.s 逐位、手算 S 逐位+独立式对拍、Touchstone 往返。"""
    fa_s, fs_p, fa_p = _design()
    f = _pole_safe(np.linspace(0.94, 1.10, 301) * FS_S, [fs_p, fa_p, fa_s])
    ret = ladder_filter_synthesis(FS_S, R0, 2, f, z0_ohm=Z0)
    s = ret["s"]
    # skrf Network 的 s 与返回矩阵逐位相等，元数据齐备可导出
    assert np.array_equal(ret["network"].s, s)
    assert np.allclose(ret["network"].f, f, rtol=0, atol=0)
    # 手算 S（教科书转换式，与模块同表达式序）→ 逐位
    abcd = ret["abcd"]
    a = abcd[:, 0, 0]
    b = abcd[:, 0, 1]
    c_mat = abcd[:, 1, 0]
    d = abcd[:, 1, 1]
    den = a + b / Z0 + c_mat * Z0 + d
    s_hand = np.empty_like(s)
    s_hand[:, 0, 0] = (a + b / Z0 - c_mat * Z0 - d) / den
    s_hand[:, 1, 0] = 2.0 / den
    s_hand[:, 0, 1] = 2.0 * (a * d - b * c_mat) / den
    s_hand[:, 1, 1] = (-a + b / Z0 - c_mat * Z0 + d) / den
    assert np.array_equal(s, s_hand)
    # 代数重排独立式（den 通乘 Z0）互证 ≤1e-9（#118：独立来源对拍）
    alt_den = a * Z0 + b + c_mat * Z0 * Z0 + d * Z0
    assert np.allclose(2.0 * Z0 / alt_den, s[:, 1, 0], rtol=0, atol=1e-9)
    assert np.allclose(
        (a * Z0 + b - c_mat * Z0 * Z0 - d * Z0) / alt_den, s[:, 0, 0],
        rtol=0, atol=1e-9)
    # Touchstone 导出→读回
    path = tmp_path / "pk2_ladder.s2p"
    ret["network"].write_touchstone(str(path))
    back = skrf.Network(str(path))
    assert np.allclose(back.f, f, rtol=1e-12)
    assert np.allclose(back.s, s, rtol=0, atol=1e-6)


def test_pk1_resonance_semantics_crosscheck():
    """A6：bvd_resonances 回收 fs/fa + mbvd_impedance 独立实现对拍（#118）。"""
    fa_s, fs_p, fa_p = _design()
    c0 = 1.0 / (2.0 * math.pi * math.sqrt(fs_p * fa_s) * Z0)
    cm = C * c0
    lm = 1.0 / ((2.0 * math.pi * FS_S) ** 2 * cm)
    res = bvd_resonances(lm, cm, c0)
    assert math.isclose(res["fs_hz"], FS_S, rel_tol=1e-12)
    assert math.isclose(res["fa_hz"], fa_s, rel_tol=1e-12)
    # 并臂同构（fs_p/fa_p 对）
    cm_p = C * c0
    lm_p = 1.0 / ((2.0 * math.pi * fs_p) ** 2 * cm_p)
    res_p = bvd_resonances(lm_p, cm_p, c0)
    assert math.isclose(res_p["fs_hz"], fs_p, rel_tol=1e-12)
    assert math.isclose(res_p["fa_hz"], fa_p, rel_tol=1e-12)
    # 独立实现对拍：mbvd（Lm/Cm 电路并联式）vs 臂闭式（有理式），离极点 ≥1e-3
    probe = np.array([0.90, 0.97, 1.015, 1.03, 1.10]) * FS_S
    probe = _pole_safe(probe, [FS_S, fa_s, fs_p, fa_p], rel=1e-3)
    z_closed = baw_arm_impedance(probe, FS_S, fa_s, c0)
    z_mbvd = np.asarray(mbvd_impedance(probe, c0, 0.0, lm, cm, 0.0), dtype=complex)
    assert np.allclose(z_closed, z_mbvd, rtol=1e-9, atol=0.0)


def test_lattice_variant_anchors():
    """A7：格型 S21@fs_s≈1、带内 Zi 实值、酉性、远带零深、fs_s 处 Zi=0。"""
    fa_s, fs_p, fa_p = _design()
    inband = _pole_safe(np.linspace(0.965, 1.036, 201) * FS_S, [fs_p, fa_p, fa_s])
    grid = np.sort(np.concatenate([inband, [FS_S, 10.0 * FS_S]]))
    ret = lattice_variant(FS_S, R0, grid, z0_ohm=Z0)
    assert np.array_equal(ret["f_hz"], grid)
    s = ret["s"]
    i_fs = int(np.argmin(np.abs(grid - FS_S)))
    assert abs(abs(s[i_fs, 1, 0]) - 1.0) <= 1e-9
    # 酉性（无损格型）
    diag = np.abs(s[:, 0, 0]) ** 2 + np.abs(s[:, 1, 0]) ** 2
    assert np.all(np.abs(diag - 1.0) <= 1e-9)
    assert np.abs(s).max() <= 1.0 + 1e-9
    # 带内镜像阻抗实值（两臂反号 ⟺ Za·Zb>0 实）；fs_s 对齐点 Za=0 → Zi=0 精确
    zi = ret["zi"]
    assert abs(zi[i_fs]) <= 1e-12 * Z0
    inband_mask = (grid > fs_p) & (grid < fa_s) & (np.abs(grid - FS_S) > 1e-3 * FS_S)
    assert np.all(zi[inband_mask].real > 0.0)
    assert np.all(np.abs(zi[inband_mask].imag) <= 1e-9 * np.abs(zi[inband_mask]))
    # 远带 10·fs_s：阻带内 Za·Zb<0 → Zi 纯虚（镜像参数经典形态；虚部符号
    # 系分支切割上的 ulp 噪声，不钉号）；且 Za/Zb→1（两臂同为 C0 容性）
    # 平衡归零 ≥40dB
    i_far = grid.size - 1
    assert zi[i_far].real == 0.0 and zi[i_far].imag != 0.0
    assert -20.0 * np.log10(abs(s[i_far, 1, 0])) >= 40.0


def test_shunt_primitive_reuse_equivalence():
    """A8：_abcd_shunt 逐字复用 + 串臂本地原语与原语级联同构（≤1e-12）。"""
    fa_s, fs_p, fa_p = _design()
    f0 = np.array([0.98 * FS_S])
    ret = ladder_filter_synthesis(FS_S, R0, 1, f0, z0_ohm=Z0)
    c0 = ret["c0_f"]
    zs0 = baw_arm_impedance(f0[0], FS_S, fa_s, c0)
    zp0 = baw_arm_impedance(f0[0], fs_p, fa_p, c0)  # 并臂阻抗形式（=1/Yp）
    expected = np.array([[1.0, zs0], [0.0, 1.0]], dtype=complex) @ _abcd_shunt(zp0)
    assert np.allclose(ret["abcd"][0], expected, rtol=0, atol=1e-12)
