"""LC-4 阻抗连续性 DRC（round15 §四 LC-4；E 流版图四件之四，2026-10-02）。

规格原文（研究扩充 round15 LC-4 段）：
    折线分段 walk + rf_trace_geometry 截面 + forward_z0 段间跳变 flag +
    rf_process_corners 角点联动。验收：阶跃/锥形负例。

规则面（四码；flag 级决定 verdict、warning 级不改判——return_path_check
同族口径；本模块无独立 rule 字段，码即规则）：

- ``Z0_STEP``（flag）：同一导通层上端点相接的两段走线，forward_z0 段间
  阻抗差 |ΔZ0| > 容差 → 阻抗失配点（位置=接点坐标，值/限=Ω）。同宽相接
  ΔZ0=0 恒不 flag；锥形过渡（taper_polygon 桥接、两端点不直接相接）不
  构成段间接点，天然不 flag——验收「阶跃检出 / 锥形不虚警」的双向口径。
- ``Z0_TARGET_DEV``（flag）：给定 z0_target_ohm 时，段阻抗偏离目标超过
  容差 → flag，expected_width_mm 附 inverse_width 反查的期望标称宽度
  （阻抗参考源=synthesis 单源，铁律 1c）。未给目标则只做段间连续性。
- ``CORNER_SHARP``（warning）：折线内部顶点转向角 > 阈值（缺省 45°）
  → 角点阻抗扰动警示；联动 rf_trace_geometry 的 90° miter 惯用档给出
  补偿建议（mitered_bend_polygon 缺省倒角 c=w/2，即 50% miter 比）。
- ``VIA_NECK``（warning）：过孔焊盘直径 < 所接走线宽（端点相接）→
  颈缩级串连不连续警示。中途 T 接过孔不在本规则面（连接性归 LC-7）。

边界口径（return_path_check 严格边界先例）：两个 flag 全部严格 ``>``、
VIA_NECK 严格 ``<``、CORNER_SHARP 严格 ``>``——恰等不 flag/不警。

消费声明（规格未要求 ``rfauto drc impedance`` CLI——本轮纯函数+消费面，
service/CLI 壳另行立项）：

- ``check_layout_impedance(layout, ...)``：LC-2 Layout 桥直喂入口。core
  是 .importlinter 叶子层、禁 import adapters——Layout 按属性签名识别
  （``points``+``width_mm``=走线、``pad_diameter_mm``=过孔；polygon/
  circle 计数跳过），与 pcell_dsl「只做参数→原语坐标、不碰格式层」同款
  纪律。LayoutPath/LayoutVia 无 id 字段，桥内按出现序指派 P001…/V001…。
- ``check_impedance_continuity(...)``：结构化纯入口（TracePathSpec/
  ViaPadSpec），未来 service 壳直接包此函数。
- 复验闭环先例：rf_guard_structures→return_path_check（LC-3）同款，
  LC-2 pcell/Layout 求值产物 → 本模块复验。

单位：全线 mm / Ω / GHz。阻抗数字只出自 core/synthesis 确定性内核
（铁律 7）：forward_z0（skrf MLine/HJ）与 inverse_width（brentq 反查），
本模块只做折线 walk、比较与报告，零物理数字自产。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

__all__ = [
    "DEFAULT_CORNER_WARN_TURN_DEG",
    "DEFAULT_JUNCTION_TOL_MM",
    "DEFAULT_Z0_STEP_TOL_OHM",
    "FLAG_CODES",
    "RULE_CODES",
    "SEVERITY_FLAG",
    "SEVERITY_WARNING",
    "WARNING_CODES",
    "ImpedanceDrcIssue",
    "ImpedanceDrcReport",
    "Point",
    "TracePathSpec",
    "ViaPadSpec",
    "check_impedance_continuity",
    "check_layout_impedance",
    "extract_layout_geometry",
]

# ─── 规则码表 ────────────────────────────────────────────────────────────────

RULE_CODES = ("Z0_STEP", "Z0_TARGET_DEV", "CORNER_SHARP", "VIA_NECK")
FLAG_CODES = ("Z0_STEP", "Z0_TARGET_DEV")
WARNING_CODES = ("CORNER_SHARP", "VIA_NECK")
SEVERITY_FLAG = "flag"
SEVERITY_WARNING = "warning"

#: 段间阻抗跳变容差缺省（Ω）。
DEFAULT_Z0_STEP_TOL_OHM = 1.0
#: 急转角警示阈值缺省（度；0°=直线延续，90°=直角弯）。
DEFAULT_CORNER_WARN_TURN_DEG = 45.0
#: 端点相接判定容差缺省（mm；Layout 内部 nm 量化的千倍裕度）。
DEFAULT_JUNCTION_TOL_MM = 1e-3

Point = tuple[float, float]

# ─── 数值守卫（bool 显式拒收 df7+⑯；判缺失 is not None #364④） ──────────────


def _finite(value: Any, name: str) -> float:
    """入参收敛为有限 float，非法即显式报错。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染）")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 数值非法 {value!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，收到 {value!r}")
    return out


