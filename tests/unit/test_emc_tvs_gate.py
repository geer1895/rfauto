"""ME-3 core/emc_tvs_gate 单测（IEC 61000-4-2/4-5 波形表 + TVS 选型门）。

判据（#118/#122 预声明）：IEC 表边界值回收（接触 2/4/6/8、空气 2/4/8/15 kV；
波形 3.75/2/1 A/kV → Level 4 锚 30/16/8 A；组合波 1.2/50 µs+8/20 µs、2 Ω、
0.5/1/2/4 kV → 0.25/0.5/1/2 kA——双源核对值见模块 provenance）；TVS 闭式逐位
（VC=VBR+IPP·Rdyn 线性式、PPPM=VC·IPP 恒等式、选型链序全序判定）；浪涌线性化
电路精确解 I=(V−VBR)/(Z+Rdyn) 与保守上界 I=V/Z 的序关系（上界≥精确解）测试钉。
边界：IPP≤0、负电压/负阻抗、bool 入参 → ValueError；判缺失 is not None。
"""

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import emc_tvs_gate as tg

# ── 1. IEC 61000-4-2 表 ───────────────────────────────────────────────────────


def test_esd_levels_table():
    assert tg.IEC61000_4_2_LEVELS["contact_kv"] == (2.0, 4.0, 6.0, 8.0)
    assert tg.IEC61000_4_2_LEVELS["air_kv"] == (2.0, 4.0, 8.0, 15.0)
    tbl = tg.esd_levels()
    assert tbl["standard"] == "IEC 61000-4-2:2008"
    assert tbl["generator"] == {"c_pf": 150.0, "r_ohm": 330.0}
    assert tbl["provenance"]["secondary"]  # 双源核对登记非空
    # 拷贝面：改返回 dict 不动模块常量
    tbl["levels"]["contact_kv"] = (0.0,)
    tbl["waveform_per_kv"]["i_peak_a_per_kv"] = 999.0
    assert tg.IEC61000_4_2_LEVELS["contact_kv"] == (2.0, 4.0, 6.0, 8.0)
    assert tg.IEC61000_4_2_WAVEFORM_PER_KV["i_peak_a_per_kv"] == 3.75


def test_esd_waveform_linear_per_kv():
    # Level 4 锚：8 kV → 30/16/8 A（任务书 "8↔30 A" 峰值面 + "1/60 ns" 尾面）
    w8 = tg.esd_waveform_currents(8.0)
    assert (w8["i_peak_a"], w8["i_30ns_a"], w8["i_60ns_a"]) == (30.0, 16.0, 8.0)
    assert w8["rise_time_ns"] == (0.6, 1.0)
    # 4 kV → 15/8/4；2 kV → 7.5/4/2（每 kV 线性归一逐位）
    w4 = tg.esd_waveform_currents(4.0)
    assert (w4["i_peak_a"], w4["i_30ns_a"], w4["i_60ns_a"]) == (15.0, 8.0, 4.0)
    w2 = tg.esd_waveform_currents(2.0)
    assert (w2["i_peak_a"], w2["i_30ns_a"], w2["i_60ns_a"]) == (7.5, 4.0, 2.0)
    # 线性恒等式：currents(4kV) == 0.5×currents(8kV) 逐位
    assert w4["i_peak_a"] == 0.5 * w8["i_peak_a"]
    # 波形规范作用域如实登记（仅接触放电）
    assert "接触" in str(w8["waveform_scope"])


def test_esd_waveform_guards():
    with pytest.raises(ValueError):
        tg.esd_waveform_currents(-1.0)
    with pytest.raises(ValueError):
        tg.esd_waveform_currents(True)  # bool 显式拒收
    w0 = tg.esd_waveform_currents(0.0)  # 0 合法
    assert (w0["i_peak_a"], w0["i_30ns_a"], w0["i_60ns_a"]) == (0.0, 0.0, 0.0)


def test_esd_generator_energy():
    # E = ½CV²：150 pF @ 8 kV → 4.8 mJ；@ 2 kV → 0.3 mJ（逐位）
    assert tg.esd_generator_energy(8.0)["energy_j"] == 0.0048
    assert tg.esd_generator_energy(2.0)["energy_j"] == 0.0003
    # 二次律恒等：V×2 → E×4 逐位
    assert tg.esd_generator_energy(4.0)["energy_j"] == 4.0 * tg.esd_generator_energy(2.0)["energy_j"]
    # 自定义电容与守卫
    assert tg.esd_generator_energy(1.0, c_pf=330.0)["energy_j"] == pytest.approx(1.65e-4, rel=1e-12)
    with pytest.raises(ValueError):
        tg.esd_generator_energy(1.0, c_pf=0.0)
    with pytest.raises(ValueError):
        tg.esd_generator_energy(-2.0)


