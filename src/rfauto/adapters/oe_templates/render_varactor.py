"""varactor_bpf 变容管可调滤波器族（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from .registry import _DEFAULT_SUB, TEMPLATE_META, TEMPLATE_NOMINAL
from .render_hairpin import _hairpin_layout

# ── §M-5 varactor_bpf：变容二极管调谐 BPF（首个半有源模板，2026-09-27）──────
# 研究扩充 M-5：hairpin 族增量——谐振臂开路端对地
# 并联 lumped C(V)（突变结闭式 C=Cj0/√(1+V/φ)，core/varactor.py 单源），布局
# 单源 _hairpin_layout（与 hairpin 同族增量口径），调谐=偏置 V 改 C 改 f0。
#
# **静态电容口径（写进 meta，判读者必读）**：openEMS FDTD 的 LumpedElement
# 电容是每 run 常数（CSXCAD .pyx 逐行核实：CSPropLumpedElement 的 `C` kwarg
# →SetCapacity（法拉）、`ny` 经 CheckNyDir 收方向索引（0/1/2=x/y/z，ny=2 即
# z 向 shunt 对地惯用法，#282 审计结论；combline c_load 同款渲染先例）、
# LEtype 缺省 LE_PARALLEL、caps=True 两端 PEC 端板）——**FDTD 无时变 C，
# 三档偏压=三次静态 run**，各档 C(V_i) 为常数，调谐曲线由多点静态解组成。
#
# 主谐振方程（core/varactor.py，单测钉住）：开路端装载 λ/2 臂
#   tan(βL) = −ω·C·Z0 ，βL ∈ (π/2, π)；C→0 ⇒ λ/2（hairpin 无载锚）、
# C→∞ ⇒ λ/4 极限；f 随 C 单调下降。名义链 varactor_bpf_design（铁律 #1c：
# 全部综合精算——臂长=λg/2(f_unloaded=2.8GHz, εeff HJ)、名义偏置点
# C(f0=2.5GHz)→V(3.6342V)；耦合链纯 KJ（hairpin_design_from_order
# kgap_corrected=False）——同向 U 的 c(gap)/c(τ) 结构修正是 hairpin 真机
# 标定（W4④/B1），对变容管装载新族**预声明不转移**，待本族真机标定。
#
# 注册（2026-09-27，M-5）：七处同步——① docs/templates/varactor_bpf/meta.yaml；
# ② test_template_geometry_audit EXPECTED_TEMPLATES（56→57）；③ fake_adapter
# 派发（_varactor_bpf_sparams，主方程 f0(C(V)) + hairpin 耦合矩阵理想频响，
# 谷位随偏置等效伸缩）；④ _geometry_audit_helpers 三表（PORT_GROUPS/
# LUMPED_VALUE_PARAMS）；⑤ 计数/尾序消费钉（==57 九处、coax 尾钉、slotline
# 尾序钉）；⑥ 独立模板审计 test_varactor_bpf_template；⑦ 内核
# core/varactor.py + test_varactor。同对象注册（非拷贝）钉死单一事实源。


def _varactor_bpf_lines(p: dict[str, Any]) -> str:
    # 变容管调谐 BPF（M-5）：hairpin 同款 U 形 λg/2 谐振器阶梯阵列 + 抽头馈线；
    # 每 U 左臂开路端（y0 侧）接一只对地 lumped C(V)（ny=2 全隙盒 z 0→H_SUB，
    # combline c_load 惯用法）。C 字面量=C(V)−C_geo（2026-09-29 P2：盒区背景
    # 位移电流与 lumped 并联，#252 族扣除，core 单源 varactor_box_geo_
    # capacitance_pf）；抽头 τ 语义自 C 端计（loaded 廓线 branch B，P0 修复）。
    lay = _hairpin_layout(p)
    from rfauto.core.varactor import (
        abrupt_junction_capacitance_pf,
        varactor_box_geo_capacitance_pf,
    )

    cj0_pf = float(p.get("cj0_pf", VARACTOR_BPF_NOMINAL["cj0_pf"]))
    phi_v = float(p.get("phi_v", VARACTOR_BPF_NOMINAL["phi_v"]))
    bias_v = float(p.get("bias_v", VARACTOR_BPF_NOMINAL["bias_v"]))
    c_design_pf = abrupt_junction_capacitance_pf(bias_v, cj0_pf, phi_v)
    # 基板 er/h：render_script 注入（_sub_er/_h_sub_mm 通用键）；直调兜底缺省
    c_geo_pf = varactor_box_geo_capacitance_pf(
        lay["wf"] * 1e3, float(p.get("_h_sub_mm", _DEFAULT_SUB["h_mm"])),
        float(p.get("_sub_er", _DEFAULT_SUB["er"])))
    if c_design_pf <= c_geo_pf:
        raise ValueError(
            f"C(V)={c_design_pf:.6f}pF ≤ 盒几何寄生 C_geo={c_geo_pf:.6f}pF"
            "（bias_v 过高/盒过大——C_literal 不可为负，如实不可行不 clamp）")
    c_f = (c_design_pf - c_geo_pf) * 1e-12
    # 变容管装载盒坐标（渲染端展开逐腔字面——对象名 _vc1.._cN 可寻址，审计
    # exec 后可逐腔取属性查 C 值；combline c_load 同规）
    _vc_boxes = [(lay["xs"][2 * _i] - lay["wf"] / 2.0, lay["y0"],
                  lay["xs"][2 * _i] + lay["wf"] / 2.0,
                  lay["y0"] + lay["wf"])
                 for _i in range(lay["n"])]
    _vc_lines = "\n".join(
        f'_vc{k} = CSX.AddLumpedElement("varactor_c{k}", ny=2, caps=True,\n'
        f'                           C=VAR_C)\n'
        f'_vc{k}.AddBox(({x0!r}, {y0!r}, 0.0), ({x1!r}, {y1!r}, H_SUB),\n'
        f'               priority=10)'
        for k, (x0, y0, x1, y1) in enumerate(_vc_boxes, start=1))
    return f'''N = {lay["n"]}
WF = {lay["wf"]!r}                       # 谐振器/馈线宽（50Ω，HJ）
B = {lay["b"]!r}                         # U 内两臂中心距
LARM = {lay["l_arm"]!r}                  # 单臂长（展开 2·LARM+B=装载臂长）
Y0 = {lay["y0"]!r}                       # U 开路端 y（变容管装载端）
Y1 = {lay["y1"]!r}                       # 臂顶/弯带中心 y
YT = {lay["y_tap"]!r}                    # 输入抽头 y（自 C 端计 τ·L_tot，loaded
                                         # 廓线 branch B——P0 修复前注「自开
                                         # 路端计」系无载廓线旧语义 #154）
YT_OUT = {lay["y_tap_out"]!r}            # 输出抽头 y（末腔翻转时自其开路端
                                         # y1 向下计；右臂=真开路端锚定与输入
                                         # C 端锚定不等价——P1 交决策暂同 τ）
XS = {lay["xs"]!r}                       # 各谐振器 [左臂心, 右臂心]（m）
VAR_C = {c_f!r}                    # C_literal=C(V)−C_geo={c_design_pf:.4f}−{c_geo_pf:.4f}pF @ bias_v={bias_v!r}V（F；盒区背景位移电流并联 #252 族扣除）
varactor_bpf = CSX.AddMetal("varactor_bpf")
for _i in range(N):
    _xl = XS[2 * _i]
    _xr = XS[2 * _i + 1]
    varactor_bpf.AddBox((_xl - WF / 2, Y0, H_SUB),
                        (_xl + WF / 2, Y1, H_SUB), priority=10)
    varactor_bpf.AddBox((_xr - WF / 2, Y0, H_SUB),
                        (_xr + WF / 2, Y1, H_SUB), priority=10)
    varactor_bpf.AddBox((_xl - WF / 2, Y1 - WF / 2, H_SUB),
                        (_xr + WF / 2, Y1 + WF / 2, H_SUB), priority=10)
# 抽头馈线（T 形）：板边 x=∓BOARD → 首/末谐振器外臂中心（hairpin 同款）
varactor_bpf.AddBox((-BOARD, YT - WF / 2, H_SUB),
                    (XS[0], YT + WF / 2, H_SUB), priority=10)
varactor_bpf.AddBox((XS[-1], YT_OUT - WF / 2, H_SUB),
                    (BOARD, YT_OUT + WF / 2, H_SUB), priority=10)
# 变容管装载（M-5 半有源口径）：每 U 左臂开路端一只对地 lumped C(V)。
# 静态电容口径：FDTD 无时变 C——三档偏压=三次静态 run（各档 C 为常数）；
# ny=2 = z 向 shunt 对地惯用法（CheckNyDir 方向索引，#282），盒 z 跨基板
# 全隙 0→H_SUB（顶板接臂端金属、底板接 z-min PEC 地），combline c_load 先例。
# C_literal=C(V)−C_geo（2026-09-29 P2，#252 族）：引擎盒区背景位移电流与
# SetCapacity 集总电流并联 → 实感 C=字面量+C_geo=设计 C(V)（单源
# core/varactor.varactor_box_geo_capacitance_pf，平行板项 0.0788pF@名义）。
{_vc_lines}
# 去嵌（hairpin A1 同款）：测量面自板边推到抽头结前 10·NEAR+4·H_SUB
_port1 = MSLPort(CSX, port_nr=1, metal_prop=varactor_bpf,
                 start=np.array([-BOARD, YT + WF / 2, H_SUB]),
                 stop=np.array([XS[0], YT - WF / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(XS[0] + BOARD) - 10 * NEAR - 4 * H_SUB,
                 priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=varactor_bpf,
                 start=np.array([BOARD, YT_OUT - WF / 2, H_SUB]),
                 stop=np.array([XS[-1], YT_OUT + WF / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - XS[-1]) - 10 * NEAR - 4 * H_SUB,
                 priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in varactor_bpf.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


VARACTOR_BPF_NOMINAL: dict[str, Any] = {
    "order": 3,
    # 50Ω 馈/臂宽 = round(inverse_width(50, 2.5, rogers4350b), 4)（铁律 #1c）
    "w_mm": 1.1117,
    # 装载臂展开长 = λg/2(f_unloaded=2.8GHz, εeff=2.8578 HJ)=31.6675（4 位；
    # 无载谐振置于调谐带上沿，C 装载向下调谐——varactor_bpf_design 再生钉住）
    "arm_len_mm": 31.6675,
    # U 内两臂缝 3.0mm（hairpin 家族名义定版：k_self(3.0)≪互耦，pt1 实证）
    "arm_gap_mm": 3.0,
    # C13 N=3/RL20/FBW5% → k=0.051514 → 纯 KJ 反解 s=1.132829mm（4 位；
    # 同向 c(gap) 结构修正预声明不转移，见段头）
    "gap_mm": 1.1328,
    # Q_e=17.0689 → loaded 廓线抽头闭式 τ=0.330119（6 位；**自 C 端计** branch B，
    # βL@2.5GHz=2.8050，在臂上限 0.4351——2026-09-29 P0 修复：旧值 0.401892 系
    # hairpin 无载廓线闭式（βL=π），loaded 族电压节点恰扫过该位=外耦失配根因；
    # varactor_bpf_design 再生钉住，语义见 meta.param_semantics）
    "tap_frac": 0.330119,
    # 变容管模型（选型常数非实测；突变结闭式 core/varactor.py）
    "cj0_pf": 1.0,
    "phi_v": 0.9,
    # 名义偏置点：C(2.5GHz)=0.4455pF → V=3.6342V（主谐振方程+突变结反解）
    "bias_v": 3.6342,
}

VARACTOR_BPF_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（变容管调谐 BPF：三档偏压=三次静态"
                  " run 各自谷位；裁判=hairpin 耦合矩阵理想频响平移到 f0(C(V))"
                  "，主谐振方程 tan(βL)=−ωCZ0 同源闭式 core/varactor.py）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["order", "w_mm", "arm_len_mm", "arm_gap_mm", "gap_mm",
               "tap_frac", "cj0_pf", "phi_v", "bias_v"],
    "topology": "变容管调谐发夹线带通（M-5 首个半有源模板，hairpin 族增量）："
                "N 个 λg/2 级 U 形谐振器沿 x 并排、相邻外臂平行耦合（缝 "
                "gap_mm），每 U 左臂开路端对地并联一只 lumped C(V)（CSXCAD "
                "LumpedElement，ny=2 全隙盒）；输入/输出 50Ω 抽头馈线（T 形，"
                "板边 x=∓BOARD；单轴 x PML）",
    "param_semantics": "order=谐振器阶数 N（每腔一只变容管），w_mm=谐振器/馈线"
                       "宽（50Ω，skrf HJ 综合），arm_len_mm=装载臂展开中心线"
                       "总长（无载谐振 f_unloaded 的 λg/2；C 装载使工作点下移"
                       "——主谐振方程 tan(βL)=−ωCZ0，core/varactor.py 单源），"
                       "arm_gap_mm=U 内两臂缝（家族名义 3.0），gap_mm=相邻谐振"
                       "器耦合缝（fake/openEMS 同语义；纯 KJ 口径，结构修正预"
                       "声明不转移），tap_frac=输入抽头位置比例（loaded 廓线"
                       "闭式 τ，**自 C 端计** branch B——C 端与电压节点之间，"
                       "τ_node=1−π/(2βL)；#154 收口：与 hairpin 无载族「自"
                       "开路端计」同名不同义；输出抽头在无 C 臂、自真开路端"
                       "锚定，两锚不等价=P1 交决策暂同 τ 值），cj0_pf/phi_v="
                       "变容管突变结零偏电容（pF）/内建电位"
                       "（V，选型常数），bias_v=本次 run 的反偏电压（V）——"
                       "c_j0/φ/bias 三键只进 C 字面量不进导体几何"
                       "（LUMPED_VALUE_PARAMS 口径）",
    "static_c_note": "静态电容口径：FDTD 无时变 C——三档偏压=三次静态 run，"
                     "各档 C(V)=Cj0/√(1+V/φ) 在该档 bias_v 处为常数，调谐曲线"
                     "由多点静态解组成（CSXCAD LumpedElement .pyx 口径核实）；"
                     "C 字面量=C(V)−C_geo（2026-09-29 P2：盒几何寄生平行板项 "
                     "ε0·εr·WF²/H_SUB=0.0788pF 单源 core/varactor."
                     "varactor_box_geo_capacitance_pf——引擎盒区背景位移电流与 "
                     "lumped 并联，不扣则实感 C=C(V)+C_geo 频偏 #252 族；边缘"
                     "项欠估 ≤31% 如实预声明，见该函数 docstring）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "全部臂缘/弯带缘/抽头缘+变容管盒外 y 缘精确入网（#198）",
}


def varactor_bpf_meta() -> dict[str, Any]:
    """返回 varactor_bpf 模板元数据（与 template_meta("varactor_bpf") 同构）。"""
    meta = dict(VARACTOR_BPF_META)
    meta["template"] = "varactor_bpf"
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(VARACTOR_BPF_NOMINAL)
    return meta


# ── 注册（2026-09-27，M-5）：同对象入表（单一事实源；尾部追加 #247）──
TEMPLATE_META["varactor_bpf"] = VARACTOR_BPF_META
TEMPLATE_NOMINAL["varactor_bpf"] = VARACTOR_BPF_NOMINAL
