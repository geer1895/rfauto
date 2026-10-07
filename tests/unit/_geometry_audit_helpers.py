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
    # hmsiw（2026-10-03 ge8b WA 席 1）：0.4mm 档 NEAR=0.1——d=0.6 ≥ 4·NEAR=0.4
    # 过守卫、孔间缝 0.4 > NEAR 过守卫（siw 同守卫口径；与 DEFAULT 同值，显式
    # 登记防缺省漂移）
    "hmsiw": 0.40,
    # §MMWAVE_SERIES_ARRAY（df7 C10d）：毫米波线宽分辨守卫档（NEAR=0.05 ≤
    # feed_w/3=0.109，#266 族；0.4 缺省档 NEAR=0.1 越守卫即渲染期红）
    "mmwave_series_array": 0.20,
    # ring_resonator（2026-09-26 fap2-ring，F-A M3）：缝分辨守卫档——自动档
    # NEAR=λ_sub/200=0.285mm > gap/3=0.133（渲染守卫拒绝，C3 族同口径）；
    # 0.4mm 档 NEAR=0.1 ≤ 0.133 过守卫（与 DEFAULT 同值，显式登记防缺省漂移）
    "ring_resonator": 0.40,
    # pyramid_horn（2026-09-26 ME-7）：λ0/50@10GHz=0.6mm 官方空气 base 档
    # （无介质板器件，base 即 λ0/50；NEAR=0.15mm，阶梯步距 2.96mm ≥4·NEAR
    # 过守卫；0.4 缺省档也能过守卫，登记为显式官方档防缺省漂移）
    "pyramid_horn": 0.60,
    # coax_waveguide_transition（2026-09-26 ME-6）：0.4mm 档 NEAR=0.1 ≤
    # min(2·pin_r, port_h)/3=0.333 探针特征分辨守卫（#266 族；官方教程
    # max_res=λ/20@f_stop≈1.46mm 为 base 上限但探针特征更紧，与 DEFAULT
    # 同值，显式登记防缺省漂移）
    "coax_waveguide_transition": 0.40,
    # schiffman（2026-10-02 TA 批）：耦合缝 0.0692mm<任何实用 NEAR——不设
    # NEAR≤gap/3 硬守卫（#311 缝中点精确入网，缝内内部线 ≥1 恒成立，C4
    # 决议口径）；0.2mm 档 NEAR=0.05 收紧缝邻域分辨（移相锚 ±few° 精度档）
    "schiffman": 0.20,
    # ridged_wg（2026-10-02 TA 批第三批）：最小特征 min(s,g)/3=1.54mm——
    # 0.4 缺省档 NEAR=0.1 足够（与 DEFAULT 同值，显式登记防缺省漂移）
    "ridged_wg": 0.40,
    # isl_shielded（2026-10-03 ge8b WB 席 B9）：0.4mm 档 NEAR=0.1——d=0.6 ≥
    # 4·NEAR=0.4 过守卫、孔间缝 0.4 > NEAR 过守卫（hmsiw 同守卫口径；与
    # DEFAULT 同值，显式登记防缺省漂移）
    "isl_shielded": 0.40,
    # vivaldi_tsa（同批）：喉部槽宽 0.3mm——0.4 缺省档 NEAR=0.1 收紧缝邻域
    # 分辨（与 DEFAULT 同值，显式登记防缺省漂移；阶梯站缘不入网，站距
    # l/24≈3.3mm 由 BASE 解析，SmoothMeshLines 站缘爆炸教训见 grid.py 注）
    "vivaldi_tsa": 0.40,
    # xcheb_bpf4（2026-10-03 ge8d WD 席 D2）：0.35mm 档 NEAR=0.0875 ≤
    # 缝_min/3=0.2885/3=0.0962 过 #266 守卫（0.4 缺省档 NEAR=0.1 > 0.0962
    # 越守卫即渲染期红——守卫是正确行为，C3 族同口径）
    "xcheb_bpf4": 0.35,
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
    # varactor_bpf（M-5 变容管调谐 BPF，2026-09-27）：hairpin 同族判据——
    # N 个 DC 隔离谐振器（各带自己的变容管装载盒，LumpedElement 与所属臂
    # bbox 相触=同分量、跨腔仍隔离），端口 1/2 分属首/末谐振器
    "varactor_bpf": (frozenset({1}), frozenset({2})),
    # hairpin_alt（2026-09-18 w2g 交替取向变体）：同族判据，N 个 DC 隔离谐振器
    "hairpin_alt": (frozenset({1}), frozenset({2})),
    # ring_resonator（2026-09-26 fap2-ring，F-A M3）：间隙耦合定义性质——
    # 输入馈线/环带/输出馈线 3 个 DC 隔离分量（缝塌缩短路即红，与功分器族
    # 判据相反）；环带分量无直接端口，同 hairpin 的 N 谐振器口径不查
    "ring_resonator": (frozenset({1}), frozenset({2})),
    "coupled_bpf": (frozenset({1}), frozenset({2})),
    "interdigital": (frozenset({1}), frozenset({2})),
    "combline": (frozenset({1}), frozenset({2})),
    "sir_bpf": (frozenset({1}), frozenset({2})),
    "cline_coupler": (frozenset({1, 2}), frozenset({3, 4})),
    "lange": (frozenset({1, 2}), frozenset({3, 4})),
    # 槽线族（2026-09-18 w1b 注册）：过渡 P1=微带网络、P2=地板/槽网络（跨基板
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
    # pyramid_horn（2026-09-26 ME-7）：单波导口模式端口（单组口径与缺省
    # (frozenset(ports),) 同效，显式登记防多端口漂移时静默改判据）
    "pyramid_horn": (frozenset({1}),),
    # coax_waveguide_transition（2026-09-26 ME-6）：探针柱经集总桥（port1
    # LumpedPort，is_conductor 含 LumpedElement）与腔壁网络导通=单网络口径
    # （壁+桥+探针 1 分量；本模板在 FIELD_PORT 分支，组判据不生效——同
    # pyramid_horn 显式登记口径，连通性正面断言由 test_coax_wg_template 钉）
    "coax_waveguide_transition": (frozenset({1, 2}),),
    # schiffman（2026-10-02 TA 批）：双路径 DC 隔离=器件定义性质（与功分器族
    # 判据相反）——{1,2}=耦合段 C-section（近端双带条+远端桥带导通）、
    # {3,4}=参考直通段；两组合流=路径间短路红
    "schiffman": (frozenset({1, 2}), frozenset({3, 4})),
    # ridged_wg（2026-10-02 TA 批第三批）：全金属封闭波导单网络（与缺省
    # (frozenset(ports),) 同效，显式登记防多端口漂移时静默改判据）
    "ridged_wg": (frozenset({1, 2}),),
    # xcheb_bpf4（2026-10-03 ge8d WD 席 D2）：hairpin 同族判据——四个 DC
    # 隔离开路环谐振器，端口 1/2 分属环 1/环 4（缝塌缩短路即红，与功分器
    # 族判据相反）
    "xcheb_bpf4": (frozenset({1}), frozenset({2})),
}

