"""Coupled-line 定向耦合器——声明式 EDB spec 发射器（数据集 EDB 快车道）。

拓扑：两条 λ/4 平行耦合微带线（后向波定向耦合器，与 openEMS 注册模板
``oe_templates/render_c4.py`` cline_coupler 同布局口径；Pozar《Microwave
Engineering》4th ed. §7.6）+ 四条 50Ω 馈线沿水平引出（耦合线竖直、馈线
水平，全部轴对齐两点线段）::

      P2(直通) ←── feed_p2 ──┤         ├── feed_p4 ──→ P4(隔离)
                             │         │
                          line_a    line_b     （λ/4 平行耦合段，
                             │  s    │           线宽 w / 缝 s = KJ 反解）
                             │         │
      P1(输入) ←── feed_p1 ──┤         ├── feed_p3 ──→ P3(耦合)

端口语义（后向波耦合器，与注册模板 cline_coupler 一致）：P1=输入（线 A
近端）、P2=直通（线 A 远端）、P3=耦合（线 B 近端，与输入同侧）、P4=隔离
（线 B 远端）；**线 A/线 B DC 隔离**（耦合经缝隙分布耦合、无直流通路=
器件物理，见下方"族特异性 schema 豁免 2"）。

尺寸全部由综合闭式/既有内核产出（禁止手抄毫米数 #252）：
  - (Z0e, Z0o, C)：Pozar §7.6 闭式（注册模板 render_c4.coupled_line_zee_zoo
    同式）C=10^(−C_dB/20)、Z0e=Z0√((1+C)/(1−C))、Z0o=Z0√((1−C)/(1+C))，
    匹配条件 Z0e·Z0o=Z0² 由构造保证；
  - (w, s)：``oe_templates.closedform.coupled_bpf_width_gap_from_zee_zoo``
    （Kirschning-Jansen 1984 准静态二维反解——注册 cline_coupler/lange/
    coupled_bpf 三模板同款内核）；
  - εeff_e/εeff_o：``core.coupled_microstrip.coupled_microstrip_even_odd_ohm``
    （KJ 正向回代）；耦合段长 lc = λ/4 @ (εeff_e+εeff_o)/2（微带耦合段
    平均 εeff 口径，注册模板同式同常数 c=299.792458 mm·GHz）；
  - w_feed：solve_microstrip(Z0)（本族 stackup 标量单源，与
    nominal_width_mm(50,...) 逐位一致，branchline 家族同款——注册设计链
    内 inverse_width 用 tanδ=0 裸 Stackup，与单源差 ~2e-3mm 二阶，族内
    以单源为准）。
  KJ 整链与注册模板设计函数 ``cline_coupler_design`` 逐值一致（同函数同
  参），由 tests/unit/test_edb_templates_ext.py 钉 1e-9。

族特异性 schema 豁免（本发射器声明并过滤，schema.py 正本逻辑不改动）：
  1. template 白名单：schema.KNOWN_TEMPLATES 未扩（本席只许追加 schema.py
     docstring），validate_spec 的 "template 非法" 行由发射器侧过滤；白名
     单升格（KNOWN_TEMPLATES + edb_lane_service 分派表接线）为 followUp。
  2. 连通图两分量：线 A/B DC 隔离是耦合线耦合器的器件物理（见上），
     validate_spec 的单连通审计对本族豁免——发射器侧过滤该行；分量结构
     恰为 {line_a, feed_p1, feed_p2} / {line_b, feed_p3, feed_p4} 两组、
     组内全连通由测试钉住。

几何口径声明（二阶效应，如实记录）：馈线内端与耦合线端部按 w/2×wf/2
矩形面积重叠保证连通（flat cap 口径），使有效耦合段较 lc 名义值长约
wf/2（≈0.56mm/λ/4≈3%）；两近端馈线端面隔 d=w+s 相对（端射缝隙并联于
主耦合路径，fF 级）。二者与注册 openEMS 版式（馈线外推+横向搭接段）的
端部不连续同类，冒烟判读按引擎偏差项对待，不进闭式裁判。

生产判读档史（W8 仲裁建议 1 → W10 定谳回退，2026-10-09）：W8 真机三变体
仲裁（runs/edblane85/w8_cl_arb/ARBITRATION.md §3/§5-1）曾裁定本族缺省自
适应档 ``adapt.max_delta`` 从 schema 假设 8 通用缺省 0.02 **加严到
0.005**——依据=名义设计点紧缝 s/h=0.161（s=0.082mm/h=0.508mm）下
ΔS=0.02 单档 S31 读数带 ~2dB 收敛档伪象（HFSS 3D 与 EDB 两引擎 0.02 档
一致读 -7.2~-7.6dB，HFSS ΔS 阶梯 0.02→0.0025 收紧回收 1.2~1.8dB；0.02
档的窗口判据在测"网格收敛度"而非"器件物理"）。

**W10 定谳与本档回退（runs/edblane85/w10_cl_recheck/REPORT.md）**：
MaxDelta=0.005 在 EDB 路径**写入不可达**——EDB 3D Layout schema
（SimSetupID=19）无 MaxDelta 键（四互证维持：EditSetup 不存在/InsertSetup
无任何 Delta 键名/configuration.load 的 AdaptiveSettings 子树被丢弃/两代
工程盘面均无 MaxDelta 键），spec 硬断言只能行使到**发射面**；W9 重查
props 通道"写入不传播"（TIGHTENING_NOT_EFFECTIVE，会话内读回确认后批解
仍按 0.02 准则停机）系同一 schema 无键总因的会话态表现。且 W10 量级修
正：EDB 侧档位伪象实测仅 **~0.62dB**（W8 的 ~2dB 系 HFSS 侧阶梯分解，
不按面值转移 EDB），剩余 ~1.0dB 偏置=EDB-Layout 特有建模保真差（判读面
校准项，非求解旋钮可及）。缺省保留 0.005"请求档"=每个 EDB 工程携带一
个求解器证明不可消费的档位（verify_adapt_tightening 每建必告警、存证值
误导归因、pyedb/AEDT 修复后还会静默激活 4× 加严档）——按 #122 不虚报
原则**回退 0.02**（与本通道求解器实际准则一致）。EDB 侧唯一可达收紧通
道=扁平键 ``MinConvergedPasses``（类路径 InsertSetup，求解器实消费：W9
mc2=2 / W10=4 两真机点）。**复进条件**：pyedb/AEDT 暴露 MaxDelta 写入
口后，按 W8 仲裁依据显式重立本族加严档（禁靠常量静默生效）；复进前本
族 EDB S31 读数不得按 0.005 档归因，判读面校准锚=W10 REPORT §3（保真差
~+1.0dB）。branchline/power_divider/ratrace 等他族维持 0.02 通用缺省
（假设 8）不动（模板作用域分派，#274 家法）。

厚度偏置声明（W8 仲裁建议 3，2026-10-09；HFSS=对齐基准）：KJ 综合
为零厚口径——零厚全波饱和档验证 -9.772 vs KJ 预测 -10.00（残差
0.23dB，综合无需修正）；有限铜厚实体在 s/t（缝/铜厚比）<4 区产生
已知厚度偏置（方向=过耦，饱和锚 +0.8dB@s/t=2.34——名义 10dB 设计
点 s=0.082/t=0.035 落此区），发射器以 spec.params["thickness_bias_note"]
渲染期注记声明、**不改综合数值**；s/t≥4 暂按「伪象主导区」划线
（W8 实测 bias+2.274dB@s/t=4.29 属 ΔS 收敛档伪象主导、非纯厚度，
厚度效应量值未分辨）——守卫仅 warning 不 fail（数据不足硬门，#122）。
W10 真机补证（runs/edblane85/w10_cl_recheck §3）：名义点（s/t=2.34）
方向支持厚度偏置、无反证，但 s/t≥4 区量级仍未分辨（W10 未测该区），
划线维持暂定。证据链：runs/edblane85/w8_cl_arb/ARBITRATION.md §3/§5-3。

纯函数：``emit_coupled_line_spec(params) -> (spec, config_json)``，无 IO
无全局态；spec/config schema 与假设清单见 edb_templates/schema.py docstring。
"""

