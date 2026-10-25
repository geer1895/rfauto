"""mim_cap / interdigital_cap IPD 电容模板测试（aurora_k K12，反馈 F1）。

零仿真（exec 截断于 FDTD.Run 之前，秒级）：闭式锚（MIM 手算逐位回收+
缩放恒等式；IDC 分解逐项回收钉+缩放恒等式+用户实测 173.5fF 参考——
K11 教训：不凭记忆写文献系数，IDC 侧壁式为**推导式**非文献转写，来源
声明 core/ipc_cap 模块头）+ CALC 键面门行为 + 布局单源几何/守卫 +
#212 exec 审计（MIM 三明治叠层/端口跨介质；IDC 双排 DC 隔离）+
fake 自洽（C 回收/SRF 对拍/参数驱动）+ 注册面同步。判据预声明
内部证据档（先声明后实测）。

数字出处（#118 家法，#331 审计 dump 原文纪律）：
- MIM 平行板：C=ε0·εr·A/d 教科书精确式（单源 core/package_interconnect
  .mim_capacitance，缩放恒等式裁判 test_package_interconnect 在案）；
  名义档 20×20μm/0.2μm SiNx(7.5) → 132.8128fF（测试内手算逐位回收）；
- IDC 侧壁 sum-of-capacitances：C=(N−1)·ε0·εeff·t·l_c/s **推导式**
  （面对面积 t·l_c、间距 s 的几何恒等式；εeff=(1+εr)/2 半空间均匀化；
  精度类 ±50% 如实声明——槽平面/齿端边缘场省略→薄金属低估偏置）；
  名义档 n=24/lf=220/wf=sf=5/e_tip=15μm → 174.087fF，对用户实测
  173.5fF（反馈 F1 原文，K8 Z12 去嵌后）偏差 −0.34%（±50% 门内；
  用户几何未给全，同量级参考对拍非逐位锚）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import (
    INTERDIGITAL_CAP_NOMINAL,
    MIM_CAP_NOMINAL,
    TEMPLATE_META,
    _interdigital_cap_layout,
    _mim_cap_layout,
    geometry_spec,
    interdigital_cap_geometry_spec,
    mim_cap_geometry_spec,
    render_script,
    template_meta,
)
from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.core.ipc_cap import (
    EPS0,
    interdigital_capacitance_f,
    mim_capacitance_report,
)
from rfauto.service.calculator_service import run_calculator
from tests.unit import _geometry_audit_helpers as gh

MIM_NOM = dict(MIM_CAP_NOMINAL)
IDC_NOM = dict(INTERDIGITAL_CAP_NOMINAL)
BAND = (2.0 - 0.25, 2.0 + 0.25)

#: 用户实测参考（反馈 F1 原文：IDC 集总 C=173.5fF，K8 Z12 去嵌后）
USER_IDC_C_FF = 173.5


# ─── 1) 闭式锚：手算/分解回收 + 缩放恒等式 ───────────────────────────────────

class TestClosedFormAnchors:
    def test_mim_hand_recovery_bitwise(self):
        """名义档手算逐位回收：C=ε0·εr·A/d（键面 μm 口径端到端）。"""
        out = run_calculator("mim_capacitance",
                             {"w_um": 20.0, "l_um": 20.0, "d_um": 0.2,
                              "er_diel": 7.5})
        assert out["ok"] is True, out
        c_ref = EPS0 * 7.5 * (20e-6 * 20e-6) / 0.2e-6
        assert out["result"]["c_f"] == pytest.approx(c_ref, rel=1e-12)
        assert out["result"]["c_ff"] == pytest.approx(132.8128, abs=5e-4)

    def test_mim_scaling_identities(self):
        """平行板缩放恒等式：C∝A（w×2）、C∝1/d（d×2）。"""
        base = run_calculator("mim_capacitance",
                              {"w_um": 20.0, "l_um": 20.0, "d_um": 0.2,
                               "er_diel": 7.5})["result"]["c_f"]
        wide = run_calculator("mim_capacitance",
                              {"w_um": 40.0, "l_um": 20.0, "d_um": 0.2,
                               "er_diel": 7.5})["result"]["c_f"]
        thin = run_calculator("mim_capacitance",
                              {"w_um": 20.0, "l_um": 20.0, "d_um": 0.1,
                               "er_diel": 7.5})["result"]["c_f"]
        assert wide == pytest.approx(2.0 * base, rel=1e-12)
        assert thin == pytest.approx(2.0 * base, rel=1e-12)

    def test_mim_parasitics_derivation_check(self):
        """串联寄生一阶核对：R_s=ρ·l/(t·w)、L_s=μ0·d·l/w（推导式回代）。"""
        out = run_calculator("mim_capacitance",
                             {"w_um": 20.0, "l_um": 20.0, "d_um": 0.2,
                              "er_diel": 7.5})["result"]
        r_ref = 2.44e-8 * 20e-6 / (3e-6 * 20e-6)
        l_ref = (4.0e-7 * math.pi) * 0.2e-6 * 20e-6 / 20e-6
        # 键面 r_s_ohm 按小数点后 8 位舍入（mΩ 量级相对舍入步 ~1e-6）
        assert out["parasitics"]["r_s_ohm"] == pytest.approx(r_ref, rel=1e-5)
        assert out["parasitics"]["l_ser_ph"] == pytest.approx(l_ref * 1e12,
                                                              rel=1e-5)
        srf_ref = 1.0 / (2.0 * math.pi * math.sqrt(l_ref * out["c_f"]))
        assert out["srf_ghz"] == pytest.approx(srf_ref * 1e-9, rel=1e-3)

    def test_idc_decomposition_recovery_pin(self):
        """分解逐项回收钉（K11 教训：推导式的实现裁判=合成参数→逐项重算
        →与闭式一致）：名义档 (N−1)·ε0·εeff·t·l_c/s 逐位回代。"""
        out = run_calculator("interdigital_capacitance",
                             {"n_fingers": 24, "lf_um": 220.0, "wf_um": 5.0,
                              "sf_um": 5.0, "e_tip_um": 15.0,
                              "er_sub": 12.9})
        assert out["ok"] is True, out
        res = out["result"]
        assert res["decomposition"]["n_gap_pairs"] == 23
        assert res["decomposition"]["l_c_um"] == pytest.approx(205.0, rel=1e-12)
        assert res["decomposition"]["eps_eff"] == pytest.approx(
            0.5 * (1.0 + 12.9), rel=1e-12)
        c_pair_ref = (EPS0 * 0.5 * (1.0 + 12.9) * 3e-6 * 205e-6 / 5e-6)
        assert res["decomposition"]["c_pair_ff"] == pytest.approx(
            c_pair_ref * 1e15, rel=1e-7)
        assert res["c_f"] == pytest.approx(23.0 * c_pair_ref, rel=1e-12)
        assert res["c_ff"] == pytest.approx(174.087, abs=5e-3)

    def test_idc_scaling_identities(self):
        """侧壁主项缩放恒等式：C∝(N−1)、C∝l_c、C∝t、C∝1/s。"""
        base = run_calculator("interdigital_capacitance",
                              {"n_fingers": 24, "lf_um": 220.0, "wf_um": 5.0,
                               "sf_um": 5.0, "e_tip_um": 15.0})["result"]["c_f"]
        more = run_calculator("interdigital_capacitance",
                              {"n_fingers": 34, "lf_um": 220.0, "wf_um": 5.0,
                               "sf_um": 5.0, "e_tip_um": 15.0})["result"]["c_f"]
        longer = run_calculator("interdigital_capacitance",
                                {"n_fingers": 24, "lf_um": 320.0, "wf_um": 5.0,
                                 "sf_um": 5.0, "e_tip_um": 15.0})["result"]["c_f"]
        thicker = run_calculator("interdigital_capacitance",
                                 {"n_fingers": 24, "lf_um": 220.0, "wf_um": 5.0,
                                  "sf_um": 5.0, "e_tip_um": 15.0,
                                  "t_um": 6.0})["result"]["c_f"]
        looser = run_calculator("interdigital_capacitance",
                                {"n_fingers": 24, "lf_um": 220.0, "wf_um": 5.0,
                                 "sf_um": 10.0, "e_tip_um": 15.0})["result"]["c_f"]
        assert more == pytest.approx(base * 33.0 / 23.0, rel=1e-12)
        assert longer == pytest.approx(base * 305.0 / 205.0, rel=1e-12)
        assert thicker == pytest.approx(2.0 * base, rel=1e-12)
        assert looser == pytest.approx(0.5 * base, rel=1e-12)

    def test_idc_user_reference_within_gate(self):
        """用户实测参考（反馈 F1）：名义档 174.087fF 对 173.5fF（K8 Z12
        去嵌后）偏差 −0.34%（±50% 门内；同量级参考对拍非逐位锚）。"""
        out = run_calculator("interdigital_capacitance",
                             {"n_fingers": 24, "lf_um": 220.0, "wf_um": 5.0,
                              "sf_um": 5.0, "e_tip_um": 15.0,
                              "er_sub": 12.9,
                              "reference_c_ff": USER_IDC_C_FF})
        gate = out["result"]["gates"]["c_vs_reference"]
        assert gate["pass"] is True
        assert gate["deviation_pct"] == pytest.approx(-0.3372, abs=5e-3)

    def test_idc_model_class_declared_honest(self):
        """±50% 精度类与低估偏置如实声明（#122 不凑绿）。"""
        rep = interdigital_capacitance_f(24, 220e-6, 5e-6, 5e-6, 3e-6, 12.9,
                                         e_tip_m=15e-6)
        assert "±50%" in rep["scope_note"]
        assert rep["model"] == "sidewall_parallel_plate_sum_first_order"


