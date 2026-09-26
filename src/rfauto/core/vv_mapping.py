"""V&V 20 术语映射层 + u_num 保守上界（DP-12，纯函数，零真机零网络）。

背景（docs/plan_deepdive_specs_20260924.md DP-12 §2/§4/§5；预声明判据
runs/df6_dp12vv/criteria.md 先于动工落盘）：现有判据门（AGREE_*/SPLIT/
UNDECIDED/UNDECIDABLE/FAIL/PARTIAL/UNKNOWN、passivity 旁证）纪律已备但
语言是项目黑话——对外无标准可信度表述。本模块是**唯一翻译层**：

- **不改名现有 verdict、不重写已归档判读**（#325/#326 零改写）——映射是
  附加字段输出（``vv_*`` 前缀），``map_verdict`` 输入串原样保留在
  ``input_verdict``；``apply_mapping`` 返回新 dict 并列注入，绝不原地改。
- V&V 20 口径：E=S−D；u_val=√(u_num²+u_input²+u_D²)；判定 |E|≤U_val=
  k·u_val（k 缺省 2；边界取 ≤ 与现行 gate 口径一致——dev 0.406≤0.5 记
  ok 同款；V&V 20 正文严格 < 与 ≤ 在浮点边界测度零，预声明按 ≤ 执行）。
- u_num 保守上界（最小实现，零新真跑）：ΔS 阶梯细化比 r 不恒定 →
  Richardson 不适用 → **u_num=Fs·max|Δφ_ladder|**（Fs=1.25；饱和合格级
  按 scripts/hfss_interdigital_check.py ``_ladder_saturated`` 同口径：
  相邻级差≤0.2dB 且末两级≤0.1dB 且级数≥2，#335① 勘误节）。增强路径
  （可选，r 恒定时）：观测阶 p=ln[(φ3−φ2)/(φ2−φ1)]/ln r、
  GCI=Fs·|φ2−φ1|/(r^p−1)（Roache/Celik 2008，V&V 20 §4）——留接口
  不强制，#311/#313 网格收敛实验可直接复用。
- **任一分量 unknown→不虚构数值**（u_val=None）：缺省判
  validation_not_attempted（=UNDECIDED 同向）；调用方显式提供已声明的
  历史 U_val 近似（fallback_u_val，如现行 gate_db）时按保守 k=3 消费并
  标记 u_val_source=fallback_declared——两分支均预声明进 schema。
- passivity 物理一致性约束 |S|≤1（限值 1.0）：违反=validation 前置失效
  （preflight_invalid）。各 criteria 的数据健全性带（如 ≤1.02 越界=数据
  坏）是另一语义，在 v2 YAML preflight 分开声明，本模块不混用。

LLM/agent 永不产生物理数字（确定性内核铁律）：本模块只做确定性换算与
判定，全部数值来自调用方传入的证据字段（verdict.json / stage1 判读档 /
v2 YAML 声明值）。

出处：ASME V&V 20-2009(R2021) §4-5（E≡S−D、TSM、k=2）/ NIST V&V 综述 /
NASA GRC Richardson-GCI / Celik 2008 ASME JFE。

消费方（本批）：tests/unit/test_vv_mapping.py（映射+u_num 合成钉）、
tests/unit/test_vv_recast.py（RECAST 历史重放：runs/df5_c3fix/
sentinel_verdict.json 与 runs/hfss_interdigital_check/verdict.json 只读）。
runner/报告面接入=后续批（knowledge/criteria/v2/*.yaml 的
runner_binding: followUp 预声明）。
"""

from __future__ import annotations

import itertools
import math
from copy import deepcopy
from typing import Any

__all__ = [
    "ADJACENT_TOL_DB",
    "FS_CONSERVATIVE",
    "K_CONSERVATIVE",
    "K_STANDARD",
    "LADDER_MIN_LEVELS",
    "LADDER_SATURATION_RULE",
    "LAST_TWO_TOL_DB",
    "PASSIVITY_LIMIT",
    "VV_CONDITIONALLY_VALIDATED",
    "VV_NOT_JUDGED",
    "VV_NOT_VALIDATED",
    "VV_OUT_OF_SCOPE",
    "VV_PREFLIGHT_INVALID",
    "VV_SCHEMA",
    "VV_VALIDATED",
    "VV_VALIDATION_NOT_ATTEMPTED",
    "apply_mapping",
    "budget_conditional",
    "combine_uncertainty",
    "conditional_validated",
    "ladder_saturated",
    "map_verdict",
    "nearest_reference_decision",
    "passivity_preflight",
    "u_num_from_ladder",
    "u_num_gci",
    "validate_claim",
]

