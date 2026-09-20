"""DRC/DFM minimum gate.

DRC/DFM minimum gate:
- Reuse KiCad official DRC (IPC API)
- RF-specific rules (minimum line width/spacing/impedance tolerance)
- rfauto only collects results and generates reports
"""

from __future__ import annotations

import itertools
import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KICAD_PYTHON = r"E:\KiCad\bin\python.exe"


@dataclass
class DRCRule:
  """DRC rule."""
  name: str
  rule_type: str # "min_width" | "min_spacing" | "impedance_tolerance"
  value: float
  unit: str = "mm"
  description: str = ""

  def to_dict(self) -> dict[str, Any]:
    return {
      "name": self.name,
      "rule_type": self.rule_type,
      "value": self.value,
      "unit": self.unit,
      "description": self.description,
    }


@dataclass
class DRCViolation:
  """DRC violation."""
  rule_name: str
  severity: str # "error" | "warning"
  location: list[float] | None = None
  message: str = ""
  actual_value: float | None = None
  expected_value: float | None = None

  def to_dict(self) -> dict[str, Any]:
    return {
      "rule_name": self.rule_name,
      "severity": self.severity,
      "location": self.location,
      "message": self.message,
      "actual_value": self.actual_value,
      "expected_value": self.expected_value,
    }


@dataclass
class DRCResult:
  """DRC check result."""
  pcb_file: str
  passed: bool
  violations: list[DRCViolation]
  rules_checked: list[DRCRule]
  n_errors: int = 0
  n_warnings: int = 0

  def to_dict(self) -> dict[str, Any]:
    return {
      "pcb_file": self.pcb_file,
      "passed": self.passed,
      "n_errors": self.n_errors,
      "n_warnings": self.n_warnings,
      "violations": [v.to_dict() for v in self.violations],
      "rules_checked": [r.to_dict() for r in self.rules_checked],
    }


DEFAULT_RF_RULES = [
  DRCRule(name="min_trace_width", rule_type="min_width", value=0.1, unit="mm", description="RF min trace width"),
  DRCRule(name="min_spacing", rule_type="min_spacing", value=0.1, unit="mm", description="RF min spacing"),
  DRCRule(name="impedance_tolerance", rule_type="impedance_tolerance", value=5.0, unit="%", description="Impedance tolerance"),
]


def run_drc_kicad(
  pcb_path: str | Path,
  rules: list[DRCRule] | None = None,
  kicad_python: str | None = None,
) -> DRCResult:
  """Run KiCad DRC check via subprocess."""
  pcb_path = Path(pcb_path)
  python_exe = kicad_python or KICAD_PYTHON
  rules = rules or DEFAULT_RF_RULES

  if not pcb_path.exists():
    return DRCResult(
      pcb_file=str(pcb_path), passed=False,
      violations=[DRCViolation(rule_name="file_exists", severity="error", message=f"PCB file not found: {pcb_path}")],
      rules_checked=rules, n_errors=1,
    )

  script = _generate_drc_script(str(pcb_path), rules)

  try:
    result = subprocess.run(
      [python_exe, "-c", script],
      capture_output=True, text=True, timeout=60,
      env={"PATH": f"E:\\KiCad\\bin;E:\\KiCad\\bin\\DLLs;{__import__('os').environ.get('PATH', '')}"},
    )

    if result.returncode != 0:
      return DRCResult(
        pcb_file=str(pcb_path), passed=False,
        violations=[DRCViolation(rule_name="execution", severity="error", message=f"KiCad DRC failed: {result.stderr[:500]}")],
        rules_checked=rules, n_errors=1,
      )

    return _parse_drc_output(result.stdout, str(pcb_path), rules)

  except subprocess.TimeoutExpired:
    return DRCResult(pcb_file=str(pcb_path), passed=False, violations=[DRCViolation(rule_name="timeout", severity="error", message="DRC timeout")], rules_checked=rules, n_errors=1)
  except Exception as e:
    return DRCResult(pcb_file=str(pcb_path), passed=False, violations=[DRCViolation(rule_name="exception", severity="error", message=str(e))], rules_checked=rules, n_errors=1)


def _generate_drc_script(pcb_path: str, rules: list[DRCRule]) -> str:
  """Generate KiCad DRC script."""
  rules_json = json.dumps([r.to_dict() for r in rules], ensure_ascii=False)

  return '''
import sys
sys.path.insert(0, r"E:\\KiCad\\bin\\Lib\\site-packages")
import json
import pcbnew

rules_json = """RULES_JSON_PLACEHOLDER"""
rules = json.loads(rules_json)

board = pcbnew.LoadBoard(r"PCB_PATH_PLACEHOLDER")
violations = []

for track in board.GetTracks():
  if track.GetClass() == "PCB_TRACK":
    width = track.GetWidth() / 1e6
    for rule in rules:
      if rule["rule_type"] == "min_width" and width < rule["value"]:
        pos = track.GetStart()
        violations.append({
          "rule_name": rule["name"],
          "severity": "error",
          "location": [pos.x / 1e6, pos.y / 1e6],
          "message": f"Width {width:.3f}mm < min {rule['value']:.3f}mm",
          "actual_value": width,
          "expected_value": rule["value"],
        })

result = {
  "pcb_file": r"PCB_PATH_PLACEHOLDER",
  "passed": len([v for v in violations if v["severity"] == "error"]) == 0,
  "violations": violations,
  "rules_checked": rules,
  "n_errors": len([v for v in violations if v["severity"] == "error"]),
  "n_warnings": len([v for v in violations if v["severity"] == "warning"]),
}

print(json.dumps(result, ensure_ascii=False, indent=2))
'''.replace("RULES_JSON_PLACEHOLDER", rules_json).replace("PCB_PATH_PLACEHOLDER", pcb_path)


