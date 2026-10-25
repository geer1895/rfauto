"""flip-chip 植球/开窗盖板规划器（K13，aurora_k 战役，反馈 F3/F4/P13）。

用户反馈原文（2026-10-23，D:\\IPD调研\\...\\rfauto使用体验与反馈.md）：

- **F3 植球/凸点图元**：``solder_ball(d, h, material)`` 要用**被上下金属面截
  断的球**（球径 > 间隙，布尔截出鼓形）——这正是参考工程 Project1.aedt 的做
  法（Sphere 被平面截断）；**圆柱近似会低估回路电感**，鼓形更接近回流焊真
  实形貌。同时要植球阵列/环生成器：按"足迹完全落在地金属并集上 + 相邻球
  净距 ≥ 30 μm"两条规则自动布点（用户第一版节距 = 球径，球球相撞，HFSS
  直接拒解）。
- **F4 开窗盖板**：``lid(... windows=[...])`` 直接支持开窗，并自动把窗口边
  缘的植球剔除（用户手工做了这件事）。
- **P13 keep-out**：Ø80 植球 (−360,10) 压在 CPW 信号引线上，球顶把信号经球
  短到盖板（S21≈−99.6 dB）——植球 API 接受 keepout（K6 席已在
  hfss_builder_utils 落了 filter_keepout_candidates，本模块**对齐其语义**，
  见下"分层声明"）。

分层：本模块为**纯规划层**——纯数值几何、零引擎依赖（无 pyaedt/openEMS
import），可测核心；HFSS 落地（建 Sphere/Box + 布尔截断/开窗）在
hfss_builder_utils.solder_balls / lid_with_windows（薄落地层，几何全在本规
划器，与 K7 wave_port_cpw 同分层法）。单位约定与 K6 NetRegistry / K7 规划
器同源：um|mm|m（units 标签随 plan 携带，**数值一律调用方单位**，本模块不
换算——对齐正确性由测试钉）。

分层声明（keepout 过滤）：core 层禁 import adapters（.importlinter layers），
故 keepout 过滤在本模块**重写为同语义实现**——候选 xy 外接框与 keepout 矩
形两轴交叠均 > tol 即剔除，skipped 如实清单（命中 keepout 名+交叠量），与
K6 ``filter_keepout_candidates`` 逐字段同构；等价性由测试端到端钉
（test_flip_chip_primitives 对同输入比 kept/skipped）。

矩形近似声明（如实，与 K5 doctor 清单近似语义同族）：

- **足迹=球的外接正方形**（保守方向：圆球可能在方框判负的角区仍放得下）；
- **足迹覆盖=矩形分解精确判定**（对轴对齐矩形并集是**精确**的：把足迹方框
  按 pad 边缘切格，每格必须整体落入某个 pad——格不跨任何 pad 边缘，故格
  ⊆pad 或格∩pad=∅ 二选一）；近似性只在"圆→方"一步，方向保守；
- **旋转 pad=AABB 保守上限，覆盖判定偏松**（4 数 rect schema 只能表达轴
  对齐矩形）：非轴对齐（旋转）pad 以其外接 AABB 进 schema 时，AABB ≥ 实
  际 pad 面积，足迹更容易被判"已覆盖"——系统性偏松（**假 PASS 方向**，
  与上面两条的保守方向相反）。:func:`plan_solder_balls` 的
  ``pad_rotation_deg`` 入参供调用方声明旋转角，非 0 非 45° 倍数时出 WARN
  条目提示人工复核（旋转感知的精确覆盖判定不做 schema 扩展，留待后续）；
- **净距=圆球精确边距**（球心距 − 球径 ≥ 净距，圆球下无近似）；
- keepout/净距判定只用 xy 投影——pad 所在金属层（z）由调用方保证
  （与 K6 登记薄 bbox 近似的局限同口径）。

openEMS 侧局限（如实声明）：鼓形（截断球）在 openEMS 网格下只能以阶梯网
格近似（CSX 无球原语的原生布尔截断形态，需逐层 Box 阶梯化），侧面圆弧呈
锯齿——HFSS 侧按 Sphere+布尔截断精确建模（落地层），openEMS 侧消费本
plan 时应接受该近似或改圆柱保守近似并在 run meta 标注。

出处：本模块为**本仓设计**（aurora_k K13 席面，零文献转写公式）——
  截断球鼓形图元=参考工程 Project1.aedt 的 Sphere 布尔截断做法（用户
  反馈 F3 指认）；植球布点两规则（足迹完全落在地金属并集+相邻球净距
  ≥30μm）、开窗盖板自动剔球（F4）与 keepout 过滤语义（P13，与 K6
  filter_keepout_candidates 逐字段同构）均为本仓布点规则设计，判定
  逻辑可由上列"矩形近似声明"逐条推导复算；无经验系数、无拟合常数。
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "DEFAULT_MIN_PITCH_CLEARANCE_UM",
    "DOCTOR_NETS",
    "FlipChipPlanError",
    "balls_to_doctor_manifest",
    "plan_lid_windows",
    "plan_solder_balls",
    "truncated_ball_profile",
]

#: 反馈原值净距缺省参考（μm 制；plan_solder_balls 的 min_pitch_clearance
#: 数值一律调用方单位，本常量只是反馈原值的文档锚，不作代码缺省）。
DEFAULT_MIN_PITCH_CLEARANCE_UM = 30.0

#: doctor net 词汇（与 K5 em_doctor_service / K6 hfss_builder_utils 同词汇：
#: signal/ground/other——core 分层禁 import，对齐由测试钉）。
DOCTOR_NETS: tuple[str, ...] = ("signal", "ground", "other")

#: 单位别名（与 hfss_builder_utils._NET_UNIT_ALIASES / wave_port_planner
#: _PLAN_UNITS 同源口径；分层契约无 import 关系，对齐由测试钉）。
_UNITS: dict[str, str] = {"um": "um", "μm": "um", "mm": "mm", "m": "m"}

#: 网格候选安全上限（防 pitch 过细 × 域过大把规划器拖死；超出即报错建议粗化）。
_MAX_GRID_CANDIDATES = 200_000

#: 鼓形截断盒 xy 外扩系数（cut box 半宽 = 1.05×球半径：HFSS 布尔 intersect
#: 对相切面形态敏感，外扩 5% 避免切盒侧面与球赤道相切的退化几何）。
_CUT_BOX_MARGIN_RATIO = 1.05


class FlipChipPlanError(ValueError):
    """flip-chip 规划失败：布点/开窗/鼓形几何任一规则违反或输入非法。

    继承 ValueError（与 K7 wave_port_planner.WavePortPlanError 同法：违反
    在建模阶段报错，不带病求解），携带 ``details``（建模脚本可编程消费）。
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


