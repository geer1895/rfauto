"""fake_adapter.filter_family —— 滤波器族解析模型（hairpin/coupled_bpf/C3）。

自 adapters/fake_adapter.py 单文件巨石按职责域拆分（架构批 W4-S2，T2 范式/
AU-1 工艺）：hairpin 真机修正常数+耦合矩阵链、平行耦合 BPF（KJ 电路级联）、
C3 族（interdigital/combline/sir_bpf）+ c3.l_via_h 锚惰性解析（G-06 改道，
模块级缓存）。代码体逐字节搬迁，零逻辑改动。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# hairpin 抽头外部 Q 的真机修正 c(τ)=Q_e_EM/Q_e_closed（线性 c0+c1·τ）：WP2.3 收口 B1
# 单谐振器双抽头 τ 扫描标定产物（scripts/hairpin_q_extract.py --analyze →
# runs/hairpin_q_extract/summary.json），数值只在内核（铁律 7）、不得手改。
# 2026-09-16 B1 实测（runs/hairpin_q_extract/tau030/036/040/043）：过质量门（0.3/0.5dB
# 两窗曲率一致 + FWHM≤窗半）τ=0.40（Q_e_EM=17.659 vs 闭式 16.450，c=1.0735）与 τ=0.43
# （34.691 vs 33.009，c=1.0509）两点线性；τ=0.30/0.36 强过耦合（直通背景平台、FWHM>窗半，
# 非窄带单极点）如实排除。标定域 τ∈[0.40,0.43]，域外为线性外推。
_HAIRPIN_QE_CORR: tuple[float, float] = (1.37437, -0.75218)
# hairpin 谐振频率真机修正 c_f0=f0_EM/f0_closed（同一 arm_len）：WP2.3 收口 B2 N=3
# 复跑（runs/hairpin_calib/pt4_ag30_plane3mm/calib.json：通带中心 2.5925GHz vs 闭式
# λg/2 设计 2.5 → 1.0370；U 弯+开路端等效缩短，pt0-pt3 四轮同值 +3.7%）。名义 arm_len
# 按 L·f0_act/f0（f∝1/L）定版后，fake 与 EM 在名义处同 f0；数值只在内核、不得手改。
_HAIRPIN_F0_CORR: float = 1.0370


def hairpin_coupling_matrix(k_list: list[float], qe: float,
                            fbw_g: float = 0.05) -> list[list[float]]:
    """(k_list, Q_e) → N+2 归一化耦合矩阵（对角 0；规范 fbw_g 任意，响应不变）。

    M_{i,i+1}=k_i/fbw_g、M_{0,1}=M_{N,N+1}=√(1/(fbw_g·Q_e))（Hong §5.2/§5.3 映射
    k=FBW·|M|、Q_e=1/(FBW·|M_{0,1}|²) 的精确逆），喂 coupling_matrix_response
    (fbw=fbw_g, external_q=[1,1])。
    #1b 模型审计（2026-09-16，test_hairpin_template 钉住）：fbw_g∈{0.02,0.05,0.10,
    0.5,1.0} 五规范 max|ΔS|=0（精确规范不变——源/载对角项 1 与 m01∝g^-1/2、内耦合
    ∝g^-1、ω∝g^-1 在响应中联合消去 g）；历史"fbw=1 偏差 6000dB"是把固定归一化
    矩阵直接换 fbw 喂响应（未按上式重归一）的实现口径，不是物理。
    """
    ks = [float(k) for k in k_list]
    n = len(ks) + 1
    g = float(fbw_g)
    q = float(qe)
    if not 0.0 < g <= 1.0:
        raise ValueError("fbw_g 须在 (0,1]")
    if q <= 0.0 or any(k <= 0.0 for k in ks):
        raise ValueError("Q_e 与 k 须 >0")
    m = np.zeros((n + 2, n + 2), dtype=float)
    m01 = math.sqrt(1.0 / (g * q))
    m[0, 1] = m[1, 0] = m01
    m[n, n + 1] = m[n + 1, n] = m01
    for i, k in enumerate(ks, start=1):
        m[i, i + 1] = m[i + 1, i] = k / g
    return m.tolist()


def _hairpin_sparams(
    freq_ghz: np.ndarray,
    f0_ghz: float = 2.5,
    order: int = 3,
    fbw: float = 0.05,
    rl_db: float = 20.0,
    z_ref: float = 50.0,
    *,
    k_list: list[float] | None = None,
    qe: float | None = None,
) -> np.ndarray:
    """发夹线带通滤波器解析（WP2.3 滤波器族）——耦合矩阵理想频响。

    电气量 (k_list, Q_e) 优先：由几何反演给出（gap→k KJ 闭式、tap_frac→Q_e 抽头
    闭式 × c(τ)，在适配器派发处完成，2026-09-16 收口 A4 接通）；缺省时退回 C13
    设计点（fbw/rl_db 常数锚：k=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M_{0,1}|²)，与旧口径
    逐位一致）。矩阵经 hairpin_coupling_matrix 以规范 fbw_g=fbw 重归一（规范不变，
    见其 docstring），响应走 core/calculators coupling_matrix_response（S22=S11/
    S12=S21 对称口径）。f0 由调用方按 λg/2 反演传入（arm_len_mm 下降沿响应）。
    """
    from rfauto.core.calculators import coupling_matrix_response

    n = int(order)
    if k_list is None or qe is None:
        from rfauto.core.synthesis import synthesize_bpf_model

        synth = synthesize_bpf_model(order=n, f0_ghz=float(f0_ghz),
                                     fbw=float(fbw), rl_db=float(rl_db),
                                     topology="folded")
        if not synth.get("ok"):
            raise ValueError(f"hairpin fake: C13 综合失败: {synth.get('errors')}")
        arr = np.asarray(synth["coupling_matrix"], dtype=float)
        if arr.ndim == 3:
            arr = np.hypot(arr[..., 0], arr[..., 1])
        if k_list is None:
            k_list = [float(fbw) * abs(arr[i, i + 1]) for i in range(1, n)]
        if qe is None:
            qe = 1.0 / (float(fbw) * abs(arr[0, 1]) ** 2)
    if len(k_list) != n - 1:
        raise ValueError(f"hairpin fake: k_list 长度须为 order-1={n - 1}")
    resp = coupling_matrix_response(
        freq_ghz=[float(v) for v in freq_ghz], f0_ghz=float(f0_ghz),
        fbw=float(fbw), matrix=hairpin_coupling_matrix(k_list, qe, float(fbw)),
        z_ref=float(z_ref))
    cube = np.asarray(resp["s_matrix"], dtype=float)   # (n,2,2,[re,im])
    return cube[..., 0] + 1j * cube[..., 1]


def _coupled_bpf_sparams(
    freq_ghz: np.ndarray,
    widths_mm: list[float] | tuple[float, ...],
    gaps_mm: list[float] | tuple[float, ...],
    res_len_mm: float,
    feed_len_mm: float,
    f0_ghz: float = 2.5,
    er: float = 3.66,
    h_mm: float = 0.508,
    z_ref: float = 50.0,
) -> np.ndarray:
    """平行耦合 BPF 解析（WP2.3 BPF 族锚）——几何 → 耦合段电气量 → 电路级联。

    裁判同源闭式：openems_templates.coupled_bpf_circuit_sparams（每耦合段
    = 偶/奇模 2 端口叠加 4 端口 S、两交叉口开路端接压成 2 端口、与 50Ω 馈线
    ABCD 级联；无耗/互易由构造保证，test_coupled_bpf_template 钉住）。

    #154 纪律（列表参数两通道同索引同语义，与 _coupled_bpf_layout 逐参数对齐）：
    - widths_mm[j] / gaps_mm[j] = 第 j 个耦合段线宽 / 边到边缝
      （j=0 输入馈-腔 … j=N 腔-输出馈；长度 N+1 ⇒ order=N 由列表长度推出）；
      每段 (w,s) → KJ 1984 准静态 (Z0e,Z0o,εeff_e,εeff_o)
      （coupled_microstrip_even_odd_ohm @f0，同综合链口径）。
    - res_len_mm = 谐振器 1 物理长；耦合段长逐段 =
      _coupled_bpf_section_lengths_mm 逐端 Δl 修正派生（与 openEMS 渲染
      _coupled_bpf_layout 同源 helper，防双源漂移），以 design
      "section_len_mm" 传入裁判（缺键回退均匀 lc=res_len/2）。
    - feed_len_mm = 50Ω 馈线物理长（裁判馈线 = 理想 z_ref 线，相位按物理长）。
    - w_feed_mm 只进几何（50Ω 线宽由 HJ 综合定），不进电气模型——同
      atten_pi/atten_t 的 w_mm 口径，如实标注。
    已知口径限制同裁判：宽度台阶不连续性、开路端边缘导纳残差、KJ 色散
    不进模型（EM 冒烟实测其总量， 平行耦合 BPF 段）。
    """
    from rfauto.adapters.openems_templates import (
        _coupled_bpf_section_lengths_mm,
        coupled_bpf_circuit_sparams,
        coupled_microstrip_even_odd_ohm,
    )

    widths = [float(v) for v in widths_mm]
    gaps = [float(v) for v in gaps_mm]
    if len(widths) != len(gaps) or len(widths) < 2:
        raise ValueError(
            f"coupled_bpf fake: widths_mm/gaps_mm 须等长且 ≥2（order+1），得 "
            f"{len(widths)}/{len(gaps)}")
    if any(v <= 0.0 for v in (*widths, *gaps)):
        raise ValueError("coupled_bpf fake: widths_mm/gaps_mm 须 >0")
    if not (float(res_len_mm) > 0.0 and float(feed_len_mm) > 0.0):
        raise ValueError("coupled_bpf fake: res_len_mm/feed_len_mm 须 >0")
    sections = []
    for w, s in zip(widths, gaps, strict=True):
        ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
            w, s, float(f0_ghz), float(er), float(h_mm))
        sections.append({"zee_ohm": ze, "zoo_ohm": zo,
                         "ere_e": ere_e, "ere_o": ere_o})
    design = {
        "order": len(widths) - 1,
        "f0_ghz": float(f0_ghz),
        "feed_len_mm": float(feed_len_mm),
        # 逐端 Δl 修正段长（与渲染同源 helper）——防双源漂移
        "section_len_mm": _coupled_bpf_section_lengths_mm(
            widths, float(res_len_mm), float(f0_ghz), float(er),
            float(h_mm)),
        "sections": sections,
    }
    return coupled_bpf_circuit_sparams(
        np.asarray(freq_ghz, dtype=float), design, z_ref=float(z_ref))


# C3 滤波器族 II（interdigital/combline/sir_bpf，2026-09-15 注册）：模块内常量
# 副本（同 _ANT2_TEMPLATES 口径：fake 对 openems_templates 只做惰性导入）
_C3_TEMPLATES: tuple[str, ...] = ("interdigital", "combline", "sir_bpf")

# c3.l_via_h 锚消费改道（G-06，2026-10-04）：l_via_h="auto" 的取值改经
# knowledge/anchors.yaml 的 c3.l_via_h.openems-hfss-v1（值 0.125e-9 H，HFSS
# 仲裁中点）惰性解析——照 render_c3._c3_l_via_anchor_h 同款范式（模块级缓存
# 首解析后复用，避免每渲染 IO），使本文件成为锚的 runtime_resolve 真消费者
# （anchors.yaml consumers 声明自此如实；此前 auto 经 c3_circuit_sparams 侧
# 同锚解析，行为不变）。注册表缺文件/schema 错/任何异常一律回退字面
# _C3_L_VIA_CAL_FALLBACK_H（=锚值 0.125e-9，逐位同，best-effort #105：
# 渲染主路径永不因锚系统故障阻塞；test_anchor_wire_df7 G-06 席钉）。
_C3_L_VIA_CAL_FALLBACK_H = 0.125e-9  # HFSS 仲裁校准值（df5f R1）＝openems_templates.C3_L_VIA_CAL_H 字面
_C3_L_VIA_ANCHOR_ID = "c3.l_via_h.openems-hfss-v1"
_c3_l_via_anchor_ready = False
_c3_l_via_anchor_h_cache: float = _C3_L_VIA_CAL_FALLBACK_H


def _c3_l_via_anchor_h() -> float:
    """惰性解析 c3.l_via_h 锚（模块级缓存；任何失败回退字面校准值）。

    解析成功条件=注册表命中且 source=anchor 且非 stale 且有限 float；
    其余（未知锚/awaiting_data/域外/stale/装载失败/异常）一律回退
    _C3_L_VIA_CAL_FALLBACK_H——回退值与锚值逐位相等，零行为变化
    （与 render_c3._c3_l_via_anchor_h 同构，df7 第二批先例）。"""
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
            _c3_l_via_anchor_h_cache = _C3_L_VIA_CAL_FALLBACK_H
    return _c3_l_via_anchor_h_cache


def _c3_sparams(
    freq_ghz: np.ndarray,
    template: str,
    params: dict[str, Any],
    f0_ghz: float = 2.5,
    er: float = 3.66,
    h_mm: float = 0.508,
    z_ref: float = 50.0,
    *,
    l_via_h: float | None = 0.0,
) -> np.ndarray:
    """C3 滤波器族解析（交指/梳状/SIR）——几何 → KJ 倒置器 → 并联谐振 J 链。

    裁判同源闭式：openems_templates.c3_circuit_sparams 几何模式（缝列表经 KJ
    1984 回代倒置器值 |J|=(Z0e−Z0o)/(2Z0eZ0o)、谐振棒 HJ 阻抗/介质 + 开路端 Δl
    等效长度、理想 z_ref 馈线，ABCD 级联；无耗/互易由构造保证，test_c3_*
    钉住）。同一模板下 fake 与电路裁判只差参数舍入（同源，非拟合）。

    l_via_h=接地过孔电感（H，§C3 口径 8/10）：0.0（缺省）=理想短路——正式
    契约，逐位复现旧名义（旧黄金钉保持，登记⑨ 保守判定）；None=auto=取校准
    锚 c3.l_via_h.openems-hfss-v1（0.125nH，df5f HFSS 仲裁校准；本侧
    "auto" 变量经 _c3_l_via_anchor_h 就地解析、None 透传由裁判侧同锚解析
    ——G-06 改道后两路同锚单源；原 G-P 几何闭式 c3_via_inductance_h 高估
    已弃）；显式 float=指定电感（H）。

    #154 纪律（三通道同索引同语义，与 _c3_layout 逐参数对齐）：
    - gaps_mm[j]=第 j 缝边到边（j=0 输入馈-棒1 … j=N 棒N-输出馈；长度 N+1
      ⇒ order 由列表长度校验）；耦合区棒宽 = w_mm（interdigital/combline）或
      w_low_mm（sir_bpf 低阻段）。
    - interdigital：res_len_mm=棒物理长（λ/4−Δl−过孔缩短），谐振
      Y=−j·cotθ/Z_r（过孔端接式见口径 8）；
      combline：res_len_mm + c_load_pf 独立进裁判（可失调），Y=jωC−j·cotθ/Z_r；
      sir_bpf：l_low_mm/l_high_mm 两段物理长 + w_low/w_high 定 Z_lo/Z_hi。
    - feed_len_mm=50Ω 馈线物理长（裁判馈线=理想 z_ref 线，相位按物理长）；
      馈线宽只进几何。
    已知口径限制同裁判：邻耦合近似（非邻耦合不进模型）、棒端/过孔寄生、
    KJ 色散——EM 冒烟实测其总量（openems_templates §C3 段首假设清单）。
    """
    from rfauto.adapters.openems_templates import C3_TEMPLATES, c3_circuit_sparams

    if template not in C3_TEMPLATES:
        raise ValueError(f"c3 fake: 非 C3 模板 {template}（可用 {C3_TEMPLATES}）")
    return c3_circuit_sparams(
        template, np.asarray(freq_ghz, dtype=float), dict(params),
        f0_ghz=float(f0_ghz), er=float(er), h_mm=float(h_mm),
        z_ref=float(z_ref), l_via_h=l_via_h)
