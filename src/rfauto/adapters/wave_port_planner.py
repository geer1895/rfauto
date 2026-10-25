"""wave_port_cpw 规划器——CPW 波端口的带不变量生成器（K7，aurora_k 战役）。

用户反馈 §6.1 P12 / §6.2 F6（2026-10-23 二轮实测，D:\\IPD调研\\...\\rfauto使用体验
与反馈.md）：手画 CPW 波端口 sheet 五类错——aperture 不含金属（13:05 旧端口
ZStart=0/Height=190，金属层在 200.2–205.2 μm，孔径没圈住导体 → 照样能建/能解/
能导出，解出 L≈0.135 nH 等效短路假结果）/端口面叠 Radiation（19:29 v5 六面全
辐射）/aperture 取整块衬底宽/积分线 z 在衬底内部（102.6）/衬底不延伸到端口面。
HFSS 的 ValidateDesign 只查语法/拓扑/材料，不查端口孔径语义——本模块把波端口
做成**带不变量的生成器**：纯几何规划 + 六条不变量逐条断言，违反即在建模阶段
报错（ValueError 家族），不带病求解。

六条不变量（反馈 P12 建议块原文照录）：

1. 端口面在求解域边界上（不是内部 sheet）；
2. aperture 的 z 覆盖衬底 + 金属 + 金属上方 3×隙空气；
3. aperture 横向两端落在地金属上（不是空气/衬底边沿），且不取整块衬底宽度；
4. 积分线从地边沿跨到信号边沿，z 在金属层中心；
5. 端口面不叠加 Radiation；面内 aperture 以外默认 PEC 作端口壁；
6. 衬底/叠层沿信号方向延伸到端口面（不能出现"空气悬空 CPW"）。

分层：本模块为**纯规划层**——零 pyaedt 依赖（纯数值几何），可测核心；HFSS 落地
（建 sheet + 赋波端口）在 hfss_builder_utils.wave_port_cpw（薄落地层，几何全在本
规划器）。单位约定与 K6 NetRegistry 同源：um|mm|m（plan 携带 units 标签，数值
一律调用方单位）。
"""

from __future__ import annotations

import math
from typing import Any

#: 端口面法向允许轴（z 法向端口不属 CPW 波端口族——CPW 截面在含 z 的平面内）。
PLANE_AXES: tuple[str, ...] = ("x", "y")

#: 单位别名（与 hfss_builder_utils._NET_UNIT_ALIASES 同源；分层契约无 import 关系，
#: 对齐由测试钉）。
_PLAN_UNITS: dict[str, str] = {"um": "um", "μm": "um", "mm": "mm", "m": "m"}


