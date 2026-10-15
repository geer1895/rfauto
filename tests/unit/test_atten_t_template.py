"""WP2.3 T 型衰减器横向变体单测：渲染/解析（ABCD 闭式裁判）/综合/spec。

口径：±d 断口各串 LumpedElement（ny=y）+ 中点对地全带宽 shunt
LumpedElement（ny=z）。确定性裁判=理想电阻网络 ABCD（E4 attenuator_t
同源）：|S21|=-atten_db 平坦、S11=0。几何边精确入网（#198）。
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


def test_template_tables_have_atten_t():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "atten_t" in TEMPLATE_META and "atten_t" in TEMPLATE_NOMINAL
    assert TEMPLATE_META["atten_t"]["n_ports"] == 2
    assert TEMPLATE_NOMINAL["atten_t"]["atten_db"] == pytest.approx(10.0)
    assert _TEMPLATE_PORT_AXES["atten_t"] == ("y",)
    assert _TEMPLATE_RADIATOR["atten_t"] is False


def test_render_atten_t_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("atten_t", {"atten_db": 10.0, "w_mm": W,
                                     "shunt_off_mm": D,
                                     "r_series_arm_ohm": 25.975,
                                     "r_shunt_mid_ohm": 35.136},
                         (2.25, 2.75))
    compile(text, "gen", "exec")  # 语法门（#201 制度化）
    assert text.count('CSX.AddLumpedElement("') == 3  # 两串臂 + 中点 shunt
    assert text.count("ny=1") == 2 and "ny=2" in text
    # 三段带：两断口在 ±(D±G/2)
    assert "-BOARD, H_SUB), (W / 2, -D - G / 2, H_SUB)" in text


def test_near_points_exact_edges():
    from rfauto.adapters.openems_templates import _near_points

    nx, ny = _near_points("atten_t", {"w_mm": W, "shunt_off_mm": D})
    assert min(abs(v - 0.5567e-3) for v in nx) < 1e-12   # 带缘
    assert min(abs(v - 0.25e-3) for v in nx) < 1e-12     # shunt 盒 x 边
    for edge_mm in (-(D + 0.25), -(D - 0.25), -0.25, 0.25,
                    D - 0.25, D + 0.25):                 # 两断口 + 中点 shunt 盒 y 边
        assert min(abs(v - edge_mm * 1e-3) for v in ny) < 1e-12


def test_nominal_shunt_off_electrically_colocated():
    """电共位名义钉（W7-A 残座批模型级修复，同 π 型）：TEMPLATE_NOMINAL 与
    synthesize_atten_t_model 缺省 shunt_off_mm=0.75mm，_atten_d_guard 界内；
    证据链=D=6mm 座 |S11|max=0.177 随"理想分布 T"级联，D=0.75 复跑
    |S11|max=0.057（-24.8dB）/|S21|med=-10.17dB。"""
    from rfauto.adapters.oe_templates.render_tl import _atten_d_guard
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
    from rfauto.core.synthesis import synthesize_atten_t_model

    assert TEMPLATE_NOMINAL["atten_t"]["shunt_off_mm"] == pytest.approx(0.75)
    res = synthesize_atten_t_model(attenuation_db=10.0, z0_ohm=50.0)
    assert res.params["shunt_off_mm"] == pytest.approx(0.75)
    assert _atten_d_guard(0.75) == pytest.approx(0.75)
    with pytest.raises(ValueError, match="电共位守卫"):
        _atten_d_guard(6.0)


def _atten_t_csx(tmp_path, mesh_resolution_mm: float = 0.0) -> dict:
    """渲染→exec 几何段→CSXCAD 对象字典（#212 离线审计基元，秒级零仿真）。"""
    from rfauto.adapters.openems_templates import render_script

    text = render_script("atten_t", {"atten_db": 10.0, "w_mm": W,
                                     "shunt_off_mm": D,
                                     "r_series_arm_ohm": 25.975,
                                     "r_shunt_mid_ohm": 35.136},
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


def test_render_atten_t_geometry_colocation_offline(tmp_path):
    """离线几何审计（#212 制度化 + W7-A 模型级修复回归）：exec 后用 CSXCAD
    实测三元件电共位画法——串臂盒内缘与中点 shunt 盒/中间带缘共享边
    （端点重合连通）、串臂零厚贴带平面、中点 shunt 短柱 z 跨满基板接地。"""
    g = _atten_t_csx(tmp_path)
    csx = g["CSX"]
    h_sub = float(g["H_SUB"]) * 1e3
    w_mm, d_mm = W, D

    metal = [b for b in _boxes_mm(csx, "Metal")
             if abs(b[4] - h_sub) < 1e-9 and abs(b[5] - h_sub) < 1e-9]
    # 三段带缘精确：y 边集 = {−60, −(D±0.25), −D, D−0.25, D, D+0.25, 60}
    # （中间带 [−(D−0.25), D−0.25] 跨中点 shunt 正上方；端口馈线止于 ∓D）
    y_edges = sorted({round(v, 6) for b in metal for v in (b[2], b[3])})
    assert y_edges == sorted({-60.0, -(d_mm + 0.25), -d_mm, -(d_mm - 0.25),
                              d_mm - 0.25, d_mm, d_mm + 0.25, 60.0}), y_edges
    for b in metal:
        assert b[0] == pytest.approx(-w_mm / 2, abs=1e-9)
        assert b[1] == pytest.approx(w_mm / 2, abs=1e-9)

    # 两串臂盒：y=±[D−0.25, D+0.25]、零厚贴带平面（ny=1）；内缘=中间带缘
    series = [b for b in _boxes_mm(csx, "LumpedElement")
              if abs(b[4] - h_sub) < 1e-9 and abs(b[5] - h_sub) < 1e-9]
    assert len(series) == 2, f"两条串臂桥接盒，得 {len(series)}"
    for b in series:
        assert b[2] == pytest.approx(-(d_mm + 0.25), abs=1e-9) or \
            b[2] == pytest.approx(d_mm - 0.25, abs=1e-9)
        assert b[3] == pytest.approx(-(d_mm - 0.25), abs=1e-9) or \
            b[3] == pytest.approx(d_mm + 0.25, abs=1e-9)

    # 中点 shunt 短柱：y=[−0.25, 0.25]、z 跨满基板接地
    mid = [b for b in _boxes_mm(csx, "LumpedElement")
           if abs(b[4]) < 1e-9 and abs(b[5] - h_sub) < 1e-9]
    assert len(mid) == 1, f"一条中点 shunt 短柱，得 {len(mid)}"
    assert mid[0][2] == pytest.approx(-0.25, abs=1e-9)
    assert mid[0][3] == pytest.approx(0.25, abs=1e-9)
    assert mid[0][0] == pytest.approx(-w_mm / 2, abs=1e-9)
    assert mid[0][1] == pytest.approx(w_mm / 2, abs=1e-9)

    # 电阻值单源：LumpedElement 属性 R 与 E4 闭式逐位（#252）
    r_props = {}
    for pi in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(pi)
        if str(prop.GetTypeString()) == "LumpedElement":
            r_props[str(prop.GetName())] = float(prop.GetResistance())
    assert r_props == {"r_series1": 25.975, "r_series2": 25.975,
                       "r_shunt_mid": 35.136}


def test_fake_atten_t_flat_attenuation():
    """fake：理想电阻网络 |S21|=-10dB 平坦、按设计匹配 S11≈0。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="atten_t", n_ports=2,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"atten_db": "10dB"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    s21_db = 20 * np.log10(np.abs(net.s[:, 0, 1]) + 1e-12)
    assert s21_db.mean() == pytest.approx(-10.0, abs=0.05)
    assert float(np.max(20 * np.log10(np.abs(net.s[:, 0, 0]) + 1e-12))) < -100


def test_synthesize_atten_t_model_roundtrip():
    from rfauto.core.synthesis import synthesize_atten_t_model

    result = synthesize_atten_t_model(attenuation_db=10.0, z0_ohm=50.0)
    assert result.model == "atten_t"
    assert result.params["r_series_arm_ohm"] == pytest.approx(25.975,
                                                              abs=0.1)
    assert result.params["r_shunt_mid_ohm"] == pytest.approx(35.136,
                                                             abs=0.1)
    objs = result.recipe_draft["objectives"]
    assert objs[0]["metric"] == "s21_db" and objs[0]["op"] == "mean_within"
    assert objs[0]["value"] == pytest.approx([-10.5, -9.5])


def test_atten_t_spec_wiring():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("atten_t")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    draft = TEMPLATE_SPECS.draft_recipe("atten_t", attenuation_db=10.0)
    assert draft["model"] == "atten_t"


def test_meta_yaml_sync():
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META

    p = REPO / "docs" / "templates" / "atten_t" / "meta.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["template"] == "atten_t"
    assert data["n_ports"] == TEMPLATE_META["atten_t"]["n_ports"]
