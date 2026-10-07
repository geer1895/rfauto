"""M-1 GWINC 式误差源分解账本（noise budget ledger，纯算法零 IO）。

方案：研究扩充 §三 M-1（P1=框架+首批 3 源条目；
条目扩容属 Ph4 GWINC 扩容批）。把散落在 坑号里的离散误差知识固化成
可计算账本：每源一个确定性贡献函数，实测总量叠加各源贡献，未解释残差=
调查靶向行（GWINC 的"residual 指向下一步调查"语义）。

机制出处：LIGO GWINC（PyPI gwinc 0.6.2，Unlicense 许可，无许可负担）——
BudgetItem 组合体机制借镜+自实现，零代码拷贝。本注册表刻意**不进**
core/calculators 注册表（#231 五表连动豁免）：BudgetRegistry 在本模块
自持独立命名空间，条目名带 "budget." 前缀自明。

首批 3 源条目与物理口径：
- budget.grid_discretization：网格离散项（#313 两点线性分解 dev=a*BASE+b）
- budget.port_reference：端口基项（#280 伪反射 |Gamma|=(Z-50)/(Z+50) 口径）
- budget.tolerance：公差项（DP-7 公差剖面思路；预算面用线性传播
  u = sum |df/dp_i| * tol_i 的简化接口）

Ph4 GWINC 扩容条目（2026-09-26 批）：
- budget.calibration_residual：校准残差项（实测-预测残差序列→RMS 谱；
  GWINC residual"指向调查"语义升格为源条目）
- budget.tolerance_mc：公差 MC 谱项（逐参数 tol×sensitivity 单变量扫描
  谱 → 不相关参数 RSS 合成；与 tolerance 的最坏情况线性和互为上下界）
- budget.surrogate_error：代理误差项（held-out 误差谱；支持 coverage
  覆盖因子保守电平）

量子噪声扩容条目（2026-09-27 批，GWINC 移植闭式，全部幅值谱 ASD 口径）：
- budget.radiation_pressure：辐射压 vs SQL（单自由质量镜；SQL 取 gwinc
  StandardQuantumLimit 逐字式，S_RP 由光子泊松统计直推；干涉仪级增强
  刻意不入条目——作用域注记见类 docstring）
- budget.thermorefractive：热折射率（单热池 FDT 洛伦兹谱 × alpha_eff·L
  光程耦合；Braginsky-Gorodetsky-Vyatchanin TRN 族）
- budget.coating_brownian：涂覆 Brownian（Harry et al. 2002 Eq. 22 逐字
  闭式，含 phi_par/phi_perp 各向异性项；Eq. 23 等材料极限做回收钉）
- budget.seismic_folded：seismic 折叠谱（Peterson 1993 NLNM 表格模型或
  幂律地面谱 × 阻尼谐振子级联悬挂折叠，低频 SEO 口径）

叠加语义：不相关源功率域正交叠加 sum |H_i|^2 开方（GWINC 惯例，
"quadratic" mode 缺省）；相干源先线性叠加再入正交总账（"coherent" mode，
per-item mode 字段声明）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, cast

import numpy as np

MODE_QUADRATIC = "quadratic"  # 不相关源：功率域正交叠加 sum |H_i|^2
MODE_COHERENT = "coherent"  # 相干源：先线性叠加 sum H_i，再入正交总账


# ─── 条目基类 ────────────────────────────────────────────────────────────────
class BudgetItem(ABC):
    """误差源条目基类（GWINC BudgetItem 机制借镜+自实现）。

    一个条目 = 确定性贡献函数 calc(f, context) -> 贡献谱（与 f 同形，
    幅值口径，可复数）+ 条目名/描述 + 叠加 mode：
    - "quadratic"（缺省）：不相关源，功率域正交叠加
    - "coherent"：相干源，线性叠加

    条目名/描述：子类声明类级 name（"budget." 前缀自明独立命名空间）供
    注册表登记；构造参数 name/description 做实例级覆写（同类多实例入
    同一账本时区分命名）。实例属性覆写类属性是常规 shadow 语义。
    """

    mode: ClassVar[str] = MODE_QUADRATIC

    # 类级 name 缺省空串：子类以 "budget.*" 条目名覆写（注册表按类级 name
    # 登记，mypy 类对象访问合法）；实例 __init__ 可再做实例级覆写，原
    # getattr(type(self), "name", "") 口径不变（缺省同为空串）。
    name: str = ""

    def __init__(
        self,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        self.name = name if name is not None else str(getattr(type(self), "name", ""))
        self.description = description if description is not None else str(getattr(type(self), "description", ""))
        if not self.name:
            raise ValueError("BudgetItem 条目名不能为空（类级 name 或构造参数 name 必须有其一）")

    @abstractmethod
    def calc(self, f: np.ndarray, context: Mapping[str, Any] | None = None) -> np.ndarray:
        """返回该源贡献谱（与 f 同形的幅值谱；可复数）。"""



# ─── 自持注册表（仿 EMSolverRegistry 惯例；不进 calculators，#231 豁免） ────
class BudgetRegistry:
    """误差源条目注册表（本模块自持，"budget.*" 键独立命名空间）。

    重名注册显式报错、未注册 create KeyError 并列可用名、lookup 不抛错
    返回 None——口径与 CalculatorRegistry/EMSolverRegistry 一致。
    """

    def __init__(self) -> None:
        self._items: dict[str, type[BudgetItem]] = {}

    def register(self, item_cls: type[BudgetItem]) -> type[BudgetItem]:
        """注册条目类（按类级 name；重名拒绝）。返回原类以便装饰器用法。"""
        cls_name = item_cls.name
        if not cls_name:
            raise ValueError("注册条目类必须有类级 name")
        if cls_name in self._items:
            raise ValueError(f"误差源条目重名注册: {cls_name}")
        self._items[cls_name] = item_cls
        return item_cls

    def create(self, name: str, **kwargs: Any) -> BudgetItem:
        """按注册名实例化条目（kwargs 透传构造器）。"""
        item_cls = self._items.get(name)
        if item_cls is None:
            raise KeyError(f"未注册的误差源条目: {name}（可用: {sorted(self._items)}）")
        return item_cls(**kwargs)

    def lookup(self, name: str) -> type[BudgetItem] | None:
        """按名返回条目类；未注册返回 None（不抛错）。"""
        return self._items.get(name)

    def list_names(self) -> list[str]:
        return sorted(self._items)

    def is_registered(self, name: str) -> bool:
        return name in self._items


# ─── 账本轨迹与求值 ──────────────────────────────────────────────────────────
@dataclass(eq=False)
class BudgetTrace:
    """一次误差预算求值的轨迹（f + 各源贡献 + 合成总量 + 残差）。

    residual = measured_total - total（实测差减去账本和）——未解释残差
    是调查靶向行（GWINC 语义）：残差显著大于零说明有未建模误差源。
    modes 逐条目记录叠加方式，保证 total 可复算。
    """

    f: np.ndarray
    contributions: dict[str, np.ndarray]
    modes: dict[str, str]
    total: np.ndarray
    residual: np.ndarray | None = field(default=None)

    def quadratic_sum(self) -> np.ndarray:
        """正交叠加分量 sum |H_i|^2 开方（仅 quadratic mode 条目）。"""
        power = np.zeros(np.asarray(self.f).shape, dtype=float)
        for key, contrib in self.contributions.items():
            if self.modes.get(key, MODE_QUADRATIC) == MODE_QUADRATIC:
                power = power + np.abs(np.asarray(contrib)) ** 2
        return np.sqrt(power)


def _combine_contributions(
    contributions: dict[str, np.ndarray],
    modes: dict[str, str],
) -> np.ndarray:
    """合成总谱：quadratic 条目功率域叠加，coherent 条目先线性叠加。

    total = sqrt( sum_quadratic |H_i|^2 + |sum_coherent H_j|^2 )。
    """
    keys = list(contributions.keys())
    if not keys:
        raise ValueError("误差源贡献为空：至少需要一个 BudgetItem")
    shape = np.asarray(contributions[keys[0]]).shape
    power = np.zeros(shape, dtype=float)
    coherent = np.zeros(shape, dtype=complex)
    for key in keys:
        arr = np.asarray(contributions[key])
        if modes.get(key, MODE_QUADRATIC) == MODE_COHERENT:
            coherent = coherent + arr.astype(complex)
        else:
            power = power + np.abs(arr) ** 2
    out: np.ndarray = np.sqrt(power + np.abs(coherent) ** 2)
    return out


def budget_evaluate(
    f: np.ndarray,
    items: Sequence[BudgetItem],
    measured_total: np.ndarray | None = None,
    context: Mapping[str, Any] | None = None,
) -> BudgetTrace:
    """跑全部条目 -> 按各自 mode 叠加 -> 有实测总量则算残差。

    measured_total 与 f 同形（幅值谱口径）；residual = measured - total，
    未提供 measured_total 时 residual 为 None。
    """
    freq = np.asarray(f, dtype=float)
    contributions: dict[str, np.ndarray] = {}
    modes: dict[str, str] = {}
    for item in items:
        if item.name in contributions:
            raise ValueError(f"误差源条目重名（实例级 name 需唯一）: {item.name}")
        contrib = np.asarray(item.calc(freq, context))
        if contrib.shape != freq.shape:
            raise ValueError(
                f"条目 {item.name} 贡献谱形状 {contrib.shape} 与频率轴 {freq.shape} 不一致"
            )
        contributions[item.name] = contrib
        modes[item.name] = getattr(item, "mode", MODE_QUADRATIC)
    total = _combine_contributions(contributions, modes)
    residual: np.ndarray | None = None
    if measured_total is not None:
        measured = np.asarray(measured_total, dtype=float)
        if measured.shape != freq.shape:
            raise ValueError(
                f"measured_total 形状 {measured.shape} 与频率轴 {freq.shape} 不一致"
            )
        residual = measured - total
    return BudgetTrace(f=freq, contributions=contributions, modes=modes, total=total, residual=residual)


# ─── 报告面（纯文本 + best-effort 堆叠图）────────────────────────────────────
def _fmt_num(value: float) -> str:
    """数值格式化（#119：条件格式符禁——先格式化再拼；0.0 是合法值）。"""
    if value != value:  # NaN（判缺失不用 or——#364④）
        return "nan"
    return f"{value:.6g}"


