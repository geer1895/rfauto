"""PK-2 席余件（2026-10-08）：垂直 PDN 文献双源对拍 + 封装互连段文献
量级表（金标准 Q3D 对拍的外部替代）+ service 接线钉。

四类钉（预声明，#122 判据先行）
================================

1. **换算回归钉**：core/package_chain 段工厂 per-length 实用单位键
   （H/m→nH/mm=×1e6；F/m→fF/mm=×1e12）——v1 误写 ×1e3（值大/小
   1e6 倍），本席文献量级表对拍准备阶段抓出，闭式独立重算+换算恒等
   式双钉。
2. **文献双源对拍**（PK-1 登记的"金标准 Q3D 对拍需外部"在 PDN 域的
   替代）：Novak-Miller《Frequency-Domain Characterization of Power
   Distribution Networks》（Artech House 2007）**章节公式口径**（PDN
   文献 canon，同式见作者公开论文集；无页码级引用——不虚构出处，
   #122/引用腐坏纪律）：①平面偶静态电容 C=ε0·εr·A/d 与方对第一腔模
   f10=c/(2√εr·a)（双端独立算术逐位+数量级例）；②静态电容预算恒等式
   （各平面对并联求和=总静态电容——梯形链 l_array=0 时与
   core/pdn.pdn_impedance_profile 合并电容逐位，N 层推广）。
3. **文献量级表**：典型封装互连段 L/R/C vs 印刷值带（**±30% 偏差带
   预声明**；印刷带为二级文献口径，标注沿用仓内 SOURCE 惯例如实
   UNVERIFIED/SECONDARY，不冒充 vendor 实测）：bondwire 2mm/
   bump(pillar) h=100µm/TGV 1:10(500µm)/RDL 5µm 四行。
4. **service 薄壳钉**：pdn_vertical_analyze（core/pdn_vertical 的
   JSON 薄壳）与 core 直调逐位（薄壳不改语义）+ 契约错误 ok=False；
   chain_si_channel_report 一段式接线（si ok=True、2 端口 COM 段
   not_applicable 如实透传、链摘要与直调装配一致）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.package_chain import (
    bondwire_network,
    bump_pi_network,
    quasi_tem_line_network,
    tgv_line_network,
)
from rfauto.core.pdn import VrmModel, pdn_impedance_profile
from rfauto.core.pdn_vertical import (
    LayerSpec,
    plane_pair_capacitance,
    vertical_pdn_impedance,
)
from rfauto.core.synthesis import Stackup, forward_z0
from rfauto.service.package_chain_service import (
    build_package_chain_report,
    chain_si_channel_report,
)
from rfauto.service.pdn_service import pdn_vertical_analyze

_EPS0_CODATA = 8.8541878128e-12  # CODATA 2018（core/pdn_vertical 同值口径）
_C0 = 299792458.0
_MU0 = 4.0e-7 * math.pi
_ETA0 = _MU0 * _C0  # 真空波阻抗 376.7303 Ω（教科书圆整值 120π≈377 的精确口径）
_FREQ = np.array([1.0e6, 1.0e9, 1.0e10])


# ── 钉 1：per-length 换算回归（v1 ×1e3 标度错，值大 1e6 倍）─────────────────

def test_per_length_conversion_regression_tgv_and_tem() -> None:
    """H/m→nH/mm=×1e6、F/m→fF/mm=×1e9；闭式独立重算逐位。"""
    tg = tgv_line_network(
        _FREQ, r_via_m=25e-6, r_shield_m=125e-6, length_m=500e-6,
        er_glass=6.0)
    # 同轴闭式独立重算：L'=μ0/2π·ln(b/a)、C'=2πε0εr/ln(b/a)
    ln_ba = math.log(125e-6 / 25e-6)
    assert tg["l_per_length_nh_per_mm"] == pytest.approx(
        2.0e-7 * ln_ba * 1e6, rel=1e-12)
    assert tg["c_per_length_ff_per_mm"] == pytest.approx(
        2.0 * math.pi * 8.854187817e-12 * 6.0 / ln_ba * 1e12, rel=1e-8)
    # 数量级常识带（nH/mm 量级，v1 错值 3.2e5 一眼即穿）
    assert 0.1 < tg["l_per_length_nh_per_mm"] < 1.0
    assert 100.0 < tg["c_per_length_ff_per_mm"] < 400.0
    ln = quasi_tem_line_network(
        _FREQ, z0_ohm=48.76, eps_eff=2.567, length_m=2e-3)
    l_hand = 48.76 * math.sqrt(2.567) / _C0    # H/m
    c_hand = math.sqrt(2.567) / (48.76 * _C0)  # F/m
    assert ln["l_per_length_nh_per_mm"] == pytest.approx(l_hand * 1e6,
                                                         rel=1e-12)
    assert ln["c_per_length_ff_per_mm"] == pytest.approx(c_hand * 1e12,
                                                         rel=1e-12)
    # TEM 恒等式：l_nh_per_mm × c_fF_per_mm 换算回 SI 后 L'·C'=μ0ε0·εeff
    assert (ln["l_per_length_nh_per_mm"] * 1e-6
            * ln["c_per_length_ff_per_mm"] * 1e-12 / (4e-7 * math.pi * _EPS0_CODATA)
            == pytest.approx(2.567, rel=1e-6))


# ── 钉 2：文献双源对拍（Novak-Miller 章节公式口径）───────────────────────────

def test_novak_plane_pair_static_cap_and_cavity_typed_example() -> None:
    """源①章节公式：C=ε0εr·A/d 与方对 f10=c/(2√εr·a) 双端独立算术逐位。

    数量级例（章节口径典型值）：100mm×100mm FR4（εr=4.4）100µm 平面偶
    ≈3.9 nF——抓 1e6 类标度错（本席在 TGV 换算键实证的同族错型）。
    """
    a = b = 25e-3
    gap = 2.0e-4
    er = 4.4
    out = plane_pair_capacitance(a, b, gap, er)
    c_hand = _EPS0_CODATA * er * a * b / gap
    assert out["c_f"] == pytest.approx(c_hand, rel=1e-9)
    f10_hand = _C0 / (2.0 * math.sqrt(er) * a)
    assert out["f_cavity1_hz"] == pytest.approx(f10_hand, rel=1e-8)
    # 数量级例（书口径印刷值带）：C ≈ 3.9 nF（±10% 手算常数带）
    out2 = plane_pair_capacitance(0.1, 0.1, 1.0e-4, 4.4)
    assert 3.5e-9 < out2["c_f"] < 4.3e-9
    # 方对腔模：f10 = c/(2√εr·a) ≈ 7.15 GHz（独立算术）
    assert out2["f_cavity1_hz"] == pytest.approx(
        _C0 / (2.0 * math.sqrt(4.4) * 0.1), rel=1e-8)


def test_novak_static_capacitance_budget_ladder_identity() -> None:
    """源②静态电容预算恒等式：l_array=0 时 N 层梯形=ΣC 单节点
    （与 pdn_impedance_profile 合并 bulk 电容逐位，N 层推广——
    W4-D 单层退化恒等式 1e-9 钉的推广面）。"""
    freqs = np.geomspace(1.0e4, 2.0e10, 400)
    vrm = VrmModel(r0=2.0e-4, l0=5.0e-8, r1=5.0e-3, l1=1.0e-9)
    caps = [3.4e-9, 7.79e-12, 1.2e-10]
    dec = (1.0e-7, 0.02, 5.0e-11, 3.0e-11)
    layers = [
        LayerSpec("l0", caps[0], 0.0),
        LayerSpec("l1", caps[1], 0.0, decaps=(dec,)),
        LayerSpec("l2", caps[2], 0.0),
    ]
    vert = vertical_pdn_impedance(layers, vrm, freqs)
    legacy = pdn_impedance_profile(
        vrm, [(sum(caps), 0.0, 0.0)], [dec], freqs)
    rel = np.max(np.abs(vert["z_complex"] - legacy) / np.abs(legacy))
    assert rel < 1e-9, f"静态电容预算恒等式破坏：max rel err={rel:.3e}"


# ── 钉 3：文献量级表（金标准 Q3D 对拍替代，±30% 偏差带预声明）────────────────
#
# 印刷值带为二级文献口径（搜索/教科书带，非 vendor 实测，不虚构出处）：
#   bondwire L：1 nH/mm 行业经验（仓内 UNVERIFIED_RULE_OF_THUMB 既有口径，
#     tests/unit/test_package_interconnect.py 行业带同族）；R_dc：金电导率
#     4.11e7 S/m（教科书常数）直算。
#   bump/pillar L：单凸点 10–50 pH（3D IC 封装文献通用带）；C：pad 对平行板
#     分量 fF 级（印刷带 10–100 fF 属全结构含 pad/underfill 口径，平行板
#     分量为其下沿，如实分口径声明）。
#   TGV L：0.1–0.5 nH（玻璃转接板文献通用带）；C：100–500 fF（同上带）。
#   RDL z0：40–70 Ω；时延 5–8 ps/mm（εeff≈2.5–4.5 印刷带推得）。
# 偏差带 = 印刷带端点 ±30%（预声明；越带即红，不凑绿 #122）。

def test_lit_table_bondwire_2mm() -> None:
    """行 1：金线 2mm/25µm——L≈2 nH（1 nH/mm）、R_dc≈0.1 Ω。"""
    out = bondwire_network(_FREQ, length_m=2e-3, radius_m=12.5e-6,
                           sigma_s_per_m=4.11e7)
    # L：印刷锚 2.0 nH，±30% → [1.4, 2.6]
    assert 1.4e-9 <= out["l_total_nh"] * 1e-9 <= 2.6e-9, (
        f"bondwire L={out['l_total_nh']:.3f} nH 出 [1.4,2.6] nH 带")
    # R_dc：金 4.11e7 S/m 直算 0.0994 Ω，印刷锚 ≈0.1 Ω，±30% → [0.07,0.13]
    r_hand = 2e-3 / (4.11e7 * math.pi * (12.5e-6) ** 2)
    assert out["r_dc_ohm"] == pytest.approx(r_hand, rel=1e-6)
    assert 0.07 <= out["r_dc_ohm"] <= 0.13


def test_lit_table_bump_pillar_h100um() -> None:
    """行 2：Cu pillar h=100µm/d=40µm（h/d=2.5，in-scope）——L≈31 pH、
    C(pad 对平行板)≈1.65 fF。"""
    out = bump_pi_network(
        _FREQ, height_m=100e-6, diameter_m=40e-6, pad_diameter_m=60e-6,
        er_between=6.6)
    assert out["in_declared_scope"] is True
    # L：印刷带 [10,50] pH，端点 ±30% → [7,65]
    assert 7.0 <= out["l_total_ph"] <= 65.0, (
        f"bump L={out['l_total_ph']:.2f} pH 出 [7,65] pH 带")
    # C：平行板分量手算 ε0·6.6·π(30µm)²/100µm ≈ 1.65 fF；印刷口径带
    # [1,10] fF，±30% → [0.7,13]
    c_hand = 8.854187817e-12 * 6.6 * math.pi * (30e-6) ** 2 / 100e-6
    assert out["c_total_ff"] == pytest.approx(c_hand * 1e15, rel=1e-8)
    assert 0.7 <= out["c_total_ff"] <= 13.0


def test_lit_table_tgv_1to10() -> None:
    """行 3：TGV 1:10（r=25µm、h=500µm、玻璃 εr=6）——孤立棒 L≈0.29 nH、
    同轴 C（回流半径 3r 声明口径）≈152 fF。"""
    out = tgv_line_network(
        _FREQ, r_via_m=25e-6, r_shield_m=75e-6, length_m=500e-6,
        er_glass=6.0)
    # L/长度：rosa 孤立棒 0.294 nH/500µm → 印刷带 [0.1,0.5] nH ±30% →
    # [0.07,0.65]；经 per-length 键（nH/mm）核总量
    l_total_nh = out["l_per_length_nh_per_mm"] * 0.5
    assert 0.07 <= l_total_nh <= 0.65, (
        f"TGV L_total={l_total_nh:.3f} nH 出 [0.07,0.65] nH 带")
    # C：同轴回流 3r 口径 C'=2πε0εr/ln3 ≈ 304 fF/m → 152 fF；印刷带
    # [100,500] fF ±30% → [70,650]
    c_total_ff = out["c_per_length_ff_per_mm"] * 0.5
    assert 70.0 <= c_total_ff <= 650.0, (
        f"TGV C_total={c_total_ff:.1f} fF 出 [70,650] fF 带")
    assert out["z0_coax_ohm"] == pytest.approx(
        _ETA0 / (2.0 * math.pi * math.sqrt(6.0)) * math.log(3.0), rel=1e-9)


def test_lit_table_rdl_5um_line() -> None:
    """行 4：RDL 5µm 线宽/2µm 介质（εr=3.3）——z0≈49 Ω、时延≈5.3 ps/mm。"""
    stack = Stackup(name="rdl_lit", epsilon_r=3.3, thickness_mm=0.002,
                    loss_tangent=0.02)
    media = forward_z0(0.005, 10.0, stack)
    # z0：印刷带 [40,70] Ω ±30% → [28,91]
    assert 28.0 <= media.z0 <= 91.0, f"RDL z0={media.z0:.1f} Ω 出 [28,91] Ω 带"
    out = quasi_tem_line_network(
        _FREQ, z0_ohm=media.z0, eps_eff=media.er_eff, length_m=1e-3)
    # 时延：√εeff/c ≈ 5.34 ps/mm；印刷带 [5,8] ps/mm ±30% → [3.5,10.4]
    t_ps_per_mm = out["t_delay_ps"]  # length=1mm
    assert t_ps_per_mm == pytest.approx(
        1e-3 * math.sqrt(media.er_eff) / _C0 * 1e12, rel=1e-9)
    assert 3.5 <= t_ps_per_mm <= 10.4


# ── 钉 4：service 薄壳钉 ─────────────────────────────────────────────────────

_PDN_PAYLOAD = {
    "f_axis": list(np.geomspace(1.0e5, 2.0e10, 300)),
    "layers": [
        {"name": "on_die", "plane": {"a_m": 2e-3, "b_m": 2e-3,
                                     "gap_m": 20e-6, "er": 4.4},
         "via_array": {"n_x": 20, "n_y": 20, "length_m": 50e-6,
                       "radius_m": 12.5e-6, "pitch_x_m": 50e-6,
                       "pitch_y_m": 50e-6}},
        {"name": "pkg", "plane": {"a_m": 10e-3, "b_m": 10e-3,
                                  "gap_m": 100e-6, "er": 4.4},
         "l_array_h": 2.9e-10,
         "decaps": [[1e-7, 0.02, 5e-11]]},
    ],
    "vrm": {"r0": 2e-4, "l0": 5e-8, "r1": 5e-3, "l1": 1e-9},
}


def test_pdn_vertical_analyze_thin_shell_identity() -> None:
    """薄壳不改语义：service JSON 口径与 core 直调逐位（1e-12）。"""
    from rfauto.core.pdn_vertical import array_equivalent_inductance

    rep = pdn_vertical_analyze(_PDN_PAYLOAD)
    assert rep["ok"] is True
    pp_top = plane_pair_capacitance(2e-3, 2e-3, 20e-6, 4.4)
    pp_bot = plane_pair_capacitance(10e-3, 10e-3, 100e-6, 4.4)
    l_eff = array_equivalent_inductance(
        20, 20, 50e-6, 12.5e-6, 50e-6, 50e-6)["l_eff_h"]
    layers = [
        LayerSpec(name="on_die", c_plane_f=pp_top["c_f"], l_array_h=l_eff,
                  f_cavity1_hz=pp_top["f_cavity1_hz"], er=4.4),
        LayerSpec(name="pkg", c_plane_f=pp_bot["c_f"], l_array_h=2.9e-10,
                  decaps=((1e-7, 0.02, 5e-11),),
                  f_cavity1_hz=pp_bot["f_cavity1_hz"], er=4.4),
    ]
    freqs = np.asarray(rep["f_hz"], dtype=float)
    core = vertical_pdn_impedance(layers, VrmModel(2e-4, 5e-8, 5e-3, 1e-9),
                                  freqs)
    z_rep = np.asarray(rep["z_mag_ohm"], dtype=float)
    assert np.max(np.abs(z_rep - core["z_abs"]) / core["z_abs"]) < 1e-12
    assert rep["n_layers"] == 2
    assert rep["layer_details"][0]["f_cavity1_hz"] == pytest.approx(
        pp_top["f_cavity1_hz"], rel=1e-12)
    assert rep["layer_details"][1]["n_decaps"] == 1
    assert isinstance(rep["peaks"], list)
    # 全频无源性（纯 LC/VRM 无源链，判据 3 同族）
    assert np.all(np.asarray(rep["z_re_ohm"], dtype=float) >= -1e-12)


def test_pdn_vertical_analyze_contract_errors() -> None:
    """契约错误 → ok=False + errors（同 pdn_analyze 家族口径）。"""
    bad = pdn_vertical_analyze({"f_start": 1e3, "f_stop": 1e6,
                                "n_points": 10, "layers": [{"name": "x"}]})
    assert bad["ok"] is False and bad["errors"]
    no_freq = pdn_vertical_analyze({"layers": [
        {"name": "l", "c_plane_f": 1e-9, "l_array_h": 0.0}]})
    assert no_freq["ok"] is False and no_freq["errors"]
    not_dict = pdn_vertical_analyze(["nope"])
    assert not_dict["ok"] is False


def test_chain_si_channel_report_wiring() -> None:
    """一段式接线：链 → 瞬态 s2p → si_channel_report 全链通。

    COM 段 not_applicable 如实透传（2 端口合成链不在 COM 的 4 端口
    输入域）；链摘要与 build_package_chain_report 直调一致。
    """
    payload = {
        "freq_hz": list(np.geomspace(1.0e7, 4.0e10, 201)),
        "segments": [
            {"kind": "bondwire", "length_m": 2e-3, "radius_m": 12.5e-6},
            {"kind": "line", "width_mm": 0.005, "length_m": 5e-3,
             "stackup": {"epsilon_r": 3.3, "thickness_mm": 0.002,
                         "loss_tangent": 0.02}},
        ],
    }
    wired = chain_si_channel_report(payload)
    assert wired["ok"] is True
    chain = wired["chain"]
    direct = build_package_chain_report(payload)
    assert chain["min_il_db"] == pytest.approx(direct["min_il_db"],
                                               rel=1e-12)
    assert chain["mean_il_db"] == pytest.approx(direct["mean_il_db"],
                                                rel=1e-12)
    assert chain["passive"] is True
    # 单信封直读：si 四段挂同级（构造器单源增广，不再造新信封——契约 §4）
    assert wired["source"]["n_ports"] == 2
    assert wired["source"]["n_freqs"] == 201
    assert wired["com"]["status"] == "not_applicable"  # 如实，不伪装
    assert wired["passivity"]["status"] == "pass"
    assert "not_applicable" in wired["note"] or "4 端口" in wired["note"]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