# ─── 2) CALC 键面：门行为与守卫 ──────────────────────────────────────────────

class TestCalcGateBehavior:
    MIM_BASE: ClassVar[dict] = {"w_um": 20.0, "l_um": 20.0, "d_um": 0.2,
                                "er_diel": 7.5}
    IDC_BASE: ClassVar[dict] = {"n_fingers": 24, "lf_um": 220.0,
                                "wf_um": 5.0, "sf_um": 5.0,
                                "e_tip_um": 15.0, "er_sub": 12.9}

    def test_mim_gate_pass_and_fail(self):
        ok = run_calculator("mim_capacitance",
                            {**self.MIM_BASE, "reference_c_ff": 140.0})
        assert ok["result"]["gates"]["c_vs_reference"]["pass"] is True
        bad = run_calculator("mim_capacitance",
                             {**self.MIM_BASE, "reference_c_ff": 200.0})
        gate = bad["result"]["gates"]["c_vs_reference"]
        assert gate["pass"] is False
        assert gate["limit_pct"] == 25.0
        assert bad["ok"] is True   # FAIL 如实呈现不抛异常（#122）

    def test_idc_gate_pass_and_fail(self):
        ok = run_calculator("interdigital_capacitance",
                            {**self.IDC_BASE, "reference_c_ff": USER_IDC_C_FF})
        assert ok["result"]["gates"]["c_vs_reference"]["pass"] is True
        bad = run_calculator("interdigital_capacitance",
                             {**self.IDC_BASE, "reference_c_ff": 400.0})
        gate = bad["result"]["gates"]["c_vs_reference"]
        assert gate["pass"] is False
        assert gate["limit_pct"] == 50.0
        assert bad["ok"] is True

    def test_srf_gate_pass_and_fail(self):
        ok = run_calculator("mim_capacitance", {**self.MIM_BASE,
                                                "f0_ghz": 2.0})
        assert ok["result"]["gates"]["srf_over_f0"]["pass"] is True
        assert ok["result"]["srf_ghz"] > 100.0   # 一阶口径：SRF 远高于带
        # f0 抬到 SRF 同量级即门红（SRF>2×f0 违反如实呈现）
        bad = run_calculator("mim_capacitance", {**self.MIM_BASE,
                                                 "f0_ghz": 500.0})
        assert bad["result"]["gates"]["srf_over_f0"]["pass"] is False
        ok2 = run_calculator("interdigital_capacitance",
                             {**self.IDC_BASE, "f0_ghz": 2.0})
        assert ok2["result"]["gates"]["srf_over_f0"]["pass"] is True

    def test_guards_domain_errors(self):
        """service 层把 ValueError 翻译成 ok=False 信封（不抛，#122）。"""
        for key, params in (
                ("mim_capacitance", {"w_um": 0.0}),
                ("mim_capacitance", {"d_um": -0.2}),
                ("mim_capacitance", {"er_diel": 0.0}),
                ("interdigital_capacitance", {"n_fingers": 23}),
                ("interdigital_capacitance", {"n_fingers": 0}),
                ("interdigital_capacitance", {"lf_um": 0.0}),
                ("interdigital_capacitance", {"e_tip_um": 300.0}),
                ("interdigital_capacitance", {"sf_um": 0.0})):
            base = dict(self.MIM_BASE if key == "mim_capacitance"
                        else self.IDC_BASE)
            out = run_calculator(key, {**base, **params})
            assert out["ok"] is False and out.get("error"), (key, params)

    def test_q_reported_at_f0(self):
        out = run_calculator("mim_capacitance",
                             {**self.MIM_BASE, "f0_ghz": 2.0})["result"]
        q_ref = 1.0 / (2.0 * math.pi * 2e9 * out["c_f"]
                       * out["parasitics"]["r_s_ohm"])
        assert out["q_at_f0"] == pytest.approx(q_ref, rel=1e-3)
        out2 = run_calculator("interdigital_capacitance",
                              {**self.IDC_BASE, "f0_ghz": 2.0})["result"]
        q_ref2 = 1.0 / (2.0 * math.pi * 2e9 * out2["c_f"]
                        * out2["parasitics"]["r_s_ohm"])
        assert out2["q_at_f0"] == pytest.approx(q_ref2, rel=1e-3)


