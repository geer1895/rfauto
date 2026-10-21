"""群时延均衡器族（架构批 W2-S7，R2_core_tier3 §③ D9）：一阶/二阶
全通节群时延整形闭式+级联频响（纯综合面）。

两键：gd_allpass_section_synthesize（全通节设计——一阶 τ_dc 参数化/
二阶 f0×Q 或 f0×τ_peak 参数化，零极点镜像构造+延迟特征量）/
gd_equalizer_cascade_response（级联逐频响应——总群时延+|S21| 平坦度+
相位+级联可加性残差）。

与既有面的边界（#222 triple-grep 证据，2026-10-18 实测）
--------------------------------------------------------
- core/si_channel.py group_delay_s/ calc_families/kqe.py qe_group_delay=
  信道表征/提取面（从响应数据提群时延）；objectives/mask_filter 等=
  幅度规格面；本族=**均衡器综合面**（由目标时延构造全通零极点），提取
  面数据的消费方，方向相反不并入。
- 既有 all_pass 命中均为布尔语义误中（butler_matrix ``all_pass: bool``、
  mask_filter_synthesis ``all(s["pass"])``）——全通网络综合面全仓零命中。

物理口径（docstring 写死，#1c/#300 出处纪律；#118 锚树见
tests/unit/test_w2s7_ruthroff_gd_drift.py）
--------------------------------------------------------
- **一阶全通节**：H(s)=(s−a)/(s+a)（a>0：极点 −a、零点 +a=极点关于原
  点镜像）；H(jω) 相位 φ=−2·arctan(ω/a)，群时延
  τ_g(ω)=2a/(a²+ω²)；直流时延 τ_dc=2/a；|H|≡1（全通定义恒等式）。
  设计参数化：τ_dc 直接给 a=2/τ_dc。
- **二阶全通节**：H(s)=(s²−(ω0/Q)s+ω0²)/(s²+(ω0/Q)s+ω0²)；群时延
  τ_g(ω)=2(ω0/Q)(ω²+ω0²)/[(ω0²−ω²)²+(ω0ω/Q)²]；谐振峰
  τ_pk=τ_g(ω0)=4Q/ω0；直流时延 τ_dc=2/(Qω0)；|H|≡1。
  设计参数化双档：q 直接给，或 τ_peak 给 Q=τ_pk·ω0/4（恰给其一）。
- **级联**：H=Π H_i、τ_g=Σ τ_g,i（级联时延可加性）、|S21|≡1；相位=
  逐节相位和（unwrap 后线性可加）。
- **群时延曲线积分语义**（任务书锚）：τ_g(ω)=−dφ/dω ⇒
  ∫₀^∞ τ_g dω = φ(0)−φ(∞) = order·π（一阶 π/二阶 2π——相位总旋转量恒
  等式；测试侧数值积分钉）。零极点镜像恒等式：z_i=−p_i（D(−s)/D(s)
  构造，逐位 0 残差）。
- Cauer 桥 T 实现口径：一阶/二阶全通的集总实现为 Cauer 桥 T 网络（元件
  值依赖终端阻抗与实现拓扑，本族只到**传输零极点/频响层**——元件综合
  无终端阻抗口径不虚构，UNVERIFIED 如实不做）。

数值锚（#118 独立路线，测试侧实现）
- |S21|≡1：级联频响 s21_db 全频轴 |dev|≤1e-12（全通定义）。
- 零极点镜像：z_i+p_i 逐位 0（构造定理）。
- 闭式时延测试侧独立重算 ≤1e-12；级联可加性 total−Σsection ≤1e-15。
- 目标时延→零极点→频响回收闭环（τ_dc/τ_peak 设计值回收 ≤1e-9，
  #340 回收钉范式）。

守卫：order∈{1,2} 白名单；tau_dc_s/q/tau_peak_s/f0_ghz>0；二阶 q 与
tau_peak_s 恰给其一；级联 sections 非空、freq_ghz 非空且 >0；级联节数
上限 32（防滥用）。数值 0.0 合法（判缺失 is not None，#364④）；无
``__all__``（公开 API 快照口径）。

接口：纯函数零 IO；math/cmath 本征闭式；返回 JSON 可序列化结构（复数
拆 re/im 出口，dB/秒/弧度实数面）。

出处（全通网络教科书恒等式；#118 锚树）：
- gd_allpass_section_synthesize/gd_equalizer_cascade_response：一阶/
  二阶全通节 H(s) 恒等式与群时延闭式（滤波/控制教科书经典式，模块
  docstring 逐项推导在档；|H|≡1/级联时延可加性恒等面测试侧独立互证，
  #118 锚树=tests/unit/test_w2s7_ruthroff_gd_drift.py）。
"""

