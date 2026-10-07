"""模板注册表单源（TEMPLATE_META/TEMPLATE_NOMINAL/端口轴/辐射器清单）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
#: - fgcpw（TA-9）：无底地共面槽场族——缝下场竖直尺度 h/π 同为分辨限制项，
#:   cpw/msl_cpw G3 分档同族迁移（core/fgcpw docstring；FD 裁判 zconv 定案
#:   实验证据链见 registry 头注）。
_SUB_CELLS_8_TEMPLATES: frozenset[str] = frozenset({"msl_cpw", "cpw", "fgcpw"})

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
        "臂中点馈电+隔离端悬空，三处结构性错误）。名义臂注记（R2-1 审查批"
        " 2026-10-04）：arm_len_mm=20.5 为薄线极限捷径口径（HJ 精算正解 "
        "18.09mm，偏差 +11.8%，已裁定维持锚定基线不改数值）；出处："
        "runs/review_ge8e/r2_synthesis_templates_anchors/REPORT.md R2-1 "
        "与坑#252",
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
        "params": ["z1_width_mm", "z2_width_mm", "seg_len_mm", "n_segments",
                   "feed_w_mm"],
        "mesh_note": "分段 junction 处 y 向 near 加密",
        "param_semantics": "z1_width_mm=高阻段宽（HJ 96.9Ω，交替起点），"
        "z2_width_mm=低阻段宽（HJ 24.8Ω），seg_len_mm=单段长度，"
        "n_segments=段数，feed_w_mm=两端馈线宽（50Ω HJ 精算 1.1133mm，"
        "六百七十一/#1c 修复批：端口线=50Ω 使 #250 参考系分裂机制根除；"
        "缺省回退 z1=修复前口径）。旧文本 z1 低阻/z2 高阻系标签颠倒勘误",
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
# ── 50Ω 宽常数出处（XC-W 单源化，2026-10-02）──：本表为**归档字面量**
# （仓内惯例：字面量落表避免模块导入期 brentq ~1s），不改值；唯一计算源=
# core/synthesis.nominal_width_mm（inverse_width(50) 回代自洽档）：
#   1.1134 = round4 @2.5GHz rogers4350b_h0.508（wstep/tjunc/bend/via/
#           atten_pi/atten_t/ratrace/gysel 馈线档）
#   1.1133 = round4 @2.4GHz 同层叠（stepped_impedance feed_w_mm，f0=2.4）
#   1.113  = round3 档（wilkinson shunt_w_mm@2.4 / mline w_mm@2.5，
#           跨频同档逐位同值）
# 逐位一致性由 tests/unit/test_width_single_source.py 钉住。
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
    # branchline 名义臂注记（R2-1 审查批 2026-10-04）：arm_len_mm=20.5 为
    # 薄线极限捷径口径（HJ 精算正解 18.09mm，偏差 +11.8%，已裁定维持锚定
    # 基线不改数值——锚历史，#252 定性）；出处 runs/review_ge8e/
    # r2_synthesis_templates_anchors/REPORT.md R2-1
    "branchline": {"arm_len_mm": 20.5, "series_w_mm": 1.87, "shunt_w_mm": 1.11},
    "dipole": {"dipole_len_mm": 58.0, "dipole_w_mm": 2.0, "gap_mm": 2.0},
    # stepped_impedance：z1/z2=阶梯设计段（0.3/3.0mm→HJ 96.9/24.8Ω 高低阻，
    # audit 六百六十八①实证 HFSS 与此级联逐门吻合——设计不动）；feed_w_mm=
    # 两端馈线 50Ω HJ 精算（六百七十一量化：0.3mm=96.9Ω 非 50Ω 是 #250
    # 参考系分裂机制，1.1133mm inverse_width 回代自洽=50.00Ω @2.4GHz）
    "stepped_impedance": {"z1_width_mm": 0.3, "z2_width_mm": 3.0, "seg_len_mm": 5.0, "n_segments": 5, "feed_w_mm": 1.1133},
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
    # varactor_bpf（M-5 变容管调谐 BPF，2026-09-27 起正式注册）：hairpin 同族
    # 布局（抽头馈线自 x=∓BOARD 引入）→ 单轴 x PML
    "varactor_bpf": ("x",),
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
    # TA Wave A 席 1（2026-10-03，render_ta_wave_a 注册块）：三模板端口轴
    # 均 y（板边/端面）→ 单轴 y PML；hmsiw 矩形域 DOM 注入（siw 同款）
    "inverted_ms": ("y",), "hmsiw": ("y",), "fgcpw": ("y",),
    # TA/AP Wave B 席 B9（2026-10-03，render_ta_wave_b 注册块）：ISL 双
    # MSLPort 板边入（y 轴，inverted_ms 口径）→ 单轴 y PML；Vivaldi 跨槽
    # 微带馈沿 x（slot 模板转置）→ 单轴 x PML
    "isl_shielded": ("y",), "vivaldi_tsa": ("x",),
    # TA Wave C 席 D2（2026-10-03，render_ta_wave_c 注册块）：embedded_ms
    # 双 MSLPort 板边入（y 轴，inverted_ms 口径）；xcheb_bpf4 双抽头馈线
    # （x 轴，hairpin 口径）
    "embedded_ms": ("y",), "xcheb_bpf4": ("x",),
}

# 四端口"单激励列轮转"模板（#208 进程隔离：适配器层按 excite_port=1..4
# 渲染 4 份脚本各跑一次后装配整 4×4；渲染脚本尾部走 9 列单激励 CSV，
# 与 ratrace 同款 footer——openems_rotation.solve_smatrix_openems 通用消费）
# branchline：2026-09-16 起 port4 隔离端为真 MSLPort（四端口升级），入轮转集
_FOUR_PORT_ROTATION_TEMPLATES: tuple[str, ...] = (
    "ratrace", "branchline", "cline_coupler", "branchline_2sect", "lange",
    # §DP-4 P3 EEP 阵列族：每元独立 LumpedPort 探针 1..4，单激励轮转=EEP 集列
    "patch_eep_2x2", "patch_eep_1x4",
    # TA-1 Schiffman 移相器（2026-10-02 TA 批）：port1/2=耦合段 C-section、
    # port3/4=参考段——差分相移 Δφ(f)=∠S43−∠S21 是器件定义量，全矩阵轮转装配
    "schiffman")

# 五端口"单激励列轮转"模板（TA-4 nway_wilkinson，2026-10-02 TA 批第二批）：
# #208 口径推广——rotation 管线（openems_rotation.solve_smatrix_openems）
# n_ports 参数化原生支持 N≠4（P2⑬ 通用列），渲染 footer 走 11 列单激励
# CSV（freq + 5×(re,im)）；渲染脚本按 meta n_ports=5 接受 excite_port=1..5
_NWAY_PORT_ROTATION_TEMPLATES: tuple[str, ...] = ("nway_wilkinson",)

# 三端口"单激励列轮转"模板（TA-5 diplexer，2026-10-02 TA 批第三批）：
# #208 口径 N=3 档——渲染 footer 走 7 列单激励 CSV（freq + 3×(re,im)）；
# 主判读列=port1（antenna 公共口）：S11/S21/S31 一列全出（能量守恒/互补/
# 交越三判读量均在 port1 列），port2/3 轮仅补全 S 矩阵
_THREE_PORT_ROTATION_TEMPLATES: tuple[str, ...] = ("diplexer",)

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
    # varactor_bpf（M-5 变容管调谐 BPF）：hairpin 同族布局，非辐射器件
    "varactor_bpf": False,
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
    # TA Wave A 席 1（2026-10-03）：三模板均 guided 传输线（5mm 空气隙足够；
    # hmsiw 底板+藩篱半封闭、fgcpw 底 MUR 槽场局限、inverted_ms 底 PEC）
    "inverted_ms": False, "hmsiw": False, "fgcpw": False,
    # TA/AP Wave B 席 B9（2026-10-03）：ISL 屏蔽腔传输线（顶板封闭，非辐射
    # 器件，5mm 空气隙足够）；Vivaldi=端射行波天线（辐射器件，λ0/4 空气隙
    # +底 MUR 域下延，slot 同款）
    "isl_shielded": False, "vivaldi_tsa": True,
    # TA Wave C 席 D2（2026-10-03）：embedded_ms 嵌埋均匀线（guided，底 PEC）
    # 与 xcheb_bpf4 开路环 BPF（guided 滤波器，hairpin 同族）均非辐射器件
    "embedded_ms": False, "xcheb_bpf4": False,
}


def template_meta(template: str) -> dict[str, Any]:
    """返回模板元数据（含公共字段）；未知模板抛 KeyError。"""
    meta = dict(TEMPLATE_META[template])
    meta["template"] = template
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(TEMPLATE_NOMINAL[template])
    return meta
