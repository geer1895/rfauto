"""闭式物理过滤漏斗（R6）——候选/数据行入库消费侧的独立物理合理性门。

R6 规格（池十五 R6 / 月计划 carry-over §二.2）：候选先过**独立闭式物理
检查**（与代理训练数据无共享）再进求解器；每级通过率计量——「过滤器
是否真在杀坏点」可量化。本席口径为数据集入库面物理合理性过滤：以
``service.dataset_service.query_dataset`` 的输出信封为输入做消费侧过滤
（本模块不改 dataset_service，只消费其 ``{ok, rows, columns, bounds}``
信封形态，落点=查询结果的入库/采信前一道漏斗）。

闭式判据（公式即出处；#300：裁判面自身先过已知基准）：
- 无源性：|S_ij| ≤ 1+tol；两端口且 S11/S21 同时在列时附能量守恒式
  |S11|²+|S21|² ≤ 1+tol（无耗极限等号成立；有耗器件只使左端更小，
  故该界对一般无源器件仍成立——能量的闭式上界）。
- ε_eff 物理界：1 < ε_eff < ε_r_max（波速介于空气与介质之间；
  ε_eff=1 下界取严格大于，空气线 ε_eff→1⁻ 为合法极限的浮点近邻）。
- cost 可采性：有限且 ≥ 0（代价语义；NaN/Inf/负值不可入库采信）。
- 参数盒：声明 bounds 内（越盒=外推区，不采信）。

#316 方向口径：形状不符/缺值/NaN 一律记 ``n_unverifiable`` 单列——
漏斗对不可验证行**不放过也不谎报 FAIL**，计数透出由调用方裁决。
漏斗判 FAIL 仅对"值在但违反闭式界"的行成立。
"""

from __future__ import annotations

from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "DEFAULT_STAGES",
    "filter_query_dataset_result",
    "run_physics_funnel",
]

#: 缺省漏斗级（顺序=执行序；每级独立计通过率）
DEFAULT_STAGES: tuple[str, ...] = (
    "finite_values",
    "param_box",
    "passivity",
    "eps_eff_bounds",
    "cost_nonnegative",
)

_TOL_S = 0.02  # |S|≤1 的测量/数值余量（2%，覆盖浮点与导出舍入）
_TOL_ENERGY = 0.02  # 能量守恒式余量（同上口径）


