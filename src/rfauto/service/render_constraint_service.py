"""R4（df7+ 第三层）：渲染前声明式几何约束 service 面（JSON 进出，规则 4）。

薄壳职责：把参数化输入（BASE 网格、耦合缝、NEAR=base/4、参数 bounds、
网格线位等）组装为 core/render_constraints.py 的 Rule 列表 → solve_rules
一次求解 → dict 判定（ok/status/冲突规则全集/冲突分组/逐规则报告/witness）。
本模块**不 import z3**（z3 触达面收在 core 的 _import_z3 单点，缺装降级在
core 内完成）；不接 CLI/MCP（五钉清单不扩张，接线留后续批次登记）。

被形式化的既有 if 链守卫（零改动，本服务是并行增强件）：
- c3_gap_mesh_guard（openems_templates.py:6359，#266：NEAR ≤ 最小耦合缝/3，
  违反抛 ValueError 只报这一条）→ gap_cells_rule；
- #152 最小间距去重（渲染脚本内 1e-6 m 阈值）与 #349 全轴 ≥10µm 提法
  → min_spacing_rule（mesh_lines_mm 线位输入）；
- #311 缝内内部线 ≥1 → gap_internal_line_rule（存在性析取：自动细分或
  缝中线，中线到缝缘须满足 #152）；
- recipe/EMSolverConfig 参数可取域 → bounds_rule（如 mesh_resolution_mm
  ∈ [0.4, 0.5] 工程缺省档；0.45≈λ_sub/100 收敛档见 calibration_service）。

单位口径：约束空间统一毫米（mm）；#152 原阈值 1e-6 m 折算 1e-3 mm 作
min_line_spacing_mm 缺省。数值只在确定性内核（规则 7）：全部数字出自
z3 求解（witness）或调用方输入，LLM/agent 只消费报告。

判据预声明：runs/df7_r4z3/criteria.md（C1–C7）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.core.render_constraints import (
    DEFAULT_MAX_CONFLICT_GROUPS,
    ConstraintVerdict,
    Rule,
    bounds_rule,
    derived_ratio_rule,
    gap_cells_rule,
    gap_internal_line_rule,
    min_spacing_rule,
    solve_rules,
)

MESH_VAR = "mesh_resolution_mm"
"""BASE 网格（毫米）在约束符号空间的规范名（NEAR 派生与 bounds 的公共键）。"""

NEAR_VAR = "near_mm"
"""近场加密区 NEAR（毫米）的规范名（NEAR = base/4 官方口径的派生变量）。"""

DEFAULT_NEAR_RATIO = 4.0
"""NEAR = BASE/near_ratio 官方缺省口径（openems_templates 同款缺省 4）。"""

DEFAULT_GAP_CELLS = 3
"""缝内最少格数（#266/_C3_GAP_CELLS_MIN 同款：NEAR ≤ 最小缝/3）。"""

DEFAULT_MIN_LINE_SPACING_MM = 1e-3
"""#152 最小间距阈值（1e-6 m 折毫米）；#349 全轴 10µm 档由调用方显式传 1e-2。"""


def evaluate_render_constraints(config: dict[str, Any]) -> dict[str, Any]:
    """渲染前一次求解：config（JSON 可载）→ 判定 dict（JSON 可存）。

    config 键（全部可选，缺项即不组装对应规则）：
      mesh_resolution_mm : float | {"low": .., "high": ..}
          BASE 网格毫米值（float=钉值 bounds）或可取域 bounds；
      near_ratio         : float，缺省 4（NEAR = base/ratio 定义规则）；
      gaps_mm            : [float, ...]（取最小值进守卫）或 min_gap_mm: float
          耦合缝族（c3）；同时组装 gap_cells_rule（#266）与
          gap_internal_line_rule（#311 存在性）；
      gap_cells_min      : int，缺省 3；
      min_line_spacing_mm: float，缺省 1e-3（#152 折毫米）；
      mesh_lines_mm      : {"<axis>": [float, ...], ...} 已规划网格线位，
          逐轴组装 min_spacing_rule（#152/#349）；
      param_bounds       : {"<var>": {"low": .., "high": ..}, ...} 其他参数
          bounds（线性 Real，规则 7：不产生物理数字，只校验可取域）；
      max_conflict_groups: int，缺省 8（独立冲突组检出上限）。

    返回 dict 键：ok/status/conflict_rule_ids/conflict_groups/rules/
    witness/near_mm/reason/solver。z3 缺装时 ok=False/status="unavailable"
    不崩；config 形状非法 raise ValueError（程序性错误，如实抛出）。
    """
    if not isinstance(config, dict):
        raise ValueError(f"config 须为 dict，得 {type(config).__name__}")
    rules, meta = _assemble_rules(config)
    max_groups = int(config.get("max_conflict_groups", DEFAULT_MAX_CONFLICT_GROUPS))
    verdict = solve_rules(rules, max_conflict_groups=max_groups)
    out = _verdict_to_dict(verdict)
    out["near_mm"] = _witness_near(out["witness"])
    out["assembled"] = meta
    return out


