"""openEMS simulation templates.

Templates: wilkinson, patch, branchline, dipole, stepped_impedance, coupled_line.
Each template renders CSXCAD scripts for openEMS Python bindings.
每模板元数据（仿真时长/网格/S 参数提取点）见 TEMPLATE_META / template_meta()——
方向 2 参数化公约（Plan §3：防 6 个模板 6 种风格）。

网格/边界方法学（2026-09-04 频率尺度根因实验后重写，对照官方 MSL_NotchFilter
教程基线，证据链 runs/audit_freq_scale/ E1-E4）：
- 网格 base = 基板内波长 λ_sub/50（官方口径），近走线区 base/4；
  旧版 λ/20@空气 ≈4.3mm 粗网格导致谷位系统性低 30-40% 且随网格漂移；
- 地面 = z-min PEC 边界（官方口径），基板延伸到侧边界（旧版有限小板
  + 70mm 空气隙引入板边衍射）；
- z 轴翻转：基板 z∈[0,H]，金属在 z=H 顶面（官方同款）；
- 端口 FeedShift=10×NEAR、MeasPlaneShift=端口段长/3（官方口径）；
- NrTS=100000 不设 EndCriteria（官方口径；默认能量判据自动停机）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np


@dataclass
class TemplateResult:
    template: str
    params: dict[str, Any]
    script: str
    csv_name: str = "sparams.csv"


# Default substrate: Rogers 4350B 0.508mm
# rogers4350b 数据表：er=3.66 @10GHz，tanδ=0.0037（带损耗基板——无损耗基板
# Q 虚高且不符合真实板材；损耗对谐振频率影响 ~0.1% 量级，E4 已验证无碍）
_DEFAULT_SUB = {"er": 3.66, "h_mm": 0.508, "tan_d": 0.0037}

# 基板 z 向格数缺省（render_script `_sub_cells` 旋钮的缺省档，G3 2026-09-22）：
# 非族模板维持官方 substrate_cells=4（旧口径逐字节不变）；CPW/槽下场族生产
# 缺省抬到 8——依据 msl_cpw zconv 定案实验（runs/msl_cpw_zconv，2026-09-20
# 预声明判据先写后跑）：β2 偏差 dev −2.151→−0.971→−0.474pp（sub4→8→16），
# verdict=GRID_UNDERRES(份额归网格, 78%)+SATURATED_RESIDUAL，sub8 即回
# msl_cpw_benchmark_verdict ±2% 锚门内（kernel PASS 五门全过）——z 向基板
# 分层（127µm 格 vs CPW 槽下场竖直尺度 h/π≈0.162mm）是该族 ZL/εeff 的
# 分辨限制项（#313 z 向地板项）。显式传 _sub_cells 仍最高优先。
_SUB_CELLS_DEFAULT = 4
#: 族内模板（同构证据口径）：
#: - msl_cpw：zconv 直接证据（上述定案实验即在本模板实测）。
#: - cpw：与 zconv 实测 CPW 段同构——同名义线（w=0.849/gap=0.2，50Ω CPWG
#:   _cpwg_ri 口径）、同叠层（rogers4350b h=0.508 底 PEC）、同一闭式参考
#:   （εeff≈2.56729）、同一 z 块消费路径（微带族 else 分支 _sub_pts）。
_SUB_CELLS_8_TEMPLATES: frozenset[str] = frozenset({"msl_cpw", "cpw"})

# 模板元数据公约（方向 2 验收：每模板 meta——仿真时长/网格数/S 参数提取点/端口）
TEMPLATE_META: dict[str, dict[str, Any]] = {
    "wilkinson": {
        "f0_ghz": 2.5, "n_ports": 3,
        "extraction": "S11/S21/S31/S23 @ MSLPort 1-3（S23 双激励第二 run）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["series_w_mm", "shunt_w_mm", "arm_len_mm"],
        "topology": "T型分叉 + 双 λ/4 臂（x 向并列）+ 100Ω 隔离电阻（LumpedElement）",
        "param_semantics": "series_w_mm=70.7Ω 臂宽（窄），shunt_w_mm=50Ω 馈线宽（宽）"
        "，arm_len_mm=λ/4 臂长——对齐 recipe/HFSS/fake 口径（2026-09-04 统一）",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50"
        "（官方口径，近走线区自动 /4）",
    },
    "patch": {
        "f0_ghz": 2.4, "n_ports": 1, "extraction": "S11 @ MSLPort 1（单端口回退）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["patch_len_mm", "patch_w_mm", "feed_offset_mm"],
        "topology": "矩形贴片（patch_len = 谐振 λ/2 轴，沿 x）+ 50Ω 底馈探针"
                    "（LumpedPort，x=-feed_offset 官方口径）",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4（guided 模板 5mm）",
        "param_semantics": "patch_len_mm=谐振 λ/2 轴长，patch_w_mm=贴片宽度"
        "（非谐振轴，影响 εeff/匹配），feed_offset_mm=底馈探针沿谐振轴距"
        "中心偏置（渲染 _patch_lines/geometry_spec/LumpedPort 三处实读，"
        "决定馈电匹配深度；fake/schema 同名同语义）。历史漂移修正（0aq）："
        "原声明的 feed_w_mm 为幽灵参数（无任何消费者），已替换为真实参数",
    },
    "branchline": {
        "f0_ghz": 2.4, "n_ports": 4,
        "extraction": "S11/S21/S31/S41 @ MSLPort 1-4（单激励 9 列 CSV；整 4×4 由 "
        "excite_port=1..4 进程隔离轮转装配 → .s4p，#208；2026-09-16 前 port4 为 "
        "PML 端接不提取）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["arm_len_mm", "series_w_mm", "shunt_w_mm"],
        "mesh_note": "x/y 双轴有端口面 → 双轴 PML",
        "topology": "标准角馈 branchline：正方形环（横臂 series_w=35.35Ω、"
        "竖臂 shunt_w=50Ω，各 λ/4）+ 四角 50Ω 馈线至端口面；四端全为 MSLPort"
        "（port4 隔离端 2026-09-16 起由 PML 端接升级为真端口，端口面贴板边）",
        "param_semantics": "series_w_mm=横臂（串联臂，1↔2 / 4↔3）35.35Ω，"
        "shunt_w_mm=竖臂（并联臂）50Ω，arm_len_mm=环边长 λ/4——"
        "2026-09-05 对照 Microwaves101/PMC 口径修正（旧版横竖阻抗反置+"
        "臂中点馈电+隔离端悬空，三处结构性错误）",
    },
    "dipole": {
        "f0_ghz": 2.4, "n_ports": 1, "extraction": "S11 @ LumpedPort 1（自由空间半波振子，#194 官方口径重写）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["dipole_len_mm", "dipole_w_mm", "gap_mm"],
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4",
        "param_semantics": "dipole_len_mm=谐振全臂长（λ/2 闭式 L=c/2f0），dipole_w_mm=臂宽，"
        "gap_mm=中央馈电间隙",
    },
    "stepped_impedance": {
        "f0_ghz": 2.4, "n_ports": 2, "extraction": "S11/S21 @ MSLPort 1-2（带通形状）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": 5,
        "params": ["z1_width_mm", "z2_width_mm", "seg_len_mm", "n_segments"],
        "mesh_note": "分段 junction 处 y 向 near 加密",
        "param_semantics": "z1_width_mm=低阻段宽（交替起点），z2_width_mm=高阻段宽，"
        "seg_len_mm=单段长度，n_segments=段数",
    },
    "coupled_line": {
        "f0_ghz": 2.4, "n_ports": 3, "extraction": "S11/S21/S31 @ MSLPort 1-3（耦合度）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["coupled_len_mm", "line_w_mm", "gap_mm"],
        "mesh_note": "耦合缝 x 向 near 加密",
        "param_semantics": "coupled_len_mm=耦合段长（λ/4），line_w_mm=单线宽，"
        "gap_mm=耦合缝宽",
    },
    "mline": {
        "f0_ghz": 2.5, "n_ports": 2,
        "extraction": "S11/S21 @ MSLPort 1-2（均匀线：S21 相位斜率→εeff，"
        "β 金标准 #162；|S11| 显著非零=端口/网格判废信号）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["w_mm", "line_len_mm"],
        "topology": "均匀微带线（锚模板，WP2.1：校准件+引擎仲裁探针+数据工厂，"
        "单点秒-分钟级）",
        "param_semantics": "w_mm=线宽（Z0 由 skrf HJ 综合定：50Ω@rogers4350b"
        "=1.113mm），line_len_mm=两端口间线长",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50"
        "（官方口径）；线缘 x 向 + 端口 junction y 向 near 加密",
    },
    "cpw": {
        "f0_ghz": 2.5, "n_ports": 2,
        "extraction": "S11/S21 @ CPWPort 1-2（均匀共面线：S21 相位斜率→εeff）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["w_mm", "gap_mm", "line_len_mm"],
        "topology": "均匀共面波导（锚族：中心带+两侧地，地延伸到域边；"
        "CPWPort 一等端口，gap_width 口径）",
        "param_semantics": "w_mm=中心带宽（Z0 由 CPWG 共形映射闭式综合定："
        "50Ω@rogers4350b gap=0.2 → w=0.849mm，#198 参照系修正——openEMS "
        "官方口径底面强制地，实际结构即 CPWG），gap_mm=缝宽，"
        "line_len_mm=两端口间线长",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
        "带缘+地内缘（缝两侧）x 向 near 加密",
    },
    "stripline": {
        "f0_ghz": 2.5, "n_ports": 2,
        "extraction": "S11/S21 @ StripLinePort 1-2（对称带状线：TEM，εeff=εr）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["w_mm", "line_len_mm"],
        "topology": "对称带状线（锚族：中心带 z=中面，上下地=域 PEC 边界；"
        "StripLinePort 一等端口，height=带-地半高口径）",
        "param_semantics": "w_mm=中心带宽（零厚度对称闭式综合：50Ω@"
        "rogers4350b 双板 b=1.016 → w=0.5554mm），line_len_mm=两端口间线长",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
        "带缘 x 向 + 中面 z 向精确入网（#198 激励体积教训）",
    },
    "cps": {
        "f0_ghz": 2.5, "n_ports": 2,
        "extraction": "S11/S21 @ LumpedPort 1-2（共面带差分直馈，R=闭式 Z0：带内"
        "|S11| 深谷=Z0 锚；εeff 锚=S21 解缠相位斜率——LumpedPort 无 β 属性，"
        "β 金标准不可用，如实降级）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["w_mm", "gap_mm", "line_len_mm"],
        "topology": "共面带 CPS（C9 传输线族 II：两条等宽带并行，中央缝，无地——"
        "基板下方空气，底界 MUR + 域向下延 AIR_TOP；两端 LumpedPort 跨缝差分"
        "馈/端接，端口在域内 → 侧界全 MUR；线沿 y）",
        "param_semantics": "w_mm=单带宽（Z0 由 CPS 无地共形闭式综合定：120Ω@"
        "rogers4350b gap=0.5 → w=2.95mm，refs §11；印制 CPS 天然高阻，50Ω 需"
        "亚 0.1mm 缝不可制造），gap_mm=两带间缝宽，line_len_mm=两端口间线长",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
        "四条带缘 x 向精确入网 + 缝中线加密 + 线两端（LumpedPort 面）y 向精确"
        "入网（#198）",
    },
    "suspended_stripline": {
        "f0_ghz": 2.5, "n_ports": 2,
        "extraction": "S11/S21 @ StripLinePort 1-2（悬置带线：β 金标准→εeff 对照"
        "共形电容比闭式，|Δεeff|≤2% 口径同 stripline）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["w_mm", "b_mm", "line_len_mm"],
        "topology": "悬置带线（C9 传输线族 II：腔高 b 上下地=域 z 边界 PEC，零厚度"
        "带在中面 z=b/2，厚 H_SUB 基板以带为中面对称悬浮 z∈[b/2−H_SUB/2, "
        "b/2+H_SUB/2]，两侧空气隙各 (b−H_SUB)/2；StripLinePort height=b/2）",
        "param_semantics": "w_mm=中心带宽（悬置闭式综合：50Ω@rogers4350b h=0.508 "
        "b=1.016 → w=0.9058mm，εeff=2.001；FD 重定标批 2026-09-18，旧 q 式口径 "
        "w=0.731/εeff=2.641 撤），b_mm=两地面间距/腔高（基板厚恒"
        "=H_SUB 0.508，b>1.37·H_SUB 保扰动域），line_len_mm=两端口间线长",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
        "带缘 x 向 + 基板两面/中面/壳边 z 向精确入网（#198）",
    },
    "wstep": {
        "f0_ghz": 2.5, "n_ports": 2,
        "extraction": "S11/S21 @ MSLPort 1-2（单阶跃两段线：锚=skrf 级联 HJ 闭式裁判）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["w1_mm", "w2_mm", "line_len_mm"],
        "topology": "微带宽度阶跃（WP2.2 不连续性基元：窄段/宽段各半长，"
        "单阶梯跃在中点；区别于 stepped_impedance 多段谐振器）",
        "param_semantics": "w1_mm=窄段线宽（50Ω 口径），w2_mm=宽段线宽"
        "（35Ω 口径），line_len_mm=总长（阶跃在中点，两段各半）",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
        "两段带缘 x 向精确入网（#198）",
    },
    "tjunc": {
        "f0_ghz": 2.5, "n_ports": 3,
        "extraction": "S11/S21/S31/S23 @ MSLPort 1-3（对称 T 结：均分+隔离，"
        "锚=skrf 理想三端口结点+HJ 线裁判）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["w_feed_mm", "through_len_mm", "branch_len_mm"],
        "topology": "微带 T 接头（WP2.2 不连续性基元：主线沿 y 两端端口，"
        "支臂沿 x 第三端口；全臂同宽 50Ω 对称均分口径）",
        "param_semantics": "w_feed_mm=全臂统一线宽（50Ω），through_len_mm="
        "主线总长（端口1/2 至结点），branch_len_mm=支臂长（结点至端口3）",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
        "三臂带缘+结点角精确入网（#198）",
    },
    "bend": {
        "f0_ghz": 2.5, "n_ports": 2,
        "extraction": "S11/S21 @ MSLPort 1-2（直角弯折：锚=|S11|<-15dB 绝对门"
        "+β 金标准；裁判=理想级联）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["w_mm", "arm_len_mm"],
        "topology": "微带直角弯折（WP2.2 不连续性基元：L 形两臂各 arm_len，"
        "未切角标准口径；切角/mitered 为后续变体）",
        "param_semantics": "w_mm=全臂统一线宽（50Ω），arm_len_mm=每臂长"
        "（角到端口面）",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
        "两臂带缘+弯角精确入网（#198）",
    },
    "via": {
        "f0_ghz": 2.5, "n_ports": 2,
        "extraction": "S11/S21 @ MSLPort 1-2（双层板过孔过渡：顶层带→过孔柱→"
        "底层带，穿内层地方反焊盘；β 金标准+|S11|<-10dB 绝对门）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["w_mm", "antipad_mm", "r_via_mm"],
        "topology": "过孔过渡（WP2.2 不连续性基元收官：双层板 z∈[0,2H]，"
        "内层地方 sheet z=H 带方反焊盘，过孔柱 r_via 穿孔连接顶/底带）",
        "param_semantics": "w_mm=顶/底带统一线宽（50Ω@每层 H），antipad_mm="
        "方反焊盘半边长（同轴口径 Z≈(60/√εr)ln(r_pad/r_via)），r_via_mm="
        "过孔柱半径",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
        "带缘+反焊盘方边精确入网（#198）；过孔柱阶梯化口径（r≪cell 不加线）",
    },
    "atten_pi": {
        "f0_ghz": 2.5, "n_ports": 2,
        "extraction": "S11/S21 @ MSLPort 1-2（π 型电阻衰减器：|S21|≈-A dB 平坦，"
        "锚=ABCD 电阻网络闭式裁判+E4 attenuator_pi 同源）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["atten_db", "w_mm", "shunt_off_mm"],
        "topology": "π 型衰减器（WP2.3 Tier 1 首族：串臂 LumpedElement 桥接"
        "中点断口，两端对地 shunt LumpedElement 经短柱接 z-min PEC 地）",
        "param_semantics": "atten_db=目标衰减（电阻值由 E4 attenuator_pi "
        "ABCD 闭式给出），w_mm=馈线宽（50Ω），shunt_off_mm=shunt 离中点距离",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
        "带缘+串臂断口+shunt 盒边精确入网（#198）",
    },
    "atten_t": {
        "f0_ghz": 2.5, "n_ports": 2,
        "extraction": "S11/S21 @ MSLPort 1-2（T 型电阻衰减器：|S21|≈-A dB 平坦，"
        "锚=ABCD 电阻网络闭式裁判+E4 attenuator_t 同源）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["atten_db", "w_mm", "shunt_off_mm"],
        "topology": "T 型衰减器（WP2.3 横向变体：两臂串 LumpedElement 桥接"
        "±d 断口，中点对地 shunt LumpedElement 全带宽短柱）",
        "param_semantics": "atten_db=目标衰减（电阻值由 E4 attenuator_t "
        "ABCD 闭式给出），w_mm=馈线宽（50Ω），shunt_off_mm=串臂离中点距离",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
        "带缘+串臂断口+shunt 盒边精确入网（#198）",
    },
    "ratrace": {
        "f0_ghz": 2.5, "n_ports": 4,
        "extraction": "全 S 矩阵 4×4 @ .s4p（官方激励轮转 4 run：SetEnabled "
        "逐端口激励+匹配终端探针；skrf Touchstone 主路，CSV 降兼容）。"
        "裁判=理想 180° 混合环 S 矩阵闭式（#208 Y 矩阵推导）：Σ 均分 -3dB "
        "同相、Δ 隔离、out1↔out2 互隔离",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["w_ring_mm", "w_feed_mm"],
        "topology": "rat-race 环形电桥（WP2.3：环周长 1.5λg@70.7Ω，arcs "
        "λ/4×3+3λ/4；规范角位 Σ=0°/out1=60°/Δ=120°/out2=300°——out1/out2 "
        "分居 Σ 两侧 λ/4，大弧 3λ/4 扫 Δ→out2 之间（pt5 实测定版）——三端口挤 "
        "上半区，下半区是大弧；out1/Δ 径向馈+弯折竖直引出）",
        "param_semantics": "w_ring_mm=环线宽（√2·Z0=70.7Ω 口径），"
        "w_feed_mm=四端口馈线宽（50Ω）",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
        "环带逐网格行栅格化（零 #198 台阶误差）+ 馈线带缘精确入网；渲染半径 "
        "= 物理 R / k(BASE)（ratrace_ring_mesh_k：0.2/0.4mm 两锚 1.0877/1.1654 "
        "对 (k−1) 幂律内插、域外 clamp；HFSS 仲裁 2.465GHz 背书 MESH_ARTIFACT；"
        "柱坐标 k=1 为根治首选 #219/#232）",
    },
    "gysel": {
        "f0_ghz": 2.5, "n_ports": 3,
        "extraction": "S11/S21/S31 @ MSLPort 1-3 + S23 第二激励（输出互隔离，"
        "标准双激励 footer 同 wilkinson）。裁判=理想 Gysel 环 S 闭式"
        "（#206 纪律理论核验轮，skrf 六段线+双负载装配 @f0）：均分 -3.01dB "
        "同相、全端口匹配、P2↔P3 互隔离",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["w_arm_mm", "w_feed_mm", "arm_len_mm", "iso_len_mm"],
        "topology": "Gysel 高隔离功分器（WP2.3 横向变体，1975 六节 λ/4 环，P2⑪ "
        "L-jog 等长拓扑重设计 2026-09-16）：P1—70.7Ω λ/4 臂—P2/P3（环下边）；"
        "P2/P3—50Ω λ/4 隔离线—负载节点 Δ1/Δ2：竖直段 YJ=iso_len−jog 后顶端 "
        "L-jog 横移 jog=|arm_len−iso_len| 到 x=±iso_len（竖直+横移=iso_len 保 "
        "λ/4 电长度）；Δ1—50Ω λ/2 桥带—Δ2（顶边，跨度 2·iso_len=λ/2 精确，"
        "中点开路=第 6 节点）；Δ1/Δ2 各接 50Ω LumpedElement 端接（大功率意义："
        "隔离负载外置不贴片）。桥带是隔离的必要环节——无桥带的朴素直读拓扑 "
        "skrf 验证 FAIL（S21=-6.5dB/S11=-9.5dB）。矩形旧版（Δ 在角部、桥带继承 "
        "2·arm_len）为历史口径，见 param_semantics。可选 `_jog_miter_mm` 切角"
        "旋钮（C7 mitered-jog 变体 2026-09-21：两侧 jog 转角外上角 c×c 台阶缺口，"
        "削减未切角 90° 弯折的弯角寄生；0=未切角缺省、渲染逐字节不变；"
        "opt-in 旋钮不入参数表，与 _end_criteria/_sub_cells 先例同构）",
        "param_semantics": "w_arm_mm=70.7Ω 臂宽（√2·Z0，skrf HJ 精算"
        " 0.6035mm），w_feed_mm=50Ω 馈线/隔离线/桥带宽（1.1134mm），"
        "arm_len_mm=臂 λ/4（εeff=2.7246 → 18.162mm@2.5GHz），iso_len_mm="
        "隔离线 λ/4（50Ω εeff=2.8527 → 17.750mm）。派生量（不入参数表）："
        "jog=|arm_len−iso_len|=0.412mm、YJ=iso_len−jog=17.338mm、Δ 节点 "
        "x=±iso_len → 桥带跨度=2·iso_len=35.500mm=50Ω λ/2 精确（L-jog 变体"
        "口径，电路级 @f0 S32/S11 ≤-88dB 装配实测）。历史事实：矩形旧版桥带"
        "继承 2·arm_len=36.324mm，对 λ/2 有 +2.32% 二阶偏差（矩形环 2 个自由"
        "边长不能同时满足三个 λ/4 约束；#211 真跑 S32=-32.6dB PASS 实证为"
        "二阶效应；P2⑪ 离线审计电路级归因：该偏差把 @f0 S32/S11 封顶 "
        "-34.8dB，为主因，junction 台阶/双臂对称性为二阶），本变体消除之。"
        "守卫：YJ>0（arm_len<2·iso_len）否则渲染 ValueError",
        "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
        "三带缘+jog 顶边带缘+Δ 节点负载盒边精确入网（#198）；jog 横移 0.412mm "
        "≈1 网格胞（0.4mm 档），Δ 缘与竖边带缘最小间距=jog≫1µm（#152 守卫）",
    },
}

# 各模板标称设计点（与 geometry_spec/render_script 默认参数一致；
# fake vs openEMS 偏差报告与冒烟跑以此为基准点）
TEMPLATE_NOMINAL: dict[str, dict[str, Any]] = {
    # wilkinson（Ansys 官方例/Pozar §7.2 口径）：50Ω 馈线 w=1.113mm、
    # 70.7Ω λ/4 臂 w=0.604mm（skrf HJ 精算，rogers4350b h=0.508 er=3.66）、
    # 臂长 18.1mm = λ/4 @2.5GHz（εeff≈2.73, w=0.604）。
    # 2026-09-04 语义统一（对齐 recipe/HFSS/fake）：series_w_mm=臂、
    # shunt_w_mm=馈线。
    "wilkinson": {"series_w_mm": 0.604, "shunt_w_mm": 1.113, "arm_len_mm": 18.1},
    # patch: patch_len 34.9mm = λ/2 @2.4GHz（εeff≈3.11 含边缘修正）；
    # feed_offset_mm=10.0（0aq 幽灵参数修正：原 feed_w_mm 无消费者，替换为
    # 渲染实读的馈电偏置；10.0 对齐 fake_adapter/schema/docs 元件链默认，
    # LumpedPort 底馈官方口径）
    "patch": {"patch_len_mm": 34.9, "patch_w_mm": 50.0, "feed_offset_mm": 10.0},
    "branchline": {"arm_len_mm": 20.5, "series_w_mm": 1.87, "shunt_w_mm": 1.11},
    "dipole": {"dipole_len_mm": 58.0, "dipole_w_mm": 2.0, "gap_mm": 2.0},
    "stepped_impedance": {"z1_width_mm": 0.3, "z2_width_mm": 3.0, "seg_len_mm": 5.0, "n_segments": 5},
    "coupled_line": {"coupled_len_mm": 20.0, "line_w_mm": 1.0, "gap_mm": 0.5},
    # mline 锚：50Ω @rogers4350b = 1.113mm（skrf HJ 精算，权威口径表 §1）
    "mline": {"w_mm": 1.113, "line_len_mm": 40.0},
    # cpw 锚：50Ω @gap=0.2（CPWG 共形映射闭式反解，er=3.66 h=0.508；
    # εeff≈2.567。#198 参照系修正：openEMS 官方口径 z-min=PEC 强制地，
    # 实际结构是 CPWG——旧 4.035mm 是无地 skrf CPW 口径，真实 Z0=18Ω）
    "cpw": {"w_mm": 0.849, "gap_mm": 0.2, "line_len_mm": 40.0},
    # stripline 锚：50Ω @b=1.016（零厚度对称闭式，er=3.66；TEM εeff=εr）
    "stripline": {"w_mm": 0.5554, "line_len_mm": 40.0},
    # cps 锚（C9 传输线族 II）：几何 w=2.95/gap=0.5 保持（真机配对 #158，docs meta
    # 同源）；2026-09-18 FD 定标（_cps_ri γ(εr) 有效厚度，refs §11.1）后该几何内核
    # 精算 Z0≈116.2Ω/εeff≈1.676（旧裸映射口径 120Ω/1.571 撤）；印制 CPS 天然高阻，
    # 可达域下限 ≈94Ω@gap=0.5，50Ω 需亚 0.1mm 缝不可制造——100~120Ω 档口径
    "cps": {"w_mm": 2.95, "gap_mm": 0.5, "line_len_mm": 40.0},
    # suspended_stripline 锚（C9）：50Ω @b=1.016 腔、H_SUB=0.508 基板对称居中
    # （_suspended_stripline_ri 反解）。2026-09-18 FD 重定标批：q 式 softmin
    # 修正后该几何内核 w=0.9058/εeff≈2.001，FD 裁判真值 εeff≈2.025/Z0≈49.7Ω
    # （旧 q 式口径 w=0.731/εeff=2.641、FD 2.092/56.1 撤；b=1.016>1.37·H_SUB
    # 保扰动域）
    "suspended_stripline": {"w_mm": 0.9058, "b_mm": 1.016, "line_len_mm": 40.0},
    # wstep 基元：50Ω→35Ω 单阶跃（inverse_width 精算，理想 Γ=-15.1dB）
    "wstep": {"w1_mm": 1.1134, "w2_mm": 1.897, "line_len_mm": 40.0},
    # tjunc 基元：全臂 50Ω 对称均分（理想结点均分 -3.01dB 口径）
    "tjunc": {"w_feed_mm": 1.1134, "through_len_mm": 25.0,
              "branch_len_mm": 20.0},
    # bend 基元：50Ω 直角弯折（未切角；|S11| 文献口径 <-15dB @2.5GHz）
    "bend": {"w_mm": 1.1134, "arm_len_mm": 20.0},
    # via 基元：双层板过孔（反焊盘同轴口径 ≈52.5Ω，r_via=0.15）
    "via": {"w_mm": 1.1134, "antipad_mm": 0.8, "r_via_mm": 0.15},
    # atten_pi：10dB/50Ω π 型（E4 attenuator_pi 闭式；串 71.15/并 96.25）
    "atten_pi": {"atten_db": 10.0, "w_mm": 1.1134, "shunt_off_mm": 6.0},
    # atten_t 横向变体：10dB/50Ω T 型（E4 attenuator_t 闭式；
    # 串臂 25.975×2 / 中点对地 35.136）
    "atten_t": {"atten_db": 10.0, "w_mm": 1.1134, "shunt_off_mm": 6.0},
    # ratrace：环 70.7Ω（w=0.604 精算），周长 1.5λg≈109mm，R=17.35mm
    # （r_ring 入 nominal：绕过 synthesis 手写 recipe 换 f0 时半径静默
    # 错误——审查 P2-7）
    "ratrace": {"w_ring_mm": 0.604, "w_feed_mm": 1.1134,
                "r_ring_mm": 17.344},
    # gysel（#206 理论核验轮定版，inverse_width 闭式精算 @2.5GHz
    # rogers4350b h=0.508 er=3.66）：70.7Ω 臂 w=0.6035（εeff=2.7246 →
    # λ/4=18.162mm）；50Ω 馈线/隔离线 w=1.1134（εeff=2.8527 →
    # λ/4=17.750mm）。桥带=顶边继承臂跨度（电气 2·arm_len=36.324mm，
    # 对 50Ω λ/2 35.500mm 为 +2.32% 二阶偏差——矩形环拓扑固有，见
    # TEMPLATE_META param_semantics）
    "gysel": {"w_arm_mm": 0.6035, "w_feed_mm": 1.1134,
              "arm_len_mm": 18.162, "iso_len_mm": 17.75},
}

# 端口面所在轴（PML_8）；其余水平轴 MUR。z 恒为 PEC 底 + MUR 顶。
# patch 用内部 LumpedPort 底馈（官方口径），无边界端口 → 侧界全 MUR。
_TEMPLATE_PORT_AXES: dict[str, tuple[str, ...]] = {
    "wilkinson": ("y",), "patch": (), "branchline": ("x", "y"),
    "dipole": ("y",), "stepped_impedance": ("y",), "coupled_line": ("y",),
    "mline": ("y",), "cpw": ("y",), "stripline": ("y",), "wstep": ("y",),
    # C9 传输线族 II：cps 两端 LumpedPort 在域内（dipole/patch 口径）→ 侧界全
    # MUR；suspended_stripline 双 StripLinePort 在 y 边界 → 单轴 PML
    "cps": (), "suspended_stripline": ("y",),
    "tjunc": ("x", "y"), "bend": ("x", "y"), "via": ("y",),
    "atten_pi": ("y",), "atten_t": ("y",), "ratrace": ("x", "y"),
    "gysel": ("y",),
    # hairpin：两端口均在 x 边界（抽头馈线自 x=∓BOARD 引入）→ 单轴 PML
    "hairpin": ("x",),
    # hairpin_alt（交替取向变体，2026-09-18 w2g）：端口面同 hairpin → 单轴 x PML
    "hairpin_alt": ("x",),
    # coupled_bpf：两端口均在 y 边界（馈线自 y=∓BOARD 引入）→ 单轴 PML
    # （2026-09-14 起正式注册）
    "coupled_bpf": ("y",),
    # WP2.5 Tier 2 过渡结构（2026-09-16 起正式注册）：两端口均在 y 边界
    "msl_cpw": ("y",), "sma_launcher": ("y",),
    # §10.3 C1 天线族 II（2026-09-14 起正式注册）：单端口集总馈 → 侧界全 MUR
    # （patch 口径）；slot 双 MSLPort 在 y 边界 → 单轴 PML
    "monopole": (), "pifa": (), "ifa": (), "loop": (), "helix": (),
    "slot": ("y",),
    # §C3 滤波器族 II（2026-09-15 起正式注册）：双馈线同在 y=−BOARD 板边
    # （gysel 同边先例）→ 单轴 y PML
    "interdigital": ("y",), "combline": ("y",), "sir_bpf": ("y",),
    # §C4 耦合器族 II（2026-09-15 起正式注册，文末附加段）：cline_coupler/
    # lange 四端口全在 y 边界（两耦合线沿 y、馈线自 y=∓BOARD 引入）→ 单轴
    # PML；branchline_2sect 四角馈线全部沿 x 引出 → x 单轴 PML
    "cline_coupler": ("y",), "lange": ("y",), "branchline_2sect": ("x",),
    # §10.3 C2 阵列族（2026-09-15 起正式注册，文末 C2 段）：1×4/2×2 底探针集总
    # 馈 → 侧界全 MUR（patch 口径）；串馈 MSLPort 在 y=−BOARD 板边 → 单轴 y PML
    "patch_array_1x4": (), "patch_array_2x2": (), "patch_array_series": ("y",),
    # §DP-4 P3 EEP 阵列族（文末 EEP 段）：每元独立底探针集总馈（无边界端口）
    # → 侧界全 MUR（patch 口径）
    "patch_eep_2x2": (), "patch_eep_1x4": (),
    # SIW 族首族（2026-09-22 siw-family 立项，文末 SIW 段）：两端 LumpedPort z 桥
    # 在 y 域内（16·BASE 出 PML）→ 单轴 y PML；x 侧界 MUR 吸收藩篱泄漏
    "siw": ("y",),
    # SIW 族第二成员（2026-09-24 df6 A2，文末 MSL_SIW_TAPER 段）：双 MSLPort
    # 面贴 y 域边界（mline 口径）→ 单轴 y PML；x 侧界 MUR 吸收藩篱泄漏
    "msl_siw_taper": ("y",),
}

# 四端口"单激励列轮转"模板（#208 进程隔离：适配器层按 excite_port=1..4
# 渲染 4 份脚本各跑一次后装配整 4×4；渲染脚本尾部走 9 列单激励 CSV，
# 与 ratrace 同款 footer——openems_rotation.solve_smatrix_openems 通用消费）
# branchline：2026-09-16 起 port4 隔离端为真 MSLPort（四端口升级），入轮转集
_FOUR_PORT_ROTATION_TEMPLATES: tuple[str, ...] = (
    "ratrace", "branchline", "cline_coupler", "branchline_2sect", "lange",
    # §DP-4 P3 EEP 阵列族：每元独立 LumpedPort 探针 1..4，单激励轮转=EEP 集列
    "patch_eep_2x2", "patch_eep_1x4")

# 辐射器件（贴片/振子）需要 λ0/4 级空气隙；guided 结构 5mm 足够
_TEMPLATE_RADIATOR: dict[str, bool] = {
    "wilkinson": False, "patch": True, "branchline": False,
    "dipole": True, "stepped_impedance": False, "coupled_line": False,
    "mline": False, "cpw": False, "stripline": False, "wstep": False,
    # C9 传输线族 II：guided 均匀线（cps 无地但场限于带缝 ~(w+gap) 尺度，
    # 5mm 空气隙足够；suspended_stripline 全屏蔽）
    "cps": False, "suspended_stripline": False,
    "tjunc": False, "bend": False, "via": False, "atten_pi": False,
    "atten_t": False, "ratrace": False, "gysel": False,
    # hairpin：非辐射器件（WP2.3 hairpin 段；2026-09-12 起已正式注册进
    # TEMPLATE_META/TEMPLATE_NOMINAL，见文末注册块）
    "hairpin": False,
    # hairpin_alt：交替取向 hairpin，非辐射器件（同段注册，2026-09-18 w2g）
    "hairpin_alt": False,
    # coupled_bpf：非辐射器件（WP2.3 平行耦合 BPF 段；2026-09-14 起正式注册）
    "coupled_bpf": False,
    # WP2.5 Tier 2 过渡结构（2026-09-16 起正式注册）：guided 过渡；sma 域顶 =
    # 壳顶 + AIR_TOP（z 网格 sma 分支专项，非 H_SUB + AIR_TOP）
    "msl_cpw": False, "sma_launcher": False,
    # §10.3 C1 天线族 II（2026-09-14 起正式注册）：全部辐射器件（λ0/4 空气隙）
    "monopole": True, "pifa": True, "ifa": True,
    "loop": True, "helix": True, "slot": True,
    # §C3 滤波器族 II：接地棒缝耦合滤波器，非辐射器件（5mm 空气隙）
    "interdigital": False, "combline": False, "sir_bpf": False,
    # §C4 耦合器族 II：guided 耦合/分支结构，5mm 空气隙足够
    "cline_coupler": False, "lange": False, "branchline_2sect": False,
    # §10.3 C2 阵列族：贴片阵全部辐射器件（λ0/4 空气隙；nf2ff 接地分支）
    "patch_array_1x4": True, "patch_array_2x2": True, "patch_array_series": True,
    # §DP-4 P3 EEP 阵列族：辐射器件（λ0/4 空气隙；nf2ff 接地分支 + 3D 复数 dump）
    "patch_eep_2x2": True, "patch_eep_1x4": True,
    # SIW 族首族：封闭双板波导（上板=域顶 PEC），非辐射器件
    "siw": False,
    # SIW 族第二成员：MSL 锥过渡+SIW 直段（SIW 区顶壁=显式板，非辐射器件）
    "msl_siw_taper": False,
}


def template_meta(template: str) -> dict[str, Any]:
    """返回模板元数据（含公共字段）；未知模板抛 KeyError。"""
    meta = dict(TEMPLATE_META[template])
    meta["template"] = template
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(TEMPLATE_NOMINAL[template])
    return meta


def geometry_spec(
    template: str,
    params: dict[str, Any],
    substrate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Template geometry spec (mm units) for UI 3D preview."""
    substrate = substrate or _DEFAULT_SUB
    if template in SLOTLINE_FAMILY_TEMPLATES:
        # 槽线族：盒/端口清单由各 layout 单源换算（文末 SLOTLINE_FAMILY 段）
        return slotline_family_geometry_spec(template, params, substrate)
    if template in METASURFACE_TEMPLATES:
        # §MS_METASURFACE 族（文末 MS_METASURFACE 段）：盒/端口由
        # ms_geometry_spec 单源换算（ms_array_NxN 无端口 ports=[]）
        return ms_geometry_spec(template, params, substrate)
    if template in COIL_NFC_TEMPLATES:
        # §COIL_NFC（文末 COIL_NFC 段）：盒/端口由 coil_nfc_geometry_spec
        # 单源换算（单端口馈隙 LumpedPort）
        return coil_nfc_geometry_spec(params, substrate)
    if template in MMWAVE_SERIES_TEMPLATES:
        # §MMWAVE_SERIES_ARRAY（文末 MMWAVE_SERIES_ARRAY 段）：盒/端口由
        # mmwave_series_geometry_spec 单源换算（单端口 MSLPort 行波串馈）
        return mmwave_series_geometry_spec(params, substrate)
    h = float(substrate["h_mm"])
    boxes: list[dict[str, Any]] = [
        {"name": "substrate", "material": "substrate",
         "start_mm": [-60.0, -60.0, 0.0], "stop_mm": [60.0, 60.0, h]},
        {"name": "ground", "material": "metal",
         "start_mm": [-60.0, -60.0, 0.0], "stop_mm": [60.0, 60.0, 0.0]},
    ]
    ports: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    ZM = h  # 金属面 z（顶面，与 render_script 新 z 口径一致）

    if template == "wilkinson":
        w_in = float(params.get("shunt_w_mm", 1.113))
        w_arm = float(params.get("series_w_mm", 0.604))
        l_arm = float(params.get("arm_len_mm", 18.1))
        gap = 8.0
        xa = gap / 2 + w_arm / 2
        y_t = -30.0
        y_end = y_t + l_arm
        boxes += [
            {"name": "t_junction", "material": "metal",
             "start_mm": [-xa - w_arm / 2, y_t, ZM], "stop_mm": [xa + w_arm / 2, y_t + w_arm, ZM]},
            {"name": "arm_left", "material": "metal",
             "start_mm": [-xa - w_arm / 2, y_t, ZM], "stop_mm": [-xa + w_arm / 2, y_end, ZM]},
            {"name": "arm_right", "material": "metal",
             "start_mm": [xa - w_arm / 2, y_t, ZM], "stop_mm": [xa + w_arm / 2, y_end, ZM]},
            # 馈线段由 MSLPort 自画（同几何同宽度），预览补画仅供显示
            {"name": "feed_in", "material": "metal",
             "start_mm": [-w_in / 2, -60.0, ZM], "stop_mm": [w_in / 2, y_t, ZM]},
            {"name": "feed_out_left", "material": "metal",
             "start_mm": [-xa - w_in / 2, y_end, ZM], "stop_mm": [-xa + w_in / 2, 60.0, ZM]},
            {"name": "feed_out_right", "material": "metal",
             "start_mm": [xa - w_in / 2, y_end, ZM], "stop_mm": [xa + w_in / 2, 60.0, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出1）", "pos_mm": [-xa, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
            {"name": "Port3（输出2）", "pos_mm": [xa, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
        elements = [{"name": "isolation_resistor", "kind": "lumped_r", "r_ohm": 100.0,
                     "ny": "x", "span_mm": [-gap / 2, gap / 2], "y_mm": y_end}]
    elif template == "branchline":
        # 标准角馈 branchline（2026-09-05 重构，对照 Microwaves101/PMC）：
        # 环=正方形（横臂 series_w=35.35Ω、竖臂 shunt_w=50Ω，各 λ/4），
        # 四角 50Ω 馈线到端口面；port4（隔离端）2026-09-16 起为真 MSLPort。
        arm_l = float(params.get("arm_len_mm", 20.5))
        sw = float(params.get("series_w_mm", 1.87))    # 横臂 35.35Ω
        shw = float(params.get("shunt_w_mm", 1.11))    # 竖臂/馈线 50Ω
        half = arm_l / 2
        boxes += [
            {"name": "arm_top（35.35Ω 串联臂）", "material": "metal",
             "start_mm": [-half - shw / 2, half - sw / 2, ZM],
             "stop_mm": [half + shw / 2, half + sw / 2, ZM]},
            {"name": "arm_bottom（35.35Ω 串联臂）", "material": "metal",
             "start_mm": [-half - shw / 2, -half - sw / 2, ZM],
             "stop_mm": [half + shw / 2, -half + sw / 2, ZM]},
            {"name": "arm_left（50Ω 并联臂）", "material": "metal",
             "start_mm": [-half - shw / 2, -half, ZM],
             "stop_mm": [-half + shw / 2, half, ZM]},
            {"name": "arm_right（50Ω 并联臂）", "material": "metal",
             "start_mm": [half - shw / 2, -half, ZM],
             "stop_mm": [half + shw / 2, half, ZM]},
            {"name": "feed_p1（50Ω，左下角向下）", "material": "metal",
             "start_mm": [-half - shw / 2, -60.0, ZM],
             "stop_mm": [-half + shw / 2, -half, ZM]},
            {"name": "feed_p2（50Ω，右下角向右）", "material": "metal",
             "start_mm": [half, -half - shw / 2, ZM],
             "stop_mm": [60.0, -half + shw / 2, ZM]},
            {"name": "feed_p3（50Ω，右上角向上）", "material": "metal",
             "start_mm": [half - shw / 2, half, ZM],
             "stop_mm": [half + shw / 2, 60.0, ZM]},
            {"name": "feed_p4（50Ω，左上角向左，隔离端 MSLPort）", "material": "metal",
             "start_mm": [-60.0, half - shw / 2, ZM],
             "stop_mm": [-half, half + shw / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入，左下）", "pos_mm": [-half, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（直通，右下）", "pos_mm": [60.0, -half, ZM], "dir": [1.0, 0.0, 0.0]},
            {"name": "Port3（耦合，右上）", "pos_mm": [half, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
            {"name": "Port4（隔离，左上；2026-09-16 起真 MSLPort）", "pos_mm": [-60.0, half, ZM], "dir": [-1.0, 0.0, 0.0]},
        ]
    elif template == "dipole":
        dip_len = float(params.get("dipole_len_mm", 58.0))
        dip_w = float(params.get("dipole_w_mm", 2.0))
        gap = float(params.get("gap_mm", 2.0))
        feed_w = 2.0
        boxes += [
            {"name": "dipole_left", "material": "metal",
             "start_mm": [-dip_len / 2, -dip_w / 2, ZM], "stop_mm": [-gap / 2, dip_w / 2, ZM]},
            {"name": "dipole_right", "material": "metal",
             "start_mm": [gap / 2, -dip_w / 2, ZM], "stop_mm": [dip_len / 2, dip_w / 2, ZM]},
            {"name": "feed_stub", "material": "metal",
             "start_mm": [-feed_w / 2, -60.0, ZM], "stop_mm": [feed_w / 2, -gap / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（馈电）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
        ]
    elif template == "coupled_line":
        cl_len = float(params.get("coupled_len_mm", 20.0))
        cl_w = float(params.get("line_w_mm", 1.0))
        cl_gap = float(params.get("gap_mm", 0.5))
        boxes += [
            {"name": "line_left", "material": "metal",
             "start_mm": [-cl_w - cl_gap / 2, -cl_len / 2, ZM],
             "stop_mm": [-cl_gap / 2, cl_len / 2, ZM]},
            {"name": "line_right", "material": "metal",
             "start_mm": [cl_gap / 2, -cl_len / 2, ZM],
             "stop_mm": [cl_gap / 2 + cl_w, cl_len / 2, ZM]},
            {"name": "feed_left_in", "material": "metal",
             "start_mm": [-cl_w - cl_gap / 2, -60.0, ZM],
             "stop_mm": [-cl_gap / 2, -cl_len / 2, ZM]},
            {"name": "feed_left_out", "material": "metal",
             "start_mm": [-cl_w - cl_gap / 2, cl_len / 2, ZM],
             "stop_mm": [-cl_gap / 2, 60.0, ZM]},
            {"name": "feed_right_in", "material": "metal",
             "start_mm": [cl_gap / 2, -60.0, ZM],
             "stop_mm": [cl_gap / 2 + cl_w, -cl_len / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（直通入）", "pos_mm": [-cl_w - cl_gap / 4, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（直通出）", "pos_mm": [-cl_w - cl_gap / 4, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
            {"name": "Port3（耦合）", "pos_mm": [cl_gap / 2 + cl_w / 2, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
        ]
    elif template == "stepped_impedance":
        z1_w = float(params.get("z1_width_mm", 0.3))
        z2_w = float(params.get("z2_width_mm", 3.0))
        seg_len = float(params.get("seg_len_mm", 5.0))
        n_segs = int(params.get("n_segments", 5))
        total = n_segs * seg_len
        boxes.append({"name": "feed_in", "material": "metal",
                       "start_mm": [-z1_w / 2, -60.0, ZM], "stop_mm": [z1_w / 2, -total / 2, ZM]})
        for i in range(n_segs):
            w = z1_w if i % 2 == 0 else z2_w
            y0 = -total / 2 + i * seg_len
            boxes.append({"name": f"seg_{i}", "material": "metal",
                          "start_mm": [-w / 2, y0, ZM], "stop_mm": [w / 2, y0 + seg_len, ZM]})
        boxes.append({"name": "feed_out", "material": "metal",
                       "start_mm": [-z1_w / 2, total / 2, ZM], "stop_mm": [z1_w / 2, 60.0, ZM]})
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "mline":
        w = float(params.get("w_mm", 1.113))
        length = float(params.get("line_len_mm", 40.0))
        boxes += [
            {"name": "uniform_line", "material": "metal",
             "start_mm": [-w / 2, -length / 2, ZM],
             "stop_mm": [w / 2, length / 2, ZM]},
            # 馈线段由 MSLPort 自画（同宽），预览补画仅供显示
            {"name": "feed_in", "material": "metal",
             "start_mm": [-w / 2, -60.0, ZM], "stop_mm": [w / 2, -length / 2, ZM]},
            {"name": "feed_out", "material": "metal",
             "start_mm": [-w / 2, length / 2, ZM], "stop_mm": [w / 2, 60.0, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "cpw":
        w = float(params.get("w_mm", 0.849))
        gap = float(params.get("gap_mm", 0.2))
        length = float(params.get("line_len_mm", 40.0))
        boxes += [
            {"name": "cpw_center", "material": "metal",
             "start_mm": [-w / 2, -length / 2, ZM],
             "stop_mm": [w / 2, length / 2, ZM]},
            {"name": "gnd_left", "material": "metal",
             "start_mm": [-60.0, -60.0, ZM],
             "stop_mm": [-w / 2 - gap, 60.0, ZM]},
            {"name": "gnd_right", "material": "metal",
             "start_mm": [w / 2 + gap, -60.0, ZM],
             "stop_mm": [60.0, 60.0, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "stripline":
        w = float(params.get("w_mm", 0.5554))
        length = float(params.get("line_len_mm", 40.0))
        boxes += [
            {"name": "stripline_center", "material": "metal",
             "start_mm": [-w / 2, -length / 2, ZM],
             "stop_mm": [w / 2, length / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "cps":
        # C9 共面带：两条等宽带（沿 y）夹中央缝，无地；两端 LumpedPort 跨缝
        # 差分馈/端接（端口在域内 y=∓L/2，与 _cps_lines 同几何口径）
        w = float(params.get("w_mm", 2.95))
        gap = float(params.get("gap_mm", 0.5))
        length = float(params.get("line_len_mm", 40.0))
        boxes += [
            {"name": "cps_strip_left", "material": "metal",
             "start_mm": [-gap / 2 - w, -length / 2, ZM],
             "stop_mm": [-gap / 2, length / 2, ZM]},
            {"name": "cps_strip_right", "material": "metal",
             "start_mm": [gap / 2, -length / 2, ZM],
             "stop_mm": [gap / 2 + w, length / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（LumpedPort 跨缝差分馈，y=−L/2）",
             "pos_mm": [0.0, -length / 2, ZM], "dir": [1.0, 0.0, 0.0]},
            {"name": "Port2（LumpedPort 跨缝差分端接，y=+L/2）",
             "pos_mm": [0.0, length / 2, ZM], "dir": [1.0, 0.0, 0.0]},
        ]
    elif template == "suspended_stripline":
        # C9 悬置带线：带在腔中面 z=b/2（基板 H_SUB 以带为中面对称悬浮）
        w = float(params.get("w_mm", 0.9058))
        b_cav = float(params.get("b_mm", 1.016))
        length = float(params.get("line_len_mm", 40.0))
        zc = b_cav / 2.0
        boxes += [
            {"name": "suspended_stripline_center", "material": "metal",
             "start_mm": [-w / 2, -length / 2, zc],
             "stop_mm": [w / 2, length / 2, zc]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, zc], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, zc], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "wstep":
        w1 = float(params.get("w1_mm", 1.1134))
        w2 = float(params.get("w2_mm", 1.897))
        length = float(params.get("line_len_mm", 40.0))
        boxes += [
            {"name": "wstep_seg1", "material": "metal",
             "start_mm": [-w1 / 2, -length / 2, ZM],
             "stop_mm": [w1 / 2, 0.0, ZM]},
            {"name": "wstep_seg2", "material": "metal",
             "start_mm": [-w2 / 2, 0.0, ZM],
             "stop_mm": [w2 / 2, length / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "tjunc":
        wf = float(params.get("w_feed_mm", 1.1134))
        tl = float(params.get("through_len_mm", 25.0))
        bl = float(params.get("branch_len_mm", 20.0))
        boxes += [
            {"name": "tjunc_through", "material": "metal",
             "start_mm": [-wf / 2, -tl, ZM], "stop_mm": [wf / 2, tl, ZM]},
            {"name": "tjunc_branch", "material": "metal",
             "start_mm": [0.0, -wf / 2, ZM], "stop_mm": [bl, wf / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（直通）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
            {"name": "Port3（支臂）", "pos_mm": [60.0, 0.0, ZM], "dir": [1.0, 0.0, 0.0]},
        ]
    elif template == "bend":
        w = float(params.get("w_mm", 1.1134))
        a = float(params.get("arm_len_mm", 20.0))
        boxes += [
            {"name": "bend_arm_y", "material": "metal",
             "start_mm": [-w / 2, -a, ZM], "stop_mm": [w / 2, 0.0, ZM]},
            {"name": "bend_arm_x", "material": "metal",
             "start_mm": [0.0, -w / 2, ZM], "stop_mm": [a, w / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [60.0, 0.0, ZM], "dir": [1.0, 0.0, 0.0]},
        ]
    elif template == "via":
        w = float(params.get("w_mm", 1.1134))
        boxes += [
            {"name": "via_top_strip", "material": "metal",
             "start_mm": [-w / 2, -60.0, ZM], "stop_mm": [w / 2, 0.0, ZM]},
            {"name": "via_bot_strip", "material": "metal",
             "start_mm": [-w / 2, 0.0, 0.0], "stop_mm": [w / 2, 60.0, 0.0]},
            {"name": "via_barrel", "material": "metal",
             "start_mm": [-0.15, -0.15, 0.0], "stop_mm": [0.15, 0.15, ZM]},
        ]
        ports = [
            {"name": "Port1（顶层输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（底层输出）", "pos_mm": [0.0, 60.0, 0.0], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "atten_pi":
        w = float(params.get("w_mm", 1.1134))
        boxes += [
            {"name": "pi_feed_low", "material": "metal",
             "start_mm": [-w / 2, -60.0, ZM], "stop_mm": [w / 2, -0.5, ZM]},
            {"name": "pi_feed_high", "material": "metal",
             "start_mm": [-w / 2, 0.5, ZM], "stop_mm": [w / 2, 60.0, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "atten_t":
        w = float(params.get("w_mm", 1.1134))
        boxes += [
            {"name": "t_feed_low", "material": "metal",
             "start_mm": [-w / 2, -60.0, ZM], "stop_mm": [w / 2, -5.75, ZM]},
            {"name": "t_feed_mid", "material": "metal",
             "start_mm": [-w / 2, -5.75, ZM], "stop_mm": [w / 2, 5.75, ZM]},
            {"name": "t_feed_high", "material": "metal",
             "start_mm": [-w / 2, 5.75, ZM], "stop_mm": [w / 2, 60.0, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出）", "pos_mm": [0.0, 60.0, ZM], "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "ratrace":
        r = 17.35
        boxes += [
            {"name": "ratrace_ring", "material": "metal",
             "start_mm": [-r, -r, ZM], "stop_mm": [r, r, ZM]},
        ]
        ports = [
            {"name": "Port1（Σ 输入）", "pos_mm": [30.0, 0.0, ZM], "dir": [1.0, 0.0, 0.0]},
            {"name": "Port2（out1）", "pos_mm": [0.0, 30.0, ZM], "dir": [0.0, 1.0, 0.0]},
            {"name": "Port3（Δ 隔离）", "pos_mm": [-30.0, 0.0, ZM], "dir": [-1.0, 0.0, 0.0]},
            {"name": "Port4（out2）", "pos_mm": [0.0, -30.0, ZM], "dir": [0.0, -1.0, 0.0]},
        ]
    elif template == "gysel":
        # 六节环 L-jog 等长变体（P2⑪ 拓扑重设计，#206 理论核验轮定版基础上）：
        # 下边双臂 70.7Ω（P1 中点分叉，角=P2/P3），左右竖边 50Ω 隔离线竖直段
        # YJ，顶端 L-jog 横移 jog=|arm_len−iso_len| 到 Δ 节点 x=±iso_len，顶边
        # 50Ω 桥带跨度 2·iso_len（λ/2 精确，中点开路），Δ1/Δ2 各接 50Ω 端接。
        # 三端口全部在 y=-BOARD 边（单轴 PML）。几何统一由 _gysel_layout 给出。
        lay = _gysel_layout(params)
        wa, wf, xa = lay["wa"], lay["wf"], lay["xa"]
        yj, xb = lay["yj"], lay["xb"]
        boxes += [
            {"name": "gysel_arm_bottom（70.7Ω 双臂）", "material": "metal",
             "start_mm": [-xa, -wa / 2, ZM], "stop_mm": [xa, wa / 2, ZM]},
            {"name": "gysel_iso_left（50Ω 隔离线竖直段 YJ）", "material": "metal",
             "start_mm": [-xa - wf / 2, 0.0, ZM], "stop_mm": [-xa + wf / 2, yj, ZM]},
            {"name": "gysel_iso_right（50Ω 隔离线竖直段 YJ）", "material": "metal",
             "start_mm": [xa - wf / 2, 0.0, ZM], "stop_mm": [xa + wf / 2, yj, ZM]},
            {"name": "gysel_jog_left（隔离线 L-jog 横移段 → Δ1）", "material": "metal",
             "start_mm": [min(-xa, -xb) - wf / 2, yj - wf / 2, ZM],
             "stop_mm": [max(-xa, -xb) + wf / 2, yj + wf / 2, ZM]},
            {"name": "gysel_jog_right（隔离线 L-jog 横移段 → Δ2）", "material": "metal",
             "start_mm": [min(xa, xb) - wf / 2, yj - wf / 2, ZM],
             "stop_mm": [max(xa, xb) + wf / 2, yj + wf / 2, ZM]},
            {"name": "gysel_bridge_top（50Ω λ/2 桥带，跨度 2·iso_len）",
             "material": "metal",
             "start_mm": [-xb - wf / 2, yj - wf / 2, ZM],
             "stop_mm": [xb + wf / 2, yj + wf / 2, ZM]},
            # 馈线段由 MSLPort 自画（同宽），预览补画仅供显示
            {"name": "feed_p1", "material": "metal",
             "start_mm": [-wf / 2, -60.0, ZM], "stop_mm": [wf / 2, -wa / 2, ZM]},
            {"name": "feed_p2", "material": "metal",
             "start_mm": [-xa - wf / 2, -60.0, ZM],
             "stop_mm": [-xa + wf / 2, -wa / 2, ZM]},
            {"name": "feed_p3", "material": "metal",
             "start_mm": [xa - wf / 2, -60.0, ZM],
             "stop_mm": [xa + wf / 2, -wa / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入）", "pos_mm": [0.0, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出1）", "pos_mm": [-xa, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
            {"name": "Port3（输出2）", "pos_mm": [xa, -60.0, ZM], "dir": [0.0, -1.0, 0.0]},
        ]
        elements = [
            {"name": "iso_load1", "kind": "lumped_r", "r_ohm": 50.0,
             "pos_mm": [-xb, yj]},
            {"name": "iso_load2", "kind": "lumped_r", "r_ohm": 50.0,
             "pos_mm": [xb, yj]},
        ]
    elif template == "hairpin":
        # 发夹线 BPF（WP2.3 Tier1 附加模板）：N 个 U 形 λg/2 谐振器 + 抽头馈线。
        # 几何统一由 _hairpin_layout 计算（render_script/_near_points/此处共用）。
        lay = _hairpin_layout(params)
        wm = lay["wf"] * 1e3
        y0m, y1m = lay["y0"] * 1e3, lay["y1"] * 1e3
        ytm = lay["y_tap"] * 1e3
        xs_mm = [v * 1e3 for v in lay["xs"]]
        for _i in range(lay["n"]):
            _xl, _xr = xs_mm[2 * _i], xs_mm[2 * _i + 1]
            boxes += [
                {"name": f"hairpin_r{_i + 1}_arm_l", "material": "metal",
                 "start_mm": [_xl - wm / 2, y0m, ZM],
                 "stop_mm": [_xl + wm / 2, y1m, ZM]},
                {"name": f"hairpin_r{_i + 1}_arm_r", "material": "metal",
                 "start_mm": [_xr - wm / 2, y0m, ZM],
                 "stop_mm": [_xr + wm / 2, y1m, ZM]},
                {"name": f"hairpin_r{_i + 1}_bend", "material": "metal",
                 "start_mm": [_xl - wm / 2, y1m - wm / 2, ZM],
                 "stop_mm": [_xr + wm / 2, y1m + wm / 2, ZM]},
            ]
        boxes += [
            {"name": "feed_in_tap", "material": "metal",
             "start_mm": [-60.0, ytm - wm / 2, ZM],
             "stop_mm": [xs_mm[0], ytm + wm / 2, ZM]},
            {"name": "feed_out_tap", "material": "metal",
             "start_mm": [xs_mm[-1], ytm - wm / 2, ZM],
             "stop_mm": [60.0, ytm + wm / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入，抽头）",
             "pos_mm": [-60.0, ytm, ZM], "dir": [-1.0, 0.0, 0.0]},
            {"name": "Port2（输出，抽头）",
             "pos_mm": [60.0, ytm, ZM], "dir": [1.0, 0.0, 0.0]},
        ]
    elif template == "hairpin_alt":
        # 交替取向发夹线 BPF（2026-09-18 w2g，0dk 根修）：奇数序谐振器上下翻转
        # （弯带 y 逐腔轮替 YBEND[i]、开路端互补），输出抽头随末腔取向自其开路端计。
        # 几何单源 _hairpin_alt_layout（render/_near_points/此处共用，#212）。
        lay = _hairpin_alt_layout(params)
        wm = lay["wf"] * 1e3
        y0m, y1m = lay["y0"] * 1e3, lay["y1"] * 1e3
        yb_mm = [v * 1e3 for v in lay["y_bend"]]
        yt_in, yt_out = lay["y_taps"][0] * 1e3, lay["y_taps"][1] * 1e3
        xs_mm = [v * 1e3 for v in lay["xs"]]
        for _i in range(lay["n"]):
            _xl, _xr = xs_mm[2 * _i], xs_mm[2 * _i + 1]
            boxes += [
                {"name": f"hairpin_r{_i + 1}_arm_l", "material": "metal",
                 "start_mm": [_xl - wm / 2, y0m, ZM],
                 "stop_mm": [_xl + wm / 2, y1m, ZM]},
                {"name": f"hairpin_r{_i + 1}_arm_r", "material": "metal",
                 "start_mm": [_xr - wm / 2, y0m, ZM],
                 "stop_mm": [_xr + wm / 2, y1m, ZM]},
                {"name": f"hairpin_r{_i + 1}_bend", "material": "metal",
                 "start_mm": [_xl - wm / 2, yb_mm[_i] - wm / 2, ZM],
                 "stop_mm": [_xr + wm / 2, yb_mm[_i] + wm / 2, ZM]},
            ]
        boxes += [
            {"name": "feed_in_tap", "material": "metal",
             "start_mm": [-60.0, yt_in - wm / 2, ZM],
             "stop_mm": [xs_mm[0], yt_in + wm / 2, ZM]},
            {"name": "feed_out_tap", "material": "metal",
             "start_mm": [xs_mm[-1], yt_out - wm / 2, ZM],
             "stop_mm": [60.0, yt_out + wm / 2, ZM]},
        ]
        ports = [
            {"name": "Port1（输入，抽头）",
             "pos_mm": [-60.0, yt_in, ZM], "dir": [-1.0, 0.0, 0.0]},
            {"name": "Port2（输出，抽头）",
             "pos_mm": [60.0, yt_out, ZM], "dir": [1.0, 0.0, 0.0]},
        ]
    elif template == "coupled_bpf":
        # 平行耦合 BPF：盒清单由 _coupled_bpf_layout 统一给出（防两处漂移）
        lay = _coupled_bpf_layout(params)
        for _i, (_bx0, _by0, _bx1, _by1) in enumerate(lay["boxes"]):
            boxes.append({"name": lay["box_names"][_i], "material": "metal",
                          "start_mm": [_bx0 * 1e3, _by0 * 1e3, ZM],
                          "stop_mm": [_bx1 * 1e3, _by1 * 1e3, ZM]})
        ports = [
            {"name": "Port1（输入 50Ω 馈）",
             "pos_mm": [lay["xs"][0] * 1e3, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出 50Ω 馈）",
             "pos_mm": [lay["xs"][-1] * 1e3, 60.0, ZM],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "msl_cpw":
        # MSL↔CPWG 过渡（WP2.5，与 _msl_cpw_lines 同几何口径，mm 单位）
        wm = float(params.get("w_msl_mm", 1.1134))
        wc = float(params.get("w_cpw_mm", 0.849))
        gp = float(params.get("gap_cpw_mm", 0.2))
        length = float(params.get("line_len_mm", 40.0))
        trans = float(params.get("trans_len_mm", 10.0))
        y0, ym, yt, y1 = -length / 2, -trans / 2, trans / 2, length / 2
        boxes += [
            {"name": "msl_section", "material": "metal",
             "start_mm": [-wm / 2, y0, ZM], "stop_mm": [wm / 2, ym, ZM]},
            {"name": "taper（阶梯渐变）", "material": "metal",
             "start_mm": [-wm / 2, ym, ZM], "stop_mm": [wm / 2, yt, ZM]},
            {"name": "cpw_center", "material": "metal",
             "start_mm": [-wc / 2, yt, ZM], "stop_mm": [wc / 2, y1, ZM]},
            {"name": "cpw_gnd_left", "material": "metal",
             "start_mm": [-60.0, yt, ZM], "stop_mm": [-(wc / 2 + gp), 60.0, ZM]},
            {"name": "cpw_gnd_right", "material": "metal",
             "start_mm": [wc / 2 + gp, yt, ZM], "stop_mm": [60.0, 60.0, ZM]},
        ]
        ports = [
            {"name": "Port1（MSL 侧）", "pos_mm": [0.0, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（CPWG 侧）", "pos_mm": [0.0, 60.0, ZM],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template == "sma_launcher":
        # SMA 边缘弹射（夹具口径，几何单源 sma_launcher_layout，预览按 0.4mm
        # 收敛档 base 定 port1 面；mm 单位）：基板/地随 PCB 抬高 Z_G 重写
        lay = sma_launcher_layout(params, h * 1e-3, 0.4e-3)
        z_g, z_top, z_ax = lay["z_g"] * 1e3, lay["z_top"] * 1e3, lay["z_ax"] * 1e3
        ros, ri, ro = lay["ros"] * 1e3, lay["ri"] * 1e3, lay["ro"] * 1e3
        y_b, y_p0, y_e = lay["y_b"] * 1e3, lay["y_p0"] * 1e3, lay["y_e"] * 1e3
        y_pe, y1, wm = lay["y_pe"] * 1e3, lay["y1"] * 1e3, lay["w_m"] * 1e3
        boxes[0] = {"name": "substrate", "material": "substrate",
                    "start_mm": [-60.0, y_e, z_g], "stop_mm": [60.0, 60.0, z_top]}
        boxes[1] = {"name": "ground", "material": "metal",
                    "start_mm": [-60.0, y_e, 0.0], "stop_mm": [60.0, 60.0, z_g]}
        boxes += [
            {"name": "coax_shell（弹射壳体）", "material": "metal",
             "start_mm": [-ros, y_b, 0.0], "stop_mm": [ros, y_e, 2 * ros]},
            {"name": "body_face（连接器体前脸，孔径按优先级挖空）", "material": "metal",
             "start_mm": [-lay["f_w"] * 1e3, (lay["y_e"] - lay["f_t"]) * 1e3, 0.0],
             "stop_mm": [lay["f_w"] * 1e3, y_e, lay["f_z"] * 1e3]},
            {"name": "coax_pin（中心针）", "material": "metal",
             "start_mm": [-ri, y_b, z_ax - ri], "stop_mm": [ri, y_pe, z_ax + ri]},
            {"name": "solder（搭焊）", "material": "metal",
             "start_mm": [-wm / 2, y_e, z_top], "stop_mm": [wm / 2, y_pe, z_ax]},
            {"name": "msl_feed", "material": "metal",
             "start_mm": [-wm / 2, y_e, z_top], "stop_mm": [wm / 2, y1, z_top]},
        ]
        ports = [
            {"name": "Port1（SMA 同轴截面集总桥）",
             "pos_mm": [0.0, y_p0, z_ax + 0.5 * (ri + ro)],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（MSL 50Ω）", "pos_mm": [0.0, 60.0, z_top],
             "dir": [0.0, 1.0, 0.0]},
        ]
    elif template in C3_TEMPLATES:
        # §C3 滤波器族 II：盒/过孔/电容清单由 _c3_layout 单源给出（米 → mm）；
        # 过孔柱以 2r 方盒进预览，装载电容进 elements（lumped_c）
        lay = _c3_layout(template, params)
        for (_bx0, _by0, _bx1, _by1), _nm in zip(lay["boxes"], lay["box_names"],
                                                strict=True):
            boxes.append({"name": _nm, "material": "metal",
                          "start_mm": [_bx0 * 1e3, _by0 * 1e3, ZM],
                          "stop_mm": [_bx1 * 1e3, _by1 * 1e3, ZM]})
        _rv = lay["r_via"]
        for _k, (_vx, _vy) in enumerate(lay["vias"], start=1):
            boxes.append({"name": f"via{_k}（接地过孔 r={_rv * 1e3:.2f}mm）",
                          "material": "metal",
                          "start_mm": [(_vx - _rv) * 1e3, (_vy - _rv) * 1e3, 0.0],
                          "stop_mm": [(_vx + _rv) * 1e3, (_vy + _rv) * 1e3, ZM]})
        if template == "combline":
            _c_pf = float(params.get("c_load_pf",
                                     TEMPLATE_NOMINAL["combline"]["c_load_pf"]))
            elements = [{"name": f"c_load{_k}", "kind": "lumped_c",
                         "c_pf": _c_pf,
                         "pos_mm": [0.5 * (_cx0 + _cx1) * 1e3,
                                    0.5 * (_cy0 + _cy1) * 1e3]}
                        for _k, (_cx0, _cy0, _cx1, _cy1)
                        in enumerate(lay["caps"], start=1)]
        ports = [
            {"name": "Port1（输入 50Ω 馈，缝耦合）",
             "pos_mm": [lay["xs"][0] * 1e3, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
            {"name": "Port2（输出 50Ω 馈，缝耦合，同边）",
             "pos_mm": [lay["xs"][-1] * 1e3, -60.0, ZM],
             "dir": [0.0, -1.0, 0.0]},
        ]
    elif template in _C4_COUPLER_TEMPLATES:
        # §C4 耦合器族 II：盒/端口清单由 _c4_layout 单源给出（米 → mm）。
        # lange 的 air-bridge（抬高薄金属 + 竖直立柱）作为独立盒进预览，
        # 让 3D 预览与 #212 连通性审计看到同一份几何。
        lay = _c4_layout(template, params)
        for (_nm, _x0, _y0, _z0, _x1, _y1, _z1) in lay["boxes"]:
            boxes.append({"name": _nm, "material": "metal",
                          "start_mm": [_x0 * 1e3, _y0 * 1e3, _z0 * 1e3],
                          "stop_mm": [_x1 * 1e3, _y1 * 1e3, _z1 * 1e3]})
        for _pt in lay["ports"]:
            _s = _pt["start"]
            _ax = 0 if _pt["prop_dir"] == "x" else 1
            _sign = -1.0 if _s[_ax] < 0.0 else 1.0
            _dir = [0.0, 0.0, 0.0]
            _dir[_ax] = _sign
            _pos = [(_pt["start"][0] + _pt["stop"][0]) / 2.0 * 1e3,
                    (_pt["start"][1] + _pt["stop"][1]) / 2.0 * 1e3, ZM]
            _pos[_ax] = _s[_ax] * 1e3
            ports.append({"name": f"Port{_pt['nr']}（{_pt['label']}）",
                          "pos_mm": _pos, "dir": _dir})
    elif template in ANTENNA2_TEMPLATES:
        # §10.3 C1 天线族 II：盒/端口清单由 _ant2_layout 单源给出（mm）。
        # monopole/helix 无介质板（像理论口径）→ 去掉默认基板盒；slot 地面为
        # 有限留槽金属板（布局自带 4 盒）→ 去掉默认整板地盒；loop 自由空间
        # （无板无地，2026-09-16）→ 两盒都去（布局 substrate/ground 标志单源）。
        lay = _ant2_layout(template, params, substrate)
        if not lay["substrate"]:
            boxes = [b for b in boxes if b["name"] != "substrate"]
        if not lay["ground"]:
            boxes = [b for b in boxes if b["name"] != "ground"]
        for (_prop, _nm, _x0, _y0, _z0, _x1, _y1, _z1) in lay["boxes"]:
            boxes.append({"name": f"{_prop}/{_nm}", "material": "metal",
                          "start_mm": [_x0, _y0, _z0],
                          "stop_mm": [_x1, _y1, _z1]})
        _axis_index = {"x": 0, "y": 1, "z": 2}
        for _pt in lay["ports"]:
            _s, _t = _pt["start_mm"], _pt["stop_mm"]
            _nr = int(_pt["nr"])
            if _pt["kind"] == "lumped":
                _dir = [0.0, 0.0, 0.0]
                _dir[_axis_index[_pt["exc_dir"]]] = 1.0
                ports.append({
                    "name": f"Port{_nr}（LumpedPort 集总馈口，E 沿 {_pt['exc_dir']}）",
                    "pos_mm": [(_s[0] + _t[0]) / 2.0, (_s[1] + _t[1]) / 2.0,
                               (_s[2] + _t[2]) / 2.0],
                    "dir": _dir})
            else:
                _ax = _axis_index[_pt["prop_dir"]]
                _sign = -1.0 if _s[_ax] < _t[_ax] else 1.0
                _dir = [0.0, 0.0, 0.0]
                _dir[_ax] = _sign
                ports.append({
                    "name": f"Port{_nr}（MSLPort 50Ω 馈）",
                    "pos_mm": [(_s[0] + _t[0]) / 2.0 if _ax != 0 else _s[0],
                               (_s[1] + _t[1]) / 2.0 if _ax != 1 else _s[1],
                               ZM],
                    "dir": _dir})
    elif template in ARRAY_TEMPLATES:
        # §10.3 C2 阵列族：盒/端口/单元中心由 _arr_layout 单源给出（mm）；接地
        # 贴片阵 → 默认基板盒与整板地盒均保留
        lay = _arr_layout(template, params, substrate)
        for (_prop, _nm, _x0, _y0, _z0, _x1, _y1, _z1) in lay["boxes"]:
            boxes.append({"name": f"{_prop}/{_nm}", "material": "metal",
                          "start_mm": [_x0, _y0, _z0],
                          "stop_mm": [_x1, _y1, _z1]})
        for _pt in lay["ports"]:
            _s, _t = _pt["start_mm"], _pt["stop_mm"]
            _nr = int(_pt["nr"])
            if _pt["kind"] == "lumped":
                ports.append({
                    "name": f"Port{_nr}（LumpedPort 底探针 50Ω，E 沿 z）",
                    "pos_mm": [(_s[0] + _t[0]) / 2.0, (_s[1] + _t[1]) / 2.0,
                               (_s[2] + _t[2]) / 2.0],
                    "dir": [0.0, 0.0, 1.0]})
            else:
                ports.append({
                    "name": f"Port{_nr}（MSLPort 50Ω 馈）",
                    "pos_mm": [(_s[0] + _t[0]) / 2.0, _s[1], ZM],
                    "dir": [0.0, -1.0 if _s[1] < _t[1] else 1.0, 0.0]})
        elements = [{"name": f"elem{_i}", "kind": "patch_element",
                     "center_mm": [float(_cx), float(_cy)]}
                    for _i, (_cx, _cy) in enumerate(lay["elements_mm"])]
    elif template in EEP_TEMPLATES:
        # §DP-4 P3 EEP 阵列族：盒/端口/单元中心由 _eep_layout 单源给出（mm）；
        # 接地贴片阵 → 默认基板盒与整板地盒均保留；端口次序=行主序契约
        lay = _eep_layout(template, params, substrate)
        for (_prop, _nm, _x0, _y0, _z0, _x1, _y1, _z1) in lay["boxes"]:
            boxes.append({"name": f"{_prop}/{_nm}", "material": "metal",
                          "start_mm": [_x0, _y0, _z0],
                          "stop_mm": [_x1, _y1, _z1]})
        for _pt in lay["ports"]:
            _s, _t = _pt["start_mm"], _pt["stop_mm"]
            _nr = int(_pt["nr"])
            ports.append({
                "name": f"Port{_nr}（EEP 底探针 50Ω，E 沿 z）",
                "pos_mm": [(_s[0] + _t[0]) / 2.0, (_s[1] + _t[1]) / 2.0,
                           (_s[2] + _t[2]) / 2.0],
                "dir": [0.0, 0.0, 1.0]})
        elements = [{"name": f"elem{_i}", "kind": "patch_element",
                     "center_mm": [float(_cx), float(_cy)]}
                    for _i, (_cx, _cy) in enumerate(lay["elements_mm"])]
    elif template == "siw":
        # SIW 族首族：矩形域（layout 单源，审计档 0.4mm base 口径）；过孔藩篱
        # 预览按列条带绘制（每孔小盒 ×77×2 过密，UI 只需拓扑示意）
        lay = siw_layout(params, (9.75, 10.25), 0.4e-3,
                         float(params.get("h_mm", h)) * 1e-3)
        boxes = [
            {"name": "substrate", "material": "substrate",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["dom_y"] * 1e3, 0.0],
             "stop_mm": [lay["dom_x"] * 1e3, lay["dom_y"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "plate_bottom", "material": "metal",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["dom_y"] * 1e3, 0.0],
             "stop_mm": [lay["dom_x"] * 1e3, lay["dom_y"] * 1e3, 0.0]},
            {"name": "plate_top", "material": "metal",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["dom_y"] * 1e3,
                          lay["h"] * 1e3],
             "stop_mm": [lay["dom_x"] * 1e3, lay["dom_y"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "via_fence_left", "material": "metal",
             "start_mm": [(lay["w"] / 2 - lay["d"] / 2) * 1e3,
                          lay["via_y"][0] * 1e3, 0.0],
             "stop_mm": [(lay["w"] / 2 + lay["d"] / 2) * 1e3,
                         lay["via_y"][-1] * 1e3, lay["h"] * 1e3]},
            {"name": "via_fence_right", "material": "metal",
             "start_mm": [-(lay["w"] / 2 + lay["d"] / 2) * 1e3,
                          lay["via_y"][0] * 1e3, 0.0],
             "stop_mm": [-(lay["w"] / 2 - lay["d"] / 2) * 1e3,
                         lay["via_y"][-1] * 1e3, lay["h"] * 1e3]},
        ]
        ports = [
            {"name": "Port1（LumpedPort z 桥，R=Z_PV 闭式）",
             "pos_mm": [0.0, lay["y1"] * 1e3, lay["h"] * 1e3 / 2.0],
             "dir": [0.0, 0.0, 1.0]},
            {"name": "Port2（LumpedPort z 桥，R=Z_PV 闭式）",
             "pos_mm": [0.0, lay["y2"] * 1e3, lay["h"] * 1e3 / 2.0],
             "dir": [0.0, 0.0, 1.0]},
        ]
    elif template == "msl_siw_taper":
        # SIW 族第二成员：矩形域（layout 单源，审计档 0.4mm base 口径）；
        # 锥形段以包络盒示意（UI 拓扑预览）
        lay = msl_siw_taper_layout(params, (9.75, 10.25), 0.4e-3,
                                   float(params.get("h_mm", h)) * 1e-3)
        boxes = [
            {"name": "substrate", "material": "substrate",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["dom_y"] * 1e3, 0.0],
             "stop_mm": [lay["dom_x"] * 1e3, lay["dom_y"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "plate_bottom", "material": "metal",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["y_plate"] * 1e3, 0.0],
             "stop_mm": [lay["dom_x"] * 1e3, lay["y_plate"] * 1e3, 0.0]},
            {"name": "plate_top_siw", "material": "metal",
             "start_mm": [-lay["dom_x"] * 1e3, -lay["y_plate"] * 1e3,
                          lay["h"] * 1e3],
             "stop_mm": [lay["dom_x"] * 1e3, lay["y_plate"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "feed_p1（50Ω MSL）", "material": "metal",
             "start_mm": [-lay["w50"] / 2 * 1e3, -lay["dom_y"] * 1e3,
                          lay["h"] * 1e3],
             "stop_mm": [lay["w50"] / 2 * 1e3, -lay["y_feed_in"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "feed_p2（50Ω MSL）", "material": "metal",
             "start_mm": [-lay["w50"] / 2 * 1e3, lay["y_feed_in"] * 1e3,
                          lay["h"] * 1e3],
             "stop_mm": [lay["w50"] / 2 * 1e3, lay["dom_y"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "taper_p1（线性锥 w50→w_end 包络）", "material": "metal",
             "start_mm": [-lay["w_end"] / 2 * 1e3, -lay["y_feed_in"] * 1e3,
                          lay["h"] * 1e3],
             "stop_mm": [lay["w_end"] / 2 * 1e3, -lay["y_plate"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "taper_p2（线性锥 w50→w_end 包络）", "material": "metal",
             "start_mm": [-lay["w_end"] / 2 * 1e3, lay["y_plate"] * 1e3,
                          lay["h"] * 1e3],
             "stop_mm": [lay["w_end"] / 2 * 1e3, lay["y_feed_in"] * 1e3,
                         lay["h"] * 1e3]},
            {"name": "via_fence_left", "material": "metal",
             "start_mm": [(lay["w"] / 2 - lay["d"] / 2) * 1e3,
                          lay["via_y"][0] * 1e3, 0.0],
             "stop_mm": [(lay["w"] / 2 + lay["d"] / 2) * 1e3,
                         lay["via_y"][-1] * 1e3, lay["h"] * 1e3]},
            {"name": "via_fence_right", "material": "metal",
             "start_mm": [-(lay["w"] / 2 + lay["d"] / 2) * 1e3,
                          lay["via_y"][0] * 1e3, 0.0],
             "stop_mm": [-(lay["w"] / 2 - lay["d"] / 2) * 1e3,
                         lay["via_y"][-1] * 1e3, lay["h"] * 1e3]},
        ]
        ports = [
            {"name": "Port1（MSLPort 50Ω 馈，线基）",
             "pos_mm": [0.0, -lay["dom_y"] * 1e3, lay["h"] * 1e3],
             "dir": [0.0, 1.0, 0.0]},
            {"name": "Port2（MSLPort 50Ω 馈，线基）",
             "pos_mm": [0.0, lay["dom_y"] * 1e3, lay["h"] * 1e3],
             "dir": [0.0, -1.0, 0.0]},
        ]
    else:  # patch (default fallback)
        pl = float(params.get("patch_len_mm", 34.9))
        pw = float(params.get("patch_w_mm", 50.0))
        off = float(params.get("feed_offset_mm", 5.5))
        boxes += [
            {"name": "patch", "material": "metal",
             "start_mm": [-pl / 2, -pw / 2, ZM], "stop_mm": [pl / 2, pw / 2, ZM]},
            # 底馈探针（官方口径：x=-feed_offset，y 向 2mm、x 向 0.2mm、z 跨基板）
            {"name": "feed_probe", "material": "metal",
             "start_mm": [-off - 0.1, -1.0, 0.0], "stop_mm": [-off + 0.1, 1.0, h]},
        ]
        ports = [
            {"name": "Port1（底馈探针 50Ω）",
             "pos_mm": [-off, 0.0, 0.0], "dir": [0.0, 0.0, 1.0]},
        ]
        elements = [{"name": "feed_port", "kind": "lumped_port", "r_ohm": 50.0,
                     "feed_offset_mm": off}]

    return {"template": template, "substrate": substrate, "boxes": boxes, "ports": ports,
            "elements": elements}


def _near_points(template: str, params: dict[str, Any],
                 base_mm: float = 0.4) -> tuple[list[float], list[float]]:
    """每模板走线边缘近场加密点（米；官方 NEAR=base/4 口径）。

    base_mm：网格 base（mm），仅 ratrace 分支消费——渲染半径 R/k(BASE) 与
    _ratrace_lines 同函数同 BASE，保证近场线与几何同 k；默认 0.4=离线审计档。
    """
    def edges(lo: float, hi: float, near: float) -> list[float]:
        return [lo - near / 2, hi + near / 2]

    nx: list[float] = [0.0]
    ny: list[float] = [0.0]
    if template == "wilkinson":
        w_in = float(params.get("shunt_w_mm", 1.113)) * 1e-3
        w_arm = float(params.get("series_w_mm", 0.604)) * 1e-3
        l_arm = float(params.get("arm_len_mm", 18.1)) * 1e-3
        xa = 4e-3 + w_arm / 2
        y_t, y_end = -30e-3, -30e-3 + l_arm
        nx += edges(-w_in / 2, w_in / 2, 1e-3)          # 输入馈线
        nx += edges(-xa - w_in / 2, -xa + w_in / 2, 1e-3)  # 输出馈线×2
        nx += edges(xa - w_in / 2, xa + w_in / 2, 1e-3)
        nx += edges(-xa - w_arm / 2, xa + w_arm / 2, 1e-3)  # T 条+双臂
        ny += edges(y_t, y_t + w_arm, 1e-3)
        ny += edges(y_end - w_arm / 2, y_end + w_arm / 2, 1e-3)
    elif template == "branchline":
        arm_l = float(params.get("arm_len_mm", 20.5)) * 1e-3
        sw = float(params.get("series_w_mm", 1.87)) * 1e-3    # 横臂 35.35Ω
        shw = float(params.get("shunt_w_mm", 1.11)) * 1e-3    # 竖臂/馈线 50Ω
        half = arm_l / 2
        nx += edges(-half - shw / 2, -half + shw / 2, 1e-3)   # 左竖臂/馈线缘
        nx += edges(half - shw / 2, half + shw / 2, 1e-3)     # 右竖臂/馈线缘
        nx += edges(-half - shw / 2, half + shw / 2, 1e-3)    # 横臂全长（角部）
        ny += edges(-half - sw / 2, -half + sw / 2, 1e-3)     # 下横臂缘
        ny += edges(half - sw / 2, half + sw / 2, 1e-3)       # 上横臂缘
        ny += edges(-half - shw / 2, half + shw / 2, 1e-3)    # 竖臂全长（角部）
        # p2/p4 水平馈线（宽 shw≠横臂宽 sw）自身边缘进网格：端口面宽度须被
        # 网格解析（2026-09-16 四端口升级，p4 真 MSLPort 与 p2 镜像同口径）
        ny += edges(-half - shw / 2, -half + shw / 2, 1e-3)   # p2 馈线缘
        ny += edges(half - shw / 2, half + shw / 2, 1e-3)     # p4 馈线缘
    elif template == "coupled_line":
        cl_len = float(params.get("coupled_len_mm", 20.0)) * 1e-3
        cl_w = float(params.get("line_w_mm", 1.0)) * 1e-3
        cl_gap = float(params.get("gap_mm", 0.5)) * 1e-3
        nx += edges(-cl_w - cl_gap / 2, cl_gap / 2 + cl_w, 1e-3)
        ny += edges(-cl_len / 2, cl_len / 2, 1e-3)
    elif template == "stepped_impedance":
        z1_w = float(params.get("z1_width_mm", 0.3)) * 1e-3
        z2_w = float(params.get("z2_width_mm", 3.0)) * 1e-3
        seg_len = float(params.get("seg_len_mm", 5.0)) * 1e-3
        n_segs = int(params.get("n_segments", 5))
        total = n_segs * seg_len
        nx += edges(-z1_w / 2, z1_w / 2, 1e-3)
        nx += edges(-z2_w / 2, z2_w / 2, 1e-3)
        for i in range(n_segs + 1):
            ny.append(-total / 2 + i * seg_len)
    elif template == "dipole":
        dip_len = float(params.get("dipole_len_mm", 58.0)) * 1e-3
        dip_w = float(params.get("dipole_w_mm", 2.0)) * 1e-3
        gap = float(params.get("gap_mm", 2.0)) * 1e-3
        nx += edges(-dip_len / 2, dip_len / 2, 1e-3)
        nx += edges(-gap / 2, gap / 2, 1e-3)
        ny += edges(-dip_w / 2, dip_w / 2, 1e-3)
    elif template == "mline":
        w = float(params.get("w_mm", 1.113)) * 1e-3
        length = float(params.get("line_len_mm", 40.0)) * 1e-3
        # 带缘精确入网（#198 收敛教训：edges() 括号线让带缘落在网格间，
        # 粗网格靠平滑运气对齐，细网格阶梯方向翻转→εeff 非单调爆走
        # 0.4mm 档 +11.55% 实证）
        nx += [-w / 2, w / 2]
        ny += edges(-length / 2, length / 2, 1e-3)             # 线两端（junction）
    elif template == "stripline":
        w = float(params.get("w_mm", 0.5554)) * 1e-3
        length = float(params.get("line_len_mm", 40.0)) * 1e-3
        nx += [-w / 2, w / 2]                       # 带缘精确入网（#198）
        ny += edges(-length / 2, length / 2, 1e-3)             # 线两端（junction）
    elif template == "cps":
        w = float(params.get("w_mm", 2.95)) * 1e-3
        gap = float(params.get("gap_mm", 0.5)) * 1e-3
        length = float(params.get("line_len_mm", 40.0)) * 1e-3
        # 四条带缘精确入网（内缘 ±gap/2、外缘 ±(gap/2+w)）+ 缝中线 x=0（nx 已
        # 含 0）；LumpedPort 跨缝盒 [−gap/2, gap/2] 两边各自吸附独立网格线，
        # 激励体积非零（#174/#198 吸附变体教训）
        nx += [-gap / 2, gap / 2, gap / 2 + w, -(gap / 2 + w)]
        # 线两端=LumpedPort 面（零厚 y 面必须恰在网格线，#212 审计①）
        ny += [-length / 2, length / 2]
        ny += edges(-length / 2, length / 2, 1e-3)
    elif template == "siw":
        # 过孔藩篱三线对精确入网（#198：列心 ±w/2、孔缘 ±d/2；每孔 y 向
        # k·s∓d/2、k·s）+ 端口盒三向边/中线（#283：盒边=结构线，中线恰在
        # 网格线上探针才逐位落位）——全部由 layout 单源给出（#349 最小间距
        # 守卫在 siw_layout 内对同一线集执行）
        lay = params.get("_siw_layout")
        if lay is None:
            raise ValueError(
                "siw _near_points: 缺 _siw_layout（必须经 render_script 渲染）")
        d, w = lay["d"], lay["w"]
        nx += [w / 2 - d / 2, w / 2, w / 2 + d / 2,
               -(w / 2 - d / 2), -w / 2, -(w / 2 + d / 2)]
        # 端口盒 x 边 ±RX 精确入网（#283：盒边=结构线，缺线即生成期断言红）
        nx += [lay["rx"], -lay["rx"]]
        ny += [lay["y1"] - lay["py"], lay["y1"], lay["y1"] + lay["py"],
               lay["y2"] - lay["py"], lay["y2"], lay["y2"] + lay["py"]]
        for _yk in lay["via_y"]:
            ny += [_yk - d / 2, _yk, _yk + d / 2]
    elif template == "msl_siw_taper":
        # 过孔藩篱三线对精确入网（#198，siw 同款）+ 锥两端宽缘/锥-板搭接缘/
        # 板缘/端口面（域界）——全部由 layout 单源给出（#349 最小间距守卫在
        # msl_siw_taper_layout 内对同一线集执行）
        lay = params.get("_msl_siw_taper_layout")
        if lay is None:
            raise ValueError(
                "msl_siw_taper _near_points: 缺 _msl_siw_taper_layout"
                "（必须经 render_script 渲染）")
        d, w = lay["d"], lay["w"]
        nx += [w / 2 - d / 2, w / 2, w / 2 + d / 2,
               -(w / 2 - d / 2), -w / 2, -(w / 2 + d / 2)]
        # 馈线/锥两端宽缘精确入网（#198：带缘恰在网格线，粗网格阶梯方向
        # 翻转→εeff 非单调教训）
        nx += [lay["w50"] / 2, -lay["w50"] / 2,
               lay["w_end"] / 2, -lay["w_end"] / 2]
        ny += [lay["dom_y"], -lay["dom_y"],
               lay["y_feed_in"], -lay["y_feed_in"],
               lay["y_plate"], -lay["y_plate"]]
        for _yk in lay["via_y"]:
            ny += [_yk - d / 2, _yk, _yk + d / 2]
    elif template in MS_UNIT_TEMPLATES:
        # §MS_METASURFACE 单元（文末 MS_METASURFACE 段）：近场线由
        # ms_unit_layout 单源给出（屏/贴片缘 + 胞缘缝 3+ 中点入网 #311）
        lay = params.get("_ms_layout")
        if lay is None:
            raise ValueError(
                f"{template} _near_points: 缺 _ms_layout（必须经 render_script "
                "渲染）")
        nx += lay["near_x"]
        ny += lay["near_y"]
    elif template == "suspended_stripline":
        w = float(params.get("w_mm", 0.9058)) * 1e-3
        length = float(params.get("line_len_mm", 40.0)) * 1e-3
        nx += [-w / 2, w / 2]                       # 带缘精确入网（#198）
        ny += edges(-length / 2, length / 2, 1e-3)             # 线两端（junction）
    elif template == "cpw":
        w = float(params.get("w_mm", 0.849)) * 1e-3
        gap = float(params.get("gap_mm", 0.2)) * 1e-3
        length = float(params.get("line_len_mm", 40.0)) * 1e-3
        # 四条几何边精确入网（带缘 ±w/2、地内缘 ±(w/2+gap)）：
        # 窄线宽下 edges() 括号线退化（缝区无线），CPWPort 激励盒
        # [w/2, w/2+gap] 两边吸附到同一网格线 → 激励体积归零、能量全零
        # （pt2 NaN 实证；#174"零体积激励"教训的吸附变体，#198）
        nx += [-w / 2, w / 2, w / 2 + gap, -(w / 2 + gap)]
        # 缝中线加密：CPW 的 εeff 由缝场主导，缝区单胞柱欠解析
        # （pt3 β→εeff −2.13% 越界的精度限制项，pt4 收敛验证）
        nx += [w / 2 + gap / 2, -(w / 2 + gap / 2)]
        ny += edges(-length / 2, length / 2, 1e-3)             # 线两端（junction）
    elif template == "wstep":
        w1 = float(params.get("w1_mm", 1.1134)) * 1e-3
        w2 = float(params.get("w2_mm", 1.897)) * 1e-3
        length = float(params.get("line_len_mm", 40.0)) * 1e-3
        nx += [-w1 / 2, w1 / 2, -w2 / 2, w2 / 2]   # 两段带缘精确入网（#198）
        ny += edges(-length / 2, length / 2, 1e-3)   # 线两端；阶跃=默认 0.0
    elif template == "tjunc":
        wf = float(params.get("w_feed_mm", 1.1134)) * 1e-3
        tl = float(params.get("through_len_mm", 25.0)) * 1e-3
        bl = float(params.get("branch_len_mm", 20.0)) * 1e-3
        # 三臂带缘+结点角精确入网（#198）：主线带缘/端点、支臂带缘/端点
        nx += [-wf / 2, wf / 2, bl]
        ny += [-tl, tl, -wf / 2, wf / 2]
    elif template == "bend":
        w = float(params.get("w_mm", 1.1134)) * 1e-3
        a = float(params.get("arm_len_mm", 20.0)) * 1e-3
        nx += [-w / 2, w / 2, a]          # 臂1带缘 + 臂2端点
        ny += [-a, -w / 2, w / 2]         # 臂1端点 + 臂2带缘；弯角=默认 0
    elif template == "via":
        w = float(params.get("w_mm", 1.1134)) * 1e-3
        ap = float(params.get("antipad_mm", 0.8)) * 1e-3
        nx += [-w / 2, w / 2, -ap, ap]    # 顶带缘 + 反焊盘方边（x）
        ny += [-ap, ap]                   # 反焊盘方边（y）
    elif template == "atten_pi":
        w = float(params.get("w_mm", 1.1134)) * 1e-3
        d = float(params.get("shunt_off_mm", 6.0)) * 1e-3
        g = 0.5 * 1e-3                    # 串臂断口半长/元件盒半宽（mm→m）
        nx += [-w / 2, w / 2, -g / 2, g / 2]          # 带缘 + shunt 盒 x 边
        ny += [-d - g / 2, -d + g / 2, -g, g,
               d - g / 2, d + g / 2]                  # shunt 盒 y 边 + 串臂断口
    elif template == "atten_t":
        w = float(params.get("w_mm", 1.1134)) * 1e-3
        d = float(params.get("shunt_off_mm", 6.0)) * 1e-3
        g = 0.5 * 1e-3
        nx += [-w / 2, w / 2, -g / 2, g / 2]          # 带缘 + shunt 盒 x 边
        ny += [-d - g / 2, -d + g / 2, -g, g,
               d - g / 2, d + g / 2]                  # shunt 盒 y 边 + 串臂断口
    elif template == "ratrace":
        wf = float(params.get("w_feed_mm", 1.1134)) * 1e-3
        # 渲染半径 = 物理半径 / k(BASE)（阶梯环慢波伪象补偿随网格档标度，
        # 与 _ratrace_lines 同函数同 BASE，见 ratrace_ring_mesh_k 注释）
        r_ring = (float(params.get("r_ring_mm", 17.344)) * 1e-3
                  / ratrace_ring_mesh_k(base_mm))
        # 规范角位（#208）：Σ/out2 水平馈带缘 y=±W_F/2；out1/Δ 竖直
        # 引出段 x=±(0.5R + 4mm/tan60)（弯折点几何与 body 同式）
        x_top = 0.5 * r_ring + 4.0e-3 / 3.0 ** 0.5
        ny += [-wf / 2, wf / 2]
        nx += [-x_top - wf / 2, -x_top + wf / 2,
               x_top - wf / 2, x_top + wf / 2]
        # out1/Δ junction 区（环顶 |y|≈0.87R）近场线（审查 P1-1：
        # 缺失时该处行距=BASE，环带 x 跳步≈0.67mm，带宽不确定 ±50%）
        y_j = 0.866 * r_ring
        wr = float(params.get("w_ring_mm", 0.6035)) * 1e-3
        ny += [y_j - wr, y_j + wr, -y_j - wr, -y_j + wr]
    elif template == "gysel":
        # L-jog 等长变体（P2⑪）：几何统一由 _gysel_layout 给出（mm→m）
        lay = _gysel_layout(params)
        wa, wf, xa = lay["wa"] * 1e-3, lay["wf"] * 1e-3, lay["xa"] * 1e-3
        yj, xb, g = lay["yj"] * 1e-3, lay["xb"] * 1e-3, lay["g"] * 1e-3
        # 带缘+负载盒边精确入网（#198）：x=±W_F/2（P1 馈）、±XA±W_F/2（竖边/
        # 馈线共线合并）、±XB±W_F/2（Δ 节点负载盒 x 缘=jog 段端缘）；
        # y=±W_A/2（臂）、YJ±W_F/2（顶边桥带/jog 段带缘）、YJ±G/2（负载盒 y 边）。
        # #152 核对：±XB±W_F/2 与 ±XA±W_F/2 最小间距=jog=|arm_len−iso_len|
        # （nominal 0.412mm≫1µm 守卫）
        nx += [-wf / 2, wf / 2,
               -xa - wf / 2, -xa + wf / 2, xa - wf / 2, xa + wf / 2,
               -xb - wf / 2, -xb + wf / 2, xb - wf / 2, xb + wf / 2]
        ny += [-wa / 2, wa / 2,
               yj - wf / 2, yj + wf / 2, yj - g / 2, yj + g / 2]
        if lay["miter"] > 0.0:
            # mitered-jog 切角档（C7）：两侧缺口缘精确入网（#198）；缺省 0
            # 不加线，近点集与未切角基线一致（渲染逐字节不变）
            _c = lay["miter"] * 1e-3
            for _s in (1.0, -1.0):
                _cx = _s * (xa + wf / 2) if xb < xa else _s * (xa - wf / 2)
                _n = sorted((_cx, _cx - _s * _c if xb < xa else _cx + _s * _c))
                nx += [_n[0], _n[1]]
            ny += [yj + wf / 2 - _c]
    elif template == "hairpin":
        # 发夹线 BPF：全部臂缘/弯带缘/抽头缘精确入网（#198 精确入网）
        lay = _hairpin_layout(params)
        _wf = lay["wf"]
        for _i in range(lay["n"]):
            _xl, _xr = lay["xs"][2 * _i], lay["xs"][2 * _i + 1]
            nx += [_xl - _wf / 2, _xl + _wf / 2, _xr - _wf / 2, _xr + _wf / 2]
        ny += [lay["y0"], lay["y1"] - _wf / 2, lay["y1"] + _wf / 2,
               lay["y_tap"] - _wf / 2, lay["y_tap"] + _wf / 2]
    elif template == "hairpin_alt":
        # 交替取向发夹线（2026-09-18 w2g）：臂缘 x + 逐腔开路端/弯带缘 y（翻转腔弯带
        # 在 Y0 侧、开路端在 Y1）+ 两抽头缘（末腔翻转时输出抽头 y 与输入不同）精确
        # 入网（#198）。网格配方与 hairpin 逐项同源（不另加缝中线）：orientation=
        # "same" 对照渲染须与 hairpin 同网格，k(gap) A/B 才只隔离拓扑变量；缝
        # 1.13mm ≫ NEAR，缝内内部线 ≥1 由审计门实测（#266 口径）。
        lay = _hairpin_alt_layout(params)
        _wf = lay["wf"]
        for _i in range(lay["n"]):
            _xl, _xr = lay["xs"][2 * _i], lay["xs"][2 * _i + 1]
            nx += [_xl - _wf / 2, _xl + _wf / 2, _xr - _wf / 2, _xr + _wf / 2]
            ny += [lay["y_open"][_i], lay["y_bend"][_i] - _wf / 2,
                   lay["y_bend"][_i] + _wf / 2]
        for _yt in lay["y_taps"]:
            ny += [_yt - _wf / 2, _yt + _wf / 2]
    elif template == "coupled_bpf":
        # 平行耦合 BPF：全部盒缘精确入网（缝区/台阶/开路端，#198 口径）
        lay = _coupled_bpf_layout(params)
        for (_bx0, _by0, _bx1, _by1) in lay["boxes"]:
            nx += [_bx0, _bx1]
            ny += [_by0, _by1]
    elif template == "msl_cpw":
        # MSL↔CPWG 过渡：MSL 带缘 / CPW 四条几何边（带缘+地内缘）精确入网
        # （cpw 同口径——窄缝下 edges() 括号线退化，激励盒两边吸附同一线
        # → 激励体积归零，#198）+ 缝中线加密 + 渐变区两端 junction
        wm = float(params.get("w_msl_mm", 1.1134)) * 1e-3
        wc = float(params.get("w_cpw_mm", 0.849)) * 1e-3
        gp = float(params.get("gap_cpw_mm", 0.2)) * 1e-3
        length = float(params.get("line_len_mm", 40.0)) * 1e-3
        trans = float(params.get("trans_len_mm", 10.0)) * 1e-3
        nx += [-wm / 2, wm / 2]
        nx += [-wc / 2, wc / 2, wc / 2 + gp, -(wc / 2 + gp)]
        nx += [wc / 2 + gp / 2, -(wc / 2 + gp / 2)]
        ny += edges(-length / 2, length / 2, 1e-3)
        ny += [-trans / 2, trans / 2]
    elif template == "sma_launcher":
        # SMA 边缘弹射（夹具口径）：同轴三半径 ±r_i/±r_o/±r_os（x 向柱面界）+
        # 集总桥盒 x 边 ±r_i/2 + 带缘 ±w/2；y 向：开口同轴端 Y_B / port1 面
        # Y_P0 / 桥终面 / 板边切口面 Y_E / 针端 Y_PE / 体带终点 Y1 精确入网
        # （#198）；z 向柱面界走 z_mesh_block（字面同源）。几何单源
        # sma_launcher_layout（z 量此处不用，h 取渲染注入值或缺省基板厚）
        lay = params.get("_sma_layout") or sma_launcher_layout(
            params, float(params.get("_h_sub_mm", 0.508)) * 1e-3, base_mm * 1e-3)
        nx += [-lay["ri"], lay["ri"], -lay["ro"], lay["ro"], -lay["ros"], lay["ros"]]
        nx += [-lay["ri"] / 2, lay["ri"] / 2]
        nx += [-lay["w_m"] / 2, lay["w_m"] / 2]
        nx += [-lay["f_w"], lay["f_w"]]                   # 前脸侧缘
        ny += [lay["y_b"], lay["y_p0"], lay["y_p0"] + lay["plen"], lay["y_e"],
               lay["y_pe"], lay["y1"], lay["y_e"] - lay["f_t"]]
    elif template in C3_TEMPLATES:
        # §C3 滤波器族 II：全部盒缘 + 过孔中心 x（柱体 2r 内须有网格线）+
        # 电容盒 y 边精确入网（#198 精确入网；布局单源 _c3_layout，米）
        lay = _c3_layout(template, params)
        for (_bx0, _by0, _bx1, _by1) in lay["boxes"]:
            nx += [_bx0, _bx1]
            ny += [_by0, _by1]
        for (_vx, _vy) in lay["vias"]:
            nx += [_vx]
            ny += [_vy]
        for (_cx0, _cy0, _cx1, _cy1) in lay["caps"]:
            nx += [_cx0, _cx1]
            ny += [_cy0, _cy1]
    elif template in _C4_COUPLER_TEMPLATES:
        # §C4 耦合器族 II：全部盒缘精确入网（耦合缝/指缝/分支臂缘/馈线拐角/
        # air-bridge 立柱边，#198 精确入网；布局单源 _c4_layout，米）
        lay = _c4_layout(template, params)
        for (_nm, x0, y0, _z0, x1, y1, _z1) in lay["boxes"]:
            nx += [x0, x1]
            ny += [y0, y1]
        # 缝中线加密（rm-oe-c4 网格假设复跑，2026-09-18）：耦合器奇模场由缝
        # 电容主导，指缝 38.6µm/耦合缝 82µm < NEAR=base/4 时 SmoothMeshLines 不
        # 细分——lange 两条外侧指缝在缺省与 0.4mm 档均为单格（缝内 0 线，仅中缝
        # 有 x=0），离线审计 #212/#266 判不许起跑。相邻耦合导体（line_*/finger_*）
        # 缝中点精确入网（cpw/msl_cpw 缝中线同口径），审计门：缝内内部线 ≥1。
        nx += _c4_gap_midlines(lay["boxes"])
    elif template in ANTENNA2_TEMPLATES:
        # §10.3 C1 天线族 II：全部盒缘精确入网（含零厚面/馈口盒边，#198；
        # 布局 mm → 近场点 m）
        lay = _ant2_layout(template, params)
        for (_prop, _nm, x0, y0, _z0, x1, y1, _z1) in lay["boxes"]:
            nx += [x0 * 1e-3, x1 * 1e-3]
            ny += [y0 * 1e-3, y1 * 1e-3]
        for _pt in lay["ports"]:
            nx += [_pt["start_mm"][0] * 1e-3, _pt["stop_mm"][0] * 1e-3]
            ny += [_pt["start_mm"][1] * 1e-3, _pt["stop_mm"][1] * 1e-3]
    elif template in ARRAY_TEMPLATES or template in EEP_TEMPLATES:
        # §10.3 C2 阵列族 + §DP-4 P3 EEP 阵列族：贴片/缺口/树/探针全部盒缘
        # 精确入网（#198；布局 mm → 近场点 m，_arr_layout/_eep_layout 单源）
        lay = (_arr_layout(template, params) if template in ARRAY_TEMPLATES
               else _eep_layout(template, params))
        for (_prop, _nm, x0, y0, _z0, x1, y1, _z1) in lay["boxes"]:
            nx += [x0 * 1e-3, x1 * 1e-3]
            ny += [y0 * 1e-3, y1 * 1e-3]
        for _pt in lay["ports"]:
            nx += [_pt["start_mm"][0] * 1e-3, _pt["stop_mm"][0] * 1e-3]
            ny += [_pt["start_mm"][1] * 1e-3, _pt["stop_mm"][1] * 1e-3]
    else:  # patch
        pl = float(params.get("patch_len_mm", 34.9)) * 1e-3
        pw = float(params.get("patch_w_mm", 50.0)) * 1e-3
        off = float(params.get("feed_offset_mm", 5.5)) * 1e-3
        nx += edges(-pl / 2, pl / 2, 1e-3)
        # 底馈盒边必须进网格（官方把 feed.pos 加进 mesh.x；盒不对齐网格时
        # 激励体积坍缩为零 → |S11|≡1，铁律 #3 实测）。馈盒在 x=-off（官方）
        nx += [-off - 0.1e-3, -off + 0.1e-3]
        ny += edges(-pw / 2, pw / 2, 1e-3)
        ny += [-1e-3, 1e-3]
    # 去重（浮点近点合并）
    def _dedup(vs: list[float]) -> list[float]:
        out: list[float] = []
        for v in sorted(vs):
            if not out or v - out[-1] > 1e-6:
                out.append(v)
        return out
    return _dedup(nx), _dedup(ny)


def render_script(
    template: str,
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    mesh_resolution_mm: float = 0.0,
    substrate: dict[str, Any] | None = None,
    excite_port: int = 1,
    far_field: bool = False,
    sar: bool = False,
) -> str:
    """Render template to CSXCAD script text（官方方法学基线）。

    excite_port：主激励端口号（1 基）。多端口模板的整 S 矩阵由适配器层
    按 excite_port=1..N 渲染 N 份脚本、进程隔离各跑一次后装配（#208
    pt3/pt4 教训：进程内跨 Run 复用 CSX/端口包装器踩绑定对象生命周期
    雷——Run(cleanup=True) 会销毁激励属性乃至 CSX 本体）。

    far_field（WP4.1/D4）：辐射模板（patch/dipole）注入官方 nf2ff 盒
    （CreateNF2FFBox，域缩 4×网格，Simple Patch Antenna 教程口径）；
    run 后 CalcNF2FF 落盘 farfield_cut.csv / farfield3d.csv /
    farfield_meta.json（方向图/Dmax/效率 η=Prad/P_acc）。nf2ff 依赖
    dump 面输出，注入时 Run 不再传 disable_dumps=True。
    sar：仅 dipole（官方 Dipole SAR 教程口径）——组织等效模型盒
    （皮肤层文献值 εr=50/κ=0.65/ρ=1100）+ DumpType 29 原始 SAR dump +
    SAR_Calculation(mass=1g, IEEE_62704) → sar.csv。
    """
    params = dict(params)
    params["_excite_port"] = max(1, min(4, int(excite_port)))
    # rm-oe-c9 合规网格/步数旋钮（真机复跑消费；缺省=旧口径逐字节不变）：
    #   _near_ratio → NEAR = base/_near_ratio（缺省 4=官方 base/4；SSL 复跑 10
    #                 使 NEAR=0.114mm ≤ w/6=0.1218mm）
    #   _sub_cells  → 基板 z 向格数（G3 2026-09-22 缺省分档：CPW/槽下场族
    #                 msl_cpw/cpw 缺省 8——zconv 定案 GRID_UNDERRES+SATURATED_
    #                 RESIDUAL（runs/msl_cpw_zconv，网格份额 78%，sub8 回 ±2%
    #                 锚门内；_SUB_CELLS_8_TEMPLATES 见模块头）；其余模板缺省
    #                 4=官方 substrate_cells=4 旧口径逐字节不变；#313 z 向
    #                 地板项；微带/lange 等 z 块同消费，SSL/CPS 各自点数换算
    #                 见 _sub_half_pts/_cps_sub_pts。显式传参仍最高优先）
    #   _nrts       → FDTD 步数上限（缺省 100000 官方口径；细网格 dt 减半后
    #                 抬到 150000 防 NrTS 触顶误判未收敛，#266/#268）
    _knob_near_ratio = float(params.get("_near_ratio", 4) or 4)
    _knob_sub_cells_default = (
        8 if template in _SUB_CELLS_8_TEMPLATES else _SUB_CELLS_DEFAULT)
    _knob_sub_cells = int(
        params.get("_sub_cells", _knob_sub_cells_default)
        or _knob_sub_cells_default)
    _nrts = int(params.get("_nrts", 100000) or 100000)
    #   _end_criteria → 显式 EndCriteria（如 1e-8=−80dB；cps_xrefine addendum：
    #                 缺省 −60dB 能量判据在长脉冲激励末 ~95% 处提前自停，
    #                 port_ut 时窗不覆盖激励全程触发 V1 截断门，runs/cps_xrefine/
    #                 run1 实证）——缺省 None 不加参逐字节不变（官方口径）
    _knob_end_criteria = params.get("_end_criteria")
    _end_criteria_repr = (
        repr(float(_knob_end_criteria)) if _knob_end_criteria else None)
    _end_criteria_src = (
        f", EndCriteria={_end_criteria_repr}" if _end_criteria_repr else "")
    #   _x_refine   → cps 缝区 x 向加密对照（wf:cps-xrefine；缺省 0=逐字节
    #                 不变）：N>0 把缝 [−gap/2, gap/2] 等分 2N 格、内部线精确
    #                 入网（#311 缝中点精确入网法推广；SmoothMeshLines 不细分
    #                 <NEAR 区间——显式 AddLine 恒保留）。单变量对照旋钮：
    #                 只动 x 缝区线，y/z/BASE/激励/NrTS/提取链逐项不变。
    _knob_x_refine = int(params.get("_x_refine", 0) or 0)
    substrate = substrate or _DEFAULT_SUB
    far_field = bool(far_field)
    sar = bool(sar)
    if (far_field or sar) and not _TEMPLATE_RADIATOR.get(template, False):
        raise ValueError(
            f"far_field/sar 仅支持辐射模板（patch/dipole），不支持: {template}")
    if sar and template != "dipole":
        raise ValueError("sar 仅支持 dipole（官方 Dipole SAR 教程口径）；"
                         "patch 请用 far_field")
    if template in SLOTLINE_FAMILY_TEMPLATES:
        # 槽线族：整脚本渲染器（附加模块升格正式入口，分发见文末 SLOTLINE_FAMILY 段）
        return slotline_family_render(template, params, freq_range_ghz,
                                      mesh_resolution_mm=mesh_resolution_mm,
                                      substrate=substrate,
                                      excite_port=params["_excite_port"])
    if template in PORTLESS_TEMPLATES:
        # §MS_METASURFACE 阵模板（文末 MS_METASURFACE 段）：无端口软平面
        # 照明散射体整脚本渲染器（nf2ff 散射远场；无 sparams.csv）
        return ms_array_render(template, params, freq_range_ghz,
                               mesh_resolution_mm=mesh_resolution_mm,
                               substrate=substrate)
    if template in COIL_NFC_TEMPLATES:
        # §COIL_NFC NFC 线圈（文末 COIL_NFC 段）：单端口馈隙 LumpedPort
        # 整脚本渲染器（MQS 频段几何驱动网格；中跳线桥 + 全 MUR）
        return coil_nfc_render(template, params, freq_range_ghz,
                               mesh_resolution_mm=mesh_resolution_mm,
                               substrate=substrate,
                               excite_port=params["_excite_port"])
    if template in MMWAVE_SERIES_TEMPLATES:
        # §MMWAVE_SERIES_ARRAY 行波串馈毫米波阵（文末 MMWAVE_SERIES_ARRAY 段）：
        # 单端口 MSLPort（PML_8 域边入）+ 链末匹配集总负载到地整脚本渲染器
        return mmwave_series_render(template, params, freq_range_ghz,
                                    mesh_resolution_mm=mesh_resolution_mm,
                                    substrate=substrate,
                                    far_field=far_field)
    render_fns = {
        "wilkinson": _wilk_lines, "patch": _patch_lines,
        "branchline": _branchline_lines, "dipole": _dipole_lines,
        "stepped_impedance": _stepped_lines, "coupled_line": _coupled_lines,
        "mline": _mline_lines, "cpw": _cpw_lines,
        "wstep": _wstep_lines, "stripline": _stripline_lines,
        # C9 传输线族 II：共面带（LumpedPort 差分直馈）/ 悬置带线（StripLinePort）
        "cps": _cps_lines, "suspended_stripline": _suspended_stripline_lines,
        "tjunc": _tjunc_lines, "bend": _bend_lines,
        "via": _via_lines, "atten_pi": _atten_pi_lines,
        "atten_t": _atten_t_lines, "ratrace": _ratrace_lines,
        "gysel": _gysel_lines, "hairpin": _hairpin_lines,
        # 交替取向 hairpin 变体（几何单源 _hairpin_layout(orientation=...)，w2g）
        "hairpin_alt": _hairpin_alt_lines,
        "coupled_bpf": _coupled_bpf_lines,
        "msl_cpw": _msl_cpw_lines, "sma_launcher": _sma_launcher_lines,
        # §10.3 C1 天线族 II（附加模板段，几何段单源 _ant2_body）
        "monopole": _monopole_lines, "pifa": _pifa_lines, "ifa": _ifa_lines,
        "loop": _loop_lines, "helix": _helix_lines, "slot": _slot_lines,
        # §C3 滤波器族 II（几何段单源 _c3_body）
        "interdigital": _interdigital_lines, "combline": _combline_lines,
        "sir_bpf": _sir_bpf_lines,
        # §C4 耦合器族 II（附加模板段，几何段单源 _c4_layout）
        "cline_coupler": _cline_coupler_lines,
        "branchline_2sect": _branchline_2sect_lines,
        "lange": _lange_lines,
        # §10.3 C2 阵列族（几何段单源 _arr_layout / _arr_body，文末 C2 段）
        "patch_array_1x4": _patch_array_1x4_lines,
        "patch_array_2x2": _patch_array_2x2_lines,
        "patch_array_series": _patch_array_series_lines,
        # §DP-4 P3 EEP 阵列族（几何段单源 _eep_layout / _eep_body，文末 EEP 段）
        "patch_eep_2x2": _patch_eep_2x2_lines,
        "patch_eep_1x4": _patch_eep_1x4_lines,
        # SIW 族首族（文末 SIW 段，几何/端口/域单源 siw_layout）
        "siw": _siw_lines,
        # SIW 族第二成员（文末 MSL_SIW_TAPER 段，几何/端口/域单源
        # msl_siw_taper_layout；df6 A2）
        "msl_siw_taper": _msl_siw_taper_lines,
        # §MS_METASURFACE 超表面/FSS 单元族（文末 MS_METASURFACE 段，几何/
        # 端口/域单源 ms_unit_layout；df6 DP-10）；阵模板 ms_array_NxN 走
        # 整脚本渲染器早分发（render_script 顶部 PORTLESS 分发）
        "ms_patch": _ms_patch_lines,
        "ms_cross": _ms_cross_lines,
        "ms_jcross": _ms_jcross_lines,
    }
    # cps：LumpedPort R=闭式 Z0（CPS 无地共形闭式 _cps_ri，按本次渲染的基板
    # er/h 精算，惰性导入；同时作 CalcPort 参考阻抗——R≠50 时若仍按 50Ω 归一，
    # 匹配线会显示 |(R−50)/(R+50)| 的假失配）。其余模板参考阻抗文本保持 "50"
    # 逐字节不变。
    z_ref_txt = "50"
    if template == "cps":
        from rfauto.core.calculators import _cps_ri

        _cps_z0 = _cps_ri(float(params.get("w_mm", 2.95)),
                          float(params.get("gap_mm", 0.5)),
                          float(substrate["h_mm"]), float(substrate["er"]))[1]
        params["_cps_r_ohm"] = round(_cps_z0, 4)
        z_ref_txt = repr(params["_cps_r_ohm"])
    elif template == "siw":
        # R=Z_PV=2b·Z_TE/w_eff 闭式（文末 SIW 段 _siw_r_port_ohm）；正常路径
        # 已由 siw_layout 注入 _siw_r_ohm，此处只兜底直调缺键
        if "_siw_r_ohm" not in params:
            params["_siw_r_ohm"] = round(_siw_r_port_ohm(
                float(params.get("w_mm", 12.1317)),
                float(params.get("d_mm", 0.6)),
                float(params.get("s_mm", 1.0)),
                float(substrate["er"]),
                float(params.get("h_mm", substrate["h_mm"])),
                (freq_range_ghz[0] + freq_range_ghz[1]) / 2), 4)
        z_ref_txt = repr(params["_siw_r_ohm"])
    elif template in MS_UNIT_TEMPLATES:
        # §MS_METASURFACE 单元（文末 MS_METASURFACE 段）：TEM 波导模拟器片
        # 端口 R=η0·a/b（方胞=η0），CalcPort 同参考——R≠50 时按 50Ω 归一会
        # 显示 |(R−50)/(R+50)| 假失配（cps 同款口径）；layout 注入在 base_m
        # 就绪后的布局单源块（几何/守卫/近场线同源）
        from rfauto.core.metasurface_lut import ETA0_OHM

        z_ref_txt = repr(round(ETA0_OHM, 4))
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = max((freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9, 1e6)
    er = float(substrate["er"])
    h_m = float(substrate["h_mm"]) * 1e-3
    tan_d = float(substrate.get("tan_d", 1e-3))
    f_max = f0 + fc  # 频段最高频率（激励带 edge）
    # 官方口径：base = 基板内波长 /50；mesh_resolution_mm>0 时作为 base 覆盖
    base_m = (3e8 / (f_max * (er ** 0.5)) / 50 if not mesh_resolution_mm
              else float(mesh_resolution_mm) * 1e-3)
    # ratrace：渲染半径 R/k(BASE) 随网格档标度（ratrace_ring_mesh_k）——base
    # 先于 body 计算并经 params 注入，几何段与近场线同 BASE 同 k
    params["_base_mm"] = base_m * 1e3
    # sma_launcher：几何单源 sma_launcher_layout 一次计算，字面量注入 body /
    # z 网格 / 基板块（夹具口径 Z_G 抬板），近场线同源（_near_points 分支）
    params["_h_sub_mm"] = h_m * 1e3
    if template == "sma_launcher":
        params["_sma_layout"] = sma_launcher_layout(params, h_m, base_m)
    if template == "siw":
        # siw：几何/端口/域单源 siw_layout（文末 SIW 段；矩形域 DOM_X/DOM_Y
        # 字面注入见 f-string _dom_x_txt/_dom_y_txt）。h_mm 模板参数优先于
        # substrate（slotline_family_params 同款合并），z 网格/基板盒/body/
        # 近场线全部同源消费
        h_m = float(params.get("h_mm", h_m * 1e3)) * 1e-3
        params["_h_sub_mm"] = h_m * 1e3
        params["_siw_layout"] = siw_layout(params, freq_range_ghz, base_m, h_m)
        params["_siw_r_ohm"] = round(params["_siw_layout"]["r_port"], 4)
    elif template == "msl_siw_taper":
        # msl_siw_taper：几何/端口/域单源 msl_siw_taper_layout（文末
        # MSL_SIW_TAPER 段；矩形域 DOM_X/DOM_Y 字面注入同 siw）。h_mm 模板
        # 参数优先于 substrate（siw 同款合并），锥宽设计链/z 网格/近场线同源
        h_m = float(params.get("h_mm", h_m * 1e3)) * 1e-3
        params["_h_sub_mm"] = h_m * 1e3
        params["_msl_siw_taper_layout"] = msl_siw_taper_layout(
            params, freq_range_ghz, base_m, h_m)
    elif template in MS_UNIT_TEMPLATES:
        # §MS_METASURFACE 单元（文末 MS_METASURFACE 段）：几何/端口/域/
        # 近场线单源 ms_unit_layout（守卫在此层：NEAR≤最小缝/3 违反抛错）
        h_m = float(params.get("h_mm", h_m * 1e3)) * 1e-3
        params["_h_sub_mm"] = h_m * 1e3
        params["_ms_layout"] = ms_unit_layout(
            template, params, freq_range_ghz, base_m, h_m)
    body = render_fns.get(template, _patch_lines)(params)
    near_m = base_m / _knob_near_ratio
    if template in C3_TEMPLATES:
        # §C3 耦合缝网格守卫（#266）：NEAR ≤ 最小耦合缝/3，违反即抛错——缺省
        # mesh=0（λ_sub/50）下 NEAR 0.285mm > 外缝 0.139~0.242mm 曾致缝内零
        # 内部线、外 Q 建模粗、峰位 −5%（真机审计）；不许静默粗网格
        c3_gap_mesh_guard(template, params, near_m)
    radiator = _TEMPLATE_RADIATOR.get(template, False)
    air_top = (3e8 / f_max / 4) if radiator else 5e-3
    air_side = (3e8 / f_max / 4) if radiator else 0.0
    port_axes = _TEMPLATE_PORT_AXES.get(template, ("y",))
    b_x0, b_x1 = "PML_8" if "x" in port_axes else "MUR", \
        "PML_8" if "x" in port_axes else "MUR"
    b_y0, b_y1 = "PML_8" if "y" in port_axes else "MUR", \
        "PML_8" if "y" in port_axes else "MUR"
    # §MS_METASURFACE 波导模拟器对壁（文末 MS_METASURFACE 段）：x 对壁 PEC /
    # y 对壁 PMC ≡ 法向入射无限阵（E∥x 极化前提）——覆盖 port_axes 缺省
    if template in _TEMPLATE_WALL_BC:
        b_x0, b_x1, b_y0, b_y1 = _TEMPLATE_WALL_BC[template]
    near_x, near_y = _near_points(template, params, base_mm=params["_base_mm"])
    if template == "cps" and _knob_x_refine > 0:
        # cps 缝区 x 向加密（wf:cps-xrefine，单变量对照）：缝 [−gap/2, gap/2]
        # 等分 2N 格，内部线（含缝中线 x=0 去重）精确入网。CPS 奇模场集中于
        # 缝区——引擎 εeff +13.3% 归因候选①"缝 0.5mm 仅 2 格"的收敛性验证档
        # （runs/cps_xrefine/criteria.md 预声明；c9 复跑遗留 TODO）。
        _gap_half_m = float(params.get("gap_mm", 0.5)) * 1e-3 / 2.0
        near_x.extend(_xv for _xv in (
            _gap_half_m * (_i / _knob_x_refine - 1.0)
            for _i in range(1, 2 * _knob_x_refine))
            if all(abs(_xv - _e) > 1e-9 for _e in near_x))
        near_x.sort()

    # tjunc：三端口 β 的 CSV 必须在 _port3.CalcPort 之后写（固定槽位的
    # beta_block 只覆盖 port1/2），独立第二插桩槽 + 存在性守卫
    beta_block3 = ""
    if template == "tjunc":
        beta_block3 = (
            '# tjunc 锚：三端口 β 金标准（对照闭式 εeff，|Δ|≤2%）\n'
            '_b3 = getattr(_port3, "beta", None)\n'
            'if _b3 is not None:\n'
            '    with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
            '              "w", newline="") as _bfh:\n'
            '        _bw = csv.writer(_bfh)\n'
            '        _bw.writerow(["freq_hz", "beta1_rad_per_m", '
            '"beta2_rad_per_m", "beta3_rad_per_m"])\n'
            '        for _i, _fi in enumerate(f):\n'
            '            _bw.writerow([_fi, float(np.real(_port1.beta[_i])), '
            'float(np.real(_port2.beta[_i])), '
            'float(np.real(_port3.beta[_i]))])\n'
        )


    # dipole（WP1.3）：自由空间器件特判——底边界 MUR（非 PEC 地，
    # 镜像破坏输入阻抗）、域 z 向下延 λ0/4、无基板（官方 Helical/
    # Dipole-SAR 教程口径）
    is_dipole = template == "dipole"
    # §10.3 C1 loop（2026-09-16 自由空间改造）：dipole 同款——环面 z=0、无基板
    # 无地、底 MUR、域 z 向下延 λ0/4（贴地口径镜像抵消辐射 R=0.56Ω 实证）
    is_free_space = is_dipole or template in _ANTENNA2_FREE_SPACE_TEMPLATES
    # slot：地面=z=0 有限金属板（槽向下辐射），底 MUR（dipole 同款；
    # PEC 底边界会短路槽）
    # cps（C9）：无地共面带，基板下方空气——底 MUR + 域向下延 AIR_TOP
    # ms_cross/ms_jcross（DP-10）：透射型 FSS——屏浮于空气区，底 MUR（ms_patch
    # 反射型保持 PEC=地面）
    bottom_bc = ("MUR" if (is_free_space
                           or template in ("via", "slot", "cps",
                                           "ms_cross", "ms_jcross"))
                 else "PEC")
    # stripline / suspended_stripline / siw：对称双面敷铜（siw=上下金属板），
    # 上地 = z-max PEC 边界（下地 = z-min PEC）
    top_bc = "PEC" if template in ("stripline", "suspended_stripline",
                                   "siw") else "MUR"
    # rm-oe-c9 单变量对照旋钮：_boundary 六元覆盖 [x0,x1,y0,y1,bot,top]
    # （缺省 None=模板映射逐字节不变；CPS MUR→PML_8 归因对照跑用）
    if params.get("_boundary"):
        _bc_ovr = [str(v) for v in params["_boundary"]]
        if len(_bc_ovr) != 6:
            raise ValueError(
                f"_boundary 需 6 元 [x0,x1,y0,y1,bot,top]，得 {len(_bc_ovr)}")
        b_x0, b_x1, b_y0, b_y1, bottom_bc, top_bc = _bc_ovr

    # 尾部插桩（#208）：默认模板 = S31/S23 双激励路径（+ tjunc beta_block3）；
    # ratrace/§C4 四端口族 = 单激励 4 探针全记录（一列 9 列 CSV）。整 4×4 矩阵
    # 由适配器层按 excite_port=1..4 渲染 4 份脚本、进程隔离各跑一次后装配
    # （skrf .s4p 主产物）——进程内跨 Run 复用 CSX/端口包装器踩绑定对
    # 象生命周期雷（Run(cleanup=True) 销毁激励属性/CSX，pt3/pt4 实测）。
    if template in _FOUR_PORT_ROTATION_TEMPLATES:
        ep = max(1, min(4, int(params.get("_excite_port", 1) or 1)))
        loop_block = ""
        s31_block = (
            '# ' + template + ' 单激励列（进程隔离轮转的第 ' + str(ep) +
            ' 列）：excite=0 端口仅探针仍记录，一列四元素全出。\n'
            '_port3.CalcPort(SIM_PATH, f, ref_impedance=50)\n'
            '_port4.CalcPort(SIM_PATH, f, ref_impedance=50)\n'
            '_SREF = _port' + str(ep) + '.uf_inc\n'
            'S11 = _port1.uf_ref / _SREF\n'
            'S21 = _port2.uf_ref / _SREF\n'
            'S31 = _port3.uf_ref / _SREF\n'
            'S41 = _port4.uf_ref / _SREF\n'
            'with open(CSV_PATH, "w", newline="") as fh:\n'
            '    w = csv.writer(fh)\n'
            '    w.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", '
            '"im_S21", "re_S31", "im_S31", "re_S41", "im_S41"])\n'
            '    for _i, _fi in enumerate(f):\n'
            '        w.writerow([_fi, S11[_i].real, S11[_i].imag, '
            'S21[_i].real, S21[_i].imag, S31[_i].real, S31[_i].imag, '
            'S41[_i].real, S41[_i].imag])\n'
            '_LOOP_DONE = True\n'
        )
    else:
        loop_block = ""
        s31_block = (
            '# S31 免费（port3 探针在 port1 激励的同一 run 里已记录）；S23 需第二激励\n'
            '# （port3 激励）——翻转激励使能后新建 FDTD 复用 CSX/网格重跑（时间 ×2，\n'
            '# 2026-09-04）。任何一步不可用就跳过对应列，不阻塞主 S 参数输出。\n'
            'S31 = None\n'
            'S23 = None\n'
            'try:\n'
            '    _port3.CalcPort(SIM_PATH, f, ref_impedance=50)\n'
            '    S31 = _port3.uf_ref / _port1.uf_inc\n'
            'except Exception:\n'
            '    S31 = None\n'
            'if S31 is not None:\n'
            '    try:\n'
            '        _SIM3 = SIM_PATH + "_p3exc"\n'
            '        # 找金属属性对象（body 里变量名随模板不同：mline/patch/filt...）\n'
            '        _metal3 = None\n'
            '        for _i in range(CSX.GetQtyProperties()):\n'
            '            _pr = CSX.GetProperty(_i)\n'
            '            if str(_pr.GetTypeString()) == "Metal" and str(_pr.GetName()) != "ground":\n'
            '                _metal3 = _pr\n'
            '                break\n'
            '        assert _metal3 is not None\n'
            '        # port3 的激励副本（excite=0 的端口不创建激励属性，无法就地翻转——\n'
            '        # 2026-09-04 实测）：PortNamePrefix 隔离探针命名，几何复用 _port3\n'
            '        _port3e = MSLPort(CSX, port_nr=3, metal_prop=_metal3,\n'
            '                          start=np.array(_port3.start), stop=np.array(_port3.stop),\n'
            '                          prop_dir=int(_port3.prop_ny), exc_dir=int(_port3.exc_ny),\n'
            '                          excite=1, FeedShift=10 * NEAR,\n'
            '                          MeasPlaneShift=float(_port3.measplane_shift),\n'
            '                          PortNamePrefix="e3_")\n'
            '        # 第二激励轮前禁用旧激励属性：port1 excite=1 的激励属性仍\n'
            '        # 随 CSX 存活，不禁止则第二 run 双激励、S23 被同相 -3dB 直\n'
            '        # 通污染（gysel pt1 实测 S23=-3.1dB 且相位=S21=-130°）。\n'
            '        # 直接操作 CSX 属性、不经旧 wrapper（#208 生命周期雷）；\n'
            '        # GetTypeString()=="Excitation" 绑定实测锚定。\n'
            '        for _i in range(CSX.GetQtyProperties()):\n'
            '            _pr = CSX.GetProperty(_i)\n'
            '            if (str(_pr.GetTypeString()) == "Excitation"\n'
            '                    and not str(_pr.GetName()).startswith("e3_")):\n'
            '                _pr.SetEnabled(0)\n'
            '        _FDTD3 = openEMS(NrTS=' + repr(_nrts) + ')\n'
            '        _FDTD3.SetCSX(CSX)\n'
            '        _FDTD3.SetGaussExcite(F0, FC)\n'
            '        _FDTD3.SetBoundaryCond(["@BX0@", "@BX1@", "@BY0@", '
            '"@BY1@", "@BBOT@", "@BTOP@"])\n'
            '        _FDTD3.Run(_SIM3, verbose=0, disable_dumps=True, cleanup=True)\n'
            '        _port3e.CalcPort(_SIM3, f, ref_impedance=50)\n'
            '        _port2.CalcPort(_SIM3, f, ref_impedance=50)\n'
            '        S23 = _port2.uf_ref / _port3e.uf_inc\n'
            '    except Exception:\n'
            '        S23 = None\n'
            '\n'
        )
        s31_block += beta_block3
    # 边界条件 token 注入（s31_block/loop_block 是普通字符串，不吃外层
    # f-string 的替换——用 @TOKEN@ 占位此处统一填入，避免双重转义）
    _bc_map = {
        '"@BX0@"': f'"{b_x0}"', '"@BX1@"': f'"{b_x1}"',
        '"@BY0@"': f'"{b_y0}"', '"@BY1@"': f'"{b_y1}"',
        '"@BBOT@"': f'"{bottom_bc}"', '"@BTOP@"': f'"{top_bc}"',
    }
    for _tok, _val in _bc_map.items():
        s31_block = s31_block.replace(_tok, _val)
        loop_block = loop_block.replace(_tok, _val)

    def fmt_list(vs: list[float]) -> str:
        return "[" + ", ".join(repr(v) for v in vs) + "]"

    # 均匀线锚模板（mline/cpw）：额外写 CalcPort 自算 β（金标准判据
    # #162——uf_ref/uf_inc 相位含端口分解伪象不可判读 #161，β 才是与
    # 闭式 εeff 对照的正确量）
    # cpw 需要额外的端口类 import（footer 固定 import 不含 CPWPort）
    extra_ports_import = ", CPWPort" if template in ("cpw", "msl_cpw") else ""
    extra_ports_import += (", StripLinePort"
                           if template in ("stripline", "suspended_stripline")
                           else "")
    extra_ports_import += (
        ", LumpedPort" if "LumpedPort" not in extra_ports_import else "")
    beta_block = ""
    if template in ("mline", "cpw", "stripline", "suspended_stripline",
                    "wstep", "bend", "via",
                    "atten_pi", "atten_t", "ratrace", "gysel", "branchline",
                    "hairpin", "hairpin_alt", "coupled_bpf", "msl_cpw", "sma_launcher",
                    "cline_coupler", "branchline_2sect", "lange",
                    "interdigital", "combline", "sir_bpf", "cps", "siw",
                    "msl_siw_taper"):
        if template == "wstep":
            # 双段两 β + 引擎自算线阻抗 ZL（W2⑤ 定案 (a)，2026-09-16）：
            # ReadUIData 用三探针算 Z_ref=sqrt(Et·dEt/(Ht·dHt))（驻波因子精确
            # 抵消，激励端亦有效），随后 CalcPort(ref_impedance=50) 把它覆盖——
            # 此处重读一次恢复 ZL 落盘（uf_inc/uf_ref 不受影响，S 列口径不变；
            # sparams.csv 契约不动）。ZL 供后处理 renorm_engine_s_to_ref 做
            # 引擎自洽基（HJ-vs-引擎 Z 偏差诊断），β 仍是金标准锚（#162）。
            beta_block = (
                '# wstep 锚：双端口 β 金标准（对照两段闭式 εeff，|Δ|≤2%）+ 引擎\n'
                '# 自算线阻抗 ZL（ReadUIData 重读恢复被 CalcPort ref=50 覆盖的 Z_ref）\n'
                '_port1.ReadUIData(SIM_PATH, f)\n'
                '_port2.ReadUIData(SIM_PATH, f)\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta1_rad_per_m", '
                '"beta2_rad_per_m", "re_zl1_ohm", "im_zl1_ohm", '
                '"re_zl2_ohm", "im_zl2_ohm"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port1.beta[_i])), "
                "float(np.real(_port2.beta[_i])), "
                "float(np.real(_port1.Z_ref[_i])), "
                "float(np.imag(_port1.Z_ref[_i])), "
                "float(np.real(_port2.Z_ref[_i])), "
                "float(np.imag(_port2.Z_ref[_i]))])\n"
            )
        elif template == "mline":
            # mline 单 β 金标准 + 引擎自算线阻抗 ZL 双端口落盘（W3②，2026-09-16）：
            # 与 wstep 同法 ReadUIData 重读恢复被 CalcPort(ref=50) 覆盖的 Z_ref。
            # 列契约：前两列 freq_hz,beta_rad_per_m **逐字节不变**（scripts/
            # wp39_followup_run.read_port_beta_csv / engine_benchmark_mline._beta_eps
            # 按列位置读 r[0]/r[1]；health_service 按 "beta*rad_per_m" 名匹配），
            # 追加 beta2 + re/im_zl{1,2}_ohm 供 wp39 引擎 ZL 基匹配判据
            # （service/wp39_benchmark.mline_port_match_health）——H1 实证：50Ω 基
            # |S11| 伪底 ≡ |Γ(ZL_engine,50)|（归档 6 档残差 ≤0.94dB，换基后 −50dB）。
            beta_block = (
                '# mline 锚：β 金标准（对照闭式 εeff，|Δ|≤2%）+ 引擎自算线阻抗 ZL\n'
                '# （ReadUIData 重读恢复被 CalcPort ref=50 覆盖的 Z_ref；两端口）\n'
                '_port1.ReadUIData(SIM_PATH, f)\n'
                '_port2.ReadUIData(SIM_PATH, f)\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta_rad_per_m", '
                '"beta2_rad_per_m", "re_zl1_ohm", "im_zl1_ohm", '
                '"re_zl2_ohm", "im_zl2_ohm"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port1.beta[_i])), "
                "float(np.real(_port2.beta[_i])), "
                "float(np.real(_port1.Z_ref[_i])), "
                "float(np.imag(_port1.Z_ref[_i])), "
                "float(np.real(_port2.Z_ref[_i])), "
                "float(np.imag(_port2.Z_ref[_i]))])\n"
            )
        elif template in ("via", "msl_cpw"):
            # 双段两 β：port1/port2 各自 CalcPort β → 分段 εeff 锚
            beta_block = (
                f'# {template} 锚：双端口 β 金标准（对照两段闭式 εeff，|Δ|≤2%）\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta1_rad_per_m", '
                '"beta2_rad_per_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port1.beta[_i])), "
                "float(np.real(_port2.beta[_i]))])\n"
            )
        elif template == "sma_launcher":
            # port1 = 同轴截面集总桥（LumpedPort 无 beta 属性，直取会
            # AttributeError）；β 金标准只写 port2（MSL HJ 闭式锚）
            beta_block = (
                '# sma_launcher 锚：port2 β 金标准（对照 MSL HJ 闭式 εeff，'
                '|Δ|≤2%）；port1=同轴截面集总桥无 β\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta2_rad_per_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port2.beta[_i]))])\n"
            )
        elif template == "cps":
            # C9 cps 端口几何落盘（2026-09-18 w2f 后续定标批 ②，同 SSL beta 块
            # 先例）：LumpedPort 无 β 属性（sma_launcher 同坑），εeff=S21 解缠
            # 相位斜率口径的线长不确定度=端口元落格——端口参考面=端口元 E 场
            # 节点（Yee y 向 cell 中心），相对名义 Y0/Y1 可吸附 ±1 格 → 标称线
            # 长口径 εeff 地板 ±5.7%（±1.14mm/40mm，pt1 postmortem）。按终网格
            # 实测 port_y1/2_m 与 plane_dist_m 落盘，判读器 G2 用实测线长替代
            # 标称 L，地板压到 ~±1%（±半格/40mm）。
            beta_block = (
                '# cps 锚：端口元 y 坐标/实测差分线长（LumpedPort 无 β，'
                'w2f 定标批 ②）\n'
                '_ys = np.asarray(mesh.GetLines("y"), dtype=float)\n'
                'def _y_node(_yv):\n'
                '    _j = int(np.clip(np.searchsorted(_ys, _yv) - 1, 0, '
                '_ys.size - 2))\n'
                '    return float(0.5 * (_ys[_j] + _ys[_j + 1]))\n'
                '_y1_node = _y_node(Y0)\n'
                '_y2_node = _y_node(Y1)\n'
                '_plane_dist = _y2_node - _y1_node\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "port_y1_m", "port_y2_m", '
                '"plane_dist_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, _y1_node, _y2_node, _plane_dist])\n"
            )
        elif template == "siw":
            # siw 锚：端口元 y 坐标/实测差分线长（cps 同契约；LumpedPort 无 β，
            # criteria §3）——S21 解缠相位斜率 ÷ plane_dist = β 测量（OE 锚 G1
            # 主判）；Y0/Y1=端口盒中心（测量面），落格坐标由终网格实测
            beta_block = (
                '# siw 锚：端口元 y 坐标/实测差分线长（LumpedPort 无 β，'
                'cps 同契约）\n'
                '_ys = np.asarray(mesh.GetLines("y"), dtype=float)\n'
                'def _y_node(_yv):\n'
                '    _j = int(np.clip(np.searchsorted(_ys, _yv) - 1, 0, '
                '_ys.size - 2))\n'
                '    return float(0.5 * (_ys[_j] + _ys[_j + 1]))\n'
                '_y1_node = _y_node(Y0)\n'
                '_y2_node = _y_node(Y1)\n'
                '_plane_dist = _y2_node - _y1_node\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "port_y1_m", "port_y2_m", '
                '"plane_dist_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, _y1_node, _y2_node, _plane_dist])\n"
            )
        elif template == "msl_siw_taper":
            # msl_siw_taper 锚：双端口 β（MSLPort 线基=馈线 β，HJ 锚参照
            # mline 口径）+ 引擎自算线阻抗 ZL（ReadUIData 重读恢复被 CalcPort
            # ref=50 覆盖的 Z_ref，wstep/mline W3② 法）+ 测量面间距（SSL 同式
            # 2·DOM_Y−两 measplane_shift）——line_z0="engine" 线基反演判读
            # 旋钮（#250/#280）消费 zl 列；前两列 freq_hz,beta_rad_per_m 契约
            # 逐字节不变（health_service 按名匹配）
            beta_block = (
                '# msl_siw_taper 锚：双端口 β 金标准 + 引擎自算 ZL + 测量面间距\n'
                '_port1.ReadUIData(SIM_PATH, f)\n'
                '_port2.ReadUIData(SIM_PATH, f)\n'
                '_plane_dist = float(2 * DOM_Y - _port1.measplane_shift '
                '- _port2.measplane_shift)\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta_rad_per_m", '
                '"beta2_rad_per_m", "re_zl1_ohm", "im_zl1_ohm", '
                '"re_zl2_ohm", "im_zl2_ohm", "plane_dist_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port1.beta[_i])), "
                "float(np.real(_port2.beta[_i])), "
                "float(np.real(_port1.Z_ref[_i])), "
                "float(np.imag(_port1.Z_ref[_i])), "
                "float(np.real(_port2.Z_ref[_i])), "
                "float(np.imag(_port2.Z_ref[_i])), _plane_dist])\n"
            )
        elif template == "suspended_stripline":
            # C9 悬置带线（2026-09-18 w2f-c9-refs 判读口径审）：前两列 freq_hz,
            # beta_rad_per_m 契约逐字节不变（smoke 判读器按列位置读）；追加
            # port2 β、两端口引擎自算线阻抗 ZL（ReadUIData 重读恢复被
            # CalcPort ref=50 覆盖的 Z_ref，同 mline W3② 法）与两测量面间距
            # plane_dist_m（2·BOARD − 两端口 measplane_shift；S21 相位斜率与
            # 端口三点差分 β 的自洽门 G0 需精确面距，网格吸附 ±BASE/2 不再
            # 进入判读不确定度）。
            beta_block = (
                '# suspended_stripline 锚：β 金标准 + 引擎 ZL + 测量面间距\n'
                '_port1.ReadUIData(SIM_PATH, f)\n'
                '_port2.ReadUIData(SIM_PATH, f)\n'
                '_plane_dist = float(2 * BOARD - _port1.measplane_shift '
                '- _port2.measplane_shift)\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta_rad_per_m", '
                '"beta2_rad_per_m", "re_zl1_ohm", "im_zl1_ohm", '
                '"re_zl2_ohm", "im_zl2_ohm", "plane_dist_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port1.beta[_i])), "
                "float(np.real(_port2.beta[_i])), "
                "float(np.real(_port1.Z_ref[_i])), "
                "float(np.imag(_port1.Z_ref[_i])), "
                "float(np.real(_port2.Z_ref[_i])), "
                "float(np.imag(_port2.Z_ref[_i])), _plane_dist])\n"
            )
        else:
            beta_block = (
                f'# {template} 锚：β 金标准数据（对照闭式 εeff，|Δ|≤2%）\n'
                'with open(CSV_PATH.replace("sparams.csv", "port_beta.csv"),\n'
                '          "w", newline="") as _bfh:\n'
                "    _bw = csv.writer(_bfh)\n"
                '    _bw.writerow(["freq_hz", "beta_rad_per_m"])\n'
                "    for _i, _fi in enumerate(f):\n"
                "        _bw.writerow([_fi, float(np.real(_port1.beta[_i]))])\n"
            )

    # sma_launcher z 网格字面量（米，几何单源 _sma_layout：夹具口径，见
    # sma_launcher_layout）：z=0 夹具底板 / Z_AX−RO 壳内壁底 / Z_G PCB 地 /
    # 基板 4 层 → Z_TOP（=针底切线）/ Z_AX 针轴 / +RI 针顶（桥下电极）/ +RO
    # 壳内壁顶（桥上电极）/ +ROS 壳外顶 / 壳顶上方 AIR_TOP
    _sma_lay = params.get("_sma_layout") if template == "sma_launcher" else None
    _sma_z_lines = ""
    _sma_z_top = 0.0
    if _sma_lay is not None:
        _sma_z_lines = ", ".join(repr(v) for v in (
            0.0, _sma_lay["z_ax"] - _sma_lay["ro"], _sma_lay["z_ax"],
            _sma_lay["z_ax"] + _sma_lay["ri"], _sma_lay["z_ax"] + _sma_lay["ro"],
            _sma_lay["z_ax"] + _sma_lay["ros"], _sma_lay["f_z"]))
        _sma_z_top = _sma_lay["z_ax"] + _sma_lay["ros"] + air_top
    # C9 suspended_stripline z 预算（米，字面注入，z 网格/基板盒/端口同源）：
    # 腔高 B=b_mm，基板厚 H_SUB 以带中面 B/2 对称悬浮 [B/2−H/2, B/2+H/2]
    _ssl_b = float(params.get("b_mm", 1.016)) * 1e-3
    if template == "suspended_stripline" and not (h_m < _ssl_b):
        raise ValueError(
            f"suspended_stripline: 基板厚 H_SUB={h_m * 1e3:.4g}mm 必须小于腔高 "
            f"b={_ssl_b * 1e3:.4g}mm（基板不得越出接地板腔）")
    _ssl_zlo = _ssl_b / 2.0 - h_m / 2.0
    _ssl_zmid = _ssl_b / 2.0
    _ssl_zhi = _ssl_b / 2.0 + h_m / 2.0
    # 基板 z 格数 → linspace 点数（SSL 半腔每 span、CPS 整腔）：缺省 4 格
    # =旧口径（SSL 3 点/半腔、CPS 5 点整腔）逐字节不变
    _sub_half_pts = max(2, _knob_sub_cells // 2 + 1)   # SSL：每半腔格数+1 点
    _cps_sub_pts = max(2, _knob_sub_cells + 1)         # CPS：整腔格数+1 点
    _sub_pts = max(2, _knob_sub_cells + 1)             # 微带/lange 等：整腔格数+1 点
    # §10.3 C1 antenna2 立体器件（monopole/helix）z 网格预算：布局单源
    # （馈口顶/元件面 mm → 米字面量 + 元件顶上方 AIR_TOP）
    if template in _ANTENNA2_TALL_TEMPLATES:
        _lay_z = _ant2_layout(template, params)
        _ant2_z_list = ", ".join(repr(z * 1e-3) for z in _lay_z["z_lines_mm"])
        _ant2_z_top = _lay_z["element_top_mm"] * 1e-3 + air_top
    else:
        _ant2_z_list, _ant2_z_top = "", 0.0
    # §C4 lange：air-bridge 抬高薄金属的 z 底/顶面精确入网（布局单源，米）。
    # 去桥变体（_bridge=0）z_lines 为空 → 哨兵 "H_SUB"：CSRectGrid.AddLine
    # 拒绝空数组（assert len>0，runs/c4_debridge/audit_nobridge.py exec 实证），
    # H_SUB 与基板 linspace 末点重合、脚本内 1µm 去重守卫随后移除重复线——
    # 最终 z 网格与"桥面线不再入网"等价。
    if template == "lange":
        _lange_z_vals = _c4_layout("lange", params)["z_lines"]
        _lange_z_list = (", ".join(repr(z) for z in _lange_z_vals)
                         if _lange_z_vals else "H_SUB")
    else:
        _lange_z_list = ""
    # dipole / loop（自由空间族）：域 z 向下延 λ0/4（元件面 z=0 居中，底 MUR 无地）
    z_mesh_block = (
        'mesh.AddLine("z", np.linspace(-AIR_TOP, 0, 5))\n'
        "mesh.AddLine(\"z\", AIR_TOP)\n"
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if is_free_space else (
        # via：双层板 0..2·H_SUB（内层地 z=H）+ 顶带上方/底带下方各
        # 留 AIR_TOP——两条带都必须是域内面（贴域边界的带=半边模场
        # 缺失/MUR 侵蚀，pt1 β 爆炸 + pt2 底带 β 崩坏实证）
        'mesh.AddLine("z", -AIR_TOP)\n'
        'mesh.AddLine("z", np.linspace(0, 2 * H_SUB, 9))\n'
        "mesh.AddLine(\"z\", 2 * H_SUB + AIR_TOP)\n"
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "via" else (
        # stripline：对称板 0..2·H_SUB（带在 H_SUB 中面），半高 4 层 ×2；
        # 上边界即上地（PEC），无 AIR_TOP（场被屏蔽，域到上地为止）
        'mesh.AddLine("z", np.linspace(0, 2 * H_SUB, 9))\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "stripline" else (
        # C9 suspended_stripline：腔 0..B_CAV（上下地=域 z 边界 PEC），带在中面
        # B/2，基板 H_SUB 以带为中面对称悬浮 [B/2−H/2, B/2+H/2]；基板两面/
        # 中面/壳边全部精确入网（#198），各层间 2 段过渡后 BASE 平滑
        # （基板两 span 的格数走 _sub_half_pts 旋钮，缺省=3 点逐字节不变）
        'mesh.AddLine("z", np.linspace(0.0, ' + repr(_ssl_zlo) + ', 3))\n'
        'mesh.AddLine("z", np.linspace(' + repr(_ssl_zlo) + ', '
        + repr(_ssl_zmid) + ', ' + repr(_sub_half_pts) + '))\n'
        'mesh.AddLine("z", np.linspace(' + repr(_ssl_zmid) + ', '
        + repr(_ssl_zhi) + ', ' + repr(_sub_half_pts) + '))\n'
        'mesh.AddLine("z", np.linspace(' + repr(_ssl_zhi) + ', '
        + repr(_ssl_b) + ', 3))\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "suspended_stripline" else (
        # C9 cps：无地共面带——基板下方空气 AIR_TOP（底 MUR，slot 同款）+
        # 基板 _cps_sub_pts 点（缺省 5 点=4 格，旧口径逐字节不变）+ 上方 AIR_TOP
        'mesh.AddLine("z", np.linspace(-AIR_TOP, 0, 5))\n'
        'mesh.AddLine("z", np.linspace(0, H_SUB, ' + repr(_cps_sub_pts) + '))\n'
        'mesh.AddLine("z", H_SUB + AIR_TOP)\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "cps" else (
        # sma_launcher（夹具口径，2026-09-16 根治）：z=0 夹具底板 → 壳内壁底 →
        # Z_G PCB 地 → 基板 4 层 → Z_TOP（微带面=针底切线）→ 针轴/针顶/壳内壁顶/
        # 壳外顶（同轴三半径柱面界恰在网格上）→ 壳顶上方 AIR_TOP（根治前域顶距壳顶
        # 仅 0.25mm=1 cell，H5）。字面量与 body 同源（_sma_layout）
        f'mesh.AddLine("z", np.array([{_sma_z_lines}]))\n'
        'mesh.AddLine("z", np.linspace('
        + (repr(_sma_lay["z_g"]) if _sma_lay else "0")
        + ", " + (repr(_sma_lay["z_top"]) if _sma_lay else "H_SUB")
        + ', 5))   # 基板 4 层（官方 substrate_cells=4，抬板 Z_G 起）\n'
        f'mesh.AddLine("z", {_sma_z_top!r})   # 壳顶 + AIR_TOP\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "sma_launcher" else (
        # §10.3 C1 antenna2 立体器件（monopole/helix）：无基板，z=0 PEC
        # 地 + 馈口顶/元件面精确入网 + 元件顶上方 AIR_TOP（字面注入，米）
        'mesh.AddLine("z", np.array([' + _ant2_z_list + ', '
        + repr(_ant2_z_top) + ']))\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template in _ANTENNA2_TALL_TEMPLATES else (
        # slot：地面=z=0 有限板，槽向下半空间也辐射 → 底 AIR_TOP（MUR）
        'mesh.AddLine("z", np.linspace(-AIR_TOP, 0, 5))\n'
        'mesh.AddLine("z", np.linspace(0, H_SUB, 5))\n'
        'mesh.AddLine("z", H_SUB + AIR_TOP)\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "slot" else (
        # §C4 lange：基板 _sub_cells 层 + air-bridge 薄金属 z 底/顶面（字面注入，
        # 米）+ 顶空气隙；桥面不入网即抬高盒不进网格（#174 零体积/#198 家族）
        'mesh.AddLine("z", np.linspace(0, H_SUB, ' + repr(_sub_pts) + '))   '
        "# 基板 _sub_cells 层（缺省 4=官方 substrate_cells=4；#313 z 向地板项）\n"
        'mesh.AddLine("z", np.array([' + _lange_z_list + ']))\n'
        'mesh.AddLine("z", H_SUB + AIR_TOP)\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "lange" else (
        # siw：封闭双板波导（上下板=域 z 边界 PEC），无空气区——基板 z
        # _sub_cells 层（TE10 的 E_z 沿 z 均匀，z 分辨非限制项，criteria §4.8）
        'mesh.AddLine("z", np.linspace(0, H_SUB, ' + repr(_sub_pts) + '))   '
        "# 基板 _sub_cells 层（缺省 4=官方 substrate_cells=4；#313 z 向地板项）\n"
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template == "siw" else (
        # §MS_METASURFACE 单元（文末 MS_METASURFACE 段）：z 面字面注入
        # （基板内 linspace + 贴片面/端口片/域顶，layout 单源米制）；
        # ms_patch 无底空气区（z 底=地面 PEC 边界），cross/jcross 屏两侧
        # 空气区含端口片与 MUR 余量
        'mesh.AddLine("z", np.linspace(0, H_SUB, ' + repr(_sub_pts) + '))\n'
        'mesh.AddLine("z", np.array(['
        + ", ".join(repr(z) for z in params["_ms_layout"]["z_lines"]) + ']))\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    ) if template in MS_UNIT_TEMPLATES else (
        'mesh.AddLine("z", np.linspace(0, H_SUB, ' + repr(_sub_pts) + '))   '
        "# 基板 _sub_cells 层（缺省 4=官方 substrate_cells=4；#313 z 向地板项）\n"
        'mesh.AddLine("z", H_SUB + AIR_TOP)\n'
        'mesh.SmoothMeshLines("z", BASE)\n'
    )
    substrate_block = (
        "# dipole/loop：自由空间器件，无基板无地（官方 Helical/Dipole-SAR 口径）\n"
        "# monopole/helix：理想 PEC 地面悬空导体，无介质板（像理论口径）\n"
    ) if (is_free_space or template in _ANTENNA2_TALL_TEMPLATES) else (
        # stripline：基板填满 0..2·H_SUB（上下地面之间）；无空气区
        'sub = CSX.AddMaterial("substrate", epsilon=ER,\n'
        "                      kappa=TAND * 2 * np.pi * F0 * "
        "8.854187817e-12 * ER)\n"
        'sub.AddBox((-BOARD, -BOARD, 0), (BOARD, BOARD, 2 * H_SUB), priority=0)\n'
    ) if template in ("stripline", "via") else (
        # C9 suspended_stripline：基板 H_SUB 以带为中面对称悬浮于腔中
        # （面坐标与 z 网格字面值逐字节同源，零厚面恰在网格线）
        "# suspended_stripline：腔高 B_CAV（上下地=域 z 边界 PEC），基板厚 H_SUB "
        "对称悬浮 [B/2−H/2, B/2+H/2]，两侧空气隙各 (B−H)/2\n"
        "B_CAV = " + repr(_ssl_b) + "\n"
        'sub = CSX.AddMaterial("substrate", epsilon=ER,\n'
        "                      kappa=TAND * 2 * np.pi * F0 * "
        "8.854187817e-12 * ER)\n"
        "sub.AddBox((-BOARD, -BOARD, " + repr(_ssl_zlo) + "), (BOARD, BOARD, "
        + repr(_ssl_zhi) + "), priority=0)\n"
    ) if template == "suspended_stripline" else (
        # sma_launcher 夹具口径：PCB 抬高 Z_G（=r_os−r_i−H_SUB，几何单源
        # _sma_layout 字面量）使针底切线=基板顶；z=0 PEC 边界=夹具底板，PCB 地
        # =body 里的夹具金属块顶；板边切口（y<Y_E）由 body 的空气盒覆盖
        "# sma_launcher：基板抬至 [Z_G, Z_G+H_SUB]（夹具口径，见 _sma_launcher_lines）\n"
        'sub = CSX.AddMaterial("substrate", epsilon=ER,\n'
        "                      kappa=TAND * 2 * np.pi * F0 * "
        "8.854187817e-12 * ER)\n"
        "sub.AddBox((-BOARD, -BOARD, "
        + (repr(_sma_lay["z_g"]) if _sma_lay else "0") + "), (BOARD, BOARD, "
        + (repr(_sma_lay["z_top"]) if _sma_lay else "H_SUB") + "), priority=0)\n"
    ) if template == "sma_launcher" else (
        # msl_siw_taper：基板填满矩形域（DOM_X/DOM_Y 由 msl_siw_taper_layout
        # 注入；底=域 z 边界 PEC，顶=MUR 开放——MSL 区微带环境）
        "# msl_siw_taper：基板填满矩形域（SIW 顶壁=显式零厚板见 body）\n"
        'sub = CSX.AddMaterial("substrate", epsilon=ER,\n'
        "                      kappa=TAND * 2 * np.pi * F0 * "
        "8.854187817e-12 * ER)\n"
        "sub.AddBox((-DOM_X, -DOM_Y, 0), (DOM_X, DOM_Y, H_SUB), priority=0)\n"
    ) if template == "msl_siw_taper" else (
        # siw：基板填满矩形域（上下板=域 z 边界 PEC + 显式零厚板见 body）
        "# siw：基板填满矩形域（上下板=域 z 边界 PEC + 显式零厚板见 body）\n"
        'sub = CSX.AddMaterial("substrate", epsilon=ER,\n'
        "                      kappa=TAND * 2 * np.pi * F0 * "
        "8.854187817e-12 * ER)\n"
        "sub.AddBox((-DOM_X, -DOM_Y, 0), (DOM_X, DOM_Y, H_SUB), priority=0)\n"
    ) if template == "siw" else (
        # §MS_METASURFACE 单元（文末 MS_METASURFACE 段）：基板填满单胞域
        # （ms_patch 地=z 底 PEC 边界；cross/jcross 屏浮，底 MUR 见 bottom_bc）
        "# ms 单元：基板填满单胞方形域（波导模拟器，屏/贴片零厚面见 body）\n"
        'sub = CSX.AddMaterial("substrate", epsilon=ER,\n'
        "                      kappa=TAND * 2 * np.pi * F0 * "
        "8.854187817e-12 * ER)\n"
        "sub.AddBox((-DOM_X, -DOM_Y, 0), (DOM_X, DOM_Y, H_SUB), priority=0)\n"
    ) if template in MS_UNIT_TEMPLATES else (
        "# 基板延伸到侧边界（guided；官方口径：无板边衍射）；"
        "地面 = z-min PEC 边界\n"
        'sub = CSX.AddMaterial("substrate", epsilon=ER,\n'
        "                      kappa=TAND * 2 * np.pi * F0 * "
        "8.854187817e-12 * ER)\n"
        "sub.AddBox((-BOARD, -BOARD, 0), (BOARD, BOARD, H_SUB), priority=0)\n"
    )

    # ── WP4.1 nf2ff / SAR 注入块 ─────────────────────────────────────────────
    # 官方口径锚（docs/rf_template_references.md §8 + wiki 教程）：
    # Simple Patch Antenna（nf2ff 盒 = SimBox 缩 4×max_res；f_res 从 S11 谷取；
    # η = Prad/P_in）、Dipole SAR（DumpType 29 + CalcSAR mass=1g IEEE_62704）。
    _ff_on = far_field or sar
    sar_setup_block = ""
    if sar:
        # 组织等效模型（官方皮肤层文献值 @1GHz tissue database）；
        # CellConstantMaterial=1 官方要求（每 Yee 元单值材料，SAR 正确性）
        sar_setup_block = (
            '# ── SAR 组织等效模型（官方 Dipole SAR 教程：皮肤层 εr=50、'
            'κ=0.65 S/m、ρ=1100 kg/m³）──\n'
            'phantom = CSX.AddMaterial("phantom", epsilon=50.0, kappa=0.65,\n'
            "                          density=1100.0)\n"
            'phantom.AddBox((-25e-3, 20e-3, -15e-3), (25e-3, 65e-3, 15e-3), '
            "priority=0)\n"
            "# 模型盒边入网格（边界必须落网格线，#198/#212 家族教训）\n"
            'mesh.AddLine("x", np.array([-25e-3, 25e-3]))\n'
            'mesh.AddLine("y", np.array([20e-3, 65e-3]))\n'
            'mesh.AddLine("z", np.array([-15e-3, 15e-3]))\n'
            'mesh.SmoothMeshLines("x", BASE)\n'
            'mesh.SmoothMeshLines("y", BASE)\n'
            'mesh.SmoothMeshLines("z", BASE)\n'
            "# 最小间距守卫（#152）：新加线与既有线撞出 nm 级近重合会塌时间步\n"
            "for _ax in (\"x\", \"y\", \"z\"):\n"
            "    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)\n"
            "    _keep = [_ls[0]]\n"
            "    for _v in _ls[1:]:\n"
            "        if _v - _keep[-1] > 1e-6:\n"
            "            _keep.append(_v)\n"
            "    mesh.SetLines(_ax, np.array(_keep))\n"
            "# SAR 原始数据 dump：DumpType 29（FD 电场+体元+κ+密度）、HDF5、\n"
            "# cell 模式；盒比模型略大（官方口径：非零 κ/密度体元才计入）\n"
            '_sar_dump = CSX.AddDump("SAR_raw", dump_type=29, frequency=[F0],\n'
            "                        file_type=1, dump_mode=2)\n"
            "_sar_dump.AddBox((-27e-3, 18e-3, -17e-3), (27e-3, 67e-3, 17e-3))\n"
        )
    ff_setup_block = ""
    if _ff_on:
        # 接地辐射模板（patch + §10.3 C1 antenna2 地面族 + §10.3 C2 贴片阵）：
        # z 底=PEC 边界，CreateNF2FFBox 依 BC 自动排除 z- 面并置 PEC 镜像；
        # slot / loop（自由空间，2026-09-16）走六面全包分支（底 MUR）
        if template in ("patch", "pifa", "ifa", "monopole", "helix",
                        "patch_array_1x4", "patch_array_2x2", "patch_array_series",
                        "patch_eep_2x2", "patch_eep_1x4"):
            # z 底=PEC 边界：CreateNF2FFBox 依 BC 自动排除 z- 面并置 PEC 镜像
            # （绑定源码 openEMS.pyx CreateNF2FFBox：BC_type==0 → direction
            # False + mirror=1）；盒必须包住贴片+探针（z 从 0 起）
            ff_setup_block = (
                "# ── nf2ff 盒（官方 Simple Patch Antenna：域缩 4×网格）──\n"
                "_FF_MARGIN = 4 * BASE\n"
                "_FF_START = np.array([-DOM_X + _FF_MARGIN, -DOM_Y + _FF_MARGIN, 0.0])\n"
                "_FF_STOP = np.array([DOM_X - _FF_MARGIN, DOM_Y - _FF_MARGIN,\n"
                "                     H_SUB + AIR_TOP - _FF_MARGIN])\n"
                "_FF = FDTD.CreateNF2FFBox('nf2ff', _FF_START, _FF_STOP)\n"
            )
        else:  # dipole / slot / loop：自由空间（或底 MUR）六面全包
            ff_setup_block = (
                "# ── nf2ff 盒（官方教程：域缩 4×网格，六面全包）──\n"
                "_FF_MARGIN = 4 * BASE\n"
                "_FF_START = np.array([-DOM_X + _FF_MARGIN, -DOM_Y + _FF_MARGIN,\n"
                "                      -AIR_TOP + _FF_MARGIN])\n"
                "_FF_STOP = np.array([DOM_X - _FF_MARGIN, DOM_Y - _FF_MARGIN,\n"
                "                     AIR_TOP - _FF_MARGIN])\n"
                "_FF = FDTD.CreateNF2FFBox('nf2ff', _FF_START, _FF_STOP)\n"
            )
    # nf2ff 依赖 dump 面输出（nf2ff_E_n.h5/nf2ff_H_n.h5），disable_dumps 会
    # 连带禁掉 → 注入时不传该开关；其余产物文件照常
    _run_kwargs = "" if _ff_on else "disable_dumps=True, "
    ff_calc_block = ""
    if _ff_on and template in EEP_TEMPLATES:
        # ── DP-4 P3 EEP 单激励轮专用块：f_res=F0 固定（轮间同频方可叠加，J4d）+
        # farfield3d_cplx.csv 复数 3D dump（core.farfield 契约同表头，多余列
        # 容忍）。非 EEP 辐射模板走下方既有块（argmin|S11| 口径）——本分支
        # 不改其渲染字节（#315 兼容纪律）。功率口径（Prad/Dmax/η）非 EEP 轮
        # 消费面，不产出（PEC 镜像只影响功率积分、不影响 E 场复分量）。
        ff_calc_block = (
            "\n# ── nf2ff 远场（DP-4 P3 EEP 单激励轮：f_res=F0 固定口径）──\n"
            "# EEPₙ=第 n 元有源方向图（其余元 50Ω 集总元端接被动在场；nf2ff 以\n"
            "# 全局原点为相位参考，位置相位免手工补偿）。辅助产物 best-effort\n"
            "# （#105）：任何失败不阻塞主 S 参数输出。\n"
            "_FF_DIR = __import__(\"os\").path.dirname(\n"
            "    __import__(\"os\").path.abspath(__file__))\n"
            "import json as _json\n"
            "try:\n"
            "    _f_res = F0\n"
            "    _THETA3 = np.arange(" + repr(EEP_FF_THETA_DEG[0]) + ", "
            + repr(EEP_FF_THETA_DEG[1] + EEP_FF_THETA_DEG[2] * 0.5) + ", "
            + repr(EEP_FF_THETA_DEG[2]) + ")\n"
            "    _PHI3 = np.arange(" + repr(EEP_FF_PHI_DEG[0]) + ", "
            + repr(EEP_FF_PHI_DEG[1] + EEP_FF_PHI_DEG[2] * 0.5) + ", "
            + repr(EEP_FF_PHI_DEG[2]) + ")\n"
            "    _ff3 = _FF.CalcNF2FF(SIM_PATH, _f_res, _THETA3, _PHI3,\n"
            "                         outfile='farfield_3d.h5')\n"
            "    _et3 = np.asarray(_ff3.E_theta[0], dtype=complex)\n"
            "    _ep3 = np.asarray(_ff3.E_phi[0], dtype=complex)\n"
            "    with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "            \"farfield3d_cplx.csv\"), \"w\", newline=\"\") as _f3h:\n"
            "        _f3w = csv.writer(_f3h)\n"
            "        _f3w.writerow([\"theta_deg\", \"phi_deg\", \"re_e_theta\", "
            "\"im_e_theta\", \"re_e_phi\", \"im_e_phi\"])\n"
            "        for _it in range(len(_THETA3)):\n"
            "            for _ip in range(len(_PHI3)):\n"
            "                _f3w.writerow([_THETA3[_it], _PHI3[_ip], "
            "_et3[_it, _ip].real, _et3[_it, _ip].imag,\n"
            "                               _ep3[_it, _ip].real, "
            "_ep3[_it, _ip].imag])\n"
            "    _ff_meta = {\n"
            "        \"ok\": True,\n"
            f"        \"template\": {template!r},\n"
            "        \"eep\": True,\n"
            f"        \"excite_port\": {int(params.get('_excite_port', 1) or 1)},\n"
            "        \"f_res_ghz\": F0 / 1e9,\n"
            "        \"f_res_mode\": \"fixed_F0\",\n"
            "        \"freq_band_ghz\": [(F0 - FC) / 1e9, (F0 + FC) / 1e9],\n"
            f"        \"grid_theta_deg\": {list(EEP_FF_THETA_DEG)!r},\n"
            f"        \"grid_phi_deg\": {list(EEP_FF_PHI_DEG)!r},\n"
            "        \"phase_reference\": \"nf2ff global origin\",\n"
            "        \"power_metrics\": None,\n"
            "        \"power_note\": (\"EEP 轮不产出 Prad/Dmax/η（功率口径非本产物\"\n"
            "                        \"消费面；PEC 镜像只影响功率积分不影响 E 场）\"),\n"
            "        \"nf2ff_box_start_m\": np.asarray(_FF_START).tolist(),\n"
            "        \"nf2ff_box_stop_m\": np.asarray(_FF_STOP).tolist(),\n"
            "        \"radius_m\": 1.0,\n"
            "    }\n"
            "    with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "            \"farfield_meta.json\"), \"w\", encoding=\"utf-8\") as _mh:\n"
            "        _json.dump(_ff_meta, _mh, ensure_ascii=False, indent=1)\n"
            "except Exception as _ffe:\n"
            "    try:\n"
            "        with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "                \"farfield_meta.json\"), \"w\", encoding=\"utf-8\") as _mh:\n"
            "            _json.dump({\"ok\": False, \"error\": str(_ffe)}, _mh,\n"
            "                       ensure_ascii=False)\n"
            "    except Exception:\n"
            "        pass\n"
            "    print(\"rfauto nf2ff 链失败（不阻塞 S 参数）:\", _ffe)\n"
        )
    elif _ff_on:
        ff_calc_block = (
            "\n# ── nf2ff 远场计算（WP4.1；官方口径 f_res=|S11| 谷，η=Prad/P_acc）──\n"
            "# 辅助产物：任何一步失败不阻塞主 S 参数输出（写 farfield_meta.json\n"
            "  # ok=false 留痕，观测性 best-effort #105）\n"
            "_FF_DIR = __import__(\"os\").path.dirname(\n"
            "    __import__(\"os\").path.abspath(__file__))\n"
            "import json as _json\n"
            "try:\n"
            "    _f_res_i = int(np.argmin(np.abs(S11)))\n"
            "    _f_res = float(f[_f_res_i])\n"
            "    _p_acc = float(np.real(_port1.P_acc[_f_res_i]))\n"
            "    _THETA_CUT = np.arange(-180.0, 181.0, 1.0)\n"
            "    _PHI_CUT = [0.0, 90.0]\n"
            "    _ffr = _FF.CalcNF2FF(SIM_PATH, _f_res, _THETA_CUT, _PHI_CUT)\n"
            "    _Dmax = float(np.atleast_1d(_ffr.Dmax)[0])\n"
            "    _Prad = float(np.atleast_1d(_ffr.Prad)[0])\n"
            "    _eta = (_Prad / _p_acc) if _p_acc > 0 else None\n"
            "    # 3D 方向图（官方 Outfile='3D_Pattern.h5' 口径）\n"
            "    _ff3 = _FF.CalcNF2FF(SIM_PATH, _f_res,\n"
            "                         np.arange(0.0, 181.0, 5.0),\n"
            "                         np.arange(0.0, 360.0, 5.0),\n"
            "                         outfile='farfield_3d.h5')\n"
            "    _en3 = np.asarray(_ff3.E_norm[0], dtype=float)\n"
            "    _db3 = 20 * np.log10(_en3 / max(_en3.max(), 1e-300) + 1e-300)\n"
            "    _th3 = np.arange(0.0, 181.0, 5.0)\n"
            "    _ph3 = np.arange(0.0, 360.0, 5.0)\n"
            "    with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "            \"farfield_cut.csv\"), \"w\", newline=\"\") as _ffh:\n"
            "        _fw = csv.writer(_ffh)\n"
            "        _fw.writerow([\"phi_deg\", \"theta_deg\", \"re_e_theta\", "
            "\"im_e_theta\", \"re_e_phi\", \"im_e_phi\", \"e_norm\", \"p_rad\"])\n"
            "        for _ip, _phv in enumerate(_PHI_CUT):\n"
            "            for _it, _thv in enumerate(_THETA_CUT):\n"
            "                _et = complex(_ffr.E_theta[0][_it, _ip])\n"
            "                _ep = complex(_ffr.E_phi[0][_it, _ip])\n"
            "                _fw.writerow([_phv, _thv, _et.real, _et.imag, "
            "_ep.real, _ep.imag,\n"
            "                              float(_ffr.E_norm[0][_it, _ip]),\n"
            "                              float(_ffr.P_rad[0][_it, _ip])])\n"
            "    with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "            \"farfield3d.csv\"), \"w\", newline=\"\") as _f3h:\n"
            "        _f3w = csv.writer(_f3h)\n"
            "        _f3w.writerow([\"theta_deg\", \"phi_deg\", \"e_norm_db\"])\n"
            "        for _it in range(len(_th3)):\n"
            "            for _ip in range(len(_ph3)):\n"
            "                _f3w.writerow([_th3[_it], _ph3[_ip], "
            "float(_db3[_it, _ip])])\n"
            "    _ff_meta = {\n"
            "        \"ok\": True,\n"
            f"        \"template\": {template!r},\n"
            "        \"f_res_ghz\": _f_res / 1e9,\n"
            "        \"freq_band_ghz\": [(F0 - FC) / 1e9, (F0 + FC) / 1e9],\n"
            "        \"prad_w\": _Prad, \"p_acc_w\": _p_acc,\n"
            "        \"dmax_linear\": _Dmax,\n"
            "        \"dmax_dbi\": 10 * np.log10(max(_Dmax, 1e-300)),\n"
            "        \"efficiency\": _eta,\n"
            "        \"gain_max_dbi\": (10 * np.log10(max(_Dmax, 1e-300)) +\n"
            "                          10 * np.log10(_eta)) if _eta else None,\n"
            "        \"power_budget_closure\": (abs(_p_acc - _Prad) / _p_acc\n"
            "                                  if _p_acc > 0 else None),\n"
            "        \"nf2ff_box_start_m\": np.asarray(_FF_START).tolist(),\n"
            "        \"nf2ff_box_stop_m\": np.asarray(_FF_STOP).tolist(),\n"
            "        \"radius_m\": 1.0,\n"
            "    }\n"
            "    # ── PEC 地镜像修正（#249：CreateNF2FFBox 遇 PEC 底面置 mirror=1 →\n"
            "    # AddMirrorPlane 对每个积分面追加镜像通量，Prad=2×物理、Dmax −3.01dB）。\n"
            "    # 口径与 core.farfield.correct_pec_mirror 同式（渲染脚本保持纯净不 import\n"
            "    # 内核；单测钉住两者逐键数值一致）：盒底 z_start==0 → k=2，Prad/k、\n"
            "    # Dmax×k、η/闭合/增益重算；修正前六指标原值留 raw；六面全包（z_start<0）\n"
            "    # k=1 原值不动。服务层读到 pec_mirror_factor 即幂等直通，不二次折半。\n"
            "    # RFAUTO_PEC_MIRROR_BEGIN\n"
            "    _k_mirror = (2.0 if abs(float(_ff_meta[\"nf2ff_box_start_m\"][2])) < 1e-9\n"
            "                 else 1.0)\n"
            "    _ff_meta[\"pec_mirror_factor\"] = _k_mirror\n"
            "    if _k_mirror != 1.0:\n"
            "        _ff_meta[\"raw\"] = {_kk: _ff_meta.get(_kk) for _kk in (\n"
            "            \"prad_w\", \"dmax_linear\", \"dmax_dbi\", \"efficiency\",\n"
            "            \"gain_max_dbi\", \"power_budget_closure\")}\n"
            "        _Prad = float(_ff_meta[\"prad_w\"]) / _k_mirror\n"
            "        _Dmax = float(_ff_meta[\"dmax_linear\"]) * _k_mirror\n"
            "        _p_acc = float(_ff_meta[\"p_acc_w\"])\n"
            "        _eta = (_Prad / _p_acc) if _p_acc > 0 else None\n"
            "        _ff_meta[\"prad_w\"] = _Prad\n"
            "        _ff_meta[\"dmax_linear\"] = _Dmax\n"
            "        _ff_meta[\"dmax_dbi\"] = 10.0 * np.log10(max(_Dmax, 1e-300))\n"
            "        _ff_meta[\"efficiency\"] = _eta\n"
            "        _ff_meta[\"gain_max_dbi\"] = ((_ff_meta[\"dmax_dbi\"]\n"
            "                                      + 10.0 * np.log10(_eta))\n"
            "                                     if _eta else None)\n"
            "        _ff_meta[\"power_budget_closure\"] = (abs(_p_acc - _Prad) / _p_acc\n"
            "                                            if _p_acc > 0 else None)\n"
            "    # RFAUTO_PEC_MIRROR_END\n"
            "    with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "            \"farfield_meta.json\"), \"w\", encoding=\"utf-8\") as _mh:\n"
            "        _json.dump(_ff_meta, _mh, ensure_ascii=False, indent=1)\n"
            "except Exception as _ffe:\n"
            "    try:\n"
            "        with open(__import__(\"os\").path.join(_FF_DIR,\n"
            "                \"farfield_meta.json\"), \"w\", encoding=\"utf-8\") as _mh:\n"
            "            _json.dump({\"ok\": False, \"error\": str(_ffe)}, _mh,\n"
            "                       ensure_ascii=False)\n"
            "    except Exception:\n"
            "        pass\n"
            "    print(\"rfauto nf2ff 链失败（不阻塞 S 参数）:\", _ffe)\n"
        )
        if sar:
            ff_calc_block += (
                "\n# ── SAR 计算（绑定已随包：SAR_Calculation mass=1g IEEE_62704）──\n"
                "try:\n"
                "    from openEMS.sar_calculation import SAR_Calculation\n"
                "    from openEMS.sar_utils import readSAR\n"
                "    _sc = SAR_Calculation(mass=1.0, method='IEEE_62704')\n"
                "    _sc.CalcFromHDF5(__import__(\"os\").path.join(SIM_PATH, "
                "'SAR_raw.h5'),\n"
                "                     __import__(\"os\").path.join(SIM_PATH, "
                "'SAR_1g.h5'))\n"
                "    _sar, _smesh, _smeta = readSAR(__import__(\"os\").path.join(\n"
                "        SIM_PATH, 'SAR_1g.h5'))\n"
                "    _p_abs = float(_smeta.get('power', 0.0) or 0.0)\n"
                "    _sar_max = float(np.max(_sar)) if _sar is not None else 0.0\n"
                "    with open(__import__(\"os\").path.join(_FF_DIR, \"sar.csv\"),\n"
                "              \"w\", newline=\"\") as _sfh:\n"
                "        _sw = csv.writer(_sfh)\n"
                "        _sw.writerow([\"metric\", \"value\"])\n"
                "        _sw.writerow([\"freq_hz\", _f_res])\n"
                "        _sw.writerow([\"mass_g\", 1.0])\n"
                "        _sw.writerow([\"p_acc_w\", _p_acc])\n"
                "        _sw.writerow([\"p_abs_w\", _p_abs])\n"
                "        _sw.writerow([\"sar_max_w_per_kg\", _sar_max])\n"
                "        _sw.writerow([\"sar_max_w_per_kg_per_1w_acc\",\n"
                "                      (_sar_max / _p_acc) if _p_acc > 0 else "
                "float('nan')])\n"
                "except Exception as _sare:\n"
                "    print(\"rfauto SAR 链失败（不阻塞 S 参数）:\", _sare)\n"
            )

    # 域半宽文本：缺省=BOARD 共享字面量（逐字节不变）；siw 矩形域由 layout
    # 字面注入（BOARD=60mm 对 SIW 自动档 ~20M cells 超预算，criteria §2）
    _dom_x_txt = "BOARD + AIR_SIDE"
    _dom_y_txt = "BOARD + AIR_SIDE"
    if template == "siw":
        _dom_x_txt = repr(params["_siw_layout"]["dom_x"])
        _dom_y_txt = repr(params["_siw_layout"]["dom_y"])
    elif template == "msl_siw_taper":
        _dom_x_txt = repr(params["_msl_siw_taper_layout"]["dom_x"])
        _dom_y_txt = repr(params["_msl_siw_taper_layout"]["dom_y"])
    elif template in MS_UNIT_TEMPLATES:
        # §MS_METASURFACE 单胞：域=单胞方形截面（period/2，layout 单源）
        _dom_x_txt = repr(params["_ms_layout"]["dom_x"])
        _dom_y_txt = repr(params["_ms_layout"]["dom_y"])

    return f'''#!/usr/env/python3
"""openEMS script (rfauto {template} template auto-generated, official-method mesh)."""
import csv
import os

# CSXCAD/openEMS 扩展模块的依赖 DLL 不在 Python 3.8+ 的 PATH 搜索里，
# 必须 add_dll_directory（仅 os.environ PATH 会 ImportError: DLL load
# failed——2026-09-03 审计实测）。目录可用 RFAUTO_OPENEMS_BIN 覆盖。
_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN", r"E:\\openEMS\\install\\bin")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
# LumpedElement 隔离电阻走 CSXCAD 原语 CSX.AddLumpedElement（模板内联），
# 不从 openEMS.ports 导入（该模块并无 LumpedElement，导入即崩——审计实测）
from openEMS.ports import LumpedPort, MSLPort{extra_ports_import}

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}
H_SUB = {h_m!r}
TAND = {tan_d!r}
BASE = {base_m!r}   # 网格 base：λ_sub/50 @F_MAX（官方口径）或显式覆盖
NEAR = {near_m!r}   # {'近走线区 = base/4（官方口径）' if _knob_near_ratio == 4 else f'近走线区 = base/{_knob_near_ratio:g}（_near_ratio 旋钮）'}
CSV_NAME = "sparams.csv"
SIM_PATH = __import__("os").path.abspath("fdtd")
# 绑定库运行中可能改写解释器 cwd：CSV 一律写脚本自身目录（绝对路径），
# 否则产物静默落到进程启动目录（2026-09-03 审计实测踩坑）
CSV_PATH = __import__("os").path.join(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__)),
    CSV_NAME)

# ── 仿真环境：官方 MSL_NotchFilter 教程方法学（2026-09-04 频率尺度根因
# 实验后定稿；旧版 λ/20@空气粗网格 + 有限小板使 λ/4 谷位系统性低 30-40%
# 且随网格漂移，证据链 runs/audit_freq_scale/ E1-E4）──
CSX = ContinuousStructure()
FDTD = openEMS(NrTS={_nrts!r}{_end_criteria_src}{', CellConstantMaterial=1' if sar else ''})   # 官方口径：不设 EndCriteria，默认能量判据停机{'；EndCriteria=显式停机判据（_end_criteria 旋钮）' if _end_criteria_src else ''}{'；CellConstantMaterial=1 = 官方 SAR 要求（每 Yee 元单值材料）' if sar else ''}
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 端口面所在轴 PML_8（官方），z 底 {bottom_bc}{'_（自由空间，无地）' if is_free_space else ' 当地面（官方）'}，其余 MUR
FDTD.SetBoundaryCond(["{b_x0}", "{b_x1}", "{b_y0}", "{b_y1}", "{bottom_bc}", "{top_bc}"])

AIR_TOP = {air_top!r}     # 辐射器件 λ0/4，guided 5mm
AIR_SIDE = {air_side!r}   # 辐射器件侧向空气隙，guided 0（基板顶到边界）

mesh = CSX.GetGrid()
BOARD = 60e-3   # 板边（端口面/基板边缘）= guided 模板域边界
DOM_X = {_dom_x_txt}
DOM_Y = {_dom_y_txt}

def _axis(ax: str, near_pts, dom_lo, dom_hi) -> None:
    """官方网格配方：走线近场 NEAR 精细区 + 全轴 BASE 渐变（SmoothMesh）。"""
    for p in near_pts:
        mesh.AddLine(ax, p)
    mesh.SmoothMeshLines(ax, NEAR)
    mesh.AddLine(ax, np.array([dom_lo, dom_hi]))
    mesh.SmoothMeshLines(ax, BASE)

_near_x = {fmt_list(near_x)}
_near_y = {fmt_list(near_y)}
_axis("x", _near_x, -DOM_X, DOM_X)
_axis("y", _near_y, -DOM_Y, DOM_Y)
{z_mesh_block}# 近重合网格线守卫：浮点误差线可能只差 nm~µm 级，把时间步压塌
# （2026-09-03 B 点审计实测）。平滑后按最小间距 1µm 去重。
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

{substrate_block}{body}
{sar_setup_block}{ff_setup_block}
# cleanup：清掉同目录旧 run 的 port/et 输出——不清理时 CalcPort 会读到
# 上一版结构的旧信号文件，S 参数静默变 NaN（实测踩坑）
FDTD.Run(SIM_PATH, verbose=0, {_run_kwargs}cleanup=True)

f = np.linspace(F0 - FC, F0 + FC, 401)
# 官方 MSL_NotchFilter 口径：CalcPort 显式 ref_impedance=50；透射 S21 取
# port2 的 uf_ref（=到达 port2 的行波）。注意 uf_ref/uf_inc 的相位含端口
# 分解伪象，只能用幅值与 β（CalcPort 自算）做物理判读（E3 实测）。
_port1.CalcPort(SIM_PATH, f, ref_impedance={z_ref_txt})
try:
    _port2.CalcPort(SIM_PATH, f, ref_impedance={z_ref_txt})
    S21 = _port2.uf_ref / _port1.uf_inc
except Exception:
    S21 = _port1.uf_ref / _port1.uf_inc  # single-port fallback
S11 = _port1.uf_ref / _port1.uf_inc
{ff_calc_block}{beta_block}
_LOOP_DONE = False
{s31_block}{loop_block}if not _LOOP_DONE:
    with open(CSV_PATH, "w", newline="") as fh:
        w = csv.writer(fh)
        if S31 is not None and S23 is not None:
            w.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21",
                        "re_S31", "im_S31", "re_S23", "im_S23"])
            for i, fi in enumerate(f):
                w.writerow([fi, S11[i].real, S11[i].imag, S21[i].real,
                            S21[i].imag, S31[i].real, S31[i].imag,
                            S23[i].real, S23[i].imag])
        else:
            w.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"])
            for i, fi in enumerate(f):
                w.writerow([fi, S11[i].real, S11[i].imag, S21[i].real, S21[i].imag])
print("rfauto openEMS simulation done")
'''


# ─── Template body render functions ──────────────────────────────────────────
# 口径（2026-09-04 官方方法学统一）：金属画在基板顶面 z=H_SUB（地面=z-min PEC
# 边界）；馈线段由 MSLPort 自画（同宽），端口面 = 板边 = 域边界；
# FeedShift=10×NEAR、MeasPlaneShift=端口段长/3（官方口径）。

def _mline_lines(p: dict[str, Any]) -> str:
    # 均匀微带线（WP2.1 锚模板）：一条直带，两端 MSLPort（端口自画馈线
    # 补齐到板边）。验收口径：S21 相位斜率→εeff 对照 skrf HJ ±1%（β 金
    # 标准 #162）；|S11| 显著非零=端口/网格判废信号（refs §3.2）。
    # 参数：w_mm=线宽（skrf HJ 综合，50Ω@rogers4350b=1.113mm），
    # line_len_mm=两端口间线长。
    return f'''W = {p.get("w_mm", 1.113)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
Y0 = -L / 2
Y1 = L / 2
mline = CSX.AddMetal("microstrip")
mline.AddBox((-W / 2, Y0, H_SUB), (W / 2, Y1, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=mline,
                 start=np.array([W / 2, -BOARD, H_SUB]),
                 stop=np.array([-W / 2, Y0, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=mline,
                 start=np.array([-W / 2, BOARD, H_SUB]),
                 stop=np.array([W / 2, Y1, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in mline.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _cpw_lines(p: dict[str, Any]) -> str:
    # 均匀共面波导（WP2.1 锚族）：中心带 + 两侧地（地延伸到域边）。
    # 端口 = CPWPort（v0.37 一等支持）：start/stop 宽度=中心带宽、
    # gap_width=缝宽、地自画；exc_dir='z'（绑定源码 L1117+ 逐条对照）。
    # 参数：w_mm=中心带宽（CPWG 共形映射闭式综合，50Ω@gap0.2=0.849mm，
    # #198 参照系修正）、gap_mm=缝宽、line_len_mm=两端口间线长。
    body = f'''W = {p.get("w_mm", 0.849)!r} * 1e-3
GAP = {p.get("gap_mm", 0.2)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
Y0 = -L / 2
Y1 = L / 2
cpw = CSX.AddMetal("cpw")
cpw.AddBox((-W / 2, Y0, H_SUB), (W / 2, Y1, H_SUB), priority=10)
# 两侧地：贯穿全域（CPWPort 只补画中心带段，端口段的地须自画）
cpw.AddBox((-BOARD, -BOARD, H_SUB), (-W / 2 - GAP, BOARD, H_SUB), priority=10)
cpw.AddBox((W / 2 + GAP, -BOARD, H_SUB), (BOARD, BOARD, H_SUB), priority=10)
_port1 = CPWPort(CSX, port_nr=1, metal_prop=cpw,
                 start=np.array([W / 2, -BOARD, H_SUB]),
                 stop=np.array([-W / 2, Y0, H_SUB]),
                 prop_dir="y", exc_dir="z", gap_width=GAP,
                 excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = CPWPort(CSX, port_nr=2, metal_prop=cpw,
                 start=np.array([-W / 2, BOARD, H_SUB]),
                 stop=np.array([W / 2, Y1, H_SUB]),
                 prop_dir="y", exc_dir="z", gap_width=GAP,
                 excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
for _prim in cpw.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''
    # B6 stage-2 深化钩子：params 含 b6_board（板级事实 dict，出自
    # service.kicad_em_service.board_facts_from_extract）时追加板级全要素
    # 几何块（fill 外轮廓/孔洞切除/via 桶壁/pad/主线折线）。缺省键=既有
    # cpw 渲染逐字节不变。惰性导入（共享文件纪律；渲染模块只反向依赖
    # adapters 内新模块，无环）。
    b6_facts = p.get("b6_board")
    if b6_facts:
        from rfauto.adapters.kicad_board_render import board_geometry_lines

        body += board_geometry_lines(b6_facts)
    return body


def _stripline_lines(p: dict[str, Any]) -> str:
    # 均匀对称带状线（WP2.1 锚族）：中心带在 H_SUB 中面，上下地 = 域
    # z 边界 PEC（底 z=0、顶 z=2·H_SUB）。端口 = StripLinePort（v0.37
    # 一等支持，绑定源码 L914+：height=带-地半高，对称电压探针上下
    # 各一）。TEM 模：εeff=εr（β 锚判据最干净的闭式）。
    return f'''W = {p.get("w_mm", 0.5554)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
Y0 = -L / 2
Y1 = L / 2
stripline = CSX.AddMetal("stripline")
stripline.AddBox((-W / 2, Y0, H_SUB), (W / 2, Y1, H_SUB), priority=10)
_port1 = StripLinePort(CSX, port_nr=1, metal_prop=stripline,
                       start=np.array([W / 2, -BOARD, H_SUB]),
                       stop=np.array([-W / 2, Y0, H_SUB]),
                       prop_dir="y", exc_dir="z", height=H_SUB,
                       excite=1, FeedShift=10 * NEAR,
                       MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = StripLinePort(CSX, port_nr=2, metal_prop=stripline,
                       start=np.array([-W / 2, BOARD, H_SUB]),
                       stop=np.array([W / 2, Y1, H_SUB]),
                       prop_dir="y", exc_dir="z", height=H_SUB,
                       excite=0, FeedShift=10 * NEAR,
                       MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
for _prim in stripline.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _cps_lines(p: dict[str, Any]) -> str:
    # 共面带 CPS（C9 传输线族 II）：两条等宽带（沿 y）夹中央缝，无地——基板
    # 下方空气（render_script 底 MUR + 域向下 AIR_TOP，slot 同款）。端口 =
    # 两端 LumpedPort 跨缝差分直馈/端接（refs §8 官方 AddLumpedPort 范式，
    # _dipole_lines 同法）：R=闭式 Z0（core/calculators._cps_ri，render_script
    # 按本次基板注入 _cps_r_ohm 并同步作 CalcPort 参考阻抗；直调兜底按
    # _DEFAULT_SUB 精算）。带内 |S11| 深谷 = Z0 锚；εeff 锚 = S21 解缠相位
    # 斜率（LumpedPort 无 β 属性，β 金标准如实降级，见 TEMPLATE_META）。
    # openEMS.ports 无 CPS/slotline 端口原语（本 session 枚举实证），差分
    # 集总馈是唯一不触 C5 阻塞的口径。
    r_ohm = p.get("_cps_r_ohm")
    if r_ohm is None:
        from rfauto.core.calculators import _cps_ri

        r_ohm = round(_cps_ri(float(p.get("w_mm", 2.95)),
                              float(p.get("gap_mm", 0.5)),
                              float(_DEFAULT_SUB["h_mm"]),
                              float(_DEFAULT_SUB["er"]))[1], 4)
    return f'''W = {p.get("w_mm", 2.95)!r} * 1e-3
GAP = {p.get("gap_mm", 0.5)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
Y0 = -L / 2
Y1 = L / 2
R_PORT = {float(r_ohm)!r}   # LumpedPort R = CPS 闭式 Z0（匹配端接；CalcPort 同参考）
cps = CSX.AddMetal("cps")
cps.AddBox((-GAP / 2 - W, Y0, H_SUB), (-GAP / 2, Y1, H_SUB), priority=10)
cps.AddBox((GAP / 2, Y0, H_SUB), (GAP / 2 + W, Y1, H_SUB), priority=10)
# 两端 LumpedPort 跨缝差分（官方 Helical/Dipole 教程口径 AddLumpedPort(
# port_nr, R, start, stop, norm_dir, excite)）：norm='x' 沿缝宽方向，
# port1 激励、port2 无激励=R 端接 + 探针
_port1 = FDTD.AddLumpedPort(1, R_PORT, np.array([-GAP / 2, Y0, H_SUB]),
                            np.array([GAP / 2, Y0, H_SUB]), "x", 1.0, priority=5)
_port2 = FDTD.AddLumpedPort(2, R_PORT, np.array([-GAP / 2, Y1, H_SUB]),
                            np.array([GAP / 2, Y1, H_SUB]), "x", 0.0, priority=5)
for _prim in cps.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _suspended_stripline_lines(p: dict[str, Any]) -> str:
    # 悬置带线（C9 传输线族 II）：腔高 B=b_mm（上下地=域 z 边界 PEC，
    # render_script top_bc PEC 同 stripline），零厚度带在中面 z=B/2；基板
    # H_SUB 以带为中面对称悬浮 [B/2−H/2, B/2+H/2]（substrate_block 按 params
    # 字面注入，面坐标与 z 网格同源）。端口 = StripLinePort（height=B/2=带-地
    # 半高，v0.37 源码 L914+ 口径，同 stripline）→ β 金标准可用。
    return f'''W = {p.get("w_mm", 0.9058)!r} * 1e-3
B = {p.get("b_mm", 1.016)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
ZC = B / 2
Y0 = -L / 2
Y1 = L / 2
ssl = CSX.AddMetal("suspended_stripline")
ssl.AddBox((-W / 2, Y0, ZC), (W / 2, Y1, ZC), priority=10)
_port1 = StripLinePort(CSX, port_nr=1, metal_prop=ssl,
                       start=np.array([W / 2, -BOARD, ZC]),
                       stop=np.array([-W / 2, Y0, ZC]),
                       prop_dir="y", exc_dir="z", height=ZC,
                       excite=1, FeedShift=10 * NEAR,
                       MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = StripLinePort(CSX, port_nr=2, metal_prop=ssl,
                       start=np.array([-W / 2, BOARD, ZC]),
                       stop=np.array([W / 2, Y1, ZC]),
                       prop_dir="y", exc_dir="z", height=ZC,
                       excite=0, FeedShift=10 * NEAR,
                       MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
for _prim in ssl.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _wstep_lines(p: dict[str, Any]) -> str:
    # 微带宽度阶跃（WP2.2 不连续性基元）：窄段/宽段各半长，单阶梯跃在
    # 中点；两端 MSLPort（手法同 mline）。锚判据=skrf 级联 HJ 闭式
    # （两段理想 TL 级联为确定性裁判，引擎-理想偏差即阶梯寄生贡献）。
    return f'''W1 = {p.get("w1_mm", 1.1134)!r} * 1e-3
W2 = {p.get("w2_mm", 1.897)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
Y0 = -L / 2
YM = 0.0
Y1 = L / 2
wstep = CSX.AddMetal("wstep")
wstep.AddBox((-W1 / 2, Y0, H_SUB), (W1 / 2, YM, H_SUB), priority=10)
wstep.AddBox((-W2 / 2, YM, H_SUB), (W2 / 2, Y1, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=wstep,
                 start=np.array([W1 / 2, -BOARD, H_SUB]),
                 stop=np.array([-W1 / 2, Y0, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=wstep,
                 start=np.array([-W2 / 2, BOARD, H_SUB]),
                 stop=np.array([W2 / 2, Y1, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
for _prim in wstep.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ─── 端接口径统一后处理 helper（W2⑤ 定案 (a)，2026-09-16）────────────────────
# 机理（战役 followUps①）：openEMS 端口面贴 PML，非激励端的
# 线由 PML 按**线自身 Z0** 匹配端接，CalcPort(ref_impedance=50) 的 uf_ref/
# uf_inc 只是 50Ω 伪波分解 → 凡端口线 ≠50Ω 的模板（wstep/via/msl_cpw/
# atten/sma_launcher），引擎单激励 'S11' 与 50Ω 双端接裁判（fake Pozar
# ABCD@50、skrf renormalize([50,50])）本非同一量（wstep 实证：引擎口径闭式
# 逐点偏差 0.033/0.029 vs fake 口径 0.171/0.305）。
# 定案 (a)：50Ω 参考是全项目裁判统一口径（fake/skrf/HFSS 仲裁/ADS），不改
# 裁判定义；引擎侧后处理统一——单激励 uf 比值按列反演到各端口线自身 Z0 真
# 波基（等价于 footer CalcPort(ref_impedance=Z_k) 的代数恒等式，无需改 CSV
# 契约）→（线基内纯相位去嵌到 DUT 参考面）→（skrf renormalize）→ 50Ω。
# 全链确定性线性代数，离线验证 vs fake Pozar 独立构造 1e-12 一致
# （tests/unit/test_port_renormalize.py）。
# ⚠ 单激励 uf 比值是**带载比值**（非激励端在 50Ω 基下被 Γ=(Z−50)/(Z+50)
# 端接，a≠0）——对装配矩阵整块 renormalize_s 是错的（合成数据实测误差
# =|Γ_step|=0.176）；必须按列反演（本 helper 的 loaded_ratios_to_line_basis）。
# 本波只接 wstep；其余 ≠50Ω 模板接入列 followUps（renormalize 耦合全端口，
# 须双激励装配全矩阵，#208 进程隔离轮转范式；4 端口模板馈线=50Ω 时反演
# 退化为恒等，天然安全）。
def tl_gamma_per_m(f_hz: Any, eps_eff: float, tan_d: float = 0.0) -> Any:
    """均匀 TL 复传播常数 γ=α+jβ（rad/m；fake `_wstep_sparams` 同式，确定性）。

    α = π·f·√εeff·tanδ/c（一阶介质损耗，fake 同式），β = 2π·f·√εeff/c。
    """
    import numpy as np

    f = np.asarray(f_hz, dtype=float)
    c0 = 299792458.0
    s = math.sqrt(float(eps_eff))
    return np.pi * f * s * float(tan_d) / c0 + 1j * (2.0 * np.pi * f * s / c0)


def loaded_ratios_to_line_basis(s_raw: Any, z_line_ohm: Any,
                                z_ref_ohm: float = 50.0) -> Any:
    """单激励 uf 比值（带载，CalcPort ref=z_ref）→ 各端口线自身 Z0 真波基 S。

    引擎第 j 列（端口 j 激励）的 uf 比值 r_ij=b_i/a_j 中，非激励端 i 被
    PML 按线自身 Z_i 匹配端接——在 z_ref 基下这是负载 Γ_i=(Z_i−z_ref)/
    (Z_i+z_ref)（a_i=Γ_i·b_i≠0），故比值是带载量而非 S^z_ref 矩阵本征列。
    本函数按列恢复物理 u/i 再换到 Z_k 基（≡CalcPort(ref_impedance=Z_k)，
    代数恒等；PML 端接在 Z_k 基=匹配，负载伪象精确消除）：

        S[j,j] = [zr(1+r) − Z_j(1−r)] / [zr(1+r) + Z_j(1−r)]
        S[i,j] = r_ij·2√(zr·Z_i)/(Z_i+zr) / a_j^Z，
        a_j^Z = [zr(1+r_jj) + Z_j(1−r_jj)]/(2√(zr·Z_j))

    `s_raw`：(N,P,P) 复数，第 j 列取自端口 j 激励的 run（P=2 时 S12/S22
    列取激励 2 的 CSV，#208 装配）。`z_line_ohm`：每端口线特征阻抗
    （标量/复数/(N,) 数组均可；HJ 闭式 forward_z0 或引擎自算 ZL，勿写死）。
    Z_k=z_ref 时该端口因子恒等（50Ω 线模板天然无变化）。
    """
    import numpy as np

    s = np.asarray(s_raw, dtype=complex)
    if s.ndim != 3 or s.shape[1] != s.shape[2]:
        raise ValueError(f"s_raw 须为 (N,P,P)，得 {s.shape}")
    n, p, _ = s.shape
    zl = np.asarray(z_line_ohm, dtype=complex)
    zl = np.broadcast_to(zl, (n, p)).copy()
    zr = float(z_ref_ohm)
    out = np.empty_like(s)
    for j in range(p):
        r_jj = s[:, j, j]
        a_j = ((zr * (1.0 + r_jj) + zl[:, j] * (1.0 - r_jj))
               / (2.0 * np.sqrt(zr * zl[:, j])))
        b_j = ((zr * (1.0 + r_jj) - zl[:, j] * (1.0 - r_jj))
               / (2.0 * np.sqrt(zr * zl[:, j])))
        out[:, j, j] = b_j / a_j
        for i in range(p):
            if i == j:
                continue
            # 非激励端：b_i^Z = r_ij·2√(zr·Z_i)/(Z_i+zr)（a_i^Z≡0 自动成立）
            b_i = (s[:, i, j] * 2.0 * np.sqrt(zr * zl[:, i])
                   / (zl[:, i] + zr))
            out[:, i, j] = b_i / a_j
    return out


def renorm_engine_s_to_ref(
    s_raw: Any,
    z_line_ohm: Any,
    z_ref_ohm: float = 50.0,
    deembed_lens_m: list[float] | None = None,
    gamma: list[Any] | None = None,
    z_out_ohm: Any = None,
) -> Any:
    """openEMS 引擎 S 全链统一到参考口径（W2⑤ 定案 (a)，可复用 helper）。

    ① `loaded_ratios_to_line_basis`：单激励带载比值 → 各端口线自身 Z0 真波
    基（PML 端接在线基=匹配，DUT 与端接解耦）；② 线基内去嵌：均匀匹配线移
    参考面=纯指数 e^{+γ_k·l_k} 对角/e^{γ1l1+γ2l2} 交叉（γ 复数时含衰减，
    精确）；③ skrf `renormalize_s`（s_def='traveling'=CalcPort 伪波口径）
    线基 → `z_out_ohm`（默认 [z_ref]*2）——实数 Z 下与 fake Pozar ABCD@50
    精确同一变换。

    - `s_raw`：(N,P,P) 带载 uf 比值（第 j 列=激励 j 的 run，#208 装配）。
    - `z_line_ohm`：每端口线 Z0（HJ 闭式 forward_z0 标量，或引擎自算 ZL 的
      (N,) 复数组——后者基最自洽，HJ-vs-引擎 Z 偏差转为被测 DUT 差异）。
    - `deembed_lens_m`/`gamma`：每端口"测量面→DUT 参考面"长度（米）与复传播
      常数 γ=α+jβ（rad/m，标量或 (N,)）；引擎自算 β（port_beta.csv 金标准
      #162）优先，HJ 闭式（tl_gamma_per_m）兜底。None=不去嵌。
    - `z_out_ohm`：输出基（默认 50Ω 参考；传 z_line_ohm 得线基输出，用于
      幅度镜像/互易的物理判读）。

    离线钉子（test_port_renormalize.py）：Z=50 恒等；理想阶跃真波基闭式
    [[Γ,t],[t,−Γ]] 带载合成 → 全链输出 vs fake Pozar ABCD@50 逐点一致
    （1e-12）；整矩阵 renormalize_s 反例（误差=|Γ_step|）钉死带载陷阱。
    """
    import numpy as np
    from skrf.network import renormalize_s

    s = np.asarray(s_raw, dtype=complex)
    if s.ndim != 3 or s.shape[1] != s.shape[2]:
        raise ValueError(f"s_raw 须为 (N,P,P)，得 {s.shape}")
    s_line = loaded_ratios_to_line_basis(s, z_line_ohm, z_ref_ohm)
    if deembed_lens_m is not None:
        if gamma is None:
            raise ValueError("deembed_lens_m 需配套 gamma（α+jβ rad/m）")
        p = s_line.shape[1]
        if len(deembed_lens_m) != p or len(gamma) != p:
            raise ValueError("deembed_lens_m/gamma 须逐端口给定")
        th = [np.asarray(g, dtype=complex) * float(length)
              for g, length in zip(gamma, deembed_lens_m, strict=True)]
        s_line = s_line.copy()
        # 去嵌因子 e^{+γ_i l_i + γ_j l_j}（γ=α+jβ 复数：e^{αl} 补回衰减、
        # e^{jβl} 退相位；勿写成 exp(1j·γl)——复 γ 下会变成 e^{−βl} 假衰减）
        for i in range(p):
            for j in range(p):
                s_line[:, i, j] = s_line[:, i, j] * np.exp(th[i] + th[j])
    z_out = (np.asarray(z_out_ohm, dtype=complex)
             if z_out_ohm is not None else np.full(s_line.shape[1], float(z_ref_ohm)))
    zl = np.broadcast_to(np.asarray(z_line_ohm, dtype=complex),
                         (s_line.shape[0], s_line.shape[1])).copy()
    zo = np.broadcast_to(z_out, (s_line.shape[0], s_line.shape[1])).copy()
    return renormalize_s(s_line, zl, zo, s_def="traveling")


def wstep_deembed_lens_m(params: dict[str, Any],
                         board_mm: float = 60.0) -> tuple[float, float]:
    """wstep 模板"测量面→画布线端（y=±line_len/2，DUT 面）"去嵌长度（米）。

    模板口径单源（与 _wstep_lines 同式）：端口面=板边 ±board_mm（渲染
    footer BOARD=60e-3），MeasPlaneShift=(Y0+BOARD)/3（Y0=−line_len/2）→
    测量面到线端 = board−half−shift = 2·(board−half)/3（两端同式）。用于把
    引擎测量面对齐到 fake 裁判的 seg_len_mm=line_len/2 面约定。
    """
    half = float(params.get("line_len_mm", 40.0)) * 1e-3 / 2.0
    b = float(board_mm) * 1e-3
    shift = (b - half) / 3.0          # MeasPlaneShift=(Y0+BOARD)/3，Y0=−half
    lens = (b - half) - shift         # 测量面到线端 = 2·(board−half)/3（两端同）
    return (lens, lens)


def _bend_lines(p: dict[str, Any]) -> str:
    # 微带直角弯折（WP2.2 不连续性基元）：L 形两臂各 arm_len，未切角
    # 标准口径（mitered 为变体）。裁判=理想级联（同宽两段级联完全
    # 匹配，弯角寄生是引擎唯一反射源）→ |S11| 绝对门 -15dB。
    return f'''W = {p.get("w_mm", 1.1134)!r} * 1e-3
A = {p.get("arm_len_mm", 20.0)!r} * 1e-3
bend = CSX.AddMetal("bend")
bend.AddBox((-W / 2, -A, H_SUB), (W / 2, 0.0, H_SUB), priority=10)
bend.AddBox((0.0, -W / 2, H_SUB), (A, W / 2, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=bend,
                 start=np.array([W / 2, -BOARD, H_SUB]),
                 stop=np.array([-W / 2, -A, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(-A + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=bend,
                 start=np.array([BOARD, W / 2, H_SUB]),
                 stop=np.array([A, -W / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - A) / 3, priority=10)
for _prim in bend.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _via_lines(p: dict[str, Any]) -> str:
    # 过孔过渡（WP2.2 收官基元）：双层板 z∈[0,2H]，内层地方 sheet z=H
    # 带方反焊盘（四盒拼孔，边长 2*antipad），过孔金属柱 r_via 穿孔
    # 连接顶带（z=2H, port1）与底带（z=0, port2）。
    # 同轴口径 Z≈(60/√εr)·ln(r_pad/r_via)（标称 ≈52.5Ω 近 50Ω）。
    # 过孔柱=CSPrimCylinder（笛卡尔网格阶梯化，r≪cell 不加网格线）。
    # 无 PEC 边界（地=内层 sheet，z 双 MUR）——全站首例。
    return f'''W = {p.get("w_mm", 1.1134)!r} * 1e-3
AP = {p.get("antipad_mm", 0.8)!r} * 1e-3
RV = {p.get("r_via_mm", 0.15)!r} * 1e-3
Y0 = -BOARD
Y1 = BOARD
H_MID = H_SUB          # 内层地平面（板半高）
H_TOP = 2 * H_SUB      # 顶层带平面
via_gnd = CSX.AddMetal("via_gnd")
via_gnd.AddBox((-BOARD, -BOARD, H_MID), (-AP, AP, H_MID), priority=10)
via_gnd.AddBox((AP, -BOARD, H_MID), (BOARD, AP, H_MID), priority=10)
via_gnd.AddBox((-AP, -BOARD, H_MID), (AP, -AP, H_MID), priority=10)
via_gnd.AddBox((-AP, AP, H_MID), (AP, BOARD, H_MID), priority=10)
via_strip = CSX.AddMetal("via_strip")
via_strip.AddBox((-W / 2, Y0, H_TOP), (W / 2, 0.0, H_TOP), priority=10)
via_strip.AddBox((-W / 2, 0.0, 0.0), (W / 2, Y1, 0.0), priority=10)
via_barrel = CSX.AddMetal("via_barrel")
via_barrel.AddCylinder([0.0, 0.0, 0.0], [0.0, 0.0, H_TOP], radius=RV,
                       priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=via_strip,
                 start=np.array([W / 2, -BOARD, H_TOP]),
                 stop=np.array([-W / 2, 0.0, H_MID]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=BOARD / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=via_strip,
                 start=np.array([-W / 2, BOARD, 0.0]),
                 stop=np.array([W / 2, 0.0, H_MID]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=BOARD / 3, priority=10)
for _prim in via_gnd.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in via_strip.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _atten_pi_lines(p: dict[str, Any]) -> str:
    # π 型电阻衰减器（WP2.3 Tier 1 首族）：串臂 LumpedElement 桥接中点
    # 断口（ny=y），两端对地 shunt LumpedElement（ny=z，短柱接 z-min
    # PEC 地；wilkinson 隔离电阻同款渲染机制已验证）。
    # 电阻值=E4 attenuator_pi ABCD 闭式（确定性裁判，同源）。
    return f'''W = {p.get("w_mm", 1.1134)!r} * 1e-3
D = {p.get("shunt_off_mm", 6.0)!r} * 1e-3
G = 0.5 * 1e-3
R_SER = {p.get("r_series_mid_ohm", 71.151)!r}
R_SH = {p.get("r_shunt_end_ohm", 96.248)!r}
pi_pad = CSX.AddMetal("pi_pad")
pi_pad.AddBox((-W / 2, -BOARD, H_SUB), (W / 2, -G, H_SUB), priority=10)
pi_pad.AddBox((-W / 2, G, H_SUB), (W / 2, BOARD, H_SUB), priority=10)
_r_series = CSX.AddLumpedElement("r_series", ny=1, caps=True, R=R_SER)
_r_series.AddBox((-W / 2, -G, H_SUB), (W / 2, G, H_SUB), priority=10)
_r_sh1 = CSX.AddLumpedElement("r_shunt1", ny=2, caps=True, R=R_SH)
_r_sh1.AddBox((-W / 2, -D - G / 2, 0.0), (W / 2, -D + G / 2, H_SUB),
              priority=10)
_r_sh2 = CSX.AddLumpedElement("r_shunt2", ny=2, caps=True, R=R_SH)
_r_sh2.AddBox((-W / 2, D - G / 2, 0.0), (W / 2, D + G / 2, H_SUB),
              priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=pi_pad,
                 start=np.array([W / 2, -BOARD, H_SUB]),
                 stop=np.array([-W / 2, -D, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(-D + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=pi_pad,
                 start=np.array([-W / 2, BOARD, H_SUB]),
                 stop=np.array([W / 2, D, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - D) / 3, priority=10)
for _prim in pi_pad.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _atten_t_lines(p: dict[str, Any]) -> str:
    # T 型电阻衰减器（WP2.3 横向变体）：±d 断口各串 LumpedElement
    # （ny=y），中点对地全带宽 shunt LumpedElement（ny=z）。
    # 电阻值=E4 attenuator_t ABCD 闭式（确定性裁判，同源）。
    return f'''W = {p.get("w_mm", 1.1134)!r} * 1e-3
D = {p.get("shunt_off_mm", 6.0)!r} * 1e-3
G = 0.5 * 1e-3
R_SER = {p.get("r_series_arm_ohm", 25.975)!r}
R_MID = {p.get("r_shunt_mid_ohm", 35.136)!r}
t_pad = CSX.AddMetal("t_pad")
t_pad.AddBox((-W / 2, -BOARD, H_SUB), (W / 2, -D - G / 2, H_SUB), priority=10)
t_pad.AddBox((-W / 2, -D + G / 2, H_SUB), (W / 2, D - G / 2, H_SUB),
             priority=10)
t_pad.AddBox((-W / 2, D + G / 2, H_SUB), (W / 2, BOARD, H_SUB), priority=10)
_r_ser1 = CSX.AddLumpedElement("r_series1", ny=1, caps=True, R=R_SER)
_r_ser1.AddBox((-W / 2, -D - G / 2, H_SUB), (W / 2, -D + G / 2, H_SUB),
               priority=10)
_r_ser2 = CSX.AddLumpedElement("r_series2", ny=1, caps=True, R=R_SER)
_r_ser2.AddBox((-W / 2, D - G / 2, H_SUB), (W / 2, D + G / 2, H_SUB),
               priority=10)
_r_mid = CSX.AddLumpedElement("r_shunt_mid", ny=2, caps=True, R=R_MID)
_r_mid.AddBox((-W / 2, -G / 2, 0.0), (W / 2, G / 2, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=t_pad,
                 start=np.array([W / 2, -BOARD, H_SUB]),
                 stop=np.array([-W / 2, -D, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(-D + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=t_pad,
                 start=np.array([-W / 2, BOARD, H_SUB]),
                 stop=np.array([W / 2, D, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - D) / 3, priority=10)
for _prim in t_pad.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# rat-race 环渲染半径引擎常数（pt8 定标 2026-09-11，#198 同类网格伪象）：
# 0.4mm 网格下 1.5 格宽的曲线环带无法带缘对齐，呈慢波/容性栅格化伪象——
# pt7/pt8 实测 hybrid 中心 ≈2.28GHz（六门在带内低端几乎全过、随 f 单调
# 劣化），pt8 全 4×4 矩阵对理想 (θ,θ,3θ,θ) 环做线性幅值最小二乘得环电长
# 缩放 k=1.0975（z=Z_ring/70.7=0.89；Σ 列口径 1.1025、only-k 1.095，
# 三者 ±0.4%），等效 εeff=3.28 超微带物理上限（εr=3.66，HJ 直线 2.72，
# 直线 70.7Ω 模板 branchline/gysel 均达标）→ 判为网格伪象而非几何问题
# （pt8 受控实验已否决结点/弯折加载假设；HFSS 仲裁 2.465GHz 背书
# verdict.k_attribution=MESH_ARTIFACT，runs/ratrace_arbitration/）。
# 渲染半径 = 物理半径 / k，物理 R（synthesis 1.5λg=17.344）与 nominal
# 不变、HFSS 通道不受影响（#219③：k 只落 adapter 渲染层）。
_RATRACE_RING_MESH_K = 1.0975   # pt8 归档锚（0.4mm 档历史定标值，仅存证）

# ── k(BASE) 网格档自适应（2026-09-12 HFSS 仲裁批两点标度，ratrace-k 定版）──
# 0.2mm 收敛核验（runs/ratrace_arbitration/openems_convergence.json）：同一
# k=1.0975 下 hybrid 中心 0.4mm→2.354GHz / 0.2mm→2.5225GHz（均 f_center_avg），
# 网格伪象随细化收敛，一阶标度 k_needed(BASE)=k_cur×F0/f_center(BASE) 给
# 两锚 k(0.2mm)=1.0877、k(0.4mm)=1.1654。(k−1) 两点比值 1.886 ≈ 2^0.915，
# 即 (k−1) ∝ BASE^α 幂律（α=ln((k04−1)/(k02−1))/ln2≈0.915），对 (k−1) 做
# 对数空间两点内插；锚外（默认自动档 BASE≈1.14mm 等）夹到最近锚并打
# clamp 旗，禁止外推。柱坐标（build_ratrace_cylindrical）无阶梯化 k=1，
# 为根治首选（#219/#232）；直角坐标换网格档按本函数标度。
_RATRACE_K_BASE_LO_MM = 0.2
_RATRACE_K_BASE_HI_MM = 0.4
_RATRACE_K_ANCHOR_LO = 1.0877   # k(0.2mm)（openems_convergence.json k_needed_0p2mm）
_RATRACE_K_ANCHOR_HI = 1.1654   # k(0.4mm)（openems_convergence.json k_needed_0p4mm）


def ratrace_ring_mesh_k(base_mm: float) -> float:
    """rat-race 渲染半径补偿因子 k，随直角坐标网格档 BASE（mm）标度。

    k(BASE) = 1 + (k02−1)·((k04−1)/(k02−1))^t，t=(BASE−0.2)/0.2∈[0,1]，
    即 (k−1) 对数空间两点幂律内插（α=log2((k04−1)/(k02−1))≈0.915），
    精确复现两锚；BASE∈[0.2,0.4]mm 外夹到最近锚（禁止外推，默认自动档
    BASE≈1.14mm 落此分支）。仅 openEMS 直角坐标渲染层消费（#219③），
    物理 R/synthesis/HFSS 通道不受影响；柱坐标 k=1 不走本函数。
    """
    b = min(max(float(base_mm), _RATRACE_K_BASE_LO_MM), _RATRACE_K_BASE_HI_MM)
    t = (b - _RATRACE_K_BASE_LO_MM) / (_RATRACE_K_BASE_HI_MM - _RATRACE_K_BASE_LO_MM)
    return 1.0 + (_RATRACE_K_ANCHOR_LO - 1.0) * (
        (_RATRACE_K_ANCHOR_HI - 1.0) / (_RATRACE_K_ANCHOR_LO - 1.0)) ** t


def ratrace_ring_mesh_k_clamped(base_mm: float) -> bool:
    """BASE 是否落在定标域 [0.2,0.4]mm 之外（True=渲染脚本用 clamp 锚）。"""
    b = float(base_mm)
    return b < _RATRACE_K_BASE_LO_MM or b > _RATRACE_K_BASE_HI_MM


def _ratrace_lines(p: dict[str, Any]) -> str:
    # rat-race 环形电桥（WP2.3，#208 理论核验轮+pt5 实测定版）：规范角位
    # Σ=0°（右缘水平馈）、out1=60°（径向馈+弯折，出顶缘）、Δ=120°
    # （径向馈+弯折，出顶缘）、out2=300°（径向馈+弯折，出底缘）——
    # out1/out2 分居 Σ 两侧 λ/4（环相位 90/450），Δ 在 λ/2（180），
    # 大弧 3λ/4 扫过 Δ→out2 之间的左下半区。**out2 不得放 geo 180**：
    # 直径对点是环相位 270=两侧各 3λ/4 的"匹配直通"位置（pt5 实测
    # Σ→out2 -0.54dB 直通 + S11 -11dB 的 3λ/4 倒阻抗特征，#208）。
    # 环带与斜馈线逐网格行栅格化（#198 零台阶）。
    # 行为（Y 矩阵严格推导，见 fake _ratrace_sparams docstring）：
    # Σ 均分→out1/out2 各 -3dB 同相；Δ 隔离；out1↔out2 互隔离。
    # 四端口：Σ excite=1（主 run 唯一激励）；out1/Δ/out2 excite=0 仅
    # 探针（激励轮转由适配器层 excite_port 参数化渲染、进程隔离完成
    # ——Run(cleanup=True) 会删激励属性/CSX 的 C++ 对象，禁用进程内
    # 复用包装器的路线，pt3/pt4 实测 #208）。
    # 门：β±2%、|S21|/|S41| -3±1dB 且差 ≤0.5dB、|S31|(Δ) ≤-20dB、
    # |S11|≤-10dB、|S24|≤-15dB。
    # k(BASE)：网格档自适应补偿（ratrace_ring_mesh_k），render_script 注入
    # _base_mm（mm）；域外档写"未定标档 clamp"注释行（禁止外推）
    _base_mm = float(p.get("_base_mm", 0.4))
    _k_ring = ratrace_ring_mesh_k(_base_mm)
    _k_note = (
        f"# 未定标档 clamp：BASE={_base_mm:.4f}mm ∉ [{_RATRACE_K_BASE_LO_MM!r},"
        f"{_RATRACE_K_BASE_HI_MM!r}]mm，夹到最近锚（禁止外推）"
        if ratrace_ring_mesh_k_clamped(_base_mm) else
        f"# 定标域内：BASE={_base_mm:.4f}mm ∈ [{_RATRACE_K_BASE_LO_MM!r},"
        f"{_RATRACE_K_BASE_HI_MM!r}]mm，(k−1) 幂律内插")
    return f'''import numpy as _np

W_R = {p.get("w_ring_mm", 0.6035)!r} * 1e-3
W_F = {p.get("w_feed_mm", 1.1134)!r} * 1e-3
# 渲染半径 = 物理半径 / k(BASE)（阶梯环慢波伪象补偿随网格档标度：锚
# k(0.2mm)={_RATRACE_K_ANCHOR_LO!r} / k(0.4mm)={_RATRACE_K_ANCHOR_HI!r}，HFSS 仲裁背书）
{_k_note}
R_RING = {p.get("r_ring_mm", 17.344)!r} * 1e-3 / {_k_ring!r}
ratrace = CSX.AddMetal("ratrace")

# 环带栅格化：逐 y 网格行，行中心处求环带 x 区间（内/外半径）
_R_OUT = R_RING + W_R / 2
_R_IN = R_RING - W_R / 2
_yl = np.asarray(mesh.GetLines("y"))
for _k in range(len(_yl) - 1):
    _ya, _yb = _yl[_k], _yl[_k + 1]
    _yc = 0.5 * (_ya + _yb)
    if abs(_yc) > _R_OUT:
        continue
    _xo = np.sqrt(max(_R_OUT ** 2 - _yc ** 2, 0.0))
    _xi = np.sqrt(max(_R_IN ** 2 - _yc ** 2, 0.0))
    if _xi > 1e-9:
        ratrace.AddBox((-_xo, _ya, H_SUB), (-_xi, _yb, H_SUB), priority=10)
        ratrace.AddBox((_xi, _ya, H_SUB), (_xo, _yb, H_SUB), priority=10)
    else:
        ratrace.AddBox((-_xo, _ya, H_SUB), (_xo, _yb, H_SUB), priority=10)

# Σ 馈（右缘水平，geo 0°）
ratrace.AddBox((R_RING, -W_F / 2, H_SUB), (BOARD, W_F / 2, H_SUB), priority=10)

# out1/Δ/out2 径向馈（geo 60°/120°/300°）+ 弯折竖直引出到顶/底缘
# （MSLPort 端口盒必须轴对齐——径向段在弯折处切台阶接竖直段）
_TAN60 = np.tan(np.deg2rad(60.0))
_Y_M = 0.866 * R_RING + 4.0e-3                       # 弯折点高度
_X_T = 0.5 * R_RING + 4.0e-3 / _TAN60                # 竖直引出段中心 x
_Y_J = 0.866 * R_RING                                # 环中心线结点高度
# 径向线栅格化（pt8 迭代，#212 续）：60° 陡线沿 **y 网格行** 栅格化，
# 每行盒 x 范围 = 线心 x_c ± W_F/(2·sin60°)（水平半宽 0.643mm，
# 垂直投影带宽恰为 W_F）。pt7 画法（沿 x 列、垂直半跨 W_F/(2cos60°)
# =1.11mm、下探到 y_c=0.8R）经离线掩模审计（渲染→exec→CSXCAD 原语
# →细网格掩模出图）实测：每结点留下 ≈1.8mm 向内伸入环孔的金属尖刺
# + ≈2.5×2.2mm 结点焊盘，三结点容性加载把 hybrid 中心压到 ≈2.2GHz
# （pt7 @2.25GHz 六门全过、@2.5 随 f 单调劣化）。行栅格化在环中心线
# 处裁剪（含中心线所在行→与环带必然重叠导通），焊盘缩至 ≈1mm²、
# 无尖刺；弯折端含 Y_M 所在行（与竖直段盒正面积重叠，#174 零缝教训）。
_W_HX = W_F / (2.0 * np.sin(np.deg2rad(60.0)))     # 水平半宽 = W_F/√3


def _stub_rows(_sign_y, _sign_x):
    """径向 stub 逐行盒：_sign_y=+1 顶缘/−1 底缘；_sign_x=+1 右/−1 左。"""
    _y_lo, _y_hi = _Y_J, _Y_M
    for _k in range(len(_yl) - 1):
        _ya, _yb = _yl[_k], _yl[_k + 1]
        _ya_s, _yb_s = sorted((_sign_y * _ya, _sign_y * _yb))
        if _yb_s < _y_lo or _ya_s > _y_hi:
            continue
        _yc = min(max(0.5 * (_ya_s + _yb_s), _y_lo), _y_hi)
        _xc = _sign_x * (0.5 * R_RING + (_yc - _Y_J) / _TAN60)
        ratrace.AddBox((_xc - _W_HX, _ya, H_SUB),
                       (_xc + _W_HX, _yb, H_SUB), priority=10)


_stub_rows(+1, +1)   # out1：geo 60°，出顶缘 x=+X_T
_stub_rows(+1, -1)   # Δ：geo 120°（镜像），出顶缘 x=−X_T
_stub_rows(-1, +1)   # out2：geo 300°=−60°，出底缘 x=+X_T（Σ 另一侧 λ/4，
                     # pt5 实测定版：不得放 geo 180 直径对点=3λ/4 匹配直通）
# 竖直引出段（带 2·NEAR 搭接防弯折缝：#174 零宽度金属缝隙教训）
# 顶缘两条：out1（+x）/Δ（−x）；底缘一条：out2（+x）
ratrace.AddBox((_X_T - W_F / 2, _Y_M - 2 * NEAR, H_SUB),
               (_X_T + W_F / 2, BOARD, H_SUB), priority=10)
ratrace.AddBox((-_X_T - W_F / 2, _Y_M - 2 * NEAR, H_SUB),
               (-_X_T + W_F / 2, BOARD, H_SUB), priority=10)
ratrace.AddBox((_X_T - W_F / 2, -BOARD, H_SUB),
               (_X_T + W_F / 2, -_Y_M + 2 * NEAR, H_SUB), priority=10)

_port1 = MSLPort(CSX, port_nr=1, metal_prop=ratrace,
                 start=np.array([BOARD, -W_F / 2, H_SUB]),
                 stop=np.array([R_RING, W_F / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=1 if {p.get("_excite_port", 1)} == 1 else 0,
                 FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - R_RING) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=ratrace,
                 start=np.array([_X_T - W_F / 2, BOARD, H_SUB]),
                 stop=np.array([_X_T + W_F / 2, _Y_M - 2 * NEAR, 0]),
                 prop_dir="y", exc_dir="z", excite=1 if {p.get("_excite_port", 1)} == 2 else 0,
                 FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - _Y_M) / 3, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=ratrace,
                 start=np.array([-_X_T - W_F / 2, BOARD, H_SUB]),
                 stop=np.array([-_X_T + W_F / 2, _Y_M - 2 * NEAR, 0]),
                 prop_dir="y", exc_dir="z", excite=1 if {p.get("_excite_port", 1)} == 3 else 0,
                 FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - _Y_M) / 3, priority=10)
_port4 = MSLPort(CSX, port_nr=4, metal_prop=ratrace,
                 start=np.array([_X_T - W_F / 2, -BOARD, H_SUB]),
                 stop=np.array([_X_T + W_F / 2, -_Y_M + 2 * NEAR, 0]),
                 prop_dir="y", exc_dir="z", excite=1 if {p.get("_excite_port", 1)} == 4 else 0,
                 FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - _Y_M) / 3, priority=10)
for _prim in ratrace.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _gysel_layout(params: dict[str, Any]) -> dict[str, float]:
    """Gysel L-jog 等长变体几何单一事实源（mm）——render/_near_points/geometry_spec 共用。

    P2⑪ 拓扑重设计（2026-09-16 离线审计定版）：矩形六节环的桥带（顶边）继承
    臂 λ/4 跨度 2·arm_len，对 50Ω λ/2 设计值 2·iso_len 有 +2.32% 二阶偏差
    （电路级归因主因：@f0 S32/S11 封顶 -34.8dB，skrf 装配实测）。L-jog 变体把
    负载节点 Δ1/Δ2 移到 x=±iso_len（桥带跨度=2·iso_len=λ/2 精确），隔离线走
    竖直段 YJ + 顶端横移 jog=|arm_len−iso_len|（竖直+横移=iso_len 保 λ/4 电
    长度；两处未切角 90° 弯折构成 EM 地板）。方向无关：arm_len>iso_len 时 Δ
    内移（nominal，jog=0.412mm），反之外移——四参数单键扰动均保持合法
    （审计 ×1.37 扰动口径）。
    守卫：YJ>0 ⟺ arm_len<2·iso_len（否则竖直段不存在，六节环不可实现）。
    候选取舍（四候选 skrf 装配 @2.3/2.5/2.7GHz，test_gysel_template 固化）：
    真斜梯形电路级同构但 0.412mm 横移在 0.4mm 网格=1 胞，斜边逐行栅格化要么
    亚网格步距（~9µm/行）触发 #152 CFL 塌缩、要么退化为折线——不采；桥带
    70.7Ω 变体 @f0 亦理想但带边 2.3GHz S32=-25.3dB 差于矩形 -29.5dB（深度换
    带宽）且偏离 §10 50Ω 桥带官方口径——不采。
    """
    wa = float(params.get("w_arm_mm", 0.6035))
    wf = float(params.get("w_feed_mm", 1.1134))
    xa = float(params.get("arm_len_mm", 18.162))
    yi = float(params.get("iso_len_mm", 17.75))
    jog = abs(xa - yi)
    yj = yi - jog
    if not yj > 0.0:
        raise ValueError(
            f"gysel L-jog 拓扑：竖直段 YJ=iso_len−|arm_len−iso_len|={yj:.4f}mm ≤0"
            f"（arm_len={xa} ≥ 2·iso_len={2 * yi}），六节环不可实现")
    # C7 followUp（2026-09-21）：_jog_miter_mm 切角旋钮（mitered-jog 变体，
    # opt-in 与 _end_criteria/_sub_cells 先例同构，不入 params/NOMINAL 参数表）。
    # 0（缺省）=未切角基线，渲染逐字节不变；c>0 时每侧 jog 转角外上角开 c×c
    # 台阶缺口（45° 切角的阶梯网格近似），几何恒等=金属并集减两缺口，竖直段/
    # 桥带/端口/电长度口径不动。守卫 0≤c<W_F（c≥W_F 缺口段降高非正；c<W_F
    # 亦蕴含缺口必落在 jog 段全长 |arm−iso|+W_F 内）。缺口语义见
    # _gysel_jog_lines。真机对照轮（TODO 排空五轮 followUps）用它做 A/B。
    _miter_raw = params.get("_jog_miter_mm")
    c_mit = float(_miter_raw) if _miter_raw is not None else 0.0
    if not (math.isfinite(c_mit) and 0.0 <= c_mit < wf):
        raise ValueError(
            f"gysel _jog_miter_mm 须为 0 ≤ c < w_feed_mm={wf!r}（0=未切角"
            f"缺省），得到 {c_mit!r}")
    return {"wa": wa, "wf": wf, "xa": xa, "yi": yi,
            "jog": jog, "yj": yj, "xb": yi, "g": 0.5, "miter": c_mit}


def _gysel_jog_lines(lay: dict[str, float]) -> str:
    """gysel 顶端 L-jog 横移段渲染文本（缺省两盒；``_jog_miter_mm``>0 切角档）。

    切角档（C7 followUp 2026-09-21）：每侧 jog 段拆"主段（全高）+ 缺口段
    （降高 c）"两盒——转角外上角（与竖直段齐平的 jog 端、y=YJ+W_F/2 顶缘）
    开 c×c 台阶缺口，为 45° miter 切角在阶梯网格下的单步近似（bend 模板
    |S11|<-15dB 口径的弯角寄生机理=外角金属集中）。几何恒等：金属并集=原
    jog 段减两侧转角缺口；竖直段/桥带/端口/负载盒不动。缺口只落在 jog 段
    顶带（y>YJ 侧，竖直段止于 YJ 不覆盖），故竖直段无需拆盒。
    """
    c = float(lay["miter"])
    if c <= 0.0:
        return (
            "# 顶端 L-jog 横移段（与桥带共线同宽）：转角 x=±XA → Δ 节点 x=±XB\n"
            "gysel.AddBox((min(-XA, -XB) - W_F / 2, YJ - W_F / 2, H_SUB),\n"
            "             (max(-XA, -XB) + W_F / 2, YJ + W_F / 2, H_SUB), priority=10)\n"
            "gysel.AddBox((min(XA, XB) - W_F / 2, YJ - W_F / 2, H_SUB),\n"
            "             (max(XA, XB) + W_F / 2, YJ + W_F / 2, H_SUB), priority=10)\n")
    # 坐标一律换算米（脚本主体 XA/YJ/W_F 同单位）——2026-09-21 C7 A/B 审计
    # 修正：初版把 mm 字面量直排（盒落 ±17m 越域 1000×，exec 金属原语实测
    # 抓出，#212 制度化面）；缺省分支走符号式变量不受影响。
    wf, yj = float(lay["wf"]) * 1e-3, float(lay["yj"]) * 1e-3
    xa, xb = float(lay["xa"]) * 1e-3, float(lay["xb"]) * 1e-3
    c_m = c * 1e-3
    lines = [f"# 顶端 L-jog 横移段（mitered-jog 切角档 c={c!r}mm：转角外上角"
             "台阶缺口，C7 followUp 2026-09-21；缺口只削 jog 顶带，"
             "竖直段/桥带不动；坐标=米）"]
    for s in (1.0, -1.0):
        m1, m2 = sorted((s * min(xa, xb), s * max(xa, xb)))
        jlo, jhi = m1 - wf / 2, m2 + wf / 2   # 与缺省 min/max 盒完全同区间
        # 转角外上角 x：Δ 内移（xb<xa）时 jog 与竖直段外侧缘齐平（x=±(XA+W_F/2)），
        # 外移时与内侧缘齐平（x=±(XA−W_F/2)）；缺口自角点向 jog 远端延伸 c
        cx = s * (xa + wf / 2) if xb < xa else s * (xa - wf / 2)
        nlo, nhi = (sorted((cx, cx - s * c_m)) if xb < xa
                    else sorted((cx, cx + s * c_m)))
        if abs(nlo - jlo) < 1e-12:      # 缺口在 jog 低端：主段=[nhi, jhi]
            mlo, mhi = nhi, jhi
        else:                           # 缺口在高端：主段=[jlo, nlo]
            mlo, mhi = jlo, nlo
        lines.append(
            f"gysel.AddBox(({mlo!r}, {yj - wf / 2!r}, H_SUB),\n"
            f"             ({mhi!r}, {yj + wf / 2!r}, H_SUB), priority=10)\n"
            f"gysel.AddBox(({nlo!r}, {yj - wf / 2!r}, H_SUB),\n"
            f"             ({nhi!r}, {yj + wf / 2 - c_m!r}, H_SUB), priority=10)")
    return "\n".join(lines) + "\n"


def _gysel_lines(p: dict[str, Any]) -> str:
    # Gysel 功分器（WP2.3 横向变体，#206 理论核验轮定版拓扑 + P2⑪ L-jog 等长
    # 几何重设计 2026-09-16，对照 Microwaves101 "Gysel even/odd mode analysis"
    # 官方口径）：六节 λ/4 环。环序：P1—[70.7Ω λ/4 臂]—P2—[50Ω λ/4 隔离线=
    # 竖直 YJ+顶端横移 jog]—Δ1(x=−iso_len)—[50Ω λ/2 桥带，跨度 2·iso_len 精确，
    # 中点开路=第 6 节点]—Δ2(x=+iso_len)—[50Ω λ/4 隔离线]—P3—[70.7Ω λ/4 臂]—P1；
    # Δ1/Δ2 各接 50Ω LumpedElement 端接（atten_pi shunt 同款：ny=2，盒 z 跨
    # 0→H_SUB 短柱接 z-min PEC 地）。
    # 隔离机制（skrf 六段线+双负载装配 @f0 实证，理论核验轮）：
    # 偶模（输出同相）：臂把 Σ 结点 2·Z0 变换为 Z0（输入匹配）；桥带中点开路
    #   经半段 λ/4 变短路压住 Δ 点、再经 λ/4 隔离线变开路——负载支路在输出
    #   端不可见；奇模（反相）：P1 结点/桥带中点=虚拟地，臂与桥带各经 λ/4 变
    #   开路，输出只见 λ/4 隔离线端接的 50Ω 负载（被吸收）。Γe=Γo=0 →
    #   S22=(Γe+Γo)/2=0 且 S32=(Γe−Γo)/2=0。
    # 判废锚（同轮 skrf 装配证据）：无桥带朴素拓扑 S21=-6.53dB/S11=-9.5dB/
    #   S32=-15.6dB；合并单负载拓扑 S21=-9.03dB/S32=-2.5dB——λ/2 桥带是隔离
    #   的必要环节。
    # 几何（_gysel_layout 单一事实源）：矩形旧版桥带继承 2·arm_len（+2.32%）
    #   电路级把 @f0 S32/S11 封顶 -34.8dB（P2⑪ 归因主因）；L-jog 变体电路级
    #   @f0 ≤-88dB（装配实测），EM 地板由两处未切角 90° 弯折决定（bend 模板
    #   |S11|<-15dB 口径估 -35~-40dB）。#211 pt2 矩形真跑基线 S32=-32.6dB/
    #   S11=-26.7dB；定案看 pt3 改善量如实落账。
    # 门：β±2%、|S21|/|S31| -3±1dB 且差≤0.5dB、|S32|≤-15dB、|S11|≤-10dB。
    lay = _gysel_layout(p)
    jog_src = _gysel_jog_lines(lay)
    return f'''W_A = {lay["wa"]!r} * 1e-3
W_F = {lay["wf"]!r} * 1e-3
XA = {lay["xa"]!r} * 1e-3
YI = {lay["yi"]!r} * 1e-3
JOG = {lay["jog"]!r} * 1e-3   # L-jog 横移 |arm_len−iso_len|
YJ = {lay["yj"]!r} * 1e-3     # 隔离线竖直段 iso_len−jog（竖直+横移=λ/4）
XB = {lay["xb"]!r} * 1e-3     # Δ 节点 x=±iso_len → 桥带跨度 2·iso_len=λ/2
G = {lay["g"]!r} * 1e-3
gysel = CSX.AddMetal("gysel")
# 下边双臂（70.7Ω，λ/4×2）：P1 结点居中分叉
gysel.AddBox((-XA, -W_A / 2, H_SUB), (XA, W_A / 2, H_SUB), priority=10)
# 左右竖边（50Ω λ/4 隔离线竖直段 YJ）：P2/P3 角部 → jog 转角
gysel.AddBox((-XA - W_F / 2, 0.0, H_SUB),
             (-XA + W_F / 2, YJ, H_SUB), priority=10)
gysel.AddBox((XA - W_F / 2, 0.0, H_SUB),
             (XA + W_F / 2, YJ, H_SUB), priority=10)
{jog_src}# 顶边桥带（50Ω λ/2：Δ1→Δ2 跨度 2·XB=2·iso_len 精确，中点开路节点悬空不连接）
gysel.AddBox((-XB - W_F / 2, YJ - W_F / 2, H_SUB),
             (XB + W_F / 2, YJ + W_F / 2, H_SUB), priority=10)
# 隔离负载 Δ1/Δ2（x=±XB）：50Ω LumpedElement 短柱（z 0→H_SUB，ny=2）
_r1 = CSX.AddLumpedElement("iso_load1", ny=2, caps=True, R=50.0)
_r1.AddBox((-XB - W_F / 2, YJ - G / 2, 0.0),
           (-XB + W_F / 2, YJ + G / 2, H_SUB), priority=10)
_r2 = CSX.AddLumpedElement("iso_load2", ny=2, caps=True, R=50.0)
_r2.AddBox((XB - W_F / 2, YJ - G / 2, 0.0),
           (XB + W_F / 2, YJ + G / 2, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=gysel,
                 start=np.array([W_F / 2, -BOARD, H_SUB]),
                 stop=np.array([-W_F / 2, 0, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=BOARD / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=gysel,
                 start=np.array([-XA + W_F / 2, -BOARD, H_SUB]),
                 stop=np.array([-XA - W_F / 2, 0, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=BOARD / 3, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=gysel,
                 start=np.array([XA + W_F / 2, -BOARD, H_SUB]),
                 stop=np.array([XA - W_F / 2, 0, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=BOARD / 3, priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in gysel.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _tjunc_lines(p: dict[str, Any]) -> str:
    # 微带 T 接头（WP2.2 不连续性基元）：主线沿 y（端口 1/2 在 y 边界，
    # mline 已验证手法），支臂沿 +x（端口 3 在 x 边界，prop_dir='x'）。
    # 全臂同宽 50Ω 对称均分口径。锚判据=skrf 理想三端口结点
    # （S=(1/3)[[-1,2,2],[2,-1,2],[2,2,-1]]）+ 三条 HJ 线级联裁判。
    return f'''W_F = {p.get("w_feed_mm", 1.1134)!r} * 1e-3
TL = {p.get("through_len_mm", 25.0)!r} * 1e-3
BL = {p.get("branch_len_mm", 20.0)!r} * 1e-3
tjunc = CSX.AddMetal("tjunc")
tjunc.AddBox((-W_F / 2, -TL, H_SUB), (W_F / 2, TL, H_SUB), priority=10)
tjunc.AddBox((0.0, -W_F / 2, H_SUB), (BL, W_F / 2, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=tjunc,
                 start=np.array([W_F / 2, -BOARD, H_SUB]),
                 stop=np.array([-W_F / 2, -TL, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(-TL + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=tjunc,
                 start=np.array([-W_F / 2, BOARD, H_SUB]),
                 stop=np.array([W_F / 2, TL, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - TL) / 3, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=tjunc,
                 start=np.array([BOARD, W_F / 2, H_SUB]),
                 stop=np.array([BL, -W_F / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - BL) / 3, priority=10)
for _prim in tjunc.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _wilk_lines(p: dict[str, Any]) -> str:
    # 拓扑：输入馈线 → T 型分叉 → 双 λ/4 臂（x 向并列，臂间距 8mm）→ 两路
    # 输出；臂末端跨接 100Ω 隔离电阻（LumpedElement）。
    # 参数语义（2026-09-04 统一，对齐 recipe/HFSS/fake 三方口径）：
    # series_w_mm = 70.7Ω λ/4 臂宽（窄），shunt_w_mm = 50Ω 馈线宽（宽）。
    return f'''W_IN = {p.get("shunt_w_mm", 1.113)!r} * 1e-3
W_ARM = {p.get("series_w_mm", 0.604)!r} * 1e-3
L_ARM = {p.get("arm_len_mm", 18.1)!r} * 1e-3
GAP = 8.0 * 1e-3
XA = GAP / 2 + W_ARM / 2
Y_T = -30e-3
Y_END = Y_T + L_ARM
mline = CSX.AddMetal("microstrip")
mline.AddBox((-XA - W_ARM / 2, Y_T, H_SUB), (XA + W_ARM / 2, Y_T + W_ARM, H_SUB), priority=10)
mline.AddBox((-XA - W_ARM / 2, Y_T, H_SUB), (-XA + W_ARM / 2, Y_END, H_SUB), priority=10)
mline.AddBox((XA - W_ARM / 2, Y_T, H_SUB), (XA + W_ARM / 2, Y_END, H_SUB), priority=10)
resistor = CSX.AddLumpedElement("isolation_resistor", ny=0, caps=True, R=100.0)
resistor.AddBox((-GAP / 2, Y_END - W_ARM / 2, H_SUB), (GAP / 2, Y_END + W_ARM / 2, H_SUB), priority=5)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=mline,
                 start=np.array([W_IN / 2, -BOARD, H_SUB]),
                 stop=np.array([-W_IN / 2, Y_T, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y_T + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=mline,
                 start=np.array([-XA + W_IN / 2, BOARD, H_SUB]),
                 stop=np.array([-XA - W_IN / 2, Y_END, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y_END) / 3, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=mline,
                 start=np.array([XA + W_IN / 2, BOARD, H_SUB]),
                 stop=np.array([XA - W_IN / 2, Y_END, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y_END) / 3, priority=10)
# MSLPort 自动补画的馈线原语默认 priority=0，会输给手画金属的 priority=10
# 而被算子判 "Unused primitive"——统一提到 10（官方口径：金属优先级最高）。
for _prim in mline.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _patch_lines(p: dict[str, Any]) -> str:
    # 结构 = 官方 Simple Patch Antenna（2026-09-05 冒烟审计后重构，对照
    # wiki.openems.de Tutorial: Simple Patch Antenna）：
    # - patch_len_mm = 谐振 λ/2 轴（x 向）；patch_w_mm = 非谐振宽（y 向）；
    # - 馈电 = LumpedPort 底探针（R=50，z 跨基板 0→H_SUB，y 向 2mm 宽、
    #   x 向 0.2mm，位置 x=-feed_offset_mm 沿谐振轴——官方 feed.pos 口径）。
    #   消费 feed_offset_mm，闭合 #154 家族的 openEMS 侧缺口（HFSS probe
    #   在 (feed_offset,0)、fake feed_offset→匹配，同语义）。
    # 旧边缘微带馈（MSLPort）两处结构性错误（冒烟证据
    # runs/audit_freq_scale/smoke_patch_auto/ 谷位 3.08GHz、s11@2.4=+0.4dB
    # 非物理）：①辐射器件 AIR_SIDE 把域扩到 ±(BOARD+λ0/4)，而端口面仍贴
    # ±BOARD——馈线止于域中，违反"端口面贴 PML 边界"铁律，入射/反射分解
    # 失效；②馈点 x=0 是 patch_len 谐振模的场节点，谐振根本激励不起来。
    # 另：更早"底部零宽探针不耦合（|S11|≡1）"是零宽盒激励体积坍缩（铁律
    # "激励盒必须与网格对齐"）——本版 0.2×2mm 盒 + _near_points 盒边进
    # 网格，官方教程同款。
    return f'''PL = {p.get("patch_len_mm", 34.9)!r} * 1e-3
PW = {p.get("patch_w_mm", 50.0)!r} * 1e-3
FEED_X = -{p.get("feed_offset_mm", 5.5)!r} * 1e-3   # 官方口径：x=-feed_offset
patch = CSX.AddMetal("patch")
patch.AddBox((-PL / 2, -PW / 2, H_SUB), (PL / 2, PW / 2, H_SUB), priority=10)
_port1 = LumpedPort(CSX, port_nr=1, R=50.0,
                    start=np.array([FEED_X - 0.1e-3, -1e-3, 0]),
                    stop=np.array([FEED_X + 0.1e-3, 1e-3, H_SUB]),
                    exc_dir="z", excite=1, priority=5)
_port2 = _port1   # 单端口模板：footer 的 single-port fallback 口径（S21 列≡S11）
'''


def _branchline_lines(p: dict[str, Any]) -> str:
    # 标准角馈 branchline（2026-09-05 重构，对照 Microwaves101/PMC 口径）：
    # 正方形环（横臂 series_w=35.35Ω 串联臂、竖臂 shunt_w=50Ω 并联臂，各 λ/4）
    # + 四角 50Ω 馈线到端口面。
    # 旧版三处结构性错误：横竖阻抗反置 / 臂中点馈电 / 隔离端悬空。
    # 2026-09-16 四端口升级（openems-real-smoke-bundle ④）：port4 隔离端由
    # "馈线延至 PML 端接"改为真 MSLPort（端口面贴板边 x=−BOARD，与 port2 镜像
    # 同口径 MeasPlaneShift），四端口 excite 随 _excite_port 四态切换
    # （ratrace 范式）——渲染脚本尾部走单激励 9 列 CSV，整 4×4 由
    # openems_rotation.solve_smatrix_openems 进程隔离轮转装配（#208）。
    # 端口语义与 linkage.field_circuit_anchor.branchline_smatrix 一致：
    # 串联臂 1-2 / 4-3（横臂 35.35Ω），并联臂 1-4 / 2-3（竖臂 50Ω）；
    # S21=直通、S31=耦合、S41=隔离。
    ep = int(p.get("_excite_port", 1) or 1)
    return f'''ARM_L = {p.get("arm_len_mm", 20.5)!r} * 1e-3
SW = {p.get("series_w_mm", 1.87)!r} * 1e-3      # 横臂 35.35Ω（串联臂）
SHW = {p.get("shunt_w_mm", 1.11)!r} * 1e-3      # 竖臂/馈线 50Ω
HALF = ARM_L / 2
mline = CSX.AddMetal("microstrip")
mline.AddBox((-HALF - SHW / 2, HALF - SW / 2, H_SUB), (HALF + SHW / 2, HALF + SW / 2, H_SUB), priority=10)
mline.AddBox((-HALF - SHW / 2, -HALF - SW / 2, H_SUB), (HALF + SHW / 2, -HALF + SW / 2, H_SUB), priority=10)
mline.AddBox((-HALF - SHW / 2, -HALF, H_SUB), (-HALF + SHW / 2, HALF, H_SUB), priority=10)
mline.AddBox((HALF - SHW / 2, -HALF, H_SUB), (HALF + SHW / 2, HALF, H_SUB), priority=10)
# 四角 50Ω 馈线：p1 左下向下 / p2 右下向右 / p3 右上向上 / p4 隔离端左上向左
# （四端全为 MSLPort，端口面贴板边=域边界；MSLPort 自画同宽馈线段与之重叠）
mline.AddBox((-HALF - SHW / 2, -BOARD, H_SUB), (-HALF + SHW / 2, -HALF, H_SUB), priority=10)
mline.AddBox((HALF, -HALF - SHW / 2, H_SUB), (BOARD, -HALF + SHW / 2, H_SUB), priority=10)
mline.AddBox((HALF - SHW / 2, HALF, H_SUB), (HALF + SHW / 2, BOARD, H_SUB), priority=10)
mline.AddBox((-BOARD, HALF - SHW / 2, H_SUB), (-HALF, HALF + SHW / 2, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=mline,
                 start=np.array([-HALF + SHW / 2, -BOARD, H_SUB]),
                 stop=np.array([-HALF - SHW / 2, -HALF, 0]),
                 prop_dir="y", exc_dir="z", excite={1 if ep == 1 else 0}, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - HALF) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=mline,
                 start=np.array([BOARD, -HALF + SHW / 2, H_SUB]),
                 stop=np.array([HALF, -HALF - SHW / 2, 0]),
                 prop_dir="x", exc_dir="z", excite={1 if ep == 2 else 0}, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - HALF) / 3, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=mline,
                 start=np.array([HALF + SHW / 2, BOARD, H_SUB]),
                 stop=np.array([HALF - SHW / 2, HALF, 0]),
                 prop_dir="y", exc_dir="z", excite={1 if ep == 3 else 0}, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - HALF) / 3, priority=10)
_port4 = MSLPort(CSX, port_nr=4, metal_prop=mline,
                 start=np.array([-BOARD, HALF + SHW / 2, H_SUB]),
                 stop=np.array([-HALF, HALF - SHW / 2, 0]),
                 prop_dir="x", exc_dir="z", excite={1 if ep == 4 else 0}, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - HALF) / 3, priority=10)
for _prim in mline.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _dipole_lines(p: dict[str, Any]) -> str:
    # 官方口径重写（WP1.3，#191 refs §8：Helical/Dipole-SAR 教程）：
    # 自由空间细带偶极子（无基板无地，域全 MUR 底 MUR），振子沿 x、
    # 位于 z=0 平面，中央 gap 处 LumpedPort 直馈（R=z0_ohm，norm='x'）。
    # 首版（基板顶面 PEC 带 + MSL 微带馈混合怪 + 底 PEC 镜像）按官方
    # 口径废弃（⑭ 拓扑疑问的裁决）。
    return f'''DIP_LEN = {p.get("dipole_len_mm", 58.0)!r} * 1e-3
DIP_W = {p.get("dipole_w_mm", 2.0)!r} * 1e-3
GAP = {p.get("gap_mm", 2.0)!r} * 1e-3
dipole = CSX.AddMetal("dipole")
dipole.AddBox((-DIP_LEN / 2, -DIP_W / 2, 0), (-GAP / 2, DIP_W / 2, 0), priority=10)
dipole.AddBox((GAP / 2, -DIP_W / 2, 0), (DIP_LEN / 2, DIP_W / 2, 0), priority=10)
# 中央 gap LumpedPort 直馈（官方 Helical 教程口径：AddLumpedPort(
# port_nr, R, start, stop, norm_dir, excite)）
_port1 = FDTD.AddLumpedPort(1, 50.0, np.array([-GAP / 2, 0, 0]),
                            np.array([GAP / 2, 0, 0]), "x", 1.0, priority=5)
'''


def _coupled_lines(p: dict[str, Any]) -> str:
    return f'''CL_LEN = {p.get("coupled_len_mm", 20.0)!r} * 1e-3
CL_W = {p.get("line_w_mm", 1.0)!r} * 1e-3
CL_GAP = {p.get("gap_mm", 0.5)!r} * 1e-3
mline = CSX.AddMetal("microstrip")
mline.AddBox((-CL_W - CL_GAP / 2, -CL_LEN / 2, H_SUB), (-CL_GAP / 2, CL_LEN / 2, H_SUB), priority=10)
mline.AddBox((CL_GAP / 2, -CL_LEN / 2, H_SUB), (CL_GAP / 2 + CL_W, CL_LEN / 2, H_SUB), priority=10)
mline.AddBox((-CL_W - CL_GAP / 2, -BOARD, H_SUB), (-CL_GAP / 2, -CL_LEN / 2, H_SUB), priority=10)
mline.AddBox((-CL_W - CL_GAP / 2, CL_LEN / 2, H_SUB), (-CL_GAP / 2, BOARD, H_SUB), priority=10)
mline.AddBox((CL_GAP / 2, -BOARD, H_SUB), (CL_GAP / 2 + CL_W, -CL_LEN / 2, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=mline,
                 start=np.array([-CL_GAP / 2, -BOARD, H_SUB]),
                 stop=np.array([-CL_W - CL_GAP / 2, -CL_LEN / 2, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - CL_LEN / 2) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=mline,
                 start=np.array([-CL_GAP / 2, BOARD, H_SUB]),
                 stop=np.array([-CL_W - CL_GAP / 2, CL_LEN / 2, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - CL_LEN / 2) / 3, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=mline,
                 start=np.array([CL_GAP / 2 + CL_W, -BOARD, H_SUB]),
                 stop=np.array([CL_GAP / 2, -CL_LEN / 2, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - CL_LEN / 2) / 3, priority=10)
for _prim in mline.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _stepped_lines(p: dict[str, Any]) -> str:
    return f'''Z1_W = {p.get("z1_width_mm", 0.3)!r} * 1e-3
Z2_W = {p.get("z2_width_mm", 3.0)!r} * 1e-3
SEG_LEN = {p.get("seg_len_mm", 5.0)!r} * 1e-3
N_SEGS = {int(p.get("n_segments", 5))}
TOTAL = N_SEGS * SEG_LEN
filt = CSX.AddMetal("filter")
filt.AddBox((-Z1_W / 2, -BOARD, H_SUB), (Z1_W / 2, -TOTAL / 2, H_SUB), priority=10)
for i in range(N_SEGS):
    w = Z1_W if i % 2 == 0 else Z2_W
    y0 = -TOTAL / 2 + i * SEG_LEN
    filt.AddBox((-w / 2, y0, H_SUB), (w / 2, y0 + SEG_LEN, H_SUB), priority=10)
filt.AddBox((-Z1_W / 2, TOTAL / 2, H_SUB), (Z1_W / 2, BOARD, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=filt,
                 start=np.array([Z1_W / 2, -BOARD, H_SUB]),
                 stop=np.array([-Z1_W / 2, -TOTAL / 2, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - TOTAL / 2) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=filt,
                 start=np.array([Z1_W / 2, BOARD, H_SUB]),
                 stop=np.array([-Z1_W / 2, TOTAL / 2, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - TOTAL / 2) / 3, priority=10)
for _prim in filt.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''

# ─── 柱坐标 rat-race（§10.20 补强①；#219 根治路线）─────────────────────────
# 官方口径（铁律 1c；已核对官方例 + openEMS 作者 discussion #196 定谳）：
#   openEMS(CoordSystem=1) + ContinuousStructure(CoordSystem=1)；(r, a, z) 网格；
#   mesh.AddLine('r'/'a'/'z', ...) / SmoothMeshLines(0/1/2, ...)；
#   mesh.a = linspace(-pi, pi, N) 即「全 2π 闭合网格」——作者原话：要闭合柱
#   网格，alpha 须覆盖整个 0..2π（如 -π..+π）；r 域可为环域（r_min>0，官方
#   Coax_Cylindrical_MG 例 rad_i=10>0 即环域）。端口面 r=R_DOM 贴外边界 PML_8。
# 物理动机（#219）：直角网格把物理 R=17.344mm 的环阶梯化成慢波栅格，0.4mm
#   档引擎常数 k=1.0975（HFSS 仲裁背书为网格伪象）。柱坐标下环带 = 常数 r
#   的精确圆环（r 网格线即内外带缘）、径向馈沿径向栅格化，理论无阶梯化
#   → 渲染半径 = 物理半径（k=1，不做任何补偿）。
# 引擎实测限制（v0.37.0-rc1，本次冒烟日志实证）：柱坐标算子**不支持 MUR**
#   （"Mur ABC Extension is not compatible with cylinder-coords!! skipping"）
#   → 所有吸收面必须用 PML；a 向全 2π 闭合网格由引擎自动周期化。
_CYL_RING_AZIMUTH_DEG = (0.0, 60.0, 120.0, 300.0)
# a 网格 = 600 单元/2π（0.6°）；60° 端口方位角 = 100 单元 → 精确入网。
_CYL_ALPHA_CELLS = 600


def _cyl_alpha_lines() -> tuple[int, float]:
    """全 2π a 网格：返回 (线数, 单元角 da)；端点 -π/+π 同址闭合。"""
    n_cells = int(_CYL_ALPHA_CELLS)
    return n_cells + 1, 2.0 * math.pi / n_cells


def _cyl_azimuths_rad() -> tuple[float, ...]:
    """四端口方位角（弧度）归一化到 [-π, π)（300° ≡ -60°，物理同一处）。"""
    out = []
    for deg in _CYL_RING_AZIMUTH_DEG:
        a = math.radians(deg)
        out.append((a + math.pi) % (2.0 * math.pi) - math.pi)
    return tuple(out)


def build_ratrace_cylindrical(
    p: dict[str, Any],
    *,
    r_dom_m: float = 28.0e-3,
    feed_shift_m: float = 1.0e-3,
    meas_shift_m: float = 5.3e-3,
    excite_port: int = 1,
) -> str:
    """柱坐标 rat-race 几何段（环带 + 四条径向馈 + 四个 MSLPort）。

    环带 = 常数 r 圆环（r∈[R−W_R/2, R+W_R/2]，a 全 2π）；四条馈线沿径向
    （a = 0/60/120/300°，r∈[R, R_DOM]），**逐 r 网格单元**栅格化并令 a 半宽
    = W_F/(2·r_c) → 物理等宽（单盒常数 azimuth 会按 R_DOM/R 锥化，改变端口
    参考阻抗）。端口面 = r=R_DOM 外边界（PML_8）；MSLPort 方位半宽取测量面
    处等宽值，使 U/I 探针恰好覆盖全带。返回脚本 body 文本（网格必须由调用
    方先行构建——body 读网格 r 线）。
    """
    w_ring = float(p.get("w_ring_mm", 0.6035)) * 1e-3
    w_feed = float(p.get("w_feed_mm", 1.1134)) * 1e-3
    r_ring = float(p.get("r_ring_mm", 17.344)) * 1e-3
    _n_alpha, da = _cyl_alpha_lines()
    az = list(_cyl_azimuths_rad())
    ep = max(1, min(4, int(excite_port)))
    r_meas = max(r_dom_m - meas_shift_m, r_ring)
    half_port = w_feed / (2.0 * r_meas)
    ports = []
    for k, a_k in enumerate(az, start=1):
        ports.append(
            f'_port{k} = MSLPort(CSX, port_nr={k}, metal_prop=ratrace,\n'
            f'                 start=np.array([R_DOM, {a_k!r} - _HALF_PORT, H_SUB]),\n'
            f'                 stop=np.array([R_RING, {a_k!r} + _HALF_PORT, 0.0]),\n'
            f'                 prop_dir="r", exc_dir="z", '
            f'excite={1 if ep == k else 0},\n'
            f'                 FeedShift={feed_shift_m!r}, '
            f'MeasPlaneShift={meas_shift_m!r}, priority=10)\n'
        )
    return (
        f'W_R = {w_ring!r}\n'
        f'W_F = {w_feed!r}\n'
        f'R_RING = {r_ring!r}    # 渲染半径 = 物理半径（柱坐标无阶梯化，k=1）\n'
        f'R_DOM = {r_dom_m!r}\n'
        f'_HALF_PORT = {half_port!r}   # 测量面处等宽 a 半宽（探针覆盖全带）\n'
        f'_DA = {da!r}\n'
        f'_AZ = [{", ".join(repr(a) for a in az)}]\n'
        '\n'
        'ratrace = CSX.AddMetal("ratrace")\n'
        '# 环带：常数 r 的精确圆环（全 2π），r 网格线即内外带缘\n'
        'ratrace.AddBox((R_RING - W_R / 2, -np.pi, H_SUB),\n'
        '               (R_RING + W_R / 2, np.pi, H_SUB), priority=10)\n'
        '# 四条径向馈线：逐 r 网格单元等物理宽段（a 半宽 = W_F/(2·r_c)）\n'
        '_RL = np.asarray(mesh.GetLines("r"))\n'
        'for _ak in _AZ:\n'
        '    for _i in range(len(_RL) - 1):\n'
        '        _ra = max(_RL[_i], R_RING)\n'
        '        _rb = min(_RL[_i + 1], R_DOM)\n'
        '        if _rb - _ra <= 1e-12:\n'
        '            continue\n'
        '        _h = W_F / (_ra + _rb)\n'
        '        ratrace.AddBox((_ra, _ak - _h, H_SUB),\n'
        '                       (_rb, _ak + _h, H_SUB), priority=10)\n'
        + "".join(ports)
        + 'for _prim in ratrace.GetAllPrimitives():\n'
        '    if _prim.GetPriority() < 10:\n'
        '        _prim.SetPriority(10)\n'
    )


def render_ratrace_cylindrical(
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    mesh_resolution_mm: float = 0.0,
    substrate: dict[str, Any] | None = None,
    excite_port: int = 1,
    r_in_mm: float = 12.0,
    r_dom_mm: float = 28.0,
) -> str:
    """渲染柱坐标 rat-race 全脚本（几何/网格/四 MSLPort/单激励列 CSV）。

    与 render_script("ratrace") 同构（9 列 CSV，整 4×4 由 excite_port
    轮转装配），但坐标系为柱坐标（CoordSystem=1）、环半径用物理值（k=1）。
    """
    params = dict(params)
    substrate = substrate or _DEFAULT_SUB
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = max((freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9, 1e6)
    er = float(substrate["er"])
    h_m = float(substrate["h_mm"]) * 1e-3
    tan_d = float(substrate.get("tan_d", 1e-3))
    f_max = f0 + fc
    base_m = (3e8 / (f_max * (er ** 0.5)) / 50 if not mesh_resolution_mm
              else float(mesh_resolution_mm) * 1e-3)
    near_m = base_m / 4
    r_in = float(r_in_mm) * 1e-3
    r_dom = float(r_dom_mm) * 1e-3
    w_ring = float(params.get("w_ring_mm", 0.6035)) * 1e-3
    r_ring = float(params.get("r_ring_mm", 17.344)) * 1e-3
    feed_shift = min(10.0 * near_m, 0.3 * (r_dom - r_ring))
    meas_shift = 0.5 * (r_dom - r_ring)
    n_alpha, _da = _cyl_alpha_lines()
    ep = max(1, min(4, int(excite_port)))
    body = build_ratrace_cylindrical(
        params, r_dom_m=r_dom, feed_shift_m=feed_shift,
        meas_shift_m=meas_shift, excite_port=ep)
    return f'''#!/usr/env/python3
"""openEMS cylindrical rat-race script (rfauto auto-generated, CoordSystem=1).

柱坐标 (r, a, z)：环带 = 常数 r 精确圆环、径向馈 = 常数 azimuth 径向段，
渲染半径 = 物理半径（k=1，无网格伪象补偿，#219 根治路线）。
"""
import csv
import os

# CSXCAD/openEMS 扩展模块依赖 DLL 不在 Python 3.8+ 的 PATH 搜索里
_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN", r"E:\\openEMS\\install\\bin")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.ports import MSLPort

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}
H_SUB = {h_m!r}
TAND = {tan_d!r}
BASE = {base_m!r}
NEAR = {near_m!r}
AIR_TOP = 5e-3
R_IN = {r_in!r}
R_DOM = {r_dom!r}
CSV_NAME = "sparams.csv"
SIM_PATH = os.path.abspath("fdtd")
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), CSV_NAME)

# ── 柱坐标 FDTD（官方 2D Cylindrical Wave / Bent Patch 口径）──
CSX = ContinuousStructure(CoordSystem=1)
FDTD = openEMS(NrTS=100000, CoordSystem=1)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# BC 序 = [r-, r+, a-, a+, z-, z+]：a 向全 2π 闭合（作者 #196 定谳，a 边界
# 不参与）；**柱坐标算子不支持 MUR**（引擎实测 "Mur ABC Extension is not
# compatible with cylinder-coords!! skipping" → MUR 静默退化为 PEC）——所有
# 吸收面一律 PML_8：r+ 端口外边界、z+ 顶空气隙；r- 内边界 PEC（环内接地
# 基板，场已衰减）；z- 地面 PEC
FDTD.SetBoundaryCond(["PEC", "PML_8", "PEC", "PEC", "PEC", "PML_8"])

mesh = CSX.GetGrid()
# r 网格：内域 R_IN → 外边界 R_DOM；环带两缘精确入网（常数 r 圆环）
mesh.AddLine("r", [R_IN, {r_ring - w_ring / 2!r}, {r_ring!r},
                   {r_ring + w_ring / 2!r}, R_DOM])
mesh.SmoothMeshLines("r", BASE)
# a 网格：全 2π 均匀闭合（端点 -π/+π 同址）；不 Smooth 以保 60° 对齐
mesh.AddLine("a", np.linspace(-np.pi, np.pi, {n_alpha}))
# z 网格：基板 4 层（官方 substrate_cells=4）+ 顶空气隙
mesh.AddLine("z", np.linspace(0.0, H_SUB, 5))
mesh.AddLine("z", H_SUB + AIR_TOP)
mesh.SmoothMeshLines("z", BASE)
# 网格最小间距守卫（#152）：去重 1µm 内近重合线，防 CFL 时间步塌缩
for _ax in ("r", "a", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((R_IN, -np.pi, 0), (R_DOM, np.pi, H_SUB), priority=0)
{body}

FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

f = np.linspace(F0 - FC, F0 + FC, 401)
_port1.CalcPort(SIM_PATH, f, ref_impedance=50)
_port2.CalcPort(SIM_PATH, f, ref_impedance=50)
_port3.CalcPort(SIM_PATH, f, ref_impedance=50)
_port4.CalcPort(SIM_PATH, f, ref_impedance=50)
_SREF = _port{ep}.uf_inc
S11 = _port1.uf_ref / _SREF
S21 = _port2.uf_ref / _SREF
S31 = _port3.uf_ref / _SREF
S41 = _port4.uf_ref / _SREF
with open(CSV_PATH, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21",
                "re_S31", "im_S31", "re_S41", "im_S41"])
    for _i, _fi in enumerate(f):
        w.writerow([_fi, S11[_i].real, S11[_i].imag, S21[_i].real,
                    S21[_i].imag, S31[_i].real, S31[_i].imag,
                    S41[_i].real, S41[_i].imag])
print("rfauto openEMS cylindrical simulation done")
'''




# ═══════════════════════════════════════════════════════════════════════════════
# WP2.3 Tier 1：hairpin（发夹线）带通滤波器——理论核验轮 + 离线几何审计
# （增量批；**附加模板**：不注册进 TEMPLATE_META，见段末"注册边界"）
# ═══════════════════════════════════════════════════════════════════════════════
# 拓扑：N 个半波谐振器折成 U 形（发夹）沿 x 并排，相邻谐振器外臂之间以耦合缝
# 做平行耦合；输入/输出 = 50Ω 抽头馈线（T 形，自 x=∓BOARD 板边接至首/末
# 谐振器外臂的抽头点）。两端均在 x 边界 → 单轴 PML；底 z-min PEC 地。
#
# ── 理论核验轮（口径/假设/来源逐条；裁判=独立来源，不自证）──
# 1) 谐振器展开长度：L_tot = λg/2 = c/(2·f0·√εeff)。来源：Pozar《Microwave
#    Engineering》半波开路线谐振器；与本仓 core/thermo_mech.py 的
#    hairpin_resonance_ghz 同式（单测互检）。εeff 一律走 skrf
#    Hammerstad-Jensen（core/synthesis.forward_z0；铁律 1c 唯一线宽口径）。
# 2) 耦合系数 ↔ 缝：同步平行耦合半波谐振器 k = (Z0e − Z0o)/(Z0e + Z0o)。
#    来源：Hong《Microstrip Filters for RF/Microwave Applications》§5.4；
#    Matthaei/Young/Jones《Microwave Filters, Impedance-Matching Networks and
#    Coupling Structures》§5。Z0e/Z0o 取耦合微带准静态闭式：Kirschning &
#    Jansen, IEEE Trans. MTT-32(1), 1984（偶/奇模填充因子 + Q 因子族），
#    零金属厚、无盖口径；对照实现 Qucs/transcalc c_microstrip.cpp
#    （C. Girardi / S. Jahn，GPL；KiCad pcb_calculator 同源）。
#    反解缝宽用 brentq（k(s) 单调递减，单测钉住）。**不采用 Akhtarzad(1975)
#    闭式综合**：本轮实测其在弱耦合（k≲0.05、s/h≳2）严重偏离 KJ 分析
#    （k=0.02：Akhtarzad 给 s=10.65mm，KJ 反解 2.15mm）——不强用，分歧以
#    数值记录在单测（诚实口径，不静默）。
# 3) 外部 Q ↔ 抽头位置：抽头在半波谐振器上距开路端 t 处接入，抽头处两段开路
#    线并联电纳 Y_res = j·Y_r·[tan(θ·τ)+tan(θ·(1−τ))]（τ=t/L_tot，θ=β·L_tot，
#    谐振 θ=π）。电纳斜率 b=(ω0/2)·dB/dω=(π/2)·Y_r·sec²(πτ)，负载 G=1/Z0
#    ⇒ Q_e = (π/2)·(Z0/Z_r)·sec²(πτ)。反解 τ=arccos(√((π/2)(Z0/Z_r)/Q_e))/π。
#    **独立校核**（#118 小步长数值）：对精确 Y_res(ω) 数值微分，与闭式逐位一致
#    （单测）。**假设**：无损（Q_e 即外部 Q）；理想 T 抽头（不连续性进器件）；
#    U 形同臂耦合与弯角造成的 f0 下移不在本级修正（待冒烟实测校准）。
# 4) C13 耦合矩阵映射（裁判口径）：core 的 synthesize_bpf_model /
#    coupling_matrix_synthesize_n2 给归一化 N+2 矩阵 M（0=源、1..N=谐振器、
#    N+1=载）。k_{i,i+1}=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M_{0,1}|²)。
#    来源：Hong §5.2/§5.3；Cameron 归一化口径外部耦合在 m_0i/m_iL。
#    独立裁判（单测）：与经典切比雪夫 g 值闭式（Pozar §8.4，
#    core/matching.chebyshev_g_values）互检：Q_e=g0·g1/FBW、
#    k_{i,i+1}=FBW/√(g_i·g_{i+1})。
#    本文件只做"k/Q_e → 几何"的确定性映射；矩阵综合在 core（数值只在内核）。
#
# ── 注册边界（#230 跨轨契约；注册已补齐）──
# 本模板最初为**附加模板**（不进注册表，#230 增量文件面所限）；注册四件套
# （docs/templates/hairpin/meta.yaml、test_template_geometry_audit 的
# EXPECTED_TEMPLATES、fake_adapter 派发、models/template_specs）已于合流轮
# 补齐——注册动作见 HAIRPIN_NOMINAL 之后的 TEMPLATE_META/TEMPLATE_NOMINAL
# 赋值块（渲染段零改动，hairpin 渲染自 680e6e7 已入库）。

# ── 闭式内核已下沉 core（WP2.3 收口 ⑦，2026-09-16）：KJ 偶/奇模、k↔缝、Q_e↔τ、
# λg/2 臂长在 core/coupled_microstrip；C13→几何映射 hairpin_design_from_order 与
# spec 综合入口 synthesize_hairpin_model 在 core/synthesis。本段只做再导出，不留
# 本地函数体副本（#116）；topology_service/fake/scripts/tests 经本模块名零改动消费。
from rfauto.core.coupled_microstrip import (  # noqa: E402
    HAIRPIN_50OHM_W_MM as _HAIRPIN_50OHM_W_MM,
)
from rfauto.core.coupled_microstrip import (  # noqa: E402
    coupled_microstrip_even_odd_ohm,
    hairpin_arm_len_mm,  # noqa: F401
    hairpin_gap_mm_from_k,  # noqa: F401
    hairpin_k_from_gap_mm,  # noqa: F401
    hairpin_qe_from_tap_frac,  # noqa: F401
    hairpin_tap_frac_from_qe,  # noqa: F401
)
from rfauto.core.synthesis import hairpin_design_from_order  # noqa: E402, F401

HAIRPIN_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（发夹线 BPF：带内回波纹波 + 带外"
                  "抑制；裁判=C13 耦合矩阵闭式 coupling_matrix_response）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["order", "w_mm", "arm_len_mm", "arm_gap_mm", "gap_mm",
               "tap_frac"],
    "topology": "发夹线带通（WP2.3 Tier1 滤波器族）：N 个 λg/2 半波谐振器折成"
                " U 形沿 x 并排，相邻外臂平行耦合（缝 gap_mm）；输入/输出为"
                " 50Ω 抽头馈线（T 形，板边 x=∓BOARD 至首/末谐振器外臂，抽头"
                " 位置 tap_frac 自开路端计）",
    "param_semantics": "order=谐振器阶数 N，w_mm=谐振器/馈线宽（50Ω，skrf HJ "
                       "综合），arm_len_mm=展开中心线总长 λg/2（2·臂长+臂间距），"
                       "arm_gap_mm=U 内两臂缝（边缘到边缘；须 ≳3×线宽量级，名义 3.0mm："
                       "同臂自耦 k_self(3.0)=0.0115 ≪ 互耦 0.0515，旧 1.0 的 k_self="
                       "0.0602 反超互耦致四轮真机 FAIL，2026-09-16 定版），gap_mm=相邻谐振器"
                       "耦合缝（锚=等缝口径；非等 k 逐缝变体走 gaps_mm 列表，"
                       "不进本 meta；**同向拓扑 gap→k 须经结构修正 c(gap)**："
                       "k_EM=c(gap)·k_KJ，c=0.12-0.26 且非单调、k_EM 上限 ~0.0155"
                       "≪ KJ 名义 0.0515——相邻臂开路端对齐致电/磁耦合反号相消，"
                       "core.coupled_microstrip.HAIRPIN_KGAP_TABLE_MM 真机表，"
                       "2026-09-17 W4④；根修见 hairpin_alt 交替取向变体），"
                       "tap_frac=抽头位置比例 τ=t/L_tot",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "全部臂缘/弯带缘/抽头缘精确入网（#198 精确入网）",
}

HAIRPIN_NOMINAL: dict[str, Any] = {
    "order": 3,
    # ── 2026-09-16 名义定版（WP2.3 收口 A2）：四项几何统一由闭式链
    # hairpin_design_from_order(3, 2.5, 0.05, 20.0) 生成并按 scripts/hairpin_calib
    # 的 design_params 同规则舍入（w/arm_len/gap 4 位、τ 6 位）——名义 = 设计链 =
    # 标定脚本 design_params 逐位同源，消 w 1.1134/1.1117（旧硬编码 50Ω 宽 vs
    # inverse_width 精算 49.95Ω/50.00Ω）与 arm_len 35.4653/35.4676 双份微漂；单测钉住。
    "w_mm": 1.1117,            # inverse_width(50Ω @2.5GHz, rogers4350b h=0.508)
    # 闭式 λg/2=35.4676（εeff=2.8578 @w，HJ）× 真机谐振修正 c_f0=1.0370（B2 pt4：
    # N=3 通带中心 2.5925 vs 2.5，U 弯+开路端等效缩短；f∝1/L → L·f0_act/f0）；
    # fake 端同源常数 fake_adapter._HAIRPIN_F0_CORR
    "arm_len_mm": 36.7799,
    # U 内两臂缝 3.0（≳2.7×线宽）：k_self(3.0)=0.0115 < 互耦 k=0.0515 < k_self(1.0)
    # =0.0602——旧名义 1.0 同臂自耦反超互耦是四轮 FAIL 的结构性根因（pt1 实证）
    "arm_gap_mm": 3.0,
    # C13 N=3/RL=20dB/FBW=0.05 → k=0.051514 → KJ 反解 s=1.132829mm
    "gap_mm": 1.1328,
    # Q_e=17.0689（=g0·g1/FBW 同源）；B1 真机标定 c(τ)=1.37437−0.75218·τ（τ=0.40/0.43
    # 两点，runs/hairpin_q_extract/summary.json）→ τ*=0.398159 重解（0.401892 闭式；
    # B3 终验轮 pt5 用单点解 0.398227，Δτ=6.8e-5≈2.5µm≪0.4mm 网格），消费端
    # hairpin_qe_from_tap_frac(τ)×c(τ) 见 fake_adapter._HAIRPIN_QE_CORR
    "tap_frac": 0.398159,
}

# ── 注册（合流待办①闭环）：hairpin 升格为正式注册模板 ──
# 四处同步：① docs/templates/hairpin/meta.yaml；②
# test_template_geometry_audit.EXPECTED_TEMPLATES（17→18）；③
# fake_adapter 派发分支（_hairpin_sparams）；④ models/template_specs
# （_register_hairpin）。同对象注册（非拷贝）钉死单一事实源，防双份
# 字典漂移；渲染段零改动。
TEMPLATE_META["hairpin"] = HAIRPIN_META
TEMPLATE_NOMINAL["hairpin"] = HAIRPIN_NOMINAL


def hairpin_meta() -> dict[str, Any]:
    """返回 hairpin 模板元数据（与 template_meta("hairpin") 同构的便捷别名）。"""
    meta = dict(HAIRPIN_META)
    meta["template"] = "hairpin"
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(HAIRPIN_NOMINAL)
    return meta


def _fmt_list(values: list[float], ndigits: int) -> str:
    """数值列表 → 紧凑字符串（notes 用；避免 % 格式化触发 UP031）。"""
    return "[" + ", ".join(f"{v:.{ndigits}f}" for v in values) + "]"


_HAIRPIN_ORIENTATIONS: tuple[str, ...] = ("same", "alternating")


def _hairpin_layout(p: dict[str, Any], *,
                    orientation: str = "same") -> dict[str, Any]:
    """hairpin 几何统一计算（单位：米）——render/_near_points/geometry_spec 共用。

    防三处各自推导几何造成漂移（#212 审计口径）。参数与 HAIRPIN_META 一致；
    可选 gaps_mm（长度 order−1 的列表，mm）给出逐缝非等耦合变体。
    order≥1：N=1 为单谐振器双抽头探针（XS=[左臂, 右臂] 两抽头各距开路端
    τ·L_tot，天然对称双端口；B1 Q_u/Q_e 标定用），无耦合缝。

    orientation（2026-09-18 w2g，0dk 根修）："same"=全部 U 同向（开路端齐在 y0、
    弯带齐在 y1，hairpin 模板口径，既有键逐位不变）；"alternating"=奇数序谐振器
    上下翻转（弯带在 y0 侧、开路端在 y1），相邻臂开路端交替 → 电/磁耦合同号叠加
    （hairpin_alt 模板口径）。两取向臂盒 y 跨度同为 [y0, y1]，仅弯带/开路端互换，
    耦合长度与网格配方不变（A/B 只隔离拓扑变量）。增量键：orientation/flips/
    y_open/y_bend（逐腔）/y_taps=[输入, 输出]/y_tap_out（末腔翻转时输出抽头自
    其开路端 y1 向下计 τ·L_tot；同向时恒 = y_tap）。
    """
    if orientation not in _HAIRPIN_ORIENTATIONS:
        raise ValueError(
            f"hairpin orientation 须为 {_HAIRPIN_ORIENTATIONS}（得 {orientation!r}）")
    n = int(p.get("order", 3))
    if n < 1:
        raise ValueError("hairpin 阶数须 ≥1（order=1 为单谐振器双抽头探针）")
    wf = float(p.get("w_mm", _HAIRPIN_50OHM_W_MM)) * 1e-3
    total = float(p.get("arm_len_mm", 35.46)) * 1e-3
    arm_gap = float(p.get("arm_gap_mm", 3.0)) * 1e-3   # 2026-09-16 名义定版 3.0
    tap_frac = float(p.get("tap_frac", 0.402))
    if not 0.0 < tap_frac < 0.5:
        raise ValueError("tap_frac 须在 (0,0.5)")
    if wf <= 0.0 or total <= 0.0 or arm_gap <= 0.0:
        raise ValueError("hairpin 几何参数须 >0")
    b = wf + arm_gap                        # U 内两臂中心距
    l_arm = (total - b) / 2.0               # 展开 = 2·l_arm + b = L_tot
    if l_arm <= 0.0:
        raise ValueError("arm_len_mm 必须大于 U 臂间距（折叠不成立）")
    gaps_raw = p.get("gaps_mm")
    if gaps_raw is None:
        gaps = [float(p.get("gap_mm", 1.133)) * 1e-3] * (n - 1)
    else:
        gaps = [float(v) * 1e-3 for v in gaps_raw]
        if len(gaps) != n - 1:
            raise ValueError(f"gaps_mm 长度须为 order-1={n - 1}")
    if any(gap <= 0.0 for gap in gaps):
        raise ValueError("耦合缝须 >0")

    centres: list[float] = []
    xs: list[float] = []
    xc = 0.0
    for i in range(n):
        centres.append(xc)
        xs += [xc - b / 2.0, xc + b / 2.0]
        if i < n - 1:
            xc += b + wf + gaps[i]
    shift = -0.5 * (centres[0] + centres[-1])   # 阵列 x 居中
    xs = [v + shift for v in xs]
    centres = [v + shift for v in centres]

    y0 = -total / 4.0
    y1 = y0 + l_arm
    y_tap = y0 + tap_frac * total
    if y_tap >= y1:
        raise ValueError(
            f"抽头位置 τ={tap_frac} 超出单臂（y_tap={y_tap:.4f}m ≥ 臂顶"
            f" {y1:.4f}m）；减小 tap_frac 或 arm_gap_mm")
    # 取向：flips[i]=第 i 腔上下翻转（alternating 下奇数序腔），开路端/弯带互换；
    # 输出抽头随末腔取向自其开路端计 τ·L_tot（翻转腔开路端在 y1 → 向下计）
    flips = [orientation == "alternating" and (i % 2 == 1) for i in range(n)]
    y_open = [y1 if f else y0 for f in flips]
    y_bend = [y0 if f else y1 for f in flips]
    y_tap_out = (y1 - tap_frac * total) if flips[-1] else y_tap
    return {"n": n, "wf": wf, "arm_gap": arm_gap, "b": b, "l_arm": l_arm,
            "total": total, "gaps": gaps, "xs": xs, "centres": centres,
            "y0": y0, "y1": y1, "y_tap": y_tap, "tap_frac": tap_frac,
            "x_feed_in": xs[0], "x_feed_out": xs[-1],
            "orientation": orientation, "flips": flips,
            "y_open": y_open, "y_bend": y_bend,
            "y_taps": [y_tap, y_tap_out], "y_tap_out": y_tap_out}


def _hairpin_lines(p: dict[str, Any]) -> str:
    # 发夹线 BPF（WP2.3 Tier1 附加模板）：N 个 U 形 λg/2 谐振器沿 x 并排，
    # 相邻外臂平行耦合；50Ω 抽头馈线（T 形）自板边接首/末外臂。等缝口径
    # gap_mm；逐缝非等耦合走 gaps_mm 列表。口径见文末 WP2.3 hairpin 段。
    lay = _hairpin_layout(p)
    return f'''N = {lay["n"]}
WF = {lay["wf"]!r}                       # 谐振器/馈线宽（50Ω，HJ）
B = {lay["b"]!r}                         # U 内两臂中心距
LARM = {lay["l_arm"]!r}                  # 单臂长（展开 2·LARM+B=λg/2）
Y0 = {lay["y0"]!r}                       # U 开路端 y
Y1 = {lay["y1"]!r}                       # 臂顶/弯带中心 y
YT = {lay["y_tap"]!r}                    # 抽头 y（自开路端计 τ·λg/2）
XS = {lay["xs"]!r}                       # 各谐振器 [左臂心, 右臂心]（m）
hairpin = CSX.AddMetal("hairpin")
for _i in range(N):
    _xl = XS[2 * _i]
    _xr = XS[2 * _i + 1]
    hairpin.AddBox((_xl - WF / 2, Y0, H_SUB),
                   (_xl + WF / 2, Y1, H_SUB), priority=10)
    hairpin.AddBox((_xr - WF / 2, Y0, H_SUB),
                   (_xr + WF / 2, Y1, H_SUB), priority=10)
    hairpin.AddBox((_xl - WF / 2, Y1 - WF / 2, H_SUB),
                   (_xr + WF / 2, Y1 + WF / 2, H_SUB), priority=10)
# 抽头馈线（T 形）：板边 x=∓BOARD → 首/末谐振器外臂中心
hairpin.AddBox((-BOARD, YT - WF / 2, H_SUB),
               (XS[0], YT + WF / 2, H_SUB), priority=10)
hairpin.AddBox((XS[-1], YT - WF / 2, H_SUB),
               (BOARD, YT + WF / 2, H_SUB), priority=10)
# 去嵌（WP2.3 收口 A1，2026-09-16）：测量面自板边推到抽头结前 10·NEAR+4·H_SUB
# （≈3mm，首版纯 10·NEAR≈1mm 落进结区网格加密过渡带——三探针 U_delta=[0.28, 0.19]mm
# 非均匀，openEMS β 二阶差分假定均匀间距 → β 金标准恒定 −23%（τ=0.30 实测，全带平
# 坦）；4·H_SUB≈2mm 回到均匀 base 网格，β 恢复）。残量 ≈3mm≈0.043λg，且 |S| 幅值
# 类指标本与参考面位置无关（无损馈线上平移不改幅值）；旧口径 feed_len/3 留 2/3
# ≈34mm≈0.49λg 未去嵌才是相位类分析的问题。端口 start/stop/FeedShift 不动，
# 其它模板仍用官方 端口段长/3（均匀通线口径）。
_port1 = MSLPort(CSX, port_nr=1, metal_prop=hairpin,
                 start=np.array([-BOARD, YT + WF / 2, H_SUB]),
                 stop=np.array([XS[0], YT - WF / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(XS[0] + BOARD) - 10 * NEAR - 4 * H_SUB,
                 priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=hairpin,
                 start=np.array([BOARD, YT - WF / 2, H_SUB]),
                 stop=np.array([XS[-1], YT + WF / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - XS[-1]) - 10 * NEAR - 4 * H_SUB,
                 priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in hairpin.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ── hairpin_alt：交替取向发夹线（2026-09-18 w2g，TODO 0dk 根修 / audit #11）──
# 物理（0dk 真机结论）：同向 U 并排时相邻臂开路端对齐，电耦合
# （开路端电压反节点对齐）与磁耦合（弯带电流反节点对齐、相邻臂电流反向）反号相消，
# k_EM=c(gap)·k_KJ 非单调、极大 0.0155@0.65 ≪ KJ 名义 0.0515（比值上限 ≈0.30），
# FBW5% 名义在同向参数空间内无自洽设计点。经典 hairpin 排布（Hong《Microstrip
# Filters》§5.6）把相邻谐振器交替翻转：相邻臂一端开路/一端弯带互补，电/磁耦合同号
# 叠加，k_EM 应回到平行耦合线闭式量级——本变体即此拓扑。
# 名义（铁律 #1c/#252：全部综合精算，无手抄毫米数）= hairpin_design_from_order
# (3, 2.5, 0.05, 20.0) **纯 KJ 链**（kgap_corrected=False：同向 c(gap) 表是同向
# 结构效应，对交替取向不适用；c_alt(gap)≈1 是预声明假设，待真机 k(gap) 图谱以
# scripts/hairpin_q_extract.hairpin_alt_kgap_gate 判读）按 hairpin 同规则舍入
# （w/arm_len/gap 4 位、τ 6 位）；arm_len × c_f0=1.0370（B2 同向 pt4 标定的 U 弯+
# 开路端等效缩短，属逐腔几何效应、与相邻取向无关——先验沿用，alt 真机复标后可改）；
# τ 走 c(τ) 修正重解（B1 单腔标定，抽头结构逐腔相同）。四项名义与 hairpin 逐位相同
# 是设计链的必然结果（唯一变量=取向），单测按链复算钉住而非拷贝。
# 选型理由（另立模板名而非改 hairpin 缺省）：① 同向 c(gap) 表/名义定版/A1-B3 标定
# 链全部绑定同向拓扑，改缺省会让既有标定与 fake 通道口径失效；② fake 派发按模板名
# 选修正链（hairpin 乘 c(gap)、hairpin_alt 纯 KJ），双模板即双口径无歧义；③ 注册
# 四件套契约现成（#247 既有键不重排：本段注册在 hairpin 之后、coupled_bpf 之前，
# 槽线族仍居字典尾）。orientation="same" 保留为 hairpin_alt 的布局选项（不进 params/
# nominal：字符串非几何量，审计扰动器只吃数值），用于同网格 A/B 对照渲染。
HAIRPIN_ALT_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（交替取向发夹线 BPF：带内回波纹波 + 带外"
                  "抑制；裁判=C13 耦合矩阵闭式 coupling_matrix_response，gap→k 纯 KJ）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["order", "w_mm", "arm_len_mm", "arm_gap_mm", "gap_mm",
               "tap_frac"],
    "topology": "交替取向发夹线带通（0dk 根修变体）：N 个 λg/2 半波谐振器折成 U 形"
                " 沿 x 并排，**奇数序谐振器上下翻转**（弯带/开路端 y 逐腔轮替），"
                " 相邻臂开路端交替 → 电/磁耦合同号叠加；相邻外臂平行耦合（缝"
                " gap_mm）；输入/输出为 50Ω 抽头馈线（板边 x=∓BOARD 至首/末谐振器"
                " 外臂，抽头位置 tap_frac 各自开路端计，末腔翻转时输出抽头自 y1 向下）",
    "param_semantics": "order=谐振器阶数 N，w_mm=谐振器/馈线宽（50Ω，skrf HJ "
                       "综合），arm_len_mm=展开中心线总长 λg/2（2·臂长+臂间距）×"
                       "c_f0（U 弯/开路端等效缩短先验 1.0370），arm_gap_mm=U 内两臂缝"
                       "（名义 3.0：k_self(3.0)=0.0115 ≪ 互耦 0.0515），gap_mm=相邻"
                       "谐振器耦合缝——**纯 KJ 口径** k=(Z0e−Z0o)/(Z0e+Z0o)，不乘同向"
                       "结构修正 c(gap)（预声明 c_alt∈[0.6,1.2]，真机 k(gap) 图谱判读"
                       "门 hairpin_alt_kgap_gate 未过前 campaign_capable=False），"
                       "tap_frac=抽头位置比例 τ=t/L_tot（各自开路端计）；可选布局"
                       "选项 orientation=alternating|same（缺省 alternating，same="
                       "同网格同向对照，不进 params）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "全部臂缘/逐腔弯带缘/开路端/两抽头缘精确入网（#198），网格配方"
                 "与 hairpin 同源（A/B 只隔离取向）",
}

HAIRPIN_ALT_NOMINAL: dict[str, Any] = {
    "order": 3,
    # 名义 = hairpin_design_from_order(3, 2.5, 0.05, 20.0) 纯 KJ 链舍入（w/arm_len/
    # gap 4 位、τ 6 位）；test_hairpin_alt_template 按链复算钉住（#252，非拷贝）
    "w_mm": 1.1117,            # inverse_width(50Ω @2.5GHz, rogers4350b h=0.508)
    # 闭式 λg/2=35.4676（εeff=2.8578 @w，HJ）× c_f0 1.0370（fake_adapter._HAIRPIN_F0_CORR
    # 先验；逐腔 U 弯+开路端效应，与取向无关）
    "arm_len_mm": 36.7799,
    "arm_gap_mm": 3.0,         # k_self(3.0)=0.0115 < 互耦 0.0515（同 hairpin A2 理由）
    # C13 N=3/RL=20dB/FBW=0.05 → k=0.051514 → KJ 反解 s=1.132829mm（不乘 c(gap)）
    "gap_mm": 1.1328,
    # Q_e=17.0689 → c(τ)=1.37437−0.75218·τ 修正重解 τ*=0.398159（闭式 0.401892）
    "tap_frac": 0.398159,
}

# 注册四件套：① docs/templates/hairpin_alt/meta.yaml；② test_template_geometry_audit
# .EXPECTED_TEMPLATES（42→43，单源）；③ fake_adapter 派发（hairpin 分支并列、纯 KJ）；
# ④ models/template_specs（_register_hairpin_alt）。同对象注册，既有键不重排（#247）。
TEMPLATE_META["hairpin_alt"] = HAIRPIN_ALT_META
TEMPLATE_NOMINAL["hairpin_alt"] = HAIRPIN_ALT_NOMINAL


def hairpin_alt_meta() -> dict[str, Any]:
    """返回 hairpin_alt 模板元数据（与 template_meta("hairpin_alt") 同构的便捷别名）。"""
    meta = dict(HAIRPIN_ALT_META)
    meta["template"] = "hairpin_alt"
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(HAIRPIN_ALT_NOMINAL)
    return meta


def _hairpin_alt_orientation(p: dict[str, Any]) -> str:
    """hairpin_alt 布局取向选项：缺省 alternating；"same" 渲染同向对照（同网格 A/B）。"""
    orientation = str(p.get("orientation", "alternating"))
    if orientation not in _HAIRPIN_ORIENTATIONS:
        raise ValueError(
            f"hairpin_alt orientation 须为 {_HAIRPIN_ORIENTATIONS}（得 {orientation!r}）")
    return orientation


def _hairpin_alt_layout(p: dict[str, Any]) -> dict[str, Any]:
    """hairpin_alt 几何单源（render/_near_points/geometry_spec 共用）。"""
    return _hairpin_layout(p, orientation=_hairpin_alt_orientation(p))


def _hairpin_alt_lines(p: dict[str, Any]) -> str:
    # 交替取向发夹线 BPF：几何与 _hairpin_lines 同源（_hairpin_layout），差异只在
    # 逐腔弯带 y（YBEND[i]）与两抽头 y（YT[0]/YT[1]）；端口/去嵌/priority 口径照抄
    # hairpin（A1 去嵌 10·NEAR+4·H_SUB，均匀馈段三探针）。
    lay = _hairpin_alt_layout(p)
    return f'''N = {lay["n"]}
ORIENTATION = {lay["orientation"]!r}     # alternating=奇数序腔翻转 / same=同向对照
WF = {lay["wf"]!r}                       # 谐振器/馈线宽（50Ω，HJ）
B = {lay["b"]!r}                         # U 内两臂中心距
LARM = {lay["l_arm"]!r}                  # 单臂长（展开 2·LARM+B=λg/2）
Y0 = {lay["y0"]!r}                       # 臂下端 y（未翻转腔的开路端）
Y1 = {lay["y1"]!r}                       # 臂上端 y（未翻转腔的弯带中心）
YOPEN = {lay["y_open"]!r}                # 各谐振器开路端 y（交替：Y0/Y1 轮替）
YBEND = {lay["y_bend"]!r}                # 各谐振器弯带中心 y（与 YOPEN 互补）
YT = {lay["y_taps"]!r}                   # [输入, 输出] 抽头 y（各自开路端计 τ·λg/2）
XS = {lay["xs"]!r}                       # 各谐振器 [左臂心, 右臂心]（m）
hairpin = CSX.AddMetal("hairpin")
for _i in range(N):
    _xl = XS[2 * _i]
    _xr = XS[2 * _i + 1]
    hairpin.AddBox((_xl - WF / 2, Y0, H_SUB),
                   (_xl + WF / 2, Y1, H_SUB), priority=10)
    hairpin.AddBox((_xr - WF / 2, Y0, H_SUB),
                   (_xr + WF / 2, Y1, H_SUB), priority=10)
    hairpin.AddBox((_xl - WF / 2, YBEND[_i] - WF / 2, H_SUB),
                   (_xr + WF / 2, YBEND[_i] + WF / 2, H_SUB), priority=10)
# 抽头馈线（T 形）：板边 x=∓BOARD → 首/末谐振器外臂中心（末腔翻转时 YT[1]≠YT[0]）
hairpin.AddBox((-BOARD, YT[0] - WF / 2, H_SUB),
               (XS[0], YT[0] + WF / 2, H_SUB), priority=10)
hairpin.AddBox((XS[-1], YT[1] - WF / 2, H_SUB),
               (BOARD, YT[1] + WF / 2, H_SUB), priority=10)
# 去嵌口径同 hairpin（WP2.3 收口 A1）：测量面 = 抽头结前 10·NEAR+4·H_SUB
_port1 = MSLPort(CSX, port_nr=1, metal_prop=hairpin,
                 start=np.array([-BOARD, YT[0] + WF / 2, H_SUB]),
                 stop=np.array([XS[0], YT[0] - WF / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(XS[0] + BOARD) - 10 * NEAR - 4 * H_SUB,
                 priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=hairpin,
                 start=np.array([BOARD, YT[1] - WF / 2, H_SUB]),
                 stop=np.array([XS[-1], YT[1] + WF / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - XS[-1]) - 10 * NEAR - 4 * H_SUB,
                 priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in hairpin.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ═══════════════════════════════════════════════════════════════════════════════
# WP2.3 Tier 1：平行耦合（边缘耦合）带通滤波器——BPF 族锚模板（增量批；
# 2026-09-14 合流轮正式注册进 TEMPLATE_META/TEMPLATE_NOMINAL，见段末"注册边界"）
# ═══════════════════════════════════════════════════════════════════════════════
# 拓扑（Pozar《Microwave Engineering》§8.6.2 平行耦合线带通，BPF 族锚——hairpin
# 为其折叠横向变体）：N 个 λg/2 半波谐振器沿 y 阶梯排列（相邻平行、y 向错位
# λg/4），N+1 个 λ/4 耦合段（馈-腔、腔-腔×(N−1)、腔-馈）；输入/输出 50Ω 馈线
# 在 y=∓BOARD 板边。两端口均在 y 边界 → 单轴 PML；底 z-min PEC 地。
#
# ── 理论核验轮（口径/来源逐条；裁判=独立来源，不自证）──
# 1) J 倒置器综合（Pozar §8.6）：J01/JN,N+1 = Z0·√(πδ/(2 g0 g1))、
#    J_j,j+1 = Z0·(πδ/2)/√(g_j g_{j+1})；Z0e = Z0(1+x+x²)、
#    Z0o = Z0(1−x+x²)，x = J/Z0。g 值走 core/matching.chebyshev_g_values
#    （RL→纹波 ε²=1/(10^(RL/10)−1)，#175 测试书写纪律）。
# 2) (Z0e, Z0o) → (w, s)：KJ 1984（本文件 coupled_microstrip_even_odd_ohm）
#    二维数值反解——内层固定 w 对 Z0e 解 s（s↑ ⇒ Z0e↓ 单调），外层对 Z0o 解 w
#    （w↑ ⇒ s*↑ ⇒ Z0o(w,s*)↑ 单调，单测钉住）。不用 Akhtarzad 闭式（hairpin
#    段同口径：弱耦合失真，分歧以数值记录）。
# 3) 长度：耦合段电长 λ/4 用 (εeff_e+εeff_o)/2；谐振器 λg/2 用全段平均 εeff；
#    开路端修正 Δl（Hammerstad 单线式，Pozar eq.4.23 口径）每开路端一个，
#    谐振器物理长 = λg/2 − Δl(端1宽) − Δl(端2宽)（等长口径）。
# 4) C13 映射互检（与 hairpin 段口径不同，两族不可混用——单测钉住）：
#    平行耦合段等效外部 Q_e = (π/2)(Z0/Z_r)/x01² → g0·g1/δ、耦合系数
#    k_j = (2/π)·x_j·(Z_r/Z0) → δ/√(g_j g_{j+1})（Z_r=√(Z0e·Z0o)，λ/2 谐振器
#    斜率 b=(π/2)Y_r 推导；hairpin 段的 k=(Z0e−Z0o)/(Z0e+Z0o) 是 U 臂口径，
#    平行耦合段该式 ≠ 等效耦合系数，实测 k_zratio/k ≈ 1+x²）。
# 5) 电路裁判 coupled_bpf_circuit_sparams：每耦合段=偶/奇模 2 端口叠加构造
#    4 端口 S（无耗/reciprocity 由构造保证，单测 S†S=I 钉住），两交叉口开路
#    端接（Γ=+1）→ 2 端口，与 50Ω 馈线 ABCD 级联。**同步 TEM 极限**
#    （synchronous_tem=True：全段 εeff=均值、λ/4 无修正）对照 C13 矩阵频响
#    coupling_matrix_response 实测带内 max|ΔS21|≈0.012dB——综合链与耦合矩阵
#    两条独立构造互证；真偶/奇模相速口径（默认）给出几何的准静态预测（微带
#    非均匀介质下带内纹波/回损退化属二阶物理，冒烟据实判读）。
#    已知口径限制（冒烟判读假设清单）：谐振器中点宽度台阶、馈线-耦合段宽度
#    台阶不连续性、开路端边缘导纳残差（Δl 仅一阶补偿）、KJ 准静态色散——
#    均不进模型，由 EM 冒烟实测其总量。
#
# ── 注册边界（#230 跨轨契约；2026-09-14 合流轮起注册已补齐）──
# 本模板最初为**附加模板**（不进注册表，docs/** 增量轨禁写）；注册四件套
# （docs/templates/coupled_bpf/meta.yaml、test_template_geometry_audit 的
# EXPECTED_TEMPLATES、fake_adapter 派发 _coupled_bpf_sparams、
# models/template_specs _register_coupled_bpf）已补齐
# ——注册动作见 COUPLED_BPF_NOMINAL 之后的 TEMPLATE_META/TEMPLATE_NOMINAL
# 赋值块（同对象注册，渲染段零改动）。

COUPLED_BPF_NOMINAL: dict[str, Any] = {
    "order": 3,
    # 50Ω 馈线宽 = round(live inverse_width(50,2.5,rogers4350b),4)=1.1117
    # （2026-09-15 对齐：旧 1.1134 系历史快照，现行 HJ 正向下 Z0=49.95Ω 非
    # 50Ω 精算，铁律 1c 线宽一律 skrf HJ 精算；hairpin 家族同名常数 1.1134
    # 的家族性对齐不属本模板段）
    "w_feed_mm": 1.1117,
    # C13 N=3/RL=20dB/FBW=0.05 → J/Z0=[0.30336,0.08092,0.08092,0.30336] →
    # (Z0e,Z0o)=[(69.769,39.433),(54.373,46.282)] → KJ 二维反解（4 位舍入）
    "widths_mm": [0.8952, 1.0956, 1.0956, 0.8952],
    "gaps_mm": [0.1286, 0.7794, 0.7794, 0.1286],
    # λg/2(εeff_gm=2.7862)=35.921mm − Δl(0.8952)=0.2017 − Δl(1.0956)=0.2082
    # （=谐振器 1 的 r_1；内谐振器按各自端宽逐端 Δl 修正，见
    # _coupled_bpf_section_lengths_mm——res2 修量 −6.465µm/−182ppm）
    "res_len_mm": 35.5107,
    # BOARD=60mm − (N+1)/2·Lc（等长阶梯阵列 y 居中 ⇒ 两馈等长）
    "feed_len_mm": 24.4893,
}

COUPLED_BPF_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（平行耦合 BPF：带内回波纹波 + 带外"
                  "抑制；裁判=电路级联 coupled_bpf_circuit_sparams，同步 TEM"
                  " 极限对照 C13 coupling_matrix_response 互证）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["order", "w_feed_mm", "widths_mm", "gaps_mm", "res_len_mm",
               "feed_len_mm"],
    "topology": "平行耦合（边缘耦合）带通（WP2.3 Tier1 BPF 族锚，Pozar §8.6.2）："
                "N 个 λg/2 半波谐振器沿 y 阶梯排列（相邻平行、y 向错位 λg/4），"
                "N+1 个 λ/4 耦合段（馈-腔、腔-腔×(N−1)、腔-馈）；输入/输出 50Ω"
                " 馈线在 y=∓BOARD 板边（单轴 PML）",
    "param_semantics": "order=谐振器阶数 N（决定 widths_mm/gaps_mm 列表长度"
                       " N+1，单独改 order 而不改列表=非法，_coupled_bpf_layout"
                       " 显式报错），w_feed_mm=50Ω 馈线宽（skrf HJ 精算 live 值；"
                       "仅进几何，电路裁判馈线=理想 50Ω 线），widths_mm[j]=第 j 个"
                       " λ/4 耦合段线宽（j=0 输入馈-腔 … j=N 腔-输出馈，KJ 二维"
                       "反解），gaps_mm[j]=同段耦合缝（边到边），res_len_mm="
                       "谐振器 1 物理长（λg/2 − Δl(w0) − Δl(w1)），其余谐振器长"
                       "按各自端宽逐端 Δl 修正（耦合段长逐段 L_j 由"
                       " _coupled_bpf_section_lengths_mm 同源派生；res2 修量"
                       " −6.465µm/−182ppm），feed_len_mm=输入 50Ω 馈线长（阵列"
                       " y 居中 ⇒ 两馈等长）"
                       "——列表参数 fake/openEMS 两通道同索引同语义（#154）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "全部盒缘（馈/耦合段/谐振器台阶）精确入网（#198 精确入网）",
}

# ── 注册（合流轮）：coupled_bpf 升格为正式注册模板 ──
# 四处同步：① docs/templates/coupled_bpf/meta.yaml；②
# test_template_geometry_audit.EXPECTED_TEMPLATES（18→25，含 antenna2 六件）；
# ③ fake_adapter 派发分支（_coupled_bpf_sparams，电路裁判同源闭式）；④
# models/template_specs（_register_coupled_bpf）。同对象注册（非拷贝）钉死
# 单一事实源，防双份字典漂移；渲染段零改动。
TEMPLATE_META["coupled_bpf"] = COUPLED_BPF_META
TEMPLATE_NOMINAL["coupled_bpf"] = COUPLED_BPF_NOMINAL


def coupled_bpf_meta() -> dict[str, Any]:
    """返回 coupled_bpf 模板元数据（与 template_meta("coupled_bpf") 同构的便捷别名）。"""
    meta = dict(COUPLED_BPF_META)
    meta["template"] = "coupled_bpf"
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = {k: (list(v) if isinstance(v, list) else v)
                              for k, v in COUPLED_BPF_NOMINAL.items()}
    return meta


def _open_end_delta_mm(w_mm: float, freq_ghz: float,
                       er: float = 3.66, h_mm: float = 0.508) -> float:
    """微带开路端等效长度增量 Δl（Hammerstad 单线闭式，Pozar eq.4.23 口径）。

    Δl/h = 0.412·(εeff+0.3)(w/h+0.264) / [(εeff−0.258)(w/h+0.8)]，
    εeff 取 skrf HJ 正向（同线宽口径）。
    """
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="coupled_bpf", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    _, ere = forward_z0(float(w_mm), float(freq_ghz), stackup)
    u = float(w_mm) / float(h_mm)
    return (float(h_mm) * 0.412 * (ere + 0.3) * (u + 0.264)
            / ((ere - 0.258) * (u + 0.8)))


def _coupled_bpf_section_lengths_mm(
    widths_mm: Any, res_len_mm: float, f0_ghz: float = 2.5,
    er: float = 3.66, h_mm: float = 0.508,
) -> list[float]:
    """逐端 Δl 修正的耦合段物理长 [L_0..L_N]（mm）——布局/电路裁判/fake 三处
    同源派生（防双源漂移，#154 同索引语义）。

    谐振器 i（1..N）跨耦合段 i−1/i 两段，两开路端宽各为 w[i−1]/w[i]，物理长须
    r_i = λg/2 − Δl(w[i−1]) − Δl(w[i]) = res_len + Δl(w0) + Δl(w1)
    − Δl(w[i−1]) − Δl(w[i])（res_len 即 r_1 的声明值；Δl=_open_end_delta_mm，
    Pozar eq.4.23 口径）。阶梯方程 L_{i−1}+L_i=r_i（N 式、N+1 元）规范自由度取
    L_0=L_N（镜像口径，奇 N 直接定解；偶 N 该式退化——L_0=L_N ⟺ f_N=0 是对 r
    的约束而非对 t 的，改钉中心段 L_{N/2}=res_len/2；偶阶切比雪夫 g_{N+1}≠1
    输入/输出段本就不对称，逐端修正后段长如实不对称）。名义 N=3 实测
    L=[17.7586,17.7521,17.7521,17.7586]mm、ΣL=2·res_len ⇒ feed_len 逐位不变
    （N≠1,3 时 ΣL 与 (N+1)·res_len/2 差 µm 级=逐端 Δl 之和）；
    中谐振器修量 = Δl(w1)−Δl(w0) = −6.465µm（−182ppm）。
    """
    w = [float(v) for v in widths_mm]
    n = len(w) - 1
    if n < 1:
        raise ValueError(f"widths_mm 长度须 ≥2（order+1），得 {len(w)}")
    if not float(res_len_mm) > 0.0:
        raise ValueError(f"res_len_mm={res_len_mm} 须 >0")
    dl = [_open_end_delta_mm(wj, float(f0_ghz), float(er), float(h_mm))
          for wj in w]
    r = [float(res_len_mm) + dl[0] + dl[1] - dl[i - 1] - dl[i]
         for i in range(1, n + 1)]
    # 递解 L_j = f_j + (−1)^j·t（t=L_0 待规范定）
    f = [0.0] * (n + 1)
    for j in range(1, n + 1):
        f[j] = r[j - 1] - f[j - 1]
    if n % 2 == 1:
        t = f[n] / 2.0                              # 规范 L_0 = L_N
    else:
        half = n // 2
        t = ((-1.0) ** half) * (float(res_len_mm) / 2.0 - f[half])
    lens = [f[j] + (-1.0) ** j * t for j in range(n + 1)]
    if any(v <= 0.0 for v in lens):
        raise ValueError(f"逐端 Δl 修正后耦合段长非正：{lens}")
    return lens


def coupled_bpf_width_gap_from_zee_zoo(
    zee_ohm: float, zoo_ohm: float, freq_ghz: float = 2.5,
    er: float = 3.66, h_mm: float = 0.508,
) -> tuple[float, float]:
    """(Z0e, Z0o) → (w_mm, s_mm)：KJ 闭式二维数值反解（嵌套 brentq）。

    内层：固定 w，s↑ ⇒ Z0e 单调下降（s→∞ 退化单线 Z0_single(w)），对 Z0e 解 s；
    外层：w↑ ⇒ 内层 s*↑ ⇒ Z0o(w,s*) 单调上升（从 Z0o(w,0+)≈小值 到
    Z0_single(w)），对 Z0o 解 w。单调性为 brentq 前置条件，单测钉住。
    """
    from scipy.optimize import brentq

    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    ze_t = float(zee_ohm)
    zo_t = float(zoo_ohm)
    if not ze_t > zo_t > 0.0:
        raise ValueError(f"须 Z0e > Z0o > 0，得 ({ze_t}, {zo_t})")
    stackup = Stackup(name="coupled_bpf", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    # w 下界：单线阻抗须 < Z0e（耦合只能抬升 Z0e）；取 0.999 留耦合余量
    w_lo = float(inverse_width(ze_t * 0.999, float(freq_ghz), stackup)[0])
    w_hi = w_lo + 8.0
    s_lo, s_hi = 0.02, 60.0

    def _ze_residual(w_mm: float, s_mm: float) -> float:
        single = forward_z0(w_mm, float(freq_ghz), stackup)
        return (coupled_microstrip_even_odd_ohm(
            w_mm, s_mm, freq_ghz, er, h_mm, single=single)[0] - ze_t)

    def _h(w_mm: float) -> float:
        """外层残差 Z0o(w, s*(w)) − Z0o_t（w ∈ [w_lo, w_zemax] 内恒可达）。"""

        def _f(s_mm: float) -> float:
            return _ze_residual(w_mm, s_mm)

        f_lo = _f(s_lo)
        if f_lo < 0.0:          # 最大耦合也达不到 Z0e（不发生于可达域内）
            return float("nan")
        s_mm = float(brentq(_f, s_lo, s_hi, xtol=1e-9)) if f_lo > 0.0 else s_lo
        single = forward_z0(w_mm, float(freq_ghz), stackup)
        return (coupled_microstrip_even_odd_ohm(
            w_mm, s_mm, freq_ghz, er, h_mm, single=single)[1] - zo_t)

    # 可达上界 w_zemax：Z0e(w, s_lo) = Z0e_t 的宽度（Z0e 随 w 单调降，二分）
    lo_b, hi_b = w_lo, w_hi
    for _ in range(60):
        mid = 0.5 * (lo_b + hi_b)
        if _ze_residual(mid, s_lo) > 0.0:
            lo_b = mid
        else:
            hi_b = mid
    w_zemax = 0.5 * (lo_b + hi_b)
    # 外层残差 h：h(w_lo) = Z0o(w_lo, s→s_hi)−Z0o_t ≈ Z_single−Z0o_t > 0、
    # h(w_zemax) = Z0o(w_zemax, s_lo)−Z0o_t < 0（紧耦合 Z0o 极低）——单调降。
    if not _h(w_lo) > 0.0:
        raise ValueError(
            f"(Z0e,Z0o)=({ze_t:.3f},{zo_t:.3f})Ω 耦合过弱无解"
            f"（w 下界处 Z0o 已 ≤ 目标）")
    lo, hi = w_lo, w_zemax
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if _h(mid) > 0.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-11:
            break
    w_root = 0.5 * (lo + hi)
    single = forward_z0(w_root, float(freq_ghz), stackup)

    def _f2(s_mm: float) -> float:
        return (coupled_microstrip_even_odd_ohm(
            w_root, s_mm, freq_ghz, er, h_mm, single=single)[0] - ze_t)

    s_root = (float(brentq(_f2, s_lo, s_hi, xtol=1e-9))
              if _f2(s_lo) > 0.0 else s_lo)
    return w_root, s_root


def coupled_bpf_design_from_order(
    order: int, f0_ghz: float = 2.5, fbw: float = 0.05, rl_db: float = 20.0,
    *, er: float = 3.66, h_mm: float = 0.508,
    with_section_lengths: bool = False,
) -> dict[str, Any]:
    """平行耦合 BPF 综合链：切比雪夫 g 值 → J 倒置器 → (Z0e,Z0o) → (w,s) → 几何。

    确定性映射（数值只在内核：g 值在 core/matching，矩阵综合在 core/synthesis，
    本函数只做几何映射，口径见本文件 WP2.3 平行耦合 BPF 段）。返回 dict：
    {"order", "f0_ghz", "fbw", "rl_db", "g_list", "j_norm"(J/Z0),
     "sections": [{zee_ohm, zoo_ohm, w_mm, s_mm, ere_e, ere_o, ere_avg} × (N+1)],
     "ere_gm", "res_len_mm", "lc_mm", "feed_len_mm", "w_feed_mm",
     "k_circuit", "qe_circuit", "coupling_matrix", "notes"}
    with_section_lengths=True 时另带可选键 "section_len_mm"（逐端 Δl 修正的
    耦合段长 [L_0..L_N]，_coupled_bpf_section_lengths_mm 派生；电路裁判
    coupled_bpf_circuit_sparams 见键即逐段取长，缺省回退均匀 lc_mm）。
    缺省不带：service/topology_service.run_fine_campaign 的 realize() 以
    {**base, "lc_mm": res_len/2} 展开综合 design 后再改 res_len/宽缝——常带该键
    会把过期段长带进战役裁判（初值点实测 RL 12.931→13.113dB、缩放点段长
    与 res_len 失配），故锚零回归 by construction 要求该键 opt-in。
    feed_len_mm=60 − ΣL_j/2（阵列 y 居中 ⇒ 两馈等长；名义 N=3 ΣL=2·res_len
    与原均匀式逐位相同）。
    """
    import numpy as _np

    from rfauto.core.matching import chebyshev_g_values
    from rfauto.core.synthesis import (
        Stackup,
        inverse_width,
        synthesize_bpf_model,
    )

    n = int(order)
    if n < 1:
        raise ValueError(f"order={order} 须 ≥1")
    if not 0.0 < float(fbw) <= 1.0:
        raise ValueError(f"fbw={fbw} 须在 (0,1]")
    if float(rl_db) <= 0.0:
        raise ValueError(f"rl_db={rl_db} 须 >0")
    stackup = Stackup(name="coupled_bpf", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    ripple_db = 10.0 * math.log10(1.0 + 1.0 / (10.0 ** (float(rl_db) / 10.0)
                                                - 1.0))
    g = chebyshev_g_values(n, ripple_db)
    # J 倒置器归一值 x_j = J_j/Z0（Pozar §8.6）
    x = [math.sqrt(math.pi * float(fbw) / (2.0 * g[0] * g[1]))]
    for j in range(1, n):
        x.append((math.pi * float(fbw) / 2.0) / math.sqrt(g[j] * g[j + 1]))
    x.append(math.sqrt(math.pi * float(fbw) / (2.0 * g[n] * g[n + 1])))
    sections: list[dict[str, Any]] = []
    for xj in x:
        zee = 50.0 * (1.0 + xj + xj * xj)
        zoo = 50.0 * (1.0 - xj + xj * xj)
        w_mm, s_mm = coupled_bpf_width_gap_from_zee_zoo(
            zee, zoo, float(f0_ghz), er, h_mm)
        ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
            w_mm, s_mm, float(f0_ghz), er, h_mm)
        sections.append({"zee_ohm": ze, "zoo_ohm": zo, "w_mm": w_mm,
                         "s_mm": s_mm, "ere_e": ere_e, "ere_o": ere_o,
                         "ere_avg": 0.5 * (ere_e + ere_o), "j_norm": xj})
    ere_gm = float(_np.mean([sec["ere_avg"] for sec in sections]))
    # 谐振器 1 物理长 = λg/2(εeff_gm) − 开路端修正（两端宽不同取各自 Δl）；
    # 内谐振器按各自端宽逐端修正 → 逐段耦合段长 L_j（同源 helper）
    lg_half_mm = 299.792458 / (2.0 * float(f0_ghz) * math.sqrt(ere_gm))
    w_feed = float(inverse_width(50.0, float(f0_ghz), stackup)[0])
    dl_end = _open_end_delta_mm(sections[0]["w_mm"], float(f0_ghz), er, h_mm)
    dl_mid = _open_end_delta_mm(sections[1]["w_mm"], float(f0_ghz), er, h_mm) \
        if n >= 2 else dl_end
    res_len_mm = lg_half_mm - dl_end - dl_mid
    lc_mm = res_len_mm / 2.0                      # 均匀参考（裁判缺省回退）
    section_len_mm = _coupled_bpf_section_lengths_mm(
        [sec["w_mm"] for sec in sections], res_len_mm, float(f0_ghz), er, h_mm)
    sum_len_mm = sum(section_len_mm)
    feed_len_mm = 60.0 - sum_len_mm / 2.0         # 阵列 y 居中 ⇒ 两馈等长
    if feed_len_mm <= 5.0:
        raise ValueError(
            f"feed_len={feed_len_mm:.2f}mm ≤5mm：order/fbw 下阵列超出 60mm 板")
    # C13 矩阵（裁判频响用）+ 等效电气量互检数（推导见段首口径 4）
    synth = synthesize_bpf_model(order=n, f0_ghz=float(f0_ghz), fbw=float(fbw),
                                 rl_db=float(rl_db), topology="folded")
    if not synth.get("ok"):
        raise ValueError(f"C13 综合失败: {synth.get('errors')}")
    k_circuit = [(2.0 / math.pi) * sec["j_norm"]
                 * math.sqrt(sec["zee_ohm"] * sec["zoo_ohm"]) / 50.0
                 for sec in sections]
    qe_circuit = ((math.pi / 2.0) * (50.0 / math.sqrt(
        sections[0]["zee_ohm"] * sections[0]["zoo_ohm"]))
        / sections[0]["j_norm"] ** 2)
    notes = [
        f"切比雪夫 N={n}（纹波 {ripple_db:.4f}dB）g={_fmt_list(g, 4)}",
        f"J/Z0={_fmt_list(x, 5)} → (Z0e,Z0o)="
        + ", ".join(f"({s['zee_ohm']:.3f},{s['zoo_ohm']:.3f})"
                    for s in sections),
        "KJ 二维反解 (w,s)=" + ", ".join(
            f"({s['w_mm']:.4f},{s['s_mm']:.4f})mm" for s in sections),
        f"εeff_avg={_fmt_list([s['ere_avg'] for s in sections], 4)}，"
        f"εeff_gm={ere_gm:.4f}",
        f"λg/2={lg_half_mm:.3f}mm − Δl({sections[0]['w_mm']:.4f})={dl_end:.4f}"
        f" − Δl({sections[1]['w_mm'] if n >= 2 else sections[0]['w_mm']:.4f})"
        f"={dl_mid:.4f} → res_len={res_len_mm:.4f}mm（谐振器 1），"
        f"lc={lc_mm:.4f}mm（均匀参考），feed={feed_len_mm:.4f}mm",
        "逐端 Δl 口径：耦合段长 L_j=" + _fmt_list(section_len_mm, 4)
        + f"mm（ΣL={sum_len_mm:.4f}mm，规范 L_0=L_N；各谐振器"
        " r_i=λg/2−Δl(w[i−1])−Δl(w[i])，宽度台阶/边缘导纳残差不进模型）",
        f"等效电气量（互检）：Q_e={qe_circuit:.4f}（g0·g1/δ="
        f"{g[0] * g[1] / float(fbw):.4f}），k="
        + _fmt_list(k_circuit[1:n], 5) + "（δ/√(g_j g_j+1)="
        + _fmt_list([float(fbw) / math.sqrt(g[j] * g[j + 1])
                     for j in range(1, n)], 5) + "）",
        "口径与假设清单见 openems_templates 文末 WP2.3 平行耦合 BPF 段",
    ]
    out: dict[str, Any] = {
        "order": n, "f0_ghz": float(f0_ghz), "fbw": float(fbw),
        "rl_db": float(rl_db), "er": float(er), "h_mm": float(h_mm),
        "g_list": g, "j_norm": x, "sections": sections,
        "ere_gm": ere_gm, "lg_half_mm": lg_half_mm,
        "res_len_mm": res_len_mm, "lc_mm": lc_mm,
        "feed_len_mm": feed_len_mm, "w_feed_mm": w_feed,
        "k_circuit": k_circuit, "qe_circuit": qe_circuit,
        "coupling_matrix": synth["coupling_matrix"], "notes": notes}
    if with_section_lengths:
        out["section_len_mm"] = section_len_mm
    return out


def _coupled_bpf_layout(p: dict[str, Any]) -> dict[str, Any]:
    """coupled_bpf 几何统一计算（米）——render/_near_points/geometry_spec 共用。

    参数与 COUPLED_BPF_NOMINAL 一致（widths_mm/gaps_mm 长度须 order+1）。
    """
    nom = COUPLED_BPF_NOMINAL
    n = int(p.get("order", nom["order"]))
    if n < 1:
        raise ValueError(f"order={n} 须 ≥1")
    widths_raw = p.get("widths_mm")
    gaps_raw = p.get("gaps_mm")
    if widths_raw is None:
        widths_raw = nom["widths_mm"]
        if n != nom["order"]:
            raise ValueError(
                f"order={n} 须随 widths_mm/gaps_mm 列表（默认表仅 order="
                f"{nom['order']}）")
    if gaps_raw is None:
        gaps_raw = nom["gaps_mm"]
        if n != nom["order"]:
            raise ValueError(
                f"order={n} 须随 widths_mm/gaps_mm 列表（默认表仅 order="
                f"{nom['order']}）")
    widths = [float(v) * 1e-3 for v in widths_raw]
    gaps = [float(v) * 1e-3 for v in gaps_raw]
    if len(widths) != n + 1 or len(gaps) != n + 1:
        raise ValueError(f"widths_mm/gaps_mm 长度须为 order+1={n + 1}")
    if any(v <= 0.0 for v in (*widths, *gaps)):
        raise ValueError("widths_mm/gaps_mm 须 >0")
    w_feed = float(p.get("w_feed_mm", nom["w_feed_mm"])) * 1e-3
    res_len_mm_v = float(p.get("res_len_mm", nom["res_len_mm"]))
    res_len = res_len_mm_v * 1e-3
    lc = res_len / 2.0                  # 均匀参考（裁判缺省回退/守卫锚，非几何）
    feed_len = float(p.get("feed_len_mm", nom["feed_len_mm"])) * 1e-3
    board = 0.060                       # 渲染 harness 固定板边（BOARD=60e-3）
    if w_feed <= 0.0 or res_len <= 0.0 or not 0.0 < feed_len < board:
        raise ValueError("w_feed/res_len/feed_len 须 >0 且 feed_len < 60mm")
    # 逐端 Δl 修正的耦合段长 L_j（mm→m；与电路裁判/fake 同源 helper，Δl 按
    # 模板 f0=2.5GHz/默认叠层口径评估）
    lens = [v * 1e-3 for v in _coupled_bpf_section_lengths_mm(
        [float(v) for v in widths_raw], res_len_mm_v)]
    y1 = feed_len - board               # 输入耦合段底 = 谐振器 1 底端
    y_edges = [y1]
    for v in lens:
        y_edges.append(y_edges[-1] + v)
    feed_out = board - y_edges[-1]
    if feed_out <= 0.0:
        raise ValueError(
            f"feed_len={feed_len * 1e3:.2f}mm 过大：输出馈线余量"
            f" {feed_out * 1e3:.2f}mm ≤0（阵列超出板）")
    # 线心位置：section j 耦合 line j / j+1，缝 s_j 为边到边 ⇒ 心距 w_j+s_j
    xs = [0.0]
    for j in range(n + 1):
        xs.append(xs[-1] + widths[j] + gaps[j])
    lw = ([max(w_feed, widths[0])]
          + [max(widths[i - 1], widths[i]) for i in range(1, n + 1)]
          + [max(w_feed, widths[n])])
    shift = -(xs[0] - lw[0] / 2.0 + xs[-1] + lw[-1] / 2.0) / 2.0
    xs = [v + shift for v in xs]
    # 盒清单（input 50Ω / input 耦合段 / 谐振器上下段 ×N / output 耦合段 /
    # output 50Ω）；全部 y 边落在累积栅格 y_edges[k]=y1+Σ_{j<k} L_j 上
    # （谐振器 i 跨 y_edges[i−1]..y_edges[i+1]，物理长 L_{i−1}+L_i=r_i）
    boxes: list[tuple[float, float, float, float]] = []
    box_names: list[str] = []
    boxes.append((xs[0] - w_feed / 2.0, -board, xs[0] + w_feed / 2.0, y1))
    box_names.append("feed_in_50")
    boxes.append((xs[0] - widths[0] / 2.0, y1, xs[0] + widths[0] / 2.0,
                  y_edges[1]))
    box_names.append("sec0_coupled")
    for i in range(1, n + 1):
        boxes.append((xs[i] - widths[i - 1] / 2.0, y_edges[i - 1],
                      xs[i] + widths[i - 1] / 2.0, y_edges[i]))
        box_names.append(f"res{i}_lower")
        boxes.append((xs[i] - widths[i] / 2.0, y_edges[i],
                      xs[i] + widths[i] / 2.0, y_edges[i + 1]))
        box_names.append(f"res{i}_upper")
    boxes.append((xs[n + 1] - widths[n] / 2.0, y_edges[n],
                  xs[n + 1] + widths[n] / 2.0, y_edges[n + 1]))
    box_names.append(f"sec{n}_coupled")
    boxes.append((xs[n + 1] - w_feed / 2.0, y_edges[n + 1],
                  xs[n + 1] + w_feed / 2.0, board))
    box_names.append("feed_out_50")
    return {"n": n, "widths": widths, "gaps": gaps, "w_feed": w_feed,
            "res_len": res_len, "lc": lc, "lens": lens, "y_edges": y_edges,
            "feed_len": feed_len, "feed_out": feed_out, "board": board,
            "y1": y1, "xs": xs, "boxes": boxes, "box_names": box_names}


def _coupled_bpf_lines(p: dict[str, Any]) -> str:
    # 平行耦合 BPF（WP2.3 Tier1 附加模板）：N 个 λg/2 谐振器沿 y 阶梯排列，
    # N+1 个 λ/4 平行耦合段；50Ω 馈线自 y=∓BOARD 板边引入，输入/输出耦合段
    # 宽度取各自 (w,s)。几何由 _coupled_bpf_layout 统一计算后以字面清单落脚本。
    lay = _coupled_bpf_layout(p)
    x0 = lay["xs"][0]
    xn = lay["xs"][-1]
    wf = lay["w_feed"]
    y_feed_end_in = lay["y1"]
    y_feed_end_out = lay["y_edges"][-1]   # 累积栅格末端（逐端 Δl 修正后）
    return f'''N = {lay["n"]}
BOXES = {lay["boxes"]!r}                 # [(x0,y0,x1,y1)]（m，layout 单一事实源）
filt = CSX.AddMetal("coupled_bpf")
for _b in BOXES:
    filt.AddBox((_b[0], _b[1], H_SUB), (_b[2], _b[3], H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=filt,
                 start=np.array([{(x0 + wf / 2.0)!r}, -BOARD, H_SUB]),
                 stop=np.array([{(x0 - wf / 2.0)!r}, {y_feed_end_in!r}, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=({y_feed_end_in!r} + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=filt,
                 start=np.array([{(xn - wf / 2.0)!r}, BOARD, H_SUB]),
                 stop=np.array([{(xn + wf / 2.0)!r}, {y_feed_end_out!r}, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - {y_feed_end_out!r}) / 3, priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in filt.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _tl_two_port_s(zc_ohm: float, theta_rad: float,
                   z_ref: float = 50.0) -> np.ndarray:
    """均匀无耗线 2 端口 S（端口参考 z_ref；经 ABCD 精确转换，支持 Zc≠Zref）。"""
    import numpy as _np

    c = math.cos(float(theta_rad))
    s = math.sin(float(theta_rad))
    zc = float(zc_ohm)
    zr = float(z_ref)
    den = c + 1j * zc * s / zr + 1j * s * zr / zc + c
    return _np.array([[(c + 1j * zc * s / zr - 1j * s * zr / zc - c) / den,
                       2.0 / den],
                      [2.0 / den,
                       (-c + 1j * zc * s / zr - 1j * s * zr / zc + c) / den]])


def _coupled_section_s4(zee_ohm: float, the_even: float, zoo_ohm: float,
                        the_odd: float, z_ref: float = 50.0) -> np.ndarray:
    """对称耦合线段 4 端口 S（偶/奇模 2 端口叠加构造；端口 1/2=A 近/远、
    3/4=B 近/远）。构造恒满足无耗（S†S=I）与互易（S=Sᵀ），单测钉住。"""
    import numpy as _np

    se = _tl_two_port_s(zee_ohm, the_even, z_ref)
    so = _tl_two_port_s(zoo_ohm, the_odd, z_ref)
    s4 = _np.zeros((4, 4), dtype=complex)
    s4[0, 0] = s4[1, 1] = s4[2, 2] = s4[3, 3] = (se[0, 0] + so[0, 0]) / 2.0
    s4[0, 1] = s4[1, 0] = s4[2, 3] = s4[3, 2] = (se[0, 1] + so[0, 1]) / 2.0
    s4[0, 2] = s4[2, 0] = s4[1, 3] = s4[3, 1] = (se[0, 0] - so[0, 0]) / 2.0
    s4[0, 3] = s4[3, 0] = s4[1, 2] = s4[2, 1] = (se[0, 1] - so[0, 1]) / 2.0
    return s4


def _s4_reduce_cross_opens(s4: np.ndarray,
                           ports: tuple[int, int]) -> np.ndarray:
    """4 端口 S 的两个指定端口以开路（Γ=+1）同时端接后压缩为 2 端口。

    波变量代数：a_open = (I − S_pp)⁻¹·S_pk·a_keep（Γ=1 ⇒ a=b）。
    """
    import numpy as _np

    keep = [q for q in range(4) if q not in ports]
    m = s4[_np.ix_(ports, ports)]
    rhs = s4[_np.ix_(ports, keep)]
    a_open = _np.linalg.solve(_np.eye(2, dtype=complex) - m, rhs)
    return (s4[_np.ix_(keep, keep)]
            + s4[_np.ix_(keep, ports)] @ a_open)


def _s2_to_abcd(s2: np.ndarray, z_ref: float = 50.0) -> np.ndarray:
    import numpy as _np

    a_, b_, c_, d_ = s2[0, 0], s2[0, 1], s2[1, 0], s2[1, 1]
    den = 2.0 * c_
    return _np.array([
        [(1 + a_) * (1 - d_) + b_ * c_,
         z_ref * ((1 + a_) * (1 + d_) - b_ * c_)],
        [((1 - a_) * (1 - d_) - b_ * c_) / z_ref,
         (1 - a_) * (1 + d_) + b_ * c_],
    ]) / den


def _abcd_line(zc_ohm: float, theta_rad: float) -> np.ndarray:
    import numpy as _np

    c = math.cos(float(theta_rad))
    s = math.sin(float(theta_rad))
    zc = float(zc_ohm)
    return _np.array([[c, 1j * zc * s], [1j * s / zc, c]])


def coupled_bpf_circuit_sparams(
    freq_ghz: Any, design: dict[str, Any], *, synchronous_tem: bool = False,
    z_ref: float = 50.0,
) -> np.ndarray:
    """平行耦合 BPF 电路裁判：耦合段级联的精确准静态频响（(n,2,2) 复数）。

    链路 = 50Ω 馈线 — [耦合段 4 端口（两交叉口开路端接）]×(N+1) — 50Ω 馈线。
    每段偶/奇模各自取 KJ εeff_e/εeff_o 相位（真非均匀介质口径）；宽度台阶、
    开路端边缘导纳残差不进模型（假设清单见段首）。

    design 可带可选键 "section_len_mm"（逐端 Δl 修正的耦合段物理长
    [L_0..L_N]mm，_coupled_bpf_section_lengths_mm 派生）——见键即逐段取长；
    缺省（或 None）回退均匀 lc=design["lc_mm"]。锚零契约：service/
    topology_service.run_fine_campaign.realize() 以均匀 lc 构造 design（无该
    键）逐字节回退，test_topology_service 钉死数字不受本键影响。

    synchronous_tem=True：同步 TEM 极限（全段 εeff=εeff_gm、段长=无修正
    λ/4，**忽略 section_len_mm**）——综合方程在该极限下精确成立，频响应与
    C13 矩阵频响一致（实测 max|ΔS21|≈0.012dB），用作综合链↔耦合矩阵互证
    （单测）。
    """
    import numpy as _np

    freqs = _np.atleast_1d(_np.asarray(freq_ghz, dtype=float))
    f0 = float(design["f0_ghz"])
    feed_len_m = float(design["feed_len_mm"]) * 1e-3
    sec_lens_m: list[float] | None = None
    if synchronous_tem:
        ere_gm = float(design["ere_gm"])
        lc_m = 299.792458 / (4.0 * f0 * math.sqrt(ere_gm)) * 1e-3
        mode_eres = [(ere_gm, ere_gm)] * (int(design["order"]) + 1)
    else:
        raw_lens = design.get("section_len_mm")
        if raw_lens is not None:
            sec_lens_m = [float(v) * 1e-3 for v in raw_lens]
            if len(sec_lens_m) != int(design["order"]) + 1:
                raise ValueError(
                    f"section_len_mm 长度须为 order+1="
                    f"{int(design['order']) + 1}，得 {len(sec_lens_m)}")
            if any(v <= 0.0 for v in sec_lens_m):
                raise ValueError("section_len_mm 须 >0")
        else:
            lc_m = float(design["lc_mm"]) * 1e-3
        mode_eres = [(sec["ere_e"], sec["ere_o"]) for sec in design["sections"]]
    out = _np.zeros((len(freqs), 2, 2), dtype=complex)
    for k, f_ghz in enumerate(freqs):
        ph = 2.0 * math.pi * float(f_ghz) * 1e9 / 299792458.0
        t_total = _abcd_line(z_ref, ph * feed_len_m)
        for j, sec in enumerate(design["sections"]):
            ere_e, ere_o = mode_eres[j]
            len_m = sec_lens_m[j] if sec_lens_m is not None else lc_m
            s4 = _coupled_section_s4(
                sec["zee_ohm"], ph * len_m * math.sqrt(ere_e),
                sec["zoo_ohm"], ph * len_m * math.sqrt(ere_o), z_ref)
            # 交叉口开路端接（A 远端 + B 近端 = 端口 2/3，0 基索引 1/2）
            s2 = _s4_reduce_cross_opens(s4, (1, 2))
            t_total = t_total @ _s2_to_abcd(s2, z_ref)
        t_total = t_total @ _abcd_line(z_ref, ph * feed_len_m)
        a_, b_, c_, d_ = (t_total[0, 0], t_total[0, 1], t_total[1, 0],
                          t_total[1, 1])
        # ABCD→S（Pozar Table 4.2）：S22=(−A+B/Z0−C·Z0+D)/Δ——A 前为负号
        # （曾误写 +a_ 致镜像对称链 S11≠S22，#212 电路裁判红）。
        den = a_ + b_ / z_ref + c_ * z_ref + d_
        out[k] = [[(a_ + b_ / z_ref - c_ * z_ref - d_) / den, 2.0 / den],
                  [2.0 * (a_ * d_ - b_ * c_) / den,
                   (d_ + b_ / z_ref - c_ * z_ref - a_) / den]]
    return out


# ─── WP2.5 Tier 2 过渡结构（2026-09-16 wp25-sma-launcher-rootcause 正式注册）────
# msl_cpw：微带↔共面波导（接地 CPWG）过渡；sma_launcher：SMA 边缘弹射
# （end-launch 同轴↔微带，夹具口径，port1=同轴截面集总桥——CoaxialPort 真机
# 判废见 _sma_launcher_lines 注）。MSL↔slotline（Marchand）随 openEMS
# slotline 端口原语缺失阻塞（方案 C5 行，勿烧）。
#
# 注册四件套（文末 TEMPLATE_META/TEMPLATE_NOMINAL 同对象入表 + docs/templates/
# <t>/meta.yaml + test_template_geometry_audit.EXPECTED_TEMPLATES + fake_adapter
# 派发分支 + models/template_specs），钉在 test_msl_cpw_template /
# test_sma_launcher_template 的 test_registered_*。
#
# 锚判据口径（Tier 2 无谐振，wstep/via 族同型）：
# - msl_cpw：双端口 β 金标准（port1→HJ εeff、port2→CPWG 共形映射闭式）+
#   skrf 两段理想 TL 级联裁判（渐变/地缘/过孔栅栏寄生=引擎-理想偏差）。
#   真机 PASS 留档 runs/wp25_tier2_smoke/pt1_msl_cpw3（|S11|@2.5G −20.0dB、
#   β +0.37%/−1.04%，1076s@0.4mm）——几何冻结勿动。
# - sma_launcher：port2 β→HJ（port1 集总桥无 β 属性）；|S11| 文献曲线门
#   （edge-launch SMA 带内回损常规 15-20dB、保守地板 -10dB，方案行口径
#   "验收靠文献曲线"；docs/rf_template_references.md SMA 节）。

_MSL_CPW_50OHM_W_MM = 1.1134   # 50Ω 微带（HJ 精算 1.113400，同 hairpin 口径）
_SMA_RI_MM = 0.635             # SMA 中心针半径（Ø1.27mm 标准针，IEC 61169-15）
_SMA_ER_FILL = 2.1             # PTFE 填充（TEM 口径 εeff=εr 精确）
_SMA_SHELL_T_MM = 0.25         # 外导体壁厚（r_os = r_o + 壁厚，派生量）
# port1 面距 y-min 边界的网格 cell 数：越过 PML_8（8 cells）再留 4 cells 净空
# （根治前 port1 距边界 0.5mm 整体落在 PML_8 内，H4 实证）
_SMA_PORT_CELLS_FROM_BOUNDARY = 12

MSL_CPW_NOMINAL: dict[str, Any] = {
    "w_msl_mm": _MSL_CPW_50OHM_W_MM,   # 50Ω 微带（inverse_width）
    "w_cpw_mm": 0.849,    # 50Ω CPWG @gap0.2（_cpwg_ri brentq 反解 0.848999）
    "gap_cpw_mm": 0.2,
    "line_len_mm": 40.0,  # 总长（过渡区居中，MSL/CPW 直段各半）
    "trans_len_mm": 10.0,
    "r_via_mm": 0.15,     # 接地过孔半径（via 基元同款）
    "via_spacing_mm": 2.0,
    "via_offset_mm": 0.5,  # 地内缘→过孔中心
}

SMA_LAUNCHER_NOMINAL: dict[str, Any] = {
    "w_msl_mm": _MSL_CPW_50OHM_W_MM,
    "r_i_mm": _SMA_RI_MM,
    # 50Ω 同轴闭式 r_o = r_i·exp(Z0·√εr/60)（PTFE εr=2.1 → 2.124389）
    "r_o_mm": 2.1244,
    "shell_t_mm": _SMA_SHELL_T_MM,   # 外导体壁厚（r_os=2.3744 派生）
    "er_fill": _SMA_ER_FILL,
    "shell_len_mm": 5.0,  # 同轴段长：port1 面 → 板边（切口面 Y_E）
    "pin_lay_mm": 2.0,    # 针搭焊段：板边外伸、水平搭在微带上（焊锡填实）
    "line_len_mm": 40.0,  # 微带体带长（板边 Y_E → Y1；port2 自画 Y1→BOARD）
    "port_len_mm": 0.2,   # 集总桥 y 向厚（针顶→壳内壁顶 z 向桥，E 沿径向）
    # ③ 变体：PTFE 介质损耗 tanδ → AddMaterial kappa（同基板 TAND 口径）；
    # 名义无耗 0.0（与理想级联裁判/真机 pt3 同口径），有耗变体走 recipe 覆盖
    "tan_d_fill": 0.0,
}


def sma_launcher_r_o_mm(r_i_mm: float, er_fill: float = _SMA_ER_FILL,
                        z0_ohm: float = 50.0) -> float:
    """50Ω 同轴外径内缘闭式：Z0 = (60/√εr)·ln(r_o/r_i) 反解（TEM 精确）。"""
    return float(r_i_mm) * math.exp(z0_ohm * math.sqrt(er_fill) / 60.0)


def sma_launcher_layout(p: dict[str, Any], h_sub_m: float,
                        base_m: float, board_m: float = 0.060) -> dict[str, float]:
    """sma_launcher 几何单源（米）——render/_near_points/z 网格/geometry_spec/审计共用。

    夹具口径（edge-launch，2026-09-16 根治）：针轴高 Z_AX=r_os（壳底切 z=0 PEC
    夹具底板），PCB 抬高 Z_G=r_os−r_i−H_SUB 使针底切线恰为基板顶 Z_TOP（针水平
    搭焊微带）；同轴段 y∈[Y_B, Y_E]（Y_E=板边切口面，Y_B=port1 面后退 2 cells
    的开口同轴端），针延至 Y_PE=Y_E+pin_lay 搭在微带上；夹具金属块填 PCB 下方
    z∈[0,Z_G]、y∈[Y_E,BOARD]，前脸 y=Y_E 与壳端实触（地链：壳—夹具—PEC 底板）。
    浮点运算顺序在此单源固定，渲染脚本内同名量按同序重算（字面同源）。
    """
    ri = float(p.get("r_i_mm", 0.635)) * 1e-3
    ro = float(p.get("r_o_mm", 2.1244)) * 1e-3
    t = float(p.get("shell_t_mm", _SMA_SHELL_T_MM)) * 1e-3
    ros = ro + t
    z_ax = ros
    z_g = ros - ri - h_sub_m
    z_top = z_g + h_sub_m
    y_p0 = -board_m + _SMA_PORT_CELLS_FROM_BOUNDARY * base_m
    y_b = y_p0 - 2 * base_m
    y_e = y_p0 + float(p.get("shell_len_mm", 5.0)) * 1e-3
    y_pe = y_e + float(p.get("pin_lay_mm", 2.0)) * 1e-3
    y1 = y_e + float(p.get("line_len_mm", 40.0)) * 1e-3
    if not (ri < ro):
        raise ValueError(f"sma_launcher: r_i={ri * 1e3:.4g}mm 须 < r_o={ro * 1e3:.4g}mm")
    if not (t > 0.0):
        raise ValueError(f"sma_launcher: shell_t_mm={t * 1e3:.4g} 须 >0")
    if not (z_g > 0.0):
        raise ValueError(
            f"sma_launcher: r_os−r_i={(ros - ri) * 1e3:.4g}mm 须 > H_SUB="
            f"{h_sub_m * 1e3:.4g}mm（针底切线高于夹具底板才能抬板）")
    if not (y1 < board_m):
        raise ValueError(f"sma_launcher: 体带终点 Y1={y1 * 1e3:.4g}mm 越出板 {board_m * 1e3:g}mm")
    # 连接器体前脸（v2，2026-09-16 pt3 v1 真跑 |S11|=−4dB 后增设）：与板边齐平的
    # 金属面墙（厂商口径"connector face flush with PCB edge"，refs §14.2），孔径由
    # PTFE 环/针以优先级挖空；半宽/高度 = 壳外径 + 2 cells，厚 2 cells（体尺寸为
    # 通用连接器体口径，非物理拟合量）
    f_w = ros + 2 * base_m
    f_t = 2 * base_m
    f_z = z_ax + ros + 2 * base_m
    return {"ri": ri, "ro": ro, "t": t, "ros": ros, "z_ax": z_ax, "z_g": z_g,
            "z_top": z_top, "y_b": y_b, "y_p0": y_p0, "y_e": y_e, "y_pe": y_pe,
            "y1": y1, "w_m": float(p.get("w_msl_mm", 1.1134)) * 1e-3,
            "plen": float(p.get("port_len_mm", 0.2)) * 1e-3,
            "f_w": f_w, "f_t": f_t, "f_z": f_z}


def _msl_cpw_lines(p: dict[str, Any]) -> str:
    # MSL↔CPWG 过渡（WP2.5 Tier 2）：微带直段 → 中心导体阶梯渐变
    # （NT 段等分过渡区）→ CPW 中心段+两侧地（延至板边）+ 接地过孔栅栏
    # （CPWG 地缝合底板 PEC，抑制平行板模——过渡族必要件）。
    # port1=MSLPort（50Ω 微带口径）、port2=CPWPort（CPWG 口径，地自画——
    # cpw 锚模板同口径）。双段 β 金标准见 render_script beta_block。
    return f'''W_M = {p.get("w_msl_mm", 1.1134)!r} * 1e-3
W_C = {p.get("w_cpw_mm", 0.849)!r} * 1e-3
GAP = {p.get("gap_cpw_mm", 0.2)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
TL = {p.get("trans_len_mm", 10.0)!r} * 1e-3
NT = 4
RV = {p.get("r_via_mm", 0.15)!r} * 1e-3
SV = {p.get("via_spacing_mm", 2.0)!r} * 1e-3
VO = {p.get("via_offset_mm", 0.5)!r} * 1e-3
Y0 = -L / 2
YM = -TL / 2
YT = TL / 2
Y1 = L / 2
mslcpw = CSX.AddMetal("msl_cpw")
# 微带直段（MSLPort 自画 -BOARD→Y0 馈线）
mslcpw.AddBox((-W_M / 2, Y0, H_SUB), (W_M / 2, YM, H_SUB), priority=10)
# 中心导体阶梯渐变（等分过渡区，段宽线性内插 W_M→W_C）
for _i in range(NT):
    _ya = YM + _i * TL / NT
    _yb = YM + (_i + 1) * TL / NT
    _w = W_M + (_i + 0.5) * (W_C - W_M) / NT
    mslcpw.AddBox((-_w / 2, _ya, H_SUB), (_w / 2, _yb, H_SUB), priority=10)
# CPW 中心段 + 两侧地（自渐变终点延至板边；端口段地须自画——cpw 同口径）
mslcpw.AddBox((-W_C / 2, YT, H_SUB), (W_C / 2, Y1, H_SUB), priority=10)
mslcpw.AddBox((-BOARD, YT, H_SUB), (-(W_C / 2 + GAP), BOARD, H_SUB),
              priority=10)
mslcpw.AddBox((W_C / 2 + GAP, YT, H_SUB), (BOARD, BOARD, H_SUB), priority=10)
# 接地过孔栅栏（地内缘外 VO 处双列，至板边——寄生方向性最小的最简栅栏）
mslcpw_via = CSX.AddMetal("msl_cpw_via")
_k = 0
while YT + VO + _k * SV <= BOARD - VO:
    _yv = YT + VO + _k * SV
    for _xv in (-(W_C / 2 + GAP + VO), (W_C / 2 + GAP + VO)):
        mslcpw_via.AddCylinder([_xv, _yv, 0.0], [_xv, _yv, H_SUB],
                               radius=RV, priority=10)
    _k += 1
_port1 = MSLPort(CSX, port_nr=1, metal_prop=mslcpw,
                 start=np.array([W_M / 2, -BOARD, H_SUB]),
                 stop=np.array([-W_M / 2, Y0, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = CPWPort(CSX, port_nr=2, metal_prop=mslcpw,
                 start=np.array([W_C / 2, BOARD, H_SUB]),
                 stop=np.array([-W_C / 2, Y1, H_SUB]),
                 prop_dir="y", exc_dir="z", gap_width=GAP,
                 excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
for _prim in mslcpw.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in mslcpw_via.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _sma_launcher_lines(p: dict[str, Any]) -> str:
    # SMA 边缘弹射（WP2.5 Tier 2，2026-09-16 根治重构，edge-launch 夹具口径）：
    # 真机 FAIL 根因（scripts/diag_sma_launcher.py 精确接触图实证，legacy 留档
    # runs/wp25_tier2_smoke/pt3_sma_launcher_diag/legacy_contacts.json）：
    #   H2 引脚柱盒与壳底壁实交叠——信号链对接地壳短路（|S21|≈−375dB）；
    #   H1 地侧针与壳/墙/底板零接触——串馈集总口基准端悬空；
    #   H4 port1 距 y-min 边界 0.5mm 整体落在 PML_8 内；H5 壳顶距域顶 0.25mm。
    # 新几何（连接器厂商 end-launch 图纸口径，docs/rf_template_references.md
    # SMA 节）：针水平搭焊微带（针底切线=基板顶）、壳体在板边切口之外、地链
    # 壳—夹具块—PEC 底板实触；port1 = 同轴截面集总桥（LumpedPort R=50Ω，
    # 针顶→壳内壁顶沿 z=径向，官方 LumpedPort 口径——CoaxialPort 真机判废：
    # pt2 冒烟 β=4166 vs TEM 闭式 68、|S21|=−240dB）。PTFE 填充 TEM 口径
    # εeff=εr；同轴 50Ω 由 r_o 闭式保证（sma_launcher_r_o_mm）。
    # 几何单源 sma_launcher_layout（render_script 注入 _sma_layout 字面量，
    # z 网格/基板块/近场线同源）。
    lay = p.get("_sma_layout") or sma_launcher_layout(
        p, 0.508e-3, float(p.get("_base_mm", 0.4)) * 1e-3)
    return f'''W_M = {lay["w_m"]!r}
RI = {lay["ri"]!r}
RO = {lay["ro"]!r}
ROS = {lay["ros"]!r}           # r_o + shell_t（外导体外径，派生）
ER_FILL = {p.get("er_fill", 2.1)!r}
PT_TAND = {p.get("tan_d_fill", 0.0)!r}   # PTFE tanδ（③ 变体；名义 0=无耗）
Z_AX = {lay["z_ax"]!r}         # 针轴高 = r_os（壳底切 z=0 PEC 夹具底板）
Z_G = {lay["z_g"]!r}           # PCB 地面 = 夹具块顶（r_os − r_i − H_SUB）
Z_TOP = {lay["z_top"]!r}       # 基板顶 = 微带面 = 针底切线（针水平搭焊）
Y_B = {lay["y_b"]!r}           # 开口同轴端（port1 面后退 2 cells）
Y_P0 = {lay["y_p0"]!r}         # port1 面（越过 y-min PML_8 + 4 cells 净空）
Y_PL = {lay["y_p0"] + lay["plen"]!r}   # 集总桥 y 向终面
Y_E = {lay["y_e"]!r}           # 板边切口面 = 壳端 = 微带起点
Y_PE = {lay["y_pe"]!r}         # 针端（搭焊段终点）
Y1 = {lay["y1"]!r}             # 体带终点（port2 自画 Y1→BOARD）
F_W = {lay["f_w"]!r}           # 连接器体前脸半宽（r_os + 2 cells）
F_T = {lay["f_t"]!r}           # 前脸厚（2 cells，y∈[Y_E−F_T, Y_E]）
F_Z = {lay["f_z"]!r}           # 前脸顶（壳顶 + 2 cells）
# 夹具金属块：PCB 下方 z∈[0,Z_G] 实心（PCB 地 = 块顶；前脸 y=Y_E 与壳端实触）
sma_gnd = CSX.AddMetal("sma_gnd")
sma_gnd.AddBox((-BOARD, Y_E, 0.0), (BOARD, BOARD, Z_G), priority=10)
# 连接器体前脸（v2）：与板边齐平的金属面墙，优先级 4 < PTFE 环 5 / 针 10 →
# 孔径处按材料优先级挖空（针穿孔而过，PTFE 隔离）；不进 priority 抬升循环
sma_face = CSX.AddMetal("sma_face")
sma_face.AddBox((-F_W, Y_E - F_T, 0.0), (F_W, Y_E, F_Z), priority=4)
# 板边切口：y<Y_E 无基板（空气盒盖过基板层；优先级 1>基板 0，<PTFE 5/金属 10）
sma_notch = CSX.AddMaterial("sma_notch", epsilon=1.0)
sma_notch.AddBox((-BOARD, -BOARD, Z_G), (BOARD, Y_E, Z_TOP), priority=1)
# 同轴段 y∈[Y_B, Y_E]：PTFE 填充环（tanδ→kappa 同基板口径）+ 外导体壳（壳底切
# z=0 夹具底板，实触）
ptfe = CSX.AddMaterial("ptfe", epsilon=ER_FILL,
                       kappa=PT_TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER_FILL)
ptfe.AddCylindricalShell(np.array([0.0, Y_B, Z_AX]), np.array([0.0, Y_E, Z_AX]),
                         0.5 * (RI + RO), RO - RI, priority=5)
sma_shell = CSX.AddMetal("sma_shell")
sma_shell.AddCylindricalShell(np.array([0.0, Y_B, Z_AX]),
                              np.array([0.0, Y_E, Z_AX]),
                              0.5 * (RO + ROS), ROS - RO, priority=10)
# 中心针：同轴内穿出板边切口面，水平搭在微带上至 Y_PE（针底切线 = Z_TOP）
sma_pin = CSX.AddMetal("sma_pin")
sma_pin.AddCylinder(np.array([0.0, Y_B, Z_AX]), np.array([0.0, Y_PE, Z_AX]),
                    radius=RI, priority=10)
# 针顶接触垫：阶梯网格下保证集总桥下电极（z=Z_AX+RI 切线）金属边连续
sma_pin.AddBox((-RI / 2, Y_P0, Z_AX), (RI / 2, Y_PL, Z_AX + RI), priority=10)
# 搭焊焊锡：针下半侧填实至微带面（针—微带实接触，宽度=微带宽）
sma_pin.AddBox((-W_M / 2, Y_E, Z_TOP), (W_M / 2, Y_PE, Z_AX), priority=10)
# port1：同轴截面集总桥（针顶 z=Z_AX+RI → 壳内壁顶 z=Z_AX+RO，E 沿 z=径向；
# 优先级 6：高于 PTFE 5（桥内为集总元件）、低于金属 10（端面归金属））
_port1 = LumpedPort(CSX, port_nr=1, R=50.0,
                    start=np.array([-RI / 2, Y_P0, Z_AX + RI]),
                    stop=np.array([RI / 2, Y_PL, Z_AX + RO]),
                    exc_dir="z", excite=1, priority=6)
sma_strip = CSX.AddMetal("sma_strip")
sma_strip.AddBox((-W_M / 2, Y_E, Z_TOP), (W_M / 2, Y1, Z_TOP), priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=sma_strip,
                 start=np.array([-W_M / 2, BOARD, Z_TOP]),
                 stop=np.array([W_M / 2, Y1, Z_G]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
for _metal in (sma_gnd, sma_shell, sma_pin, sma_strip):
    for _prim in _metal.GetAllPrimitives():
        if _prim.GetPriority() < 10:
            _prim.SetPriority(10)
'''


# ── WP2.5 两模板 META/NOMINAL（2026-09-16 正式注册，hairpin/coupled_bpf 同款
# 同对象入表；四件套其余三处：docs/templates/{msl_cpw,sma_launcher}/meta.yaml、
# test_template_geometry_audit.EXPECTED_TEMPLATES、fake_adapter 派发分支、
# models/template_specs _register_msl_cpw/_register_sma_launcher）──
MSL_CPW_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1 / CPWPort 2（MSL↔CPWG 过渡：双端口 β 金标准"
                  "（port1→HJ、port2→CPWG 共形映射）+ skrf 两段理想 TL 级联裁判）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_msl_mm", "w_cpw_mm", "gap_cpw_mm", "line_len_mm",
               "trans_len_mm", "r_via_mm", "via_spacing_mm", "via_offset_mm"],
    "topology": "微带↔接地共面波导过渡（WP2.5 Tier 2）：微带直段 → 4 段等分"
                "阶梯渐变（线宽线性内插）→ CPW 中心带 + 两侧地（延至板边）+ 双列"
                "接地过孔栅栏（地缝合底板 PEC，抑制平行板模）；过渡区居中",
    "param_semantics": "w_msl_mm=50Ω 微带宽（HJ 反解），w_cpw_mm=50Ω CPWG 中心"
                       "带宽（_cpwg_ri brentq 反解 @gap），gap_cpw_mm=CPW 缝宽，"
                       "line_len_mm=总长（MSL/CPW 直段各半），trans_len_mm=渐变区"
                       "长，r_via_mm/via_spacing_mm/via_offset_mm=接地过孔半径/"
                       "列间距/地内缘→过孔中心",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "微带带缘 + CPW 四条几何边（带缘/地内缘）+ 缝中线 + 渐变区两端"
                 "精确入网（#198）",
}

SMA_LAUNCHER_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ LumpedPort 1（同轴截面集总桥）/ MSLPort 2（SMA edge-"
                  "launch：port2 β→HJ 金标准 + |S11| 文献曲线门 -10dB 保守地板）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_msl_mm", "r_i_mm", "r_o_mm", "shell_t_mm", "er_fill",
               "shell_len_mm", "pin_lay_mm", "line_len_mm", "port_len_mm",
               "tan_d_fill"],
    "topology": "SMA 边缘弹射（WP2.5 Tier 2，end-launch 夹具口径）：PTFE 填充"
                " 50Ω 同轴段（针/壳圆柱自画）在板边切口之外，针水平穿出搭焊在"
                " 微带上（针底切线=基板顶），壳底切 z=0 PEC 夹具底板、壳端与"
                " PCB 下方夹具金属块前脸实触（地链）；port1=同轴截面集总桥"
                "（针顶→壳内壁顶），port2=板边 MSLPort",
    "param_semantics": "w_msl_mm=50Ω 微带宽（HJ），r_i_mm=针半径，r_o_mm=PTFE 外"
                       "径/壳内径（50Ω 闭式 r_i·exp(Z0√εr/60)），shell_t_mm=外导"
                       "体壁厚（r_os=r_o+t 派生），er_fill=PTFE εr（材料参数，"
                       "不驱动导体几何），shell_len_mm=同轴段长（port1 面→板边），"
                       "pin_lay_mm=针搭焊外伸长，line_len_mm=微带体带长，"
                       "port_len_mm=集总桥 y 向厚，tan_d_fill=PTFE tanδ（材料"
                       "参数→kappa，名义 0 无耗；③ 有耗变体 recipe 覆盖）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "同轴三半径 x/z 向柱面界 + 桥盒边 + 板边/针端/带端 y 面精确"
                 "入网；port1 面距 y-min 边界 12 cells（越过 PML_8）",
}

TEMPLATE_META["msl_cpw"] = MSL_CPW_META
TEMPLATE_NOMINAL["msl_cpw"] = MSL_CPW_NOMINAL
TEMPLATE_META["sma_launcher"] = SMA_LAUNCHER_META
TEMPLATE_NOMINAL["sma_launcher"] = SMA_LAUNCHER_NOMINAL



# ═══════════════════════════════════════════════════════════════════════════════
# §10.3 C1 天线族 II：单极子(monopole)/PIFA/IFA/环形(loop)/螺旋(helix)/缝隙(slot)
# ——贴片锚向变形扩展的六个辐射模板（2026-09-14 增量；同日合流轮正式注册进
# TEMPLATE_META/TEMPLATE_NOMINAL——注册四件套 docs/templates/<t>/meta.yaml、
# test_template_geometry_audit.EXPECTED_TEMPLATES、fake_adapter 派发
# _antenna2_sparams、models/template_specs _register_antenna2 已补齐；注册动作
# 见 ANTENNA2_NOMINAL 之后的赋值块，钉在 test_antenna2_templates.py::
# test_antenna2_registered_in_registry）
# ═══════════════════════════════════════════════════════════════════════════════
# ── 理论核验轮（口径/来源逐条；裁判=独立闭式，不自证；#206 纪律）──
# 1) 单极子：像理论（Balanis《Antenna Theory》4ed monopole = PEC 地面上方
#    半偶极子）⇒ 一阶谐振长 λ0/4：L = c/(4·f0)。细带端效应使真机谷位低于
#    设计频率（同 dipole 58mm 口径）——设计式不做预补偿，冒烟实测偏差如实
#    记录（#190 范式：引擎常数须经仲裁才能进设计公式）。
#    真机实测（runs/antenna2_smoke/monopole，2026-09-14）：谷 −17.39dB @
#    2.135GHz，端效应偏移 −11.0%（设计点 2.4GHz），窗 ±12% 内 PASS。
# 2) PIFA：**L 路径式定版（2026-09-16）** L = λ0/(4·√εeff(W))（εeff 取 skrf
#    HJ @W，与 patch 谐振轴同口径，铁律 1c）。文献通式 L + W − Ws ≈ λ/4
#    （Ollikainen 1999 / Zürcher & Gardiol）**前提是角部短路板**（电流自短路
#    板沿贴片宽度绕行再折向开路边）；本布局短路板居中（Ws=2 于 W=8 中央），
#    电流不绕行，有效路径≈L——两轮真机实证（战役档案/仓内
#    antenna2 坑③）：通式标称 L=11.0785 谐振在 2.9GHz 之上 FAIL，L 路径式
#    override 17.08 → −8.79dB@2.26GHz PASS（runs/antenna2_smoke/pifa_override）。
#    Ws 仍是几何输入（短路板宽定馈阻抗/带宽），不进谐振式。馈针位置定匹配
#    （近短路板低阻、远离升高）：标称 pin_back=2mm、pin_y=W/4。
# 3) IFA：PIFA 通式的窄臂退化（W→臂宽）：臂长（自短路板起算）≈ λ0/(4·√εeff)
#    （HJ @臂宽）；馈针-短路板间距 s 定输入阻抗（s 小→低阻），标称 s=2mm，
#    冒烟判读。
# 4) 环形：**自由空间口径（2026-09-16 改造）**——一周长自谐振环 C ≈ λ0
#    （Balanis §5 大环口径；小环电容加载不在本模板）⇒ 方环中心线边
#    a = λ0/4（εeff→1：无基板无地，dipole 同款底 MUR + 域 z 向下延 λ0/4，
#    环面 z=0）；馈口 = 底边中央断口 LumpedPort（dipole 中央馈口同型）。
#    改造动因（像理论，真机实证）：旧贴地口径（z=h 环贴 PEC 地 0.508mm=
#    0.004λ0）镜像反向电流抵消辐射 → R=0.56Ω（电抗过零 2.3825GHz 对但不
#    辐射，runs/antenna2_smoke/loop）。判据改电抗过零（f0±12%）+ 过零处
#    R ≥ 20Ω（对照旧 0.56Ω；S11 −5dB 作次级）——一周长环馈阻抗文献口径
#    ≈100-200Ω，对 50Ω 固有失配，谷深不是谐振判据（antenna2 坑②：
#    判谐振看电抗过零/并联 R 峰）。
# 5) 螺旋：法向模螺旋单极子（Balanis §9 helical antennas 法向模区）：一阶
#    口径 = 总导线长 k_helix·λ0/4（k_helix=1.3615，2026-09-17 HFSS 同几何仲裁
#    AGREE 定版：λ0/4 口径真机 f_x=3.31GHz（openEMS）/3.2675GHz（HFSS）≠2.4，
#    即 λ0/4 线长高估电长度、谐振偏高——与"慢波使谐振更低"的初始预期相反；
#    K_HELIX 常量与证据链见 helix_pitch_mm 段）；方截面 staircase 渲染（每圈
#    4 直段、四角 1/4 螺距竖板逐级上升——单导线连续路径，无双并联回路）；
#    p = (k_helix·λ0/4 − 4·d·N)/N ≥ 1mm 守卫（d 太大则设计非法，显式报错不静默）。
# 6) 缝隙：地面谐振缝 L = λ0/(2·√εeff_slot)（Balanis §14 slot antennas；
#    Booker 互补原理：缝↔偶极子对偶）；介质单侧加载有效 ε 一阶取半空间
#    均值 (1+εr)/2。真机标定（runs/antenna2_smoke/slot[_override]，
#    2026-09-14，两点）：L=40.9168mm→S21 辐射凹 −16.4dB@2.70GHz
#    （隐含 εeff 1.84）；L=46.036mm→−21.8dB@2.6275GHz（隐含 εeff 1.54，
#    窗内 PASS）——辐射凹指标与缝长非线性，k_slot ∈ [0.66, 0.79]·(1+εr)/2
#    待 HFSS 仲裁后才进设计公式（#190；场偏空气侧=薄基底单侧加载）。
#    锚签名（实证）：过缝辐射负载使 S11 全带平坦（−0.5~-2.8dB，功率辐射
#    不反射）——谐振判据=S21 辐射凹位置+深度，非 S11 谷。
#    地面 = z=0 有限金属板（4 盒拼合、槽区留空）+ 底边界 MUR + z 向下延
#    λ0/4（dipole 同款——槽向下半空间也辐射，PEC 底边界会短路槽）；微带
#    馈线垂直跨槽中心，双 MSLPort 板边端接。
# 通用口径：PIFA/IFA 介质板下方 z-min PEC = 无限大地（patch 官方口径）；
# monopole/helix 无介质板（PEC 地面悬空导体）；loop 自由空间（无板无地、底
# MUR、域 z 向下延 λ0/4，dipole 同款）；六模板全部辐射器件
# （AIR_TOP/AIR_SIDE = λ0/4）。端口铁律自查：馈口盒边全部进网格（#198）、
# 激励向跨度 >0（#174）、单端口模板 _port2=_port1 fallback（patch 口径）。

_ANT2_C_MM_GHZ = 299.792458   # mm·GHz（真空光速，与 core/_HAIRPIN 段同口径）
ANTENNA2_TEMPLATES: tuple[str, ...] = (
    "monopole", "pifa", "ifa", "loop", "helix", "slot")
# 立体器件（无介质板 + 竖直元 → 专项 z 网格/无基板块）
_ANTENNA2_TALL_TEMPLATES: tuple[str, ...] = ("monopole", "helix")
# 自由空间器件（无介质板、无地：底 MUR + 域 z 向下延 λ0/4，dipole 同款）
_ANTENNA2_FREE_SPACE_TEMPLATES: tuple[str, ...] = ("loop",)


def _ant2_eps_eff(w_mm: float, freq_ghz: float, er: float, h_mm: float) -> float:
    """微带 εeff（skrf HJ 正向；core/synthesis 唯一介质口径，铁律 1c）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="antenna2", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    _, ere = forward_z0(float(w_mm), float(freq_ghz), stackup)
    return float(ere)


# ─── 闭式设计函数（确定性内核：谐振尺寸只由公式给出，非手数）────────────────

def monopole_len_mm(f0_ghz: float) -> float:
    """单极子一阶谐振长 λ0/4（像理论，Balanis monopole = 半偶极子）。"""
    if not float(f0_ghz) > 0.0:
        raise ValueError(f"f0 须正，得 {f0_ghz}")
    return _ANT2_C_MM_GHZ / (4.0 * float(f0_ghz))


def pifa_l_mm(f0_ghz: float, w_mm: float, w_short_mm: float,
              er: float = 3.66, h_mm: float = 0.508) -> float:
    """PIFA 贴片长 L = λ0/(4·√εeff(W))（L 路径式定版，HJ @W）。

    居中短路板下有效电流路径≈L（段首理论核验 2；真机两轮实证），文献通式
    L+W−Ws 的 +W−Ws 项不适用。w_short_mm 只做合法性守卫（Ws≤W 由布局守
    卫），不进谐振式——签名保留以稳住 template_specs/单测调用契约。
    """
    if not (float(f0_ghz) > 0.0 and float(w_mm) > 0.0
            and float(w_short_mm) > 0.0):
        raise ValueError("f0/W/Ws 须正")
    return _ANT2_C_MM_GHZ / (
        4.0 * float(f0_ghz)
        * math.sqrt(_ant2_eps_eff(float(w_mm), float(f0_ghz),
                                  float(er), float(h_mm))))


def ifa_arm_len_mm(f0_ghz: float, w_mm: float = 1.0,
                   er: float = 3.66, h_mm: float = 0.508) -> float:
    """IFA 臂长（短路板起算）≈ λ0/(4·√εeff)（HJ @臂宽；PIFA 窄臂退化）。"""
    if not float(w_mm) > 0.0:
        raise ValueError("臂宽须正")
    return _ANT2_C_MM_GHZ / (
        4.0 * float(f0_ghz)
        * math.sqrt(_ant2_eps_eff(float(w_mm), float(f0_ghz),
                                  float(er), float(h_mm))))


def loop_side_mm(f0_ghz: float, w_mm: float = 1.0,
                 er: float = 3.66, h_mm: float = 0.508) -> float:
    """一周长谐振环方环中心线边 a = λ0/4（自由空间口径 C=4a≈λ0，εeff→1）。

    2026-09-16 自由空间改造：无基板无地（段首理论核验 4），介质加载项退出
    ——w_mm/er/h_mm 保留在签名（守卫 + template_specs/单测调用契约），不进
    谐振式。
    """
    if not (float(f0_ghz) > 0.0 and float(w_mm) > 0.0):
        raise ValueError("f0/环带宽须正")
    return _ANT2_C_MM_GHZ / (4.0 * float(f0_ghz))


#: 法向模螺旋慢波系数（HFSS 同几何仲裁定版，2026-09-17 收尾批，#190 范式）：
#: λ0/4 总线长口径的真机电抗过零 f_x=3.2675GHz（HFSS，真实三维盒/unite/0.3mm）
#: vs 3.3146GHz（openEMS，自动/0.35mm 网格、16.7/50mm 域三重稳健）偏差 1.44% ≤5%
#: ⇒ AGREE；k_helix=f_x(HFSS)/f0=3.2675/2.4（openEMS 基 1.3811 同在门内）。总线长
#: 设计式 = k_helix·λ0/4（谐振随线长一阶反比）。证据链 runs/helix_arbitration/。
K_HELIX = 1.3615


def helix_pitch_mm(f0_ghz: float, d_mm: float, n_turns: int) -> float:
    """法向模螺旋螺距：总导线长 k_helix·λ0/4 = N·(4d + p) 反解 p（守卫 p ≥ 1mm）。"""
    wire = K_HELIX * _ANT2_C_MM_GHZ / (4.0 * float(f0_ghz))
    if not (float(d_mm) > 0.0 and int(n_turns) >= 1):
        raise ValueError("d 须正且 N ≥ 1")
    pitch = (wire - 4.0 * float(d_mm) * int(n_turns)) / int(n_turns)
    if pitch < 1.0:
        raise ValueError(
            f"螺旋设计非法：p={pitch:.3f}mm < 1mm（d·N 过大，压不下 k_helix·λ0/4）")
    return pitch


def slot_len_mm(f0_ghz: float, er: float = 3.66) -> float:
    """地面谐振缝长 λ0/(2·√((1+εr)/2))（Booker 对偶 + 半空间均值口径）。"""
    if not float(er) >= 1.0:
        raise ValueError("εr 须 ≥ 1")
    eps = 0.5 * (1.0 + float(er))
    return _ANT2_C_MM_GHZ / (2.0 * float(f0_ghz) * math.sqrt(eps))


# 各模板标称设计点 @2.4GHz（与闭式设计函数 4 位舍入一致，单测互检；
# 贴片/臂/环带宽=设计输入，εeff 由 HJ 随动）
ANTENNA2_NOMINAL: dict[str, dict[str, Any]] = {
    "monopole": {
        # λ0/4 @2.4GHz = 31.2284（monopole_len_mm 4 位舍入）
        "mon_len_mm": 31.2284, "mon_w_mm": 1.0, "feed_gap_mm": 2.0,
    },
    "pifa": {
        # L = λ0/(4√εeff(8mm)=3.3435) = 17.0785（L 路径式定版；旧通式
        # 17.0785 − 8 + 2 = 11.0785 真机 FAIL，见段注）
        "pifa_l_mm": 17.0785, "pifa_w_mm": 8.0, "pifa_ws_mm": 2.0,
        "pin_back_mm": 2.0, "pin_y_mm": 2.0,
    },
    "ifa": {
        # 臂长 = λ0/(4√εeff(1mm)=2.8336) = 18.5515
        "ifa_arm_mm": 18.5515, "ifa_w_mm": 1.0, "feed_off_mm": 2.0,
    },
    "loop": {
        # 中心线方边 = λ0/4（自由空间口径，monopole 同数）= 31.2284；旧贴地
        # λg/4=18.5515 口径 R=0.56Ω 不辐射（见段注）
        "loop_side_mm": 31.2284, "loop_w_mm": 1.0, "loop_gap_mm": 1.0,
    },
    "helix": {
        # p = (k_helix·31.2284 − 4·3·2)/2 = (42.5174 − 24)/2 = 9.2587（守卫 ≥1mm 过）
        # 旧 λ0/4 口径 3.6142（真机 f_x 3.27-3.31GHz ≠ 2.4，HFSS 仲裁 AGREE 后定版）
        "helix_d_mm": 3.0, "helix_turns": 2, "helix_pitch_mm": 9.2587,
        "helix_w_mm": 0.6, "feed_gap_mm": 2.0,
    },
    "slot": {
        # 缝长 = λ0/(2√2.33) = 40.9168；馈线 = 50Ω HJ 宽
        "slot_l_mm": 40.9168, "slot_w_mm": 2.0,
        "feed_w_mm": 1.1134, "feed_margin_mm": 12.0,
    },
}

# 各模板元数据（TEMPLATE_META 公约字段；f0=2.4GHz 设计点；单端口集总馈
# n_ports=1、slot 双 MSLPort n_ports=2）。
# ── 真机冒烟判读（runs/antenna2_smoke/<t>/sparams.csv，2026-09-14，扫频
#    1.9-2.9GHz，判据 scripts/smoke_antenna2_anchor.py：谷深门 + f0±12% 窗）──
#   monopole PASS：S11 −17.39dB @2.135GHz（−11.0%，端效应）；Zin 电抗过零
#     2.110GHz R=37.3Ω（Balanis 单极子 36.5Ω 口径吻合）。
#   ifa  PASS：S11 −8.48dB @2.44GHz（+1.7%）；并联型谐振 Zin@谷=103−24jΩ
#     （馈针距短路板 2mm ⇒ R_peak≈100Ω，对 50Ω 过耦合限住谷深；feed_off
#     再近可压向 50Ω）。带外 R≈0 是无耗短路桩馈结构的正常反应，非端口短路
#     （首判"端口被针盒短路→PARTIAL"已被去针复跑证伪：v1/v2 逐点一致）。
#   pifa 旧通式标称 L=11.0785 FAIL：|S11|≥−0.02dB 全带，Zin=0.0+j(3.9→8.6)Ω
#     随 f 线性=纯短路桩电感 ⇒ 谐振在 2.9GHz 之上。**根因（真机实证，两轮）**：
#     ① 去掉同体积金属针盒后 S11 逐点不变——"PEC 针盒短路端口"假设证伪；
#     ② override pifa_l_mm=17.08（=λ0/(4√εeff(W))，仅 L 路径口径）→ S11
#     −8.79dB @2.26GHz（−5.8%）PASS、Zin@谷=105−14jΩ、solve 264s（vs 非谐振
#     34s）。即 L+W−Ws=λ/4 通式假定角部短路板（电流绕行贴片宽度），而本
#     布局短路板居中（Ws=2 于 W=8 中央）电流不绕行，有效路径≈L。
#     **定版（2026-09-16）**：设计式改 L 路径式 pifa_l_mm=λ0/(4√εeff(W))，
#     标称 17.0785（与 PASS 的 override 17.08 差 0.0015mm=0.009%，真机证据
#     直接沿用，runs/antenna2_smoke/pifa_override），fake 逆/单测/meta 同步。
#   loop 旧贴地口径（λg/4=18.5515，z=h 贴 PEC 地）FAIL：S11 −0.19dB；Zin 电抗
#     过零 2.3825GHz（−0.7%，谐振长度口径正确）但 R=0.56Ω。**归因（像理论）**：
#     水平环贴 PEC 地 0.508mm（0.004λ0），镜像反向电流抵消辐射 → R_rad→0。
#     **改造（2026-09-16）**：自由空间口径（无板无地、底 MUR、域下延 λ0/4、
#     环面 z=0、a=λ0/4=31.2284），判据改电抗过零 f0±12% + 过零处 R≥20Ω；
#     v2 真机结果见 docs/templates/loop/meta.yaml smoke_note
#     （runs/antenna2_smoke/loop_v2）。
#   helix FAIL：S11 ≤−1.22dB；Zin 全带容性 X∈[−156,−44]Ω 且随 f 单调升
#     → 谐振在 2.9GHz 之上（与段首"慢波使谐振更低"预期相反：λ0/4 总线长
#     口径高估电长度）；R=1.8~6.2Ω 与电小天线 395(h/λ)²≈2Ω 一致——即便谐振
#     也对 50Ω 失配，S11 谷深判据不适用，应改判电抗过零。扩带/仲裁进展见
#     docs/templates/helix/meta.yaml smoke_note（scripts/hfss_helix_arbitration.py）。
#   slot PASS×2：S21 辐射凹 −16.41dB @2.665GHz（L=40.9168）/ −21.76dB @
#     2.6275GHz（L=46.036 override）。Σ|S|² 带边 >1 **已排查（2026-09-16，
#     runs/antenna2_smoke/slot/sparams.csv 实测）**：1.9GHz=1.212、2.9GHz=
#     1.128；>1.02 的点全部落在 1.9-2.08 与 2.82-2.9 两侧，f0±12% 判读窗
#     （2.112-2.688GHz）内 ≤1.008——越限恰在 SetGaussExcite(F0,FC) 高斯激励
#     −20dB 带边（评估带=激励带，uf_inc 归一化分母趋零放大数值噪声），是
#     归一化伪象而非 MSLPort/有限地物理错。判读窗收内带 f0±0.4GHz（激励带
#     内 80%）+ Σ|S|²>1.02 点剔除（smoke_antenna2_anchor.py 全模板通用；slot
#     掩模后 307/321 点，凹位/深度不变），全局 FC 不动（f_max 进 base_m 网格
#     预算，改激励带会漂全部模板网格锚）。
ANTENNA2_META: dict[str, dict[str, Any]] = {
    "monopole": {
        "f0_ghz": 2.4, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（PEC 地面 λ0/4 竖直细带单极子：谷位/"
                      "谷深；真机 −17.39dB@2.135GHz，端效应 −11%）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["mon_len_mm", "mon_w_mm", "feed_gap_mm"],
        "topology": "单极子（§10.3 C1 天线族 II）：竖直零厚细带（x 向宽 mon_w，"
                    "y=0 面）自馈口顶 z=feed_gap 起立 λ0/4；馈口=地面 z=0 → 细带"
                    "底缘 LumpedPort（patch 底馈探针同型）；无介质板（像理论口径）",
        "param_semantics": "mon_len_mm=细带长（一阶谐振 λ0/4=c/(4f0)，像理论），"
                           "mon_w_mm=细带宽，feed_gap_mm=馈口高（地面到细带底缘，"
                           "LumpedPort 激励向 z 跨度）",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；z 网格专项（馈口顶/元件顶"
                     "精确入网，_ANTENNA2_TALL_TEMPLATES）",
    },
    "pifa": {
        "f0_ghz": 2.4, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（PIFA 居中短路板 λ/4：谷位/谷深；L 路径式"
                      "定版标称 17.0785 ≈ 真机 override 17.08 → −8.79dB@2.26GHz"
                      "（−5.8%）PASS，Zin@谷=105−14jΩ，见段注）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["pifa_l_mm", "pifa_w_mm", "pifa_ws_mm", "pin_back_mm",
                   "pin_y_mm"],
        "topology": "PIFA（§10.3 C1）：贴片 z=h（L×W）+ +x 边短路板（宽 Ws，z 0→h"
                    " 触地）+ 馈针（距短路板 pin_back，y 偏 pin_y，针顶触贴片、针底"
                    "触地）；LumpedPort 沿针 z 向；基板 + z-min PEC 无限大地",
        "param_semantics": "pifa_l_mm=贴片长 L（L 路径式定版 L=λ0/(4√εeff(W))，HJ"
                           " @W；居中短路板电流不绕行，文献通式 L+W−Ws 的 +W−Ws 项"
                           "不适用，真机两轮实证），pifa_w_mm=贴片宽 W，pifa_ws_mm="
                           "短路板宽 Ws（≤W，几何输入不进谐振式），pin_back_mm=馈针"
                           "距短路板（定匹配），pin_y_mm=馈针 y 偏置（<W）",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；贴片/短路板/针缘精确入网",
    },
    "ifa": {
        "f0_ghz": 2.4, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（IFA λ/4 窄臂：谷位/谷深；真机 −8.48dB"
                      "@2.44GHz（+1.7%）PASS，并联型谐振 R_peak≈103Ω 限谷深）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["ifa_arm_mm", "ifa_w_mm", "feed_off_mm"],
        "topology": "IFA（§10.3 C1，PIFA 窄臂退化）：短路板 x∈[−1,0]（z 0→h）+ 臂"
                    " z=h 自短路板 −x 向伸出 λ/4 + 馈针 x=−feed_off（顶触臂、底"
                    "触地）；LumpedPort 沿针 z 向；基板 + z-min PEC 地",
        "param_semantics": "ifa_arm_mm=臂长（短路板起算 ≈λ0/(4√εeff)，HJ @臂宽），"
                           "ifa_w_mm=臂宽，feed_off_mm=馈针-短路板间距（>1.5mm，"
                           "定输入阻抗）",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；臂/短路板/针缘精确入网",
    },
    "loop": {
        "f0_ghz": 2.4, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（一周长方环，自由空间口径：判据=Zin 电抗"
                      "过零 f0±12% + 过零处 R≥20Ω，S11 −5dB 次级；v2 真机 "
                      "2.6774GHz R=112.02Ω PASS（v1 贴地 0.56Ω 镜像抵消 FAIL），"
                      "见 meta.yaml smoke_note）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["loop_side_mm", "loop_w_mm", "loop_gap_mm"],
        "topology": "环形（§10.3 C1，2026-09-16 自由空间改造）：z=0 方环（中心线边 a、"
                    "带宽 w，顶/左/右全跨含角）+ 底边中央断口 g（馈口位）LumpedPort"
                    " 跨断口（E 沿 x，dipole 中央馈口同型）；无基板无地：底 MUR + "
                    "域 z 向下延 λ0/4（dipole 同款）",
        "param_semantics": "loop_side_mm=方环中心线边 a（一周长 C=4a≈λ0，自由空间"
                           " a=λ0/4，εeff→1），loop_w_mm=环带宽，loop_gap_mm=底边"
                           "断口宽（<a，激励向 x 跨度）",
        "mesh_note": "辐射器件：上方/侧向/下方空气隙 λ0/4；环带缘/断口缘精确入网",
    },
    "helix": {
        "f0_ghz": 2.4, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（法向模方螺旋：判据=Zin 电抗容→感上穿 f_x，"
                      "R 电小失配谷深不适用；旧 λ0/4 口径真机 f_x 3.31GHz，HFSS 同几何"
                      "仲裁 3.2675GHz 偏差 1.44% AGREE → k_helix=1.3615 定版，见段注）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["helix_d_mm", "helix_turns", "helix_pitch_mm", "helix_w_mm",
                   "feed_gap_mm"],
        "topology": "螺旋（§10.3 C1）：单导线 staircase 方螺旋（每圈 4 直段各 1/4"
                    " 螺距上升 + 角部竖板，无双并联回路），首圈 A 段即馈口顶，"
                    "总线长 4·d·N + N·p = k_helix·λ0/4（k_helix=1.3615 HFSS 仲裁）；"
                    "馈口=地面 z=0 → 角 A 柱底 LumpedPort；无介质板（PEC 地面悬空导体）",
        "param_semantics": "helix_d_mm=方截面中心线边 d，helix_turns=圈数 N（整数，"
                           "int() 截断），helix_pitch_mm=螺距 p（=(k_helix·λ0/4−4dN)/N "
                           "反解，守卫 ≥1mm），helix_w_mm=导带宽，feed_gap_mm=馈口高",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；z 网格专项（各圈 1/4 螺距面"
                     "全部入网，_ANTENNA2_TALL_TEMPLATES）",
    },
    "slot": {
        "f0_ghz": 2.4, "n_ports": 2,
        "extraction": "S11/S21 @ MSLPort 1-2（地面谐振缝：S21 辐射凹位置+深度=谐振"
                      "判据，过缝辐射负载使 S11 全带平坦不适用；真机 −16.41dB@"
                      "2.665GHz PASS；判读窗收内带 f0±0.4GHz + Σ|S|²>1.02 点剔除——"
                      "带边 Σ|S|²>1 为高斯激励 −20dB 带边归一化伪象，见段注）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["slot_l_mm", "slot_w_mm", "feed_w_mm", "feed_margin_mm"],
        "topology": "缝隙（§10.3 C1）：z=0 有限金属地（4 盒拼合、槽 L×Ws 留空）+"
                    " z=h 50Ω 微带馈线 y 向垂直跨槽居中 + 双 MSLPort 板边端接"
                    "（y=∓BOARD，单轴 PML）；底 MUR + z 向下延 λ0/4（槽向下半空间"
                    "也辐射，PEC 底会短路槽）",
        "param_semantics": "slot_l_mm=缝长（λ0/(2√((1+εr)/2))，Booker 对偶+半空间"
                           "均值口径），slot_w_mm=缝宽，feed_w_mm=馈线宽（50Ω HJ），"
                           "feed_margin_mm=板边到馈线手画段起点的馈段长（MSLPort"
                           " 自画，MeasPlaneShift=margin/3）",
        "mesh_note": "辐射器件：上方/侧向/下方空气隙 λ0/4；地缘/槽缘/馈线缘精确入网",
    },
}

# ── 注册（合流轮）：天线族 II 六模板升格为正式注册模板 ──
# 四处同步：① docs/templates/<t>/meta.yaml ×6；② test_template_geometry_audit
# .EXPECTED_TEMPLATES（18→25，含 coupled_bpf）；③ fake_adapter 派发分支
# （_antenna2_sparams：闭式设计函数精确逆 → 串联谐振一阶模型 / slot 串联
# 并联 RLC 辐射凹）；④ models/template_specs（_register_antenna2）。
# 同对象注册（非拷贝）钉死单一事实源；渲染段零改动。
for _ant2_name in ANTENNA2_TEMPLATES:
    TEMPLATE_META[_ant2_name] = ANTENNA2_META[_ant2_name]
    TEMPLATE_NOMINAL[_ant2_name] = ANTENNA2_NOMINAL[_ant2_name]
del _ant2_name


def antenna2_meta(template: str) -> dict[str, Any]:
    """返回天线族 II 某模板元数据（与 template_meta(t) 同构的便捷别名）。"""
    if template not in ANTENNA2_TEMPLATES:
        raise KeyError(f"非 antenna2 模板: {template}（可用 {ANTENNA2_TEMPLATES}）")
    meta = dict(ANTENNA2_META[template])
    meta["template"] = template
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(ANTENNA2_NOMINAL[template])
    return meta


def _ant2_layout(
    template: str,
    params: dict[str, Any],
    sub: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """C1 天线族 II 单一事实源（mm）：金属盒 / 端口 / z 网格线 / 元件顶。

    渲染段（_ant2_body）、近场加密（_near_points 分支）、z 网格预算
    （render_script z_mesh_block）与离线审计测试（test_antenna2_templates）
    四方消费——单源防漂移（hairpin _hairpin_layout 同制度）。
    盒元组 = (金属属性名, 盒名, x0, y0, z0, x1, y1, z1)；零厚度面合法
    （官方金属面口径），端口激励向跨度恒 >0（#174）。
    """
    sub = sub or _DEFAULT_SUB
    er = float(sub["er"])
    h = float(sub["h_mm"])
    boxes: list[tuple[str, str, float, float, float, float, float, float]] = []
    ports: list[dict[str, Any]] = []
    z_lines: list[float] = []
    element_top = h
    if template == "monopole":
        w = float(params.get("mon_w_mm", 1.0))
        ln = float(params.get("mon_len_mm", 31.2284))
        g = float(params.get("feed_gap_mm", 2.0))
        if not (ln > 0.0 and w > 0.0 and g > 0.0):
            raise ValueError("monopole 几何须正")
        # 竖直细带：x 向宽 w、y=0 零厚面、z 自馈口顶起 λ0/4
        boxes.append(("monopole_strip", "strip", -w / 2, 0.0, g, w / 2, 0.0, g + ln))
        # 馈口：地面（z=0 PEC 边界）→ 细带底缘（patch 底馈探针同型）
        ports.append({"kind": "lumped", "nr": 1, "R": 50.0,
                      "start_mm": (-w / 2, -w / 2, 0.0),
                      "stop_mm": (w / 2, w / 2, g),
                      "exc_dir": "z", "excite": 1})
        z_lines = [0.0, g, g + ln]
        element_top = g + ln
    elif template == "pifa":
        ln = float(params.get("pifa_l_mm", 11.0785))
        w = float(params.get("pifa_w_mm", 8.0))
        ws = float(params.get("pifa_ws_mm", 2.0))
        back = float(params.get("pin_back_mm", 2.0))
        py = float(params.get("pin_y_mm", w / 4))
        t = 1.0   # 短路板厚/馈针边长（mm）
        if not (ln > 0.0 and w > 0.0 and 0.0 < ws <= w and 0.0 < back < ln
                and 0.0 < py < w):
            raise ValueError("pifa 几何超界")
        # 贴片（z=h 顶面）
        boxes.append(("pifa_patch", "patch", -ln / 2, -w / 2, h, ln / 2, w / 2, h))
        # 短路板（+x 边缘，z 0→h 触地）
        boxes.append(("pifa_short", "short", ln / 2 - t, -ws / 2, 0.0,
                      ln / 2, ws / 2, h))
        # 馈针 = LumpedPort 本身（距短路板 back，y 偏 py；端口顶触贴片、底触地
        # ——patch 官方口径"端口即探针"）。不另画同体积金属针盒：2026-09-14
        # 真机 v1（有针盒）/v2（无针盒）S11 逐点一致，针盒对结果无影响，去掉
        # 只为消除"金属盖端口体元"的口径歧义（回归钉 test_pifa_ifa_feed_pin_
        # and_short_touch_ground_line）。标称 FAIL 的真根因见 ANTENNA2_META 段注
        # （居中短路板 ⇒ 有效路径≈L，L+W−Ws 通式不适用）。
        px = ln / 2 - back
        ports.append({"kind": "lumped", "nr": 1, "R": 50.0,
                      "start_mm": (px - t / 2, py - t / 2, 0.0),
                      "stop_mm": (px + t / 2, py + t / 2, h),
                      "exc_dir": "z", "excite": 1})
        z_lines = [0.0, h]
    elif template == "ifa":
        ln = float(params.get("ifa_arm_mm", 18.5515))
        w = float(params.get("ifa_w_mm", 1.0))
        s = float(params.get("feed_off_mm", 2.0))
        t = 1.0
        if not (ln > 0.0 and w > 0.0 and s > 1.5 * t):
            raise ValueError("ifa 几何超界（馈针须与短路板净距 >1.5mm）")
        # 短路板（x∈[−t,0]，z 0→h 触地）
        boxes.append(("ifa_short", "short", -t, -w / 2, 0.0, 0.0, w / 2, h))
        # 臂（z=h 顶面，自短路板 −x 向伸出 λ/4）
        boxes.append(("ifa_arm", "arm", -ln, -w / 2, h, 0.0, w / 2, h))
        # 馈针 = LumpedPort 本身（x=−s，端口顶触臂、底触地；同 pifa 不另画金属
        # 针盒——真机 v1/v2 逐点一致 −8.5dB@2.44GHz，针盒无影响）
        ports.append({"kind": "lumped", "nr": 1, "R": 50.0,
                      "start_mm": (-s - t / 2, -t / 2, 0.0),
                      "stop_mm": (-s + t / 2, t / 2, h),
                      "exc_dir": "z", "excite": 1})
        z_lines = [0.0, h]
    elif template == "loop":
        a = float(params.get("loop_side_mm", 31.2284))
        w = float(params.get("loop_w_mm", 1.0))
        g = float(params.get("loop_gap_mm", 1.0))
        if not (a > 0.0 and w > 0.0 and 0.0 < g < a):
            raise ValueError("loop 几何须 0 < gap < side")
        # 自由空间口径（2026-09-16 改造）：环面 z=0（dipole 振子面同款，无基板
        # 无地、底 MUR、域 z 向下延 λ0/4——旧 z=h 贴 PEC 地口径镜像抵消辐射
        # R=0.56Ω，见 ANTENNA2_META 段注）。方环（中心线 ±a/2，带宽 w）：顶边/
        # 左右竖边全跨（含角），底边中央断口 g（馈口位）
        zl = 0.0
        boxes.append(("loop_top", "top", -a / 2 - w / 2, a / 2 - w / 2, zl,
                      a / 2 + w / 2, a / 2 + w / 2, zl))
        boxes.append(("loop_left", "left", -a / 2 - w / 2, -a / 2 - w / 2, zl,
                      -a / 2 + w / 2, a / 2 + w / 2, zl))
        boxes.append(("loop_right", "right", a / 2 - w / 2, -a / 2 - w / 2, zl,
                      a / 2 + w / 2, a / 2 + w / 2, zl))
        boxes.append(("loop_bot_l", "bot_l", -a / 2 - w / 2, -a / 2 - w / 2, zl,
                      -g / 2, -a / 2 + w / 2, zl))
        boxes.append(("loop_bot_r", "bot_r", g / 2, -a / 2 - w / 2, zl,
                      a / 2 + w / 2, -a / 2 + w / 2, zl))
        # 馈口跨断口（dipole 中央馈口同型零厚面；激励向 x 跨度 = g > 0）
        ports.append({"kind": "lumped", "nr": 1, "R": 50.0,
                      "start_mm": (-g / 2, -a / 2, zl),
                      "stop_mm": (g / 2, -a / 2, zl),
                      "exc_dir": "x", "excite": 1})
        z_lines = [zl]
        element_top = zl
    elif template == "helix":
        d = float(params.get("helix_d_mm", 3.0))
        n = int(params.get("helix_turns", 2))
        p = float(params.get("helix_pitch_mm", 9.2587))
        w = float(params.get("helix_w_mm", 0.6))
        g = float(params.get("feed_gap_mm", 2.0))
        if not (d > 0.0 and n >= 1 and p >= 1.0 and w > 0.0 and g > 0.0):
            raise ValueError("helix 几何须正且螺距 ≥ 1mm")
        # 单导线连续 staircase 螺旋：每圈 4 直段各占 1/4 螺距上升、
        # 角部竖板连接（无双并联回路——closed-ring+单 riser 拓扑是错画）。
        # 中心线方边 d；角 A=(−d/2,−d/2) B=(+d/2,−d/2) C=(+d/2,+d/2)
        # D=(−d/2,+d/2)；turn k 基平面 z_k = g + k·p（首圈 A 段即馈口顶，
        # 无引入段——总线长恰 = 4dN + Np = λ0/4，设计式精确成立）。
        z_a = g
        for k in range(n):
            za = z_a + k * p
            # A 段（沿 +x，y=−d/2 面，z=za）
            boxes.append(("helix", f"t{k}_a", -d / 2, -d / 2 - w / 2, za,
                          d / 2, -d / 2 + w / 2, za))
            # AB 竖板（角 B，z za→za+p/4）
            boxes.append(("helix", f"t{k}_ab", d / 2 - w / 2, -d / 2, za,
                          d / 2 + w / 2, -d / 2, za + p / 4))
            # B 段（沿 +y，x=+d/2 面，z=za+p/4）
            boxes.append(("helix", f"t{k}_b", d / 2 - w / 2, -d / 2,
                          za + p / 4, d / 2 + w / 2, d / 2, za + p / 4))
            # BC 竖板（角 C）
            boxes.append(("helix", f"t{k}_bc", d / 2 - w / 2, d / 2,
                          za + p / 4, d / 2 + w / 2, d / 2, za + p / 2))
            # C 段（沿 −x，y=+d/2 面，z=za+p/2）
            boxes.append(("helix", f"t{k}_c", -d / 2, d / 2 - w / 2,
                          za + p / 2, d / 2, d / 2 + w / 2, za + p / 2))
            # CD 竖板（角 D）
            boxes.append(("helix", f"t{k}_cd", -d / 2 - w / 2, d / 2,
                          za + p / 2, -d / 2 + w / 2, d / 2, za + 3 * p / 4))
            # D 段（沿 −y，x=−d/2 面，z=za+3p/4；终点接下一圈基面）
            boxes.append(("helix", f"t{k}_d", -d / 2 - w / 2, -d / 2,
                          za + 3 * p / 4, -d / 2 + w / 2, d / 2,
                          za + p))
        ports.append({"kind": "lumped", "nr": 1, "R": 50.0,
                      "start_mm": (-d / 2 - w / 2, -d / 2 - w / 2, 0.0),
                      "stop_mm": (-d / 2 + w / 2, -d / 2 + w / 2, g),
                      "exc_dir": "z", "excite": 1})
        z_lines = [0.0, g]
        for k in range(n):
            base = z_a + k * p
            z_lines += [base + p / 4, base + p / 2, base + 3 * p / 4,
                        base + p]
        element_top = z_a + n * p
    elif template == "slot":
        ln = float(params.get("slot_l_mm", 40.9168))
        ws = float(params.get("slot_w_mm", 2.0))
        wf = float(params.get("feed_w_mm", 1.1134))
        m = float(params.get("feed_margin_mm", 12.0))
        if not (ln > 0.0 and ws > 0.0 and wf > 0.0 and m > 0.0):
            raise ValueError("slot 几何须正")
        # 有限地面（z=0，4 盒拼合、槽区 [±ln/2]×[±ws/2] 留空）
        boxes.append(("slot_gnd", "gnd_ym", -60.0, -60.0, 0.0,
                      60.0, -ws / 2, 0.0))
        boxes.append(("slot_gnd", "gnd_yp", -60.0, ws / 2, 0.0,
                      60.0, 60.0, 0.0))
        boxes.append(("slot_gnd", "gnd_xm", -60.0, -ws / 2, 0.0,
                      -ln / 2, ws / 2, 0.0))
        boxes.append(("slot_gnd", "gnd_xp", ln / 2, -ws / 2, 0.0,
                      60.0, ws / 2, 0.0))
        # 50Ω 微带馈线（z=h 顶面，y 向跨槽居中，两端留 m 馈段给 MSLPort 自画）
        y1 = 60.0 - m
        boxes.append(("slot_feed", "feed_line", -wf / 2, -y1, h,
                      wf / 2, y1, h))
        ports.append({"kind": "msl", "nr": 1, "metal_prop": "slot_feed",
                      "start_mm": (wf / 2, -60.0, h),
                      "stop_mm": (-wf / 2, -y1, 0.0),
                      "prop_dir": "y", "exc_dir": "z", "excite": 1,
                      "meas_shift_mm": m / 3.0})
        ports.append({"kind": "msl", "nr": 2, "metal_prop": "slot_feed",
                      "start_mm": (-wf / 2, 60.0, h),
                      "stop_mm": (wf / 2, y1, 0.0),
                      "prop_dir": "y", "exc_dir": "z", "excite": 0,
                      "meas_shift_mm": m / 3.0})
        z_lines = [0.0, h]
        element_top = h
    else:
        raise ValueError(f"未知 antenna2 模板: {template}")
    return {
        "boxes": boxes,
        "ports": ports,
        "z_lines_mm": sorted(set(z_lines)),
        "element_top_mm": element_top,
        "air_below": template in ("slot", *_ANTENNA2_FREE_SPACE_TEMPLATES),
        "substrate": (template not in _ANTENNA2_TALL_TEMPLATES
                      and template not in _ANTENNA2_FREE_SPACE_TEMPLATES),
        "ground": template not in ("slot", *_ANTENNA2_FREE_SPACE_TEMPLATES),
        "er": er, "h_mm": h,
    }


def _ant2_body(template: str, p: dict[str, Any]) -> str:
    """由 _ant2_layout 单源渲染几何段（金属盒 + 端口 + priority 收口）。

    坐标全部走布局字面量（米），渲染==布局==审计三方一致；单端口模板
    _port2=_port1（patch 单端口 fallback 口径）。
    """
    lay = _ant2_layout(template, p)
    out: list[str] = []
    m = lambda v: repr(float(v) * 1e-3)   # noqa: E731  mm→m 字面量
    metal_names: list[str] = []
    for box in lay["boxes"]:
        prop = box[0]
        if prop not in metal_names:
            metal_names.append(prop)
    for prop in metal_names:
        out.append(f'{prop} = CSX.AddMetal("{prop}")')
    for (prop, name, x0, y0, z0, x1, y1, z1) in lay["boxes"]:
        out.append(f'{prop}.AddBox(({m(x0)}, {m(y0)}, {m(z0)}), '
                   f'({m(x1)}, {m(y1)}, {m(z1)}), priority=10)  # {name}')
    for port in lay["ports"]:
        s, t = port["start_mm"], port["stop_mm"]
        nr = int(port["nr"])
        if port["kind"] == "lumped":
            out.append(
                f'_port{nr} = LumpedPort(CSX, port_nr={nr}, R={port["R"]!r},\n'
                f'                    start=np.array([{m(s[0])}, {m(s[1])}, '
                f'{m(s[2])}]),\n'
                f'                    stop=np.array([{m(t[0])}, {m(t[1])}, '
                f'{m(t[2])}]),\n'
                f'                    exc_dir="{port["exc_dir"]}", '
                f'excite={int(port["excite"])}, priority=5)')
        else:
            out.append(
                f'_port{nr} = MSLPort(CSX, port_nr={nr}, '
                f'metal_prop={port["metal_prop"]},\n'
                f'                 start=np.array([{m(s[0])}, {m(s[1])}, '
                f'{m(s[2])}]),\n'
                f'                 stop=np.array([{m(t[0])}, {m(t[1])}, '
                f'{m(t[2])}]),\n'
                f'                 prop_dir="{port["prop_dir"]}", '
                f'exc_dir="{port["exc_dir"]}", excite={int(port["excite"])},\n'
                f'                 FeedShift=10 * NEAR, '
                f'MeasPlaneShift={float(port["meas_shift_mm"]) * 1e-3!r},\n'
                f'                 priority=10)')
    if len(lay["ports"]) == 1:
        out.append('_port2 = _port1   # 单端口模板：footer fallback 口径')
    for prop in metal_names:
        out.append(f'for _prim in {prop}.GetAllPrimitives():\n'
                   '    if _prim.GetPriority() < 10:\n'
                   '        _prim.SetPriority(10)')
    return "\n".join(out) + "\n"


def _monopole_lines(p: dict[str, Any]) -> str:
    # §10.3 C1 单极子：竖直细带 λ0/4 于 PEC 地面（像理论口径），LumpedPort
    # 底馈（patch 探针同型）；设计式/布局/审计单源 _ant2_layout。
    return _ant2_body("monopole", p)


def _pifa_lines(p: dict[str, Any]) -> str:
    # §10.3 C1 PIFA：贴片+短路板（+x 边）+馈针（patch 底馈同型），
    # 短路板态 λ/4 通式定长（见段首理论核验 2）。
    return _ant2_body("pifa", p)


def _ifa_lines(p: dict[str, Any]) -> str:
    # §10.3 C1 IFA：窄臂+短路板+馈针（PIFA 窄臂退化，λ/4 口径见段首 3）。
    return _ant2_body("ifa", p)


def _loop_lines(p: dict[str, Any]) -> str:
    # §10.3 C1 环形：一周长方环 + 底边中央断口 LumpedPort（dipole 馈口
    # 同型；C≈λ 大环自谐振口径见段首 4）。
    return _ant2_body("loop", p)


def _helix_lines(p: dict[str, Any]) -> str:
    # §10.3 C1 螺旋：单导线 staircase 方螺旋（λ0/4 总线长口径见段首 5；
    # 每圈 4 直段 1/4 螺距逐级上升，无双并联回路）。
    return _ant2_body("helix", p)


def _slot_lines(p: dict[str, Any]) -> str:
    # §10.3 C1 缝隙：有限地面（槽区留空）+ 微带馈线跨槽 + 双 MSLPort
    # （λ0/2 缝谐振口径见段首 6；底 MUR + z 下延由 render_script 专项）。
    return _ant2_body("slot", p)


# ═══════════════════════════════════════════════════════════════════════════════
# §C3 滤波器族 II：interdigital（交指）/ combline（梳状）/ sir_bpf（阶梯阻抗谐振器）
# ——接地棒接地耦合滤波器族三成员（2026-09-15 增量；同日注册进 TEMPLATE_META/
# TEMPLATE_NOMINAL，见段末赋值块；本任务 c3-filter-family-ii #23）
# ═══════════════════════════════════════════════════════════════════════════════
# 拓扑（三族同构）：N 根平行谐振棒 + 两端 50Ω 馈线（缝耦合），双端口均在
# y=−BOARD 板边（gysel 三端口同边先例 → 单轴 y PML）；底 z-min PEC 地。
# - interdigital：λ/4 均匀棒，接地端**交替**（奇棒底端过孔、偶棒顶端过孔，
#   Cohn 交指口径）；无装载电容。
# - combline：缩短棒（θr<π/4 由装载电容定），接地端**同端**（底端全部过孔，
#   MYJ Ch.10 梳状口径），顶端各接 LumpedElement 装载电容 c_load_pf。
# - sir_bpf：λ/4 型阶梯阻抗棒（开路端低阻段 w_low + 接地端高阻段 w_high，
#   同端接地顶端过孔），步进比给出紧凑化（总电长 2θ < π/2），无装载电容。
#
# ── 理论核验轮（口径/来源/独立裁判逐条；#206/#118 纪律，不自证）──
# 1) 原型映射（hairpin §4 既有 C13 口径）：core synthesize_bpf_model（folded）
#    → k_{i,i+1}=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M_{0,1}|²)；经典切比雪夫 g 值
#    （core/matching.chebyshev_g_values）进 notes 互检（N=3/RL20/δ5% 实测
#    Qe 17.0693 vs 矩阵 17.0689、k 0.051513 vs 0.051514，3e-5 级一致）。
# 2) 谐振器并联模型（本族核心近似，MYJ Ch.8/Ch.10/Hong §5.6 邻耦合口径）：
#    棒 = 单端看入的一端口导纳 Y_i(ω)，耦合 = 相邻对 J 倒置器，链 = 馈线—
#    J01—Y_1—J12—…—J_N,N+1—馈线，与 C13 耦合矩阵网络同拓扑。互指/梳状的
#    相邻棒全长耦合本质是多导体系统，两线级联展开不可达（棒全长重叠）——
#    非邻耦合与棒端效应不进模型，由 EM 冒烟实测其总量（假设清单，hairpin
#    /coupled_bpf 同口径）。
# 3) 斜率参数（MYJ 定义 b=(ω0/2)·dB/dω|ω0，并联谐振 Q=b/G）：
#    - λ/4 短路棒（interdigital）：B=−cot θ/Z_r → b=θ0·csc²θ0/(2Z_r)，θ0=π/2
#      → b=π/(4Z_r)（λ/2 开路谐振器 π/(2Z_r) 的一半——存储能量减半）。
#    - 梳状（短路棒+顶端装载电容）：谐振条件 **cot θr = ω0·C·Z_r**（MYJ
#      Ch.10：ω0C−cot(θr)/Z_r=0），b=½(ω0C+csc²θr·θr/Z_r)。
#    - SIR（λ/4 型接地阶梯棒）：谐振条件 **tan θ1·tan θ2 = Z1/Z2**
#      （Z1=开路端低阻段、Z2=接地端高阻段；MYJ SIR 章；本文件由 Z_in=∞
#      的 ABCD 分子零点独立推导）——对称分 θ1=θ2=arctan√(Z1/Z2)，总电长
#      2θ < π/2（紧凑化）。b 闭式 = ω0/2·Σᵢ dY/dtᵢ·(1+tᵢ²)·dθᵢ/dω（推导见
#      函数 docstring），对照数值中心差分实测 rel 3.2e-8（#118）。
# 4) J ↔ (Z0e,Z0o)（Cohn 精确关系，非 Pozar 小 x 近似）：λ/4 平行耦合段
#    开路缩减 2 端口的倒置器值 |J|=(Z0e−Z0o)/(2·Z0e·Z0o)=x/(Z0(1+x²+x⁴))；
#    设计 J → x 经该式 brentq 精确反演（j(x) 在 x²=(√13−1)/6≈0.659 达峰，
#    反演区间限 (0,0.65) 并做可达守卫）；(w,s) 均匀棒口径固定棒宽对 J 一维
#    brentq 反解缝（KJ 1984 内核复用 coupled_microstrip_even_odd_ohm）——
#    规格草案的 coupled_bpf_width_gap_from_zee_zoo 二维反解属边耦合 λ/2
#    级联的逐段变宽口径，本族均匀棒几何只有 (w_bar, s_j) 单自由度，改用
#    一维反解（KJ 内核同源复用；漂移已记 verdict）。
# 5) 电路裁判（三族共用 c3_inverter_chain_sparams）：理想 J 倒置器
#    ABCD=[[0,±j/J],[±jJ,0]] + 并联 Y_i(ω) + 理想 z_ref 馈线（相位按物理长，
#    coupled_bpf 馈线口径），ABCD→S 按 Pozar T4.2（与 coupled_bpf footer
#    同式）。**同步 TEM 极限（J=设计目标值 + 设计电气值理想化）对照 C13
#    coupling_matrix_response 实测：interdigital max|ΔS21|=0.0104dB、
#    combline 0.00045dB、sir_bpf 0.0061dB（N=3/δ5%/RL20）**——链与耦合矩
#    阵两条独立构造互证；几何预测（J 由 KJ(w,s) 闭式回代 + Δl 等效长度进
#    裁判）与同步极限几乎重合（差异=反解闭合误差 1e-6 级）。
# 6) 开路端 Δl（Hammerstad，_open_end_delta_mm 复用）：设计式按等效长度
#    口径（谐振条件对电长成立），物理棒长 = 电长 − Δl；电路裁判以
#    L_phys+Δl 等效长度回代——同源同口径，不再引入二阶失谐（对照
#    coupled_bpf 的物理长直代口径，此处选择等效长度并在 notes 声明）。
# 7) 端口铁律自查：馈线耦合段与棒间隙 s 全程 DC 隔离（PORT_GROUPS
#    (1,)(2,) 缝耦合族判据，N+2 分量）；过孔柱/装载电容盒边全部精确入网
#    （#198/#174）；棒接地端过孔半径 0.15mm（via 基元同款）。
# 8) 接地过孔电感（2026-09-18 w2e，裁判闭式补项；2026-09-22 R1 校准修订）：
#    短路端不是理想短路而是串联 jωL_via 接地。原口径 = Goldfarb & Pucel,
#    "Modeling via hole grounds in microstrip", IEEE Microwave and Guided Wave
#    Letters, vol.1 no.6, pp.135-137, 1991：L_via=(μ0/2π)·h·[ln(4h/d)+1]
#    （via_inductance_h，h=0.508/d=0.3 → 0.29596nH）。**R1 校准（df5-c3fix）**：
#    HFSS interdigital 仲裁反解 0.12–0.13nH（audit2 证据）⇒ G-P 对"连续 PEC
#    地面粗短过孔"高估 2.2–2.5×（SC verdict 次根因：补偿过缩短，峰 +4.1%）；
#    auto（l_via_h=None）改取校准值 C3_L_VIA_CAL_H=0.125nH（HFSS 区间中点，
#    对齐基准立规）；G-P 闭式保留为 via_inductance_h/c3_via_
#    inductance_h 文献公式（离线判别消费者不变）；OE 反解 ≈0.20nH 与 HFSS 差
#    异=跨引擎发现（OE 哨预期承载）。
#    λ/4 短路棒并联谐振条件由 tanθ=∞ 变为 tanθ=Z_r/(ωL_via)（谐振下移）；
#    combline 装载条件 ωC=(1−x·t)/(Z_r(x+t))、SIR 高阻段 Z_B 按 L 端接变换
#    （x=ωL/Z，t=tanθ）。三模板真机峰位 −4.7/−5.15/−4.6%
#    与该项同量级——裁判 c3_circuit_sparams(l_via_h=None) 自动取校准值，
#    l_via_h=0.0（缺省）逐位复现理想短路旧口径。
# 9) 耦合缝网格守卫（#266，c3_gap_mesh_guard）：NEAR=base/4 ≤ 最小耦合缝/3，
#    违反即 render_script 抛 ValueError（缺省 mesh=0 → NEAR 0.285mm > 外缝
#    0.139~0.242mm ⇒ 缝内零内部线、外 Q 建模粗、峰位 −5%，不许静默粗网格）。
# 10) 设计链过孔补偿（登记⑨，纯离线）：谐振棒长按谐振条件**精确解**
#    缩短，使渲染几何在过孔存在下谐振回 f0——
#    - interdigital（λ/4 短路棒）：tanθ_c=Z_r/(ω0 L)（口径 8 谐振条件反解），
#      θ_c=arctan(Z_r/(ω0L))<π/2，物理长=θ_c·c/(ω0√εeff)−Δl_open，即电长按
#      2θ_c/π 比例缩短；
#    - combline（装载电容+过孔）：ω0C=(1−x t)/(Z_r(x+t))（口径 8）解出
#      t=(1−A x)/(A+x)（A=ω0CZ_r=cotθr、x=ω0L/Z_r），θ_c=arctan(t)，C 不变、
#      棒长重解；无正解判据 x≥tanθr（过孔电感超出装载能力）显式报错；
#    - sir_bpf（高阻段过孔端接）：Z_B=jZ_hi(x+t2)/(1−x t2) 代入谐振
#      Z_B=jZ_lo/t1 → t2=(Z_lo−Z_hi t1 x)/(Z_hi t1+Z_lo x)，θ2c=arctan(t2)，低阻
#      段/缝不变、高阻段重解；无正解判据 x Z_hi t1≥Z_lo（t2≤0）显式报错。
#    三族均为**精确谐振条件解**（无 tanθ≈θ 近似），适用域 θ_c∈(0,π/2)
#    （工程有效域 x=ω0L/Z≪1，名义 x≈0.093/0.066）；斜率 b/J/缝仍取理想短路
#    口径——经由孔对 b 为二阶小量（λ/4 族恒等式 θ_c+x/(1+x²)≈π/2，名义点
#    b 相对变化 <0.1%，三族同构）。设计链开关 l_via_h：0.0（缺省）=理想短路
#    **逐字节复现补偿前口径**、None=按几何自动、显式 float=指定电感（H）；
#    补偿生效时设计 dict 增补 l_via_h/theta_c_rad/via_delta_mm 三键。
#    NOMINAL/meta.yaml/synthesizer（template_specs）=校准补偿口径再生（新战役
#    渲染几何谐振回 f0）；fake 同源通道缺省保持理想短路（旧黄金钉保持），
#    过孔裁判经变量 l_via_h（"auto"/数值 H）显式开启。
#
# ── 真机后置（followUp）：openEMS 冒烟不在本项（循 coupled_bpf NrTS
# PARTIAL 先例，真机轨道留 openems-real-smoke-bundle 类包）。

_C3_C_MM_GHZ = 299.792458        # mm·GHz（真空光速，core/_HAIRPIN/_ANT2 同口径）
_C3_Z0 = 50.0                    # 棒/馈线单线设计阻抗（Ω，skrf HJ 精算线宽）
_C3_R_VIA_MM = 0.15              # 接地过孔半径（via 基元同款，渲染常数）
_C3_CAP_LEN_MM = 0.5             # 梳状装载电容 LumpedElement 盒 y 向长（棒顶端内侧）
_C3_COHN_X_MAX = 0.65            # j(x)=x/(Z0(1+x²+x⁴)) 单调区上界（驻点 x≈0.6589）
_C3_GAP_CELLS_MIN = 3.0          # 耦合缝内最少 NEAR 格数（守卫 NEAR ≤ 缝/3，#266）
_MU0_H_PER_M = 4.0e-7 * math.pi  # 真空磁导率（Goldfarb-Pucel 系数 μ0/2π=2e-7）
# 过孔电感校准值（R1，2026-09-22 df5-c3fix）：l_via_h=None（auto）的解析结果。
# 依据 HFSS interdigital 仲裁反解 0.12–0.13nH（runs/hfss_interdigital_check/
# _audit2/audit2_evidence.json：θ(2.60)=1.5350、ωL=1.953Ω@2.60GHz）取区间中点
# 0.125nH——对齐基准立规（HFSS 仲裁）。Goldfarb-Pucel 闭式
# （c3_via_inductance_h，0.29596nH）对"连续 PEC 地面上粗短过孔"高估 2.2–2.5×
# （SC runs/df5_c3_mapping/verdict.json 次根因），降级为文献公式保留；OE 反解
# ≈0.20nH 与 HFSS 的差异如实登记为跨引擎发现（OE 哨预期承载，不进定值）。
C3_L_VIA_CAL_H = 0.125e-9
C3_TEMPLATES: tuple[str, ...] = ("interdigital", "combline", "sir_bpf")

# c3.l_via_h 锚消费（DP-3 第二批改道，df7 锚消费接线）：l_via_h=None（auto）
# 的取值改经 knowledge/anchors.yaml 的 c3.l_via_h.openems-hfss-v1（0.125e-9 H，
# HFSS 仲裁中点，单源=注册表）惰性解析——首次调用 resolve 并缓存模块级变量；
# 注册表缺文件/schema 错/任何异常一律回退字面 C3_L_VIA_CAL_H（best-effort
# #105：渲染主路径永不因锚系统故障阻塞）。锚值与字面值逐位相等
# （test_anchors_core a1 / test_anchor_wire_df7 钉）。
_C3_L_VIA_ANCHOR_ID = "c3.l_via_h.openems-hfss-v1"
_c3_l_via_anchor_ready = False
_c3_l_via_anchor_h_cache: float = C3_L_VIA_CAL_H


def _c3_l_via_anchor_h() -> float:
    """惰性解析 c3.l_via_h 锚（模块级缓存；任何失败回退字面校准值）。

    解析成功条件=注册表命中且 source=anchor 且非 stale 且有限 float；
    其余（未知锚/awaiting_data/域外/stale/装载失败/异常）一律回退
    C3_L_VIA_CAL_H——回退值与锚值逐位相等，零行为变化。"""
    global _c3_l_via_anchor_ready, _c3_l_via_anchor_h_cache
    if not _c3_l_via_anchor_ready:
        _c3_l_via_anchor_ready = True
        try:
            from rfauto.infra.anchors_store import load_anchors

            got = load_anchors().resolve_anchor(_C3_L_VIA_ANCHOR_ID)
            value = got.get("value")
            if (got.get("hit") and got.get("source") == "anchor"
                    and not got.get("stale")
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))):
                _c3_l_via_anchor_h_cache = float(value)
        except Exception:  # best-effort 兜底（#105）
            _c3_l_via_anchor_h_cache = C3_L_VIA_CAL_H
    return _c3_l_via_anchor_h_cache


def via_inductance_h(h_m: float, d_m: float) -> float:
    """接地过孔电感（H）：Goldfarb & Pucel 1991 闭式 L=(μ0/2π)·h·[ln(4h/d)+1]。

    h_m=过孔长（=基板厚），d_m=过孔直径，SI。出处见 §C3 段首口径 8。
    """
    h = float(h_m)
    d = float(d_m)
    if not (h > 0.0 and d > 0.0):
        raise ValueError(f"过孔 h/d 须 >0，得 h={h_m} d={d_m}")
    return _MU0_H_PER_M / (2.0 * math.pi) * h * (math.log(4.0 * h / d) + 1.0)


def c3_via_inductance_h(h_mm: float, r_via_mm: float = _C3_R_VIA_MM) -> float:
    """C3 族接地过孔电感（H）：h=基板厚 h_mm、d=2·r_via_mm（渲染常数同源）。"""
    return via_inductance_h(float(h_mm) * 1e-3, 2.0 * float(r_via_mm) * 1e-3)


def _c3_via_resolved_h(l_via_h: float | None, h_mm: float) -> float:
    """设计链过孔电感三态解析（口径 10+R1 校准）：0.0=理想短路（缺省，逐字节
    复现补偿前口径）、None=按校准值 C3_L_VIA_CAL_H（HFSS 仲裁 0.125nH；原
    Goldfarb-Pucel 几何值高估，见常量注）、显式 float=指定（H）。"""
    lv = _c3_l_via_anchor_h() if l_via_h is None else float(l_via_h)
    if lv < 0.0:
        raise ValueError(f"l_via_h 须 ≥0，得 {l_via_h}")
    return lv


def c3_mesh_max_mm(template: str, params: dict[str, Any]) -> float:
    """耦合缝网格守卫的 mesh_resolution_mm 上限（mm）：NEAR=base/4 ≤ 缝_min/3
    ⇒ base ≤ 4·缝_min/3（缝取 gaps_mm 列表最小值，边到边）。"""
    gaps = _c3_gaps_from_params(template, params)
    return 4.0 * min(gaps) / _C3_GAP_CELLS_MIN


def c3_gap_mesh_guard(template: str, params: dict[str, Any],
                      near_m: float) -> dict[str, float]:
    """耦合缝网格守卫（#266）：NEAR ≤ 最小耦合缝/3，违反即抛 ValueError。

    返回 {min_gap_mm, near_mm, near_max_mm, mesh_max_mm}（渲染前断言，
    不许静默粗网格；mesh_max_mm=4·缝_min/3 即合规的 mesh_resolution_mm 上限）。
    """
    if template not in C3_TEMPLATES:
        raise ValueError(f"非 C3 模板: {template}")
    gaps = _c3_gaps_from_params(template, params)
    min_gap = float(min(gaps))
    near_mm = float(near_m) * 1e3
    near_max = min_gap / _C3_GAP_CELLS_MIN
    info = {"min_gap_mm": min_gap, "near_mm": near_mm,
            "near_max_mm": near_max, "mesh_max_mm": 4.0 * near_max}
    if near_mm > near_max * (1.0 + 1e-9):
        raise ValueError(
            f"C3 {template} 耦合缝网格守卫（#266）：NEAR={near_mm:.4f}mm > "
            f"最小耦合缝 {min_gap:.4f}mm/3={near_max:.4f}mm（缝内不足 "
            f"{_C3_GAP_CELLS_MIN:g} 格 ⇒ 缝内零内部线、外 Q 建模粗、峰位 −5%）；"
            f"请显式传 mesh_resolution_mm ≤ {4.0 * near_max:.4f}（NEAR=base/4）")
    return info


def c3_cohn_j_from_x(x: float, z0: float = _C3_Z0) -> float:
    """λ/4 平行耦合段（开路缩减）倒置器值的 Cohn 精确式：J=x/(Z0(1+x²+x⁴))。

    x=归一化耦合参数；Pozar §8.6 小 x 近似 J≈x/Z0 的精确版（x²+x⁴ 项即
    J 倒置器 λ/4 实现的二阶修正来源）。
    """
    x = float(x)
    if x <= 0.0:
        raise ValueError(f"x 须 >0，得 {x}")
    return x / (float(z0) * (1.0 + x * x + x ** 4))


def c3_cohn_x_from_j(j_s: float, z0: float = _C3_Z0) -> float:
    """Cohn 精确式反演：J → x（brentq；j(x) 在 x≈0.659 达峰，区间限峰前单调段）。"""
    from scipy.optimize import brentq

    j = float(j_s)
    if not 0.0 < j < c3_cohn_j_from_x(_C3_COHN_X_MAX, z0):
        raise ValueError(
            f"J={j:.6f} S 超出 Cohn 单调区可达上限 "
            f"{c3_cohn_j_from_x(_C3_COHN_X_MAX, z0):.6f} S（x<{_C3_COHN_X_MAX}）")
    return float(brentq(lambda x: c3_cohn_j_from_x(x, z0) - j,
                        1e-12, _C3_COHN_X_MAX, xtol=1e-12))


def _c3_x_diag(j_list: list[float], z0: float = _C3_Z0) -> list[float | None]:
    """Cohn 精确 x 诊断量：J 超单支可达上限（x>0.65 峰后）记 None，不阻塞设计——
    缝隙由 J 直接经 KJ 一维反解（x 只进 notes/互检，不进几何）。"""
    out: list[float | None] = []
    for j in j_list:
        try:
            out.append(c3_cohn_x_from_j(j, z0))
        except ValueError:
            out.append(None)
    return out


def _c3_fmt_x(xs: list[float | None]) -> str:
    return "[" + ", ".join("n/a" if v is None else f"{v:.5f}" for v in xs) + "]"


def c3_coupling_j_from_gap(w_mm: float, s_mm: float, freq_ghz: float,
                           er: float = 3.66,
                           h_mm: float = 0.508) -> tuple[float, float]:
    """耦合缝 → 倒置器值 |J|=(Z0e−Z0o)/(2 Z0e Z0o)（S）与该段 εeff 均值（KJ 口径）。"""
    ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
        w_mm, s_mm, freq_ghz, er, h_mm)
    return (ze - zo) / (2.0 * ze * zo), 0.5 * (ere_e + ere_o)


def c3_gap_from_coupling_j(j_target_s: float, w_mm: float, freq_ghz: float,
                           er: float = 3.66, h_mm: float = 0.508,
                           s_lo_mm: float = 0.02,
                           s_hi_mm: float = 30.0) -> float:
    """倒置器值 → 耦合缝（固定棒宽一维 brentq；J(s) 单调递减，实测钉住）。"""
    from scipy.optimize import brentq

    j = float(j_target_s)
    if j <= 0.0:
        raise ValueError(f"J 须 >0，得 {j}")
    if not w_mm > 0.0:
        raise ValueError(f"棒宽须 >0，得 {w_mm}")

    def _residual(s_mm: float) -> float:
        return c3_coupling_j_from_gap(w_mm, s_mm, freq_ghz, er, h_mm)[0] - j

    f_lo = _residual(s_lo_mm)
    f_hi = _residual(s_hi_mm)
    if f_lo <= 0.0 or f_hi >= 0.0:
        raise ValueError(
            f"J={j:.6f} S 超出 {w_mm:.4f}mm 棒宽可达范围 "
            f"[{_residual(s_hi_mm) + j:.6f}, {_residual(s_lo_mm) + j:.6f}] S"
            f"（缝 {s_lo_mm}~{s_hi_mm}mm）")
    return float(brentq(_residual, s_lo_mm, s_hi_mm, xtol=1e-9))


def _c3_single_line(w_mm: float, freq_ghz: float, er: float,
                    h_mm: float) -> tuple[float, float]:
    """单线 (Z0, εeff)（skrf HJ 正向，铁律 1c 唯一线宽/介质口径）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="c3", epsilon_r=float(er), thickness_mm=float(h_mm))
    z0, ere = forward_z0(float(w_mm), float(freq_ghz), stackup)
    return float(z0), float(ere)


def _c3_theta(f_ghz: float, ere: float, len_mm: float) -> float:
    """电长度 θ=2πf√εeff·L/c（rad）。"""
    return (2.0 * math.pi * float(f_ghz) * 1e9 * math.sqrt(float(ere))
            * float(len_mm) * 1e-3 / 299792458.0)


# ─── 三族谐振器一端口导纳 Y(ω)（并联倒置器链的谐振臂）────────────────────────

def _c3_via_terminated_short(f_ghz: float, z_r: float, t: float,
                             l_via_h: float) -> complex:
    """经过孔电感接地的传输线段看入阻抗 Z_in=Z_r(jωL+jZ_r t)/(Z_r−ωL t)（t=tanθ）。

    并联谐振点（分母=0）返回 inf（Y=0）；串联谐振点（分子=0）返回 0（调用方判奇异）。
    """
    xl = 2.0 * math.pi * float(f_ghz) * 1e9 * float(l_via_h)
    z = float(z_r)
    den = z - xl * t
    if den == 0.0:
        return complex(math.inf)
    return z * 1j * (xl + z * t) / den


def c3_y_shorted_stub(f_ghz: float, ere: float, len_mm: float,
                      z_r: float, l_via_h: float = 0.0) -> complex:
    """λ/4 短路棒（interdigital）：Y=1/(jZ_r tanθ)=−j·cotθ/Z_r（开路端看入）。

    l_via_h=接地过孔电感（H，§C3 口径 8）：短路端串联 jωL 接地，
    Z_in=Z_r(jωL+jZ_r tanθ)/(Z_r−ωL tanθ)（谐振条件 tanθ=Z_r/(ωL)）；
    0.0（缺省）走原理想短路表达式（逐位复现旧口径）。
    """
    th = _c3_theta(f_ghz, ere, len_mm)
    t = math.tan(th)
    if float(l_via_h) < 0.0:
        raise ValueError(f"l_via_h 须 ≥0，得 {l_via_h}")
    if float(l_via_h) == 0.0:
        if abs(t) < 1e-12:
            raise ValueError("tan θ≈0（棒长为半波长整数倍），导纳奇异")
        return -1j / t / float(z_r)
    z_in = _c3_via_terminated_short(f_ghz, z_r, t, float(l_via_h))
    if z_in == complex(math.inf):
        return 0j
    if abs(z_in) == 0.0:
        raise ValueError("Z_in=0（过孔电感与棒串联谐振点），导纳奇异")
    return 1.0 / z_in


def c3_y_combline(f_ghz: float, ere: float, len_mm: float, z_r: float,
                  c_f: float, l_via_h: float = 0.0) -> complex:
    """梳状：Y=jωC−j·cotθ/Z_r（短路棒顶端并联装载电容；谐振 ω0C=cotθr/Z_r）。

    l_via_h≠0 时短路棒项换用过孔电感端接式（c3_y_shorted_stub 同口径）。
    """
    return (1j * 2.0 * math.pi * float(f_ghz) * 1e9 * float(c_f)
            + c3_y_shorted_stub(f_ghz, ere, len_mm, z_r, l_via_h))


def c3_y_sir(f_ghz: float, ere_lo: float, l_lo_mm: float, z_lo: float,
             ere_hi: float, l_hi_mm: float, z_hi: float,
             l_via_h: float = 0.0) -> complex:
    """λ/4 型接地 SIR：Y=1/Z_in，Z_in=Z_lo(Z_B+jZ_lo tanθ1)/(Z_lo+jZ_B tanθ1)，
    Z_B=jZ_hi tanθ2（高阻段接地端看入）。

    谐振（Y=0 ⟺ Z_in=∞ ⟺ ABCD 分子 Z_lo−Z_hi·tanθ1·tanθ2=0）即
    **tan θ1·tan θ2 = Z_lo/Z_hi**（MYJ SIR 章条件；#118 独立裁判：对
    |Y(ω)| 数值极小化定位谐振，与闭式逐位一致，单测钉住）。

    l_via_h≠0：高阻段接地端经过孔电感端接，Z_B=Z_hi(jωL+jZ_hi t2)/(Z_hi−ωL t2)
    （§C3 口径 8）；0.0（缺省）走原表达式。
    """
    t1 = math.tan(_c3_theta(f_ghz, ere_lo, l_lo_mm))
    t2 = math.tan(_c3_theta(f_ghz, ere_hi, l_hi_mm))
    if float(l_via_h) < 0.0:
        raise ValueError(f"l_via_h 须 ≥0，得 {l_via_h}")
    if float(l_via_h) == 0.0:
        z_b = 1j * float(z_hi) * t2
    else:
        z_b = _c3_via_terminated_short(f_ghz, z_hi, t2, float(l_via_h))
        if z_b == complex(math.inf):
            # 高阻段自身并联谐振：Z_B=∞ → Z_in=Z_lo/(j tanθ1)（开路端接式极限）
            if abs(t1) < 1e-12:
                raise ValueError("Z_B=∞ 且 tanθ1≈0，导纳奇异")
            return 1j * t1 / float(z_lo)
    z_lo_c = complex(float(z_lo))
    z_in = z_lo_c * (z_b + 1j * z_lo_c * t1) / (z_lo_c + 1j * z_b * t1)
    if abs(z_in) == 0.0:
        raise ValueError("Z_in=0（SIR 串联谐振点），导纳奇异")
    return 1.0 / z_in


# ─── 斜率参数 b（MYJ 定义 b=(ω0/2)·dB/dω|ω0；并联谐振 Q=b/G）────────────────

def c3_slope_shorted_stub(z_r: float, theta0: float = math.pi / 2) -> float:
    """λ/4 短路棒斜率 b=θ0·csc²θ0/(2Z_r)（θ0=π/2 → π/(4Z_r)；λ/2 谐振器的一半）。"""
    if not 0.0 < float(theta0) < math.pi:
        raise ValueError(f"theta0 须在 (0,π)，得 {theta0}")
    return float(theta0) / (math.sin(float(theta0)) ** 2) / (2.0 * float(z_r))


def combline_theta_r(f0_ghz: float, c_pf: float, z_r: float) -> float:
    """梳状谐振电长 θr=arctan(1/(ω0·C·Z_r))（闭式 cot θr = ω0 C Z_r 反演）。"""
    c_f = float(c_pf) * 1e-12
    if not c_f > 0.0:
        raise ValueError(f"c_load_pf 须 >0，得 {c_pf}")
    cot_th = 2.0 * math.pi * float(f0_ghz) * 1e9 * c_f * float(z_r)
    return math.atan2(1.0, cot_th)


def c3_slope_combline(f0_ghz: float, c_pf: float, z_r: float,
                      theta_r: float) -> float:
    """梳状斜率 b=½(ω0C + csc²θr·θr/Z_r)（B=ωC−cotθ/Z_r 的 MYJ 斜率闭式）。"""
    c_f = float(c_pf) * 1e-12
    csc2 = 1.0 + 1.0 / math.tan(float(theta_r)) ** 2
    return 0.5 * (2.0 * math.pi * float(f0_ghz) * 1e9 * c_f
                  + csc2 * float(theta_r) / float(z_r))


def sir_theta_symmetric(z_lo: float, z_hi: float) -> float:
    """对称分θ 的 SIR 谐振角 θ=arctan√(Z_lo/Z_hi)（tanθ1tanθ2=Z_lo/Z_hi、θ1=θ2）。"""
    if not (float(z_lo) > 0.0 and float(z_hi) > 0.0):
        raise ValueError("Z_lo/Z_hi 须正")
    return math.atan(math.sqrt(float(z_lo) / float(z_hi)))


def c3_slope_sir(f0_ghz: float, z_lo: float, ere_lo: float, l_lo_mm: float,
                 z_hi: float, ere_hi: float, l_hi_mm: float) -> float:
    """SIR 斜率 b（闭式；对照数值中心差分实测 rel 3.2e-8，#118）。

    推导：Y=(Z_lo−Z_hi t1 t2)/(j Z_lo(Z_hi t2+Z_lo t1))（t=tan θ，谐振点分子
    N=0），dY/dtᵢ=Nᵢ/D（N=0 消去分子导数），N₁=−Z_hi t2、N₂=−Z_hi t1，
    D=j Z_lo(Z_hi t2+Z_lo t1)；dB/dω=Σᵢ (dY/dtᵢ)·(1+tᵢ²)·dθᵢ/dω，b=ω0/2·Im(dB/dω)。
    """
    w0 = 2.0 * math.pi * float(f0_ghz) * 1e9
    t1 = math.tan(_c3_theta(f0_ghz, ere_lo, l_lo_mm))
    t2 = math.tan(_c3_theta(f0_ghz, ere_hi, l_hi_mm))
    a1 = math.sqrt(float(ere_lo)) * float(l_lo_mm) * 1e-3 / 299792458.0
    a2 = math.sqrt(float(ere_hi)) * float(l_hi_mm) * 1e-3 / 299792458.0
    xd = float(z_lo) * (float(z_hi) * t2 + float(z_lo) * t1)
    if xd == 0.0:
        raise ValueError("SIR 斜率分母为零（分θ 退化）")
    dy_dt1 = 1j * float(z_hi) * t2 / xd
    dy_dt2 = 1j * float(z_hi) * t1 / xd
    db_dw = (dy_dt1 * (1.0 + t1 * t1) * a1
             + dy_dt2 * (1.0 + t2 * t2) * a2).imag
    return 0.5 * w0 * db_dw


# ─── 原型映射与倒置器链（三族共用）────────────────────────────────────────────

def _c3_prototype(order: int, f0_ghz: float, fbw: float,
                  rl_db: float) -> dict[str, Any]:
    """C13 原型量（core 数值内核，零自产数字）：g 值/k 列表/端部 Q_e/耦合矩阵。"""
    from rfauto.core.matching import chebyshev_g_values
    from rfauto.core.synthesis import synthesize_bpf_model

    n = int(order)
    if n < 1:
        raise ValueError(f"order={order} 须 ≥1")
    if not 0.0 < float(fbw) <= 1.0:
        raise ValueError(f"fbw={fbw} 须在 (0,1]")
    if float(rl_db) <= 0.0:
        raise ValueError(f"rl_db={rl_db} 须 >0")
    ripple_db = 10.0 * math.log10(1.0 + 1.0 / (10.0 ** (float(rl_db) / 10.0)
                                                - 1.0))
    g_list = chebyshev_g_values(n, ripple_db)
    synth = synthesize_bpf_model(order=n, f0_ghz=float(f0_ghz),
                                 fbw=float(fbw), rl_db=float(rl_db),
                                 topology="folded")
    if not synth.get("ok"):
        raise ValueError(f"C13 综合失败: {synth.get('errors')}")
    import numpy as _np

    arr = _np.asarray(synth["coupling_matrix"], dtype=float)
    if arr.ndim == 3:                       # [re, im] 对（复元素）
        arr = _np.hypot(arr[..., 0], arr[..., 1])
    k_list = [float(fbw) * float(arr[i, i + 1]) for i in range(1, n)]
    qe_in = 1.0 / (float(fbw) * float(arr[0, 1]) ** 2)
    qe_out = 1.0 / (float(fbw) * float(arr[n, n + 1]) ** 2)
    return {"order": n, "g_list": g_list, "k_list": k_list,
            "qe_in": qe_in, "qe_out": qe_out,
            "coupling_matrix": synth["coupling_matrix"]}


def _c3_j_targets(b_list: list[float], proto: dict[str, Any],
                  z0: float = _C3_Z0) -> list[float]:
    """谐振器斜率 + k/Q_e → 倒置器目标值 [J01, J12.., J_N,N+1]（S）。

    J_mid=k·√(b_i b_j)、J01=√(b_1/(Q_e Z0))（Q=b/G 并联口径，MYJ）；
    b 的整体标度在 k=J/√(bb)、Q=b/(J²Z0) 中相消——链频响只由 k/Q_e 决定，
    b 精度只影响缝隙可实现性（不进频响）。
    """
    b = [float(v) for v in b_list]
    if len(b) != len(proto["k_list"]) + 1:
        raise ValueError(f"b_list 长度须为 order={len(proto['k_list']) + 1}，得 {len(b)}")
    out = [math.sqrt(b[0] / (float(proto["qe_in"]) * z0))]
    for i, k_val in enumerate(proto["k_list"]):
        out.append(float(k_val) * math.sqrt(b[i] * b[i + 1]))
    out.append(math.sqrt(b[-1] / (float(proto["qe_out"]) * z0)))
    return out


def c3_inverter_chain_sparams(freq_ghz: Any, j_list: list[float],
                              y_fns: list[Any], feed_len_mm: float,
                              z_ref: float = 50.0) -> np.ndarray:
    """并联谐振器 J 倒置器链电路裁判（三族共用）：(n, 2, 2) 复数 S。

    链 = 馈线 — J01 — Y_1 — J12 — … — Y_N — J_N,N+1 — 馈线；J 倒置器
    ABCD=[[0, j/J],[jJ, 0]]、并联元 [[1,0],[Y,1]]、馈线=理想 z_ref 线
    （相位按物理长，coupled_bpf 口径）；ABCD→S 按 Pozar T4.2（与
    coupled_bpf_circuit_sparams footer 同式）。无耗/互易由构造保证（单测）。
    """
    import numpy as _np

    freqs = _np.atleast_1d(_np.asarray(freq_ghz, dtype=float))
    j_inv = [float(v) for v in j_list]
    if len(j_inv) != len(y_fns) + 1:
        raise ValueError(f"j_list 长度须为谐振器数+1，得 {len(j_inv)}/{len(y_fns)}")
    if any(v <= 0.0 for v in j_inv):
        raise ValueError("J 须 >0")
    if not float(feed_len_mm) > 0.0:
        raise ValueError("feed_len_mm 须 >0")
    out = _np.zeros((len(freqs), 2, 2), dtype=complex)
    for k_f, f_ghz in enumerate(freqs):
        ph = 2.0 * math.pi * float(f_ghz) * 1e9 / 299792458.0
        t_total = _abcd_line(z_ref, ph * float(feed_len_mm) * 1e-3)
        for i, y_fn in enumerate(y_fns):
            j_i = j_inv[i]
            t_inv = _np.array([[0.0, 1j / j_i], [1j * j_i, 0.0]],
                              dtype=complex)
            t_total = t_total @ t_inv @ _np.array(
                [[1.0, 0.0], [complex(y_fn(float(f_ghz))), 1.0]],
                dtype=complex)
        j_n = j_inv[-1]
        t_total = (t_total @ _np.array([[0.0, 1j / j_n], [1j * j_n, 0.0]],
                                       dtype=complex)
                   @ _abcd_line(z_ref, ph * float(feed_len_mm) * 1e-3))
        a_, b_, c_, d_ = (t_total[0, 0], t_total[0, 1], t_total[1, 0],
                          t_total[1, 1])
        den = a_ + b_ / z_ref + c_ * z_ref + d_
        out[k_f] = [[(a_ + b_ / z_ref - c_ * z_ref - d_) / den, 2.0 / den],
                    [2.0 * (a_ * d_ - b_ * c_) / den,
                     (d_ + b_ / z_ref - c_ * z_ref - a_) / den]]
    return out


def _c3_yfns_from_design(template: str, design: dict[str, Any],
                         l_via_h: float = 0.0) -> list:
    """同步 TEM 极限谐振臂（设计电气值理想化：无 Δl、阻抗/介质取设计值）。

    l_via_h=接地过孔电感（H，§C3 口径 8；0.0=理想短路）。
    """
    n = int(design["order"])
    lv = float(l_via_h)
    if template == "interdigital":
        z_r = float(design["z_r_ohm"])
        ere = float(design["ere"])
        l_quarter = float(design["lg_quarter_mm"])

        def _y(f: float) -> complex:
            return c3_y_shorted_stub(f, ere, l_quarter, z_r, lv)
    elif template == "combline":
        z_r = float(design["z_r_ohm"])
        ere = float(design["ere"])
        l_res = float(design["res_len_mm"])
        c_f = float(design["c_load_pf"]) * 1e-12

        def _y(f: float) -> complex:
            return c3_y_combline(f, ere, l_res, z_r, c_f, lv)
    elif template == "sir_bpf":
        z_lo = float(design["z_lo_ohm"])
        z_hi = float(design["z_hi_ohm"])
        ere_lo = float(design["ere_lo"])
        ere_hi = float(design["ere_hi"])
        l_lo = float(design["l_lo_elec_mm"])
        l_hi = float(design["l_high_mm"])

        def _y(f: float) -> complex:
            return c3_y_sir(f, ere_lo, l_lo, z_lo, ere_hi, l_hi, z_hi, lv)
    else:
        raise ValueError(f"未知 C3 模板: {template}")
    return [_y for _ in range(n)]


def _c3_jlist_from_geometry(template: str, params: dict[str, Any],
                            f0_ghz: float, er: float,
                            h_mm: float) -> list[float]:
    """几何 → 倒置器值（KJ 闭式回代；缝隙列表与渲染同索引同语义 #154）。"""
    gaps = _c3_gaps_from_params(template, params)
    w_c = float(params.get("w_mm", params.get("w_low_mm")))  # 耦合区棒宽
    return [c3_coupling_j_from_gap(w_c, float(s), float(f0_ghz), er, h_mm)[0]
            for s in gaps]


def _c3_gaps_from_params(template: str, params: dict[str, Any]) -> list[float]:
    """参数表 → 缝列表（默认表仅名义 order 可省略，与 _coupled_bpf_layout 同规）。"""
    nom = TEMPLATE_NOMINAL[template]
    n = int(params.get("order", nom["order"]))
    if n < 1:
        raise ValueError(f"order={n} 须 ≥1")
    raw = params.get("gaps_mm")
    if raw is None:
        if n != int(nom["order"]):
            raise ValueError(
                f"order={n} 须随 gaps_mm 列表（默认表仅 order={nom['order']}）")
        raw = nom["gaps_mm"]
    gaps = [float(v) for v in raw]
    if len(gaps) != n + 1:
        raise ValueError(f"gaps_mm 长度须为 order+1={n + 1}，得 {len(gaps)}")
    if any(v <= 0.0 for v in gaps):
        raise ValueError("gaps_mm 须 >0")
    return gaps


def _c3_yfns_from_geometry(template: str, params: dict[str, Any],
                           f0_ghz: float, er: float,
                           h_mm: float, l_via_h: float = 0.0) -> list:
    """几何预测谐振臂（HJ 阻抗/介质 + Δl 等效长度，与渲染同参数口径）。

    l_via_h=接地过孔电感（H，§C3 口径 8；0.0=理想短路）。
    """
    n = int(params.get("order", TEMPLATE_NOMINAL[template]["order"]))
    lv = float(l_via_h)
    if template == "interdigital":
        w = float(params.get("w_mm", TEMPLATE_NOMINAL["interdigital"]["w_mm"]))
        z_r, ere = _c3_single_line(w, float(f0_ghz), er, h_mm)
        res_len = float(params.get("res_len_mm",
                                   TEMPLATE_NOMINAL["interdigital"]["res_len_mm"]))
        dl = _open_end_delta_mm(w, float(f0_ghz), er, h_mm)
        l_eff = res_len + dl          # Δl 等效长度口径（段首口径 6）

        def _y(f: float) -> complex:
            return c3_y_shorted_stub(f, ere, l_eff, z_r, lv)
    elif template == "combline":
        nom = TEMPLATE_NOMINAL["combline"]
        w = float(params.get("w_mm", nom["w_mm"]))
        z_r, ere = _c3_single_line(w, float(f0_ghz), er, h_mm)
        res_len = float(params.get("res_len_mm", nom["res_len_mm"]))
        c_f = float(params.get("c_load_pf", nom["c_load_pf"])) * 1e-12

        def _y(f: float) -> complex:
            return c3_y_combline(f, ere, res_len, z_r, c_f, lv)
    elif template == "sir_bpf":
        nom = TEMPLATE_NOMINAL["sir_bpf"]
        w_lo = float(params.get("w_low_mm", nom["w_low_mm"]))
        w_hi = float(params.get("w_high_mm", nom["w_high_mm"]))
        z_lo, ere_lo = _c3_single_line(w_lo, float(f0_ghz), er, h_mm)
        z_hi, ere_hi = _c3_single_line(w_hi, float(f0_ghz), er, h_mm)
        l_lo = float(params.get("l_low_mm", nom["l_low_mm"]))
        l_hi = float(params.get("l_high_mm", nom["l_high_mm"]))
        dl = _open_end_delta_mm(w_lo, float(f0_ghz), er, h_mm)
        l_lo_eff = l_lo + dl          # 低阻段开路端 Δl 等效长度

        def _y(f: float) -> complex:
            return c3_y_sir(f, ere_lo, l_lo_eff, z_lo, ere_hi, l_hi, z_hi, lv)
    else:
        raise ValueError(f"未知 C3 模板: {template}")
    return [_y for _ in range(n)]


def c3_circuit_sparams(template: str, freq_ghz: Any, params: dict[str, Any],
                       *, synchronous_tem: bool = False,
                       design: dict[str, Any] | None = None,
                       f0_ghz: float = 2.5, er: float = 3.66,
                       h_mm: float = 0.508,
                       z_ref: float = 50.0,
                       l_via_h: float | None = 0.0) -> np.ndarray:
    """C3 滤波器族电路裁判：synchronous_tem=True 走设计理想值（须传 design，
    对照 C13 互证锚），否则由几何参数 KJ 闭式回代（fake 同源通道，#154
    缝列表同索引同语义）。

    l_via_h=接地过孔电感（H，§C3 口径 8，Goldfarb-Pucel 1991 闭式经 HFSS 仲裁
    校准，R1）：
    0.0（缺省）=理想短路（逐位复现旧口径，fake 同源/设计闭合测试不变）；
    None=按校准值 C3_L_VIA_CAL_H（HFSS 仲裁 0.125nH，真机裁判口径，冒烟判读用；
    原 auto=Goldfarb-Pucel 几何值 0.29596nH 系高估已弃）；
    显式 float=指定电感（H）。
    """
    if template not in C3_TEMPLATES:
        raise ValueError(f"非 C3 模板: {template}")
    lv = _c3_l_via_anchor_h() if l_via_h is None else float(l_via_h)
    if lv < 0.0:
        raise ValueError(f"l_via_h 须 ≥0，得 {l_via_h}")
    if synchronous_tem:
        if design is None:
            raise ValueError("synchronous_tem=True 须传 design（设计理想值）")
        j_list = [float(v) for v in design["j_targets"]]
        y_fns = _c3_yfns_from_design(template, design, lv)
        feed_len = float(design["feed_len_mm"])
    else:
        j_list = _c3_jlist_from_geometry(template, params, float(f0_ghz),
                                         er, h_mm)
        y_fns = _c3_yfns_from_geometry(template, params, float(f0_ghz), er,
                                       h_mm, lv)
        feed_len = float(params.get(
            "feed_len_mm", TEMPLATE_NOMINAL[template]["feed_len_mm"]))
    return c3_inverter_chain_sparams(freq_ghz, j_list, y_fns, feed_len, z_ref)


# ─── interdigital（交指）设计链 ──────────────────────────────────────────────

def interdigital_design_from_order(
    order: int, f0_ghz: float = 2.5, fbw: float = 0.05, rl_db: float = 20.0,
    *, er: float = 3.66, h_mm: float = 0.508,
    l_via_h: float | None = 0.0,
) -> dict[str, Any]:
    """交指带通综合链：C13 原型 → MYJ 斜率 → J 目标 → Cohn 精确 x → KJ 反解缝。

    棒 = 50Ω 单线（HJ 精算），电长 λ/4（εeff 取单线 HJ），物理长减一个开路
    端 Δl（接地端无 Δl）；确定性映射（矩阵综合在 core，本函数只做几何映射，
    口径见段首）。l_via_h≠0 时棒长按过孔谐振条件精确解缩短（口径 10：
    tanθ_c=Z_r/(ω0L) → 电长 2θ_c/π 比例），缺省 0.0 逐字节复现理想短路口径。
    """
    from rfauto.core.synthesis import Stackup as _Stackup
    from rfauto.core.synthesis import inverse_width

    n = int(order)
    proto = _c3_prototype(n, float(f0_ghz), float(fbw), float(rl_db))
    w = float(inverse_width(_C3_Z0, float(f0_ghz),
                            _Stackup(name="interdigital", epsilon_r=float(er),
                                     thickness_mm=float(h_mm)))[0])
    z_r, ere = _c3_single_line(w, float(f0_ghz), er, h_mm)
    b = c3_slope_shorted_stub(z_r)
    j_list = _c3_j_targets([b] * n, proto)
    x_list = _c3_x_diag(j_list)
    gaps = [c3_gap_from_coupling_j(v, w, float(f0_ghz), er, h_mm)
            for v in j_list]
    lg_quarter = _C3_C_MM_GHZ / (4.0 * float(f0_ghz) * math.sqrt(ere))
    dl = _open_end_delta_mm(w, float(f0_ghz), er, h_mm)
    res_len = lg_quarter - dl
    lv = _c3_via_resolved_h(l_via_h, h_mm)
    via: dict[str, Any] = {}
    if lv > 0.0:
        # 过孔补偿（口径 10，谐振条件精确解）：过孔端接短路棒 Z_in=Z_r(jωL+jZ_r
        # tanθ)/(Z_r−ωL tanθ)（_c3_via_terminated_short），并联谐振 Z_in→∞ ⇔
        # 分母=0 ⇔ tanθ_c=Z_r/(ω0L)，θ_c=arctan(Z_r/(ω0L))<π/2——电长自 π/2 缩至
        # θ_c（Δl_via=λ/4·(1−2θ_c/π)），物理长=θ_c·c/(ω0√εeff)−Δl_open。精确解
        # （无 tanθ≈θ 近似）；θ_c∈(0,π/2) 对任意 x=ω0L/Z_r>0 有正解，工程有效域
        # x≪1（名义 x≈0.093）。斜率/J/缝取理想短路口径（b 二阶：θ_c+x/(1+x²)≈π/2）。
        theta_c = math.atan(z_r / (2.0 * math.pi * float(f0_ghz) * 1e9 * lv))
        l_elec = lg_quarter * (2.0 * theta_c / math.pi)
        res_len_via = l_elec - dl
        if not res_len_via > 0.0:
            raise ValueError(
                f"过孔补偿后棒长 {res_len_via:.4f}mm ≤0（l_via_h={lv:.3e} H 过大）")
        via = {"l_via_h": lv, "theta_c_rad": theta_c,
               "via_delta_mm": lg_quarter - l_elec}
        res_len = res_len_via
    feed_len = 60.0 - res_len / 2.0        # 阵列 y 居中 ⇒ 两馈等长
    if not 5.0 < feed_len < 60.0:
        raise ValueError(f"feed_len={feed_len:.2f}mm 越界（棒阵列超出 60mm 板）")
    sections = [{"j_target_s": jv, "x": xv, "s_mm": sv,
                 "j_realized_s": c3_coupling_j_from_gap(
                     w, sv, float(f0_ghz), er, h_mm)[0]}
                for jv, xv, sv in zip(j_list, x_list, gaps, strict=True)]
    notes = [
        f"C13 folded N={n}：k={_fmt_list(proto['k_list'], 5)}，"
        f"Q_e={proto['qe_in']:.4f}/{proto['qe_out']:.4f}"
        f"（g 值互检 g0g1/δ={proto['g_list'][0] * proto['g_list'][1] / float(fbw):.4f}）",
        f"MYJ 斜率 b={b:.6f} S（λ/4 短路棒 π/(4Z_r)，Z_r={z_r:.3f}Ω）",
        "J 目标=" + _fmt_list(j_list, 7) + " S → Cohn 精确 x="
        + _c3_fmt_x(x_list) + "（n/a=超单支上限，缝仍由 J 直接反解）",
        f"KJ 一维反解缝={_fmt_list(gaps, 4)} mm（棒宽 {w:.4f} mm 固定）",
        f"λ/4={lg_quarter:.4f}mm − Δl({w:.4f})={dl:.4f} → res_len="
        f"{res_len:.4f}mm（开路端等效长度口径进裁判），feed={feed_len:.4f}mm",
        "口径与假设清单见 openems_templates §C3 段首（邻耦合近似，非邻耦合"
        "/棒端效应由 EM 冒烟实测）",
    ]
    if via:
        y_via = c3_y_shorted_stub(float(f0_ghz), ere,
                                  res_len + dl, z_r, lv)
        notes.append(
            f"过孔补偿（口径 10+R1）：l_via={lv * 1e9:.4f} nH（HFSS 仲裁校准值"
            f" C3_L_VIA_CAL_H，原 Goldfarb-Pucel 0.29596nH 系高估；"
            f"h={h_mm}mm/d={2.0 * _C3_R_VIA_MM}mm）→ tanθ_c=Z_r/(ω0L)，"
            f"θ_c={via['theta_c_rad']:.5f} rad，棒电长缩短 "
            f"{via['via_delta_mm']:.4f}mm → res_len={res_len:.4f}mm；"
            f"Y(f0) 过孔端接自证 |Y|={abs(y_via):.2e} S（须≈0）；斜率 b/J/缝"
            f"取理想短路口径（经由孔 b 二阶 <0.1%）")
    return {"order": n, "f0_ghz": float(f0_ghz), "fbw": float(fbw),
            "rl_db": float(rl_db), "er": float(er), "h_mm": float(h_mm),
            "g_list": proto["g_list"], "k_list": proto["k_list"],
            "qe_in": proto["qe_in"], "qe_out": proto["qe_out"],
            "coupling_matrix": proto["coupling_matrix"],
            "b_s": b, "j_targets": j_list, "x_list": x_list,
            "z_r_ohm": z_r, "ere": ere,
            "lg_quarter_mm": lg_quarter, "dl_mm": dl,
            "w_mm": w, "gaps_mm": gaps, "res_len_mm": res_len,
            "feed_len_mm": feed_len, "sections": sections, "notes": notes,
            **via}


# ─── combline（梳状）设计链 ──────────────────────────────────────────────────

def combline_design_from_order(
    order: int, f0_ghz: float = 2.5, fbw: float = 0.05, rl_db: float = 20.0,
    *, er: float = 3.66, h_mm: float = 0.508,
    theta_r: float = math.pi / 4,
    l_via_h: float | None = 0.0,
) -> dict[str, Any]:
    """梳状带通综合链：谐振条件 cot θr=ω0·C·Z_r 定装载电容与缩短棒长。

    theta_r（谐振电长，<π/2）为设计输入 → c_load=C=cot(θr)/(ω0 Z_r)（pF）、
    res_len=θr·c/(ω0√εeff)；其余同 interdigital 链（斜率/缝口径）。
    l_via_h≠0 时棒长按过孔+装载电容谐振条件精确解重解（口径 10：
    t=(1−Ax)/(A+x)、A=ω0CZ_r，C 不变），缺省 0.0 逐字节复现理想短路口径。
    """
    from rfauto.core.synthesis import Stackup as _Stackup
    from rfauto.core.synthesis import inverse_width

    n = int(order)
    if not 0.0 < float(theta_r) < math.pi / 2:
        raise ValueError(f"theta_r 须在 (0, π/2)，得 {theta_r}")
    proto = _c3_prototype(n, float(f0_ghz), float(fbw), float(rl_db))
    w = float(inverse_width(_C3_Z0, float(f0_ghz),
                            _Stackup(name="combline", epsilon_r=float(er),
                                     thickness_mm=float(h_mm)))[0])
    z_r, ere = _c3_single_line(w, float(f0_ghz), er, h_mm)
    c_pf = (1.0 / math.tan(float(theta_r))
            / (2.0 * math.pi * float(f0_ghz) * 1e9 * z_r) * 1e12)
    res_len = (float(theta_r) * _C3_C_MM_GHZ
               / (2.0 * math.pi * float(f0_ghz) * math.sqrt(ere)))
    b = c3_slope_combline(float(f0_ghz), c_pf, z_r, float(theta_r))
    j_list = _c3_j_targets([b] * n, proto)
    x_list = _c3_x_diag(j_list)
    gaps = [c3_gap_from_coupling_j(v, w, float(f0_ghz), er, h_mm)
            for v in j_list]
    lv = _c3_via_resolved_h(l_via_h, h_mm)
    via: dict[str, Any] = {}
    if lv > 0.0:
        # 过孔补偿（口径 10，谐振条件精确解）：Y=jωC−j(1−x t)/(Z_r(x+t))=0
        # （过孔端接短路棒，x=ω0L/Z_r、t=tanθ）→ ω0C=(1−x t)/(Z_r(x+t)) →
        # A(x+t)=1−x t（A=ω0CZ_r=cotθr）→ t=(1−A x)/(A+x)，θ_c=arctan(t)，
        # 物理棒长=θ_c·c/(ω0√εeff)。装载电容 C 不变（谐振条件重解棒长）；
        # 精确解（无 tanθ≈θ 近似）；t>0 ⇔ x<tanθr（x≥tanθr=过孔电感超出装载
        # 能力，无正解显式报错）。斜率/J/缝取理想短路口径（b 二阶）。
        w0 = 2.0 * math.pi * float(f0_ghz) * 1e9
        big_a = w0 * (c_pf * 1e-12) * z_r
        x_via = w0 * lv / z_r
        if not x_via < math.tan(float(theta_r)):
            raise ValueError(
                f"过孔电感 x=ω0L/Z_r={x_via:.4f} ≥ tanθr="
                f"{math.tan(float(theta_r)):.4f}（l_via_h={lv:.3e} H 超出"
                f"装载电容补偿能力，谐振无正解）")
        t_c = (1.0 - big_a * x_via) / (big_a + x_via)
        theta_c = math.atan(t_c)
        res_len_via = (theta_c * _C3_C_MM_GHZ
                       / (2.0 * math.pi * float(f0_ghz) * math.sqrt(ere)))
        via = {"l_via_h": lv, "theta_c_rad": theta_c,
               "via_delta_mm": res_len - res_len_via}
        res_len = res_len_via
    feed_len = 60.0 - res_len / 2.0
    if not 5.0 < feed_len < 60.0:
        raise ValueError(f"feed_len={feed_len:.2f}mm 越界（棒阵列超出 60mm 板）")
    sections = [{"j_target_s": jv, "x": xv, "s_mm": sv,
                 "j_realized_s": c3_coupling_j_from_gap(
                     w, sv, float(f0_ghz), er, h_mm)[0]}
                for jv, xv, sv in zip(j_list, x_list, gaps, strict=True)]
    # 谐振条件独立自证（#118）：Y(f0)=jω0C−j·cot(θr)/Z_r 逐项代入
    # （l_via_h≠0 时换用过孔端接式回代，补偿后 |Y(f0)| 仍须≈0）
    y_res = c3_y_combline(float(f0_ghz), ere, res_len, z_r, c_pf * 1e-12, lv)
    notes = [
        f"C13 folded N={n}：k={_fmt_list(proto['k_list'], 5)}，"
        f"Q_e={proto['qe_in']:.4f}/{proto['qe_out']:.4f}",
        f"谐振条件 cot θr=ω0CZ_r：θr={float(theta_r):.5f} rad → C={c_pf:.4f} pF、"
        f"res_len={res_len:.4f}mm（缩短 {100.0 * (1.0 - 2.0 * float(theta_r) / math.pi):.1f}%）",
        f"Y(f0) 自证 |Y|={abs(y_res):.2e} S（条件闭式逐项代入，须≈0）",
        f"MYJ 斜率 b={b:.6f} S（装载电容抬升斜率 vs 裸棒 π/(4Z_r)="
        f"{math.pi / (4.0 * z_r):.6f}）",
        "J 目标=" + _fmt_list(j_list, 7) + " S → Cohn 精确 x="
        + _c3_fmt_x(x_list) + "（n/a=超单支上限，缝仍由 J 直接反解）",
        f"KJ 一维反解缝={_fmt_list(gaps, 4)} mm（棒宽 {w:.4f} mm 固定），"
        f"feed={feed_len:.4f}mm",
        "口径与假设清单见 openems_templates §C3 段首（同端接地+顶端 LumpedElement "
        "电容；棒端效应/非邻耦合不进模型）",
    ]
    if via:
        notes.append(
            f"过孔补偿（口径 10+R1）：l_via={lv * 1e9:.4f} nH（HFSS 仲裁校准值"
            f" C3_L_VIA_CAL_H，原 Goldfarb-Pucel 系高估；h={h_mm}mm/"
            f"d={2.0 * _C3_R_VIA_MM}mm）→ t=(1−Ax)/(A+x)"
            f"（A=ω0CZ_r={big_a:.4f}），θ_c={via['theta_c_rad']:.5f} rad，棒长"
            f"缩短 {via['via_delta_mm']:.4f}mm → res_len={res_len:.4f}mm"
            f"（C={c_pf:.4f} pF 不变）；Y(f0) 过孔端接自证 |Y|={abs(y_res):.2e} S"
            f"（须≈0）；斜率 b/J/缝取理想短路口径（经由孔 b 二阶）")
    return {"order": n, "f0_ghz": float(f0_ghz), "fbw": float(fbw),
            "rl_db": float(rl_db), "er": float(er), "h_mm": float(h_mm),
            "g_list": proto["g_list"], "k_list": proto["k_list"],
            "qe_in": proto["qe_in"], "qe_out": proto["qe_out"],
            "coupling_matrix": proto["coupling_matrix"],
            "b_s": b, "j_targets": j_list, "x_list": x_list,
            "z_r_ohm": z_r, "ere": ere, "theta_r": float(theta_r),
            "c_load_pf": c_pf, "res_len_mm": res_len,
            "w_mm": w, "gaps_mm": gaps, "feed_len_mm": feed_len,
            "sections": sections, "notes": notes,
            **via}


# ─── sir_bpf（阶梯阻抗谐振器）设计链 ─────────────────────────────────────────

def sir_bpf_design_from_order(
    order: int, f0_ghz: float = 2.5, fbw: float = 0.05, rl_db: float = 20.0,
    *, er: float = 3.66, h_mm: float = 0.508, z_low_ohm: float = 35.0,
    z_high_ohm: float = 70.0,
    l_via_h: float | None = 0.0,
) -> dict[str, Any]:
    """λ/4 型接地 SIR 带通综合链：tan θ1·tan θ2=Z_lo/Z_hi 定紧凑化分θ。

    开路端低阻段（w_low，宽）+ 接地端高阻段（w_high，窄）；线宽/εeff 由
    skrf HJ 精算（Z_low/Z_high 为设计目标，实际值回读并进谐振条件）；低阻
    段物理长减开路端 Δl，电路裁判以等效长度回代（口径 6）。耦合区=低阻段
    （相邻棒低阻段对齐），缝在 w_low 宽上一维反解。l_via_h≠0 时高阻段长按
    过孔端接谐振条件精确解重解（口径 10：t2=Z_lo(1−x t1)/(Z_hi t1+Z_lo x)，
    低阻段/缝不变），缺省 0.0 逐字节复现理想短路口径。
    """
    from rfauto.core.synthesis import Stackup as _Stackup
    from rfauto.core.synthesis import inverse_width

    n = int(order)
    if not (0.0 < float(z_low_ohm) < float(z_high_ohm)):
        raise ValueError(
            f"须 Z_low < Z_high（开路端低阻/接地端高阻），得 "
            f"({z_low_ohm}, {z_high_ohm})")
    proto = _c3_prototype(n, float(f0_ghz), float(fbw), float(rl_db))
    st_lo = _Stackup(name="sir_lo", epsilon_r=float(er),
                     thickness_mm=float(h_mm))
    st_hi = _Stackup(name="sir_hi", epsilon_r=float(er),
                     thickness_mm=float(h_mm))
    w_lo = float(inverse_width(float(z_low_ohm), float(f0_ghz), st_lo)[0])
    w_hi = float(inverse_width(float(z_high_ohm), float(f0_ghz), st_hi)[0])
    z_lo, ere_lo = _c3_single_line(w_lo, float(f0_ghz), er, h_mm)
    z_hi, ere_hi = _c3_single_line(w_hi, float(f0_ghz), er, h_mm)
    theta = sir_theta_symmetric(z_lo, z_hi)
    # 段电长 → 物理长（mm·GHz 口径：L=θ·c/(2π f0 √εeff)，勿混 SI rad/s）
    l_lo_elec = theta * _C3_C_MM_GHZ / (2.0 * math.pi * float(f0_ghz)
                                        * math.sqrt(ere_lo))
    l_hi = theta * _C3_C_MM_GHZ / (2.0 * math.pi * float(f0_ghz)
                                   * math.sqrt(ere_hi))
    dl = _open_end_delta_mm(w_lo, float(f0_ghz), er, h_mm)
    l_lo_phys = l_lo_elec - dl
    if l_lo_phys <= 0.0:
        raise ValueError(f"低阻段物理长 {l_lo_phys:.4f}mm ≤0（Δl 过大）")
    b = c3_slope_sir(float(f0_ghz), z_lo, ere_lo, l_lo_elec, z_hi, ere_hi, l_hi)
    j_list = _c3_j_targets([b] * n, proto)
    x_list = _c3_x_diag(j_list)
    gaps = [c3_gap_from_coupling_j(v, w_lo, float(f0_ghz), er, h_mm)
            for v in j_list]
    lv = _c3_via_resolved_h(l_via_h, h_mm)
    via: dict[str, Any] = {}
    if lv > 0.0:
        # 过孔补偿（口径 10，谐振条件精确解）：高阻段接地端经过孔端接，
        # Z_B=Z_hi(jωL+jZ_hi t2)/(Z_hi−ωL t2)=jZ_hi(x+t2)/(1−x t2)
        # （x=ω0L/Z_hi，_c3_via_terminated_short）；谐振 Z_B=jZ_lo/t1（
        # Z_in=Z_lo(Z_B+jZ_lo t1)/(Z_lo+jZ_B t1) 分母=0）→ 交叉相乘
        # Z_hi t1(x+t2)=Z_lo(1−x t2) → t2=(Z_lo−Z_hi t1 x)/(Z_hi t1+Z_lo x)，
        # θ2c=arctan(t2)，高阻段物理长=θ2c·c/(ω0√εeff_hi)。低阻段/Δl/缝不变；
        # 精确解（无 tanθ≈θ 近似）；t2>0 ⇔ Z_lo>Z_hi t1 x（x≥Z_lo/(Z_hi t1)=
        # 过孔电感超出高阻段端接能力，无正解显式报错）。斜率/J/缝取理想短路
        # 口径（b 二阶）。
        w0 = 2.0 * math.pi * float(f0_ghz) * 1e9
        t1_ideal = math.tan(theta)
        x_via = w0 * lv / z_hi
        if not t1_ideal * x_via * z_hi < z_lo:
            raise ValueError(
                f"过孔电感 x·Z_hi·t1={t1_ideal * x_via * z_hi:.4f} ≥ Z_lo="
                f"{z_lo:.4f}（l_via_h={lv:.3e} H 超出高阻段端接能力，谐振无正解）")
        t2_c = (z_lo - z_hi * t1_ideal * x_via) / (z_hi * t1_ideal + z_lo * x_via)
        theta2_c = math.atan(t2_c)
        l_hi_via = (theta2_c * _C3_C_MM_GHZ
                    / (2.0 * math.pi * float(f0_ghz) * math.sqrt(ere_hi)))
        via = {"l_via_h": lv, "theta_c_rad": theta2_c,
               "via_delta_mm": l_hi - l_hi_via}
        l_hi = l_hi_via
    bank_len = l_lo_phys + l_hi
    feed_len = 60.0 - bank_len / 2.0
    if not 5.0 < feed_len < 60.0:
        raise ValueError(f"feed_len={feed_len:.2f}mm 越界（棒阵列超出 60mm 板）")
    # 谐振独立自证（#118）：|Y| 数值极小化定位谐振 vs 闭式 f0
    # （l_via_h≠0 时换用过孔端接式回代，补偿后 |Y(f0)| 仍须≈0）
    y_at_f0 = c3_y_sir(float(f0_ghz), ere_lo, l_lo_elec, z_lo, ere_hi, l_hi,
                       z_hi, lv)
    sections = [{"j_target_s": jv, "x": xv, "s_mm": sv,
                 "j_realized_s": c3_coupling_j_from_gap(
                     w_lo, sv, float(f0_ghz), er, h_mm)[0]}
                for jv, xv, sv in zip(j_list, x_list, gaps, strict=True)]
    notes = [
        f"C13 folded N={n}：k={_fmt_list(proto['k_list'], 5)}，"
        f"Q_e={proto['qe_in']:.4f}/{proto['qe_out']:.4f}",
        f"SIR 谐振 tanθ1·tanθ2=Z_lo/Z_hi（HJ 回读 Z={z_lo:.3f}/{z_hi:.3f}Ω）"
        f"→ θ={theta:.5f} rad（对称分θ），总电长 {2.0 * theta:.5f} rad = "
        f"{100.0 * 2.0 * theta / (math.pi / 2.0):.1f}% λ/4（紧凑化）",
        f"段长：低阻（开路端）电长 {l_lo_elec:.4f} − Δl({w_lo:.4f})={dl:.4f}"
        f" = 物理 {l_lo_phys:.4f}mm；高阻（接地端）{l_hi:.4f}mm；"
        f"棒总长 {bank_len:.4f}mm，feed={feed_len:.4f}mm",
        f"Y(f0) 自证 |Y|={abs(y_at_f0):.2e} S（条件闭式逐项代入，须≈0）",
        f"MYJ 斜率 b={b:.6f} S（闭式 vs 数值中心差分 rel 3.2e-8，单测钉住）",
        "J 目标=" + _fmt_list(j_list, 7) + " S → Cohn 精确 x="
        + _c3_fmt_x(x_list) + "（n/a=超单支上限，缝仍由 J 直接反解）",
        f"KJ 一维反解缝（w_low 耦合区）={_fmt_list(gaps, 4)} mm",
        "口径与假设清单见 openems_templates §C3 段首（同端接地、耦合区=低阻段；"
        "高阻段侧缝增大不进耦合模型）",
    ]
    if via:
        notes.append(
            f"过孔补偿（口径 10+R1）：l_via={lv * 1e9:.4f} nH（HFSS 仲裁校准值"
            f" C3_L_VIA_CAL_H，原 Goldfarb-Pucel 系高估；h={h_mm}mm/"
            f"d={2.0 * _C3_R_VIA_MM}mm）→ 高阻段端接 t2=(Z_lo−Z_hi t1 x)"
            f"/(Z_hi t1+Z_lo x)（x=ω0L/Z_hi={x_via:.4f}），θ2c="
            f"{via['theta_c_rad']:.5f} rad，高阻段缩短 {via['via_delta_mm']:.4f}mm"
            f" → l_high={l_hi:.4f}mm（低阻段/缝不变）；Y(f0) 过孔端接自证 "
            f"|Y|={abs(y_at_f0):.2e} S（须≈0）；斜率 b/J/缝取理想短路口径"
            f"（经由孔 b 二阶）")
    return {"order": n, "f0_ghz": float(f0_ghz), "fbw": float(fbw),
            "rl_db": float(rl_db), "er": float(er), "h_mm": float(h_mm),
            "g_list": proto["g_list"], "k_list": proto["k_list"],
            "qe_in": proto["qe_in"], "qe_out": proto["qe_out"],
            "coupling_matrix": proto["coupling_matrix"],
            "b_s": b, "j_targets": j_list, "x_list": x_list,
            "z_lo_ohm": z_lo, "z_hi_ohm": z_hi,
            "ere_lo": ere_lo, "ere_hi": ere_hi,
            "theta": float(theta), "l_lo_elec_mm": l_lo_elec,
            "l_low_mm": l_lo_phys, "l_high_mm": l_hi, "dl_mm": dl,
            "w_feed_mm": float(inverse_width(_C3_Z0, float(f0_ghz),
                                             _Stackup(name="sir_f",
                                                      epsilon_r=float(er),
                                                      thickness_mm=float(h_mm)))[0]),
            "w_low_mm": w_lo, "w_high_mm": w_hi,
            "gaps_mm": gaps, "feed_len_mm": feed_len,
            "sections": sections, "notes": notes,
            **via}


# ─── 几何布局（render/_near_points/geometry_spec/审计 单一事实源，米）────────

def _c3_layout(template: str, params: dict[str, Any]) -> dict[str, Any]:
    """C3 三族几何统一计算（米）——防四处各自推导漂移（#212 口径）。

    双馈线同在 y=−BOARD 板边（gysel 同边先例），x 镜像对称；棒阵列 y 居中。
    """
    nom = TEMPLATE_NOMINAL[template]
    n = int(params.get("order", nom["order"]))
    if n < 1:
        raise ValueError(f"order={n} 须 ≥1")
    gaps = [v * 1e-3 for v in _c3_gaps_from_params(template, params)]   # mm → m
    board = 0.060                    # 渲染 harness 固定板边（BOARD=60e-3）
    r_via = _C3_R_VIA_MM * 1e-3
    cap_half = _C3_CAP_LEN_MM * 1e-3 / 2.0
    if template in ("interdigital", "combline"):
        w = float(params.get("w_mm", nom["w_mm"])) * 1e-3
        if not w > 0.0:
            raise ValueError("w_mm 须 >0")
        if 2.0 * r_via >= w:
            raise ValueError("过孔直径 ≥ 棒宽（几何非法）")
        w_c = w_feed = w
        res_len = float(params.get("res_len_mm", nom["res_len_mm"])) * 1e-3
        if not res_len > 0.0:
            raise ValueError("res_len_mm 须 >0")
        bank_len = res_len
        l_lo = l_hi = None
    else:  # sir_bpf
        w_hi = float(params.get("w_high_mm", nom["w_high_mm"])) * 1e-3
        w_lo = float(params.get("w_low_mm", nom["w_low_mm"])) * 1e-3
        w_feed = float(params.get("w_feed_mm", nom["w_feed_mm"])) * 1e-3
        l_lo = float(params.get("l_low_mm", nom["l_low_mm"])) * 1e-3
        l_hi = float(params.get("l_high_mm", nom["l_high_mm"])) * 1e-3
        if not (w_lo > 0.0 and w_hi > 0.0 and w_feed > 0.0
                and l_lo > 0.0 and l_hi > 0.0):
            raise ValueError("sir_bpf 几何须正")
        if w_lo <= w_hi:
            raise ValueError("须 w_low > w_high（开路端低阻/接地端高阻）")
        if 2.0 * r_via >= w_hi:
            raise ValueError("过孔直径 ≥ 高阻段宽（几何非法）")
        w_c = w_lo
        bank_len = l_lo + l_hi
        res_len = bank_len
    feed_len = float(params.get("feed_len_mm", nom["feed_len_mm"])) * 1e-3
    if not 0.0 < feed_len < board:
        raise ValueError("feed_len_mm 须在 (0, 60)")
    y1 = feed_len - board            # 棒阵列底端
    y_top = y1 + bank_len
    feed_out = board - y_top
    if feed_out <= 0.0:
        raise ValueError(
            f"feed_len={feed_len * 1e3:.2f}mm 过大：棒阵列顶端越板"
            f"（余量 {feed_out * 1e3:.2f}mm ≤0）")
    # x 心位：feed_in、bar1..N、feed_out；缝 s_j 为边到边（耦合区宽 w_c）
    widths_c = [w_c] * (n + 2)
    xs = [0.0]
    for j in range(n + 1):
        xs.append(xs[-1] + widths_c[j] / 2.0 + gaps[j] + widths_c[j + 1] / 2.0)
    total_w = xs[-1] + w_c / 2.0
    shift = -total_w / 2.0
    xs = [v + shift for v in xs]
    boxes: list[tuple[float, float, float, float]] = []
    box_names: list[str] = []
    vias: list[tuple[float, float]] = []
    caps: list[tuple[float, float, float, float]] = []
    if template == "sir_bpf":
        for idx, xc in enumerate(xs):
            if idx in (0, n + 1):      # 馈线：w_feed 板边段 + w_low 耦合段
                boxes.append((xc - w_feed / 2.0, -board,
                              xc + w_feed / 2.0, y1))
                box_names.append(f"feed{idx}_board")
                boxes.append((xc - w_lo / 2.0, y1, xc + w_lo / 2.0,
                              y1 + l_lo))
                box_names.append(f"feed{idx}_coup")
            else:                      # 谐振棒：低阻段 + 高阻段
                i_bar = idx - 1
                boxes.append((xc - w_lo / 2.0, y1, xc + w_lo / 2.0,
                              y1 + l_lo))
                box_names.append(f"sir{i_bar + 1}_low")
                boxes.append((xc - w_hi / 2.0, y1 + l_lo,
                              xc + w_hi / 2.0, y_top))
                box_names.append(f"sir{i_bar + 1}_high")
                vias.append((xc, y_top - r_via))   # 同端接地（顶端）
    else:
        for idx, xc in enumerate(xs):
            if idx in (0, n + 1):      # 馈线（板边到棒阵列顶端，开路端）
                boxes.append((xc - w_feed / 2.0, -board,
                              xc + w_feed / 2.0, y_top))
                box_names.append(f"feed{idx}_50")
            else:                      # 谐振棒
                i_bar = idx - 1
                boxes.append((xc - w / 2.0, y1, xc + w / 2.0, y_top))
                box_names.append(f"bar{i_bar + 1}")
                if template == "interdigital":
                    # 交替接地：奇棒底端、偶棒顶端（Cohn 交指口径）
                    y_via = y1 + r_via if (i_bar + 1) % 2 == 1 \
                        else y_top - r_via
                    vias.append((xc, y_via))
                else:                  # combline：同端接地（底端）+ 顶端电容
                    vias.append((xc, y1 + r_via))
                    caps.append((xc - w / 2.0, y_top - 2.0 * cap_half,
                                 xc + w / 2.0, y_top))
    return {"n": n, "template": template, "board": board,
            "w_c": w_c, "w_feed": w_feed, "w_bar": (
                w if template in ("interdigital", "combline") else w_lo),
            "w_hi": (w_hi if template == "sir_bpf" else None),
            "w_lo": (w_lo if template == "sir_bpf" else None),
            "l_lo": l_lo, "l_hi": l_hi,
            "gaps": gaps, "xs": xs, "y1": y1, "y_top": y_top,
            "res_len": res_len, "feed_len": feed_len, "feed_out": feed_out,
            "r_via": r_via, "cap_half": cap_half,
            "boxes": boxes, "box_names": box_names,
            "vias": vias, "caps": caps}


def _c3_body(template: str, p: dict[str, Any]) -> str:
    """C3 三族渲染几何段（布局字面量落脚本；#212 三方一致口径）。"""
    lay = _c3_layout(template, p)
    r_via = lay["r_via"]
    lines: list[str] = []
    lines.append(f'{template} = CSX.AddMetal("{template}")')
    for (x0, y0, x1, y1), name in zip(lay["boxes"], lay["box_names"],
                                      strict=True):
        lines.append(f'{template}.AddBox(({x0!r}, {y0!r}, H_SUB), '
                     f'({x1!r}, {y1!r}, H_SUB), priority=10)  # {name}')
    if lay["vias"]:
        lines.append(f'{template}_via = CSX.AddMetal("{template}_via")')
        for (xc, yc) in lay["vias"]:
            lines.append(f'{template}_via.AddCylinder([{xc!r}, {yc!r}, 0.0], '
                         f'[{xc!r}, {yc!r}, H_SUB], radius={r_via!r}, '
                         f'priority=10)')
    if template == "combline":
        c_f = float(p.get("c_load_pf",
                          TEMPLATE_NOMINAL["combline"]["c_load_pf"])) * 1e-12
        # 装载帽=shunt 对地惯用法（R3 审计判定等效，df5-c3fix 入账）：CSXCAD
        # 绑定的方向 kwarg 参数名就叫 ny（仅收 ny），**值**=方向索引
        # （CheckNyDir：0/1/2=x/y/z）⇒ ny=2 即 z-directed——电压沿 z 跨基板
        # 全隙（棒面 z=H_SUB→地 z=0），端帽 PEC 板落在 z=0/z=H_SUB 既有 PEC
        # 面（无新增短路墙），EC_C 只改 z 边（棒 y 边金属不被切断）——与
        # c_load_pf 的集总对地电容 KCL 语义一致。SC"ny=2 全高盒非 shunt 惯
        # 用法"指控系把参数名误读为 y 方向（runs/df5_c3fix/r3_verdict.json）。
        for k_i, (x0, y0, x1, y1) in enumerate(lay["caps"], start=1):
            lines.append(f'_c_load{k_i} = CSX.AddLumpedElement('
                         f'"c_load{k_i}", ny=2, caps=True, C={c_f!r})')
            lines.append(f'_c_load{k_i}.AddBox(({x0!r}, {y0!r}, 0.0), '
                         f'({x1!r}, {y1!r}, H_SUB), priority=10)')
    x_in = lay["xs"][0]
    x_out = lay["xs"][-1]
    wf = lay["w_feed"]
    y1 = lay["y1"]
    lines.append(f'_port1 = MSLPort(CSX, port_nr=1, metal_prop={template},')
    lines.append(f'                 start=np.array([{(x_in + wf / 2.0)!r}, '
                 f'-BOARD, H_SUB]),')
    lines.append(f'                 stop=np.array([{(x_in - wf / 2.0)!r}, '
                 f'{y1!r}, 0]),')
    lines.append('                 prop_dir="y", exc_dir="z", excite=1, '
                 'FeedShift=10 * NEAR,')
    lines.append(f'                 MeasPlaneShift=({y1!r} + BOARD) / 3, '
                 'priority=10)')
    lines.append(f'_port2 = MSLPort(CSX, port_nr=2, metal_prop={template},')
    lines.append(f'                 start=np.array([{(x_out - wf / 2.0)!r}, '
                 f'-BOARD, H_SUB]),')
    lines.append(f'                 stop=np.array([{(x_out + wf / 2.0)!r}, '
                 f'{y1!r}, 0]),')
    lines.append('                 prop_dir="y", exc_dir="z", excite=0, '
                 'FeedShift=10 * NEAR,')
    lines.append(f'                 MeasPlaneShift=({y1!r} + BOARD) / 3, '
                 'priority=10)')
    lines.append(f'for _prim in {template}.GetAllPrimitives():')
    lines.append('    if _prim.GetPriority() < 10:')
    lines.append('        _prim.SetPriority(10)')
    if lay["vias"]:
        lines.append(f'for _prim in {template}_via.GetAllPrimitives():')
        lines.append('    if _prim.GetPriority() < 10:')
        lines.append('        _prim.SetPriority(10)')
    return "\n".join(lines) + "\n"


def _interdigital_lines(p: dict[str, Any]) -> str:
    # 交指带通（§C3 滤波器族 II）：N 根 λ/4 均匀棒交替接地（奇底/偶顶过孔），
    # 双 50Ω 馈线缝耦合同边引入。几何单源 _c3_layout。
    return _c3_body("interdigital", p)


def _combline_lines(p: dict[str, Any]) -> str:
    # 梳状带通（§C3）：缩短棒（谐振条件 cot θr=ω0CZ_r）同端接地 + 顶端
    # LumpedElement 装载电容（CSXCAD caps=True）。几何单源 _c3_layout。
    return _c3_body("combline", p)


def _sir_bpf_lines(p: dict[str, Any]) -> str:
    # λ/4 型接地 SIR 带通（§C3）：低阻段（开路端/耦合区）+ 高阻段（接地端
    # 过孔），步进比紧凑化。几何单源 _c3_layout。
    return _c3_body("sir_bpf", p)


# ─── 注册（同对象单一事实源，hairpin/coupled_bpf/antenna2 同制度）────────────

INTERDIGITAL_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（交指带通：带内回波纹波 + 带外抑制；"
                  "裁判=并联谐振 J 倒置器链 c3_circuit_sparams，同步 TEM 极限"
                  "对照 C13 coupling_matrix_response 互证）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["order", "w_mm", "res_len_mm", "gaps_mm", "feed_len_mm"],
    "topology": "交指带通（§C3 滤波器族 II，Cohn 交指口径）：N 根 λ/4 均匀谐振棒"
                "平行排列，接地端交替（奇棒底端过孔/偶棒顶端过孔），相邻棒全长"
                "缝耦合；双 50Ω 馈线缝耦合自 y=−BOARD 板边引入（单轴 PML）",
    "param_semantics": "order=谐振棒数 N（决定 gaps_mm 列表长度 N+1，单独改 "
                       "order 而不改列表=非法），w_mm=棒/馈线宽（50Ω，skrf HJ "
                       "综合），res_len_mm=棒物理长（λ/4 − 过孔缩短 − 开路端 "
                       "Δl，登记⑨+R1 校准口径：tanθ_c=Z_r/(ω0L_via)、"
                       "L_via=0.125nH HFSS 仲裁校准值 C3_L_VIA_CAL_H（原 "
                       "Goldfarb-Pucel 0.29596nH 高估已弃）；缺省渲染几何在过孔"
                       "存在下谐振回 f0），gaps_mm"
                       "[j]=第 j 缝边到边（j=0 馈-棒1 … j=N 棒N-馈，"
                       "fake/openEMS 两通道同索引同语义 #154），feed_len_mm="
                       "板边到棒阵列底端的馈线段长（阵列 y 居中 ⇒ 两馈等长）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "棒/馈缘+过孔中心精确入网（#198 精确入网）",
}

INTERDIGITAL_NOMINAL: dict[str, Any] = {
    "order": 3,
    # 50Ω 棒/馈线宽 = round(live inverse_width(50,2.5,rogers4350b),4)（铁律 1c）
    "w_mm": 1.1117,
    # 过孔补偿口径（登记⑨+R1 校准 2026-09-22，设计链 l_via_h=None 自动值
    # C3_L_VIA_CAL_H=0.125nH）：λ/4(εeff=2.8578)=17.7338 − 过孔缩短 0.4431
    # （tanθ_c=Z_r/(ω0L)，θ_c=1.531547）− Δl(1.1117)=0.2086（开路端等效长度
    # 口径）= 17.0820。旧 G-P auto 值 0.29596nH 高估致补偿过缩短
    # （16.4785，全波峰 +4.1%，SC verdict 次根因）
    "res_len_mm": 17.0820,
    # C13 N=3/RL20/δ5% → Q_e=17.0689、k=0.051514；b=π/(4·49.998)=0.015708 S →
    # J=[4.290e-3, 8.09e-4, 8.09e-4, 4.290e-3] S → KJ 一维反解缝（4 位舍入；
    # 过孔对 b 二阶 <0.1%，缝与理想短路口径相同）
    "gaps_mm": [0.2263, 1.3567, 1.3567, 0.2263],
    # 60 − res_len/2（棒阵列 y 居中 ⇒ 两馈等长）
    "feed_len_mm": 51.4590,
}

COMBLINE_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（梳状带通：带内回波纹波 + 带外抑制；"
                  "裁判=并联谐振 J 倒置器链 c3_circuit_sparams，同步 TEM 极限"
                  "对照 C13 coupling_matrix_response 互证）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["order", "w_mm", "res_len_mm", "gaps_mm", "feed_len_mm",
               "c_load_pf"],
    "topology": "梳状带通（§C3 滤波器族 II，MYJ Ch.10 口径）：N 根缩短棒平行"
                "排列，接地端同端（底端全部过孔），顶端各接 LumpedElement 装载"
                "电容（谐振条件 cot θr=ω0·C·Z_r 定缩短长度）；双 50Ω 馈线缝耦合"
                "自 y=−BOARD 板边引入（单轴 PML）",
    "param_semantics": "order=谐振棒数 N（决定 gaps_mm 列表长度 N+1），w_mm=棒/"
                       "馈线宽（50Ω，skrf HJ 综合），res_len_mm=缩短棒物理长"
                       "（与 c_load_pf 经谐振条件联动，可独立失调；名义值含登记"
                       "⑨ 过孔补偿：t=(1−Ax)/(A+x)、A=ω0CZ_r，C 不变棒长重解），"
                       "gaps_mm[j]=第 j 缝边到边（同索引同语义 #154），"
                       "feed_len_mm=板边到棒阵列底端馈段长，c_load_pf=顶端装载"
                       "电容（LumpedElement C 值，进电路裁判不改变导体几何）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "棒/馈缘+过孔中心+电容盒边精确入网（#198 精确入网）",
}

COMBLINE_NOMINAL: dict[str, Any] = {
    "order": 3,
    "w_mm": 1.1117,
    # θr=π/4：cot θr=ω0CZ_r → C=1/(ω0·Z_r)=1.2732pF（Z_r=HJ 49.9998Ω）；
    # res_len=θr·c/(ω0√εeff)=8.8669 − 过孔缩短 0.4431（t=(1−Ax)/(A+x)、
    # A=ω0CZ_r=1，θ_c=0.746148 rad；登记⑨+R1 校准 0.125nH 过孔补偿，
    # C 不变棒长重解）= 8.4238
    "res_len_mm": 8.4238,
    # b=½(ω0C+csc²θr·θr/Z_r)=0.025707 S（装载抬升 1.64×）→ 缝更紧
    "gaps_mm": [0.1393, 0.9291, 0.9291, 0.1393],
    "feed_len_mm": 55.7881,
    "c_load_pf": 1.2732,
}

SIR_BPF_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（SIR 带通：带内回波纹波 + 带外抑制；"
                  "裁判=并联谐振 J 倒置器链 c3_circuit_sparams，同步 TEM 极限"
                  "对照 C13 coupling_matrix_response 互证）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["order", "w_feed_mm", "w_low_mm", "w_high_mm", "l_low_mm",
               "l_high_mm", "gaps_mm", "feed_len_mm"],
    "topology": "λ/4 型接地 SIR 带通（§C3 滤波器族 II，MYJ SIR 章口径）：N 根"
                "阶梯阻抗棒平行排列（开路端低阻段+接地端高阻段，步进比给出紧凑"
                "化，谐振条件 tanθ1·tanθ2=Z_lo/Z_hi），同端接地顶端过孔，耦合区"
                "=低阻段；双 50Ω 馈线缝耦合自 y=−BOARD 板边引入（单轴 PML）",
    "param_semantics": "order=谐振棒数 N（决定 gaps_mm 列表长度 N+1），w_feed_mm"
                       "=馈线宽（50Ω HJ），w_low_mm/w_high_mm=低阻/高阻段宽"
                       "（须 w_low>w_high），l_low_mm/l_high_mm=低阻/高阻段物理"
                       "长（l_low 已减开路端 Δl，裁判以等效长度回代；l_high 名义"
                       "值含登记⑨ 过孔补偿：t2=(Z_lo−Z_hi t1 x)/(Z_hi t1+Z_lo x)"
                       "，接地端过孔缩短），gaps_mm"
                       "[j]=第 j 缝边到边（低阻耦合区，同索引同语义 #154），"
                       "feed_len_mm=板边到棒阵列底端馈段长",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "棒/馈/台阶缘+过孔中心精确入网（#198 精确入网）",
}

SIR_BPF_NOMINAL: dict[str, Any] = {
    "order": 3,
    "w_feed_mm": 1.1117,
    # Z_low=35Ω/Z_high=70Ω（HJ 精算线宽），tanθ1tanθ2=Z_lo/Z_hi → θ=0.61548 rad
    "w_low_mm": 1.8944,
    "w_high_mm": 0.6144,
    # 低阻段电长 6.7941 − Δl(w_low)=0.2222 → 物理 6.5719；高阻段电长 7.1055
    # − 过孔缩短 0.3237（t2=(Z_lo−Z_hi t1 x)/(Z_hi t1+Z_lo x)，θ2c=0.587437 rad；
    # 登记⑨+R1 校准 0.125nH 过孔补偿）= 6.7818（接地端无 Δl）
    "l_low_mm": 6.5719,
    "l_high_mm": 6.7818,
    "gaps_mm": [0.2417, 1.5189, 1.5189, 0.2417],
    # 60 − (l_low+l_high)/2（棒阵列 y 居中）
    "feed_len_mm": 53.3232,
}

# ── 注册（2026-09-15，c3-filter-family-ii）：三模板正式注册 ──
# 七处同步：① docs/templates/{interdigital,combline,sir_bpf}/meta.yaml；②
# test_template_geometry_audit.EXPECTED_TEMPLATES（25→28）；③ fake_adapter 派发
# （_c3_sparams，裁判同源闭式）；④ models/template_specs（_register_c3_*）；⑤
# _geometry_audit_helpers 三表（PORT_GROUPS/JOINT_DOMAIN_PARAMS/PERTURB_OVERRIDES）；
# ⑥ test_physics_invariants SCALE/MIRROR 案；⑦ 独立模板测试。同对象注册（非
# 拷贝）钉死单一事实源；标称数字=设计函数 4 位舍入（再生守卫钉住）。
TEMPLATE_META["interdigital"] = INTERDIGITAL_META
TEMPLATE_NOMINAL["interdigital"] = INTERDIGITAL_NOMINAL
TEMPLATE_META["combline"] = COMBLINE_META
TEMPLATE_NOMINAL["combline"] = COMBLINE_NOMINAL
TEMPLATE_META["sir_bpf"] = SIR_BPF_META
TEMPLATE_NOMINAL["sir_bpf"] = SIR_BPF_NOMINAL


def c3_meta(template: str) -> dict[str, Any]:
    """返回 C3 族某模板元数据（与 template_meta(t) 同构的便捷别名）。"""
    if template not in C3_TEMPLATES:
        raise KeyError(f"非 C3 模板: {template}（可用 {C3_TEMPLATES}）")
    meta = dict(TEMPLATE_META[template])
    meta["template"] = template
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = {k: (list(v) if isinstance(v, list) else v)
                              for k, v in TEMPLATE_NOMINAL[template].items()}
    return meta


# ═══ §10.3 C2 阵列族（2026-09-15 注册）：patch_array_1x4 / patch_array_2x2 /
# patch_array_series ═══
# 方案行：器件族表 §10.3 "C2 阵列族｜1×4/2×2 贴片阵、
# 串馈阵｜阵列因子综合接口"（接 D5 综合内核 core/array_synthesis）。
#
# ── 理论核验轮（#206/铁律 1b：先理论后几何；antenna2 六模板同款制度）──
# 1. C. A. Balanis, Antenna Theory 3rd ed., Ch. 6 "Arrays: Linear, Planar, and
#    Circular"：均匀直线阵 AF 闭式 |sin(Nψ/2)/(N sin(ψ/2))|（§6.3）、方向图积定理
#    F=F_elem·AF、侧射 HPBW 渐近式 0.886λ/(Nd)（N=4 精确 26.32° vs 渐近 25.38°，
#    偏 3.7%，单测钉死）、栅瓣判据 d/λ≤1/(1+|u0|)、§6.10 矩形栅格平面阵可分离积
#    AF(θ,φ)=AF_x(sinθcosφ)·AF_y(sinθsinφ)（2×2 裁判，array_synthesis.planar_array_
#    factor 加法式扩展）。
# 2. Balanis Ch. 14 "Microstrip Antennas"（传输线/腔模型）：
#    W = c/(2f0)·√(2/(εr+1))；εeff = (εr+1)/2+(εr−1)/2·(1+12h/W)^−½（Hammerstad）；
#    ΔL = 0.824h·(εeff+0.3)(W/h+0.264)/((εeff−0.258)(W/h+0.8))；L = c/(2f0√εeff)−2ΔL
#    ——与 core/calculators.patch_length、core/synthesis.synthesize_patch 同公式，
#    core/symbolic_fit.patch_resonance_hj_ghz（f0 = c/(2(L+2ΔL)√εeff)）为独立裁判；
#    本段 array_elem_len_mm 为设计式，fake_adapter.array_resonance_ghz 为其精确逆。
#    双缝方向图闭式（等效磁面流同相、地面镜像、上半空间）见 array_synthesis.
#    patch_element_field（E 面 ∝ cos((k0L/2)sinθ)、H 面 ∝ cosθ·sinc((k0W/2)sinθ)）。
#    馈电阻抗一阶口径（fake 常数出处，未标定不进锚判据）：单缝辐射电导小缝近似
#    G1 ≈ (W/λ0)²/90，边馈 Rin(0)=1/(2(G1+G12))（G12 互导忽略），插入馈
#    Rin(y0) = Rin(0)·cos²(π y0/L)。
# 3. C. L. Dolph, Proc. IRE 1946（Chebyshev 等副瓣加权；副瓣判据 peak_sidelobe_
#    level_db）。
# 4. **openEMS 无官方阵列教程**——官方基线只有 Simple Patch Antenna（单元口径：
#    底馈 LumpedPort、基板延伸到侧界、z-min PEC 地、nf2ff 盒域缩 4×网格；
#    _patch_lines 2026-09-05 冒烟审计后重构版）。本段单元几何沿用该口径，阵列层
#    离线裁判 = 积定理闭式（真机 nf2ff 主瓣/HPBW/Dmax 对照为 openEMS 轨 followUp，
#    scripts/smoke_array_anchor.py 已备判据）；不杜撰官方阵列例。
#
# ── 设计点与几何约束 ──
# f0 = 5.8GHz：BOARD=60e-3 是全模板共享字面量（render_script，禁改）——2.4GHz 下
# 1×4 λ0/2 间距需 ~222mm 装不进 120mm 板；5.8GHz λ0=51.6884mm 三模板全装下。
# 单元间距取 0.484λ0 = 25.0172mm（略缩 λ0/2）：#212 泛化审计对每个声明参数做
# ×1.37+0.013 扰动后仍须渲染成功，3d+W = 119.79mm ≤ 120mm 恰装下（λ0/2 时 123mm
# 超板）；侧射栅瓣判据 d<λ0 宽裕（has_grating_lobe(0.484)=False）。
# 线宽/λg 一律 skrf HJ 精算（铁律 1c，禁沿用文档毫米数）：50Ω w=1.112mm
# （εeff 2.8579 → λg/2 = 15.2876mm）、70.7Ω w=0.6025mm（εeff 2.7294 → λ/4 =
# 7.8217mm）。单元 W=16.9311 / L=12.9058 / 插入深度 0.3L=3.8717mm（synthesize_
# patch ~100Ω 插入点同口径）。
#
# ── 拓扑（单元 L 沿 y、W 沿 x，三模板同口径；#154 三通道同名同语义）──
# patch_array_1x4：4 元沿 x 等距（阵列面 x-z = 单元 H 面），插入馈缺口开在 −y 边
#   （贴片=缺口两侧+缺口顶 3 盒，馈线终点触缺口底=馈点）。corporate 树：主干 50Ω
#   自底探针上行至 J0；J0→J1± 各 λ/4 70.7Ω 变换段（沿 x）；J1± 经 50Ω 透明连线
#   （y0 横走 + 各元 x 竖走）到每元最后一段 λ/4 70.7Ω 变换段入缺口。阻抗账：元
#   50Ω→λ/4 70.7 → 100Ω，两元并联@J1=50Ω → λ/4 70.7 → 100Ω，两侧并联@J0=50Ω。
#   单馈口 = 主干下方 LumpedPort 底探针（patch 官方口径）→ PORT_AXES=() 全 MUR。
# patch_array_2x2：同口径 H-tree。底排缺口向 −y（自下入）；顶排缺口向 +y，馈线
#   经 J1± 沿 y0 外走到元列外侧走廊 x=±(dx/2+W/2+2mm)，上行至顶排上方 y_ta 再
#   内折、变换段自上向下入缺口——同层零交叉（首版"顶排自下方穿底排"方案会与
#   底排贴片重叠短接，布局期即否决）。
# patch_array_series：1×3 共线串馈（MSLPort 自 y=−BOARD 入，PORT_AXES=("y",)）：
#   λg/2 50Ω 互联接相邻贴片辐射边中心。相位账：λg/2 段 180° + λ/2 贴片两辐射边
#   场反相 180° ⇒ 各元同相侧射（Balanis Ch.14 串馈阵口径）。取 3 元是 120mm 板在
#   审计 ×1.37 扰动域内的上限（4 元 4L+3λg/2 = 98mm，elem_len×1.37 后超板）。
# 单一几何源 _arr_layout（mm）喂渲染 _arr_body / _near_points / geometry_spec /
# 离线审计四方（_ant2_layout 同制度）；fake 派发 _array_sparams：f0 = 单元设计
# 闭式精确逆的一阶串联谐振（S 参数不含方向图物理，如实注明）。

_ARR_C_MM_GHZ = 299.792458
ARRAY_TEMPLATES: tuple[str, ...] = (
    "patch_array_1x4", "patch_array_2x2", "patch_array_series")
_ARR_SPACING_FRAC = 0.484        # 单元间距 / λ0（略缩 λ0/2，见段首约束）
_ARR_INSET_FRAC = 0.3            # 插入深度 / L（synthesize_patch 同口径）
_ARR_NOTCH_CLEAR_MM = 0.5        # 缺口两侧净空（缺口宽 = 馈线宽 + 2×净空）
_ARR_ROW_Y_MM = 20.0             # 1×4 行中心 / 2×2 栅格中心 y
_ARR_TREE_Y_MM = {"patch_array_1x4": -4.0, "patch_array_2x2": -13.0}   # J 线 y0
_ARR_TRUNK_MM = 8.0              # 主干长（J0 → 探针中心）
_ARR_PROBE_HALF_X_MM = 0.1       # 底探针盒 x 半宽（patch 官方 0.2mm 盒）
_ARR_PROBE_HALF_Y_MM = 1.0       # 底探针盒 y 半宽（patch 官方 2mm 盒）
_ARR_CORRIDOR_CLEAR_MM = 2.0     # 2×2 顶排走廊距元列外缘净空
_ARR_SERIES_N = 3
_ARR_SERIES_FEED_MARGIN_MM = 8.0
_ARR_EDGE_MARGIN_MM = 1.0        # 金属到板边最小净空
_ARR_BOARD_MM = 60.0             # 与 render_script BOARD=60e-3 同值（mm）


# ─── 闭式设计函数（确定性内核：尺寸只由公式给出，非手数）────────────────────

def array_elem_w_mm(f0_ghz: float, er: float = 3.66) -> float:
    """贴片宽 W = c/(2f0)·√(2/(εr+1))（Balanis Ch.14 传输线模型）。"""
    if not (float(f0_ghz) > 0.0 and float(er) > 1.0):
        raise ValueError("f0 须正且 εr > 1")
    return _ARR_C_MM_GHZ / (2.0 * float(f0_ghz)) * math.sqrt(2.0 / (float(er) + 1.0))


def _array_patch_eps_dl(w_mm: float, er: float, h_mm: float) -> tuple[float, float]:
    """贴片准静态 εeff 与边缘修正 ΔL（Hammerstad；与 symbolic_fit 独立裁判同式）。"""
    w, e, h = float(w_mm), float(er), float(h_mm)
    if not (w > 0.0 and h > 0.0 and e > 1.0):
        raise ValueError("W/h 须正且 εr > 1")
    ee = (e + 1.0) / 2.0 + (e - 1.0) / 2.0 * (1.0 + 12.0 * h / w) ** -0.5
    dl = 0.824 * h * (ee + 0.3) / (ee - 0.258) * (w / h + 0.264) / (w / h + 0.8)
    return ee, dl


def array_elem_len_mm(f0_ghz: float, w_mm: float, er: float = 3.66,
                      h_mm: float = 0.508) -> float:
    """贴片谐振长 L = c/(2f0√εeff) − 2ΔL（设计式；fake array_resonance_ghz 为精确逆）。"""
    if not float(f0_ghz) > 0.0:
        raise ValueError("f0 须正")
    ee, dl = _array_patch_eps_dl(w_mm, er, h_mm)
    return _ARR_C_MM_GHZ / (2.0 * float(f0_ghz) * math.sqrt(ee)) - 2.0 * dl


def array_line_w_mm(z0_ohm: float, f0_ghz: float, er: float = 3.66,
                    h_mm: float = 0.508) -> float:
    """微带线宽（skrf HJ inverse_width 精算，铁律 1c）。"""
    from rfauto.core.synthesis import Stackup, inverse_width

    if not (float(z0_ohm) > 0.0 and float(f0_ghz) > 0.0):
        raise ValueError("Z0/f0 须正")
    stackup = Stackup(name="c2_array", epsilon_r=float(er), thickness_mm=float(h_mm))
    w, _z_actual, _status = inverse_width(float(z0_ohm), float(f0_ghz), stackup)
    return float(w)


def array_quarter_len_mm(w_mm: float, f0_ghz: float, er: float = 3.66,
                         h_mm: float = 0.508) -> float:
    """λ/4 变换段长 = c/(4f0√εeff(w))（HJ εeff @线宽）。"""
    eps = _ant2_eps_eff(float(w_mm), float(f0_ghz), float(er), float(h_mm))
    return _ARR_C_MM_GHZ / (4.0 * float(f0_ghz) * math.sqrt(eps))


def array_half_guided_len_mm(w_mm: float, f0_ghz: float, er: float = 3.66,
                             h_mm: float = 0.508) -> float:
    """串馈互联 λg/2 = c/(2f0√εeff(w))（HJ εeff @线宽）。"""
    return 2.0 * array_quarter_len_mm(w_mm, f0_ghz, er, h_mm)


def array_design_params(template: str, f0_ghz: float = 5.8, er: float = 3.66,
                        h_mm: float = 0.508) -> dict[str, Any]:
    """C2 三模板全参数设计链（4 位舍入；ARRAY_NOMINAL = 本函数 @5.8GHz，单测互检）。

    线宽先舍入再算 εeff（λ/4、λg/2 以渲染实际线宽为准，与标称常数逐位一致）。
    """
    if template not in ARRAY_TEMPLATES:
        raise KeyError(f"非 C2 阵列模板: {template}（可用 {ARRAY_TEMPLATES}）")
    f0 = float(f0_ghz)
    w_raw = array_elem_w_mm(f0, er)
    l_raw = array_elem_len_mm(f0, w_raw, er, h_mm)
    feed_w = round(array_line_w_mm(50.0, f0, er, h_mm), 4)
    params: dict[str, Any] = {
        "elem_len_mm": round(l_raw, 4),
        "elem_w_mm": round(w_raw, 4),
    }
    if template == "patch_array_series":
        params["feed_w_mm"] = feed_w
        params["link_len_mm"] = round(array_half_guided_len_mm(feed_w, f0, er, h_mm), 4)
        params["feed_margin_mm"] = _ARR_SERIES_FEED_MARGIN_MM
        return params
    spacing = round(_ARR_SPACING_FRAC * _ARR_C_MM_GHZ / f0, 4)
    q_w = round(array_line_w_mm(50.0 * math.sqrt(2.0), f0, er, h_mm), 4)
    params["elem_feed_mm"] = round(_ARR_INSET_FRAC * l_raw, 4)
    if template == "patch_array_1x4":
        params["spacing_mm"] = spacing
    else:
        params["spacing_x_mm"] = spacing
        params["spacing_y_mm"] = spacing
    params["feed_w_mm"] = feed_w
    params["q_w_mm"] = q_w
    params["q_len_mm"] = round(array_quarter_len_mm(q_w, f0, er, h_mm), 4)
    return params


# 各模板标称设计点 @5.8GHz（= array_design_params 4 位舍入，单测互检）
ARRAY_NOMINAL: dict[str, dict[str, Any]] = {
    "patch_array_1x4": {
        "elem_len_mm": 12.9058, "elem_w_mm": 16.9311, "elem_feed_mm": 3.8717,
        "spacing_mm": 25.0172, "feed_w_mm": 1.112, "q_w_mm": 0.6025,
        "q_len_mm": 7.8217,
    },
    "patch_array_2x2": {
        "elem_len_mm": 12.9058, "elem_w_mm": 16.9311, "elem_feed_mm": 3.8717,
        "spacing_x_mm": 25.0172, "spacing_y_mm": 25.0172, "feed_w_mm": 1.112,
        "q_w_mm": 0.6025, "q_len_mm": 7.8217,
    },
    "patch_array_series": {
        "elem_len_mm": 12.9058, "elem_w_mm": 16.9311, "feed_w_mm": 1.112,
        "link_len_mm": 15.2876, "feed_margin_mm": 8.0,
    },
}

_ARR_ELEM_SEMANTICS = (
    "elem_len_mm=单元谐振长 L（沿 y；Balanis Ch.14 传输线模型 c/(2f0√εeff)−2ΔL，"
    "fake 谐振为其精确逆），elem_w_mm=单元宽 W（沿 x；c/(2f0)√(2/(εr+1))，"
    "决定 εeff/ΔL 与 H 面波束）")
_ARR_TREE_SEMANTICS = (
    "feed_w_mm=50Ω 线宽（主干/透明连线/缺口内馈段；HJ 1.112mm），q_w_mm=70.7Ω "
    "λ/4 变换段宽（HJ 0.6025mm），q_len_mm=变换段长 λ/4=c/(4f0√εeff(q_w))=7.8217mm"
    "（J0→J1± 与各元入缺口最后一段共用），elem_feed_mm=插入馈深度 y0（缺口深=馈线"
    "终点=馈点；Rin(y0)=Rin(0)cos²(πy0/L)，0.3L≈100Ω 口径）")

ARRAY_META: dict[str, dict[str, Any]] = {
    "patch_array_1x4": {
        "f0_ghz": 5.8, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（底探针馈 corporate 1×4 贴片阵：谷位/谷深"
                      "；方向图走 far_field=True nf2ff，离线裁判=积定理闭式：主瓣 0°、"
                      "HPBW 对照 broadside_hpbw_deg(4,d/λ0)、无栅瓣；未真机冒烟）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["elem_len_mm", "elem_w_mm", "elem_feed_mm", "spacing_mm",
                   "feed_w_mm", "q_w_mm", "q_len_mm"],
        "topology": "1×4 直线贴片阵（§10.3 C2）：4 元沿 x 等距 spacing、行中心 y=20mm，"
                    "单元 L 沿 y/W 沿 x、插入馈缺口开在 −y 边（3 盒贴片）；corporate 树"
                    "=主干 50Ω（底探针→J0）+ J0→J1± λ/4 70.7Ω + J1± 50Ω 透明连线（y0 横"
                    "走/各元 x 竖走）+ 每元最后一段 λ/4 70.7Ω 入缺口；基板 + z-min PEC 地",
        "param_semantics": _ARR_ELEM_SEMANTICS + "，spacing_mm=单元中心距 d（0.484λ0="
                           "25.0172mm，略缩 λ0/2 以满足审计扰动域 3d+W≤120mm；栅瓣判据 "
                           "d<λ0），" + _ARR_TREE_SEMANTICS,
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；全部盒缘（贴片/缺口/树/探针）精确"
                     "入网（#198）",
    },
    "patch_array_2x2": {
        "f0_ghz": 5.8, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（底探针馈 H-tree 2×2 贴片阵：谷位/谷深；方向图"
                      "走 far_field=True nf2ff，离线裁判=平面阵可分离积 AF_x·AF_y 逐点；"
                      "未真机冒烟）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["elem_len_mm", "elem_w_mm", "elem_feed_mm", "spacing_x_mm",
                   "spacing_y_mm", "feed_w_mm", "q_w_mm", "q_len_mm"],
        "topology": "2×2 平面贴片阵（§10.3 C2）：栅格中心 (0,20mm)，元列 x=±dx/2、元排 "
                    "y=20∓dy/2；底排缺口向 −y 自下入，顶排缺口向 +y——馈线经 J1± 沿 y0 外走"
                    "到元列外侧走廊 x=±(dx/2+W/2+2mm) 上行、顶排上方内折、变换段自上向下入"
                    "缺口（同层零交叉）；H-tree 阻抗账同 1×4；基板 + z-min PEC 地",
        "param_semantics": _ARR_ELEM_SEMANTICS + "，spacing_x_mm/spacing_y_mm=元列/元排"
                           "中心距（均 0.484λ0=25.0172mm；可分离栅格），"
                           + _ARR_TREE_SEMANTICS,
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；全部盒缘精确入网（#198）",
    },
    "patch_array_series": {
        "f0_ghz": 5.8, "n_ports": 1,
        "extraction": "S11 @ MSLPort 1（1×3 共线串馈贴片阵，端接=链末开路辐射边：谷位/"
                      "谷深；方向图走 far_field=True nf2ff，离线裁判=积定理闭式（同相侧射"
                      "）；未真机冒烟）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["elem_len_mm", "elem_w_mm", "feed_w_mm", "link_len_mm",
                   "feed_margin_mm"],
        "topology": "1×3 串馈贴片阵（§10.3 C2）：3 元共线沿 y（x=0 居中，L 沿 y/W 沿 x），"
                    "相邻元以 λg/2 50Ω 互联接辐射边中心；MSLPort 自 y=−BOARD 入、自画馈段"
                    "至链首元 −y 边（feed_margin）；链末开路。相位账：λg/2 段 180°+λ/2 贴片"
                    "两边场反相 180° ⇒ 同相侧射；单轴 PML（y）；基板 + z-min PEC 地",
        "param_semantics": _ARR_ELEM_SEMANTICS + "，feed_w_mm=50Ω 馈线/互联宽（HJ "
                           "1.112mm），link_len_mm=互联长 λg/2=c/(2f0√εeff(feed_w))="
                           "15.2876mm（HJ），feed_margin_mm=板边到链首元的馈段长（MSLPort"
                           " 自画，MeasPlaneShift=margin/3）",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；贴片/互联/馈段盒缘精确入网（#198）",
    },
}

# ── 注册：同对象入 TEMPLATE_META/TEMPLATE_NOMINAL（单一事实源；antenna2 同款）──
# 四处同步：① docs/templates/<t>/meta.yaml ×3；② test_template_geometry_audit.
# EXPECTED_TEMPLATES（+3）；③ fake_adapter 派发 _array_sparams；④ models/
# template_specs._register_patch_array。
for _arr_name in ARRAY_TEMPLATES:
    TEMPLATE_META[_arr_name] = ARRAY_META[_arr_name]
    TEMPLATE_NOMINAL[_arr_name] = ARRAY_NOMINAL[_arr_name]
del _arr_name


def array_meta(template: str) -> dict[str, Any]:
    """返回 C2 阵列族某模板元数据（与 template_meta(t) 同构的便捷别名）。"""
    if template not in ARRAY_TEMPLATES:
        raise KeyError(f"非 C2 阵列模板: {template}（可用 {ARRAY_TEMPLATES}）")
    meta = dict(ARRAY_META[template])
    meta["template"] = template
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(ARRAY_NOMINAL[template])
    return meta


def _arr_layout(
    template: str,
    params: dict[str, Any],
    sub: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """C2 阵列族单一事实源（mm）：金属盒 / 端口 / 单元中心 / z 网格线。

    渲染段（_arr_body）、近场加密（_near_points 分支）、UI 预览（geometry_spec
    分支）与离线审计（test_array_templates / test_template_geometry_audit）四方
    消费——单源防漂移（_ant2_layout / _hairpin_layout 同制度）。
    盒元组 = (金属属性名, 盒名, x0, y0, z0, x1, y1, z1)，全部零厚顶面 z=h
    （官方金属面口径）；集总馈口激励向 z 跨度 = h > 0（#174）。
    几何守卫显式 ValueError（超板/重叠/缺口越界），不静默夹紧——审计 ×1.37
    扰动域已按标称常数预核（段首"设计点与几何约束"）。
    """
    if template not in ARRAY_TEMPLATES:
        raise ValueError(f"未知 C2 阵列模板: {template}")
    sub = sub or _DEFAULT_SUB
    er = float(sub["er"])
    h = float(sub["h_mm"])
    nom = ARRAY_NOMINAL[template]

    def g(key: str) -> float:
        return float(params.get(key, nom[key]))

    length = g("elem_len_mm")
    width = g("elem_w_mm")
    fw = g("feed_w_mm")
    if not (length > 0.0 and width > 0.0 and fw > 0.0):
        raise ValueError(f"{template}: 单元 L/W 与馈线宽须正")
    if fw >= width:
        raise ValueError(f"{template}: 馈线宽 {fw} 须小于单元宽 {width}")
    board = _ARR_BOARD_MM
    lim = board - _ARR_EDGE_MARGIN_MM
    prop_patch = f"{template}_patch"
    prop_line = f"{template}_line"
    prop_q = f"{template}_qline"
    boxes: list[tuple[str, str, float, float, float, float, float, float]] = []
    ports: list[dict[str, Any]] = []
    elements: list[tuple[float, float]] = []

    def hline(tag: str, x0: float, x1: float, y: float, w: float, prop: str) -> None:
        boxes.append((prop, tag, min(x0, x1), y - w / 2, h, max(x0, x1), y + w / 2, h))

    def vline(tag: str, x: float, y0: float, y1: float, w: float, prop: str) -> None:
        boxes.append((prop, tag, x - w / 2, min(y0, y1), h, x + w / 2, max(y0, y1), h))

    if template == "patch_array_series":
        link = g("link_len_mm")
        margin = g("feed_margin_mm")
        if not (link > 0.0 and margin > 0.0):
            raise ValueError("patch_array_series: 互联长/馈段长须正")
        if width / 2 > lim:
            raise ValueError("patch_array_series: 单元宽超板")
        y = -board + margin
        for k in range(_ARR_SERIES_N):
            boxes.append((prop_patch, f"e{k}", -width / 2, y, h, width / 2, y + length, h))
            elements.append((0.0, y + length / 2))
            if k < _ARR_SERIES_N - 1:
                vline(f"link{k}", 0.0, y + length, y + length + link, fw, prop_line)
            y += length + link
        chain_top = y - link
        if chain_top > lim:
            raise ValueError(
                f"patch_array_series: 链顶 {chain_top:.3f}mm 超板（≤{lim}mm；"
                f"{_ARR_SERIES_N}·L + {_ARR_SERIES_N - 1}·λg/2 + margin）")
        ports.append({"kind": "msl", "nr": 1, "metal_prop": prop_line,
                      "start_mm": (fw / 2, -board, h),
                      "stop_mm": (-fw / 2, -board + margin, 0.0),
                      "prop_dir": "y", "exc_dir": "z", "excite": 1,
                      "meas_shift_mm": margin / 3.0})
    else:
        d_in = g("elem_feed_mm")
        qw = g("q_w_mm")
        ql = g("q_len_mm")
        nw = fw + 2.0 * _ARR_NOTCH_CLEAR_MM
        if not (0.0 < d_in < length / 2):
            raise ValueError(f"{template}: 插入深度 {d_in} 须落在 (0, L/2={length / 2})")
        if nw >= width:
            raise ValueError(f"{template}: 缺口宽 {nw} 须小于单元宽 {width}")
        if not (qw > 0.0 and ql > 0.0):
            raise ValueError(f"{template}: 变换段宽/长须正")
        y0 = _ARR_TREE_Y_MM[template]
        y_probe = y0 - _ARR_TRUNK_MM
        cy = _ARR_ROW_Y_MM

        def inset_elem(tag: str, cx: float, cyl: float, mouth_sign: int) -> float:
            """插入馈贴片 3 盒 + 缺口内 50Ω 馈段；返回缺口口沿 y（mouth）。

            mouth_sign=−1：缺口开在 −y 边（自下入）；+1：开在 +y 边（自上入）。
            馈段终点触缺口顶盒 = 馈点（连通即由此面接触建立）。
            """
            y_lo, y_hi = cyl - length / 2, cyl + length / 2
            boxes.append((prop_patch, f"{tag}_l", cx - width / 2, y_lo, h,
                          cx - nw / 2, y_hi, h))
            boxes.append((prop_patch, f"{tag}_r", cx + nw / 2, y_lo, h,
                          cx + width / 2, y_hi, h))
            if mouth_sign < 0:
                boxes.append((prop_patch, f"{tag}_c", cx - nw / 2, y_lo + d_in, h,
                              cx + nw / 2, y_hi, h))
                mouth = y_lo
            else:
                boxes.append((prop_patch, f"{tag}_c", cx - nw / 2, y_lo, h,
                              cx + nw / 2, y_hi - d_in, h))
                mouth = y_hi
            vline(f"{tag}_stub", cx, mouth, mouth - mouth_sign * d_in, fw, prop_line)
            elements.append((cx, cyl))
            return mouth

        # 主干（探针盒完全位于主干金属下方）+ J0→J1± λ/4 变换段
        vline("trunk", 0.0, y_probe - _ARR_PROBE_HALF_Y_MM, y0, fw, prop_line)
        hline("q_j0_l", -ql, 0.0, y0, qw, prop_q)
        hline("q_j0_r", 0.0, ql, y0, qw, prop_q)
        if template == "patch_array_1x4":
            s = g("spacing_mm")
            if s <= width:
                raise ValueError(f"patch_array_1x4: 中心距 {s} 须大于单元宽 {width}（重叠）")
            if ql >= s / 2:
                raise ValueError(f"patch_array_1x4: λ/4 段 {ql} 须小于半间距 {s / 2}")
            if 1.5 * s + width / 2 > board:
                raise ValueError(
                    f"patch_array_1x4: 跨度 3d+W={3 * s + width:.3f}mm 超 {2 * board}mm 板")
            if cy + length / 2 > lim:
                raise ValueError("patch_array_1x4: 单元顶超板")
            mouth = cy - length / 2
            y_ts = mouth - ql
            if y_ts <= y0 + fw:
                raise ValueError(
                    f"patch_array_1x4: 变换段起点 {y_ts:.3f} 须在 J 线 {y0} 上方")
            for i in range(4):
                cx = (i - 1.5) * s
                sgn = -1.0 if cx < 0.0 else 1.0
                hline(f"run{i}", sgn * ql, cx, y0, fw, prop_line)
                vline(f"rise{i}", cx, y0, y_ts, fw, prop_line)
                vline(f"q{i}", cx, y_ts, mouth, qw, prop_q)
                inset_elem(f"e{i}", cx, cy, -1)
        else:  # patch_array_2x2
            dx = g("spacing_x_mm")
            dy = g("spacing_y_mm")
            if dx <= width or dy <= length:
                raise ValueError(f"patch_array_2x2: 中心距 ({dx},{dy}) 须大于单元 ({width},{length})")
            if ql >= dx / 2:
                raise ValueError(f"patch_array_2x2: λ/4 段 {ql} 须小于半列距 {dx / 2}")
            row_b, row_t = cy - dy / 2, cy + dy / 2
            mouth_b = row_b - length / 2
            mouth_t = row_t + length / 2
            y_tsb = mouth_b - ql
            y_ta = mouth_t + ql
            x_c = dx / 2 + width / 2 + _ARR_CORRIDOR_CLEAR_MM
            if y_tsb <= y0 + fw:
                raise ValueError(
                    f"patch_array_2x2: 底排变换段起点 {y_tsb:.3f} 须在 J 线 {y0} 上方")
            if y_ta + qw / 2 > lim:
                raise ValueError(f"patch_array_2x2: 顶排走线 y={y_ta:.3f} 超板顶")
            if x_c + fw / 2 > lim:
                raise ValueError(f"patch_array_2x2: 走廊 x={x_c:.3f} 超板边")
            for cx in (-dx / 2, dx / 2):
                sgn = -1.0 if cx < 0.0 else 1.0
                tag = "l" if cx < 0.0 else "r"
                # 底排：J1 沿 y0 外走（共享段，顺带覆盖到走廊起点）→ 元列竖走 → 变换段 → 缺口
                hline(f"run_b_{tag}", sgn * ql, sgn * x_c, y0, fw, prop_line)
                vline(f"rise_b_{tag}", cx, y0, y_tsb, fw, prop_line)
                vline(f"q_b_{tag}", cx, y_tsb, mouth_b, qw, prop_q)
                inset_elem(f"e_b_{tag}", cx, row_b, -1)
                # 顶排：走廊上行 → 顶排上方内折 → 变换段自上向下 → 缺口（同层零交叉）
                vline(f"corr_{tag}", sgn * x_c, y0, y_ta, fw, prop_line)
                hline(f"run_t_{tag}", sgn * x_c, cx, y_ta, fw, prop_line)
                vline(f"q_t_{tag}", cx, y_ta, mouth_t, qw, prop_q)
                inset_elem(f"e_t_{tag}", cx, row_t, +1)
        ports.append({"kind": "lumped", "nr": 1, "R": 50.0,
                      "start_mm": (-_ARR_PROBE_HALF_X_MM, y_probe - _ARR_PROBE_HALF_Y_MM, 0.0),
                      "stop_mm": (_ARR_PROBE_HALF_X_MM, y_probe + _ARR_PROBE_HALF_Y_MM, h),
                      "exc_dir": "z", "excite": 1})
    return {
        "boxes": boxes,
        "ports": ports,
        "elements_mm": elements,
        "z_lines_mm": [0.0, h],
        "element_top_mm": h,
        "air_below": False,
        "substrate": True,
        "er": er, "h_mm": h,
    }


def _arr_body(template: str, p: dict[str, Any]) -> str:
    """由 _arr_layout 单源渲染几何段（金属盒 + 端口 + priority 收口；_ant2_body 同构）。

    坐标全部走布局字面量（米），渲染==布局==审计三方一致；单端口模板
    _port2=_port1（patch 单端口 fallback 口径）。
    """
    lay = _arr_layout(template, p)
    out: list[str] = []
    m = lambda v: repr(float(v) * 1e-3)   # noqa: E731  mm→m 字面量
    metal_names: list[str] = []
    for box in lay["boxes"]:
        if box[0] not in metal_names:
            metal_names.append(box[0])
    for prop in metal_names:
        out.append(f'{prop} = CSX.AddMetal("{prop}")')
    for (prop, name, x0, y0, z0, x1, y1, z1) in lay["boxes"]:
        out.append(f'{prop}.AddBox(({m(x0)}, {m(y0)}, {m(z0)}), '
                   f'({m(x1)}, {m(y1)}, {m(z1)}), priority=10)  # {name}')
    for port in lay["ports"]:
        s, t = port["start_mm"], port["stop_mm"]
        nr = int(port["nr"])
        if port["kind"] == "lumped":
            out.append(
                f'_port{nr} = LumpedPort(CSX, port_nr={nr}, R={port["R"]!r},\n'
                f'                    start=np.array([{m(s[0])}, {m(s[1])}, '
                f'{m(s[2])}]),\n'
                f'                    stop=np.array([{m(t[0])}, {m(t[1])}, '
                f'{m(t[2])}]),\n'
                f'                    exc_dir="{port["exc_dir"]}", '
                f'excite={int(port["excite"])}, priority=5)')
        else:
            out.append(
                f'_port{nr} = MSLPort(CSX, port_nr={nr}, '
                f'metal_prop={port["metal_prop"]},\n'
                f'                 start=np.array([{m(s[0])}, {m(s[1])}, '
                f'{m(s[2])}]),\n'
                f'                 stop=np.array([{m(t[0])}, {m(t[1])}, '
                f'{m(t[2])}]),\n'
                f'                 prop_dir="{port["prop_dir"]}", '
                f'exc_dir="{port["exc_dir"]}", excite={int(port["excite"])},\n'
                f'                 FeedShift=10 * NEAR, '
                f'MeasPlaneShift={float(port["meas_shift_mm"]) * 1e-3!r},\n'
                f'                 priority=10)')
    if len(lay["ports"]) == 1:
        out.append('_port2 = _port1   # 单端口模板：footer fallback 口径')
    for prop in metal_names:
        out.append(f'for _prim in {prop}.GetAllPrimitives():\n'
                   '    if _prim.GetPriority() < 10:\n'
                   '        _prim.SetPriority(10)')
    return "\n".join(out) + "\n"


def _patch_array_1x4_lines(p: dict[str, Any]) -> str:
    # §10.3 C2 1×4 corporate 贴片阵：插入馈单元 ×4 + λ/4 70.7Ω 变换树 + 底探针
    # LumpedPort（patch 官方口径）；设计式/布局/审计单源 _arr_layout。
    return _arr_body("patch_array_1x4", p)


def _patch_array_2x2_lines(p: dict[str, Any]) -> str:
    # §10.3 C2 2×2 H-tree 贴片阵：底排自下入缺口、顶排走廊绕行自上入缺口
    # （同层零交叉），底探针 LumpedPort。
    return _arr_body("patch_array_2x2", p)


def _patch_array_series_lines(p: dict[str, Any]) -> str:
    # §10.3 C2 1×3 共线串馈贴片阵：λg/2 互联接辐射边中心，MSLPort 自 y=−BOARD 入
    # （slot 馈段同款自画 + MeasPlaneShift=margin/3）。
    return _arr_body("patch_array_series", p)


# ═══════════════════════════════════════════════════════════════════════════════
# §DP-4 P3 EEP 阵列族（2026-09-24 df6）：patch_eep_2x2 / patch_eep_1x4 ═════════
# 互耦档（EEP）专用阵模板：单元平铺参数化（elem_len/w/feed_mm + spacing_x/y_mm），
# **每元独立 LumpedPort 底探针馈（端口 1..4），无 corporate 馈树**——
# N 次单激励轮转（#208 进程隔离，_FOUR_PORT_ROTATION_TEMPLATES 9 列 CSV footer）
# 逐轮产出第 n 列 S 参数与第 n 元有源方向图（EEPₙ，nf2ff 全局原点参考，
# farfield3d_cplx.csv）；非激励端口=50Ω 集总元端接（EEP 教科书口径）。
#
# ── 理论核验轮（#206/铁律 1b）──
# 1. EEP 定义：F(û)=ΣₙaₙEEPₙ(û)，EEPₙ=第 n 元有源单元方向图（其余元 50Ω 端接
#    被动在场）；Γ_act,n=Σ_m S_nm(a_m/a_n)（DP-4 规格书 §2c；Pozar & Schaubert
#    1984）。叠加可行性前提：各轮 nf2ff 在**同一频率**取值——EEP 轮 f_res=F0
#    固定（设计带中心），非 argmin|S11|（其余元被动在场的单激励轮里 port1
#    的 S11 谷不代表阵列谐振，且逐轮 argmin 会漂到不同频点使叠加失效）。
# 2. 轮间幅度/相位可比前提：各元端口几何全同（R=50 同阻值、同探针盒）且
#    各轮激励幅值一致（excite=1 同脉冲）——EEPₙ 逐轮按同一"单位入射波"尺度
#    落盘（nf2ff 场对激励线性）。非均匀元尺寸阵此前提不成立，如实不外推。
# 3. 单元几何沿用官方 Simple Patch Antenna 底探针口径（_patch_lines/C2 同源
#    闭式：Balanis Ch.14 传输线模型 W=c/(2f0)√(2/(εr+1))、L=c/(2f0√εeff)−2ΔL、
#    插入馈 0.3L≈100Ω 口径；线宽 skrf HJ 精算 #1c）——与 C2 阵列族共用
#    array_elem_w_mm/array_elem_len_mm/array_line_w_mm 设计链（零复制毫米数）。
# 4. 端口取向全 −y（元间同向、同极化）：EEP 阵无馈树约束，不需要 C2 2×2 的
#    顶排翻转（那是同层零交叉布线手段）；同向是 EEP 阵的物理规范形。
#
# ── 设计点与几何约束（复用 C2 预核扰动域，#212 ×1.37+0.013 单键逐键可建）──
# f0=5.8GHz、BOARD=60mm 共享字面量；spacing=0.484λ0=25.0172mm（同 C2：1×4
# 跨度 3d+W=126mm>120 的扰动域由 C2 同款守卫 board=60（非 lim）恰好容纳
# 1.5·s'+W'/2=59.90≤60）；元间 DC 隔离（4 个独立导体分量）=EEP 定义性质，
# 审计 PORT_GROUPS 四组 {1}{2}{3}{4}（非功分器族的单分量判据）。
EEP_TEMPLATES: tuple[str, ...] = ("patch_eep_2x2", "patch_eep_1x4")
_EEP_BOARD_MM = _ARR_BOARD_MM            # 与 render_script BOARD=60e-3 同值（mm）
_EEP_EDGE_MARGIN_MM = _ARR_EDGE_MARGIN_MM
_EEP_ROW_Y_MM = _ARR_ROW_Y_MM            # 阵面行中心 y（1×4 单行 / 2×2 栅格中心）
_EEP_NOTCH_CLEAR_MM = _ARR_NOTCH_CLEAR_MM
_EEP_PROBE_HALF_X_MM = _ARR_PROBE_HALF_X_MM   # 底探针盒 x 半宽（patch 官方 0.2mm 盒）
_EEP_PROBE_HALF_Y_MM = _ARR_PROBE_HALF_Y_MM   # 底探针盒 y 半宽（patch 官方 2mm 盒）
_EEP_SPACING_FRAC = _ARR_SPACING_FRAC    # 单元间距/λ0（同 C2，0.484）

#: EEP 3D 复数远场网格（度；模板脚本与 core.farfield 契约共同遵守）
EEP_FF_THETA_DEG = (0.0, 180.0, 5.0)
EEP_FF_PHI_DEG = (0.0, 360.0, 5.0)


def eep_n_ports(template: str) -> int:
    """EEP 模板端口数（=单元数，恒 4——excite_port 钳位 1..4 恰容 2×2）。"""
    if template not in EEP_TEMPLATES:
        raise KeyError(f"非 EEP 阵列模板: {template}（可用 {EEP_TEMPLATES}）")
    return 4


def eep_design_params(template: str, f0_ghz: float = 5.8, er: float = 3.66,
                      h_mm: float = 0.508) -> dict[str, Any]:
    """EEP 两模板全参数设计链（4 位舍入；EEP_NOMINAL = 本函数 @5.8GHz，单测互检）。

    全部尺寸出自确定性闭式（#1c）：单元 W/L（Balanis Ch.14，array_elem_w/len_mm）、
    插入馈深 0.3L（~100Ω 口径）、间距 0.484λ0（同 C2，栅瓣判据 d<λ0）、
    馈线宽（skrf HJ inverse_width 50Ω）。先舍入再出的口径与 ARRAY_NOMINAL 一致。
    """
    if template not in EEP_TEMPLATES:
        raise KeyError(f"非 EEP 阵列模板: {template}（可用 {EEP_TEMPLATES}）")
    f0 = float(f0_ghz)
    w_raw = array_elem_w_mm(f0, er)
    l_raw = array_elem_len_mm(f0, w_raw, er, h_mm)
    params: dict[str, Any] = {
        "elem_len_mm": round(l_raw, 4),
        "elem_w_mm": round(w_raw, 4),
        "elem_feed_mm": round(_ARR_INSET_FRAC * l_raw, 4),
        "spacing_x_mm": round(_EEP_SPACING_FRAC * _ARR_C_MM_GHZ / f0, 4),
        "feed_w_mm": round(array_line_w_mm(50.0, f0, er, h_mm), 4),
    }
    if template == "patch_eep_2x2":
        params["spacing_y_mm"] = params["spacing_x_mm"]
    return params


#: 各模板标称设计点 @5.8GHz（= eep_design_params 4 位舍入，单测互检）
EEP_NOMINAL: dict[str, dict[str, Any]] = {
    "patch_eep_2x2": {
        "elem_len_mm": 12.9058, "elem_w_mm": 16.9311, "elem_feed_mm": 3.8717,
        "spacing_x_mm": 25.0172, "spacing_y_mm": 25.0172, "feed_w_mm": 1.112,
    },
    "patch_eep_1x4": {
        "elem_len_mm": 12.9058, "elem_w_mm": 16.9311, "elem_feed_mm": 3.8717,
        "spacing_x_mm": 25.0172, "feed_w_mm": 1.112,
    },
}

_EEP_ELEM_SEMANTICS = (
    "elem_len_mm=单元谐振长 L（沿 y；Balanis Ch.14 c/(2f0√εeff)−2ΔL，fake 谐振为"
    "精确逆），elem_w_mm=单元宽 W（沿 x；c/(2f0)√(2/(εr+1))），elem_feed_mm=插入"
    "馈深度（缺口深=探针馈点；Rin(y0)=Rin(0)cos²(πy0/L)，0.3L≈100Ω 口径），"
    "feed_w_mm=缺口内馈段/探针邻域线宽（HJ 50Ω 1.112mm）")

EEP_META: dict[str, dict[str, Any]] = {
    "patch_eep_2x2": {
        "f0_ghz": 5.8, "n_ports": 4,
        "extraction": "整 4×4 S @ LumpedPort 1-4（单激励 9 列 CSV，excite_port=1..4 "
                      "进程隔离轮转装配 → .s4p，#208）+ EEPₙ @ farfield3d_cplx.csv"
                      "（far_field=True，f_res=F0 固定口径，轮间同频可叠加）；互耦档"
                      "判据 J4 见 runs/df6_dp4p3/criteria.md",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["elem_len_mm", "elem_w_mm", "elem_feed_mm", "spacing_x_mm",
                   "spacing_y_mm", "feed_w_mm"],
        "topology": "2×2 EEP 贴片阵（§DP-4 P3）：栅格中心 (0,20mm)，元列 x=±dx/2、"
                    "元排 y=20∓dy/2，四元同向（缺口全开 −y）；每元独立 LumpedPort "
                    "底探针（端口 1..4=行主序 x 外层 y 内层），无 corporate 馈树，"
                    "元间 DC 隔离=EEP 定义性质；基板 + z-min PEC 地",
        "param_semantics": _EEP_ELEM_SEMANTICS + "，spacing_x_mm/spacing_y_mm=元列/"
                           "元排中心距（均 0.484λ0=25.0172mm，同 C2 扰动域预核）",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；全部盒缘（贴片/缺口/探针）精确"
                     "入网（#198）",
    },
    "patch_eep_1x4": {
        "f0_ghz": 5.8, "n_ports": 4,
        "extraction": "整 4×4 S @ LumpedPort 1-4（单激励 9 列 CSV，excite_port=1..4 "
                      "进程隔离轮转装配 → .s4p，#208）+ EEPₙ @ farfield3d_cplx.csv"
                      "（far_field=True，f_res=F0 固定口径，轮间同频可叠加）；互耦档"
                      "判据 J4 见 runs/df6_dp4p3/criteria.md",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["elem_len_mm", "elem_w_mm", "elem_feed_mm", "spacing_x_mm",
                   "feed_w_mm"],
        "topology": "1×4 EEP 贴片阵（§DP-4 P3）：4 元沿 x 等距 spacing（行中心 "
                    "y=20mm），缺口全开 −y；每元独立 LumpedPort 底探针（端口 1..4 "
                    "=x 升序），无 corporate 馈树，元间 DC 隔离=EEP 定义性质；基板 + "
                    "z-min PEC 地",
        "param_semantics": _EEP_ELEM_SEMANTICS + "，spacing_x_mm=单元中心距 d"
                           "（0.484λ0=25.0172mm；栅瓣判据 d<λ0，1×4 跨度 3d+W 扰动域"
                           "与 C2 同款预核 ≤120mm 板）",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；全部盒缘（贴片/缺口/探针）精确"
                     "入网（#198）",
    },
}

# ── 注册（单一事实源；C2 同款）：同对象入 TEMPLATE_META/TEMPLATE_NOMINAL ──
for _eep_name in EEP_TEMPLATES:
    TEMPLATE_META[_eep_name] = EEP_META[_eep_name]
    TEMPLATE_NOMINAL[_eep_name] = EEP_NOMINAL[_eep_name]
del _eep_name


def eep_meta(template: str) -> dict[str, Any]:
    """返回 EEP 阵列族某模板元数据（与 template_meta(t) 同构的便捷别名）。"""
    if template not in EEP_TEMPLATES:
        raise KeyError(f"非 EEP 阵列模板: {template}（可用 {EEP_TEMPLATES}）")
    meta = dict(EEP_META[template])
    meta["template"] = template
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(EEP_NOMINAL[template])
    return meta


def _eep_layout(
    template: str,
    params: dict[str, Any],
    sub: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """EEP 两模板单一事实源（mm）：金属盒 / 端口 / 单元中心 / z 网格线。

    渲染段（_eep_body）、近场加密（_near_points 分支）、UI 预览（geometry_spec
    分支）与离线审计（test_eep_templates / test_template_geometry_audit）四方
    消费——单源防漂移（_arr_layout 同制度）。盒元组 =
    (金属属性名, 盒名, x0, y0, z0, x1, y1, z1)，全部零厚顶面 z=h；
    集总馈口激励向 z 跨度 = h > 0（#174）。
    端口次序（叠加/扫描相位记账的行主序契约，服务层同序消费）：
    1x4 = x 升序；2x2 = x 外层 y 内层 (−dx,−dy),(−dx,+dy),(+dx,−dy),(+dx,+dy)。
    """
    if template not in EEP_TEMPLATES:
        raise ValueError(f"未知 EEP 阵列模板: {template}")
    sub = sub or _DEFAULT_SUB
    er = float(sub["er"])
    h = float(sub["h_mm"])
    nom = EEP_NOMINAL[template]

    def g(key: str) -> float:
        return float(params.get(key, nom[key]))

    length = g("elem_len_mm")
    width = g("elem_w_mm")
    fw = g("feed_w_mm")
    d_in = g("elem_feed_mm")
    dx = g("spacing_x_mm")
    if not (length > 0.0 and width > 0.0 and fw > 0.0):
        raise ValueError(f"{template}: 单元 L/W 与馈线宽须正")
    if fw >= width:
        raise ValueError(f"{template}: 馈线宽 {fw} 须小于单元宽 {width}")
    if not (0.0 < d_in < length / 2):
        raise ValueError(f"{template}: 插入深度 {d_in} 须落在 (0, L/2={length / 2})")
    nw = fw + 2.0 * _EEP_NOTCH_CLEAR_MM
    if nw >= width:
        raise ValueError(f"{template}: 缺口宽 {nw} 须小于单元宽 {width}")
    if dx <= width:
        raise ValueError(f"{template}: 列距 {dx} 须大于单元宽 {width}（重叠）")
    board = _EEP_BOARD_MM
    lim = board - _EEP_EDGE_MARGIN_MM
    cy = _EEP_ROW_Y_MM
    prop_patch = f"{template}_patch"
    prop_line = f"{template}_line"
    boxes: list[tuple[str, str, float, float, float, float, float, float]] = []
    ports: list[dict[str, Any]] = []
    elements: list[tuple[float, float]] = []

    def inset_elem(tag: str, cx: float, cyl: float, nr: int) -> float:
        """插入馈贴片 3 盒 + 缺口内 50Ω 馈段 + 底探针 LumpedPort（返回馈点 y）。

        缺口开在 −y 边（四元同向）；探针从 z=0（PEC 地）跨基板到 z=h，
        盒顶面与缺口内馈段/缺口顶盒相接（连通即由此面接触建立，#174 激励
        体积=z 向 h>0）；excite 随 _excite_port 四态切换（ratrace 范式）。
        """
        y_lo, y_hi = cyl - length / 2, cyl + length / 2
        boxes.append((prop_patch, f"{tag}_l", cx - width / 2, y_lo, h,
                      cx - nw / 2, y_hi, h))
        boxes.append((prop_patch, f"{tag}_r", cx + nw / 2, y_lo, h,
                      cx + width / 2, y_hi, h))
        boxes.append((prop_patch, f"{tag}_c", cx - nw / 2, y_lo + d_in, h,
                      cx + nw / 2, y_hi, h))
        # 缺口内馈段：mouth → 缺口底（+y 向 d_in；终点=缺口顶盒底缘=馈点）
        boxes.append((prop_line, f"{tag}_stub", cx - fw / 2, y_lo, h,
                      cx + fw / 2, y_lo + d_in, h))
        yf = y_lo + d_in
        ep = int(params.get("_excite_port", 1) or 1)
        ports.append({
            "kind": "lumped", "nr": nr, "R": 50.0,
            "start_mm": (cx - _EEP_PROBE_HALF_X_MM, yf - _EEP_PROBE_HALF_Y_MM, 0.0),
            "stop_mm": (cx + _EEP_PROBE_HALF_X_MM, yf + _EEP_PROBE_HALF_Y_MM, h),
            "exc_dir": "z", "excite": 1 if ep == nr else 0})
        elements.append((cx, cyl))
        return yf

    if template == "patch_eep_1x4":
        if 1.5 * dx + width / 2 > board:
            raise ValueError(
                f"patch_eep_1x4: 跨度 3d+W={3 * dx + width:.3f}mm 超 {2 * board}mm 板")
        if cy + length / 2 > lim:
            raise ValueError("patch_eep_1x4: 单元顶超板")
        for i in range(4):
            inset_elem(f"e{i}", (i - 1.5) * dx, cy, i + 1)
    else:  # patch_eep_2x2
        dy = g("spacing_y_mm")
        if dy <= length:
            raise ValueError(f"patch_eep_2x2: 排距 {dy} 须大于单元长 {length}（重叠）")
        row_b, row_t = cy - dy / 2, cy + dy / 2
        if row_t + length / 2 > lim or row_b - length / 2 < -lim:
            raise ValueError("patch_eep_2x2: 元排越板")
        nr = 0
        for cx in (-dx / 2, dx / 2):          # x 外层
            for cyl in (row_b, row_t):        # y 内层（行主序=端口次序契约）
                nr += 1
                inset_elem(f"e{nr}", cx, cyl, nr)
    return {
        "boxes": boxes,
        "ports": ports,
        "elements_mm": elements,
        "z_lines_mm": [0.0, h],
        "element_top_mm": h,
        "air_below": False,
        "substrate": True,
        "er": er, "h_mm": h,
    }


def _eep_body(template: str, p: dict[str, Any]) -> str:
    """由 _eep_layout 单源渲染几何段（金属盒 + 端口 + priority 收口）。

    四端口 excite 随 _excite_port 四态切换（ratrace/branchline 范式）——
    非激励端口 excite=0 仅探针仍记录（LumpedPort u/i 探针无条件创建），
    渲染脚本尾部走单激励 9 列 CSV（_FOUR_PORT_ROTATION_TEMPLATES footer）。
    """
    lay = _eep_layout(template, p)
    out: list[str] = []
    m = lambda v: repr(float(v) * 1e-3)   # noqa: E731  mm→m 字面量
    metal_names: list[str] = []
    for box in lay["boxes"]:
        if box[0] not in metal_names:
            metal_names.append(box[0])
    for prop in metal_names:
        out.append(f'{prop} = CSX.AddMetal("{prop}")')
    for (prop, name, x0, y0, z0, x1, y1, z1) in lay["boxes"]:
        out.append(f'{prop}.AddBox(({m(x0)}, {m(y0)}, {m(z0)}), '
                   f'({m(x1)}, {m(y1)}, {m(z1)}), priority=10)  # {name}')
    for port in lay["ports"]:
        s, t = port["start_mm"], port["stop_mm"]
        nr = int(port["nr"])
        out.append(
            f'_port{nr} = LumpedPort(CSX, port_nr={nr}, R={port["R"]!r},\n'
            f'                    start=np.array([{m(s[0])}, {m(s[1])}, '
            f'{m(s[2])}]),\n'
            f'                    stop=np.array([{m(t[0])}, {m(t[1])}, '
            f'{m(t[2])}]),\n'
            f'                    exc_dir="{port["exc_dir"]}", '
            f'excite={int(port["excite"])}, priority=5)')
    for prop in metal_names:
        out.append(f'for _prim in {prop}.GetAllPrimitives():\n'
                   '    if _prim.GetPriority() < 10:\n'
                   '        _prim.SetPriority(10)')
    return "\n".join(out) + "\n"


def _patch_eep_2x2_lines(p: dict[str, Any]) -> str:
    # §DP-4 P3 2×2 EEP 阵：四元同向独立探针（端口 1..4 行主序），无馈树。
    return _eep_body("patch_eep_2x2", p)


def _patch_eep_1x4_lines(p: dict[str, Any]) -> str:
    # §DP-4 P3 1×4 EEP 阵：四元同向独立探针（端口 1..4 x 升序），无馈树。
    return _eep_body("patch_eep_1x4", p)


# ═══════════════════════════════════════════════════════════════════════════════
# §C4 耦合器族 II 本体段：cline_coupler（耦合线定向耦合器）/ branchline_2sect
# （两节分支线）/ lange（展开型 Lange 电桥）——理论核验轮 + 离线几何审计
# （2026-09-16 增量；正式注册进 TEMPLATE_META/TEMPLATE_NOMINAL，见段末注册块）
# ═══════════════════════════════════════════════════════════════════════════════
# ── 理论核验轮（#206 纪律；口径/来源逐条，裁判=独立来源不自证）──
# 1) 耦合线定向耦合器（Pozar《Microwave Engineering》4th ed. §7.6 耦合线定向
#    耦合器节；章节号以版次为准）：电压耦合系数 C=10^(−C_dB/20)；匹配条件
#    Z0²=Z0e·Z0o 下 Z0e=Z0√((1+C)/(1−C))、Z0o=Z0√((1−C)/(1+C))、
#    C=(Z0e−Z0o)/(Z0e+Z0o)；频响（同步 TEM）S31=jC·sinθ/(√(1−C²)cosθ+j·sinθ)、
#    S21=√(1−C²)/(√(1−C²)cosθ+j·sinθ)，S11=S41=0；θ=90° 处 |S31|=C（同相）、
#    S21=−j√(1−C²)。端口约定（后向波耦合器）：1=输入（线 A 近端）、2=直通
#    （线 A 远端）、3=耦合（线 B 近端，与输入同侧）、4=隔离（线 B 远端）。
#    **独立互检**：偶/奇模装配 _coupled_section_s4（coupled_bpf 段既有内核，
#    无耗/互易由构造保证）在 θ=60/75/90/110° 与 Pozar 闭式逐位一致
#    （test_coupler2_templates 钉住）。
#    微带非同步残差（εeff_e≠εeff_o，真 KJ 相速）：名义 10dB 设计 @f0 实测
#    |S31|=−10.045dB、S41=−23.3dB、S11=−32.9dB（定向性 ≈13dB——Pozar 明述的
#    微带耦合线固有极限，未做相速补偿/锯齿缝；fake 默认走真 KJ 相速
#    （coupled_bpf 同口径），synchronous_tem=True 为理想裁判极限，两路单测各钉）。
# 2) 两节分支线（Pozar 4th ed. §7.5 分支线偶/奇模分析推广至两节；Levy & Lind,
#    "Synthesis of Symmetrical Branch-Guide Directional Couplers", IEEE Trans.
#    MTT-16(2), 1968 对称分支导综合口径；Microwaves101 "Two-section branchline
#    coupler" 页二级参照）：沿水平中面二分——支臂切成 λ/8 半桩（偶模 PMC=
#    开路桩 +j·Y_b·tan(θ_b/2)、奇模 PEC=短路桩 −j·Y_b·cot(θ_b/2)），半电路
#    ABCD = 桩(Y_b1)·线(Z_a)·桩(Y_b2)·线(Z_a)·桩(Y_b1)；S11=(Γe+Γo)/2、
#    S21=(Te+To)/2（直通=P2 同线远端）、S31=(Te−To)/2（耦合=P3 对角）、
#    S41=(Γe−Γo)/2（隔离=P4 同侧）。**映射校验**：单节 (Z_a=Z0/√2, Z_b=Z0)
#    代入同式复现 Pozar S21=−j/√2、S31=−1/√2、S11=S41≈0（|S11|~1e-17，
#    单测钉住）。**f0 处解为单参数族**（本轮多起点 least_squares 数值解 +
#    解析归纳）：Z_b1=(1+√2)Z0（外支臂，120.71Ω@50Ω）、Z_b2=√2·Z_a²/Z0
#    （中支臂）、Z_a 自由——Microwaves101 独立表述逐字一致（"end impedances
#    must remain at [1+√2]×Z0 … Z3=√2×Z1²/Z0"）。标称取 Pozar 经典点 Z_a=Z0
#    → (50, 120.71, 70.71)Ω；理想 ±1dB 均分带宽 35.0%（本轮扫描 0.350，
#    Microwaves101 同页 35%）vs 单节 25.8%，−20dB 匹配/隔离带宽 24.2% vs
#    10.4%（两节 ≥ 单节，单测钉住）。最平坦匹配解 Z_a≈0.72·Z0（|S11|² 二阶
#    导零点）作 main_z_ratio 选项保留。f0 处 S21=−1/√2（两 λ/4=λ/2，−180°）、
#    S31=+j/√2（+90°），正交。**几何固有偏差**（gysel 桥带同类）：外/中支臂
#    Z 不同 → εeff 不同 → λ/4 物理长不同（本叠层差 ≈3.1%），矩形拓扑只有
#    一个支臂跨度，取两支臂 λ/4 的算术平均（各 ≈±1.5%，二阶），如实记录。
# 3) Lange 电桥（Pozar 4th ed. §7.6 Lange 节，四指展开型 fig 7.33(b)；原始
#    J. Lange, IEEE-MTT-S 1969；Microwaves101 "Lange Couplers" 页二级参照：
#    "through 与 input 有 DC 连接"）：相邻对 (Z0e,Z0o) → 四线等效两线
#    Ze4=Z0e(Z0o+Z0e)/(3Z0o+Z0e)、Zo4=Z0o(Z0o+Z0e)/(3Z0e+Z0o)，耦合
#    C=(Ze4−Zo4)/(Ze4+Zo4)、Z0=√(Ze4·Zo4)；设计式（反解，含 √(9−8C²) 项）
#    Z0e=Z0(4C−3+√(9−8C²))/(2C√((1−C)/(1+C)))、Z0o=Z0(4C+3−√(9−8C²))/
#    (2C√((1+C)/(1−C)))。**自洽校验**：3dB（C=1/√2）→ 相邻对
#    (176.216, 52.609)Ω（文献常引 ≈176/52.6 同值）→ 四线换算回 Ze4=120.71、
#    Zo4=20.71 → C=0.707107、Z0=50.000（逐位闭合，单测钉住）。等效两线
#    (Ze4,Zo4) 代入口径 1 偶/奇模内核 → f0 处 |S21|=|S31|=−3.01dB、
#    S31=+1/√2（耦合同相）、S21=−j/√2（直通滞后 90°）、S11=S41=0。
#    几何：展开型（交替指两端各以 air-bridge 并联=Pozar 等效两线模型精确
#    成立的拓扑）；外指承馈（P1/P2=指 1 近/远端、P3/P4=指 4 近/远端，
#    {1,2}=网络 A、{3,4}=网络 B，两网络 DC 隔离）。**相速口径**：fake 默认
#    synchronous_tem=True——相邻对 KJ εeff_e/εeff_o 不是四线等效模相速
#    （多导体模式，Ou 1975），拿来当非同步相位即建模错误；Lange 只给理想
#    裁判（ratrace/gysel 窄带理想化同口径）。KJ 有效域提示：3dB Lange 于
#    rogers4350b h=0.508 反解 s=0.0386mm → g=s/h=0.076 略低于 KJ 标称有效
#    域下限 0.1（如实记录）；单指 w=0.167mm（u=0.33）在域内。非相邻指耦合
#    忽略（一阶 Lange 设计口径）。
# 4) 线宽全部 skrf HJ 精算（inverse_width/forward_z0，铁律 1c）；(Z0e,Z0o)→
#    (w,s) 走 coupled_bpf_width_gap_from_zee_zoo（KJ 二维反解，既有内核）。
# 5) 渲染：三模板四端口 MSLPort 全建 + excite_port 轮转
#    （_FOUR_PORT_ROTATION_TEMPLATES，9 列单激励 CSV，openems_rotation 进程
#    隔离装配 #208）；端口面贴 PML 边界（铁律 §3）；50Ω 馈线比耦合结构宽 →
#    馈线外推 + 横向搭接段（同心直连必短路），搭接段为 bend 族同类不连续性
#    （进冒烟偏差项，不进闭式）。lange air-bridge = 抬高薄金属
#    （z∈[H+g, H+g+t]）+ 竖直立柱（z∈[H, H+g]，不落 z=0 地面——落地即对地
#    短路）；同端两网络桥错位、两端分置，#212 bbox 连通审计恰判"两组 DC
#    隔离、组内全导通"。

_C4_C_MM_GHZ = 299.792458
_C4_COUPLER_TEMPLATES: tuple[str, ...] = ("cline_coupler", "branchline_2sect",
                                          "lange")
# 馈线内缘净距（mm）：两 50Ω 馈线并行段的耦合随缝宽指数衰减，5mm（≈10h）
# 下 ~50mm 并行长度串扰 <−45dB 量级（一阶口径）；同心直连（缝 0）必短路。
_C4_FEED_CLEAR_MM = 5.0
_C4_LANGE_BRIDGE_GAP_MM = 0.1        # 桥底面离金属面高度 g（mm）
_C4_LANGE_BRIDGE_T_MM = 0.05         # 桥金属厚 t（mm）
_C4_LANGE_BRIDGE_W_MM = 0.3          # 桥沿 y 宽 wb（mm）
_C4_LANGE_BRIDGE_INSET_MM = 0.25     # 端侧首桥中心离指端距离（mm）
_C4_LANGE_BRIDGE_STAGGER_MM = 0.55   # 同端 A/B 桥中心距（错位 > wb+净距）


def coupled_line_zee_zoo(coupling_db: float,
                         z0_ohm: float = 50.0) -> tuple[float, float, float]:
    """耦合线定向耦合器综合（Pozar §7.6）：C(dB) → (Z0e, Z0o, C)。

    C=10^(−C_dB/20)；Z0e=Z0√((1+C)/(1−C))、Z0o=Z0√((1−C)/(1+C))
    （匹配条件 Z0e·Z0o=Z0² 由构造保证）。C_dB>0（10 → 10dB 耦合器）。
    """
    c = 10.0 ** (-float(coupling_db) / 20.0)
    if not 0.0 < c < 1.0:
        raise ValueError(f"coupling_db={coupling_db} 须 >0（C∈(0,1)）")
    zee = float(z0_ohm) * math.sqrt((1.0 + c) / (1.0 - c))
    zoo = float(z0_ohm) * math.sqrt((1.0 - c) / (1.0 + c))
    return zee, zoo, c


def lange_pair_zee_zoo(coupling: float, z0_ohm: float = 50.0) -> tuple[float, float]:
    """四指 Lange 设计式（Pozar §7.6 Lange 节）：C → 相邻对 (Z0e, Z0o)。

    Z0e=Z0(4C−3+√(9−8C²))/(2C√((1−C)/(1+C)))、
    Z0o=Z0(4C+3−√(9−8C²))/(2C√((1+C)/(1−C)))。
    3dB（C=1/√2）→ (176.216, 52.609)Ω@50Ω（自洽校验见段首口径 3）。
    """
    c = float(coupling)
    if not 0.0 < c < 1.0:
        raise ValueError(f"coupling={coupling} 须在 (0,1)")
    if 8.0 * c * c >= 9.0:
        raise ValueError(f"coupling={coupling} 超出设计式可达（须 8C²<9）")
    rt = math.sqrt(9.0 - 8.0 * c * c)
    zee = (float(z0_ohm) * (4.0 * c - 3.0 + rt)
           / (2.0 * c * math.sqrt((1.0 - c) / (1.0 + c))))
    zoo = (float(z0_ohm) * (4.0 * c + 3.0 - rt)
           / (2.0 * c * math.sqrt((1.0 + c) / (1.0 - c))))
    return zee, zoo


def lange_equivalent_zee_zoo(zee_pair: float,
                             zoo_pair: float) -> tuple[float, float]:
    """四指 Lange 相邻对 (Z0e,Z0o) → 四线等效两线 (Ze4, Zo4)（Pozar §7.6）。

    Ze4=Z0e(Z0o+Z0e)/(3Z0o+Z0e)、Zo4=Z0o(Z0o+Z0e)/(3Z0e+Z0o)；其耦合
    C=(Ze4−Zo4)/(Ze4+Zo4)、Z0=√(Ze4·Zo4)（test_coupler2_templates 逐位钉）。
    """
    ze = float(zee_pair)
    zo = float(zoo_pair)
    if not ze > zo > 0.0:
        raise ValueError(f"须 Z0e > Z0o > 0，得 ({ze}, {zo})")
    s = ze + zo
    return ze * s / (3.0 * zo + ze), zo * s / (3.0 * ze + zo)


def branchline_2sect_impedances(z0_ohm: float = 50.0,
                                main_z_ratio: float = 1.0) -> tuple[float, float, float]:
    """两节分支线 f0 阻抗族（段首口径 2）：(Z_a, Z_b1, Z_b2)。

    Z_a=main_z_ratio·Z0（主线节）、Z_b1=(1+√2)Z0（外支臂）、
    Z_b2=√2·Z_a²/Z0（中支臂）。f0 处该族对任意 main_z_ratio>0 均给理想
    3dB 正交响应（匹配/隔离=0）；main_z_ratio=1 为 Pozar 经典点。
    """
    if float(main_z_ratio) <= 0.0:
        raise ValueError(f"main_z_ratio={main_z_ratio} 须 >0")
    za = float(main_z_ratio) * float(z0_ohm)
    zb1 = (1.0 + math.sqrt(2.0)) * float(z0_ohm)
    zb2 = math.sqrt(2.0) * za * za / float(z0_ohm)
    return za, zb1, zb2


def cline_coupler_design(coupling_db: float = 10.0, f0_ghz: float = 2.5,
                         z0_ohm: float = 50.0, *, er: float = 3.66,
                         h_mm: float = 0.508) -> dict[str, Any]:
    """耦合线定向耦合器综合链：C(dB) → (Z0e,Z0o) → KJ (w,s) → 几何。

    确定性映射（数值只在内核；口径见段首 1/4）。返回 {coupling_db, z0_ohm,
    f0_ghz, zee_ohm, zoo_ohm, c, w_mm, s_mm, zee_kj, zoo_kj, ere_e, ere_o,
    ere_avg, lc_mm, w_feed_mm, notes}。lc = λ/4 @ (εeff_e+εeff_o)/2（微带
    耦合段平均 εeff 口径，coupled_bpf 同源）。
    """
    from rfauto.core.synthesis import Stackup, inverse_width

    stackup = Stackup(name="cline_coupler", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    zee, zoo, c = coupled_line_zee_zoo(coupling_db, z0_ohm)
    w_mm, s_mm = coupled_bpf_width_gap_from_zee_zoo(zee, zoo, f0_ghz, er, h_mm)
    ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(w_mm, s_mm, f0_ghz,
                                                           er, h_mm)
    ere_avg = 0.5 * (ere_e + ere_o)
    lc_mm = _C4_C_MM_GHZ / (4.0 * float(f0_ghz) * math.sqrt(ere_avg))
    w_feed = float(inverse_width(float(z0_ohm), float(f0_ghz), stackup)[0])
    notes = [
        f"C={c:.5f}（{coupling_db}dB）→ (Z0e,Z0o)=({zee:.3f},{zoo:.3f})Ω"
        f"（Z0e·Z0o={zee * zoo:.1f}Ω²=Z0²）",
        f"KJ 二维反解 (w,s)=({w_mm:.4f},{s_mm:.4f})mm，回代"
        f" (Z0e,Z0o)=({ze:.3f},{zoo:.3f})Ω、εeff_e={ere_e:.4f}/"
        f"εeff_o={ere_o:.4f} → λ/4={lc_mm:.4f}mm",
        "非同步残差与假设清单见 openems_templates 文末 §C4 段首 1/5",
    ]
    return {"coupling_db": float(coupling_db), "z0_ohm": float(z0_ohm),
            "f0_ghz": float(f0_ghz), "zee_ohm": zee, "zoo_ohm": zoo, "c": c,
            "w_mm": w_mm, "s_mm": s_mm, "zee_kj": ze, "zoo_kj": zo,
            "ere_e": ere_e, "ere_o": ere_o, "ere_avg": ere_avg,
            "lc_mm": lc_mm, "w_feed_mm": w_feed, "notes": notes}


def lange_design(f0_ghz: float = 2.5, z0_ohm: float = 50.0,
                 coupling_db: float = 3.0103, *, er: float = 3.66,
                 h_mm: float = 0.508) -> dict[str, Any]:
    """Lange 电桥综合链：C → 相邻对 (Z0e,Z0o)（Pozar 设计式）→ 四线等效
    (Ze4,Zo4) → KJ (w,s) → 几何（口径见段首 3/4）。

    返回 {coupling_db, z0_ohm, f0_ghz, zee_pair_ohm, zoo_pair_ohm, ze4_ohm,
    zo4_ohm, c, w_mm, s_mm, ere_e, ere_o, finger_len_mm, w_feed_mm, notes}。
    """
    from rfauto.core.synthesis import Stackup, inverse_width

    stackup = Stackup(name="lange", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    c = 10.0 ** (-float(coupling_db) / 20.0)
    zee_p, zoo_p = lange_pair_zee_zoo(c, z0_ohm)
    ze4, zo4 = lange_equivalent_zee_zoo(zee_p, zoo_p)
    w_mm, s_mm = coupled_bpf_width_gap_from_zee_zoo(zee_p, zoo_p, f0_ghz,
                                                    er, h_mm)
    _ze_kj, _zo_kj, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
        w_mm, s_mm, f0_ghz, er, h_mm)
    finger_len = _C4_C_MM_GHZ / (4.0 * float(f0_ghz)
                                 * math.sqrt(0.5 * (ere_e + ere_o)))
    w_feed = float(inverse_width(float(z0_ohm), float(f0_ghz), stackup)[0])
    notes = [
        f"C={c:.6f} → 相邻对 (Z0e,Z0o)=({zee_p:.3f},{zoo_p:.3f})Ω → 四线等效"
        f" (Ze4,Zo4)=({ze4:.3f},{zo4:.3f})Ω（C 回代={(ze4 - zo4) / (ze4 + zo4):.6f}、"
        f"Z0=√(Ze4·Zo4)={math.sqrt(ze4 * zo4):.3f}Ω）",
        f"KJ 反解 (w,s)=({w_mm:.4f},{s_mm:.4f})mm（g=s/h={s_mm / h_mm:.3f}，"
        f"KJ 标称有效域下限 0.1 提示见段首 3）、指长 λ/4={finger_len:.4f}mm",
        "非相邻指耦合忽略；air-bridge 尺寸为 FDTD 网格尺度选择（真工艺 µm 级）；"
        "假设清单见 openems_templates 文末 §C4 段首 3",
    ]
    return {"coupling_db": float(coupling_db), "z0_ohm": float(z0_ohm),
            "f0_ghz": float(f0_ghz), "zee_pair_ohm": zee_p,
            "zoo_pair_ohm": zoo_p, "ze4_ohm": ze4, "zo4_ohm": zo4, "c": c,
            "w_mm": w_mm, "s_mm": s_mm, "ere_e": ere_e, "ere_o": ere_o,
            "finger_len_mm": finger_len, "w_feed_mm": w_feed, "notes": notes}


def branchline_2sect_design(f0_ghz: float = 2.5, z0_ohm: float = 50.0, *,
                            main_z_ratio: float = 1.0, er: float = 3.66,
                            h_mm: float = 0.508) -> dict[str, Any]:
    """两节分支线综合链：f0 阻抗族（段首口径 2）→ HJ 线宽 → λ/4 长度。

    main_z_ratio=1（Pozar 经典点）。支臂物理长 = 外/中支臂 λ/4 的算术平均
    （两支臂 εeff 不同 → λ/4 不同，矩形拓扑单跨度的固有二阶偏差 ≈±1.5%，
    段首口径 2）。返回 {f0_ghz, z0_ohm, za_ohm, zb1_ohm, zb2_ohm, w_main_mm,
    w_out_mm, w_mid_mm, w_feed_mm, sect_len_mm, branch_len_mm, ere_main,
    ere_out, ere_mid, notes}。
    """
    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    stackup = Stackup(name="branchline_2sect", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    za, zb1, zb2 = branchline_2sect_impedances(z0_ohm, main_z_ratio)
    lengths: list[float] = []
    eres: list[float] = []
    widths: list[float] = []
    for z in (za, zb1, zb2):
        w, _z_act, _st = inverse_width(z, float(f0_ghz), stackup)
        _z0v, ere = forward_z0(w, float(f0_ghz), stackup)
        widths.append(w)
        eres.append(ere)
        lengths.append(_C4_C_MM_GHZ / (4.0 * float(f0_ghz) * math.sqrt(ere)))
    w_feed = float(inverse_width(float(z0_ohm), float(f0_ghz), stackup)[0])
    notes = [
        f"两节族：Z_a={za:.2f}Ω（×{main_z_ratio}）、Z_b1=(1+√2)Z0={zb1:.2f}Ω、"
        f"Z_b2=√2·Z_a²/Z0={zb2:.2f}Ω（单参数族推导与 Microwaves101 独立表述"
        "一致，段首口径 2）",
        "HJ 线宽 (w_main,w_out,w_mid)=" + _fmt_list(widths, 4)
        + "mm，εeff=" + _fmt_list(eres, 4),
        f"λ/4: 主线 {lengths[0]:.4f}、外支臂 {lengths[1]:.4f}、中支臂 "
        f"{lengths[2]:.4f}mm → 支臂跨度取均值 "
        f"{0.5 * (lengths[1] + lengths[2]):.4f}mm（固有二阶偏差 "
        f"≈±{(lengths[1] - lengths[2]) / 2:.2%}，段首口径 2）",
    ]
    return {"f0_ghz": float(f0_ghz), "z0_ohm": float(z0_ohm), "za_ohm": za,
            "zb1_ohm": zb1, "zb2_ohm": zb2,
            "w_main_mm": widths[0], "w_out_mm": widths[1],
            "w_mid_mm": widths[2], "w_feed_mm": w_feed,
            "sect_len_mm": lengths[0],
            "branch_len_mm": 0.5 * (lengths[1] + lengths[2]),
            "ere_main": eres[0], "ere_out": eres[1], "ere_mid": eres[2],
            "notes": notes}


def coupled_line_coupler_sparams(
    freq_ghz: Any, zee_ohm: float, zoo_ohm: float, len_mm: float,
    ere_e: float, ere_o: float, *, synchronous_tem: bool = False,
    z_ref: float = 50.0,
) -> np.ndarray:
    """耦合线定向耦合器偶/奇模裁判（(n,4,4)；cline_coupler 与 lange 共用）。

    每耦合段 = 偶/奇模 2 端口叠加构造 4 端口（_coupled_section_s4，无耗/
    互易由构造保证）：端口 1/2=线 A 近/远端（输入/直通）、3/4=线 B 近/远端
    （耦合/隔离）。θ_e/θ_o = k0·l·√εeff_e / k0·l·√εeff_o（真非同步相速，
    coupled_bpf 同口径）；synchronous_tem=True 全段取平均 εeff（理想 TEM
    极限：f0 处精确 S11=S41=0、|S31|=C——教科书闭式裁判）。
    """
    import numpy as _np

    freqs = _np.atleast_1d(_np.asarray(freq_ghz, dtype=float))
    l_m = float(len_mm) * 1e-3
    out = _np.zeros((len(freqs), 4, 4), dtype=complex)
    for k, f_ghz in enumerate(freqs):
        k0 = 2.0 * math.pi * float(f_ghz) * 1e9 / 299792458.0
        if synchronous_tem:
            th = k0 * l_m * math.sqrt(0.5 * (float(ere_e) + float(ere_o)))
            the = tho = th
        else:
            the = k0 * l_m * math.sqrt(float(ere_e))
            tho = k0 * l_m * math.sqrt(float(ere_o))
        out[k] = _coupled_section_s4(zee_ohm, the, zoo_ohm, tho, z_ref)
    return out


def branchline_2sect_sparams(
    freq_ghz: Any, za_ohm: float, zb1_ohm: float, zb2_ohm: float,
    sect_len_mm: float, branch_len_mm: float, ere_main: float,
    ere_out: float, ere_mid: float, *, z_ref: float = 50.0,
) -> np.ndarray:
    """两节分支线偶/奇模二分裁判（(n,4,4)；闭式见段首口径 2）。

    半电路 ABCD(f) = 桩(Y_b1,θ_b1/2)·线(Z_a,θ_a)·桩(Y_b2,θ_b2/2)·线(Z_a,θ_a)
    ·桩(Y_b1,θ_b1/2)；各段电长按自身物理长+εeff 独立评估（几何参数变化有
    真实频响）。Γ/T 组合 S11=(Γe+Γo)/2、S21=(Te+To)/2、S31=(Te−To)/2、
    S41=(Γe−Γo)/2，矩形双镜面对称填满 4×4。
    """
    import numpy as _np

    freqs = _np.atleast_1d(_np.asarray(freq_ghz, dtype=float))
    la = float(sect_len_mm) * 1e-3
    lb = float(branch_len_mm) * 1e-3
    za, zb1, zb2 = float(za_ohm), float(zb1_ohm), float(zb2_ohm)
    out = _np.zeros((len(freqs), 4, 4), dtype=complex)

    def _line(zc: float, th: float) -> _np.ndarray:
        c, s = math.cos(th), math.sin(th)
        return _np.array([[c, 1j * zc * s], [1j * s / zc, c]])

    def _shunt(y: complex) -> _np.ndarray:
        return _np.array([[1.0, 0.0], [y, 1.0]])

    for k, f_ghz in enumerate(freqs):
        k0 = 2.0 * math.pi * float(f_ghz) * 1e9 / 299792458.0
        th_a = k0 * la * math.sqrt(float(ere_main))
        th_b1 = 0.5 * k0 * lb * math.sqrt(float(ere_out))   # 半支臂 λ/8
        th_b2 = 0.5 * k0 * lb * math.sqrt(float(ere_mid))
        modes = []
        for even in (True, False):
            y1 = (1j / zb1 * math.tan(th_b1) if even
                  else -1j / zb1 / math.tan(th_b1))
            y2 = (1j / zb2 * math.tan(th_b2) if even
                  else -1j / zb2 / math.tan(th_b2))
            m = (_shunt(y1) @ _line(za, th_a) @ _shunt(y2) @ _line(za, th_a)
                 @ _shunt(y1))
            a_, b_, c_, d_ = m[0, 0], m[0, 1], m[1, 0], m[1, 1]
            # ABCD→S（Pozar Table 4.2，参考阻抗 z_ref；B 阻抗形/C 导纳形）：
            # 阻抗按实际 Ω 入矩阵，归一化在此处一次完成（曾误按 Z0=1 归一
            # → S11≡0dB 全反射，fake 预跑抓出）
            den = a_ + b_ / z_ref + c_ * z_ref + d_
            modes.append(((a_ + b_ / z_ref - c_ * z_ref - d_) / den, 2.0 / den))
        ge, te = modes[0]
        go, to = modes[1]
        s = _np.zeros((4, 4), dtype=complex)
        s[0, 0] = s[1, 1] = s[2, 2] = s[3, 3] = (ge + go) / 2.0
        s[0, 1] = s[1, 0] = s[2, 3] = s[3, 2] = (te + to) / 2.0  # 直通对
        s[0, 2] = s[2, 0] = s[1, 3] = s[3, 1] = (te - to) / 2.0  # 耦合对
        s[0, 3] = s[3, 0] = s[1, 2] = s[2, 1] = (ge - go) / 2.0  # 隔离对
        out[k] = s
    return out


def _c4_feed_boxes(
    x_feed: float, wf: float, y_line_end: float, board: float,
    x_line: float, side: int, prefix: str,
) -> tuple[list[tuple[str, float, float, float, float, float, float]], float]:
    """馈线 + 横向搭接段盒清单（米；段首口径 5）。

    side=−1 近端（y<0）/ +1 远端；搭接段从馈线外缘跨到耦合结构中心线
    x_line（保重叠连通、离对侧结构 ≥ 线心距）。返回 (boxes, meas_shift)。
    z 仅存 0 占位（调用方统一填金属面 zm）。
    """
    y_inner = y_line_end + side * wf
    y_outer = float(board) * (1.0 if side > 0 else -1.0)
    lo_y, hi_y = min(y_inner, y_outer), max(y_inner, y_outer)
    if x_feed < 0.0:
        jx_lo, jx_hi = x_feed - wf / 2.0, x_line
    else:
        jx_lo, jx_hi = x_line, x_feed + wf / 2.0
    boxes = [(f"{prefix}_feed", x_feed - wf / 2.0, lo_y, 0.0,
              x_feed + wf / 2.0, hi_y, 0.0)]
    jy_lo, jy_hi = (y_inner, y_line_end) if side < 0 else (y_line_end, y_inner)
    boxes.append((f"{prefix}_jog", jx_lo, jy_lo, 0.0, jx_hi, jy_hi, 0.0))
    return boxes, (float(board) - abs(y_inner)) / 3.0


def _c4_layout(template: str, p: dict[str, Any]) -> dict[str, Any]:
    """§C4 三模板几何单一事实源（米）——render/_near_points/geometry_spec 共用。

    盒元组 = (名, x0, y0, z0, x1, y1, z1)；z 绝对高（0=地面、zm=金属面，
    官方顶面口径）；lange 桥 z∈[zm+g, zm+g+t]、立柱 z∈[zm, zm+g]（不落
    z=0 地面——落地即对地短路）。端口 start/stop=MSLPort 面（start 贴板边）。
    """
    zm = float(_DEFAULT_SUB["h_mm"]) * 1e-3
    board = 0.060
    if template == "cline_coupler":
        w = float(p.get("w_mm", CLINE_COUPLER_NOMINAL["w_mm"])) * 1e-3
        s = float(p.get("gap_mm", CLINE_COUPLER_NOMINAL["gap_mm"])) * 1e-3
        lc = float(p.get("coupled_len_mm",
                         CLINE_COUPLER_NOMINAL["coupled_len_mm"])) * 1e-3
        wf = float(p.get("w_feed_mm",
                         CLINE_COUPLER_NOMINAL["w_feed_mm"])) * 1e-3
        if min(w, s, lc, wf) <= 0.0:
            raise ValueError("cline_coupler 几何须 >0")
        clear = _C4_FEED_CLEAR_MM * 1e-3
        d = w + s
        xa, xb = -d / 2.0, d / 2.0
        xf_a = -(wf / 2.0 + clear / 2.0)
        xf_b = -xf_a
        boxes: list[tuple[str, float, float, float, float, float, float]] = [
            ("line_a", xa - w / 2.0, -lc / 2.0, zm, xa + w / 2.0, lc / 2.0, zm),
            ("line_b", xb - w / 2.0, -lc / 2.0, zm, xb + w / 2.0, lc / 2.0, zm),
        ]
        ports: list[dict[str, Any]] = []
        for (nr, x_line, x_feed, y_end, side, label) in (
                (1, xa, xf_a, -lc / 2.0, -1, "输入（线 A 近端）"),
                (2, xa, xf_a, lc / 2.0, +1, "直通（线 A 远端）"),
                (3, xb, xf_b, -lc / 2.0, -1, "耦合（线 B 近端）"),
                (4, xb, xf_b, lc / 2.0, +1, "隔离（线 B 远端）")):
            fb, meas = _c4_feed_boxes(x_feed, wf, y_end, board, x_line, side,
                                      f"feed_p{nr}")
            for bx in fb:
                boxes.append((bx[0], bx[1], bx[2], zm, bx[4], bx[5], zm))
            if side < 0:
                start = (x_feed + wf / 2.0, -board)
                stop = (x_feed - wf / 2.0, y_end - wf)
            else:
                start = (x_feed - wf / 2.0, board)
                stop = (x_feed + wf / 2.0, y_end + wf)
            ports.append({"nr": nr, "label": label,
                          "start": [start[0], start[1], zm],
                          "stop": [stop[0], stop[1], zm],
                          "prop_dir": "y", "meas_shift": meas})
        return {"boxes": boxes, "ports": ports, "z_lines": []}
    if template == "branchline_2sect":
        wm = float(p.get("w_main_mm",
                         BRANCHLINE_2SECT_NOMINAL["w_main_mm"])) * 1e-3
        wo = float(p.get("w_out_mm",
                         BRANCHLINE_2SECT_NOMINAL["w_out_mm"])) * 1e-3
        wc = float(p.get("w_mid_mm",
                         BRANCHLINE_2SECT_NOMINAL["w_mid_mm"])) * 1e-3
        la = float(p.get("sect_len_mm",
                         BRANCHLINE_2SECT_NOMINAL["sect_len_mm"])) * 1e-3
        lb = float(p.get("branch_len_mm",
                         BRANCHLINE_2SECT_NOMINAL["branch_len_mm"])) * 1e-3
        wf = float(p.get("w_feed_mm",
                         BRANCHLINE_2SECT_NOMINAL["w_feed_mm"])) * 1e-3
        if min(wm, wo, wc, la, lb, wf) <= 0.0:
            raise ValueError("branchline_2sect 几何须 >0")
        yt, yb = lb / 2.0, -lb / 2.0
        boxes = [
            ("arm_top（Z_a 主线）", -la - wo / 2.0, yt - wm / 2.0, zm,
             la + wo / 2.0, yt + wm / 2.0, zm),
            ("arm_bottom（Z_a 主线）", -la - wo / 2.0, yb - wm / 2.0, zm,
             la + wo / 2.0, yb + wm / 2.0, zm),
            ("branch_out_left（Z_b1 外支臂）", -la - wo / 2.0, yb, zm,
             -la + wo / 2.0, yt, zm),
            ("branch_out_right（Z_b1 外支臂）", la - wo / 2.0, yb, zm,
             la + wo / 2.0, yt, zm),
            ("branch_mid（Z_b2 中支臂）", -wc / 2.0, yb, zm, wc / 2.0, yt, zm),
        ]
        meas = (board - la) / 3.0
        ports = []
        for (nr, y_c, label) in ((1, yt, "输入（左上）"),
                                 (2, yt, "直通（右上）"),
                                 (3, yb, "耦合（右下）"),
                                 (4, yb, "隔离（左下）")):
            sign = 1.0 if nr in (2, 3) else -1.0
            if sign > 0:
                x_face, x_joint = board, la
                start = (board, y_c - wf / 2.0)
                stop = (la, y_c + wf / 2.0)
            else:
                x_face, x_joint = -board, -la
                start = (-board, y_c + wf / 2.0)
                stop = (-la, y_c - wf / 2.0)
            boxes.append((f"feed_p{nr}", min(x_face, x_joint),
                          y_c - wf / 2.0, zm, max(x_face, x_joint),
                          y_c + wf / 2.0, zm))
            ports.append({"nr": nr, "label": label,
                          "start": [start[0], start[1], zm],
                          "stop": [stop[0], stop[1], zm],
                          "prop_dir": "x", "meas_shift": meas})
        return {"boxes": boxes, "ports": ports, "z_lines": []}
    if template == "lange":
        w = float(p.get("w_mm", LANGE_NOMINAL["w_mm"])) * 1e-3
        s = float(p.get("gap_mm", LANGE_NOMINAL["gap_mm"])) * 1e-3
        lf = float(p.get("finger_len_mm",
                         LANGE_NOMINAL["finger_len_mm"])) * 1e-3
        wf = float(p.get("w_feed_mm", LANGE_NOMINAL["w_feed_mm"])) * 1e-3
        if min(w, s, lf, wf) <= 0.0:
            raise ValueError("lange 几何须 >0")
        d = w + s
        xs = [(k - 1.5) * d for k in range(4)]    # 四指中心（外指承馈）
        # c4-去桥单变量对照旋钮（wf:c4-debridge，2026-09-19）：params["_bridge"]
        # =0 → 桥金属盒+立柱盒全部不渲染、z_lines 同步清空（桥面 z 网格线随之
        # 消失，_near_y 亦不再含桥 y 缘——单变量="无 air-bridge"）；缺省 1=逐
        # 字节不变（render_base_lange.py 快照自证）。关位 0 是合法值，禁用
        # `or` 缺省惯语（#117 falsy 陷阱）。去桥后指 2/3 无馈无桥=悬浮 PEC
        # （FDTD 良定：PEC 感应电流合法、无需 DC 通路）；连通性/网格逐条审计
        # 归档 runs/c4_debridge/。
        _bridge_on = bool(p.get("_bridge", 1))
        gb = _C4_LANGE_BRIDGE_GAP_MM * 1e-3
        tb = _C4_LANGE_BRIDGE_T_MM * 1e-3
        wb = _C4_LANGE_BRIDGE_W_MM * 1e-3
        ins = _C4_LANGE_BRIDGE_INSET_MM * 1e-3
        stag = _C4_LANGE_BRIDGE_STAGGER_MM * 1e-3
        boxes = [(f"finger_{k + 1}", xs[k] - w / 2.0, -lf / 2.0, zm,
                  xs[k] + w / 2.0, lf / 2.0, zm) for k in range(4)]
        # 桥（两端 × 网络 A=指 1/3、B=指 2/4）：同端 A/B 错位（bbox 不交，
        # #212 审计判两组 DC 隔离）；桥底 z=zm+g、立柱 z∈[zm, zm+g] 不落地
        for (yk, fingers, tag) in (
                (-lf / 2.0 + ins, (0, 2), "a"),
                (-lf / 2.0 + ins + stag, (1, 3), "b"),
                (lf / 2.0 - ins - stag, (1, 3), "b2"),
                (lf / 2.0 - ins, (0, 2), "a2")):
            x_lo = min(xs[fingers[0]], xs[fingers[1]]) - w / 2.0
            x_hi = max(xs[fingers[0]], xs[fingers[1]]) + w / 2.0
            boxes.append((f"bridge_{tag}", x_lo, yk - wb / 2.0, zm + gb,
                          x_hi, yk + wb / 2.0, zm + gb + tb))
            for k in fingers:
                boxes.append((f"post_{tag}_f{k + 1}", xs[k] - w / 2.0,
                              yk - wb / 2.0, zm, xs[k] + w / 2.0,
                              yk + wb / 2.0, zm + gb))
        clear = _C4_FEED_CLEAR_MM * 1e-3
        xf_a = -(wf / 2.0 + clear / 2.0)
        xf_b = -xf_a
        ports = []
        for (nr, k_f, y_end, x_feed, side, label) in (
                (1, 0, -lf / 2.0, xf_a, -1, "输入（指1近端）"),
                (2, 0, lf / 2.0, xf_a, +1, "直通（指1远端）"),
                (3, 3, -lf / 2.0, xf_b, -1, "耦合（指4近端）"),
                (4, 3, lf / 2.0, xf_b, +1, "隔离（指4远端）")):
            fb, meas = _c4_feed_boxes(x_feed, wf, y_end, board, xs[k_f],
                                      side, f"feed_p{nr}")
            for bx in fb:
                boxes.append((bx[0], bx[1], bx[2], zm, bx[4], bx[5], zm))
            if side < 0:
                start = (x_feed + wf / 2.0, -board)
                stop = (x_feed - wf / 2.0, y_end - wf)
            else:
                start = (x_feed - wf / 2.0, board)
                stop = (x_feed + wf / 2.0, y_end + wf)
            ports.append({"nr": nr, "label": label,
                          "start": [start[0], start[1], zm],
                          "stop": [stop[0], stop[1], zm],
                          "prop_dir": "y", "meas_shift": meas})
        if not _bridge_on:
            boxes = [b for b in boxes
                     if not b[0].startswith(("bridge_", "post_"))]
        return {"boxes": boxes, "ports": ports,
                "z_lines": [zm + gb, zm + gb + tb] if _bridge_on else []}
    raise ValueError(f"未知 §C4 模板: {template}（可用 {_C4_COUPLER_TEMPLATES}）")


_C4_COUPLED_BOX_PREFIX: tuple[str, ...] = ("line_", "finger_")


def _c4_gap_midlines(boxes: list[tuple[str, float, float, float,
                                        float, float, float]]) -> list[float]:
    """§C4 相邻耦合导体（line_*/finger_*）x 向缝中点列表（米）——缝中线加密。

    按 x0 排序后相邻两盒 x1<x0' 即一条缝，取中点；branchline_2sect 无耦合缝
    返回空。cline_coupler 缝中点=0（nx 本已含）、lange 三缝中点 0/±(w+s)/2。
    """
    cond = sorted((b for b in boxes if b[0].startswith(_C4_COUPLED_BOX_PREFIX)),
                  key=lambda b: b[1])
    return [(a[4] + b[1]) / 2.0 for a, b in pairwise(cond) if b[1] > a[4]]


def _c4_body_lines(template: str, p: dict[str, Any]) -> str:
    """§C4 三模板渲染几何段（布局字面量 + excite_port 轮转激励 + priority 收口）。"""
    lay = _c4_layout(template, p)
    ep = max(1, min(4, int(p.get("_excite_port", 1) or 1)))
    out: list[str] = [f"EP = {ep}",
                      f'{template} = CSX.AddMetal("{template}")']
    for (nm, x0, y0, z0, x1, y1, z1) in lay["boxes"]:
        out.append(f"{template}.AddBox(({x0!r}, {y0!r}, {z0!r}), "
                   f"({x1!r}, {y1!r}, {z1!r}), priority=10)  # {nm}")
    for pt in lay["ports"]:
        sx, sy, _ = pt["start"]
        tx, ty, _ = pt["stop"]
        out.append(
            f'_port{pt["nr"]} = MSLPort(CSX, port_nr={pt["nr"]}, '
            f"metal_prop={template},\n"
            f"                 start=np.array([{sx!r}, {sy!r}, H_SUB]),\n"
            f"                 stop=np.array([{tx!r}, {ty!r}, 0]),\n"
            f'                 prop_dir="{pt["prop_dir"]}", exc_dir="z", '
            f"excite=1 if EP == {pt['nr']} else 0,\n"
            f"                 FeedShift=10 * NEAR, "
            f'MeasPlaneShift={float(pt["meas_shift"])!r}, priority=10)')
    out.append(f"for _prim in {template}.GetAllPrimitives():\n"
               "    if _prim.GetPriority() < 10:\n"
               "        _prim.SetPriority(10)")
    return "\n".join(out) + "\n"


def _cline_coupler_lines(p: dict[str, Any]) -> str:
    # 耦合线定向耦合器（§C4 口径 1）：两条 λ/4 平行线（KJ (w,s)），四端口
    # 全建（后向波：1 输入/2 直通/3 耦合近端/4 隔离远端）；50Ω 馈线外推+
    # 横向搭接段（同心直连短路）。几何单源 _c4_layout。
    return _c4_body_lines("cline_coupler", p)


def _branchline_2sect_lines(p: dict[str, Any]) -> str:
    # 两节分支线（§C4 口径 2）：主线 Z_a 两节 + 外/中支臂 Z_b1/Z_b2，四角
    # 50Ω 馈线沿 x 引出（P1 左上输入/P2 右上直通/P3 右下耦合/P4 左下隔离）。
    # 支臂跨度 = 两支臂 λ/4 均值（固有二阶偏差 ±1.5%，段首口径 2）。
    return _c4_body_lines("branchline_2sect", p)


def _lange_lines(p: dict[str, Any]) -> str:
    # 展开型 Lange 电桥（§C4 口径 3）：四指交替并联（网络 A=指1/3、B=指2/4），
    # 桥=抬高薄金属+竖直立柱（同端 A/B 桥错位、两端分置——#212 bbox 审计
    # 判两组 DC 隔离）；外指承馈 P1/P2/P3/P4。params["_bridge"]=0 → 去桥
    # 对照变体（单变量，判据 runs/c4_debridge/criteria.md）。
    return _c4_body_lines("lange", p)


# ── 名义设计点（设计函数 @2.5GHz rogers4350b 的 4 位舍入；再生口径由
# test_coupler2_templates 逐键钉住：round(设计函数, 4) == 标称 逐位）──
CLINE_COUPLER_NOMINAL: dict[str, Any] = {
    # C=10^(−10/20)=0.31623 → (Z0e,Z0o)=(69.371,36.038)Ω → KJ 反解 (w,s)
    "w_mm": 0.9243,
    "gap_mm": 0.082,
    # λ/4 @ (εeff_e+εeff_o)/2=2.7292 → 18.1469mm
    "coupled_len_mm": 18.1469,
    "w_feed_mm": 1.1117,
}

BRANCHLINE_2SECT_NOMINAL: dict[str, Any] = {
    # Pozar 经典点 (Z_a,Z_b1,Z_b2)=(50,120.71,70.71)Ω → HJ 线宽
    "w_main_mm": 1.1117,
    "w_out_mm": 0.162,
    "w_mid_mm": 0.6024,
    "w_feed_mm": 1.1117,
    # 主线节 λ/4（εeff=2.8579）；支臂跨度=(18.7144+18.1465)/2（外/中支臂均值）
    "sect_len_mm": 17.7338,
    "branch_len_mm": 18.4304,
}

LANGE_NOMINAL: dict[str, Any] = {
    # C=1/√2 → 相邻对 (176.216,52.609)Ω → KJ 反解（g=s/h=0.076 提示见段首 3）
    "w_mm": 0.1672,
    "gap_mm": 0.0386,
    # 指长 λ/4 @ (εeff_e+εeff_o)/2=2.4972 → 18.9712mm
    "finger_len_mm": 18.9712,
    "w_feed_mm": 1.1117,
}

CLINE_COUPLER_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 4,
    "extraction": "全 S 矩阵 4×4 @ .s4p（excite_port 轮转 4 run，#208 进程隔离"
                  "；同 ratrace footer 9 列单激励 CSV）。裁判=偶/奇模频响"
                  " coupled_line_coupler_sparams（Pozar §7.6 闭式）：f0 处"
                  " |S31|=C、S21=−j√(1−C²)、S11=S41=0（同步极限）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "gap_mm", "coupled_len_mm", "w_feed_mm"],
    "topology": "耦合线定向耦合器（后向波，C4 族）：两条 λ/4 平行耦合线"
                "（KJ (w,s) 反解）+ 四条 50Ω 馈线外推+横向搭接段（同心直连"
                "短路）；1=输入/2=直通（线 A 远端）/3=耦合（线 B 近端，与"
                "输入同侧）/4=隔离",
    "param_semantics": "w_mm=耦合段单线宽，gap_mm=耦合缝（边到边），"
                       "coupled_len_mm=耦合段物理长（λ/4 @平均 εeff），"
                       "w_feed_mm=50Ω 馈线宽——fake/openEMS 两通道同名同语义",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "全部盒缘精确入网（#198；_c4_layout 单源）",
    "smoke_note": "真机未跑（followUp）：非同步残差预期 S41≈−23dB/S11≈−33dB"
                  "（定向性 ≈13dB，微带耦合线固有，段首口径 1），冒烟按此判读",
}

BRANCHLINE_2SECT_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 4,
    "extraction": "全 S 矩阵 4×4 @ .s4p（excite_port 轮转 4 run，#208）。"
                  "裁判=偶/奇模二分频响 branchline_2sect_sparams（Pozar §7.5"
                  " 推广 + Levy & Lind 1968）：f0 处 |S21|=|S31|=−3.01dB、"
                  "S11=S41=0；两节 ≥ 单节带宽（±1dB 均分 35.0% vs 25.8%）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_main_mm", "w_out_mm", "w_mid_mm", "sect_len_mm",
               "branch_len_mm", "w_feed_mm"],
    "topology": "两节分支线 3dB 正交耦合器（C4 族，Pozar 经典点）：主线 Z_a"
                "=Z0 两节 + 外支臂 (1+√2)Z0 + 中支臂 √2·Z_a²/Z0（单参数族，"
                "main_z_ratio 可调）；四角 50Ω 馈线沿 x 引出，P1 左上输入/"
                "P2 右上直通/P3 右下耦合/P4 左下隔离",
    "param_semantics": "w_main_mm/w_out_mm/w_mid_mm=主线/外支臂/中支臂线宽"
                       "（HJ 精算），sect_len_mm=主线节长（λ/4 @εeff(Z_a)），"
                       "branch_len_mm=支臂跨度（外/中支臂 λ/4 均值——两支臂"
                       "εeff 不同致 ≈±1.5% 固有二阶偏差，段首口径 2），"
                       "w_feed_mm=50Ω 馈线宽",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "全部盒缘精确入网（#198；_c4_layout 单源）",
    "smoke_note": "真机未跑（followUp）：预期引擎偏差项=T 结不连续性+拐角"
                  "（理想闭式不含），冒烟对照 branchline 单节同门",
}

LANGE_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 4,
    "extraction": "全 S 矩阵 4×4 @ .s4p（excite_port 轮转 4 run，#208）。"
                  "裁判=四线等效两线偶/奇模频响（Pozar §7.6 Lange 节设计式"
                  "自洽回代 C/Z0 逐位闭合）：f0 处 |S21|=|S31|=−3.01dB、"
                  "S31=+1/√2（耦合同相）、S21=−j/√2、S11=S41=0",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "gap_mm", "finger_len_mm", "w_feed_mm"],
    "topology": "展开型 Lange 电桥（3dB 正交，C4 族）：四指交替并联（网络 A="
                "指1/3、B=指2/4，DC 隔离），air-bridge=抬高薄金属+竖直立柱"
                "（同端 A/B 桥错位、两端分置）；外指承馈 P1/P2/P3/P4，等效"
                "两线 (Ze4,Zo4)=(120.71,20.71)Ω 精确成立",
    "param_semantics": "w_mm=单指宽，gap_mm=指缝（边到边；3dB 于本叠层 "
                       "s=0.0386mm，g=s/h=0.076 略低于 KJ 标称有效域下限 0.1，"
                       "段首口径 3 如实记录），finger_len_mm=指长（λ/4 @平均 "
                       "εeff），w_feed_mm=50Ω 馈线宽",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "指缝/桥/立柱盒缘精确入网（#198；air-bridge z 底/顶面入网）",
    "smoke_note": "真机未跑（followUp）：指缝 38.6µm 小于 0.4mm 审计网格"
                  "（near 加密入网）；桥缝耦合寄生于理想裁判之外，冒烟按 "
                  "g=0.076 提示与一阶口径判读",
}

# ── 注册（2026-09-16）：C4 耦合器族 II 三模板升格正式注册 ──
# 四处同步：① docs/templates/{cline_coupler,branchline_2sect,lange}/meta.yaml；
# ② test_template_geometry_audit.EXPECTED_TEMPLATES（HEAD 25 → 合流时实际值，
# 同轮 C3/CPS 等多轨在制、计数以合流实测为准，不得写死）；③ fake_adapter
# 派发分支；④ models/template_specs（_register_cline_coupler/_register_
# branchline_2sect/_register_lange）。同对象注册（非拷贝）钉死单一事实源。
TEMPLATE_META["cline_coupler"] = CLINE_COUPLER_META
TEMPLATE_NOMINAL["cline_coupler"] = CLINE_COUPLER_NOMINAL
TEMPLATE_META["branchline_2sect"] = BRANCHLINE_2SECT_META
TEMPLATE_NOMINAL["branchline_2sect"] = BRANCHLINE_2SECT_NOMINAL
TEMPLATE_META["lange"] = LANGE_META
TEMPLATE_NOMINAL["lange"] = LANGE_NOMINAL

# ══ SIW 族首族：直 SIW 传输线段（2026-09-22 siw-family 立项）══════════════════
# 权威口径：runs/siw_family/criteria.md（文献双源/闭式/激励方案利弊/预声明门全账）。
# 结构：基板 z∈[0,h]（上下显式零厚金属板贴 z 边界 PEC——与边界等电势冗余，使
# 桥-板-过孔连通图物理化）+ 两列金属化过孔 PEC 圆柱（x=±w/2，心距 s，贯通
# 全域直入 PML——slotline_lumped"匹配端接"口径，端口背后无开路 stub/短路面）。
# 端口：两端 LumpedPort z 桥（中线 x=0、跨全高；TE10 的 E_z 沿 z 在中线最大，
# 带内高阶模全倏逝——criteria.md §3），R=闭式 Z_PV=2b·Z_TE/w_eff。
# 域：x 半宽 = w/2 + w_eff/2（藩篱外倏逝尾 e^−π≈4% 处截断，侧界 MUR 吸收
# 泄漏）；y 半宽 = line_len/2 + 16·BASE（端口出 PML_8，slotline_lumped
# PORT_INSET_BASE=16 先例）——BOARD=60e-3 共享字面量对本模板不适用（自动档
# 约 20M cells 超预算），DOM_X/DOM_Y 由 layout 字面注入（机制层 per-template
# 分支，他模板渲染文本逐字节不变）。
# β 判读：LumpedPort 无 beta 属性（cps 同坑）→ port_beta.csv 落端口元 y 坐标
# + plane_dist_m（cps 契约复用）；WaveguidePort 解析 β=闭式自证不可作判据
# （criteria.md §3 弃用理由 2，#118 不自证）。
# 端口方案 v2（2026-09-23 df5-SE，runs/siw_family/v2_criteria.md）：opt-in
# 旋钮 params["_port_mode"]="v2"=藩篱止于端口面+端面口径 LumpedPort（跨介质
# 孔径 ±W/2、R=Z_PV 不变）——按原 G3 门重裁的 §R2 路线；缺省 v1 渲染逐字节
# 不变（字节钉 test_siw_v1_default_render_byte_pin）。

_SIW_PORT_INSET_BASE = 16.0   # 端口面→y 域边界净距（×BASE；PML_8≈8·BASE 的 2×）
_SIW_MESH_FLOOR_M = 10e-6     # 显式近场线最小间距地板（#349，渲染期 ValueError）


def _siw_r_port_ohm(w_mm: float, d_mm: float, s_mm: float, epsilon_r: float,
                    h_mm: float, f0_ghz: float) -> float:
    """LumpedPort R = 等效 RWG TE10 功率-电压阻抗 Z_PV=2·b·Z_TE/w_eff（Ω）。

    确定性闭式（#7）：V=中线全高电压=E0·b、P=E0²·a·b/(4·Z_TE) 消元 ⇒
    Z_PV=2b·Z_TE/w_eff，Z_TE=ωμ0/β（criteria.md §2；与 OE 锚判读同源）。
    """
    from rfauto.core.calculators import siw_beta_rad_m, siw_effective_width_mm

    weff_mm = siw_effective_width_mm(w_mm, d_mm, s_mm)
    beta, _fc = siw_beta_rad_m(weff_mm, epsilon_r, f0_ghz)
    if not (math.isfinite(beta) and beta > 0.0):
        raise ValueError(
            f"siw: 频带中心 {f0_ghz}GHz 低于 TE10 截止（fc10={_fc:.4f}GHz）"
            "——SIW 线段必须工作在传播区")
    z_te = 2.0 * math.pi * f0_ghz * 1e9 * 1.25663706212e-6 / beta
    return 2.0 * float(h_mm) * 1e-3 * z_te / (weff_mm * 1e-3)


def siw_layout(params: dict[str, Any], freq_range_ghz: tuple[float, float],
               base_m: float, h_m: float) -> dict[str, Any]:
    """直 SIW 线段几何/端口/域单一事实源（mm 入参 → 米字面量 + 守卫）。

    所有名义派生量（w_eff/β/λg/R_port/过孔栅格/端口盒）在此一次计算，body/
    近场线/机制分支（DOM_X/DOM_Y、substrate、z 网格）同源消费——#198/#212
    单源纪律。设计规则违规/网格欠分辨显式 ValueError 拒渲染。
    """
    from rfauto.core.calculators import (
        siw_beta_rad_m,
        siw_check_design_rules,
        siw_effective_width_mm,
    )

    w = float(params.get("w_mm", 12.1317)) * 1e-3
    d = float(params.get("d_mm", 0.6)) * 1e-3
    s = float(params.get("s_mm", 1.0)) * 1e-3
    line_len = float(params.get("line_len_mm", 63.0724)) * 1e-3
    er = float(params.get("er", _DEFAULT_SUB["er"]))
    f0 = 0.5 * (float(freq_range_ghz[0]) + float(freq_range_ghz[1])) * 1e9
    if not (math.isfinite(line_len) and line_len > 0.0):
        raise ValueError(f"siw_layout: line_len_mm 必须为正有限，得到 {line_len!r}")
    if not (math.isfinite(base_m) and base_m > 0.0):
        raise ValueError(f"siw_layout: base 必须为正有限，得到 {base_m!r}")
    if not (math.isfinite(h_m) and h_m > 0.0):
        raise ValueError(f"siw_layout: h 必须为正有限，得到 {h_m!r}")
    # 设计规则（双源出处 criteria.md §1）：违规拒渲染
    siw_check_design_rules(w * 1e3, d * 1e3, s * 1e3, er, freq_ghz=f0 / 1e9)
    weff = siw_effective_width_mm(w * 1e3, d * 1e3, s * 1e3) * 1e-3
    if not weff > 0.0:
        raise ValueError(f"siw_layout: 等效宽度非正 w_eff={weff!r}")
    beta, fc10 = siw_beta_rad_m(weff * 1e3, er, f0 / 1e9)
    if not (math.isfinite(beta) and beta > 0.0):
        raise ValueError(
            f"siw_layout: 频带中心 {f0 / 1e9:.4g}GHz 低于 TE10 截止 "
            f"fc10={fc10:.4f}GHz（线段必须工作在传播区）")
    near = base_m / 4.0
    # 过孔可分辨守卫（criteria §4.2）：直径 ≥4·NEAR（2 格硬下限的 2× 余量）
    if not d >= 4.0 * near:
        raise ValueError(
            f"siw_layout: 网格欠分辨——过孔直径 d={d * 1e3:.4g}mm < "
            f"4·NEAR={4.0 * near * 1e3:.4g}mm（BASE={base_m * 1e3:.4g}mm；"
            "收紧 mesh_resolution_mm）")
    # 孔间缝渲染守卫（#311 先例口径，round6 B-LOW#4）：相邻过孔缝隙 s−d
    # 须容得下 ≥1 内部网格线——SmoothMeshLines 只细分 >NEAR 的区间（#311），
    # 缝 ≤ NEAR ⇒ 缝内零内部线（缝缘线不算），藩篱等效面/泄漏建模粗。
    # 判据=严格 >（含 1e-9 浮点余量，与 #266/#283 同一口径）
    via_gap = s - d
    if not via_gap > near * (1.0 + 1e-9):
        raise ValueError(
            f"siw_layout: 孔间缝 s−d={via_gap * 1e3:.4g}mm ≤ NEAR="
            f"{near * 1e3:.4g}mm（BASE={base_m * 1e3:.4g}mm）——缝内零内部"
            "网格线（#311 先例口径：SmoothMesh 不细分 ≤NEAR 区间），藩篱"
            f"泄漏建模粗；收紧 mesh_resolution_mm ≤ "
            f"{4.0 * via_gap * 1e3:.4g}mm 或加大 s−d（设计规则域内）")
    # 端口方案旋钮（runs/siw_family/v2_criteria.md §1/§2，2026-09-23 df5-SE
    # 批；criteria.md §R2 归因裁定后用户选 v2 路线）：
    #   v1（缺省）=z 桥探针悬在贯通 PML 的连续 SIW 中间——端面三支路节点分光，
    #     fixture 汇 ≥0.385，理想探针天花板 −3.10dB（§R2 构造性证明）；
    #   v2=藩篱止于端口面+端面口径 LumpedPort（跨介质孔径 ±W/2）——端口即终端
    #     负载而非中间抽头，消除"端口背后 3.5mm 延拓"与探针耗散两条结构性
    #     吞噬路径；R=Z_PV 闭式不变（v2_criteria.md §2 选型论证）。
    #   其他值显式拒绝（不静默回退）。
    port_mode = str(params.get("_port_mode", "v1"))
    if port_mode not in ("v1", "v2"):
        raise ValueError(
            f"siw_layout: _port_mode 只接受 'v1'/'v2'，得到 {port_mode!r}")
    rx = near if port_mode == "v1" else w / 2.0
    # 端口盒 x 半宽（#283 盒边=结构线：v1=NEAR 窄桥 2 格；v2=跨介质孔径 ±W/2，
    # 复用过孔列心线零新增网格线）
    py = near                       # 端口盒 y 半长
    port_inset = _SIW_PORT_INSET_BASE * base_m
    y1 = -line_len / 2.0
    y2 = line_len / 2.0
    dom_x = w / 2.0 + weff / 2.0    # 侧界 MUR：藩篱外倏逝尾 e^−π≈4% 截断
    if port_mode == "v1":
        # 过孔藩篱贯通全域直入 PML（端口背后=匹配端接，无短路面/开路 stub）；
        # 心距取精确 s 的全域栅格：y_k = k·s，覆盖 |y| ≤ K·s ≥ line_len/2+
        # port_inset；dom_y 吸收藩篱端孔外缘（结构线不得越出域界——SmoothMesh
        # 会把网格撑到结构线处，域变量与实际网格必须一致，#212 审计④口径）
        dom_y_min = line_len / 2.0 + port_inset
        k_half = math.ceil(dom_y_min / s - 1e-9)
        dom_y = max(dom_y_min, k_half * s + d / 2)
    else:
        # v2（v2_criteria.md §1）：藩篱止于端口面——过孔只在 |k·s|+d/2 ≤
        # line_len/2 线段区（末孔缘不越端口面），端口面背后直接是基板平行板
        # 区入 PML_8（无 SIW 延拓支路）；dom_y=端口面+16·BASE 精确值
        # （无藩篱端孔要吸收，全部结构线 < dom_y，#212 审计④仍闭合）
        dom_y = line_len / 2.0 + port_inset
        k_half = math.floor((line_len / 2.0 - d / 2) / s + 1e-9)
        if k_half < 1:
            raise ValueError(
                f"siw_layout: v2 藩篱止于端口面后无线段区过孔（line_len/2−d/2="
                f"{(line_len / 2.0 - d / 2) * 1e3:.4g}mm < s={s * 1e3:.4g}mm）"
                "——加大 line_len_mm")
        if not k_half * s + d / 2 < line_len / 2.0:
            raise ValueError(
                f"siw_layout: v2 末孔缘 {k_half * s + d / 2!r} 越过端口面 "
                f"{line_len / 2.0!r}（数值容差外）")
    via_y = tuple(k * s for k in range(-k_half, k_half + 1))
    # 显式近场线集最小间距地板（#349，渲染期确定性守卫）：x 集=过孔列三线对
    # （±(w/2∓d/2)、±w/2）+ 端口盒边，y 集=每孔三线（k·s∓d/2、k·s）+
    # 端口盒边——与 _near_points 注入集合同源（v2 端口盒边=±w/2 与列心线
    # 是同一条结构线：set 去重后守卫，重合不是近撞；v1 无重合逐字节原路径）
    x_lines = [0.0, w / 2 - d / 2, w / 2, w / 2 + d / 2,
               rx, -rx]
    y_lines = [y1 - py, y1, y1 + py, y2 - py, y2, y2 + py]
    for _yk in via_y:
        y_lines += [_yk - d / 2, _yk, _yk + d / 2]
    for _name, _lines in (("x", x_lines), ("y", y_lines)):
        _arr = sorted(_lines if port_mode == "v1" else set(_lines))
        _gaps = [b - a for a, b in pairwise(_arr)]
        _gmin = min(_gaps) if _gaps else float("inf")
        if not _gmin > _SIW_MESH_FLOOR_M:
            raise ValueError(
                f"siw_layout: {_name} 向显式网格线最小间距 {_gmin * 1e6:.3f}µm "
                f"≤ {_SIW_MESH_FLOOR_M * 1e6:.0f}µm 地板（#349 CFL 塌缩守卫；"
                "过孔栅格/端口盒与结构线近撞，调整 d/s/line_len）")
    r_port = _siw_r_port_ohm(w * 1e3, d * 1e3, s * 1e3, er, h_m * 1e3,
                             f0 / 1e9)
    return {"w": w, "d": d, "s": s, "h": h_m, "er": er, "f0": f0,
            "weff": weff, "beta": beta, "fc10": fc10, "near": near,
            "port_mode": port_mode,
            "rx": rx, "py": py, "port_inset": port_inset,
            "y1": y1, "y2": y2, "dom_x": dom_x, "dom_y": dom_y,
            "k_half": k_half, "via_y": via_y, "r_port": r_port}


def _siw_lines(p: dict[str, Any]) -> str:
    # 直 SIW 线段几何段（layout 单源字面注入，米）。必须经 render_script 渲染
    # （_siw_layout 注入）——直调缺布局显式报错，不做静默兜底（#283 渲染期守卫
    # 纪律：守卫条件与消费端同源）。
    lay = p.get("_siw_layout")
    if lay is None:
        raise ValueError(
            "siw 几何段缺 _siw_layout：必须经 render_script 渲染（布局单源注入）")
    via_y = list(lay["via_y"])
    v2 = lay.get("port_mode") == "v2"
    # 模式条件注释（仅注释行随端口方案变；几何/端口/守卫代码同一条 f-string，
    # v1 缺省路径渲染文本逐字节不变——字节钉 test_siw_v1_default_render_byte_pin）
    s_pitch_note = (
        "过孔心距（线段区精确栅格 y_k = k·S_PITCH，藩篱止于端口面 v2_criteria.md"
        " §1）" if v2 else "过孔心距（全域精确栅格 y_k = k·S_PITCH）")
    fence_note = (
        "# 两列金属化过孔 PEC 圆柱（z∈[0,H_SUB] 贯通；藩篱止于端口面=v2 端面\n"
        "# 口径，端口背后无 SIW 延拓支路——v2_criteria.md §1/§3）"
        if v2 else
        "# 两列金属化过孔 PEC 圆柱（z∈[0,H_SUB] 贯通；藩篱直入 PML=匹配端接，\n"
        "# slotline_lumped 口径——端口背后无短路面/开路 stub）")
    port_note = (
        "# 两端 LumpedPort 端面口径（跨介质孔径 x∈[-W/2,+W/2]、跨全高 0..H_SUB，\n"
        "# R=Z_PV 闭式同源）：端口即终端负载而非中间抽头（v2_criteria.md §2/§3）；\n"
        "# 盒三向边全部入网（#198/#283），端口面出 PML_8（16·BASE−NEAR 净距，\n"
        "# #253/H4）"
        if v2 else
        "# 两端 LumpedPort z 桥（中线 x=0、跨全高 0..H_SUB）：TE10 的 E_z 中线最大、\n"
        "# 带内高阶模倏逝（criteria §3）；盒三向边全部入网（#198/#283），端口面出\n"
        "# PML_8（16·BASE−NEAR 净距，#253/H4）")
    rx_note = (
        "端口盒 x 半宽（=W/2 跨介质孔径，盒边=列心线 v2_criteria.md §1）"
        if v2 else "端口盒 x 半宽（=NEAR，盒宽 2 格 #283）")
    return f'''# ── siw 直线段几何（layout 单源字面量，米；criteria.md §2/§4）──
W = {lay["w"]!r}              # 两过孔列心距（Cassivi 等效宽度 w_eff 的物理宽度）
D_VIA = {lay["d"]!r}          # 过孔直径
S_PITCH = {lay["s"]!r}        # {s_pitch_note}
R_PORT = {round(lay["r_port"], 4)!r}   # LumpedPort R = Z_PV=2b·Z_TE/w_eff（闭式；CalcPort 同参考）
RX = {lay["rx"]!r}            # {rx_note}
PY = {lay["py"]!r}            # 端口盒 y 半长（=NEAR）
Y0 = {lay["y1"]!r}            # port1 测量面（端口盒中心，cps 命名契约）
Y1 = {lay["y2"]!r}            # port2 测量面（端口盒中心）
# 上下金属板：显式零厚盒贴 z 边界（与 z 边界 PEC 等电势冗余——桥-板-过孔
# 连通图物理化，#212 审计③可判）
siw_plates = CSX.AddMetal("siw_plates")
siw_plates.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, 0.0), priority=10)
siw_plates.AddBox((-DOM_X, -DOM_Y, H_SUB), (DOM_X, DOM_Y, H_SUB), priority=10)
{fence_note}
siw_via = CSX.AddMetal("siw_via")
_VIA_Y = {via_y!r}
for _vy in _VIA_Y:
    siw_via.AddCylinder([-W / 2, _vy, 0.0], [-W / 2, _vy, H_SUB],
                        radius=D_VIA / 2, priority=10)
    siw_via.AddCylinder([W / 2, _vy, 0.0], [W / 2, _vy, H_SUB],
                        radius=D_VIA / 2, priority=10)
{port_note}
_port1 = FDTD.AddLumpedPort(1, R_PORT, np.array([-RX, Y0 - PY, 0.0]),
                            np.array([RX, Y0 + PY, H_SUB]), "z", 1.0,
                            priority=5)
_port2 = FDTD.AddLumpedPort(2, R_PORT, np.array([-RX, Y1 - PY, 0.0]),
                            np.array([RX, Y1 + PY, H_SUB]), "z", 0.0,
                            priority=5)
# 生成期网格守卫：#152 去重后全轴最小间距复测（CFL 塌缩哨兵）+ 端口盒/
# 中线边落格断言（#283：盒边=结构线，中线恰在网格线上探针才逐位落位）
for _ax in ("x", "y", "z"):
    _dl = np.diff(np.asarray(mesh.GetLines(_ax), dtype=float))
    if _dl.size and not bool(np.all(_dl > 1e-6)):
        raise SystemExit("siw #" + "152" + ": "
                         + _ax + " 轴网格含 ≤1µm 近重合线（CFL 塌缩守卫）")
def _siw_on_line(_ax, _v):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _j = int(np.searchsorted(_ls, _v))
    return (_j < _ls.size and abs(float(_ls[_j]) - _v) <= 1e-9) or (
        _j > 0 and abs(float(_ls[_j - 1]) - _v) <= 1e-9)
for _ax, _v in (("x", 0.0), ("x", -RX), ("x", RX),
                ("y", Y0 - PY), ("y", Y0), ("y", Y0 + PY),
                ("y", Y1 - PY), ("y", Y1), ("y", Y1 + PY),
                ("z", 0.0), ("z", H_SUB)):
    if not _siw_on_line(_ax, _v):
        raise SystemExit("siw #" + "283" + ": 端口盒/中线边 "
                         + _ax + "=" + repr(_v) + " 未落在网格线上")
for _prim in siw_plates.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in siw_via.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ── 元数据（TEMPLATE_META 公约；nominal 全闭式精算 #1c，出处 criteria.md §2）──
SIW_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 2,
    "extraction": "LumpedPort z 桥×2（R=闭式 Z_PV=2b·Z_TE/w_eff，CalcPort 同参考）："
                  "原始 S=带载比值（#250 口径，slotline_lumped 同）；β/εeff 主判="
                  "S21 解缠相位斜率÷port_beta.csv 实测 plane_dist（cps 同契约，"
                  "LumpedPort 无 β 属性）；fc10 由带内 φ(f)=−β(f；fc)·L+φ0 单参数"
                  "拟合（OE 锚 G1，预声明 runs/siw_family/criteria.md §6）",
    "max_time_ns": 45.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "d_mm", "s_mm", "line_len_mm"],
    "topology": "直 SIW 传输线段：基板 z∈[0,h] 上下显式零厚金属板（贴 z 边界 "
                "PEC）+ 两列金属化过孔 PEC 圆柱（x=±w/2、心距 s、全域精确栅格、"
                "藩篱直入 PML=匹配端接）；端口=两端 LumpedPort z 桥（中线、跨全"
                "高、盒边入网、16·BASE 出 PML_8）；域 x 半宽=w/2+w_eff/2（侧界 "
                "MUR 吸收泄漏）、y 半宽=line_len/2+16·BASE（PML_8）——矩形域，"
                "BOARD=60e-3 不适用（机制层 DOM_X/DOM_Y 字面注入）",
    "param_semantics": "w_mm=两过孔列心距（物理宽度，Cassivi 等效宽度 "
                       "w_eff=w−d²/(0.95s) 的输入）、d_mm=过孔直径、s_mm=过孔"
                       "心距（渲染按全域 k·s 精确栅格）、line_len_mm=两端口测量"
                       "面间距（名义 3λg@f0 闭式精算）；h/er/tan_d 走 substrate/"
                       "nominal（TE10 截止与 β 与 h 无关，Microwaves101 SIW 条目）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；"
                 "全域 NEAR=base/4（SmoothMesh 全轴均匀化实测）；过孔直径 ≥4·"
                 "NEAR 守卫、孔间缝 ≥1 内部线（#311 类比）、显式近场线 10µm "
                 "地板（#349）、端口盒 ≥2 格且中线落格（#283，生成期断言）、"
                 "基板 z 4 层（TE10 的 E_z 沿 z 均匀，z 分辨非限制项）",
    "smoke_note": "离线审计先行（#212，test_siw_template）；真机锚已落判"
                  "（df4f：G1 勘误 PASS/G2 PASS/G3 口径裁定/G4 PASS，"
                  "runs/siw_family/，驱动 scripts/siw_anchor_smoke.py）；"
                  "预声明门与预算见 runs/siw_family/criteria.md §6",
}

SIW_NOMINAL: dict[str, Any] = {
    "w_mm": 12.1317, "d_mm": 0.6, "s_mm": 1.0, "line_len_mm": 63.0724,
    "h_mm": 0.508, "er": 3.66, "tan_d": 0.0037,
    # 全闭式精算（#1c，criteria.md §2）：fc10 目标=f0/1.5=6.6667GHz（f0=10GHz
    # 预声明设计点）→ w_eff=c/(2·fc·√3.66)=11.7528 → w=w_eff+d²/(0.95·s)
    # =12.1317（Cassivi 2002 反解）；line_len=round(3λg@10GHz,4)=63.0724
    # （β=298.856 rad/m 闭式、λg=21.0241——链路与 synthesize_siw_model 逐位
    # 同源：4 位舍入 w 起算）；R_port=Z_PV=2b·Z_TE/w_eff=22.8393Ω（渲染层
    # 精算，非手数）；设计规则复核：s/d=1.667≤2 ✔、d=0.6<λ_sub/5=3.134 ✔
}

# （siw 注册在槽线族四件套之前：#247 尾部追加契约要求槽线族保持字典尾，
#   见文末 SIW 段元数据定义与注册行——2026-09-22 siw-family）

# ── 注册（2026-09-22 siw-family：SIW 族首族=直 SIW 传输线段；坑 #247 尾部
#    追加契约=槽线族四件套保持字典尾，故本键先于槽线族注册行执行；同对象
#    注册钉死单一事实源，同对象注册钉死单一事实源）──
TEMPLATE_META["siw"] = SIW_META
TEMPLATE_NOMINAL["siw"] = SIW_NOMINAL

# ══ SIW 族第二成员：MSL 锥形过渡 + SIW 直段（2026-09-24 df6 A2 立项）══════════
# 权威口径：runs/df6_a2siwmsl/criteria.md（Deslandes-Wu 两段论/文献互证账/
# G3' 预声明门/预算）。结构：基板填满矩形域（z=0 PEC 底界=MSL 地+SIW 底壁
# 共用+SIW 区显式零厚底板；顶界 MUR 开放——MSL 区是微带环境），顶层金属单
# 属性 msl_top 三段（50Ω 馈线 → 线性锥 AddPolygon 梯形 → SIW 顶壁显式板，
# 锥末 SEAM 搭接进板区防共棱浮岛）；两列过孔 PEC 圆柱藩篱止于板缘（siw v2
# 口径）。端口=双 MSLPort（线基，CalcPort ref=50 主口径；line_z0="engine"
# 反演+renormalize 判读旋钮沿 openems_rotation #250/#280 先例留判读侧），
# 端口面=域边界贴 PML_8（#174）、端口段=均匀 50Ω 线（refs §3.2）。
# 设计式（criteria §1）：锥=50Ω MSL → Z_PV=2b·Z_TE/w_eff 阻抗变换器（电压
# 基连续性：MSLPort u 探针电压=跨板全高，Z_PV 同基；u/i 口径 Z_TE=264Ω
# 反解线宽 <0.1mm 不可制造，任何已发表版图均无此形态）+ 锥末-SIW 台阶；
# w50/w_end=inverse_width（skrf HJ 单源，渲染期同参精算非手数 #1c）；
# 缺省锥长 λg/2（criteria §1.1 一阶互证：λg/4 在本阻抗比 50/22.84=2.19 下
# 带内 RL≈10.6dB 达不到 15dB 门，如实收档只作旋钮变体）。
# R*=2·Z_PV/π=14.5402Ω 旋钮（siw v2_criteria.md §2 条件触发项）在 MSL 线基
# 端口下语义废弃——匹配由锥形几何承担，Z_PV 只进锥末宽度设计式；v2 历史
# 档与其触发条件不删（#122 收档纪律）。

_MSL_SIW_SEAM_NEAR = 0.25     # 锥末搭接顶板深度（×NEAR；slotline METAL_SEAM 同式）
_MSL_SIW_FEED_BASE = 14.0     # MSLPort 端口段长（×BASE；MSL_PORT_CLEAR_BASE 同款）
_MSL_SIW_MESH_FLOOR_M = 10e-6  # 显式近场线最小间距地板（#349，与 siw 同值）


def msl_siw_taper_layout(params: dict[str, Any],
                         freq_range_ghz: tuple[float, float],
                         base_m: float, h_m: float) -> dict[str, Any]:
    """MSL 锥形过渡+SIW 直段几何/端口/域单一事实源（mm 入参 → 米字面量+守卫）。

    所有名义派生量（w_eff/β/λg/Z_PV/w50/w_end/锥装配/过孔栅格/端口段）在此
    一次计算，body/近场线/机制分支（DOM_X/DOM_Y、substrate、beta_block）同源
    消费——#198/#212 单源纪律。设计规则违规/网格欠分辨/反解未自洽显式
    ValueError 拒渲染。
    """
    from rfauto.core.calculators import (
        siw_beta_rad_m,
        siw_check_design_rules,
        siw_effective_width_mm,
    )
    from rfauto.core.synthesis import Stackup, inverse_width

    w = float(params.get("w_mm", 12.1317)) * 1e-3
    d = float(params.get("d_mm", 0.6)) * 1e-3
    s = float(params.get("s_mm", 1.0)) * 1e-3
    siw_len = float(params.get("siw_len_mm", 63.0724)) * 1e-3
    taper_len = float(params.get("taper_len_mm", 10.5121)) * 1e-3
    er = float(params.get("er", _DEFAULT_SUB["er"]))
    tan_d = float(params.get("tan_d", _DEFAULT_SUB.get("tan_d", 0.0037)))
    f0 = 0.5 * (float(freq_range_ghz[0]) + float(freq_range_ghz[1])) * 1e9
    for _name, _v in (("siw_len_mm", siw_len), ("taper_len_mm", taper_len)):
        if not (math.isfinite(_v) and _v > 0.0):
            raise ValueError(
                f"msl_siw_taper_layout: {_name} 必须为正有限，得到 {_v!r}")
    if not (math.isfinite(base_m) and base_m > 0.0):
        raise ValueError(f"msl_siw_taper_layout: base 必须为正有限，得到 {base_m!r}")
    if not (math.isfinite(h_m) and h_m > 0.0):
        raise ValueError(f"msl_siw_taper_layout: h 必须为正有限，得到 {h_m!r}")
    # 设计规则（siw 单源复用，criteria §1）：违规拒渲染
    siw_check_design_rules(w * 1e3, d * 1e3, s * 1e3, er, freq_ghz=f0 / 1e9)
    weff = siw_effective_width_mm(w * 1e3, d * 1e3, s * 1e3) * 1e-3
    if not weff > 0.0:
        raise ValueError(f"msl_siw_taper_layout: 等效宽度非正 w_eff={weff!r}")
    beta, fc10 = siw_beta_rad_m(weff * 1e3, er, f0 / 1e9)
    if not (math.isfinite(beta) and beta > 0.0):
        raise ValueError(
            f"msl_siw_taper_layout: 频带中心 {f0 / 1e9:.4g}GHz 低于 TE10 截止 "
            f"fc10={fc10:.4f}GHz（SIW 直段必须工作在传播区）")
    # 注意：不设"带低频>fc10"守卫——锚运行口径带 (6,13)GHz 有意含 6.2GHz
    # 截止下频点（G2 波导性滚降门，siw 同款），带缘倏逝是设计意图非误用
    near = base_m / 4.0
    # 过孔可分辨守卫（siw 同款）：直径 ≥4·NEAR
    if not d >= 4.0 * near:
        raise ValueError(
            f"msl_siw_taper_layout: 网格欠分辨——过孔直径 d={d * 1e3:.4g}mm < "
            f"4·NEAR={4.0 * near * 1e3:.4g}mm（BASE={base_m * 1e3:.4g}mm；"
            "收紧 mesh_resolution_mm）")
    # 孔间缝渲染守卫（#311 先例口径，siw_layout 共用判据）：s−d 须 > NEAR
    via_gap = s - d
    if not via_gap > near * (1.0 + 1e-9):
        raise ValueError(
            f"msl_siw_taper_layout: 孔间缝 s−d={via_gap * 1e3:.4g}mm ≤ NEAR="
            f"{near * 1e3:.4g}mm（BASE={base_m * 1e3:.4g}mm）——缝内零内部"
            "网格线（#311 先例口径），藩篱泄漏建模粗；收紧 mesh_resolution_mm")
    # MSL 锥两端线宽（skrf HJ 单源精算，同参 substrate——#1c 禁抄毫米数；
    # inverse_width 返回 mm，此处收敛到米）
    stackup = Stackup(name="render_substrate", epsilon_r=er,
                      thickness_mm=h_m * 1e3, loss_tangent=tan_d)
    w50_mm, _z50, st50 = inverse_width(50.0, f0 / 1e9, stackup)
    if st50 != "ok":
        raise ValueError(
            f"msl_siw_taper_layout: 50Ω 线宽反解未自洽（status={st50!r}）")
    w50 = w50_mm * 1e-3
    z_te = 2.0 * math.pi * f0 * 1.25663706212e-6 / beta
    z_pv = 2.0 * h_m * z_te / weff
    if not z_pv < 50.0:
        raise ValueError(
            f"msl_siw_taper_layout: Z_PV={z_pv:.4f}Ω ≥ 50Ω 出设计域"
            "（锥反向/无匹配意义，criteria §1 选型域为 Z_PV<50）")
    w_end_mm, _zend, stend = inverse_width(z_pv, f0 / 1e9, stackup)
    if stend != "ok":
        raise ValueError(
            f"msl_siw_taper_layout: Z_PV={z_pv:.4f}Ω 线宽反解未自洽"
            f"（status={stend!r}）")
    w_end = w_end_mm * 1e-3
    if not (w50 >= 4.0 * near and w_end >= 4.0 * near):
        raise ValueError(
            f"msl_siw_taper_layout: 线宽欠分辨——w50={w50 * 1e3:.4g}mm/"
            f"w_end={w_end * 1e3:.4g}mm < 4·NEAR={4.0 * near * 1e3:.4g}mm"
            "（收紧 mesh_resolution_mm）")
    if not w_end / 2.0 < w / 2.0 - d / 2.0:
        raise ValueError(
            f"msl_siw_taper_layout: 锥末宽越过过孔藩篱（w_end/2="
            f"{w_end / 2.0 * 1e3:.4g}mm ≥ w/2−d/2={(w / 2.0 - d / 2.0) * 1e3:.4g}mm）")
    # 几何装配（criteria §3）：端口面=域边界；feed→taper→SIW（对称）
    feed_len = _MSL_SIW_FEED_BASE * base_m
    y_plate = siw_len / 2.0          # 顶板缘=锥末（波导区 |y|≤y_plate）
    y_feed_in = y_plate + taper_len  # 锥起点=馈线内端
    dom_y = y_feed_in + feed_len
    dom_x = w / 2.0 + weff / 2.0     # 侧界 MUR：藩篱外倏逝尾截断（siw 同式）
    seam = _MSL_SIW_SEAM_NEAR * near
    # #347：MeasPlaneShift(=feed_len/3) 与 FeedShift(=10·NEAR) 间距 ≥3.9·NEAR
    # （留浮点余量，恰等会炸——msl_slot_transition #347 口径；layout+body 双保险）
    if not feed_len / 3.0 - 10.0 * near >= 3.9 * near:
        raise ValueError(
            f"msl_siw_taper_layout: MeasPlaneShift/FeedShift 间距 "
            f"{(feed_len / 3.0 - 10.0 * near) * 1e6:.1f}µm < 3.9·NEAR（#347；"
            "加大 _MSL_SIW_FEED_BASE）")
    k_half = math.floor((y_plate - d / 2) / s + 1e-9)
    if k_half < 1:
        raise ValueError(
            f"msl_siw_taper_layout: 藩篱装不下（y_plate−d/2="
            f"{(y_plate - d / 2) * 1e3:.4g}mm < s={s * 1e3:.4g}mm）——加大 siw_len_mm")
    via_y = tuple(k * s for k in range(-k_half, k_half + 1))
    # 显式近场线集（与 _near_points 注入同源）最小间距地板（#349，siw 同款）
    x_lines = [0.0, w50 / 2, -w50 / 2, w_end / 2, -w_end / 2,
               w / 2 - d / 2, w / 2, w / 2 + d / 2,
               -(w / 2 - d / 2), -w / 2, -(w / 2 + d / 2)]
    # 注意：锥-板搭接缘（y_plate−seam）不入显式线集——多边形顶点允许阶梯化
    # （非端口/非零厚板平面），入集会造出 25µm 级近线把 CFL dt 拉低 ~40%
    #（NrTS 预算触顶，#152/#283 家族预算面教训；y 最小线距保持与 siw 锚同构）
    y_lines = [dom_y, -dom_y, y_feed_in, -y_feed_in,
               y_plate, -y_plate]
    for _yk in via_y:
        y_lines += [_yk - d / 2, _yk, _yk + d / 2]
    for _name, _lines in (("x", x_lines), ("y", y_lines)):
        _arr = sorted(set(_lines))
        _gaps = [b - a for a, b in pairwise(_arr)]
        _gmin = min(_gaps) if _gaps else float("inf")
        if not _gmin > _MSL_SIW_MESH_FLOOR_M:
            raise ValueError(
                f"msl_siw_taper_layout: {_name} 向显式网格线最小间距 "
                f"{_gmin * 1e6:.3f}µm ≤ {_MSL_SIW_MESH_FLOOR_M * 1e6:.0f}µm "
                "地板（#349 CFL 塌缩守卫；锥缘/板缘/过孔栅格近撞，调整 "
                "siw_len/taper_len/d/s）")
    return {"w": w, "d": d, "s": s, "h": h_m, "er": er, "tan_d": tan_d,
            "f0": f0, "weff": weff, "beta": beta, "fc10": fc10,
            "near": near, "w50": w50, "w_end": w_end, "z_te": z_te,
            "z_pv": z_pv, "siw_len": siw_len, "taper_len": taper_len,
            "feed_len": feed_len, "y_plate": y_plate,
            "y_feed_in": y_feed_in, "seam": seam,
            "dom_x": dom_x, "dom_y": dom_y,
            "k_half": k_half, "via_y": via_y}


def _msl_siw_taper_lines(p: dict[str, Any]) -> str:
    # MSL 锥形过渡+SIW 直段几何段（layout 单源字面注入，米）。必须经
    # render_script 渲染（layout 注入）——直调缺布局显式报错（#283 纪律）。
    lay = p.get("_msl_siw_taper_layout")
    if lay is None:
        raise ValueError(
            "msl_siw_taper 几何段缺 _msl_siw_taper_layout：必须经 render_script "
            "渲染（布局单源注入）")
    via_y = list(lay["via_y"])
    return f'''# ── msl_siw_taper 几何（layout 单源字面量，米；runs/df6_a2siwmsl/criteria.md §1/§3）──
# Deslandes-Wu 两段论：50Ω MSL 馈线 → 线性锥（W50→W_END=Z_PV 阻抗变换器）
# → 锥末-SIW 台阶 → SIW 直段（顶壁板+两列过孔藩篱止于板缘=siw v2 口径）
W = {lay["w"]!r}              # 两过孔列心距（=siw 名义，Cassivi w_eff 输入）
D_VIA = {lay["d"]!r}          # 过孔直径
S_PITCH = {lay["s"]!r}        # 过孔心距（线段区精确栅格 y_k = k·S_PITCH）
W50 = {lay["w50"]!r}          # 50Ω MSL 馈线宽（inverse_width skrf HJ，f0 带心精算 #1c）
W_END = {lay["w_end"]!r}      # 锥末宽（=Z_PV 的微带当宽；电压基连续性 criteria §1）
Z_PV = {round(lay["z_pv"], 4)!r}       # SIW TE10 功率-电压阻抗（w_eff 闭式同源；设计 provenance）
Y_PLATE = {lay["y_plate"]!r}  # SIW 顶板缘=锥末（波导区 |y|≤Y_PLATE）
Y_FEED_IN = {lay["y_feed_in"]!r}  # 锥起点=馈线内端（taper_len=λg/2 缺省 criteria §1.1）
SEAM = {lay["seam"]!r}        # 锥末搭接顶板深度（×NEAR，防共棱浮岛 slotline 先例）
FEED_LEN = {lay["feed_len"]!r}    # MSLPort 端口段长（14·BASE）
# 顶层金属单属性 msl_top 三段（馈线/锥/顶壁板）：同属性+锥末 SEAM 搭接保证
# 馈线-锥-板连通图（#212 审计③；#310 共边不连通教训的预防性搭接）
msl_top = CSX.AddMetal("msl_top")
msl_top.AddBox((-W50 / 2, -DOM_Y, H_SUB), (W50 / 2, -Y_FEED_IN, H_SUB), priority=10)
msl_top.AddBox((-W50 / 2, Y_FEED_IN, H_SUB), (W50 / 2, DOM_Y, H_SUB), priority=10)
# 线性锥（梯形多边形；y 向 [±(Y_PLATE−SEAM), ±Y_FEED_IN]，宽 W50→W_END）
msl_top.AddPolygon(([-W50 / 2, W50 / 2, W_END / 2, -W_END / 2],
                    [-Y_FEED_IN, -Y_FEED_IN, -(Y_PLATE - SEAM), -(Y_PLATE - SEAM)]),
                   norm_dir="z", elevation=H_SUB, priority=10)
msl_top.AddPolygon(([-W50 / 2, W50 / 2, W_END / 2, -W_END / 2],
                    [Y_FEED_IN, Y_FEED_IN, Y_PLATE - SEAM, Y_PLATE - SEAM]),
                   norm_dir="z", elevation=H_SUB, priority=10)
# SIW 顶壁显式零厚板（域顶=MUR 开放——MSL 区微带环境，板只盖波导区）
msl_top.AddBox((-DOM_X, -Y_PLATE, H_SUB), (DOM_X, Y_PLATE, H_SUB), priority=10)
# SIW 底壁显式零厚板（与 z-min PEC 边界等电势冗余——过孔连通图物理化，siw 同款）
siw_bot = CSX.AddMetal("siw_bot")
siw_bot.AddBox((-DOM_X, -Y_PLATE, 0.0), (DOM_X, Y_PLATE, 0.0), priority=10)
# 两列金属化过孔 PEC 圆柱（z∈[0,H_SUB] 贯通；藩篱止于板缘）
siw_via = CSX.AddMetal("siw_via")
_VIA_Y = {via_y!r}
for _vy in _VIA_Y:
    siw_via.AddCylinder([-W / 2, _vy, 0.0], [-W / 2, _vy, H_SUB],
                        radius=D_VIA / 2, priority=10)
    siw_via.AddCylinder([W / 2, _vy, 0.0], [W / 2, _vy, H_SUB],
                        radius=D_VIA / 2, priority=10)
# 双 MSLPort（线基：CalcPort 自算 Z_ref/β；ref=50 归一主口径，line_z0="engine"
# 反演+renormalize 判读旋钮沿 openems_rotation #250/#280 先例留判读侧）：
# 端口面=域边界贴 PML_8（#174）、端口段=均匀 50Ω 线（refs §3.2）、
# FeedShift=10·NEAR 与 MeasPlaneShift=FEED_LEN/3 间距 #347 断言
if not FEED_LEN / 3.0 - 10 * NEAR >= 3.9 * NEAR:
    raise SystemExit("msl_siw_taper #" + "347" + ": "
                     "MeasPlaneShift/FeedShift 间距不足 3.9·NEAR")
_port1 = MSLPort(CSX, port_nr=1, metal_prop=msl_top,
                 start=np.array([W50 / 2, -DOM_Y, H_SUB]),
                 stop=np.array([-W50 / 2, -Y_FEED_IN, 0.0]),
                 prop_dir="y", exc_dir="z", excite=1.0,
                 FeedShift=10 * NEAR, MeasPlaneShift=FEED_LEN / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=msl_top,
                 start=np.array([-W50 / 2, DOM_Y, H_SUB]),
                 stop=np.array([W50 / 2, Y_FEED_IN, 0.0]),
                 prop_dir="y", exc_dir="z", excite=0.0,
                 FeedShift=10 * NEAR, MeasPlaneShift=FEED_LEN / 3, priority=10)
# 生成期网格守卫：#152 去重后全轴最小间距复测（CFL 塌缩哨兵）+ 锥缘/板缘/
# 端口边落格断言（#283：盒边=结构线）
for _ax in ("x", "y", "z"):
    _dl = np.diff(np.asarray(mesh.GetLines(_ax), dtype=float))
    if _dl.size and not bool(np.all(_dl > 1e-6)):
        raise SystemExit("msl_siw_taper #" + "152" + ": "
                         + _ax + " 轴网格含 ≤1µm 近重合线（CFL 塌缩守卫）")
def _mslsiw_on_line(_ax, _v):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _j = int(np.searchsorted(_ls, _v))
    return (_j < _ls.size and abs(float(_ls[_j]) - _v) <= 1e-9) or (
        _j > 0 and abs(float(_ls[_j - 1]) - _v) <= 1e-9)
for _ax, _v in (("x", 0.0), ("x", -W50 / 2), ("x", W50 / 2),
                ("x", -W_END / 2), ("x", W_END / 2),
                ("y", -DOM_Y), ("y", DOM_Y),
                ("y", -Y_FEED_IN), ("y", Y_FEED_IN),
                ("y", -Y_PLATE), ("y", Y_PLATE),
                ("z", 0.0), ("z", H_SUB)):
    if not _mslsiw_on_line(_ax, _v):
        raise SystemExit("msl_siw_taper #" + "283" + ": 端口/锥/板缘边 "
                         + _ax + "=" + repr(_v) + " 未落在网格线上")
for _prim in msl_top.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in siw_bot.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in siw_via.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ── 元数据（TEMPLATE_META 公约；nominal 全闭式精算 #1c，出处 criteria.md §1）──
MSL_SIW_TAPER_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（线基：CalcPort ref=50 主口径；"
                  "port_beta.csv 落双端口 β+引擎自算 ZL（ReadUIData 重读，"
                  "wstep/mline W3② 法）+测量面间距 plane_dist_m——line_z0="
                  "'engine' 线基反演+renormalize 判读旋钮消费，#250/#280）；"
                  "fc10 主判=G1' 带内相位拟合 φ=−β_siw(f;fc)·L_siw+(a+b·f)"
                  "（线性项吸收馈线/锥群延迟，预声明 "
                  "runs/df6_a2siwmsl/criteria.md §4）",
    "max_time_ns": 45.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "d_mm", "s_mm", "taper_len_mm", "siw_len_mm"],
    "topology": "MSL 锥形过渡+SIW 直段（Deslandes-Wu 两段论）：50Ω MSL 馈线 "
                "→ 线性锥（w50→w_end=Z_PV 微带当宽的阻抗变换器+锥末-SIW 台阶"
                "不连续）→ SIW 直段（顶壁显式板+两列过孔藩篱止于板缘=siw v2 "
                "口径+底壁板）；基板填满矩形域，z=0 PEC 底界，顶界 MUR（MSL 区"
                "微带环境）；端口=双 MSLPort（面贴域界 PML_8、端口段=均匀 50Ω 线）",
    "param_semantics": "w_mm=两过孔列心距（=TEMPLATE_NOMINAL['siw'] 同名同义）、"
                       "d_mm=过孔直径、s_mm=过孔心距、taper_len_mm=锥形段长"
                       "（缺省 λg/2@f0，criteria §1.1 一阶互证收档）、"
                       "siw_len_mm=SIW 直段长（顶板缘间距，缺省 3λg）；w50/"
                       "w_end=inverse_width 渲染期同参精算（非参数，#1c）；"
                       "h/er/tan_d 走 substrate/nominal（er/h 进锥宽设计链）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；"
                 "全域 NEAR=base/4；过孔直径 ≥4·NEAR 守卫、孔间缝 ≥1 内部线"
                 "（#311）、显式近场线 10µm 地板（#349）、锥缘/板缘/端口边落格"
                 "断言（#283）、FeedShift/MeasPlaneShift 间距 ≥3.9·NEAR"
                 "（#347）；基板 z 4 层（TE10 的 E_z 沿 z 均匀，z 分辨非限制项）",
    "smoke_note": "离线审计先行（#212，test_msl_siw_taper_template）；OE 锚"
                  "发射面备妥（驱动 scripts/siw_anchor_smoke.py --template "
                  "msl_siw_taper，发射前置=A1 队列清空+.oe_collect.lock 空，"
                  "见 runs/df6_a2siwmsl/handoff.md）；预声明门与预算见 "
                  "runs/df6_a2siwmsl/criteria.md §4/§6；R*=14.5402Ω 旋钮（siw "
                  "v2_criteria.md §2 条件触发项）在 MSL 线基端口下语义废弃——"
                  "匹配由锥形几何承担，Z_PV 只进锥末宽度设计式（如实收档，v2 "
                  "历史档不删）",
}

MSL_SIW_TAPER_NOMINAL: dict[str, Any] = {
    "w_mm": 12.1317, "d_mm": 0.6, "s_mm": 1.0,
    "taper_len_mm": 10.5121, "siw_len_mm": 63.0724,
    "h_mm": 0.508, "er": 3.66, "tan_d": 0.0037,
    # 全闭式精算（#1c，runs/df6_a2siwmsl/criteria.md §1/§1.1）：w/d/s=
    # TEMPLATE_NOMINAL["siw"] 同源沿用（fc10=6.6667GHz=f0/1.5 设计点）；
    # λg=21.0241mm（β=298.856 rad/m 闭式）→ taper_len=round(λg/2,4)=10.5121
    # （缺省锥长；λg/4=5.256 只作旋钮变体——对称双锥确定性级联实测带内
    # |S11| max −7.8dB 达不到 15dB 预声明门，criteria §1.1 两轮勘误账如实
    # 收档）；siw_len=round(3λg,4)=63.0724（与 siw line_len 同链同值）；
    # w50=1.1198/w_end=3.361（inverse_width @Z_PV=22.8393Ω，渲染期同参
    # 精算非手数）
}

# ── 注册（2026-09-24 df6 A2：SIW 族第二成员=MSL 锥形过渡+SIW 直段；坑 #247
#    尾部追加契约=槽线族四件套保持字典尾，本键在槽线族注册行之前执行）──
TEMPLATE_META["msl_siw_taper"] = MSL_SIW_TAPER_META
TEMPLATE_NOMINAL["msl_siw_taper"] = MSL_SIW_TAPER_NOMINAL

# ══ 槽线族正式注册（2026-09-18 w1b，排空六轮 followUps ④/0df②/0dl①；审计 #12/#17）══
# 路线 A/B 均匀槽线段（真机三门 PASS，战役档案）、MSL↔slot 过渡
# 与 Marchand 双槽臂（真机判读战役档案）由附加模块升格正式注册——渲染入口
# 仍在各自模块（本段零拷贝、只做分发与元数据，#116 防本地副本）：
#   adapters/slotline_template.render_slotline_script        （slotline，路线 A）
#   adapters/slotline_lumped_template.render_slotline_lumped_script（slotline_lumped，路线 B）
#   adapters/slotline_transitions_template.render_msl_slot_transition / render_marchand_balun
# 整脚本渲染器（非 _xxx_lines 几何段）：render_script/geometry_spec 顶部的
# SLOTLINE_FAMILY 钩子直接委托本段分发函数，签名与主路径对齐。
SLOTLINE_FAMILY_TEMPLATES: tuple[str, ...] = (
    "slotline", "slotline_lumped", "msl_slot_transition", "marchand_balun")

#: 路线 A 模式文件缺省名（相对脚本运行目录；正式口径必须传绝对路径——
#: 由 adapters/ngsolve_modes.solve_slotline_mode + openems_slotline_port.
#: write_slotline_mode_files 预生成，WaveguidePort 文件模式在 FDTD.Run 时读取）
_SLOTLINE_MODE_FILE_DEFAULTS = ("slot_mode_E.h5", "slot_mode_H.h5")


def _slotline_family_params(template: str, params: dict[str, Any],
                            substrate: dict[str, Any] | None) -> dict[str, Any]:
    """槽线族入参归一：h_mm/er/tan_d 模板参数优先（缺省=路线 A/B 设计点），
    缺项才回退 recipe substrate。**h=1.524（RO4350B 60mil）是模板参数而非缺省
    叠层**：Janaswamy–Schaubert 闭式域要求 d/λ0≥0.006，缺省 0.508@2.5GHz 落域外
    （战役档案）。"""
    p = dict(params)
    sub = substrate or _DEFAULT_SUB
    p.setdefault("h_mm", float(sub["h_mm"]))
    p.setdefault("er", float(sub["er"]))
    p.setdefault("tan_d", float(sub.get("tan_d", 0.0037)))
    return p


def slotline_family_render(template: str, params: dict[str, Any],
                           freq_range_ghz: tuple[float, float], *,
                           mesh_resolution_mm: float = 0.0,
                           substrate: dict[str, Any] | None = None,
                           excite_port: int = 1) -> str:
    """槽线族整脚本分发（与 render_script 主路径签名对齐的正式渲染入口）。"""
    p = _slotline_family_params(template, params, substrate)
    f0_hz = 0.5 * (freq_range_ghz[0] + freq_range_ghz[1]) * 1e9
    ep = max(1, min(4, int(excite_port)))
    if template == "slotline":
        from rfauto.adapters.openems_slotline_port import slotline_port_kc
        from rfauto.adapters.slotline_template import render_slotline_script
        from rfauto.core.slotline import slotline_beta, slotline_closed_form

        cf = slotline_closed_form(float(p.get("w_mm", 1.0)), float(p["h_mm"]),
                                  float(p["er"]), f0_hz / 1e9)
        kc = (complex(p["kc"]) if p.get("kc") is not None else
              slotline_port_kc(slotline_beta(float(p.get("w_mm", 1.0)), float(p["h_mm"]),
                                             float(p["er"]), f0_hz / 1e9), f0_hz))
        return render_slotline_script(
            p, freq_range_ghz,
            str(p.get("e_mode_file", _SLOTLINE_MODE_FILE_DEFAULTS[0])),
            str(p.get("h_mode_file", _SLOTLINE_MODE_FILE_DEFAULTS[1])),
            kc, float(p.get("z_mode_ohm", round(cf.z0_ohm, 4))),
            mesh_resolution_mm=mesh_resolution_mm, excite_port=max(1, min(2, ep)),
            tan_d=float(p.get("tan_d", 0.0037)),
            beta_ref_rad_m=p.get("beta_ref_rad_m"))
    if template == "slotline_lumped":
        from rfauto.adapters.slotline_lumped_template import (
            render_slotline_lumped_script,
        )
        from rfauto.core.slotline import slotline_closed_form

        cf = slotline_closed_form(float(p.get("w_mm", 1.0)), float(p["h_mm"]),
                                  float(p["er"]), f0_hz / 1e9)
        r_port = float(p.get("r_port_ohm", round(cf.z0_ohm, 4)))
        return render_slotline_lumped_script(
            p, freq_range_ghz, r_port, mesh_resolution_mm=mesh_resolution_mm,
            nrts=int(p.get("nrts", 100000)), tan_d=float(p.get("tan_d", 0.0037)),
            beta_ref_rad_m=p.get("beta_ref_rad_m"), excite_port=max(1, min(2, ep)))
    from rfauto.adapters.slotline_transitions_template import (
        render_marchand_balun,
        render_msl_slot_transition,
    )

    if template == "msl_slot_transition":
        return render_msl_slot_transition(
            p, freq_range_ghz, mesh_resolution_mm=mesh_resolution_mm,
            nrts=int(p.get("nrts", 100000)), excite_port=1)
    return render_marchand_balun(
        p, freq_range_ghz, mesh_resolution_mm=mesh_resolution_mm,
        nrts=int(p.get("nrts", 100000)), excite_port=max(1, min(3, ep)),
        f0_ghz=p.get("f0_ghz"))


def slotline_family_geometry_spec(template: str, params: dict[str, Any],
                                  substrate: dict[str, Any]) -> dict[str, Any]:
    """槽线族 UI 3D 预览 spec（盒/端口由 layout 单一事实源换算，米→mm）。"""
    from rfauto.adapters.slotline_lumped_template import slotline_lumped_layout
    from rfauto.adapters.slotline_template import slotline_layout
    from rfauto.adapters.slotline_transitions_template import (
        marchand_balun_layout,
        msl_slot_transition_layout,
    )

    p = _slotline_family_params(template, params, substrate)
    h = float(p["h_mm"])
    band = (2.25, 2.75)
    boxes: list[dict[str, Any]] = []
    ports: list[dict[str, Any]] = []

    def _box(name: str, x0, y0, z0, x1, y1, z1, material="metal") -> None:
        boxes.append({"name": name, "material": material,
                      "start_mm": [x0 * 1e3, y0 * 1e3, z0 * 1e3],
                      "stop_mm": [x1 * 1e3, y1 * 1e3, z1 * 1e3]})

    def _port(nr: int, label: str, pos, axis: str) -> None:
        d = [0.0, 0.0, 0.0]
        d["xyz".index(axis)] = 1.0
        ports.append({"name": f"Port{nr}（{label}）", "pos_mm": pos, "dir": d})

    def _sub(dx: float, dy: float) -> None:
        boxes.append({"name": "substrate", "material": "substrate",
                      "start_mm": [-dx * 1e3, -dy * 1e3, 0.0],
                      "stop_mm": [dx * 1e3, dy * 1e3, h * 1e3]})

    if template in ("slotline", "slotline_lumped"):
        lay = (slotline_layout(p, band, 0.0) if template == "slotline"
               else slotline_lumped_layout(p, band, 0.0))
        w, h_m, yh = lay.w_m, lay.h_m, lay.y_half_m
        dom_x = lay.dom_x_m
        _sub(dom_x, yh)
        _box("slot_metal_lo", -dom_x, -yh, h_m, dom_x, -w / 2, h_m)
        _box("slot_metal_hi", -dom_x, w / 2, h_m, dom_x, yh, h_m)
        if template == "slotline":
            _port(1, "WaveguidePort 文件模式（路线 A）",
                  [lay.x_exc1_m * 1e3, 0.0, h_m * 1e3 / 2.0], "x")
            _port(2, "WaveguidePort 文件模式（路线 A）",
                  [lay.x_exc2_m * 1e3, 0.0, h_m * 1e3 / 2.0], "x")
        else:
            _port(1, "LumpedPort 跨槽（路线 B，R=闭式 Z0）",
                  [lay.x_port1_m * 1e3, 0.0, h_m * 1e3], "y")
            _port(2, "LumpedPort 跨槽（路线 B）",
                  [lay.x_port2_m * 1e3, 0.0, h_m * 1e3], "y")
    elif template == "msl_slot_transition":
        lay = msl_slot_transition_layout(p, band, 0.0)
        _sub(lay.dom_x_m, lay.dom_y_m)
        _box("gnd_slot_lo", -lay.dom_x_m, lay.s_m / 2, 0.0, lay.dom_x_m, lay.dom_y_m, 0.0)
        _box("gnd_slot_hi", -lay.dom_x_m, -lay.dom_y_m, 0.0, lay.dom_x_m, -lay.s_m / 2, 0.0)
        _box("msl_top", -lay.w_msl_m / 2, -lay.dom_y_m, lay.h_m, lay.w_msl_m / 2,
             lay.y_stub_tip_m, lay.h_m)
        _port(1, "MSLPort（微带，线基）",
              [0.0, lay.y_p1_edge_m * 1e3, lay.h_m * 1e3], "y")
        _port(2, "LumpedPort 跨槽（R=槽线 Z0）",
              [-lay.x_port_m * 1e3, 0.0, 0.0], "y")
    else:
        lay = marchand_balun_layout(p, band, 0.0)
        _sub(lay.dom_x_m, lay.dom_y_m)
        a1, a2, x_sh = lay.a1_m, lay.a2_m, lay.l_short_m
        _box("gnd_M1", -lay.dom_x_m, a2, 0.0, lay.dom_x_m, lay.dom_y_m, 0.0)
        _box("gnd_M2", -lay.dom_x_m, -lay.dom_y_m, 0.0, lay.dom_x_m, -a2, 0.0)
        _box("gnd_M3", -lay.dom_x_m, -a1, 0.0, lay.dom_x_m, a1, 0.0)
        _box("gnd_M4", x_sh, -a2, 0.0, lay.dom_x_m, -a1, 0.0)
        _box("gnd_M5", -lay.dom_x_m, a1, 0.0, -x_sh, a2, 0.0)
        _box("msl_top", -lay.w_msl_m / 2, lay.y_stub_tip_m, lay.h_m, lay.w_msl_m / 2,
             lay.dom_y_m, lay.h_m)
        _port(1, "MSLPort（微带，线基）",
              [0.0, lay.y_p1_edge_m * 1e3, lay.h_m * 1e3], "y")
        _port(2, "LumpedPort 跨槽臂 1", [lay.x_port_m * 1e3, (a1 + a2) / 2 * 1e3, 0.0], "y")
        _port(3, "LumpedPort 跨槽臂 2", [-lay.x_port_m * 1e3, -(a1 + a2) / 2 * 1e3, 0.0], "y")
    return {"template": template, "substrate": substrate, "boxes": boxes,
            "ports": ports, "elements": []}


# ── 元数据（TEMPLATE_META 公约：f0/n_ports/extraction/params/topology/
#    param_semantics/mesh_note/smoke_note；与附加模块 docstring 单源对齐）──
SLOTLINE_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "WaveguidePort 文件模式（NGSolve 2D 本征模 E/H 喂入，exc_dir=x）："
                  "模式文件必需 SetPropagationDir；CalcPort 参考阻抗=交叉取对面端口"
                  "视入阻抗（文件模式 U/I 度量常数 γ≈2.71，坑 B，战役档案）；"
                  "S21=port2.uf_inc/SREF（实证口径）；β 独立提取=槽跨压探针 N 站"
                  "自实现工程 DFT 相位斜率",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "line_len_mm", "h_mm"],
    "topology": "均匀槽线段（路线 A，单面金属开缝、无地开放结构）：槽 |y|≤w/2 贯通至"
                "两端边界，两端 WaveguidePort（E/H 模式文件），激励面内移 16·BASE 出 "
                "PML_8；基板 z∈[0,h]，上下/侧向 MUR、端口轴 PML_8；槽跨压探针 9 站",
    "param_semantics": "w_mm=槽宽，line_len_mm=两测量面间距（设计 ≈1λ' 槽波长，"
                       "闭式精算），h_mm=基板厚（模板参数：JS 闭式域 d/λ0≥0.006，"
                       "缺省叠层 0.508@2.5GHz 落域外，设计点 RO4350B 60mil=1.524）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "近槽/近端口 NEAR=base/4、基板 z 6 层、#152 最小间距守卫；"
                 "槽缘细化步长 min(NEAR, w/8)、地板 10µm（#349，TODO 0df④——"
                 "自动档恰为 w/8 且引擎 dt 相应减半，真跑前按 et 实测 dt 重排 "
                 "NrTS，#283）",
    "smoke_note": "真机 PASS（08d63b0）：β 闭式 67.227/NGSolve 67.149/openEMS 67.937 "
                  "rad/m 互差 ≤1.2%、|S11|@f0 −39.1dB、|S21| −0.32dB 三门。**运行前置**："
                  "模式文件必须先经 adapters/ngsolve_modes.solve_slotline_mode + "
                  "openems_slotline_port.write_slotline_mode_files 生成，params 传 "
                  "e_mode_file/h_mode_file 绝对路径（缺省名仅占位，真跑会缺文件报错）；"
                  "kc/z_mode 缺省由闭式反解，正式口径取 NGSolve 解",
}

SLOTLINE_LUMPED_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "LumpedPort 跨槽 R=线阻抗档（CalcPort 参考同值）：带载比值 S11/S21 "
                  "#250 口径，assemble_route_b_sparams 归一到 50Ω 对拍；β 主口径="
                  "双行波拟合 two_wave_beta_fit（线性斜率法驻波下偏 +10.7% 只作诊断列）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "line_len_mm", "h_mm"],
    "topology": "均匀槽线段（路线 B，官方 AddLumpedPort 范式）：金属/基板/槽贯通全域"
                "直入 PML（匹配端接），两端 LumpedPort 跨槽桥接（盒三向边全部入网，"
                "#198/#174）；槽跨压探针 9 站 [−L/4,+L/4]",
    "param_semantics": "w_mm=槽宽，line_len_mm=两端口间距，h_mm=基板厚（模板参数，"
                       "理由同 slotline）；r_port_ohm 缺省=闭式 Z0（可注入 HFSS Zpv 档）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "端口盒/槽缘/基板界面精确入网、#152 守卫",
    "smoke_note": "真机 β_B 68.40 vs HFSS-wide +2.44%（门 3% PASS，e35a517）。原始 "
                  "|S11|/|S21| 为\"PML 匹配线上并联抽头\"拓扑解析必然（βL=2π 时 "
                  "S11=−1/2/S21=+1/2）：β 生产口径可用，S 参数 D 级需 tap_network_"
                  "sparams 换算（#250）",
}

MSL_SLOT_TRANSITION_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "P1 MSLPort（微带线基：CalcPort 自算 Z_ref(f)/β(f)）激励，"
                  "S11=uf_ref/uf_inc；P2 LumpedPort 跨槽 R=槽线 Z0（并联抽头拓扑 "
                  "#250），S21 判据按 tap_receive_factor_db 修正、原始值并列如实；"
                  "β_slot 双行波拟合对照闭式（信息门 ≤5%）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_slot_mm", "x_port_mm", "h_mm"],
    "topology": "Roberts/Knorr 过渡（双层板）：底层地板开槽（槽开口向 −x 直入 PML，"
                "+x 封口=λg'/4 短路臂），顶层微带沿 y 跨槽后延伸 λg_m/4−Δl 开路支节"
                "（跨越点虚短路/虚开路机理，Knorr 1974/Schuppert 1988；开路端边缘场"
                "等效延长 Δl，物理长=电长−Δl，Pozar eq.4.23 口径——C6 符号修正"
                " 2026-09-21，旧 +Δl 系符号反）；MSLPort 段内移 14·BASE（H4：段⊂"
                "PML_8 致非物理已根治）",
    "param_semantics": "w_slot_mm=槽宽，x_port_mm=P2 端口距跨越点（输出臂长），"
                       "h_mm=基板厚（模板参数，理由同 slotline）；f0 取自仿真频带中心",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50、"
                 "NEAR=base/4；封口 SEAM 搭接（×NEAR 不关槽方向）、全部盒缘入网",
    "smoke_note": "真机（a8abe8d）：openEMS |S11|@f0 −19.9/带内 max −10.43dB（匹配门 "
                  "PASS）、超额损耗 1.05dB 贴门；HFSS β=66.55 对闭式 −1.0%、带内 "
                  "−9.55dB 贴门、IL 1.37dB FAIL——判 PASS 需结区优化（渐变槽/径向"
                  "短路盘），复跑按 TRANSITION_GATES 预声明门判读",
}

MARCHAND_BALUN_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 3,
    "extraction": "excite_port∈{1,2,3} 轮转（#208 进程隔离单激励）：P1 MSLPort 线基、"
                  "P2/P3 LumpedPort 跨槽（抽头基线 RX/SRC 因子修正口径）；S23（隔离）"
                  "需第二激励；巴伦判据门=BALUN_GATES（不平衡 ≤1dB、RL ≤−10、隔离 "
                  "≤−15、|S21| ≥−3.5）+ 相位极性约定如实报告",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_slot_mm", "x_port_mm", "h_mm"],
    "topology": "Marchand 双槽臂最小族（底层五盒：外地 M1/M2、中条 M3、封口桥 M4/M5 "
                "与中条精确共边；顶层微带穿两槽+共享开路支节）：**设计级结论=单支节"
                "串接已被两引擎互证证伪**（四门 FAIL、两跨越点激励不对称、拓扑无隔离"
                "机制，战役档案）——真 Marchand=两节对称耦合段（电路级综合 "
                "core/slotline_transitions.synthesize_marchand_two_section，名义点 "
                "50Ω→280Ω 差分、C=−7.02dB、(w,s,ℓ)=(1.7616,0.1016,18.4670)mm@h=1.524）；"
                "本模板保留作对照口径与判据载体，不作生产巴伦",
    "param_semantics": "w_slot_mm=槽宽，x_port_mm=P2/P3 距跨越区中心，h_mm=基板厚"
                       "（模板参数，理由同 slotline）；f0 取自仿真频带中心",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50、"
                 "NEAR=base/4；槽内缘/中条/封口桥共边网格线已钉（PEC 共棱连通）",
    "smoke_note": "真机（a8abe8d）四门 FAIL 两引擎一致：不平衡 2.76/2.64dB、RL −7.4/"
                  "−5.6、|S21| −4.05/−3.93、隔离 −0.55/−5.42、相位 −97°/−31°；幅度三量"
                  "两引擎差 ≤0.2dB 互证=设计级结论成立。复跑冒烟只作回归对照，验收看"
                  "两节新设计（followUp 立项）",
}

SLOTLINE_NOMINAL: dict[str, Any] = {
    "w_mm": 1.0, "line_len_mm": 93.4624, "h_mm": 1.524,
    "er": 3.66, "tan_d": 0.0037,
    # λ'=93.4624mm=1λ'@2.5GHz（Janaswamy–Schaubert 闭式：Z0=110.92Ω/εeff=1.6462，
    # core/slotline 精算 #1c；h=1.524 设计点理由见 slotline_family_params）
}

SLOTLINE_LUMPED_NOMINAL: dict[str, Any] = dict(SLOTLINE_NOMINAL)

MSL_SLOT_TRANSITION_NOMINAL: dict[str, Any] = {
    "w_slot_mm": 1.0, "x_port_mm": 40.0, "h_mm": 1.524,
    "er": 3.66, "tan_d": 0.0037, "f0_ghz": 2.5,
    # 槽线闭式：Z0=110.92Ω/λ'=93.4624mm；微带 50Ω HJ w=3.3439/εeff=2.8530 →
    # 短路臂 λg'/4=23.3656、支节 λg_m/4−Δl=17.1253（core/slotline_transitions
    # transition_design 精算，渲染层单源换算；C6 符号修正 2026-09-21：开路端
    # 边缘场等效延长 Δl，物理长=电长−Δl，Pozar eq.4.23 口径，旧 +Δl 系符号反）
}

MARCHAND_BALUN_NOMINAL: dict[str, Any] = dict(MSL_SLOT_TRANSITION_NOMINAL)

# ── 注册（尾部追加，坑 #247：不重排既有键；同对象注册钉死单一事实源）──
TEMPLATE_META["slotline"] = SLOTLINE_META
TEMPLATE_NOMINAL["slotline"] = SLOTLINE_NOMINAL
TEMPLATE_META["slotline_lumped"] = SLOTLINE_LUMPED_META
TEMPLATE_NOMINAL["slotline_lumped"] = SLOTLINE_LUMPED_NOMINAL
TEMPLATE_META["msl_slot_transition"] = MSL_SLOT_TRANSITION_META
TEMPLATE_NOMINAL["msl_slot_transition"] = MSL_SLOT_TRANSITION_NOMINAL
TEMPLATE_META["marchand_balun"] = MARCHAND_BALUN_META
TEMPLATE_NOMINAL["marchand_balun"] = MARCHAND_BALUN_NOMINAL


# ══ Marchand 两节对称耦合段渲染器 + 过孔对照旋钮（C12，2026-09-21）══
# 背景：HFSS 巴伦锚全波中心（S11 零点 2.04GHz）比理想电路（2.5GHz）低 ≈18%
# （runs/hfss_marchand_anchor，归因假设=过孔柱电感
# ≈0.7nH+开路 fringe）；openEMS 烟测（runs/smoke_marchand_2sect）谷 ≥3.0 触
# 扫频边截断、两引擎 DISAGREE 谐振反向（二百五十八）；同端口仲裁 ENGINE_SIDE
# （二百七十九）+匹配线标定（二百八十二）把 openEMS 侧偏差主体定位到 Z0/端口
# 提取（修正项 engine_z0_correction 已落地 core/slotline_transitions）。**−18%
# 本身的登记归因对照=过孔 PEC 薄片单变量**（排空五轮段档案
# 四）followUp ①"过孔改理想 PEC 薄片短路"）。电路级预判（core
# coupled_line_z_matrix + 短路口 jωL 负载约束，2026-09-21 C12 实算）：L=0.7nH
# → 谷 2.046GHz——**−18% 主体可由过孔电感定量复现**（方向=短路副线电学变长、
# 谐振下移：θ_副线+θ_via=90°，t_res=Z0o/(ωL)）。
# 本渲染器把 runs/smoke_marchand_2sect/render_run.py 单源化（rod 缺省=烟测
# 几何逐字节口径）并加 _via_mode 对照（opt-in，缺省不变）：
#   rod   = 0.25mm 方柱贯通 z∈[0,H]（现状/HFSS 锚 VIA_SIDE_MM 同款，有限电感）
#   sheet = 理想 PEC 薄片短路墙（零 x 厚 yz 面、全臂宽贯通 z∈[0,H]，无收束电感）
# 单变量纪律：两变体**网格线/端口/域/激励逐字节一致**（rod 专属网格线在 sheet
# 模式保留为纯加密，落格守卫在 via_guard 内分支），唯一差异=过孔金属原语；
# 渲染全文 diff 恰=VIA_MODE 行+过孔原语段（单测钉）。
# 可证伪预测：rod→sheet 谷位上移 Δf/f≈+18~25%（openEMS 引擎偏置使两臂谷位
# 整体偏高，**A/B 差值才是过孔贡献**）；Δ<5% 即证伪过孔假设（残差归 fringe/
# 端口/引擎侧，由 judge 如实分解）。
# 范围声明：对照实验口径，**未接入** render_script 分发/TEMPLATE_META/四件套
# 注册（消费者=scripts/marchand_via_ab.py + 单测；正式注册走独立立项，#304
# 五消费者连带不在本项）。
MARCHAND2_VIA_MODES: tuple[str, ...] = ("rod", "sheet")
#: rod 过孔柱边长（HFSS 锚 scripts/hfss_marchand_anchor.py VIA_SIDE_MM 同款）
MARCHAND2_VIA_SIDE_MM: float = 0.25


def marchand2_via_geometry(via_mode: str, *,
                           via_side_mm: float = MARCHAND2_VIA_SIDE_MM
                           ) -> dict[str, Any]:
    """过孔对照几何规格（渲染器/runner/单测共用单一事实源；非法输入显式报错）。

    rod：两柱 [XA, via1_c−d/2, 0]→[XA+d, via1_c+d/2, H] 与 [XC−d, −via1_c−d/2, 0]
    →[XC, −via1_c+d/2, H]（d=via_side_mm，HFSS 锚同款方柱）；sheet：两面零 x 厚
    墙 x=XA / x=XC、y 全臂宽、z∈[0,H]（设计短路平面上的理想短路）。
    """
    if via_mode not in MARCHAND2_VIA_MODES:
        raise ValueError(f"marchand2_via_geometry: via_mode 须为 "
                         f"'|'.join({MARCHAND2_VIA_MODES!r}) 之一，得 {via_mode!r}")
    if not float(via_side_mm) > 0.0:
        raise ValueError(f"marchand2_via_geometry: via_side_mm 须 >0，得 {via_side_mm!r}")
    return {"mode": via_mode, "via_side_mm": float(via_side_mm)}


def render_marchand2_script(
        freq_range_ghz: tuple[float, float], *, via_mode: str = "rod",
        via_side_mm: float = MARCHAND2_VIA_SIDE_MM, nrts: int = 150000,
        base_anchor_f_hi_hz: float = 3.0e9) -> str:
    """两节对称 Marchand openEMS 整脚本渲染（C12 过孔对照单源；自包含可执行）。

    几何/网格/端口/审计=runs/smoke_marchand_2sect/render_run.py 逐行单源
    （rod 缺省）；扫频窗可扩（A/B 用 (2.0,4.2)GHz：rod 谷在烟测 3.0 边被截断、
    sheet 预期更高）；**网格锚 base_anchor_f_hi_hz=3.0e9 与烟测逐字节一致**
    （单变量：扩窗不改网格）。名义几何零手抄（core marchand_two_section_nominal
    运行时单源读取）。脚本支持 RFAUTO_SKIP_RUN=1 审计模式（零仿真）；summary/
    audit 记录全部生效值（#283：via_mode/via_side_mm/nrts/base/near）。真机由
    scripts/marchand_via_ab.py --collect 编排（本函数不求解）。
    """
    spec = marchand2_via_geometry(via_mode, via_side_mm=via_side_mm)
    f_lo = float(freq_range_ghz[0]) * 1e9
    f_hi = float(freq_range_ghz[1]) * 1e9
    nf = 441
    if not (0.0 < f_lo < f_hi):
        raise ValueError(f"render_marchand2_script: 频窗非法 {freq_range_ghz!r}")
    if int(nrts) <= 0:
        raise ValueError(f"render_marchand2_script: nrts 须 >0，得 {nrts!r}")
    # 过孔原语段（两模式唯一几何差异；rod=烟测 render_run.py L133-136 逐行同文）
    if spec["mode"] == "rod":
        via_block = (
            "msl.AddBox((XA, via1_c - VIA / 2, 0.0), (XA + VIA, via1_c + VIA / 2, H),\n"
            "           priority=10)                                     # 过孔 1\n"
            "msl.AddBox((XC - VIA, -via1_c - VIA / 2, 0.0),\n"
            "           (XC, -via1_c + VIA / 2, H), priority=10)         # 过孔 2\n")
    else:
        via_block = (
            "msl.AddBox((XA, Y_S1_LO, 0.0), (XA, Y_S1_HI, H),\n"
            "           priority=10)      # 理想薄片短路 1（零 x 厚 yz 墙：全臂宽贯通 z0..H，无收束电感）\n"
            "msl.AddBox((XC, Y_S2_LO, 0.0), (XC, Y_S2_HI, H),\n"
            "           priority=10)      # 理想薄片短路 2\n")
    header = f'''#!/usr/bin/env python3
"""C12 过孔 PEC 薄片单变量对照：Marchand 两节对称 openEMS 渲染+求解（自动生成）。

单源：adapters/openems_templates.render_marchand2_script（rod 缺省=
runs/smoke_marchand_2sect/render_run.py 逐行口径；勿手改本文件——再渲染）。
变体：VIA_MODE ∈ {{"rod"（0.25mm 方柱，有限过孔电感）/ "sheet"（理想 PEC 薄片
短路墙）}}，两变体网格/端口/域/激励逐字节一致，唯一差异=过孔金属原语。
判据：runs/marchand_via_ab/criteria.md（A/B 预声明）+ core MARCHAND2_GATES。
用法：
  RFAUTO_SKIP_RUN=1 python render_script.py   # 仅离线审计（构建 CSX+守卫，零仿真）
  python render_script.py                     # 审计通过后真跑+后处理
"""
import csv
import json
import math
import os
import sys

# rfauto 不可导入时按 __file__ 向上找仓库 src/（runs/<实验>/<变体>/ 布局自举）
if __import__("importlib.util", fromlist=["x"]).find_spec("rfauto") is None:
    _ROOTS = [p for p in __import__("pathlib").Path(__file__).resolve().parents
              if (p / "src" / "rfauto").is_dir()]
    if not _ROOTS:
        raise ImportError("rfauto 不可导入且未找到仓库 src/（渲染脚本须在仓库布局内或已装 rfauto）")
    sys.path.insert(0, str(_ROOTS[0] / "src"))

from rfauto.core.slotline_transitions import (  # noqa: E402
    MARCHAND2_NOMINAL_INPUTS,
    marchand_two_section_nominal,
)

_DESIGN = marchand_two_section_nominal()
_NOM = _DESIGN.nominal_params()

# ── 渲染侧常量（烟测 render_run.py 同款；米）──
C0 = 299792458.0
F_LO, F_HI = {f_lo!r}, {f_hi!r}   # A/B 扩窗：rod 谷 ≥3.0 烟测触边截断、sheet 预期更高
NF = {nf}
NRTS = int(os.environ.get("RFAUTO_NRTS", {int(nrts)!r}))   # G0 档 C 续跑用 env 覆盖
BASE = C0 / {float(base_anchor_f_hi_hz)!r} / math.sqrt(MARCHAND2_NOMINAL_INPUTS["er"]) / 50.0
# ↑ 网格锚=烟测 F_HI=3.0GHz 同款公式（单变量：扩窗不改网格，#368 同参口径）
NEAR = BASE / 4.0
PORT_CLEAR = 14.0 * BASE           # MSLPort 段起点→域边净距（H4 惯例）
L_PORT = 8.0e-3                    # MSLPort 段长
FEED_CLEAR = 4.0e-3                # 端口段内端→节 1 起点（x=0）净距
PAD_X = 6.0e-3                     # 开路端→+x 域边
PAD_Y = 6.0e-3                     # 副线→y 域边
Z_BOT, Z_TOP = 3.0e-3, 15.0e-3
VIA = {float(spec["via_side_mm"])!r}e-3   # 短路过孔柱截面（HFSS 锚同款）
N_SUB_LAYER = 6                    # 基板 z 层数
Z_GRID_EPS = 1e-6                  # #152 去重/守卫判据（严格 >）
VIA_MODE = {spec["mode"]!r}              # 过孔对照口径（C12 旋钮；唯一几何差异）

W = _NOM["w_mm"] * 1e-3
S = _NOM["s_mm"] * 1e-3
L = _NOM["l_sect_mm"] * 1e-3
H = MARCHAND2_NOMINAL_INPUTS["h_mm"] * 1e-3
ER = MARCHAND2_NOMINAL_INPUTS["er"]
TAND = MARCHAND2_NOMINAL_INPUTS["tan_d"]

XA, XB, XC = 0.0, L, 2.0 * L       # 节 1 起点 / 结平面 / 开路端
VIA1_C = W + S                                     # 副 1 中心 y（过孔中心）
Y_M_LO, Y_M_HI = -W / 2, W / 2                     # 主线
Y_S1_LO, Y_S1_HI = W / 2 + S, 3 * W / 2 + S        # 副 1（+y）
Y_S2_LO, Y_S2_HI = -3 * W / 2 - S, -W / 2 - S      # 副 2（−y）
XDOM = PORT_CLEAR + L_PORT + FEED_CLEAR            # 域边（−x）
DOM_X = XC + PAD_X
DOM_Y = 3 * W / 2 + S + PAD_Y
X_E = -XDOM + PORT_CLEAR           # MSLPort 段起点
# 测量面：激励盒(10·NEAR)之外 4·NEAR——烟测实证近场毒化守卫（#347）
MEAS_SHIFT = 14.0 * NEAR
assert abs(MEAS_SHIFT - 10.0 * NEAR) >= 3.9 * NEAR   # ≥4·NEAR（浮点留余量）
assert MEAS_SHIFT < L_PORT - 2.0 * NEAR

_OE_CAND = (
    os.environ.get("RFAUTO_OPENEMS_BIN"),
    os.path.normpath(os.path.join(sys.prefix, "..", "..", "vendor", "openEMS",
                                  "install", "bin")),
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "..", "..", "..", "vendor", "openEMS",
                                  "install", "bin")))
_OE_BIN = next((c for c in _OE_CAND if c and os.path.isdir(c)), "")
if _OE_BIN:
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.ports import LumpedPort, MSLPort

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(0.5 * (F_LO + F_HI), 0.5 * (F_HI - F_LO))
FDTD.SetBoundaryCond(["PML_8", "PML_8", "PML_8", "PML_8", "MUR", "MUR"])

mesh = CSX.GetGrid()
'''
    body = '''
# ── 网格：结构线精确入网 + 平滑（#311：SmoothMeshLines 只细分 >阈值 区间）──
# （rod 专属过孔网格线在 sheet 模式保留为纯加密——单变量：网格逐字节一致）
via1_c = VIA1_C
x_lines = [-XDOM, DOM_X, X_E, X_E + L_PORT,
           XA, XB - NEAR, XB, XB + NEAR, XC,
           XA, XA + VIA / 2, XA + VIA,             # 过孔 1（x 边+中线）
           XC - VIA, XC - VIA / 2, XC]             # 过孔 2
y_lines = [0.0, -DOM_Y, DOM_Y,
           Y_M_LO, Y_M_HI, Y_S1_LO, Y_S1_HI, Y_S2_LO, Y_S2_HI,
           W / 2 + S / 2, -(W / 2 + S / 2),        # 缝中线（#311）
           via1_c, via1_c - VIA / 2, via1_c + VIA / 2,
           -via1_c, -via1_c + VIA / 2, -via1_c - VIA / 2]
z_lines = [*np.linspace(0.0, H, N_SUB_LAYER + 1),
           H / 2, -Z_BOT, H + Z_TOP]   # 不加 ±NEAR：与层线 0.254 近重合 7µm（#152）
_dom_edge = {"x": [-XDOM, DOM_X], "y": [-DOM_Y, DOM_Y],
             "z": [-Z_BOT, H + Z_TOP]}
for ax, pts in (("x", x_lines), ("y", y_lines), ("z", z_lines)):
    mesh.AddLine(ax, np.asarray(sorted(set(pts)), dtype=float))
    mesh.SmoothMeshLines(ax, NEAR)
    mesh.AddLine(ax, np.asarray(_dom_edge[ax], dtype=float))
    mesh.SmoothMeshLines(ax, BASE)

# #152 去重（严格 >，与 #283 守卫同口径）
min_span = {}
for ax in ("x", "y", "z"):
    ls = np.asarray(mesh.GetLines(ax), dtype=float)
    keep = [ls[0]]
    for v in ls[1:]:
        if v - keep[-1] > Z_GRID_EPS:
            keep.append(v)
    mesh.SetLines(ax, np.asarray(keep, dtype=float))
    min_span[ax] = float(np.min(np.diff(mesh.GetLines(ax))))

# ── 几何（米；顶铜+过孔柱同一 metal 属性，gnd 独立属性共面搭接）──
sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * 2.5e9 * 8.854187817e-12 * ER)
sub.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, H), priority=0)
gnd = CSX.AddMetal("gnd")
gnd.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, 0.0), priority=10)
msl = CSX.AddMetal("msl")
msl.AddBox((-DOM_X, Y_M_LO, H), (XC, Y_M_HI, H), priority=10)       # 主线
msl.AddBox((XA, Y_S1_LO, H), (XB, Y_S1_HI, H), priority=10)         # 副 1
msl.AddBox((XB, Y_S2_LO, H), (XC, Y_S2_HI, H), priority=10)         # 副 2
'''
    tail = '''
# ── 端口 ──
p1 = MSLPort(CSX, port_nr=1, metal_prop=msl,
             start=np.array([X_E, W / 2, H]),
             stop=np.array([X_E + L_PORT, -W / 2, 0.0]),
             prop_dir="x", exc_dir="z", excite=1.0,
             FeedShift=10 * NEAR, MeasPlaneShift=MEAS_SHIFT, priority=10)
for prim in msl.GetAllPrimitives():
    if prim.GetPriority() < 10:
        prim.SetPriority(10)
p2 = LumpedPort(CSX, 2, 140.0,
                np.array([XB - NEAR, Y_S1_LO, 0.0]),
                np.array([XB + NEAR, Y_S1_HI, H]),
                "z", excite=0, priority=5)
p3 = LumpedPort(CSX, 3, 140.0,
                np.array([XB - NEAR, Y_S2_LO, 0.0]),
                np.array([XB + NEAR, Y_S2_HI, H]),
                "z", excite=0, priority=5)


def _audit(mesh, min_span):
    """离线守卫（烟测 criteria.md 预声明口径逐行同文；任一 FAIL 即不起跑）。

    注：via1/via2_chain 两键是烟测逐字节保留的常量几何恒真式（sheet 模式下
    不描述薄片）——薄片/过孔的**原语实测守卫全在 _via_guard**（分支实现）。
    """
    import numpy as np

    def _has(ax, v):
        ls = np.asarray(mesh.GetLines(ax), dtype=float)
        hits = ls[np.abs(ls - v) <= Z_GRID_EPS]
        return bool(len(hits) > 0), (float(hits[0]) if len(hits) else None)

    def _gap_internal(lo, hi):
        ls = np.asarray(mesh.GetLines("y"), dtype=float)
        return int(np.sum((ls > lo + Z_GRID_EPS) & (ls < hi - Z_GRID_EPS)))

    def _port_guard(x_edges, y_edges):
        """三轴 start/mid/stop 三线齐备 + 邻距严格 > 1e-6（#283）。"""
        res = {}
        for ax, (lo, mid, hi) in (("x", x_edges), ("y", y_edges),
                                  ("z", (0.0, H / 2, H))):
            ok_lo, _ = _has(ax, lo)
            ok_mid, _ = _has(ax, mid)
            ok_hi, _ = _has(ax, hi)
            ls = np.asarray(mesh.GetLines(ax), dtype=float)
            span = float(np.min(np.abs(np.diff(ls))))
            res[ax] = {"lines": bool(ok_lo and ok_mid and ok_hi),
                       "min_span_m": span, "gt_eps": bool(span > Z_GRID_EPS)}
        return res

    checks = {
        "gap1_internal_lines_ge1": _gap_internal(W / 2, W / 2 + S) >= 1,
        "gap2_internal_lines_ge1": _gap_internal(-W / 2 - S, -W / 2) >= 1,
        "port2_box": _port_guard((XB - NEAR, XB, XB + NEAR),
                                 (Y_S1_LO, W + S, Y_S1_HI)),
        "port3_box": _port_guard((XB - NEAR, XB, XB + NEAR),
                                 (Y_S2_LO, -(W + S), Y_S2_HI)),
        "excite_inset_ge2base": bool((X_E + 10 * NEAR) - (-XDOM) >= 2 * BASE),
        "excite_inset_m": float((X_E + 10 * NEAR) - (-XDOM)),
        "min_span_m": min_span,
        "min_span_ge_10um": bool(all(v >= 10e-6 for v in min_span.values())),
        # 过孔-副线-地 z 向搭接（#212 连通审计：xy 足印重叠 + z 两端触金属）
        "via1_chain": bool(XA + VIA <= XB and Y_S1_LO < VIA1_C - VIA / 2
                           and VIA1_C + VIA / 2 < Y_S1_HI),
        "via2_chain": bool(XC - VIA >= XB and Y_S2_LO < -VIA1_C - VIA / 2
                           and -VIA1_C + VIA / 2 < Y_S2_HI),
        "mslport_lines_ge5": bool(len(mesh.GetLines("x")) > 5),
    }
    flat = {}
    for k, v in checks.items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                if isinstance(vv, dict):
                    flat[f"{k}.{kk}.lines"] = vv["lines"]
                    flat[f"{k}.{kk}.gt_eps"] = vv["gt_eps"]
                else:
                    flat[f"{k}.{kk}"] = vv
        else:
            flat[k] = v
    checks["all_pass"] = all(v for v in flat.values() if isinstance(v, bool))
    return checks


def _via_guard(mesh, msl):
    """过孔对照几何合法性守卫（C12；#212 原语实测 + #283 落格严格 > 口径）。

    rod：柱实体尺寸/位置/贯通/足印内嵌副线 + 过孔 6 线落格 + 足印内网格区间
    ≥2（三线齐备，烟测口径超集）；sheet：两面墙零 x 厚、全臂宽、贴 z=0/H、
    x 落在设计短路平面网格线、与主线间隙=S（不短路耦合缝）。分支按 VIA_MODE
    运行时判定（两模式渲染文本在此函数逐字节一致）。
    """
    import numpy as np

    def _has(ax, v):
        ls = np.asarray(mesh.GetLines(ax), dtype=float)
        return bool(np.any(np.abs(ls - v) <= Z_GRID_EPS))

    def _cells(ax, lo, hi):
        ls = np.asarray(mesh.GetLines(ax), dtype=float)
        n_in = int(np.sum((ls > lo + Z_GRID_EPS) & (ls < hi - Z_GRID_EPS)))
        return n_in + 1   # [lo,hi] 闭区间内网格区间数

    boxes = []
    for _prim in msl.GetAllPrimitives():
        if hasattr(_prim, "GetStart"):
            _s = np.asarray(_prim.GetStart(), dtype=float)
            _e = np.asarray(_prim.GetStop(), dtype=float)
            boxes.append((np.minimum(_s, _e), np.maximum(_s, _e)))
    res: dict[str, Any] = {}
    if VIA_MODE == "rod":
        rods = [b for b in boxes
                if abs((b[1][0] - b[0][0]) - VIA) <= 1e-12
                and abs((b[1][1] - b[0][1]) - VIA) <= 1e-12
                and abs(b[0][2]) <= 1e-12 and abs(b[1][2] - H) <= 1e-12]
        res["rod_count_eq2"] = len(rods) == 2
        if len(rods) == 2:
            b1 = min(rods, key=lambda b: b[0][1])   # y 较小者=副 2 侧
            b2 = max(rods, key=lambda b: b[0][1])
            res["rod1_pos"] = bool(abs(b2[0][0] - XA) <= 1e-12
                                   and abs(b2[0][1] - (via1_c - VIA / 2)) <= 1e-12)
            res["rod2_pos"] = bool(abs(b1[1][0] - XC) <= 1e-12
                                   and abs(b1[0][1] - (-via1_c - VIA / 2)) <= 1e-12)
            res["rod1_in_sub1"] = bool(b2[1][0] <= XB + 1e-12
                                       and VIA1_C + VIA / 2 < Y_S1_HI
                                       and VIA1_C - VIA / 2 > Y_S1_LO)
            res["via_lines_x1"] = all(_has("x", v) for v in (XA, XA + VIA / 2, XA + VIA))
            res["via_lines_y1"] = all(_has("y", v)
                                      for v in (via1_c - VIA / 2, via1_c, via1_c + VIA / 2))
            res["via_lines_x2"] = all(_has("x", v)
                                      for v in (XC - VIA, XC - VIA / 2, XC))
            res["via_lines_y2"] = all(_has("y", v) for v in
                                      (-via1_c - VIA / 2, -via1_c, -via1_c + VIA / 2))
            res["via1_cells_ge2"] = bool(_cells("x", XA, XA + VIA) >= 2
                                         and _cells("y", via1_c - VIA / 2,
                                                    via1_c + VIA / 2) >= 2)
            res["via2_cells_ge2"] = bool(_cells("x", XC - VIA, XC) >= 2
                                         and _cells("y", -via1_c - VIA / 2,
                                                    -via1_c + VIA / 2) >= 2)
    else:
        walls = [b for b in boxes
                 if abs(b[1][0] - b[0][0]) <= 1e-12
                 and abs(b[0][2]) <= 1e-12 and abs(b[1][2] - H) <= 1e-12
                 and (b[1][1] - b[0][1]) > 0.0]
        res["wall_count_eq2"] = len(walls) == 2
        if len(walls) == 2:
            w1 = min(walls, key=lambda b: b[0][1])   # y 较小者=副 2 侧
            w2 = max(walls, key=lambda b: b[0][1])
            res["wall1_zero_x_at_short_plane"] = bool(abs(w2[0][0] - XA) <= 1e-12
                                                      and abs(w2[1][0] - XA) <= 1e-12)
            res["wall2_zero_x_at_short_plane"] = bool(abs(w1[0][0] - XC) <= 1e-12
                                                      and abs(w1[1][0] - XC) <= 1e-12)
            res["wall1_full_span"] = bool(abs(w2[0][1] - Y_S1_LO) <= 1e-12
                                          and abs(w2[1][1] - Y_S1_HI) <= 1e-12)
            res["wall2_full_span"] = bool(abs(w1[0][1] - Y_S2_LO) <= 1e-12
                                          and abs(w1[1][1] - Y_S2_HI) <= 1e-12)
            res["wall1_gap_to_main_eq_s"] = bool(abs((w2[0][1] - W / 2) - S) <= 1e-12)
            res["wall2_gap_to_main_eq_s"] = bool(abs((-W / 2 - w1[1][1]) - S) <= 1e-12)
            res["wall_x_lines_on_grid"] = bool(_has("x", XA) and _has("x", XC))
    return res


audit = _audit(mesh, min_span)
audit["boxes"] = {
    "main": [-DOM_X, Y_M_LO, XC, Y_M_HI], "sub1": [XA, Y_S1_LO, XB, Y_S1_HI],
    "sub2": [XB, Y_S2_LO, XC, Y_S2_HI], "via1": [XA, via1_c - VIA / 2,
                                                 XA + VIA, via1_c + VIA / 2],
    "via2": [XC - VIA, -via1_c - VIA / 2, XC, -via1_c + VIA / 2]}
via_guard = _via_guard(mesh, msl)
audit["via_guard"] = via_guard
audit["all_pass"] = bool(audit["all_pass"]) and all(
    v for v in via_guard.values() if isinstance(v, bool))
audit["via"] = {"mode": VIA_MODE, "via_side_mm": VIA * 1e3,
                "note": "C12 生效值（#283）：两变体唯一差异=过孔金属原语"}
audit["mesh_lines"] = {ax: len(mesh.GetLines(ax)) for ax in "xyz"}
audit["design"] = _DESIGN.to_dict()
audit["layout_m"] = {"XDOM": XDOM, "DOM_X": DOM_X, "DOM_Y": DOM_Y,
                     "X_E": X_E, "L_PORT": L_PORT, "BASE": BASE,
                     "NEAR": NEAR, "NRTS": NRTS, "F_LO": F_LO, "F_HI": F_HI,
                     "NF": NF}
HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "audit_mesh.json"), "w", encoding="utf-8") as fh:
    json.dump(audit, fh, ensure_ascii=False, indent=1)
print("audit all_pass =", audit["all_pass"],
      "| via_guard =", {k: v for k, v in via_guard.items()}, flush=True)
if not audit["all_pass"]:
    print("AUDIT FAIL — 不起跑", flush=True)
    raise SystemExit(2)

if os.environ.get("RFAUTO_SKIP_RUN") == "1":
    print("RFAUTO_SKIP_RUN=1 → 审计模式退出（零仿真）", flush=True)
    raise SystemExit(0)

SIM_PATH = os.path.abspath(os.path.join(HERE, "fdtd"))
FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

f = np.linspace(F_LO, F_HI, NF)
p1.CalcPort(SIM_PATH, f)
p2.CalcPort(SIM_PATH, f)
p3.CalcPort(SIM_PATH, f)


def _cx(a):
    return {"re": [float(v.real) for v in a],
            "im": [float(v.imag) for v in a]}


summary = {
    "ok": True, "kind": "marchand_via_ab_render", "excite_port": 1,
    "via_mode": VIA_MODE, "via_side_mm": VIA * 1e3,
    "f0_hz": 2.5e9, "f_lo_hz": F_LO, "f_hi_hz": F_HI, "nf": NF,
    "nrts_declared": NRTS, "base_mm": BASE * 1e3, "near_mm": NEAR * 1e3,
    "design": _NOM,
    "uf1_inc": _cx(p1.uf_inc), "uf1_ref": _cx(p1.uf_ref),
    "uf2_ref": _cx(p2.uf_ref), "uf2_inc": _cx(p2.uf_inc),
    "uf3_ref": _cx(p3.uf_ref), "uf3_inc": _cx(p3.uf_inc),
    "z1_ref": _cx(np.asarray(p1.Z_ref, dtype=complex)),
    "beta_msl": [float(v) for v in np.real(p1.beta)],
    "gates_ref": {"band_ghz": [2.25, 2.75],
                  "source": "core MARCHAND2_GATES（runner judge 单源读取）"},
}
# 时域衰减统计（#344）：各口 post-pulse 峰值、末 10% 窗电平、末 50% 斜率
decay = {}
t = np.asarray(p1.u_time, dtype=float)
for tag, port in (("p1", p1), ("p2", p2), ("p3", p3)):
    ut = np.abs(np.asarray(port.ut_tot, dtype=float))
    tp = t[t <= 2.0e-9]
    post = ut[t > 2.0e-9] if len(tp) < len(t) else ut
    peak = float(np.max(post)) if len(post) else 0.0
    n10 = max(1, int(0.10 * len(t)))
    tail = float(np.max(ut[-n10:])) if len(ut) else 0.0
    n5 = max(2, len(t) // 2)
    tt, uu = t[-n5:], ut[-n5:]
    seg = max(2, len(tt) // 6)
    floor = max(peak * 1e-12, 1e-30)   # 相对峰值地板（绝对地板会给假斜率）
    xs = [20 * math.log10(max(float(np.max(uu[i * seg:(i + 1) * seg])),
                              floor)) for i in range(6)]
    xc = [float(np.median(tt[i * seg:(i + 1) * seg])) for i in range(6)]
    slope = float(np.polyfit(xc, xs, 1)[0]) * 1e-9    # dB/s → dB/ns
    decay[tag] = {
        "t_end_ns": float(t[-1] * 1e9), "n_samples": len(t),
        "post_pulse_peak": peak, "tail10_rel_db":
            20 * math.log10(max(tail, 1e-30) / max(peak, 1e-30)),
        "tail_slope_db_per_ns": slope}
summary["decay"] = decay
summary["mesh_lines"] = audit["mesh_lines"]
summary["min_span_m"] = audit["min_span_m"]
with open(os.path.join(HERE, "summary.json"), "w", encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
np.savez(os.path.join(HERE, "port_time.npz"),
         t=t, ut1=p1.ut_tot, ut2=p2.ut_tot, ut3=p3.ut_tot)

# 原始 sparams.csv：线基 S11 + 混合参考 S21/S31（raw，判读在 runner --judge）
s11_raw = p1.uf_ref / p1.uf_inc
z1 = np.abs(p1.Z_ref)
s21_mix = p2.uf_ref / p1.uf_inc * np.sqrt(z1 / 140.0)
s31_mix = p3.uf_ref / p1.uf_inc * np.sqrt(z1 / 140.0)
with open(os.path.join(HERE, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_S11_raw", "im_S11_raw", "re_S21_mix",
                 "im_S21_mix", "re_S31_mix", "im_S31_mix", "z1_re",
                 "z1_im", "beta_rad_m"])
    for i, fi in enumerate(f):
        w_.writerow([fi, s11_raw[i].real, s11_raw[i].imag,
                     s21_mix[i].real, s21_mix[i].imag, s31_mix[i].real,
                     s31_mix[i].imag, np.real(p1.Z_ref[i]),
                     np.imag(p1.Z_ref[i]), float(np.real(p1.beta[i]))])
print("render+run done; via_mode =", VIA_MODE,
      "| decay p1/p2/p3 tail10 dB =",
      [round(decay[k]["tail10_rel_db"], 1) for k in ("p1", "p2", "p3")],
      flush=True)
'''
    return header + body + via_block + tail


# ══ DP-8：模板 pin 契约 + 几何组合契约（2026-09-24 df6；openems_templates.py
#    唯一增量面=port_pins 注册 + layout 契约，缺省渲染零变化——字节钉复验为门，
#    runs/df6_dp8compose/criteria.md §0/§3）════════════════════════════════════
# 契约形态（图元化，非文本拼接）：compose_layout(params, band, base, h, frame)
# → {pins, dom/bbox, primitives, plates_top, bottom_plate, bc_compat,
#    face_on_boundary, clearance_m, span_m, substrate, guards_text}；
# 文本发射由 core.compose.layout_netlist 单一发射器承担（图元→CSXCAD 语句，
# 属性名由引擎加 "__<instance_id>" 命名空间）。

#: siw pin schema（静态声明；position=名义局部坐标米、z_ref_ohm=None=Z_PV
#: 闭式同源注入（layout 期按本次参数精算，与 R_PORT 字面量同源）、
#: direction=外法向单位向量（±x/±y 四向枚举）、n_modes 预留）。
SIW_PORT_PINS: list[dict[str, Any]] = [
    {
        "pin_id": "p1",
        "position": [0.0, -0.0315362],
        "direction": [0, -1],
        "z_ref_ohm": None,
        "ref_plane_offset_m": 0.0,
        "port_type": "lumped",
        "n_modes": None,
        "cross_section": {"kind": "siw", "w_mm": 12.1317, "d_mm": 0.6,
                          "s_mm": 1.0, "h_mm": 0.508, "er": 3.66},
    },
    {
        "pin_id": "p2",
        "position": [0.0, 0.0315362],
        "direction": [0, 1],
        "z_ref_ohm": None,
        "ref_plane_offset_m": 0.0,
        "port_type": "lumped",
        "n_modes": None,
        "cross_section": {"kind": "siw", "w_mm": 12.1317, "d_mm": 0.6,
                          "s_mm": 1.0, "h_mm": 0.508, "er": 3.66},
    },
]

#: msl_siw_taper pin schema（msl 端=50Ω 馈线端面（贴域界）；siw 端=顶板缘
#: 截面（Z_PV 闭式注入）。position 名义=TEMPLATE_NOMINAL 缺省参数值）。
MSL_SIW_TAPER_PORT_PINS: list[dict[str, Any]] = [
    {
        "pin_id": "msl",
        "position": [0.0, -0.0476483],
        "direction": [0, -1],
        "z_ref_ohm": 50.0,
        "ref_plane_offset_m": 0.0,
        "port_type": "msl",
        "n_modes": None,
        "cross_section": {"kind": "msl", "w_mm": 1.1198, "h_mm": 0.508,
                          "er": 3.66},
    },
    {
        "pin_id": "siw",
        "position": [0.0, 0.0315362],
        "direction": [0, 1],
        "z_ref_ohm": None,
        "ref_plane_offset_m": 0.0,
        "port_type": "lumped",
        "n_modes": None,
        "cross_section": {"kind": "siw", "w_mm": 12.1317, "d_mm": 0.6,
                          "s_mm": 1.0, "h_mm": 0.508, "er": 3.66},
    },
]

# 注册（opt-in 渐进：改值不改键——TEMPLATE_META 字典键集/尾部序不受影响，
# #247 槽线族尾部追加契约保持；五消费者对既有模板增值均不敏感）
TEMPLATE_META["siw"]["port_pins"] = SIW_PORT_PINS
TEMPLATE_META["msl_siw_taper"]["port_pins"] = MSL_SIW_TAPER_PORT_PINS


def _compose_pin(pin_id: str, position: tuple[float, float],
                 direction: tuple[float, float], *, z_ref: float,
                 port_type: str, cross_section: dict[str, Any],
                 width_m: float, ref_plane: float = 0.0,
                 n_modes: int | None = None) -> dict[str, Any]:
    """layout 期 pin 解析值（schema 静态声明的运行时对应物，frame 已仿射）。"""
    return {"pin_id": pin_id,
            "position": [float(position[0]), float(position[1])],
            "direction": [float(direction[0]), float(direction[1])],
            "z_ref_ohm": float(z_ref), "ref_plane_offset_m": float(ref_plane),
            "port_type": port_type, "n_modes": n_modes,
            "cross_section": cross_section, "width_m": float(width_m)}


def _siw_compose_layout(params: dict[str, Any],
                        freq_range_ghz: tuple[float, float], base_m: float,
                        h_m: float,
                        frame: tuple[float, float, bool]) -> dict[str, Any]:
    """siw 组合契约（dp8）：结构限于段内（_port_mode 强制 v2——藩篱止于端口
    面；v1 藩篱贯通域与组合不相容，显式报错。standalone 缺省 v1 不受影响）。
    顶板=段区间显式零厚盒（组合域顶 MUR，SIW 顶壁由板承担）；底板声明=局部
    域覆盖（引擎统一整域单盒发射）。全部坐标按 frame 仿射到全局（米）。"""
    from rfauto.core.compose.layout_netlist import frame_apply_dir, frame_apply_point

    p = dict(params)
    mode = str(p.setdefault("_port_mode", "v2"))
    if mode != "v2":
        raise ValueError(
            f"siw 组合契约要求 _port_mode='v2'（藩篱止于端口面=结构限于段内；"
            f"得到 {mode!r}——v1 藩篱贯通全域与组合域合并不相容；standalone "
            "缺省 v1 不受本契约影响")
    lay = siw_layout(p, freq_range_ghz, base_m, h_m)
    h = float(lay["h"])
    er = float(lay["er"])
    w, d = float(lay["w"]), float(lay["d"])
    dom_x, dom_y = float(lay["dom_x"]), float(lay["dom_y"])
    y1, y2 = float(lay["y1"]), float(lay["y2"])
    via_y = tuple(frame_apply_point(frame, (0.0, float(vy)))[1]
                  for vy in lay["via_y"])
    y1g = frame_apply_point(frame, (0.0, y1))[1]
    y2g = frame_apply_point(frame, (0.0, y2))[1]
    y1g, y2g = min(y1g, y2g), max(y1g, y2g)
    x0 = frame_apply_point(frame, (-dom_x, 0.0))[0]
    x1 = frame_apply_point(frame, (dom_x, 0.0))[0]
    xlo, xhi = min(x0, x1), max(x0, x1)
    ydom0 = frame_apply_point(frame, (0.0, -dom_y))[1]
    ydom1 = frame_apply_point(frame, (0.0, dom_y))[1]
    ylo, yhi = min(ydom0, ydom1), max(ydom0, ydom1)
    r_port = round(float(lay["r_port"]), 4)
    xs_siw = {"kind": "siw", "w_mm": w * 1e3, "d_mm": d * 1e3,
              "s_mm": float(lay["s"]) * 1e3, "h_mm": h * 1e3, "er": er}
    pins = {
        "p1": _compose_pin("p1", frame_apply_point(frame, (0.0, y1)),
                           frame_apply_dir(frame, (0, -1)), z_ref=r_port,
                           port_type="lumped", cross_section=xs_siw,
                           width_m=w),
        "p2": _compose_pin("p2", frame_apply_point(frame, (0.0, y2)),
                           frame_apply_dir(frame, (0, 1)), z_ref=r_port,
                           port_type="lumped", cross_section=xs_siw,
                           width_m=w),
    }
    prims: list[dict[str, Any]] = [
        # SIW 顶壁显式零厚板（段区间；组合域顶=MUR，顶壁由本板承担）
        {"kind": "box", "prop": "siw_top",
         "start": [xlo, y1g, h], "stop": [xhi, y2g, h], "priority": 10},
    ]
    for vy in via_y:
        for vx in (-w / 2.0, w / 2.0):
            prims.append({"kind": "cylinder", "prop": "siw_via",
                          "start": [vx, vy, 0.0], "stop": [vx, vy, h],
                          "radius": d / 2.0, "priority": 10})
    for pin_id, y_face in (("p1", y1), ("p2", y2)):
        pos = frame_apply_point(frame, (0.0, y_face))
        x_a = frame_apply_point(frame, (-w / 2.0, 0.0))[0]
        x_b = frame_apply_point(frame, (w / 2.0, 0.0))[0]
        py = float(lay["py"])
        prims.append({"kind": "port", "pin": pin_id, "port_type": "lumped",
                      "prop": "siw_top",
                      "start": [min(x_a, x_b), pos[1] - py, 0.0],
                      "stop": [max(x_a, x_b), pos[1] + py, h],
                      "axis": "z", "ref_impedance": r_port, "priority": 5})
    return {"pins": pins,
            "dom": (min(xlo, xhi), ylo, max(xlo, xhi), yhi),
            "bbox": (xlo, y1g, xhi, y2g),
            "primitives": prims,
            "plates_top": [(xlo, y1g, xhi, y2g)],
            "bottom_plate": (min(xlo, xhi), ylo, max(xlo, xhi), yhi),
            "bc_compat": "siw_family",
            "face_on_boundary": {"p1": False, "p2": False},
            "clearance_m": {"p1": 16.0 * base_m, "p2": 16.0 * base_m},
            "span_m": {"p1": float(y2 - y1), "p2": float(y2 - y1)},
            "substrate": {"h_m": h, "er": er, "tan_d": 0.0037},
            "guards_text": []}


def _msl_siw_taper_compose_layout(params: dict[str, Any],
                                  freq_range_ghz: tuple[float, float],
                                  base_m: float, h_m: float,
                                  frame: tuple[float, float, bool]
                                  ) -> dict[str, Any]:
    """msl_siw_taper 组合契约（dp8）：msl pin 内连显式不支持（馈线延伸 P3+
    预留，引擎 D4 拒绝）；全部坐标按 frame 仿射到全局（米）。"""
    from rfauto.core.compose.layout_netlist import frame_apply_dir, frame_apply_point

    lay = msl_siw_taper_layout(params, freq_range_ghz, base_m, h_m)
    h = float(lay["h"])
    er = float(lay["er"])
    tan_d = float(lay["tan_d"])
    w, d = float(lay["w"]), float(lay["d"])
    w50, w_end = float(lay["w50"]), float(lay["w_end"])
    dom_x, dom_y = float(lay["dom_x"]), float(lay["dom_y"])
    y_plate, y_feed_in = float(lay["y_plate"]), float(lay["y_feed_in"])
    seam = float(lay["seam"])
    feed_len = float(lay["feed_len"])
    near = float(lay["near"])

    def xy(local: tuple[float, float]) -> tuple[float, float]:
        return frame_apply_point(frame, local)

    xlo = min(xy((-dom_x, 0.0))[0], xy((dom_x, 0.0))[0])
    xhi = max(xy((-dom_x, 0.0))[0], xy((dom_x, 0.0))[0])
    ylo = xy((0.0, -dom_y))[1]
    yhi = xy((0.0, dom_y))[1]
    y_plate_g = sorted((xy((0.0, -y_plate))[1], xy((0.0, y_plate))[1]))
    y_feed_g = sorted((xy((0.0, -y_feed_in))[1], xy((0.0, y_feed_in))[1]))
    # 两段 50Ω 馈线（域界→锥起点）与双锥（梯形多边形，宽 w50→w_end）
    feed_segs = [(ylo, y_feed_g[0]), (y_feed_g[1], yhi)]
    taper_polys = [(y_feed_g[0], y_plate_g[0] - seam),
                   (y_plate_g[1] + seam, y_feed_g[1])]
    prims: list[dict[str, Any]] = []
    for _ya, _yb in feed_segs:
        prims.append({"kind": "box", "prop": "msl_top",
                      "start": [xy((-w50 / 2.0, 0.0))[0], min(_ya, _yb), h],
                      "stop": [xy((w50 / 2.0, 0.0))[0], max(_ya, _yb), h],
                      "priority": 10})
    for _ya, _yb in taper_polys:
        _ys = sorted((xy((0.0, _ya))[1], xy((0.0, _yb))[1]))
        prims.append({"kind": "polygon", "prop": "msl_top",
                      "xs": [xy((-w50 / 2.0, 0.0))[0],
                             xy((w50 / 2.0, 0.0))[0],
                             xy((w_end / 2.0, 0.0))[0],
                             xy((-w_end / 2.0, 0.0))[0]],
                      "ys": [_ys[0], _ys[0], _ys[1], _ys[1]],
                      "elevation": h, "priority": 10})
    # SIW 顶壁显式板（波导区 |y|≤y_plate；组合域顶=MUR，顶壁由本板承担）
    prims.append({"kind": "box", "prop": "msl_top",
                  "start": [xlo, y_plate_g[0], h],
                  "stop": [xhi, y_plate_g[1], h], "priority": 10})
    via_y = tuple(frame_apply_point(frame, (0.0, float(vy)))[1]
                  for vy in lay["via_y"])
    for vy in via_y:
        for vx in (-w / 2.0, w / 2.0):
            prims.append({"kind": "cylinder", "prop": "siw_via",
                          "start": [vx, vy, 0.0], "stop": [vx, vy, h],
                          "radius": d / 2.0, "priority": 10})
    xs_msl = {"kind": "msl", "w_mm": w50 * 1e3, "h_mm": h * 1e3, "er": er}
    xs_siw = {"kind": "siw", "w_mm": w * 1e3, "d_mm": d * 1e3,
              "s_mm": float(lay["s"]) * 1e3, "h_mm": h * 1e3, "er": er}
    pins = {
        "msl": _compose_pin("msl", xy((0.0, -dom_y)),
                            frame_apply_dir(frame, (0, -1)), z_ref=50.0,
                            port_type="msl", cross_section=xs_msl,
                            width_m=w50),
        "siw": _compose_pin("siw", xy((0.0, y_plate)),
                            frame_apply_dir(frame, (0, 1)),
                            z_ref=round(float(lay["z_pv"]), 4),
                            port_type="lumped", cross_section=xs_siw,
                            width_m=w),
    }
    # msl pin 端口图元（面贴域界 #174）：端点=standalone 端口的精确刚体变换
    #（start=(W50/2,−DOM_Y,H_SUB)→stop=(−W50/2,−Y_FEED_IN,0) 逐点仿射，非
    # min/max 近似——rot180 下馈线在全局 +y 侧，FaceShift 方向语义=P3 真跑
    # 核对项，criteria.md §5）
    _face = xy((0.0, -dom_y))
    _inner = xy((0.0, -y_feed_in))
    prims.append({"kind": "port", "pin": "msl", "port_type": "msl",
                  "prop": "msl_top",
                  "start": [xy((w50 / 2.0, 0.0))[0], _face[1], h],
                  "stop": [xy((-w50 / 2.0, 0.0))[0], _inner[1], 0.0],
                  "axis": "y", "feed_shift": 10.0 * near,
                  "meas_plane_shift": feed_len / 3.0, "priority": 10})
    guards_text = [
        f'if not {feed_len / 3.0!r} - {10.0 * near!r} >= {3.9 * near!r}:',
        '    raise SystemExit("msl_siw_taper #" + "347" + ": "',
        '                     "MeasPlaneShift/FeedShift 间距不足 3.9·NEAR")',
    ]
    return {"pins": pins, "dom": (xlo, min(ylo, yhi), xhi, max(ylo, yhi)),
            "bbox": (xlo, min(ylo, yhi), xhi, max(ylo, yhi)),
            "primitives": prims,
            "plates_top": [(xlo, y_plate_g[0], xhi, y_plate_g[1])],
            "bottom_plate": (xlo, min(ylo, yhi), xhi, max(ylo, yhi)),
            "bc_compat": "siw_family",
            "face_on_boundary": {"msl": True, "siw": False},
            "clearance_m": {"msl": 0.0, "siw": 16.0 * base_m},
            "span_m": {"msl": 2.0 * dom_y, "siw": y_plate + dom_y},
            "substrate": {"h_m": h, "er": er, "tan_d": tan_d},
            "guards_text": guards_text}


#: 组合契约注册表（opt-in：service/compose_service 注入引擎；模板未在此注册
#: 即不可被组合引用——显式报错即正确行为）。
COMPOSE_CONTRACTS: dict[str, dict[str, Any]] = {
    "siw": {"layout": _siw_compose_layout},
    "msl_siw_taper": {"layout": _msl_siw_taper_compose_layout},
}


# ─── §MS_METASURFACE 超表面/FSS 族（2026-09-24 df6 DP-10，文末注册块）─────────
# 规格与判据：docs/plan_deepdive_specs_20260924.md §DP-10 +
# runs/df6_dp10ms/criteria.md（预声明冻结）。离线内核=core/metasurface_lut.py
# （名义尺寸闭式单源 #252/#1c：本段只消费不重复实现）。
#
# 波导模拟器技巧（法向入射≡无限阵@θ=0，官方 Parallel Plate Waveguide 教程
# 口径 + ports.py LumpedPort 全口径片馈语义）：
# - 域=单胞方形截面：x 对壁 PEC（E∥x 为法向场，兼容）、y 对壁 PMC
#   （E∥x 为切向场，兼容）——TEM 平面波，E∥x 极化前提（y 极化互换 PEC/PMC）；
# - 激励=全口径集总电阻片 LumpedPort（exc_dir='x'，R=η0·a/b，方胞=η0）：
#   u 探针=片中心 x 向线（TEM 电压 V=E_x·a）、i 探针=片上 y 向线
#   （I=∫H_y dy，模式电流）——CalcPort 同参考阻抗去嵌出 Γ/T；
# - 软激励（exc_type=0）语义=官方 PPW 教程 AddExcitation type 0 同源；
# - ms_patch（反射型）：z 底=地面 PEC 边界，片在空气侧，|S11|≈1 的相位
#   即反射阵 LUT（幅相分离口径：幅度非 ≈0dB=端口/网格判废信号）；
# - ms_cross/ms_jcross（透射型 FSS）：片在屏两侧空气区，S21=传输
#   （带阻/带通），底边界 MUR。
# 极化前提双处注明（meta extraction + 渲染脚本注释）；斜入射与无限阵
# 仲裁走 HFSS Floquet（J4，真机轨）。
MS_UNIT_TEMPLATES: tuple[str, ...] = ("ms_patch", "ms_cross", "ms_jcross")
METASURFACE_TEMPLATES: tuple[str, ...] = (*MS_UNIT_TEMPLATES, "ms_array_NxN")
#: 无端口模板（软平面照明散射体，audit ②/③ 独立分支）：
PORTLESS_TEMPLATES: tuple[str, ...] = ("ms_array_NxN",)
#: 波导模拟器对壁 BC（x0,x1,y0,y1）——unit 三件（E∥x 前提，见上）
_TEMPLATE_WALL_BC: dict[str, tuple[str, str, str, str]] = {
    "ms_patch": ("PEC", "PEC", "PMC", "PMC"),
    "ms_cross": ("PEC", "PEC", "PMC", "PMC"),
    "ms_jcross": ("PEC", "PEC", "PMC", "PMC"),
}


def _ms_gap_midlines(lo: float, hi: float, n: int = 3) -> list[float]:
    """1-D 缝隙 [lo,hi] 的 n+1 等分内部点（#311 缝中点精确入网口径：
    SmoothMesh 不细分 <NEAR 区间——显式 AddLine 恒保留）。"""
    if hi <= lo:
        raise ValueError(f"缝隙区间非法 [{lo}, {hi}]")
    return [lo + (hi - lo) * k / (n + 1) for k in range(1, n + 1)]


def ms_unit_layout(template: str, params: dict[str, Any],
                   freq_range_ghz: tuple[float, float], base_m: float,
                   h_m: float) -> dict[str, Any]:
    """单元三件几何/端口/域单源（siw_layout 同款；米制；渲染期守卫在本层）。

    返回 dict：period/屏几何/dom_x/dom_y/z 各面/近场线 x/y（米，字面注入）/
    min_gap_m/r_port（η0·a/b，方胞=η0）。守卫违反抛 ValueError（#266 口径：
    不许静默粗网格）。
    """
    from rfauto.core.metasurface_lut import ETA0_OHM

    near_m = base_m / float(params.get("_near_ratio", 4) or 4)
    period = float(params.get("period_mm", 14.9896)) * 1e-3
    if period <= 0:
        raise ValueError("period_mm 须 >0")
    lam0_m = 299792458.0 / ((freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9)

    def _gap_guard(min_gap_m: float, what: str) -> None:
        if min_gap_m < 3 * near_m:
            raise ValueError(
                f"{template}: {what} {min_gap_m * 1e3:.4f}mm < 3·NEAR"
                f"({3 * near_m * 1e3:.4f}mm，#266 守卫)——加密网格或放宽几何")

    def _gap_mid(gaps: list[tuple[float, float]]) -> list[float]:
        out: list[float] = []
        for lo, hi in gaps:
            out.extend(_ms_gap_midlines(lo, hi, 3))
        return out

    if template == "ms_patch":
        px = float(params.get("px_mm", 8.5406)) * 1e-3
        py = float(params.get("py_mm", 8.5406)) * 1e-3
        if not 0 < px < period or not 0 < py < period:
            raise ValueError(
                f"ms_patch: 贴片须在胞内 0<px,py<period（{px},{py} vs {period}）")
        gap_x = (period - px) / 2
        gap_y = (period - py) / 2
        _gap_guard(min(gap_x, gap_y), "胞缘缝")
        g_feed = lam0_m / 4          # 片端口距贴片 λ0/4（空气区）
        z_feed = h_m + g_feed
        z_top = z_feed + lam0_m / 4  # 片上方 λ0/4 余量再 MUR
        near_x = [-px / 2, px / 2]
        near_y = [-py / 2, py / 2]
        near_x += _gap_mid([(-period / 2, -px / 2), (px / 2, period / 2)])
        near_y += _gap_mid([(-period / 2, -py / 2), (py / 2, period / 2)])
        return {"period": period, "dom_x": period / 2, "dom_y": period / 2,
                "z_lines": [h_m, z_feed, z_top], "z_feed": z_feed,
                "z_top": z_top, "near_x": near_x, "near_y": near_y,
                "min_gap_m": min(gap_x, gap_y),
                "r_port": ETA0_OHM * period / period,
                "px": px, "py": py}

    if template == "ms_cross":
        period = float(params.get("period_mm", 11.9917)) * 1e-3
        arm = float(params.get("arm_len_mm", 4.91)) * 1e-3
        arm_w = float(params.get("arm_w_mm", 0.982)) * 1e-3
        if not 0 < 2 * arm < period or not 0 < arm_w < 2 * arm:
            raise ValueError("ms_cross: 臂须在胞内且宽 < 全跨")
        tip_gap = period - 2 * arm
        _gap_guard(tip_gap, "邻臂尖缝")
        g_air = lam0_m / 4
        z_feed_lo = -g_air           # 下片（馈）
        z_feed_hi = h_m + g_air      # 上片（收）
        z_bot = z_feed_lo - lam0_m / 8
        z_top = z_feed_hi + lam0_m / 8
        near_x = [-arm, arm, -arm_w / 2, arm_w / 2]
        near_y = [-arm, arm, -arm_w / 2, arm_w / 2]
        near_x += _gap_mid([(arm, period / 2), (-period / 2, -arm)])
        near_y += _gap_mid([(arm, period / 2), (-period / 2, -arm)])
        return {"period": period, "dom_x": period / 2, "dom_y": period / 2,
                "z_lines": [z_bot, z_feed_lo, h_m, z_feed_hi, z_top],
                "z_feed_lo": z_feed_lo, "z_feed_hi": z_feed_hi,
                "z_bot": z_bot, "z_top": z_top, "near_x": near_x,
                "near_y": near_y, "min_gap_m": tip_gap,
                "r_port": ETA0_OHM * period / period,
                "arm": arm, "arm_w": arm_w}

    if template == "ms_jcross":
        period = float(params.get("period_mm", 11.9917)) * 1e-3
        slot_len = float(params.get("slot_len_mm", 4.91)) * 1e-3
        slot_w = float(params.get("slot_w_mm", 0.491)) * 1e-3
        stub_len = float(params.get("stub_len_mm", 2.455)) * 1e-3
        if not 0 < slot_len < period or not 0 < slot_w < slot_len:
            raise ValueError("ms_jcross: 缝尺寸非法")
        stub_tip = slot_w / 2 + stub_len
        edge_gap = period / 2 - slot_len / 2
        tip_gap_y = period / 2 - stub_tip
        _gap_guard(min(edge_gap, tip_gap_y), "屏缝")
        g_air = lam0_m / 4
        z_feed_lo = -g_air
        z_feed_hi = h_m + g_air
        z_bot = z_feed_lo - lam0_m / 8
        z_top = z_feed_hi + lam0_m / 8
        # 缝缘近场线（主缝 ±slot_len/2、缝宽缘 ±slot_w/2、端枝尖）
        near_x = [-slot_len / 2, slot_len / 2,
                  -slot_len / 2 + slot_w, slot_len / 2 - slot_w]
        near_y = [-slot_w / 2, slot_w / 2,
                  -(slot_w / 2 + stub_len), slot_w / 2 + stub_len]
        near_x += _gap_mid([(slot_len / 2, period / 2),
                            (-period / 2, -slot_len / 2)])
        near_y += _gap_mid([(slot_w / 2 + stub_len, period / 2),
                            (-period / 2, -(slot_w / 2 + stub_len))])
        return {"period": period, "dom_x": period / 2, "dom_y": period / 2,
                "z_lines": [z_bot, z_feed_lo, h_m, z_feed_hi, z_top],
                "z_feed_lo": z_feed_lo, "z_feed_hi": z_feed_hi,
                "z_bot": z_bot, "z_top": z_top, "near_x": near_x,
                "near_y": near_y, "min_gap_m": min(edge_gap, tip_gap_y),
                "r_port": ETA0_OHM * period / period,
                "slot_len": slot_len, "slot_w": slot_w, "stub_len": stub_len}

    raise ValueError(f"ms_unit_layout: 未知单元模板 {template!r}")


def _ms_patch_lines(p: dict[str, Any]) -> str:
    """反射阵方贴片单元（DP-10）：接地基板+零厚方贴片，全口径片端口 TEM 馈。"""
    lay = p["_ms_layout"]
    return f'''# ms_patch 波导模拟器单元（E∥x 极化前提；y 极化需互换 PEC/PMC 对壁）
PX = {lay["px"]!r}
PY = {lay["py"]!r}
patch = CSX.AddMetal("patch")
patch.AddBox((-PX / 2, -PY / 2, H_SUB), (PX / 2, PY / 2, H_SUB), priority=10)
# 全口径集总电阻片 TEM 馈（R=η0·a/b 方胞=η0；u=片心 x 向线、i=片上 y 向线）
_port1 = LumpedPort(CSX, port_nr=1, R={round(lay["r_port"], 4)!r},
                    start=np.array([-DOM_X, -DOM_Y, {lay["z_feed"]!r}]),
                    stop=np.array([DOM_X, DOM_Y, {lay["z_feed"]!r}]),
                    exc_dir="x", excite=1, priority=5)
_port2 = _port1   # 单端口模板：footer 的 single-port fallback 口径（S21 列≡S11）
'''


def _ms_cross_lines(p: dict[str, Any]) -> str:
    """FSS 带阻十字偶极子单元（DP-10）：正交双极化稳定，屏=基板顶零厚十字。"""
    lay = p["_ms_layout"]
    return f'''# ms_cross 波导模拟器单元（E∥x 极化前提；x 臂为受激臂，y 臂=正交极化对偶臂）
ARM = {lay["arm"]!r}
ARM_W = {lay["arm_w"]!r}
cross = CSX.AddMetal("cross")
cross.AddBox((-ARM, -ARM_W / 2, H_SUB), (ARM, ARM_W / 2, H_SUB), priority=10)
cross.AddBox((-ARM_W / 2, -ARM, H_SUB), (ARM_W / 2, ARM, H_SUB), priority=10)
# 上/下全口径集总电阻片（R=η0；下片激励、上片接收，S21=透射）
_port1 = LumpedPort(CSX, port_nr=1, R={round(lay["r_port"], 4)!r},
                    start=np.array([-DOM_X, -DOM_Y, {lay["z_feed_lo"]!r}]),
                    stop=np.array([DOM_X, DOM_Y, {lay["z_feed_lo"]!r}]),
                    exc_dir="x", excite=1, priority=5)
_port2 = LumpedPort(CSX, port_nr=2, R={round(lay["r_port"], 4)!r},
                    start=np.array([-DOM_X, -DOM_Y, {lay["z_feed_hi"]!r}]),
                    stop=np.array([DOM_X, DOM_Y, {lay["z_feed_hi"]!r}]),
                    exc_dir="x", excite=0, priority=5)
for _prim in cross.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def ms_jcross_metal_boxes(period: float, slot_len: float, slot_w: float,
                          stub_len: float) -> list[tuple[float, float, float, float]]:
    """JC 缝屏金属分解（纯函数）：胞面减「主缝+4 端枝」互联孔径 → y 条带金属盒。

    孔洞：主缝 |x|≤S/2,|y|≤w/2；端枝 x∈[±(S/2−w),±S/2]、
    y∈[±w/2,±(w/2+T)]（与主缝共边互联=单孔径）。返回 (x0,y0,x1,y1) 米制。
    """
    a = period
    s, w, t = slot_len, slot_w, stub_len
    strips: list[tuple[float, float, float, float]] = []
    # 按条带下缘 y 界键控的孔洞 x 区间（#212 实测抓错版：端枝孔原被切进
    # 邻带——带内孔与带缘对位错一格，金属补集面积差 4·w·t）
    stub_metal = [(-a / 2, -s / 2), (-s / 2 + w, s / 2 - w), (s / 2, a / 2)]
    slot_metal = [(-a / 2, -s / 2), (s / 2, a / 2)]
    holes: dict[float, list[tuple[float, float]]] = {
        -(w / 2 + t): stub_metal,   # 带 [−(w/2+T), −w/2]：−y 端枝孔
        -w / 2: slot_metal,          # 带 [−w/2, w/2]：主缝孔
        w / 2: stub_metal,           # 带 [w/2, w/2+T]：+y 端枝孔
        # [w/2+T, a/2] 无键=全金属条带
    }
    # 条带界必须含全部孔洞 y 缘（含无键的 w/2+t 全金属带界），否则末带
    # 合并进端枝带、端枝孔洞越切到胞缘（#212 实测抓出的第一版错误形态）
    ys = sorted({*holes, w / 2 + t})
    bands = ([(-a / 2, ys[0])]
             + [(ys[i], ys[i + 1]) for i in range(len(ys) - 1)]
             + [(ys[-1], a / 2)])
    for y0, y1 in bands:
        xs_list = holes.get(y0)  # 带下缘=孔洞 y 界的带按孔洞 x 分段
        if xs_list is None:
            strips.append((-a / 2, y0, a / 2, y1))
            continue
        for x0, x1 in xs_list:
            strips.append((x0, y0, x1, y1))
    return strips


def _ms_jcross_lines(p: dict[str, Any]) -> str:
    """FSS 带通 Jerusalem cross 缝单元（DP-10）：互联缝孔径，屏=孔洞补集盒。"""
    lay = p["_ms_layout"]
    boxes = ms_jcross_metal_boxes(lay["period"], lay["slot_len"],
                                  lay["slot_w"], lay["stub_len"])
    body = "\n".join(
        f"screen.AddBox(({x0!r}, {y0!r}, H_SUB), ({x1!r}, {y1!r}, H_SUB), priority=10)"
        for x0, y0, x1, y1 in boxes)
    return f'''# ms_jcross 波导模拟器单元（E∥x 极化前提；互联 JC 缝=带通孔径，Marcuvitz
# 网格 EC 初值口径：主缝 λg/4 + 端枝 λg/8，core/metasurface_lut 单源）
screen = CSX.AddMetal("jc_screen")
{body}
# 上/下全口径集总电阻片（R=η0；下片激励、上片接收，S21=带通透射）
_port1 = LumpedPort(CSX, port_nr=1, R={round(lay["r_port"], 4)!r},
                    start=np.array([-DOM_X, -DOM_Y, {lay["z_feed_lo"]!r}]),
                    stop=np.array([DOM_X, DOM_Y, {lay["z_feed_lo"]!r}]),
                    exc_dir="x", excite=1, priority=5)
_port2 = LumpedPort(CSX, port_nr=2, R={round(lay["r_port"], 4)!r},
                    start=np.array([-DOM_X, -DOM_Y, {lay["z_feed_hi"]!r}]),
                    stop=np.array([DOM_X, DOM_Y, {lay["z_feed_hi"]!r}]),
                    exc_dir="x", excite=0, priority=5)
for _prim in screen.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''

def _fmt_float_list(values: list[float]) -> str:
    return "[" + ", ".join(repr(float(v)) for v in values) + "]"


def ms_array_layout(params: dict[str, Any],
                    freq_range_ghz: tuple[float, float], base_m: float,
                    h_m: float) -> dict[str, Any]:
    """ms_array_NxN 几何/照明/域单源（米制；cell_map 覆盖完备+邻胞间隙守卫）。

    cell_map：n_y 行 × n_x 列的逐单元参数表（每胞 dict：px_mm/py_mm 必填，
    cell_id 可选且仅接受 "ms_patch"）。n_x/n_y 与 cell_map 行列数逐维相等
    （覆盖完备守卫，违反抛 ValueError）。照明=软平面（法向入射 E∥x）；
    阵为有限口径（侧向 MUR，无 PEC/PMC 对壁——那是单胞无限阵技巧）。
    """
    near_m = base_m / float(params.get("_near_ratio", 4) or 4)
    period = float(params.get("period_mm", 14.9896)) * 1e-3
    n_x = int(params.get("n_x", 3))
    n_y = int(params.get("n_y", 3))
    cell_map = params.get("cell_map")
    if (not isinstance(cell_map, list) or len(cell_map) != n_y
            or any(not isinstance(row, list) or len(row) != n_x
                   for row in cell_map)):
        raise ValueError(
            f"ms_array_NxN: cell_map 覆盖不完备（需 {n_y} 行 × {n_x} 列）")
    lam0_m = 299792458.0 / ((freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9)
    cells: list[dict[str, Any]] = []
    min_edge_gap = float("inf")
    min_neighbor_gap = float("inf")
    for j in range(n_y):
        for i in range(n_x):
            cell = cell_map[j][i]
            if not isinstance(cell, dict):
                raise ValueError(
                    f"ms_array_NxN: cell_map[{j}][{i}] 非参数表")
            cid = cell.get("cell_id", "ms_patch")
            if cid != "ms_patch":
                raise ValueError(
                    f"ms_array_NxN: cell_map[{j}][{i}] cell_id={cid!r} "
                    "不在本渲染器单元库（当前=ms_patch）")
            px = float(cell["px_mm"]) * 1e-3
            py = float(cell["py_mm"]) * 1e-3
            if not 0 < px < period or not 0 < py < period:
                raise ValueError(
                    f"ms_array_NxN: cell_map[{j}][{i}] 贴片须在胞内")
            edge = min((period - px) / 2, (period - py) / 2)
            if edge < 2 * near_m:
                raise ValueError(
                    f"ms_array_NxN: cell_map[{j}][{i}] 胞缘缝 "
                    f"{edge * 1e3:.4f}mm < 2·NEAR（#266 族守卫）")
            min_edge_gap = min(min_edge_gap, edge)
            x0 = (i - (n_x - 1) / 2) * period
            y0 = (j - (n_y - 1) / 2) * period
            if i + 1 < n_x:
                nb = period - (px + float(cell_map[j][i + 1]["px_mm"]) * 1e-3) / 2
                min_neighbor_gap = min(min_neighbor_gap, nb)
            if j + 1 < n_y:
                nb = period - (py + float(cell_map[j + 1][i]["py_mm"]) * 1e-3) / 2
                min_neighbor_gap = min(min_neighbor_gap, nb)
            cells.append({"i": i, "j": j, "x": x0, "y": y0,
                          "px": px, "py": py})
    if min_neighbor_gap < 2 * near_m:
        raise ValueError(
            f"ms_array_NxN: 邻胞间隙 {min_neighbor_gap * 1e3:.4f}mm < 2·NEAR"
            f"（criteria §4.2 守卫）")
    side_margin = lam0_m / 4
    dom_x = n_x * period / 2 + side_margin
    dom_y = n_y * period / 2 + side_margin
    z_exc = h_m + lam0_m / 4           # 软平面照明（法向入射，E∥x）
    z_top = z_exc + lam0_m / 8         # 平面上方余量再 MUR
    near_x: list[float] = []
    near_y: list[float] = []
    for c in cells:
        near_x += [c["x"] - c["px"] / 2, c["x"] + c["px"] / 2]
        near_y += [c["y"] - c["py"] / 2, c["y"] + c["py"] / 2]
    return {"n_x": n_x, "n_y": n_y, "period": period, "cells": cells,
            "dom_x": dom_x, "dom_y": dom_y, "z_exc": z_exc, "z_top": z_top,
            "near_x": sorted(set(near_x)), "near_y": sorted(set(near_y)),
            "min_edge_gap_m": min_edge_gap,
            "min_neighbor_gap_m": min_neighbor_gap}


def ms_array_render(template: str, params: dict[str, Any],
                    freq_range_ghz: tuple[float, float],
                    mesh_resolution_mm: float = 0.0,
                    substrate: dict[str, Any] | None = None) -> str:
    """ms_array_NxN 整脚本渲染器（无端口软平面照明 + nf2ff 散射远场）。

    口径（DP-10 §4/J2）：有限 N×N 反射阵；地面=z 底 PEC 边界（地连续由
    边界构造性保证）；贴片零厚在基板顶；上方 λ0/4 空气隙处置软激励平面
    （exc_type=0 全口径，官方 PPW 教程口径；法向入射 E∥x 极化前提），
    平面与阵之间置 nf2ff 盒（反射方向远场，J2 判读面）。
    无端口无 sparams.csv——产物=farfield_cut.csv/farfield3d.csv/
    farfield_meta.json/array_meta.json（观测链 best-effort #105）。
    """
    substrate = substrate or _DEFAULT_SUB
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = max((freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9, 1e6)
    er = float(substrate["er"])
    h_m = float(params.get("h_mm", substrate["h_mm"])) * 1e-3
    tan_d = float(substrate.get("tan_d", 1e-3))
    base_m = (3e8 / ((f0 + fc) * (er ** 0.5)) / 50 if not mesh_resolution_mm
              else float(mesh_resolution_mm) * 1e-3)
    _nrts = int(params.get("_nrts", 100000) or 100000)
    lay = ms_array_layout(params, freq_range_ghz, base_m, h_m)
    near_m = base_m / float(params.get("_near_ratio", 4) or 4)
    cell_boxes = "\n".join(
        f'patch.AddBox(({c["x"] - c["px"] / 2!r}, {c["y"] - c["py"] / 2!r}, '
        f'H_SUB), ({c["x"] + c["px"] / 2!r}, {c["y"] + c["py"] / 2!r}, H_SUB), '
        f'priority=10)' for c in lay["cells"])
    near_x_txt = _fmt_float_list(lay["near_x"])
    near_y_txt = _fmt_float_list(lay["near_y"])
    cell_map_literal = repr(params.get("cell_map"))
    return f'''#!/usr/env/python3
"""openEMS script (rfauto {template} template auto-generated, official-method mesh)."""
import csv
import json
import os

# CSXCAD/openEMS 扩展模块的依赖 DLL 不在 Python 3.8+ 的 PATH 搜索里，
# 必须 add_dll_directory（2026-09-03 审计实测）。
_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN", r"E:\\\\openEMS\\\\install\\\\bin")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}
H_SUB = {h_m!r}
TAND = {tan_d!r}
BASE = {base_m!r}   # 网格 base：λ_sub/50 @F_MAX（官方口径）或显式覆盖
NEAR = {near_m!r}   # 近场区 = base/_near_ratio
DOM_X = {lay["dom_x"]!r}
DOM_Y = {lay["dom_y"]!r}
Z_EXC = {lay["z_exc"]!r}   # 软平面照明面（λ0/4 空气隙上）
Z_TOP = {lay["z_top"]!r}
N_X = {lay["n_x"]}
N_Y = {lay["n_y"]}

CSX = ContinuousStructure()
FDTD = openEMS(NrTS={_nrts!r})   # 官方口径：不设 EndCriteria，能量判据停机
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 有限阵：侧/顶 MUR 吸收；z 底 PEC=反射阵地板（地连续由边界构造性保证）
FDTD.SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "PEC", "MUR"])

mesh = CSX.GetGrid()
# 贴片缘精确入网（#198）+ 胞缘缝内部线（#311 口径），全轴 BASE 平滑
for _x in {near_x_txt}:
    mesh.AddLine("x", _x)
for _y in {near_y_txt}:
    mesh.AddLine("y", _y)
mesh.AddLine("x", np.array([-DOM_X, DOM_X]))
mesh.AddLine("y", np.array([-DOM_Y, DOM_Y]))
mesh.AddLine("z", np.linspace(0, H_SUB, 5))
mesh.AddLine("z", np.array([Z_EXC, Z_TOP]))
mesh.SmoothMeshLines("x", NEAR)
mesh.SmoothMeshLines("y", NEAR)
mesh.SmoothMeshLines("z", BASE)
# 近重合网格线守卫（#152）：平滑后按最小间距 1µm 去重
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((-DOM_X, -DOM_Y, 0), (DOM_X, DOM_Y, H_SUB), priority=0)
patch = CSX.AddMetal("patches")
{cell_boxes}
for _prim in patch.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)

# ── 软平面照明（法向入射 E∥x；exc_type=0 官方 PPW 教程口径）──
# E∥x 极化前提（y 极化需改 exc_val 向量）；软源双向发射：向下照明阵列，
# 向上穿 nf2ff 盒顶后被 MUR 吸收（盒在照明面下方，不测照明面直射场）。
_exc = CSX.AddExcitation("inc_plane", exc_type=0,
                         exc_val=np.array([1.0, 0.0, 0.0]))
_exc.AddBox((-DOM_X, -DOM_Y, Z_EXC), (DOM_X, DOM_Y, Z_EXC), priority=0)

# ── nf2ff 盒（官方教程口径：域缩 4×网格；阵与照明面之间）──
_FF_MARGIN = 4 * BASE
_FF = FDTD.CreateNF2FFBox(
    "nf2ff",
    np.array([-DOM_X + _FF_MARGIN, -DOM_Y + _FF_MARGIN, H_SUB + _FF_MARGIN]),
    np.array([DOM_X - _FF_MARGIN, DOM_Y - _FF_MARGIN, Z_EXC - _FF_MARGIN]))

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
FDTD.Run(os.path.join(_THIS_DIR, "fdtd"), verbose=0, cleanup=True)

# ── 远场计算 + 阵 meta 落盘（best-effort，#105：失败不阻塞进程）──
try:
    _f_res = float(F0)
    _THETA_CUT = np.arange(-90.0, 91.0, 1.0)
    _PHI_CUT = [0.0, 90.0]
    _ffr = _FF.CalcNF2FF(os.path.join(_THIS_DIR, "fdtd"), _f_res,
                         _THETA_CUT, _PHI_CUT)
    _Dmax = float(np.atleast_1d(_ffr.Dmax)[0])
    _meta = {{
        "ok": True, "template": {template!r},
        "n_x": N_X, "n_y": N_Y,
        "period_mm": {lay["period"] * 1e3!r},
        "cell_map": {cell_map_literal},
        "f0_ghz": F0 / 1e9,
        "dmax_linear": _Dmax,
        "dmax_dbi": 10.0 * np.log10(max(_Dmax, 1e-300)),
        "polarization": "E parallel x (normal incidence)",
        "farfield_semantics": "total outgoing field (specular + shaped beam)"
    }}
    with open(os.path.join(_THIS_DIR, "array_meta.json"), "w",
              encoding="utf-8") as _mh:
        json.dump(_meta, _mh, ensure_ascii=False, indent=1)
    print("rfauto ms_array farfield done: Dmax =", _Dmax)
except Exception as _ffe:
    try:
        with open(os.path.join(_THIS_DIR, "array_meta.json"), "w",
                  encoding="utf-8") as _mh:
            json.dump({{"ok": False, "error": str(_ffe)}}, _mh,
                      ensure_ascii=False)
    except Exception:
        pass
    print("rfauto ms_array farfield 链失败（不阻塞）:", _ffe)
print("rfauto openEMS simulation done")
'''


def ms_geometry_spec(template: str, params: dict[str, Any],
                     substrate: dict[str, Any]) -> dict[str, Any]:
    """MS 族 geometry_spec（UI 3D 预览，mm；early-dispatch 自 geometry_spec）。

    审计契约消费点：test_meta_yaml_identity 校验 spec_ports 数 == meta
    n_ports；test_nominal_params_cover_geometry_inputs 只要求不抛错。
    ms_array_NxN 无端口（ports=[]，n_ports=0 口径）。
    """
    if template in MS_UNIT_TEMPLATES:
        band = (9.75, 10.25)
        base_m = 0.4e-3  # 审计档 base（UI 预览不需真网格）
        h_m = float(params.get("h_mm", substrate["h_mm"])) * 1e-3
        lay = ms_unit_layout(template, params, band, base_m, h_m)
        period_mm = lay["period"] * 1e3
        z_feed_mm = {k: lay[k] * 1e3 for k in ("z_feed", "z_feed_lo",
                                               "z_feed_hi") if k in lay}
        if template == "ms_patch":
            boxes = [
                {"name": "substrate", "material": "substrate",
                 "start_mm": [-period_mm / 2, -period_mm / 2, 0.0],
                 "stop_mm": [period_mm / 2, period_mm / 2, h_m * 1e3]},
                {"name": "patch", "material": "metal",
                 "start_mm": [-lay["px"] * 1e3 / 2, -lay["py"] * 1e3 / 2,
                              h_m * 1e3],
                 "stop_mm": [lay["px"] * 1e3 / 2, lay["py"] * 1e3 / 2, h_m * 1e3]},
                {"name": "feed_sheet（全口径集总片端口）", "material": "metal",
                 "start_mm": [-period_mm / 2, -period_mm / 2,
                              z_feed_mm["z_feed"]],
                 "stop_mm": [period_mm / 2, period_mm / 2, z_feed_mm["z_feed"]]},
            ]
            ports = [{"name": "Port1（TEM 片端口 R=η0）",
                      "pos_mm": [0.0, 0.0, z_feed_mm["z_feed"]],
                      "dir": [1.0, 0.0, 0.0]}]
        elif template == "ms_cross":
            arm_mm = lay["arm"] * 1e3
            arm_w_mm = lay["arm_w"] * 1e3
            boxes = [
                {"name": "substrate", "material": "substrate",
                 "start_mm": [-period_mm / 2, -period_mm / 2, 0.0],
                 "stop_mm": [period_mm / 2, period_mm / 2, h_m * 1e3]},
                {"name": "cross_x", "material": "metal",
                 "start_mm": [-arm_mm, -arm_w_mm / 2, h_m * 1e3],
                 "stop_mm": [arm_mm, arm_w_mm / 2, h_m * 1e3]},
                {"name": "cross_y", "material": "metal",
                 "start_mm": [-arm_w_mm / 2, -arm_mm, h_m * 1e3],
                 "stop_mm": [arm_w_mm / 2, arm_mm, h_m * 1e3]},
                {"name": "feed_sheet_lo", "material": "metal",
                 "start_mm": [-period_mm / 2, -period_mm / 2,
                              z_feed_mm["z_feed_lo"]],
                 "stop_mm": [period_mm / 2, period_mm / 2,
                             z_feed_mm["z_feed_lo"]]},
                {"name": "feed_sheet_hi", "material": "metal",
                 "start_mm": [-period_mm / 2, -period_mm / 2,
                              z_feed_mm["z_feed_hi"]],
                 "stop_mm": [period_mm / 2, period_mm / 2,
                             z_feed_mm["z_feed_hi"]]},
            ]
            ports = [
                {"name": "Port1（TEM 片端口 R=η0，馈）",
                 "pos_mm": [0.0, 0.0, z_feed_mm["z_feed_lo"]],
                 "dir": [1.0, 0.0, 0.0]},
                {"name": "Port2（TEM 片端口 R=η0，收）",
                 "pos_mm": [0.0, 0.0, z_feed_mm["z_feed_hi"]],
                 "dir": [1.0, 0.0, 0.0]},
            ]
        else:  # ms_jcross
            boxes = [
                {"name": "substrate", "material": "substrate",
                 "start_mm": [-period_mm / 2, -period_mm / 2, 0.0],
                 "stop_mm": [period_mm / 2, period_mm / 2, h_m * 1e3]},
                {"name": "jc_screen（JC 缝屏，孔洞补集盒）", "material": "metal",
                 "start_mm": [-period_mm / 2, -period_mm / 2, h_m * 1e3],
                 "stop_mm": [period_mm / 2, period_mm / 2, h_m * 1e3]},
                {"name": "feed_sheet_lo", "material": "metal",
                 "start_mm": [-period_mm / 2, -period_mm / 2,
                              z_feed_mm["z_feed_lo"]],
                 "stop_mm": [period_mm / 2, period_mm / 2,
                             z_feed_mm["z_feed_lo"]]},
                {"name": "feed_sheet_hi", "material": "metal",
                 "start_mm": [-period_mm / 2, -period_mm / 2,
                              z_feed_mm["z_feed_hi"]],
                 "stop_mm": [period_mm / 2, period_mm / 2,
                             z_feed_mm["z_feed_hi"]]},
            ]
            ports = [
                {"name": "Port1（TEM 片端口 R=η0，馈）",
                 "pos_mm": [0.0, 0.0, z_feed_mm["z_feed_lo"]],
                 "dir": [1.0, 0.0, 0.0]},
                {"name": "Port2（TEM 片端口 R=η0，收）",
                 "pos_mm": [0.0, 0.0, z_feed_mm["z_feed_hi"]],
                 "dir": [1.0, 0.0, 0.0]},
            ]
        return {"template": template, "substrate": substrate, "boxes": boxes,
                "ports": ports, "elements": []}
    if template == "ms_array_NxN":
        h_m = float(params.get("h_mm", substrate["h_mm"])) * 1e-3
        lay = ms_array_layout(params, (9.75, 10.25), 0.4e-3, h_m)
        n_mm_x = lay["n_x"] * lay["period"] * 1e3
        n_mm_y = lay["n_y"] * lay["period"] * 1e3
        boxes = [
            {"name": "substrate", "material": "substrate",
             "start_mm": [-n_mm_x / 2, -n_mm_y / 2, 0.0],
             "stop_mm": [n_mm_x / 2, n_mm_y / 2, h_m * 1e3]},
            {"name": "patches（cell_map 逐单元）", "material": "metal",
             "start_mm": [-n_mm_x / 2, -n_mm_y / 2, h_m * 1e3],
             "stop_mm": [n_mm_x / 2, n_mm_y / 2, h_m * 1e3]},
            {"name": "excitation_plane（软平面照明）", "material": "metal",
             "start_mm": [-n_mm_x / 2, -n_mm_y / 2, lay["z_exc"] * 1e3],
             "stop_mm": [n_mm_x / 2, n_mm_y / 2, lay["z_exc"] * 1e3]},
        ]
        return {"template": template, "substrate": substrate, "boxes": boxes,
                "ports": [], "elements": []}
    raise ValueError(f"ms_geometry_spec: 未知模板 {template!r}")


# ─── §MS_METASURFACE 注册（TEMPLATE_META/TEMPLATE_NOMINAL 文末注册块，#304 口径）
# 名义尺寸闭式（#252 禁抄毫米数；core/metasurface_lut 单源，互证钉在
# test_metasurface_templates.py；src 侧 nominal=导入期闭式计算非手抄）：
# - ms_patch：period=λ0/2=15.0（0.5λ0 口径）；px=py=方贴片谐振边长
#   λ0/(2√εeff(w)) 不动点（Hammerstad εeff，er=3.66/h=1.524）；
#   h=1.524（60mil 板材数据，X 波段反射阵常用厚度→相位覆盖宽）。
# - ms_cross：period=0.4λ0=12.0；臂长=总跨/2=λ0/(4√εeff)、
#   εeff=(1+εr)/2 单侧基板加载（Luukkonen eq.3 口径）；臂宽=总跨/10。
# - ms_jcross：period=12.0；主缝=λg/4、端枝=λg/8、缝宽=λg/40
#   （λg=λ0/√εeff；Marcuvitz 网格 EC 初值口径，带心真机修正归 P3）。
# - ms_array_NxN：演示名义务 3×3（真机 15×15 战役走参数注入，预算见
#   handoff.md）；cell_map=三值 px 图样证明逐单元驱动（cell_id 显式）。
def _ms_nominal() -> tuple[float, float, float]:
    """闭式 nominal 计算（core 单源导入收口在函数内，scipy 链惰性）。"""
    from rfauto.core.metasurface_lut import ms_cross_arm_len_mm, ms_jcross_slot_dims_mm, ms_patch_resonant_len_mm

    px = round(ms_patch_resonant_len_mm(10.0, 3.66, 1.524), 4)
    arm = round(ms_cross_arm_len_mm(10.0, 3.66), 4)
    jc = ms_jcross_slot_dims_mm(10.0, 3.66)
    return px, arm, round(jc["stub_len_mm"], 4)


_MS_PATCH_NOM_PX, _MS_CROSS_NOM_ARM, _MS_JCROSS_NOM_STUB = _ms_nominal()
_MS_LAM0_MM = 299792458.0 / 10e9 * 1e3
_MS_EPS_EFF_SCREEN = (1.0 + 3.66) / 2.0
_MS_LAMG_MM = _MS_LAM0_MM / (_MS_EPS_EFF_SCREEN ** 0.5)

MS_PATCH_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 1,
    "extraction": "S11 @ 全口径集总片端口 1（R=η0·a/b 方胞=η0，CalcPort 同参考；"
                  "波导模拟器 PEC/PMC 对壁方波导≡无限阵@θ=0，E∥x 极化前提；"
                  "|S11|≈1 的 argΓ 逐 px 入反射相位 LUT；相位含片-胞距离常数项，"
                  "扫 px 差分或地面基准 run 校准）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["px_mm", "py_mm", "period_mm", "h_mm"],
    "topology": "反射阵方贴片单元：接地基板（z 底 PEC 边界）+ 零厚方贴片；单胞方形"
                "域 x 对壁 PEC / y 对壁 PMC（TEM 平面波）；全口径集总电阻片馈于"
                "贴片上方 λ0/4",
    "param_semantics": "px_mm=E 向（x）谐振边长（LUT 扫描变量），py_mm=非谐振宽（y），"
                       "period_mm=单胞周期（方形域边长），h_mm=基板厚；er/tan_d 走 "
                       "substrate/nominal（材料属性不改导体）",
    "mesh_note": "0=自动 λ_sub/50@F_MAX；贴片缘精确入网+胞缘缝 3+ 中点入网（#311）；"
                 "NEAR≤最小胞缘缝/3 渲染期守卫（#266）；全轴 ≥10µm",
    "smoke_note": "离线审计先行（#212，test_metasurface_templates）；波导模拟器扫"
                  "描战役（粗 21+细 41 点）发射面见 runs/df6_dp10ms/handoff.md",
}
_MS_PATCH_NOM_PERIOD = round(_MS_LAM0_MM / 2, 4)   # λ0/2（#252 闭式非手抄）
MS_PATCH_NOMINAL: dict[str, Any] = {
    "px_mm": _MS_PATCH_NOM_PX, "py_mm": _MS_PATCH_NOM_PX,
    "period_mm": _MS_PATCH_NOM_PERIOD, "h_mm": 1.524,
    "er": 3.66, "tan_d": 0.0037,
}

MS_CROSS_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 2,
    "extraction": "S11/S21 @ 全口径集总片端口 1-2（R=η0，CalcPort 同参考；波导"
                  "模拟器≡无限阵@θ=0，E∥x 极化前提；S21 谷=带阻谐振；J3 vs "
                  "PSSFSS Δf≤0.3GHz 或 ≤5% 真机轨判）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["arm_len_mm", "arm_w_mm", "period_mm", "h_mm"],
    "topology": "FSS 带阻十字偶极子单元：基板顶零厚正交双十字臂（x 臂=受激臂，"
                "y 臂=正交极化对偶臂）；单胞 PEC/PMC 对壁域；屏两侧 λ0/4 空气"
                "区各置全口径电阻片（下馈上收）",
    "param_semantics": "arm_len_mm=臂长（中心→尖端，总跨=2·arm 半波谐振），"
                       "arm_w_mm=臂宽，period_mm=单胞周期，h_mm=基板厚；"
                       "er/tan_d 走 substrate/nominal",
    "mesh_note": "0=自动 λ_sub/50@F_MAX；臂缘精确入网+邻臂尖缝 3+ 中点入网；"
                 "NEAR≤邻臂尖缝/3 渲染期守卫；全轴 ≥10µm",
    "smoke_note": "离线审计先行（#212）；带阻谐振闭式互证（λ0/2√εeff 口径）",
}
MS_CROSS_NOMINAL: dict[str, Any] = {
    "arm_len_mm": _MS_CROSS_NOM_ARM,
    "arm_w_mm": round(_MS_CROSS_NOM_ARM / 5, 4),  # 臂宽=臂长/5（=总跨/10 闭式）
    "period_mm": round(0.4 * _MS_LAM0_MM, 4),     # 0.4λ0（无光栅瓣口径闭式）
    "h_mm": 0.508,
    "er": 3.66, "tan_d": 0.0037,
}

MS_JCROSS_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 2,
    "extraction": "S11/S21 @ 全口径集总片端口 1-2（R=η0，CalcPort 同参考；波导"
                  "模拟器≡无限阵@θ=0，E∥x 极化前提；S21 峰=带通（JC 缝互联孔径"
                  "谐振）；J3 vs PSSFSS Δf≤0.3GHz 或 ≤5% 真机轨判）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["slot_len_mm", "slot_w_mm", "stub_len_mm", "period_mm", "h_mm"],
    "topology": "FSS 带通 Jerusalem cross 缝单元：零厚金属屏（胞面减互联孔径盒"
                "分解）+ 主缝端 4 枝端加载；单胞 PEC/PMC 对壁域；屏两侧 λ0/4 "
                "空气区各置全口径电阻片（下馈上收）",
    "param_semantics": "slot_len_mm=主缝全长（x 向），slot_w_mm=缝宽（主缝与端枝"
                       "同宽），stub_len_mm=端枝长（±y 向，与主缝共边互联），"
                       "period_mm=单胞周期，h_mm=基板厚；er/tan_d 走 "
                       "substrate/nominal",
    "mesh_note": "0=自动 λ_sub/50@F_MAX；缝缘精确入网+屏缘缝 3+ 中点入网；"
                 "NEAR≤最小屏缝/3 渲染期守卫；孔径盒逐面入网（#174）；全轴 ≥10µm",
    "smoke_note": "离线审计先行（#212）；EC 自洽钉（shunt 并联 LC 峰=f0）在 "
                  "test_metasurface_lut；真机带心修正（openEMS LUT 一轮）归 P3",
}
MS_JCROSS_NOMINAL: dict[str, Any] = {
    "slot_len_mm": round(_MS_LAMG_MM / 4, 4),
    "slot_w_mm": round(_MS_LAMG_MM / 40, 4),
    "stub_len_mm": _MS_JCROSS_NOM_STUB,
    "period_mm": round(0.4 * _MS_LAM0_MM, 4),     # 0.4λ0（同 ms_cross 口径）
    "h_mm": 0.508,
    "er": 3.66, "tan_d": 0.0037,
}

_MS_ARRAY_CELL_MAP = [
    [{"cell_id": "ms_patch", "px_mm": 6.0, "py_mm": 6.0},
     {"cell_id": "ms_patch", "px_mm": 7.5, "py_mm": 7.5},
     {"cell_id": "ms_patch", "px_mm": 9.0, "py_mm": 9.0}],
    [{"cell_id": "ms_patch", "px_mm": 7.5, "py_mm": 7.5},
     {"cell_id": "ms_patch", "px_mm": 9.0, "py_mm": 9.0},
     {"cell_id": "ms_patch", "px_mm": 6.0, "py_mm": 6.0}],
    [{"cell_id": "ms_patch", "px_mm": 9.0, "py_mm": 9.0},
     {"cell_id": "ms_patch", "px_mm": 6.0, "py_mm": 6.0},
     {"cell_id": "ms_patch", "px_mm": 7.5, "py_mm": 7.5}],
]

MS_ARRAY_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 0,
    "extraction": "无端口（软平面照明散射体）：产物=farfield_cut.csv/"
                  "farfield3d.csv/farfield_meta.json/array_meta.json；"
                  "J2 峰值方向 vs 闭式 φ_mn 指向 ≤3°（真机轨）；farfield=总出射"
                  "场（镜面反射+赋形波束，判读面在 J2 分解）",
    "max_time_ns": 60.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["n_x", "n_y", "period_mm", "cell_map", "h_mm"],
    "topology": "有限 N×N 反射阵（ms_patch 单元平铺）：接地基板（z 底 PEC 边界）"
                "+ cell_map 逐单元贴片表；上方 λ0/4 空气隙软激励平面照明；"
                "侧向 MUR（有限口径，无 PEC/PMC 对壁——那是单胞无限阵技巧）",
    "param_semantics": "n_x/n_y=x/y 向胞数，period_mm=胞周期，cell_map=n_y 行 ×"
                       " n_x 列逐单元参数表（每胞 px_mm/py_mm/cell_id），"
                       "h_mm=基板厚；n 与 cell_map 行列数逐维相等（覆盖完备守卫）；"
                       "er/tan_d 走 substrate/nominal",
    "mesh_note": "0=自动 λ_sub/50@F_MAX；全部贴片缘精确入网；胞缘/邻胞缝 ≥2·NEAR"
                 " 渲染期守卫；1µm 近重合去重（#152）；全轴 ≥10µm；演示名义 3×3，"
                 "真机 15×15 预算（~4×10⁷ cells 小时级/轮，#328 CSXCAD exec 实测"
                 "口径）见 runs/df6_dp10ms/handoff.md",
    "smoke_note": "离线审计先行（#212）；真机 solo 单飞（#246/#261）",
}
MS_ARRAY_NOMINAL: dict[str, Any] = {
    "n_x": 3, "n_y": 3, "period_mm": _MS_PATCH_NOM_PERIOD,
    "cell_map": _MS_ARRAY_CELL_MAP,
    "h_mm": 1.524,
    "er": 3.66, "tan_d": 0.0037,
}

TEMPLATE_META["ms_patch"] = MS_PATCH_META
TEMPLATE_NOMINAL["ms_patch"] = MS_PATCH_NOMINAL
TEMPLATE_META["ms_cross"] = MS_CROSS_META
TEMPLATE_NOMINAL["ms_cross"] = MS_CROSS_NOMINAL
TEMPLATE_META["ms_jcross"] = MS_JCROSS_META
TEMPLATE_NOMINAL["ms_jcross"] = MS_JCROSS_NOMINAL
TEMPLATE_META["ms_array_NxN"] = MS_ARRAY_META
TEMPLATE_NOMINAL["ms_array_NxN"] = MS_ARRAY_NOMINAL


# ─── §COIL_NFC NFC/WPC 线圈族（2026-09-26 df7 C10b，文末注册块，#304 口径）─────
# 单端口方螺旋线圈（13.56MHz NFC 频段）：FR4 类基板 + 阶梯方螺旋 + 中跳线桥
# （lange air-bridge 同法：抬高 z 越过下层走线）+ 外圈馈隙 LumpedPort 单端口
# （slotline_lumped 跨隙集总馈同源口径）。名义尺寸全闭式精算（#1c/#252）：
# L_target = 1/((2π·f0)²·C_tune)（f0=13.56MHz、C_tune=47pF 标准 NP0 档）→
# core/nfc_coil.synthesize_coil 二分反解 d_out（导入期计算非手抄）。
# 真机面：13.56MHz 全波 FDTD 预算 ~小时-天/点（MQS 频段无 MQS 求解器，
# 见 runs/df7_nfc/criteria.md §e），本批仅离线审计不发射。
def _coil_nfc_nominal_dout() -> float:
    """名义外径闭式合成（mm，导入期；core 单源，零手抄毫米数）。"""
    import math

    from rfauto.core.nfc_coil import synthesize_coil

    l_target = 1.0 / ((2.0 * math.pi * 13.56e6) ** 2 * 47e-12)
    result = synthesize_coil(l_target, "square", 7, 0.5e-3, 0.5e-3)
    return round(float(result["d_out_m"]) * 1e3, 4)


COIL_NFC_TEMPLATES: frozenset[str] = frozenset({"coil_nfc"})
_COIL_NFC_D_OUT_MM = _coil_nfc_nominal_dout()

COIL_NFC_META: dict[str, Any] = {
    "f0_ghz": 0.01356, "n_ports": 1,
    "extraction": "S11 @ LumpedPort 1（外圈馈隙桥接，R=50Ω CalcPort 同参考；"
                  "f0 谷=串联谐振 1/(2π√(L_self·C_tune))，C_tune=外匹配电容"
                  "不进几何，fake 同源 47pF 口径）",
    "max_time_ns": 60.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["n_turns", "d_out_mm", "w_mm", "s_mm", "gap_mm", "h_mm"],
    "topology": "NFC/WPC 平面线圈：FR4 类基板（无地平面）+ 阶梯方螺旋（外圈"
                "馈隙=端口位）+ 中跳线桥（抬高 z 越过螺旋，lange air-bridge "
                "同法）把内端引出到外端端口对侧——单导体通路，端口跨馈隙；"
                "全域 MUR（无地，辐射口径；13.56MHz 电小，近场主导）",
    "param_semantics": "n_turns=匝数（渲染取整），d_out_mm=外圈外缘宽（跨面宽"
                       "口径），w_mm=线宽，s_mm=匝间距，gap_mm=外圈馈隙长"
                       "（端口 y 向跨距），h_mm=基板厚；er/tan_d 走 "
                       "substrate/nominal（FR4 类）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖；0=自动 max(w,s,gap)/4"
                 "（MQS 频段几何驱动网格，禁 λ_sub/50 口径——13.56MHz 下"
                 "λ_sub/50≈250mm 装不下线圈）；螺旋缘/馈隙缘/桥面/过孔棱精确"
                 "入网（#198）；NEAR≤min(s,gap)/3 渲染期守卫（#266）；全轴"
                 "1µm 近重合去重（#152）；端口盒三向 ≥NEAR 厚、边全入网"
                 "（#174/#283）",
    "smoke_note": "未冒烟（离线审计过，#212，test_coil_nfc_template）；真机"
                  "发射面=13.56MHz FDTD 预算审计（runs/df7_nfc/criteria.md "
                  "§e：小时-天/点量级，建议几何等比缩放阶梯研究后由主代理"
                  "决定），本批零发射",
}
COIL_NFC_NOMINAL: dict[str, Any] = {
    "n_turns": 7,
    "d_out_mm": _COIL_NFC_D_OUT_MM,   # 导入期闭式合成（§块头注释）
    "w_mm": 0.5, "s_mm": 0.5, "gap_mm": 0.4,
    "h_mm": 1.6, "er": 4.4, "tan_d": 0.02,   # FR4 类板材
}

TEMPLATE_META["coil_nfc"] = COIL_NFC_META
TEMPLATE_NOMINAL["coil_nfc"] = COIL_NFC_NOMINAL


def _coil_nfc_layout(params: dict[str, Any],
                     freq_range_ghz: tuple[float, float],
                     mesh_resolution_mm: float = 0.0) -> dict[str, Any]:
    """coil_nfc 几何/端口/域单源（米）。

    几何拓扑（全部 z=H_SUB 顶层金属除桥/过孔）：
    - 阶梯方螺旋：turn k 中心线半宽 A_k=A_0−k·p（p=w+s），A_0=d_out/2−w/2；
      换匝过渡=内圈右边缘 p 长尾（R_k 自 y=−A_{k−1} 起）；最内圈底边止于
      x=0（内端）；
    - 中跳线桥：内端 (0,−A_{n−1}) 过孔上引 z=H+h_b，沿 −y 越过全部底边，
      再沿 +x 至 (A_0,y_pad)，过孔下引落 pad；
    - 馈隙端口：pad 顶缘 ↔ R_0 底端，y 向跨距=gap_mm（LumpedPort 盒
      x=w/z=NEAR 厚，跨 z=H 金属面对称）。
    """
    import math

    n = int(float(params.get("n_turns", COIL_NFC_NOMINAL["n_turns"])))
    if n < 1:
        raise ValueError(f"coil_nfc: n_turns 须 ≥1，收到 {n}")
    d_out = float(params.get("d_out_mm", COIL_NFC_NOMINAL["d_out_mm"])) * 1e-3
    w = float(params.get("w_mm", COIL_NFC_NOMINAL["w_mm"])) * 1e-3
    s = float(params.get("s_mm", COIL_NFC_NOMINAL["s_mm"])) * 1e-3
    gap = float(params.get("gap_mm", COIL_NFC_NOMINAL["gap_mm"])) * 1e-3
    h = float(params.get("h_mm", COIL_NFC_NOMINAL["h_mm"])) * 1e-3
    for name, v in (("d_out_mm", d_out), ("w_mm", w), ("s_mm", s),
                    ("gap_mm", gap), ("h_mm", h)):
        if not (math.isfinite(v) and v > 0):
            raise ValueError(f"coil_nfc: {name} 必须为正有限，得到 {v!r}")
    a0 = d_out / 2.0 - w / 2.0
    pitch = w + s
    a_min = a0 - (n - 1) * pitch
    if a_min <= 2.0 * w:
        raise ValueError(
            f"coil_nfc: 几何不可行（内圈半宽 {a_min * 1e3:.4g}mm ≤ 2w，"
            "减小 n_turns 或线宽/间距）")
    # 网格：显式覆盖优先；自动档=几何驱动（MQS 频段禁 λ 口径，meta mesh_note）
    base = (max(w, s, gap) / 4.0 if not mesh_resolution_mm
            else float(mesh_resolution_mm) * 1e-3)
    near = base / 4.0
    if near > min(s, gap) / 3.0:
        raise ValueError(
            f"coil_nfc: NEAR={near * 1e3:.4g}mm > min(s,gap)/3="
            f"{min(s, gap) / 3.0 * 1e3:.4g}mm（#266 耦合缝守卫，收紧 "
            "mesh_resolution_mm）")
    h_bridge = max(2.0 * near, base)   # 桥高（≥base，桥面独立 z 网格层）
    y_pad = -(a0 + w + gap)            # pad 中心线 y（桥落点/端口下缘）
    # 螺旋中心线段（z=H）：设计口径见 docstring
    segs: list[tuple[float, float, float, float]] = []
    for k in range(n):
        a_k = a0 - k * pitch
        if k == 0:
            segs.append((a0, -a0, a0, a0))            # R0：外端自馈隙上引
        else:
            segs.append((a_k, -(a0 - (k - 1) * pitch), a_k, a_k))  # Rk 带尾
        segs.append((a_k, a_k, -a_k, a_k))            # T_k
        segs.append((-a_k, a_k, -a_k, -a_k))          # L_k
        if k < n - 1:
            segs.append((-a_k, -a_k, a0 - (k + 1) * pitch, -a_k))  # B_k
        else:
            segs.append((-a_k, -a_k, 0.0, -a_k))      # B_{n-1} 止于内端
    via_up = (0.0, -a_min)
    via_down = (a0, y_pad)
    bridge_segs = [(0.0, -a_min, 0.0, y_pad), (0.0, y_pad, a0, y_pad)]
    dom_x = a0 + w / 2.0 + 2.0e-3
    dom_y = max(a0 + w / 2.0, -(y_pad - w / 2.0)) + 2.0e-3
    port_box = (a0 - w / 2.0, y_pad + w / 2.0, a0 + w / 2.0,
                -a0 - w / 2.0)   # x0,y0,x1,y1（y_pad+w/2 < −a0−w/2）
    if port_box[1] >= port_box[3] - 1e-12:
        raise ValueError("coil_nfc: 馈隙端口 y 跨距非正（gap_mm 过小）")
    return {
        "n": n, "d_out": d_out, "w": w, "s": s, "gap": gap, "h": h,
        "a0": a0, "pitch": pitch, "a_min": a_min,
        "base": base, "near": near, "h_bridge": h_bridge,
        "y_pad": y_pad, "segs": segs, "bridge_segs": bridge_segs,
        "via_up": via_up, "via_down": via_down,
        "port_box": port_box, "dom_x": dom_x, "dom_y": dom_y,
    }


def _coil_nfc_seg_box(x0: float, y0: float, x1: float, y1: float,
                      w: float, z: float) -> tuple[float, float, float,
                                                    float, float, float]:
    """中心线段（轴对齐）→ 金属薄盒 (x0,y0,z0,x1,y1,z1)，横向加宽 w/2。"""
    if abs(y0 - y1) <= 1e-15:      # 水平段
        return (min(x0, x1), y0 - w / 2.0, z,
                max(x0, x1), y0 + w / 2.0, z)
    return (x0 - w / 2.0, min(y0, y1), z,
            x0 + w / 2.0, max(y0, y1), z)


def coil_nfc_geometry_spec(params: dict[str, Any],
                           substrate: dict[str, Any]) -> dict[str, Any]:
    """coil_nfc UI 预览 spec（mm；early-dispatch 自 geometry_spec）。"""
    lay = _coil_nfc_layout(params, (0.01356, 0.01356))

    def to_mm(v: float) -> float:
        return v * 1e3
    boxes = [
        {"name": "substrate", "material": "substrate",
         "start_mm": [-to_mm(lay["dom_x"]), -to_mm(lay["dom_y"]), 0.0],
         "stop_mm": [to_mm(lay["dom_x"]), to_mm(lay["dom_y"]),
                     to_mm(lay["h"])]},
        {"name": "spiral（阶梯方螺旋）", "material": "metal",
         "start_mm": [-to_mm(lay["a0"] + lay["w"] / 2.0),
                      -to_mm(lay["a0"] + lay["w"] / 2.0), to_mm(lay["h"])],
         "stop_mm": [to_mm(lay["a0"] + lay["w"] / 2.0),
                     to_mm(lay["a0"] + lay["w"] / 2.0), to_mm(lay["h"])]},
        {"name": "bridge（中跳线桥）", "material": "metal",
         "start_mm": [-to_mm(lay["w"] / 2.0), to_mm(lay["y_pad"]),
                      to_mm(lay["h"] + lay["h_bridge"])],
         "stop_mm": [to_mm(lay["w"] / 2.0), to_mm(-lay["a_min"]),
                     to_mm(lay["h"] + lay["h_bridge"])]},
    ]
    ports = [{"name": "Port1（馈隙 LumpedPort，R=50Ω）",
              "pos_mm": [to_mm(lay["a0"]),
                         to_mm((lay["port_box"][1] + lay["port_box"][3]) / 2),
                         to_mm(lay["h"])],
              "dir": [0.0, 1.0, 0.0]}]
    sub_view = dict(substrate)
    sub_view.update({"er": COIL_NFC_NOMINAL["er"],
                     "h_mm": COIL_NFC_NOMINAL["h_mm"],
                     "tan_d": COIL_NFC_NOMINAL["tan_d"]})
    return {"template": "coil_nfc", "substrate": sub_view,
            "boxes": boxes, "ports": ports, "elements": []}


def coil_nfc_render(template: str, params: dict[str, Any],
                    freq_range_ghz: tuple[float, float],
                    mesh_resolution_mm: float = 0.0,
                    substrate: dict[str, Any] | None = None,
                    excite_port: int = 1) -> str:
    """coil_nfc 整脚本渲染器（早分发自 render_script；slotline 族同款结构）。

    单端口（LumpedPort 跨外圈馈隙）：S11=串联谐振谷口径（f0 谷，fake 同
    源 1/(2π√(LC)) 判读）；域全 MUR；_nrts 旋钮缺省逐字节不变。
    er/tan_d/h 从 params/NOMINAL 消费（模板自带 FR4 类板材；render_script
    顶层会把缺省 substrate 重绑为 RO4350B——本族不用全局缺省板材，
    ms 族「er/tan_d 走 substrate/nominal」同口径）。
    """
    er = float(params.get("er", COIL_NFC_NOMINAL["er"]))
    tan_d = float(params.get("tan_d", COIL_NFC_NOMINAL["tan_d"]))
    lay = _coil_nfc_layout(params, freq_range_ghz, mesh_resolution_mm)
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = abs(freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9
    nrts = int(params.get("_nrts", 100000) or 100000)
    # 特征线收集（全部盒的边 + 端口盒边 + 桥/过孔棱；#198 精确入网）
    trace_boxes = [_coil_nfc_seg_box(*s, lay["w"], lay["h"])
                   for s in lay["segs"]]
    bridge_boxes = [_coil_nfc_seg_box(*s, lay["w"],
                                      lay["h"] + lay["h_bridge"])
                    for s in lay["bridge_segs"]]
    w2 = lay["w"] / 2.0
    via_u = (lay["via_up"][0] - w2, lay["via_up"][1] - w2, lay["h"],
             lay["via_up"][0] + w2, lay["via_up"][1] + w2,
             lay["h"] + lay["h_bridge"])
    via_d = (lay["via_down"][0] - w2, lay["via_down"][1] - w2, lay["h"],
             lay["via_down"][0] + w2, lay["via_down"][1] + w2,
             lay["h"] + lay["h_bridge"])
    pad = (lay["a0"] - w2, lay["y_pad"] - w2, lay["a0"] + w2,
           lay["y_pad"] + w2, lay["h"])
    px0, py0, px1, py1 = lay["port_box"]
    metal_boxes = trace_boxes + bridge_boxes + [via_u, via_d]
    xs: list[float] = []
    ys: list[float] = []
    for b in metal_boxes:
        xs += [b[0], b[3]]
        ys += [b[1], b[4]]
    xs += [px0, px1, 0.0]                       # 端口盒 x 边 + 桥中线
    ys += [py0, py1, (py0 + py1) / 2.0]         # 端口盒 y 边 + 馈隙中线（#283）
    zs = [lay["h"] - lay["near"] / 2.0, lay["h"] + lay["near"] / 2.0,
          lay["h"] + lay["h_bridge"]]

    def dedup(vals: list[float]) -> list[float]:
        return sorted(set(round(float(v), 15) for v in vals))
    xs_t, ys_t, zs_t = dedup(xs), dedup(ys), dedup(zs)
    xs_lit = ", ".join(repr(v) for v in xs_t)
    ys_lit = ", ".join(repr(v) for v in ys_t)
    zs_lit = ", ".join(repr(v) for v in zs_t)
    tb_lit = "\n".join(
        f"coil.AddBox(({b[0]!r}, {b[1]!r}, {b[2]!r}), ({b[3]!r}, {b[4]!r}, "
        f"{b[5]!r}), priority=10)" for b in trace_boxes)
    bb_lit = "\n".join(
        f"bridge.AddBox(({b[0]!r}, {b[1]!r}, {b[2]!r}), ({b[3]!r}, {b[4]!r}, "
        f"{b[5]!r}), priority=10)" for b in bridge_boxes)
    via_lit = "\n".join(
        f"coil.AddBox(({b[0]!r}, {b[1]!r}, {b[2]!r}), ({b[3]!r}, {b[4]!r}, "
        f"{b[5]!r}), priority=10)" for b in (via_u, via_d))
    return f'''#!/usr/bin/env python3
"""openEMS coil_nfc script (rfauto df7 C10b auto-generated).

几何/端口/网格口径见 src/rfauto/adapters/openems_templates.py 文末 COIL_NFC 段。
13.56MHz MQS 频段：几何驱动网格（禁 λ 口径），真机预算见
runs/df7_nfc/criteria.md §e。
"""
import csv
import json
import os

_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN",
                         r"E:\\\\openEMS\\\\install\\\\bin")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.ports import LumpedPort

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}
TAND = {tan_d!r}
H_SUB = {lay["h"]!r}
H_BRIDGE = {lay["h_bridge"]!r}   # 跳线桥离板高（桥面=抬高金属层）
NEAR = {lay["near"]!r}   # 近特征区 = base/4
BASE = {lay["base"]!r}   # 网格 base：自动档 max(w,s,gap)/4（MQS 几何驱动）
DOM_X = {lay["dom_x"]!r}
DOM_Y = {lay["dom_y"]!r}
NRTS = {nrts}
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 无地平面线圈（辐射口径；13.56MHz 电小、近场主导）：全 MUR
FDTD.SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "MUR", "MUR"])

mesh = CSX.GetGrid()
# 螺旋/桥/过孔/端口全部特征线精确入网（#198），先 NEAR 后 BASE 平滑，
# 域界最后补入（平滑保线，slotline 族 _axis 同款次序）
for _x in np.array([{xs_lit}]):
    mesh.AddLine("x", _x)
for _y in np.array([{ys_lit}]):
    mesh.AddLine("y", _y)
mesh.SmoothMeshLines("x", NEAR)
mesh.SmoothMeshLines("y", NEAR)
mesh.AddLine("x", np.array([-DOM_X, DOM_X]))
mesh.AddLine("y", np.array([-DOM_Y, DOM_Y]))
mesh.AddLine("z", np.linspace(0, H_SUB, 5))
mesh.AddLine("z", np.array([{zs_lit}]))
mesh.AddLine("z", np.array([-1.5e-3, H_SUB + 2.0e-3]))
mesh.SmoothMeshLines("z", BASE)
# 近重合网格线守卫（#152）：平滑后按最小间距 1µm 去重
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

# ── 几何：FR4 类基板（无地平面）+ 阶梯方螺旋 + 中跳线桥 ──
sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, H_SUB), priority=0)
coil = CSX.AddMetal("coil")
{tb_lit}
# 过孔×2（内端上引 / 桥端下引落 pad）
{via_lit}
# 中跳线桥（抬高 z=H+H_BRIDGE，越下层走线不接触；lange air-bridge 同法）
bridge = CSX.AddMetal("bridge")
{bb_lit}
# 端口落 pad（外圈馈隙下侧）
coil.AddBox(({pad[0]!r}, {pad[1]!r}, {pad[4]!r}), ({pad[2]!r}, {pad[3]!r}, {pad[4]!r}), priority=10)

# ── 端口：LumpedPort 跨外圈馈隙（slotline_lumped 同口径，盒三向厚、
#    对称跨 z=H 金属面；exc 沿 +y=主电流方向）──
_port1 = LumpedPort(CSX, 1, 50.0,
                    np.array([{px0!r}, {py0!r}, {lay["h"] - lay["near"] / 2.0!r}]),
                    np.array([{px1!r}, {py1!r}, {lay["h"] + lay["near"] / 2.0!r}]),
                    "y", excite=1, priority=5)

# ── 求解 ──
# RFAUTO_SKIP_RUN=1：只重跑后处理（复用既有 fdtd/ 时域产物；几何段未变时合法）
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：单端口 S11（串联谐振谷=f0 判读位；R=50Ω 同参考）──
f = np.linspace(F0 - FC, F0 + FC, 201)
_port1.CalcPort(SIM_PATH, f, ref_impedance=50.0)
S11 = _port1.uf_ref / _port1.uf_inc

with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_S11", "im_S11"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, S11[_i].real, S11[_i].imag])
summary = {{
    "ok": True,
    "template": "coil_nfc",
    "f0_hz": F0, "fc_hz": FC,
    "n_turns": {lay["n"]},
    "d_out_m": {lay["d_out"]!r}, "w_m": {lay["w"]!r}, "s_m": {lay["s"]!r},
    "gap_m": {lay["gap"]!r}, "h_sub_m": H_SUB,
    "er": ER, "tan_d": TAND,
    "c_tune_pf_note": "C_tune=外匹配电容不进几何；f0 谷判读=1/(2π√(L·C))",
    "nrts": NRTS,
    "mesh_lines": [int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
}}
with open(os.path.join(SCRIPT_DIR, "coil_nfc_meta.json"), "w",
          encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto coil_nfc simulation done")
'''
# ═══════════════════════════════════════════════════════════════════════════════
# §MMWAVE_SERIES_ARRAY 串馈毫米波阵（2026-09-26 df7 C10d，文末注册块，coil_nfc
# 同款口径）═════════════════════════════════════════════════════════════════════
# 汽车雷达 76-81GHz 行波串馈贴片阵：微带串馈线 + N×λ/2 贴片（边接互联）+
# 链末匹配集总负载到地（行波阵；openEMS 惯例=shunt LumpedElement R=Z0 到
# z-min PEC 地，atten_pi shunt 同款渲染机制）。与 C2 patch_array_series 的
# 差异（§10.3 C2=λg/2 谐振式驻波阵、链末开路、同相侧射）：本族互联长 s 为
# 自由设计参数——行波渐进相位 Δφ = π + βg·s 逐元递推（π=λ/2 贴片两辐射边场
# 反相，C2 相位账同源）→ 波束倾斜 u0 = (Δφ−2πm)/(k0·d) 可设计（core/
# array_synthesis.series_feed_* 闭式，2026-09-26 C10d 加法式扩展）。
# 名义尺寸全闭式精算（#1c/#252，导入期 mmwave_series_design_params() 非手抄）：
# 单元 W/L=Balanis Ch.14（array_elem_w_mm/len_mm 复用，er/h 参数化）、
# 线宽=skrf HJ inverse_width 50Ω、βg=k0·√εeff(HJ @feed_w)、s=倾斜式反解。
# 基板 RO3003 类（er=3.0/h=0.127/tan_d=0.001，模板参数基板——ms 族「er/tan_d
# 走 substrate/nominal」同口径；0.508 缺省板在 78GHz 非物理厚）。
# 真机面：预算预声明 runs/df7_c10d/criteria.md §d（~3.6e7 cells/dt~4.8e-14s/
# NrTS~2.5e4/墙钟数小时～半天每点），本批零发射。
MMWAVE_SERIES_TEMPLATES: frozenset[str] = frozenset({"mmwave_series_array"})
_MMWAVE_DOM_MM = 20.0            # 方域半宽（40×40mm 板，criteria §d 域）
_MMWAVE_AIR_TOP_MM = 1.0         # 空气隙（≈λ0/4 @78GHz + MUR 余量）
_MMWAVE_TAN_D = 0.001            # RO3003 类损耗（设计点典型值）
_MMWAVE_FEED_MARGIN_MM = 3.0     # 板边到链首元馈段长（#347 守卫下限核算见下）
_MMWAVE_LOAD_R_OHM = 50.0        # 端接=线 Z0（一阶未载入口径，如实不进锚）


def mmwave_series_design_params(
    f0_ghz: float = 78.0,
    tilt_u0: float = 0.30,
    n_elem: int = 4,
    er: float = 3.0,
    h_mm: float = 0.127,
    tan_d: float = _MMWAVE_TAN_D,
    feed_margin_mm: float = _MMWAVE_FEED_MARGIN_MM,
    load_r_ohm: float = _MMWAVE_LOAD_R_OHM,
) -> dict[str, Any]:
    """C10d 串馈毫米波阵全参数设计链（4 位舍入；MMWAVE_SERIES_NOMINAL=
    本函数缺省调用，单测互检 #252）。

    闭合链：W/L（Balanis Ch.14，array_elem_w_mm/len_mm）→ feed_w（skrf HJ
    50Ω，先舍入再算 εeff——C2 同口径）→ βg=k0√εeff → 互联长 s 由倾斜设计式
    反解：u0 = (π + βg·s − 2π)/(k0·(L+s))  ⇒  s = (u0·k0·L + π)/(βg − u0·k0)
    （主分支 m=1，s∈(0, λg) 域）。设计守卫：u0 落可见区（闭式内部）、
    栅瓣判据 d/λ0 < 1/(1+u0)（Balanis Ch.6；越界显式 ValueError——
    名义 u0=0.30 时 d/λ0=0.696 < 0.769 余量 0.073λ0，u0≳0.37 即入栅瓣域）。
    """
    f0 = float(f0_ghz)
    u0_target = float(tilt_u0)
    n = int(n_elem)
    if not (f0 > 0.0 and 0.0 < u0_target < 1.0):
        raise ValueError("f0 须正且 tilt_u0 须落在 (0, 1)")
    if n < 2:
        raise ValueError(f"n_elem 须 ≥2（串馈阵定义），收到 {n_elem!r}")
    if not (float(er) > 1.0 and float(h_mm) > 0.0):
        raise ValueError("er 须 >1 且 h_mm 须正")
    w_raw = array_elem_w_mm(f0, er)
    l_raw = array_elem_len_mm(f0, w_raw, er, h_mm)
    fw = round(array_line_w_mm(50.0, f0, er, h_mm), 4)
    lam0 = _ARR_C_MM_GHZ / f0
    k0 = 2.0 * math.pi / lam0
    beta_g = k0 * math.sqrt(_ant2_eps_eff(fw, f0, er, h_mm))
    s_raw = (u0_target * k0 * l_raw + math.pi) / (beta_g - u0_target * k0)
    if not (0.0 < s_raw < lam0):
        raise ValueError(
            f"串馈倾斜设计式 s={s_raw:.6g}mm 落 (0, λg) 域外（u0={u0_target}）")
    # 设计式公式自检在舍入前（未舍入闭合往返 ≤1e-9）；舍入后重建偏差由
    # 4 位舍入主导（≤~4e-5，不作为公式错判据）
    u0_raw = (math.pi + beta_g * s_raw - 2.0 * math.pi) / (k0 * (l_raw + s_raw))
    if abs(u0_raw - u0_target) > 1e-9:
        raise ValueError(
            f"倾斜设计式往返失配：u0 重建 {u0_raw:.9g} != 目标 {u0_target}")
    s = round(s_raw, 4)
    length = round(l_raw, 4)
    pitch = length + s
    u0_recon = (math.pi + beta_g * s - 2.0 * math.pi) / (k0 * pitch)
    from rfauto.core.array_synthesis import has_grating_lobe

    if has_grating_lobe(pitch / lam0, u0_recon):
        raise ValueError(
            f"串馈设计点入栅瓣域：d/λ0={pitch / lam0:.4g} ≥ 1/(1+u0)="
            f"{1.0 / (1.0 + u0_recon):.4g}（u0={u0_recon:.4g}）——调小 tilt_u0")
    params: dict[str, Any] = {
        "n_elem": n,
        "elem_len_mm": length,
        "elem_w_mm": round(w_raw, 4),
        "link_len_mm": s,
        "feed_w_mm": fw,
        "feed_margin_mm": round(float(feed_margin_mm), 4),
        "load_r_ohm": round(float(load_r_ohm), 4),
        "h_mm": round(float(h_mm), 4),
        "er": round(float(er), 4),
        "tan_d": round(float(tan_d), 4),
    }
    return params


# 名义设计点 @78GHz/u0=0.30/N=4（导入期闭式合成，非手抄 #252）
MMWAVE_SERIES_NOMINAL: dict[str, Any] = mmwave_series_design_params()

MMWAVE_SERIES_META: dict[str, Any] = {
    "f0_ghz": 78.0, "n_ports": 1,
    "extraction": "S11 @ MSLPort 1（1×4 行波串馈贴片阵，链末 50Ω 集总匹配到"
                  "地：谷位=单元谐振设计式精确逆 patch_resonance_hj_ghz；方向"
                  "图走 far_field=True nf2ff，离线裁判=相位递推闭式主瓣指向 "
                  "core/array_synthesis.series_feed_beam_direction_cosine；"
                  "未真机冒烟）",
    "max_time_ns": 60.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["n_elem", "elem_len_mm", "elem_w_mm", "link_len_mm",
               "feed_w_mm", "feed_margin_mm", "h_mm"],
    "topology": "1×N 串馈毫米波阵（§18.3d C10d）：N 元共线沿 y（x=0 居中，"
                "L 沿 y/W 沿 x），相邻元以互联线接辐射边中心（互联长 s=自由"
                "设计参数，行波渐进相位 βg·s）；MSLPort 自 y=−DOM 入、自画馈"
                "段至链首元（feed_margin）；链末 stub+匹配集总负载到地（R="
                "线 Z0 一阶）——行波阵口径，与 C2 patch_array_series（λg/2 "
                "谐振式、链末开路）分族；基板 + z-min PEC 地，y 轴 PML_8",
    "param_semantics": "n_elem=单元数（≥2），elem_len_mm=单元谐振长 L（沿 y；"
                       "Balanis Ch.14 c/(2f0√εeff)−2ΔL，fake 谷位为其精确"
                       "逆），elem_w_mm=单元宽 W（c/(2f0)√(2/(εr+1))），"
                       "link_len_mm=互联线长 s（行波渐进相位自由度：u0=(π+"
                       "βg·s−2π)/(k0·d)，d=L+s；s=λg/2 退化为 C2 同相侧"
                       "射），feed_w_mm=50Ω 馈线/互联宽（HJ 0.3259mm @78GHz），"
                       "feed_margin_mm=板边到链首元馈段长（MSLPort 自画，"
                       "MeasPlaneShift=margin/3），h_mm=基板厚（毫米波板 "
                       "0.127）；er/tan_d 走 substrate/nominal（RO3003 类）",
    "mesh_note": "辐射器件：上方空气隙 λ0/4+、侧向至域界（MUR）；贴片/互联/"
                 "stub/负载盒缘精确入网（#198）；渲染守卫：NEAR≤feed_w/3"
                 "（#266 族，线宽分辨）、|MeasPlaneShift−FeedShift|≥3.9·NEAR"
                 "（#347）；全轴 1µm 近重合去重（#152）；端口面贴 PML_8 域边"
                 "（#154 前节）",
    "smoke_note": "未冒烟（离线审计过，#212，test_mmwave_series_array_"
                  "template）；真机发射面=预算预声明 runs/df7_c10d/criteria."
                  "md §d（0.1mm 格 ~3.6e7 cells、dt~4.8e-14s、NrTS~2.5e4、"
                  "墙钟数小时～半天/点，发射前以 exec 实测为准），本批零发射",
}

# ── 注册：同对象入 TEMPLATE_META/TEMPLATE_NOMINAL（单一事实源；尾部追加 #247）──
TEMPLATE_META["mmwave_series_array"] = MMWAVE_SERIES_META
TEMPLATE_NOMINAL["mmwave_series_array"] = MMWAVE_SERIES_NOMINAL
_TEMPLATE_PORT_AXES["mmwave_series_array"] = ("y",)
_TEMPLATE_RADIATOR["mmwave_series_array"] = True


def mmwave_series_meta(template: str) -> dict[str, Any]:
    """返回 C10d 串馈毫米波阵元数据（与 template_meta(t) 同构的便捷别名）。"""
    if template not in MMWAVE_SERIES_TEMPLATES:
        raise KeyError(f"非串馈毫米波阵模板: {template}")
    meta = dict(MMWAVE_SERIES_META)
    meta["template"] = template
    meta["substrate"] = {
        "er": MMWAVE_SERIES_NOMINAL["er"],
        "h_mm": MMWAVE_SERIES_NOMINAL["h_mm"],
        "tan_d": MMWAVE_SERIES_NOMINAL["tan_d"],
    }
    meta["nominal_params"] = dict(MMWAVE_SERIES_NOMINAL)
    return meta


def _mmwave_series_layout(
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    mesh_resolution_mm: float = 0.0,
) -> dict[str, Any]:
    """C10d 串馈毫米波阵单一事实源（mm）：金属盒 / 端口 / 单元中心 / 特征线。

    渲染段（mmwave_series_render）、UI 预览（mmwave_series_geometry_spec）、
    离线审计（#212 exec 截断）与本模板单测四方消费——单源防漂移（_arr_layout
    同制度）。金属盒元组 = (属性名, 盒名, x0, y0, z0, x1, y1, z1)，零厚顶面
    z=h（官方金属面口径）；端接集总负载单列（LumpedElement 盒 z=0..h）。
    相位/波束闭式自洽：layout 内调 core/array_synthesis.
    series_feed_beam_direction_cosine 守卫（主波束落可见区外显式 ValueError）。
    """
    if "mmwave_series_array" not in MMWAVE_SERIES_TEMPLATES:  # pragma: no cover
        raise ValueError("注册表漂移")
    nom = MMWAVE_SERIES_NOMINAL

    def g(key: str) -> Any:
        return params.get(key, nom[key])

    n = int(float(g("n_elem")))
    if n < 2:
        raise ValueError(f"mmwave_series_array: n_elem 须 ≥2，收到 {n}")
    length = float(g("elem_len_mm"))
    width = float(g("elem_w_mm"))
    s = float(g("link_len_mm"))
    fw = float(g("feed_w_mm"))
    margin = float(g("feed_margin_mm"))
    load_r = float(g("load_r_ohm"))
    h = float(g("h_mm"))
    er = float(g("er"))
    for label, v in (("elem_len_mm", length), ("elem_w_mm", width),
                     ("link_len_mm", s), ("feed_w_mm", fw),
                     ("feed_margin_mm", margin), ("load_r_ohm", load_r),
                     ("h_mm", h)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"mmwave_series_array: {label} 必须为正有限，得到 {v!r}")
    if fw >= width:
        raise ValueError(f"mmwave_series_array: 馈线宽 {fw} 须小于单元宽 {width}")
    dom = _MMWAVE_DOM_MM
    f0 = (float(freq_range_ghz[0]) + float(freq_range_ghz[1])) / 2.0
    lam0 = _ARR_C_MM_GHZ / f0
    k0 = 2.0 * math.pi / lam0
    beta_g = k0 * math.sqrt(_ant2_eps_eff(fw, f0, er, h))
    pitch = length + s
    from rfauto.core.array_synthesis import series_feed_beam_direction_cosine

    u0_pred = series_feed_beam_direction_cosine(pitch, k0, s, beta_g)
    # 网格：显式覆盖优先；自动档=线宽驱动（毫米波几何驱动，meta mesh_note）
    base = (fw / 4.0 if not mesh_resolution_mm
            else float(mesh_resolution_mm))
    near = base / 4.0
    if near > fw / 3.0:
        raise ValueError(
            f"mmwave_series_array: NEAR={near:.4g}mm > feed_w/3={fw / 3.0:.4g}mm"
            "（#266 族线宽分辨守卫，收紧 mesh_resolution_mm）")
    feed_shift = 10.0 * near
    meas_shift = margin / 3.0
    if abs(meas_shift - feed_shift) < 3.9 * near:
        raise ValueError(
            f"mmwave_series_array: |MeasPlaneShift({meas_shift:.4g})−FeedShift"
            f"({feed_shift:.4g})| < 3.9·NEAR={3.9 * near:.4g}mm（#347 探针入"
            "激励盒近场守卫，加大 feed_margin_mm）")
    # 链几何（mm）
    load_seg = 2.0 * fw                 # 端接 stub 长（负载盒占后半段）
    y_start = -dom + margin             # 链首元 −y 边
    chain_top = y_start + n * length + (n - 1) * s
    y_end = chain_top + load_seg
    if y_end > dom - _ARR_EDGE_MARGIN_MM:
        raise ValueError(
            f"mmwave_series_array: 链顶+端接 {y_end:.3f}mm 超域（≤{dom - _ARR_EDGE_MARGIN_MM:.3f}mm；"
            f"{n}·L + {n - 1}·s + margin + 端接）")
    prop_line = "mmwave_series_array_line"
    boxes: list[tuple[str, str, float, float, float, float, float, float]] = []
    elements: list[tuple[float, float]] = []
    x_lines: list[float] = [-width / 2, width / 2, -fw / 2, fw / 2, 0.0]
    y_lines: list[float] = [-dom, -dom + margin, y_start, y_end]
    y = y_start
    for k in range(n):
        boxes.append((prop_line, f"e{k}", -width / 2, y, h, width / 2, y + length, h))
        elements.append((0.0, y + length / 2))
        y_lines += [y, y + length]
        if k < n - 1:
            boxes.append((prop_line, f"link{k}", -fw / 2, y + length, h,
                          fw / 2, y + length + s, h))
            y_lines.append(y + length + s)
        y += length + s
    boxes.append((prop_line, "load_stub", -fw / 2, chain_top, h,
                  fw / 2, y_end, h))
    # 行波端接：匹配集总负载到地（shunt ny=z；atten_pi shunt 同款机制）
    load_box = (-fw / 2, chain_top + fw, 0.0, fw / 2, y_end, h)
    y_lines += [chain_top + fw]
    port = {"kind": "msl", "nr": 1, "metal_prop": prop_line,
            "start_mm": (fw / 2, -dom, h),
            "stop_mm": (-fw / 2, -dom + margin, 0.0),
            "prop_dir": "y", "exc_dir": "z", "excite": 1,
            "meas_shift_mm": meas_shift}
    return {
        "n": n, "f0_ghz": f0, "lam0_mm": lam0, "k0_rad_mm": k0,
        "beta_g_rad_mm": beta_g, "u0_pred": u0_pred,
        "pitch_mm": pitch, "elem_len_mm": length, "elem_w_mm": width,
        "link_len_mm": s, "dom_mm": dom, "h_mm": h, "er": er,
        "base_mm": base, "near_mm": near,
        "feed_shift_mm": feed_shift, "meas_shift_mm": meas_shift,
        "boxes": boxes, "load_box": load_box, "load_r_ohm": load_r,
        "port": port, "elements_mm": elements,
        "x_lines_mm": x_lines, "y_lines_mm": y_lines,
        "air_top_mm": _MMWAVE_AIR_TOP_MM,
    }


def mmwave_series_geometry_spec(
    params: dict[str, Any],
    substrate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """mmwave_series_array UI 预览 spec（mm；early-dispatch 自 geometry_spec）。"""
    lay = _mmwave_series_layout(params, (MMWAVE_SERIES_META["f0_ghz"],
                                         MMWAVE_SERIES_META["f0_ghz"]))
    xs = [b[2] for b in lay["boxes"]] + [b[5] for b in lay["boxes"]]
    ys = [b[3] for b in lay["boxes"]] + [b[6] for b in lay["boxes"]]
    dom = lay["dom_mm"]
    h = lay["h_mm"]
    boxes = [
        {"name": "substrate", "material": "substrate",
         "start_mm": [-dom, -dom, 0.0], "stop_mm": [dom, dom, h]},
        {"name": "series_chain（串馈链+端接 stub）", "material": "metal",
         "start_mm": [min(xs), min(ys), h], "stop_mm": [max(xs), max(ys), h]},
    ]
    ports = [{"name": "Port1（MSLPort，行波串馈馈入）",
              "pos_mm": [0.0, -dom, h], "dir": [0.0, -1.0, 0.0]}]
    sub_view = {"er": lay["er"], "h_mm": h,
                "tan_d": float(params.get("tan_d",
                                          MMWAVE_SERIES_NOMINAL["tan_d"]))}
    return {"template": "mmwave_series_array", "substrate": sub_view,
            "boxes": boxes, "ports": ports,
            "elements": [{"name": "load_termination", "kind": "lumped_r",
                          "r_ohm": lay["load_r_ohm"], "ny": "z",
                          "span_mm": [lay["load_box"][1], lay["load_box"][4]],
                          "y_mm": lay["load_box"][4]}]}


def mmwave_series_render(
    template: str,
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    mesh_resolution_mm: float = 0.0,
    substrate: dict[str, Any] | None = None,
    far_field: bool = False,
) -> str:
    """mmwave_series_array 整脚本渲染器（早分发自 render_script；coil_nfc
    同款结构）。

    单端口（MSLPort 自 PML_8 域边入）+ 链末匹配集总负载到地：S11=单元谐振
    谷口径（行波阵的带内吸收谷，fake 同源精确逆判读）；y=PML_8 端口轴、
    x=MUR、z0=PEC 地、z1=MUR。er/tan_d/h 从 params/NOMINAL 消费（模板自带
    RO3003 类板材；render_script 顶层会把缺省 substrate 重绑为 RO4350B——
    本族不用全局缺省板材）。_nrts 旋钮缺省逐字节不变；far_field=True 注入
    官方 nf2ff 盒（z 底=PEC 接地分支，CreateNF2FFBox 自动镜像口径）。
    """
    del substrate, template   # 板材/域全由 params/NOMINAL 单源（段头注释）
    lay = _mmwave_series_layout(params, freq_range_ghz, mesh_resolution_mm)
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = abs(freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9
    er = float(params.get("er", MMWAVE_SERIES_NOMINAL["er"]))
    tan_d = float(params.get("tan_d", MMWAVE_SERIES_NOMINAL["tan_d"]))
    nrts = int(params.get("_nrts", 60000) or 60000)
    h = lay["h_mm"] * 1e-3
    dom = lay["dom_mm"] * 1e-3
    air_top = lay["air_top_mm"] * 1e-3
    base = lay["base_mm"] * 1e-3
    near = lay["near_mm"] * 1e-3
    load_r = lay["load_r_ohm"]

    def m(v: float) -> float:
        return float(v) * 1e-3

    box_lit = "\n".join(
        f'line.AddBox(({m(b[2])!r}, {m(b[3])!r}, {m(b[4])!r}), '
        f'({m(b[5])!r}, {m(b[6])!r}, {m(b[7])!r}), priority=10)  # {b[1]}'
        for b in lay["boxes"])
    lb = lay["load_box"]
    load_lit = (f'load.AddBox(({m(lb[0])!r}, {m(lb[1])!r}, {m(lb[2])!r}), '
                f'({m(lb[3])!r}, {m(lb[4])!r}, {m(lb[5])!r}), priority=10)')
    x_lit = ", ".join(repr(m(v)) for v in sorted(set(lay["x_lines_mm"])))
    y_lit = ", ".join(repr(m(v)) for v in sorted(set(lay["y_lines_mm"])))
    p = lay["port"]
    ff_setup = ""
    ff_calc = ""
    if far_field:
        ff_setup = (
            "\n# ── nf2ff 盒（官方 Simple Patch Antenna：域缩 4×网格；"
            "z 底=PEC 边界自动镜像）──\n"
            "_FF_MARGIN = 4 * BASE\n"
            "_FF_START = np.array([-DOM_X + _FF_MARGIN, -DOM_Y + _FF_MARGIN, 0.0])\n"
            "_FF_STOP = np.array([DOM_X - _FF_MARGIN, DOM_Y - _FF_MARGIN,\n"
            "                     H_SUB + AIR_TOP - _FF_MARGIN])\n"
            "_FF = FDTD.CreateNF2FFBox('nf2ff', _FF_START, _FF_STOP)\n")
        ff_calc = (
            "\n# ── nf2ff 远场（f_res=|S11| 谷；Dmax/η best-effort #105；"
            "η 注意 PEC 镜像 Prad 双计口径 #249，主判=主瓣指向 vs 相位递推"
            "闭式）──\n"
            "try:\n"
            "    _f_res_i = int(np.argmin(np.abs(S11)))\n"
            "    _f_res = float(f[_f_res_i])\n"
            "    _THETA_CUT = np.arange(-180.0, 181.0, 1.0)\n"
            "    _PHI_CUT = [0.0, 90.0]\n"
            "    _ffr = _FF.CalcNF2FF(SIM_PATH, _f_res, _THETA_CUT, _PHI_CUT)\n"
            "    _db = np.asarray(_ffr.E_norm[0], dtype=float)\n"
            "    _db = 20 * np.log10(_db / max(_db.max(), 1e-300) + 1e-300)\n"
            "    _peak = int(np.argmax(_db[:, 1]))\n"
            "    _meta = dict(ok=True, f_res_hz=_f_res,\n"
            "                 peak_theta_deg=float(_THETA_CUT[_peak]),\n"
            "                 phi_cut_deg=_PHI_CUT,\n"
            "                 note='PEC 镜像 Prad 双计口径 #249；主判=指向')\n"
            "    with open(os.path.join(SCRIPT_DIR, 'farfield_meta.json'),\n"
            "              'w', encoding='utf-8') as _mh:\n"
            "        json.dump(_meta, _mh, ensure_ascii=False, indent=1)\n"
            "except Exception as _ffe:\n"
            "    print('rfauto nf2ff 链失败（不阻塞 S 参数）:', _ffe)\n")
    return f'''#!/usr/bin/env python3
"""openEMS mmwave_series_array script (rfauto df7 C10d auto-generated).

几何/端口/网格口径见 src/rfauto/adapters/openems_templates.py 文末
MMWAVE_SERIES_ARRAY 段。行波串馈（βg·s 渐进相位递推，波束倾斜 u0=
{lay["u0_pred"]:.4f} 闭式 core/array_synthesis）+ 链末匹配集总负载到地；
真机预算预声明 runs/df7_c10d/criteria.md §d（本批零发射）。
"""
import csv
import json
import os

_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN",
                         "E:/openEMS/install/bin")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.ports import MSLPort

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}
TAND = {tan_d!r}
H_SUB = {h!r}
AIR_TOP = {air_top!r}   # 空气隙（≈λ0/4 @78GHz + MUR 余量）
BASE = {base!r}   # 网格 base：自动档 feed_w/4（毫米波几何驱动）
NEAR = {near!r}   # 近特征区 = base/4
DOM_X = {dom!r}
DOM_Y = {dom!r}
LOAD_R = {load_r!r}   # 行波端接=线 Z0（一阶未载入口径）
NRTS = {nrts}
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)   # 官方口径：不设 EndCriteria，能量判据停机
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 行波串馈链（辐射口径）：y=PML_8 端口轴（#154 前节）、x=MUR、z0=PEC 地
FDTD.SetBoundaryCond(["MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"])

mesh = CSX.GetGrid()
# 链/端口/负载全部特征线精确入网（#198）：特征区 NEAR 细分→域界补入→
# 空气区 BASE 粗化（细格只在特征走廊，空气区 λ0/BASE≈38 格够；dt 由最小
# 格 NEAR 定，双档平滑不放宽 CFL——预算随最小格走，criteria §d）
for _x in np.array([{x_lit}]):
    mesh.AddLine("x", _x)
for _y in np.array([{y_lit}]):
    mesh.AddLine("y", _y)
mesh.SmoothMeshLines("x", NEAR)
mesh.SmoothMeshLines("y", NEAR)
mesh.AddLine("x", np.array([-DOM_X, DOM_X]))
mesh.AddLine("y", np.array([-DOM_Y, DOM_Y]))
mesh.SmoothMeshLines("x", BASE)
mesh.SmoothMeshLines("y", BASE)
mesh.AddLine("z", np.linspace(0, H_SUB, 5))
mesh.AddLine("z", np.array([H_SUB + AIR_TOP]))
mesh.SmoothMeshLines("z", BASE)
# 近重合网格线守卫（#152）：平滑后按最小间距 1µm 去重
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

# ── 几何：RO3003 类基板 + 串馈链（贴片×{lay["n"]} + 互联 + 端接 stub）──
sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, H_SUB), priority=0)
line = CSX.AddMetal("line")
{box_lit}
# 行波端接：链末匹配集总负载到地（shunt ny=z，R=线 Z0 一阶口径）
load = CSX.AddLumpedElement("load", ny=2, caps=True, R=LOAD_R)
{load_lit}

# ── 端口：MSLPort 自 y=−DOM 域边（PML_8 面）入，自画馈段至链首元 ──
_port1 = MSLPort(CSX, port_nr=1, metal_prop=line,
                 start=np.array([{m(p["start_mm"][0])!r}, {m(p["start_mm"][1])!r}, {m(p["start_mm"][2])!r}]),
                 stop=np.array([{m(p["stop_mm"][0])!r}, {m(p["stop_mm"][1])!r}, {m(p["stop_mm"][2])!r}]),
                 prop_dir="y", exc_dir="z", excite=1,
                 FeedShift=10 * NEAR, MeasPlaneShift={m(p["meas_shift_mm"])!r},
                 priority=10)
{ff_setup}
# ── 求解 ──
# RFAUTO_SKIP_RUN=1：只重跑后处理（复用既有 fdtd/ 时域产物；几何段未变时合法）
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：单端口 S11（单元谐振吸收谷=f0 判读位；R=50Ω 同参考）──
f = np.linspace(F0 - FC, F0 + FC, 201)
_port1.CalcPort(SIM_PATH, f, ref_impedance=50.0)
S11 = _port1.uf_ref / _port1.uf_inc

with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_S11", "im_S11"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, S11[_i].real, S11[_i].imag])
{ff_calc}summary = dict(
    ok=True, template="mmwave_series_array", f0_hz=F0, fc_hz=FC,
    n_elem={lay["n"]}, u0_pred={lay["u0_pred"]!r},
    pitch_mm={lay["pitch_mm"]!r}, beta_g_rad_mm={lay["beta_g_rad_mm"]!r},
    elem_len_mm={lay["elem_len_mm"]!r}, link_len_mm={lay["link_len_mm"]!r},
    load_r_ohm=LOAD_R, nrts=NRTS,
    mesh_lines=[int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
)
with open(os.path.join(SCRIPT_DIR, "mmwave_series_array_meta.json"), "w",
          encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto mmwave_series_array simulation done")
'''
