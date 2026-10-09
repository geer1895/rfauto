"""EDB 平面族模板发射器单测：离线几何审计 + 综合值数值对照 + PyEDB 配置形态。

审计制度化（#212 先例）：测试实际执行发射函数（emit_branchline_spec /
emit_power_divider_spec），对产出 spec 做完备性与几何审计（层齐全/走线
端点-附着图单连通/端口 1e-9 落走线端点/50Ω 端口宽=综合单源值），全程
零 pyedb 依赖（pyedb 仅在 importorskip 的配置形态回溯测试中出现）。

数值断言口径（任务书"测试内独立重导公式对照，允许 1e-9 级"）：
  1. 线宽/臂长在测试内独立重导：core.synthesis.inverse_width（HJ 反解）
     → forward_media(εeff) → λg/4=c/(4·f0·√εeff)，与 spec params 逐值
     1e-9 对照；线宽回代正向 |Z0(w)−Z目标| < 1e-3Ω（brentq xtol=1e-6mm）。
  2. 50Ω 端口宽 = nominal_width_mm(50, f0, "rogers4350b_h0.508",
     digits=None) 逐位相等（XC-W 单源权威；同参数同 brentq 路径必逐位）。
  3. 名义参数口径与已注册模板同综合单源（任务书要求 3）：与
     synthesize_branchline / synthesize_wilkinson 的 params（2/3 位舍入档）
     对照，容差=舍入半步（长度 5e-3mm、宽度 5e-4mm）。
"""

from __future__ import annotations

import copy
import math
import re
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
    emit_branchline_spec,
    emit_power_divider_spec,
    trace_attach_graph,
    trace_connected_components,
    validate_spec,
)
from rfauto.adapters.edb_templates.power_divider import DEFAULT_GAP_MM

C0_MM_GHZ = 299.792458  # c（mm·GHz，与 core.synthesis 同常数）
F0 = 2.4
STACKUP_KW = dict(epsilon_r=3.66, thickness_mm=0.508, loss_tangent=0.0037)

TOL = 1e-9


# ─── 独立重导（测试内自带公式链，不信发射器记账）────────────────────────────


def _rederive(f0: float) -> dict[str, float]:
    """branchline 口径独立重导：35.35/50Ω 线宽 + 各自 εeff + 各自 λ/4。"""
    from rfauto.core.synthesis import Stackup, forward_media, inverse_width

    st = Stackup(name="audit", **STACKUP_KW)
    out: dict[str, float] = {}
    for key, z_target in (("series", 50.0 / math.sqrt(2.0)), ("shunt", 50.0)):
        w, z_act, status = inverse_width(z_target, f0, st)
        assert status == "ok"
        assert abs(z_act - z_target) < 1e-3  # 回代正向（brentq xtol=1e-6mm 量级）
        eps = float(forward_media(w, f0, st).er_eff)
        out[f"w_{key}"] = float(w)
        out[f"eps_{key}"] = eps
        out[f"len_{key}"] = C0_MM_GHZ / (4.0 * f0 * math.sqrt(eps))
    return out


def _rederive_pd(f0: float) -> dict[str, float]:
    """功分器口径独立重导：70.7Ω 臂宽/λ/4 + 50Ω 馈线宽。"""
    from rfauto.core.synthesis import Stackup, forward_media, inverse_width

    st = Stackup(name="audit", **STACKUP_KW)
    out: dict[str, float] = {}
    for key, z_target in (("series", 50.0 * math.sqrt(2.0)), ("shunt", 50.0)):
        w, z_act, status = inverse_width(z_target, f0, st)
        assert status == "ok"
        assert abs(z_act - z_target) < 1e-3
        eps = float(forward_media(w, f0, st).er_eff)
        out[f"w_{key}"] = float(w)
        out[f"eps_{key}"] = eps
        out[f"len_{key}"] = C0_MM_GHZ / (4.0 * f0 * math.sqrt(eps))
    return out


@pytest.fixture(scope="module")
def bl() -> tuple[dict, dict]:
    return emit_branchline_spec({"f0_ghz": F0})


@pytest.fixture(scope="module")
def pd() -> tuple[dict, dict]:
    return emit_power_divider_spec({"f0_ghz": F0})


# ─── spec 完备性（契约五字段 + schema 校验）─────────────────────────────────


