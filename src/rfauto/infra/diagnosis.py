"""知识库诊断引擎（P6）—— 基于 rules.yaml 的仿真结果诊断。

激活 knowledge/rules.yaml 中的规则，对仿真结果进行自动诊断：
- 初值估计规则（initial_value）：给出参数初值建议
- 诊断规则（diagnosis）：分析异常指标，给出修复建议
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# 默认规则文件路径
_DEFAULT_RULES_PATH = Path(__file__).parent.parent.parent.parent / "knowledge" / "rules.yaml"


class DiagnosisEngine:
    """知识库诊断引擎。

    加载 rules.yaml 中的规则，对仿真结果进行自动诊断。
    """

    def __init__(self, rules_path: str | Path | None = None) -> None:
        self.rules_path = Path(rules_path) if rules_path else _DEFAULT_RULES_PATH
        self.rules: list[dict[str, Any]] = []
        self._load_rules()

    def _load_rules(self) -> None:
        """加载规则文件。"""
        if not self.rules_path.exists():
            logger.warning("规则文件不存在: %s", self.rules_path)
            return

        try:
            with open(self.rules_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self.rules = data.get("rules", [])
            logger.info("加载 %d 条诊断规则", len(self.rules))
        except Exception as e:
            logger.error("加载规则文件失败: %s", e)

    def diagnose(
        self,
        metrics: dict[str, float],
        model_name: str = "all",
        objectives: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """对仿真结果进行诊断。"""
        diagnoses: list[dict[str, Any]] = []
        suggestions: list[str] = []
        initial_values: dict[str, Any] = {}

        for rule in self.rules:
            applicable = rule.get("applicable_models", [])
            if "all" not in applicable and model_name not in applicable:
                continue

            category = rule.get("category", "")

            if category == "diagnosis":
                diagnosis = self._check_diagnosis_rule(rule, metrics, objectives)
                if diagnosis:
                    diagnoses.append(diagnosis)
                    suggestions.append(diagnosis.get("hint", ""))

            elif category == "initial_value":
                initial_value = self._estimate_initial_value(rule, metrics)
                if initial_value:
                    initial_values.update(initial_value)

        return {
            "ok": True,
            "diagnoses": diagnoses,
            "suggestions": [s for s in suggestions if s],
            "initial_values": initial_values,
            "rules_applied": len(diagnoses) + len(initial_values),
        }

    def diagnose_divergence(self, config_a: Any, config_b: Any, **kwargs: Any) -> dict[str, Any]:
        """跨引擎分歧诊断（薄委托，见模块级 diagnose_divergence）。"""
        return diagnose_divergence(config_a, config_b, **kwargs)

    def _check_diagnosis_rule(
        self,
        rule: dict[str, Any],
        metrics: dict[str, float],
        objectives: list[dict[str, Any]] | None,
    ) -> dict[str, Any] | None:
        """检查诊断规则是否触发。"""
        rule_id = rule.get("id", "")
        description = rule.get("description", "")
        hint = rule.get("hint", "")

        if rule_id == "R002":
            # 指标缺失时跳过而非按默认值判断（C5 修复：原先默认 0 > -10，
            # objectives 不含 s11_db 的配方会被误报 R002）
            s11 = metrics.get("s11_db_max_in_band")
            if s11 is not None and s11 > -10:
                return {
                    "rule_id": rule_id,
                    "description": description,
                    "hint": hint,
                    "severity": "warning",
                    "metric": "s11_db_max_in_band",
                    "value": s11,
                    "threshold": -10,
                }

        if rule_id == "R003":
            s21 = metrics.get("s21_db_mean_in_band")
            if s21 is not None and s21 < -6:
                return {
                    "rule_id": rule_id,
                    "description": description,
                    "hint": hint,
                    "severity": "warning",
                    "metric": "s21_db_mean_in_band",
                    "value": s21,
                    "threshold": -6,
                }

        if rule_id == "R004":
            passivity = metrics.get("passivity_ok", True)
            if not passivity:
                return {
                    "rule_id": rule_id,
                    "description": description,
                    "hint": hint,
                    "severity": "error",
                    "metric": "passivity_ok",
                    "value": False,
                }

        return None

    def _estimate_initial_value(
        self,
        rule: dict[str, Any],
        metrics: dict[str, float],
    ) -> dict[str, Any] | None:
        """根据规则估计参数初值。"""
        rule_id = rule.get("id", "")

        if rule_id == "R001":
            return {
                "arm_len_mm": {
                    "formula": rule.get("formula", ""),
                    "example": rule.get("example", ""),
                }
            }

        return None


_engine: DiagnosisEngine | None = None


def get_diagnosis_engine() -> DiagnosisEngine:
    """获取诊断引擎单例。"""
    global _engine
    if _engine is None:
        _engine = DiagnosisEngine()
    return _engine


def diagnose_results(
    metrics: dict[str, float],
    model_name: str = "all",
    objectives: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """便捷函数：对仿真结果进行诊断。"""
    engine = get_diagnosis_engine()
    return engine.diagnose(metrics, model_name, objectives)


# ---------------------------------------------------------------------------
# 跨引擎分歧诊断
# ---------------------------------------------------------------------------
# 与既有 rules 诊断（R001-R009）正交：本段不读 rules.yaml、不调用任何 LLM。
# 输入=两引擎配置与结果，输出=配置逐项 diff + 教训核对表 + 有序根因清单。
# LLM 只能消费本输出做解释，全部判定在确定性规则内。

CONFIG_DIMENSIONS: tuple[str, ...] = ("mesh", "port", "material", "boundary")

LESSON_SAME_NAME_INVERSE = "#154（同名参数跨适配器语义相反）"
LESSON_WAVE_PORT_SIZE = "#191（波端口尺寸不符官方口径）"
LESSON_VERIFY_MODEL_FIRST = "先验模型/先对照官方例"

CAUSE_MESH_LEVEL = "mesh_level_mismatch"
CAUSE_PORT_OFFICIAL = "port_size_official_deviation"
CAUSE_PORT_MISMATCH = "port_size_mismatch"
CAUSE_PARAM_INVERSE = "param_semantics_inverted"
CAUSE_MATERIAL = "material_mismatch"
CAUSE_BOUNDARY = "boundary_mismatch"
CAUSE_RESULT_TOLERANCE = "result_tolerance_exceeded"
CAUSE_MODEL_NOT_VERIFIED = "model_not_verified"

# 单位归一表（#121：跨适配器数值先统一单位再比较，禁止裸数值对拍）
_UNIT_SCALE: dict[str, tuple[str, float]] = {
    "m": ("length_mm", 1000.0),
    "mm": ("length_mm", 1.0),
    "cm": ("length_mm", 10.0),
    "um": ("length_mm", 1e-3),
    "hz": ("freq_ghz", 1e-9),
    "khz": ("freq_ghz", 1e-6),
    "mhz": ("freq_ghz", 1e-3),
    "ghz": ("freq_ghz", 1.0),
    "s": ("time_s", 1.0),
    "ms": ("time_s", 1e-3),
    "us": ("time_s", 1e-6),
    "ns": ("time_s", 1e-9),
    "ps": ("time_s", 1e-12),
    "deg": ("angle_deg", 1.0),
    "ohm": ("impedance_ohm", 1.0),
}

_QUANTITY_RE = re.compile(r"^\s*([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*([a-zA-Z]+)?\s*$")


def _parse_quantity(value: Any) -> tuple[float, str | None] | None:
    """把数值/带单位字符串归一为 (基准值, 单位族)；不可解析返回 None。

    基准：长度→mm、频率→GHz、时间→s、角度→deg、阻抗→Ω（#121）。
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value), None
    if not isinstance(value, str):
        return None
    match = _QUANTITY_RE.match(value)
    if not match:
        return None
    try:
        num = float(match.group(1))
    except (TypeError, ValueError):
        return None
    unit = (match.group(2) or "").lower()
    if not unit:
        return num, None
    spec = _UNIT_SCALE.get(unit)
    if spec is None:
        return num, None  # 未知单位：不猜，按原值比较
    return num * spec[1], spec[0]


