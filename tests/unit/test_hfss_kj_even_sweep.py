"""P-KJ-EVEN P2：HFSS 宽端口扫描战役发射面离线单测（零真机，HFSS 未装可跑）。

覆盖（规格离线可测面，v2 测量架构口径）：①点表与毫米换算/KJ 锚转写钉；
②εeff 包络；③Γ 反演与参考阻抗无关性（合成已知量回收 #118）；④γL 解缠；
⑤基准确认门（#307 格点 {1,0.5,2}）与单线基准换算因子；⑥直读-反演互证门；
⑦gate0 v2 判据（步进单调递减+末档<1% 双条件）；⑧judge_point 门矩阵
（合成 PASS/FAIL/UNKNOWN）；⑨逐档 β 模识别鲁棒性（IntLine 交换重排免疫）；
⑩半模型对照判读；⑪预算与 schema；⑫互斥自排除（#261）。
真机面（HFSS 调用/互斥枚举）一律不在本文件触发。
"""
from __future__ import annotations

import cmath
import json
import math
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for _p in (SRC, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hfss_kj_even_sweep as kjs
from hfss_kj_even_sweep import (
    BASIS_LATTICE,
    KJ_DOMAIN,
    LEVELS,
    POINTS,
    READ_CHAR_IMP,
    SINGLE_LINE_FACTOR,
    _cx,
    _filter_self_pids,
    basis_confirm,
    budget_estimate,
    build_point_plan,
    eps_envelope,
    extrap_inv_w,
    identify_modes,
    judge_half_model,
    judge_point,
    kj_anchor,
    mode_pair,
    mode_scalars,
    point_geom,
    port_widths,
    record_schema,
    single_line_ohm,
    unwrap_gl,
    z0_from_gamma,
)

K0 = 2.0 * math.pi * 2.5e9 / 299792458.0
L_M = 0.030


# ── ① 点表 / KJ 锚 / 转写钉 ──────────────────────────────────────────────


def test_points_mm_values_hard_converted_from_uh():
    y1 = next(p for p in POINTS if p["tag"] == "y1")
    assert y1["w_mm"] == pytest.approx(1.8195 * 0.508, abs=5e-7)
    assert y1["s_mm"] == pytest.approx(0.1614 * 0.508, abs=5e-7)
    edge_a = next(p for p in POINTS if p["tag"] == "edge_a")
    assert edge_a["w_mm"] == pytest.approx(0.1 * 0.508, abs=5e-7)
    edge_b = next(p for p in POINTS if p["tag"] == "edge_b")
    assert edge_b["w_mm"] == pytest.approx(10.0 * 0.508, abs=5e-7)
    for p in POINTS:
        assert p["w_mm"] > 0 and p["s_mm"] > 0
        assert set(p) >= {"tag", "u", "g", "w_mm", "s_mm", "in_domain", "note"}


def test_points_domain_flags_match_kj_box():
    lo_u, hi_u, lo_g, hi_g = KJ_DOMAIN
    for p in POINTS:
        inside = (lo_u <= p["u"] <= hi_u) and (lo_g <= p["g"] <= hi_g)
        assert p["in_domain"] is inside, p["tag"]
    tags = {p["tag"] for p in POINTS}
    assert {"y1", "lange", "cline6", "bpf", "edge_a", "edge_b", "edge_c"} <= tags
    assert sum(p["in_domain"] for p in POINTS) == 4


def test_kj_anchor_p1_transcription_pin_bitwise():
    """P1 记录锚（4 位缩写几何）必须逐位复现——消费链未漂移的证据钉。"""
    kj = kj_anchor(0.9243, 0.0820)
    assert kj["z0e_ohm"] == 69.37088231385582
    assert kj["z0o_ohm"] == 36.03866991398955


def test_kj_anchor_y1_point_values():
    kj = kj_anchor(0.924306, 0.081991)
    assert kj["z0e_ohm"] == pytest.approx(69.3708, abs=1e-3)
    assert kj["z0o_ohm"] == pytest.approx(36.0379, abs=1e-3)
    assert kj["eps_eff_e"] == pytest.approx(2.99216, abs=1e-4)
    assert kj["z0e_ohm"] > kj["z0o_ohm"] > 0


def test_kj_anchor_all_points_sane_and_inside_envelope():
    for p in POINTS:
        kj = kj_anchor(p["w_mm"], p["s_mm"])
        env = eps_envelope(p["w_mm"], p["s_mm"])
        assert kj["z0e_ohm"] > kj["z0o_ohm"] > 0
        assert env[0] < env[1]
        assert env[0] <= kj["eps_eff_e"] <= env[1], p["tag"]


def test_eps_envelope_y1_matches_p1_numbers():
    env = eps_envelope(0.924306, 0.081991)
    assert env[0] == pytest.approx(2.8161, abs=1e-3)
    assert env[1] == pytest.approx(3.0241, abs=1e-3)


def test_point_geom_and_port_widths():
    geom = point_geom(0.924306, 0.081991)
    w0, w1, w2 = geom["port_w_mm"]
    assert w0 == pytest.approx(2 * 0.924306 + 0.081991 + 20 * 0.508, abs=1e-6)
    assert w1 == pytest.approx(1.5 * w0, abs=1e-6)
    assert w2 == pytest.approx(2.0 * w0, abs=1e-6)
    assert geom["air_x_half_mm"] == pytest.approx(w2 / 2 + 2 * 0.508, abs=1e-9)
    assert geom["xa_mm"] < 0 < geom["xb_mm"]
    assert geom["lossless"] is True
    assert port_widths(0.924306, 0.081991) == (w0, w1, w2)


def test_build_point_plan_schema_and_solves():
    plan = build_point_plan(POINTS[0])
    assert plan["solves_per_point"] == len(LEVELS) + 2   # 3 阶梯 + 2 宽度档
    assert plan["kj"]["z0e_ohm"] > 0
    assert len(plan["eps_envelope"]) == 2
    assert json.dumps(plan)   # JSON 可序列化


def test_read_char_imp_is_zvi_v2_declaration():
    """v2 直读定义预声明钉（criteria v2 §一.2：准 TEM 等效口径）。"""
    assert READ_CHAR_IMP == "Zvi"


# ── ② 模识别 / γL 解缠 / Γ 反演（合成回收 #118）───────────────────────────


def test_identify_modes_by_beta():
    even_if_beta_high = identify_modes({1: 80 + 90j, 2: 5 + 82j})
    assert even_if_beta_high == (1, 2)
    swapped = identify_modes({1: 5 + 82j, 2: 80 + 90j})
    assert swapped == (2, 1)
    with pytest.raises(ValueError):
        identify_modes({1: 1j})


def test_mode_pair_per_level_and_missing_readings():
    """逐档 β 识别（v2 §一.4）：同一函数对任意档独立可用；Γ 缺失→None。"""
    lv = {"port_data": {"P1": {"Gamma": {
        "1": {"re": 0.0, "im": 80.0}, "2": {"re": 0.0, "im": 82.0}}}}}
    assert mode_pair(lv) == (2, 1)
    assert mode_pair({"port_data": {"P1": {}}}) is None
    assert mode_pair(None) is None


def test_unwrap_gl_branch_resolution():
    beta = K0 * math.sqrt(2.99)
    gl_true = complex(0.01, beta * L_M)
    t = cmath.exp(-gl_true)
    # -log 的主值分支把相位卷绕后仍须被 β 直读拉回
    assert unwrap_gl(t, beta, L_M) == pytest.approx(gl_true, abs=1e-9)


def test_z0_from_gamma_recovers_synthetic_line():
    """合成已知量回收：Z0=69.37、Zr=67（端口读数偏离 ~3%）、γ 已知 →
    反演须精确回收 Z0；不带 e^{2γL} 修正的捷径值须可见偏离（证明修正必要）。"""
    z0_true, zr = 69.37, 67.0
    beta = K0 * math.sqrt(2.99)
    gl = complex(0.01, beta * L_M)
    rho = (zr - z0_true) / (zr + z0_true)
    gamma_in = rho * cmath.exp(-2.0 * gl)
    out = z0_from_gamma(zr, gamma_in, gl)
    assert abs(out["z0"]) == pytest.approx(z0_true, rel=1e-10)
    assert out["rho_load"] == pytest.approx(rho, abs=1e-12)
    assert abs(out["z0_naive"] - z0_true) / z0_true > 1e-4


def test_z0_from_gamma_reference_invariance_crosscheck_basis():
    """互证门/基准确认门的数学基础：同一物理线、不同参考阻抗读数 →
    反演不变性（criteria v2 门 2/B）。"""
    z0_true = 69.37
    beta = K0 * math.sqrt(2.99)
    gl = complex(0.005, beta * L_M)
    rec = []
    for zr in (69.0, 70.5, 68.2):   # 假想不同基准读数
        rho = (zr - z0_true) / (zr + z0_true)
        gamma_in = rho * cmath.exp(-2.0 * gl)
        rec.append(abs(z0_from_gamma(zr, gamma_in, gl)["z0"]))
    assert max(rec) - min(rec) < 1e-8 * z0_true
    with pytest.raises(ValueError):
        z0_from_gamma(69.0, -1 + 0j, 0j)   # Γ_in≈−1 退化显式报错


# ── ③ 基准确认门 / 单线基准换算（#307 显式化，v2 §一.3/门 B）──────────────


def test_single_line_conversion_factors():
    """模基→KJ 单线基准换算因子（解析：even 端口电流=2×单线电流、
    odd 端口电压=2×单线电压）。"""
    assert SINGLE_LINE_FACTOR == {"even": 2.0, "odd": 0.5}
    # y1 KJ 锚的算术恒等（换算口径自洽，非门数字）
    assert single_line_ohm(69.3708 / 2, "even") == pytest.approx(69.3708, abs=1e-9)
    assert single_line_ohm(36.0379 * 2, "odd") == pytest.approx(36.0379, abs=1e-9)
    with pytest.raises(KeyError):
        single_line_ohm(50.0, "common")


def test_basis_confirm_lattice_membership():
    """route_ratio 必须落格点 {1.0, 0.5, 2.0}（±2%）；检出 0.5/2.0 = 路间
    基准因子差（#307）→ 换算后采信；不在格点（0.7）= 测量面无效。"""
    ok1 = basis_confirm(101.0, 100.0)          # ratio 1.01 → 格点 1.0
    assert ok1["ok"] is True and ok1["factor"] == 1.0
    edge_in = basis_confirm(101.9, 100.0)      # ratio 1.019 → 容差内
    assert edge_in["ok"] is True and edge_in["factor"] == 1.0
    edge_out = basis_confirm(102.1, 100.0)     # ratio 1.021 → 恰出 2% 容差
    assert edge_out["ok"] is False
    ok_half = basis_confirm(50.5, 100.0)       # ratio 0.505 → 格点 0.5
    assert ok_half["factor"] == 0.5 and ok_half["ok"] is True
    ok_two = basis_confirm(202.0, 100.0)       # ratio 2.02 → 格点 2.0
    assert ok_two["factor"] == 2.0 and ok_two["ok"] is True
    off = basis_confirm(103.0, 100.0)          # ratio 1.03 → 偏 3% >2%
    assert off["ok"] is False and off["factor"] == 1.0
    off2 = basis_confirm(70.0, 100.0)          # ratio 0.70 → 不在格点
    assert off2["ok"] is False
    assert basis_confirm(None, 100.0)["ok"] is None
    assert basis_confirm(50.0, 0.0)["ok"] is None


def test_basis_confirm_lattice_constant():
    assert BASIS_LATTICE == (1.0, 0.5, 2.0)


# ── ④ mode_scalars（合成档）──────────────────────────────────────────────


def _synth_level(*, z0e: float, eps_e: float, z0o: float, eps_o: float,
                 zr_e: float | None = None, zr_o: float | None = None,
                 gl_e: complex, gl_o: complex, label: str,
                 char_imp: str = "Zvi", read_bias: float = 0.002,
                 swap_slots: bool = False, max_delta_s: float = 0.005,
                 max_passes: int = 24, converged: bool = True,
                 passes: int = 15, cross: float = 1e-4) -> dict:
    """合成 HFSS 单档读数（JSON 形态，模键=str；v2 测量架构口径）。

    物理口径：模线阻抗 z0m（该模行波阻抗）；直读 zr=端口 Zo 读数=
    z0m·(1+read_bias)（renormalize=False 下 S 参考基与直读同源，
    read_bias=读数链噪声）；Γ_in=ρ·e^{−2γL}，ρ=(zr−z0m)/(zr+z0m)；
    T=e^{−γL}；εeff 经 β=gl.imag/L 进 Gamma 读数（eps_e/eps_o 为语义注记，
    实值由 gl_e/gl_o 携带）。显式传 zr_e/zr_o 时按基准错位合成（基准确认
    门用例）。swap_slots=True：物理 even 落模槽 "2"/odd 落 "1"（逐档识别
    鲁棒性用例）。
    """
    if zr_e is None:
        zr_e = z0e * (1.0 + read_bias)
    if zr_o is None:
        zr_o = z0o * (1.0 + read_bias)
    level: dict = {"label": label, "max_delta_s": max_delta_s,
                   "max_passes": max_passes, "char_imp": char_imp,
                   "converged": converged, "delta_s_final": 0.003,
                   "passes": passes, "hit_max_passes": False, "errors": [],
                   "port_data": {}, "s_data": {}}
    zr_by = {"1": zr_o if swap_slots else zr_e,
             "2": zr_e if swap_slots else zr_o}
    gl_by = {"1": gl_o if swap_slots else gl_e,
             "2": gl_e if swap_slots else gl_o}
    z0m_by = {"1": z0o if swap_slots else z0e,
              "2": z0e if swap_slots else z0o}
    for pn in ("P1", "P2"):
        level["port_data"][pn] = {
            "Zo": {m: {"re": zr_by[m], "im": 0.0} for m in ("1", "2")},
            # HFSS port Gamma 读数=该模传播常数 γ（/m）＝γL/L
            "Gamma": {m: {"re": gl_by[m].real / L_M, "im": gl_by[m].imag / L_M}
                      for m in ("1", "2")},
        }
    for m in ("1", "2"):
        zr, z0m, glm = zr_by[m], z0m_by[m], gl_by[m]
        rho = (zr - z0m) / (zr + z0m)
        gamma_in = rho * cmath.exp(-2.0 * glm)
        t = cmath.exp(-glm)
        level["s_data"][f"S(P1:{m},P1:{m})"] = {
            "re": gamma_in.real, "im": gamma_in.imag}
        level["s_data"][f"S(P2:{m},P2:{m})"] = {
            "re": gamma_in.real, "im": gamma_in.imag}
        level["s_data"][f"S(P2:{m},P1:{m})"] = {"re": t.real, "im": t.imag}
        level["s_data"][f"S(P1:{m},P2:{m})"] = {"re": t.real, "im": t.imag}
    me_slot, mo_slot = ("2", "1") if swap_slots else ("1", "2")
    level["s_data"][f"S(P2:{mo_slot},P1:{me_slot})"] = {"re": cross, "im": 0.0}
    level["s_data"][f"S(P2:{me_slot},P1:{mo_slot})"] = {"re": cross, "im": 0.0}
    level["s_data"][f"S(P1:{mo_slot},P1:{me_slot})"] = {"re": cross, "im": 0.0}
    return level


def test_mode_scalars_recovers_synthetic():
    z0e, eps_e = 69.37, 2.99
    beta = K0 * math.sqrt(eps_e)
    gl = complex(0.01, beta * L_M)
    zr = 67.0
    lv = _synth_level(z0e=z0e, eps_e=eps_e, z0o=36.0, eps_o=2.47,
                      zr_e=zr, zr_o=35.0, gl_e=gl,
                      gl_o=complex(0.01, K0 * math.sqrt(2.47) * L_M),
                      label="W0")
    sc = mode_scalars(lv, 1, L_M)
    assert sc is not None
    assert abs(sc["z0"]) == pytest.approx(z0e, rel=1e-9)
    assert sc["z_direct"] == pytest.approx(zr, rel=1e-12)   # v2 直读量在列
    assert sc["eps_gamma"] == pytest.approx(eps_e, rel=1e-12)
    assert sc["eps_s"] == pytest.approx(eps_e, rel=1e-9)
    assert sc["eps_route_rel"] < 1e-8
    assert abs(sc["z0_naive"] - z0e) / z0e > 1e-4
    assert mode_scalars({"port_data": {}, "s_data": {}}, 1, L_M) is None


# ── ⑤ 外推 ───────────────────────────────────────────────────────────────


def test_extrap_inv_w_exact_on_linear_family():
    ws = [12.0, 18.0, 24.0]
    z_inf_true = 69.5
    a = -3.0
    vals = [z_inf_true + a / w for w in ws]
    out = extrap_inv_w(ws, vals)
    assert out["z_inf"] == pytest.approx(z_inf_true, rel=1e-10)
    assert out["monotone"] is True
    assert out["rel_last2"] < 0.003
    assert out["valid"] is True


def test_extrap_inv_w_validity_gates():
    # 末两档差 0.5% > 0.3% → 无效
    out = extrap_inv_w([12.0, 18.0, 24.0], [70.0, 69.7, 69.35])
    assert out["rel_last2"] == pytest.approx(0.35 / 69.35, abs=1e-6)
    assert out["rel_last2"] > 0.003
    assert out["valid"] is False
    # 非单调（回折）→ 无效
    out2 = extrap_inv_w([12.0, 18.0, 24.0], [70.0, 69.2, 69.35])
    assert out2["monotone"] is False
    assert out2["valid"] is False
    # 两档、末差达标 → 有效（无单调证据不因缺证而否）
    out3 = extrap_inv_w([18.0, 24.0], [69.2, 69.06])
    assert out3["monotone"] is None
    assert out3["valid"] is True
    with pytest.raises(ValueError):
        extrap_inv_w([12.0], [70.0])


# ── ⑥ judge_point 门矩阵（合成，v2 门名/判据）────────────────────────────

Y1 = next(p for p in POINTS if p["tag"] == "y1")


def _base_rec(dev_by_rung=(0.02, 0.008, 0.003), dev_odd=0.002,
              eps_dev=0.004, conv_ok=True, read_bias=0.002,
              ladder_steps=(0.0020, 0.0009, 0.0004),
              swap_slots: bool = False):
    """合成 y1 点完整记录（默认全门可 PASS：最宽档残差 ~0.5%≤1%）。

    ladder_steps=ΔS 阶梯三档的模阻抗相对偏移序列（gate0 v2 步进观测面）；
    swap_slots=True 时物理 even 落模槽 "2"（逐档 β 识别鲁棒性用例）。
    """
    kj = kj_anchor(Y1["w_mm"], Y1["s_mm"])
    env = eps_envelope(Y1["w_mm"], Y1["s_mm"])
    geom = point_geom(Y1["w_mm"], Y1["s_mm"])
    z0e_kj, z0o_kj = kj["z0e_ohm"], kj["z0o_ohm"]
    levels = []
    for i, (ds, mp) in enumerate(LEVELS):
        step = ladder_steps[i]
        gl_e = complex(0.01, K0 * math.sqrt(kj["eps_eff_e"] * (1 + eps_dev + step / 2)) * L_M)
        gl_o = complex(0.01, K0 * math.sqrt(kj["eps_eff_o"]) * L_M)
        levels.append(_synth_level(
            # 模基线阻抗：even=单线之半、odd=单线之倍（#307 口径，criteria v2
            # §一.3）——主判消费 single_line_ohm(z_direct) 后回到 KJ 单线值
            z0e=z0e_kj * (1 + dev_by_rung[0] + step) / 2.0,
            eps_e=kj["eps_eff_e"] * (1 + eps_dev + step / 2),
            z0o=z0o_kj * (1 + dev_odd + step) * 2.0,
            eps_o=kj["eps_eff_o"], gl_e=gl_e, gl_o=gl_o, label="W0",
            read_bias=read_bias, swap_slots=swap_slots, max_delta_s=ds,
            max_passes=mp, converged=conv_ok, passes=mp - 2))
    # 宽度档（dev 递减、单调趋缓；eps 随档位线性内插）
    width_runs = []
    for i in (1, 2):
        gl_e = complex(0.01, K0 * math.sqrt(
            kj["eps_eff_e"] * (1 + eps_dev * (1 - 0.3 * i))) * L_M)
        gl_o = complex(0.01, K0 * math.sqrt(kj["eps_eff_o"]) * L_M)
        width_runs.append(_synth_level(
            z0e=z0e_kj * (1 + dev_by_rung[i]) / 2.0,
            eps_e=kj["eps_eff_e"] * (1 + eps_dev * (1 - 0.3 * i)),
            z0o=z0o_kj * (1 + dev_odd) * 2.0, eps_o=kj["eps_eff_o"],
            gl_e=gl_e, gl_o=gl_o, label=f"W{i}", read_bias=read_bias,
            swap_slots=swap_slots))
    return {"tag": "y1", "point": {"in_domain": True}, "geom": geom, "kj": kj,
            "eps_envelope": list(env), "levels": levels,
            "width_runs": width_runs, "mode_map": {"even": 1, "odd": 2}}


def test_judge_point_synthetic_pass():
    out = judge_point(_base_rec())
    assert out["verdict"] == "PASS", json.dumps(out, indent=1)[:1200]
    g = out["gates"]
    assert "gate2_charimp_triple" not in g      # v1 门已撤销（criteria v2）
    assert g["gate2_modal_crosscheck"]["ok"] is True
    assert g["gate_basis_confirm"]["ok"] is True
    assert g["gate_basis_confirm"]["modes"]["even"]["factor"] == 1.0
    assert g["gate0_convergence"]["ok"] is True
    assert g["gate4_even_main"]["route"] == "widest_rung"
    assert g["gate3_odd_control"]["ok"] is True
    assert g["gate5_eps_envelope"]["ok"] is True
    # #307 单线换算证据落档（criteria v2 §一.3/门 B）
    conv = g["gate_basis_confirm"]["single_line_conversion"]
    assert conv["factors"] == {"even": 2.0, "odd": 0.5}
    assert conv["modes"]["even"]["z_direct_single"] == pytest.approx(
        conv["modes"]["even"]["z_direct_modal"] * 2.0, rel=1e-12)
    assert conv["modes"]["odd"]["z_direct_single"] == pytest.approx(
        conv["modes"]["odd"]["z_direct_modal"] * 0.5, rel=1e-12)


def test_judge_point_gate0_v2_monotone_and_last_step():
    """gate0 v2 双条件：默认阶梯（步进单调降、末档 <1%）过；
    步进回升（越改越差）即使末档 <1% 也 fail-closed。"""
    out = judge_point(_base_rec())
    g0 = out["gates"]["gate0_convergence"]
    assert g0["ok"] is True
    assert g0["steps"]["even_z0"][1] < g0["steps"]["even_z0"][0]
    # 阶梯反序 → s2 > s1（单调性破坏），末档仍 <1% → gate0 False → UNKNOWN
    rec = _base_rec(ladder_steps=(0.0004, 0.0009, 0.0020))
    out2 = judge_point(rec)
    g0b = out2["gates"]["gate0_convergence"]
    assert g0b["steps"]["even_z0"][1] > g0b["steps"]["even_z0"][0]
    assert g0b["steps"]["even_z0"][1] <= 0.01
    assert g0b["ok"] is False
    assert out2["verdict"] == "UNKNOWN"


def test_judge_point_gate0_v2_last_step_above_1pct():
    """步进单调降但末档 1.4%>1% → gate0 False（双条件的第二支）。"""
    rec = _base_rec(ladder_steps=(0.0, 0.030, 0.0446))
    out = judge_point(rec)
    g0 = out["gates"]["gate0_convergence"]
    s = g0["steps"]["even_z0"]
    assert s[1] < s[0]                      # 单调降成立
    assert s[1] > 0.01                      # 末档 >1%
    assert g0["ok"] is False
    assert out["verdict"] == "UNKNOWN"


def test_judge_point_crosscheck_fail_is_unknown():
    """直读-反演互证越 2%（W2 档反演路线注入 ~3% 偏移，W0 基准正常检出
    1.0）→ 门 2 False → 测量面无效 → UNKNOWN（先修再判，非 FAIL）。"""
    rec = _base_rec()
    lv = rec["width_runs"][-1]
    gl = lv["port_data"]["P1"]["Gamma"]["1"]   # 用该档自身 γ（消 e^{2γL} 旋转）
    glm = complex(gl["re"] * L_M, gl["im"] * L_M)
    s11 = -0.015 * cmath.exp(-2.0 * glm)   # x=−0.015 → z_inv=1.03046×z直读
    lv["s_data"]["S(P1:1,P1:1)"] = {"re": s11.real, "im": s11.imag}
    out = judge_point(rec)
    g2 = out["gates"]["gate2_modal_crosscheck"]
    assert g2["ok"] is False
    assert g2["entries"]["W2:even"]["route_rel_pct"] == pytest.approx(3.05, abs=0.05)
    assert out["gates"]["gate_basis_confirm"]["ok"] is True   # W0 基准正常
    assert out["verdict"] == "UNKNOWN"
    assert "gate2_modal_crosscheck" in out["unknown"]


def test_judge_point_basis_factor_two_conversion_recorded():
    """路间基准因子 2.0（#307）：直读=真模值、S11 按 x=−1/3 合成使反演回
    2×直读 → route_ratio=2.0 检出 → 互证按换算过、证据落档、主判仍消费直读
    换算单线值（不被路间因子阻断）。"""
    kj = kj_anchor(Y1["w_mm"], Y1["s_mm"])
    rec = _base_rec()
    # 与 _base_rec 的阶梯/宽度偏移同构（保 gate0 步进序列）
    devs = (0.022, 0.0209, 0.0204, 0.008, 0.003)
    for lv, dev in zip(rec["levels"] + rec["width_runs"], devs, strict=True):
        gl = lv["port_data"]["P1"]["Gamma"]["1"]   # 该档自身 γ
        glm = complex(gl["re"] * L_M, gl["im"] * L_M)
        z_half = kj["z0e_ohm"] * (1 + dev) / 2.0   # = 该档 even 模线阻抗
        s11 = (-1.0 / 3.0) * cmath.exp(-2.0 * glm)  # x=−1/3 → z_inv=2×z直读
        lv["port_data"]["P1"]["Zo"]["1"] = {"re": z_half, "im": 0.0}
        lv["port_data"]["P2"]["Zo"]["1"] = {"re": z_half, "im": 0.0}
        lv["s_data"]["S(P1:1,P1:1)"] = {"re": s11.real, "im": s11.imag}
        lv["s_data"]["S(P2:1,P2:1)"] = {"re": s11.real, "im": s11.imag}
    out = judge_point(rec)
    gB = out["gates"]["gate_basis_confirm"]
    assert gB["modes"]["even"]["ok"] is True
    assert gB["modes"]["even"]["factor"] == 2.0
    assert gB["modes"]["even"]["route_ratio"] == pytest.approx(2.0, abs=1e-9)
    assert out["gates"]["gate2_modal_crosscheck"]["ok"] is True
    assert gB["single_line_conversion"]["modes"]["even"]["route_factor"] == 2.0
    # 主判（直读基）不受路间因子影响：W2 残差仍 ~0.5% → widest_rung PASS
    assert out["gates"]["gate4_even_main"]["route"] == "widest_rung"
    assert out["verdict"] == "PASS", json.dumps(out, indent=1)[:1200]


def test_judge_point_basis_off_lattice_is_unknown():
    """route_ratio=0.7（不在格点）→ 门 B False → 测量面无效 → UNKNOWN。"""
    kj = kj_anchor(Y1["w_mm"], Y1["s_mm"])
    rec = _base_rec()
    devs = (0.02, 0.02, 0.02, 0.008, 0.003)
    for lv, dev in zip(rec["levels"] + rec["width_runs"], devs, strict=True):
        gl = lv["port_data"]["P1"]["Gamma"]["1"]   # 该档自身 γ
        glm = complex(gl["re"] * L_M, gl["im"] * L_M)
        z0m = kj["z0e_ohm"] * (1 + dev)
        zr = z0m / 0.7                       # → 反演回收 z0m，rr=0.7
        rho = (zr - z0m) / (zr + z0m)
        s11 = rho * cmath.exp(-2.0 * glm)
        lv["port_data"]["P1"]["Zo"]["1"] = {"re": zr, "im": 0.0}
        lv["port_data"]["P2"]["Zo"]["1"] = {"re": zr, "im": 0.0}
        lv["s_data"]["S(P1:1,P1:1)"] = {"re": s11.real, "im": s11.imag}
        lv["s_data"]["S(P2:1,P2:1)"] = {"re": s11.real, "im": s11.imag}
    out = judge_point(rec)
    gB = out["gates"]["gate_basis_confirm"]
    assert gB["modes"]["even"]["ok"] is False
    assert gB["modes"]["even"]["route_ratio"] == pytest.approx(0.7, abs=1e-9)
    assert out["verdict"] == "UNKNOWN"
    assert "gate_basis_confirm" in out["unknown"]


def test_judge_point_even_fail_no_extrap_rescue():
    # 最宽档 3% 且三档平坦（外推无单调证据、末两档差 0）→ 门 4 FAIL
    out = judge_point(_base_rec(dev_by_rung=(0.03, 0.03, 0.03)))
    assert out["gates"]["gate4_even_main"]["ok"] is False
    assert out["verdict"] == "FAIL"
    assert "gate4_even_main" in out["failed"]


def test_judge_point_even_pass_via_extrapolation():
    # 最宽档 ~1.2%（含读数链噪声）>1% → 末两档差 0.2% ≤0.3% 且单调 →
    # 外推有效 ≤1%
    rec = _base_rec(dev_by_rung=(0.020, 0.012, 0.010))
    kj = rec["kj"]
    vals = [kj["z0e_ohm"] * (1 + d) * 1.002 for d in (0.020, 0.012, 0.010)]
    ex = extrap_inv_w(list(rec["geom"]["port_w_mm"]), vals)
    assert ex["valid"] is True
    assert abs(abs(ex["z_inf"]) - kj["z0e_ohm"]) / kj["z0e_ohm"] <= 0.01
    out = judge_point(rec)
    assert out["gates"]["gate4_even_main"]["route"] == "extrap_inv_w"
    assert out["verdict"] == "PASS", json.dumps(out, indent=1)[:1200]


def test_judge_point_odd_control_fail():
    out = judge_point(_base_rec(dev_odd=0.02))
    assert out["gates"]["gate3_odd_control"]["ok"] is False
    assert out["verdict"] == "FAIL"


def test_judge_point_envelope_violation_is_fail():
    # εeff_e 压到包络下界以下（P1 病灶方向：更多场留空气 → εeff 偏低；
    # eps 经 gl_e 全档等偏 → W2 档同样越界）
    kj = kj_anchor(Y1["w_mm"], Y1["s_mm"])
    env = eps_envelope(Y1["w_mm"], Y1["s_mm"])
    rec = _base_rec(eps_dev=-0.16)
    assert kj["eps_eff_e"] * (1 - 0.16 * 0.4) < env[0]   # W2 档确在包络外
    out = judge_point(rec)
    assert out["gates"]["gate5_eps_envelope"]["ok"] is False
    assert out["verdict"] == "FAIL"


def test_judge_point_missing_w2_is_unknown():
    rec = _base_rec()
    rec["width_runs"] = rec["width_runs"][:1]   # 只剩 W1
    out = judge_point(rec)
    assert out["verdict"] == "UNKNOWN"
    assert "gate4_even_main" in out["unknown"]


def test_judge_point_unconverged_is_unknown():
    rec = _base_rec()
    rec["levels"][-1]["converged"] = False
    out = judge_point(rec)
    assert out["gates"]["gate0_convergence"]["ok"] is False
    assert out["verdict"] == "UNKNOWN"


def test_judge_point_unknown_dominates_fail_failclosed():
    """门 0 未饱和 + 门 5 解坏并存 → UNKNOWN 优先（读数不可信不判 FAIL）。"""
    rec = _base_rec()
    env = eps_envelope(Y1["w_mm"], Y1["s_mm"])
    rec["levels"][-1]["converged"] = False
    # W2 档 even 模 Γ 压到包络下界以下（β 走低 → εeff 走低，P1 病灶方向）
    beta_bad = K0 * math.sqrt(env[0] - 0.1)
    rec["width_runs"][-1]["port_data"]["P1"]["Gamma"]["1"] = {
        "re": 0.0, "im": beta_bad}
    out = judge_point(rec)
    assert out["gates"]["gate0_convergence"]["ok"] is False
    assert out["gates"]["gate5_eps_envelope"]["ok"] is False
    assert out["verdict"] == "UNKNOWN"


def test_judge_point_out_of_domain_informational():
    rec = _base_rec()
    rec["point"]["in_domain"] = False
    out = judge_point(rec)
    assert out["verdict"] == "PASS"
    assert out["informational"] is True
    assert out["info_within_2pct"] is True


def test_judge_point_mode_purity_fail():
    rec = _base_rec()
    for lv in [rec["levels"][-1]] + rec["width_runs"]:
        lv["s_data"]["S(P2:2,P1:1)"] = {"re": 0.05, "im": 0.0}
    out = judge_point(rec)
    assert out["gates"]["gate1_mode_purity"]["ok"] is False
    assert out["verdict"] == "FAIL"


def test_judge_point_symmetry_fail():
    rec = _base_rec()
    lv = rec["levels"][-1]
    lv["s_data"]["S(P2:1,P2:1)"] = {"re": 0.05, "im": 0.0}
    out = judge_point(rec)
    assert out["gates"]["gate7_symmetry"]["ok"] is False
    assert out["verdict"] == "FAIL"


def test_judge_point_mode_readings_missing_is_unknown():
    rec = _base_rec()
    rec["levels"] = []
    rec["width_runs"] = []
    out = judge_point(rec)
    assert out["verdict"] == "UNKNOWN"
    assert out["reason"] == "模序识别读数缺失"


def test_judge_point_swap_slots_identified_per_level():
    """IntLine 交换后解算器模号重排免疫（v2 §一.4）：物理 even 落模槽 2，
    逐档 β 识别正确归属 → 判读结论与不换槽一致。"""
    ref = judge_point(_base_rec())
    out = judge_point(_base_rec(swap_slots=True))
    assert out["mode_map"] == {"even": 2, "odd": 1}
    assert out["verdict"] == "PASS", json.dumps(out, indent=1)[:1200]
    assert out["gates"]["gate4_even_main"]["z0e_by_rung"] == \
        ref["gates"]["gate4_even_main"]["z0e_by_rung"]
    assert out["gates"]["gate3_odd_control"]["entries"] == \
        ref["gates"]["gate3_odd_control"]["entries"]


# ── ⑦ 半模型对照判读 ─────────────────────────────────────────────────────


def test_judge_half_model_ladder():
    kj = kj_anchor(Y1["w_mm"], Y1["s_mm"])
    z0e = kj["z0e_ohm"]
    devs = (0.03, 0.02, 0.015, 0.012)   # 单调收敛；末两档差 0.3% 边界内
    lv = []
    for w, dev in zip((6.0, 10.0, 15.0, 20.0), devs, strict=True):
        beta = K0 * math.sqrt(kj["eps_eff_e"])
        lv.append(_synth_level(
            z0e=z0e, eps_e=kj["eps_eff_e"], z0o=36.0, eps_o=2.47,
            zr_e=z0e * (1 + dev), zr_o=35.0,
            gl_e=complex(0.01, beta * L_M),
            gl_o=complex(0.01, K0 * math.sqrt(2.47) * L_M),
            label=f"W{w:g}", char_imp="Zpv", max_delta_s=0.005,
            max_passes=20))
    rec = {"kj": kj, "widths_mm": [6.0, 10.0, 15.0, 20.0], "levels": lv}
    out = judge_half_model(rec)
    assert out["ladder_monotone"] is True
    assert out["extrap"]["valid"] is True
    assert out["extrap_dev_pct"] < 1.0
    assert out["verdict"] == "RECORDED"   # 最宽档 dev=1.2%>1% → 记录不判 PASS
    rec2 = {"kj": kj, "widths_mm": [6.0, 10.0, 15.0, 20.0],
            "levels": [dict(x, port_data=json.loads(json.dumps(
                x["port_data"]))) for x in lv]}
    # 最宽档 ≤1% → PASS（直读口径）
    for x, dev in zip(rec2["levels"], (0.008, 0.006, 0.004, 0.002), strict=True):
        x["port_data"]["P1"]["Zo"]["1"] = {"re": z0e * (1 + dev), "im": 0.0}
    out2 = judge_half_model(rec2)
    assert out2["verdict"] == "PASS"


# ── ⑧ 预算 / schema / 互斥自排除 ─────────────────────────────────────────


def test_budget_matches_criteria_v2_declaration():
    b = budget_estimate(7, 5)   # v2：每点 5 解（3 阶梯 + 2 宽度档）
    assert b["n_solves"] == 35
    assert b["core_min"] == [70.0, 175.0]
    assert b["band_min_with_margin"] == [105.0, 262.5]
    assert b["band_h_with_margin"][1] == pytest.approx(4.375)
    half = budget_estimate(1, 6)   # --half-model：1 设计 ×(4 宽度+2 子解)
    assert half["n_solves"] == 6
    assert half["core_min"] == [12.0, 30.0]


def test_record_schema_keys():
    schema = record_schema()
    for key in ("tag", "point", "geom", "kj", "eps_envelope", "mode_map",
                "levels", "width_runs", "gates", "verdict",
                "status", "budget"):
        assert key in schema
    assert "charimp_runs" not in schema   # v1 CharImp 三定义子解已撤销
    assert schema["criteria"] == "runs/df7_kjeven/p2_criteria_v2.md"
    assert schema["verdict"] == "PASS|FAIL|UNKNOWN"


def test_filter_self_pids_excludes_own_chain():
    own, parent = os.getpid(), os.getppid()
    out = _filter_self_pids({own, parent, 12345, 678})
    assert out == {12345, 678}
    assert own not in out and parent not in out


def test_points_tuple_immutable_and_json_safe():
    assert isinstance(POINTS, tuple) and len(POINTS) == 7
    json.dumps(list(POINTS))


def test_cx_json_roundtrip():
    assert _cx({"re": 1.5, "im": -2.0}) == complex(1.5, -2.0)
    assert _cx(None) is None
    assert _cx(3) == complex(3.0)
    assert _cx({"re": "bad"}) is None


def test_rel_helper():
    assert kjs._rel(101.0, 100.0) == pytest.approx(0.01)
    assert kjs._rel(1.0, 0.0) == float("inf")
