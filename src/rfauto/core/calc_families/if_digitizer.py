"""IF 数字化欠采样规划族（aurora_g W2-S2 席域 C4，R2_core_tier4 §③ Top6
设计案）。

出处（原文定理逐式转写，详见下节物理口径）：
- bandpass_sampling_plan：带通采样定理可行 fs 区间（Vaughan-Scott-White
  1991, IEEE Trans. SP 39(9) 带通采样不等式）。
- alias_fold_check：折叠恒等式 f'=|f−round(f/fs)·fs|（采样混叠第一性
  恒等式）+孔径抖动 SNR 消费口径（adc_budget 同族）。

两键：bandpass_sampling_plan（带通采样 Nyquist 区规划：f_c/BW → 可行 fs
区间表+区号+最小采样率）/ alias_fold_check（候选 fs 混叠折叠核验：折叠
恒等式+防混叠保护带三态判定+孔径抖动 SNR 消费面）。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``nyquist.?zone|bandpass.?sampl|欠采样`` 命中全部为已知误中（vibration_srs
Duhamel 网格/test_emc_service 波形折信封/test_metasurface_lut 最短角差/
test_phase_center 阵列欠采样拒绝/test_vibration_srs 误差预算注记）——
**带通采样/Nyquist 区规划键面零**（R2 §② 方向 3 判据原文复跑同判）。
邻域 docstring 边界实测：adc_budget.py=噪声合成面（孔径抖动/量化/kTC
RSS+ENOB，无采样率/折叠区规划输出）、budget.py if_plan_sweep=混频杂散
落带面（无采样规划输出）——两邻 docstring 边界内空白成立，本族=测量
接收机 IF 链的数字化半边。

物理口径（docstring 写死，#1c/#300 出处纪律；#118 锚树见
tests/unit/test_w2s2_core_tier4.py）
--------------------------------------------------------
带通信号 [f_L, f_H]（f_L=f_c−BW/2、f_H=f_c+BW/2）以 fs 欠采样不混叠的
可行区间（Vaughan-Scott-White 1991，IEEE Trans. SP 39(9) 带通采样定理）：

  对整数区号 m = 1..M，M = ⌊f_H/BW⌋：

      m = 1      ：fs ≥ 2·f_H                      （基带退化档）
      m ≥ 2      ：2·f_H/m ≤ fs ≤ 2·f_L/(m−1)

  区间非空 ⇔ m ≤ f_H/BW（与 M 上界自洽；m=M 档两端相等=零保护带理论点）。
  最小可行采样率 = 2·f_H/M（最高区号档）。

折叠恒等式（alias fold，逐频严格成立）：

  f' ≡ |f − round(f/fs)·fs| ∈ [0, fs/2]

混叠不发生 ⇔ [f_L, f_H] 不跨越任何 k·fs/2 边界。三态判定（如实三分，
#122 不凑绿）：

  alias_free_strict ：带严格落在单一 Nyquist 区内（保护带 >0 两端）
  boundary_touching ：带缘恰落 k·fs/2（零保护带理论点，fs 微扰即混叠，
                      如实标注不判绿）
  alias_overlap     ：跨边界（真实混叠，拒绝）

孔径抖动 SNR 直接消费 adc_budget.snr_jitter_db 同式（MT-007 口径
−20lg(2π·f_in·σ_j)；f_in 取模拟输入最高频率 f_H——欠采样 ADC 的 dv/dt
由模拟频率决定，非折叠后 IF）。导入复用零公式复制（单源消费），锚树
另做独立算术对拍（同仓双源+#118）。

边界防撞（#222）
--------------------------------------------------------
- adc_budget=ADC 噪声合成面（孔径抖动/量化/kTC+ENOB）——本族=采样规划
  面，抖动 SNR 经导入消费衔接（规划键出 f_H，噪声键给 SNR）；
- budget.if_plan_sweep=混频器杂散乘积域落带面（f_RF/f_LO 杂散窗）——
  本族=采样/折叠区规划，两邻上下游不并入；
- cispr_detector=EMC 检波器算法、cdr_jitter_mask=SI 抖动掩模——检波与
  抖动语义不并入；
- 时域波形/滤波器设计（抗混叠滤波器阶数/过渡带）不在口径——本族只做
  采样规划（R2 §③ C4 边界原文）。

数值锚（#118 独立来源；锚树 tests/unit/test_w2s2_core_tier4.py）
--------------------------------------------------------
- fc=70MHz/BW=20MHz → M=4 区：m=1 档 fs≥160MHz 无上界；m=3 档
  [53.333, 60]MHz；m=4 档退化点 40MHz（零保护带）；
- fs=54MHz（m=3 档内点）→ 原带居第 3 Nyquist 区（54–81MHz），折叠像
  [6,26]MHz 全落首 Nyquist 区（0–27MHz），保护带 6/1MHz（独立算术复算）；
- fs=40MHz（m=M 边界点）→ f_L 缘恰触 3·fs/2=60MHz、f_H 缘恰触 4·fs/2=
  80MHz → boundary_touching 如实；
- fs=50MHz（不可行）→ f_H=80MHz mod 50=30MHz 跨 fs/2=25MHz 边界折回
  20MHz → alias_overlap；
- 折叠恒等式对任意 (f, fs) 独立复算逐位；抖动 SNR 与 adc_budget 同值。

守卫：f_center_hz>BW/2（f_L>0）、bw_hz>0、fs_hz>0、sigma_jitter_s≥0；
bool 入参显式拒收（_finite_nb，fec_codes._as_int 同族先例）。

接口：纯函数零 IO；math 为主；全部返回 JSON 可序列化结构（浮点/字符串/
bool/None；数值 0.0 合法，判缺失一律 is not None，禁 ``or 缺省``，
#364④）。无 ``__all__``（公开 API 快照口径，waveguide_iris 先例）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

#: 边界触碰判定容差（相对 fs 的相对量；浮点 k·fs/2 恰等是测度零点，
#: 容差内按触碰三态如实标注而非硬判混叠）
_TOUCH_RTOL = 1.0e-12


def _finite_nb(value: Any, name: str) -> float:
    """有限数收敛（bool 显式拒收版，全模块键面入参走此）——
    ``float(True)=1.0`` 静默污染面（W3-S1 审查 P3-2：原声明"自然拒收"
    失实），对齐 fec_codes._as_int 显式 bool 拒绝先例（df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染）")
    return _finite(value, name)


