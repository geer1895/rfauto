"""求解健康度体检内核。

把历史踩坑教训内核化为每 run 确定性体检——LLM/agent 永不产生物理数字，
本模块全部判据为确定性数值规则，不健康 run 禁入
数据集注册表（护数据集质量）。

内核化的教训（每条含踩坑编号）：
- #174 激励体积死：能量/传输曲线全零 = 激励体积死（零宽盒/盒边未进网格）
- #195 cost 退化常数：窄带谐振器件带内 max 统计量恒定 → cost 无区分度
- #152 CFL/网格塌缩：openEMS 时间步塌缩 6 个量级（近重合网格线）
- 1.0491 探针窗异常：CalcPort β/εeff 带常数归一化偏移会互相矛盾
- 无源性/互易性：照 core/objectives.py SpecEvaluator.check_passivity /
  check_reciprocity 口径（|S|≤1.01、max|Sij−Sji|<0.01）；互易性只对
  **两向都独立已测**的端口对比对——openEMS 单激励 sparams.csv 部分矩阵
  （只测 S11/S21[/S31/S23]，S12/S13 置零）不构成互易证据，按 UNKNOWN 不
  拦（6 个真机校准 run 曾被"置零元素 vs 已测元素"
  假阳性拦住的修正；掩码由服务层解析 csv 时给出，Touchstone 全矩阵不变）
- 非物理增益：照 SpecEvaluator.sanity_check 插损口径（全带宽 |S21| dB 均值
  > 0.5 dB 物理上不可能）
- 功率守恒闭合：损耗图积分 ∫q dV vs S 参数耗散
  功率 P_in·(1−Σ|S_ij|²)，3% 门与 non_passive 判定同源
  core/loss_density.power_conservation_check；rel>3% 只 WARN（dump 覆盖
  不全/辐射是诊断不是病，防误杀既有归档 run 进 dataset health_gate），
  non_passive 才 FAIL。
- 热合理性（判据原文 + #233）：热源非负；正热源下 ΔT==0
  是 #233 Elmer 恒温陷阱；T_max 超材料额定是稳态 7215°C 非物理族；
  ΔT/(P·R_th) 出 [0.1, 10] 量级窗只 WARN。

设计约束：
- 纯函数内核，输入为已加载的数据结构（skrf.Network 或 S 矩阵+频率轴、
  cost 序列、可选 provenance dict）；skrf 按 SpecEvaluator 惯例不做顶层
  import——network 参数 duck-type 取 .s 与 .frequency.f。
- 每个检查独立 try/except：单项异常 → 该项 UNKNOWN，不传染（#105 观测
  代码不得成为业务故障点）。
- 产物缺失 → UNKNOWN，不误报（如 #152 的 timestep 字段缺失）。
- verdict 规则：任一 FAIL → unhealthy；无 FAIL 有 WARN → suspect；
  否则 healthy。ok = (verdict == "healthy")，即 suspect 也视为
  "不可采信"（供注册表门禁使用；报告里 verdict 保留细分）。

报告结构（JSON 友好）::
    {
      "ok": bool,
      "verdict": "healthy" | "unhealthy" | "suspect",
      "factors": [
        {"factor": str, "status": "PASS|WARN|FAIL|UNKNOWN",
         "detail": str, "lesson_ref": str, "evidence": {...}},
        ...
      ],
    }
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from rfauto.core.loss_density import DEFAULT_CLOSURE_TOLERANCE

# ---------------------------------------------------------------------------
# 状态与 verdict 常量
# ---------------------------------------------------------------------------

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

VERDICT_HEALTHY = "healthy"
VERDICT_UNHEALTHY = "unhealthy"
VERDICT_SUSPECT = "suspect"

# 教训编号——写进每条 factor，保证报告可回溯到踩坑原文
LESSON_EXCITATION_DEAD = "#174"
LESSON_COST_DEGENERATE = "#195"
LESSON_TIMESTEP_COLLAPSE = "#152"
LESSON_PROBE_SCALE = "1.0491 探针窗（多模态几何审计）"
LESSON_PASSIVITY = "SpecEvaluator.check_passivity"
LESSON_RECIPROCITY = "SpecEvaluator.check_reciprocity"
LESSON_UNPHYSICAL_GAIN = "SpecEvaluator.sanity_check 插损口径"
LESSON_POWER_BALANCE = "core/loss_density.power_conservation_check（Jackson §6.9 / Pozar §1.6）"
LESSON_THERMAL = "热合理性判据 + #233 Elmer 恒温陷阱 + 稳态 7215°C 族"

# ---------------------------------------------------------------------------
# 判据阈值（与踩坑原文数值一致）
# ---------------------------------------------------------------------------

# #174：全带宽透射峰值线性幅值 < 1e-6 = 激励体积死（数值零，非弱耦合）
EXCITATION_DEAD_FLOOR = 1e-6
# #195：trial 数 ≥5 且（unique ≤1 或方差 <1e-12）→ cost 退化常数
COST_DEGENERATE_MIN_TRIALS = 5
COST_DEGENERATE_VAR_FLOOR = 1e-12
# #152：同 run 多条 timestep 记录 min/max 比 <1e-3 → 时间步塌缩 6 个量级
TIMESTEP_COLLAPSE_RATIO = 1e-3
# 1.0491：任两端口 εeff 比值落在 1.04±0.01 窗口 → 疑似归一化偏移
PROBE_SCALE_CENTER = 1.04
PROBE_SCALE_HALF_WIDTH = 0.01
# 无源性容差 1%（SpecEvaluator.check_passivity 同款）
PASSIVITY_TOLERANCE = 1.01
# 互易性容差 0.01 线性（SpecEvaluator.check_reciprocity 同款）
RECIPROCITY_TOLERANCE = 0.01
# 全带宽透射 dB 均值 >0.5 dB = 无源网络出现增益（sanity_check 同款）
UNPHYSICAL_GAIN_MEAN_DB = 0.5
# 功率守恒闭合门：与 core/loss_density.DEFAULT_CLOSURE_TOLERANCE 同源（3%）
POWER_CLOSURE_TOLERANCE = DEFAULT_CLOSURE_TOLERANCE
# 非无源判定（sum|S|^2 > 1 + 1e-9，power_conservation_check 同款浮点余量）
_NON_PASSIVE_EPS = 1e-9
# 热合理性量级窗：ΔT/(P·R_th) 落在 [0.1, 10] 之外 → WARN（诊断量）
THERMAL_MAGNITUDE_WINDOW = (0.1, 10.0)

# factor 键名（供服务层/门禁按名取用）
FACTOR_EXCITATION = "excitation"
FACTOR_COST = "cost_distribution"
FACTOR_TIMESTEP = "timestep"
FACTOR_PROBE_SCALE = "probe_scale"
FACTOR_PASSIVITY = "passivity"
FACTOR_RECIPROCITY = "reciprocity"
FACTOR_GAIN = "gain"
FACTOR_POWER_BALANCE = "power_balance"
FACTOR_THERMAL = "thermal_plausibility"

# 新两因子的输入键（供服务层 dict 组装 / provenance 兜底按名取用）
POWER_BALANCE_INPUT_KEYS = (
    "field_power_w", "incident_power_w", "s_row", "sparams_power_w",
    "reflected_fraction", "tolerance",
)
THERMAL_INPUT_KEYS = (
    "t_max_c", "t_ambient_c", "rise_k", "heat_source_w", "input_power_w",
    "thermal_resistance_k_per_w", "material_rating_c",
)

# S 参数幅值的 log 地板（SpecEvaluator 同款 1e-30，防 log10(0)）
_DB_FLOOR = 1e-30


def _factor(
    factor: str,
    status: str,
    detail: str,
    lesson_ref: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造统一形态的单条体检 factor（JSON 友好）。"""
    item: dict[str, Any] = {
        "factor": factor,
        "status": status,
        "detail": detail,
        "lesson_ref": lesson_ref,
    }
    if evidence:
        item["evidence"] = evidence
    return item


