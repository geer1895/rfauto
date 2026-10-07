"""网格构建守卫（NEAR/BASE 近区网格点 + CFL dt/NrTS 预算链）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from . import _nominal_width  # 50Ω 标称线宽单源（XC-W，惰性：取属性才算）
from .registry import TEMPLATE_META
from .render_ratrace_cyl import ratrace_ring_mesh_k
from .render_tl import _gysel_layout


def _near_points(template: str, params: dict[str, Any],
                 base_mm: float = 0.4) -> tuple[list[float], list[float]]:
    """每模板走线边缘近场加密点（米；官方 NEAR=base/4 口径）。

    base_mm：网格 base（mm），仅 ratrace 分支消费——渲染半径 R/k(BASE) 与
    _ratrace_lines 同函数同 BASE，保证近场线与几何同 k；默认 0.4=离线审计档。
    """

    # 延迟族导入（AU-1 拆分）：_near_points 依赖各族 layout/_midlines；
    # 族模块顶层不回依赖本模块 → 仅调用期导入避免顶层循环（任务书许可）。
    from .render_antenna2 import (
        ANTENNA2_TEMPLATES,
        _ant2_layout,
    )
    from .render_array_eep import (
        ARRAY_TEMPLATES,
        EEP_TEMPLATES,
        _arr_layout,
        _eep_layout,
    )
    from .render_c3 import (
        C3_TEMPLATES,
        _c3_layout,
    )
    from .render_c4 import (
        _C4_COUPLER_TEMPLATES,
        _c4_gap_midlines,
        _c4_layout,
    )
    from .render_coupled_bpf import (
        _coupled_bpf_layout,
    )
    from .render_diplexer_ridged import (
        _diplexer_layout,
    )
    from .render_hairpin import (
        _hairpin_alt_layout,
        _hairpin_layout,
    )
    from .render_metasurface import (
        MS_UNIT_TEMPLATES,
    )
    from .render_msl_sma import (
        sma_launcher_layout,
    )
    from .render_phase_qwt import (
        _qwt_layout,
        _schiffman_layout,
    )
    from .render_ring import (
        RING_RESONATOR_GAP_MM,
        RING_RESONATOR_W_MM,
    )
    from .render_sicl_nway import (
        _nway_layout,
    )
    def edges(lo: float, hi: float, near: float) -> list[float]:
        return [lo - near / 2, hi + near / 2]

    nx: list[float] = [0.0]
    ny: list[float] = [0.0]
    if template == "wilkinson":
        w_in = float(params.get("shunt_w_mm", _nominal_width.W50_MM_R3)) * 1e-3
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
        if params.get("_gap_midline"):
            # X1 缝场网格加密旋钮（ge8 K-3 机制分离批，runs/ge8_k3mech/
            # criteria.md 预声明；缺省 False=不进本分支，近点集与渲染
            # 逐字节不变——缺省恒等由单测钉）：缝区 [-gap/2, +gap/2] 等分
            # 10 格（0.5mm 缝 → 0.05mm 格），内部线精确入网（#311 缝中点
            # 精确入网法推广；x=0 中线本就在近点集，此处补 ±0.05k 细分线，
            # 间隔全部 0.05mm ≥ 10µm 最小线距守卫 #349）。单变量口径：
            # 只加缝内 x 线——带缘/y/BASE/NEAR/激励/提取链逐项不变；
            # #368 口径：生效断言在最终网格上实测（test_gap_midline 审计）。
            _cl_half = cl_gap / 2.0
            nx += [-_cl_half + cl_gap * _i / 10 for _i in range(1, 10)]
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
        w = float(params.get("w_mm", _nominal_width.W50_MM_R3)) * 1e-3
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
    elif template == "hmsiw":
        # TA-8 hmsiw：藩篱三线对精确入网（#198：列心 w/2、孔缘 ±d/2，单列
        # x=+w/2）+ 开路边 x=−w/2 + 端口盒三向边（#283：盒边=结构线）——
        # 全部由 layout 单源给出（#349 最小间距守卫在 hmsiw_layout 内执行）
        lay = params.get("_hmsiw_layout")
        if lay is None:
            raise ValueError(
                "hmsiw _near_points: 缺 _hmsiw_layout（必须经 render_script "
                "渲染）")
        d = lay["d"]
        nx += [lay["w"] / 2 - d / 2, lay["w"] / 2, lay["w"] / 2 + d / 2,
               -lay["w"] / 2]
        ny += [lay["y1"] - lay["py"], lay["y1"], lay["y1"] + lay["py"],
               lay["y2"] - lay["py"], lay["y2"], lay["y2"] + lay["py"]]
        for _yk in lay["via_y"]:
            ny += [_yk - d / 2, _yk, _yk + d / 2]
    elif template == "inverted_ms":
        # TA-7 inverted_ms：条带缘精确入网（#198 mline 同口径）+ 线两端
        w = float(params.get("w_mm", 2.1359)) * 1e-3
        length = float(params.get("line_len_mm", 40.0)) * 1e-3
        nx += [-w / 2, w / 2]
        ny += edges(-length / 2, length / 2, 1e-3)             # 线两端（junction）
    elif template == "embedded_ms":
        # TA-11 embedded_ms（render_ta_wave_c 注册块，ge8d Wave D 席 D2）：
        # 条带缘精确入网（#198 mline/inverted_ms 同口径）+ 线两端
        w = float(params.get("w_mm", 1.0014)) * 1e-3
        length = float(params.get("line_len_mm", 40.0)) * 1e-3
        nx += [-w / 2, w / 2]
        ny += edges(-length / 2, length / 2, 1e-3)             # 线两端（junction）
    elif template == "xcheb_bpf4":
        # TA-14 开路环四重奏（render_ta_wave_c 注册块）：全部环边/开缝缘/
        # 馈线缘精确入网（#198，layout 单源）+ 四耦合缝中线（#311，cpw pt4
        # 同源——缝下场主导 εeff/耦合精度）
        lay = params.get("_xcheb_layout")
        if lay is None:
            raise ValueError(
                "xcheb_bpf4 _near_points: 缺 _xcheb_layout（必须经 "
                "render_script 渲染）")
        wf = lay["wf"]
        h_r = lay["h_r"]
        for _cx, _cy in lay["cen"]:
            nx += [_cx - h_r, _cx - h_r + wf, _cx + h_r - wf, _cx + h_r]
            ny += [_cy - h_r, _cy - h_r + wf, _cy + h_r - wf, _cy + h_r]
        for _b in lay["feeds"]:
            ny += [_b[1], _b[3]]                    # 馈线缘（x=−BOARD 板边入）
        for _gx, _gy in lay["gap_mids"]:
            if _gx is not None:
                nx += [_gx]
            if _gy is not None:
                ny += [_gy]
    elif template == "fgcpw":
        # TA-9 fgcpw：六条带/地缘精确入网（带缘 ±w/2、地内/外缘
        # ±(w/2+gap)/±(w/2+gap+gnd)，cpw #198 口径推广）+ 缝中线加密
        # （cpw pt4 同源：εeff 由缝场主导）
        w = float(params.get("w_mm", 4.3466)) * 1e-3
        gap = float(params.get("gap_mm", 0.2)) * 1e-3
        gnd = float(params.get("gnd_mm", 4.0)) * 1e-3
        length = float(params.get("line_len_mm", 40.0)) * 1e-3
        nx += [-w / 2, w / 2, w / 2 + gap, -(w / 2 + gap),
               w / 2 + gap + gnd, -(w / 2 + gap + gnd)]
        nx += [w / 2 + gap / 2, -(w / 2 + gap / 2)]
        ny += edges(-length / 2, length / 2, 1e-3)             # 线两端（junction）
    elif template == "isl_shielded":
        # TA-10 ISL（render_ta_wave_b 注册块，ge8b Wave B 席 B9）：条带缘
        # + 藩篱三线对精确入网（hmsiw #198/#283 同口径，layout 单源）
        lay = params.get("_isl_layout")
        if lay is None:
            raise ValueError(
                "isl_shielded _near_points: 缺 _isl_layout（必须经 "
                "render_script 渲染）")
        nx += [-lay["w"] / 2, lay["w"] / 2,
               lay["wall_x"] - lay["d"] / 2, lay["wall_x"],
               -(lay["wall_x"] - lay["d"] / 2), -lay["wall_x"]]
        ny += edges(-lay["y_half"], lay["y_half"], 1e-3)   # 线两端（junction）
        for _yk in lay["via_y"]:
            ny += [_yk - lay["d"] / 2, _yk, _yk + lay["d"] / 2]
    elif template == "vivaldi_tsa":
        # AP-11 Vivaldi（render_ta_wave_b 注册块）：特征线入网——喉部槽缘/
        # 口面槽缘/馈线缘（#198；阶梯化站缘不入网：站间宽度差 <NEAR 会把
        # SmoothMeshLines 推入 Unique O(N²) 重细化（实测 250k 线+死循环，
        # 2026-10-03 本席实测），站缘几何由 BASE 网格解析、审计①只查盒内
        # 有线，槽宽跳变精度由阶梯化站距（l/24≈3.3mm）承担）
        from .render_ta_wave_b import vivaldi_layout

        lay = vivaldi_layout(params)
        # 注意 _ant2_layout 族布局为 mm 口径——近场线一律 *1e-3 转米
        # （缺转换时 y 平滑要填 ±40"米"@NEAR=0.1mm → 25 万线级爆炸/死循环，
        # 2026-10-03 本席实测；#140 单位口径家族）
        hw0 = lay["stations_hw"][0] * 1e-3
        feed_w = lay["feed_w"] * 1e-3
        nx += [0.0, -feed_w / 2, feed_w / 2,
               -hw0, hw0, -lay["stations_hw"][-1] * 1e-3,
               lay["stations_hw"][-1] * 1e-3]
        # 站缘 y 向精确入网（审计①每站盒内须有线；站距 l/24≈3.3mm，单位
        # 修正后线量 benign）
        ny += [y * 1e-3 for y in lay["stations_y"]]
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
        w1 = float(params.get("w1_mm", _nominal_width.W50_MM)) * 1e-3
        w2 = float(params.get("w2_mm", 1.897)) * 1e-3
        length = float(params.get("line_len_mm", 40.0)) * 1e-3
        nx += [-w1 / 2, w1 / 2, -w2 / 2, w2 / 2]   # 两段带缘精确入网（#198）
        ny += edges(-length / 2, length / 2, 1e-3)   # 线两端；阶跃=默认 0.0
    elif template == "tjunc":
        wf = float(params.get("w_feed_mm", _nominal_width.W50_MM)) * 1e-3
        tl = float(params.get("through_len_mm", 25.0)) * 1e-3
        bl = float(params.get("branch_len_mm", 20.0)) * 1e-3
        # 三臂带缘+结点角精确入网（#198）：主线带缘/端点、支臂带缘/端点
        nx += [-wf / 2, wf / 2, bl]
        ny += [-tl, tl, -wf / 2, wf / 2]
    elif template == "bend":
        w = float(params.get("w_mm", _nominal_width.W50_MM)) * 1e-3
        a = float(params.get("arm_len_mm", 20.0)) * 1e-3
        nx += [-w / 2, w / 2, a]          # 臂1带缘 + 臂2端点
        ny += [-a, -w / 2, w / 2]         # 臂1端点 + 臂2带缘；弯角=默认 0
    elif template == "via":
        w = float(params.get("w_mm", _nominal_width.W50_MM)) * 1e-3
        ap = float(params.get("antipad_mm", 0.8)) * 1e-3
        nx += [-w / 2, w / 2, -ap, ap]    # 顶带缘 + 反焊盘方边（x）
        ny += [-ap, ap]                   # 反焊盘方边（y）
    elif template == "atten_pi":
        w = float(params.get("w_mm", _nominal_width.W50_MM)) * 1e-3
        d = float(params.get("shunt_off_mm", 6.0)) * 1e-3
        g = 0.5 * 1e-3                    # 串臂断口半长/元件盒半宽（mm→m）
        nx += [-w / 2, w / 2, -g / 2, g / 2]          # 带缘 + shunt 盒 x 边
        ny += [-d - g / 2, -d + g / 2, -g, g,
               d - g / 2, d + g / 2]                  # shunt 盒 y 边 + 串臂断口
    elif template == "atten_t":
        w = float(params.get("w_mm", _nominal_width.W50_MM)) * 1e-3
        d = float(params.get("shunt_off_mm", 6.0)) * 1e-3
        g = 0.5 * 1e-3
        nx += [-w / 2, w / 2, -g / 2, g / 2]          # 带缘 + shunt 盒 x 边
        ny += [-d - g / 2, -d + g / 2, -g, g,
               d - g / 2, d + g / 2]                  # shunt 盒 y 边 + 串臂断口
    elif template == "ratrace":
        wf = float(params.get("w_feed_mm", _nominal_width.W50_MM)) * 1e-3
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
    elif template == "varactor_bpf":
        # M-5 变容管调谐 BPF：hairpin 同款臂/弯带/抽头缘 + 变容管装载盒
        # 外 y 缘（y0+wf；x 缘=臂缘已含；z 缘 0/H_SUB 在基板网格内）精确入网
        # （#198 精确入网；几何单源 _hairpin_layout，C 值只进 LumpedElement
        # 字面量不进几何——审计 LUMPED_VALUE_PARAMS 口径）
        lay = _hairpin_layout(params)
        _wf = lay["wf"]
        for _i in range(lay["n"]):
            _xl, _xr = lay["xs"][2 * _i], lay["xs"][2 * _i + 1]
            nx += [_xl - _wf / 2, _xl + _wf / 2, _xr - _wf / 2, _xr + _wf / 2]
            ny += [lay["y0"] + _wf]
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
        wm = float(params.get("w_msl_mm", _nominal_width.W50_MM)) * 1e-3
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
    elif template == "ring_resonator":
        # §F-A M3 环形谐振器：环带基点缘（y≈0 行左右缘 + x=0 列上下缘）、
        # 馈线带缘、馈端/缝缘精确入网 + 缝中线入网（#198/#311；派生量与
        # _ring_resonator_lines 同式同字面）
        w = float(params.get("w_mm", RING_RESONATOR_W_MM)) * 1e-3
        fw = float(params.get("feed_w_mm", RING_RESONATOR_W_MM)) * 1e-3
        gap = float(params.get("gap_mm", RING_RESONATOR_GAP_MM)) * 1e-3
        rm = float(params.get("r_mean_mm", 11.299802692199101)) * 1e-3
        r_out = rm + w / 2
        r_in = rm - w / 2
        nx += [-r_out, -r_in, r_in, r_out]      # 环带左右基点缘（y≈0 行）
        ny += [-r_out, r_out]                    # 环带上下基点缘（x=0 列）
        ny += [-r_out - gap, -r_out - gap / 2, r_out + gap / 2, r_out + gap]
        # 馈端面 + 缝中线（#311 缝内内部线 ≥1）+ 馈线带缘（端口面解析）
        nx += [-fw / 2, fw / 2]
    elif template == "schiffman":
        # TA-1 Schiffman 移相器：耦合缝中线（缺省 nx[0]=0 即缝中线 #311）+
        # 耦合对四带缘/桥带缘/段两端/参考段两端/参考带缘精确入网（#198；
        # 近场线由 layout 单源给出——ms_unit_layout 同制度）
        lay = _schiffman_layout(params)
        nx += lay["near_x"]
        ny += lay["near_y"]
    elif template == "qwt_multisection":
        # TA-2 多节 λ/4 变换器：馈线/各节带缘 + 节间 junction + 端接盒缘
        # 精确入网（#198；近场线由 layout 单源给出）
        lay = _qwt_layout(params)
        nx += lay["near_x"]
        ny += lay["near_y"]
    elif template == "sicl":
        # TA-3 SICL（render_sicl_nway 文末注册块）：条带缘/过孔墙三线对
        # （列心±d/2、列心）/条带两端/端口面精确入网（#198；全部由
        # sicl_layout 单源给出，#349 最小间距地板在 layout 内执行）
        lay = params.get("_sicl_layout")
        if lay is None:
            raise ValueError(
                "sicl _near_points: 缺 _sicl_layout（必须经 render_script 渲染）")
        d = lay["d"]
        nx += [lay["w"] / 2, -lay["w"] / 2,
               lay["a"] / 2 - d / 2, lay["a"] / 2, lay["a"] / 2 + d / 2,
               -(lay["a"] / 2 - d / 2), -lay["a"] / 2,
               -(lay["a"] / 2 + d / 2)]
        ny += [lay["y0"], lay["y1"]]
        for _yk in lay["via_y"]:
            ny += [_yk - d / 2, _yk, _yk + d / 2]
    elif template == "nway_wilkinson":
        # TA-4 N-way 树形功分器：全部盒缘（T 条/臂/支线/电阻盒）+ 输入/
        # 输出馈线带缘精确入网（#198；近场线由 _nway_layout 单源给出，
        # 共享缘已去重、#349 地板在 layout 内执行）
        lay = _nway_layout(params)
        nx += lay["near_x"]
        ny += lay["near_y"]
    elif template == "diplexer":
        # TA-5 Diplexer（render_diplexer_ridged 文末注册块）：馈线/T 条/
        # 双臂带缘 + 元件断口缘精确入网（#198；近场线由 _diplexer_layout
        # 单源给出）
        lay = _diplexer_layout(params)
        nx += lay["near_x"]
        ny += lay["near_y"]
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


# ── F-D NrTS/EndCriteria 接线（wf:nrts-fix，#262 截断族修复面）──────────────
# 根因缺口（runs/fd_rerun_20260927/seat2_truncation_verdict 判读）：TEMPLATE_
# META.max_time_ns 早已声明（墙钟上界语义，#328）但渲染链从未消费——四 F-D
# 模板缺省 NrTS=100000/不设 EndCriteria，patch_array_series 在 11.5ns 窗内
# 4.88GHz 长寿命储能只衰减到幅值 14%（尾/峰 0.1414）即被切，max|S|=5.65 非物理。
# 接线口径（缺省行为**仅对下列四模板变化**；其他模板逐字节不变有钉）：
#   NrTS = ceil(NRTS_DT_SAFETY·max_time_ns/dt_cfl)：dt_cfl 在生成脚本内 Run 前
#   按终网格三轴最小间距 CFL 实算（#328），SetNumberOfTimeSteps（官方 setter）
#   覆写构造占位；EndCriteria 显式 −60dB（END_CRITERIA_FD=1e-6，#266 口径）。
# 显式 _nrts/_end_criteria 旋钮仍最高优先（c3 先例 #266）；安全余量 1.1 盖
# #312 CFL 估-实测漂（0.93–1.07），宁长勿截。
NRTS_MAX_TIME_TEMPLATES: frozenset[str] = frozenset({
    "patch_array_series", "patch_eep_1x4", "ifa", "ms_array_NxN"})
NRTS_MAX_TIME_FALLBACK_NS = 30.0  # META 缺 max_time_ns 声明时的回退（公约缺省）
END_CRITERIA_FD = 1e-6            # −60dB 能量判据（10^(−60/10)；#266 口径）
NRTS_DT_SAFETY = 1.1              # CFL 估-实测漂移余量（#312）
_C_LIGHT_MS = 299792458.0         # 真空光速 m/s（生成脚本内 CFL dt 自包含用）


def cfl_dt_s(dx_min: float, dy_min: float, dz_min: float) -> float:
    """FDTD CFL 稳定性时间步（秒）：dt=1/(c·√(1/dx²+1/dy²+1/dz²))。

    纯函数（wf:nrts-fix）；生成脚本内联公式与此镜像，test_nrts_wiring 以
    exec 渲染脚本实测 _dt_cfl 回算互证（#212 离线审计口径）。
    """
    vals = (float(dx_min), float(dy_min), float(dz_min))
    for v in vals:
        if not v > 0:
            raise ValueError(f"cfl_dt_s: 网格最小间距须 >0，得 {v!r}")
    return 1.0 / (_C_LIGHT_MS * math.sqrt(
        1.0 / vals[0] ** 2 + 1.0 / vals[1] ** 2 + 1.0 / vals[2] ** 2))


def nrts_from_max_time_ns(max_time_ns: float, dt_s: float) -> int:
    """max_time_ns→NrTS 换算纯函数：NrTS=ceil(NRTS_DT_SAFETY·T/dt)（#328）。

    max_time_ns 是墙钟上界语义（TEMPLATE_META 公约），dt_s 按终网格实测或
    CFL 保守估；安全余量 NRTS_DT_SAFETY 盖估-实测漂移，宁长勿截。
    """
    t_ns = float(max_time_ns)
    dt = float(dt_s)
    if not t_ns > 0 or not dt > 0:
        raise ValueError(
            f"nrts_from_max_time_ns: max_time_ns/dt_s 须 >0，得 {t_ns!r}/{dt!r}")
    return math.ceil(NRTS_DT_SAFETY * (t_ns * 1e-9) / dt)


def _fd_nrts_defaults(template: str, params: dict[str, Any]) -> float | None:
    """F-D 缺省接线判定单源（render_script 与 ms_array_render 各沿自身路径
    恰调一次；render_script 对 PORTLESS_TEMPLATES 早分发不调，见调用点注释）。

    四 F-D 模板且 _nrts/_end_criteria 两旋钮均未显式传入时：给 params 补
    _end_criteria=END_CRITERIA_FD（走既有 _end_criteria 机制进 FDTD 构造行）
    并返回 max_time_ns（NrTS 终网格折算用）；否则返回 None 且 params 零改动
    （非 F-D 模板/显式旋钮路径逐字节不变）。
    """
    if (template in NRTS_MAX_TIME_TEMPLATES
            and "_nrts" not in params and "_end_criteria" not in params):
        params["_end_criteria"] = END_CRITERIA_FD
        return float(TEMPLATE_META.get(template, {}).get("max_time_ns")
                     or NRTS_MAX_TIME_FALLBACK_NS)
    return None


def _fd_nrts_override_block(max_time_ns: float) -> str:
    """生成 Run 前 NrTS 终网格折算块（wf:nrts-fix；注入主/MS 渲染脚本）。

    与 cfl_dt_s/nrts_from_max_time_ns 公式镜像（互证钉在 test_nrts_wiring）；
    nrts_meta.json best-effort 落盘（#105）供 fd_oe_campaign nrts_converged
    门与离线审计消费（引擎日志 Max.number-of-timesteps 为覆写后真值的第二证）。
    """
    t_s = repr(float(max_time_ns)) + "e-09"   # 干净字面量（30.0e-09，非长尾浮点 repr）
    safety = repr(NRTS_DT_SAFETY)
    c = repr(_C_LIGHT_MS)
    return (
        "# ── NrTS 按 TEMPLATE_META.max_time_ns 终网格 CFL 折算"
        "（wf:nrts-fix，#262/#328 口径）──\n"
        "# dt=1/(c·√(Σ 1/dmin²))（终网格三轴最小间距）；NrTS=ceil(" + safety
        + "·T/dt)（1.1=#312 估-实测漂余量，宁长勿截）；\n"
        "# SetNumberOfTimeSteps=官方 setter（构造占位后 Run 前覆写）。\n"
        "_fd_min_d = {ax: float(np.min(np.diff(np.asarray(\n"
        "    mesh.GetLines(ax), dtype=float)))) for ax in ('x', 'y', 'z')}\n"
        "_dt_cfl = 1.0 / (" + c + " * float(np.sqrt(sum(\n"
        "    1.0 / _fd_min_d[ax] ** 2 for ax in ('x', 'y', 'z')))))\n"
        "_nrts_fd = int(np.ceil(" + safety + " * " + t_s + " / _dt_cfl))\n"
        "FDTD.SetNumberOfTimeSteps(_nrts_fd)\n"
        "# nrts_meta.json 只随真跑落盘（真跑脚本名恒 simulation.py：campaign/\n"
        "# adapter 同名）；离线审计 exec 的 _*_sim.py 假名不写（防测试污染根目录，\n"
        "# #144 族）。\n"
        "if os.path.basename(__file__) == 'simulation.py':\n"
        "    try:\n"
        "        with open(os.path.join(\n"
        "                os.path.dirname(os.path.abspath(__file__)),\n"
        "                'nrts_meta.json'), 'w', encoding='utf-8') as _nj:\n"
        "            __import__('json').dump({'nrts_declared': _nrts_fd,\n"
        "                                     'dt_cfl_s': _dt_cfl,\n"
        "                                     'max_time_ns': "
        + repr(float(max_time_ns)) + ",\n"
        "                                     'end_criteria': "
        + repr(END_CRITERIA_FD) + "}, _nj)\n"
        "    except Exception:\n"
        "        pass\n")
