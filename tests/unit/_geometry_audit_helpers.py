"""§10.20 补强④ 共享夹具：全部模板离线几何审计（#212 审计模式泛化）。

审计手法：render_script → exec 几何段（FDTD.Run 之前）→ CSXCAD 实测
金属/介质原语、网格线、端口对象。秒级、零仿真、无网络、不落盘
（__file__ 仅用于脚本内路径拼接，不写文件）。

设计要点（#212 教训）：全部判据量在 CSXCAD 实测对象上，不做字符串存在性
检查——compile/字符串门抓不住画法错误（pt5/pt6"中心线弦"三端口全死、
wilkinson 共线断口直通线、openEMS AddMetal priority 类型错误均能通过
compile）。

判据一览：
① 原语非零体积（金属面内非零面积 / 柱半径>0）+ 原语坐标进网格；
② 端口面贴板边（PML）或内部集总端口激励体积非零；
③ 信号连通性：分组内端口共享同一导体分量，分组间不短路；
④ 域/基板尺寸与 meta 声明一致；
⑤ 网格最小间距守卫（#152，>1µm）。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import (
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    render_script,
)

# 收敛档网格（#198/#212）：0.4mm 档下 rat-race 环带/径向馈逐行栅格化已定标。
DEFAULT_MESH_MM = 0.4
# §C3 滤波器族 II 耦合缝网格守卫（#266，render_script 违反即抛错）：NEAR=base/4
# ≤ 缝_min/3 ⇒ base ≤ 4·缝_min/3（名义缝 interdigital 0.2263→0.3017 /
# combline 0.1393→0.1857 / sir_bpf 0.2417→0.3223 mm）——审计档按模板覆盖，
# 其余模板仍走 0.4mm 收敛档（load_geometry 缺省 mesh_mm=None 时查表）。
TEMPLATE_MESH_MM: dict[str, float] = {
    "interdigital": 0.30, "combline": 0.18, "sir_bpf": 0.32,
    # §MMWAVE_SERIES_ARRAY（df7 C10d）：毫米波线宽分辨守卫档（NEAR=0.05 ≤
    # feed_w/3=0.109，#266 族；0.4 缺省档 NEAR=0.1 越守卫即渲染期红）
    "mmwave_series_array": 0.20,
}
# 各模板带宽（以 meta f0 为中心，±0.25GHz）——网格 BASE 由 mesh_resolution
# 显式覆盖，故带宽只影响激励常量 F0/FC 与辐射器件空气隙。
BAND_HALF_GHZ = 0.25

# 端口连通分组（③）：默认全部端口同属一个导体网络（功分器/混合环/线/基元）。
# coupled_line 例外：两条 DC 隔离的耦合线——{1,2}=直通线、{3}=耦合线，
# 必须各自连通，且两组不得合流（耦合缝塌缩成短路即红）。
# hairpin 例外（耦合滤波器族定义性质）：N 个 DC 隔离谐振器，端口 1/2 分属
# 首/末谐振器——两端口同分量即缝塌缩短路（与功分器族判据相反）。
# coupled_bpf 同族：输入馈线+首耦合段 / 输出馈线+末耦合段 各自一个分量，
# N 个谐振器另成 N 个隔离分量（N+2 分量，test_coupled_bpf_template 钉数）。
# §C3 滤波器族 II（interdigital/combline/sir_bpf）同族：双馈线 + N 根接地棒
# 全程缝隔离（棒与其过孔柱/装载电容盒同分量），N+2 分量，端口 1/2 分属两馈线。
# §C4 耦合器族 II：cline_coupler 两条 DC 隔离耦合线——{1,2}=线 A（输入/直通）、
# {3,4}=线 B（耦合/隔离）；lange 展开型交替指并联——{1,2}=网络 A（指 1/3 +
# 两端 air-bridge）、{3,4}=网络 B（指 2/4），桥抬高 z>H_SUB 不与被跨指 bbox
# 相交（同层直通即两组短路红）；branchline_2sect 单导体网络走默认。
PORT_GROUPS: dict[str, tuple[frozenset[int], ...]] = {
    "coupled_line": (frozenset({1, 2}), frozenset({3})),
    "hairpin": (frozenset({1}), frozenset({2})),
    # hairpin_alt（2026-09-18 交替取向变体）：同族判据，N 个 DC 隔离谐振器
    "hairpin_alt": (frozenset({1}), frozenset({2})),
    "coupled_bpf": (frozenset({1}), frozenset({2})),
    "interdigital": (frozenset({1}), frozenset({2})),
    "combline": (frozenset({1}), frozenset({2})),
    "sir_bpf": (frozenset({1}), frozenset({2})),
    "cline_coupler": (frozenset({1, 2}), frozenset({3, 4})),
    "lange": (frozenset({1, 2}), frozenset({3, 4})),
    # 槽线族（2026-09-18 注册）：过渡 P1=微带网络、P2=地板/槽网络（跨基板
    # 不导通，与功分器族判据相反）；巴伦 P2/P3 同属地板网络（槽臂+中条经封口桥
    # 共棱连通），与 P1 微带网络隔离
    "msl_slot_transition": (frozenset({1}), frozenset({2})),
    "marchand_balun": (frozenset({1}), frozenset({2, 3})),
    # §DP-4 P3 EEP 阵列族（df6）：每元独立探针、元间 DC 隔离=EEP 定义性质
    # （4 个独立导体分量）——与功分器族"全阵单分量"判据相反：{1}{2}{3}{4}
    # 各自一组，组间合流即元间短路红
    "patch_eep_2x2": (frozenset({1}), frozenset({2}), frozenset({3}),
                      frozenset({4})),
    "patch_eep_1x4": (frozenset({1}), frozenset({2}), frozenset({3}),
                      frozenset({4})),
}

# 场激励端口模板（2026-09-18）：WaveguidePort 文件模式（路线 A）是截面场
# 激励——馈电点在槽中空气隙，不在导体上（"端口悬空"判据不适用）。改查：端口
# 盒包围盒内含 ≥1 金属原语（模式端口截面含导体=截面有效）。
FIELD_PORT_TEMPLATES: frozenset[str] = frozenset({"slotline"})

# 面内缩 MSL 端口模板（2026-09-18；H4 教训：MSLPort 段⊂PML_8 致非物理，
# 槽线过渡/巴伦有意把端口段内移 14·BASE）。判据改：端口面严格在域内、且含
# 馈电点的金属原语沿端口轴延伸到域边界（馈线到板边=无开路 stub，#174）。
INSET_PORT_TEMPLATES: frozenset[str] = frozenset({"msl_slot_transition",
                                                  "marchand_balun"})

# 域边贴界 MSL 端口模板（SIW 锥形过渡族）：矩形域 DOM_Y 字面≠BOARD 的
# 模板，MSLPort 面=域边界=PML 面（mline"端口面贴板边"口径的矩形域变体）。
EDGE_PORT_TEMPLATES: frozenset[str] = frozenset({"msl_siw_taper"})

# 全口径集总电阻片端口模板（DP-10 §MS_METASURFACE）：波导
# 模拟器 TEM 馈——LumpedPort 全口径片（exc_dir=x，R=η0），浮于空气区，
# 与屏/贴片金属 DC 隔离（容性馈）。审计③"馈电点在导体上"判据不适用，
# 改查：片端口 LumpedElement 与金属原语无 bbox 接触（短路即红）+ 模板
# 有独立金属网络（屏/贴片）。
SHEET_PORT_TEMPLATES: frozenset[str] = frozenset({"ms_patch", "ms_cross",
                                                  "ms_jcross"})

# 无端口模板（DP-10）：软平面照明散射体（ms_array_NxN）——
# openEMS 无 TF/SF 平面波，用 exc_type=0 软激励平面 + nf2ff 盒替代（官方
# PPW 教程口径）。审计②无端口对象，改查软激励平面与 nf2ff 盒存在；
# 审计③无端口连通性，改查金属分量数与 BC 地连续。
PORTLESS_TEMPLATES: frozenset[str] = frozenset({"ms_array_NxN"})

# 矩形域/模板参数基板模板：域 x/y 半宽不同（DOM_HI/Y_HALF/
# DOM_X/DOM_Y），基板厚取 TEMPLATE_NOMINAL.h_mm（槽线闭式域要求 d/λ0≥0.006，
# 缺省叠层 0.508@2.5GHz 落域外——设计点 RO4350B 60mil h=1.524）。
RECT_DOMAIN_TEMPLATES: frozenset[str] = frozenset({"slotline", "slotline_lumped",
                                                   "msl_slot_transition",
                                                   "marchand_balun",
                                                   "siw", "msl_siw_taper",
                                                   # §MS_METASURFACE（df6 DP-10）：
                                                   # 单胞方形域/阵矩形域 +
                                                   # 模板参数基板（nominal h_mm）
                                                   "ms_patch", "ms_cross",
                                                   "ms_jcross", "ms_array_NxN",
                                                   # §COIL_NFC（df7 C10b）：线圈
                                                   # 矩形域 + FR4 类模板参数基板
                                                   "coil_nfc",
                                                   # §MMWAVE_SERIES_ARRAY（df7
                                                   # C10d）：方域 + RO3003 类
                                                   # 模板参数基板（78GHz 毫米波板）
                                                   "mmwave_series_array"})

# 无介质板模板：dipole=自由空间器件（官方 Helical/Dipole-SAR 口径）；
# monopole/helix=PEC 地面悬空导体（像理论口径，§10.3 C1 天线族 II
# _ANTENNA2_TALL_TEMPLATES）；loop=自由空间环（2026-09-16 改造：无板无地、底
# MUR，_ANTENNA2_FREE_SPACE_TEMPLATES）——审计④"恰一块全板基板"对其改判
# "零介质原语"。
NO_SUBSTRATE_TEMPLATES: frozenset[str] = frozenset(
    {"dipole", "monopole", "helix", "loop"})

# 联合域参数：单键扰动在结构上非法（只能与其它参数联动改变）——
# coupled_bpf 的 order 决定 widths_mm/gaps_mm 列表长度（order+1），nominal
# 列表固定为 4 项，单独把 order 扰到 4 即 _coupled_bpf_layout 显式 ValueError
# （test_coupled_bpf_template.test_layout_validation 钉住）。其几何驱动性由
# test_order_sweep_designable（N=1..5 全链可设计）直接覆盖，审计单键扰动跳过。
# §C3 三模板同规（order 决定 gaps_mm 长度 N+1，_c3_gaps_from_params 显式报错）。
JOINT_DOMAIN_PARAMS: dict[str, frozenset[str]] = {
    "coupled_bpf": frozenset({"order"}),
    "interdigital": frozenset({"order"}),
    "combline": frozenset({"order"}),
    "sir_bpf": frozenset({"order"}),
    # §MS_METASURFACE（df6 DP-10）：n_x/n_y 决定 cell_map 行列数（同 order
    # 联动语义），cell_map 逐胞参数表——单键扰动结构非法，几何驱动性由
    # test_metasurface_templates（cell_map 变更→贴片逐胞变化+覆盖完备守卫）覆盖
    "ms_array_NxN": frozenset({"n_x", "n_y", "cell_map"}),
}

# 进渲染脚本的**集总元件值**而非导体几何的参数：combline 的 c_load_pf 是
# CSXCAD LumpedElement 的 C 值（与电路裁判同源消费），导体盒签名不随之变化
# ——不是漂移；字面量接线由 test_combline_template 钉住（脚本含 C=<值>）。
LUMPED_VALUE_PARAMS: dict[str, frozenset[str]] = {
    "combline": frozenset({"c_load_pf"}),
    # §MMWAVE_SERIES_ARRAY（df7 C10d）：load_r_ohm 是链末端接集总电阻值
    # （LumpedElement R 值，与渲染脚本 LOAD_R 字面量同源消费），导体盒签名
    # 不随之变化——不是漂移；字面量接线由 test_mmwave_series_array_template 钉
    "mmwave_series_array": frozenset({"load_r_ohm"}),
}

# 进渲染脚本的**材料参数**而非导体几何的参数（2026-09-16 sma_launcher 注册）：
# er_fill / tan_d_fill 是 PTFE 填充环 AddMaterial(epsilon=…, kappa=…) 的介电常数/
# 损耗——同轴 TEM 口径 εeff=εr 与介质损耗由它们驱动电气（fake/真机同源消费），
# 导体签名不随之变化——不是漂移；字面量接线由 test_sma_launcher_template 钉住
# （脚本含 ER_FILL=<值>/PT_TAND=<值>，且导体签名对其扰动不变）。语义独立于
# LUMPED_VALUE_PARAMS，不得混用。
MATERIAL_VALUE_PARAMS: dict[str, frozenset[str]] = {
    "sma_launcher": frozenset({"er_fill", "tan_d_fill"}),
    # 槽线族均匀线段：er/tan_d 只进基板材料属性不改几何（TEMPLATE_NOMINAL 与
    # meta.yaml nominal_params 键集一致由 test_template_meta_consistency 钉）。
    "slotline": frozenset({"er", "tan_d"}),
    "slotline_lumped": frozenset({"er", "tan_d"}),
    # siw：er/tan_d 只进基板材料属性（TE10 截止与 β 与 h 无关——h_mm 是
    # 几何驱动参数经端口盒/板 z 消费，不需豁免）；nominal-only 键与 slotline 同口径
    "siw": frozenset({"er", "tan_d"}),
    # msl_siw_taper（df6 A2）：tan_d 只进基板材料 kappa 不改导体几何；er/h
    # 进锥宽设计链（inverse_width/Z_PV 同参精算）驱动导体——不需豁免
    "msl_siw_taper": frozenset({"tan_d"}),
    # §MS_METASURFACE（df6 DP-10）：er/tan_d 只进基板材料属性（与 slotline/siw
    # 同口径）；h_mm/几何键经 substrate 盒/屏 z 消费驱动导体，不需豁免
    "ms_patch": frozenset({"er", "tan_d"}),
    "ms_cross": frozenset({"er", "tan_d"}),
    "ms_jcross": frozenset({"er", "tan_d"}),
    "ms_array_NxN": frozenset({"er", "tan_d"}),
    # §COIL_NFC（df7 C10b）：er/tan_d 只进基板材料属性（slotline/siw 同口径）；
    # h_mm 是几何驱动参数经基板盒/金属面 z 消费，不需豁免
    "coil_nfc": frozenset({"er", "tan_d"}),
    # §MMWAVE_SERIES_ARRAY（df7 C10d）：er/tan_d 只进基板材料属性（同 coil_nfc
    # 口径，RO3003 类毫米波板）；h_mm/几何键经基板盒/金属面 z 消费，不需豁免
    "mmwave_series_array": frozenset({"er", "tan_d"}),
}

# 登记的**额外介质原语**（审计④"恰一块全板基板"之外的合法介质，按属性名）：
# sma_launcher 的 PTFE 填充环（ptfe）与板边切口空气盒（sma_notch，覆盖基板层
# 令 y<Y_E 无基板）。集合外出现第二块介质即红。
EXTRA_DIELECTRICS: dict[str, frozenset[str]] = {
    "sma_launcher": frozenset({"ptfe", "sma_notch"}),
}

# 亚 cell 柱体属性（2r < 网格 base，横向不要求网格线穿过）：msl_cpw 的接地过孔
# 栅栏 r=0.15mm（via 基元先例——阶梯化为本族既定口径，test_msl_cpw_template
# 同口径），轴向两端仍须落网格线。该模板几何/网格已由真机 PASS 冻结
# （runs/wp25_tier2_smoke/pt1_msl_cpw3，|S11| −20.0dB、β ±1%），不改近场线。
SUBCELL_CYLINDER_PROPS: dict[str, frozenset[str]] = {
    "msl_cpw": frozenset({"msl_cpw_via"}),
}

# meta 参数中由合成层消费、不进 render_script 几何的参数：atten_db 由
# core/synthesis 的 attenuator_pi/t ABCD 闭式解析为 r_series/r_shunt，
# render 读的是电阻值——正常分层，不是漂移。
SYNTHESIS_ROUTED_PARAMS: frozenset[str] = frozenset({"atten_db"})

# 已知 TEMPLATE_META 元数据漂移（泛化审计实测发现、修复后清空的登记处）：
# 历史条目 patch/feed_w_mm（幽灵参数，无消费者）已随元数据修复清空——
# TEMPLATE_META['patch'].params 现声明渲染实读的 feed_offset_mm，TEMPLATE_NOMINAL
# 同步补键。当前集合为空 = 无已知漂移；新出现的未驱动参数（集合外）即红。
KNOWN_METADATA_DRIFT: dict[str, frozenset[str]] = {}

# 参数扰动覆盖（默认 ×1.37+0.013 对域受限参数会越界出合法域）：键 →
# (乘法因子, 加法偏移)。hairpin 的 tap_frac ∈ (0,0.5)（越界 =
# _hairpin_layout 显式 ValueError）：×0.9 保域且必变几何（与
# test_hairpin_template.py 参数化口径一致）。helix 的 helix_turns 为整数
# （_ant2_layout int() 截断）：默认 2×1.37+0.013=2.753→int 2 = 几何不变的
# 假阴性；×0.5→1 圈，螺距守卫 p=(λ0/4−4·d·1)/1=19.2mm ≥1 保域且必变几何。
PERTURB_OVERRIDES: dict[str, dict[str, tuple[float, float]]] = {
    "hairpin": {"tap_frac": (0.9, 0.0)},
    "hairpin_alt": {"tap_frac": (0.9, 0.0)},     # 同族 τ∈(0,0.5) 域守卫
    "helix": {"helix_turns": (0.5, 0.0)},
    # coupled_bpf：res_len ×1.37 使 (N+1)·lc 阵列超出 60mm 板（_coupled_bpf_layout
    # 输出馈余量 ≤0 显式 ValueError）；×0.9 缩短保域（与 test_coupled_bpf_template
    # 的 feed_len ×0.9 口径一致）
    "coupled_bpf": {"res_len_mm": (0.9, 0.0), "feed_len_mm": (0.9, 0.0)},
    # §C3 三模板：棒阵列 y 居中于板，feed_len ×1.37 把阵列顶端推出 60mm 板
    # （_c3_layout 余量 ≤0 显式 ValueError）→ ×0.9 保域必变几何；interdigital
    # res_len ×1.37 同理越板 → ×0.9
    "interdigital": {"res_len_mm": (0.9, 0.0), "feed_len_mm": (0.9, 0.0)},
    "combline": {"feed_len_mm": (0.9, 0.0)},
    "sir_bpf": {"feed_len_mm": (0.9, 0.0)},
    # siw：s_mm ×1.37 会越泄漏上界 s≤2d（1.383>2×0.6，设计规则守卫拒渲染
    # ——守卫是正确行为，runs/siw_family/criteria.md §1）；×1.1 保域
    # （1.1≤1.2）且必变几何
    "siw": {"s_mm": (1.1, 0.0)},
    # msl_siw_taper（df6 A2）：s_mm 同 siw（设计规则 s≤2d 共用单源）；
    # taper_len_mm ×1.37 把 dom_y 拉长（合法，无越界）；siw_len_mm 同合法
    "msl_siw_taper": {"s_mm": (1.1, 0.0)},
    # §MS_METASURFACE（df6 DP-10）：ms_cross arm_len ×1.37 使 2·arm 越胞
    # （2×6.74>12，"臂须在胞内"守卫拒渲染——守卫是正确行为）；×1.1 保域
    # （2×5.41<12）且必变几何。ms_jcross slot_len ×1.37=6.74<12 合法不需覆盖。
    "ms_cross": {"arm_len_mm": (1.1, 0.013)},
}


@dataclass
class Prim:
    """一条 CSXCAD 原语的三维包围盒（米）+ 类型信息。"""

    prop: str          # 所属属性名（Metal/Material 属性）
    kind: str          # CSXCAD 属性类型：Metal / Material / LumpedElement / ...
    prim_type: str     # 原语类型串（"1"=盒，"5"=柱）
    lo: np.ndarray     # 包围盒下角（米）
    hi: np.ndarray     # 包围盒上角（米）
    radius: float | None = None   # 柱半径（仅 CSPrimCylinder）

    @property
    def extent(self) -> np.ndarray:
        return self.hi - self.lo


def is_conductor(p: Prim) -> bool:
    """导体（金属 + 集总元件桥接盒）——参与连通性图的原语。"""
    return p.kind in ("Metal", "LumpedElement")


def band_for(template: str) -> tuple[float, float]:
    """该模板的审计频带（以 meta f0 为中心的 ±0.25GHz）。"""
    f0 = float(TEMPLATE_META[template]["f0_ghz"])
    return (f0 - BAND_HALF_GHZ, f0 + BAND_HALF_GHZ)


def extract_primitives(csx: Any) -> list[Prim]:
    """CSXCAD 属性表 → 原语包围盒列表（柱按半径外扩为等效盒）。

    B6 stage-2 扩：CSPrimPolygon(7)/CSPrimLinPoly(8)
    无 GetStart/GetStop（CSPrimPolygon 无此方法，AttributeError）——改走
    GetBoundBox()（基类方法，返回 (2,3) [lo, hi] 数组，已按
    norm_dir/elevation 展开为三维包围盒）。CSPrimCylindricalShell(6)
    （b6 via 桶壁）有轴线端点但包围盒须按外缘 radius+shell_width/2 外扩
    （绑定口径 radius=中径）。
    """
    out: list[Prim] = []
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        kind = str(prop.GetTypeString())
        for prim in prop.GetAllPrimitives():
            prim_type = str(prim.GetType())
            radius: float | None = None
            if hasattr(prim, "GetStart"):
                start = np.asarray(prim.GetStart(), dtype=float)
                stop = np.asarray(prim.GetStop(), dtype=float)
                lo = np.minimum(start, stop)
                hi = np.maximum(start, stop)
                if prim_type in ("5", "6"):
                    # CSPrimCylinder(5)：start/stop 是轴线两端；CSPrimCylindricalShell
                    # (6)：桶壁外缘 = radius + shell_width/2（绑定口径 radius=中径，
                    # 实测 radius=1.0/shell_width=0.2 → GetBoundBox ±1.1）。
                    # 轴向感知（2026-09-16 sma_launcher 注册）：沿实际轴（轴线端点
                    # 唯一非零轴）之外的两轴按外径外扩——z 向柱（via/栅栏）行为不变，
                    # y 向柱（sma 针/壳）不再被误判为零厚 z 面
                    radius = float(prim.GetRadius())
                    outer = radius + (float(prim.GetShellWidth()) / 2.0
                                      if prim_type == "6" else 0.0)
                    axis = int(np.argmax(hi - lo))
                    grow = np.array([outer, outer, outer])
                    grow[axis] = 0.0
                    lo = lo - grow
                    hi = hi + grow
            else:
                bb = np.asarray(prim.GetBoundBox(), dtype=float)
                lo, hi = bb[0], bb[1]
            out.append(Prim(str(prop.GetName()), kind, prim_type, lo, hi, radius))
    return out


_CACHE: dict[tuple, tuple[dict[str, Any], list[Prim]]] = {}


def _scalar(v: Any) -> Any:
    """缓存键归一：numpy 标量 → Python 标量；列表/元组（coupled_bpf 的
    widths_mm/gaps_mm）→ 元素归一后的元组（list 不可哈希，直接进键会抛错）；
    dict（b6_board 板级事实）→ 键排序后的嵌套元组。"""
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, dict):
        return tuple(sorted((k, _scalar(x)) for k, x in v.items()))
    if isinstance(v, (list, tuple)):
        return tuple(_scalar(x) for x in v)
    return v


def load_geometry(
    template: str,
    params: dict[str, Any] | None = None,
    mesh_mm: float | None = None,
) -> tuple[dict[str, Any], list[Prim]]:
    """渲染→exec 几何段→(脚本全局字典, 原语列表)；同参数结果会话内缓存。

    mesh_mm=None → TEMPLATE_MESH_MM 按模板查表（C3 族守卫档），否则 DEFAULT_MESH_MM。
    """
    if mesh_mm is None:
        mesh_mm = TEMPLATE_MESH_MM.get(template, DEFAULT_MESH_MM)
    resolved = dict(TEMPLATE_NOMINAL[template] if params is None else params)
    key = (
        template,
        tuple(sorted((k, _scalar(v)) for k, v in resolved.items())),
        float(mesh_mm),
    )
    cached = _CACHE.get(key)
    if cached is None:
        text = render_script(template, resolved, band_for(template),
                             mesh_resolution_mm=mesh_mm)
        # 槽线族整脚本渲染器的求解段有 "# ── 求解 ──" 标记（其后可能是
        # RFAUTO_SKIP_RUN 守卫的缩进块，直接截 "FDTD.Run(" 会留下悬空 if）；
        # 主模板无该标记，回退原口径
        marker = text.find("# ── 求解 ──")
        cut = marker if marker >= 0 else text.index("FDTD.Run(")
        head = text[:cut]
        scope: dict[str, Any] = {
            "__name__": "__main__",
            "__file__": str(REPO / "_geometry_audit_sim.py"),
        }
        exec(compile(head, "geometry_audit", "exec"), scope)
        cached = (scope, extract_primitives(scope["CSX"]))
        _CACHE[key] = cached
    return cached


def domain_half_extents(scope: dict[str, Any]) -> tuple[float, float]:
    """(x, y) 域半宽（米）：主模板方形 BOARD=DOM_X=DOM_Y；槽线族矩形域用
    DOM_HI（x）/Y_HALF（y）（2026-09-18 注册）。"""
    if "DOM_X" in scope:
        x = scope["DOM_X"]
    elif "DOM_HI" in scope:
        x = scope["DOM_HI"]
    else:
        x = scope["BOARD"]
    if "DOM_Y" in scope:
        y = scope["DOM_Y"]
    elif "Y_HALF" in scope:
        y = scope["Y_HALF"]
    else:
        y = scope["BOARD"]
    return float(x), float(y)


def mesh_lines(scope: dict[str, Any], axis: str) -> np.ndarray:
    return np.asarray(scope["mesh"].GetLines(axis), dtype=float)


def conductor_signature(prims: list[Prim]) -> tuple:
    """导体原语的不可变签名（用于"参数是否驱动几何"比对）。"""
    return tuple(sorted(
        tuple(round(float(v), 12) for v in (*p.lo, *p.hi))
        for p in prims if is_conductor(p)
    ))


def geometry_changing_params(
    template: str,
    declared: list[str],
    extra_nominal: dict[str, Any] | None = None,
) -> set[str]:
    """在 nominal 上逐个扰动 declared 参数，返回确实改变导体几何的键集合。

    extra_nominal 补 TEMPLATE_NOMINAL 缺少的键（历史如 patch 的
    feed_offset_mm 曾只在 docs meta.yaml 的 nominal_params 里，元数据修复后
    TEMPLATE_NOMINAL 已含），已有键不覆盖。

    列表参数（coupled_bpf 的 widths_mm/gaps_mm：每项=第 j 耦合段线宽/缝）
    逐元素施加同一 (因子, 偏移)——长度不变（结构合法），全部段几何必变。
    JOINT_DOMAIN_PARAMS 里的键单键扰动结构非法，跳过（不计入 changed，
    由调用方从 unwired 中豁免）。
    """
    nominal = dict(TEMPLATE_NOMINAL[template])
    if extra_nominal:
        for key, value in extra_nominal.items():
            nominal.setdefault(key, value)
    base = conductor_signature(load_geometry(template, nominal)[1])
    changed: set[str] = set()
    overrides = PERTURB_OVERRIDES.get(template, {})
    joint = JOINT_DOMAIN_PARAMS.get(template, frozenset())
    for key in declared:
        if key not in nominal or key in joint:
            continue
        factor, offset = overrides.get(key, (1.37, 0.013))
        perturbed = dict(nominal)
        value = nominal[key]
        if isinstance(value, (list, tuple)):
            perturbed[key] = [float(v) * factor + offset for v in value]
        else:
            perturbed[key] = float(value) * factor + offset
        if conductor_signature(load_geometry(template, perturbed)[1]) != base:
            changed.add(key)
    return changed


def connected(a: Prim, b: Prim, tol: float = 1e-9) -> bool:
    """闭合包围盒相交（允许共享面/边/点接触；导体在 FDTD 网格上导通）。"""
    overlap = np.minimum(a.hi, b.hi) - np.maximum(a.lo, b.lo)
    return bool(np.all(overlap >= -tol))


def component_labels(prims: list[Prim]) -> list[int]:
    """并查集连通分量标签（对给定原语列表，逐对判 connected）。"""
    n = len(prims)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if connected(prims[i], prims[j]):
                parent[find(i)] = find(j)
    return [find(i) for i in range(n)]


def conductor_labels(prims: list[Prim]) -> tuple[list[Prim], list[int]]:
    conductors = [p for p in prims if is_conductor(p)]
    return conductors, component_labels(conductors)


def port_objects(scope: dict[str, Any]) -> dict[int, Any]:
    """脚本里 _portN 绑定去重后的 {端口号: 端口对象}（patch 的 _port2 别名并入）。"""
    raw = {
        int(k[5:]): v
        for k, v in scope.items()
        if k.startswith("_port") and k[5:].isdigit()
    }
    unique: dict[int, Any] = {}
    seen: dict[int, int] = {}
    for n in sorted(raw):
        if id(raw[n]) not in seen:
            seen[id(raw[n])] = n
            unique[n] = raw[n]
    return unique


def port_feed_point(port: Any) -> np.ndarray:
    """端口金属面上的代表性馈电点：start/stop 面内中点 + start 的 z（金属面）。"""
    start = np.asarray(port.start, dtype=float)
    stop = np.asarray(port.stop, dtype=float)
    return np.array([(start[0] + stop[0]) / 2, (start[1] + stop[1]) / 2, start[2]])


def containing_labels(
    point: np.ndarray, prims: list[Prim], labels: list[int], tol: float = 1e-9
) -> frozenset[int]:
    """包含该点的导体原语所属连通分量集合。"""
    return frozenset(
        labels[i]
        for i, p in enumerate(prims)
        if bool(np.all(point >= p.lo - tol)) and bool(np.all(point <= p.hi + tol))
    )


def off_mesh_planes(prims: list[Prim], scope: dict[str, Any]) -> list[tuple[str, str, float]]:
    """零厚度面必须落在网格线上（否则原语不进网格 / 激励体积坍缩，#174）。"""
    lines = {ax: mesh_lines(scope, ax) for ax in ("x", "y", "z")}
    bad: list[tuple[str, str, float]] = []
    for p in prims:
        if p.kind not in ("Metal", "Material", "LumpedElement"):
            continue
        ext = p.extent
        for index, axis in enumerate(("x", "y", "z")):
            if ext[index] <= 1e-12:
                gap = float(np.min(np.abs(lines[axis] - p.lo[index])))
                if gap > 1e-6:
                    bad.append((p.prop, axis, float(p.lo[index])))
    return bad
