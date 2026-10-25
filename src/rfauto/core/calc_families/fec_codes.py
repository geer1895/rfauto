"""FEC 块码族（aurora_g W1-S2 席域 C2，R2_core_tier4 §③ Top3 设计案）。

出处（原文/教科书经典闭式二级转引，详见下节公式口径）：
- hamming_code_design：R. W. Hamming, Bell Syst. Tech. J. 1950；Lin &
  Costello, Error Control Coding 2nd ed. ch.3（Hamming bound 球填充界，
  完全系完全码取等）。
- reed_solomon_capacity：Reed & Solomon 1960；MDS=Singleton 1964 界
  取等（RS(255,223) GF(256) NASA/CCSDS 标准码锚）。
- coded_ebn0_requirement：硬判译码 union bound 一阶口径（Lin & Costello
  2ed / Clark & Cain 1981）。

三键：hamming_code_design（(n,k) Hamming 码参数+Hamming bound 判定）/
reed_solomon_capacity（RS(n,k) MDS 纠错能力闭式）/ coded_ebn0_requirement
（硬判 union bound 编码后 BER 反解 → 目标 BER 点净编码增益 G 产生面）。
官方缺口背书（#122 如实口径，modulation_ber.py docstring 逐字）："仅计入
码率能量扩张 + 固定净编码增益偏移（G 必须取目标 BER 点净增益）"——
G 的**产生面**（具体码型闭式）此前全仓零：``bch|reed.solomon|ldpc|
viterbi|hamming.bound|minimum.distance`` 全零（R2 §② 方向 2 零命中判据；
``hamming`` 字面命中=窗函数/汉明距离误中三处剔除）。

公式口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- Hamming 码（R. W. Hamming, Bell Syst. Tech. J. 1950；Lin & Costello
  *Error Control Coding* 2nd ed. ch.3）：m 位校验 →

      n = 2^m − 1，k = n − m，d_min = 3，t = ⌊(d_min−1)/2⌋ = 1

  Hamming bound（球填充界）2^k·Σ_{i=0}^{t}C(n,i) ≤ 2^n：t=1 时
  2^k·(1+n) ≤ 2^n；n=2^m−1 全系**完全码**（取等，perfect 判定逐位整数
  算术，零浮点）。缩短/扩展 Hamming 不在本键（边界节）。
- RS 码（Reed & Solomon 1960；MDS：Singleton 1964 界取等）：

      d_min = n − k + 1（Singleton 恒等式 n−k ≥ d_min−1 取等=MDS）
      t = ⌊(n−k)/2⌋（符号错），e 错+擦除 f 并行纠正 2e+f ≤ n−k
      连续突发保证：b ≤ (t−1)·m_sym + 1 bit（最坏对齐口径，教科书式）

  锚：RS(255,223)（GF(256)，NASA/CCSDS 标准码）d=33 → t=16 逐位。
- 编码增益产生面（硬判译码 union bound 一阶口径；Lin & Costello 2ed /
  Clark & Cain 1981）：码率能量扩张后信道原始误码率

      p = BER_theory(γ_b + 10·lg(k/n))（BER 闭式单源复用 modulation_ber，
      Q 函数全族唯一实现纪律）

  译码后 BER 的 union bound 估计（t 纠错后剩余比特错的截断均值/块长）：

      P_b ≤ (1/n)·Σ_{i=t+1}^{n} i·C(n,i)·p^i·(1−p)^(n−i)

  P_b 对 γ_b 单调降（p 单调降 + 二项上尾均值随 p 随机占优递增，测试
  数值扫描复核）→ dB 域二分反解 γ_b^coded(P_b=target)。净编码增益

      G = γ_b^uncoded(target) − γ_b^coded(target)

  **诚实口径**：union bound 高估剩余误码 → G 为真增益的**保守下界估
  计**（note+source 双写死）；t=0 且 k=n 时截断均值恒等还原二项均值
  Σi·C(n,i)p^i(1−p)^(n−i) = n·p → P_b ≡ p → G ≡ 0（d=1 恒等锚，精确到
  浮点）。软判/打孔/交织/迭代译码（LDPC/Turbo 瀑布区）不在本面如实
  不建模——瀑布区实际增益高于本口径，故"下界"方向恒成立。
- 与消费链握手：coded_ber_estimate（γ_eff = γ_b + 10lg(R_c) + G）的 G
  语义=码率扩张**后**信道上的增益；本键输出双口径显式分列——
  net_coding_gain_db=γ_b^unc−γ_b^coded（教科书净增益，信息比特口径）与
  coded_ber_estimate_gain_db=净增益−10lg(R_c)（回灌面，闭环复现
  target BER）。两口径差=码率扩张记账项（#122 如实，防双计）；闭环
  恒等是**接线钉**非独立物理裁判（bisection 与 coded_ber_estimate 同源
  _ber），物理量级由独立实现互证与单调结构测试另钉。

边界防撞（#222 triple-grep，2026-10-19 实测）
--------------------------------------------------------
- modulation_ber.coded_ber_estimate=G 的**消费面**（输入参数，docstring
  自证缺口——本族为其产生面）；required_ebn0=未编码需求反解（本键
  uncoded 支路单源复用其 _invert_ber_db）；cdr_jitter_mask=SI 抖动
  mask 不同对象。chipless_rfid 汉明距离=标签识别码比对、time_gating/
  nf 变换 hamming=窗函数——与本族纠错码同名异义剔除。

数值锚（#118 独立来源；锚树 tests/unit/test_w1s2_link_fec.py）
--------------------------------------------------------
- Hamming(7,4)：2^4·(1+7)=128=2^7 完全码 bound 取等（精确整数）；
  m=2..7 全系 perfect；rate=k/n 恒等。
- RS(255,223)：d=33、t=16（NASA 标准码逐位）；Singleton slack=0；
  突发保证 (16−1)·8+1=121 bit；RS(255,240) 奇余量档 n−k=15→t=7/d=16。
- G 恒等：n=k、t=0 → G=0（<1e-9 dB，二项均值恒等式精确还原）；
- 独立实现互证：union bound 和式 vs scipy.stats.binom 生存/期望独立
  算术逐位（#118 同式双实现，非文献转引——G 的绝对量级属一阶口径
  估计，不做凭记忆文献锚，量级序由结构测试钉：Hamming(7,4)/BPSK/
  1e-5 点 G∈(0,6) dB 正增益带+RS(255,223) G>Hamming(7,4) G）；
- P_b 全 γ 扫描单调降（二分前提复核）；G 回灌 coded_ber_estimate
  闭环复现 target（同仓消费链装配钉）。

守卫：parity_bits_m 整数 [2,16]；n_sym/k_sym 整数 0<k<n≤2^m−1；block_n
整数 [2,1020]（上沿 1021–1024 收缩：union bound 求和 int→float 转换
必 OverflowError，W3-S1 审查 P2-1）、info_k 整数 [1,block_n]
（k=n=未编码退化档，t 恒 0）、
t_correct 整数 [0,⌊(n−k)/2⌋]
（超 (n−k)/2 必要条件显式拒绝——d_min≥2t+1 与 Singleton 上界联立）；
target_ber ∈ [1e-15, 0.5)；scheme 未知名显式拒绝；反解端点不可解显式
拒绝（同 required_ebn0 口径）。
"""

