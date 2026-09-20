"""PCell 几何 DSL（声明式参数化单元语言，YAML/Python 双面）。

设计目标："既有模板迁移到 DSL，冒烟结果等价"。
语言形态 = 声明式参数化单元（Parameterized Cell）：参数（带边界）→
派生量（表达式）→ 盒原语列表（每面坐标是参数表达式）。

生态复用口径：gdsfactory/KLayout 未进本仓
venv（GDS 读写/DRC 属文件互操作层），本模块是几何参数化内核——
只做"参数 → 盒坐标"的确定性求值，不碰 GDS/版图文件格式，与上述
生态无功能重叠；等价性裁判 = 既有渲染器几何段（#212 审计模式）。

数值只在确定性内核：表达式经 AST 白名单求值（四则/幂/
min/max/abs），无 eval、无外部调用面；LLM 只产出 DSL 文本，数值
全部由本内核从参数确定性导出。

用法（Python 面）：
    from rfauto.core.pcell_dsl import get_pcell, evaluate_pcell
    geo = evaluate_pcell(get_pcell("mline"), {"w_mm": 1.113},
                         context={"H_SUB": 5.08e-4, "BOARD": 0.06})
    geo.boxes[0].lo  # 归一化包围盒下角（与参数同单位域）

用法（YAML 面）：
    name: mline
    params: {w_mm: {default: 1.113}, line_len_mm: {default: 40.0}}
    variables:
      W: w_mm*1e-3
      Y0: -L/2
    boxes:
      - layer: microstrip
        name: line
        start: [-W/2, Y0, H_SUB]
        stop: [W/2, Y1, H_SUB]
        priority: 10
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "PCELL_LIBRARY",
    "PCellBox",
    "PCellBoxGeom",
    "PCellDef",
    "PCellError",
    "PCellExpressionError",
    "PCellGeometry",
    "PCellParam",
    "PCellParamError",
    "evaluate_pcell",
    "get_pcell",
]


class PCellError(ValueError):
    """PCell DSL 基类错误。"""


class PCellExpressionError(PCellError):
    """表达式非法或引用未知名字。"""


class PCellParamError(PCellError):
    """参数缺失/未知/越界。"""


# ─── 安全表达式求值（AST 白名单，确定性内核）───────────────────────────────

_ALLOWED_FUNCS: dict[str, Any] = {"min": min, "max": max, "abs": abs}
_ALLOWED_BINOPS: tuple[type[ast.AST], ...] = (
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
)
_ALLOWED_UNARY: tuple[type[ast.AST], ...] = (ast.USub, ast.UAdd)


def eval_expr(expr: Any, names: dict[str, float]) -> float:
    """白名单 AST 求值：四则/幂/一元正负/min/max/abs + 名字查找。

    expr 为 int/float 时直通（YAML 常量面）；str 才走解析。其它类型
    与一切越界节点（属性访问/下标/比较/调用白名单外函数/lambda/…）
    抛 PCellExpressionError——DSL 面不可执行任意代码。
    """
    if isinstance(expr, bool):
        raise PCellExpressionError(f"表达式不接受布尔值: {expr!r}")
    if isinstance(expr, (int, float)):
        value = float(expr)
        if value != value or value in (float("inf"), float("-inf")):
            raise PCellExpressionError(f"常量非有限: {expr!r}")
        return value
    if not isinstance(expr, str):
        raise PCellExpressionError(f"表达式必须是常量或字符串: {expr!r}")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise PCellExpressionError(f"表达式语法错误: {expr!r}（{exc}）") from exc
    try:
        value = float(_eval_node(tree.body, expr, names))
    except ZeroDivisionError as exc:
        raise PCellExpressionError(f"表达式 {expr!r} 除零") from exc
    except OverflowError as exc:
        raise PCellExpressionError(f"表达式 {expr!r} 数值溢出") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise PCellExpressionError(f"表达式结果非有限: {expr!r} → {value}")
    return value


def _eval_node(node: ast.AST, source: str, names: dict[str, float]) -> float:
    if isinstance(node, ast.Constant):
        return eval_expr(node.value, names)
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise PCellExpressionError(
                f"表达式 {source!r} 引用未定义名字: {node.id}")
        return float(names[node.id])
    if isinstance(node, ast.BinOp):
        _require(node.op, _ALLOWED_BINOPS, source, "二元运算")
        left = _eval_node(node.left, source, names)
        right = _eval_node(node.right, source, names)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        return left ** right  # ast.Pow
    if isinstance(node, ast.UnaryOp):
        _require(node.op, _ALLOWED_UNARY, source, "一元运算")
        operand = _eval_node(node.operand, source, names)
        return -operand if isinstance(node.op, ast.USub) else +operand
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in (
                _ALLOWED_FUNCS):
            raise PCellExpressionError(
                f"表达式 {source!r} 调用了白名单外的函数")
        if node.keywords:
            raise PCellExpressionError(f"表达式 {source!r} 不接受关键字参数")
        args = [_eval_node(a, source, names) for a in node.args]
        return float(_ALLOWED_FUNCS[node.func.id](*args))
    raise PCellExpressionError(
        f"表达式 {source!r} 含不允许的节点: {type(node).__name__}")


def _require(op: ast.AST, allowed: tuple[type[ast.AST], ...],
             source: str, what: str) -> None:
    if not any(isinstance(op, kind) for kind in allowed):
        raise PCellExpressionError(
            f"表达式 {source!r} 的{what}不在白名单: {type(op).__name__}")


# ─── 数据模型 ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PCellParam:
    """PCell 用户参数：默认值 + 可选闭区间边界。"""
    name: str
    default: float
    lo: float | None = None
    hi: float | None = None
    note: str = ""


@dataclass(frozen=True)
class PCellBox:
    """一个盒原语声明：每面坐标是表达式（常量或参数算式字符串）。"""
    layer: str
    start: tuple[Any, Any, Any]
    stop: tuple[Any, Any, Any]
    priority: Any = 10
    name: str = ""


@dataclass(frozen=True)
class PCellDef:
    """一个 PCell 的声明式全集（不可变；YAML/Python 双面共用）。"""
    name: str
    description: str = ""
    params: tuple[PCellParam, ...] = ()
    variables: tuple[tuple[str, Any], ...] = ()  # 派生量，按声明序求值
    boxes: tuple[PCellBox, ...] = ()
    context_names: tuple[str, ...] = ()  # 求值时须由调用方注入的外部常量


@dataclass(frozen=True)
class PCellBoxGeom:
    """求值后的盒原语（lo/hi 为逐轴归一化包围盒，坐标域与参数一致）。"""
    name: str
    layer: str
    start: tuple[float, float, float]
    stop: tuple[float, float, float]
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]
    priority: float


@dataclass(frozen=True)
class PCellGeometry:
    """PCell 求值产物：参数点 + 盒原语列表（确定性、可序列化）。"""
    pcell: str
    params: dict[str, float]
    boxes: tuple[PCellBoxGeom, ...]

    def signature(self, digits: int = 12) -> tuple:
        """几何签名（round 归一），供等价/参数敏感性比对。"""
        return tuple(sorted(
            tuple(round(v, digits) for v in (*b.lo, *b.hi))
            for b in self.boxes
        ))

    def to_dicts(self) -> list[dict[str, Any]]:
        """JSON 友好序列化（service 层进出约定）。"""
        return [
            {"name": b.name, "layer": b.layer,
             "start": list(b.start), "stop": list(b.stop),
             "lo": list(b.lo), "hi": list(b.hi), "priority": b.priority}
            for b in self.boxes
        ]


# ─── 求值 ────────────────────────────────────────────────────────────────────

def evaluate_pcell(
    defn: PCellDef,
    params: dict[str, Any] | None = None,
    context: dict[str, float] | None = None,
) -> PCellGeometry:
    """参数点 → 几何。缺省/越界/未知参数与缺失/未知 context 均显式报错。"""
    values: dict[str, float] = {}
    overrides = dict(params or {})
    declared = {p.name: p for p in defn.params}
    for key in overrides:
        if key not in declared:
            raise PCellParamError(
                f"PCell {defn.name} 未知参数: {key}（可用: {sorted(declared)}）")
    for pname, param in declared.items():
        raw = overrides.get(pname, param.default)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise PCellParamError(
                f"PCell {defn.name} 参数 {pname} 必须是数值，得到 {raw!r}")
        value = float(raw)
        if value != value or value in (float("inf"), float("-inf")):
            raise PCellParamError(f"PCell {defn.name} 参数 {pname} 非有限")
        if param.lo is not None and value < param.lo:
            raise PCellParamError(
                f"PCell {defn.name} 参数 {pname}={value} 低于下界 {param.lo}")
        if param.hi is not None and value > param.hi:
            raise PCellParamError(
                f"PCell {defn.name} 参数 {pname}={value} 高于上界 {param.hi}")
        values[pname] = value

    ctx = dict(context or {})
    missing = [n for n in defn.context_names if n not in ctx]
    if missing:
        raise PCellParamError(
            f"PCell {defn.name} 缺少上下文常量: {missing}（"
            f"如 render 脚手架的 H_SUB/BOARD/NEAR）")
    extra = [n for n in ctx if n not in defn.context_names]
    if extra:
        raise PCellParamError(f"PCell {defn.name} 传入了未声明的上下文: {extra}")
    values.update({k: float(v) for k, v in ctx.items()})

    for var_name, expr in defn.variables:
        if var_name in values:
            raise PCellError(
                f"PCell {defn.name} 派生量 {var_name} 与参数/上下文/更早"
                f"派生量重名")
        values[var_name] = eval_expr(expr, values)

    boxes: list[PCellBoxGeom] = []
    for box in defn.boxes:
        start = tuple(eval_expr(c, values) for c in box.start)
        stop = tuple(eval_expr(c, values) for c in box.stop)
        lo = tuple(min(s, t) for s, t in zip(start, stop, strict=True))
        hi = tuple(max(s, t) for s, t in zip(start, stop, strict=True))
        boxes.append(PCellBoxGeom(
            name=box.name, layer=box.layer,
            start=start, stop=stop, lo=lo, hi=hi,
            priority=eval_expr(box.priority, values),
        ))
    return PCellGeometry(
        pcell=defn.name, params={k: values[k] for k in declared}, boxes=tuple(boxes))


# ─── 序列化（YAML/Python 双面共用同一 dict 形状）──────────────────────────

_EXPR_OBJ_KEYS = ("start", "stop")


def def_to_dict(defn: PCellDef) -> dict[str, Any]:
    """PCellDef → 纯数据 dict（YAML/JSON 双兼容）。"""
    out: dict[str, Any] = {"name": defn.name}
    if defn.description:
        out["description"] = defn.description
    if defn.params:
        out["params"] = {
            p.name: _param_dict(p) for p in defn.params}
    if defn.variables:
        out["variables"] = {k: v for k, v in defn.variables}
    out["boxes"] = [
        {"layer": b.layer, "start": list(b.start), "stop": list(b.stop),
         "priority": b.priority, **({"name": b.name} if b.name else {})}
        for b in defn.boxes
    ]
    if defn.context_names:
        out["context"] = list(defn.context_names)
    return out


def _param_dict(p: PCellParam) -> dict[str, Any]:
    d: dict[str, Any] = {"default": p.default}
    if p.lo is not None:
        d["lo"] = p.lo
    if p.hi is not None:
        d["hi"] = p.hi
    if p.note:
        d["note"] = p.note
    return d


def def_from_dict(data: dict[str, Any]) -> PCellDef:
    """纯数据 dict → PCellDef。形状不对/名字缺失显式报错。"""
    name = data.get("name")
    if not name or not isinstance(name, str):
        raise PCellError(f"PCell 定义缺 name: {data!r}")
    params: list[PCellParam] = []
    for pname, raw in (data.get("params") or {}).items():
        if isinstance(raw, (int, float)):
            params.append(PCellParam(name=pname, default=float(raw)))
            continue
        if not isinstance(raw, dict):
            raise PCellError(f"PCell {name} 参数 {pname} 形状非法: {raw!r}")
        params.append(PCellParam(
            name=pname,
            default=float(raw.get("default", 0.0)),
            lo=raw.get("lo"),
            hi=raw.get("hi"),
            note=str(raw.get("note", "")),
        ))
    variables = tuple((k, v) for k, v in (data.get("variables") or {}).items())
    boxes: list[PCellBox] = []
    for raw in data.get("boxes") or []:
        for key in _EXPR_OBJ_KEYS:
            if len(raw.get(key) or ()) != 3:
                raise PCellError(
                    f"PCell {name} 盒的 {key} 必须是 3 元素: {raw!r}")
        boxes.append(PCellBox(
            layer=str(raw.get("layer", "metal")),
            start=tuple(raw["start"]),
            stop=tuple(raw["stop"]),
            priority=raw.get("priority", 10),
            name=str(raw.get("name", "")),
        ))
    if not boxes:
        raise PCellError(f"PCell {name} 至少需要一个 box 原语")
    return PCellDef(
        name=name,
        description=str(data.get("description", "")),
        params=tuple(params),
        variables=variables,
        boxes=tuple(boxes),
        context_names=tuple(data.get("context") or ()),
    )


def def_to_yaml(defn: PCellDef) -> str:
    return yaml.safe_dump(def_to_dict(defn), allow_unicode=True, sort_keys=False)


def def_from_yaml(path: str | Path) -> PCellDef:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise PCellError(f"PCell YAML 顶层必须是映射: {path}")
    return def_from_dict(data)


# ─── 既有模板迁移库（迁移 3 个既有模板到 DSL）──────────────────
# 坐标表达式与 adapters/openems_templates 的几何段逐字同构（_mline_lines /
# _cpw_lines / _wstep_lines），默认值 = TEMPLATE_NOMINAL 同名条目；
# 冒烟等价由 tests/unit/test_pcell_dsl.py 对渲染器几何段实测钉死。

_CONTEXT_SCAFFOLD = ("H_SUB", "BOARD", "NEAR")  # render 脚手架注入的常量


def _mline_def() -> PCellDef:
    """均匀微带线（mline 锚模板）：一条直带，两端 MSLPort 自画馈线。"""
    return def_from_dict({
        "name": "mline",
        "description": "均匀微带线：单直带金属，端口馈线由 MSLPort 补画",
        "params": {
            "w_mm": {"default": 1.113, "note": "线宽（skrf HJ 综合 50Ω 口径）"},
            "line_len_mm": {"default": 40.0, "note": "两端口间线长"},
        },
        "context": list(_CONTEXT_SCAFFOLD),
        "variables": {
            "W": "w_mm*1e-3", "L": "line_len_mm*1e-3",
            "Y0": "-L/2", "Y1": "L/2",
        },
        "boxes": [
            {"layer": "microstrip", "name": "line",
             "start": ["-W/2", "Y0", "H_SUB"],
             "stop": ["W/2", "Y1", "H_SUB"], "priority": 10},
        ],
    })


def _cpw_def() -> PCellDef:
    """均匀共面波导：中心带 + 两侧地（地延伸到域边，端口段地须自画）。"""
    return def_from_dict({
        "name": "cpw",
        "description": "均匀共面波导：中心带 + 两侧全域地（CPWG 口径）",
        "params": {
            "w_mm": {"default": 0.849, "note": "中心带宽（CPWG 共形映射闭式）"},
            "gap_mm": {"default": 0.2, "note": "缝宽"},
            "line_len_mm": {"default": 40.0, "note": "两端口间线长"},
        },
        "context": list(_CONTEXT_SCAFFOLD),
        "variables": {
            "W": "w_mm*1e-3", "GAP": "gap_mm*1e-3", "L": "line_len_mm*1e-3",
            "Y0": "-L/2", "Y1": "L/2",
        },
        "boxes": [
            {"layer": "cpw", "name": "center",
             "start": ["-W/2", "Y0", "H_SUB"],
             "stop": ["W/2", "Y1", "H_SUB"], "priority": 10},
            {"layer": "cpw", "name": "gnd_left",
             "start": ["-BOARD", "-BOARD", "H_SUB"],
             "stop": ["-W/2-GAP", "BOARD", "H_SUB"], "priority": 10},
            {"layer": "cpw", "name": "gnd_right",
             "start": ["W/2+GAP", "-BOARD", "H_SUB"],
             "stop": ["BOARD", "BOARD", "H_SUB"], "priority": 10},
        ],
    })


def _wstep_def() -> PCellDef:
    """微带宽度阶跃（不连续性基元）：窄段/宽段各半长，单阶在中点。"""
    return def_from_dict({
        "name": "wstep",
        "description": "微带宽度阶跃：窄段/宽段各半长，单阶梯跃在中点",
        "params": {
            "w1_mm": {"default": 1.1134, "note": "窄段线宽（50Ω 口径）"},
            "w2_mm": {"default": 1.897, "note": "宽段线宽（35Ω 口径）"},
            "line_len_mm": {"default": 40.0, "note": "总长"},
        },
        "context": list(_CONTEXT_SCAFFOLD),
        "variables": {
            "W1": "w1_mm*1e-3", "W2": "w2_mm*1e-3", "L": "line_len_mm*1e-3",
            "Y0": "-L/2", "YM": 0.0, "Y1": "L/2",
        },
        "boxes": [
            {"layer": "wstep", "name": "narrow",
             "start": ["-W1/2", "Y0", "H_SUB"],
             "stop": ["W1/2", "YM", "H_SUB"], "priority": 10},
            {"layer": "wstep", "name": "wide",
             "start": ["-W2/2", "YM", "H_SUB"],
             "stop": ["W2/2", "Y1", "H_SUB"], "priority": 10},
        ],
    })


PCELL_LIBRARY: dict[str, PCellDef] = {
    d.name: d for d in (_mline_def(), _cpw_def(), _wstep_def())
}


def get_pcell(name: str) -> PCellDef:
    """按名取迁移库中的 PCell 定义；未知名字列出可用项。"""
    if name not in PCELL_LIBRARY:
        raise KeyError(f"未迁移的 PCell: {name}（可用: {sorted(PCELL_LIBRARY)}）")
    return PCELL_LIBRARY[name]


def evaluate_library(context: dict[str, float],
                     param_sets: Iterable[dict[str, Any]] | None = None
                     ) -> dict[str, PCellGeometry]:
    """整库求值便捷入口（param_sets 按序对应各 PCell，None=全默认）。"""
    sets = list(param_sets) if param_sets is not None else [None] * len(PCELL_LIBRARY)
    return {
        name: evaluate_pcell(defn, params, context)
        for (name, defn), params in zip(PCELL_LIBRARY.items(), sets,
                                        strict=True)
    }