def test_branchline_spec_contract_and_validate(bl):
    spec, config = bl
    for key in ("stackup", "traces", "vias", "ports", "sim_setup"):
        assert key in spec, f"契约字段缺失: {key}"
    assert spec["template"] == "edb_branchline"
    assert spec["schema_version"] == 1
    assert spec["units"] == {"length": "mm", "frequency": "GHz"}
    assert validate_spec(spec) == []
    assert set(config) == {"stackup", "modeler", "ports", "setups", "boundaries"}


def test_power_divider_spec_contract_and_validate(pd):
    spec, config = pd
    for key in ("stackup", "traces", "vias", "ports", "sim_setup"):
        assert key in spec, f"契约字段缺失: {key}"
    assert spec["template"] == "edb_power_divider"
    assert validate_spec(spec) == []
    assert set(config) == {"stackup", "modeler", "ports", "setups", "boundaries"}


def test_stackup_layers_complete(bl, pd):
    for spec, _ in (bl, pd):
        layers = spec["stackup"]["layers"]
        assert [la["name"] for la in layers] == ["GND", "SUB", "TOP"]  # 自底向上
        assert [la["type"] for la in layers] == ["signal", "dielectric", "signal"]
        sub = layers[1]
        assert sub["material"] == "rogers4350b_h0.508"
        assert sub["thickness_mm"] == 0.508
        mats = {m["name"]: m for m in spec["stackup"]["materials"]}
        assert mats["rogers4350b_h0.508"]["permittivity"] == 3.66
        assert mats["rogers4350b_h0.508"]["dielectric_loss_tangent"] == 0.0037
        assert abs(mats["copper"]["conductivity"] - 1.0 / 1.724e-8) < 1e-3


# ─── 数值对照：独立重导 1e-9 + 单源一致性 ────────────────────────────────────


def test_branchline_numerics_match_closed_form(bl):
    spec, _ = bl
    p = spec["params"]
    rd = _rederive(F0)
    assert p["series_w_mm"] == pytest.approx(rd["w_series"], abs=TOL)
    assert p["shunt_w_mm"] == pytest.approx(rd["w_shunt"], abs=TOL)
    assert p["series_len_mm"] == pytest.approx(rd["len_series"], rel=TOL)
    assert p["shunt_len_mm"] == pytest.approx(rd["len_shunt"], rel=TOL)
    assert p["eps_eff_series"] == pytest.approx(rd["eps_series"], rel=TOL)
    # 阻抗目标闭式：串联臂 = Z0/√2 = 35.355...Ω
    assert p["z_series_ohm"] == 50.0 / math.sqrt(2.0)
    # λ/4 电长度闭式再复核（用 spec 自身 εeff 第三方复核长度记账）
    assert p["series_len_mm"] == pytest.approx(
        C0_MM_GHZ / (4.0 * F0 * math.sqrt(p["eps_eff_series"])), rel=TOL)


def test_branchline_nominal_single_source_consistency(bl):
    """任务书要求 3：与已注册 branchline 模板（synthesize_branchline）同综合单源。"""
    from rfauto.core.synthesis import synthesize_branchline

    spec, _ = bl
    p = spec["params"]
    reg = synthesize_branchline(F0, 50.0).params  # 缺省 yaml 层叠=发射器缺省标量
    assert p["series_w_mm"] == pytest.approx(reg["series_w_mm"], abs=5e-4)  # 3 位舍入半步
    assert p["shunt_w_mm"] == pytest.approx(reg["shunt_w_mm"], abs=5e-4)
    assert p["series_len_mm"] == pytest.approx(reg["series_len_mm"], abs=5e-3)  # 2 位
    assert p["shunt_len_mm"] == pytest.approx(reg["shunt_len_mm"], abs=5e-3)


def test_power_divider_numerics_match_closed_form(pd):
    spec, _ = pd
    p = spec["params"]
    rd = _rederive_pd(F0)
    assert p["series_w_mm"] == pytest.approx(rd["w_series"], abs=TOL)  # 70.7Ω 臂宽
    assert p["shunt_w_mm"] == pytest.approx(rd["w_shunt"], abs=TOL)
    assert p["arm_len_mm"] == pytest.approx(rd["len_series"], rel=TOL)  # λ/4@臂 εeff
    assert p["z_series_ohm"] == 50.0 * math.sqrt(2.0)
    assert p["iso_r_ohm"] == 100.0  # 2·Z0 闭式
    assert p["arm_len_mm"] == pytest.approx(
        C0_MM_GHZ / (4.0 * F0 * math.sqrt(p["eps_eff_series"])), rel=TOL)