# 场激励端口模板（2026-09-18 w1b）：WaveguidePort 文件模式（路线 A）是截面场
# 激励——馈电点在槽中空气隙，不在导体上（"端口悬空"判据不适用）。改查：端口
# 盒包围盒内含 ≥1 金属原语（模式端口截面含导体=截面有效）。
# pyramid_horn（2026-09-26 ME-7）同口径：RectWGPort 解析 TE10 截面场激励，
# 端口面在波导腔空气截面内，馈电点不在导体上；端口盒含馈电段四壁金属原语。
# coax_waveguide_transition（2026-09-26 ME-6）：port2=RectWGPort（同上）+
# port1=探针基 LumpedPort 集总桥（桥盒 Face 贴腔壁内侧面/针底——集总口
# 馈电点在桥盒内非导体面，"端口悬空"判据同样不适用；端口盒含壁/针原语）。
FIELD_PORT_TEMPLATES: frozenset[str] = frozenset(
    {"slotline", "pyramid_horn", "coax_waveguide_transition",
     # ridged_wg（2026-10-02 TA 批第三批）：双 RectWGPort 打在加宽馈段——
     # 馈电点在波导空气截面内（horn 同款），端口盒含四壁金属原语
     "ridged_wg"})

# 面内缩 MSL 端口模板（2026-09-18 w1b；H4 教训：MSLPort 段⊂PML_8 致非物理，
# 槽线过渡/巴伦有意把端口段内移 14·BASE）。判据改：端口面严格在域内、且含
# 馈电点的金属原语沿端口轴延伸到域边界（馈线到板边=无开路 stub，#174）。
INSET_PORT_TEMPLATES: frozenset[str] = frozenset({"msl_slot_transition",
                                                  "marchand_balun"})