def _unknown(factor: str, detail: str, lesson_ref: str,
             evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """产物缺失/不可判定时的 UNKNOWN 条目（不误报，#152 惯例）。"""
    return _factor(factor, UNKNOWN, detail, lesson_ref, evidence=evidence)


# ---------------------------------------------------------------------------
# 输入归一化
# ---------------------------------------------------------------------------

def _extract_network_arrays(network: Any) -> tuple[np.ndarray, np.ndarray]:
    """从 duck-type 的 skrf.Network 提取 (freq_hz, s_matrix)。

    不 import skrf（SpecEvaluator 惯例）：只读属性 .s 与 .frequency.f。
    """
    s = np.asarray(network.s, dtype=complex)
    freq_hz = np.asarray(network.frequency.f, dtype=float)
    return freq_hz, s


def _normalize_costs(costs: Any) -> np.ndarray:
    """cost 序列归一化为一维 float 数组（剔除 NaN/Inf）。"""
    arr = np.asarray(costs, dtype=float).reshape(-1)
    return arr[np.isfinite(arr)]


def _normalize_timesteps(timestep_values: Any) -> np.ndarray:
    """timestep 记录归一化为一维正 float 数组（剔除 NaN/Inf/非正）。"""
    arr = np.asarray(timestep_values, dtype=float).reshape(-1)
    arr = arr[np.isfinite(arr)]
    return arr[arr > 0]


def _normalize_eps_eff(eps_eff_by_port: Any) -> dict[str, float]:
    """各端口 εeff 归一化为 {port: value}（list → port1..portN，剔除非正）。"""
    out: dict[str, float] = {}
    if isinstance(eps_eff_by_port, dict):
        items = list(eps_eff_by_port.items())
    else:
        arr = np.asarray(eps_eff_by_port, dtype=float).reshape(-1)
        items = [(f"port{i + 1}", v) for i, v in enumerate(arr)]
    for key, val in items:
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if np.isfinite(v) and v > 0:
            out[str(key)] = v
    return out


# ---------------------------------------------------------------------------
# 各检查项（独立函数，由 solve_health_check 统一 try/except 包裹）
# ---------------------------------------------------------------------------

def _check_excitation(freq_hz: np.ndarray | None, s_matrix: np.ndarray | None) -> dict[str, Any]:
    """#174 激励体积死：全带宽全部透射列峰值线性幅值 < 1e-6 → FAIL。

    零激励的数值指纹是"整条曲线精确为零"（零宽盒/盒边未进网格），
    弱耦合不会低到 1e-6 以下。单端口 run 无透射列时退化为检查 |S11|：
    全零 S11 同样是激励死的指纹。
    """
    if s_matrix is None or s_matrix.size == 0:
        return _unknown(FACTOR_EXCITATION, "S 参数缺失，无法判定激励是否死", LESSON_EXCITATION_DEAD)
    s = np.asarray(s_matrix, dtype=complex)
    n_ports = s.shape[1]
    if n_ports > 1:
        off_diag = ~np.eye(n_ports, dtype=bool)
        mags = np.abs(s[:, off_diag])
        target = "全部透射列"
    else:
        mags = np.abs(s[:, 0, 0]).reshape(-1, 1)
        target = "|S11|（单端口无透射列，退化口径）"
    # finite 掩模（全 NaN 时 np.max 得 NaN，"NaN < 阈值"恒
    # False → 假 PASS 穿透门禁；openEMS 非收敛 CSV 落 nan 是现实场景）
    finite = mags[np.isfinite(mags)]
    if finite.size == 0:
        return _unknown(
            FACTOR_EXCITATION,
            "透射幅值全为非有限值（NaN/Inf），无法判定激励状态",
            LESSON_EXCITATION_DEAD)
    peak = float(np.max(finite))
    if peak < EXCITATION_DEAD_FLOOR:
        return _factor(
            FACTOR_EXCITATION, FAIL,
            f"{target}全带宽峰值 {peak:.3e} < {EXCITATION_DEAD_FLOOR:.0e}：激励体积死"
            "（零宽盒/盒边未进网格，先修建模勿校准）",
            LESSON_EXCITATION_DEAD,
            evidence={"peak_transmission": peak, "n_ports": int(n_ports)},
        )
    return _factor(
        FACTOR_EXCITATION, PASS,
        f"{target}全带宽峰值 {peak:.4g} ≥ {EXCITATION_DEAD_FLOOR:.0e}，激励非零",
        LESSON_EXCITATION_DEAD,
        evidence={"peak_transmission": peak, "n_ports": int(n_ports)},
    )


def _check_cost(costs: Any) -> dict[str, Any]:
    """#195 cost 退化常数：unique ≤1 或方差 <1e-12 且 trial ≥5 → FAIL。

    窄带谐振器件带内 max 统计量恒定的陷阱——cost 无区分度意味着优化
    循环在盲走（历史上 47 样本批次的代价教训）。
    """
    if costs is None:
        return _unknown(FACTOR_COST, "cost 序列缺失，无法判定分布", LESSON_COST_DEGENERATE)
    arr = _normalize_costs(costs)
    n = int(arr.size)
    if n < COST_DEGENERATE_MIN_TRIALS:
        return _unknown(
            FACTOR_COST,
            f"有效 trial 数 {n} < {COST_DEGENERATE_MIN_TRIALS}，样本不足以判定退化",
            LESSON_COST_DEGENERATE,
            evidence={"n_trials": n},
        )
    n_unique = int(np.unique(arr).size)
    var = float(np.var(arr))
    degenerate = n_unique <= 1 or var < COST_DEGENERATE_VAR_FLOOR
    ev = {"n_trials": n, "n_unique": n_unique, "variance": var}
    if degenerate:
        return _factor(
            FACTOR_COST, FAIL,
            f"cost 序列退化常数（{n} 个 trial，unique={n_unique}，方差={var:.3e} <"
            f" {COST_DEGENERATE_VAR_FLOOR:.0e}）：优化无区分度，疑带内常数统计量陷阱",
            LESSON_COST_DEGENERATE,
            evidence=ev,
        )
    return _factor(
        FACTOR_COST, PASS,
        f"cost 序列有区分度（{n} 个 trial，unique={n_unique}，方差={var:.3e}）",
        LESSON_COST_DEGENERATE,
        evidence=ev,
    )


def _check_timestep(timestep_values: Any) -> dict[str, Any]:
    """#152 CFL/网格塌缩：min/max 比 < 1e-3 → FAIL；字段缺失 → UNKNOWN 不误报。

    openEMS 近重合网格线使 CFL 时间步塌缩 6 个量级，症状是 CalcPort
    IndexError 而非网格报错——同 run 多次激励的 timestep 应同量级。
    """
    if timestep_values is None:
        return _unknown(
            FACTOR_TIMESTEP,
            "无 timestep 记录（非 openEMS/FDTD 或日志缺失），按 #152 惯例不误报",
            LESSON_TIMESTEP_COLLAPSE,
        )
    arr = _normalize_timesteps(timestep_values)
    n = int(arr.size)
    if n < 2:
        return _unknown(
            FACTOR_TIMESTEP,
            f"timestep 记录仅 {n} 条，无法比较 min/max 比",
            LESSON_TIMESTEP_COLLAPSE,
            evidence={"n_records": n},
        )
    ratio = float(np.min(arr) / np.max(arr))
    ev = {"n_records": n, "min_s": float(np.min(arr)), "max_s": float(np.max(arr)), "min_max_ratio": ratio}
    if ratio < TIMESTEP_COLLAPSE_RATIO:
        return _factor(
            FACTOR_TIMESTEP, FAIL,
            f"timestep min/max 比 {ratio:.3e} < {TIMESTEP_COLLAPSE_RATIO:.0e}："
            "CFL 时间步塌缩（疑近重合网格线，最小间距守卫未生效）",
            LESSON_TIMESTEP_COLLAPSE,
            evidence=ev,
        )
    return _factor(
        FACTOR_TIMESTEP, PASS,
        f"timestep min/max 比 {ratio:.4g} 正常（{n} 条记录）",
        LESSON_TIMESTEP_COLLAPSE,
        evidence=ev,
    )


def _check_probe_scale(eps_eff_by_port: Any, mirror_symmetric: bool | None) -> dict[str, Any]:
    """1.0491 探针窗：任两端口 εeff 比值落在 1.04±0.01 → WARN（诊断量不 FAIL）。

    CalcPort β/εeff 提取若带常数归一化偏移，各端口提取值会互相矛盾且
    恰好差一个常数因子——镜像对称声明（mirror_symmetric）可解释的除外。
    """
    if eps_eff_by_port is None:
        return _unknown(
            FACTOR_PROBE_SCALE,
            "无各端口 εeff 提取记录（port_beta 产物缺失），不评估探针窗",
            LESSON_PROBE_SCALE,
        )
    eps = _normalize_eps_eff(eps_eff_by_port)
    if len(eps) < 2:
        return _unknown(
            FACTOR_PROBE_SCALE,
            f"有效端口 εeff 仅 {len(eps)} 个，无法做两两比值",
            LESSON_PROBE_SCALE,
            evidence={"eps_eff": eps},
        )
    keys = sorted(eps)
    suspicious: list[dict[str, float]] = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = eps[keys[i]], eps[keys[j]]
            ratio = max(a, b) / min(a, b)
            if PROBE_SCALE_CENTER - PROBE_SCALE_HALF_WIDTH <= ratio <= PROBE_SCALE_CENTER + PROBE_SCALE_HALF_WIDTH:
                suspicious.append({"port_a": keys[i], "port_b": keys[j], "ratio": ratio})
    ev: dict[str, Any] = {"eps_eff": eps, "suspicious_pairs": suspicious}
    if not suspicious:
        return _factor(
            FACTOR_PROBE_SCALE, PASS,
            "各端口 εeff 两两比值均不在 1.04±0.01 窗口",
            LESSON_PROBE_SCALE,
            evidence=ev,
        )
    if mirror_symmetric is True:
        return _factor(
            FACTOR_PROBE_SCALE, PASS,
            "端口 εeff 比值落在 1.04±0.01 窗口，但 run 声明镜像对称，可由结构解释",
            LESSON_PROBE_SCALE,
            evidence=ev,
        )
    detail = "；".join(f"{p['port_a']}/{p['port_b']} 比值 {p['ratio']:.4f}" for p in suspicious)
    note = "" if mirror_symmetric is False else "（未声明对称性）"
    return _factor(
        FACTOR_PROBE_SCALE, WARN,
        f"端口 εeff 比值落入 1.04±0.01 探针窗{note}：{detail}——疑 CalcPort 归一化偏移"
        "（诊断量，不 FAIL，须人工核对端口提取链）",
        LESSON_PROBE_SCALE,
        evidence=ev,
    )


def _check_passivity(s_matrix: np.ndarray | None) -> dict[str, Any]:
    """无源性：max|S| > 1.01 → FAIL（SpecEvaluator.check_passivity 同款口径）。"""
    if s_matrix is None or s_matrix.size == 0:
        return _unknown(FACTOR_PASSIVITY, "S 参数缺失，无法校验无源性", LESSON_PASSIVITY)
    mags = np.abs(np.asarray(s_matrix, dtype=complex))
    finite = mags[np.isfinite(mags)]
    if finite.size == 0:
        return _unknown(FACTOR_PASSIVITY, "S 参数全为非有限值，无法校验无源性", LESSON_PASSIVITY)
    max_s = float(np.max(finite))
    if max_s > PASSIVITY_TOLERANCE:
        return _factor(
            FACTOR_PASSIVITY, FAIL,
            f"max|S|={max_s:.4f} > {PASSIVITY_TOLERANCE}：无源性违背（无源网络 |S|≤1）",
            LESSON_PASSIVITY,
            evidence={"max_abs_s": max_s},
        )
    return _factor(
        FACTOR_PASSIVITY, PASS,
        f"max|S|={max_s:.4f} ≤ {PASSIVITY_TOLERANCE}（1% 容差，SpecEvaluator 口径）",
        LESSON_PASSIVITY,
        evidence={"max_abs_s": max_s},
    )


def _normalize_measured_mask(
    measured_mask: Any, n_ports: int,
) -> np.ndarray | None:
    """已测掩码归一化为 (n_ports, n_ports) bool；None/形状不符 → None（=全矩阵已测）。

    形状不符时宁可回退到全矩阵口径也不静默按"全未测"处理——前者最多
    多报一条 FAIL 让人来看，后者会把真互易破坏放过去。
    """
    if measured_mask is None:
        return None
    try:
        mask = np.asarray(measured_mask, dtype=bool)
    except (TypeError, ValueError):
        return None
    if mask.shape != (n_ports, n_ports):
        return None
    return mask


def _check_reciprocity(
    s_matrix: np.ndarray | None,
    measured_mask: Any | None = None,
) -> dict[str, Any]:
    """互易性：max|Sij−Sji| ≥ 0.01 → FAIL（SpecEvaluator.check_reciprocity 口径，
    从 (0,1)/(1,0) 推广到全部 i<j 端口对；单端口不适用按 PASS）。

    measured_mask（可选，(n_ports, n_ports) bool，True=该元素由独立测量得到）：
    部分 S 矩阵（openEMS 单激励 sparams.csv 只测 S11/S21[/S31/S23]，其余
    元素置零或按互易补齐）**不构成互易证据**——只有 (i,j) 与 (j,i) 均独立
    已测的端口对才参与比对；一对都没有 → UNKNOWN（不是 PASS 也不是 FAIL）。
    掩码缺省 = 全矩阵已测（Touchstone 全矩阵路径行为不变）。阈值语义不改：
    已测对上的真互易破坏仍按 0.01 拦。
    """
    if s_matrix is None or s_matrix.size == 0:
        return _unknown(FACTOR_RECIPROCITY, "S 参数缺失，无法校验互易性", LESSON_RECIPROCITY)
    s = np.asarray(s_matrix, dtype=complex)
    n_ports = s.shape[1]
    if n_ports < 2:
        return _factor(
            FACTOR_RECIPROCITY, PASS,
            "单端口网络不适用互易性（SpecEvaluator 口径）",
            LESSON_RECIPROCITY,
            evidence={"n_ports": int(n_ports)},
        )
    mask = _normalize_measured_mask(measured_mask, n_ports)
    n_pairs_total = n_ports * (n_ports - 1) // 2
    worst = 0.0
    n_finite_pairs = 0
    n_measured_pairs = 0
    unmeasured_pairs: list[list[int]] = []
    for i in range(n_ports):
        for j in range(i + 1, n_ports):
            if mask is not None and not (bool(mask[i, j]) and bool(mask[j, i])):
                unmeasured_pairs.append([i, j])
                continue  # 部分矩阵：未独立测得的对称对不是互易证据
            n_measured_pairs += 1
            diff = np.abs(s[:, i, j] - s[:, j, i])
            diff = diff[np.isfinite(diff)]
            if diff.size:
                n_finite_pairs += 1
                worst = max(worst, float(np.max(diff)))
    evidence: dict[str, Any] = {"n_ports": int(n_ports)}
    if mask is not None:
        evidence["partial_matrix"] = True
        evidence["n_measured_pairs"] = int(n_measured_pairs)
        evidence["n_pairs_total"] = int(n_pairs_total)
        evidence["unmeasured_pairs"] = unmeasured_pairs
    if mask is not None and n_measured_pairs == 0:
        # 单激励部分矩阵：没有任何一对 (i,j)/(j,i) 都独立测得 → 无证据，
        # 如实 UNKNOWN（既不凑 PASS，也不拿置零元素冒充违背，#122）
        return _unknown(
            FACTOR_RECIPROCITY,
            f"部分 S 矩阵（{n_ports} 端口，0/{n_pairs_total} 对称对独立已测）：单激励"
            "产物不构成互易证据，不判定",
            LESSON_RECIPROCITY, evidence=evidence)
    if n_finite_pairs == 0:
        # 全 NaN 时 worst 恒 0 → 假 PASS：退化为 UNKNOWN
        return _unknown(
            FACTOR_RECIPROCITY,
            "互易性差分全为非有限值，无法校验",
            LESSON_RECIPROCITY, evidence=evidence)
    evidence["max_asym"] = worst
    scope = (f"（{n_measured_pairs}/{n_pairs_total} 已测对称对）"
             if mask is not None else "")
    if worst >= RECIPROCITY_TOLERANCE:
        return _factor(
            FACTOR_RECIPROCITY, FAIL,
            f"max|Sij−Sji|={worst:.4f} ≥ {RECIPROCITY_TOLERANCE}：互易性违背"
            f"（无源互易媒质必满足 Sij=Sji）{scope}",
            LESSON_RECIPROCITY,
            evidence=evidence,
        )
    return _factor(
        FACTOR_RECIPROCITY, PASS,
        f"max|Sij−Sji|={worst:.2e} < {RECIPROCITY_TOLERANCE}（SpecEvaluator 口径）{scope}",
        LESSON_RECIPROCITY,
        evidence=evidence,
    )


def _check_gain(freq_hz: np.ndarray | None, s_matrix: np.ndarray | None) -> dict[str, Any]:
    """非物理增益：全带宽透射 dB 均值 > 0.5 dB → FAIL。

    SpecEvaluator.sanity_check 插损口径（对无源网络均值 S21>0.5 dB 判
    物理不可能）；此处输入是裸 S 矩阵而非 objectives，故独立实现同族
    规则。统计量取全部透射对均值 dB 的最大者——地板方向只会把可疑
    判成 PASS（漏报），不会把健康判成 FAIL（误报），对体检器是保守的。
    """
    if s_matrix is None or s_matrix.size == 0:
        return _unknown(FACTOR_GAIN, "S 参数缺失，无法校验增益", LESSON_UNPHYSICAL_GAIN)
    s = np.asarray(s_matrix, dtype=complex)
    n_ports = s.shape[1]
    if n_ports < 2:
        return _unknown(FACTOR_GAIN, "单端口无透射通道，增益检查不适用", LESSON_UNPHYSICAL_GAIN)
    worst_mean_db = -np.inf
    worst_pair: tuple[int, int] | None = None
    for i in range(n_ports):
        for j in range(n_ports):
            if i == j:
                continue
            sij = s[:, i, j]
            sij = sij[np.isfinite(sij)]
            if sij.size == 0:
                continue  # 全非有限对跳过；部分 NaN 过滤后再求均值（混 NaN 均值=NaN 会被静默跳过）
            mean_db = float(np.mean(20 * np.log10(np.abs(sij) + _DB_FLOOR)))
            if mean_db > worst_mean_db:
                worst_mean_db = mean_db
                worst_pair = (i, j)
    if worst_pair is None:
        return _unknown(FACTOR_GAIN, "无有效透射数据", LESSON_UNPHYSICAL_GAIN)
    ev = {
        "max_mean_transmission_db": worst_mean_db,
        "pair": [int(worst_pair[0]), int(worst_pair[1])],
    }
    if worst_mean_db > UNPHYSICAL_GAIN_MEAN_DB:
        return _factor(
            FACTOR_GAIN, FAIL,
            f"全带宽透射均值 {worst_mean_db:.3f} dB（S{worst_pair[1] + 1}{worst_pair[0] + 1}）"
            f" > {UNPHYSICAL_GAIN_MEAN_DB} dB：无源网络出现增益，非物理",
            LESSON_UNPHYSICAL_GAIN,
            evidence=ev,
        )
    return _factor(
        FACTOR_GAIN, PASS,
        f"全带宽透射均值 {worst_mean_db:.3f} dB ≤ {UNPHYSICAL_GAIN_MEAN_DB} dB，无物理不可能增益",
        LESSON_UNPHYSICAL_GAIN,
        evidence=ev,
    )


# ---------------------------------------------------------------------------
# 新两因子的标量入参归一化（NaN/Inf 守卫：全 NaN 不得假 PASS）
# ---------------------------------------------------------------------------

def _opt_float(value: Any) -> tuple[float | None, bool]:
    """→ (float 或 None, 是否遇到非有限/不可解析值)。None 表示"未提供"。"""
    if value is None:
        return None, False
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None, True
    if not math.isfinite(v):
        return None, True
    return v, False


def _check_power_balance(
    field_power_w: Any = None,
    incident_power_w: Any = None,
    s_row: Sequence[complex] | None = None,
    sparams_power_w: Any = None,
    reflected_fraction: Any = None,
    tolerance: Any = None,
) -> dict[str, Any]:
    """功率守恒闭合：∫q dV（损耗图积分）vs P_in·(1−Σ|S_ij|²)（S 参数耗散功率）。

    口径与 core/loss_density.power_conservation_check 同源（对称相对误差、
    3% 门、non_passive 判定 Σ|S|²>1+1e-9）；此处入参是已积分好的标量，故
    独立复现公式而非传 q 数组。判定：
    - field_power_w 缺失 → UNKNOWN（无 dump_type=29 体 dump 或未解析）；
    - 耗散功率一侧缺失（无 P_in、无 sparams_power_w）→ UNKNOWN 但把已知的
      ∫q dV / Σ|S|² 留在 evidence（归档无 P_in 口径是常态）；
    - non_passive（Σ|S|²>1 → 耗散功率为负）→ FAIL；
    - rel ≤ 3% → PASS；rel > 3% → WARN（dump 覆盖不全/辐射/介损折算是
      诊断不是病，不得把既有归档 run 误杀出 dataset health_gate）；
    - 任一入参非有限 → UNKNOWN（P1-2：NaN 比较恒 False 会假 PASS）。
    """
    tol, tol_bad = _opt_float(tolerance)
    if tol_bad or (tol is not None and not (0.0 < tol < 1.0)):
        return _unknown(FACTOR_POWER_BALANCE, f"tolerance 非法: {tolerance!r}", LESSON_POWER_BALANCE)
    tol = POWER_CLOSURE_TOLERANCE if tol is None else tol

    fp, fp_bad = _opt_float(field_power_w)
    if fp_bad:
        return _unknown(FACTOR_POWER_BALANCE, "field_power_w 非有限值（NaN/Inf），无法闭合", LESSON_POWER_BALANCE)
    if fp is None:
        return _unknown(
            FACTOR_POWER_BALANCE,
            "无损耗图积分功率（未发现 dump_type=29 体 dump 或未解析），不评估功率守恒",
            LESSON_POWER_BALANCE)

    p_in, p_in_bad = _opt_float(incident_power_w)
    sp, sp_bad = _opt_float(sparams_power_w)
    rf, rf_bad = _opt_float(reflected_fraction)
    if p_in_bad or sp_bad or rf_bad:
        return _unknown(
            FACTOR_POWER_BALANCE,
            "incident_power_w / sparams_power_w / reflected_fraction 含非有限值，无法闭合",
            LESSON_POWER_BALANCE, evidence={"field_power_w": fp})

    # Σ|S_ij|²：显式 reflected_fraction 优先，否则由 s_row 算
    if s_row is not None:
        s = np.asarray(s_row, dtype=complex).reshape(-1)
        if s.size == 0 or not bool(np.all(np.isfinite(s.real)) and np.all(np.isfinite(s.imag))):
            return _unknown(
                FACTOR_POWER_BALANCE, "s_row 为空或含 NaN/Inf，无法算 Σ|S_ij|²",
                LESSON_POWER_BALANCE, evidence={"field_power_w": fp})
        s_sum = float(np.sum(np.abs(s) ** 2))
        if rf is None:
            rf = s_sum
    ev: dict[str, Any] = {"field_power_w": fp, "tolerance": tol}
    if rf is not None:
        ev["reflected_fraction"] = rf
    if p_in is not None:
        ev["incident_power_w"] = p_in

    non_passive = False
    if sp is None:
        if p_in is None or rf is None:
            missing = "P_in" if p_in is None else "S 行/Σ|S_ij|²"
            return _unknown(
                FACTOR_POWER_BALANCE,
                f"损耗图积分 {fp:.4e} W 已得，但耗散功率一侧缺 {missing}"
                "（归档无入射功率口径），闭合不判——证据已留",
                LESSON_POWER_BALANCE, evidence=ev)
        if p_in <= 0.0:
            return _unknown(
                FACTOR_POWER_BALANCE, f"incident_power_w={p_in!r} 须 >0",
                LESSON_POWER_BALANCE, evidence=ev)
        non_passive = rf > 1.0 + _NON_PASSIVE_EPS
        sp = p_in * (1.0 - rf)
    elif rf is not None:
        non_passive = rf > 1.0 + _NON_PASSIVE_EPS
    ev["sparams_power_w"] = sp

    scale = max(abs(fp), abs(sp))
    rel = abs(fp - sp) / scale if scale > 0.0 else 0.0
    ev["rel_error"] = rel
    ev["non_passive"] = non_passive
    if non_passive:
        return _factor(
            FACTOR_POWER_BALANCE, FAIL,
            f"Σ|S_ij|²={rf:.4f} > 1：S 行非无源，耗散功率 {sp:.4e} W 为负，功率守恒不可能闭合",
            LESSON_POWER_BALANCE, evidence=ev)
    if rel <= tol:
        return _factor(
            FACTOR_POWER_BALANCE, PASS,
            f"∫q dV={fp:.4e} W vs P_in(1−Σ|S|²)={sp:.4e} W，相对误差 {rel:.3e} ≤ {tol:.0%}，闭合",
            LESSON_POWER_BALANCE, evidence=ev)
    return _factor(
        FACTOR_POWER_BALANCE, WARN,
        f"∫q dV={fp:.4e} W vs P_in(1−Σ|S|²)={sp:.4e} W，相对误差 {rel:.3e} > {tol:.0%}："
        "不闭合（诊断量：dump 覆盖不全/辐射/介损折算均可致，不 FAIL，须人工核对）",
        LESSON_POWER_BALANCE, evidence=ev)


def _check_thermal_plausibility(
    t_max_c: Any = None,
    t_ambient_c: Any = None,
    rise_k: Any = None,
    heat_source_w: Any = None,
    input_power_w: Any = None,
    thermal_resistance_k_per_w: Any = None,
    material_rating_c: Any = None,
) -> dict[str, Any]:
    """热合理性（T_max<材料额定、热源非负；补『温升量级 vs 输入功率』）。

    有效热源功率 P = heat_source_w（缺则 input_power_w）；温升 ΔT = rise_k
    （缺则 t_max_c − t_ambient_c）。判定（FAIL 支配 WARN）：
    - P < 0 → FAIL（热源非负，方案原文）；
    - P > 0 且 ΔT == 0 → FAIL（#233 Elmer HeatSolver 不消费 'Heat Source' 的
      恒温陷阱：给了热源却得常数 T=环境温度）；
    - t_max_c > material_rating_c → FAIL（稳态口径 7215°C 非物理族）；
    - P > 0、R_th > 0、ΔT 可得时 ΔT/(P·R_th) 出 [0.1, 10] → WARN（量级窗，
      诊断量；R_th 缺失不判）；
    - 任一入参非有限 → UNKNOWN（全 NaN 不得假 PASS）；全部缺失 → UNKNOWN。
    """
    raw = {
        "t_max_c": t_max_c, "t_ambient_c": t_ambient_c, "rise_k": rise_k,
        "heat_source_w": heat_source_w, "input_power_w": input_power_w,
        "thermal_resistance_k_per_w": thermal_resistance_k_per_w,
        "material_rating_c": material_rating_c,
    }
    vals: dict[str, float] = {}
    bad: list[str] = []
    for key, value in raw.items():
        v, is_bad = _opt_float(value)
        if is_bad:
            bad.append(key)
        elif v is not None:
            vals[key] = v
    if bad:
        return _unknown(
            FACTOR_THERMAL, f"热入参含非有限/不可解析值: {', '.join(bad)}，不判定",
            LESSON_THERMAL, evidence={"provided": vals} if vals else None)
    if not vals:
        return _unknown(FACTOR_THERMAL, "无热产物（无 T_max/温升/热源记录），不评估热合理性", LESSON_THERMAL)

    t_max = vals.get("t_max_c")
    t_amb = vals.get("t_ambient_c")
    rise = vals.get("rise_k")
    if rise is None and t_max is not None and t_amb is not None:
        rise = t_max - t_amb
    power = vals.get("heat_source_w")
    power_key = "heat_source_w"
    if power is None:
        power = vals.get("input_power_w")
        power_key = "input_power_w"
    r_th = vals.get("thermal_resistance_k_per_w")
    rating = vals.get("material_rating_c")

    ev: dict[str, Any] = dict(vals)
    if rise is not None:
        ev["delta_t_k"] = rise
    if power is not None:
        ev["heat_power_w"] = power
        ev["heat_power_source"] = power_key

    if power is not None and power < 0.0:
        return _factor(
            FACTOR_THERMAL, FAIL,
            f"{power_key}={power:.4g} W < 0：热源为负，非物理（热源非负判据）",
            LESSON_THERMAL, evidence=ev)
    if rating is not None and t_max is not None and t_max > rating:
        return _factor(
            FACTOR_THERMAL, FAIL,
            f"T_max={t_max:.4g}°C > 材料额定 {rating:.4g}°C：超温（稳态 7215°C 非物理族）",
            LESSON_THERMAL, evidence=ev)
    if power is not None and power > 0.0 and rise is not None and rise == 0.0:
        return _factor(
            FACTOR_THERMAL, FAIL,
            f"热源 {power:.4g} W > 0 但温升 ΔT=0：恒温陷阱（#233 Elmer 不消费 'Heat Source'，"
            "须用 'Volumetric Heat Source'）",
            LESSON_THERMAL, evidence=ev)

    checks: list[str] = []
    if rise is not None:
        checks.append(f"ΔT={rise:.4g} K")
    if power is not None:
        checks.append(f"P={power:.4g} W ≥ 0")
    if rating is not None and t_max is not None:
        checks.append(f"T_max={t_max:.4g}°C ≤ 额定 {rating:.4g}°C")
    if power is not None and power > 0.0 and r_th is not None and r_th > 0.0 and rise is not None:
        expected = power * r_th
        ratio = rise / expected
        ev["expected_rise_k"] = expected
        ev["rise_ratio"] = ratio
        lo, hi = THERMAL_MAGNITUDE_WINDOW
        if not (lo <= ratio <= hi):
            return _factor(
                FACTOR_THERMAL, WARN,
                f"ΔT/(P·R_th)={ratio:.3g} 出 [{lo}, {hi}] 量级窗（ΔT={rise:.4g} K vs "
                f"P·R_th={expected:.4g} K）：温升量级与输入功率不符，疑单位/热源/边界错（诊断量，不 FAIL）",
                LESSON_THERMAL, evidence=ev)
        checks.append(f"ΔT/(P·R_th)={ratio:.3g} ∈ [{lo}, {hi}]")
    if not checks:
        return _unknown(
            FACTOR_THERMAL, "热入参不足以判定任何一条（仅 " + ", ".join(sorted(vals)) + "）",
            LESSON_THERMAL, evidence=ev)
    return _factor(
        FACTOR_THERMAL, PASS,
        "热合理性通过：" + "；".join(checks),
        LESSON_THERMAL, evidence=ev)


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

_CHECK_SPEC = (
    (FACTOR_EXCITATION, LESSON_EXCITATION_DEAD),
    (FACTOR_COST, LESSON_COST_DEGENERATE),
    (FACTOR_TIMESTEP, LESSON_TIMESTEP_COLLAPSE),
    (FACTOR_PROBE_SCALE, LESSON_PROBE_SCALE),
    (FACTOR_PASSIVITY, LESSON_PASSIVITY),
    (FACTOR_RECIPROCITY, LESSON_RECIPROCITY),
    (FACTOR_GAIN, LESSON_UNPHYSICAL_GAIN),
    # 追加不重排：消费方（certify_design g11_factors、CLI 表格）按顺序渲染
    (FACTOR_POWER_BALANCE, LESSON_POWER_BALANCE),
    (FACTOR_THERMAL, LESSON_THERMAL),
)


def _pick_inputs(source: Any, keys: Sequence[str]) -> dict[str, Any]:
    """从 dict 里挑出已知键（None 值视为未提供）；非 dict → 空。"""
    if not isinstance(source, dict):
        return {}
    return {k: source[k] for k in keys if k in source and source[k] is not None}


def solve_health_check(
    *,
    network: Any | None = None,
    freq_hz: Any | None = None,
    s_matrix: Any | None = None,
    s_measured_mask: Any | None = None,
    costs: Any | None = None,
    timestep_values: Any | None = None,
    eps_eff_by_port: Any | None = None,
    mirror_symmetric: bool | None = None,
    power_balance_inputs: dict[str, Any] | None = None,
    thermal_inputs: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """求解健康度体检统一入口（纯函数，输入均为已加载数据结构）。

    参数：
        network: 已加载的 skrf.Network（duck-type 取 .s / .frequency.f），
            与 freq_hz+s_matrix 二选一，前者优先。
        freq_hz / s_matrix: 频率轴(Hz) 与 (n_freq, n_ports, n_ports) 复矩阵。
        s_measured_mask: 可选 (n_ports, n_ports) bool，True=该 S 元素由独立
            测量得到（openEMS 单激励 sparams.csv 部分矩阵：未测元素置零/按
            互易补齐者为 False）。只影响互易性因子——仅两向都已测的端口对
            参与比对，一对都没有 → UNKNOWN 而非 FAIL（部分矩阵不构成互易
            证据）。缺省/形状不符 = 全矩阵已测（Touchstone 路径行为不变）。
        costs: 全部 trial 的 cost 序列（#195）。
        timestep_values: 同 run 的 FDTD timestep 记录序列(s)（#152）。
        eps_eff_by_port: 各端口 εeff 提取值 {port: v} 或序列（1.0491）。
        mirror_symmetric: 结构镜像对称声明（True 时探针窗 WARN 降为 PASS）。
        power_balance_inputs: 功率守恒因子入参 dict，键见
            POWER_BALANCE_INPUT_KEYS（field_power_w 必需；incident_power_w +
            s_row/reflected_fraction 或 sparams_power_w 给耗散一侧）。
        thermal_inputs: 热合理性因子入参 dict，键见 THERMAL_INPUT_KEYS
            （t_max_c / t_ambient_c / rise_k / heat_source_w / input_power_w /
            thermal_resistance_k_per_w / material_rating_c）。
        provenance: 可选 provenance dict，可携带键 timestep(s)/timestep_values、
            eps_eff_by_port、mirror_symmetric、costs、power_balance、thermal；
            显式 kwargs 优先。

    返回：见模块 docstring 的报告结构。每项检查独立 try/except，单项
    异常 → 该项 UNKNOWN，不传染（#105）。
    """
    # provenance 兜底（显式 kwargs 优先）
    provenance = provenance or {}
    if timestep_values is None:
        timestep_values = provenance.get("timestep_values", provenance.get("timesteps"))
    if eps_eff_by_port is None:
        eps_eff_by_port = provenance.get("eps_eff_by_port")
    if mirror_symmetric is None:
        ms = provenance.get("mirror_symmetric")
        mirror_symmetric = bool(ms) if ms is not None else None
    if costs is None:
        costs = provenance.get("costs")
    if power_balance_inputs is None:
        power_balance_inputs = provenance.get("power_balance", provenance.get("power_balance_inputs"))
    if thermal_inputs is None:
        thermal_inputs = provenance.get("thermal", provenance.get("thermal_inputs"))
    power_kwargs = _pick_inputs(power_balance_inputs, POWER_BALANCE_INPUT_KEYS)
    thermal_kwargs = _pick_inputs(thermal_inputs, THERMAL_INPUT_KEYS)

    # network 优先于裸数组
    if network is not None:
        try:
            freq_hz, s_matrix = _extract_network_arrays(network)
        except Exception:
            freq_hz, s_matrix = None, None

    s_arr = None
    if s_matrix is not None:
        s_arr = np.asarray(s_matrix, dtype=complex)
    f_arr = None
    if freq_hz is not None:
        try:
            f_arr = np.asarray(freq_hz, dtype=float)
        except (TypeError, ValueError):
            f_arr = None

    runners = {
        FACTOR_EXCITATION: lambda: _check_excitation(f_arr, s_arr),
        FACTOR_COST: lambda: _check_cost(costs),
        FACTOR_TIMESTEP: lambda: _check_timestep(timestep_values),
        FACTOR_PROBE_SCALE: lambda: _check_probe_scale(eps_eff_by_port, mirror_symmetric),
        FACTOR_PASSIVITY: lambda: _check_passivity(s_arr),
        FACTOR_RECIPROCITY: lambda: _check_reciprocity(s_arr, s_measured_mask),
        FACTOR_GAIN: lambda: _check_gain(f_arr, s_arr),
        FACTOR_POWER_BALANCE: lambda: _check_power_balance(**power_kwargs),
        FACTOR_THERMAL: lambda: _check_thermal_plausibility(**thermal_kwargs),
    }

    factors: list[dict[str, Any]] = []
    for name, lesson in _CHECK_SPEC:
        try:
            factors.append(runners[name]())
        except Exception as exc:  # 单项炸 → UNKNOWN，不传染（#105）
            factors.append(_factor(name, UNKNOWN, f"检查项异常: {exc!r}", lesson))

    has_fail = any(f["status"] == FAIL for f in factors)
    has_warn = any(f["status"] == WARN for f in factors)
    verdict = VERDICT_UNHEALTHY if has_fail else (VERDICT_SUSPECT if has_warn else VERDICT_HEALTHY)
    return {
        "ok": verdict == VERDICT_HEALTHY,
        "verdict": verdict,
        "factors": factors,
    }
