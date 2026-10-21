"""架构批 W5-S18 席锚树：在片 ISS 校准两键（iss_standard_response/
iss_oneport_cal_extract）+ 源功率校准一键（source_power_cal_table）。

域边界与 #222 结论（详见 内部证据目录 报告）：
- outphasing/Chireixx=本席边际池件 1，#222 查实**已闭合**（fe-batch1
  2026-09-27 落 core/pa_architectures chireix_* 全函数+service 面+锚测，
  ；R2 审计"仅引注"系误判）且模块 docstring 预声明
  "不进 calculators 注册表（F-E 域内约定，消费者是 service 层）"——
  零改动交付，本文件不涉。
- ISS/源功率校准=真实缺口（#222 triple-grep 零实现零键），本文件为锚树。

数值断言口径（#118 不自证——闭式测试侧独立重解/同仓双源异路线互证/文
献惯例锚，不用自身推导互证自身）：
- ISS 标准件：理想退化 Γ=+1/−1/0、|S21|=10^(−IL/20) 与 τ=l√εeff/c 恒等
  式测试侧独立复算；open 电容解析式独立重算（(1−jx)/(1+jx)）+ 与
  cal_kit_standard_response open 一阶项同仓双源逐位互证（W3 预声明诚实
  边界外的频率多项式面恰为本族域，一阶项重叠区同式）；load 寄生无源性
  |Γ|≤1 逐频断言+独立重算一点。
- 一端口三项：理想标准档（Γ=+1/−1/0）与 core/trl_solt._oneport_three_term
  同仓双源逐位互证（Ed/Es/Er 三项全比）；非理想 ISS 定义档 #118 合成回
  收（已知误差箱→原始测量→提取→回收 ≤1e-12，DUT Γ 回收 ≤1e-12，反解
  回代残差 ≤1e-12）；退化定义组（两标准重合）显式拒绝。
- 源功率校准：交付恒等式 program+offset=p_target 逐位（构造残差=浮点噪
  声）；合成损耗表精确回收（offset=−L、program=p_target+L 独立重解）；
  flat-falling 双读法方向旗标（损耗上升档 offset 非增/program 非降/平坦
  设定档交付下坠）；与 power_cal_chain 链间握手同仓互证（测量端 +缆损
  回补 vs 源端 −offset，互补闭环语义）；u 1:1 传播+U=k=2；源上限触顶
  infeasible 如实不裁剪。
- 守卫族：见 test_physics_invariants DOMAIN_ERROR_CASES 同笔（此处不复
  写，只留描述形态门）。
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.core.trl_solt import _oneport_three_term
from rfauto.service.calculator_service import run_calculator


def _run(name: str, **params: object) -> dict:
    out = run_calculator(name, params)
    assert out["ok"], f"{name} 失败: {out.get('error')!r}"
    return out["result"]


def _fail(name: str, **params: object) -> None:
    out = run_calculator(name, params)
    assert out["ok"] is False and out.get("error"), (
        f"{name}({params}) 应显式拒绝，得到 ok={out.get('ok')!r}")


NEW_KEYS = (
    "iss_standard_response", "iss_oneport_cal_extract",
    "source_power_cal_table")


# ─── 描述形态门（R5 §①：中文名全由 description 自带）────────────────────────

@pytest.mark.parametrize("key", NEW_KEYS)
def test_description_zh_head_form(key: str) -> None:
    spec = CALCULATOR_REGISTRY.get(key)
    head = re.split(r"[：:]", str(spec.description or ""))[0].strip()
    assert head and re.search(r"[\u4e00-\u9fff]", head)
    assert len(head) <= 24, f"{key} 中文名超 24 字符: {head!r}"


# ─── ISS 标准件响应：恒等式+解析+同仓双源 ─────────────────────────────────────

class TestIssStandardResponse:
    def test_ideal_limits_bitwise(self):
        """理想退化档：open Γ=+1、short Γ=−1、load Γ=0、thru S21=1 逐位。"""
        freqs = [1.0, 5.0, 10.0, 26.5]
        ro = _run("iss_standard_response", standard_type="open",
                  freq_ghz=freqs)
        rs = _run("iss_standard_response", standard_type="short",
                  freq_ghz=freqs)
        rl = _run("iss_standard_response", standard_type="load",
                  freq_ghz=freqs)
        rt = _run("iss_standard_response", standard_type="thru",
                  freq_ghz=freqs)
        for i in range(len(freqs)):
            assert ro["gamma_re"][i] == 1.0 and ro["gamma_im"][i] == 0.0
            assert rs["gamma_re"][i] == -1.0 and rs["gamma_im"][i] == 0.0
            assert rl["gamma_re"][i] == 0.0 and rl["gamma_im"][i] == 0.0
            assert rt["s21_re"][i] == 1.0 and rt["s21_im"][i] == 0.0

    def test_open_cap_analytic_and_w3_cross_source(self):
        """open 电容：解析式 (1−jx)/(1+jx) 独立重算 + 与
        cal_kit_standard_response（同轴机械件同式一阶项）逐位互证。"""
        freqs = [1.0, 10.0]
        cap = [12.0, 0.5, 0.0, 0.0]
        out = _run("iss_standard_response", standard_type="open",
                   freq_ghz=freqs, cap_poly_ff=cap)
        for i, f in enumerate(freqs):
            c_ff = cap[0] + cap[1] * f
            x = 2.0 * math.pi * f * 1e9 * (c_ff * 1e-15) * 50.0
            g = complex(1.0, -x) / complex(1.0, x)
            got = complex(out["gamma_re"][i], out["gamma_im"][i])
            assert abs(got - g) <= 1e-14, (f, got, g)
            # 同仓双源：C_f 等值给 W3 键（其 open 同式）→ 逐位（圆整窗）
            w3o = _run("cal_kit_standard_response", standard_type="open",
                       freq_ghz=[f], open_cap_ff=c_ff)
            gw3 = complex(w3o["response_re"][0], w3o["response_im"][0])
            assert abs(got - gw3) <= 1e-13, (f, got, gw3)
            # 有效电容回显=多项式代入值（恒等）
            assert out["cap_eff_ff"][i] == c_ff

    def test_short_ind_load_lc_independent(self):
        """short 电感解析重算；load 寄生 LC 一点独立重算+无源性逐频。"""
        f0 = 10.0
        l_ph = 15.0
        out = _run("iss_standard_response", standard_type="short",
                   freq_ghz=[f0], ind_poly_ph=[l_ph, 0.0, 0.0, 0.0])
        zl = 1j * 2.0 * math.pi * f0 * 1e9 * (l_ph * 1e-12)
        g_ref = (zl - 50.0) / (zl + 50.0)
        got = complex(out["gamma_re"][0], out["gamma_im"][0])
        assert abs(got - g_ref) <= 1e-14
        # |Γ|=1（纯电抗反射）且相位=180°−2·atan(ωL/Z0)（文献口径独立式）
        assert abs(out["gamma_mag"][0] - 1.0) <= 1e-12
        phase_dev = -2.0 * math.atan(zl.imag / 50.0)
        assert abs((math.atan2(got.imag, got.real) - math.pi)
                   - phase_dev) <= 1e-12

        freqs = [2.0, 8.0, 20.0]
        out_l = _run("iss_standard_response", standard_type="load",
                     freq_ghz=freqs, load_r_ohm=50.0, load_l_ph=20.0,
                     load_c_ff=8.0)
        for i, f in enumerate(freqs):
            om = 2.0 * math.pi * f * 1e9
            z = 1j * om * 20e-12 + 50.0 / complex(1.0, om * 50.0 * 8e-15)
            g_ref = (z - 50.0) / (z + 50.0)
            got = complex(out_l["gamma_re"][i], out_l["gamma_im"][i])
            assert abs(got - g_ref) <= 1e-13, (f, got, g_ref)
            assert out_l["gamma_mag"][i] <= 1.0 + 1e-12  # 无源性

    def test_thru_identity_and_delay(self):
        """thru：|S21|=10^(−IL/20) 与 τ=l√εeff/c 恒等式独立重算。"""
        f0, l_mm, eps, loss = 18.0, 3.2, 2.9, 0.15
        out = _run("iss_standard_response", standard_type="thru",
                   freq_ghz=[f0], length_mm=l_mm, eps_eff=eps,
                   loss_db_per_mm=loss)
        il = loss * l_mm
        s21 = complex(out["s21_re"][0], out["s21_im"][0])
        assert abs(abs(s21) - 10.0 ** (-il / 20.0)) <= 1e-12
        # 实部=10^(−IL/20)cos(βl)、虚部=−…sin(βl)（独立重算）
        beta_l = 2.0 * math.pi * f0 * 1e9 * math.sqrt(eps) \
            * (l_mm * 1e-3) / 299792458.0
        ref = 10.0 ** (-il / 20.0) * complex(math.cos(beta_l),
                                             -math.sin(beta_l))
        assert abs(s21 - ref) <= 1e-12
        tau_ref = l_mm * 1e-3 * math.sqrt(eps) / 299792458.0 * 1e9
        assert abs(out["group_delay_ns"][0] - tau_ref) <= 1e-15


# ─── 一端口三项提取：同仓双源+合成回收 ────────────────────────────────────────

_ED, _ES, _ER = 0.01 + 0.005j, 0.02 - 0.01j, 0.95 + 0.03j


def _fwd(g: complex, ed: complex = _ED, es: complex = _ES,
         er: complex = _ER) -> complex:
    return ed + er * g / (complex(1.0) - es * g)


class TestIssOneportCalExtract:
    def test_ideal_defs_match_trl_solt(self):
        """理想标准档：与 core/trl_solt._oneport_three_term 同仓双源逐位
        互证（同式异实现：Cramer 线性组 vs N_o/N_s 比值闭式）。"""
        raws = [_fwd(1.0 + 0j), _fwd(-1.0 + 0j), _fwd(0.0 + 0j)]
        out = _run("iss_oneport_cal_extract",
                   gamma_std_def=[[1.0, 0.0], [-1.0, 0.0], [0.0, 0.0]],
                   gamma_raw_meas=[[m.real, m.imag] for m in raws])
        d_ref, es_ref, er_ref = _oneport_three_term(
            np.array(raws[1]), np.array(raws[0]), np.array(raws[2]),
            "锚树双源")
        got_ed = complex(out["ed"]["re"], out["ed"]["im"])
        got_es = complex(out["es"]["re"], out["es"]["im"])
        got_er = complex(out["er"]["re"], out["er"]["im"])
        assert got_ed == d_ref
        # 同式异实现（Cramer 线性组 vs N_o/N_s 比值闭式）——浮点双路线
        # 容差 ≤1e-14（#118：异路线裁判容浮点噪声，不逐位硬钉单路线）
        assert abs(got_es - es_ref) <= 1e-14
        assert abs(got_er - er_ref) <= 1e-14 * max(1.0, abs(er_ref))
        assert out["solve_max_residual"] <= 1e-12

    def test_synthetic_recovery_iss_defs(self):
        """非理想 ISS 定义档 #118 合成回收：误差箱/标准定义/DUT Γ 全链
        回收 ≤1e-12；标准定义取自 iss_standard_response 产出（族内闭环）。"""
        # ISS 定义：open C=25fF@10GHz、short L=20pH@10GHz、load 寄生档
        std_open = _run("iss_standard_response", standard_type="open",
                        freq_ghz=[10.0], cap_poly_ff=[25.0, 0, 0, 0])
        std_short = _run("iss_standard_response", standard_type="short",
                         freq_ghz=[10.0], ind_poly_ph=[20.0, 0, 0, 0])
        std_load = _run("iss_standard_response", standard_type="load",
                        freq_ghz=[10.0], load_r_ohm=50.0, load_l_ph=20.0,
                        load_c_ff=8.0)
        gdefs = [
            complex(std_open["gamma_re"][0], std_open["gamma_im"][0]),
            complex(std_short["gamma_re"][0], std_short["gamma_im"][0]),
            complex(std_load["gamma_re"][0], std_load["gamma_im"][0]),
        ]
        raws = [_fwd(g) for g in gdefs]
        gdut = 0.3 + 0.1j
        out = _run("iss_oneport_cal_extract",
                   gamma_std_def=[[g.real, g.imag] for g in gdefs],
                   gamma_raw_meas=[[m.real, m.imag] for m in raws],
                   gamma_meas_raw=[_fwd(gdut).real, _fwd(gdut).imag])
        got_ed = complex(out["ed"]["re"], out["ed"]["im"])
        got_es = complex(out["es"]["re"], out["es"]["im"])
        got_er = complex(out["er"]["re"], out["er"]["im"])
        assert abs(got_ed - _ED) <= 1e-12
        assert abs(got_es - _ES) <= 1e-12
        assert abs(got_er - _ER) <= 1e-12
        got_dut = complex(out["gamma_dut"]["re"], out["gamma_dut"]["im"])
        assert abs(got_dut - gdut) <= 1e-12
        assert out["solve_max_residual"] <= 1e-12

    def test_degenerate_defs_rejected(self):
        """退化定义组（开路≡短路）→ 行列式奇异显式拒绝（不可辨如实）。"""
        _fail("iss_oneport_cal_extract",
              gamma_std_def=[[1.0, 0.0], [1.0, 0.0], [0.0, 0.0]],
              gamma_raw_meas=[[0.9, 0.0], [0.9, 0.0], [0.0, 0.0]])


# ─── 源功率校准：恒等式+回收+链间握手 ─────────────────────────────────────────

class TestSourcePowerCalTable:
    def test_loss_profile_recovery_and_flat_falling(self):
        """合成损耗表精确回收：p_meas=p_set−L(f) → offset=−L、
        program=p_target+L（独立重解）；方向旗标=flat-falling 补偿向。"""
        p_set, p_target = -2.0, 5.0
        freqs = [1.0, 2.0, 4.0, 8.0]
        loss = [0.5 + 0.3 * f for f in freqs]  # 损耗随频上升（falling 原始档）
        meas = [p_set - l_db for l_db in loss]
        out = _run("source_power_cal_table", freq_ghz=freqs,
                   p_meas_dbm=meas, p_set_dbm=p_set,
                   p_target_dbm=p_target)
        for i, l_db in enumerate(loss):
            assert abs(out["offset_db"][i] - (-l_db)) <= 1e-12
            assert abs(out["program_dbm"][i] - (p_target + l_db)) <= 1e-12
            # 平坦设定对照档：交付=p_target+offset（随损耗下坠）
            assert abs(out["program_flat_setting_delivered_dbm"][i]
                       - (p_target - l_db)) <= 1e-12
        assert out["delivered_check_max_dev_db"] <= 1e-12
        assert out["offset_direction"] == "nonincreasing"
        assert out["program_direction"] == "nondecreasing"
        assert abs(out["offset_span_db"] - (loss[-1] - loss[0])) <= 1e-12

    def test_constant_offset_program_flat_and_defaults(self):
        """平坦损耗档：offset 恒 → program 恒（flat）；p_target 缺省=p_set
        （交付=读数原值）；u 标量广播与 U=k=2 恒等。"""
        freqs = [1.0, 3.0, 6.0]
        meas = [-2.0] * 3
        out = _run("source_power_cal_table", freq_ghz=freqs,
                   p_meas_dbm=meas, p_set_dbm=0.0, u_meas_db=0.1)
        assert out["p_target_dbm"] == 0.0
        assert all(v == -2.0 for v in out["offset_db"])
        assert all(v == 2.0 for v in out["program_dbm"])
        assert out["offset_direction"] == "flat"
        assert out["program_direction"] == "flat"
        assert out["offset_span_db"] == 0.0
        assert all(u == 0.1 for u in out["u_program_db"])
        assert all(u == 0.2 for u in out["u_expanded_k2_db"])

    def test_power_cal_chain_handshake(self):
        """链间握手（同仓双源）：power_cal_chain 测量端把缆损加回读数
        （+3dB），本键源端从设定减去（program=p_target−3）——互补闭环，
        交付恒等式两端重合。"""
        p_read, cable = 0.0, 3.0
        chain = run_calculator(
            "power_cal_chain",
            {"p_read_dbm": p_read, "k_cal_lin": 1.0,
             "cable_loss_db": cable})
        assert chain["ok"], chain
        p_available = chain["result"]["p_available_dbm"]
        assert abs(p_available - (p_read + cable)) <= 1e-12  # 测量端语义
        out = _run("source_power_cal_table", freq_ghz=[10.0],
                   p_meas_dbm=[p_available], p_set_dbm=p_read,
                   p_target_dbm=p_read)
        assert abs(out["offset_db"][0] - cable) <= 1e-12
        assert abs(out["program_dbm"][0] - (p_read - cable)) <= 1e-12
        assert out["delivered_check_max_dev_db"] <= 1e-12

    def test_overdrive_infeasible_reported_not_clipped(self):
        """源上限触顶：infeasible 点如实记录+超限 dB，不裁剪 program。"""
        out = _run("source_power_cal_table", freq_ghz=[1.0, 2.0],
                   p_meas_dbm=[-4.0, -2.0], p_set_dbm=0.0,
                   p_target_dbm=0.0, p_src_max_dbm=3.0)
        assert out["infeasible_idx"] == [0]
        assert abs(out["max_overdrive_db"] - 1.0) <= 1e-12
        # program 未裁剪（触顶点仍=p_target−offset）
        assert abs(out["program_dbm"][0] - 4.0) <= 1e-12
        assert abs(out["program_dbm"][1] - 2.0) <= 1e-12