def test_power_divider_nominal_single_source_consistency(pd):
    """任务书要求 3：与已注册 wilkinson 模板（synthesize_wilkinson）同综合单源。"""
    from rfauto.core.synthesis import synthesize_wilkinson

    spec, _ = pd
    p = spec["params"]
    reg = synthesize_wilkinson(F0, 50.0).params
    assert p["series_w_mm"] == pytest.approx(reg["series_w_mm"], abs=5e-4)
    assert p["shunt_w_mm"] == pytest.approx(reg["shunt_w_mm"], abs=5e-4)
    assert p["arm_len_mm"] == pytest.approx(reg["arm_len_mm"], abs=5e-3)


def test_50ohm_port_width_is_synthesis_authority(bl, pd):
    """50Ω 端口/馈线宽 = nominal_width_mm 单源全精度档，逐位相等（XC-W 口径）。"""
    from rfauto.core.synthesis import nominal_width_mm

    w_src = nominal_width_mm(50.0, F0, "rogers4350b_h0.508", digits=None)
    for spec in (bl[0], pd[0]):
        p = spec["params"]
        assert p["shunt_w_mm"] == w_src  # 同参数同 brentq 路径必逐位
        for tr in spec["traces"]:
            if tr["role"] == "feed":
                assert tr["width_mm"] == w_src
        for pt in spec["ports"]:
            assert pt["impedance"] == 50.0


# ─── 离线几何审计：branchline 矩形环 ─────────────────────────────────────────


def test_branchline_geometry_audit(bl):
    spec, _ = bl
    p = spec["params"]
    sl, shl = p["series_len_mm"], p["shunt_len_mm"]
    hx, hy = sl / 2.0, shl / 2.0
    feed = p["feed_len_mm"]
    by_name = {tr["name"]: tr for tr in spec["traces"]}
    assert set(by_name) == {
        "arm_top", "arm_bottom", "arm_left", "arm_right",
        "feed_p1", "feed_p2", "feed_p3", "feed_p4",
    }
    # 横臂=串联臂（35.35Ω 宽、λ/4@εeff_series 长）；竖臂/馈线=50Ω 宽
    for name in ("arm_top", "arm_bottom"):
        assert by_name[name]["width_mm"] == pytest.approx(p["series_w_mm"], abs=TOL)
        assert by_name[name]["path_mm"] == [[-hx, hy if name == "arm_top" else -hy],
                                            [hx, hy if name == "arm_top" else -hy]]
    for name, x in (("arm_left", -hx), ("arm_right", hx)):
        assert by_name[name]["width_mm"] == pytest.approx(p["shunt_w_mm"], abs=TOL)
        assert by_name[name]["path_mm"] == [[x, -hy], [x, hy]]
    # 馈线从环四角沿臂线引出（角馈口径，与 openEMS 渲染器同布局）
    assert by_name["feed_p1"]["path_mm"] == [[-hx, -hy], [-hx, -hy - feed]]
    assert by_name["feed_p2"]["path_mm"] == [[hx, -hy], [hx + feed, -hy]]
    assert by_name["feed_p3"]["path_mm"] == [[hx, hy], [hx, hy + feed]]
    assert by_name["feed_p4"]["path_mm"] == [[-hx, hy], [-hx - feed, hy]]
    # 端点-附着图单连通（环+四馈线一体）
    adj = trace_attach_graph(spec["traces"])
    assert len(trace_connected_components(adj)) == 1
    # 端口语义：P1 输入/P2 直通/P3 耦合/P4 隔离，全部落在馈线端点
    assert [(pt["name"], pt["port_nr"], pt["trace"]) for pt in spec["ports"]] == [
        ("P1", 1, "feed_p1"), ("P2", 2, "feed_p2"),
        ("P3", 3, "feed_p3"), ("P4", 4, "feed_p4"),
    ]
    ends = {pt["name"]: pt["point_mm"] for pt in spec["ports"]}
    assert ends["P1"] == [-hx, -hy - feed]
    assert ends["P2"] == [hx + feed, -hy]
    assert ends["P3"] == [hx, hy + feed]
    assert ends["P4"] == [-hx - feed, hy]


