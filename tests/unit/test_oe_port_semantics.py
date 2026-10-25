"""oe_port_semantics：openEMS MSLPort 端口语义五判据校验器单测（Wave-E E2）。

覆盖面（aurora_l R1 #1，用户 P12 反馈 openEMS 侧同款病灶单源化）：
① 好参数全绿（显式 mesh 格点口径 + mesh_mm=None 降级口径）；
② 五判据逐条违反各一钉（内核立规注记 坑账原值：#347 探针近场 0.056mm=0.2 格、
   #340④ 零宽盒、#253 激励截面缺导带、#283 离格盒边/导带落地）；
③ 三接线点（render_hairpin 的 hairpin/hairpin_alt、render_varactor 的
   varactor_bpf、render_c4 的 lange/cline_coupler/branchline_2sect）冒烟
   ——发射器违例 fail-loud（monkeypatch 钉接线面真调校验器）+ 裸 params
   直调缺 render_script 注入键即 ValueError。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.oe_port_semantics import (
    assert_msl_port_geometry,
    validate_msl_port_geometry,
)
from rfauto.adapters.oe_templates import render_c4 as rc4
from rfauto.adapters.oe_templates import render_hairpin as rh
from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, render_script

BAND = (2.0, 3.0)
MESH_MM = 0.4

# ── 规范好几何（格点口径：全盒边=1mm 整数倍；NEAR=0.25mm）─────────────────
NEAR = 2.5e-4
MESH_MM_LATTICE = 1.0
GOOD_PORT = ((0.0, 0.0, 1e-3), (0.02, 1e-3, 0.0))
GOOD_FEED = ((0.0, 2.5e-4, 1e-3), (0.02, 7.5e-4, 1e-3))
GOOD_MEAS = 5e-3
GOOD_FEED_SHIFT = 1e-3


def _good_kwargs() -> dict:
    return dict(port_box=GOOD_PORT, feed_box=GOOD_FEED,
                meas_plane_shift=GOOD_MEAS, feed_shift=GOOD_FEED_SHIFT,
                near=NEAR, mesh_mm=MESH_MM_LATTICE)


def _failed_ids(res: dict) -> list[str]:
    return [c["id"] for c in res["checks"] if c["ok"] is False]


# ── ①好参数全绿 ────────────────────────────────────────────────────────────
def test_good_geometry_all_green():
    """格点口径好参数：五判据全 ok=True、violations 空。"""
    res = validate_msl_port_geometry(**_good_kwargs())
    assert res["ok"] is True
    assert res["violations"] == []
    assert [c["ok"] for c in res["checks"]] == [True] * 5
    assert res["checks"][0]["id"] == "c1_meas_feed_sep_4near"


def test_good_geometry_c4_degraded_when_mesh_unknown():
    """mesh_mm=None（终网格线集渲染期不可知）：c4 降级 ok=None 不否决整体。"""
    res = validate_msl_port_geometry(
        **dict(_good_kwargs(), mesh_mm=None))
    assert res["ok"] is True
    c4 = next(c for c in res["checks"]
              if c["id"] == "c4_box_edges_on_grid")
    assert c4["ok"] is None
    assert "降级" in c4["detail"]
    assert res["violations"] == []


# ── ②五判据逐条违反钉（坑账原值）───────────────────────────────────────────
def test_c1_violation_pin_347_probe_in_excitation_nearfield():
    """#347 原值：MeasPlaneShift−FeedShift=0.056mm（0.2 格）< 4·NEAR。

    病灶人话钉：β 偏 10×、Z_ref≈9Ω、|Γ|>1。"""
    res = validate_msl_port_geometry(
        **dict(_good_kwargs(),
               meas_plane_shift=GOOD_FEED_SHIFT + 5.6e-5))  # sep=0.056mm
    assert res["ok"] is False
    assert _failed_ids(res) == ["c1_meas_feed_sep_4near"]
    viol = res["violations"][0]
    assert "c1(#347)" in viol and "β 偏 10×" in viol and "|Γ|>1" in viol


def test_c2_violation_pin_zero_width_box_340():
    """#340④：端口盒写零宽（盒对角不横跨导带）——探针同位非物理。"""
    collapsed = ((0.0, 0.0, 1e-3), (0.02, 0.0, 0.0))
    res = validate_msl_port_geometry(
        port_box=collapsed,
        feed_box=((0.0, 0.0, 1e-3), (0.02, 0.0, 1e-3)),
        meas_plane_shift=GOOD_MEAS, feed_shift=GOOD_FEED_SHIFT,
        near=NEAR, mesh_mm=MESH_MM_LATTICE)
    assert res["ok"] is False
    assert _failed_ids(res) == ["c2_port_spans_conductor"]
    assert "c2(#340④)" in res["violations"][0]
    assert "S11/S21" in res["violations"][0]


