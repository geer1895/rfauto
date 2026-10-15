"""thz_vna 族（TH-2 TNVNA 扩频误差模型+跨带拼接键面，SB22-TH-2）。

内核在 core/thz_vna.py（经典一端口三项误差模型闭式反演 + 一阶灵敏度
RSS 预算 + 两带重叠线性权重拼接器；文献口径与守卫见该模块 docstring），
本模块只做注册薄壳（同 cdr_mask/rx_impairments 惯例）。两键：

- tnvna_extender_error_model：THz VNA 扩频器一端口误差修正 + 修正后
  逐点 1σ 预算。误差项（Ed/Es/Er）按带级标定给入（标量 [re,im] 广播）
  或逐点；残余 σ 调用方给入（缺省 0）。
- tnvna_band_stitch：相邻两带拼接 + 重叠区一致性判据（max|ΔS| vs 调用
  方 tol_abs_linear，#122：阈值不 ship 标准门限）+ 带界不确定度预算；
  重叠区异栅格 v1 如实拒绝（不静默插值）。

登记语义：SB22-TH-2"扩频器误差模型语义+跨带拼接器+带界不确定性预算"
键面兑现（净表"硬件门后置"指实机段；本键面=确定性内核，合成对拍）。
N>2 带链式拼接与跨栅插值为登记 followUp。
"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator


@register_calculator(
    "tnvna_extender_error_model",
    "扩频VNA误差：TH-2 THz VNA 扩频器一端口三项误差模型修正+1σ 预算："
    "Γ=(M−Ed)/(Er+Es·(M−Ed))（经典一端口误差模型闭式反演，Hesler "
    "ISSTT 2010 按带标定语义）；预算=一阶灵敏度 RSS（NIST MUF 口径）"
    "σ_Γ=sqrt(|Er|²(σM²+σEd²)+|N|⁴σEs²+|N|²σEr²)/|D|²，N=M−Ed、"
    "D=Er+Es·N。Ed/Es/Er 为带级标定复数（标量 [re,im] 广播）或逐点；"
    "σ 四项=修正后残余幅值（线性域，≥0，缺省 0）。域守卫：|Er| 逐点"
    "非零、修正分母非零（奇异显式拒绝不外推）",
    (("freq_hz", "list[float] Hz 频率点列（>=1 点，全正）"),
     ("measured", "list[[re,im]] 原始（未修正）反射复数列"),
     ("ed", "[re,im] 或 list[[re,im]] directivity 误差项"),
     ("es", "[re,im] 或 list[[re,im]] source match 误差项"),
     ("er", "[re,im] 或 list[[re,im]] reflection tracking 误差项"),
     ("sigma_m", "float 原始测量残余 1σ（线性域，缺省 0）"),
     ("sigma_ed", "float Ed 残余 1σ（缺省 0）"),
     ("sigma_es", "float Es 残余 1σ（缺省 0）"),
     ("sigma_er", "float Er 残余 1σ（缺省 0）")),
    required=("freq_hz", "measured", "ed", "es", "er"),
)
def tnvna_extender_error_model(freq_hz: list[float],
                               measured: list[list[float]],
                               ed: list[float] | list[list[float]],
                               es: list[float] | list[list[float]],
                               er: list[float] | list[list[float]],
                               sigma_m: float = 0.0,
                               sigma_ed: float = 0.0,
                               sigma_es: float = 0.0,
                               sigma_er: float = 0.0) -> dict:
    import numpy as np

    from rfauto.core.thz_vna import (
        _as_complex_array,
        _check_freq_grid,
        extender_correct_oneport,
        extender_oneport_budget,
    )

    freq = np.asarray([float(f) for f in freq_hz], dtype=float)
    _check_freq_grid(freq, "freq_hz")
    n = freq.shape[0]
    m = _as_complex_array(measured, "measured")
    if m.shape[0] == 1 and n == 1:
        m = m.reshape(1)
    if m.shape[0] != n:
        raise ValueError(f"measured 点数须与 freq_hz 一致（{n}，逐点测量"
                         f"不广播），得 {m.shape[0]}")
    g = extender_correct_oneport(m, ed, es, er)
    sig = extender_oneport_budget(m, ed, es, er,
                                  sigma_m, sigma_ed, sigma_es, sigma_er)
    return {
        "model": "one-port three-term (Ed/Es/Er)",
        "freq_hz": [float(x) for x in freq],
        "gamma_corr": [[float(v.real), float(v.imag)] for v in g],
        "gamma_corr_db": [float(20.0 * np.log10(abs(v)))
                          if abs(v) > 0.0 else None for v in g],
        "sigma_gamma": [float(x) for x in sig],
    }


@register_calculator(
    "tnvna_band_stitch",
    "TH-2 TNVNA 跨带拼接器：相邻两带（低/高由 f_start 判定）在重叠区按"
    "到带缘归一距离线性权重合并（带缘 C0 连续），输出全带拼接曲线；重叠"
    "一致性=max|S_low−S_high| vs 调用方 tol_abs_linear（#122 阈值不 "
    "ship）→ consistent/inconsistent；带界预算=权重合成 σ="
    "sqrt((w·σlo)²+((1−w)·σhi)²) 逐点（max+两带缘）。域守卫：两带频栅"
    "严格递增全正；重叠区必须同频点（异栅格如实拒绝不静默插值）；恰共点"
    "=退化单点重叠等权合并；无重叠=butt 直连如实报告"
    "（verdict='no_overlap'）。N>2 带链式拼接为登记 followUp",
    (("band_a", "dict {freq_hz, s(list[[re,im]]), sigma, name?}"),
     ("band_b", "dict 同 band_a"),
     ("tol_abs_linear", "float 重叠区一致性阈值（线性域 |ΔS|，>=0，必填）")),
    required=("band_a", "band_b", "tol_abs_linear"),
)
def tnvna_band_stitch(band_a: dict[str, Any], band_b: dict[str, Any],
                      tol_abs_linear: float) -> dict:
    from rfauto.core.thz_vna import band_stitch_two

    return band_stitch_two(band_a, band_b, tol_abs_linear)