def _fold_hz(f_hz: float, fs_hz: float) -> float:
    """折叠恒等式单源：f' = |f − round(f/fs)·fs| ∈ [0, fs/2]。"""
    return abs(f_hz - round(f_hz / fs_hz) * fs_hz)


def _band_status(fl_hz: float, fh_hz: float, fs_hz: float
                 ) -> tuple[str, float, float, int]:
    """带 [fl,fh] 对 fs 的混叠三态判定。

    判据（带不跨 k·fs/2 边界）：a=2fl/fs、b=2fh/fs，取候选区间
    [n0, n0+1]（n0=⌊a⌋）——b ≤ n0+1 即带不越过该区间上边界（下边界由
    n0 ≤ a 构造成立）；b 恰等 n0+1 或 a 恰等 n0 为边界触碰（零保护带）。

    返回 (status, guard_low_hz, guard_high_hz, nyquist_zone)：
    - guard_low/high = 折叠带像到 0 与 fs/2 的两端距离（带在单区内时；
      跨边界时取 0 并标 overlap）；
    - nyquist_zone = 原带所处 Nyquist 区号（1 起，=n0+1；折叠像恒落
      首 Nyquist 区 [0, fs/2]，由折叠恒等式构造）。
    """
    a = 2.0 * fl_hz / fs_hz
    b = 2.0 * fh_hz / fs_hz
    n0 = math.floor(a)
    tol = _TOUCH_RTOL * max(1.0, b)
    lo_on = abs(a - n0) <= tol
    hi_on = abs(b - (n0 + 1)) <= tol
    if b <= n0 + 1.0 - tol:
        if lo_on:
            return ("boundary_touching", 0.0, 0.0, n0 + 1)
        f_lo_img = _fold_hz(fl_hz, fs_hz)
        f_hi_img = _fold_hz(fh_hz, fs_hz)
        return ("alias_free_strict", min(f_lo_img, f_hi_img),
                fs_hz / 2.0 - max(f_lo_img, f_hi_img), n0 + 1)
    if hi_on:
        # 上缘恰触 (n0+1)·fs/2：零保护带理论点（fs 微扰即混叠，如实标注）
        return ("boundary_touching", 0.0, 0.0, n0 + 1)
    return ("alias_overlap", 0.0, 0.0, 0)


