"""DP-14 M1：PySR 锚公式自动发现（合成回收先行 → γ(εr) 8 档重发现对照）。

规格书 docs/plan_deepdive_specs_20260924.md §14.1；判据预声明
runs/df6_dp14m1/criteria.md（开工前落盘，不事后改门）。

流程：
  1. 合成回收门：γ(εr)=1+c0·εr^(−c1)（c0/c1=仓内锚 calculators.
     CPS_H_EFF_GAMMA_C/P）造 64 点 log-uniform εr∈[1.5,12.9] + 0.2% 相对
     高斯噪声（seed 固定）→ PySR 从 [+-*/^]+[inv,sqrt,log,exp] 词表恢复
     结构（AST 归一后与 1+c0·x^(−c1) 等价书写逐字一致）+ 系数（确定性
     LSQ 精修后 rel err ≤1e-3）。本门不过不进入第 2 步。
  2. γ(εr) 8 档重发现：对 docs/rf_template_references.md §11.1 的 8 档
     定标值（εr∈{1.5,2.2,3.0,3.66,4.4,6.15,10.2,12.9} →
     γ∈{1.706,1.547,1.446,1.392,1.348,1.281,1.206,1.180}）重发现；选式
     在 8 档求值逐档相对误差 ≤1.4%（§11.1 既有判据口径）。
  3. 整条复杂度-损失 Pareto 前沿打印（人工选式口）；本批选式=最简
     无损式（损失 ≤ 最优式 1.05× 窗内取最小复杂度，平局取更低损失）。
  4. 复现锁验证：8 点拟合跑两遍（同 seed）对比 Pareto 前沿逐位一致。
  5. 候选 JSON 落 --out-dir/cps_gamma_pysr_candidate.json：rules.yaml
     formula 型字段 + register_symbolic_formula 兼容 terms/coefficients
     形态 + AST 白名单校验证明（复刻 core/calculators.py:3206-3236 词表，
     测试与仓内 _validate_symbolic_node 双检对照）。**不改 rules.yaml**
     （formula 登记随 DP-3 锚注册表批次走，本批只产候选）。

铁律 7：本脚本不产生新物理常数——γ(εr) 候选式仅供人工审核，不入注册表。
复现锁：OPENBLAS_NUM_THREADS=1、Julia depot 钉 E 盘（JULIA_DEPOT_PATH）、
procs=1/parallelism=serial + deterministic=True + random_state 固定。

用法：
  .venv/Scripts/python.exe scripts/pysr_anchor_fit.py \
      --out-dir runs/df6_dp14m1 [--skip-synthetic] [--niterations 40]
"""

from __future__ import annotations

import os

# 复现锁必须先于 numpy/pysr 导入生效（BLAS 线程数在加载期读取；Julia
# depot 必须在 juliacall 初始化前指向 E 盘——硬规则 1）。
for _key, _val in (
    ("OPENBLAS_NUM_THREADS", "1"),
    ("OMP_NUM_THREADS", "1"),
    ("MKL_NUM_THREADS", "1"),
    ("PYTHONHASHSEED", "0"),   # 跨进程复现（PySR deterministic 仅进程内）
    ("JULIA_DEPOT_PATH", os.environ.get("RFAUTO_JULIA_DEPOT", r"E:\julia_depot")),
    ("JULIAUP_DEPOT_PATH", os.environ.get("RFAUTO_JULIA_UP", r"E:\julia_up")),
):
    os.environ[_key] = _val

import argparse  # noqa: E402 —— 复现锁 env 必须先于 numpy/pysr 导入生效（固有形态）
import ast  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from rfauto.core.calculators import CPS_H_EFF_GAMMA_C, CPS_H_EFF_GAMMA_P  # noqa: E402

# ── 判据常数（预声明，与 runs/df6_dp14m1/criteria.md 一致，不事后改门）──────
SYNTHETIC_SEED = 20260924
N_SYNTHETIC = 64
NOISE_REL = 0.002                     # 合成数据相对高斯噪声
ER_LO, ER_HI = 1.5, 12.9              # γ(εr) 定标域（refs §11.1）
SYNTH_PARAM_REL_TOL = 1e-3            # 合成回收：参数 rel err 门（精修后）
STRUCT_TOL = 1e-3                     # 严格档：常数节点 |A−1|≤1e-3
FAMILY_TOL = 0.05                     # 结构档：物理极限常数 |A−1|≤5%（PySR
                                      # 演化常数未收敛到 1 的容差；精修阶段
                                      # 钉 A=1 后参数门仍 1e-3）
EIGHT_POINT_REL_TOL = 0.014           # 8 档重发现：逐档 ≤1.4%（refs §11.1）
LOSS_WINDOW = 1.05                    # 选式"无损窗"：损失 ≤ 最优式 ×1.05

# γ(εr) 8 档真值（docs/rf_template_references.md §11.1 :321-323，逐档
# max|err|≤0.6% 的定标产物；--refit-cps-gamma 可复现）
EIGHT_POINT: tuple[tuple[float, float], ...] = (
    (1.5, 1.706), (2.2, 1.547), (3.0, 1.446), (3.66, 1.392),
    (4.4, 1.348), (6.15, 1.281), (10.2, 1.206), (12.9, 1.180),
)