def _quantity_equal(qa: tuple[float, str | None], qb: tuple[float, str | None],
                    rel_tol: float, abs_tol: float) -> bool:
    """两个归一量化是否相等（不同单位族=不相等）。"""
    if qa[1] is not None and qb[1] is not None and qa[1] != qb[1]:
        return False
    va, vb = qa[0], qb[0]
    return abs(va - vb) <= abs_tol + rel_tol * max(abs(va), abs(vb))


def _flatten_config(obj: Any, prefix: str, out: dict[str, Any]) -> None:
    """把嵌套配置展平为 {路径: 叶值}（路径用 . 连接，sorted 保证确定性）。"""
    if isinstance(obj, dict):
        for key in sorted(obj, key=str):
            _flatten_config(obj[key], f"{prefix}.{key}" if prefix else str(key), out)
    else:
        out[prefix] = obj


def diff_engine_configs(
    config_a: Any,
    config_b: Any,
    *,
    dimensions: tuple[str, ...] = CONFIG_DIMENSIONS,
    rel_tol: float = 0.02,
    abs_tol: float = 1e-9,
) -> dict[str, Any]:
    """两引擎配置逐项 diff（网格/端口/材料/边界 + other 桶）。

    数值先按 _UNIT_SCALE 归一单位（#121），再以 rel_tol/abs_tol 判定是否分歧。
    返回 JSON 友好结构：{"dimensions": {dim: [entry, ...]}, "differing": [...],
    "n_differences": int}。entry.kind ∈ {only_in_a, only_in_b, value_changed,
    unit_kind_mismatch}。
    """
    a = config_a if isinstance(config_a, dict) else {}
    b = config_b if isinstance(config_b, dict) else {}
    scanned: list[tuple[str, Any, Any]] = []
    for dim in dimensions:
        scanned.append((dim, a.get(dim, {}), b.get(dim, {})))
    other_a = {k: v for k, v in a.items() if k not in dimensions}
    other_b = {k: v for k, v in b.items() if k not in dimensions}
    scanned.append(("other", other_a, other_b))

    out_dims: dict[str, list[dict[str, Any]]] = {}
    for dim, sub_a, sub_b in scanned:
        flat_a: dict[str, Any] = {}
        flat_b: dict[str, Any] = {}
        _flatten_config(sub_a, "", flat_a)
        _flatten_config(sub_b, "", flat_b)
        entries: list[dict[str, Any]] = []
        for path in sorted(set(flat_a) | set(flat_b)):
            full = f"{dim}.{path}" if path else dim
            if path not in flat_a:
                entries.append({"path": full, "a": None, "b": flat_b[path], "kind": "only_in_b"})
                continue
            if path not in flat_b:
                entries.append({"path": full, "a": flat_a[path], "b": None, "kind": "only_in_a"})
                continue
            va, vb = flat_a[path], flat_b[path]
            qa, qb = _parse_quantity(va), _parse_quantity(vb)
            if qa is not None and qb is not None:
                if not _quantity_equal(qa, qb, rel_tol, abs_tol):
                    kind = ("unit_kind_mismatch"
                            if qa[1] is not None and qb[1] is not None and qa[1] != qb[1]
                            else "value_changed")
                    rel = abs(qa[0] - qb[0]) / max(abs(qa[0]), abs(qb[0]), abs_tol)
                    entries.append({
                        "path": full, "a": va, "b": vb, "kind": kind,
                        "normalized_a": qa[0], "normalized_b": qb[0], "rel_delta": rel,
                    })
                continue
            if va != vb:
                entries.append({"path": full, "a": va, "b": vb, "kind": "value_changed"})
        out_dims[dim] = entries

    return {
        "dimensions": out_dims,
        "differing": [d for d, e in out_dims.items() if e],
        "n_differences": sum(len(e) for e in out_dims.values()),
    }


