"""geometry_lint——建模期几何门（T-Q26b，aurora_q 席位 Q-X2）。

来源：晶圆键合空腔传输线外部用户实测反馈
（D:/晶圆键合/rfauto_反馈与实测经验.md §4 质检门表 + §2.2/§2.3，
用户令 2026-11-06 吸收立项）。定位：**solve 之前、零 license 就能跑**
的建模期几何门——补既有六道门"偏数值/物理不变量、缺建模期几何门"
的缺口。HFSS 的三种端口静默失败（反馈 §2.3 形态 A/B/C）与实体部分
相交（反馈 §2.2）都会"正常跑完但结果是垃圾"，validate/solve 阶段
要么报错误导、要么不报。

六检查（反馈 §4 表逐条）：
① port_on_outer_boundary       波端口 sheet 与模型包围盒某面重合；不重合 ERROR
② port_adjacent_solve_inside   端口面 1e-6 邻域内至少一个 solve_inside=True 体；无 ERROR
③ port_cross_section_connectivity 截面按材料栅格化，空气连通域 >1 WARN（多模可豁免）
④ partial_intersection         两两 AABB 相交且非包含 ERROR（vacuum 包裹=合法包含不报）
⑤ metal_aspect_ratio           薄金属最薄边/最长边 <1e-5 WARN（零厚度=已是 sheet 不报）
⑥ variable_units               变量表达式加性位置的无量纲裸数 ERROR（HFSS 按米解释真坑）

形态（任务书 T-Q26b）：输入=声明式几何描述 :class:`LintGeometry`
（box 列表 {name, material, solve_inside, coords} + 端口 sheet + 变量
表达式，model_units 统一）；输出=服务层 JSON 信封
``{"ok", "lint_pass", "issues": [{check, level, objects, message}],
"counts", "model_units", "summary"}``。**零 pyaedt 依赖**——纯几何
AABB/栅格 BFS 连通域与表达式词法分析，零第三方新依赖（pydantic 既有）。

接线（最小侵入，缺省关）：适配器层禁 import service（.importlinter
layers 契约），故 :meth:`hfss_adapter.HfssAdapter.build_and_setup` 的
钩子只消费调用方（顶层/测试/后续 recipe runner）经本模块
:func:`lint_geometry` 预算好的报告信封（键 ok/lint_pass/issues），
ERROR 级问题在 build 出口、configure_setup/solve 之前抛
ModelBuildError 拦截；缺省 ``geometry_lint_report=None`` 零行为变化。
"缺省关+显式开启、默认开启裁决留后续"按任务书登记。

口径细节：
- 坐标/容差单位=model_units（声明式形态内部统一，缺省 mm）；
  邻域/重合容差 1e-6（反馈 §4 表"1e-6 邻域"原口径）。
- 连通域栅格：端口截面按 64×64 胞**保守栅格化**（体截面与胞相交即
  覆盖）——亚胞薄壁金属也能切开空气（反馈 §2.3 形态 C 周长切分），
  代价是亚胞空气缝可能过告警（WARN 不拦截，可接受）。
- 变量单位检查语义：只拦**加性/减性位置**的无量纲裸数与整式裸数
  （``w_s+0.04``、``"0.5"``）——HFSS 把裸数按**米**解释，膜宽
  0.56mm 变 40mm 级报废且无报错（反馈 §4 最后一条真坑）；
  乘除/指数/函数参位的无量纲数（``2*w``、``sqrt(2)``）是合法
  无量纲乘子不拦；已知单位后缀（``0.04mm``）不拦。
- 本模块不带 ``__all__``：按 public_api 快照口径记私有
  （tests/gold/public_api.json 零漂移；金快照对席位禁改）。
"""

from __future__ import annotations

import math
import re
from collections import deque
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfauto.service.envelope import error_envelope, ok_envelope

# ── 口径常量（单位=model_units）─────────────────────────────────────────