def test_c3_violation_pin_conductor_outside_excitation_253():
    """#253：导带截面越出激励截面（横向悬空）——零模 DC 漂移病灶。"""
    res = validate_msl_port_geometry(
        port_box=GOOD_PORT,
        feed_box=((0.0, 1.2e-3, 1e-3), (0.02, 1.4e-3, 1e-3)),  # 越出 y 上缘
        meas_plane_shift=GOOD_MEAS, feed_shift=GOOD_FEED_SHIFT,
        near=NEAR, mesh_mm=MESH_MM_LATTICE)
    assert res["ok"] is False
    assert _failed_ids(res) == ["c3_excitation_contains_conductor"]
    assert "c3(#253)" in res["violations"][0]
    assert "零模 DC 漂移" in res["violations"][0]


def test_c4_violation_pin_off_lattice_face_283():
    """#283：显式 mesh 口径下盒边离格（0.3mm 面 vs 1mm 格）——单棱积分。"""
    res = validate_msl_port_geometry(
        port_box=((0.0, 0.0, 1e-3), (0.02, 3e-4, 0.0)),  # y 面 0.3mm 离格
        feed_box=((0.0, 5e-5, 1e-3), (0.02, 1e-4, 1e-3)),
        meas_plane_shift=GOOD_MEAS, feed_shift=GOOD_FEED_SHIFT,
        near=NEAR, mesh_mm=1.0)
    assert res["ok"] is False
    assert _failed_ids(res) == ["c4_box_edges_on_grid"]
    assert "c4(#283)" in res["violations"][0]
    assert "单棱积分" in res["violations"][0]


def test_c5_violation_pin_conductor_at_ground_and_zero_height():
    """#283/#340④ z 向两形态：导带落地（激励向倒置）与零高盒。"""
    # 形态 A：start z=0（MSLPort 端口金属面落地=导带落地，exc 倒置）
    res_a = validate_msl_port_geometry(
        port_box=((0.0, 0.0, 0.0), (0.02, 1e-3, 1e-3)),
        feed_box=GOOD_FEED,
        meas_plane_shift=GOOD_MEAS, feed_shift=GOOD_FEED_SHIFT,
        near=NEAR, mesh_mm=MESH_MM_LATTICE)
    assert res_a["ok"] is False
    assert _failed_ids(res_a) == ["c5_z_pillar_two_cells"]
    assert "c5(#283)" in res_a["violations"][0]
    # 形态 B：z 零高盒（探针塌缩单棱）
    res_b = validate_msl_port_geometry(
        port_box=((0.0, 0.0, 1e-3), (0.02, 1e-3, 1e-3)),
        feed_box=GOOD_FEED,
        meas_plane_shift=GOOD_MEAS, feed_shift=GOOD_FEED_SHIFT,
        near=NEAR, mesh_mm=MESH_MM_LATTICE)
    assert res_b["ok"] is False
    assert _failed_ids(res_b) == ["c5_z_pillar_two_cells"]


def test_invalid_inputs_fail_loud():
    """入参契约：near/mesh_mm 非正、盒形不合法一律 ValueError（不静默）。"""
    with pytest.raises(ValueError, match="near"):
        validate_msl_port_geometry(**dict(_good_kwargs(), near=0.0))
    with pytest.raises(ValueError, match="mesh_mm"):
        validate_msl_port_geometry(**dict(_good_kwargs(), mesh_mm=-1.0))
    with pytest.raises(ValueError, match="port_box"):
        validate_msl_port_geometry(
            **dict(_good_kwargs(), port_box=((0.0, 0.0), (0.02, 1e-3))))