def _parse_drc_output(output: str, pcb_path: str, rules: list[DRCRule]) -> DRCResult:
  """Parse KiCad DRC output."""
  try:
    data = json.loads(output)
    violations = [DRCViolation(**v) for v in data.get("violations", [])]
    return DRCResult(
      pcb_file=pcb_path, passed=data.get("passed", False),
      violations=violations, rules_checked=rules,
      n_errors=data.get("n_errors", 0), n_warnings=data.get("n_warnings", 0),
    )
  except json.JSONDecodeError:
    return DRCResult(
      pcb_file=pcb_path, passed=False,
      violations=[DRCViolation(rule_name="parse_error", severity="error", message=f"Cannot parse DRC output: {output[:200]}")],
      rules_checked=rules, n_errors=1,
    )


def generate_drc_report(
  result: DRCResult,
  output_path: str | Path | None = None,
  rf_result: RFDRCResult | None = None,
) -> str:
  """Generate DRC report (Markdown)."""
  status = "PASS" if (result.passed and (rf_result.passed if rf_result is not None else True)) else "FAIL"
  total_errors = result.n_errors + (rf_result.n_errors if rf_result is not None else 0)
  total_warnings = result.n_warnings + (rf_result.n_warnings if rf_result is not None else 0)

  report = "# DRC/DFM Check Report\n\n"
  report += "## Summary\n\n"
  report += f"- PCB File: {result.pcb_file}\n"
  report += f"- Status: {status}\n"
  report += f"- Errors: {total_errors}\n"
  report += f"- Warnings: {total_warnings}\n\n"
  if rf_result is not None:
    report += f"- RF-DRC Errors: {rf_result.n_errors}\n"
    report += f"- RF-DRC Warnings: {rf_result.n_warnings}\n\n"

  report += "## Rules\n\n"
  report += "| Rule | Type | Threshold |\n"
  report += "|------|------|-----------|\n"
  for rule in result.rules_checked:
    report += f"| {rule.name} | {rule.rule_type} | {rule.value} {rule.unit} |\n"

  if result.violations:
    report += "\n## Violations\n\n"
    for v in result.violations:
      icon = "ERROR" if v.severity == "error" else "WARNING"
      report += f"- [{icon}] {v.rule_name}: {v.message}\n"
      if v.actual_value is not None:
        report += f" - Actual: {v.actual_value:.3f}\n"
        report += f" - Expected: {v.expected_value:.3f}\n"
  else:
    report += "\n## Result\n\nNo violations found.\n"

  if rf_result is not None:
    report += _render_rf_drc_section(rf_result)

  if output_path:
    Path(output_path).write_text(report, encoding="utf-8")

  return report

# ─── RF-DRC：高频 PCB 专项规则（B4 几何自动验证扩充） ────────────────────
#
# 本段为加性扩充：全部确定性纯函数（无 I/O、无子进程、无网络），输入为几何/
# 网络/频率/基板参数，输出沿用既有 DRCRule / DRCViolation / DRCResult 数据结构，
# 通过 generate_drc_report(..., rf_result=...) 并入既有汇总报告。
# 阈值集中在 RFDRCConfig（可配），每条规则的物理来源见其 docstring。

C_MM_GHZ = 299.792458 # mm·GHz（光速，f[GHz]×λ[mm]=此值）

RF_RULE_VIA_STITCH_PITCH = "via_stitch_pitch"
RF_RULE_GROUND_STITCH_INTEGRITY = "ground_stitch_integrity"
RF_RULE_TRACE_CLEARANCE = "trace_clearance"
RF_RULE_REFERENCE_PLANE_SLOT = "reference_plane_slot"


@dataclass
class Via:
  """RF-DRC 过孔（缝合孔 / 信号孔）。坐标单位 mm。"""

  x: float
  y: float
  net: str = "GND"
  diameter_mm: float = 0.3

  def to_dict(self) -> dict[str, Any]:
    return {"x": self.x, "y": self.y, "net": self.net, "diameter_mm": self.diameter_mm}


@dataclass
class Conductor:
  """RF-DRC 导体（走线/铜特征）：折线中心线 + 线宽。坐标单位 mm。"""

  net: str
  points: list[tuple[float, float]]
  layer: str = "F.Cu"
  width_mm: float = 0.2
  sensitive: bool = False

  def to_dict(self) -> dict[str, Any]:
    return {
      "net": self.net,
      "points": [[p[0], p[1]] for p in self.points],
      "layer": self.layer,
      "width_mm": self.width_mm,
      "sensitive": self.sensitive,
    }


