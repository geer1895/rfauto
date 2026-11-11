"""layered_stack 族批 2 注册链钉（aurora_q Q-X6 席；#304 注册五消费者+铁律 7）。

钉面（批 1 91ef1a1c=schema+双引擎渲染+lint；批 2=注册+nominal 精算账本）：
- **nominal 反解自洽链**：design_params()（Z0 目标 → strip 宽二分反解）
  正向复算 |Z0(w*)−目标|≤1e-9Ω（#118 独立裁判）+TEMPLATE_NOMINAL 归档
  字面量=反解单源回代钉（ring_resonator 全精度精算先例）+§2.1 HFSS
  实测 50.2Ω 锚对照记录（锚点 Z0 闭式现算零手抄）；
- **注册契约**：TEMPLATE_META/TEMPLATE_NOMINAL/_TEMPLATE_PORT_AXES/
  _TEMPLATE_RADIATOR 四表新键+计数 75→76+meta 契约字段；
- **分派**：render_script 早分发与批 1 家族渲染器逐字节等价+geometry_spec
  预览端口数=meta n_ports（#304 审计家法）；
- **审计查表**：TEMPLATE_MESH_MM 自动档（0.0=λ_sub/50@F_MAX，防 0.4mm
  缺省档混入 95GHz 物理错档）+声明参数全驱动几何（#304 布线家法）。

零网络零真机零 runs/ 写入（render/load_geometry 纯内存）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.layered_stack_spec import (
    DESIGN_Z0_JUDGE_OHM,
    MATERIALS,
    LayeredStackSpec,
    design_params,
)
from rfauto.adapters.oe_templates.registry import (
    _TEMPLATE_PORT_AXES,
    _TEMPLATE_RADIATOR,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
)
from rfauto.adapters.openems_templates import geometry_spec, render_script

BAND = (94.75, 95.25)   # meta f0=95.0 ±0.25（band_for 家法口径）
NOMINAL = dict(TEMPLATE_NOMINAL["layered_stack"])

#: §2.1 锚点（HFSS 实测背书 w=0.52→Z0≈50.2）
_ANCHOR_W_MM = 0.52
_ANCHOR_Z0_HFSS_OHM = 50.2


def _spec_from_nominal():
    from rfauto.adapters.oe_templates.render_core import (
        _layered_stack_spec_from_params,
    )
    return _layered_stack_spec_from_params(NOMINAL)


# ─── 1. nominal 反解自洽链（铁律 7 + #118 独立裁判）──────────────────────────

def test_design_params_inverse_self_consistent():
    """反解终点正向复算 |Z0(w*)−50|≤1e-9Ω（独立裁判阈 DESIGN_Z0_JUDGE_OHM）。"""
    dp = design_params()
    assert dp["z0_target_ohm"] == 50.0
    assert dp["z0_residual_ohm"] <= DESIGN_Z0_JUDGE_OHM, dp["z0_residual_ohm"]
    w = dp["params"]["strip_w_mm"]
    assert 0.02 <= w <= 2.0
    # 反解几何五键齐全（TEMPLATE_NOMINAL 同键集）
    assert set(dp["params"]) == {
        "strip_w_mm", "line_len_mm", "wafer_width_mm",
        "cavity_w_mm", "cavity_h_mm"}


def test_design_params_z0_monotonic_decreasing():
    """Z0(w) 在名义邻域严格单调降（二分反解前提；#118 前置校验同源）。"""
    from rfauto.core.calculators import _suspended_stripline_ri
    spec = LayeredStackSpec()
    b = float(spec.cavity.h_mm)
    h = float(spec.layers[spec.conductor_index()][1])
    er = float(MATERIALS[spec.layers[spec.conductor_index()][0]].er)
    ws = [0.3, 0.45, 0.5243362925046158, 0.7, 1.2]
    z0s = [_suspended_stripline_ri(w, b, h, er)[1] for w in ws]
    assert all(z0s[i] > z0s[i + 1] for i in range(len(z0s) - 1))


@pytest.mark.parametrize("target", [45.0, 50.0, 55.0])
def test_design_params_target_sweep_self_consistent(target):
    """多目标档反解全部过 1e-9 独立裁判（反解链非 50Ω 单点特调）。"""
    dp = design_params(z0_target_ohm=target)
    assert dp["z0_residual_ohm"] <= DESIGN_Z0_JUDGE_OHM
    assert abs(dp["z0_achieved_ohm"] - target) <= DESIGN_Z0_JUDGE_OHM


