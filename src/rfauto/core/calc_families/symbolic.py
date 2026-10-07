"""E13 符号归纳公式登记（实验态默认关；import 期注册 patch_f0_symbolic_e13）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rfauto.core.symbolic_fit import CandidateFormula

from .registry import CALCULATOR_REGISTRY, CalculatorRegistry, CalculatorSpec

# ─── E13 符号归纳公式登记（experimental 默认关，W1⑨ 2026-09-16 用户口径）─────
# 用户决定（2026-09-16）：所有符号回归归纳公式入库但**默认关**、显式开关才用
# （TODO「0-用户口径（2026-09-16）」②）。机制：register_symbolic_formula 把
# symbolic_fit 的 CandidateFormula 一律以 experimental=True 登记进注册表——
# names()/describe() 默认不列、service 运行默认拒绝（run_calculator 显式
# allow_experimental=True，或 configs/settings.yaml 的
# calculators.allow_experimental: true 放行）。人工审核晋级（§10.5 E13 口径）
# 是另一个显式动作：以 register_calculator(experimental=False) 重登记正式键，
# 本机制不提供自动晋级。
# 求值安全（铁律 6/7 同源）：项字符串只允许 build_library 词表能产出的语法
# （常量/已声明变量/+-*/、幂、sqrt/log），ast 白名单校验后才 eval——拒绝任何
# 经 term 字符串进入的任意代码；系数只来自记录产物（runs）或确定性重拟合。

_ALLOWED_SYMBOLIC_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
_ALLOWED_SYMBOLIC_FUNCS = frozenset({"sqrt", "log"})


def _validate_symbolic_node(node: ast.AST, allowed_names: frozenset[str]) -> None:
    """递归校验公式语法树：只允许数值常量、已声明变量、四则/幂、一元 ±、
    sqrt/log 单参调用；其余节点一律 ValueError（显式，不静默降级）。"""
    if isinstance(node, ast.Expression):
        _validate_symbolic_node(node.body, allowed_names)
        return
    if (isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)):
        return
    if isinstance(node, ast.Name) and node.id in allowed_names:
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_SYMBOLIC_BINOPS):
        _validate_symbolic_node(node.left, allowed_names)
        _validate_symbolic_node(node.right, allowed_names)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        _validate_symbolic_node(node.operand, allowed_names)
        return
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _ALLOWED_SYMBOLIC_FUNCS
            and not node.keywords and len(node.args) == 1):
        _validate_symbolic_node(node.args[0], allowed_names)
        return
    raise ValueError(
        f"归纳公式项含不允许的语法节点: {type(node).__name__}"
        "（只允许常量/已声明变量/四则幂/sqrt/log——build_library 词表口径）")


def _compile_symbolic_terms(
    terms: Sequence[str], allowed_names: frozenset[str],
) -> list[Any]:
    """把归纳式各项编译为可求值代码对象（^→** 后 ast 白名单校验）。

    返回与 terms 等长的列表：None 表示常数项 1（build_library 的常数列），
    否则为 compile 后的表达式（eval 时配 sqrt/log 环境）。
    """
    compiled: list[Any] = []
    for term in terms:
        if term == "1":
            compiled.append(None)
            continue
        tree = ast.parse(term.replace("^", "**"), mode="eval")
        _validate_symbolic_node(tree, allowed_names)
        compiled.append(compile(tree, f"<symbolic:{term}>", "eval"))
    return compiled


def _eval_symbolic_terms(compiled: Sequence[Any], coefficients: Sequence[float],
                         namespace: Mapping[str, float]) -> float:
    """确定性求值 Σ cᵢ·termᵢ（纯 float 闭式；sqrt/log 来自 math）。"""
    env = {"sqrt": math.sqrt, "log": math.log, "__builtins__": {}}
    total = 0.0
    for code, coef in zip(compiled, coefficients, strict=True):
        term_value = 1.0 if code is None else float(eval(code, env, dict(namespace)))
        total += float(coef) * term_value
    return total


def register_symbolic_formula(
    candidate: CandidateFormula,
    key: str,
    *,
    variables: Sequence[str],
    param_names: Sequence[str] | None = None,
    output_key: str = "y",
    provenance: str = "",
    domain: Mapping[str, tuple[float, float]] | None = None,
    description: str | None = None,
    registry: CalculatorRegistry | None = None,
) -> str:
    """把 symbolic_fit 的 CandidateFormula 以 experimental=True 登记进注册表。

    后续一切自动归纳公式统一走本入口（一律实验态、默认关，见节首口径块）。
    - variables：项字符串里出现的变量名（build_library 词表口径，如 L_mm）；
    - param_names：计算器入参名（缺省=variables 原名；用于把库内变量名映射到
      注册表参数命名惯例，如 L_mm→l_mm）；
    - output_key：返回 dict 的量名（如 f0_ghz）；
    - provenance：出处串（数据集 id/点数/种子/rmse/裁判结论），进 description
      与每次返回值——系数必须可溯源（记录产物或确定性重拟合，铁律 7）；
    - domain：{入参名: (lo, hi)} 适用域——拟合数据范围外显式报错（外推未验证，
      不保证）。
    重名注册照常 ValueError；返回注册键名。
    """
    from rfauto.core.symbolic_fit import format_formula

    if len(set(variables)) != len(variables):
        raise ValueError(f"variables 有重复: {tuple(variables)}")
    pnames = tuple(param_names) if param_names is not None else tuple(variables)
    if len(pnames) != len(variables):
        raise ValueError("param_names 与 variables 长度不一致")
    terms = tuple(str(t) for t in candidate.terms)
    coefficients = tuple(float(c) for c in candidate.coefficients)
    if len(terms) != len(coefficients):
        raise ValueError("terms 与 coefficients 长度不一致")
    formula_text = format_formula(terms, coefficients, name=output_key)
    if description is None:
        description = (f"符号回归归纳公式（实验态，默认关闭）：{formula_text}。"
                       f"{provenance}")
    compiled = _compile_symbolic_terms(terms, frozenset(variables))
    domain_map: dict[str, tuple[float, float]] = dict(domain or {})
    if not set(domain_map) <= set(pnames):
        raise ValueError(
            f"domain 的键必须是入参名 {list(pnames)}，"
            f"收到 {sorted(domain_map)}")

    def func(**kwargs: float) -> dict[str, Any]:
        known = set(pnames)
        unknown = [k for k in kwargs if k not in known]
        if unknown:
            raise TypeError(f"未知参数: {unknown}（该计算器需要: {sorted(known)}）")
        ns: dict[str, float] = {}
        for var, pname in zip(variables, pnames, strict=True):
            if pname not in kwargs:
                raise ValueError(f"缺少参数: {pname}")
            v = float(kwargs[pname])
            if not math.isfinite(v):
                raise ValueError(f"{pname} 必须为有限数")
            ns[var] = v
        for pname, (lo, hi) in domain_map.items():
            v = float(kwargs[pname])
            if not lo <= v <= hi:
                raise ValueError(
                    f"{pname}={v} 超出归纳式适用域 [{lo}, {hi}]"
                    "（拟合数据范围外不保证，外推未验证）")
        value = _eval_symbolic_terms(compiled, coefficients, ns)
        return {output_key: round(value, 9),
                "formula": formula_text,
                "provenance": provenance,
                "note": "实验性归纳公式：对观测数据的最小二乘近似，不含物理"
                        "推导；默认关闭，需显式开关；适用域外不保证"}

    target = registry if registry is not None else CALCULATOR_REGISTRY
    params = tuple(
        (pname, f"float - 归纳变量 {var}（适用域/出处见 description）")
        for var, pname in zip(variables, pnames, strict=True))
    target.register(CalculatorSpec(
        name=key, description=description, func=func, params=params,
        required=pnames, experimental=True))
    return key


# E13 patch 基模谐振候选公式（2026-09-12；系数与误差逐位
# 取自产物 runs/symbolic_fit/patch_f0.json 的 induced.best）：
#   f0 = 0.0261448 + 75.1834/L + 0.0162789·L/W  （GHz；L/W 单位 mm）
# 51 真实 openEMS patch 点（L∈[35,45]、W∈[40,60]、er=3.66、h=0.508 恒定），
# holdout 每 5 留 1：rmse_holdout=0.001773GHz、r2_train=0.999889；独立裁判
# vs Hammerstad/HJ（patch_resonance_hj_ghz，#118 不自证）：mean −0.699%、
# max|dev|=0.765% ≤ 2% PASS。er/h 在数据集上恒定 → 本式不含 er/h
# （不可辨识），仅适用该基底；适用域外显式报错。实验态登记（默认关）。

def _register_e13_patch_f0() -> str:
    from rfauto.core.symbolic_fit import CandidateFormula

    return register_symbolic_formula(
        CandidateFormula(
            terms=("1", "1/L_mm", "L_mm/W_mm"),
            coefficients=(0.026144821820511657, 75.18344519064581,
                          0.0162789352212073),
            complexity=8,
            mse_train=1.3517603341483583e-06,
            rmse_train=0.0011626522842829487,
            r2_train=0.9998889118662188,
            mse_holdout=3.144626978633213e-06,
            rmse_holdout=0.0017733096116113545,
        ),
        "patch_f0_symbolic_e13",
        variables=("L_mm", "W_mm"),
        param_names=("l_mm", "w_mm"),
        output_key="f0_ghz",
        provenance=(
            "E13（runs/symbolic_fit/patch_f0.json）：数据集 "
            "patch_antenna_openems_campaign，51 真实 openEMS 点"
            "（L∈[35,45]mm、W∈[40,60]mm、er=3.66、h=0.508），基模=[1.3,2.7]GHz"
            " 最低频 ≥3dB 局部谷；holdout 每 5 留 1，rmse_holdout=0.001773GHz、"
            "r2_train=0.999889；独立裁判 vs Hammerstad/HJ mean −0.699%、"
            "max|dev|=0.765%≤2% PASS"),
        domain={"l_mm": (35.0, 45.0), "w_mm": (40.0, 60.0)},
    )


_register_e13_patch_f0()
