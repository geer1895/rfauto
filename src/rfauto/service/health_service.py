"""run 健康度体检服务层（G11）——runs/<run_id>/ 产物读取 + core 内核组装。

职责切分（服务层薄壳）：run 产物发现/解析/JSON 编排在 service，确定性
判据全部在 core/solve_health.py。本模块 best-effort（#105）：run 目录不
存在/全空 → ok=False + errors 说明，不抛异常；单类产物解析失败记入
errors 后继续，缺失因子由内核标 UNKNOWN。

产物发现约定（与仓内既有写入口径一致）：
- S 参数：results/params.s*p Touchstone（service/api.generate_report_for_run
 同款 glob）→ 任意位置 sparams.csv（openEMS 模板 schema，见
 adapters/openems_solver._parse_output：freq_hz + re/im S11/S21[/S31/S23]
 的部分矩阵）→ 任意位置 *.sNp Touchstone。
- cost：trials/trial_*.json 的 cost 字段（按 trial_number 排序）→
 results/metrics.json 的 cost。
- timestep（#152）：run 目录下 *.log 的 "FDTD timestep is: <x> s" 行
 （openEMS run.log 实测格式）+ meta.json 的 timestep* 字段。
- 各端口 εeff（1.0491）：port_beta.csv 的 beta*_rad_per_m 列 →
 εeff = (β·c0 / 2πf)² 的逐频中位数。
- mirror_symmetric：meta.json 的 mirror_symmetric 键（best-effort）。
- 功率守恒（D3-1/G11）：dump_type=29 体 dump（infra/loss_dump 逐
 cell 积分）→ field_power_w；sparams 在 dump 频点线性插值出激励行 s_row；
 归档无入射功率口径 → 耗散一侧留 UNKNOWN 只留证据。openEMS 自算 SAR
 （SAR_*g.h5 的 power 属性）作 ∫q dV 的自检对照。
- 热合理性（G11）：meta.json thermal 块 > icepak.anchor.sim（真跑锚）>
 chain.thermal（注入场景）> d32_closure_summary.json transient_run，
 best-effort 映射（#105 失败只记 errors）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.solve_health import (
  COST_DEGENERATE_MIN_TRIALS,
  COST_DEGENERATE_VAR_FLOOR,
  FACTOR_COST,
  FAIL,
  LESSON_COST_DEGENERATE,
  THERMAL_INPUT_KEYS,
  solve_health_check,
)

_C0 = 299792458.0
_TIMESTEP_RE = re.compile(r"FDTD timestep is:\s*([0-9.eE+\-]+)\s*s")

# 探针频带：TEMPLATE_META f0 × [0.8, 1.2]，201 点（覆盖设计带与近邻，
# 与 calibration_service 的 201 点口径一致；不是物理设计数，只是采样窗）
_PROBE_FREQ_SPAN = (0.8, 1.2)
_PROBE_FREQ_POINTS = 201


# ---------------------------------------------------------------------------
# 产物读取（各自 best-effort，失败返回 None / 空并记 error）
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any] | None:
  """读 JSON 文件，失败返回 None（不抛）。"""
  try:
    return json.loads(path.read_text(encoding="utf-8"))
  except Exception:
    return None


def _load_touchstone(run_dir: Path, errors: list[str]) -> tuple[np.ndarray, np.ndarray] | None:
  """加载 Touchstone S 参数 → (freq_hz, s_matrix)；skrf 缺失/解析失败为 None。"""
  candidates = sorted((run_dir / "results").glob("params.s*p"))
  candidates += [p for p in sorted(run_dir.rglob("*.s2p")) + sorted(run_dir.rglob("*.s3p"))
          + sorted(run_dir.rglob("*.s4p")) if p not in candidates]
  if not candidates:
    return None
  try:
    import skrf  # 懒加载（SpecEvaluator 惯例：顶层不 import skrf）
  except Exception as exc:
    errors.append(f"skrf 不可用，Touchstone 未读取: {exc}")
    return None
  for path in candidates:
    try:
      network = skrf.Network(str(path))
      return (
        np.asarray(network.f, dtype=float),
        np.asarray(network.s, dtype=complex),
      )
    except Exception as exc:
      errors.append(f"Touchstone 解析失败 {path.name}: {exc}")
  return None


def _parse_sparams_csv_masked(
  csv_path: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
  """解析 openEMS sparams.csv → (freq_hz, s_matrix, measured_mask)。

  schema 同 adapters/openems_solver._parse_output：第 1 列 freq_hz，随后
  re/im S11、re/im S21（≥9 列再接 re/im S31、re/im S23 构成 3 端口部分
  矩阵，未测元素置零）。

  measured_mask 是 (n_ports, n_ports) bool：True 只标 **直接来自 csv 列**
  的元素；按互易补齐（S12:=S21、S32:=S23）与按对称补齐（S22:=S11）的元素
  为 False。它喂给 G11 互易性因子——单激励产物里 (i,j)/(j,i) 从未同时
  独立测得，置零/补齐元素与已测元素比对是假阳性（曾致入库体检拦下
  6 个 wilkinson/branchline 真机校准 run 被拦，max|Sij−Sji|≈|S21|≈0.65–0.72）。
  """
  data = np.loadtxt(str(csv_path), delimiter=",", skiprows=1, ndmin=2)
  if data.shape[0] == 0 or data.shape[1] < 5:
    return None
  freq_hz = data[:, 0]
  s11 = data[:, 1] + 1j * data[:, 2]
  s21 = data[:, 3] + 1j * data[:, 4]
  n_freq = len(freq_hz)
  if data.shape[1] >= 9:
    s31 = data[:, 5] + 1j * data[:, 6]
    s23 = data[:, 7] + 1j * data[:, 8]
    s = np.zeros((n_freq, 3, 3), dtype=complex)
    mask = np.zeros((3, 3), dtype=bool)
    s[:, 0, 0] = s11
    s[:, 1, 0] = s21
    s[:, 2, 0] = s31
    s[:, 1, 2] = s23
    s[:, 2, 1] = s23 # 互易补齐（非独立测量，掩码 False）
    mask[0, 0] = mask[1, 0] = mask[2, 0] = mask[1, 2] = True
  else:
    s = np.zeros((n_freq, 2, 2), dtype=complex)
    mask = np.zeros((2, 2), dtype=bool)
    s[:, 0, 0] = s11
    s[:, 1, 0] = s21
    s[:, 0, 1] = s21 # 互易补齐（非独立测量，掩码 False）
    s[:, 1, 1] = s11 # 对称补齐（非独立测量，掩码 False）
    mask[0, 0] = mask[1, 0] = True
  return freq_hz, s, mask


def _parse_sparams_csv(csv_path: Path) -> tuple[np.ndarray, np.ndarray] | None:
  """解析 openEMS sparams.csv → (freq_hz, s_matrix)（不带掩码的兼容契约，
  calibration 侧曲线复算等外部调用方按 2 元组解包；体检主路走
  _parse_sparams_csv_masked）。"""
  parsed = _parse_sparams_csv_masked(csv_path)
  if parsed is None:
    return None
  freq_hz, s, _mask = parsed
  return freq_hz, s


class _SparamsCsvCorrupt(Exception):
  """sparams.csv 存在但全部解析失败（读入异常 / shape-reject）。

  csv 是互易掩码载体：其损坏 = S 参数证据损坏，禁止静默回退 Touchstone
  （零填充部分矩阵按全矩阵逐对查互易必假阳性，df3a 假阳性门可无痕重开，
  round5 C-F1）；按 #316 多报方向让 S 参数因子走 None → 如实 UNKNOWN /
  低证据，errors 留痕。
  """


def _load_sparams_csv(
  run_dir: Path, errors: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
  """在 run 目录任意层级找 sparams.csv（openEMS 模板 fdtd/ 子目录 rglob 覆盖）；
  返回 (freq_hz, s_matrix, measured_mask)。

  多个 csv 时第一个可解析的胜出，坏 csv 逐个记 errors（audit S2 不误伤）；
  csv 存在但**全部**解析失败（异常 / shape-reject）→ 抛
  _SparamsCsvCorrupt（调用方**不回退** Touchstone）；csv 不存在 → 返回
  None（调用方回退 Touchstone，现行为不变）。
  """
  n_found = 0
  for path in sorted(run_dir.rglob("sparams.csv")):
    n_found += 1
    try:
      parsed = _parse_sparams_csv_masked(path)
    except Exception as exc:
      errors.append(f"sparams.csv 解析失败 {path}: {exc}")
      continue
    if parsed is not None:
      return parsed
    errors.append(f"sparams.csv 存在但解析失败（shape-reject：0 行或 "
           f"<5 列）{path}")
  if n_found:
    raise _SparamsCsvCorrupt(
      f"sparams.csv 存在但解析失败（shape-reject/异常，{n_found} 个"
      "全不可用）——不回退 Touchstone（掩码载体损坏=S 参数证据损坏，"
      "#316 多报方向：S 参数因子走 UNKNOWN/低证据）")
  return None


def _load_costs(run_dir: Path, errors: list[str]) -> list[float]:
  """收集 cost 序列：trials/trial_*.json（按 trial_number 排序）→ results/metrics.json。"""
  costs: list[float] = []
  trials_dir = run_dir / "trials"
  records: list[tuple[int, float]] = []
  if trials_dir.is_dir():
    for path in sorted(trials_dir.glob("trial_*.json")):
      data = _read_json(path)
      if not data or data.get("cost") is None:
        continue
      try:
        num = int(data.get("trial_number", len(records)))
        records.append((num, float(data["cost"])))
      except (TypeError, ValueError):
        errors.append(f"trial cost 无法解析: {path.name}")
  records.sort(key=lambda r: r[0])
  costs = [c for _, c in records]
  if not costs:
    data = _read_json(run_dir / "results" / "metrics.json")
    if data and data.get("cost") is not None:
      try:
        costs = [float(data["cost"])]
      except (TypeError, ValueError):
        errors.append("results/metrics.json cost 无法解析")
  return costs


def _load_timesteps(run_dir: Path, meta: dict[str, Any] | None, errors: list[str]) -> list[float]:
  """收集 timestep 记录（s）：*.log 的 "FDTD timestep is:" 行 + meta.json 字段。"""
  values: list[float] = []
  try:
    for log_path in sorted(run_dir.rglob("*.log")):
      try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
      except Exception:
        continue
      for match in _TIMESTEP_RE.finditer(text):
        try:
          values.append(float(match.group(1)))
        except ValueError:
          continue
  except Exception as exc:
    errors.append(f"日志扫描失败: {exc}")
  if meta:
    for key in ("timestep", "timestep_s", "fdtd_timestep_s", "timesteps"):
      raw = meta.get(key)
      if raw is None:
        continue
      seq = raw if isinstance(raw, (list, tuple)) else [raw]
      for item in seq:
        try:
          values.append(float(item))
        except (TypeError, ValueError):
          errors.append(f"meta.json {key} 值无法解析为 float")
  return values


def _load_eps_eff(run_dir: Path, meta: dict[str, Any] | None, errors: list[str]) -> dict[str, float] | None:
  """各端口 εeff：port_beta.csv 的 beta*_rad_per_m 列 → (β·c0/2πf)² 逐频中位数。

  port_beta.csv 由 openEMS 模板插桩落盘（#189），表头形如
  freq_hz,beta_rad_per_m / freq_hz,beta1_rad_per_m,beta2_rad_per_m[,...]。
  meta.json 的 eps_eff_by_port 键（若有）作兜底。
  """
  for csv_path in sorted(run_dir.rglob("port_beta.csv")):
    try:
      header = csv_path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
      columns = [c.strip() for c in header.split(",")]
      beta_idx = [i for i, c in enumerate(columns) if "beta" in c and "rad_per_m" in c]
      if not beta_idx:
        continue
      data = np.loadtxt(str(csv_path), delimiter=",", skiprows=1, ndmin=2)
      freq_hz = data[:, 0]
      eps: dict[str, float] = {}
      for i in beta_idx:
        beta = data[:, i]
        with np.errstate(divide="ignore", invalid="ignore"):
          samples = (beta * _C0 / (2.0 * np.pi * freq_hz)) ** 2
        samples = samples[np.isfinite(samples) & (samples > 0)]
        if samples.size:
          port_name = columns[i].replace("_rad_per_m", "").replace("beta", "port")
          port_name = port_name if port_name != "port" else "port1"
          eps[port_name] = float(np.median(samples))
      if len(eps) >= 2:
        return eps
    except Exception as exc:
      errors.append(f"port_beta.csv 解析失败 {csv_path}: {exc}")
  if meta and isinstance(meta.get("eps_eff_by_port"), dict):
    try:
      return {str(k): float(v) for k, v in meta["eps_eff_by_port"].items()}
    except (TypeError, ValueError):
      errors.append("meta.json eps_eff_by_port 值无法解析")
  return None


# ---------------------------------------------------------------------------
# G11 补强（D3-1）：损耗 dump 功率 + 热合理性产物发现
# ---------------------------------------------------------------------------

def _interp_s_row(
  freq_hz: np.ndarray,
  s_matrix: np.ndarray,
  target_hz: float,
) -> list[complex] | None:
  """dump 频点处插值激励端口行 S_1j（列 0 = 激励端口，openEMS sparams 惯例）。

  实/虚部逐列线性插值；target 不在 [min, max] 频率范围内 → None（不外推，
  如实缺失）。非有限值行跳过。
  """
  f = np.asarray(freq_hz, dtype=float).reshape(-1)
  s = np.asarray(s_matrix, dtype=complex)
  if f.size < 2 or s.ndim != 3 or s.shape[0] != f.size:
    return None
  if not (float(np.min(f)) <= target_hz <= float(np.max(f))):
    return None
  order = np.argsort(f)
  f_sorted = f[order]
  s_sorted = s[order, 0, :] # 激励行
  row: list[complex] = []
  for j in range(s_sorted.shape[1]):
    col = s_sorted[:, j]
    ok = np.isfinite(col.real) & np.isfinite(col.imag)
    if int(np.count_nonzero(ok)) < 2:
      continue
    re = float(np.interp(target_hz, f_sorted[ok], col.real[ok]))
    im = float(np.interp(target_hz, f_sorted[ok], col.imag[ok]))
    row.append(complex(re, im))
  return row or None


def _load_loss_power(
  run_dir: Path,
  errors: list[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
  """dump_type=29 体 dump → (power_balance_inputs, dump 证据)。

  - field_power_w：infra/loss_dump 逐 cell 欧姆积分（峰值相量口径）；
  - sar 自检：同目录 openEMS 自算 SAR_*.h5 的 power 属性 vs 本地积分，
   相对差记进证据（≤1e-3 视为锚合，只记录不判定）；
  - best-effort（#105）：h5py 缺失/无 dump/解析失败 → (None, None) +
   errors（读档失败才记，无 dump 不记——常态）。
  """
  try:
    from rfauto.infra.loss_dump import (  # 懒加载（h5py 只在 infra 内出现）
      KIND_PROCESSED_SAR,
      find_volume_loss_dumps,
      read_loss_dump,
    )
  except Exception as exc: # pragma: no cover - infra 导入失败
    errors.append(f"loss_dump 模块不可用: {exc}")
    return None, None

  try:
    dumps = find_volume_loss_dumps(run_dir)
  except Exception as exc:
    errors.append(f"体 dump 发现失败: {exc}")
    return None, None
  if not dumps:
    return None, None

  try:
    dump = read_loss_dump(dumps[0])
    field_power = dump.integrate_power_w()
  except Exception as exc:
    errors.append(f"体 dump 解析失败 {dumps[0].name}: {exc}")
    return None, None
  if field_power is None:
    errors.append(f"体 dump 无可积节数据 {dumps[0].name}")
    return None, None

  evidence: dict[str, Any] = {
    "dump_path": str(dumps[0]),
    "freq_hz": dump.freq_hz,
    "total_volume_m3": dump.total_volume_m3,
  }
  # 归档自带 power 属性自检（openEMS 自算 SAR 同值锚，实档 2.1e-8）
  try:
    for sar_path in sorted(run_dir.rglob("SAR_*.h5")):
      try:
        processed = read_loss_dump(sar_path)
      except Exception:
        continue
      if processed.kind != KIND_PROCESSED_SAR or processed.openems_power_w is None:
        continue
      attr = float(processed.openems_power_w)
      evidence["openems_sar_power_w"] = attr
      evidence["openems_sar_path"] = str(sar_path)
      if attr > 0.0:
        evidence["sar_power_selfcheck_rel"] = abs(field_power - attr) / attr
      break
  except Exception as exc: # 自检失败不影响主路径
    errors.append(f"SAR 自检属性读取失败: {exc}")

  return {"field_power_w": float(field_power)}, evidence


# 已知归档 JSON 的热键映射（块路径 → {输出键: 候选源键}；优先级 = 块序，
# **一个 JSON 只取第一个命中的块、不跨块混合**——icepak 归档里
# chain.thermal 的 t_hot_c=219.73 是注入场景、icepak.anchor.sim 的 rise 是真跑
# 锚，混在一起 ΔT 自相矛盾；#105 解析失败只记 errors）
_THERMAL_ARCHIVE_MAPPINGS: tuple[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]], ...] = (
  # icepak electrothermal 链路归档：真跑锚（rise_sim_k）优先于注入场景
  ("icepak.anchor.sim", (("rise_k", ("rise_sim_k",)),)),
  ("icepak.anchor.block_midplane_reference_c", (("rise_k", ("rise_k",)),)),
  ("chain.thermal", (
    ("t_max_c", ("t_hot_c",)),
    ("t_ambient_c", ("ambient_c",)),
    ("rise_k", ("rise_k",)),
  )),
  # COMSOL 微波炉 D3-2 收口归档：瞬态温升自洽锚
  ("transient_run", (
    ("t_max_c", ("t_max_c",)),
    ("heat_source_w", ("p_absorbed_w",)),
    ("rise_k", ("measured_delta_t_k",)),
  )),
)

#: 只透传给内核的热输入键（source_keys/archive_json 等溯源键留在本层）
_THERMAL_PASSTHROUGH = THERMAL_INPUT_KEYS


def _dig(data: Any, dotted: str) -> Any:
  """按 "a.b.c" 逐层取嵌套 dict；任一层缺失返回 None。"""
  cur = data
  for part in dotted.split("."):
    if not isinstance(cur, dict) or part not in cur:
      return None
    cur = cur[part]
  return cur


def _load_thermal(
  run_dir: Path,
  meta: dict[str, Any] | None,
  errors: list[str],
) -> dict[str, Any] | None:
  """热合理性入参发现（优先级：meta.thermal 块 > 已知归档 JSON 键）。

  meta.json thermal 块直接用（THERMAL_INPUT_KEYS 内的浮点键）；否则扫描
  run 目录 JSON，按 _THERMAL_ARCHIVE_MAPPINGS best-effort 映射。返回
  inputs dict（含 source_keys/archive_json 溯源键，透传内核前由调用方
  剥离）；无可识别热产物 → None。
  """
  inputs: dict[str, Any] = {}
  if isinstance(meta, dict) and isinstance(meta.get("thermal"), dict):
    for k, v in meta["thermal"].items():
      if k not in THERMAL_INPUT_KEYS or v is None:
        continue
      try:
        fv = float(v)
      except (TypeError, ValueError):
        errors.append(f"meta.json thermal.{k} 无法解析为 float")
        continue
      if np.isfinite(fv):
        inputs[str(k)] = fv
    if inputs:
      inputs["source_keys"] = sorted(k for k in inputs if k in THERMAL_INPUT_KEYS)
      inputs["archive_json"] = "meta.json"
      return inputs

  for json_path in sorted(run_dir.rglob("*.json")):
    data = _read_json(json_path)
    if not isinstance(data, dict):
      continue
    for block_path, key_map in _THERMAL_ARCHIVE_MAPPINGS:
      block = _dig(data, block_path)
      if not isinstance(block, dict):
        continue
      merged: dict[str, Any] = {}
      source: list[str] = []
      for out_key, candidates in key_map:
        for cand in candidates:
          if cand not in block:
            continue
          try:
            v = float(block[cand])
          except (TypeError, ValueError):
            errors.append(f"{json_path.name} {block_path}.{cand} 无法解析为 float")
            break
          if np.isfinite(v):
            merged[out_key] = v
            source.append(f"{block_path}.{cand}->{out_key}")
          break
      if merged: # 第一个命中的块即定口径，不跨块混合
        merged["source_keys"] = sorted(source)
        merged["archive_json"] = str(json_path)
        return merged
  return None


# ---------------------------------------------------------------------------
# 服务入口
# ---------------------------------------------------------------------------

def health_check_run(run_id: str, *, runs_dir: str | Path | None = None) -> dict[str, Any]:
  """对单次 run 做求解健康度体检（G11）。

  读取 runs/<run_id>/ 下能找到的产物（meta.json、trials/*.json 的 cost、
  Touchstone/sparams.csv S 参数、*.log 的 timestep、port_beta.csv 的
  β→εeff、dump_type=29 体 dump 的 ∫q dV、已知热归档 JSON），组装后调
  core.solve_health_check 确定性内核（九因子）。openEMS 单激励
  sparams.csv 是部分 S 矩阵：解析器同时给出已测掩码传给内核，互易性
  因子只校两向都独立已测的端口对，一对都没有 → UNKNOWN 不拦（修正
  "置零元素 vs 已测元素"假阳性）；Touchstone 全矩阵不带掩码，逐对全查。
  S 参数载入优先级=可解析的 sparams.csv（掩码载体）**优先于**
  Touchstone：单激励写入方落盘的 Touchstone 是零填充部分矩阵，按全
  矩阵逐对查互易必假阳性（c10 GT 探针实证，max|S12−S21|=|S21| 指纹，
  #314 同族）；仅 Touchstone 的 run（HFSS 类全矩阵）行为不变。csv
  存在但全部解析失败（异常/shape-reject）→ **不回退** Touchstone
  （掩码载体损坏=证据损坏，errors 留痕、S 参数因子走 UNKNOWN 低证据，
  round5 C-F1）；csv 不存在才回退（现行为不变）。

  返回 JSON 友好 dict；best-effort：run 目录不存在/全空 → ok=False +
  errors 说明（不抛）；verdict 语义同内核，本层硬失败时 verdict=suspect
  （不可证实健康）。门禁消费口径（#209 实际行为）：数据集物化的
  health_gate 按 verdict 细分——仅 verdict=="unhealthy"（真实 FAIL
  证据）禁入注册表；suspect（含"无可识别体检产物"的 suspect-by-absence
  与本层硬失败）不拦，verdict 仍记录进 manifest 供查询侧降权/过滤；
  ``ok`` 仅作报告字段，不作为门禁判据。
  """
  base = Path(runs_dir) if runs_dir is not None else Path("runs")
  run_dir = base / run_id
  errors: list[str] = []

  if not run_dir.is_dir():
    return {
      "ok": False,
      "run_id": run_id,
      "run_dir": str(run_dir),
      "verdict": "suspect",
      "factors": [],
      "errors": [f"run 目录不存在: {run_dir}"],
    }

  meta = _read_json(run_dir / "meta.json")

  # 逐类产物收集（每类独立 try/except，单类失败不传染）
  # S 参数载入优先级：sparams.csv（携带已测掩码）优先于 Touchstone——
  # 单激励写入方的 Touchstone 是零填充部分矩阵，全对查互易必假阳性
  # （c10 GT 探针实证）；仅 Touchstone（HFSS 类全矩阵）→ 掩码 None
  # 逐对全查，行为不变。csv 存在但全部解析失败 → _SparamsCsvCorrupt
  # 在此处被接住：不回退 Touchstone，S 参数因子走 None（round5 C-F1）。
  s_measured_mask: np.ndarray | None = None
  try:
    loaded_csv = _load_sparams_csv(run_dir, errors)
    if loaded_csv is not None:
      freq_hz, s_matrix, s_measured_mask = loaded_csv
    else:
      loaded = _load_touchstone(run_dir, errors)
      if loaded is not None:
        freq_hz, s_matrix = loaded
      else:
        freq_hz, s_matrix = None, None
  except Exception as exc: # 防御：产物发现本身不应炸体检
    freq_hz, s_matrix, s_measured_mask = None, None, None
    errors.append(f"S 参数发现失败: {exc}")

  try:
    costs = _load_costs(run_dir, errors) or None
  except Exception as exc:
    costs = None
    errors.append(f"cost 收集失败: {exc}")

  try:
    timesteps = _load_timesteps(run_dir, meta, errors) or None
  except Exception as exc:
    timesteps = None
    errors.append(f"timestep 收集失败: {exc}")

  try:
    eps_eff = _load_eps_eff(run_dir, meta, errors)
  except Exception as exc:
    eps_eff = None
    errors.append(f"εeff 收集失败: {exc}")

  mirror_symmetric = None
  if meta and meta.get("mirror_symmetric") is not None:
    mirror_symmetric = bool(meta.get("mirror_symmetric"))

  # G11 补强：dump_type=29 体 dump → 功率守恒入参；已知热归档 → 热合理性入参
  try:
    power_inputs, dump_evidence = _load_loss_power(run_dir, errors)
  except Exception as exc:
    power_inputs, dump_evidence = None, None
    errors.append(f"损耗 dump 收集失败: {exc}")
  if power_inputs is not None and freq_hz is not None and s_matrix is not None \
      and dump_evidence and dump_evidence.get("freq_hz") is not None:
    try:
      s_row = _interp_s_row(freq_hz, s_matrix, float(dump_evidence["freq_hz"]))
    except Exception as exc:
      s_row = None
      errors.append(f"S 行在 dump 频点插值失败: {exc}")
    if s_row is not None:
      power_inputs["s_row"] = s_row
      dump_evidence["s_row_at_dump_freq"] = [[c.real, c.imag] for c in s_row]

  try:
    thermal_found = _load_thermal(run_dir, meta, errors)
  except Exception as exc:
    thermal_found = None
    errors.append(f"热产物收集失败: {exc}")
  thermal_inputs = None
  if thermal_found:
    thermal_inputs = {k: v for k, v in thermal_found.items() if k in _THERMAL_PASSTHROUGH} or None

  # 全空：无任何可体检产物 → ok=False + errors（不调用内核误判 healthy）
  if (freq_hz is None and costs is None and timesteps is None and eps_eff is None
      and power_inputs is None and thermal_inputs is None):
    return {
      "ok": False,
      "run_id": run_id,
      "run_dir": str(run_dir),
      "verdict": "suspect",
      "factors": [],
      "errors": [*errors, "run 目录存在但无可识别体检产物"
            "（无 S 参数/cost/timestep/εeff/体 dump/热记录）"],
    }

  report = solve_health_check(
    freq_hz=freq_hz,
    s_matrix=s_matrix,
    s_measured_mask=s_measured_mask,
    costs=costs,
    timestep_values=timesteps,
    eps_eff_by_port=eps_eff,
    mirror_symmetric=mirror_symmetric,
    power_balance_inputs=power_inputs,
    thermal_inputs=thermal_inputs,
  )

  result: dict[str, Any] = {
    "ok": report["ok"],
    "run_id": run_id,
    "run_dir": str(run_dir),
    "verdict": report["verdict"],
    "factors": report["factors"],
  }
  if dump_evidence:
    result["loss_dump"] = dump_evidence
  if thermal_found:
    result["thermal_source"] = {
      "archive_json": thermal_found.get("archive_json"),
      "source_keys": thermal_found.get("source_keys"),
    }
  if errors:
    result["errors"] = errors
  if meta:
    summary = {
      key: meta[key]
      for key in ("run_id", "model", "adapter", "status", "study_name", "schema_version")
      if key in meta
    }
    if summary:
      result["meta"] = summary
  return result


# ---------------------------------------------------------------------------
# 开跑前 fake 成本非退化探针（#195 因子前置到战役开工之前）
# ---------------------------------------------------------------------------

def _normalize_objectives(objectives: Any) -> list[Any]:
  """dict/Objective 混合列表 → Objective 列表（JSON 进出，规则 4）。"""
  from rfauto.core.objectives import Objective

  out: list[Any] = []
  for o in objectives or []:
    out.append(o if isinstance(o, Objective) else Objective(**dict(o)))
  return out


def _fake_cost_at(
  model_type: str,
  params: dict[str, float],
  objectives: list[Any],
  *,
  n_ports: int,
  f0_ghz: float,
) -> float:
  """直构 FakeAdapter 求单点 cost（不复用 calibration_service._make_sampler：
  其硬编码 n_ports=3 且统一拼 "mm" 后缀，对 order/tap_frac 等无量纲参数
  不适用）。变量按裸数值字符串写入（physics_roles.parse_length 直收）。"""
  from rfauto.adapters.fake_adapter import FakeAdapter
  from rfauto.core.objectives import SpecEvaluator

  ad = FakeAdapter(
    model_type=model_type, n_ports=n_ports,
    freq_ghz=(f0_ghz * _PROBE_FREQ_SPAN[0], f0_ghz * _PROBE_FREQ_SPAN[1],
         _PROBE_FREQ_POINTS),
    f0_ghz=f0_ghz)
  ad.connect({})
  ad.set_variables({k: str(v) for k, v in params.items()})
  report = ad.solve("degeneracy_probe")
  if not getattr(report, "success", False):
    raise RuntimeError(f"fake 求解失败: {getattr(report, 'message', report)!r}")
  metrics = SpecEvaluator.compute_metrics(ad.get_sparams(), objectives)
  ad.close()
  return float(SpecEvaluator.evaluate_objectives(metrics, objectives))


def fake_cost_degeneracy_probe(
  model_type: str,
  param_bounds: dict[str, tuple[float, float]],
  objectives: list[Any],
  *,
  fixed_params: dict[str, float] | None = None,
  n_points: int = 8,
  seed: int = 42,
) -> dict[str, Any]:
  """开跑前 fake 成本非退化探针：#195 cost 退化因子前置。

  动机：#195 的 `solve_health_check(costs=...)` 只在 run 跑完后体检；对
  fake 不消费的调参（如 hairpin 的 gap_mm/tap_frac，fake 只反演
  arm_len→f0）整场战役 cost 恒为常数——两轮 47 样本的代价。本探针在
  开跑前用 LHS 小样本直构 FakeAdapter 出 cost，交 #195 因子判退化，并
  逐参数单轴扫描给出 insensitive_params（该参数在 fake 通道零敏感）。

  参数：
    model_type: FakeAdapter 模型名（须在 TEMPLATE_META 登记，n_ports /
      f0_ghz 从中取）。
    param_bounds: {参数名: (low, high)} 调参空间（LHS 全维采样 + 逐轴扫）。
    objectives: 配方 objectives（dict 或 Objective 列表）；cost 走
      SpecEvaluator.compute_metrics + evaluate_objectives 确定性内核。
    fixed_params: 不扫描的固定参数（如 w_mm/order），随每点一并写入。
    n_points: LHS 点数与单轴扫描点数（≥ COST_DEGENERATE_MIN_TRIALS=5，
      否则内核判 UNKNOWN，探针拒绝）。
    seed: LHS 种子（确定性）。

  返回（JSON 友好）：ok=探针是否跑通（非健康判定）；verdict/cost_factor 为
  内核 #195 判定（degenerate=True ⇔ cost 因子 FAIL）；param_sensitivity
  逐参数单轴 cost 方差；insensitive_params=方差 < COST_DEGENERATE_VAR_FLOOR
  的参数（fake 确定性下不消费的参数方差恰为 0）。best-effort（#105）：
  单点求解失败记 errors、不炸探针；有效点不足则 ok=False。

  注意：本探针只消费 FakeAdapter，不接线任何参数（gap→k / tap_frac→Q_e
  电气反演属队列 #3 独占）；#3 接线后 hairpin {gap_mm, tap_frac} 探针
  预期由 FAIL 翻 PASS，对应测试期望须同步改。
  """
  from rfauto.adapters.openems_templates import TEMPLATE_META
  from rfauto.optimization.sample_design import lhs_points

  errors: list[str] = []
  meta = TEMPLATE_META.get(model_type)
  if meta is None:
    return {"ok": False, "model_type": model_type,
        "errors": [f"model_type={model_type!r} 未在 TEMPLATE_META 登记"
              f"（可选 {sorted(TEMPLATE_META)}）"]}
  if not param_bounds:
    return {"ok": False, "model_type": model_type,
        "errors": ["param_bounds 为空，无从探针"]}
  try:
    bounds = {str(k): (float(v[0]), float(v[1]))
         for k, v in param_bounds.items()}
  except (TypeError, ValueError, IndexError) as exc:
    return {"ok": False, "model_type": model_type,
        "errors": [f"param_bounds 形状非法（须 {{名: (low, high)}}）: {exc}"]}
  for name, (lo, hi) in bounds.items():
    if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
      return {"ok": False, "model_type": model_type,
          "errors": [f"参数 {name} 的 bounds 须有限且 high>low，收到 {(lo, hi)!r}"]}
  n_points = int(n_points)
  if n_points < COST_DEGENERATE_MIN_TRIALS:
    return {"ok": False, "model_type": model_type,
        "errors": [f"n_points={n_points} < {COST_DEGENERATE_MIN_TRIALS}"
              "（#195 因子最小样本），探针无法判定退化"]}
  try:
    objs = _normalize_objectives(objectives)
  except Exception as exc:
    return {"ok": False, "model_type": model_type,
        "errors": [f"objectives 解析失败: {exc}"]}
  if not objs:
    return {"ok": False, "model_type": model_type,
        "errors": ["objectives 为空，无从评估 cost"]}

  n_ports = int(meta.get("n_ports", 2))
  f0_ghz = float(meta.get("f0_ghz", 2.4))
  fixed = {str(k): v for k, v in (fixed_params or {}).items()}

  def cost_at(point: dict[str, float]) -> float | None:
    try:
      return _fake_cost_at(model_type, {**fixed, **point}, objs,
                 n_ports=n_ports, f0_ghz=f0_ghz)
    except Exception as exc: # 单点失败不炸探针（#105）
      errors.append(f"点 {point} 求解失败: {exc}")
      return None

  # ① LHS 全维采样 → cost 序列 → #195 因子
  design = lhs_points(bounds, n_points, seed=seed)["points"]
  costs: list[float] = []
  for pt in design:
    c = cost_at(pt)
    if c is not None:
      costs.append(c)
  if len(costs) < COST_DEGENERATE_MIN_TRIALS:
    return {"ok": False, "model_type": model_type,
        "n_points": len(costs), "costs": costs,
        "errors": [*errors, f"有效 cost 点 {len(costs)} < "
              f"{COST_DEGENERATE_MIN_TRIALS}，无法判定退化"]}
  report = solve_health_check(costs=costs)
  cost_factor = next(
    (f for f in report["factors"] if f.get("factor") == FACTOR_COST),
    {"factor": FACTOR_COST, "status": "UNKNOWN", "detail": "因子缺失",
     "lesson_ref": LESSON_COST_DEGENERATE})

  # ② 逐参数单轴敏感性：其余参数取 bounds 中点，本轴 linspace 扫 n_points
  center = {name: 0.5 * (lo + hi) for name, (lo, hi) in bounds.items()}
  sensitivity: dict[str, dict[str, Any]] = {}
  insensitive: list[str] = []
  for name in sorted(bounds):
    lo, hi = bounds[name]
    axis_costs: list[float] = []
    for v in np.linspace(lo, hi, n_points):
      c = cost_at({**center, name: float(v)})
      if c is not None:
        axis_costs.append(c)
    if len(axis_costs) < 2:
      sensitivity[name] = {"n": len(axis_costs), "variance": None,
                 "cost_min": None, "cost_max": None,
                 "insensitive": None}
      continue
    arr = np.asarray(axis_costs, dtype=float)
    var = float(np.var(arr))
    flag = var < COST_DEGENERATE_VAR_FLOOR
    sensitivity[name] = {"n": int(arr.size), "variance": var,
               "cost_min": float(arr.min()),
               "cost_max": float(arr.max()),
               "insensitive": flag}
    if flag:
      insensitive.append(name)

  result: dict[str, Any] = {
    "ok": True,
    "model_type": model_type,
    "verdict": report["verdict"],
    "degenerate": cost_factor.get("status") == FAIL,
    "cost_factor": cost_factor,
    "factors": report["factors"],
    "n_points": len(costs),
    "costs": costs,
    "param_sensitivity": sensitivity,
    "insensitive_params": insensitive,
    "lesson_ref": LESSON_COST_DEGENERATE,
    "sampling": {
      "design": "lhs", "seed": int(seed), "n_ports": n_ports,
      "f0_ghz": f0_ghz,
      "freq_ghz": [f0_ghz * _PROBE_FREQ_SPAN[0],
             f0_ghz * _PROBE_FREQ_SPAN[1], _PROBE_FREQ_POINTS],
      "fixed_params": fixed,
      "bounds": {k: list(v) for k, v in bounds.items()},
    },
  }
  if errors:
    result["errors"] = errors
  return result