@dataclass
class PlaneSlot:
  """参考平面上的矩形开槽（跨分割/回流路径断裂源）。坐标单位 mm。"""

  x_min: float
  y_min: float
  x_max: float
  y_max: float
  layer: str = "In1.Cu"
  plane_net: str = "GND"

  def to_dict(self) -> dict[str, Any]:
    return {
      "x_min": self.x_min,
      "y_min": self.y_min,
      "x_max": self.x_max,
      "y_max": self.y_max,
      "layer": self.layer,
      "plane_net": self.plane_net,
    }


@dataclass
class RFGeometry:
  """RF-DRC 几何输入（合成数据或 KiCad 提取几何均可）。"""

  vias: list[Via] = field(default_factory=list)
  conductors: list[Conductor] = field(default_factory=list)
  slots: list[PlaneSlot] = field(default_factory=list)

  def to_dict(self) -> dict[str, Any]:
    return {
      "vias": [v.to_dict() for v in self.vias],
      "conductors": [c.to_dict() for c in self.conductors],
      "slots": [s.to_dict() for s in self.slots],
    }


@dataclass
class RFDRCConfig:
  """RF-DRC 阈值集合（全部可配）。

  来源口径：
  - lambda_g：准 TEM 导波波长 λg = c / (f·√εeff)（Pozar, Microwave
   Engineering, 4e, §2.1/§3.8；微带准 TEM 近似）。
  - via_pitch_ratio：缝合孔最大间距 = ratio × λg；默认 0.1（λg/10 是高速/
   射频板过孔栅栏的工程经验上限，来源：Johnson & Graham, High-Speed
   Digital Design, §6；用于抑制平行板与缝隙模式）。
  - via_pitch_override_mm：显式绝对上限（mm），非 None 时覆盖 ratio 口径。
  - stitch_band_mm：地缝合覆盖带半宽——地孔到走线中心线垂距在该带内即视为
   为该处提供回流缝合（覆盖半长 c = √(band² − d²)）。
  - stitch_gap_max_mm：单侧允许的最长连续无缝合弧长（断缝判据）。
  - stitch_min_vias_per_side：走线每侧至少需有的缝合孔数（0 = 只查断缝）。
  - min_gap_to_ground_mm / min_gap_to_other_mm：RF 走线铜边缘到地/其他网络
   铜边缘的最小间距（IPC-2221B 电气间距规则在射频段的保守下限）。
  - check_reference_plane_slot：是否做参考平面开槽跨分割检查。
  """

  freq_ghz: float = 1.0
  eps_eff: float = 1.0
  via_pitch_ratio: float = 0.1
  via_pitch_override_mm: float | None = None
  stitch_band_mm: float = 2.0
  stitch_gap_max_mm: float = 2.0
  stitch_min_vias_per_side: int = 1
  min_gap_to_ground_mm: float = 0.2
  min_gap_to_other_mm: float = 0.2
  ground_nets: tuple[str, ...] = ("GND", "AGND", "GNDA", "VSS")
  check_reference_plane_slot: bool = True

  def to_dict(self) -> dict[str, Any]:
    return {
      "freq_ghz": self.freq_ghz,
      "eps_eff": self.eps_eff,
      "via_pitch_ratio": self.via_pitch_ratio,
      "via_pitch_override_mm": self.via_pitch_override_mm,
      "stitch_band_mm": self.stitch_band_mm,
      "stitch_gap_max_mm": self.stitch_gap_max_mm,
      "stitch_min_vias_per_side": self.stitch_min_vias_per_side,
      "min_gap_to_ground_mm": self.min_gap_to_ground_mm,
      "min_gap_to_other_mm": self.min_gap_to_other_mm,
      "ground_nets": list(self.ground_nets),
      "check_reference_plane_slot": self.check_reference_plane_slot,
    }


@dataclass
class RFDRCResult:
  """RF-DRC 检查结果（字段与 DRCResult 对齐，便于合并/上报）。"""

  violations: list[DRCViolation]
  rules_checked: list[DRCRule]
  lambda_g_mm: float | None = None
  passed: bool = True
  n_errors: int = 0
  n_warnings: int = 0

  def to_dict(self) -> dict[str, Any]:
    return {
      "passed": self.passed,
      "n_errors": self.n_errors,
      "n_warnings": self.n_warnings,
      "lambda_g_mm": self.lambda_g_mm,
      "violations": [v.to_dict() for v in self.violations],
      "rules_checked": [r.to_dict() for r in self.rules_checked],
    }


# ─── 输入校验 ─────────────────────────────────────────────────────────────────

def _finite(name: str, value: Any) -> float:
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    raise ValueError(f"{name} must be a number, got {value!r}")
  out = float(value)
  if not math.isfinite(out):
    raise ValueError(f"{name} must be finite, got {value!r}")
  return out


def _finite_positive(name: str, value: Any) -> float:
  out = _finite(name, value)
  if out <= 0:
    raise ValueError(f"{name} must be a positive finite number, got {value!r}")
  return out


