"""EDB 平面族发射器扩展单测：coupled_line / ratrace / lange 三族（ext 批）。

照 test_edb_templates.py 先例（#212 离线几何审计制度化）：全程零 pyedb
依赖（pyedb 仅在 importorskip 的 CfgData 离线解析测试中出现）。
  - 几何审计：连通图分量结构/端点重合/端口落位/轴对齐（flat cap 矩形
    反推）/board 覆盖/连接面正面积重叠（防零面积边贴假连通）；
  - 综合值：测试内独立重导公式链 1e-9 对照 + 与注册模板综合单源对照
    （cline_coupler_design / synthesize_ratrace_model / lange_design，
    舍入档容差同先例：宽度 5e-4mm、长度 5e-3mm）；
  - config_json 经 pyedb CfgData 离线解析零 unknown-section 警告。

lange 族：EDB 发射声明不支持（NotImplementedError，裁定论证见
edb_templates/lange.py docstring）——本文件钉"不支持"契约与综合单源链。
族豁免事实面：validate_spec 正本未动，coupled_line 恰两豁免行（template
白名单 + 线 A/B DC 隔离双分量）、ratrace 恰一豁免行（template 白名单）。
"""

from __future__ import annotations

import copy
import math
import sys
import warnings
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from rfauto.adapters.edb_templates import (
    KNOWN_TEMPLATES,
    LANGE_EDB_SUPPORTED,
    emit_coupled_line_spec,
    emit_lange_spec,
    emit_ratrace_spec,
    lange_synth,
    trace_attach_graph,
    trace_connected_components,
    validate_spec,
)

C0_MM_GHZ = 299.792458  # c（mm·GHz，与 core.synthesis 同常数）
F0 = 2.4
STACKUP_KW = dict(epsilon_r=3.66, thickness_mm=0.508, loss_tangent=0.0037)
TOL = 1e-9


# ─── 几何 helper（flat cap 矩形反推，兼任轴对齐断言）─────────────────────────


def _rect(tr: dict) -> tuple[float, float, float, float]:
    """trace 轴对齐矩形足迹 (x0, y0, x1, y1)——cap=flat 只向横向外扩 w/2。"""
    (xa, ya), (xb, yb) = [(float(p[0]), float(p[1])) for p in tr["path_mm"]]
    w2 = float(tr["width_mm"]) / 2.0
    if abs(ya - yb) < 1e-15:
        return (min(xa, xb), ya - w2, max(xa, xb), ya + w2)
    if abs(xa - xb) < 1e-15:
        return (xa - w2, min(ya, yb), xa + w2, max(ya, yb))
    raise AssertionError(f"非轴对齐走线: {tr['name']} {tr['path_mm']}")


def _overlap_area(a: tuple, b: tuple) -> float:
    """两矩形正面积重叠（0=不相交/仅边贴）。"""
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, dx) * max(0.0, dy)


@pytest.fixture(scope="module")
def cl() -> tuple[dict, dict]:
    return emit_coupled_line_spec({"f0_ghz": F0})


@pytest.fixture(scope="module")
def rr() -> tuple[dict, dict]:
    return emit_ratrace_spec({"f0_ghz": F0})


# ═══ coupled_line（edb_coupled_line）═════════════════════════════════════════


def test_cl_spec_contract_and_validate(cl):
    spec, config = cl
    for key in ("stackup", "traces", "vias", "ports", "sim_setup"):
        assert key in spec, f"契约字段缺失: {key}"
    assert spec["template"] == "edb_coupled_line"
    assert spec["schema_version"] == 1
    assert spec["units"] == {"length": "mm", "frequency": "GHz"}
    # 族豁免恰两行：template 白名单（followUp 升格）+ 线 A/B DC 隔离双分量
    errors = validate_spec(spec)
    assert len(errors) == 2
    assert errors[0].startswith("template 非法:")
    assert errors[1].startswith("走线连通图非单连通")
    assert set(config) == {"stackup", "modeler", "ports", "setups", "boundaries"}


def test_cl_numerics_match_closed_form(cl):
    spec, _ = cl
    p = spec["params"]
    c = 10.0 ** (-p["coupling_db"] / 20.0)
    assert p["c"] == pytest.approx(c, rel=TOL)
    zee = 50.0 * math.sqrt((1.0 + c) / (1.0 - c))  # Pozar §7.6 闭式
    zoo = 50.0 * math.sqrt((1.0 - c) / (1.0 + c))
    assert p["zee_ohm"] == pytest.approx(zee, rel=TOL)
    assert p["zoo_ohm"] == pytest.approx(zoo, rel=TOL)
    assert p["zee_ohm"] * p["zoo_ohm"] == pytest.approx(2500.0, rel=1e-9)  # Z0e·Z0o=Z0²
    # KJ 正向回代：(w,s) → (Z0e, Z0o) 恢复（brentq xtol 量级，<1e-3Ω）
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    ze, zo, ee, eo = coupled_microstrip_even_odd_ohm(
        p["w_mm"], p["s_mm"], F0, 3.66, 0.508)
    assert abs(ze - p["zee_ohm"]) < 1e-3
    assert abs(zo - p["zoo_ohm"]) < 1e-3
    assert p["eps_eff_even"] == pytest.approx(ee, rel=TOL)
    assert p["eps_eff_odd"] == pytest.approx(eo, rel=TOL)
    assert p["eps_eff_avg"] == pytest.approx(0.5 * (ee + eo), rel=TOL)
    # 耦合段长 = λ/4 @ 平均 εeff（用 spec 自身 εeff 第三方复核长度记账）
    assert p["coupled_len_mm"] == pytest.approx(
        C0_MM_GHZ / (4.0 * F0 * math.sqrt(p["eps_eff_avg"])), rel=TOL)


