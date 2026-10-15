"""WP2.1 对称带状线锚单测：渲染（StripLinePort 口径）/解析/综合/spec。

口径依据：绑定源码 L914+（StripLinePort：height=带-地半高、上下对称
电压探针）；上下地 = 域 z 边界 PEC（对称双面敷铜板 b=1.016 口径）。
TEM 模：εeff=εr 精确——β 锚判据最干净的闭式。几何边精确入网（#198
激励体积教训：盒边不进网格 → 吸附归零）。

_sub_cells_z z 向介质细分诊断档（W7-A z0 地板碰撞 followUp，预声明）：
N=细分倍率——z 网格 linspace(0, 2·H_SUB) 共 8N 格（N=1 → 9 点=旧口径
逐字节 #329）、介质盒每半层切 N 片同材料堆叠（共 2N 盒，界面 z=i·H/N
恰在网格线）。背景：W7-A 网格阶梯 m1→m2 x/y 加密 ~2× 而 z 恒 9 线
（runs/real_machine_window/w7a/stripline.*.verdict.json，eps_eff 已收敛
3.6601≈εr 而引擎 ZL 卡 44-45Ω 不随档收敛）——z0 仲裁 limit 项=z 向离散
（#313 z 向地板项 stripline 实证）。dt/预算注记（CFL 线性估）：z 最小格
H_SUB/(4N) 随 N 线性缩小 → dt 随全局最小格线性塌缩（0.4mm 审计档 N=3
实测网格 z 42.3µm 成全局最小格，单轴线性估 ÷2.2；自动档 ÷3.0）→ 真跑
须 _nrts 同档抬限（÷N 上界预留），防 #262/#266 截断假象。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))


def test_template_tables_have_stripline():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "stripline" in TEMPLATE_META
    assert TEMPLATE_META["stripline"]["n_ports"] == 2
    assert TEMPLATE_NOMINAL["stripline"]["w_mm"] == pytest.approx(0.5554,
                                                                  abs=0.02)
    assert _TEMPLATE_PORT_AXES["stripline"] == ("y",)
    assert _TEMPLATE_RADIATOR["stripline"] is False


def test_render_stripline_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("stripline", {"w_mm": 0.5554, "line_len_mm": 40.0},
                         (2.25, 2.75))
    assert "StripLinePort(CSX, port_nr=1" in text
    assert "StripLinePort(CSX, port_nr=2" in text
    assert "height=H_SUB" in text
    # 上下地 = z 域边界双 PEC（对称板口径）
    assert '"PEC", "PEC"' in text
    # 基板填满 0..2·H_SUB，z 网格含中面（带平面）
    assert "2 * H_SUB" in text
    assert 'np.linspace(0, 2 * H_SUB, 9)' in text
    assert 'CSX.AddMetal("stripline")' in text


def test_near_points_exact_edges():
    from rfauto.adapters.openems_templates import _near_points

    nx, ny = _near_points("stripline", {"w_mm": 0.5554,
                                        "line_len_mm": 40.0})
    # 带缘精确入网（#198 激励体积教训）——float 噪声用近似比较
    assert min(abs(v - 0.2777e-3) for v in nx) < 1e-12
    assert len(ny) == 3  # 0 + 线两端


def test_fake_stripline_dispatch_tem():
    """fake 派发：TEM εeff=εr=3.66——相位斜率恢复 εeff 必须等于 εr。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="stripline", n_ports=2,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"w_mm": "0.5554mm", "line_len_mm": "40mm"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    assert np.max(np.abs(net.s[:, 0, 0])) < 0.05  # 匹配线
    phase = np.unwrap(np.angle(net.s[:, 0, 1]))
    slope = np.polyfit(net.f, phase, 1)[0]
    eps_recovered = (slope * 299792458.0 / (-2 * np.pi * 40e-3)) ** 2
    assert eps_recovered == pytest.approx(3.66, rel=0.01)


def test_synthesize_stripline_model_roundtrip():
    from rfauto.core.calculators import _stripline_z0
    from rfauto.core.synthesis import synthesize_stripline_model

    result = synthesize_stripline_model(z0_ohm=50.0, freq_ghz=2.5,
                                        line_len_mm=40.0)
    assert result.model == "stripline"
    assert result.params["w_mm"] == pytest.approx(0.5554, abs=0.02)
    z0_back = _stripline_z0(result.params["w_mm"], 1.016, 3.66)
    assert z0_back == pytest.approx(50.0, abs=0.3)
    assert result.recipe_draft["model"] == "stripline"


def test_stripline_spec_wiring():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("stripline")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    draft = TEMPLATE_SPECS.draft_recipe("stripline", z0_ohm=50.0)
    assert draft["model"] == "stripline"


def test_meta_yaml_sync():
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META

    p = REPO / "docs" / "templates" / "stripline" / "meta.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["template"] == "stripline"
    assert data["n_ports"] == TEMPLATE_META["stripline"]["n_ports"]


# ── _sub_cells_z z 向介质细分诊断档（W7-A z0 地板碰撞 followUp）──────────────
# 判据全部在最终网格上实测（#368：效力断言与求解同参渲染，非字符串存在性）；
# exec 几何段秒级零仿真（#212 制度化）。CSXCAD 缺席环境诚实 skip。
_STL_NOMINAL = {"w_mm": 0.5554, "line_len_mm": 40.0}
_STL_BAND = (2.25, 2.75)     # TEMPLATE_META f0=2.5 ±0.25（audit 同带）
_STL_MESH_MM = 0.4           # audit 收敛档（DEFAULT_MESH_MM 同值）