def evaluate_render_constraints_from_file(path: str | Path) -> dict[str, Any]:
    """约束配置文件（JSON/YAML）→ :func:`evaluate_render_constraints`。

    后缀定渠道：.yaml/.yml 走 yaml.safe_load，其余走 json.loads（#90：
    配置解析在服务层，CLI/MCP 是传路径的薄壳）。文件缺失/读取失败/解析
    失败/顶层非对象一律 raise ValueError（程序性错误如实抛出，与主函数
    同口径；z3 缺装降级仍在 core 内完成，不在此层）。
    """
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"约束配置文件不存在: {p}")
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"约束配置文件读取失败: {exc}") from exc
    if p.suffix.lower() in (".yaml", ".yml"):
        import yaml

        try:
            config = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"约束配置 YAML 解析失败: {exc}") from exc
    else:
        try:
            config = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"约束配置 JSON 解析失败: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError(f"约束配置顶层须为对象，得 {type(config).__name__}")
    return evaluate_render_constraints(config)


# ---------------------------------------------------------------------------
# 规则组装（确定性顺序；config 键取值校验就地 raise ValueError）
# ---------------------------------------------------------------------------

def _assemble_rules(config: dict[str, Any]) -> tuple[list[Rule], dict[str, Any]]:
    rules: list[Rule] = []
    meta: dict[str, Any] = {"rules": []}
    min_spacing = float(config.get("min_line_spacing_mm",
                                   DEFAULT_MIN_LINE_SPACING_MM))
    if min_spacing <= 0.0:
        raise ValueError(f"min_line_spacing_mm 须 >0，得 {min_spacing}")

    near_ratio = float(config.get("near_ratio", DEFAULT_NEAR_RATIO))
    if near_ratio <= 0.0:
        raise ValueError(f"near_ratio 须 >0，得 {near_ratio}")
    has_mesh_var = "mesh_resolution_mm" in config
    if has_mesh_var:
        rules.append(_mesh_bounds_rule(config["mesh_resolution_mm"]))
        meta["rules"].append("bounds:mesh_resolution_mm")
        rules.append(derived_ratio_rule(
            "near_definition",
            f"NEAR = BASE/{near_ratio:g}（官方近场加密口径，派生定义）",
            NEAR_VAR, MESH_VAR, near_ratio))
        meta["rules"].append("near_definition")

    gap = _min_gap_mm(config)
    if gap is not None:
        cells = int(config.get("gap_cells_min", DEFAULT_GAP_CELLS))
        rules.append(gap_cells_rule(
            "gap_cells_guard",
            f"最小耦合缝 {gap:.4g}mm ≥ {cells}×NEAR（#266，缝内至少 "
            f"{cells} 格；既有 c3_gap_mesh_guard 同式）",
            min_gap=gap, near_var=NEAR_VAR, cells=cells))
        meta["rules"].append("gap_cells_guard")
        rules.append(gap_internal_line_rule(
            "gap_internal_line",
            f"缝 {gap:.4g}mm 内部线 ≥1（#311：gap ≥ NEAR 自动细分，或缝中线 "
            f"且 gap/2 ≥ 最小间距）",
            gap=gap, near_var=NEAR_VAR, min_spacing=min_spacing))
        meta["rules"].append("gap_internal_line")

    mesh_lines = config.get("mesh_lines_mm") or {}
    if not isinstance(mesh_lines, dict):
        # P2：非 dict（list/str 等）此前裸抛 AttributeError 击穿 CLI 的
        # (OSError, ValueError) 捕获——统一 ValueError 信封（#122 形状
        # 违约显式报错，与 param_bounds 同口径）。
        raise ValueError(
            f"mesh_lines_mm 须为 {{axis: 线位列表}} 对象，得到 "
            f"{type(mesh_lines).__name__}")
    for axis, positions in sorted(mesh_lines.items()):
        if not isinstance(positions, (list, tuple)):
            raise ValueError(f"mesh_lines_mm[{axis!r}] 须为线位列表")
        rules.append(min_spacing_rule(
            f"min_spacing:{axis}",
            f"{axis} 轴网格线相邻间距 ≥ {min_spacing:g}mm（#152 最小间距，"
            f"近重合线塌 CFL 时间步；#349 同族）",
            positions, min_spacing=min_spacing))
        meta["rules"].append(f"min_spacing:{axis}")

    for var in sorted(config.get("param_bounds") or {}):
        lo_hi = (config.get("param_bounds") or {})[var]
        if not isinstance(lo_hi, dict):
            raise ValueError(f"param_bounds[{var!r}] 须为 {{low, high}} dict")
        rules.append(bounds_rule(
            f"bounds:{var}", f"参数 {var} ∈ 声明可取域（recipe/配置 bounds）",
            var, low=lo_hi.get("low"), high=lo_hi.get("high")))
        meta["rules"].append(f"bounds:{var}")
    return rules, meta