def test_cl_single_source_registered_chain(cl):
    """与注册 cline_coupler 模板设计函数同综合单源（同函数同参，1e-9）。"""
    from rfauto.adapters.oe_templates.render_c4 import cline_coupler_design

    spec, _ = cl
    p = spec["params"]
    d = cline_coupler_design(p["coupling_db"], F0, 50.0, er=3.66, h_mm=0.508)
    pairs = (("c", "c"), ("zee_ohm", "zee_ohm"), ("zoo_ohm", "zoo_ohm"),
             ("w_mm", "w_mm"), ("s_mm", "s_mm"), ("eps_eff_even", "ere_e"),
             ("eps_eff_odd", "ere_o"), ("eps_eff_avg", "ere_avg"),
             ("coupled_len_mm", "lc_mm"))
    for key_p, key_d in pairs:
        assert p[key_p] == pytest.approx(float(d[key_d]), abs=TOL), key_p


def test_cl_w_feed_single_source(cl):
    """50Ω 馈线宽 = nominal_width_mm 单源全精度档逐位（XC-W 口径，先例同款）。"""
    from rfauto.core.synthesis import nominal_width_mm

    spec, _ = cl
    p = spec["params"]
    w_src = nominal_width_mm(50.0, F0, "rogers4350b_h0.508", digits=None)
    assert p["w_feed_mm"] == w_src
    for tr in spec["traces"]:
        if tr["role"] == "feed":
            assert tr["width_mm"] == w_src
        else:
            assert tr["width_mm"] == pytest.approx(p["w_mm"], abs=TOL)
    for pt in spec["ports"]:
        assert pt["impedance"] == 50.0


def test_cl_nominal_registry_2p5():
    """@2.5GHz/10dB 与注册 CLINE_COUPLER_NOMINAL 同名义点（舍入档 5e-4）。

    w_feed 不在此对照：注册名义值出自设计链 tand=0 裸 Stackup 通道，发射器
    50Ω 宽走族内单源（solve_microstrip，含 tanδ 标量，差 ~1.7e-3mm 二阶，
    发射器 docstring 已声明）——单源逐位由 test_cl_w_feed_single_source 钉。
    """
    from rfauto.adapters.oe_templates.render_c4 import CLINE_COUPLER_NOMINAL

    spec, _ = emit_coupled_line_spec({"f0_ghz": 2.5})
    p = spec["params"]
    assert p["w_mm"] == pytest.approx(CLINE_COUPLER_NOMINAL["w_mm"], abs=5e-4)
    assert p["s_mm"] == pytest.approx(CLINE_COUPLER_NOMINAL["gap_mm"], abs=5e-4)
    assert p["coupled_len_mm"] == pytest.approx(
        CLINE_COUPLER_NOMINAL["coupled_len_mm"], abs=5e-4)


def test_cl_geometry_audit(cl):
    spec, _ = cl
    p = spec["params"]
    d = p["w_mm"] + p["s_mm"]
    xa, xb = -d / 2.0, d / 2.0
    y0, y1 = -p["coupled_len_mm"] / 2.0, p["coupled_len_mm"] / 2.0
    feed = p["feed_len_mm"]
    by_name = {tr["name"]: tr for tr in spec["traces"]}
    assert set(by_name) == {"line_a", "line_b",
                            "feed_p1", "feed_p2", "feed_p3", "feed_p4"}
    assert by_name["line_a"]["path_mm"] == [[xa, y0], [xa, y1]]
    assert by_name["line_b"]["path_mm"] == [[xb, y0], [xb, y1]]
    assert by_name["line_a"]["width_mm"] == pytest.approx(p["w_mm"], abs=TOL)
    assert by_name["line_b"]["width_mm"] == pytest.approx(p["w_mm"], abs=TOL)
    assert by_name["feed_p1"]["path_mm"] == [[xa - feed, y0], [xa, y0]]
    assert by_name["feed_p2"]["path_mm"] == [[xa - feed, y1], [xa, y1]]
    assert by_name["feed_p3"]["path_mm"] == [[xb, y0], [xb + feed, y0]]
    assert by_name["feed_p4"]["path_mm"] == [[xb, y1], [xb + feed, y1]]
    # 连通图：恰两分量（线 A/B DC 隔离=器件物理），组内全连通
    adj = trace_attach_graph(spec["traces"])
    comps = trace_connected_components(adj)
    assert len(comps) == 2
    groups = sorted([sorted(spec["traces"][i]["name"] for i in c) for c in comps])
    assert groups == [["feed_p1", "feed_p2", "line_a"],
                      ["feed_p3", "feed_p4", "line_b"]]
    # 端口语义（后向波耦合器）与落位（馈线外端点）
    assert [(pt["name"], pt["port_nr"], pt["trace"]) for pt in spec["ports"]] == [
        ("P1", 1, "feed_p1"), ("P2", 2, "feed_p2"),
        ("P3", 3, "feed_p3"), ("P4", 4, "feed_p4"),
    ]
    ends = {pt["name"]: pt["point_mm"] for pt in spec["ports"]}
    assert ends["P1"] == [xa - feed, y0]
    assert ends["P2"] == [xa - feed, y1]
    assert ends["P3"] == [xb + feed, y0]
    assert ends["P4"] == [xb + feed, y1]