def _stl_render(params: dict) -> str:
    from rfauto.adapters.openems_templates import render_script

    return render_script("stripline", params, _STL_BAND,
                         mesh_resolution_mm=_STL_MESH_MM)


def test_sub_cells_z_default_byte_identity():
    """缺省恒等（#329）：无键 / None / 显式 1 三态与名义渲染逐字节一致。"""
    base = _stl_render(dict(_STL_NOMINAL))
    assert base == _stl_render({**_STL_NOMINAL, "_sub_cells_z": 1})
    assert base == _stl_render({**_STL_NOMINAL, "_sub_cells_z": None})
    # 旧口径字面仍在（test_render_stripline_structure 双保险）
    assert 'np.linspace(0, 2 * H_SUB, 9)' in base


def test_sub_cells_z3_diff_surface_is_z_mesh_and_slices_only():
    """生效档差异面=恰 2 处：z linspace 9→25 一行 + 基板单盒→6 片堆叠
    （单变量字节实证，ge7 render_diff 同法）——端口/BASE/激励/提取链
    零改动。"""
    import difflib

    base = _stl_render(dict(_STL_NOMINAL)).splitlines()
    knob = _stl_render({**_STL_NOMINAL, "_sub_cells_z": 3}).splitlines()
    diff = list(difflib.unified_diff(base, knob, lineterm="", n=0))
    minus = [ln[1:] for ln in diff
             if ln.startswith("-") and not ln.startswith("---")]
    plus = [ln[1:] for ln in diff
            if ln.startswith("+") and not ln.startswith("+++")]
    assert minus == [
        'mesh.AddLine("z", np.linspace(0, 2 * H_SUB, 9))',
        'sub.AddBox((-BOARD, -BOARD, 0), (BOARD, BOARD, 2 * H_SUB), '
        'priority=0)',
    ]
    assert len(plus) == 7
    assert plus[0] == 'mesh.AddLine("z", np.linspace(0, 2 * H_SUB, 25))'
    assert all(
        ln.startswith("sub.AddBox((-BOARD, -BOARD, ")
        and "priority=0)   # 介质片 " in ln
        for ln in plus[1:])
    assert sum("（_sub_cells_z=3 细分档）" in ln for ln in plus[1:]) == 6


def test_sub_cells_z3_final_mesh_z_refined():
    """生效档最终网格实测（#368/#311 口径）：25 条 z 线 ≥ 基线 2 倍、均匀
    2H/(8N) 格、带平面 z=H_SUB 恰在网格线（中点）、介质 2N 片界面全部落
    网、全轴最小线距 ≥10µm（#152/#349 守卫）。"""
    pytest.importorskip("CSXCAD")
    from tests.unit import _geometry_audit_helpers as gh

    base_scope, _ = gh.load_geometry("stripline", dict(_STL_NOMINAL))
    z0 = gh.mesh_lines(base_scope, "z")
    assert len(z0) == 9          # 基线钉（缺省漂移即红）
    h_sub = float(base_scope["H_SUB"])
    scope, prims = gh.load_geometry(
        "stripline", {**_STL_NOMINAL, "_sub_cells_z": 3})
    z3 = gh.mesh_lines(scope, "z")
    assert len(z3) >= 2 * len(z0)            # 门口径：N=3 ≥ 2× 基线
    assert len(z3) == 25                     # 精确钉：8N+1
    assert np.allclose(np.diff(z3), 2 * h_sub / 24, atol=1e-12)
    assert np.isclose(z3[12], h_sub, atol=1e-12)   # 带平面在网格线
    subs = [p for p in prims if p.prop == "substrate"]
    assert len(subs) == 6                    # 2N 片同材料堆叠
    faces = sorted({float(p.lo[2]) for p in subs}
                   | {float(p.hi[2]) for p in subs})
    assert len(faces) == 7                   # 0, i·H/3 .. 2H（6 片 7 面）
    for f in faces:
        assert np.min(np.abs(z3 - f)) < 1e-12     # 界面全部落网
    for ax in ("x", "y", "z"):
        lines = gh.mesh_lines(scope, ax)
        assert float(np.min(np.diff(lines))) >= 10e-6   # #152/#349


def test_sub_cells_z_scales_with_n():
    """N=2 中间档：17 线（8N+1）、4 片——旋钮随 N 线性标度，非 N=3 硬编码。"""
    pytest.importorskip("CSXCAD")
    from tests.unit import _geometry_audit_helpers as gh

    scope, prims = gh.load_geometry(
        "stripline", {**_STL_NOMINAL, "_sub_cells_z": 2})
    z = gh.mesh_lines(scope, "z")
    assert len(z) == 17
    assert np.allclose(np.diff(z), 2 * float(scope["H_SUB"]) / 16,
                       atol=1e-12)
    assert len([p for p in prims if p.prop == "substrate"]) == 4


def test_sub_cells_z_invalid_values_fail_loud():
    """0/负=配置错误 fail-loud（#1b/#364 家法），不静默当 1。"""
    for bad in (0, -2):
        with pytest.raises(ValueError, match="_sub_cells_z"):
            _stl_render({**_STL_NOMINAL, "_sub_cells_z": bad})
