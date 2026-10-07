"""MT-4 接收机损伤三件套（round17 规格，频域纯闭式；相噪积分消费 clock_noise）。

规格：研究扩充 round17 §二 MT-4（P1/S-M）。
三件（以规格为准）：

1. **IQ 失衡 IRR**：增益/相位失衡 → 镜像抑制比 + EVM 贡献（3GPP 口径）。
2. **相噪 → 积分 EVM**：L(f) 积分 → σ_φ → EVM（积分复用
   core/clock_noise.phase_jitter_from_l——同一 2∫L df 公式**不重复实现**，
   防双实现分叉，clock_noise 模块头同源纪律）。
3. **blocking/信道选择性预算**：阻塞信号 → 倒易混频噪声 + 灵敏度恶化
   （desense）+ 前端 P1dB 裕量 + 杂散落带检查（spur_search 复用
   core/cascade.py，既有语义零改动、只读消费）。

公式口径（铁律 5：来源写 docstring；裁判=独立来源，不自证，#118）：

- IRR（镜像抑制比=信号功率/镜像功率）::

      IRR = (1+ε²+2ε·cosφ) / (1+ε²−2ε·cosφ)

  ε=Q/I 增益比（线性）、φ=正交相位误差。ε=1 退化 IRR=cot²(φ/2)。
  出处：B. Razavi, *RF Microelectronics*, 2nd ed., ch.4（IQ mismatch
  镜像抑制式）。3GPP 消费口径：TS 38.141-1（BS 一致性）以 EVM 裁决接收
  损伤——镜像泄漏折算 EVM_rms² = P_image/P_signal = 1/IRR（rms 误差
  矢量/基准信号，与 3GPP EVM 定义同构），本模块按此折算输出 evm_rms/
  evm_db；IRR 本身不设 3GPP 限值门（限值面 out-of-scope，如实注明）。
- 相噪 → EVM：σ_φ² = 2∫[f1,f2] L(f) df（rad²，ADI MT-008 口径，
  clock_noise 已钉）；小角度平稳高斯下 rms 相位误差即 rms EVM 幅度
  （EVM_rms ≈ σ_φ，σ_φ≪1 rad；>0.5 rad 显式打 small_angle_ok=False
  不静默）。EVM dB = 20·log10(σ_φ)。
- 倒易混频（reciprocal mixing）：阻塞信号经前端选择性衰减后打在混频器
  上，LO 裙边把阻塞功率搬进信道::

      N_rm [dBm] = P_blk@mixer + L(f_offset) + 10·log10(B)

  灵敏度恶化（desense，等效 NF 抬升）::

      ΔNF = 10·log10(1 + 10^((N_rm − N_floor)/10))

  N_floor 来自 core/cascade.cascade_budget（Friis NF + kTB，只读消费）。
  前端线性度面：P1dB 裕量 = 链路输入 P1dB − 阻塞电平（cascade_budget
  的 p1db 口径：p1db_dbm=该级输出 1dB 压缩点）。杂散面：阻塞与本振的
  |m·f_blk ± n·f_LO| 产物落带检查复用 cascade.spur_search。

诚实边界（预声明）：
1. IRR 是静态失衡闭式——不含 AM/PM 转换、二阶失真与 DDS/ADC 支路损伤；
2. 相噪 EVM 假设平稳高斯小角度（大角度/周期调制不适用，clock_noise 同
   边界）；积分区间由调用方给定（不外推）；
3. blocking 预算的倒易混频用**阻塞偏移处的标量 L(f)**——LO 裙边斜率
   分段积分不在此层（调用方按偏移取值或走 clock_noise 幂律谱合成）；
   前端选择性用**单一聚总抑制参数**（不逐级频变）；AGC/压缩行为只做
   P1dB 裕量检查（不迭代压缩后 NF）。

单位口径：dB/dBm/Hz/K/rad/deg 显式钉在参数名。数值 0.0 合法（判缺失
一律 is not None，#364④）；bool 显式拒收（df7+⑯）。纯函数零 IO（相噪
积分与杂散搜索的既有内核同为纯函数）。LLM 不参与任何数值（铁律 7）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.cascade import (
    DEFAULT_MAX_ORDER,
    DEFAULT_T_KELVIN,
    cascade_budget,
    spur_search,
)
from rfauto.core.clock_noise import INTERP_DB_LINEAR, phase_jitter_from_l

#: 小角度判据阈值：σ_φ 超过此值（rad rms）时 EVM≈σ_φ 线性化不可靠
SMALL_ANGLE_LIMIT_RAD = 0.5

__all__ = [
    "DEFAULT_MAX_ORDER",
    "SMALL_ANGLE_LIMIT_RAD",
    "blocking_budget",
    "iq_imbalance_irr",
    "phase_noise_evm",
]


# ─── 入参守卫（#140：注解不等于调用方真的传了）───────────────────────────────

def _finite(value: Any, name: str) -> float:
    """收敛入参为有限 float；bool 显式拒收（df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    if not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限实数，收到 {value!r}")
    return out