@register_calculator(
    "bandpass_sampling_plan",
    "带通采样 Nyquist 区规划：f_c/BW → 可行 fs 区间表（VSW 1991 不等式，"
    "区号 m=1..⌊f_H/BW⌋，m=1 基带退化档 fs≥2f_H 无上界、m≥2 档 "
    "2f_H/m ≤ fs ≤ 2f_L/(m−1)）+每档几何中心 fs_rec 及其折叠带/两端保护"
    "带+最小可行采样率 2f_H/M；alias_fold_check=单点 fs 核验面",
    (("f_center_hz", "float Hz 通带中心频率（>bw_hz/2 使 f_L>0）"),
     ("bw_hz", "float Hz 通带带宽（>0）")),
    required=("f_center_hz", "bw_hz"),
)
def bandpass_sampling_plan(f_center_hz: float,
                           bw_hz: float) -> dict[str, Any]:
    tag = "bandpass_sampling_plan"
    fc = _finite_nb(f_center_hz, f"{tag}.f_center_hz")
    bw = _finite_nb(bw_hz, f"{tag}.bw_hz")
    if bw <= 0.0:
        raise ValueError(f"{tag}: bw_hz 必须 >0，得到 {bw_hz!r}")
    if fc <= bw / 2.0:
        raise ValueError(
            f"{tag}: f_center_hz={f_center_hz!r} 必须 >bw_hz/2={bw / 2!r}"
            "（通带下缘 f_L=f_c−bw/2 必须 >0，负频率非物理）")
    fl = fc - bw / 2.0
    fh = fc + bw / 2.0
    m_max = math.floor(fh / bw)
    intervals: list[dict[str, Any]] = []
    for m in range(1, m_max + 1):
        fs_lo = 2.0 * fh / m
        fs_hi: float | None = (2.0 * fl / (m - 1)) if m >= 2 else None
        # 推荐点=区间几何中心（相对保护带均衡的标准取法）；m=1 无上界档
        # 取最小值 2 倍（确定性规则，不引入外部启发常数）
        fs_rec = math.sqrt(fs_lo * fs_hi) if fs_hi is not None else 2.0 * fs_lo
        status, g_lo, g_hi, zone = _band_status(fl, fh, fs_rec)
        intervals.append({
            "zone_m": m,
            "fs_min_hz": round(fs_lo, 9),
            "fs_max_hz": (round(fs_hi, 9) if fs_hi is not None else None),
            "fs_recommended_hz": round(fs_rec, 9),
            "folded_low_hz": round(_fold_hz(fl, fs_rec), 9),
            "folded_center_hz": round(_fold_hz(fc, fs_rec), 9),
            "folded_high_hz": round(_fold_hz(fh, fs_rec), 9),
            "nyquist_zone": zone,
            "alias_status": status,
            "guard_low_hz": round(g_lo, 9),
            "guard_high_hz": round(g_hi, 9),
        })
    return {
        "f_center_hz": round(fc, 9),
        "bw_hz": round(bw, 9),
        "f_low_hz": round(fl, 9),
        "f_high_hz": round(fh, 9),
        "m_max": m_max,
        "min_feasible_fs_hz": round(2.0 * fh / m_max, 9),
        "intervals": intervals,
        "note": (
            "VSW 带通采样定理可行区间表：m=1 基带退化档（fs≥2f_H 无上"
            "界）；m≥2 欠采样档；m=m_max 档两端相等=零保护带理论点（"
            "boundary_touching 如实，工程取内点留保护带）；fs_recommended"
            "=区间几何中心（相对保护带均衡），m=1 档取 2×最小值；折叠带/"
            "保护带按折叠恒等式逐档实算（不是解析近似）"),
        "source": (
            "Vaughan, Scott, White, \"The theory of bandpass sampling\", "
            "IEEE Trans. Signal Processing 39(9), 1991（带通采样定理）；"
            "折叠恒等式第一性"),
    }