from __future__ import annotations

import math
import warnings
from typing import Any

from rfauto.adapters.edb_templates.schema import (
    DEFAULT_BOARD_MARGIN_MM,
    DEFAULT_COPPER_THICKNESS_MM,
    SPEC_SCHEMA_VERSION,
    assemble_config,
    board_from_traces,
    build_spec_stackup,
    make_trace,
    make_wave_port,
    resolve_stackup,
    solve_microstrip,
    validate_spec,
)
from rfauto.adapters.oe_templates.render_c4 import cline_coupler_design

# __all__ 不动（public_api 金快照只收 __all__ 面；DEFAULT_ADAPT_MAX_DELTA
# 以模块常量形态供测试/调用方按模块路径导入——金快照纯增量需 --generate
# 评审动作，超本席文件面）
__all__ = ["DEFAULT_COUPLING_DB", "DEFAULT_FEED_LEN_MM", "emit_coupled_line_spec"]

#: 缺省耦合度 dB（10dB 耦合器=注册 cline_coupler 名义设计点同款）
DEFAULT_COUPLING_DB = 10.0

#: 缺省馈线长度 mm（与 branchline 发射器 DEFAULT_FEED_LEN_MM 同口径）
DEFAULT_FEED_LEN_MM = 5.0

#: 本族 adapt.max_delta 缺省=schema 假设 8 通用缺省 0.02（**W10 定谳回退**，
#: 2026-10-09）：W8 仲裁曾加严 0.005，但 EDB 3D Layout schema 无 MaxDelta
#: 键=写入不可达（runs/edblane85/w10_cl_recheck 四互证；W9 props 通道
#: TIGHTENING_NOT_EFFECTIVE 系同因会话态表现），且 EDB 侧档位伪象实测仅
#: ~0.62dB（W8 ~2dB 系 HFSS 侧阶梯分解）、剩余 ~1.0dB=EDB-Layout 建模保
#: 真差——0.005 请求档求解器不消费，保留即每建必告警+存证误导归因，故
#: 回退到与求解器实际准则一致的 0.02。复进条件=pyedb/AEDT 暴露 MaxDelta
#: 写入口后按 W8 依据显式重立（禁静默激活）；EDB 侧可达收紧通道=
#: MinConvergedPasses 扁平键（求解器实消费）。显式覆盖走
#: params["adapt"]["max_delta"]；他族维持 0.02 不动（模板作用域分派）。
DEFAULT_ADAPT_MAX_DELTA = 0.02