from __future__ import annotations

import math
from typing import Any

# BER 闭式/Q 函数单源复用（modulation_ber 全族唯一实现纪律，禁第二份
# erfc 形态）；_BER_FLOOR=双精度下限同口径透传
from .modulation_ber import _BER_FLOOR, _ber, _invert_ber_db, _normalize_scheme
from .registry import register_calculator

_SOURCES = {
    "hamming_code_design": (
        "Hamming BSTJ 1950; Lin & Costello Error Control Coding 2ed ch.3 "
        "(perfect-code Hamming bound)"),
    "reed_solomon_capacity": (
        "Reed & Solomon 1960; Singleton 1964 (MDS); NASA/CCSDS RS(255,223) "
        "standard; Lin & Costello 2ed"),
    "coded_ebn0_requirement": (
        "Lin & Costello 2ed / Clark & Cain 1981 (hard-decision union "
        "bound); BER closed form reused from modulation_ber (single source)"),
}

#: union bound 键块长上限（RS(255,*)/Hamming(127,*) 实用域内；二分
#: 200 轮 × O(n) 循环的耗时上限约束）。上沿收缩 1024→1020（aurora_g
#: W3-S1 审查 P2-1，W4-S1 修复）：求值序 ``i·C(n,i)`` 先于乘 p**i 完成
#: int→float 转换，n=1021 起中央项 C(n,n/2)·n/2 > DBL_MAX≈1.8e308 必
#: OverflowError（实测 n≤1020 正常：1020 档最大项 ≈1.4e308）——声明域
#: 内不可服务的守卫矛盾以域收缩消除，越界走 _as_int 显式"参数名+域"
#: 拒绝（防溢出重写求和会破坏既有"逐位"对拍钉，不采）。
_MAX_BLOCK_N = 1020