def test_cl_gap_and_area_overlaps(cl):
    """耦合缝=s 精确；连接面正面积重叠；馈线与对侧导体零重叠（无寄生缝-s 跑线）。"""
    spec, _ = cl
    p = spec["params"]
    by_name = {tr["name"]: tr for tr in spec["traces"]}
    rect_a = _rect(by_name["line_a"])
    rect_b = _rect(by_name["line_b"])
    assert (rect_b[0] - rect_a[2]) == pytest.approx(p["s_mm"], abs=TOL)
    for fn, ln in (("feed_p1", "line_a"), ("feed_p2", "line_a"),
                   ("feed_p3", "line_b"), ("feed_p4", "line_b")):
        assert _overlap_area(_rect(by_name[fn]), _rect(by_name[ln])) > 0.0, fn
    assert _overlap_area(_rect(by_name["feed_p1"]), rect_b) == 0.0
    assert _overlap_area(_rect(by_name["feed_p2"]), rect_b) == 0.0
    assert _overlap_area(_rect(by_name["feed_p3"]), rect_a) == 0.0
    assert _overlap_area(_rect(by_name["feed_p4"]), rect_a) == 0.0
    for fa, fb in (("feed_p1", "feed_p2"), ("feed_p3", "feed_p4"),
                   ("feed_p1", "feed_p3"), ("feed_p2", "feed_p4"),
                   ("feed_p1", "feed_p4"), ("feed_p2", "feed_p3")):
        assert _overlap_area(_rect(by_name[fa]), _rect(by_name[fb])) == 0.0


def test_cl_axis_aligned_and_board(cl):
    spec, _ = cl
    x0, y0 = spec["board"]["lower_left_mm"]
    x1, y1 = spec["board"]["upper_right_mm"]
    for tr in spec["traces"]:
        _rect(tr)  # 非轴对齐在此抛 AssertionError
        w2 = tr["width_mm"] / 2.0
        for x, y in tr["path_mm"]:
            assert x0 - 1e-12 <= x - w2 and x + w2 <= x1 + 1e-12
            assert y0 - 1e-12 <= y - w2 and y + w2 <= y1 + 1e-12


def test_cl_config_json_shape(cl):
    spec, config = cl
    layers = config["stackup"]["layers"]
    # config 自顶向下（spec 自底向上翻转；pyedb AddLayerBottom 首项落物理
    # 顶层，2026-10-08 审查批 P0 修复）
    assert [la["name"] for la in layers] == ["TOP", "SUB", "GND"]
    for tr_cfg, tr_spec in zip(config["modeler"]["traces"], spec["traces"],
                               strict=True):
        assert tr_cfg["name"] == tr_spec["name"] and tr_cfg["layer"] == "TOP"
        assert tr_cfg["path"] == [[x * 1e-3, y * 1e-3] for x, y in tr_spec["path_mm"]]
        assert abs(float(tr_cfg["width"][:-2]) - tr_spec["width_mm"]) < 1e-8
        assert tr_cfg["start_cap_style"] == "flat"
        assert tr_cfg["corner_style"] == "sharp"
    assert [pl["name"] for pl in config["modeler"]["planes"]] == ["GND_plane"]
    for pt_cfg, pt_spec in zip(config["ports"], spec["ports"], strict=True):
        assert pt_cfg["type"] == "wave_port"
        assert pt_cfg["primitive_name"] == pt_spec["trace"]
        assert pt_cfg["point_on_edge"] == [pt_spec["point_mm"][0] * 1e-3,
                                           pt_spec["point_mm"][1] * 1e-3]
        assert pt_cfg["horizontal_extent_factor"] == 5
        assert pt_cfg["vertical_extent_factor"] == 3
    (setup,) = config["setups"]
    assert setup["type"] == "hfss" and setup["adapt_type"] == "single"
    assert setup["single_frequency_adaptive_solution"]["adaptive_frequency"] == "2.4GHz"
    (sweep,) = setup["freq_sweep"]
    (fr,) = sweep["frequencies"]
    assert fr["start"] == "1.68GHz" and fr["stop"] == "3.12GHz"
    assert fr["increment"] == 401 and fr["distribution"] == "linear_count"
    assert config["boundaries"] == {"use_open_region": True,
                                    "open_region_type": "radiation"}


def test_cl_config_parses_pyedb_cfgdata(cl):
    """config dict 过 pyedb CfgData 离线解析（零 EDB 会话）：段合法零警告。"""
    pytest.importorskip("pyedb")
    from pyedb.configuration.cfg_data import CfgData

    spec, config = cl
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        data = CfgData(pedb=None, **config)
    unknown = [str(w.message) for w in caught
               if "Unknown configuration section" in str(w.message)]
    assert unknown == []
    assert len(data.modeler.traces) == len(spec["traces"])
    assert len(data.modeler.planes) == 1
    assert len(data.ports.ports) == len(spec["ports"])
    (setup,) = data.setups.setups
    assert type(setup).__name__ == "CfgHFSSSetup"


def test_cl_pure_and_param_guards():
    a = emit_coupled_line_spec({"f0_ghz": F0})
    b = emit_coupled_line_spec({"f0_ghz": F0})
    assert a == b  # 纯函数确定性
    params = {"f0_ghz": F0, "sweep": {"points": 201}}
    frozen = copy.deepcopy(params)
    emit_coupled_line_spec(params)
    assert params == frozen  # 无入参突变副作用
    with pytest.raises(ValueError, match="f0_ghz"):
        emit_coupled_line_spec({"f0_ghz": -1.0})
    with pytest.raises(ValueError, match="50Ω"):
        emit_coupled_line_spec({"f0_ghz": F0, "z0_ohm": 75.0})
    with pytest.raises(ValueError, match="coupling_db"):
        emit_coupled_line_spec({"f0_ghz": F0, "coupling_db": 0.0})
    with pytest.raises(ValueError, match="coupling_db"):
        emit_coupled_line_spec({"f0_ghz": F0, "coupling_db": -3.0})
    with pytest.raises(ValueError, match="feed_len_mm"):
        emit_coupled_line_spec({"f0_ghz": F0, "feed_len_mm": 0.0})