def _diff_results(result_a: Any, result_b: Any, tolerance: Any) -> dict[str, Any]:
    """两引擎结果指标 diff（共享键 + 容差；容差可为标量或 {metric: tol}）。"""
    if not isinstance(result_a, dict) or not isinstance(result_b, dict):
        return {"diverged": False, "entries": [], "note": "结果缺失，仅按配置分歧诊断"}
    entries: list[dict[str, Any]] = []
    for key in sorted(set(result_a) & set(result_b)):
        va, vb = result_a[key], result_b[key]
        num_a, num_b = None, None
        if not isinstance(va, bool) and not isinstance(vb, bool):
            try:
                num_a, num_b = float(va), float(vb)
            except (TypeError, ValueError):
                num_a, num_b = None, None
        if num_a is None or num_b is None:
            if va != vb:
                entries.append({"metric": key, "a": va, "b": vb, "kind": "value_changed"})
            continue
        tol = tolerance.get(key, 0.5) if isinstance(tolerance, dict) else float(tolerance)
        delta = abs(num_a - num_b)
        if delta != delta:  # NaN：不可判定，跳过（不误报）
            continue
        if delta > tol:
            entries.append({
                "metric": key, "a": num_a, "b": num_b,
                "delta": delta, "tolerance": tol, "kind": "beyond_tolerance",
            })
    return {"diverged": bool(entries), "entries": entries, "note": ""}