# ── 2. IEC 61000-4-5 表 ───────────────────────────────────────────────────────


def test_surge_cwg_table():
    cwg = tg.IEC61000_4_5_CWG
    assert (cwg["voc_front_us"], cwg["voc_tail_us"]) == (1.2, 50.0)
    assert (cwg["isc_front_us"], cwg["isc_tail_us"]) == (8.0, 20.0)
    assert cwg["z_eff_ohm"] == 2.0
    assert cwg["levels_kv"] == (0.5, 1.0, 2.0, 4.0)
    assert cwg["coupling_z_ohm"] == {
        "power_line_line": 2.0,
        "power_line_earth": 12.0,
        "signal_line": 42.0,
    }
    tbl = tg.surge_levels()
    assert tbl["standard"] == "IEC 61000-4-5:2014"
    assert tbl["provenance"]["secondary"]
    tbl["cwg"]["z_eff_ohm"] = 999.0  # 拷贝面
    assert tg.IEC61000_4_5_CWG["z_eff_ohm"] == 2.0


def test_surge_short_circuit_current():
    # 锚：4 kV / 2 Ω → 2 kA；1 kV / 42 Ω（信号线耦合网络）→ 23.8095 A
    assert tg.surge_short_circuit_current(4.0)["i_sc_peak_a"] == 2000.0
    assert tg.surge_short_circuit_current(1.0, 42.0)["i_sc_peak_a"] == pytest.approx(
        23.80952380952381, rel=1e-12
    )
    # 首选等级 × 2 Ω → 0.25/0.5/1/2 kA（等级-电流对应表）
    got = [tg.surge_short_circuit_current(v)["i_sc_peak_a"] for v in (0.5, 1.0, 2.0, 4.0)]
    assert got == [250.0, 500.0, 1000.0, 2000.0]
    with pytest.raises(ValueError):
        tg.surge_short_circuit_current(4.0, 0.0)
    with pytest.raises(ValueError):
        tg.surge_short_circuit_current(-1.0, 2.0)
    with pytest.raises(ValueError):
        tg.surge_short_circuit_current(True, 2.0)


# ── 3. TVS 选型闭式 ───────────────────────────────────────────────────────────


def test_tvs_clamp_linear_bitexact():
    # VC = VBR + IPP·Rdyn 线性式逐位
    assert tg.tvs_clamp_voltage(10.0, 5.0, 1.0) == 15.0
    assert tg.tvs_clamp_voltage(6.4, 23.106976744186046, 1.0) == 29.506976744186046
    assert tg.tvs_clamp_voltage(10.0, 5.0, 0.0) == 10.0  # Rdyn=0 → VC==VBR 逐位
    # IPP ≤ 0 → ValueError（任务书边界）；bool 拒收；负 VBR/Rdyn 拒收
    for bad_ipp in (0.0, -1.0, True):
        with pytest.raises(ValueError):
            tg.tvs_clamp_voltage(10.0, bad_ipp, 1.0)
    with pytest.raises(ValueError):
        tg.tvs_clamp_voltage(-10.0, 5.0, 1.0)
    with pytest.raises(ValueError):
        tg.tvs_clamp_voltage(10.0, 5.0, -1.0)


def test_tvs_pppm_identity():
    # PPPM = VC·IPP 恒等式（与 tvs_clamp_voltage 同式自洽）
    assert tg.tvs_peak_pulse_power(5.0, 10.0, 1.0) == 75.0
    for ipp, vbr, rdyn in ((5.0, 10.0, 1.0), (23.106976744186046, 6.4, 0.5), (1.0, 3.3, 0.0)):
        vc = tg.tvs_clamp_voltage(vbr, ipp, rdyn)
        assert tg.tvs_peak_pulse_power(ipp, vbr, rdyn) == vc * ipp
    with pytest.raises(ValueError):
        tg.tvs_peak_pulse_power(0.0, 10.0, 1.0)


