"""QM-3 判据 JSON Schema 化（round16 QM-3；P1/S）：criteria/v2 文档的
pydantic 合同——注册校验 + 重放前校验。

职责边界（#222 接地口径）：
- **只收敛已有词表，不发明新词表**——全部字段/枚举值逐一对照既有面：
  必备键 = ``core/recast.REQUIRED_TOP``（test_criteria_v2_pilot 同款注册
  合同）；decision_rule 形态 = recast 三种机器可重放 form + 既有骨架库的
  ``unmigrated_skeleton``；门算子 = ``recast._cmp`` 支持的四种比较串；
  V&V 状态值 = ``core/vv_mapping`` 常量族；status = 既有
  ``active_v2``/``skeleton_v2`` 两值。新词表 = 代码显式扩枚举，不静默放行。
- **重放机器不在本模块**——校验通过后仍由 ``core/recast.replay_one/_batch``
  重放（本模块是它的"重放前校验"前置，:func:`preflight_for_replay`）；
  两模块零相互 import（form 词表一致性由测试对拍钉住，防漂移）。
- 归档零改写（#325/#326）：本模块纯只读校验，任何加载/注册面都不回写。

诚实语义（#122/#316）：校验失败=显式 error 登记不静默跳；骨架档
（skeleton/ 子目录，status=skeleton_v2）按骨架合同校验（信封+骨架 form），
不冒充可重放判据。
"""
from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "CRITERIA_SCHEMA_ID",
    "CriteriaV2Document",
    "DecisionRuleForm",
    "GateOp",
    "VVStatus",
    "preflight_for_replay",
    "validate_criteria_document",
    "validate_registered_dir",
]

#: 判据 schema 标识（既有 registered yaml 的 schema 键值，逐字收敛）
CRITERIA_SCHEMA_ID = "criteria/v2"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
_QUANTITY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class StatusV2(str, Enum):
    """既有 status 词表（全库实测两值；新值=显式扩枚举）。"""

    ACTIVE = "active_v2"
    SKELETON = "skeleton_v2"


class GateOp(str, Enum):
    """门算子词表（recast._cmp 支持域，逐字收敛；≤/≥ 边界含、</> 严格）。"""

    LE = "<="
    GE = ">="
    LT = "<"
    GT = ">"


class DecisionRuleForm(str, Enum):
    """decision_rule 形态词表（recast 三种机器可重放 form + 骨架库既有
    form——一致性对 core/recast 的对拍钉在 test_criteria_schema）。"""

    MULTI_GATE = "multi_gate_all_pass"
    THRESHOLD = "threshold_gate"
    NEAREST_REF = "nearest_reference_gate"
    SKELETON = "unmigrated_skeleton"


class VVStatus(str, Enum):
    """V&V 状态词表（core/vv_mapping 常量族，逐字收敛）。"""

    VALIDATED = "validated"
    NOT_VALIDATED = "not_validated"
    CONDITIONALLY = "conditionally_validated"
    NOT_ATTEMPTED = "validation_not_attempted"
    NOT_JUDGED = "not_judged"
    OUT_OF_SCOPE = "out_of_scope"
    PREFLIGHT_INVALID = "preflight_invalid"


class _AllowExtra(BaseModel):
    """criteria/v2 文档面允许携带附加键（注释性/前向兼容键如 migration/
    runner 注记不拒收），已声明字段的类型/枚举合同照常强制。"""

    model_config = ConfigDict(extra="allow")


class ClaimV2(_AllowExtra):
    """claim 面：既有字段 quantity/template/f_ghz（f_ghz 骨架可 null）。"""

    quantity: str = Field(min_length=1)
    template: str | None = None
    f_ghz: float | None = None

    @field_validator("quantity")
    @classmethod
    def _quantity_snake(cls, v: str) -> str:
        if not _QUANTITY_RE.match(v):
            raise ValueError(
                f"claim.quantity 须为 snake_case 词（既有词表面）: {v!r}")
        return v


class GateSpec(_AllowExtra):
    """multi_gate_all_pass 单门：{op, threshold, evidence}（既有三键）。"""

    op: GateOp
    threshold: float
    evidence: str = Field(min_length=1)