#: 反解域界（与 modulation_ber._invert_ber_db 同域，dB）
_BISECT_LO_DB = -20.0
_BISECT_HI_DB = 60.0


def _as_int(v: Any, name: str, lo: int, hi: int) -> int:
    """整数收敛：非整数值显式拒绝（bool 亦拒绝——bool 是 int 子类陷阱）。"""
    if isinstance(v, bool):
        raise ValueError(f"{name} 必须为整数，得到布尔值 {v!r}")
    try:
        f = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为整数，得到 {v!r}") from exc
    if not math.isfinite(f) or f != int(f):
        raise ValueError(f"{name} 必须为整数，得到 {v!r}")
    out = int(f)
    if out < lo or out > hi:
        raise ValueError(f"{name} 必须在 [{lo}, {hi}] 内，得到 {out}")
    return out


def _post_decode_ber_union(n: int, t: int, p: float) -> float:
    """硬判 union bound 译码后 BER：

    P_b = (1/n)·Σ_{i=t+1}^{n} i·C(n,i)·p^i·(1−p)^(n−i)

    t=0 时由二项均值恒等式精确还原 p（Σ i·C(n,i)p^i(1−p)^(n−i)=n·p）。
    正项和零相消，无病态数值；p^i 深尾下溢为 0 即该项可忽略，如实。
    """
    if p <= 0.0:
        return 0.0
    q = 1.0 - p
    total = 0.0
    for i in range(t + 1, n + 1):
        total += i * math.comb(n, i) * (p ** i) * (q ** (n - i))
    return total / n


def _block_error_union(n: int, t: int, p: float) -> float:
    """块错误率 union bound：P_B = Σ_{i=t+1}^{n} C(n,i)·p^i·(1−p)^(n−i)。"""
    if p <= 0.0:
        return 0.0
    q = 1.0 - p
    return sum(math.comb(n, i) * (p ** i) * (q ** (n - i))
               for i in range(t + 1, n + 1))


def _coded_face_ber(scheme: str, gamma_db: float, n: int, k: int,
                    t: int) -> float:
    """编码后 BER 面：码率扩张 → 信道 p → union bound 译码后 P_b。

    γ_b 为信息比特口径 Eb/N0（dB）；调制级（传输比特）口径
    γ_mod = γ_b + 10·lg(k/n)。P_b 对 γ_b 单调降（测试复核）。
    """
    rate = k / n
    p = _ber(scheme, 10.0 ** ((gamma_db + 10.0 * math.log10(rate)) / 10.0))
    return _post_decode_ber_union(n, t, p)