def _positive(value: Any, name: str) -> float:
    """入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，收到 {out!r}")
    return out


def _nonneg(value: Any, name: str) -> float:
    """入参收敛为有限非负 float，非法即显式报错。"""
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 ≥0，收到 {out!r}")
    return out


def _pt(value: Any, name: str) -> Point:
    """二维坐标收敛（list/tuple 均 Accept，出参恒 tuple）。"""
    if isinstance(value, (str, bytes)) or not hasattr(value, "__len__") or len(value) != 2:
        raise ValueError(f"{name} 必须为二元坐标，收到 {value!r}")
    return (_finite(value[0], f"{name}[0]"), _finite(value[1], f"{name}[1]"))


# ─── 输入规格（dataclass，构造期校验；return_path_check 同族） ───────────────


@dataclass(frozen=True)
class TracePathSpec:
    """走线折线规格（mm）：恒宽中心线折线（LayoutPath 的 core 侧镜像）。

    构造期校验：≥2 点、坐标有限、无零长段、宽度正——退化 ValueError。
    """

    trace_id: str
    points: tuple[Point, ...]
    width_mm: float
    layer: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", str(self.trace_id))
        object.__setattr__(self, "layer", str(self.layer))
        pts = tuple(_pt(p, f"TracePathSpec({self.trace_id}).points[{k}]")
                    for k, p in enumerate(self.points))
        if len(pts) < 2:
            raise ValueError(f"TracePathSpec({self.trace_id}) 至少 2 点，收到 {len(pts)}")
        for k in range(len(pts) - 1):
            if pts[k] == pts[k + 1]:
                raise ValueError(
                    f"TracePathSpec({self.trace_id}) 零长段（点 {k}=={k + 1}）")
        object.__setattr__(self, "points", pts)
        object.__setattr__(self, "width_mm", _positive(self.width_mm, "TracePathSpec.width_mm"))


@dataclass(frozen=True)
class ViaPadSpec:
    """过孔焊盘规格（mm 平面坐标 + 焊盘直径 + 所在导通层）。"""

    via_id: str
    position: Point
    pad_diameter_mm: float
    layer: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "via_id", str(self.via_id))
        object.__setattr__(self, "position", _pt(self.position, "ViaPadSpec.position"))
        object.__setattr__(
            self, "pad_diameter_mm", _positive(self.pad_diameter_mm, "ViaPadSpec.pad_diameter_mm"))
        object.__setattr__(self, "layer", str(self.layer))


# ─── 违规项与报告 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImpedanceDrcIssue:
    """单条违规/警示（ReturnPathIssue 同族口径，dataclass+to_dict）。"""

    code: str
    severity: str
    element_id: str
    detail: str
    related_id: str | None = None
    position: Point | None = None
    value_ohm: float | None = None
    limit_ohm: float | None = None
    expected_width_mm: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "element_id": self.element_id,
            "related_id": self.related_id,
            "position": None
            if self.position is None
            else [round(self.position[0], 9), round(self.position[1], 9)],
            "value_ohm": None if self.value_ohm is None else round(self.value_ohm, 6),
            "limit_ohm": None if self.limit_ohm is None else round(self.limit_ohm, 6),
            "expected_width_mm": None
            if self.expected_width_mm is None
            else round(self.expected_width_mm, 9),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ImpedanceDrcReport:
    """阻抗连续性检查报告（flag 级 verdict + 违规清单）。"""

    verdict: str
    issues: tuple[ImpedanceDrcIssue, ...]
    counts: dict[str, Any]
    checked: dict[str, Any]

    @property
    def ok(self) -> bool:
        """flag 级无违规（warning 不影响）。"""
        return self.verdict == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "verdict": self.verdict,
            "issues": [i.to_dict() for i in self.issues],
            "counts": dict(self.counts),
            "checked": dict(self.checked),
        }


# ─── 折线几何（纯函数；mm） ──────────────────────────────────────────────────


def _turn_deg(a: Point, b: Point, c: Point) -> float:
    """折线在顶点 b 处的转向角（度）：0=直线延续，90=直角弯，180=折返。

    atan2(|v1×v2|, v1·v2) 双未归一口径（atan2 对正尺度不变，夹角
    θ=atan2(|v1||v2|sinθ, |v1||v2|cosθ)）；dot 归一化而 cross 不归一会
    把 60° 弯算成 88.9°（锚树实测抓出后修正）。
    """
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    # 零长段已在 TracePathSpec 构造期拒绝；此处护栏式防 0 向量。
    if math.hypot(*v1) == 0.0 or math.hypot(*v2) == 0.0:
        return 0.0
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    cross = v1[0] * v2[1] - v1[1] * v2[0]
    return math.degrees(math.atan2(abs(cross), dot))


def _connected_chains(paths: list[TracePathSpec], tol_mm: float) -> tuple[list[int], list[tuple[int, int]]]:
    """端点相接的连通分量（union-find）与接点对清单（按输入序确定性）。

    Returns:
        (chain_id_per_path, junction_pairs)——junction_pairs 内每对 (i, j)
        满足 i<j、按 (i, j) 字典序。
    """
    n = len(paths)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    pairs: list[tuple[int, int]] = []
    for i in range(n):
        ends_i = (paths[i].points[0], paths[i].points[-1])
        for j in range(i + 1, n):
            ends_j = (paths[j].points[0], paths[j].points[-1])
            if any(math.hypot(a[0] - b[0], a[1] - b[1]) <= tol_mm for a in ends_i for b in ends_j):
                union(i, j)
                pairs.append((i, j))
    return [find(i) for i in range(n)], pairs


def _junction_point(pa: TracePathSpec, pb: TracePathSpec) -> Point:
    """接点坐标=相接端点对的中点（恰等相接时即精确坐标；确定性口径）。"""
    best: tuple[float, Point] | None = None
    for a in (pa.points[0], pa.points[-1]):
        for b in (pb.points[0], pb.points[-1]):
            d = math.hypot(a[0] - b[0], a[1] - b[1])
            if best is None or d < best[0]:
                best = (d, ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0))
    assert best is not None  # 2×2 必有解
    return best[1]


# ─── LC-2 Layout 桥（duck-typing；core 禁 import adapters） ──────────────────


def extract_layout_geometry(
    layout_like: Any,
    *,
    layers: list[str] | tuple[str, ...] | None = None,
) -> tuple[list[TracePathSpec], list[ViaPadSpec], dict[str, Any]]:
    """从 Layout 形状对象抽取走线/过孔规格（属性签名识别，零 adapters import）。

    识别口径：``points``+``width_mm``+``layer`` → 走线（LayoutPath）；
    ``position``+``pad_diameter_mm``+``pad_layer`` → 过孔（LayoutVia）；
    其余（LayoutPolygon/LayoutCircle）计数跳过（填充面无恒宽截面语义）。

    Args:
        layout_like: 带 ``layers``（元素有 ``.name``）与 ``items`` 的版图对象。
        layers: 受检导通层白名单；None=全部 ``.Cu`` 结尾的声明层。

    Returns:
        (paths, vias, stats)——id 按出现序指派 P001…/V001…；stats 含
        declared_layers/selected_layers/skipped_items 计数。

    Raises:
        ValueError: 项引用未声明层（fail-loud）；白名单含未声明层。
    """
    declared = [str(layer.name) for layer in getattr(layout_like, "layers", ())]
    declared_set = set(declared)
    if layers is None:
        selected = {name for name in declared if name.endswith(".Cu")}
    else:
        selected = {str(name) for name in layers}
        unknown = sorted(selected - declared_set)
        if unknown:
            raise ValueError(f"白名单引用未声明层 {unknown}；声明层: {declared}")
    paths: list[TracePathSpec] = []
    vias: list[ViaPadSpec] = []
    skipped = 0
    for item in getattr(layout_like, "items", ()):
        if hasattr(item, "width_mm") and hasattr(item, "points") and hasattr(item, "layer"):
            layer = str(item.layer)
            if layer not in declared_set:
                raise ValueError(f"走线引用未声明层 {layer!r}；声明层: {declared}")
            if layer not in selected:
                skipped += 1
                continue
            paths.append(
                TracePathSpec(
                    trace_id=f"P{len(paths) + 1:03d}",
                    points=tuple(_pt(p, "layout path point") for p in item.points),
                    width_mm=float(item.width_mm),
                    layer=layer,
                )
            )
        elif hasattr(item, "pad_diameter_mm") and hasattr(item, "position"):
            layer = str(getattr(item, "pad_layer", ""))
            if layer not in declared_set:
                raise ValueError(f"过孔引用未声明层 {layer!r}；声明层: {declared}")
            if layer not in selected:
                skipped += 1
                continue
            vias.append(
                ViaPadSpec(
                    via_id=f"V{len(vias) + 1:03d}",
                    position=_pt(item.position, "layout via position"),
                    pad_diameter_mm=float(item.pad_diameter_mm),
                    layer=layer,
                )
            )
        else:
            skipped += 1
    stats = {
        "declared_layers": declared,
        "selected_layers": sorted(selected),
        "skipped_items": skipped,
    }
    return paths, vias, stats


# ─── 主入口 ──────────────────────────────────────────────────────────────────


def check_impedance_continuity(
    paths: list[TracePathSpec],
    vias: list[ViaPadSpec] | None = None,
    *,
    stackup: Stackup,
    freq_ghz: float,
    layers: list[str] | tuple[str, ...] | None = None,
    z0_target_ohm: float | None = None,
    z0_step_tol_ohm: float = DEFAULT_Z0_STEP_TOL_OHM,
    z0_target_tol_ohm: float | None = None,
    corner_warn_turn_deg: float = DEFAULT_CORNER_WARN_TURN_DEG,
    junction_tol_mm: float = DEFAULT_JUNCTION_TOL_MM,
) -> ImpedanceDrcReport:
    """阻抗连续性检查（结构化纯入口；规则面见模块 docstring）。

    Args:
        paths: 走线折线清单（TracePathSpec，mm）。
        vias: 过孔清单（可选；缺省无 → VIA_NECK 恒零违规）。
        stackup: 微带层叠（forward_z0/inverse_width 截面口径）。
        freq_ghz: 设计频点（GHz）。
        layers: 受检导通层白名单；None=paths/vias 出现的全部层。
            引用白名单之外层的项 → ValueError（未知层 fail-loud）。
        z0_target_ohm: 参考目标阻抗（Ω）；None=只做段间连续性。
        z0_step_tol_ohm: 段间跳变容差（Ω，≥0；严格 > 判 flag）。
        z0_target_tol_ohm: 目标偏离容差（Ω，≥0；None=取 z0_step_tol_ohm）。
        corner_warn_turn_deg: 急转角警示阈值（度，(0, 180]；严格 > 判警）。
        junction_tol_mm: 端点相接判定容差（mm，≥0）。

    Returns:
        ImpedanceDrcReport（verdict=PASS|FAIL 按 flag 级；warning 不改判）。

    Raises:
        ValueError: 非法数值（bool/NaN/非正宽/零长段）、paths 元素类型
            不符、未知层引用、阈值越界。
    """
    path_list = list(paths)
    if any(not isinstance(p, TracePathSpec) for p in path_list):
        raise ValueError("paths 必须为 TracePathSpec 列表")
    via_list = list(vias) if vias is not None else []
    if any(not isinstance(v, ViaPadSpec) for v in via_list):
        raise ValueError("vias 必须为 ViaPadSpec 列表")
    freq = _positive(freq_ghz, "freq_ghz")
    step_tol = _nonneg(z0_step_tol_ohm, "z0_step_tol_ohm")
    target_tol = step_tol if z0_target_tol_ohm is None else _nonneg(
        z0_target_tol_ohm, "z0_target_tol_ohm")
    corner_deg = _finite(corner_warn_turn_deg, "corner_warn_turn_deg")
    if not 0.0 < corner_deg <= 180.0:
        raise ValueError(f"corner_warn_turn_deg 必须 ∈ (0, 180]，收到 {corner_deg!r}")
    tol_mm = _nonneg(junction_tol_mm, "junction_tol_mm")
    target: float | None = None
    if z0_target_ohm is not None:
        target = _positive(z0_target_ohm, "z0_target_ohm")

    if layers is None:
        selected = {p.layer for p in path_list} | {v.layer for v in via_list}
    else:
        selected = {str(name) for name in layers}
    for p in path_list:
        if p.layer not in selected:
            raise ValueError(f"走线 {p.trace_id!r} 引用未知层 {p.layer!r}；受检层: {sorted(selected)}")
    for v in via_list:
        if v.layer not in selected:
            raise ValueError(f"过孔 {v.via_id!r} 引用未知层 {v.layer!r}；受检层: {sorted(selected)}")

    # 截面阻抗：宽度 → forward_z0（同宽缓存，确定性内核唯一数字源）。
    z0_cache: dict[float, float] = {}

    def z0_of(width_mm: float) -> float:
        if width_mm not in z0_cache:
            z0_cache[width_mm] = forward_z0(width_mm, freq, stackup).z0
        return z0_cache[width_mm]

    issues: list[ImpedanceDrcIssue] = []

    # Z0_TARGET_DEV：段阻抗 vs 目标（inverse_width 反查期望宽度，一次）。
    expected_w: float | None = None
    if target is not None:
        w_exp, _z0_actual, status = inverse_width(target, freq, stackup)
        expected_w = w_exp if status == "ok" else None
        for p in path_list:
            z0 = z0_of(p.width_mm)
            dev = abs(z0 - target)
            if dev > target_tol:
                issues.append(
                    ImpedanceDrcIssue(
                        code="Z0_TARGET_DEV",
                        severity=SEVERITY_FLAG,
                        element_id=p.trace_id,
                        related_id=None,
                        position=p.points[0],
                        value_ohm=dev,
                        limit_ohm=target_tol,
                        expected_width_mm=expected_w,
                        detail=(
                            f"{p.trace_id} 阻抗 {z0:.4f}Ω 偏离目标 {target:.4f}Ω "
                            f"超容差 {target_tol:.4g}Ω（宽 {p.width_mm:.6g}mm"
                            + (
                                f"，目标阻抗期望标称宽 {expected_w:.6g}mm"
                                if expected_w is not None
                                else f"，期望宽度反查不可得（status={status}）"
                            )
                            + "）"
                        ),
                    )
                )

    # 连通链与接点（端点相接；同宽相接 ΔZ0=0 恒不 flag）。
    chain_ids, junction_pairs = _connected_chains(path_list, tol_mm)
    for i, j in junction_pairs:
        pa, pb = path_list[i], path_list[j]
        dz = abs(z0_of(pb.width_mm) - z0_of(pa.width_mm))
        if dz > step_tol:
            issues.append(
                ImpedanceDrcIssue(
                    code="Z0_STEP",
                    severity=SEVERITY_FLAG,
                    element_id=pb.trace_id,
                    related_id=pa.trace_id,
                    position=_junction_point(pa, pb),
                    value_ohm=dz,
                    limit_ohm=step_tol,
                    expected_width_mm=None,
                    detail=(
                        f"段间阻抗跳变 {z0_of(pa.width_mm):.4f}Ω → "
                        f"{z0_of(pb.width_mm):.4f}Ω（Δ={dz:.4f}Ω > 容差 "
                        f"{step_tol:.4g}Ω；宽 {pa.width_mm:.6g}→{pb.width_mm:.6g}mm）"
                    ),
                )
            )

    # CORNER_SHARP：折线内部顶点转向角（warning；miter 惯用档联动建议）。
    corners_scanned = 0
    for p in path_list:
        for k in range(1, len(p.points) - 1):
            corners_scanned += 1
            turn = _turn_deg(p.points[k - 1], p.points[k], p.points[k + 1])
            if turn > corner_deg:
                issues.append(
                    ImpedanceDrcIssue(
                        code="CORNER_SHARP",
                        severity=SEVERITY_WARNING,
                        element_id=p.trace_id,
                        related_id=None,
                        position=p.points[k],
                        value_ohm=None,
                        limit_ohm=corner_deg,
                        expected_width_mm=None,
                        detail=(
                            f"转向角 {turn:.2f}° > 阈值 {corner_deg:.2f}°——角点阻抗扰动，"
                            f"建议 miter 补偿（rf_trace_geometry.mitered_bend_polygon "
                            f"惯用倒角 c=w/2，w={p.width_mm:.6g}mm）"
                        ),
                    )
                )

    # VIA_NECK：焊盘直径 < 所接走线宽（端点相接；warning）。
    vias_checked = 0
    for v in via_list:
        connecting = [
            p
            for p in path_list
            if p.layer == v.layer
            and any(math.hypot(a[0] - v.position[0], a[1] - v.position[1]) <= tol_mm
                    for a in (p.points[0], p.points[-1]))
        ]
        if not connecting:
            continue
        vias_checked += 1
        for p in connecting:
            if v.pad_diameter_mm < p.width_mm:
                issues.append(
                    ImpedanceDrcIssue(
                        code="VIA_NECK",
                        severity=SEVERITY_WARNING,
                        element_id=v.via_id,
                        related_id=p.trace_id,
                        position=v.position,
                        value_ohm=None,
                        limit_ohm=None,
                        expected_width_mm=None,
                        detail=(
                            f"焊盘直径 {v.pad_diameter_mm:.6g}mm < 所接走线宽 "
                            f"{p.width_mm:.6g}mm——颈缩级串连不连续"
                        ),
                    )
                )

    n_chains = len(set(chain_ids))
    flags = sum(1 for i in issues if i.severity == SEVERITY_FLAG)
    warnings = sum(1 for i in issues if i.severity == SEVERITY_WARNING)
    counts: dict[str, Any] = {"flags": flags, "warnings": warnings}
    for code in RULE_CODES:
        counts[code] = sum(1 for i in issues if i.code == code)
    checked: dict[str, Any] = {
        "stackup": stackup.name,
        "freq_ghz": freq,
        "layers": sorted(selected),
        "paths": len(path_list),
        "chains": n_chains,
        "junctions": len(junction_pairs),
        "corners_scanned": corners_scanned,
        "vias_connected": vias_checked,
        "z0_target_ohm": target,
        "z0_step_tol_ohm": step_tol,
        "z0_target_tol_ohm": target_tol,
        "corner_warn_turn_deg": corner_deg,
        "junction_tol_mm": tol_mm,
    }
    verdict = "FAIL" if flags else "PASS"
    return ImpedanceDrcReport(verdict=verdict, issues=tuple(issues), counts=counts, checked=checked)


def check_layout_impedance(
    layout_like: Any,
    *,
    stackup: Stackup,
    freq_ghz: float,
    layers: list[str] | tuple[str, ...] | None = None,
    z0_target_ohm: float | None = None,
    z0_step_tol_ohm: float = DEFAULT_Z0_STEP_TOL_OHM,
    z0_target_tol_ohm: float | None = None,
    corner_warn_turn_deg: float = DEFAULT_CORNER_WARN_TURN_DEG,
    junction_tol_mm: float = DEFAULT_JUNCTION_TOL_MM,
) -> ImpedanceDrcReport:
    """Layout 桥入口：LC-2 Layout 求值产物直喂（duck-typing，见模块 docstring）。"""
    paths, vias, stats = extract_layout_geometry(layout_like, layers=layers)
    report = check_impedance_continuity(
        paths,
        vias,
        stackup=stackup,
        freq_ghz=freq_ghz,
        z0_target_ohm=z0_target_ohm,
        z0_step_tol_ohm=z0_step_tol_ohm,
        z0_target_tol_ohm=z0_target_tol_ohm,
        corner_warn_turn_deg=corner_warn_turn_deg,
        junction_tol_mm=junction_tol_mm,
    )
    checked = dict(report.checked)
    checked.update(stats)
    return ImpedanceDrcReport(
        verdict=report.verdict, issues=report.issues, counts=report.counts, checked=checked
    )