def _frequency_shift(results_diff: dict[str, Any]) -> bool:
    """结果 diff 中频率类指标相对偏移 >1% → 疑网格档/建模分歧。"""
    for entry in results_diff.get("entries", []):
        key = str(entry.get("metric", "")).lower()
        if not any(token in key for token in ("f0", "freq", "ghz")):
            continue
        a, b = entry.get("a"), entry.get("b")
        if (isinstance(a, (int, float)) and isinstance(b, (int, float)) and a
                and abs(b - a) / abs(a) > 0.01):
            return True
    return False


def _extract_semantics(config: Any) -> dict[str, str]:
    """取配置里的参数语义声明（param_semantics / semantics）。"""
    if not isinstance(config, dict):
        return {}
    for key in ("param_semantics", "semantics"):
        value = config.get(key)
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
    return {}


def _detect_param_semantics(
    config_a: Any,
    config_b: Any,
    semantics_a: Any,
    semantics_b: Any,
    config_diff: dict[str, Any],
) -> dict[str, Any] | None:
    """#154：同名参数跨适配器语义相反（声明角色冲突或数值互反/取负）。"""
    sa = semantics_a if isinstance(semantics_a, dict) else _extract_semantics(config_a)
    sb = semantics_b if isinstance(semantics_b, dict) else _extract_semantics(config_b)
    sa = {str(k): str(v) for k, v in sa.items()}
    sb = {str(k): str(v) for k, v in sb.items()}
    flips = [
        {"param": name, "role_a": sa[name], "role_b": sb[name]}
        for name in sorted(set(sa) & set(sb)) if sa[name] != sb[name]
    ]
    inversions: list[dict[str, Any]] = []
    for entries in config_diff["dimensions"].values():
        for entry in entries:
            if entry.get("kind") != "value_changed":
                continue
            qa = _parse_quantity(entry.get("a"))
            qb = _parse_quantity(entry.get("b"))
            if qa is None or qb is None:
                continue
            va, vb = qa[0], qb[0]
            if va == 0 or vb == 0:
                continue
            if abs(va * vb - 1.0) <= 1e-6 and abs(va - 1.0) > 1e-9:
                inversions.append({"path": entry["path"], "kind": "reciprocal",
                                   "a": entry.get("a"), "b": entry.get("b")})
            elif abs(va + vb) <= 1e-9:
                inversions.append({"path": entry["path"], "kind": "negated",
                                   "a": entry.get("a"), "b": entry.get("b")})
    if not flips and not inversions:
        return None
    n = len(flips) + len(inversions)
    role_pairs = "；".join(f"{f['param']}: {f['role_a']} vs {f['role_b']}" for f in flips)
    inv_pairs = "；".join(f"{i['path']}（{i['kind']}）" for i in inversions)
    detail = "#154 同名参数跨适配器语义相反"
    if role_pairs:
        detail += f"：{role_pairs}"
    if inv_pairs:
        detail += f"；数值互反/取负：{inv_pairs}"
    return {
        "id": CAUSE_PARAM_INVERSE,
        "root_cause": "同名参数跨适配器语义相反（或数值互反/取负）",
        "lesson_ref": LESSON_SAME_NAME_INVERSE,
        "severity": "error",
        "score": 3.0 + 0.2 * max(0, n - 1),
        "detail": detail,
        "evidence": {"role_flips": flips, "numeric_inversions": inversions},
        "actions": [
            "逐参数对语义（走 core/physics_roles 的角色表），禁止各适配器按同名参数自行解释（#154）",
            "把两侧参数映射写进配置/清单后重跑对照，勿在校准层补偿语义错配",
        ],
    }