def test_cl_custom_params_flow():
    spec, _ = emit_coupled_line_spec({
        "f0_ghz": 5.8, "coupling_db": 20.0, "feed_len_mm": 3.0,
        "sweep": {"start_ghz": 4.0, "stop_ghz": 7.6, "points": 201},
    })
    p = spec["params"]
    assert p["coupling_db"] == 20.0 and p["feed_len_mm"] == 3.0
    assert p["c"] == pytest.approx(10.0 ** (-20.0 / 20.0), rel=TOL)
    assert spec["sim_setup"]["sweep"] == {
        "name": "sweep1", "type": "interpolation",
        "start_ghz": 4.0, "stop_ghz": 7.6, "points": 201,
    }
    errors = validate_spec(spec)
    assert len(errors) == 2
    assert all(e.startswith(("template 非法:", "走线连通图非单连通"))
               for e in errors)


def test_cl_thickness_bias_note_nominal_region(cl):
    """s/t<4 区厚度偏置声明（W8 仲裁建议 3）：注记键在案、锚+区划线单源。

    名义 10dB 设计点 s≈0.082/t=0.035 → s/t≈2.34 落厚度偏置区：饱和锚
    +0.8dB@s/t=2.34（W8 HFSS 饱和口径，HFSS=对齐基准）；综合数值不改
    （w/s 单源逐位另钉 test_cl_single_source_registered_chain）。
    """
    from rfauto.adapters.edb_templates.coupled_line import (
        THICKNESS_BIAS_ANCHOR_DB,
        THICKNESS_BIAS_ANCHOR_ST,
        THICKNESS_BIAS_ST_DIVIDER,
    )

    spec, _ = cl
    p = spec["params"]
    note = p["thickness_bias_note"]
    assert f"s/t={p['s_mm'] / p['copper_thickness_mm']:.2f}" in note
    assert "+0.8dB@s/t=2.34" in note        # 饱和锚（HFSS 匹配档阶梯趋稳值）
    assert "HFSS=对齐基准" in note
    assert "厚度偏置区" in note
    assert "伪象主导区" not in note          # 名义点不在伪象主导区
    # 区划线/锚常量=声明正本（模块常量单源）
    assert THICKNESS_BIAS_ST_DIVIDER == 4.0
    assert THICKNESS_BIAS_ANCHOR_DB == 0.8
    assert THICKNESS_BIAS_ANCHOR_ST == 2.34
    # 注记键不改 validate 面（族豁免仍恰两行）
    errors = validate_spec(spec)
    assert len(errors) == 2


def test_cl_thickness_bias_guard_warning_only():
    """s/t≥4 伪象主导区守卫：UserWarning 仅提示不阻断（#122 数据不足硬门）。"""
    with pytest.warns(UserWarning, match="伪象主导区"):
        spec, _ = emit_coupled_line_spec(
            {"f0_ghz": F0, "copper_thickness_mm": 0.01})
    p = spec["params"]
    assert p["s_mm"] / p["copper_thickness_mm"] >= 4.0
    note = p["thickness_bias_note"]
    assert "伪象主导区" in note and "厚度偏置区" not in note
    assert "+2.274dB@s/t=4.29" in note      # W8 V3 实测（伪象主导区锚）
    # warning 不阻断发射、不改综合数值（同 f0/coupling 综合单源逐位同值）
    assert spec["template"] == "edb_coupled_line"
    ref, _ = emit_coupled_line_spec({"f0_ghz": F0})
    assert (p["w_mm"], p["s_mm"], p["coupled_len_mm"]) == (
        ref["params"]["w_mm"], ref["params"]["s_mm"],
        ref["params"]["coupled_len_mm"])


def test_cl_thickness_bias_no_warning_nominal():
    """名义点（s/t≈2.34<4）不发伪象区守卫；零厚口径注记在案（无偏置）。"""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        emit_coupled_line_spec({"f0_ghz": F0})
    assert [w for w in caught if "伪象主导区" in str(w.message)] == []
    zero_spec, _ = emit_coupled_line_spec(
        {"f0_ghz": F0, "copper_thickness_mm": 0.0})
    assert "零厚" in zero_spec["params"]["thickness_bias_note"]
    assert "厚度偏置区" not in zero_spec["params"]["thickness_bias_note"]


# ── W8 仲裁判读档（建议 1：紧缝族生产判读档加严，2026-10-09）────────────────


def test_cl_default_adapt_max_delta_tightened(cl):
    """缺省 adapt.max_delta=0.005（W8 加严档）：spec 与 config 存证同值。

    W8 真机三变体仲裁（两引擎对照+ΔS 阶梯）：
    名义设计点紧缝 s/h=0.161 下 ΔS=0.02 单档 S31 读数带 ~2dB 收敛档伪象
    （HFSS 3D 与 EDB 两引擎一致读 -7.2~-7.6，HFSS ΔS 阶梯 0.02→0.0025
    收紧回收 1.2~1.8dB）——0.02 档窗口判据测的是"网格收敛度"而非"器件
    物理"。config 侧同值=建模期写入面（3D Layout 真收紧通道，W8 建议 2）。
    """
    from rfauto.adapters.edb_templates.coupled_line import (
        DEFAULT_ADAPT_MAX_DELTA,
    )

    assert DEFAULT_ADAPT_MAX_DELTA == 0.005
    spec, config = cl
    assert spec["sim_setup"]["adapt"]["max_delta"] == 0.005
    (setup,) = config["setups"]
    assert setup["type"] == "hfss"
    assert setup["single_frequency_adaptive_solution"]["max_delta"] == 0.005
    # W8 证据在案：模块/函数 docstring 带仲裁出处（伪象量值/紧缝比可回溯）
    import rfauto.adapters.edb_templates.coupled_line as cl_mod

    doc = (cl_mod.__doc__ or "") + (cl_mod.emit_coupled_line_spec.__doc__ or "")
    assert "W8" in doc and "0.005" in doc and "0.161" in doc