# ─── 件 1：IQ 失衡 IRR ───────────────────────────────────────────────────────

def iq_imbalance_irr(amp_imbalance_db: float,
                     phase_imbalance_deg: float) -> dict[str, Any]:
    """IQ 增益/相位失衡 → 镜像抑制比 IRR + EVM 贡献（Razavi 式 + 3GPP EVM 折算）。

    amp_imbalance_db: I/Q 增益失衡 [dB]（ε=10^(a/20)，Q 对 I；符号即
    方向，同值异号 IRR 相同）；phase_imbalance_deg: 正交相位误差 [deg]
    （|φ| ≤ 180 越界显式拒绝；符号=旋转方向，IRR 同值）。

    Returns（全 JSON 可序列化；无穷/零值走 None+标志位，不产 NaN/Inf）：

    - irr_linear / irr_db：信号/镜像功率比（完全平衡 → None+balanced；
      完全反相 ε=1,φ=±180° → IRR=0 dB 仍可列，evm 无界走 None）；
    - evm_rms / evm_db / evm_percent：镜像泄漏折算 EVM（√(1/IRR)）；
    - balanced / full_image 标志位（口径见模块 docstring）。
    """
    a = _finite(amp_imbalance_db, "amp_imbalance_db")
    d = _finite(phase_imbalance_deg, "phase_imbalance_deg")
    if abs(d) > 180.0:
        raise ValueError(
            f"phase_imbalance_deg 必须 |φ| ≤ 180（正交误差口径，越界请先"
            f"折叠），收到 {d!r}")
    eps = 10.0 ** (a / 20.0)
    phi = math.radians(d)
    numer = 1.0 + eps * eps + 2.0 * eps * math.cos(phi)
    denom = 1.0 + eps * eps - 2.0 * eps * math.cos(phi)
    balanced = (a == 0.0 and d == 0.0)
    full_image = (numer <= 0.0)
    irr_linear: float | None
    irr_db: float | None
    evm_rms: float | None
    evm_db: float | None
    if balanced:
        # 理想平衡：IRR→∞、EVM→0（dB 域无定义走 None，JSON 契约禁 Inf）
        irr_linear = None
        irr_db = None
        evm_rms = 0.0
        evm_db = None
    elif full_image:
        # ε=1 且 φ=±180°：信号支路完全抵消、全部功率落镜像——EVM 无界
        irr_linear = 0.0
        irr_db = None
        evm_rms = None
        evm_db = None
    else:
        irr_linear = numer / denom
        irr_db = 10.0 * math.log10(irr_linear)
        evm_rms = math.sqrt(denom / numer)
        evm_db = -irr_db
    return {
        "amp_imbalance_db": a,
        "phase_imbalance_deg": d,
        "gain_ratio_linear": eps,
        "irr_linear": irr_linear,
        "irr_db": irr_db,
        "evm_rms": evm_rms,
        "evm_db": evm_db,
        "evm_percent": None if evm_rms is None else 100.0 * evm_rms,
        "balanced": balanced,
        "full_image": full_image,
    }


# ─── 件 2：相噪 → 积分 EVM ───────────────────────────────────────────────────

