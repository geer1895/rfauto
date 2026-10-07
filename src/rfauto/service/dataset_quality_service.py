"""KD-3 数据质量门（round16 P1，J 流）——数据集入库面校验。

定位（任务书口径）：数据集入库面的确定性校验门——**单调频轴 / NaN /
单位 / 掩码** 四门，供 query_dataset 消费面在读取曲线载荷后调用
（query_dataset 本体禁改——本模块是旁挂校验面，不改动读取链）。

与既有面分工（不重复建库）：
- dataset_service.query_dataset = 读取面（谓词下推/列裁剪）；
- dataset_insights = 覆盖度/GT 标注/可见性（数据集级统计）；
- 本模块 = 曲线/行级质量门（物理合法性：频轴单调、有限性、单位
  词表、掩码完备）——检查项与 G11 健康门（run 级体检）互补不重叠。

设计约束（确定性内核，铁律 7；#122 如实）：
- 纯函数、零网络、零 LLM；同输入两次输出逐位一致；
- 门失败**如实记 FAIL 明细**，不静默放行也不静默丢弃；
- 单位词表：频率类只认 Hz 系词根（hz/khz/mhz/ghz/thz），阻抗类只认
  欧姆系（ohm/kohm/mohm）——大小写不敏感；未声明单位=UNKNOWN 如实
  报告（不猜、不默认）；
- 掩码（#314 家族）：凡按对称/互易补齐的矩阵必须随行给出掩码；掩码
  长度不匹配值长度=FAIL（"多报不放过"方向，#316）。

用法::

    from rfauto.service.dataset_quality_service import (
        curve_quality_gate, gates_for_dataset_rows)

    r = curve_quality_gate([{"freq_hz": [1e9, 2e9], "s11_db": [-1, -2],
                             "unit_freq": "Hz"}])
    rows = query_dataset("myset")["rows"]
    g = gates_for_dataset_rows(rows)   # 行级门：cost 有限、必填非空
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from rfauto.service.envelope import ok_envelope

#: 质量门契约版本（JSON 消费面稳定钉）。
DATASET_QUALITY_SCHEMA = "rfauto-dataset-quality-v1"

#: 曲线载荷键名（频率轴）；allow 别名见 _FREQ_KEYS。
_FREQ_KEYS = ("freq_hz", "frequency_hz", "freq", "frequency")

#: 单位声明键名。
_UNIT_KEYS = ("unit_freq", "units", "unit", "freq_unit")

#: 频率单位受控词表（小写词根；词根匹配=完全相等或以词根开头如 "hz"）。
FREQ_UNIT_WHITELIST = ("hz", "khz", "mhz", "ghz", "thz")

#: 阻抗单位受控词表（曲线族 z*/impedance 类消费）。
IMPEDANCE_UNIT_WHITELIST = ("ohm", "kohm", "mohm")

#: 行级门：值列必须有限的数值列（DATASET_SCHEMA 数值列的子集）。
ROW_NUMERIC_COLUMNS = ("cost", "seed", "point_index")

#: 行级门：字符串列必须非空（缺失/空白=FAIL）。
ROW_REQUIRED_COLUMNS = ("run_id", "model", "adapter")

#: 门等级（每条检查三态，#122 如实：无法判的记 UNKNOWN 不凑 PASS）。
GATE_PASS = "PASS"
GATE_FAIL = "FAIL"
GATE_UNKNOWN = "UNKNOWN"


def _first_key(payload: Mapping[str, Any], keys: Sequence[str]) -> tuple[str, Any] | None:
    """载荷里第一个存在的键（按 keys 优先级）；无 → None。"""
    for k in keys:
        if k in payload:
            return k, payload[k]
    return None


def _is_sequence_of_numbers(value: Any) -> bool:
    return (isinstance(value, (list, tuple))
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    for v in value))


def check_frequency_axis(freq_hz: Sequence[float], *,
                         strict: bool = True) -> dict[str, Any]:
    """频率轴单调性+有限性门（纯函数）。

    strict=True 要求严格递增（重复点也不许——Touchstone/扫描轴惯例）；
    strict=False 允许等值（参数扫描轴）。空轴/非数值轴=FAIL。
    """
    issues: list[str] = []
    if not isinstance(freq_hz, (list, tuple)) or not freq_hz:
        return {"gate": GATE_FAIL,
                "issues": ["freq 轴为空或非序列"], "n_points": 0}
    if not _is_sequence_of_numbers(freq_hz):
        bad = next((i for i, v in enumerate(freq_hz)
                    if not isinstance(v, (int, float)) or isinstance(v, bool)), 0)
        return {"gate": GATE_FAIL,
                "issues": [f"freq 轴第 {bad} 点非数值"], "n_points": len(freq_hz)}
    if any(not math.isfinite(float(v)) for v in freq_hz):
        issues.append("freq 轴含 NaN/Inf（非有限点）")
    finite = [float(v) for v in freq_hz if math.isfinite(float(v))]
    pairs = list(itertools.pairwise(finite))
    if strict:
        if any(b <= a for a, b in pairs):
            issues.append("freq 轴非严格递增（重复/回折点）")
    else:
        if any(b < a for a, b in pairs):
            issues.append("freq 轴非单调递增（回折点）")
    return {"gate": GATE_FAIL if issues else GATE_PASS,
            "issues": issues, "n_points": len(freq_hz)}


def check_finite(values: Sequence[float], *, name: str = "values") -> dict[str, Any]:
    """NaN/Inf 门：曲线值列逐点有限性（空序列如实 FAIL——无数据不放行）。"""
    if not isinstance(values, (list, tuple)) or not values:
        return {"gate": GATE_FAIL, "issues": [f"{name} 为空或非序列"],
                "n_nonfinite": 0}
    if not _is_sequence_of_numbers(values):
        return {"gate": GATE_FAIL, "issues": [f"{name} 含非数值元素"],
                "n_nonfinite": 0}
    bad_idx = [i for i, v in enumerate(values) if not math.isfinite(float(v))]
    issues = [f"{name} 含 {len(bad_idx)} 个非有限点（首现 idx={bad_idx[0]}）"] \
        if bad_idx else []
    return {"gate": GATE_FAIL if issues else GATE_PASS,
            "issues": issues, "n_nonfinite": len(bad_idx)}


def check_units(declared: Any, *, kind: str = "freq") -> dict[str, Any]:
    """单位声明门：declared 必须命中受控词表；未声明=UNKNOWN（不猜）。

    kind="freq" 查 FREQ_UNIT_WHITELIST，kind="impedance" 查
    IMPEDANCE_UNIT_WHITELIST；其他 kind 如实 UNKNOWN（词表未定义）。
    """
    whitelist = {"freq": FREQ_UNIT_WHITELIST,
                 "impedance": IMPEDANCE_UNIT_WHITELIST}.get(kind)
    if whitelist is None:
        return {"gate": GATE_UNKNOWN, "declared": declared,
                "issues": [f"kind={kind!r} 无受控词表（如实不判）"]}
    if declared is None or (isinstance(declared, str) and not declared.strip()):
        return {"gate": GATE_UNKNOWN, "declared": declared,
                "issues": ["单位未声明（如实 UNKNOWN，不默认）"]}
    token = str(declared).strip().lower()
    if token in whitelist:
        return {"gate": GATE_PASS, "declared": declared, "issues": []}
    # 词根形态（"Hz"/"HZ" 已由 lower 覆盖；带空格/复数形态剔除后重试）
    if token.rstrip("s ") in whitelist:
        return {"gate": GATE_PASS, "declared": declared, "issues": []}
    return {"gate": GATE_FAIL, "declared": declared,
            "issues": [f"单位 {declared!r} 不在 {kind} 受控词表 {list(whitelist)}"]}


def check_mask(mask: Any, n_values: int) -> dict[str, Any]:
    """掩码完备性门（#314 家族口径）。

    mask=None=未掩码（如实 UNKNOWN——是否需要掩码由载荷语义决定，
    本门只判"给了掩码就给对"）；给掩码时须与值等长的 bool 序列，
    全 False 掩码=FAIL（#316：全 False 会把数据整列静默藏掉）。
    """
    if mask is None:
        return {"gate": GATE_UNKNOWN, "issues": ["未给掩码（如实 UNKNOWN）"],
                "n_true": 0}
    if not isinstance(mask, (list, tuple)) or not mask:
        return {"gate": GATE_FAIL, "issues": ["掩码为空或非序列"], "n_true": 0}
    if not all(isinstance(v, bool) for v in mask):
        return {"gate": GATE_FAIL, "issues": ["掩码含非 bool 元素"],
                "n_true": 0}
    if len(mask) != n_values:
        return {"gate": GATE_FAIL,
                "issues": [f"掩码长度 {len(mask)} != 值长度 {n_values}"],
                "n_true": sum(mask)}
    if not any(mask):
        return {"gate": GATE_FAIL, "issues": ["掩码全 False（整列被藏，#316 方向）"],
                "n_true": 0}
    return {"gate": GATE_PASS, "issues": [], "n_true": sum(mask)}


def curve_quality_gate(curves: Sequence[Mapping[str, Any]], *,
                       strict_axis: bool = True) -> dict[str, Any]:
    """曲线载荷入库门（KD-3 主入口，确定性纯函数）。

    每条曲线载荷 = {"freq_hz": [...], "<量名>": [...], "unit_freq": "Hz",
    "mask": [bool]|None, "curve_id": str}（curve_id 缺省按序号）。四门
    逐曲线跑：单调频轴 / NaN / 单位 / 掩码。任何一条曲线 FAIL → 总门
    FAIL；UNKNOWN 不翻转总门但如实透出（#122：不凑绿不掩盖）。

    返回 JSON 友好契约::

        {ok, schema, n_curves, verdict,
         per_curve: [{curve_id, freq, nan, units, mask, verdict}],
         n_fail, n_unknown, issues: [str]}
    """
    per_curve: list[dict[str, Any]] = []
    issues: list[str] = []
    n_fail = 0
    n_unknown = 0
    if not isinstance(curves, (list, tuple)):
        return {"ok": False, "schema": DATASET_QUALITY_SCHEMA, "n_curves": 0,
                "verdict": GATE_FAIL, "per_curve": [], "n_fail": 0,
                "n_unknown": 0, "issues": ["curves 须为序列"]}
    for i, curve in enumerate(curves):
        if not isinstance(curve, Mapping):
            n_fail += 1
            per_curve.append({"curve_id": f"curve[{i}]", "verdict": GATE_FAIL,
                              "issues": ["曲线载荷须为 mapping"]})
            issues.append(f"curve[{i}]: 载荷须为 mapping")
            continue
        cid = str(curve.get("curve_id", f"curve[{i}]"))
        curve_issues: list[str] = []
        gates: dict[str, str] = {}

        freq_hit = _first_key(curve, _FREQ_KEYS)
        if freq_hit is None:
            freq_r = {"gate": GATE_FAIL, "issues": ["无频率轴键"], "n_points": 0}
        else:
            freq_r = check_frequency_axis(freq_hit[1], strict=strict_axis)
        gates["freq"] = freq_r["gate"]
        curve_issues += [f"freq: {m}" for m in freq_r["issues"]]

        value_keys = [k for k in curve
                      if k not in _FREQ_KEYS + _UNIT_KEYS + ("mask", "curve_id")
                      and _is_sequence_of_numbers(curve[k])]
        nan_gates = []
        for vk in value_keys:
            vr = check_finite(curve[vk], name=vk)
            nan_gates.append(vr["gate"])
            curve_issues += [f"{m}" for m in vr["issues"]]
        gates["nan"] = (GATE_FAIL if GATE_FAIL in nan_gates
                        else GATE_PASS if nan_gates else GATE_UNKNOWN)
        if gates["nan"] == GATE_UNKNOWN:
            curve_issues.append("nan: 无数值值列可检（如实 UNKNOWN）")

        unit_hit = _first_key(curve, _UNIT_KEYS)
        unit_r = check_units(unit_hit[1] if unit_hit else None, kind="freq")
        gates["units"] = unit_r["gate"]
        curve_issues += [f"units: {m}" for m in unit_r["issues"]]

        n_vals = max((len(curve[k]) for k in value_keys), default=0)
        mask_r = check_mask(curve.get("mask"), n_vals)
        gates["mask"] = mask_r["gate"]
        curve_issues += [f"mask: {m}" for m in mask_r["issues"]]

        # 掩码 UNKNOWN=未给掩码（非补齐矩阵的正常形态）不阻断——只有
        # FAIL（给了掩码但给错）翻转总门；freq/nan/units UNKNOWN 照常阻断。
        blocking = {k: v for k, v in gates.items()
                    if not (k == "mask" and v == GATE_UNKNOWN)}
        if GATE_FAIL in blocking.values():
            verdict = GATE_FAIL
            n_fail += 1
        elif GATE_UNKNOWN in blocking.values():
            verdict = GATE_UNKNOWN
            n_unknown += 1
        else:
            verdict = GATE_PASS
        for m in curve_issues:
            issues.append(f"{cid}: {m}")
        per_curve.append({"curve_id": cid, "verdict": verdict,
                          "gates": gates, "issues": curve_issues})

    verdict = (GATE_FAIL if n_fail else
               GATE_UNKNOWN if n_unknown else GATE_PASS)
    return ok_envelope(schema=DATASET_QUALITY_SCHEMA,
                       n_curves=len(per_curve), verdict=verdict,
                       per_curve=per_curve, n_fail=n_fail,
                       n_unknown=n_unknown, issues=issues)


def gates_for_dataset_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """query_dataset 行面质量门（消费面旁挂，确定性纯函数）。

    行级三门：必填字符串列非空（run_id/model/adapter）、数值列有限
    （cost/seed/point_index）、params_json/metrics_json 可解析为 JSON
    对象（载荷损坏留痕不中断——坏行计数透出）。
    """
    bad_required: list[str] = []
    bad_numeric: list[str] = []
    bad_json: list[str] = []
    n_rows = len(rows) if isinstance(rows, (list, tuple)) else 0
    if not isinstance(rows, (list, tuple)):
        return {"ok": False, "schema": DATASET_QUALITY_SCHEMA,
                "n_rows": 0, "verdict": GATE_FAIL,
                "bad_required": [], "bad_numeric": [], "bad_json": [],
                "issues": ["rows 须为序列"]}
    for i, row in enumerate(rows):
        if not isinstance(row, Mapping):
            bad_required.append(f"row[{i}](非 mapping)")
            continue
        rid = str(row.get("run_id", f"row[{i}]"))
        for col in ROW_REQUIRED_COLUMNS:
            val = row.get(col)
            if val is None or (isinstance(val, str) and not val.strip()):
                bad_required.append(f"{rid}.{col}")
        for col in ROW_NUMERIC_COLUMNS:
            val = row.get(col)
            if val is None:
                continue  # 可空列（seed 可 null）如实放过
            if isinstance(val, bool) or not isinstance(val, (int, float)) \
                    or not math.isfinite(float(val)):
                bad_numeric.append(f"{rid}.{col}={val!r}")
        for col in ("params_json", "metrics_json"):
            val = row.get(col)
            if val is None:
                continue
            try:
                parsed = json.loads(val)
                if not isinstance(parsed, dict):
                    raise ValueError("非 JSON 对象")
            except Exception as exc:
                bad_json.append(f"{rid}.{col}（{type(exc).__name__}）")
    verdict = GATE_FAIL if (bad_required or bad_numeric or bad_json) else GATE_PASS
    return ok_envelope(schema=DATASET_QUALITY_SCHEMA, n_rows=n_rows,
                       verdict=verdict,
                       bad_required=bad_required, bad_numeric=bad_numeric,
                       bad_json=bad_json,
                       issues=([f"必填列缺失 {len(bad_required)} 处"] if bad_required else [])
                              + ([f"数值列非有限 {len(bad_numeric)} 处"] if bad_numeric else [])
                              + ([f"JSON 载荷损坏 {len(bad_json)} 处"] if bad_json else []))