def test_tvs_rdyn_backsolve():
    # Rdyn = (VC−VBR)/IPP：12/10/5 → 0.4 逐位；往返恢复 VC
    rd = tg.tvs_rdyn_ohm(10.0, 12.0, 5.0)
    assert rd == 0.4
    assert tg.tvs_clamp_voltage(10.0, 5.0, rd) == 12.0
    with pytest.raises(ValueError):
        tg.tvs_rdyn_ohm(10.0, 9.999, 5.0)  # VC<VBR → 线性近似退化，显式报错


def test_tvs_select_pass_chain():
    g = tg.tvs_select(3.3, 5.0, 6.4, 5.0, rdyn_ohm=0.5, port_withstand_v=12.0)
    assert g.verdict == "PASS"
    assert g.first_failure is None
    assert [link["margin_v"] for link in g.links] == pytest.approx([1.7, 1.4, 3.1], rel=1e-12)
    assert g.vc_v == 8.9  # 6.4 + 5×0.5 逐位
    assert g.pppm_w == 44.5  # 8.9×5 逐位
    assert all(link["pass"] for link in g.links)


def test_tvs_select_fail_links():
    # 链 1：工作电压 > VWM
    g1 = tg.tvs_select(5.5, 5.0, 6.4, 5.0, rdyn_ohm=0.5, port_withstand_v=12.0)
    assert g1.verdict == "FAIL" and g1.first_failure == "vop_vs_vwm"
    assert g1.links[0]["margin_v"] == -0.5
    # 链 2：VWM ≥ VBR（严格 <；相等即违链序）
    g2 = tg.tvs_select(3.3, 5.0, 5.0, 5.0, rdyn_ohm=0.5, port_withstand_v=12.0)
    assert g2.verdict == "FAIL" and g2.first_failure == "vwm_vs_vbr"
    assert g2.links[1]["margin_v"] == 0.0
    # 链 3：钳位 + 余量 > 耐压（VC=6.4+5×2=16.4 > 12）
    g3 = tg.tvs_select(3.3, 5.0, 6.4, 5.0, rdyn_ohm=2.0, port_withstand_v=12.0)
    assert g3.verdict == "FAIL" and g3.first_failure == "clamp_vs_withstand"
    assert g3.links[2]["margin_v"] == pytest.approx(-4.4, rel=1e-12)
    # 钳位余量参数把边缘 PASS 变 FAIL（VC=8.9+余量 3.2 > 12）
    g4 = tg.tvs_select(3.3, 5.0, 6.4, 5.0, rdyn_ohm=0.5, port_withstand_v=12.0, clamp_margin_v=3.2)
    assert g4.verdict == "FAIL" and g4.first_failure == "clamp_vs_withstand"


def test_tvs_select_clamp_source_and_missing():
    # 显式 vc_max_v（数据手册口径，is not None 判缺失）优先于线性式
    g = tg.tvs_select(3.3, 5.0, 6.4, 5.0, vc_max_v=11.0, port_withstand_v=12.0)
    assert g.verdict == "PASS"
    assert g.vc_v == 11.0
    assert g.pppm_w == 55.0
    assert g.links[2]["margin_v"] == 1.0
    # rdyn 与 vc_max_v 双缺 → 显式 ValueError（不静默）
    with pytest.raises(ValueError):
        tg.tvs_select(3.3, 5.0, 6.4, 5.0, port_withstand_v=12.0)
    # 耐压缺省 0.0 会通过入参守卫吗——必须显式给正值
    with pytest.raises(ValueError):
        tg.tvs_select(3.3, 5.0, 6.4, 5.0, rdyn_ohm=0.5)


# ── 4. 浪涌通过判定 ───────────────────────────────────────────────────────────


def test_surge_gate_below_breakdown():
    # 浪涌 4 V < VBR 6.4：不导通，端口吃满 4 V，PASS（耐压 12）
    g = tg.surge_gate(0.004, source_impedance_ohm=2.0, vwm_v=5.0, vbr_min_v=6.4, port_withstand_v=12.0)
    assert g.verdict == "PASS"
    assert g.ipp_a == 0.0
    assert g.vc_v == 4.0
    assert g.pppm_w == 0.0  # 无电流无功率（不虚构保守乘积）
    assert any("below_breakdown" in note for note in g.notes)