def _mesh_bounds_rule(value: Any) -> Rule:
    """mesh_resolution_mm 输入 → bounds 规则（float=钉值，dict=可取域）。"""
    if isinstance(value, dict):
        low, high = value.get("low"), value.get("high")
        if low is None and high is None:
            raise ValueError("mesh_resolution_mm bounds low/high 至少给一侧")
        desc = (f"BASE 网格 ∈ [{low}, {high}] mm（recipe/EMSolverConfig "
                f"可取域，工程缺省档 0.4/0.45/0.5）")
        return bounds_rule("bounds:mesh_resolution_mm", desc, MESH_VAR,
                           low=low, high=high)
    if isinstance(value, (int, float)) and value > 0.0:
        return bounds_rule("bounds:mesh_resolution_mm",
                           f"BASE 网格钉值 {value:g} mm", MESH_VAR,
                           low=float(value), high=float(value))
    raise ValueError(f"mesh_resolution_mm 须为正数或 {{low, high}}，得 {value!r}")


def _min_gap_mm(config: dict[str, Any]) -> float | None:
    """耦合缝输入归一：gaps_mm 列表取最小（c3 守卫口径），min_gap_mm 直取。"""
    if "min_gap_mm" in config and "gaps_mm" in config:
        raise ValueError("min_gap_mm 与 gaps_mm 二选一（后者取最小）")
    gaps = config.get("gaps_mm")
    if gaps is not None:
        if not isinstance(gaps, (list, tuple)) or not gaps:
            raise ValueError("gaps_mm 须为非空缝宽列表")
        vals = [float(g) for g in gaps]
        if any(g <= 0.0 for g in vals):
            raise ValueError(f"gaps_mm 须全 >0，得 {vals}")
        return min(vals)
    single = config.get("min_gap_mm")
    if single is not None:
        gap = float(single)
        if gap <= 0.0:
            raise ValueError(f"min_gap_mm 须 >0，得 {gap}")
        return gap
    return None


def _witness_near(witness: dict[str, float]) -> float | None:
    return witness.get(NEAR_VAR)


def _verdict_to_dict(verdict: ConstraintVerdict) -> dict[str, Any]:
    """ConstraintVerdict → JSON 友好 dict（frozen dataclass 字段直映射）。"""
    return {
        "ok": verdict.ok,
        "status": verdict.status,
        "conflict_rule_ids": list(verdict.conflict_rule_ids),
        "conflict_groups": [list(g) for g in verdict.conflict_groups],
        "rules": [{"rule_id": r.rule_id, "description": r.description,
                   "in_conflict": r.in_conflict} for r in verdict.rules],
        "witness": dict(verdict.witness),
        "reason": verdict.reason,
        "solver": verdict.solver,
    }