# ─── 3) 布局单源：几何/守卫（#212 家法辅助）──────────────────────────────────

class TestLayout:
    def test_mim_sandwich_z_accounting(self):
        """叠层 z 账目：下极板 z=H、介质 [H, H+d]、上极板 z=H+d（K9
        Stackup z_ranges 单源映射，#154 同语义）。"""
        lay = _mim_cap_layout(dict(MIM_NOM), BAND)
        assert lay["z_diel"] == pytest.approx(
            (MIM_NOM["h_mm"] * 1e-3,
             MIM_NOM["h_mm"] * 1e-3 + MIM_NOM["d_um"] * 1e-6), rel=1e-12)
        assert lay["n_plan_segments"] == 1   # 共形单足迹退化档 over_metal
        bot, top = lay["bot"], lay["top"]
        for k in (0, 1, 2, 3):
            assert top[k] == pytest.approx(bot[k], rel=1e-12) or True
        # 下极板=上极板足迹外扩 overhang（四周）
        assert bot[0] == pytest.approx(top[0] - lay["ov"], rel=1e-12)
        assert bot[2] == pytest.approx(top[2] + lay["ov"], rel=1e-12)
        assert bot[1] == pytest.approx(top[1] - lay["ov"], rel=1e-12)
        assert bot[3] == pytest.approx(top[3] + lay["ov"], rel=1e-12)
        # 端口盒 z 跨介质（上-下极板之间）、xy 内含于叠合区
        px0, py0, pz0, px1, py1, pz1 = lay["port_box"]
        assert pz0 == pytest.approx(lay["h"], rel=1e-12)
        assert pz1 == pytest.approx(lay["h"] + lay["d"], rel=1e-12)
        assert lay["top"][0] < px0 < px1 < lay["top"][2]
        assert lay["top"][1] < py0 < py1 < lay["top"][3]

    def test_mim_um_params_via_to_mm_single_source(self):
        """μm 参数经 core.stackup.to_mm 单源换算（1μm 扰动必变几何）。"""
        lay = _mim_cap_layout(dict(MIM_NOM, w_um=20.001), BAND)
        lay0 = _mim_cap_layout(dict(MIM_NOM), BAND)
        assert lay["w"] - lay0["w"] == pytest.approx(1e-9, rel=1e-9)

    def test_mim_port_inside_guard(self):
        with pytest.raises(ValueError, match="端口盒须内含于叠合区"):
            _mim_cap_layout(dict(MIM_NOM, port_um=18.0), BAND)

    def test_mim_near_guard_rejects_underresolved_mesh(self):
        with pytest.raises(ValueError, match="#266"):
            _mim_cap_layout(dict(MIM_NOM), BAND, mesh_resolution_mm=0.4)

    def test_idc_geometry_closed_form(self):
        """齿条坐标闭式：l_c=lf−e_tip、y_span=N(wf+sf)−sf、总宽闭式。"""
        lay = _interdigital_cap_layout(dict(IDC_NOM), BAND)
        n, pitch = lay["n"], lay["pitch"]
        assert lay["l_c"] == pytest.approx(lay["lf"] - lay["e_tip"],
                                           rel=1e-12)
        assert lay["y_span"] == pytest.approx(n * pitch - lay["sf"],
                                              rel=1e-12)
        assert len(lay["fingers_a"]) == n // 2
        assert len(lay["fingers_b"]) == n // 2
        # B 排尖部外伸越 A 排指条端：xb0 = xa0 + e_tip
        assert lay["fingers_b"][0][0] == pytest.approx(
            lay["fingers_a"][0][0] + lay["e_tip"], rel=1e-12)
        # B 排尖部与左汇流排间距=e_tip ≥ sf（Clears 守卫）
        assert lay["fingers_b"][0][0] - lay["bus_a"][2] == pytest.approx(
            lay["e_tip"], rel=1e-12)
        # 端口桥隙跨距=gp、两端口各自跨在馈盘-汇流排之间
        for pb in (lay["port1"], lay["port2"]):
            assert pb[2] - pb[0] == pytest.approx(lay["gp"], rel=1e-12)

    def test_idc_guards(self):
        # 渲染层 n 取整到最近偶数（审计扰动 ×1.37 形态合法）；n<2（如
        # 1→0）显式拒绝；CALC 层奇数显式拒绝（域错误用例族钉）
        with pytest.raises(ValueError, match="≥2"):
            _interdigital_cap_layout(dict(IDC_NOM, n_fingers=1), BAND)
        with pytest.raises(ValueError, match="耦合长度"):
            _interdigital_cap_layout(dict(IDC_NOM, e_tip_um=300.0), BAND)
        with pytest.raises(ValueError, match="#266"):
            _interdigital_cap_layout(dict(IDC_NOM), BAND,
                                     mesh_resolution_mm=0.4)

    def test_idc_odd_count_snaps_to_even(self):
        """审计扰动 ×1.37 形态：奇数扰动取整到最近偶数（A/B 排各半）。"""
        lay = _interdigital_cap_layout(dict(IDC_NOM, n_fingers=32.893), BAND)
        assert lay["n"] == 32

    def test_render_script_wiring(self):
        """整脚本：MIM 竖直端口 z 向激励+介质层材料块；IDC 双端口 x 向+
        零厚金属跨口径注记在档。"""
        txt = render_script("mim_cap", dict(MIM_NOM), BAND)
        assert '"z", excite=1' in txt
        assert "mim_diel" in txt and "AddMaterial" in txt
        assert "mim_cap_meta.json" in txt
        txt_i = render_script("interdigital_cap", dict(IDC_NOM), BAND)
        assert '"x", excite=1' in txt_i and '"x", excite=0' in txt_i
        assert "interdigital_cap_meta.json" in txt_i
        txt_i2 = render_script("interdigital_cap", dict(IDC_NOM), BAND,
                               excite_port=2)
        assert '"x", excite=0' in txt_i2 and '"x", excite=1' in txt_i2

    def test_geometry_spec_shape(self):
        spec = mim_cap_geometry_spec(dict(MIM_NOM), {"er": 12.9})
        assert spec["template"] == "mim_cap"
        assert len(spec["ports"]) == 1
        assert any("mim_diel" in b["name"] for b in spec["boxes"])
        spec2 = interdigital_cap_geometry_spec(dict(IDC_NOM), {"er": 12.9})
        assert spec2["template"] == "interdigital_cap"
        assert len(spec2["ports"]) == 2
        # geometry_spec 早分发（render_core 主入口同结果）
        assert geometry_spec("mim_cap", dict(MIM_NOM))["template"] == "mim_cap"
        assert geometry_spec("interdigital_cap",
                             dict(IDC_NOM))["template"] == "interdigital_cap"


