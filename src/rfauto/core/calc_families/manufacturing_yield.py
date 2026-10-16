"""制造良率换算族（aurora_d W3-CORE7 席域 1，R7_core_tier2 附加候选
"Cpk→良率% / 多工序串联良率" 顺手件，2026-10-14）。

两键：cpk_yield_convert（Cpk↔良率 正态尾双向换算——Cpk→良率单尾工业标准档
Φ(3Cpk) 或给双限边际 (Cu,Cl) 精确两尾 Φ(3Cu)·Φ(3Cl)；良率→Cpk 反解
Φ⁻¹/3 双档）/ serial_yield_budget（多工序串联良率——独立乘积 + 等相关
高斯潜变量精确合并 + Fréchet-Hoeffding 界，相关性口径如实声明）。

与既有面的边界（#222 树面核实，2026-10-14 实测）
------------------------------------------------
- core/manufacturing_stats.py（PT-1/2/3 内核，`rfauto stats` CLI 薄壳）=
  **样本→能力指数置信区间**（guardband/cpk_ci/weibull_mle，Bissell 1990）
  ——本族是 **能力指数↔良率正态尾换算** 与 **多工序串联合并** 面，不消费
  样本、不出置信区间，语义互补不重复（R7 原文"manufacturing_stats(cpk_ci)
  +tolerance_allocation 已覆盖 Cpk 面，yield 换算建议原位 +1"——CALC 注册
  键面本域零命中（grep cpk|yield|manufactur 195 键实测零），故立新族）。
- core/tolerance_allocation.py cpk_from_tols = **公差→Cpk 点估计重算**、
  yield_to_output_sigma = 良率目标→输出 σ（六西格玛设计口径）——本族是
  Cpk/良率**双向换算与串联合并**，不分配公差、不做 σ 汇总。
- core/acceptance_sampling.py = 抽样检验 OC 曲线面（计件抽检），不在本族。

物理口径（docstring 写死，#1c/#300/#118 出处纪律）
------------------------------------------------
1. **Cpk↔良率（正态过程，Montgomery《Introduction to Statistical Quality
   Control》ch.7 过程能力/过程出界率节，章节级转引）**：规格边际指数
   Cu=(USL−μ)/(3σ)、Cl=(μ−LSL)/(3σ)，Cpk=min(Cu,Cl)。单侧出界率
   p = 1−Φ(3C)（C 为该侧边际），良率 = Φ(3C)。工业标准"Cpk→良率"表值
   = 单尾口径（假定出界集中于近限侧）：Cpk=1→出界 1349.9 ppm、4/3→
   31.7 ppm、5/3→0.287 ppm、2→0.987 ppb（锚树逐位钉）。
   **仅知 Cpk（=min）时两尾良率不可唯一确定**——如实给界：
   Φ(3Cpk)² ≤ yield ≤ Φ(3Cpk)（近限侧取 Cpk、远限侧 ≥Cpk 的单调性；
   下界=两侧同取 Cpk 的居中最坏档，上界=远限侧出界为零的最好档），
   并在 notes 声明。给全 (Cu,Cl) 时良率精确 = Φ(3Cu)·Φ(3Cl)（两尾
   独立正态尾乘积，锚树 scipy 双侧积分第二路线互证）。
   反解（良率→Cpk）：单尾档 Cpk = Φ⁻¹(y)/3；居中两尾档
   Cpk = Φ⁻¹((1+y)/2)/3（Cp=Cpk 对称假定，档位如实声明不冒充唯一）。
2. **多工序串联良率**：
   - 独立口径（缺省）：总良率 Y = ∏y_i（串联系统可靠性乘积律，Rausand
     & Høyland, *System Reliability Theory*, 2nd ed., Wiley 2004 串联
     结构节，章节级转引）；总 DPMO = (1−Y)·1e6。
   - 等相关口径（给 rho>0）：各工序潜在质量分位 z_i ~ 等相关多元正态
     （两两相关系数 ρ），工序 i 达标当 z_i ≤ t_i=Φ⁻¹(y_i)，联合良率
     条件分解恒等式（标准多元正态结果，一章 level 转引）::

         Y_joint(ρ) = ∫ φ(z)·∏_i Φ((t_i − √ρ·z)/√(1−ρ)) dz

     数值=scipy quad 自适应积分（GH Gauss-Hermite 第二路线锚树互证
     ≤3e-16 @ρ≤0.8）；**双极限锚**：ρ=0 → ∏y_i（独立退化，逐位）、
     ρ→1⁻ → min(y_i)（完全共因退化，测试钉）。
   - 相关性界（任意相关结构，恒真）：Fréchet–Hoeffding 界（Nelsen,
     *An Introduction to Copulas*, 2nd ed., Springer 2006，章节级转引）
     max(0, Σy_i−(N−1)) ≤ Y_joint ≤ min(y_i)——独立乘积恒在界内
     （锚树断言），给出即如实并列，不冒充精确。

出处（Montgomery, *Introduction to Statistical Quality Control*, 7th ed.,
Wiley 2019, ch.7 过程能力比与过程出界率——正态尾恒等式 p=1−Φ(3Cpk) 与
Cpk 良率表值口径，章节级转引，式号不落键面；两尾精确式 Φ(3Cu)·Φ(3Cl) 与
仅知 Cpk 的界 [Φ(3Cpk)²,Φ(3Cpk)] 为本仓正态单调性第一性推导；串联乘积律：
Rausand & Høyland, *System Reliability Theory*, 2nd ed., Wiley 2004 串联
结构节（章节级转引）；Fréchet–Hoeffding 界：Nelsen, *An Introduction to
Copulas*, 2nd ed., Springer 2006（章节级转引）；等相关正态联合达标概率
条件分解恒等式=标准多元正态结果（chapter 级转引）。实现前独立复算：
Montgomery 表值 1350/31.7/0.287 ppm 档逐位+scipy sf/ppf 第二路线+quad vs
Gauss–Hermite 双数值路线（ρ=0 退化乘积逐位、ρ→1 退化 min(y) 双极限锚），
独立验证轨迹（内部档），锚树
tests/unit/test_aurora_d_core7.py。）

守卫：cpk≥0 有限（0 合法=均值恰在规格限，#364④ is not None 判缺失）；
cpk_upper/cpk_lower 成对给且与 cpk=min 一致（违背显式拒绝）；yield∈(0,1)
开区间（0/1 → Cpk 无穷档显式拒绝）；spec_side 白名单；yields 非空序列、
每元素 ∈(0,1]、条数 1..64；rho ∈ [0,1)（1 恰值=完全相关退化仅作极限锚
不收输入）；route 二选一（同给/全缺显式拒绝）；数值 0.0 合法面判缺失一律
is not None；无 IO、dict 进出 JSON 可序列化。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

#: 单键联合良率积分的最大工序数（积分稳定域，超界显式拒绝）
_MAX_STAGES = 64

_SOURCES = {
    "convert": (
        "Montgomery, Introduction to Statistical Quality Control, 7th ed., "
        "Wiley 2019, ch.7 过程能力比与过程出界率（正态尾恒等式 p=1−Φ(3Cpk)、"
        "Cpk 良率表值口径，章节级转引，式号不落键面）；两尾精确式 "
        "Φ(3Cu)·Φ(3Cl) 与仅知 Cpk 的界 [Φ(3Cpk)²,Φ(3Cpk)] 为本仓正态"
        "单调性第一性推导（实现前独立复算：Montgomery 表值 1350/31.7/"
        "0.287 ppm 档逐位 + scipy 双侧积分第二路线，锚树 "
        "tests/unit/test_aurora_d_core7.py）"),
    "serial": (
        "串联乘积律：Rausand & Høyland, System Reliability Theory, 2nd ed., "
        "Wiley 2004 串联结构节（章节级转引）；Fréchet–Hoeffding 界：Nelsen, "
        "An Introduction to Copulas, 2nd ed., Springer 2006（章节级转引）；"
        "等相关正态联合达标概率条件分解恒等式 = 标准多元正态结果（一章 "
        "level 转引）+ 本仓 quad/GH 双数值路线互证（ρ=0 独立退化逐位、"
        "ρ→1 min(y) 完全相关退化双极限锚）"),
}


def _normal_tail(cpk: float) -> float:
    """单尾出界率 1−Φ(3·cpk)（正态 survival，SF 口径消 1−CDF 相消）。"""
    from scipy import stats

    return float(stats.norm.sf(3.0 * cpk))


def _quantile(p: float) -> float:
    from scipy import stats

    return float(stats.norm.ppf(p))


@register_calculator(
    "cpk_yield_convert",
    "Cpk↔良率正态尾双向换算：Cpk→良率（单尾工业标准档 Φ(3Cpk)=Montgomery "
    "表值口径 + 可选双限边际 (Cu,Cl) 精确两尾 Φ(3Cu)·Φ(3Cl) + 仅知 Cpk 的"
    "界 [Φ(3Cpk)²,Φ(3Cpk)] 如实声明）；良率→Cpk 反解 Φ⁻¹/3（单尾/居中两尾"
    "双档声明）；随行 ppm/DPMO 面出界率",
    (("cpk", "float 过程能力指数 Cpk（≥0；Cpk→良率路线，与 yield_frac 二选一）"),
     ("yield_frac", "float 良率小数（0<Y<1 开区间；反解路线）"),
     ("cpk_upper", "float 上侧边际指数 Cu=(USL−μ)/(3σ)（成对与 cpk_lower；"
      "给了才出精确两尾档）"),
     ("cpk_lower", "float 下侧边际指数 Cl=(μ−LSL)/(3σ)（成对与 cpk_upper）"),
     ("spec_side", "str 反解档位 one_sided|two_sided_centered（缺省 "
      "one_sided，档位假设如实进 note）")),
    required=(),
)
def cpk_yield_convert(
    cpk: float | None = None,
    yield_frac: float | None = None,
    cpk_upper: float | None = None,
    cpk_lower: float | None = None,
    spec_side: str = "one_sided",
) -> dict[str, Any]:
    """Cpk↔良率双向换算（route 分派：cpk 入=正解，yield_frac 入=反解）。"""
    has_cpk = cpk is not None
    has_yield = yield_frac is not None
    if has_cpk and has_yield:
        raise ValueError(
            "cpk_yield_convert: cpk（正解路线）与 yield_frac（反解路线）"
            "二选一（同给显式拒绝，route 不可分派）")
    if not has_cpk and not has_yield:
        raise ValueError(
            "cpk_yield_convert: 须给 cpk（Cpk→良率）或 yield_frac（良率→"
            "Cpk）之一（全缺显式拒绝）")

    has_margins = cpk_upper is not None or cpk_lower is not None
    if has_margins and (cpk_upper is None or cpk_lower is None):
        raise ValueError(
            "cpk_yield_convert: cpk_upper/cpk_lower 须成对给（单给显式拒绝）")
    if spec_side not in ("one_sided", "two_sided_centered"):
        raise ValueError(
            "cpk_yield_convert: spec_side 须 one_sided|two_sided_centered，"
            f"得到 {spec_side!r}")

    if has_cpk:
        c_val = _finite(cpk, "cpk")
        if c_val < 0.0:
            raise ValueError(
                f"cpk_yield_convert: cpk 必须 ≥0（能力指数非负），得到 {cpk!r}")
        cpk_v = c_val
        if has_margins:
            cu = _finite(cpk_upper, "cpk_upper")
            cl = _finite(cpk_lower, "cpk_lower")
            if cu < 0.0 or cl < 0.0:
                raise ValueError(
                    "cpk_yield_convert: cpk_upper/cpk_lower 必须 ≥0")
            if abs(min(cu, cl) - cpk_v) > 1e-12 * max(1.0, cpk_v):
                raise ValueError(
                    f"cpk_yield_convert: 口径不一致——cpk={cpk_v!r} 但 "
                    f"min(Cu,Cl)={min(cu, cl)!r}（Cpk=min(Cu,Cl) 定义，"
                    "违背显式拒绝）")
        route = "cpk_to_yield"
    else:
        if has_margins:
            raise ValueError(
                "cpk_yield_convert: cpk_upper/cpk_lower 仅属 Cpk→良率路线"
                "（反解路线同给显式拒绝）")
        y_val = _finite(yield_frac, "yield_frac")
        if not 0.0 < y_val < 1.0:
            raise ValueError(
                "cpk_yield_convert: yield_frac 必须 ∈(0,1) 开区间（0/1 对应 "
                f"Cpk 无穷档），得到 {yield_frac!r}")
        cpk_v = None
        route = "yield_to_cpk"

    notes: list[str] = []
    out: dict[str, Any] = {"route": route, "spec_side": spec_side}

    if route == "cpk_to_yield":
        tail_one = _normal_tail(cpk_v)
        yield_one = 1.0 - tail_one
        out.update({
            "cpk": cpk_v,
            "yield_frac": yield_one,
            "yield_pct": yield_one * 100.0,
            "defect_frac_one_tail": tail_one,
            "dpmo_one_tail": tail_one * 1e6,
            "margin_z": 3.0 * cpk_v,
        })
        if has_margins:
            cu = float(cpk_upper)
            cl = float(cpk_lower)
            y_exact = (1.0 - _normal_tail(cu)) * (1.0 - _normal_tail(cl))
            out.update({
                "cpk_upper": cu,
                "cpk_lower": cl,
                "yield_frac_exact_two_tail": y_exact,
                "yield_pct_exact_two_tail": y_exact * 100.0,
                "dpmo_exact_two_tail": (1.0 - y_exact) * 1e6,
            })
            notes.append(
                "两尾精确档：yield=Φ(3Cu)·Φ(3Cl)（两尾独立正态尾乘积）；"
                "yield_frac/dpmo 主字段=单尾工业标准档（近限侧口径），"
                "与精确档并列不混用")
        else:
            y_lo = yield_one * yield_one
            out.update({
                "yield_frac_lower_bound": y_lo,
                "yield_frac_upper_bound": yield_one,
            })
            notes.append(
                "仅知 Cpk（=min(Cu,Cl)）时两尾良率不可唯一确定：给界 "
                "Φ(3Cpk)² ≤ Y ≤ Φ(3Cpk)（下界=两侧同取 Cpk 的居中最坏档、"
                "上界=远限侧出界为零档）；主字段=单尾工业标准档——需精确值"
                "请给 cpk_upper/cpk_lower 双限边际")
        notes.append(
            "正态过程假定（μ/σ 已知无抽样误差）；本键为点换算，样本→Cpk "
            "置信区间走 `rfauto stats cpk`（core/manufacturing_stats）"
            "互补不重复")
        out["note"] = "；".join(notes)
        out["source"] = _SOURCES["convert"]
        return out

    # 反解：良率→Cpk
    y = float(yield_frac)
    if spec_side == "one_sided":
        cpk_back = _quantile(y) / 3.0
        assumption = "单尾档：全部出界集中于单侧（近限侧），Cpk=Φ⁻¹(Y)/3"
        tail_back = 1.0 - y
    else:
        cpk_back = _quantile((1.0 + y) / 2.0) / 3.0
        assumption = "居中两尾档：Cp=Cpk 对称假定（μ 居规格中心），Cpk=Φ⁻¹((1+Y)/2)/3"
        tail_back = 1.0 - y
    out.update({
        "yield_frac": y,
        "yield_pct": y * 100.0,
        "cpk": cpk_back,
        "margin_z": 3.0 * cpk_back,
        "dpmo": tail_back * 1e6,
    })
    notes.append(
        assumption + "——良率→Cpk 逆映射不唯一（依赖分布假定），档位假设"
        "如实声明不冒充唯一解")
    notes.append(
        "正态过程假定；与 tolerance_allocation.yield_to_output_sigma（"
        "良率目标→输出 σ 六西格玛口径）互补不重复")
    out["note"] = "；".join(notes)
    out["source"] = _SOURCES["convert"]
    return out


@register_calculator(
    "serial_yield_budget",
    "多工序串联良率预算：独立口径乘积 ∏y_i + 总 DPMO；可选等相关高斯潜变"
    "量精确合并（rho>0，条件分解 1D 积分，ρ=0 退化乘积/ρ→1 退化 min 双极"
    "限锚）；任意相关结构恒真 Fréchet–Hoeffding 界 [max(0,Σy−N+1), min(y)] "
    "如实并列（相关性口径声明，不冒充精确）",
    (("yields", "array 各工序良率小数序列（每元素 ∈(0,1]，1..64 条）"),
     ("rho", "float 等相关系数 ρ（[0,1)；缺省 0=独立乘积精确；>0 走等相关"
      "高斯合并口径）")),
    required=("yields",),
)
def serial_yield_budget(
    yields: list,
    rho: float = 0.0,
) -> dict[str, Any]:
    """多工序串联良率（独立乘积 + 可选等相关精确合并 + Fréchet 界并列）。"""
    from scipy import integrate, stats

    if isinstance(yields, (str, bytes, bool)) or not hasattr(yields, "__len__"):
        raise ValueError(
            f"serial_yield_budget: yields 必须是数值序列，得到 {yields!r}")
    ys_raw = [float(v) for v in yields]
    if not ys_raw:
        raise ValueError("serial_yield_budget: yields 不能为空")
    if len(ys_raw) > _MAX_STAGES:
        raise ValueError(
            f"serial_yield_budget: 工序数须 ≤{_MAX_STAGES}，得到 {len(ys_raw)}")
    for i, y in enumerate(ys_raw):
        if not math.isfinite(y) or not 0.0 < y <= 1.0:
            raise ValueError(
                f"serial_yield_budget: yields[{i}] 必须 ∈(0,1]（0=整链必废"
                f"退化档不收），得到 {yields[i]!r}")
    rho_v = _finite(rho, "rho")
    if not 0.0 <= rho_v < 1.0:
        raise ValueError(
            f"serial_yield_budget: rho 必须 ∈[0,1)（1=完全相关仅作极限锚，"
            f"不收输入），得到 {rho!r}")

    n = len(ys_raw)
    product = math.prod(ys_raw)
    frechet_lo = max(0.0, sum(ys_raw) - (n - 1))
    frechet_hi = min(ys_raw)

    out: dict[str, Any] = {
        "n_stages": n,
        "yields": [round(y, 15) for y in ys_raw],
        "rho": rho_v,
        "yield_independent": product,
        "yield_pct_independent": product * 100.0,
        "dpmo_independent": (1.0 - product) * 1e6,
        "frechet_lower": frechet_lo,
        "frechet_upper": frechet_hi,
    }
    notes: list[str] = []

    if rho_v > 0.0:
        t_vec = [_quantile(y) for y in ys_raw]
        sq_rho = math.sqrt(rho_v)
        sq_om = math.sqrt(1.0 - rho_v)
        log_cdf = stats.norm.logcdf
        # 各 Φ 因子膝点 z=t_i/√ρ 作为 quad 强制分段点（高良率+高 ρ 时
        # 被积函数在该处台阶式下降，自适应细分漏段防线）
        knees = sorted({min(14.0, max(-14.0, t / sq_rho)) for t in t_vec})

        def integrand(z: float) -> float:
            acc = 0.0
            for t in t_vec:
                lp = log_cdf((t - sq_rho * z) / sq_om)
                if lp == -math.inf:
                    return 0.0
                acc += lp
            return math.exp(acc - 0.5 * z * z) / math.sqrt(2.0 * math.pi)

        joint, err = integrate.quad(integrand, -14.0, 14.0, limit=400,
                                    points=knees)
        out.update({
            "yield_correlated": float(joint),
            "yield_pct_correlated": float(joint) * 100.0,
            "dpmo_correlated": (1.0 - joint) * 1e6,
            "quad_abserr": float(err),
            "dev_from_independence": float(joint) - product,
        })
        notes.append(
            f"等相关口径（ρ={rho_v}）：联合良率=∫φ(z)·∏Φ((t_i−√ρ·z)/"
            "√(1−ρ))dz（条件分解恒等式，quad 自适应积分；quad_abserr 为"
            "数值误差面）。正相关使联合良率高于独立乘积（共因波动同涨同落，"
            "坏年景全体同坏但达标事件绑定高分位潜变量）——与独立口径并列"
            "如实双报，选哪个口径由实际工序相关结构决定")
    notes.append(
        "Fréchet–Hoeffding 界（任意相关结构恒真）：max(0,Σy−(N−1)) ≤ "
        "Y_joint ≤ min(y)；独立乘积恒在界内（锚树断言）——仅知边缘良率时"
        "联合良率不可唯一确定，界与所选口径并列不冒充精确")
    if n == 1:
        notes.append("单工序退化：乘积/合并/界三口径同值（=y_1，锚树钉）")
    notes.append(
        "独立口径=串联系统可靠性乘积律；良率→Cpk 单工序换算走 "
        "cpk_yield_convert 互补")
    out["note"] = "；".join(notes)
    out["source"] = _SOURCES["serial"]
    return out