def test_design_params_anchor_hfss_record():
    """§2.1 HFSS 实测锚对照记录：锚点 Z0 闭式现算（非手抄）vs 50.2。"""
    dp = design_params()
    anchor = dp["anchor_hfss"]
    assert anchor["w_mm"] == _ANCHOR_W_MM
    assert anchor["hfss_measured_z0_ohm"] == _ANCHOR_Z0_HFSS_OHM
    # 锚点闭式现算（同参 _suspended_stripline_ri）对实测锚偏差 ≤0.1Ω
    # （实测 50.2513 vs 反馈 §2.1 记载 ≈50.2，经验锚对照非严格裁判）
    from rfauto.core.calculators import _suspended_stripline_ri
    spec = LayeredStackSpec()
    _, z0_anchor = _suspended_stripline_ri(
        _ANCHOR_W_MM, float(spec.cavity.h_mm),
        float(spec.layers[spec.conductor_index()][1]), 11.9)
    assert abs(z0_anchor - anchor["z0_closed_form_ohm"]) <= 1e-12
    assert abs(z0_anchor - _ANCHOR_Z0_HFSS_OHM) <= 0.1
    assert "§2.1" in anchor["source"]


def test_design_params_out_of_domain_rejected():
    """目标越可达域 fail-loud（bracket 守卫，非静默夹逼）。"""
    with pytest.raises(ValueError):
        design_params(z0_target_ohm=1e-3)


def test_nominal_matches_design_params_single_source():
    """TEMPLATE_NOMINAL 归档字面量=design_params 反解单源（回代钉）+名义点
    正向复算独立裁判 ≤1e-9（全精度字面量直判，非 round4 二次近似）。"""
    dp = design_params()
    assert abs(NOMINAL["strip_w_mm"]
               - dp["params"]["strip_w_mm"]) <= 1e-12
    for key in ("line_len_mm", "wafer_width_mm", "cavity_w_mm",
                "cavity_h_mm"):
        assert NOMINAL[key] == dp["params"][key], key
    # 名义点正向复算（独立第三方面：闭式正向，非反解残差转述）
    from rfauto.core.calculators import _suspended_stripline_ri
    spec = LayeredStackSpec()
    _, z0 = _suspended_stripline_ri(
        NOMINAL["strip_w_mm"], float(spec.cavity.h_mm),
        float(spec.layers[spec.conductor_index()][1]),
        float(MATERIALS[
            spec.layers[spec.conductor_index()][0]].er))
    assert abs(z0 - 50.0) <= DESIGN_Z0_JUDGE_OHM


def test_nominal_spec_builds_valid_family_constant_layers():
    """参数面 → spec 桥：名义点合法（校验器 fail-loud 全过）+layers=族常量
    （§3.4 示例，不入参数表）+腔 z0 对称派生。"""
    spec = _spec_from_nominal()
    assert spec.conductor.width_mm == NOMINAL["strip_w_mm"]
    assert spec.cavity.w_mm == NOMINAL["cavity_w_mm"]
    assert spec.cavity.h_mm == NOMINAL["cavity_h_mm"]
    assert spec.cavity.z0_mm == -NOMINAL["cavity_h_mm"] / 2.0
    assert spec.line_len_mm == NOMINAL["line_len_mm"]
    assert spec.wafer_width_mm == NOMINAL["wafer_width_mm"]
    assert spec.layers == LayeredStackSpec().layers   # 族常量直通缺省
    assert spec.conductor.layer == LayeredStackSpec().conductor.layer


# ─── 2. 注册契约（#304 五消费者链 seat 局部钉）────────────────────────────────

def test_registered_in_all_tables():
    """四表新键：TEMPLATE_META/TEMPLATE_NOMINAL/端口轴/辐射器位。"""
    assert "layered_stack" in TEMPLATE_META
    assert "layered_stack" in TEMPLATE_NOMINAL
    assert _TEMPLATE_PORT_AXES["layered_stack"] == ("x",)
    assert _TEMPLATE_RADIATOR["layered_stack"] is False


def test_meta_contract_fields():
    """meta 契约字段（TEMPLATE_META 公约）+params/nominal 键集自洽。"""
    meta = TEMPLATE_META["layered_stack"]
    assert meta["f0_ghz"] == 95.0
    assert meta["n_ports"] == 2
    assert meta["mesh_resolution_mm"] == 0.0
    assert meta["n_segments"] is None
    assert meta["max_time_ns"] > 0
    for key in ("extraction", "topology", "param_semantics", "mesh_note",
                "params"):
        assert meta.get(key), key
    assert set(meta["params"]) == set(TEMPLATE_NOMINAL["layered_stack"])