@register_calculator(
    "alias_fold_check",
    "候选采样率混叠折叠核验：带 [f_c±BW/2] 对 fs 的折叠恒等式 "
    "f'≡|f−round(f/fs)·fs| 逐缘折叠+混叠三态判定（alias_free_strict/"
    "boundary_touching/alias_overlap 如实三分）+两端保护带+Nyquist 区号"
    "+VSW 区号回查；sigma_jitter_s 给出时经 adc_budget.snr_jitter_db 同式"
    "消费孔径抖动 SNR（f_in 取模拟最高频率 f_H——欠采样 dv/dt 由模拟频率"
    "决定，MT-007 口径）",
    (("f_center_hz", "float Hz 通带中心频率（>bw_hz/2）"),
     ("bw_hz", "float Hz 通带带宽（>0）"),
     ("fs_hz", "float Hz 候选采样率（>0）"),
     ("sigma_jitter_s", "float s ADC 孔径抖动 RMS（≥0，可选——给出时输出"
      "抖动 SNR 消费面）")),
    required=("f_center_hz", "bw_hz", "fs_hz"),
)
def alias_fold_check(f_center_hz: float, bw_hz: float, fs_hz: float,
                     sigma_jitter_s: float | None = None
                     ) -> dict[str, Any]:
    tag = "alias_fold_check"
    fc = _finite_nb(f_center_hz, f"{tag}.f_center_hz")
    bw = _finite_nb(bw_hz, f"{tag}.bw_hz")
    fs = _finite_nb(fs_hz, f"{tag}.fs_hz")
    if bw <= 0.0:
        raise ValueError(f"{tag}: bw_hz 必须 >0，得到 {bw_hz!r}")
    if fc <= bw / 2.0:
        raise ValueError(
            f"{tag}: f_center_hz={f_center_hz!r} 必须 >bw_hz/2={bw / 2!r}"
            "（通带下缘 f_L 必须 >0）")
    if fs <= 0.0:
        raise ValueError(f"{tag}: fs_hz 必须 >0，得到 {fs_hz!r}")
    fl = fc - bw / 2.0
    fh = fc + bw / 2.0
    status, g_lo, g_hi, zone = _band_status(fl, fh, fs)

    # VSW 区号回查：fs 落在哪一档可行区间（m 满足 2f_H/m ≤ fs ≤ 2f_L/(m−1)）
    m_max = math.floor(fh / bw)
    vsw_zone_m: int | None = None
    for m in range(1, m_max + 1):
        lo = 2.0 * fh / m
        hi = (2.0 * fl / (m - 1)) if m >= 2 else math.inf
        if lo <= fs <= hi:
            vsw_zone_m = m
            break

    out: dict[str, Any] = {
        "f_center_hz": round(fc, 9),
        "bw_hz": round(bw, 9),
        "f_low_hz": round(fl, 9),
        "f_high_hz": round(fh, 9),
        "fs_hz": round(fs, 9),
        "nyquist_zone": zone,
        "vsw_zone_m": vsw_zone_m,
        "alias_status": status,
        "alias_free": status == "alias_free_strict",
        "folded_low_hz": round(_fold_hz(fl, fs), 9),
        "folded_center_hz": round(_fold_hz(fc, fs), 9),
        "folded_high_hz": round(_fold_hz(fh, fs), 9),
        "guard_low_hz": round(g_lo, 9),
        "guard_high_hz": round(g_hi, 9),
        "boundary_touching": status == "boundary_touching",
        "note": (
            "三态如实：alias_free_strict=严格单区内（保护带 >0）；"
            "boundary_touching=带缘恰触 k·fs/2（零保护带理论点，fs 微扰即"
            "混叠，不判绿）；alias_overlap=跨边界真实混叠。vsw_zone_m=候"
            "选 fs 所在 VSW 可行档（None=不在任何可行区间）；f_in 取模拟"
            "最高频率 f_H"),
        "source": (
            "折叠恒等式第一性；三态判定=防混叠条件（带不跨 k·fs/2 边"
            "界）；VSW 区间回查同 bandpass_sampling_plan 单源口径"),
    }
    if sigma_jitter_s is not None:
        from rfauto.core.adc_budget import snr_jitter_db  # 单源消费零复制

        sj = _finite_nb(sigma_jitter_s, f"{tag}.sigma_jitter_s")
        if sj < 0.0:
            raise ValueError(
                f"{tag}: sigma_jitter_s 必须 >=0，得到 {sigma_jitter_s!r}")
        out["sigma_jitter_s"] = round(sj, 18)
        out["jitter_f_in_hz"] = round(fh, 9)
        out["snr_jitter_db"] = (None if math.isinf(
            snr_jitter_db(fh, sj)) else round(snr_jitter_db(fh, sj), 9))
        out["snr_jitter_inf"] = math.isinf(snr_jitter_db(fh, sj))
        out["note"] = (
            out["note"] + "；snr_jitter_db 经 adc_budget.snr_jitter_db 同"
            "式消费（MT-007：−20lg(2π·f_in·σ_j)，f_in=f_H 模拟最高频率；"
            "σ_j=0 → inf 以 snr_jitter_inf 旗标透出，JSON 禁 inf）")
    return out