def _finite_nonnegative(name: str, value: Any) -> float:
  out = _finite(name, value)
  if out < 0:
    raise ValueError(f"{name} must be a non-negative finite number, got {value!r}")
  return out


def _validate_points(name: str, points: Any) -> list[tuple[float, float]]:
  if not isinstance(points, (list, tuple)) or len(points) < 2:
    raise ValueError(f"{name}: need >= 2 points, got {points!r}")
  out: list[tuple[float, float]] = []
  for p in points:
    if not isinstance(p, (list, tuple)) or len(p) != 2:
      raise ValueError(f"{name}: each point must be (x, y), got {p!r}")
    out.append((_finite(f"{name} x", p[0]), _finite(f"{name} y", p[1])))
  return out


def _validate_via(via: Via) -> None:
  if not isinstance(via, Via):
    raise TypeError(f"via must be Via, got {type(via).__name__}")
  _finite("via x", via.x)
  _finite("via y", via.y)
  _finite_nonnegative("via diameter_mm", via.diameter_mm)


def _validate_conductor(conductor: Conductor) -> list[tuple[float, float]]:
  if not isinstance(conductor, Conductor):
    raise TypeError(f"conductor must be Conductor, got {type(conductor).__name__}")
  pts = _validate_points(f"conductor net={conductor.net!r}", conductor.points)
  _finite_nonnegative(f"conductor net={conductor.net!r} width_mm", conductor.width_mm)
  return pts


def _validate_slot(slot: PlaneSlot) -> tuple[float, float, float, float]:
  if not isinstance(slot, PlaneSlot):
    raise TypeError(f"slot must be PlaneSlot, got {type(slot).__name__}")
  x_min = _finite("slot x_min", slot.x_min)
  y_min = _finite("slot y_min", slot.y_min)
  x_max = _finite("slot x_max", slot.x_max)
  y_max = _finite("slot y_max", slot.y_max)
  if x_max <= x_min or y_max <= y_min:
    raise ValueError(f"slot must have positive area, got {slot!r}")
  return x_min, y_min, x_max, y_max


def _validate_rf_config(config: RFDRCConfig) -> None:
  if not isinstance(config, RFDRCConfig):
    raise TypeError(f"config must be RFDRCConfig, got {type(config).__name__}")
  guided_wavelength_mm(config.freq_ghz, config.eps_eff)
  _finite_positive("via_pitch_ratio", config.via_pitch_ratio)
  if config.via_pitch_override_mm is not None:
    _finite_positive("via_pitch_override_mm", config.via_pitch_override_mm)
  _finite_positive("stitch_band_mm", config.stitch_band_mm)
  _finite_nonnegative("stitch_gap_max_mm", config.stitch_gap_max_mm)
  _finite_nonnegative("min_gap_to_ground_mm", config.min_gap_to_ground_mm)
  _finite_nonnegative("min_gap_to_other_mm", config.min_gap_to_other_mm)
  if isinstance(config.stitch_min_vias_per_side, bool) or not isinstance(
    config.stitch_min_vias_per_side, int
  ) or config.stitch_min_vias_per_side < 0:
    raise ValueError(
      f"stitch_min_vias_per_side must be a non-negative int, got {config.stitch_min_vias_per_side!r}"
    )
  if not config.ground_nets:
    raise ValueError("ground_nets must not be empty")


# ─── 波长的确定性计算 ─────────────────────────────────────────────────────────

def guided_wavelength_mm(freq_ghz: float, eps_eff: float) -> float:
  """准 TEM 导波波长 λg = c / (f · √εeff)（mm；f 单位 GHz）。

  来源：Pozar, Microwave Engineering, 4e, §2.1 & §3.8（λg = λ0/√εeff）。
  非法输入（f ≤ 0、εeff < 1、非有限）抛 ValueError。
  """
  f = _finite_positive("freq_ghz", freq_ghz)
  er = _finite_positive("eps_eff", eps_eff)
  if er < 1.0:
    raise ValueError(f"eps_eff must be >= 1 (relative permittivity), got {eps_eff!r}")
  return C_MM_GHZ / (f * math.sqrt(er))


def max_via_pitch_mm(config: RFDRCConfig) -> float:
  """缝合孔最大允许间距（mm）：via_pitch_override_mm 优先，否则 ratio × λg。"""
  _validate_rf_config(config)
  if config.via_pitch_override_mm is not None:
    return float(config.via_pitch_override_mm)
  return config.via_pitch_ratio * guided_wavelength_mm(config.freq_ghz, config.eps_eff)


def _ground_vias(vias: list[Via], config: RFDRCConfig) -> list[Via]:
  names = {g.strip().upper() for g in config.ground_nets}
  out: list[Via] = []
  for via in vias:
    _validate_via(via)
    if via.net.strip().upper() in names:
      out.append(via)
  return out


# ─── 纯几何工具（确定性，无 I/O） ─────────────────────────────────────────────