def budget_report(trace: BudgetTrace, max_points: int = 5) -> str:
    """文本报告：各源在采样频点的幅值与功率占比表 + total + 残差行。

    纯文本 ASCII 表格（不用 matplotlib，避免 CJK 字形坑）。占比分母
    = sum |H_i|^2（coherent 交叉项不进分母，有相干条目时显式注记）。
    频率轴单位沿用调用方口径（报告不假设单位）。
    """
    freq = np.asarray(trace.f, dtype=float)
    n_points = int(freq.size)
    if n_points == 0:
        raise ValueError("BudgetTrace.f 为空，无法出报告")
    idx = np.unique(np.linspace(0, n_points - 1, min(max_points, n_points)).astype(int))
    names = list(trace.contributions.keys())
    col_heads = ["@" + _fmt_num(float(freq[i])) for i in idx]
    name_w = max([len(nm) for nm in names] + [len("source"), len("total (combined)")]) + 2
    col_w = max([len(h) for h in col_heads] + [12])
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("Error budget report (M-1 GWINC-style noise budget ledger)")
    lines.append("=" * 64)
    lines.append(f"f-axis: {n_points} points, sample: {col_heads[0]} .. {col_heads[-1]} (caller units)")
    header = "source".ljust(name_w) + "".join(h.ljust(col_w) for h in col_heads)

    lines.append("")
    lines.append("Amplitude at sample frequencies:")
    lines.append(header)
    for nm in names:
        contrib = np.asarray(trace.contributions[nm])
        cells = [_fmt_num(float(np.abs(contrib[i]))) for i in idx]
        lines.append(("  " + nm).ljust(name_w) + "".join(c.ljust(col_w) for c in cells))

    denom = np.zeros(n_points, dtype=float)
    for nm in names:
        denom = denom + np.abs(np.asarray(trace.contributions[nm])) ** 2
    lines.append("")
    lines.append("Power share [%] (denominator = sum |H_i|^2; coherent cross terms excluded):")
    lines.append(header)
    for nm in names:
        contrib = np.asarray(trace.contributions[nm])
        cells = []
        for i in idx:
            if denom[i] > 0.0:
                cells.append(_fmt_num(100.0 * float(np.abs(contrib[i]) ** 2 / denom[i])))
            else:
                cells.append("n/a")
        lines.append(("  " + nm).ljust(name_w) + "".join(c.ljust(col_w) for c in cells))

    if any(m == MODE_COHERENT for m in trace.modes.values()):
        lines.append("")
        lines.append("note: coherent-mode sources add linearly before quadrature.")

    lines.append("")
    total_cells = [_fmt_num(float(np.asarray(trace.total)[i])) for i in idx]
    lines.append("total (combined)".ljust(name_w) + "".join(c.ljust(col_w) for c in total_cells))

    lines.append("")
    if trace.residual is not None:
        abs_r = np.abs(np.asarray(trace.residual))
        i_max = int(np.argmax(abs_r))
        lines.append(
            "residual (measured - total): "
            f"mean_abs={_fmt_num(float(np.mean(abs_r)))}, "
            f"max_abs={_fmt_num(float(abs_r[i_max]))} @f={_fmt_num(float(freq[i_max]))}"
        )
    else:
        lines.append("residual: n/a (measured_total not provided)")
    return "\n".join(lines)


