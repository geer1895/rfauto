"""R4（df7+ 第三层）：Z3 声明式几何约束内核（渲染前一次求解 + UNSAT core 全量冲突报告）。

方案池 docs/plan_expansion_pool_20260924.md R4（:207）：#152 最小线距/#311 缝内
线数/recipe bounds 全写成 SMT 约束渲染前一次求解，UNSAT core 直接告知哪几条
规则互斥——现状是渲染期 if 链（如 c3_gap_mesh_guard）只报第一个失败、其余被
遮蔽。本内核把"规则"提升为一等对象：每条规则贡献一条 z3 断言并带 rule_id
标签，一次 check 后由 z3 unsat core 回读全部参与互斥的 rule_id 集合。

依赖与降级：z3-solver 为可选依赖（extras [z3]），本模块**惰性 import**——顶层
零 z3 import；未安装时 solve_rules 返回 ok=False/status="unavailable"（reason
指明安装命令），不 raise 裸异常（#105 best-effort 精神：声明式求解是增强件，
不得成为渲染主路径的故障点；既有 if 链守卫零改动零替代）。

编码纪律：约束限定**线性算术**（符号与常数间的 +/−/×常数；禁止符号×符号），
z3 对线性 Real 算术可判定，杜绝 unknown 进入业务路径；_Symbols 是 Rule.build
闭包触达 z3 的唯一入口，保证 z3 只在 solve_rules 内部被加载。规则构造期
（helpers）与 service 层均不 import z3。

用法（service 薄壳见 service/render_constraint_service.py）::

    rules = [
        bounds_rule("bounds:base", "...", "base_mm", low=0.4, high=0.5),
        derived_ratio_rule("near_definition", "...", "near_mm", "base_mm", 4.0),
        gap_cells_rule("gap_cells_guard", "...", min_gap=0.139, near_var="near_mm", cells=3),
    ]
    verdict = solve_rules(rules)
    if not verdict.ok and verdict.status == "unsat":
        # verdict.conflict_rule_ids = 全部互斥规则（迭代去核覆盖独立多冲突组）

判据预声明：runs/df7_r4z3/criteria.md（C1–C7）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

Z3_INSTALL_HINT = "pip install rfauto[z3]（或 pip install z3-solver）"
"""z3 缺装降级 reason 中的安装指引（与 pyproject extras 名一致）。"""

DEFAULT_MAX_CONFLICT_GROUPS = 8
"""迭代去核检出独立冲突组的上限（防爆；超出部分如实记入 reason）。"""


# ---------------------------------------------------------------------------
# z3 惰性导入通道（唯一 import 点；测试 monkeypatch 本函数模拟缺装）
# ---------------------------------------------------------------------------

def _import_z3() -> Any:
    """返回 z3 模块；缺装抛 ImportError——由 solve_rules 捕获降级，不外泄。

    单独成函数便于测试 monkeypatch 钉通道（#139 同族纪律：不依赖真实卸载）。
    """
    import z3

    return z3


class _Symbols:
    """Rule.build 闭包的 z3 表达式面（z3 触达的唯一入口，线性算术子集）。

    只在 solve_rules 内部实例化（彼时 z3 已成功加载）；Rule 构造 helpers 与
    service 层永不持有本类实例，故它们不需要 z3 可导入。
    """

    def __init__(self, z3: Any) -> None:
        self._z3 = z3
        self._reals: dict[str, Any] = {}

    def real(self, name: str) -> Any:
        """按名声明/复用一个 z3 Real 符号（同名跨规则天然共享=互斥链来源）。"""
        if name not in self._reals:
            self._reals[name] = self._z3.Real(name)
        return self._reals[name]

    def val(self, x: float) -> Any:
        """Python 数值 → z3 有理常数（float 按二进制精确转为 RatVal）。"""
        return self._z3.RealVal(float(x))

    def ge(self, a: Any, b: Any) -> Any:
        return a >= b

    def le(self, a: Any, b: Any) -> Any:
        return a <= b

    def eq(self, a: Any, b: Any) -> Any:
        return a == b

    def sub(self, a: Any, b: Any) -> Any:
        return a - b

    def scale(self, k: float, a: Any) -> Any:
        return self.val(k) * a

    def all_of(self, exprs: Sequence[Any]) -> Any:
        """合取（单条直返；空表恒真——True 常数，调用方一般不应传空）。"""
        if not exprs:
            return self._z3.BoolVal(True)
        if len(exprs) == 1:
            return exprs[0]
        return self._z3.And(list(exprs))

    def any_of(self, exprs: Sequence[Any]) -> Any:
        """析取（单条直返；空表恒假——True 不该由空析取伪造）。"""
        if not exprs:
            return self._z3.BoolVal(False)
        if len(exprs) == 1:
            return exprs[0]
        return self._z3.Or(list(exprs))


# ---------------------------------------------------------------------------
# 规则与判定结果
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    """一条命名几何/参数约束。

    rule_id     稳定标识（UNSAT core 回读与跨 run 比对的键；同批不得重复）；
    description 人类可读口径（进 verdict/报告，不含物理结论——数值只在内核）；
    build       惰性约束构造器：接收 _Symbols，返回 z3 Bool 表达式。只在 z3
                加载成功后被 solve_rules 调用；闭包内禁止触达 IO/z3 顶层名。
    """

    rule_id: str
    description: str
    build: Callable[[_Symbols], Any]


@dataclass(frozen=True)
class RuleReport:
    """逐规则报告（in_conflict=是否落入任一冲突组）。"""

    rule_id: str
    description: str
    in_conflict: bool


@dataclass(frozen=True)
class ConstraintVerdict:
    """solve_rules 判定结果（service 层直接转 JSON）。

    status:
      "sat"         全部规则可行（witness 给出一组满足值）；
      "unsat"       存在冲突（conflict_groups 逐组给出互斥规则集；
                    conflict_rule_ids=并集）；
      "unavailable" z3 缺装/加载失败——优雅降级，ok=False，不崩；
      "unknown"     求解器无法判定（线性编码下不应出现，如实上报不凑）；
      "error"       规则构造/求解过程异常（reason 带原始异常 repr）。
    """

    ok: bool
    status: str
    conflict_rule_ids: tuple[str, ...] = ()
    conflict_groups: tuple[tuple[str, ...], ...] = ()
    rules: tuple[RuleReport, ...] = ()
    witness: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    solver: str = "z3"


# ---------------------------------------------------------------------------
# 求解
# ---------------------------------------------------------------------------

def solve_rules(
    rules: Sequence[Rule],
    *,
    max_conflict_groups: int = DEFAULT_MAX_CONFLICT_GROUPS,
) -> ConstraintVerdict:
    """一次求解全部规则；UNSAT 时经 unsat core 报出全部冲突 rule_id。

    语义与边界（预声明，criteria C1/C2）：
    - z3 unsat core 是"本次不可满足性证明参与的规则集"——同核内互斥链全量
      报出（对比 if 链只报首个失败的根除点）；
    - 互不相干的独立冲突组经**迭代去核**补齐：取核→剔除核内规则→剩余规则
      重解，直至 sat 或组数达 max_conflict_groups；每组各自是真冲突，
      conflict_rule_ids 为并集（同一规则可参与多组，并集是冲突规则的上界集）；
    - 组序不预设（z3 核提取顺序属求解器内部策略），消费方按集合语义读取；
    - 一旦发现冲突组，整体判据即 unsat/ok=False，不因去核轮的剩余规则可满足
      而翻转；witness 仅在首轮全量规则 SAT 时给出（去核残局的模型无整体意义）。
    """
    ids = [r.rule_id for r in rules]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"rule_id 重复: {dupes}（rule_id 是核回读键，必须唯一）")
    if not rules:
        return ConstraintVerdict(ok=True, status="sat", reason="无规则，平凡可行")

    try:
        z3 = _import_z3()
    except (ImportError, OSError) as exc:
        return ConstraintVerdict(
            ok=False,
            status="unavailable",
            reason=f"z3 未安装/加载失败，声明式约束求解降级不可用"
                   f"（{Z3_INSTALL_HINT}）：{exc!r}",
            solver="",
        )

    remaining = list(rules)
    groups: list[tuple[str, ...]] = []
    witness: dict[str, float] = {}
    status = "sat"
    reason = ""
    full_pass = True  # 首轮=全量规则；去核轮的 sat 只说明无更多独立冲突
    while remaining:
        solver = z3.Solver()
        solver.set("unsat_core", True)
        symbols = _Symbols(z3)
        try:
            for r in remaining:
                solver.assert_and_track(r.build(symbols), r.rule_id)
            result = solver.check()
        except Exception as exc:  # 降级边界内如实归类，不裸崩（#105 best-effort）
            return ConstraintVerdict(
                ok=False,
                status="error",
                conflict_rule_ids=tuple(i for g in groups for i in g),
                conflict_groups=tuple(groups),
                reason=f"规则构造/求解异常（如实上报，不凑判定）：{exc!r}",
            )
        if result == z3.sat:
            if full_pass:
                status = "sat"
                witness = _model_witness(symbols, solver.model())
            # 去核轮 sat：剩余规则无更多独立冲突，整体判据维持 unsat 不翻转
            break
        if result == z3.unknown:
            status = "unknown"
            reason = ("z3 返回 unknown（线性编码下不应出现；检查是否引入了"
                      "非线性约束），如实上报不凑 sat")
            break
        # unsat：回读核（assert_and_track 的 str 标签回读为 Bool 常量名）
        full_pass = False
        core_ids = sorted(str(lit.decl().name()) for lit in solver.unsat_core())
        if not core_ids:
            status = "unsat"
            reason = "unsat core 为空（求解器异常态），无法归属冲突规则——如实上报"
            break
        groups.append(tuple(core_ids))
        status = "unsat"
        remaining = [r for r in remaining if r.rule_id not in set(core_ids)]
        if remaining and len(groups) >= max_conflict_groups:
            reason = (f"冲突组数达上限 {max_conflict_groups}，剩余 "
                      f"{len(remaining)} 条规则未继续检独立冲突"
                      f"（提升 max_conflict_groups 可放宽）")
            break

    conflict_ids = tuple(sorted({i for g in groups for i in g}))
    conflicted = set(conflict_ids)
    reports = tuple(
        RuleReport(r.rule_id, r.description, r.rule_id in conflicted) for r in rules
    )
    return ConstraintVerdict(
        ok=status == "sat",
        status=status,
        conflict_rule_ids=conflict_ids,
        conflict_groups=tuple(groups),
        rules=reports,
        witness=witness,
        reason=reason,
    )


def _model_witness(symbols: _Symbols, model: Any) -> dict[str, float]:
    """SAT 模型回读：已声明符号 → float（有理数精确转双精度；仅 witness 用途）。

    数值只在确定性内核（规则 7）：witness 是 z3 模型值，不是任何物理结论。
    """
    out: dict[str, float] = {}
    for name, sym in symbols._reals.items():
        evaluated = model.eval(sym, model_completion=True)
        out[name] = _rat_to_float(evaluated)
    return out


def _rat_to_float(numref: Any) -> float:
    """z3 有理数 → float（as_float 优先，退化走分子/分母长整除）。"""
    try:
        return float(numref.as_float())
    except (AttributeError, TypeError):
        return float(numref.numerator_as_long()) / float(
            numref.denominator_as_long())


# ---------------------------------------------------------------------------
# 规则构造 helpers（三族：最小间距/缝内线数/参数 bounds；均不触达 z3）
# ---------------------------------------------------------------------------

def bounds_rule(
    rule_id: str,
    description: str,
    var: str,
    *,
    low: float | None = None,
    high: float | None = None,
) -> Rule:
    """参数 bounds 族：var ∈ [low, high]（闭区间；None=该侧不设限）。

    recipe/配置可取域的 SMT 形式（如 mesh_resolution_mm ∈ [0.4, 0.5] 工程
    缺省档）；恰等边界合规（闭区间，与 c3_gap_mesh_guard 的 1e-9 容差方向
    一致：恰等合规、严格越界违规）。
    """
    if low is None and high is None:
        raise ValueError(f"{rule_id}: low/high 至少给一侧（否则不构成约束）")
    if low is not None and high is not None and low > high:
        raise ValueError(f"{rule_id}: low={low} > high={high}（空区间）")

    def build(syms: _Symbols) -> Any:
        expr = syms.real(var)
        conds = []
        if low is not None:
            conds.append(syms.ge(expr, syms.val(low)))
        if high is not None:
            conds.append(syms.le(expr, syms.val(high)))
        return syms.all_of(conds)

    return Rule(rule_id, description, build)


def derived_ratio_rule(
    rule_id: str,
    description: str,
    var: str,
    source_var: str,
    ratio: float,
) -> Rule:
    """派生定义族：var == source_var / ratio（如 NEAR = base/4 官方口径）。

    定义型规则本身不"违规"，但它把互斥链两端接通（bounds 对 base 的限制
    经此传播到 NEAR 侧守卫），是 UNSAT core 能报全冲突链的关键断言。
    """
    if ratio == 0.0:
        raise ValueError(f"{rule_id}: ratio 不得为 0")

    def build(syms: _Symbols) -> Any:
        return syms.eq(syms.real(var),
                       syms.real(source_var) / syms.val(ratio))

    return Rule(rule_id, description, build)


def min_spacing_rule(
    rule_id: str,
    description: str,
    positions: Sequence[float],
    *,
    min_spacing: float,
) -> Rule:
    """最小间距族（#152）：同轴网格线两两相邻间距 ≥ min_spacing（单位一致即可，
    推荐毫米；#152 原阈值 1e-6 m=1e-3 mm，#349 全轴守卫 10µm=1e-2 mm 同族）。

    positions 为常数线位（地面约束）：恰等 SAT（≥ 闭边界）、严格偏小即本条
    规则单独成核——单规则违反时的核恰为该条，不多报。
    """
    pos = sorted(float(p) for p in positions)
    if len(pos) < 2:
        raise ValueError(f"{rule_id}: 至少 2 条线位才构成间距约束，得 {len(pos)}")
    if min_spacing <= 0.0:
        raise ValueError(f"{rule_id}: min_spacing 须 >0，得 {min_spacing}")

    def build(syms: _Symbols) -> Any:
        conds = [
            syms.ge(syms.sub(syms.val(pos[i + 1]), syms.val(pos[i])),
                    syms.val(min_spacing))
            for i in range(len(pos) - 1)
        ]
        return syms.all_of(conds)

    return Rule(rule_id, description, build)


def gap_cells_rule(
    rule_id: str,
    description: str,
    *,
    min_gap: float,
    near_var: str,
    cells: int,
) -> Rule:
    """缝内格数族·守卫侧（#266/#311）：最小耦合缝 ≥ cells×NEAR，即
    NEAR × cells ≤ min_gap（c3_gap_mesh_guard 的 NEAR ≤ 缝/cells 同式）。

    cells 取 3（_C3_GAP_CELLS_MIN 同款）=缝内至少 cells 格的充分条件；
    恰等合规（NEAR×cells == gap 判 SAT，与既有守卫 1e-9 容差方向一致）。
    """
    if cells <= 0:
        raise ValueError(f"{rule_id}: cells 须 >0，得 {cells}")
    if min_gap <= 0.0:
        raise ValueError(f"{rule_id}: min_gap 须 >0，得 {min_gap}")

    def build(syms: _Symbols) -> Any:
        return syms.le(syms.scale(float(cells), syms.real(near_var)),
                       syms.val(min_gap))

    return Rule(rule_id, description, build)


def gap_internal_line_rule(
    rule_id: str,
    description: str,
    *,
    gap: float,
    near_var: str,
    min_spacing: float,
) -> Rule:
    """缝内线数族·存在性侧（#311）：缝宽 gap 内部线 ≥1 的两种达成路径取析取——

    (a) 自动细分路径：gap ≥ NEAR（SmoothMeshLines 会细分 >NEAR 的区间）；
    (b) 显式缝中线路径（_c4_gap_midlines 同口径）：gap/2 ≥ min_spacing，
        即中线到两侧缝缘均满足 #152 最小间距（中线存在且不被去重吞掉）。

    该规则是"修复路径"而非互斥链主干——c3 #266 历史案例重演中它应**不在**
    核内（真凶是 NEAR×cells ≤ gap 与 bounds 的互斥），验证核只收真凶。
    """
    if gap <= 0.0:
        raise ValueError(f"{rule_id}: gap 须 >0，得 {gap}")
    if min_spacing <= 0.0:
        raise ValueError(f"{rule_id}: min_spacing 须 >0，得 {min_spacing}")

    def build(syms: _Symbols) -> Any:
        gap_expr = syms.val(gap)
        return syms.any_of([
            syms.ge(gap_expr, syms.real(near_var)),
            syms.ge(gap_expr, syms.scale(2.0, syms.val(min_spacing))),
        ])

    return Rule(rule_id, description, build)