# ─── 内部小工具 ──────────────────────────────────────────────────────────────


def _norm_units(units: Any, where: str) -> str:
    """units 标签规范化（um|μm→um / mm / m；非法即 FlipChipPlanError）。"""
    u = _UNITS.get(str(units or "").strip())
    if u is None:
        raise FlipChipPlanError(
            f"{where}: units 需 um|mm|m，实际 {units!r}",
            details={"where": where, "units": str(units)},
        )
    return u


def _rect4(value: Any, where: str) -> tuple[float, float, float, float]:
    """4 数矩形 → 规范 (x0,y0,x1,y1)（逐轴 min/max；退化即 FlipChipPlanError）。"""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise FlipChipPlanError(
            f"{where}: 需 4 数矩形 [x0,y0,x1,y1]，实际 {value!r}",
            details={"where": where, "value": repr(value)[:200]},
        )
    try:
        xs, ys, xe, ye = (float(v) for v in value)
    except (TypeError, ValueError) as exc:
        raise FlipChipPlanError(
            f"{where}: 矩形含非数值，实际 {value!r}",
            details={"where": where},
        ) from exc
    x0, y0, x1, y1 = min(xs, xe), min(ys, ye), max(xs, xe), max(ys, ye)
    if x1 <= x0 or y1 <= y0:
        raise FlipChipPlanError(
            f"{where}: 矩形退化（两轴跨度需 >0），实际 "
            f"[{x0:g},{y0:g},{x1:g},{y1:g}]",
            details={"where": where, "rect": [x0, y0, x1, y1]},
        )
    return (x0, y0, x1, y1)


def _bbox6(value: Any, where: str) -> tuple[tuple[float, float, float],
                                            tuple[float, float, float]]:
    """6 数 bbox → (lo, hi) 三元组对（逐轴 min/max 强制）。"""
    if not isinstance(value, (list, tuple)) or len(value) != 6:
        raise FlipChipPlanError(
            f"{where}: bbox 需 6 数 [x0,y0,z0,x1,y1,z1]，实际 {value!r}",
            details={"where": where, "value": repr(value)[:200]},
        )
    try:
        nums = [float(v) for v in value]  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise FlipChipPlanError(
            f"{where}: bbox 含非数值，实际 {value!r}",
            details={"where": where},
        ) from exc
    lo = tuple(min(nums[i], nums[i + 3]) for i in range(3))
    hi = tuple(max(nums[i], nums[i + 3]) for i in range(3))
    if hi[0] <= lo[0] or hi[1] <= lo[1] or hi[2] <= lo[2]:
        raise FlipChipPlanError(
            f"{where}: bbox 退化（三轴跨度需 >0），实际 {[*lo, *hi]}",
            details={"where": where},
        )
    return lo, hi  # type: ignore[return-value]


def _ov1d(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    """1D 区间交叠长度（不相交为 0）。"""
    return max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))


