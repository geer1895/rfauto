"""槽线族（slotline/slotline_lumped/msl_slot_transition/marchand + marchand2）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from .registry import _DEFAULT_SUB, TEMPLATE_META, TEMPLATE_NOMINAL

# ══ 槽线族正式注册（2026-09-18 w1b，排空六轮 followUps ④/0df②/0dl①；审计 #12/#17）══
# 路线 A/B 均匀槽线段（真机三门 PASS，（二百）、MSL↔slot 过渡
# 与 Marchand 双槽臂（真机判读 ）由附加模块升格正式注册——渲染入口
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
    。"""
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
                  "视入阻抗（文件模式 U/I 度量常数 γ≈2.71，坑 B）；"
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
                "机制）——真 Marchand=两节对称耦合段（电路级综合 "
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
# 本身的登记归因对照=过孔 PEC 薄片单变量**（TODO 排空五轮段/（二百五十
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
    # 激励盒内缩守卫（#253 单源 raise 型，审查 R4-2；渲染期 Python 侧——
    # 只校验不改几何，生成脚本字节不变）。内缩与脚本内 excite_inset_ge2base
    # 审计键同式：X_E−(−XDOM)+10·NEAR = PORT_CLEAR+10·NEAR（PORT_CLEAR=14·BASE、
    # NEAR=BASE/4，BASE 公式同下文 L428 渲染式——两处公式任一改动必须同步，
    # 审计/求解同参口径 #368）
    import math as _math

    from rfauto.core.slotline_transitions import MARCHAND2_NOMINAL_INPUTS

    from .inset_guard import assert_excitation_inset

    _base_m = (299792458.0
               / (float(base_anchor_f_hi_hz)
                  * _math.sqrt(MARCHAND2_NOMINAL_INPUTS["er"])) / 50.0)
    _inset_m = 14.0 * _base_m + 10.0 * (_base_m / 4.0)
    assert_excitation_inset(_inset_m, _base_m,
                            label="marchand2 激励盒→−x 域边内缩")
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
