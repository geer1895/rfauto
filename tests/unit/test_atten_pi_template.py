"""WP2.3 π 型衰减器首族单测：渲染（LumpedElement 口径）/解析/综合/spec。

口径：串臂 LumpedElement 桥接中点断口（ny=y）+ 两端对地 shunt
LumpedElement（ny=z，短柱接 z-min PEC 地）。确定性裁判=理想电阻
网络 ABCD 闭式（E4 attenuator_pi 同源），|S21|=-atten_db 平坦、
S11=0（按设计匹配）。几何边精确入网（#198）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

W, D = 1.1134, 0.75


def test_template_tables_have_atten_pi():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "atten_pi" in TEMPLATE_META and "atten_pi" in TEMPLATE_NOMINAL
    assert TEMPLATE_META["atten_pi"]["n_ports"] == 2
    assert TEMPLATE_NOMINAL["atten_pi"]["w_mm"] == pytest.approx(1.1134,
                                                                 abs=0.02)
    assert _TEMPLATE_PORT_AXES["atten_pi"] == ("y",)
    assert _TEMPLATE_RADIATOR["atten_pi"] is False


def test_render_atten_pi_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("atten_pi", {"atten_db": 10.0, "w_mm": W,
                                      "shunt_off_mm": D,
                                      "r_series_mid_ohm": 71.151,
                                      "r_shunt_end_ohm": 96.248},
                         (2.25, 2.75))
    compile(text, "gen", "exec")  # 语法门（#201 制度化）
    assert text.count('CSX.AddLumpedElement("') == 3  # 串臂 + 两 shunt
    assert "ny=1" in text and "ny=2" in text
    # 串臂断口：带在 y=±G 处断开
    assert "-BOARD, H_SUB), (W / 2, -G, H_SUB)" in text


def test_near_points_exact_edges():
    from rfauto.adapters.openems_templates import _near_points

    nx, ny = _near_points("atten_pi", {"w_mm": W, "shunt_off_mm": D})
    assert min(abs(v - 0.5567e-3) for v in nx) < 1e-12   # 带缘
    assert min(abs(v - 0.25e-3) for v in nx) < 1e-12     # shunt 盒 x 边
    assert min(abs(v - (D + 0.25) * 1e-3) for v in ny) < 1e-12  # shunt 盒 y 外缘
    assert min(abs(v - (D - 0.25) * 1e-3) for v in ny) < 1e-12  # shunt 盒 y 内缘
    assert min(abs(v - 0.5e-3) for v in ny) < 1e-12      # 串臂断口


def test_nominal_shunt_off_electrically_colocated():
    """电共位名义钉（W7-A 残座批模型级修复）：TEMPLATE_NOMINAL 与
    synthesize_atten_pi_model 缺省的 shunt_off_mm=0.75mm，与渲染端
    _atten_d_guard 界（θ=β·D≤0.09rad ⇒ ≤0.83mm @3GHz/εr=3.66）互洽。

    证据链：D=6mm 名义座 EM |S11|max=0.272 与"理想分布 π"级联 0.226
    同源（D=3/12 EM 0.153/0.526 对级联 0.105/0.499 同线）；mount 级
    单变量（εr/窄盒/caps）Δ<0.002 排除集总盒缺陷；D=0.75 复跑
    |S11|max=0.080（-21.9dB）/|S21|med=-10.18dB。
    """
    from rfauto.adapters.oe_templates.render_tl import _atten_d_guard
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
    from rfauto.core.synthesis import synthesize_atten_pi_model

    assert TEMPLATE_NOMINAL["atten_pi"]["shunt_off_mm"] == pytest.approx(0.75)
    res = synthesize_atten_pi_model(attenuation_db=10.0, z0_ohm=50.0)
    assert res.params["shunt_off_mm"] == pytest.approx(0.75)
    # 守卫界自洽：0.75 通过、越界值抛错（含错误语义说明）
    assert _atten_d_guard(0.75) == pytest.approx(0.75)
    with pytest.raises(ValueError, match="电共位守卫"):
        _atten_d_guard(6.0)


def _atten_pi_csx(tmp_path, mesh_resolution_mm: float = 0.0) -> dict:
    """渲染→exec 几何段→CSXCAD 对象字典（#212 离线审计基元，秒级零仿真）。"""
    from rfauto.adapters.openems_templates import render_script

    text = render_script("atten_pi", {"atten_db": 10.0, "w_mm": W,
                                      "shunt_off_mm": D,
                                      "r_series_mid_ohm": 71.151,
                                      "r_shunt_end_ohm": 96.248},
                         (2.25, 2.75),
                         mesh_resolution_mm=mesh_resolution_mm)
    compile(text, "gen", "exec")  # 语法门（#201 制度化）
    head = text[:text.index("FDTD.Run(")]
    g = {"__name__": "__main__", "__file__": str(tmp_path / "simulation.py")}
    exec(compile(head, "sim", "exec"), g)  # 受限 exec：模板几何段（仓内惯例）
    return g