def _gap1d(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    """1D 区间间隙（相交为 0）。"""
    return max(0.0, b_lo - a_hi, a_lo - b_hi)


def _scale_of(rects: list[tuple[float, float, float, float]]) -> float:
    """坐标尺度（容差定标用；空集给 1）。"""
    m = 1.0
    for r in rects:
        m = max(m, abs(r[0]), abs(r[1]), abs(r[2]), abs(r[3]))
    return m


def _covered_by_union(
    fp: tuple[float, float, float, float],
    pads: list[tuple[float, float, float, float]],
    *,
    tol: float,
) -> bool:
    """足迹方框是否被 pad 矩形并集完全覆盖（矩形分解法，轴对齐下精确）。

    把足迹按全部 pad 边缘切格（只取足迹内的边缘坐标），每格必须整体落入
    至少一个 pad——格不跨任何 pad 边缘，故对每 pad "格⊆pad 或格∩pad=∅"
    二选一，判定对轴对齐矩形并集**精确**（近似只在"圆球→外接方"一步，
    保守方向，见模块 docstring 声明）。

    局限（如实声明）：本判定只认 4 数轴对齐矩形——旋转 pad 若以 AABB 进
    schema，AABB ≥ 实际 pad，覆盖判定系统性偏松（假 PASS 方向）；调用方
    应在 plan_solder_balls 用 ``pad_rotation_deg`` 声明旋转角（非 0 非 45°
    倍数 WARN）或人工复核足迹覆盖。
    """
    fx0, fy0, fx1, fy1 = fp
    xs = {fx0, fx1}
    ys = {fy0, fy1}
    for p in pads:
        if fx0 < p[0] < fx1:
            xs.add(p[0])
        if fx0 < p[2] < fx1:
            xs.add(p[2])
        if fy0 < p[1] < fy1:
            ys.add(p[1])
        if fy0 < p[3] < fy1:
            ys.add(p[3])
    xl = sorted(xs)
    yl = sorted(ys)
    for i in range(len(xl) - 1):
        for j in range(len(yl) - 1):
            cx0, cy0, cx1, cy1 = xl[i], yl[j], xl[i + 1], yl[j + 1]
            if not any(
                p[0] <= cx0 + tol and p[1] <= cy0 + tol
                and p[2] >= cx1 - tol and p[3] >= cy1 - tol
                for p in pads
            ):
                return False
    return True


def _keepout_pairs(
    keepouts: Any, where: str
) -> list[tuple[str, tuple[float, float, float, float]]]:
    """keepout 输入规范化：裸 4 数矩形或 (name, rect) 二元组 → (name, rect)。"""
    pairs: list[tuple[str, tuple[float, float, float, float]]] = []
    for i, ko in enumerate(keepouts or ()):
        if isinstance(ko, (list, tuple)) and len(ko) == 2 and isinstance(ko[0], str):
            pairs.append((str(ko[0]), _rect4(ko[1], f"{where}[{i}]")))
        else:
            pairs.append((f"keepout_{i + 1}", _rect4(ko, f"{where}[{i}]")))
    return pairs


# ─── 鼓形截断几何（F3 前半：被上下金属面截断的球）───────────────────────────


def truncated_ball_profile(
    ball_d: float,
    gap: float,
    *,
    upper_z: float,
    lower_z: float,
    center_z: float | None = None,
) -> dict[str, Any]:
    """植球鼓形（双平面截断球）几何参数——纯几何，HFSS/openEMS 两用。

    惯例（**对称回流**，如实声明）：未截球半径 R=ball_d/2 > gap/2，球心置于
    两金属面**中点**（上下润湿各截掉一个矢高 R−gap/2 的球冠——缺省对称形
    态；非对称润湿用 ``center_z`` 覆盖，但球心须在两金属面之间且两面都真截
    到球 |球心距面| < R，否则报错）。Project1.aedt 参考做法=Sphere 被平面
    截断；圆柱近似会低估回路电感（反馈 F3 原话），本函数给出鼓形的全部
    落地参数：

    - 截断圆半径（上下两面，对称时相等）：
      ``trunc_radius = sqrt(R² − (gap/2)²)``（勾恒等式 R² = trunc² + (gap/2)²）；
    - 截掉球冠矢高（单侧）：``sagitta = R − gap/2``；
    - 鼓形最大半径=球赤道半径 R（赤道在间隙带内：gap/2 < R）。

    Parameters
    ----------
    ball_d : 球径（> gap，否则球桥接不了间隙——回流焊塌落后高度=间隙）。
    gap : 上下金属面间隙（与 upper_z−lower_z 一致性受检）。
    upper_z, lower_z : 上/下金属面 z（截断平面）。
    center_z : 球心 z（缺省 = (upper_z+lower_z)/2 对称惯例）。

    Returns
    -------
    dict（``kind="truncated_ball_profile"``）：球心/半径/截断圆半径/矢高/
    cut box 参数（HFSS Sphere+Box intersect 落地直接可用）与 openEMS 阶梯
    网格近似局限注记。

    Raises
    ------
    FlipChipPlanError
        ball_d ≤ gap（球不桥接/退化相切）、upper_z ≤ lower_z、gap 与
        upper_z−lower_z 不一致、球心越面（|球心距面| ≥ R：面截不到球=开路
        或相切退化）。
    """
    d = float(ball_d)
    g = float(gap)
    uz = float(upper_z)
    lz = float(lower_z)
    scale = max(abs(d), abs(g), abs(uz), abs(lz), 1.0)
    tol = 1e-9 * scale
    if not (d > 0.0) or not math.isfinite(d):
        raise FlipChipPlanError(
            f"ball_d 需正有限，实际 {ball_d!r}", details={"ball_d": ball_d})
    if not (g > 0.0) or not math.isfinite(g):
        raise FlipChipPlanError(
            f"gap 需正有限，实际 {gap!r}", details={"gap": gap})
    if uz <= lz:
        raise FlipChipPlanError(
            f"upper_z 需 > lower_z，实际 upper_z={uz:g} ≤ lower_z={lz:g}",
            details={"upper_z": uz, "lower_z": lz},
        )
    if abs((uz - lz) - g) > tol:
        raise FlipChipPlanError(
            f"gap 与 upper_z−lower_z 不一致：gap={g:g}，"
            f"upper_z−lower_z={uz - lz:g}（容差 {tol:g}）",
            details={"gap": g, "upper_z": uz, "lower_z": lz},
        )
    if d <= g + tol:
        raise FlipChipPlanError(
            f"球径须 > 间隙（球径 {d:g} ≤ 间隙 {g:g}）：球径=间隙为相切退化、"
            "球径<间隙球桥接不了两面（回流焊塌落后球高=间隙）——圆柱近似"
            "低估回路电感，鼓形以 d>g 截出",
            details={"ball_d": d, "gap": g},
        )
    r = d / 2.0
    cz = (uz + lz) / 2.0 if center_z is None else float(center_z)
    if not (lz <= cz <= uz):
        raise FlipChipPlanError(
            f"球心 z 须在两金属面之间 [{lz:g},{uz:g}]，实际 {cz:g}"
            "（不支持整球偏置到单侧的病态形态）",
            details={"center_z": cz, "lower_z": lz, "upper_z": uz},
        )
    dist_lo = cz - lz   # 球心到下金属面距离（截断平面距）
    dist_hi = uz - cz   # 球心到上金属面距离
    for label, dist in (("lower_z", dist_lo), ("upper_z", dist_hi)):
        if dist >= r - tol:
            raise FlipChipPlanError(
                f"面 {label} 截不到球：球心距该面 {dist:g} ≥ 球半径 {r:g}"
                "（面悬空=球与该金属开路，或相切退化点接触）",
                details={"face": label, "dist": dist, "radius": r},
            )
    trunc_lo = math.sqrt(r * r - dist_lo * dist_lo)
    trunc_hi = math.sqrt(r * r - dist_hi * dist_hi)
    return {
        "kind": "truncated_ball_profile",
        "ball_d": d,
        "gap": g,
        "radius": r,
        "center_z": cz,
        "upper_z": uz,
        "lower_z": lz,
        "trunc_radius_lower": trunc_lo,
        "trunc_radius_upper": trunc_hi,
        "trunc_radius": min(trunc_lo, trunc_hi),
        "sagitta_lower": r - dist_lo,
        "sagitta_upper": r - dist_hi,
        "drum_height": g,
        "max_radius": r,
        "convention": "symmetric_reflow",
        "cut_box": {
            "xy_half": r * _CUT_BOX_MARGIN_RATIO,
            "z_range": [lz, uz],
            "margin_ratio": _CUT_BOX_MARGIN_RATIO,
            "note": ("HFSS 落地=Sphere(origin=[cx,cy,center_z], radius=R) 与 "
                     "Box(xy 半宽 1.05R, z 跨 [lower_z,upper_z]) intersect——"
                     "切盒外扩 5% 避免与球赤道相切的退化布尔"),
        },
        "openems_limitation": (
            "openEMS CSX 无球原生布尔截断形态：鼓形侧面圆弧只能阶梯网格近似"
            "（逐层 Box 锯齿），HFSS 侧为精确截断球——跨保真比较时如实标注"
            "该近似差"),
    }


# ─── 植球阵列/环布点规划（F3 后半：两规则自动布点）──────────────────────────


def plan_solder_balls(
    pads: Any,
    *,
    ball_d: float,
    upper_z: float,
    lower_z: float,
    min_pitch_clearance: float = 30.0,
    keepouts: Any = (),
    grid: Any = None,
    pad_rotation_deg: float = 0.0,
    units: str = "mm",
) -> dict[str, Any]:
    """植球阵列/环布点规划——两规则自动布点（反馈 F3 原文规则）+ keepout 剔除。

    规则（反馈 F3 原文照录，违者进 skipped 如实清单、不进 balls）：

    1. **足迹完全落在地金属并集上**：每球足迹=球的外接正方形（半宽 R），
       必须被 pads 矩形并集完全覆盖（矩形分解判定，见模块 docstring——对
       轴对齐并集精确，保守近似只在"圆→方"）；
    2. **相邻球净距 ≥ min_pitch_clearance**（反馈原值 30 μm）：球心距 −
       球径 ≥ 净距（圆球精确边距）。用户第一版节距=球径 → 球球相撞、HFSS
       拒解——本规则按贪心（候选序先到先得）拒绝违者；**安全节距 =
       ball_d + min_pitch_clearance**。

    外加 P13 keepout 剔除（对齐 K6 filter_keepout_candidates 语义，见分层
    声明）：候选外接框与任一 keepout 两轴交叠均 > tol 即剔除。

    Parameters
    ----------
    pads : 地金属足迹矩形清单（元素 4 数 [x0,y0,x1,y1]；并集=可植球区）。
    ball_d : 球径（> upper_z−lower_z，鼓形截断前提）。
    upper_z, lower_z : 上/下金属面 z（截断平面；鼓形参数逐球内嵌）。
    min_pitch_clearance : 相邻球净距（>0 严格——0 意味允许相切，即反馈中
        HFSS 拒解的病灶形态）。
    keepouts : 禁入矩形清单（元素=裸 4 数矩形或 (name, rect) 二元组）。
    grid : None=pad 中心单球（每 pad 一球）；``(pitch_x, pitch_y)``=规则网
        格布点（球心距节距，格点锚定在 pads 并集 bbox 左下角，步进节距，
        行主序；覆盖/净距/keepout 三规则过滤后即成阵列或环——环=框形 pad
        并集上的网格存活集）。安全缺省节距建议 ball_d+min_pitch_clearance。
    pad_rotation_deg : pads 的物理旋转角声明（度；缺省 0=轴对齐）。4 数
        rect schema 只能表达轴对齐矩形——旋转 pad 以 AABB 进清单时覆盖判
        定系统性偏松（假 PASS 方向，见模块 docstring 声明）；非 0 且非 45°
        倍数时 plan notes 追加 WARN 条目（建议轴对齐布局或人工复核足迹覆
        盖），45°/90° 等倍数角豁免（布局常用正交/斜切角）。
    units : 单位标签（um|mm|m，数值不换算只记账）。

    Returns
    -------
    dict（``kind="solder_ball_plan"``）：balls（每球名/球心/外接框/6 数
    bbox/鼓形参数）、skipped（逐条 rule=footprint|clearance|keepout + 人话
    detail）、profile（公共鼓形截面）、自检与近似声明。

    Raises
    ------
    FlipChipPlanError
        pads 空/非法、min_pitch_clearance ≤ 0、grid 非法或候选超上限、
        pad_rotation_deg 非数值/非有限、ball_d ≤ 间隙（经
        truncated_ball_profile）。
    """
    u = _norm_units(units, "plan_solder_balls")
    pad_list = [_rect4(p, f"pads[{i}]") for i, p in enumerate(pads or ())]
    if not pad_list:
        raise FlipChipPlanError(
            "pads 需非空地金属足迹矩形清单", details={"n_pads": len(pad_list)})
    d = float(ball_d)
    if not (d > 0.0) or not math.isfinite(d):
        raise FlipChipPlanError(
            f"ball_d 需正有限，实际 {ball_d!r}", details={"ball_d": ball_d})
    clr = float(min_pitch_clearance)
    if not (clr > 0.0) or not math.isfinite(clr):
        raise FlipChipPlanError(
            f"min_pitch_clearance 需 >0（0=允许相切——球球相撞 HFSS 会"
            f"拒解），实际 {min_pitch_clearance!r}",
            details={"min_pitch_clearance": min_pitch_clearance},
        )
    try:
        rot_deg = float(pad_rotation_deg)
    except (TypeError, ValueError) as exc:
        raise FlipChipPlanError(
            f"pad_rotation_deg 需数值（度），实际 {pad_rotation_deg!r}",
            details={"pad_rotation_deg": str(pad_rotation_deg)[:100]},
        ) from exc
    if not math.isfinite(rot_deg):
        raise FlipChipPlanError(
            f"pad_rotation_deg 需有限数值，实际 {pad_rotation_deg!r}",
            details={"pad_rotation_deg": str(pad_rotation_deg)[:100]},
        )
    # 旋转 pad 的 AABB 偏松告警（非 0 且非 45° 倍数才提示；45°/90° 倍数豁免
    # ——布局常用正交/斜切角，偏松量纲固定且调用方已显式声明知情）。
    rot_is_multiple_of_45 = abs(rot_deg % 45.0) <= 1e-9
    rot_warn = rot_deg != 0.0 and not rot_is_multiple_of_45
    scale = _scale_of([*pad_list, (-d, -d, d, d)])
    tol = 1e-9 * scale
    r = d / 2.0
    profile = truncated_ball_profile(
        d, float(upper_z) - float(lower_z),
        upper_z=upper_z, lower_z=lower_z)
    ko_pairs = _keepout_pairs(keepouts, "keepouts")

    # ── 候选生成（grid=None: pad 中心单球；grid=(px,py): 规则网格）────────
    pitch: tuple[float, float] | None = None
    if grid is None:
        cand_centers = [
            ((p[0] + p[2]) / 2.0, (p[1] + p[3]) / 2.0) for p in pad_list]
        mode = "pad_center"
    else:
        if (not isinstance(grid, (list, tuple)) or len(grid) != 2):
            raise FlipChipPlanError(
                f"grid 需 None 或 (pitch_x, pitch_y) 二元组，实际 {grid!r}",
                details={"grid": repr(grid)[:200]},
            )
        try:
            px, py = float(grid[0]), float(grid[1])
        except (TypeError, ValueError) as exc:
            raise FlipChipPlanError(
                f"grid 节距含非数值，实际 {grid!r}", details={"grid": str(grid)},
            ) from exc
        if not (px > 0.0 and py > 0.0) or not (math.isfinite(px) and math.isfinite(py)):
            raise FlipChipPlanError(
                f"grid 节距需正有限，实际 {grid!r}", details={"grid": str(grid)})
        pitch = (px, py)
        mode = "grid"
        x_min = min(p[0] for p in pad_list)
        y_min = min(p[1] for p in pad_list)
        x_max = max(p[2] for p in pad_list)
        y_max = max(p[3] for p in pad_list)
        nx = math.floor((x_max - x_min) / px + tol) + 1
        ny = math.floor((y_max - y_min) / py + tol) + 1
        if nx * ny > _MAX_GRID_CANDIDATES:
            raise FlipChipPlanError(
                f"网格候选 {nx}×{ny}={nx * ny} 超上限 {_MAX_GRID_CANDIDATES}"
                f"（节距过细或域过大）——请粗化 grid 节距",
                details={"nx": nx, "ny": ny, "pitch": [px, py]},
            )
        cand_centers = [
            (x_min + j * px, y_min + i * py)
            for i in range(ny) for j in range(nx)]

    # ── 三规则过滤（footprint → clearance → keepout；skipped 如实清单）────
    balls: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    accepted_centers: list[tuple[float, str, tuple[float, float]]] = []
    min_gap_seen = math.inf
    for idx, (cx, cy) in enumerate(cand_centers):
        cand_id = f"cand_{idx:03d}"
        fp = (cx - r, cy - r, cx + r, cy + r)
        # 规则 1：足迹完全落在地金属并集上（矩形分解精确判定）
        if not _covered_by_union(fp, pad_list, tol=tol):
            skipped.append({
                "candidate": cand_id, "center": [cx, cy],
                "footprint": [*fp], "rule": "footprint",
                "detail": (f"候选 {cand_id} 球心 ({cx:g},{cy:g}) 足迹外接方 "
                           f"x[{fp[0]:g},{fp[2]:g}] y[{fp[1]:g},{fp[3]:g}] 未"
                           "被地金属并集完全覆盖——足迹须整体落在可植球金属上"
                           "（规则 1：足迹完全落在地金属并集上）"),
            })
            continue
        # 规则 2：相邻球净距 ≥ min_pitch_clearance（圆球精确边距）
        viol = None
        for nb_id, _nb_name, (nx_, ny_) in accepted_centers:
            dist = math.hypot(cx - nx_, cy - ny_)
            gap = dist - d
            min_gap_seen = min(min_gap_seen, gap)
            if gap < clr - tol:
                viol = (nb_id, dist, gap)
                break
        if viol is not None:
            nb_id, dist, gap = viol
            skipped.append({
                "candidate": cand_id, "center": [cx, cy],
                "footprint": [*fp], "rule": "clearance",
                "neighbor": nb_id, "center_distance": dist, "edge_gap": gap,
                "detail": (f"候选 {cand_id} 球心 ({cx:g},{cy:g}) 与已收球 "
                           f"{nb_id} 球心距 {dist:g}、边距 {gap:g} < 净距要求 "
                           f"{clr:g}（规则 2：相邻球净距 ≥ {clr:g}；教训："
                           "节距取球径会球球相撞、HFSS 拒解；安全节距 "
                           f"= 球径 {d:g} + 净距 {clr:g} = {d + clr:g}）"),
            })
            continue
        # 规则 3（P13）：keepout 剔除（K6 filter_keepout_candidates 同语义）
        ko_hit = None
        for ko_name, (kx0, ky0, kx1, ky1) in ko_pairs:
            ov_x = _ov1d(fp[0], fp[2], kx0, kx1)
            ov_y = _ov1d(fp[1], fp[3], ky0, ky1)
            if ov_x > tol and ov_y > tol:
                ko_hit = (ko_name, [ov_x, ov_y])
                break
        if ko_hit is not None:
            ko_name, ov = ko_hit
            skipped.append({
                "candidate": cand_id, "center": [cx, cy],
                "footprint": [*fp], "rule": "keepout",
                "keepout": ko_name, "overlap": ov,
                "detail": (f"候选 {cand_id} 球心 ({cx:g},{cy:g}) 外接框与 "
                           f"keepout {ko_name} 两轴交叠 {ov[0]:g}×{ov[1]:g}"
                           "——按'植球外接框 ∩ 信号引线矩形'剔除（P13：Ø80 "
                           "球压引线球顶把信号短到盖板 S21≈−99.6 dB）"),
            })
            continue
        # 三规则全过 → 收球
        bname = f"ball_{len(balls) + 1:02d}"
        accepted_centers.append((cand_id, bname, (cx, cy)))
        balls.append({
            "name": bname,
            "candidate": cand_id,
            "center": [cx, cy],
            "footprint": [*fp],
            "bbox": [fp[0], fp[1], profile["lower_z"],
                     fp[2], fp[3], profile["upper_z"]],
            "ball_d": d,
            "center_z": profile["center_z"],
            "trunc_radius": profile["trunc_radius"],
            "sagitta": profile["sagitta_upper"],
            "upper_z": profile["upper_z"],
            "lower_z": profile["lower_z"],
        })

    # ── 自检（后验：收球两两净距全部达标——实现一致性断言）─────────────────
    for i in range(len(balls)):
        for j in range(i + 1, len(balls)):
            bi, bj = balls[i], balls[j]
            dist = math.hypot(bi["center"][0] - bj["center"][0],
                              bi["center"][1] - bj["center"][1])
            if dist - d < clr - tol:
                raise FlipChipPlanError(
                    f"自检失败：已收球 {bi['name']}/{bj['name']} 边距 "
                    f"{dist - d:g} < 净距 {clr:g}（过滤器实现不一致）",
                    details={"balls": [bi["name"], bj["name"]]},
                )

    notes: list[str] = [
        "足迹=外接正方形（保守：圆球在方框判负的角区可能仍放得下）",
        "keepout/净距只用 xy 投影——pad 所在金属层 z 由调用方保证",
        f"网格锚定 pads 并集 bbox 左下角、行主序贪心（候选序先到先得，"
        f"候选上限 {_MAX_GRID_CANDIDATES}）",
    ]
    if rot_warn:
        notes.append(
            f"WARN：pad_rotation_deg={rot_deg:g}（非 0 且非 45° 倍数）——"
            "旋转 pad 以 AABB 进 4 数 rect schema，AABB≥实际 pad，覆盖判定"
            "系统性偏松（假 PASS 方向），建议轴对齐布局或人工复核足迹覆盖"
        )
    return {
        "kind": "solder_ball_plan",
        "units": u,
        "ball_d": d,
        "min_pitch_clearance": clr,
        "mode": mode,
        "pitch": list(pitch) if pitch is not None else None,
        "pads": [[*p] for p in pad_list],
        "keepouts": [{"name": n, "rect": [*rc]} for n, rc in ko_pairs],
        "profile": profile,
        "balls": balls,
        "skipped": skipped,
        "n_candidates": len(cand_centers),
        "n_balls": len(balls),
        "n_skipped": len(skipped),
        "checks": {
            "footprint_on_metal_union": True,
            "min_pitch_clearance": True,
            "keepouts_applied": True,
            "post_verified": True,
        },
        "rules": {
            "footprint": "球外接方被 pads 并集完全覆盖（矩形分解判定，"
                         "轴对齐精确；圆→方保守近似）",
            "clearance": f"球心距 − 球径 ≥ {clr:g}（圆球精确边距；安全节距 "
                         f"= {d:g} + {clr:g} = {d + clr:g}）",
            "keepout": "外接框 ∩ keepout 两轴交叠 > tol 即剔除（K6 "
                       "filter_keepout_candidates 同语义）",
        },
        "notes": notes,
    }


# ─── 开窗盖板规划（F4：lid(... windows=[...]) + 窗缘植球剔除）───────────────


def plan_lid_windows(
    lid_bbox: Any,
    *,
    windows: Any,
    ball_clearance: float = 30.0,
    balls: Any = None,
    units: str = "mm",
) -> dict[str, Any]:
    """盖板开窗规划——窗口从底面通孔开窗 + 窗缘净距内植球剔除（反馈 F4）。

    窗口语义（如实声明）：每窗口=**全厚度通孔**（z 跨整个盖板——探针/加电
    通道，反馈 F4"倒装盖板必须给探针/加电留窗"）；HFSS 落地=盖板 Box 与窗
    口 Box subtract（落地层），多窗交叠合法（subtract 天然并集，如实注记）。

    自检（违反即 FlipChipPlanError，fail-fast）：

    - 窗在盖板内（xy 全包，容差 1e-9×尺度）；
    - 窗不吞盖板（两轴跨度都 ≥ 盖板跨度=盖板消失，报错；单轴全跨=盖板被
      切成条带，合法但注记如实提示）；
    - 窗口非退化（两轴跨度 >0）。

    植球剔除（``balls`` 给定时）：球外接框到窗口矩形 xy 距离 < ball_clearance
    即剔除（窗口边缘剔除半径，反馈原值 30 μm；与 plan_solder_balls 净距规则
    同容差方向：≥ clearance−tol 保留）。``balls`` 接受
    :func:`plan_solder_balls` 产物整包（取其 ``balls`` 段）或球 dict 清单
    （每项需 name+footprint）。

    Returns
    -------
    dict（``kind="lid_window_plan"``）：windows（名/xy 矩形/穿透 cut box）、
    balls_kept / balls_skipped（窗缘剔除逐条带距离与命中窗口）、checks、
    notes。

    Raises
    ------
    FlipChipPlanError
        lid_bbox 非法、windows 空/退化/越出盖板/吞盖板、ball_clearance < 0、
        balls 元素缺 name/footprint。
    """
    u = _norm_units(units, "plan_lid_windows")
    lo, hi = _bbox6(lid_bbox, "lid_bbox")
    lid_rect = (lo[0], lo[1], hi[0], hi[1])
    scale = max(abs(v) for v in (*lo, *hi))
    tol = 1e-9 * scale
    bc = float(ball_clearance)
    if bc < 0.0 or not math.isfinite(bc):
        raise FlipChipPlanError(
            f"ball_clearance 需 ≥0，实际 {ball_clearance!r}",
            details={"ball_clearance": ball_clearance},
        )
    win_list = [_rect4(w, f"windows[{i}]") for i, w in enumerate(windows or ())]
    if not win_list:
        raise FlipChipPlanError(
            "windows 需非空窗口矩形清单（不开窗请直接建盖板，不走本规划器）",
            details={"n_windows": 0},
        )
    # ── 自检：窗在盖板内 / 不吞盖板 ──────────────────────────────────────
    for i, w in enumerate(win_list):
        if (w[0] < lid_rect[0] - tol or w[1] < lid_rect[1] - tol
                or w[2] > lid_rect[2] + tol or w[3] > lid_rect[3] + tol):
            raise FlipChipPlanError(
                f"windows[{i}] 越出盖板 xy 范围：窗 [{w[0]:g},{w[1]:g},"
                f"{w[2]:g},{w[3]:g}] ⊄ 盖板 [{lid_rect[0]:g},{lid_rect[1]:g},"
                f"{lid_rect[2]:g},{lid_rect[3]:g}]（自检：窗在盖板内）",
                details={"window_index": i, "window": [*w],
                         "lid_xy": [*lid_rect]},
            )
        full_x = (w[2] - w[0]) >= (lid_rect[2] - lid_rect[0]) - tol
        full_y = (w[3] - w[1]) >= (lid_rect[3] - lid_rect[1]) - tol
        if full_x and full_y:
            raise FlipChipPlanError(
                f"windows[{i}] 两轴全跨=吞掉整块盖板（自检：窗不吞盖板）"
                "——开窗须给盖板留料",
                details={"window_index": i, "window": [*w],
                         "lid_xy": [*lid_rect]},
            )
    # ── 穿透 cut box（全厚度通孔）─────────────────────────────────────────
    windows_out: list[dict[str, Any]] = []
    for i, w in enumerate(win_list):
        full_x = (w[2] - w[0]) >= (lid_rect[2] - lid_rect[0]) - tol
        full_y = (w[3] - w[1]) >= (lid_rect[3] - lid_rect[1]) - tol
        windows_out.append({
            "name": f"window_{i + 1}",
            "rect": [*w],
            "cut_box": [w[0], w[1], lo[2], w[2], w[3], hi[2]],
            "z_range": [lo[2], hi[2]],
            "through": True,
            "splits_lid": bool(full_x or full_y),
        })
    # ── 窗缘植球剔除 ──────────────────────────────────────────────────────
    if balls is None:
        ball_items: list[dict[str, Any]] = []
        balls_from = "none"
    elif isinstance(balls, dict) and balls.get("kind") == "solder_ball_plan":
        ball_items = list(balls.get("balls") or ())
        balls_from = "plan"
    elif isinstance(balls, (list, tuple)):
        ball_items = list(balls)
        balls_from = "list"
    else:
        raise FlipChipPlanError(
            f"balls 需 None、solder_ball_plan dict 或球 dict 清单，实际 "
            f"{type(balls).__name__}",
            details={"type": type(balls).__name__},
        )
    kept: list[dict[str, Any]] = []
    skipped_balls: list[dict[str, Any]] = []
    for b in ball_items:
        if not isinstance(b, dict) or "name" not in b or "footprint" not in b:
            raise FlipChipPlanError(
                f"balls 元素需含 name 与 footprint 的球 dict，实际 {b!r}",
                details={"ball": repr(b)[:200]},
            )
        fp = _rect4(b["footprint"], f"balls[{b['name']}].footprint")
        hits: list[tuple[str, float]] = []
        for w in windows_out:
            wx0, wy0, wx1, wy1 = w["rect"]
            dx = _gap1d(fp[0], fp[2], wx0, wx1)
            dy = _gap1d(fp[1], fp[3], wy0, wy1)
            dist = math.hypot(dx, dy)  # 相交时 dx=dy=0 → dist=0
            if dist < bc - tol:
                hits.append((w["name"], dist))
        if hits:
            worst = min(hits, key=lambda h: h[1])
            skipped_balls.append({
                "ball": str(b["name"]),
                "footprint": [*fp],
                "windows": [h[0] for h in hits],
                "distance": worst[1],
                "detail": (
                    f"球 {b['name']} 外接框距窗口 {worst[0]} 边缘 {worst[1]:g}"
                    f" < 剔除净距 {bc:g}——窗口边缘剔除半径内植球剔除（开窗时"
                    "自动把窗口边缘的植球剔除）"),
            })
        else:
            kept.append({"name": str(b["name"]), "footprint": [*fp]})
    return {
        "kind": "lid_window_plan",
        "units": u,
        "lid_bbox": [*lo, *hi],
        "windows": windows_out,
        "ball_clearance": bc,
        "balls_from": balls_from,
        "balls_kept": kept,
        "balls_skipped": skipped_balls,
        "n_windows": len(windows_out),
        "n_balls_kept": len(kept),
        "n_balls_skipped": len(skipped_balls),
        "checks": {
            "window_inside_lid": True,
            "window_not_swallow_lid": True,
            "windows_positive": True,
        },
        "notes": [
            "窗口=全厚度通孔（探针/加电通道）；多窗交叠合法（HFSS subtract "
            "天然并集）",
            "单轴全跨窗口会把盖板切成条带（splits_lid 如实标注；subtract 后"
            "盖板为多体，调用方按需 unite——同材料 unite 安全，混材料严禁 "
            "unite（Cu+Au unite 会静默吞材料）",
            "窗缘剔除判据=球外接框到窗口 xy 距离 < ball_clearance（方框近似"
            "，与 net 登记薄一致）",
        ],
    }


# ─── 转换桥（K5 em doctor 清单 schema；照 K6 to_doctor_manifest 先例）───────


def balls_to_doctor_manifest(
    plan: Any,
    *,
    net: str = "ground",
    material: str | None = None,
    keepouts: Any = None,
    ball_separation_keepouts: bool = False,
    min_pitch_clearance: float | None = None,
) -> dict[str, Any]:
    """植球 plan → em doctor 清单 dict（balls→objects + keepouts→keepouts 段）。

    照 K6 ``NetRegistry.to_doctor_manifest`` 先例：只产**纯 dict**（core/adapters
    分层均禁 import service 层 K5 ``run_em_doctor``），schema 字段名对齐
    em_doctor_service docstring（objects[name,bbox,net,kind,material?,
    thickness_z?] / keepouts[name,rect,z_range?,clearance?,applies_to?]），
    对齐正确性由测试端到端钉（test_flip_chip_primitives → run_em_doctor）。

    球体 objects 形态：每球 bbox=外接方 xy ± R × z [lower_z, upper_z]（鼓形
    赤道在间隙带内，xy 极值=球半径），net 缺省 ground（balls→ground net；独
    立 bump net 由 ``net`` 入参给——词汇 signal|ground|other，与 K5/K6 同），
    thickness_z=鼓形高度（间隙）。

    ``ball_separation_keepouts=True``：把**球间净距规则投影成 doctor keepout**
    （每收球一个 ko_<球名> 环带，applies_to=其余球，clearance=净距要求）——
    绕过规划器手工塞进的过近球会被 doctor 表#12 抓出：重叠=FAIL（侵入）、
    未触但净距不足=WARN（净距告警；恰在规划器容差边界上的球 doctor 会 WARN，
    WARN 不翻门，属 belt-and-braces 提示级）。

    Parameters
    ----------
    plan : :func:`plan_solder_balls` 产物（``kind="solder_ball_plan"``）。
    net : 球归属 net（signal|ground|other）。
    material : 球材料（如 "SAC305"；None=不带 material 字段）。
    keepouts : 覆盖用 keepout 清单（doctor 形态 dict 或 (name, rect) 对）；
        缺省透传 plan 自带 keepouts（规划期剔除依据，doctor 复核面）。
    ball_separation_keepouts : 是否投影球间净距环带（见上；缺省 False）。
    min_pitch_clearance : 环带净距阈值（缺省取 plan 值）。

    Raises
    ------
    FlipChipPlanError
        plan 非 solder_ball_plan / net 出词汇 / keepouts 形态非法。
    """
    if not isinstance(plan, dict) or plan.get("kind") != "solder_ball_plan":
        raise FlipChipPlanError(
            "balls_to_doctor_manifest: plan 需为 plan_solder_balls 产物"
            f"（kind='solder_ball_plan'），实际 {type(plan).__name__}"
            f"/kind={plan.get('kind') if isinstance(plan, dict) else None!r}"
            "——禁止 hand-crafted plan 绕过规划器",
            details={"kind": plan.get("kind") if isinstance(plan, dict) else None},
        )
    if net not in DOCTOR_NETS:
        raise FlipChipPlanError(
            f"net 需 {'|'.join(DOCTOR_NETS)}，实际 {net!r}",
            details={"net": str(net)},
        )
    balls = list(plan.get("balls") or ())
    objects: list[dict[str, Any]] = []
    for b in balls:
        entry: dict[str, Any] = {
            "name": str(b["name"]),
            "net": net,
            "kind": "metal",
            "bbox": [float(v) for v in b["bbox"]],
        }
        if material is not None:
            entry["material"] = str(material)
        if b.get("upper_z") is not None and b.get("lower_z") is not None:
            entry["thickness_z"] = float(b["upper_z"]) - float(b["lower_z"])
        objects.append(entry)
    # keepouts 段：显式入参覆盖，否则透传 plan 自带（规划期剔除依据）
    if keepouts is not None:
        pairs = _keepout_pairs(keepouts, "keepouts")
        ko_out: list[dict[str, Any]] = [
            {"name": n, "rect": [*rc]} for n, rc in pairs]
    else:
        raw = list(plan.get("keepouts") or ())
        ko_out = [
            {"name": str(k["name"]), "rect": [float(v) for v in k["rect"]]}
            for k in raw]
    if ball_separation_keepouts:
        clr = (float(min_pitch_clearance) if min_pitch_clearance is not None
               else float(plan["min_pitch_clearance"]))
        names = [str(b["name"]) for b in balls]
        for b in balls:
            others = [n for n in names if n != str(b["name"])]
            ko_out.append({
                "name": f"ko_{b['name']}",
                "rect": [float(v) for v in b["footprint"]],
                "clearance": clr,
                "applies_to": others,
            })
    return {
        "units": str(plan["units"]),
        "objects": objects,
        "keepouts": ko_out,
    }