def test_assert_wrapper_raises_with_context():
    """assert_msl_port_geometry：ok=False → ValueError 带 context+病灶人话。"""
    with pytest.raises(ValueError, match="mytmpl port1") as ei:
        assert_msl_port_geometry(
            context="mytmpl port1",
            **dict(_good_kwargs(),
                   meas_plane_shift=GOOD_FEED_SHIFT + 5.6e-5))
    assert "c1(#347)" in str(ei.value)


# ── ③三接线点冒烟 + fail-loud ─────────────────────────────────────────────
def _nominal_params(template: str) -> dict:
    return {k: float(v) for k, v in TEMPLATE_NOMINAL[template].items()}


@pytest.mark.parametrize("template", [
    "hairpin", "hairpin_alt", "varactor_bpf",
    "lange", "cline_coupler", "branchline_2sect",
])
@pytest.mark.parametrize("mesh_mm", [MESH_MM, 0])
def test_wired_renderers_smoke_green(template, mesh_mm):
    """三渲染器六模板（两网格档）经五判据校验后正常发射 MSLPort。"""
    text = render_script(template, _nominal_params(template), BAND,
                         mesh_resolution_mm=mesh_mm)
    assert "MSLPort(" in text


def test_hairpin_wiring_calls_validator_fail_loud(monkeypatch):
    """hairpin 族接线真调发射器：发射器违例抛错 → render 建模期 ValueError。"""
    calls: list[dict] = []

    def _stub(**kwargs):
        calls.append(kwargs)
        if kwargs["context"] == "hairpin 族 port2":  # 末口抛错，双口都过记录
            raise ValueError("人为违例钉")

    monkeypatch.setattr(rh, "assert_msl_port_geometry", _stub)
    with pytest.raises(ValueError, match="人为违例钉"):
        render_script("hairpin", _nominal_params("hairpin"), BAND,
                      mesh_resolution_mm=MESH_MM)
    assert calls, "hairpin 渲染未调用端口语义发射器"
    # 两端口各校验一次，几何键齐全
    assert {c["context"] for c in calls} == {"hairpin 族 port1",
                                             "hairpin 族 port2"}
    for c in calls:
        for key in ("port_box", "feed_box", "meas_plane_shift",
                    "feed_shift", "near", "mesh_mm"):
            assert key in c


def test_c4_wiring_calls_validator_fail_loud(monkeypatch):
    """c4 族接线真调发射器：lange 四端口逐口校验、违例建模期炸。"""
    calls: list[dict] = []

    def _stub(**kwargs):
        calls.append(kwargs)
        if kwargs["context"] == "lange port4":
            raise ValueError("人为违例钉")

    monkeypatch.setattr(rc4, "assert_msl_port_geometry", _stub)
    with pytest.raises(ValueError, match="人为违例钉"):
        render_script("lange", _nominal_params("lange"), BAND,
                      mesh_resolution_mm=MESH_MM)
    assert {c["context"] for c in calls} == {f"lange port{i}" for i in
                                             range(1, 5)}


def test_varactor_wiring_via_family_guard(monkeypatch):
    """varactor_bpf 走 hairpin 族守卫（同族 T 抽头双端口单源）。"""
    calls: list[dict] = []

    def _stub(**kwargs):
        calls.append(kwargs)
        if kwargs["context"] == "hairpin 族 port2":
            raise ValueError("人为违例钉")

    monkeypatch.setattr(rh, "assert_msl_port_geometry", _stub)
    with pytest.raises(ValueError, match="人为违例钉"):
        render_script("varactor_bpf", _nominal_params("varactor_bpf"), BAND,
                      mesh_resolution_mm=MESH_MM)
    assert {c["context"] for c in calls} == {"hairpin 族 port1",
                                             "hairpin 族 port2"}


def test_guard_requires_render_injected_base_mm():
    """裸 params 直调 _lines（无 _base_mm）：缺发射口径即 ValueError 不静默。"""
    from rfauto.adapters.oe_templates.render_c4 import _c4_port_guard
    from rfauto.adapters.oe_templates.render_hairpin import (
        _hairpin_layout,
        _hairpin_port_guard,
    )
    with pytest.raises(ValueError, match="_base_mm"):
        _hairpin_port_guard({}, _hairpin_layout({}), (0.0, 0.0))
    with pytest.raises(ValueError, match="_base_mm"):
        _c4_port_guard("lange", {}, {"boxes": [], "ports": []})