class BudgetConditional(_AllowExtra):
    """预算条件注记：{op, ratio_limit, on_exceed}（哨 1.3× 口径既有面）。"""

    op: GateOp
    ratio_limit: float = Field(gt=0.0)
    on_exceed: str | None = None


class MultiGateRule(_AllowExtra):
    """form=multi_gate_all_pass（df5_c3fix_sentinel 同构）。"""

    form: Literal[DecisionRuleForm.MULTI_GATE]
    gates: dict[str, GateSpec]
    budget_conditional: BudgetConditional | None = None
    overall: str | None = None


class ThresholdRule(_AllowExtra):
    """form=threshold_gate（df6_dp10_scan 同构）。"""

    form: Literal[DecisionRuleForm.THRESHOLD]
    threshold: float
    comparison: GateOp
    on_fail: str | None = None
    overall: str | None = None


class NearestRefRule(_AllowExtra):
    """form=nearest_reference_gate（hfss_interdigital_check_m1 同构；
    references=参考名 → 冻结值；preflight 资格门=声明文本面）。"""

    form: Literal[DecisionRuleForm.NEAREST_REF]
    gate_db: float
    references: dict[str, float]
    preflight: dict[str, Any] | None = None


class SkeletonRule(_AllowExtra):
    """form=unmigrated_skeleton（skeleton/ 骨架库既有形态：gates 为原始
    条目列表，未迁移成机器门——如实登记为不可重放）。"""

    form: Literal[DecisionRuleForm.SKELETON]
    gates: list[dict[str, Any]] | None = None


DecisionRule = Annotated[
    MultiGateRule | ThresholdRule | NearestRefRule | SkeletonRule,
    Field(discriminator="form"),
]


class UValComponent(_AllowExtra):
    """u_val 分量：{source, rule}（source 既有词：ladder/holdout_rel/
    none_declared 等——自由词不枚举，缺 source 即拒）。"""

    source: str = Field(min_length=1)
    rule: str | None = None


class UValV2(_AllowExtra):
    """不确定度三分量声明（u_num/u_input/u_D；缺分量=拒收，不虚构）。"""

    u_num: UValComponent
    u_input: UValComponent
    u_D: UValComponent


class ProvenanceV2(_AllowExtra):
    """provenance 面：commit/devlog/referee_run/gate_db_legacy 等既有键
    （自由词文本，不枚举）。"""


