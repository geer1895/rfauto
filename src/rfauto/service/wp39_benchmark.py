"""WP3.9 MVP 基准内核（，用户最低功能的定量验收）。

三代表问题（mline 阻抗匹配 / patch 谐振调频 / ratrace 隔离度）× 2 引擎
（rfauto 代理环 = ``run_surrogate_loop``（``rfauto tune --sampler sbo`` 同
内核）vs HFSS Optimetrics 口径基线）× 真跑预算 25（固定不得超）。

判据（本模块为唯一裁判实现）：
- 预算：两引擎真跑评估尝试次数（成功+失败）均 ≤ 预算（默认 25）；
- wall-clock：rfauto 环优化墙钟 ≤ HFSS 基线的 1/2
 （优化墙钟 = 首次评估开始 → 末次评估结束，含环内算法开销，
 不含 desktop 启动与一次性建模——两引擎同口径）；
- cost 劣化：rfauto 最优指标相对基线劣化 ≤ 5%
 （指标为 dB 语义、越负越好：劣化 = (x−ref)/|ref|×100）。

基线两档：Pattern Search（Hooke-Jeeves 探索移动+模式移动，HFSS
Optimetrics Pattern Search 口径的等价 scripted loop，经 PyAEDT 驱动
变量更新+求解）= 达标线；optiSLang MOP = 超额线（本 MVP 未接）。

铁律：本模块全部为确定性纯函数或注入式 evaluator 环——零真机即可
单测（预算/判据/搜索环逻辑），真机只发生在 scripts/wp39_benchmark_run.py
的 HFSS evaluator 里。数值只在确定性内核（数值铁律）。
"""

from __future__ import annotations

import itertools
import math
import time
from collections.abc import Callable
from typing import Any

from rfauto.core.anchor_verdict import SUB_ANCHOR_TOL_PCT
from rfauto.core.objectives import Objective, SpecEvaluator

# ── 判据常量（改动=显式重标定决策，须附证据）────────
BUDGET_DEFAULT = 25         # 真跑预算（固定不得超）
WALLCLOCK_MAX_RATIO = 0.5      # wall-clock ≤ 基线的 1/2
COST_MAX_DEGRADATION_PCT = 5.0   # cost 劣化 ≤ 5%（vs 基线）

# Hooke-Jeeves 默认步长（占搜索域比例；Optimetrics Pattern Search 惯例
# 的有限差分/步长收缩量级：初始 1/4 域宽，无改善减半，低于 2% 域宽停）
PATTERN_INITIAL_STEP_FRAC = 0.25
PATTERN_MIN_STEP_FRAC = 0.02


# ── 判据原语（纯函数，零真机）────────────────────────────────────────────


def budget_used_ok(n_evals: int, budget: int = BUDGET_DEFAULT) -> bool:
  """真跑尝试次数（成功+失败）未超预算。负数视为非法输入判 False。"""
  return 0 <= int(n_evals) <= int(budget)


def cost_degradation_pct(
  metric_test: float, metric_ref: float
) -> float | None:
  """cost 劣化百分比：正 = 试验臂比参考臂差，负 = 更优。

  指标为 dB 语义（越负越好）时劣化即 (test−ref)/|ref|×100。
  参考值恒 0 时比值退化（无穷放大）——返回 None 由调用方如实
  记"不可判定"，绝不静默当作通过。
  """
  if metric_ref == 0.0:
    return None if metric_test != 0.0 else 0.0
  return (float(metric_test) - float(metric_ref)) / abs(float(metric_ref)) * 100.0


def wallclock_ratio(wall_test_s: float, wall_ref_s: float) -> float | None:
  """试验臂/参考臂优化墙钟比；参考臂墙钟非正 → None（不可判定）。"""
  if wall_ref_s <= 0.0:
    return None
  return float(wall_test_s) / float(wall_ref_s)


def _best_metric_of(campaign: dict[str, Any]) -> float | None:
  """从战役 JSON 提取最优指标（越负越好语义）；缺失/非数返回 None。"""
  best = campaign.get("best")
  if not isinstance(best, dict):
    return None
  val = best.get("metric")
  if not isinstance(val, (int, float)) or isinstance(val, bool):
    return None
  if not math.isfinite(float(val)):
    return None
  return float(val)


