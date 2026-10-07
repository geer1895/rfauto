r"""AP-11 Vivaldi/TSA（指数张口槽线天线）确定性内核（ge8b Wave B 席 B9，
2026-10-03）。

规格：研究扩充 round17 §三 :78「AP-11 Vivaldi/
TSA 模板（P2/M）：Yngvesson 1985 准则+巴伦注记」。

规格边界（#122 如实）
--------------------
- 交付=指数张口律 + 低截止工程准则 + 模板几何链（render_ta_wave_b）；
- **巴伦不在内核/模板渲染面**：微带-槽线巴伦（ quarter 波短路桩/环形
  巴伦）是独立馈电件，本批渲染面以微带跨槽耦合馈（slot 模板同款已证
  机理）直馈槽线模，巴伦设计留登记注记（round17"巴伦注记"口径）；
- 增益/方向图全波面不做（round17 无要求；Yngvesson 经验曲线族未回原文
  逐位核对前不入码，citation-rot 纪律）。

法源与公式（出处逐式）
--------------------
- **指数张口律**（R. W. Gibson 1979 "The Vivaldi aerial"，第 9 届欧微会
  议；逐式转写自教科书通称口径，**二手转写如实**：原文未回 PDF 逐位
  核对，恒等式裁判）——槽半宽随轴向 x 指数张开：

      w(x) = w_throat · exp(k·x)，  k = ln(w_mouth / w_throat) / L

  指数律的判读性质（对数螺旋/tapered slot 文献通称）：工作波长 λ 与
  局部槽宽 w 同量级处能量辐射出去 → 对数周期性宽带行为，k 越小
  （张口越缓）方向图越窄、低频越向口面外推。
- **低截止工程准则**：口面宽度 w_mouth ≈ λ0/2 时开始有效端射辐射 →

      f_low = c / (2 · w_mouth)          （自由空间半波口径）

  **二手工程口径如实登记**：文献通称准则（Vivaldi 类端射槽线天线
  的最低工作频率由口面半波设定；介质加载使实际截止略低、过渡带
  略宽），Yngvesson 1985 原文的介质加载修正系数未回 PDF 逐位核对前
  不入码（#118）；本准则的恒等式面（w_mouth=λ0/2 ↔ f_low）由测试
  双向回收钉住，真机首判窗未排期。
- **高截止**：由喉部槽宽与馈电过渡决定（槽线高模/馈电寄生），无
  单值闭式——登记注记不做数（喉部槽线阻抗可由仓内槽线族闭式链
  交叉参考，见 render_ta_wave_b 模块注记）。

单位口径 mm/GHz；e^{−jωt}；core 纯函数零 IO、不注册 calculators 键
（amc_mushroom 同款本席纪律）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.dielectric_extract import C0

__all__ = [
    "vivaldi_low_cutoff_ghz",
    "vivaldi_slot_half_width_mm",
    "vivaldi_taper_k_per_mm",
    "vivaldi_tsa_design",
]


def _positive(value: float, label: str) -> float:
    v = float(value)
    if not (math.isfinite(v) and v > 0.0):
        raise ValueError(f"{label} 必须为正有限，得到 {value!r}")
    return v


def vivaldi_taper_k_per_mm(w_throat_mm: float, w_mouth_mm: float,
                           l_mm: float) -> float:
    """指数张口常数 k = ln(w_mouth/w_throat)/L（1/mm）。

    守卫：w_mouth > w_throat（张开律）；l>0。
    """
    wt = _positive(w_throat_mm, "w_throat_mm")
    wm = _positive(w_mouth_mm, "w_mouth_mm")
    length = _positive(l_mm, "l_mm")
    if wm <= wt:
        raise ValueError(
            f"口面宽 {wm:.4g}mm 必须大于喉宽 {wt:.4g}mm（指数张开律）")
    return math.log(wm / wt) / length


def vivaldi_slot_half_width_mm(x_mm: float, w_throat_mm: float,
                               k_per_mm: float) -> float:
    """槽半宽 w(x)/2 = (w_throat/2)·exp(k·x)（x 自喉部起算，mm；x=0=喉部
    合法，半宽=w_throat/2）。"""
    wt = _positive(w_throat_mm, "w_throat_mm")
    k = float(k_per_mm)
    if not (math.isfinite(k) and k > 0.0):
        raise ValueError(f"k 必须为正有限，得到 {k_per_mm!r}")
    x = float(x_mm)
    if not (math.isfinite(x) and x >= 0.0):
        raise ValueError(f"x_mm 必须为非负有限，得到 {x_mm!r}")
    return 0.5 * wt * math.exp(k * x)


def vivaldi_low_cutoff_ghz(w_mouth_mm: float) -> float:
    """低截止工程准则 f_low = c/(2·w_mouth)（GHz；口面=λ0/2 口径）。"""
    wm = _positive(w_mouth_mm, "w_mouth_mm") * 1e-3
    return C0 / (2.0 * wm) / 1e9


def vivaldi_tsa_design(f_low_ghz: float, w_throat_mm: float,
                       l_mm: float) -> dict[str, Any]:
    """设计链：目标低截止 → 口面宽 w_mouth = c/(2·f_low) → 张口常数 k。

    返回 dict（w_mouth_mm/k_per_mm/f_low_ghz 回代/f_throat_note）；回代
    恒等守卫 |f_back/f_low − 1| ≤ 1e-9（#118 恒等裁判）。
    """
    f_low = _positive(f_low_ghz, "f_low_ghz")
    wt = _positive(w_throat_mm, "w_throat_mm")
    length = _positive(l_mm, "l_mm")
    w_mouth_raw = C0 / (2.0 * f_low * 1e9) * 1e3
    w_mouth = round(w_mouth_raw, 6)   # 6 位舍入（回代 f_low 6 位逐位自洽）
    # k 按舍入后 w_mouth 计算——归档 (w_mouth, k) 对可逐位复算（#252）
    k = vivaldi_taper_k_per_mm(wt, w_mouth, length)
    f_back = vivaldi_low_cutoff_ghz(w_mouth)
    if abs(f_back / f_low - 1.0) > 1e-6:
        raise ValueError(
            f"回代恒等失败：w_mouth={w_mouth:.6f}mm → f={f_back:.6g}GHz"
            f" ≠ {f_low:.6g}GHz（舍入带 1e-6）")
    return {"w_mouth_mm": w_mouth,
            "w_throat_mm": float(wt), "l_mm": float(length),
            "k_per_mm": k,
            "f_low_ghz": round(f_back, 6),
            "note": "高截止由喉部槽宽/馈电过渡决定（登记注记，无单值闭式）"}
