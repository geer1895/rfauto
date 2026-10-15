"""aurora36 W3-A 席锚树：unequal_split_wilkinson + bethe_hole_coupler 两键。

数值断言口径（#118 不自证）：
- Wilkinson：①K=1 退化锚 = Pozar 等分 Wilkinson（√2·Z0 臂 / 2·Z0 隔离
  电阻 / 变换段=Z0，教科书通用结果）；②K=1/√2（2:1 分配）文献锚 =
  Parad–Moynihan 1965（Microwaves101 "Unequal-split Wilkinsons" 转载：
  ZA=51.5 / ZB=103 / R=106.07 / 变换段 42.05/59.46 Ω @50Ω）；③独立裁判
  = 通用节点导纳分析（λ/4 线 j/Z 倒纳 + 隔离电阻网络组集 Y 矩阵→S），
  与设计闭式互为独立来源：全匹配 + S32=0 + 功率比=K²。
- Bethe：①X 波段量级锚（任务书指定）：WR-90 @10 GHz 单孔耦合文献典型
  带 20~30 dB；②c∝d³ 闭式自洽（d×2^(1/3) ⇒ 耦合精确 +6.0206 dB）；
  ③E/M 平衡独立物理不变量：f=c0/(√2·a) 设计频率方向性→无究大；
  ④λg 跨模块互证 rw_tables.wavelength_g。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

_Z0 = 50.0


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"] is True, f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


# ─── unequal_split_wilkinson：退化锚 / 文献锚 / 极值单调 / 显式拒绝 ────────


def test_unequal_split_degenerates_to_equal_at_k1():
    """K=1 → 等分 Wilkinson：臂 √2·Z0、R=2·Z0、变换段=Z0（Pozar 等分节）。"""
    r = _run("unequal_split_wilkinson", {"z0_ohm": _Z0, "power_ratio_k": 1.0})
    assert r["z02_arm_ohm"] == pytest.approx(math.sqrt(2.0) * _Z0, abs=1e-3)
    assert r["z03_arm_ohm"] == pytest.approx(math.sqrt(2.0) * _Z0, abs=1e-3)
    assert r["r_isolation_ohm"] == pytest.approx(2.0 * _Z0, abs=1e-3)
    assert r["z04_transformer_ohm"] == pytest.approx(_Z0, abs=1e-3)
    assert r["z05_transformer_ohm"] == pytest.approx(_Z0, abs=1e-3)
    assert r["favored_port"] == 0
    assert r["s21_db"] == pytest.approx(-3.0103, abs=1e-3)
    assert r["s31_db"] == pytest.approx(-3.0103, abs=1e-3)


def test_unequal_split_parad_moynihan_2to1_anchor():
    """K=1/√2（P3/P2=1/2，端口 2 受惠）→ Parad–Moynihan 文献值 @50Ω。

    锚：Microwaves101 "Unequal-split Wilkinsons"（ZA=51.5、ZB=103、
    R=106.07、变换段 42.05/59.46 Ω）——闭式设计的独立文献数值锚。
    """
    k = math.sqrt(0.5)
    r = _run("unequal_split_wilkinson", {"z0_ohm": _Z0, "power_ratio_k": k})
    assert r["z02_arm_ohm"] == pytest.approx(51.5, abs=0.05)
    assert r["z03_arm_ohm"] == pytest.approx(103.0, abs=0.05)
    assert r["r_isolation_ohm"] == pytest.approx(106.07, abs=0.05)
    assert r["z04_transformer_ohm"] == pytest.approx(42.05, abs=0.05)
    assert r["z05_transformer_ohm"] == pytest.approx(59.46, abs=0.05)
    assert r["favored_port"] == 2
    # 臂端电阻分配：受惠臂=低阻端，两臂之和=总隔离电阻
    assert r["r2_arm2_ohm"] + r["r3_arm3_ohm"] == pytest.approx(
        r["r_isolation_ohm"], rel=1e-9)


def test_unequal_split_power_fractions_and_db():
    """|S21|²+|S31|²=1 且分配比=K²（无损三端口功率守恒）。"""
    for k in (0.25, 0.7071, 2.0, 5.0):
        r = _run("unequal_split_wilkinson", {"z0_ohm": _Z0, "power_ratio_k": k})
        assert r["p2_fraction"] + r["p3_fraction"] == pytest.approx(1.0, abs=1e-12)
        assert r["p3_fraction"] / r["p2_fraction"] == pytest.approx(k * k, rel=1e-9)


def test_unequal_split_monotonic_extremes_no_negative():
    """K→极值（100/0.01）：阻抗单调、无负值、R≥2·Z0 且 K=1 取最小。"""
    ks = [0.01, 0.1, 0.5, 1.0, 2.0, 10.0, 100.0]
    z02s, z03s, rs = [], [], []
    for k in ks:
        r = _run("unequal_split_wilkinson", {"z0_ohm": _Z0, "power_ratio_k": k})
        z02s.append(r["z02_arm_ohm"])
        z03s.append(r["z03_arm_ohm"])
        rs.append(r["r_isolation_ohm"])
        assert min(r["z02_arm_ohm"], r["z03_arm_ohm"],
                   r["r_isolation_ohm"]) > 0.0
    assert z02s == sorted(z02s)  # Z02 随 K 单调升
    assert z03s == sorted(z03s, reverse=True)  # Z03 随 K 单调降
    assert rs[ks.index(1.0)] == min(rs)  # R 在 K=1 取最小 2·Z0
    assert rs[ks.index(1.0)] == pytest.approx(2.0 * _Z0, abs=1e-6)
    # K>10 如实标注不可常规实现（>100:1 臂/电阻比），不拒绝
    assert _run("unequal_split_wilkinson",
                {"z0_ohm": _Z0, "power_ratio_k": 100.0})["practical_split"] is False
    assert _run("unequal_split_wilkinson",
                {"z0_ohm": _Z0, "power_ratio_k": 2.0})["practical_split"] is True


@pytest.mark.parametrize("bad_k", [0.0, -1.0, float("nan"), float("inf")])
def test_unequal_split_rejects_bad_k(bad_k):
    spec = CALCULATOR_REGISTRY.get("unequal_split_wilkinson")
    with pytest.raises(ValueError, match="power_ratio_k"):
        spec.func(z0_ohm=_Z0, power_ratio_k=bad_k)


@pytest.mark.parametrize("bad_z0", [0.0, -50.0, float("nan")])
def test_unequal_split_rejects_bad_z0(bad_z0):
    spec = CALCULATOR_REGISTRY.get("unequal_split_wilkinson")
    with pytest.raises(ValueError, match="z0_ohm"):
        spec.func(z0_ohm=bad_z0, power_ratio_k=2.0)


# ─── 独立裁判：节点导纳分析重算全 S 矩阵（与设计闭式互为独立来源）──────────


def _wilkinson_s_matrix(z0: float, z02: float, z03: float, r_total: float,
                        z04: float, z05: float) -> np.ndarray:
    """中心频率节点导纳分析（3×3 S，端口序 [1, 2, 3]）。

    节点：J=端口1、A2/A3=两臂末端、P2/P3=端口 2/3。λ/4 线在中心频率
    只有互导纳 j/Z（自导纳=0，cot(π/2)=0）；隔离电阻为 A2–A3 间串联 g。
    S 提取=直波法：全部端口节点并 1/Z0 接地终接，逐列在端口节点注入
    单位入射波电流源 1/√Z0 解节点电压，b_k=v_k/√Z0（激励口再减 a=1）。
    """
    y = np.zeros((5, 5), dtype=complex)

    def line(u: int, v: int, z: float) -> None:
        y[u, v] += 1j / z
        y[v, u] += 1j / z

    def shunt(u: int, adm: complex) -> None:
        y[u, u] += adm

    line(0, 1, z02)
    line(0, 2, z03)
    g = 1.0 / r_total
    shunt(1, g)
    shunt(2, g)
    y[1, 2] -= g
    y[2, 1] -= g
    line(1, 3, z04)
    line(2, 4, z05)
    ports = [0, 3, 4]
    for p in ports:  # 端口参考阻抗=接地终接（同时给网络提供地参考）
        y[p, p] += 1.0 / z0
    yt_inv = np.linalg.inv(y)
    s = np.zeros((3, 3), dtype=complex)
    sq = math.sqrt(z0)
    for j in range(3):
        i_src = np.zeros(5, dtype=complex)
        # 端口=Thévenin(2√Z0·a_j, Z0) → Norton 电流源 2a_j/√Z0（含源内阻 1/Z0）
        i_src[ports[j]] = 2.0 / sq
        v = yt_inv @ i_src
        for k in range(3):
            s[k, j] = v[ports[k]] / sq  # b_k = v_k/√Z0（a_k=0）
        s[j, j] -= 1.0  # 激励口 b_j = v_j/√Z0 − a_j
    return s


@pytest.mark.parametrize("k", [0.5, 1.0, math.sqrt(2.0), 2.0, 3.0])
def test_unequal_split_nodal_smatrix_referee(k):
    """节点分析独立裁判：全匹配 + 隔离 S32=0 + 功率比=K² + 互易 + 守恒。

    裁判输入用闭式精确值（API 输出按 1e-4 Ω 圆整，1e-9 级判据必须喂
    精确阻抗）；API 输出与精确闭式的圆整一致由断言 1 单独钉。
    """
    z02 = _Z0 * math.sqrt(k * (1.0 + k * k))
    z03 = _Z0 * math.sqrt((1.0 + k * k) / (k * k * k))
    r_iso = _Z0 * (1.0 + k * k) / k
    z04 = _Z0 * math.sqrt(k)
    z05 = _Z0 / math.sqrt(k)
    # API 输出与闭式逐键一致（圆整精度 1e-4 Ω）
    r = _run("unequal_split_wilkinson", {"z0_ohm": _Z0, "power_ratio_k": k})
    assert r["z02_arm_ohm"] == pytest.approx(z02, abs=1e-3)
    assert r["z03_arm_ohm"] == pytest.approx(z03, abs=1e-3)
    assert r["r_isolation_ohm"] == pytest.approx(r_iso, abs=1e-3)
    assert r["z04_transformer_ohm"] == pytest.approx(z04, abs=1e-3)
    assert r["z05_transformer_ohm"] == pytest.approx(z05, abs=1e-3)
    s = _wilkinson_s_matrix(_Z0, z02, z03, r_iso, z04, z05)
    assert np.max(np.abs(s)) <= 2.0
    for (i, j) in ((0, 0), (1, 1), (2, 2)):  # 全端口匹配
        assert abs(s[i, j]) < 1e-9, f"S{i+1}{j+1}={s[i, j]}"
    assert abs(s[2, 1]) < 1e-9, f"隔离 S32={s[2, 1]} 未归零"
    assert abs(s[1, 2]) < 1e-9  # 互易（隔离双向）
    p2 = abs(s[1, 0]) ** 2  # |S21|²
    p3 = abs(s[2, 0]) ** 2  # |S31|²
    assert p2 + p3 == pytest.approx(1.0, abs=1e-9)  # 无损守恒
    assert p3 / p2 == pytest.approx(k * k, rel=1e-8)  # 设计功率比
    np.testing.assert_allclose(s, s.T, atol=1e-12)  # 互易 S=Sᵀ


# ─── bethe_hole_coupler：量级锚 / d³ 律 / 设计频率方向性 / 综合 / 守卫 ─────


def test_bethe_analysis_xband_literature_window():
    """WR-90 @10 GHz、d=6mm → 耦合落 X 波段单孔文献典型带 20~30 dB 量级。"""
    r = _run("bethe_hole_coupler", {"wr_name": "WR-90", "freq_ghz": 10.0,
                                    "hole_diameter_mm": 6.0})
    assert 18.0 <= r["coupling_db"] <= 32.0
    assert r["mode"] == "analysis"
    assert r["coupler_sense"] == "reverse (backward-wave)"
    # 方向性有限且为正（偏离设计频率）；隔离=耦合+方向性
    assert 0.0 < r["directivity_db"] < 60.0
    assert r["isolation_db"] == pytest.approx(
        r["coupling_db"] + r["directivity_db"], abs=1e-6)


def test_bethe_coupling_follows_d_cubed_law():
    """c∝d³ 闭式自洽：d×2^(1/3) ⇒ 耦合精确 +6.0206 dB（20·lg2）。"""
    d0 = 4.0
    r1 = _run("bethe_hole_coupler", {"wr_name": "WR-90", "freq_ghz": 10.0,
                                     "hole_diameter_mm": d0})
    r2 = _run("bethe_hole_coupler", {"wr_name": "WR-90", "freq_ghz": 10.0,
                                     "hole_diameter_mm": d0 * 2.0 ** (1.0 / 3.0)})
    assert r2["coupling_db"] == pytest.approx(
        r1["coupling_db"] - 20.0 * math.log10(2.0), abs=1e-6)


def test_bethe_design_frequency_directivity_maximum():
    """E/M 平衡独立物理不变量：f=c0/(√2·a) 时隔离向相消 → 方向性极大。"""
    f_design = 299792458.0 / (math.sqrt(2.0) * 22.86e-3) / 1e9
    r = _run("bethe_hole_coupler", {"wr_name": "WR-90",
                                    "freq_ghz": round(f_design, 6),
                                    "hole_diameter_mm": 5.0})
    assert r["directivity_db"] > 60.0  # c_iso 机器零 → 方向性无究大量级
    assert r["f_design_ghz"] == pytest.approx(f_design, abs=1e-3)


def test_bethe_lambda_g_cross_module_consistency():
    """λg 与 rw_tables.wavelength_g 跨模块互证（同值单源）。"""
    from rfauto.core.rw_tables import wavelength_g

    r = _run("bethe_hole_coupler", {"wr_name": "WR-90", "freq_ghz": 10.0,
                                    "hole_diameter_mm": 6.0})
    assert r["lambda_g_mm"] == pytest.approx(
        wavelength_g(10.0, 22.86), abs=1e-3)  # 输出按 4 位小数圆整
    assert r["fc10_ghz"] == pytest.approx(299792458.0 / (2 * 22.86e-3) / 1e9,
                                          abs=1e-5)  # 输出按 6 位小数圆整


def test_bethe_synthesis_roundtrip_and_physical_window():
    """综合 25 dB → 孔径物理窗 + 回代自洽 + 分析(孔径)=目标。"""
    r = _run("bethe_hole_coupler", {"wr_name": "WR-90", "freq_ghz": 10.0,
                                    "coupling_db": 25.0})
    assert r["mode"] == "synthesis"
    assert 3.0 <= r["hole_diameter_mm"] <= 6.5  # 物理可实现窗（X 波段单孔）
    assert r["roundtrip_diameter_mm"] == pytest.approx(
        r["hole_diameter_mm"], abs=1e-6)
    back = _run("bethe_hole_coupler", {"wr_name": "WR-90", "freq_ghz": 10.0,
                                       "hole_diameter_mm": r["hole_diameter_mm"]})
    # 孔径输出按 6 位小数圆整 → 回代耦合度差 <1e-4 dB
    assert back["coupling_db"] == pytest.approx(25.0, abs=1e-4)


def test_bethe_explicit_dims_match_wr_route():
    """显式 a/b 口径与 wr_name 口径同参同果（rw_tables 单源一致性）。"""
    a, b = 22.86, 10.16
    via_wr = _run("bethe_hole_coupler", {"wr_name": "WR-90", "freq_ghz": 10.0,
                                         "hole_diameter_mm": 5.0})
    via_dims = _run("bethe_hole_coupler", {"a_mm": a, "b_mm": b,
                                           "freq_ghz": 10.0,
                                           "hole_diameter_mm": 5.0})
    assert via_wr["coupling_db"] == via_dims["coupling_db"]
    assert via_dims["wr_name"] is None


def test_bethe_cohn_thickness_weakens_coupling():
    """Cohn 修正（t>0）：耦合变弱、共振因子>1、衰减<1、applied 标记。"""
    base = _run("bethe_hole_coupler", {"wr_name": "WR-90", "freq_ghz": 10.0,
                                       "hole_diameter_mm": 5.0})
    thick = _run("bethe_hole_coupler", {"wr_name": "WR-90", "freq_ghz": 10.0,
                                        "hole_diameter_mm": 5.0,
                                        "wall_thickness_mm": 1.0})
    assert base["cohn"]["applied"] is False
    assert thick["cohn"]["applied"] is True
    assert thick["coupling_db"] > base["coupling_db"]  # 壁厚 → 耦合变弱
    assert thick["cohn"]["resonance_factor_m"] > 1.0
    assert 0.0 < thick["cohn"]["thickness_att_m"] < 1.0
    # 同厚度扫描单调：更厚更弱
    thicker = _run("bethe_hole_coupler", {"wr_name": "WR-90", "freq_ghz": 10.0,
                                          "hole_diameter_mm": 5.0,
                                          "wall_thickness_mm": 2.0})
    assert thicker["coupling_db"] > thick["coupling_db"]


def test_bethe_synthesis_unreachable_rejected():
    """综合可达窗外显式拒绝（强耦合需求超出 d_max 窗）。"""
    out = run_calculator("bethe_hole_coupler", {"wr_name": "WR-90",
                                                "freq_ghz": 10.0,
                                                "coupling_db": 3.0})
    assert out["ok"] is False
    assert "不可达" in out["error"]


@pytest.mark.parametrize("params,match", [
    # 截止下（无传播解）
    ({"wr_name": "WR-90", "freq_ghz": 6.0, "hole_diameter_mm": 5.0},
     "截止"),
    # 截止附近 5% 带内（λg 发散带）
    ({"wr_name": "WR-90", "freq_ghz": 6.7, "hole_diameter_mm": 5.0},
     "截止"),
    # 窄边比例上限守卫（d>0.8·b）
    ({"wr_name": "WR-90", "freq_ghz": 10.0, "hole_diameter_mm": 9.0},
     "窄边比例上限"),
    # 小孔假设上限（d>λ0/3）
    ({"wr_name": "WR-90", "freq_ghz": 10.0, "hole_diameter_mm": 11.0},
     "小孔假设"),
    # 双方向入参互斥
    ({"wr_name": "WR-90", "freq_ghz": 10.0, "hole_diameter_mm": 5.0,
      "coupling_db": 25.0}, "只能给其一"),
    # 双向皆缺
    ({"wr_name": "WR-90", "freq_ghz": 10.0}, "之一"),
    # 负耦合度
    ({"wr_name": "WR-90", "freq_ghz": 10.0, "coupling_db": -5.0},
     "coupling_db"),
    # wr_name 与显式尺寸互斥
    ({"wr_name": "WR-90", "a_mm": 22.86, "b_mm": 10.16, "freq_ghz": 10.0,
      "hole_diameter_mm": 5.0}, "二选一"),
])
def test_bethe_domain_guards_explicit(params, match):
    out = run_calculator("bethe_hole_coupler", params)
    assert out["ok"] is False, f"越界输入未拒绝: {params!r} -> {out!r}"
    assert match in out["error"]


def test_bethe_cohn_resonance_domain_rejected():
    """Cohn 域守卫：f≥0.9·f_res,m（孔口共振）显式拒绝（公共核直调）。

    在小孔假设界内（d≤λ0/3）恒有 f_res,m≥1.76f，公共键路径到不了共振
    守卫（防线纵深，仍须验证其可失败）——用 d=20mm 大孔直调公共核：
    f_res,m=c0/(1.706·20mm)=8.79 GHz，f=10GHz 落拒绝带。
    """
    from rfauto.core.calc_families.bethe_hole import _bethe_amplitude_coeffs

    with pytest.raises(ValueError, match="共振"):
        _bethe_amplitude_coeffs(22.86, 10.16, 10.0, 20.0, 0.5)
    # 同孔零厚度口径不受共振守卫拦截（Cohn 修正未启用）
    core = _bethe_amplitude_coeffs(22.86, 10.16, 10.0, 20.0, 0.0)
    assert core["c_strong"] > 0.0


def test_bethe_service_envelope_json_contract():
    """service 出口契约：ok=True、结果 dict、可 JSON 化（JSON 进出）。"""
    import json

    out = run_calculator("bethe_hole_coupler", {"wr_name": "WR-90",
                                                "freq_ghz": 10.0,
                                                "hole_diameter_mm": 5.0})
    assert out["ok"] is True and isinstance(out["result"], dict)
    json.dumps(out, ensure_ascii=False, allow_nan=False)