def phase_noise_evm(
    f_edges: Any,
    l_dbc: Any,
    *,
    interp: str = INTERP_DB_LINEAR,
    f_carrier_hz: float | None = None,
) -> dict[str, Any]:
    """单边带相噪 L(f) → 积分相位误差 σ_φ → EVM（小角度口径）。

    积分本体（σ_φ² = 2∫10^(L/10)df，ADI MT-008）**复用
    clock_noise.phase_jitter_from_l**（不重复实现——同式双实现分叉禁令，
    clock_noise 模块头纪律）；本函数只做 σ_φ→EVM 的口径转换与小角度
    有效性旗标。参数语义（f_edges/l_dbc/interp/f_carrier_hz）逐字透传
    clock_noise（dB 域线性插值=边界值、const=段值；严格递增偏移频率）。

    Returns：sigma_phi_rad/deg、sigma_phi2_rad2、evm_rms（=σ_φ）、
    evm_db（σ_φ=0 时 None——dB 域无定义，JSON 契约禁 −Inf）、
    evm_percent、small_angle_ok（σ_φ ≤ 0.5 rad）、jitter_s（给了载波
    才有，否则 None）。
    """
    fc = None if f_carrier_hz is None else _finite(f_carrier_hz, "f_carrier_hz")
    if interp not in (INTERP_DB_LINEAR, "const"):
        raise ValueError(f"interp 必须是 'db_linear'|'const'，收到 {interp!r}")
    r = phase_jitter_from_l(f_edges, l_dbc, interp=interp, f_carrier=fc)
    sigma = r.sigma_phi_rad
    evm_db = 20.0 * math.log10(sigma) if sigma > 0.0 else None
    return {
        "sigma_phi_rad": sigma,
        "sigma_phi_deg": r.sigma_phi_deg,
        "sigma_phi2_rad2": r.sigma_phi2_rad2,
        "evm_rms": sigma,
        "evm_db": evm_db,
        "evm_percent": 100.0 * sigma,
        "small_angle_ok": sigma <= SMALL_ANGLE_LIMIT_RAD,
        "small_angle_limit_rad": SMALL_ANGLE_LIMIT_RAD,
        "f1_hz": r.f1_hz,
        "f2_hz": r.f2_hz,
        "n_segments": r.n_segments,
        "jitter_s": r.jitter_s,
        "f_carrier_hz": r.f_carrier_hz,
    }


# ─── 件 3：blocking / 信道选择性预算 ─────────────────────────────────────────