def test_cl_adapt_max_delta_explicit_override():
    """加严档可显式覆盖：params.adapt.max_delta 原样透传（不静默钳位）。"""
    spec, _ = emit_coupled_line_spec({"f0_ghz": F0, "adapt": {"max_delta": 0.02}})
    assert spec["sim_setup"]["adapt"]["max_delta"] == 0.02
    spec2, _ = emit_coupled_line_spec({
        "f0_ghz": F0, "adapt": {"max_passes": 30, "max_delta": 0.001}})
    assert spec2["sim_setup"]["adapt"]["max_passes"] == 30
    assert spec2["sim_setup"]["adapt"]["max_delta"] == 0.001


def test_cl_tightened_scope_is_family_only():
    """加严仅限 coupled_line（模板作用域分派，#274 家法）：他族仍 0.02。"""
    from rfauto.adapters.edb_templates import (
        emit_branchline_spec,
        emit_power_divider_spec,
    )

    for emit in (emit_branchline_spec, emit_power_divider_spec,
                 emit_ratrace_spec):
        spec, _ = emit({"f0_ghz": F0})
        assert spec["sim_setup"]["adapt"]["max_delta"] == 0.02, emit.__name__


# ═══ ratrace（edb_ratrace）═══════════════════════════════════════════════════


def test_rr_spec_contract_and_validate(rr):
    spec, config = rr
    for key in ("stackup", "traces", "vias", "ports", "sim_setup"):
        assert key in spec, f"契约字段缺失: {key}"
    assert spec["template"] == "edb_ratrace"
    assert spec["schema_version"] == 1
    assert spec["units"] == {"length": "mm", "frequency": "GHz"}
    # 族豁免恰一行（template 白名单）；环+四馈线单连通走正本审计全绿
    errors = validate_spec(spec)
    assert len(errors) == 1
    assert errors[0].startswith("template 非法:")
    assert set(config) == {"stackup", "modeler", "ports", "setups", "boundaries"}


def test_rr_numerics_match_closed_form(rr):
    spec, _ = rr
    p = spec["params"]
    assert p["z_ring_ohm"] == 50.0 * math.sqrt(2.0)
    from rfauto.core.synthesis import Stackup, forward_media, inverse_width

    st = Stackup(name="audit", **STACKUP_KW)
    w, z_act, status = inverse_width(p["z_ring_ohm"], F0, st)
    assert status == "ok"
    assert abs(z_act - p["z_ring_ohm"]) < 1e-3  # 回代正向（brentq 量级）
    eps = float(forward_media(w, F0, st).er_eff)
    assert p["w_ring_mm"] == pytest.approx(w, abs=TOL)
    assert p["eps_eff_ring"] == pytest.approx(eps, rel=TOL)
    lam = C0_MM_GHZ / (F0 * math.sqrt(eps))
    assert p["lam_g_mm"] == pytest.approx(lam, rel=TOL)
    assert p["perimeter_mm"] == pytest.approx(1.5 * lam, rel=TOL)  # 周长 1.5λg
    assert p["side_mm"] == pytest.approx(1.5 * lam / 4.0, rel=TOL)
    assert p["r_ring_equivalent_mm"] == pytest.approx(
        1.5 * lam / (2.0 * math.pi), rel=TOL)


def test_rr_single_source_registered_synthesis(rr):
    """与注册 ratrace 模板 synthesize_ratrace_model 同综合单源（舍入档）。"""
    from rfauto.core.synthesis import synthesize_ratrace_model

    spec, _ = rr
    p = spec["params"]
    reg = synthesize_ratrace_model(50.0, F0, "rogers4350b_h0.508").params
    assert p["w_ring_mm"] == pytest.approx(reg["w_ring_mm"], abs=5e-4)  # 4 位舍入
    assert p["r_ring_equivalent_mm"] == pytest.approx(float(reg["r_ring_mm"]),
                                                      abs=5e-3)  # 3 位舍入


def test_rr_geometry_audit(rr):
    spec, _ = rr
    p = spec["params"]
    half = p["side_mm"] / 2.0
    off = p["lam_g_mm"] / 8.0
    feed = p["feed_len_mm"]
    by_name = {tr["name"]: tr for tr in spec["traces"]}
    assert set(by_name) == {
        "side_right_low", "side_right_high",
        "side_top_e", "side_top_mid", "side_top_w",
        "side_left", "side_bottom_w", "side_bottom_e",
        "feed_p1", "feed_p2", "feed_p3", "feed_p4",
    }
    for name in by_name:
        if by_name[name]["role"] == "ring":
            assert by_name[name]["width_mm"] == pytest.approx(p["w_ring_mm"], abs=TOL)
    assert by_name["side_right_low"]["path_mm"] == [[half, -half], [half, 0.0]]
    assert by_name["side_right_high"]["path_mm"] == [[half, 0.0], [half, half]]
    assert by_name["side_top_e"]["path_mm"] == [[half, half], [off, half]]
    assert by_name["side_top_mid"]["path_mm"] == [[off, half], [-off, half]]
    assert by_name["side_top_w"]["path_mm"] == [[-off, half], [-half, half]]
    assert by_name["side_left"]["path_mm"] == [[-half, half], [-half, -half]]
    assert by_name["side_bottom_w"]["path_mm"] == [[-half, -half], [off, -half]]
    assert by_name["side_bottom_e"]["path_mm"] == [[off, -half], [half, -half]]
    for name in ("feed_p1", "feed_p2", "feed_p3", "feed_p4"):
        assert by_name[name]["width_mm"] == pytest.approx(p["w_feed_mm"], abs=TOL)
    assert by_name["feed_p1"]["path_mm"] == [[half, 0.0], [half + feed, 0.0]]
    assert by_name["feed_p2"]["path_mm"] == [[off, half], [off, half + feed]]
    assert by_name["feed_p3"]["path_mm"] == [[-off, half], [-off, half + feed]]
    assert by_name["feed_p4"]["path_mm"] == [[off, -half], [off, -half - feed]]
    # 环带中心线总长 = 周长 1.5λg（分段不改变电长度）
    ring_len = sum(
        math.hypot(tr["path_mm"][1][0] - tr["path_mm"][0][0],
                   tr["path_mm"][1][1] - tr["path_mm"][0][1])
        for tr in spec["traces"] if tr["role"] == "ring")
    assert ring_len == pytest.approx(p["perimeter_mm"], rel=TOL)
    # 环 + 四馈线一体单连通（分段端点-重合=双向附着边，冻结底座可并）
    adj = trace_attach_graph(spec["traces"])
    assert len(trace_connected_components(adj)) == 1
    # 端口语义与落位
    assert [(pt["name"], pt["port_nr"], pt["trace"]) for pt in spec["ports"]] == [
        ("P1", 1, "feed_p1"), ("P2", 2, "feed_p2"),
        ("P3", 3, "feed_p3"), ("P4", 4, "feed_p4"),
    ]
    ends = {pt["name"]: pt["point_mm"] for pt in spec["ports"]}
    assert ends["P1"] == [half + feed, 0.0]
    assert ends["P2"] == [off, half + feed]
    assert ends["P3"] == [-off, half + feed]
    assert ends["P4"] == [off, -half - feed]