def test_guard_port_geometry_matches_emitted_mslport_literals(
        monkeypatch):
    """守卫输入与发射文本同源：port1 port_box/meas 面公式与 MSLPort 字面一致。

    防双源漂移（#116 族）：守卫用 (x_in+BOARD)−10·NEAR−4·H_SUB 公式重导，
    发射文本同一公式——抽 hairpin 名义渲染文本对拍守卫实收值。"""
    seen: list[dict] = []
    real = rh.assert_msl_port_geometry

    def _spy(**kwargs):
        seen.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(rh, "assert_msl_port_geometry", _spy)
    render_script("hairpin", _nominal_params("hairpin"), BAND,
                  mesh_resolution_mm=MESH_MM)
    assert len(seen) == 2
    p1 = seen[0]
    lay = rh._hairpin_layout(_nominal_params("hairpin"))
    board_m, h_m = 0.060, 0.508e-3
    near_m = MESH_MM * 1e-3 / 4.0
    assert p1["port_box"][0] == (-board_m, lay["y_taps"][0] + lay["wf"] / 2.0,
                                 h_m)
    assert p1["port_box"][1] == (lay["xs"][0],
                                 lay["y_taps"][0] - lay["wf"] / 2.0, 0.0)
    assert p1["meas_plane_shift"] == ((lay["xs"][0] + board_m)
                                      - 10.0 * near_m - 4.0 * h_m)


# ── ④Wave-F F1 三渲染器余量接线（render_tl/render_siw/render_antenna2）────
from rfauto.adapters.oe_templates import (
    render_antenna2 as ra2,
)
from rfauto.adapters.oe_templates import render_siw as rsiw
from rfauto.adapters.oe_templates import render_tl as rtl

#: TL 族 12 模板（11 接守卫 + via 豁免）MSLPort 发射口数（regex 口径
#: ``_port\\d = MSLPort\\(``；render_core footer 的 _port3e 提取辅助口不计）。
_TL_PORT_COUNTS = {
    "mline": 2, "wstep": 2, "bend": 2, "atten_pi": 2, "atten_t": 2,
    "gysel": 3, "tjunc": 3, "wilkinson": 3, "branchline": 4,
    "coupled_line": 3, "stepped_impedance": 2, "via": 2,
}


@pytest.mark.parametrize("template", sorted(_TL_PORT_COUNTS))
@pytest.mark.parametrize("mesh_mm", [MESH_MM, 0])
def test_tl_wired_renderers_smoke_green(template, mesh_mm):
    """TL 族 12 模板（两网格档）经五判据校验后正常发射 MSLPort（口数不漂）。"""
    import re

    text = render_script(template, _nominal_params(template), BAND,
                         mesh_resolution_mm=mesh_mm)
    n = len(re.findall(r"_port\d = MSLPort\(", text))
    assert n == _TL_PORT_COUNTS[template], template


def test_tl_wiring_calls_validator_fail_loud(monkeypatch):
    """TL 族接线真调发射器：mline 双口/branchline 四口逐口校验、违例建模期炸。"""
    calls: list[dict] = []

    def _stub(**kwargs):
        calls.append(kwargs)
        if kwargs["context"] in ("mline port2", "branchline port4"):
            raise ValueError("人为违例钉")

    monkeypatch.setattr(rtl, "assert_msl_port_geometry", _stub)
    with pytest.raises(ValueError, match="人为违例钉"):
        render_script("mline", _nominal_params("mline"), BAND,
                      mesh_resolution_mm=MESH_MM)
    assert {c["context"] for c in calls} == {"mline port1", "mline port2"}
    calls.clear()
    with pytest.raises(ValueError, match="人为违例钉"):
        render_script("branchline", _nominal_params("branchline"), BAND,
                      mesh_resolution_mm=MESH_MM)
    assert {c["context"] for c in calls} == {
        f"branchline port{i}" for i in range(1, 5)}
    for c in calls:
        for key in ("port_box", "feed_box", "meas_plane_shift",
                    "feed_shift", "near", "mesh_mm"):
            assert key in c