def _orient(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> int:
  v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
  if v > 0:
    return 1
  if v < 0:
    return -1
  return 0


def _on_segment(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
  return (
    min(a[0], b[0]) - 1e-9 <= c[0] <= max(a[0], b[0]) + 1e-9
    and min(a[1], b[1]) - 1e-9 <= c[1] <= max(a[1], b[1]) + 1e-9
  )


def _segments_intersect(
  a: tuple[float, float],
  b: tuple[float, float],
  c: tuple[float, float],
  d: tuple[float, float],
) -> bool:
  o1, o2 = _orient(a, b, c), _orient(a, b, d)
  o3, o4 = _orient(c, d, a), _orient(c, d, b)
  if o1 != o2 and o3 != o4:
    return True
  if o1 == 0 and _on_segment(a, b, c):
    return True
  if o2 == 0 and _on_segment(a, b, d):
    return True
  if o3 == 0 and _on_segment(c, d, a):
    return True
  return o4 == 0 and _on_segment(c, d, b)


def _point_segment_nearest(
  p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> tuple[tuple[float, float], float]:
  dx, dy = b[0] - a[0], b[1] - a[1]
  seg2 = dx * dx + dy * dy
  if seg2 == 0.0:
    return (a[0], a[1]), math.hypot(p[0] - a[0], p[1] - a[1])
  t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / seg2
  t = min(1.0, max(0.0, t))
  nearest = (a[0] + t * dx, a[1] + t * dy)
  return nearest, math.hypot(p[0] - nearest[0], p[1] - nearest[1])


def _polyline_length(pts: list[tuple[float, float]]) -> float:
  return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in itertools.pairwise(pts))


def _polyline_point_at(pts: list[tuple[float, float]], s: float) -> tuple[float, float]:
  if s <= 0:
    return pts[0]
  acc = 0.0
  for a, b in itertools.pairwise(pts):
    seg = math.hypot(b[0] - a[0], b[1] - a[1])
    if acc + seg >= s:
      t = 0.0 if seg == 0.0 else (s - acc) / seg
      return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    acc += seg
  return pts[-1]


def _project_onto_path(
  p: tuple[float, float], pts: list[tuple[float, float]]
) -> tuple[float, float, tuple[float, float], tuple[float, float]]:
  """点 → 折线投影：返回 (垂距, 弧长 s, 折线上最近点, 该段单位切向)。"""
  best: tuple[float, float, tuple[float, float], tuple[float, float]] | None = None
  acc = 0.0
  for a, b in itertools.pairwise(pts):
    seg = math.hypot(b[0] - a[0], b[1] - a[1])
    nearest, dist = _point_segment_nearest(p, a, b)
    if seg > 0.0:
      tangent = ((b[0] - a[0]) / seg, (b[1] - a[1]) / seg)
      along = math.hypot(nearest[0] - a[0], nearest[1] - a[1])
    else:
      tangent = (1.0, 0.0)
      along = 0.0
    if best is None or dist < best[0] - 1e-12:
      best = (dist, acc + along, nearest, tangent)
    acc += seg
  if best is None:
    return 0.0, 0.0, pts[0], (1.0, 0.0)
  return best


def _polyline_min_distance(
  pts1: list[tuple[float, float]], pts2: list[tuple[float, float]]
) -> tuple[float, tuple[float, float]]:
  """两条折线的最小距离及取最小处的 pts1 上一点。"""
  best: tuple[float, tuple[float, float]] | None = None
  for a, b in itertools.pairwise(pts1):
    for c, d in itertools.pairwise(pts2):
      if _segments_intersect(a, b, c, d):
        return 0.0, a
      for p in (a, b):
        _, dist = _point_segment_nearest(p, c, d)
        if best is None or dist < best[0]:
          best = (dist, p)
      for p in (c, d):
        nearest, dist = _point_segment_nearest(p, a, b)
        if best is None or dist < best[0]:
          best = (dist, nearest)
  if best is None:
    return 0.0, pts1[0]
  return best


def _point_polyline_min_distance(
  p: tuple[float, float], pts: list[tuple[float, float]]
) -> tuple[float, tuple[float, float]]:
  best: tuple[float, tuple[float, float]] | None = None
  for a, b in itertools.pairwise(pts):
    nearest, dist = _point_segment_nearest(p, a, b)
    if best is None or dist < best[0]:
      best = (dist, nearest)
  if best is None:
    return 0.0, pts[0]
  return best


def _point_in_rect(
  p: tuple[float, float], rect: tuple[float, float, float, float]
) -> bool:
  return rect[0] <= p[0] <= rect[2] and rect[1] <= p[1] <= rect[3]


def _segment_crosses_rect(
  a: tuple[float, float], b: tuple[float, float], rect: tuple[float, float, float, float]
) -> bool:
  if _point_in_rect(a, rect) or _point_in_rect(b, rect):
    return True
  corners = [
    (rect[0], rect[1]),
    (rect[2], rect[1]),
    (rect[2], rect[3]),
    (rect[0], rect[3]),
  ]
  return any(_segments_intersect(a, b, corners[i], corners[(i + 1) % 4]) for i in range(4))


def _merge_intervals(
  intervals: list[tuple[float, float]], total: float
) -> list[list[float]]:
  if not intervals:
    return []
  ivs = sorted((max(0.0, lo), min(total, hi)) for lo, hi in intervals)
  merged: list[list[float]] = [[ivs[0][0], ivs[0][1]]]
  for lo, hi in ivs[1:]:
    if lo <= merged[-1][1] + 1e-12:
      merged[-1][1] = max(merged[-1][1], hi)
    else:
      merged.append([lo, hi])
  return merged


def _uncovered_gaps(
  intervals: list[tuple[float, float]], total: float
) -> list[tuple[float, float]]:
  merged = _merge_intervals(intervals, total)
  if not merged:
    return [(0.0, total)] if total > 0 else []
  gaps: list[tuple[float, float]] = []
  if merged[0][0] > 0:
    gaps.append((0.0, merged[0][0]))
  for i in range(1, len(merged)):
    if merged[i][0] > merged[i - 1][1]:
      gaps.append((merged[i - 1][1], merged[i][0]))
  if merged[-1][1] < total:
    gaps.append((merged[-1][1], total))
  return gaps


def _max_uncovered_gap(intervals: list[tuple[float, float]], total: float) -> float:
  return max((hi - lo for lo, hi in _uncovered_gaps(intervals, total)), default=0.0)


def _max_gap_midpoint(intervals: list[tuple[float, float]], total: float) -> float:
  gaps = _uncovered_gaps(intervals, total)
  if not gaps:
    return total / 2.0
  lo, hi = max(gaps, key=lambda g: g[1] - g[0])
  return (lo + hi) / 2.0


# ─── RF-DRC 规则 ──────────────────────────────────────────────────────────────

def check_via_stitch_pitch(
  vias: list[Via], config: RFDRCConfig | None = None
) -> list[DRCViolation]:
  """过孔缝合间距 vs λg 上限。

  地缝合孔按栅栏顺序（输入顺序）相邻间距不得超过 max_via_pitch_mm
  （默认 via_pitch_ratio × λg = λg/10）。判据：d > max_pitch 报 error；
  d == max_pitch 通过（边界含）。
  来源：λg = c/(f√εeff)（Pozar §2.1/§3.8）；λg/10 过孔栅栏经验上限
  （Johnson & Graham, High-Speed Digital Design, §6）。
  """
  config = config or RFDRCConfig()
  _validate_rf_config(config)
  max_pitch = max_via_pitch_mm(config)
  lambda_g = guided_wavelength_mm(config.freq_ghz, config.eps_eff)
  violations: list[DRCViolation] = []
  ground = _ground_vias(vias, config)
  for v1, v2 in itertools.pairwise(ground):
    d = math.hypot(v2.x - v1.x, v2.y - v1.y)
    if d > max_pitch:
      violations.append(
        DRCViolation(
          rule_name=RF_RULE_VIA_STITCH_PITCH,
          severity="error",
          location=[(v1.x + v2.x) / 2.0, (v1.y + v2.y) / 2.0],
          message=(
            f"ground via pitch {d:.3f}mm > max {max_pitch:.3f}mm "
            f"(lambda_g={lambda_g:.3f}mm)"
          ),
          actual_value=d,
          expected_value=max_pitch,
        )
      )
  return violations


def check_ground_stitch_integrity(
  conductors: list[Conductor], vias: list[Via], config: RFDRCConfig | None = None
) -> list[DRCViolation]:
  """地缝合完整性：敏感走线两侧缝合缺失或中断（断缝）。

  对每条 sensitive 走线折线按弧长参数化；每个地缝合孔投影到走线，垂距
  d ≤ stitch_band_mm 时覆盖区间 [s−c, s+c]，c = √(band²−d²)，按投影法向
  分 left/right 两侧。某侧孔数 < stitch_min_vias_per_side 判缺失（error）；
  每侧未覆盖弧长最大值 > stitch_gap_max_mm 判断缝（error）。
  来源：射频/高速回流缝合惯例（Johnson & Graham §6；RF 板地缝合栅栏）。
  """
  config = config or RFDRCConfig()
  _validate_rf_config(config)
  band = float(config.stitch_band_mm)
  ground = _ground_vias(vias, config)
  violations: list[DRCViolation] = []
  for conductor in conductors:
    if not conductor.sensitive:
      continue
    pts = _validate_conductor(conductor)
    total = _polyline_length(pts)
    if total <= 0.0:
      continue
    sides: dict[str, list[tuple[float, float]]] = {"left": [], "right": []}
    counts = {"left": 0, "right": 0}
    for via in ground:
      d_perp, s, nearest, tangent = _project_onto_path((via.x, via.y), pts)
      if d_perp > band + 1e-12:
        continue
      normal = (-tangent[1], tangent[0])
      signed = (via.x - nearest[0]) * normal[0] + (via.y - nearest[1]) * normal[1]
      side = "left" if signed >= 0.0 else "right"
      half = math.sqrt(max(0.0, band * band - d_perp * d_perp))
      sides[side].append((max(0.0, s - half), min(total, s + half)))
      counts[side] += 1
    mid = _polyline_point_at(pts, total / 2.0)
    for side in ("left", "right"):
      if counts[side] < config.stitch_min_vias_per_side:
        violations.append(
          DRCViolation(
            rule_name=RF_RULE_GROUND_STITCH_INTEGRITY,
            severity="error",
            location=[mid[0], mid[1]],
            message=(
              f"RF trace net={conductor.net!r} {side} side has {counts[side]} "
              f"ground stitching vias (< {config.stitch_min_vias_per_side})"
            ),
            actual_value=float(counts[side]),
            expected_value=float(config.stitch_min_vias_per_side),
          )
        )
        continue
      gap = _max_uncovered_gap(sides[side], total)
      if gap > config.stitch_gap_max_mm:
        loc = _polyline_point_at(pts, _max_gap_midpoint(sides[side], total))
        violations.append(
          DRCViolation(
            rule_name=RF_RULE_GROUND_STITCH_INTEGRITY,
            severity="error",
            location=[loc[0], loc[1]],
            message=(
              f"RF trace net={conductor.net!r} {side} ground-stitch break "
              f"{gap:.3f}mm > max {config.stitch_gap_max_mm:.3f}mm"
            ),
            actual_value=gap,
            expected_value=float(config.stitch_gap_max_mm),
          )
        )
  return violations


def _clearance_limit(net: str, config: RFDRCConfig, ground_names: set[str]) -> tuple[float, str]:
  if net.strip().upper() in ground_names:
    return float(config.min_gap_to_ground_mm), "ground"
  return float(config.min_gap_to_other_mm), "other-net"


def check_trace_clearance(
  conductors: list[Conductor], vias: list[Via], config: RFDRCConfig | None = None
) -> list[DRCViolation]:
  """敏感走线近地约束：RF 走线铜边缘到地/其他网络铜边缘的间距下限。

  边缘间距 = 中心线最小距离 − (走线半宽 + 对方半宽)。地网络
  （config.ground_nets）用 min_gap_to_ground_mm，其他网络用
  min_gap_to_other_mm；同网络铜特征跳过。gap < limit 报 error。
  来源：IPC-2221B 电气间距规则在射频段的保守下限。
  """
  config = config or RFDRCConfig()
  _validate_rf_config(config)
  ground_names = {g.strip().upper() for g in config.ground_nets}
  ground_vias = _ground_vias(vias, config)
  other_vias: list[Via] = []
  for via in vias:
    _validate_via(via)
    if via.net.strip().upper() not in ground_names:
      other_vias.append(via)
  violations: list[DRCViolation] = []
  for trace in conductors:
    if not trace.sensitive:
      continue
    trace_pts = _validate_conductor(trace)
    trace_half = max(0.0, float(trace.width_mm)) / 2.0
    for other in conductors:
      if other is trace or other.net == trace.net:
        continue
      other_pts = _validate_conductor(other)
      dist, point = _polyline_min_distance(trace_pts, other_pts)
      gap = dist - trace_half - max(0.0, float(other.width_mm)) / 2.0
      limit, kind = _clearance_limit(other.net, config, ground_names)
      if gap < limit:
        violations.append(
          DRCViolation(
            rule_name=RF_RULE_TRACE_CLEARANCE,
            severity="error",
            location=[point[0], point[1]],
            message=(
              f"RF trace net={trace.net!r} to {kind} net={other.net!r} "
              f"clearance {gap:.3f}mm < min {limit:.3f}mm"
            ),
            actual_value=gap,
            expected_value=limit,
          )
        )
    for via in [*ground_vias, *other_vias]:
      dist, point = _point_polyline_min_distance((via.x, via.y), trace_pts)
      gap = dist - trace_half - max(0.0, float(via.diameter_mm)) / 2.0
      limit, kind = _clearance_limit(via.net, config, ground_names)
      if gap < limit:
        violations.append(
          DRCViolation(
            rule_name=RF_RULE_TRACE_CLEARANCE,
            severity="error",
            location=[point[0], point[1]],
            message=(
              f"RF trace net={trace.net!r} to {kind} via net={via.net!r} "
              f"clearance {gap:.3f}mm < min {limit:.3f}mm"
            ),
            actual_value=gap,
            expected_value=limit,
          )
        )
  return violations


def check_reference_plane_slot(
  conductors: list[Conductor], slots: list[PlaneSlot], config: RFDRCConfig | None = None
) -> list[DRCViolation]:
  """参考平面开槽跨分割检查：RF 走线不得跨越参考平面开槽。

  走线中心线任一折线段与槽矩形相交（含端点落入槽内）判 error——回流路径
  被切断导致阻抗突变与辐射。location 取相交线段中点（确定性）。
  来源：射频/高速回流路径连续性要求（Pozar §3.8；Johnson & Graham §6 回流面）。
  """
  config = config or RFDRCConfig()
  _validate_rf_config(config)
  violations: list[DRCViolation] = []
  for trace in conductors:
    if not trace.sensitive:
      continue
    trace_pts = _validate_conductor(trace)
    for slot in slots:
      rect = _validate_slot(slot)
      hit: tuple[float, float] | None = None
      for a, b in itertools.pairwise(trace_pts):
        if _segment_crosses_rect(a, b, rect):
          hit = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
          break
      if hit is None:
        continue
      violations.append(
        DRCViolation(
          rule_name=RF_RULE_REFERENCE_PLANE_SLOT,
          severity="error",
          location=[hit[0], hit[1]],
          message=(
            f"RF trace net={trace.net!r} crosses reference-plane slot "
            f"[{rect[0]:g},{rect[1]:g}]-[{rect[2]:g},{rect[3]:g}] on {slot.layer}"
          ),
          actual_value=1.0,
          expected_value=0.0,
        )
      )
  return violations


def rf_drc_rules(config: RFDRCConfig) -> list[DRCRule]:
  """构建本轮 RF-DRC 规则清单（阈值取自 config）。"""
  _validate_rf_config(config)
  return [
    DRCRule(
      name="rf_via_stitch_pitch",
      rule_type=RF_RULE_VIA_STITCH_PITCH,
      value=max_via_pitch_mm(config),
      unit="mm",
      description="max ground via-fence pitch (ratio x lambda_g)",
    ),
    DRCRule(
      name="rf_ground_stitch_gap",
      rule_type=RF_RULE_GROUND_STITCH_INTEGRITY,
      value=float(config.stitch_gap_max_mm),
      unit="mm",
      description="max continuous ground-stitch gap per trace side",
    ),
    DRCRule(
      name="rf_trace_clearance_ground",
      rule_type=RF_RULE_TRACE_CLEARANCE,
      value=float(config.min_gap_to_ground_mm),
      unit="mm",
      description="min RF trace edge clearance to ground copper",
    ),
    DRCRule(
      name="rf_trace_clearance_other",
      rule_type=RF_RULE_TRACE_CLEARANCE,
      value=float(config.min_gap_to_other_mm),
      unit="mm",
      description="min RF trace edge clearance to other nets",
    ),
    DRCRule(
      name="rf_reference_plane_slot",
      rule_type=RF_RULE_REFERENCE_PLANE_SLOT,
      value=0.0,
      unit="count",
      description="RF trace crossings over reference-plane slots",
    ),
  ]


def run_rf_drc(geometry: RFGeometry, config: RFDRCConfig | None = None) -> RFDRCResult:
  """运行全部 RF-DRC 规则并汇总（纯函数，无 I/O/子进程/网络）。"""
  if not isinstance(geometry, RFGeometry):
    raise TypeError(f"geometry must be RFGeometry, got {type(geometry).__name__}")
  config = config or RFDRCConfig()
  _validate_rf_config(config)
  violations: list[DRCViolation] = []
  violations += check_via_stitch_pitch(geometry.vias, config)
  violations += check_ground_stitch_integrity(geometry.conductors, geometry.vias, config)
  violations += check_trace_clearance(geometry.conductors, geometry.vias, config)
  if config.check_reference_plane_slot:
    violations += check_reference_plane_slot(geometry.conductors, geometry.slots, config)
  n_errors = sum(1 for v in violations if v.severity == "error")
  n_warnings = sum(1 for v in violations if v.severity == "warning")
  return RFDRCResult(
    violations=violations,
    rules_checked=rf_drc_rules(config),
    lambda_g_mm=guided_wavelength_mm(config.freq_ghz, config.eps_eff),
    passed=n_errors == 0,
    n_errors=n_errors,
    n_warnings=n_warnings,
  )


def merge_drc_results(base: DRCResult, rf: RFDRCResult) -> DRCResult:
  """把常规 DRC 与 RF-DRC 合并为单一 DRCResult（加性，不改既有结构）。"""
  n_errors = base.n_errors + rf.n_errors
  n_warnings = base.n_warnings + rf.n_warnings
  return DRCResult(
    pcb_file=base.pcb_file,
    passed=n_errors == 0,
    violations=[*base.violations, *rf.violations],
    rules_checked=[*base.rules_checked, *rf.rules_checked],
    n_errors=n_errors,
    n_warnings=n_warnings,
  )


def _render_rf_drc_section(rf_result: RFDRCResult) -> str:
  status = "PASS" if rf_result.passed else "FAIL"
  out = "\n## RF-DRC\n\n"
  out += f"- Status: {status}\n"
  out += f"- Errors: {rf_result.n_errors}\n"
  out += f"- Warnings: {rf_result.n_warnings}\n"
  if rf_result.lambda_g_mm is not None:
    out += f"- Guided wavelength (lambda_g): {rf_result.lambda_g_mm:.3f} mm\n"
  out += "\n### RF Rules\n\n"
  out += "| Rule | Type | Threshold |\n"
  out += "|------|------|-----------|\n"
  for rule in rf_result.rules_checked:
    out += f"| {rule.name} | {rule.rule_type} | {rule.value:g} {rule.unit} |\n"
  out += "\n### RF Violations\n\n"
  if rf_result.violations:
    for v in rf_result.violations:
      icon = "ERROR" if v.severity == "error" else "WARNING"
      loc = "" if v.location is None else f" @ ({v.location[0]:.3f}, {v.location[1]:.3f})"
      out += f"- [{icon}] {v.rule_name}{loc}: {v.message}\n"
  else:
    out += "None.\n"
  return out
