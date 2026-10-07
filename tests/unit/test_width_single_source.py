"""XC-W 50Ω 宽常数单源化一致性测试（2026-10-02，月度宏图 §10.1 弱点 6）。

单源（唯一计算点）= core/synthesis.nominal_width_mm（materials.yaml 层叠系）
与 core/synthesis.lossless_width_mm（无耗裸层叠系），均为 inverse_width(50)
回代自洽档。本测试钉三件事：

1. 权威值本身（各 (f, εr, h, tanδ) 参数系的标称档逐位=历史字面量）；
2. 同参系消费者逐位同值（普查清单每消费者一对断言：registry 归档/
   docs meta/各渲染文件 *_NOMINAL 字面量落表/模块常数）；
3. src 全树字面量普查守卫（AST 级：目标字面量只允许出现在本测试声明的
   归档位，位置与个数精确匹配——新增散落字面量即红）。

两系并存是**参数系不同**非同参漂移：1.1134/1.1133/1.113 走 yaml 层叠
（tanδ=0.0037），1.1117（@2.5GHz）/1.112（@5.8GHz）走无耗裸层叠（tanδ=0，
hairpin/c3/c4/阵列 KJ-HJ 闭式链 tanδ 不进正向）——HJ Z0 随介质损耗弱变，
各系在自己层叠定义下回代均自洽 50Ω。
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
_DOCS_TPL = Path(__file__).resolve().parents[2] / "docs" / "templates"
_SUB50 = "rogers4350b_h0.508"

# 目标字面量集合（50Ω 微带宽标称档；AST float 精确匹配）
_TARGET_WIDTHS = {1.1134, 1.1133, 1.113, 1.112, 1.1117}


# ─── 1. 权威值本身 ────────────────────────────────────────────────────────────

def test_yaml_family_canonical_values():
    """yaml 层叠系（rogers4350b_h0.508，tanδ=0.0037）标称档逐位钉。"""
    from rfauto.core.synthesis import nominal_width_mm

    w25 = nominal_width_mm(50.0, 2.5, _SUB50)
    w24 = nominal_width_mm(50.0, 2.4, _SUB50)
    # 逐位=历史字面量（round 为 IEEE754 就近舍入，repr 同串→渲染字节零漂移）
    assert w25 == 1.1134
    assert w24 == 1.1133
    assert repr(w25) == repr(1.1134)
    # round3 档：@2.4/@2.5 跨频逐位同值（同落 1.113 就近双精度）——
    # 这是 wilkinson(2.4)/mline(2.5) 可共用一个档的数值根据
    r3_25 = nominal_width_mm(50.0, 2.5, _SUB50, digits=3)
    r3_24 = nominal_width_mm(50.0, 2.4, _SUB50, digits=3)
    assert r3_25 == r3_24 == 1.113
    # 回代自洽：标称档宽度在对应频点正向回代仍 50Ω（|Δ|≤0.05Ω，4 位舍入量级）
    from rfauto.core.synthesis import Stackup, forward_z0
    st = Stackup.from_materials_yaml(_SUB50)
    assert abs(forward_z0(w25, 2.5, st).z0 - 50.0) < 0.05
    assert abs(forward_z0(w24, 2.4, st).z0 - 50.0) < 0.05


def test_lossless_family_canonical_values():
    """无耗裸层叠系（tanδ=0，εr3.66 h0.508）标称档逐位钉。"""
    from rfauto.core.synthesis import Stackup, forward_z0, lossless_width_mm

    w_hairpin = lossless_width_mm(50.0, 2.5)
    w_array = lossless_width_mm(50.0, 5.8)
    assert w_hairpin == 1.1117
    assert w_array == 1.112
    # 与重构前 hairpin 链的旧公式逐位同值（同参同函数，仅加缓存）——
    # hairpin 设计链（gap/τ 反解以原值 w 继续）零漂移的根据
    from rfauto.core.synthesis import inverse_width
    st = Stackup(name="hairpin", epsilon_r=3.66, thickness_mm=0.508)
    w_old = float(inverse_width(50.0, 2.5, st)[0])
    assert lossless_width_mm(50.0, 2.5, digits=None) == w_old
    # 回代自洽（无耗层叠定义下恰 50Ω；yaml 档字面量在无耗系下 49.95Ω——
    # 两系各自自洽，历史注释"旧 1.1134 Z0=49.95Ω"即无耗系观察）
    assert abs(forward_z0(w_hairpin, 2.5, st).z0 - 50.0) < 0.05


def test_wilkinson_synthesis_shunt_uses_same_r3_tier():
    """synthesize_wilkinson 的 shunt_w（@2.4GHz）与 round3 单源档逐位同值。"""
    from rfauto.core.synthesis import nominal_width_mm, synthesize_wilkinson

    res = synthesize_wilkinson(f0_ghz=2.4)
    assert res.params["shunt_w_mm"] == nominal_width_mm(
        50.0, 2.4, _SUB50, digits=3) == 1.113


# ─── 2. 同参系消费者逐位同值（普查清单逐条钉）────────────────────────────────

def _registry():
    from rfauto.adapters.oe_templates.registry import TEMPLATE_NOMINAL
    return TEMPLATE_NOMINAL


def _w50():
    from rfauto.adapters.oe_templates import _nominal_width
    return _nominal_width.W50_MM


def _w50_r3():
    from rfauto.adapters.oe_templates import _nominal_width
    return _nominal_width.W50_MM_R3


def test_registry_nominal_yaml_family_pins():
    """registry.TEMPLATE_NOMINAL 归档值 vs 单源（yaml 系）逐位同值。"""
    tn = _registry()
    w = _w50()
    # 1.1134 档（round4 @2.5GHz）：八模板馈线缺省档
    for tpl, key in [("wstep", "w1_mm"), ("tjunc", "w_feed_mm"),
                     ("bend", "w_mm"), ("via", "w_mm"),
                     ("atten_pi", "w_mm"), ("atten_t", "w_mm"),
                     ("ratrace", "w_feed_mm"), ("gysel", "w_feed_mm")]:
        assert tn[tpl][key] == w, f"{tpl}.{key}"
    # 1.1133 档（round4 @2.4GHz）：stepped 馈线（f0=2.4）
    from rfauto.core.synthesis import nominal_width_mm
    assert tn["stepped_impedance"]["feed_w_mm"] == nominal_width_mm(
        50.0, 2.4, _SUB50) == 1.1133
    # 1.113 档（round3）：wilkinson 馈线 / mline
    assert tn["wilkinson"]["shunt_w_mm"] == _w50_r3()
    assert tn["mline"]["w_mm"] == _w50_r3()


def test_docs_meta_nominal_yaml_family_pins():
    """docs/templates/*/meta.yaml 归档 nominal vs 单源逐位同值（只读钉）。"""
    import yaml

    w = _w50()
    r3 = _w50_r3()
    # (模板, 键, 期望值)——yaml 层叠系归档位
    pins = [
        ("mline", "w_mm", r3), ("wilkinson", "shunt_w_mm", r3),
        ("wstep", "w1_mm", w), ("tjunc", "w_feed_mm", w),
        ("bend", "w_mm", w), ("via", "w_mm", w),
        ("atten_pi", "w_mm", w), ("atten_t", "w_mm", w),
        ("ratrace", "w_feed_mm", w), ("gysel", "w_feed_mm", w),
        ("stepped_impedance", "feed_w_mm", 1.1133),
        ("ring_resonator", "w_mm", w), ("ring_resonator", "feed_w_mm", w),
        ("slot", "feed_w_mm", w), ("sma_launcher", "w_msl_mm", w),
        ("schiffman", "w_ref_mm", w), ("qwt_multisection", "feed_w_mm", w),
    ]
    for tpl, key, want in pins:
        meta_path = _DOCS_TPL / tpl / "meta.yaml"
        data = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
        got = data["nominal_params"][key]
        assert got == want, f"docs {tpl}.{key}: {got!r} != {want!r}"


def test_docs_meta_lossless_family_pins():
    """docs 阵列归档（无耗系 @5.8GHz）vs 单源逐位同值。"""
    import yaml

    from rfauto.core.synthesis import lossless_width_mm
    w58 = lossless_width_mm(50.0, 5.8)
    assert w58 == 1.112
    for tpl in ("patch_eep_2x2", "patch_eep_1x4"):
        data = yaml.safe_load(
            (_DOCS_TPL / tpl / "meta.yaml").read_text(encoding="utf-8"))
        assert data["nominal_params"]["feed_w_mm"] == w58, tpl


def test_render_archived_nominals_yaml_family_pins():
    """渲染层「字面量落表」归档 vs 单源逐位同值（yaml 系）。"""
    w = _w50()
    # render_ring：模块常数 + 名义表（「字面量落表避免模块导入期 IO」惯例）
    from rfauto.adapters.oe_templates.render_ring import (
        RING_RESONATOR_NOMINAL,
        RING_RESONATOR_W_MM,
    )
    assert w == RING_RESONATOR_W_MM
    assert RING_RESONATOR_NOMINAL["w_mm"] == w
    assert RING_RESONATOR_NOMINAL["feed_w_mm"] == w
    # render_msl_sma：50Ω 微带常数（msl_cpw nominal 引用）
    from rfauto.adapters.oe_templates.render_msl_sma import (
        _MSL_CPW_50OHM_W_MM,
    )
    assert w == _MSL_CPW_50OHM_W_MM
    # render_phase_qwt：qwt 名义表馈线档
    from rfauto.adapters.oe_templates.render_phase_qwt import (
        QWT_MULTISECTION_NOMINAL,
    )
    assert QWT_MULTISECTION_NOMINAL["feed_w_mm"] == w
    # core/coupled_microstrip：KJ 闭式缺省宽常数（yaml 档；注意其缺省消费的
    # KJ 正向是无耗闭式——跨档缺省的现状如实钉住，收敛见普查报告 followUp）
    from rfauto.core.coupled_microstrip import HAIRPIN_50OHM_W_MM
    assert w == HAIRPIN_50OHM_W_MM
    # 渲染缺省面单源引用本体（XC-W 收敛点）：惰性常量=权威函数值
    from rfauto.core.synthesis import nominal_width_mm
    assert w == nominal_width_mm(50.0, 2.5, _SUB50)


def test_render_and_core_nominals_lossless_family_pins():
    """hairpin/c3/c4/combline/varactor 归档 vs 无耗单源逐位同值。"""
    from rfauto.core.synthesis import lossless_width_mm

    w = lossless_width_mm(50.0, 2.5)
    assert w == 1.1117
    from rfauto.adapters.oe_templates.render_hairpin import (
        HAIRPIN_ALT_NOMINAL,
        HAIRPIN_NOMINAL,
    )
    assert HAIRPIN_NOMINAL["w_mm"] == w
    assert HAIRPIN_ALT_NOMINAL["w_mm"] == w
    from rfauto.adapters.oe_templates.render_coupled_bpf import (
        COUPLED_BPF_NOMINAL,
    )
    assert COUPLED_BPF_NOMINAL["w_feed_mm"] == w
    from rfauto.adapters.oe_templates.render_c4 import (
        BRANCHLINE_2SECT_NOMINAL,
        CLINE_COUPLER_NOMINAL,
        LANGE_NOMINAL,
    )
    assert CLINE_COUPLER_NOMINAL["w_feed_mm"] == w
    assert BRANCHLINE_2SECT_NOMINAL["w_feed_mm"] == w
    assert BRANCHLINE_2SECT_NOMINAL["w_main_mm"] == w
    assert LANGE_NOMINAL["w_feed_mm"] == w
    from rfauto.adapters.oe_templates.render_c3 import (
        COMBLINE_NOMINAL,
        INTERDIGITAL_NOMINAL,
    )
    assert INTERDIGITAL_NOMINAL["w_mm"] == w
    assert COMBLINE_NOMINAL["w_mm"] == w
    from rfauto.adapters.oe_templates.render_varactor import (
        VARACTOR_BPF_NOMINAL,
    )
    assert VARACTOR_BPF_NOMINAL["w_mm"] == w
    # kgap 标定口径几何（core/coupled_microstrip）
    from rfauto.core.coupled_microstrip import HAIRPIN_KGAP_CALIB
    assert HAIRPIN_KGAP_CALIB["w_mm"] == w


def test_array_chain_lossless_family_pins():
    """C2 阵列链（无耗 @5.8GHz）：ARRAY/EEP_NOMINAL 馈线档 vs 单源逐位同值。"""
    from rfauto.adapters.oe_templates.closedform import array_line_w_mm
    from rfauto.adapters.oe_templates.render_array_eep import (
        ARRAY_NOMINAL,
        EEP_NOMINAL,
    )
    from rfauto.core.synthesis import lossless_width_mm

    w58 = lossless_width_mm(50.0, 5.8)
    # 链身份：closedform.array_line_w_mm 委托同一缓存底座（原值恒等）
    assert array_line_w_mm(50.0, 5.8) == lossless_width_mm(
        50.0, 5.8, digits=None)
    for tpl, nom in [*ARRAY_NOMINAL.items(), *EEP_NOMINAL.items()]:
        assert nom["feed_w_mm"] == w58, tpl


def test_service_and_schema_fallback_pins():
    """出界面（service/schema/适配器）1.113 档消费者 vs round3 单源逐位同值。"""
    from rfauto.service.remote_service import L2_W_MM
    assert _w50_r3() == L2_W_MM


# ─── 3. src 全树字面量普查守卫（AST 级）───────────────────────────────────────

#: 允许保留目标字面量的归档位（文件相对 src/ → {值: 允许出现次数}）。
#: 渲染缺省面已收敛 `_nominal_width` 引用（本表不再含这些文件=禁再回添）；
#: 表内=归档字面量/出界面缺省（语义出处见各处注释与 runs/xcw 普查清单）。
_ALLOWED_CENSUS: dict[str, dict[float, int]] = {
    # ge8b EP-5 教学卡数字串（teaching 卡 w_mm=1.113=nominal_width_mm(50,2.5,digits=3)
    # 同值；出处内容非几何消费面，归档登记——XC-W 守卫与 EP-5 交叉）：
    "rfauto/service/teaching_service.py": {1.113: 1},
    # ge8d 席D2 xcheb_bpf4 NOMINAL 登记值（w=1.1117 hairpin 无耗档归档字面）：
    "rfauto/adapters/oe_templates/render_ta_wave_c.py": {1.1117: 1},  # NOMINAL 登记值（表达式位已单源化）
    # 归档字面量（字面量落表惯例，一致性钉在上方各 test）
    "rfauto/adapters/oe_templates/registry.py": {
        1.113: 2, 1.1133: 1, 1.1134: 8},
    "rfauto/adapters/oe_templates/render_antenna2.py": {1.1134: 1},
    # TA-3/4 NOMINAL 归档字面量（render_phase_qwt SCHIFFMAN_NOMINAL 同例，
    # 逐位测试钉在 test_sicl_nway_templates）
    "rfauto/adapters/oe_templates/render_sicl_nway.py": {1.1134: 1},
    "rfauto/adapters/oe_templates/render_array_eep.py": {1.112: 5},
    "rfauto/adapters/oe_templates/render_c3.py": {1.1117: 3},
    "rfauto/adapters/oe_templates/render_c4.py": {1.1117: 4},
    "rfauto/adapters/oe_templates/render_coupled_bpf.py": {1.1117: 1},
    "rfauto/adapters/oe_templates/render_hairpin.py": {1.1117: 2},
    "rfauto/adapters/oe_templates/render_msl_sma.py": {1.1134: 1},
    "rfauto/adapters/oe_templates/render_phase_qwt.py": {1.1134: 2},
    "rfauto/adapters/oe_templates/render_ring.py": {1.1134: 3},
    "rfauto/adapters/oe_templates/render_varactor.py": {1.1117: 1},
    # 出界面（本批文件面外；收敛 followUp 见普查报告）
    "rfauto/adapters/comsol_adapter.py": {1.113: 1},
    "rfauto/adapters/fake_adapter.py": {1.113: 1, 1.1134: 6},
    "rfauto/adapters/meep_adapter.py": {1.113: 1},
    "rfauto/adapters/qucsator_adapter.py": {1.113: 1},
    "rfauto/core/coupled_microstrip.py": {1.1134: 1, 1.1117: 1},
    # LC-2 扩面（2026-10-02）：+4×1.113=新单元毫米口径缺省（ms_bend/
    # rf_taper w1/rf_miter_bend w/rf_round_bend w，Layout 桥演示面归档，
    # 非 50Ω 综合锚）；mline 原档 1.113 与 wstep 1.1134 不变
    "rfauto/core/pcell_dsl.py": {1.113: 5, 1.1134: 1},
    "rfauto/models/mline/schema.py": {1.113: 1},
    "rfauto/service/qucsator_service.py": {1.113: 1},
    "rfauto/service/remote_service.py": {1.113: 1},
}


def _src_width_literal_census() -> dict[str, Counter]:
    """src 全树目标字面量普查（AST float Constant 精确匹配，注释/docstring 不算）。"""
    census: dict[str, Counter] = {}
    for p in sorted(_SRC.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        hits = Counter(
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, float)
            and n.value in _TARGET_WIDTHS)
        if hits:
            census[p.relative_to(_SRC).as_posix()] = hits
    return census


def test_src_width_literal_census_guard():
    """普查守卫：src 目标字面量必须精确落在声明的归档位（文件×值×个数）。

    新增散落字面量（哪怕逐位同值）即红——50Ω 宽一律走
    core/synthesis.nominal_width_mm / lossless_width_mm 或 oe_templates
    ._nominal_width（渲染层惰性引用）；确需新增归档字面量须同笔更新本表。
    """
    census = _src_width_literal_census()
    declared = {f: Counter(v) for f, v in _ALLOWED_CENSUS.items()}
    assert census == declared, (
        "50Ω 宽字面量普查漂移："
        f"多出={ {f: dict(c - declared.get(f, Counter())) for f, c in census.items()} }；"
        f"缺失={ {f: dict(declared[f] - census.get(f, Counter())) for f in declared} }")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