def blocking_budget(
    stages: list,
    bw_hz: float,
    blocker_dbm: float,
    f_blocker_hz: float,
    f_lo_hz: float,
    lo_phase_noise_dbc_hz: float,
    *,
    f_rx_hz: float | None = None,
    if_center_hz: float | None = None,
    filter_rejection_db: float = 0.0,
    desense_limit_db: float = 3.0,
    max_order: int = DEFAULT_MAX_ORDER,
    t_kelvin: float = DEFAULT_T_KELVIN,
) -> dict[str, Any]:
    """阻塞/信道选择性预算：倒易混频 desense + P1dB 裕量 + 杂散落带三面。

    stages: 接收链级表（schema 与 core/cascade.cascade_budget 完全一致，
    只读消费其 NF/P1dB/噪声底）；bw_hz: 信道（ wanted）噪声带宽 [Hz]；
    blocker_dbm: 链路输入处阻塞电平 [dBm]；f_blocker_hz/f_lo_hz: 阻塞/
    本振频率 [Hz]；lo_phase_noise_dbc_hz: 阻塞偏移处的 LO 单边带相噪
    L(f) [dBc/Hz]（标量，调用方按偏移取值——裙边分段积分不在此层）；
    f_rx_hz: 期望信道频率（if_center_hz 缺省时信道 IF=|f_rx−f_lo|，两者
    必须给其一）；filter_rejection_db: 阻塞偏移处前端聚总选择性 [dB]
    （≥0；作用于阻塞到混频器之前）；desense_limit_db: 判过限值（≥0）；
    max_order/t_kelvin: 透传 spur_search/cascade_budget。

    三面预算（公式口径见模块 docstring）：

    1. 倒易混频：N_rm = blocker−rejection+L+10log10(B)；desense =
       10log10(1+10^((N_rm−N_floor)/10))（等效 NF 抬升=灵敏度恶化）；
    2. 线性度：p1db_margin = 链路输入 P1dB − 阻塞电平（无 p1db 级时
       None，不参与判过）；
    3. 杂散：spur_search(f_blocker, f_lo) 落带产物（fundamental 不计），
       高危（hazard="high"）落带即判负。

    pass = desense_ok ∧ p1db_ok ∧ spur_ok（三面合取；各面独立出旗标）。
    """
    bw = _finite(bw_hz, "bw_hz")
    if bw <= 0.0:
        raise ValueError(f"bw_hz 必须 >0（信道带宽口径），收到 {bw!r}")
    blk = _finite(blocker_dbm, "blocker_dbm")
    f_blk = _finite(f_blocker_hz, "f_blocker_hz")
    if f_blk <= 0.0:
        raise ValueError(f"f_blocker_hz 必须 >0，收到 {f_blk!r}")
    f_lo = _finite(f_lo_hz, "f_lo_hz")
    if f_lo <= 0.0:
        raise ValueError(f"f_lo_hz 必须 >0，收到 {f_lo!r}")
    l_off = _finite(lo_phase_noise_dbc_hz, "lo_phase_noise_dbc_hz")
    rej = _finite(filter_rejection_db, "filter_rejection_db")
    if rej < 0.0:
        raise ValueError(
            f"filter_rejection_db 必须 >=0（选择性是衰减量），收到 {rej!r}")
    lim = _finite(desense_limit_db, "desense_limit_db")
    if lim < 0.0:
        raise ValueError(f"desense_limit_db 必须 >=0，收到 {lim!r}")
    if isinstance(max_order, bool) or not isinstance(max_order, int):
        raise ValueError(f"max_order 必须是整数，收到 {max_order!r}")
    if max_order < 1:
        raise ValueError(f"max_order 必须 >=1，收到 {max_order!r}")
    if if_center_hz is None:
        if f_rx_hz is None:
            raise ValueError(
                "if_center_hz 与 f_rx_hz 必须给其一（信道 IF 无法解析）")
        f_rx = _finite(f_rx_hz, "f_rx_hz")
        if f_rx <= 0.0:
            raise ValueError(f"f_rx_hz 必须 >0，收到 {f_rx!r}")
        if_center = abs(f_rx - f_lo)
    else:
        if_center = _finite(if_center_hz, "if_center_hz")
        if if_center < 0.0:
            raise ValueError(
                f"if_center_hz 必须 >=0，收到 {if_center!r}")

    # 面 0：链路基线（Friis NF/噪声底/P1dB——core/cascade 只读消费）
    budget = cascade_budget(list(stages), bw_hz=bw, t_kelvin=t_kelvin)
    n_floor = float(budget["noise_floor_dbm"])

    # 面 1：倒易混频 → desense
    p_blk_mixer = blk - rej
    n_rm = p_blk_mixer + l_off + 10.0 * math.log10(bw)
    desense_db = 10.0 * math.log10(1.0 + 10.0 ** ((n_rm - n_floor) / 10.0))
    eff_floor = n_floor + desense_db

    # 面 2：前端线性度裕量
    p1db_in = budget["p1db_in_dbm"]
    p1db_margin_db = None if p1db_in is None else float(p1db_in) - blk

    # 面 3：阻塞×本振杂散落带（复用 cascade.spur_search，fundamental 不计）
    spurs = spur_search(
        f_blk, f_lo, if_center_hz=if_center, if_bw_hz=bw, max_order=max_order)
    in_band = [s for s in spurs
               if s["in_band"] and s["role"] == "spur"]

    desense_ok = desense_db <= lim
    p1db_ok = p1db_margin_db is None or p1db_margin_db > 0.0
    spur_ok = all(s["hazard"] != "high" for s in in_band)
    return {
        "n_floor_dbm": n_floor,
        "nf_total_db": float(budget["nf_total_db"]),
        "gain_total_db": float(budget["gain_total_db"]),
        "blocker_at_mixer_dbm": p_blk_mixer,
        "lo_phase_noise_dbc_hz": l_off,
        "filter_rejection_db": rej,
        "n_recip_mix_dbm": n_rm,
        "desense_db": desense_db,
        "effective_floor_dbm": eff_floor,
        "desense_ok": desense_ok,
        "desense_limit_db": lim,
        "p1db_margin_db": p1db_margin_db,
        "p1db_ok": p1db_ok,
        "n_in_band_spurs": len(in_band),
        "in_band_spurs": in_band,
        "spur_ok": spur_ok,
        "if_center_hz": float(if_center),
        "bw_hz": bw,
        "pass": bool(desense_ok and p1db_ok and spur_ok),
    }