def test_rr_ring_closure_and_arc_positions(rr):
    """环分段闭合（段端点互享）+ 端口弧位 0/±λ/4/+λ/2 精确（中心线弧长）。"""
    spec, _ = rr
    p = spec["params"]
    half = p["side_mm"] / 2.0
    off = p["lam_g_mm"] / 8.0
    ring_trs = [tr for tr in spec["traces"] if tr["role"] == "ring"]
    # 每段端点必与另一环段端点重合（闭合环，1e-9）
    ends_list: list[tuple[str, tuple[float, float]]] = []
    for tr in ring_trs:
        for pt in tr["path_mm"]:
            ends_list.append((tr["name"], (float(pt[0]), float(pt[1]))))
    for name, (x, y) in ends_list:
        assert any(math.hypot(x - x2, y - y2) <= TOL
                   for name2, (x2, y2) in ends_list if name2 != name), (name, x, y)
    # 弧位（Σ=右边中点 (half,0)：上右边 half + 顶边左行至端口 x）
    arc_out1 = half + (half - off)   # P2（+λ/4）
    arc_out2 = half + (half - off)   # P4（−λ/4，镜像）
    arc_delta = half + (half + off)  # P3（+λ/2）
    assert arc_out1 == pytest.approx(p["lam_g_mm"] / 4.0, rel=TOL)
    assert arc_out2 == pytest.approx(p["lam_g_mm"] / 4.0, rel=TOL)
    assert arc_delta == pytest.approx(p["lam_g_mm"] / 2.0, rel=TOL)
    # out1/out2 关于 Σ 镜像；Δ 与 out1 同在顶边、关于 y 轴对称
    by_name = {tr["name"]: tr for tr in spec["traces"]}
    assert by_name["feed_p4"]["path_mm"][0] == [off, -half]
    assert by_name["feed_p3"]["path_mm"][0] == [-off, half]


def test_rr_port_attach_closed_form_arc_degrees(rr):
    """四端口环接入点坐标对闭式弧位（geo 0°/60°/120°/300°）逐点 1e-9。

    闭式口径（Pozar §7.5；docs/rf_template_references.md §9 #208 定版）：
    周长 C=1.5λg 上弧位 Σ=0、out1=+λ/4、Δ=+λ/2、out2=−λ/4——等效圆 geo
    角=弧/C·360° 即 0°/60°/120°/300°；**out2 不得放 geo 180**（Σ 直径对
    点=两侧各 3λ/4 的"匹配直通"位置，pt5 实测 −0.54dB 直通+S11 −11dB，
    #208；docs/templates/ratrace/meta.yaml 抽取行曾误写 out2=180°，本仲裁
    归正为 300°）。方形环实现中心线弧长精确：half=P/8、off=λg/8 下接入点
    Σ=(half,0)、out1=(off,half)、Δ=(−off,half)、out2=(off,−half)。
    """
    spec, _ = rr
    p = spec["params"]
    lam = p["lam_g_mm"]
    per = p["perimeter_mm"]
    half = p["side_mm"] / 2.0            # = P/8
    off = lam / 8.0                      # = λg/8
    by_name = {tr["name"]: tr for tr in spec["traces"]}
    # 馈线环侧端点=环接入点（馈线自接入点沿边中心线向外引出）
    attach = {f"P{i}": by_name[f"feed_p{i}"]["path_mm"][0]
              for i in range(1, 5)}
    closed = {                           # 闭式弧位 → 中心线接入点坐标
        "P1": (half, 0.0),               # Σ：geo 0°（弧 0，右缘中点）
        "P2": (off, half),               # out1：弧 +λ/4（geo 60°）
        "P3": (-off, half),              # Δ：弧 +λ/2（geo 120°）
        "P4": (off, -half),              # out2：弧 −λ/4（geo 300°）
    }
    for pn, (cx, cy) in closed.items():
        x, y = (float(v) for v in attach[pn])
        assert math.hypot(x - cx, y - cy) <= TOL, (pn, x, y, cx, cy)
    # 弧长闭式（自 Σ 沿中心线计量，方形实现逐段精确）与等效圆 geo 角
    arc_len = {
        "P1": 0.0,
        "P2": half + (half - off),       # 右边缘上行 half + 顶边左行
        "P3": half + (half + off),
        "P4": -(half + (half - off)),    # 关于 Σ 镜像（顺时针 −λ/4）
    }
    expect_arc = {"P1": 0.0, "P2": lam / 4.0,
                  "P3": lam / 2.0, "P4": -lam / 4.0}
    expect_deg = {"P1": 0.0, "P2": 60.0, "P3": 120.0, "P4": 300.0}
    for pn, a in arc_len.items():
        assert a == pytest.approx(expect_arc[pn], rel=TOL), pn
        assert (a / per * 360.0) % 360.0 == pytest.approx(
            expect_deg[pn], abs=1e-9), pn
    # 发射器自述口径与闭式一致（docstring↔geometry 漂移守卫，本仲裁镜像）
    assert "Σ=0°/out1=60°/Δ=120°/out2=300°" in p["topology_note"]