def test_power_divider_geometry_audit(pd):
    spec, _ = pd
    p = spec["params"]
    al, g = p["arm_len_mm"], p["gap_mm"]
    half_g = g / 2.0
    y_end, y_out = -al, -al - p["out_len_mm"]
    by_name = {tr["name"]: tr for tr in spec["traces"]}
    assert set(by_name) == {
        "trace_input", "trace_junction", "trace_arm1", "trace_arm2",
        "trace_out1", "trace_out2",
    }
    assert by_name["trace_arm1"]["path_mm"] == [[half_g, 0.0], [half_g, y_end]]
    assert by_name["trace_arm2"]["path_mm"] == [[-half_g, 0.0], [-half_g, y_end]]
    for name in ("trace_arm1", "trace_arm2", "trace_junction"):
        assert by_name[name]["width_mm"] == pytest.approx(p["series_w_mm"], abs=TOL)
    for name in ("trace_input", "trace_out1", "trace_out2"):
        assert by_name[name]["width_mm"] == pytest.approx(p["shunt_w_mm"], abs=TOL)
    adj = trace_attach_graph(spec["traces"])
    assert len(trace_connected_components(adj)) == 1  # T 结经横杆重叠连通
    assert [(pt["name"], pt["port_nr"], pt["trace"]) for pt in spec["ports"]] == [
        ("P1", 1, "trace_input"), ("P2", 2, "trace_out1"), ("P3", 3, "trace_out2"),
    ]
    ends = {pt["name"]: pt["point_mm"] for pt in spec["ports"]}
    assert ends["P1"] == [0.0, p["in_len_mm"]]
    assert ends["P2"] == [half_g, y_out]
    assert ends["P3"] == [-half_g, y_out]
    # 隔离电阻：100Ω、跨两臂端内侧壁、端点恰贴臂内缘（距臂中心线 W/2）
    (res,) = spec["resistors"]
    assert res["r_ohm"] == 100.0
    assert res["path_mm"] == [
        [-(half_g - p["series_w_mm"] / 2.0), y_end],
        [half_g - p["series_w_mm"] / 2.0, y_end],
    ]


def test_power_divider_resistor_not_in_config(pd):
    """安全钉（schema 假设 5）：电阻绝不以金属进 config modeler。"""
    _, config = pd
    trace_names = [t["name"] for t in config["modeler"]["traces"]]
    assert "RISO" not in trace_names and len(trace_names) == 6
    assert [pl["name"] for pl in config["modeler"]["planes"]] == ["GND_plane"]
    assert all("resistor" not in k for k in config)


# ─── board 覆盖 ───────────────────────────────────────────────────────────────


def test_board_covers_trace_footprints(bl, pd):
    for spec, _ in (bl, pd):
        x0, y0 = spec["board"]["lower_left_mm"]
        x1, y1 = spec["board"]["upper_right_mm"]
        for tr in spec["traces"]:
            w2 = tr["width_mm"] / 2.0
            for x, y in tr["path_mm"]:
                assert x0 - 1e-12 <= x - w2 and x + w2 <= x1 + 1e-12
                assert y0 - 1e-12 <= y - w2 and y + w2 <= y1 + 1e-12


# ─── config JSON 形态（PyEDB configuration.load() 兼容面）────────────────────


def test_config_json_shape(bl, pd):
    for spec, config in (bl, pd):
        layers = config["stackup"]["layers"]
        # config 自顶向下（spec 自底向上翻转——pyedb 0.83 __create_stackup
        # 逐层 AddLayerBottom 首项落物理顶层，2026-10-08 审查批 P0 修复）
        assert [la["name"] for la in layers] == ["TOP", "SUB", "GND"]
        assert [la["layer_type"] for la in layers] == ["signal", "dielectric", "signal"]
        assert layers[1]["thickness"].endswith("mm")
        assert abs(float(layers[1]["thickness"][:-2]) - 0.508) < 1e-9
        # 走线：坐标米（EDB 数据库单位）、宽度带单位字符串、flat/sharp
        for tr_cfg, tr_spec in zip(config["modeler"]["traces"], spec["traces"], strict=True):
            assert tr_cfg["name"] == tr_spec["name"] and tr_cfg["layer"] == "TOP"
            assert tr_cfg["path"] == [[x * 1e-3, y * 1e-3] for x, y in tr_spec["path_mm"]]
            assert abs(float(tr_cfg["width"][:-2]) - tr_spec["width_mm"]) < 1e-8
            assert tr_cfg["start_cap_style"] == "flat"
            assert tr_cfg["corner_style"] == "sharp"
        # 端口：wave_port 指向已存在走线、点=端点×1e-3
        for pt_cfg, pt_spec in zip(config["ports"], spec["ports"], strict=True):
            assert pt_cfg["type"] == "wave_port"
            assert pt_cfg["primitive_name"] == pt_spec["trace"]
            assert pt_cfg["point_on_edge"] == [pt_spec["point_mm"][0] * 1e-3,
                                               pt_spec["point_mm"][1] * 1e-3]
            assert pt_cfg["horizontal_extent_factor"] == 5
            assert pt_cfg["vertical_extent_factor"] == 3
        # setup：单频 f0 自适应 + [0.7, 1.3]·f0 401 点插值扫频（假设 8 口径）
        (setup,) = config["setups"]
        assert setup["type"] == "hfss" and setup["adapt_type"] == "single"
        f0 = spec["sim_setup"]["f0_ghz"]
        assert setup["single_frequency_adaptive_solution"]["adaptive_frequency"] == "2.4GHz"
        (sweep,) = setup["freq_sweep"]
        assert sweep["type"] == "interpolation"
        (fr,) = sweep["frequencies"]
        assert fr["start"] == "1.68GHz" and fr["stop"] == "3.12GHz"
        assert fr["increment"] == 401 and fr["distribution"] == "linear_count"
        assert 0.7 * f0 <= f0 <= 1.3 * f0
        assert config["boundaries"] == {"use_open_region": True,
                                        "open_region_type": "radiation"}


