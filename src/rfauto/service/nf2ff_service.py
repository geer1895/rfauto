"""nf2ff 远场/SAR 服务层（WP4.1 / D4，openEMS 原生）。

职责（服务层 JSON 进出，UI/CLI/MCP 薄壳）：
- 盘点 runs/ 下含远场产物的 run（模板 far_field/sar=True 真跑落盘）；
- 单 run 远场视图：farfield_meta.json + farfield_cut.csv → 切面极坐标
 序列（θ-dB）+ 指标（Dmax/增益/效率/HPBW/前后比/功率闭合），数值
 全部出自确定性内核（openEMS 脚本 + core.farfield，LLM 零参与）；
- SAR 视图：sar.csv（IEEE_62704 1g 平均，含 1W 接受功率归一值）+
 功率守恒闭合（P_acc vs Prad+P_abs，官方 Dipole SAR 教程口径）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

RUNS_DIR = Path("runs")


def _find_run_dirs(base: Path) -> list[Path]:
  """runs/ 下一级 run 目录（含产物扫描由 find_artifacts 做）。"""
  if not base.is_dir():
    return []
  return sorted(p for p in base.iterdir() if p.is_dir())


def _shallow_artifacts(run_dir: Path) -> dict[str, Path]:
  """浅层产物探测（runs/ 清单热路径免全树 rglob）。

  已知落盘层级：run 根（模板脚本目录，主路）与 fdtd/（SIM_PATH）。
  """
  from rfauto.core.farfield import (
    FARFIELD_CUT_NAME,
    FARFIELD_META_NAME,
    SAR_CSV_NAME,
  )

  found: dict[str, Path] = {}
  for name in (FARFIELD_META_NAME, FARFIELD_CUT_NAME, SAR_CSV_NAME):
    for cand in (run_dir / name, run_dir / "fdtd" / name):
      if cand.is_file():
        found[name] = cand
        break
  return found


def farfield_runs(limit: int = 50) -> dict[str, Any]:
  """含远场/SAR 产物的 run 清单（远场极坐标页的候选下拉）。"""
  from rfauto.core.farfield import (
    FARFIELD_CUT_NAME,
    FARFIELD_META_NAME,
    SAR_CSV_NAME,
  )

  hits: list[dict[str, Any]] = []
  for run_dir in _find_run_dirs(RUNS_DIR):
    found = _shallow_artifacts(run_dir)
    if FARFIELD_META_NAME not in found:
      continue
    hits.append({
      "run_id": run_dir.name,
      "has_cut": FARFIELD_CUT_NAME in found,
      "has_sar": SAR_CSV_NAME in found,
      "mtime": found[FARFIELD_META_NAME].stat().st_mtime,
    })
  hits.sort(key=lambda h: -h["mtime"])
  return {"ok": True, "runs": hits[: max(1, int(limit))]}


def _read_metrics(
  meta: dict[str, Any], sar: dict[str, Any] | None,
  pattern3d: tuple[Any, Any, Any] | None = None,
) -> dict[str, Any]:
  """汇总指标（meta 数值为脚本内核产出；组合指标在服务层组装）。

  功率账口径（真机冒烟校准）：P_acc−Prad = 组织吸收功率
  （有 SAR 注入时两者恰闭合）；sar.csv 的 p_abs_w 属性是激励总功率
  归一（与端口逐频谱功率不同尺度，实测 ~15×），不得混入预算闭合。

  PEC 地镜像修正：接地辐射模板的 nf2ff 盒底贴 PEC
  地 → openEMS 把 Prad 双计/Dmax 折半（core.farfield.correct_pec_mirror
  注记），此处按盒几何确定性修正；修正前原值保留在 metrics["raw"]。
  pattern3d=(θ°, φ°, dB 网格) 时另给图形自归一方向性（教科书口径）作
  交叉校验：dmax_pattern_dbi 取物理辐射半球（镜像件=上半球）。
  """
  from rfauto.core.farfield import (
    correct_pec_mirror,
    dmax_dbi,
    dmax_from_pattern,
    pattern_power_from_db,
  )

  fixed = correct_pec_mirror(meta)
  metrics: dict[str, Any] = {
    "f_res_ghz": fixed.get("f_res_ghz"),
    "dmax_dbi": fixed.get("dmax_dbi"),
    "gain_max_dbi": fixed.get("gain_max_dbi"),
    "efficiency": fixed.get("efficiency"),
    "power_budget_closure": fixed.get("power_budget_closure"),
    "pec_mirror_factor": fixed.get("pec_mirror_factor", 1.0),
  }
  if "raw" in fixed:
    metrics["raw"] = fixed["raw"]
  if pattern3d is not None:
    th_deg, ph_deg, db = pattern3d
    try:
      import numpy as np

      p = pattern_power_from_db(db)
      th = np.deg2rad(np.asarray(th_deg, dtype=float))
      ph = np.deg2rad(np.asarray(ph_deg, dtype=float))
      d_full = dmax_from_pattern(p, th, ph, "full")
      d_up = dmax_from_pattern(p, th, ph, "upper")
      metrics["dmax_pattern_full_dbi"] = dmax_dbi(d_full)
      metrics["dmax_pattern_upper_dbi"] = dmax_dbi(d_up)
      metrics["dmax_pattern_dbi"] = dmax_dbi(
        d_up if metrics["pec_mirror_factor"] > 1.0 else d_full)
    except ValueError:
      pass # 网格不构成球面（切面级产物）→ 不给交叉值，不虚构
  if sar and sar.get("ok"):
    vals = sar.get("values") or {}
    metrics["sar"] = {
      "mass_g": vals.get("mass_g"),
      "sar_max_w_per_kg": vals.get("sar_max_w_per_kg"),
      "sar_max_w_per_kg_per_1w_acc":
        vals.get("sar_max_w_per_kg_per_1w_acc"),
      "absorbed_fraction": (None if not metrics["efficiency"]
                 else 1.0 - metrics["efficiency"]),
    }
  return metrics


def farfield_view(run_id: str) -> dict[str, Any]:
  """单 run 远场视图（polar 页数据：切面 θ-dB 序列 + 指标 + SAR）。"""
  from rfauto.core.farfield import (
    FARFIELD_3D_NAME,
    FARFIELD_CUT_NAME,
    FARFIELD_META_NAME,
    SAR_CSV_NAME,
    find_artifacts,
    parse_farfield_3d_csv,
    parse_farfield_cut_csv,
    pattern_db,
    summarize_cut,
  )

  run_dir = RUNS_DIR / run_id
  if not run_dir.is_dir():
    return {"ok": False, "errors": [f"run 不存在: {run_id}"]}
  found = find_artifacts(run_dir)
  if FARFIELD_META_NAME not in found:
    return {"ok": False,
        "errors": [f"该 run 无远场产物（需 far_field=True 真跑）: {run_id}"]}

  import json

  try:
    meta = json.loads(found[FARFIELD_META_NAME].read_text(encoding="utf-8"))
  except Exception as e:
    return {"ok": False, "errors": [f"farfield_meta.json 解析失败: {e}"]}
  if not meta.get("ok"):
    return {"ok": False, "errors": [
      f"远场链在脚本内失败: {meta.get('error', 'unknown')}"]}

  sar: dict[str, Any] | None = None
  if SAR_CSV_NAME in found:
    try:
      rows: dict[str, float] = {}
      with open(found[SAR_CSV_NAME], encoding="utf-8") as fh:
        fh.readline()
        for line in fh:
          parts = line.strip().split(",")
          if len(parts) >= 2:
            try:
              rows[parts[0]] = float(parts[1])
            except ValueError:
              continue
      sar = {"ok": True, "values": rows}
    except Exception as e:
      sar = {"ok": False, "error": str(e)}

  cuts: list[dict[str, Any]] = []
  if FARFIELD_CUT_NAME in found:
    for cut in parse_farfield_cut_csv(found[FARFIELD_CUT_NAME]):
      pdb = pattern_db(cut["e_norm"])
      s = summarize_cut(cut["theta_deg"], cut["e_norm"])
      cuts.append({
        "phi_deg": cut["phi_deg"],
        "theta_deg": [round(float(t), 3) for t in cut["theta_deg"]],
        "pattern_db": [round(float(v), 3) for v in pdb],
        **s,
      })

  pattern3d: dict[str, Any] | None = None
  if FARFIELD_3D_NAME in found:
    # 只回传稀疏网格的 dB 矩阵（theta 0..180/5 × phi 0..355/5 ≈ 2.6k 点）
    theta: list[float] = []
    phi: list[float] = []
    grid: list[list[float | None]] = []
    try:
      with open(found[FARFIELD_3D_NAME], encoding="utf-8") as fh:
        fh.readline()
        cur_theta: float | None = None
        row: list[float | None] = []
        for line in fh:
          parts = line.strip().split(",")
          if len(parts) < 3:
            continue
          t, p = float(parts[0]), float(parts[1])
          v = float(parts[2])
          if t != cur_theta:
            if row:
              grid.append(row)
              row = []
            theta.append(t)
            cur_theta = t
          if cur_theta == theta[0]:
            phi.append(p) # 第一行 theta 记录完整 phi 轴
          row.append(None if v != v else round(v, 2))
        if row:
          grid.append(row)
      pattern3d = {"theta_deg": theta, "phi_deg": phi, "db": grid}
    except Exception:
      pattern3d = None # 3D 体图 best-effort，缺省不影响切面页

  grid3d: tuple[Any, Any, Any] | None = None
  if FARFIELD_3D_NAME in found:
    try:
      grid3d = parse_farfield_3d_csv(found[FARFIELD_3D_NAME])
    except Exception:
      grid3d = None # 交叉校验 best-effort（#105）

  return {
    "ok": True,
    "run_id": run_id,
    "template": meta.get("template"),
    "metrics": _read_metrics(meta, sar, grid3d),
    "meta": meta,
    "cuts": cuts,
    "pattern3d": pattern3d,
  }