def test_surge_gate_linear_divert_exact():
    # 线性化电路精确解：I=(1000−6.4)/(42+1)、VC=6.4+I×1（测试文件内独立复算）
    vbr, rdyn, z, v_surge = 6.4, 1.0, 42.0, 1000.0
    g = tg.surge_gate(
        1.0,
        source_impedance_ohm=z,
        vwm_v=5.0,
        vbr_min_v=vbr,
        port_withstand_v=12.0,
        rdyn_ohm=rdyn,
    )
    i_exact = (v_surge - vbr) / (z + rdyn)
    assert g.ipp_a == pytest.approx(i_exact, rel=1e-12)
    assert g.vc_v == pytest.approx(vbr + i_exact * rdyn, rel=1e-12)
    # VC=29.51 > 耐压 12 → FAIL 于钳位链
    assert g.verdict == "FAIL" and g.first_failure == "clamp_vs_withstand"
    # 保守上界 I=V/Z ≥ 线性精确解（序关系登记；上界只登记不判读）
    assert v_surge / z > i_exact
    assert any(str(round(v_surge / z, 6))[:5] in note for note in g.notes)
    # 耐压放宽到 30 V → PASS（margin=30−29.507）
    g2 = tg.surge_gate(
        1.0,
        source_impedance_ohm=z,
        vwm_v=5.0,
        vbr_min_v=vbr,
        port_withstand_v=30.0,
        rdyn_ohm=rdyn,
    )
    assert g2.verdict == "PASS"
    assert g2.links[2]["margin_v"] == pytest.approx(30.0 - (vbr + i_exact * rdyn), rel=1e-12)


def test_surge_gate_ipp_rating_link():
    kwargs = dict(
        source_impedance_ohm=42.0,
        vwm_v=5.0,
        vbr_min_v=6.4,
        port_withstand_v=30.0,
        rdyn_ohm=1.0,
    )
    g_fail = tg.surge_gate(1.0, ipp_rating_a=20.0, **kwargs)
    assert g_fail.verdict == "FAIL" and g_fail.first_failure == "ipp_vs_rating"
    assert g_fail.links[-1]["link"] == "ipp_vs_rating"
    g_pass = tg.surge_gate(1.0, ipp_rating_a=25.0, **kwargs)
    assert g_pass.verdict == "PASS" and g_pass.first_failure is None


def test_surge_gate_guards():
    with pytest.raises(ValueError):
        tg.surge_gate(-1.0, source_impedance_ohm=2.0, vwm_v=5.0, vbr_min_v=6.4, port_withstand_v=12.0)
    with pytest.raises(ValueError):
        tg.surge_gate(1.0, source_impedance_ohm=0.0, vwm_v=5.0, vbr_min_v=6.4, port_withstand_v=12.0)
    with pytest.raises(ValueError):
        tg.surge_gate(1.0, source_impedance_ohm=2.0, vwm_v=-5.0, vbr_min_v=6.4, port_withstand_v=12.0)
    with pytest.raises(ValueError):
        tg.surge_gate(True, source_impedance_ohm=2.0, vwm_v=5.0, vbr_min_v=6.4, port_withstand_v=12.0)


# ── 5. 登记面 ─────────────────────────────────────────────────────────────────


def test_gate_result_to_dict_json():
    g = tg.tvs_select(3.3, 5.0, 6.4, 5.0, rdyn_ohm=0.5, port_withstand_v=12.0)
    revived = json.loads(json.dumps(g.to_dict()))
    assert revived["verdict"] == "PASS"
    assert revived["first_failure"] is None  # PASS → null（判缺失 is not None 语义）
    assert len(revived["links"]) == 3
    assert revived["vc_v"] == pytest.approx(8.9, rel=1e-15)
    g_fail = tg.tvs_select(5.5, 5.0, 6.4, 5.0, rdyn_ohm=0.5, port_withstand_v=12.0)
    revived_fail = json.loads(json.dumps(g_fail.to_dict()))
    assert revived_fail["first_failure"] == "vop_vs_vwm"


def test_pypi_emc2_warning_registered():
    # 任务书 ME-3 明文警示：PyPI emc2 是大气科学同名假朋友（防再犯登记）
    assert "emc2" in tg.PYPI_EMC2_FAKE_FRIEND
    assert "大气科学" in tg.PYPI_EMC2_FAKE_FRIEND
    assert "勿引用" in tg.PYPI_EMC2_FAKE_FRIEND
    assert "emc2" in tg.__doc__
    g = tg.tvs_select(3.3, 5.0, 6.4, 5.0, rdyn_ohm=0.5, port_withstand_v=12.0)
    assert any("emc2" in note for note in g.notes)