from __future__ import annotations

import cmath
import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

_MAX_CASCADE_SECTIONS = 32


def _first_order(a: float, w: float) -> tuple[complex, float]:
    """一阶节 H(jω) 与群时延闭式；a=正实极点参数。"""
    h = (1j * w - a) / (1j * w + a)
    tau = 2.0 * a / (a * a + w * w)
    return h, tau


def _second_order(w0: float, q: float, w: float) -> tuple[complex, float]:
    """二阶节 H(jω) 与群时延闭式；w0=谐振角频率、q=品质因数。"""
    num = (1j * w) ** 2 - (w0 / q) * (1j * w) + w0 * w0
    den = (1j * w) ** 2 + (w0 / q) * (1j * w) + w0 * w0
    h = num / den
    tau = (2.0 * (w0 / q) * (w * w + w0 * w0)) / (
        (w0 * w0 - w * w) ** 2 + (w0 * w / q) ** 2)
    return h, tau


def _section_poles_zeros(order: int, a: float | None,
                         w0: float | None, q: float | None
                         ) -> list[tuple[complex, complex]]:
    """逐节 (极点, 零点) 对；零点=−极点（D(−s)/D(s) 镜像构造）。"""
    pairs: list[tuple[complex, complex]] = []
    if order == 1:
        p = complex(-a)
        pairs.append((p, -p))
        return pairs
    sigma = w0 / (2.0 * q)
    if q > 0.5:
        wd = w0 * math.sqrt(1.0 - 1.0 / (4.0 * q * q))
        p1 = complex(-sigma, wd)
        p2 = complex(-sigma, -wd)
    else:
        p1 = complex(-sigma + w0 * math.sqrt(0.25 / (q * q) - 1.0))
        p2 = complex(-sigma - w0 * math.sqrt(0.25 / (q * q) - 1.0))
    pairs.append((p1, -p1))
    pairs.append((p2, -p2))
    return pairs


def _req_finite(value: Any, name: str) -> float:
    """条件必填参数收敛：None 显式报错（_finite 不收 None，TypeError 面）。"""
    if value is None:
        raise ValueError(f"{name} 必填（本档缺失）")
    return _finite(value, name)


def _resolve_section(idx: int, spec: dict) -> tuple[int, float, float,
                                                     float, float]:
    """级联节规格收敛：返回 (order, a, w0, q, tau_dc_s)。

    一阶：a=2/tau_dc_s；二阶：q/tau_peak_s 恰给其一（τ_pk 给
    Q=τ_pk·ω0/4）。非法显式报错。
    """
    tag = f"sections[{idx}]"
    if not isinstance(spec, dict):
        raise ValueError(f"{tag}: 节规格须为 dict，得到 {type(spec)!r}")
    order = spec.get("order")
    if order not in (1, 2):
        raise ValueError(
            f"{tag}.order 必须 ∈{{1,2}}，得到 {order!r}")
    order = int(order)
    if order == 1:
        tau_dc = _req_finite(spec.get("tau_dc_s"), f"{tag}.tau_dc_s")
        if tau_dc <= 0.0:
            raise ValueError(
                f"{tag}.tau_dc_s 必须 >0，得到 {tau_dc!r}")
        return 1, 2.0 / tau_dc, 0.0, 0.0, tau_dc
    f0 = _req_finite(spec.get("f0_ghz"), f"{tag}.f0_ghz")
    if f0 <= 0.0:
        raise ValueError(f"{tag}.f0_ghz 必须 >0，得到 {f0!r}")
    w0 = 2.0 * math.pi * f0 * 1e9
    q_raw = spec.get("q")
    tau_pk_raw = spec.get("tau_peak_s")
    if (q_raw is None) == (tau_pk_raw is None):
        raise ValueError(
            f"{tag}: 二阶节 q 与 tau_peak_s 必须恰给其一（得到 q={q_raw!r}"
            f"，tau_peak_s={tau_pk_raw!r}）")
    if q_raw is not None:
        q = _finite(q_raw, f"{tag}.q")
        if q <= 0.0:
            raise ValueError(f"{tag}.q 必须 >0，得到 {q!r}")
    else:
        tau_pk = _finite(tau_pk_raw, f"{tag}.tau_peak_s")
        if tau_pk <= 0.0:
            raise ValueError(
                f"{tag}.tau_peak_s 必须 >0，得到 {tau_pk!r}")
        q = tau_pk * w0 / 4.0
    return 2, 0.0, w0, q, 2.0 / (q * w0)