class CriteriaV2Document(_AllowExtra):
    """criteria/v2 机器判据文档（REQUIRED_TOP 全键合同）。"""

    schema_id: Literal["criteria/v2"] = Field(alias="schema")
    criteria_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: StatusV2
    runner_binding: str = Field(min_length=1)
    claim: ClaimV2
    evidence_fields: list[str] = Field(min_length=1)
    u_val: UValV2
    decision_rule: DecisionRule
    verdict_map: dict[str, str]
    provenance: ProvenanceV2

    @field_validator("criteria_id")
    @classmethod
    def _id_charset(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(f"criteria_id 字符集越界: {v!r}")
        return v

    @field_validator("evidence_fields")
    @classmethod
    def _evidence_nonempty(cls, v: list[str]) -> list[str]:
        if any(not isinstance(e, str) or not e.strip() for e in v):
            raise ValueError("evidence_fields 须为非空字符串点路径")
        return v

    @field_validator("verdict_map")
    @classmethod
    def _vmap_values(cls, v: dict[str, str]) -> dict[str, str]:
        known = {m.value for m in VVStatus}
        for key, val in v.items():
            if str(val) not in known:
                raise ValueError(f"verdict_map[{key!r}]={val!r} 不在 V&V "
                                 f"状态词表 {sorted(known)}")
        return v


def validate_criteria_document(data: Any) -> CriteriaV2Document:
    """mapping → 校验过的 criteria/v2 文档（pydantic ValidationError 上抛）。"""
    if not isinstance(data, dict):
        raise ValueError("判据根必须是映射")
    return CriteriaV2Document.model_validate(data)


def _load_yaml(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """单文件加载（只读）；坏 YAML/非映射 → (None, error)。"""
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"YAML 解析失败: {exc}"
    if not isinstance(data, dict):
        return None, "判据根必须是映射"
    return data, None


def validate_registered_dir(criteria_dir: str | Path) -> dict[str, Any]:
    """注册面校验：顶层 *.yaml=active 全合同；skeleton/*.yaml=骨架合同
    （status 必须 skeleton_v2，不冒充可重放判据）。

    返回 {"n_active", "n_skeleton", "ok", "errors", "by_file"}；坏条目
    error 登记不静默跳（#316 方向）。
    """
    base = Path(criteria_dir)
    by_file: dict[str, Any] = {}
    errors: list[str] = []
    n_active = n_skeleton = 0

    for path in sorted(base.glob("*.yaml")):
        name = path.name
        data, err = _load_yaml(path)
        if err:
            errors.append(f"{name}: {err}")
            by_file[name] = {"ok": False, "errors": [err]}
            continue
        try:
            doc = validate_criteria_document(data)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            by_file[name] = {"ok": False, "errors": [str(exc)]}
            continue
        if doc.status == StatusV2.ACTIVE:
            n_active += 1
            by_file[name] = {"ok": True, "criteria_id": doc.criteria_id,
                             "form": doc.decision_rule.form.value}
        else:
            msg = (f"{name}: 顶层注册面出现非 active 档"
                   f"（status={doc.status.value}，骨架应入 skeleton）")
            errors.append(msg)
            by_file[name] = {"ok": False, "errors": [msg]}

    skel = base / "skeleton"
    if skel.is_dir():
        for path in sorted(skel.glob("*.yaml")):
            name = f"skeleton/{path.name}"
            data, err = _load_yaml(path)
            if err:
                errors.append(f"{name}: {err}")
                by_file[name] = {"ok": False, "errors": [err]}
                continue
            try:
                doc = validate_criteria_document(data)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                by_file[name] = {"ok": False, "errors": [str(exc)]}
                continue
            if doc.status == StatusV2.SKELETON:
                n_skeleton += 1
                by_file[name] = {"ok": True, "criteria_id": doc.criteria_id}
            else:
                msg = (f"{name}: skeleton/ 下 status 应为 skeleton_v2，"
                       f"得 {doc.status.value}")
                errors.append(msg)
                by_file[name] = {"ok": False, "errors": [msg]}

    return {"n_active": n_active, "n_skeleton": n_skeleton,
            "ok": not errors, "errors": errors, "by_file": by_file}


#: 重放出 verdict 的机器直放形态（recast.replay_one 实况：multi_gate/
#: threshold 二形出 PASS/FAIL；nearest_reference 走 bespoke 重放钉路径只出
#: not-judged——一致性对拍钉在 test_criteria_schema）
_REPLAYABLE_FORMS = frozenset({
    DecisionRuleForm.MULTI_GATE,
    DecisionRuleForm.THRESHOLD,
})


def preflight_for_replay(data: Any) -> dict[str, Any]:
    """重放前校验（QM-3"注册+重放前校验"的后半）：文档过全合同后，
    判定其能否交 ``core/recast.replay_one`` 机器直放出 verdict。

    - ``replayable=True`` ⇔ status=active_v2 且 decision_rule.form ∈
      {multi_gate_all_pass, threshold_gate}（recast 直放二形）；
    - nearest_reference_gate → replayable=False + reason（recast 口径：
      非机器直放，bespoke 重放钉路径，如 test_vv_recast）；
    - 骨架 form / 非 active / 合同不过 → ``replayable=False`` + 显式
      reason（不冒充，#122 如实）。

    返回 {"ok", "replayable", "form", "criteria_id", "reasons"}；
    合同不过时 ok=False，reasons 带校验错误摘要。
    """
    reasons: list[str] = []
    try:
        doc = validate_criteria_document(data)
    except Exception as exc:
        return {"ok": False, "replayable": False, "form": None,
                "criteria_id": (data or {}).get("criteria_id")
                if isinstance(data, dict) else None,
                "reasons": [str(exc)[:500]]}
    form = doc.decision_rule.form
    if doc.status != StatusV2.ACTIVE:
        reasons.append(f"status={doc.status.value} 非 active_v2（骨架档"
                       "不可重放，如实登记）")
    if form not in _REPLAYABLE_FORMS:
        reasons.append(f"form={form.value!r} 非机器可重放形态"
                       "（bespoke 重放钉路径）")
    return {"ok": True, "replayable": not reasons,
            "form": form.value, "criteria_id": doc.criteria_id,
            "reasons": reasons}
