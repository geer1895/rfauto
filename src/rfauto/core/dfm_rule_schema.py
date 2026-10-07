r"""PK-10 DFM 规则引擎统一——单一 YAML 规则 schema（规则 id/IPC 条款/
量纲/方向语义）。

规格：研究扩充 round14 §五 PK-10（P2/M）：
"五件套+fab_check 收敛单一 YAML 规则 schema（规则 id/IPC 条款/量纲/
方向语义）；标准锚=IPC-2221/2141A。勘误（防错）：IPC-2171 不存在
（检索仅命中印度消防标准），勿引入"。

**统一规则层，不重写引擎**（任务书口径）：既有执行引擎
（core/fab_check.check_geometry 判据、service/fab_service.
check_template_dfm、service/design_lint_service 五子检查）一律不改；
本模块提供三件事：

1. **规则 schema**（YAML 可承载的纯 dict + validator）——每条规则四轴：
   ``id``（唯一规则 id）、``ipc_ref``（标准锚：文档级+条款位）、
   ``quantity``（量纲）、``direction``（方向语义）；
2. **收敛映射**——既有 fab_check 违规码全集（VIOLATION_CODES，core 单源
   import）与 design_lint 五件套（constraints/fab/bounds/pdn/stub）到
   schema 规则族的覆盖登记（tests 与消费方钉住"全覆盖"）；
3. **纯求值器**——ruleset×measurements → 逐规则 pass/violation/unknown
   行 + verdict（语义与 design_lint 对齐：violation>0→issues、
   unknown>0→attention、否则 clean）。

方向语义（direction axis）
--------------------------
- ``min``：量测值 < value 即违规（下限规则，如最小线宽）；
- ``max``：量测值 > value 即违规（上限规则，如残桩谐振频率上限）；
- ``range``：量测值出 [lo, hi] 即违规（如板厚范围）；
- ``enum``：量测 token 不在白名单即违规（如表面处理枚举）；
- ``info``：信息性界，永不违规（如 Chu 信息界；verdict 不受影响）。

量纲（quantity axis）：``length_mm`` / ``copper_oz`` / ``ratio`` /
``impedance_ohm`` / ``frequency_ghz`` / ``token``——求值器对数值方向做
量纲标记检查（数值型测量拒绝 bool，df7+⑯），token 型只用于 enum。

IPC 锚诚实口径（#df6-⑨）：本模块只登记**文档级**锚
（IPC-2221A=Generic Standard on Printed Board Design、IPC-2141A=
controlled impedance 设计指南；规格点名）——**具体条款号未回原文逐位
核对，一律 ``UNVERIFIED_clause`` 不臆造**。IPC-2171 不存在（规格勘误），
本模块任何规则不得引用。

YAML 承载示例（核心零 IO——schema 是纯 mapping，YAML 读写由调用方
yaml.safe_load/safe_dump 承担；round-trip 由测试钉）::

    rules:
      - id: fab.trace.min_width@1oz
        direction: min
        quantity: length_mm
        value: 0.127
        ipc_ref: IPC-2221A
        ipc_clause: UNVERIFIED_clause
        severity: hard
        source: knowledge/fab_profiles/jlcpcb.yaml

纯函数零 IO；不进注册表、不定义 ``__all__``（PK-1 先例）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.fab_check import VIOLATION_CODES

# ─── schema 常量（文案即语义）────────────────────────────────────────────────

DIRECTION_MIN = "min"
DIRECTION_MAX = "max"
DIRECTION_RANGE = "range"
DIRECTION_ENUM = "enum"
DIRECTION_INFO = "info"
DIRECTIONS = (DIRECTION_MIN, DIRECTION_MAX, DIRECTION_RANGE, DIRECTION_ENUM,
              DIRECTION_INFO)

QUANTITY_LENGTH_MM = "length_mm"
QUANTITY_COPPER_OZ = "copper_oz"
QUANTITY_RATIO = "ratio"
QUANTITY_IMPEDANCE_OHM = "impedance_ohm"
QUANTITY_FREQUENCY_GHZ = "frequency_ghz"
QUANTITY_TOKEN = "token"
QUANTITIES = (QUANTITY_LENGTH_MM, QUANTITY_COPPER_OZ, QUANTITY_RATIO,
              QUANTITY_IMPEDANCE_OHM, QUANTITY_FREQUENCY_GHZ, QUANTITY_TOKEN)

SEVERITY_HARD = "hard"
SEVERITY_ADVISORY = "advisory"
SEVERITIES = (SEVERITY_HARD, SEVERITY_ADVISORY)

#: 文档级 IPC 锚（规格点名；条款级未核对一律 UNVERIFIED_clause）
IPC_REF_2221A = "IPC-2221A"
IPC_REF_2141A = "IPC-2141A"
IPC_CLAUSE_UNVERIFIED = "UNVERIFIED_clause"
_IPC_DOC_REFS = (IPC_REF_2221A, IPC_REF_2141A)

_NUMERIC_DIRECTIONS = (DIRECTION_MIN, DIRECTION_MAX, DIRECTION_RANGE)
_NUMERIC_QUANTITIES = (QUANTITY_LENGTH_MM, QUANTITY_COPPER_OZ, QUANTITY_RATIO,
                       QUANTITY_IMPEDANCE_OHM, QUANTITY_FREQUENCY_GHZ)


# ─── validator（纯函数）──────────────────────────────────────────────────────


def _finite_number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} 必须为数值（bool 拒收），得到 {value!r}")
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{where} 必须为有限数，得到 {value!r}")
    return v


def validate_rule(rule: dict[str, Any]) -> dict[str, Any]:
    """单条规则校验 → 归一化副本（非法即 ValueError）。

    归一化：min/max 的 value 转 float；range 转 (float lo, float hi)
    列表；enum 转 str 列表（非空）；info 的 value 可为 None。
    """
    if not isinstance(rule, dict):
        raise ValueError(f"规则必须是 dict，得到 {rule!r}")
    rid = rule.get("id")
    if not isinstance(rid, str) or not rid.strip():
        raise ValueError(f"规则 id 必须为非空 str，得到 {rid!r}")
    where = f"rule[{rid!r}]"
    direction = rule.get("direction")
    if direction not in DIRECTIONS:
        raise ValueError(f"{where}.direction 非法：{direction!r}（允许 {DIRECTIONS}）")
    quantity = rule.get("quantity")
    if quantity not in QUANTITIES:
        raise ValueError(f"{where}.quantity 非法：{quantity!r}（允许 {QUANTITIES}）")
    severity = rule.get("severity", SEVERITY_HARD)
    if severity not in SEVERITIES:
        raise ValueError(f"{where}.severity 非法：{severity!r}（允许 {SEVERITIES}）")
    ipc_ref = rule.get("ipc_ref")
    if not isinstance(ipc_ref, str) or not ipc_ref.strip():
        raise ValueError(f"{where}.ipc_ref 必须为非空 str（文档级锚或 "
                         f"'UNVERIFIED_doc_anchor'），得到 {ipc_ref!r}")
    clause = rule.get("ipc_clause", IPC_CLAUSE_UNVERIFIED)
    if not isinstance(clause, str) or not clause.strip():
        raise ValueError(f"{where}.ipc_clause 必须为非空 str（未核对条款写 "
                         f"'{IPC_CLAUSE_UNVERIFIED}'），得到 {clause!r}")
    if ipc_ref not in _IPC_DOC_REFS and ipc_ref != "UNVERIFIED_doc_anchor":
        raise ValueError(
            f"{where}.ipc_ref 只允许文档级锚 {_IPC_DOC_REFS} 或 "
            f"'UNVERIFIED_doc_anchor'，得到 {ipc_ref!r}；IPC-2171 不存在"
            "（规格勘误，勿引入）")
    source = rule.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f"{where}.source 必须为非空 str，得到 {source!r}")
    out: dict[str, Any] = {
        "id": rid, "direction": direction, "quantity": quantity,
        "severity": severity, "ipc_ref": ipc_ref, "ipc_clause": clause,
        "source": source,
        "notes": rule.get("notes", ""),
    }
    if direction in (DIRECTION_MIN, DIRECTION_MAX):
        out["value"] = _finite_number(rule.get("value"), f"{where}.value")
    elif direction == DIRECTION_RANGE:
        band = rule.get("value")
        if not isinstance(band, (list, tuple)) or len(band) != 2:
            raise ValueError(f"{where}.value 必须为 [lo, hi]，得到 {band!r}")
        lo = _finite_number(band[0], f"{where}.value[0]")
        hi = _finite_number(band[1], f"{where}.value[1]")
        if lo > hi:
            raise ValueError(f"{where}.value 须 lo<=hi，得到 {(lo, hi)}")
        out["value"] = [lo, hi]
    elif direction == DIRECTION_ENUM:
        tokens = rule.get("value")
        if (not isinstance(tokens, list) or not tokens
                or not all(isinstance(t, str) and t for t in tokens)):
            raise ValueError(
                f"{where}.value 必须为非空 str 列表（白名单），得到 {tokens!r}")
        out["value"] = list(tokens)
    else:  # info
        out["value"] = rule.get("value")
    if (direction in _NUMERIC_DIRECTIONS
            and quantity not in _NUMERIC_QUANTITIES):
        raise ValueError(
            f"{where}: 数值方向 {direction} 与量纲 {quantity} 不兼容"
            f"（数值方向要求 {_NUMERIC_QUANTITIES}）")
    return out


def validate_ruleset(rules: list[dict[str, Any]]) -> dict[str, Any]:
    """规则集校验（id 全局唯一）→ {n_rules, ids}。"""
    if not isinstance(rules, list) or not rules:
        raise ValueError("rules 必须为非空列表")
    seen: set[str] = set()
    for i, rule in enumerate(rules):
        normalized = validate_rule(rule)
        if normalized["id"] in seen:
            raise ValueError(f"规则 id 重复: {normalized['id']!r}（第 {i} 条）")
        seen.add(normalized["id"])
    return {"n_rules": len(rules), "ids": sorted(seen)}


# ─── 收敛映射：fab_check 违规码 + design_lint 五件套 → schema 规则族 ─────────


def fab_violation_code_coverage() -> dict[str, dict[str, Any]]:
    """core/fab_check.VIOLATION_CODES 全集 → schema 规则族（单源 import）。

    返回 {violation_code: {rule_family, direction(s), quantity, ipc_ref,
    ipc_clause, note}}；UNKNOWN/输入校验类如实标注 schema 外（如实不凑
    覆盖，#122）。tests 钉"码全集键相等"。
    """
    cov: dict[str, dict[str, Any]] = {
        "TRACE_BELOW_MIN": {
            "rule_family": "fab.trace.min_width",
            "directions": [DIRECTION_MIN], "quantity": QUANTITY_LENGTH_MM,
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED},
        "GAP_BELOW_MIN": {
            "rule_family": "fab.gap.min_spacing",
            "directions": [DIRECTION_MIN], "quantity": QUANTITY_LENGTH_MM,
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED},
        "COPPER_UNSUPPORTED": {
            "rule_family": "fab.copper_oz.supported",
            "directions": [DIRECTION_ENUM, DIRECTION_RANGE],
            "quantity": QUANTITY_COPPER_OZ,
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED},
        "MATERIAL_UNSUPPORTED": {
            "rule_family": "fab.material.supported",
            "directions": [DIRECTION_ENUM], "quantity": QUANTITY_TOKEN,
            "ipc_ref": "UNVERIFIED_doc_anchor",
            "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "note": "板材支持清单系厂商剖面（无 IPC 文档锚）"},
        "DRILL_BELOW_MIN": {
            "rule_family": "fab.drill.min_diameter",
            "directions": [DIRECTION_MIN], "quantity": QUANTITY_LENGTH_MM,
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED},
        "VIA_ANNULAR_RING_BELOW_MIN": {
            "rule_family": "fab.via_annular_ring.min",
            "directions": [DIRECTION_MIN], "quantity": QUANTITY_LENGTH_MM,
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED},
        "BOARD_THICKNESS_OUT_OF_RANGE": {
            "rule_family": "fab.board_thickness.range",
            "directions": [DIRECTION_RANGE], "quantity": QUANTITY_LENGTH_MM,
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED},
        "SURFACE_FINISH_UNSUPPORTED": {
            "rule_family": "fab.surface_finish.supported",
            "directions": [DIRECTION_ENUM], "quantity": QUANTITY_TOKEN,
            "ipc_ref": "UNVERIFIED_doc_anchor",
            "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "note": "表面处理枚举系厂商剖面（无 IPC 文档锚）"},
        "STUB_RES": {
            "rule_family": "fab.stub_resonance.max",
            "directions": [DIRECTION_MAX], "quantity": QUANTITY_FREQUENCY_GHZ,
            "ipc_ref": "UNVERIFIED_doc_anchor",
            "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "note": "残桩谐振频率须低于关注带下沿（check_stub_resonance；"
                    "无 IPC 文档锚，奈奎斯特判据）"},
        "BACKDRILL_OD": {
            "rule_family": "fab.backdrill.depth.max",
            "directions": [DIRECTION_MAX], "quantity": QUANTITY_LENGTH_MM,
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "note": "背钻深度 ≤ 过孔跨度（over-drill 钻穿对侧）"},
        "BACKDRILL_UNDER": {
            "rule_family": "fab.backdrill.residual.min",
            "directions": [DIRECTION_MIN], "quantity": QUANTITY_LENGTH_MM,
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "note": "残余桩/钻尖-信号层余量 ≥ 工艺最小间距"},
        "INVALID_GEOMETRY": {
            "rule_family": "input_validation（schema 外）",
            "directions": [], "quantity": None,
            "ipc_ref": "UNVERIFIED_doc_anchor",
            "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "note": "输入校验伪违规码（非制造规则）——如实标 schema 外"},
    }
    missing = [c for c in VIOLATION_CODES if c not in cov]
    extra = [c for c in cov if c not in VIOLATION_CODES]
    if missing or extra:
        raise ValueError(
            f"fab_check.VIOLATION_CODES 覆盖表失同步：缺 {missing}、多 {extra}"
            "（消费 fab_check 单源，须同步本表）")
    return cov


def lint_five_coverage() -> dict[str, dict[str, Any]]:
    """design_lint 五件套（constraints/fab/bounds/pdn/stub）→ schema 登记。

    覆盖语义：五件套中**阈值型判据**（fab/stub/pdn 的硬违规）映射到
    方向语义；非阈值判据（constraints 的 Z3 SAT、bounds 信息界）以
    ``info`` 家族登记（schema 承载其规则 id 与文档锚，不伪造方向语义）。
    集合一致性（五件套名全集）由 tests 双侧 import 钉住。
    """
    return {
        "constraints": {
            "family_id": "render.constraints.sat",
            "directions": [DIRECTION_INFO],
            "note": "Z3 渲染约束 SAT/UNSAT——声明式约束求解非阈值规则，"
                    "info 家族登记（violation 语义不适用）",
        },
        "fab": {
            "family_id": "fab.check_geometry",
            "directions": [DIRECTION_MIN, DIRECTION_RANGE, DIRECTION_ENUM],
            "note": "core/fab_check.check_geometry 判据族（全覆盖见 "
                    "fab_violation_code_coverage）",
        },
        "bounds": {
            "family_id": "antenna.bounds.info",
            "directions": [DIRECTION_INFO],
            "note": "Chu Q/方向性信息界（design_lint 明示不设门）",
        },
        "pdn": {
            "family_id": "pdn.gate.thresholds",
            "directions": [DIRECTION_MAX, DIRECTION_MIN, DIRECTION_INFO],
            "note": "PDN 腔模/避让/Z 裕量门：阈值型（方向语义承载）+"
                    "三值 UNKNOWN 归 info/unknown 行",
        },
        "stub": {
            "family_id": "fab.stub_resonance.max",
            "directions": [DIRECTION_MAX],
            "quantity": QUANTITY_FREQUENCY_GHZ,
            "note": "残桩谐振频率须低于关注带下沿（max 方向承载；"
                    "check_stub_resonance 判据式映射）",
        },
    }


# ─── fab 剖面 → 收敛规则集（既有 load_fab_profile 视图的规则化）──────────────


def ruleset_from_fab_profile_view(profile_view: dict[str, Any]) -> list[dict[str, Any]]:
    """fab 剖面 JSON 视图（service/fab_service.load_fab_profile 输出）→ 规则集。

    阈值面全部规则化（per-oz 线宽/间距、孔径、环宽、阻焊坝、板厚范围、
    铜厚档区间）；枚举面（板材/表面处理）走 enum 方向。来源逐条回指
    剖面文件（source=profile path），IPC 锚文档级（条款 UNVERIFIED）。
    """
    if profile_view.get("ok") is not True:
        raise ValueError(
            f"profile_view.ok 须为 True（errors={profile_view.get('errors')}），"
            "非法剖面不生成规则集")
    name = str(profile_view.get("name", "<anon>"))
    path = str(profile_view.get("path", name))
    rules: list[dict[str, Any]] = []
    for oz_key, rule in sorted(
            (profile_view.get("copper_rules") or {}).items()):
        rules.append({
            "id": f"fab.trace.min_width@{oz_key}oz",
            "direction": DIRECTION_MIN, "quantity": QUANTITY_LENGTH_MM,
            "value": float(rule["min_trace_mm"]),
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "severity": SEVERITY_HARD,
            "source": f"{path}#copper_rules[{oz_key}oz].min_trace_mm",
        })
        rules.append({
            "id": f"fab.gap.min_spacing@{oz_key}oz",
            "direction": DIRECTION_MIN, "quantity": QUANTITY_LENGTH_MM,
            "value": float(rule["min_gap_mm"]),
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "severity": SEVERITY_HARD,
            "source": f"{path}#copper_rules[{oz_key}oz].min_gap_mm",
        })
    oz_keys = sorted(float(k) for k in (profile_view.get("copper_rules") or {}))
    if oz_keys:
        rules.append({
            "id": "fab.copper_oz.supported",
            "direction": DIRECTION_ENUM, "quantity": QUANTITY_COPPER_OZ,
            "value": [f"{k:g}" for k in oz_keys],
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "severity": SEVERITY_HARD,
            "source": f"{path}#copper_rules 键集",
            "notes": "铜厚档枚举（oz 字符串 token）",
        })
    if profile_view.get("min_drill_mm") is not None:
        rules.append({
            "id": "fab.drill.min_diameter",
            "direction": DIRECTION_MIN, "quantity": QUANTITY_LENGTH_MM,
            "value": float(profile_view["min_drill_mm"]),
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "severity": SEVERITY_HARD, "source": f"{path}#min_drill_mm",
        })
    if profile_view.get("min_via_annular_ring_mm") is not None:
        rules.append({
            "id": "fab.via_annular_ring.min",
            "direction": DIRECTION_MIN, "quantity": QUANTITY_LENGTH_MM,
            "value": float(profile_view["min_via_annular_ring_mm"]),
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "severity": SEVERITY_HARD,
            "source": f"{path}#min_via_annular_ring_mm",
        })
    if profile_view.get("min_solder_mask_dam_mm") is not None:
        rules.append({
            "id": "fab.solder_mask_dam.min",
            "direction": DIRECTION_MIN, "quantity": QUANTITY_LENGTH_MM,
            "value": float(profile_view["min_solder_mask_dam_mm"]),
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "severity": SEVERITY_ADVISORY,
            "source": f"{path}#min_solder_mask_dam_mm",
        })
    board = profile_view.get("board_thickness_mm")
    if isinstance(board, (list, tuple)) and len(board) == 2:
        rules.append({
            "id": "fab.board_thickness.range",
            "direction": DIRECTION_RANGE, "quantity": QUANTITY_LENGTH_MM,
            "value": [float(board[0]), float(board[1])],
            "ipc_ref": IPC_REF_2221A, "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "severity": SEVERITY_HARD, "source": f"{path}#board_thickness_mm",
        })
    finishes = profile_view.get("surface_finishes")
    if isinstance(finishes, list) and finishes:
        rules.append({
            "id": "fab.surface_finish.supported",
            "direction": DIRECTION_ENUM, "quantity": QUANTITY_TOKEN,
            "value": [str(t) for t in finishes],
            "ipc_ref": "UNVERIFIED_doc_anchor",
            "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "severity": SEVERITY_HARD,
            "source": f"{path}#surface_finishes",
            "notes": "厂商枚举（无 IPC 文档锚，如实登记）",
        })
    materials = profile_view.get("supported_materials")
    if isinstance(materials, list) and materials:
        rules.append({
            "id": "fab.material.supported",
            "direction": DIRECTION_ENUM, "quantity": QUANTITY_TOKEN,
            "value": [str(t) for t in materials],
            "ipc_ref": "UNVERIFIED_doc_anchor",
            "ipc_clause": IPC_CLAUSE_UNVERIFIED,
            "severity": SEVERITY_HARD,
            "source": f"{path}#supported_materials",
            "notes": "厂商枚举（匹配语义见 core/fab_check 前缀/token 口径）",
        })
    if not rules:
        raise ValueError(f"剖面 {name!r} 未产出任何规则（剖面视图为空？）")
    validate_ruleset(rules)
    return rules


# ─── 纯求值器（ruleset × measurements）──────────────────────────────────────


def evaluate_ruleset(
    rules: list[dict[str, Any]],
    measurements: dict[str, Any],
) -> dict[str, Any]:
    """规则集求值：逐规则 pass/violation/unknown/info 行 + verdict。

    方向语义：min（<value 违规）/ max（>value 违规）/ range（出界违规）/
    enum（token 不在白名单违规）/ info（永不违规）。缺测/None → unknown
    （unknown 不算 fail，与 design_lint 语义一致）。数值方向测量拒收
    bool（df7+⑯）。verdict：violation>0→issues；unknown>0→attention；
    否则 clean。
    """
    if not isinstance(measurements, dict):
        raise ValueError("measurements 必须为 dict（rule_id → 量测值）")
    rows: list[dict[str, Any]] = []
    for raw in rules:
        rule = validate_rule(raw)
        rid = rule["id"]
        direction = rule["direction"]
        measured = measurements.get(rid)
        row: dict[str, Any] = {
            "rule_id": rid, "direction": direction, "quantity": rule["quantity"],
            "severity": rule["severity"], "ipc_ref": rule["ipc_ref"],
        }
        if direction == DIRECTION_INFO:
            row["status"] = "info"
            row["detail"] = "信息性规则（不设门）"
            rows.append(row)
            continue
        if measured is None:
            row["status"] = "unknown"
            row["detail"] = "缺测量（unknown 不算 fail）"
            rows.append(row)
            continue
        if direction == DIRECTION_ENUM:
            if not isinstance(measured, str):
                raise ValueError(f"{rid}: enum 测量必须为 str，得到 {measured!r}")
            violated = measured not in rule["value"]
        else:
            if isinstance(measured, bool):
                raise ValueError(f"{rid}: 数值测量拒收 bool（df7+⑯）")
            value = _finite_number(measured, f"measurement[{rid!r}]")
            if direction == DIRECTION_MIN:
                violated = value < rule["value"]
            elif direction == DIRECTION_MAX:
                violated = value > rule["value"]
            else:  # range
                lo, hi = rule["value"]
                violated = value < lo or value > hi
        row["status"] = "violation" if violated else "pass"
        row["detail"] = (
            f"measured={measured!r} vs {direction}{rule['value']!r}")
        rows.append(row)
    summary: dict[str, int] = {"pass": 0, "violation": 0, "unknown": 0,
                               "info": 0}
    for row in rows:
        summary[row["status"]] += 1
    if summary["violation"] > 0:
        verdict = "issues"
    elif summary["unknown"] > 0:
        verdict = "attention"
    else:
        verdict = "clean"
    return {"ruleset_size": len(rows), "rows": rows, "summary": summary,
            "verdict": verdict}