@register_calculator(
    "gd_allpass_section_synthesize",
    "全通均衡节综合：一阶/二阶全通节（零极点镜像 D(−s)/D(s) 构造）群时"
    "延整形设计——一阶 τ_dc 参数化、二阶 f0×Q 或 f0×τ_peak 参数化；出零"
    "极点/系数/τ_dc/τ_pk 特征量；|H|≡1 全通恒等与 ∫τ dω=order·π 相位"
    "旋转恒等式为族锚；元件级 Cauer 桥 T 实现无终端口径 UNVERIFIED 不做",
    (("order", "int 节阶数（1|2）"),
     ("tau_dc_s", "float s 一阶节直流群时延目标（order=1 必给，>0）"),
     ("f0_ghz", "float GHz 二阶节谐振频率（order=2 必给，>0）"),
     ("q", "float 二阶节品质因数（与 tau_peak_s 恰给其一，>0）"),
     ("tau_peak_s", "float s 二阶节谐振峰群时延（与 q 恰给其一，>0）")),
    required=("order",),
)
def gd_allpass_section_synthesize(order: int, tau_dc_s: float | None = None,
                                  f0_ghz: float | None = None,
                                  q: float | None = None,
                                  tau_peak_s: float | None = None
                                  ) -> dict[str, Any]:
    spec = {"order": order, "tau_dc_s": tau_dc_s, "f0_ghz": f0_ghz,
            "q": q, "tau_peak_s": tau_peak_s}
    o, a, w0, qq, tau_dc = _resolve_section(0, spec)
    tau_pk = 4.0 * qq / w0 if o == 2 else 0.0
    pairs = _section_poles_zeros(o, a, w0, qq)
    mirror_resid = max(abs(z + p) for p, z in pairs)
    if o == 1:
        poles = [{"re": p.real, "im": p.imag} for p, _z in pairs]
        zeros = [{"re": z.real, "im": z.imag} for _p, z in pairs]
        num_s = [1.0, -a]
        den_s = [1.0, a]
        note = (
            "一阶全通节 H(s)=(s−a)/(s+a)：零点 +a=极点 −a 关于原点镜像；"
            "τ_g(ω)=2a/(a²+ω²)、τ_dc=2/a；∫₀^∞ τ_g dω=π（相位总旋转恒"
            "等式）；|H|≡1（全通定义）")
        source = (
            "教科书一阶全通网络（零极点镜像构造 D(−s)/D(s)）；R2_core_"
            "tier3 D9 立项口径")
    else:
        poles = [{"re": p.real, "im": p.imag} for p, _z in pairs]
        zeros = [{"re": z.real, "im": z.imag} for _p, z in pairs]
        num_s = [1.0, -w0 / qq, w0 * w0]
        den_s = [1.0, w0 / qq, w0 * w0]
        bw_hz = (w0 / qq) / (2.0 * math.pi) / 1e9
        note = (
            f"二阶全通节 H(s)=(s²−(ω0/Q)s+ω0²)/(s²+(ω0/Q)s+ω0²)：零点="
            f"极点关于原点镜像；τ_g(ω0)=4Q/ω0=τ_pk、τ_dc=2/(Qω0)；3dB "
            f"带宽 ω0/Q={bw_hz:.9g} GHz；∫₀^∞ τ_g dω=2π（相位总旋转恒等"
            "式）；|H|≡1（全通定义）")
        source = (
            "教科书二阶全通网络（零极点镜像构造）；τ_pk=4Q/ω0 经典谐振"
            "峰口径；R2_core_tier3 D9 立项口径")
    return {
        "order": o,
        "tau_dc_s": round(tau_dc, 18),
        "tau_peak_s": (round(tau_pk, 18) if o == 2 else None),
        "q": (round(qq, 15) if o == 2 else None),
        "f0_ghz": (round(f0_ghz, 15) if o == 2 and f0_ghz is not None
                   else None),
        "poles": poles,
        "zeros": zeros,
        "num_s_coefficients": num_s,
        "den_s_coefficients": den_s,
        "zero_pole_mirror_max_dev": round(mirror_resid, 18),
        "allpass_identity": "|H(jω)|≡1",
        "phase_integral_identity": f"∫₀^∞ τ_g dω = {o}·π",
        "note": note,
        "source": source,
    }


