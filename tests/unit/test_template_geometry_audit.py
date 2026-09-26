"""§10.20 补强④：全部模板离线几何审计 + meta↔渲染一致性（#212 泛化）。

背景（#212）：字符串存在性 + compile() 抓不住画法错误——ratrace 径向馈
"中心线弦"盒厚=设计 1/13 且不导通、三端口全死，却通过了全部字符串门。
制度化手法：render_script → exec 几何段（FDTD.Run 之前）→ CSXCAD 实测
原语/网格/端口，秒级零仿真。本文件把该手法泛化到 TEMPLATE_META 全条目。

覆盖数 = TEMPLATE_META 条目数（EXPECTED_TEMPLATES 冻结集合 + 参数化 +
覆盖断言钉死；TEMPLATE_META/meta.yaml/TEMPLATE_NOMINAL 任一缺项即红）。

判据（全部量在 CSXCAD 实测对象上，非字符串）：
① 金属/介质原语非零体积且坐落在网格上（零厚度面必须恰在网格线）；
② 端口面贴板边（MSLPort 族）或内部集总端口激励体积非零；
③ 关键连通性：分组内端口共享同一导体连通分量，分组间不短路；
④ 域/基板尺寸与 meta 声明一致；
⑤ 无 nm 级近重合网格线（#152 守卫）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import (
    _DEFAULT_SUB,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    geometry_spec,
    sma_launcher_layout,
)
from tests.unit import _geometry_audit_helpers as gh

# 冻结的模板清单（#212：覆盖数即验收门，缺一即失败）。新增模板必须同步
# 更新此处与 docs/templates/<t>/meta.yaml，否则覆盖断言红。
# 2026-09-14：coupled_bpf（WP2.3 BPF 族锚）+ C1 天线族 II 六模板
# （monopole/pifa/ifa/loop/helix/slot）由附加模板升格正式注册（18→25）。
# 2026-09-15 c3-filter-family-ii：§C3 滤波器族 II 三模板（interdigital/
# combline/sir_bpf）正式注册（25→28）。
# 2026-09-15 c9-tline-family-ii：C9 传输线族 II 两模板（cps 共面带 LumpedPort
# 差分直馈 / suspended_stripline 悬置带线 StripLinePort）正式注册（28→30）。
# 2026-09-15 c2-array-templates：§10.3 C2 阵列族三模板（patch_array_1x4 corporate /
# patch_array_2x2 H-tree / patch_array_series 1×3 串馈，f0=5.8GHz）正式注册（30→33）。
# 2026-09-16 c4-coupler-family-ii：§C4 耦合器族 II 三模板（cline_coupler 耦合线
# 定向耦合器 / branchline_2sect 两节分支线 / lange 展开型 Lange 电桥，四端口
# excite_port 轮转）正式注册（33→36；多轨同日合流，计数以合流实测为准）。
# 2026-09-16 wp25-sma-launcher-rootcause：WP2.5 Tier 2 过渡族两模板（msl_cpw
# MSL↔CPWG 过渡 / sma_launcher SMA edge-launch 夹具口径，真机 FAIL 根治）正式
# 注册（36→38；多轨同日合流，计数以合流实测为准）。
# 2026-09-18：槽线族四模板（slotline 路线 A WaveguidePort 文件
# 模式 / slotline_lumped 路线 B LumpedPort 跨槽 / msl_slot_transition Roberts-
# Knorr 过渡 / marchand_balun 双槽臂最小族——单支节设计已证伪、保留作对照口径）
# 由附加模块升格正式注册（38→42；整脚本渲染器，分发见 openems_templates 文末
# SLOTLINE_FAMILY 段）。
# 2026-09-18：hairpin_alt 交替取向发夹线（根修：奇数序
# 谐振器翻转使相邻臂开路端交替、电/磁耦合同号叠加；纯 KJ gap→k 口径）正式注册
# （42→43；注册在 hairpin 之后、coupled_bpf 之前，槽线族仍居尾 #247）。
# 2026-09-22 siw-family：SIW 族首族=直 SIW 传输线段（LumpedPort z 桥×2、矩形域
# DOM_X/DOM_Y 字面注入、f0=10GHz 设计点）正式注册（43→44；注册在文末 SIW 段，
# 尾部追加 #247）。
# 2026-09-24 df6-a2siwmsl：SIW 族第二成员=MSL 锥形过渡+SIW 直段（双 MSLPort
# 线基、Deslandes-Wu 两段论、矩形域 DOM_X/DOM_Y 字面注入、f0=10GHz 设计点）
# 正式注册（44→45；注册在文末 MSL_SIW_TAPER 段，槽线族仍居尾 #247）。
# 2026-09-24 df6-dp4p3：§DP-4 P3 EEP 阵列族两模板（patch_eep_2x2/patch_eep_1x4，
# 每元独立 LumpedPort 探针 1..4、无馈树、元间 DC 隔离=EEP 定义性质）正式注册
# （49→51；注册在文末 EEP 段，C2 阵列族同款闭式设计链复用）。
# 2026-09-26 df7-c10b：§COIL_NFC NFC/WPC 线圈族首模板 coil_nfc（13.56MHz 单端口
# 方螺旋、FR4 类基板、中跳线桥、外圈馈隙 LumpedPort）正式注册（51→52；注册在
# 文末 COIL_NFC 段，槽线/EEP 同款整脚本渲染器早分发）。
# 2026-09-26 df7-c10d：§MMWAVE_SERIES_ARRAY 串馈毫米波阵模板 mmwave_series_array
# （78GHz 行波串馈 1×N、链末匹配集总负载到地、RO3003 类毫米波板、相位递推闭式
# core/array_synthesis.series_feed_*）正式注册（52→53；注册在文末
# MMWAVE_SERIES_ARRAY 段，coil_nfc 同款整脚本渲染器早分发）。
EXPECTED_TEMPLATES = frozenset({
    "wilkinson", "patch", "branchline", "dipole", "stepped_impedance",
    "coupled_line", "mline", "cpw", "stripline", "wstep", "tjunc", "bend",
    "via", "atten_pi", "atten_t", "ratrace", "gysel", "hairpin",
    "hairpin_alt",
    "coupled_bpf",
    "monopole", "pifa", "ifa", "loop", "helix", "slot",
    "interdigital", "combline", "sir_bpf",
    "cps", "suspended_stripline",
    "patch_array_1x4", "patch_array_2x2", "patch_array_series",
    "cline_coupler", "branchline_2sect", "lange",
    "msl_cpw", "sma_launcher",
    "slotline", "slotline_lumped", "msl_slot_transition", "marchand_balun",
    "siw", "msl_siw_taper",
    # §MS_METASURFACE 超表面/FSS 族（2026-09-24 df6 DP-10，文末注册块）
    "ms_patch", "ms_cross", "ms_jcross", "ms_array_NxN",
    # §DP-4 P3 EEP 阵列族（2026-09-24 df6，文末注册块）
    "patch_eep_2x2", "patch_eep_1x4",
    # §COIL_NFC NFC/WPC 线圈族（2026-09-26 df7 C10b，文末注册块；
    # 单端口馈隙 LumpedPort，整脚本渲染器早分发）
    "coil_nfc",
    # §MMWAVE_SERIES_ARRAY 串馈毫米波阵（2026-09-26 df7 C10d，文末注册块；
    # 单端口 MSLPort + 链末匹配集总负载，整脚本渲染器早分发）
    "mmwave_series_array",
})

# 渲染脚本实际创建的端口对象数与 meta n_ports 的差异（历史口径）：
# branchline 的 port4 曾是隔离端 PML 端接（无 MSLPort 对象，渲染 3 端口）；
# 2026-09-16 四端口升级后 port4 为真 MSLPort，渲染端口数=meta n_ports=4——
# 此处显式钉 4 作回退绊线（退回 PML 端接即红）。
RENDER_PORT_COUNT: dict[str, int] = {"branchline": 4}

_AXES = ("x", "y", "z")


# ─── 覆盖锁定 ────────────────────────────────────────────────────────────────

def test_template_coverage_locked():
    """TEMPLATE_META / TEMPLATE_NOMINAL / docs meta.yaml 三处条目集完全一致。"""
    assert len(EXPECTED_TEMPLATES) == 53, "覆盖基线漂移：台账记 53 个模板"
    assert frozenset(TEMPLATE_META) == EXPECTED_TEMPLATES
    assert frozenset(TEMPLATE_NOMINAL) == EXPECTED_TEMPLATES
    yaml_names = {
        p.parent.name for p in (REPO / "docs" / "templates").glob("*/meta.yaml")
    }
    assert yaml_names == EXPECTED_TEMPLATES


def _meta_yaml(template: str) -> dict:
    import yaml

    path = REPO / "docs" / "templates" / template / "meta.yaml"
    assert path.exists(), path
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ─── ① 原语非零体积 + 进网格 ─────────────────────────────────────────────────

@pytest.mark.parametrize("template", sorted(EXPECTED_TEMPLATES))
def test_primitives_nonzero_and_entered_in_mesh(template):
    scope, prims = gh.load_geometry(template)
    metal = [p for p in prims if p.kind == "Metal"]
    dielectric = [p for p in prims if p.kind == "Material"]
    conductors = [p for p in prims if gh.is_conductor(p)]
    assert metal, f"{template}: 无金属原语"
    if template not in gh.NO_SUBSTRATE_TEMPLATES:  # dipole/monopole/helix 无基板
        assert dielectric, f"{template}: 无介质原语"

    # 非零体积：金属板任意取向面内面积 >0（水平面 z 零厚 / 竖直板 x 或 y 零厚
    # 均为既定口径——monopole 竖直细带、helix 角部竖板、pifa/ifa 短路板）；
    # 退化成线（仅一轴非零）即红；柱半径>0 且轴长>0
    for p in metal:
        ext = p.extent
        if p.radius is not None:
            assert p.radius > 0 and ext[2] > 0, f"{template}: 零体积柱 {p.prop}"
        else:
            assert int(np.sum(ext > 1e-12)) >= 2, \
                f"{template}: 零面积金属盒 {p.prop} ext={ext}"
    for p in dielectric:
        assert bool(np.all(p.extent > 1e-12)), f"{template}: 零体积介质 {p.prop}"

    # 进网格：零厚度面恰在网格线上；有厚度轴内至少落在一条网格线上
    # （SUBCELL_CYLINDER_PROPS：亚 cell 柱体只查轴向——msl_cpw 过孔栅栏 via 基元口径）
    assert gh.off_mesh_planes(prims, scope) == [], "原语零厚度面未落在网格线上"
    lines = {ax: gh.mesh_lines(scope, ax) for ax in _AXES}
    subcell = gh.SUBCELL_CYLINDER_PROPS.get(template, frozenset())
    for p in conductors:
        ext = p.extent
        axial_only = p.prop in subcell and p.radius is not None
        axial = int(np.argmax(ext)) if axial_only else -1
        for index, axis in enumerate(_AXES):
            if axial_only and index != axial:
                continue
            if ext[index] > 1e-12:
                inside = lines[axis][
                    (lines[axis] >= p.lo[index] - 1e-9)
                    & (lines[axis] <= p.hi[index] + 1e-9)
                ]
                assert len(inside) >= 1, f"{template}: {p.prop} 在 {axis} 轴未进网格"


# ─── ② 端口面贴边 + 尺寸非零 ─────────────────────────────────────────────────

@pytest.mark.parametrize("template", sorted(EXPECTED_TEMPLATES))
def test_ports_on_boundary_and_nonzero(template):
    scope, prims = gh.load_geometry(template)
    ports = gh.port_objects(scope)
    if template in gh.PORTLESS_TEMPLATES:
        # §MS_METASURFACE 阵（df6 DP-10）：无端口软平面照明散射体——改查
        # 软激励平面 + nf2ff 盒存在（官方 PPW 教程口径，正面判据非豁免）
        assert not ports, f"{template}: 无端口模板不应有端口对象"
        exc_names = [k for k in scope
                     if k.startswith("_exc") or k == "_excitation"]
        assert exc_names, f"{template}: 无软激励平面（exc_type=0 照明缺失）"
        assert "_FF" in scope, f"{template}: 无 nf2ff 盒（J2 判读面缺失）"
        assert TEMPLATE_META[template]["n_ports"] == 0
        return
    assert ports, f"{template}: 渲染脚本无端口对象"
    expected = RENDER_PORT_COUNT.get(template, TEMPLATE_META[template]["n_ports"])
    assert len(ports) == expected, f"{template}: 端口对象数 {len(ports)} != {expected}"

    dom_x, dom_y = gh.domain_half_extents(scope)
    board = float(scope.get("BOARD", max(dom_x, dom_y)))
    z_lines = gh.mesh_lines(scope, "z")
    for number, port in ports.items():
        start = np.asarray(port.start, dtype=float)
        stop = np.asarray(port.stop, dtype=float)
        ext = np.abs(start - stop)
        if hasattr(port, "prop_ny"):
            axis = int(port.prop_ny)
            if template in gh.INSET_PORT_TEMPLATES:
                # 面内缩 MSL 端口（H4：段⊂PML_8 致非物理，槽线过渡/巴伦有意内移
                # 14·BASE）：端口面严格在域内 + 含馈电点的金属原语沿端口轴延伸到
                # 域边界（馈线到板边=无开路 stub，#174）
                face = float(start[axis])
                dom = dom_y if axis == 1 else dom_x
                assert abs(face) < dom - 1e-9, \
                    f"{template} port{number}: 内缩端口面越界（{face}）"
                feed = gh.port_feed_point(port)
                host = [p for p in prims if gh.is_conductor(p)
                        and bool(np.all(feed >= p.lo - 1e-9))
                        and bool(np.all(feed <= p.hi + 1e-9))]
                assert host, f"{template} port{number}: 馈电点不在任何导体上"
                reach = any(
                    (p.lo[axis] <= -dom + 1e-9) or (p.hi[axis] >= dom - 1e-9)
                    for p in host)
                assert reach, \
                    f"{template} port{number}: 馈线未延伸到域边界（开路 stub 嫌疑 #174）"
            elif template in gh.EDGE_PORT_TEMPLATES:
                # 域边贴界 MSL 端口（msl_siw_taper：矩形域 DOM_Y 字面≠BOARD，
                # 端口面=域边界=PML 面，mline 口径的矩形域变体，#174）
                dom = dom_y if axis == 1 else dom_x
                assert abs(abs(float(start[axis])) - dom) <= 1e-9, \
                    f"{template} port{number}: 端口面未贴域边界（{start[axis]}）"
            else:
                # 端口面贴板边 = PML 边界（馈线止于域中即开路 stub，#174）
                assert abs(abs(start[axis]) - board) <= 1e-9, \
                    f"{template} port{number}: 端口面未贴板边（{start[axis]}）"
            assert int(np.sum(ext > 1e-9)) >= 2, f"port{number}: 端口面退化 {ext}"
            # 金属面 z 精确入网（否则激励体积坍缩）
            assert float(np.min(np.abs(z_lines - start[2]))) <= 1e-6, \
                f"port{number}: 端口金属面 z 未入网"
        else:
            # 内部集总端口（patch 底馈探针 / dipole 中央 gap）：官方口径不贴边界，
            # 检查激励方向体积非零；槽线族路线 A 的 WaveguidePort 为截面场激励
            # （exc_ny 轴向长度=测量面距，>0 即有效截面端口）
            axis = int(getattr(port, "exc_ny", 0))
            assert ext[axis] > 1e-9, f"port{number}: 集总端口激励体积为零"


# ─── ③ 信号连通性 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("template", sorted(EXPECTED_TEMPLATES))
def test_signal_connectivity(template):
    scope, prims = gh.load_geometry(template)
    conductors, labels = gh.conductor_labels(prims)
    ports = gh.port_objects(scope)
    if template in gh.PORTLESS_TEMPLATES:
        # §MS_METASURFACE 阵（df6 DP-10）：无端口连通性——改查金属分量
        # （逐胞贴片 DC 隔离分量；地连续=脚本 BC token，由
        # test_metasurface_templates 正面断言）
        metal_prims = [p for p in conductors if p.kind == "Metal"]
        assert metal_prims, f"{template}: 无金属原语"
        assert len(labels) >= 1
        return
    if template in gh.SHEET_PORT_TEMPLATES:
        # §MS_METASURFACE 单元（df6 DP-10）：波导模拟器 TEM 片端口浮于空气区
        # （容性馈）——判据改：①片端口 LumpedElement 与金属原语无 bbox 接触
        # （DC 短路即红）；②模板有独立金属网络（屏/贴片）；
        # ③端口片激励体积非零（exc 向 span>0）
        metal_prims = [p for p in conductors if p.kind == "Metal"]
        assert metal_prims, f"{template}: 无屏/贴片金属"
        for number, port in ports.items():
            lo = np.minimum(np.asarray(port.start, dtype=float),
                            np.asarray(port.stop, dtype=float))
            hi = np.maximum(np.asarray(port.start, dtype=float),
                            np.asarray(port.stop, dtype=float))
            for p in metal_prims:
                overlap = np.minimum(hi, p.hi) - np.maximum(lo, p.lo)
                assert not bool(np.all(overlap >= -1e-9)), \
                    f"{template} port{number}: 片端口与金属 {p.prop} 接触" \
                    "（DC 短路，容性馈口径被破坏）"
        return
    if template in gh.FIELD_PORT_TEMPLATES:
        # 场激励端口（WaveguidePort 文件模式，路线 A）：馈电点在槽中空气隙，
        # "端口悬空"判据不适用——改查端口盒包围盒含 ≥1 金属原语（截面含导体）
        for number, port in ports.items():
            lo = np.minimum(np.asarray(port.start, dtype=float),
                            np.asarray(port.stop, dtype=float))
            hi = np.maximum(np.asarray(port.start, dtype=float),
                            np.asarray(port.stop, dtype=float))
            inside = [p for p in prims if gh.is_conductor(p)
                      and bool(np.all(p.hi >= lo - 1e-9))
                      and bool(np.all(p.lo <= hi + 1e-9))]
            assert inside, f"{template} port{number}: 端口截面无导体（模式端口无效）"
    else:
        components = {
            n: gh.containing_labels(gh.port_feed_point(p), conductors, labels)
            for n, p in ports.items()
        }
        for number, comp in components.items():
            assert comp, f"{template} port{number}: 馈电点不在任何导体上（激励悬空）"
            assert any(
                labels[i] in comp and conductors[i].kind == "Metal"
                for i in range(len(conductors))
            ), f"{template} port{number}: 连通分量不含金属原语"

        groups = gh.PORT_GROUPS.get(template, (frozenset(ports),))
        used: set[int] = set()
        for group in groups:
            common = set.intersection(*(set(components[n]) for n in group))
            assert common, (
                f"{template}: 分组 {sorted(group)} 未导通 "
                f"{[sorted(components[n]) for n in group]}（#212 pt5/pt6 端口全死）"
            )
            assert not (common & used),                 f"{template}: 分组 {sorted(group)} 与其它分组短路"
            used |= common


# ─── ④ 域/基板尺寸与 meta 一致 ───────────────────────────────────────────────

@pytest.mark.parametrize("template", sorted(EXPECTED_TEMPLATES))
def test_domain_and_substrate_match_meta(template):
    scope, prims = gh.load_geometry(template)
    dom_x, dom_y = gh.domain_half_extents(scope)
    board = float(scope.get("BOARD", max(dom_x, dom_y)))
    h_sub = float(scope["H_SUB"])
    if template in gh.RECT_DOMAIN_TEMPLATES:
        # 槽线族：矩形域 + 模板参数基板（设计点 h=1.524，闭式域要求，见 helpers）
        assert h_sub == pytest.approx(
            float(TEMPLATE_NOMINAL[template]["h_mm"]) * 1e-3, rel=1e-12)
        assert float(scope["ER"]) == pytest.approx(
            float(TEMPLATE_NOMINAL[template]["er"]), rel=1e-12)
    else:
        assert h_sub == pytest.approx(float(_DEFAULT_SUB["h_mm"]) * 1e-3, rel=1e-12)
        assert float(scope["ER"]) == pytest.approx(float(_DEFAULT_SUB["er"]), rel=1e-12)

    for axis, dom in (("x", dom_x), ("y", dom_y)):
        lines = gh.mesh_lines(scope, axis)
        assert lines.min() == pytest.approx(-dom, abs=1e-9), \
            f"{template}: {axis} 域下界 {lines.min()} != -{dom}"
        assert lines.max() == pytest.approx(dom, abs=1e-9), \
            f"{template}: {axis} 域上界 {lines.max()} != {dom}"

    dielectric = [p for p in prims if p.kind == "Material"]
    if template in gh.NO_SUBSTRATE_TEMPLATES:
        assert dielectric == [], f"{template}: 无基板器件不应有介质原语"
        return
    # 恰一块全板基板 + 登记的额外介质（EXTRA_DIELECTRICS：sma_launcher 的 PTFE
    # 填充环/板边切口空气盒）；集合外的第二块介质即红
    extra = gh.EXTRA_DIELECTRICS.get(template, frozenset())
    extra_found = {p.prop for p in dielectric if p.prop in extra}
    subs = [p for p in dielectric if p.prop not in extra]
    assert len(subs) == 1, f"{template}: 基板原语数 {len(subs)}（介质 {[p.prop for p in dielectric]}）"
    assert extra_found == extra, f"{template}: 登记的额外介质缺失 {sorted(extra - extra_found)}"
    sub = subs[0]
    if template in gh.RECT_DOMAIN_TEMPLATES:
        assert sub.lo[0] == pytest.approx(-dom_x, abs=1e-9)
        assert sub.hi[0] == pytest.approx(dom_x, abs=1e-9)
        assert sub.lo[1] == pytest.approx(-dom_y, abs=1e-9)
        assert sub.hi[1] == pytest.approx(dom_y, abs=1e-9)
        assert sub.lo[2] == pytest.approx(0.0, abs=1e-12)
        assert sub.hi[2] == pytest.approx(h_sub, rel=1e-9)
        return
    assert sub.lo[0] == pytest.approx(-board, abs=1e-9)
    assert sub.hi[0] == pytest.approx(board, abs=1e-9)
    assert sub.lo[1] == pytest.approx(-board, abs=1e-9)
    assert sub.hi[1] == pytest.approx(board, abs=1e-9)
    if template == "suspended_stripline":
        # C9 悬置带线：基板 H_SUB 以带中面 b/2 对称悬浮 [b/2−H/2, b/2+H/2]
        # （腔高 b=nominal b_mm，上下地=域 z 边界），基板不从 z=0 起
        b_cav = float(TEMPLATE_NOMINAL[template]["b_mm"]) * 1e-3
        assert sub.lo[2] == pytest.approx(b_cav / 2 - h_sub / 2, rel=1e-9)
        assert sub.hi[2] == pytest.approx(b_cav / 2 + h_sub / 2, rel=1e-9)
        z_lines = gh.mesh_lines(scope, "z")
        assert z_lines.min() == pytest.approx(0.0, abs=1e-12)
        assert z_lines.max() == pytest.approx(b_cav, rel=1e-9)
        return
    if template == "sma_launcher":
        # WP2.5 SMA edge-launch 夹具口径：PCB 抬高 Z_G=r_os−r_i−H_SUB（针底切线=
        # 基板顶），基板 [Z_G, Z_G+H_SUB]；z=0 PEC=夹具底板（壳底切线）；域顶=
        # 壳顶+AIR_TOP（几何单源 sma_launcher_layout，0.4mm 审计档 base）
        lay = sma_launcher_layout(dict(TEMPLATE_NOMINAL[template]), h_sub,
                                  gh.DEFAULT_MESH_MM * 1e-3)
        assert sub.lo[2] == pytest.approx(lay["z_g"], rel=1e-9)
        assert sub.hi[2] == pytest.approx(lay["z_top"], rel=1e-9)
        z_lines = gh.mesh_lines(scope, "z")
        assert z_lines.min() == pytest.approx(0.0, abs=1e-12)
        assert z_lines.max() > lay["z_ax"] + lay["ros"] + 4e-3   # 壳顶上方 ≥4mm 空气
        return
    top = 2 * h_sub if template in ("via", "stripline") else h_sub
    assert sub.lo[2] == pytest.approx(0.0, abs=1e-12)
    assert sub.hi[2] == pytest.approx(top, rel=1e-9)


# ─── ⑤ 网格最小间距守卫（#152）───────────────────────────────────────────────

@pytest.mark.parametrize("template", sorted(EXPECTED_TEMPLATES))
def test_mesh_min_gap_guard(template):
    scope, _ = gh.load_geometry(template)
    for axis in _AXES:
        lines = gh.mesh_lines(scope, axis)
        assert lines.size >= 2, f"{template}: {axis} 轴网格线不足"
        diffs = np.diff(lines)
        assert bool(np.all(diffs > 0)), f"{template}: {axis} 轴网格线非严格递增"
        assert bool(np.all(diffs > 1e-6)), \
            f"{template}: {axis} 轴存在 <1µm 近重合线（#152 CFL 塌缩）"


# ─── 参数化几何布线（声明即生效）─────────────────────────────────────────────

@pytest.mark.parametrize("template", sorted(EXPECTED_TEMPLATES))
def test_declared_params_drive_geometry(template):
    """TEMPLATE_META.params 每个键扰动后必须改变 CSXCAD 导体几何。

    atten_db 由合成层消费（SYNTHESIS_ROUTED_PARAMS）；patch 的幽灵参数
    feed_w_mm 已随元数据修复替换为渲染实读的 feed_offset_mm（白名单清空）——
    集合外的新"声明但不生效"参数即红。JOINT_DOMAIN_PARAMS（coupled_bpf/C3
    order）单键扰动结构非法，几何驱动性由其模板单测直接覆盖。
    LUMPED_VALUE_PARAMS（combline c_load_pf）进渲染脚本的 LumpedElement 元件值
    而非导体几何，字面量接线由其模板单测钉住。MATERIAL_VALUE_PARAMS
    （sma_launcher er_fill）进渲染脚本的 AddMaterial 介电常数而非导体几何，
    字面量接线与"不驱动导体"语义由 test_sma_launcher_template 钉住。
    """
    declared = list(TEMPLATE_META[template]["params"])
    changed = gh.geometry_changing_params(template, declared)
    allowed = set(gh.SYNTHESIS_ROUTED_PARAMS) | set(
        gh.KNOWN_METADATA_DRIFT.get(template, frozenset())
    ) | set(gh.JOINT_DOMAIN_PARAMS.get(template, frozenset())) | set(
        gh.LUMPED_VALUE_PARAMS.get(template, frozenset())
    ) | set(gh.MATERIAL_VALUE_PARAMS.get(template, frozenset()))
    unwired = set(declared) - changed - allowed
    assert not unwired, f"{template}: 声明但未驱动几何的参数 {sorted(unwired)}"


# ─── meta ↔ 渲染脚本一致性（§10.20 任务 3）───────────────────────────────────

@pytest.mark.parametrize("template", sorted(EXPECTED_TEMPLATES))
def test_meta_yaml_identity_matches_template_meta(template):
    """meta.yaml 的 template / f0_ghz / n_ports 与 TEMPLATE_META 及几何一致。"""
    data = _meta_yaml(template)
    meta = TEMPLATE_META[template]
    assert data["template"] == template
    assert float(data["f0_ghz"]) == pytest.approx(float(meta["f0_ghz"]), rel=1e-12)
    assert int(data["n_ports"]) == int(meta["n_ports"])
    spec_ports = geometry_spec(template, dict(TEMPLATE_NOMINAL[template]))["ports"]
    assert len(spec_ports) == int(meta["n_ports"]), "geometry_spec 端口数与 meta 漂移"


@pytest.mark.parametrize("template", sorted(EXPECTED_TEMPLATES))
def test_meta_yaml_params_drive_geometry(template):
    """meta.yaml 声明的 params / nominal_params 必须真正驱动渲染几何（漂移即红）。"""
    data = _meta_yaml(template)
    declared = list(data.get("params") or [])
    declared += [k for k in (data.get("nominal_params") or {}) if k not in declared]
    changed = gh.geometry_changing_params(
        template, declared, extra_nominal=data.get("nominal_params")
    )
    unwired = (set(declared) - changed - set(gh.SYNTHESIS_ROUTED_PARAMS)
               - set(gh.JOINT_DOMAIN_PARAMS.get(template, frozenset()))
               - set(gh.LUMPED_VALUE_PARAMS.get(template, frozenset()))
               - set(gh.MATERIAL_VALUE_PARAMS.get(template, frozenset())))
    assert not unwired, f"{template}: meta.yaml 声明但渲染不用 {sorted(unwired)}"


@pytest.mark.parametrize("template", sorted(EXPECTED_TEMPLATES))
def test_meta_f0_wired_into_render_excitation(template):
    """以 meta f0 为中心的频带渲染时，激励常量 F0 必须等于 meta f0。"""
    scope, _ = gh.load_geometry(template)
    f0 = float(TEMPLATE_META[template]["f0_ghz"])
    assert float(scope["F0"]) == pytest.approx(f0 * 1e9, rel=1e-12)
    assert float(scope["FC"]) == pytest.approx(gh.BAND_HALF_GHZ * 1e9, rel=1e-12)