def _num(row: dict[str, Any], key: str) -> float | None:
    """取数值列值：缺列/None/NaN 返回 None（不可验证语义，非 FAIL）。

    非 _helpers 族（F-13 批 2 处置注记）：本函数是行取值器 (row, key)，
    与 parse_num 的入参收敛契约完全不同源——本地保留。
    """
    if key not in row:
        return None
    val = row[key]
    if val is None:
        return None
    try:
        out = float(val)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _check_finite_values(row: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """行内任意数值列含 ±Inf 即 FAIL（显式坏数据；NaN 由各列 None 语义单列）。"""
    for val in row.values():
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            f = float(val)
            if f == float("inf") or f == float("-inf"):
                return False
    return True


def _check_param_box(row: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """参数落声明盒内；盒缺失或参数缺值=不可验证（放行本级，计数另列）。"""
    bounds = ctx["bounds"]
    for name, box in bounds.items():
        val = _num(row, name)
        if val is None:
            continue
        lo, hi = box
        if lo is not None and val < float(lo):
            return False
        if hi is not None and val > float(hi):
            return False
    return True


def _check_passivity(row: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """|S_ij| ≤ 1+tol；S11/S21 同列时加能量守恒上界（闭式，见模块 docstring）。"""
    s11 = _num(row, ctx.get("s11_col", "s11"))
    if s11 is not None and abs(s11) > 1.0 + _TOL_S:
        return False
    s21 = _num(row, ctx.get("s21_col", "s21"))
    if s21 is not None and abs(s21) > 1.0 + _TOL_S:
        return False
    energy_violated = (s11 is not None and s21 is not None
                       and s11 * s11 + s21 * s21 > 1.0 + _TOL_ENERGY)
    return not energy_violated


def _check_eps_eff(row: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """1 < ε_eff < ε_r_max（物理界；缺列=不可验证放行，计数另列）。"""
    col = ctx.get("eps_eff_col", "eps_eff")
    val = _num(row, col)
    if val is None:
        return True
    eps_max_raw = ctx.get("eps_r_max")
    # #364-④：数值面禁 `or` 缺省惯语——显式判 None，0/负界照实参与判据
    eps_max = float(eps_max_raw) if eps_max_raw is not None else 1e9
    return 1.0 < val < eps_max


def _check_cost(row: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """cost 有限且 ≥ 0；缺列=不可验证放行（finite_values 级已拦 Inf/NaN 坏列）。"""
    col = ctx.get("cost_col", "cost")
    val = _num(row, col)
    if val is None:
        return True
    return val >= 0.0


_STAGE_FNS = {
    "finite_values": _check_finite_values,
    "param_box": _check_param_box,
    "passivity": _check_passivity,
    "eps_eff_bounds": _check_eps_eff,
    "cost_nonnegative": _check_cost,
}


def run_physics_funnel(
    rows: list[dict[str, Any]],
    *,
    stages: tuple[str, ...] | list[str] | None = None,
    bounds: dict[str, Any] | None = None,
    eps_r_max: float | None = None,
    cost_col: str = "cost",
    eps_eff_col: str = "eps_eff",
    s11_col: str = "s11",
    s21_col: str = "s21",
) -> dict[str, Any]:
    """对候选行跑闭式物理漏斗；返回逐级通过率与存活行索引（R6 计量面）。

    Args:
        rows: dict 行列表（query_dataset 的 ``rows`` 形态）。
        stages: 漏斗级名序列（缺省 :data:`DEFAULT_STAGES`）。
        bounds: 参数盒 ``{name: [lo, hi]}``（来自数据集 manifest；None=该级
            只拦有限值坏列外的不可验证情况，不拦越盒）。
        eps_r_max: ε_eff 上界（介电常数上限；None=不设上界）。
        cost_col/eps_eff_col/s11_col/s21_col: 列名（缺省同 query_dataset
            惯例小写名；数据集列名不同时显式传）。

    Returns:
        dict：``{ok, n_in, stages: [{name, n_pass, n_fail, n_unverifiable,
        pass_rate, fail_idx}], survivors_idx, survivors}``。
        未知级名 ok=False。
    """
    stage_names = tuple(stages) if stages is not None else DEFAULT_STAGES
    unknown = [s for s in stage_names if s not in _STAGE_FNS]
    if unknown:
        return error_envelope([f"未知漏斗级: {unknown}（可选: {sorted(_STAGE_FNS)}）"])
    ctx: dict[str, Any] = {
        "bounds": bounds or {},
        "eps_r_max": eps_r_max,
        "cost_col": cost_col,
        "eps_eff_col": eps_eff_col,
        "s11_col": s11_col,
        "s21_col": s21_col,
    }
    stage_reports: list[dict[str, Any]] = []
    alive = list(range(len(rows)))
    for stage in stage_names:
        fn = _STAGE_FNS[stage]
        n_pass = 0
        n_fail = 0
        n_unverifiable = 0
        fail_idx: list[int] = []
        next_alive: list[int] = []
        for idx in alive:
            verdict = _row_verifiable(rows[idx], stage, ctx)
            if verdict is None:
                n_unverifiable += 1
                next_alive.append(idx)  # 不可验证不杀（#316 方向：不放过也不谎报）
                continue
            if fn(rows[idx], ctx):
                n_pass += 1
                next_alive.append(idx)
            else:
                n_fail += 1
                fail_idx.append(idx)
        n_in_stage = n_pass + n_fail + n_unverifiable
        stage_reports.append({
            "name": stage,
            "n_in": n_in_stage,
            "n_pass": n_pass,
            "n_fail": n_fail,
            "n_unverifiable": n_unverifiable,
            "pass_rate": round(n_pass / (n_pass + n_fail), 6)
            if (n_pass + n_fail) else None,
            "fail_idx": fail_idx,
        })
        alive = next_alive
    return ok_envelope(n_in=len(rows), stages=stage_reports, survivors_idx=alive, survivors=[rows[i] for i in alive])


def _row_verifiable(
    row: dict[str, Any], stage: str, ctx: dict[str, Any],
) -> bool | None:
    """该行在本级是否可验证：值在=True；缺值/NaN=None（不可验证）。

    仅对"值在"的行才可能 FAIL——缺值行进不了本级裁决（n_unverifiable）。
    finite_values 级恒可验证（它本身就是坏值侦测级）。
    """
    if stage == "finite_values":
        return True
    if stage == "param_box":
        return None if not ctx["bounds"] else True
    if stage == "passivity":
        return None if (_num(row, ctx["s11_col"]) is None
                        and _num(row, ctx["s21_col"]) is None) else True
    if stage == "eps_eff_bounds":
        return None if _num(row, ctx["eps_eff_col"]) is None else True
    if stage == "cost_nonnegative":
        return None if _num(row, ctx["cost_col"]) is None else True
    return True


def filter_query_dataset_result(
    result: dict[str, Any],
    *,
    stages: tuple[str, ...] | list[str] | None = None,
    eps_r_max: float | None = None,
    cost_col: str = "cost",
    eps_eff_col: str = "eps_eff",
    s11_col: str = "s11",
    s21_col: str = "s21",
) -> dict[str, Any]:
    """消费侧接线：过滤 ``query_dataset`` 输出信封，附漏斗计量报告。

    输入信封需含 ``rows``（list[dict]）；``bounds``/``columns`` 在则透传
    进漏斗。输入 ok=False 时原样透传（不二次包装）。输出在输入信封之上
    追加 ``funnel``（:func:`run_physics_funnel` 结果）与 ``rows``（存活行）。
    """
    if not result.get("ok", False):
        return result
    rows = result.get("rows") or []
    if not isinstance(rows, list):
        return error_envelope([f"rows 必须是 list，收到 {type(rows).__name__}"])
    funnel = run_physics_funnel(
        rows, stages=stages, bounds=result.get("bounds"),
        eps_r_max=eps_r_max, cost_col=cost_col, eps_eff_col=eps_eff_col,
        s11_col=s11_col, s21_col=s21_col)
    if not funnel.get("ok", False):
        return error_envelope(list(funnel.get("errors", [])))
    return ok_envelope(
        rows=funnel.pop("survivors"),
        funnel=funnel,
        dataset=result.get("dataset"),
        n_rows_in=funnel["n_in"],
        n_rows_out=len(funnel["survivors_idx"]),
    )
