"""slotline_service 单测：JSON 信封契约 + 内核透传（数值只出内核）。

口径：
- 成功信封 ok=True，数值与 core 直调逐位相等（service 零复算）；
- 越有效域/不可达/参数非法 → ok=False + error 字符串，绝不抛出；
- realizable=False 是合法结果（ok=True），不进 error（#122 不凑绿）；
- 全部信封 json.dumps 可序列化（MCP/CLI 直出）。
锚：core/slotline_transitions 模块 docstring 设计点
（w=1.0/h=1.524/εr=3.66@2.5GHz → Z0=110.92Ω/εeff=1.6462/λ'=93.462mm）。
"""

from __future__ import annotations

import json

import pytest

from rfauto.service import slotline_service as svc

_SUB = dict(h_mm=1.524, epsilon_r=3.66, freq_ghz=2.5)
_TRANSITION_ARGS = dict(f0_ghz=2.5, h_mm=1.524, er=3.66, w_slot_mm=1.0)


class TestSlotlineAnalysisSynthesis:
    def test_analysis_matches_core_and_is_json(self):
        from rfauto.core.calculators import slotline_analysis as core_fn

        data = svc.slotline_analysis(1.0, **_SUB)
        assert data["ok"] is True
        assert data["result"] == core_fn(1.0, 1.524, 3.66, 2.5)
        assert data["result"]["z0_ohm"] == pytest.approx(110.92, abs=0.01)
        assert data["result"]["eps_eff"] == pytest.approx(1.6462, abs=1e-4)
        assert data["result"]["lambda_g_mm"] == pytest.approx(93.462, abs=1e-3)
        json.dumps(data)

    @pytest.mark.parametrize("kwargs, needle", [
        (dict(w_mm=1.0, h_mm=0.508, epsilon_r=3.66, freq_ghz=2.5), "d/λ0"),   # 域外
        (dict(w_mm=-1.0, h_mm=1.524, epsilon_r=3.66, freq_ghz=2.5), "正有限数"),
        (dict(w_mm=1.0, h_mm=1.524, epsilon_r=12.0, freq_ghz=2.5), "9.8"),  # 高 εr 段未实现
    ])
    def test_analysis_rejections_are_envelopes(self, kwargs, needle):
        data = svc.slotline_analysis(**kwargs)
        assert data["ok"] is False
        assert needle in data["error"]

    def test_analysis_string_input_coerced(self):
        data = svc.slotline_analysis("1.0", "1.524", "3.66", "2.5")
        assert data["ok"] is True
        assert data["result"]["z0_ohm"] == pytest.approx(110.92, abs=0.01)

    def test_synthesis_roundtrip_and_unreachable(self):
        data = svc.slotline_synthesis(110.92, **_SUB)
        assert data["ok"] is True
        assert data["result"]["w_mm"] == pytest.approx(1.0, abs=2e-3)
        assert data["result"]["z0_actual_ohm"] == pytest.approx(110.92, abs=0.01)
        bad = svc.slotline_synthesis(500.0, **_SUB)
        assert bad["ok"] is False
        assert "可达范围" in bad["error"]
        neg = svc.slotline_synthesis(-50.0, **_SUB)
        assert neg["ok"] is False


class TestTransitionDesigns:
    def test_msl_slot_transition_matches_core(self):
        from rfauto.core.slotline_transitions import TRANSITION_GATES, transition_design

        data = svc.msl_slot_transition_design(**_TRANSITION_ARGS)
        assert data["ok"] is True
        assert data["design"] == transition_design(2.5, 1.524, 3.66, 1.0).to_dict()
        assert data["gates"] == TRANSITION_GATES
        assert data["design"]["l_stub_mm"] == pytest.approx(18.3725, abs=1e-3)
        assert data["design"]["l_short_mm"] == pytest.approx(23.3656, abs=1e-3)
        assert data["design"]["w_msl_mm"] == pytest.approx(3.3439, abs=1e-3)
        json.dumps(data)

    def test_msl_slot_transition_out_of_domain_envelope(self):
        data = svc.msl_slot_transition_design(2.5, 0.508, 3.66, 1.0)
        assert data["ok"] is False
        assert "不外推" in data["error"]

    def test_marchand_balun_design_adds_slot_spacing(self):
        from rfauto.core.slotline_transitions import BALUN_GATES

        data = svc.marchand_balun_design(**_TRANSITION_ARGS)
        assert data["ok"] is True
        d = data["design"]
        assert data["gates"] == BALUN_GATES
        assert d["d_center_mm"] == pytest.approx(d["w_msl_mm"] + d["w_slot_mm"], abs=1e-3)
        assert d["a2_mm"] - d["a1_mm"] == pytest.approx(d["w_slot_mm"], abs=1e-3)
        assert d["a1_mm"] + d["a2_mm"] == pytest.approx(d["d_center_mm"], abs=1e-3)
        json.dumps(data)


class TestMarchandTwoSectionSynthesis:
    def test_nominal_defaults_realizable_gates_pass(self):
        from rfauto.core.slotline_transitions import MARCHAND2_GATES

        data = svc.marchand_two_section_synthesis()
        assert data["ok"] is True
        d = data["design"]
        assert d["realizable"] is True
        assert d["model_metrics"]["all_gates_pass"] is True
        assert data["gates"] == MARCHAND2_GATES
        assert data["nominal_params"] == {
            "w_mm": pytest.approx(1.7616, abs=1e-3),
            "s_mm": pytest.approx(0.1016, abs=1e-3),
            "l_sect_mm": pytest.approx(18.467, abs=1e-3),
            "w_feed_mm": pytest.approx(3.3439, abs=1e-3),
            "w_bal_line_mm": pytest.approx(0.2981, abs=1e-3),
            "r_bal_se_ohm": pytest.approx(140.0),
        }
        assert isinstance(d["notes"], list) and d["notes"]
        json.dumps(data)

    def test_unrealizable_is_result_not_error(self):
        # 常规 50→100Ω 差分：边耦合微带 L 下限实证不可达
        data = svc.marchand_two_section_synthesis(2.5, 50.0, 100.0)
        assert data["ok"] is True
        assert data["design"]["realizable"] is False
        json.dumps(data)

    def test_band_override_propagates(self):
        data = svc.marchand_two_section_synthesis(band_ghz=[2.3, 2.7])
        assert data["ok"] is True
        assert data["design"]["model_metrics"]["band_ghz"] == [2.3, 2.7]

    @pytest.mark.parametrize("kwargs, needle", [
        (dict(band_ghz=[3.0]), "两元素"),
        (dict(band_ghz=[3.0, 2.0]), "f_lo < f_hi"),
        (dict(band_ghz="ab"), "两元素"),
        (dict(z_c_ohm=-5.0), "阻抗须 >0"),
        (dict(f0_ghz=0.0), "须 >0"),
        (dict(s_min_mm=-0.1), "须 >0"),
    ])
    def test_invalid_inputs_are_envelopes(self, kwargs, needle):
        data = svc.marchand_two_section_synthesis(**kwargs)
        assert data["ok"] is False
        assert needle in data["error"]
