"""槽线族四模板注册四件套同步 + fake 派发（2026-09-18）。

覆盖（followUps ④/0df②/0dl①，审计 #12/#17 修复）：
- TEMPLATE_META/TEMPLATE_NOMINAL（openems_templates 文末 SLOTLINE_FAMILY 段，
  整脚本渲染器分发）/ docs meta.yaml ×4 / template_specs / EXPECTED_TEMPLATES
  （单源=审计文件）/ fake_adapter 派发分支；
- fake 解析模型数值口径：路线 A 匹配线（β 锚）/路线 B 并联抽头（#250 装配）/
  过渡 Knorr 一阶等效（无耗互易、f0 邻域匹配）/巴伦两节对称耦合段电路级
  （理想 3 端口 S：S11=0、|S21|=|S31|=1/√2、180°）；
- 槽线闭式计算器键（slotline_analysis/slotline_synthesis）与综合/路由链路。

设计点（#1c 全闭式精算）：h=1.524（RO4350B 60mil，JS 闭式域 d/λ0≥0.006，
缺省叠层 0.508@2.5GHz 落域外）；w=1.0 → Z0=110.92Ω/εeff=1.6462/λ'=93.4624mm。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters import openems_templates as ot
from rfauto.core.slotline import (
    slotline_beta,
    slotline_closed_form,
    slotline_z0,
)

SLOTLINE_FAMILY = ot.SLOTLINE_FAMILY_TEMPLATES
F0 = 2.5


def _meta_yaml(template: str) -> dict:
    path = REPO / "docs" / "templates" / template / "meta.yaml"
    assert path.exists(), path
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class TestSlotlineFamilyRegistration:
    """四件套同步：TEMPLATE_META/NOMINAL × meta.yaml × EXPECTED_TEMPLATES × specs。"""

    def test_family_registry_tail_appended(self):
        from tests.unit.test_template_geometry_audit import (
            EXPECTED_TEMPLATES as _ET,
        )

        assert set(SLOTLINE_FAMILY) <= set(ot.TEMPLATE_META)
        assert set(SLOTLINE_FAMILY) <= set(ot.TEMPLATE_NOMINAL)
        # 同对象注册（单一事实源，非拷贝）
        for t in SLOTLINE_FAMILY:
            assert ot.TEMPLATE_META[t] is getattr(
                ot, {"slotline": "SLOTLINE_META", "slotline_lumped":
                     "SLOTLINE_LUMPED_META", "msl_slot_transition":
                     "MSL_SLOT_TRANSITION_META", "marchand_balun":
                     "MARCHAND_BALUN_META"}[t])
            assert ot.TEMPLATE_NOMINAL[t] is getattr(
                ot, {"slotline": "SLOTLINE_NOMINAL", "slotline_lumped":
                     "SLOTLINE_LUMPED_NOMINAL", "msl_slot_transition":
                     "MSL_SLOT_TRANSITION_NOMINAL", "marchand_balun":
                     "MARCHAND_BALUN_NOMINAL"}[t])
        # 既有键未被重排（尾部追加契约，坑 #247）：新键恰在字典尾部
        # 串馈毫米波阵批起：槽线族位次退居尾 10..6，ms 四件居尾 6..2，
        # coil_nfc 尾 2、mmwave_series_array 尾 1（仍钉）
        assert list(ot.TEMPLATE_META)[-10:-6] == list(SLOTLINE_FAMILY)
        assert list(ot.TEMPLATE_META)[-6:-2] == ["ms_patch", "ms_cross",
                                                 "ms_jcross", "ms_array_NxN"]
        assert list(ot.TEMPLATE_META)[-1] == "mmwave_series_array"
        # 42→43：hairpin_alt 注册在 hairpin 之后（同族段内），槽线族仍居尾；
        # 计数只与单源比对（#247 禁轨内自钉），字面基线在审计文件单点钉
        assert len(ot.TEMPLATE_META) == len(ot.TEMPLATE_NOMINAL) == len(_ET)

    def test_expected_templates_single_source(self):
        from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

        assert set(SLOTLINE_FAMILY) <= EXPECTED_TEMPLATES
        assert len(ot.TEMPLATE_META) == len(EXPECTED_TEMPLATES)

    @pytest.mark.parametrize("template", sorted(SLOTLINE_FAMILY))
    def test_meta_yaml_matches_template_meta(self, template):
        data = _meta_yaml(template)
        meta = ot.TEMPLATE_META[template]
        nominal = ot.TEMPLATE_NOMINAL[template]
        assert data["template"] == template
        assert float(data["f0_ghz"]) == pytest.approx(float(meta["f0_ghz"]))
        assert int(data["n_ports"]) == int(meta["n_ports"])
        assert list(data["params"]) == list(meta["params"])
        for key, value in data["nominal_params"].items():
            assert float(value) == pytest.approx(float(nominal[key])), key
        assert "smoke_note" in data, f"{template}: 真机冒烟判读须入 meta.yaml"
        # 基板口径：h=1.524 设计点（闭式域要求），er 缺省 3.66
        assert float(data["substrate"]["h_mm"]) == pytest.approx(1.524)
        assert float(data["substrate"]["er"]) == pytest.approx(3.66)

    @pytest.mark.parametrize("template", sorted(SLOTLINE_FAMILY))
    def test_template_specs_entry(self, template):
        from rfauto.models.template_spec import TEMPLATE_SPECS
        from rfauto.models.template_specs import bootstrap_template_specs

        bootstrap_template_specs()
        spec = TEMPLATE_SPECS.get(template)
        assert spec.meta["n_ports"] == ot.TEMPLATE_META[template]["n_ports"]
        assert callable(TEMPLATE_SPECS.component(template, "render_script"))
        assert callable(TEMPLATE_SPECS.component(template, "fake_model"))
        # 综合入口可跑且 4 位舍入 == NOMINAL（同 coupled_bpf 契约）
        draft = spec.synthesizer()
        for key, value in draft.params.items():
            assert value == pytest.approx(float(ot.TEMPLATE_NOMINAL[template][key]),
                                          abs=5e-5), key

    @pytest.mark.parametrize("template", sorted(SLOTLINE_FAMILY))
    def test_geometry_spec_port_count(self, template):
        spec = ot.geometry_spec(template, dict(ot.TEMPLATE_NOMINAL[template]))
        assert len(spec["ports"]) == int(ot.TEMPLATE_META[template]["n_ports"])
        assert any(b["material"] == "substrate" for b in spec["boxes"])

    @pytest.mark.parametrize("template", sorted(SLOTLINE_FAMILY))
    def test_render_script_smoke_and_routing(self, template):
        text = ot.render_script(template, dict(ot.TEMPLATE_NOMINAL[template]),
                                (2.25, 2.75), mesh_resolution_mm=0.4)
        assert "FDTD.Run(" in text
        # 整脚本渲染器路由到附加模块（非 _patch_lines 兜底）：
        assert text.index("FDTD.Run(") > 2000
        if template == "slotline":
            assert "WaveguidePort" in text and "slot_mode_E.h5" in text
        elif template == "slotline_lumped":
            assert "LumpedPort" in text
        elif template == "msl_slot_transition":
            assert "MSLPort" in text and "LumpedPort" in text
        else:
            assert text.count("LumpedPort(") == 2 and "MSLPort(" in text

    def test_route_a_mode_file_contract(self):
        """路线 A：模式文件缺省名是占位——meta.yaml 必须写明预生成前置（真跑
        会缺文件报错）；kc/z_mode 缺省由闭式反解。"""
        note = ot.TEMPLATE_META["slotline"]["smoke_note"]
        assert "solve_slotline_mode" in note and "write_slotline_mode_files" in note
        r = slotline_closed_form(1.0, 1.524, 3.66, F0)
        text = ot.render_script("slotline", {"w_mm": 1.0, "line_len_mm": 93.4624,
                                             "h_mm": 1.524, "er": 3.66},
                                (2.25, 2.75))
        assert repr(round(r.z0_ohm, 4)) in text   # z_mode=闭式 Z0 缺省注入


class TestSlotlineFamilyFakeDispatch:
    """fake 派发数值口径（数值只在 core 闭式内核，铁律 7）。"""

    F = np.linspace(2.25, 2.75, 21)

    def test_route_a_matched_line_beta_anchor(self):
        """短段（L≪λ'，无相位缠绕）：S21 相位=−β·L 逐位对照闭式，β 随槽宽移动。"""
        from rfauto.adapters.fake_adapter import _slotline_route_a_sparams

        r1 = slotline_closed_form(1.0, 1.524, 3.66, F0)
        r14 = slotline_closed_form(1.4, 1.524, 3.66, F0)
        l_mm = 10.0                              # ≪ λ'，相位不缠绕
        f = np.array([2.3, 2.5, 2.7])
        s1 = _slotline_route_a_sparams(f, w_mm=1.0, line_len_mm=l_mm)
        s14 = _slotline_route_a_sparams(f, w_mm=1.4, line_len_mm=l_mm)
        for k, f_ghz in enumerate(f):
            rk = slotline_closed_form(1.0, 1.524, 3.66, float(f_ghz))
            assert np.angle(s1[k, 1, 0]) == pytest.approx(
                -rk.beta_rad_m * 1e-3 * l_mm, abs=1e-9), f_ghz
        assert -np.angle(s14[1, 1, 0]) / (l_mm * 1e-3) == pytest.approx(
            r14.beta_rad_m, rel=1e-9)
        assert r14.beta_rad_m < r1.beta_rad_m    # 宽槽 εeff 略降（闭式单调）
        assert abs(s1[1, 0, 0]) <= 1e-3          # 匹配线 S11 数值底

    def test_route_b_tap_topology_baselines(self):
        from rfauto.adapters.fake_adapter import _slotline_route_b_sparams

        s = _slotline_route_b_sparams(self.F)
        i0 = 10
        # βL=2π（L=1λ'）、R=Z0：带载口径解析必然 S11_raw=−1/2/S21_raw=+1/2（#250）；
        # 装配到 50Ω 基后量级保持（fake=抽头顶基口径，非匹配线）
        assert 0.25 < abs(s[i0, 0, 0]) < 0.45
        assert 0.55 < abs(s[i0, 1, 0]) < 0.8
        assert s[0, 0, 1] == pytest.approx(s[0, 1, 0], rel=1e-12)  # 对称装配
        # 无源性（tanδ 一阶损耗口径下 ≤1）
        assert np.max(np.abs(s[:, 0, 0]) ** 2 + np.abs(s[:, 1, 0]) ** 2) <= 1.0 + 1e-9
        # r_port 失配档灵敏度（R≠Z0 → S11 抬升）
        s_hi = _slotline_route_b_sparams(self.F, r_port_ohm=200.0)
        assert abs(s_hi[i0, 0, 0]) > abs(s[i0, 0, 0])

    def test_transition_knorr_equivalent_circuit(self):
        from rfauto.adapters.fake_adapter import _msl_slot_transition_sparams

        s = _msl_slot_transition_sparams(self.F)
        i0 = 10
        # 无耗互易
        for k in range(len(self.F)):
            m = s[k]
            assert abs(m[0, 1] - m[1, 0]) < 1e-12
            assert abs(m[0, 0]) ** 2 + abs(m[1, 0]) ** 2 <= 1.0 + 1e-9
        # f0 邻域匹配（Knorr 一阶口径；带内形状=两 λ/4 失谐包络）
        s11_db = 20 * math.log10(abs(s[i0, 0, 0]))
        assert s11_db < -8.0
        assert abs(s[i0, 1, 0]) < 1.0

    def test_balun_ideal_two_section_circuit(self):
        from rfauto.adapters.fake_adapter import _marchand_balun_sparams

        s = _marchand_balun_sparams(self.F)
        i0 = 10
        assert abs(s[i0, 0, 0]) < 1e-6
        assert abs(abs(s[i0, 1, 0]) - 1 / math.sqrt(2)) < 1e-6
        assert abs(abs(s[i0, 2, 0]) - 1 / math.sqrt(2)) < 1e-6
        assert abs(s[i0, 1, 0] + s[i0, 2, 0]) < 1e-9      # 180° 反相
        assert np.max(np.abs(s.conj().transpose(0, 2, 1) @ s
                             - np.eye(3))) < 1e-9          # 无耗

    @pytest.mark.parametrize("template", sorted(SLOTLINE_FAMILY))
    def test_dispatch_reaches_slotline_family(self, template):
        """model_type 路由：FakeAdapter solve 对四模板各出合法 Network
        （coupler2 test_fake_dispatch_c4 同款管道；n_ports/f0 与 meta 一致）。"""
        from rfauto.adapters.fake_adapter import FakeAdapter

        n_ports = int(ot.TEMPLATE_META[template]["n_ports"])
        ad = FakeAdapter(model_type=template, n_ports=n_ports,
                         freq_ghz=(2.25, 2.75, 11), f0_ghz=F0)
        ad.connect({})
        ad.set_variables({k: str(v) for k, v in
                          ot.TEMPLATE_NOMINAL[template].items()})
        report = ad.solve("main_setup")
        assert report.success, (template, report.message)
        net = ad.get_sparams()
        assert net.s.shape == (11, n_ports, n_ports), template
        assert np.max(np.abs(net.s)) > 0.0