@register_calculator(
    "hamming_code_design",
    "Hamming码设计：(m 位校验 → n=2^m−1, k=n−m, d_min=3, t=1 纠 1 bit) "
    "参数面+编码率恒等式 k/n+Hamming bound（球填充界）2^k·(1+n)≤2^n "
    "精确整数判定——n=2^m−1 全系完全码（取等，perfect 逐位）。锚："
    "Hamming(7,4) 2^4·8=128=2^7 取等；m=2→(3,1) 重复码档。出处 Hamming "
    "BSTJ 1950/Lin & Costello 2ed ch.3；缩短/扩展 Hamming 不在本键",
    (("parity_bits_m", "int - 校验位数 m（[2,16]；n=2^m−1 由 m 唯一"
      "确定）"),),
    required=("parity_bits_m",),
)
def hamming_code_design(parity_bits_m: Any) -> dict[str, Any]:
    m = _as_int(parity_bits_m, "parity_bits_m", 2, 16)
    n = 2 ** m - 1
    k = n - m
    t = 1
    d_min = 2 * t + 1
    # Hamming bound（t=1 档）精确整数算术：2^k·(1+n) ≤ 2^n
    bound_left = (1 << k) * (1 + n)
    bound_right = 1 << n
    perfect = bool(bound_left == bound_right)
    return {
        "parity_bits_m": m,
        "block_length_n": n,
        "info_bits_k": k,
        "d_min": d_min,
        "t_correct": t,
        "code_rate": round(k / n, 12),
        "parity_matrix_shape": [m, n],
        "hamming_bound_left": bound_left,
        "hamming_bound_right": bound_right,
        "hamming_bound_satisfied": bool(bound_left <= bound_right),
        "perfect_code": perfect,
        "identity_k_eq_n_minus_m": bool(k == n - m),
        "note": (
            "n=2^m−1 原生 Hamming 码为完全码（Hamming bound 取等）——"
            "bound_left/bound_right 为精确整数字段（非浮点）；缩短/扩展"
            "变体不在本键面"),
        "source": _SOURCES["hamming_code_design"],
    }


@register_calculator(
    "reed_solomon_capacity",
    "RS码纠错能力：RS(n,k) over GF(2^m_sym) MDS 闭式——d_min=n−k+1"
    "（Singleton 恒等式 n−k≥d_min−1 取等，slack 字段逐位自检）、"
    "t=⌊(n−k)/2⌋ 符号纠错、擦除并行面 2e+f≤n−k、连续突发保证 "
    "b≤(t−1)·m_sym+1 bit（最坏对齐口径）。锚：RS(255,223)（GF(256)）"
    "NASA/CCSDS 标准码 d=33→t=16 逐位。出处 Reed&Solomon 1960/Singleton "
    "1964/Lin & Costello 2ed",
    (("n_sym", "int - 码长（符号，0<k<n≤2^m_sym−1）"),
     ("k_sym", "int - 信息符号数（>0）"),
     ("symbol_bits_m", "int - GF(2^m) 符号位宽（[3,16]，默认 8=GF(256)）")),
    required=("n_sym", "k_sym"),
)
def reed_solomon_capacity(n_sym: Any, k_sym: Any,
                          symbol_bits_m: Any = 8) -> dict[str, Any]:
    m_sym = _as_int(symbol_bits_m, "symbol_bits_m", 3, 16)
    n = _as_int(n_sym, "n_sym", 2, 2 ** m_sym - 1)
    k = _as_int(k_sym, "k_sym", 1, n - 1)
    d_min = n - k + 1
    t = (n - k) // 2
    max_erasures = n - k  # 2·0+f ≤ n−k（d_min−1）
    burst_bits = (t - 1) * m_sym + 1 if t >= 1 else 0
    return {
        "symbol_bits_m": m_sym,
        "gf_size": 2 ** m_sym,
        "block_length_n_sym": n,
        "info_symbols_k": k,
        "d_min": d_min,
        "t_correct_sym": t,
        "code_rate": round(k / n, 12),
        "singleton_slack": d_min - 1 - (n - k),
        "max_erasures_only": max_erasures,
        "errors_erasures_rule": "2*e + f <= n-k（e=符号错数, f=擦除数）",
        "burst_guarantee_bits": burst_bits,
        "note": (
            "RS 为 MDS：Singleton 恒等式取等（singleton_slack 恒 0）；"
            "t 以符号（GF(2^m_sym) 元素）计；burst_guarantee_bits=可保"
            "证纠正的连续突发 bit 上界（最坏符号对齐口径），t=0 档记 0 "
            "如实；错误+擦除并行纠正规则 2e+f≤n−k"),
        "source": _SOURCES["reed_solomon_capacity"],
    }