def test_tl_direct_raw_params_skips_guard(monkeypatch):
    """裸 params 直调（test_pcell_dsl BODY_FNS 消费面）：守卫降级跳过不炸。

    render_tl 与 hairpin/c4 的 fail-loud 契约不同源——直调面被冻结测试
    占用（无 band 上下文可导 base/NEAR，硬造即伪造判据）；强制路径=
    render_script 注入（_tl_port_guard 头注契约）。"""
    from rfauto.adapters.openems_templates import _mline_lines

    calls: list[dict] = []
    monkeypatch.setattr(rtl, "assert_msl_port_geometry",
                        lambda **kw: calls.append(kw))
    text = _mline_lines(dict(TEMPLATE_NOMINAL["mline"]))
    assert "MSLPort(" in text
    assert calls == [], "裸直调不应触发发射器（降级跳过契约）"


def test_tl_guard_geometry_matches_emitted_mslport_literals(monkeypatch):
    """守卫输入与发射字面同源（mline）：port_box/公式/NEAR 逐键对拍。"""
    seen: list[dict] = []
    real = rtl.assert_msl_port_geometry

    def _spy(**kwargs):
        seen.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(rtl, "assert_msl_port_geometry", _spy)
    render_script("mline", _nominal_params("mline"), BAND,
                  mesh_resolution_mm=MESH_MM)
    assert len(seen) == 2
    p1 = seen[0]
    w = float(TEMPLATE_NOMINAL["mline"]["w_mm"]) * 1e-3
    ln = float(TEMPLATE_NOMINAL["mline"]["line_len_mm"]) * 1e-3
    near_m = MESH_MM * 1e-3 / 4.0
    assert p1["near"] == near_m
    assert p1["feed_shift"] == 10.0 * near_m
    assert p1["mesh_mm"] is None
    assert p1["port_box"][0] == (w / 2.0, -0.060, 0.508e-3)
    assert p1["port_box"][1] == (-w / 2.0, -ln / 2.0, 0.0)
    assert p1["meas_plane_shift"] == (-ln / 2.0 + 0.060) / 3.0


def test_tl_near_ratio_knob_violation_red():
    """_near_ratio=1.0（auto 网格）：FeedShift=10·base 与 meas 间距塌缩即 c1 红。"""
    with pytest.raises(ValueError, match="c1\\(#347\\)"):
        render_script("mline", dict(_nominal_params("mline"), _near_ratio=1.0),
                      BAND, mesh_resolution_mm=0)


def test_msl_siw_taper_layout_guard_single_source(monkeypatch):
    """msl_siw_taper 旧手写 #347 判据收敛单源校验器：layout 双口真调+几何同源。"""
    from rfauto.adapters.openems_templates import msl_siw_taper_layout

    seen: list[dict] = []
    real = rsiw.assert_msl_port_geometry

    def _spy(**kwargs):
        seen.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(rsiw, "assert_msl_port_geometry", _spy)
    base_m, h_m = 0.4e-3, 0.508e-3
    lay = msl_siw_taper_layout(_nominal_params("msl_siw_taper"),
                               (9.75, 10.25), base_m, h_m)
    assert [c["context"] for c in seen] == ["msl_siw_taper port1",
                                            "msl_siw_taper port2"]
    p1 = seen[0]
    w50 = lay["w50"]
    assert p1["port_box"][0] == (w50 / 2.0, -lay["dom_y"], h_m)
    assert p1["port_box"][1] == (-w50 / 2.0, -lay["y_feed_in"], 0.0)
    # feed_box=手画 50Ω 馈线盒（发射文本 msl_top.AddBox 同区间）
    assert p1["feed_box"] == ((-w50 / 2.0, -lay["dom_y"], h_m),
                              (w50 / 2.0, -lay["y_feed_in"], h_m))
    assert p1["meas_plane_shift"] == lay["feed_len"] / 3.0
    assert p1["near"] == base_m / 4.0
    assert p1["feed_shift"] == 10.0 * base_m / 4.0