def _detect_port(
    config_a: Any,
    config_b: Any,
    config_diff: dict[str, Any],
    official: Any,
) -> dict[str, Any] | None:
    """#191：波端口尺寸不符官方口径（有官参时按官参判，否则仅报两侧不一致）。"""
    entries = config_diff["dimensions"].get("port", [])
    if not entries:
        return None
    official_port: dict[str, Any] = {}
    if isinstance(official, dict):
        inner = official.get("port")
        official_port = inner if isinstance(inner, dict) else official
    official_flat: dict[str, Any] = {}
    _flatten_config(official_port, "", official_flat)
    deviations: list[dict[str, Any]] = []
    if official_flat:
        flat_a: dict[str, Any] = {}
        flat_b: dict[str, Any] = {}
        _flatten_config(config_a.get("port", {}) if isinstance(config_a, dict) else {}, "", flat_a)
        _flatten_config(config_b.get("port", {}) if isinstance(config_b, dict) else {}, "", flat_b)
        for path, ref in sorted(official_flat.items()):
            qr = _parse_quantity(ref)
            if qr is None:
                continue
            for side, table in (("a", flat_a), ("b", flat_b)):
                if path not in table:
                    continue
                qv = _parse_quantity(table[path])
                if qv is None:
                    continue
                if not _quantity_equal(qv, qr, 1e-6, 1e-9):
                    deviations.append({"side": side, "path": f"port.{path}",
                                       "value": table[path], "official": ref})
    if deviations:
        detail = "#191 波端口尺寸偏离官方口径：" + "；".join(
            f"{d['side']} 侧 {d['path']}={d['value']}（官方 {d['official']}）" for d in deviations)
        return {
            "id": CAUSE_PORT_OFFICIAL,
            "root_cause": "波端口尺寸不符官方口径（#191）",
            "lesson_ref": LESSON_WAVE_PORT_SIZE,
            "severity": "error",
            "score": 3.0,
            "detail": detail,
            "evidence": {"official_port": official_port, "deviations": deviations,
                         "port_diff": entries},
            "actions": [
                "按官方口径重设波端口尺寸（#191：Ansys Help 波端口尺寸惯例，勿凭经验拍数）",
                "HFSS 异常先查官方文档核对端口面尺寸/参考面，再对齐另一引擎",
                "对齐后重跑两引擎对照；勿在校准层补偿端口口径错误",
            ],
        }
    return {
        "id": CAUSE_PORT_MISMATCH,
        "root_cause": "端口配置存在差异（无官方口径参照或双方均符官方）",
        "lesson_ref": "#191（波端口尺寸口径；本次未检出偏离官参）",
        "severity": "warning",
        "score": 1.2,
        "detail": "两引擎端口配置不一致：" + "；".join(
            f"{e['path']}: {e.get('a')!r} vs {e.get('b')!r}" for e in entries),
        "evidence": {"port_diff": entries, "official_port": official_port},
        "actions": [
            "核对端口类型/尺寸/参考面是否同口径（#191）",
            "补一份官方口径参照后再判定是否偏离（当前只能判两侧不一致）",
        ],
    }


