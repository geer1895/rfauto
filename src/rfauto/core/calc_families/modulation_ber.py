"""数字调制理论 BER/Eb-N0 族（aurora36 W4-A 席，R2 空白域 G3）。

出处（教科书经典闭式二级转引，详见下节公式口径）：
- modulation_ber_curve：BPSK/QPSK Pb=Q(√(2γb)) 与 square M-QAM Gray
  精确和式（Proakis, Digital Communications 5th ed. ch.4/QAM 节；
  Cho & Kim, IEEE Comm. Lett. 2005 square-QAM 同形逐项式）。
- required_ebn0：目标 BER→Eb/N0 反解（同上闭式；域内严格单调降
  二分反解，物理出处同曲线键）。
- coded_ber_estimate：码率能量扩张+固定净编码增益一阶粗估（工程
  惯例口径，如实标注粗估不冒充精确，G 取目标 BER 点净增益）。

三键：modulation_ber_curve（理论 BER 曲线）/ required_ebn0（目标 BER→
所需 Eb/N0 反解）/ coded_ber_estimate（级联编码一阶粗估）。

公式口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- Q 函数单源：Q(x) = 0.5·erfc(x/√2)（本模块 _qfunc，全族唯一实现，
  禁止第二份 erfc/Q 形态）。
- BPSK/QPSK（相干解调、AWGN、Gray 映射，比特能量口径 γb=Eb/N0 线性值）：

      Pb = Q(√(2·γb))

  QPSK 与 BPSK 在同比特能量口径下 BER 逐位相等（QPSK 每支路即 BPSK、
  Es/N0=2·Eb/N0，物理恒等，测试钉）。
- square M-QAM（M=16/64，Gray 映射，相干 AWGN）精确和式：

      Pb = 4(1−1/√M)/k · Σ_{i=1}^{√M/2} Q((2i−1)·√(3k·γb/(M−1)))，
      k = log2(M)

  （Proakis, *Digital Communications* 5th ed. QAM 节；Cho & Kim,
  IEEE Comm. Lett. 2005 同形逐项式。M=4 退化回 Q(√(2γb))。高 BER 端
  （≳0.1）和式渐失精确性，如实标注不作门。）
- 反解：γb→Pb 在域内严格单调降（Q 单调 + 正系数和式），dB 域二分
  200 轮（~1e-60 区间收敛，纯 math 零依赖，同 bethe_hole 反解惯例）。
  双精度下 BER 有效下限 1e-15（erfc 深尾下溢地板之上），target_ber
  低于此显式拒绝。
- 编码粗估（一阶）：仅计入码率能量扩张 + 固定净编码增益偏移

      γb_eff = γb + 10·lg(R_c) + G_coding    →  Pb = BER_theory(γb_eff)

  不建模打孔/交织/迭代译码瀑布区（G_coding 必须取目标 BER 点的净
  增益，如实施表/门限上限），结果为粗估口径（docstring 与输出 note
  双写死，#122 不冒充精确）。

数值锚（#118 独立来源；锚树 tests/unit/test_w4a_mod_radar.py）
- Q(3.026) = 1.2391e-3 ≈ 1.24e-3（任务书量级点）；
- BPSK @ Eb/N0=10 dB → 3.872e-6（文献通用值 ≈3.87e-6）；
- QPSK ≡ BPSK 全 γ 扫描逐位相等（物理恒等）；
- 反解锚：BPSK 目标 1e-5 → 9.5879 dB（文献表 9.588 dB）；目标 1e-3
  → 6.7895 dB（文献 6.79 dB）；16QAM 目标 1e-6 → 14.40 dB；
  64QAM 目标 1e-6 → 18.78 dB（文献表 ~14.4/~18.8 dB）；
- 曲线锚：16QAM @10 dB = 1.754e-3、64QAM @10 dB = 2.653e-2（文献
  常引值）。

守卫：ebn0_db 必须有限（标量或非空列表逐点校验）；target_ber ∈
[1e-15, 0.5)（>0.1 给 low_confidence 标注不拒绝）；scheme 未知名显式
拒绝；code_rate ∈ (0,1]；coding_gain_db 有限。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator

# 双精度 BER 有效下限（erfc 深尾下溢地板之上，任务书口径）
_BER_FLOOR = 1e-15
_SCHEMES = ("bpsk", "qpsk", "16qam", "64qam")
_K_BITS = {"bpsk": 1, "qpsk": 2, "16qam": 4, "64qam": 6}
_M_QAM = {"16qam": 16, "64qam": 64}
_SOURCES = {
    "bpsk": "Proakis Digital Communications 5ed ch.4 (coherent BPSK)",
    "qpsk": "Proakis 5ed ch.4 (Gray QPSK ≡ BPSK per-bit)",
    "16qam": "Proakis 5ed; Cho&Kim 2005 square-QAM Gray exact sum",
    "64qam": "Proakis 5ed; Cho&Kim 2005 square-QAM Gray exact sum",
}


def _qfunc(x: float) -> float:
    """Q 函数单源：Q(x)=0.5·erfc(x/√2)（全族唯一实现）。"""
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def _ber_bpsk(gamma_b: float) -> float:
    """相干 BPSK：Pb=Q(√(2γb))。"""
    return _qfunc(math.sqrt(2.0 * gamma_b))


def _ber_qam(m: int, gamma_b: float) -> float:
    """square M-QAM（Gray）精确和式（高 BER 端渐失精确性，见 docstring）。"""
    k = math.log2(m)
    sq = math.sqrt(m)
    pref = 4.0 * (1.0 - 1.0 / sq) / k
    x_base = math.sqrt(3.0 * k * gamma_b / (m - 1.0))
    total = 0.0
    for i in range(1, int(sq / 2) + 1):
        total += _qfunc((2.0 * i - 1.0) * x_base)
    return pref * total


def _ber(scheme: str, gamma_b: float) -> float:
    """按制式分派的 BER 闭式（scheme 已归一小写）。"""
    if scheme in ("bpsk", "qpsk"):
        return _ber_bpsk(gamma_b)
    return _ber_qam(_M_QAM[scheme], gamma_b)


def _normalize_scheme(scheme: str) -> str:
    s = str(scheme).strip().lower()
    if s not in _SCHEMES:
        raise ValueError(
            f"未知调制制式 {scheme!r}（支持: {'/'.join(_SCHEMES)}）")
    return s


def _normalize_ebn0_list(ebn0_db: Any, key: str = "ebn0_db") -> list[float]:
    """标量→单点列表；列表逐点有限校验（任务书越界显式拒绝口径）。"""
    vals = [ebn0_db] if isinstance(ebn0_db, (int, float)) else list(ebn0_db)
    if not vals:
        raise ValueError(f"{key} 不能为空列表")
    out: list[float] = []
    for v in vals:
        f = float(v)
        if not math.isfinite(f):
            raise ValueError(f"{key} 必须为有限数，得到 {v!r}")
        out.append(f)
    return out


def _ber_log10(ber: float) -> float | None:
    """log10 BER；深尾下溢为 0.0 时如实返 None（JSON 无 NaN/Inf 铁律）。"""
    return None if ber <= 0.0 else round(math.log10(ber), 12)


def _invert_ber_db(scheme: str, target_ber: float) -> float:
    """dB 域二分反解（BER 单调降，200 轮；域守卫见键 docstring）。"""
    lo, hi = -20.0, 60.0
    ber_lo = _ber(scheme, 10.0 ** (lo / 10.0))
    if target_ber >= ber_lo:
        raise ValueError(
            f"required_ebn0: target_ber={target_ber:g} 不低于闭式可反解上界"
            f"（γb={lo:g} dB 处理论 BER={ber_lo:.4g}）——目标 BER 过大")
    ber_hi = _ber(scheme, 10.0 ** (hi / 10.0))
    if target_ber <= ber_hi:
        raise ValueError(
            f"required_ebn0: target_ber={target_ber:g} 低于双精度闭式下限 "
            f"{_BER_FLOOR:g}（γb={hi:g} dB 处已下溢）——目标 BER 过小")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _ber(scheme, 10.0 ** (mid / 10.0)) > target_ber:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


@register_calculator(
    "modulation_ber_curve",
    "调制BER曲线：数字调制理论 BER 曲线（相干解调 AWGN、Gray 映射、比特能量口径 "
    "γb=Eb/N0）：bpsk/qpsk 闭式 Q(√(2γb))（QPSK≡BPSK 物理恒等）；"
    "16qam/64qam square-QAM Gray 精确和式 4(1−1/√M)/k·ΣQ((2i−1)·"
    "√(3kγb/(M−1)))。Q 函数单源 0.5·erfc(x/√2)。ebn0_db 标量或列表"
    "（列表返回曲线数组）；锚：BPSK@10dB=3.872e-6、Q(3.026)=1.239e-3、"
    "16QAM@10dB=1.754e-3。出处 Proakis 5ed ch.4 / Cho&Kim 2005",
    (("ebn0_db", "float|list dB Eb/N0（比特能量口径，标量或非空列表，"
      "逐点有限校验）"),
     ("scheme", "str 'bpsk'/'qpsk'/'16qam'/'64qam'（大小写不敏感）")),
    required=("ebn0_db", "scheme"),
)
def modulation_ber_curve(ebn0_db: Any, scheme: str) -> dict[str, Any]:
    s = _normalize_scheme(scheme)
    grid = _normalize_ebn0_list(ebn0_db)
    k = _K_BITS[s]

    ber_list: list[float] = []
    es_n0_list: list[float] = []
    log10_list: list[float | None] = []
    for gdb in grid:
        ber = _ber(s, 10.0 ** (gdb / 10.0))
        ber_list.append(ber)
        es_n0_list.append(round(gdb + 10.0 * math.log10(k), 6))
        log10_list.append(_ber_log10(ber))

    return {
        "scheme": s,
        "k_bits_per_symbol": k,
        "ebn0_db": [round(v, 9) for v in grid],
        "es_n0_db": es_n0_list,
        "ber": ber_list,
        "ber_log10": log10_list,
        "n_points": len(grid),
        "ber_zero_note": (
            "ber_log10=null 表示该点 BER 已低于双精度下溢地板（如实标注）"),
        "source": _SOURCES[s],
    }


@register_calculator(
    "required_ebn0",
    "所需Eb/N0：目标 BER→所需 Eb/N0 反解（dB 域二分，BER 单调降闭式同 "
    "modulation_ber_curve）：BPSK 锚 1e-5→9.5879 dB（文献 9.588）、"
    "1e-3→6.7895 dB（文献 6.79）；16QAM 1e-6→14.40 dB；64QAM "
    "1e-6→18.78 dB（文献表）。target_ber ∈ [1e-15, 0.5)（>0.1 如实标 "
    "low_confidence——square-QAM 和式高 BER 端渐失精确，不拒绝）；"
    "低于双精度下限/高于可反解上界显式拒绝。反解后前向回代自检",
    (("target_ber", "float - 目标误码率（[1e-15,0.5)，越大越接近闭式"
      "高 BER 失精确带）"),
     ("scheme", "str 'bpsk'/'qpsk'/'16qam'/'64qam'（大小写不敏感）")),
    required=("target_ber", "scheme"),
)
def required_ebn0(target_ber: float, scheme: str) -> dict[str, Any]:
    s = _normalize_scheme(scheme)
    t = float(target_ber)
    if not math.isfinite(t) or t < _BER_FLOOR or t >= 0.5:
        raise ValueError(
            f"required_ebn0: target_ber 必须在 [{_BER_FLOOR:g}, 0.5) 内，"
            f"得到 {target_ber!r}")
    gamma_db = _invert_ber_db(s, t)
    achieved = _ber(s, 10.0 ** (gamma_db / 10.0))
    if achieved <= 0.0 or abs(math.log10(achieved) - math.log10(t)) > 1e-6:
        raise ValueError(
            f"required_ebn0: 反解回代自检失败（target={t:g}, achieved="
            f"{achieved:g}）——内部错误，显式拒绝而非外推")
    return {
        "scheme": s,
        "target_ber": t,
        "required_ebn0_db": round(gamma_db, 6),
        "required_esn0_db": round(gamma_db + 10.0 * math.log10(_K_BITS[s]),
                                  6),
        "k_bits_per_symbol": _K_BITS[s],
        "achieved_ber": achieved,
        "low_confidence": bool(t > 0.1),
        "note": (
            "高 BER 端（>0.1）square-QAM 和式渐失精确性（粗估口径）；"
            "BPSK/QPSK 闭式全域精确"),
        "source": _SOURCES[s],
    }


@register_calculator(
    "coded_ber_estimate",
    "级联编码 BER 一阶粗估：γb_eff = ebn0_db + 10·lg(code_rate) + "
    "coding_gain_db → 理论 BER（闭式同 modulation_ber_curve）。仅计入"
    "码率能量扩张 + 固定净编码增益偏移（G 必须取目标 BER 点净增益），"
    "不建模打孔/交织/迭代译码瀑布区——粗估口径 docstring+note 双写死。"
    "锚：rate=1/2 且 gain=5dB ⇔ 未编码 +1.9897 dB 恒等（测试钉）。"
    "code_rate ∈ (0,1]，coding_gain_db 有限（可为负=弱码）",
    (("scheme", "str 'bpsk'/'qpsk'/'16qam'/'64qam'（大小写不敏感）"),
     ("ebn0_db", "float dB 信息比特能量口径 Eb/N0（未编码等效）"),
     ("code_rate", "float - 码率 R_c=k/n（(0,1]，默认 1.0=无编码）"),
     ("coding_gain_db", "float dB 目标 BER 点净编码增益（有限，默认 "
      "0.0；弱码可为负）")),
    required=("scheme", "ebn0_db"),
)
def coded_ber_estimate(scheme: str, ebn0_db: float,
                       code_rate: float = 1.0,
                       coding_gain_db: float = 0.0) -> dict[str, Any]:
    s = _normalize_scheme(scheme)
    g = float(ebn0_db)
    if not math.isfinite(g):
        raise ValueError(
            f"coded_ber_estimate: ebn0_db 必须为有限数，得到 {ebn0_db!r}")
    r = float(code_rate)
    if not math.isfinite(r) or r <= 0.0 or r > 1.0:
        raise ValueError(
            f"coded_ber_estimate: code_rate 必须在 (0,1] 内，得到 "
            f"{code_rate!r}")
    gain = float(coding_gain_db)
    if not math.isfinite(gain):
        raise ValueError(
            f"coded_ber_estimate: coding_gain_db 必须为有限数，得到 "
            f"{coding_gain_db!r}")
    effective = g + 10.0 * math.log10(r) + gain
    ber = _ber(s, 10.0 ** (effective / 10.0))
    return {
        "scheme": s,
        "ebn0_db": round(g, 9),
        "code_rate": r,
        "coding_gain_db": gain,
        "ebn0_effective_db": round(effective, 6),
        "rate_expansion_db": round(10.0 * math.log10(r), 6),
        "ber": ber,
        "ber_log10": _ber_log10(ber),
        "note": (
            "一阶粗估：只含码率能量扩张+固定净编码增益偏移；不含打孔/"
            "交织/迭代译码瀑布区（G_coding 须取目标 BER 点净增益）"),
        "source": _SOURCES[s],
    }