#: 输出 schema 标识（随 vv_* 附加字段写入，消费者据此识别）
VV_SCHEMA = "rfauto-vv-mapping/1"

# ── V&V 状态常量（v2 YAML verdict_map 值域 = 这组常量） ─────────────────────
VV_VALIDATED = "validated"
VV_NOT_VALIDATED = "not_validated"
VV_CONDITIONALLY_VALIDATED = "conditionally_validated"
VV_VALIDATION_NOT_ATTEMPTED = "validation_not_attempted"
VV_OUT_OF_SCOPE = "out_of_scope"
VV_NOT_JUDGED = "not_judged"
VV_PREFLIGHT_INVALID = "preflight_invalid"

# ── u_num 保守上界常量（与 _ladder_saturated 同口径，#335① 勘误节） ─────────
FS_CONSERVATIVE = 1.25  #: GCI 缺省安全因子（Roache/Celik 2008）
K_STANDARD = 2.0        #: V&V 20 判定展开因子（U_val=k·u_val）
K_CONSERVATIVE = 3.0    #: 分量缺失走已声明 fallback 时的保守展开因子
ADJACENT_TOL_DB = 0.2   #: 饱和合格级：相邻级差上限
LAST_TWO_TOL_DB = 0.1   #: 饱和合格级：末两级差上限
LADDER_MIN_LEVELS = 2   #: 饱和账最少级数（单点不可验关键标量稳定性）
LADDER_SATURATION_RULE = (
    "相邻级差≤0.2dB 且末两级≤0.1dB 且级数≥2"
    "（#335① 勘误节，scripts/hfss_interdigital_check._ladder_saturated 同口径）"
)
PASSIVITY_LIMIT = 1.0  #: 物理一致性约束 |S|≤1（数据健全性带如 1.02 由 criteria 另行声明）

#: 现行 verdict → V&V 重述映射表（DP-12 §2 表格的可执行形态）。
#: 值 = (vv_status, vv_basis, vv_evidence_fields, vv_notes)
_VERDICT_MAP: dict[str, tuple[str, str, list[str], list[str]]] = {
    "AGREE": (
        VV_VALIDATED,
        "|E|≤gate 且 ≤U_val（对所比对参考 D 该模型成立）",
        ["delta_vs_reference_db", "ladder/final_delta_s（verdict.json）"],
        ["AGREE_* 为项目别名；V&V 词只进报告面"],
    ),
    "PASS": (
        VV_VALIDATED,
        "门全过（项目 PASS 别名，无 U_val 分量式时视为历史 U_val 近似）",
        ["gates 块"],
        [],
    ),
    "CERTIFIED": (
        VV_VALIDATED,
        "证书 rollup 全 PASS（项目别名）",
        ["certificates[].verdict"],
        [],
    ),
    "SPLIT": (
        VV_NOT_VALIDATED,
        "两候选 D 均 |E|>U_val",
        ["双 Δ 值（#350 判向门）"],
        ["model-form 不可辨识（epistemic）"],
    ),
    "UNDECIDED": (
        VV_VALIDATION_NOT_ATTEMPTED,
        "u_num 未收敛（ΔS 阶梯未饱和/无合格收敛解）",
        ["ladder_saturation", "ladder/_eligible（convergence）"],
        ["validation not attempted：非 FAIL、非翻案，数值判读未发生"],
    ),
    "UNDECIDABLE": (
        VV_OUT_OF_SCOPE,
        "域内无 D（gate=None/无配对）",
        ["measured_mask", "作用域分派表"],
        ["out-of-scope：登记不判，非 FAIL（#274/#314）"],
    ),
    "FAIL": (
        VV_NOT_VALIDATED,
        "|E|≥U_val（或证据损坏面 FAIL，#316 方向区分）",
        ["health verdict", "gates 块"],
        [],
    ),
    "PARTIAL": (
        VV_CONDITIONALLY_VALIDATED,
        "子集过+超限注记",
        ["budget/elapsed（哨 1.3× 实例）"],
        ["conditionally validated：结论限注记范围内有效"],
    ),
    "WARN": (
        VV_CONDITIONALLY_VALIDATED,
        "证书 rollup WARN（子集过+注记，项目别名）",
        ["certificates[].verdict"],
        [],
    ),
    "UNKNOWN": (
        VV_NOT_JUDGED,
        "证据缺失",
        ["缺失字段清单"],
        ["not judged：缺失方向『多报』（#316），不冒充 FAIL 也不放行"],
    ),
}