# 域边贴界 MSL 端口模板（2026-09-24 df6 A2）：矩形域 DOM_Y 字面≠BOARD 的
# 模板，MSLPort 面=域边界=PML 面（mline"端口面贴板边"口径的矩形域变体）。
# sicl（2026-10-02 TA 批第二批）同口径：双 StripLinePort 面贴 ±DOM_Y 域边界
# （矩形域 DOM_X/DOM_Y 字面注入，siw 族机制同源）。
EDGE_PORT_TEMPLATES: frozenset[str] = frozenset({"msl_siw_taper", "sicl"})

# 全口径集总电阻片端口模板（2026-09-24 df6 DP-10 §MS_METASURFACE）：波导
# 模拟器 TEM 馈——LumpedPort 全口径片（exc_dir=x，R=η0），浮于空气区，
# 与屏/贴片金属 DC 隔离（容性馈）。审计③"馈电点在导体上"判据不适用，
# 改查：片端口 LumpedElement 与金属原语无 bbox 接触（短路即红）+ 模板
# 有独立金属网络（屏/贴片）。
SHEET_PORT_TEMPLATES: frozenset[str] = frozenset({"ms_patch", "ms_cross",
                                                  "ms_jcross",
                                                  "ms_ring_patch"})

# 无端口模板（2026-09-24 df6 DP-10）：软平面照明散射体（ms_array_NxN）——
# openEMS 无 TF/SF 平面波，用 exc_type=0 软激励平面 + nf2ff 盒替代（官方
# PPW 教程口径）。审计②无端口对象，改查软激励平面与 nf2ff 盒存在；
# 审计③无端口连通性，改查金属分量数与 BC 地连续。
PORTLESS_TEMPLATES: frozenset[str] = frozenset({"ms_array_NxN"})

# 矩形域/模板参数基板模板（2026-09-18 w1b）：域 x/y 半宽不同（DOM_HI/Y_HALF/
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
                                                   "ms_ring_patch",
                                                   # §COIL_NFC（df7 C10b）：线圈
                                                   # 矩形域 + FR4 类模板参数基板
                                                   "coil_nfc",
                                                   # §MMWAVE_SERIES_ARRAY（df7
                                                   # C10d）：方域 + RO3003 类
                                                   # 模板参数基板（78GHz 毫米波板）
                                                   "mmwave_series_array",
                                                   # §ME-7 pyramid_horn（2026
                                                   # -09-26）：矩形域 DOM_X/Y/Z
                                                   # 字面 + 模板参数 er（空气填
                                                   # 充；h_mm=0.0 占位键见段头）
                                                   "pyramid_horn",
                                                   # §ME-6 coax_waveguide_
                                                   # transition（2026-09-26）：
                                                   # 矩形域 DOM_X/DOM_Y 字面 +
                                                   # er=1.0/h_mm=0.0 占位键（同
                                                   # pyramid_horn 口径）
                                                   "coax_waveguide_transition",
                                                   # sicl（2026-10-02 TA 批
                                                   # 第二批）：矩形域 DOM_X/
                                                   # DOM_Y 字面 + 模板参数基板
                                                   # （nominal h_mm=腔高 b）
                                                   "sicl",
                                                   # ridged_wg（2026-10-02
                                                   # TA 批第三批）：矩形域
                                                   # DOM_X/DOM_Y/DOM_Z 字面 +
                                                   # er=1.0/h_mm=0.0 占位键
                                                   # （horn 同口径）
                                                   "ridged_wg",
                                                   # hmsiw（2026-10-03 ge8b
                                                   # WA 席 1）：矩形域 DOM_X/
                                                   # DOM_Y 字面 + 模板参数基板
                                                   # （nominal h_mm/er，siw
                                                   # 同口径）
                                                   "hmsiw"})

