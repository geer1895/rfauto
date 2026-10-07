"""F-B P2：电源完整性（PI/PDN）service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/pdn.py 闭式族（F-B.1 P1 已落地；本服务零物理公式，全部数字出自
确定性内核，铁律 7）。三入口（方案 研究扩充
§F-B 第 3 节文件面级分解）：

- :func:`pdn_analyze`：decap 库/内联规格 + VRM + 平面几何 → Z 谱 + 逐频
  裕量 + 反谐振峰清单（峰频 + Q 估计）+ 腔模清单；
- :func:`pdn_select`：候选池（库子集 + cost 口径）+ 目标 + 频轴 →
  greedy_decap_select 薄封装（同输入同解，不改变语义）+ 选中明细 + 逐频
  裕量；infeasible 如实透传（不凑解语义由内核保证）；
- :func:`pdn_gate`：KiCad AC-PI 门（fab DFM 门同框架的薄面）——平面腔模
  筛查（f_mn vs 关注带）+ 安装位置避让判据 +（可选）Z 谱裕量门，verdict
  PASS/FAIL/UNKNOWN 三值。

**KiCad 提取面现状（B5-5 已落，如实登记）**：:func:`pdn_power_pairs` 从
.kicad_pcb **文本 s-expression**（不走 pcbnew 子进程）提取电源对——网分类
（启发式+调用方覆盖）→ 同层电源/地 zone bbox 交集的平面偶 span（
``pdn_plane_inputs[].a_m/b_m``，可直接作本服务 ``plane`` 参数候选）+ 电源/
地过孔最近邻对间距（``via_pairs[].spacing_mm``，core.pdn.mount_inductance
的 via_pair_spacing_m 输入）+ 去耦电容簇（``decap_clusters[]``，焊盘桥接
电源/地两网的封装按轨聚簇）。pdn_analyze/pdn_gate 的 ``plane`` 本身仍显式
走参数（提取产物喂入是调用方编排，门不隐式读文件）；v1 简化如实声明在
adapter docstring（zone bbox 近似、不判 L 形分割平面、弧段轮廓跳过告警）。

**预声明判据（先写后跑，#122；research_expansion §F-B 第 4 节）**：
1. analyze 的 Z 谱与 core.pdn.pdn_impedance_profile 直算逐位一致（薄壳
   不改语义）；反谐振峰频 vs LC 解析式逐位（峰位恰落栅格点时）；
2. select 与 core.greedy_decap_select 同输入同解（selected_indices/
   total_cost/z_profile 逐位）；infeasible 如实透传；
3. gate 判据（缺省口径，均预声明）：
   - R1 腔模筛查：任一 (m,n) 腔模频率落入关注带 [f_lo, f_hi] → 违项
     ``cavity_mode_in_band``（保守筛查口径：带内腔模即风险，不做激励强度
     加权——加权需布局细节，v1 不臆造）；
   - R2 安装避让：安装位置到带内腔模最近波腹的欧氏距离 < threshold_frac
     ·λ_eff → 违项 ``mount_too_close``；λ_eff 在**关注带上缘 f_hi** 评估
     （f_hi=调用方扰动频率代理——内核 docstring 已声明 f_mn 自身频率下
     缺省半波长口径必然退化为 too_close，故门取带缘，如实声明）；
   - R3 Z 谱裕量门（可选）：payload.impedance 给出时复用 pdn_analyze，
     worst margin < 0 → 违项 ``impedance_exceeds_target``；
   - verdict 聚合：plane 或 interest_band 缺失 → UNKNOWN（如实，理由进
     unknown_reason；R3 结果照报但不得把 UNKNOWN 升级为 PASS/FAIL）；
     否则有违项 → FAIL，无违项 → PASS。
4. 库缺件：任何条目 part_id 在库中不存在 → ok=False，errors 列出全部
   缺件（不静默跳过、不部分计算）。
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import numpy as np
import yaml

from rfauto.adapters.kicad_power_pairs import extract_power_pairs
from rfauto.core.pdn import (
    DecapSpec,
    VrmModel,
    greedy_decap_select,
    load_decap_library,
    mount_position_clearance,
    pdn_impedance_profile,
    plane_cavity_modes,
    target_impedance_freq,
)

# F-13 批 2（W6-E）：payload 解析助手单源化——_num/_require_payload_dict
# 自 service/_helpers 别名 import（W2-G 批 1 同款，#116 旧副本删净）；
# pdn 本地副本三处文案分歧（bool/positive/nonneg）与 None 语义（本地
# 「必须是数字，实际 None」vs 单源「缺失」）统一为单源文案——ok=False
# 语义逐位不变，文案变更已声明（W6-E 报告/口径）。
from rfauto.service._helpers import parse_num as _num
from rfauto.service._helpers import require_payload_dict as _require_payload_dict
from rfauto.service.envelope import ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
PDN_SERVICE_SCHEMA_VERSION = "1.0"

#: 反谐振峰清单最多输出条数（按 |Z| 降序取前 N）
_ANTIRESONANCE_TOP_N = 20

#: plane.m_max/n_max 缺省（腔模筛查阶数；显式可覆盖）
_PLANE_DEFAULT_MODE_MAX = 4

#: 内联规格无 provenance 时的如实缺省（铁律 7：不冒充 vendor 实测）
_INLINE_PROVENANCE_DEFAULT = "caller_payload: 调用方内联规格（未经 vendor 实测核实）"

#: gate 名（JSON 消费方按 gate 字段分派）
PDN_GATE_NAME = "pdn_ac_pi"


# ─── payload 解析助手（全部错误收集进 errors 列表，不抛出） ──────────────────


def _load_library(payload: dict[str, Any], errors: list[str]) -> dict[str, DecapSpec]:
    """加载 decap 库（payload.library_path 可选覆盖缺省库）。

    捕获面=一切"库文件坏"的合理形态（含 OSError 权限/目录、yaml 解析错）——
    审查轨 C P1-1：窄捕会让 malformed YAML/目录路径穿透信封炸 MCP 会话。
    """
    lib_path = payload.get("library_path")
    try:
        return load_decap_library(lib_path) if lib_path is not None else load_decap_library()
    except (KeyError, ValueError, OSError, yaml.YAMLError) as exc:
        errors.append(f"decap 库加载失败: {exc}")
        return {}


def _curve_from_raw(raw: Any, where: str, errors: list[str]) -> tuple[tuple[float, float], ...] | None:
    """dc_bias_curve 解析：{"v": [...], "c": [...]} 或 [[v, c], ...] 序列。"""
    if raw is None:
        return None
    try:
        pairs = list(zip(raw["v"], raw["c"], strict=True)) if isinstance(raw, dict) else [(p[0], p[1]) for p in raw]
        return tuple((float(v), float(c)) for v, c in pairs)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"{where}: dc_bias_curve 形状非法（须 {{v:[...], c:[...]}} 或 [[v,c],...]）: {exc}")
        return None


def _resolve_cap_entries(
    entries: Any,
    where: str,
    lib: dict[str, DecapSpec],
    errors: list[str],
) -> list[tuple[DecapSpec, dict[str, Any]]]:
    """电容条目归一：库 part_id 字符串 | {part_id...} 库引用 | {c_f...} 内联。

    返回 [(DecapSpec, meta)]（未按 count 展开；展开在 _instantiate）。
    缺名/形状错写 errors（不抛出，最终 ok=False 列缺件）。
    """
    if entries is None:
        return []
    if not isinstance(entries, list):
        errors.append(f"{where} 必须是列表，实际 {type(entries).__name__}")
        return []
    out: list[tuple[DecapSpec, dict[str, Any]]] = []
    for i, raw in enumerate(entries):
        tag = f"{where}[{i}]"
        if isinstance(raw, str):
            part_id = raw.strip()
            spec = lib.get(part_id)
            if spec is None:
                errors.append(f"{tag}: 库中无此 part_id {part_id!r}（库共 {len(lib)} 条）")
                continue
            out.append((spec, {"part_id": part_id, "source": "library", "count": 1}))
            continue
        if not isinstance(raw, dict):
            errors.append(f"{tag}: 须为库 part_id 字符串或对象，实际 {type(raw).__name__}")
            continue
        if raw.get("part_id") is not None:
            part_id = str(raw["part_id"]).strip()
            spec = lib.get(part_id)
            if spec is None:
                errors.append(f"{tag}: 库中无此 part_id {part_id!r}（库共 {len(lib)} 条）")
                continue
            overrides: dict[str, Any] = {}
            if raw.get("mount_l_h") is not None:
                mount = _num(raw["mount_l_h"], f"{tag}.mount_l_h", errors, nonneg=True)
                if mount is not None:
                    overrides["mount_l_h"] = mount
            if overrides:
                spec = dataclasses.replace(spec, **overrides)
            count = raw.get("count", 1)
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                errors.append(f"{tag}.count 必须为正整数，实际 {count!r}")
                continue
            out.append((spec, {"part_id": part_id, "source": "library_ref", "count": count}))
            continue
        if raw.get("c_f") is not None:
            c_f = _num(raw["c_f"], f"{tag}.c_f", errors, positive=True)
            esr = _num(raw.get("esr_ohm", 0.0), f"{tag}.esr_ohm", errors, nonneg=True)
            esl = _num(raw.get("esl_h", 0.0), f"{tag}.esl_h", errors, nonneg=True)
            mount = _num(raw.get("mount_l_h", 0.0), f"{tag}.mount_l_h", errors, nonneg=True)
            cost = _num(raw.get("cost", 1.0), f"{tag}.cost", errors, positive=True)
            if None in (c_f, esr, esl, mount, cost):
                continue
            curve = _curve_from_raw(raw.get("dc_bias_curve"), f"{tag}.dc_bias_curve", errors)
            try:
                spec = DecapSpec(
                    part=str(raw.get("part") or f"inline_{i}"),
                    c_f=c_f,  # type: ignore[arg-type]
                    esr_ohm=esr,  # type: ignore[arg-type]
                    esl_h=esl,  # type: ignore[arg-type]
                    mount_l_h=mount,  # type: ignore[arg-type]
                    provenance=str(raw.get("provenance") or _INLINE_PROVENANCE_DEFAULT),
                    dc_bias_curve=curve,
                    cost=cost,  # type: ignore[arg-type]
                    notes=str(raw.get("notes", "")),
                )
            except ValueError as exc:
                errors.append(f"{tag}: {exc}")
                continue
            count = raw.get("count", 1)
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                errors.append(f"{tag}.count 必须为正整数，实际 {count!r}")
                continue
            out.append((spec, {"part_id": str(raw.get("part") or f"inline_{i}"), "source": "inline", "count": count}))
            continue
        errors.append(f"{tag}: 须为库 part_id 字符串、{{part_id...}} 库引用或 {{c_f...}} 内联规格")
    return out


def _apply_dc_bias(spec: DecapSpec, v_bias_v: float) -> tuple[DecapSpec, float, str]:
    """按 DC-bias 曲线生成等效候选（core docstring 口径：折减由调用方先做）。

    返回 (等效 spec, 有效电容, 状态标记)；无曲线/无折减返回原 spec。
    """
    c_eff, status = spec.effective_c(v_bias_v)
    if status != "derated":
        return spec, spec.c_f, status
    return dataclasses.replace(spec, c_f=c_eff), c_eff, status


def _instantiate(
    resolved: list[tuple[DecapSpec, dict[str, Any]]],
    v_bias_v: float | None,
) -> tuple[list[DecapSpec], list[dict[str, Any]], list[int]]:
    """展开 count 为并行支路实例；v_bias_v 给出时对带曲线条目折减。

    返回 (specs, details, slot_owner)；slot_owner[k] = specs[k] 所属条目序号
    （select 输出按槽位回查条目明细用）。
    """
    specs: list[DecapSpec] = []
    details: list[dict[str, Any]] = []
    slot_owner: list[int] = []
    for idx, (spec, meta) in enumerate(resolved):
        if v_bias_v is not None:
            eff_spec, c_eff, status = _apply_dc_bias(spec, v_bias_v)
        else:
            eff_spec, c_eff, status = spec, spec.c_f, "not_applied"
        for _ in range(meta["count"]):
            specs.append(eff_spec)
            slot_owner.append(idx)
        details.append({
            **meta,
            "part": spec.part,
            "c_f": spec.c_f,
            "c_effective": c_eff,
            "derating": status,
            "esr_ohm": spec.esr_ohm,
            "esl_h": spec.esl_h,
            "mount_l_h": spec.mount_l_h,
            "cost": spec.cost,
            "provenance": spec.provenance,
        })
    return specs, details, slot_owner


def _build_vrm(raw: Any, errors: list[str]) -> VrmModel | None:
    """vrm {r0, l0, r1, l1}（四键全必给，各自非负）→ VrmModel 或 None。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        errors.append(f"vrm 必须是对象 {{r0, l0, r1, l1}}，实际 {type(raw).__name__}")
        return None
    vals: dict[str, float] = {}
    for key in ("r0", "l0", "r1", "l1"):
        num = _num(raw.get(key), f"vrm.{key}", errors, nonneg=True)
        if num is None:
            return None
        vals[key] = num
    try:
        return VrmModel(**vals)
    except (TypeError, ValueError) as exc:
        errors.append(f"vrm 非法: {exc}")
        return None