#: s/t（缝/铜厚比）厚度偏置区划线（W8 仲裁建议 3 阈值，2026-10-09）：
#: s/t<4=已知厚度偏置区（锚 +0.8dB@s/t=2.34，见 :data:`THICKNESS_BIAS_ANCHOR_DB`）；
#: s/t≥4=「伪象主导区」暂划线（V3 实测 bias+2.274dB@s/t=4.29 属 ΔS 收敛档
#: 伪象主导、非纯厚度，厚度效应量值未分辨）——守卫仅 warning 不 fail
#: （数据不足硬门，#122）。W10 名义点（s/t=2.34）方向支持厚度偏置、无反
#: 证；s/t≥4 区量级仍未分辨，划线维持暂定（runs/edblane85/w10_cl_recheck）。
THICKNESS_BIAS_ST_DIVIDER = 4.0

#: 厚度偏置饱和锚点 dB（HFSS 匹配档阶梯差随收紧趋稳 +0.80@饱和；
#: HFSS=对齐基准——名义 10dB 设计点 s/t=2.34 的有限厚偏差声明值，
#: 方向=过耦；渲染期注记不改综合数值）
THICKNESS_BIAS_ANCHOR_DB = 0.8

#: 厚度偏置锚点 s/t 值（名义 10dB 设计点 s=0.082mm / 铜 0.035mm）
THICKNESS_BIAS_ANCHOR_ST = 2.34