# 无介质板模板：dipole=自由空间器件（官方 Helical/Dipole-SAR 口径）；
# monopole/helix=PEC 地面悬空导体（像理论口径，§10.3 C1 天线族 II
# _ANTENNA2_TALL_TEMPLATES）；loop=自由空间环（2026-09-16 改造：无板无地、底
# MUR，_ANTENNA2_FREE_SPACE_TEMPLATES）——审计④"恰一块全板基板"对其改判
# "零介质原语"。
# pyramid_horn（2026-09-26 ME-7）：全金属空气填充波导器件（RectWGPort 解析
# β 按 C0 真空口径，无介质原语；同登 RECT_DOMAIN——er=1.0/h_mm=0.0 走模板
# 参数口径，见 MATERIAL_VALUE_PARAMS 豁免）。
NO_SUBSTRATE_TEMPLATES: frozenset[str] = frozenset(
    {"dipole", "monopole", "helix", "loop", "pyramid_horn",
     # coax_waveguide_transition（2026-09-26 ME-6）：全金属空气填充波导器件
     # （RectWGPort 解析 β 按 C0 真空口径，无介质原语；同登 RECT_DOMAIN）
     "coax_waveguide_transition",
     # ridged_wg（2026-10-02 TA 批第三批）：全金属空气填充波导器件（同上）
     "ridged_wg"})

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
    # varactor_bpf（M-5，2026-09-27）：cj0_pf/phi_v/bias_v 只进 LumpedElement
    # 的 C 字面量（C=Cj0/√(1+V/φ) 在 bias_v 处的静态值，core/varactor.py
    # 闭式），导体盒签名不随之变化——不是漂移；字面量接线由
    # test_varactor_bpf_template 钉住（脚本含 VAR_C=<值>，且导体签名对
    # 三键扰动不变）
    "varactor_bpf": frozenset({"cj0_pf", "phi_v", "bias_v"}),
    # §MMWAVE_SERIES_ARRAY（df7 C10d）：load_r_ohm 是链末端接集总电阻值
    # （LumpedElement R 值，与渲染脚本 LOAD_R 字面量同源消费），导体盒签名
    # 不随之变化——不是漂移；字面量接线由 test_mmwave_series_array_template 钉
    "mmwave_series_array": frozenset({"load_r_ohm"}),
    # qwt_multisection（2026-10-02 TA 批）：z_load_ohm 是末端端接集总电阻值
    # （LumpedElement R=ZL，atten_pi 电阻值同口径），导体盒签名不随之变化
    # ——不是漂移；字面量接线由 test_schiffman_qwt_templates 钉
    "qwt_multisection": frozenset({"z_load_ohm"}),
    # nway_wilkinson（2026-10-02 TA 批第二批）：iso_r_ohm 是隔离电阻值
    # （LumpedElement R=2·Z0，qwt z_load_ohm 同口径），导体盒签名不随之
    # 变化——不是漂移；字面量接线由 test_sicl_nway_templates 钉
    "nway_wilkinson": frozenset({"iso_r_ohm"}),
    # diplexer（2026-10-02 TA 批第三批）：l_lpf_nh/c_hpf_pf 是一阶 CR 对
    # 集总元件值（LumpedElement L=/C= 字面量，内核 element_values 同源
    # 消费），导体盒签名不随之变化——不是漂移；字面量接线由
    # test_diplexer_ridged_templates 钉
    "diplexer": frozenset({"l_lpf_nh", "c_hpf_pf"}),
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
    # meta.yaml nominal_params 键集一致由 test_template_meta_consistency 钉，b55acc8）。
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
    # ms_ring_patch（ge5 段③）：tan_d 只进基板材料；er 进环几何闭式
    # （εeff=(1+εr)/2 → void/ring_w/ring_outer 随 er）——er 驱动导体不需豁免
    "ms_ring_patch": frozenset({"tan_d"}),
    "ms_array_NxN": frozenset({"er", "tan_d"}),
    # §COIL_NFC（df7 C10b）：er/tan_d 只进基板材料属性（slotline/siw 同口径）；
    # h_mm 是几何驱动参数经基板盒/金属面 z 消费，不需豁免
    "coil_nfc": frozenset({"er", "tan_d"}),
    # §MMWAVE_SERIES_ARRAY（df7 C10d）：er/tan_d 只进基板材料属性（同 coil_nfc
    # 口径，RO3003 类毫米波板）；h_mm/几何键经基板盒/金属面 z 消费，不需豁免
    "mmwave_series_array": frozenset({"er", "tan_d"}),
    # §ME-7 pyramid_horn（2026-09-26）：er=1.0 只进渲染脚本 summary 的 TE10
    # 截止/波导波长闭式回显（空气填充；RectWGPort 解析 β 本按 C0 真空口径），
    # h_mm=0.0 为无介质板器件占位键（审计④ RECT 域分支要求 nominal 有键）——
    # 二者均不动导体几何，字面量接线由 test_pyramid_horn_template 钉住
    # （脚本含 ER=1.0 常量与 summary fc_te10/lambda_g 字段）
    "pyramid_horn": frozenset({"er", "h_mm"}),
    # §ME-6 coax_waveguide_transition（2026-09-26）：同 pyramid_horn 口径
    # （er 只进渲染脚本 summary TE10 回显；h_mm=0.0 占位键；test_coax_wg_
    # template 钉字面量接线）
    "coax_waveguide_transition": frozenset({"er", "h_mm"}),
    # sicl（2026-10-02 TA 批第二批）：er/tan_d 只进基板材料属性（slotline/siw
    # 同口径）；h_mm 是腔高（几何驱动：上下地板 z/条带中面 z 随动，不需豁免）；
    # w 的 Z0 联动仅在名义设计点（sicl_design_params），渲染期 er 扰动不改导体
    "sicl": frozenset({"er", "tan_d"}),
    # ridged_wg（2026-10-02 TA 批第三批）：er=1.0 只进渲染脚本 summary 的
    # 回显（空气填充；RectWGPort 解析 β 本按 C0 真空口径），h_mm=0.0 为
    # 无介质板器件占位键（审计④ RECT 域分支要求 nominal 有键）——二者均
    # 不动导体几何，pyramid_horn 同口径，字面量接线由
    # test_diplexer_ridged_templates 钉住
    "ridged_wg": frozenset({"er", "h_mm"}),
    # hmsiw/inverted_ms/fgcpw（2026-10-03 ge8b WA 席 1）：er/tan_d 只进基板
    # 材料属性（siw/slotline 同口径）。hmsiw 的 h_mm 是几何驱动参数（板/端口
    # 盒/藩篱 z 经 hmsiw_layout 消费）不需豁免；inverted_ms/fgcpw 的 h_mm 为
    # 对账占位键（与 substrate.h_mm 同值一致性由 test_ta_wave_a_templates 正面
    # 钉；渲染基板厚走 substrate——pyramid_horn h_mm=0.0 占位键同口径）
    "hmsiw": frozenset({"er", "tan_d"}),
    "inverted_ms": frozenset({"er", "tan_d", "h_mm", "h_sub_mm"}),
    "fgcpw": frozenset({"er", "tan_d", "h_mm"}),
    # isl_shielded/vivaldi_tsa（2026-10-03 ge8b WB 席 B9）：er/tan_d 只进基
    # 板材料属性（siw/slotline 同口径）；几何键（w/g_air/h_top/d/s/line_len、
    # w_throat/w_mouth/l/feed_w）全部驱动导体不需豁免
    "isl_shielded": frozenset({"er", "tan_d"}),
    "vivaldi_tsa": frozenset({"er", "tan_d"}),
    # embedded_ms（2026-10-03 ge8d WD 席 D2）：er/tan_d 只进基板材料属性；
    # h_mm 为对账占位键（渲染基板厚走 substrate，同 inverted_ms 口径）
    "embedded_ms": frozenset({"er", "tan_d", "h_mm"}),
    # xcheb_bpf4（同批）：er/tan_d 只进基板材料属性；h_mm 为对账占位键
    # （fgcpw 同口径）；几何键（w/a/g12/g23/g34/g14/g_open/g_pos/tap_t）
    # 全部驱动导体不需豁免
    "xcheb_bpf4": frozenset({"er", "tan_d", "h_mm"}),
}