def _build_freq_axis(payload: dict[str, Any], errors: list[str]) -> np.ndarray | None:
    """f_axis 显式列表 或 f_start/f_stop/n_points(+scale log|lin 缺省 log)。"""
    if payload.get("f_axis") is not None:
        raw = payload["f_axis"]
        if not isinstance(raw, list) or not raw:
            errors.append(f"f_axis 必须是非空数字列表，实际 {raw!r}")
            return None
        vals: list[float] = []
        for i, v in enumerate(raw):
            num = _num(v, f"f_axis[{i}]", errors, positive=True)
            if num is None:
                return None
            vals.append(num)
        return np.asarray(vals, dtype=float)
    f_start = _num(payload.get("f_start"), "f_start", errors, positive=True)
    f_stop = _num(payload.get("f_stop"), "f_stop", errors, positive=True)
    n_points = payload.get("n_points", 201)
    if not isinstance(n_points, int) or isinstance(n_points, bool) or n_points < 2:
        errors.append(f"n_points 必须为 ≥2 的整数，实际 {n_points!r}")
        return None
    if f_start is None or f_stop is None:
        if not errors:
            errors.append("频率轴须给 f_axis 或 f_start/f_stop(/n_points)")
        return None
    if f_stop <= f_start:
        errors.append(f"f_stop 必须大于 f_start，实际 {f_stop!r} ≤ {f_start!r}")
        return None
    scale = str(payload.get("scale", "log")).strip().lower()
    if scale == "log":
        return np.geomspace(f_start, f_stop, n_points)
    if scale == "lin":
        return np.linspace(f_start, f_stop, n_points)
    errors.append(f"scale 须为 log|lin，实际 {scale!r}")
    return None