# 前缀匹配表：AGREE_* 族按前缀（AGREE_CIRCUIT/AGREE_SENTINEL/AGREE_OPENEMS…），
# 其余按最长字面前缀（兼容带尾注串的 verdict，如 "FAIL（fail_kind=gates…）"）。
_PREFIX_KEYS = ("AGREE", "CERTIFIED", "UNDECIDABLE", "UNDECIDED", "PARTIAL",
                "UNKNOWN", "SPLIT", "FAIL", "PASS", "WARN")


def _normalize(verdict: str) -> str:
    """verdict 串归一（strip + 大写；None/空 → 空串走 not_judged）。"""
    if not isinstance(verdict, str):
        return ""
    return verdict.strip().upper()


def _lookup(normalized: str) -> tuple[str, str] | None:
    """归一串 → (映射键, 命中方式)。前缀最长优先；无命中返回 None。"""
    for key in _PREFIX_KEYS:
        if normalized.startswith(key):
            return key, "prefix"
    return None


def map_verdict(verdict: str) -> dict[str, Any]:
    """现行 verdict → V&V 20 重述（纯函数；附加字段，不改名不重写）。

    返回 dict（可 json.dumps 并列进 verdict 文件）：

    - ``input_verdict``：输入串 strip 后原样保留（改写禁令的显式证据）；
    - ``vv_schema``：输出标识（VV_SCHEMA）；
    - ``vv_status``：VV_* 状态常量；
    - ``vv_basis``：V&V 判据依据（DP-12 §2 表行）；
    - ``vv_evidence_fields``：证据字段（已有落点）；
    - ``vv_notes``：注记（epistemic/out-of-scope/多报方向等）。

    未识别串 → not_judged（#316 方向：不可辨 多报不放过，附带命中=no）。
    AGREE_* 族按前缀识别（AGREE_CIRCUIT/AGREE_SENTINEL/AGREE_OPENEMS 同
    一行）；带尾注串（如 ``FAIL（fail_kind=gates…）``）按字面前缀识别。
    """
    normalized = _normalize(verdict)
    hit = _lookup(normalized)
    if hit is None:
        return {
            "input_verdict": (verdict.strip() if isinstance(verdict, str) else verdict),
            "vv_schema": VV_SCHEMA,
            "vv_status": VV_NOT_JUDGED,
            "vv_basis": "未识别 verdict（不在现行门枚举）",
            "vv_evidence_fields": [],
            "vv_notes": ["not judged：未识别串按缺失方向『多报』（#316）"],
        }
    key, _mode = hit
    status, basis, fields, notes = _VERDICT_MAP[key]
    out_notes = list(notes)
    if normalized != key:
        out_notes.append(f"按前缀识别：{verdict.strip()!r} → {key}")
    return {
        "input_verdict": verdict.strip() if isinstance(verdict, str) else verdict,
        "vv_schema": VV_SCHEMA,
        "vv_status": status,
        "vv_basis": basis,
        "vv_evidence_fields": list(fields),
        "vv_notes": out_notes,
    }


def apply_mapping(verdict_obj: dict[str, Any], key: str = "verdict") -> dict[str, Any]:
    """把 map_verdict 结果**并列注入** verdict dict 的副本（零原地改写）。

    返回新 dict：``{**verdict_obj, "verdict": 原值, "vv_*": 映射字段}``。
    输入对象内容逐键不变（深拷贝返回），已归档判读零改写（#325/#326）。
    """
    merged = deepcopy(verdict_obj)
    merged.update(map_verdict(str(verdict_obj.get(key, ""))))
    return merged


# ── u_num 保守上界（DP-12 §4 最小实现 + GCI 可选接口） ──────────────────────


def ladder_saturated(levels: list[float]) -> tuple[bool, dict[str, Any]]:
    """饱和合格级判定（``_ladder_saturated`` 同口径纯函数移植，#335① 勘误节）。

    相邻级差 ≤0.2dB 且末两级差 ≤0.1dB 且级数 ≥2。返回 ``(ok, detail)``；
    级数不足 → ``ok=False`` 且 detail 带原因（饱和性不可判定 ≠ 不饱和）。
    """
    vals = [float(v) for v in levels]
    if len(vals) < LADDER_MIN_LEVELS:
        return False, {"reason": f"阶梯不足 {LADDER_MIN_LEVELS} 级，饱和性不可判定"}
    adjacent = [abs(b - a) for a, b in itertools.pairwise(vals)]
    last_two = abs(vals[-1] - vals[-2])
    ok = max(adjacent) <= ADJACENT_TOL_DB and last_two <= LAST_TWO_TOL_DB
    return ok, {"adjacent_db": adjacent, "last_two_db": last_two,
                "rule": LADDER_SATURATION_RULE}