def judge_problem_pair(
  baseline: dict[str, Any],
  candidate: dict[str, Any],
  *,
  budget: int = BUDGET_DEFAULT,
  max_wall_ratio: float = WALLCLOCK_MAX_RATIO,
  max_degradation_pct: float = COST_MAX_DEGRADATION_PCT,
) -> dict[str, Any]:
  """单问题头对头判定（判据，纯函数）。

  baseline = HFSS Optimetrics 口径基线战役 JSON；
  candidate = rfauto 环战役 JSON。verdict=PASS 当且仅当：
  预算双达标 ∧ wall-clock ≤ max_wall_ratio ∧ cost 劣化 ≤ max_pct。
  任一侧战役整体失败（best 缺失）→ FAIL（单问题失败不连坐，
  汇总层只计本问题）。指标只需"越小越好"（dB 或无量纲 |εeff−target|
  皆可，劣化式对任何此类指标数学成立）；返回键 abs_delta_db 为
  候选−基线的原单位差（键名沿用历史契约，非 dB 指标亦复用该键）。
  """
  wall_c = candidate.get("wall_s") or {}
  wall_b = baseline.get("wall_s") or {}
  ratio = wallclock_ratio(
    float(wall_c.get("optimization_s") or 0.0),
    float(wall_b.get("optimization_s") or 0.0))
  metric_c = _best_metric_of(candidate)
  metric_b = _best_metric_of(baseline)
  deg = (cost_degradation_pct(metric_c, metric_b)
      if metric_c is not None and metric_b is not None else None)
  abs_delta_db = (metric_c - metric_b
          if metric_c is not None and metric_b is not None else None)

  budget_ok = (budget_used_ok(int(candidate.get("n_evals") or 0), budget)
         and budget_used_ok(int(baseline.get("n_evals") or 0), budget))
  wall_ok = ratio is not None and ratio <= max_wall_ratio
  cost_ok = deg is not None and deg <= max_degradation_pct

  reasons: list[str] = []
  if not budget_ok:
    reasons.append(
      f"预算超标：candidate n_evals={candidate.get('n_evals')} / "
      f"baseline n_evals={baseline.get('n_evals')}（预算 {budget}）")
  if metric_c is None or metric_b is None:
    reasons.append("最优指标缺失（某侧战役整体失败或全评估失败）")
  else:
    if not wall_ok:
      ratio_txt = "不可判定（基线墙钟非正）" if ratio is None \
        else f"{ratio:.3f}"
      reasons.append(
        f"wall-clock 超门：ratio={ratio_txt} > {max_wall_ratio}"
        f"（candidate {wall_c.get('optimization_s')}s vs baseline "
        f"{wall_b.get('optimization_s')}s）")
    if deg is None:
      reasons.append("cost 劣化不可判定（参考值恒 0）")
    elif not cost_ok:
      reasons.append(
        f"cost 劣化超门：{deg:+.2f}% > {max_degradation_pct}%"
        f"（Δ={abs_delta_db:+.4g}，指标原单位）")
  return {
    "problem": candidate.get("problem") or baseline.get("problem"),
    "budget_ok": budget_ok,
    "wallclock_ok": wall_ok,
    "cost_ok": cost_ok,
    "wallclock_ratio": None if ratio is None else round(ratio, 4),
    "degradation_pct": None if deg is None else round(deg, 4),
    "abs_delta_db": None if abs_delta_db is None else round(abs_delta_db, 4),
    "metric_candidate": metric_c,
    "metric_baseline": metric_b,
    "n_evals_candidate": candidate.get("n_evals"),
    "n_evals_baseline": baseline.get("n_evals"),
    "verdict": "PASS" if (budget_ok and wall_ok and cost_ok) else "FAIL",
    "reasons": reasons,
  }


