"""FORM 可靠度注册壳（XD-11，内核 core/form_reliability.py，本模块只做注册壳）。

规格 研究扩充_crossdomain_transplant.md XD-11（池
第二十轮，2026-10-04）：uq_service 良率全走代理蒙特卡洛，稀有良率
（Pf<1e-3）MC 样本爆炸——FORM 在已校准代理/闭式极限状态面上是几十次
迭代的纯 numpy。一键：
- form_beta_linear：线性极限状态面便捷封装（g=offset−a·x<0 失效）。
  HL-RF 内核路径与闭式 β=(offset−aᵀμ)/||a·σ|| 双路径互证（字段
  beta/beta_closed_form）；α=a·σ/||a·σ||=失效方向单位灵敏度。

form_beta/sorm_beta_correction 及正态数值件（erfc 尾式 Pf/Acklam 逆
CDF）为 core 纯函数不注册（分析面走 core 直调；非线性面/黑盒代理面
直接调 core.form_reliability.form_beta）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator


@register_calculator(
    "form_beta_linear",
    "XD-11 FORM 一阶可靠度·线性极限状态面便捷键：g(x)=offset−Σcoeff_i·x_i"
    "<0 失效（Hasofer-Lind 1974 β 几何定义 / Rackwitz-Fiessler 1978 "
    "HL-RF 迭代；OpenTURNS FORM 例题族方法学参照）。线性面 HL-RF 一步"
    "到解且与闭式 β=(offset−aᵀμ)/||a·σ|| 逐位一致（双路径互证字段 "
    "beta_closed_form）；Pf=Φ(−β)；α=a·σ/||a·σ||=失效方向单位灵敏度"
    "（|α_i| 大=第 i 个参数的公差/σ 把 Pf 拖得最狠）。stddev 逐元素>0；"
    "均值点已入失效域（β<0）如实返回 Pf>0.5 不翻符号。非线性面走 "
    "core.form_reliability.form_beta（黑盒 callable）直调",
    (("coeffs", "list[float] 线性系数 a（g=offset−a·x；非全零）"),
     ("offset", "float 截距 offset=g(0)（安全裕度项，>0=均值点安全）"),
     ("mean", "list[float] 各变量均值 μ（与 coeffs 等长）"),
     ("stddev", "list[float] 各变量标准差 σ（逐元素>0）")),
    required=("coeffs", "offset", "mean", "stddev"),
)
def form_beta_linear(coeffs: Any, offset: Any, mean: Any,
                     stddev: Any) -> dict:
    from rfauto.core.form_reliability import form_beta as _form_beta

    a = [float(v) for v in coeffs]
    mu = [float(v) for v in mean]
    sd = [float(v) for v in stddev]
    b = float(offset)
    if not a or len(mu) != len(a) or len(sd) != len(a):
        raise ValueError(
            f"coeffs/mean/stddev 长度必须一致非空: {len(a)}/{len(mu)}/{len(sd)}")
    if not (math.isfinite(b) and all(math.isfinite(v) for v in a + mu + sd)):
        raise ValueError("入参含非有限值")
    if all(v == 0.0 for v in a):
        raise ValueError("全零线性系数=常数面：β 无定义（安全裕度请直接判 offset 符号）")

    def g(x: Any) -> float:
        return b - sum(ai * float(xi) for ai, xi in zip(a, x, strict=True))

    res = _form_beta(g, mu, sd)

    # 闭式双路径（独立于 HL-RF 数值路径的互证面）
    asig = [ai * si for ai, si in zip(a, sd, strict=True)]
    norm = math.sqrt(sum(v * v for v in asig))
    beta_cf = (b - sum(ai * mi for ai, mi in zip(a, mu, strict=True))) / norm
    alpha_cf = [v / norm for v in asig]
    return {
        "beta": float(res.beta),
        "beta_closed_form": float(beta_cf),
        "pf_form": float(res.pf_form),
        "alpha": [float(v) for v in res.alpha],
        "alpha_closed_form": [float(v) for v in alpha_cf],
        "design_point_x": [float(v) for v in res.design_point_x],
        "n_iter": int(res.n_iter),
        "converged": bool(res.converged),
    }