def u_num_from_ladder(levels: list[float], fs: float = FS_CONSERVATIVE) -> float | None:
    """u_num 保守上界：Fs·max|Δφ_ladder|（饱和合格级才可估，否则 None 不虚构）。

    合成回收钉（runs/df6_dp12vv/criteria.md §二）：[0.0625, 0.03125,
    0.015625] → u_num=1.25×0.03125=0.0390625（二进制可逐位）。
    """
    ok, _detail = ladder_saturated(levels)
    if not ok:
        return None
    vals = [float(v) for v in levels]
    max_adj = max(abs(b - a) for a, b in itertools.pairwise(vals))
    return fs * max_adj


def u_num_gci(phi1: float, phi2: float, phi3: float, r: float,
              fs: float = FS_CONSERVATIVE) -> float | None:
    """恒定细化比 r 的 Richardson/GCI 路径（可选增强接口，不强制）。

    phi1/phi2/phi3 = 同一标量在 细→粗 三级阶梯上的值（φ1 最细）；
    p=ln[(φ3−φ2)/(φ2−φ1)]/ln r；GCI=fs·|φ2−φ1|/(r^p−1)。
    不适用（r≤1、差零/异号即非单调收敛、差比≤1 即无正收敛观测——含值
    单调下降形态，保守起见不重排符号约定）→ None 不虚构；r 不恒定的
    阶梯用 :func:`u_num_from_ladder` 保守上界。
    """
    d21 = float(phi2) - float(phi1)
    d32 = float(phi3) - float(phi2)
    if not (float(r) > 1.0) or d21 == 0.0 or d32 == 0.0:
        return None
    ratio = d32 / d21
    if ratio <= 1.0:  # p≤0：无正收敛观测（含差比=1）
        return None
    return fs * abs(d21) / (ratio - 1.0)


# ── u_val 合成与判定（DP-12 §2 判定式） ────────────────────────────────────


def combine_uncertainty(u_num: float | None, u_input: float | None,
                        u_d: float | None) -> float | None:
    """u_val=√(u_num²+u_input²+u_D²)；任一分量 None → None（不虚构）。"""
    parts = [u_num, u_input, u_d]
    if any(p is None for p in parts):
        return None
    return math.sqrt(sum(float(p) ** 2 for p in parts))  # type: ignore[arg-type]


def validate_claim(
    e_s_minus_d: float,
    u_num: float | None,
    u_input: float | None = None,
    u_d: float | None = None,
    k: float = K_STANDARD,
    fallback_u_val: float | None = None,
    missing_k: float = K_CONSERVATIVE,
) -> dict[str, Any]:
    """V&V 20 判定：|E|≤U_val（E=S−D，U_val=k·u_val）——纯函数。

    分量缺失语义（预声明进 schema，runs/df6_dp12vv/criteria.md §二）：

    - 缺省（fallback_u_val=None）：任一分量 None → u_val=None 不虚构 →
      ``vv_status=validation_not_attempted``（UNDECIDED 同向）；
    - 调用方显式提供 ``fallback_u_val``（已声明的历史 U_val 近似，如现行
      gate_db）：按保守 ``missing_k``（缺省 3）消费，标记
      ``u_val_source=fallback_declared``。

    边界取 ≤（与现行 gate 口径一致，预声明；V&V 20 正文的严格 < 在浮点
    边界测度零）。返回字段：E/u_num/u_input/u_D/u_val/k/u_val_expanded/
    within/vv_status/vv_notes/u_val_source。
    """
    notes: list[str] = []
    missing = [name for name, v in
               (("u_num", u_num), ("u_input", u_input), ("u_D", u_d)) if v is None]
    if missing:
        if fallback_u_val is None:
            return {
                "E": float(e_s_minus_d), "u_num": u_num, "u_input": u_input,
                "u_D": u_d, "u_val": None, "u_val_source": None,
                "k": None, "u_val_expanded": None, "within": None,
                "vv_status": VV_VALIDATION_NOT_ATTEMPTED,
                "vv_notes": [f"u_val 分量缺失不虚构（{','.join(missing)}）"
                             "→ validation not attempted",
                             "如须降级消费须显式提供已声明 fallback_u_val（保守 k=3）"],
            }
        u_val = float(fallback_u_val)
        k_used = float(missing_k)
        notes.append(f"分量缺失不虚构（{','.join(missing)}）；"
                     f"消费已声明 fallback_u_val，保守 k={k_used:g}")
        source = "fallback_declared"
    else:
        u_val = combine_uncertainty(u_num, u_input, u_d)
        k_used = float(k)
        source = "components"
    expanded = k_used * u_val
    within = abs(float(e_s_minus_d)) <= expanded
    return {
        "E": float(e_s_minus_d), "u_num": u_num, "u_input": u_input, "u_D": u_d,
        "u_val": u_val, "u_val_source": source,
        "k": k_used, "u_val_expanded": expanded, "within": within,
        "vv_status": VV_VALIDATED if within else VV_NOT_VALIDATED,
        "vv_notes": notes,
    }