def summarize_judgment(
  problem_verdicts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
  """汇总判定：overall PASS 当且仅当全部问题 PASS（单问题失败不连坐，
  但最低功能验收口径 = 三问题全过；分项如实进表）。"""
  items = {k: v.get("verdict") for k, v in sorted(problem_verdicts.items())}
  n_pass = sum(1 for v in items.values() if v == "PASS")
  return {
    "n_problems": len(items),
    "n_pass": n_pass,
    "per_problem": items,
    "overall": "PASS" if n_pass == len(items) and items else "FAIL",
  }


# ── Pattern Search 基线环（HFSS Optimetrics Pattern Search 口径）──────────


def _clip(v: float, lo: float, hi: float) -> float:
  return min(max(v, lo), hi)


def pattern_search_loop(
  bounds: dict[str, tuple[float, float]],
  evaluate_fn: Callable[[dict[str, float]], dict[str, float]],
  objectives: list[Objective],
  *,
  x0: dict[str, float],
  budget: int = BUDGET_DEFAULT,
  initial_step_frac: float = PATTERN_INITIAL_STEP_FRAC,
  min_step_frac: float = PATTERN_MIN_STEP_FRAC,
) -> dict[str, Any]:
  """Hooke-Jeeves Pattern Search（HFSS Optimetrics Pattern Search 的
  等价 scripted 环——探索移动 + 模式移动 + 步长减半）。

  每次调用 evaluate_fn 计一次真跑尝试（成功+失败同计预算），硬上限
  budget；评估失败记 failure 并按 +inf cost 处理（消耗预算但不炸环）。
  返回 JSON 契约与 run_surrogate_loop 对齐（best/real_cost_trace/
  best_so_far_trace/n_evals/wall_s），保证 judge 与收敛曲线同构。
  """
  names = sorted(bounds)
  t0 = time.time()
  samples: list[dict[str, Any]] = []
  failures: list[dict[str, Any]] = []
  n_evals = 0

  def cost_of(metrics: dict[str, float]) -> float:
    return SpecEvaluator.evaluate_objectives(metrics, objectives)

  def evaluate(params: dict[str, float]) -> float | None:
    nonlocal n_evals
    n_evals += 1
    try:
      metrics = evaluate_fn(dict(params))
    except Exception as exc: # 单点失败入环不炸环（surrogate_loop 同口径）
      failures.append({"params": dict(params), "error": str(exc)})
      return None
    cost = cost_of(metrics)
    samples.append({"params": dict(params), "metrics": metrics,
            "cost": cost})
    return cost

  def start_point() -> dict[str, float]:
    return {n: _clip(float(x0.get(n, bounds[n][0])), *bounds[n])
        for n in names}

  def center_point() -> dict[str, float]:
    return {n: (bounds[n][0] + bounds[n][1]) / 2.0 for n in names}

  best: dict[str, Any] | None = None
  cur: dict[str, float] | None = None
  cur_metrics: dict[str, float] = {}
  fcur = math.inf

  def record_best(params: dict[str, float],
          metrics: dict[str, float], cost: float) -> None:
    nonlocal best
    if best is None or cost < best["cost"]:
      best = {"params": dict(params), "metrics": dict(metrics),
          "cost": cost}

  # 起点失败（如网格病态）退回域中心重试一次——两次都失败则战役失败
  for cand in (start_point(), center_point()):
    f = evaluate(cand)
    if f is not None:
      cur, cur_metrics, fcur = cand, samples[-1]["metrics"], f
      break
  if cur is not None:
    record_best(cur, cur_metrics, fcur)

  steps = {n: initial_step_frac * (bounds[n][1] - bounds[n][0])
       for n in names}
  min_steps = {n: min_step_frac * (bounds[n][1] - bounds[n][0])
         for n in names}

  while n_evals < budget and cur is not None:
    base, fbase = dict(cur), fcur
    base_metrics = cur_metrics
    improved = False
    # ── 探索移动：逐坐标 ±step，取首个改进方向（沿用至后续坐标）──────
    for n in names:
      for sign in (1.0, -1.0):
        if n_evals >= budget:
          break
        trial = dict(base)
        trial[n] = _clip(base[n] + sign * steps[n], *bounds[n])
        if trial[n] == base[n]:
          continue # 已贴界，该方向无新点（不烧预算）
        f = evaluate(trial)
        if f is not None and f < fbase:
          base, fbase = trial, f
          base_metrics = samples[-1]["metrics"]
          improved = True
          break
      if n_evals >= budget:
        break
    # ── 模式移动：自旧基点沿新方向外推一步（Hooke-Jeeves 加速）────────
    if improved and n_evals < budget:
      patt = {n: _clip(2.0 * base[n] - cur[n], *bounds[n])
          for n in names}
      f = evaluate(patt)
      if f is not None and f < fbase:
        base, fbase = patt, f
        base_metrics = samples[-1]["metrics"]
    cur, cur_metrics, fcur = base, base_metrics, fbase
    record_best(cur, cur_metrics, fcur)
    if not improved:
      steps = {n: steps[n] / 2.0 for n in names}
      if all(steps[n] < min_steps[n] for n in names):
        break

  trace = [s["cost"] for s in samples]
  return {
    "ok": best is not None,
    "algorithm": "pattern_search",
    "best": best,
    "n_evals": n_evals,
    "n_failures": len(failures),
    "stop_reason": ("budget" if n_evals >= budget
            else ("min_step" if cur is not None else "all_failed")),
    "real_cost_trace": trace,
    "best_so_far_trace": best_so_far_trace(trace),
    "failures": failures,
    "wall_s": {"optimization_s": round(time.time() - t0, 2)},
    "params": {
      "initial_step_frac": initial_step_frac,
      "min_step_frac": min_step_frac,
    },
  }


def best_so_far_trace(costs: list[float]) -> list[float]:
  """逐次真跑的 best-so-far 轨迹（与 surrogate_loop 同口径的确定性工具）。"""
  out: list[float] = []
  cur = math.inf
  for c in costs:
    cur = min(cur, float(c))
    out.append(cur)
  return out


def sbo_objectives(metric_name: str) -> list[Objective]:
  """基准目标的统一 cost 语义（两引擎同评估器，"回代同一评估器"）。

  max_below 阈值取 -1e6（远深于一切物理 dB 值）→ cost = 指标 + 1e6：
  无平台、保序、两引擎与判据层共用同一 SpecEvaluator 闭式。
  """
  return [Objective(metric=metric_name, band=[], op="max_below",
           value=-1e6, weight=1.0)]


# ── 后续项内核──────────────
#
# ③ ratrace 深零点判据：单频 |S31|@f0（−40~−52dB）对网格自适应敏感，
#  sbo 劣化 +11%（MVP 存档）——给两个鲁棒替代判据：
#  带宽积分（band_power_avg_db）与深零点邻域（deep_null_neighborhood_db）；
# ④ patch 谷位标定：谐振常数 f_dip·L 按引擎漂移（HFSS 99.8 vs openEMS
#  76.8 GHz·mm）——问题定义前先单点扫频定位谷位再定 f0/尺寸；
# ①档 openEMS 数据工厂：工厂环最优参数回代 HFSS 评估器判 cost 的合并契约。

# ── MVP 基准换代内核────────────
#
# 归因（子项 A，归因报告存档）：
# mline openEMS 工厂地貌被 MSLPort 端口级 |S11| 伪底主导（加密网格不消、
# β→εeff 地貌物理且随 w 单调）——工厂与基线换"引擎一致指标"：
# openEMS 侧 β→εeff（CalcPort 金标准口径），HFSS 侧 S21 相位斜率→εeff；
# 目标 |εeff−target| 按 ④ 纪律由本引擎名义点标定（两引擎同一物理量、
# 各自标定），judge_problem_pair 仍为唯一裁判（cost_degradation_pct 对
# 任何越小越好指标数学成立；非 dB 语义由 metric_semantics 如实标注）。

#: 真空光速（m/s，CODATA 定义值；εeff 抽取两内核共用）
C_LIGHT = 299792458.0

#: εeff 抽取频窗（±4%，与 scripts/engine_benchmark_mline._beta_eps 同口径）
EPS_EFF_WINDOW_FRAC = 0.04


def eps_eff_from_beta(
  freqs_hz: Any,
  betas: Any,
  f_target_hz: float,
  *,
  window_frac: float = EPS_EFF_WINDOW_FRAC,
) -> tuple[float, float]:
  """CalcPort β→εeff（金标准口径）：±window_frac 频窗中值 β 与中值频率。

  与 scripts/engine_benchmark_mline.py::_beta_eps（:49-58）同窗同中值
  以保两源一致：εeff = (β·c / (2π·f_med))²。频窗无样本 → ValueError
  （如实报错，不外推不猜）。返回 (eps_eff, f_med_hz)。
  """
  import numpy as np

  f = np.asarray(freqs_hz, dtype=float)
  b = np.asarray(betas, dtype=float)
  if f.shape != b.shape or f.size == 0:
    raise ValueError("freqs_hz/betas 形状不一致或为空")
  f_t = float(f_target_hz)
  if f_t <= 0.0:
    raise ValueError("f_target_hz 必须为正")
  if not (0.0 < float(window_frac) < 1.0):
    raise ValueError("window_frac 必须在 (0,1) 内")
  sel = (f >= (1.0 - window_frac) * f_t) & (f <= (1.0 + window_frac) * f_t)
  if not sel.any():
    raise ValueError(
      f"频窗 [{(1 - window_frac) * f_t:.6g}, "
      f"{(1 + window_frac) * f_t:.6g}] Hz 内无 β 样本"
      f"（数据范围 {f.min():.6g}–{f.max():.6g}）")
  beta = float(np.median(b[sel]))
  f_med = float(np.median(f[sel]))
  return (beta * C_LIGHT / (2.0 * math.pi * f_med)) ** 2, f_med


def eps_eff_from_s21_phase(
  freqs_hz: Any, s21: Any, line_len_m: float,
) -> tuple[float, dict[str, Any]]:
  """HFSS S21 相位解卷积斜率→εeff（与 β→εeff 同一物理量，HFSS 侧抽取）。

  传输相位 φ(f) = −β(f)·L + φ0，β = 2πf√εeff/c ⇒ |dφ/df| = 2π√εeff·L/c
  ⇒ εeff = (slope·c / (2π·L))²（平方后符号无关）。相位 unwrap 后做
  含截距线性最小二乘——截距吸收端口参考面相位。line_len_m ≤ 0 或
  样本 <2 → ValueError。返回 (eps_eff, meta)。
  """
  import numpy as np

  f = np.asarray(freqs_hz, dtype=float)
  s = np.asarray(s21)
  if s.shape != f.shape or f.size < 2:
    raise ValueError("S21 相位斜率至少需要 2 个同形频率样本")
  if float(line_len_m) <= 0.0:
    raise ValueError("line_len_m 必须为正")
  phase = np.unwrap(np.angle(s))
  slope, intercept = (float(v) for v in np.polyfit(f, phase, 1))
  eps_eff = (slope * C_LIGHT / (2.0 * math.pi * float(line_len_m))) ** 2
  return float(eps_eff), {
    "slope_rad_per_hz": slope, "intercept_rad": intercept,
    "n_points": int(f.size), "line_len_m": float(line_len_m),
  }


def eps_eff_error_metric(eps_eff: float, eps_target: float) -> float:
  """工厂/基线统一目标函数（#190 预声明）：|εeff−target|（无量纲）。

  非 dB、越小越好；cost_degradation_pct 对该指标数学成立（唯一裁判
  judge_problem_pair 消费），非 dB 语义由战役 JSON 的 metric_semantics
  如实标注。④ 纪律：target 由本引擎名义点标定（openEMS=eps_eff_from_beta、
  HFSS=eps_eff_from_s21_phase，两引擎同一物理量、各自标定）。
  """
  if not (math.isfinite(float(eps_eff)) and math.isfinite(float(eps_target))):
    raise ValueError(f"εeff 输入非有限值: {eps_eff!r}, {eps_target!r}")
  return abs(float(eps_eff) - float(eps_target))


def mline_landscape_health_gate(
  w_list: list[float],
  eps_list: list[float],
  *,
  nominal_w: float,
  eps_hj: float,
  eps_tol_pct: float = SUB_ANCHOR_TOL_PCT,
  direction: str = "increasing",
  port_match: dict[str, Any] | None = None,
) -> dict[str, Any]:
  """mline εeff 地貌健康门（wp39-factory-verdict-next 子项 B）。

  替代 scripts/wp39_followup_run.py:186-188 的 |S11| 内联门
  （nominal_is_argmin+sane<−15dB——端口伪底地貌下该门无网格可过，
  归因见子项 A 记录）。两门：
  ① 副锚（名义点一致）：|εeff(nominal)/eps_hj−1|·100 ≤ eps_tol_pct——
    同 core/anchor_verdict.SUB_ANCHOR_TOL_PCT 口径（默认 3.0，单一
    事实源导入）；
  ② 单调：εeff 随 w 全序列单调（direction="increasing" 对应 HJ 准静态
    口径 εeff 随 w 增；平点允许、反序即判废）。
  名义点缺失（w_list 无 nominal_w）→ ValueError。纯函数零真机。

  可选融合（向后兼容：不传 port_match 输出零变化）：``port_match``
  传 `mline_port_match_health` 的输出 dict 时，第三门=引擎 ZL 基匹配
  （line_basis_ok）——三门全过才 PASS，port_match 原样折入输出
  ``port_match`` 键（旧 50Ω 基 |S11| 为其中诊断量 s11_meas_50_db）。
  """
  if len(w_list) != len(eps_list) or not w_list:
    raise ValueError("w_list/eps_list 形状不一致或为空")
  if eps_hj <= 0.0:
    raise ValueError("eps_hj 锚值必须为正")
  nominal_idx = next(
    (i for i, w in enumerate(w_list) if abs(float(w) - float(nominal_w)) < 1e-9),
    None)
  if nominal_idx is None:
    raise ValueError(f"名义点 w={nominal_w} 不在采样列表 {w_list!r} 内")
  eps = [float(e) for e in eps_list]
  delta_pct = (eps[nominal_idx] / float(eps_hj) - 1.0) * 100.0
  anchor_ok = bool(abs(delta_pct) <= float(eps_tol_pct))
  diffs = [b - a for a, b in itertools.pairwise(eps)]
  if direction == "increasing":
    monotonic_ok = all(d >= 0.0 for d in diffs)
  elif direction == "decreasing":
    monotonic_ok = all(d <= 0.0 for d in diffs)
  else:
    raise ValueError(f"direction 非法: {direction!r}")
  reasons: list[str] = []
  if not anchor_ok:
    reasons.append(
      f"副锚超门：名义点 εeff={eps[nominal_idx]:.4f} 对 HJ "
      f"{delta_pct:+.2f}% 超 ±{eps_tol_pct}%")
  if not monotonic_ok:
    reasons.append(
      f"εeff 地貌非单调（{direction}）：{eps}")
  port_match_ok = True
  if port_match is not None:
    port_match_ok = bool(port_match.get("line_basis_ok"))
    if not port_match_ok:
      reasons.append(
        f"引擎 ZL 基匹配超门：|S11|_line={port_match.get('s11_line_basis_db'):.2f}dB"
        f" > {port_match.get('line_basis_max_db')}dB（端口分解残差）")
  return {
    "nominal_w": float(nominal_w),
    "eps_eff_nominal": eps[nominal_idx],
    "eps_hj": float(eps_hj),
    "nominal_delta_hj_pct": delta_pct,
    "anchor_ok": anchor_ok,
    "monotonic_ok": monotonic_ok,
    "port_match_ok": port_match_ok if port_match is not None else None,
    "port_match": port_match,
    "eps_eff": eps,
    "verdict": "PASS" if (anchor_ok and monotonic_ok and port_match_ok) else "FAIL",
    "reasons": reasons,
  }


def band_power_avg_db(
  freqs_ghz: Any, s_db: Any, lo_ghz: float, hi_ghz: float,
) -> float:
  """带内功率平均 dB：``10·log10(mean(10^(s_db/10)))``（③ 带宽积分档）。

  dB 值直接算术平均会放大深零点的支配权重；功率域平均下，单个栅格
  敏感的窄零点只贡献其能量份额——判据从"谷点深度"退到"带内泄漏
  能量"，对零点频率的网格自适应漂移一阶不敏感。带内无样本 →
  ValueError（如实报错，不返回占位数字）。
  """
  import numpy as np

  f = np.asarray(freqs_ghz, dtype=float)
  v = np.asarray(s_db, dtype=float)
  if f.shape != v.shape or f.size == 0:
    raise ValueError("freqs_ghz/s_db 形状不一致或为空")
  mask = (f >= float(lo_ghz)) & (f <= float(hi_ghz))
  if not mask.any():
    raise ValueError(
      f"带 [{lo_ghz}, {hi_ghz}] GHz 内无频率样本"
      f"（数据范围 {f.min()}–{f.max()}）")
  power = np.power(10.0, v[mask] / 10.0)
  return float(10.0 * np.log10(float(power.mean())))


def locate_dip_ghz(freqs_ghz: Any, s_db: Any) -> tuple[float, dict[str, Any]]:
  """单点扫频谷位（④ 标定内核）：argmin + 三点抛物线插值细分。

  返回 (f_dip_ghz, meta)；meta 携带 argmin/dip_db/refined——refined=False
  表示谷在采样端点或曲率非极小（denominator ≤ 0），插值未生效，此时
  f_dip = argmin 栅格值（调用方据 refined 位决定是否加密重扫）。
  """
  import numpy as np

  f = np.asarray(freqs_ghz, dtype=float)
  v = np.asarray(s_db, dtype=float)
  if f.shape != v.shape or f.size < 3:
    raise ValueError("谷位定位至少需要 3 个同形频率样本")
  i = int(np.argmin(v))
  f_dip = float(f[i])
  refined = False
  if 0 < i < f.size - 1:
    y0, y1, y2 = float(v[i - 1]), float(v[i]), float(v[i + 1])
    denom = y0 - 2.0 * y1 + y2
    if denom > 0.0:
      delta = 0.5 * (y0 - y2) / denom
      if abs(delta) <= 1.0:
        f_dip = float(f[i] + delta * (f[i + 1] - f[i]))
        refined = True
  return f_dip, {
    "argmin_ghz": float(f[i]), "dip_db": float(v[i]),
    "refined": refined, "f_dip_ghz": f_dip,
    "n_points": int(f.size),
  }


def dip_constant(f_dip_ghz: float, dim_mm: float) -> float:
  """谐振经验常数 f_dip·L（GHz·mm；④ 标定量，按引擎漂移）。"""
  return float(f_dip_ghz) * float(dim_mm)


def recenter_length_for_target(f_target_ghz: float, constant: float) -> float:
  """按引擎常数定标目标频率所需尺寸：``L* = 常数 / f_target``（④）。

  问题定义纪律：先在本引擎扫频标定常数，再定尺寸/中心频率——
  直接沿用他引擎常数（如把 openEMS 的 76.8 用到 HFSS）会让首版
  优化目标落空（wp39 首轮 patch 2.0GHz 目标盒内无谷的根因）。
  """
  if float(f_target_ghz) <= 0.0:
    raise ValueError("目标频率必须为正")
  return float(constant) / float(f_target_ghz)


def deep_null_neighborhood_db(
  freqs_ghz: Any, s_db: Any,
  search_lo_ghz: float, search_hi_ghz: float, half_window_ghz: float,
) -> float:
  """深零点邻域指标（③）：搜索带内实测谷位 ± half_window 的功率平均。

  判读从"固定 f0 单频谷深"改为"实测谷位邻域能量"——网格自适应把
  谷点在邻域内挪动不再改变判读值；谷位本身由 locate_dip_ghz 同源
  定位（argmin，不再插值——邻域平均下插值增益可忽略）。搜索带内
  无样本 → ValueError（如实报错）。
  """
  import numpy as np

  f = np.asarray(freqs_ghz, dtype=float)
  v = np.asarray(s_db, dtype=float)
  mask = (f >= float(search_lo_ghz)) & (f <= float(search_hi_ghz))
  if not mask.any():
    raise ValueError(
      f"搜索带 [{search_lo_ghz}, {search_hi_ghz}] GHz 内无频率样本")
  sub_f, sub_v = f[mask], v[mask]
  f_null = float(sub_f[int(np.argmin(sub_v))])
  return band_power_avg_db(
    f, v, f_null - float(half_window_ghz), f_null + float(half_window_ghz))


def merge_factory_with_replay(
  factory: dict[str, Any], replay: dict[str, Any], *,
  metric_name: str,
) -> dict[str, Any]:
  """①档合并契约：openEMS 工厂最优参数 × HFSS 回代指标 → candidate。

  judge_problem_pair 的 candidate 形状要求：best.metric 取 **HFSS 回代**
  指标（"回代同一评估器"判 cost，方案），wall 取工厂环优化墙钟；
  工厂环内的 openEMS 指标与回代评估数如实进 factory_extra（回代评估
  独立记账，不计入工厂真跑预算——它是仲裁步不是环内评估）。
  工厂无 best 或回代指标缺失 → ValueError（调用方如实记 FAIL）。
  """
  best = factory.get("best")
  if not isinstance(best, dict) or not best.get("params"):
    raise ValueError("工厂战役无 best（全评估失败或未运行），无法合并")
  rp_metrics = replay.get("metrics") or {}
  rp_metric = rp_metrics.get(metric_name)
  if not isinstance(rp_metric, (int, float)) or isinstance(rp_metric, bool):
    raise ValueError(f"回代指标缺失或非法: {rp_metric!r}")
  wall = factory.get("wall_s") or {}
  opt_s = wall.get("optimization_s")
  if not opt_s:
    opt_s = factory.get("elapsed_s")
  return {
    "problem": factory.get("problem"),
    "best": {
      "params": dict(best["params"]),
      "metric": float(rp_metric),
      "cost": None,
    },
    "n_evals": int(factory.get("n_attempts")
            if factory.get("n_attempts") is not None
            else factory.get("n_evals") or 0),
    "wall_s": {"optimization_s": float(opt_s or 0.0)},
    "factory_extra": {
      "cost_source": "hfss_replay",
      "factory_metric": (best.get("metrics") or {}).get(metric_name),
      "replay_metric": float(rp_metric),
      "replay_n_evals": replay.get("n_evals"),
      "replay_wall_s": replay.get("wall_s"),
      "cross_engine_note": (
        "①档口径（方案）：openEMS 数据工厂寻优 + HFSS 回代"
        "仲裁 cost；回代评估独立于工厂预算"),
    },
  }


# ── mline MSLPort |S11| 伪底判据内核─────────────────────
# 机理（归因存档 + #250 新证据）：mline 模板
# CalcPort(ref_impedance=50) 下单激励 |S11| 是 50Ω 基**带载比值**；均匀线两端
# 入 PML 无远端失配 ⇒ 物理 |S11| ≡ |Γ(Z_line, 50)|。引擎自算线阻抗 ZL
# （MSLPort.ReadUIData 三探针 sqrt(Et·dEt/(Ht·dHt))）对 HJ 系统性偏低
# （wstep 实证 −4.7%/−3.7%），H1：伪底 = |Γ(ZL_engine, 50)| 的真实失配反射；
# H2（旧假设）：端口面 V/I 行波分解残差。分离手段=把 50Ω 基 r11 按
# `loaded_ratios_to_line_basis` 对角式换到引擎 ZL 基——匹配线在自身基下应
# → 0，剩余量即 H2 残差（端口算法伪底真实量级）。数值只在确定性内核（铁律 7）。

#: 引擎 ZL 基匹配门：均匀匹配线在自身阻抗基下 |S11| ≤ 该值即判"端口分解
#: 残差可接受"（|Γ|≈3.2%，工程端口匹配惯例）。预声明常量，不随数据挪动。
MLINE_LINE_BASIS_S11_MAX_DB = -30.0
#: H1 主导判据：换基（50Ω→引擎 ZL）后 |S11| 至少降该 dB 数，且线基值过门。
#: 6dB = 线性幅度减半，是"失配项贡献至少一半以上反射能量"的最小可辩护口径。
H1_DOMINANCE_MIN_GAIN_DB = 6.0
#: |Γ| dB 夹底（Z 精确等于参考时 20·log10(0)=−inf，JSON 不可序列化）。
GAMMA_DB_FLOOR = -200.0
#: openEMS 通道线阻抗经验偏差（引擎 ZL 对 HJ 闭式，%）——**经验修正常数**，
#: 来源：本项 mline 真机三宽度×网格与 wstep
#: pt3_s22_renorm（50Ω −4.7%/35Ω −3.7%）拟合；适用范围
#: rogers4350b_h0.508 微带、官方口径网格（λ_sub/50 base，NEAR=base/4）、
#: 2–3GHz。**不进 core/synthesis HJ 内核**（铁律 7：常数来自真机拟合并可由
#: mline_pseudofloor_probe.py 复算）；调用方显式传入 `engine_z0_from_hj`。
#: None = 尚未标定（本项真机收口后由 progress/h1_check.json 回填数值）。
OPENEMS_MLINE_Z0_BIAS_PCT: float | None = None

#: 逐网格档 ZL 偏差表（%）：**ZL 偏差强依赖网格**（H1 机理=阶梯化线宽量化随
#: 网格收敛：1.2mm −11.80% → 0.2mm −4.21%，单调向 HJ 收敛、无常数平台——
#: 0.25→0.2mm 实测 −4.67→−4.21% 与线性外推 −4.11% 吻合，细网格收敛性已判定
#: 为"随网格收敛"而非"固定偏差"），单一常数只在声明网格档内有效——按档登记，
#: 键=网格 base（mm）。来源：归档重放 10 档（
#: h1_check_archive/meshconv.json）+ 真机 4 点（h1_check_real.json，新模板 ZL
#: 列与重放逐位一致）；0.8/1.2 档为三宽度均值（w=0.85/1.113/1.4），其余为
#: w=1.113 单宽度（auto 档 BASE=λ_sub/50@F_MAX 计算值）如实标注。
#: 复算：scripts/mline_pseudofloor_probe.py check --run-dir <归档点> ...。
OPENEMS_MLINE_Z0_BIAS_BY_MESH: dict[float, float] = {
  1.2: -10.48,  # 三宽度均值（−11.15/−11.80/−8.48，工厂档）
  1.1405: -11.77, # auto 档单宽度（w=1.113）
  0.8: -8.08,  # 三宽度均值（−8.43/−8.66/−7.16）
  0.6: -7.16,  # 单宽度
  0.4: -5.65,  # 单宽度（wstep 0.4mm 档 50Ω 线 47.64=−4.72% 互证）
  0.25: -4.67,  # 单宽度
  0.2: -4.21,  # 单宽度（真机 8243.6s，收敛性判定档）
}


def reflection_db(z_line_ohm: complex, z_ref_ohm: float = 50.0,
         *, floor_db: float = GAMMA_DB_FLOOR) -> float:
  """|Γ| = |(Z−Z_ref)/(Z+Z_ref)| → dB（夹底 floor_db；Z 可复数）。"""
  z = complex(z_line_ohm)
  zr = float(z_ref_ohm)
  if zr <= 0.0:
    raise ValueError("z_ref_ohm 必须为正")
  if not (math.isfinite(z.real) and math.isfinite(z.imag)):
    raise ValueError(f"z_line_ohm 非有限值: {z_line_ohm!r}")
  mag = abs((z - zr) / (z + zr))
  if mag <= 0.0:
    return float(floor_db)
  return max(float(floor_db), 20.0 * math.log10(mag))


def s11_to_line_basis(r11: complex, z_line_ohm: complex,
           z_ref_ohm: float = 50.0) -> complex:
  """50Ω 基单激励带载比值 r11 → 线自身 Z 基 S11（标量式）。

  与 adapters/openems_templates.loaded_ratios_to_line_basis 的对角项同式：
    S = [zr(1+r) − Z(1−r)] / [zr(1+r) + Z(1−r)]
  Z==zr 时恒等。单元测试对拍 helper 逐位一致。
  """
  r = complex(r11)
  z = complex(z_line_ohm)
  zr = float(z_ref_ohm)
  num = zr * (1.0 + r) - z * (1.0 - r)
  den = zr * (1.0 + r) + z * (1.0 - r)
  if den == 0:
    raise ValueError("线基换算分母为零（Z 与 r 组合退化）")
  return num / den


def median_in_window(
  freqs_hz: Any, values: Any, f_target_hz: float,
  *, window_frac: float = EPS_EFF_WINDOW_FRAC,
) -> complex:
  """±window_frac 频窗内逐分量中值（复数：实/虚部各取中值）。

  与 eps_eff_from_beta 同窗口径（默认 ±4%），用于引擎 ZL(f) 的带内代表值
  （带内色散 ±0.05Ω 量级，中值抗单点毛刺）。窗内无样本 → ValueError。
  """
  import numpy as np

  f = np.asarray(freqs_hz, dtype=float)
  v = np.asarray(values, dtype=complex)
  if f.shape != v.shape or f.size == 0:
    raise ValueError("freqs_hz/values 形状不一致或为空")
  f_t = float(f_target_hz)
  if f_t <= 0.0 or not (0.0 < float(window_frac) < 1.0):
    raise ValueError("f_target_hz 必须为正且 window_frac∈(0,1)")
  sel = (f >= (1.0 - window_frac) * f_t) & (f <= (1.0 + window_frac) * f_t)
  if not sel.any():
    raise ValueError(
      f"频窗 [{(1 - window_frac) * f_t:.6g}, {(1 + window_frac) * f_t:.6g}] "
      f"Hz 内无样本（数据范围 {f.min():.6g}–{f.max():.6g}）")
  return complex(float(np.median(v[sel].real)), float(np.median(v[sel].imag)))


def interp_complex_at(freqs_hz: Any, values: Any, f_target_hz: float) -> complex:
  """复数序列在 f_target 的线性插值（实/虚部分别插值；越界 → ValueError）。"""
  import numpy as np

  f = np.asarray(freqs_hz, dtype=float)
  v = np.asarray(values, dtype=complex)
  if f.shape != v.shape or f.size < 2:
    raise ValueError("插值至少需要 2 个同形频率样本")
  f_t = float(f_target_hz)
  if not (f.min() <= f_t <= f.max()):
    raise ValueError(f"f_target {f_t:.6g} 越出数据范围 {f.min():.6g}–{f.max():.6g}")
  order = np.argsort(f)
  return complex(float(np.interp(f_t, f[order], v.real[order])),
          float(np.interp(f_t, f[order], v.imag[order])))


def mag_db(value: complex, *, floor_db: float = GAMMA_DB_FLOOR) -> float:
  """20·log10|value|（夹底）。"""
  mag = abs(complex(value))
  if mag <= 0.0:
    return float(floor_db)
  return max(float(floor_db), 20.0 * math.log10(mag))


def mline_port_match_health(
  *,
  w_mm: float,
  z0_hj_ohm: float,
  zl_engine_ohm: complex,
  s11_raw_50: complex,
  z_ref_ohm: float = 50.0,
  line_basis_max_db: float = MLINE_LINE_BASIS_S11_MAX_DB,
  h1_min_gain_db: float = H1_DOMINANCE_MIN_GAIN_DB,
) -> dict[str, Any]:
  """mline 单档端口匹配健康判据（引擎 ZL 基）+ H1/H2 分离量。

  输入均为 2.5GHz 代表值（ZL 取 median_in_window、r11 取 interp_complex_at）。
  输出字段：
  - ``z0_dev_pct``：引擎 Re(ZL) 对 HJ Z0 偏差 %（经验修正常数的原材料）；
  - ``s11_meas_50_db``：旧 50Ω 基 |S11|（**保留为诊断量**，不再作门）；
  - ``s11_pred_50_db``：H1 预测 |Γ(ZL_engine, 50)| dB；
  - ``h1_residual_db``：实测 − 预测（50Ω 基）；
  - ``s11_line_basis_db``：引擎 ZL 基 |S11|（**新门**：≤ line_basis_max_db）；
  - ``basis_gain_db``：换基降幅 = s11_meas_50_db − s11_line_basis_db；
  - ``h1_dominant``：basis_gain_db ≥ h1_min_gain_db ∧ 线基过门；
  - ``verdict``：PASS ⇔ 线基过门（端口分解残差可接受）。
  纯函数零真机。
  """
  if float(z0_hj_ohm) <= 0.0:
    raise ValueError("z0_hj_ohm 必须为正")
  zl = complex(zl_engine_ohm)
  if zl.real <= 0.0:
    raise ValueError(f"引擎 ZL 实部非正: {zl!r}")
  r11 = complex(s11_raw_50)
  z0_dev_pct = (zl.real / float(z0_hj_ohm) - 1.0) * 100.0
  s11_meas_50_db = mag_db(r11)
  s11_pred_50_db = reflection_db(zl, z_ref_ohm)
  s11_line = s11_to_line_basis(r11, zl, z_ref_ohm)
  s11_line_db = mag_db(s11_line)
  basis_gain_db = s11_meas_50_db - s11_line_db
  line_basis_ok = bool(s11_line_db <= float(line_basis_max_db))
  h1_dominant = bool(line_basis_ok and basis_gain_db >= float(h1_min_gain_db))
  reasons: list[str] = []
  if not line_basis_ok:
    reasons.append(
      f"引擎 ZL 基 |S11|={s11_line_db:.2f}dB 超门 {line_basis_max_db}dB"
      "（端口分解残差/H2 项不可忽略）")
  if not h1_dominant and line_basis_ok:
    reasons.append(
      f"换基降幅 {basis_gain_db:.2f}dB < {h1_min_gain_db}dB：50Ω 基反射并非"
      "由 ZL 失配主导（H1 弱）")
  return {
    "w_mm": float(w_mm),
    "z0_hj_ohm": float(z0_hj_ohm),
    "zl_engine_re_ohm": zl.real,
    "zl_engine_im_ohm": zl.imag,
    "z0_dev_pct": z0_dev_pct,
    "s11_meas_50_db": s11_meas_50_db,
    "s11_pred_50_db": s11_pred_50_db,
    "h1_residual_db": s11_meas_50_db - s11_pred_50_db,
    "s11_line_basis_db": s11_line_db,
    "basis_gain_db": basis_gain_db,
    "line_basis_max_db": float(line_basis_max_db),
    "line_basis_ok": line_basis_ok,
    "h1_dominant": h1_dominant,
    "verdict": "PASS" if line_basis_ok else "FAIL",
    "reasons": reasons,
  }


def judge_pseudofloor_hypothesis(rows: list[dict[str, Any]]) -> dict[str, Any]:
  """多档聚合裁决 H1/H2（rows = mline_port_match_health 输出列表）。

  - ``H1``：全部档 h1_dominant（换基降幅 ≥ 6dB ∧ 线基过门）——伪底=ZL 失配
   的真实反射，修法=引擎 ZL 基判据 + Z0 经验修正；
  - ``H2``：无档 h1_dominant 且存在线基超门——端口分解残差主导；
  - ``MIXED``：其余（部分档 H1、部分 H2，或全部线基过门但降幅不足）。
  附 z0_dev_pct 统计（均值/极差）供经验修正常数标定；空列表 → ValueError。
  """
  if not rows:
    raise ValueError("rows 为空，无法裁决")
  n = len(rows)
  n_h1 = sum(1 for r in rows if r.get("h1_dominant"))
  n_line_ok = sum(1 for r in rows if r.get("line_basis_ok"))
  devs = [float(r["z0_dev_pct"]) for r in rows]
  if n_h1 == n:
    verdict = "H1"
  elif n_h1 == 0 and n_line_ok < n:
    verdict = "H2"
  else:
    verdict = "MIXED"
  return {
    "verdict": verdict,
    "n_rows": n,
    "n_h1_dominant": n_h1,
    "n_line_basis_ok": n_line_ok,
    "z0_dev_pct_mean": sum(devs) / n,
    "z0_dev_pct_min": min(devs),
    "z0_dev_pct_max": max(devs),
    "line_basis_max_db": MLINE_LINE_BASIS_S11_MAX_DB,
    "h1_min_gain_db": H1_DOMINANCE_MIN_GAIN_DB,
  }


def engine_z0_from_hj(z0_hj_ohm: float,
           bias_pct: float | None = OPENEMS_MLINE_Z0_BIAS_PCT) -> float:
  """HJ 闭式 Z0 → openEMS 通道预期线阻抗（经验修正：Z·(1+bias/100)）。

  bias_pct=None（未标定）→ ValueError，禁止静默恒等（调用方必须显式知道
  常数是否已标定）。不改 HJ 内核，只在 openEMS 通道消费侧使用。
  """
  if bias_pct is None:
    raise ValueError(
      "OPENEMS_MLINE_Z0_BIAS_PCT 尚未标定（None）：先由 "
      "scripts/mline_pseudofloor_probe.py 真机数据回填，或显式传 bias_pct")
  if float(z0_hj_ohm) <= 0.0:
    raise ValueError("z0_hj_ohm 必须为正")
  return float(z0_hj_ohm) * (1.0 + float(bias_pct) / 100.0)