def _boxes_mm(csx, type_string: str) -> list[tuple]:
    """指定属性类型的全部盒原语 (x0,x1,y0,y1,z0,z1) mm 列表（逐轴排序）。"""
    import numpy as np

    out = []
    for pi in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(pi)
        if str(prop.GetTypeString()) != type_string:
            continue
        for prim in prop.GetAllPrimitives():
            s = np.array(prim.GetStart(), dtype=float) * 1e3
            e = np.array(prim.GetStop(), dtype=float) * 1e3
            lo, hi = np.minimum(s, e), np.maximum(s, e)
            out.append((float(lo[0]), float(hi[0]), float(lo[1]),
                        float(hi[1]), float(lo[2]), float(hi[2])))
    return out


def test_render_atten_pi_geometry_colocation_offline(tmp_path):
    """离线几何审计（#212 制度化 + W7-A 模型级修复回归）：exec 后用 CSXCAD
    实测三元件电共位画法——shunt 盒内缘与串臂断口缘共享边（y=±G 端点重合，
    连通图无孤立段）、短柱 z 跨满基板（0→H_SUB）接地连续、串臂桥接断口。
    字符串存在性测试抓不住画法错误（#212 家族；本审计=W7-A"寄生"定谳的
    模型级修复回归钉，D=6mm 旧画法 shunt 内缘在 ∓5.75mm 非共位）。"""
    g = _atten_pi_csx(tmp_path)
    csx = g["CSX"]
    h_sub = float(g["H_SUB"]) * 1e3
    w_mm, d_mm = W, D

    metal = [b for b in _boxes_mm(csx, "Metal")
             if abs(b[4] - h_sub) < 1e-9 and abs(b[5] - h_sub) < 1e-9]
    # 带两段（MSLPort 自画馈线盒为同属性子集盒）：x 跨满线宽、断口缘=±G、
    # 断口 [−G, G] 内无金属（留给串臂桥接）
    assert len(metal) == 4, f"两用户带+两端口馈线盒，得 {len(metal)}"
    for b in metal:
        assert b[0] == pytest.approx(-w_mm / 2, abs=1e-9)
        assert b[1] == pytest.approx(w_mm / 2, abs=1e-9)
        assert b[2] == pytest.approx(-60.0, abs=1e-9) or \
            b[2] == pytest.approx(0.5, abs=1e-9) or \
            b[2] == pytest.approx(d_mm, abs=1e-9)
        assert b[3] <= -0.5 + 1e-9 or b[2] >= 0.5 - 1e-9
    assert any(b[3] == pytest.approx(-0.5, abs=1e-9) for b in metal)
    assert any(b[2] == pytest.approx(0.5, abs=1e-9) for b in metal)

    # shunt 短柱：z 跨满基板接地（0→H_SUB）、内缘与断口缘共享边（电共位）
    shunt = [b for b in _boxes_mm(csx, "LumpedElement")
             if abs(b[4]) < 1e-9 and abs(b[5] - h_sub) < 1e-9]
    assert len(shunt) == 2, f"两 shunt 短柱，得 {len(shunt)}"
    inners = sorted(round(b[2], 6) if b[2] > 0 else -round(b[3], 6)
                    for b in shunt)
    assert inners == [0.5, 0.5], f"shunt 内缘须=断口缘 ±0.5：{shunt}"
    for b in shunt:
        assert b[0] == pytest.approx(-w_mm / 2, abs=1e-9)
        assert b[1] == pytest.approx(w_mm / 2, abs=1e-9)
    y_edges = sorted(round(v, 6) for b in shunt for v in (b[2], b[3]))
    assert y_edges == [-(d_mm + 0.25), -0.5, 0.5, d_mm + 0.25], y_edges

    # 串臂桥接盒：y 跨断口 [−G, G]、零厚贴带平面（ny=1）
    series = [b for b in _boxes_mm(csx, "LumpedElement")
              if b[2] == pytest.approx(-0.5, abs=1e-9)
              and b[3] == pytest.approx(0.5, abs=1e-9)]
    assert len(series) == 1, f"一条串臂桥接盒，得 {len(series)}"
    assert series[0][4] == pytest.approx(h_sub, abs=1e-9)
    assert series[0][5] == pytest.approx(h_sub, abs=1e-9)

    # 电阻值单源：LumpedElement 属性 R 与 E4 闭式逐位（#252）
    r_props = {}
    for pi in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(pi)
        if str(prop.GetTypeString()) == "LumpedElement":
            r_props[str(prop.GetName())] = float(prop.GetResistance())
    assert r_props == {"r_series": 71.151, "r_shunt1": 96.248,
                       "r_shunt2": 96.248}