def test_msl_siw_taper_near_ratio_knob_violation_red():
    """_near_ratio=1.5：发射 NEAR=base/1.5 时 FeedShift 追平 meas——c1 红不静默。"""
    from rfauto.adapters.openems_templates import msl_siw_taper_layout

    with pytest.raises(ValueError, match="c1\\(#347\\)"):
        msl_siw_taper_layout(
            dict(_nominal_params("msl_siw_taper"), _near_ratio=1.5),
            (9.75, 10.25), 0.4e-3, 0.508e-3)


def test_slot_guard_smoke_green_and_fail_loud(monkeypatch):
    """slot 双 MSLPort 接线：名义绿（双口真调）+ 发射器违例建模期炸。"""
    calls: list[dict] = []

    def _stub(**kwargs):
        calls.append(kwargs)
        if kwargs["context"] == "slot port2":
            raise ValueError("人为违例钉")

    monkeypatch.setattr(ra2, "assert_msl_port_geometry", _stub)
    with pytest.raises(ValueError, match="人为违例钉"):
        render_script("slot", _nominal_params("slot"), BAND,
                      mesh_resolution_mm=MESH_MM)
    assert {c["context"] for c in calls} == {"slot port1", "slot port2"}
    for c in calls:
        for key in ("port_box", "feed_box", "meas_plane_shift",
                    "feed_shift", "near", "mesh_mm"):
            assert key in c


def test_slot_guard_geometry_matches_layout(monkeypatch):
    """守卫输入与布局单源同源：slot port1 盒字面对拍 _ant2_layout。"""
    seen: list[dict] = []
    real = ra2.assert_msl_port_geometry

    def _spy(**kwargs):
        seen.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(ra2, "assert_msl_port_geometry", _spy)
    render_script("slot", _nominal_params("slot"), BAND,
                  mesh_resolution_mm=MESH_MM)
    assert len(seen) == 2
    p1 = seen[0]
    lay = ra2._ant2_layout("slot", _nominal_params("slot"))
    pt = lay["ports"][0]
    fb = next(b for b in lay["boxes"] if b[0] == pt["metal_prop"])
    m = lambda v: float(v) * 1e-3   # noqa: E731
    assert p1["port_box"] == ((m(pt["start_mm"][0]), m(pt["start_mm"][1]),
                               m(pt["start_mm"][2])),
                              (m(pt["stop_mm"][0]), m(pt["stop_mm"][1]),
                               m(pt["stop_mm"][2])))
    assert p1["feed_box"] == ((m(fb[2]), m(fb[3]), m(fb[4])),
                              (m(fb[5]), m(fb[6]), m(fb[7])))
    assert p1["meas_plane_shift"] == float(pt["meas_shift_mm"]) * 1e-3


def test_slot_feed_margin_violation_red():
    """feed_margin_mm=20·NEAR：meas=margin/2=10·NEAR 恰追平 FeedShift——c1 红。

    （aurora_l 终门注记：测量面公式 m/3→m/2 后，旧构造 margin=3 不再
    违例（3.75·NEAR 出带）；违例带=margin∈(12·NEAR, 28·NEAR)，取
    meas=10·NEAR 精确追平点构造确定性红。）"""
    near_m = MESH_MM * 1e-3 / 4.0
    with pytest.raises(ValueError, match="c1\\(#347\\)"):
        render_script("slot",
                      dict(_nominal_params("slot"),
                           feed_margin_mm=20.0 * near_m * 1e3),
                      BAND, mesh_resolution_mm=MESH_MM)


def test_ant2_direct_raw_params_fail_loud_and_lumped_unguarded(monkeypatch):
    """裸直调 _ant2_body（slot）缺注入键即 ValueError；LumpedPort 五模板零触发。"""
    with pytest.raises(ValueError, match="_base_mm"):
        ra2._ant2_body("slot", dict(TEMPLATE_NOMINAL["slot"]))
    # 集总馈五模板不进校验面：发射器（若被误触发即炸）全程零调用
    monkeypatch.setattr(
        ra2, "assert_msl_port_geometry",
        lambda **kw: (_ for _ in ()).throw(AssertionError("不应触发")))
    for t in ("monopole", "pifa", "ifa", "loop", "helix"):
        render_script(t, _nominal_params(t), BAND, mesh_resolution_mm=MESH_MM)