class TestSlotlineCalculatorWiring:
    """闭式计算器键注册（#231 三表同步见 test_calculators/test_physics_invariants）。"""

    def test_analysis_synthesis_round_trip(self):
        from rfauto.service.calculator_service import run_calculator

        out = run_calculator("slotline_synthesis", {
            "z0_ohm": 110.92, "h_mm": 1.524, "epsilon_r": 3.66, "freq_ghz": F0})
        assert out["ok"], out
        w = out["result"]["w_mm"]
        assert abs(w - 1.0) < 1e-3
        chk = run_calculator("slotline_analysis", {
            "w_mm": w, "h_mm": 1.524, "epsilon_r": 3.66, "freq_ghz": F0})
        assert chk["ok"] and abs(chk["result"]["z0_ohm"] - 110.92) < 0.01
        assert abs(chk["result"]["eps_eff"] - 1.6462) < 1e-3
        # 独立内核互证：slotline_z0/β 与计算器同源闭式（不同入口）
        assert abs(slotline_z0(w, 1.524, 3.66, F0) - 110.92) < 0.01
        assert abs(slotline_beta(w, 1.524, 3.66, F0)
                   - chk["result"]["beta_rad_m"]) < 1e-3

    def test_default_stackup_explicitly_rejected(self):
        """缺省叠层 0.508@2.5GHz 落 JS 闭式域外 → 显式拒绝不外推（0df 遗留口径）。"""
        from rfauto.service.calculator_service import run_calculator

        out = run_calculator("slotline_analysis", {
            "w_mm": 1.0, "h_mm": 0.508, "epsilon_r": 3.66, "freq_ghz": F0})
        assert not out["ok"] and "有效域" in out["error"]