@register_calculator(
    "gd_equalizer_cascade_response",
    "群时延均衡级联频响：一阶/二阶全通节级联逐频精确响应——总群时延（级"
    "联可加性）/|S21| dB（全通恒等 |S21|≡1 平坦度）/相位（unwrap）/逐节"
    "贡献；均衡平坦度指标（带内 max dev）；零极点镜像残差逐节自报",
    (("freq_ghz", "array GHz 频率轴（>0）"),
     ("sections", "array 节规格列表（每节 {order:1,tau_dc_s} 或 "
                  "{order:2,f0_ghz,q|tau_peak_s}，≤32 节）")),
    required=("freq_ghz", "sections"),
)
def gd_equalizer_cascade_response(freq_ghz: list,
                                  sections: list) -> dict[str, Any]:
    tag = "gd_equalizer_cascade_response"
    freqs = [float(v) for v in freq_ghz]
    if not freqs:
        raise ValueError(f"{tag}: freq_ghz 不能为空")
    if any(f <= 0.0 for f in freqs):
        raise ValueError(f"{tag}: 频率须 >0")
    if not isinstance(sections, list) or not sections:
        raise ValueError(f"{tag}: sections 须为非空列表")
    if len(sections) > _MAX_CASCADE_SECTIONS:
        raise ValueError(
            f"{tag}: sections 节数 {len(sections)} 超上限 "
            f"{_MAX_CASCADE_SECTIONS}（防滥用守卫）")
    resolved = [_resolve_section(i, s) for i, s in enumerate(sections)]
    total_order = sum(r[0] for r in resolved)
    if total_order > 2 * _MAX_CASCADE_SECTIONS:
        raise ValueError(f"{tag}: 总阶数超上限（防滥用守卫）")

    total_phase = [0.0] * len(freqs)
    tau_total = [0.0] * len(freqs)
    h_total = [1.0 + 0.0j] * len(freqs)
    s21_db: list[float] = []
    per_section_tau_dc: list[float] = []
    mirror_resid_max = 0.0
    for r in resolved:
        o, a, w0, qq, tau_dc = r
        per_section_tau_dc.append(tau_dc)
        pairs = _section_poles_zeros(o, a, w0, qq)
        mirror_resid_max = max(max(abs(z + p) for p, z in pairs),
                               mirror_resid_max)
        for k, f in enumerate(freqs):
            w = 2.0 * math.pi * f * 1e9
            if o == 1:
                h, tau = _first_order(a, w)
            else:
                h, tau = _second_order(w0, qq, w)
            h_total[k] = h_total[k] * h
            tau_total[k] += tau
    # 相位：经典差分 unwrap（逐点相邻差 wrap 到 (−π,π] 后累加——unwrap
    # 保证连续；相邻差 >π 仅在全通节采样不足时可能出现，频轴责任在调用方）
    raw_phase = [cmath.phase(h) for h in h_total]
    total_phase[0] = raw_phase[0]
    for k in range(1, len(freqs)):
        d = raw_phase[k] - raw_phase[k - 1]
        while d > math.pi:
            d -= 2.0 * math.pi
        while d < -math.pi:
            d += 2.0 * math.pi
        total_phase[k] = total_phase[k - 1] + d
    s21_db = [20.0 * math.log10(max(abs(h), 1e-300)) for h in h_total]
    flat_dev = max(abs(v) for v in s21_db)
    return {
        "n_sections": len(sections),
        "total_order": total_order,
        "per_section_tau_dc_s": [round(v, 18) for v in per_section_tau_dc],
        "tau_dc_total_s": round(sum(per_section_tau_dc), 18),
        "freq_ghz": [round(f, 9) for f in freqs],
        "group_delay_s": [round(v, 18) for v in tau_total],
        "s21_db": [round(v, 12) for v in s21_db],
        "s21_flatness_max_dev_db": round(flat_dev, 15),
        "phase_rad_unwrapped": [round(v, 12) for v in total_phase],
        "zero_pole_mirror_max_dev": round(mirror_resid_max, 18),
        "note": (
            "全通级联：|S21|≡1（全通定义恒等式，平坦度残差即数值精度）；"
            "总群时延=逐节可加和（级联时延可加性）；相位 unwrap 后线性可"
            "加；零极点镜像 z_i=−p_i 残差逐节自报（构造定理）；∫₀^∞ τ_g "
            "dω=total_order·π（相位总旋转语义，测试侧数值积分钉）；元件级"
            " Cauer 桥 T 实现无终端口径 UNVERIFIED 不做"),
        "source": (
            "教科书全通网络级联（零极点镜像构造 D(−s)/D(s)）；一阶 "
            "τ_g=2a/(a²+ω²)、二阶 τ_g=2(ω0/Q)(ω²+ω0²)/[(ω0²−ω²)²+"
            "(ω0ω/Q)²] 闭式；R2_core_tier3 D9 立项口径"),
    }