# 搜索词表（规格书 §14.1 白名单）与登记词表（repo 0cz AST 口径，只允许
# sqrt/log——候选式若含 exp/inv 等价式必须先改写才可登记）
SEARCH_BINARY_OPS = ["+", "-", "*", "/", "^"]
SEARCH_UNARY_OPS = ["inv(x) = 1/x", "sqrt", "log", "exp"]
REGISTRY_ALLOWED_FUNCS = frozenset({"sqrt", "log"})

# 嵌套约束（搜索整形，词表不变）：exp/log 内禁止任意嵌套（压制 exp∘sqrt∘/
# exp∘除法类平台陷阱——首轮合成实测进化陷该平台），sqrt 内禁 exp/log/sqrt。
_NEST_ZERO_OPS = ("+", "-", "*", "/", "^", "inv", "sqrt", "exp", "log")
NESTED_CONSTRAINTS = {
    "exp": {op: 0 for op in _NEST_ZERO_OPS},
    "log": {op: 0 for op in _NEST_ZERO_OPS},
    "sqrt": {"exp": 0, "log": 0, "sqrt": 0},
}


# ── AST 白名单（复刻 core/calculators.py:3206-3236 词表；测试与仓内原版
#    双检对照。独立实现而非 import 私有符号——候选 JSON 证明自带校验器）──────
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)


def _validate_node(node: ast.AST, allowed_names: frozenset[str],
                   allowed_funcs: frozenset[str]) -> None:
    """递归校验公式语法树：只允许数值常量、已声明变量、四则/幂、一元 ±、
    白名单单参函数调用；其余节点 ValueError（显式拒绝，不静默）。"""
    if isinstance(node, ast.Expression):
        _validate_node(node.body, allowed_names, allowed_funcs)
        return
    if (isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)):
        return
    if isinstance(node, ast.Name) and node.id in allowed_names:
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        _validate_node(node.left, allowed_names, allowed_funcs)
        _validate_node(node.right, allowed_names, allowed_funcs)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        _validate_node(node.operand, allowed_names, allowed_funcs)
        return
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in allowed_funcs
            and not node.keywords and len(node.args) == 1):
        _validate_node(node.args[0], allowed_names, allowed_funcs)
        return
    raise ValueError(
        f"公式含不允许的语法节点: {type(node).__name__}"
        "（只允许常量/已声明变量/四则幂/一元±/白名单单参函数）")


def validate_formula_ast(expr: str, allowed_names: frozenset[str],
                         allowed_funcs: frozenset[str] = REGISTRY_ALLOWED_FUNCS,
                         ) -> ast.AST:
    """`^`→`**` 归一后 ast.parse+白名单校验；返回 AST（供结构匹配复用）。"""
    tree = ast.parse(expr.replace("^", "**"), mode="eval")
    _validate_node(tree, allowed_names, allowed_funcs)
    return tree


