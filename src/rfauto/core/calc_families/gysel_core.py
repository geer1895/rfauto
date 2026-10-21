"""Gysel 功分器 core 电气闭式族（架构批 A6-B 席域 2，R7_core_tier2 §② G6
余量：Gysel core 级注册键缺，现仅 synthesis.py 模板级等分综合）。

出处（Gysel 拓扑经典文献+偶/奇模半电路验证，正文物理口径节转录）：
- gysel_core_synthesize / gysel_frequency_response：Gysel 功分器
  六 λ/4 段拓扑与偶/奇模半电路闭式（U. H. Gysel, "A new technique
  for power divider/combiner", IEEE MTT-S Int. Microwave Symp. Dig.,
  1975；隔离桥带必要性判废锚 #206 同文件）。

两键：gysel_core_synthesize（等分口径闭式设计值+偶/奇模半电路验证+理想 f0
三口 S 矩阵） / gysel_frequency_response（五线六节点导纳网络精确频响——
匹配/均分/隔离/幅度失衡+负载耗散守恒）。

与既有 Gysel 面的边界（#222 triple-grep 证据，2026-10-11 实测）
--------------------------------------------------------
- core/synthesis.py synthesize_gysel_model=**模板级**（出 Stackup 线宽/
  长度几何+配方草稿，渲染管线绑定）；adapters/fake_adapter._gysel_sparams
  =**裁判级**（f0 常数理想 S，窄带理想化）——本族是**注册计算器 core 级**
  （纯电气闭式，无叠层依赖；频响键补全 f0 以外的带宽行为，模板/裁判均
  无此面）。anchors.py gysel.s32_iso=真机锚判读语境，不并入。
- unequal_split_wilkinson=电阻功分（内嵌薄膜电阻）；Gysel=隔离负载外置
  （两个 Z0 端接可独立散热=大功率口径）——拓扑族不同不并入。

物理口径（docstring 写死，#1c/#300 出处纪律；#206 理论核验轮定版拓扑）
--------------------------------------------------------
- 拓扑（六 λ/4 电气段）：P1—[√2·Z0 臂]—P2 与 P1—[√2·Z0 臂]—P3；
  P2—[Z0 隔离线]—Δ1 与 P3—[Z0 隔离线]—Δ2；Δ1—[Z0 λ/2 桥带，中点 M]—
  Δ2（连续线，M=几何中点=对称面上的真实电路节点）；Δ1/Δ2 各端接 Z0
  负载。端口对外 3 口（P1=入、P2/P3=出）。
- 偶/奇模半电路（对称面：偶模虚开路/奇模虚地；对称面上的端口阻抗拆半
  ——P1 的 Z0 在半电路中为 2Z0）：
  偶模：臂 λ/4 把 2Z0 变换为 Z0（Γe=0）；桥带半段 λ/4 端接虚开路→短
  路压 Δ 点→隔离线 λ/4 变开路——负载支路输出端不可见→Z_in,e=Z0。
  奇模：P1/M=虚地，臂与桥带半段 λ/4 变开路；输出只见 λ/4 隔离线端接
  Z0→Z_in,o=Z0（Γo=0）。S22=(Γe+Γo)/2=0、S32=(Γe−Γo)/2=0（f0 精确匹
  配+隔离）。判废锚（#206）：无桥带朴素拓扑带心 S21≈−6.5dB——λ/2 桥带
  是隔离的必要环节。
- 理想 f0 三口 S 矩阵：S21=S31=−j/√2（臂 −90°+均分 3.0103dB）、全对角
  与 S32=0（互易 S=Sᵀ；内负载吸收→非无耗不幺正，如实注记）。
- 频响=五线六节点导纳网络精确解（无理想化）：线导纳参量
  Y_self=−j·cotθ/Zc、Y_mutual=j/(Zc·sinθ)（λ/4 反解 Z_in=Zc²/ZL 由该
  参量直接复现）；桥带按中点 M 拆两段 λ/4（f0 处全部线节 θ=π/2 正则，
  规避连续 λ/2 在 θ=kπ 的 Y 参量奇异——f0 本身必可解）；内节点（Δ1/
  Δ2/M）消元得 3 口 Y_red，S=(I−Z0·Y_red)(I+Z0·Y_red)⁻¹。耗散守恒：
  |a1|²=Σ|b_k|²+|V_Δ1|²/Z0+|V_Δ2|²/Z0（残差字段，构造恒成立）。

数值锚（#118 独立来源；锚树 tests/unit/test_a6b_multisection_gysel.py）
- 偶/奇半电路：测试侧有限代理负载独立重解（虚开路/虚地以 1e±12 端接
  代理+缩比收敛），Γe/Γo→0 ≤1e-9。
- f0 频响 vs 理想矩阵逐位 ≤1e-9；3.0103dB 恒等；耗散守恒残差 ≤1e-12；
  vs fake_adapter 理想 S（同物理异层）≤1e-9。
- 判废对照：无桥带五节点朴素拓扑（M 不存在）带心 S21 显著偏离 −3.01dB
  （桥带必要性；#206 同口径）。

守卫：z0_ohm>0；freq_ghz/f0_ghz>0 且避开线节 θ=kπ 奇异点（f=2k·f0 显
式拒绝）；频轴非空。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .registry import register_calculator
from .thermal import _finite

_SOURCES = {
    "synth": ("Gysel 大功率等分功分器闭式（#206 理论核验轮定版拓扑：√2·Z0 "
              "臂+Z0 隔离线+Z0 λ/2 桥带+外置 Z0 负载）；偶/奇模半电路验证"
              "（对称面虚开路/虚地+端口阻抗拆半）； Microwaves101 Gysel "
              "even/odd 口径同源"),
    "resp": ("五线六节点导纳网络精确解（Y_self=−j·cotθ/Zc、Y_mutual=j/"
             "cscθ/Zc；内节点 Δ1/Δ2/M 消元；S=(I−Z0Y)(I+Z0Y)⁻¹）"),
}

_PROXY_OPEN = 1e12    # 偶模虚开路的有限代理端接（Ω）
_PROXY_SHORT = 1e-12  # 奇模虚地的有限代理端接（Ω）


def _parallel(a: float, b: float) -> float:
    """两阻抗并联（有限正值域，代理口径下无 inf 退化）。"""
    return a * b / (a + b)


def _quarter_wave_zin(zc: float, zl: float) -> float:
    """λ/4 线输入阻抗 Zc²/ZL（有限正值代理口径）。"""
    return zc * zc / zl


@register_calculator(
    "gysel_core_synthesize",
    "Gysel 功分器 core 闭式综合：等分大功率口径——臂 √2·Z0、隔离线/桥带 "
    "Z0（桥带 λ/2 中点=对称面真实节点）、Δ1/Δ2 外置 Z0 负载（可独立散热="
    "与内嵌电阻 Wilkinson 的族界）；偶/奇模半电路闭式验证 Γe=Γo=0（有限代"
    "理端接+缩比收敛）+理想 f0 三口 S 矩阵（S21=S31=−j/√2、S32=0、互易非"
    "幺正如实注记）。锚：半电路测试侧独立重解 ≤1e-9；−3.0103dB 恒等；无"
    "桥带判废对照（#206）。纯电气口径不出几何尺寸（模板级走 "
    "synthesize_gysel_model）",
    (("z0_ohm", "float Ω 系统/端口/负载阻抗（>0，缺省 50）"),),
    required=(),
)
def gysel_core_synthesize(z0_ohm: float = 50.0) -> dict[str, Any]:
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(
            f"gysel_core_synthesize: z0_ohm 必须 >0，得到 {z0!r}")
    z_arm = math.sqrt(2.0) * z0
    z_iso = z0
    z_bridge = z0
    g = 1.0 / math.sqrt(2.0)

    # 偶/奇半电路验证（有限代理端接，两组缩比证明收敛到虚开路/虚地极限）
    ver: list[dict[str, float]] = []
    for proxy_open, proxy_short in ((_PROXY_OPEN / 1000.0, _PROXY_SHORT * 1000.0),
                                    (_PROXY_OPEN, _PROXY_SHORT)):
        # 偶模：对称面虚开路（桥带中点开路代理）+P1 端口拆半 2Z0
        zin_bridge = _quarter_wave_zin(z_bridge, proxy_open)
        d1 = _parallel(z0, zin_bridge)
        zin_iso = _quarter_wave_zin(z_iso, d1)
        zin_arm = _quarter_wave_zin(z_arm, 2.0 * z0)
        zin_e = _parallel(zin_arm, zin_iso)
        gamma_e = (zin_e - z0) / (zin_e + z0)
        # 奇模：对称面虚地（P1/桥带中点接地代理）
        zin_bridge_o = _quarter_wave_zin(z_bridge, proxy_short)
        d1_o = _parallel(z0, zin_bridge_o)
        zin_iso_o = _quarter_wave_zin(z_iso, d1_o)
        zin_arm_o = _quarter_wave_zin(z_arm, proxy_short)
        zin_o = _parallel(zin_arm_o, zin_iso_o)
        gamma_o = (zin_o - z0) / (zin_o + z0)
        ver.append({
            "proxy_open_ohm": proxy_open,
            "gamma_e": abs(gamma_e),
            "gamma_o": abs(gamma_o),
            "zin_e_over_z0": zin_e / z0,
            "zin_o_over_z0": zin_o / z0,
        })
    worst = max(max(v["gamma_e"], v["gamma_o"]) for v in ver)

    s_ideal = [
        [[0.0, 0.0], [-0.0, -g], [-0.0, -g]],
        [[-0.0, -g], [0.0, 0.0], [0.0, 0.0]],
        [[-0.0, -g], [0.0, 0.0], [0.0, 0.0]],
    ]
    return {
        "z0_ohm": z0,
        "z_arm_ohm": round(z_arm, 12),
        "z_iso_ohm": round(z_iso, 12),
        "z_bridge_ohm": round(z_bridge, 12),
        "z_load_ohm": round(z0, 12),
        "arm_electrical_deg": 90.0,
        "iso_electrical_deg": 90.0,
        "bridge_electrical_deg": 180.0,
        "split_db": round(-10.0 * math.log10(2.0), 12),
        "even_odd_verification": [
            {k: (round(v, 15) if isinstance(v, float) else v)
             for k, v in item.items()} for item in ver],
        "gamma_max_residual": round(worst, 18),
        "s_matrix_f0": s_ideal,
        "isolation_s32_linear": 0.0,
        "isolation_s32_db": None,
        "match_sii_linear": 0.0,
        "note": (
            "理想 f0 口径：S21=S31=−j/√2（臂 −90°+均分）、全对角与 S32=0；"
            "互易 S=Sᵀ 成立，Δ1/Δ2 负载吸收→非无耗不幺正（如实注记）；偶/"
            "奇验证=有限代理端接两组缩比（proxy_open 1e9→1e12、proxy_short "
            "1e-9→1e-12），γ 残差随代理收敛到 0（虚开路/虚地极限的数值载"
            "体）；大功率口径=隔离负载外置可独立散热；几何尺寸/叠层综合走 "
            "core/synthesis.synthesize_gysel_model（模板级，互不重复）"),
        "source": _SOURCES["synth"],
    }


# ─── 键 2：五线六节点导纳网络精确频响 ────────────────────────────────────────

_NODES = ("P1", "P2", "P3", "D1", "D2", "M")
_P = (0, 1, 2)        # 端口节点
_I = (3, 4, 5)        # 内部节点（Δ1/Δ2/桥带中点）
_SIN_GUARD = 1e-9


def _stamp_line(y: np.ndarray, ia: int, ib: int, zc: float,
                th: float, f: float) -> None:
    """无耗线导纳参量盖章：Y_self=−j·cotθ/Zc、Y_mutual=j/(Zc·sinθ)。"""
    s = math.sin(th)
    if abs(s) < _SIN_GUARD:
        raise ValueError(
            f"gysel_frequency_response: f={f} GHz 触及线节 θ=kπ 奇异点"
            f"（f=2k·f0 族；显式拒绝）")
    ys = -1j * math.cos(th) / (s * zc)
    ym = 1j / (zc * s)
    y[ia, ia] += ys
    y[ib, ib] += ys
    y[ia, ib] += ym
    y[ib, ia] += ym


def _build_y(f: float, f0: float, z0: float,
             with_bridge: bool = True) -> np.ndarray:
    """导纳矩阵（全部线节 λ/4@f0；桥带按中点 M 拆两半段）。

    with_bridge=False 为判废对照口径：五节点网络（无 M——M 在无桥带时
    悬空，保留会使 Y 奇异），电气语义=无桥带朴素拓扑（#206 判废锚）。
    """
    n_node = 6 if with_bridge else 5
    y = np.zeros((n_node, n_node), dtype=complex)
    th = (math.pi / 2.0) * (f / f0)
    z_arm = math.sqrt(2.0) * z0
    _stamp_line(y, 0, 1, z_arm, th, f)   # 臂 A：P1–P2
    _stamp_line(y, 0, 2, z_arm, th, f)   # 臂 B：P1–P3
    _stamp_line(y, 1, 3, z0, th, f)      # 隔离线 C：P2–Δ1
    _stamp_line(y, 2, 4, z0, th, f)      # 隔离线 D：P3–Δ2
    if with_bridge:
        _stamp_line(y, 3, 5, z0, th, f)  # 桥带前半：Δ1–M
        _stamp_line(y, 5, 4, z0, th, f)  # 桥带后半：M–Δ2
    y[3, 3] += 1.0 / z0                  # Δ1 外置负载
    y[4, 4] += 1.0 / z0                  # Δ2 外置负载
    return y


def _solve_s(y: np.ndarray, z0: float) -> tuple[np.ndarray, np.ndarray]:
    """内节点消元 → S(3×3) 与全节点电压（a=[1,0,0] 激励口径）。"""
    pp = np.ix_(_P, _P)
    pi = np.ix_(_P, _I)
    ip = np.ix_(_I, _P)
    ii = np.ix_(_I, _I)
    y_red = y[pp] - y[pi] @ np.linalg.solve(y[ii], y[ip])
    eye3 = np.eye(3, dtype=complex)
    s = np.linalg.solve(eye3 + z0 * y_red, eye3 - z0 * y_red)
    a_vec = np.array([1.0, 0.0, 0.0], dtype=complex)
    b_vec = s @ a_vec
    inj = np.zeros(6, dtype=complex)
    # 功率波口径（V=√Z0·(a+b)、I=(a−b)/√Z0）：端口注入电流按 √Z0 归一
    inj[:3] = (a_vec - b_vec) / math.sqrt(z0)
    v_full = np.linalg.solve(y, inj)
    return s, v_full


@register_calculator(
    "gysel_frequency_response",
    "Gysel 功分器精确频响：五线六节点导纳网络（臂×2=√2·Z0 λ/4@f0、隔离"
    "线×2=Z0 λ/4@f0、桥带按中点 M 拆两半段、Δ1/Δ2 外置 Z0 负载）逐频精"
    "确解——S11/S21/S31 dB+P2↔P3 隔离+幅度失衡+耗散守恒残差；f0 锚 vs 理"
    "想矩阵（−3.0103dB/全匹配/全隔离）逐位 ≤1e-9；无桥带判废对照字段"
    "（桥带必要性 #206 同口径）。θ=kπ（f=2k·f0）显式拒绝",
    (("f0_ghz", "float GHz 中心频率（线节长=λ/4@f0；>0）"),
     ("freq_ghz", "array GHz 频率轴（>0；避开 f=2k·f0 奇异点）"),
     ("z0_ohm", "float Ω 系统/端口/负载阻抗（>0，缺省 50）")),
    required=("f0_ghz", "freq_ghz"),
)
def gysel_frequency_response(f0_ghz: float, freq_ghz: list,
                             z0_ohm: float = 50.0) -> dict[str, Any]:
    f0 = _finite(f0_ghz, "f0_ghz")
    if f0 <= 0.0:
        raise ValueError(
            f"gysel_frequency_response: f0_ghz 必须 >0，得到 {f0_ghz!r}")
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(
            f"gysel_frequency_response: z0_ohm 必须 >0，得到 {z0!r}")
    freqs = [float(v) for v in freq_ghz]
    if not freqs:
        raise ValueError("gysel_frequency_response: freq_ghz 不能为空")
    if any(f <= 0.0 for f in freqs):
        raise ValueError("gysel_frequency_response: 频率须 >0")

    g = 1.0 / math.sqrt(2.0)
    s_ideal = np.array([[0, -1j * g, -1j * g],
                        [-1j * g, 0, 0],
                        [-1j * g, 0, 0]], dtype=complex)

    def _solve_at(f: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        y = _build_y(f, f0, z0)
        s, v = _solve_s(y, z0)
        return y, s, v

    rows: list[dict[str, float]] = []
    energy_dev = 0.0
    recip_dev = 0.0
    for f in freqs:
        _, s, v = _solve_at(f)
        recip_dev = max(recip_dev, float(np.max(np.abs(s - s.T))))
        p_diss = (abs(v[3]) ** 2 + abs(v[4]) ** 2) / z0
        p_out = float(np.sum(np.abs(s[:, 0]) ** 2))
        energy_dev = max(energy_dev, abs(1.0 - p_out - p_diss))
        s21_db = 20.0 * math.log10(max(abs(s[1, 0]), 1e-300))
        s31_db = 20.0 * math.log10(max(abs(s[2, 0]), 1e-300))
        rows.append({
            "s11_db": 20.0 * math.log10(max(abs(s[0, 0]), 1e-300)),
            "s21_db": s21_db,
            "s31_db": s31_db,
            "s32_db": 20.0 * math.log10(max(abs(s[2, 1]), 1e-300)),
            "imbalance_db": s21_db - s31_db,
        })

    # f0 锚（θ=π/2 正则）与判废对照（去桥带：五节点朴素拓扑，#206 口径）
    _, s_f0, _ = _solve_at(f0)
    f0_ideal_dev = float(np.max(np.abs(s_f0 - s_ideal)))
    y_nb = _build_y(f0, f0, z0, with_bridge=False)
    pp = np.ix_((0, 1, 2), (0, 1, 2))
    pi = np.ix_((0, 1, 2), (3, 4))
    ip = np.ix_((3, 4), (0, 1, 2))
    ii = np.ix_((3, 4), (3, 4))
    y_red_nb = y_nb[pp] - y_nb[pi] @ np.linalg.solve(y_nb[ii], y_nb[ip])
    eye3 = np.eye(3, dtype=complex)
    s_nb = np.linalg.solve(eye3 + z0 * y_red_nb, eye3 - z0 * y_red_nb)
    return {
        "f0_ghz": f0,
        "z0_ohm": z0,
        "freq_ghz": [round(f, 9) for f in freqs],
        "s11_db": [round(r["s11_db"], 6) for r in rows],
        "s21_db": [round(r["s21_db"], 6) for r in rows],
        "s31_db": [round(r["s31_db"], 6) for r in rows],
        "s32_db": [round(r["s32_db"], 6) for r in rows],
        "imbalance_db": [round(r["imbalance_db"], 9) for r in rows],
        "s21_at_f0_db": round(20.0 * math.log10(max(abs(s_f0[1, 0]), 1e-300)),
                              9),
        "s31_at_f0_db": round(20.0 * math.log10(max(abs(s_f0[2, 0]), 1e-300)),
                              9),
        "s32_at_f0_db": round(20.0 * math.log10(max(abs(s_f0[2, 1]), 1e-300)),
                              9),
        "f0_ideal_matrix_dev": round(f0_ideal_dev, 15),
        "dissipation_conservation_max_dev": round(energy_dev, 15),
        "reciprocity_max_dev": round(recip_dev, 18),
        "no_bridge_s21_at_f0_db": round(
            20.0 * math.log10(max(abs(s_nb[1, 0]), 1e-300)), 6),
        "note": (
            "精确电路口径（无耗线+外置电阻负载；桥带按中点 M 拆两 λ/4 半段"
            "——连续 λ/2 在 θ=kπ 的 Y 参量奇异的正则化，电气等效不变）；f0 "
            "锚=同网络解 vs 理想闭式矩阵（−3.0103dB/匹配/隔离）最大偏差；"
            "no_bridge_* 为判废对照（五节点朴素拓扑、无桥带，带心 S21 偏离 "
            "−3.01dB=桥带是隔离必要环节，#206 同口径）；f=2k·f0 处线节 "
            "θ=kπ 显式拒绝"),
        "source": _SOURCES["resp"],
    }