#: 本族 validate_spec 豁免行前缀（发射器侧过滤，理由见模块 docstring 豁免 1/2）
_FAMILY_VALIDATE_EXEMPT_PREFIXES = (
    "template 非法:",       # 白名单升格 followUp（豁免 1）
    "走线连通图非单连通",    # 线 A/B DC 隔离=器件物理（豁免 2）
)


def emit_coupled_line_spec(
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Coupled-line 耦合器发射器：设计参数 dict → (spec dict, config_json dict)。

    Args:
        params: 设计参数。
            - ``f0_ghz``（必填，>0）：中心频率。
            - ``coupling_db``（缺省 10.0）：耦合度 C_dB（>0，电压耦合系数
              C=10^(−C_dB/20)；过紧耦合超出 KJ 零厚可达域时综合链报错）。
            - ``z0_ohm``（缺省 50.0）：系统阻抗；仅支持 50（假设 3）。
            - ``stackup``（缺省 rogers4350b_h0.508 标量，假设 7）。
            - ``feed_len_mm``（缺省 5.0）：四条 50Ω 馈线长。
            - ``copper_thickness_mm``（缺省 0.035）/ ``board_margin_mm``
              （缺省 2.0）。
            - ``sweep``：缺省 [0.7,1.3]·f0、401 点 interpolation（假设 8，
              同 branchline）。
            - ``adapt``：单频 f0 自适应、max_passes 缺省 20（假设 8）；
              max_delta 缺省 0.02=schema 通用缺省（**W10 定谳回退**——W8 曾
              裁定本族加严 0.005，但 EDB 路径 MaxDelta 写入不可达且 EDB 侧
              档位伪象实测仅 ~0.62dB，见 :data:`DEFAULT_ADAPT_MAX_DELTA`
              注释与模块 docstring"生产判读档史"节），
              可显式覆盖（``adapt: {"max_delta": ...}``）。

    Returns:
        (spec, config_json) 二元组；config_json 为 PyEDB
        ``edb.configuration.load()`` 兼容 dict。内部 validate_spec 自检
        （族豁免见模块 docstring），其余失败抛 ValueError。spec.params
        带厚度偏置注记键 ``thickness_bias_note``（W8 仲裁建议 3，见模块
        docstring"厚度偏置声明"节）：s/t<4 区声明饱和锚 +0.8dB@s/t=2.34
        （HFSS=对齐基准，不改综合数值）；s/t≥4 伪象主导区划线，此时发
        :class:`UserWarning` 仅提示不阻断（数据不足硬门，#122）。

    Raises:
        ValueError: f0/coupling_db/feed_len 非法、z0_ohm != 50、KJ 反解
            不可达或 spec 自检失败。
    """
    f0_ghz = float(params["f0_ghz"])
    if not (f0_ghz > 0.0) or not math.isfinite(f0_ghz):
        raise ValueError(f"f0_ghz 必须为正有限数: {params.get('f0_ghz')!r}")
    z0_ohm = float(params.get("z0_ohm", 50.0))
    if z0_ohm != 50.0:
        raise ValueError(
            f"仅支持 50Ω 系统口径（pyedb wave_port 配置面阻抗固定 50，假设 3）:"
            f" z0_ohm={z0_ohm}"
        )
    coupling_db = float(params.get("coupling_db", DEFAULT_COUPLING_DB))
    if not math.isfinite(coupling_db) or coupling_db <= 0.0:
        raise ValueError(f"coupling_db 必须为正有限数: {params.get('coupling_db')!r}")
    feed_len_mm = float(params.get("feed_len_mm", DEFAULT_FEED_LEN_MM))
    copper_t = float(params.get("copper_thickness_mm", DEFAULT_COPPER_THICKNESS_MM))
    margin_mm = float(params.get("board_margin_mm", DEFAULT_BOARD_MARGIN_MM))
    if feed_len_mm <= 0.0:
        raise ValueError(f"feed_len_mm 必须为正: {feed_len_mm}")

    stackup = resolve_stackup(params.get("stackup"))
    # 综合链（注册 cline_coupler 模板设计函数同款，同函数同参）：Pozar §7.6
    # 闭式 (Z0e,Z0o) → KJ 二维反解 (w,s) → KJ 正向回代 + λ/4@平均 εeff
    design = cline_coupler_design(
        coupling_db, f0_ghz, z0_ohm,
        er=stackup.epsilon_r, h_mm=stackup.thickness_mm,
    )
    w_mm = float(design["w_mm"])
    s_mm = float(design["s_mm"])
    lc_mm = float(design["lc_mm"])
    w_feed, _eps_feed = solve_microstrip(z0_ohm, f0_ghz, stackup)  # 50Ω 单源
    if min(w_mm, s_mm, lc_mm, w_feed) <= 0.0:
        raise ValueError(
            f"综合几何须 >0: w={w_mm}, s={s_mm}, lc={lc_mm}, w_feed={w_feed}"
        )

    # s/t 厚度偏置注记（W8 仲裁建议 3，渲染期声明不改综合数值——模块
    # docstring"厚度偏置声明"节）：s/t<4 区锚 +0.8dB@s/t=2.34；s/t≥4
    # 伪象主导区守卫仅 warning 不 fail（#122）
    if copper_t > 0.0:
        st_ratio = s_mm / copper_t
        if st_ratio < THICKNESS_BIAS_ST_DIVIDER:
            thickness_bias_note = (
                f"s/t={st_ratio:.2f}（缝/铜厚比）<{THICKNESS_BIAS_ST_DIVIDER:g}："
                "已知厚度偏置区——饱和锚 +0.8dB@s/t=2.34（W8 HFSS 饱和口径，"
                "HFSS=对齐基准；方向=过耦）。综合数值不改（KJ 零厚假设经"
                "零厚全波验证无需修正，残差 0.23dB）；冒烟判读 S31 按此偏置"
                "对待。"
            )
        else:
            warnings.warn(
                f"coupled_line 厚度伪象区守卫：s/t={st_ratio:.2f}≥"
                f"{THICKNESS_BIAS_ST_DIVIDER:g} 属伪象主导区划线（W8 实测 "
                "bias+2.274dB@s/t=4.29 为 ΔS 收敛档伪象主导、非纯厚度，"
                "厚度效应量值未分辨）——仅提示不阻断（数据不足硬门，#122），"
                "判读请收紧收敛档复核",
                UserWarning,
                stacklevel=2,
            )
            thickness_bias_note = (
                f"s/t={st_ratio:.2f}（缝/铜厚比）≥{THICKNESS_BIAS_ST_DIVIDER:g}："
                "伪象主导区划线——W8 实测 bias+2.274dB@s/t=4.29 属 ΔS 收敛档"
                "伪象主导、非纯厚度（厚度效应量值未分辨）；守卫仅 warning "
                "不 fail（数据不足硬门，#122），判读需收紧收敛档复核后归因。"
            )
    else:
        thickness_bias_note = (
            "copper_thickness_mm<=0（零厚口径）：KJ 零厚假设精确成立、无厚度"
            "偏置（W8 零厚全波验证 vs KJ 预测残差 0.23dB）。"
        )

    # 几何：耦合线竖直（x=±(w+s)/2，y∈[−lc/2, lc/2]），馈线水平自线端点
    # 向外引出（馈线矩形与线矩形 w/2×wf/2 面积重叠=连通，flat cap 口径）
    d = w_mm + s_mm
    xa, xb = -d / 2.0, d / 2.0
    y0, y1 = -lc_mm / 2.0, lc_mm / 2.0
    traces = [
        make_trace("line_a", w_mm, [[xa, y0], [xa, y1]], "coupled_line"),
        make_trace("line_b", w_mm, [[xb, y0], [xb, y1]], "coupled_line"),
        make_trace("feed_p1", w_feed, [[xa - feed_len_mm, y0], [xa, y0]], "feed"),
        make_trace("feed_p2", w_feed, [[xa - feed_len_mm, y1], [xa, y1]], "feed"),
        make_trace("feed_p3", w_feed, [[xb, y0], [xb + feed_len_mm, y0]], "feed"),
        make_trace("feed_p4", w_feed, [[xb, y1], [xb + feed_len_mm, y1]], "feed"),
    ]
    ports = [
        make_wave_port("P1", 1, "feed_p1", [xa - feed_len_mm, y0]),
        make_wave_port("P2", 2, "feed_p2", [xa - feed_len_mm, y1]),
        make_wave_port("P3", 3, "feed_p3", [xb + feed_len_mm, y0]),
        make_wave_port("P4", 4, "feed_p4", [xb + feed_len_mm, y1]),
    ]

    sweep = params.get("sweep") or {}
    sweep_spec = {
        "name": "sweep1",
        "type": str(sweep.get("type", "interpolation")),
        "start_ghz": float(sweep.get("start_ghz", 0.7 * f0_ghz)),
        "stop_ghz": float(sweep.get("stop_ghz", 1.3 * f0_ghz)),
        "points": int(sweep.get("points", 401)),
    }
    adapt = params.get("adapt") or {}
    sim_setup = {
        "f0_ghz": f0_ghz,
        "sweep": sweep_spec,
        "adapt": {
            "max_passes": int(adapt.get("max_passes", 20)),
            # 缺省 0.02=W10 定谳回退（W8 加严 0.005 因 EDB schema 无
            # MaxDelta 键写入不可达而撤，DEFAULT_ADAPT_MAX_DELTA 注释带
            # 证据链）；显式覆盖原样透传
            "max_delta": float(adapt.get("max_delta", DEFAULT_ADAPT_MAX_DELTA)),
        },
    }

    spec: dict[str, Any] = {
        "template": "edb_coupled_line",
        "schema_version": SPEC_SCHEMA_VERSION,
        "units": {"length": "mm", "frequency": "GHz"},
        "params": {
            "f0_ghz": f0_ghz,
            "z0_ohm": z0_ohm,
            "coupling_db": coupling_db,
            "c": float(design["c"]),
            "zee_ohm": float(design["zee_ohm"]),
            "zoo_ohm": float(design["zoo_ohm"]),
            "w_mm": w_mm,
            "s_mm": s_mm,
            "eps_eff_even": float(design["ere_e"]),
            "eps_eff_odd": float(design["ere_o"]),
            "eps_eff_avg": float(design["ere_avg"]),
            "coupled_len_mm": lc_mm,
            "w_feed_mm": w_feed,
            "feed_len_mm": feed_len_mm,
            "copper_thickness_mm": copper_t,
            "board_margin_mm": margin_mm,
            "synthesis_source": "oe_templates.render_c4.cline_coupler_design"
                                "（Pozar §7.6 闭式 + closedform KJ 二维反解，"
                                "注册 cline_coupler 模板同款单源）；w_feed="
                                "core.synthesis solve_microstrip 50Ω 单源",
            "port_roles": "P1 输入（线A近端）/P2 直通（线A远端）"
                          "/P3 耦合（线B近端）/P4 隔离（线B远端）——后向波"
                          "耦合器，线 A/B DC 隔离",
            "thickness_bias_note": thickness_bias_note,
        },
        "stackup": build_spec_stackup(stackup, copper_t),
        "traces": traces,
        "vias": [],
        "resistors": [],
        "ports": ports,
        "board": board_from_traces(traces, margin_mm),
        "sim_setup": sim_setup,
    }
    # 自检：validate_spec 正本逻辑不动，族豁免行由发射器侧过滤（模块
    # docstring 豁免 1/2；非豁免行任何一条非空即拒绝发射）
    errors = [e for e in validate_spec(spec)
              if not e.startswith(_FAMILY_VALIDATE_EXEMPT_PREFIXES)]
    if errors:
        raise ValueError(f"coupled_line spec 自检失败: {errors}")
    return spec, assemble_config(spec)