def _build_target(
    payload: dict[str, Any],
    freqs: np.ndarray,
    errors: list[str],
) -> np.ndarray | None:
    """target {v_ripple_v, delta_i_a, profile?, fc_hz?} → Z_target(f) 或 None。"""
    raw = payload.get("target")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        errors.append(f"target 必须是对象，实际 {type(raw).__name__}")
        return None
    v_ripple = _num(raw.get("v_ripple_v"), "target.v_ripple_v", errors, positive=True)
    delta_i = _num(raw.get("delta_i_a"), "target.delta_i_a", errors, positive=True)
    if v_ripple is None or delta_i is None:
        return None
    profile = str(raw.get("profile", "flat")).strip().lower()
    corner_raw = raw.get("fc_hz", raw.get("corner_freq_hz"))
    corner = None if corner_raw is None else _num(corner_raw, "target.fc_hz", errors, positive=True)
    if profile == "smith" and corner is None and not errors:
        errors.append("target.profile='smith' 必须给 fc_hz（拐点频率为参数，不发明缺省）")
        return None
    try:
        return target_impedance_freq(freqs, v_ripple, delta_i, profile, corner_freq_hz=corner)
    except ValueError as exc:
        errors.append(f"target 非法: {exc}")
        return None


def _build_plane(raw: Any, errors: list[str]) -> dict[str, Any] | None:
    """plane {a_m, b_m, er, m_max?, n_max?} → 归一 dict 或 None。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        errors.append(f"plane 必须是对象 {{a_m, b_m, er}}，实际 {type(raw).__name__}")
        return None
    a_m = _num(raw.get("a_m"), "plane.a_m", errors, positive=True)
    b_m = _num(raw.get("b_m"), "plane.b_m", errors, positive=True)
    er = _num(raw.get("er"), "plane.er", errors, positive=True)
    if a_m is None or b_m is None or er is None:
        return None
    m_max = raw.get("m_max", _PLANE_DEFAULT_MODE_MAX)
    n_max = raw.get("n_max", _PLANE_DEFAULT_MODE_MAX)
    for tag, val in (("m_max", m_max), ("n_max", n_max)):
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            errors.append(f"plane.{tag} 必须为非负整数，实际 {val!r}")
            return None
    return {"a_m": a_m, "b_m": b_m, "er": er, "m_max": m_max, "n_max": n_max}


def _bias_value(payload: dict[str, Any], errors: list[str]) -> float | None:
    """v_bias_v 可选（>0 才生效；缺省 None=不做折减）。"""
    raw = payload.get("v_bias_v")
    if raw is None:
        return None
    return _num(raw, "v_bias_v", errors, positive=True)


def _fin(x: float) -> float | None:
    """非有限值（inf/nan）序列化为 None（JSON 无 Infinity）。"""
    return float(x) if math.isfinite(float(x)) else None


def _float_list(arr: np.ndarray) -> list[float | None]:
    return [_fin(v) for v in np.asarray(arr).ravel()]


# ─── 反谐振峰检测（|Z| 局部极大 + -3dB 带宽 Q 估计） ─────────────────────────


def _half_power_edge(f: np.ndarray, db: np.ndarray, i: int, step: int, thr: float) -> float | None:
    """从峰位 i 向 step 方向找 dB 域首次跌破 thr 的栅格间线性插值交点。

    越界/不可分辨（平坦段）→ None（Q 估计如实缺失，不凑值）。
    """
    n = len(db)
    j = i
    while 0 <= j + step < n and math.isfinite(float(db[j + step])) and float(db[j + step]) > thr:
        j += step
    k = j + step
    if not (0 <= k < n) or not math.isfinite(float(db[k])):
        return None
    db_j = float(db[j])
    db_k = float(db[k])
    if db_j == db_k:
        return None
    frac = (db_j - thr) / (db_j - db_k)
    return float(f[j] + (f[k] - f[j]) * frac)


def _detect_antiresonances(
    freqs: np.ndarray,
    z: np.ndarray,
    top_n: int = _ANTIRESONANCE_TOP_N,
) -> list[dict[str, Any]]:
    """|Z(f)| 局部极大 → 峰清单（按 |Z| 降序取前 top_n；Q=f_peak/BW_-3dB）。

    |Z|=inf（栅格点恰为精确反谐振，Y=0）照常检出为峰——峰频如实报、
    |Z| 与 Q 估计序列化为 None（-3dB 带宽在 inf 峰不可分辨，不凑值）。
    """
    mag = np.abs(z)
    if mag.size < 3:
        return []
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(mag)
    peaks = [
        i for i in range(1, mag.size - 1)
        if float(mag[i]) > float(mag[i - 1])
        and float(mag[i]) >= float(mag[i + 1])
    ]
    peaks.sort(key=lambda i: float(mag[i]), reverse=True)
    out: list[dict[str, Any]] = []
    for i in peaks[:top_n]:
        peak_db = float(db[i])
        if not math.isfinite(peak_db):
            q_est = None
        else:
            thr = peak_db - 3.0
            f_lo = _half_power_edge(freqs, db, i, -1, thr)
            f_hi = _half_power_edge(freqs, db, i, +1, thr)
            q_est = (float(freqs[i] / (f_hi - f_lo))
                     if f_lo is not None and f_hi is not None and f_hi > f_lo else None)
        out.append({
            "f_hz": float(freqs[i]),
            "z_ohm": _fin(mag[i]),
            "q_est": q_est,
        })
    return out


# ─── 分析共享内核（analyze 与 gate.impedance 复用，保证同语义） ───────────────


def _analyze_network(
    payload: dict[str, Any],
    errors: list[str],
) -> dict[str, Any] | None:
    """Z 谱合成核心：条目解析→折减→导纳求和→目标/裕量/峰清单。

    plane 腔模不在此（analyze 顶层组装）；errors 非空时返回 None。
    """
    lib = _load_library(payload, errors)
    decap_resolved = _resolve_cap_entries(payload.get("decaps"), "decaps", lib, errors)
    bulk_resolved = _resolve_cap_entries(payload.get("bulk"), "bulk", lib, errors)
    vrm = _build_vrm(payload.get("vrm"), errors)
    freqs = _build_freq_axis(payload, errors)
    v_bias = _bias_value(payload, errors)
    # freqs is None 必然伴随 error 已入列（_build_freq_axis 契约）——判空仅为
    # 类型收窄，运行时行为与 `if errors` 完全等价。
    if errors or freqs is None:
        return None
    decap_specs, decap_details, _ = _instantiate(decap_resolved, v_bias)
    bulk_specs, bulk_details, _ = _instantiate(bulk_resolved, v_bias)
    z = pdn_impedance_profile(vrm, bulk_specs, decap_specs, freqs)
    z_target = _build_target(payload, freqs, errors)
    if errors:
        return None

    z_mag = np.abs(z)
    with np.errstate(divide="ignore", invalid="ignore"):
        z_db = 20.0 * np.log10(z_mag)
    margin: np.ndarray | None = None
    worst: dict[str, Any] | None = None
    if z_target is not None:
        with np.errstate(divide="ignore", invalid="ignore"):
            margin = 20.0 * np.log10(z_target / z_mag)
        finite = np.isfinite(margin)
        if bool(np.any(finite)):
            idx = int(np.argmin(np.where(finite, margin, np.inf)))
            worst = {
                "f_hz": float(freqs[idx]),
                "margin_db": float(margin[idx]),
                "z_ohm": float(z_mag[idx]),
                "z_target_ohm": float(z_target[idx]),
            }
    return {
        "f_hz": freqs,
        "z": z,
        "z_mag": z_mag,
        "z_db": z_db,
        "z_target": z_target,
        "margin": margin,
        "worst_margin": worst,
        "anti_resonances": _detect_antiresonances(freqs, z),
        "branch_details": {"vrm": None if vrm is None else dataclasses.asdict(vrm),
                           "bulk": bulk_details, "decaps": decap_details},
        "v_bias_v": v_bias,
        "n_decap_branches": len(decap_specs),
        "n_bulk_branches": len(bulk_specs),
    }


def _network_output(core: dict[str, Any]) -> dict[str, Any]:
    """_analyze_network 结果 → JSON 面（复数拆 re/im，非有限值 → None）。"""
    z = core["z"]
    return {
        "f_hz": core["f_hz"].tolist(),
        "n_points": int(core["f_hz"].size),
        "z_re_ohm": core["z"].real.tolist(),
        "z_im_ohm": core["z"].imag.tolist(),
        "z_mag_ohm": _float_list(core["z_mag"]),
        "z_mag_db_ohm": _float_list(core["z_db"]),
        "z_phase_deg": (np.degrees(np.angle(z))).tolist(),
        "z_target_ohm": None if core["z_target"] is None else core["z_target"].tolist(),
        "margin_db": None if core["margin"] is None else _float_list(core["margin"]),
        "worst_margin": core["worst_margin"],
        "anti_resonances": core["anti_resonances"],
        "branch_details": core["branch_details"],
        "v_bias_v": core["v_bias_v"],
        "n_decap_branches": core["n_decap_branches"],
        "n_bulk_branches": core["n_bulk_branches"],
    }


# ─── 三入口 ──────────────────────────────────────────────────────────────────


def pdn_analyze(payload: dict[str, Any]) -> dict[str, Any]:
    """PDN 阻抗谱分析（JSON 进出）。

    Args:
        payload: decaps（条目=库 part_id 字符串 | {part_id, mount_l_h?,
            count?} 库引用 | {part?, c_f, esr_ohm?, esl_h?, mount_l_h?,
            cost?, dc_bias_curve?, count?, provenance?} 内联规格）、
            bulk/vrm({r0,l0,r1,l1}) 可选、plane({a_m,b_m,er,m_max?,n_max?})
            可选、target({v_ripple_v, delta_i_a, profile: flat|smith,
            fc_hz?}) 可选、f_axis 或 f_start/f_stop/n_points(+scale)、
            v_bias_v 可选、library_path 可选。

    Returns:
        dict: {ok, schema_version, f_hz, z_re/z_im/z_mag/z_mag_db/z_phase,
        z_target_ohm, margin_db, worst_margin, anti_resonances, cavity_modes,
        branch_details, ...}；库缺件/形状非法 → {ok: False, errors}
    """
    try:
        payload = _require_payload_dict(payload)
        errors: list[str] = []
        core = _analyze_network(payload, errors)
        plane = _build_plane(payload.get("plane"), errors)
        if errors or core is None:
            return {"ok": False, "schema_version": PDN_SERVICE_SCHEMA_VERSION, "errors": errors}
        out = ok_envelope(schema_version=PDN_SERVICE_SCHEMA_VERSION)
        out.update(_network_output(core))
        if plane is not None:
            modes = plane_cavity_modes(plane["a_m"], plane["b_m"], plane["er"],
                                       plane["m_max"], plane["n_max"])
            out["cavity_modes"] = [
                {"m": m.m, "n": m.n, "f_hz": m.f_hz} for m in modes
            ]
            out["plane"] = {k: plane[k] for k in ("a_m", "b_m", "er", "m_max", "n_max")}
        else:
            out["cavity_modes"] = None
        return out
    except (KeyError, TypeError, ValueError, OSError, yaml.YAMLError) as exc:
        return {"ok": False, "schema_version": PDN_SERVICE_SCHEMA_VERSION,
                "errors": [str(exc)]}


def pdn_select(payload: dict[str, Any]) -> dict[str, Any]:
    """贪心 decap 选型（greedy_decap_select 薄封装，同输入同解）。

    Args:
        payload: candidates（必给非空，条目形态同 analyze.decaps；count>1
            展开为多颗池槽位）、budget（必给 ≥0）、target（必给）、频率轴
            （f_axis 或 f_start/f_stop/n_points）、vrm/bulk 基线可选、
            v_bias_v 可选、library_path 可选。

    Returns:
        dict: {ok, feasible, infeasible, n_selected, total_cost, budget,
        excess, selected[{slot, part_id, part, c_f, ...}], margin_db,
        worst_margin, candidate_details}；infeasible 是正常结果（ok=True）
        如实透传，不凑解语义由内核保证。
    """
    try:
        payload = _require_payload_dict(payload)
        errors: list[str] = []
        lib = _load_library(payload, errors)
        cand_resolved = _resolve_cap_entries(payload.get("candidates"), "candidates", lib, errors)
        if payload.get("candidates") is not None and not cand_resolved and not errors:
            errors.append("candidates 必须是非空列表")
        bulk_resolved = _resolve_cap_entries(payload.get("bulk"), "bulk", lib, errors)
        vrm = _build_vrm(payload.get("vrm"), errors)
        freqs = _build_freq_axis(payload, errors)
        z_target = None
        if freqs is not None:
            z_target = _build_target(payload, freqs, errors)
        budget = _num(payload.get("budget"), "budget", errors, nonneg=True)
        v_bias = _bias_value(payload, errors)
        if z_target is None and not errors:
            errors.append("target 必给（v_ripple_v/delta_i_a[/profile/fc_hz]）")
        if errors:
            return {"ok": False, "schema_version": PDN_SERVICE_SCHEMA_VERSION, "errors": errors}

        cand_specs, cand_details, slot_owner = _instantiate(cand_resolved, v_bias)
        bulk_specs, _, _ = _instantiate(bulk_resolved, v_bias)
        result = greedy_decap_select(
            cand_specs, z_target, freqs, budget,  # type: ignore[arg-type]
            baseline_vrm=vrm, baseline_caps=bulk_specs,
        )
        selected_out: list[dict[str, Any]] = []
        for slot, spec in zip(result.selected_indices, result.selected, strict=True):
            owner = slot_owner[slot]
            meta = cand_details[owner]
            selected_out.append({
                "slot": int(slot),
                "part_id": meta["part_id"],
                "part": spec.part,
                "c_f": spec.c_f,
                "esr_ohm": spec.esr_ohm,
                "esl_h": spec.esl_h,
                "mount_l_h": spec.mount_l_h,
                "cost": spec.cost,
                "derating": meta["derating"],
            })
        with np.errstate(divide="ignore", invalid="ignore"):
            margin = 20.0 * np.log10(result.z_target / np.abs(result.z_profile))
        finite = np.isfinite(margin)
        worst = None
        if bool(np.any(finite)):
            idx = int(np.argmin(np.where(finite, margin, np.inf)))
            worst = {
                "f_hz": float(freqs[idx]),  # type: ignore[index]
                "margin_db": float(margin[idx]),
                "z_ohm": float(np.abs(result.z_profile[idx])),
                "z_target_ohm": float(result.z_target[idx]),
            }
        return {
            "ok": True,
            "schema_version": PDN_SERVICE_SCHEMA_VERSION,
            "feasible": result.feasible,
            "infeasible": result.infeasible,
            "n_selected": result.n_selected,
            "total_cost": result.total_cost,
            "budget": result.budget,
            "excess": result.excess,
            "selected": selected_out,
            "f_hz": freqs.tolist(),  # type: ignore[union-attr]
            "z_mag_ohm": _float_list(np.abs(result.z_profile)),
            "z_target_ohm": result.z_target.tolist(),
            "margin_db": _float_list(margin),
            "worst_margin": worst,
            "candidate_details": cand_details,
            "n_candidate_slots": len(cand_specs),
            "v_bias_v": v_bias,
        }
    except (KeyError, TypeError, ValueError, OSError, yaml.YAMLError) as exc:
        return {"ok": False, "schema_version": PDN_SERVICE_SCHEMA_VERSION,
                "errors": [str(exc)]}


def pdn_gate(payload: dict[str, Any]) -> dict[str, Any]:
    """KiCad AC-PI 门（fab DFM 门同框架薄面；verdict 三值 PASS/FAIL/UNKNOWN）。

    判据预声明见模块 docstring（R1 腔模带内筛查 / R2 安装避让（λ_eff 在
    关注带上缘评估）/ R3 可选 Z 谱裕量门；plane/interest_band 缺 → UNKNOWN）。
    plane 的 a_m/b_m 显式走参数——自动来源见 :func:`pdn_power_pairs`
    （.kicad_pcb 电源对提取，pdn_plane_inputs 可直接作 plane 候选）。

    Args:
        payload: plane({a_m,b_m,er,m_max?,n_max?})、interest_band({f_lo_hz,
            f_hi_hz})、mount_positions([{x_m,y_m},...])、
            mount_threshold_frac（缺省 0.5）、impedance（可选，内嵌
            pdn_analyze 同款 schema：decaps/vrm/bulk/target/频率轴/v_bias_v）、
            library_path 可选。

    Returns:
        dict: {ok, gate, verdict, violations, modes_in_band, cavity_modes,
        mount_clearances, impedance_gate, unknown_reason, ...}
    """
    try:
        payload = _require_payload_dict(payload)
        errors: list[str] = []
        plane = _build_plane(payload.get("plane"), errors)
        band_raw = payload.get("interest_band")
        f_lo = f_hi = None
        if band_raw is not None:
            if not isinstance(band_raw, dict):
                errors.append(f"interest_band 必须是对象 {{f_lo_hz, f_hi_hz}}，实际 {type(band_raw).__name__}")
            else:
                f_lo = _num(band_raw.get("f_lo_hz"), "interest_band.f_lo_hz", errors, positive=True)
                f_hi = _num(band_raw.get("f_hi_hz"), "interest_band.f_hi_hz", errors, positive=True)
                if f_lo is not None and f_hi is not None and f_hi <= f_lo:
                    errors.append(f"interest_band.f_hi_hz 必须大于 f_lo_hz，实际 {f_hi!r} ≤ {f_lo!r}")
        threshold = _num(payload.get("mount_threshold_frac", 0.5),
                         "mount_threshold_frac", errors, positive=True)
        positions: list[tuple[float, float]] = []
        raw_positions = payload.get("mount_positions")
        if raw_positions is not None:
            if not isinstance(raw_positions, list):
                errors.append("mount_positions 必须是 [{x_m, y_m}, ...] 列表")
            else:
                for i, pos in enumerate(raw_positions):
                    if not isinstance(pos, dict):
                        errors.append(f"mount_positions[{i}] 必须是对象 {{x_m, y_m}}")
                        continue
                    x = _num(pos.get("x_m"), f"mount_positions[{i}].x_m", errors)
                    y = _num(pos.get("y_m"), f"mount_positions[{i}].y_m", errors)
                    if x is not None and y is not None:
                        positions.append((x, y))
        # threshold is None 必然伴随 error 已入列（_num 契约）——判空仅为类型
        # 收窄，运行时行为与 `if errors` 完全等价。
        if errors or threshold is None:
            return {"ok": False, "gate": PDN_GATE_NAME,
                    "schema_version": PDN_SERVICE_SCHEMA_VERSION, "errors": errors}

        violations: list[dict[str, Any]] = []
        cavity_modes_out: list[dict[str, Any]] | None = None
        modes_in_band: list[dict[str, Any]] = []
        mount_clearances: list[dict[str, Any]] = []

        if plane is not None and f_lo is not None and f_hi is not None:
            modes = plane_cavity_modes(plane["a_m"], plane["b_m"], plane["er"],
                                       plane["m_max"], plane["n_max"])
            cavity_modes_out = []
            for mode in modes:
                in_band = bool(f_lo <= mode.f_hz <= f_hi)
                cavity_modes_out.append({"m": mode.m, "n": mode.n, "f_hz": mode.f_hz, "in_band": in_band})
                if in_band:
                    modes_in_band.append({"m": mode.m, "n": mode.n, "f_hz": mode.f_hz})
            # band_mode 是 modes_in_band 里的 dict（非 CavityMode 对象）——
            # 独立命名避免遮蔽上一循环的 mode 对象绑定（types only）。
            for band_mode in modes_in_band:
                violations.append({
                    "code": "cavity_mode_in_band",
                    "detail": f"腔模 ({band_mode['m']},{band_mode['n']}) f={band_mode['f_hz']:.6g} Hz 落入关注带 "
                              f"[{f_lo:.6g}, {f_hi:.6g}] Hz（保守筛查口径：带内腔模即风险）",
                })
                for pos_idx, (x, y) in enumerate(positions):
                    clearance = mount_position_clearance(
                        x, y, plane["a_m"], plane["b_m"], plane["er"],
                        band_mode["m"], band_mode["n"], f_hz=f_hi, threshold_frac=threshold,
                    )
                    row = {
                        "position_index": pos_idx,
                        "x_m": x,
                        "y_m": y,
                        "mode_m": band_mode["m"],
                        "mode_n": band_mode["n"],
                        "f_eval_hz": f_hi,
                        "verdict": clearance.verdict,
                        "distance_m": clearance.distance_m,
                        "required_m": clearance.required_m,
                        "margin_m": clearance.margin_m,
                    }
                    mount_clearances.append(row)
                    if clearance.verdict != "clear":
                        violations.append({
                            "code": "mount_too_close",
                            "detail": f"安装位 #{pos_idx} ({x:.6g},{y:.6g}) m 距腔模 "
                                      f"({band_mode['m']},{band_mode['n']}) 最近波腹 {clearance.distance_m:.6g} m "
                                      f"< 要求 {clearance.required_m:.6g} m（λ_eff 在带缘 {f_hi:.6g} Hz 评估）",
                        })

        impedance_gate: dict[str, Any] | None = None
        if payload.get("impedance") is not None:
            sub = dict(payload["impedance"])
            sub_errors: list[str] = []
            sub_core = _analyze_network(sub, sub_errors)
            if sub_core is None:
                impedance_gate = {"ok": False, "errors": sub_errors}
            else:
                worst = sub_core["worst_margin"]
                impedance_gate = {
                    "ok": True,
                    "worst_margin": worst,
                    "n_points": int(sub_core["f_hz"].size),
                    "anti_resonances": sub_core["anti_resonances"],
                    "branch_details": sub_core["branch_details"],
                }
                if worst is not None and float(worst["margin_db"]) < 0.0:
                    violations.append({
                        "code": "impedance_exceeds_target",
                        "detail": f"Z 谱最差裕量 {worst['margin_db']:.4f} dB @ {worst['f_hz']:.6g} Hz "
                                  f"（|Z|={worst['z_ohm']:.6g} Ω > Z_target={worst['z_target_ohm']:.6g} Ω）",
                    })

        unknown_reason: str | None = None
        if plane is None:
            unknown_reason = ("plane 缺失（a_m/b_m 由调用方显式给；可经 pdn_power_pairs"
                              " 从 .kicad_pcb 电源对提取获得候选），腔模/避让筛查无法执行")
        elif f_lo is None or f_hi is None:
            unknown_reason = "interest_band 缺失（f_mn vs 关注带比较无带可比）"
        elif impedance_gate is not None and not impedance_gate.get("ok"):
            # 审查轨 C P1-4：请求了 R3 子门但子分析失败（如库缺件）——
            # "要求了但没跑成"按 UNKNOWN 如实，不得静默 PASS（fail-closed）
            unknown_reason = ("impedance 子门分析失败: "
                              + "; ".join(impedance_gate.get("errors", [])[:3]))
        verdict = "UNKNOWN" if unknown_reason is not None else ("FAIL" if violations else "PASS")
        return ok_envelope(
            gate=PDN_GATE_NAME,
            schema_version=PDN_SERVICE_SCHEMA_VERSION,
            verdict=verdict,
            unknown_reason=unknown_reason,
            violations=violations,
            n_violations=len(violations),
            plane=plane,
            interest_band=None if f_lo is None or f_hi is None else {"f_lo_hz": f_lo, "f_hi_hz": f_hi},
            cavity_modes=cavity_modes_out,
            modes_in_band=modes_in_band,
            mount_positions=[{"x_m": x, "y_m": y} for x, y in positions],
            mount_threshold_frac=threshold,
            mount_clearances=mount_clearances,
            impedance_gate=impedance_gate,
        )
    except (KeyError, TypeError, ValueError, OSError, yaml.YAMLError) as exc:
        return {"ok": False, "gate": PDN_GATE_NAME,
                "schema_version": PDN_SERVICE_SCHEMA_VERSION, "errors": [str(exc)]}


def pdn_power_pairs(payload: dict[str, Any]) -> dict[str, Any]:
    """KiCad 电源对自动提取（B5-5；JSON 进出，adapters/kicad_power_pairs 薄壳）。

    语义（pdn 参数路径视角，adapter docstring 有全文）：.kicad_pcb 文本
    s-expression 解析（不走 pcbnew 子进程，全离线）→
    1. ``pdn_plane_inputs[].{a_m, b_m, er}``：同层电源/地 zone bbox 交集的
       平面偶 span（米制+stackup er）——pdn_analyze/pdn_gate ``plane``
       参数候选；
    2. ``via_pairs[].spacing_mm``：电源/地过孔最近邻对心距——
       core.pdn.mount_inductance 的 ``via_pair_spacing_m`` 输入；
    3. ``decap_clusters[]``：焊盘桥接电源/地两网的封装按轨聚簇（refs/
       质心/逐颗位置）——去耦电容簇最小面（B5-5 剩余件补齐）。

    Args:
        payload: pcb_path（必给，.kicad_pcb 路径）、power_nets/ground_nets
            （可选名单，给出时替换启发式分类）、max_via_pairs（可选正整数，
            明细列表上限；统计量恒为全量）。

    Returns:
        dict: ``{ok, schema_version, pcb_path, nets, counts, plane_pairs,
        via_pairs, via_pair_stats, decap_clusters, pdn_plane_inputs,
        warnings, ...}``；文件缺失/文本坏/实参非法 → ``{ok: False, errors}``。
    """
    try:
        payload = _require_payload_dict(payload)
        errors: list[str] = []
        pcb_path = payload.get("pcb_path")
        if not isinstance(pcb_path, str) or not pcb_path.strip():
            errors.append("pcb_path 必给（.kicad_pcb 文件路径字符串）")
        for name in ("power_nets", "ground_nets"):
            raw = payload.get(name)
            if raw is None:
                continue
            if not isinstance(raw, list) or any(not isinstance(x, str) for x in raw):
                errors.append(f"{name} 须为字符串列表或缺省，实际 {raw!r}")
        max_via_pairs = payload.get("max_via_pairs")
        if max_via_pairs is not None and (not isinstance(max_via_pairs, int)
                                          or isinstance(max_via_pairs, bool)
                                          or max_via_pairs < 1):
            errors.append(f"max_via_pairs 必须为正整数，实际 {max_via_pairs!r}")
        if errors or not isinstance(pcb_path, str):
            # pcb_path 非 str 时 errors 必非空（上方校验已记账）——此处
            # 复判 isinstance 只为 mypy 收窄（AU-2 批：原 #type:ignore
            # 错误码 arg-type 与实报 union-attr 不匹配，按语义收窄替代）。
            return {"ok": False, "schema_version": PDN_SERVICE_SCHEMA_VERSION,
                    "errors": errors}
        result = extract_power_pairs(
            pcb_path.strip(),
            power_nets=payload.get("power_nets"),
            ground_nets=payload.get("ground_nets"),
            max_via_pairs=max_via_pairs,
        )
        result.setdefault("schema_version", PDN_SERVICE_SCHEMA_VERSION)
        return result
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return {"ok": False, "schema_version": PDN_SERVICE_SCHEMA_VERSION,
                "errors": [str(exc)]}