def test_rr_feed_area_overlaps(rr):
    """馈线与所接环带段正面积重叠（连通）；馈线间/馈线与非所接段零重叠。"""
    spec, _ = rr
    by_name = {tr["name"]: tr for tr in spec["traces"]}
    rects = {name: _rect(tr) for name, tr in by_name.items()}
    adj_map = {
        "feed_p1": ("side_right_low", "side_right_high"),
        "feed_p2": ("side_top_e", "side_top_mid"),
        "feed_p3": ("side_top_mid", "side_top_w"),
        "feed_p4": ("side_bottom_e", "side_bottom_w"),
    }
    for fn, sides in adj_map.items():
        for sn in sides:
            assert _overlap_area(rects[fn], rects[sn]) > 0.0, (fn, sn)
    feeds = tuple(adj_map)
    for i, fa in enumerate(feeds):
        for fb in feeds[i + 1:]:
            assert _overlap_area(rects[fa], rects[fb]) == 0.0, (fa, fb)
    ring_names = tuple(n for n, tr in by_name.items() if tr["role"] == "ring")
    for fn, sides in adj_map.items():
        for rn in ring_names:
            if rn not in sides:
                assert _overlap_area(rects[fn], rects[rn]) == 0.0, (fn, rn)


def test_rr_axis_aligned_and_board(rr):
    spec, _ = rr
    x0, y0 = spec["board"]["lower_left_mm"]
    x1, y1 = spec["board"]["upper_right_mm"]
    for tr in spec["traces"]:
        _rect(tr)  # 非轴对齐在此抛 AssertionError
        w2 = tr["width_mm"] / 2.0
        for x, y in tr["path_mm"]:
            assert x0 - 1e-12 <= x - w2 and x + w2 <= x1 + 1e-12
            assert y0 - 1e-12 <= y - w2 and y + w2 <= y1 + 1e-12


def test_rr_config_json_shape(rr):
    spec, config = rr
    layers = config["stackup"]["layers"]
    # config 自顶向下（spec 自底向上翻转；pyedb AddLayerBottom 首项落物理
    # 顶层，2026-10-08 审查批 P0 修复）
    assert [la["name"] for la in layers] == ["TOP", "SUB", "GND"]
    for tr_cfg, tr_spec in zip(config["modeler"]["traces"], spec["traces"],
                               strict=True):
        assert tr_cfg["name"] == tr_spec["name"] and tr_cfg["layer"] == "TOP"
        assert tr_cfg["path"] == [[x * 1e-3, y * 1e-3] for x, y in tr_spec["path_mm"]]
        assert abs(float(tr_cfg["width"][:-2]) - tr_spec["width_mm"]) < 1e-8
        assert tr_cfg["start_cap_style"] == "flat"
        assert tr_cfg["corner_style"] == "sharp"
    assert [pl["name"] for pl in config["modeler"]["planes"]] == ["GND_plane"]
    for pt_cfg, pt_spec in zip(config["ports"], spec["ports"], strict=True):
        assert pt_cfg["type"] == "wave_port"
        assert pt_cfg["primitive_name"] == pt_spec["trace"]
        assert pt_cfg["point_on_edge"] == [pt_spec["point_mm"][0] * 1e-3,
                                           pt_spec["point_mm"][1] * 1e-3]
    (setup,) = config["setups"]
    assert setup["single_frequency_adaptive_solution"]["adaptive_frequency"] == "2.4GHz"
    (sweep,) = setup["freq_sweep"]
    (fr,) = sweep["frequencies"]
    assert fr["start"] == "1.68GHz" and fr["stop"] == "3.12GHz"
    assert fr["increment"] == 401 and fr["distribution"] == "linear_count"


def test_rr_config_parses_pyedb_cfgdata(rr):
    pytest.importorskip("pyedb")
    from pyedb.configuration.cfg_data import CfgData

    spec, config = rr
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        data = CfgData(pedb=None, **config)
    unknown = [str(w.message) for w in caught
               if "Unknown configuration section" in str(w.message)]
    assert unknown == []
    assert len(data.modeler.traces) == len(spec["traces"])
    assert len(data.modeler.planes) == 1
    assert len(data.ports.ports) == len(spec["ports"])
    (setup,) = data.setups.setups
    assert type(setup).__name__ == "CfgHFSSSetup"