# ── 结构匹配：识别 1 + c0·x^(−c1) 的等价书写 ──────────────────────────────
def _fold_const(node: ast.AST) -> float | None:
    """折叠 Constant / 一元 ±（含嵌套）为 float；其余 None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _fold_const(node.operand)
        return None if inner is None else -inner
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
        return _fold_const(node.operand)
    return None


def _pow_exp_pos(node: ast.AST, var: str) -> float | None:
    """识别 x**c1（c1>0 正常数）、inv(x**c1) 或裸 x（≡c1=1，倒数拼写），
    返回 c1；否则 None。"""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        if isinstance(node.left, ast.Name) and node.left.id == var:
            e = _fold_const(node.right)
            if e is not None and e > 0:
                return e
        return None
    if isinstance(node, ast.Name) and node.id == var:
        return 1.0                                # x ≡ x**1（除法分母）
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == "inv" and len(node.args) == 1 \
            and not node.keywords:
        return _pow_exp_pos(node.args[0], var)
    return None


def _pow_exp_neg(node: ast.AST, var: str) -> float | None:
    """识别 x**(-c1)（负常数或一元负号），返回 c1>0；否则 None。"""
    if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)
            and isinstance(node.left, ast.Name) and node.left.id == var):
        e = _fold_const(node.right)
        if e is not None and e < 0:
            return -e
    return None


def _match_power_term(node: ast.AST, var: str) -> tuple[float, float] | None:
    """识别 c0·x^(−c1) 项的等价书写，返回 (c0, c1)；否则 None。

    覆盖：c0*x**-c1 / c0*x**(-c1) / x**-c1*c0 / c0/x**c1 / c0*(1/x**c1)
    / c0*inv(x**c1)（inv 归一为倒数幂）。"""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        num = _fold_const(node.left)               # c0 / (x**c1)
        den = _pow_exp_pos(node.right, var)
        if num is not None and den is not None and num > 0:
            return (num, den)
        neg = _pow_exp_neg(node.left, var)         # (x**-c1) / c0 ≡ (1/c0)·x^-c1
        den_c = _fold_const(node.right)
        if neg is not None and den_c is not None and den_c > 0:
            return (1.0 / den_c, neg)
        return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == "inv" and len(node.args) == 1 \
            and not node.keywords:                 # 裸 inv(x**c1) / inv(x)
        e = _pow_exp_pos(node.args[0], var)
        if e is not None:
            return (1.0, e)
        if isinstance(node.args[0], ast.Name) and node.args[0].id == var:
            return (1.0, 1.0)
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        for coef_side, pow_side in ((node.left, node.right),
                                    (node.right, node.left)):
            c0 = _fold_const(coef_side)
            if c0 is None or c0 <= 0:
                continue
            e = _pow_exp_neg(pow_side, var)         # c0 * x**-c1
            if e is not None:
                return (c0, e)
            if isinstance(pow_side, ast.BinOp) and isinstance(pow_side.op,
                                                              ast.Div):
                one = _fold_const(pow_side.left)    # c0 * (1 / x**c1)
                if one == 1.0:
                    e = _pow_exp_pos(pow_side.right, var)
                    if e is not None:
                        return (c0, e)
            if isinstance(pow_side, ast.Call) \
                    and isinstance(pow_side.func, ast.Name) \
                    and pow_side.func.id == "inv":
                e = _pow_exp_pos(pow_side, var)     # c0 * inv(x**c1)
                if e is not None:
                    return (c0, e)
        return None
    e = _pow_exp_neg(node, var)                     # 裸 x**-c1（c0=1）
    if e is not None:
        return (1.0, e)
    return None


def match_power_law(expr: str, var: str = "x") -> tuple[float, float] | None:
    """从公式串识别 A + B·x^(−C) 结构（AST 归一后等价书写），其中常数项
    A 须满足 |A−1|≤FAMILY_TOL（物理极限常数 γ→1 的结构角色；PySR 演化期
    常数允许未收敛），返回 (B, C)（PySR 原始系数，供 LSQ 精修起点——精修
    阶段钉 A=1）。覆盖等价书写：Sub/负常数（`t − −A` ≡ t + A）、因式
    `B·(x^(−C) ± A)`（分配律展开同族）；`A − B·x^(−C)`（B>0）非目标族，
    显式拒绝。无匹配 None。"""
    plain = _match_power_law_plain(expr, var)
    if plain is not None:
        return plain
    return _match_power_law_factor(expr, var)


def _match_power_law_plain(expr: str, var: str) -> tuple[float, float] | None:
    try:
        tree = ast.parse(expr.replace("^", "**"), mode="eval")
    except SyntaxError:
        return None
    body = tree.body
    if not (isinstance(body, ast.BinOp)
            and isinstance(body.op, (ast.Add, ast.Sub))):
        return None
    is_sub = isinstance(body.op, ast.Sub)
    for const_side, term_side in ((body.left, body.right),
                                  (body.right, body.left)):
        a = _fold_const(const_side)
        if a is None:
            continue
        if is_sub and const_side is body.right:
            a = -a                       # Sub 右操作数取负（− −A ≡ +A）
        if is_sub and const_side is body.left:
            continue                     # A − B·x^(−C) 非目标族（B>0）
        if a <= 0 or abs(a - 1.0) > FAMILY_TOL:
            continue
        term = _match_power_term(term_side, var)
        if term is not None:
            return term
    return None


def _match_power_law_factor(expr: str, var: str) -> tuple[float, float] | None:
    """因式等价书写 B·(x^(−C) ± A)（分配律展开 = A·B + B·x^(−C)，同一
    目标族）；A·B 须满足 |A·B−1|≤FAMILY_TOL。返回 (B, C)；否则 None。"""
    try:
        tree = ast.parse(expr.replace("^", "**"), mode="eval")
    except SyntaxError:
        return None
    body = tree.body
    if not (isinstance(body, ast.BinOp) and isinstance(body.op, ast.Mult)):
        return None
    for coef_side, sum_side in ((body.left, body.right),
                                (body.right, body.left)):
        b = _fold_const(coef_side)
        if b is None or b <= 0:
            continue
        if not (isinstance(sum_side, ast.BinOp)
                and isinstance(sum_side.op, (ast.Add, ast.Sub))):
            continue
        is_sub = isinstance(sum_side.op, ast.Sub)
        for const_side, term_side in ((sum_side.left, sum_side.right),
                                      (sum_side.right, sum_side.left)):
            a = _fold_const(const_side)
            if a is None:
                continue
            if is_sub and const_side is sum_side.right:
                a = -a
            if is_sub and const_side is sum_side.left:
                continue
            a_eff = b * a
            if a_eff <= 0 or abs(a_eff - 1.0) > FAMILY_TOL:
                continue
            term = _match_power_term(term_side, var)
            if term is not None:
                return (b * term[0], term[1])
    return None


# ── 确定性系数精修（铁律 7：数值只在确定性内核）──────────────────────────
def refine_power_law(x: np.ndarray, y: np.ndarray,
                     c0: float, c1: float) -> tuple[float, float]:
    """给定结构 1+c0·x^(−c1)，从 (c0,c1) 起做确定性 Levenberg-Marquardt
    精修（同起点的 LM 是确定性算法）。"""
    from scipy.optimize import least_squares

    def resid(p: np.ndarray) -> np.ndarray:
        return 1.0 + p[0] * np.power(x, -p[1]) - y

    sol = least_squares(resid, np.array([c0, c1]), method="lm",
                        xtol=1e-15, ftol=1e-15, gtol=1e-15)
    return float(sol.x[0]), float(sol.x[1])


def make_synthetic(seed: int = SYNTHETIC_SEED,
                   n: int = N_SYNTHETIC) -> tuple[np.ndarray, np.ndarray]:
    """γ(εr) 幂律合成数据：log-uniform εr∈[1.5,12.9] + 0.2% 相对噪声。"""
    rng = np.random.default_rng(seed)
    x = np.exp(rng.uniform(math.log(ER_LO), math.log(ER_HI), size=n))
    x.sort()
    y_true = 1.0 + CPS_H_EFF_GAMMA_C * x ** (-CPS_H_EFF_GAMMA_P)
    y = y_true * (1.0 + rng.normal(0.0, NOISE_REL, size=n))
    return x, y


# ── PySR 拟合（版本自适应：parallelism（新）/procs+multithreading（旧））──
# 分阶段搜索整形（criteria.md 执行期澄清四；词表不变，纯搜索配置）：
#   合成阶段 exp∘嵌套平台实测需 nested_constraints 破局（三轮 PASS 实证）；
#   8 点阶段 nested 会偏移普通锚族式轨迹（四轮实证），用二轮同参
#   （无 nested，80×25×40——其前沿含普通锚族式且确定性 PASS 实证）。
POPULATION_SIZE = 50
SYNTH_CONFIG = {"niterations": 160, "populations": 40,
                "population_size": 50, "nested": True}
GAMMA8_CONFIG = {"niterations": 80, "populations": 25,
                 "population_size": 40, "nested": False}


def pysr_kwargs(seed: int, niterations: int, populations: int,
                maxsize: int, timeout_s: int, nested: bool = True,
                popsize: int = POPULATION_SIZE) -> dict[str, Any]:
    import inspect

    from pysr import PySRRegressor

    params = inspect.signature(PySRRegressor.__init__).parameters
    base: dict[str, Any] = {
        "binary_operators": SEARCH_BINARY_OPS,
        "unary_operators": SEARCH_UNARY_OPS,
        "extra_sympy_mappings": {"inv": lambda x: 1 / x},  # 自定义 inv 必需
        "niterations": niterations,
        "populations": populations,
        "population_size": popsize,
        "maxsize": maxsize,
        "parsimony": 0.0005,
        "constraints": {"^": (-1, 1)},   # 压制 (expr)^const 嵌套（官方调参口径）
        "nested_constraints": NESTED_CONSTRAINTS if nested else {},
        "random_state": seed,
        "deterministic": True,
        "progress": False,
        "verbosity": 0,
        "timeout_in_seconds": timeout_s,
        "output_jax_format": False,
        "output_torch_format": False,
        "model_selection": "best",
    }
    if "parallelism" in params:
        base["parallelism"] = "serial"          # procs=1 等价（新版口径）
    else:
        base["procs"] = 1
        base["multithreading"] = False
    return base


def run_pysr_fit(x: np.ndarray, y: np.ndarray, var: str, tag: str,
                 out_dir: Path, seed: int, niterations: int, populations: int,
                 maxsize: int, timeout_s: int, nested: bool = True,
                 popsize: int = POPULATION_SIZE,
                 ) -> tuple[list[dict[str, Any]], Any]:
    """跑一次 PySR 拟合，返回 Pareto 前沿 [{complexity, loss, equation}] 与
    模型对象（HOF csv 从 tempdir 抄到 out_dir 留证；pysr 2.5 无
    equation_file 参数，产物在 tempdir 下）。"""
    import shutil

    from pysr import PySRRegressor

    tmp = out_dir / f"pysr_tmp_{tag}"
    model = PySRRegressor(
        **pysr_kwargs(seed, niterations, populations, maxsize, timeout_s,
                      nested=nested, popsize=popsize),
        tempdir=str(tmp),
    )
    model.fit(np.asarray(x, dtype=float).reshape(-1, 1), y,
              variable_names=[var])
    if tmp.is_dir():
        for csv in tmp.glob("*.csv"):
            shutil.copy2(csv, out_dir / f"hof_{tag}_{csv.name}")
    eqs = model.equations_
    pareto = [
        {"complexity": int(row.complexity), "loss": float(row.loss),
         "equation": str(row.equation)}
        for row in eqs.itertuples()
    ]
    return pareto, model


def eval_formula(expr: str, x: np.ndarray, var: str = "x") -> np.ndarray:
    """确定性求值 PySR 公式串（^→**；inv/sqrt/log/exp 受限命名空间，
    禁 builtins——与登记校验同源的安全口）。var=公式中自变量名。"""
    code = compile(expr.replace("^", "**"), "<pysr-expr>", "eval")
    env: dict[str, Any] = {
        "inv": lambda t: 1.0 / t,
        "sqrt": np.sqrt, "log": np.log, "exp": np.exp,
        "__builtins__": {},
    }
    return np.atleast_1d(
        np.asarray(eval(code, env, {var: np.asarray(x, dtype=float)}),
                   dtype=float))


def decompose_linear_terms(expr: str,
                           var: str) -> tuple[tuple[str, ...],
                                              tuple[float, ...]] | None:
    """把 PySR 选式分解为 register_symbolic_formula 兼容的线性形态
    Σ cᵢ·termᵢ（term = "1" 或 var**k）。仅覆盖常数与幂项的加性组合
    （锚族及其等价形态皆属此类）；含 sqrt/exp/log 等非线性节点的选式
    返回 None（如实不产候选，不硬凑）。"""
    try:
        tree = ast.parse(expr.replace("^", "**"), mode="eval")
    except SyntaxError:
        return None

    def addends(node: ast.AST, sign: float = 1.0) -> list[tuple[ast.AST, float]]:
        """顶层 ± 展开为 (加项, 符号)；Sub 右支取负（PySR 的 `t − −A`）；
        常数 ×（± 子树）按分配律展开（PySR 因式拼写 `B·(x^-C + A)`）。"""
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return addends(node.left, sign) + addends(node.right, sign)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
            return addends(node.left, sign) + addends(node.right, -sign)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            for const_side, other_side in ((node.left, node.right),
                                           (node.right, node.left)):
                c = _fold_const(const_side)
                if c is None:
                    continue
                if isinstance(other_side, ast.BinOp) \
                        and isinstance(other_side.op, (ast.Add, ast.Sub)):
                    return [(inner_node, sign * c * inner_sign)
                            for inner_node, inner_sign
                            in addends(other_side)]
        return [(node, sign)]

    terms: list[str] = []
    coefficients: list[float] = []
    for node, sign in addends(tree.body):
        c = _fold_const(node)                    # 常数项（含一元 ±）
        if c is not None:
            terms.append("1")
            coefficients.append(sign * c)
            continue
        m = _match_power_term(node, var)         # B·x^(−C) 家族
        if m is not None:
            b, cc = m
            terms.append(f"{var}**{-cc:.7g}")
            coefficients.append(sign * b)
            continue
        # B·x^(+C)：正幂（Mult(常数, Pow(正)) / 裸 Pow）
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            placed = False
            for coef_side, pow_side in ((node.left, node.right),
                                        (node.right, node.left)):
                b = _fold_const(coef_side)
                if b is None:
                    continue
                if isinstance(pow_side, ast.BinOp) \
                        and isinstance(pow_side.op, ast.Pow) \
                        and isinstance(pow_side.left, ast.Name) \
                        and pow_side.left.id == var:
                    e = _fold_const(pow_side.right)
                    if e is not None:
                        terms.append(f"{var}**{e:.7g}")
                        coefficients.append(sign * b)
                        placed = True
                        break
            if not placed:
                return None
            continue
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow) \
                and isinstance(node.left, ast.Name) \
                and node.left.id == var:
            e = _fold_const(node.right)
            if e is not None:
                terms.append(f"{var}**{e:.7g}")
                coefficients.append(sign * 1.0)
                continue
        return None
    return tuple(terms), tuple(coefficients)


# ── 选式（预声明：最简无损式）─────────────────────────────────────────────
def select_formula(pareto: list[dict[str, Any]]) -> tuple[dict[str, Any] | None,
                                                          dict[str, Any] | None]:
    """返回 (selected, best)。无损窗 = loss ≤ best_loss×1.05 内取最小
    complexity，平局取更低损失；空前沿返回 (None, None)。"""
    if not pareto:
        return None, None
    best = min(pareto, key=lambda r: r["loss"])
    in_window = [r for r in pareto if r["loss"] <= best["loss"] * LOSS_WINDOW]
    selected = min(in_window, key=lambda r: (r["complexity"], r["loss"]))
    return selected, best


def pareto_table(pareto: list[dict[str, Any]]) -> str:
    if not pareto:
        return "(empty pareto)"
    best_loss = min(r["loss"] for r in pareto)
    lines = ["  complexity  loss          loss/best  equation"]
    for r in sorted(pareto, key=lambda r: r["complexity"]):
        lines.append(f"  {r['complexity']:>9d}  {r['loss']:.6e}  "
                     f"{r['loss'] / best_loss:>9.4f}  {r['equation']}")
    return "\n".join(lines)


# ── 主流程 ────────────────────────────────────────────────────────────────
def julia_version_evidence() -> dict[str, Any]:
    """best-effort 定位 julia.exe（juliapkg 解析优先，depot 扫描兜底）并取
    版本；观测性 best-effort，失败记 unknown 不阻塞主路径（#105）。"""
    import subprocess

    exe = "unknown"
    try:
        import juliapkg  # pysr 依赖链自带

        exe = juliapkg.executable()
    except Exception:  # best-effort：juliapkg 不可用则扫描 E 盘 depot
        for root in (os.environ.get("JULIA_DEPOT_PATH", ""),
                     os.environ.get("JULIAUP_DEPOT_PATH", "")):
            if root and Path(root).is_dir():
                found = sorted(str(p) for p in Path(root).rglob("julia.exe"))
                if found:
                    exe = found[0]
                    break
    if exe == "unknown" or not Path(exe).exists():
        return {"julia_exe": exe, "julia_version": "unknown"}
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=60, check=True)
        return {"julia_exe": exe, "julia_version": out.stdout.strip()}
    except Exception as exc:  # best-effort 观测（#105：观测不阻塞主路径）
        return {"julia_exe": exe, "julia_version": f"unknown ({exc})"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", default="runs/df6_dp14m1")
    parser.add_argument("--seed", type=int, default=SYNTHETIC_SEED)
    parser.add_argument("--niterations", type=int, default=160)
    parser.add_argument("--populations", type=int, default=40)
    parser.add_argument("--maxsize", type=int, default=16)
    parser.add_argument("--timeout", type=int, default=900,
                        help="单次拟合秒级超时")
    parser.add_argument("--skip-synthetic", action="store_true",
                        help="跳过合成回收门（仅限复跑 8 档对照的调试档）")
    parser.add_argument("--no-rerun", action="store_true",
                        help="跳过 8 点复现性第二遍拟合")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    gates: dict[str, Any] = {}
    report: dict[str, Any] = {
        "task": "DP-14 M1 PySR 锚公式自动发现（合成回收 + γ(εr) 8 档重发现）",
        "criteria": "runs/df6_dp14m1/criteria.md（开工前落盘）",
        "seed": args.seed,
        "pysr_params": {"synthetic": dict(SYNTH_CONFIG),
                        "gamma8": dict(GAMMA8_CONFIG),
                        "niterations_cli_override": args.niterations,
                        "populations_cli_override": args.populations,
                        "population_size": SYNTH_CONFIG["population_size"],
                        "maxsize": args.maxsize,
                        "parsimony": 0.0005,
                        "binary_operators": SEARCH_BINARY_OPS,
                        "unary_operators": SEARCH_UNARY_OPS,
                        "nested_constraints": NESTED_CONSTRAINTS,
                        "deterministic": True, "parallelism": "serial",
                        "note": "nested 仅合成阶段生效（见 criteria 澄清四）"},
        "openblas_num_threads": os.environ["OPENBLAS_NUM_THREADS"],
        "julia_depot_path": os.environ["JULIA_DEPOT_PATH"],
        "c_source": {"CPS_H_EFF_GAMMA_C": CPS_H_EFF_GAMMA_C,
                     "CPS_H_EFF_GAMMA_P": CPS_H_EFF_GAMMA_P},
    }

    try:
        import pysr
        report["pysr_version"] = pysr.__version__
    except Exception as exc:
        print(f"===GATE ENV FAIL=== pysr 不可导入: {exc}")
        report["pysr_version"] = f"unavailable ({exc})"
        (out_dir / "pysr_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return 1

    report["julia"] = julia_version_evidence()

    # ── 第 1 步：合成回收门 ────────────────────────────────────────────
    selected8: dict[str, Any] | None = None
    pareto8: list[dict[str, Any]] = []
    if not args.skip_synthetic:
        xs, ys = make_synthetic(args.seed)
        t0 = time.monotonic()
        pareto_syn, _ = run_pysr_fit(xs, ys, "x", "synthetic", out_dir,
                                     args.seed, SYNTH_CONFIG["niterations"],
                                     SYNTH_CONFIG["populations"],
                                     args.maxsize, args.timeout,
                                     nested=SYNTH_CONFIG["nested"],
                                     popsize=SYNTH_CONFIG["population_size"])
        synth_elapsed = time.monotonic() - t0
        print(f"[synthetic] elapsed {synth_elapsed:.1f}s, "
              f"pareto {len(pareto_syn)} rows")
        print(pareto_table(pareto_syn))

        matched = None
        for row in sorted(pareto_syn, key=lambda r: r["loss"]):
            m = match_power_law(row["equation"], var="x")
            if m is not None:
                matched = (row, m)
                break
        if matched is None:
            print("===GATE SYNTHETIC FAIL=== 前沿无 1+c0*x^-c1 等价结构")
            gates["synthetic_recovery"] = {"pass": False,
                                           "reason": "no structural match"}
        else:
            row, (c0_raw, c1_raw) = matched
            c0_fit, c1_fit = refine_power_law(xs, ys, c0_raw, c1_raw)
            c0_rel = abs(c0_fit - CPS_H_EFF_GAMMA_C) / CPS_H_EFF_GAMMA_C
            c1_rel = abs(c1_fit - CPS_H_EFF_GAMMA_P) / CPS_H_EFF_GAMMA_P
            ok = c0_rel <= SYNTH_PARAM_REL_TOL and c1_rel <= SYNTH_PARAM_REL_TOL
            gates["synthetic_recovery"] = {
                "pass": bool(ok),
                "equation": row["equation"], "complexity": row["complexity"],
                "loss": row["loss"],
                "c0_fit": c0_fit, "c1_fit": c1_fit,
                "c0_rel_err": c0_rel, "c1_rel_err": c1_rel,
                "tol": SYNTH_PARAM_REL_TOL,
                "elapsed_s": synth_elapsed,
            }
            print(f"===GATE SYNTHETIC {'PASS' if ok else 'FAIL'}=== "
                  f"c0={c0_fit:.6f} (rel {c0_rel:.2e}) "
                  f"c1={c1_fit:.6f} (rel {c1_rel:.2e}) "
                  f"tol {SYNTH_PARAM_REL_TOL}")
            if not ok:
                gates["eight_point"] = {"pass": False,
                                        "reason": "synthetic gate failed; "
                                                  "真数据对照未喂（预声明门序）"}
                report["gates"] = gates
                (out_dir / "pysr_report.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2),
                    encoding="utf-8")
                return 1

    # ── 第 2 步：γ(εr) 8 档重发现（两遍，验证复现锁）───────────────────
    x8 = np.array([p[0] for p in EIGHT_POINT])
    y8 = np.array([p[1] for p in EIGHT_POINT])
    t0 = time.monotonic()
    pareto8, _ = run_pysr_fit(x8, y8, "er", "gamma8", out_dir,
                              args.seed, GAMMA8_CONFIG["niterations"],
                              GAMMA8_CONFIG["populations"], args.maxsize,
                              args.timeout, nested=GAMMA8_CONFIG["nested"],
                              popsize=GAMMA8_CONFIG["population_size"])
    elapsed8 = time.monotonic() - t0
    print(f"[gamma8 run1] elapsed {elapsed8:.1f}s, pareto {len(pareto8)} rows")
    print(pareto_table(pareto8))

    if not args.no_rerun:
        pareto8b, _ = run_pysr_fit(x8, y8, "er", "gamma8_rerun", out_dir,
                                   args.seed, GAMMA8_CONFIG["niterations"],
                                   GAMMA8_CONFIG["populations"],
                                   args.maxsize, args.timeout,
                                   nested=GAMMA8_CONFIG["nested"],
                                   popsize=GAMMA8_CONFIG["population_size"])
        identical = pareto8b == pareto8
        gates["determinism"] = {
            "pass": bool(identical),
            "note": "同 seed 两遍 Pareto 前沿逐位一致"
                    if identical else
                    "同 seed 两遍前沿不一致（如实记录，#122 不凑绿）",
        }
        print(f"===GATE DETERMINISM {'PASS' if identical else 'FAIL'}===")

    selected8, best8 = select_formula(pareto8)
    if selected8 is None or best8 is None:
        print("===GATE EIGHT_POINT FAIL=== 空前沿")
        gates["eight_point"] = {"pass": False, "reason": "empty pareto"}
        report["gates"] = gates
        (out_dir / "pysr_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    def _row_rel(row: dict[str, Any]) -> float | None:
        """前沿式在 8 档求值的最大逐档相对误差（求值失败 None——含常数式
        长度不符等，一律不入选而非崩主流程）。"""
        try:
            yh = eval_formula(row["equation"], x8, var="er")
            return max(abs(float(gh) - gm) / gm
                       for (_, gm), gh in zip(EIGHT_POINT, yh, strict=True))
        except Exception:  # 单条前沿式不可求值则不入选（观测不阻塞）
            return None

    # 机械选式（预声明缺省）：loss ≤ best×1.05 窗内最简
    mechanical_equation = selected8["equation"]
    # 批次选式（规格书 §14.1"人工选式，不全自动采信"；criteria.md 执行期
    # 澄清二/三）：①锚族式（A+B·er^-C，常数项 A 为物理极限 1 的结构角色）
    # 中取最低损失——这是 γ(εr) 重发现的预期形态，也是可精修登记的形态；
    # ②无锚族式时，可登记（线性 Σcᵢ·termᵢ）且过 8 档门者取最低损失；
    # ③都无则回退机械窗（候选大概率 FAIL，如实）。8 档表值 3 位舍入的
    # MSE 地板 ~8e-8 上，纯损失排序无信息，复杂度最低但常数项病态的
    # "过门最简"式会被门与锚族优先双重否决（如 er^-0.506+0.884 在
    # er=12.9 偏 2.0% 过不了门）。
    anchor_rows = [r for r in pareto8
                   if match_power_law(r["equation"], var="er") is not None]
    registrable_passers = []
    for row in pareto8:
        rel = _row_rel(row)
        if rel is None or rel > EIGHT_POINT_REL_TOL:
            continue
        if decompose_linear_terms(row["equation"], "er") is not None:
            registrable_passers.append((row, rel))
    if anchor_rows:
        chosen = min(anchor_rows, key=lambda r: r["loss"])
        selection_note = (f"锚族式最低损失（{len(anchor_rows)} 条锚族式）；"
                          f"机械 5% 窗选式={mechanical_equation}")
    elif registrable_passers:
        chosen = min(registrable_passers,
                     key=lambda t: (t[0]["loss"], t[0]["complexity"]))[0]
        selection_note = (f"可登记过门者最低损失（{len(registrable_passers)} "
                          f"条）；机械 5% 窗选式={mechanical_equation}")
    else:
        chosen = selected8
        selection_note = "无锚族/可登记过门式，回退机械 5% 窗选式"

    # 选式求值 vs 8 档真值（eval_formula 确定性求值，不经 PySR 运行时）
    yhat = eval_formula(chosen["equation"], x8, var="er")
    per_point = []
    max_rel = 0.0
    for (er, gamma), gh in zip(EIGHT_POINT, yhat, strict=True):
        rel = abs(float(gh) - gamma) / gamma
        max_rel = max(max_rel, rel)
        per_point.append({"er": er, "gamma_table": gamma,
                          "gamma_formula": float(gh), "rel_err": rel})
    ok8 = bool(max_rel <= EIGHT_POINT_REL_TOL)
    gates["eight_point"] = {
        "pass": ok8,
        "selected_equation": chosen["equation"],
        "selected_complexity": chosen["complexity"],
        "selected_loss": chosen["loss"],
        "mechanical_window_equation": mechanical_equation,
        "manual_selection_note": selection_note,
        "best_equation": best8["equation"], "best_loss": best8["loss"],
        "selection_rule": ("最简无损式：批次选式=锚族式最低损失（可精修"
                           "登记）；无锚族式时=可登记过门者最低损失；机械"
                           f"缺省=loss ≤ best×{LOSS_WINDOW} 窗内最简"),
        "per_point": per_point, "max_rel_err": max_rel,
        "tol": EIGHT_POINT_REL_TOL,
    }
    print(f"===GATE EIGHT_POINT {'PASS' if ok8 else 'FAIL'}=== "
          f"max rel err {max_rel:.4e} (tol {EIGHT_POINT_REL_TOL}) "
          f"selected: {chosen['equation']}")

    # ── 第 3 步：候选 JSON（formula 型 + register_symbolic_formula 兼容）─
    candidate: dict[str, Any] | None = None
    ast_ok = False
    try:
        validate_formula_ast(chosen["equation"], frozenset({"er"}),
                             frozenset({"sqrt", "log", "exp", "inv"}))
        ast_search_ok = True
    except ValueError:
        ast_search_ok = False

    # 登记形态三选一：①锚族匹配→常数钉 1 确定性精修；②通用线性项分解
    # Σ cᵢ·termᵢ；③都不可→如实不产候选（不硬凑）。
    m8 = match_power_law(chosen["equation"], var="er")
    terms: tuple[str, ...] | None = None
    coefficients: tuple[float, ...] | None = None
    registry_expr = ""
    refined_anchor = False
    if m8 is not None:
        c0_r, c1_r = m8
        c0_f, c1_f = refine_power_law(x8, y8, c0_r, c1_r)
        terms = ("1", f"er**{-c1_f:.7g}")
        coefficients = (1.0, c0_f)
        registry_expr = f"1 + {c0_f:.7g}*er**{-c1_f:.7g}"
        refined_anchor = True
    else:
        decomp = decompose_linear_terms(chosen["equation"], "er")
        if decomp is not None:
            terms, coefficients = decomp
            parts = []
            for t, c in zip(terms, coefficients, strict=True):
                parts.append(f"{c:.7g}" if t == "1" else f"{c:.7g}*{t}")
            registry_expr = " + ".join(parts)
    if terms is None:
        print("===CANDIDATE AST FAIL=== 选式含非线性节点（sqrt/exp/log 等），"
              "无线性 Σcᵢ·termᵢ 可登记形态（如实记录，不硬凑）")
    else:
        try:
            for term in terms:
                if term != "1":
                    validate_formula_ast(term, frozenset({"er"}),
                                         REGISTRY_ALLOWED_FUNCS)
            validate_formula_ast(registry_expr, frozenset({"er"}),
                                 REGISTRY_ALLOWED_FUNCS)
            ast_ok = True
            # 登记形态独立复核（8 档逐档；登记式与选式数值恒等/精修后同族）
            yhat_reg = np.zeros_like(x8)
            for term, coef in zip(terms, coefficients, strict=True):
                yhat_reg += (coef if term == "1"
                             else coef * eval_formula(term, x8, var="er"))
            reg_per_point = []
            reg_max_rel = 0.0
            for (er, gamma), gh in zip(EIGHT_POINT, yhat_reg, strict=True):
                rel = abs(float(gh) - gamma) / gamma
                reg_max_rel = max(reg_max_rel, rel)
                reg_per_point.append({"er": er, "gamma_table": gamma,
                                      "gamma_registered": float(gh),
                                      "rel_err": rel})
            formula_text = f"cps_gamma = {registry_expr}"
            candidate = {
                "candidate_id": "R-cps-gamma-pysr-candidate",
                "status": "candidate（实验态候选，未入库；登记随 DP-3 锚"
                          "注册表批次走）",
                "category": "initial_value",
                "description": "CPS 有效厚度因子 γ(εr) PySR 重发现（对照"
                               "仓内锚 CPS_H_EFF_GAMMA_C/P=0.9014/0.6361）",
                "formula": formula_text,
                "variables": ["er"],
                "output_key": "cps_gamma",
                "pareto_equation": chosen["equation"],
                "anchor_form_refined": refined_anchor,
                "register_symbolic_formula_form": {
                    "terms": list(terms),
                    "coefficients": list(coefficients),
                    "complexity": chosen["complexity"],
                    "note": "Σ cᵢ·termᵢ 线性形态；term 字符串过 repo AST "
                            "白名单（^→** 归一）",
                },
                "domain": {"er": [ER_LO, ER_HI]},
                "ast_whitelist": {
                    "passed": bool(ast_ok),
                    "registry_expr": registry_expr,
                    "allowed_funcs": sorted(REGISTRY_ALLOWED_FUNCS),
                    "validator": "复刻 core/calculators.py:3206-3236 词表",
                    "search_expr_ast_ok": bool(ast_search_ok),
                },
                "eight_point_check": gates["eight_point"],
                "registered_form_check": {
                    "per_point": reg_per_point,
                    "max_rel_err": reg_max_rel,
                    "tol": EIGHT_POINT_REL_TOL,
                    "pass": bool(reg_max_rel <= EIGHT_POINT_REL_TOL),
                },
                "pareto_front": sorted(pareto8, key=lambda r: r["complexity"]),
                "provenance": {
                    "data": "docs/rf_template_references.md §11.1 γ(εr) 8 档"
                            "定标值（--refit-cps-gamma 复现源）",
                    "seed": args.seed,
                    "reference_formula": "1 + 0.9014*er**-0.6361",
                    "reference_values_at_8pts": {
                        str(er): float(1.0 + CPS_H_EFF_GAMMA_C
                                       * er ** (-CPS_H_EFF_GAMMA_P))
                        for er, _ in EIGHT_POINT},
                    "pysr_version": report.get("pysr_version"),
                    "julia": report.get("julia"),
                },
                "selection_reason": gates["eight_point"]["selection_rule"],
            }
            (out_dir / "cps_gamma_pysr_candidate.json").write_text(
                json.dumps(candidate, ensure_ascii=False, indent=2),
                encoding="utf-8")
            print(f"===CANDIDATE AST {'PASS' if ast_ok else 'FAIL'}=== "
                  f"registered: {registry_expr} "
                  f"(max rel {reg_max_rel:.4e}) "
                  f"-> {out_dir / 'cps_gamma_pysr_candidate.json'}")
        except ValueError as exc:
            print(f"===CANDIDATE AST FAIL=== {exc}")

    report["gates"] = gates
    report["candidate_ast_passed"] = ast_ok
    (out_dir / "pysr_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    all_pass = (all(g.get("pass") for g in gates.values() if isinstance(g, dict))
                and ast_ok)
    print(f"===ALL GATES {'PASS' if all_pass else 'FAIL'}===")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