def test_render_atten_pi_default_mesh_geometry_offline(tmp_path):
    """auto 档（mesh=0，锚座口径）同审计：电共位画法不随网格档变化。"""
    g = _atten_pi_csx(tmp_path, mesh_resolution_mm=0.0)
    h_sub = float(g["H_SUB"]) * 1e3
    metal = [b for b in _boxes_mm(g["CSX"], "Metal")
             if abs(b[4] - h_sub) < 1e-9 and abs(b[5] - h_sub) < 1e-9]
    assert any(b[3] == pytest.approx(-0.5, abs=1e-9) for b in metal)
    assert any(b[2] == pytest.approx(0.5, abs=1e-9) for b in metal)
    shunt = [b for b in _boxes_mm(g["CSX"], "LumpedElement")
             if abs(b[4]) < 1e-9 and abs(b[5] - h_sub) < 1e-9]
    assert len(shunt) == 2
    assert sorted(round(b[2], 6) for b in shunt) == [-1.0, 0.5]


def test_fake_atten_pi_flat_attenuation():
    """fake：理想电阻网络 |S21|=-10dB 平坦、按设计匹配 S11≈0。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="atten_pi", n_ports=2,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"atten_db": "10dB"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    s21_db = 20 * np.log10(np.abs(net.s[:, 0, 1]) + 1e-12)
    assert s21_db.mean() == pytest.approx(-10.0, abs=0.05)
    assert float(np.max(20 * np.log10(np.abs(net.s[:, 0, 0]) + 1e-12))) < -100


def test_synthesize_atten_pi_model_roundtrip():
    from rfauto.core.synthesis import synthesize_atten_pi_model

    result = synthesize_atten_pi_model(attenuation_db=10.0, z0_ohm=50.0)
    assert result.model == "atten_pi"
    assert result.params["r_series_mid_ohm"] == pytest.approx(71.151,
                                                              abs=0.1)
    assert result.params["r_shunt_end_ohm"] == pytest.approx(96.248,
                                                             abs=0.1)
    objs = result.recipe_draft["objectives"]
    assert objs[0]["metric"] == "s21_db" and objs[0]["op"] == "mean_within"
    assert objs[0]["value"] == pytest.approx([-10.5, -9.5])
    assert objs[1]["metric"] == "s11_db"


def test_atten_pi_spec_wiring():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("atten_pi")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    draft = TEMPLATE_SPECS.draft_recipe("atten_pi", attenuation_db=10.0)
    assert draft["model"] == "atten_pi"


def test_meta_yaml_sync():
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META

    p = REPO / "docs" / "templates" / "atten_pi" / "meta.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["template"] == "atten_pi"
    assert data["n_ports"] == TEMPLATE_META["atten_pi"]["n_ports"]