@register_calculator(
    "coded_ebn0_requirement",
    "编码Eb/N0需求（净编码增益G产生面）：给定调制制式与目标**编码后**"
    "BER，硬判 union bound 口径反解 ①未编码需求 γ_unc（单源复用 "
    "required_ebn0 闭式）②编码后需求 γ_coded（码率能量扩张 "
    "10lg(k/n)+t 纠错 union bound 剩余误码 P_b，dB 域二分）③净编码增益 "
    "双口径：net_coding_gain_db=γ_unc−γ_coded（教科书信息比特口径，保守"
    "下界估计）+coded_ber_estimate_gain_db（回灌面=净增益−10lg(R_c)，其 "
    "G 语义=码率扩张后信道增益，回灌闭环复现 target）。**诚实口径："
    "union bound 高估剩余误码 → G 为保守下界估计**；软判/交织/迭代瀑布"
    "区不在本面（实际增益高于本口径，方向恒成立）。锚：n=k,t=0 → G=0 "
    "恒等；量级序结构钉（锚树主判，不做凭记忆文献锚）",
    (("scheme", "str 'bpsk'/'qpsk'/'16qam'/'64qam'（大小写不敏感）"),
     ("target_ber", "float - 目标编码后 BER（[1e-15, 0.5)）"),
     ("block_n", "int - 码块长（bit，[2,1020]）"),
     ("info_k", "int - 信息位数（[1, block_n]；k=n=未编码退化档，此时 "
      "t 恒 0、G≡0）"),
     ("t_correct", "int - 可纠错位数（[0, ⌊(n−k)/2⌋]；超界显式拒绝）")),
    required=("scheme", "target_ber", "block_n", "info_k", "t_correct"),
)
def coded_ebn0_requirement(scheme: str, target_ber: float, block_n: Any,
                           info_k: Any, t_correct: Any) -> dict[str, Any]:
    s = _normalize_scheme(scheme)
    tgt = float(target_ber)
    if not math.isfinite(tgt) or tgt < _BER_FLOOR or tgt >= 0.5:
        raise ValueError(
            f"coded_ebn0_requirement: target_ber 必须在 [{_BER_FLOOR:g}, "
            f"0.5) 内，得到 {target_ber!r}")
    n = _as_int(block_n, "block_n", 2, _MAX_BLOCK_N)
    k = _as_int(info_k, "info_k", 1, n)  # k=n=未编码退化档（t 恒 0，G=0 锚）
    # 必要条件：d_min ≥ 2t+1 且 d_min ≤ n−k+1（Singleton 上界）⇒ t ≤ (n−k)/2
    t = _as_int(t_correct, "t_correct", 0, (n - k) // 2)

    rate = k / n
    rate_expansion_db = 10.0 * math.log10(rate)

    # ① 未编码需求（单源复用 required_ebn0 的闭式反解；前缀换成本键）
    try:
        gamma_unc = _invert_ber_db(s, tgt)
    except ValueError as exc:
        raise ValueError(f"coded_ebn0_requirement: {exc}") from exc

    # ② 编码后需求（P_b 对 γ 单调降，dB 域二分；端点不可解显式拒绝）
    def pb(gamma_db: float) -> float:
        return _coded_face_ber(s, gamma_db, n, k, t)

    pb_lo = pb(_BISECT_LO_DB)
    if tgt >= pb_lo:
        raise ValueError(
            f"coded_ebn0_requirement: target_ber={tgt:g} 不低于闭式可反解"
            f"上界（γb={_BISECT_LO_DB:g} dB 处编码后 P_b={pb_lo:.4g}）——"
            "目标 BER 过大")
    pb_hi = pb(_BISECT_HI_DB)
    if tgt <= pb_hi:
        raise ValueError(
            f"coded_ebn0_requirement: target_ber={tgt:g} 低于双精度闭式"
            f"下限 {_BER_FLOOR:g}（γb={_BISECT_HI_DB:g} dB 处已下溢）——"
            "目标 BER 过小")
    lo, hi = _BISECT_LO_DB, _BISECT_HI_DB
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if pb(mid) > tgt:
            lo = mid
        else:
            hi = mid
    gamma_coded = 0.5 * (lo + hi)

    # 回代自检（required_ebn0 同款口径；解在域内 ⇒ P_b>0 必然）
    achieved = pb(gamma_coded)
    if achieved <= 0.0 or abs(math.log10(achieved)
                              - math.log10(tgt)) > 1e-6:
        raise ValueError(
            f"coded_ebn0_requirement: 反解回代自检失败（target={tgt:g}, "
            f"achieved={achieved:g}）——内部错误，显式拒绝而非外推")

    p_channel = _ber(s, 10.0 ** ((gamma_coded + rate_expansion_db) / 10.0))
    gain = gamma_unc - gamma_coded
    # coded_ber_estimate 回灌面：其 G 语义=码率扩张**后**信道上的增益
    # （γ_eff=γ+10lg(R_c)+G → 理论 BER），与本键教科书净增益（信息比特
    # 口径 γ_unc−γ_coded）差一个 10lg(R_c) 记账项——回灌必须用本字段，
    # 两口径显式分列（#122 如实，防双计码率扩张）
    gain_loopback = gamma_unc - gamma_coded - rate_expansion_db
    return {
        "scheme": s,
        "target_ber": tgt,
        "block_n": n,
        "info_k": k,
        "t_correct": t,
        "code_rate": round(rate, 12),
        "rate_expansion_db": round(rate_expansion_db, 9),
        "uncoded_required_ebn0_db": round(gamma_unc, 6),
        "coded_required_ebn0_db": round(gamma_coded, 6),
        "net_coding_gain_db": round(gain, 6),
        "coded_ber_estimate_gain_db": round(gain_loopback, 6),
        "channel_ber_at_coded_req": p_channel,
        "channel_ber_log10": (None if p_channel <= 0.0
                              else round(math.log10(p_channel), 12)),
        "block_error_rate_union": _block_error_union(n, t, p_channel),
        "achieved_post_ber": achieved,
        "note": (
            "硬判译码 union bound 一阶口径：net_coding_gain_db=γ_unc−"
            "γ_coded（教科书净增益，信息比特口径）为真增益的保守下界估计"
            "（bound 高估剩余误码）；不含软判/打孔/交织/迭代译码瀑布区"
            "（实际增益高于本口径，方向恒成立）。回灌 coded_ber_estimate "
            "用 coded_ber_estimate_gain_db（其 G 语义=码率扩张后信道增益，"
            "=净增益−10lg(R_c)，两口径差=码率扩张记账项）；闭环恒等是"
            "接线钉（同源 _ber），物理量级由结构测试另钉"),
        "source": _SOURCES["coded_ebn0_requirement"],
    }