#: 端口邻接判定的邻域（反馈 §4 表"端口面 1e-6 邻域"原口径）
PORT_ADJACENCY_TOL = 1e-6
#: 波端口 sheet 与模型包围盒面重合容差
PORT_BOUNDARY_TOL = 1e-6
#: 部分相交判定：三轴重叠均为正的最小值（面贴/层叠重叠=0 不算相交）
INTERSECTION_EPS = 1e-12
#: 包含关系判定容差（AABB 恰好贴边仍算包含）
CONTAINMENT_TOL = 1e-9
#: 端口面与体切向正面积交的最小限（零面积擦边不算邻接）
_TANGENTIAL_EPS = 1e-12
#: 薄金属纵横比门限（反馈 §4 表：最薄边/最长边 <1e-5 WARN）
ASPECT_RATIO_MIN = 1e-5
#: 端口截面连通性栅格密度（每轴胞数；保守栅格化见模块 docstring）
CROSS_SECTION_GRID_N = 64

CheckName = Literal[
    "port_on_outer_boundary",
    "port_adjacent_solve_inside",
    "port_cross_section_connectivity",
    "partial_intersection",
    "metal_aspect_ratio",
    "variable_units",
]

#: 空气/背景类材料名（不阻挡端口截面空气连通性）
_AIR_MATERIALS = {"air", "vacuum", "vac", "free_space", "background", "gas", "void"}
#: 金属材质启发式词元（显式 is_metal 声明优先，见 :func:`is_metal_material`）
_METAL_TOKENS = {
    "metal", "metallic", "pec", "perfect", "conductor", "conduct",
    "gold", "copper", "silver", "aluminum", "aluminium", "brass",
    "solder", "nickel", "chrome", "tin", "titanium", "platinum",
}
#: 单元素符号类金属名（仅整名精确匹配，避免 "alumina" 之类子串误判）
_METAL_EXACT = {"au", "cu", "ag", "al", "mo", "w", "pt", "sn", "fe", "cr", "ni", "ti"}

# ── 声明式几何 schema（构建器产出面）───────────────────────────────────


def _norm_pair(pair: tuple[float, float]) -> tuple[float, float]:
    lo, hi = float(pair[0]), float(pair[1])
    return (lo, hi) if lo <= hi else (hi, lo)


class LintBox(BaseModel):
    """一个三维实体/薄片的声明式包围盒。

    coords = (x_min, y_min, z_min, x_max, y_max, z_max)，model_units。
    零厚度（某轴 lo==hi）=薄片（sheet 形态），纵横比检查自动豁免
    （"建议改 sheet"的 sheet 本身不再告警）。
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    material: str = "vacuum"
    solve_inside: bool = False
    coords: tuple[float, float, float, float, float, float]
    #: 金属判定覆盖：None=按 material 名启发式（见 is_metal_material）
    is_metal: bool | None = None

    @model_validator(mode="after")
    def _normalize(self) -> LintBox:
        c = self.coords
        # 布局 (x_lo, y_lo, z_lo, x_hi, y_hi, z_hi)——归一化必须按本布局
        # 写回且幂等（pydantic 2.14 after-validator 内赋值会再跑一轮）
        x_lo, x_hi = _norm_pair((c[0], c[3]))
        y_lo, y_hi = _norm_pair((c[1], c[4]))
        z_lo, z_hi = _norm_pair((c[2], c[5]))
        self.coords = (x_lo, y_lo, z_lo, x_hi, y_hi, z_hi)
        return self

    def lo(self) -> tuple[float, float, float]:
        return (self.coords[0], self.coords[1], self.coords[2])

    def hi(self) -> tuple[float, float, float]:
        return (self.coords[3], self.coords[4], self.coords[5])

    def extent(self) -> tuple[float, float, float]:
        return (
            self.coords[3] - self.coords[0],
            self.coords[4] - self.coords[1],
            self.coords[5] - self.coords[2],
        )


class LintPortSheet(BaseModel):
    """端口 sheet 的声明式矩形：法向轴 + 面内两轴范围。"""

    model_config = ConfigDict(extra="forbid")

    #: sheet 法向轴（sheet 落在 axis=pos 平面上）
    axis: Literal["x", "y", "z"]
    pos: float
    #: 面内第一轴（axis=x 时 u=y, v=z；y 时 u=x, v=z；z 时 u=x, v=y）
    u: tuple[float, float]
    v: tuple[float, float]

    @model_validator(mode="after")
    def _normalize(self) -> LintPortSheet:
        self.u = _norm_pair(self.u)
        self.v = _norm_pair(self.v)
        return self

    def tangential_axes(self) -> tuple[int, int]:
        """(u 轴, v 轴) 的 0/1/2 序号。"""
        axis = "xyz".index(self.axis)
        return tuple(i for i in range(3) if i != axis)  # type: ignore[return-value]


class LintPort(BaseModel):
    """一个端口的声明式描述。

    kind="wave"（缺省）参与检查①（外边界重合）；"lumped" 为模型内部
    集总口，天然不在域边界，检查①豁免（①②③④⑤照常/按需）。
    multimode=True 声明多模端口，检查③连通性豁免（反馈 §4 表
    "可声明多模豁免"）。
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Literal["wave", "lumped"] = "wave"
    sheet: LintPortSheet
    multimode: bool = False