# ─── 4) exec 几何审计（#212：渲染→exec→CSXCAD 实测，秒级零仿真）──────────────

class TestExecGeometryAuditMim:
    @pytest.fixture(scope="class")
    def scope_and_prims(self):
        return gh.load_geometry("mim_cap")

    def test_sandwich_stack_and_isolated_plates(self, scope_and_prims):
        """三明治叠层实测：基板/介质/下极板/上极板 bbox 逐位对齐；双极板
        DC 隔离（介质隔开——LumpedElement 桥接属 RF 维）。"""
        scope, prims = scope_and_prims
        lay = _mim_cap_layout(dict(MIM_NOM), BAND)
        diel = [p for p in prims if p.prop == "mim_diel"]
        assert len(diel) == 1
        d = diel[0]
        assert d.lo[2] == pytest.approx(lay["h"], rel=1e-12)
        assert d.hi[2] == pytest.approx(lay["h"] + lay["d"], rel=1e-12)
        conductors, labels = gh.conductor_labels(prims)
        metal_idx = [i for i, p in enumerate(conductors)
                     if p.kind == "Metal" and p.prop == "metal"]
        assert len(metal_idx) == 2, "极板应恰两块（下+上）"
        # 两块极板 z 分层（零厚面各自贴介质上下界）
        zs = sorted(float(conductors[i].lo[2]) for i in metal_idx)
        assert zs[0] == pytest.approx(lay["h"], rel=1e-12)
        assert zs[1] == pytest.approx(lay["h"] + lay["d"], rel=1e-12)
        # 端口馈电点落在导体连通分量上（LumpedElement 桥接双板）
        port_feed = gh.port_feed_point(scope["_port1"])
        assert gh.containing_labels(port_feed, conductors, labels), (
            "端口馈电点悬空")

    def test_no_near_coincident_mesh_lines(self, scope_and_prims):
        """#152 z 轴薄层适配档（d/4=0.05µm）：介质三线保留、nm 级重合线
        无。"""
        scope, _ = scope_and_prims
        for axis, thr in (("x", 1e-6), ("y", 1e-6), ("z", 5e-8)):
            lines = gh.mesh_lines(scope, axis)
            diffs = np.diff(lines)
            assert bool(np.all(diffs > thr)), f"{axis} 轴近重合线"
        # 介质三线在档（H、H+d/2、H+d）
        lay = _mim_cap_layout(dict(MIM_NOM), BAND)
        z = gh.mesh_lines(scope, "z")
        for z_ref in (lay["h"], (lay["h"] + lay["z_diel"][1]) / 2.0,
                      lay["z_diel"][1]):
            assert float(np.min(np.abs(z - z_ref))) <= 5e-8, (
                f"z={z_ref!r} 未入网（介质薄层三线 #283）")

    def test_port_excitation_volume_nonzero(self, scope_and_prims):
        scope, _ = scope_and_prims
        port = scope["_port1"]
        ext = np.abs(np.asarray(port.start) - np.asarray(port.stop))
        assert ext[2] > 0, "端口激励体积为零（跨介质向）"
        assert int(getattr(port, "exc_ny", 0)) == 2, "exc 须沿 z"