def test_rr_pure_and_param_guards():
    a = emit_ratrace_spec({"f0_ghz": F0})
    b = emit_ratrace_spec({"f0_ghz": F0})
    assert a == b
    params = {"f0_ghz": F0, "adapt": {"max_passes": 8}}
    frozen = copy.deepcopy(params)
    emit_ratrace_spec(params)
    assert params == frozen
    with pytest.raises(ValueError, match="f0_ghz"):
        emit_ratrace_spec({"f0_ghz": -1.0})
    with pytest.raises(ValueError, match="50Ω"):
        emit_ratrace_spec({"f0_ghz": F0, "z0_ohm": 75.0})
    with pytest.raises(ValueError, match="feed_len_mm"):
        emit_ratrace_spec({"f0_ghz": F0, "feed_len_mm": -1.0})
    spec, _ = emit_ratrace_spec({
        "f0_ghz": 5.8, "feed_len_mm": 3.0,
        "sweep": {"start_ghz": 4.0, "stop_ghz": 7.6, "points": 201},
    })
    assert spec["params"]["feed_len_mm"] == 3.0
    assert spec["sim_setup"]["sweep"]["points"] == 201
    assert spec["sim_setup"]["adapt"]["max_passes"] == 20  # 未传 adapt 走缺省
    errors = validate_spec(spec)
    assert len(errors) == 1 and errors[0].startswith("template 非法:")


# ═══ lange（综合单源 + EDB 发射声明不支持）═══════════════════════════════════


def test_lg_emit_declared_unsupported():
    with pytest.raises(NotImplementedError, match="不支持"):
        emit_lange_spec({"f0_ghz": F0})
    with pytest.raises(NotImplementedError, match="crossover"):
        emit_lange_spec({"f0_ghz": F0, "coupling_db": 3.0103,
                         "stackup": dict(STACKUP_KW, name="rogers4350b_h0.508")})


def test_lg_supported_flag_and_docs():
    import rfauto.adapters.edb_templates.lange as mod

    assert LANGE_EDB_SUPPORTED is False
    assert mod.TEMPLATE_KEY_RESERVED == "edb_lange"
    doc = (mod.__doc__ or "") + (mod.emit_lange_spec.__doc__ or "")
    assert "Jordan" in doc  # 平面性论证在案
    assert "不支持" in doc
    assert "crossover" in doc or "跨线" in doc


def test_lg_input_validation_precedes_capability():
    with pytest.raises(KeyError):
        emit_lange_spec({})  # f0 缺失
    with pytest.raises(ValueError, match="f0_ghz"):
        emit_lange_spec({"f0_ghz": -1.0})
    with pytest.raises(ValueError, match="50Ω"):
        emit_lange_spec({"f0_ghz": F0, "z0_ohm": 75.0})


def test_lg_synth_matches_registered_design():
    """综合单源：lange_synth == 注册模板 lange_design 同函数同参（逐位）。"""
    from rfauto.adapters.oe_templates.render_c4 import lange_design

    d_ref = lange_design(f0_ghz=F0, z0_ohm=50.0, coupling_db=3.0103,
                         er=3.66, h_mm=0.508)
    assert lange_synth({"f0_ghz": F0}) == d_ref


def test_lg_synth_3db_nominal():
    """@2.5GHz/3dB 与注册 LANGE_NOMINAL 同名义点（舍入档 5e-4）。"""
    from rfauto.adapters.oe_templates.render_c4 import LANGE_NOMINAL

    d = lange_synth({"f0_ghz": 2.5})
    assert d["w_mm"] == pytest.approx(LANGE_NOMINAL["w_mm"], abs=5e-4)
    assert d["s_mm"] == pytest.approx(LANGE_NOMINAL["gap_mm"], abs=5e-4)
    assert d["finger_len_mm"] == pytest.approx(LANGE_NOMINAL["finger_len_mm"],
                                               abs=5e-4)
    assert d["w_feed_mm"] == pytest.approx(LANGE_NOMINAL["w_feed_mm"], abs=5e-4)


def test_lg_closed_form_roundtrip():
    """Pozar 设计式自洽回代：C=1/√2 → 相邻对 → 四线等效 → C/Z0 逐位闭合。"""
    from rfauto.adapters.oe_templates.render_c4 import (
        lange_equivalent_zee_zoo,
        lange_pair_zee_zoo,
    )

    c3 = 1.0 / math.sqrt(2.0)
    zee, zoo = lange_pair_zee_zoo(c3, 50.0)
    assert zee == pytest.approx(176.216, abs=5e-3)
    assert zoo == pytest.approx(52.609, abs=5e-3)
    ze4, zo4 = lange_equivalent_zee_zoo(zee, zoo)
    assert (ze4 - zo4) / (ze4 + zo4) == pytest.approx(c3, rel=1e-9)
    assert math.sqrt(ze4 * zo4) == pytest.approx(50.0, rel=1e-9)


def test_lg_synth_guards():
    with pytest.raises(ValueError, match="f0_ghz"):
        lange_synth({"f0_ghz": 0.0})
    with pytest.raises(ValueError, match="50Ω"):
        lange_synth({"f0_ghz": F0, "z0_ohm": 60.0})
    with pytest.raises(ValueError, match="coupling"):
        lange_synth({"f0_ghz": F0, "coupling_db": -6.0})  # C>1 出可达域


def test_lg_finger_len_formula():
    """指长 = λ/4 @ 平均 εeff（KJ 正向回代 1e-9）+ (w,s) 恢复相邻对阻抗。"""
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    d = lange_synth({"f0_ghz": F0})
    ze, zo, ee, eo = coupled_microstrip_even_odd_ohm(
        d["w_mm"], d["s_mm"], F0, 3.66, 0.508)
    assert abs(ze - d["zee_pair_ohm"]) < 1e-3
    assert abs(zo - d["zoo_pair_ohm"]) < 1e-3
    assert d["finger_len_mm"] == pytest.approx(
        C0_MM_GHZ / (4.0 * F0 * math.sqrt(0.5 * (ee + eo))), rel=TOL)


def test_lg_known_templates_untouched():
    """schema.py 正本逻辑不动纪律：白名单仍两族（扩展族升格走 followUp）。"""
    assert KNOWN_TEMPLATES == ("edb_branchline", "edb_power_divider")