# 域/读出单驱动参数（2026-10-01 ge5 ms_cross 收尾批，runs/ge5_msfam/
# criteria.md §0/§1）：声明键不驱动导体原语、但驱动单胞域（DOM_*）与读出
# 探针面（_portN start/stop）。ms_cross 的导体（十字臂）严格内含于胞
# （2·arm<period）；读出修复（全口径电阻片→soft plane+探针垫片）删除了
# 电阻片 bbox 后 period_mm 不再经导体签名体现——豁免的同时以正面判据补偿
# 钉住（test_metasurface_templates.py::
# test_ms_cross_period_drives_domain_and_probes：扰动 period 实测域与探针
# 面随动）。语义独立于 KNOWN_METADATA_DRIFT（那是元数据漂移登记，不是
# 几何驱动面的声明）。
DOMAIN_DRIVEN_PARAMS: dict[str, frozenset[str]] = {
    "ms_cross": frozenset({"period_mm"}),
    # ms_patch 同口径（2026-10-01 ge5 J2 fallback 段①，runs/ge5_j2fb）：
    # 读出修复删电阻片 bbox 后 period_mm 不再驱动导体（贴片 px/py、读出面
    # 均只随 px/λ0），单胞域 DOM_* 仍随 period——豁免+正面补偿钉
    # test_metasurface_templates.py::test_ms_patch_period_drives_domain。
    "ms_patch": frozenset({"period_mm"}),
    # ms_ring_patch（ge5 段③）：同 ms_patch 反射读出族口径——period 只驱动
    # 单胞域（环几何=λ0 闭式派生、贴片随 patch_px），正面补偿钉同族
    # test_ms_patch_period_drives_domain 的参数化扩展。
    "ms_ring_patch": frozenset({"period_mm"}),
    # embedded_ms（2026-10-03 ge8d WD 席 D2）：h2_mm（覆盖层厚）驱动介质盒
    # 上沿与 z 网格（Material 原语），导体签名不变——豁免+正面补偿钉
    # test_ta_wave_c_templates.py::test_embedded_ms_h2_drives_dielectric
    # （扰动 h2 实测介质盒顶随动）。
    "embedded_ms": frozenset({"h2_mm"}),
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
# 历史条目 patch/feed_w_mm（幽灵参数，无消费者）已随 0aq 修复清空——
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
    # varactor_bpf（M-5）：hairpin 同族布局，τ∈(0,0.5) 域守卫同款；
    # arm_len ×1.37 无碍（变容管装载臂短，31.67×1.37=43.4mm 仍在板内）
    "varactor_bpf": {"tap_frac": (0.9, 0.0)},
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
    # ms_ring_patch（ge5 段③）：patch_px ×1.37=11.71 使贴片-环内缘缝
    # 0.139mm<3·NEAR(0.3)（"环-贴片/环-胞缝"守卫拒渲染——守卫是正确行为）；
    # ×0.9 缩小保域（缝 2.15mm）且必变几何
    "ms_ring_patch": {"patch_px_mm": (0.9, 0.013)},
    # ridged_wg（2026-10-02 TA 批第三批）：d_mm ×1.37 使 g/b=0.253<0.4
    # （"深脊拒渲染"XC-P 精度域守卫拒——守卫是正确行为）；×0.9 保域
    # （g/b=0.509≥0.4）且必变几何。a_mm ×1.37 使外廓 TE10（4.79GHz）跌破
    # 判读带顶（5.45）——"判读带单模域"守卫拒（守卫是正确行为）；×0.9
    # 抬高外廓截止（7.29GHz）保域且必变几何
    "ridged_wg": {"d_mm": (0.9, 0.0), "a_mm": (0.9, 0.013)},
    # hmsiw（2026-10-03 ge8b WA 席 1）：s_mm ×1.37 越泄漏上界 s≤2d
    # （1.383>2×0.6，siw_check_design_rules 拒——守卫是正确行为，siw 同款）；
    # ×1.1 保域（1.1≤1.2）且必变几何。d_mm ×1.37=0.835 后孔间缝 0.165>
    # NEAR(0.1) 仍过守卫，不需覆盖
    "hmsiw": {"s_mm": (1.1, 0.0)},
    # xcheb_bpf4（2026-10-03 ge8d WD 席 D2）：tap_t_mm ×1.37=11.18mm 超环边
    # 段长 a=8.7626（抽头位越左边段守卫拒渲染——守卫是正确行为）；×0.9
    # 保域（7.33 < 8.76）且必变几何
    "xcheb_bpf4": {"tap_t_mm": (0.9, 0.0)},
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

    B6 stage-2 扩（2026-09-15 实测）：CSPrimPolygon(7)/CSPrimLinPoly(8)
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
    DOM_HI（x）/Y_HALF（y）（2026-09-18 w1b 注册）。"""
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
    feed_offset_mm 曾只在 docs meta.yaml 的 nominal_params 里，0aq 修复后
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