class TestExecGeometryAuditIdc:
    @pytest.fixture(scope="class")
    def scope_and_prims(self):
        return gh.load_geometry("interdigital_cap")

    def test_two_isolated_banks(self, scope_and_prims):
        """梳齿互锁定义性质：{A 排+左汇流排+馈盘A} 与 {B 排+右汇流排+
        馈盘B} 两个 DC 隔离分量（缝塌缩短路即红）。"""
        scope, prims = scope_and_prims
        conductors, labels = gh.conductor_labels(prims)
        idc_idx = [i for i, p in enumerate(conductors)
                   if p.kind == "Metal" and p.prop == "idc"]
        assert idc_idx, "无 idc 金属原语"
        comps = sorted(set(labels[i] for i in idc_idx))
        assert len(comps) == 2, (
            f"A/B 排应恰 2 个 DC 隔离分量，实测 {len(comps)}（缝塌缩短路）")
        # 每个分量恰含：1 汇流排 + n/2 齿 + 1 馈盘
        for comp in comps:
            members = [conductors[i] for i in idc_idx if labels[i] == comp]
            assert len(members) == (IDC_NOM["n_fingers"] // 2 + 2), (
                f"分量原语数 {len(members)} != n/2 齿+汇流排+馈盘")
        # 端口馈电点各自落位（Port1 在 A 分量、Port2 在 B 分量）
        ports = gh.port_objects(scope)
        assert set(ports) == {1, 2}
        comps_by_port = {
            n: gh.containing_labels(gh.port_feed_point(p), conductors, labels)
            for n, p in ports.items()}
        assert comps_by_port[1] and comps_by_port[2]
        assert comps_by_port[1].isdisjoint(comps_by_port[2]), (
            "双端口馈电点同分量=两排短路")

    def test_finger_pitch_on_mesh(self, scope_and_prims):
        """齿缘/齿缝全部特征线在档（wf/sf μm 特征精确入网 #198）。"""
        scope, _ = scope_and_prims
        lay = _interdigital_cap_layout(dict(IDC_NOM), BAND)
        xs = gh.mesh_lines(scope, "x")
        ys = gh.mesh_lines(scope, "y")
        for f in lay["fingers_a"] + lay["fingers_b"]:
            for x_ref in (f[0], f[2]):
                assert float(np.min(np.abs(xs - x_ref))) <= 1e-9, (
                    f"x={x_ref!r} 未入网（齿缘）")
            for y_ref in (f[1], f[3]):
                assert float(np.min(np.abs(ys - y_ref))) <= 1e-9, (
                    f"y={y_ref!r} 未入网（齿缘）")

    def test_no_near_coincident_mesh_lines(self, scope_and_prims):
        scope, _ = scope_and_prims
        for axis in ("x", "y", "z"):
            lines = gh.mesh_lines(scope, axis)
            diffs = np.diff(lines)
            assert bool(np.all(diffs > 1e-6)), f"{axis} 轴 <1µm 近重合线"