def test_emitters_are_pure_deterministic():
    """纯函数口径：同参两次发射 spec/config 逐键相等（无隐藏状态/随机）。"""
    a = emit_branchline_spec({"f0_ghz": F0})
    b = emit_branchline_spec({"f0_ghz": F0})
    assert a == b
    c = emit_power_divider_spec({"f0_ghz": F0})
    d = emit_power_divider_spec({"f0_ghz": F0})
    assert c == d
    # 深拷贝入参不被发射器改写（无入参突变副作用）
    params = {"f0_ghz": F0, "sweep": {"points": 201}}
    frozen = copy.deepcopy(params)
    emit_branchline_spec(params)
    assert params == frozen


def test_custom_sweep_and_structural_params_pass_through():
    spec, _ = emit_power_divider_spec({
        "f0_ghz": 5.8, "gap_mm": 6.5, "in_len_mm": 8.0, "out_len_mm": 4.0,
        "sweep": {"start_ghz": 4.0, "stop_ghz": 7.6, "points": 201},
    })
    assert spec["sim_setup"]["sweep"] == {
        "name": "sweep1", "type": "interpolation",
        "start_ghz": 4.0, "stop_ghz": 7.6, "points": 201,
    }
    assert spec["params"]["gap_mm"] == 6.5
    assert validate_spec(spec) == []
    # f0 不在频窗内必须被 validate 拦下（发射器自检会先抛 ValueError）
    with pytest.raises(ValueError, match="频窗"):
        emit_branchline_spec({"f0_ghz": 5.0, "sweep": {"start_ghz": 1.0, "stop_ghz": 2.0}})


def test_invalid_design_params_rejected():
    with pytest.raises(ValueError, match="f0_ghz"):
        emit_branchline_spec({"f0_ghz": -1.0})
    with pytest.raises(ValueError, match="50Ω"):
        emit_power_divider_spec({"f0_ghz": F0, "z0_ohm": 75.0})
    with pytest.raises(ValueError, match="gap"):
        emit_power_divider_spec({"f0_ghz": F0, "gap_mm": 0.0})


# ─── 波端口扩展守卫（rc=103 真机实证，W1 冒烟 REPORT §3.3/§4.5）──────────────
#
# 物理界：端口片宽 = horizontal_extent_factor × 线宽（P2/P3 片不交叠要求
# gap_mm ≥ 因子×shunt_w，缺省层叠 5×w≈5.57mm）；旧缺省 2.0mm 在 AEDT
# 网格生成报 "Port#Port2 intersects mesh body: Port#Port3"（rc=103）。


def _pd_shunt_w(f0: float) -> float:
    """50Ω 馈线宽独立重导（与发射器同综合单源，HJ 反解）。"""
    from rfauto.core.synthesis import Stackup, inverse_width

    st = Stackup(name="audit", **STACKUP_KW)
    w, _, status = inverse_width(50.0, f0, st)
    assert status == "ok"
    return float(w)