class WavePortPlanError(ValueError):
    """wave_port_cpw 规划失败：六不变量任一违反或输入几何非法。

    继承 ValueError（任务契约：不变量违反 → ValueError 带人话证据），携带
    ``details["violations"]``（[(条号, 证据文案), ...]，建模脚本可编程消费）。
    建模阶段直接抛出（fail-fast），代替"解出 0.135 nH 才发现端口错"。
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


# ─── 内部几何小工具 ──────────────────────────────────────────────────────────


def _bbox6(value: Any, where: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """6 数 bbox → (lo, hi) 三元组对（逐轴 min/max 强制；非法即 WavePortPlanError）。"""
    if not isinstance(value, (list, tuple)) or len(value) != 6:
        raise WavePortPlanError(
            f"{where}: bbox 需 6 数 [x0,y0,z0,x1,y1,z1]，实际 {value!r}",
            details={"where": where, "value": repr(value)[:200]},
        )
    try:
        nums = [float(v) for v in value]  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise WavePortPlanError(
            f"{where}: bbox 含非数值: {value!r}",
            details={"where": where},
        ) from exc
    if not all(math.isfinite(n) for n in nums):
        raise WavePortPlanError(
            f"{where}: bbox 含非有限值: {value!r}",
            details={"where": where},
        )
    lo = tuple(min(nums[i], nums[i + 3]) for i in range(3))
    hi = tuple(max(nums[i], nums[i + 3]) for i in range(3))
    return lo, hi  # type: ignore[return-value]


def _union(boxes: list[tuple[tuple[float, ...], tuple[float, ...]]]) -> tuple[float, ...]:
    """bbox 列表的并包（逐轴 min/max；空列表调用方先拦）。"""
    lo = tuple(min(b[0][i] for b in boxes) for i in range(3))
    hi = tuple(max(b[1][i] for b in boxes) for i in range(3))
    return (*lo, *hi)  # type: ignore[return-value]


def _span_contains(
    box: tuple[tuple[float, ...], tuple[float, ...]], axis: int, at: float, tol: float
) -> bool:
    """box 在 axis 上的区间是否包含 at（含 tol 容差）。"""
    return box[0][axis] - tol <= at <= box[1][axis] + tol


# ─── 规划主入口 ──────────────────────────────────────────────────────────────


def plan_wave_port_cpw(
    domain_bbox: Any,
    substrate_bbox: Any,
    signal_bbox: Any,
    ground_bboxes: Any,
    gap: float,
    *,
    plane_axis: str,
    plane_at: float,
    metal_z_range: Any,
    z_top_air_factor: float = 3.0,
    aperture_z_range: Any = None,
    aperture_lateral_range: Any = None,
    integration_line_z: float | None = None,
    radiation_on_port_plane: bool = False,
    lateral_margin_factor: float = 5.0,
    units: str = "mm",
    tol: float | None = None,
) -> dict[str, Any]:
    """规划一个 CPW 波端口（纯几何，零 pyaedt 依赖；六不变量逐条断言）。

    输入一律 6 数 bbox ``[x0, y0, z0, x1, y1, z1]``（调用方单位，um/mm/m 均可，
    全部同单位）；坐标轴约定：端口面法向 = ``plane_axis``（x|y），横向轴 = 另一
    个水平轴，纵向恒为 z（CPW 叠层方向）。

    Parameters
    ----------
    domain_bbox : 求解域（空气盒）bbox——不变量 1 的边界判据。
    substrate_bbox : 端口处介质叠层（衬底+介质层并包）bbox——不变量 2/6。
    signal_bbox : 端口处信号导体 bbox（多层金属叠段可传并包）。
    ground_bboxes : 端口两侧地金属 bbox 列表（逐对象传，规划器按横向位置分侧）。
    gap : CPW 隙宽（正数；金属上方空气窗 = z_top_air_factor × gap）。
    plane_axis : 端口面法向轴（"x"|"y"）。
    plane_at : 端口面在法向轴上的坐标（必须 = 求解域边界面之一，不变量 1）。
    metal_z_range : 金属层 z 区间 ``(z0, z1)``（薄片金属允许 z0==z1）。
    z_top_air_factor : 金属上方空气窗系数（缺省 3.0 = 3×gap，反馈 P12 第 2 条）。
    aperture_z_range : 显式孔径 z 窗口（旧手画端口复现入口：给 13:05 的
        ``(0, 190)`` 会被不变量 2 当场拦下）；缺省自动 = [衬底底, 金属顶+3×gap]。
    aperture_lateral_range : 显式孔径横向窗口（同上：旧版整块衬底宽 ±300 会
        被不变量 3 拦下）；缺省自动 = 信号两侧各向地内探 lateral_margin_factor×gap
        （被地外沿钳制，端点必落金属上）。
    integration_line_z : 显式积分线 z（13:05 的 102.6 会被不变量 4 拦下）；
        缺省自动 = 金属层中心。
    radiation_on_port_plane : 调用方声明"端口面当前已被叠辐射"（19:29 v5 六面
        全辐射状态）→ 不变量 5 当场拦下；缺省 False=未叠/尚未赋边界。
    lateral_margin_factor : 自动横向探入系数（×gap，缺省 5.0）。
    units : 坐标单位标签（um|mm|m，随 plan 透传给落地层拼显式单位串）。
    tol : 几何重合容差（缺省 1e-6 × 坐标尺度，单位无关）。

    Returns
    -------
    plan dict（``kind="wave_port_cpw_plan"``）：``plane`` / ``sheet``（pyaedt
    create_rectangle 直用形态，#310 尺寸序）/ ``aperture`` / ``integration_line``
    / ``boundary_config``（端口面排除辐射+aperture 外 PEC 壁等落地指令）/
    ``invariants``（1–6 逐条 ok+证据）/ ``notes``。

    Raises
    ------
    WavePortPlanError
        六不变量任一违反（一条报错聚合全部违反项，逐条带条号+数值证据+会导致
        什么假结果的人话），或输入几何/参数非法。

    Examples
    --------
    13:05 旧端口参数（um 制，八角电感工程）直接被拦::

        >>> plan_wave_port_cpw(
        ...     domain_bbox=[-630, -660, -40, 630, 640, 620],
        ...     substrate_bbox=[-330, -660, 0.0, 330, 340, 200.2],
        ...     signal_bbox=[6.47, -660, 200.2, 136.47, -415.0, 205.2],
        ...     ground_bboxes=[[-330, -660, 200.2, -23.53, -390, 205.2],
        ...                    [166.47, -660, 200.2, 330, -390, 205.2]],
        ...     gap=30.0, plane_axis="y", plane_at=-660.0,
        ...     metal_z_range=(200.2, 205.2),
        ...     aperture_z_range=(0.0, 190.0))          # doctest: +SKIP
        Traceback (most recent call last):
        ...
        rfauto.adapters.wave_port_planner.WavePortPlanError: 违反第 2 条: ...
    """
    # ── 输入收敛 ────────────────────────────────────────────────────────────
    u = _PLAN_UNITS.get(str(units).strip())
    if u is None:
        raise WavePortPlanError(
            f"units 需 um|mm|m，实际 {units!r}",
            details={"units": str(units)},
        )
    dom = _bbox6(domain_bbox, "domain_bbox")
    sub = _bbox6(substrate_bbox, "substrate_bbox")
    sig = _bbox6(signal_bbox, "signal_bbox")
    gnd_raw = list(ground_bboxes or [])
    grounds = [_bbox6(g, f"ground_bboxes[{i}]") for i, g in enumerate(gnd_raw)]
    try:
        gap = float(gap)
    except (TypeError, ValueError) as exc:
        raise WavePortPlanError(f"gap 非数值: {gap!r}") from exc
    if gap <= 0.0:
        raise WavePortPlanError(
            f"gap 需为正数（CPW 隙宽），实际 {gap!r}",
            details={"gap": gap},
        )
    factor = float(z_top_air_factor)
    if factor < 0.0:
        raise WavePortPlanError(
            f"z_top_air_factor 需 ≥ 0，实际 {factor!r}",
            details={"z_top_air_factor": factor},
        )
    if float(lateral_margin_factor) < 0.0:
        raise WavePortPlanError(
            f"lateral_margin_factor 需 ≥ 0，实际 {lateral_margin_factor!r}",
            details={"lateral_margin_factor": float(lateral_margin_factor)},
        )
    axis = str(plane_axis).strip().lower()
    if axis not in PLANE_AXES:
        raise WavePortPlanError(
            f"plane_axis 需 {'|'.join(PLANE_AXES)}（z 法向端口不属 CPW 波端口族——"
            "CPW 截面在含 z 的平面内），实际 "
            f"{plane_axis!r}",
            details={"plane_axis": str(plane_axis)},
        )
    ai = 0 if axis == "x" else 1          # 法向轴下标
    li = 1 - ai                            # 横向轴下标（x<->y）
    try:
        at = float(plane_at)
    except (TypeError, ValueError) as exc:
        raise WavePortPlanError(f"plane_at 非数值: {plane_at!r}") from exc
    if not isinstance(metal_z_range, (list, tuple)) or len(metal_z_range) != 2:
        raise WavePortPlanError(
            f"metal_z_range 需 2 数 (z0, z1)，实际 {metal_z_range!r}",
            details={"metal_z_range": repr(metal_z_range)[:120]},
        )
    try:
        mlo, mhi = sorted(float(v) for v in metal_z_range)
    except (TypeError, ValueError) as exc:
        raise WavePortPlanError(
            f"metal_z_range 含非数值: {metal_z_range!r}"
        ) from exc

    violations: list[tuple[int, str]] = []   # (条号, 人话证据)，raise 前聚合
    notes: list[str] = []

    # 坐标尺度自适应容差（单位无关：um 制数百 → 亚 nm 级；mm 制同比例）
    scale = max(
        1.0,
        max(abs(v) for v in (*dom[0], *dom[1], *sub[0], *sub[1],
                             *sig[0], *sig[1], *[v for g in grounds for v in (*g[0], *g[1])],
                             at, mlo, mhi)),
    )
    t = float(tol) if tol is not None else 1e-6 * scale

    # ── 不变量 1：端口面在求解域边界上 ─────────────────────────────────────
    dlo, dhi = dom[0][ai], dom[1][ai]
    on_lo = abs(at - dlo) <= t
    on_hi = abs(at - dhi) <= t
    if not (on_lo or on_hi):
        violations.append((
            1,
            f"端口面 {axis}={at:g} 不在求解域边界上（求解域 {axis} ∈ "
            f"[{dlo:g}, {dhi:g}]，距下界 {at - dlo:g}、距上界 {dhi - at:g}）——"
            "内部 sheet 波端口缺 PEC 背衬、端口模不纯（不变量第 1 条）；"
            "把求解域边界收到端口面（或改用带 PEC 背衬的内部端口方案）",
        ))
    face = "lo" if on_lo else "hi"

    # ── 不变量 6：衬底/叠层（含端口导体）延伸到端口面 ──────────────────────
    slo, shi = sub[0][ai], sub[1][ai]
    if not _span_contains(sub, ai, at, t):
        short = max(slo - at, at - shi)
        violations.append((
            6,
            f"衬底/叠层 {axis} ∈ [{slo:g}, {shi:g}] 未延伸到端口面 {axis}={at:g}"
            f"（差 {short:g}）——端口截面处 CPW 悬在空气里（'空气悬空 CPW'、"
            "台阶不连续），解出的不是器件的传输模（不变量第 6 条）",
        ))
    for label, box in [("信号导体", sig)] + [
        (f"地金属 ground_bboxes[{i}]", g) for i, g in enumerate(grounds)
    ]:
        if not _span_contains(box, ai, at, t):
            violations.append((
                6,
                f"{label} {axis} ∈ [{box[0][ai]:g}, {box[1][ai]:g}] 未延伸到端口面 "
                f"{axis}={at:g}——端口面切在导体中途=端口截面不完整（馈线止于域中"
                "=开路 stub 家族，不变量第 6 条/#174 家族）",
            ))

    # ── 地金属分侧（不变量 3 的几何前提）───────────────────────────────────
    s_lo, s_hi = sig[0][li], sig[1][li]
    left: list[tuple[float, tuple[float, ...], tuple[float, ...]]] = []
    right: list[tuple[float, tuple[float, ...], tuple[float, ...]]] = []
    for i, g in enumerate(grounds):
        if g[1][li] <= s_lo + t:            # 全部在信号左侧（地内沿 ≤ 信号左沿）
            left.append((i, g[0], g[1]))
        elif g[0][li] >= s_hi - t:          # 全部在信号右侧
            right.append((i, g[0], g[1]))
        else:
            violations.append((
                3,
                f"地金属 ground_bboxes[{i}] 横向 [{g[0][li]:g}, {g[1][li]:g}] 与信号 "
                f"[{s_lo:g}, {s_hi:g}] 交叠——CPW 信号与地短路（实测病灶：植球短信号 "
                "S21≈−99.6 dB / pad 与偶指共面接触 S21≈0 dB 的几何前提，不变量"
                "第 3 条前置）",
            ))
    if not left:
        violations.append((
            3,
            f"信号横向 [{s_lo:g}, {s_hi:g}] 左侧没有地金属——aperture 横向两端必须"
            "落在地金属上（G-S-G 截面，不变量第 3 条）",
        ))
    if not right:
        violations.append((
            3,
            f"信号横向 [{s_lo:g}, {s_hi:g}] 右侧没有地金属——aperture 横向两端必须"
            "落在地金属上（G-S-G 截面，不变量第 3 条）",
        ))

    # 分侧聚合（多块地/多层金属：内沿=靠信号最近者，外沿=并包）
    # 内沿块=靠信号最近的那块地（auto 探入按它的实际宽钳制——按并包宽钳制会
    # 让端点落进同侧两地之间的空隙，静态校验 hull 化同样放行：K20 审查 P1-1）
    left_inner_blk = max(left, key=lambda g: g[2][li]) if left else None
    right_inner_blk = min(right, key=lambda g: g[1][li]) if right else None
    left_inner = max(hi[li] for _i, _lo, hi in left) if left else None
    left_outer = min(lo[li] for _i, lo, _hi in left) if left else None
    right_inner = min(lo[li] for _i, lo, _hi in right) if right else None
    right_outer = max(hi[li] for _i, _lo, hi in right) if right else None

    # ── 不变量 2：aperture z 覆盖 衬底+金属+金属上方 3×隙空气 ─────────────
    z_need_lo = sub[0][2]
    z_need_hi = mhi + factor * gap
    if aperture_z_range is not None:
        if not isinstance(aperture_z_range, (list, tuple)) or len(aperture_z_range) != 2:
            raise WavePortPlanError(
                f"aperture_z_range 需 2 数 (z0, z1)，实际 {aperture_z_range!r}",
                details={"aperture_z_range": repr(aperture_z_range)[:120]},
            )
        try:
            z_lo, z_hi = sorted(float(v) for v in aperture_z_range)
        except (TypeError, ValueError) as exc:
            raise WavePortPlanError(
                f"aperture_z_range 含非数值: {aperture_z_range!r}"
            ) from exc
        if z_lo > z_need_lo + t or z_hi < z_need_hi - t:
            miss = []
            if z_lo > z_need_lo + t:
                miss.append(f"下界欠 {z_lo - z_need_lo:g}（衬底底 {z_need_lo:g}）")
            if z_hi < z_need_hi - t:
                miss.append(
                    f"上界欠 {z_need_hi - z_hi:g}（金属顶 {mhi:g} + "
                    f"{factor:g}×gap={factor * gap:g} 空气 = {z_need_hi:g}）"
                )
            violations.append((
                2,
                f"aperture z 窗口 [{z_lo:g}, {z_hi:g}] 未覆盖「衬底+金属+金属上方"
                f"{factor:g}×隙空气」（金属层 [{mlo:g}, {mhi:g}]；{'；'.join(miss)}）"
                "——端口孔径没圈住导体：HFSS 照样能建、能解、能导出 Touchstone，"
                "但端口解出的不是 CPW 模而是等效短路假结果（13:05 病灶：z 窗口 "
                "0–190 未覆盖金属 200.2–205.2 → 解出 L≈0.135 nH；不变量第 2 条）",
            ))
    else:
        z_lo, z_hi = z_need_lo, z_need_hi
    dzlo, dzhi = dom[0][2], dom[1][2]
    if z_lo < dzlo - t or z_hi > dzhi + t:
        violations.append((
            2,
            f"aperture z [{z_lo:g}, {z_hi:g}] 超出求解域 z [{dzlo:g}, {dzhi:g}]——"
            "孔径装不进域（扩域，或核对 substrate/metal z 与 z_top_air_factor）",
        ))

    # ── 不变量 3：aperture 横向两端落在地金属上，且不取整块衬底宽度 ────────
    if aperture_lateral_range is not None:
        if not isinstance(aperture_lateral_range, (list, tuple)) or len(aperture_lateral_range) != 2:
            raise WavePortPlanError(
                f"aperture_lateral_range 需 2 数 (lo, hi)，实际 {aperture_lateral_range!r}",
                details={"aperture_lateral_range": repr(aperture_lateral_range)[:120]},
            )
        try:
            a_lo, a_hi = sorted(float(v) for v in aperture_lateral_range)
        except (TypeError, ValueError) as exc:
            raise WavePortPlanError(
                f"aperture_lateral_range 含非数值: {aperture_lateral_range!r}"
            ) from exc
    elif left_inner is not None and right_inner is not None:
        desired = float(lateral_margin_factor) * gap
        # 逐块钳制：端点必须落进"某一块地"内，不能只落在并包 hull 里（K20 P1-1）
        pen_l = min(desired, left_inner_blk[2][li] - left_inner_blk[1][li])
        pen_r = min(desired, right_inner_blk[2][li] - right_inner_blk[1][li])
        if pen_l < desired or pen_r < desired:
            notes.append(
                f"地金属宽不足以容纳 {lateral_margin_factor:g}×gap 探入，探入被地"
                f"外沿钳制 pen_l={pen_l:g}/pen_r={pen_r:g}（期望 {desired:g}）"
            )
        a_lo, a_hi = left_inner - pen_l, right_inner + pen_r
    else:
        a_lo, a_hi = 0.0, 0.0  # 无地可落——已在上文记第 3 条violation，此处占位
    if left_inner is not None and not any(
            g[1][li] - t <= a_lo <= g[2][li] + t for g in left):
        violations.append((
            3,
            f"aperture 横向下端 {a_lo:g} 不落在左侧任何一块地金属上"
            f"（左侧地横向并包 [{float(left_outer):g}, {left_inner:g}]，逐块判定）"
            "（落进了隙/信号/地外空气/衬底边沿）——端口模式泄漏、"
            "端口阻抗错（不变量第 3 条：aperture 端必须压在地金属上）",
        ))
    if right_inner is not None and not any(
            g[1][li] - t <= a_hi <= g[2][li] + t for g in right):
        violations.append((
            3,
            f"aperture 横向上端 {a_hi:g} 不落在右侧任何一块地金属上"
            f"（右侧地横向并包 [{right_inner:g}, {float(right_outer):g}]，逐块判定）"
            "（落进了隙/信号/地外空气/衬底边沿）——端口"
            "模式泄漏、端口阻抗错（不变量第 3 条）",
        ))
    w_sub = sub[1][li] - sub[0][li]
    if (a_hi - a_lo) >= w_sub - t:
        violations.append((
            3,
            f"aperture 横向宽 {a_hi - a_lo:g} ≈ 整块衬底宽度 {w_sub:g}——把衬底/腔模"
            "一起圈进端口（13:05 旧版取整块衬底宽 ±300 病灶；不变量第 3 条后半："
            "两端收在地金属上）",
        ))

    # ── 不变量 4：积分线 地边沿→信号边沿，z 在金属层中心 ───────────────────
    zc_req = (mlo + mhi) / 2.0
    zc = zc_req if integration_line_z is None else float(integration_line_z)
    if not (mlo - t <= zc <= mhi + t):
        violations.append((
            4,
            f"积分线 z={zc:g} 不在金属层 [{mlo:g}, {mhi:g}] 内（金属层中心应为 "
            f"{zc_req:g}）——积分线悬在衬底/空气里，端口电压积分取错位置 → 模式/"
            "符号错、负电阻（13:05 病灶：积分线 z=102.6 在 200 μm 衬底内部；"
            "不变量第 4 条）",
        ))
    if integration_line_z is not None:
        notes.append(f"积分线 z 用显式覆盖值 {zc:g}（金属层中心 {zc_req:g}）")

    # ── 不变量 5：端口面不叠 Radiation ─────────────────────────────────────
    if radiation_on_port_plane:
        violations.append((
            5,
            "端口面当前被同时赋了 Radiation——端口模被外场吸收/模不干净（19:29 v5 "
            "病灶：空气盒 6 面全辐射、端口面也在内，HFSS 不报错但结果错；不变量"
            "第 5 条）：端口面只留波端口，面内 aperture 以外默认 PEC 作端口壁"
            "（CPW 地在该壁上收口，信号被隙隔开）",
        ))

    # ── 聚合报错（一条 WavePortPlanError 列全部违反项）────────────────────
    if violations:
        lines = [
            f"wave_port_cpw 规划失败：{len(violations)} 条不变量违反"
            "（建模阶段报错，不带病求解——六条不变量见 wave_port_cpw 模块文档）"
        ]
        for n, msg in sorted(violations, key=lambda v: v[0]):
            lines.append(f"  违反第 {n} 条：{msg}")
        raise WavePortPlanError(
            "\n".join(lines),
            details={
                "violations": [
                    {"invariant": n, "detail": msg} for n, msg in sorted(
                        violations, key=lambda v: v[0])
                ],
            },
        )

    # ── 全绿：组装 plan（sheet = aperture 矩形，pyaedt 直用形态）──────────
    # #310：create_rectangle 的 Width/Height 按法向轴循环映射（法向 y → (Z, X)、
    # 法向 x → (Y, Z)），sizes 直通不重排——与仓内 hfss_c4_arbitration("ZX")/
    # hfss_marchand_anchor("YZ") 已验证形态一致。
    orientation = "ZX" if axis == "y" else "YZ"
    if axis == "y":
        sheet_origin = [a_lo, at, z_lo]
        sheet_sizes = [z_hi - z_lo, a_hi - a_lo]      # [ΔZ, ΔX]
    else:
        sheet_origin = [at, a_lo, z_lo]
        sheet_sizes = [a_hi - a_lo, z_hi - z_lo]      # [ΔY, ΔZ]
    if axis == "y":
        il_start = [left_inner, at, zc]
        il_end = [s_lo, at, zc]
    else:
        il_start = [at, left_inner, zc]
        il_end = [at, s_lo, zc]
    # 实测隙宽 vs 传入 gap 的一致性提示（gap 决定金属上方空气窗，值得对上）
    if left_inner is not None and right_inner is not None:
        act_l, act_r = s_lo - left_inner, right_inner - s_hi
        for side, act in (("左", act_l), ("右", act_r)):
            if abs(act - gap) > max(0.25 * gap, 10.0 * t):
                notes.append(
                    f"{side}侧几何实测隙宽 {act:g} 与传入 gap={gap:g} 偏差 "
                    f"{abs(act - gap):g}（金属上方空气窗按传入 gap 计，请核对）"
                )

    ap_bbox = [0.0, 0.0, z_lo, 0.0, 0.0, z_hi]
    ap_bbox[ai], ap_bbox[ai + 3] = at, at
    ap_bbox[li], ap_bbox[li + 3] = a_lo, a_hi

    invariants = {
        "1": {
            "ok": True,
            "evidence": (
                f"端口面 {axis}={at:g} 位于求解域 {axis} "
                f"[{dlo:g}, {dhi:g}] 的 {'下' if face == 'lo' else '上'}界（{face} 面）"
            ),
        },
        "2": {
            "ok": True,
            "evidence": (
                f"aperture z [{z_lo:g}, {z_hi:g}] = 衬底底 {z_need_lo:g} → 金属顶 "
                f"{mhi:g} + {factor:g}×gap={factor * gap:g} 空气（金属层 "
                f"[{mlo:g}, {mhi:g}] 已含）"
            ),
        },
        "3": {
            "ok": True,
            "evidence": (
                f"aperture 横向 [{a_lo:g}, {a_hi:g}] 两端落在左右地金属 "
                f"[{float(left_outer):g}, {left_inner:g}] / "
                f"[{right_inner:g}, {float(right_outer):g}]（孔径宽 {a_hi - a_lo:g} < "
                f"衬底宽 {w_sub:g}，未取整宽）"
            ),
        },
        "4": {
            "ok": True,
            "evidence": (
                f"积分线 ({left_inner:g}, {at:g}, {zc:g}) → ({s_lo:g}, {at:g}, "
                f"{zc:g})：左地内沿 → 信号左沿，z={zc:g}="
                f"{'金属层中心' if integration_line_z is None else '显式覆盖值'}"
            ),
        },
        "5": {
            "ok": True,
            "evidence": (
                "端口面不叠 Radiation（radiation_on_port_plane=False）；面内 "
                "aperture 以外默认 PEC 作端口壁（落地层不代改辐射边界——调用方"
                "辐射面赋值须排除该面，见 boundary_config.port_face）"
            ),
        },
        "6": {
            "ok": True,
            "evidence": (
                f"衬底 {axis} ∈ [{slo:g}, {shi:g}] 与端口导体均延伸到端口面 "
                f"{axis}={at:g}"
            ),
        },
    }
    return {
        "kind": "wave_port_cpw_plan",
        "port_name": None,
        "units": u,
        "plane": {"axis": axis, "at": at, "domain_face": face,
                  "orientation": orientation},
        "sheet": {"orientation": orientation, "origin": sheet_origin,
                  "sizes": sheet_sizes},
        "aperture": {"lateral": [a_lo, a_hi], "z": [z_lo, z_hi], "bbox": ap_bbox},
        "integration_line": {"start": il_start, "end": il_end, "z": zc,
                             "z_basis": "override" if integration_line_z is not None
                                        else "metal_center",
                             "from": "ground_inner_edge", "to": "signal_edge"},
        "boundary_config": {
            "radiation_on_port_plane": False,
            "port_face": {"axis": axis, "at": at, "domain_face": face},
            "outside_aperture_wall": "pec",
            "pec_cap": False,          # 端口贴边界（不变量 1）→ 无需 PEC 背衬帽
            "modes": 1,
            "impedance": 50.0,
            "renormalize": True,
            "deembed": 0.0,
        },
        "invariants": invariants,
        "notes": notes,
    }


# ─── K6 NetRegistry 桥（nets_report() → plan）────────────────────────────────


def plan_from_nets(
    report: dict[str, Any],
    port_name: str,
    *,
    domain_bbox: Any = None,
    domain_names: Any = None,
    gap: float,
    plane_axis: str,
    plane_at: float,
    metal_z_range: Any = None,
    signal_names: Any = None,
    ground_names: Any = None,
    substrate_names: Any = None,
    **planner_kwargs: Any,
) -> dict[str, Any]:
    """从 K6 NetRegistry 登记薄快照规划 CPW 波端口（plan 输入直接来自 nets_report）。

    与 :class:`rfauto.adapters.hfss_builder_utils.NetRegistry` 互通：``report`` 即
    ``nets_report()`` 产物（objects 带 name/net/kind/bbox，单位标签透传）；按
    ``plane_at`` 过滤"延伸到端口面的对象"自动提取三类 bbox——

    - signal：net=signal 且 kind=metal 且法向区间含端口面（多层金属叠段自动
      并包；signal_names 显式点名可绕过过滤）；
    - ground：net=ground 且 kind=metal 且法向区间含端口面（逐对象透传给规划器
      分侧；ground_names 显式点名）；
    - substrate：kind=dielectric（**排除 domain_names 指定的域盒**；substrate_names
      显式点名）——并包后交给规划器判不变量 6（衬底没铺到端口面会在规划器报第
      6 条，不在这里静默吞掉）；
    - domain：domain_bbox 显式 6 数，或 domain_names（如 ``("AirBox",)``）取登记
      dielectric 并包。

    metal_z_range 缺省取 signal 并包 z 区间（叠层金属天然并出全金属层）；
    其余 kwargs 透传 :func:`plan_wave_port_cpw`（aperture/integration_line 覆盖
    入口同款）。返回 plan（``port_name`` 已标注，供端口报告/落地层命名参考）。

    Examples
    --------
    ::

        reg = NetRegistry(app.modeler, units="um")
        ...  # 建模期 net_add 衬底/信号/地/空气盒（衬底与 AirBox 记 kind="dielectric"）
        plan = plan_from_nets(
            reg.nets_report(), "P1",
            domain_names=("AirBox",), gap=30.0,
            plane_axis="y", plane_at=-660.0)
        from rfauto.adapters.hfss_builder_utils import wave_port_cpw
        wave_port_cpw(app.modeler, plan, name="P1", hfss=app)
    """
    if not isinstance(report, dict) or not isinstance(report.get("objects"), list):
        raise WavePortPlanError(
            "plan_from_nets: report 需为 NetRegistry.nets_report() 的快照 dict"
            f"（含 objects 列表），实际类型 {type(report).__name__}",
            details={"type": type(report).__name__},
        )
    objs = report["objects"]
    boxes: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {}
    for o in objs:
        name = str(o.get("name"))
        try:
            boxes[name] = _bbox6(o.get("bbox"), f"report.objects[{name}].bbox")
        except WavePortPlanError as exc:
            raise WavePortPlanError(
                f"plan_from_nets: 登记薄对象几何非法——{exc}",
                details={"object": name},
            ) from exc

    axis = str(plane_axis).strip().lower()
    if axis not in PLANE_AXES:
        raise WavePortPlanError(
            f"plan_from_nets: plane_axis 需 {'|'.join(PLANE_AXES)}，实际 {plane_axis!r}",
            details={"plane_axis": str(plane_axis)},
        )
    ai = 0 if axis == "x" else 1
    try:
        at = float(plane_at)
    except (TypeError, ValueError) as exc:
        raise WavePortPlanError(f"plan_from_nets: plane_at 非数值 {plane_at!r}") from exc
    scale = max([1.0] + [abs(v) for b in boxes.values() for v in (*b[0], *b[1])] + [abs(at)])
    t = float(planner_kwargs.get("tol") or 1e-6 * scale)

    def _pick(
        names: Any, kind: str, touch_plane: bool, *, net: str | None = None, label: str
    ) -> list[str]:
        """按 kind（可选 net）+可选端口面触达过滤对象名；names 显式点名优先。"""
        if names is not None:
            picked = [str(n) for n in names]
            missing = [n for n in picked if n not in boxes]
            if missing:
                raise WavePortPlanError(
                    f"plan_from_nets: {label} 名单引用未登记对象 {missing}"
                    f"（登记薄现有 {sorted(boxes)}）",
                    details={"missing": missing},
                )
            return picked
        return [
            str(o.get("name")) for o in objs
            if (net is None or str(o.get("net")) == net)
            and str(o.get("kind")) == kind
            and (not touch_plane or _span_contains(boxes[str(o.get("name"))], ai, at, t))
        ]

    sig_names = _pick(signal_names, "metal", touch_plane=True, net="signal",
                      label="signal")
    if not sig_names:
        raise WavePortPlanError(
            f"plan_from_nets: 没有 net=signal/kind=metal 且延伸到端口面 "
            f"{axis}={at:g} 的对象（signal_names 可显式点名；登记薄 {len(objs)} 个对象）",
            details={"plane": {axis: at}},
        )
    signal_bbox = _union([boxes[n] for n in sig_names])

    gnd_names = _pick(ground_names, "metal", touch_plane=True, net="ground",
                      label="ground")
    if not gnd_names:
        raise WavePortPlanError(
            f"plan_from_nets: 没有 net=ground/kind=metal 且延伸到端口面 "
            f"{axis}={at:g} 的对象（ground_names 可显式点名）",
            details={"plane": {axis: at}},
        )
    ground_bboxes = [[*boxes[n][0], *boxes[n][1]] for n in gnd_names]

    # 域盒：显式 bbox 或点名 dielectric 并包（统一 (lo, hi) 对形态）
    dom_names_used: list[str] = []
    if domain_bbox is not None:
        dom_pair = _bbox6(domain_bbox, "plan_from_nets domain_bbox")
    elif domain_names is not None:
        dom_names_used = [str(n) for n in domain_names]
        missing = [n for n in dom_names_used if n not in boxes]
        if missing:
            raise WavePortPlanError(
                f"plan_from_nets: domain_names 引用未登记对象 {missing}",
                details={"missing": missing},
            )
        dom_pair = _bbox6(
            _union([boxes[n] for n in dom_names_used]), "domain_names 并包")
    else:
        raise WavePortPlanError(
            "plan_from_nets: 求解域需二选一给出——domain_bbox=6 数或 "
            "domain_names（如 ('AirBox',)，登记为 kind=dielectric）",
        )

    # 衬底：dielectric 并包（net 不限），排除域盒对象与"容器壳"——AirBox 不是
    # 衬底，不排除会把空气圈进"衬底"（aperture z 下界跑到域底、不变量 6 被空
    # 放水）。容器壳判定：候选中完全包住其余候选者=空气盒/域壳，剔除。
    sub_names = _pick(substrate_names, "dielectric", touch_plane=False,
                      label="substrate")
    sub_names = [n for n in sub_names if n not in set(dom_names_used)]
    if len(sub_names) > 1:
        def _contains_all(outer: str) -> bool:
            ob = boxes[outer]
            return all(
                ob[0][k] <= boxes[n][0][k] + t and ob[1][k] >= boxes[n][1][k] - t
                for n in sub_names if n != outer for k in range(3))
        containers = [n for n in sub_names if _contains_all(n)]
        sub_names = [n for n in sub_names if n not in set(containers)]
    if not sub_names:
        raise WavePortPlanError(
            "plan_from_nets: 找不到衬底对象（kind=dielectric 且不在 domain_names"
            " 内）——substrate_names 显式点名（衬底没铺到端口面会被规划器第 6 条"
            "拦下，这里不静默放行）",
        )
    substrate_bbox = _union([boxes[n] for n in sub_names])

    metal = metal_z_range
    if metal is None:
        metal = (signal_bbox[2], signal_bbox[5])   # 多层金属叠段并包 z

    plan = plan_wave_port_cpw(
        [*dom_pair[0], *dom_pair[1]],
        substrate_bbox,        # _union 产 flat 6 数
        signal_bbox,           # 同上
        ground_bboxes,
        gap,
        plane_axis=plane_axis,
        plane_at=plane_at,
        metal_z_range=metal,
        units=str(report.get("units") or "mm"),
        **planner_kwargs,
    )
    plan["port_name"] = str(port_name)
    plan["extraction"] = {
        "signal": sig_names,
        "ground": gnd_names,
        "substrate": sub_names,
        "domain": dom_names_used or "explicit_bbox",
    }
    return plan