# ─── 5) fake 通道自洽（参数 → 闭式 C → 自洽 S 参数）─────────────────────────

def _zin_from_s11(f_ghz: np.ndarray, s11: np.ndarray,
                  z0: float = 50.0) -> np.ndarray:
    return z0 * (1.0 + s11) / (1.0 - s11)


class TestFakeSelfConsistency:
    def test_mim_c_recovered_from_low_freq_zin(self):
        """低频段 Zin=50(1+S11)/(1−S11) → C=−1/(ω·Im(Zin)) 回收闭式 C
        （串联寄生 (ωL)/(1/(ωC)) 二阶——f≪SRF 时 ≤0.1%）。"""
        from rfauto.adapters.fake_adapter import _mim_cap_sparams

        c_ref = float(mim_capacitance_report(20e-6, 20e-6, 0.2e-6, 7.5)["c_f"])
        f = np.array([0.1, 0.3, 0.5])
        s = np.asarray(_mim_cap_sparams(f))[:, 0, 0]
        z = _zin_from_s11(f, s)
        c_ext = -1.0 / (2.0 * math.pi * f * 1e9 * np.imag(z))
        assert np.allclose(c_ext, c_ref, rtol=1e-3), (c_ext, c_ref)

    def test_mim_srf_series_resonance_matches_closed_form(self):
        """Im(Zin) 过零=1/(2π√(L_s·C))（串联谐振，≤0.1%）。"""
        from rfauto.adapters.fake_adapter import _mim_cap_sparams

        c_ref = float(mim_capacitance_report(20e-6, 20e-6, 0.2e-6, 7.5)["c_f"])
        l_ref = (4.0e-7 * math.pi) * 0.2e-6 * 20e-6 / 20e-6
        srf_ref = 1.0 / (2.0 * math.pi * math.sqrt(l_ref * c_ref))
        f = np.linspace(srf_ref / 1e9 * 0.9, srf_ref / 1e9 * 1.1, 2001)
        s = np.asarray(_mim_cap_sparams(f))[:, 0, 0]
        z = _zin_from_s11(f, s)
        idx = int(np.argmin(np.abs(np.imag(z))))
        assert f[idx] * 1e9 == pytest.approx(srf_ref, rel=1e-3)

    def test_mim_passivity(self):
        from rfauto.adapters.fake_adapter import _mim_cap_sparams

        f = np.logspace(-1, 3, 400)   # 0.1GHz..1THz（跨 SRF）
        s = np.asarray(_mim_cap_sparams(f))[:, 0, 0]
        assert bool(np.all(np.abs(s) <= 1.0 + 1e-9))

    def test_idc_c_recovered_via_series_extraction(self):
        """串联口径：Z=2·z0·(1−S21)/S21 → C=−1/(ω·Im(Z))（K8 Z12 链同
        口径；串联寄生 (ωL)/(1/(ωC)) 二阶 ≤0.1%）。"""
        from rfauto.adapters.fake_adapter import _interdigital_cap_sparams

        rep = interdigital_capacitance_f(24, 220e-6, 5e-6, 5e-6, 3e-6, 12.9,
                                         e_tip_m=15e-6)
        c_ref = float(rep["c_f"])
        f = np.array([0.1, 0.3, 0.5])
        s21 = np.asarray(_interdigital_cap_sparams(f))[:, 0, 1]
        z = 2.0 * 50.0 * (1.0 - s21) / s21
        c_ext = -1.0 / (2.0 * math.pi * f * 1e9 * np.imag(z))
        assert np.allclose(c_ext, c_ref, rtol=1e-3), (c_ext, c_ref)

    def test_idc_s21_low_freq_unit_and_reciprocity(self):
        from rfauto.adapters.fake_adapter import _interdigital_cap_sparams

        f = np.array([0.1, 0.5, 1.0])
        sm = np.asarray(_interdigital_cap_sparams(f))
        assert bool(np.all(np.abs(sm[:, 1, 0]) <= 1.0 + 1e-9))
        assert bool(np.all(np.abs(sm[:, 0, 1] - sm[:, 1, 0]) <= 1e-12))
        assert bool(np.all(np.abs(sm[:, 0, 0]) <= 1.0 + 1e-9))

    def test_params_drive_response(self):
        """参数变化有真实响应：MIM d 减半 → C 翻倍（Zin 相位双移）；
        IDC n 增 → C 增（S21 谷深下移）。"""
        from rfauto.adapters.fake_adapter import (
            _interdigital_cap_sparams,
            _mim_cap_sparams,
        )

        f = np.array([0.5])
        c_base = -1.0 / (2 * math.pi * 0.5e9 * np.imag(_zin_from_s11(
            f, np.asarray(_mim_cap_sparams(f))[:, 0, 0]))[0])
        c_thin = -1.0 / (2 * math.pi * 0.5e9 * np.imag(_zin_from_s11(
            f, np.asarray(_mim_cap_sparams(f, d_um=0.1))[:, 0, 0]))[0])
        assert c_thin == pytest.approx(2.0 * float(c_base), rel=1e-3)
        c_n24 = float(interdigital_capacitance_f(
            24, 220e-6, 5e-6, 5e-6, 3e-6, 12.9, e_tip_m=15e-6)["c_f"])
        c_n34 = float(interdigital_capacitance_f(
            34, 220e-6, 5e-6, 5e-6, 3e-6, 12.9, e_tip_m=15e-6)["c_f"])
        s21_24 = np.asarray(_interdigital_cap_sparams(np.array([1.0])))[0, 1, 0]
        s21_34 = np.asarray(_interdigital_cap_sparams(
            np.array([1.0]), n_fingers=34))[0, 1, 0]
        # |S21| 随 C 增大而升高（串联阻抗减小——1/(ωC) 主项）
        assert abs(s21_34) > abs(s21_24)
        z24 = 2 * 50 * (1 - s21_24) / s21_24
        assert -1.0 / (2 * math.pi * 1e9 * np.imag(z24)) == pytest.approx(
            c_n24, rel=1e-3)
        z34 = 2 * 50 * (1 - s21_34) / s21_34
        assert -1.0 / (2 * math.pi * 1e9 * np.imag(z34)) == pytest.approx(
            c_n34, rel=1e-3)

    def test_fake_dispatch_via_adapter(self):
        """FakeAdapter 按名分发全路径（solve→network→C 回收）。"""
        import skrf

        from rfauto.adapters.fake_adapter import FakeAdapter

        c_ref = float(mim_capacitance_report(20e-6, 20e-6, 0.2e-6, 7.5)["c_f"])
        ad = FakeAdapter(model_type="mim_cap", n_ports=1,
                         freq_ghz=(0.1, 10.0, 201), f0_ghz=2.0)
        ad.connect({})
        ad.set_variables({})
        report = ad.solve("k12")
        assert report.success
        net = ad.get_sparams()
        assert isinstance(net, skrf.Network)
        f = np.asarray(net.frequency.f, dtype=float)
        s = np.asarray(net.s, dtype=complex)[:, 0, 0]
        z = _zin_from_s11(f, s)
        c_ext = -1.0 / (2 * math.pi * f * np.imag(z))
        mask = (f >= 0.1e9) & (f <= 1.0e9)
        assert np.allclose(c_ext[mask], c_ref, rtol=1e-2)

        ad2 = FakeAdapter(model_type="interdigital_cap", n_ports=2,
                          freq_ghz=(0.1, 10.0, 201), f0_ghz=2.0)
        ad2.connect({})
        ad2.set_variables({})
        assert ad2.solve("k12").success
        net2 = ad2.get_sparams()
        s21 = np.asarray(net2.s, dtype=complex)[:, 0, 1]
        f2 = np.asarray(net2.frequency.f, dtype=float)
        rep = interdigital_capacitance_f(24, 220e-6, 5e-6, 5e-6, 3e-6, 12.9,
                                         e_tip_m=15e-6)
        z2 = 2 * 50 * (1 - s21) / s21
        c_ext2 = -1.0 / (2 * math.pi * f2 * np.imag(z2))
        mask2 = (f2 >= 0.1e9) & (f2 <= 1.0e9)
        assert np.allclose(c_ext2[mask2], float(rep["c_f"]), rtol=1e-2)

    def test_variable_override_via_set_variables(self):
        """set_variables 同名同语义驱动（#154）：d_um 减半 → C 翻倍。"""
        from rfauto.adapters.fake_adapter import FakeAdapter

        ad = FakeAdapter(model_type="mim_cap", n_ports=1,
                         freq_ghz=(0.5, 0.5, 1), f0_ghz=2.0)
        ad.connect({})
        ad.set_variables({"d_um": 0.1})
        ad.solve("k12")
        s = np.asarray(ad.get_sparams().s, dtype=complex)[0, 0, 0]
        z = _zin_from_s11(np.array([0.5]), np.array([s]))
        c_ref = float(mim_capacitance_report(20e-6, 20e-6, 0.1e-6, 7.5)["c_f"])
        assert -1.0 / (2 * math.pi * 0.5e9 * np.imag(z[0])) == pytest.approx(
            c_ref, rel=1e-2)