# ── 前置失效 / 判向 / PARTIAL 注记 ──────────────────────────────────────────


def passivity_preflight(passivity_max: float, limit: float = PASSIVITY_LIMIT) -> dict[str, Any]:
    """passivity 物理一致性约束 |S|≤1：违反=validation 前置失效。

    注意区分：各 criteria 的数据健全性带（如 ≤1.02 越界=数据坏）是另一
    语义，由 v2 YAML preflight 分开声明，不经本函数。
    """
    ok = float(passivity_max) <= float(limit)
    return {
        "passivity_max": float(passivity_max), "limit": float(limit), "ok": ok,
        "vv_status": None if ok else VV_PREFLIGHT_INVALID,
        "vv_note": (None if ok else
                    "passivity 违反（|S|>1 物理约束）→ validation 前置失效；"
                    "后续判读字段只作证据不产生 validated 结论"),
    }


def nearest_reference_decision(value: float, references: dict[str, float],
                               gate_db: float) -> dict[str, Any]:
    """最近参考判向（M1 口径的通用形态）：|value−ref|≤gate_db 站该参考边。

    两参考互斥时 0.5dB 窗天然不双命中；全不命中 → matched=None（调用方
    按现行门记 SPLIT，经 map_verdict → not_validated+model-form 注记）。
    无收敛合格解时**不得调用**本函数（触顶未收敛解不进判读，#335①）。
    """
    deltas = {name: abs(float(value) - float(ref)) for name, ref in references.items()}
    best = min(deltas, key=lambda name: deltas[name]) if deltas else None
    matched = best if (best is not None and deltas[best] <= float(gate_db)) else None
    return {
        "value": float(value), "gate_db": float(gate_db), "deltas": deltas,
        "matched": matched, "within_gate": matched is not None,
        "vv_status": VV_VALIDATED if matched is not None else VV_NOT_VALIDATED,
        "vv_notes": ([] if matched is not None else
                     ["两参考均未命中 → 现行 SPLIT；model-form 不可辨识（epistemic）"]),
    }


def conditional_validated(passed: list[str], exceeded: dict[str, str],
                          failed: list[str]) -> dict[str, Any]:
    """PARTIAL 注记语义：子集过 + 超限注记 → conditionally_validated。

    存在硬失败（failed 非空）→ not_validated（条件注记救不了硬门）。
    """
    if failed:
        return {"vv_status": VV_NOT_VALIDATED,
                "passed": list(passed), "exceeded": dict(exceeded),
                "failed": list(failed),
                "vv_notes": ["存在硬失败：conditional 注记不适用（如实 not validated）"]}
    return {"vv_status": VV_CONDITIONALLY_VALIDATED,
            "passed": list(passed), "exceeded": dict(exceeded), "failed": [],
            "vv_notes": [f"conditionally validated：超限注记 {sorted(exceeded) or '∅'}"
                         "（结论限注记范围内有效）"]}


def budget_conditional(ratio: float, limit: float = 1.5) -> dict[str, Any]:
    """超预算 PARTIAL 注记语义（哨 1.3× 实例口径：实测/预声明比 > limit 触发）。"""
    triggered = float(ratio) > float(limit)
    return {
        "budget_ratio": float(ratio), "budget_limit": float(limit),
        "triggered": triggered,
        "vv_status": VV_CONDITIONALLY_VALIDATED if triggered else None,
        "vv_note": (None if triggered else
                    f"预算比 {ratio:g}≤{limit:g}：不判超预算（无 PARTIAL 注记）"),
    }