class LintVariable(BaseModel):
    """一个设计变量表达式（检查⑥输入）。

    dimension：几何长度/角度类变量缺省 "unknown"（执行加性裸数检查）；
    确属无量纲（计数、比例）的变量显式声明 "dimensionless" 豁免。
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    expression: str
    dimension: Literal["length", "angle", "dimensionless", "unknown"] = "unknown"


class LintGeometry(BaseModel):
    """声明式几何描述整体（geometry_lint 唯一输入面）。

    构建器（模型插件/模板/recipe runner）在 solve 前从自身几何参数
    产出；box/port/variable 名各自唯一（重名=输入契约错误）。
    """

    model_config = ConfigDict(extra="forbid")

    model_units: str = "mm"
    boxes: list[LintBox] = Field(default_factory=list)
    ports: list[LintPort] = Field(default_factory=list)
    variables: list[LintVariable] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_names(self) -> LintGeometry:
        for field, items in (("box", self.boxes), ("port", self.ports),
                             ("variable", self.variables)):
            names = [it.name for it in items]
            dup = sorted({n for n in names if names.count(n) > 1})
            if dup:
                raise ValueError(f"重名 {field}: {dup}（LintGeometry 名必须唯一）")
        return self


# ── 材料分类 ───────────────────────────────────────────────────────────


def is_air_material(material: str) -> bool:
    """空气/背景类材料（不阻挡端口截面空气连通性）。"""
    return material.strip().lower() in _AIR_MATERIALS


def is_metal_material(material: str, is_metal: bool | None = None) -> bool:
    """金属材质判定：显式 is_metal 声明优先，否则材质名启发式。

    启发式=整名命中单元素符号集，或按非字母词元切分后命中金属词元集
    （"pec"/"gold"/"copper"…）。"alumina" 等含金属子串的介质名不误判
    （词元切分，非子串匹配）。
    """
    if is_metal is not None:
        return bool(is_metal)
    m = material.strip().lower()
    if m in _METAL_EXACT:
        return True
    return any(tok in _METAL_TOKENS for tok in re.split(r"[^a-z]+", m) if tok)


# ── 信封 issue 构造 ────────────────────────────────────────────────────


def _issue(check: str, level: Literal["ERROR", "WARN"],
           objects: list[str], message: str) -> dict[str, Any]:
    return {"check": check, "level": level,
            "objects": list(objects), "message": message}


# ── 检查④ 实体部分相交（反馈 §2.2 两情形）──────────────────────────────


def _contains(outer: LintBox, inner: LintBox) -> bool:
    """outer 的 AABB 完全包含 inner（贴边容差内）。"""
    lo_o, hi_o, lo_i, hi_i = outer.lo(), outer.hi(), inner.lo(), inner.hi()
    return all(
        lo_o[k] <= lo_i[k] + CONTAINMENT_TOL and hi_i[k] <= hi_o[k] + CONTAINMENT_TOL
        for k in range(3)
    )


def check_partial_intersections(geo: LintGeometry) -> list[dict[str, Any]]:
    """两两 AABB 相交且非包含 → ERROR 列表。

    反馈 §2.2 实测两情形：真空盒**完全包住**固体=合法包含（不报）；
    真空盒与实心体**部分相交**=HFSS validate 报
    "Parts X and Y intersect." 求解失败（ERROR）。面贴/层叠（某轴
    重叠=0）与零厚度薄片（sheet 不会与体"相交"成实体）不算相交。
    """
    issues: list[dict[str, Any]] = []
    boxes = geo.boxes
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            lo_a, hi_a, lo_b, hi_b = a.lo(), a.hi(), b.lo(), b.hi()
            overlap = [min(hi_a[k], hi_b[k]) - max(lo_a[k], lo_b[k])
                       for k in range(3)]
            if not all(o > INTERSECTION_EPS for o in overlap):
                continue
            if _contains(a, b) or _contains(b, a):
                continue  # 合法包含（vacuum 包裹，反馈 §2.2 情形 1）
            issues.append(_issue(
                "partial_intersection", "ERROR", [a.name, b.name],
                f"实体 '{a.name}' 与 '{b.name}' AABB 部分相交（三轴均有正重叠"
                "且互不包含）——HFSS validate 报 \"Parts ... intersect.\" 求解"
                "失败（反馈 §2.2 情形 2）。完全包含（如 vacuum 包裹固体）合法；"
                "部分相交须布尔运算（unite/subtract）或调整坐标消除。"))
    return issues


# ── 检查⑤ 薄金属纵横比 ─────────────────────────────────────────────────


def check_metal_aspect_ratio(geo: LintGeometry) -> list[dict[str, Any]]:
    """金属盒最薄边/最长边 <1e-5 → WARN（建议改 sheet 或加密网格）。

    零厚度盒=已经是 sheet 形态（"建议改 sheet"的目标形态本身），豁免。
    """
    issues: list[dict[str, Any]] = []
    for box in geo.boxes:
        if not is_metal_material(box.material, box.is_metal):
            continue
        ext = box.extent()
        if any(e <= 0.0 for e in ext):
            continue  # 零厚度=sheet，不告警
        ratio = min(ext) / max(ext)
        if ratio < ASPECT_RATIO_MIN:
            issues.append(_issue(
                "metal_aspect_ratio", "WARN", [box.name],
                f"薄金属 '{box.name}'（material={box.material}）纵横比 "
                f"{ratio:.3e} < {ASPECT_RATIO_MIN:g}（extent={ext}）——"
                "极薄实体金属网格代价大且易病态，建议改零厚度 sheet"
                "（PEC 面）或对薄向显式加密网格（反馈 §4 表第 5 条）。"))
    return issues


# ── 检查⑥ 变量单位裸数 ─────────────────────────────────────────────────

#: 词法单元：标识符/单位、数字（含指数与 .5 形态）、运算符/分隔符
_TOKEN_RE = re.compile(
    r"[A-Za-z_µ][A-Za-z0-9_µ]*"
    r"|\d+\.?\d*(?:[eE][+-]?\d+)?"
    r"|\.\d+(?:[eE][+-]?\d+)?"
    r"|[+\-*/^(),]"
)
_NUMBER_RE = re.compile(r"^(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
#: 已知单位后缀（长度/角度/频率/时间/电学；命中即"非裸数"）
_KNOWN_UNITS = {
    "km", "m", "dm", "cm", "mm", "um", "µm", "nm", "mil", "thou", "in", "ft", "yd",
    "deg", "degs", "degree", "degrees", "rad", "rads", "grad",
    "thz", "ghz", "mhz", "khz", "hz",
    "s", "ms", "us", "µs", "ns", "ps", "fs",
    "kv", "v", "mv", "ma", "a", "ohm", "ohms", "dbm", "db",
}


def _tokenize(expr: str) -> list[str]:
    return [m.group(0) for m in _TOKEN_RE.finditer(expr)]


def _mark_unary(tokens: list[str]) -> list[str]:
    """一元 +/- 改记 'u'：首 token 或前邻为运算符/'(' /',' 的 +/- 是符号位。"""
    out: list[str] = []
    for idx, tok in enumerate(tokens):
        if tok in ("+", "-"):
            prev = out[idx - 1] if idx else ""
            if prev == "" or prev in ("+", "-", "*", "/", "^", "(", ",", "u"):
                out.append("u")
                continue
        out.append(tok)
    return out


def _bare_additive_literals(expr: str) -> list[str]:
    """找表达式里加性/减性位置的无量纲裸数字面量。

    规则（模块 docstring 检查⑥语义）：
    - 整式就是一个（可带符号的）裸数 → 裸（按米解释真坑）；
    - 裸数的最近有效邻 token（回跳过一元符号位）是 +/-，或后邻是
      +/- → 加性位置 → 裸；
    - 数字后紧跟已知单位后缀（"0.04mm"，允许空格）→ 非裸；
    - 乘除/指数/函数参位（"2*w"、"sqrt(2)"、"max(a,0.04)"）→ 不拦。
    """
    tokens = _mark_unary(_tokenize(expr))
    if not tokens:
        return []
    # 整式裸数（允许前导一元符号）
    core = [t for t in tokens if t != "u"]
    if core and all(_NUMBER_RE.fullmatch(t) for t in core):
        return [expr.strip()]

    def significant_prev(idx: int) -> str:
        for k in range(idx - 1, -1, -1):
            if tokens[k] != "u":
                return tokens[k]
        return ""

    bare: list[str] = []
    for idx, tok in enumerate(tokens):
        if not _NUMBER_RE.fullmatch(tok):
            continue
        nxt = tokens[idx + 1] if idx + 1 < len(tokens) else ""
        if nxt.lower() in _KNOWN_UNITS:
            continue  # 带单位后缀（0.04mm），非裸
        prev = significant_prev(idx)
        if prev in ("+", "-") or nxt in ("+", "-"):
            bare.append(tok)
    return bare


def check_variable_units(geo: LintGeometry) -> list[dict[str, Any]]:
    """加性位置的无量纲裸数 → ERROR（HFSS 按米解释真坑，反馈 §4 末条）。

    ``w_s+0.04`` 里 0.04 被当 0.04 m（膜宽 0.56mm 变 40mm 级报废且
    无任何报错）。dimension="dimensionless" 的变量显式豁免。
    """
    issues: list[dict[str, Any]] = []
    for var in geo.variables:
        if var.dimension == "dimensionless":
            continue
        if not var.expression or not var.expression.strip():
            continue
        bare = _bare_additive_literals(var.expression)
        if bare:
            issues.append(_issue(
                "variable_units", "ERROR", [var.name],
                f"变量 '{var.name}'={var.expression} 含加性位置无量纲裸数 "
                f"{bare}——HFSS 把裸数按米解释（如 0.04 → 0.04 m），模型"
                "静默报废（反馈 §4 末条真坑）。请写显式单位后缀"
                "（0.04mm）或引用带单位变量。"))
    return issues


# ── 检查①②③ 端口三断言（反馈 §2.3 形态 A/B/C）────────────────────────


def _model_bbox(geo: LintGeometry) -> tuple[tuple[float, float], ...] | None:
    """全部 box 的并集包围盒（端口 sheet 不参与），无 box 时 None。"""
    if not geo.boxes:
        return None
    los = [b.lo() for b in geo.boxes]
    his = [b.hi() for b in geo.boxes]
    return tuple(
        (min(lo[k] for lo in los), max(hi[k] for hi in his)) for k in range(3)
    )


def check_port_on_outer_boundary(
    geo: LintGeometry, bbox: tuple[tuple[float, float], ...] | None,
) -> list[dict[str, Any]]:
    """波端口 sheet 必须与模型包围盒某面重合 → 否则 ERROR。

    反馈 §2.3 断言 1（"端口 sheet 是否落在模型外边界平面上，坐标与
    bounding box 对齐"）：埋在模型内部的波端口在非物理边界上展开
    模式，解静默失真。lumped 端口天然在模型内部，检查①豁免。
    """
    issues: list[dict[str, Any]] = []
    if bbox is None:
        return issues
    for port in geo.ports:
        if port.kind != "wave":
            continue
        ax = "xyz".index(port.sheet.axis)
        lo, hi = bbox[ax]
        pos = port.sheet.pos
        if abs(pos - lo) <= PORT_BOUNDARY_TOL or abs(pos - hi) <= PORT_BOUNDARY_TOL:
            continue
        issues.append(_issue(
            "port_on_outer_boundary", "ERROR", [port.name],
            f"波端口 '{port.name}' sheet（{port.sheet.axis}={pos}）不与模型"
            f"包围盒任一面重合（{port.sheet.axis} 范围 [{lo}, {hi}]，容差 "
            f"{PORT_BOUNDARY_TOL:g}）——端口埋在模型内部时模式求解器在非"
            "物理边界上展开，解静默失真（反馈 §2.3 断言 1）。波端口必须"
            "落在求解域外边界平面（如真空域截面）上。"))
    return issues


def check_port_adjacent_solve_inside(geo: LintGeometry) -> list[dict[str, Any]]:
    """端口面 1e-6 邻域内至少一个 solve_inside=True 体 → 否则 ERROR。

    反馈 §2.3 断言 2/形态 A：端口一侧没有 solve-inside 材料
    （"Port P1 does not have a solved inside material on either side"）
    ——真空是背景未被显式建体时高频翻车。邻接判定：体轴向范围
    ±tol 覆盖 sheet 平面，且面矩形与体截面有正面积交。
    """
    issues: list[dict[str, Any]] = []
    for port in geo.ports:
        ax = "xyz".index(port.sheet.axis)
        u_ax, v_ax = port.sheet.tangential_axes()
        u0, u1 = port.sheet.u
        v0, v1 = port.sheet.v
        adjacent: list[str] = []
        for box in geo.boxes:
            if not box.solve_inside:
                continue
            lo, hi = box.lo(), box.hi()
            if not (lo[ax] - PORT_ADJACENCY_TOL <= port.sheet.pos
                    <= hi[ax] + PORT_ADJACENCY_TOL):
                continue
            ov_u = min(u1, hi[u_ax]) - max(u0, lo[u_ax])
            ov_v = min(v1, hi[v_ax]) - max(v0, lo[v_ax])
            if ov_u > _TANGENTIAL_EPS and ov_v > _TANGENTIAL_EPS:
                adjacent.append(box.name)
        if not adjacent:
            issues.append(_issue(
                "port_adjacent_solve_inside", "ERROR", [port.name],
                f"端口 '{port.name}' 面邻域（±{PORT_ADJACENCY_TOL:g}）内没有"
                " solve_inside=True 的体——端口一侧无 solve-inside 材料，"
                "solve 报 \"Port ... does not have a solved inside material "
                "on either side\"（反馈 §2.3 形态 A）。请显式建真空/介质体"
                "（solve_inside=True）贴住端口面，勿依赖背景介质。"))
    return issues


def check_port_cross_section_connectivity(
    geo: LintGeometry,
) -> list[dict[str, Any]]:
    """端口截面按材料栅格化，空气连通域 >1 → WARN（多模可豁免）。

    反馈 §2.3 断言 3/形态 B/C：端口面跨多个不连通空气区 → mode 1
    不是传输线模（|S11|≈0dB 全反射）；周长被薄膜金属/介质切分 →
    非无源/假谐振。栅格为 64×64 保守覆盖（亚胞薄壁也能切开空气，
    见模块 docstring）。空气=未被任何非空气材料体覆盖的胞（背景
    计空气；air/vacuum 体不阻挡）。multimode=True 的端口豁免。
    """
    issues: list[dict[str, Any]] = []
    n = CROSS_SECTION_GRID_N
    for port in geo.ports:
        if port.multimode:
            continue
        ax = "xyz".index(port.sheet.axis)
        u_ax, v_ax = port.sheet.tangential_axes()
        u0, u1 = port.sheet.u
        v0, v1 = port.sheet.v
        du = (u1 - u0) / n
        dv = (v1 - v0) / n
        if du <= 0.0 or dv <= 0.0:
            continue  # 退化 sheet 矩形，交由检查①②把门
        solids: list[LintBox] = []
        for box in geo.boxes:
            if is_air_material(box.material):
                continue
            lo, hi = box.lo(), box.hi()
            if lo[ax] - PORT_ADJACENCY_TOL <= port.sheet.pos <= hi[ax] + PORT_ADJACENCY_TOL:
                solids.append(box)
        # 保守栅格化：体截面（切向两轴区间）与胞闭区间相交即覆盖
        covered = [[False] * n for _ in range(n)]
        for box in solids:
            lo, hi = box.lo(), box.hi()
            i_lo = max(0, min(n, math.floor((lo[u_ax] - u0) / du)))
            i_hi = max(0, min(n, math.ceil((hi[u_ax] - u0) / du)))
            if i_hi <= i_lo:
                i_hi = min(n, i_lo + 1)  # 零厚壁=含于单胞
            j_lo = max(0, min(n, math.floor((lo[v_ax] - v0) / dv)))
            j_hi = max(0, min(n, math.ceil((hi[v_ax] - v0) / dv)))
            if j_hi <= j_lo:
                j_hi = min(n, j_lo + 1)
            for i in range(i_lo, i_hi):
                for j in range(j_lo, j_hi):
                    covered[i][j] = True
        # 空气连通域（4-连通 BFS）
        seen = [[False] * n for _ in range(n)]
        components = 0
        for i in range(n):
            for j in range(n):
                if covered[i][j] or seen[i][j]:
                    continue
                components += 1
                queue = deque([(i, j)])
                seen[i][j] = True
                while queue:
                    ci, cj = queue.popleft()
                    for ni, nj in ((ci - 1, cj), (ci + 1, cj),
                                   (ci, cj - 1), (ci, cj + 1)):
                        if (0 <= ni < n and 0 <= nj < n
                                and not covered[ni][nj] and not seen[ni][nj]):
                            seen[ni][nj] = True
                            queue.append((ni, nj))
        if components > 1:
            issues.append(_issue(
                "port_cross_section_connectivity", "WARN",
                [port.name] + [b.name for b in solids],
                f"端口 '{port.name}' 截面栅格化后空气连通域数={components} "
                f"（>1，参与切分的实体={[b.name for b in solids]}）——端口面"
                "跨多个不连通空气区时 mode 1 非传输线模（|S11|≈0dB 全反射，"
                "反馈 §2.3 形态 B）；周长被薄膜金属/介质切分时非无源/假谐振"
                "（形态 C）。确属多模端口请声明 multimode=True 豁免。"))
    return issues


# ── 服务入口 ───────────────────────────────────────────────────────────

_CHECKS = (
    check_partial_intersections,
    check_metal_aspect_ratio,
    check_variable_units,
    check_port_on_outer_boundary,
    check_port_adjacent_solve_inside,
    check_port_cross_section_connectivity,
)


def lint_geometry(geometry: LintGeometry | dict[str, Any]) -> dict[str, Any]:
    """建模期几何门：六检查全跑，返回服务层信封。

    Parameters
    ----------
    geometry : LintGeometry | dict
        声明式几何描述（schema 实例或可校验 dict——service JSON 进出）。

    Returns
    -------
    dict
        - 成功：``{"ok": True, "lint_pass": bool, "issues": [...],
          "counts": {"error", "warn"}, "model_units", "summary"}``；
          ``lint_pass`` = 无 ERROR 级问题（门判定；WARN 不拦截）。
        - 输入未过 schema：``error_envelope``（ok=False，errors 非空）。
    """
    try:
        geo = (geometry if isinstance(geometry, LintGeometry)
               else LintGeometry.model_validate(geometry))
    except Exception as exc:
        return error_envelope(
            f"LintGeometry 校验失败: {exc}",
            issues=[], counts={"error": 0, "warn": 0}, lint_pass=False,
            model_units=None, summary={"boxes": 0, "ports": 0, "variables": 0},
        )
    bbox = _model_bbox(geo)
    issues: list[dict[str, Any]] = []
    for check in _CHECKS:
        if check is check_port_on_outer_boundary:
            issues += check(geo, bbox)
        else:
            issues += check(geo)
    n_error = sum(1 for it in issues if it["level"] == "ERROR")
    n_warn = len(issues) - n_error
    return ok_envelope(
        lint_pass=(n_error == 0),
        issues=issues,
        counts={"error": n_error, "warn": n_warn},
        model_units=geo.model_units,
        summary={"boxes": len(geo.boxes), "ports": len(geo.ports),
                 "variables": len(geo.variables)},
    )
