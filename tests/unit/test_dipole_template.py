"""WP1.3 dipole 模板官方口径重写单测（refs §8：自由空间 + LumpedPort 直馈）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))


def test_dipole_render_free_space_and_lumped_feed():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("dipole", {"dipole_len_mm": 58.0,
                                    "dipole_w_mm": 2.0, "gap_mm": 2.0},
                         (2.25, 2.75))
    # 官方口径：自由空间无基板无地，域全 MUR，LumpedPort 中央直馈
    assert "AddLumpedPort(1, 50.0" in text
    assert 'CSX.AddMaterial("substrate"' not in text
    assert '"MUR", "MUR"' in text  # 底边界 MUR（非 PEC 地）
    assert "PEC" not in text.split("SetBoundaryCond")[1].split("]")[0]


def test_mline_render_keeps_pec_ground():
    """非辐射 guided 模板保持 z 底 PEC 地口径（回归守卫）。"""
    from rfauto.adapters.openems_templates import render_script

    text = render_script("mline", {"w_mm": 1.113, "line_len_mm": 40.0},
                         (2.25, 2.75))
    assert '"PEC", "MUR"' in text
    assert 'CSX.AddMaterial("substrate"' in text


def test_dipole_nominal_unchanged():
    from rfauto.adapters.openems_templates import TEMPLATE_META

    assert TEMPLATE_META["dipole"]["params"] == [
        "dipole_len_mm", "dipole_w_mm", "gap_mm"]


def test_dipole_meta_extraction_updated_to_lumped():
    """#194 官方口径重写后馈电=LumpedPort，meta 文案不得残留 MSLPort。"""
    from rfauto.adapters.openems_templates import TEMPLATE_META

    assert "LumpedPort" in TEMPLATE_META["dipole"]["extraction"]
    assert "MSLPort" not in TEMPLATE_META["dipole"]["extraction"]


def test_fake_dipole_dispatch_valley_position():
    """fake 派发：单端口谐振谷，谷位=λ/2 闭式 c/(2L)，随 L 精确移动。"""
    import numpy as np

    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="dipole", n_ports=1,
                     freq_ghz=(1.5, 3.5, 401), f0_ghz=2.4)
    ad.connect({})
    ad.set_variables({"dipole_len_mm": "58mm"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    assert net.s.shape[1] == 1  # 单端口
    s11_db = 20 * np.log10(np.abs(net.s[:, 0, 0]) + 1e-30)
    f_res = float(net.f[np.argmin(s11_db)])  # skrf .f 恒为 Hz
    assert f_res == pytest.approx(299792458.0 / (2 * 58e-3), rel=0.01)
    # 谷深 ≈ (73−50)/(73+50) → −14.5dB（Balanis R_rad 一阶口径）
    assert s11_db.min() == pytest.approx(-14.55, abs=0.5)


def test_synthesize_dipole_model_roundtrip_and_valley_objective():
    """综合：f0 → L=c/(2f0) 回代自洽；objectives 必须谷深语义（#197）。"""
    from rfauto.core.synthesis import synthesize_dipole_model

    result = synthesize_dipole_model(f0_ghz=2.4)
    assert result.model == "dipole"
    assert result.params["dipole_len_mm"] == pytest.approx(62.4551, abs=0.01)
    assert result.params["dipole_len_mm"] == pytest.approx(
        299.792458 / (2 * 2.4), abs=0.01)
    obj = result.recipe_draft["objectives"][0]
    assert obj["metric"] == "s11_db_min" and obj["op"] == "max_below"


def test_dipole_spec_wiring():
    """TemplateSpec 接线：dipole 六件套可见可取（WP1.3 收尾）。"""
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("dipole")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    assert spec.physics_roles["dipole_len_mm"] == "resonator_length_mm"
    # draft_recipe 端到端（确定性内核，零求解）
    draft = TEMPLATE_SPECS.draft_recipe("dipole", f0_ghz=3.0)
    assert draft["model"] == "dipole"
    assert draft["params"]["dipole_len_mm"]["value"] == pytest.approx(
        299.792458 / 6.0, abs=0.01)