def _detect_mesh(config_diff: dict[str, Any], results_diff: dict[str, Any]) -> dict[str, Any] | None:
    """网格档分歧（#152/#219）：档位/单元数/自适应设置不同，会淹没物理分歧。"""
    entries = config_diff["dimensions"].get("mesh", [])
    if not entries:
        return None
    score = min(2.5, 1.5 + 0.25 * max(0, len(entries) - 1))
    shifted = _frequency_shift(results_diff)
    if shifted:
        score += 0.5
    detail = "两引擎网格档不一致：" + "；".join(
        f"{e['path']}: {e.get('a')!r} vs {e.get('b')!r}" for e in entries)
    if shifted:
        detail += "；结果频率类指标相对偏移 >1%（疑网格伪象/建模分歧）"
    return {
        "id": CAUSE_MESH_LEVEL,
        "root_cause": "两引擎网格档不一致（网格伪象/收敛档不同，#152/#219）",
        "lesson_ref": "#152/#219（网格最小间距守卫、网格细化中心漂移）",
        "severity": "warning",
        "score": score,
        "detail": detail,
        "evidence": {"mesh_diff": entries, "frequency_shift": shifted},
        "actions": [
            "统一两引擎网格口径（base/自适应/每波长单元数）后再比较结果",
            "做网格收敛研究（≥2 档）：中心随细化单调上移=伪象自证（#219②）",
            "以 HFSS 为对齐基准仲裁网格分歧归属",
        ],
    }


def _detect_dimension(
    config_diff: dict[str, Any], dim: str, cause: str, root_cause: str,
    lesson: str, base: float,
) -> dict[str, Any] | None:
    """通用维度分歧候选（材料/边界）。"""
    entries = config_diff["dimensions"].get(dim, [])
    if not entries:
        return None
    return {
        "id": cause,
        "root_cause": root_cause,
        "lesson_ref": lesson,
        "severity": "warning",
        "score": base + 0.1 * max(0, len(entries) - 1),
        "detail": f"两引擎 {dim} 配置不一致：" + "；".join(
            f"{e['path']}: {e.get('a')!r} vs {e.get('b')!r}" for e in entries),
        "evidence": {f"{dim}_diff": entries},
        "actions": [
            f"逐项核对 {dim} 配置是否同源（#121：先统一单位再比较）",
            "模型不一致时禁止进入校准（先验模型）",
        ],
    }


