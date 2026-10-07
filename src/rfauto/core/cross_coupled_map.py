"""交叉耦合广义切比雪夫 BPF → 模板物理参数映射内核（TA-14，ge8d Wave D 席 D2）。

条目（研究扩充 round15 §二·2 TA-14）：「交叉耦合
广义 Chebyshev 模板化 | cm_core 全流程已在（见十七轮勘误）——非相邻耦合线
映射 L 级」。十七轮勘误（round17 §二）：cm_core 936 行已覆盖广义 Chebyshev
任意 TZ 混合 + Cameron N+2 横向留数 + folded/arrow 旋转消元（对拍
Yellowbooker 开源码）——**本模块为纯消费（cm_core 禁改）**，补齐缺的最后一
环：耦合矩阵（含**非相邻**交叉耦合条目）→ 模板物理参数映射闭式。

映射口径（denormalization，与 core/synthesis.hairpin_design_from_order 同
约定，Hong §5.2/§5.3；全极点情形对 classical g 值闭式逐项独立验证，见锚）：
- k_ij = FBW·|M_ij|（谐振器-谐振器耦合；**含 |i−j|≥2 非相邻条目**——folded
  拓扑的交叉耦合，N=4 TZ 设计实测 m14=−0.1705）；
- Q_e = 1/(FBW·|M_S1|²)（外部耦合）；
- 物理实现（模板 xcheb_bpf4 开路环四重奏）：全部耦合为共面平行边耦合段
  （Kirschning-Jansen 准静态闭式，core/coupled_microstrip），部分长度耦合
  线性标度模型 k_eff = χ·KJ(s)——χ=耦合段长/谐振器长（开路环布局内禀
  χ=(a+w)/(4a)，边段 a/周长 4a），反解 s=KJ_inv(k/χ)。**χ 线性标度为一阶
  准静态近似**（部分长耦合的扰动一阶项；真机 EM 校准属后续批次，meta
  smoke_note 如实登记——此即 round15「非相邻耦合线映射 L 级」的剩余项）；
- 抽头馈电 τ：hairpin 同闭式 Q_e=(π/2)(Z0/Z_r)sec²(πτ)（τ 自开路端沿环
  路径计，core/coupled_microstrip.hairpin_tap_frac_from_qe）。

验证锚（#118/#300，≥2 独立来源；test_cross_coupled_map）：
1. 全极点退化对 classical g 值闭式（独立来源：core/matching.chebyshev_g_
   values，Pozar §8.6 口径）：k_i ↔ FBW/√(g_j·g_{j+1})、Q_e ↔ g0·g1/FBW
   （cm_core 折叠矩阵端到端与 g 值链互证——两条独立综合路径同答案）；
2. KJ 反解/正解往返：gaps→k（KJ 正解）→ 重组矩阵 → coupling_matrix_response
   与原矩阵频响 max|ΔS| ≤ 1e-9（hairpin_gap_mm_from_k xtol=1e-12 设计精度，
   A4 同口径）；
3. TZ 设计的频响形状锚：TZ=[±2.0] 时耦合矩阵频响在 Ω≈±2 产传输零点
   （|S21| 谷）——映射保号重组后零点保持（形状不变性）。

铁律 7：数值只在确定性内核（cm_core/KJ/g 值闭式），本模块零随机零 IO。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = ["CROSS_COUPLED_MIN_M", "cross_coupled_bpf_design",
           "cross_coupled_ring_quad_design"]

#: 非相邻条目计入映射的幅值地板（低于此视为无该耦合，全极点矩阵即全零）
CROSS_COUPLED_MIN_M = 1e-9


def cross_coupled_bpf_design(
    order: int = 4,
    f0_ghz: float = 2.5,
    fbw: float = 0.05,
    rl_db: float = 20.0,
    transmission_zeros: list[float] | None = None,
    er: float = 3.66,
    h_mm: float = 0.508,
    w_mm: float | None = None,
    chi: float | None = None,
    chi_overrides: dict[tuple[int, int], float] | None = None,
) -> dict[str, Any]:
    """cm_core 折叠耦合矩阵 → 模板物理参数（闭式映射，确定性）。

    参数：
    - order：谐振器数 N（折叠四重奏拓扑 N=4 为名义；N≥2 通用，交叉耦合
      条目按 folded 拓扑出现才映射）；
    - transmission_zeros：归一化低通 TZ（±Ω 成对口径，如 [2.0]；None=全极
      点——此时矩阵无交叉条目，gaps 仅有主线缝）；
    - chi：耦合段长/谐振器长（开路环布局内禀值；None=按名义几何 live 精算
      (a+w)/(4a)）。缺省全部耦合缝共用同一 χ（全共翼对齐布局）；
    - chi_overrides：逐对 χ 覆盖 {(i,j): χ}——布局错位（如 s14≠s23 使底行
      两环竖向错位 → 3-4 水平耦合段共翼缩短）时的确定性修正入口；两遍法
      消费：第一遍均匀 χ 得缝 → 布局错位量 → 覆盖 χ 复算受影响对；

    返回 dict：order/f0_ghz/fbw/rl_db/tz/w_mm/a_mm/perimeter_mm/res_len_mm/
    qe/tap_frac/k_pairs（逐对 m_ij/k_ij/chi/s_mm/kind）/gaps_mm（主线序）
    /g_cross_mm/anchors（g 值互证/往返误差/响应一致性）/coupling_matrix/
    notes。设计链整链复算 ~10s（cm_core 综合+KJ 反解，在门预算内）。
    """
    from rfauto.core.calc_families.cm_core import (
        _cm_from_list,
        coupling_matrix_folded,
        coupling_matrix_response,
        coupling_matrix_synthesize_n2,
    )
    from rfauto.core.coupled_microstrip import (
        hairpin_gap_mm_from_k,
        hairpin_k_from_gap_mm,
        hairpin_tap_frac_from_qe,
    )

    n = int(order)
    if n < 2:
        raise ValueError(f"order 须 ≥2（交叉耦合拓扑至少 2 谐振器），得 {n}")
    if not 0.0 < float(fbw) <= 1.0:
        raise ValueError(f"fbw={fbw} 须在 (0,1]")
    if float(rl_db) <= 0.0:
        raise ValueError(f"rl_db={rl_db} 须 >0")
    tz = [float(v) for v in (transmission_zeros or [])]

    # ── ① cm_core 折叠矩阵（消费，禁改）───────────────────────────────────
    synth = coupling_matrix_synthesize_n2(n, float(rl_db), tz)
    if not synth.get("ok"):
        raise ValueError(f"cm_core 综合失败: {synth}")
    folded = coupling_matrix_folded(synth["coupling_matrix"],
                                    sign_mode="mainline_positive")
    m = _cm_from_list(folded["coupling_matrix"])
    m_abs = abs(complex(m[0, 1].item()))
    m_s1 = m_abs.real if hasattr(m_abs, "real") else float(m_abs)
    qe = 1.0 / (float(fbw) * m_s1 ** 2)

    # ── ② 谐振器几何（λg/2 周长开路环；w=50Ω HJ 单源）──────────────────────
    from rfauto.core.synthesis import (
        Stackup,
        forward_z0,
        lossless_width_mm,
        patch_fringing_delta_l,
    )

    w = (lossless_width_mm(50.0, float(f0_ghz), float(er), float(h_mm),
                           digits=None) if w_mm is None else float(w_mm))
    stackup = Stackup(name="xcheb_bpf4", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    _, eps_eff = forward_z0(w, float(f0_ghz), stackup)
    lg_half_mm = 299.792458 / (2.0 * float(f0_ghz) * math.sqrt(eps_eff))
    dl_mm = patch_fringing_delta_l(w * 1e-3, float(h_mm) * 1e-3,
                                   eps_eff) * 1e3
    perimeter_mm = lg_half_mm - 2.0 * dl_mm      # 开路环周长（双开路端 Δl）
    a_mm = perimeter_mm / 4.0                    # 环边段长
    chi_eff = (float(chi) if chi is not None
               else (a_mm + w) / perimeter_mm)   # (a+w)/(4a) live 精算
    if not 0.0 < chi_eff < 1.0:
        raise ValueError(f"耦合段占比 χ={chi_eff:.4g} 须在 (0,1)")

    # ── ③ 谐振器对逐对映射（主线+非相邻交叉）───────────────────────────────
    pairs: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        for j in range(i + 1, n + 1):
            mij = complex(m[i, j].item())
            if abs(mij) <= CROSS_COUPLED_MIN_M:
                continue
            kind = "mainline" if j - i == 1 else "cross"
            chi_p = float((chi_overrides or {}).get((i, j), chi_eff))
            if not 0.0 < chi_p < 1.0:
                raise ValueError(
                    f"耦合对 ({i},{j}) 的 χ={chi_p:.4g} 须在 (0,1)")
            k = float(fbw) * abs(mij)
            k_section = k / chi_p
            s_mm = hairpin_gap_mm_from_k(k_section, w, float(f0_ghz),
                                         float(er), float(h_mm))
            pairs.append({"i": i, "j": j, "m_ij": round(abs(mij), 9),
                          "sign": -1.0 if mij.real < 0 else 1.0,
                          "k": round(k, 9), "chi": round(chi_p, 6),
                          "k_section": round(k_section, 9),
                          "s_mm": round(s_mm, 4), "s_raw_mm": s_mm,
                          "kind": kind})
    main = [p for p in pairs if p["kind"] == "mainline"]
    cross = [p for p in pairs if p["kind"] == "cross"]
    main_sorted = sorted(main, key=lambda p: (p["i"], p["j"]))
    gaps_mm = [p["s_mm"] for p in main_sorted]
    g_cross_mm = ([p["s_mm"] for p in
                   sorted(cross, key=lambda p: (p["i"], p["j"]))] if cross
                  else None)

    # ── ④ 抽头馈电 τ（hairpin 同闭式；τ 自开路端沿环路径计）────────────────
    tau = hairpin_tap_frac_from_qe(qe)

    # ── ⑤ 锚一：全极点退化对 classical g 值（独立综合路径互证）──────────────
    anchors: dict[str, Any] = {}
    if not tz:
        from rfauto.core.matching import chebyshev_g_values

        ripple_db = 10.0 * math.log10(1.0 + 1.0 / (10.0 ** (float(rl_db) / 10.0)
                                                    - 1.0))
        g = chebyshev_g_values(n, ripple_db)
        k_g = [float(fbw) / math.sqrt(g[j] * g[j + 1]) for j in range(1, n)]
        k_map = [p["k"] for p in main_sorted]
        if len(k_g) == len(k_map):
            anchors["g_value_max_rel_dev"] = round(max(
                abs(kv / kg - 1.0) for kv, kg in zip(k_map, k_g, strict=True)), 9)
        anchors["qe_g_value"] = round(g[0] * g[1] / float(fbw), 6)
        anchors["qe_rel_dev"] = round(abs(qe / anchors["qe_g_value"] - 1.0), 9)

    # ── ⑥ 锚二：KJ 往返 + 频响一致性（gaps→k→重组矩阵 vs 原矩阵）────────────
    m2 = m.copy()
    for p in pairs:
        # 往返锚用未舍入缝（4 位舍入是名义档发布口径，其 KJ 灵敏度 ~0.1/mm
        # 会把舍入误差放大到 1e-4 级——锚验证的是映射数学非舍入档位）
        k_fwd = hairpin_k_from_gap_mm(p["s_raw_mm"], w, float(f0_ghz),
                                      float(er), float(h_mm)) * p["chi"]
        val = complex(p["sign"] * k_fwd / float(fbw))
        m2[p["i"], p["j"]] = val
        m2[p["j"], p["i"]] = val
    m01 = complex(1.0 / math.sqrt(qe * float(fbw)))
    m2[0, 1] = m2[1, 0] = m01
    m2[n, n + 1] = m2[n + 1, n] = m01
    fr_axis = [float(f0_ghz) * (1.0 + 0.02 * t) for t in range(-40, 41)]
    r0 = coupling_matrix_response(fr_axis, float(f0_ghz), float(fbw),
                                  folded["coupling_matrix"])
    r2 = coupling_matrix_response(fr_axis, float(f0_ghz), float(fbw),
                                  _cm_to_list_local(m2))

    def _to_complex(resp: dict):
        cube = np.asarray(resp["s_matrix"])          # (nf, 2, 2, 2) [re, im]
        return cube[..., 0] + 1j * cube[..., 1]

    dev = float(np.max(np.abs(_to_complex(r0) - _to_complex(r2))))
    anchors["roundtrip_max_ds"] = round(dev, 12)

    # ── ⑦ 锚三：TZ 零点保持（形状不变性）──────────────────────────────────
    if tz:
        s21_0 = _to_complex(r0)[:, 1, 0]
        s21_2 = _to_complex(r2)[:, 1, 0]
        anchors["tz_s21_min_orig_db"] = round(
            20.0 * math.log10(max(float(np.min(np.abs(s21_0))), 1e-300)), 4)
        anchors["tz_s21_min_remapped_db"] = round(
            20.0 * math.log10(max(float(np.min(np.abs(s21_2))), 1e-300)), 4)

    tap_path_mm = tau * perimeter_mm
    notes = [
        f"cm_core folded N={n}（TZ={tz or '全极点'}）：M_S1={m_s1:.5f} → "
        f"Q_e={qe:.4f}，τ={tau:.5f}",
        f"耦合对（χ={chi_eff:.4f}，KJ 反解）："
        + ", ".join(f"m{p['i']}{p['j']}={p['m_ij']:.4f}({p['kind']})→"
                    f"k={p['k']:.5f}→s={p['s_mm']:.4f}mm" for p in pairs),
        f"开路环：周长={perimeter_mm:.4f}mm（λg/2−2Δl，Δl={dl_mm:.4f}mm），"
        f"边段 a={a_mm:.4f}mm，w={w:.4f}mm",
        "χ 线性部分长耦合为一阶准静态近似（EM 校准属后续批次，#122 如实）",
    ]
    return {
        "order": n, "f0_ghz": float(f0_ghz), "fbw": float(fbw),
        "rl_db": float(rl_db), "transmission_zeros": tz,
        "er": float(er), "h_mm": float(h_mm),
        "w_mm": w, "a_mm": a_mm, "perimeter_mm": perimeter_mm,
        "eps_eff": round(eps_eff, 5),
        "qe": qe, "tap_frac": tau, "tap_path_mm": round(tap_path_mm, 4),
        "m_s1": m_s1, "chi": chi_eff,
        "k_pairs": pairs, "gaps_mm": gaps_mm, "g_cross_mm": g_cross_mm,
        "anchors": anchors,
        "coupling_matrix": folded["coupling_matrix"],
        "notes": notes,
    }


def cross_coupled_ring_quad_design(
    f0_ghz: float = 2.5, fbw: float = 0.05, rl_db: float = 20.0,
    transmission_zeros: list[float] | None = None,
    er: float = 3.66, h_mm: float = 0.508,
    g_open_mm: float = 0.3, g_pos_frac: float = 0.7,
    n_iter: int = 12,
) -> dict[str, Any]:
    """开路环四重奏（2×2）布局级设计链：cross_coupled_bpf_design + 逐对 χ
    定点自洽（两遍法推广为有界定点迭代）。

    布局物理（模板 xcheb_bpf4 单源）：环 1（左上）/2（右上）/3（右下）/
    4（左下）；耦合对 1-2（顶行水平缝 s12）、2-3（右侧竖缝 s23）、3-4（底行
    水平缝 s34）、4-1（左侧竖缝 s14=交叉耦合）。s14≠s23 使环 3/4 竖向错位
    dy34=|s14−s23| → 3-4 水平耦合段共翼缩短 2h_r−dy34 → χ34 降；s12≠s34 使
    环 2/3 横向错位 dx23 → χ23 同理。缝反解依赖 χ、χ 依赖缝——定点迭代至
    错位量变化 <1e-9mm（有界 n_iter；不收敛如实 ValueError）。

    返回：design 全量键 + g12/g23/g34/g14_mm + g_open_mm/g_pos_mm/tap_t_mm
    （环 1/4 开缝位与抽头位；环 2/3 开缝居中）+ dx23/dy34 错位量。
    """
    d0 = cross_coupled_bpf_design(order=4, f0_ghz=f0_ghz, fbw=fbw,
                                  rl_db=rl_db,
                                  transmission_zeros=transmission_zeros,
                                  er=er, h_mm=h_mm)
    a = d0["a_mm"]
    w = d0["w_mm"]
    h_r = (a + w) / 2.0
    chi0 = d0["chi"]

    def pair(design: dict, i: int, j: int) -> dict:
        for p in design["k_pairs"]:
            if (p["i"], p["j"]) == (i, j):
                return p
        raise KeyError(f"耦合对 ({i},{j}) 不在映射输出中")

    dx23 = dy34 = 0.0
    d = d0
    for _ in range(int(n_iter)):
        ov = {(3, 4): chi0 * max(2.0 * h_r - dy34, 1e-6) / (2.0 * h_r),
              (2, 3): chi0 * max(2.0 * h_r - dx23, 1e-6) / (2.0 * h_r)}
        d = cross_coupled_bpf_design(order=4, f0_ghz=f0_ghz, fbw=fbw,
                                     rl_db=rl_db,
                                     transmission_zeros=transmission_zeros,
                                     er=er, h_mm=h_mm, chi=chi0,
                                     chi_overrides=ov)
        s12 = pair(d, 1, 2)["s_raw_mm"]
        s23 = pair(d, 2, 3)["s_raw_mm"]
        s34 = pair(d, 3, 4)["s_raw_mm"]
        s14 = pair(d, 1, 4)["s_raw_mm"]
        ndy, ndx = abs(s14 - s23), abs(s12 - s34)
        if abs(ndy - dy34) < 1e-9 and abs(ndx - dx23) < 1e-9:
            dx23, dy34 = ndx, ndy
            break
        dx23, dy34 = ndx, ndy
    else:
        raise ValueError(
            f"开路环四重奏定点不收敛（n_iter={n_iter}，dx23={dx23:.3g}/"
            f"dy34={dy34:.3g}mm）——如实报错不静默截断")

    # 开缝位/抽头位（环 1/4：Q_e 决定「开缝中点→抽头」沿环路径 τ·周长；
    # 路径 = g_pos + t，t 为抽头沿耦合侧自角部距离）
    tau = d["tap_frac"]
    perimeter = d["perimeter_mm"]
    g_pos_mm = g_pos_frac * a
    tap_t_mm = tau * perimeter - g_pos_mm
    if not 0.0 < tap_t_mm < a:
        raise ValueError(
            f"抽头位 t={tap_t_mm:.4f}mm 超出环边段 (0, {a:.4f})mm——调整 "
            f"g_pos_frac（τ={tau:.5f}、周长={perimeter:.4f}mm）")
    out = dict(d)
    out.update({
        "g12_mm": round(pair(d, 1, 2)["s_raw_mm"], 4),
        "g23_mm": round(pair(d, 2, 3)["s_raw_mm"], 4),
        "g34_mm": round(pair(d, 3, 4)["s_raw_mm"], 4),
        "g14_mm": round(pair(d, 1, 4)["s_raw_mm"], 4),
        "g_open_mm": float(g_open_mm),
        "g_pos_mm": round(g_pos_mm, 4),
        "tap_t_mm": round(tap_t_mm, 4),
        "dx23_mm": round(dx23, 6), "dy34_mm": round(dy34, 6),
        "chi_pair": {f"{p['i']},{p['j']}": p["chi"] for p in d["k_pairs"]},
    })
    out["notes"] = [*d["notes"],
                    f"开路环布局定点：χ 逐对={out['chi_pair']}（dx23={dx23:.4g}/"
                    f"dy34={dy34:.4g}mm 错位修正），g_pos={g_pos_mm:.4f}mm、"
                    f"tap_t={tap_t_mm:.4f}mm（环 1/4 对称）"]
    return out


def _cm_to_list_local(m) -> list:
    """复矩阵 → cm_core [re, im] 对嵌套列表（_cm_to_list 非公开，本地薄等价）。"""
    return [[[round(float(v.real), 12), round(float(v.imag), 12)] for v in row]
            for row in m]

