"""coupled_bpf 耦合线带通族（设计链 + 电路 S 参数裁判）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np
from .closedform import (
    _fmt_list,
    _open_end_delta_mm,
    coupled_bpf_width_gap_from_zee_zoo,
)
from .registry import _DEFAULT_SUB, TEMPLATE_META, TEMPLATE_NOMINAL
from .render_hairpin import coupled_microstrip_even_odd_ohm

# ═══════════════════════════════════════════════════════════════════════════════
# WP2.3 Tier 1：平行耦合（边缘耦合）带通滤波器——BPF 族锚模板（2026-09-12 增量；
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
# models/template_specs _register_coupled_bpf）已于 2026-09-14 合流轮补齐
# ——注册动作见 COUPLED_BPF_NOMINAL 之后的 TEMPLATE_META/TEMPLATE_NOMINAL
# 赋值块（同对象注册，渲染段零改动）。

COUPLED_BPF_NOMINAL: dict[str, Any] = {
    "order": 3,
    # 50Ω 馈线宽 = lossless_width_mm(50,2.5, εr3.66 h0.508 无耗档)=1.1117
    # （XC-W 口径勘误 2026-10-02：1.1117 出自**无耗裸层叠** inverse_width——
    # 本模板 KJ/HJ 闭式链 tanδ 不进正向；旧注"live inverse_width(50,2.5,
    # rogers4350b)=1.1117"不精确，yaml 层叠（tanδ=0.0037）同参反解=1.1134
    # 且回代恰 50.00Ω——1.1134/1.1117 并存系 tanδ 参数系不同非同参漂移，
    # test_width_single_source 分系钉住。历史勘误保留：铁律 1c 线宽一律
    # skrf HJ 精算；hairpin 家族同名常数 1.1134 的家族性对齐不属本模板段）
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

# ── 注册（2026-09-14 合流轮）：coupled_bpf 升格为正式注册模板 ──
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