def diagnose_divergence(
    config_a: Any,
    config_b: Any,
    *,
    result_a: dict[str, Any] | None = None,
    result_b: dict[str, Any] | None = None,
    engine_a: str = "engine_a",
    engine_b: str = "engine_b",
    official: Any = None,
    semantics_a: Any = None,
    semantics_b: Any = None,
    result_tolerance: Any = 0.5,
    config_rel_tol: float = 0.02,
    config_abs_tol: float = 1e-9,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """跨引擎分歧诊断（配置逐项 diff + 教训核对表 + 有序根因清单）。

    参数：
        config_a / config_b: 两引擎配置 dict（含 mesh/port/material/boundary
            子配置；可带 param_semantics 声明）。数值可带单位（mm/GHz/s...）。
        result_a / result_b: 两引擎结果指标 dict（如 f0_ghz/s11_db_min）。
        official: 官方口径参照配置（如 {"port": {...}}），用于 #191 偏离判定。
        semantics_a / semantics_b: 参数语义声明 {param: role}（覆盖 config 内声明）。
        result_tolerance: 结果容差（标量或 {metric: tol}）。
        config_rel_tol / config_abs_tol: 配置数值比较容差。
        provenance: 可选来源说明，原样带回。

    返回（JSON 友好，排序后的诊断清单，top_causes 为 top-2 命中口径）::

        {"ok", "diverged", "results_diverged", "config_diverged",
         "config_diff", "result_diff", "diagnoses", "top_causes",
         "checklist", "suggestions", "llm_role"}

    本函数不做任何 LLM 调用；LLM 仅可消费本输出做解释（llm_role="explain-only"）。
    """
    config_diff = diff_engine_configs(
        config_a, config_b, rel_tol=config_rel_tol, abs_tol=config_abs_tol)
    results_diff = _diff_results(result_a, result_b, result_tolerance)
    config_diverged = config_diff["n_differences"] > 0
    results_diverged = bool(results_diff.get("diverged"))

    candidates: list[dict[str, Any]] = []
    semantics_cand = _detect_param_semantics(
        config_a, config_b, semantics_a, semantics_b, config_diff)
    if semantics_cand:
        candidates.append(semantics_cand)
    port_cand = _detect_port(config_a, config_b, config_diff, official)
    if port_cand:
        candidates.append(port_cand)
    mesh_cand = _detect_mesh(config_diff, results_diff)
    if mesh_cand:
        candidates.append(mesh_cand)
    material_cand = _detect_dimension(
        config_diff, "material", CAUSE_MATERIAL,
        "两引擎材料参数不一致", "材料口径（#121 单位归一 + 先验模型）", 1.3)
    if material_cand:
        candidates.append(material_cand)
    boundary_cand = _detect_dimension(
        config_diff, "boundary", CAUSE_BOUNDARY,
        "两引擎边界条件不一致", "边界/PML 口径（#154 前节）", 1.1)
    if boundary_cand:
        candidates.append(boundary_cand)

    lesson154 = any(c["id"] == CAUSE_PARAM_INVERSE for c in candidates)
    lesson191 = any(c["id"] == CAUSE_PORT_OFFICIAL for c in candidates)

    if results_diverged:
        candidates.append({
            "id": CAUSE_RESULT_TOLERANCE,
            "root_cause": "两引擎结果超容差（未见已知配置指纹）",
            "lesson_ref": "容差对照（结果面）",
            "severity": "warning",
            "score": 0.5,
            "detail": "结果指标超容差：" + "；".join(
                f"{e['metric']}: {e.get('a')} vs {e.get('b')}"
                f"（Δ={e.get('delta')}，容差 {e.get('tolerance')}）"
                for e in results_diff.get("entries", [])),
            "evidence": {"result_diff": results_diff.get("entries", [])},
            "actions": [
                "结果超容差但无已知配置指纹：先人工审计建模，勿直接调参",
            ],
        })

    model_verify_hit = config_diverged and not (lesson154 or lesson191)
    if model_verify_hit:
        candidates.append({
            "id": CAUSE_MODEL_NOT_VERIFIED,
            "root_cause": "配置存在一般性分歧：先验模型/先对照官方例",
            "lesson_ref": LESSON_VERIFY_MODEL_FIRST,
            "severity": "info",
            "score": 0.3,
            "detail": "配置分歧未命中 #154/#191 已知签名，先做建模审计",
            "evidence": {"differing_dimensions": config_diff["differing"]},
            "actions": [
                "先验模型再校准：逐行审计渲染脚本/几何拓扑/端口约定/单位",
                "对照 docs/rf_template_references.md 官方例口径，确认模型正确后再比较差异",
            ],
        })

    candidates.sort(key=lambda c: -c["score"])
    top_causes = [c["id"] for c in candidates[:2]]

    checklist = [
        {
            "lesson": LESSON_SAME_NAME_INVERSE,
            "hit": lesson154,
            "evidence": "已检出同名参数语义反转" if lesson154 else "未检出同名参数语义反转",
        },
        {
            "lesson": LESSON_WAVE_PORT_SIZE,
            "hit": lesson191,
            "evidence": ("已检出波端口尺寸偏离官方口径" if lesson191
                         else "未检出波端口尺寸偏离官方口径"),
        },
        {
            "lesson": LESSON_VERIFY_MODEL_FIRST,
            "hit": model_verify_hit,
            "evidence": ("配置有分歧且未命中 #154/#191：须先验模型/对照官方例"
                         if model_verify_hit else "已由具体教训解释，无需泛化归因"),
        },
    ]

    suggestions: list[str] = []
    for cand in candidates[:2]:
        for action in cand["actions"]:
            if action not in suggestions:
                suggestions.append(action)

    report: dict[str, Any] = {
        "ok": True,
        "diverged": results_diverged or config_diverged,
        "results_diverged": results_diverged,
        "config_diverged": config_diverged,
        "engine_a": engine_a,
        "engine_b": engine_b,
        "config_diff": config_diff,
        "result_diff": results_diff,
        "diagnoses": candidates,
        "top_causes": top_causes,
        "checklist": checklist,
        "suggestions": suggestions,
        "llm_role": "explain-only",
    }
    if provenance is not None:
        report["provenance"] = provenance
    return report