def budget_report_stacked(trace: BudgetTrace, path: str | Path) -> bool:
    """误差预算堆叠图（功率域 |H|^2 堆叠 + total/residual 参考线）。

    观测面 best-effort（#105：画图失败不抛异常，返回 False 不阻塞主路径）。
    matplotlib 必须 use("Agg") 先于 pyplot 导入；标签一律取条目名且必须
    保持 ASCII（内置条目名全 ASCII；自定义条目名带中文会渲染成豆腐块）。
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        freq = np.asarray(trace.f, dtype=float)
        names = list(trace.contributions.keys())
        fig, ax = plt.subplots()
        if names:
            powers = [np.abs(np.asarray(trace.contributions[nm])) ** 2 for nm in names]
            ax.stackplot(freq, powers, labels=names)
        ax.plot(freq, np.asarray(trace.total) ** 2, color="black", label="total (power)")
        if trace.residual is not None:
            ax.plot(freq, np.abs(np.asarray(trace.residual)) ** 2, color="red", label="residual (power)")
        ax.set_xlabel("frequency")
        ax.set_ylabel("power")
        ax.set_title("error budget (power contributions)")
        if names or trace.residual is not None:
            ax.legend(loc="best")
        fig.savefig(str(path))
        plt.close(fig)
        return True
    except Exception as exc:  # 兜 matplotlib 缺失/Agg 后端/写盘失败：观测面 best-effort（#105），失败语义由 False 承载，不阻塞主报告路径
        del exc  # 返回 bool 无 reason 承载面（L0 纯函数层无日志），仅保留 as exc 归类
        return False


# ─── 首批 3 源条目 ────────────────────────────────────────────────────────────
class GridDiscretizationItem(BudgetItem):
    """网格离散误差项（#313 两点线性分解口径）。

    物理口径（#313）：网格离散误差做两点线性分解
    dev = a*BASE + b——a 是一阶收敛斜率，b 是与 BASE 无关的地板项（z 向
    substrate_cells 分层是 ZL 与耦合度共同的分辨限制项，面内一阶外推会
    系统性低估残差）。电平来源三选一：
    - a, b, base：常数谱，电平 dev = a*base + b
    - two_point=(dev1, base1, dev2, base2) + base：两点拟合 a、b 后按
      base 取当前电平（仍需显式 base）
    - freq_coeffs=[c0, c1, ...]：f 依赖谱 dev(f) = np.polyval(freq_coeffs, f)

    机制出处：LIGO GWINC（PyPI gwinc 0.6.2，Unlicense）BudgetItem 机制
    借镜+自实现，零代码拷贝。
    """

    name = "budget.grid_discretization"
    description = "grid discretization error (two-point dev=a*BASE+b, #313)"

    def __init__(
        self,
        a: float | None = None,
        b: float | None = None,
        base: float | None = None,
        two_point: Sequence[float] | None = None,
        freq_coeffs: Sequence[float] | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.a = None if a is None else float(a)
        self.b = None if b is None else float(b)
        self.base = None if base is None else float(base)
        self.freq_coeffs = None if freq_coeffs is None else np.asarray(freq_coeffs, dtype=float)
        if two_point is not None:
            tp = [float(v) for v in two_point]
            if len(tp) != 4:
                raise ValueError("two_point 需为 (dev1, base1, dev2, base2) 四元组")
            dev1, base1, dev2, base2 = tp
            if base2 == base1:
                raise ValueError("two_point 两点 BASE 相同，无法拟合斜率 a（#313 两点分解）")
            self.a = (dev2 - dev1) / (base2 - base1)
            self.b = dev1 - self.a * base1
        if self.freq_coeffs is None and (self.a is None or self.b is None or self.base is None):
            raise ValueError(
                "GridDiscretizationItem 电平来源不足：需 (a, b, base) / two_point+base / freq_coeffs 之一"
            )

    def calc(self, f: np.ndarray, context: Mapping[str, Any] | None = None) -> np.ndarray:
        freq = np.asarray(f, dtype=float)
        if self.freq_coeffs is not None:
            return np.polyval(self.freq_coeffs, freq)
        # a/b/base 非 None 已在 __init__ 校验（cast=恒等，types only）
        a = cast("float", self.a)
        b = cast("float", self.b)
        base = cast("float", self.base)
        level = a * base + b
        return np.full(freq.shape, level, dtype=float)


class PortReferenceItem(BudgetItem):
    """端口基参考失配项（#280 伪反射口径）。

    物理口径（#280）：CalcPort(ref=50) 在引擎自算
    线阻抗 ZL != 50 时引入伪反射 Gamma=(Z-Z0)/(Z+Z0)（实测 ZL=45.7 Ohm
    即 -8.6% 偏差时 Gamma 约 -0.045），归一只能修伪反射不改耦合度。
    预算面以 |Gamma| 常数谱计入：z0_deviance = Z - Z0（引擎线阻抗对参考
    阻抗的偏差），z0_ref 缺省 50 Ohm。

    机制出处：LIGO GWINC（PyPI gwinc 0.6.2，Unlicense）BudgetItem 机制
    借镜+自实现，零代码拷贝。
    """

    name = "budget.port_reference"
    description = "port reference mismatch |Gamma| constant spectrum (#280)"

    def __init__(
        self,
        z0_deviance: float,
        z0_ref: float = 50.0,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.z0_deviance = float(z0_deviance)
        self.z0_ref = float(z0_ref)

    def gamma(self) -> float:
        """|Gamma| = |(Z-Z0)/(Z+Z0)|，其中 Z = z0_ref + z0_deviance。"""
        denom = 2.0 * self.z0_ref + self.z0_deviance
        if denom == 0.0:
            raise ValueError("端口参考失配分母为 0（Z+Z0=0），无法换算 |Gamma|")
        return abs(self.z0_deviance / denom)

    def calc(self, f: np.ndarray, context: Mapping[str, Any] | None = None) -> np.ndarray:
        freq = np.asarray(f, dtype=float)
        return np.full(freq.shape, self.gamma(), dtype=float)


class ToleranceItem(BudgetItem):
    """公差项（DP-7 公差剖面思路的预算面简化接口）。

    物理口径（DP-7，剖面面在 core/fab_check.py 的 fab 能力剖面）：预算面
    用线性传播 u = sum |df/dp_i| * tol_i（最坏情况线性和，非 RSS）。
    输入二选一：
    - tolerances + sensitivities：逐参数字典 {参数名: tol_i} / {参数名:
      |df/dp_i|}，合成电平 u 为常数谱
    - contribution：直接给贡献谱（标量 -> 常数谱；数组 -> f 依赖谱，
      长度须与 f 一致；实幅值口径）

    机制出处：LIGO GWINC（PyPI gwinc 0.6.2，Unlicense）BudgetItem 机制
    借镜+自实现，零代码拷贝。
    """

    name = "budget.tolerance"
    description = "manufacturing tolerance (linear propagation u=sum|df/dp_i*tol_i|, DP-7)"

    def __init__(
        self,
        tolerances: Mapping[str, float] | None = None,
        sensitivities: Mapping[str, float] | None = None,
        contribution: float | np.ndarray | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.tolerances = dict(tolerances) if tolerances is not None else None
        self.sensitivities = dict(sensitivities) if sensitivities is not None else None
        self.contribution = None if contribution is None else np.asarray(contribution, dtype=float)
        self.level: float | None = None
        if self.contribution is None:
            if self.tolerances is None or self.sensitivities is None:
                raise ValueError("ToleranceItem 需要 (tolerances + sensitivities) 或 contribution 之一")
            missing = [key for key in self.tolerances if key not in self.sensitivities]
            if missing:
                raise ValueError(f"sensitivities 缺少参数的敏感度: {missing}")
            self.level = float(sum(abs(self.sensitivities[key] * tol) for key, tol in self.tolerances.items()))

    def calc(self, f: np.ndarray, context: Mapping[str, Any] | None = None) -> np.ndarray:
        freq = np.asarray(f, dtype=float)
        if self.contribution is not None:
            if self.contribution.shape != freq.shape:
                raise ValueError(
                    f"contribution 形状 {self.contribution.shape} 与频率轴 {freq.shape} 不一致"
                )
            return self.contribution
        return np.full(freq.shape, self.level, dtype=float)


# ─── Ph4 GWINC 扩容条目（校准残差 / 公差 MC 谱 / 代理误差）───────────────────
class CalibrationResidualItem(BudgetItem):
    """校准残差项（实测-预测残差序列 → RMS 谱）。

    物理口径：校准/对齐后的实测响应与模型预测之差 residual(f) =
    measured(f) − predicted(f)——GWINC 的"未解释残差指向下一步调查"语义
    升格为独立误差源条目（残差本身即该源的贡献谱，不再留给 residual 行）。
    输入二选一：
    - residual：逐频残差幅值谱（数组，长度须与 f 一致；复残差取 |·| 归
      幅值口径）；实测-预测的逐频点差直接入账
    - residual_rms：残差序列的 RMS 电平（常数谱；残差以时间序列/散点形
      态给出无频轴对位时的简化接口）

    机制出处：LIGO GWINC（PyPI gwinc 0.6.2，Unlicense）BudgetItem 机制
    借镜+自实现，零代码拷贝。
    """

    name = "budget.calibration_residual"
    description = "calibration residual (measured-predicted) RMS spectrum"

    def __init__(
        self,
        residual: float | np.ndarray | Sequence[float] | None = None,
        residual_rms: float | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.residual = None
        if residual is not None:
            arr = np.asarray(
                [abs(complex(v)) if isinstance(v, complex) else v
                 for v in np.atleast_1d(residual)], dtype=float)
            self.residual = arr if arr.size > 1 else arr.reshape(())
        self.residual_rms = None if residual_rms is None else float(residual_rms)
        if self.residual is None and self.residual_rms is None:
            raise ValueError(
                "CalibrationResidualItem 需 residual（逐频残差谱）或 "
                "residual_rms（RMS 常数电平）之一")
        if self.residual is not None and self.residual.ndim > 1:
            raise ValueError(
                f"residual 须为一维谱（与 f 同形），得到 shape {self.residual.shape}")
        if self.residual_rms is not None and self.residual_rms < 0.0:
            raise ValueError(f"residual_rms 须 >= 0，得到 {self.residual_rms}")

    def rms_level(self) -> float:
        """残差电平的标量摘要（逐频谱取 RMS；常数谱取自身）。"""
        if self.residual is not None:
            arr = np.atleast_1d(self.residual)
            return float(np.sqrt(np.mean(arr**2)))
        # residual 与 residual_rms 二选一已在 __init__ 校验（cast=恒等）
        return float(cast("float", self.residual_rms))

    def calc(self, f: np.ndarray, context: Mapping[str, Any] | None = None) -> np.ndarray:
        freq = np.asarray(f, dtype=float)
        if self.residual is None:
            # residual 与 residual_rms 二选一已在 __init__ 校验（cast=恒等）
            return np.full(freq.shape, float(cast("float", self.residual_rms)), dtype=float)
        arr = np.broadcast_to(self.residual, freq.shape) \
            if self.residual.ndim == 0 else self.residual
        if arr.shape != freq.shape:
            raise ValueError(
                f"residual 谱长度 {arr.shape} 与频率轴 {freq.shape} 不一致")
        return np.asarray(arr, dtype=float)


class ToleranceMcItem(BudgetItem):
    """公差蒙特卡洛谱项（逐参数 tol×sensitivity 单变量扫描谱 → RSS 合成）。

    与 :class:`ToleranceItem`（最坏情况线性传播 u = Σ|s_i·t_i|）的口径差：
    本条目按不相关参数**功率域 RSS** 合成 sqrt(Σ_i |s_i(f)·t_i|²)——MC/
    线性扰动扫描给的是逐参数独立贡献谱，参数间不相关（GWINC quadratic
    惯例），线性求和会高估。逐参数敏感度支持标量（常数谱）或逐频谱（单
    变量扫描输出，长度须与 f 一致）。

    机制出处：LIGO GWINC（PyPI gwinc 0.6.2，Unlicense）BudgetItem 机制
    借镜+自实现，零代码拷贝。
    """

    name = "budget.tolerance_mc"
    description = "tolerance MC (per-parameter tol*sensitivity RSS synthesis)"

    def __init__(
        self,
        tolerances: Mapping[str, float],
        sensitivities: Mapping[str, float | Sequence[float] | np.ndarray],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.tolerances = {k: float(v) for k, v in dict(tolerances).items()}
        self.sensitivities: dict[str, float | np.ndarray] = {}
        for key, value in dict(sensitivities).items():
            self.sensitivities[key] = (
                float(value) if np.isscalar(value) and not isinstance(value, bool)
                else np.asarray(value, dtype=float))
        missing = [k for k in self.tolerances if k not in self.sensitivities]
        if missing:
            raise ValueError(f"sensitivities 缺少参数的敏感度: {missing}")
        unused = [k for k in self.sensitivities if k not in self.tolerances]
        if unused:
            raise ValueError(f"sensitivities 含未给公差的参数: {unused}")
        for key, sens in self.sensitivities.items():
            if isinstance(sens, np.ndarray) and sens.ndim > 1:
                raise ValueError(f"敏感度 {key!r} 须为标量或一维谱")
        if not self.tolerances:
            raise ValueError("ToleranceMcItem 至少需要一个参数（tolerances 为空）")

    def per_parameter(self, f: np.ndarray) -> dict[str, np.ndarray]:
        """逐参数单变量贡献谱 |s_i(f)·t_i|（诊断面：看哪个参数主导）。"""
        freq = np.asarray(f, dtype=float)
        out: dict[str, np.ndarray] = {}
        for key, tol in self.tolerances.items():
            sens = self.sensitivities[key]
            if np.isscalar(sens) or isinstance(sens, float):
                spec: np.ndarray = np.full(freq.shape, float(cast("float", sens)), dtype=float)
            else:
                spec = sens
            spec = np.asarray(spec, dtype=float)
            if spec.shape != freq.shape:
                raise ValueError(
                    f"敏感度 {key!r} 谱长度 {spec.shape} 与频率轴 "
                    f"{freq.shape} 不一致")
            out[key] = np.abs(spec * tol)
        return out

    def calc(self, f: np.ndarray, context: Mapping[str, Any] | None = None) -> np.ndarray:
        per = self.per_parameter(f)
        power = np.zeros(np.asarray(f, dtype=float).shape, dtype=float)
        for spec in per.values():
            power = power + spec**2
        return np.sqrt(power)


class SurrogateErrorItem(BudgetItem):
    """代理模型误差项（held-out 误差谱）。

    物理口径：代理模型（GP/森林等）在 held-out 验证集上的 |误差| 谱——
    代理驱动优化/采样的预测不确定度的实测下界（不是 GP 后验 σ 的先验
    面）。输入二选一：
    - heldout_errors：逐频 held-out 误差幅值谱（长度须与 f 一致；散点无
      频轴对位时给常数谱或 RMS）
    - error_rms：held-out 误差 RMS（常数谱）
    - coverage：覆盖因子（缺省 1.0；k=2 即 95% 置信面保守电平），作用在
      最终谱上

    机制出处：LIGO GWINC（PyPI gwinc 0.6.2，Unlicense）BudgetItem 机制
    借镜+自实现，零代码拷贝。
    """

    name = "budget.surrogate_error"
    description = "surrogate held-out error spectrum (proxy accuracy floor)"

    def __init__(
        self,
        heldout_errors: float | Sequence[float] | np.ndarray | None = None,
        error_rms: float | None = None,
        coverage: float = 1.0,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.heldout_errors = None
        if heldout_errors is not None:
            if isinstance(heldout_errors, bool):
                raise ValueError("heldout_errors 不接受 bool（数值入参显式拒收）")
            arr = np.asarray(heldout_errors, dtype=float)
            self.heldout_errors = np.abs(arr) if arr.ndim else float(np.abs(arr))
        self.error_rms = None if error_rms is None else float(error_rms)
        self.coverage = float(coverage)
        if self.heldout_errors is None and self.error_rms is None:
            raise ValueError(
                "SurrogateErrorItem 需 heldout_errors（逐频误差谱）或 "
                "error_rms（RMS 常数电平）之一")
        if self.heldout_errors is not None and isinstance(self.heldout_errors, np.ndarray) \
                and self.heldout_errors.ndim > 1:
            raise ValueError(
                f"heldout_errors 须为一维谱，得到 shape {self.heldout_errors.shape}")
        if self.error_rms is not None and self.error_rms < 0.0:
            raise ValueError(f"error_rms 须 >= 0，得到 {self.error_rms}")
        if not self.coverage > 0.0:
            raise ValueError(f"coverage 须 > 0，得到 {self.coverage}")

    def calc(self, f: np.ndarray, context: Mapping[str, Any] | None = None) -> np.ndarray:
        freq = np.asarray(f, dtype=float)
        if self.heldout_errors is None:
            # heldout_errors 与 error_rms 二选一已在 __init__ 校验（cast=恒等）
            rms = cast("float", self.error_rms)
            return np.full(freq.shape, rms * self.coverage, dtype=float)
        arr = self.heldout_errors
        if not isinstance(arr, np.ndarray):
            return np.full(freq.shape, float(arr) * self.coverage, dtype=float)
        if arr.shape != freq.shape:
            raise ValueError(
                f"heldout_errors 谱长度 {arr.shape} 与频率轴 {freq.shape} 不一致")
        return arr * self.coverage


# ─── 量子噪声扩容条目（2026-09-27 批；GWINC 移植闭式，幅值谱 ASD 口径）───────
# 物理常量：SI 2019 精确定义值（CODATA 2018 口径，与 core/aging.py、
# core/adc_budget.py 的常量取值惯例一致）。
HBAR_J_S = 1.054_571_817e-34  # 约化普朗克常量 [J*s]（h/(2*pi)，h=6.62607015e-34 精确）
C_LIGHT_M_S = 299792458.0  # 真空光速 [m/s]（SI 精确定义）
K_B_J_PER_K = 1.380649e-23  # 玻尔兹曼常量 [J/K]（SI 精确定义）


def _num_param(value: Any, label: str, positive: bool = False) -> float:
    """数值入参收敛：显式拒收 bool（df7 ⑯ 惯例）+ NaN/inf 拒收。

    positive=True 要求严格 > 0；否则要求 >= 0（噪声电平/功率可为 0 不可
    为负）。判缺失一律 is not None（#364④），不用 or 惯语。
    """
    if isinstance(value, bool):
        raise ValueError(f"{label} 不接受 bool（数值入参显式拒收）")
    v = float(value)
    if not np.isfinite(v):
        raise ValueError(f"{label} 须为有限数值，得到 {v}")
    if positive and v <= 0.0:
        raise ValueError(f"{label} 须 > 0，得到 {v}")
    if not positive and v < 0.0:
        raise ValueError(f"{label} 须 >= 0，得到 {v}")
    return v


class RadiationPressureItem(BudgetItem):
    """辐射压噪声条目（SQL 口径，单自由质量镜，KLMTV 族闭式）。

    物理口径（单镜自由质量、正入射、镜上功率 P、光波长 lambda0）：
    - SQL 位移谱密度 S_x^SQL(f) = 8*hbar/(m*(2*pi*f)^2) [m^2/Hz]——LIGO
      GWINC StandardQuantumLimit（gwinc/noise/quantum.py）逐字式，即
      Buonanno & Chen PRD 64, 042006 (2001) Eq. 2.12 的位移口径（去 L^2）。
    - 辐射压力谱 S_F = 8*hbar*omega0*P/c^2 [N^2/Hz]——光子泊松涨落直推：
      光子流 R = P/(hbar*omega0) 的单边速率噪声 2R，每光子动量转移
      2*hbar*k0（k0 = omega0/c），S_F = 2R*(2*hbar*k0)^2；自由质量响应
      |chi| = 1/(m*Omega^2) 给
      S_x^RP(f) = 8*hbar*omega0*P/(c^2*m^2*(2*pi*f)^4)。
    - 交叉恒等式：P = P_SQL(f) = c^2*m*(2*pi*f)^2/omega0 时 S_RP = S_SQL
      （合成回收测试钉；sql_power() 给出该交叉功率）。

    作用域注记：以上是**单镜**口径。干涉仪级增强（双臂 ×2、臂腔滤波与
    信号提取增益，KLMTV 的 kappa/2K 约定：Kimble, Levin, Matsko, Thorne &
    Vyatchanin, PRD 65, 022002 (2001)；gwinc shotrad 的 sqrt(2K)/h_SQL 噪声
    注入）是模型特定的，刻意不进本条目——干涉仪级预算用 gwinc 全量子模型。

    calc 返回幅值谱 ASD [m/sqrt(Hz)]（与账本叠加约定一致）。
    """

    name = "budget.radiation_pressure"
    description = "radiation pressure noise vs SQL (single free mirror, KLMTV family)"

    def __init__(
        self,
        mass_kg: float,
        power_w: float,
        wavelength_m: float,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.mass_kg = _num_param(mass_kg, "mass_kg", positive=True)
        self.power_w = _num_param(power_w, "power_w")
        self.wavelength_m = _num_param(wavelength_m, "wavelength_m", positive=True)

    def _omega0(self) -> float:
        return 2.0 * np.pi * C_LIGHT_M_S / self.wavelength_m

    def sql_psd(self, f: np.ndarray) -> np.ndarray:
        """SQL 位移谱密度 8*hbar/(m*Omega^2) [m^2/Hz]。"""
        omega = 2.0 * np.pi * np.asarray(f, dtype=float)
        return 8.0 * HBAR_J_S / (self.mass_kg * omega**2)

    def rp_psd(self, f: np.ndarray) -> np.ndarray:
        """辐射压位移谱密度 [m^2/Hz]（单镜自由质量，见类 docstring）。"""
        omega = 2.0 * np.pi * np.asarray(f, dtype=float)
        s_force = 8.0 * HBAR_J_S * self._omega0() * self.power_w / C_LIGHT_M_S**2
        return s_force / (self.mass_kg**2 * omega**4)

    def sql_power(self, f: np.ndarray) -> np.ndarray:
        """交叉功率 P_SQL(f) = c^2*m*Omega^2/omega0（S_RP = S_SQL 的解，[W]）。"""
        omega = 2.0 * np.pi * np.asarray(f, dtype=float)
        return C_LIGHT_M_S**2 * self.mass_kg * omega**2 / self._omega0()

    def calc(self, f: np.ndarray, context: Mapping[str, Any] | None = None) -> np.ndarray:
        out: np.ndarray = np.sqrt(self.rp_psd(f))
        return out


class ThermorefractiveItem(BudgetItem):
    """热折射率噪声条目（单热池 FDT 涨落 × 折射率/光程耦合）。

    物理口径（单弛豫热池，Ornstein-Uhlenbeck 型温度涨落谱）：
    - S_T(f) = kB*T^2/G_th / (1 + (2*pi*f*tau_th)^2) [K^2/Hz]，
      tau_th = C_th/G_th——热导 G_th [W/K] 对热容 C_th [J/K] 的单池热交换
      涨落耗散定理（FDT）单弛豫极限。TRN 机制出处：Braginsky, Gorodetsky
      & Vyatchanin, Phys. Lett. A 264, 1 (1999)（热折射率噪声原始文献）；
      有限体精确式与逐阶系数（Gorodetsky 口径）见 arXiv:cond-mat/0402650
      （gwinc substrate_thermorefractive 的 exact/adiabatic 两档同源）。
    - 折射率耦合：等效光程 L_opt 上的等效热光系数 alpha_eff（dn/dT 或
      等效 CTE，量纲 1/K，可负）→ 贡献幅值谱 = |alpha_eff| * L_opt *
      sqrt(S_T(f))。

    calc 返回幅值谱（ASD 口径，单位 = |alpha_eff|*L_opt 的单位/sqrt(Hz)）。
    """

    name = "budget.thermorefractive"
    description = "thermorefractive noise (single thermal pool, Braginsky-Gorodetsky-Vyatchanin family)"

    def __init__(
        self,
        g_th_w_per_k: float,
        c_th_j_per_k: float,
        temp_k: float,
        alpha_eff: float = 1.0,
        l_opt: float = 1.0,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.g_th_w_per_k = _num_param(g_th_w_per_k, "g_th_w_per_k", positive=True)
        self.c_th_j_per_k = _num_param(c_th_j_per_k, "c_th_j_per_k", positive=True)
        self.temp_k = _num_param(temp_k, "temp_k", positive=True)
        if isinstance(alpha_eff, bool):
            raise ValueError("alpha_eff 不接受 bool（数值入参显式拒收）")
        self.alpha_eff = float(alpha_eff)
        self.l_opt = _num_param(l_opt, "l_opt", positive=True)

    def tau_th(self) -> float:
        """单池热时间常数 tau_th = C_th/G_th [s]。"""
        return self.c_th_j_per_k / self.g_th_w_per_k

    def temp_psd(self, f: np.ndarray) -> np.ndarray:
        """温度涨落谱密度 S_T(f) [K^2/Hz]（f=0 取 DC 电平 kB*T^2/G_th）。"""
        omega = 2.0 * np.pi * np.asarray(f, dtype=float)
        tau = self.tau_th()
        dc_level = K_B_J_PER_K * self.temp_k**2 / self.g_th_w_per_k
        return dc_level / (1.0 + (omega * tau) ** 2)

    def calc(self, f: np.ndarray, context: Mapping[str, Any] | None = None) -> np.ndarray:
        out: np.ndarray = abs(self.alpha_eff) * self.l_opt * np.sqrt(self.temp_psd(f))
        return out


class CoatingBrownianItem(BudgetItem):
    """涂覆 Brownian 噪声条目（Harry et al. 2002 Eq. 22 逐字闭式）。

    物理口径（Levin formalism，半无限基底 + 薄涂覆，高斯光斑半径 w）：
        S_x(f) = 2*kB*T/(pi^(3/2)*f) * (1-sigma_s^2)/(w*Y_s) *
          { phi_sub + (d/w)/(pi*sqrt(pi)) *
            [ Y_c^2*(1+sigma_s)^2*(1-2*sigma_s)^2*phi_par
            + Y_s*Y_c*sigma_c*(1+sigma_s)*(1+sigma_c)*(1-2*sigma_s)*(phi_par-phi_perp)
            + Y_s^2*(1+sigma_c)^2*(1-2*sigma_c)*phi_perp ]
            / (Y_s*Y_c*(1-sigma_c^2)*(1-sigma_s^2)) }
    其中 Y_s/sigma_s 为基底、Y_c/sigma_c 为涂覆等效介质的杨氏模量/泊松比，
    d 为涂覆总厚，phi_par/phi_perp 为平行/垂直应变损耗角（phi_perp 缺省
    =phi_par），phi_sub 为基底损耗角（可 0）。注意第三项是 (1-2*sigma_c)
    一次幂（PDF 逐字）——论文自述的 Eq. 23 等材料极限（Y_c=Y_s、
    sigma_c=sigma_s、phi_par=phi_perp 时括号 → (2/sqrt(pi))*(1-2*sigma_s)/
    (1-sigma_s)*(d/w)*phi_par）只有在该幂次下成立，合成回收测试钉此。

    出处：G. M. Harry et al., "Thermal noise in interferometric
    gravitational wave detectors due to dielectric optical coatings",
    Class. Quantum Grav. 19, 897 (2002)，Eq. 22/23（arXiv:gr-qc/0109073，
    Eq. 23 即 Nakagawa 等材料极限）。逐层分辨（bulk/shear 分离、光弹项）
    的多层层析处理见 Hong et al., PRD 87, 082001 (2013)（gwinc
    coatingthermal 实现），属后续精化不进本条目。

    calc 返回幅值谱 ASD [m/sqrt(Hz)]。
    """

    name = "budget.coating_brownian"
    description = "coating Brownian noise (Harry 2002 Eq.22 closed form)"

    def __init__(
        self,
        temp_k: float,
        w_beam_m: float,
        y_sub_pa: float,
        sigma_sub: float,
        d_coat_m: float,
        y_coat_pa: float,
        sigma_coat: float,
        phi_parallel: float,
        phi_perp: float | None = None,
        phi_substrate: float = 0.0,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.temp_k = _num_param(temp_k, "temp_k", positive=True)
        self.w_beam_m = _num_param(w_beam_m, "w_beam_m", positive=True)
        self.y_sub_pa = _num_param(y_sub_pa, "y_sub_pa", positive=True)
        self.sigma_sub = _num_param(sigma_sub, "sigma_sub")
        self.d_coat_m = _num_param(d_coat_m, "d_coat_m", positive=True)
        self.y_coat_pa = _num_param(y_coat_pa, "y_coat_pa", positive=True)
        self.sigma_coat = _num_param(sigma_coat, "sigma_coat")
        self.phi_parallel = _num_param(phi_parallel, "phi_parallel")
        self.phi_perp = None if phi_perp is None else _num_param(phi_perp, "phi_perp")
        self.phi_substrate = _num_param(phi_substrate, "phi_substrate")
        for label, sigma in (("sigma_sub", self.sigma_sub), ("sigma_coat", self.sigma_coat)):
            if not abs(sigma) < 1.0:
                raise ValueError(f"{label} 须 |sigma| < 1（1-sigma^2 > 0），得到 {sigma}")

    def psd(self, f: np.ndarray) -> np.ndarray:
        """涂覆 Brownian 位移谱密度 S_x(f) [m^2/Hz]（Eq. 22 逐字）。"""
        freq = np.asarray(f, dtype=float)
        ys, ss = self.y_sub_pa, self.sigma_sub
        yc, sc = self.y_coat_pa, self.sigma_coat
        phi_par = self.phi_parallel
        phi_perp = phi_par if self.phi_perp is None else self.phi_perp
        numer = (
            yc**2 * (1.0 + ss) ** 2 * (1.0 - 2.0 * ss) ** 2 * phi_par
            + ys * yc * sc * (1.0 + ss) * (1.0 + sc) * (1.0 - 2.0 * ss) * (phi_par - phi_perp)
            + ys**2 * (1.0 + sc) ** 2 * (1.0 - 2.0 * sc) * phi_perp
        )
        denom = ys * yc * (1.0 - sc**2) * (1.0 - ss**2)
        bracket = self.phi_substrate + (numer / denom) / np.sqrt(np.pi) * self.d_coat_m / self.w_beam_m
        out: np.ndarray = (
            2.0 * K_B_J_PER_K * self.temp_k / (np.pi**1.5 * freq)
            * (1.0 - ss**2) / (self.w_beam_m * ys)
            * bracket
        )
        return out

    def calc(self, f: np.ndarray, context: Mapping[str, Any] | None = None) -> np.ndarray:
        out: np.ndarray = np.sqrt(self.psd(f))
        return out


# Peterson (1993) 新低噪声模型 NLNM 表格（USGS Open-File Report 93-322，
# 公有领域；逐字借镜 LIGO GWINC seismic_ground_NLNM，Unlicense）：
# 自变量 x=1/f [s]，幅值 = 10^((A+B*log10(x))/20)/(2*pi*f)^2 [m/sqrt(Hz)]。
_PETERSON_NLNM_P = np.array([
    1.00e-02, 1.00e-01, 1.70e-01, 4.00e-01, 8.00e-01, 1.24e+00,
    2.40e+00, 4.30e+00, 5.00e+00, 6.00e+00, 1.00e+01, 1.20e+01,
    1.56e+01, 2.19e+01, 3.16e+01, 4.50e+01, 7.00e+01, 1.01e+02,
    1.54e+02, 3.28e+02, 6.00e+02, 1.00e+04,
])
_PETERSON_NLNM_A = np.array([
    -156.72, -162.36, -166.7, -170.0, -166.4, -168.6, -159.98,
    -141.1, -71.36, -97.26, -132.18, -205.27, -37.65, -114.37,
    -160.58, -187.5, -216.47, -185.0, -168.34, -217.43, -258.28,
    -346.88,
])
_PETERSON_NLNM_B = np.array([
    5.64, 5.64, 0.0, -8.3, 28.9, 52.48, 29.81,
    0.0, -99.77, -66.49, -31.57, 36.16, -104.33, -47.1,
    -16.28, 0.0, 15.7, 0.0, -7.61, 11.9, 26.6,
    48.75,
])


class SeismicFoldedItem(BudgetItem):
    """seismic 折叠谱条目（地面谱 × 悬挂传递函数折叠，低频 SEO 口径）。

    物理口径（gwinc seismic 机制：贡献 = |T| * 地面幅值谱，功率域按账本
    quadratic 叠加）：
    - 地面谱二选一：
      * ground_model="peterson_nlnm"（缺省）：Peterson (1993) 新低噪声模型
        NLNM——USGS Open-File Report 93-322 公有领域表格，实现逐字借镜
        LIGO GWINC seismic_ground_NLNM（Unlicense）；
      * ground_model="power_law"：幂律幅值谱
        ground_power_a * (f/ground_power_f_ref)^(-ground_power_exponent)
        [长度单位/sqrt(Hz)]（实测台址谱的渐近拟合口径）。
    - 悬挂折叠：n_stages 级谐振 f0/Q 阻尼谐振子低通级联（gwinc
      suspension.py 符号级级联同构的紧凑闭式）：
        |T(f)| = prod_i |1 / (1 - (f/f0)^2 + 1j*f/(Q*f0))|
      超谐振极限 |T| -> (f0/f)^(2*n_stages)（f0=1 Hz 四级摆即 gwinc aLIGO
      惯例的 f^-8 功率律折叠）。

    calc 返回幅值谱 ASD（与地面谱同长度单位/sqrt(Hz)）。
    """

    name = "budget.seismic_folded"
    description = "seismic folded spectrum (Peterson NLNM / power law x pendulum fold)"

    def __init__(
        self,
        f0_hz: float,
        q_pendulum: float = 10.0,
        n_stages: int = 1,
        ground_model: str = "peterson_nlnm",
        ground_power_a: float | None = None,
        ground_power_exponent: float | None = None,
        ground_power_f_ref: float | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self.f0_hz = _num_param(f0_hz, "f0_hz", positive=True)
        self.q_pendulum = _num_param(q_pendulum, "q_pendulum", positive=True)
        if isinstance(n_stages, bool) or float(n_stages) != int(n_stages) or int(n_stages) < 1:
            raise ValueError(f"n_stages 须为 >=1 的整数，得到 {n_stages!r}")
        self.n_stages = int(n_stages)
        self.ground_model = str(ground_model)
        # power_law 分支赋值、peterson 分支显式 None（缺省联合口径，types only
        # 的裸注解——ground_asd 的 power_law 分支由 __init__ 校验三参齐备）
        self.ground_power_a: float | None
        self.ground_power_exponent: float | None
        self.ground_power_f_ref: float | None
        if self.ground_model == "power_law":
            if ground_power_a is None or ground_power_exponent is None or ground_power_f_ref is None:
                raise ValueError(
                    "ground_model='power_law' 需 ground_power_a/ground_power_exponent/"
                    "ground_power_f_ref 三参齐备（判缺失 is not None）")
            self.ground_power_a = _num_param(ground_power_a, "ground_power_a")
            if isinstance(ground_power_exponent, bool):
                raise ValueError("ground_power_exponent 不接受 bool（数值入参显式拒收）")
            self.ground_power_exponent = float(ground_power_exponent)
            self.ground_power_f_ref = _num_param(ground_power_f_ref, "ground_power_f_ref", positive=True)
        elif self.ground_model == "peterson_nlnm":
            self.ground_power_a = None
            self.ground_power_exponent = None
            self.ground_power_f_ref = None
        else:
            raise ValueError(
                f"未知 ground_model: {self.ground_model!r}（可用: peterson_nlnm / power_law）")

    @staticmethod
    def peterson_nlnm_asd(f: np.ndarray) -> np.ndarray:
        """Peterson NLNM 地面位移幅值谱 [m/sqrt(Hz)]（gwinc 逐字口径）。"""
        freq = np.asarray(f, dtype=float)
        x = 1.0 / freq
        db = np.interp(x, _PETERSON_NLNM_P, _PETERSON_NLNM_A + _PETERSON_NLNM_B * np.log10(_PETERSON_NLNM_P))
        out: np.ndarray = 10.0 ** (db / 20.0) / (2.0 * np.pi * freq) ** 2
        return out

    def ground_asd(self, f: np.ndarray) -> np.ndarray:
        """地面运动幅值谱（NLNM 表格或幂律，[长度单位/sqrt(Hz)]）。"""
        freq = np.asarray(f, dtype=float)
        if self.ground_model == "peterson_nlnm":
            return self.peterson_nlnm_asd(freq)
        # power_law 三参齐备已在 __init__ 校验（cast=恒等，types only）
        a = cast("float", self.ground_power_a)
        f_ref = cast("float", self.ground_power_f_ref)
        exponent = cast("float", self.ground_power_exponent)
        return a * (freq / f_ref) ** (-exponent)

    def fold_gain(self, f: np.ndarray) -> np.ndarray:
        """悬挂折叠增益 |T(f)|（n_stages 级阻尼谐振子级联，无量纲）。"""
        ratio = np.asarray(f, dtype=float) / self.f0_hz
        denom = 1.0 - ratio**2 + 1j * ratio / self.q_pendulum
        return np.abs(denom) ** (-self.n_stages)

    def calc(self, f: np.ndarray, context: Mapping[str, Any] | None = None) -> np.ndarray:
        out: np.ndarray = self.ground_asd(f) * self.fold_gain(f)
        return out


# ─── 全局注册表（内置条目导入即注册）─────────────────────────────────────────
BUDGET_REGISTRY = BudgetRegistry()
BUDGET_REGISTRY.register(GridDiscretizationItem)
BUDGET_REGISTRY.register(PortReferenceItem)
BUDGET_REGISTRY.register(ToleranceItem)
BUDGET_REGISTRY.register(CalibrationResidualItem)
BUDGET_REGISTRY.register(ToleranceMcItem)
BUDGET_REGISTRY.register(SurrogateErrorItem)
BUDGET_REGISTRY.register(RadiationPressureItem)
BUDGET_REGISTRY.register(ThermorefractiveItem)
BUDGET_REGISTRY.register(CoatingBrownianItem)
BUDGET_REGISTRY.register(SeismicFoldedItem)


__all__ = [
    "BUDGET_REGISTRY",
    "MODE_COHERENT",
    "MODE_QUADRATIC",
    "BudgetItem",
    "BudgetRegistry",
    "BudgetTrace",
    "CalibrationResidualItem",
    "GridDiscretizationItem",
    "PortReferenceItem",
    "SurrogateErrorItem",
    "ToleranceItem",
    "ToleranceMcItem",
    "budget_evaluate",
    "budget_report",
    "budget_report_stacked",
]