def test_power_divider_gap_guard_rejects_old_default_with_relax_hint():
    """gap=2.0（旧缺省=rc=103 真机实证值）→ ValueError 点名交叠+r=103
    + 建议放宽值 ≥ 因子×shunt_w（任务书"提示放宽值"口径）。"""
    w = _pd_shunt_w(F0)
    with pytest.raises(ValueError) as ei:
        emit_power_divider_spec({"f0_ghz": F0, "gap_mm": 2.0})
    msg = str(ei.value)
    assert "rc=103" in msg and "放宽" in msg
    m = re.search(r"gap_mm ≥ ([0-9.]+)mm", msg)
    assert m is not None and float(m.group(1)) >= 5.0 * w


def test_power_divider_gap_guard_boundary_exact_and_below():
    """恰等 5×shunt_w 与略低同样拦下（#347 家法：恰等会炸，留浮点余量）。"""
    w = _pd_shunt_w(F0)
    for gap in (5.0 * w, 5.0 * w * (1.0 - 1e-3)):
        with pytest.raises(ValueError, match="不足"):
            emit_power_divider_spec({"f0_ghz": F0, "gap_mm": gap})


def test_power_divider_gap_guard_passes_just_above_threshold():
    """略高于最小可行界即放行（守卫只拦端口片交叠形态，无隐性更高门槛），
    放行值原样进 spec params（透传语义）。"""
    w = _pd_shunt_w(F0)
    spec, _ = emit_power_divider_spec(
        {"f0_ghz": F0, "gap_mm": 5.0 * w * 1.001})
    assert spec["params"]["gap_mm"] == pytest.approx(5.0 * w * 1.001)
    assert validate_spec(spec) == []


def test_power_divider_default_gap_is_wave_port_buildable():
    """缺省 gap=6.0 过守卫且高于物理界（旧缺省 2.0 与扩展因子 5 冲突已
    落档为与 HFSS 插件口径的有意分叉，W1 冒烟实证可用值）。"""
    assert 5.0 * _pd_shunt_w(F0) < DEFAULT_GAP_MM
    spec, _ = emit_power_divider_spec({"f0_ghz": F0})
    assert spec["params"]["gap_mm"] == DEFAULT_GAP_MM


# ─── validate_spec 拒绝面（几何审计守卫真实可红）────────────────────────────


def test_validate_spec_rejects_incomplete_stackup(bl):
    spec, _ = bl
    broken = copy.deepcopy(spec)
    broken["stackup"]["layers"] = broken["stackup"]["layers"][:1]
    errors = validate_spec(broken)
    assert any("层" in e for e in errors)


def test_validate_spec_rejects_port_off_endpoint(bl):
    spec, _ = bl
    broken = copy.deepcopy(spec)
    broken["ports"][0]["point_mm"][1] += 0.1
    errors = validate_spec(broken)
    assert any("端点" in e for e in errors)


def test_validate_spec_rejects_disconnected_trace(bl):
    spec, _ = bl
    broken = copy.deepcopy(spec)
    left = next(t for t in broken["traces"] if t["name"] == "arm_left")
    left["path_mm"] = [[50.0, 50.0], [50.0, 60.0]]
    errors = validate_spec(broken)
    assert any("连通" in e for e in errors)  # 连通分量 + board 覆盖双红
    assert any("board" in e for e in errors)


def test_validate_spec_rejects_detached_resistor(pd):
    spec, _ = pd
    broken = copy.deepcopy(spec)
    broken["resistors"][0]["path_mm"] = [[30.0, 30.0], [31.0, 30.0]]
    errors = validate_spec(broken)
    assert any("RISO" in e and "附着" in e for e in errors)


# ─── PyEDB configuration 形态回溯（可选：装了 pyedb 才跑）────────────────────


def test_config_json_parses_through_pyedb_cfgdata(bl, pd):
    """config dict 过 pyedb CfgData 离线解析（零 EDB 会话）：段合法零警告。"""
    pytest.importorskip("pyedb")
    from pyedb.configuration.cfg_data import CfgData

    for spec, config in (bl, pd):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            data = CfgData(pedb=None, **config)
        unknown = [str(w.message) for w in caught
                   if "Unknown configuration section" in str(w.message)]
        assert unknown == []
        n_traces = len(spec["traces"])
        assert len(data.modeler.traces) == n_traces
        assert len(data.modeler.planes) == 1
        assert len(data.ports.ports) == len(spec["ports"])
        (setup,) = data.setups.setups
        assert type(setup).__name__ == "CfgHFSSSetup"
        assert setup.single_frequency_adaptive_solution.adaptive_frequency == "2.4GHz"
        (sweep,) = setup.freq_sweep
        assert sweep.frequencies[0].increment == 401
        assert sweep.frequencies[0].distribution == "linear_count"