def test_template_meta_count_76_sources():
    """计数 75→76 三源同数：registry 表长+check_numbers.count_template_meta
    同源（scripts 非包，按 test_check_numbers 装载法单源消费）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_qxl6_check_numbers", REPO / "scripts" / "check_numbers.py")
    cn = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cn)
    assert len(TEMPLATE_META) == 76
    assert len(TEMPLATE_NOMINAL) == 76
    assert cn.count_template_meta() == 76


def test_meta_yaml_keys_match_src():
    """docs/templates/layered_stack/meta.yaml 键集+数值与 src 双侧严格相等
    （0aq 家法 seat 局部钉；全局参数化门在 test_template_meta_consistency）。"""
    import yaml

    data = yaml.safe_load(
        (REPO / "docs" / "templates" / "layered_stack" / "meta.yaml")
        .read_text(encoding="utf-8"))
    assert data["template"] == "layered_stack"
    assert set(data["params"]) == set(TEMPLATE_META["layered_stack"]["params"])
    assert set(data["nominal_params"]) == set(NOMINAL)
    for key, val in NOMINAL.items():
        assert abs(float(data["nominal_params"][key]) - float(val)) <= 1e-15
    assert float(data["f0_ghz"]) == TEMPLATE_META["layered_stack"]["f0_ghz"]
    assert int(data["n_ports"]) == 2


# ─── 3. 分派（render_script 早分发/geometry_spec 预览）────────────────────────

def test_render_dispatch_byte_equal_family_renderer():
    """render_script 注册路径与批 1 家族渲染器直调逐字节等价（早分发纯
    换算零改写）。"""
    from rfauto.adapters.oe_templates.render_layered_stack import (
        render_layered_stack,
    )

    via_registry = render_script("layered_stack", dict(NOMINAL), BAND)
    direct = render_layered_stack(_spec_from_nominal(),
                                  freq_range_ghz=BAND)
    assert via_registry == direct
    assert "StripLinePort(CSX" in via_registry
    assert "F0 = 95000000000.0" in via_registry
    assert "FC = 250000000.0" in via_registry


def test_render_dispatch_rejects_bad_excite_port():
    """excite_port 越域（n_ports=2）显式拒绝（meta 感知校验）。"""
    with pytest.raises(ValueError):
        render_script("layered_stack", dict(NOMINAL), BAND, excite_port=3)


def test_geometry_spec_preview_ports_two():
    """geometry_spec 预览：双端口=meta n_ports（#304 审计钉）+盒面齐全。"""
    gs = geometry_spec("layered_stack", dict(NOMINAL))
    assert len(gs["ports"]) == TEMPLATE_META["layered_stack"]["n_ports"]
    names = {b["name"] for b in gs["boxes"]}
    assert "vacuum_box" in names
    assert any("strip" in n for n in names)
    assert any("cavity_wall" in n for n in names)


# ─── 4. 审计查表与布线（#304 家法）────────────────────────────────────────────

def test_audit_mesh_lookup_auto_base():
    """TEMPLATE_MESH_MM 登记自动档 0.0 → load_geometry BASE=λ_sub/50
    @F_MAX（防 0.4mm 缺省档混入 95GHz 物理错档）。"""
    from tests.unit import _geometry_audit_helpers as gh

    assert gh.TEMPLATE_MESH_MM["layered_stack"] == 0.0
    scope, _prims = gh.load_geometry("layered_stack")
    er_max = max(float(MATERIALS[m].er) for m, _t in LayeredStackSpec().layers
                 if not MATERIALS[m].is_metal)
    base_expected_mm = (299.792458 / BAND[1] / math.sqrt(er_max) / 50.0)
    assert float(scope["BASE"]) * 1e3 == pytest.approx(base_expected_mm,
                                                       rel=1e-9)
    assert base_expected_mm < 0.05   # 95GHz 档量级守卫（≠0.4 缺省档）


def test_audit_all_declared_params_drive_geometry():
    """声明参数全驱动几何（#304 布线家法；cavity_w/h 越域守卫走
    PERTURB_OVERRIDES 保域档）。"""
    from tests.unit import _geometry_audit_helpers as gh

    declared = list(TEMPLATE_META["layered_stack"]["params"])
    changed = gh.geometry_changing_params("layered_stack", declared)
    assert set(declared) <= changed, sorted(set(declared) - changed)


def test_audit_load_geometry_port_feed_connectivity():
    """审计面实测：双端口对象=meta n_ports 且馈点同属载带网络（strip+馈段
    单分量；腔壁/键合环分量 DC 隔离不计）。"""
    from tests.unit import _geometry_audit_helpers as gh

    scope, prims = gh.load_geometry("layered_stack")
    ports = gh.port_objects(scope)
    assert sorted(ports) == [1, 2]
    conductors, labels = gh.conductor_labels(prims)
    comps = {n: gh.containing_labels(gh.port_feed_point(p), conductors,
                                     labels)
             for n, p in ports.items()}
    assert comps[1] & comps[2], "双端口须同属载带网络"


def test_golden_snapshot_registered():
    """EC-8 golden 覆盖：layered_stack 快照在档且当前渲染零漂移。"""
    from rfauto.service.template_golden_service import (
        compute_template_digest,
        golden_path,
    )

    path = golden_path("layered_stack")
    assert path.exists(), path
    import yaml

    stored = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert stored["template"] == "layered_stack"
    assert stored["status"] == "ok"
    current = compute_template_digest("layered_stack")
    assert current["script_sha256"] == stored["script_sha256"]