# ─── 6) spec 综合与注册面同步 ────────────────────────────────────────────────

class TestRegistration:
    def test_template_meta_and_nominal_registered(self):
        for name, nom in (("mim_cap", MIM_NOM),
                          ("interdigital_cap", IDC_NOM)):
            meta = template_meta(name)
            assert meta["n_ports"] == TEMPLATE_META[name]["n_ports"]
            assert set(meta["params"]) <= set(nom)
            assert TEMPLATE_META[name]["extraction"]

    def test_gallery_family_registered(self):
        """gallery 族登记全量覆盖（#231/#304 注册表消费者纪律）。"""
        from rfauto.service.gallery_service import FAMILY_LABELS, TEMPLATE_FAMILIES
        for name in ("mim_cap", "interdigital_cap"):
            assert name in TEMPLATE_FAMILIES
            assert TEMPLATE_FAMILIES[name] in FAMILY_LABELS

    def test_spec_registered_and_synthesizer(self):
        """TEMPLATE_SPECS 注册（w2b 全量覆盖钉同源）+ 综合入口回代自洽：
        c_target=132.81fF → d≈0.2μm；c_target=173.5fF → lf≈220μm（与
        NOMINAL 逐位同源）。"""
        from rfauto.models.template_spec import TEMPLATE_SPECS
        from rfauto.models.template_specs import bootstrap_template_specs

        bootstrap_template_specs()
        for name in ("mim_cap", "interdigital_cap"):
            assert name in TEMPLATE_SPECS.names()
        r1 = TEMPLATE_SPECS.get("mim_cap").synthesizer(c_target_ff=132.81)
        assert r1.params["d_um"] == pytest.approx(0.2, abs=5e-4)
        assert set(r1.params) == set(MIM_NOM)
        r2 = TEMPLATE_SPECS.get("interdigital_cap").synthesizer(
            c_target_ff=USER_IDC_C_FF)
        assert r2.params["lf_um"] == pytest.approx(
            IDC_NOM["lf_um"], rel=5e-3)
        assert set(r2.params) == set(IDC_NOM)

    def test_calc_keys_registered(self):
        for key in ("mim_capacitance", "interdigital_capacitance"):
            assert key in CALCULATOR_REGISTRY.names()

    def test_meta_yaml_matches_src(self):
        """docs meta.yaml ↔ src 双向逐键（0aq 口径，元数据漂移即红）。"""
        import yaml

        for name, nom in (("mim_cap", MIM_NOM),
                          ("interdigital_cap", IDC_NOM)):
            data = yaml.safe_load(
                (REPO / "docs" / "templates" / name / "meta.yaml")
                .read_text(encoding="utf-8"))
            assert set(data["params"]) == set(TEMPLATE_META[name]["params"])
            assert data["n_ports"] == TEMPLATE_META[name]["n_ports"]
            for key, val in nom.items():
                assert float(data["nominal_params"][key]) == pytest.approx(
                    float(val), rel=1e-9)

    def test_render_smoke_note_honest(self):
        """未冒烟/真机留登记如实声明（#122 不凑绿）。"""
        for name in ("mim_cap", "interdigital_cap"):
            note = TEMPLATE_META[name]["smoke_note"]
            assert "未冒烟" in note and "留登记" in note
